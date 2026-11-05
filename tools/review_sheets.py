"""Review sheets of a rendered preview: per chapter, two frames of every shot (at 30 % and 75 %), labelled
with shot id, film time, clip and audio tag. -> analysis/review/<version>/<NN>_<chapter>.jpg
Usage: python tools/review_sheets.py film_v1.json previews/preview_v1.mp4 v1
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
film, video, ver = json.load(open(sys.argv[1], encoding="utf-8")), sys.argv[2], sys.argv[3]
OUT = ROOT / "analysis" / "review" / ver
OUT.mkdir(parents=True, exist_ok=True)
FPS = film["format"]["fps_num"] / film["format"]["fps_den"]
font = ImageFont.truetype(config.font("label"), 15)
TW, TH = 320, 180


def grab(t: float) -> Image.Image:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                          "-vf", f"scale={TW}:{TH}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return Image.frombytes("RGB", (TW, TH), raw) if len(raw) == TW * TH * 3 else Image.new("RGB", (TW, TH), "gray")


t, chapters = 0.0, {}
for c in film["clips"]:
    d = round((float(c["out"]) - float(c["in"])) / float(c.get("speed", 1)) * FPS) / FPS
    chapters.setdefault(c["chapter"], []).append((c, t, d))
    t += d
for n, (ch, shots) in enumerate(chapters.items()):
    cols = 6  # 3 shots per row, two frames each
    rows = (len(shots) + 2) // 3
    page = Image.new("RGB", (cols * (TW + 2), rows * (TH + 2)), "black")
    dr = ImageDraw.Draw(page)
    for k, (c, t0, d) in enumerate(shots):
        for j, frac in enumerate((0.3, 0.75)):
            x, y = ((k % 3) * 2 + j) * (TW + 2), (k // 3) * (TH + 2)
            page.paste(grab(t0 + d * frac), (x, y))
            if j == 0:
                mm = f"{int(t0 // 60):02d}:{t0 % 60:04.1f}"
                tag = {"keep": "TALK", "ambient": "amb", "mute": ""}.get(c.get("audio"), "")
                label = f"{c['id']} {mm} {d:.1f}s {tag}"
                label2 = c["clip"].replace("PHOTO:", "P:")[:30]
                for yy, txt in ((y + 3, label), (y + 21, label2)):
                    dr.rectangle([x + 2, yy - 1, x + 4 + dr.textlength(txt, font=font), yy + 16], fill=(0, 0, 0))
                    dr.text((x + 3, yy), txt, fill="yellow", font=font)
    page.save(OUT / f"{n:02d}_{ch}.jpg", quality=82)
    print(ch, len(shots), "shots", flush=True)
