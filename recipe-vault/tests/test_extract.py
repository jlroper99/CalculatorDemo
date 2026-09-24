from conftest import BROWNIES, LASAGNA, TUSCAN_CAPTION, ld_page

from app.categorize import categorize
from app.extract import (caption_links, find_jsonld_recipe, from_jsonld, instagram_caption_from_meta,
                         parse_caption, parse_duration)


def test_durations():
    assert parse_duration("PT1H15M") == 75
    assert parse_duration("P0DT0H20M") == 20
    assert parse_duration("1 hr 30 mins") == 90
    assert parse_duration("45 minutes") == 45
    assert parse_duration("") is None


def test_jsonld_recipe():
    ex = from_jsonld(find_jsonld_recipe(ld_page(LASAGNA)))
    assert ex.title == "The Best Classic Lasagna"
    assert ex.author == "Maria"
    assert ex.servings == "8 servings"
    assert (ex.prep_time, ex.cook_time, ex.total_time) == (30, 75, 105)
    assert len(ex.ingredients) == 5 and len(ex.directions) == 3
    assert ex.nutrition == {"calories": "520 kcal"}
    assert "Italian" in ex.hints


def test_jsonld_graph_and_string_instructions():
    ex = from_jsonld(find_jsonld_recipe(ld_page(BROWNIES)))
    assert ex.title == "Fudgy Vegan Brownies"
    assert ex.image_url == "https://example-recipes.com/brownies.jpg"
    assert ex.directions == ["Mix dry ingredients.", "Stir in oil and almond milk.", "Bake 30 minutes at 350°F."]
    assert "Vegan" in ex.hints


def test_caption_parsing():
    ex = parse_caption(TUSCAN_CAPTION)
    assert ex.title == "Creamy Tuscan Chicken"
    assert ex.prep_time == 10 and ex.cook_time == 20 and ex.total_time == 30
    assert ex.servings == "4"
    assert ex.ingredients[0] == "2 large chicken breasts, halved"
    assert len(ex.ingredients) == 7
    assert len(ex.directions) == 3
    assert ex.directions[0].startswith("Season the chicken")
    assert "#dinner" not in ex.description


def test_caption_without_headings():
    ex = parse_caption("Garlic Butter Shrimp\n- 1 lb shrimp\n- 3 tbsp butter\n- 4 cloves garlic\n"
                       "1. Melt the butter in a skillet over medium heat.\n2. Add shrimp and garlic and cook 4 minutes.")
    assert ex.title == "Garlic Butter Shrimp"
    assert ex.ingredients == ["1 lb shrimp", "3 tbsp butter", "4 cloves garlic"]
    assert len(ex.directions) == 2


def test_caption_links_and_meta_caption():
    assert caption_links("Full recipe: https://example-recipes.com/vegan-brownies/ 🤎") == [
        "https://example-recipes.com/vegan-brownies/"]
    assert caption_links("recipe at mysite.com/pie!") == ["https://mysite.com/pie"]
    desc = '1,234 likes, 56 comments - chef on May 1, 2024: "Easy pasta\nIngredients: ..."'
    assert instagram_caption_from_meta(desc).startswith("Easy pasta")


def test_categorize_tuscan_chicken():
    ex = parse_caption(TUSCAN_CAPTION)
    cats = categorize(ex.title, ex.description + TUSCAN_CAPTION, ex.ingredients, ex.directions, ex.total_time)
    assert cats.meal_type == ["Dinner"]
    assert "Main Dish" in cats.course
    assert cats.main_ingredient[0] == "Chicken"
    assert "Italian" in cats.cuisine  # "tuscan", "parmesan"
    assert "Vegetarian" not in cats.diet
    assert "Quick (30 min or less)" in cats.tag


def test_categorize_vegan_dessert():
    cats = categorize("Fudgy Vegan Brownies", "", ["1 cup flour", "1/2 cup coconut oil", "1/2 cup almond milk", "cocoa"])
    assert cats.meal_type == ["Dessert"]
    assert "Main Dish" not in cats.course
    assert {"Vegan", "Vegetarian"} <= set(cats.diet)
    assert "Chocolate" in cats.main_ingredient


def test_categorize_vegetarian_not_vegan():
    cats = categorize("Spinach Frittata", "", ["8 eggs", "2 cups spinach", "1/2 cup feta"])
    assert "Breakfast" in cats.meal_type
    assert "Vegetarian" in cats.diet and "Vegan" not in cats.diet


def test_categorize_drink_and_method():
    cats = categorize("Strawberry Lemonade", "No-cook summer drink", ["1 cup strawberries", "lemons", "sugar"])
    assert cats.meal_type == ["Drink"]
    cats = categorize("Air Fryer Salmon Bites", "", ["1 lb salmon", "soy sauce"])
    assert "Air Fryer" in cats.method and "Seafood" in cats.main_ingredient
