"""The chief's reconciliation of the review rounds -> analysis/late_fixes.json (applied last by build_film.py).

Every review file analysis/review_r<N>_<lens>.json holds "ops". Here the chief decides, in writing, which ops are
skipped (conflicts, duplicates, superseded) and which are adjusted, then orders them: sets first, then inserts and
moves (their targets must still exist), then overlays/cutaways, then drops last.
Usage: python tools/make_late_fixes.py
"""
import json
from pathlib import Path

from config import PROJECT as ROOT  # noqa: E402
A = ROOT / "analysis"

# The chief's decisions live in analysis/late_fixes_decisions.json:
# {"skip":  {"review_r1_story#22": "why it is skipped", ...},          # (reviewer file stem # op index) -> reason
#  "patch": {"review_r2_director#17": {"set.label.text": "new text"}}} # values the chief changes before applying
_DEC = A / "late_fixes_decisions.json"
_DECISIONS = json.loads(_DEC.read_text(encoding="utf-8")) if _DEC.exists() else {}
SKIP = {tuple(k.rsplit("#", 1)[:1]) + (int(k.rsplit("#", 1)[1]),): v for k, v in _DECISIONS.get("skip", {}).items()}
PATCH = {tuple(k.rsplit("#", 1)[:1]) + (int(k.rsplit("#", 1)[1]),): v for k, v in _DECISIONS.get("patch", {}).items()}

def key(o):
    return (o["op"], o.get("clip"), round(float(o.get("at", 0)), 2), o.get("occurrence", 1),
            json.dumps(o.get("to"), sort_keys=True), json.dumps(o.get("set"), sort_keys=True))


def main():
    ops, seen, skipped = [], set(), []
    # the chief speaks last within a round, so his corrections win over the reviewers' values for the same shot
    files = sorted(A.glob("review_r[0-9]*_*.json"), key=lambda f: (f.stem.split("_")[1], f.stem.endswith("_chief"), f.stem))
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for i, o in enumerate(data.get("ops", [])):
            if (o.get("type") or (o.get("fx") or {}).get("type")) == "subtitle":
                skipped.append(f"{f.stem}#{i}: subtitle op moved into the subtitle files (tools/apply_sub_ops.py)")
                continue
            if (f.stem, i) in SKIP:
                skipped.append(f"{f.stem}#{i}: {SKIP[(f.stem, i)]}")
                continue
            for dotted, val in PATCH.get((f.stem, i), {}).items():
                node = o
                parts = dotted.split(".")
                for part in parts[:-1]:
                    node = node[part]
                node[parts[-1]] = val
            k = key(o)
            if k in seen and o["op"] == "drop":
                skipped.append(f"{f.stem}#{i}: duplicate drop of {o.get('clip')}")
                continue
            seen.add(k)
            o = dict(o, why=f"[{f.stem.replace('review_', '')}] {o.get('why', '')}")
            if o["op"] == "fx_add" and o["fx"].get("type") == "counter":
                o["fx"].setdefault("start", 0.3)
                o["fx"].setdefault("dur", 3.0)
            ops.append(o)
    order = {"insert_after": 0, "move_after": 0, "move_before": 0, "set": 1, "cw_add": 2, "cw_set": 2, "cw_remove": 2,
             "fx_add": 2, "fx_set": 2, "fx_remove": 2, "title_move": 2, "drop": 3}
    ops.sort(key=lambda o: order.get(o["op"], 2))
    (A / "late_fixes.json").write_text(json.dumps({"ops": ops}, ensure_ascii=False, indent=1), encoding="utf-8")
    (A / "late_fixes_skipped.txt").write_text("\n".join(skipped), encoding="utf-8")
    print(f"{len(ops)} ops from {len(files)} reviews; {len(skipped)} skipped (analysis/late_fixes_skipped.txt)")


if __name__ == "__main__":
    main()
