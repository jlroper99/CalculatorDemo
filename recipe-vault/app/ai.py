"""Optional Claude-powered extraction and categorization.

Enabled when ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) is set, or when
RECIPE_VAULT_AI=on. Set RECIPE_VAULT_AI=off to force the offline heuristics.
Everything in the app works without it; Claude just reads messy captions
("comment-style" recipes, run-on paragraphs, other languages) far better
than regexes and gives more consistent categories.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

from .models import Categories

log = logging.getLogger(__name__)

MODEL = os.environ.get("RECIPE_VAULT_MODEL", "claude-opus-5")

MEAL_TYPES = ["Breakfast", "Brunch", "Lunch", "Dinner", "Dessert", "Snack", "Appetizer", "Side Dish", "Drink"]
COURSES = ["Main Dish", "Soup", "Salad", "Bread", "Baked Goods", "Sauce & Dressing", "Pasta", "Sandwich"]

SYSTEM_PROMPT = f"""You turn saved social-media food posts and recipe web pages into clean recipe records for a personal recipe database.

The text you get is usually an Instagram or Facebook caption. Captions mix the recipe with chatter, emoji, hashtags, calls to action ("comment RECIPE", "link in bio") and sponsor notes; keep only the recipe. Copy ingredient quantities and step wording faithfully; don't invent ingredients, amounts, or steps that aren't in the text. If the text has no actual recipe (only a dish name, a teaser, or "recipe on my blog"), set is_recipe to false and fill in what you can (title, description) so the person can find the post again.

Categories:
- meal_type: choose from {", ".join(MEAL_TYPES)}.
- course: choose from {", ".join(COURSES)}, or leave empty.
- cuisine: a common cuisine name such as Italian, Mexican, Thai, Indian, American, Mediterranean.
- diet: only diets the recipe really satisfies based on its ingredients or explicit claims (Vegetarian, Vegan, Gluten-Free, Dairy-Free, Keto, Low-Carb, High-Protein, Healthy).
- main_ingredient: the one or two star ingredients, e.g. Chicken, Beef, Seafood, Pasta, Tofu & Tempeh, Chocolate.
- method: cooking method or appliance if notable, e.g. Air Fryer, Slow Cooker, Instant Pot, Grill, Sheet Pan, One Pot, No-Bake.
- tag: a few short, useful search tags (e.g. "Weeknight", "Kid-Friendly", "Meal Prep", "Holiday"). No hashtags.
Times are whole minutes. Write the title in title case without emoji."""


class AICategories(BaseModel):
    meal_type: list[str] = Field(default_factory=list)
    course: list[str] = Field(default_factory=list)
    cuisine: list[str] = Field(default_factory=list)
    diet: list[str] = Field(default_factory=list)
    main_ingredient: list[str] = Field(default_factory=list)
    method: list[str] = Field(default_factory=list)
    tag: list[str] = Field(default_factory=list)


class AIRecipe(BaseModel):
    is_recipe: bool
    title: str
    description: str
    servings: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    total_time: Optional[int] = None
    ingredients: list[str]
    directions: list[str]
    notes: str = ""
    external_recipe_url: Optional[str] = None
    categories: AICategories


class AIUnavailable(Exception):
    pass


# Set when credentials turn out to be missing or rejected, so a long import
# doesn't retry (and log) the same failure for every item.
disabled_reason: Optional[str] = None


def enabled() -> bool:
    if disabled_reason:
        return False
    setting = os.environ.get("RECIPE_VAULT_AI", "auto").lower()
    if setting in ("off", "0", "false", "no"):
        return False
    if setting in ("on", "1", "true", "yes"):
        return True
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
            raise AIUnavailable("the anthropic package is not installed") from exc
        _client = anthropic.Anthropic()
    return _client


def _disable(reason: str) -> None:
    global disabled_reason
    disabled_reason = reason
    log.warning("Claude features turned off for this session: %s", reason)


def _ask(prompt: str, output: type[BaseModel]) -> Optional[BaseModel]:
    import anthropic

    credential_errors = (TypeError, getattr(anthropic, "CredentialsError", TypeError))
    try:
        client = _get_client()
        response = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=output,
            # Re-run on Anthropic's recommended model if a safety classifier
            # declines (rare for recipes, but it keeps imports from stalling).
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        _disable("Anthropic credentials were rejected")
        raise AIUnavailable(disabled_reason) from exc
    except credential_errors as exc:  # the SDK found no API key, auth token, or profile
        _disable(f"no Anthropic credentials found ({exc})")
        raise AIUnavailable(disabled_reason) from exc
    except anthropic.RateLimitError:
        log.warning("Claude rate limit hit; falling back to heuristics for this item")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Claude request failed (%s); falling back to heuristics", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("Could not reach the Claude API; falling back to heuristics")
        return None
    if response.stop_reason == "refusal":
        return None
    return response.parsed_output


def extract_recipe(text: str, context: str = "") -> Optional[AIRecipe]:
    """Structured recipe from free text (a caption or page description)."""
    prompt = (
        f"{context}\n\n<post>\n{text}\n</post>\n\n"
        "Extract the recipe from this saved post."
    ).strip()
    return _ask(prompt, AIRecipe)


def categorize(title: str, description: str, ingredients: list[str], directions: list[str]) -> Optional[Categories]:
    prompt = (
        f"<recipe>\nTitle: {title}\nDescription: {description}\n"
        f"Ingredients:\n" + "\n".join(ingredients) + "\nDirections:\n" + "\n".join(directions)
        + "\n</recipe>\n\nCategorize this recipe."
    )
    result = _ask(prompt, AICategories)
    return Categories(**result.model_dump()) if result else None
