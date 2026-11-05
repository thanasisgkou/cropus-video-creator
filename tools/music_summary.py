"""Duration and integrated loudness of every track in music/ -> analysis/music/summary.json
Rows: [name, duration_s, 0, "LUFS", "", 0, ""] (the row shape build_film.py reads).  Usage: python tools/music_summary.py
"""
import json
import re
import subprocess
from pathlib import Path

from config import PROJECT as ROOT  # noqa: E402
out = ROOT / "analysis" / "music" / "summary.json"
out.parent.mkdir(parents=True, exist_ok=True)
rows = []
for mp3 in sorted((ROOT / "music").glob("*.mp3")):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp3), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                               capture_output=True, text=True).stdout)
    rows.append([mp3.stem, round(dur), 0, lufs, "", 0, ""])
    print(f"{mp3.stem:<80} {dur:6.0f}s {lufs} LUFS")
out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
