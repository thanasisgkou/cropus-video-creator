"""Beat grid of every music track -> analysis/music/beats/<track>.json  {"bpm": .., "beats": [s, ...], "downbeats": [...]}

No librosa here: spectral-flux onset envelope, tempo by autocorrelation (70–180 BPM, folded towards 90–150),
phase by comb search, then every beat is pulled to the strongest onset within ±12 % of a period.
Usage: python tools/beats.py [track ...]   (default: every mp3 in music/)
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from config import PROJECT as ROOT  # noqa: E402
OUT = ROOT / "analysis" / "music" / "beats"
OUT.mkdir(parents=True, exist_ok=True)
SR, HOP, NFFT = 11025, 128, 1024


def load(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def onset_env(y: np.ndarray) -> np.ndarray:
    n = 1 + (len(y) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = y[idx] * np.hanning(NFFT)[None, :]
    mag = np.log1p(30 * np.abs(np.fft.rfft(frames, axis=1)))
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # local mean removal
    flux = np.maximum(flux, 0)
    return flux / (flux.max() + 1e-9)


def tempo(env: np.ndarray) -> float:
    fps = SR / HOP
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    lags = np.arange(len(ac))
    bpm = 60 * fps / np.maximum(lags, 1)
    ok = (bpm >= 70) & (bpm <= 180)
    w = np.exp(-0.5 * (np.log2(bpm / 120) / 0.9) ** 2)  # prefer the 90–150 region
    score = np.where(ok, ac * w, 0)
    return float(bpm[int(np.argmax(score))])


def track(path: Path) -> dict:
    y = load(path)
    env = onset_env(y)
    fps = SR / HOP
    bpm = tempo(env)
    period = 60 * fps / bpm
    # phase: comb sum over the whole track
    best, best_phase = -1, 0.0
    for ph in np.linspace(0, period, 48, endpoint=False):
        pos = np.arange(ph, len(env) - 1, period).astype(int)
        s = env[pos].sum()
        if s > best:
            best, best_phase = s, ph
    beats = []
    win = max(1, int(period * 0.12))
    for p in np.arange(best_phase, len(env) - 1, period):
        a, b = max(0, int(p) - win), min(len(env), int(p) + win + 1)
        q = a + int(np.argmax(env[a:b])) if env[a:b].max() > 0.15 else int(p)
        beats.append(round(q / fps, 3))
    # downbeats: the 4-phase whose beats carry the most onset energy
    strength = [sum(env[int(b * fps)] for b in beats[k::4]) for k in range(4)]
    k0 = int(np.argmax(strength))
    return {"bpm": round(bpm, 1), "beats": beats, "downbeats": beats[k0::4]}


if __name__ == "__main__":
    names = sys.argv[1:] or [p.stem for p in sorted((ROOT / "music").glob("*.mp3"))]
    for n in names:
        res = track(ROOT / "music" / f"{n}.mp3")
        (OUT / f"{n}.json").write_text(json.dumps(res), encoding="utf-8")
        print(f"{res['bpm']:6.1f} bpm {len(res['beats']):4d} beats  {n}", flush=True)
