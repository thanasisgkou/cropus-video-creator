#!/usr/bin/env python3
"""Segment-based renderer for horizontal 16:9 films.

Every timeline clip is encoded on its own (NVENC, cached by content hash), then
all segments are concatenated losslessly and the soundtrack is mixed in one pass:

    film.json -> segments/<hash>.mp4 + <hash>.wav -> video.mp4 + natural.wav
              -> music bed (per-chapter songs, crossfades, smooth ducking) -> final mp4

Preview mode reads the 480p proxies and renders 960x540; master mode reads the
original files (paths from analysis/catalog.csv) and renders 1920x1080. Stills (PHOTO:<id>) are static.

film.json (abridged):
{
  "format": {"fps_num": 24000, "fps_den": 1001},
  "proxy_dir": str(config.PROXY), "jpg_dir": str(config.JPG),
  "grade": "eq=contrast=1.05:saturation=1.12",
  "clips": [
    {"id": "c001", "clip": "GX010123", "in": 12.0, "out": 16.5,
     "audio": "keep" | "mute" | "ambient", "audio_gain": 1.0,
     "fade_in": 0.0, "fade_out": 0.0, "speed": 1.0,
     "title": {"text": "OLD TOWN", "sub": "Day 1", "start": 0.4, "dur": 3.6},
     "label": {"text": "Street food", "start": 0.5, "dur": 3.0}}
  ],
  "music": [{"file": "music/x.mp3", "src_in": 0, "start": 0, "end": 95,
             "fade_in": 1.0, "fade_out": 2.0, "gain": 0.8}],
  "duck": {"level": 0.22, "ramp": 0.35, "pad": 0.15},
  "audio": {"target_lufs": -14, "true_peak": -1.0, "ambient_gain": 0.18}
}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import math
import subprocess
import sys
import unicodedata
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fx as fxlib  # noqa: E402

HERE = Path(__file__).resolve().parent
from config import PROJECT  # noqa: E402
import config  # noqa: E402
FONT_BOLD = config.font("bold")
FONT_TEXT = config.font("text")
RENDERER_VERSION = "7"


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(cmd)[:600]}\n{r.stderr[-2000:]}")


# ---------------------------------------------------------------- overlays --

def _font(path: str, size: int, variation: str | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    if variation:
        try:
            f.set_variation_by_name(variation)
        except Exception:
            pass
    return f


def caps(text: str) -> str:
    """Uppercase; Greek capitals lose their tonos/dialytika, Spanish accents stay."""
    out = []
    for ch in unicodedata.normalize("NFD", text.upper()):
        if unicodedata.combining(ch) and out and "Ͱ" <= out[-1] <= "Ͽ":
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def _spaced(draw: ImageDraw.ImageDraw, xy, text, font, fill, spacing):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + spacing
    return x


def _spaced_width(draw, text, font, spacing):
    return sum(draw.textlength(ch, font=font) for ch in text) + spacing * max(0, len(text) - 1)


def make_title_png(path: Path, text: str, sub: str, w: int, h: int) -> None:
    """Chapter title: big spaced caps lower-left, thin accent line, subtitle."""
    s = h / 1080
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # soft vignette behind text for legibility
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    sd.rectangle([0, int(h * 0.62), int(w * 0.75), h], fill=(0, 0, 0, 120))
    shade = shade.filter(ImageFilter.GaussianBlur(int(120 * s)))
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    big = _font(FONT_BOLD, int(104 * s), "Bold")
    small = _font(FONT_BOLD, int(36 * s), "SemiBold")
    x0, y0 = int(96 * s), int(h - 300 * s)
    spacing = int(10 * s)
    text = caps(text)
    tw = _spaced_width(d, text, big, spacing)
    if tw > w * 0.82:  # shrink long names
        big = _font(FONT_BOLD, int(104 * s * w * 0.82 / tw), "Bold")
    # shadow
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sdd = ImageDraw.Draw(shadow)
    _spaced(sdd, (x0 + 3 * s, y0 + 4 * s), text, big, (0, 0, 0, 170), spacing)
    shadow = shadow.filter(ImageFilter.GaussianBlur(5 * s))
    img.alpha_composite(shadow)
    _spaced(d, (x0, y0), text, big, (255, 255, 255, 255), spacing)
    ly = y0 + int(132 * s)
    d.rectangle([x0, ly, x0 + int(120 * s), ly + max(2, int(5 * s))], fill=(255, 196, 0, 255))
    if sub:
        _spaced(d, (x0 + int(140 * s), ly - int(20 * s)), caps(sub), small, (255, 255, 255, 235), int(4 * s))
    img.save(path)


def make_label_png(path: Path, text: str, w: int, h: int, top: bool = False) -> None:
    """Small lower-third label (food, landmark); at the top when subtitles hold the bottom of the frame."""
    s = h / 1080
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = _font(FONT_BOLD, int(40 * s), "SemiBold")
    pad_x, pad_y = int(26 * s), int(14 * s)
    tw = d.textlength(text, font=f)
    x0, y1 = int(96 * s), (int(70 * s) + int(40 * s) + 2 * pad_y if top else int(h - 110 * s))
    box = [x0, y1 - int(40 * s) - 2 * pad_y, x0 + int(tw) + 2 * pad_x + int(14 * s), y1]
    d.rounded_rectangle(box, radius=int(10 * s), fill=(15, 15, 15, 170))
    d.rectangle([box[0], box[1], box[0] + int(8 * s), box[3]], fill=(255, 196, 0, 255))
    d.text((box[0] + pad_x + int(10 * s), box[1] + pad_y - int(4 * s)), text, font=f, fill=(255, 255, 255, 255))
    img.save(path)


# ---------------------------------------------------------------- segments --

class Film:
    def __init__(self, path: Path, master: bool):
        self.path = path.resolve()
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.master = master
        fmt = self.data.get("format", {})
        self.fps_num = int(fmt.get("fps_num", 30000))
        self.fps_den = int(fmt.get("fps_den", 1001))
        self.fps = self.fps_num / self.fps_den
        self.w, self.h = (1920, 1080) if master else (960, 540)
        import csv
        with open(PROJECT / "analysis" / "catalog.csv", encoding="utf-8") as fh:
            self.originals = {r["id"]: Path(r["path"]) for r in csv.DictReader(fh) if r["type"] == "video"}
        self.proxy_dir = Path(self.data.get("proxy_dir", str(config.PROXY)))
        self.jpg_dir = Path(self.data.get("jpg_dir", str(config.JPG)))
        self.grade = self.data.get("grade", "eq=contrast=1.05:saturation=1.12")
        self.audio_cfg = self.data.get("audio", {})
        self.work = (config.WORK / "render") / ("master" if master else "preview")
        self.seg_dir = self.work / "segments"
        self.ovl_dir = self.work / "overlays"
        self.seg_dir.mkdir(parents=True, exist_ok=True)
        self.ovl_dir.mkdir(parents=True, exist_ok=True)
        self.clips = self.data["clips"]
        self._durations: dict[str, float] = {}

    # -- sources
    def source_for(self, clip: str) -> Path:
        """Sources by id (see analysis/catalog.csv).
        PHOTO:<id>  -> <work_dir>/jpg/<id>.jpg (orientation applied)
        <id>        -> preview: <work_dir>/proxy/<id>.mp4 (480p); master: the original file (catalog path)
        file:<path> -> project asset (route map, legs, intro)"""
        if clip.startswith("file:"):
            return PROJECT / clip[5:]
        if clip.startswith("PHOTO:"):
            full = self.jpg_dir / f"{clip[6:]}.jpg"
            if self.master or not full.exists():
                return full
            small = self.jpg_dir.parent / "jpg_small" / f"{clip[6:]}.jpg"  # preview: 1280 px copy, light to decode
            if not small.exists():
                small.parent.mkdir(parents=True, exist_ok=True)
                im = Image.open(full)
                im.thumbnail((1280, 1280))
                im.convert("RGB").save(small, quality=90)
            return small
        if not self.master:
            return self.proxy_dir / f"{clip}.mp4"
        return self.originals.get(clip, self.proxy_dir / f"{clip}.mp4")

    def audio_source(self, c: dict) -> Path:
        """Voice-isolated track (Demucs, same timeline) when the shot asks for it, else the picture's own file."""
        if c.get("clean_audio"):
            p = (config.WORK / "clean") / f"{c['clip']}.wav"
            if p.exists():
                return p
        return self.source_for(c["clip"])

    def source_duration(self, clip: str) -> float:
        if clip.startswith("PHOTO:"):
            return 3600.0
        if clip not in self._durations:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  str(self.source_for(clip))], capture_output=True, text=True).stdout.strip()
            self._durations[clip] = float(out)
        return self._durations[clip]

    def display_aspect(self, clip: str) -> float:
        """Width/height as displayed (rotation applied)."""
        key = "aspect:" + clip
        if key not in self._durations:
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                  "stream=width,height:stream_side_data=rotation:stream_tags=rotate", "-of", "json",
                                  str(self.source_for(clip))], capture_output=True, text=True).stdout
            st = json.loads(out)["streams"][0]
            rot = 0
            for sd in st.get("side_data_list", []) or []:
                rot = int(sd.get("rotation", rot) or 0)
            rot = int(st.get("tags", {}).get("rotate", rot) or rot)
            w, h = st["width"], st["height"]
            if abs(rot) % 180 == 90:
                w, h = h, w
            self._durations[key] = w / h
        return self._durations[key]

    def speech_gain(self, c: dict) -> float:
        """Gain that brings a kept-audio range to about -19 LUFS before the mix."""
        g_in, g_out = c.get("gain_range", [c["in"], c["out"]])
        key = f"lufs:{c['clip']}:{g_in}:{g_out}:{bool(c.get('clean_audio'))}"
        if key not in self._durations:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-ss", f"{float(g_in):.3f}", "-t",
                                f"{float(g_out) - float(g_in):.3f}", "-i", str(self.audio_source(c)),
                                "-vn", "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace").stderr
            vals = re.findall(r"I:\s+(-?[\d.]+) LUFS", r)
            self._durations[key] = float(vals[-1]) if vals else -19.0
        lufs = self._durations[key]
        if lufs < -60:
            return 1.0
        return max(0.5, min(6.0, 10 ** ((-19.0 - lufs) / 20)))

    # -- timing
    def frames(self, c: dict) -> int:
        speed = float(c.get("speed", 1.0))
        return max(1, round((float(c["out"]) - float(c["in"])) / speed * self.fps))

    def validate(self) -> list[str]:
        errors, ids = [], set()
        for i, c in enumerate(self.clips):
            cid = c.get("id", f"#{i}")
            if cid in ids:
                errors.append(f"{cid}: duplicate id")
            ids.add(cid)
            if not self.source_for(c["clip"]).exists():
                errors.append(f"{cid}: missing source {c['clip']}")
                continue
            if float(c["out"]) <= float(c["in"]):
                errors.append(f"{cid}: out <= in")
            dur = self.source_duration(c["clip"])
            if float(c["out"]) > dur + 0.05 and not c.get("freeze"):
                errors.append(f"{cid}: out {c['out']} beyond source duration {dur:.2f}")
        for m in self.data.get("music", []):
            if not (PROJECT / m["file"]).exists():
                errors.append(f"music missing: {m['file']}")
        return errors

    def seg_key(self, c: dict) -> str:
        payload = json.dumps({k: c.get(k) for k in sorted(c) if k not in ("note", "chapter", "desc", "id")}, sort_keys=True,
                             ensure_ascii=False)
        if c.get("audio") == "keep" and "audio_gain" not in c:
            payload += "|autogain2"
        if c["clip"].startswith("file:"):  # project assets (maps) are re-rendered in place: their mtime is part of the key
            src = self.source_for(c["clip"])
            payload += f"|{src.stat().st_mtime_ns if src.exists() else 0}"
        payload += f"|{self.master}|{self.grade}|{self.fps_num}/{self.fps_den}|{RENDERER_VERSION}|{self.audio_cfg.get('ambient_gain', 0.18)}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

    def render_quad(self, c: dict, vout: Path, aout: Path) -> None:
        """2x2 split screen; panel 0 is real time (its audio is kept), others are time-warped piecewise.
        c["quad"] = [{"clip": .., "pieces": [[src_a, src_b, out_dur], ...], "hold": seconds_to_freeze_at_end}, x4]"""
        n = self.frames(c)
        seg_dur = n / self.fps
        hw, hh = self.w // 2, self.h // 2
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error"]
        graph, panels = [], []
        for k, pnl in enumerate(c["quad"]):
            a0 = float(pnl["pieces"][0][0]); a1 = float(pnl["pieces"][-1][1])
            cmd += ["-ss", f"{a0:.3f}", "-t", f"{a1 - a0 + 0.5:.3f}", "-i", str(self.source_for(pnl["clip"]))]
            pcs = pnl["pieces"]
            labels = "".join(f"[q{k}s{j}]" for j in range(len(pcs)))
            graph.append(f"[{k}:v]split={len(pcs)}{labels}")
            outs = []
            for j, (sa, sb, od) in enumerate(pcs):
                f = float(od) / (float(sb) - float(sa))
                graph.append(f"[q{k}s{j}]trim=start={float(sa) - a0:.3f}:end={float(sb) - a0:.3f},setpts=(PTS-STARTPTS)*{f:.5f},"
                             f"fps={self.fps_num}/{self.fps_den}[q{k}p{j}]")
                outs.append(f"[q{k}p{j}]")
            hold = float(pnl.get("hold", 0))
            graph.append(f"{''.join(outs)}concat=n={len(outs)}:v=1:a=0,"
                         + (f"tpad=stop_mode=clone:stop_duration={hold + 0.5:.3f}," if hold else "")
                         + f"scale={hw}:{hh}:force_original_aspect_ratio=increase,crop={hw}:{hh},setsar=1,{self.grade},"
                         f"trim=duration={seg_dur:.4f},setpts=PTS-STARTPTS[pan{k}]")
            panels.append(f"[pan{k}]")
        graph.append(f"{''.join(panels)}xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0,format=yuv420p[vq]")
        last = "vq"
        idx = len(c["quad"])
        for item in c.get("fx", []):
            tag = hashlib.sha1((json.dumps(item, sort_keys=True, ensure_ascii=False) + str(self.h)).encode()).hexdigest()[:12]
            png = self.ovl_dir / f"fx_{tag}.png"
            if not png.exists():
                fxlib.make_png(png, self.w, self.h, item)
            cmd += ["-loop", "1", "-framerate", f"{self.fps_num}/{self.fps_den}", "-t", f"{seg_dur:.3f}", "-i", str(png)]
            st, du = float(item.get("start", 0)), float(item.get("dur", seg_dur))
            graph.append(f"[{idx}:v]format=rgba,fade=t=in:st={st:.3f}:d=0.4:alpha=1,fade=t=out:st={max(st, st + du - 0.4):.3f}:d=0.4:alpha=1[t{idx}]")
            graph.append(f"[{last}][t{idx}]overlay=0:0[v{idx}]")
            last = f"v{idx}"; idx += 1
        graph.append(f"[{last}]format=yuv420p[vout]")
        gain = float(c["audio_gain"]) if "audio_gain" in c else self.speech_gain(dict(c, clip=c["quad"][0]["clip"],
                                                                                      **{"in": c["quad"][0]["pieces"][0][0],
                                                                                         "out": c["quad"][0]["pieces"][-1][1]}))
        graph.append(f"[0:a]asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={gain:.3f},"
                     f"acompressor=threshold=0.08:ratio=3:attack=5:release=250:makeup=1,alimiter=limit=0.6:level=0:latency=1,"
                     f"apad=whole_dur={seg_dur:.6f},atrim=duration={seg_dur:.6f}[aout]")
        enc = config.h264("master" if self.master else "preview")
        tmpv, tmpa = vout.with_suffix(".tmp.mp4"), aout.with_suffix(".tmp.wav")
        script = self.seg_dir / f"{vout.stem}_quad.txt"
        script.write_text((";" + chr(10)).join(graph), encoding="utf-8")
        cmd += ["-/filter_complex", str(script), "-map", "[vout]", "-frames:v", str(n), *enc, "-g", "48", "-bf", "0",
                "-video_track_timescale", "24000", str(tmpv), "-map", "[aout]", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(tmpa)]
        run(cmd)
        tmpv.replace(vout); tmpa.replace(aout)

    def render_segment(self, c: dict) -> tuple[Path, Path]:
        key = self.seg_key(c)
        vout, aout = self.seg_dir / f"{key}.mp4", self.seg_dir / f"{key}.wav"
        if vout.exists() and aout.exists():
            return vout, aout
        if c.get("quad"):
            self.render_quad(c, vout, aout)
            return vout, aout
        n = self.frames(c)
        seg_dur = n / self.fps
        speed = float(c.get("speed", 1.0))
        src_len = float(c["out"]) - float(c["in"])
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error"]
        if self.master:
            cmd += config.hwaccel()
        if c["clip"].startswith("PHOTO:"):  # still photo: static, never moves (guide), silent
            cmd += ["-loop", "1", "-framerate", f"{self.fps_num}/{self.fps_den}", "-t", f"{src_len + 0.5:.3f}",
                    "-i", str(self.source_for(c["clip"]))]
            c = dict(c, audio="mute", framing=c.get("framing") or "blur")
        else:
            cmd += ["-ss", f"{float(c['in']):.3f}", "-t", f"{src_len + 0.5:.3f}", "-i", str(self.source_for(c["clip"]))]
        overlays = []
        if c.get("title"):
            t = c["title"]
            png = self.ovl_dir / f"title_{hashlib.sha1((t['text'] + t.get('sub', '') + str(self.h)).encode()).hexdigest()[:10]}.png"
            if not png.exists():
                make_title_png(png, t["text"], t.get("sub", ""), self.w, self.h)
            overlays.append((png, float(t.get("start", 0.4)), float(t.get("dur", 3.6)), None))
        if c.get("label"):
            lb = c["label"]
            top = lb.get("pos") == "top"
            png = self.ovl_dir / f"label_{hashlib.sha1((lb['text'] + str(self.h) + ('top' if top else '')).encode()).hexdigest()[:10]}.png"
            if not png.exists():
                make_label_png(png, lb["text"], self.w, self.h, top)
            overlays.append((png, float(lb.get("start", 0.4)), float(lb.get("dur", 3.0)), None))
        for k_fx, item in enumerate(c.get("fx", [])):
            tag = hashlib.sha1((json.dumps(item, sort_keys=True, ensure_ascii=False) + str(self.h)).encode()).hexdigest()[:12]
            png = self.ovl_dir / f"fx_{tag}.png"
            if not png.exists():
                fxlib.make_png(png, self.w, self.h, item)
            overlays.append((png, float(item.get("start", 0)), float(item.get("dur", 2.0)), item.get("fade")))
        for png, _, _, _ in overlays:
            cmd += ["-loop", "1", "-framerate", f"{self.fps_num}/{self.fps_den}", "-t", f"{seg_dur:.3f}", "-i", str(png)]
        cutaways = [cw for cw in c.get("cutaways", []) if float(cw["start"]) < seg_dur - 0.2]
        for cw in cutaways:
            cmd += ["-ss", f"{float(cw['in']):.3f}", "-t", f"{float(cw['dur']) + 0.5:.3f}", "-i", str(self.source_for(cw["clip"]))]

        if c.get("freeze"):
            vf_freeze = [f"trim=end_frame=1", "setpts=PTS-STARTPTS", f"tpad=stop_mode=clone:stop_duration={seg_dur + 0.5:.3f}"]
        else:
            vf_freeze = []
        rot = int(c.get("rotate", 0) or 0) % 360
        aspect = self.display_aspect(c["clip"])
        if rot in (90, 270):
            aspect = 1 / aspect
        # 4:3, portrait and panoramas are shown whole on a blurred fill; ~16:9 fills the frame; ~2:1 phone
        # landscape videos fill it too (9 % off each side) unless people talk in them (faces may sit near the edges)
        wide_phone = 1.9 < aspect < 2.3 and c.get("audio") != "keep" and not c["clip"].startswith("PHOTO:")
        framing = c.get("framing") or ("cover" if 1.6 <= aspect <= 1.9 or wide_phone else "blur")
        vf = [f"setpts=(PTS-STARTPTS)/{speed}" if speed != 1.0 else "setpts=PTS-STARTPTS",
              f"fps={self.fps_num}/{self.fps_den}"]
        if rot:  # media stored sideways (phone turned while filming)
            vf.append({90: "transpose=1", 270: "transpose=2", 180: "hflip,vflip"}[rot])
        if c.get("crop"):  # [x, y, w, h] as fractions of the frame: punch-in / reframe
            cx, cy, cw, ch_ = (float(v) for v in c["crop"])
            vf.append(f"crop=iw*{cw}:ih*{ch_}:iw*{cx}:ih*{cy}")
        if framing == "left":
            # credits layout: the shot sits whole in the left 60 %, on black; the credits fx uses the right
            fw, fh = int(self.w * 0.58) // 2 * 2, int(self.h * 0.84) // 2 * 2
            vf.append(f"scale={fw}:{fh}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,"
                      f"pad={self.w}:{self.h}:{int(self.w * 0.035)}+({fw}-iw)/2:(oh-ih)/2:black")
        elif framing in ("blur", "fit"):
            # portrait / 4:3 / panorama: the whole frame, sharp, centred on black (no blurred side fill)
            vf.append(f"scale={self.w}:{self.h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,"
                      f"pad={self.w}:{self.h}:(ow-iw)/2:(oh-ih)/2:black")
        else:
            vf += [f"scale={self.w}:{self.h}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={self.w}:{self.h}"]
        vf = vf[:1] + vf_freeze + vf[1:] if vf_freeze else vf
        # hold the last frame if the picture ends early (phone clips whose audio outlasts the video):
        # a missing frame would shift every later shot against the sample-exact audio
        vf.insert(next(i for i, f in enumerate(vf) if f.startswith("fps=")) + 1, f"tpad=stop_mode=clone:stop_duration={seg_dur:.3f}")
        vf += ["setsar=1", c.get("grade") or self.grade]
        if c.get("temp"):  # per-shot colour temperature (K; 6500 neutral, lower = warmer)
            vf.append(f"colortemperature=temperature={int(c['temp'])}:mix=0.6")
        if c.get("lift"):  # dark night shots: open the shadows (gamma) and lift the floor a touch
            g = float(c["lift"])
            vf.append(f"eq=gamma={g:.2f}:brightness={min(0.08, (g - 1) * 0.06):.3f}:saturation=1.05")
        if c.get("style") == "flashback":
            vf += ["hue=s=0.25", "eq=contrast=1.06:brightness=0.02", "vignette=PI/6"]
        if self.master:
            vf.append("unsharp=5:5:0.35:5:5:0.0")
        fi, fo = float(c.get("fade_in", 0)), float(c.get("fade_out", 0))
        if fi > 0:
            vf.append(f"fade=t=in:st=0:d={fi:.3f}")
        if fo > 0:
            vf.append(f"fade=t=out:st={max(0, seg_dur - fo):.3f}:d={fo:.3f}")
        graph = [f"[0:v]{','.join(vf)},format=yuv420p[v0]"]
        last = "v0"
        base_idx = 1 + len(overlays)
        for j, cw in enumerate(cutaways):
            st = float(cw["start"]); du = min(float(cw["dur"]), seg_dur - st)
            cvf = ["setpts=PTS-STARTPTS", f"fps={self.fps_num}/{self.fps_den}"]
            if cw.get("crop"):
                cx, cy, cwid, chei = (float(v) for v in cw["crop"])
                cvf.append(f"crop=iw*{cwid}:ih*{chei}:iw*{cx}:ih*{cy}")
            cvf += [f"scale={self.w}:{self.h}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={self.w}:{self.h}",
                    "setsar=1", self.grade,
                    *(["hue=s=0.25", "eq=contrast=1.06:brightness=0.02", "vignette=PI/6"] if cw.get("style") == "flashback" else []),
                    "format=yuv420p", f"trim=duration={du:.3f}", f"setpts=PTS+{st:.3f}/TB"]
            graph.append(f"[{base_idx + j}:v]{','.join(cvf)}[cw{j}]")
            graph.append(f"[{last}][cw{j}]overlay=0:0:eof_action=pass:enable='between(t,{st:.3f},{st + du:.3f})'[vc{j}]")
            last = f"vc{j}"
        for k, (png, st, du, fade) in enumerate(overlays, start=1):
            du = min(du, seg_dur - st)
            fd = min(0.45, du / 4) if fade is None else max(0.04, float(fade))
            graph.append(f"[{k}:v]format=rgba,fade=t=in:st={st:.3f}:d={fd:.3f}:alpha=1,"
                         f"fade=t=out:st={max(st, st + du - fd):.3f}:d={fd:.3f}:alpha=1[o{k}]")
            graph.append(f"[{last}][o{k}]overlay=0:0:format=auto[v{k}]")
            last = f"v{k}"
        graph.append(f"[{last}]format=yuv420p[vout]")

        mode = c.get("audio", "mute")
        has_audio = True
        if mode == "keep":
            gain = float(c["audio_gain"]) if "audio_gain" in c else self.speech_gain(c)
            gain *= 10 ** (float(c.get("voice_db", 0)) / 20)  # reviewer correction on top of the automatic level
        else:
            gain = float(self.audio_cfg.get("ambient_gain", 0.18))
        if mode == "mute" or speed != 1.0:
            graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={seg_dur:.6f}[aout]")
            has_audio = False
        else:
            af = ["asetpts=PTS-STARTPTS", "aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo",
                  f"volume={gain:.3f}",
                  *(["acompressor=threshold=0.08:ratio=3:attack=5:release=250:makeup=1",
                    "alimiter=limit=0.6:level=0:attack=1:release=50:latency=1"] if mode == "keep" else []),
                  # before the first word a speech shot plays at ambience level (no noise burst at speech gain)
                  *([f"volume={float(self.audio_cfg.get('ambient_gain', 0.18)) / gain:.4f}:enable='lt(t,{float(c['speech_from']):.3f})'"]
                    if mode == "keep" and c.get("speech_from") and gain > 0 else []),
                  *([] if c.get("seamless_in") else [f"afade=t=in:st=0:d={max(0.08, fi):.3f}"]),
                  *([] if c.get("seamless_out") else
                    [f"afade=t=out:st={max(0, seg_dur - max(0.12, fo)):.3f}:d={max(0.12, fo):.3f}"]),
                  f"apad=whole_dur={seg_dur:.6f}", f"atrim=duration={seg_dur:.6f}"]
            ain = "0:a"
            if mode == "keep" and c.get("clean_audio") and self.audio_source(c) != self.source_for(c["clip"]):
                cmd += ["-ss", f"{float(c['in']):.3f}", "-t", f"{src_len + 0.5:.3f}", "-i", str(self.audio_source(c))]
                ain = f"{sum(1 for x in cmd if x == '-i') - 1}:a"
            graph.append(f"[{ain}]{','.join(af)}[aout]")
        enc = config.h264("master" if self.master else "preview")
        tmpv, tmpa = vout.with_suffix(".tmp.mp4"), aout.with_suffix(".tmp.wav")
        cmd += ["-filter_complex", ";".join(graph),
                "-map", "[vout]", "-frames:v", str(n), *enc, "-g", "48", "-bf", "0",
                "-video_track_timescale", "24000", str(tmpv),
                "-map", "[aout]", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(tmpa)]
        try:
            run(cmd)
        except RuntimeError:
            if not has_audio:
                raise
            # some clips have no usable audio stream: retry silent
            c2 = dict(c, audio="mute")
            return self.render_segment(c2)
        got = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                              "stream=nb_read_packets", "-of", "csv=p=0", str(tmpv)], capture_output=True, text=True).stdout
        if int(got.strip().split(",")[0] or 0) != n:
            raise RuntimeError(f"{c.get('id')} {c['clip']}: {got.strip()} frames rendered, {n} planned (lip sync would drift)")
        tmpv.replace(vout)
        tmpa.replace(aout)
        return vout, aout

    # -------------------------------------------------------------- assembly --
    def timeline(self) -> list[tuple[dict, float, float]]:
        t, out = 0.0, []
        for c in self.clips:
            d = self.frames(c) / self.fps
            out.append((c, t, t + d))
            t += d
        return out

    def duck_expression(self) -> str:
        cfg = self.data.get("duck", {})
        level = float(cfg.get("level", 0.22))
        ramp = float(cfg.get("ramp", 0.35))
        pad = float(cfg.get("pad", 0.15))
        intervals = []
        for c, s, e in self.timeline():
            if c.get("audio") == "keep" and c.get("duck", True):
                lv = float(c.get("duck_level", level))
                # duck from the first word, not the cut: the music would leave a hole before people speak
                intervals.append((s + float(c.get("speech_from", 0)) - pad, e + pad, lv))
        for vo in self.data.get("voiceover", []):
            intervals.append((float(vo["start"]) - 0.25, float(vo["start"]) + float(vo["dur"]) + 0.2,
                              float(vo.get("duck_level", 0.32))))
        merged = self._merge_duck(intervals)
        if not merged:
            return "1"
        terms = []
        for s, e, lv in merged:
            # trapezoid 0..1 that is 1 inside [s,e], ramps outside over `ramp`
            shape = f"clip(min((t-{s - ramp:.3f})/{ramp:.3f},({e + ramp:.3f}-t)/{ramp:.3f}),0,1)"
            terms.append(f"{1 - lv:.3f}*{shape}")
        expr = terms[0]
        for term in terms[1:]:
            expr = f"max({expr},{term})"
        return f"1-{expr}"

    def concat(self, segs: list[tuple[Path, Path]], total: float) -> tuple[Path, Path]:
        lst = self.work / "concat.txt"
        lst.write_text("".join(f"file '{v.as_posix()}'\n" for v, _ in segs), encoding="utf-8")
        video = self.work / "video_only.mp4"
        run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", str(video)])
        # sample-exact WAV concat
        natural = self.work / "natural.wav"
        with wave.open(str(natural), "wb") as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(48000)
            for c, (_, a) in zip(self.clips, segs):
                # exactly the samples of the segment's frames, so a short audio stream cannot shift later shots
                want = round(self.frames(c) * self.fps_den / self.fps_num * 48000)
                with wave.open(str(a), "rb") as w:
                    data = w.readframes(min(w.getnframes(), want))
                out.writeframes(data + bytes(4 * (want - len(data) // 4)))
        return video, natural


    @staticmethod
    def _merge_duck(intervals):
        # merge touching intervals
        merged: list[list[float]] = []
        for s, e, lv in sorted(intervals):
            if merged and s <= merged[-1][1] + 1.2:  # no swell for a moment between two voices...
                merged[-1][1] = max(merged[-1][1], e)
                merged[-1][2] = min(merged[-1][2], lv)
            elif merged and s <= merged[-1][1] + 3.0:  # ...but a short gap keeps a quiet bed, never digital silence
                merged.append([merged[-1][1], s, 0.25])
                merged.append([s, e, lv])
            else:
                merged.append([s, e, lv])
        return merged

    def duck_intervals(self):
        """(start, end, level) of every music dip, as the expression would build them, plus the ramp."""
        cfg = self.data.get("duck", {})
        level, pad = float(cfg.get("level", 0.22)), float(cfg.get("pad", 0.15))
        intervals = []
        for c, s_, e_ in self.timeline():
            if c.get("audio") == "keep" and c.get("duck", True):
                intervals.append((s_ + float(c.get("speech_from", 0)) - pad, e_ + pad, float(c.get("duck_level", level))))
        for vo in self.data.get("voiceover", []):
            intervals.append((float(vo["start"]) - 0.25, float(vo["start"]) + float(vo["dur"]) + 0.2,
                              float(vo.get("duck_level", 0.32))))
        return self._merge_duck(intervals), float(cfg.get("ramp", 0.35))

    def build_track(self, items, total, out, duck=False):
        """Assemble cues into ONE wav with numpy (memmap on D:): sample-exact placement, fades and ducking.
        ffmpeg mixing 20+ delayed inputs dropped whole cues at random (input queues overflowed); it never does that now."""
        import numpy as np
        import wave as _wave
        sr = 48000
        n = int(round(total * sr)) + sr
        tmp = out.with_suffix(".f32")
        buf = np.memmap(tmp, dtype=np.float32, mode="w+", shape=(n, 2))
        for it in items:
            with _wave.open(str(it["path"]), "rb") as w:
                assert w.getframerate() == sr and w.getnchannels() == 2 and w.getsampwidth() == 2, it["path"]
                want = int(round(float(it["dur"]) * sr))
                raw = w.readframes(min(w.getnframes(), want))
            data = np.frombuffer(raw, dtype="<i2").astype(np.float32).reshape(-1, 2) / 32768.0
            data = data * float(it.get("gain", 1.0))
            m = len(data)
            fi, fo = int(float(it.get("fade_in", 0)) * sr), int(float(it.get("fade_out", 0)) * sr)
            if fi > 0:
                k = min(fi, m)
                data[:k] *= np.linspace(0, 1, k, dtype=np.float32)[:, None]
            if fo > 0:
                k = min(fo, m)
                data[m - k:] *= np.linspace(1, 0, k, dtype=np.float32)[:, None]
            a0 = int(round(float(it["start"]) * sr))
            a1 = min(n, a0 + m)
            if a1 > a0:
                buf[a0:a1] += data[:a1 - a0]
        if duck:
            merged, ramp = self.duck_intervals()
            for s_, e_, lv in merged:
                x0, x1 = max(0, int((s_ - ramp) * sr)), min(n, int((e_ + ramp) * sr))
                if x1 <= x0:
                    continue
                t = np.arange(x0, x1, dtype=np.float64) / sr
                shape = np.clip(np.minimum((t - (s_ - ramp)) / ramp, ((e_ + ramp) - t) / ramp), 0, 1).astype(np.float32)
                buf[x0:x1] *= (1 - (1 - lv) * shape)[:, None]
        buf.flush()
        end = int(round(total * sr))
        with _wave.open(str(out), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(sr)
            step = sr * 10
            for k in range(0, end, step):
                chunk = np.clip(np.asarray(buf[k:min(k + step, end)]), -1, 1)
                w.writeframes((chunk * 32767).astype("<i2").tobytes())
        del buf
        tmp.unlink(missing_ok=True)
        return out

    def mix_and_mux(self, video: Path, natural: Path, total: float, output: Path) -> None:
        music = self.data.get("music", [])
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", str(video), "-i", str(natural)]
        graph = []
        a = self.audio_cfg
        cue_items = []
        for m in music:
            dur = float(m["end"]) - float(m["start"])
            lvl = (float(self.data["music_level_lufs"]) + float(m.get("gain_db_extra", 0))
                   if self.data.get("music_level_lufs") is not None else None)
            key = hashlib.sha1(f"{m['file']}|{float(m.get('src_in', 0)):.3f}|{dur:.3f}|{lvl}|{m.get('gain')}".encode()).hexdigest()[:16]
            cue = self.work / "music_cues" / f"{key}.wav"
            if not cue.exists():
                cue.parent.mkdir(parents=True, exist_ok=True)
                af = (f"loudnorm=I={lvl:.1f}:LRA=7:TP=-6,aresample=48000" if lvl is not None
                      else f"volume={float(m.get('gain', 0.8)):.3f}")
                run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", f"{float(m.get('src_in', 0)):.3f}",
                     "-t", f"{dur + 0.2:.3f}", "-i", str(PROJECT / m["file"]), "-af", af, "-ar", "48000", "-ac", "2",
                     "-c:a", "pcm_s16le", str(cue)])
            cue_items.append({"path": cue, "start": float(m["start"]), "dur": dur,
                              "fade_in": float(m.get("fade_in", 0.8)), "fade_out": float(m.get("fade_out", 1.5))})
        bed = self.build_track(cue_items, total, self.work / "bed.wav", duck=True)
        vo_items = []
        for vo in self.data.get("voiceover", []):
            lv = float(vo.get("lufs", -19))
            key = hashlib.sha1(f"{vo['file']}|{lv}|{Path(vo['file']).stat().st_size}".encode()).hexdigest()[:16]
            levelled = self.work / "vo" / f"{key}.wav"
            if not levelled.exists():
                levelled.parent.mkdir(parents=True, exist_ok=True)
                run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", str(vo["file"]), "-af",
                     f"loudnorm=I={lv:.1f}:LRA=9:TP=-3,aresample=48000", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
                     str(levelled)])
            vo_items.append({"path": levelled, "start": float(vo["start"]), "dur": float(vo["dur"]) + 0.5, "fade_in": 0.05})
        vtrack = self.build_track(vo_items, total, self.work / "voiceover.wav")
        cmd += ["-i", str(bed), "-i", str(vtrack)]
        graph.append("[2:a]aformat=sample_fmts=fltp:channel_layouts=stereo[bed]")
        graph.append("[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[nat0]")
        graph.append("[3:a]aformat=sample_fmts=fltp:channel_layouts=stereo[vo]")
        graph.append("[nat0][vo]amix=inputs=2:normalize=0:duration=first[nat]")
        graph.append(f"[bed][nat]amix=inputs=2:normalize=0:duration=first[mix]")
        # static loudness: measure the whole mix, then one fixed gain (a dynamic loudnorm rides the level
        # every few seconds and pulls speech down after loud music)
        script = self.work / "mix_filter.txt"
        script.write_text(";\n".join(graph + ["[mix]ebur128=framelog=quiet[aout]"]), encoding="utf-8")
        measure = [x for x in cmd if x not in ("-v", "error")]  # the ebur128 summary prints at info level
        r = subprocess.run(measure + ["-/filter_complex", str(script), "-map", "[aout]", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        measured = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])
        # the final limiter takes back about 1 dB of loudness on this material: aim that much higher before it
        gain_db = float(a.get("target_lufs", -14)) - measured + float(a.get("limiter_makeup_db", 1.0))
        print(f"  mix {measured:.1f} LUFS -> gain {gain_db:+.1f} dB")
        graph.append(f"[mix]volume={gain_db:.2f}dB,"
                     # limit at 4x the sample rate so inter-sample (true) peaks are caught too
                     f"aresample=192000,alimiter=limit=0.71:level=0:attack=1:release=60,aresample=48000,"
                     f"atrim=duration={total:.3f}[aout]")
        script.write_text(";\n".join(graph), encoding="utf-8")
        cmd += ["-/filter_complex", str(script), "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
                "-c:a", "aac_mf", "-b:a", "256k", "-ar", "48000",
                "-movflags", "+faststart", "-t", f"{total:.3f}", str(output)]
        run(cmd)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("film", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--master", action="store_true")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()

    film = Film(args.film, args.master)
    errors = film.validate()
    if errors:
        print("VALIDATION FAILED:\n  " + "\n  ".join(errors))
        sys.exit(2)
    tl = film.timeline()
    total = tl[-1][2]
    print(f"{len(tl)} clips, {total:.2f} s ({total / 60:.2f} min), {film.w}x{film.h} @ {film.fps:.3f}")
    if args.validate_only:
        return

    done = 0

    def job(c):
        nonlocal done
        r = film.render_segment(c)
        done += 1
        if done % 10 == 0 or done == len(film.clips):
            print(f"  segments {done}/{len(film.clips)}", flush=True)
        return r

    with ThreadPoolExecutor(args.jobs) as ex:
        segs = list(ex.map(job, film.clips))
    video, natural = film.concat(segs, total)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    film.mix_and_mux(video, natural, total, args.output.resolve())
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
