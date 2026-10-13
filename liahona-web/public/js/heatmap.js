// The "Insight heatmap" view: whole-book chapter grid, theme × book matrix and listening calendar.
import { chapterKey, today } from "./store.js";
import { esc, heatStep, toast } from "./util.js";

let mode = "insight"; // insight | theme | listening
let theme = null;

export function renderHeatmap(view, ctx) {
  const { BOM, index, store, status } = ctx;
  const s = store.get();
  const totalCh = BOM.books.reduce((a, b) => a + b.chapters.length, 0);
  const keys = Object.keys(index);
  const allScores = keys.flatMap((k) => index[k].scores);
  const avgAll = allScores.length ? allScores.reduce((a, b) => a + b, 0) / allScores.length : 0;

  // Normalised theme counts across every chapter with insights
  const themeCount = new Map();
  const themeLabel = new Map();
  for (const k of keys) {
    for (const t of new Set(index[k].themes.map(normTheme))) themeCount.set(t, (themeCount.get(t) || 0) + 1);
    for (const t of index[k].themes) if (!themeLabel.has(normTheme(t))) themeLabel.set(normTheme(t), t);
  }
  const topThemes = [...themeCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10).map(([t]) => t);
  if (!theme || !themeCount.has(theme)) theme = topThemes[0] ?? null;

  view.innerHTML = `
    <section class="heatmap-page">
      <h1>Insight heatmap</h1>
      <p class="muted">Where the Book of Mormon is richest in doctrine and teaching, chapter by chapter — built from the insights generated as you study. Select any cell to open that chapter.</p>

      <div class="stats">
        <div class="stat"><span class="stat-value">${keys.length}<small>/${totalCh}</small></span><span class="stat-label">chapters analysed</span></div>
        <div class="stat"><span class="stat-value">${avgAll.toFixed(1)}</span><span class="stat-label">avg verse insight (0–10)</span></div>
        <div class="stat"><span class="stat-value">${themeCount.size}</span><span class="stat-label">distinct themes</span></div>
        <div class="stat"><span class="stat-value">${Object.keys(s.completed).length}</span><span class="stat-label">chapters listened</span></div>
      </div>

      <div class="hm-controls">
        <div class="seg" role="tablist" aria-label="Color cells by">
          <button role="tab" data-mode="insight" aria-selected="${mode === "insight"}">Insight intensity</button>
          <button role="tab" data-mode="theme" aria-selected="${mode === "theme"}" ${topThemes.length ? "" : "disabled"}>Theme</button>
          <button role="tab" data-mode="listening" aria-selected="${mode === "listening"}">Listening</button>
        </div>
        ${
          mode === "theme" && topThemes.length
            ? `<select id="themePick" aria-label="Theme">${topThemes.map((t) => `<option value="${esc(t)}" ${t === theme ? "selected" : ""}>${esc(themeLabel.get(t))} (${themeCount.get(t)})</option>`).join("")}</select>`
            : ""
        }
      </div>

      <div class="hm-grid card" id="hmGrid">
        ${BOM.books
          .map(
            (b) => `
          <div class="hm-row">
            <span class="hm-book">${esc(b.name)}</span>
            <div class="hm-cells">
              ${b.chapters
                .map((_, i) => {
                  const k = chapterKey(b.slug, i + 1);
                  const info = index[k];
                  let heat = 0;
                  let label = `${b.name} ${i + 1}`;
                  if (mode === "insight") {
                    heat = info ? Math.max(1, heatStep(info.avg, true)) : 0;
                    label += info ? ` · avg insight ${info.avg.toFixed(1)}, peak ${info.max}${info.themes.length ? " · " + info.themes.join(", ") : ""}` : " · no insights yet";
                  } else if (mode === "theme") {
                    const has = info && info.themes.some((t) => normTheme(t) === theme);
                    heat = has ? Math.max(2, heatStep(info.avg, true)) : 0;
                    label += info ? (has ? ` · ${themeLabel.get(theme)}` : " · theme not present") : " · no insights yet";
                  } else {
                    const done = s.completed[k];
                    heat = done ? 4 : s.last?.slug === b.slug && s.last?.chapter === i + 1 ? 2 : 0;
                    label += done ? ` · listened ${done}` : " · not yet";
                  }
                  return `<a class="hm-cell ${info || mode === "listening" ? "" : "none"}" href="#/read/${b.slug}/${i + 1}" data-heat="${heat}" data-tip="${esc(label)}" aria-label="${esc(label)}"></a>`;
                })
                .join("")}
            </div>
          </div>`,
          )
          .join("")}
      </div>
      <div class="legend wide">
        ${
          mode === "listening"
            ? `<span class="sw-cell" data-heat="0"></span> Not yet <span class="sw-cell" data-heat="2"></span> In progress <span class="sw-cell" data-heat="4"></span> Completed`
            : `<span class="sw-cell none"></span> No insights yet &nbsp; <span>Narrative</span><span class="ramp"></span><span>Rich insight</span>`
        }
      </div>

      ${topThemes.length ? themeMatrix(BOM, index, topThemes, themeLabel) : ""}

      <h2 class="section-title">Listening activity</h2>
      ${calendar(s.activity)}

      <h2 class="section-title">Build the heatmap</h2>
      <div class="card gen-card">
        <p>${
          status.ai
            ? "Generate AI insights for every chapter of a book. Each chapter is one API request; results are cached on the server so they are only generated once."
            : "The server has no ANTHROPIC_API_KEY, so this fills the heatmap with basic offline (keyword-based) analysis. Add a key for AI insights."
        }</p>
        <div class="row">
          <select id="genBook" aria-label="Book to analyse">${BOM.books.map((b) => {
            const done = b.chapters.filter((_, i) => index[chapterKey(b.slug, i + 1)]).length;
            return `<option value="${b.slug}">${esc(b.name)} (${done}/${b.chapters.length})</option>`;
          }).join("")}</select>
          <button class="btn primary" id="genGo">Generate</button>
        </div>
        <div class="progress big" id="genProg" hidden><span></span></div>
      </div>
    </section>`;

  view.querySelectorAll(".seg button").forEach((b) => {
    b.onclick = () => {
      mode = b.dataset.mode;
      renderHeatmap(view, ctx);
    };
  });
  view.querySelector("#themePick")?.addEventListener("change", (e) => {
    theme = e.target.value;
    renderHeatmap(view, ctx);
  });
  view.querySelectorAll(".tm-row[data-theme]").forEach((r) => {
    r.onclick = () => {
      mode = "theme";
      theme = r.dataset.theme;
      renderHeatmap(view, ctx);
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
  });
  setupTooltip(view);

  view.querySelector("#genGo").onclick = async (e) => {
    const slug = view.querySelector("#genBook").value;
    const book = BOM.books.find((b) => b.slug === slug);
    if (status.ai && !confirm(`Generate AI insights for up to ${book.chapters.length} chapters of ${book.name}? This uses your Anthropic API credits.`)) return;
    const btn = e.currentTarget;
    const prog = view.querySelector("#genProg");
    btn.disabled = true;
    prog.hidden = false;
    try {
      await ctx.onGenerate(slug, (i, n) => {
        prog.firstElementChild.style.width = `${(i / n) * 100}%`;
        btn.textContent = `${i}/${n}…`;
      });
      toast(`${book.name}: insights ready`);
    } catch (err) {
      toast(err.message);
    }
    renderHeatmap(view, ctx);
  };
}

function normTheme(t) {
  return t.toLowerCase().replace(/^the\s+/, "").replace(/[^a-z0-9& ]/g, "").trim();
}

function themeMatrix(BOM, index, topThemes, themeLabel) {
  const books = BOM.books.filter((b) => b.chapters.some((_, i) => index[chapterKey(b.slug, i + 1)]));
  const cell = (b, t) => {
    const analysed = b.chapters.map((_, i) => index[chapterKey(b.slug, i + 1)]).filter(Boolean);
    const hits = analysed.filter((x) => x.themes.some((y) => normTheme(y) === t)).length;
    const share = analysed.length ? hits / analysed.length : 0;
    const heat = hits ? Math.min(5, 1 + Math.floor(share * 5)) : 0;
    const tip = `${themeLabel.get(t)} in ${b.name}: ${hits} of ${analysed.length} analysed chapters`;
    return `<td><span class="tm-cell" data-heat="${heat}" data-tip="${esc(tip)}" aria-label="${esc(tip)}"></span></td>`;
  };
  return `
    <h2 class="section-title">Themes across the books</h2>
    <p class="muted">Share of analysed chapters in each book where a theme appears. Select a theme to map it chapter by chapter.</p>
    <div class="card tm-wrap">
      <table class="tm">
        <thead><tr><th></th>${books.map((b) => `<th scope="col"><span>${esc(b.name)}</span></th>`).join("")}</tr></thead>
        <tbody>${topThemes
          .map((t) => `<tr class="tm-row" data-theme="${esc(t)}"><th scope="row">${esc(themeLabel.get(t))}</th>${books.map((b) => cell(b, t)).join("")}</tr>`)
          .join("")}</tbody>
      </table>
    </div>`;
}

function calendar(activity) {
  const weeks = 26;
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - (weeks * 7 - 1) - start.getDay());
  const cols = [];
  const d = new Date(start);
  while (d <= end) {
    const col = [];
    for (let i = 0; i < 7; i++) {
      const key = today(d);
      const mins = Math.round((activity[key] || 0) / 60);
      const heat = d > end ? -1 : mins === 0 ? 0 : mins < 5 ? 1 : mins < 15 ? 2 : mins < 30 ? 3 : mins < 60 ? 4 : 5;
      col.push(heat < 0 ? `<span class="cal-cell blank"></span>` : `<span class="cal-cell" data-heat="${heat}" data-tip="${key}: ${mins} min" aria-label="${key}: ${mins} minutes"></span>`);
      d.setDate(d.getDate() + 1);
    }
    cols.push(`<div class="cal-col">${col.join("")}</div>`);
  }
  return `<div class="card cal-wrap"><div class="cal">${cols.join("")}</div>
    <div class="legend"><span>Less</span><span class="ramp"></span><span>More</span></div></div>`;
}

function setupTooltip(root) {
  let tip = document.getElementById("hmTip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "hmTip";
    tip.className = "tooltip";
    tip.setAttribute("role", "tooltip");
    document.body.appendChild(tip);
  }
  const show = (e) => {
    const t = e.target.closest("[data-tip]");
    if (!t) return (tip.style.opacity = 0);
    tip.textContent = t.dataset.tip;
    const r = t.getBoundingClientRect();
    tip.style.opacity = 1;
    const x = Math.min(window.innerWidth - tip.offsetWidth - 8, Math.max(8, r.left + r.width / 2 - tip.offsetWidth / 2));
    tip.style.transform = `translate(${x}px, ${r.top - tip.offsetHeight - 8}px)`;
  };
  root.addEventListener("mouseover", show);
  root.addEventListener("focusin", show);
  root.addEventListener("mouseleave", () => (tip.style.opacity = 0));
  window.addEventListener("hashchange", () => (tip.style.opacity = 0), { once: true });
}
