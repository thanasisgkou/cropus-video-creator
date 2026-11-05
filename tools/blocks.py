"""Write one compact catalog slice per day director: analysis/directors/blocks/<id>_catalog.txt
Usage: python tools/blocks.py
"""
import csv
import json
from pathlib import Path

from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
BLOCKS = config.director_blocks()  # project.json "director_blocks", or an even split of the days
out = ROOT / "analysis" / "directors" / "blocks"
out.mkdir(parents=True, exist_ok=True)
with open(ROOT / "analysis" / "catalog.csv", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
tx = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "analysis" / "transcripts").glob("*.json")}
for did, days in BLOCKS.items():
    mine = [r for r in rows if (r["local_time"][:10] or "") in days]
    lines = [f"# {did}: days {', '.join(d or 'undated' for d in days)} — {len(mine)} items",
             "# id | type | local time | dur s | WxH | camera | lat,lon | transcript (first words)"]
    for r in mine:
        t = tx.get(r["id"], {})
        words = " ".join(s["text"] for s in t.get("segments", []))[:90]
        lang = t.get("language", "")
        geo = f"{r['lat']},{r['lon']}" if r["lat"] else ""
        cam = r["camera"].split(" ")[0]
        lines.append(f"{r['id']} | {r['type']} | {r['local_time'][5:16]} | {r['duration'] or '-'} | {r['w']}x{r['h']} | {cam} | {geo} | "
                     f"{(lang + ': ') if words else ''}{words}")
    (out / f"{did}_catalog.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(did, len(mine), "items,", sum(1 for r in mine if r["type"] == "video"), "videos,",
          sum(1 for r in mine if r["type"] == "photo"), "photos")
