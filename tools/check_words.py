"""Word-level check: keep shots that cut a word, or stop/start while the speaker continues without a pause."""
import json, os
END = (".", "!", "?", ";", "…", "»")
f = json.load(open("film.json", encoding="utf-8"))
ONSET = json.load(open("analysis/audio_onset.json", encoding="utf-8")) if os.path.exists("analysis/audio_onset.json") else {}
fps = 30000 / 1001; t = 0; rows = []
for c in f["clips"]:
    d = round((c["out"] - c["in"]) * fps) / fps; rows.append((c, t)); t += d
n = 0
for i, (c, t0) in enumerate(rows):
    if c.get("audio") != "keep" or c["clip"].startswith("file:"): continue
    p = f"analysis/words/{c['clip']}.json"
    if not os.path.exists(p): print("NOWORDS", c["clip"]); continue
    ws = [w for w in json.load(open(p, encoding="utf-8"))["words"]
          if not any(h in w["w"] for h in ("AUTHORWAVE", "Υπότιτλοι", "υπότιτλοι"))]  # Whisper hallucinations
    a, b = float(c["in"]), float(c["out"])
    prev_same = i > 0 and rows[i-1][0]["clip"] == c["clip"] and abs(float(rows[i-1][0]["out"]) - a) < 0.6
    next_same = i + 1 < len(rows) and rows[i+1][0]["clip"] == c["clip"] and abs(float(rows[i+1][0]["in"]) - b) < 0.6
    issues = []
    for w in ws:
        silent_head = a <= ONSET.get(c["clip"], 0) + 0.03  # the file is silent before its onset: whisper's 0.0 starts are artefacts
        if w["s"] < a - 0.05 < w["e"] - 0.08 and not prev_same and not silent_head: issues.append(f"cuts word at in: '{w['w'].strip()}'")
        if w["s"] + 0.08 < b < w["e"] - 0.05 and not next_same: issues.append(f"cuts word at out: '{w['w'].strip()}'")
    inside = [w for w in ws if w["s"] >= a - 0.05 and w["e"] <= b + 0.05]
    after = [w for w in ws if w["s"] >= b - 0.05]
    if inside and after and not next_same:
        last = inside[-1]["w"].strip()
        if not last.endswith(END) and after[0]["s"] - inside[-1]["e"] < 0.5:
            issues.append(f"stops mid-flow after '{last}' -> next '{after[0]['w'].strip()}' at {after[0]['s']:.1f}")
    if issues:
        n += 1
        print(f"{int(t0//60):02d}:{t0%60:05.2f} {c['chapter']:<13} {c['clip']} {a:.2f}-{b:.2f}")
        for x in dict.fromkeys(issues): print("     ", x)
print("issues:", n)
