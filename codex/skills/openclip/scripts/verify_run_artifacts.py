#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


LANGS = ["en", "ko", "es", "ja", "zh-Hans"]


def ffprobe(path: Path) -> dict:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,duration,width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"ffprobe failed for {path}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    run_dir = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else None
    if run_dir is None:
        print("usage: verify_run_artifacts.py RUN_DIR", file=sys.stderr)
        return 2

    manifest_path = run_dir / "manifest.json"
    assert_true(manifest_path.exists(), f"missing manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert_true(manifest.get("status") == "success", "manifest status is not success")
    assert_true((run_dir / "analysis" / "candidate_selection.json").exists(), "missing candidate_selection.json")

    outputs = manifest.get("outputs", [])
    assert_true(outputs, "manifest has no outputs")
    checked = []
    for output in outputs:
        output_id = str(output["id"])
        kind = str(output["kind"])
        path = Path(str(output["path"]))
        assert_true(path.exists(), f"missing mp4 for {output_id}: {path}")
        data = ffprobe(path)
        streams = data.get("streams", [])
        stream_types = [stream.get("codec_type") for stream in streams]
        assert_true("video" in stream_types, f"{output_id} has no video stream")
        assert_true("data" not in stream_types, f"{output_id} still has a data stream")
        fmt_duration = float(data["format"]["duration"])
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        width = int(video.get("width", 0))
        height = int(video.get("height", 0))

        if kind == "short":
            assert_true(width == 1080 and height == 1920, f"{output_id} is not 9:16 1080x1920")
            assert_true(30.0 <= fmt_duration <= 60.5, f"{output_id} duration is not 30-60s: {fmt_duration}")
        elif kind == "long":
            assert_true(480.0 <= fmt_duration <= 720.5, f"{output_id} duration is not 8-12m: {fmt_duration}")
        elif kind == "edited_original":
            pass

        subtitles = output.get("subtitles", {})
        for lang in LANGS:
            subtitle_path = Path(str(subtitles.get(lang, "")))
            assert_true(subtitle_path.exists() and subtitle_path.stat().st_size > 0, f"{output_id} missing {lang} SRT")

        if kind in {"short", "long"}:
            thumbnail = output.get("thumbnail") or {}
            thumbnail_path = Path(str(thumbnail.get("path", "")))
            assert_true(thumbnail_path.exists() and thumbnail_path.stat().st_size > 0, f"{output_id} missing thumbnail")

        checked.append({"id": output_id, "kind": kind, "duration": round(fmt_duration, 3), "streams": stream_types})

    print(json.dumps({"status": "pass", "run_dir": str(run_dir), "checked": checked}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"VERIFY_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
