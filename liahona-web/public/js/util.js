export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/**
 * Map an insight score (0-10) to a heat step 0-5 (0 = none).
 * Chapter averages run lower than single verses, so they get their own thresholds.
 */
export function heatStep(score, isAverage = false) {
  if (score == null || Number.isNaN(score)) return 0;
  const cuts = isAverage ? [0.5, 2, 3, 4, 5.25] : [1, 3, 5, 7, 9];
  let step = 0;
  for (const c of cuts) if (score >= c) step++;
  return step;
}

let toastTimer = null;
export function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

export async function api(url, { method = "GET", body } = {}) {
  const res = await fetch(url, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}
