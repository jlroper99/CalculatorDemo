# Liahona Web

Listen to the Book of Mormon while the text follows along. The current verse is highlighted, the current word lights up as it is spoken, and the page scrolls with the narration. It also has AI chapter insights and an insight heatmap, similar to the Liahona Path iOS app.

## Run it

```bash
cd liahona-web
npm install
ANTHROPIC_API_KEY=sk-ant-... npm start     # http://localhost:3000
```

Without `ANTHROPIC_API_KEY` the app still works. Narration, sync, the heatmap and everything else run, but insights come from a basic keyword analysis and are labelled as such. "Ask" needs the key.

Optional env vars: `PORT` (default 3000), `LIAHONA_MODEL` (default `claude-opus-5-5`) and `LIAHONA_CACHE_DIR` (default `./cache/insights`).

## Features

**Listen and read in sync**
- Narration uses the browser's speech voices. Each verse is split into short chunks, and word-boundary events drive the word highlight. For voices that don't send boundary events, the highlight follows an estimated speaking speed instead.
- Auto-scroll keeps the spoken word in the upper third of the screen. If you scroll on your own, following pauses and a **Follow narration** button appears.
- Tap any word to start reading from there.
- Prev/next verse, speed from 0.75× to 2×, voice picker and an optional chapter announcement.
- It can continue into the next chapter, has a sleep timer (5/15/30/60 min or end of chapter), works with lock-screen media keys, and has keyboard shortcuts (Space, ↑/↓, `i`).
- **My recording** mode lets you play your own audio file for a chapter. The text is aligned to the audio by interpolation. Press **Sync** and tap each verse as it begins to pin it exactly; sync points are saved per chapter.

**AI chapter insights** (Claude)
- For each chapter: summary, narrative context, themes, key verses (tap to jump there), cross-references, discussion questions and how to apply it.
- Every verse gets a 0–10 "insight density" score. This drives the colored verse edges in the text, the strip beside the text that you can tap to jump, and the mini-chart in the panel.
- **Ask about this chapter**: a chat that uses the chapter text as context, with verse references turned into links.
- Results are cached on the server, so each chapter is generated only once.

**Insight heatmap**
- A grid of all 239 chapters with three views: insight intensity, one theme, or your listening progress.
- A themes-by-books matrix (tap a theme to map it chapter by chapter), plus a listening calendar.
- **Build the heatmap** generates insights for a whole book in one go.

**Study tools**
- Bookmarks, four highlight colors, verse notes and copy.
- Full-text search.
- A library with reading progress, day streak and weekly minutes.
- Light, sepia and dark themes.
- Export/import of your data. It is stored in the browser's localStorage.

## Layout

```
server.js            Node HTTP server: static files + /api (no framework)
lib/insights.js      Claude calls (structured JSON insights, chapter Q&A) + offline fallback
lib/scripture.js     Chapter lookup
public/              The single-page app (vanilla JS modules, no build step)
  js/narrator.js     Narration engine: speech-synthesis and recorded-audio sync
  js/app.js          Router, reader, insights panel, player
  js/heatmap.js      Heatmap view
  data/bom.json      Book of Mormon text (public domain)
test/                node --test unit tests
```

API: `GET /api/status`, `GET|POST /api/insights/:book/:chapter`, `GET /api/insights-index`, `POST /api/ask/:book/:chapter`.

## Notes

- Text is the public-domain Book of Mormon from the open [bcbooks/scriptures-json](https://github.com/bcbooks/scriptures-json) project.
- The app does not stream the Church's official recordings. Use the speech voices, or load an audio file you have the right to use with **My recording**.
- Voice quality depends on your device. Edge's "Natural" voices and Safari's Enhanced/Premium voices sound best.
- AI insights are a study aid. Check them against the text.
