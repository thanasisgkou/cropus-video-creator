#!/usr/bin/env python3
"""Turn the chief director's edit decision list (edl.json) into a renderable film.json.

edl.json:
{
  "intro": [{"clip": "file:assets/route_intro.mp4", "in": 0, "out": 9.0}],
  "chapters": [
    {"name": "D1_OLD_TOWN", "title": {"text": "OLD TOWN", "sub": "Day 1"},
     "music": "my-track", "music_in": 0,                      # mp3 name in music/, or "continue"
     "shots": ["d1:m3",                                                   # director moment by id
               {"ref": "d1:m5", "in": 12.0, "out": 16.0, "audio": "keep", "label": "Street food"},
               {"clip": "GX010123", "in": 1, "out": 4}]}                  # raw clip range
  ],
  "outro": [...],
  "music_gap_fade": 1.2
}
Shot fields override the referenced moment. audio: keep|mute|ambient (default: keep if the
director marked keep_audio, else ambient).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from config import PROJECT  # noqa: E402
import config  # noqa: E402
FPS = 30000 / 1001
BED_LUFS = -28.0


def load_moments() -> dict[str, dict]:
    out = {}
    for p in sorted((PROJECT / "analysis" / "directors").glob("d*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        for m in data.get("moments", []):
            out[f"{p.stem}:{m['id']}"] = m
    return out


def music_rows() -> list:
    p = PROJECT / "analysis" / "music" / "summary.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def music_loudness() -> dict[str, float]:
    rows = music_rows()
    return {r[0]: float(r[3]) for r in rows}


def music_length() -> dict[str, float]:
    """Playable length: up to the last audible sound (a silent tail would leave dead air at a chain point)."""
    import re as _re
    import subprocess as _sp
    rows = music_rows()
    cache = PROJECT / "analysis" / "music" / "audible_end.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    ends = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    for r in rows:
        if r[0] not in ends:
            err = _sp.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(PROJECT / "music" / f"{r[0]}.mp3"), "-af",
                           "silencedetect=n=-45dB:d=0.4", "-f", "null", "-"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stderr
            starts = [float(x) for x in _re.findall(r"silence_start: ([\d.]+)", err)]
            tail = [x for x in starts if x > float(r[1]) - 15]
            ends[r[0]] = round(min(tail) if tail else float(r[1]), 2)
    cache.write_text(json.dumps(ends, indent=0), encoding="utf-8")
    return {r[0]: min(float(r[1]), ends[r[0]]) for r in rows}


END_PUNCT = (".", "!", "?", ";", "…", "»")


def load_words(clip: str):
    p = PROJECT / "analysis" / "words" / f"{clip}.json"
    if not p.exists():
        return None
    ws = json.loads(p.read_text(encoding="utf-8"))["words"]
    return [w for w in ws if w["e"] > w["s"]]


def snap_speech(clips: list[dict], durations: dict[str, float]) -> list[str]:
    """Move in/out of audio=keep shots so no sentence is cut (word-level Whisper)."""
    log = []
    for i, c in enumerate(clips):
        if c.get("audio") != "keep" or c["clip"].startswith("file:") or c.get("lock"):
            continue
        ws = load_words(c["clip"])
        if not ws:
            continue
        a, b = float(c["in"]), float(c["out"])
        prev_same = i > 0 and clips[i - 1]["clip"] == c["clip"] and abs(float(clips[i - 1]["out"]) - a) < 0.6
        next_same = i + 1 < len(clips) and clips[i + 1]["clip"] == c["clip"] and abs(float(clips[i + 1]["in"]) - b) < 0.6
        new_a, new_b = a, b
        if not prev_same:
            # first word that is heard inside the shot
            k = next((j for j, w in enumerate(ws) if w["e"] > a + 0.05), None)
            if k is not None and ws[k]["s"] < b:
                # walk back while the previous word belongs to the same sentence
                while k > 0 and not ws[k - 1]["w"].strip().endswith(END_PUNCT) and ws[k]["s"] - ws[k - 1]["e"] < 0.9                         and a - ws[k - 1]["s"] < 4:
                    k -= 1
                new_a = min(a, max(0.0, ws[k]["s"] - 0.25))
        if not next_same:
            k = max((j for j, w in enumerate(ws) if w["s"] < b - 0.05), default=None)
            if k is not None and ws[k]["e"] > a:
                while k + 1 < len(ws) and not ws[k]["w"].strip().endswith(END_PUNCT) and ws[k + 1]["s"] - ws[k]["e"] < 0.9                         and ws[k + 1]["e"] - b < 9:
                    k += 1
                new_b = max(b, ws[k]["e"] + 0.35)
                new_b = min(new_b, durations.get(c["clip"], new_b) - 0.05)
        # no word may straddle a cut point
        for w in ws:
            if w["s"] < new_a - 0.05 < w["e"] - 0.08:
                new_a = w["e"] + 0.03 if w["w"].strip().endswith(END_PUNCT + (",",)) else max(0.0, w["s"] - 0.2)
            if w["s"] + 0.08 < new_b < w["e"] - 0.05:
                new_b = min(w["e"] + 0.25, durations.get(c["clip"], w["e"] + 0.25) - 0.05)
        # never grow into a neighbouring shot cut from the same clip (jump cuts)
        for j in (i - 1, i + 1):
            if 0 <= j < len(clips) and clips[j]["clip"] == c["clip"]:
                o_a, o_b = float(clips[j]["in"]), float(clips[j]["out"])
                if o_b <= a + 0.01:
                    new_a = max(new_a, o_b)
                if o_a >= b - 0.01:
                    new_b = min(new_b, o_a)
        if abs(new_a - a) > 0.05 or abs(new_b - b) > 0.05:
            log.append(f"{c['id']} {c['clip']} {a:.2f}-{b:.2f} -> {new_a:.2f}-{new_b:.2f}")
            c["in"], c["out"] = round(new_a, 2), round(new_b, 2)
    return log


def apply_graphics(clips: list[dict], gfx: dict) -> list[str]:
    """Insert flashbacks/freezes (splitting shots) and attach overlays, from analysis/graphics.json."""
    log = []

    def find(clip, t, shot=None):
        hits = [i for i, c in enumerate(clips)
                if c["clip"] == clip and float(c["in"]) + 0.05 < t < float(c["out"]) - 0.05 and not c.get("freeze")
                and c.get("style") != "flashback"]
        if len(hits) > 1 and shot:
            exact = [i for i in hits if clips[i].get("id") == shot]
            if exact:
                return exact[0]
        return hits[0] if hits else None

    def split_insert(i, t, new):
        c = clips[i]
        a = dict(c, out=round(t, 3), lock=True)
        b = dict(c, **{"in": round(t, 3), "lock": True})
        a.pop("title", None) if float(c["in"]) + float(c.get("title", {}).get("start", 0)) > t else b.pop("title", None)
        b.pop("label", None)
        parts = [x for x in (a, new, b) if x is new or float(x["out"]) - float(x["in"]) >= 0.5]
        clips[i:i + 1] = parts

    last_insert = {}
    for fb in gfx.get("flashbacks", []):
        key = (fb["after_clip"], float(fb["after_time"]))
        d = float(fb["from_out"]) - float(fb["from_in"])
        new = {"clip": fb["from_clip"], "in": float(fb["from_in"]), "out": float(fb["from_out"]),
               "audio": fb.get("audio", "keep"), "style": "flashback", "lock": True,
               "desc": "FLASHBACK " + fb.get("label", ""),
               "fx": [{"type": "flashback_tag", "text": fb.get("label", ""), "start": 0.0, "dur": d}]}
        if fb.get("crop"):
            new["crop"] = fb["crop"]
        if key in last_insert:  # montage: chain after the previous piece
            j = clips.index(last_insert[key]) + 1
            new["chapter"] = clips[j - 1]["chapter"]
            clips.insert(j, new); last_insert[key] = new
            log.append(f"flashback(montage) {fb['from_clip']}"); continue
        i = find(fb["after_clip"], float(fb["after_time"]), fb.get("after_shot"))
        if i is None:
            log.append(f"flashback skipped (not in cut): {fb['after_clip']} @ {fb['after_time']}"); continue
        new["chapter"] = clips[i]["chapter"]
        split_insert(i, float(fb["after_time"]), new); last_insert[key] = new
        log.append(f"flashback {fb['from_clip']} after {fb['after_clip']}@{fb['after_time']}")
    for fx in gfx.get("overlays", []):
        if fx.get("type") != "freeze":
            continue
        i = find(fx["clip"], float(fx["at"]))
        if i is None:
            log.append(f"freeze skipped: {fx['clip']} @ {fx['at']}"); continue
        d = float(fx.get("dur", 1.5))
        new = {"clip": fx["clip"], "in": float(fx["at"]), "out": float(fx["at"]) + d, "freeze": True, "audio": "mute",
               "lock": True, "chapter": clips[i]["chapter"], "desc": "FREEZE " + fx.get("text", ""),
               "fx": [{"type": "caption", "text": fx.get("text", ""), "pos": fx.get("pos", "bottom"), "start": 0.15, "dur": d - 0.15}]}
        split_insert(i, float(fx["at"]), new); log.append(f"freeze {fx['clip']}@{fx['at']}")
    for fx in gfx.get("overlays", []):
        if fx.get("type") == "freeze":
            continue
        at = float(fx["at"])
        hit = False
        cands = [c for c in clips if c["clip"] == fx["clip"] and not c.get("freeze") and c.get("style") != "flashback"
                 and float(c["in"]) - 0.05 <= at < float(c["out"]) - 0.3]
        if len(cands) > 1 and fx.get("shot"):
            cands = [c for c in cands if c.get("id") == fx["shot"]] or cands
        for c in cands[:1]:
                d = min(float(fx.get("dur", 2.5)), float(c["out"]) - at)
                c.setdefault("fx", []).append({**{k: v for k, v in fx.items() if k not in ("clip", "at", "shot", "why")},
                                               "start": round(max(0.0, at - float(c["in"])), 3), "dur": round(d, 3)})
                hit = True
                break
        if not hit:
            log.append(f"overlay skipped (not in cut): {fx['clip']} @ {at} {fx.get('text','')}")
    return log


_CAT_TIMES = None


def clip_time(clip: str) -> str:
    """Local time of a clip or still (from analysis/catalog.csv)."""
    return _clip_time_raw(clip)


def src_path(clip: str) -> Path:
    """Analysis source for a clip id: the 480p proxy (every video has one)."""
    return (config.WORK / "proxy") / f"{clip}.mp4"


def _clip_time_raw(clip: str) -> str:
    global _CAT_TIMES
    import csv
    if _CAT_TIMES is None:
        _CAT_TIMES = {r["id"]: r["local_time"] for r in csv.DictReader(open(PROJECT / "analysis" / "catalog.csv", encoding="utf-8"))}
    if clip.startswith("PHOTO:"):
        clip = clip[6:]
    return _CAT_TIMES.get(clip, "")


PLACES = config.PLACES  # (from local time, place), from project.json "places"


def place_of(clip: str) -> str:
    """Where a clip was filmed (by local time and project.json "places")."""
    t = clip_time(clip)
    hits = [p for start, p in PLACES if t and t >= start]
    return hits[-1] if hits else ""


def mark_memories(clips: list[dict]) -> int:
    """Cutaways from another place look like a memory: desaturated + a small '⏪ place' tag."""
    n = 0
    for c in clips:
        hp = place_of(c["clip"])
        for cw in c.get("cutaways", []):
            sp = place_of(cw["clip"])
            if hp and sp and hp != sp and not cw.get("style"):
                cw["style"] = "flashback"
                c.setdefault("fx", []).append({"type": "flashback_tag", "text": sp, "start": cw["start"],
                                               "dur": cw["dur"], "memory": True})
                n += 1
    return n


def _v4_ranges() -> dict:
    p = PROJECT / "analysis" / "review_timeline.txt"
    out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) > 6 and "-" in parts[6]:
                a, b = parts[6].split("-")[:2]
                try:
                    out[parts[0]] = (parts[5], float(a), float(b))
                except ValueError:
                    pass
    return out


def apply_review_fixes(clips: list[dict], reviews: list[dict]) -> list[str]:
    """Reviewers' fixes keyed by old shot ids, mapped to clip + source range so they survive re-timing."""
    log, rng = [], _v4_ranges()
    def targets(fx):
        clip = fx.get("clip")
        r = rng.get(fx.get("shot"))
        a, b = (r[1], r[2]) if r and r[0] == clip else (-1, 1e9)
        return [c for c in clips if c["clip"] == clip and float(c["out"]) > a + 0.05 and float(c["in"]) < b - 0.05
                and c.get("style") != "flashback"]
    for rv in reviews:
        for fx in rv.get("fixes", []):
            kind, ts = fx.get("kind"), targets(fx)
            if not ts:
                log.append(f"fix skipped (not found) {kind} {fx.get('shot')} {fx.get('clip')}"); continue
            if kind == "drop_shot":
                r = rng.get(fx.get("shot"))
                gone = [c for c in ts if r and abs(float(c["in"]) - r[1]) < 0.15 and abs(float(c["out"]) - r[2]) < 0.15]
                for c in gone:
                    clips.remove(c)
                if not gone:
                    log.append(f"fix: drop_shot found nothing {fx.get('shot')}"); continue
            elif kind == "add_cutaway":
                at = float(fx["at"]); placed = False
                for c in ts:
                    if float(c["in"]) <= at < float(c["out"]) - 0.5:
                        c.setdefault("cutaways", []).append({"clip": fx["cutaway_clip"], "in": float(fx["cw_in"]),
                                                             "dur": min(float(fx["dur"]), float(c["out"]) - at - 0.1),
                                                             "start": round(at - float(c["in"]), 3)})
                        placed = True; break
                if not placed:
                    log.append(f"fix: add_cutaway found no shot {fx.get('clip')}@{at}"); continue
            elif kind == "remove_zoom":
                for c in ts: c["no_zoom"] = True
            elif kind in ("remove_cutaway", "replace_cutaway"):
                hit = 0
                want_in = None
                if fx.get("n") is None:
                    import re as _re
                    m_ = _re.search(r"n\s*=\s*(\d+)", fx.get("why", ""))
                    if m_ and str(fx.get("shot", "")).startswith("x"):
                        fx = dict(fx, n=int(m_.group(1)))
                if fx.get("n") is not None:
                    vp = PROJECT / "analysis" / "verify" / "cutaways.json"
                    if vp.exists():
                        it = next((x for x in json.loads(vp.read_text(encoding="utf-8")) if x["n"] == int(fx["n"])), None)
                        if it:
                            want_in = float(it["cutaway_in"])
                for c in ts:
                    for cw in list(c.get("cutaways", [])):
                        if cw["clip"] == fx.get("cutaway_clip") and (want_in is None or abs(float(cw["in"]) - want_in) < 0.06):
                            hit += 1
                            if kind == "remove_cutaway":
                                c["cutaways"].remove(cw)
                            else:
                                cw["clip"] = fx["new_clip"]; cw["in"] = float(fx.get("new_in", cw["in"]))
                if not hit:
                    log.append(f"fix: cutaway {fx.get('cutaway_clip')} not found on {fx.get('clip')}"); continue
            elif kind == "make_talk":
                for c in ts: c["audio"] = "keep"
            elif kind == "make_music":
                for c in ts: c["audio"] = "ambient"
            elif kind == "remove_overlay":
                key = (fx.get("overlay") or "").lower()
                for c in ts:
                    c["fx"] = [x for x in c.get("fx", []) if not (key and (x["type"].lower() in key) and
                               (not (x.get("text") or x.get("stats")) or (x.get("text") or x.get("stats") or "")[:12].lower() in key))]
            else:
                log.append(f"MANUAL {fx.get('shot')} {fx.get('clip')}: {fx.get('why','')[:160]}"); continue
            log.append(f"fix {kind} {fx.get('shot')} {fx.get('clip')}")
    return log


def apply_subtitles(clips: list[dict], reviews: list[dict]) -> int:
    n = 0
    for rv in reviews:
        for sb in rv.get("subtitles", []):
            a, b = float(sb["from"]), float(sb["to"])
            for c in clips:
                if c["clip"] != sb["clip"] or c.get("freeze") or c.get("audio") != "keep":
                    continue
                ca, cb = float(c["in"]), float(c["out"])
                lo, hi = max(a, ca), min(b, cb)
                if hi - lo >= 0.8:  # a shorter remnant across a cut only blinks the line again
                    c.setdefault("fx", []).append({"type": "subtitle", "text": sb["text"], "start": round(lo - ca, 3),
                                                   "dur": round(hi - lo, 3), "v": 2, "fade": 0.08})  # v2: line breaks kept; no slow fade
                    n += 1
    return n


def apply_phone(clips: list[dict], plans: list[dict], durations: dict) -> list[str]:
    """Insert phone clips (PH...) chosen by the judges: after a given shot, or chronologically."""
    log = []
    items = [it for pl in plans for it in pl.get("inserts", [])]
    for pl in plans:  # photos: static, 3.5 s, placed chronologically
        for ph in pl.get("photos", []):
            if str(ph.get("file", "")).lower().endswith((".jpg", ".jpeg", ".png")):
                items.append({"clip": "PHOTO:" + ph["file"], "in": 0.0, "out": float(ph.get("dur", 3.5)), "audio": "mute",
                              "why": "photo: " + ph.get("why", "")})
    last_after = {}  # anchor clip -> last shot inserted after it (keeps the judges' listed order)
    for it in items:
        shot = {"id": "ph", "clip": it["clip"], "in": float(it["in"]), "out": float(it["out"]), "audio": it.get("audio", "keep"),
                "desc": "PHONE: " + it.get("why", "")[:100]}
        if it.get("label"):
            shot["label"] = {"text": it["label"], "start": 0.4, "dur": 3.0}
        if not shot["clip"].startswith("PHOTO:"):
            snap_speech([shot], durations)
        pos = None
        if it.get("after_clip"):
            t = float(it.get("after_time", 0))
            cand = [i for i, c in enumerate(clips) if c["clip"] == it["after_clip"] and float(c["in"]) - 0.1 <= t <= float(c["out"]) + 0.1]
            if cand:
                pos = cand[-1] + 1
                prev = last_after.get(it["after_clip"])
                if prev is not None and prev in clips and clips.index(prev) >= pos - 1:
                    pos = clips.index(prev) + 1
        if pos is None:  # chronological: before the first later shot (skipping flashbacks/assets)
            pt = clip_time(it["clip"])
            for i, c in enumerate(clips):
                ct = clip_time(c["clip"])
                if ct and c.get("style") != "flashback" and c.get("chapter") != "OUTRO" and ct > pt:
                    pos = i; break
            if pos is None:
                pos = len(clips)
        # never split a running clip: move past shots that continue the same source clip
        while 0 < pos < len(clips) and clips[pos]["clip"] == clips[pos - 1]["clip"]:
            pos += 1
        shot["chapter"] = clips[pos - 1]["chapter"] if pos > 0 else clips[0]["chapter"]
        if shot.get("speed") is None and it.get("speed") not in (None, 1, 1.0):
            shot["speed"] = float(it["speed"])
        clips.insert(pos, shot)
        if it.get("after_clip"):
            last_after[it["after_clip"]] = shot
        log.append(f"phone {it['clip']} {shot['in']:.1f}-{shot['out']:.1f} at #{pos} ({shot['chapter']})")
    return log


def apply_rhythm(clips: list[dict], plans: list[dict]) -> list[str]:
    """Cutaways (picture over talk), music breaths (inserted shots) and unmuting, from analysis/rhythm_*.json."""
    log, by_id = [], {c.get("id"): c for c in clips}
    for plan in plans:
        for u in plan.get("speech_to_unmute", []):
            c = by_id.get(u.get("shot"))
            if c and c["clip"] == u.get("clip", c["clip"]) and c.get("audio") != "keep" and c.get("style") != "flashback":
                c["audio"] = "keep"; log.append(f"unmute {c['clip']}")
        for cw in plan.get("cutaways", []):
            c = by_id.get(cw.get("shot"))
            if not c or c["clip"] != cw.get("talk_clip", c["clip"]) or not float(c["in"]) <= float(cw["at"]) < float(c["out"]):
                c = next((x for x in clips if x["clip"] == cw.get("talk_clip") and float(x["in"]) <= float(cw["at"]) < float(x["out"])), None)
            if not c:
                log.append(f"cutaway skipped (shot not found) {cw}"); continue
            st = float(cw["at"]) - float(c["in"])
            shot_len = float(c["out"]) - float(c["in"])
            du = min(float(cw["dur"]), shot_len - st - 1.0)
            if (st < 1.5 and not cw.get("privacy")) or du < 1.0:
                log.append(f"cutaway skipped (too close to edges) {c['clip']}@{cw['at']}"); continue
            item = {"clip": cw["clip"], "in": float(cw["in"]), "dur": round(du, 3), "start": round(st, 3)}
            if cw.get("crop"):
                item["crop"] = cw["crop"]
            c.setdefault("cutaways", []).append(item); log.append(f"cutaway {cw['clip']} over {c['clip']}@{cw['at']}")
        for br in plan.get("breaths", []):
            anchor = by_id.get(br.get("after_shot"))
            if anchor is None or anchor not in clips:
                log.append(f"breath skipped (anchor) {br.get('after_shot')}"); continue
            j = clips.index(anchor) + 1
            # never split a running flashback/rewind sequence or a jump cut of the same clip
            at_ = clip_time(anchor["clip"])
            keep_shots = []
            for s in br["shots"]:
                st_ = clip_time(s["clip"])
                same_place = place_of(s["clip"]) == place_of(anchor["clip"])
                same_day = st_[:10] == at_[:10]
                not_earlier = st_ >= at_[:11] + f"{max(0, int(at_[11:13]) - 1):02d}" + at_[13:] if at_ else True
                if same_place and same_day and not_earlier:
                    keep_shots.append(s)
                else:
                    log.append(f"breath shot dropped (chronology) {s['clip']} after {anchor['clip']}")
            if len(keep_shots) < 2:
                log.append(f"breath dropped (chronology) after {br.get('after_shot')}"); continue
            new = [{"clip": s["clip"], "in": float(s["in"]), "out": float(s["out"]), "audio": "ambient", "lock": True,
                    "chapter": anchor["chapter"], "desc": "BREATH " + br.get("why", "")[:60]} for s in keep_shots]
            clips[j:j] = new; log.append(f"breath {len(new)} shots after {br['after_shot']}")
    return log


def apply_facts(clips: list[dict], facts: list[dict]) -> list[str]:
    """Documentary info cards right after each chapter title (or on the next long enough shot)."""
    log, fps = [], 30000 / 1001
    for fc in facts:
        if fc.get("clip"):  # anchored card (transit city / airport): on the shot showing that moment
            at = float(fc.get("at", 0))
            c = next((c for c in clips if c["clip"] == fc["clip"] and float(c["in"]) - 0.5 <= at < float(c["out"]) - 3.5
                      and not c.get("freeze") and c.get("style") != "flashback"), None)
            if c is None:
                log.append(f"info skipped (anchor not in cut) {fc['clip']}@{at}"); continue
            st = max(0.2, at - float(c["in"]))
            ln = float(c["out"]) - float(c["in"])
            c.setdefault("fx", []).append({"type": "info", "stats": fc.get("stats", ""), "fact": fc.get("fact", ""),
                                           "start": round(st, 2), "dur": round(min(6.5, ln - st - 0.2), 2)})
            log.append(f"info {fc.get('place', fc['clip'])} on {c['clip']}")
            continue
        ch = [c for c in clips if c.get("chapter") == fc["chapter"]]
        if not ch:
            log.append(f"info skipped (no chapter) {fc['chapter']}"); continue
        start_i = next((i for i, c in enumerate(ch) if c.get("title")), 0)
        placed = False
        for k, c in enumerate(ch[start_i:]):
            if c.get("freeze") or c.get("style") == "flashback" or c["clip"].startswith("file:"):
                continue
            ln = (float(c["out"]) - float(c["in"])) / float(c.get("speed", 1))
            st = (float(c["title"]["start"]) + float(c["title"]["dur"]) + 0.3) if c.get("title") else 0.6
            if ln - st >= 5.2:
                c.setdefault("fx", []).append({"type": "info", "stats": fc.get("stats", ""), "fact": fc.get("fact", ""),
                                               "start": round(st, 2), "dur": round(min(6.5, ln - st - 0.3), 2)})
                log.append(f"info {fc['chapter']} on {c['clip']}"); placed = True
                break
        if not placed:  # a chapter of short photos: hold the first photo after the title long enough to read the card
            ph = next((c for c in ch[start_i:] if c["clip"].startswith("PHOTO:") and not c.get("title")), None)
            if ph is not None:
                ph["out"] = max(float(ph["out"]), 6.4)
                ph.setdefault("fx", []).append({"type": "info", "stats": fc.get("stats", ""), "fact": fc.get("fact", ""),
                                                "start": 0.5, "dur": 5.6})
                ph["lock"] = True  # the beat snap must not shorten it under the card
                log.append(f"info {fc['chapter']} on photo {ph['clip']} (held 6.4 s)")
            else:
                log.append(f"info skipped (no long shot) {fc['chapter']}")
    return log


_FACE_CACHE_PATH = PROJECT / "analysis" / "face_cache.json"
_face_cache = None


def is_selfie(clip: str, a: float, b: float) -> bool:
    """True when a large face (close to the GoPro) is visible in most sampled frames of [a, b]."""
    global _face_cache
    import subprocess
    if _face_cache is None:
        _face_cache = json.loads(_FACE_CACHE_PATH.read_text()) if _FACE_CACHE_PATH.exists() else {}
    key = f"{clip}:{a:.2f}:{b:.2f}"
    if key in _face_cache:
        return _face_cache[key]
    import cv2
    import numpy as np
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    src = src_path(clip)
    hits, centers = 0, []
    times = [a + (b - a) * k / 6 for k in range(1, 6)]
    for t in times:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-vf",
                              "scale=424:240,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        if len(raw) < 424 * 240:
            continue
        img = np.frombuffer(raw[:424 * 240], dtype=np.uint8).reshape(240, 424)
        faces = det.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        if len(faces) and max(fh for (_, _, _, fh) in faces) >= 0.17 * 240:
            hits += 1
            fx_, fy_, fw_, fh_ = max(faces, key=lambda f: f[3])
            centers.append(((fx_ + fw_ / 2) / 424, (fy_ + fh_ / 2) / 240))
    res = hits >= 3
    if res and centers:
        _face_cache[key + ":center"] = [sorted(c[0] for c in centers)[len(centers) // 2],
                                         sorted(c[1] for c in centers)[len(centers) // 2]]
    _face_cache[key] = res
    _FACE_CACHE_PATH.write_text(json.dumps(_face_cache))
    return res


def jump_zoom(clips: list[dict], min_len: float = 16.0, every: float = 7.5) -> list[str]:
    """Split long selfie-talk shots at sentence pauses and alternate a gentle punch-in (vlog jump zoom)."""
    log, out = [], []
    for c in clips:
        ln = float(c["out"]) - float(c["in"])
        if (c.get("audio") != "keep" or ln < min_len or c.get("crop") or c.get("framing") or c.get("freeze")
                or c.get("style") == "flashback" or c["clip"].startswith("file:") or c.get("no_zoom") or c.get("quad")):
            out.append(c); continue
        ws = load_words(c["clip"])
        if not ws or not is_selfie(c["clip"], float(c["in"]), float(c["out"])):
            out.append(c); continue
        a, b = float(c["in"]), float(c["out"])
        busy = []
        for cw in c.get("cutaways", []):
            busy.append((a + float(cw["start"]) - 0.4, a + float(cw["start"]) + float(cw["dur"]) + 0.4))
        for fx in c.get("fx", []):
            busy.append((a + float(fx.get("start", 0)) - 0.3, a + float(fx.get("start", 0)) + float(fx.get("dur", 2)) + 0.3))
        if c.get("title"):
            busy.append((a, a + float(c["title"]["start"]) + float(c["title"]["dur"]) + 0.3))
        if c.get("label"):
            busy.append((a + float(c["label"].get("start", 0)) - 0.3, a + float(c["label"].get("start", 0)) + float(c["label"].get("dur", 3)) + 0.3))
        cands = []
        for i in range(len(ws) - 1):
            gap = ws[i + 1]["s"] - ws[i]["e"]
            if gap >= 0.22 or ws[i]["w"].strip().endswith(END_PUNCT + (",",)):
                t = round(ws[i]["e"] + min(gap, 0.4) / 2, 3)
                if a + 5.0 <= t <= b - 4.0 and not any(x <= t <= y for x, y in busy):
                    cands.append(t)
        splits, last = [], a
        for t in cands:
            if t - last >= every:
                splits.append(t); last = t
        if not splits:
            out.append(c); continue
        bounds = [a] + splits + [b]
        for k in range(len(bounds) - 1):
            p0, p1 = bounds[k], bounds[k + 1]
            piece = {kk: v for kk, v in c.items() if kk not in ("fx", "cutaways", "title", "label")}
            piece.update({"in": round(p0, 3), "out": round(p1, 3), "lock": True, "gain_range": [a, b],
                          "seamless_in": k > 0, "seamless_out": k < len(bounds) - 2})
            if k % 2 == 1:
                cx, cy = (_face_cache or {}).get(f"{c['clip']}:{a:.2f}:{b:.2f}:center", [0.5, 0.45])
                piece["crop"] = [round(min(max(cx - 0.44, 0.0), 0.12), 3), round(min(max(cy - 0.40, 0.0), 0.12), 3), 0.88, 0.88]
            for key in ("fx", "cutaways"):
                items = [dict(it, start=round(a + float(it["start"]) - p0, 3)) for it in c.get(key, [])
                         if p0 <= a + float(it["start"]) < p1]
                if items:
                    piece[key] = items
            if k == 0 and c.get("title"):
                piece["title"] = c["title"]
            if c.get("label") and p0 <= a + float(c["label"].get("start", 0)) < p1:
                piece["label"] = dict(c["label"], start=round(a + float(c["label"].get("start", 0)) - p0, 3))
            out.append(piece)
        log.append(f"zoom {c['clip']} {a:.1f}-{b:.1f}: {len(splits)} cuts")
    clips[:] = out
    return log


def apply_quads(clips: list[dict], quads: list[dict]) -> list[str]:
    """Replace [from, to] of a shot with a synced 2x2 split screen (panel 0 = the shot's own clip, real time)."""
    log = []
    for q in quads:
        a, b = float(q["from"]), float(q["to"])
        hits = [c for c in clips if c["clip"] == q["clip"] and float(c["out"]) > a and float(c["in"]) < b
                and c.get("style") != "flashback" and not c.get("freeze")]
        if not hits:
            log.append(f"quad skipped (not in cut) {q['clip']}"); continue
        i0, i1 = clips.index(hits[0]), clips.index(hits[-1])
        first, last = clips[i0], clips[i1]
        new = []
        if float(first["in"]) < a - 0.3:
            pre = dict(first, out=a, lock=True, seamless_out=True)
            pre["cutaways"] = [cw for cw in first.get("cutaways", []) if float(first["in"]) + float(cw["start"]) + float(cw["dur"]) <= a]
            pre["fx"] = [x for x in first.get("fx", []) if float(first["in"]) + float(x.get("start", 0)) < a - 1]
            new.append(pre)
        mid = {"clip": q["clip"], "in": a, "out": b, "audio": "keep", "lock": True, "no_zoom": True,
               "fx": list(q.get("fx", [])), "chapter": first.get("chapter"),
               "seamless_in": True, "seamless_out": True, "desc": ("RELAY: " if q.get("relay") else "QUAD: ") + q.get("why", "")}
        if q.get("relay"):
            # one continuous walk that changes person/day on every cut: the host's own sound runs under it,
            # other takes come in as cutaways at the same point of the route, each with a small who/when tag
            mid["cutaways"] = [{"clip": r["clip"], "in": r["in"], "dur": round(r["to"] - r["from"], 3), "start": round(r["from"] - a, 3)}
                               for r in q["relay"] if r["clip"] != q["clip"]]
            mid["fx"] += [{"type": "tag", "text": r["tag"], "start": round(r["from"] - a, 3), "dur": round(r["to"] - r["from"], 3),
                           "size": 50, "fade": 0.08} for r in q["relay"]]  # big enough at 540p, no fade on short pieces
        else:
            mid["quad"] = q["quad"]
        new.append(mid)
        if float(last["out"]) > b + 0.3:
            post = dict(last, **{"in": b, "lock": True, "seamless_in": True})
            post["cutaways"] = [dict(cw, start=round(float(last["in"]) + float(cw["start"]) - b, 3)) for cw in last.get("cutaways", [])
                                if float(last["in"]) + float(cw["start"]) >= b]
            post["fx"] = [dict(x, start=round(float(last["in"]) + float(x.get("start", 0)) - b, 3)) for x in last.get("fx", [])
                          if float(last["in"]) + float(x.get("start", 0)) >= b]
            post.pop("title", None)
            new.append(post)
        clips[i0:i1 + 1] = new
        log.append(f"quad {q['clip']} {a}-{b}")
    return log


_ONSETS = None


def audio_onset(clip: str) -> float:
    """Seconds of digital silence at the head of a clip's audio (GoPro/phone files start with ~0.2 s)."""
    global _ONSETS
    import re as _re
    import subprocess as _sp
    cache = PROJECT / "analysis" / "audio_onset.json"
    if _ONSETS is None:
        _ONSETS = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    if clip not in _ONSETS:
        src = src_path(clip)
        r = _sp.run(["ffmpeg", "-hide_banner", "-nostats", "-t", "1.0", "-i", str(src), "-vn", "-af",
                     "silencedetect=n=-70dB:d=0.05", "-f", "null", "-"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace").stderr
        st = _re.findall(r"silence_start: (-?[\d.]+)", r)
        en = _re.findall(r"silence_end: ([\d.]+)", r)
        _ONSETS[clip] = round(max(0.0, float(en[0]) - 0.02), 3) if st and float(st[0]) <= 0.01 and en else 0.0
        cache.write_text(json.dumps(_ONSETS, indent=0), encoding="utf-8")
    return float(_ONSETS[clip])


def reanchor(c: dict, old_in: float, old_out: float) -> None:
    """A shot's overlays and cutaways are timed from its IN point: when a fix moves IN or OUT, keep them on the same
    source moment, trim what now hangs over an edge, and drop what fell outside the shot."""
    sp = float(c.get("speed", 1.0))
    delta = (float(c["in"]) - old_in) / sp
    dur = (float(c["out"]) - float(c["in"])) / sp
    if abs(delta) < 1e-6 and abs(float(c["out"]) - old_out) < 1e-6:
        return

    def fit(x: dict) -> bool:
        st = float(x.get("start", 0)) - delta
        en = st + float(x.get("dur", 0))
        st, en = max(0.0, st), min(dur, en)
        if en - st < 0.6:
            return False
        x["start"], x["dur"] = round(st, 3), round(en - st, 3)
        return True

    if c.get("fx"):
        c["fx"] = [x for x in c["fx"] if fit(x)]
    if c.get("cutaways"):
        kept = []
        for cw in c["cutaways"]:
            st0 = float(cw["start"])
            if fit(cw):
                cw["in"] = round(float(cw["in"]) + (float(cw["start"]) - (st0 - delta)), 3)  # trimmed head moves the source in
                kept.append(cw)
        c["cutaways"] = kept
    for k in ("title", "label"):
        if c.get(k) and not fit(c[k]):
            c.pop(k)


def apply_late_fixes(clips: list[dict], ops: list[dict]) -> list[str]:
    """Reviewer fixes applied last. A shot is found by clip + a source time inside it (`at`), never by position."""
    log = []

    def find(ref):
        hits = [c for c in clips if c["clip"] == ref["clip"] and float(c["in"]) - 0.06 <= float(ref["at"]) < float(c["out"]) + 0.06]
        k = int(ref.get("occurrence", 1)) - 1
        if len(hits) > k:
            return hits[k]
        return hits[0] if len(hits) == 1 else None  # 'occurrence' counted every use of the clip: one shot holds 'at'


    def fx_match(c, op):
        return [x for x in c.get("fx", []) if x.get("type") == op.get("type")
                and (not op.get("contains") or op["contains"] in " ".join(str(x.get(f, "")) for f in ("text", "stats", "fact", "kicker")))
                and (op.get("start") is None or abs(float(x.get("start", 0)) - float(op["start"])) < 0.2)]

    def cw_match(c, op):
        return [cw for cw in c.get("cutaways", []) if cw["clip"] == op["cw_clip"] and abs(float(cw["in"]) - float(op["cw_in"])) < 0.1]

    def put(d, changes):
        for k, v in changes.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v

    for op in ops:
        kind, tag = op["op"], f"{op['op']} {op.get('clip', '')}@{op.get('at', '')} {op.get('why', '')[:60]}"
        c = find(op) if "clip" in op else None
        if "clip" in op and c is None:
            log.append(f"NOT APPLIED (shot not found) {tag}"); continue
        if kind == "set":
            old_in, old_out = float(c["in"]), float(c["out"])
            put(c, op["set"])
            reanchor(c, old_in, old_out)
        elif kind == "drop":
            j = clips.index(c)
            nxt = clips[j + 1] if j + 1 < len(clips) and clips[j + 1]["chapter"] == c["chapter"] else None
            if c.get("title") and nxt is not None and not nxt.get("title"):  # the chapter title survives the drop
                nxt["title"] = c["title"]
                if (float(nxt["out"]) - float(nxt["in"])) < 3.6 and nxt["clip"].startswith("PHOTO:"):
                    nxt["out"] = float(nxt["in"]) + 4.0
            clips.remove(c)
        elif kind in ("move_after", "move_before"):
            t = find(op["to"])
            if t is None or t is c:
                log.append(f"NOT APPLIED (target not found) {tag}"); continue
            clips.remove(c)
            j = clips.index(t)
            clips.insert(j + 1 if kind == "move_after" else j, c)
            c["chapter"] = t["chapter"]
        elif kind == "insert_after":
            t = find(op["to"])
            if t is None:
                log.append(f"NOT APPLIED (target not found) {tag}"); continue
            clips.insert(clips.index(t) + 1, dict(op["shot"], chapter=t["chapter"]))
        elif kind == "cw_remove" or kind == "cw_set":
            m = cw_match(c, op)
            if not m:
                log.append(f"NOT APPLIED (cutaway not found) {tag}"); continue
            for cw in m[:1]:
                if kind == "cw_remove":
                    c["fx"] = [x for x in c.get("fx", []) if not (x.get("memory") and abs(float(x["start"]) - float(cw["start"])) < 0.05)]
                    c["cutaways"].remove(cw)
                else:
                    for x in c.get("fx", []):  # the memory tag moves with its cutaway
                        if x.get("memory") and abs(float(x["start"]) - float(cw["start"])) < 0.05:
                            put(x, {k: v for k, v in op["set"].items() if k in ("start", "dur")})
                    put(cw, op["set"])
        elif kind == "cw_add":
            c.setdefault("cutaways", []).append(op["cw"])
        elif kind in ("fx_remove", "fx_set"):
            m = fx_match(c, op)
            if not m:
                log.append(f"NOT APPLIED (overlay not found) {tag}"); continue
            for x in m[:1] if not op.get("all") else m:
                if kind == "fx_remove":
                    c["fx"].remove(x)
                else:
                    put(x, op["set"])
        elif kind == "fx_add":
            c.setdefault("fx", []).append(op["fx"])
        elif kind == "title_move":
            t = find(op["to"])
            if t is None or not c.get("title"):
                log.append(f"NOT APPLIED (title move) {tag}"); continue
            t["title"] = {**c.pop("title"), **op.get("set", {})}
        else:
            log.append(f"NOT APPLIED (unknown op) {tag}"); continue
        log.append(f"ok {tag}")
    return log


def short_units(clips: list[dict]) -> list[tuple[str, list[int]]]:
    """Units for the short cut: runs of consecutive shots of the same clip (never split a sentence or a jump-zoom run)."""
    units = []
    for i, c in enumerate(clips):
        if units and clips[units[-1][1][-1]]["clip"] == c["clip"]:
            units[-1][1].append(i)
        else:
            units.append((f"{c['clip']}@{float(c['in']):.2f}", [i]))
    seen = {}
    for n, (key, idx) in enumerate(units):  # the same clip range can appear twice (e.g. a later flashback)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            units[n] = (f"{key}#{seen[key]}", idx)
    return units


def apply_short(clips: list[dict], keep: set[str]) -> list[dict]:
    """Keep only the chosen units; a dropped chapter title moves to the chapter's first kept shot."""
    kept, titles = [], {}
    for key, idx in short_units(clips):
        for i in idx:
            if clips[i].get("title"):
                titles.setdefault(clips[i]["chapter"], clips[i]["title"])
        if key in keep:
            kept += [clips[i] for i in idx]
    seen = set()
    for c in kept:
        if c["chapter"] not in seen:
            seen.add(c["chapter"])
            if titles.get(c["chapter"]) and not any(k.get("title") for k in kept if k["chapter"] == c["chapter"]):
                dur = (float(c["out"]) - float(c["in"])) / float(c.get("speed", 1))
                c["title"] = {**titles[c["chapter"]], "dur": min(titles[c["chapter"]]["dur"], max(1.5, dur - 0.6))}
                c.pop("label", None)
    for n, c in enumerate(kept, 1):
        c["id"] = f"s{n:03d}"
    return kept


def shot_from(spec, moments) -> dict:
    if isinstance(spec, str):
        spec = {"ref": spec}
    base: dict = {}
    if "ref" in spec:
        m = moments.get(spec["ref"])
        if m is None:
            raise SystemExit(f"unknown moment {spec['ref']}")
        base = {"clip": m["clip"], "in": float(m["src_in"]), "out": float(m["src_out"]),
                "audio": "keep" if m.get("keep_audio") else "ambient", "desc": m.get("description", "")}
    shot = {**base, **{k: v for k, v in spec.items() if k != "ref"}}
    if isinstance(shot.get("label"), str):
        shot["label"] = {"text": shot["label"], "start": 0.4, "dur": min(3.0, (shot["out"] - shot["in"]) - 0.5)}
    shot["ref"] = spec.get("ref", "")
    return shot


def beat_grid(track: str) -> list[float]:
    """Strong beats of a track (half time when the detected tempo is above 140 BPM)."""
    p = PROJECT / "analysis" / "music" / "beats" / f"{track}.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    beats, down = d["beats"], set(d.get("downbeats", []))
    if d.get("bpm", 0) > 140 and beats:
        i0 = next((i for i, b in enumerate(beats) if b in down), 0)
        return [b for i, b in enumerate(beats) if (i - i0) % 2 == 0]
    return beats


def beat_snap(clips: list[dict], chapters_out: list, durations: dict, tol: float = 0.35) -> list[str]:
    """Walk the film in order; for every non-speech shot move its OUT point to the nearest strong beat of the cue
    playing at that moment. Photos stretch or shrink (1.5–6.5 s), videos/lives only shrink or grow into spare
    source, speech shots and locked/asset shots never move. Cue start = start of the chapter that starts the track."""
    log = []
    ch_of = {ch["name"]: ch for ch, _, _ in chapters_out}
    t, cue = 0.0, None  # cue = (grid, film time of track second src_in, src_in)
    cur_ch = None
    for i, c in enumerate(clips):
        if c["chapter"] != cur_ch:
            cur_ch = c["chapter"]
            ch = ch_of.get(cur_ch, {})
            track = ch.get("music")
            if track in (None, "none"):
                cue = None
            elif track != "continue" or cue is None:
                cue = (beat_grid(track), t + float(ch.get("music_start_offset", 0)), float(ch.get("music_in", 0)))
        sp = float(c.get("speed", 1.0))
        d = (float(c["out"]) - float(c["in"])) / sp
        movable = (cue and cue[0] and c.get("audio") != "keep" and not c["clip"].startswith("file:")
                   and not c.get("lock") and not c.get("freeze") and not c.get("quad")
                   and not (i + 1 < len(clips) and clips[i + 1]["clip"] == c["clip"]))  # keep jump-cut pairs intact
        if movable:
            grid, t0, src_in = cue
            end = t + d
            nearest = min(grid, key=lambda b: abs(t0 + b - src_in - end))
            delta = (t0 + nearest - src_in) - end
            if abs(delta) <= tol and abs(delta) > 1 / 60:
                is_photo = c["clip"].startswith("PHOTO:")
                new_d = d + delta
                room = durations.get(c["clip"], 1e9) - float(c["out"]) - 0.05
                ok = (1.5 <= new_d <= 6.5) if is_photo else (new_d >= 1.2 and (delta < 0 or delta * sp <= room))
                if ok:
                    c["out"] = round(float(c["out"]) + delta * sp, 3)
                    d = new_d
                    log.append(f"snap {c['id']} {c['clip']} {delta:+.2f}s -> cut at {end + delta:.2f}")
                else:
                    log.append(f"skip {c['id']} {c['clip']} {delta:+.2f}s (no room)")
        t += round(d * FPS) / FPS
    return log


def frames(c) -> int:
    return max(1, round((float(c["out"]) - float(c["in"])) / float(c.get("speed", 1.0)) * FPS))


def main(edl_path: str, out_path: str, short: str | None = None) -> None:
    edl = json.loads(Path(edl_path).read_text(encoding="utf-8"))
    moments = load_moments()
    lufs = music_loudness()
    clips, chapters_out = [], []
    n = 0

    def add(shot, chapter):
        nonlocal n
        n += 1
        shot = dict(shot)
        shot["id"] = f"s{n:03d}"
        shot["chapter"] = chapter
        clips.append(shot)

    for s in edl.get("intro", []):
        add(shot_from(s, moments), "INTRO")
    inserts = edl.get("inserts", {})
    for ch in edl["chapters"]:
        first = len(clips)
        pre = inserts.get(ch["name"], [])
        if pre and ch.get("title"):
            ch = dict(ch, title_on=int(ch.get("title_on", 0)) + len(pre))
        for s in pre + ch["shots"]:
            add(shot_from(s, moments), ch["name"])
        if ch.get("title") and len(clips) > first:
            at = first + int(ch.get("title_on", 0))
            def _len(c_):
                return (float(c_["out"]) - float(c_["in"])) / float(c_.get("speed", 1))
            if _len(clips[at]) < 3.6:
                if clips[at]["clip"].startswith("PHOTO:"):
                    clips[at]["out"] = float(clips[at]["in"]) + 4.0
                    clips[at]["lock"] = True
                else:
                    nxt = next((k for k in range(at + 1, min(len(clips), at + 6)) if _len(clips[k]) >= 3.6), None)
                    if nxt is not None:
                        at = nxt
            dur = (float(clips[at]["out"]) - float(clips[at]["in"])) / float(clips[at].get("speed", 1))
            clips[at]["title"] = {**ch["title"], "start": ch["title"].get("start", 0.5),
                                  "dur": ch["title"].get("dur", min(4.0, dur - 0.6))}
            # never show a label on top of the chapter title
            c0 = clips[at]
            if c0.get("label"):
                dur0 = (float(c0["out"]) - float(c0["in"])) / float(c0.get("speed", 1))
                after = c0["title"]["start"] + c0["title"]["dur"] + 0.3
                if dur0 - after >= 2.0:
                    c0["label"] = {**c0["label"], "start": after, "dur": min(2.6, dur0 - after - 0.2)}
                else:
                    c0.pop("label")
        chapters_out.append((ch, first, len(clips)))
    for s in edl.get("outro", []):
        add(shot_from(s, moments), "OUTRO")

    # per-clip overrides (e.g. reframing a shot wherever it is used)
    for c in clips:
        for k, v in edl.get("overrides", {}).get(c["clip"], {}).items():
            c[k] = v

    # per-camera grade: edl "grade_by_camera" {"<word in the catalog camera name>": "<ffmpeg filter>"}
    import csv
    cams = {r["id"]: r["camera"] for r in csv.DictReader(open(PROJECT / "analysis" / "catalog.csv", encoding="utf-8"))}
    gbc = edl.get("grade_by_camera", {})
    for c in clips:
        key = c["clip"][6:] if c["clip"].startswith("PHOTO:") else c["clip"]
        cam = cams.get(key, "").split(" ")[0].lower()
        if gbc.get(cam) and not c.get("grade"):
            c["grade"] = gbc[cam]

    # voice isolation (tools/clean_voice.py): noisy speech shots read the Demucs track
    cv = PROJECT / "analysis" / "clean_voice.json"
    if cv.exists():
        use = {k for k, v in json.loads(cv.read_text(encoding="utf-8")).items() if v.get("use")}
        for c in clips:
            if c.get("audio") == "keep" and c["clip"] in use and "clean_audio" not in c:
                c["clean_audio"] = True

    # never cut a sentence (word-level transcripts)
    durations = {r["id"]: float(r["duration"]) for r in csv.DictReader(open(PROJECT / "analysis" / "catalog.csv", encoding="utf-8"))
                 if r["duration"]}
    snapped = snap_speech(clips, durations)
    if snapped:
        (PROJECT / "analysis" / "snap_log.txt").write_text(chr(10).join(snapped), encoding="utf-8")
        print(f"  snapped {len(snapped)} speech shots to sentence boundaries (analysis/snap_log.txt)")

    gpath = PROJECT / "analysis" / "graphics.json"
    if gpath.exists() and not edl.get("no_graphics"):
        glog = apply_graphics(clips, json.loads(gpath.read_text(encoding="utf-8")))
        (PROJECT / "analysis" / "graphics_log.txt").write_text(chr(10).join(glog), encoding="utf-8")
        print(f"  graphics: {sum(1 for l in glog if 'skipped' not in l)} inserts, {sum(1 for c in clips for _ in c.get('fx', []))} overlays, {sum(1 for l in glog if 'skipped' in l)} skipped")
        for n, c in enumerate(clips, 1):
            c["id"] = f"s{n:03d}"

    facts = [f for p in sorted((PROJECT / "analysis").glob("facts_f*.json")) for f in json.loads(p.read_text(encoding="utf-8"))]
    if facts:
        flog = apply_facts(clips, facts)
        print(f"  info cards: {sum(l.startswith('info ') for l in flog)} placed, {sum('skipped' in l for l in flog)} skipped")
        (PROJECT / "analysis" / "facts_log.txt").write_text(chr(10).join(flog), encoding="utf-8")

    rplans = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((PROJECT / "analysis").glob("rhythm_r*.json"))]
    if rplans and not edl.get("no_rhythm"):
        rlog = apply_rhythm(clips, rplans)
        (PROJECT / "analysis" / "rhythm_log.txt").write_text(chr(10).join(rlog), encoding="utf-8")
        print(f"  rhythm: {sum('cutaway ' in l for l in rlog)} cutaways, {sum(l.startswith('breath ') for l in rlog)} breaths, "
              f"{sum(l.startswith('unmute') for l in rlog)} unmuted, {sum('skipped' in l for l in rlog)} skipped")
        for n, c in enumerate(clips, 1):
            c["id"] = f"s{n:03d}"
        print(f"  memories: {mark_memories(clips)} cutaways from another place get the flashback look")

    # Review files (fixes/subtitles). Round reviews (review_r1_story.json …) hold "ops" that only reach the
    # film through late_fixes.json after the chief has reconciled them, so they are skipped here.
    import re as _re
    reviews = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((PROJECT / "analysis").glob("review_*.json"))
               if not _re.match(r"review_r\d", p.stem)]
    if reviews:
        vlog = apply_review_fixes(clips, reviews)
        (PROJECT / "analysis" / "review_log.txt").write_text(chr(10).join(vlog), encoding="utf-8")
        print(f"  review fixes: {sum(l.startswith('fix ') for l in vlog)} applied, {sum(l.startswith('MANUAL') for l in vlog)} manual, "
              f"{sum('skipped' in l or 'not found' in l for l in vlog)} not found")

    pplans = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((PROJECT / "analysis").glob("phone_j*.json"))]
    if pplans:
        plog = apply_phone(clips, pplans, durations)
        (PROJECT / "analysis" / "phone_log.txt").write_text(chr(10).join(plog), encoding="utf-8")
        print(f"  phone clips inserted: {len(plog)}")

    qpath = PROJECT / "analysis" / "quads.json"
    if qpath.exists():
        qlog = apply_quads(clips, json.loads(qpath.read_text(encoding="utf-8")))
        print("  " + "; ".join(qlog))

    if not edl.get("no_jump_zoom"):
        zlog = jump_zoom(clips)
        (PROJECT / "analysis" / "zoom_log.txt").write_text(chr(10).join(zlog), encoding="utf-8")
        print(f"  jump zoom: {len(zlog)} talk shots, {sum(int(l.split(': ')[1].split()[0]) for l in zlog)} zoom cuts")
        for n, c in enumerate(clips, 1):
            c["id"] = f"s{n:03d}"

    # place check: cutaways that showed another place than the one talked about (analysis/verify/place_fixes.json)
    pf = PROJECT / "analysis" / "verify" / "place_fixes.json"
    if pf.exists():
        done = 0
        for fx in json.loads(pf.read_text(encoding="utf-8")).get("fixes", []):
            # the same host/cutaway/in can occur twice in a row: `occurrence` picks which one (film order)
            matches = [(c, cw) for c in clips if c["clip"] == fx["host_clip"] for cw in c.get("cutaways", [])
                       if cw["clip"] == fx["cw_clip"] and abs(float(cw["in"]) - float(fx["cw_in"])) < 0.06]
            k = int(fx.get("occurrence", 1)) - 1
            for c, hit in matches[k:k + 1]:
                cws = c["cutaways"]
                # the memory tag ('⏪ place') belongs to the cutaway it labels
                c["fx"] = [x for x in c.get("fx", []) if not (x.get("memory") and abs(float(x["start"]) - float(hit["start"])) < 0.01)]
                if fx.get("action") == "replace" and fx.get("new_clip") and place_of(fx["new_clip"]) != place_of(c["clip"]):
                    c["fx"].append({"type": "flashback_tag", "text": place_of(fx["new_clip"]), "start": hit["start"],
                                    "dur": min(float(fx.get("new_dur", hit["dur"])), float(hit["dur"])), "memory": True})
                if fx.get("action") == "replace" and fx.get("new_clip"):
                    hit.update({"clip": fx["new_clip"], "in": float(fx["new_in"]),
                                "dur": min(float(fx.get("new_dur", hit["dur"])), float(hit["dur"]))})
                    if place_of(fx["new_clip"]) == place_of(c["clip"]):
                        hit.pop("style", None)
                    else:
                        hit["style"] = "flashback"
                else:
                    cws.remove(hit)
                done += 1
        print(f"  place fixes: {done} applied")

    # GoPro and phone files open with ~0.2 s of digital silence: a speech shot starting there leaves a hole.
    # Start such shots where the sound actually begins (measured per clip, cached).
    for c in clips:
        if c.get("audio") == "keep" and not c["clip"].startswith(("file:", "PHOTO:")) and float(c["in"]) < 0.3                 and not c.get("quad") and not c.get("freeze"):
            on = audio_onset(c["clip"])
            if on > float(c["in"]) + 0.02 and float(c["out"]) - on > 1.0:
                shift = round(on - float(c["in"]), 3)
                c["in"] = on
                for cw in c.get("cutaways", []):
                    cw["start"] = round(max(0.0, float(cw["start"]) - shift), 3)
                for x in c.get("fx", []):
                    x["start"] = round(max(0.0, float(x.get("start", 0)) - shift), 3)
                for k in ("title", "label"):
                    if c.get(k):
                        c[k] = {**c[k], "start": max(0.0, float(c[k].get("start", 0.4)) - shift)}

    # voice gain overrides also reach shots added after the first override pass (phone inserts, breaths)
    for c in clips:
        g = edl.get("overrides", {}).get(c["clip"], {}).get("audio_gain")
        if g is not None and c.get("audio") == "keep":
            c["audio_gain"] = g

    # a memory tag without its graded cutaway (dropped or moved by an earlier pass) would label the wrong picture
    for c in clips:
        starts = [float(cw["start"]) for cw in c.get("cutaways", []) if cw.get("style") == "flashback"]
        if c.get("fx"):
            c["fx"] = [x for x in c["fx"] if not x.get("memory") or any(abs(float(x["start"]) - s) < 0.05 for s in starts)]

    # punch-ins: split a shot at `at` and reframe the rest (last, so no earlier pass sees the extra shot)
    for p in edl.get("punch_ins", []):
        i = next((i for i, c in enumerate(clips) if c["clip"] == p["clip"] and float(c["in"]) < float(p["at"]) < float(c["out"])), None)
        if i is None:
            print(f"  punch-in not found: {p['clip']} @ {p['at']}"); continue
        a = clips[i]
        b = {k: v for k, v in a.items() if k not in ("title", "label", "fx", "cutaways")}
        b.update({"in": float(p["at"]), "crop": p["crop"], "no_zoom": True, "seamless_in": True, "desc": p.get("desc", a.get("desc", ""))})
        a.update({"out": float(p["at"]), "seamless_out": True})
        clips.insert(i + 1, b)
        print(f"  punch-in {p['clip']} @ {p['at']}")
    for n, c in enumerate(clips, 1):
        c["id"] = f"s{n:03d}"

    if reviews:
        print(f"  subtitles: {apply_subtitles(clips, reviews)} placed")

    lpath = PROJECT / "analysis" / "late_fixes.json"
    if lpath.exists():
        llog = apply_late_fixes(clips, json.loads(lpath.read_text(encoding="utf-8")).get("ops", []))
        (PROJECT / "analysis" / "late_fixes_log.txt").write_text(chr(10).join(llog), encoding="utf-8")
        # subtitles are re-placed from their source times on the final shots (fixes moved in/out points and added shots)
        for c in clips:
            if c.get("fx"):
                c["fx"] = [x for x in c["fx"] if x.get("type") != "subtitle"]
        sub_reviews = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((PROJECT / "analysis").glob("review_*.json"))
                       if not _re.match(r"review_r\d", p.stem)]
        print(f"  subtitles re-placed after fixes: {apply_subtitles(clips, sub_reviews)}")
        bad = [l for l in llog if l.startswith("NOT APPLIED")]
        print(f"  late fixes: {len(llog) - len(bad)} applied, {len(bad)} not applied")
        for n, c in enumerate(clips, 1):
            c["id"] = f"s{n:03d}"

    # a chapter title never shares the screen with a subtitle: slide it to a quiet moment of its shot, else to the next
    # quiet shot of the chapter (title and subtitles both live in the lower part of the frame)
    def _subs(c_):
        return [(float(x["start"]), float(x["start"]) + float(x["dur"])) for x in c_.get("fx", []) if x.get("type") == "subtitle"]

    def _quiet(c_, need=3.0):
        ln = (float(c_["out"]) - float(c_["in"])) / float(c_.get("speed", 1.0))
        subs = sorted(_subs(c_))
        t = 0.3
        while t + need <= ln - 0.2:
            hit = [b for a, b in subs if a < t + need + 0.2 and t - 0.2 < b]
            if not hit:
                return t
            t = max(hit) + 0.25
        return None

    for i, c in enumerate(clips):
        if not c.get("title") or not _subs(c):
            continue
        tt = (float(c["title"].get("start", 0.5)), float(c["title"].get("start", 0.5)) + float(c["title"].get("dur", 3.6)))
        if not any(a < tt[1] and tt[0] < b for a, b in _subs(c)):
            continue
        t0 = _quiet(c)
        if t0 is not None:
            c["title"] = {**c["title"], "start": round(t0, 2), "dur": 3.0}
            print(f"  title {c['chapter']} moved to {t0:.1f}s of its shot (subtitles)")
            continue
        for j in range(i + 1, min(len(clips), i + 8)):
            d_ = clips[j]
            if d_["chapter"] != c["chapter"] or d_.get("title"):
                break
            t0 = _quiet(d_)
            if t0 is not None:
                d_["title"] = {**c["title"], "start": round(t0, 2), "dur": 3.0}
                c.pop("title")
                if d_.get("label"):
                    d_.pop("label")
                print(f"  title {d_['chapter']} moved to shot {d_['id']} {d_['clip']} (subtitles)")
                break
        else:
            print(f"  title {c['chapter']}: no quiet moment found")

    # subtitles own the bottom of the frame: labels, info cards and captions that overlap one in time move to the top
    for c in clips:
        subs = [(float(x["start"]), float(x["start"]) + float(x["dur"])) for x in c.get("fx", []) if x.get("type") == "subtitle"]
        if not subs:
            continue
        hit = lambda a, b: any(a < sb and sa < b for sa, sb in subs)
        for x in c.get("fx", []):
            if x.get("type") in ("info", "caption") and hit(float(x.get("start", 0)), float(x.get("start", 0)) + float(x.get("dur", 2))):
                x["pos"] = "top"
        lb = c.get("label")
        if lb and hit(float(lb.get("start", 0.4)), float(lb.get("start", 0.4)) + float(lb.get("dur", 3.0))):
            c["label"] = {**lb, "pos": "top"}

    # no flashes of the talking shot: close gaps under 0.9 s between cutaways and at the shot edges
    for c in clips:
        cws = sorted(c.get("cutaways", []), key=lambda cw: float(cw["start"]))
        if not cws:
            continue
        shot_len = (float(c["out"]) - float(c["in"])) / float(c.get("speed", 1.0))
        first = cws[0]
        if 0 < float(first["start"]) < 0.9:
            d = float(first["start"])
            first["start"] = 0.0
            first["dur"] = round(float(first["dur"]) + d, 3)
            for x in c.get("fx", []):
                if x.get("memory") and abs(float(x["start"]) - d) < 0.05:
                    x["start"], x["dur"] = 0.0, first["dur"]
        for a, b in zip(cws, cws[1:]):
            g = float(b["start"]) - (float(a["start"]) + float(a["dur"]))
            if 0 < g < 0.9:
                a["dur"] = round(float(a["dur"]) + g, 3)
        last = cws[-1]
        tail = shot_len - (float(last["start"]) + float(last["dur"]))
        if 0 < tail < 0.9:
            last["dur"] = round(float(last["dur"]) + tail, 3)
        c["cutaways"] = cws

    if short:
        keep = set(json.loads(Path(short).read_text(encoding="utf-8"))["keep"])
        known = {k for k, _ in short_units(clips)}
        for k in sorted(keep - known):
            print(f"  short cut: unknown unit {k}")
        clips[:] = apply_short(clips, keep)
        print(f"  short cut: kept {len(keep & known)} units, {len(clips)} shots")

    # first word of each speech shot (the music ducks from there, not from the cut)
    for i, c in enumerate(clips):
        c.pop("speech_from", None)
        if i and clips[i - 1].get("audio") == "keep":
            continue  # inside a run of speech the music stays down
        if c.get("audio") == "keep" and not c["clip"].startswith(("file:", "PHOTO:")) and not c.get("quad"):
            ws = [w for w in (load_words(c["clip"]) or []) if float(c["in"]) - 0.05 <= w["s"] < float(c["out"])]
            if ws and ws[0]["s"] - float(c["in"]) > 0.6:
                c["speech_from"] = round(ws[0]["s"] - float(c["in"]) - 0.3, 2)

    # seamless continuations: start exactly where the previous piece's frames end (no skipped or repeated audio),
    # and one voice gain for a whole run of the same clip (no level step in the middle of a sentence)
    for a, b in zip(clips, clips[1:]):
        if b["clip"] == a["clip"] and b.get("seamless_in") and abs(float(b["in"]) - float(a["out"])) < 0.05:
            b["in"] = round(float(a["in"]) + frames(a) / FPS * float(a.get("speed", 1.0)), 4)
    i = 0
    while i < len(clips):
        j = i
        while j + 1 < len(clips) and clips[j + 1]["clip"] == clips[i]["clip"] and clips[j + 1].get("audio") == "keep"                 and abs(float(clips[j + 1]["in"]) - float(clips[j]["out"])) < 0.1:
            j += 1
        if j > i and clips[i].get("audio") == "keep" and not clips[i]["clip"].startswith(("file:", "PHOTO:")):
            for c in clips[i:j + 1]:
                c.setdefault("gain_range", [float(clips[i]["in"]), float(clips[j]["out"])])
        i = j + 1

    # chapter ranges from the final shot list (the passes above inserted shots, so the build-time indices are stale)
    runs = {}
    for i, c in enumerate(clips):
        runs[c["chapter"]] = (runs.get(c["chapter"], (i, i))[0], i + 1)
    chapters_out = [(ch, *runs.get(ch["name"], (0, 0))) for ch, _, _ in chapters_out]

    # cut montages on the music: move each cut out of a non-speech shot to the nearest strong beat (±0.35 s)
    if not edl.get("no_beat_snap"):
        blog = beat_snap(clips, chapters_out, durations)
        (PROJECT / "analysis" / "beat_log.txt").write_text(chr(10).join(blog), encoding="utf-8")
        print(f"  beat snap: {sum(1 for x in blog if x.startswith('snap'))} cuts moved onto the beat")

    # timeline positions
    t, pos = 0.0, []
    for c in clips:
        d = frames(c) / FPS
        pos.append((t, t + d))
        t += d
    total = t

    # music: one entry per chapter run that starts a new track
    xf = float(edl.get("music_gap_fade", 1.2))
    music = []
    for ch, a, b in chapters_out:
        if a == b:
            continue
        start, end = pos[a][0], pos[b - 1][1]
        track = ch.get("music")
        if track in (None, "none"):
            continue
        if track == "continue" and music:
            music[-1]["end"] = end + (xf if b < len(clips) else 0)
            continue
        offset = float(ch.get("music_start_offset", 0))
        start += offset
        gain_db = BED_LUFS - lufs.get(track, -14.0) + float(ch.get("music_gain_db", 0))
        if music and music[-1]["end"] >= start - 0.05:
            # overlap with the previous track for a crossfade (not across a silent chapter such as the cold open)
            music[-1]["end"] = max(music[-1]["end"], start + xf)
            music[-1]["fade_out"] = xf
        music.append({"file": f"music/{track}.mp3", "src_in": float(ch.get("music_in", 0)),
                      "gain_db_extra": float(ch.get("music_gain_db", 0)),
                      "start": round(start, 3), "end": round(end, 3), "fade_in": xf if music else 0.6,
                      "fade_out": 2.5, "gain": round(10 ** (gain_db / 20), 3), "chapter": ch["name"],
                      **({"start_offset": offset} if offset else {})})
    lengths = music_length()
    # back-timed cues end on the track's real last bar: src_in = playable length - cue length
    bt = {ch["name"] for ch, _, _ in chapters_out if ch.get("music_backtime")}
    for m in music:
        if m["chapter"] in bt:
            track = Path(m["file"]).stem
            m["src_in"] = round(max(0.0, lengths.get(track, 0) - (m["end"] - m["start"]) - 0.7), 3)
            print(f"  music for {m['chapter']} back-timed: starts at {m['src_in']:.1f}s of {track}")
    # split cues that outlast their track: continue with the chapter's next track (or the same one again)
    nexts = {ch["name"]: list(ch.get("music_more", [])) for ch, _, _ in chapters_out}
    fixed = []
    for m in music:
        track = Path(m["file"]).stem
        avail = lengths.get(track, 999) - m["src_in"] - 0.5
        while m["end"] - m["start"] > avail:
            queue = nexts.get(m["chapter"]) or [track]
            nxt = queue.pop(0) if nexts.get(m["chapter"]) else track
            cut = m["start"] + avail
            first = dict(m, end=round(cut, 3), fade_out=xf)
            fixed.append(first)
            gain_db = BED_LUFS - lufs.get(nxt, -14.0)
            m = dict(m, file=f"music/{nxt}.mp3", src_in=0.0, start=round(cut - xf, 3), fade_in=xf,
                     gain=round(10 ** (gain_db / 20), 3))
            track = nxt
            avail = lengths.get(track, 999) - 0.5
            print(f"  music for {m['chapter']} continues with {nxt} at {cut:.1f}s")
        fixed.append(m)
    # no music snippets: a cue under 8 s starts and stops audibly, so the next cue takes its place
    for k in range(len(fixed) - 2, -1, -1):
        m, nxt = fixed[k], fixed[k + 1]
        if m["end"] - m["start"] < 8.0 and k > 0:
            nxt["start"] = m["start"]
            nxt["fade_in"] = max(float(nxt.get("fade_in", xf)), 1.0)
            nxt["early"] = True  # starts before its chapter on purpose (took over a snippet)
            fixed[k - 1]["end"] = max(fixed[k - 1]["end"], m["start"] + xf)
            del fixed[k]
    music = fixed
    if edl.get("music_end_at"):
        music[-1]["end"] = float(edl["music_end_at"])
    if music:
        music[-1]["end"] = min(music[-1]["end"], total)
        if edl.get("final_fade") is not None:
            music[-1]["fade_out"] = float(edl["final_fade"])

    # voice-over (generated): approved lines anchored to a shot by clip + source time, placed in film time
    voiceover, vlog = [], []
    nsp = PROJECT / "analysis" / "narration_script.json"
    if nsp.exists() and not edl.get("no_voiceover"):
        import subprocess as _sp
        items = json.loads(nsp.read_text(encoding="utf-8"))
        items = items if isinstance(items, list) else items.get("lines", [])
        for it in items:
            f = (config.WORK / "narration") / f"{int(it['n']):02d}.mp3"
            if not it.get("approved") or not f.exists():
                continue
            an = it["anchor"]
            names = {an["clip"], "PHOTO:" + an["clip"], an["clip"].removeprefix("PHOTO:")}
            cands = [i for i, c in enumerate(clips) if c["clip"] in names
                     and float(c["in"]) - 0.06 <= float(an["at"]) < float(c["out"]) + 0.06]
            want_t = it.get("film_time")
            if isinstance(want_t, str) and ":" in want_t:
                mm, ss = want_t.split(":"); want_t = int(mm) * 60 + float(ss)
            # a clip can be used twice (the flashback reuses frames): take the use nearest the writer's film time
            k = min(cands, key=lambda i: abs(pos[i][0] - float(want_t))) if cands and want_t is not None else (cands[0] if cands else None)
            if k is None:
                vlog.append(f"VO {it['n']} NOT PLACED (anchor shot gone) {an}"); continue
            dur = float(_sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True).stdout.strip() or 0)
            st = pos[k][0] + float(it.get("start", 0.5))
            # never under a chapter title (title and narration subtitle share the bottom of the frame)
            for c, (a_, b_) in zip(clips, pos):
                if c.get("title"):
                    t0 = a_ + float(c["title"].get("start", 0.5))
                    t1 = t0 + float(c["title"].get("dur", 3.6))
                    if t0 < st + dur and t1 > st:
                        vlog.append(f"VO {it['n']} moved after the title of {c['chapter']}")
                        st = t1 + 0.3
            talk = [c["id"] for c, (a_, b_) in zip(clips, pos) if c.get("audio") == "keep" and a_ < st + dur and b_ > st]
            if talk:
                vlog.append(f"VO {it['n']} overlaps speech shots {talk}: moved after them")
                st = max(b_ for c, (a_, b_) in zip(clips, pos) if c["id"] in talk) + 0.4
            voiceover.append({"n": it["n"], "file": str(f), "start": round(st, 3), "dur": round(dur, 3), "text": it["text"]})
            vlog.append(f"VO {it['n']} at {st:.1f}s ({dur:.1f}s): {it['text'][:60]}")
        # the narration gets subtitles like all speech in the film (two balanced lines, cut at the shot boundaries)
        for vo in voiceover:
            words = vo["text"].split()
            best = min(range(1, len(words)), key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:])))) if len(words) > 3 else len(words)
            text = " ".join(words[:best]) + (chr(10) + " ".join(words[best:]) if best < len(words) else "")
            a_, b_ = vo["start"], vo["start"] + vo["dur"] + 0.25
            for c, (s0, e0) in zip(clips, pos):
                lo, hi = max(a_, s0), min(b_, e0)
                if hi - lo >= 0.8:
                    c.setdefault("fx", []).append({"type": "subtitle", "text": text, "start": round(lo - s0, 3),
                                                   "dur": round(hi - lo, 3), "v": 2, "fade": 0.08, "narration": True})
                    st_, en_ = lo - s0, hi - s0  # a label or card in the bottom third moves up while the narration speaks
                    for x in ([c["label"]] if c.get("label") else []) + [x for x in c.get("fx", []) if x.get("type") in ("info", "caption")]:
                        xs, xe = float(x.get("start", 0)), float(x.get("start", 0)) + float(x.get("dur", 2))
                        if x.get("pos") != "top" and xs < en_ and st_ < xe:
                            x["pos"] = "top"
        (PROJECT / "analysis" / "voiceover_log.txt").write_text(chr(10).join(vlog), encoding="utf-8")
        if voiceover:
            print(f"  voice-over: {len(voiceover)} lines placed")

    film = {"format": {"fps_num": 30000, "fps_den": 1001}, "proxy_dir": str(config.PROXY), "jpg_dir": str(config.JPG),
            "grade": edl.get("grade", "eq=contrast=1.05:saturation=1.12"),
            "duck": edl.get("duck", {"level": 0.2, "ramp": 0.35, "pad": 0.15}),
            "audio": edl.get("audio", {"target_lufs": -14, "true_peak": -1.0, "ambient_gain": 0.12}),
            "clips": clips, "music": music, "music_level_lufs": edl.get("music_level_lufs", BED_LUFS),
            "voiceover": voiceover,
            "no_music": [[round(pos[a][0], 2), round(pos[b - 1][1], 2)] for ch, a, b in chapters_out
                         if a < b and ch.get("music") == "none"]}  # intentional silence (cold open voice, credits)
    Path(out_path).write_text(json.dumps(film, ensure_ascii=False, indent=1), encoding="utf-8")
    # human-readable cut list
    lines = [f"Total {total:.1f}s ({total / 60:.2f} min), {len(clips)} shots, {len(music)} music cues", ""]
    for c, (s, e) in zip(clips, pos):
        flag = "♪" if c.get("audio") == "keep" else " "
        ttl = f"  [TITLE {c['title']['text']}]" if c.get("title") else ""
        lbl = f"  [LABEL {c['label']['text']}]" if c.get("label") else ""
        lines.append(f"{int(s // 60):02d}:{s % 60:05.2f}  {e - s:5.2f}s {flag} {c['chapter']:<14} {c['clip']:<10} "
                     f"{float(c['in']):7.2f}-{float(c['out']):7.2f}  {c.get('desc', '')[:70]}{ttl}{lbl}")
    lines.append("")
    for m in music:
        lines.append(f"music {m['start']:7.2f}-{m['end']:7.2f}  {m['chapter']:<14} {m['file']}  gain {m['gain']}")
    Path(out_path).with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")
    print(lines[0])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
