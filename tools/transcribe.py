"""Whisper (GPU if available) on every video of the project (reads the 480p proxies): segments -> analysis/transcripts/<id>.json,
word timings -> analysis/words/<id>.json.  Usage: <.venv-captions python> tools/transcribe.py [ID ...]
"""
import csv
import json
import sys
from pathlib import Path

from faster_whisper import WhisperModel

from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
PROXY = (config.WORK / "proxy")
TX, WD = ROOT / "analysis" / "transcripts", ROOT / "analysis" / "words"
TX.mkdir(parents=True, exist_ok=True)
WD.mkdir(parents=True, exist_ok=True)

with open(ROOT / "analysis" / "catalog.csv", encoding="utf-8") as fh:
    rows = [r for r in csv.DictReader(fh) if r["type"] == "video"]
wanted = set(sys.argv[1:])
DEVICE = config.WHISPER.get("device") or ("cuda" if config.nvenc() else "cpu")
model = WhisperModel(config.WHISPER.get("model", "large-v3"), device=DEVICE,
                     compute_type=config.WHISPER.get("compute_type") or ("int8_float16" if DEVICE == "cuda" else "int8"),
                     cpu_threads=4, num_workers=1)  # light: see safe_run.py
LANGS = tuple(config.WHISPER.get("languages", ["en"]))  # expected languages; the first is the fallback
for r in rows:
    cid = r["id"]
    if wanted and cid not in wanted:
        continue
    dst = TX / f"{cid}.json"
    if dst.exists() or not (PROXY / f"{cid}.mp4").exists():
        continue
    try:
        segs, info = model.transcribe(str(PROXY / f"{cid}.mp4"), vad_filter=True, beam_size=5, word_timestamps=True,
                                      vad_parameters={"min_silence_duration_ms": 400})
        segs = list(segs)
        if info.language not in LANGS or info.language_probability < 0.5:
            segs, info = model.transcribe(str(PROXY / f"{cid}.mp4"), language=LANGS[0], vad_filter=True, beam_size=5,
                                          word_timestamps=True, vad_parameters={"min_silence_duration_ms": 400})
            segs = list(segs)
        tx = {"file": r["path"], "language": info.language, "lang_prob": round(info.language_probability, 2),
              "segments": [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                            "no_speech": round(s.no_speech_prob, 2)} for s in segs]}
        words = [{"s": round(w.start, 2), "e": round(w.end, 2), "w": w.word, "p": round(w.probability, 2)}
                 for s in segs for w in (s.words or [])]
        (WD / f"{cid}.json").write_text(json.dumps({"clip": cid, "language": info.language, "words": words},
                                                   ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        tx = {"file": r["path"], "error": str(e)[:300], "segments": []}
    dst.write_text(json.dumps(tx, ensure_ascii=False, indent=1), encoding="utf-8")
    print(cid, tx.get("language"), len(tx["segments"]), "segments", flush=True)
