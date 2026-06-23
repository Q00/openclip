from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


SUPPORTED_LANGS = ("en", "ko", "es", "ja", "zh-Hans")
MIN_CUE_DURATION_SECONDS = 0.2


class TimedTextSegment(Protocol):
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SubtitleTimelineSegment:
    source_start_seconds: float
    source_end_seconds: float
    output_start_seconds: float
    output_end_seconds: float


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start_seconds: float
    end_seconds: float
    text: str


def srt_time(seconds: float) -> str:
    ms_total = int(round(max(0.0, seconds) * 1000))
    ms = ms_total % 1000
    total_s = ms_total // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def subtitle_cues_for_window(
    transcript: Sequence[TimedTextSegment],
    translations: Mapping[str, Sequence[Any]],
    language: str,
    start_seconds: float,
    end_seconds: float,
    duration_seconds: float,
) -> list[SubtitleCue]:
    return subtitle_cues_for_timeline(
        transcript,
        translations,
        language,
        [
            SubtitleTimelineSegment(
                source_start_seconds=start_seconds,
                source_end_seconds=end_seconds,
                output_start_seconds=0.0,
                output_end_seconds=duration_seconds,
            )
        ],
        duration_seconds,
    )


def subtitle_cues_for_timeline(
    transcript: Sequence[TimedTextSegment],
    translations: Mapping[str, Sequence[Any]],
    language: str,
    timeline_segments: Sequence[SubtitleTimelineSegment],
    duration_seconds: float,
) -> list[SubtitleCue]:
    cues = []
    translated_segments = translations.get(language) or translations.get("en") or []
    for timeline_segment in timeline_segments:
        source_start = float(timeline_segment.source_start_seconds)
        source_end = float(timeline_segment.source_end_seconds)
        output_start = float(timeline_segment.output_start_seconds)
        output_end = float(timeline_segment.output_end_seconds)
        if source_end <= source_start or output_end <= output_start:
            continue
        for segment_index, segment in enumerate(transcript):
            if segment.start >= source_end or segment.end <= source_start:
                continue
            source_cue_start = max(float(segment.start), source_start)
            source_cue_end = min(float(segment.end), source_end)
            if source_cue_end - source_cue_start < MIN_CUE_DURATION_SECONDS:
                continue
            cue_start = output_start + (source_cue_start - source_start)
            cue_end = output_start + (source_cue_end - source_start)
            cue_start = clamp_seconds(cue_start, min(duration_seconds, output_end))
            cue_end = clamp_seconds(cue_end, min(duration_seconds, output_end))
            cue_end = max(cue_start + MIN_CUE_DURATION_SECONDS, cue_end)
            cue_end = clamp_seconds(cue_end, min(duration_seconds, output_end))
            if cue_end <= cue_start:
                continue
            cues.append(
                SubtitleCue(
                    index=len(cues) + 1,
                    start_seconds=cue_start,
                    end_seconds=cue_end,
                    text=clip_subtitle_text_to_overlap(
                        subtitle_text(translated_segments, segment_index, segment.text),
                        float(segment.start),
                        float(segment.end),
                        source_cue_start,
                        source_cue_end,
                    ),
                )
            )
    return normalize_subtitle_cues(cues, duration_seconds)


def normalize_subtitle_cues(cues: Sequence[SubtitleCue], duration_seconds: float) -> list[SubtitleCue]:
    normalized = []
    cursor = 0.0
    for cue in sorted(cues, key=lambda item: (item.start_seconds, -(item.end_seconds - item.start_seconds), item.index)):
        start = max(float(cue.start_seconds), cursor)
        end = min(float(cue.end_seconds), float(duration_seconds))
        if end - start < MIN_CUE_DURATION_SECONDS:
            continue
        normalized.append(
            SubtitleCue(
                index=len(normalized) + 1,
                start_seconds=start,
                end_seconds=end,
                text=cue.text,
            )
        )
        cursor = end
    return normalized


def write_srt_files(
    output_dir: Path,
    output_id: str,
    transcript: Sequence[TimedTextSegment],
    translations: Mapping[str, Sequence[Any]],
    languages: Sequence[str],
    start_seconds: float,
    end_seconds: float,
    duration_seconds: float,
    timeline_segments: Sequence[SubtitleTimelineSegment] | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for language in languages:
        cues = (
            subtitle_cues_for_timeline(transcript, translations, language, timeline_segments, duration_seconds)
            if timeline_segments is not None
            else subtitle_cues_for_window(
                transcript,
                translations,
                language,
                start_seconds,
                end_seconds,
                duration_seconds,
            )
        )
        path = output_dir / f"{output_id}.{language}.srt"
        path.write_text(render_srt(cues), encoding="utf-8")
        written[language] = str(path)
    return written


def render_srt(cues: Sequence[SubtitleCue]) -> str:
    if not cues:
        return ""
    blocks = []
    for cue in cues:
        blocks.append(
            f"{cue.index}\n"
            f"{srt_time(cue.start_seconds)} --> {srt_time(cue.end_seconds)}\n"
            f"{normalize_srt_text(cue.text)}\n"
        )
    return "\n".join(blocks)


def subtitle_text(translated_segments: Sequence[Any], index: int, fallback: str) -> str:
    if index >= len(translated_segments):
        return fallback
    item = translated_segments[index]
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        value = item.get("text")
        return str(value) if value is not None else fallback
    value = getattr(item, "text", None)
    return str(value) if value is not None else fallback


def normalize_srt_text(text: str) -> str:
    return str(text).replace("\r\n", "\n").replace("\r", "\n").replace("...", " ").replace("…", " ")


def clip_subtitle_text_to_overlap(
    text: str,
    segment_start_seconds: float,
    segment_end_seconds: float,
    cue_start_seconds: float,
    cue_end_seconds: float,
) -> str:
    original = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = " ".join(original.split())
    duration = float(segment_end_seconds) - float(segment_start_seconds)
    cue_duration = float(cue_end_seconds) - float(cue_start_seconds)
    if not normalized or duration <= 0 or cue_duration / duration >= 0.9:
        return original
    if len(normalized) < 42:
        return original

    start_ratio = clamp_ratio((float(cue_start_seconds) - float(segment_start_seconds)) / duration)
    end_ratio = clamp_ratio((float(cue_end_seconds) - float(segment_start_seconds)) / duration)
    if start_ratio <= 0.08 and end_ratio >= 0.92:
        return original

    if start_ratio <= 0.08:
        return clip_text_prefix(normalized, min(1.0, end_ratio + 0.10))
    if end_ratio >= 0.92:
        return clip_text_suffix(normalized, max(0.0, start_ratio - 0.10))
    return clip_text_middle(normalized, max(0.0, start_ratio - 0.08), min(1.0, end_ratio + 0.08))


def clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, value))


def clip_text_prefix(text: str, end_ratio: float) -> str:
    target = max(1, int(len(text) * clamp_ratio(end_ratio)))
    sentences = split_sentences(text)
    if len(sentences) > 1:
        selected = []
        current = 0
        for sentence in sentences:
            next_len = current + len(sentence) + (1 if selected else 0)
            if selected and next_len > target:
                break
            selected.append(sentence)
            current = next_len
        return " ".join(selected).strip() or text[:target].strip()
    return trim_to_word_boundary(text[:target])


def clip_text_suffix(text: str, start_ratio: float) -> str:
    target = int(len(text) * clamp_ratio(start_ratio))
    sentences = split_sentences(text)
    if len(sentences) > 1:
        selected = []
        current_end = len(text)
        for sentence in reversed(sentences):
            current_end -= len(sentence)
            if selected and current_end < target:
                break
            selected.append(sentence)
            current_end -= 1
        return " ".join(reversed(selected)).strip() or text[target:].strip()
    return trim_to_word_boundary(text[target:])


def clip_text_middle(text: str, start_ratio: float, end_ratio: float) -> str:
    start = int(len(text) * clamp_ratio(start_ratio))
    end = max(start + 1, int(len(text) * clamp_ratio(end_ratio)))
    return trim_to_word_boundary(text[start:end])


def trim_to_word_boundary(text: str) -> str:
    stripped = text.strip()
    if " " not in stripped:
        return stripped
    leading = stripped.split(" ", 1)[1] if not stripped[:1].isspace() and " " in stripped else stripped
    if " " in leading:
        leading = leading.rsplit(" ", 1)[0]
    return leading.strip() or stripped


def split_sentences(text: str) -> list[str]:
    sentences = []
    current = []
    terminators = {".", "!", "?", "。", "！", "？"}
    for char in text:
        current.append(char)
        if char in terminators:
            sentence = "".join(current).strip()
            if sentence:
                sentences.append(sentence)
            current = []
    tail = "".join(current).strip()
    if tail:
        sentences.append(tail)
    return sentences


def clamp_seconds(seconds: float, duration_seconds: float) -> float:
    return max(0.0, min(float(duration_seconds), float(seconds)))
