import time

from conftest import SAMPLES


def wait_for_worker(client, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get("/api/inbox/status").json()
        if not status["running"] and status["counts"]["pending"] == 0:
            return status
        time.sleep(0.05)
    raise AssertionError("worker did not finish")


def upload(client, name):
    with open(SAMPLES / name, "rb") as fh:
        return client.post("/api/import/file", files=[("files", (name, fh, "application/zip"))])


def test_full_instagram_and_facebook_import(client):
    res = upload(client, "instagram-export-sample.zip").json()
    assert res["added"] == 3
    status = wait_for_worker(client)
    counts = status["counts"]
    assert counts["imported"] == 2       # Tuscan chicken (caption) + brownies (linked blog)
    assert counts["not_recipe"] == 1     # the beach photo

    upload(client, "facebook-export-sample.zip")
    counts = wait_for_worker(client)["counts"]
    assert counts["imported"] == 3       # + lasagna from the linked site
    assert counts["failed"] == 1         # Facebook login wall

    # re-importing the same export adds nothing
    again = upload(client, "instagram-export-sample.zip").json()
    assert again["added"] == 0 and again["duplicates"] == 3

    recipes = client.get("/api/recipes").json()
    titles = {r["title"] for r in recipes["results"]}
    assert titles == {"Creamy Tuscan Chicken", "Fudgy Vegan Brownies", "The Best Classic Lasagna"}

    tuscan = next(r for r in recipes["results"] if r["title"] == "Creamy Tuscan Chicken")
    assert tuscan["source_platform"] == "instagram"
    assert tuscan["author"] == "halfbakedharvest"
    assert tuscan["categories"]["collection"] == ["Weeknight Dinners"]
    assert "Dinner" in tuscan["categories"]["meal_type"]

    brownies = next(r for r in recipes["results"] if r["title"] == "Fudgy Vegan Brownies")
    assert brownies["source_url"] == "https://www.instagram.com/reel/C2VeganBrwn/"
    assert brownies["categories"]["collection"] == ["Desserts 🍰"]
    assert "Vegan" in brownies["categories"]["diet"]
    assert brownies["total_time"] == 45


def test_search_ranking_facets_and_filters(client):
    upload(client, "instagram-export-sample.zip")
    upload(client, "facebook-export-sample.zip")
    wait_for_worker(client)

    r = client.get("/api/recipes", params={"q": "parmesan"}).json()
    assert [x["title"] for x in r["results"]] == ["Creamy Tuscan Chicken"]
    assert "\x01" in r["results"][0]["snippet"]

    # prefix search while typing
    assert client.get("/api/recipes", params={"q": "lasag"}).json()["total"] == 1
    # ingredient-only and exclusion syntax
    assert client.get("/api/recipes", params={"q": "ingredient:ricotta"}).json()["total"] == 1
    assert client.get("/api/recipes", params={"q": "cup -cocoa"}).json()["total"] == 2
    # stemming: "brownie" finds "Brownies"
    assert client.get("/api/recipes", params={"q": "brownie"}).json()["total"] == 1

    dessert = client.get("/api/recipes", params={"meal_type": "Dessert"}).json()
    assert [x["title"] for x in dessert["results"]] == ["Fudgy Vegan Brownies"]
    facets = client.get("/api/recipes").json()["facets"]
    assert any(f["value"] == "Italian" for f in facets["cuisine"])

    quick = client.get("/api/recipes", params={"max_time": 30}).json()
    assert [x["title"] for x in quick["results"]] == ["Creamy Tuscan Chicken"]

    # garbage input must not error
    assert client.get("/api/recipes", params={"q": '"unbalanced AND ( NOT'}).status_code == 200
    assert client.get("/api/suggest", params={"q": "tusc"}).json() == ["Creamy Tuscan Chicken"]


def test_manual_recipe_crud_and_autocategorize(client):
    body = {"title": "Slow Cooker Beef Chili", "ingredients": ["2 lb ground beef", "2 cans kidney beans", "1 onion"],
            "directions": ["Brown beef.", "Add everything to the slow cooker and cook 8 hours."],
            "categories": {"tag": ["Game Day"]}}
    r = client.post("/api/recipes", json=body)
    assert r.status_code == 201
    recipe = r.json()
    assert "Slow Cooker" in recipe["categories"]["method"]
    assert "Beef" in recipe["categories"]["main_ingredient"]
    assert "Game Day" in recipe["categories"]["tag"]  # the user's own tag survives

    rid = recipe["id"]
    client.patch(f"/api/recipes/{rid}", json={"favorite": True, "rating": 5, "notes": "Double the cumin"})
    got = client.get(f"/api/recipes/{rid}").json()
    assert got["favorite"] and got["rating"] == 5
    assert client.get("/api/recipes", params={"q": "cumin"}).json()["total"] == 1  # notes are indexed
    assert client.get("/api/recipes", params={"favorite": True}).json()["total"] == 1
    assert client.delete(f"/api/recipes/{rid}").status_code == 204
    assert client.get("/api/recipes", params={"q": "chili"}).json()["total"] == 0


def test_paste_caption_for_failed_item(client):
    upload(client, "facebook-export-sample.zip")
    wait_for_worker(client)
    failed = client.get("/api/inbox", params={"status": "failed"}).json()
    assert len(failed) == 1 and "paste" in failed[0]["error"].lower()
    text = "Sheet Pan Gnocchi\nIngredients:\n- 1 lb gnocchi\n- 2 cups cherry tomatoes\n- 2 tbsp olive oil\nDirections:\nToss everything and roast at 425F for 20 minutes."
    res = client.post(f"/api/inbox/{failed[0]['id']}/text", json={"text": text}).json()
    assert res["recipe"]["title"] == "Sheet Pan Gnocchi"
    assert res["recipe"]["source_url"] == "https://www.facebook.com/quickcooks/posts/pfbid0abc"
    assert "Sheet Pan" in res["recipe"]["categories"]["method"]
    assert client.get("/api/inbox/status").json()["counts"]["failed"] == 0


def test_single_url_import_and_duplicate(client):
    r = client.post("/api/import/url", json={"url": "https://example-recipes.com/best-lasagna/?utm_source=x"}).json()
    assert r["status"] == "imported"
    again = client.post("/api/import/url", json={"url": "https://example-recipes.com/best-lasagna/"}).json()
    assert again == {"status": "exists", "recipe_id": r["recipe_id"]}
    assert client.post("/api/import/url", json={"url": "not a url"}).status_code == 400


def test_needs_review_flag(client):
    res = client.post("/api/import/text", json={"text": "Grandma's famous pie. So good!! Recipe coming soon"}).json()
    assert res["status"] == "needs_review"
    assert "Needs Review" in res["recipe"]["categories"]["tag"]


def test_export_and_restore(client, tmp_path):
    client.post("/api/recipes", json={"title": "Toast", "ingredients": ["bread", "butter"], "directions": ["Toast it."]})
    data = client.get("/api/export").content
    client.delete("/api/recipes/1")
    res = client.post("/api/import/backup", files={"file": ("backup.json", data, "application/json")}).json()
    assert res == {"added": 1, "skipped": 0}
    assert client.get("/api/recipes", params={"q": "toast"}).json()["total"] == 1


def test_ui_served(client):
    assert "Recipe Vault" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_claude_output_is_used_when_enabled(client, monkeypatch):
    from app import ai, pipeline

    monkeypatch.setenv("RECIPE_VAULT_AI", "on")
    seen = {}

    def fake_extract(text, context=""):
        seen["text"] = text
        return ai.AIRecipe(
            is_recipe=True, title="Honey Garlic Salmon", description="Sticky, glossy salmon.",
            servings="2", prep_time=5, cook_time=12, total_time=17,
            ingredients=["2 salmon fillets", "2 tbsp honey", "2 cloves garlic"],
            directions=["Whisk the glaze.", "Sear the salmon and glaze it."],
            categories=ai.AICategories(meal_type=["Dinner"], cuisine=["Asian Fusion"], main_ingredient=["Seafood"]),
        )

    monkeypatch.setattr(pipeline.ai, "extract_recipe", fake_extract)
    monkeypatch.setattr(pipeline.ai, "categorize", lambda *a, **k: None)
    caption = "made this salmon again omg 😍 honey + garlic + soy, 12 min in the pan, glaze at the end"
    res = client.post("/api/import/text", json={"text": caption}).json()
    assert seen["text"] == caption
    assert res["status"] == "imported"
    recipe = res["recipe"]
    assert recipe["title"] == "Honey Garlic Salmon" and recipe["total_time"] == 17
    assert recipe["categories"]["cuisine"] == ["Asian Fusion"]
    assert "Needs Review" not in recipe["categories"]["tag"]


def test_claude_not_recipe(client, monkeypatch):
    from app import ai, pipeline

    monkeypatch.setenv("RECIPE_VAULT_AI", "on")
    monkeypatch.setattr(pipeline.ai, "extract_recipe", lambda text, context="": ai.AIRecipe(
        is_recipe=False, title="Beach Sunset", description="", ingredients=[], directions=[],
        categories=ai.AICategories()))
    upload(client, "instagram-export-sample.zip")
    counts = wait_for_worker(client)["counts"]
    assert counts["not_recipe"] == 1


def test_missing_credentials_do_not_break_import(client, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent")
    monkeypatch.setenv("RECIPE_VAULT_AI", "on")
    monkeypatch.setattr("app.ai._client", None)
    upload(client, "instagram-export-sample.zip")
    counts = wait_for_worker(client)["counts"]
    assert counts["imported"] == 2  # fell back to the offline heuristics
    assert client.get("/api/inbox/status").json()["ai_enabled"] is False
