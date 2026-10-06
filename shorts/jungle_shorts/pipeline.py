"""Jungle Shorts pipeline: transcriberen -> highlights kiezen -> shorts renderen."""

import json
import shutil
import subprocess
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"

FORMATS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}

MIN_CLIP_SEC = 15
MAX_CLIP_SEC = 90


# ---------------------------------------------------------------- transcript

def transcribe(video, model_size="small", language="nl", progress=None):
    """Transcribeer met faster-whisper (woord-timestamps). Cachet naast de video."""
    video = Path(video)
    cache = video.with_suffix(video.suffix + ".transcript.json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, info = model.transcribe(
        str(video), language=language or None, word_timestamps=True, vad_filter=True
    )
    result = []
    for seg in segments:
        result.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "words": [
                {"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()}
                for w in (seg.words or [])
            ],
        })
        if progress and info.duration:
            progress(min(seg.end / info.duration, 1.0))

    cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


# ---------------------------------------------------------------- highlights

HIGHLIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                    "caption": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "hook", "start", "end", "score", "reason", "caption", "hashtags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Je bent een ervaren short-form video-editor voor Podcast Jungle, een podcaststudio voor ondernemers.
Je kiest uit een podcasttranscript de fragmenten die als losse short (TikTok, Reels, YouTube Shorts) het best presteren.

Wat een goede short is:
- De eerste 2 seconden werpen een vraag op, doen een stellige uitspraak of beginnen midden in spanning. Geen aanloop ("ja, dus, eh...").
- Het fragment is zonder context te begrijpen en sluit af met een afgeronde gedachte, pointe of inzicht.
- Concreet boven abstract: cijfers, fouten, verhalen, tegendraadse meningen.
- Duur tussen {min_sec} en {max_sec} seconden.

Regels:
- Gebruik alleen tijdstempels die in het transcript staan. Begin op het begin van een zin en eindig op het einde van een zin.
- Fragmenten overlappen niet.
- score (1-10) = hoe sterk de hook en de afronding zijn. Wees streng.
- title: korte pakkende titel (max 8 woorden). hook: de letterlijke openingszin. reason: waarom dit werkt (1 zin).
- caption: social caption van 1-3 zinnen in de taal van de podcast. hashtags: 3-6 stuks, zonder #.
- Sorteer op score, hoogste eerst."""


def _format_transcript(segments):
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments)


def select_highlights(segments, count=5, mode="grondig", client=None):
    """Laat Claude de sterkste fragmenten kiezen. mode: 'snel' of 'grondig'."""
    client = client or anthropic.Anthropic()
    effort = "low" if mode == "snel" else "high"

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT.format(min_sec=MIN_CLIP_SEC, max_sec=MAX_CLIP_SEC),
        messages=[{
            "role": "user",
            "content": f"Kies de {count} beste shorts uit dit transcript.\n\n<transcript>\n"
                       f"{_format_transcript(segments)}\n</transcript>",
        }],
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": HIGHLIGHT_SCHEMA},
        },
        # Bij een (onterechte) weigering laat de API automatisch een ander model het overnemen.
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude weigerde dit transcript te verwerken.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Antwoord afgekapt; vraag minder clips aan.")

    text = next(b.text for b in response.content if b.type == "text")
    clips = json.loads(text)["clips"]
    clips = [snap_to_segments(c, segments) for c in clips]
    clips = [c for c in clips if c["end"] - c["start"] >= MIN_CLIP_SEC * 0.6]
    clips.sort(key=lambda c: c["score"], reverse=True)
    return clips[:count]


def snap_to_segments(clip, segments):
    """Leg begin en eind op zinsgrenzen, binnen de toegestane duur."""
    start, end = float(clip["start"]), float(clip["end"])
    starts = [s["start"] for s in segments]
    ends = [s["end"] for s in segments]
    if starts:
        start = min(starts, key=lambda t: abs(t - start))
        candidates = [t for t in ends if t > start] or ends
        end = min(candidates, key=lambda t: abs(t - end))
        if end - start > MAX_CLIP_SEC:
            fitting = [t for t in ends if start < t <= start + MAX_CLIP_SEC]
            end = max(fitting) if fitting else start + MAX_CLIP_SEC
    return {**clip, "start": round(start, 2), "end": round(end, 2)}


# ---------------------------------------------------------------- render

def _ass_time(t):
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _chunk_words(words, max_words=3, max_gap=0.6, max_len=1.4):
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


def build_ass(segments, start, end, width, height):
    """Ondertitels in shorts-stijl: korte woordgroepen, groot en vet, actief woord in groen."""
    words = [
        w for s in segments for w in s.get("words", [])
        if w["end"] > start and w["start"] < end and w["word"]
    ]
    font_size = int(width * 0.075)
    margin_v = int(height * 0.22)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Short,Arial Black,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(font_size // 12, 4)},2,2,60,60,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for chunk in _chunk_words(words):
        for i, active in enumerate(chunk):
            a = active["start"] - start
            b = (chunk[i + 1]["start"] if i + 1 < len(chunk) else chunk[-1]["end"]) - start
            text = " ".join(
                ("{\\c&H5EC522&}" + w["word"].upper() + "{\\c&HFFFFFF&}") if w is active
                else w["word"].upper()
                for w in chunk
            )
            lines.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Short,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def _video_size(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    s = json.loads(out.stdout)["streams"][0]
    return s["width"], s["height"]


def render_clip(video, clip, segments, out_dir, fmt="9:16", subtitles=True, index=1):
    """Knip, crop (midden) naar het gekozen formaat en brand ondertitels in."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg niet gevonden. Installeer ffmpeg en zet het in je PATH.")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    width, height = FORMATS[fmt]
    start, end = clip["start"], clip["end"]

    src_w, src_h = _video_size(video)
    target_ratio = width / height
    if src_w / src_h > target_ratio:
        crop = f"crop=ih*{width}/{height}:ih"
    else:
        crop = f"crop=iw:iw*{height}/{width}"
    filters = [crop, f"scale={width}:{height}", "setsar=1"]

    safe_title = "".join(c if c.isalnum() else "_" for c in clip.get("title", "short"))[:40].strip("_")
    name = f"short_{index:02d}_{safe_title or 'clip'}"
    if subtitles:
        ass_name = f"{name}.ass"
        (out_dir / ass_name).write_text(build_ass(segments, start, end, width, height), encoding="utf-8")
        # Relatieve bestandsnaam + cwd=out_dir: voorkomt escape-problemen met C:\-paden.
        filters.append(f"ass={ass_name}")

    out_file = out_dir / f"{name}.mp4"
    cmd = [
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(Path(video).resolve()),
        "-t", f"{end - start:.2f}", "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_file.name,
    ]
    proc = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg faalde: {proc.stderr[-800:]}")
    return out_file


def download(url, out_dir):
    """Haal een video op via een link (YouTube, Drive, ...) met yt-dlp."""
    import yt_dlp

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(out_dir / "%(title).80s.%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info)).with_suffix(".mp4")
