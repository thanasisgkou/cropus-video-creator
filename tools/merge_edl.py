"""Merge edl_part*.json (+ intro/outro/inserts/settings from edl_frame.json) into edl.json.
The chief's per-chapter decisions (music) live in edl_frame.json "music_map" and override the parts."""
import json, glob
from pathlib import Path
out = {"chapters": []}
frame = Path("edl_frame.json")
fr = json.loads(frame.read_text(encoding="utf-8")) if frame.exists() else {}
out.update({k: v for k, v in fr.items() if k not in ("chapters", "music_map", "comment")})
for p in sorted(glob.glob("edl_part*.json")):
    out["chapters"] += json.loads(Path(p).read_text(encoding="utf-8"))["chapters"]
# chapter splits: {"D3_CITY": {"at_clip": "A_IMG_0001", "new": "D3_CITY_NIGHT"}} -> shots from that clip on form a new
# chapter (no title) so it can carry its own music
for name, sp in fr.get("chapter_split", {}).items():
    for k, ch in enumerate(out["chapters"]):
        if ch["name"] != name:
            continue
        idx = next((i for i, s_ in enumerate(ch["shots"]) if isinstance(s_, dict) and s_.get("clip") == sp["at_clip"]), None)
        if idx:
            out["chapters"].insert(k + 1, {"name": sp["new"], "title": None, "shots": ch["shots"][idx:]})
            ch["shots"] = ch["shots"][:idx]
        break
mm = fr.get("music_map", {})
intro = out.pop("intro", [])
if intro:  # the route map is its own chapter so that it can carry the opening music
    out["chapters"].insert(0, {"name": "INTRO", "title": None, "shots": intro})
out["chapters"] = fr.get("pre_chapters", []) + out["chapters"] + fr.get("post_chapters", [])
for name, ins in fr.get("chapter_insert", {}).items():  # {"D8_HOMEWARD": {"before_clip": "...", "shots": [...]}}
    for ch in out["chapters"]:
        if ch["name"] == name:
            idx = next((i for i, s_ in enumerate(ch["shots"]) if isinstance(s_, dict) and s_.get("clip") == ins["before_clip"]),
                       len(ch["shots"]))
            ch["shots"][idx:idx] = ins["shots"]
for ch in out["chapters"]:
    ch.update(mm.get(ch["name"], {}))
# the chief's title decisions: {"D2_CITY": {"title": null, "label_first": "The city at night"}, "D3_CITY": {"title": {...}}}
for ch in out["chapters"]:
    patch = dict(fr.get("chapter_patch", {}).get(ch["name"], {}))
    lab = patch.pop("label_first", None)
    ch.update(patch)
    if lab and ch["shots"]:
        s0 = ch["shots"][0]
        s0 = {"ref": s0} if isinstance(s0, str) else dict(s0)
        s0["label"] = {"text": lab, "start": 0.4, "dur": 2.6}
        ch["shots"][0] = s0
missing = [ch["name"] for ch in out["chapters"] if not ch.get("music")]
Path("edl.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(out["chapters"]), "chapters", ("; no music for " + ", ".join(missing)) if missing else "")
