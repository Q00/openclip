#!/usr/bin/env python3
"""Make a small looping GIF preview from a video clip range. Authored by an agent."""
import argparse, json, subprocess, sys
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True); ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=480); ap.add_argument("--fps", type=int, default=10)
    a = ap.parse_args()
    dur = max(0.1, a.end - a.start)
    vf = f"fps={a.fps},scale={a.width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    r = subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-ss",f"{a.start:.3f}",
        "-t",f"{dur:.3f}","-i",a.input,"-vf",vf,"-loop","0",a.out], capture_output=True, text=True)
    if r.returncode != 0:
        print(json.dumps({"error": r.stderr[-300:]})); sys.exit(1)
    print(json.dumps({"tool":"gif_preview","output":a.out,"seconds":round(dur,2)}))
if __name__ == "__main__": main()
