"""Shared data shapes for recipes and saved social-media items."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Every categorization dimension the app knows about. The keys double as the
# `kind` column in the recipe_tags table and as filter names in the API.
CATEGORY_KINDS = (
    "meal_type",
    "course",
    "cuisine",
    "diet",
    "main_ingredient",
    "method",
    "collection",
    "tag",
)


class Categories(BaseModel):
    meal_type: list[str] = Field(default_factory=list)
    course: list[str] = Field(default_factory=list)
    cuisine: list[str] = Field(default_factory=list)
    diet: list[str] = Field(default_factory=list)
    main_ingredient: list[str] = Field(default_factory=list)
    method: list[str] = Field(default_factory=list)
    collection: list[str] = Field(default_factory=list)
    tag: list[str] = Field(default_factory=list)

    def merge(self, other: "Categories") -> "Categories":
        merged = {}
        for kind in CATEGORY_KINDS:
            seen: dict[str, None] = {}
            for value in getattr(self, kind) + getattr(other, kind):
                value = value.strip()
                if value and value.lower() not in {v.lower() for v in seen}:
                    seen[value] = None
            merged[kind] = list(seen)
        return Categories(**merged)

    def is_empty(self) -> bool:
        return not any(getattr(self, kind) for kind in CATEGORY_KINDS)


class RecipeIn(BaseModel):
    """A recipe as the user (or an importer) submits it."""

    title: str
    description: str = ""
    source_url: Optional[str] = None
    source_platform: Optional[str] = None  # instagram | facebook | web | manual
    author: Optional[str] = None
    image_url: Optional[str] = None
    servings: Optional[str] = None
    prep_time: Optional[int] = None  # minutes
    cook_time: Optional[int] = None
    total_time: Optional[int] = None
    ingredients: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    notes: str = ""
    nutrition: dict[str, str] = Field(default_factory=dict)
    rating: int = Field(default=0, ge=0, le=5)
    favorite: bool = False
    categories: Categories = Field(default_factory=Categories)
    saved_at: Optional[str] = None  # when it was saved on social media (ISO)
    auto_categorize: bool = True


class Recipe(RecipeIn):
    id: int
    created_at: str
    updated_at: str


class RecipePatch(BaseModel):
    """Partial update; only fields that are set are written."""

    title: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None
    author: Optional[str] = None
    image_url: Optional[str] = None
    servings: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    total_time: Optional[int] = None
    ingredients: Optional[list[str]] = None
    directions: Optional[list[str]] = None
    notes: Optional[str] = None
    nutrition: Optional[dict[str, str]] = None
    rating: Optional[int] = Field(default=None, ge=0, le=5)
    favorite: Optional[bool] = None
    categories: Optional[Categories] = None


class SavedItem(BaseModel):
    """One saved post/link pulled from a Facebook or Instagram data export."""

    platform: str  # instagram | facebook
    url: str
    author: Optional[str] = None
    title: Optional[str] = None
    caption: Optional[str] = None
    collection: Optional[str] = None
    saved_at: Optional[str] = None
