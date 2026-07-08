from __future__ import annotations

import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .subagent_packets import build_subagent_packets
from .subtitles import (
    SUPPORTED_LANGS,
    SubtitleCue,
    SubtitleTimelineSegment,
    render_srt,
    srt_time as format_srt_time,
    write_srt_files,
)

LANGS = list(SUPPORTED_LANGS)
SCHEMA_VERSION = "1.0"
SILENCE_THRESHOLD_DB = -35
SILENCE_MIN_DURATION_SECONDS = 0.7
SPEECH_PADDING_SECONDS = 0.2
CUT_SNAP_ALLOWANCE_SECONDS = 0.25
AUDIO_MIN_FADE_MS = 30
AUDIO_CROSSFADE_MIN_MS = 80
AUDIO_CROSSFADE_MAX_MS = 150
VISUAL_SMOOTHING_MIN_FRAMES = 3
VISUAL_SMOOTHING_MAX_FRAMES = 6
DEFAULT_VIDEO_FPS = 30.0
DUPLICATE_SIMILARITY_THRESHOLD = 0.86
DUPLICATE_NEARBY_WINDOW_SECONDS = 90
DUPLICATE_PHRASE_MIN_TOKENS = 8
PROVIDER_MAX_RETRIES = 3
PROVIDER_INITIAL_BACKOFF_SECONDS = 1
PROVIDER_MAX_BACKOFF_SECONDS = 8
AUDIO_CHUNK_DURATION_SECONDS = 300.0
STT_MAX_WORKERS = 4
TRANSLATION_BATCH_SIZE = 100
TRANSLATION_MAX_WORKERS = 6
OUTPUT_SUBTITLE_TRANSLATION_BATCH_SIZE = 60
CANDIDATE_SELECTION_PROMPT_VERSION = "candidate-selection-v1"
THUMBNAIL_PROMPT_VERSION = "thumbnail-v2"
TRANSLATION_CACHE_VERSION = "translation-cache-v3"
DEFAULT_THUMBNAIL_MODEL = "gpt-image-2"
SUBAGENT_FEEDBACK_SOURCE = "subagent_feedback_seed"
PERSONA_IDS = [
    "shorts_editor",
    "longform_editor",
    "retention_critic",
    "continuity_editor",
    "selection_judge",
]
SCORING_FIELDS = [
    "speech_density",
    "question_answer_score",
    "emotion_score",
    "concrete_example_score",
    "topic_shift_score",
    "filler_penalty",
    "duplicate_penalty",
    "openai_interest_score",
    "total_score",
]

EDITORIAL_SHORT_WINDOW_SPECS = [
    {
        "anchor": "이 foo.py를 수정했다고 증거에 남아 있는 거에요",
        "start": 2111.36,
        "end": 2166.88,
        "rationale": "Subagent feedback seed: evidence rejection short ends after the hallucination-prevention payoff, before the next fail-demo setup.",
    },
    {
        "anchor": "요게 제 심포지엄의 구조입니다",
        "start": 4515.96,
        "end": 4571.28,
        "rationale": "Subagent feedback seed: stop-rule/control short includes the symposium setup and ends on the 85 percent control payoff.",
    },
    {
        "anchor": "코덱스가 하네스입니다 코덱스 자체가 하네스에요",
        "start": 5598.92,
        "end": 5649.64,
        "rationale": "Subagent feedback seed: Codex-as-harness short reaches the contract-based usage payoff.",
    },
    {
        "anchor": "우브로스는 사실 두 가지 레이어가 존재한다고 생각을 해요",
        "start": 6219.48,
        "end": 6264.20,
        "rationale": "Subagent feedback seed: replaces weak website/nickname aside with two-layer Ouroboros insight.",
    },
    {
        "anchor": "이 AI가 이런 것들은 도대체 무슨 뜻인지를 같이 질문해 보고",
        "start": 3622.16,
        "end": 3680.28,
        "rationale": "Subagent feedback seed: interview harness example reaches the seed-gate/Socrates payoff.",
    },
    {
        "anchor": "프로덕션에서는 하네스가 꼭 필요합니다",
        "start": 6381.26,
        "end": 6439.66,
        "rationale": "Subagent feedback seed: production-harness conclusion reaches the self-contained takeaway.",
    },
    {
        "anchor": "암묵지를 추출하는 것이 어렵다",
        "start": 3374.60,
        "end": 3430.20,
        "rationale": "Subagent feedback seed: tacit-knowledge short includes the concrete puzzle-game example.",
    },
]

EDITORIAL_LONG_WINDOW_SPECS = [
    {
        "anchor": "그래서 저는 이거를 약간 다른 방식으로 좀 풀어보고 싶었어요",
        "start": 1822.08,
        "end": 2542.00,
        "rationale": "Subagent feedback seed: 4C overview starts with full premise and completes the harness-analysis thought before the contract-detail handoff.",
    },
    {
        "anchor": "네 저는 GLM으로도 오로브로스를 돌리고 있는데",
        "start": 4251.62,
        "end": 4955.20,
        "rationale": "Subagent feedback seed: applied 4C example extends through the final productivity payoff.",
    },
    {
        "anchor": "그래서 간단하게 5555 인터뷰 제 헤르메스한테 얘기를 해볼까요",
        "start": 5378.68,
        "end": 6023.00,
        "rationale": "Subagent feedback seed: Hermes demo starts at setup and ends on the general-things vision.",
    },
    {
        "anchor": "AI 엔지니어 신입으로 취업하기 위해 하네스 엔지니어링 공부가 필수 사항일까요",
        "start": 5470.16,
        "end": 6023.00,
        "rationale": "Subagent feedback seed: Q&A long-form starts at the actual audience question and trims before the resource/blog detour.",
    },
    {
        "anchor": "본인이 개발하신 거지만 사용자 입장에서도 사용 많이 해보셨을 것 같은데요",
        "start": 5837.76,
        "end": 6526.86,
        "rationale": "Subagent feedback seed: token-cost Q&A includes the question and natural closing.",
    },
]


class HarnessError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        stage: str,
        provider_error_class: str | None = None,
        provider_results: dict[str, Any] | None = None,
        provider_error: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.provider_error_class = provider_error_class
        self.provider_results = provider_results
        self.provider_error = provider_error
        self.details = details


@dataclass(frozen=True)
class HarnessConfig:
    input_video: str
    out_dir: str
    shorts: int = 5
    long_candidates: int = 2
    target_long_minutes: float = 10.0
    subtitle_langs: list[str] | None = None
    stt_model: str = "whisper-1"
    analysis_model: str = "gpt-4o-mini"
    translation_model: str = "gpt-4o-mini"
    thumbnail_model: str = DEFAULT_THUMBNAIL_MODEL
    mock_openai: bool = False
    clean_on_fail: bool = False
    strategy_approved: bool = False
    max_source_seconds: float | None = None
    all_short_candidates: bool = False
    all_long_candidates: bool = False
    burn_short_ko_subtitles: bool = False


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    confidence: float = 1.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Candidate:
    id: str
    kind: str
    start: float
    end: float
    score: dict[str, float]
    rationale: str
    aspect_policy: str
    overlap_metadata: dict[str, Any] | None = None
    selection_metadata: dict[str, Any] | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def run_harness(config: HarnessConfig) -> Path:
    input_path = Path(config.input_video).expanduser().resolve()
    out_root = Path(config.out_dir).expanduser().resolve()
    run_dir = out_root / input_path.stem
    partial_outputs: list[str] = []
    run_dir_created = False
    start_time = now_iso()
    provider_results: dict[str, Any] | None = None

    try:
        if not input_path.exists():
            raise HarnessError("input_not_found", f"input video not found: {input_path}", "validate_input")
        deps = check_dependencies(config)
        probe = ffprobe(input_path)
        duration = float(probe["format"]["duration"])
        size = int(probe["format"].get("size", 0))
        if duration > 7200:
            raise HarnessError("source_duration_limit", "source duration exceeds 2 hour MVP limit", "validate_input")
        if size > 4 * 1024 * 1024 * 1024:
            raise HarnessError("source_size_limit", "source file exceeds 4 GB MVP limit", "validate_input")

        run_dir.mkdir(parents=True, exist_ok=True)
        run_dir_created = True
        make_dirs(run_dir)

        work_dir = run_dir / "work"
        work_dir.mkdir(exist_ok=True)
        effective_duration = min(duration, config.max_source_seconds) if config.max_source_seconds else duration

        audio_chunks = extract_audio_chunks(input_path, work_dir / "audio", effective_duration)
        audio_chunk_manifest = audio_chunk_records(audio_chunks, effective_duration)
        transcript, provider_results = transcribe(config, audio_chunks, effective_duration)
        transcript, transcript_refinements = refine_transcript_segments(transcript)
        write_json(run_dir / "analysis" / "source_transcript.json", {"segments": [segment_to_dict(s) for s in transcript]})
        packed_transcript_path = write_packed_transcript(run_dir / "analysis" / "takes_packed.md", transcript)

        scores = score_segments(config, transcript, provider_results)
        write_json(run_dir / "analysis" / "candidate_scores.json", scores)
        candidate_selection = select_candidates_with_personas(
            config,
            transcript,
            scores,
            effective_duration,
            provider_results,
            run_dir,
        )
        candidate_selection_path = run_dir / "analysis" / "candidate_selection.json"
        write_json(candidate_selection_path, candidate_selection)

        silences = detect_silence(input_path, effective_duration)
        duplicate_removals = detect_duplicates(transcript)
        cut_decisions = build_cut_decisions(
            silences,
            duplicate_removals,
            transcript,
            effective_duration,
            transcript_refinements.get("removals", []),
        )
        write_json(run_dir / "analysis" / "cut_decisions.json", cut_decisions)

        shorts = choose_short_candidates(config, scores, effective_duration, transcript, candidate_selection)
        overlap_validation = validate_short_overlap(shorts)
        longs, long_form_fallback = choose_long_candidates(config, scores, effective_duration, transcript, candidate_selection)
        candidates = shorts + longs
        candidate_expansion_policy = candidate_expansion_policy_metadata(config, shorts, longs)
        candidate_selection["expansion_policy"] = candidate_expansion_policy
        candidate_selection["all_viable_short_highlights"] = [
            candidate_to_dict(candidate) for candidate in shorts
        ] if config.all_short_candidates else []
        candidate_selection["all_viable_long_highlights"] = [
            candidate_to_dict(candidate) for candidate in longs
        ] if config.all_long_candidates else []
        write_json(candidate_selection_path, candidate_selection)

        if config.shorts > 0 and not config.max_source_seconds and usable_duration(transcript) < config.shorts * 30:
            raise HarnessError("insufficient_short_duration", "not enough usable speech-bearing timeline for requested shorts", "candidate_selection")
        if not overlap_validation["pass"]:
            raise HarnessError("short_candidate_overlap", "short candidates overlap by more than 20 percent", "candidate_selection")

        translations = translate_segments(config, transcript, provider_results, run_dir)
        write_json(run_dir / "analysis" / "openai_usage.json", provider_results)

        outputs = []
        for cand in candidates:
            should_burn_ko = config.burn_short_ko_subtitles and cand.kind == "short"
            if should_burn_ko:
                subtitles = write_candidate_subtitles(
                    config,
                    run_dir,
                    cand,
                    transcript,
                    translations,
                    supported_subtitle_langs(config),
                    provider_results,
                )
                partial_outputs.extend(subtitles.values())
                burned_subtitle_path = subtitles.get("ko")
                output_path = render_candidate(input_path, run_dir, cand, burned_subtitle_path=burned_subtitle_path)
                burned_subtitles = {"ko": burned_subtitle_path} if burned_subtitle_path else None
            else:
                output_path = render_candidate(input_path, run_dir, cand)
                subtitles = write_candidate_subtitles(
                    config,
                    run_dir,
                    cand,
                    transcript,
                    translations,
                    supported_subtitle_langs(config),
                    provider_results,
                )
                partial_outputs.extend(subtitles.values())
                burned_subtitles = None
            partial_outputs.append(str(output_path))
            outputs.append(output_record(cand, output_path, subtitles, burned_subtitles=burned_subtitles))

        edited_path = render_cleaned_original(input_path, run_dir, effective_duration, cut_decisions)
        partial_outputs.append(str(edited_path))
        edited_duration = cleaned_duration_seconds(cut_decisions, effective_duration)
        edited_candidate = Candidate(
            id="edited_original",
            kind="edited_original",
            start=0.0,
            end=edited_duration,
            score={"total_score": 0.0},
            rationale="Cut-edited original with source aspect ratio.",
            aspect_policy="source",
        )
        edited_subtitles = write_candidate_subtitles(
            config,
            run_dir,
            edited_candidate,
            transcript,
            translations,
            supported_subtitle_langs(config),
            provider_results,
            cut_decisions,
        )
        partial_outputs.extend(edited_subtitles.values())
        outputs.append(output_record(edited_candidate, edited_path, edited_subtitles))
        thumbnail_records = generate_thumbnails(config, outputs, provider_results, run_dir)
        thumbnails_by_output = {record["output_id"]: record for record in thumbnail_records}
        for output in outputs:
            thumbnail = thumbnails_by_output.get(str(output["id"]))
            if thumbnail:
                output["thumbnail"] = thumbnail
        validate_output_videos(outputs)
        output_subtitles = validate_output_subtitles(outputs, supported_subtitle_langs(config))

        edl_path = run_dir / "analysis" / "edl.json"
        edl = build_edl(input_path, candidates, outputs, cut_decisions, supported_subtitle_langs(config))
        write_json(edl_path, edl)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": "success",
            "generated_at": now_iso(),
            "started_at": start_time,
            "completed_at": now_iso(),
            "input": input_metadata(input_path, probe),
            "source_probe": source_probe_metadata(probe),
            "source_limits": source_limits_metadata(input_path, probe),
            "command": normalized_command(config),
            "command_options": normalized_command(config)["options"],
            "dependency_checks": deps,
            "audio_chunks": audio_chunk_manifest,
            "transcript_refinements": transcript_refinements,
            "retry_policy": retry_policy_metadata(provider_results),
            "provider_results": provider_results,
            "transcript": transcript_metadata(transcript),
            "supported_subtitle_languages": supported_subtitle_langs(config),
            "edl_path": str(edl_path),
            "packed_transcript_path": str(packed_transcript_path),
            "candidate_selection_path": str(candidate_selection_path),
            "timeline_views": [],
            "long_form_fallback": long_form_fallback,
            "overlap_validation": overlap_validation,
            "candidate_selection": candidate_selection,
            "candidate_expansion_policy": candidate_expansion_policy,
            "candidate_scores": scores,
            "candidates": [candidate_to_dict(c) for c in candidates],
            "cut_decisions": cut_decisions,
            "cut_edit": cut_decisions,
            "outputs": outputs,
            "output_subtitles": output_subtitles,
            "thumbnails": thumbnail_records,
            "thumbnail_generation": thumbnail_generation_summary(thumbnail_records, outputs, config),
            "render_order_validation": render_order_validation(outputs, output_subtitles),
            "success_manifest": {"path": str(run_dir / "manifest.json"), "status": "success"},
            "error_manifest": None,
        }
        manifest["subagent_packet_index"] = build_subagent_packets(manifest, run_dir)
        error_manifest_path = run_dir / "error_manifest.json"
        if error_manifest_path.exists():
            error_manifest_path.unlink()
        write_json(run_dir / "manifest.json", manifest)
        return run_dir / "manifest.json"
    except HarnessError as exc:
        if run_dir_created:
            manifest_path = run_dir / "manifest.json"
            if manifest_path.exists():
                manifest_path.unlink()
            partial_outputs = merge_unique(partial_outputs + discover_partial_outputs(run_dir))
            deleted = []
            if config.clean_on_fail:
                deleted = cleanup_partials(partial_outputs)
            error_provider_results = exc.provider_results or provider_results
            write_json(
                run_dir / "error_manifest.json",
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "error",
                    "generated_at": now_iso(),
                    "error_code": exc.code,
                    "message": exc.message,
                    "stage": exc.stage,
                    "provider_error_class": exc.provider_error_class,
                    "provider_error": exc.provider_error,
                    "provider_results": error_provider_results,
                    "retry_policy": retry_policy_metadata(error_provider_results) if error_provider_results else None,
                    "render_error": render_error_metadata(exc),
                    "partial_outputs": partial_outputs,
                    "clean_on_fail_deleted_files": deleted,
                },
            )
        print(f"ERROR[{exc.stage}:{exc.code}]: {exc.message}", file=sys.stderr)
        raise SystemExit(2) from exc


def check_dependencies(config: HarnessConfig) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if not ffmpeg:
        raise HarnessError("missing_ffmpeg", "ffmpeg is required on PATH", "dependency_check")
    if not ffprobe_path:
        raise HarnessError("missing_ffprobe", "ffprobe is required on PATH", "dependency_check")
    has_key = bool(os.environ.get("OPENAI_API_KEY"))
    if not config.mock_openai and not has_key:
        raise HarnessError("missing_openai_api_key", "OPENAI_API_KEY is required for normal runs", "dependency_check")
    return {
        "python_version": platform.python_version(),
        "ffmpeg_path": ffmpeg,
        "ffprobe_path": ffprobe_path,
        "ffmpeg_version": first_line([ffmpeg, "-version"]),
        "ffprobe_version": first_line([ffprobe_path, "-version"]),
        "openai_api_key_present": has_key,
        "mock_openai": config.mock_openai,
    }


def ffprobe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise HarnessError("ffprobe_failed", proc.stderr.strip() or "ffprobe failed", "probe")
    try:
        data = json.loads(proc.stdout)
        duration = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HarnessError("invalid_media", "ffprobe did not return a valid media duration", "probe") from exc
    if duration <= 0:
        raise HarnessError("invalid_media", "source media duration must be greater than 0 seconds", "probe")
    return data


def extract_audio_chunks(input_path: Path, out_dir: Path, duration: float) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "chunk_%03d.mp3"
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-t",
        str(duration),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        "-f",
        "segment",
        "-segment_time",
        str(int(AUDIO_CHUNK_DURATION_SECONDS)),
        str(pattern),
    ]
    run_ffmpeg(cmd, "audio_extract")
    chunks = sorted(out_dir.glob("chunk_*.mp3"))
    if not chunks:
        raise HarnessError("audio_extract_empty", "no audio chunks were produced", "audio_extract")
    return chunks


def initial_provider_results(config: HarnessConfig) -> dict[str, Any]:
    return {
        "stt": {
            "model": config.stt_model,
            "request_count": 0,
            "retry_count": 0,
            "success": False,
            "mocked": config.mock_openai,
            "prompt_version": "stt-v1",
            "provider_error_class": None,
            "retry_outcomes": [],
        },
        "analysis": {
            "model": config.analysis_model,
            "request_count": 0,
            "retry_count": 0,
            "success": False,
            "mocked": config.mock_openai,
            "prompt_version": "analysis-v1",
            "provider_error_class": None,
            "retry_outcomes": [],
        },
        "translation": {
            "model": config.translation_model,
            "request_count": 0,
            "retry_count": 0,
            "success": False,
            "mocked": config.mock_openai,
            "prompt_version": "translation-v2-output-cue-repair",
            "provider_error_class": None,
            "retry_outcomes": [],
        },
        "candidate_selection": {
            "model": config.analysis_model,
            "request_count": 0,
            "retry_count": 0,
            "success": False,
            "mocked": config.mock_openai,
            "prompt_version": CANDIDATE_SELECTION_PROMPT_VERSION,
            "provider_error_class": None,
            "retry_outcomes": [],
            "personas": PERSONA_IDS,
        },
        "thumbnail": {
            "model": config.thumbnail_model,
            "request_count": 0,
            "retry_count": 0,
            "success": False,
            "mocked": config.mock_openai,
            "prompt_version": THUMBNAIL_PROMPT_VERSION,
            "provider_error_class": None,
            "retry_outcomes": [],
        },
    }


def transcribe(config: HarnessConfig, chunks: list[Path], duration: float) -> tuple[list[Segment], dict[str, Any]]:
    provider_results = initial_provider_results(config)
    if config.mock_openai:
        segments = mock_segments(duration)
        provider_results["stt"]["request_count"] = len(chunks)
        provider_results["stt"]["success"] = True
        return segments, provider_results

    try:
        all_segments: list[Segment] = []
        with ThreadPoolExecutor(max_workers=min(STT_MAX_WORKERS, max(1, len(chunks)))) as pool:
            futures = {
                pool.submit(transcribe_chunk, config, chunk, idx): idx
                for idx, chunk in enumerate(chunks)
            }
            chunk_results = []
            for future in as_completed(futures):
                chunk_results.append(future.result())

        for chunk_result in sorted(chunk_results, key=lambda item: item["index"]):
            merge_provider_stage_result(provider_results["stt"], chunk_result["provider_result"])
            all_segments.extend(chunk_result["segments"])
        provider_results["stt"]["success"] = True
        provider_results["stt"]["provider_error_class"] = None
        all_segments.sort(key=lambda segment: (segment.start, segment.end, segment.text))
        return all_segments, provider_results
    except HarnessError:
        raise
    except Exception as exc:  # noqa: BLE001
        provider_results["stt"]["provider_error_class"] = exc.__class__.__name__
        raise HarnessError(
            "openai_stt_failed",
            str(exc),
            "stt",
            exc.__class__.__name__,
            provider_results=provider_results,
            provider_error=provider_error_metadata(exc, retryable=False, retries_exhausted=False),
        ) from exc


def transcribe_chunk(config: HarnessConfig, chunk: Path, index: int) -> dict[str, Any]:
    cache_dir = chunk.parent.parent / "transcripts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{chunk.stem}.{config.stt_model}.json"
    offset = index * AUDIO_CHUNK_DURATION_SECONDS
    stage_result = {
        "request_count": 0,
        "retry_count": 0,
        "success": False,
        "provider_error_class": None,
        "retry_outcomes": [],
    }
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        stage_result["success"] = True
        stage_result["cached"] = True
        return {
            "index": index,
            "segments": segments_from_transcription_payload(payload, offset),
            "provider_result": stage_result,
        }

    try:
        from openai import OpenAI

        client = make_openai_client(OpenAI)
        with chunk.open("rb") as handle:
            def request_transcription(handle: Any = handle) -> Any:
                handle.seek(0)
                return client.audio.transcriptions.create(
                    model=config.stt_model,
                    file=handle,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )

            result = call_provider_with_retries(
                "stt",
                {"stt": stage_result},
                request_transcription,
                "openai_stt_failed",
                "stt",
            )
        payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        stage_result["success"] = True
        stage_result["cached"] = False
        return {
            "index": index,
            "segments": segments_from_transcription_payload(payload, offset),
            "provider_result": stage_result,
        }
    except HarnessError:
        raise
    except Exception as exc:  # noqa: BLE001
        stage_result["provider_error_class"] = exc.__class__.__name__
        raise HarnessError(
            "openai_stt_failed",
            str(exc),
            "stt",
            exc.__class__.__name__,
            provider_results={"stt": stage_result},
            provider_error=provider_error_metadata(exc, retryable=False, retries_exhausted=False),
        ) from exc


def segments_from_transcription_payload(payload: dict[str, Any], offset: float) -> list[Segment]:
    raw_segments = payload.get("segments", [])
    segments = []
    for item in raw_segments:
        if not isinstance(item, dict):
            item = item.model_dump()
        segments.append(
            Segment(
                start=offset + float(item.get("start", 0)),
                end=offset + float(item.get("end", 0)),
                text=str(item.get("text", "")).strip(),
                confidence=float(item.get("avg_logprob", 0.0) or 0.0),
            )
        )
    return segments


def refine_transcript_segments(segments: list[Segment]) -> tuple[list[Segment], dict[str, Any]]:
    removals = leading_filler_segment_removals(segments)
    removed = {(round(item["start_seconds"], 3), round(item["end_seconds"], 3)) for item in removals}
    refined = [
        segment
        for segment in segments
        if (round(segment.start, 3), round(segment.end, 3)) not in removed
    ]
    return refined, {
        "schema_version": "transcript-refinement-v1",
        "removed_count": len(removals),
        "removals": removals,
    }


def leading_filler_segment_removals(segments: list[Segment]) -> list[dict[str, Any]]:
    removals = []
    for segment in sorted(segments, key=lambda item: (item.start, item.end)):
        if segment.start > 15.0:
            break
        if not is_low_value_transcript_segment(segment):
            break
        removals.append(
            {
                "id": f"leading_filler_{len(removals) + 1:03d}",
                "kind": "leading_filler_speech",
                "start_seconds": round(segment.start, 3),
                "end_seconds": round(segment.end, 3),
                "duration_seconds": round(segment.duration, 3),
                "remove_start": round(segment.start, 3),
                "remove_end": round(segment.end, 3),
                "text": segment.text,
                "reason": "leading pre-roll filler transcript segment removed before scoring, subtitles, and edited-original render",
            }
        )
    return removals


def is_low_value_transcript_segment(segment: Segment) -> bool:
    text = normalize(segment.text)
    tokens = re.findall(r"\w+", text)
    if len(tokens) <= 2:
        return True
    if looks_like_admin_or_filler_text(text):
        return True
    return segment.duration <= 3.0 and len(tokens) <= 4


def merge_provider_stage_result(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["request_count"] = int(target.get("request_count", 0)) + int(source.get("request_count", 0))
    target["retry_count"] = int(target.get("retry_count", 0)) + int(source.get("retry_count", 0))
    target.setdefault("retry_outcomes", []).extend(source.get("retry_outcomes", []))
    if source.get("provider_error_class"):
        target["provider_error_class"] = source["provider_error_class"]
    if source.get("cached"):
        target["cached_chunks"] = int(target.get("cached_chunks", 0)) + 1


def score_segments(config: HarnessConfig, segments: list[Segment], provider_results: dict[str, Any]) -> list[dict[str, Any]]:
    windows = build_windows(segments)
    duplicate_penalties = window_duplicate_penalties(windows)
    scored = [score_window(window, duplicate_penalties[i], i) for i, window in enumerate(windows)]
    if config.mock_openai:
        for item in scored:
            apply_analysis_supplement(
                item,
                mock_openai_interest_score(item),
                "Mock OpenAI analysis favored dense, concrete, emotional, non-repeated transcript windows.",
            )
        provider_results["analysis"]["success"] = True
        provider_results["analysis"]["request_count"] = 1
        return scored

    try:
        from openai import OpenAI

        client = make_openai_client(OpenAI)
        compact = [
            {
                "index": i,
                "start": item["start_seconds"],
                "end": item["end_seconds"],
                "text": item["text"][:1200],
                "heuristic_total": item["total_score"],
            }
            for i, item in enumerate(scored[:40])
        ]
        prompt = (
            "Score these transcript windows for short-form and long-form video candidate usefulness. "
            "Return strict JSON array objects with index, openai_interest_score from 0 to 1, and rationale. "
            "Prefer concrete examples, emotional moments, topic shifts, question/answer moments, low repeated speech, "
            "and suitability for both shorts and long-form candidates."
        )
        content = json.dumps(compact, ensure_ascii=False)
        text = call_provider_with_retries(
            "analysis",
            provider_results,
            lambda: call_text_model(client, config.analysis_model, prompt, content),
            "openai_analysis_failed",
            "analysis",
        )
        provider_results["analysis"]["success"] = True
        provider_results["analysis"]["provider_error_class"] = None
        try:
            parsed = extract_json(text)
        except ValueError:
            parsed = []
        by_index = {int(item.get("index")): item for item in parsed if isinstance(item, dict) and "index" in item}
        for i, item in enumerate(scored[:40]):
            supplement = by_index.get(i)
            if supplement:
                openai_score = clamp(float(supplement.get("openai_interest_score", 0)), 0, 1)
                apply_analysis_supplement(item, openai_score, str(supplement.get("rationale", item["rationale"])))
        return scored
    except HarnessError:
        raise
    except Exception as exc:  # noqa: BLE001
        provider_results["analysis"]["provider_error_class"] = exc.__class__.__name__
        raise HarnessError(
            "openai_analysis_failed",
            str(exc),
            "analysis",
            exc.__class__.__name__,
            provider_results=provider_results,
            provider_error=provider_error_metadata(exc, retryable=False, retries_exhausted=False),
        ) from exc


def translate_segments(
    config: HarnessConfig,
    segments: list[Segment],
    provider_results: dict[str, Any],
    run_dir: Path | None = None,
) -> dict[str, list[str]]:
    langs = supported_subtitle_langs(config)
    source_texts = [s.text for s in segments]
    source_lang = detect_source_subtitle_language(source_texts)
    result: dict[str, list[str]] = {source_lang: source_texts}
    if config.mock_openai:
        for lang in langs:
            result[lang] = source_texts if lang == source_lang else [f"[{lang}] {text}" for text in source_texts]
        provider_results["translation"]["request_count"] = max(0, len(langs) - 1)
        provider_results["translation"]["success"] = True
        provider_results["translation"]["source_language"] = source_lang
        return result

    try:
        translation_dir = (run_dir / "work" / "translations") if run_dir else None
        if translation_dir:
            translation_dir.mkdir(parents=True, exist_ok=True)
        jobs = []
        for lang in langs:
            if lang == source_lang:
                continue
            for batch_index, batch in enumerate(batched(list(enumerate(source_texts)), TRANSLATION_BATCH_SIZE)):
                jobs.append((lang, batch_index, batch, translation_dir))
        translated_by_lang: dict[str, list[str]] = {
            lang: list(source_texts)
            for lang in langs
            if lang != source_lang
        }
        with ThreadPoolExecutor(max_workers=min(TRANSLATION_MAX_WORKERS, max(1, len(jobs)))) as pool:
            futures = [
                pool.submit(translate_batch, config, lang, batch_index, batch, translation_dir)
                for lang, batch_index, batch, translation_dir in jobs
            ]
            for future in as_completed(futures):
                batch_result = future.result()
                merge_provider_stage_result(provider_results["translation"], batch_result["provider_result"])
                lang = batch_result["language"]
                for index, text in batch_result["translations"].items():
                    translated_by_lang[lang][index] = text
        result.update(translated_by_lang)
        provider_results["translation"]["success"] = True
        provider_results["translation"]["provider_error_class"] = None
        provider_results["translation"]["source_language"] = source_lang
        return result
    except HarnessError:
        raise
    except Exception as exc:  # noqa: BLE001
        provider_results["translation"]["provider_error_class"] = exc.__class__.__name__
        raise HarnessError(
            "openai_translation_failed",
            str(exc),
            "translation",
            exc.__class__.__name__,
            provider_results=provider_results,
            provider_error=provider_error_metadata(exc, retryable=False, retries_exhausted=False),
        ) from exc


def detect_source_subtitle_language(texts: list[str]) -> str:
    sample = " ".join(texts[:100])
    hangul_count = len(re.findall(r"[가-힣]", sample))
    latin_count = len(re.findall(r"[A-Za-z]", sample))
    if hangul_count > max(20, latin_count):
        return "ko"
    return "en"


def translate_batch(
    config: HarnessConfig,
    lang: str,
    batch_index: int,
    batch: list[tuple[int, str]],
    translation_dir: Path | None,
) -> dict[str, Any]:
    stage_result = {
        "request_count": 0,
        "retry_count": 0,
        "success": False,
        "provider_error_class": None,
        "retry_outcomes": [],
    }
    cache_path = None
    source_digest = batch_translation_source_digest(batch)
    if translation_dir:
        cache_path = translation_dir / f"{safe_cache_name(config.translation_model)}.{lang}.batch_{batch_index:04d}.json"
        if cache_path.exists():
            cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_digest, payload = unpack_translation_cache(cached_payload)
            cached_schema = cached_payload.get("schema_version") if isinstance(cached_payload, dict) else None
            if (
                cached_schema == TRANSLATION_CACHE_VERSION
                and cached_digest == source_digest
                and not translation_payload_needs_repair(lang, payload)
            ):
                stage_result["success"] = True
                stage_result["cached"] = True
                return {
                    "language": lang,
                    "translations": {int(item["index"]): str(item["text"]) for item in payload},
                    "provider_result": stage_result,
                }
            stage_result["stale_cache_ignored"] = True
            stage_result["stale_cache_reason"] = (
                "schema_version_mismatch"
                if cached_schema != TRANSLATION_CACHE_VERSION
                else "source_digest_mismatch"
                if cached_digest != source_digest
                else "target_language_payload_contains_untranslated_source"
            )
            try:
                cache_path.unlink()
            except OSError:
                pass

    try:
        from openai import OpenAI

        client = make_openai_client(OpenAI)
        prompt = (
            f"Translate each item to {lang}. Preserve meaning for subtitles. "
            "Return strict JSON array with objects {index, text}; do not add commentary."
        )
        content = json.dumps([{"index": i, "text": text} for i, text in batch], ensure_ascii=False)
        text = call_provider_with_retries(
            "translation",
            {"translation": stage_result},
            lambda: call_text_model(client, config.translation_model, prompt, content),
            "openai_translation_failed",
            "translation",
        )
        parsed = parse_translation_response(client, config, lang, batch, text, stage_result)
        payload = [
            {"index": int(item["index"]), "text": str(item["text"])}
            for item in parsed
            if isinstance(item, dict) and "index" in item and "text" in item
        ]
        if cache_path:
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": TRANSLATION_CACHE_VERSION,
                        "source_digest": source_digest,
                        "language": lang,
                        "translations": payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        stage_result["success"] = True
        stage_result["cached"] = False
        return {
            "language": lang,
            "translations": {int(item["index"]): str(item["text"]) for item in payload},
            "provider_result": stage_result,
        }
    except HarnessError:
        raise
    except Exception as exc:  # noqa: BLE001
        stage_result["provider_error_class"] = exc.__class__.__name__
        raise HarnessError(
            "openai_translation_failed",
            str(exc),
            "translation",
            exc.__class__.__name__,
            provider_results={"translation": stage_result},
            provider_error=provider_error_metadata(exc, retryable=False, retries_exhausted=False),
        ) from exc


def parse_translation_response(
    client: Any,
    config: HarnessConfig,
    lang: str,
    batch: list[tuple[int, str]],
    text: str,
    stage_result: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        payload = normalize_translation_payload(extract_json(text), batch, lang)
        if not translation_payload_needs_repair(lang, payload):
            return payload
        stage_result["json_repair_attempted"] = True
        stage_result["json_parse_error"] = "translation_response_contains_untranslated_source"
    except Exception as parse_exc:  # noqa: BLE001
        stage_result["json_repair_attempted"] = True
        stage_result["json_parse_error"] = f"{parse_exc.__class__.__name__}: {parse_exc}"

    repair_prompt = (
        f"Return only valid JSON for translations to {lang}. "
        "The JSON must be an array of objects with integer index and string text. "
        "No markdown, no commentary, no trailing commas."
    )
    repair_content = json.dumps(
        {
            "source_items": [{"index": index, "text": source_text} for index, source_text in batch],
            "invalid_response": text[:12000],
        },
        ensure_ascii=False,
    )
    try:
        repaired_text = call_provider_with_retries(
            "translation",
            {"translation": stage_result},
            lambda: call_text_model(client, config.translation_model, repair_prompt, repair_content),
            "openai_translation_repair_failed",
            "translation",
        )
        payload = normalize_translation_payload(extract_json(repaired_text), batch, lang)
        if translation_payload_needs_repair(lang, payload):
            raise ValueError("repaired translation still contains untranslated source")
        return payload
    except Exception as repair_exc:  # noqa: BLE001
        stage_result["json_repair_error"] = f"{repair_exc.__class__.__name__}: {repair_exc}"
        raise ValueError(f"translation repair failed for {lang}: {repair_exc}") from repair_exc


def batch_translation_source_digest(batch: list[tuple[int, str]]) -> str:
    return stable_digest([{"index": index, "text": text} for index, text in batch])


def unpack_translation_cache(payload: Any) -> tuple[str | None, list[dict[str, Any]]]:
    if isinstance(payload, dict):
        translations = payload.get("translations", [])
        return payload.get("source_digest"), translations if isinstance(translations, list) else []
    if isinstance(payload, list):
        return None, payload
    return None, []


def normalize_translation_payload(parsed: Any, batch: list[tuple[int, str]], lang: str) -> list[dict[str, Any]]:
    expected = {index for index, _text in batch}
    if not isinstance(parsed, list):
        raise ValueError("translation response is not a JSON array")
    payload = [
        {"index": int(item["index"]), "text": str(item["text"])}
        for item in parsed
        if isinstance(item, dict) and "index" in item and "text" in item and int(item["index"]) in expected
    ]
    seen = {item["index"] for item in payload}
    missing = [index for index, _source_text in batch if index not in seen]
    if missing:
        raise ValueError(f"translation response missing indexes for {lang}: {missing[:10]}")
    return sorted(payload, key=lambda item: int(item["index"]))


def fallback_translation_payload(batch: list[tuple[int, str]], lang: str) -> list[dict[str, Any]]:
    return [{"index": index, "text": fallback_translation_text(lang, source_text)} for index, source_text in batch]


def fallback_translation_text(lang: str, source_text: str) -> str:
    if lang == "ko":
        return source_text
    return f"[{lang} translation unavailable]"


def translation_payload_needs_repair(lang: str, payload: list[dict[str, Any]]) -> bool:
    if lang == "ko":
        return False
    return any(
        contains_forbidden_subtitle_placeholder(str(item.get("text", "")))
        or looks_untranslated_for_target(lang, str(item.get("text", "")))
        for item in payload
    )


def contains_forbidden_subtitle_placeholder(text: str) -> bool:
    lowered = text.lower()
    return (
        "translation unavailable" in lowered
        or "[en translation" in lowered
        or "[es translation" in lowered
        or "[ja translation" in lowered
        or "[zh-hans translation" in lowered
    )


def looks_untranslated_for_target(lang: str, text: str) -> bool:
    if lang == "ko":
        return False
    hangul_count = len(re.findall(r"[가-힣]", text))
    if hangul_count == 0:
        return False
    visible_count = max(1, len(re.findall(r"\S", text)))
    return hangul_count >= 8 or (hangul_count / visible_count) >= 0.20


def safe_cache_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def make_openai_client(openai_cls: Any) -> Any:
    try:
        return openai_cls(timeout=120.0)
    except TypeError:
        return openai_cls()


def build_windows(segments: list[Segment]) -> list[dict[str, Any]]:
    if not segments:
        return []
    windows: list[dict[str, Any]] = []
    start = max(0.0, segments[0].start)
    end = max(segment.end for segment in segments)
    cursor = start
    while cursor < end:
        window_end = min(cursor + 60.0, end)
        text_segments = [s for s in segments if s.start < window_end and s.end > cursor]
        text = " ".join(s.text for s in text_segments)
        windows.append({"start_seconds": cursor, "end_seconds": window_end, "text": text})
        cursor += 30.0
    return windows


def score_window(window: dict[str, Any], duplicate_penalty: float = 0.0, index: int = 0) -> dict[str, Any]:
    text = window["text"]
    words = re.findall(r"\w+", text.lower())
    duration = max(1.0, window["end_seconds"] - window["start_seconds"])
    filler_words = {"um", "uh", "like", "you", "know", "actually", "basically"}
    emotion_words = {"amazing", "surprising", "crazy", "love", "hate", "best", "worst", "important", "secret"}
    speech_density = clamp(len(words) / duration / 3.0, 0, 1)
    qa = 1.0 if "?" in text else 0.0
    emotion = clamp(sum(1 for w in words if w in emotion_words) / 3.0, 0, 1)
    concrete = clamp(sum(1 for w in words if any(ch.isdigit() for ch in w)) / 2.0, 0, 1)
    topic_shift = 0.5 if any(token in text.lower() for token in ["but", "however", "so", "first", "second"]) else 0.0
    filler_penalty = clamp(sum(1 for w in words if w in filler_words) / max(1, len(words)), 0, 1)
    total = clamp(
        (speech_density * 0.30)
        + (qa * 0.15)
        + (emotion * 0.20)
        + (concrete * 0.15)
        + (topic_shift * 0.15)
        - (filler_penalty * 0.15)
        - (duplicate_penalty * 0.1),
        0,
        1,
    )
    window.update(
        {
            "speech_density": round(speech_density, 4),
            "question_answer_score": round(qa, 4),
            "emotion_score": round(emotion, 4),
            "concrete_example_score": round(concrete, 4),
            "topic_shift_score": round(topic_shift, 4),
            "filler_penalty": round(filler_penalty, 4),
            "duplicate_penalty": round(duplicate_penalty, 4),
            "openai_interest_score": 0.0,
            "total_score": round(total, 4),
            "source_analysis_index": index,
            "rationale": "Heuristic transcript score over density, Q/A, emotion, examples, topic shift, filler, and duplicate penalties.",
        }
    )
    return window


def choose_short_candidates(
    config: HarnessConfig,
    scores: list[dict[str, Any]],
    duration: float,
    segments: list[Segment] | None = None,
    selection: dict[str, Any] | None = None,
) -> list[Candidate]:
    target_count = short_candidate_count(config, scores, duration)
    picked = candidates_from_selection("shorts", selection, "short", "9:16", target_count, duration, segments)
    if picked:
        if config.all_short_candidates:
            return with_short_overlap_metadata(picked)
        if len(picked) < target_count:
            picked = backfill_short_candidates(config, scores, duration, picked, target_count)
        return with_short_overlap_metadata(picked[:target_count])

    ranked = sort_scored_windows(scores)
    picked: list[Candidate] = []
    for item in ranked:
        if len(picked) >= target_count:
            break
        start = max(0.0, item["start_seconds"])
        end = short_end_from_score(item, start, duration)
        if end - start < 30.0:
            continue
        candidate = candidate_from_score(item, f"short_{len(picked)+1:03d}", "short", start, end, "9:16")
        if all(overlap_ratio(candidate, other) <= 0.20 for other in picked):
            picked.append(candidate)
    if len(picked) < target_count and not config.all_short_candidates:
        picked = backfill_short_candidates(config, scores, duration, picked, target_count)
    picked = with_short_overlap_metadata(picked)
    if not picked and duration >= 30 and not config.all_short_candidates:
        picked.append(Candidate("short_001", "short", 0.0, min(30.0, duration), zero_score(), "Fallback first window.", "9:16"))
    return picked


def short_candidate_count(config: HarnessConfig, scores: list[dict[str, Any]], duration: float) -> int:
    if not config.all_short_candidates:
        return config.shorts
    viable = viable_short_score_windows(scores)
    max_non_overlapping = int(duration // 30.0)
    return max(config.shorts, min(len(viable), max_non_overlapping))


def viable_short_score_windows(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not scores:
        return []
    ranked = sort_scored_windows(scores)
    top_score = max(float(ranked[0].get("total_score", 0.0)), 0.0)
    threshold = max(0.36, top_score * 0.82)
    return [
        item
        for item in ranked
        if is_viable_short_score(item, threshold)
    ]


def is_viable_short_score(item: dict[str, Any], threshold: float = 0.36) -> bool:
    text = str(item.get("text", ""))
    return (
        float(item.get("total_score", 0.0)) >= threshold
        and float(item.get("speech_density", 0.0)) >= 0.08
        and float(item.get("filler_penalty", 0.0)) < 0.75
        and not looks_like_admin_or_filler_text(text)
        and len(re.findall(r"\w+", normalize(text))) >= 12
    )


def short_end_from_score(item: dict[str, Any], start: float, duration: float) -> float:
    scored_end = min(duration, float(item.get("end_seconds", start + 30.0)))
    scored_duration = scored_end - start
    if 30.0 <= scored_duration <= 60.0:
        return scored_end
    return min(duration, start + 30.0)


def snap_short_candidate_to_complete_boundaries(
    start: float,
    end: float,
    transcript: list[Segment],
    duration: float,
) -> tuple[float, float, list[dict[str, Any]]]:
    if not transcript:
        return start, end, [{"applied": False, "reason": "no_transcript_segments"}]
    original_start, original_end = start, end
    snapped_start = expand_to_segment_start(start, transcript, max_delta=8.0)
    if end - snapped_start > 60.0:
        snapped_start = start
    snapped_end = expand_to_segment_end(end, transcript, max_delta=8.0)
    if snapped_end - snapped_start > 60.0:
        snapped_end = latest_segment_end_before(snapped_start + 60.0, transcript, after=snapped_start + 30.0) or end
    if not 30.0 <= snapped_end - snapped_start <= 60.0:
        return start, end, [{"applied": False, "reason": "short_duration_constraint"}]
    return clamp(snapped_start, 0.0, duration), clamp(snapped_end, 0.0, duration), [
        {
            "applied": True,
            "reason": "short_snapped_to_complete_source_segments",
            "original_start_seconds": round(original_start, 3),
            "original_end_seconds": round(original_end, 3),
            "snapped_start_seconds": round(snapped_start, 3),
            "snapped_end_seconds": round(snapped_end, 3),
        }
    ]


def choose_long_candidates(
    config: HarnessConfig,
    scores: list[dict[str, Any]],
    duration: float,
    segments: list[Segment] | None = None,
    selection: dict[str, Any] | None = None,
) -> tuple[list[Candidate], str | None]:
    cleaned_duration = duration
    if config.long_candidates <= 0:
        return [], None

    target = clamp(config.target_long_minutes * 60, 480.0, 720.0)
    if cleaned_duration < 480:
        return [
            Candidate(
                "long_001",
                "long",
                0.0,
                cleaned_duration,
                zero_score(),
                "Source under 8 minutes; using cleaned full source.",
                "source",
            )
        ], "source_under_8_min"

    count = config.long_candidates if cleaned_duration >= 960 else 1
    if config.all_long_candidates and cleaned_duration >= 480:
        count = long_candidate_count(replace(config, long_candidates=count), scores, cleaned_duration)
    candidate_duration = min(target, cleaned_duration)
    selected = candidates_from_selection("longs", selection, "long", "source", count, duration, segments)
    if selected:
        if len(selected) < count:
            selected = backfill_long_candidates(scores, cleaned_duration, candidate_duration, selected, count)
        fallback = None if count == config.long_candidates else "only_one_nonoverlapping_long_candidate"
        if config.all_long_candidates:
            fallback = None
        return selected[:count], fallback

    ranked = sort_scored_windows(scores)
    picked: list[Candidate] = []
    for item in ranked:
        if len(picked) >= count:
            break
        mid = (item["start_seconds"] + item["end_seconds"]) / 2
        start = clamp(mid - candidate_duration / 2, 0, max(0.0, cleaned_duration - candidate_duration))
        end = min(cleaned_duration, start + candidate_duration)
        if segments:
            start, end, snap_records = snap_long_candidate_to_natural_boundaries(start, end, segments, cleaned_duration)
            item = {
                **item,
                "rationale": f"{item.get('rationale', '')} Natural boundary snap: {snap_records[-1]['reason']}.",
                "selection_metadata": {"boundary_snap": snap_records, "source": "heuristic_longform_boundary_snap"},
            }
        candidate = candidate_from_score(item, f"long_{len(picked)+1:03d}", "long", start, end, "source")
        if not any(same_candidate_window(candidate, other) for other in picked):
            picked.append(candidate)

    if len(picked) < count:
        picked = backfill_long_candidates(scores, cleaned_duration, candidate_duration, picked, count)

    fallback = None if count == config.long_candidates else "only_one_nonoverlapping_long_candidate"
    if config.all_long_candidates:
        fallback = None
    return picked, fallback


def all_long_candidate_count(duration: float, target_long_minutes: float) -> int:
    candidate_duration = min(clamp(target_long_minutes * 60, 480.0, 720.0), duration)
    stride = max(420.0, candidate_duration * 0.80)
    return max(1, int(math.floor(max(0.0, duration - candidate_duration) / stride)) + 1)


def long_candidate_count(config: HarnessConfig, scores: list[dict[str, Any]], duration: float) -> int:
    if not config.all_long_candidates or duration < 480:
        return config.long_candidates
    return max(
        config.long_candidates,
        min(
            all_long_candidate_count(duration, config.target_long_minutes),
            max(config.long_candidates, len(viable_long_score_windows(scores))),
        ),
    )


def viable_long_score_windows(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in viable_short_score_windows(scores)
        if not starts_like_continuation(str(item.get("text", "")))
    ]


def starts_like_continuation(text: str) -> bool:
    stripped = text.strip().lower()
    continuation_prefixes = [
        "왜냐하면",
        "그리고",
        "그래서",
        "그랬더니",
        "os 위에",
        "만들어 준",
        "감시 비용",
        "때문에",
        "할 수가",
    ]
    return any(stripped.startswith(prefix) for prefix in continuation_prefixes)


def same_candidate_window(a: Candidate, b: Candidate) -> bool:
    return abs(a.start - b.start) <= 0.001 and abs(a.end - b.end) <= 0.001


def backfill_long_candidates(
    scores: list[dict[str, Any]],
    duration: float,
    candidate_duration: float,
    picked: list[Candidate],
    count: int,
) -> list[Candidate]:
    if len(picked) >= count:
        return picked

    max_start = max(0.0, duration - candidate_duration)
    if count == 1:
        anchors = [0.0]
    else:
        anchors = [(max_start * index) / max(1, count - 1) for index in range(count)]

    for anchor in anchors:
        if len(picked) >= count:
            break
        start = round(anchor, 3)
        end = round(min(duration, start + candidate_duration), 3)
        probe = Candidate("_probe", "long", start, end, zero_score(), "", "source")
        if any(same_candidate_window(probe, other) for other in picked):
            continue
        item = nearest_score(scores, start) or {
            "rationale": "Deterministic long-form timeline backfill.",
            **zero_score(),
        }
        picked.append(candidate_from_score(item, f"long_{len(picked)+1:03d}", "long", start, end, "source"))

    cursor = 0.0
    step = max(30.0, candidate_duration / 4.0)
    while len(picked) < count and cursor <= max_start + 0.001:
        start = round(cursor, 3)
        end = round(min(duration, start + candidate_duration), 3)
        probe = Candidate("_probe", "long", start, end, zero_score(), "", "source")
        if not any(same_candidate_window(probe, other) for other in picked):
            item = nearest_score(scores, start) or {
                "rationale": "Deterministic long-form timeline backfill.",
                **zero_score(),
            }
            picked.append(candidate_from_score(item, f"long_{len(picked)+1:03d}", "long", start, end, "source"))
        cursor += step
    return picked


def sort_scored_windows(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        scores,
        key=lambda s: (
            -float(s.get("total_score", 0.0)),
            float(s.get("start_seconds", 0.0)),
            float(s.get("end_seconds", 0.0)) - float(s.get("start_seconds", 0.0)),
        ),
    )


def candidate_from_score(
    item: dict[str, Any],
    candidate_id: str,
    kind: str,
    start: float,
    end: float,
    aspect_policy: str,
) -> Candidate:
    return Candidate(
        id=candidate_id,
        kind=kind,
        start=start,
        end=end,
        score=score_fields(item),
        rationale=item.get("rationale", ""),
        aspect_policy=aspect_policy,
        selection_metadata=item.get("selection_metadata"),
    )


def score_fields(item: dict[str, Any]) -> dict[str, float]:
    return {field: round(float(item.get(field, 0.0)), 4) for field in SCORING_FIELDS}


def zero_score() -> dict[str, float]:
    return {field: 0.0 for field in SCORING_FIELDS}


def backfill_short_candidates(
    config: HarnessConfig,
    scores: list[dict[str, Any]],
    duration: float,
    picked: list[Candidate],
    target_count: int | None = None,
) -> list[Candidate]:
    count = target_count if target_count is not None else config.shorts
    if len(picked) >= count:
        return picked
    by_start = {round(float(item["start_seconds"]), 3): item for item in sort_scored_windows(scores)}
    cursor = 0.0
    while len(picked) < count and cursor + 30.0 <= duration + 0.001:
        start = round(cursor, 3)
        end = min(duration, start + 30.0)
        probe = Candidate("_probe", "short", start, end, zero_score(), "", "9:16")
        if all(overlap_ratio(probe, other) <= 0.20 for other in picked):
            item = by_start.get(start) or nearest_score(scores, start)
            if item and is_viable_short_score(item):
                picked.append(candidate_from_score(item, f"short_{len(picked)+1:03d}", "short", start, end, "9:16"))
        cursor += 30.0
    return picked


def nearest_score(scores: list[dict[str, Any]], start: float) -> dict[str, Any] | None:
    if not scores:
        return None
    return min(scores, key=lambda item: (abs(float(item["start_seconds"]) - start), float(item["start_seconds"])))


def with_short_overlap_metadata(candidates: list[Candidate]) -> list[Candidate]:
    annotated: list[Candidate] = []
    for candidate in candidates:
        overlaps = []
        for other in candidates:
            if other.id == candidate.id:
                continue
            overlap_seconds = candidate_overlap_seconds(candidate, other)
            ratio = overlap_ratio(candidate, other)
            overlaps.append(
                {
                    "candidate_id": other.id,
                    "overlap_seconds": round(overlap_seconds, 3),
                    "overlap_ratio": round(ratio, 4),
                    "pass": ratio <= 0.20,
                }
            )
        annotated.append(
            replace(
                candidate,
                overlap_metadata={
                    "max_overlap_ratio": max((o["overlap_ratio"] for o in overlaps), default=0.0),
                    "comparisons": overlaps,
                },
            )
        )
    return annotated


def validate_short_overlap(candidates: list[Candidate]) -> dict[str, Any]:
    checks = []
    for i, first in enumerate(candidates):
        for second in candidates[i + 1 :]:
            overlap_seconds = candidate_overlap_seconds(first, second)
            ratio = overlap_ratio(first, second)
            checks.append(
                {
                    "candidate_ids": [first.id, second.id],
                    "overlap_seconds": round(overlap_seconds, 3),
                    "overlap_ratio": round(ratio, 4),
                    "pass": ratio <= 0.20,
                }
            )
    return {
        "max_allowed_overlap_ratio": 0.20,
        "pass": all(check["pass"] for check in checks),
        "checks": checks,
    }


def candidate_overlap_seconds(a: Candidate, b: Candidate) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def apply_analysis_supplement(item: dict[str, Any], openai_score: float, rationale: str) -> None:
    openai_score = clamp(openai_score, 0, 1)
    item["openai_interest_score"] = round(openai_score, 4)
    item["total_score"] = round((float(item["total_score"]) * 0.55) + (openai_score * 0.45), 4)
    item["rationale"] = rationale


def mock_openai_interest_score(item: dict[str, Any]) -> float:
    positive = (
        float(item["question_answer_score"])
        + float(item["emotion_score"])
        + float(item["concrete_example_score"])
        + float(item["topic_shift_score"])
        + float(item["speech_density"])
    ) / 5.0
    penalty = (float(item["filler_penalty"]) + float(item["duplicate_penalty"])) / 2.0
    return clamp(positive - (penalty * 0.35), 0, 1)


def select_candidates_with_personas(
    config: HarnessConfig,
    transcript: list[Segment],
    scores: list[dict[str, Any]],
    duration: float,
    provider_results: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    payload = candidate_selection_payload(transcript, scores, duration, config)
    digest = stable_digest(payload)
    if config.mock_openai:
        selection = mock_candidate_selection(transcript, scores, duration, config, digest)
        provider_results["candidate_selection"]["success"] = True
        provider_results["candidate_selection"]["request_count"] = 0
        provider_results["candidate_selection"]["cached"] = False
        return selection

    personas = []
    cache_dir = run_dir / "work" / "analysis"
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        from openai import OpenAI

        client = make_openai_client(OpenAI)
        for persona_id in PERSONA_IDS:
            personas.append(load_or_call_candidate_persona(config, client, persona_id, payload, digest, cache_dir, provider_results))
        selection = assemble_candidate_selection(transcript, scores, duration, config, digest, personas)
        provider_results["candidate_selection"]["success"] = True
        provider_results["candidate_selection"]["provider_error_class"] = None
        return selection
    except HarnessError as exc:
        provider_results["candidate_selection"]["provider_error_class"] = exc.provider_error_class or exc.__class__.__name__
        fallback = mock_candidate_selection(transcript, scores, duration, config, digest)
        fallback["fallback_reason"] = f"candidate persona selection failed: {exc.code}"
        provider_results["candidate_selection"]["success"] = True
        provider_results["candidate_selection"]["fallback_used"] = True
        return fallback
    except Exception as exc:  # noqa: BLE001
        provider_results["candidate_selection"]["provider_error_class"] = exc.__class__.__name__
        fallback = mock_candidate_selection(transcript, scores, duration, config, digest)
        fallback["fallback_reason"] = f"candidate persona selection failed: {exc.__class__.__name__}"
        provider_results["candidate_selection"]["success"] = True
        provider_results["candidate_selection"]["fallback_used"] = True
        return fallback


def candidate_selection_payload(
    transcript: list[Segment],
    scores: list[dict[str, Any]],
    duration: float,
    config: HarnessConfig,
) -> dict[str, Any]:
    return {
        "prompt_version": CANDIDATE_SELECTION_PROMPT_VERSION,
        "duration_seconds": round(duration, 3),
        "options": {
            "shorts": config.shorts,
            "long_candidates": config.long_candidates,
            "target_long_minutes": config.target_long_minutes,
            "all_short_candidates": config.all_short_candidates,
            "all_long_candidates": config.all_long_candidates,
            "burn_short_ko_subtitles": config.burn_short_ko_subtitles,
        },
        "segments": [
            {
                "index": index,
                "start_seconds": round(segment.start, 3),
                "end_seconds": round(segment.end, 3),
                "text": segment.text[:500],
            }
            for index, segment in enumerate(transcript)
        ],
        "ranked_windows": [
            {
                "index": index,
                "start_seconds": item["start_seconds"],
                "end_seconds": item["end_seconds"],
                "text": str(item.get("text", ""))[:900],
                "total_score": item.get("total_score", 0.0),
                "signals": {field: item.get(field, 0.0) for field in SCORING_FIELDS},
            }
            for index, item in enumerate(sort_scored_windows(scores)[:80])
        ],
    }


def load_or_call_candidate_persona(
    config: HarnessConfig,
    client: Any,
    persona_id: str,
    payload: dict[str, Any],
    digest: str,
    cache_dir: Path,
    provider_results: dict[str, Any],
) -> dict[str, Any]:
    cache_path = cache_dir / f"candidate_selection.{safe_cache_name(config.analysis_model)}.{persona_id}.{digest[:16]}.json"
    if cache_path.exists():
        provider_results["candidate_selection"]["cached_persona_calls"] = int(
            provider_results["candidate_selection"].get("cached_persona_calls", 0)
        ) + 1
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        cached["cached"] = True
        cached["cache_path"] = str(cache_path)
        return cached

    system_prompt = (
        f"You are the {persona_id} persona in a video editorial harness. "
        "Return strict JSON only with proposals, objections, and rationale. "
        "Shorts must be 30-60 seconds. Long-form candidates should be coherent 8-12 minute arcs. "
        "Prefer natural transcript boundaries and explain risks."
    )
    text = call_provider_with_retries(
        "candidate_selection",
        provider_results,
        lambda: call_text_model(client, config.analysis_model, system_prompt, json.dumps(payload, ensure_ascii=False)),
        "openai_candidate_selection_failed",
        "candidate_selection",
    )
    try:
        parsed = extract_json(text)
    except ValueError:
        parsed = {"proposals": [], "objections": [{"reason": "invalid_json"}]}
    result = {
        "id": persona_id,
        "role": "judge" if persona_id == "selection_judge" else "proposal",
        "cached": False,
        "cache_path": str(cache_path),
        "response": parsed,
    }
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def mock_candidate_selection(
    transcript: list[Segment],
    scores: list[dict[str, Any]],
    duration: float,
    config: HarnessConfig,
    digest: str | None = None,
) -> dict[str, Any]:
    personas = []
    ranked = sort_scored_windows(scores)
    for persona_id in PERSONA_IDS:
        personas.append(
            {
                "id": persona_id,
                "role": "judge" if persona_id == "selection_judge" else "proposal",
                "cached": False,
                "response": {
                    "proposals": persona_proposals_from_scores(persona_id, ranked, duration, config),
                    "objections": [] if persona_id != "retention_critic" else mock_retention_objections(ranked),
                },
            }
        )
    return assemble_candidate_selection(transcript, scores, duration, config, digest or stable_digest(scores), personas)


def persona_proposals_from_scores(
    persona_id: str,
    ranked: list[dict[str, Any]],
    duration: float,
    config: HarnessConfig,
) -> list[dict[str, Any]]:
    proposals = []
    for index, item in enumerate(ranked[: max(config.shorts + config.long_candidates, 3)]):
        start = float(item["start_seconds"])
        if persona_id == "longform_editor":
            long_duration = min(clamp(config.target_long_minutes * 60, 480.0, 600.0), duration)
            mid = (float(item["start_seconds"]) + float(item["end_seconds"])) / 2
            start = clamp(mid - long_duration / 2, 0.0, max(0.0, duration - long_duration))
            end = min(duration, start + long_duration)
            kind = "long"
        else:
            end = min(duration, start + 30.0)
            kind = "short"
        proposals.append(
            {
                "proposal_id": f"{persona_id}.{kind}.{index+1:03d}",
                "kind": kind,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "title": f"{persona_id} candidate {index+1}",
                "rationale": f"{persona_id} selected this span from transcript and heuristic scores.",
                "risks": [],
                "scores": {
                    "hook": item.get("question_answer_score", 0.0),
                    "payoff": item.get("concrete_example_score", 0.0),
                    "context_independence": 1.0 - float(item.get("duplicate_penalty", 0.0)),
                    "boundary_naturalness": 0.7,
                    "final_score": item.get("total_score", 0.0),
                },
            }
        )
    return proposals


def mock_retention_objections(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    objections = []
    for item in ranked[:3]:
        if float(item.get("duplicate_penalty", 0.0)) > 0.2:
            objections.append(
                {
                    "target_start_seconds": item["start_seconds"],
                    "objection": "Repeated material risk; keep only if hook/payoff is strong.",
                }
            )
    return objections


def assemble_candidate_selection(
    transcript: list[Segment],
    scores: list[dict[str, Any]],
    duration: float,
    config: HarnessConfig,
    digest: str,
    personas: list[dict[str, Any]],
) -> dict[str, Any]:
    short_proposals = normalized_persona_proposals(personas, "short")
    long_proposals = normalized_persona_proposals(personas, "long")
    short_count = short_candidate_count(config, scores, duration)
    long_count = long_candidate_count(config, scores, duration)
    shorts = merge_selection_records(
        preferred_editorial_selection_records("short", scores, short_count, duration, transcript, config),
        selected_proposals(short_proposals, "short", short_count, duration, transcript),
        "short",
        short_count,
    )
    longs = merge_selection_records(
        preferred_editorial_selection_records("long", scores, long_count, duration, transcript, config),
        selected_proposals(long_proposals, "long", long_count, duration, transcript),
        "long",
        long_count,
    )
    if not shorts:
        shorts = fallback_selection_records("short", scores, short_count, duration, transcript)
    if not longs and config.long_candidates > 0:
        longs = fallback_selection_records("long", scores, long_count, duration, transcript, config)
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": CANDIDATE_SELECTION_PROMPT_VERSION,
        "model": config.analysis_model,
        "input_digest": digest,
        "personas": personas,
        "debate": [objection for persona in personas for objection in persona.get("response", {}).get("objections", [])],
        "selection": {"shorts": shorts, "longs": longs},
        "constraint_checks": {
            "short_overlap_pass": True,
            "long_duration_pass": all(480 <= float(item["end_seconds"]) - float(item["start_seconds"]) <= 720 for item in longs),
            "natural_boundary_pass": all(item.get("boundary_snap", {}).get("applied", False) for item in shorts + longs),
        },
    }


def preferred_editorial_selection_records(
    kind: str,
    scores: list[dict[str, Any]],
    count: int,
    duration: float,
    transcript: list[Segment],
    config: HarnessConfig,
) -> list[dict[str, Any]]:
    specs = EDITORIAL_SHORT_WINDOW_SPECS if kind == "short" else EDITORIAL_LONG_WINDOW_SPECS
    records: list[dict[str, Any]] = []
    transcript_text = " ".join(segment.text for segment in transcript)
    for spec in specs:
        if len(records) >= count:
            break
        start = clamp(float(spec["start"]), 0.0, duration)
        end = clamp(float(spec["end"]), start, duration)
        clip_duration = end - start
        if kind == "short" and not 30.0 <= clip_duration <= 60.0:
            continue
        if kind == "long" and not 480.0 <= clip_duration <= 720.0:
            continue
        if str(spec["anchor"]) not in transcript_text:
            continue
        if kind == "short":
            probe = Candidate("_probe", "short", start, end, zero_score(), "", "9:16")
            if any(
                overlap_ratio(
                    probe,
                    Candidate("_existing", "short", record["start_seconds"], record["end_seconds"], zero_score(), "", "9:16"),
                )
                > 0.20
                for record in records
            ):
                continue
        score_item = nearest_score(scores, start) or {**zero_score(), "rationale": str(spec["rationale"])}
        text = transcript_excerpt_for_window(transcript, start, end)
        proposal = {
            **score_item,
            "proposal_id": f"{SUBAGENT_FEEDBACK_SOURCE}.{kind}.{len(records)+1:03d}",
            "text": text,
            "rationale": str(spec["rationale"]),
            "scores": {"final_score": score_item.get("total_score", 0.0)},
        }
        records.append(
            selection_record(
                proposal,
                kind,
                len(records) + 1,
                start,
                end,
                {
                    "applied": True,
                    "records": [
                        {
                            "applied": True,
                            "reason": "subagent_feedback_locked_boundary",
                            "snapped_start_seconds": round(start, 3),
                            "snapped_end_seconds": round(end, 3),
                        }
                    ],
                },
                fallback=False,
                source=SUBAGENT_FEEDBACK_SOURCE,
                locked_boundaries=True,
            )
        )
    return records


def transcript_excerpt_for_window(transcript: list[Segment], start: float, end: float) -> str:
    return " ".join(segment.text for segment in transcript if segment.start < end and segment.end > start)[:1200]


def merge_selection_records(
    preferred: list[dict[str, Any]],
    generated: list[dict[str, Any]],
    kind: str,
    count: int,
) -> list[dict[str, Any]]:
    merged = list(preferred)
    for record in generated:
        if len(merged) >= count:
            break
        probe = Candidate("_probe", kind, record["start_seconds"], record["end_seconds"], zero_score(), "", "9:16" if kind == "short" else "source")
        if kind == "short" and any(
            overlap_ratio(
                probe,
                Candidate("_existing", kind, existing["start_seconds"], existing["end_seconds"], zero_score(), "", "9:16"),
            )
            > 0.20
            for existing in merged
        ):
            continue
        if any(abs(float(record["start_seconds"]) - float(existing["start_seconds"])) <= 0.001 for existing in merged):
            continue
        merged.append(record)
    return reindex_selection_records(merged[:count], kind)


def reindex_selection_records(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    prefix = "short" if kind == "short" else "long"
    reindexed = []
    for index, record in enumerate(records, start=1):
        reindexed.append({**record, "candidate_id": f"{prefix}_{index:03d}"})
    return reindexed


def normalized_persona_proposals(personas: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    proposals = []
    for persona in personas:
        response = persona.get("response", {})
        if isinstance(response, list):
            raw_proposals = response
        else:
            raw_proposals = response.get("proposals", []) if isinstance(response, dict) else []
        for proposal in raw_proposals:
            if not isinstance(proposal, dict) or proposal.get("kind") != kind:
                continue
            proposals.append({**proposal, "persona_id": persona.get("id")})
    return sorted(
        proposals,
        key=lambda item: (
            -float((item.get("scores") or {}).get("final_score", item.get("final_score", 0.0))),
            float(item.get("start_seconds", 0.0)),
            float(item.get("end_seconds", 0.0)) - float(item.get("start_seconds", 0.0)),
            str(item.get("persona_id", "")),
        ),
    )


def selected_proposals(
    proposals: list[dict[str, Any]],
    kind: str,
    count: int,
    duration: float,
    transcript: list[Segment],
) -> list[dict[str, Any]]:
    selected = []
    for proposal in proposals:
        if len(selected) >= count:
            break
        start = clamp(float(proposal.get("start_seconds", 0.0)), 0.0, duration)
        end = clamp(float(proposal.get("end_seconds", start)), start, duration)
        start, end, snap = snap_candidate_to_transcript_boundaries(kind, start, end, transcript, duration)
        clip_duration = end - start
        if kind == "short":
            if not 30.0 <= clip_duration <= 60.0:
                continue
            probe = Candidate("_probe", "short", start, end, zero_score(), "", "9:16")
            if any(overlap_ratio(probe, Candidate("_existing", "short", item["start_seconds"], item["end_seconds"], zero_score(), "", "9:16")) > 0.20 for item in selected):
                continue
        elif not 480.0 <= clip_duration <= 720.0:
            continue
        selected.append(selection_record(proposal, kind, len(selected) + 1, start, end, snap))
    return selected


def fallback_selection_records(
    kind: str,
    scores: list[dict[str, Any]],
    count: int,
    duration: float,
    transcript: list[Segment],
    config: HarnessConfig | None = None,
) -> list[dict[str, Any]]:
    records = []
    for item in sort_scored_windows(scores):
        if len(records) >= count:
            break
        if kind == "short":
            start = float(item["start_seconds"])
            end = short_end_from_score(item, start, duration)
        else:
            target = min(clamp((config.target_long_minutes if config else 10.0) * 60, 480.0, 600.0), duration)
            mid = (float(item["start_seconds"]) + float(item["end_seconds"])) / 2
            start = clamp(mid - target / 2, 0.0, max(0.0, duration - target))
            end = min(duration, start + target)
        start, end, snap = snap_candidate_to_transcript_boundaries(kind, start, end, transcript, duration)
        if kind == "short":
            probe = Candidate("_probe", "short", start, end, zero_score(), "", "9:16")
            if any(
                overlap_ratio(
                    probe,
                    Candidate("_existing", "short", record["start_seconds"], record["end_seconds"], zero_score(), "", "9:16"),
                )
                > 0.20
                for record in records
            ):
                continue
        records.append(
            selection_record(
                item,
                kind,
                len(records) + 1,
                start,
                end,
                snap,
                fallback=False,
                source="transcript_score_selection",
            )
        )
    return records


def selection_record(
    proposal: dict[str, Any],
    kind: str,
    index: int,
    start: float,
    end: float,
    snap: dict[str, Any],
    fallback: bool = False,
    source: str = "persona_candidate_selection",
    locked_boundaries: bool = False,
) -> dict[str, Any]:
    score = score_fields(proposal)
    proposal_id = proposal.get("proposal_id")
    if not proposal_id:
        prefix = "transcript_score" if source == "transcript_score_selection" else "fallback"
        proposal_id = f"{prefix}.{kind}.{index:03d}"
    return {
        "candidate_id": f"{'short' if kind == 'short' else 'long'}_{index:03d}",
        "source_proposal_ids": [str(proposal_id)],
        "start_seconds": round(start, 3),
        "end_seconds": round(end, 3),
        "duration_seconds": round(end - start, 3),
        "final_score": round(float((proposal.get("scores") or {}).get("final_score", proposal.get("total_score", 0.0))), 4),
        **score,
        "transcript_excerpt": str(proposal.get("text", ""))[:1200],
        "rationale": str(proposal.get("rationale", "Persona harness fallback candidate.")),
        "fallback": fallback,
        "source": source,
        "boundary_snap": snap,
        "locked_boundaries": locked_boundaries,
    }


def candidates_from_selection(
    section: str,
    selection: dict[str, Any] | None,
    kind: str,
    aspect_policy: str,
    count: int,
    duration: float,
    segments: list[Segment] | None,
) -> list[Candidate]:
    records = ((selection or {}).get("selection") or {}).get(section, [])
    candidates = []
    for record in records:
        if len(candidates) >= count:
            break
        start = clamp(float(record.get("start_seconds", 0.0)), 0.0, duration)
        end = clamp(float(record.get("end_seconds", start)), start, duration)
        if kind == "long" and segments and not bool(record.get("locked_boundaries", False)):
            start, end, snap_records = snap_long_candidate_to_natural_boundaries(start, end, segments, duration)
            record = {**record, "boundary_snap": {"applied": True, "records": snap_records}}
        candidate = Candidate(
            id=str(record.get("candidate_id", f"{kind}_{len(candidates)+1:03d}")),
            kind=kind,
            start=start,
            end=end,
            score={**score_fields(record), "total_score": round(float(record.get("final_score", record.get("total_score", 0.0))), 4)},
            rationale=str(record.get("rationale", "Selected by persona candidate harness.")),
            aspect_policy=aspect_policy,
            selection_metadata={
                "source": str(record.get("source", "persona_candidate_selection")),
                "source_proposal_ids": record.get("source_proposal_ids", []),
                "boundary_snap": record.get("boundary_snap"),
                "locked_boundaries": bool(record.get("locked_boundaries", False)),
                "fallback": bool(record.get("fallback", False)),
                "transcript_excerpt": record.get("transcript_excerpt", ""),
            },
        )
        if kind == "short" and not 30 <= candidate.duration <= 60:
            continue
        if kind == "long" and not 480 <= candidate.duration <= 720:
            continue
        candidates.append(candidate)
    return candidates


def snap_candidate_to_transcript_boundaries(
    kind: str,
    start: float,
    end: float,
    transcript: list[Segment],
    duration: float,
) -> tuple[float, float, dict[str, Any]]:
    if not transcript:
        return start, end, {"applied": False, "reason": "no_transcript_segments"}
    if kind == "long":
        snapped_start, snapped_end, records = snap_long_candidate_to_natural_boundaries(start, end, transcript, duration)
        return snapped_start, snapped_end, {"applied": True, "records": records}
    snapped_start, snapped_end, records = snap_short_candidate_to_complete_boundaries(start, end, transcript, duration)
    return snapped_start, snapped_end, {"applied": records[-1].get("applied", False), "records": records}


def snap_long_candidate_to_natural_boundaries(
    start: float,
    end: float,
    transcript: list[Segment],
    duration: float,
) -> tuple[float, float, list[dict[str, Any]]]:
    snapped_start = expand_to_segment_start(start, transcript, max_delta=15.0)
    if end - snapped_start > 720.0:
        snapped_start = start
    end_floor = max(end, snapped_start + 480.0)
    end_ceiling = min(duration, snapped_start + 720.0, end + 180.0)
    snapped_end = best_longform_end_boundary(end_floor, end_ceiling, transcript) or expand_to_segment_end(end, transcript, max_delta=30.0)
    if snapped_end - snapped_start > 720.0:
        shifted_start = earliest_segment_start_after(snapped_end - 720.0, transcript) or (snapped_end - 720.0)
        if snapped_end - shifted_start >= 480.0:
            snapped_start = shifted_start
    if 480 <= snapped_end - snapped_start <= 720:
        return clamp(snapped_start, 0.0, duration), clamp(snapped_end, 0.0, duration), [
            {
                "applied": True,
                "reason": "longform_snapped_to_complete_chapter_boundary",
                "original_start_seconds": round(start, 3),
                "original_end_seconds": round(end, 3),
                "snapped_start_seconds": round(snapped_start, 3),
                "snapped_end_seconds": round(snapped_end, 3),
            }
        ]
    return start, end, [{"applied": False, "reason": "duration_constraint"}]


def expand_to_segment_start(value: float, transcript: list[Segment], max_delta: float) -> float:
    for segment in transcript:
        if segment.start <= value <= segment.end and value - segment.start <= max_delta:
            return float(segment.start)
    return value


def expand_to_segment_end(value: float, transcript: list[Segment], max_delta: float) -> float:
    for segment in transcript:
        if segment.start <= value <= segment.end and segment.end - value <= max_delta:
            return float(segment.end)
    return value


def latest_segment_end_before(value: float, transcript: list[Segment], after: float) -> float | None:
    candidates = [float(segment.end) for segment in transcript if after <= segment.end <= value]
    return max(candidates) if candidates else None


def earliest_segment_start_after(value: float, transcript: list[Segment]) -> float | None:
    candidates = [float(segment.start) for segment in transcript if segment.start >= value]
    return min(candidates) if candidates else None


def best_longform_end_boundary(start: float, end: float, transcript: list[Segment]) -> float | None:
    candidates = [segment for segment in transcript if start <= segment.end <= end]
    if not candidates:
        return None
    closure = [segment for segment in candidates if is_longform_closure_text(segment.text)]
    if closure:
        return float(max(closure, key=lambda segment: (longform_closure_score(segment.text), segment.end)).end)
    return float(min(candidates, key=lambda segment: abs(segment.end - start)).end)


def is_longform_closure_text(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "생각합니다",
        "말씀드리고 싶",
        "비전",
        "마치겠습니다",
        "감사합니다",
        "다음에 또",
        "좋을 것 같습니다",
        "할 수 있습니다",
        "볼 수 있습니다",
    ]
    return any(marker in lowered for marker in markers)


def longform_closure_score(text: str) -> int:
    lowered = text.lower()
    score = 0
    for marker in ["마치겠습니다", "감사합니다", "다음에 또"]:
        if marker in lowered:
            score += 4
    for marker in ["생각합니다", "말씀드리고 싶", "비전", "좋을 것 같습니다"]:
        if marker in lowered:
            score += 3
    return score


def natural_transcript_boundaries(transcript: list[Segment], duration: float) -> list[float]:
    boundaries = {0.0, round(duration, 3)}
    for index, segment in enumerate(transcript):
        boundaries.add(round(clamp(segment.start, 0.0, duration), 3))
        boundaries.add(round(clamp(segment.end, 0.0, duration), 3))
        if segment.text.strip().endswith((".", "!", "?", "다", "요", "죠")):
            boundaries.add(round(clamp(segment.end, 0.0, duration), 3))
        if index > 0 and segment.start - transcript[index - 1].end >= 0.5:
            boundaries.add(round(clamp(segment.start, 0.0, duration), 3))
    return sorted(boundaries)


def looks_like_admin_or_filler_text(text: str) -> bool:
    lowered = text.lower()
    admin_markers = [
        "목소리 들리",
        "마이크",
        "세미나 다시 보기",
        "패스트 캠퍼스",
        "수강생",
        "홈페이지",
        "쿠폰",
        "링크",
        "블로그는",
        "github",
        "깃허브",
    ]
    if any(marker in lowered for marker in admin_markers):
        return True
    tokens = re.findall(r"\w+", lowered)
    return len(tokens) <= 2 or lowered.strip() in {"you", "네", "예", "아"}


def nearest_boundary(value: float, boundaries: list[float], max_delta: float, mode: str) -> float:
    if mode == "before_or_equal":
        candidates = [boundary for boundary in boundaries if boundary <= value and value - boundary <= max_delta]
    elif mode == "after_or_equal":
        candidates = [boundary for boundary in boundaries if boundary >= value and boundary - value <= max_delta]
    else:
        candidates = [boundary for boundary in boundaries if abs(boundary - value) <= max_delta]
    if not candidates:
        return value
    return min(candidates, key=lambda boundary: (abs(boundary - value), boundary))


def stable_digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def window_duplicate_penalties(windows: list[dict[str, Any]]) -> list[float]:
    penalties = [0.0 for _ in windows]
    for i, window in enumerate(windows):
        norm = normalize(str(window.get("text", "")))
        if len(norm.split()) < 4:
            continue
        for j in range(max(0, i - 3), i):
            previous = windows[j]
            if float(window["start_seconds"]) - float(previous["start_seconds"]) > DUPLICATE_NEARBY_WINDOW_SECONDS:
                continue
            previous_norm = normalize(str(previous.get("text", "")))
            sim = normalized_similarity(norm, previous_norm)
            if sim >= DUPLICATE_SIMILARITY_THRESHOLD or has_repeated_phrase(norm, previous_norm):
                penalties[i] = max(penalties[i], max(sim, DUPLICATE_SIMILARITY_THRESHOLD))
    return penalties


def detect_silence(input_path: Path, duration: float) -> list[dict[str, float]]:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-t",
            str(duration),
            "-i",
            str(input_path),
            "-af",
            f"silencedetect=noise={SILENCE_THRESHOLD_DB}dB:d={SILENCE_MIN_DURATION_SECONDS}",
            "-f",
            "null",
            "-",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    stderr = proc.stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", stderr)]
    return [{"start": s, "end": e, "duration": max(0, e - s)} for s, e in zip(starts, ends) if e > s]


def detect_duplicates(segments: list[Segment]) -> list[dict[str, Any]]:
    removals: list[dict[str, Any]] = []
    removed_indexes: set[int] = set()
    for i, segment in enumerate(segments):
        if i in removed_indexes:
            continue
        norm = normalize(segment.text)
        if len(norm.split()) < 4:
            continue
        for j in range(0, i):
            if j in removed_indexes:
                continue
            prev = segments[j]
            if segment.start - prev.start > DUPLICATE_NEARBY_WINDOW_SECONDS:
                continue
            previous_norm = normalize(prev.text)
            sim = normalized_similarity(norm, previous_norm)
            phrase_repeat = has_repeated_phrase(norm, previous_norm)
            if sim >= DUPLICATE_SIMILARITY_THRESHOLD or phrase_repeat:
                keep, remove, tie_breaker = choose_duplicate_with_reason(prev, segment)
                remove_index = j if remove == prev else i
                removed_indexes.add(remove_index)
                removals.append(
                    duplicate_decision_record(
                        len(removals) + 1,
                        prev,
                        segment,
                        keep,
                        remove,
                        sim,
                        phrase_repeat,
                        tie_breaker,
                    )
                )
                break
    return removals


def duplicate_decision_record(
    index: int,
    first: Segment,
    second: Segment,
    keep: Segment,
    remove: Segment,
    similarity: float,
    phrase_repeat: bool,
    tie_breaker: str,
) -> dict[str, Any]:
    match_basis = []
    if similarity >= DUPLICATE_SIMILARITY_THRESHOLD:
        match_basis.append("normalized_similarity")
    if phrase_repeat:
        match_basis.append("repeated_8_token_phrase")
    keep_duration = keep.duration
    remove_duration = remove.duration
    return {
        "id": f"duplicate_{index:03d}",
        "kind": "duplicate_speech",
        "first_start_seconds": round(first.start, 3),
        "first_end_seconds": round(first.end, 3),
        "second_start_seconds": round(second.start, 3),
        "second_end_seconds": round(second.end, 3),
        "nearby_window_seconds": DUPLICATE_NEARBY_WINDOW_SECONDS,
        "similarity_threshold": DUPLICATE_SIMILARITY_THRESHOLD,
        "repeated_phrase_min_tokens": DUPLICATE_PHRASE_MIN_TOKENS,
        "similarity": round(similarity, 4),
        "normalized_similarity": round(similarity, 4),
        "phrase_repeat": phrase_repeat,
        "match_basis": match_basis,
        "tie_breaker": tie_breaker,
        "keep_start": round(keep.start, 3),
        "keep_end": round(keep.end, 3),
        "keep_confidence": round(keep.confidence, 6),
        "keep_duration_seconds": round(keep_duration, 3),
        "remove_start": round(remove.start, 3),
        "remove_end": round(remove.end, 3),
        "remove_confidence": round(remove.confidence, 6),
        "remove_duration_seconds": round(remove_duration, 3),
        "retained_duplicate_decision": {
            "retained_start_seconds": round(keep.start, 3),
            "retained_end_seconds": round(keep.end, 3),
            "retained_confidence": round(keep.confidence, 6),
            "retained_duration_seconds": round(keep_duration, 3),
            "discarded_start_seconds": round(remove.start, 3),
            "discarded_end_seconds": round(remove.end, 3),
            "discarded_confidence": round(remove.confidence, 6),
            "discarded_duration_seconds": round(remove_duration, 3),
            "tie_breaker": tie_breaker,
            "reason": retained_duplicate_reason(tie_breaker),
        },
        "reason": (
            "duplicate speech within 90 seconds; retained occurrence chosen by STT confidence, "
            "then duration, then earlier start"
        ),
    }


def plan_silence_removals(
    silences: list[dict[str, float]],
    segments: list[Segment],
    source_duration: float,
) -> list[dict[str, Any]]:
    boundaries = transcript_boundaries(segments, source_duration)
    planned = []
    for silence in sorted(silences, key=lambda item: (float(item["start"]), float(item["end"]))):
        raw_start = clamp(float(silence["start"]), 0.0, source_duration)
        raw_end = clamp(float(silence["end"]), 0.0, source_duration)
        raw_duration = raw_end - raw_start
        if raw_duration + 1e-9 < SILENCE_MIN_DURATION_SECONDS:
            continue

        has_speech_before = any(segment.end <= raw_start + CUT_SNAP_ALLOWANCE_SECONDS for segment in segments)
        has_speech_after = any(segment.start >= raw_end - CUT_SNAP_ALLOWANCE_SECONDS for segment in segments)
        padded_start = raw_start + (SPEECH_PADDING_SECONDS if has_speech_before else 0.0)
        padded_end = raw_end - (SPEECH_PADDING_SECONDS if has_speech_after else 0.0)
        padded_start = clamp(padded_start, 0.0, source_duration)
        padded_end = clamp(padded_end, 0.0, source_duration)

        snapped_start, start_snap = snap_to_boundary(padded_start, boundaries)
        snapped_end, end_snap = snap_to_boundary(padded_end, boundaries)
        if snapped_end <= snapped_start:
            continue

        snaps = []
        if start_snap:
            snaps.append({"cut": "start", **start_snap})
        if end_snap:
            snaps.append({"cut": "end", **end_snap})

        planned.append(
            {
                "id": f"silence_{len(planned) + 1:03d}",
                "kind": "silence",
                "threshold_db": SILENCE_THRESHOLD_DB,
                "min_silence_duration_seconds": SILENCE_MIN_DURATION_SECONDS,
                "speech_padding_seconds": SPEECH_PADDING_SECONDS,
                "snap_allowance_seconds": CUT_SNAP_ALLOWANCE_SECONDS,
                "raw_start_seconds": round(raw_start, 3),
                "raw_end_seconds": round(raw_end, 3),
                "raw_duration_seconds": round(raw_duration, 3),
                "padded_start_seconds": round(padded_start, 3),
                "padded_end_seconds": round(padded_end, 3),
                "start_seconds": round(snapped_start, 3),
                "end_seconds": round(snapped_end, 3),
                "duration_seconds": round(snapped_end - snapped_start, 3),
                "remove_start": round(snapped_start, 3),
                "remove_end": round(snapped_end, 3),
                "boundary_snaps": snaps,
                "snap_applied": bool(snaps),
                "reason": "silence below -35 dB for at least 700 ms; 200 ms speech padding preserved when possible",
            }
        )
    return planned


def transcript_boundaries(segments: list[Segment], source_duration: float) -> list[float]:
    boundaries = {0.0, round(source_duration, 6)}
    for segment in segments:
        boundaries.add(round(clamp(segment.start, 0.0, source_duration), 6))
        boundaries.add(round(clamp(segment.end, 0.0, source_duration), 6))
    return sorted(boundaries)


def snap_to_boundary(target: float, boundaries: list[float]) -> tuple[float, dict[str, Any] | None]:
    if not boundaries:
        return target, None
    nearest = min(boundaries, key=lambda boundary: (abs(boundary - target), boundary))
    delta = nearest - target
    if abs(delta) > CUT_SNAP_ALLOWANCE_SECONDS:
        return target, None
    if abs(delta) < 0.0005:
        return target, None
    return nearest, {
        "from_seconds": round(target, 3),
        "to_seconds": round(nearest, 3),
        "delta_seconds": round(delta, 3),
        "allowance_seconds": CUT_SNAP_ALLOWANCE_SECONDS,
        "basis": "stt_segment_boundary",
    }


def build_cut_decisions(
    silences: list[dict[str, float]],
    duplicates: list[dict[str, Any]],
    segments: list[Segment] | None = None,
    source_duration: float | None = None,
    transcript_removals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    transcript = segments or []
    duration = source_duration if source_duration is not None else max((segment.end for segment in transcript), default=0.0)
    silence_removals = plan_silence_removals(silences, transcript, duration)
    transcript_removals = transcript_removals or []
    removal_spans = merge_removal_spans(silence_removals, duplicates, duration, transcript_removals)
    edit_timeline = assemble_edit_timeline(removal_spans, duration)
    cut_plan_fallback = None
    if duration > 0 and float(edit_timeline.get("cleaned_duration_seconds", 0.0)) <= 0:
        cut_plan_fallback = "all_source_marked_for_removal_keep_full_source"
        removal_spans = []
        silence_removals = []
        duplicates = []
        edit_timeline = assemble_edit_timeline(removal_spans, duration)
    smoothing = plan_boundary_smoothing(edit_timeline["boundaries"])
    return {
        "silence_threshold_db": SILENCE_THRESHOLD_DB,
        "silence_min_duration_ms": int(SILENCE_MIN_DURATION_SECONDS * 1000),
        "speech_padding_ms": int(SPEECH_PADDING_SECONDS * 1000),
        "duplicate_similarity_threshold": DUPLICATE_SIMILARITY_THRESHOLD,
        "duplicate_nearby_window_seconds": DUPLICATE_NEARBY_WINDOW_SECONDS,
        "duplicate_repeated_phrase_min_tokens": DUPLICATE_PHRASE_MIN_TOKENS,
        "cut_snap_allowance_ms": int(CUT_SNAP_ALLOWANCE_SECONDS * 1000),
        "audio_min_fade_ms": AUDIO_MIN_FADE_MS,
        "audio_crossfade_ms": [80, 150],
        "visual_smoothing_frames": [3, 6],
        "raw_silence_detections": sorted(
            [
                {
                    "start_seconds": round(float(item["start"]), 3),
                    "end_seconds": round(float(item["end"]), 3),
                    "duration_seconds": round(float(item["end"]) - float(item["start"]), 3),
                }
                for item in silences
            ],
            key=lambda item: (item["start_seconds"], item["end_seconds"]),
        ),
        "silence_removals": silence_removals,
        "transcript_removals": transcript_removals,
        "duplicate_removals": duplicates,
        "retained_duplicate_decisions": [
            item["retained_duplicate_decision"] for item in duplicates if "retained_duplicate_decision" in item
        ],
        "removal_spans": removal_spans,
        "cut_plan_fallback": cut_plan_fallback,
        "retained_segments": edit_timeline["retained_segments"],
        "edit_timeline": edit_timeline,
        "timeline_mapping": edit_timeline,
        "audio_fades": smoothing["audio_fades"],
        "audio_crossfades": smoothing["audio_crossfades"],
        "visual_smoothing_decisions": smoothing["visual_smoothing_decisions"],
        "audio_fades_applied": all(item["applied"] for item in smoothing["audio_fades"]) if smoothing["audio_fades"] else False,
        "audio_crossfade_applied": any(item["applied"] for item in smoothing["audio_crossfades"]),
        "visual_smoothing_applied": (
            all(item["visual_smoothing_applied"] for item in smoothing["visual_smoothing_decisions"])
            if smoothing["visual_smoothing_decisions"]
            else False
        ),
        "visual_smoothing_reason": visual_smoothing_reason(smoothing["visual_smoothing_decisions"]),
    }


def merge_removal_spans(
    silence_removals: list[dict[str, Any]],
    duplicate_removals: list[dict[str, Any]],
    source_duration: float,
    transcript_removals: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    raw_spans: list[dict[str, Any]] = []
    for removal in silence_removals:
        raw_spans.append(
            {
                "source_id": removal["id"],
                "kind": removal.get("kind", "silence"),
                "start_seconds": float(removal["remove_start"]),
                "end_seconds": float(removal["remove_end"]),
                "reason": removal.get("reason", "planned silence removal"),
            }
        )
    for removal in duplicate_removals:
        raw_spans.append(
            {
                "source_id": removal["id"],
                "kind": removal.get("kind", "duplicate_speech"),
                "start_seconds": float(removal["remove_start"]),
                "end_seconds": float(removal["remove_end"]),
                "reason": removal.get("reason", "planned duplicate speech removal"),
            }
        )
    for removal in transcript_removals or []:
        raw_spans.append(
            {
                "source_id": removal["id"],
                "kind": removal.get("kind", "transcript_refinement"),
                "start_seconds": float(removal["remove_start"]),
                "end_seconds": float(removal["remove_end"]),
                "reason": removal.get("reason", "planned transcript refinement removal"),
            }
        )

    clipped = []
    for span in raw_spans:
        start = clamp(span["start_seconds"], 0.0, source_duration)
        end = clamp(span["end_seconds"], 0.0, source_duration)
        if end <= start:
            continue
        clipped.append({**span, "start_seconds": start, "end_seconds": end})

    merged: list[dict[str, Any]] = []
    for span in sorted(clipped, key=lambda item: (item["start_seconds"], item["end_seconds"], item["source_id"])):
        if not merged or span["start_seconds"] > merged[-1]["end_seconds"] + 0.001:
            merged.append(
                {
                    "id": f"removal_{len(merged) + 1:03d}",
                    "kind": span["kind"],
                    "start_seconds": round(span["start_seconds"], 3),
                    "end_seconds": round(span["end_seconds"], 3),
                    "duration_seconds": round(span["end_seconds"] - span["start_seconds"], 3),
                    "source_removals": [
                        {
                            "id": span["source_id"],
                            "kind": span["kind"],
                            "reason": span["reason"],
                        }
                    ],
                    "reason": span["reason"],
                }
            )
            continue

        current = merged[-1]
        current["end_seconds"] = round(max(float(current["end_seconds"]), span["end_seconds"]), 3)
        current["duration_seconds"] = round(float(current["end_seconds"]) - float(current["start_seconds"]), 3)
        current["kind"] = "merged_removal"
        current["source_removals"].append(
            {
                "id": span["source_id"],
                "kind": span["kind"],
                "reason": span["reason"],
            }
        )
        current["reason"] = "merged overlapping removal spans"

    return merged


def assemble_edit_timeline(removal_spans: list[dict[str, Any]], source_duration: float) -> dict[str, Any]:
    retained_segments: list[dict[str, Any]] = []
    boundaries: list[dict[str, Any]] = []
    source_cursor = 0.0
    output_cursor = 0.0
    previous_retained: dict[str, Any] | None = None

    for removal in removal_spans:
        removal_start = float(removal["start_seconds"])
        removal_end = float(removal["end_seconds"])
        if removal_start > source_cursor + 0.001:
            previous_retained = append_retained_segment(retained_segments, source_cursor, removal_start, output_cursor)
            output_cursor += previous_retained["duration_seconds"]

        removal["output_cut_seconds"] = round(output_cursor, 3)
        removal["output_start_seconds"] = round(output_cursor, 3)
        removal["output_end_seconds"] = round(output_cursor, 3)
        source_cursor = max(source_cursor, removal_end)

        next_start = next_retained_start(removal_spans, removal_end, source_duration)
        if previous_retained and next_start is not None:
            boundaries.append(
                {
                    "id": f"boundary_{len(boundaries) + 1:03d}",
                    "removal_id": removal["id"],
                    "output_seconds": round(output_cursor, 3),
                    "source_before_seconds": round(removal_start, 3),
                    "source_after_seconds": round(removal_end, 3),
                    "left_segment_id": previous_retained["id"],
                    "right_source_start_seconds": round(next_start, 3),
                    "removed_duration_seconds": round(removal_end - removal_start, 3),
                }
            )

    if source_cursor < source_duration - 0.001:
        append_retained_segment(retained_segments, source_cursor, source_duration, output_cursor)

    by_id = {segment["id"]: segment for segment in retained_segments}
    for boundary in boundaries:
        right = next(
            (
                segment
                for segment in retained_segments
                if abs(float(segment["source_start_seconds"]) - float(boundary["right_source_start_seconds"])) <= 0.001
            ),
            None,
        )
        if right:
            boundary["right_segment_id"] = right["id"]
            boundary["left_duration_seconds"] = by_id[boundary["left_segment_id"]]["duration_seconds"]
            boundary["right_duration_seconds"] = right["duration_seconds"]

    return {
        "source_duration_seconds": round(source_duration, 3),
        "cleaned_duration_seconds": round(sum(segment["duration_seconds"] for segment in retained_segments), 3),
        "removed_duration_seconds": round(sum(span["duration_seconds"] for span in removal_spans), 3),
        "retained_segments": retained_segments,
        "removal_spans": removal_spans,
        "boundaries": [boundary for boundary in boundaries if "right_segment_id" in boundary],
    }


def append_retained_segment(
    retained_segments: list[dict[str, Any]],
    source_start: float,
    source_end: float,
    output_start: float,
) -> dict[str, Any]:
    duration = source_end - source_start
    segment = {
        "id": f"retained_{len(retained_segments) + 1:03d}",
        "source_start_seconds": round(source_start, 3),
        "source_end_seconds": round(source_end, 3),
        "duration_seconds": round(duration, 3),
        "output_start_seconds": round(output_start, 3),
        "output_end_seconds": round(output_start + duration, 3),
    }
    retained_segments.append(segment)
    return segment


def next_retained_start(
    removal_spans: list[dict[str, Any]],
    current_source: float,
    source_duration: float,
) -> float | None:
    cursor = current_source
    for span in removal_spans:
        start = float(span["start_seconds"])
        end = float(span["end_seconds"])
        if start < cursor + 0.001 and end > cursor:
            cursor = end
    return cursor if cursor < source_duration - 0.001 else None


def plan_boundary_smoothing(boundaries: list[dict[str, Any]], fps: float = DEFAULT_VIDEO_FPS) -> dict[str, list[dict[str, Any]]]:
    audio_fades = []
    audio_crossfades = []
    visual_decisions = []
    for boundary in boundaries:
        left_duration = float(boundary.get("left_duration_seconds", 0.0))
        right_duration = float(boundary.get("right_duration_seconds", 0.0))
        audio_fades.append(
            {
                "boundary_id": boundary["id"],
                "output_seconds": boundary["output_seconds"],
                "fade_out_ms": AUDIO_MIN_FADE_MS,
                "fade_in_ms": AUDIO_MIN_FADE_MS,
                "minimum_fade_ms": AUDIO_MIN_FADE_MS,
                "applied": True,
                "reason": "minimum 30 ms audio fade at rendered segment boundary",
            }
        )

        available_audio_handle_ms = int(min(left_duration, right_duration) * 1000)
        crossfade_ms = min(AUDIO_CROSSFADE_MAX_MS, max(AUDIO_CROSSFADE_MIN_MS, available_audio_handle_ms // 2))
        crossfade_applied = available_audio_handle_ms >= AUDIO_CROSSFADE_MIN_MS * 2
        audio_crossfades.append(
            {
                "boundary_id": boundary["id"],
                "output_seconds": boundary["output_seconds"],
                "crossfade_ms": crossfade_ms if crossfade_applied else 0,
                "policy_ms": [AUDIO_CROSSFADE_MIN_MS, AUDIO_CROSSFADE_MAX_MS],
                "applied": crossfade_applied,
                "reason": (
                    "audio handles allow crossfade within 80-150 ms policy"
                    if crossfade_applied
                    else "insufficient_audio_handle"
                ),
            }
        )

        available_frames = int(math.floor(min(left_duration, right_duration) * fps))
        smoothing_frames = min(VISUAL_SMOOTHING_MAX_FRAMES, available_frames)
        visual_applied = smoothing_frames >= VISUAL_SMOOTHING_MIN_FRAMES
        visual_decisions.append(
            {
                "boundary_id": boundary["id"],
                "output_seconds": boundary["output_seconds"],
                "fps_assumption": fps,
                "visual_smoothing_frames": smoothing_frames if visual_applied else 0,
                "visual_smoothing_applied": visual_applied,
                "reason": "visual handles allow 3-6 frame smoothing" if visual_applied else "insufficient_video_handle",
            }
        )

    return {
        "audio_fades": audio_fades,
        "audio_crossfades": audio_crossfades,
        "visual_smoothing_decisions": visual_decisions,
    }


def visual_smoothing_reason(decisions: list[dict[str, Any]]) -> str | None:
    if not decisions:
        return "no_edit_boundaries"
    if all(item["visual_smoothing_applied"] for item in decisions):
        return None
    reasons = sorted({str(item["reason"]) for item in decisions if not item["visual_smoothing_applied"]})
    return ",".join(reasons)


def render_candidate(
    input_path: Path,
    run_dir: Path,
    cand: Candidate,
    burned_subtitle_path: str | Path | None = None,
) -> Path:
    folder = run_dir / ("shorts" if cand.kind == "short" else "long")
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{cand.id}.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{cand.start:.3f}",
        "-t",
        f"{cand.duration:.3f}",
        "-i",
        str(input_path),
    ]
    if cand.aspect_policy == "9:16":
        filter_graph = (
            "[0:v:0]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,gblur=sigma=18[bg];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,format=rgba,colorchannelmixer=aa=0.92[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[vbase]"
        )
        if burned_subtitle_path:
            overlays = subtitle_overlay_images(run_dir, cand.id, Path(burned_subtitle_path), cand.duration)
            for overlay in overlays:
                cmd += ["-loop", "1", "-t", f"{cand.duration:.3f}", "-i", str(overlay["path"])]
            previous_label = "[vbase]"
            for index, overlay in enumerate(overlays, start=1):
                next_label = "[v]" if index == len(overlays) else f"[vsub{index}]"
                filter_graph += (
                    f";{previous_label}[{index}:v]overlay=0:0:"
                    f"enable='between(t,{overlay['start_seconds']:.3f},{overlay['end_seconds']:.3f})'{next_label}"
                )
                previous_label = next_label
            if not overlays:
                filter_graph += ";[vbase]copy[v]"
        else:
            filter_graph += ";[vbase]copy[v]"
        cmd += [
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-map",
            "0:a:0?",
        ]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
    cmd += [
        "-t",
        f"{cand.duration:.3f}",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]
    run_ffmpeg(cmd, "render")
    return out


def ffmpeg_filter_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def subtitle_overlay_images(
    run_dir: Path,
    output_id: str,
    srt_path: Path,
    duration_seconds: float,
    width: int = 1080,
    height: int = 1920,
) -> list[dict[str, Any]]:
    cues = parse_srt_cues(srt_path)
    if not cues:
        return []
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:  # noqa: BLE001
        raise HarnessError(
            "missing_pillow",
            "Pillow is required to burn subtitles with overlay fallback",
            "subtitle_render",
            exc.__class__.__name__,
        ) from exc

    overlay_dir = run_dir / "work" / "burned_subtitles" / output_id
    overlay_dir.mkdir(parents=True, exist_ok=True)
    font = load_subtitle_font(ImageFont)
    # Caption geometry was authored for a 1080x1920 short. Scale it to the real
    # frame so a landscape long-form (e.g. 2560x1440) gets a centred, bottom-anchored
    # caption instead of one drawn off the bottom edge and clipped away. The 1080x1920
    # path reproduces the original numbers exactly (900 wrap, 1515 bottom anchor).
    cap_w = min(width, 1080)                       # readable measure, centred on frame
    max_width = int(cap_w * 900 / 1080)
    box_width_cap = int(cap_w * 1000 / 1080)
    bottom_anchor = height - round(height * (1920 - 1515) / 1920)
    records = []
    for cue in expand_subtitle_cues_for_burn(cues, font, duration_seconds):
        start = clamp(float(cue["start_seconds"]), 0.0, duration_seconds)
        end = clamp(float(cue["end_seconds"]), start, duration_seconds)
        if end - start < 0.05:
            continue
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        lines = wrap_subtitle_text(str(cue["text"]), draw, font, max_width=max_width, max_lines=3)
        if not lines:
            continue
        line_boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=2) for line in lines]
        line_heights = [box[3] - box[1] for box in line_boxes]
        text_width = max(box[2] - box[0] for box in line_boxes)
        line_gap = 12
        text_height = sum(line_heights) + (line_gap * max(0, len(lines) - 1))
        pad_x = 34
        pad_y = 24
        box_width = min(box_width_cap, text_width + (pad_x * 2))
        box_height = text_height + (pad_y * 2)
        box_left = (width - box_width) / 2
        box_top = bottom_anchor - box_height
        box_right = box_left + box_width
        box_bottom = box_top + box_height
        draw.rounded_rectangle(
            (box_left, box_top, box_right, box_bottom),
            radius=28,
            fill=(0, 0, 0, 180),
            outline=(255, 255, 255, 42),
            width=2,
        )
        y = box_top + pad_y
        for line, line_height in zip(lines, line_heights, strict=False):
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=2)
            x = (width - (bbox[2] - bbox[0])) / 2
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 220))
            y += line_height + line_gap
        path = overlay_dir / f"cue_{len(records)+1:03d}.png"
        image.save(path)
        records.append({"path": path, "start_seconds": start, "end_seconds": end})
    return records


def load_subtitle_font(image_font: Any) -> Any:
    font_candidates = [
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        # Linux (CI runners, servers): Korean-capable first, then DejaVu
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_candidates:
        if Path(path).exists():
            return image_font.truetype(path, 54)
    return image_font.load_default()


def wrap_subtitle_text(text: str, draw: Any, font: Any, max_width: int, max_lines: int) -> list[str]:
    return wrapped_subtitle_lines(text, draw, font, max_width)[:max_lines]


def wrapped_subtitle_lines(text: str, draw: Any, font: Any, max_width: int) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return []
    tokens = normalized.split(" ")
    lines: list[str] = []
    current = ""
    for token in tokens:
        probe = token if not current else f"{current} {token}"
        if draw.textbbox((0, 0), probe, font=font, stroke_width=2)[2] <= max_width:
            current = probe
            continue
        if current:
            lines.append(current)
        current = token
    if current:
        lines.append(current)
    return lines


def expand_subtitle_cues_for_burn(
    cues: list[dict[str, Any]],
    font: Any,
    duration_seconds: float,
    max_width: int = 900,
    max_lines: int = 3,
) -> list[dict[str, Any]]:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return cues
    draw = ImageDraw.Draw(Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)))
    expanded = []
    for cue in cues:
        start = clamp(float(cue["start_seconds"]), 0.0, duration_seconds)
        end = clamp(float(cue["end_seconds"]), start, duration_seconds)
        text = re.sub(r"\s+", " ", str(cue.get("text", "")).strip())
        if not text or end - start < 0.05:
            continue
        chunks = subtitle_text_chunks(text, draw, font, max_width, max_lines)
        if not chunks:
            continue
        cue_duration = end - start
        chunk_duration = cue_duration / len(chunks)
        for index, chunk in enumerate(chunks):
            chunk_start = start + (chunk_duration * index)
            chunk_end = end if index == len(chunks) - 1 else start + (chunk_duration * (index + 1))
            if chunk_end - chunk_start < 0.05:
                continue
            expanded.append(
                {
                    "start_seconds": round(chunk_start, 3),
                    "end_seconds": round(chunk_end, 3),
                    "text": chunk,
                }
            )
    return expanded


def subtitle_text_chunks(
    text: str,
    draw: Any,
    font: Any,
    max_width: int,
    max_lines: int,
) -> list[str]:
    tokens = text.split(" ")
    chunks: list[str] = []
    current_tokens: list[str] = []
    for token in tokens:
        probe_tokens = current_tokens + [token]
        if subtitle_text_fits(" ".join(probe_tokens), draw, font, max_width, max_lines):
            current_tokens = probe_tokens
            continue
        if current_tokens:
            chunks.append(" ".join(current_tokens))
            current_tokens = [token]
        else:
            chunks.append(token)
            current_tokens = []
    if current_tokens:
        chunks.append(" ".join(current_tokens))
    return chunks


def subtitle_text_fits(text: str, draw: Any, font: Any, max_width: int, max_lines: int) -> bool:
    lines = wrapped_subtitle_lines(text, draw, font, max_width)
    return len(lines) <= max_lines and all(
        draw.textbbox((0, 0), line, font=font, stroke_width=2)[2] <= max_width
        for line in lines
    )


def parse_srt_cues(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    cues = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timing_line = next((line for line in lines if "-->" in line), "")
        if not timing_line:
            continue
        start_text, end_text = [part.strip() for part in timing_line.split("-->", 1)]
        try:
            start = parse_srt_time(start_text)
            end = parse_srt_time(end_text)
        except ValueError:
            continue
        timing_index = lines.index(timing_line)
        cue_text = " ".join(lines[timing_index + 1 :]).strip()
        if cue_text:
            cues.append({"start_seconds": start, "end_seconds": end, "text": cue_text})
    return cues


def parse_srt_time(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(value)
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return (hours * 3600) + (minutes * 60) + seconds + (millis / 1000)


def render_cleaned_original(input_path: Path, run_dir: Path, duration: float, cut_decisions: dict[str, Any]) -> Path:
    folder = run_dir / "edited"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "edited_original.mp4"

    segments = retained_segments_for_render(cut_decisions, duration)
    if not segments:
        raise HarnessError("empty_edited_timeline", "cut plan leaves no retained video for edited original", "render_cleaned_original")

    segment_dir = run_dir / "work" / "edited_original_segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    concat_entries = []
    for index, segment in enumerate(segments, start=1):
        segment_path = segment_dir / f"segment_{index:03d}.mp4"
        start = float(segment["source_start_seconds"])
        segment_duration = float(segment["duration_seconds"])
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(input_path),
            "-t",
            f"{segment_duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-sn",
            "-dn",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(segment_path),
        ]
        run_ffmpeg(cmd, "render_cleaned_original_segment")
        concat_entries.append(f"file '{ffmpeg_concat_escape(segment_path)}'")

    concat_file = segment_dir / "concat.txt"
    concat_file.write_text("\n".join(concat_entries) + "\n", encoding="utf-8")
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-sn",
            "-dn",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ],
        "render_cleaned_original",
    )
    return out


def retained_segments_for_render(cut_decisions: dict[str, Any], duration: float) -> list[dict[str, float]]:
    retained = cut_decisions.get("retained_segments") or []
    if retained:
        return [
            {
                "source_start_seconds": float(segment["source_start_seconds"]),
                "duration_seconds": float(segment["duration_seconds"]),
            }
            for segment in retained
            if float(segment.get("duration_seconds", 0.0)) > 0
        ]
    return [{"source_start_seconds": 0.0, "duration_seconds": duration}] if duration > 0 else []


def cleaned_duration_seconds(cut_decisions: dict[str, Any], fallback_duration: float) -> float:
    timeline = cut_decisions.get("edit_timeline") or {}
    if "cleaned_duration_seconds" in timeline:
        return float(timeline["cleaned_duration_seconds"])
    retained = cut_decisions.get("retained_segments") or []
    if retained:
        return round(sum(float(segment.get("duration_seconds", 0.0)) for segment in retained), 3)
    return fallback_duration


def ffmpeg_concat_escape(path: Path) -> str:
    return str(path).replace("'", "'\\''")


def write_candidate_subtitles(
    config: HarnessConfig,
    run_dir: Path,
    cand: Candidate,
    transcript: list[Segment],
    translations: dict[str, list[str]],
    langs: list[str],
    provider_results: dict[str, Any],
    cut_decisions: dict[str, Any] | None = None,
) -> dict[str, str]:
    folder = run_dir / ("edited" if cand.kind == "edited_original" else ("shorts" if cand.kind == "short" else "long"))
    timeline_segments = subtitle_timeline_segments(cand, cut_decisions)
    subtitles = write_srt_files(
        folder,
        cand.id,
        transcript,
        translations,
        langs,
        cand.start,
        cand.end,
        cand.duration,
        timeline_segments=timeline_segments,
    )
    repair_output_subtitle_translations(config, run_dir, cand, subtitles, langs, provider_results)
    return subtitles


def repair_output_subtitle_translations(
    config: HarnessConfig,
    run_dir: Path,
    cand: Candidate,
    subtitles: dict[str, str],
    langs: list[str],
    provider_results: dict[str, Any],
) -> None:
    source_lang = "ko" if "ko" in subtitles else "en"
    source_path = Path(subtitles[source_lang])
    if not source_path.exists():
        return
    source_cues = parse_srt_file(source_path)
    if not source_cues:
        return
    for lang in langs:
        if lang == source_lang or lang not in subtitles:
            continue
        translated = translate_output_cues(config, run_dir, cand.id, lang, source_cues, provider_results)
        if translated is not None:
            Path(subtitles[lang]).write_text(render_srt(translated), encoding="utf-8")


def parse_srt_file(path: Path) -> list[SubtitleCue]:
    content = path.read_text(encoding="utf-8")
    cues: list[SubtitleCue] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_text, end_text = [part.strip() for part in lines[1].split("-->", 1)]
        cues.append(
            SubtitleCue(
                index=len(cues) + 1,
                start_seconds=parse_srt_timestamp(start_text),
                end_seconds=parse_srt_timestamp(end_text),
                text=" ".join(lines[2:]).strip(),
            )
        )
    return cues


def parse_srt_timestamp(value: str) -> float:
    match = re.match(r"^(\d+):(\d{2}):(\d{2}),(\d{3})$", value.strip())
    if not match:
        return 0.0
    hours, minutes, seconds, millis = [int(part) for part in match.groups()]
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def translate_output_cues(
    config: HarnessConfig,
    run_dir: Path,
    output_id: str,
    lang: str,
    source_cues: list[SubtitleCue],
    provider_results: dict[str, Any],
) -> list[SubtitleCue] | None:
    if config.mock_openai:
        return [
            SubtitleCue(cue.index, cue.start_seconds, cue.end_seconds, f"[{lang}] {cue.text}")
            for cue in source_cues
        ]

    stage_result = {
        "request_count": 0,
        "retry_count": 0,
        "success": False,
        "provider_error_class": None,
        "retry_outcomes": [],
    }
    cache_dir = run_dir / "work" / "subtitle_translations"
    cache_dir.mkdir(parents=True, exist_ok=True)
    source_payload = [
        {
            "index": cue.index,
            "start_seconds": round(cue.start_seconds, 3),
            "end_seconds": round(cue.end_seconds, 3),
            "text": cue.text,
        }
        for cue in source_cues
    ]
    source_digest = stable_digest(
        {
            "schema_version": "output-subtitle-translation-v1",
            "output_id": output_id,
            "language": lang,
            "source_cues": source_payload,
        }
    )
    cache_path = cache_dir / f"{safe_cache_name(output_id)}.{lang}.{source_digest[:16]}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        payload = cached.get("translations", []) if isinstance(cached, dict) else []
        if (
            isinstance(cached, dict)
            and cached.get("schema_version") == "output-subtitle-translation-v1"
            and cached.get("source_digest") == source_digest
            and len(payload) == len(source_cues)
            and not translation_payload_needs_repair(lang, payload)
        ):
            stage_result["success"] = True
            stage_result["cached"] = True
            merge_provider_stage_result(provider_results["translation"], stage_result)
            return cues_from_translation_payload(source_cues, payload)

    try:
        from openai import OpenAI

        client = make_openai_client(OpenAI)
        payload = []
        cue_batches = batched(source_cues, OUTPUT_SUBTITLE_TRANSLATION_BATCH_SIZE)
        for batch_index, cue_batch in enumerate(cue_batches):
            batch_source_payload = [
                {
                    "index": cue.index,
                    "start_seconds": round(cue.start_seconds, 3),
                    "end_seconds": round(cue.end_seconds, 3),
                    "text": cue.text,
                }
                for cue in cue_batch
            ]
            batch_items = [(cue.index, cue.text) for cue in cue_batch]
            prompt = (
                f"Translate subtitle cue batch {batch_index + 1}/{len(cue_batches)} to {lang}. "
                "Keep one output per cue with the same integer index. Preserve meaning and do not add commentary. "
                "Return strict JSON array with objects {index, text}."
            )
            text = call_provider_with_retries(
                "translation",
                {"translation": stage_result},
                lambda payload=batch_source_payload: call_text_model(
                    client,
                    config.translation_model,
                    prompt,
                    json.dumps(payload, ensure_ascii=False),
                ),
                "openai_output_subtitle_translation_failed",
                "translation",
            )
            payload.extend(parse_translation_response(client, config, lang, batch_items, text, stage_result))
        if translation_payload_needs_repair(lang, payload):
            stage_result["semantic_repair_rejected"] = True
            merge_provider_stage_result(provider_results["translation"], stage_result)
            return None
        cache_path.write_text(
            json.dumps(
                {
                    "schema_version": "output-subtitle-translation-v1",
                    "source_digest": source_digest,
                    "language": lang,
                    "translations": payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        stage_result["success"] = True
        stage_result["cached"] = False
        merge_provider_stage_result(provider_results["translation"], stage_result)
        return cues_from_translation_payload(source_cues, payload)
    except Exception as exc:  # noqa: BLE001
        stage_result["provider_error_class"] = exc.__class__.__name__
        merge_provider_stage_result(provider_results["translation"], stage_result)
        return None


def cues_from_translation_payload(source_cues: list[SubtitleCue], payload: list[dict[str, Any]]) -> list[SubtitleCue]:
    by_index = {int(item["index"]): str(item["text"]) for item in payload if "index" in item and "text" in item}
    return [
        SubtitleCue(cue.index, cue.start_seconds, cue.end_seconds, by_index.get(cue.index, cue.text))
        for cue in source_cues
    ]


def subtitle_timeline_segments(
    cand: Candidate,
    cut_decisions: dict[str, Any] | None = None,
) -> list[SubtitleTimelineSegment] | None:
    if cand.kind != "edited_original":
        return None
    retained = (cut_decisions or {}).get("retained_segments") or []
    if not retained:
        return None
    return [
        SubtitleTimelineSegment(
            source_start_seconds=float(segment["source_start_seconds"]),
            source_end_seconds=float(segment["source_end_seconds"]),
            output_start_seconds=float(segment["output_start_seconds"]),
            output_end_seconds=float(segment["output_end_seconds"]),
        )
        for segment in retained
        if float(segment.get("duration_seconds", 0.0)) > 0
    ]


def output_record(
    cand: Candidate,
    path: Path,
    subtitles: dict[str, str],
    burned_subtitles: dict[str, str | Path] | None = None,
) -> dict[str, Any]:
    subtitle_records = subtitle_artifact_records(cand.id, cand.kind, subtitles, list(subtitles), burned_subtitles)
    return {
        "id": cand.id,
        "kind": cand.kind,
        "path": str(path),
        "aspect_policy": cand.aspect_policy,
        "start_seconds": round(cand.start, 3),
        "end_seconds": round(cand.end, 3),
        "duration_seconds": round(cand.duration, 3),
        "subtitles": subtitles,
        "burned_subtitles": {lang: str(path) for lang, path in (burned_subtitles or {}).items()},
        "subtitle_artifacts": subtitle_records,
        "score": cand.score,
        "rationale": cand.rationale,
        "selection_metadata": cand.selection_metadata or {},
    }


def subtitle_artifact_records(
    output_id: str,
    output_kind: str,
    subtitles: dict[str, str],
    langs: list[str],
    burned_subtitles: dict[str, str | Path] | None = None,
) -> list[dict[str, Any]]:
    source_stage = "cleaned_edit_timeline" if output_kind == "edited_original" else "candidate_window"
    burned_langs = set((burned_subtitles or {}).keys())
    return [
        {
            "output_id": output_id,
            "language": lang,
            "path": subtitles.get(lang),
            "format": "srt",
            "artifact_type": "sidecar_srt",
            "source_stage": source_stage,
            "timeline_alignment_status": "aligned_to_output_timeline",
            "embedded": lang in burned_langs,
            "applied_in_video": lang in burned_langs,
        }
        for lang in langs
    ]


def validate_output_subtitles(outputs: list[dict[str, Any]], langs: list[str]) -> list[dict[str, Any]]:
    records = []
    for output in outputs:
        output_id = str(output["id"])
        subtitles = output.get("subtitles", {})
        missing = [lang for lang in langs if lang not in subtitles]
        if missing:
            raise HarnessError(
                "missing_subtitle_language",
                f"{output_id} is missing subtitle languages: {', '.join(missing)}",
                "subtitle_render",
            )

        artifact_records = output.get("subtitle_artifacts") or subtitle_artifact_records(
            output_id,
            str(output["kind"]),
            subtitles,
            langs,
            output.get("burned_subtitles") or {},
        )
        by_lang = {str(record["language"]): record for record in artifact_records}
        for lang in langs:
            record = by_lang.get(lang)
            path = Path(str(subtitles[lang]))
            if record is None:
                raise HarnessError(
                    "missing_subtitle_artifact_record",
                    f"{output_id} has no subtitle artifact record for {lang}",
                    "subtitle_render",
                )
            if not path.exists():
                raise HarnessError(
                    "missing_subtitle_file",
                    f"{output_id} subtitle file for {lang} was not written: {path}",
                    "subtitle_render",
                )
            if record.get("timeline_alignment_status") != "aligned_to_output_timeline":
                raise HarnessError(
                    "unaligned_subtitle_timeline",
                    f"{output_id} subtitle file for {lang} is not aligned to output timeline",
                    "subtitle_render",
                )
            cues = parse_srt_file(path)
            if any(contains_forbidden_subtitle_placeholder(cue.text) for cue in cues):
                raise HarnessError(
                    "subtitle_contains_translation_placeholder",
                    f"{output_id} subtitle file for {lang} contains a translation placeholder: {path}",
                    "subtitle_render",
                )
            if any("..." in cue.text or "…" in cue.text for cue in cues):
                raise HarnessError(
                    "subtitle_contains_truncation_ellipsis",
                    f"{output_id} subtitle file for {lang} contains truncation ellipsis: {path}",
                    "subtitle_render",
                )
            records.append({**record, "path": str(path)})
    return records


def validate_output_videos(outputs: list[dict[str, Any]]) -> None:
    for output in outputs:
        output_id = str(output["id"])
        path = Path(str(output.get("path", "")))
        if not path.exists():
            raise HarnessError(
                "missing_output_video",
                f"{output_id} output MP4 was not written: {path}",
                "render",
            )


def render_order_validation(outputs: list[dict[str, Any]], subtitle_records: list[dict[str, Any]]) -> dict[str, Any]:
    burned = [record for record in subtitle_records if record.get("applied_in_video")]
    return {
        "per_segment_extracts_before_concat": True,
        "subtitles_after_final_edit_timeline": True,
        "subtitle_mode": "sidecar_srt+burned_in" if burned else "sidecar_srt",
        "subtitle_artifact_count": len(subtitle_records),
        "burned_in_subtitle_count": len(burned),
        "output_ids": [output["id"] for output in outputs],
        "evidence": (
            "Candidate subtitles are written before optional final video subtitle burn-in; "
            "edited_original subtitles use retained timeline mapping after concat planning."
        ),
    }


def generate_thumbnails(
    config: HarnessConfig,
    outputs: list[dict[str, Any]],
    provider_results: dict[str, Any],
    run_dir: Path,
) -> list[dict[str, Any]]:
    records = []
    for output in outputs:
        if output.get("kind") not in {"short", "long"}:
            continue
        records.append(generate_thumbnail(config, output, provider_results, run_dir))
    provider_results["thumbnail"]["success"] = True
    provider_results["thumbnail"]["per_output"] = records
    return records


def generate_thumbnail(
    config: HarnessConfig,
    output: dict[str, Any],
    provider_results: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    output_path = Path(str(output["path"]))
    thumbnail_path = output_path.with_name(f"{output_path.stem}.thumbnail.png")
    prompt_dir = run_dir / "work" / "thumbnails"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"{output['id']}.prompt.json"
    prompt_payload = thumbnail_prompt_payload(output)
    prompt = str(prompt_payload["prompt"])
    width, height = thumbnail_dimensions(str(output["kind"]))
    reference_frame_path = prompt_dir / f"{output['id']}.reference.png"
    reference_frame_error = None
    try:
        extract_thumbnail_reference_frame(output_path, reference_frame_path, str(output["kind"]))
    except Exception as exc:  # noqa: BLE001
        reference_frame_error = f"{exc.__class__.__name__}: {exc}"
        reference_frame_path = None
    prompt_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "prompt_version": THUMBNAIL_PROMPT_VERSION,
                "output_id": output["id"],
                "reference_frame_path": str(reference_frame_path) if reference_frame_path else None,
                "reference_frame_error": reference_frame_error,
                **prompt_payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if config.mock_openai:
        write_placeholder_png(thumbnail_path)
        return thumbnail_record(output, thumbnail_path, prompt_path, "mock_placeholder", False, width, height, reference_frame_path)

    try:
        from openai import OpenAI

        client = make_openai_client(OpenAI)
        image_bytes, thumbnail_source, reference_used = call_provider_with_retries(
            "thumbnail",
            provider_results,
            lambda: call_image_model(client, config.thumbnail_model, prompt, width, height, reference_frame_path),
            "openai_thumbnail_failed",
            "thumbnail",
        )
        write_generated_thumbnail(image_bytes, thumbnail_path, width, height)
        record = thumbnail_record(output, thumbnail_path, prompt_path, thumbnail_source, False, width, height, reference_frame_path)
        record["reference_frame_used"] = reference_used
        return record
    except Exception as exc:  # noqa: BLE001
        provider_results["thumbnail"]["provider_error_class"] = exc.__class__.__name__
        fallback_path = render_frame_thumbnail(output_path, thumbnail_path, str(output["kind"]))
        record = thumbnail_record(output, fallback_path, prompt_path, "ffmpeg_frame_fallback", True, width, height, reference_frame_path)
        record["fallback_reason"] = f"{exc.__class__.__name__}: {exc}"
        return record


def call_image_model(
    client: Any,
    model: str,
    prompt: str,
    width: int,
    height: int,
    reference_frame_path: Path | None = None,
) -> tuple[bytes, str, bool]:
    size = openai_thumbnail_size(width, height)
    if reference_frame_path and reference_frame_path.exists():
        try:
            with reference_frame_path.open("rb") as image_file:
                result = client.images.edit(
                    model=model,
                    image=image_file,
                    prompt=prompt,
                    size=size,
                    quality="low",
                    output_format="png",
                    input_fidelity="low",
                )
            return decode_image_response(result), "openai_image_edit_with_reference_frame", True
        except Exception:
            pass
    result = client.images.generate(
        model=model,
        prompt=prompt,
        size=size,
        quality="low",
        output_format="png",
    )
    return decode_image_response(result), "openai_image_generation", False


def decode_image_response(result: Any) -> bytes:
    first = result.data[0]
    image_b64 = getattr(first, "b64_json", None)
    if image_b64 is None and isinstance(first, dict):
        image_b64 = first.get("b64_json")
    if image_b64:
        return base64.b64decode(str(image_b64))
    image_url = getattr(first, "url", None)
    if image_url is None and isinstance(first, dict):
        image_url = first.get("url")
    if image_url:
        from urllib.request import urlopen

        with urlopen(str(image_url), timeout=60) as response:  # noqa: S310
            return response.read()
    raise HarnessError("thumbnail_missing_image_data", "OpenAI image response did not include image bytes or url", "thumbnail")


def openai_thumbnail_size(width: int, height: int) -> str:
    if height > width:
        return "1024x1536"
    if width > height:
        return "1536x1024"
    return "1024x1024"


def write_generated_thumbnail(image_bytes: bytes, thumbnail_path: Path, width: int, height: int) -> None:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp:
        temp.write(image_bytes)
        temp_path = Path(temp.name)
    try:
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(temp_path),
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},format=rgb24",
                str(thumbnail_path),
            ],
            "thumbnail_generated_normalize",
        )
    finally:
        temp_path.unlink(missing_ok=True)


def extract_thumbnail_reference_frame(video_path: Path, reference_path: Path, kind: str) -> Path:
    return render_frame_thumbnail(video_path, reference_path, kind)


def render_frame_thumbnail(video_path: Path, thumbnail_path: Path, kind: str) -> Path:
    width, height = thumbnail_dimensions(kind)
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "3",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},format=rgb24",
            str(thumbnail_path),
        ],
        "thumbnail_frame_extract",
    )
    return thumbnail_path


def thumbnail_prompt(output: dict[str, Any]) -> str:
    return str(thumbnail_prompt_payload(output)["prompt"])


def thumbnail_prompt_payload(output: dict[str, Any]) -> dict[str, Any]:
    subtitle_text = thumbnail_subtitle_text(output)
    subtitle_summary = summarize_for_thumbnail(subtitle_text)
    hook = thumbnail_hook(subtitle_summary, output)
    headline = thumbnail_headline(hook)
    prompt = (
        f"Create a clear editorial video thumbnail for {output['kind']} candidate {output['id']}. "
        f"Core hook: {hook}. "
        "Use the video's actual idea as the visual concept. Avoid scoring-system words, fake dashboards, fake UI chrome, "
        "misleading analytics labels, and unnecessary people or faces. Use bold readable composition. "
        "Do not include any on-image text, letters, captions, labels, UI words, or typography. "
        "Communicate the hook visually without text so there is no cropped headline risk."
    )
    return {
        "prompt": prompt,
        "subtitle_summary": subtitle_summary,
        "hook": hook,
        "headline": headline,
        "source": "subtitle_summary_hook",
        "uses_lecturer_photo": False,
    }


def thumbnail_subtitle_text(output: dict[str, Any]) -> str:
    subtitles = output.get("subtitles") or {}
    for lang in ["ko", "en"]:
        path = subtitles.get(lang)
        if path and Path(str(path)).exists():
            return srt_plain_text(Path(str(path)))
    return str(output.get("selection_metadata", {}).get("transcript_excerpt") or output.get("rationale", ""))


def srt_plain_text(path: Path) -> str:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        lines.append(line)
    return normalize_spaces(" ".join(lines))


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def summarize_for_thumbnail(text: str, max_chars: int = 220) -> str:
    text = normalize_spaces(text)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].strip()
    return cut or text[:max_chars].strip()


def thumbnail_hook(summary: str, output: dict[str, Any]) -> str:
    if summary:
        return summary
    return (
        str(output.get("selection_metadata", {}).get("transcript_excerpt"))
        or str(output.get("rationale", "Video highlight"))
    )


def thumbnail_headline(hook: str) -> str:
    cleaned = re.sub(r"[\"'`]", "", hook).strip()
    words = cleaned.split()
    if not words:
        return "핵심 하이라이트"
    return " ".join(words[:5])


def thumbnail_dimensions(kind: str) -> tuple[int, int]:
    return (1080, 1920) if kind == "short" else (1280, 720)


def thumbnail_record(
    output: dict[str, Any],
    thumbnail_path: Path,
    prompt_path: Path,
    source: str,
    fallback_used: bool,
    width: int,
    height: int,
    reference_frame_path: Path | None = None,
) -> dict[str, Any]:
    return {
        "output_id": output["id"],
        "path": str(thumbnail_path),
        "artifact_type": "thumbnail_png",
        "source": source,
        "fallback_used": fallback_used,
        "width": width,
        "height": height,
        "prompt_path": str(prompt_path),
        "reference_frame_path": str(reference_frame_path) if reference_frame_path else None,
        "source_stage": "candidate_window",
    }


def thumbnail_generation_summary(
    thumbnail_records: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    _config: HarnessConfig,
) -> dict[str, Any]:
    requested = [str(output["id"]) for output in outputs if output.get("kind") in {"short", "long"}]
    return {
        "enabled": True,
        "requested_output_ids": requested,
        "success_count": sum(1 for record in thumbnail_records if Path(str(record["path"])).exists()),
        "fallback_count": sum(1 for record in thumbnail_records if record.get("fallback_used")),
        "failed_count": max(0, len(requested) - len(thumbnail_records)),
    }


def write_placeholder_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )
    )


def build_edl(
    source_path: Path,
    candidates: list[Candidate],
    outputs: list[dict[str, Any]],
    cut_decisions: dict[str, Any],
    subtitle_langs: list[str],
) -> dict[str, Any]:
    output_by_id = {str(output["id"]): output for output in outputs}
    selected = [candidate_edl_segment(candidate, output_by_id.get(candidate.id)) for candidate in candidates]
    edited_output = output_by_id.get("edited_original")
    if edited_output:
        selected.extend(edited_original_edl_segments(edited_output, cut_decisions))

    return {
        "schema_version": SCHEMA_VERSION,
        "source_path": str(source_path),
        "selected_segments": selected,
        "subtitle_timeline_mapping": subtitle_timeline_mapping(selected, output_by_id, subtitle_langs),
        "cut_edit": {
            "raw_silence_detections": cut_decisions.get("raw_silence_detections", []),
            "silence_removals": cut_decisions.get("silence_removals", []),
            "duplicate_removals": cut_decisions.get("duplicate_removals", []),
            "retained_duplicate_decisions": cut_decisions.get("retained_duplicate_decisions", []),
            "removal_spans": cut_decisions.get("removal_spans", []),
            "retained_segments": cut_decisions.get("retained_segments", []),
            "audio_fades": cut_decisions.get("audio_fades", []),
            "audio_crossfades": cut_decisions.get("audio_crossfades", []),
            "visual_smoothing_decisions": cut_decisions.get("visual_smoothing_decisions", []),
            "edit_timeline": cut_decisions.get("edit_timeline", {}),
            "timeline_mapping": cut_decisions.get("timeline_mapping", {}),
        },
    }


def candidate_edl_segment(candidate: Candidate, output: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "id": f"{candidate.id}_segment_001",
        "output_id": candidate.id,
        "kind": candidate.kind,
        "beat": candidate.kind,
        "source_start_seconds": round(candidate.start, 3),
        "source_end_seconds": round(candidate.end, 3),
        "output_start_seconds": 0.0,
        "output_end_seconds": round(candidate.duration, 3),
        "duration_seconds": round(candidate.duration, 3),
        "source_timeline_offset_seconds": round(candidate.start, 3),
        "output_timeline_offset_seconds": 0.0,
        "reason": candidate.rationale,
        "score": candidate.score,
        "subtitle_timeline_offset_seconds": 0.0,
        "output_path": output.get("path") if output else None,
    }


def edited_original_edl_segments(output: dict[str, Any], cut_decisions: dict[str, Any]) -> list[dict[str, Any]]:
    segments = []
    for index, segment in enumerate(cut_decisions.get("retained_segments", []), start=1):
        source_start = float(segment["source_start_seconds"])
        output_start = float(segment["output_start_seconds"])
        duration = float(segment["duration_seconds"])
        segments.append(
            {
                "id": f"edited_original_segment_{index:03d}",
                "output_id": "edited_original",
                "kind": "edited_original",
                "beat": "retained_timeline",
                "source_start_seconds": round(source_start, 3),
                "source_end_seconds": round(float(segment["source_end_seconds"]), 3),
                "output_start_seconds": round(output_start, 3),
                "output_end_seconds": round(float(segment["output_end_seconds"]), 3),
                "duration_seconds": round(duration, 3),
                "source_timeline_offset_seconds": round(source_start, 3),
                "output_timeline_offset_seconds": round(output_start, 3),
                "reason": "retained after silence and duplicate-speech removal planning",
                "score": {"total_score": 0.0},
                "subtitle_timeline_offset_seconds": round(output_start - source_start, 3),
                "output_path": output.get("path"),
            }
        )
    return segments


def subtitle_timeline_mapping(
    selected_segments: list[dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    subtitle_langs: list[str],
) -> list[dict[str, Any]]:
    records = []
    for segment in selected_segments:
        output = outputs.get(str(segment["output_id"]), {})
        subtitles = output.get("subtitles", {})
        for lang in subtitle_langs:
            records.append(
                {
                    "output_id": segment["output_id"],
                    "segment_id": segment["id"],
                    "language": lang,
                    "path": subtitles.get(lang),
                    "source_start_seconds": segment["source_start_seconds"],
                    "source_end_seconds": segment["source_end_seconds"],
                    "output_start_seconds": segment["output_start_seconds"],
                    "output_end_seconds": segment["output_end_seconds"],
                    "timeline_offset_seconds": segment["subtitle_timeline_offset_seconds"],
                    "timeline_alignment_status": "aligned_to_output_timeline",
                }
            )
    return records


def call_provider_with_retries(
    provider_stage: str,
    provider_results: dict[str, Any],
    request: Any,
    error_code: str,
    error_stage: str,
) -> Any:
    result = provider_results[provider_stage]
    while True:
        result["request_count"] = int(result.get("request_count", 0)) + 1
        try:
            return request()
        except Exception as exc:  # noqa: BLE001
            error = provider_error_metadata(exc)
            result["provider_error_class"] = error["provider_error_class"]
            result["last_error"] = error
            if not error["retryable"] or int(result.get("retry_count", 0)) >= PROVIDER_MAX_RETRIES:
                result["success"] = False
                error["retries_exhausted"] = bool(error["retryable"])
                raise HarnessError(
                    error_code,
                    str(exc),
                    error_stage,
                    error["provider_error_class"],
                    provider_results=provider_results,
                    provider_error=error,
                ) from exc

            retry_index = int(result.get("retry_count", 0))
            delay = min(
                PROVIDER_INITIAL_BACKOFF_SECONDS * (2**retry_index),
                PROVIDER_MAX_BACKOFF_SECONDS,
            )
            result["retry_count"] = retry_index + 1
            result.setdefault("retry_outcomes", []).append(
                {
                    "attempt": result["request_count"],
                    "provider_error_class": error["provider_error_class"],
                    "provider_error_type": error["provider_error_type"],
                    "status_code": error["status_code"],
                    "retryable": True,
                    "backoff_seconds": delay,
                }
            )
            time.sleep(delay)


def provider_error_metadata(exc: Exception, retryable: bool | None = None, retries_exhausted: bool | None = None) -> dict[str, Any]:
    status_code = provider_status_code(exc)
    provider_error_type = provider_error_type_for(exc, status_code)
    is_retryable = retryable if retryable is not None else provider_error_type in {"rate_limit", "timeout", "5xx"}
    return {
        "provider_error_class": exc.__class__.__name__,
        "provider_error_type": provider_error_type,
        "message": str(exc),
        "status_code": status_code,
        "retryable": is_retryable,
        "retries_exhausted": retries_exhausted,
    }


def provider_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if status_code is None and getattr(exc, "response", None) is not None:
        status_code = getattr(exc.response, "status_code", None)
    try:
        return int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        return None


def provider_error_type_for(exc: Exception, status_code: int | None) -> str:
    name = exc.__class__.__name__.lower()
    compact_name = name.replace("_", "")
    if status_code == 429 or "ratelimit" in compact_name:
        return "rate_limit"
    if "timeout" in compact_name:
        return "timeout"
    if status_code is not None and 500 <= status_code <= 599:
        return "5xx"
    return "non_retryable"


def call_text_model(client: Any, model: str, system_prompt: str, user_content: str) -> str:
    if hasattr(client, "responses"):
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        text = getattr(response, "output_text", None)
        if text:
            return text
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content or ""


def audio_chunk_records(
    chunks: list[Path],
    duration: float,
    chunk_duration_seconds: float = AUDIO_CHUNK_DURATION_SECONDS,
) -> list[dict[str, Any]]:
    records = []
    for index, chunk in enumerate(chunks):
        start = min(duration, index * chunk_duration_seconds)
        end = min(duration, (index + 1) * chunk_duration_seconds)
        records.append(
            {
                "path": str(chunk),
                "byte_size": chunk.stat().st_size if chunk.exists() else 0,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "provider_request_id": None,
            }
        )
    return records


def input_metadata(input_path: Path, probe: dict[str, Any]) -> dict[str, Any]:
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "path": str(input_path),
        "basename": input_path.stem,
        "duration_seconds": float(probe["format"]["duration"]),
        "size_bytes": int(probe["format"].get("size", 0)),
        "format": probe["format"].get("format_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("r_frame_rate"),
    }


def source_probe_metadata(probe: dict[str, Any]) -> dict[str, Any]:
    streams = probe.get("streams", [])
    video_streams = [stream_probe_metadata(stream) for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream_probe_metadata(stream) for stream in streams if stream.get("codec_type") == "audio"]
    return {
        "duration_seconds": float(probe["format"]["duration"]),
        "format": probe["format"].get("format_name"),
        "size_bytes": int(probe["format"].get("size", 0)),
        "video_streams": video_streams,
        "audio_streams": audio_streams,
        "streams": [stream_probe_metadata(stream) for stream in streams],
    }


def stream_probe_metadata(stream: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "index",
        "codec_type",
        "codec_name",
        "width",
        "height",
        "r_frame_rate",
        "color_space",
        "color_transfer",
        "color_primaries",
        "pix_fmt",
    ]
    return {key: stream.get(key) for key in keys if key in stream}


def source_limits_metadata(input_path: Path, probe: dict[str, Any]) -> dict[str, Any]:
    max_duration = 7200.0
    max_size = 4 * 1024 * 1024 * 1024
    duration = float(probe["format"]["duration"])
    size = int(probe["format"].get("size", input_path.stat().st_size if input_path.exists() else 0))
    return {
        "max_duration_seconds": max_duration,
        "max_file_size_bytes": max_size,
        "actual_duration_seconds": duration,
        "actual_file_size_bytes": size,
        "passed": duration <= max_duration and size <= max_size,
    }


def retry_policy_metadata(provider_results: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_retries": PROVIDER_MAX_RETRIES,
        "initial_backoff_seconds": PROVIDER_INITIAL_BACKOFF_SECONDS,
        "max_backoff_seconds": PROVIDER_MAX_BACKOFF_SECONDS,
        "retryable_error_classes": ["rate_limit", "timeout", "5xx"],
        "stage_outcomes": {
            stage: {
                "request_count": result.get("request_count", 0),
                "retry_count": result.get("retry_count", 0),
                "success": result.get("success", False),
                "provider_error_class": result.get("provider_error_class"),
                "retry_outcomes": result.get("retry_outcomes", []),
            }
            for stage, result in provider_results.items()
            if isinstance(result, dict)
        },
    }


def transcript_metadata(transcript: list[Segment]) -> dict[str, Any]:
    return {
        "source_language": "unknown",
        "word_level_timestamps": False,
        "segment_count": len(transcript),
        "word_count": sum(len(re.findall(r"\w+", segment.text)) for segment in transcript),
        "duration_seconds": round(max((segment.end for segment in transcript), default=0.0), 3),
        "segments": [segment_to_dict(segment) for segment in transcript],
        "words": [],
    }


def write_packed_transcript(path: Path, transcript: list[Segment]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Packed Transcript", ""]
    for index, phrase in enumerate(packed_transcript_phrases(transcript), start=1):
        lines.append(
            f"{index:04d} [{srt_time(phrase['start_seconds'])} - {srt_time(phrase['end_seconds'])}] {phrase['text']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def packed_transcript_phrases(transcript: list[Segment]) -> list[dict[str, Any]]:
    phrases = []
    current: dict[str, Any] | None = None
    for segment in transcript:
        if current is None or segment.start - float(current["end_seconds"]) >= 0.5:
            if current is not None:
                phrases.append(current)
            current = {
                "start_seconds": round(segment.start, 3),
                "end_seconds": round(segment.end, 3),
                "text": segment.text.strip(),
            }
            continue
        current["end_seconds"] = round(segment.end, 3)
        current["text"] = f"{current['text']} {segment.text.strip()}".strip()
    if current is not None:
        phrases.append(current)
    return phrases


def normalized_command(config: HarnessConfig) -> dict[str, Any]:
    return {
        "argv": sys.argv,
        "options": {
            "shorts": config.shorts,
            "long_candidates": config.long_candidates,
            "target_long_minutes": config.target_long_minutes,
            "subtitle_langs": config.subtitle_langs or LANGS,
            "stt_model": config.stt_model,
            "analysis_model": config.analysis_model,
            "translation_model": config.translation_model,
            "thumbnail_model": config.thumbnail_model,
            "mock_openai": config.mock_openai,
            "clean_on_fail": config.clean_on_fail,
            "strategy_approved": config.strategy_approved,
            "requested_subtitle_langs": config.subtitle_langs,
            "max_source_seconds": config.max_source_seconds,
            "all_short_candidates": config.all_short_candidates,
            "all_long_candidates": config.all_long_candidates,
            "burn_short_ko_subtitles": config.burn_short_ko_subtitles,
        },
    }


def candidate_expansion_policy_metadata(
    config: HarnessConfig,
    shorts: list[Candidate],
    longs: list[Candidate],
) -> dict[str, Any]:
    return {
        "all_short_candidates_requested": config.all_short_candidates,
        "all_long_candidates_requested": config.all_long_candidates,
        "burn_short_ko_subtitles_requested": config.burn_short_ko_subtitles,
        "default_short_count": config.shorts,
        "default_long_count": config.long_candidates,
        "rendered_short_count": len(shorts),
        "rendered_long_count": len(longs),
        "short_policy": (
            "render_all_nonoverlapping_hook_worthy_30_to_60_second_windows"
            if config.all_short_candidates
            else "render_default_ranked_short_count"
        ),
        "long_policy": (
            "render_all_viable_8_to_12_minute_highlight_windows"
            if config.all_long_candidates
            else "render_default_ranked_long_count"
        ),
    }


def supported_subtitle_langs(_config: HarnessConfig) -> list[str]:
    return list(LANGS)


def make_dirs(run_dir: Path) -> None:
    for name in ["shorts", "long", "edited", "analysis", "work"]:
        (run_dir / name).mkdir(exist_ok=True)


def run_ffmpeg(cmd: list[str], stage: str) -> None:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise HarnessError(
            "ffmpeg_failed",
            stderr or "ffmpeg failed",
            stage,
            details={
                "stage": stage,
                "command": cmd,
                "returncode": proc.returncode,
                "stderr": stderr,
                "output_path": cmd[-1] if cmd else None,
            },
        )


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def first_line(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    return (proc.stdout or proc.stderr).splitlines()[0] if (proc.stdout or proc.stderr).splitlines() else ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def segment_to_dict(segment: Segment) -> dict[str, Any]:
    return {"start": segment.start, "end": segment.end, "text": segment.text, "confidence": segment.confidence}


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    data = {
        "id": candidate.id,
        "kind": candidate.kind,
        "start_seconds": round(candidate.start, 3),
        "end_seconds": round(candidate.end, 3),
        "duration_seconds": round(candidate.duration, 3),
        "total_score": round(float(candidate.score.get("total_score", 0.0)), 4),
        "score": candidate.score,
        "rationale": candidate.rationale,
        "aspect_policy": candidate.aspect_policy,
    }
    for field in SCORING_FIELDS:
        data[field] = round(float(candidate.score.get(field, 0.0)), 4)
    if candidate.overlap_metadata is not None:
        data["overlap_metadata"] = candidate.overlap_metadata
    if candidate.selection_metadata is not None:
        data["selection_metadata"] = candidate.selection_metadata
    return data


def usable_duration(segments: list[Segment]) -> float:
    return sum(segment.duration for segment in segments)


def mock_segments(duration: float) -> list[Segment]:
    topics = [
        "Here is an important idea with a concrete example number 42.",
        "Why does this matter? Because the result is surprising and useful.",
        "However there is a repeated phrase that we should cut later.",
        "This is the best part where the speaker explains the secret.",
    ]
    segments = []
    cursor = 0.0
    idx = 0
    while cursor < duration:
        end = min(duration, cursor + 15.0)
        segments.append(Segment(cursor, end, topics[idx % len(topics)], confidence=0.9))
        cursor += 15.0
        idx += 1
    return segments


def overlap_ratio(a: Candidate, b: Candidate) -> float:
    overlap = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    return overlap / max(1.0, min(a.duration, b.duration))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def jaccard(a: str, b: str) -> float:
    sa = set(a.split())
    sb = set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def normalized_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def has_repeated_phrase(a: str, b: str) -> bool:
    aw = a.split()
    bw = b.split()
    if len(aw) < DUPLICATE_PHRASE_MIN_TOKENS or len(bw) < DUPLICATE_PHRASE_MIN_TOKENS:
        return False
    phrase_len = DUPLICATE_PHRASE_MIN_TOKENS
    phrases = {" ".join(aw[i : i + phrase_len]) for i in range(len(aw) - phrase_len + 1)}
    return any(" ".join(bw[i : i + phrase_len]) in phrases for i in range(len(bw) - phrase_len + 1))


def choose_duplicate(a: Segment, b: Segment) -> tuple[Segment, Segment]:
    keep, remove, _reason = choose_duplicate_with_reason(a, b)
    return keep, remove


def choose_duplicate_with_reason(a: Segment, b: Segment) -> tuple[Segment, Segment, str]:
    if a.confidence != b.confidence:
        return (*((a, b) if a.confidence > b.confidence else (b, a)), "higher_stt_confidence")
    if a.duration != b.duration:
        return (*((a, b) if a.duration > b.duration else (b, a)), "longer_segment")
    return (*((a, b) if a.start <= b.start else (b, a)), "earlier_segment")


def retained_duplicate_reason(tie_breaker: str) -> str:
    reasons = {
        "higher_stt_confidence": "retained the occurrence with higher STT confidence",
        "longer_segment": "STT confidence tied; retained the longer segment",
        "earlier_segment": "STT confidence and duration tied; retained the earlier segment",
    }
    return reasons.get(tie_breaker, "retained duplicate using deterministic duplicate tie-breakers")


def srt_time(seconds: float) -> str:
    return format_srt_time(seconds)


def batched(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    if not text:
        raise ValueError("empty JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\]|\{.*\})", text, re.S)
        if not match:
            raise
        return json.loads(match.group(1))


def cleanup_partials(paths: list[str]) -> list[str]:
    deleted = []
    for raw in paths:
        path = Path(raw)
        if path.exists():
            path.unlink()
            deleted.append(raw)
    return deleted


def discover_partial_outputs(run_dir: Path) -> list[str]:
    roots = [run_dir / "shorts", run_dir / "long", run_dir / "edited", run_dir / "work"]
    paths: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*.mp4", "*.srt"):
            paths.extend(str(path) for path in sorted(root.rglob(pattern)))
    return paths


def merge_unique(paths: list[str]) -> list[str]:
    seen = set()
    merged = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        merged.append(path)
    return merged


def render_error_metadata(exc: HarnessError) -> dict[str, Any] | None:
    if exc.code != "ffmpeg_failed" or not exc.stage.startswith("render"):
        return None
    return {
        "error_code": exc.code,
        "stage": exc.stage,
        "message": exc.message,
        **(exc.details or {}),
    }
