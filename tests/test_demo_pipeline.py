"""End-to-end smoke test: synthetic demo project -> catalog -> proxies -> film.json -> preview mp4 -> QA gate."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"


def run(cwd: Path, *args: str) -> str:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    env.pop("CROPUS_PROJECT", None)
    r = subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, f"{args} failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("cropus") / "demo-trip"
    run(REPO, str(REPO / "examples" / "make_demo.py"), str(root))
    return root


def test_ingest_uses_local_time(demo: Path) -> None:
    run(demo, str(TOOLS / "ingest.py"))
    rows = {r["id"]: r for r in csv.DictReader(open(demo / "analysis" / "catalog.csv", encoding="utf-8"))}
    assert rows["P_VID_20240501_090000"]["local_time"] == "2024-05-01 09:00:00"  # UTC 07:00 + 2 h
    assert rows["P_IMG_20240502_110000"]["type"] == "photo"
    assert len(rows) == 5


def test_build_and_render(demo: Path) -> None:
    run(demo, str(TOOLS / "prep_media.py"), "all")
    assert len(list((demo / "work" / "proxy").glob("*.mp4"))) == 3
    run(demo, str(TOOLS / "music_summary.py"))
    run(demo, str(TOOLS / "build_film.py"), "edl.json", "film.json")
    film = json.loads((demo / "film.json").read_text(encoding="utf-8"))
    assert len(film["clips"]) == 5 and film["music"]
    run(demo, str(TOOLS / "render_film.py"), "film.json", "--output", "demo_preview.mp4", "--jobs", "2")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(demo / "demo_preview.mp4")], capture_output=True, text=True).stdout
    assert abs(float(out) - 19.5) < 0.5
    assert "QA GATE: PASSED" in run(demo, str(TOOLS / "qa_gate.py"), "film.json", "demo_preview.mp4")
