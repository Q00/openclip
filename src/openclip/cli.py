from __future__ import annotations

import argparse
import sys

from . import __version__
from .pipeline import HarnessConfig, run_harness


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openclip",
        description="Generate shorts, long-form candidates, subtitles, thumbnails, and review packets from a source video.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Generate video candidates and subtitles")
    run.add_argument("input_video")
    run.add_argument("--out", required=True)
    run.add_argument("--shorts", type=int, default=5)
    run.add_argument("--long-candidates", type=int, default=2)
    run.add_argument("--target-long-minutes", type=float, default=10.0)
    run.add_argument("--subtitle-langs", default="en,ko,es,ja,zh-Hans")
    run.add_argument("--stt-model", default="whisper-1")
    run.add_argument("--analysis-model", default="gpt-4o-mini")
    run.add_argument("--translation-model", default="gpt-4o-mini")
    run.add_argument("--thumbnail-model", default="gpt-image-2")
    run.add_argument("--mock-openai", action="store_true")
    run.add_argument("--clean-on-fail", action="store_true")
    run.add_argument("--strategy-approved", action="store_true")
    run.add_argument("--max-source-seconds", type=float, default=None, help="Developer aid for bounded trial runs")
    run.add_argument("--all-short-candidates", action="store_true")
    run.add_argument("--all-long-candidates", action="store_true")
    run.add_argument("--burn-short-ko-subtitles", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "run":
        raise AssertionError(args.command)

    config = HarnessConfig(
        input_video=args.input_video,
        out_dir=args.out,
        shorts=args.shorts,
        long_candidates=args.long_candidates,
        target_long_minutes=args.target_long_minutes,
        subtitle_langs=[part.strip() for part in args.subtitle_langs.split(",") if part.strip()],
        stt_model=args.stt_model,
        analysis_model=args.analysis_model,
        translation_model=args.translation_model,
        thumbnail_model=args.thumbnail_model,
        mock_openai=args.mock_openai,
        clean_on_fail=args.clean_on_fail,
        strategy_approved=args.strategy_approved,
        max_source_seconds=args.max_source_seconds,
        all_short_candidates=args.all_short_candidates,
        all_long_candidates=args.all_long_candidates,
        burn_short_ko_subtitles=args.burn_short_ko_subtitles,
    )
    try:
        run_harness(config)
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        return 130
    return 0
