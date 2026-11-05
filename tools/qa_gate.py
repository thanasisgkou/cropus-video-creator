#!/usr/bin/env python3
"""QA gate: every check that has caught a real problem in this film, in one run. Nothing ships unless it passes.

  python tools/qa_gate.py film.json              # before rendering
  python tools/qa_gate.py film.json out.mp4      # after rendering (adds sync, speech level and black-frame checks)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from config import PROJECT  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_film import FPS, frames  # noqa: E402


def run_tool(*args: str) -> str:
    tool = str(Path(__file__).resolve().parent / Path(args[0]).name)
    r = subprocess.run([sys.executable, tool, *args[1:]], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=PROJECT, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    return r.stdout + r.stderr


def main() -> None:
    film_path = sys.argv[1]
    video = sys.argv[2] if len(sys.argv) > 2 else None
    film = json.loads(Path(film_path).read_text(encoding="utf-8"))
    clips, fails, notes = film["clips"], [], []

    # 1. music sits on its chapter (catches music shifted against the picture)
    t, first, last = 0.0, {}, {}
    for c in clips:
        first.setdefault(c["chapter"], t)
        t += frames(c) / FPS
        last[c["chapter"]] = t
    total = t
    for ch in first:
        cues = [m for m in film["music"] if m["chapter"] == ch]
        if cues and not cues[0].get("early") and abs(cues[0]["start"] - float(cues[0].get("start_offset", 0)) - first[ch]) > 2.0:
            fails.append(f"music for {ch} starts at {cues[0]['start']:.1f}s, chapter starts at {first[ch]:.1f}s")
    covered = sorted((m["start"], m["end"]) for m in film["music"])
    gap_from = 0.0
    for a, b in covered:
        if a - gap_from > 20:
            notes.append(f"no music {gap_from:.0f}-{a:.0f}s (check it is intended)")
        gap_from = max(gap_from, b)
    quiet = film.get("no_music", [])
    if any(q[0] <= gap_from + 1 and q[1] >= total - 1 for q in quiet):
        gap_from = total  # the end is silent on purpose (credits over the bloopers' own sound)
    if total - gap_from > 20:
        fails.append(f"no music from {gap_from:.0f}s to the end ({total:.0f}s)")

    # 2. nothing the editors planned was silently dropped by a pass
    logs = {p.name: p.read_text(encoding="utf-8") for p in (PROJECT / "analysis").glob("*_log.txt")}
    skipped = [l for l in logs.get("rhythm_log.txt", "").splitlines() if "skipped" in l]
    if skipped:
        fails.append(f"{len(skipped)} rhythm items skipped, e.g. {skipped[0]}")

    # 3. a memory tag always sits on its graded cutaway
    for c in clips:
        starts = [float(cw["start"]) for cw in c.get("cutaways", []) if cw.get("style") == "flashback"]
        for x in c.get("fx", []):
            if x.get("memory") and not any(abs(float(x["start"]) - s) < 0.05 for s in starts):
                fails.append(f"memory tag without its cutaway on {c['clip']} at {x['start']}")

    # 3b. one subtitle at a time, and nothing else in the bottom third while it is on screen
    for c in clips:
        iv = lambda x: (float(x.get("start", 0)), float(x.get("start", 0)) + float(x.get("dur", 2)))
        subs = sorted(iv(x) for x in c.get("fx", []) if x.get("type") == "subtitle")
        if any(x < b - 0.05 for (a, b), (x, y) in zip(subs, subs[1:])):
            fails.append(f"two subtitles at once on {c['clip']} {c['in']}")
        low = [iv(x) for x in c.get("fx", []) if x.get("type") in ("info", "caption") and x.get("pos") != "top"]
        if c.get("label") and c["label"].get("pos") != "top":
            low.append(iv(c["label"]))
        if c.get("title"):
            tt = (float(c["title"].get("start", 0.5)), float(c["title"].get("start", 0.5)) + float(c["title"].get("dur", 3.6)))
            if any(a < tt[1] and tt[0] < b for a, b in subs):
                fails.append(f"subtitle over the chapter title on {c['clip']} {c['in']}")
        if any(a < y and x < b for a, b in subs for x, y in low):
            fails.append(f"subtitle under a label/card on {c['clip']} {c['in']}")

    # 4. sentences and must-have moments
    # accepted flags: whisper put no full stop, but the sentence does end there (checked by ear / by a reviewer)
    accepted = ()
    out = run_tool("tools/check_words.py")
    flagged = [l.strip() for l in out.splitlines() if l.startswith("      ") and not any(a in l for a in accepted)]
    if flagged:
        fails.append(f"check_words: {len(flagged)} new flags, e.g. {flagged[0]}")
    out = run_tool("tools/check_must_have.py")
    if "ALL PRESENT" not in out:
        fails.append("must-have: " + out.strip().splitlines()[-1])

    if video:
        # 0. the sound runs the whole film (catches a soundtrack that ends before the picture)
        durs = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", video],
                              capture_output=True, text=True).stdout.split()
        dd = {x.split(",")[0]: float(x.split(",")[1]) for x in durs if "," in x and x.split(",")[1] not in ("", "N/A")}
        if dd.get("audio", 0) < dd.get("video", 0) - 0.5:
            fails.append(f"audio track ends at {dd.get('audio', 0):.1f}s but the picture runs {dd.get('video', 0):.1f}s")
        # 0b. music really plays: sample the middle of every music-only stretch of >= 4 s (no talk, inside a music cue);
        #     a render once came out with whole chapters of digital silence while every other check passed
        t, spans = 0.0, []
        for c in clips:
            d = frames(c) / FPS
            spans.append((c, t, t + d)); t += d
        cues = [(float(m["start"]), float(m["end"])) for m in film.get("music", [])]
        vo = [(float(v["start"]) - 1, float(v["start"]) + float(v["dur"]) + 1) for v in film.get("voiceover", [])]
        probes = []
        for c, a_, b_ in spans:
            mid = (a_ + b_) / 2
            if (c.get("audio") != "keep" and b_ - a_ >= 4 and any(s0 + 3 < mid < e0 - 3 for s0, e0 in cues)
                    and not any(s0 < mid < e0 for s0, e0 in vo)):
                probes.append(mid)
        probes = probes[::max(1, len(probes) // 40)]
        if probes:
            af = ",".join(f"atrim=start={p_ - 0.5:.2f}:duration=1" for p_ in probes[:1])
            silent = []
            for p_ in probes:
                e = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-vn", "-af",
                                    f"atrim=start={p_ - 0.5:.2f}:duration=1,volumedetect", "-f", "null", "-"],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
                mv = re.findall(r"mean_volume: (-?[\d.]+) dB", e)
                if not mv or float(mv[-1]) < -60:
                    silent.append(round(p_))
            if silent:
                fails.append(f"no music where it should play at {len(silent)} of {len(probes)} probes, e.g. {silent[:5]} s")
            else:
                notes.append(f"music present at all {len(probes)} music-only probes")
        # 5. lip sync: every segment has exactly its planned frames
        out = run_tool("tools/check_sync.py", film_path)
        last_line = out.strip().splitlines()[-1]
        s = re.search(r"(\d+) not rendered, total picture drift (-?\d+) frames", last_line)
        if not s or s[1] != "0" or s[2] != "0":
            fails.append("sync: " + last_line)
        # 6. speech audible against the music, no holes at cuts
        out = run_tool("tools/check_audio.py", film_path, video)
        quiet = [l for l in out.splitlines() if l.startswith(("QUIET", "HOLE"))]
        (PROJECT / "analysis" / "qa_audio.txt").write_text(out, encoding="utf-8")
        if len(quiet) > 10:
            fails.append(f"audio: {len(quiet)} speech shots quiet or with holes (analysis/qa_audio.txt)")
        elif quiet:
            notes.append(f"audio: {len(quiet)} borderline speech shots (analysis/qa_audio.txt)")
        # 7. loudness, peaks, black frames
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-af", "ebur128=peak=true", "-vf",
                            "scale=320:-1,blackdetect=d=0.5:pix_th=0.05", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        i = re.findall(r"I:\s+(-?[\d.]+) LUFS", r)
        pk = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r)
        black = re.findall(r"black_start:([\d.]+)", r)
        notes.append(f"loudness {i[-1] if i else '?'} LUFS, true peak {pk[-1] if pk else '?'} dBFS")
        if i and abs(float(i[-1]) + 14) > 1.0:
            fails.append(f"loudness {i[-1]} LUFS (target -14)")
        if pk and float(pk[-1]) > -1.0:
            fails.append(f"true peak {pk[-1]} dBFS")
        if black:
            fails.append(f"black frames at {', '.join(black[:5])}s")

    print("\n".join(f"  note: {n}" for n in notes))
    print("\n".join(f"  FAIL: {f}" for f in fails) or "  all checks passed")
    print("QA GATE: " + ("FAILED" if fails else "PASSED"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
