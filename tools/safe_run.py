"""Run a heavy job without freezing the PC.

Why: several Whisper models and ffmpeg jobs at once can exhaust RAM, grow the swap/pagefile until the system disk is full
and lock the machine. This wrapper prevents that:

- the job and all its children run at BelowNormal priority (the desktop stays responsive);
- `--lock NAME` allows only one job per lock name at a time (default lock "heavy"); later jobs wait their turn;
- every few seconds it checks free RAM, free space on the system disk and the job's own memory. When RAM or disk is low it SUSPENDS
  the whole job tree and resumes it once there is room again; if it stays suspended too long, or the job grows past
  `--max-gb`, the job is killed (a cached, resumable job such as transcribe.py or prep_media.py just continues next run);
- `--wait-for PATTERN` waits while any other process whose command line contains PATTERN is running
  (e.g. another session's Whisper on the same GPU).

Usage:  python tools/safe_run.py [--lock heavy] [--ram-gb 6] [--c-gb 10] [--max-gb 8] [--wait-for whisper] -- <command ...>
Log:    analysis/scratch/logs/safe_run.log
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

from config import PROJECT as ROOT  # noqa: E402
import config  # noqa: E402
LOCKS = (config.WORK / "locks")
LOG = ROOT / "analysis" / "scratch" / "logs" / "safe_run.log"
GB = 1024 ** 3


def log(msg: str) -> None:
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def free_ram() -> float:
    return psutil.virtual_memory().available / GB


SYSTEM_DISK = os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"


def free_c() -> float:
    """Free space on the system disk (where swap/pagefile grows)."""
    return psutil.disk_usage(SYSTEM_DISK).free / GB


def tree(p: psutil.Process) -> list[psutil.Process]:
    try:
        return [p] + p.children(recursive=True)
    except psutil.Error:
        return []


def tree_rss(p: psutil.Process) -> float:
    total = 0
    for q in tree(p):
        try:
            total += q.memory_info().rss
        except psutil.Error:
            pass
    return total / GB


def set_low(p: psutil.Process, seen: set[int]) -> None:
    for q in tree(p):
        if q.pid in seen:
            continue
        try:
            q.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
            seen.add(q.pid)
        except psutil.Error:
            pass


def each(p: psutil.Process, fn: str) -> None:
    for q in tree(p):
        try:
            getattr(q, fn)()
        except psutil.Error:
            pass


def acquire(name: str) -> Path:
    LOCKS.mkdir(parents=True, exist_ok=True)
    lock = LOCKS / f"{name}.lock"
    waited = False
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if not pid or not psutil.pid_exists(pid):
                lock.unlink(missing_ok=True)  # stale lock from a crashed run
                continue
            if not waited:
                log(f"waiting for lock '{name}' held by pid {pid}")
                waited = True
            time.sleep(10)


def others_running(pattern: str) -> list[int]:
    me = {os.getpid()}
    out = []
    for q in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(q.info["cmdline"] or [])
        except psutil.Error:
            continue
        if q.info["pid"] not in me and pattern.lower() in cmd.lower() and "safe_run.py" not in cmd:
            out.append(q.info["pid"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", default="heavy")
    ap.add_argument("--ram-gb", type=float, default=6.0, help="suspend below this much free RAM")
    ap.add_argument("--c-gb", type=float, default=10.0, help="suspend below this much free space on the system disk")
    ap.add_argument("--max-gb", type=float, default=8.0, help="kill the job if it uses more RAM than this")
    ap.add_argument("--max-pause-min", type=float, default=20.0)
    ap.add_argument("--wait-for", action="append", default=[])
    ap.add_argument("--log-to", type=Path, help="send the job's output to this file")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        ap.error("no command")
    lock = acquire(a.lock) if a.lock != "none" else None
    try:
        for pat in a.wait_for:
            first = True
            while others_running(pat):
                if first:
                    log(f"waiting: another '{pat}' process is running {others_running(pat)}")
                    first = False
                time.sleep(15)
        while free_ram() < a.ram_gb or free_c() < a.c_gb:
            log(f"waiting to start: RAM {free_ram():.1f} GB, C: {free_c():.1f} GB")
            time.sleep(15)
        out = open(a.log_to, "a", encoding="utf-8") if a.log_to else None
        child = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT if out else None,
                                 creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0)
        proc = psutil.Process(child.pid)
        log(f"start pid {child.pid} [{a.lock}]: {' '.join(cmd)[:160]}")
        seen: set[int] = set()
        paused_at = None
        while child.poll() is None:
            set_low(proc, seen)
            ram, c, rss = free_ram(), free_c(), tree_rss(proc)
            if rss > a.max_gb:
                log(f"KILL: job uses {rss:.1f} GB (> {a.max_gb})")
                each(proc, "kill")
                break
            if paused_at is None and (ram < a.ram_gb or c < a.c_gb):
                each(proc, "suspend")
                paused_at = time.time()
                log(f"PAUSE: RAM {ram:.1f} GB, C: {c:.1f} GB")
            elif paused_at is not None:
                if ram > a.ram_gb + 2 and c > a.c_gb + 2:
                    each(proc, "resume")
                    log(f"RESUME after {time.time() - paused_at:.0f} s: RAM {ram:.1f} GB, C: {c:.1f} GB")
                    paused_at = None
                elif time.time() - paused_at > a.max_pause_min * 60:
                    log("KILL: paused too long")
                    each(proc, "kill")
                    break
            time.sleep(5)
        rc = child.wait()
        log(f"end pid {child.pid} rc={rc}")
        return rc
    finally:
        if lock:
            lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
