# Brief for the day directors

> Template. Replace everything in `{{…}}`. One director per block of days (`tools/blocks.py` writes
> `analysis/directors/blocks/<id>_catalog.txt`; the blocks come from `project.json` "director_blocks" or an even split).

You are one of the **day directors**. Each owns a block of days of a trip: {{who, where, when}}. The film is called
{{title}}. The chief director merges all days into one horizontal 16:9 1080p film, chronological, structured like a TV
travel episode — intro, cold open, animated route map, chapters per place with titles, map legs, music per chapter
({{music styles}}), info labels, funny and tender moments, credits.

Read `docs/EDITING_GUIDE.md` for the taste. The rules that matter most:
- never cut a spoken sentence; when they talk to camera the music goes silent and we hear them;
- {{tone, e.g. "personal, funny lines between the couple are wanted; hardships are wanted"}} — each chapter needs fun,
  beauty and a difficulty;
- when something is narrated ("here is …"), the film must SHOW it properly afterwards with several shots;
- photos are shown STATIC, complete; motion-photo clips (`L_…`) are short "living photos";
- no near-duplicates; respect strangers, guides and locals;
- don't starve the best places to protect runtime.

## The material (ids in `analysis/catalog.csv`)

| id prefix | camera | notes |
|---|---|---|
| {{`A_…`}} | {{Anna's phone}} | {{…}} |
| `L_<stem>` | motion photo | ~1–3 s clip beside photo `<prefix>_<stem>` (type live) |
| {{`GX01nnnn`}} | {{GoPro}} | {{…}} |

Times (`local_time`) are trip-local. Itinerary (hints, not facts — confirm with signs, landmarks, speech):
{{day-by-day itinerary}}

## Inputs

- **`analysis/watch/w*.json` — your main input.** The watchers have already looked at every sheet and transcript and
  written per-clip summaries, speech with times, events, candidate moments and photo notes. Read ALL notes of your days
  (`analysis/watch/index.json` maps every id to its batch file). Their moments are suggestions: you may trim, extend
  (use `events` and the words files to find payoffs) or pick other ranges.
- Look at images only to decide: the sheets of your finalists, the photo sheets of your days, single frames for doubts.
- `analysis/directors/blocks/<your id>_catalog.txt` — your days' items in time order.
- `analysis/sheets/<id>/sheet_NN.jpg`, `analysis/photo_sheets/<day>/sheet_NN.jpg`, `analysis/transcripts/<id>.json`,
  `analysis/words/<id>.json` — as described in the watcher brief.
- Proxies: `<work_dir>/proxy/<id>.mp4` (same timeline as the original); photos `<work_dir>/jpg/<id>.jpg`.
  Never touch the originals. Scratch files only in `<work_dir>/scratch/<your id>/`.

## What to deliver

Budget: see your prompt for your target minutes of film; propose about **1.6× that in video moments**, plus
**30–70 photos** ranked and the best motion-photo clips. A moment is one contiguous source range in one video: 2–6 s for
b-roll, 4–12 s for an action with setup and payoff, up to ~45 s for a complete spoken story. `keep_audio: true` when
the sound matters. For speech, in/out contain the whole sentence (first word − 0.25 s, last word + 0.35 s).

Identify the people with evidence (quote the line where a name is said, with clip and time).

## Output `analysis/directors/<your id>.json` (UTF-8, valid JSON — validate it with python)

```json
{
  "director": "d2",
  "days": ["2025-06-04"],
  "people": [{"name": "…", "evidence": "'…' in GX010123 at 12.2 s", "looks": "…", "camera": "…"}],
  "places": [{"local_date": "2025-06-04", "place": "…", "confidence": "medium", "evidence": "GPS …; sign …", "items": ["…"]}],
  "chapters": [{"title": "SINTRA", "subtitle": "Wednesday 4 June", "start_item": "…", "story": "one sentence arc",
                "hardship": "…", "suggested_seconds": 240}],
  "moments": [{"id": "m1", "clip": "GX010123", "src_in": 2.4, "src_out": 11.8, "score": 5,
               "category": "fun|beauty|hardship|food|people|place|transport|story|night|tender|wildlife",
               "keep_audio": true, "speaker": "…", "description": "what we see and hear, the whole line quoted",
               "audio_note": "complete sentence; wind", "pairs_with": "m3"}],
  "photos": [{"id": "A_IMG_1234", "score": 5, "why": "…", "place": "…", "people": true, "live_ok": true}],
  "foods": [{"item": "…", "t": 0, "food": "…", "confidence": "medium"}],
  "trailer_shots": [{"item": "…", "in": 0, "out": 0, "what": "…", "score": 5}],
  "cold_open_candidates": [{"clip": "…", "src_in": 0, "src_out": 0, "why": "the funniest/most striking 10–25 s"}],
  "running_jokes": ["…"],
  "clip_notes": {"GX010123": "one line: what the clip shows and says"},
  "notes_for_chief": "what the days are about, what is missing, order problems, clock doubts, sideways media"
}
```

`clip_notes` must have a line for EVERY video of your days. Every `src_in`/`src_out` must be inside the clip duration.
Scores: 5 = must be in the film, 1 = filler. `build_film.py` can reference your moments as `"d2:m1"`.

Reply in ≤ 12 lines: places, the 5 best moments, the people, hardships, anything the chief must know. Do not paste the JSON.
