"""Turns saved items in the inbox into recipes, one at a time in the background."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

from . import ai
from .categorize import categorize, hashtags
from .db import Database
from .extract import Extracted, Fetcher, caption_links, parse_caption
from .models import Categories, RecipeIn

log = logging.getLogger(__name__)

# Be polite to Instagram/Facebook: they rate-limit anonymous requests quickly.
SOCIAL_DELAY_SECONDS = 2.0
NEEDS_REVIEW_TAG = "Needs Review"
RECIPE_WORDS = re.compile(
    r"\b(recipe|ingredients?|tbsp|tsp|tablespoons?|teaspoons?|cups?|bake|baked|simmer|saut[eé]|oven|preheat"
    r"|stir|whisk|marinate|servings?)\b", re.I)


def _merge_text_into(base: Extracted, caption: Extracted) -> Extracted:
    for attr in ("title", "description", "servings", "prep_time", "cook_time", "total_time", "author", "image_url"):
        if not getattr(base, attr) and getattr(caption, attr):
            setattr(base, attr, getattr(caption, attr))
    if not base.ingredients:
        base.ingredients = caption.ingredients
    if not base.directions:
        base.directions = caption.directions
    base.raw_text = base.raw_text or caption.raw_text
    return base


def build_recipe(
    ex: Extracted,
    *,
    platform: Optional[str],
    url: Optional[str],
    author: Optional[str] = None,
    collection: Optional[str] = None,
    saved_at: Optional[str] = None,
    use_ai: bool = True,
) -> tuple[Optional[RecipeIn], str]:
    """Return (recipe, status). Status is imported, needs_review, or not_recipe."""
    notes = ""
    ai_categories: Optional[Categories] = None
    status = "imported"

    if not ex.looks_complete and ex.raw_text and use_ai and ai.enabled():
        try:
            parsed = ai.extract_recipe(ex.raw_text, context=f"Post by: {author}" if author else "")
        except ai.AIUnavailable as exc:
            log.warning("AI disabled for this run: %s", exc)
            parsed = None
        if parsed:
            ex.title = parsed.title or ex.title
            ex.description = parsed.description or ex.description
            ex.ingredients = parsed.ingredients or ex.ingredients
            ex.directions = parsed.directions or ex.directions
            ex.servings = parsed.servings or ex.servings
            ex.prep_time = parsed.prep_time or ex.prep_time
            ex.cook_time = parsed.cook_time or ex.cook_time
            ex.total_time = parsed.total_time or ex.total_time
            notes = parsed.notes
            ai_categories = Categories(**parsed.categories.model_dump())
            if not parsed.is_recipe:
                status = "not_recipe"
    elif ex.looks_complete and use_ai and ai.enabled():
        try:
            ai_categories = ai.categorize(ex.title, ex.description, ex.ingredients, ex.directions)
        except ai.AIUnavailable:
            ai_categories = None

    title = ex.title or (f"Saved post by {author}" if author else "Saved recipe")
    cats = categorize(
        title, ex.description + " " + ex.raw_text, ex.ingredients, ex.directions, ex.total_time, ex.hints
    )
    if status == "imported" and not ex.looks_complete:
        # Half a recipe, or a food post worth a look, goes to review; a beach
        # photo someone saved does not.
        foodish = (ex.ingredients or ex.directions or RECIPE_WORDS.search(ex.raw_text + " " + title)
                   or cats.meal_type or cats.main_ingredient)
        status = "needs_review" if foodish else "not_recipe"
    if ai_categories and not ai_categories.is_empty():
        # Claude's judgement wins on the main dimensions; keep offline tags too.
        cats = Categories(**{**ai_categories.model_dump(), "tag": ai_categories.tag}).merge(
            Categories(tag=cats.tag)
        )
    cats.tag = list(dict.fromkeys(cats.tag + [t for t in hashtags(ex.raw_text) if t not in cats.tag]))[:20]
    if collection:
        cats.collection = [collection]
    if status == "needs_review":
        cats.tag = [NEEDS_REVIEW_TAG] + cats.tag

    description = ex.description
    if not ex.looks_complete and ex.raw_text and ex.raw_text not in description:
        # Keep the original caption visible so nothing is lost while reviewing.
        description = (description + "\n\n" if description else "") + ex.raw_text
    recipe = RecipeIn(
        title=title[:200],
        description=description.strip(),
        source_url=url,
        source_platform=platform,
        author=ex.author or author,
        image_url=ex.image_url,
        servings=ex.servings,
        prep_time=ex.prep_time,
        cook_time=ex.cook_time,
        total_time=ex.total_time,
        ingredients=ex.ingredients,
        directions=ex.directions,
        nutrition=ex.nutrition,
        notes=notes,
        categories=cats,
        saved_at=saved_at,
    )
    return recipe, status


def extract_item(item: dict, fetcher: Fetcher) -> Optional[Extracted]:
    """Fetch whatever we can for a saved item. None means nothing was readable."""
    url, platform = item["url"], item["platform"]
    ex: Optional[Extracted] = None
    if "instagram.com" in url:
        ex = fetcher.instagram_post(url)
    elif "facebook.com" in url or "fb.watch" in url:
        ex = fetcher.facebook_post(url)
    else:
        ex = fetcher.web_page(url)

    caption_text = (ex.raw_text if ex else "") or item.get("caption") or ""
    if item.get("caption") and ex and item["caption"] not in ex.raw_text:
        caption_text = item["caption"] + "\n\n" + (ex.raw_text or "")

    # Structured data on an outside page beats any caption, so follow links.
    if not (ex and ex.structured):
        for link in caption_links(caption_text)[:2]:
            linked = fetcher.web_page(link)
            if linked and linked.structured:
                linked.raw_text = caption_text
                linked.author = linked.author or (ex.author if ex else None)
                return linked

    if caption_text and not (ex and ex.structured):
        parsed = parse_caption(caption_text)
        if ex is None:
            ex = parsed
        else:
            ex.raw_text = caption_text
            ex = _merge_text_into(ex, parsed)
            if parsed.title and (not ex.title or ex.title.lower().endswith("on instagram")):
                ex.title = parsed.title
            if parsed.ingredients:
                ex.ingredients, ex.directions = parsed.ingredients, parsed.directions or ex.directions
    return ex


def process_item(db: Database, item: dict, fetcher: Fetcher) -> str:
    existing = db.find_recipe_by_url(item["url"])
    if existing:
        db.update_saved_item(item["id"], status="imported", recipe_id=existing, error=None)
        return "imported"
    try:
        ex = extract_item(item, fetcher)
    except Exception as exc:  # one bad page must not stop the whole import
        log.exception("extract failed for %s", item["url"])
        db.update_saved_item(item["id"], status="failed", error=f"Error reading post: {exc}")
        return "failed"
    if ex is None:
        if item["url"].startswith(("https://www.instagram.com", "https://www.facebook.com")):
            error = ("Couldn't read this post (it may be private or need a login). "
                     "Open it, copy the caption, and paste it here.")
        else:
            error = "Couldn't load this page. Open it, copy the recipe, and paste it here."
        db.update_saved_item(item["id"], status="failed", error=error)
        return "failed"
    recipe, status = build_recipe(
        ex, platform=item["platform"], url=item["url"], author=item.get("author"),
        collection=item.get("collection"), saved_at=item.get("saved_at"),
    )
    if status == "not_recipe":
        # Keep the caption on the inbox item so it can still be turned into a recipe by hand.
        db.update_saved_item(item["id"], status="not_recipe", caption=ex.raw_text or item.get("caption"),
                             error="No recipe found in this post.")
        return status
    recipe_id = db.add_recipe(recipe)
    db.update_saved_item(item["id"], status=status, recipe_id=recipe_id,
                         caption=item.get("caption") or ex.raw_text or None, error=None)
    return status


def import_text(db: Database, text: str, url: Optional[str] = None, platform: str = "manual",
                collection: Optional[str] = None, use_ai: bool = True) -> tuple[int, str]:
    """Create a recipe from pasted caption/recipe text."""
    ex = parse_caption(text)
    recipe, status = build_recipe(ex, platform=platform, url=url, collection=collection, use_ai=use_ai)
    existing = db.find_recipe_by_url(url) if url else None
    if existing:
        db.delete_recipe(existing)  # pasted text replaces a failed/partial import
    return db.add_recipe(recipe), status


class Worker:
    """Single background thread that drains the pending queue."""

    def __init__(self, db: Database, fetcher: Optional[Fetcher] = None):
        self.db = db
        self.fetcher = fetcher or Fetcher()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.current: Optional[str] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="import-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self.db.next_pending_item()
            if item is None:
                break
            self.current = item["url"]
            try:
                status = process_item(self.db, item, self.fetcher)
            except Exception as exc:  # keep draining the queue no matter what
                log.exception("processing failed for %s", item["url"])
                self.db.update_saved_item(item["id"], status="failed", error=f"Unexpected error: {exc}")
                status = "failed"
            log.info("%s -> %s", item["url"], status)
            if item["platform"] in ("instagram", "facebook"):
                self._stop.wait(SOCIAL_DELAY_SECONDS)
        self.current = None
