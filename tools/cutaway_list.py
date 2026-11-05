#!/usr/bin/env python3
"""List every cutaway with what is said under it and where both shots were filmed, for the place check.

Usage: python tools/cutaway_list.py film.json analysis/verify/cutaways_place.txt
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_film import FPS, frames, load_words, place_of, clip_time  # noqa: E402


def said(clip: str, a: float, b: float) -> str:
    return "".join(w["w"] for w in (load_words(clip) or []) if a <= w["s"] < b).strip()


def main(film_path: str, out_path: str) -> None:
    clips = json.loads(Path(film_path).read_text(encoding="utf-8"))["clips"]
    t, lines, n = 0.0, [], 0
    for c in clips:
        for cw in c.get("cutaways", []):
            n += 1
            st = t + float(cw["start"])
            src = float(c["in"]) + float(cw["start"])
            lines.append(
                f"#{n:03d} film {int(st // 60):02d}:{st % 60:04.1f} | host {c['clip']} ({place_of(c['clip'])}, {clip_time(c['clip'])}) "
                f"chapter {c['chapter']} | CUTAWAY {cw['clip']} in {float(cw['in']):.1f} dur {float(cw['dur']):.1f} "
                f"({place_of(cw['clip'])}, {clip_time(cw['clip'])}){' [memory look]' if cw.get('style') == 'flashback' else ''}\n"
                f"     before: «{said(c['clip'], src - 6, src)}»\n"
                f"     under:  «{said(c['clip'], src, src + float(cw['dur']))}»")
        t += frames(c) / FPS
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"{n} cutaways -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
