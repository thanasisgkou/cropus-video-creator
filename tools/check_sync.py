#!/usr/bin/env python3
"""Lip-sync check: every rendered segment must hold exactly the frames and audio samples the timeline expects.

A segment with fewer video frames than planned shifts all later picture against the sample-exact audio.
Usage: python tools/check_sync.py film.json [--master]
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_film import Film  # noqa: E402


def video_frames(p: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=nb_read_packets", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout
    return int(out.strip().split(",")[0] or 0)


def main() -> None:
    film = Film(Path(sys.argv[1]), master="--master" in sys.argv)
    drift, adrift, bad, missing = 0, 0, 0, 0
    for i, c in enumerate(film.clips):
        key = film.seg_key(c)
        v, a = film.seg_dir / f"{key}.mp4", film.seg_dir / f"{key}.wav"
        if not v.exists():
            missing += 1
            continue
        n = film.frames(c)
        got = video_frames(v)
        with wave.open(str(a), "rb") as w:
            samples = w.getnframes()
        want_samples = round(n * film.fps_den / film.fps_num * 48000)
        if got != n or abs(samples - want_samples) > 48:
            bad += 1
            drift += (got - n)
            adrift += samples - want_samples
            print(f"#{i:03d} {c['id']} {c['clip']} {float(c['in']):.2f}-{float(c['out']):.2f}: video {got}/{n} frames, "
                  f"audio {samples}/{want_samples} samples, running drift {drift} frames")
    print(f"{len(film.clips)} segments, {bad} off, {missing} not rendered, total picture drift {drift} frames "
          f"({drift * film.fps_den / film.fps_num:+.2f} s), audio drift {adrift / 48000:+.3f} s")


if __name__ == "__main__":
    main()
