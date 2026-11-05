"""Every line listed in analysis/must_have.json ([{"clip", "from", "to", "why"}]) must be in film.json with audio "keep"."""
import json
import os
need=json.load(open('analysis/must_have.json',encoding='utf-8')) if os.path.exists('analysis/must_have.json') else []
f=json.load(open('film.json',encoding='utf-8'))
cov={}
for c in f['clips']: cov.setdefault(c['clip'],[]).append((float(c['in']),float(c['out']),c.get('audio')))
bad=0
for n in need:
    rs=sorted(cov.get(n['clip'],[]))
    # merge covered ranges with audio keep
    t=n['from']; ok=True
    for a,b,au in rs:
        if a<=t+0.3 and b>t and au=='keep': t=max(t,b)
    if t < n['to']-0.3:
        bad+=1; print(f"MISSING {n['clip']} {n['from']}-{n['to']} (covered to {t:.1f}) : {n['why']}")
print('must-have check:', 'ALL PRESENT' if not bad else f'{bad} missing')
