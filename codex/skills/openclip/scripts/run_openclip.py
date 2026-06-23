#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[4]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex skill wrapper for OpenClip.")
    parser.add_argument("input_video")
    parser.add_argument("--out", required=True)
    parser.add_argument("--shorts", type=int, default=5)
    parser.add_argument("--long-candidates", type=int, default=2)
    parser.add_argument("--target-long-minutes", type=float, default=10.0)
    parser.add_argument("--stt-model", default="whisper-1")
    parser.add_argument("--analysis-model", default="gpt-4o-mini")
    parser.add_argument("--translation-model", default="gpt-4o-mini")
    parser.add_argument("--thumbnail-model", default="gpt-image-2")
    parser.add_argument("--mock-openai", action="store_true")
    parser.add_argument("--clean-on-fail", action="store_true")
    parser.add_argument("--strategy-approved", action="store_true")
    parser.add_argument("--max-source-seconds", type=float, default=None)
    parser.add_argument("--all-short-candidates", action="store_true")
    parser.add_argument("--all-long-candidates", action="store_true")
    parser.add_argument("--burn-short-ko-subtitles", action="store_true")
    return parser


def apply_local_openai_env(env: dict[str, str], project_dir: Path) -> dict[str, str]:
    env = env.copy()
    env.pop("OPENAI_BASE_URL", None)
    dotenv = parse_dotenv(project_dir / ".env")
    key = dotenv.get("OPENAI_API_KEY") or dotenv.get("OPEN_API_KEY")
    if key:
        env["OPENAI_API_KEY"] = key
    return env


def parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def main() -> int:
    args = build_parser().parse_args()
    input_video = Path(args.input_video).expanduser()
    if not input_video.exists():
        print(f"ERROR: input video not found: {input_video}", file=sys.stderr)
        return 2
    if not PROJECT_DIR.exists():
        print(f"ERROR: OpenClip project not found: {PROJECT_DIR}", file=sys.stderr)
        return 2

    cmd = [
        "uv",
        "run",
        "openclip",
        "run",
        str(input_video),
        "--out",
        args.out,
        "--shorts",
        str(args.shorts),
        "--long-candidates",
        str(args.long_candidates),
        "--target-long-minutes",
        str(args.target_long_minutes),
        "--stt-model",
        args.stt_model,
        "--analysis-model",
        args.analysis_model,
        "--translation-model",
        args.translation_model,
        "--thumbnail-model",
        args.thumbnail_model,
    ]
    if args.mock_openai:
        cmd.append("--mock-openai")
    if args.clean_on_fail:
        cmd.append("--clean-on-fail")
    if args.strategy_approved:
        cmd.append("--strategy-approved")
    if args.max_source_seconds is not None:
        cmd += ["--max-source-seconds", str(args.max_source_seconds)]
    if args.all_short_candidates:
        cmd.append("--all-short-candidates")
    if args.all_long_candidates:
        cmd.append("--all-long-candidates")
    if args.burn_short_ko_subtitles:
        cmd.append("--burn-short-ko-subtitles")

    env = apply_local_openai_env(os.environ.copy(), PROJECT_DIR)
    if not args.mock_openai and not env.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY or OPEN_API_KEY in .env is required for non-mock runs.", file=sys.stderr)
        return 2

    return subprocess.run(cmd, cwd=PROJECT_DIR, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
