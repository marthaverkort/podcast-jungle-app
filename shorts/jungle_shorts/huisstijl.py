"""Huisstijlen: per klant kleuren, lettertype, logo en tagline. Opgeslagen in shorts/huisstijlen/<slug>/."""

import base64
import json
import mimetypes
import re
from pathlib import Path

MAP = Path(__file__).resolve().parent.parent / "huisstijlen"

LETTERTYPES = ["Archivo", "Montserrat", "Poppins", "Inter Tight"]

STANDAARD = {
    "naam": "Podcast Jungle",
    "accent": "#16A34A",
    "accentTekst": "#FFFFFF",
    "vlak": "#18181B",
    "vlakDekking": 86,
    "tekst": "#FFFFFF",
    "lettertype": "Archivo",
    "eindkaart": "#16A34A",
    "tagline": "",
    "eindkaartAan": True,
    "ondertitels": True,
}

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def slug(naam):
    s = re.sub(r"[^a-z0-9]+", "-", naam.lower()).strip("-")
    return s or "huisstijl"


def _schoon(data):
    """Neem alleen bekende velden over en valideer ze."""
    s = dict(STANDAARD)
    for k in ("accent", "accentTekst", "vlak", "tekst", "eindkaart"):
        if _HEX.match(str(data.get(k, ""))):
            s[k] = data[k].upper()
    if data.get("lettertype") in LETTERTYPES:
        s["lettertype"] = data["lettertype"]
    try:
        s["vlakDekking"] = max(0, min(100, int(data.get("vlakDekking", s["vlakDekking"]))))
    except (TypeError, ValueError):
        pass
    s["naam"] = str(data.get("naam") or s["naam"])[:60]
    s["tagline"] = str(data.get("tagline") or "")[:80]
    for k in ("eindkaartAan", "ondertitels"):
        if k in data:
            s[k] = bool(data[k])
    return s


def lijst():
    MAP.mkdir(parents=True, exist_ok=True)
    stijlen = []
    for f in sorted(MAP.glob("*/stijl.json")):
        s = laad(f.parent.name)
        stijlen.append({"slug": f.parent.name, **s, "heeftLogo": bool(logo_pad(f.parent.name))})
    return stijlen


def laad(naam_slug):
    f = MAP / naam_slug / "stijl.json"
    if not f.is_file():
        return dict(STANDAARD)
    return _schoon(json.loads(f.read_text(encoding="utf-8")))


def bewaar(data, logo_bytes=None, logo_ext=None):
    s = _schoon(data)
    map_ = MAP / slug(s["naam"])
    map_.mkdir(parents=True, exist_ok=True)
    (map_ / "stijl.json").write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    if logo_bytes:
        for oud in map_.glob("logo.*"):
            oud.unlink()
        (map_ / f"logo{logo_ext or '.png'}").write_bytes(logo_bytes)
    return map_.name


def logo_pad(naam_slug):
    return next((MAP / naam_slug).glob("logo.*"), None) if (MAP / naam_slug).is_dir() else None


def voor_overlay(naam_slug):
    """Stijl in de vorm die overlay.html (zetStijl) verwacht."""
    s = laad(naam_slug)
    r, g, b = (int(s["vlak"][i:i + 2], 16) for i in (1, 3, 5))
    logo = None
    pad = logo_pad(naam_slug)
    if pad:
        mime = mimetypes.guess_type(pad.name)[0] or "image/png"
        logo = f"data:{mime};base64,{base64.b64encode(pad.read_bytes()).decode()}"
    return {
        "naam": s["naam"],
        "tagline": s["tagline"],
        "logo": logo,
        "eindkaartAan": s["eindkaartAan"],
        "ondertitels": s["ondertitels"],
        "css": {
            "--accent": s["accent"],
            "--accent-tekst": s["accentTekst"],
            "--vlak": f"rgba({r}, {g}, {b}, {s['vlakDekking'] / 100:.2f})",
            "--tekst": s["tekst"],
            "--font": f'"{s["lettertype"]}"',
            "--eindkaart": s["eindkaart"],
        },
    }
