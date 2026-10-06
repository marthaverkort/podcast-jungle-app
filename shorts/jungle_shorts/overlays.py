"""Grafische laag: tijdlijn van ondertitels + graphics -> transparante PNG's (via overlay.html) -> concat-lijst voor ffmpeg."""

import json
import os
from pathlib import Path

OVERLAY_HTML = Path(__file__).resolve().parent / "overlay.html"

SUB_NA_LOOP = 0.35  # zo lang blijft een woordgroep staan na het laatste woord


def _chunks(words, max_words=4, max_gap=0.6, max_len=1.8):
    chunks, cur = [], []
    for w in words:
        if cur and (
            len(cur) >= max_words
            or w["start"] - cur[-1]["end"] > max_gap
            or w["end"] - cur[0]["start"] > max_len
            or cur[-1]["word"].endswith((".", "?", "!"))
        ):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def tijdlijn(clip, segments, ondertitels=True):
    """Lijst van (begin, eind, state) relatief aan de clip; opeenvolgende gelijke states samengevoegd."""
    start, end = clip["start"], clip["end"]
    duur = end - start
    words = [
        {**w, "start": w["start"] - start, "end": w["end"] - start}
        for s in segments for w in s.get("words", [])
        if w.get("word") and w["end"] > start and w["start"] < end
    ] if ondertitels else []
    chunks = _chunks(words)

    graphics = []
    for g in clip.get("overlays", []):
        a, b = max(g["start"] - start, 0), min(g["end"] - start, duur)
        if b - a >= 1.0 and g.get("type") in ("hook", "stat", "punt"):
            graphics.append((a, b, g))

    grenzen = {0.0, duur}
    for i, c in enumerate(chunks):
        tot = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else duur
        c_eind = min(c[-1]["end"] + SUB_NA_LOOP, tot)
        grenzen.update(w["start"] for w in c)
        grenzen.add(c_eind)
        c.append({"_eind": c_eind})
    for a, b, _ in graphics:
        grenzen.update((a, b))
    punten = sorted(t for t in grenzen if 0 <= t <= duur)

    def state_op(t):
        st = {}
        for c in chunks:
            ws, c_eind = c[:-1], c[-1]["_eind"]
            if ws[0]["start"] <= t < c_eind:
                actief = max(i for i, w in enumerate(ws) if w["start"] <= t)
                st["sub"] = {"woorden": [w["word"].strip(".,!?;:") or w["word"] for w in ws], "actief": actief}
                break
        for a, b, g in graphics:
            if a <= t < b:
                if g["type"] == "hook":
                    st["hook"] = {"kicker": g.get("kicker", ""), "tekst": g.get("tekst", ""), "highlight": g.get("highlight", "")}
                elif g["type"] == "stat":
                    st["stat"] = {"kicker": g.get("kicker", ""), "waarde": g.get("waarde", ""), "sub": g.get("tekst", "")}
                else:
                    st["punt"] = {"nummer": g.get("nummer", "1"), "titel": g.get("tekst", ""), "sub": g.get("sub", "")}
        return st

    reeks = []
    for a, b in zip(punten, punten[1:]):
        if b - a < 1e-3:
            continue
        st = state_op(a)
        if reeks and reeks[-1][2] == st:
            reeks[-1] = (reeks[-1][0], b, st)
        else:
            reeks.append((a, b, st))
    return reeks


class Renderer:
    """Houdt één headless browser open en rendert states naar transparante PNG's."""

    def __init__(self, stijl, width, height):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        # JUNGLE_CHROMIUM: optioneel pad naar een eigen Chromium (standaard: die van `playwright install chromium`)
        self._browser = self._pw.chromium.launch(executable_path=os.environ.get("JUNGLE_CHROMIUM") or None)
        self.page = self._browser.new_page(viewport={"width": width, "height": height})
        self.page.goto(OVERLAY_HTML.as_uri())
        self.page.evaluate(
            "([w, h]) => { const s = document.getElementById('stage'); s.style.width = w + 'px'; s.style.height = h + 'px'; }",
            [width, height],
        )
        self.page.evaluate("s => zetStijl(s)", stijl)
        self.page.evaluate("document.fonts.ready.then(() => true)")
        self._cache = {}

    def png(self, state, pad):
        key = json.dumps(state, sort_keys=True)
        if key in self._cache:
            return self._cache[key]
        self.page.evaluate("s => render(s)", state)
        self.page.screenshot(path=str(pad), omit_background=True)
        self._cache[key] = pad
        return pad

    def sluit(self):
        self._browser.close()
        self._pw.stop()


def concat_lijst(reeks, renderer, map_):
    """Render elke state en schrijf een ffmpeg concat-lijst met duur per beeld."""
    map_ = Path(map_)
    map_.mkdir(parents=True, exist_ok=True)
    regels = ["ffconcat version 1.0"]
    laatste = None
    for i, (a, b, st) in enumerate(reeks):
        pad = renderer.png(st, map_ / f"laag_{i:04d}.png")
        regels += [f"file '{pad.name}'", f"duration {b - a:.3f}"]
        laatste = pad
    if laatste:
        regels.append(f"file '{laatste.name}'")  # concat-demuxer neemt de laatste duur alleen zo mee
    lijst = map_ / "laag.ffconcat"
    lijst.write_text("\n".join(regels) + "\n", encoding="utf-8")
    return lijst
