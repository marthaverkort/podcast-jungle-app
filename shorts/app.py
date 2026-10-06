"""Jungle Shorts — lokale webapp. Start met: python app.py  (opent http://localhost:5055)"""

import threading
import traceback
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from jungle_shorts import pipeline

BASE = Path(__file__).parent
WORK = BASE / "werkmap"
UPLOADS = WORK / "uploads"
OUTPUT = WORK / "shorts"

app = Flask(__name__, static_folder=None)
jobs = {}


def start_job(fn, *args):
    job_id = uuid.uuid4().hex[:10]
    job = {"status": "bezig", "step": "Starten…", "progress": 0.0, "result": None, "error": None}
    jobs[job_id] = job

    def run():
        try:
            job["result"] = fn(job, *args)
            job["status"] = "klaar"
            job["progress"] = 1.0
        except Exception as exc:  # noqa: BLE001 - fout naar de UI sturen
            traceback.print_exc()
            job["status"] = "fout"
            job["error"] = str(exc)

    threading.Thread(target=run, daemon=True).start()
    return job_id


def resolve_video(path_str):
    path = Path(path_str.strip().strip('"')).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Video niet gevonden: {path}")
    return path


# ---------------------------------------------------------------- jobs

def job_highlights(job, video, count, mode, language):
    video = resolve_video(video)
    job["step"] = "Transcriberen (eerste keer duurt dit even)…"

    def on_progress(p):
        job["progress"] = 0.75 * p

    segments = pipeline.transcribe(video, language=language, progress=on_progress)
    job["step"] = "Highlights kiezen…"
    job["progress"] = 0.8
    clips = pipeline.select_highlights(segments, count=count, mode=mode)
    return {"video": str(video), "clips": clips}


def job_render(job, video, clips, fmt, subtitles):
    video = resolve_video(video)
    segments = pipeline.transcribe(video)
    out_dir = OUTPUT / video.stem
    files = []
    for i, clip in enumerate(clips, 1):
        job["step"] = f"Short {i} van {len(clips)} renderen…"
        job["progress"] = (i - 1) / len(clips)
        out = pipeline.render_clip(video, clip, segments, out_dir, fmt=fmt, subtitles=subtitles, index=i)
        files.append({"title": clip.get("title", out.stem), "url": f"/files/{video.stem}/{out.name}"})
    return {"files": files, "folder": str(out_dir.resolve())}


def job_download(job, url):
    job["step"] = "Video ophalen…"
    path = pipeline.download(url, UPLOADS)
    return {"video": str(path.resolve())}


# ---------------------------------------------------------------- routes

@app.get("/")
def index():
    return send_from_directory(BASE / "static", "index.html")


@app.post("/api/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="Geen bestand ontvangen."), 400
    UPLOADS.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS / Path(f.filename).name
    f.save(dest)
    return jsonify(video=str(dest.resolve()))


@app.post("/api/highlights")
def highlights():
    d = request.get_json(force=True)
    count = max(1, min(int(d.get("count", 5)), 20))
    mode = "snel" if d.get("mode") == "snel" else "grondig"
    return jsonify(job=start_job(job_highlights, d.get("video", ""), count, mode, d.get("language", "nl")))


@app.post("/api/render")
def render():
    d = request.get_json(force=True)
    fmt = d.get("format", "9:16")
    if fmt not in pipeline.FORMATS:
        return jsonify(error="Onbekend formaat."), 400
    clips = d.get("clips") or []
    if not clips:
        return jsonify(error="Selecteer minstens één clip."), 400
    return jsonify(job=start_job(job_render, d.get("video", ""), clips, fmt, bool(d.get("subtitles", True))))


@app.post("/api/fetch")
def fetch():
    url = (request.get_json(force=True).get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify(error="Plak een geldige link."), 400
    return jsonify(job=start_job(job_download, url))


@app.get("/api/job/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        abort(404)
    return jsonify(job)


@app.get("/files/<folder>/<name>")
def files(folder, name):
    path = (OUTPUT / folder / name).resolve()
    if OUTPUT.resolve() not in path.parents or not path.is_file():
        abort(404)
    return send_file(path)


if __name__ == "__main__":
    port = 5055
    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="127.0.0.1", port=port, debug=False)
