"""Shorts maken zonder de webapp.

Voorbeeld:
  python maak_shorts.py "\\\\Bobbie\\Video 2\\...\\RENDERS" --aantal 10 --huisstijl podcast-jungle

Geef je een map, dan pakt hij de grootste video daarin (de volledige aflevering).
"""

import argparse
import json
from pathlib import Path

from jungle_shorts import huisstijl, pipeline

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".mxf"}


def kies_video(pad):
    pad = Path(pad.strip().strip('"'))
    if pad.is_file():
        return pad
    if pad.is_dir():
        videos = [f for f in pad.iterdir() if f.suffix.lower() in VIDEO_EXT and f.is_file()]
        if videos:
            return max(videos, key=lambda f: f.stat().st_size)
        raise SystemExit(f"Geen video gevonden in {pad}")
    raise SystemExit(f"Pad niet gevonden: {pad}")


def main():
    ap = argparse.ArgumentParser(description="Maak shorts van een podcastaflevering.")
    ap.add_argument("video", help="Videobestand of map met de render")
    ap.add_argument("--aantal", type=int, default=10)
    ap.add_argument("--huisstijl", default="podcast-jungle", help="Map-naam in huisstijlen/ (leeg = zonder graphics)")
    ap.add_argument("--formaat", default="9:16", choices=list(pipeline.FORMATS))
    ap.add_argument("--modus", default="grondig", choices=["snel", "grondig"])
    ap.add_argument("--uit", help="Uitvoermap (standaard: werkmap/shorts/<videonaam>)")
    args = ap.parse_args()

    video = kies_video(args.video)
    print(f"Video: {video}")
    print("Transcriberen (eerste keer duurt dit even)...")
    segments = pipeline.transcribe(video, progress=lambda p: print(f"\r  {p:4.0%}", end="", flush=True))
    print("\nHighlights en graphics kiezen...")
    clips = pipeline.select_highlights(segments, count=args.aantal, mode=args.modus)
    if len(clips) < args.aantal:
        print(f"Let op: {len(clips)} bruikbare shorts gevonden in plaats van {args.aantal}.")

    out_dir = Path(args.uit) if args.uit else Path(__file__).parent / "werkmap" / "shorts" / video.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    stijl = huisstijl.voor_overlay(args.huisstijl) if args.huisstijl else None

    for i, clip in enumerate(clips, 1):
        print(f"[{i}/{len(clips)}] {clip['title']}  ({clip['start']:.0f}s-{clip['end']:.0f}s, score {clip['score']})")
        pipeline.render_clip(video, clip, segments, out_dir, fmt=args.formaat, stijl=stijl, index=i)

    # Captions en hashtags meteen klaar om te plakken
    (out_dir / "captions.json").write_text(json.dumps(
        [{"short": i, "titel": c["title"], "caption": c["caption"], "hashtags": c["hashtags"]}
         for i, c in enumerate(clips, 1)], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nKlaar: {len(clips)} shorts in {out_dir.resolve()}")


if __name__ == "__main__":
    main()
