"use strict";

// ------------------------------------------------------------------ helpers

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const view = $("#view");

const KINDS = [
  ["meal_type", "Meal type"],
  ["course", "Course"],
  ["cuisine", "Cuisine"],
  ["diet", "Diet"],
  ["main_ingredient", "Main ingredient"],
  ["method", "Method"],
  ["collection", "Collection"],
  ["tag", "Tags"],
];
const KIND_LABEL = Object.fromEntries(KINDS);
const PLATFORM_ICON = { instagram: "📷", facebook: "📘", web: "🌐", manual: "✍️" };
const MEAL_EMOJI = { Breakfast: "🥞", Lunch: "🥪", Dinner: "🍝", Dessert: "🍰", Snack: "🥨", Appetizer: "🧆", "Side Dish": "🥗", Drink: "🍹" };
const STATUS_LABEL = {
  pending: "Waiting", processing: "Working…", needs_review: "Needs review", imported: "Imported",
  not_recipe: "No recipe found", failed: "Couldn't read", skipped: "Skipped",
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function snippetHtml(snippet) {
  // The server marks hits with \x01 ... \x02 so the text can be escaped safely first.
  return esc(snippet).replace(/\x01/g, "<mark>").replace(/\x02/g, "</mark>");
}

function minutes(m) {
  if (!m) return "";
  const h = Math.floor(m / 60), r = m % 60;
  return h ? `${h} hr${r ? ` ${r} min` : ""}` : `${r} min`;
}

async function api(path, options = {}) {
  const opts = { ...options };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error((data && data.detail && (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))) || res.statusText);
  return data;
}

let toastTimer;
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
}

function parseHash() {
  const raw = location.hash.slice(1) || "/";
  const [path, query = ""] = raw.split("?");
  return { path, params: new URLSearchParams(query) };
}

function setHash(path, params) {
  const qs = params && params.toString();
  const next = "#" + path + (qs ? "?" + qs : "");
  if (location.hash !== next) location.hash = next;
  else route();
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ------------------------------------------------------------------ search bar

const searchInput = $("#search");
const suggestionsEl = $("#suggestions");

function currentParams() {
  const { path, params } = parseHash();
  return path === "/" ? params : new URLSearchParams();
}

function runSearch(q) {
  const params = currentParams();
  if (q) params.set("q", q); else params.delete("q");
  setHash("/", params);
}

const liveSearch = debounce(() => runSearch(searchInput.value.trim()), 250);
const loadSuggestions = debounce(async () => {
  const q = searchInput.value.trim();
  if (q.length < 2) { suggestionsEl.hidden = true; return; }
  const list = await api(`/api/suggest?q=${encodeURIComponent(q)}`).catch(() => []);
  if (!list.length || document.activeElement !== searchInput) { suggestionsEl.hidden = true; return; }
  suggestionsEl.innerHTML = list.map(s => `<li>${esc(s)}</li>`).join("");
  suggestionsEl.hidden = false;
}, 150);

searchInput.addEventListener("input", () => { liveSearch(); loadSuggestions(); });
searchInput.addEventListener("blur", () => setTimeout(() => { suggestionsEl.hidden = true; }, 150));
searchInput.addEventListener("keydown", e => {
  const items = $$("li", suggestionsEl);
  const active = items.findIndex(li => li.classList.contains("active"));
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (suggestionsEl.hidden || !items.length) return;
    e.preventDefault();
    items.forEach(li => li.classList.remove("active"));
    const next = e.key === "ArrowDown" ? (active + 1) % items.length : (active - 1 + items.length) % items.length;
    items[next].classList.add("active");
  } else if (e.key === "Enter" && active >= 0 && !suggestionsEl.hidden) {
    e.preventDefault();
    searchInput.value = items[active].textContent;
    suggestionsEl.hidden = true;
    runSearch(searchInput.value);
  } else if (e.key === "Escape") {
    suggestionsEl.hidden = true;
  }
});
suggestionsEl.addEventListener("mousedown", e => {
  const li = e.target.closest("li");
  if (!li) return;
  searchInput.value = li.textContent;
  suggestionsEl.hidden = true;
  runSearch(searchInput.value);
});
$("#search-form").addEventListener("submit", e => {
  e.preventDefault();
  suggestionsEl.hidden = true;
  runSearch(searchInput.value.trim());
});
document.addEventListener("keydown", e => {
  // "/" jumps to search from anywhere, like most search-first apps.
  if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
    e.preventDefault();
    searchInput.focus();
    searchInput.select();
  }
});

// ------------------------------------------------------------------ browse / search view

const expandedFacets = new Set();

function cardHtml(r) {
  const meal = r.categories.meal_type[0];
  const thumb = r.image_url
    ? `<div class="thumb" style="background-image:url('${esc(r.image_url)}')"></div>`
    : `<div class="thumb">${MEAL_EMOJI[meal] || "🍽️"}</div>`;
  const time = r.total_time || ((r.prep_time || 0) + (r.cook_time || 0));
  const bits = [
    time ? `⏱ ${minutes(time)}` : "",
    meal ? esc(meal) : "",
    r.categories.cuisine[0] ? esc(r.categories.cuisine[0]) : "",
    r.rating ? "★".repeat(r.rating) : "",
  ].filter(Boolean);
  return `<a class="card" href="#/recipe/${r.id}">
    ${thumb}
    <div class="body">
      <h3>${r.favorite ? '<span class="fav">♥</span> ' : ""}${esc(r.title)}</h3>
      <div class="meta"><span title="${esc(r.source_platform || "")}">${PLATFORM_ICON[r.source_platform] || ""}</span>${bits.map(b => `<span>${b}</span>`).join("")}</div>
      ${r.snippet ? `<div class="snippet">${snippetHtml(r.snippet)}</div>` : ""}
    </div>
  </a>`;
}

function facetHtml(kind, label, entries, params) {
  const selected = params.getAll(kind);
  const merged = [...entries];
  for (const value of selected) {
    if (!merged.some(e => e.value.toLowerCase() === value.toLowerCase())) merged.unshift({ value, count: 0 });
  }
  if (!merged.length) return "";
  const limit = expandedFacets.has(kind) ? Infinity : 8;
  const rows = merged.slice(0, limit).map(e => {
    const on = selected.some(s => s.toLowerCase() === e.value.toLowerCase());
    return `<button data-kind="${kind}" data-value="${esc(e.value)}" class="${on ? "on" : ""}">
      <span>${esc(e.value)}</span><span class="count">${e.count}</span></button>`;
  }).join("");
  const more = merged.length > 8
    ? `<button class="more" data-more="${kind}">${expandedFacets.has(kind) ? "Show less" : `Show all ${merged.length}`}</button>` : "";
  return `<div class="facet"><h4>${label}</h4>${rows}${more}</div>`;
}

async function renderBrowse(params) {
  searchInput.value = params.get("q") || "";
  const data = await api("/api/recipes?" + params.toString());
  const active = [];
  for (const [kind, label] of KINDS) {
    for (const value of params.getAll(kind)) active.push({ kind, value, label });
  }
  const filtersOn = active.length || params.get("favorite") || params.get("max_time");
  const sort = params.get("sort") || "relevance";

  let results;
  if (data.results.length) {
    results = `<div class="grid">${data.results.map(cardHtml).join("")}</div>`;
    if (data.total > data.results.length) {
      results += `<p class="empty"><button id="load-more">Show more (${data.total - data.results.length} left)</button></p>`;
    }
  } else if (params.get("q") || filtersOn) {
    results = `<div class="empty"><h2>No recipes match</h2><p>Try fewer words or remove a filter.</p></div>`;
  } else {
    results = `<div class="empty"><h2>Your recipe box is empty</h2>
      <p>Pull in everything you've saved on Instagram and Facebook, or add a recipe by hand.</p>
      <p><a class="button primary" href="#/import">Import saved posts</a> <a class="button" href="#/new">Add a recipe</a></p></div>`;
  }

  view.innerHTML = `
    <div class="browse">
      <aside class="facets" id="facets">
        ${KINDS.map(([k, label]) => facetHtml(k, label, data.facets[k] || [], params)).join("")}
      </aside>
      <section>
        <div class="toolbar">
          <button class="filters-toggle small" id="filters-toggle">☰ Filters${active.length ? ` (${active.length})` : ""}</button>
          <button class="chip ${params.get("favorite") ? "on" : ""}" data-toggle="favorite" data-on="true">♥ Favorites</button>
          <button class="chip ${params.get("max_time") === "30" ? "on" : ""}" data-toggle="max_time" data-on="30">⏱ 30 min or less</button>
          ${active.map(a => `<button class="chip on" data-kind="${a.kind}" data-value="${esc(a.value)}" title="${esc(a.label)}">${esc(a.value)} <span class="x">×</span></button>`).join("")}
          ${filtersOn ? `<button class="chip" id="clear-filters">Clear all</button>` : ""}
          <span class="spacer"></span>
          <span class="result-count">${data.total} recipe${data.total === 1 ? "" : "s"}</span>
          <select id="sort" aria-label="Sort">
            ${[["relevance", params.get("q") ? "Best match" : "Recently saved"], ["newest", "Recently added"], ["title", "A–Z"], ["rating", "Top rated"], ["quickest", "Quickest"]]
              .map(([v, l]) => `<option value="${v}" ${v === sort ? "selected" : ""}>${l}</option>`).join("")}
          </select>
        </div>
        ${results}
      </section>
    </div>`;

  const toggleParam = (kind, value) => {
    const next = new URLSearchParams(params);
    const values = next.getAll(kind);
    next.delete(kind);
    const has = values.some(v => v.toLowerCase() === value.toLowerCase());
    for (const v of values) if (v.toLowerCase() !== value.toLowerCase()) next.append(kind, v);
    if (!has) next.append(kind, value);
    next.delete("limit");
    setHash("/", next);
  };
  $$("[data-kind]", view).forEach(b => b.addEventListener("click", () => toggleParam(b.dataset.kind, b.dataset.value)));
  $$("[data-more]", view).forEach(b => b.addEventListener("click", () => {
    const k = b.dataset.more;
    expandedFacets.has(k) ? expandedFacets.delete(k) : expandedFacets.add(k);
    renderBrowse(params);
  }));
  $$("[data-toggle]", view).forEach(b => b.addEventListener("click", () => {
    const next = new URLSearchParams(params);
    if (next.get(b.dataset.toggle)) next.delete(b.dataset.toggle); else next.set(b.dataset.toggle, b.dataset.on);
    setHash("/", next);
  }));
  $("#sort", view).addEventListener("change", e => {
    const next = new URLSearchParams(params);
    next.set("sort", e.target.value);
    setHash("/", next);
  });
  $("#clear-filters", view)?.addEventListener("click", () => {
    const next = new URLSearchParams();
    if (params.get("q")) next.set("q", params.get("q"));
    setHash("/", next);
  });
  $("#filters-toggle", view).addEventListener("click", () => $("#facets").classList.toggle("open"));
  $("#load-more", view)?.addEventListener("click", () => {
    const next = new URLSearchParams(params);
    next.set("limit", String(Number(params.get("limit") || 60) + 60));
    setHash("/", next);
  });
}

// ------------------------------------------------------------------ recipe detail

function listHtml(items, cls, checkable) {
  return items.map(line => {
    if (line.startsWith("## ")) return `<li class="section">${esc(line.slice(3))}</li>`;
    return checkable
      ? `<li><input type="checkbox" aria-label="Got it"><span>${esc(line)}</span></li>`
      : `<li>${esc(line)}</li>`;
  }).join("");
}

async function renderRecipe(id) {
  const r = await api(`/api/recipes/${id}`);
  document.title = `${r.title} · Recipe Vault`;
  const needsReview = r.categories.tag.includes("Needs Review");
  const facts = [
    ["Servings", r.servings], ["Prep", minutes(r.prep_time)], ["Cook", minutes(r.cook_time)], ["Total", minutes(r.total_time)],
  ].filter(([, v]) => v);
  const cats = KINDS.flatMap(([kind]) => r.categories[kind].map(v =>
    `<a class="chip" href="#/?${kind}=${encodeURIComponent(v)}"><span class="kind">${esc(KIND_LABEL[kind])}</span>${esc(v)}</a>`)).join("");
  const nutrition = Object.entries(r.nutrition || {});
  const meal = r.categories.meal_type[0];

  view.innerHTML = `
    <article class="recipe">
      ${needsReview ? `<div class="review-banner">⚠️ This came from a caption we couldn't fully read. Check the ingredients and steps, then save it to clear this flag. <a href="#/edit/${r.id}">Review now →</a></div>` : ""}
      <div class="recipe-head">
        ${r.image_url ? `<div class="hero" style="background-image:url('${esc(r.image_url)}')"></div>` : `<div class="hero">${MEAL_EMOJI[meal] || "🍽️"}</div>`}
        <div>
          <h1>${esc(r.title)}</h1>
          <div class="stars" id="stars">${[1, 2, 3, 4, 5].map(n => `<button data-n="${n}" class="${n <= r.rating ? "on" : ""}" aria-label="${n} stars">★</button>`).join("")}</div>
          ${r.author ? `<div>by <b>${esc(r.author)}</b></div>` : ""}
          ${r.source_url ? `<div>${PLATFORM_ICON[r.source_platform] || ""} <a href="${esc(r.source_url)}" target="_blank" rel="noopener">View original post</a></div>` : ""}
          ${facts.length ? `<div class="facts">${facts.map(([k, v]) => `<div><b>${k}</b>${esc(v)}</div>`).join("")}</div>` : ""}
          ${r.description ? `<p class="description">${esc(r.description)}</p>` : ""}
          <div class="cats">${cats}</div>
          <div class="actions">
            <button id="fav">${r.favorite ? "♥ Favorited" : "♡ Favorite"}</button>
            <a class="button" href="#/edit/${r.id}">✎ Edit</a>
            <button id="recat" title="Re-run automatic categorization">✨ Auto-categorize</button>
            <button id="print">🖨 Print</button>
            <button id="del" class="danger">Delete</button>
          </div>
        </div>
      </div>
      <div class="columns">
        <section class="panel">
          <h2>Ingredients</h2>
          ${r.ingredients.length ? `<ul class="ingredients">${listHtml(r.ingredients, "ingredients", true)}</ul>` : `<p class="description">No ingredients yet. <a href="#/edit/${r.id}">Add them</a>.</p>`}
        </section>
        <section class="panel">
          <h2>Directions</h2>
          ${r.directions.length ? `<ol class="directions">${listHtml(r.directions, "directions", false)}</ol>` : `<p class="description">No directions yet.</p>`}
          ${r.notes ? `<h3>Notes</h3><p class="description">${esc(r.notes)}</p>` : ""}
          ${nutrition.length ? `<h3>Nutrition</h3><p class="description">${nutrition.map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ")}</p>` : ""}
        </section>
      </div>
    </article>`;

  $$(".ingredients input", view).forEach(cb => cb.addEventListener("change", () => cb.parentElement.classList.toggle("checked", cb.checked)));
  $$("#stars button", view).forEach(b => b.addEventListener("click", async () => {
    const n = Number(b.dataset.n);
    await api(`/api/recipes/${id}`, { method: "PATCH", body: { rating: n === r.rating ? 0 : n } });
    renderRecipe(id);
  }));
  $("#fav", view).addEventListener("click", async () => {
    await api(`/api/recipes/${id}`, { method: "PATCH", body: { favorite: !r.favorite } });
    renderRecipe(id);
  });
  $("#recat", view).addEventListener("click", async e => {
    e.target.disabled = true;
    e.target.textContent = "Categorizing…";
    await api(`/api/recipes/${id}/recategorize`, { method: "POST" });
    toast("Categories updated");
    renderRecipe(id);
  });
  $("#print", view).addEventListener("click", () => window.print());
  $("#del", view).addEventListener("click", async () => {
    if (!confirm(`Delete “${r.title}”? This can't be undone.`)) return;
    await api(`/api/recipes/${id}`, { method: "DELETE" });
    toast("Recipe deleted");
    location.hash = "#/";
  });
}

// ------------------------------------------------------------------ edit / new

async function renderEdit(id) {
  const r = id ? await api(`/api/recipes/${id}`) : {
    title: "", description: "", source_url: "", author: "", image_url: "", servings: "",
    prep_time: null, cook_time: null, total_time: null, ingredients: [], directions: [], notes: "",
    categories: Object.fromEntries(KINDS.map(([k]) => [k, []])),
  };
  view.innerHTML = `
    <form class="form" id="edit-form">
      <h1>${id ? "Edit recipe" : "New recipe"}</h1>
      <label for="f-title">Title</label><input type="text" id="f-title" required value="${esc(r.title)}">
      <div class="row2">
        <div><label for="f-source">Source link</label><input type="url" id="f-source" value="${esc(r.source_url || "")}"></div>
        <div><label for="f-author">Author / creator</label><input type="text" id="f-author" value="${esc(r.author || "")}"></div>
      </div>
      <label for="f-image">Photo URL</label><input type="url" id="f-image" value="${esc(r.image_url || "")}">
      <div class="row">
        <div><label for="f-servings">Servings</label><input type="text" id="f-servings" value="${esc(r.servings || "")}"></div>
        <div><label for="f-prep">Prep (min)</label><input type="number" min="0" id="f-prep" value="${r.prep_time ?? ""}"></div>
        <div><label for="f-cook">Cook (min)</label><input type="number" min="0" id="f-cook" value="${r.cook_time ?? ""}"></div>
        <div><label for="f-total">Total (min)</label><input type="number" min="0" id="f-total" value="${r.total_time ?? ""}"></div>
      </div>
      <label for="f-desc">Description</label><textarea id="f-desc">${esc(r.description)}</textarea>
      <div class="row2">
        <div><label for="f-ing">Ingredients</label><textarea id="f-ing" style="min-height:260px">${esc(r.ingredients.join("\n"))}</textarea>
          <div class="hint">One per line. Start a line with ## for a section heading (## For the sauce).</div></div>
        <div><label for="f-dir">Directions</label><textarea id="f-dir" style="min-height:260px">${esc(r.directions.join("\n"))}</textarea>
          <div class="hint">One step per line.</div></div>
      </div>
      <label for="f-notes">Notes</label><textarea id="f-notes" style="min-height:70px">${esc(r.notes)}</textarea>
      <h2 style="margin-top:22px">Categories</h2>
      <p class="hint">Comma-separated. ${id ? "Use ✨ Auto-categorize on the recipe page to re-guess." : "Leave blank to categorize automatically."}</p>
      <div class="row2">
        ${KINDS.map(([k, label]) => `<div><label for="c-${k}">${label}</label><input type="text" id="c-${k}" data-cat="${k}" value="${esc(r.categories[k].filter(v => v !== "Needs Review").join(", "))}"></div>`).join("")}
      </div>
      <div class="actions" style="margin-top:20px">
        <button class="primary" type="submit">Save recipe</button>
        <a class="button" href="${id ? `#/recipe/${id}` : "#/"}">Cancel</a>
      </div>
    </form>`;

  $("#edit-form").addEventListener("submit", async e => {
    e.preventDefault();
    const num = sel => { const v = $(sel).value; return v === "" ? null : Number(v); };
    const lines = sel => $(sel).value.split("\n").map(s => s.trim()).filter(Boolean);
    const categories = Object.fromEntries($$("[data-cat]").map(inp => [inp.dataset.cat, inp.value.split(",").map(s => s.trim()).filter(Boolean)]));
    const body = {
      title: $("#f-title").value.trim(),
      source_url: $("#f-source").value.trim() || null,
      author: $("#f-author").value.trim() || null,
      image_url: $("#f-image").value.trim() || null,
      servings: $("#f-servings").value.trim() || null,
      prep_time: num("#f-prep"), cook_time: num("#f-cook"),
      total_time: num("#f-total") ?? ((num("#f-prep") || 0) + (num("#f-cook") || 0) || null),
      description: $("#f-desc").value.trim(),
      ingredients: lines("#f-ing"),
      directions: lines("#f-dir"),
      notes: $("#f-notes").value.trim(),
      categories,
    };
    try {
      const saved = id
        ? await api(`/api/recipes/${id}`, { method: "PATCH", body })
        : await api("/api/recipes", { method: "POST", body: { ...body, auto_categorize: true } });
      toast("Saved");
      location.hash = `#/recipe/${saved.id}`;
    } catch (err) {
      toast(err.message);
    }
  });
}

// ------------------------------------------------------------------ import

function bookmarkletHref() {
  const origin = location.origin;
  const code = `(function(){var s=String(window.getSelection()||'');` +
    `window.open('${origin}/#/import?url='+encodeURIComponent(location.href)+'&text='+encodeURIComponent(s.slice(0,6000)),'_blank');})();`;
  return "javascript:" + encodeURIComponent(code);
}

async function renderImport(params) {
  view.innerHTML = `
    <div class="import-grid">
      <section class="panel">
        <h1>Import everything you've saved</h1>
        <p>Instagram and Facebook don't let apps read your saved posts directly, but both let <b>you</b> download them. It takes a few minutes for Meta to prepare the file.</p>
        <h3>📷 Instagram</h3>
        <ol class="steps">
          <li>Open <a href="https://accountscenter.instagram.com/info_and_permissions/dyi/" target="_blank" rel="noopener">Accounts Center → Download your information</a>.</li>
          <li>Choose <b>Download or transfer information</b> → your Instagram account → <b>Some of your information</b>.</li>
          <li>Tick only <b>Saved</b> (under “Your Instagram activity”). Choose <b>Download to device</b>, date range <b>All time</b>, format <b>JSON</b>.</li>
          <li>When the email arrives, download the .zip and drop it below. Your collections (e.g. “Dinner ideas”) come across too.</li>
        </ol>
        <h3>📘 Facebook</h3>
        <ol class="steps">
          <li>Open <a href="https://accountscenter.facebook.com/info_and_permissions/dyi/" target="_blank" rel="noopener">Accounts Center → Download your information</a>.</li>
          <li>Pick your Facebook account → <b>Some of your information</b> → tick <b>Saved items and collections</b>.</li>
          <li>Format <b>JSON</b>, date range <b>All time</b>. Download the .zip when it's ready and drop it below.</li>
        </ol>
        <div class="dropzone" id="dropzone">
          <p><b>Drop your export .zip here</b> (or its saved_posts / saved_collections / saved_items .json files)</p>
          <p class="hint">or a .txt / .csv list of links</p>
          <button type="button" class="primary" id="pick">Choose files</button>
          <input type="file" id="files" multiple hidden accept=".zip,.json,.html,.htm,.txt,.csv">
        </div>
        <p id="upload-result"></p>
      </section>
      <div>
        <section class="panel">
          <h2>Add one link</h2>
          <p class="hint">An Instagram post or reel, a Facebook post, or any recipe website.</p>
          <form id="url-form" class="actions" style="margin-top:0">
            <input type="url" id="one-url" placeholder="https://www.instagram.com/p/…" required value="${esc(params.get("url") || "")}">
            <button class="primary" type="submit">Import</button>
          </form>
          <p id="url-result"></p>
        </section>
        <section class="panel" style="margin-top:16px">
          <h2>Paste a caption or recipe</h2>
          <p class="hint">Works for anything — copy the caption from a post, a text from a friend, a recipe card you typed up.</p>
          <form id="text-form">
            <textarea id="paste-text" placeholder="Creamy Tuscan Chicken&#10;&#10;Ingredients:&#10;- 2 chicken breasts&#10;…&#10;&#10;Instructions:&#10;1. …">${esc(params.get("text") || "")}</textarea>
            <label for="paste-url">Link to the post (optional)</label>
            <input type="url" id="paste-url" value="${esc(params.get("url") || "")}">
            <div class="actions"><button class="primary" type="submit">Create recipe</button></div>
          </form>
        </section>
        <section class="panel" style="margin-top:16px">
          <h2>Save from your browser</h2>
          <p>Drag this button to your bookmarks bar. On any Instagram, Facebook, or recipe page, highlight the caption (optional) and click it.</p>
          <p><a class="bookmarklet" href="${bookmarkletHref()}" onclick="event.preventDefault();alert('Drag this button to your bookmarks bar.')">＋ Save to Recipe Vault</a></p>
        </section>
        <section class="panel" style="margin-top:16px">
          <h2>Backup</h2>
          <p><a class="button" href="/api/export">⬇ Download all recipes (JSON)</a></p>
          <p><label class="button" style="display:inline-flex;margin:0;color:inherit;font-size:inherit">⬆ Restore a backup<input type="file" id="restore" hidden accept=".json"></label></p>
        </section>
      </div>
    </div>`;

  const dz = $("#dropzone"), input = $("#files");
  const upload = async files => {
    if (!files.length) return;
    const form = new FormData();
    for (const f of files) form.append("files", f);
    $("#upload-result").textContent = "Reading your export…";
    try {
      const res = await api("/api/import/file", { method: "POST", body: form });
      const errors = res.files.filter(f => f.error).map(f => `${f.file}: ${f.error}`);
      $("#upload-result").innerHTML = `Found <b>${res.added}</b> new saved post${res.added === 1 ? "" : "s"}` +
        (res.duplicates ? ` (${res.duplicates} already imported)` : "") + ". " +
        (res.added ? `Recipes are being pulled in now — <a href="#/inbox">watch progress in the Inbox</a>.` : "") +
        (errors.length ? `<br><span class="err">${esc(errors.join("; "))}</span>` : "");
      refreshBadge();
    } catch (err) {
      $("#upload-result").textContent = err.message;
    }
  };
  $("#pick").addEventListener("click", () => input.click());
  input.addEventListener("change", () => upload(input.files));
  dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", e => { e.preventDefault(); dz.classList.remove("over"); upload(e.dataTransfer.files); });

  const importOne = async () => {
    const url = $("#one-url").value.trim();
    $("#url-result").textContent = "Fetching…";
    try {
      const res = await api("/api/import/url", { method: "POST", body: { url } });
      if (res.recipe_id) { toast(res.status === "exists" ? "Already in your recipes" : "Imported"); location.hash = `#/recipe/${res.recipe_id}`; }
      else $("#url-result").innerHTML = `${esc(res.error || "No recipe found.")} Paste the caption in the box below instead.`;
    } catch (err) {
      $("#url-result").textContent = err.message;
    }
  };
  $("#url-form").addEventListener("submit", e => { e.preventDefault(); importOne(); });
  $("#text-form").addEventListener("submit", async e => {
    e.preventDefault();
    try {
      const res = await api("/api/import/text", { method: "POST", body: { text: $("#paste-text").value, url: $("#paste-url").value.trim() || null } });
      toast(res.status === "imported" ? "Recipe created" : "Created — please check it over");
      location.hash = `#/recipe/${res.recipe.id}`;
    } catch (err) {
      toast(err.message);
    }
  });
  $("#restore").addEventListener("change", async e => {
    const form = new FormData();
    form.append("file", e.target.files[0]);
    try {
      const res = await api("/api/import/backup", { method: "POST", body: form });
      toast(`Restored ${res.added} recipes (${res.skipped} already present)`);
    } catch (err) { toast(err.message); }
  });

  // From the bookmarklet: selected text wins; otherwise import the link directly.
  if (params.get("text")) $("#paste-text").focus();
  else if (params.get("url")) importOne();
}

// ------------------------------------------------------------------ inbox

let inboxTimer;

async function renderInbox(params) {
  const status = params.get("status") || "";
  const [info, items] = await Promise.all([
    api("/api/inbox/status"),
    api("/api/inbox" + (status ? `?status=${status}` : "")),
  ]);
  const c = info.counts;
  const total = Object.values(c).reduce((a, b) => a + b, 0);
  const done = total - c.pending - c.processing;
  const tabs = [["", "All", total], ...Object.keys(STATUS_LABEL).filter(s => c[s]).map(s => [s, STATUS_LABEL[s], c[s]])];

  view.innerHTML = `
    <section>
      <h1>Import inbox</h1>
      <p class="hint">Every saved post from your exports lands here. Recipes are pulled in automatically; anything that couldn't be read waits for you.
        ${info.ai_enabled ? `Claude (<code>${esc(info.model)}</code>) is reading captions.` : "Tip: set <code>ANTHROPIC_API_KEY</code> before starting the app to let Claude read messy captions."}</p>
      ${total ? `<div class="progress"><div style="width:${total ? (100 * done / total).toFixed(1) : 0}%"></div></div>
      <div class="toolbar">
        <span>${done} of ${total} processed${info.running ? ` · working on <span class="url">${esc(info.current || "")}</span>` : ""}</span>
        <span class="spacer"></span>
        ${info.running ? `<button id="stop">Pause</button>` : (c.pending ? `<button class="primary" id="start">Resume</button>` : "")}
        ${c.failed ? `<button id="retry">Retry ${c.failed} failed</button>` : ""}
      </div>` : `<div class="empty"><h2>Nothing here yet</h2><p><a class="button primary" href="#/import">Import your saved posts</a></p></div>`}
      <div class="tabs">${tabs.map(([s, l, n]) => `<a class="chip ${s === status ? "on" : ""}" href="#/inbox${s ? `?status=${s}` : ""}">${l} ${n}</a>`).join("")}</div>
      <div class="items">${items.map(itemHtml).join("")}</div>
    </section>`;

  $("#start", view)?.addEventListener("click", async () => { await api("/api/inbox/process", { method: "POST" }); renderInbox(params); });
  $("#stop", view)?.addEventListener("click", async () => { await api("/api/inbox/stop", { method: "POST" }); setTimeout(() => renderInbox(params), 500); });
  $("#retry", view)?.addEventListener("click", async () => { await api("/api/inbox/retry", { method: "POST", body: { statuses: ["failed"] } }); renderInbox(params); });
  $$("[data-skip]", view).forEach(b => b.addEventListener("click", async () => { await api(`/api/inbox/${b.dataset.skip}/skip`, { method: "POST" }); renderInbox(params); }));
  $$("[data-paste]", view).forEach(b => b.addEventListener("click", () => {
    const box = $(`#paste-${b.dataset.paste}`);
    box.hidden = !box.hidden;
    if (!box.hidden) $("textarea", box).focus();
  }));
  $$("[data-save-text]", view).forEach(b => b.addEventListener("click", async () => {
    const text = $(`#paste-${b.dataset.saveText} textarea`).value;
    try {
      const res = await api(`/api/inbox/${b.dataset.saveText}/text`, { method: "POST", body: { text } });
      toast("Recipe created");
      location.hash = `#/recipe/${res.recipe.id}`;
    } catch (err) { toast(err.message); }
  }));

  clearTimeout(inboxTimer);
  if (info.running) {
    inboxTimer = setTimeout(() => { if (parseHash().path === "/inbox") renderInbox(parseHash().params); }, 2500);
  }
  refreshBadge(info);
}

function itemHtml(it) {
  const canPaste = ["failed", "not_recipe", "needs_review", "skipped"].includes(it.status);
  return `<div class="item">
    <div class="top">
      <span>${PLATFORM_ICON[it.platform] || "🔗"}</span>
      <b>${esc(it.title || it.author || "Saved post")}</b>
      ${it.collection ? `<span class="chip">${esc(it.collection)}</span>` : ""}
      <span class="status ${it.status}">${STATUS_LABEL[it.status] || it.status}</span>
      <a class="url" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.url)}</a>
      <span class="spacer" style="flex:1"></span>
      ${it.recipe_id ? `<a class="button small" href="#/recipe/${it.recipe_id}">Open recipe</a>` : ""}
      ${canPaste ? `<button class="small" data-paste="${it.id}">Paste caption</button>` : ""}
      ${["failed", "not_recipe", "needs_review", "pending"].includes(it.status) ? `<button class="small" data-skip="${it.id}">Skip</button>` : ""}
    </div>
    ${it.error ? `<div class="err">${esc(it.error)}</div>` : ""}
    ${it.caption && it.status !== "imported" ? `<div class="caption">${esc(it.caption)}</div>` : ""}
    <div id="paste-${it.id}" hidden>
      <textarea placeholder="Open the post, copy the caption, and paste it here">${esc(it.caption || "")}</textarea>
      <div class="actions"><button class="primary small" data-save-text="${it.id}">Create recipe</button></div>
    </div>
  </div>`;
}

async function refreshBadge(info) {
  try {
    info = info || await api("/api/inbox/status");
    const n = info.counts.failed + info.counts.needs_review + info.counts.pending + info.counts.processing;
    const badge = $("#inbox-badge");
    badge.textContent = n;
    badge.hidden = !n;
  } catch { /* the badge is decoration; never block the page on it */ }
}

// ------------------------------------------------------------------ router

async function route() {
  const { path, params } = parseHash();
  document.title = "Recipe Vault";
  const section = path.startsWith("/import") ? "import" : path.startsWith("/inbox") ? "inbox" : "recipes";
  $$("[data-nav]").forEach(a => a.classList.toggle("active", a.dataset.nav === section));
  clearTimeout(inboxTimer);
  if (path !== "/" && !path.startsWith("/recipe/")) searchInput.value = "";
  try {
    let m;
    if ((m = path.match(/^\/recipe\/(\d+)/))) await renderRecipe(m[1]);
    else if ((m = path.match(/^\/edit\/(\d+)/))) await renderEdit(m[1]);
    else if (path === "/new") await renderEdit(null);
    else if (path === "/import") await renderImport(params);
    else if (path === "/inbox") await renderInbox(params);
    else await renderBrowse(params);
  } catch (err) {
    view.innerHTML = `<div class="empty"><h2>Something went wrong</h2><p>${esc(err.message)}</p><p><a href="#/">Back to recipes</a></p></div>`;
  }
  if (section !== "recipes" || path !== "/") window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
route();
refreshBadge();
setInterval(refreshBadge, 15000);
