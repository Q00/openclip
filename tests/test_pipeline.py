from __future__ import annotations

import builtins
import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import openclip.pipeline as pipeline
from openclip.pipeline import (
    SCORING_FIELDS,
    Candidate,
    HarnessConfig,
    HarnessError,
    Segment,
    build_edl,
    build_cut_decisions,
    candidate_to_dict,
    choose_duplicate,
    choose_long_candidates,
    choose_short_candidates,
    detect_duplicates,
    overlap_ratio,
    plan_silence_removals,
    render_cleaned_original,
    score_segments,
    srt_time,
    validate_short_overlap,
)


def test_srt_time_formats_milliseconds() -> None:
    assert srt_time(3723.456) == "01:02:03,456"


def test_overlap_ratio_uses_shorter_candidate() -> None:
    a = Candidate("a", "short", 0, 40, {"total_score": 1}, "", "9:16")
    b = Candidate("b", "short", 20, 60, {"total_score": 1}, "", "9:16")
    assert overlap_ratio(a, b) == 0.5


def test_duplicate_tie_breaker_confidence_then_duration_then_earlier() -> None:
    low = Segment(0, 8, "same words", confidence=0.1)
    high = Segment(10, 15, "same words", confidence=0.9)
    assert choose_duplicate(low, high) == (high, low)

    long = Segment(10, 20, "same words", confidence=0.5)
    short = Segment(0, 5, "same words", confidence=0.5)
    assert choose_duplicate(short, long) == (long, short)

    first = Segment(0, 5, "same words", confidence=0.5)
    second = Segment(10, 15, "same words", confidence=0.5)
    assert choose_duplicate(first, second) == (first, second)


def test_duplicate_planning_records_thresholds_and_retained_decision() -> None:
    lower_confidence = Segment(0, 8, "This exact duplicate phrase should be retained only once.", confidence=0.4)
    higher_confidence = Segment(30, 38, "This exact duplicate phrase should be retained only once!", confidence=0.9)
    outside_window = Segment(130, 138, "This exact duplicate phrase should be retained only once.", confidence=1.0)

    decisions = detect_duplicates([lower_confidence, higher_confidence, outside_window])

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["nearby_window_seconds"] == 90
    assert decision["similarity_threshold"] == 0.86
    assert decision["repeated_phrase_min_tokens"] == 8
    assert decision["normalized_similarity"] >= 0.86
    assert "normalized_similarity" in decision["match_basis"]
    assert decision["tie_breaker"] == "higher_stt_confidence"
    assert decision["keep_start"] == 30
    assert decision["remove_start"] == 0
    assert decision["retained_duplicate_decision"] == {
        "retained_start_seconds": 30,
        "retained_end_seconds": 38,
        "retained_confidence": 0.9,
        "retained_duration_seconds": 8,
        "discarded_start_seconds": 0,
        "discarded_end_seconds": 8,
        "discarded_confidence": 0.4,
        "discarded_duration_seconds": 8,
        "tie_breaker": "higher_stt_confidence",
        "reason": "retained the occurrence with higher STT confidence",
    }


def test_cut_plan_keeps_full_source_when_everything_would_be_removed() -> None:
    decisions = build_cut_decisions(
        [{"start": 0.0, "end": 10.0, "duration": 10.0}],
        [],
        [],
        10.0,
    )

    assert decisions["cut_plan_fallback"] == "all_source_marked_for_removal_keep_full_source"
    assert decisions["edit_timeline"]["cleaned_duration_seconds"] == 10.0
    assert decisions["removal_spans"] == []
    assert decisions["retained_segments"] == [
        {
            "id": "retained_001",
            "source_start_seconds": 0.0,
            "source_end_seconds": 10.0,
            "duration_seconds": 10.0,
            "output_start_seconds": 0.0,
            "output_end_seconds": 10.0,
        }
    ]


def test_duplicate_planning_detects_eight_token_phrase_repeat_and_duration_tie_breaker() -> None:
    repeated_phrase_a = Segment(
        0,
        5,
        "Alpha beta gamma delta epsilon zeta eta theta appears in a short note.",
        confidence=0.8,
    )
    repeated_phrase_b = Segment(
        40,
        52,
        "Before the turn alpha beta gamma delta epsilon zeta eta theta appears with more detail.",
        confidence=0.8,
    )

    decisions = detect_duplicates([repeated_phrase_a, repeated_phrase_b])

    assert len(decisions) == 1
    assert decisions[0]["phrase_repeat"] is True
    assert decisions[0]["match_basis"] == ["repeated_8_token_phrase"]
    assert decisions[0]["tie_breaker"] == "longer_segment"
    assert decisions[0]["keep_start"] == 40
    assert decisions[0]["remove_start"] == 0


def test_candidate_scoring_is_deterministic_and_records_all_numeric_fields() -> None:
    segments = [
        Segment(0, 12, "Why does this matter? It is amazing and important with example 42.", confidence=0.9),
        Segment(15, 27, "However the second point has a concrete example number 7.", confidence=0.8),
        Segment(30, 42, "This repeated repeated repeated phrase should lower repeated windows.", confidence=0.7),
        Segment(45, 57, "This repeated repeated repeated phrase should lower repeated windows.", confidence=0.7),
    ]
    config = HarnessConfig("input.mp4", "out", mock_openai=True)
    provider_results = {"analysis": {"success": False, "request_count": 0}}

    first = score_segments(config, segments, provider_results)
    second = score_segments(config, segments, {"analysis": {"success": False, "request_count": 0}})

    assert first == second
    assert all(field in first[0] for field in SCORING_FIELDS)
    assert all(isinstance(first[0][field], int | float) and not isinstance(first[0][field], bool) for field in SCORING_FIELDS)
    assert any(item["duplicate_penalty"] > 0 for item in first)


def test_short_candidates_use_deterministic_tie_breakers_and_overlap_validation() -> None:
    scores = []
    for start in range(0, 150, 30):
        scores.append(
            {
                "start_seconds": float(start),
                "end_seconds": float(start + 30),
                "rationale": f"window {start}",
                **{field: 0.0 for field in SCORING_FIELDS},
                "speech_density": 0.5,
                "openai_interest_score": 0.5,
                "total_score": 0.75,
            }
        )
    config = HarnessConfig("input.mp4", "out", shorts=5, mock_openai=True)

    candidates = choose_short_candidates(config, scores, 150.0)
    validation = validate_short_overlap(candidates)

    assert [candidate.start for candidate in candidates] == [0.0, 30.0, 60.0, 90.0, 120.0]
    assert [candidate.id for candidate in candidates] == [f"short_{i:03d}" for i in range(1, 6)]
    assert validation["pass"] is True
    assert all(check["overlap_ratio"] <= 0.20 for check in validation["checks"])

    manifest_candidate = candidate_to_dict(candidates[0])
    assert manifest_candidate["rationale"] == "window 0"
    assert manifest_candidate["overlap_metadata"]["max_overlap_ratio"] == 0.0
    assert all(field in manifest_candidate for field in SCORING_FIELDS)


def test_transcript_score_selection_records_keep_scores_and_excerpt() -> None:
    scores = [
        {
            "start_seconds": 30.0,
            "end_seconds": 90.0,
            "text": "This is a complete transcript-backed hook with proof and payoff.",
            "rationale": "Strong transcript-backed moment.",
            **{field: 0.0 for field in SCORING_FIELDS},
            "speech_density": 0.7,
            "question_answer_score": 1.0,
            "concrete_example_score": 0.5,
            "total_score": 0.8,
        }
    ]

    records = pipeline.fallback_selection_records(
        "short",
        scores,
        1,
        120.0,
        [Segment(30.0, 90.0, scores[0]["text"])],
    )
    candidate = pipeline.candidates_from_selection("shorts", {"selection": {"shorts": records}}, "short", "9:16", 1, 120.0, [])
    output = pipeline.output_record(candidate[0], Path("short_001.mp4"), {})

    assert records[0]["fallback"] is False
    assert records[0]["source"] == "transcript_score_selection"
    assert records[0]["source_proposal_ids"] == ["transcript_score.short.001"]
    assert records[0]["speech_density"] == 0.7
    assert "complete transcript-backed hook" in records[0]["transcript_excerpt"]
    assert candidate[0].score["speech_density"] == 0.7
    assert output["selection_metadata"]["source"] == "transcript_score_selection"


def test_short_selection_uses_full_scored_window_when_under_sixty_seconds() -> None:
    score = {
        "start_seconds": 10.0,
        "end_seconds": 62.0,
        "text": "A complete short with setup, proof, and payoff.",
        "rationale": "Full window should survive.",
        **{field: 0.0 for field in SCORING_FIELDS},
        "speech_density": 0.8,
        "question_answer_score": 1.0,
        "total_score": 0.9,
    }

    candidates = choose_short_candidates(
        HarnessConfig("input.mp4", "out", shorts=1, mock_openai=True),
        [score],
        120.0,
    )

    assert candidates[0].start == 10.0
    assert candidates[0].end == 62.0
    assert candidates[0].duration == 52.0


def test_short_boundary_snap_expands_to_complete_source_segments() -> None:
    segments = [
        Segment(9.0, 12.0, "complete opening."),
        Segment(12.0, 39.0, "middle proof."),
        Segment(39.0, 62.0, "payoff sentence."),
    ]

    start, end, records = pipeline.snap_short_candidate_to_complete_boundaries(10.0, 58.0, segments, 120.0)

    assert start == 9.0
    assert end == 62.0
    assert 30 <= end - start <= 60
    assert records[-1]["applied"] is True


def test_subagent_feedback_seed_windows_are_preferred_and_locked() -> None:
    transcript = [
        Segment(2100.0, 2111.36, "한번 패스를 시켜 볼게요."),
        Segment(2111.36, 2119.84, "이 foo.py를 수정했다고 증거에 남아 있는 거에요."),
        Segment(2158.84, 2166.88, "디터미스틱하게 환각을 주는 구조를 아예 없앴다."),
        Segment(3605.28, 3613.2, "소크래틱 리즈닝 질문."),
        Segment(3653.4, 3661.24, "프레임워크를 구축해야 해."),
    ]
    scores = [
        {
            "start_seconds": 2100.0,
            "end_seconds": 2160.0,
            "text": "weak scored window",
            "rationale": "score",
            **{field: 0.0 for field in SCORING_FIELDS},
            "speech_density": 0.8,
            "total_score": 0.9,
        }
    ]

    records = pipeline.preferred_editorial_selection_records(
        "short",
        scores,
        1,
        4000.0,
        transcript,
        HarnessConfig("input.mp4", "out", mock_openai=True),
    )

    assert records[0]["source"] == pipeline.SUBAGENT_FEEDBACK_SOURCE
    assert records[0]["start_seconds"] == 2111.36
    assert records[0]["end_seconds"] == 2166.88
    assert records[0]["locked_boundaries"] is True
    candidates = pipeline.candidates_from_selection("shorts", {"selection": {"shorts": records}}, "short", "9:16", 1, 4000.0, transcript)
    assert candidates[0].start == 2111.36
    assert candidates[0].end == 2166.88


def test_long_boundary_snap_can_extend_to_closure_within_twelve_minutes() -> None:
    segments = [
        Segment(95.0, 105.0, "topic setup."),
        Segment(650.0, 660.0, "this is still middle."),
        Segment(705.0, 712.0, "그래서 이렇게 할 수 있다고 생각합니다."),
    ]

    start, end, records = pipeline.snap_long_candidate_to_natural_boundaries(100.0, 650.0, segments, 1000.0)

    assert start == 95.0
    assert end == 712.0
    assert 480 <= end - start <= 720
    assert records[-1]["reason"] == "longform_snapped_to_complete_chapter_boundary"


def test_all_long_candidate_count_is_bounded_by_viable_scored_windows() -> None:
    config = HarnessConfig("input.mp4", "out", long_candidates=2, all_long_candidates=True, mock_openai=True)
    scores = []
    for index, start in enumerate([600.0, 1800.0, 3000.0]):
        scores.append(
            {
                "start_seconds": start,
                "end_seconds": start + 60.0,
                "text": f"Complete chapter-worthy moment {index} with enough concrete speech density and payoff for selection",
                "rationale": "viable",
                **{field: 0.0 for field in SCORING_FIELDS},
                "speech_density": 0.7,
                "question_answer_score": 1.0,
                "total_score": 0.8 - index * 0.01,
            }
        )

    candidates, fallback = choose_long_candidates(config, scores, 6545.0, [Segment(0, 6545, "complete")])

    assert fallback is None
    assert len(candidates) == 3
    selection = pipeline.assemble_candidate_selection(
        [Segment(0, 6545, "complete")],
        scores,
        6545.0,
        config,
        "digest",
        [],
    )
    assert len(selection["selection"]["longs"]) == 3


def test_all_short_candidates_do_not_backfill_low_value_placeholder() -> None:
    config = HarnessConfig("input.mp4", "out", shorts=5, all_short_candidates=True, mock_openai=True)
    transcript = [
        Segment(0.0, 2.06, "you"),
        Segment(120.0, 180.0, "A complete useful highlight with concrete proof, context, and payoff for the viewer."),
    ]
    selection = {
        "selection": {
            "shorts": [
                {
                    "candidate_id": "short_001",
                    "start_seconds": 120.0,
                    "end_seconds": 180.0,
                    "rationale": "real selected highlight",
                    "source": "persona_candidate_selection",
                    "boundary_snap": {"applied": True},
                    **{field: 0.0 for field in SCORING_FIELDS},
                    "total_score": 0.8,
                    "speech_density": 0.8,
                }
            ]
        }
    }

    candidates = choose_short_candidates(config, [], 240.0, transcript, selection)

    assert [candidate.id for candidate in candidates] == ["short_001"]
    assert all(candidate.start > 0.0 for candidate in candidates)


def test_refine_transcript_segments_removes_leading_filler_only() -> None:
    refined, metadata = pipeline.refine_transcript_segments(
        [
            Segment(0.0, 2.06, "you"),
            Segment(9.4, 16.0, "하네스 엔지니어링에 대해 이야기해보겠습니다."),
        ]
    )

    assert [segment.text for segment in refined] == ["하네스 엔지니어링에 대해 이야기해보겠습니다."]
    assert metadata["removed_count"] == 1
    assert metadata["removals"][0]["kind"] == "leading_filler_speech"


def test_build_cut_decisions_includes_transcript_refinement_removals() -> None:
    cut = pipeline.build_cut_decisions(
        [],
        [],
        [Segment(9.4, 16.0, "real speech")],
        30.0,
        [
            {
                "id": "leading_filler_001",
                "kind": "leading_filler_speech",
                "remove_start": 0.0,
                "remove_end": 2.06,
                "reason": "pre-roll filler",
            }
        ],
    )

    assert cut["transcript_removals"][0]["id"] == "leading_filler_001"
    assert cut["removal_spans"][0]["kind"] == "leading_filler_speech"


def test_translation_cache_v2_is_ignored(tmp_path) -> None:
    cache_dir = tmp_path / "translations"
    cache_dir.mkdir()
    batch = [(0, "안녕하세요")]
    digest = pipeline.batch_translation_source_digest(batch)
    cache_path = cache_dir / "gpt-4o-mini.en.batch_0000.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": "translation-cache-v2",
                "source_digest": digest,
                "language": "en",
                "translations": [{"index": 0, "text": "stale"}],
            }
        ),
        encoding="utf-8",
    )

    class Responses:
        def create(self, **_kwargs):
            return SimpleNamespace(output_text='[{"index": 0, "text": "fresh"}]')

    class OpenAI:
        def __init__(self, **_kwargs):
            self.responses = Responses()

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openai":
            return SimpleNamespace(OpenAI=OpenAI)
        return original_import(name, *args, **kwargs)

    try:
        builtins.__import__ = fake_import
        result = pipeline.translate_batch(
            HarnessConfig("input.mp4", "out", mock_openai=False),
            "en",
            0,
            batch,
            cache_dir,
        )
    finally:
        builtins.__import__ = original_import

    assert result["translations"] == {0: "fresh"}
    assert json.loads(cache_path.read_text(encoding="utf-8"))["schema_version"] == pipeline.TRANSLATION_CACHE_VERSION


def test_mock_transcript_has_enough_usable_timeline_for_default_shorts() -> None:
    segments = pipeline.mock_segments(150.0)

    assert pipeline.usable_duration(segments) == 150.0
    assert segments[0].start == 0.0
    assert segments[-1].end == 150.0


def test_render_short_candidate_uses_robust_vertical_9_16_filter(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run_ffmpeg(cmd: list[str], stage: str) -> None:
        calls.append((cmd, stage))

    monkeypatch.setattr(pipeline, "run_ffmpeg", fake_run_ffmpeg)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"")
    candidate = Candidate("short_001", "short", 30.0, 60.0, {"total_score": 1.0}, "best short", "9:16")

    output = pipeline.render_candidate(source, tmp_path / "run", candidate)

    assert output == tmp_path / "run" / "shorts" / "short_001.mp4"
    cmd, stage = calls[0]
    assert stage == "render"
    assert cmd[cmd.index("-ss") + 1] == "30.000"
    assert cmd[cmd.index("-t") + 1] == "30.000"
    assert cmd.index("-t") < cmd.index("-i")
    vf = cmd[cmd.index("-filter_complex") + 1]
    assert cmd[cmd.index("-map") - 2 : cmd.index("-map")] == ["-filter_complex", vf]
    assert cmd[cmd.index("-sn") - 2 : cmd.index("-sn")] == ["-t", "30.000"]
    assert "force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=18" in vf
    assert "format=rgba,colorchannelmixer=aa=0.92" in vf
    assert "force_original_aspect_ratio=decrease" not in vf
    assert "overlay=(W-w)/2:(H-h)/2" in vf
    assert cmd[cmd.index("-map") + 1] == "[v]"
    assert "0:a:0?" in cmd
    assert "-dn" in cmd
    assert "-shortest" in cmd
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"


def test_render_short_candidate_can_burn_korean_subtitles_after_reframe(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run_ffmpeg(cmd: list[str], stage: str) -> None:
        calls.append((cmd, stage))

    monkeypatch.setattr(pipeline, "run_ffmpeg", fake_run_ffmpeg)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"")
    subtitle = tmp_path / "short_001.ko.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕하세요\n", encoding="utf-8")
    candidate = Candidate("short_001", "short", 30.0, 60.0, {"total_score": 1.0}, "best short", "9:16")

    pipeline.render_candidate(source, tmp_path / "run", candidate, burned_subtitle_path=subtitle)

    cmd, stage = calls[0]
    assert stage == "render"
    vf = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay=(W-w)/2:(H-h)/2,format=yuv420p[vbase]" in vf
    assert "enable='between(t,0.000,1.000)'" in vf
    assert vf.rindex("enable='between") > vf.index("format=yuv420p[vbase]")
    assert cmd.count("-i") == 2


def test_subtitle_burn_splits_long_text_without_ellipsis(tmp_path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    srt = tmp_path / "short_001.ko.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:06,000\n"
        "이것은 아주 긴 한국어 자막 문장이고 쇼츠 화면에서 한 번에 다 보여주면 읽기 어렵기 때문에 "
        "여러 조각으로 나뉘어야 하지만 말줄임표로 대체되면 안 됩니다\n",
        encoding="utf-8",
    )

    font = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", 54)
    draw = ImageDraw.Draw(Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)))
    chunks = pipeline.subtitle_text_chunks(
        "이것은 아주 긴 한국어 자막 문장이고 쇼츠 화면에서 한 번에 다 보여주면 읽기 어렵기 때문에 "
        "여러 조각으로 나뉘어야 하지만 말줄임표로 대체되면 안 됩니다",
        draw,
        font,
        900,
        3,
    )
    overlays = pipeline.subtitle_overlay_images(tmp_path, "short_001", srt, 6.0)

    assert len(chunks) > 1
    assert all("..." not in chunk and "…" not in chunk for chunk in chunks)
    assert len(overlays) > 1
    assert all(path["path"].exists() for path in overlays)


def test_long_candidates_default_to_two_source_aspect_8_to_12_minute_outputs() -> None:
    scores = [
        {
            "start_seconds": float(start),
            "end_seconds": float(start + 60),
            "rationale": f"long window {start}",
            **{field: 0.0 for field in SCORING_FIELDS},
            "total_score": 1.0 - (start / 10_000),
        }
        for start in range(0, 960, 30)
    ]
    config = HarnessConfig("input.mp4", "out", mock_openai=True)

    candidates, fallback = choose_long_candidates(config, scores, 960.0)

    assert fallback is None
    assert [candidate.id for candidate in candidates] == ["long_001", "long_002"]
    assert all(candidate.kind == "long" for candidate in candidates)
    assert all(candidate.aspect_policy == "source" for candidate in candidates)
    assert all(480.0 <= candidate.duration <= 720.0 for candidate in candidates)
    assert [candidate.start for candidate in candidates] == sorted(candidate.start for candidate in candidates)


def test_long_candidates_under_8_minutes_use_cleaned_full_source_fallback() -> None:
    config = HarnessConfig("input.mp4", "out", mock_openai=True)

    candidates, fallback = choose_long_candidates(config, [], 479.0)

    assert fallback == "source_under_8_min"
    assert len(candidates) == 1
    assert candidates[0].id == "long_001"
    assert candidates[0].start == 0.0
    assert candidates[0].end == 479.0
    assert candidates[0].aspect_policy == "source"


def test_long_candidates_between_8_and_16_minutes_emit_one_best_available_candidate() -> None:
    scores = [
        {
            "start_seconds": 120.0,
            "end_seconds": 180.0,
            "rationale": "best middle long-form window",
            **{field: 0.0 for field in SCORING_FIELDS},
            "total_score": 0.9,
        }
    ]
    config = HarnessConfig("input.mp4", "out", mock_openai=True)

    candidates, fallback = choose_long_candidates(config, scores, 700.0)

    assert fallback == "only_one_nonoverlapping_long_candidate"
    assert len(candidates) == 1
    assert candidates[0].id == "long_001"
    assert 480.0 <= candidates[0].duration <= 720.0
    assert candidates[0].end <= 700.0
    assert candidates[0].aspect_policy == "source"


def test_render_long_candidate_preserves_source_aspect_without_vertical_filter(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run_ffmpeg(cmd: list[str], stage: str) -> None:
        calls.append((cmd, stage))

    monkeypatch.setattr(pipeline, "run_ffmpeg", fake_run_ffmpeg)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"")
    candidate = Candidate("long_001", "long", 0.0, 600.0, {"total_score": 1.0}, "best long", "source")

    output = pipeline.render_candidate(source, tmp_path / "run", candidate)

    assert output == tmp_path / "run" / "long" / "long_001.mp4"
    cmd, stage = calls[0]
    assert stage == "render"
    assert "-vf" not in cmd
    assert "-filter_complex" not in cmd
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    assert "0:a:0?" in cmd
    assert "-dn" in cmd
    assert "-shortest" in cmd
    assert cmd[cmd.index("-t") + 1] == "600.000"


def test_silence_removal_planning_uses_threshold_padding_snap_and_deterministic_order() -> None:
    silences = [
        {"start": 30.0, "end": 30.5, "duration": 0.5},
        {"start": 10.0, "end": 12.0, "duration": 2.0},
        {"start": 20.0, "end": 21.0, "duration": 1.0},
    ]
    segments = [
        Segment(0.0, 10.05, "first phrase", confidence=0.9),
        Segment(12.0, 19.0, "second phrase", confidence=0.9),
        Segment(22.0, 25.0, "third phrase", confidence=0.9),
    ]

    removals = plan_silence_removals(silences, segments, 40.0)

    assert [removal["id"] for removal in removals] == ["silence_001", "silence_002"]
    assert removals[0]["raw_start_seconds"] == 10.0
    assert removals[0]["raw_end_seconds"] == 12.0
    assert removals[0]["padded_start_seconds"] == 10.2
    assert removals[0]["padded_end_seconds"] == 11.8
    assert removals[0]["start_seconds"] == 10.05
    assert removals[0]["end_seconds"] == 12.0
    assert removals[0]["snap_applied"] is True
    assert removals[0]["threshold_db"] == -35
    assert removals[0]["min_silence_duration_seconds"] == 0.7
    assert removals[0]["speech_padding_seconds"] == 0.2
    assert removals[0]["snap_allowance_seconds"] == 0.25
    assert all(abs(snap["delta_seconds"]) <= 0.25 for snap in removals[0]["boundary_snaps"])

    assert removals[1]["raw_start_seconds"] == 20.0
    assert removals[1]["raw_end_seconds"] == 21.0
    assert removals[1]["start_seconds"] == 20.2
    assert removals[1]["end_seconds"] == 20.8
    assert removals[1]["snap_applied"] is False


def test_cut_decisions_emit_planned_silence_removals_and_raw_detections() -> None:
    decisions = build_cut_decisions(
        [{"start": 5.0, "end": 6.0, "duration": 1.0}],
        [],
        [Segment(0.0, 5.0, "before"), Segment(6.0, 8.0, "after")],
        8.0,
    )

    assert decisions["silence_threshold_db"] == -35
    assert decisions["silence_min_duration_ms"] == 700
    assert decisions["speech_padding_ms"] == 200
    assert decisions["cut_snap_allowance_ms"] == 250
    assert decisions["raw_silence_detections"] == [{"start_seconds": 5.0, "end_seconds": 6.0, "duration_seconds": 1.0}]
    assert decisions["silence_removals"][0]["remove_start"] == 5.0
    assert decisions["silence_removals"][0]["remove_end"] == 6.0


def test_cut_decisions_emit_retained_duplicate_decision_records() -> None:
    duplicates = detect_duplicates(
        [
            Segment(0.0, 6.0, "repeat this speech exactly for duplicate planning now", confidence=0.7),
            Segment(20.0, 26.0, "repeat this speech exactly for duplicate planning now", confidence=0.7),
        ]
    )

    decisions = build_cut_decisions([], duplicates, [], 30.0)

    assert decisions["duplicate_similarity_threshold"] == 0.86
    assert decisions["duplicate_nearby_window_seconds"] == 90
    assert decisions["duplicate_repeated_phrase_min_tokens"] == 8
    assert decisions["duplicate_removals"] == duplicates
    assert decisions["retained_duplicate_decisions"] == [duplicates[0]["retained_duplicate_decision"]]
    assert decisions["retained_duplicate_decisions"][0]["tie_breaker"] == "earlier_segment"


def test_cut_decisions_assemble_edit_timeline_offsets_and_smoothing() -> None:
    duplicate_removal = {
        "id": "duplicate_001",
        "kind": "duplicate_speech",
        "remove_start": 20.0,
        "remove_end": 25.0,
        "reason": "duplicate speech removal",
    }
    decisions = build_cut_decisions(
        [{"start": 10.0, "end": 11.0, "duration": 1.0}],
        [duplicate_removal],
        [
            Segment(0.0, 10.0, "before silence"),
            Segment(11.0, 20.0, "after silence before duplicate"),
            Segment(25.0, 40.0, "after duplicate"),
        ],
        40.0,
    )

    assert decisions["audio_min_fade_ms"] == 30
    assert decisions["removal_spans"] == [
        {
            "id": "removal_001",
            "kind": "silence",
            "start_seconds": 10.0,
            "end_seconds": 11.0,
            "duration_seconds": 1.0,
            "source_removals": [
                {
                    "id": "silence_001",
                    "kind": "silence",
                    "reason": "silence below -35 dB for at least 700 ms; 200 ms speech padding preserved when possible",
                }
            ],
            "reason": "silence below -35 dB for at least 700 ms; 200 ms speech padding preserved when possible",
            "output_cut_seconds": 10.0,
            "output_start_seconds": 10.0,
            "output_end_seconds": 10.0,
        },
        {
            "id": "removal_002",
            "kind": "duplicate_speech",
            "start_seconds": 20.0,
            "end_seconds": 25.0,
            "duration_seconds": 5.0,
            "source_removals": [{"id": "duplicate_001", "kind": "duplicate_speech", "reason": "duplicate speech removal"}],
            "reason": "duplicate speech removal",
            "output_cut_seconds": 19.0,
            "output_start_seconds": 19.0,
            "output_end_seconds": 19.0,
        },
    ]
    assert decisions["retained_segments"] == [
        {
            "id": "retained_001",
            "source_start_seconds": 0.0,
            "source_end_seconds": 10.0,
            "duration_seconds": 10.0,
            "output_start_seconds": 0.0,
            "output_end_seconds": 10.0,
        },
        {
            "id": "retained_002",
            "source_start_seconds": 11.0,
            "source_end_seconds": 20.0,
            "duration_seconds": 9.0,
            "output_start_seconds": 10.0,
            "output_end_seconds": 19.0,
        },
        {
            "id": "retained_003",
            "source_start_seconds": 25.0,
            "source_end_seconds": 40.0,
            "duration_seconds": 15.0,
            "output_start_seconds": 19.0,
            "output_end_seconds": 34.0,
        },
    ]
    assert decisions["edit_timeline"]["cleaned_duration_seconds"] == 34.0
    assert decisions["timeline_mapping"] == decisions["edit_timeline"]
    assert [fade["fade_out_ms"] for fade in decisions["audio_fades"]] == [30, 30]
    assert [fade["fade_in_ms"] for fade in decisions["audio_fades"]] == [30, 30]
    assert [crossfade["applied"] for crossfade in decisions["audio_crossfades"]] == [True, True]
    assert [visual["visual_smoothing_applied"] for visual in decisions["visual_smoothing_decisions"]] == [True, True]
    assert [visual["visual_smoothing_frames"] for visual in decisions["visual_smoothing_decisions"]] == [6, 6]
    assert decisions["visual_smoothing_reason"] is None


def test_cut_decisions_record_insufficient_video_handle_for_short_boundaries() -> None:
    decisions = build_cut_decisions(
        [],
        [
            {
                "id": "duplicate_001",
                "kind": "duplicate_speech",
                "remove_start": 0.05,
                "remove_end": 0.08,
                "reason": "duplicate speech removal",
            }
        ],
        [],
        0.11,
    )

    assert decisions["audio_fades"][0]["fade_out_ms"] == 30
    assert decisions["audio_crossfades"][0]["applied"] is False
    assert decisions["visual_smoothing_decisions"][0]["visual_smoothing_applied"] is False
    assert decisions["visual_smoothing_decisions"][0]["reason"] == "insufficient_video_handle"
    assert decisions["visual_smoothing_reason"] == "insufficient_video_handle"


def test_edl_records_cut_artifacts_and_output_timeline_offsets() -> None:
    duplicates = detect_duplicates(
        [
            Segment(0.0, 6.0, "repeat this speech exactly for duplicate planning now", confidence=0.7),
            Segment(20.0, 26.0, "repeat this speech exactly for duplicate planning now", confidence=0.7),
        ]
    )
    decisions = build_cut_decisions(
        [{"start": 10.0, "end": 11.0, "duration": 1.0}],
        duplicates,
        [
            Segment(0.0, 10.0, "before silence"),
            Segment(11.0, 20.0, "after silence before duplicate"),
            Segment(26.0, 40.0, "after duplicate"),
        ],
        40.0,
    )
    candidate = Candidate(
        "short_001",
        "short",
        11.0,
        41.0,
        {"total_score": 0.8, **{field: 0.0 for field in SCORING_FIELDS if field != "total_score"}},
        "best short",
        "9:16",
    )
    outputs = [
        {
            "id": "short_001",
            "kind": "short",
            "path": "shorts/short_001.mp4",
            "subtitles": {"en": "shorts/short_001.en.srt", "ko": "shorts/short_001.ko.srt"},
        },
        {
            "id": "edited_original",
            "kind": "edited_original",
            "path": "edited/edited_original.mp4",
            "subtitles": {"en": "edited/edited_original.en.srt", "ko": "edited/edited_original.ko.srt"},
        },
    ]

    edl = build_edl(Path("/tmp/source.mp4"), [candidate], outputs, decisions, ["en", "ko"])

    assert edl["source_path"] == "/tmp/source.mp4"
    assert edl["cut_edit"]["silence_removals"] == decisions["silence_removals"]
    assert edl["cut_edit"]["duplicate_removals"] == decisions["duplicate_removals"]
    assert edl["cut_edit"]["retained_duplicate_decisions"] == decisions["retained_duplicate_decisions"]
    assert edl["cut_edit"]["removal_spans"] == decisions["removal_spans"]
    assert edl["cut_edit"]["audio_fades"] == decisions["audio_fades"]
    assert edl["cut_edit"]["audio_crossfades"] == decisions["audio_crossfades"]
    assert edl["cut_edit"]["visual_smoothing_decisions"] == decisions["visual_smoothing_decisions"]

    short_segment = edl["selected_segments"][0]
    assert short_segment["output_id"] == "short_001"
    assert short_segment["source_timeline_offset_seconds"] == 11.0
    assert short_segment["output_timeline_offset_seconds"] == 0.0
    assert short_segment["subtitle_timeline_offset_seconds"] == 0.0

    edited_segments = [segment for segment in edl["selected_segments"] if segment["output_id"] == "edited_original"]
    assert [segment["output_start_seconds"] for segment in edited_segments] == [
        segment["output_start_seconds"] for segment in decisions["retained_segments"]
    ]
    assert any(record["path"] == "edited/edited_original.ko.srt" for record in edl["subtitle_timeline_mapping"])


def test_render_cleaned_original_uses_retained_segments_and_concat(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run_ffmpeg(cmd: list[str], stage: str) -> None:
        calls.append((cmd, stage))

    monkeypatch.setattr(pipeline, "run_ffmpeg", fake_run_ffmpeg)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"")
    run_dir = tmp_path / "run"
    decisions = {
        "retained_segments": [
            {"source_start_seconds": 0.0, "duration_seconds": 10.0},
            {"source_start_seconds": 12.0, "duration_seconds": 8.0},
            {"source_start_seconds": 30.0, "duration_seconds": 5.0},
        ]
    }

    output = render_cleaned_original(source, run_dir, 40.0, decisions)

    assert output == run_dir / "edited" / "edited_original.mp4"
    assert [stage for _cmd, stage in calls] == [
        "render_cleaned_original_segment",
        "render_cleaned_original_segment",
        "render_cleaned_original_segment",
        "render_cleaned_original",
    ]
    assert [calls[index][0][calls[index][0].index("-ss") + 1] for index in range(3)] == ["0.000", "12.000", "30.000"]
    assert [calls[index][0][calls[index][0].index("-t") + 1] for index in range(3)] == ["10.000", "8.000", "5.000"]
    assert all("-dn" in calls[index][0] for index in range(3))
    assert all("-shortest" in calls[index][0] for index in range(3))
    concat_cmd = calls[-1][0]
    assert concat_cmd[concat_cmd.index("-f") + 1] == "concat"
    assert concat_cmd[concat_cmd.index("-map") + 1] == "0:v:0"
    assert "0:a:0?" in concat_cmd
    assert "-dn" in concat_cmd
    assert concat_cmd[-1] == str(output)


def test_edited_original_subtitles_use_retained_timeline_mapping(tmp_path) -> None:
    transcript = [
        Segment(1.0, 2.0, "kept before cut"),
        Segment(10.5, 11.5, "removed by cut"),
        Segment(12.25, 13.25, "kept after cut"),
    ]
    candidate = Candidate(
        "edited_original",
        "edited_original",
        0.0,
        18.0,
        {"total_score": 0.0},
        "edited",
        "source",
    )
    cut_decisions = {
        "retained_segments": [
            {
                "source_start_seconds": 0.0,
                "source_end_seconds": 10.0,
                "duration_seconds": 10.0,
                "output_start_seconds": 0.0,
                "output_end_seconds": 10.0,
            },
            {
                "source_start_seconds": 12.0,
                "source_end_seconds": 20.0,
                "duration_seconds": 8.0,
                "output_start_seconds": 10.0,
                "output_end_seconds": 18.0,
            },
        ]
    }

    pipeline.write_candidate_subtitles(
        HarnessConfig("input.mp4", "out", mock_openai=True),
        tmp_path,
        candidate,
        transcript,
        {"en": ["kept before cut", "removed by cut", "kept after cut"]},
        ["en"],
        {"translation": {}},
        cut_decisions,
    )

    text = (tmp_path / "edited" / "edited_original.en.srt").read_text(encoding="utf-8")
    assert "kept before cut" in text
    assert "removed by cut" not in text
    assert "00:00:10,250 --> 00:00:11,250" in text
    assert "kept after cut" in text


def test_output_subtitle_translation_repair_uses_final_ko_cues(tmp_path) -> None:
    run_dir = tmp_path / "run"
    folder = run_dir / "shorts"
    folder.mkdir(parents=True)
    ko_path = folder / "short_001.ko.srt"
    en_path = folder / "short_001.en.srt"
    ko_path.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n코덱스가 하네스입니다\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\n컨트랙트 기반으로 작업합니다\n",
        encoding="utf-8",
    )
    en_path.write_text("stale", encoding="utf-8")

    class Responses:
        def create(self, **_kwargs):
            return SimpleNamespace(
                output_text='[{"index": 1, "text": "Codex is the harness"}, {"index": 2, "text": "It works from contracts"}]'
            )

    class OpenAI:
        def __init__(self, **_kwargs):
            self.responses = Responses()

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openai":
            return SimpleNamespace(OpenAI=OpenAI)
        return original_import(name, *args, **kwargs)

    try:
        builtins.__import__ = fake_import
        provider_results = {"translation": {"request_count": 0, "retry_count": 0, "retry_outcomes": []}}
        pipeline.repair_output_subtitle_translations(
            HarnessConfig("input.mp4", "out", mock_openai=False),
            run_dir,
            Candidate("short_001", "short", 0.0, 4.0, {"total_score": 0.0}, "", "9:16"),
            {"ko": str(ko_path), "en": str(en_path)},
            ["ko", "en"],
            provider_results,
        )
    finally:
        builtins.__import__ = original_import

    text = en_path.read_text(encoding="utf-8")
    assert "Codex is the harness" in text
    assert "It works from contracts" in text
    assert "00:00:02,000 --> 00:00:04,000" in text


def test_output_record_and_validation_require_all_mvp_subtitle_artifacts(tmp_path) -> None:
    candidate = Candidate(
        "short_001",
        "short",
        0.0,
        30.0,
        {"total_score": 1.0},
        "short",
        "9:16",
    )
    subtitles = {}
    for lang in pipeline.LANGS:
        path = tmp_path / f"short_001.{lang}.srt"
        path.write_text("1\n00:00:00,000 --> 00:00:01,000\ntext\n", encoding="utf-8")
        subtitles[lang] = str(path)

    output = pipeline.output_record(candidate, tmp_path / "short_001.mp4", subtitles)
    records = pipeline.validate_output_subtitles([output], pipeline.LANGS)

    assert len(records) == len(pipeline.LANGS)
    assert [record["language"] for record in records] == pipeline.LANGS
    assert all(record["output_id"] == "short_001" for record in records)
    assert all(record["format"] == "srt" for record in records)
    assert all(record["artifact_type"] == "sidecar_srt" for record in records)
    assert all(record["source_stage"] == "candidate_window" for record in records)
    assert all(record["timeline_alignment_status"] == "aligned_to_output_timeline" for record in records)
    assert output["subtitle_artifacts"] == records


def test_output_record_marks_burned_korean_short_subtitle_artifact(tmp_path) -> None:
    candidate = Candidate(
        "short_001",
        "short",
        0.0,
        30.0,
        {"total_score": 1.0},
        "short",
        "9:16",
    )
    subtitles = {}
    for lang in pipeline.LANGS:
        path = tmp_path / f"short_001.{lang}.srt"
        path.write_text("1\n00:00:00,000 --> 00:00:01,000\ntext\n", encoding="utf-8")
        subtitles[lang] = str(path)

    output = pipeline.output_record(candidate, tmp_path / "short_001.mp4", subtitles, burned_subtitles={"ko": subtitles["ko"]})
    records = pipeline.validate_output_subtitles([output], pipeline.LANGS)
    ko_record = next(record for record in records if record["language"] == "ko")
    en_record = next(record for record in records if record["language"] == "en")

    assert output["burned_subtitles"] == {"ko": subtitles["ko"]}
    assert output["selection_metadata"] == {}
    assert ko_record["artifact_type"] == "sidecar_srt"
    assert ko_record["embedded"] is True
    assert ko_record["applied_in_video"] is True
    assert en_record["applied_in_video"] is False


def test_subtitle_validation_fails_when_expected_language_file_is_missing(tmp_path) -> None:
    candidate = Candidate(
        "long_001",
        "long",
        0.0,
        600.0,
        {"total_score": 1.0},
        "long",
        "source",
    )
    subtitles = {}
    for lang in pipeline.LANGS[:-1]:
        path = tmp_path / f"long_001.{lang}.srt"
        path.write_text("", encoding="utf-8")
        subtitles[lang] = str(path)

    output = pipeline.output_record(candidate, tmp_path / "long_001.mp4", subtitles)

    with pytest.raises(HarnessError) as excinfo:
        pipeline.validate_output_subtitles([output], pipeline.LANGS)

    assert excinfo.value.stage == "subtitle_render"
    assert excinfo.value.code == "missing_subtitle_language"


def test_thumbnail_prompt_payload_uses_subtitle_summary_hook(tmp_path) -> None:
    subtitle = tmp_path / "short_001.ko.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:03,000\n계약 기반으로 코덱스를 제어하는 방법\n\n"
        "2\n00:00:03,000 --> 00:00:06,000\n증거가 없으면 거절하게 만드는 하네스\n",
        encoding="utf-8",
    )
    output = {
        "id": "short_001",
        "kind": "short",
        "subtitles": {"ko": str(subtitle)},
        "rationale": "Heuristic transcript score over density.",
    }

    payload = pipeline.thumbnail_prompt_payload(output)

    assert payload["source"] == "subtitle_summary_hook"
    assert "계약 기반" in payload["subtitle_summary"]
    assert "Heuristic" not in payload["prompt"]
    assert "Do not include any on-image text" in payload["prompt"]
    assert payload["hook"]
    assert payload["headline"]
    assert len(payload["headline"].split()) <= 5


def test_detect_source_subtitle_language_uses_korean_source_for_hangul_transcript() -> None:
    assert pipeline.detect_source_subtitle_language(["안녕하세요 하네스 엔지니어링을 설명합니다"] * 5) == "ko"
    assert pipeline.detect_source_subtitle_language(["This transcript is already English."] * 5) == "en"


def test_call_image_model_prefers_reference_frame_edit_with_official_size(tmp_path) -> None:
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")
    calls = []

    class Images:
        def edit(self, **kwargs):
            calls.append(("edit", kwargs))
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"image-bytes").decode("ascii"))])

        def generate(self, **kwargs):
            calls.append(("generate", kwargs))
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"image-bytes").decode("ascii"))])

    image_bytes, source, reference_used = pipeline.call_image_model(
        SimpleNamespace(images=Images()),
        "gpt-image-2",
        "thumbnail prompt",
        1080,
        1920,
        reference,
    )

    assert image_bytes == b"image-bytes"
    assert source == "openai_image_edit_with_reference_frame"
    assert reference_used is True
    assert calls[0][0] == "edit"
    assert calls[0][1]["model"] == "gpt-image-2"
    assert calls[0][1]["size"] == "1024x1536"
    assert "response_format" not in calls[0][1]


def test_parse_translation_response_repairs_invalid_json() -> None:
    calls = []

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text='[{"index": 7, "text": "repaired"}]')

    stage_result = {}

    parsed = pipeline.parse_translation_response(
        SimpleNamespace(responses=Responses()),
        HarnessConfig("input.mp4", "out", mock_openai=False),
        "zh-Hans",
        [(7, "source")],
        '[{"index": 7, "text": "broken"} trailing',
        stage_result,
    )

    assert parsed == [{"index": 7, "text": "repaired"}]
    assert stage_result["json_repair_attempted"] is True
    assert calls


def test_parse_translation_response_fails_when_repair_fails() -> None:
    class Responses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text="still not json")

    stage_result = {}

    with pytest.raises(ValueError):
        pipeline.parse_translation_response(
            SimpleNamespace(responses=Responses()),
            HarnessConfig("input.mp4", "out", mock_openai=False),
            "zh-Hans",
            [(7, "source")],
            "not json",
            stage_result,
        )

    assert "json_repair_error" in stage_result


def test_translation_payload_needs_repair_for_untranslated_target_language() -> None:
    assert pipeline.translation_payload_needs_repair("en", [{"index": 1, "text": "이 문장은 아직 한국어입니다"}]) is True
    assert pipeline.translation_payload_needs_repair("ko", [{"index": 1, "text": "이 문장은 한국어 원문입니다"}]) is False
    assert pipeline.translation_payload_needs_repair("en", [{"index": 1, "text": "This sentence is English."}]) is False
    assert pipeline.translation_payload_needs_repair("en", [{"index": 1, "text": "[en translation unavailable]"}]) is True


def test_subtitle_validation_rejects_translation_placeholders(tmp_path) -> None:
    candidate = Candidate(
        "long_001",
        "long",
        0.0,
        600.0,
        {"total_score": 1.0},
        "long",
        "source",
    )
    subtitles = {}
    for lang in pipeline.LANGS:
        path = tmp_path / f"long_001.{lang}.srt"
        text = "[en translation unavailable]" if lang == "en" else "text"
        path.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n", encoding="utf-8")
        subtitles[lang] = str(path)

    output = pipeline.output_record(candidate, tmp_path / "long_001.mp4", subtitles)

    with pytest.raises(HarnessError) as excinfo:
        pipeline.validate_output_subtitles([output], pipeline.LANGS)

    assert excinfo.value.code == "subtitle_contains_translation_placeholder"


def test_thumbnail_record_includes_reference_frame_path(tmp_path) -> None:
    reference = tmp_path / "short_001.reference.png"
    record = pipeline.thumbnail_record(
        {"id": "short_001"},
        tmp_path / "short_001.thumbnail.png",
        tmp_path / "short_001.prompt.json",
        "openai_image_generation",
        False,
        1080,
        1920,
        reference,
    )

    assert record["reference_frame_path"] == str(reference)


def test_missing_openai_key_fails_before_creating_outputs(tmp_path, monkeypatch, capsys) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"fake video")
    out_root = tmp_path / "out"

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        pipeline.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None,
    )

    with pytest.raises(SystemExit) as excinfo:
        pipeline.run_harness(HarnessConfig(str(input_video), str(out_root)))

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "ERROR[dependency_check:missing_openai_api_key]: OPENAI_API_KEY is required for normal runs" in captured.err
    assert not out_root.exists()


def test_missing_ffmpeg_fails_before_creating_outputs(tmp_path, monkeypatch, capsys) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"fake video")
    out_root = tmp_path / "out"

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        pipeline.shutil,
        "which",
        lambda name: None if name == "ffmpeg" else f"/usr/bin/{name}",
    )

    with pytest.raises(SystemExit) as excinfo:
        pipeline.run_harness(HarnessConfig(str(input_video), str(out_root)))

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "ERROR[dependency_check:missing_ffmpeg]: ffmpeg is required on PATH" in captured.err
    assert not out_root.exists()


def test_invalid_media_fails_before_creating_outputs(tmp_path, monkeypatch, capsys) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"not real media")
    out_root = tmp_path / "out"

    monkeypatch.setattr(pipeline, "check_dependencies", lambda _config: {"ffmpeg_path": "ffmpeg", "ffprobe_path": "ffprobe"})

    def fake_ffprobe(_path: Path) -> dict:
        raise HarnessError("invalid_media", "ffprobe did not return a valid media duration", "probe")

    monkeypatch.setattr(pipeline, "ffprobe", fake_ffprobe)

    with pytest.raises(SystemExit) as excinfo:
        pipeline.run_harness(HarnessConfig(str(input_video), str(out_root), mock_openai=True))

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "ERROR[probe:invalid_media]: ffprobe did not return a valid media duration" in captured.err
    assert not out_root.exists()


def test_insufficient_short_duration_writes_error_manifest_without_success_manifest(tmp_path, monkeypatch, capsys) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"fake video")
    out_root = tmp_path / "out"
    run_dir = out_root / "source"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text('{"status":"success"}', encoding="utf-8")

    def fake_extract_audio_chunks(_input_path: Path, out_dir: Path, _duration: float) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        chunk = out_dir / "chunk_000.mp3"
        chunk.write_bytes(b"audio")
        return [chunk]

    monkeypatch.setattr(pipeline, "check_dependencies", lambda _config: {"ffmpeg_path": "ffmpeg", "ffprobe_path": "ffprobe"})
    monkeypatch.setattr(
        pipeline,
        "ffprobe",
        lambda _path: {
            "format": {"duration": "120.0", "size": "1024", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}],
        },
    )
    monkeypatch.setattr(pipeline, "extract_audio_chunks", fake_extract_audio_chunks)
    monkeypatch.setattr(pipeline, "detect_silence", lambda _input_path, _duration: [])

    with pytest.raises(SystemExit) as excinfo:
        pipeline.run_harness(HarnessConfig(str(input_video), str(out_root), mock_openai=True))

    captured = capsys.readouterr()
    error_manifest_path = run_dir / "error_manifest.json"
    error_manifest = json.loads(error_manifest_path.read_text(encoding="utf-8"))

    assert excinfo.value.code == 2
    assert "ERROR[candidate_selection:insufficient_short_duration]: not enough usable speech-bearing timeline" in captured.err
    assert not (run_dir / "manifest.json").exists()
    assert error_manifest["status"] == "error"
    assert error_manifest["error_code"] == "insufficient_short_duration"
    assert error_manifest["stage"] == "candidate_selection"
    assert error_manifest["provider_error_class"] is None
    assert error_manifest["partial_outputs"] == []
    assert error_manifest["clean_on_fail_deleted_files"] == []


def test_provider_failure_after_retries_writes_structured_error_manifest(tmp_path, monkeypatch, capsys) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"fake video")
    out_root = tmp_path / "out"
    run_dir = out_root / "source"

    class RetryableProviderError(Exception):
        status_code = 500

    class FakeTranscriptions:
        def create(self, **_kwargs):
            raise RetryableProviderError("temporary provider outage")

    fake_client = SimpleNamespace(audio=SimpleNamespace(transcriptions=FakeTranscriptions()))

    def fake_extract_audio_chunks(_input_path: Path, out_dir: Path, _duration: float) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        chunk = out_dir / "chunk_000.mp3"
        chunk.write_bytes(b"audio")
        return [chunk]

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda: fake_client))
    monkeypatch.setattr(pipeline.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(pipeline, "check_dependencies", lambda _config: {"ffmpeg_path": "ffmpeg", "ffprobe_path": "ffprobe"})
    monkeypatch.setattr(
        pipeline,
        "ffprobe",
        lambda _path: {
            "format": {"duration": "180.0", "size": "1024", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}],
        },
    )
    monkeypatch.setattr(pipeline, "extract_audio_chunks", fake_extract_audio_chunks)

    with pytest.raises(SystemExit) as excinfo:
        pipeline.run_harness(HarnessConfig(str(input_video), str(out_root)))

    captured = capsys.readouterr()
    error_manifest_path = run_dir / "error_manifest.json"
    error_manifest = json.loads(error_manifest_path.read_text(encoding="utf-8"))

    assert excinfo.value.code == 2
    assert "ERROR[stt:openai_stt_failed]: temporary provider outage" in captured.err
    assert not (run_dir / "manifest.json").exists()
    assert error_manifest["status"] == "error"
    assert error_manifest["error_code"] == "openai_stt_failed"
    assert error_manifest["stage"] == "stt"
    assert error_manifest["provider_error_class"] == "RetryableProviderError"
    assert error_manifest["provider_error"] == {
        "provider_error_class": "RetryableProviderError",
        "provider_error_type": "5xx",
        "message": "temporary provider outage",
        "status_code": 500,
        "retryable": True,
        "retries_exhausted": True,
    }
    assert error_manifest["provider_results"]["stt"]["request_count"] == 4
    assert error_manifest["provider_results"]["stt"]["retry_count"] == 3
    assert error_manifest["provider_results"]["stt"]["success"] is False
    assert [item["backoff_seconds"] for item in error_manifest["provider_results"]["stt"]["retry_outcomes"]] == [1, 2, 4]
    assert error_manifest["retry_policy"]["stage_outcomes"]["stt"]["request_count"] == 4
    assert error_manifest["retry_policy"]["stage_outcomes"]["stt"]["retry_count"] == 3
    assert error_manifest["partial_outputs"] == []
    assert error_manifest["clean_on_fail_deleted_files"] == []


def test_provider_retry_policy_does_not_retry_non_retryable_errors(monkeypatch) -> None:
    class BadRequestProviderError(Exception):
        status_code = 400

    sleeps = []
    provider_results = pipeline.initial_provider_results(HarnessConfig("input.mp4", "out"))

    def request():
        raise BadRequestProviderError("invalid provider request")

    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(HarnessError) as excinfo:
        pipeline.call_provider_with_retries(
            "analysis",
            provider_results,
            request,
            "openai_analysis_failed",
            "analysis",
        )

    assert excinfo.value.code == "openai_analysis_failed"
    assert excinfo.value.provider_error_class == "BadRequestProviderError"
    assert provider_results["analysis"]["request_count"] == 1
    assert provider_results["analysis"]["retry_count"] == 0
    assert provider_results["analysis"]["last_error"]["provider_error_type"] == "non_retryable"
    assert sleeps == []


def test_render_failure_writes_structured_error_manifest_with_partial_outputs(tmp_path, monkeypatch, capsys) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"fake video")
    out_root = tmp_path / "out"
    run_dir = out_root / "source"

    def fake_extract_audio_chunks(_input_path: Path, out_dir: Path, _duration: float) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        chunk = out_dir / "chunk_000.mp3"
        chunk.write_bytes(b"audio")
        return [chunk]

    def fake_run_ffmpeg(cmd: list[str], stage: str) -> None:
        partial_path = Path(cmd[-1])
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path.write_bytes(b"partial mp4")
        raise HarnessError(
            "ffmpeg_failed",
            "encoder failed",
            stage,
            details={
                "stage": stage,
                "command": cmd,
                "returncode": 234,
                "stderr": "encoder failed",
                "output_path": str(partial_path),
            },
        )

    monkeypatch.setattr(pipeline, "check_dependencies", lambda _config: {"ffmpeg_path": "ffmpeg", "ffprobe_path": "ffprobe"})
    monkeypatch.setattr(
        pipeline,
        "ffprobe",
        lambda _path: {
            "format": {"duration": "180.0", "size": "1024", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}],
        },
    )
    monkeypatch.setattr(pipeline, "extract_audio_chunks", fake_extract_audio_chunks)
    monkeypatch.setattr(pipeline, "detect_silence", lambda _input_path, _duration: [])
    monkeypatch.setattr(pipeline, "run_ffmpeg", fake_run_ffmpeg)

    with pytest.raises(SystemExit) as excinfo:
        pipeline.run_harness(HarnessConfig(str(input_video), str(out_root), shorts=1, long_candidates=0, mock_openai=True))

    captured = capsys.readouterr()
    partial_output = run_dir / "shorts" / "short_001.mp4"
    error_manifest = json.loads((run_dir / "error_manifest.json").read_text(encoding="utf-8"))

    assert excinfo.value.code == 2
    assert "ERROR[render:ffmpeg_failed]: encoder failed" in captured.err
    assert not (run_dir / "manifest.json").exists()
    assert partial_output.exists()
    assert error_manifest["status"] == "error"
    assert error_manifest["error_code"] == "ffmpeg_failed"
    assert error_manifest["stage"] == "render"
    assert error_manifest["render_error"]["returncode"] == 234
    assert error_manifest["render_error"]["stderr"] == "encoder failed"
    assert error_manifest["render_error"]["output_path"] == str(partial_output)
    assert error_manifest["partial_outputs"] == [str(partial_output)]
    assert error_manifest["clean_on_fail_deleted_files"] == []


def test_render_failure_clean_on_fail_deletes_discovered_partial_outputs(tmp_path, monkeypatch) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"fake video")
    out_root = tmp_path / "out"
    run_dir = out_root / "source"

    def fake_extract_audio_chunks(_input_path: Path, out_dir: Path, _duration: float) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        chunk = out_dir / "chunk_000.mp3"
        chunk.write_bytes(b"audio")
        return [chunk]

    def fake_run_ffmpeg(cmd: list[str], stage: str) -> None:
        partial_path = Path(cmd[-1])
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path.write_bytes(b"partial mp4")
        raise HarnessError(
            "ffmpeg_failed",
            "encoder failed",
            stage,
            details={
                "stage": stage,
                "command": cmd,
                "returncode": 234,
                "stderr": "encoder failed",
                "output_path": str(partial_path),
            },
        )

    monkeypatch.setattr(pipeline, "check_dependencies", lambda _config: {"ffmpeg_path": "ffmpeg", "ffprobe_path": "ffprobe"})
    monkeypatch.setattr(
        pipeline,
        "ffprobe",
        lambda _path: {
            "format": {"duration": "180.0", "size": "1024", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}],
        },
    )
    monkeypatch.setattr(pipeline, "extract_audio_chunks", fake_extract_audio_chunks)
    monkeypatch.setattr(pipeline, "detect_silence", lambda _input_path, _duration: [])
    monkeypatch.setattr(pipeline, "run_ffmpeg", fake_run_ffmpeg)

    with pytest.raises(SystemExit):
        pipeline.run_harness(
            HarnessConfig(
                str(input_video),
                str(out_root),
                shorts=1,
                long_candidates=0,
                mock_openai=True,
                clean_on_fail=True,
            )
        )

    partial_output = run_dir / "shorts" / "short_001.mp4"
    error_manifest = json.loads((run_dir / "error_manifest.json").read_text(encoding="utf-8"))

    assert not partial_output.exists()
    assert error_manifest["partial_outputs"] == [str(partial_output)]
    assert error_manifest["clean_on_fail_deleted_files"] == [str(partial_output)]


def test_success_manifest_records_required_schema_sections(tmp_path, monkeypatch) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"fake video")
    out_root = tmp_path / "out"
    stale_run_dir = out_root / "source"
    stale_run_dir.mkdir(parents=True)
    (stale_run_dir / "error_manifest.json").write_text('{"status":"error"}', encoding="utf-8")

    def fake_extract_audio_chunks(_input_path: Path, out_dir: Path, _duration: float) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        chunk = out_dir / "chunk_000.mp3"
        chunk.write_bytes(b"audio")
        return [chunk]

    def fake_render_candidate(_input_path: Path, run_dir: Path, candidate: Candidate) -> Path:
        folder = run_dir / ("shorts" if candidate.kind == "short" else "long")
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / f"{candidate.id}.mp4"
        output.write_bytes(b"mp4")
        return output

    def fake_render_cleaned_original(_input_path: Path, run_dir: Path, _duration: float, _cut_decisions: dict) -> Path:
        folder = run_dir / "edited"
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / "edited_original.mp4"
        output.write_bytes(b"mp4")
        return output

    monkeypatch.setattr(pipeline, "check_dependencies", lambda _config: {"ffmpeg_path": "ffmpeg", "ffprobe_path": "ffprobe"})
    monkeypatch.setattr(
        pipeline,
        "ffprobe",
        lambda _path: {
            "format": {"duration": "180.0", "size": "1024", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "color_transfer": "bt709",
                },
                {"index": 1, "codec_type": "audio", "codec_name": "aac"},
            ],
        },
    )
    monkeypatch.setattr(pipeline, "extract_audio_chunks", fake_extract_audio_chunks)
    monkeypatch.setattr(pipeline, "detect_silence", lambda _input_path, _duration: [])
    monkeypatch.setattr(pipeline, "render_candidate", fake_render_candidate)
    monkeypatch.setattr(pipeline, "render_cleaned_original", fake_render_cleaned_original)

    manifest_path = pipeline.run_harness(
        HarnessConfig(str(input_video), str(out_root), shorts=1, long_candidates=0, mock_openai=True)
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0"
    assert manifest["status"] == "success"
    assert manifest["completed_at"]
    assert not (manifest_path.parent / "error_manifest.json").exists()
    assert manifest["input"]["path"] == str(input_video.resolve())
    assert manifest["source_probe"]["video_streams"][0]["width"] == 1920
    assert manifest["source_limits"]["passed"] is True
    assert manifest["command_options"]["shorts"] == 1
    assert manifest["dependency_checks"]["ffmpeg_path"] == "ffmpeg"
    assert manifest["audio_chunks"][0]["byte_size"] == 5
    assert manifest["provider_results"]["stt"]["success"] is True
    assert manifest["provider_results"]["analysis"]["mocked"] is True
    assert manifest["provider_results"]["translation"]["model"] == "gpt-4o-mini"
    assert manifest["retry_policy"]["max_retries"] == 3
    assert manifest["transcript"]["word_level_timestamps"] is False
    assert manifest["candidate_scores"]
    assert all(field in manifest["candidates"][0] for field in SCORING_FIELDS)
    assert manifest["cut_decisions"] == manifest["cut_edit"]
    assert Path(manifest["edl_path"]).exists()
    assert Path(manifest["packed_transcript_path"]).exists()
    assert manifest["outputs"]
    assert manifest["output_subtitles"]
    assert manifest["success_manifest"]["status"] == "success"
    assert manifest["error_manifest"] is None


def test_explicit_mock_openai_produces_full_user_visible_artifact_contract_without_network(
    tmp_path,
    monkeypatch,
) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"fake video")
    out_root = tmp_path / "out"
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "openai" or name.startswith("openai."):
            raise AssertionError("mock OpenAI mode must not import the OpenAI SDK")
        return original_import(name, *args, **kwargs)

    def fake_extract_audio_chunks(_input_path: Path, out_dir: Path, _duration: float) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        chunk = out_dir / "chunk_000.mp3"
        chunk.write_bytes(b"audio")
        return [chunk]

    def fake_render_candidate(_input_path: Path, run_dir: Path, candidate: Candidate) -> Path:
        folder = run_dir / ("shorts" if candidate.kind == "short" else "long")
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / f"{candidate.id}.mp4"
        output.write_bytes(f"mp4:{candidate.id}".encode())
        return output

    def fake_render_cleaned_original(_input_path: Path, run_dir: Path, _duration: float, _cut_decisions: dict) -> Path:
        folder = run_dir / "edited"
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / "edited_original.mp4"
        output.write_bytes(b"mp4:edited_original")
        return output

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(
        pipeline.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"ffmpeg", "ffprobe"} else None,
    )
    monkeypatch.setattr(pipeline, "first_line", lambda cmd: f"{Path(cmd[0]).name} version test")
    monkeypatch.setattr(
        pipeline,
        "ffprobe",
        lambda _path: {
            "format": {"duration": "180.0", "size": "1024", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                },
                {"index": 1, "codec_type": "audio", "codec_name": "aac"},
            ],
        },
    )
    monkeypatch.setattr(pipeline, "extract_audio_chunks", fake_extract_audio_chunks)
    monkeypatch.setattr(pipeline, "detect_silence", lambda _input_path, _duration: [])
    monkeypatch.setattr(pipeline, "render_candidate", fake_render_candidate)
    monkeypatch.setattr(pipeline, "render_cleaned_original", fake_render_cleaned_original)

    manifest_path = pipeline.run_harness(HarnessConfig(str(input_video), str(out_root), mock_openai=True))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_dir = manifest_path.parent
    output_ids = {output["id"] for output in manifest["outputs"]}

    assert manifest["status"] == "success"
    assert not (run_dir / "error_manifest.json").exists()
    assert manifest["dependency_checks"]["openai_api_key_present"] is False
    assert manifest["command_options"]["mock_openai"] is True
    assert manifest["supported_subtitle_languages"] == pipeline.LANGS
    assert output_ids == {
        "short_001",
        "short_002",
        "short_003",
        "short_004",
        "short_005",
        "long_001",
        "edited_original",
    }
    assert [output["id"] for output in manifest["outputs"] if output["kind"] == "short"] == [
        "short_001",
        "short_002",
        "short_003",
        "short_004",
        "short_005",
    ]
    assert all(Path(output["path"]).exists() for output in manifest["outputs"])
    assert all(Path(record["path"]).exists() for record in manifest["output_subtitles"])
    assert len(manifest["output_subtitles"]) == len(manifest["outputs"]) * len(pipeline.LANGS)
    assert Path(manifest["edl_path"]).exists()
    assert Path(manifest["packed_transcript_path"]).exists()
    assert Path(manifest["candidate_selection_path"]).exists()
    assert manifest["candidate_selection"]["personas"]
    assert len(manifest["thumbnails"]) == 6
    assert all(Path(record["path"]).exists() for record in manifest["thumbnails"])
    assert manifest_path.exists()
    assert {stage: result["mocked"] for stage, result in manifest["provider_results"].items()} == {
        "stt": True,
        "analysis": True,
        "translation": True,
        "candidate_selection": True,
        "thumbnail": True,
    }
    assert all(result["success"] is True for result in manifest["provider_results"].values())
    assert manifest["provider_results"]["stt"]["request_count"] == 1
    assert manifest["provider_results"]["analysis"]["request_count"] == 1
    assert manifest["provider_results"]["translation"]["request_count"] == 4
    assert manifest["render_order_validation"]["subtitles_after_final_edit_timeline"] is True
