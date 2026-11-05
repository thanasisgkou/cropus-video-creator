"""Write and render the travel-leg maps (assets/leg_<name>.json/.mp4) shown before each chapter that changes city.
Usage: python tools/make_legs.py [name ...]   (default: all; existing mp4s are kept unless named)
"""
import json
import subprocess
import sys
from pathlib import Path

from config import PROJECT as ROOT  # noqa: E402
INTRO = json.loads((ROOT / "assets" / "route_intro.json").read_text(encoding="utf-8"))
# assets/legs.json: {"skip_stops": 2, "view": [lon0, lon1, lat0, lat1],
#                    "legs": {"<name>": [destination index in STOPS, first new leg index, "card", "card sub"], ...}}
# STOPS = the intro map's stops after the first `skip_stops` (the flight from home).
SPEC = json.loads((ROOT / "assets" / "legs.json").read_text(encoding="utf-8"))
STOPS = INTRO["stops"][int(SPEC.get("skip_stops", 0)):]
VIEW = SPEC["view"]
LEGS = {k: tuple(v) for k, v in SPEC["legs"].items()}

def leg_spec(dest: int, first: int, card: str, sub: str) -> dict:
    stops = [dict(s, fade=None) for s in STOPS]
    bends = {lg["to"] - 2: lg["bend"] for lg in INTRO["legs"] if "bend" in lg and lg["to"] >= 3}
    legs = [{"to": k, "t0": 0, "t1": 0.01} for k in range(1, first)]
    n = dest - first + 1
    for j, k in enumerate(range(first, dest + 1)):  # the new legs share the drawing time
        legs.append({"to": k, "t0": round(0.9 + 2.2 * j / n, 3), "t1": round(0.9 + 2.2 * (j + 1) / n, 3)})
    for lg in legs:
        if lg["to"] in bends:
            lg["bend"] = bends[lg["to"]]
    return {"duration": 4.4 if n == 1 else 5.0, "card": card, "card_sub": sub, "title_in": 0.2, "title_out": 3.9 if n == 1 else 4.5,
            "fade_in": 0.35, "fade_out": 0.35, "keys": [[0, *VIEW]], "stops": stops, "legs": legs, "done": first - 1}


def main() -> None:
    names = sys.argv[1:] or list(LEGS)
    for name in names:
        dest, first, card, sub = LEGS[name]
        js = ROOT / "assets" / f"leg_{name}.json"
        js.write_text(json.dumps(leg_spec(dest, first, card, sub), ensure_ascii=False, indent=1), encoding="utf-8")
        mp4 = js.with_suffix(".mp4")
        if mp4.exists() and len(sys.argv) == 1:
            continue
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "route_map.py"), str(js), str(mp4)], check=True)


if __name__ == "__main__":
    main()
