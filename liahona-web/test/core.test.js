import { test } from "node:test";
import assert from "node:assert/strict";
import { chunk, wordAt } from "../public/js/narrator.js";
import { heatStep } from "../public/js/util.js";
import { normalize, offlineInsights } from "../lib/insights.js";
import { getChapter, books } from "../lib/scripture.js";

test("scripture data loads all 15 books and 239 chapters", () => {
  assert.equal(books.length, 15);
  assert.equal(books.reduce((a, b) => a + b.chapters.length, 0), 239);
  assert.match(getChapter("1-ne", 1).verses[0], /^I, Nephi, having been born of goodly parents/);
  assert.equal(getChapter("1-ne", 99), null);
});

test("chunk covers the whole verse, in order, within the size limit", () => {
  const verse = getChapter("alma", 32).verses[27];
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

test("heatStep buckets scores", () => {
  assert.equal(heatStep(0), 0);
  assert.equal(heatStep(10), 5);
  assert.equal(heatStep(5), 3);
  assert.equal(heatStep(null), 0);
  assert.equal(heatStep(3.5, true), 3);
});

test("normalize fills a score for every verse and clamps values", () => {
  const out = normalize({ verseScores: [{ verse: 2, score: 14, note: "x" }, { verse: 9, score: 5 }], keyVerses: [{ verse: 40, why: "" }] }, 3, "ai");
  assert.deepEqual(out.verseScores.map((v) => v.score), [0, 10, 0]);
  assert.equal(out.keyVerses.length, 0);
});

test("offline insights produce a full, valid shape", () => {
  const ch = getChapter("alma", 32);
  const ins = offlineInsights(ch);
  assert.equal(ins.source, "offline");
  assert.equal(ins.verseScores.length, ch.verses.length);
  assert.ok(ins.themes.some((t) => t.name === "Faith"));
  assert.ok(ins.keyVerses.length > 0);
});
