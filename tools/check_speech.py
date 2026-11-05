"""Flag shots whose speech is cut mid-sentence, or whose speech is muted, using Whisper segments."""
import json, sys
from pathlib import Path
JUNK = ("υπότιτλοι", "authorwave", "thanks for watching", "gracias por ver", "thank you.")
def segs(clip):
    p = Path(f"analysis/transcripts/{clip}.json")
    if not p.exists(): return []
    d = json.loads(p.read_text(encoding="utf-8"))
    return [s for s in d["segments"] if s["no_speech"] < 0.6 and len(s["text"]) > 2
            and not any(j in s["text"].lower() for j in JUNK)]
f = json.load(open("film.json", encoding="utf-8"))
fps = 30000 / 1001; t = 0; rows = []
for i, c in enumerate(f["clips"]):
    d = round((c["out"] - c["in"]) * fps) / fps
    rows.append((i, c, t)); t += d
for idx, (i, c, t0) in enumerate(rows):
    if c["clip"].startswith("file:"): continue
    a, b = float(c["in"]), float(c["out"])
    nxt = rows[idx + 1][1] if idx + 1 < len(rows) else None
    contiguous_next = nxt and nxt["clip"] == c["clip"] and abs(float(nxt["in"]) - b) < 0.6
    prv = rows[idx - 1][1] if idx else None
    contiguous_prev = prv and prv["clip"] == c["clip"] and abs(float(prv["out"]) - a) < 0.6
    ss = segs(c["clip"])
    inside = [s for s in ss if s["end"] > a + 0.3 and s["start"] < b - 0.3]
    issues = []
    if c.get("audio") == "keep":
        for s in inside:
            if s["start"] < a - 0.15 and not contiguous_prev: issues.append(f"starts mid-sentence (seg {s['start']:.1f}-{s['end']:.1f})")
            if s["end"] > b + 0.15 and not contiguous_next: issues.append(f"ends mid-sentence (seg {s['start']:.1f}-{s['end']:.1f})")
        after = [s for s in ss if b - 0.3 <= s["start"] < b + 1.5]
        if after and not contiguous_next: issues.append(f"next sentence starts {after[0]['start']:.1f}: {after[0]['text'][:60]}")
    elif inside:
        issues.append(f"MUTED/AMBIENT speech {len(inside)} seg: {inside[0]['text'][:70]}")
    if issues:
        mm = f"{int(t0//60):02d}:{t0%60:05.2f}"
        print(f"{mm} #{i:03d} {c['chapter']:<14} {c['clip']} {a:.1f}-{b:.1f} [{c.get('audio','ambient')}]")
        for x in dict.fromkeys(issues): print("      -", x)
