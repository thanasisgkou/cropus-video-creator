"""Validate one chapter editor's EDL part and print its running time.
Usage: python tools/check_edl_part.py edl_part2.json
Checks: valid JSON, unique chapter names, every ref exists, every clip/still exists, in/out inside the source,
no source range used twice (across ALL edl_part*.json), titles and labels short enough.
"""
import csv
import glob
import json
import sys
from pathlib import Path

from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
cat = {r["id"]: r for r in csv.DictReader(open(ROOT / "analysis" / "catalog.csv", encoding="utf-8"))}
moments = {}
for p in sorted((ROOT / "analysis" / "directors").glob("d*.json")):
    for m in json.loads(p.read_text(encoding="utf-8")).get("moments", []):
        moments[f"{p.stem}:{m['id']}"] = m


def resolve(s):
    if isinstance(s, str):
        s = {"ref": s}
    base = {}
    if "ref" in s:
        m = moments.get(s["ref"])
        if m is None:
            return None, f"unknown ref {s['ref']}"
        base = {"clip": m["clip"], "in": float(m["src_in"]), "out": float(m["src_out"]),
                "audio": "keep" if m.get("keep_audio") else "ambient"}
    return {**base, **{k: v for k, v in s.items() if k != "ref"}}, None


def check(path: Path) -> tuple[list[str], float, list]:
    errs, total, used = [], 0.0, []
    data = json.loads(path.read_text(encoding="utf-8"))
    names = set()
    for ch in data.get("chapters", []):
        if ch["name"] in names:
            errs.append(f"duplicate chapter {ch['name']}")
        names.add(ch["name"])
        t = ch.get("title") or {}
        if t and len(t.get("text", "")) > 24:
            errs.append(f"{ch['name']}: title over 24 chars")
        ch_t = 0.0
        for k, s in enumerate(ch.get("shots", [])):
            sh, e = resolve(s)
            where = f"{ch['name']}#{k}"
            if e:
                errs.append(f"{where}: {e}")
                continue
            clip = sh.get("clip", "")
            a, b = float(sh.get("in", 0)), float(sh.get("out", 0))
            if b <= a:
                errs.append(f"{where}: out <= in")
            if clip.startswith("PHOTO:"):
                pid = clip[6:]
                if pid not in cat:
                    errs.append(f"{where}: unknown still {pid}")
                elif not ((config.WORK / "jpg") / f"{pid}.jpg").exists():
                    errs.append(f"{where}: no jpg for {pid}")
                if not 1.5 <= b - a <= 7:
                    errs.append(f"{where}: photo shown {b - a:.1f}s (keep 1.5–7 s)")
            elif clip.startswith("file:"):
                pass
            else:
                r = cat.get(clip)
                if r is None:
                    errs.append(f"{where}: unknown clip {clip}")
                elif not r["duration"]:
                    errs.append(f"{where}: {clip} is a still; use PHOTO:{clip}")
                elif b > float(r["duration"]) + 0.05:
                    errs.append(f"{where}: out {b} > duration {r['duration']} of {clip}")
                used.append((clip, a, b, where))
            if sh.get("audio") not in ("keep", "ambient", "mute"):
                errs.append(f"{where}: audio must be keep|ambient|mute")
            lb = sh.get("label")
            if isinstance(lb, str) and len(lb) > 40:
                errs.append(f"{where}: label over 40 chars")
            ch_t += (b - a) / float(sh.get("speed", 1.0))
        total += ch_t
        print(f"  {ch['name']:<26} {len(ch.get('shots', [])):3d} shots {ch_t / 60:5.2f} min  mood: {ch.get('mood', '-')}")
    return errs, total, used


target = Path(sys.argv[1])
errs, total, mine = check(target)
# overlaps inside this part and against the other parts
def ranges(path: Path) -> list:
    out = []
    for ch in json.loads(path.read_text(encoding="utf-8")).get("chapters", []):
        for k, s_ in enumerate(ch.get("shots", [])):
            sh, e = resolve(s_)
            if sh and not e and not str(sh.get("clip", "")).startswith(("PHOTO:", "file:")):
                out.append((sh["clip"], float(sh.get("in", 0)), float(sh.get("out", 0)), f"{path.name}:{ch['name']}#{k}"))
    return out


seen = {}
for p_ in sorted(glob.glob(str(ROOT / "edl_part*.json"))):
    if Path(p_).resolve() != target.resolve():
        try:
            for clip, a_, b_, w in ranges(Path(p_)):
                seen.setdefault(clip, []).append((a_, b_, w))
        except Exception as e_:  # another editor's file mid-write
            print(f"  (skipped {Path(p_).name}: {e_})")
for clip, a, b, w in mine:
    for a2, b2, w2 in seen.get(clip, []):
        if min(b, b2) - max(a, a2) > 0.3:
            errs.append(f"{w}: overlaps {w2} on {clip} {max(a, a2):.1f}-{min(b, b2):.1f}")
    seen.setdefault(clip, []).append((a, b, w))
print(f"TOTAL {total / 60:.2f} min, {sum(len(c.get('shots', [])) for c in json.loads(target.read_text(encoding='utf-8'))['chapters'])} shots")
print("OK" if not errs else "PROBLEMS:\n  " + "\n  ".join(errs))
sys.exit(1 if errs else 0)
