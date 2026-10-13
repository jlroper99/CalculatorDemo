# Liahona Web

Listen to the Book of Mormon while the text follows along. The current verse is highlighted, the current word lights up as it is spoken, and the page scrolls with the narration. Inspired by the Liahona Path iOS app.

It's free to run: no API keys, no accounts and no dependencies.

## Run it

Requires Node.js 20 or newer.

```bash
cd liahona-web
npm start     # http://localhost:3000
```

(On Windows PowerShell, use `npm.cmd start` if scripts are blocked.) Set `PORT` to use a different port.

## Features

**Listen and read in sync**
- Narration uses the browser's speech voices. Each verse is split into short chunks, and word-boundary events drive the word highlight. For voices that don't send boundary events, the highlight follows an estimated speaking speed instead.
- Auto-scroll keeps the spoken word in the upper third of the screen. If you scroll on your own, following pauses and a **Follow narration** button appears.
- Tap any word to start reading from there.
- Prev/next verse, speed from 0.75× to 2×, voice picker and an optional chapter announcement.
- It can continue into the next chapter, has a sleep timer (5/15/30/60 min or end of chapter), works with lock-screen media keys, and has keyboard shortcuts (Space, ↑/↓).
- **My recording** mode lets you play your own audio file for a chapter. The text is aligned to the audio by interpolation. Press **Sync** and tap each verse as it begins to pin it exactly; sync points are saved per chapter.

**Progress**
- A grid of all 239 chapters showing which you've completed, plus a listening calendar, day streak and total minutes.

**Study tools**
- Bookmarks, four highlight colors, verse notes and copy.
- Full-text search.
- Light, sepia and dark themes.
- Export/import of your data. It is stored in the browser's localStorage.

## Layout

```
server.js            Tiny static file server (no dependencies)
public/              The single-page app (vanilla JS modules, no build step)
  js/narrator.js     Narration engine: speech-synthesis and recorded-audio sync
  js/app.js          Router, library, reader, player, saved, search
  js/progress.js     Progress view
  data/bom.json      Book of Mormon text (public domain)
test/                node --test unit tests (`npm test`)
```

## Notes

- Text is the public-domain Book of Mormon from the open [bcbooks/scriptures-json](https://github.com/bcbooks/scriptures-json) project.
- The app does not stream the Church's official recordings. Use the speech voices, or load an audio file you have the right to use with **My recording**.
- Voice quality depends on your device. Edge's "Natural" voices and Safari's Enhanced/Premium voices sound best.
