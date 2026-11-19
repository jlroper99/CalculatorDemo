// Narration engine. Two sources share one interface:
//  - "tts":   the browser's speech synthesis, synced word-by-word via boundary events
//             (with a timing estimator for voices that don't emit them).
//  - "audio": a user-supplied recording, synced by piecewise-linear interpolation over
//             calibration anchors (time -> character position).
// Emits: "position" {verse, start, end}, "state" {playing}, "ended", "error" {message}.

import { logListening } from "./store.js";

const MAX_CHUNK = 200;
const VERSE_GAP = 24; // virtual characters of silence between verses (audio mode)

export function wordAt(text, i) {
  i = Math.max(0, Math.min(i, text.length - 1));
  let start = i;
  while (start > 0 && !/\s/.test(text[start - 1])) start--;
  let end = i;
  while (end < text.length && !/\s/.test(text[end])) end++;
  return [start, end];
}

/** Split text (from offset) into speakable chunks that end at punctuation where possible. */
export function chunk(text, offset = 0, max = MAX_CHUNK) {
  const out = [];
  let pos = offset;
  while (pos < text.length) {
    while (pos < text.length && /\s/.test(text[pos])) pos++;
    if (pos >= text.length) break;
    let end = Math.min(text.length, pos + max);
    if (end < text.length) {
      const slice = text.slice(pos, end);
      const m = Math.max(slice.lastIndexOf(". "), slice.lastIndexOf("; "), slice.lastIndexOf(": "), slice.lastIndexOf("? "), slice.lastIndexOf("! "));
      const c = slice.lastIndexOf(", ");
      const s = slice.lastIndexOf(" ");
      const cut = m > max * 0.4 ? m + 1 : c > max * 0.4 ? c + 1 : s > 0 ? s : slice.length;
      end = pos + cut;
    }
    out.push({ offset: pos, text: text.slice(pos, end) });
    pos = end;
  }
  return out;
}

export class Narrator extends EventTarget {
  constructor() {
    super();
    this.mode = "tts";
    this.rate = 1;
    this.voice = null;
    this.verses = [];
    this.title = "";
    this.announce = true;
    this.playing = false;
    this.verse = 1;
    this.char = 0;
    this.gen = 0;
    this.audio = new Audio();
    this.audio.preload = "auto";
    this.anchors = [];
    this._raf = 0;
    this._tick = null;
    this._est = null;

    this.audio.addEventListener("ended", () => {
      this._setPlaying(false);
      this.emit("ended");
    });
    this.audio.addEventListener("pause", () => this.mode === "audio" && this._setPlaying(false));
    this.audio.addEventListener("play", () => {
      if (this.mode !== "audio") return;
      this._setPlaying(true);
      this._loopAudio();
    });
    this.audio.addEventListener("loadedmetadata", () => this.emit("audioready", { duration: this.audio.duration }));

    if ("speechSynthesis" in window) {
      // Some browsers silently stop speech when the tab is hidden for a while; nothing to do but stay consistent.
      window.addEventListener("pagehide", () => speechSynthesis.cancel());
    }
  }

  get ttsSupported() {
    return "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  }

  emit(type, detail = {}) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }

  load({ title, verses }, { verse = 1 } = {}) {
    this.stop();
    this.title = title;
    this.verses = verses;
    this.verse = Math.min(Math.max(1, verse), verses.length);
    this.char = 0;
    this._starts = [];
    let acc = 0;
    for (const v of verses) {
      this._starts.push(acc);
      acc += v.length + VERSE_GAP;
    }
    this._total = acc;
  }

  // ----- shared controls ---------------------------------------------------

  play(verse = this.verse, char = this.char) {
    if (!this.verses.length) return;
    this.verse = verse;
    this.char = char;
    if (this.mode === "audio") {
      if (!this.audio.src) return this.emit("error", { message: "Choose an audio file first." });
      this.audio.currentTime = this._timeFor(verse, char);
      this.audio.play().catch((e) => this.emit("error", { message: e.message }));
      this._loopAudio();
    } else {
      if (!this.ttsSupported) return this.emit("error", { message: "Speech synthesis isn't supported in this browser." });
      speechSynthesis.cancel();
      this._setPlaying(true);
      const intro = this.announce && verse === 1 && char === 0 ? this.title : null;
      this._speakVerse(verse, char, intro);
    }
  }

  pause() {
    if (this.mode === "audio") {
      this.audio.pause();
    } else {
      this.gen++;
      this._clearEstimator();
      if (this.ttsSupported) speechSynthesis.cancel();
      this._setPlaying(false);
    }
  }

  stop() {
    this.pause();
    this.char = 0;
  }

  toggle() {
    this.playing ? this.pause() : this.play();
  }

  seek(verse, char = 0) {
    verse = Math.min(Math.max(1, verse), this.verses.length);
    const wasPlaying = this.playing;
    if (wasPlaying && this.mode === "tts") this.pause();
    this.verse = verse;
    this.char = char;
    this._emitPos(verse, char);
    if (this.mode === "audio") {
      if (this.audio.src) this.audio.currentTime = this._timeFor(verse, char);
    } else if (wasPlaying) {
      this.play(verse, char);
    }
  }

  step(delta) {
    this.seek(this.verse + delta, 0);
  }

  setRate(rate) {
    this.rate = rate;
    this.audio.playbackRate = rate;
    if (this.playing && this.mode === "tts") this.play(this.verse, this._wordStart ?? this.char);
  }

  setVoice(voice) {
    this.voice = voice;
    if (this.playing && this.mode === "tts") this.play(this.verse, this._wordStart ?? this.char);
  }

  setMode(mode) {
    if (mode === this.mode) return;
    this.pause();
    this.mode = mode;
    this.emit("mode", { mode });
  }

  _setPlaying(p) {
    if (this.playing === p) return;
    this.playing = p;
    clearInterval(this._tick);
    if (p) this._tick = setInterval(() => logListening(5), 5000);
    this.emit("state", { playing: p });
  }

  _emitPos(verse, char) {
    const text = this.verses[verse - 1] ?? "";
    const [start, end] = wordAt(text, char);
    this._wordStart = start;
    this.verse = verse;
    this.char = char;
    this.emit("position", { verse, start, end });
  }

  // ----- TTS ---------------------------------------------------------------

  _speakVerse(verse, offset, intro) {
    const gen = ++this.gen;
    const text = this.verses[verse - 1];
    const parts = chunk(text, offset);
    if (intro) parts.unshift({ offset: -1, text: intro });
    let i = 0;

    const next = () => {
      if (gen !== this.gen) return;
      this._clearEstimator();
      if (i >= parts.length) {
        if (verse < this.verses.length) {
          this._speakVerse(verse + 1, 0, null);
        } else {
          this._setPlaying(false);
          this.verse = this.verses.length;
          this.emit("ended");
        }
        return;
      }
      const part = parts[i++];
      const u = new SpeechSynthesisUtterance(part.text);
      u.rate = this.rate;
      if (this.voice) {
        u.voice = this.voice;
        u.lang = this.voice.lang;
      }
      let gotBoundary = false;
      u.onstart = () => {
        if (gen !== this.gen || part.offset < 0) return;
        this._emitPos(verse, part.offset);
        this._startEstimator(gen, verse, part, () => gotBoundary);
      };
      u.onboundary = (e) => {
        if (gen !== this.gen || part.offset < 0) return;
        if (e.name && e.name !== "word") return;
        gotBoundary = true;
        this._clearEstimator();
        this._emitPos(verse, part.offset + e.charIndex);
      };
      u.onend = next;
      u.onerror = (e) => {
        if (gen !== this.gen) return;
        if (e.error === "interrupted" || e.error === "canceled") return;
        if (e.error === "not-allowed") {
          this._setPlaying(false);
          return this.emit("error", { message: "The browser blocked speech. Press play again." });
        }
        next();
      };
      speechSynthesis.speak(u);
    };
    next();
  }

  // Voices without boundary events (common on Linux/Firefox and some mobile voices):
  // advance the highlight at an estimated speaking speed until a real boundary arrives.
  _startEstimator(gen, verse, part, hasBoundary) {
    this._clearEstimator();
    const cps = 14.5 * this.rate;
    const t0 = performance.now();
    this._est = setInterval(() => {
      if (gen !== this.gen || hasBoundary()) return this._clearEstimator();
      const elapsed = (performance.now() - t0) / 1000;
      if (elapsed < 0.6) return;
      const c = Math.min(part.text.length - 1, Math.floor(elapsed * cps));
      this._emitPos(verse, part.offset + c);
    }, 90);
  }

  _clearEstimator() {
    clearInterval(this._est);
    this._est = null;
  }

  // ----- recorded audio ----------------------------------------------------

  setAudioFile(file) {
    if (this._objectUrl) URL.revokeObjectURL(this._objectUrl);
    this._objectUrl = URL.createObjectURL(file);
    this.audio.src = this._objectUrl;
    this.audio.playbackRate = this.rate;
    this.audioName = file.name;
  }

  setAnchors(anchors) {
    this.anchors = anchors || [];
  }

  /** Pin the current playback time to the start of a verse. Returns the new anchor list. */
  addAnchor(verse) {
    const t = this.audio.currentTime;
    const pos = this._starts[verse - 1];
    const kept = this.anchors.filter(([at, p]) => Math.abs(at - t) > 0.25 && p !== pos);
    kept.push([t, pos]);
    kept.sort((a, b) => a[0] - b[0]);
    // keep anchors monotonic in both time and position
    this.anchors = kept.filter((a, i, arr) => i === 0 || a[1] > arr[i - 1][1]);
    this._emitPos(verse, 0);
    return this.anchors;
  }

  _points() {
    const d = this.audio.duration;
    const pts = [[0, 0], ...this.anchors];
    if (Number.isFinite(d) && (!pts.length || pts[pts.length - 1][0] < d)) pts.push([d, this._total]);
    return pts;
  }

  _posFor(t) {
    const pts = this._points();
    for (let i = 1; i < pts.length; i++) {
      const [t0, p0] = pts[i - 1];
      const [t1, p1] = pts[i];
      if (t <= t1) return p0 + ((t - t0) / Math.max(1e-6, t1 - t0)) * (p1 - p0);
    }
    return this._total;
  }

  _timeFor(verse, char) {
    const pos = this._starts[verse - 1] + char;
    const pts = this._points();
    for (let i = 1; i < pts.length; i++) {
      const [t0, p0] = pts[i - 1];
      const [t1, p1] = pts[i];
      if (pos <= p1) return t0 + ((pos - p0) / Math.max(1e-6, p1 - p0)) * (t1 - t0);
    }
    return 0;
  }

  _loopAudio() {
    cancelAnimationFrame(this._raf);
    const tick = () => {
      if (this.mode !== "audio") return;
      const pos = this._posFor(this.audio.currentTime);
      let v = this._starts.length;
      while (v > 1 && this._starts[v - 1] > pos) v--;
      const c = Math.min(this.verses[v - 1].length - 1, Math.max(0, Math.floor(pos - this._starts[v - 1])));
      if (v !== this.verse || Math.abs(c - this.char) > 1) this._emitPos(v, c);
      if (!this.audio.paused) this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
  }
}
