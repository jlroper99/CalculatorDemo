import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(
  readFileSync(path.join(here, "..", "public", "data", "bom.json"), "utf8"),
);

export const books = data.books;

/** Look up a chapter by book slug (e.g. "1-ne") and 1-based chapter number. */
export function getChapter(slug, chapter) {
  const book = books.find((b) => b.slug === slug);
  if (!book) return null;
  const verses = book.chapters[chapter - 1];
  if (!verses) return null;
  return { book, chapter, verses };
}

export function chapterText({ book, chapter, verses }) {
  return verses
    .map((v, i) => `${book.name} ${chapter}:${i + 1} ${v}`)
    .join("\n");
}
