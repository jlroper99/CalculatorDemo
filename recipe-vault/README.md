# Recipe Vault

A personal recipe database that pulls in everything you've saved on **Instagram** and **Facebook**, turns each post into a proper recipe (ingredients, steps, times, servings, photo, source), sorts it into categories automatically, and puts **search** at the center of everything. It's modeled loosely on Recipe Keeper, but the social-media import is automatic instead of copy/paste.

## Why it imports from a data export

Neither Instagram's nor Facebook's API lets any app read a person's saved posts. The supported way to get them in bulk is Meta's **Download your information** export, which includes every saved post, saved link, and collection. Recipe Vault reads that export and then, for each saved item:

1. **Linked recipe websites** (most Facebook saves, and captions that say "full recipe at …"): reads the page's schema.org Recipe data, so ingredients, steps, times, nutrition, and photo come across exactly.
2. **Instagram posts and reels**: fetches the public caption and parses the usual `Ingredients: … Instructions: …` layout.
3. **Messy captions** (run-on paragraphs, recipes in the comments, other languages): if you give it an Anthropic API key, Claude pulls out the recipe. Without a key, offline heuristics do the job and anything uncertain is flagged **Needs Review**.
4. **Private or login-only posts**: they wait in the **Inbox** with a "Paste caption" box. Copy the caption from the app and paste it in.

Posts that aren't recipes, like the beach photo you saved in 2019, are marked "No recipe found" and kept out of your recipe list.

## Quick start

```bash
cd recipe-vault
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# optional: let Claude read messy captions and categorize recipes
export ANTHROPIC_API_KEY=sk-ant-...

python -m app            # then open http://127.0.0.1:8000
```

Options: `python -m app --port 9000 --db ~/recipes.db`. The database is one SQLite file (default `recipe-vault/data/recipes.db`), so backing it up means copying that file. There's also **Import → Backup** for a JSON export and restore.

## Getting your saved posts

**Instagram**: [Accounts Center → Download your information](https://accountscenter.instagram.com/info_and_permissions/dyi/) → *Download or transfer information* → your Instagram account → *Some of your information* → tick **Saved** → *Download to device*, **All time**, format **JSON**.

**Facebook**: [Accounts Center → Download your information](https://accountscenter.facebook.com/info_and_permissions/dyi/) → your Facebook account → *Some of your information* → tick **Saved items and collections** → **All time**, format **JSON**.

Meta emails you when the file is ready, usually within a few minutes to a few hours. Drop the `.zip` onto the **Import** page. You can also drop individual `saved_posts.json`, `saved_collections.json`, or `your_saved_items.json` files, an HTML-format export, or a `.txt`/`.csv` list of links. Re-importing a newer export later only adds posts you haven't imported yet.

Your Instagram **collections** (for example "Weeknight Dinners") become a **Collection** category, so you can filter by them.

### Adding recipes one at a time

- **Import → Add one link**: an Instagram post or reel, a Facebook post, or any recipe site.
- **Import → Paste a caption or recipe**: any text.
- **Bookmarklet**: drag "＋ Save to Recipe Vault" from the Import page to your bookmarks bar. On a post, highlight the caption and click it.
- **＋ New**: type a recipe in by hand.

## Search

The search bar is on every page (press `/` to jump to it). Results update as you type and are ranked by relevance. A match in the title counts most, then ingredients and tags, then everything else. The index covers title, description, ingredients, directions, tags and categories, author, and your notes.

| Type | Finds |
| --- | --- |
| `chicken rice` | recipes that contain both words, anywhere |
| `lasag` | prefix match while you type |
| `brownie` | also finds "brownies" (stemming) |
| `"sun dried tomatoes"` | the exact phrase |
| `chicken -mushroom` | chicken, but nothing with mushrooms |
| `ingredient:basil` | basil in the ingredient list only (also `title:`, `tag:`, `author:`) |

Filters in the sidebar show live counts and combine with the search: meal type, course, cuisine, diet, main ingredient, cooking method, collection, and tags. There are also Favorites and "30 min or less" toggles, and you can sort by best match, recently saved, A–Z, rating, or quickest.

## Categories

Each recipe is auto-categorized along these dimensions:

- **Meal type**: Breakfast, Lunch, Dinner, Dessert, Snack, Appetizer, Side Dish, Drink
- **Course**: Main Dish, Soup, Salad, Bread, Baked Goods, Sauce & Dressing, Pasta, Sandwich
- **Cuisine**: Italian, Mexican, Thai, Indian, and so on
- **Diet**: Vegetarian or Vegan when the ingredient list has no meat or animal products; Gluten-Free, Keto, and others only when the recipe says so
- **Main ingredient**: Chicken, Beef, Seafood, Pasta, Tofu, Chocolate, and so on
- **Method**: Air Fryer, Slow Cooker, Instant Pot, Grill, Sheet Pan, One Pot, No-Bake, and so on
- **Collection**: from your Instagram and Facebook collections
- **Tags**: the post's hashtags, "Quick (30 min or less)", plus anything you add

Without an API key, a keyword classifier assigns categories. It weighs the title most, then the description, then the first few ingredients. With a key, Claude categorizes instead, and the keyword tags are kept alongside. You can edit any category, and **✨ Auto-categorize** on a recipe page re-runs it while keeping your collections and your own tags.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | unset | Turns on Claude for caption extraction and categorization |
| `RECIPE_VAULT_AI` | `auto` | `off` forces offline heuristics; `on` tries Claude with any configured Anthropic credentials |
| `RECIPE_VAULT_MODEL` | `claude-opus-5` | Claude model to use |
| `RECIPE_VAULT_DB` | `data/recipes.db` | Database path |

If the key is missing or rejected, the app logs it once, switches to heuristics, and carries on. An import never stops because of it.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests run a full Instagram + Facebook import against the sample exports in `sample_data/`, with mocked web pages, and cover search syntax, facets, categorization, and the paste-caption flow.

```
app/
  importers.py   reads Meta export zips/json/html/csv → saved items
  extract.py     fetches pages; parses schema.org JSON-LD and captions
  categorize.py  offline keyword categorizer
  ai.py          optional Claude extraction/categorization (structured output)
  pipeline.py    background worker: saved item → recipe
  db.py          SQLite + FTS5 search, facets, inbox
  main.py        FastAPI routes
  static/        the web app (no build step)
```

## Limits and notes

- Instagram and Facebook throttle anonymous requests, so the importer pauses about 2 seconds between posts. A few hundred saves take several minutes. You can pause and resume from the Inbox.
- Private accounts, Facebook group posts, and most Facebook posts (as opposed to links) need a login, so they land in the Inbox for a quick paste.
- Everything runs locally. The only outside requests are fetching the posts and pages you saved, plus the Claude API if you turn it on.
