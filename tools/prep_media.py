"""Phase-0 media prep. Idempotent; run the parts you need:

  python tools/prep_media.py proxies   -> <work_dir>/proxy/<id>.mp4   (480p h264; GoPro: copy of the LRV)
  python tools/prep_media.py jpg       -> <work_dir>/jpg/<id>.jpg     (every still as full-res JPG, EXIF orientation applied)
  python tools/prep_media.py sheets    -> analysis/sheets/<id>/sheet_NN.jpg   (videos: one frame every 2 s, 6x4, true time label)
  python tools/prep_media.py photos    -> analysis/photo_sheets/<day>/sheet_NN.jpg (photos + lives per day, 6x5, id/time label)
  python tools/prep_media.py all
"""
from __future__ import annotations

import csv
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()
from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
PROXY = (config.WORK / "proxy")
JPG = (config.WORK / "jpg")
SHEETS = ROOT / "analysis" / "sheets"
PSHEETS = ROOT / "analysis" / "photo_sheets"
FONT = config.ffmpeg_font("label")
PIL_FONT = config.font("label")


def catalog() -> list[dict]:
    with open(ROOT / "analysis" / "catalog.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def proxy_one(r: dict) -> str:
    dst = PROXY / f"{r['id']}.mp4"
    if dst.exists():
        return "skip"
    tmp = dst.with_suffix(".part.mp4")
    res = None
    if r["proxy"]:  # GoPro LRV: already 480p h264, same duration
        res = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", r["proxy"], "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                              "-movflags", "+faststart", str(tmp)], capture_output=True, text=True, timeout=600)
    if res is None and r["src"] == "gopro" and config.nvenc():  # GoPro H.264: decode + resize on the GPU, ~3x faster
        w = int(round(480 * float(r["w"]) / float(r["h"]) / 2)) * 2
        res = subprocess.run(["ffmpeg", "-v", "error", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-c:v", "h264_cuvid",
                              "-resize", f"{w}x480", "-i", r["path"], "-vf", "hwdownload,format=nv12,fps=30,format=yuv420p",
                              *config.h264("proxy"), "-c:a", "aac", "-b:a", "96k", "-ac", "2",
                              "-movflags", "+faststart", str(tmp)], capture_output=True, text=True, timeout=1200)
    if res is None or res.returncode != 0:  # phones (4K HEVC), or a broken LRV: 480p h264, constant 30 fps
        res = subprocess.run(["ffmpeg", "-v", "error", "-y", *config.hwaccel(), "-i", r["path"],
                              "-vf", "scale=-2:480,fps=30,format=yuv420p", *config.h264("proxy"),
                              "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-movflags", "+faststart", str(tmp)],
                             capture_output=True, text=True, timeout=3600)
    if res.returncode == 0 and tmp.exists() and tmp.stat().st_size > 2000:
        tmp.replace(dst)
        return "ok"
    tmp.unlink(missing_ok=True)
    return "FAIL " + res.stderr.strip()[:120]


def proxies() -> None:
    PROXY.mkdir(parents=True, exist_ok=True)
    rows = [r for r in catalog() if r["type"] in ("video", "live")]
    with ThreadPoolExecutor(3) as ex:
        for r, s in zip(rows, ex.map(proxy_one, rows)):
            if s != "skip":
                print("proxy", r["id"], s, flush=True)


def jpg_one(r: dict) -> str:
    dst = JPG / f"{r['id']}.jpg"
    if dst.exists():
        return "skip"
    src = Path(r["path"])
    try:
        im = Image.open(src)
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((2400, 2400))
        im.save(dst, quality=92)
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"ERR {e}"[:120]


def jpgs() -> None:
    JPG.mkdir(parents=True, exist_ok=True)
    rows = [r for r in catalog() if r["type"] == "photo"]  # orientation applied, max 2400 px
    with ThreadPoolExecutor(4) as ex:
        for r, s in zip(rows, ex.map(jpg_one, rows)):
            if s not in ("skip", "ok"):
                print("jpg", r["id"], s, flush=True)


def sheet_one(r: dict) -> str:
    out = SHEETS / r["id"]
    if out.exists() and any(out.glob("*.jpg")):
        return "skip"
    out.mkdir(parents=True, exist_ok=True)
    src = PROXY / f"{r['id']}.mp4"
    step = 1.99 if float(r["duration"]) < 30 else 2.99
    vf = (f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{step})',scale=320:180:force_original_aspect_ratio=decrease,"
          "pad=320:180:(ow-iw)/2:(oh-ih)/2,"
          f"drawtext=fontfile='{FONT}':text='%{{pts\\:hms}}':x=6:y=6:fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.6,"
          "tile=6x4:padding=2:color=black")
    res = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-vf", vf, "-fps_mode", "vfr", "-q:v", "4",
                          str(out / "sheet_%02d.jpg")], capture_output=True, text=True)
    return res.stderr.strip()[:120] or f"{len(list(out.glob('*.jpg')))} sheets"


def sheets() -> None:
    rows = [r for r in catalog() if r["type"] == "video"]
    with ThreadPoolExecutor(4) as ex:
        for r, s in zip(rows, ex.map(sheet_one, rows)):
            print("sheet", r["id"], s, flush=True)


def still_path(r: dict) -> Path:
    p = JPG / f"{r['id']}.jpg"
    return p if p.exists() else Path(r["path"])


def photo_sheets() -> None:
    """Per day: every photo and live photo, 6 x 5 tiles of 320x240, label = id (+LIVE) and time."""
    cols, rows_n, tw, th = 6, 5, 320, 240
    font = ImageFont.truetype(PIL_FONT, 15)
    by_day = defaultdict(list)
    for r in catalog():
        if r["type"] == "photo":
            by_day[r["local_time"][:10] or "undated"].append(r)

    def build(day: str, items: list[dict]) -> str:
        out = PSHEETS / day
        if out.exists() and any(out.glob("*.jpg")):
            return f"{day} skip"
        out.mkdir(parents=True, exist_ok=True)
        per = cols * rows_n
        for n in range(0, len(items), per):
            page = Image.new("RGB", (cols * (tw + 2), rows_n * (th + 2)), "black")
            d = ImageDraw.Draw(page)
            for k, r in enumerate(items[n:n + per]):
                try:
                    im = Image.open(still_path(r))
                    im = ImageOps.exif_transpose(im)
                    im.thumbnail((tw, th))
                except Exception:
                    im = Image.new("RGB", (tw, th), "gray")
                x = (k % cols) * (tw + 2) + (tw - im.width) // 2
                y = (k // cols) * (th + 2) + (th - im.height) // 2
                page.paste(im, (x, y))
                label = f"{r['id']}{' LIVE' if 'live L_' in r['note'] else ''}  {r['local_time'][11:16]}"
                bx, by = (k % cols) * (tw + 2) + 4, (k // cols) * (th + 2) + 4
                d.rectangle([bx - 2, by - 1, bx + d.textlength(label, font=font) + 4, by + 18], fill=(0, 0, 0, 160))
                d.text((bx, by), label, fill="yellow", font=font)
            page.save(out / f"sheet_{n // per + 1:02d}.jpg", quality=85)
        return f"{day} {len(items)} items, {(len(items) + per - 1) // per} sheets"

    with ThreadPoolExecutor(4) as ex:
        for s in ex.map(lambda kv: build(*kv), sorted(by_day.items())):
            print("photos", s, flush=True)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("proxies", "all"):
        proxies()
    if what in ("jpg", "all"):
        jpgs()
    if what in ("sheets", "all"):
        sheets()
    if what in ("photos", "all"):
        photo_sheets()
