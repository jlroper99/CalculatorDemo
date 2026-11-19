import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chunk, wordAt } from "../public/js/narrator.js";

const bom = JSON.parse(readFileSync(new URL("../public/data/bom.json", import.meta.url), "utf8"));
const chapter = (slug, n) => bom.books.find((b) => b.slug === slug).chapters[n - 1];

test("scripture data has all 15 books and 239 chapters", () => {
  assert.equal(bom.books.length, 15);
  assert.equal(bom.books.reduce((a, b) => a + b.chapters.length, 0), 239);
  assert.match(chapter("1-ne", 1)[0], /^I, Nephi, having been born of goodly parents/);
});

test("chunk covers the whole verse, in order, within the size limit", () => {
  const verse = chapter("alma", 32)[27];
  const parts = chunk(verse, 0, 200);
  assert.ok(parts.length > 1);
  for (const p of parts) {
    assert.ok(p.text.length <= 200);
    assert.equal(verse.slice(p.offset, p.offset + p.text.length), p.text);
  }
  const rebuilt = parts.map((p) => p.text).join(" ").replace(/\s+/g, " ");
  assert.equal(rebuilt, verse.replace(/\s+/g, " ").trim());
});

test("chunk can resume from a mid-verse offset", () => {
  const text = "And it came to pass that I, Nephi, said unto my father: I will go and do.";
  const parts = chunk(text, 25);
  assert.equal(parts[0].offset, 25);
  assert.ok(parts[0].text.startsWith("I, Nephi"));
});

test("wordAt finds word boundaries", () => {
  const t = "I, Nephi, having been";
  assert.deepEqual(wordAt(t, 4), [3, 9]);
  assert.deepEqual(wordAt(t, 0), [0, 2]);
});
