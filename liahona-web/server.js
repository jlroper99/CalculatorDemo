import http from "node:http";
import { createReadStream, existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import zlib from "node:zlib";
import Anthropic from "@anthropic-ai/sdk";
import { getChapter } from "./lib/scripture.js";
import {
  MODEL,
  RefusalError,
  aiEnabled,
  askAboutChapter,
  generateInsights,
  offlineInsights,
} from "./lib/insights.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(here, "public");
const CACHE = process.env.LIAHONA_CACHE_DIR || path.join(here, "cache", "insights");
const PORT = Number(process.env.PORT) || 3000;
mkdirSync(CACHE, { recursive: true });

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".webmanifest": "application/manifest+json",
};

function sendJson(req, res, status, body) {
  const json = JSON.stringify(body);
  if (/\bgzip\b/.test(req.headers["accept-encoding"] || "") && json.length > 2048) {
    res.writeHead(status, { "content-type": MIME[".json"], "content-encoding": "gzip" });
    res.end(zlib.gzipSync(json));
  } else {
    res.writeHead(status, { "content-type": MIME[".json"] });
    res.end(json);
  }
}

function serveStatic(req, res, pathname) {
  const rel = pathname === "/" ? "index.html" : decodeURIComponent(pathname.slice(1));
  const file = path.normalize(path.join(PUBLIC, rel));
  if (!file.startsWith(PUBLIC + path.sep) || !existsSync(file) || !statSync(file).isFile()) {
    // SPA fallback
    return serveFile(req, res, path.join(PUBLIC, "index.html"));
  }
  serveFile(req, res, file);
}

function serveFile(req, res, file) {
  const type = MIME[path.extname(file)] || "application/octet-stream";
  const headers = { "content-type": type, "cache-control": "no-cache" };
  const compressible = /json|javascript|css|html|svg/.test(type);
  if (compressible && /\bgzip\b/.test(req.headers["accept-encoding"] || "")) {
    res.writeHead(200, { ...headers, "content-encoding": "gzip" });
    createReadStream(file).pipe(zlib.createGzip()).pipe(res);
  } else {
    res.writeHead(200, headers);
    createReadStream(file).pipe(res);
  }
}

async function readBody(req) {
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 64 * 1024) throw Object.assign(new Error("Body too large"), { status: 413 });
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw Object.assign(new Error("Invalid JSON"), { status: 400 });
  }
}

const cacheFile = (slug, chapter) => path.join(CACHE, `${slug}-${chapter}.json`);

function readCached(slug, chapter) {
  const f = cacheFile(slug, chapter);
  return existsSync(f) ? JSON.parse(readFileSync(f, "utf8")) : null;
}

const inFlight = new Map();
async function getOrCreateInsights(ch, { force = false, offline = false } = {}) {
  const slug = ch.book.slug;
  const cached = readCached(slug, ch.chapter);
  // An AI result is never replaced by an offline one; offline results are upgraded when AI is available.
  if (cached && !force && (cached.source === "ai" || offline || !aiEnabled())) return cached;
  const key = `${slug}-${ch.chapter}`;
  if (inFlight.has(key)) return inFlight.get(key);
  const job = (async () => {
    const result = !offline && aiEnabled() ? await generateInsights(ch) : offlineInsights(ch);
    writeFileSync(cacheFile(slug, ch.chapter), JSON.stringify(result));
    return result;
  })().finally(() => inFlight.delete(key));
  inFlight.set(key, job);
  return job;
}

function insightsIndex() {
  const index = {};
  for (const name of readdirSync(CACHE)) {
    if (!name.endsWith(".json")) continue;
    try {
      const ins = JSON.parse(readFileSync(path.join(CACHE, name), "utf8"));
      const scores = ins.verseScores.map((v) => v.score);
      index[name.slice(0, -5)] = {
        source: ins.source,
        avg: scores.reduce((a, b) => a + b, 0) / Math.max(1, scores.length),
        max: Math.max(0, ...scores),
        themes: ins.themes.map((t) => t.name),
        scores,
      };
    } catch {
      /* skip unreadable cache entries */
    }
  }
  return index;
}

function apiError(err) {
  if (err instanceof RefusalError) return [422, err.message];
  if (err instanceof Anthropic.AuthenticationError) return [502, "The server's Anthropic API key was rejected."];
  if (err instanceof Anthropic.RateLimitError) return [429, "AI rate limit reached — try again in a moment."];
  if (err instanceof Anthropic.APIError) return [502, `AI service error (${err.status ?? "network"}).`];
  if (err.status) return [err.status, err.message];
  return [500, "Unexpected server error."];
}

async function handleApi(req, res, url) {
  const parts = url.pathname.split("/").filter(Boolean); // ["api", ...]
  if (parts[1] === "status" && req.method === "GET") {
    return sendJson(req, res, 200, { ai: aiEnabled(), model: aiEnabled() ? MODEL : null });
  }
  if (parts[1] === "insights-index" && req.method === "GET") {
    return sendJson(req, res, 200, insightsIndex());
  }
  if ((parts[1] === "insights" || parts[1] === "ask") && parts.length === 4) {
    const ch = getChapter(parts[2], Number(parts[3]));
    if (!ch) return sendJson(req, res, 404, { error: "Unknown chapter" });

    if (parts[1] === "insights" && req.method === "GET") {
      const cached = readCached(ch.book.slug, ch.chapter);
      return cached ? sendJson(req, res, 200, cached) : sendJson(req, res, 404, { error: "Not generated yet" });
    }
    if (parts[1] === "insights" && req.method === "POST") {
      const body = await readBody(req);
      const result = await getOrCreateInsights(ch, { force: !!body.force, offline: !!body.offline });
      return sendJson(req, res, 200, result);
    }
    if (parts[1] === "ask" && req.method === "POST") {
      if (!aiEnabled()) {
        return sendJson(req, res, 503, { error: "Ask requires ANTHROPIC_API_KEY to be set on the server." });
      }
      const body = await readBody(req);
      const question = typeof body.question === "string" ? body.question.trim() : "";
      if (!question) return sendJson(req, res, 400, { error: "Question is required" });
      const answer = await askAboutChapter(ch, question, Array.isArray(body.history) ? body.history : []);
      return sendJson(req, res, 200, { answer });
    }
  }
  sendJson(req, res, 404, { error: "Not found" });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  try {
    if (url.pathname.startsWith("/api/")) return await handleApi(req, res, url);
    if (req.method !== "GET" && req.method !== "HEAD") return sendJson(req, res, 405, { error: "Method not allowed" });
    serveStatic(req, res, url.pathname);
  } catch (err) {
    const [status, message] = apiError(err);
    if (status >= 500) console.error(err);
    if (!res.headersSent) sendJson(req, res, status, { error: message });
    else res.end();
  }
});

server.listen(PORT, () => {
  console.log(`Liahona Web listening on http://localhost:${PORT}`);
  console.log(aiEnabled() ? `AI insights: ${MODEL}` : "AI insights: offline mode (set ANTHROPIC_API_KEY to enable)");
});
