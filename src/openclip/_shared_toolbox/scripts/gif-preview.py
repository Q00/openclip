#!/usr/bin/env python3
"""Make a small looping GIF preview from a video clip range."""

import argparse
import json
import shutil
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--out")
    ap.add_argument("--width", type=int, default=480)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        available = shutil.which("ffmpeg") is not None
        print(json.dumps({"tool": "gif_preview", "selftest": True, "ffmpeg": available}))
        return 0 if available else 2
    missing = [name for name in ("input", "start", "end", "out") if getattr(a, name) is None]
    if missing:
        print(json.dumps({"error": f"missing required flags: {', '.join(missing)}"}))
        return 2
    dur = max(0.1, a.end - a.start)
    vf = f"fps={a.fps},scale={a.width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{a.start:.3f}",
         "-t", f"{dur:.3f}", "-i", a.input, "-vf", vf, "-loop", "0", a.out],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(json.dumps({"error": r.stderr[-300:]}))
        return 1
    print(json.dumps({"tool": "gif_preview", "output": a.out, "seconds": round(dur, 2)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
