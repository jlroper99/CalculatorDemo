// The "Progress" view: which chapters you've listened to, and a listening-activity calendar.
import { chapterKey, today, streak } from "./store.js";
import { esc } from "./util.js";

export function renderProgress(view, { BOM, store }) {
  const s = store.get();
  const totalCh = BOM.books.reduce((a, b) => a + b.chapters.length, 0);
  const doneCh = Object.keys(s.completed).length;
  const totalMins = Math.round(Object.values(s.activity).reduce((a, b) => a + b, 0) / 60);

  view.innerHTML = `
    <section class="progress-page">
      <h1>Progress</h1>
      <p class="muted">Every chapter you've listened to the end, and how much you've listened each day. Select a chapter to open it.</p>

      <div class="stats">
        <div class="stat"><span class="stat-value">${doneCh}<small>/${totalCh}</small></span><span class="stat-label">chapters completed</span></div>
        <div class="stat"><span class="stat-value">${Math.round((doneCh / totalCh) * 100)}%</span><span class="stat-label">of the Book of Mormon</span></div>
        <div class="stat"><span class="stat-value">${streak()}</span><span class="stat-label">day streak</span></div>
        <div class="stat"><span class="stat-value">${totalMins}</span><span class="stat-label">minutes listened</span></div>
      </div>

      <div class="hm-grid card">
        ${BOM.books
          .map(
            (b) => `
          <div class="hm-row">
            <span class="hm-book">${esc(b.name)}</span>
            <div class="hm-cells">
              ${b.chapters
                .map((_, i) => {
                  const k = chapterKey(b.slug, i + 1);
                  const done = s.completed[k];
                  const current = s.last?.slug === b.slug && s.last?.chapter === i + 1;
                  const heat = done ? 4 : current ? 2 : 0;
                  const label = `${b.name} ${i + 1} · ${done ? `listened ${done}` : current ? "in progress" : "not yet"}`;
                  return `<a class="hm-cell" href="#/read/${b.slug}/${i + 1}" data-heat="${heat}" data-tip="${esc(label)}" aria-label="${esc(label)}"></a>`;
                })
                .join("")}
            </div>
          </div>`,
          )
          .join("")}
      </div>
      <div class="legend wide">
        <span class="sw-cell" data-heat="0"></span> Not yet
        <span class="sw-cell" data-heat="2"></span> In progress
        <span class="sw-cell" data-heat="4"></span> Completed
      </div>

      <h2 class="section-title">Listening activity</h2>
      ${calendar(s.activity)}
    </section>`;

  setupTooltip(view);
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
