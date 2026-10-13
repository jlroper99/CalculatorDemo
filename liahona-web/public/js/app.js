import { Narrator } from "./narrator.js";
import { store, verseKey, chapterKey, today, streak } from "./store.js";
import { renderHeatmap } from "./heatmap.js";
import { heatStep, esc, toast, api } from "./util.js";

const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const narrator = new Narrator();

let BOM = null; // { books: [{ name, slug, fullTitle, heading, chapters: [[verse]] }] }
let status = { ai: false };
let current = null; // { book, chapter, verses }
let currentInsights = null;
let insightsIndex = {};
let followPausedUntil = 0;
let sleepTimer = null;
let askHistory = [];

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  applyTheme();
  const [bom, st, idx] = await Promise.all([
    fetch("data/bom.json").then((r) => r.json()),
    api("/api/status").catch(() => ({ ai: false })),
    api("/api/insights-index").catch(() => ({})),
  ]);
  BOM = bom;
  status = st;
  insightsIndex = idx;
  setupPlayer();
  setupVoices();
  window.addEventListener("hashchange", route);
  route();
}

function bookBySlug(slug) {
  return BOM.books.find((b) => b.slug === slug);
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

function route() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [name, ...rest] = hash.split("/");
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === (name || "library")));
  document.body.dataset.view = name || "library";
  if (name === "read") {
    const [slug, ch, v] = rest;
    return showReader(slug, Number(ch) || 1, Number(v) || null);
  }
  if (narrator.playing && name !== "read") {
    // keep playing in the background; player bar stays visible
  }
  if (name === "heatmap") return showHeatmap();
  if (name === "saved") return showSaved();
  if (name === "search") return showSearch(decodeURIComponent(rest.join("/") || ""));
  showLibrary();
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

function showLibrary() {
  const s = store.get();
  const last = s.last && bookBySlug(s.last.slug);
  const totalCh = BOM.books.reduce((a, b) => a + b.chapters.length, 0);
  const doneCh = Object.keys(s.completed).length;
  const weekSecs = Object.entries(s.activity)
    .filter(([d]) => (Date.now() - new Date(d + "T00:00").getTime()) / 864e5 < 7)
    .reduce((a, [, v]) => a + v, 0);

  view.innerHTML = `
    <section class="library">
      <div class="hero">
        <div>
          <p class="eyebrow">The Book of Mormon</p>
          <h1>Listen and read, together.</h1>
          <p class="lede">Narration with word-by-word highlighting that scrolls with the voice, plus AI chapter insights and an insight heatmap of the whole book.</p>
        </div>
        ${
          last
            ? `<a class="continue card" href="#/read/${last.slug}/${s.last.chapter}/${s.last.verse || 1}">
                <span class="eyebrow">Continue listening</span>
                <strong>${esc(last.name)} ${s.last.chapter}</strong>
                <span class="muted">Verse ${s.last.verse || 1}</span>
                <span class="btn primary">▶ Resume</span>
              </a>`
            : `<a class="continue card" href="#/read/1-ne/1">
                <span class="eyebrow">Start here</span>
                <strong>1 Nephi 1</strong>
                <span class="muted">“I, Nephi, having been born of goodly parents…”</span>
                <span class="btn primary">▶ Begin</span>
              </a>`
        }
      </div>
      <div class="stats">
        <div class="stat"><span class="stat-value">${streak()}</span><span class="stat-label">day streak</span></div>
        <div class="stat"><span class="stat-value">${Math.round(weekSecs / 60)}</span><span class="stat-label">minutes this week</span></div>
        <div class="stat"><span class="stat-value">${doneCh}<small>/${totalCh}</small></span><span class="stat-label">chapters completed</span></div>
        <div class="stat"><span class="stat-value">${Object.keys(insightsIndex).length}</span><span class="stat-label">chapters with insights</span></div>
      </div>
      <h2 class="section-title">Books</h2>
      <div class="books">
        ${BOM.books
          .map((b) => {
            const done = b.chapters.filter((_, i) => s.completed[chapterKey(b.slug, i + 1)]).length;
            const pct = Math.round((done / b.chapters.length) * 100);
            return `
            <details class="book card">
              <summary>
                <span class="book-name">${esc(b.name)}</span>
                <span class="muted">${b.chapters.length} chapter${b.chapters.length > 1 ? "s" : ""}</span>
                <span class="progress" role="img" aria-label="${pct}% completed"><span style="width:${pct}%"></span></span>
              </summary>
              <p class="book-heading">${esc(b.heading || b.fullTitle)}</p>
              <div class="chapters">
                ${b.chapters
                  .map((_, i) => {
                    const k = chapterKey(b.slug, i + 1);
                    const heat = insightsIndex[k] ? heatStep(insightsIndex[k].avg, true) : 0;
                    return `<a class="ch ${s.completed[k] ? "done" : ""}" data-heat="${heat}" href="#/read/${b.slug}/${i + 1}" title="${esc(b.name)} ${i + 1}">${i + 1}</a>`;
                  })
                  .join("")}
              </div>
            </details>`;
          })
          .join("")}
      </div>
      <p class="fine">Text: the Book of Mormon (public domain), via the open <a href="https://github.com/bcbooks/scriptures-json" target="_blank" rel="noopener">scriptures-json</a> project. Progress and notes are stored only in this browser.</p>
    </section>`;
}

// ---------------------------------------------------------------------------
// Reader
// ---------------------------------------------------------------------------

async function showReader(slug, chapter, verse) {
  const book = bookBySlug(slug);
  if (!book || !book.chapters[chapter - 1]) {
    location.hash = "#/";
    return;
  }
  const same = current && current.book.slug === slug && current.chapter === chapter;
  const s = store.settings();

  if (!same) {
    current = { book, chapter, verses: book.chapters[chapter - 1] };
    currentInsights = null;
    askHistory = [];
    const startVerse = verse || (store.get().last?.slug === slug && store.get().last?.chapter === chapter ? store.get().last.verse : 1);
    narrator.announce = s.announceChapter;
    narrator.load({ title: `${book.name}, chapter ${chapter}.`, verses: current.verses }, { verse: startVerse || 1 });
    narrator.setAnchors(store.get().audioSync[chapterKey(slug, chapter)]);
  }

  if (!same || !$(".reader", view)) renderReader();
  if (verse) {
    narrator.seek(verse, 0);
    scrollToVerse(verse, "auto");
  } else if (!same) {
    narrator._emitPos(narrator.verse, 0);
    scrollToVerse(narrator.verse, "auto");
  }
  document.getElementById("player").hidden = false;
  updatePlayerTitle();
  if (!same) loadInsights();
}

function renderReader() {
  const { book, chapter, verses } = current;
  const s = store.get();
  const prev = neighbor(-1);
  const next = neighbor(1);
  document.title = `${book.name} ${chapter} · Liahona`;

  view.innerHTML = `
    <div class="reader ${store.settings().heatOverlay ? "heat-on" : ""}" style="--fs:${store.settings().fontSize}px">
      <section class="text-col" aria-label="Chapter text">
        <nav class="chapter-nav">
          ${prev ? `<a class="icon-btn" href="#/read/${prev.slug}/${prev.chapter}" aria-label="Previous chapter">‹</a>` : `<span></span>`}
          <div class="pickers">
            <select id="bookPick" aria-label="Book">${BOM.books.map((b) => `<option value="${b.slug}" ${b.slug === book.slug ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>
            <select id="chPick" aria-label="Chapter">${book.chapters.map((_, i) => `<option ${i + 1 === chapter ? "selected" : ""}>${i + 1}</option>`).join("")}</select>
          </div>
          ${next ? `<a class="icon-btn" href="#/read/${next.slug}/${next.chapter}" aria-label="Next chapter">›</a>` : `<span></span>`}
        </nav>
        <header class="chapter-head">
          <p class="eyebrow">${esc(book.fullTitle)}</p>
          <h1>${esc(book.name)} <span>${chapter}</span></h1>
        </header>
        <div class="verses" id="verses">
          ${verses
            .map((text, i) => {
              const v = i + 1;
              const k = verseKey(book.slug, chapter, v);
              const hl = s.highlights[k];
              let words = "";
              text.replace(/\S+/g, (w, off) => {
                words += `<span class="w" data-c="${off}">${esc(w)}</span> `;
              });
              return `<p class="verse ${hl ? "hl-" + hl : ""}" id="v${v}" data-v="${v}">
                <button class="vnum" data-v="${v}" aria-label="Verse ${v} options">${v}</button>${
                  s.bookmarks[k] ? '<span class="mark" title="Bookmarked">🔖</span>' : ""
                }${words}${s.notes[k] ? `<span class="note-chip" title="${esc(s.notes[k].text)}">✎</span>` : ""}</p>`;
            })
            .join("")}
        </div>
        <footer class="chapter-end">
          ${next ? `<a class="btn" href="#/read/${next.slug}/${next.chapter}">Next: ${esc(bookBySlug(next.slug).name)} ${next.chapter} ›</a>` : `<p class="muted">The end of the Book of Mormon.</p>`}
        </footer>
      </section>
      <div class="heatstrip" id="heatstrip" aria-label="Chapter insight heatmap; select a verse to jump"></div>
      <aside class="insights" id="insights" aria-label="Chapter insights"></aside>
      <button class="follow-btn" id="followBtn" hidden>↓ Follow narration</button>
    </div>`;

  $("#bookPick").onchange = (e) => (location.hash = `#/read/${e.target.value}/1`);
  $("#chPick").onchange = (e) => (location.hash = `#/read/${book.slug}/${e.target.value}`);

  const versesEl = $("#verses");
  versesEl.addEventListener("click", (e) => {
    const num = e.target.closest(".vnum");
    if (num) return openVerseMenu(Number(num.dataset.v), num);
    const verseEl = e.target.closest(".verse");
    if (!verseEl) return;
    const v = Number(verseEl.dataset.v);
    if (narrator.mode === "audio" && document.body.classList.contains("calibrating")) {
      const anchors = narrator.addAnchor(v);
      store.update((st) => (st.audioSync[chapterKey(current.book.slug, current.chapter)] = anchors));
      toast(`Synced verse ${v} to ${fmtTime(narrator.audio.currentTime)}`);
      return;
    }
    const w = e.target.closest(".w");
    if (window.getSelection()?.toString()) return;
    narrator.seek(v, w ? Number(w.dataset.c) : 0);
    if (!narrator.playing) narrator.play();
  });

  // Pause auto-follow while the reader scrolls on their own.
  const pauseFollow = () => {
    if (!narrator.playing) return;
    followPausedUntil = Date.now() + 8000;
    $("#followBtn").hidden = false;
  };
  window.onwheel = pauseFollow;
  window.ontouchmove = pauseFollow;
  $("#followBtn").onclick = () => {
    followPausedUntil = 0;
    $("#followBtn").hidden = true;
    scrollToVerse(narrator.verse);
  };

  renderHeatstrip();
  renderInsights();
}

function neighbor(delta) {
  const bi = BOM.books.indexOf(current.book);
  let ch = current.chapter + delta;
  if (ch >= 1 && ch <= current.book.chapters.length) return { slug: current.book.slug, chapter: ch };
  const nb = BOM.books[bi + delta];
  if (!nb) return null;
  return { slug: nb.slug, chapter: delta > 0 ? 1 : nb.chapters.length };
}

let lastWordEl = null;
let lastVerseEl = null;
function highlight({ verse, start }) {
  if (!current) return;
  const verseEl = document.getElementById("v" + verse);
  if (!verseEl) return;
  if (verseEl !== lastVerseEl) {
    lastVerseEl?.classList.remove("active");
    verseEl.classList.add("active");
    lastVerseEl = verseEl;
    store.update((s) => (s.last = { slug: current.book.slug, chapter: current.chapter, verse }), "position");
    updatePlayerProgress();
    document.querySelectorAll("#heatstrip .hs-cell.now").forEach((c) => c.classList.remove("now"));
    document.querySelector(`#heatstrip .hs-cell[data-v="${verse}"]`)?.classList.add("now");
  }
  const words = verseEl.querySelectorAll(".w");
  let wordEl = null;
  for (const w of words) {
    if (Number(w.dataset.c) <= start) wordEl = w;
    else break;
  }
  if (wordEl !== lastWordEl) {
    lastWordEl?.classList.remove("on");
    wordEl?.classList.add("on");
    lastWordEl = wordEl;
  }
  if (wordEl && store.settings().follow && Date.now() > followPausedUntil) keepInView(wordEl);
}

function keepInView(el) {
  const r = el.getBoundingClientRect();
  const vh = window.innerHeight;
  const top = vh * 0.28;
  const bottom = vh * 0.62;
  if (r.top < top - 4 || r.bottom > bottom) {
    window.scrollTo({ top: window.scrollY + r.top - vh * 0.35, behavior: "smooth" });
  }
}

function scrollToVerse(v, behavior = "smooth") {
  const el = document.getElementById("v" + v);
  if (!el) return;
  const r = el.getBoundingClientRect();
  window.scrollTo({ top: window.scrollY + r.top - window.innerHeight * 0.3, behavior });
}

// ----- verse menu ----------------------------------------------------------

function openVerseMenu(v, anchor) {
  closeVerseMenu();
  const k = verseKey(current.book.slug, current.chapter, v);
  const s = store.get();
  const menu = document.createElement("div");
  menu.className = "verse-menu card";
  menu.setAttribute("role", "menu");
  menu.innerHTML = `
    <strong>${esc(current.book.name)} ${current.chapter}:${v}</strong>
    <button data-act="play">▶ Play from here</button>
    <button data-act="bookmark">${s.bookmarks[k] ? "Remove bookmark" : "🔖 Bookmark"}</button>
    <div class="swatches" aria-label="Highlight color">
      ${["gold", "rose", "sky", "sage"].map((c) => `<button class="sw sw-${c} ${s.highlights[k] === c ? "sel" : ""}" data-act="hl" data-c="${c}" aria-label="Highlight ${c}"></button>`).join("")}
      <button class="sw sw-none" data-act="hl" data-c="" aria-label="Remove highlight">✕</button>
    </div>
    <button data-act="note">✎ ${s.notes[k] ? "Edit note" : "Add note"}</button>
    <button data-act="copy">⧉ Copy verse</button>
    ${status.ai ? `<button data-act="ask">✦ Ask about this verse</button>` : ""}`;
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.top = `${window.scrollY + r.bottom + 6}px`;
  menu.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - menu.offsetWidth - 8))}px`;
  menu.querySelector("button").focus?.();

  menu.onclick = async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const act = b.dataset.act;
    const text = current.verses[v - 1];
    if (act === "play") {
      narrator.seek(v, 0);
      narrator.play();
    } else if (act === "bookmark") {
      store.update((st) => (st.bookmarks[k] ? delete st.bookmarks[k] : (st.bookmarks[k] = { created: Date.now() })));
      rerenderVerse(v);
    } else if (act === "hl") {
      store.update((st) => (b.dataset.c ? (st.highlights[k] = b.dataset.c) : delete st.highlights[k]));
      rerenderVerse(v);
    } else if (act === "note") {
      const note = prompt(`Note for ${current.book.name} ${current.chapter}:${v}`, s.notes[k]?.text || "");
      if (note !== null) {
        store.update((st) => (note.trim() ? (st.notes[k] = { text: note.trim(), updated: Date.now() }) : delete st.notes[k]));
        rerenderVerse(v);
      }
    } else if (act === "copy") {
      await navigator.clipboard?.writeText(`${text} (${current.book.name} ${current.chapter}:${v})`);
      toast("Copied");
    } else if (act === "ask") {
      openInsightsPanel();
      const input = $("#askInput");
      if (input) {
        input.value = `What does verse ${v} mean?`;
        input.form.requestSubmit();
      }
    }
    closeVerseMenu();
  };
  setTimeout(() => document.addEventListener("click", outsideMenu, { once: true }), 0);
}
function outsideMenu(e) {
  if (!e.target.closest(".verse-menu")) closeVerseMenu();
  else document.addEventListener("click", outsideMenu, { once: true });
}
function closeVerseMenu() {
  document.querySelectorAll(".verse-menu").forEach((m) => m.remove());
}
function rerenderVerse(v) {
  const y = window.scrollY;
  renderReader();
  window.scrollTo(0, y);
  highlight({ verse: narrator.verse, start: narrator.char });
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------

async function loadInsights({ generate = false, force = false } = {}) {
  const { book, chapter } = current;
  const key = chapterKey(book.slug, chapter);
  currentInsights = { loading: true };
  renderInsights();
  try {
    let ins = null;
    if (!force) ins = await api(`/api/insights/${book.slug}/${chapter}`).catch(() => null);
    const wantUpgrade = ins && ins.source === "offline" && status.ai && store.settings().autoInsights;
    if (!ins || force || wantUpgrade) {
      if (!generate && !store.settings().autoInsights && !wantUpgrade) {
        currentInsights = null;
        return renderInsights();
      }
      currentInsights = { loading: true, generating: true };
      renderInsights();
      ins = await api(`/api/insights/${book.slug}/${chapter}`, { method: "POST", body: { force } });
    }
    if (chapterKey(current.book.slug, current.chapter) !== key) return;
    currentInsights = ins;
    const scores = ins.verseScores.map((v) => v.score);
    insightsIndex[key] = {
      source: ins.source,
      avg: scores.reduce((a, b) => a + b, 0) / scores.length,
      max: Math.max(...scores),
      themes: ins.themes.map((t) => t.name),
      scores,
    };
  } catch (err) {
    if (chapterKey(current.book.slug, current.chapter) !== key) return;
    currentInsights = { error: err.message };
  }
  renderInsights();
  renderHeatstrip();
  applyVerseHeat();
}

function applyVerseHeat() {
  if (!currentInsights?.verseScores) return;
  for (const s of currentInsights.verseScores) {
    const el = document.getElementById("v" + s.verse);
    if (!el) continue;
    el.dataset.heat = heatStep(s.score);
    if (s.note) el.title = `Insight ${s.score}/10 — ${s.note}`;
  }
}

function renderHeatstrip() {
  const el = $("#heatstrip");
  if (!el || !current) return;
  const scores = currentInsights?.verseScores;
  el.innerHTML = current.verses
    .map((_, i) => {
      const s = scores?.[i];
      return `<button class="hs-cell ${i + 1 === narrator.verse ? "now" : ""}" data-v="${i + 1}" data-heat="${s ? heatStep(s.score) : 0}"
        aria-label="Verse ${i + 1}${s ? `, insight ${s.score} of 10` : ""}" title="v${i + 1}${s ? ` · ${s.score}/10${s.note ? " · " + esc(s.note) : ""}` : ""}"></button>`;
    })
    .join("");
  el.onclick = (e) => {
    const c = e.target.closest(".hs-cell");
    if (!c) return;
    const v = Number(c.dataset.v);
    narrator.seek(v, 0);
    scrollToVerse(v);
  };
}

function renderInsights() {
  const el = $("#insights");
  if (!el) return;
  const ins = currentInsights;
  const head = `
    <div class="ins-head">
      <h2>✦ Chapter insights</h2>
      <button class="icon-btn close-ins" aria-label="Close insights">✕</button>
    </div>`;
  let body = "";
  if (!ins) {
    body = `<p class="muted">Get a summary, themes, key verses, cross-references and discussion questions for this chapter${status.ai ? "" : " (basic offline analysis — add an API key on the server for AI insights)"}.</p>
      <button class="btn primary" id="genIns">Generate insights</button>`;
  } else if (ins.loading) {
    body = `<div class="skeleton"></div><div class="skeleton short"></div><div class="skeleton"></div>
      <p class="muted">${ins.generating ? (status.ai ? "Studying this chapter…" : "Analyzing…") : "Loading…"}</p>`;
  } else if (ins.error) {
    body = `<p class="error">${esc(ins.error)}</p><button class="btn" id="genIns">Try again</button>`;
  } else {
    const verseLink = (v) => `<a href="#/read/${current.book.slug}/${current.chapter}/${v}" class="vlink">v. ${v}</a>`;
    body = `
      ${ins.source === "offline" ? `<p class="badge">Basic offline analysis${status.ai ? "" : " · set ANTHROPIC_API_KEY for AI insights"}</p>` : ""}
      <section><h3>Summary</h3><p>${esc(ins.summary)}</p></section>
      ${ins.historicalContext ? `<section><h3>Context</h3><p>${esc(ins.historicalContext)}</p></section>` : ""}
      ${ins.themes.length ? `<section><h3>Themes</h3><ul class="themes">${ins.themes.map((t) => `<li><strong>${esc(t.name)}</strong> ${esc(t.description)}</li>`).join("")}</ul></section>` : ""}
      ${ins.keyVerses.length ? `<section><h3>Key verses</h3><ul class="key-verses">${ins.keyVerses.map((k) => `<li>${verseLink(k.verse)} <q>${esc(trimWords(current.verses[k.verse - 1], 18))}</q><span>${esc(k.why)}</span></li>`).join("")}</ul></section>` : ""}
      <section>
        <h3>Insight heatmap</h3>
        <div class="mini-heat" role="img" aria-label="Insight score for each verse">
          ${ins.verseScores.map((s) => `<a href="#/read/${current.book.slug}/${current.chapter}/${s.verse}" data-heat="${heatStep(s.score)}" style="--h:${Math.max(8, s.score * 10)}%" title="v${s.verse} · ${s.score}/10${s.note ? " · " + esc(s.note) : ""}"></a>`).join("")}
        </div>
        <div class="legend"><span>Narrative</span><span class="ramp"></span><span>Rich insight</span></div>
        <label class="toggle"><input type="checkbox" id="heatToggle" ${store.settings().heatOverlay ? "checked" : ""}> Tint verses in the text</label>
      </section>
      ${ins.crossReferences.length ? `<section><h3>Cross-references</h3><ul class="xrefs">${ins.crossReferences.map((x) => `<li><strong>${esc(x.reference)}</strong> ${esc(x.connection)}</li>`).join("")}</ul></section>` : ""}
      ${ins.questions.length ? `<section><h3>Ponder</h3><ol class="questions">${ins.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ol></section>` : ""}
      ${ins.application ? `<section><h3>Apply it</h3><p>${esc(ins.application)}</p></section>` : ""}
      <p class="fine">${ins.source === "ai" ? "AI-generated study aid — verify against the text and Church sources." : ""}
        <button class="link" id="regenIns">Regenerate</button></p>`;
  }
  const ask = status.ai
    ? `<section class="ask">
        <h3>Ask about this chapter</h3>
        <div class="ask-log" id="askLog">${askHistory.map((m) => `<div class="msg ${m.role}">${m.role === "assistant" ? linkVerses(esc(m.content)) : esc(m.content)}</div>`).join("")}</div>
        <form id="askForm"><input id="askInput" placeholder="e.g. Why did Lehi have to leave Jerusalem?" autocomplete="off" maxlength="500"><button class="btn primary">Ask</button></form>
      </section>`
    : "";
  el.innerHTML = head + `<div class="ins-body">${body}${ask}</div>`;

  el.querySelector(".close-ins").onclick = () => document.body.classList.remove("show-insights");
  $("#genIns")?.addEventListener("click", () => loadInsights({ generate: true }));
  $("#regenIns")?.addEventListener("click", () => {
    if (status.ai && !confirm("Regenerate insights for this chapter with AI?")) return;
    loadInsights({ generate: true, force: true });
  });
  $("#heatToggle")?.addEventListener("change", (e) => {
    store.setSetting("heatOverlay", e.target.checked);
    $(".reader")?.classList.toggle("heat-on", e.target.checked);
  });
  $("#askForm")?.addEventListener("submit", onAsk);
  applyVerseHeat();
}

async function onAsk(e) {
  e.preventDefault();
  const input = $("#askInput");
  const q = input.value.trim();
  if (!q) return;
  const key = chapterKey(current.book.slug, current.chapter);
  const history = askHistory.slice();
  askHistory.push({ role: "user", content: q });
  input.value = "";
  const log = $("#askLog");
  log.insertAdjacentHTML("beforeend", `<div class="msg user">${esc(q)}</div><div class="msg assistant pending">Thinking…</div>`);
  log.scrollTop = log.scrollHeight;
  try {
    const { answer } = await api(`/api/ask/${current.book.slug}/${current.chapter}`, { method: "POST", body: { question: q, history } });
    if (chapterKey(current.book.slug, current.chapter) !== key) return;
    askHistory.push({ role: "assistant", content: answer });
  } catch (err) {
    askHistory.pop();
    toast(err.message);
  }
  renderInsights();
  const l = $("#askLog");
  if (l) l.scrollTop = l.scrollHeight;
}

function linkVerses(html) {
  return html.replace(/\b(v{1,2}\.|verses?)\s?(\d{1,3})/gi, (m, p, n) =>
    Number(n) <= current.verses.length ? `<a href="#/read/${current.book.slug}/${current.chapter}/${n}" class="vlink">${m}</a>` : m,
  );
}

function trimWords(t, n) {
  const w = t.split(/\s+/);
  return w.length > n ? w.slice(0, n).join(" ") + "…" : t;
}

function openInsightsPanel() {
  document.body.classList.add("show-insights");
}

// ---------------------------------------------------------------------------
// Heatmap, Saved, Search
// ---------------------------------------------------------------------------

async function showHeatmap() {
  document.title = "Insight heatmap · Liahona";
  insightsIndex = await api("/api/insights-index").catch(() => insightsIndex);
  renderHeatmap(view, { BOM, index: insightsIndex, store, status, onGenerate: generateBook });
}

async function generateBook(slug, onProgress) {
  const book = bookBySlug(slug);
  for (let i = 1; i <= book.chapters.length; i++) {
    const k = chapterKey(slug, i);
    if (insightsIndex[k]?.source === "ai" || (!status.ai && insightsIndex[k])) {
      onProgress(i, book.chapters.length);
      continue;
    }
    const ins = await api(`/api/insights/${slug}/${i}`, { method: "POST", body: {} });
    const scores = ins.verseScores.map((v) => v.score);
    insightsIndex[k] = { source: ins.source, avg: scores.reduce((a, b) => a + b, 0) / scores.length, max: Math.max(...scores), themes: ins.themes.map((t) => t.name), scores };
    onProgress(i, book.chapters.length);
  }
}

function showSaved() {
  document.title = "Saved · Liahona";
  const s = store.get();
  const keys = new Set([...Object.keys(s.bookmarks), ...Object.keys(s.highlights), ...Object.keys(s.notes)]);
  const items = [...keys]
    .map((k) => {
      const m = k.match(/^(.*)-(\d+)-(\d+)$/);
      const book = m && bookBySlug(m[1]);
      if (!book) return null;
      const ch = Number(m[2]);
      const v = Number(m[3]);
      return { k, book, ch, v, text: book.chapters[ch - 1]?.[v - 1] ?? "", order: BOM.books.indexOf(book) * 1e6 + ch * 1e3 + v };
    })
    .filter(Boolean)
    .sort((a, b) => a.order - b.order);

  view.innerHTML = `
    <section class="saved">
      <h1>Saved</h1>
      <p class="muted">Bookmarks, highlights and notes. Tap a verse number while reading to add one.</p>
      ${
        items.length
          ? `<ul class="saved-list">${items
              .map(
                (it) => `
            <li class="card ${s.highlights[it.k] ? "hl-" + s.highlights[it.k] : ""}">
              <a href="#/read/${it.book.slug}/${it.ch}/${it.v}"><strong>${esc(it.book.name)} ${it.ch}:${it.v}</strong> ${s.bookmarks[it.k] ? "🔖" : ""}</a>
              <p class="scripture">${esc(it.text)}</p>
              ${s.notes[it.k] ? `<p class="note">✎ ${esc(s.notes[it.k].text)}</p>` : ""}
            </li>`,
              )
              .join("")}</ul>`
          : `<div class="empty card">Nothing saved yet.</div>`
      }
      <div class="row">
        <button class="btn" id="exportBtn">Export my data</button>
        <label class="btn">Import<input type="file" id="importFile" accept="application/json" hidden></label>
      </div>
    </section>`;
  $("#exportBtn").onclick = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([store.exportJson()], { type: "application/json" }));
    a.download = `liahona-${today()}.json`;
    a.click();
  };
  $("#importFile").onchange = async (e) => {
    try {
      store.importJson(await e.target.files[0].text());
      toast("Imported");
      showSaved();
    } catch {
      toast("That file couldn't be imported.");
    }
  };
}

function showSearch(q) {
  document.title = "Search · Liahona";
  $("#searchInput").value = q;
  const results = [];
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length) {
    outer: for (const b of BOM.books)
      for (let c = 0; c < b.chapters.length; c++)
        for (let v = 0; v < b.chapters[c].length; v++) {
          const t = b.chapters[c][v].toLowerCase();
          if (terms.every((term) => t.includes(term))) {
            results.push({ b, c: c + 1, v: v + 1, text: b.chapters[c][v] });
            if (results.length >= 300) break outer;
          }
        }
  }
  const mark = (text) => {
    let h = esc(text);
    for (const t of terms) h = h.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"), "<mark>$1</mark>");
    return h;
  };
  view.innerHTML = `
    <section class="search">
      <h1>Search</h1>
      <p class="muted">${terms.length ? `${results.length}${results.length >= 300 ? "+" : ""} verse${results.length === 1 ? "" : "s"} for “${esc(q)}”` : "Type a word or phrase in the search box."}</p>
      <ul class="results">${results
        .map((r) => `<li><a href="#/read/${r.b.slug}/${r.c}/${r.v}"><strong>${esc(r.b.name)} ${r.c}:${r.v}</strong></a><p class="scripture">${mark(r.text)}</p></li>`)
        .join("")}</ul>
    </section>`;
}

// ---------------------------------------------------------------------------
// Player
// ---------------------------------------------------------------------------

function setupPlayer() {
  const p = $("#player");
  const s = store.settings();
  narrator.rate = s.rate;
  narrator.announce = s.announceChapter;

  narrator.addEventListener("position", (e) => highlight(e.detail));
  narrator.addEventListener("state", (e) => {
    p.classList.toggle("playing", e.detail.playing);
    $("#playBtn").setAttribute("aria-label", e.detail.playing ? "Pause" : "Play");
    if (!e.detail.playing) $("#followBtn")?.setAttribute("hidden", "");
    updateMediaSession();
  });
  narrator.addEventListener("error", (e) => toast(e.detail.message));
  narrator.addEventListener("ended", onChapterEnd);
  narrator.addEventListener("audioready", () => {
    $("#audioName").textContent = narrator.audioName;
  });

  $("#playBtn").onclick = () => narrator.toggle();
  $("#prevVerse").onclick = () => narrator.step(-1);
  $("#nextVerse").onclick = () => narrator.step(1);
  $("#rateBtn").textContent = fmtRate(s.rate);
  $("#rateBtn").onclick = () => {
    const rates = [0.75, 0.9, 1, 1.15, 1.25, 1.5, 1.75, 2];
    const next = rates[(rates.indexOf(store.settings().rate) + 1) % rates.length] ?? 1;
    store.setSetting("rate", next);
    narrator.setRate(next);
    $("#rateBtn").textContent = fmtRate(next);
  };
  $("#insBtn").onclick = () => document.body.classList.toggle("show-insights");
  $("#sleepBtn").onclick = cycleSleep;
  $("#settingsBtn").onclick = openSettings;
  $("#progress").onclick = (e) => {
    if (!current) return;
    const r = e.currentTarget.getBoundingClientRect();
    const v = Math.max(1, Math.ceil(((e.clientX - r.left) / r.width) * current.verses.length));
    narrator.seek(v, 0);
    scrollToVerse(v);
  };

  // Source: synthesized voice vs. the user's own recording
  document.querySelectorAll('input[name="source"]').forEach((r) => {
    r.onchange = () => {
      narrator.setMode(r.value);
      document.body.classList.toggle("audio-mode", r.value === "audio");
      document.body.classList.remove("calibrating");
    };
  });
  $("#audioFile").onchange = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    narrator.setAudioFile(f);
    toast(`Loaded ${f.name}. Tap “Sync” then tap each verse as it begins for tighter alignment.`);
  };
  $("#calibrateBtn").onclick = () => {
    const on = document.body.classList.toggle("calibrating");
    $("#calibrateBtn").setAttribute("aria-pressed", on);
    toast(on ? "Sync mode: while the audio plays, tap a verse the moment it begins." : "Sync mode off");
  };
  $("#clearSyncBtn").onclick = () => {
    if (!current) return;
    narrator.setAnchors([]);
    store.update((st) => delete st.audioSync[chapterKey(current.book.slug, current.chapter)]);
    toast("Sync points cleared");
  };

  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select") || e.metaKey || e.ctrlKey) return;
    if (document.body.dataset.view !== "read") return;
    if (e.code === "Space") {
      e.preventDefault();
      narrator.toggle();
    } else if (e.key === "ArrowDown" || e.key === "j") narrator.step(1);
    else if (e.key === "ArrowUp" || e.key === "k") narrator.step(-1);
    else if (e.key === "i") document.body.classList.toggle("show-insights");
  });

  $("#searchForm").onsubmit = (e) => {
    e.preventDefault();
    location.hash = `#/search/${encodeURIComponent($("#searchInput").value.trim())}`;
  };
  $("#themeBtn").onclick = () => {
    const order = ["auto", "light", "sepia", "dark"];
    store.setSetting("theme", order[(order.indexOf(store.settings().theme) + 1) % order.length]);
    applyTheme();
    toast(`Theme: ${store.settings().theme}`);
  };
}

function onChapterEnd() {
  if (!current) return;
  store.update((s) => (s.completed[chapterKey(current.book.slug, current.chapter)] = today()));
  const next = neighbor(1);
  if (narrator.mode === "tts" && store.settings().autoAdvance && next && !sleepTimer?.endOfChapter) {
    location.hash = `#/read/${next.slug}/${next.chapter}/1`;
    setTimeout(() => {
      window.scrollTo({ top: 0 });
      narrator.play(1, 0);
    }, 400);
  } else if (sleepTimer?.endOfChapter) {
    clearSleep();
    toast("Sleep timer: stopped at end of chapter");
  }
}

function updatePlayerTitle() {
  if (!current) return;
  $("#playerTitle").textContent = `${current.book.name} ${current.chapter}`;
  updatePlayerProgress();
  updateMediaSession();
}

function updatePlayerProgress() {
  if (!current) return;
  $("#playerSub").textContent = `Verse ${narrator.verse} of ${current.verses.length}`;
  $("#progress span").style.width = `${((narrator.verse - 1) / Math.max(1, current.verses.length - 1)) * 100}%`;
}

function updateMediaSession() {
  if (!("mediaSession" in navigator) || !current) return;
  navigator.mediaSession.metadata = new MediaMetadata({ title: `${current.book.name} ${current.chapter}`, artist: "The Book of Mormon", album: "Liahona" });
  navigator.mediaSession.playbackState = narrator.playing ? "playing" : "paused";
  navigator.mediaSession.setActionHandler("play", () => narrator.play());
  navigator.mediaSession.setActionHandler("pause", () => narrator.pause());
  navigator.mediaSession.setActionHandler("nexttrack", () => narrator.step(1));
  navigator.mediaSession.setActionHandler("previoustrack", () => narrator.step(-1));
}

function cycleSleep() {
  const opts = [null, 5, 15, 30, 60, "chapter"];
  const cur = sleepTimer ? sleepTimer.option : null;
  const next = opts[(opts.indexOf(cur) + 1) % opts.length];
  clearSleep();
  if (next === null) return toast("Sleep timer off");
  if (next === "chapter") {
    sleepTimer = { option: next, endOfChapter: true };
    $("#sleepBtn").dataset.on = "end";
    return toast("Stop at end of chapter");
  }
  sleepTimer = { option: next, id: setTimeout(() => (narrator.pause(), clearSleep(), toast("Sleep timer: paused")), next * 60000) };
  $("#sleepBtn").dataset.on = `${next}m`;
  toast(`Sleep in ${next} minutes`);
}
function clearSleep() {
  if (sleepTimer?.id) clearTimeout(sleepTimer.id);
  sleepTimer = null;
  delete $("#sleepBtn").dataset.on;
}

// ---------------------------------------------------------------------------
// Settings & voices
// ---------------------------------------------------------------------------

let voices = [];
function setupVoices() {
  if (!narrator.ttsSupported) return;
  const pick = () => {
    voices = speechSynthesis.getVoices();
    const saved = store.settings().voiceURI;
    narrator.voice =
      voices.find((v) => v.voiceURI === saved) ||
      voices.find((v) => /^en(-|_)US/i.test(v.lang) && /natural|neural|premium|enhanced|samantha|google/i.test(v.name)) ||
      voices.find((v) => /^en/i.test(v.lang)) ||
      null;
  };
  pick();
  speechSynthesis.addEventListener?.("voiceschanged", pick);
}

function openSettings() {
  const d = $("#settings");
  const s = store.settings();
  const en = voices.filter((v) => /^en/i.test(v.lang));
  const list = en.length ? en : voices;
  d.querySelector(".settings-body").innerHTML = `
    <label>Narrator voice
      <select id="setVoice">${list.map((v) => `<option value="${esc(v.voiceURI)}" ${narrator.voice?.voiceURI === v.voiceURI ? "selected" : ""}>${esc(v.name)} (${esc(v.lang)})</option>`).join("") || "<option>System default</option>"}</select>
    </label>
    <button class="btn" type="button" id="previewVoice">Preview voice</button>
    <label>Text size <input type="range" id="setFont" min="16" max="30" value="${s.fontSize}"></label>
    <label class="toggle"><input type="checkbox" id="setFollow" ${s.follow ? "checked" : ""}> Auto-scroll to follow narration</label>
    <label class="toggle"><input type="checkbox" id="setAnnounce" ${s.announceChapter ? "checked" : ""}> Announce chapter before verse 1</label>
    <label class="toggle"><input type="checkbox" id="setAdvance" ${s.autoAdvance ? "checked" : ""}> Continue to next chapter automatically</label>
    <label class="toggle"><input type="checkbox" id="setAutoIns" ${s.autoInsights ? "checked" : ""}> Load insights automatically when opening a chapter</label>
    <p class="fine">AI: ${status.ai ? `on (${esc(status.model)})` : "off — the server has no ANTHROPIC_API_KEY, so insights use basic offline analysis."}<br>
    Shortcuts: Space play/pause · ↑/↓ previous/next verse · i insights.</p>`;
  $("#setVoice").onchange = (e) => {
    const v = voices.find((x) => x.voiceURI === e.target.value);
    store.setSetting("voiceURI", v?.voiceURI ?? null);
    narrator.setVoice(v || null);
  };
  $("#previewVoice").onclick = () => {
    if (!narrator.ttsSupported) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance("I, Nephi, having been born of goodly parents.");
    u.voice = narrator.voice;
    u.rate = narrator.rate;
    speechSynthesis.speak(u);
  };
  $("#setFont").oninput = (e) => {
    store.setSetting("fontSize", Number(e.target.value));
    $(".reader")?.style.setProperty("--fs", e.target.value + "px");
  };
  $("#setFollow").onchange = (e) => store.setSetting("follow", e.target.checked);
  $("#setAnnounce").onchange = (e) => {
    store.setSetting("announceChapter", e.target.checked);
    narrator.announce = e.target.checked;
  };
  $("#setAdvance").onchange = (e) => store.setSetting("autoAdvance", e.target.checked);
  $("#setAutoIns").onchange = (e) => store.setSetting("autoInsights", e.target.checked);
  d.showModal();
}

function applyTheme() {
  const t = store.settings().theme;
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = t;
}

const fmtRate = (r) => `${r}×`;
const fmtTime = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

boot().catch((err) => {
  console.error(err);
  view.innerHTML = `<p class="error">Couldn't start the app: ${esc(err.message)}</p>`;
});
