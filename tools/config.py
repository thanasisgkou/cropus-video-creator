"""Project settings shared by every tool.

A *project* is one film: a folder with `project.json`, `analysis/`, `music/`, `assets/` and the edit files
(`edl.json`, `film.json`). Run the tools from inside that folder, or point CROPUS_PROJECT at it:

    cd my-trip
    python ../cropus-video-creator/tools/build_film.py edl.json film.json

Heavy, regenerable files (proxies, full-size JPGs, render caches, locks, scratch) live in `work_dir`
(default `<project>/work`); put it on a big disk. See `project.example.json` for every key.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent


def _find_project() -> Path:
    env = os.environ.get("CROPUS_PROJECT")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if (p / "project.json").exists():
            return p
    return here


PROJECT = _find_project()
CFG: dict = json.loads((PROJECT / "project.json").read_text(encoding="utf-8")) if (PROJECT / "project.json").exists() else {}


def _path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    p = Path(value).expanduser()
    return p if p.is_absolute() else PROJECT / p


ANALYSIS = PROJECT / "analysis"
WORK = _path(CFG.get("work_dir"), PROJECT / "work")
PROXY = WORK / "proxy"          # 480p H.264 copies of every video (same timeline as the original)
JPG = WORK / "jpg"              # every still as a full-size JPG, orientation applied
LIVE = WORK / "live"            # videos extracted from motion photos
RENDER = WORK / "render"        # renderer caches (segments, overlays)
CLEAN = WORK / "clean"          # optional voice-isolated WAVs (same timeline as the clip)
NARRATION = WORK / "narration"  # optional voice-over lines NN.mp3
LOCKS = WORK / "locks"
SCRATCH = WORK / "scratch"

UTC_OFFSET_HOURS = float(CFG.get("utc_offset_hours", 0))  # local time of the trip
PLACES: list = [tuple(x) for x in CFG.get("places", [])]  # [["YYYY-MM-DD HH:MM", "Place"], ...] in local time
LAND_GEOJSON = _path(CFG.get("land_geojson"), PROJECT / "assets" / "maps" / "ne_50m_land.geojson")
WHISPER = CFG.get("whisper", {})

_FONT_DIRS = {
    "Windows": [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"],
    "Darwin": [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"),
               Path.home() / "Library" / "Fonts"],
}.get(platform.system(), [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
                          Path.home() / ".local" / "share" / "fonts"])

_FONT_DEFAULTS = {  # role -> candidates (first that exists wins); a path in project.json "fonts" overrides
    "bold": ["bahnschrift.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf"],
    "text": ["segoeuisl.ttf", "segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "LiberationSans-Regular.ttf"],
    "label": ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "emoji": ["seguiemj.ttf", "NotoColorEmoji.ttf", "Apple Color Emoji.ttc"],
}


@lru_cache(None)
def font(role: str) -> str:
    """Path of a TrueType font for a role: bold (titles), text, label (contact sheets), emoji."""
    custom = CFG.get("fonts", {}).get(role)
    if custom:
        return str(_path(custom, Path(custom)))
    for name in _FONT_DEFAULTS[role]:
        for d in _FONT_DIRS:
            if (d / name).exists():
                return str(d / name)
            hits = list(d.rglob(name)) if d.exists() and platform.system() not in ("Windows",) else []
            if hits:
                return str(hits[0])
    if role == "emoji":
        return font("bold")
    raise FileNotFoundError(f"no font for '{role}': set project.json fonts.{role} to a .ttf path")


def ffmpeg_font(role: str) -> str:
    """Font path escaped for an ffmpeg drawtext filter (C:/x -> C\\:/x)."""
    return font(role).replace("\\", "/").replace(":", "\\:")


@lru_cache(None)
def nvenc() -> bool:
    """True when ffmpeg can actually encode with NVIDIA NVENC (setting "gpu": false in project.json turns it off)."""
    if CFG.get("gpu") is False or not shutil.which("ffmpeg"):
        return False
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1", "-c:v", "h264_nvenc",
                        "-f", "null", "-"], capture_output=True, text=True)
    return r.returncode == 0


def h264(quality: str = "preview") -> list[str]:
    """ffmpeg video-encoder arguments: NVENC when available, else libx264."""
    if quality == "master":
        return (["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "18", "-b:v", "0", "-profile:v", "high"]
                if nvenc() else ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high"])
    if quality == "proxy":
        return (["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "27"] if nvenc()
                else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"])
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "4", "-profile:v", "high"]


def hwaccel() -> list[str]:
    return ["-hwaccel", "cuda"] if nvenc() else []


def director_blocks(n: int = 4) -> dict[str, list[str]]:
    """Days per day-director: project.json "director_blocks" ({"d1": ["2024-05-01", ...], ...}), else the catalog's
    days split into n blocks with about the same amount of video; undated items ("") go to the last block."""
    if CFG.get("director_blocks"):
        return CFG["director_blocks"]
    import csv
    from collections import defaultdict
    secs: dict[str, float] = defaultdict(float)
    with open(ANALYSIS / "catalog.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            secs[r["local_time"][:10]] += float(r["duration"] or 0) + 3
    days = sorted(d for d in secs if d)
    total, blocks, acc, cur = sum(secs[d] for d in days) or 1, {}, 0.0, []
    for d in days:
        cur.append(d)
        acc += secs[d]
        if acc >= total * (len(blocks) + 1) / n and len(blocks) < n - 1:
            blocks[f"d{len(blocks) + 1}"], cur = cur, []
    blocks[f"d{len(blocks) + 1}"] = cur + [""]
    return blocks
