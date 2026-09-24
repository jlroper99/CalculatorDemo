"""Rule-based auto-categorization.

Works offline with no API key. Each rule is a keyword list; the title counts
more than the description, which counts more than the ingredient list. When
Claude is configured (see ai.py) its categories are merged on top of these.
"""

from __future__ import annotations

import re
from typing import Optional

from .models import Categories

MEAL_TYPES = {
    "Breakfast": [
        "breakfast", "brunch", "pancake", "pancakes", "waffle", "waffles", "french toast", "oatmeal",
        "overnight oats", "granola", "omelet", "omelette", "frittata", "scrambled eggs", "eggs benedict",
        "breakfast burrito", "hash brown", "hash browns", "crepe", "crepes", "smoothie bowl", "parfait",
        "biscuits and gravy", "shakshuka", "quiche", "cinnamon roll", "cinnamon rolls", "muffin", "muffins",
        "bagel", "chia pudding", "breakfast casserole",
    ],
    "Lunch": [
        "lunch", "sandwich", "sandwiches", "wrap", "wraps", "panini", "grilled cheese", "quesadilla",
        "salad", "grain bowl", "buddha bowl", "poke", "bento", "blt", "pita",
    ],
    "Dinner": [
        "dinner", "supper", "weeknight", "casserole", "lasagna", "roast", "pot roast", "steak",
        "chicken breast", "chicken thighs", "meatloaf", "curry", "stir fry", "stir-fry", "enchiladas",
        "pasta", "spaghetti", "risotto", "tacos", "fajitas", "chili", "stew", "pot pie", "salmon",
        "shrimp", "pork chops", "tenderloin", "meatballs", "burgers", "burger", "pizza", "gnocchi",
        "fried rice", "lo mein", "ramen", "pad thai", "one pot", "one-pot", "sheet pan",
    ],
    "Dessert": [
        "dessert", "cake", "cupcake", "cupcakes", "cookie", "cookies", "brownie", "brownies", "blondies",
        "pie", "tart", "cheesecake", "ice cream", "gelato", "sorbet", "pudding", "mousse", "fudge",
        "truffles", "frosting", "cobbler", "apple crisp", "crumble", "tiramisu", "macarons", "donut", "donuts",
        "doughnut", "churros", "cinnamon sugar", "caramel", "sweet treat", "no-bake", "no bake", "trifle",
        "panna cotta", "creme brulee", "banana bread",
    ],
    "Snack": [
        "snack", "snacks", "energy balls", "energy bites", "protein balls", "trail mix", "popcorn",
        "granola bars", "chips", "crackers", "jerky", "roasted chickpeas", "hummus",
    ],
    "Appetizer": [
        "appetizer", "appetizers", "starter", "dip", "bruschetta", "crostini", "sliders",
        "wings", "deviled eggs", "spring rolls", "egg rolls", "dumplings", "nachos", "charcuterie",
        "stuffed mushrooms", "party food", "game day", "finger food", "guacamole", "salsa",
    ],
    "Side Dish": [
        "side dish", "sides", "mashed potatoes", "roasted vegetables", "roasted potatoes",
        "coleslaw", "cornbread", "rice pilaf", "green beans", "brussels sprouts", "mac and cheese",
        "garlic bread", "dinner rolls", "potato salad", "baked beans", "stuffing",
    ],
    "Drink": [
        "drink", "drinks", "cocktail", "mocktail", "smoothie", "lemonade", "latte", "coffee", "tea",
        "punch", "sangria", "margarita", "hot chocolate", "milkshake", "shake", "juice", "spritz",
        "agua fresca", "iced coffee", "iced tea", "boba",
    ],
}

COURSES = {
    "Main Dish": MEAL_TYPES["Dinner"] + ["main dish", "entree", "entrée", "main course"],
    "Soup": ["soup", "chowder", "bisque", "broth", "pho", "ramen", "gazpacho", "minestrone"],
    "Salad": ["salad", "slaw"],
    "Bread": ["bread", "focaccia", "sourdough", "loaf", "rolls", "biscuits", "naan", "flatbread", "buns"],
    "Baked Goods": ["bake", "baked", "cake", "cookies", "muffins", "scones", "pastry", "croissant", "brownies"],
    "Sauce & Dressing": ["sauce", "dressing", "vinaigrette", "marinade", "gravy", "aioli", "pesto", "salsa"],
    "Pasta": ["pasta", "spaghetti", "penne", "fettuccine", "linguine", "rigatoni", "orzo", "lasagna",
              "mac and cheese", "gnocchi", "tortellini", "ravioli", "noodles"],
    "Sandwich": ["sandwich", "burger", "sliders", "panini", "wrap", "hoagie", "melt"],
}

CUISINES = {
    "Italian": ["italian", "pasta", "risotto", "parmesan", "parmigiana", "marinara", "pesto", "lasagna",
                "bolognese", "carbonara", "alfredo", "tiramisu", "bruschetta", "focaccia", "gnocchi",
                "caprese", "prosciutto", "ricotta", "pizza", "panna cotta", "tuscan", "orzo", "arrabbiata"],
    "Mexican": ["mexican", "taco", "tacos", "enchilada", "enchiladas", "burrito", "quesadilla", "salsa",
                "tortilla", "tortillas", "guacamole", "chipotle", "fajitas", "elote", "pozole", "tamales",
                "carnitas", "birria", "queso", "jalapeño", "jalapeno", "cilantro lime", "churros", "tex-mex"],
    "Chinese": ["chinese", "lo mein", "chow mein", "kung pao", "orange chicken", "fried rice", "dumplings",
                "bok choy", "hoisin", "szechuan", "sichuan", "wonton", "general tso", "sesame chicken",
                "char siu", "mapo tofu", "egg rolls"],
    "Japanese": ["japanese", "sushi", "teriyaki", "miso", "ramen", "udon", "tempura", "katsu", "onigiri",
                 "matcha", "yakitori", "gyoza", "furikake", "mirin"],
    "Korean": ["korean", "kimchi", "gochujang", "bulgogi", "bibimbap", "gochugaru", "japchae", "tteokbokki"],
    "Thai": ["thai", "pad thai", "curry paste", "coconut curry", "lemongrass", "fish sauce", "tom yum",
             "tom kha", "pad see ew", "satay", "larb"],
    "Indian": ["indian", "curry", "tikka", "masala", "garam masala", "tandoori", "naan", "dal", "daal",
               "biryani", "paneer", "korma", "vindaloo", "chana", "samosa", "turmeric", "chutney", "saag"],
    "Mediterranean": ["mediterranean", "hummus", "falafel", "tahini", "tabbouleh",
                      "za'atar", "pita", "couscous", "shakshuka"],
    "Greek": ["greek", "tzatziki", "gyro", "gyros", "souvlaki", "spanakopita", "moussaka", "baklava"],
    "Middle Eastern": ["middle eastern", "shawarma", "kofta", "sumac", "harissa", "baba ganoush",
                       "labneh", "za'atar", "pomegranate molasses"],
    "French": ["french", "croissant", "crepe", "crepes", "ratatouille", "coq au vin", "bouillabaisse",
               "gratin", "beurre", "soufflé", "souffle", "quiche", "macarons", "creme brulee", "dijon"],
    "American": ["american", "bbq", "barbecue", "burger", "burgers", "mac and cheese", "meatloaf",
                 "fried chicken", "cornbread", "sloppy joe", "buffalo", "ranch", "pot roast", "apple pie",
                 "chocolate chip cookies", "casserole", "grilled cheese", "biscuits and gravy"],
    "Cajun & Southern": ["cajun", "creole", "gumbo", "jambalaya", "etouffee", "grits", "collard greens",
                         "hush puppies", "po boy", "southern"],
    "Vietnamese": ["vietnamese", "pho", "banh mi", "spring rolls", "nuoc cham", "vermicelli bowl"],
    "Spanish": ["spanish", "paella", "chorizo", "patatas bravas", "gazpacho", "tapas", "romesco"],
}

MAIN_INGREDIENTS = {
    "Chicken": ["chicken"],
    "Beef": ["beef", "steak", "ground beef", "brisket", "short ribs", "sirloin", "ribeye", "flank"],
    "Pork": ["pork", "bacon", "ham", "sausage", "prosciutto", "pancetta", "chorizo", "carnitas"],
    "Turkey": ["turkey"],
    "Lamb": ["lamb"],
    "Seafood": ["salmon", "shrimp", "tuna", "cod", "tilapia", "halibut", "fish", "crab", "lobster",
                "scallops", "mussels", "clams", "prawns", "mahi"],
    "Pasta": COURSES["Pasta"],
    "Rice & Grains": ["rice", "quinoa", "farro", "barley", "couscous", "risotto"],
    "Eggs": ["egg", "eggs", "frittata", "omelet", "omelette", "quiche"],
    "Beans & Legumes": ["beans", "chickpeas", "lentils", "black beans", "garbanzo", "edamame"],
    "Tofu & Tempeh": ["tofu", "tempeh", "seitan"],
    "Potatoes": ["potato", "potatoes", "sweet potato", "sweet potatoes"],
    "Vegetables": ["zucchini", "cauliflower", "broccoli", "eggplant", "spinach", "kale", "mushroom",
                   "mushrooms", "squash", "brussels sprouts", "asparagus", "carrots", "cabbage"],
    "Chocolate": ["chocolate", "cocoa", "nutella", "brownie", "brownies", "fudge"],
    "Fruit": ["apple", "banana", "berries", "strawberry", "strawberries", "blueberry", "blueberries",
              "lemon", "peach", "peaches", "raspberry", "raspberries", "mango", "pineapple", "cherry"],
}

METHODS = {
    "Slow Cooker": ["slow cooker", "crockpot", "crock pot", "crock-pot"],
    "Instant Pot": ["instant pot", "pressure cooker", "instapot"],
    "Air Fryer": ["air fryer", "air-fryer", "air fried", "airfryer"],
    "Grill": ["grill", "grilled", "grilling", "bbq", "barbecue", "smoker", "smoked"],
    "One Pot": ["one pot", "one-pot", "one pan", "one-pan", "skillet"],
    "Sheet Pan": ["sheet pan", "sheet-pan", "traybake"],
    "No-Bake": ["no bake", "no-bake"],
    "Baked": ["bake", "baked", "oven", "roasted", "roast"],
    "Fried": ["fried", "deep fry", "deep-fried", "pan-fried"],
    "Meal Prep": ["meal prep", "make ahead", "make-ahead", "freezer"],
}

# Diets are only applied when the text says so explicitly, or (for
# vegetarian/vegan) when there is an ingredient list with no meat at all.
DIETS = {
    "Vegan": ["vegan", "plant-based", "plant based"],
    "Vegetarian": ["vegetarian", "meatless"],
    "Gluten-Free": ["gluten-free", "gluten free", "gf", "celiac"],
    "Dairy-Free": ["dairy-free", "dairy free"],
    "Keto": ["keto", "ketogenic"],
    "Low-Carb": ["low carb", "low-carb"],
    "Paleo": ["paleo"],
    "Whole30": ["whole30", "whole 30"],
    "High-Protein": ["high protein", "high-protein", "protein packed", "protein-packed"],
    "Healthy": ["healthy", "low calorie", "low-calorie", "lightened up"],
}

MEAT_WORDS = sorted(
    {w for k in ("Chicken", "Beef", "Pork", "Turkey", "Lamb", "Seafood") for w in MAIN_INGREDIENTS[k]}
    | {"anchovy", "anchovies", "gelatin", "meat", "veal", "duck", "venison", "pepperoni", "salami"}
)
ANIMAL_WORDS = MEAT_WORDS + [
    "egg", "eggs", "milk", "butter", "cheese", "cream", "yogurt", "honey", "parmesan", "mozzarella",
    "cheddar", "ricotta", "feta", "mayo", "mayonnaise", "ghee", "buttermilk", "whey",
]
# Words that look like animal products but are not.
NOT_ANIMAL = ["peanut butter", "almond butter", "coconut milk", "almond milk", "oat milk", "soy milk",
              "coconut cream", "vegan butter", "vegan cheese", "cashew cream", "eggplant", "nutritional yeast",
              "butternut", "cream of tartar", "vegan mayo", "flax egg"]

HASHTAG_SKIP = {"recipe", "recipes", "food", "foodie", "yum", "yummy", "delicious", "instafood",
                "foodporn", "foodstagram", "reels", "reel", "fyp", "viral", "cooking", "homemade",
                "easyrecipes", "easyrecipe", "foodblogger", "tasty", "explore", "explorepage"}


def _compile(words: list[str]) -> re.Pattern:
    escaped = sorted((re.escape(w) for w in words), key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(escaped) + r")(?![\w-])", re.I)


_CACHE: dict[int, re.Pattern] = {}


def _pattern(words: list[str]) -> re.Pattern:
    key = id(words)
    if key not in _CACHE:
        _CACHE[key] = _compile(words)
    return _CACHE[key]


def _score(table: dict[str, list[str]], title: str, body: str, ingredients: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    for label, words in table.items():
        pat = _pattern(words)
        s = 3.0 * len(pat.findall(title)) + 1.0 * min(len(pat.findall(body)), 3)
        s += 0.5 * min(len(pat.findall(ingredients)), 4)
        if s:
            scores[label] = s
    return scores


def _top(scores: dict[str, float], threshold: float, max_n: int) -> list[str]:
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [label for label, s in ranked if s >= threshold][:max_n]


def _strip_non_animal(text: str) -> str:
    return _pattern(NOT_ANIMAL).sub(" ", text)


def hashtags(text: str) -> list[str]:
    tags = []
    for tag in re.findall(r"#(\w+)", text or ""):
        if tag.lower() not in HASHTAG_SKIP and not tag.isdigit():
            tags.append(tag.lower())
    return list(dict.fromkeys(tags))[:15]


def categorize(
    title: str,
    description: str = "",
    ingredients: Optional[list[str]] = None,
    directions: Optional[list[str]] = None,
    total_time: Optional[int] = None,
    hints: Optional[list[str]] = None,
) -> Categories:
    """Guess categories from recipe text. `hints` are site-provided categories/keywords."""
    ingredients = ingredients or []
    ing_text = "\n".join(ingredients)
    hint_text = " ".join(hints or [])
    body = " ".join([description, hint_text, " ".join(directions or [])])
    title = title or ""

    meal = _top(_score(MEAL_TYPES, title, body, ""), 3.0, 2)
    course = _top(_score(COURSES, title, body, ""), 3.0, 2)
    cuisine = _top(_score(CUISINES, title, body, ing_text), 3.0, 2)
    method = _top(_score(METHODS, title, body, ""), 1.0, 3)
    main_scores = _score(MAIN_INGREDIENTS, title, "", "")
    # Weight the first few ingredients: they are usually the star of the dish.
    for label, s in _score(MAIN_INGREDIENTS, "", "", "\n".join(ingredients[:5])).items():
        main_scores[label] = main_scores.get(label, 0) + s
    main = _top(main_scores, 1.0, 2)

    diet = [label for label, words in DIETS.items()
            if _pattern(words).search(title + " " + description + " " + hint_text)]
    if ingredients:
        clean = _strip_non_animal(ing_text + " " + title)
        if not _pattern(MEAT_WORDS).search(clean) and "Vegetarian" not in diet and "Vegan" not in diet:
            diet.append("Vegetarian")
            if not _pattern(ANIMAL_WORDS).search(clean):
                diet.append("Vegan")
    if "Vegan" in diet and "Vegetarian" not in diet:
        diet.append("Vegetarian")

    # Drinks and desserts rarely double as dinner; don't let "chocolate cake
    # with a pie crust" land in Main Dish.
    if meal and meal[0] in ("Dessert", "Drink", "Snack"):
        course = [c for c in course if c != "Main Dish"]
        meal = meal[:1]
    if meal and meal[0] == "Dinner" and not course:
        course = ["Main Dish"]
    if not meal and "Main Dish" in course:
        meal = ["Dinner"]

    tags: list[str] = []
    if total_time and total_time <= 30:
        tags.append("Quick (30 min or less)")
    tags += hashtags(description)

    return Categories(
        meal_type=meal, course=course, cuisine=cuisine, diet=diet,
        main_ingredient=main, method=method, tag=tags,
    )
