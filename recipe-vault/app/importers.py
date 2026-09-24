"""Read saved posts out of Facebook and Instagram "Download your information" exports.

Neither Meta API exposes a person's saved posts, so the export is the one
supported way to get them in bulk. The export's layout has changed several
times over the years, so rather than depending on exact key names we walk the
JSON and treat each list element that contains a link as one saved item.
Accepted inputs: the export .zip itself, any .json/.html file from it, or a
plain text/CSV list of links.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Iterable, Iterator, Optional
from urllib.parse import parse_qs, urlparse, urlunparse

from .models import SavedItem

URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")

INSTAGRAM_POST = re.compile(r"instagram\.com/(?:[\w.]+/)?(p|reel|reels|tv)/([\w-]+)", re.I)
FACEBOOK_HOSTS = ("facebook.com", "fb.com", "fb.watch", "m.facebook.com")
# Meta-owned pages that are never recipes (profiles, help pages, CDN files).
SKIP_PATTERNS = re.compile(
    r"(facebook\.com/(help|policies|privacy|settings|legal)|fbcdn\.net|cdninstagram\.com"
    r"|instagram\.com/(accounts|explore|about|legal)|static\.xx\.fbcdn)",
    re.I,
)


def fix_mojibake(text: str) -> str:
    """Meta exports write UTF-8 bytes as if they were Latin-1 ("Ã©" for "é")."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _iso(ts: Any) -> Optional[str]:
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return None
    if ts > 1e12:  # milliseconds
        ts /= 1000
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def normalize_url(url: str) -> str:
    """Canonical form so the same post saved twice (or re-imported) is de-duplicated."""
    url = url.strip().rstrip(".,")
    m = INSTAGRAM_POST.search(url)
    if m:
        kind = "reel" if m.group(1).lower() in ("reel", "reels") else m.group(1).lower()
        return f"https://www.instagram.com/{kind}/{m.group(2)}/"
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("l.facebook.com") or host.startswith("lm.facebook.com"):
        # Facebook wraps outbound links: l.facebook.com/l.php?u=<real url>
        real = parse_qs(parsed.query).get("u")
        if real:
            return normalize_url(real[0])
    # Drop tracking parameters but keep ones that identify content (e.g. story_fbid).
    query = "&".join(
        p for p in parsed.query.split("&")
        if p and not re.match(r"(utm_|fbclid|igsh|igshid|mibextid|__cft__|__tn__|ref=|rdid|share_url)", p)
    )
    return urlunparse((parsed.scheme.lower(), host, parsed.path, "", query, ""))


def platform_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "instagram.com" in host:
        return "instagram"
    if any(host.endswith(h) for h in FACEBOOK_HOSTS):
        return "facebook"
    return "web"


def is_saveable(url: str) -> bool:
    if SKIP_PATTERNS.search(url):
        return False
    host = urlparse(url).netloc.lower()
    if "instagram.com" in host:
        return bool(INSTAGRAM_POST.search(url))  # skip bare profile links
    return host != ""


# ---------------------------------------------------------------- JSON walking


def _strings(obj: Any) -> Iterator[tuple[str, str]]:
    """Yield (key, string) pairs anywhere in obj."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                yield k, v
            else:
                yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _numbers(obj: Any, key: str) -> Iterator[Any]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, (int, float)):
                yield v
            else:
                yield from _numbers(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _numbers(v, key)


def _find_key(obj: Any, key: str) -> Optional[Any]:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_key(v, key)
            if found is not None:
                return found
    return None


def _collection_header(entry: dict) -> Optional[str]:
    """Instagram's saved_collections.json lists a header row per collection
    (a "Name" with no link) followed by that collection's posts."""
    smd = entry.get("string_map_data") or {}
    name = smd.get("Name") if isinstance(smd, dict) else None
    if isinstance(name, dict) and name.get("value") and not name.get("href"):
        return name["value"]
    for lv in entry.get("label_values") or []:
        if isinstance(lv, dict) and lv.get("label") == "Name" and lv.get("value") and not lv.get("href"):
            return lv["value"]
    return None


def _entry_to_item(entry: Any, platform_hint: Optional[str], collection: Optional[str]) -> Optional[SavedItem]:
    urls = [v for k, v in _strings(entry) if k in ("href", "url", "uri", "link") or URL_RE.fullmatch(v)]
    urls += [m for _, v in _strings(entry) for m in URL_RE.findall(v)]
    candidates = [normalize_url(fix_mojibake(u)) for u in urls if u.startswith("http")]
    candidates = [u for u in candidates if is_saveable(u)]
    if not candidates:
        return None
    # Prefer an Instagram post or external recipe link over a Facebook permalink.
    candidates.sort(key=lambda u: {"instagram": 0, "web": 1, "facebook": 2}[platform_for(u)])
    url = candidates[0]

    ext = _find_key(entry, "external_context")
    title = ext.get("name") if isinstance(ext, dict) else None
    author = None
    if isinstance(entry, dict):
        raw_title = entry.get("title")
        # Instagram puts the post author in "title"; Facebook puts "X saved a link."
        # (or, in collections files, the collection name).
        if (isinstance(raw_title, str) and raw_title and raw_title != collection
                and " saved " not in raw_title and not raw_title.endswith(".")):
            author = raw_title
        smd = entry.get("string_map_data")
        if isinstance(smd, dict) and not author:
            for field in smd.values():
                if isinstance(field, dict) and field.get("href") and field.get("value"):
                    author = field["value"]
                    break
    caption = None
    for key, value in _strings(entry):
        if key in ("description", "text", "post", "caption") and len(value) > 20:
            caption = value
            break
    timestamps = list(_numbers(entry, "timestamp"))
    platform = platform_for(url)
    if platform == "web" and platform_hint:
        platform = platform_hint  # an outside link saved *on* Facebook/Instagram
    return SavedItem(
        platform=platform,
        url=url,
        author=fix_mojibake(author) if author else None,
        title=fix_mojibake(title) if title else None,
        caption=fix_mojibake(caption) if caption else None,
        collection=fix_mojibake(collection) if collection else None,
        saved_at=_iso(timestamps[0]) if timestamps else None,
    )


def _entries(data: Any) -> Iterator[Any]:
    """The per-item lists: top-level lists, or lists one level into a dict."""
    if isinstance(data, list):
        yield from data
    elif isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                yield from value
            elif isinstance(value, dict):
                yield from _entries(value)


def parse_json(data: Any, platform_hint: Optional[str] = None, collection_hint: Optional[str] = None) -> list[SavedItem]:
    items: list[SavedItem] = []
    collection = collection_hint
    for entry in _entries(data):
        if isinstance(entry, dict):
            header = _collection_header(entry)
            if header:
                collection = header
                continue
            # Facebook collections: {"title": "Recipes", "attachments": [...]}.
            if (collection_hint and isinstance(entry.get("title"), str) and entry.get("attachments")
                    and " saved " not in entry["title"]):
                collection = entry["title"]
        item = _entry_to_item(entry, platform_hint, collection)
        if item:
            items.append(item)
    return items


# ---------------------------------------------------------------- HTML exports


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, "".join(self._text).strip()))
            self._href = None


def parse_html(html: str, platform_hint: Optional[str] = None) -> list[SavedItem]:
    parser = _LinkParser()
    parser.feed(html)
    items = []
    for href, text in parser.links:
        if not href.startswith("http"):
            continue
        url = normalize_url(href)
        if not is_saveable(url):
            continue
        platform = platform_for(url)
        if platform == "web" and platform_hint:
            platform = platform_hint
        is_title = text and not text.startswith("http")
        items.append(SavedItem(platform=platform, url=url, title=text if is_title else None))
    return items


def parse_text(text: str, platform_hint: Optional[str] = None) -> list[SavedItem]:
    """A plain list of links, one per line, or a CSV with a url column."""
    items = []
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error:
        rows = []
    if rows and any("url" in (k or "").lower() for k in rows[0]):
        for row in rows:
            url_key = next(k for k in row if k and "url" in k.lower())
            if row.get(url_key, "").startswith("http"):
                url = normalize_url(row[url_key])
                if is_saveable(url):
                    items.append(SavedItem(
                        platform=platform_for(url) if platform_for(url) != "web" else (platform_hint or "web"),
                        url=url, title=row.get("title") or row.get("name"),
                        collection=row.get("collection"), caption=row.get("caption"),
                    ))
        return items
    for url in URL_RE.findall(text):
        url = normalize_url(url)
        if is_saveable(url):
            platform = platform_for(url)
            items.append(SavedItem(platform=platform if platform != "web" else (platform_hint or "web"), url=url))
    return items


# ---------------------------------------------------------------- entry point


def _hint_from_name(name: str, data: Any = None) -> Optional[str]:
    lowered = name.lower()
    if "instagram" in lowered:
        return "instagram"
    if "facebook" in lowered:
        return "facebook"
    if isinstance(data, dict):
        keys = " ".join(data.keys()).lower()
        if "saved_saved" in keys:
            return "instagram"
        if "saves" in keys or "collections_v2" in keys:
            return "facebook"
    return None


def _relevant(name: str) -> bool:
    lowered = name.lower()
    return any(k in lowered for k in ("saved", "collection")) and lowered.endswith((".json", ".html", ".htm"))


def parse_file(filename: str, content: bytes, platform_hint: Optional[str] = None) -> list[SavedItem]:
    """Parse an uploaded export file of any supported kind."""
    name = filename.lower()
    if name.endswith(".zip") or content[:2] == b"PK":
        items: list[SavedItem] = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = [n for n in zf.namelist() if _relevant(n)]
            # A whole-account zip holds thousands of files; only the saved ones matter.
            if not names:
                names = [n for n in zf.namelist() if n.lower().endswith(".json")]
            zip_hint = platform_hint or _hint_from_name(filename)
            for inner in names:
                items += parse_file(inner, zf.read(inner), zip_hint)
        return dedupe(items)
    text = content.decode("utf-8", errors="replace")
    if name.endswith((".html", ".htm")) or text.lstrip().startswith("<"):
        return dedupe(parse_html(text, platform_hint or _hint_from_name(filename)))
    if name.endswith(".json") or text.lstrip()[:1] in "[{":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return dedupe(parse_text(text, platform_hint))
        hint = platform_hint or _hint_from_name(filename, data)
        collection_hint = "__collections__" if "collection" in name else None
        items = parse_json(data, hint, collection_hint)
        for item in items:
            if item.collection == "__collections__":
                item.collection = None
        return dedupe(items)
    return dedupe(parse_text(text, platform_hint))


def dedupe(items: Iterable[SavedItem]) -> list[SavedItem]:
    """Merge duplicates, keeping whichever copy knows the collection/caption."""
    by_url: dict[str, SavedItem] = {}
    for item in items:
        existing = by_url.get(item.url)
        if existing is None:
            by_url[item.url] = item
            continue
        for field in ("author", "title", "caption", "collection", "saved_at"):
            if getattr(existing, field) is None and getattr(item, field) is not None:
                setattr(existing, field, getattr(item, field))
    return list(by_url.values())
