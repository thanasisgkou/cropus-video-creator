"""Catalog every photo and video of the trip -> analysis/catalog.csv and analysis/days.txt

Sources come from project.json:

  "utc_offset_hours": -5,                       # local time of the trip (the film is told in local time)
  "sources": [
    {"dir": "D:/Trip/phone", "prefix": "P", "camera": "Pixel 7"},
    {"dir": "D:/Trip/gopro", "camera": "GoPro", "gopro": true, "clock_utc_offset_hours": 3.0}
  ]

Per source:
  dir                      folder with the files (not recursive unless "recursive": true)
  prefix                   id prefix: id = <prefix>_<file stem>; GoPro ids are the bare stem (GX010123)
  camera                   free text for the catalog
  gopro                    true: GoPro files (G*.MP4); the camera's .LRV low-res copy becomes the proxy
  clock_utc_offset_hours   the camera clock's offset from UTC (GoPro writes its local clock as if it were UTC;
                           phones write real UTC: leave it 0). tools/gopro_gps.py measures it from the GPS.
  photo_time               "exif_local" (default: EXIF DateTimeOriginal is local trip time unless an OffsetTime tag
                           says otherwise) or "exif_utc"

Ids: photos and videos get <prefix>_<stem>; a motion photo (JPEG with an MP4 inside, e.g. Pixel "MP" files) also
gets a short video L_<stem> extracted to <work_dir>/live (type "live").
Usage:   python tools/ingest.py
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

import config

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # HEIC photos are skipped without it
    pass

OUT = config.ANALYSIS
LIVE = config.LIVE
LOCAL = timedelta(hours=config.UTC_OFFSET_HOURS)
PHOTO_EXT = {".jpg", ".jpeg", ".heic", ".png"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv"}


def gps(g) -> tuple[float | None, float | None]:
    try:
        la = sum(float(x) / 60 ** i for i, x in enumerate(g[2]))
        lo = sum(float(x) / 60 ** i for i, x in enumerate(g[4]))
        if g.get(1) == "S":
            la = -la
        if g.get(3) == "W":
            lo = -lo
        return round(la, 5), round(lo, 5)
    except Exception:
        return None, None


def exif(p: Path, assume_local: bool) -> dict:
    d = {"dt": None, "lat": None, "lon": None, "w": None, "h": None, "model": ""}
    try:
        im = Image.open(p)
        d["w"], d["h"] = im.size
        ex = im.getexif()
        d["model"] = str(ex.get(272) or "")
        ifd = ex.get_ifd(0x8769)
        dt = ifd.get(36867) or ex.get(306)
        off = ifd.get(36881) or ifd.get(36880)
        if dt and dt[:4].isdigit():
            t = datetime.strptime(dt[:19], "%Y:%m:%d %H:%M:%S")
            m = re.match(r"([+-])(\d\d):(\d\d)", off or "")
            if m:  # to UTC, then to trip-local
                sign = 1 if m.group(1) == "+" else -1
                t = t - sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))) + LOCAL
            elif not assume_local:
                t = t + LOCAL
            d["dt"] = t
        if ex.get(274) in (5, 6, 7, 8):
            d["w"], d["h"] = d["h"], d["w"]
        g = ex.get_ifd(0x8825)
        if g:
            d["lat"], d["lon"] = gps(g)
    except Exception as e:  # noqa: BLE001
        d["err"] = str(e)[:80]
    return d


def probe(p: Path) -> dict:
    out = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:format_tags=creation_time,location,com.apple.quicktime.location.ISO6709:"
         "stream=codec_type,width,height,r_frame_rate:stream_side_data=rotation", "-of", "json", str(p)],
        capture_output=True, text=True, encoding="utf-8").stdout or "{}")
    v = next((s for s in out.get("streams", []) if s.get("codec_type") == "video"), {})
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        rot = int(sd.get("rotation", 0) or 0) or rot
    w, h = v.get("width", 0), v.get("height", 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    tags = out.get("format", {}).get("tags", {})
    utc = None
    if tags.get("creation_time"):
        try:
            utc = datetime.strptime(tags["creation_time"][:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            utc = None
    if utc and utc.year < 2005:  # unset camera clock
        utc = None
    lat = lon = None
    loc = tags.get("location") or tags.get("com.apple.quicktime.location.ISO6709") or ""
    m = re.match(r"([+-]\d+\.\d+)([+-]\d+\.\d+)", loc)
    if m and (float(m.group(1)), float(m.group(2))) != (0.0, 0.0):
        lat, lon = float(m.group(1)), float(m.group(2))
    try:
        a, b = v.get("r_frame_rate", "0/1").split("/")
        fps = round(int(a) / int(b), 2)
    except Exception:
        fps = 0
    return {"duration": round(float(out.get("format", {}).get("duration", 0) or 0), 2), "w": w, "h": h, "fps": fps,
            "utc": utc, "lat": lat, "lon": lon,
            "audio": any(s.get("codec_type") == "audio" for s in out.get("streams", []))}


def stem_id(name: str) -> str:
    s = re.sub(r"\.[A-Za-z0-9]+$", "", name)
    s = re.sub(r"^PXL_", "", s)
    return re.sub(r"[^0-9A-Za-z]+", "_", s).strip("_")


def extract_motion(p: Path, lid: str) -> Path | None:
    """Motion photo: an MP4 appended to the JPEG (length in the XMP Item:Length / MicroVideoOffset, else find 'ftyp')."""
    dst = LIVE / f"{lid}.mp4"
    if dst.exists():
        return dst
    b = p.read_bytes()
    lens = [int(x) for x in re.findall(rb'Item:Semantic="MotionPhoto"[^>]*?Item:Length="(\d+)"', b[:200000], re.S)]
    lens += [int(x) for x in re.findall(rb'MicroVideoOffset="(\d+)"', b[:200000])]
    start = len(b) - lens[0] if lens and lens[0] > 0 else -1
    if start <= 0 or b[start + 4:start + 8] != b"ftyp":
        i = b.find(b"ftypmp4")
        i = i if i > 0 else b.find(b"ftypisom")
        if i <= 0:
            return None
        start = i - 4
    LIVE.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b[start:])
    return dst


def row(**kw) -> dict:
    r = {"id": "", "src": "", "type": "", "path": "", "proxy": "", "local_time": "", "duration": "", "w": "", "h": "",
         "fps": "", "audio": "", "lat": "", "lon": "", "camera": "", "note": ""}
    r.update(kw)
    return r


def fmt(t: datetime | None) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S") if t else ""


def scan(src: dict) -> list[dict]:
    d = Path(src["dir"]).expanduser()
    if not d.is_absolute():
        d = config.PROJECT / d
    if not d.exists():
        print("missing source folder:", d)
        return []
    files = sorted(d.rglob("*") if src.get("recursive") else d.iterdir())
    files = [p for p in files if p.is_file() and p.suffix.lower() in PHOTO_EXT | VIDEO_EXT]
    is_gopro = bool(src.get("gopro"))
    prefix = src.get("prefix", "" if is_gopro else stem_id(d.name)[:6])
    cam = src.get("camera", d.name)
    clock = timedelta(hours=float(src.get("clock_utc_offset_hours", 0)))
    exif_local = src.get("photo_time", "exif_local") == "exif_local"

    def make_id(p: Path) -> str:
        return p.stem if is_gopro and not prefix else f"{prefix}_{stem_id(p.name)}" if prefix else stem_id(p.name)

    vids = [p for p in files if p.suffix.lower() in VIDEO_EXT]
    stills = [p for p in files if p.suffix.lower() in PHOTO_EXT]
    with ThreadPoolExecutor(6) as ex:
        vprobe = dict(zip(vids, ex.map(probe, vids)))
        sexif = dict(zip(stills, ex.map(lambda p: exif(p, exif_local), stills)))
    rows, lives = [], []
    for p in stills:
        e, sid = sexif[p], make_id(p)
        note = "" if e["dt"] else "undated"
        if ".MP." in p.name.upper() or p.stem.upper().endswith(".MP") or "MVIMG" in p.name.upper():
            lid = "L_" + stem_id(p.name)
            lp = extract_motion(p, lid)
            if lp:
                lives.append((lp, lid, sid, e))
                note = (note + f" live {lid}").strip()
        for k in ("PANO", "PORTRAIT", "LONG_EXPOSURE"):
            if k in p.name.upper():
                note = (note + " " + k.lower()).strip()
        rows.append(row(id=sid, src=prefix or "cam", type="photo", path=str(p), local_time=fmt(e["dt"]), w=e["w"], h=e["h"],
                        lat=e["lat"] or "", lon=e["lon"] or "", camera=cam + (f" ({e['model']})" if e["model"] else ""),
                        note=note))
    for p in vids:
        pr = vprobe[p]
        # creation_time: real UTC on phones; GoPro writes its own clock -> subtract the clock offset first
        local = pr["utc"] - clock + LOCAL if pr["utc"] else None
        lrv = next((q for q in (p.with_suffix(".LRV"), p.with_name(re.sub(r"^G[HX]", "GL", p.name)).with_suffix(".LRV"))
                    if is_gopro and q.exists()), None)
        rows.append(row(id=make_id(p), src="gopro" if is_gopro else (prefix or "cam"), type="video", path=str(p),
                        proxy=str(lrv) if lrv else "", local_time=fmt(local), duration=pr["duration"], w=pr["w"],
                        h=pr["h"], fps=pr["fps"], audio=pr["audio"], lat=pr["lat"] or "", lon=pr["lon"] or "",
                        camera=cam, note="" if local else "undated: place it by content"))
    with ThreadPoolExecutor(6) as ex:
        lprobe = list(ex.map(lambda t: probe(t[0]), lives))
    for (lp, lid, sid, e), pr in zip(lives, lprobe):
        if pr["duration"] <= 0.3:
            continue
        rows.append(row(id=lid, src="L", type="live", path=str(lp), local_time=fmt(e["dt"]), duration=pr["duration"],
                        w=pr["w"], h=pr["h"], fps=pr["fps"], audio=pr["audio"], lat=e["lat"] or "", lon=e["lon"] or "",
                        camera=cam + " (motion photo)", note=f"photo {sid}"))
    return rows


def apply_gopro_gps(rows: list[dict]) -> None:
    """Fill GoPro lat/lon from analysis/gopro_gps.csv (tools/gopro_gps.py) when present."""
    p = OUT / "gopro_gps.csv"
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        g = {Path(r["file"]).stem: r for r in csv.DictReader(fh)}
    for r in rows:
        if r["src"] == "gopro" and r["id"] in g and not r["lat"]:
            r["lat"], r["lon"] = g[r["id"]].get("lat", ""), g[r["id"]].get("lon", "")


def main() -> None:
    sources = config.CFG.get("sources", [])
    if not sources:
        raise SystemExit("project.json has no \"sources\" (see project.example.json)")
    rows = [r for s in sources for r in scan(s)]
    if not rows:
        raise SystemExit("no media found in the sources")
    ids = Counter(r["id"] for r in rows)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids (give the sources different prefixes): {dup[:10]}")
    apply_gopro_gps(rows)
    rows.sort(key=lambda r: (r["local_time"] or "9999", r["id"]))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "catalog.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    days = defaultdict(Counter)
    for r in rows:
        d = r["local_time"][:10] or "undated"
        days[d][r["src"] + "_" + r["type"]] += 1
        if r["type"] == "video":
            days[d]["video_s"] += float(r["duration"] or 0)
    lines = [f"{d}: video {c['video_s']/60:5.1f} min  " + "  ".join(f"{k}={v}" for k, v in sorted(c.items()) if k != "video_s")
             for d, c in sorted(days.items())]
    (OUT / "days.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(len(rows), "entries ->", OUT / "catalog.csv")


if __name__ == "__main__":
    main()
