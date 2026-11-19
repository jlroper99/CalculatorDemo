export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

let toastTimer = null;
export function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

/** Link to a chapter (and optional verse). Hashes are plain `#name` tokens so they also work when hosted as a claude.ai page. */
export const readHref = (slug, ch, v) => `#read-${slug}-${ch}${v ? `-${v}` : ""}`;
