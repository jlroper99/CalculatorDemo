// Local, per-device persistence: settings, progress, bookmarks, highlights, notes, activity.
const KEY = "liahona:v1";

const defaults = {
  settings: {
    voiceURI: null,
    rate: 1,
    announceChapter: true,
    autoAdvance: true,
    follow: true,
    fontSize: 20,
    theme: "auto", // auto | light | dark | sepia
    heatOverlay: true,
    autoInsights: true,
  },
  last: null, // { slug, chapter, verse }
  completed: {}, // "slug-ch": ISO date of last completion
  activity: {}, // "YYYY-MM-DD": seconds listened
  bookmarks: {}, // "slug-ch-v": { created }
  highlights: {}, // "slug-ch-v": color
  notes: {}, // "slug-ch-v": { text, updated }
  audioSync: {}, // "slug-ch": [[time, charPos], ...]
};

let state = load();
const listeners = new Set();

function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    return { ...defaults, ...raw, settings: { ...defaults.settings, ...(raw.settings || {}) } };
  } catch {
    return structuredClone(defaults);
  }
}

let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(state));
    } catch {
      /* storage full or unavailable: keep working in memory */
    }
  }, 150);
}

export const store = {
  get: () => state,
  settings: () => state.settings,
  setSetting(key, value) {
    state.settings[key] = value;
    save();
    listeners.forEach((fn) => fn("settings", key));
  },
  update(fn, topic = "data") {
    fn(state);
    save();
    listeners.forEach((l) => l(topic));
  },
  subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  exportJson: () => JSON.stringify(state, null, 2),
  importJson(text) {
    const raw = JSON.parse(text);
    state = { ...defaults, ...raw, settings: { ...defaults.settings, ...(raw.settings || {}) } };
    save();
    listeners.forEach((l) => l("all"));
  },
};

export const verseKey = (slug, ch, v) => `${slug}-${ch}-${v}`;
export const chapterKey = (slug, ch) => `${slug}-${ch}`;

export function today(d = new Date()) {
  const z = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

export function logListening(seconds) {
  if (seconds <= 0 || seconds > 60) return;
  const t = today();
  state.activity[t] = (state.activity[t] || 0) + seconds;
  save();
}

/** Consecutive days (ending today or yesterday) with at least one minute of listening. */
export function streak() {
  let n = 0;
  const d = new Date();
  if (!((state.activity[today(d)] || 0) >= 60)) d.setDate(d.getDate() - 1);
  while ((state.activity[today(d)] || 0) >= 60) {
    n++;
    d.setDate(d.getDate() - 1);
  }
  return n;
}
