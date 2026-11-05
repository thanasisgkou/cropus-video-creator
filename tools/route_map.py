#!/usr/bin/env python3
"""Animated route maps (1920x1080): the opening flight + itinerary, and the travel legs.

Usage: python tools/route_map.py <route.json> <out.mp4>

route.json:
{"duration": 14.0, "title": "PORTUGAL", "subtitle": "June 2025",
 "keys": [[0, 18, 112, -6, 46], [5.5, 18, 112, -6, 46], [8.5, 99.0, 104.6, 0.9, 7.2]],   # [t, lon0, lon1, lat0, lat1]
 "stops": [{"name": "Home", "lat": 50.11, "lon": 8.68, "side": "left"}, ...],
 "legs": [{"to": 1, "t0": 1.0, "t1": 3.0, "mode": "flight"}, ...],   # leg k goes from stop to-1 to stop `to`
 "done": 0,                                                         # legs before this index are drawn dimmed from t=0
 "region": {"fill": [[lon, lat], ...],                             # optional: the destination drawn lighter,
            "borders": [[[lon, lat], [lon, lat]], ...],            #   dashed border lines,
            "names": [["COLORADO", -105.55, 39.0]], "highlight": "COLORADO"}}   # and region labels

Land: Natural Earth 1:50m land polygons (public domain; path from project.json "land_geojson", default
assets/maps/ne_50m_land.geojson). Route lines show the order of travel, not GPS tracks.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
LAND = config.LAND_GEOJSON
W, H, FPS_NUM, FPS_DEN = 1920, 1080, 30000, 1001
FPS = FPS_NUM / FPS_DEN
SS = 2  # supersampling for smooth coastlines
FONT = config.font("bold")
SEA_TOP, SEA_BOT = (9, 34, 48), (4, 18, 28)
LAND_FILL, LAND_EDGE = (38, 74, 66), (120, 170, 150)
YELLOW, WHITE = (255, 196, 0), (245, 245, 240)
STATE_FILL = (58, 100, 84)


def caps(text: str) -> str:
    out = []
    for ch in unicodedata.normalize("NFD", text.upper()):
        if unicodedata.combining(ch) and out and "Ͱ" <= out[-1] <= "Ͽ":
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def ease(v: float) -> float:
    v = max(0.0, min(1.0, v))
    return v * v * (3 - 2 * v)


def load_land() -> list[np.ndarray]:
    gj = json.loads(LAND.read_text(encoding="utf-8"))
    rings = []
    for f in gj["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            ring = np.array(poly[0], dtype=np.float64)
            if len(ring) > 3:
                rings.append(ring)
    return rings


class View:
    """Equirectangular view with cos(lat) correction, fitted into the frame."""

    def __init__(self, lon0, lon1, lat0, lat1):
        self.lon0, self.lon1, self.lat0, self.lat1 = lon0, lon1, lat0, lat1
        self.k = math.cos(math.radians((lat0 + lat1) / 2))
        sx = W / ((lon1 - lon0) * self.k)
        sy = H / (lat1 - lat0)
        self.s = min(sx, sy)  # the whole extent stays visible
        self.cx, self.cy = (lon0 + lon1) / 2, (lat0 + lat1) / 2

    def xy(self, lon, lat):
        return (W / 2 + (np.asarray(lon) - self.cx) * self.k * self.s, H / 2 - (np.asarray(lat) - self.cy) * self.s)

    def bbox(self):
        hw, hh = W / 2 / (self.k * self.s), H / 2 / self.s
        return self.cx - hw, self.cx + hw, self.cy - hh, self.cy + hh


def view_at(keys: list, t: float) -> View:
    if t <= keys[0][0]:
        return View(*keys[0][1:])
    for a, b in zip(keys, keys[1:]):
        if t <= b[0]:
            u = ease((t - a[0]) / max(1e-6, b[0] - a[0]))
            # zoom in log space so the move feels even
            wa, wb = a[2] - a[1], b[2] - b[1]
            w = math.exp(math.log(wa) * (1 - u) + math.log(wb) * u)
            ha, hb = a[4] - a[3], b[4] - b[3]
            h = math.exp(math.log(ha) * (1 - u) + math.log(hb) * u)
            v = 0.0 if wa == wb else (w - wa) / (wb - wa)
            cxa, cxb = (a[1] + a[2]) / 2, (b[1] + b[2]) / 2
            cya, cyb = (a[3] + a[4]) / 2, (b[3] + b[4]) / 2
            cx, cy = cxa + (cxb - cxa) * (v if wa != wb else u), cya + (cyb - cya) * (v if wa != wb else u)
            return View(cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2)
    return View(*keys[-1][1:])


def arc(p0, p1, n=60, bend=0.16):
    (x0, y0), (x1, y1) = p0, p1
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    cx, cy = mx - dy * bend, my + dx * bend
    t = np.linspace(0, 1, n)
    return list(zip((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1))


def plane(d: ImageDraw.ImageDraw, x, y, ang, s, fill):
    shape = [(1.0, 0), (0.15, 0.12), (-0.05, 0.75), (-0.25, 0.75), (-0.1, 0.12), (-0.6, 0.1), (-0.75, 0.35), (-0.88, 0.35),
             (-0.8, 0), (-0.88, -0.35), (-0.75, -0.35), (-0.6, -0.1), (-0.1, -0.12), (-0.25, -0.75), (-0.05, -0.75), (0.15, -0.12)]
    ca, sa = math.cos(ang), math.sin(ang)
    d.polygon([(x + s * (px * ca - py * sa), y + s * (px * sa + py * ca)) for px, py in shape], fill=fill)


def render(cfg: dict, out_path: str) -> None:
    dur = float(cfg.get("duration", 5.0))
    keys = cfg["keys"]
    stops = cfg["stops"]
    legs = cfg.get("legs", [])
    done = int(cfg.get("done", 0))
    rings = load_land()
    f_title, f_sub, f_stop = font(160), font(50, "SemiBold"), font(34, "SemiBold")
    f_card, f_card_sub = font(96), font(40, "SemiBold")
    sea = Image.new("RGB", (W * SS, H * SS))
    grad = np.linspace(0, 1, H * SS)[:, None, None]
    sea = Image.fromarray((np.array(SEA_TOP) * (1 - grad) + np.array(SEA_BOT) * grad).astype(np.uint8).repeat(W * SS, axis=1))
    n_frames = round(dur * FPS)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", f"{FPS_NUM}/{FPS_DEN}", "-i", "-", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                             "-shortest", "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
                             "-c:a", "aac", out_path], stdin=subprocess.PIPE)
    last_view_key, land_cache = None, None
    for k in range(n_frames):
        t = k / FPS
        v = view_at(keys, t)
        vk = (round(v.cx, 4), round(v.cy, 4), round(v.s, 3))
        if vk != last_view_key:
            big = sea.copy()
            bd = ImageDraw.Draw(big)
            lo0, lo1, la0, la1 = v.bbox()
            # graticule every 5 degrees (10 when zoomed out)
            step = 5 if lo1 - lo0 < 40 else 10
            for g in range(int(math.floor(lo0 / step)) * step, int(lo1) + step, step):
                x, _ = v.xy(g, 0)
                bd.line([(x * SS, 0), (x * SS, H * SS)], fill=(30, 62, 78), width=SS)
            for g in range(int(math.floor(la0 / step)) * step, int(la1) + step, step):
                _, y = v.xy(0, g)
                bd.line([(0, y * SS), (W * SS, y * SS)], fill=(30, 62, 78), width=SS)
            for ring in rings:
                if ring[:, 0].max() < lo0 or ring[:, 0].min() > lo1 or ring[:, 1].max() < la0 or ring[:, 1].min() > la1:
                    continue
                xs, ys = v.xy(ring[:, 0], ring[:, 1])
                pts = list(zip((xs * SS).tolist(), (ys * SS).tolist()))
                bd.polygon(pts, fill=LAND_FILL)
                bd.line(pts + [pts[0]], fill=LAND_EDGE, width=2 * SS)
            region = cfg.get("region") or {}
            if region and lo1 - lo0 < 60:  # the destination region lighter, its borders dashed
                if region.get("fill"):
                    cx_, cy_ = v.xy([p[0] for p in region["fill"]], [p[1] for p in region["fill"]])
                    bd.polygon(list(zip((cx_ * SS).tolist(), (cy_ * SS).tolist())), fill=STATE_FILL)
                for line in region.get("borders", []):
                    bx, by = v.xy([p[0] for p in line], [p[1] for p in line])
                    a, b = (bx[0] * SS, by[0] * SS), (bx[1] * SS, by[1] * SS)
                    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (18 * SS)))
                    seg = np.linspace(0, 1, 2 * n)
                    for u0, u1 in zip(seg[::2], seg[1::2]):
                        bd.line([(a[0] + (b[0] - a[0]) * u0, a[1] + (b[1] - a[1]) * u0),
                                 (a[0] + (b[0] - a[0]) * u1, a[1] + (b[1] - a[1]) * u1)], fill=(150, 190, 175), width=2 * SS)
                if lo1 - lo0 < 30 and cfg.get("state_names", True):
                    fn = font(30 * SS if lo1 - lo0 > 12 else 44 * SS, "SemiBold")
                    for nm, lon_, lat_, *_ in region.get("names", []):
                        x_, y_ = v.xy(lon_, lat_)
                        tw_ = bd.textlength(nm, font=fn)
                        bd.text((x_ * SS - tw_ / 2, y_ * SS), nm, font=fn,
                                fill=(200, 225, 210) if nm == region.get("highlight") else (110, 150, 135))
            land_cache = big.resize((W, H), Image.LANCZOS).convert("RGBA")
            last_view_key = vk
        frame = land_cache.copy()
        layer = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        pts = [tuple(float(c) for c in v.xy(s_["lon"], s_["lat"])) for s_ in stops]
        reached = {0} if (legs and t >= float(legs[0]["t0"]) - 0.6) or not legs else set()
        head = None
        for li, lg in enumerate(legs):
            a, b = pts[lg["to"] - 1], pts[lg["to"]]
            path = arc(a, b, bend=float(lg.get("bend", 0.16 if lg.get("mode") == "flight" else 0.08)))
            if li < done:
                d.line([(x * SS, y * SS) for x, y in path], fill=(170, 135, 45, 255), width=5 * SS, joint="curve")
                reached |= {lg["to"] - 1, lg["to"]}
                continue
            p = ease((t - float(lg["t0"])) / (float(lg["t1"]) - float(lg["t0"])))
            fa = 1.0 if not lg.get("fade") else 1 - ease((t - lg["fade"][0]) / (lg["fade"][1] - lg["fade"][0]))
            if p >= 1:
                reached |= {lg["to"] - 1, lg["to"]}
            if p <= 0 or fa <= 0:
                continue
            col = YELLOW + (int(255 * fa),)
            seg = path[: max(2, int(round(p * (len(path) - 1))) + 1)]
            if lg.get("mode") == "flight":  # dashed flight path
                for j in range(0, len(seg) - 1, 2):
                    d.line([(seg[j][0] * SS, seg[j][1] * SS), (seg[j + 1][0] * SS, seg[j + 1][1] * SS)], fill=col, width=5 * SS)
            else:
                d.line([(x * SS, y * SS) for x, y in seg], fill=col, width=7 * SS, joint="curve")
            reached.add(lg["to"] - 1)
            if p >= 1:
                reached.add(lg["to"])
            elif len(seg) >= 2:
                head = (seg[-1], math.atan2(seg[-1][1] - seg[-2][1], seg[-1][0] - seg[-2][0]), lg.get("mode"))
        for i, s_ in enumerate(stops):
            if i not in reached or s_.get("hidden"):
                continue
            sf = 1.0 if not s_.get("fade") else 1 - ease((t - s_["fade"][0]) / (s_["fade"][1] - s_["fade"][0]))
            if sf <= 0:
                continue
            x, y = pts[i]
            if not (-50 < x < W + 50 and -50 < y < H + 50):
                continue
            arrive = next((float(lg["t1"]) for lg in legs if lg["to"] == i), 0.0)
            age = t - arrive if i else 9.0
            r = (10 + 8 * math.exp(-max(0.0, age) * 4)) * SS
            d.ellipse([x * SS - r, y * SS - r, x * SS + r, y * SS + r], fill=WHITE + (int(255 * sf),), outline=YELLOW + (int(255 * sf),),
                      width=4 * SS)
            name = caps(s_["name"])
            a_ = int(255 * ease((age + 0.2) * 3) * sf)
            fs = font(int(s_.get("size", 34)) * SS, "SemiBold")
            tw = d.textlength(name, font=fs)
            side = s_.get("side", "right")
            tx = x * SS + 24 * SS if side == "right" else x * SS - 24 * SS - tw
            ty = y * SS - 22 * SS + float(s_.get("dy", 0)) * SS
            d.text((tx + 3 * SS, ty + 3 * SS), name, font=fs, fill=(0, 0, 0, a_ // 2))
            d.text((tx, ty), name, font=fs, fill=WHITE + (a_,))
        if head:
            (hx, hy), ang, mode = head
            if mode == "flight":
                plane(d, hx * SS, hy * SS, ang, 26 * SS, WHITE + (255,))
            else:
                d.ellipse([hx * SS - 9 * SS, hy * SS - 9 * SS, hx * SS + 9 * SS, hy * SS + 9 * SS], fill=YELLOW + (255,))
        frame.alpha_composite(layer.resize((W, H), Image.LANCZOS))
        # title block (left), or a leg card (top-left)
        if cfg.get("title") or cfg.get("card"):
            t_in, t_out = float(cfg.get("title_in", 0.3)), float(cfg.get("title_out", dur - 0.4))
            ta = int(255 * ease((t - t_in) / 0.8) * (1 - ease((t - t_out) / 0.6)))
            if ta > 0:
                tl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                dd = ImageDraw.Draw(tl)
                if cfg.get("title"):
                    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    ImageDraw.Draw(shade).rectangle([0, 300, 900, 720], fill=(0, 0, 0, int(110 * ta / 255)))
                    tl.alpha_composite(shade.filter(ImageFilter.GaussianBlur(80)))
                    dd.text((120, 380), caps(cfg["title"]), font=f_title, fill=WHITE + (ta,))
                    dd.rectangle([124, 570, 124 + 150, 577], fill=YELLOW + (ta,))
                    dd.text((124, 600), cfg.get("subtitle", ""), font=f_sub, fill=WHITE + (int(ta * 0.9),))
                else:
                    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    ImageDraw.Draw(shade).rectangle([0, 780, 1100, 1040], fill=(0, 0, 0, int(120 * ta / 255)))
                    tl.alpha_composite(shade.filter(ImageFilter.GaussianBlur(60)))
                    dd.text((96, 820), caps(cfg["card"]), font=f_card, fill=WHITE + (ta,))
                    dd.rectangle([100, 940, 100 + 120, 946], fill=YELLOW + (ta,))
                    if cfg.get("card_sub"):
                        dd.text((240, 922), caps(cfg["card_sub"]), font=f_card_sub, fill=WHITE + (int(ta * 0.92),))
                frame.alpha_composite(tl)
        fade_in, fade_out = float(cfg.get("fade_in", 0.5)), float(cfg.get("fade_out", 0.5))
        fade = min(1.0, t / fade_in if fade_in else 1.0, (dur - t) / fade_out if fade_out else 1.0)
        if fade < 1:
            frame = Image.blend(Image.new("RGBA", (W, H), (0, 0, 0, 255)), frame, max(0.0, fade))
        proc.stdin.write(frame.convert("RGB").tobytes())
    proc.stdin.close()
    proc.wait()
    print("wrote", out_path, n_frames, "frames")


if __name__ == "__main__":
    render(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), sys.argv[2])
