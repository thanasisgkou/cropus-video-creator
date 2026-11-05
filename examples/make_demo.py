#!/usr/bin/env python3
"""Create a tiny demo project with synthetic media, so the whole pipeline can be tried without any footage.

    python examples/make_demo.py demo-trip
    cd demo-trip
    python ../tools/ingest.py
    ...                                   (the full list is printed at the end, and in README.md)

It writes: demo-trip/project.json, demo-trip/media/phone/*.mp4 + *.jpg (test patterns with timestamps and GPS),
demo-trip/music/demo-tune.mp3 (a synthetic tune) and demo-trip/edl.json (a two-chapter cut of the demo clips).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def video(path: Path, pattern: str, seconds: float, utc: str, tone: int) -> None:
    ff("-f", "lavfi", "-i", f"{pattern}=size=1280x720:rate=30:duration={seconds}",
       "-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={seconds}",
       "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
       "-metadata", f"creation_time={utc}", "-metadata", "location=+00.0000+000.0000/", str(path))


def photo(path: Path, text: str, color: tuple, when: str) -> None:
    im = Image.new("RGB", (1600, 1200), color)
    d = ImageDraw.Draw(im)
    for k in range(0, 1600, 80):
        d.line([(k, 0), (k + 400, 1200)], fill=tuple(min(255, c + 40) for c in color), width=6)
    d.text((80, 80), text, fill="white")
    ex = Image.Exif()
    ex[306] = when  # DateTime (local time of the trip)
    ex.get_ifd(0x8769)[36867] = when  # DateTimeOriginal
    im.save(path, quality=92, exif=ex)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-trip").resolve()
    media = root / "media" / "phone"
    media.mkdir(parents=True, exist_ok=True)
    (root / "music").mkdir(exist_ok=True)
    # three "phone videos" (creation_time is UTC, as phones write it) and two photos (EXIF in local time, UTC+2)
    video(media / "VID_20240501_090000.mp4", "testsrc2", 8, "2024-05-01T07:00:00Z", 330)
    video(media / "VID_20240501_120000.mp4", "smptebars", 6, "2024-05-01T10:00:00Z", 440)
    video(media / "VID_20240502_100000.mp4", "rgbtestsrc", 7, "2024-05-02T08:00:00Z", 550)
    photo(media / "IMG_20240501_093000.jpg", "Photo 1: the old town", (40, 90, 140), "2024:05:01 09:30:00")
    photo(media / "IMG_20240502_110000.jpg", "Photo 2: the beach", (150, 110, 50), "2024:05:02 11:00:00")
    # a short synthetic tune (two chords) as the music bed
    ff("-f", "lavfi", "-i", "sine=frequency=262:duration=40", "-f", "lavfi", "-i", "sine=frequency=330:duration=40",
       "-f", "lavfi", "-i", "sine=frequency=392:duration=40",
       "-filter_complex", "[0][1][2]amix=inputs=3,volume=0.6,afade=t=in:d=1,afade=t=out:st=37:d=3,"
                          "tremolo=f=2:d=0.4[a]", "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "128k",
       str(root / "music" / "demo-tune.mp3"))
    (root / "project.json").write_text(json.dumps({
        "title": "Demo trip",
        "utc_offset_hours": 2,
        "work_dir": "work",
        "sources": [{"dir": "media/phone", "prefix": "P", "camera": "Demo phone"}],
        "places": [["2024-05-01", "Old town"], ["2024-05-02", "Beach"]],
        "whisper": {"model": "small", "languages": ["en"]},
    }, indent=1), encoding="utf-8")
    edl = {
        "chapters": [
            {"name": "D1_OLD_TOWN", "title": {"text": "OLD TOWN", "sub": "Day 1"}, "music": "demo-tune", "music_in": 0,
             "shots": [
                 {"clip": "P_VID_20240501_090000", "in": 0.5, "out": 4.5, "audio": "ambient", "desc": "test pattern walk"},
                 {"clip": "PHOTO:P_IMG_20240501_093000", "in": 0, "out": 3.0, "audio": "mute", "desc": "old town photo",
                  "label": "The old town"},
                 {"clip": "P_VID_20240501_120000", "in": 1.0, "out": 5.0, "audio": "keep", "desc": "a tone we keep"}]},
            {"name": "D2_BEACH", "title": {"text": "BEACH", "sub": "Day 2"}, "music": "continue",
             "shots": [
                 {"clip": "P_VID_20240502_100000", "in": 0.0, "out": 5.0, "audio": "ambient", "desc": "colour bars"},
                 {"clip": "PHOTO:P_IMG_20240502_110000", "in": 0, "out": 3.5, "audio": "mute", "desc": "beach photo"}]},
        ],
    }
    (root / "edl.json").write_text(json.dumps(edl, indent=1), encoding="utf-8")
    tools = Path(__file__).resolve().parent.parent / "tools"
    print(f"Demo project ready: {root}\n\nNext (inside {root.name}/):")
    for cmd in ("ingest.py", "prep_media.py all", "music_summary.py", "build_film.py edl.json film.json",
                "render_film.py film.json --output demo_preview.mp4"):
        print(f"  python {tools / cmd.split()[0]}{cmd[len(cmd.split()[0]):]}")


if __name__ == "__main__":
    main()
