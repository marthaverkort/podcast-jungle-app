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
                    "overlays": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["hook", "stat", "punt"]},
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                                "kicker": {"type": "string"},
                                "tekst": {"type": "string"},
                                "highlight": {"type": "string"},
                                "waarde": {"type": "string"},
                                "nummer": {"type": "string"},
                                "sub": {"type": "string"},
                            },
                            "required": ["type", "start", "end", "kicker", "tekst", "highlight", "waarde", "nummer", "sub"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "hook", "start", "end", "score", "reason", "caption", "hashtags", "overlays"],
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
- Sorteer op score, hoogste eerst.

Graphics (overlays) per short — je bent ook de motion designer:
- Altijd precies één "hook" in de eerste 0-4 seconden: kicker = label van 1-2 woorden in hoofdletters (bijv. "LET OP", "EN JIJ?"),
  tekst = de kern van de short in max 6 woorden, highlight = het ene woord uit die tekst dat de lading draagt.
- "stat" alleen als de spreker een concreet getal noemt: waarde = het getal zoals op beeld ("64,4%", "€12.000", "3x"),
  tekst = wat het getal betekent in max 5 woorden, kicker = 1 woord duiding. Zet hem op het moment dat het getal valt, 2-4 seconden.
- "punt" voor een opsomming of genummerd inzicht: nummer, tekst = het punt in max 6 woorden, sub = toelichting in max 7 woorden.
- Hoogstens 3 overlays per short, nooit twee tegelijk. Liever weinig en raak dan veel. Velden die niet van toepassing zijn: lege string.
- start/end van overlays zijn tijdstempels in de podcast (dus binnen start-end van de short)."""


def _format_transcript(segments):
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments)


def select_highlights(segments, count=5, mode="grondig", client=None):
    """Laat Claude de sterkste fragmenten kiezen. mode: 'snel' of 'grondig'."""
    client = client or anthropic.Anthropic()
    effort = "low" if mode == "snel" else "high"

    # Streaming: 10 shorts met graphics plus nadenken is een lang antwoord.
    with client.messages.stream(
        model=MODEL,
        max_tokens=64000,
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
    ) as stream:
        response = stream.get_final_message()
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

FPS = 30
EINDKAART_SEC = 2.0


def _video_size(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    s = json.loads(out.stdout)["streams"][0]
    return s["width"], s["height"]


def gezicht_x(video, start, end, stappen=12):
    """Mediaan van de horizontale gezichtspositie (0-1) in de clip, of None zonder gezicht/OpenCV."""
    try:
        import cv2
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    except (ImportError, AttributeError):
        return None
    cap = cv2.VideoCapture(str(video))
    xs = []
    for i in range(stappen):
        cap.set(cv2.CAP_PROP_POS_MSEC, (start + (end - start) * (i + 0.5) / stappen) * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        grijs = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h = grijs.shape[0]
        faces = cascade.detectMultiScale(grijs, scaleFactor=1.1, minNeighbors=6, minSize=(h // 10, h // 10))
        if len(faces):
            x, _, w, _ = max(faces, key=lambda f: f[2] * f[3])
            xs.append((x + w / 2) / grijs.shape[1])
    cap.release()
    return sorted(xs)[len(xs) // 2] if xs else None


def _crop_filter(video, start, end, width, height):
    src_w, src_h = _video_size(video)
    if src_w / src_h <= width / height:
        return f"crop=iw:iw*{height}/{width}"
    crop_w = int(src_h * width / height) // 2 * 2
    fx = gezicht_x(video, start, end)
    x = (src_w - crop_w) // 2 if fx is None else int(min(max(fx * src_w - crop_w / 2, 0), src_w - crop_w))
    return f"crop={crop_w}:ih:{x}:0"


def _encode_args(out_name):
    return ["-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out_name]


def _ffmpeg(cmd, cwd):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg faalde: {proc.stderr[-800:]}")


def render_clip(video, clip, segments, out_dir, fmt="9:16", stijl=None, index=1):
    """Knip, crop op de spreker, leg de grafische laag (ondertitels + graphics) erover en plak de eindkaart erachter.

    stijl: dict uit huisstijl.voor_overlay(); None = alleen knippen en croppen.
    """
    from . import overlays

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg niet gevonden. Installeer ffmpeg en zet het in je PATH.")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    width, height = FORMATS[fmt]
    start, end = clip["start"], clip["end"]
    video = Path(video).resolve()

    safe_title = "".join(c if c.isalnum() else "_" for c in clip.get("title", "short"))[:40].strip("_")
    name = f"short_{index:02d}_{safe_title or 'clip'}"
    werk = out_dir / f".{name}"
    werk.mkdir(exist_ok=True)
    base = f"{_crop_filter(video, start, end, width, height)},scale={width}:{height},setsar=1,fps={FPS}"
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(video)]

    renderer = None
    try:
        if stijl:
            renderer = overlays.Renderer(stijl, width, height)
            reeks = overlays.tijdlijn(clip, segments, ondertitels=stijl.get("ondertitels", True))
            laag = overlays.concat_lijst(reeks, renderer, werk)
            cmd += ["-f", "concat", "-safe", "0", "-i", str(laag),
                    "-filter_complex", f"[0:v]{base}[v];[1:v]format=rgba[o];[v][o]overlay=0:0:eof_action=pass,format=yuv420p[out]",
                    "-map", "[out]", "-map", "0:a?"]
        else:
            cmd += ["-vf", base]
        cmd += ["-t", f"{end - start:.2f}"]

        hoofd = werk / "hoofd.mp4"
        _ffmpeg(cmd + _encode_args(hoofd.name), werk)

        out_file = out_dir / f"{name}.mp4"
        if stijl and stijl.get("eindkaartAan", True):
            kaart_png = renderer.png({"eind": True}, werk / "eindkaart.png")
            _ffmpeg(["ffmpeg", "-y", "-loop", "1", "-t", f"{EINDKAART_SEC}", "-i", kaart_png.name,
                     "-f", "lavfi", "-t", f"{EINDKAART_SEC}", "-i", "anullsrc=r=48000:cl=stereo",
                     "-vf", f"scale={width}:{height},setsar=1,format=yuv420p", "-shortest"]
                    + _encode_args("eind.mp4"), werk)
            (werk / "lijst.txt").write_text("file 'hoofd.mp4'\nfile 'eind.mp4'\n", encoding="utf-8")
            _ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "lijst.txt", "-c", "copy",
                     "-movflags", "+faststart", str(out_file.resolve())], werk)
        else:
            hoofd.replace(out_file)
    finally:
        if renderer:
            renderer.sluit()
    shutil.rmtree(werk, ignore_errors=True)
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
