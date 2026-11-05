import json, sys
for d in sys.argv[1:]:
    j = json.load(open(f"analysis/directors/{d}.json", encoding="utf-8"))
    print(f"===== {d} {j.get('days')}")
    for c in j.get("chapters", []):
        print(f"CH {c.get('title')} / {c.get('subtitle')} ~{c.get('suggested_seconds')}s: {c.get('story','')[:150]}")
    for m in j.get("moments", []):
        print(f"{m['id']:>4} {m['clip']} {float(m['src_in']):6.1f}-{float(m['src_out']):6.1f} ({float(m['src_out'])-float(m['src_in']):4.1f}s) s{m.get('score')} {m.get('category','')[:9]:9} {'A' if m.get('keep_audio') else ' '} [{m.get('chapter','')[:14]}] {m.get('description','')[:150]}" + (f" | pairs {m['pairs_with']}" if m.get('pairs_with') else "") + (f" | AUDIO: {m['audio_note'][:90]}" if m.get('audio_note') else ""))
    print("FOODS:", "; ".join(f"{f['clip']}@{f.get('t')} {f['food']}({f.get('confidence','')[:1]})" for f in j.get("foods", [])))
    print("NOTES:", j.get("notes_for_chief", "")[:1800])
