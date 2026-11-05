#!/usr/bin/env python3
"""Speech blocks of the film for the subtitlers: each run of consecutive speech shots of one clip, with its
source range, film time, word timings and the subtitles that already cover it.

Usage: python tools/subtitle_worklist.py film.json analysis/subs/worklist_P<N>.txt (writes 4 parts)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_film import FPS, PROJECT, frames, load_words  # noqa: E402


def main(film_path: str, out_dir: str, parts: int = 4) -> None:
    clips = json.loads(Path(film_path).read_text(encoding="utf-8"))["clips"]
    existing = {}
    for p in sorted((PROJECT / "analysis").glob("review_*.json")):
        if p.name.startswith("review_subs_auto"):
            continue
        for sb in json.loads(p.read_text(encoding="utf-8")).get("subtitles", []):
            existing.setdefault(sb["clip"], []).append((float(sb["from"]), float(sb["to"]), sb["text"].replace("\n", " / ")))
    blocks, t, i = [], 0.0, 0
    starts = []
    for c in clips:
        starts.append(t)
        t += frames(c) / FPS
    total = t
    while i < len(clips):
        c = clips[i]
        j = i
        while j + 1 < len(clips) and clips[j + 1]["clip"] == c["clip"] and abs(float(clips[j + 1]["in"]) - float(clips[j]["out"])) < 0.1:
            j += 1
        if c.get("audio") == "keep" and not c["clip"].startswith(("file:", "PHOTO:")) and not c.get("freeze"):
            a, b = float(c["in"]), float(clips[j]["out"])
            ws = [w for w in (load_words(c["clip"]) or []) if a - 0.05 <= w["s"] < b]
            if ws:
                blocks.append((starts[i], c, a, b, ws, [e for e in existing.get(c["clip"], []) if e[1] > a and e[0] < b]))
        i = j + 1
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    per = total / parts
    for n in range(parts):
        lines = []
        for st, c, a, b, ws, ex in blocks:
            if not (n * per <= st < (n + 1) * per or (n == parts - 1 and st >= total - 1)):
                continue
            lines.append(f"### film {int(st // 60):02d}:{st % 60:04.1f} | chapter {c['chapter']} | clip {c['clip']} | source {a:.2f}-{b:.2f}")
            lines.append(f"    context: {c.get('desc', '')[:160]}")
            for e in ex:
                lines.append(f"    ALREADY SUBTITLED {e[0]:.2f}-{e[1]:.2f}: {e[2]}")
            lines.append("    words: " + " ".join(f"[{w['s']:.2f}-{w['e']:.2f}]{w['w'].strip()}" for w in ws))
            lines.append("")
        (Path(out_dir) / f"worklist_P{n + 1}.txt").write_text("\n".join(lines), encoding="utf-8")
        print(f"part {n + 1}: {sum(1 for l in lines if l.startswith('###'))} blocks")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
