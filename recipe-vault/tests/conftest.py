import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.extract import Fetcher  # noqa: E402
from app.main import create_app  # noqa: E402

SAMPLES = ROOT / "sample_data"

TUSCAN_CAPTION = """Creamy Tuscan Chicken 🍗✨ the dinner my family asks for every week!

Prep: 10 min | Cook: 20 min | Serves 4

Ingredients:
- 2 large chicken breasts, halved
- 1 tbsp olive oil
- 3 cloves garlic, minced
- 1 cup heavy cream
- 1/2 cup grated parmesan
- 1/2 cup sun-dried tomatoes
- 2 cups fresh spinach

Instructions:
1. Season the chicken and sear in olive oil until golden, about 5 minutes per side. Remove.
2. Add garlic, then cream, parmesan and sun-dried tomatoes. Simmer 3 minutes.
3. Stir in spinach, return chicken to the pan and simmer until cooked through.

#dinner #chickenrecipes #easyrecipes #weeknightdinner"""

BROWNIE_CAPTION = """The fudgiest vegan brownies you'll ever make 🤎
Full recipe: https://example-recipes.com/vegan-brownies/
#vegan #brownies"""

BEACH_CAPTION = "Sunset at the beach 🌅 #travel #summer"


def embed_page(user, caption):
    body = caption.replace("\n", "<br/>")
    return f"""<html><body><div class="Embed">
      <a class="UsernameText">{user}</a>
      <img class="EmbeddedMediaImage" src="https://cdn.example/{user}.jpg">
      <div class="Caption"><a class="CaptionUsername">{user}</a> {body}
      <div class="CaptionComments">View all 12 comments</div></div></div></body></html>"""


def ld_page(data):
    return f"""<html><head><meta property="og:image" content="https://example-recipes.com/img.jpg">
      <script type="application/ld+json">{json.dumps(data)}</script></head><body></body></html>"""


LASAGNA = {
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "The Best Classic Lasagna",
    "author": {"@type": "Person", "name": "Maria"},
    "description": "Layers of meat sauce, ricotta and mozzarella.",
    "recipeYield": ["8", "8 servings"],
    "prepTime": "PT30M",
    "cookTime": "PT1H15M",
    "recipeCategory": "Main Course",
    "recipeCuisine": "Italian",
    "keywords": "lasagna, comfort food",
    "recipeIngredient": ["1 lb ground beef", "12 lasagna noodles", "15 oz ricotta", "2 cups mozzarella", "24 oz marinara"],
    "recipeInstructions": [
        {"@type": "HowToStep", "text": "Brown the beef and stir in marinara."},
        {"@type": "HowToStep", "text": "Layer noodles, sauce, ricotta and mozzarella."},
        {"@type": "HowToStep", "text": "Bake at 375°F for 45 minutes."},
    ],
    "nutrition": {"@type": "NutritionInformation", "calories": "520 kcal"},
}

BROWNIES = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "WebPage", "name": "Vegan brownies"},
        {
            "@type": ["Recipe"],
            "name": "Fudgy Vegan Brownies",
            "image": [{"@type": "ImageObject", "url": "https://example-recipes.com/brownies.jpg"}],
            "totalTime": "PT45M",
            "suitableForDiet": "https://schema.org/VeganDiet",
            "recipeIngredient": ["1 cup flour", "3/4 cup cocoa powder", "1 cup sugar", "1/2 cup coconut oil", "1/2 cup almond milk"],
            "recipeInstructions": "Mix dry ingredients.\nStir in oil and almond milk.\nBake 30 minutes at 350°F.",
        },
    ],
}

PAGES = {
    "https://www.instagram.com/p/C1TuscanChx/embed/captioned/": embed_page("halfbakedharvest", TUSCAN_CAPTION),
    "https://www.instagram.com/p/C2VeganBrwn/embed/captioned/": embed_page("minimalistbaker", BROWNIE_CAPTION),
    "https://www.instagram.com/p/C3Beach/embed/captioned/": embed_page("someone_travels", BEACH_CAPTION),
    "https://example-recipes.com/best-lasagna/": ld_page(LASAGNA),
    "https://example-recipes.com/vegan-brownies/": ld_page(BROWNIES),
    "https://www.facebook.com/quickcooks/posts/pfbid0abc": "<html><head><title>Log in to Facebook</title></head></html>",
}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url in PAGES:
        return httpx.Response(200, text=PAGES[url], headers={"content-type": "text/html"})
    return httpx.Response(404, text="not found", headers={"content-type": "text/html"})


@pytest.fixture(autouse=True)
def no_ai(monkeypatch):
    monkeypatch.setenv("RECIPE_VAULT_AI", "off")
    monkeypatch.setattr("app.ai.disabled_reason", None)


@pytest.fixture
def fetcher():
    return Fetcher(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


@pytest.fixture
def client(tmp_path, fetcher, monkeypatch):
    monkeypatch.setattr("app.pipeline.SOCIAL_DELAY_SECONDS", 0)
    app = create_app(str(tmp_path / "test.db"), fetcher=fetcher)
    with TestClient(app) as c:
        c.app_state = app.state
        yield c
