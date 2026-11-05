#!/usr/bin/env python3
"""List the film's units (runs of the same clip) with time, length, speech and graphics, for the short-cut editors.

Usage: python tools/short_units.py film.json analysis/short_units.txt
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_film import FPS, frames, load_words, short_units  # noqa: E402


def speech(c: dict) -> str:
    if c.get("audio") != "keep" or c["clip"].startswith(("file:", "PHOTO:")):
        return ""
    ws = load_words(c["clip"]) or []
    a, b = float(c["in"]), float(c["out"])
    return "".join(w["w"] for w in ws if a - 0.05 <= w["s"] < b).strip()


def extras(c: dict) -> list[str]:
    out = []
    if c.get("title"):
        out.append(f"TITLE {c['title'].get('text', '')}")
    if c.get("label"):
        out.append(f"LABEL {c['label'].get('text', '')}")
    for fx in c.get("fx", []):
        kind = fx.get("type", fx.get("kind", "fx"))
        txt = str(fx.get("text") or fx.get("title") or "").replace("\n", " ")
        out.append(f"{kind} {txt}"[:60])
    if c.get("cutaways"):
        out.append(f"{len(c['cutaways'])} cutaways")
    if c.get("style"):
        out.append(c["style"])
    return out


def main(film_path: str, out_path: str) -> None:
    clips = json.loads(Path(film_path).read_text(encoding="utf-8"))["clips"]
    starts, t = [], 0.0
    for c in clips:
        starts.append(t)
        t += frames(c) / FPS
    lines = [f"{len(clips)} shots, {t / 60:.1f} min. One line per unit: KEY | start | length | chapter | audio | graphics | desc | speech", ""]
    for key, idx in short_units(clips):
        first = clips[idx[0]]
        dur = sum(frames(clips[i]) / FPS for i in idx)
        s = starts[idx[0]]
        audio = "/".join(sorted({clips[i].get("audio", "ambient") for i in idx}))
        gfx = "; ".join(x for i in idx for x in extras(clips[i]))
        text = " ".join(x for x in (speech(clips[i]) for i in idx) if x)
        lines.append(f"{key} | {int(s // 60):02d}:{s % 60:04.1f} | {dur:5.1f}s | {first['chapter']} | {audio} | {gfx} | "
                     f"{first.get('desc', '')[:110]} | «{text}»")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(lines) - 2} units -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
