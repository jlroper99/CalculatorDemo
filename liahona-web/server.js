// Minimal static file server for the app (no dependencies).
import http from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import zlib from "node:zlib";

const here = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(here, "public");
const PORT = Number(process.env.PORT) || 3000;

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

function serveFile(req, res, file) {
  const type = MIME[path.extname(file)] || "application/octet-stream";
  const headers = { "content-type": type, "cache-control": "no-cache" };
  if (/json|javascript|css|html|svg/.test(type) && /\bgzip\b/.test(req.headers["accept-encoding"] || "")) {
    res.writeHead(200, { ...headers, "content-encoding": "gzip" });
    createReadStream(file).pipe(zlib.createGzip()).pipe(res);
  } else {
    res.writeHead(200, headers);
    createReadStream(file).pipe(res);
  }
}

const server = http.createServer((req, res) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405).end();
    return;
  }
  const { pathname } = new URL(req.url, "http://localhost");
  let rel;
  try {
    rel = pathname === "/" ? "index.html" : decodeURIComponent(pathname.slice(1));
  } catch {
    res.writeHead(400).end();
    return;
  }
  const file = path.normalize(path.join(PUBLIC, rel));
  const ok = file.startsWith(PUBLIC + path.sep) && existsSync(file) && statSync(file).isFile();
  serveFile(req, res, ok ? file : path.join(PUBLIC, "index.html"));
});

server.listen(PORT, () => {
  console.log(`Liahona Web listening on http://localhost:${PORT}`);
});
