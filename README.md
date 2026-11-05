# cropus-video-creator

Turn a folder of holiday phone videos, photos and GoPro clips into a finished, TV-style travel film: chapters with
titles, animated route maps, music per chapter that ducks under speech, Greek/any-language subtitles, info labels,
comic graphics, and a loudness-checked 1080p master.

It is a set of small Python + FFmpeg tools driven by plain JSON files. The *creative* decisions (which moments,
in which order, what music, what jokes) are written into those JSON files by AI agents (we use Claude Code) or by
you by hand. The tools do the mechanical, exact part: catalog, proxies, contact sheets, transcripts, timeline
assembly, rendering and quality checks.

> Ελληνικά: [README.el.md](README.el.md)

```
your footage ──► ingest ──► proxies + contact sheets + transcripts ──► (AI) watchers → directors → editors
                                                                              │
          final.mp4 ◄── render (master) ◄── QA gate ◄── render (preview) ◄── build_film ◄── edl.json
```

## Requirements

| | |
|---|---|
| Python | 3.10 or newer |
| FFmpeg | 7.0 or newer, `ffmpeg` and `ffprobe` on the PATH (the renderer uses `-/filter_complex`) |
| Python packages | `pip install -r requirements.txt` (Pillow, pillow-heif, numpy, psutil, faster-whisper) |
| GPU (optional) | An NVIDIA GPU makes proxies, master renders and Whisper much faster. Without one everything runs on the CPU (libx264, Whisper int8), just slower. Set `"gpu": false` in `project.json` to force CPU. |
| Disk | Proxies + render caches need roughly 15–40 GB for a two-week trip. Point `work_dir` at a big disk. |
| AI agent (optional) | [Claude Code](https://claude.com/claude-code) or any coding agent that can read images, for the watcher/director/editor steps. |

Fonts are found automatically on Windows, macOS and Linux (Bahnschrift/Segoe on Windows, DejaVu or Arial elsewhere).
Override any of them in `project.json` → `"fonts": {"bold": "path/to/font.ttf", "text": ..., "label": ..., "emoji": ...}`.

## Install

```bash
git clone https://github.com/thanasisgkou/cropus-video-creator.git
cd cropus-video-creator
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Try it in two minutes (no footage needed)

The demo makes a tiny project with synthetic test videos, two photos and a synthetic tune, then runs the whole chain:

```bash
python examples/make_demo.py demo-trip
cd demo-trip
python ../tools/ingest.py
python ../tools/prep_media.py all
python ../tools/music_summary.py
python ../tools/build_film.py edl.json film.json
python ../tools/render_film.py film.json --output demo_preview.mp4
python ../tools/qa_gate.py film.json demo_preview.mp4
```

Open `demo_preview.mp4`: two chapters with titles, a lower-third label, static photos and a music bed.
The same chain runs as a test: `python -m pytest tests`.

## Make your own film

### 1. Create a project folder

A project is one film. Keep it next to (not inside) this repo:

```
my-trip/
  project.json        settings (copy project.example.json)
  music/              your music tracks, .mp3 (royalty-free or your own)
  assets/             maps, intro clips, legs.json …
  analysis/           everything the tools and agents write (catalog, sheets, transcripts, notes)
  edl.json            the cut (written by the editors / you)
  film.json           the renderable timeline (written by build_film)
```

Copy `project.example.json` to `my-trip/project.json` and edit it:

```jsonc
{
  "title": "Portugal 2025",
  "utc_offset_hours": 1,                 // local time of the trip; the film is told in local time
  "work_dir": "E:/portugal-work",        // big disk for proxies and render caches
  "sources": [
    {"dir": "E:/Portugal/phone-anna", "prefix": "A", "camera": "Anna's iPhone"},
    {"dir": "E:/Portugal/phone-nick", "prefix": "N", "camera": "Nick's Pixel"},
    {"dir": "E:/Portugal/gopro", "camera": "GoPro", "gopro": true, "clock_utc_offset_hours": 2}
  ],
  "places": [["2025-06-01", "Lisbon"], ["2025-06-04 10:00", "Sintra"], ["2025-06-05", "Porto"]],
  "whisper": {"model": "large-v3", "languages": ["en", "pt"]}
}
```

- **sources**: one entry per camera/phone export folder. Every file gets an id `<prefix>_<file name>`
  (GoPro clips keep their own name, e.g. `GX010123`). Use different prefixes so ids never clash.
- **clock_utc_offset_hours**: phones write real UTC, so leave it out. GoPros write their own clock; if the GoPro was set
  to home time (say UTC+2) put `2`. `tools/gopro_gps.py` measures the exact offset from the GoPro's GPS.
- **places**: optional "from this local time on we were in…" list, used for memory flashback tags.

Originals are never modified. All paths can be absolute or relative to the project folder.

### 2. Prepare the material (run inside `my-trip/`)

```bash
python ../cropus-video-creator/tools/ingest.py                 # -> analysis/catalog.csv, analysis/days.txt
python ../cropus-video-creator/tools/prep_media.py all         # 480p proxies, JPGs, contact sheets, photo sheets
python ../cropus-video-creator/tools/transcribe.py             # Whisper -> analysis/transcripts, analysis/words
python ../cropus-video-creator/tools/music_summary.py          # length + loudness of every track in music/
```

Long jobs can be wrapped in `tools/safe_run.py` so the computer stays usable: it lowers priority, runs one job per lock,
and pauses the job when RAM or disk runs low:

```bash
python ../cropus-video-creator/tools/safe_run.py --lock whisper --ram-gb 4 -- python ../cropus-video-creator/tools/transcribe.py
```

Optional: `tools/gopro_gps.py <gopro_dir> analysis/gopro_gps.csv` (GPS + clock offset of GoPro clips).

### 3. Watch and choose (AI agents or you)

This is where the film is actually made. Each step reads the previous step's JSON and writes its own. The briefs in
[`briefs/`](briefs) are the prompts we give to the agents; copy them into the project and fill in the trip details
(people, dates, places, tone).

| Step | Who | Reads | Writes | Brief |
|---|---|---|---|---|
| Watch | many small "watcher" agents, one batch each (`tools/watch_batches.py` makes the batches) | contact sheets, photo sheets, transcripts | `analysis/watch/<batch>.json`: per-clip summary, speech with times, events, candidate moments | [`WATCHER_BRIEF.md`](briefs/WATCHER_BRIEF.md) |
| Direct | 3–5 "day directors", one block of days each (`tools/blocks.py`) | the watcher notes of their days | `analysis/directors/d<N>.json`: chapters, ranked moments, photos, people, places | [`DIRECTOR_BRIEF.md`](briefs/DIRECTOR_BRIEF.md) |
| Plan | one "chief" | all director files | `analysis/chief_plan.md`: arc, chapter list, runtime per chapter, music moods | — |
| Edit | 3–5 "chapter editors" | chief plan + director files | `edl_part<N>.json`, checked with `tools/check_edl_part.py` | [`EDITOR_BRIEF.md`](briefs/EDITOR_BRIEF.md) |
| Frame | the chief | — | `edl_frame.json`: cold open, intro map, music per chapter, credits | — |
| Subtitles | 2–4 agents | `tools/subtitle_worklist.py` output | `analysis/review_subs_*.json` | [`SUBS_BRIEF.md`](briefs/SUBS_BRIEF.md) |

The taste we edit for (story first, never cut a sentence, static photos, no near-duplicates…) is written down in
[`docs/EDITING_GUIDE.md`](docs/EDITING_GUIDE.md). Give it to every agent.

Doing it by hand works too: look at the sheets in `analysis/sheets/` and write `edl.json` yourself
(format in the header of [`tools/build_film.py`](tools/build_film.py)).

### 4. Build, check, render

```bash
python ../cropus-video-creator/tools/merge_edl.py                        # edl_frame.json + edl_part*.json -> edl.json
python ../cropus-video-creator/tools/build_film.py edl.json film.json    # snaps cuts to speech, places music, subtitles …
python ../cropus-video-creator/tools/qa_gate.py film.json                # checks before rendering
python ../cropus-video-creator/tools/render_film.py film.json --output previews/v1.mp4 --jobs 3
python ../cropus-video-creator/tools/qa_gate.py film.json previews/v1.mp4
```

The preview renders 960x540 from the proxies. Only changed shots are re-rendered (segment cache keyed by content).
Watch it, write notes, fix (reviewer agents can write `analysis/review_*.json` ops; see `tools/make_late_fixes.py`),
rebuild. When you are happy:

```bash
python ../cropus-video-creator/tools/render_film.py film.json --master --output final_1080p.mp4
```

`--master` reads the original files and renders 1920x1080. Never send a version that fails `qa_gate.py`
(music present, speech not under music, loudness about −14 LUFS, true peak, no black frames, sync).

### Extras

| Tool | What it does |
|---|---|
| `route_map.py <route.json> <out.mp4>` | Animated flight/route map. Needs Natural Earth land polygons: download `ne_50m_land.geojson` (public domain, [naturalearthdata.com](https://www.naturalearthdata.com/downloads/50m-physical-vectors/) or the GeoJSON at [github.com/nvkelso/natural-earth-vector](https://github.com/nvkelso/natural-earth-vector/tree/master/geojson)) to `assets/maps/`. Format in the file header. |
| `make_legs.py` | Short "from A to B" map cards between chapters (`assets/legs.json`). |
| `make_card.py` | Black title cards ("3 days later…"). |
| `fx.py` | Comic graphics used by the renderer: speech bubbles, circles, counters, flashback tags. |
| `beats.py` | Beat grid of a music track; `build_film` snaps cuts near a beat onto it. |
| `short_units.py` | Lists units for cutting a short version (`build_film.py edl.json film_short.json keep.json`). |
| `review_sheets.py` | Contact sheets of a rendered preview, for reviewers. |
| `check_*.py` | Speech, words, sync, audio and must-have checks (all run by `qa_gate.py`). |

## Privacy

The tools run entirely on your computer. Nothing is uploaded except what you send to an AI agent yourself.
`.gitignore` keeps media, `analysis/`, `work/` and renders out of git. Do not commit your project folder to a public repo.

## License

MIT — see [LICENSE](LICENSE). Music, fonts and map data you add keep their own licenses.
