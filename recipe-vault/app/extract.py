"""Turn a saved link or a block of caption text into a structured recipe.

Three sources, best first:
1. schema.org/Recipe JSON-LD on the linked web page (nearly every recipe blog
   publishes it, so ingredients/steps/times come out exact).
2. The Instagram/Facebook caption, parsed with heuristics for the usual
   "Ingredients: ... Instructions: ..." layout.
3. Claude (optional, see ai.py) for captions the heuristics can't follow.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from .importers import INSTAGRAM_POST, URL_RE, is_saveable, normalize_url, platform_for

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class Extracted:
    """What we learned about one saved item."""

    title: str = ""
    description: str = ""
    author: Optional[str] = None
    image_url: Optional[str] = None
    servings: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    total_time: Optional[int] = None
    ingredients: list[str] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    nutrition: dict[str, str] = field(default_factory=dict)
    hints: list[str] = field(default_factory=list)  # site categories/keywords
    source_url: Optional[str] = None
    structured: bool = False  # came from JSON-LD
    raw_text: str = ""  # caption / page text, for review or AI

    @property
    def looks_complete(self) -> bool:
        return len(self.ingredients) >= 2 and len(self.directions) >= 1


# ------------------------------------------------------------------ helpers


def parse_duration(value: Any) -> Optional[int]:
    """ISO-8601 durations (PT1H30M) or loose text ("1 hr 15 mins") to minutes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+)S)?)?", text, re.I)
    if m and any(m.groups()):
        d, h, mi, _ = m.groups()
        total = int(d or 0) * 1440 + float(h or 0) * 60 + float(mi or 0)
        return int(round(total)) or None
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", text, re.I)
    mins = re.search(r"(\d+)\s*(?:m|min|mins|minute|minutes)\b", text, re.I)
    if hours or mins:
        return int(float(hours.group(1)) * 60 if hours else 0) + int(mins.group(1) if mins else 0) or None
    return None


def _clean(text: Any) -> str:
    if text is None:
        return ""
    text = html_lib.unescape(str(text))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _image(value: Any) -> Optional[str]:
    for v in _as_list(value):
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return v.get("url") or v.get("contentUrl")
    return None


def _author(value: Any) -> Optional[str]:
    for v in _as_list(value):
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and v.get("name"):
            return _clean(v["name"])
    return None


def _instructions(value: Any) -> list[str]:
    steps: list[str] = []
    for v in _as_list(value):
        if isinstance(v, str):
            # Some sites put every step in one string.
            parts = [p for p in re.split(r"\n+|(?<=\.)\s+(?=\d+[.)]\s)", v) if p.strip()]
            steps += [_clean(p) for p in parts]
        elif isinstance(v, dict):
            kind = v.get("@type")
            kind = kind[0] if isinstance(kind, list) else kind
            if kind == "HowToSection":
                name = _clean(v.get("name"))
                if name:
                    steps.append(f"## {name}")
                steps += _instructions(v.get("itemListElement"))
            else:
                text = _clean(v.get("text") or v.get("name"))
                if text:
                    steps.append(text)
    return [re.sub(r"^\d+[.)]\s*", "", s) for s in steps if s]


# ----------------------------------------------------------------- JSON-LD


def _walk_ld(node: Any):
    if isinstance(node, list):
        for n in node:
            yield from _walk_ld(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _walk_ld(node[key])


def find_jsonld_recipe(html: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            try:  # Some sites leave trailing commas or control characters.
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw.strip()), strict=False)
            except json.JSONDecodeError:
                continue
        for node in _walk_ld(data):
            types = _as_list(node.get("@type"))
            if any(str(t).lower().endswith("recipe") for t in types):
                return node
    return None


def from_jsonld(node: dict, url: Optional[str] = None) -> Extracted:
    hints = []
    for key in ("recipeCategory", "recipeCuisine"):
        hints += [_clean(v) for v in _as_list(node.get(key))]
    keywords = node.get("keywords")
    if isinstance(keywords, str):
        hints += [k.strip() for k in keywords.split(",") if k.strip()]
    elif isinstance(keywords, list):
        hints += [_clean(k) for k in keywords]
    for diet in _as_list(node.get("suitableForDiet")):
        name = str(diet).rsplit("/", 1)[-1].replace("Diet", "")
        hints.append(re.sub(r"(?<=[a-z])(?=[A-Z])", "-", name))  # GlutenFree -> Gluten-Free
    nutrition = {}
    if isinstance(node.get("nutrition"), dict):
        for k, v in node["nutrition"].items():
            if not k.startswith("@") and v:
                label = re.sub(r"Content$", "", k)
                nutrition[label] = _clean(v)
    servings = node.get("recipeYield")
    if isinstance(servings, list):
        servings = next((s for s in servings if isinstance(s, str) and not s.isdigit()), servings[0] if servings else None)
    prep = parse_duration(node.get("prepTime"))
    cook = parse_duration(node.get("cookTime"))
    total = parse_duration(node.get("totalTime")) or ((prep or 0) + (cook or 0) or None)
    return Extracted(
        title=_clean(node.get("name")),
        description=_clean(node.get("description")),
        author=_author(node.get("author")),
        image_url=_image(node.get("image")),
        servings=_clean(servings) or None,
        prep_time=prep,
        cook_time=cook,
        total_time=total,
        ingredients=[_clean(i) for i in _as_list(node.get("recipeIngredient") or node.get("ingredients")) if _clean(i)],
        directions=_instructions(node.get("recipeInstructions")),
        nutrition=nutrition,
        hints=[h for h in hints if h],
        source_url=url,
        structured=True,
    )


def page_meta(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    meta = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        if key and tag.get("content") and key.lower() not in meta:
            meta[key.lower()] = tag["content"]
    if soup.title and soup.title.string:
        meta.setdefault("title", soup.title.string.strip())
    return meta


# ----------------------------------------------------------- caption parsing

ING_HEADING = re.compile(
    r"^\W*(ingredients?|you(?:'ll| will)? need|what you(?:'ll)? need|shopping list|for the [\w\s]+:)\W*",
    re.I,
)
DIR_HEADING = re.compile(
    r"^\W*(instructions?|directions?|method|steps?|how to make( it)?|preparation|prep|to make|recipe steps)\b\W*",
    re.I,
)
NOTE_HEADING = re.compile(r"^\W*(notes?|tips?|storage|substitutions?)\b\W*:?", re.I)
BULLET = re.compile(r"^\s*(?:[-•*▪️◦✔️✅🔸🔹▫️⁃–—]+|\d+[.)])\s*")
NUMBERED = re.compile(r"^\s*(?:step\s*)?\d+\s*[.):-]\s*|^\s*[1-9]️⃣\s*", re.I)
QUANTITY = re.compile(
    r"^\W*(?:\d+(?:[/.]\d+)?|[½¼¾⅓⅔⅛])\s*(?:-\s*\d+\s*)?"
    r"(?:cups?|c\b|tbsps?|tablespoons?|tsps?|teaspoons?|oz|ounces?|lbs?|pounds?|g\b|grams?|kg|ml|l\b"
    r"|liters?|cloves?|cans?|large|medium|small|slices?|sticks?|packages?|bunch|whole|pinch|[½¼¾⅓⅔⅛]|\s)"
    r"|^\W*(?:a |an )?(?:pinch|handful|dash|splash|drizzle)\b",
    re.I,
)
SERVES = re.compile(r"\b(?:serves|servings?|makes|yield)\s*:?\s*(\d+(?:\s*-\s*\d+)?(?:\s+\w+)?)", re.I)
TIME_LINE = re.compile(r"\b(prep|cook|bake|total)\s*(?:time\s*:?|:)\s*([\d.]+\s*(?:h\w*|m\w*)(?:\s*\d+\s*m\w*)?)", re.I)
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿️‍⭐⬆↔-↪⤴⤵〰〽]+"
)


def _strip_line(line: str) -> str:
    line = EMOJI.sub("", line)
    return re.sub(r"\s+", " ", line).strip(" -–—•*:|")


def _is_hashtag_line(line: str) -> bool:
    words = line.split()
    return bool(words) and sum(w.startswith("#") or w.startswith("@") for w in words) / len(words) > 0.6


def parse_caption(text: str) -> Extracted:
    """Best-effort structure from a social-media caption or pasted recipe text."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r", "").split("\n")]
    title = ""
    description: list[str] = []
    ingredients: list[str] = []
    directions: list[str] = []
    notes: list[str] = []
    section = None
    ex = Extracted(raw_text=text or "")

    for raw in lines:
        if not raw.strip():
            continue
        m = TIME_LINE.findall(raw)
        for kind, value in m:
            minutes = parse_duration(value)
            attr = {"prep": "prep_time", "cook": "cook_time", "bake": "cook_time", "total": "total_time"}[kind.lower()]
            if minutes and getattr(ex, attr) is None:
                setattr(ex, attr, minutes)
        serves = SERVES.search(raw)
        if serves and not ex.servings:
            ex.servings = serves.group(1).strip()
        if (m or serves) and len(raw.strip()) < 60 and section != "directions":
            continue  # a "Prep: 10 min | Serves 4" metadata line
        if _is_hashtag_line(raw):
            continue

        stripped = EMOJI.sub("", raw).strip()
        if ING_HEADING.match(stripped) and len(stripped) < 60:
            section = "ingredients"
            rest = ING_HEADING.sub("", stripped).strip(" :")
            if rest and section and len(rest) > 2 and rest.lower() != stripped.lower():
                ingredients.append(_strip_line(rest))
            elif re.match(r"^\W*for the", stripped, re.I):
                ingredients.append("## " + _strip_line(stripped).rstrip(":"))
            continue
        if DIR_HEADING.match(stripped) and len(stripped) < 60 and not QUANTITY.match(stripped):
            section = "directions"
            rest = DIR_HEADING.sub("", stripped).strip(" :")
            if len(rest) > 15:
                directions.append(_strip_line(rest))
            continue
        if NOTE_HEADING.match(stripped) and len(stripped) < 40:
            section = "notes"
            continue

        clean = _strip_line(BULLET.sub("", raw))
        if not clean:
            continue
        if section == "ingredients":
            # A numbered line with a verb after the ingredient list means the steps started.
            if NUMBERED.match(raw) and not QUANTITY.match(BULLET.sub("", raw)) and len(clean) > 30:
                section = "directions"
                directions.append(clean)
            else:
                ingredients.append(clean)
        elif section == "directions":
            directions.append(clean)
        elif section == "notes":
            notes.append(clean)
        elif not title:
            # "Creamy Tuscan Chicken 🍗 the dinner my family loves!" -> title + blurb
            head, _, rest = EMOJI.sub("\x00", raw).partition("\x00")
            head = _strip_line(head)
            if not head:
                head, rest = clean, ""
            title = head
            rest = _strip_line(rest.replace("\x00", " "))
            if rest:
                description.append(rest)
        elif NUMBERED.match(raw) and len(clean) > 25:
            directions.append(clean)
        elif BULLET.match(raw) or QUANTITY.match(raw):
            ingredients.append(clean)
        else:
            description.append(clean)

    # Captions that run the steps together in one paragraph: split on sentences.
    if len(directions) == 1 and len(directions[0]) > 200:
        directions = [s.strip() for s in re.split(r"(?<=[.!])\s+(?=[A-Z])", directions[0]) if s.strip()]

    title = re.sub(r"#\w+", "", title).strip()
    if len(title) > 90:  # a first line that is really a sentence of prose
        description.insert(0, title)
        title = re.split(r"[.!?:]", title)[0][:80].strip()
    ex.title = title
    ex.description = "\n".join(description + notes)
    ex.ingredients = ingredients
    ex.directions = directions
    if ex.total_time is None and (ex.prep_time or ex.cook_time):
        ex.total_time = (ex.prep_time or 0) + (ex.cook_time or 0)
    return ex


def caption_links(text: str) -> list[str]:
    """Outside links mentioned in a caption ("full recipe at ...")."""
    links = []
    for url in URL_RE.findall(text or ""):
        url = normalize_url(url)
        if platform_for(url) == "web" and is_saveable(url):
            links.append(url)
    # Bare domains like "example.com/lasagna" without a scheme.
    for m in re.finditer(r"(?<![@/\w.-])((?:[\w-]+\.)+(?:com|net|org|co|blog|kitchen|recipes)(?:/[^\s)]*)?)", text or ""):
        url = "https://" + m.group(1).rstrip(".,!")
        already = any(m.group(1) in link for link in links)
        if "/" in m.group(1) and not already and platform_for(url) == "web":
            links.append(url)
    return links


# ----------------------------------------------------------------- fetching


class Fetcher:
    def __init__(self, client: Optional[httpx.Client] = None, timeout: float = 15.0):
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
            timeout=timeout,
        )

    def get(self, url: str) -> Optional[str]:
        try:
            resp = self.client.get(url)
        except httpx.HTTPError:
            return None
        if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", "html"):
            return None
        return resp.text

    # --- per-platform

    def web_page(self, url: str) -> Optional[Extracted]:
        html = self.get(url)
        if not html:
            return None
        node = find_jsonld_recipe(html)
        meta = page_meta(html)
        if node:
            ex = from_jsonld(node, url)
            ex.image_url = ex.image_url or meta.get("og:image")
            ex.title = ex.title or meta.get("og:title", "")
            return ex
        text = meta.get("og:description") or meta.get("description") or ""
        return Extracted(
            title=_clean(meta.get("og:title") or meta.get("title")),
            description=_clean(text),
            image_url=meta.get("og:image"),
            source_url=url,
            raw_text=text,
        )

    def instagram_post(self, url: str) -> Optional[Extracted]:
        m = INSTAGRAM_POST.search(url)
        if not m:
            return None
        code = m.group(2)
        # The embed page is public for public posts and includes the caption.
        html = self.get(f"https://www.instagram.com/p/{code}/embed/captioned/")
        if html:
            ex = parse_instagram_embed(html)
            if ex and ex.raw_text:
                ex.source_url = url
                return ex
        html = self.get(url)
        if not html:
            return None
        meta = page_meta(html)
        caption = instagram_caption_from_meta(meta.get("og:description") or meta.get("description") or "")
        if not caption:
            return None
        return Extracted(raw_text=caption, image_url=meta.get("og:image"), source_url=url,
                         author=_instagram_author(meta.get("og:title", "")))

    def facebook_post(self, url: str) -> Optional[Extracted]:
        html = self.get(url)
        if not html:
            return None
        meta = page_meta(html)
        text = meta.get("og:description") or meta.get("description") or ""
        if "log in" in (meta.get("og:title", "") + meta.get("title", "")).lower() and not text:
            return None
        return Extracted(title=_clean(meta.get("og:title")), raw_text=_clean(text) if "<" in text else text,
                         image_url=meta.get("og:image"), source_url=url)


def parse_instagram_embed(html: str) -> Optional[Extracted]:
    soup = BeautifulSoup(html, "html.parser")
    caption_div = soup.find(class_=re.compile(r"\bCaption\b"))
    author = None
    user = soup.find(class_=re.compile(r"UsernameText|CaptionUsername"))
    if user:
        author = user.get_text(strip=True)
    image = soup.find("img", class_=re.compile("EmbeddedMediaImage"))
    if caption_div is None:
        return None
    for br in caption_div.find_all("br"):
        br.replace_with("\n")
    for extra in caption_div.find_all(class_=re.compile(r"CaptionComments|CaptionUsername")):
        extra.decompose()
    text = caption_div.get_text()
    text = re.sub(r"\n?View all \d+ comments\s*$", "", text.strip())
    return Extracted(raw_text=text.strip(), author=author, image_url=image.get("src") if image else None)


def instagram_caption_from_meta(desc: str) -> str:
    """og:description looks like: '1,234 likes, 56 comments - user on May 1, 2024: "caption"'."""
    desc = html_lib.unescape(desc)
    m = re.search(r':\s*"(.*)"\.?\s*$', desc, re.S)
    if m:
        return m.group(1).strip()
    return re.sub(r"^[\d,.KkMm]+ (?:likes?|Likes?),.*? - ", "", desc).strip()


def _instagram_author(og_title: str) -> Optional[str]:
    m = re.match(r"(.+?) on Instagram", og_title)
    return m.group(1).strip() if m else None
