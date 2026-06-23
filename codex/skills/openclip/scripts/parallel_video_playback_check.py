#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont, ImageStat
except Exception:  # pragma: no cover - reported at runtime for skill use.
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageStat = None


@dataclass(frozen=True)
class CheckConfig:
    run_dir: Path
    workers: int
    sample_count: int
    full_decode: bool
    write_manifest: bool
    min_mean_luma: float
    min_luma_stddev: float


def main() -> int:
    args = parse_args()
    config = CheckConfig(
        run_dir=args.run_dir.expanduser().resolve(),
        workers=args.workers,
        sample_count=args.sample_count,
        full_decode=args.full_decode,
        write_manifest=args.write_manifest,
        min_mean_luma=args.min_mean_luma,
        min_luma_stddev=args.min_luma_stddev,
    )
    result = run_checks(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parallel playback/decode validation for OpenClip outputs.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--workers", type=int, default=max(2, min(6, (os.cpu_count() or 4))))
    parser.add_argument("--sample-count", type=int, default=5)
    parser.add_argument("--full-decode", action="store_true")
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--min-mean-luma", type=float, default=2.0)
    parser.add_argument("--min-luma-stddev", type=float, default=1.0)
    return parser.parse_args()


def run_checks(config: CheckConfig) -> dict[str, Any]:
    manifest_path = config.run_dir / "manifest.json"
    if not manifest_path.exists():
        return {"status": "fail", "error": f"missing manifest: {manifest_path}"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    outputs = [output for output in manifest.get("outputs", []) if Path(str(output.get("path", ""))).suffix == ".mp4"]
    work_dir = config.run_dir / "analysis" / "playback_checks"
    work_dir.mkdir(parents=True, exist_ok=True)

    checked: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, config.workers)) as pool:
        futures = {
            pool.submit(check_output, config, output, work_dir / str(output["id"])): output
            for output in outputs
        }
        for future in as_completed(futures):
            checked.append(future.result())
    checked.sort(key=lambda item: str(item["id"]))

    contact_sheet_path = build_contact_sheet(work_dir, checked)
    failures = [item for item in checked if item["status"] != "pass"]
    result = {
        "schema_version": "playback-check-v1",
        "status": "fail" if failures else "pass",
        "run_dir": str(config.run_dir),
        "workers": config.workers,
        "parallelized": True,
        "sample_count": config.sample_count,
        "full_decode": config.full_decode,
        "contact_sheet_path": str(contact_sheet_path) if contact_sheet_path else None,
        "checked_count": len(checked),
        "failure_count": len(failures),
        "checked": checked,
    }
    result_path = work_dir / "playback_check.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if config.write_manifest:
        manifest["playback_validation"] = {
            "status": result["status"],
            "parallelized": True,
            "workers": config.workers,
            "sample_count": config.sample_count,
            "full_decode": config.full_decode,
            "checked_count": len(checked),
            "failure_count": len(failures),
            "result_path": str(result_path),
            "contact_sheet_path": result["contact_sheet_path"],
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def check_output(config: CheckConfig, output: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_id = str(output["id"])
    path = Path(str(output["path"]))
    errors: list[str] = []
    sample_records: list[dict[str, Any]] = []
    try:
        probe = ffprobe(path)
        streams = probe.get("streams", [])
        stream_types = [stream.get("codec_type") for stream in streams]
        duration = float(probe["format"]["duration"])
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        width = int(video.get("width", 0))
        height = int(video.get("height", 0))
        if "video" not in stream_types:
            errors.append("missing video stream")
        if "audio" not in stream_types:
            errors.append("missing audio stream")
        if "data" in stream_types:
            errors.append("unexpected data stream")
        manifest_duration = float(output.get("duration_seconds") or 0.0)
        if manifest_duration and abs(duration - manifest_duration) > 0.75:
            errors.append(f"duration mismatch: manifest={manifest_duration:.3f}, actual={duration:.3f}")

        for index, position in enumerate(sample_positions(duration, config.sample_count), start=1):
            frame_path = output_dir / f"sample_{index:02d}_{position:.3f}.jpg"
            extract_frame(path, position, frame_path)
            frame_record = analyze_frame(frame_path, config)
            frame_record["position_seconds"] = round(position, 3)
            frame_record["path"] = str(frame_path)
            sample_records.append(frame_record)
            if not frame_record["nonblank"]:
                errors.append(
                    f"blank-looking frame at {position:.3f}s "
                    f"(mean={frame_record['mean_luma']:.2f}, stddev={frame_record['luma_stddev']:.2f})"
                )

        audio_decode = decode_audio_sample(path, duration)
        if not audio_decode["ok"]:
            errors.append(f"audio decode failed: {audio_decode['stderr'][:240]}")

        full_decode = {"ran": False, "ok": None}
        if config.full_decode:
            full_decode = decode_full_media(path, duration)
            if not full_decode["ok"]:
                errors.append(f"full media decode failed: {full_decode['stderr'][:240]}")

        return {
            "id": output_id,
            "kind": output.get("kind"),
            "path": str(path),
            "status": "fail" if errors else "pass",
            "errors": errors,
            "duration_seconds": round(duration, 3),
            "width": width,
            "height": height,
            "stream_types": stream_types,
            "samples": sample_records,
            "audio_decode": audio_decode,
            "full_decode": full_decode,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": output_id,
            "kind": output.get("kind"),
            "path": str(path),
            "status": "fail",
            "errors": [f"{exc.__class__.__name__}: {exc}"],
            "samples": sample_records,
        }


def ffprobe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,duration,width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"ffprobe failed: {path}")
    return json.loads(proc.stdout)


def sample_positions(duration: float, sample_count: int) -> list[float]:
    if duration <= 0:
        return [0.0]
    if sample_count <= 1:
        return [min(1.0, duration / 2)]
    fractions = [0.02, 0.10, 0.50, 0.90, 0.98]
    if sample_count != len(fractions):
        fractions = [index / max(1, sample_count - 1) for index in range(sample_count)]
    positions = []
    for fraction in fractions:
        position = duration * fraction
        position = max(0.0, min(max(0.0, duration - 0.25), position))
        positions.append(round(position, 3))
    return sorted(set(positions))


def extract_frame(video_path: Path, position: float, frame_path: Path) -> None:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{position:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=480:-1",
            str(frame_path),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    if proc.returncode != 0 or not frame_path.exists():
        raise RuntimeError(proc.stderr.strip() or f"failed to extract frame at {position:.3f}s")


def analyze_frame(frame_path: Path, config: CheckConfig) -> dict[str, Any]:
    if Image is None or ImageStat is None:
        raise RuntimeError("Pillow is required for frame analysis")
    with Image.open(frame_path) as image:
        luma = image.convert("L")
        stat = ImageStat.Stat(luma)
        mean_luma = float(stat.mean[0])
        luma_stddev = float(stat.stddev[0])
    return {
        "mean_luma": round(mean_luma, 3),
        "luma_stddev": round(luma_stddev, 3),
        "nonblank": mean_luma >= config.min_mean_luma and luma_stddev >= config.min_luma_stddev,
    }


def decode_audio_sample(video_path: Path, duration: float) -> dict[str, Any]:
    start = max(0.0, min(duration * 0.45, max(0.0, duration - 3.0)))
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            "3",
            "-i",
            str(video_path),
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    return {"ok": proc.returncode == 0, "start_seconds": round(start, 3), "stderr": proc.stderr.strip()}


def decode_full_media(video_path: Path, duration: float) -> dict[str, Any]:
    timeout = max(180, min(1800, int(math.ceil(duration * 2.0))))
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-f",
            "null",
            "-",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    return {"ran": True, "ok": proc.returncode == 0, "timeout_seconds": timeout, "stderr": proc.stderr.strip()}


def build_contact_sheet(work_dir: Path, checked: list[dict[str, Any]]) -> Path | None:
    if Image is None or ImageDraw is None:
        return None
    frame_paths: list[tuple[str, Path]] = []
    for item in checked:
        for sample in item.get("samples", []):
            path = Path(str(sample.get("path", "")))
            if path.exists():
                frame_paths.append((str(item["id"]), path))
    if not frame_paths:
        return None

    cols = 5
    cell_w = 220
    cell_h = 170
    label_h = 24
    pad = 14
    rows = math.ceil(len(frame_paths) / cols)
    sheet = Image.new("RGB", (cols * (cell_w + pad) + pad, rows * (cell_h + label_h + pad) + pad), (18, 20, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 13) if ImageFont else None
    except Exception:
        font = None
    for index, (output_id, path) in enumerate(frame_paths):
        row = index // cols
        col = index % cols
        x = pad + col * (cell_w + pad)
        y = pad + row * (cell_h + label_h + pad)
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((cell_w, cell_h))
            frame = Image.new("RGB", (cell_w, cell_h), (6, 7, 9))
            frame.paste(image, ((cell_w - image.width) // 2, (cell_h - image.height) // 2))
            sheet.paste(frame, (x, y))
        draw.text((x, y + cell_h + 5), f"{output_id} {path.stem.split('_')[1]}", fill=(235, 235, 235), font=font)
    contact_sheet = work_dir / "playback_contact_sheet.jpg"
    sheet.save(contact_sheet, quality=90)
    return contact_sheet


if __name__ == "__main__":
    raise SystemExit(main())
