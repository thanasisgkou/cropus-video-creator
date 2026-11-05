# Brief for the subtitle writers

> Template. Replace everything in `{{…}}`. Make the work lists first:
> `python <tools>/subtitle_worklist.py film.json "analysis/subs/worklist_P<N>.txt"` (writes 4 parts, P1–P4).

The film is {{a private, funny travel film of …}}. They want **{{language}} subtitles on all the speech in the film**:
- **{{language}} speech:** subtitle it as said.
- **Other languages:** translate into {{language}} (guides, waiters, strangers).

## Your input

Your work list is `analysis/subs/worklist_P<N>.txt`, one block per speech run:
- the film time, the chapter, the clip and the source range (in seconds, in the clip's own time);
- a one-line context from the director;
- `ALREADY SUBTITLED from-to: text`: these ranges are done — **do not write subtitles that overlap them**;
- `words`: word-level Whisper transcripts as `[start-end]word`, in source seconds.

Whisper makes mistakes. Fix obvious ones with the context: names ({{names}}), place names ({{places}}).
If a passage is unintelligible, **skip it** rather than invent text. Whisper also invents text on silent or noisy clips
("Thanks for watching", repeated lines): never subtitle those.

## Rules for each subtitle

- **Timing:** `from` = start of its first word − 0.1 s, `to` = end of its last word + 0.3 s. Never run past the next
  subtitle's `from`; stay inside the block's source range.
- **Length:** at most 2 lines, about 42 characters per line; `\n` for a line break at a natural phrase boundary.
- **Duration:** 1.2 s minimum, 6.5 s maximum, at most ~17 characters per second; split long sentences at a pause.
- **Dialogue:** two speakers in one subtitle → one line each, starting with «— ». No speaker names.
- **Keep their voice:** write it as spoken, jokes and swearing included. Do not censor, summarise or "improve" it.
- **Skip:** fillers on their own ("uh", "haha") and singing along to music.

## Output `analysis/review_subs_auto_P<N>.json`

```json
{"note": "auto subtitles part N", "subtitles": [
  {"clip": "A_VID_20250604_122209", "from": 0.7, "to": 4.5, "text": "The only reason I made it\nto the top"}
]}
```
- `from`/`to` are in the clip's **source** seconds, as in the work list.
- Validate the JSON with Python: no subtitle overlaps another in the same clip, or an ALREADY SUBTITLED range.
- Do not edit any other file. Do not run Whisper or any model; work from the word lists.

Reply with the number of subtitles and 3 example lines where you fixed Whisper errors.
