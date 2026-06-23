from __future__ import annotations

from dataclasses import dataclass

from openclip.subtitles import (
    SUPPORTED_LANGS,
    SubtitleTimelineSegment,
    render_srt,
    srt_time,
    subtitle_cues_for_timeline,
    subtitle_cues_for_window,
    write_srt_files,
)


@dataclass(frozen=True)
class FakeSegment:
    start: float
    end: float
    text: str


def test_srt_time_rounds_to_millisecond_precision() -> None:
    assert srt_time(0) == "00:00:00,000"
    assert srt_time(1.2344) == "00:00:01,234"
    assert srt_time(1.2345) == "00:00:01,234"
    assert srt_time(3723.456) == "01:02:03,456"


def test_subtitle_cues_clip_to_output_window_and_preserve_text() -> None:
    transcript = [
        FakeSegment(9.7, 10.5, "first source line"),
        FakeSegment(12.25, 13.75, "second source line"),
        FakeSegment(40.0, 41.0, "outside line"),
    ]
    translations = {
        "en": ["first source line", "second source line", "outside line"],
        "ko": [{"text": "첫 번째 줄"}, {"text": "두 번째 줄"}, {"text": "바깥 줄"}],
    }

    cues = subtitle_cues_for_window(transcript, translations, "ko", 10.0, 20.0, 10.0)

    assert [cue.index for cue in cues] == [1, 2]
    assert cues[0].start_seconds == 0.0
    assert cues[0].end_seconds == 0.5
    assert cues[0].text == "첫 번째 줄"
    assert cues[1].start_seconds == 2.25
    assert cues[1].end_seconds == 3.75
    assert cues[1].text == "두 번째 줄"


def test_partial_segment_subtitle_text_is_trimmed_without_ellipsis() -> None:
    transcript = [
        FakeSegment(
            10.0,
            20.0,
            "다행히도 제 인지 부하에 큰 영향이 없어서 잘 진행을 하고 있어요. 오! 논문! 저는 아카이브를 많이 봐요.",
        )
    ]

    cues = subtitle_cues_for_window(transcript, {"ko": [transcript[0].text]}, "ko", 10.0, 14.0, 4.0)

    assert len(cues) == 1
    assert cues[0].text == "다행히도 제 인지 부하에 큰 영향이 없어서 잘 진행을 하고 있어요."
    assert "논문" not in cues[0].text
    assert "..." not in cues[0].text
    assert "…" not in cues[0].text


def test_render_srt_produces_valid_numbered_blocks() -> None:
    cues = subtitle_cues_for_window(
        [FakeSegment(0.0, 1.234, "Hello\nworld")],
        {"en": ["Hello\nworld"]},
        "en",
        0.0,
        2.0,
        2.0,
    )

    assert render_srt(cues) == "1\n00:00:00,000 --> 00:00:01,234\nHello\nworld\n"


def test_write_srt_files_emits_all_mvp_languages_with_source_and_translation_text(tmp_path) -> None:
    transcript = [
        FakeSegment(0.0, 1.0, "Source one"),
        FakeSegment(1.5, 2.5, "Source two"),
    ]
    translations = {
        "en": ["Source one", "Source two"],
        "ko": ["한국어 하나", "한국어 둘"],
        "es": ["Español uno", "Español dos"],
        "ja": ["日本語一", "日本語二"],
        "zh-Hans": ["简体一", "简体二"],
    }

    written = write_srt_files(tmp_path, "short_001", transcript, translations, SUPPORTED_LANGS, 0.0, 3.0, 3.0)

    assert list(written) == list(SUPPORTED_LANGS)
    for lang in SUPPORTED_LANGS:
        path = tmp_path / f"short_001.{lang}.srt"
        assert written[lang] == str(path)
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "1\n00:00:00,000 --> 00:00:01,000\n" in text
        assert "2\n00:00:01,500 --> 00:00:02,500\n" in text
    assert "Source one" in (tmp_path / "short_001.en.srt").read_text(encoding="utf-8")
    assert "한국어 하나" in (tmp_path / "short_001.ko.srt").read_text(encoding="utf-8")
    assert "Español uno" in (tmp_path / "short_001.es.srt").read_text(encoding="utf-8")
    assert "日本語一" in (tmp_path / "short_001.ja.srt").read_text(encoding="utf-8")
    assert "简体一" in (tmp_path / "short_001.zh-Hans.srt").read_text(encoding="utf-8")


def test_subtitle_cues_for_timeline_shift_segments_after_removed_span() -> None:
    transcript = [
        FakeSegment(1.0, 2.0, "before cut"),
        FakeSegment(12.5, 13.5, "after cut"),
    ]
    timeline = [
        SubtitleTimelineSegment(0.0, 10.0, 0.0, 10.0),
        SubtitleTimelineSegment(12.0, 20.0, 10.0, 18.0),
    ]

    cues = subtitle_cues_for_timeline(transcript, {"en": ["before cut", "after cut"]}, "en", timeline, 18.0)

    assert [(cue.start_seconds, cue.end_seconds, cue.text) for cue in cues] == [
        (1.0, 2.0, "before cut"),
        (10.5, 11.5, "after cut"),
    ]


def test_subtitle_cues_are_positive_duration_and_non_overlapping() -> None:
    transcript = [
        FakeSegment(0.0, 2.0, "first"),
        FakeSegment(0.0, 1.0, "overlap"),
        FakeSegment(2.0, 2.0, "zero"),
        FakeSegment(2.1, 2.15, "too short"),
        FakeSegment(2.2, 3.0, "second"),
    ]

    cues = subtitle_cues_for_window(transcript, {"en": [item.text for item in transcript]}, "en", 0.0, 3.0, 3.0)

    assert [cue.text for cue in cues] == ["first", "second"]
    assert all(cue.end_seconds > cue.start_seconds for cue in cues)
    assert all(first.end_seconds <= second.start_seconds for first, second in zip(cues, cues[1:]))
    assert [cue.index for cue in cues] == [1, 2]


def test_write_srt_files_with_timeline_omits_removed_source_segments(tmp_path) -> None:
    transcript = [
        FakeSegment(1.0, 2.0, "kept before"),
        FakeSegment(10.5, 11.5, "removed middle"),
        FakeSegment(12.25, 13.25, "kept after"),
    ]
    timeline = [
        SubtitleTimelineSegment(0.0, 10.0, 0.0, 10.0),
        SubtitleTimelineSegment(12.0, 20.0, 10.0, 18.0),
    ]

    write_srt_files(
        tmp_path,
        "edited_original",
        transcript,
        {"en": ["kept before", "removed middle", "kept after"]},
        ["en"],
        0.0,
        18.0,
        18.0,
        timeline_segments=timeline,
    )

    text = (tmp_path / "edited_original.en.srt").read_text(encoding="utf-8")
    assert "kept before" in text
    assert "removed middle" not in text
    assert "00:00:10,250 --> 00:00:11,250" in text
    assert "kept after" in text
