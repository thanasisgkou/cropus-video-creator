"""Print which director blocks have all their transcripts (used to start day directors as Whisper progresses)."""
import csv
import os
import sys
from pathlib import Path

from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
BLOCKS = config.director_blocks()  # project.json "director_blocks", or an even split of the days
rows = [r for r in csv.DictReader(open(ROOT / "analysis" / "catalog.csv", encoding="utf-8")) if r["type"] == "video"]
for d, days in BLOCKS.items():
    v = [r for r in rows if r["local_time"][:10] in days]
    done = sum((ROOT / "analysis" / "transcripts" / f"{r['id']}.json").exists() for r in v)
    print(f"{d} {done}/{len(v)}")
