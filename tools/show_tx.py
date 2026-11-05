import json, sys
for c in sys.argv[1:]:
    try:
        d = json.load(open(f"analysis/transcripts/{c}.json", encoding="utf-8"))
    except FileNotFoundError:
        print(f"== {c}: (no transcript yet)"); continue
    print(f"== {c} [{d.get('language')}]")
    for s in d["segments"]:
        print(f"  {s['start']:6.2f}-{s['end']:6.2f} ns{s['no_speech']:.2f}  {s['text']}")
