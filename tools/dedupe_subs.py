"""Clips used twice (cold open + main cut) were subtitled by two subtitlers: keep one subtitle per source moment.
Later parts win (their subtitler saw the full scene). Backs up the files to analysis/subs/backup/.
Usage: python tools/dedupe_subs.py
"""
import json
import shutil
from pathlib import Path

from config import PROJECT as ROOT  # noqa: E402
files = sorted((ROOT / "analysis").glob("review_subs_auto_P*.json"), reverse=True)
(ROOT / "analysis" / "subs" / "backup").mkdir(parents=True, exist_ok=True)
kept: dict[str, list[tuple[float, float]]] = {}
for f in files:
    shutil.copy(f, ROOT / "analysis" / "subs" / "backup" / f.name)
    d = json.loads(f.read_text(encoding="utf-8"))
    out, dropped = [], 0
    for sb in d["subtitles"]:
        a, b = float(sb["from"]), float(sb["to"])
        if any(min(b, y) - max(a, x) > 0.15 for x, y in kept.get(sb["clip"], [])):
            dropped += 1
            continue
        out.append(sb)
    for sb in out:
        kept.setdefault(sb["clip"], []).append((float(sb["from"]), float(sb["to"])))
    d["subtitles"] = out
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f.name, len(out), "kept,", dropped, "duplicates dropped")
