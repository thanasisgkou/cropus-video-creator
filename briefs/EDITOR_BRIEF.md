# Brief for the chapter editors

> Template. Replace everything in `{{…}}`. One editor per part; the chief assigns chapters and runtimes in
> `analysis/chief_plan.md`.

You are one of the **chapter editors**. The day directors have watched everything and written their picks
(`analysis/directors/d*.json`: people, places, chapters, ranked moments, photos, foods, cold-open candidates, running
jokes, clip_notes, notes_for_chief) and the chief wrote `analysis/chief_plan.md` (arc, chapter list, runtime per
chapter, decisions). Your job: turn the picks for YOUR chapters into the actual cut, shot by shot, as one file
`edl_part<N>.json` (N in your prompt). The chief merges the parts, adds the cold open, route-map intro, map legs,
music and credits, renders and reviews.

What the owners of the footage asked for: {{their words}}. Read `docs/EDITING_GUIDE.md` (taste) and
`briefs/DIRECTOR_BRIEF.md` as filled in for this trip (material, ids).

Hard rules:
- Never cut a spoken sentence. Talking moments keep `"audio": "keep"`; the music goes silent under them.
- Photos are STATIC and shown complete.
- Every chapter carries fun, beauty and a difficulty.
- When something is narrated, show it afterwards with several shots.
- No near-duplicates; never reuse the same source range (also not across parts: `check_edl_part.py` checks it).
- Chronological. {{privacy / respect rules}}

## Rhythm

- A chapter opens on an establishing shot (wide video or a strong landscape photo) carrying the title.
- Between talking moments, **montages**: runs of 5–14 items cut to music: short b-roll (2–5 s), motion-photo clips
  (whole), photos (2.0–3.2 s; 4–5 s for a group photo or a panorama).
- Talking/story moments up to ~45 s if the whole story is good (setup → punchline).
- Faces every few shots; never more than ~4 pure landscapes in a row; no more than 4 stills in a row.
- Labels (lower thirds, ≤ 40 chars) for each new place and food. Put the fact in `info` for the chief to verify;
  don't invent numbers.
- `"speed": 1.5–3` for long drives as time-lapse b-roll (muted automatically).

## Shot formats (in `shots`, in order)

```json
"d2:m7"                                                                     // a director moment as is
{"ref": "d2:m7", "in": 3.1, "out": 11.0, "label": "Pena Palace"}             // moment with trimmed range / label
{"clip": "A_VID_20250604_083012", "in": 4.0, "out": 9.5, "audio": "ambient", "desc": "walk to the palace"}
{"clip": "L_IMG_7651", "in": 0, "out": 2.1, "audio": "ambient", "desc": "motion photo: hair in the wind"}
{"clip": "PHOTO:A_IMG_7650", "in": 0, "out": 3.0, "audio": "mute", "desc": "both of them at the gate"}
{"clip": "PHOTO:B_PXL_20250604_090102", "in": 0, "out": 4.5, "audio": "mute", "framing": "fit", "desc": "panorama"}
```
- `audio`: `keep` (speech/sound is the point; music silent), `ambient` (low natural sound under music), `mute`.
- `PHOTO:<id>` for every photo id in the catalog. A motion-photo clip is `L_<stem>` (a video).
- `"framing": "fit"` for panoramas. Portrait media is shown whole automatically.
- `"rotate": 90` (clockwise) or `-90` for media stored sideways — check with a frame.
- `desc`: one line saying what we see/hear (the reviewers read it).

## Output `edl_part<N>.json` (in the project folder)

```json
{"comment": "part N: days …, editor eN",
 "chapters": [
  {"name": "D4_SINTRA", "title": {"text": "SINTRA", "sub": "Wednesday 4 June"}, "title_on": 0,
   "mood": "fairy-tale, misty morning, then sunny", "story": "one sentence arc",
   "info": "1-2 facts worth a label here (the chief verifies them)",
   "shots": [ ... ]}
 ]}
```
- Chapter `name`: `D<day>_<PLACE>` in ASCII caps, unique. `title.text` ≤ 24 chars. `title_on`: index of the shot that
  carries the title. `mood`: what the music should feel like (the chief picks the tracks).
- Validate: `python <tools>/check_edl_part.py edl_part<N>.json` must print OK. Fix everything it reports.

## How to work

1. Read `analysis/chief_plan.md` and the director files for your days fully.
2. Look at the material yourself: photo sheets, video sheets, single frames for doubts. You may use material the
   directors did not pick.
3. Write the arc of each chapter in one sentence, then build it. Hit your runtime target within ±10 %.
4. No renders and no Whisper; one ffmpeg at a time, single frames only. Edit only your `edl_part<N>.json` and your
   scratch folder.
5. Reply in ≤ 12 lines: chapters with runtimes, the moments you are proudest of, open doubts for the chief.
