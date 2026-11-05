#!/usr/bin/env python3
"""Speech audibility check on a rendered film.

Flags speech shots whose loudness sits well under the music around them, and holes (near silence)
at the start of speech shots. Momentary loudness (400 ms) comes from ffmpeg ebur128 on the final mix.
Usage: python tools/check_audio.py film.json rendered.mp4
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_film import FPS, frames  # noqa: E402


def momentary(video: str) -> list[tuple[float, float]]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-vn", "-af",
                        "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    return [(float(t), float(m)) for t, m in re.findall(r"pts_time:([\d.]+)\s*\n.*?lavfi\.r128\.M=(-?[\d.]+)", r)]


def main(film_path: str, video: str) -> None:
    clips = json.loads(Path(film_path).read_text(encoding="utf-8"))["clips"]
    spans, t = [], 0.0
    for c in clips:
        d = frames(c) / FPS
        spans.append((c, t, t + d))
        t += d
    m = momentary(video)

    def level(a: float, b: float) -> float | None:
        vals = [v for tt, v in m if a <= tt < b and v > -60]
        return statistics.median(vals) if vals else None

    issues = []
    for i, (c, a, b) in enumerate(spans):
        if c.get("audio") != "keep" or b - a < 1.5:
            continue
        sp = level(a + 0.4, b)
        around = [level(x, y) for cc, x, y in spans[max(0, i - 2):i + 3] if cc.get("audio") != "keep"]
        around = [v for v in around if v is not None]
        mus = max(around) if around else None
        hole = min((v for tt, v in m if a - 0.3 <= tt < a + 0.5), default=0)
        tag = f"{int(a // 60):02d}:{a % 60:04.1f} {c['clip']} {float(c['in']):.1f}-{float(c['out']):.1f}"
        if sp is not None and (sp < -22 or (mus is not None and sp < mus - 3)):
            issues.append(f"QUIET  {tag}: speech {sp:.1f} LUFS, music around {mus if mus is None else round(mus, 1)}")
        if hole < -45 and a > 1.0:  # the film itself starts from silence: not a hole
            issues.append(f"HOLE   {tag}: drops to {hole:.0f} LUFS at the cut")
    print("\n".join(issues) or "no issues")
    print(f"{len(issues)} issues")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
