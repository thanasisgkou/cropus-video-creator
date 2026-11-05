"""Move a review's subtitle ops (fx_add / fx_set / fx_remove of type subtitle) into the subtitle files, in SOURCE time.

Subtitles live in analysis/review_subs_*.json as {clip, from, to, text} (source seconds); the builder places them on
whatever shots exist. A reviewer writes subtitle ops against a rendered version, timed from that version's shot IN.
This tool maps them back: from = shot.in (in film_<ver>.json) + start. New lines go to analysis/review_subs_<round>.json.
Overlaps inside a clip are resolved (the edited/added line wins; the older one is trimmed or dropped).
Usage: python tools/apply_sub_ops.py analysis/review_r2_story.json film_v2.json r2
"""
import json
import shutil
import sys
from pathlib import Path

from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
A = ROOT / "analysis"


def main():
    review, film_path, rnd = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    ops = [o for o in json.loads(review.read_text(encoding="utf-8"))["ops"]
           if (o.get("type") or (o.get("fx") or {}).get("type")) == "subtitle"]
    clips = json.loads(film_path.read_text(encoding="utf-8"))["clips"]

    def shot_in(clip, at, occ=1):
        hits = [c for c in clips if c["clip"] == clip and float(c["in"]) - 0.06 <= float(at) < float(c["out"]) + 0.06]
        if len(hits) >= occ:
            return float(hits[occ - 1]["in"])
        return float(hits[0]["in"]) if len(hits) == 1 else None

    files = sorted(A.glob("review_subs_*.json"))
    backup = (config.SCRATCH / "subs_backup") / rnd
    backup.mkdir(parents=True, exist_ok=True)
    data = {}
    for f in files:
        shutil.copy2(f, backup / f.name)
        data[f] = json.loads(f.read_text(encoding="utf-8"))
    new_file = A / f"review_subs_{rnd}.json"
    data.setdefault(new_file, {"note": f"subtitles added in review {rnd}", "subtitles": []})
    entries = [(f, sb) for f, d in data.items() for sb in d["subtitles"]]
    log, touched = [], set()

    def find(clip, contains):
        return [(f, sb) for f, sb in entries if sb["clip"] == clip and contains.replace("\n", " ") in sb["text"].replace("\n", " ")]

    for o in ops:
        clip = o["clip"]
        base = shot_in(clip, o.get("at", 0), int(o.get("occurrence", 1)))
        if o["op"] == "fx_remove":
            hits = find(clip, o["contains"])
            for f, sb in hits[:1]:
                data[f]["subtitles"].remove(sb); entries.remove((f, sb))
            log.append(f"{'removed' if hits else 'NOT FOUND remove'} {clip} «{o['contains']}»")
        elif o["op"] == "fx_set":
            hits = find(clip, o["contains"])
            if not hits:
                log.append(f"NOT FOUND set {clip} «{o['contains']}»"); continue
            f, sb = hits[0]
            st = o["set"]
            if "text" in st:
                sb["text"] = st["text"]
            if "start" in st and base is not None:
                d = float(st.get("dur", float(sb["to"]) - float(sb["from"])))
                sb["from"] = round(base + float(st["start"]), 2)
                sb["to"] = round(sb["from"] + d, 2)
            elif "dur" in st:
                sb["to"] = round(float(sb["from"]) + float(st["dur"]), 2)
            touched.add(id(sb))
            log.append(f"set {clip} «{o['contains']}» -> {sb['from']}-{sb['to']} «{sb['text'][:40]}»")
        elif o["op"] == "fx_add":
            fx = o["fx"]
            if base is None:
                log.append(f"NOT FOUND add {clip}@{o.get('at')} «{fx['text'][:40]}»"); continue
            sb = {"clip": clip, "from": round(base + float(fx["start"]), 2),
                  "to": round(base + float(fx["start"]) + float(fx["dur"]), 2), "text": fx["text"]}
            data[new_file]["subtitles"].append(sb); entries.append((new_file, sb)); touched.add(id(sb))
            log.append(f"added {clip} {sb['from']}-{sb['to']} «{fx['text'][:40]}»")
    # overlaps within a clip: the line touched in this round wins
    by_clip = {}
    for f, sb in entries:
        by_clip.setdefault(sb["clip"], []).append((f, sb))
    for clip, lst in by_clip.items():
        lst.sort(key=lambda x: float(x[1]["from"]))
        for (f1, a), (f2, b) in zip(lst, lst[1:]):
            if a not in data[f1]["subtitles"] or b not in data[f2]["subtitles"]:
                continue
            if float(a["to"]) > float(b["from"]) - 0.04:
                if id(a) in touched and id(b) not in touched:
                    b["from"] = round(float(a["to"]) + 0.04, 2)
                    if float(b["to"]) - float(b["from"]) < 0.8:
                        data[f2]["subtitles"].remove(b); log.append(f"dropped overlapped «{b['text'][:30]}»")
                else:
                    a["to"] = round(float(b["from"]) - 0.04, 2)
                    if float(a["to"]) - float(a["from"]) < 0.8:
                        data[f1]["subtitles"].remove(a); log.append(f"dropped overlapped «{a['text'][:30]}»")
    for f, d in data.items():
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    (A / f"subs_ops_{rnd}_log.txt").write_text("\n".join(log), encoding="utf-8")
    print(f"{len(ops)} subtitle ops: {sum(1 for l in log if not l.startswith('NOT'))} done, "
          f"{sum(1 for l in log if l.startswith('NOT'))} not found; backup in {backup}")


if __name__ == "__main__":
    main()
