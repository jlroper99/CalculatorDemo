"""HTTP API and web UI for Recipe Vault."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai
from .categorize import categorize
from .db import INBOX_STATUSES, Database
from .extract import Fetcher
from .importers import is_saveable, normalize_url, parse_file, platform_for
from .models import CATEGORY_KINDS, Categories, RecipeIn, RecipePatch, SavedItem
from .pipeline import NEEDS_REVIEW_TAG, Worker, import_text, process_item

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_DB = os.environ.get("RECIPE_VAULT_DB", str(Path(__file__).resolve().parent.parent / "data" / "recipes.db"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class UrlImport(BaseModel):
    url: str
    collection: Optional[str] = None


class TextImport(BaseModel):
    text: str
    url: Optional[str] = None
    collection: Optional[str] = None


class RetryRequest(BaseModel):
    statuses: list[str] = ["failed"]


def create_app(db_path: str = DEFAULT_DB, fetcher: Optional[Fetcher] = None) -> FastAPI:
    db = Database(db_path)
    db.reset_items(["processing"])  # anything interrupted by a restart goes back in the queue
    fetcher = fetcher or Fetcher()
    worker = Worker(db, fetcher)

    app = FastAPI(title="Recipe Vault", version="1.0")
    app.state.db = db
    app.state.worker = worker

    def auto_categories(recipe: RecipeIn) -> Categories:
        guessed = None
        if ai.enabled():
            try:
                guessed = ai.categorize(recipe.title, recipe.description, recipe.ingredients, recipe.directions)
            except ai.AIUnavailable:
                guessed = None
        offline = categorize(recipe.title, recipe.description, recipe.ingredients,
                             recipe.directions, recipe.total_time)
        guessed = guessed.merge(Categories(tag=offline.tag)) if guessed else offline
        # What the person chose themselves always stays.
        return recipe.categories.merge(guessed)

    # ------------------------------------------------------------- recipes

    @app.get("/api/recipes")
    def search_recipes(
        q: str = "",
        meal_type: list[str] = Query(default=[]),
        course: list[str] = Query(default=[]),
        cuisine: list[str] = Query(default=[]),
        diet: list[str] = Query(default=[]),
        main_ingredient: list[str] = Query(default=[]),
        method: list[str] = Query(default=[]),
        collection: list[str] = Query(default=[]),
        tag: list[str] = Query(default=[]),
        favorite: bool = False,
        min_rating: int = 0,
        max_time: Optional[int] = None,
        platform: Optional[str] = None,
        sort: str = "relevance",
        limit: int = Query(default=60, le=500),
        offset: int = 0,
    ):
        filters = {
            "meal_type": meal_type, "course": course, "cuisine": cuisine, "diet": diet,
            "main_ingredient": main_ingredient, "method": method, "collection": collection, "tag": tag,
        }
        return db.search(q, filters, favorite, min_rating, max_time, platform, sort, limit, offset)

    @app.get("/api/suggest")
    def suggest(q: str = ""):
        return db.suggest(q) if q.strip() else []

    @app.get("/api/recipes/{recipe_id}")
    def get_recipe(recipe_id: int):
        recipe = db.get_recipe(recipe_id)
        if recipe is None:
            raise HTTPException(404, "Recipe not found")
        return recipe

    @app.post("/api/recipes", status_code=201)
    def create_recipe(recipe: RecipeIn):
        if recipe.source_url and db.find_recipe_by_url(recipe.source_url):
            raise HTTPException(409, "A recipe from that link is already saved")
        if recipe.auto_categorize:
            recipe.categories = auto_categories(recipe)
        recipe.source_platform = recipe.source_platform or (
            platform_for(recipe.source_url) if recipe.source_url else "manual")
        return db.get_recipe(db.add_recipe(recipe))

    @app.patch("/api/recipes/{recipe_id}")
    def update_recipe(recipe_id: int, patch: RecipePatch):
        if not db.update_recipe(recipe_id, patch):
            raise HTTPException(404, "Recipe not found")
        return db.get_recipe(recipe_id)

    @app.delete("/api/recipes/{recipe_id}", status_code=204)
    def delete_recipe(recipe_id: int):
        if not db.delete_recipe(recipe_id):
            raise HTTPException(404, "Recipe not found")

    @app.post("/api/recipes/{recipe_id}/recategorize")
    def recategorize(recipe_id: int):
        current = db.get_recipe(recipe_id)
        if current is None:
            raise HTTPException(404, "Recipe not found")
        keep = Categories(collection=current["categories"]["collection"],
                          tag=[t for t in current["categories"]["tag"] if t != NEEDS_REVIEW_TAG])
        recipe = RecipeIn(**{**current, "categories": keep})
        db.update_recipe(recipe_id, RecipePatch(categories=auto_categories(recipe)))
        return db.get_recipe(recipe_id)

    @app.get("/api/categories")
    def all_categories():
        return db.search("", limit=1)["facets"]

    # -------------------------------------------------------------- import

    @app.post("/api/import/file")
    async def import_files(
        files: list[UploadFile] = File(...),
        platform: Optional[str] = Form(default=None),
        start: bool = Form(default=True),
    ):
        items: list[SavedItem] = []
        per_file = []
        for upload in files:
            content = await upload.read()
            try:
                found = parse_file(upload.filename or "upload", content, platform or None)
            except Exception as exc:  # corrupt zip, unreadable file
                per_file.append({"file": upload.filename, "error": str(exc), "found": 0})
                continue
            per_file.append({"file": upload.filename, "found": len(found)})
            items += found
        result = db.add_saved_items(items)
        if start and result["added"]:
            worker.start()
        return {**result, "files": per_file, "processing": worker.running}

    @app.post("/api/import/url")
    def import_url(body: UrlImport):
        url = normalize_url(body.url)
        if not url.startswith("http") or not is_saveable(url):
            raise HTTPException(400, "That doesn't look like a link to a post or recipe page")
        existing = db.find_recipe_by_url(url)
        if existing:
            return {"status": "exists", "recipe_id": existing}
        db.add_saved_items([SavedItem(platform=platform_for(url), url=url, collection=body.collection)])
        item = db.get_saved_item_by_url(url)
        if item["status"] != "pending":
            db.update_saved_item(item["id"], status="pending")
        status = process_item(db, {**item, "collection": body.collection or item["collection"]}, fetcher)
        item = db.get_saved_item(item["id"])
        return {"status": status, "recipe_id": item["recipe_id"], "item_id": item["id"], "error": item["error"]}

    @app.post("/api/import/text", status_code=201)
    def import_pasted(body: TextImport):
        if not body.text.strip():
            raise HTTPException(400, "Paste the recipe or caption text first")
        url = normalize_url(body.url) if body.url else None
        platform = platform_for(url) if url else "manual"
        recipe_id, status = import_text(db, body.text, url, platform, body.collection)
        return {"status": status, "recipe": db.get_recipe(recipe_id)}

    # --------------------------------------------------------------- inbox

    @app.get("/api/inbox")
    def inbox(status: Optional[str] = None, limit: int = 200, offset: int = 0):
        if status and status not in INBOX_STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(INBOX_STATUSES)}")
        return db.list_saved_items(status, limit, offset)

    @app.get("/api/inbox/status")
    def inbox_status():
        return {
            "counts": db.inbox_counts(),
            "running": worker.running,
            "current": worker.current,
            "ai_enabled": ai.enabled(),
            "model": ai.MODEL if ai.enabled() else None,
        }

    @app.post("/api/inbox/process")
    def start_processing():
        worker.start()
        return {"running": worker.running}

    @app.post("/api/inbox/stop")
    def stop_processing():
        worker.stop()
        return {"running": False}

    @app.post("/api/inbox/retry")
    def retry(body: RetryRequest):
        count = db.reset_items(body.statuses)
        if count:
            worker.start()
        return {"reset": count}

    @app.post("/api/inbox/{item_id}/skip")
    def skip(item_id: int):
        if not db.get_saved_item(item_id):
            raise HTTPException(404, "Item not found")
        db.update_saved_item(item_id, status="skipped")
        return db.get_saved_item(item_id)

    @app.post("/api/inbox/{item_id}/text")
    def item_text(item_id: int, body: TextImport):
        item = db.get_saved_item(item_id)
        if not item:
            raise HTTPException(404, "Item not found")
        if not body.text.strip():
            raise HTTPException(400, "Paste the caption text first")
        recipe_id, status = import_text(db, body.text, item["url"], item["platform"],
                                        body.collection or item["collection"])
        db.update_saved_item(item_id, status="imported", recipe_id=recipe_id, caption=body.text, error=None)
        return {"status": status, "recipe": db.get_recipe(recipe_id)}

    # -------------------------------------------------------------- backup

    @app.get("/api/export")
    def export():
        return JSONResponse(
            {"version": 1, "recipes": db.all_recipes()},
            headers={"Content-Disposition": 'attachment; filename="recipe-vault-export.json"'},
        )

    @app.post("/api/import/backup")
    async def restore(file: UploadFile = File(...)):
        try:
            data = json.loads(await file.read())
        except json.JSONDecodeError:
            raise HTTPException(400, "That file isn't a Recipe Vault export")
        added = skipped = 0
        for raw in data.get("recipes", []):
            recipe = RecipeIn(**{k: v for k, v in raw.items() if k in RecipeIn.model_fields})
            if recipe.source_url and db.find_recipe_by_url(recipe.source_url):
                skipped += 1
                continue
            db.add_recipe(recipe)
            added += 1
        return {"added": added, "skipped": skipped}

    @app.get("/api/meta")
    def meta():
        return {"category_kinds": CATEGORY_KINDS, **db.stats(), "ai_enabled": ai.enabled()}

    # ------------------------------------------------------------------ UI

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app

