"""Comic / TV graphics for the travel films: bubbles, captions, circles, counters, flashback tags.

Every function draws a full-frame transparent PNG (w x h) that the renderer overlays with a short fade.
Positions are fractions of the frame (x, y from top-left). Emoji are drawn with Segoe UI Emoji.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
import config  # noqa: E402

FONT_BOLD = config.font("bold")
FONT_EMOJI = config.font("emoji")
INK = (20, 20, 20, 255)
PAPER = (255, 255, 255, 245)
YELLOW = (255, 204, 0, 255)


def _font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(FONT_BOLD, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return cp >= 0x1F000 or 0x2190 <= cp <= 0x2BFF or cp in (0x23EA, 0x23E9, 0x2602, 0x2614, 0x2600, 0x2601, 0xFE0F)


def _runs(text: str):
    run, emo = "", None
    for ch in text:
        e = _is_emoji(ch)
        if emo is None or e == emo:
            run += ch
        else:
            yield run, emo
            run = ch
        emo = e
    if run:
        yield run, emo


def text_size(text: str, size: int) -> tuple[int, int]:
    f, fe = _font(size), ImageFont.truetype(FONT_EMOJI, int(size * 0.9))
    d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    w = sum(d.textlength(r, font=fe if e else f) for r, e in _runs(text))
    return int(w), int(size * 1.15)


def draw_text(img: Image.Image, xy, text: str, size: int, fill=INK, stroke=0, stroke_fill=None):
    d = ImageDraw.Draw(img)
    f, fe = _font(size), ImageFont.truetype(FONT_EMOJI, int(size * 0.9))
    x, y = xy
    for r, e in _runs(text):
        if e:
            d.text((x, y + size * 0.08), r, font=fe, embedded_color=True)
            x += d.textlength(r, font=fe)
        else:
            d.text((x, y), r, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
            x += d.textlength(r, font=f)


def _wrap(text: str, size: int, max_w: int) -> list[str]:
    lines = []
    for para in text.split(chr(10)):  # an explicit line break (a speaker change) always starts a new line
        cur = ""
        for w in para.split():
            t = (cur + " " + w).strip()
            if cur and text_size(t, size)[0] > max_w:
                lines.append(cur)
                cur = w
            else:
                cur = t
        if cur:
            lines.append(cur)
    return lines


def _shadowed(img: Image.Image, shape: Image.Image, s: float) -> Image.Image:
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    alpha = shape.split()[3].point(lambda a: int(a * 0.45))
    sh.paste((0, 0, 0, 255), (int(4 * s), int(6 * s)), alpha)
    sh = sh.filter(ImageFilter.GaussianBlur(6 * s))
    img.alpha_composite(sh)
    img.alpha_composite(shape)
    return img


def bubble(w: int, h: int, fx: dict) -> Image.Image:
    s = h / 1080
    size = int(fx.get("size", 46) * s)
    lines = _wrap(fx["text"], size, int(w * 0.32))
    tw = max(text_size(l, size)[0] for l in lines)
    th = int(size * 1.2) * len(lines)
    pad_x, pad_y = int(34 * s), int(24 * s)
    bw, bh = tw + 2 * pad_x, th + 2 * pad_y
    cx, cy = float(fx.get("x", 0.5)) * w, float(fx.get("y", 0.2)) * h
    x0 = int(min(max(cx - bw / 2, 20 * s), w - bw - 20 * s))
    y0 = int(min(max(cy - bh / 2, 20 * s), h - bh - 20 * s))
    shape = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(shape)
    tail = fx.get("tail", "down_left")
    tx = x0 + bw * (0.25 if "left" in tail else 0.75 if "right" in tail else 0.5)
    down = not tail.startswith("up")
    by = y0 + bh if down else y0
    tip = (tx + (-60 if "left" in tail else 60 if "right" in tail else 0) * s, by + (70 if down else -70) * s)
    if fx.get("style") == "thought":
        d.ellipse([x0 - 10 * s, y0 - 6 * s, x0 + bw + 10 * s, y0 + bh + 6 * s], fill=PAPER, outline=INK, width=int(4 * s))
        for k, r in enumerate((16, 11, 7)):
            px = tx + (tip[0] - tx) * (0.35 + 0.3 * k)
            py = by + (tip[1] - by) * (0.35 + 0.3 * k)
            d.ellipse([px - r * s, py - r * s, px + r * s, py + r * s], fill=PAPER, outline=INK, width=int(3 * s))
    else:
        d.polygon([(tx - 22 * s, by), (tx + 22 * s, by), tip], fill=PAPER, outline=INK)
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(28 * s), fill=PAPER, outline=INK, width=int(4 * s))
        d.polygon([(tx - 18 * s, by + (-3 if down else 3) * s), (tx + 18 * s, by + (-3 if down else 3) * s),
                   (tip[0], tip[1] + (-8 if down else 8) * s)], fill=PAPER)
    img = _shadowed(Image.new("RGBA", (w, h), (0, 0, 0, 0)), shape, s)
    for i, l in enumerate(lines):
        lw = text_size(l, size)[0]
        draw_text(img, (x0 + (bw - lw) / 2, y0 + pad_y + i * int(size * 1.2) - size * 0.08), l, size)
    return img


def caption(w: int, h: int, fx: dict) -> Image.Image:
    s = h / 1080
    size = int(fx.get("size", 54) * s)
    text = fx["text"]
    tw, _ = text_size(text, size)
    pad_x, pad_y = int(30 * s), int(16 * s)
    bw, bh = tw + 2 * pad_x, int(size * 1.25) + 2 * pad_y
    x0 = int((w - bw) / 2)
    y0 = int(h * 0.08) if fx.get("pos") == "top" else int(h - bh - h * 0.09)
    shape = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(shape)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(10 * s), fill=YELLOW)
    img = _shadowed(Image.new("RGBA", (w, h), (0, 0, 0, 0)), shape, s)
    draw_text(img, (x0 + pad_x, y0 + pad_y - size * 0.05), text, size)
    return img


def circle(w: int, h: int, fx: dict) -> Image.Image:
    s = h / 1080
    cx, cy = float(fx["x"]) * w, float(fx["y"]) * h
    r = float(fx.get("r", 0.08)) * h
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for k, a in ((10, 90), (7, 255)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 214, 0, a), width=int(k * s))
    if fx.get("text"):
        size = int(46 * s)
        tw, th = text_size(fx["text"], size)
        tx = cx + r + 18 * s if cx + r + tw + 40 * s < w else cx - r - tw - 18 * s
        draw_text(img, (tx, cy - th / 2), fx["text"], size, fill=(255, 255, 255, 255), stroke=int(5 * s),
                  stroke_fill=(0, 0, 0, 255))
    return img


def counter(w: int, h: int, fx: dict) -> Image.Image:
    s = h / 1080
    size = int(fx.get("size", 44) * s)
    text = fx["text"]
    tw, _ = text_size(text, size)
    pad_x, pad_y = int(26 * s), int(14 * s)
    bw, bh = tw + 2 * pad_x, int(size * 1.25) + 2 * pad_y
    corner = fx.get("corner", "top_right")
    x0 = int(w - bw - 50 * s) if "right" in corner else int(50 * s)
    y0 = int(46 * s) if "top" in corner else int(h - bh - 60 * s)
    shape = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(shape)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(bh / 2), fill=(20, 20, 20, 215), outline=YELLOW,
                        width=int(4 * s))
    img = _shadowed(Image.new("RGBA", (w, h), (0, 0, 0, 0)), shape, s)
    draw_text(img, (x0 + pad_x, y0 + pad_y - size * 0.05), text, size, fill=(255, 255, 255, 255))
    return img


def flashback_tag(w: int, h: int, label: str) -> Image.Image:
    s = h / 1080
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    size = int(44 * s)
    text = label if label.startswith(("⏩", "⏪")) else (f"⏪  {label}" if label else "⏪  FLASHBACK")
    tw, _ = text_size(text, size)
    d = ImageDraw.Draw(img)
    x0, y0 = int(60 * s), int(50 * s)
    d.rounded_rectangle([x0, y0, x0 + tw + int(50 * s), y0 + int(size * 1.6)], radius=int(12 * s), fill=(0, 0, 0, 170))
    draw_text(img, (x0 + int(25 * s), y0 + int(size * 0.2)), text, size, fill=(255, 255, 255, 255))
    return img


def info(w: int, h: int, fx: dict) -> Image.Image:
    """Documentary info card, bottom-right: stats line + one wow fact."""
    s = h / 1080
    st_size, f_size = int(40 * s), int(34 * s)
    stats, fact = fx.get("stats", ""), fx.get("fact", "")
    max_w = int(w * 0.40)
    fact_lines = _wrap(fact, f_size, max_w) if fact else []
    tw = max([text_size(stats, st_size)[0]] + [text_size(l, f_size)[0] for l in fact_lines])
    pad = int(26 * s)
    bw = tw + 2 * pad + int(10 * s)
    bh = pad * 2 + int(st_size * 1.25) + (int(10 * s) + int(f_size * 1.25) * len(fact_lines) if fact_lines else 0)
    x0 = int(w - bw - 60 * s)
    y0 = int(60 * s) if fx.get("pos") == "top" else int(h - bh - 70 * s)  # top when subtitles hold the bottom
    shape = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(shape)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(14 * s), fill=(12, 16, 20, 190))
    d.rectangle([x0, y0 + int(12 * s), x0 + int(7 * s), y0 + bh - int(12 * s)], fill=YELLOW)
    img = _shadowed(Image.new("RGBA", (w, h), (0, 0, 0, 0)), shape, s)
    tx = x0 + pad + int(10 * s)
    draw_text(img, (tx, y0 + pad - st_size * 0.08), stats, st_size, fill=(255, 214, 0, 255))
    y = y0 + pad + int(st_size * 1.25) + int(10 * s)
    for l in fact_lines:
        draw_text(img, (tx, y - f_size * 0.08), l, f_size, fill=(245, 245, 245, 255))
        y += int(f_size * 1.25)
    return img


def quadtags(w: int, h: int, fx: dict) -> Image.Image:
    """Small time/name tags in the top-left corner of each quadrant of a 2x2 split screen."""
    s = h / 1080
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    size = int(30 * s)
    for k, text in enumerate(fx.get("tags", [])):
        qx, qy = (k % 2) * w // 2, (k // 2) * h // 2
        tw, th = text_size(text, size)
        x0, y0 = qx + int(18 * s), qy + int(16 * s)
        d.rounded_rectangle([x0, y0, x0 + tw + int(24 * s), y0 + int(size * 1.5)], radius=int(8 * s), fill=(0, 0, 0, 160))
        draw_text(img, (x0 + int(12 * s), y0 + int(size * 0.18)), text, size, fill=(255, 214, 0, 255))
    d.line([(w // 2, 0), (w // 2, h)], fill=(0, 0, 0, 255), width=max(2, int(4 * s)))
    d.line([(0, h // 2), (w, h // 2)], fill=(0, 0, 0, 255), width=max(2, int(4 * s)))
    return img


def doc(w: int, h: int, fx: dict) -> Image.Image:
    """Sober documentary caption, bottom centre: a small yellow kicker (place · year) over one white sentence."""
    s = h / 1080
    k_size, f_size = int(34 * s), int(46 * s)
    lines = _wrap(fx["text"], f_size, int(w * 0.72))[:3]
    lh = int(f_size * 1.3)
    pad = int(30 * s)
    tw = max([text_size(fx.get("kicker", ""), k_size)[0]] + [text_size(l, f_size)[0] for l in lines])
    bw, bh = tw + 2 * pad, pad * 2 + int(k_size * 1.5) + lh * len(lines)
    x0, y0 = int((w - bw) / 2), int(h - bh - 80 * s)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(12 * s), fill=(0, 0, 0, 175))
    draw_text(img, (x0 + pad, y0 + pad - k_size * 0.1), fx.get("kicker", ""), k_size, fill=(255, 214, 0, 255))
    y = y0 + pad + int(k_size * 1.5)
    for l in lines:
        draw_text(img, (x0 + pad, y - f_size * 0.08), l, f_size, fill=(255, 255, 255, 255))
        y += lh
    return img


def tag(w: int, h: int, fx: dict) -> Image.Image:
    """One small time/name tag, top-left (the relay of walks: who and when, per cut)."""
    s = h / 1080
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    size = int(fx.get("size", 34) * s)
    tw, _ = text_size(fx["text"], size)
    x0, y0 = int(40 * s), int(36 * s)
    d.rounded_rectangle([x0, y0, x0 + tw + int(28 * s), y0 + int(size * 1.5)], radius=int(9 * s), fill=(0, 0, 0, 165))
    draw_text(img, (x0 + int(14 * s), y0 + int(size * 0.18)), fx["text"], size, fill=(255, 214, 0, 255))
    return img


def subtitle(w: int, h: int, fx: dict) -> Image.Image:
    """Subtitle: white bold text with a dark outline, bottom centre, max 2 lines."""
    s = h / 1080
    size = int(fx.get("size", 46) * s)
    lines = _wrap(fx["text"], size, int(w * 0.70))[:2]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    lh = int(size * 1.25)
    y = int(h * 0.90) - lh * len(lines)
    for l in lines:
        tw, _ = text_size(l, size)
        draw_text(img, ((w - tw) / 2, y), l, size, fill=(255, 255, 255, 255), stroke=int(5 * s), stroke_fill=(0, 0, 0, 235))
        y += lh
    return img


RENDERERS = {"bubble": bubble, "caption": caption, "circle": circle, "counter": counter, "info": info, "quadtags": quadtags, "subtitle": subtitle, "tag": tag, "doc": doc}


def credits_panel(w: int, h: int, fx: dict) -> Image.Image:
    """End credits on the right 36 % of the frame (the shot itself sits on the left with framing 'left'):
    a small yellow heading, then lines; a line 'A: B' shows A small and grey above B."""
    s = h / 1080
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x0 = int(w * 0.645)
    head, lines = fx.get("heading", ""), fx.get("lines", [])
    h_size, k_size, v_size = int(30 * s), int(26 * s), int(40 * s)
    blocks = []
    for l in lines:
        if ": " in l:
            k, v = l.split(": ", 1)
            blocks.append((k, _wrap(v, v_size, int(w * 0.32))))
        else:
            blocks.append(("", _wrap(l, v_size, int(w * 0.32))))
    total = (int(h_size * 2.2) if head else 0) + sum(
        (int(k_size * 1.35) if k else 0) + int(v_size * 1.2) * len(v) + int(22 * s) for k, v in blocks)
    y = int((h - total) / 2)
    if head:
        up = "".join(ch for ch in unicodedata.normalize("NFD", head.upper()) if not unicodedata.combining(ch))
        draw_text(img, (x0, y), unicodedata.normalize("NFC", up), h_size, fill=YELLOW)  # Greek capitals carry no accents
        y += int(h_size * 2.2)
    for k, v in blocks:
        if k:
            draw_text(img, (x0, y), k, k_size, fill=(190, 190, 190, 255))
            y += int(k_size * 1.35)
        for line in v:
            draw_text(img, (x0, y), line, v_size, fill=(245, 245, 240, 255))
            y += int(v_size * 1.2)
        y += int(22 * s)
    return img


RENDERERS["credits"] = credits_panel


def make_png(path: Path, w: int, h: int, fx: dict) -> None:
    if fx["type"] == "flashback_tag":
        img = flashback_tag(w, h, fx.get("text", ""))
    else:
        img = RENDERERS[fx["type"]](w, h, fx)
    img.save(path)
