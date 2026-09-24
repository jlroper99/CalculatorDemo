"""SQLite storage with an FTS5 full-text index for search."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import CATEGORY_KINDS, Categories, RecipeIn, RecipePatch, SavedItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    source_url      TEXT,
    source_platform TEXT,
    author          TEXT,
    image_url       TEXT,
    servings        TEXT,
    prep_time       INTEGER,
    cook_time       INTEGER,
    total_time      INTEGER,
    ingredients     TEXT NOT NULL DEFAULT '[]',
    directions      TEXT NOT NULL DEFAULT '[]',
    notes           TEXT NOT NULL DEFAULT '',
    nutrition       TEXT NOT NULL DEFAULT '{}',
    rating          INTEGER NOT NULL DEFAULT 0,
    favorite        INTEGER NOT NULL DEFAULT 0,
    saved_at        TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS recipes_source_url ON recipes(source_url)
    WHERE source_url IS NOT NULL;

CREATE TABLE IF NOT EXISTS recipe_tags (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    kind      TEXT NOT NULL,
    value     TEXT NOT NULL,
    PRIMARY KEY (recipe_id, kind, value)
);
CREATE INDEX IF NOT EXISTS recipe_tags_kind_value ON recipe_tags(kind, value);

CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
    title, description, ingredients, directions, tags, author, notes,
    tokenize = 'porter unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS saved_items (
    id         INTEGER PRIMARY KEY,
    platform   TEXT NOT NULL,
    url        TEXT NOT NULL UNIQUE,
    author     TEXT,
    title      TEXT,
    caption    TEXT,
    collection TEXT,
    saved_at   TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    error      TEXT,
    recipe_id  INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS saved_items_status ON saved_items(status);
"""

# Search results are ranked with bm25; title and ingredient hits count most.
BM25_WEIGHTS = "10.0, 2.0, 5.0, 1.0, 4.0, 2.0, 1.0"

SORTS = {
    "relevance": None,
    "newest": "r.created_at DESC",
    "saved": "COALESCE(r.saved_at, r.created_at) DESC",
    "title": "r.title COLLATE NOCASE ASC",
    "rating": "r.rating DESC, r.title COLLATE NOCASE",
    "quickest": "COALESCE(r.total_time, r.prep_time + r.cook_time, 100000) ASC",
}

INBOX_STATUSES = ("pending", "processing", "needs_review", "imported", "not_recipe", "failed", "skipped")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fts_terms(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def build_match(query: str) -> Optional[str]:
    """Turn free text into a safe FTS5 MATCH expression.

    Every word must match (AND); the final word is a prefix so results update
    while typing. Quoted phrases are kept together, a leading '-' excludes a
    word, and `ingredient:x` / `title:x` restrict a word to one column.
    """
    parts: list[str] = []
    negatives: list[str] = []
    tokens = re.findall(r'-?(?:\w+:)?"[^"]*"|\S+', query)
    for i, token in enumerate(tokens):
        negate = token.startswith("-") and len(token) > 1
        if negate:
            token = token[1:]
        column = None
        m = re.match(r"(ingredients?|title|tags?|author|directions?):(.+)", token, re.I)
        if m:
            column = {"ingredient": "ingredients", "tag": "tags", "direction": "directions"}.get(
                m.group(1).lower(), m.group(1).lower()
            )
            token = m.group(2)
        is_phrase = token.startswith('"')
        words = _fts_terms(token)
        if not words:
            continue
        if is_phrase or len(words) > 1:
            expr = '"' + " ".join(words) + '"'
        else:
            expr = f'"{words[0]}"'
            if i == len(tokens) - 1 and not negate:
                expr += "*"
        if column:
            expr = f"{column} : {expr}"
        (negatives if negate else parts).append(expr)
    if not parts:
        return None
    match = " AND ".join(parts)
    for neg in negatives:
        match += f" NOT {neg}"
    return match


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ recipes

    def _write_tags(self, recipe_id: int, categories: Categories) -> None:
        self._conn.execute("DELETE FROM recipe_tags WHERE recipe_id = ?", (recipe_id,))
        rows = [
            (recipe_id, kind, value)
            for kind in CATEGORY_KINDS
            for value in getattr(categories, kind)
            if value.strip()
        ]
        self._conn.executemany("INSERT OR IGNORE INTO recipe_tags VALUES (?, ?, ?)", rows)

    def _reindex(self, recipe_id: int) -> None:
        row = self._conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        self._conn.execute("DELETE FROM recipes_fts WHERE rowid = ?", (recipe_id,))
        if row is None:
            return
        tags = [r["value"] for r in self._conn.execute(
            "SELECT value FROM recipe_tags WHERE recipe_id = ?", (recipe_id,))]
        self._conn.execute(
            "INSERT INTO recipes_fts(rowid, title, description, ingredients, directions, tags, author, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                recipe_id,
                row["title"],
                row["description"],
                "\n".join(json.loads(row["ingredients"])),
                "\n".join(json.loads(row["directions"])),
                " | ".join(tags),
                row["author"] or "",
                row["notes"],
            ),
        )

    def find_recipe_by_url(self, url: str) -> Optional[int]:
        row = self._conn.execute("SELECT id FROM recipes WHERE source_url = ?", (url,)).fetchone()
        return row["id"] if row else None

    def add_recipe(self, recipe: RecipeIn) -> int:
        now = _now()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """INSERT INTO recipes (title, description, source_url, source_platform, author,
                   image_url, servings, prep_time, cook_time, total_time, ingredients, directions,
                   notes, nutrition, rating, favorite, saved_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recipe.title.strip() or "Untitled recipe",
                    recipe.description,
                    recipe.source_url,
                    recipe.source_platform,
                    recipe.author,
                    recipe.image_url,
                    recipe.servings,
                    recipe.prep_time,
                    recipe.cook_time,
                    recipe.total_time,
                    json.dumps(recipe.ingredients),
                    json.dumps(recipe.directions),
                    recipe.notes,
                    json.dumps(recipe.nutrition),
                    recipe.rating,
                    int(recipe.favorite),
                    recipe.saved_at,
                    now,
                    now,
                ),
            )
            recipe_id = cur.lastrowid
            self._write_tags(recipe_id, recipe.categories)
            self._reindex(recipe_id)
        return recipe_id

    def update_recipe(self, recipe_id: int, patch: RecipePatch) -> bool:
        fields = patch.model_dump(exclude_unset=True)
        categories = fields.pop("categories", None)
        with self._lock, self._conn:
            if not self._conn.execute("SELECT 1 FROM recipes WHERE id = ?", (recipe_id,)).fetchone():
                return False
            for key in ("ingredients", "directions", "nutrition"):
                if key in fields:
                    fields[key] = json.dumps(fields[key])
            if "favorite" in fields:
                fields["favorite"] = int(fields["favorite"])
            fields["updated_at"] = _now()
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self._conn.execute(
                f"UPDATE recipes SET {assignments} WHERE id = ?", (*fields.values(), recipe_id)
            )
            if categories is not None:
                self._write_tags(recipe_id, Categories(**categories))
            self._reindex(recipe_id)
        return True

    def delete_recipe(self, recipe_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            self._conn.execute("DELETE FROM recipes_fts WHERE rowid = ?", (recipe_id,))
        return cur.rowcount > 0

    def _categories_for(self, ids: Iterable[int]) -> dict[int, Categories]:
        ids = list(ids)
        result: dict[int, dict[str, list[str]]] = {i: {k: [] for k in CATEGORY_KINDS} for i in ids}
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        for row in self._conn.execute(
            f"SELECT recipe_id, kind, value FROM recipe_tags WHERE recipe_id IN ({marks})"
            " ORDER BY value COLLATE NOCASE", ids
        ):
            if row["kind"] in result[row["recipe_id"]]:
                result[row["recipe_id"]][row["kind"]].append(row["value"])
        return {i: Categories(**c) for i, c in result.items()}

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, categories: Categories) -> dict[str, Any]:
        data = dict(row)
        data["ingredients"] = json.loads(data["ingredients"])
        data["directions"] = json.loads(data["directions"])
        data["nutrition"] = json.loads(data["nutrition"])
        data["favorite"] = bool(data["favorite"])
        data["categories"] = categories.model_dump()
        data.pop("snippet", None)
        return data

    def get_recipe(self, recipe_id: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row, self._categories_for([recipe_id])[recipe_id])

    def all_recipes(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM recipes ORDER BY id").fetchall()
        cats = self._categories_for(r["id"] for r in rows)
        return [self._row_to_dict(r, cats[r["id"]]) for r in rows]

    def search(
        self,
        q: str = "",
        filters: Optional[dict[str, list[str]]] = None,
        favorite: bool = False,
        min_rating: int = 0,
        max_time: Optional[int] = None,
        platform: Optional[str] = None,
        sort: str = "relevance",
        limit: int = 60,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Full-text search plus facet filtering. Returns results and facet counts."""
        where: list[str] = []
        params: list[Any] = []
        joins = ""
        match = build_match(q) if q.strip() else None
        if match:
            joins = "JOIN recipes_fts f ON f.rowid = r.id"
            where.append("recipes_fts MATCH ?")
            params.append(match)
        for kind, values in (filters or {}).items():
            if kind not in CATEGORY_KINDS:
                continue
            for value in values:  # every selected facet must apply (AND)
                where.append(
                    "EXISTS (SELECT 1 FROM recipe_tags t WHERE t.recipe_id = r.id"
                    " AND t.kind = ? AND t.value = ? COLLATE NOCASE)"
                )
                params += [kind, value]
        if favorite:
            where.append("r.favorite = 1")
        if min_rating:
            where.append("r.rating >= ?")
            params.append(min_rating)
        if max_time:
            where.append("COALESCE(r.total_time, r.prep_time + r.cook_time) <= ?")
            params.append(max_time)
        if platform:
            where.append("r.source_platform = ?")
            params.append(platform)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        order = SORTS.get(sort) if sort in SORTS else None
        if order is None:
            order = f"bm25(recipes_fts, {BM25_WEIGHTS})" if match else SORTS["saved"]
        snippet = (
            # \x01/\x02 mark the hit; the UI escapes the text, then turns them into <mark>.
            "snippet(recipes_fts, -1, char(1), char(2), '…', 12) AS snippet" if match else "NULL AS snippet"
        )
        with self._lock:
            try:
                rows = self._conn.execute(
                    f"SELECT r.*, {snippet} FROM recipes r {joins} {where_sql}"
                    f" ORDER BY {order} LIMIT ? OFFSET ?",
                    (*params, limit, offset),
                ).fetchall()
                total = self._conn.execute(
                    f"SELECT COUNT(*) FROM recipes r {joins} {where_sql}", params
                ).fetchone()[0]
                facet_rows = self._conn.execute(
                    f"SELECT t.kind, t.value, COUNT(*) AS n FROM recipe_tags t WHERE t.recipe_id IN"
                    f" (SELECT r.id FROM recipes r {joins} {where_sql})"
                    " GROUP BY t.kind, t.value COLLATE NOCASE ORDER BY n DESC, t.value COLLATE NOCASE",
                    params,
                ).fetchall()
            except sqlite3.OperationalError:
                # A malformed query should read as "no results", never a 500.
                return {"total": 0, "results": [], "facets": {}}
        cats = self._categories_for(r["id"] for r in rows)
        results = []
        for r in rows:
            item = self._row_to_dict(r, cats[r["id"]])
            item["snippet"] = r["snippet"]
            results.append(item)
        facets: dict[str, list[dict[str, Any]]] = {k: [] for k in CATEGORY_KINDS}
        for row in facet_rows:
            facets[row["kind"]].append({"value": row["value"], "count": row["n"]})
        return {"total": total, "results": results, "facets": facets}

    def suggest(self, prefix: str, limit: int = 8) -> list[str]:
        """Typeahead: matching recipe titles and tag values."""
        like = f"%{prefix.strip()}%"
        titles = [r[0] for r in self._conn.execute(
            "SELECT title FROM recipes WHERE title LIKE ? ORDER BY title LIMIT ?", (like, limit))]
        tags = [r[0] for r in self._conn.execute(
            "SELECT DISTINCT value FROM recipe_tags WHERE value LIKE ? LIMIT ?", (like, limit))]
        return list(dict.fromkeys(titles + tags))[:limit]

    def stats(self) -> dict[str, Any]:
        recipes = self._conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        return {"recipes": recipes, "inbox": self.inbox_counts()}

    # -------------------------------------------------------------- saved items

    def add_saved_items(self, items: Iterable[SavedItem]) -> dict[str, int]:
        added = duplicates = 0
        now = _now()
        with self._lock, self._conn:
            for item in items:
                existing = self._conn.execute(
                    "SELECT id, collection, caption FROM saved_items WHERE url = ?", (item.url,)
                ).fetchone()
                if existing:
                    duplicates += 1
                    # A later export may know the collection/caption the first one lacked.
                    self._conn.execute(
                        "UPDATE saved_items SET collection = COALESCE(collection, ?),"
                        " caption = COALESCE(caption, ?), updated_at = ? WHERE id = ?",
                        (item.collection, item.caption, now, existing["id"]),
                    )
                    continue
                self._conn.execute(
                    """INSERT INTO saved_items (platform, url, author, title, caption, collection,
                       saved_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item.platform, item.url, item.author, item.title, item.caption,
                     item.collection, item.saved_at, now, now),
                )
                added += 1
        return {"added": added, "duplicates": duplicates}

    def list_saved_items(self, status: Optional[str] = None, limit: int = 200, offset: int = 0) -> list[dict]:
        sql = "SELECT * FROM saved_items"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY COALESCE(saved_at, created_at) DESC LIMIT ? OFFSET ?"
        return [dict(r) for r in self._conn.execute(sql, (*params, limit, offset))]

    def get_saved_item(self, item_id: int) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM saved_items WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None

    def get_saved_item_by_url(self, url: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM saved_items WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None

    def next_pending_item(self) -> Optional[dict]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM saved_items WHERE status = 'pending' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE saved_items SET status = 'processing', updated_at = ? WHERE id = ?",
                (_now(), row["id"]),
            )
        return dict(row)

    def update_saved_item(self, item_id: int, **fields: Any) -> None:
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE saved_items SET {assignments} WHERE id = ?", (*fields.values(), item_id)
            )

    def reset_items(self, statuses: Iterable[str]) -> int:
        statuses = [s for s in statuses if s in INBOX_STATUSES]
        if not statuses:
            return 0
        marks = ",".join("?" * len(statuses))
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"UPDATE saved_items SET status = 'pending', error = NULL, updated_at = ?"
                f" WHERE status IN ({marks})", (_now(), *statuses)
            )
        return cur.rowcount

    def inbox_counts(self) -> dict[str, int]:
        counts = {s: 0 for s in INBOX_STATUSES}
        for row in self._conn.execute("SELECT status, COUNT(*) FROM saved_items GROUP BY status"):
            counts[row[0]] = row[1]
        return counts
