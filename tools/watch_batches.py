"""Split the material into small watcher batches (small agent viewing tasks) -> analysis/watch/batches.json + index.json

Video batches: consecutive videos in time order, at most MAX_SHEETS contact sheets each (sheet = 24 frames, one per 2 s,
3 s for clips over 30 s), never mixing directors' blocks. Photo batches: one or more per day, at most MAX_PSHEETS photo sheets.
index.json maps every video/photo id to its batch file (analysis/watch/<batch>.json), for the directors.
Usage: python tools/watch_batches.py
"""
import csv
import json
import math
from pathlib import Path

from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
MAX_SHEETS, MAX_PSHEETS = 34, 6
BLOCKS = config.director_blocks()  # project.json "director_blocks", or an even split of the days
day_block = {d: b for b, ds in BLOCKS.items() for d in ds}
rows = list(csv.DictReader(open(ROOT / "analysis" / "catalog.csv", encoding="utf-8")))


def n_sheets(r) -> int:
    sd = ROOT / "analysis" / "sheets" / r["id"]
    if sd.exists() and any(sd.glob("*.jpg")):
        return len(list(sd.glob("*.jpg")))
    d = float(r["duration"] or 0)
    return max(1, math.ceil(d / (2 if d < 30 else 3) / 24))


batches, cur, cur_n, cur_blk = [], [], 0, None
for r in [r for r in rows if r["type"] == "video"]:
    blk = day_block[r["local_time"][:10]]
    n = n_sheets(r)
    if cur and (cur_n + n > MAX_SHEETS or blk != cur_blk):
        batches.append({"block": cur_blk, "videos": cur, "sheets": cur_n})
        cur, cur_n = [], 0
    cur.append(r["id"])
    cur_n += n
    cur_blk = blk
if cur:
    batches.append({"block": cur_blk, "videos": cur, "sheets": cur_n})
merged = []  # a small tail batch joins the previous batch of the same block
for b in batches:
    if merged and b["sheets"] < 10 and merged[-1]["block"] == b["block"]:
        merged[-1]["videos"] += b["videos"]
        merged[-1]["sheets"] += b["sheets"]
    else:
        merged.append(b)
batches = merged

photo_days = {}
for r in rows:
    if r["type"] == "photo":
        photo_days.setdefault(r["local_time"][:10] or "undated", []).append(r["id"])
pbatches = []  # consecutive days of one block share a batch, at most MAX_PSHEETS sheets
for day, ids in sorted(photo_days.items()):
    sheets = sorted((ROOT / "analysis" / "photo_sheets" / day).glob("sheet_*.jpg"))
    n = len(sheets) or math.ceil(len(ids) / 30)
    blk = day_block.get(day, "d3")
    for k in range(0, n, MAX_PSHEETS):
        part = list(range(k + 1, min(n, k + MAX_PSHEETS) + 1))
        chunk = {"day": day, "sheets": part, "photos": ids[k * 30:(k + MAX_PSHEETS) * 30]}
        last = pbatches[-1] if pbatches else None
        if last and last["block"] == blk and last["n"] + len(part) <= MAX_PSHEETS:
            last["photo_days"].append(chunk)
            last["n"] += len(part)
        else:
            pbatches.append({"block": blk, "photo_days": [chunk], "n": len(part)})
for b in pbatches:
    b["photos"] = [i for c in b["photo_days"] for i in c["photos"]]
    for c in b["photo_days"]:
        del c["photos"]
out = []
for i, b in enumerate(batches, 1):
    out.append({"batch": f"w{i:02d}", **b})
for i, b in enumerate(pbatches, 1):
    out.append({"batch": f"p{i:02d}", **b})
index = {}
for b in out:
    for cid in b.get("videos", []) + b.get("photos", []):
        index[cid] = b["batch"]
wd = ROOT / "analysis" / "watch"
wd.mkdir(parents=True, exist_ok=True)
(wd / "batches.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
(wd / "index.json").write_text(json.dumps(index, indent=0, ensure_ascii=False), encoding="utf-8")
for b in out:
    what = f"{len(b['videos'])} videos, {b['sheets']} sheets" if "videos" in b else " ".join(f"{c['day']}{c['sheets']}" for c in b["photo_days"])
    print(b["batch"], b["block"], what)
print(len(out), "batches")
