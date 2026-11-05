"""Text card as a still (1920x1080 JPG) usable as PHOTO:CARD_<name> in the EDL.
Usage: python tools/make_card.py <name> "line 1" ["line 2" ...] [--small "smaller line"]
Writes <work_dir>/jpg/CARD_<name>.jpg: near-black background, centred lines in the title font, a short yellow rule.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import config  # noqa: E402

W, H = 1920, 1080
FONT = config.font("bold")


def font(size, weight="SemiBold"):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def main():
    name, args = sys.argv[1], sys.argv[2:]
    big, small = [], []
    i = 0
    while i < len(args):
        if args[i] == "--small":
            small.append(args[i + 1]); i += 2
        else:
            big.append(args[i]); i += 1
    img = Image.new("RGB", (W, H), (10, 11, 13))
    d = ImageDraw.Draw(img)
    fb, fs = font(64), font(38, "Regular")
    lines = [(t, fb) for t in big] + [(t, fs) for t in small]
    heights = [int(f.size * 1.45) for _, f in lines]
    y = (H - sum(heights) - 40) // 2
    for (t, f), hh in zip(lines, heights):
        if f is fs and (t, f) == lines[len(big)]:
            d.rectangle([W // 2 - 60, y + 6, W // 2 + 60, y + 11], fill=(255, 196, 0))
            y += 40
        tw = d.textlength(t, font=f)
        d.text(((W - tw) / 2, y), t, font=f, fill=(242, 240, 232) if f is fb else (200, 200, 195))
        y += hh
    out = (config.WORK / "jpg") / f"CARD_{name}.jpg"
    img.save(out, quality=94)
    print("wrote", out)


if __name__ == "__main__":
    main()
