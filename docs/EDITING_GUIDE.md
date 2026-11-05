# Editing guide

The taste these films are cut for. Give this file to every agent (watcher, director, editor, reviewer) and adapt it
to your own taste. The tools enforce some of it (sentence snapping, static photos, loudness); the rest is judgement.

## Core objective

A lively, personal travel film that feels like a real memory, not a generic destination reel. Combine people, scenery,
activities, funny moments, food, animals, roads and photos without letting any one type dominate. Structure it like a
TV travel episode: a cold open, an intro (route map, title), chapters per place with titles, map legs between places,
music per chapter, credits.

## Story first

- Never choose a clip because its first frames look nice. Know the whole clip: what actually happens and how it ends.
- Keep setup and payoff together (or split them on purpose). Do not cut away just before the action finishes:
  the fall until they disappear under the water, the throw of the lasso, the dive until it hits the water,
  the scare until the reaction, the ride's climb and drop with the screams.
- When something is narrated on camera ("here is the market…"), follow it with several shots that show it.
- Tell the real story, hardships included: rain, cold, illness, long buses, early alarms, mosquitoes, lost things.
  Every chapter wants some fun, some beauty and a difficulty.
- Give the best places generous coverage with quick montages; do not starve them to protect the runtime.

## Speech and sound

- Never cut a spoken sentence. Snap talking shots to word timings (in = first word − 0.25 s, out = last word + 0.35 s);
  `build_film.py` checks and snaps this.
- Under talking-to-camera the music goes silent and we hear the people; it comes back after. Ambient sound may stay low
  under montages.
- Keep natural sound where it adds emotion or comedy (screams, laughter, a band, waves, a storm).
- The ending must feel complete: the last spoken line fully audible, the music fading under it.

## Variety

- No near-duplicates: from a burst or a repeated event keep the best one or two.
- Never reuse the same source range.
- Faces every few shots; never more than about four pure landscapes in a row; no more than four stills in a row.
- Mix the cameras: GoPro breaks up phone footage.
- Montages: runs of 5–14 items cut to music (b-roll 2–5 s, motion-photo clips whole, photos 2–3 s, panoramas 4–5 s).

## Photos

- Photos are static: no Ken Burns, zoom, pan or shake. Show them complete.
- Portrait or 4:3 photos sit on a fill (black bars or a blurred copy); the photo itself never moves.
- Drop photos that are repetitive, awkward or weaker than the video of the same moment.

## Respect

- Respect strangers, guides and locals; no mocking.
- No body-focused framing at pools, beaches or hot springs; prefer faces and wide views.
- No accidental pocket footage, half faces or mirror shots unless they are the joke.

## Review loop

1. Treat every timestamp in a note as exact; find the shot active at that time and its source range.
2. Look beyond the selected range to find the whole action or payoff.
3. "Remove it" means remove that photo or video, not recolour it. Replace it with a different subject if the runtime needs it.
4. Never bring back footage that was removed in an earlier round. Keep approved sections untouched.
5. Re-render only what changed, then check the whole film (`qa_gate.py`) before sending it.

## Pre-export checklist

- Speech complete everywhere; no music over talking.
- Loudness about −14 LUFS integrated, true peak below −1 dBFS.
- No still photo moves; no rejected clip returned; no duplicates.
- Every setup reaches its payoff.
- Titles and labels spelled correctly; facts on labels verified.
- The opening and the ending both feel deliberate.
