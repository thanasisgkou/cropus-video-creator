"""Extract GPS fixes from GoPro HERO9 GPMF telemetry and build a clean clip catalog.

Usage: python gopro_gps.py <source_dir> <out_csv>
"""
import csv, json, struct, subprocess, sys
from pathlib import Path

def gpmd_index(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=index,codec_tag_string", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    for s in json.loads(out).get("streams", []):
        if s.get("codec_tag_string") == "gpmd":
            return s["index"]
    return None

def raw_gpmd(path, idx):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", f"0:{idx}",
                           "-c", "copy", "-f", "rawvideo", "-"], capture_output=True).stdout

def walk(buf, start, end, ctx, fixes):
    i = start
    while i + 8 <= end:
        key = buf[i:i+4]
        typ = buf[i+4:i+5]
        size = buf[i+5]
        rep = struct.unpack(">H", buf[i+6:i+8])[0]
        length = size * rep
        data = buf[i+8:i+8+length]
        nxt = i + 8 + ((length + 3) & ~3)
        if typ == b"\x00":
            walk(buf, i + 8, i + 8 + length, dict(ctx), fixes)
        elif key == b"SCAL":
            fmt = {b"l": "l", b"s": "h", b"L": "L", b"S": "H"}.get(typ)
            if fmt:
                n = length // struct.calcsize(fmt)
                ctx["scal"] = struct.unpack(">" + fmt * n, data[:n * struct.calcsize(fmt)])
        elif key == b"GPSF":
            ctx["fix"] = struct.unpack(">L", data[:4])[0]
        elif key == b"GPSP":
            ctx["dop"] = struct.unpack(">H", data[:2])[0] / 100.0
        elif key == b"GPSU":
            ctx["utc"] = data[:16].decode("ascii", "ignore")
        elif key == b"GPS5" and typ == b"l":
            scal = ctx.get("scal", (1,) * 5)
            if len(scal) == 1:
                scal = scal * 5
            for r in range(rep):
                vals = struct.unpack(">5l", data[r*20:(r+1)*20])
                lat, lon, alt, spd = (vals[k] / scal[k] for k in range(4))
                fixes.append({"lat": lat, "lon": lon, "alt": alt, "speed": spd,
                              "fix": ctx.get("fix", 0), "dop": ctx.get("dop", 99), "utc": ctx.get("utc", "")})
        i = nxt

def main(src, out_csv):
    src = Path(src)
    rows = []
    for mp4 in sorted(src.glob("G*.MP4")):
        meta = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
            "format=duration,size:format_tags=creation_time", "-of", "json", str(mp4)],
            capture_output=True, text=True).stdout)["format"]
        row = {"file": mp4.name, "camera_time": meta.get("tags", {}).get("creation_time", "")[:19],
               "duration": round(float(meta["duration"]), 2), "size_mb": round(int(meta["size"]) / 1e6),
               "gps_utc": "", "lat": "", "lon": "", "alt": "", "max_speed_kmh": "", "gps_fixes": 0}
        idx = gpmd_index(mp4)
        if idx is not None:
            fixes = []
            buf = raw_gpmd(mp4, idx)
            walk(buf, 0, len(buf), {}, fixes)
            good = [f for f in fixes if f["fix"] >= 2 and f["dop"] < 10 and abs(f["lat"]) > 0.01]
            row["gps_fixes"] = len(good)
            if good:
                mid = good[len(good) // 2]
                row.update(gps_utc=mid["utc"], lat=round(mid["lat"], 5), lon=round(mid["lon"], 5),
                           alt=round(mid["alt"]), max_speed_kmh=round(max(f["speed"] for f in good) * 3.6))
        rows.append(row)
        print(row["file"], row["camera_time"], row["lat"], row["lon"], flush=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
