import Anthropic from "@anthropic-ai/sdk";
import { chapterText } from "./scripture.js";

export const MODEL = process.env.LIAHONA_MODEL || "claude-opus-5-5";

let client = null;
export function aiEnabled() {
  return Boolean(process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN);
}
function getClient() {
  if (!client) client = new Anthropic();
  return client;
}

const SYSTEM = `You are a thoughtful, faithful study companion for readers of the Book of Mormon.
You help readers understand each chapter: its narrative, doctrine, historical setting within the text, and how it can apply to their lives.
Be accurate to the text you are given; cite verses by number. Do not invent events or quotations.
Write warmly and clearly for a general audience. Prefer insight over paraphrase.`;

// JSON schema for structured chapter insights. verseScores drives the verse-level heatmap.
const INSIGHT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "summary",
    "historicalContext",
    "themes",
    "keyVerses",
    "verseScores",
    "crossReferences",
    "questions",
    "application",
  ],
  properties: {
    summary: { type: "string", description: "3-5 sentence summary of the chapter." },
    historicalContext: {
      type: "string",
      description: "Where this chapter sits in the Book of Mormon narrative: who is speaking, to whom, and when.",
    },
    themes: {
      type: "array",
      description: "2-5 major themes, each a short title-case label (1-3 words) plus one sentence.",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["name", "description"],
        properties: { name: { type: "string" }, description: { type: "string" } },
      },
    },
    keyVerses: {
      type: "array",
      description: "The 2-5 most significant verses and why they matter.",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["verse", "why"],
        properties: { verse: { type: "integer" }, why: { type: "string" } },
      },
    },
    verseScores: {
      type: "array",
      description:
        "One entry for EVERY verse in the chapter, in order. score is an integer 0-10 for doctrinal / spiritual insight density (0 = transitional narrative, 10 = profound, much-quoted teaching). note is a short phrase (max 12 words) naming what makes the verse notable, or empty string.",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["verse", "score", "note"],
        properties: {
          verse: { type: "integer" },
          score: { type: "integer" },
          note: { type: "string" },
        },
      },
    },
    crossReferences: {
      type: "array",
      description: "2-5 related passages elsewhere in scripture (Bible, Book of Mormon, D&C, Pearl of Great Price).",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["reference", "connection"],
        properties: { reference: { type: "string" }, connection: { type: "string" } },
      },
    },
    questions: {
      type: "array",
      description: "3 open-ended reflection or discussion questions.",
      items: { type: "string" },
    },
    application: {
      type: "string",
      description: "2-3 sentences on how a reader might apply this chapter today.",
    },
  },
};

export class RefusalError extends Error {}

function textOf(message) {
  return message.content
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("");
}

/** Generate structured insights for a chapter with Claude. */
export async function generateInsights(ch) {
  const message = await getClient().beta.messages.create({
    model: MODEL,
    max_tokens: 16000,
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
    output_config: {
      effort: "medium",
      format: { type: "json_schema", schema: INSIGHT_SCHEMA },
    },
    system: SYSTEM,
    messages: [
      {
        role: "user",
        content: `Here is ${ch.book.name} chapter ${ch.chapter} (${ch.verses.length} verses):\n\n${chapterText(ch)}\n\nProduce study insights for this chapter. verseScores must contain exactly ${ch.verses.length} entries, verse 1 through ${ch.verses.length}.`,
      },
    ],
  });
  if (message.stop_reason === "refusal") throw new RefusalError("The model declined this request.");
  const parsed = JSON.parse(textOf(message));
  return normalize(parsed, ch.verses.length, "ai");
}

/** Answer a free-form question about a chapter. The chapter text is cached across questions. */
export async function askAboutChapter(ch, question, history = []) {
  const messages = [];
  for (const turn of history.slice(-6)) {
    if (turn && (turn.role === "user" || turn.role === "assistant") && typeof turn.content === "string") {
      messages.push({ role: turn.role, content: turn.content.slice(0, 4000) });
    }
  }
  messages.push({ role: "user", content: question.slice(0, 2000) });
  if (messages[0].role !== "user") messages.shift();

  const message = await getClient().beta.messages.create({
    model: MODEL,
    max_tokens: 16000,
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
    output_config: { effort: "low" },
    system: [
      { type: "text", text: SYSTEM },
      {
        type: "text",
        text: `The reader is studying ${ch.book.name} chapter ${ch.chapter}:\n\n${chapterText(ch)}\n\nAnswer their questions about it concisely (under 200 words unless asked for more). Cite verses like (v. 12).`,
        cache_control: { type: "ephemeral" },
      },
    ],
    messages,
  });
  if (message.stop_reason === "refusal") throw new RefusalError("The model declined this question.");
  return textOf(message);
}

/** Clamp and fill model output so the client can rely on its shape. */
export function normalize(raw, verseCount, source) {
  const byVerse = new Map();
  for (const s of raw.verseScores ?? []) {
    if (Number.isInteger(s.verse) && s.verse >= 1 && s.verse <= verseCount) byVerse.set(s.verse, s);
  }
  const verseScores = [];
  for (let v = 1; v <= verseCount; v++) {
    const s = byVerse.get(v);
    verseScores.push({
      verse: v,
      score: Math.max(0, Math.min(10, Math.round(Number(s?.score) || 0))),
      note: s?.note ?? "",
    });
  }
  return {
    source,
    generatedAt: new Date().toISOString(),
    summary: raw.summary ?? "",
    historicalContext: raw.historicalContext ?? "",
    themes: (raw.themes ?? []).slice(0, 5),
    keyVerses: (raw.keyVerses ?? []).filter((k) => k.verse >= 1 && k.verse <= verseCount).slice(0, 5),
    verseScores,
    crossReferences: (raw.crossReferences ?? []).slice(0, 5),
    questions: (raw.questions ?? []).slice(0, 5),
    application: raw.application ?? "",
  };
}

// ---------------------------------------------------------------------------
// Offline fallback: keyword-based heuristics so the app (and heatmap) work
// without an API key. Clearly labelled as "basic" in the UI.
// ---------------------------------------------------------------------------

const THEME_LEXICON = {
  "Jesus Christ": ["christ", "jesus", "messiah", "redeemer", "lamb of god", "son of god", "savior", "holy one of israel"],
  Atonement: ["atonement", "redeem", "redemption", "ransom", "blood", "cross", "resurrection", "mercy"],
  Faith: ["faith", "believe", "belief", "hope", "trust"],
  Repentance: ["repent", "repentance", "forgive", "forgiveness", "sin", "iniquity", "baptiz"],
  Covenants: ["covenant", "promise", "commandment", "keep the commandments", "law of moses"],
  Prayer: ["pray", "prayer", "cried unto the lord", "supplication"],
  Revelation: ["vision", "dream", "revelation", "prophesy", "prophecy", "angel", "spirit of the lord", "holy ghost"],
  Scripture: ["record", "plates", "engraven", "scripture", "words of isaiah"],
  Charity: ["charity", "love", "poor", "needy", "impart of your substance"],
  "War & Conflict": ["war", "battle", "armies", "sword", "slain", "contention", "fortification"],
  Pride: ["pride", "riches", "costly apparel", "lifted up", "boast"],
  Deliverance: ["deliver", "bondage", "captivity", "preserved", "strength of the lord"],
};

const EMPHASIS = [
  "behold", "i say unto you", "verily", "remember", "o that", "i know", "i would that ye",
  "eternal life", "kingdom of god", "plan of", "great and marvelous", "my beloved",
];

export function offlineInsights(ch) {
  const n = ch.verses.length;
  const lower = ch.verses.map((v) => v.toLowerCase());
  const themeCounts = Object.fromEntries(Object.keys(THEME_LEXICON).map((t) => [t, 0]));
  const raw = lower.map((text) => {
    let s = 0;
    const hits = [];
    for (const [theme, words] of Object.entries(THEME_LEXICON)) {
      const c = words.reduce((acc, w) => acc + (text.includes(w) ? 1 : 0), 0);
      if (c) {
        themeCounts[theme] += c;
        hits.push(theme);
        s += theme === "War & Conflict" ? 0.4 * c : 1.4 * c;
      }
    }
    s += EMPHASIS.reduce((acc, w) => acc + (text.includes(w) ? 0.8 : 0), 0);
    return { s, hits };
  });
  const max = Math.max(1, ...raw.map((r) => r.s));
  const verseScores = raw.map((r, i) => ({
    verse: i + 1,
    score: Math.round((r.s / max) * 8 + (r.s > 0 ? 1 : 0)),
    note: r.hits.slice(0, 2).join(", "),
  }));
  const themes = Object.entries(themeCounts)
    .filter(([, c]) => c > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([name, c]) => ({ name, description: `Mentioned in about ${c} place${c === 1 ? "" : "s"} in this chapter.` }));
  const keyVerses = [...verseScores]
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .sort((a, b) => a.verse - b.verse)
    .map((v) => ({ verse: v.verse, why: v.note ? `Touches on ${v.note.toLowerCase()}.` : "A notable verse." }));
  const first = ch.verses[0].split(/(?<=[.;:])\s/)[0];
  return normalize(
    {
      summary: `${ch.book.name} ${ch.chapter} has ${n} verses. It opens: “${first}”`,
      historicalContext: ch.book.heading
        ? `From the book's heading: ${ch.book.heading.slice(0, 400)}${ch.book.heading.length > 400 ? "…" : ""}`
        : "",
      themes,
      keyVerses,
      verseScores,
      crossReferences: [],
      questions: [
        `What do you notice about how ${themes[0]?.name.toLowerCase() ?? "the Lord"} is described in this chapter?`,
        `Which verse stood out most to you as you listened, and why?`,
        `How could you apply one principle from this chapter this week?`,
      ],
      application: "Add an Anthropic API key on the server for full AI-generated insights.",
    },
    n,
    "offline",
  );
}
