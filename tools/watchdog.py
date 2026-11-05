"""Print one line when free RAM or free space on the system disk drops low, and one when it recovers (for a Monitor watch).
Usage: python -u tools/watchdog.py [ram_gb=4] [c_gb=8]"""
import os
import sys
import time

import psutil

RAM_MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
C_MIN = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
DISK = os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"
low = False
while True:
    ram = psutil.virtual_memory().available / 2 ** 30
    c = psutil.disk_usage(DISK).free / 2 ** 30
    bad = ram < RAM_MIN or c < C_MIN
    if bad and not low:
        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            mi = p.info.get("memory_info")
            if mi:
                procs.append((mi.rss, p.info["name"], p.info["pid"]))
        top = ", ".join(f"{n}:{pid}:{rss / 2 ** 30:.1f}G" for rss, n, pid in sorted(procs, reverse=True)[:5])
        print(f"LOW: RAM {ram:.1f} GB, disk {c:.1f} GB; top: {top}", flush=True)
    elif low and not bad:
        print(f"OK again: RAM {ram:.1f} GB, disk {c:.1f} GB", flush=True)
    low = bad
    time.sleep(10)
