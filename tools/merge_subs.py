#!/usr/bin/env python3
"""Make the subtitle files safe to merge: no two subtitles of one clip may overlap in source time.

Hand-made subtitles (every review_*.json except review_subs_auto_*) win. Among the auto parts, the earlier
part wins. Overlapping later entries are trimmed if what is left still reads (>= 1.2 s), else dropped.
Usage: python tools/merge_subs.py   (rewrites analysis/review_subs_auto_P*.json in place)
"""
from __future__ import annotations

import json
from pathlib import Path

from config import PROJECT  # noqa: E402


def main() -> None:
    taken: dict[str, list[tuple[float, float]]] = {}
    for p in sorted((PROJECT / "analysis").glob("review_*.json")):
        if p.name.startswith("review_subs_auto"):
            continue
        for sb in json.loads(p.read_text(encoding="utf-8")).get("subtitles", []):
            taken.setdefault(sb["clip"], []).append((float(sb["from"]), float(sb["to"])))
    dropped = trimmed = 0
    for p in sorted((PROJECT / "analysis").glob("review_subs_auto_P*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        keep = []
        for sb in d["subtitles"]:
            a, b = float(sb["from"]), float(sb["to"])
            for x, y in taken.get(sb["clip"], []):
                if a < y and x < b:  # overlap: keep the free side if it is long enough
                    if x <= a:
                        a = y
                    else:
                        b = min(b, x)
            if b - a < 1.2:
                dropped += 1
                continue
            if (a, b) != (float(sb["from"]), float(sb["to"])):
                trimmed += 1
                sb["from"], sb["to"] = round(a, 3), round(b, 3)
            keep.append(sb)
            taken.setdefault(sb["clip"], []).append((a, b))
        d["subtitles"] = keep
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{p.name}: {len(keep)} subtitles")
    print(f"overlaps: {trimmed} trimmed, {dropped} dropped")


if __name__ == "__main__":
    main()
