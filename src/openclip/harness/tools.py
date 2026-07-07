"""OpenClip tool layer.

Small, composable, JSON-in / JSON-out building blocks that subagents call via
Bash. Each tool does ONE thing, prints a JSON result to stdout, and reuses the
battle-tested ffmpeg / Whisper helpers from ``openclip.pipeline``.

Design: there is no Python orchestrator here. The LLM agent (Claude Code
subagent or Codex) is the control plane — it reads a flow manifest, fans out
work across these tools, and merges the results. This module only provides
deterministic, side-effect-isolated capabilities + a project state file.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ..pipeline import (
    detect_silence,
    ffprobe,
    run_ffmpeg,
    subtitle_overlay_images,
)

AUDIO_CHUNK_SECONDS = 300.0
# Strip subtitle/data/chapter/metadata streams so outputs are clean v+a only —
# a stray timecode `data` track can make some players show a black frame.
CLEAN_OUT = ["-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1"]


# --------------------------------------------------------------------------- #
# project state
# --------------------------------------------------------------------------- #
@dataclass
class Project:
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "project.json"

    @property
    def audio_dir(self) -> Path:
        return self.root / "audio"

    @property
    def transcripts_dir(self) -> Path:
        return self.root / "transcripts"

    def load(self) -> dict[str, Any]:
        if self.manifest_path.exists():
            try:
                return json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"corrupt project manifest {self.manifest_path}: {exc}. "
                    "Fix or delete it (ledger.jsonl still holds completed work), then re-run."
                ) from exc
        return {"chunks": [], "inputs": [], "stages": {}}

    def save(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ledger(proj: "Project", event: str, data: dict[str, Any]) -> None:
    """Append-only JSONL event log for resumability + audit.

    We record events, not snapshots: replaying the ledger reconstructs what
    happened, so an interrupted run resumes from the last real fact instead of a
    guessed state. No wall-clock is written, keeping replays deterministic.
    """
    proj.ensure()
    line = json.dumps({"event": event, **data}, ensure_ascii=False)
    with (proj.root / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _probe_duration(path: Path) -> float:
    return float(ffprobe(path)["format"]["duration"])


def _out_path(proj: "Project", out: str) -> Path:
    """Resolve a user-supplied output path.

    Relative paths are project-relative (the flows document `--out
    thumbnails/<id>.png` etc.), NOT cwd-relative — otherwise renders silently
    land wherever the agent happened to run `oc` from.
    """
    p = Path(out).expanduser()
    if not p.is_absolute():
        p = proj.root / p
    return p.resolve()


def _require_openai_key(context: str) -> None:
    """Fail with an actionable message before a real OpenAI call, not a stack
    trace from inside the SDK. Mock paths never reach this."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            f"OPENAI_API_KEY is not set (needed for {context}); "
            "set it in the environment or a .env file, or pass --mock for offline runs"
        )


# --------------------------------------------------------------------------- #
# resumption: skip a unit of work already recorded done in the ledger
# --------------------------------------------------------------------------- #
def _resume_key(tool: str, **parts: Any) -> str:
    """Stable signature for one unit of work (tool + its inputs + output)."""
    payload = json.dumps({"tool": tool, **parts}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _done_outputs(proj: "Project") -> dict[str, str]:
    """Map resume-key -> output path for completed, keyed ledger events whose
    output still exists on disk. This is what makes a re-run actually resume."""
    ledger = proj.root / "ledger.jsonl"
    done: dict[str, str] = {}
    if not ledger.exists():
        return done
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        key, out = ev.get("key"), ev.get("output")
        if key and out:
            done[key] = out
        if ev.get("event") == "unlink" and key:  # explicit invalidation
            done.pop(key, None)
    return {k: v for k, v in done.items() if Path(v).exists()}


def _resume_hit(proj: "Project", key: str, force: bool) -> str | None:
    """Return the cached output path if this unit is already done and not forced."""
    if force:
        return None
    return _done_outputs(proj).get(key)


# --------------------------------------------------------------------------- #
# proxy: LRF / LRV low-res proxy -> playable mp4
# --------------------------------------------------------------------------- #
def proxy(project: str, input_video: str, scale: int | None = 640, out: str | None = None,
          force: bool = False) -> dict[str, Any]:
    """Convert a DJI ``.LRF`` / GoPro ``.LRV`` low-res proxy (or any clip) to mp4.

    LRF/LRV are valid H.264 elementary streams in a renamed container, so a
    stream copy usually works. We re-encode when downscaling to a review proxy.
    """
    proj = Project(Path(project).expanduser().resolve())
    proj.ensure()
    src = Path(input_video).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"input not found: {src}")
    out_path = _out_path(proj, out) if out else proj.root / "proxy" / f"{src.stem}.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    key = _resume_key("proxy", input=str(src), scale=scale, output=str(out_path),
                      sig=str(src.stat().st_mtime))
    cached = _resume_hit(proj, key, force)
    if cached:
        return {"tool": "proxy", "input": str(src), "output": cached, "scale": scale,
                "resumed": True, "duration_seconds": _probe_duration(Path(cached))}

    if scale:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            "-vf", f"scale=-2:{scale}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
            str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src), "-c", "copy", "-movflags", "+faststart", str(out_path),
        ]
    run_ffmpeg(cmd, "proxy")
    _ledger(proj, "proxy", {"key": key, "input": str(src), "output": str(out_path), "scale": scale})
    return {
        "tool": "proxy",
        "input": str(src),
        "output": str(out_path),
        "scale": scale,
        "resumed": False,
        "duration_seconds": _probe_duration(out_path),
    }


# --------------------------------------------------------------------------- #
# ingest: split source audio into fan-out chunks
# --------------------------------------------------------------------------- #
def ingest(project: str, input_video: str, max_seconds: float | None = None,
           start: float = 0.0, chunk_seconds: float = AUDIO_CHUNK_SECONDS) -> dict[str, Any]:
    """Extract audio chunks (default 5 min). Each chunk = one parallel STT fan-out unit.

    ``start`` lets you target a speech-bearing region of a long source (a lecture's
    intro is often silent, which makes Whisper hallucinate). ``chunk_seconds``
    tunes the fan-out width (shorter chunks = more parallel STT workers). Chunk
    timecodes are absolute source seconds, so downstream cut/clip ranges line up
    with the video.
    """
    proj = Project(Path(project).expanduser().resolve())
    proj.ensure()
    src = Path(input_video).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"input not found: {src}")
    chunk_seconds = float(chunk_seconds)
    if chunk_seconds < 10.0:
        raise ValueError(f"chunk-seconds must be >= 10, got {chunk_seconds}")
    duration = _probe_duration(src)
    start = max(0.0, float(start))
    end = min(duration, start + max_seconds) if max_seconds else duration
    window = max(0.0, end - start)
    chunks = _extract_audio_chunks_offset(src, proj.audio_dir, start, window, chunk_seconds)
    # Use each chunk's MEASURED duration for cumulative absolute starts. ffmpeg's
    # segmenter cuts near — not exactly at — the chunk size, and assuming exact
    # size makes word/segment timecodes drift (and accumulate) over a long source.
    # An exact-boundary source can also leave a sub-frame tail chunk that ffprobe
    # cannot even measure — drop those instead of crashing the ingest.
    usable: list[tuple[Path, float]] = []
    for chunk in chunks:
        try:
            cdur = _probe_duration(chunk)
        except Exception:  # noqa: BLE001 — unprobeable tail sliver
            cdur = 0.0
        if cdur < 0.2:
            chunk.unlink(missing_ok=True)
            continue
        usable.append((chunk, cdur))
    if not usable:
        raise RuntimeError("no usable audio chunks were produced")
    records = []
    cursor = start
    for index, (chunk, cdur) in enumerate(usable):
        records.append(
            {
                "index": index,
                "path": str(chunk),
                "start_seconds": round(cursor, 3),
                "end_seconds": round(min(cursor + cdur, end), 3),
                "measured_duration": round(cdur, 3),
            }
        )
        cursor += cdur
    data = proj.load()
    data["inputs"] = [{"path": str(src), "duration_seconds": duration}]
    data["chunks"] = records
    data["effective_duration_seconds"] = end
    data["ingest_window"] = {"start_seconds": start, "end_seconds": end}
    data["chunk_seconds"] = chunk_seconds
    data.setdefault("stages", {})["ingest"] = "done"
    proj.save(data)
    _ledger(proj, "ingest", {"input": str(src), "start": start, "chunk_count": len(records),
                             "chunk_seconds": chunk_seconds})
    return {
        "tool": "ingest",
        "input": str(src),
        "duration_seconds": duration,
        "window": {"start_seconds": start, "end_seconds": end},
        "chunk_count": len(records),
        "chunks": records,
        "fanout_hint": f"Spawn {len(records)} stt-worker subagents, one per --chunk index.",
    }


def _extract_audio_chunks_offset(src: Path, out_dir: Path, start: float, window: float,
                                 chunk_seconds: float = AUDIO_CHUNK_SECONDS) -> list[Path]:
    """Extract mono mp3 chunks starting at ``start`` seconds for ``window`` seconds.

    Stale chunks from a previous (possibly longer) ingest are cleared first —
    the glob below would otherwise pick them up and corrupt the chunk manifest.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("chunk_*.mp3"):
        stale.unlink()
    pattern = out_dir / "chunk_%03d.mp3"
    run_ffmpeg(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start:.3f}", "-t", f"{window:.3f}", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
         "-f", "segment", "-segment_time", str(int(chunk_seconds)), str(pattern)],
        "audio_extract",
    )
    chunks = sorted(out_dir.glob("chunk_*.mp3"))
    if not chunks:
        raise RuntimeError("no audio chunks were produced")
    return chunks


# --------------------------------------------------------------------------- #
# stt: transcribe ONE chunk (the parallel fan-out unit)
# --------------------------------------------------------------------------- #
def stt(project: str, chunk: int, model: str = "whisper-1", mock: bool = False) -> dict[str, Any]:
    proj = Project(Path(project).expanduser().resolve())
    data = proj.load()
    rec = next((c for c in data.get("chunks", []) if int(c["index"]) == int(chunk)), None)
    if rec is None:
        raise ValueError(f"chunk {chunk} not found; run `oc ingest` first")
    chunk_path = Path(rec["path"])
    # Each chunk mp3 is an independent 0..300s clip; its transcription times are
    # relative to the chunk, so add the chunk's absolute start to line up with the
    # source video (cut/clip ranges).
    base = float(rec["start_seconds"])
    if mock:
        segments = _mock_chunk_segments(base, float(rec["end_seconds"]), int(chunk))
        words = _mock_words(segments)
    else:
        seg_raw, word_raw = _transcribe_words(chunk_path, model, proj.transcripts_dir, int(chunk))
        segments = [
            {"start": round(float(s.get("start", 0)) + base, 3), "end": round(float(s.get("end", 0)) + base, 3),
             "text": str(s.get("text", "")).strip()}
            for s in seg_raw
        ]
        words = [
            {"start": round(float(w.get("start", 0)) + base, 3), "end": round(float(w.get("end", 0)) + base, 3),
             "word": str(w.get("word", ""))}
            for w in word_raw if str(w.get("word", "")).strip()
        ]
    out_path = proj.transcripts_dir / f"chunk_{int(chunk):03d}.segments.json"
    _write_json(out_path, {"chunk": int(chunk), "model": model, "segments": segments, "words": words})
    _ledger(proj, "stt", {"chunk": int(chunk), "segment_count": len(segments), "word_count": len(words), "mock": mock})
    return {
        "tool": "stt",
        "chunk": int(chunk),
        "model": model,
        "mock": mock,
        "segment_count": len(segments),
        "word_count": len(words),
        "output": str(out_path),
    }


def _transcribe_words(chunk_path: Path, model: str, cache_dir: Path, index: int) -> tuple[list, list]:
    """Whisper verbose_json with word + segment timestamps (cached raw payload)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{chunk_path.stem}.{model}.words.json"
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        _require_openai_key(f"Whisper transcription ({model})")
        from openai import OpenAI

        client = OpenAI(timeout=120.0)
        with chunk_path.open("rb") as fh:
            resp = client.audio.transcriptions.create(
                model=model, file=fh, response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )
        payload = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload.get("segments", []) or [], payload.get("words", []) or []


def _mock_words(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words = []
    for s in segments:
        toks = s["text"].split() or [s["text"]]
        span = (s["end"] - s["start"]) / max(1, len(toks))
        for i, t in enumerate(toks):
            words.append({"start": round(s["start"] + i * span, 3),
                          "end": round(s["start"] + (i + 1) * span, 3), "word": (" " if i else "") + t})
    return words


def transcript_merge(project: str) -> dict[str, Any]:
    """Merge all per-chunk transcripts into transcript.json + a packed markdown.

    Reports (and refuses to silently paper over) coverage gaps: an ingested
    chunk with no transcript file means an STT worker was skipped or failed —
    flow 1's "every chunk transcribed" success criterion, checked mechanically.
    """
    proj = Project(Path(project).expanduser().resolve())
    files = sorted(proj.transcripts_dir.glob("chunk_*.segments.json"))
    if not files:
        raise FileNotFoundError("no chunk transcripts found; run `oc stt --chunk N` first")
    expected = [int(c["index"]) for c in proj.load().get("chunks", [])]
    have = {int(json.loads(f.read_text(encoding='utf-8')).get("chunk", -1)) for f in files}
    missing_chunks = sorted(set(expected) - have)

    segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    for f in files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        segments.extend(payload.get("segments", []))
        words.extend(payload.get("words", []))
    segments.sort(key=lambda s: (s["start"], s["end"]))
    words.sort(key=lambda w: (w["start"], w["end"]))
    _write_json(proj.root / "transcript.json", {"segments": segments, "words": words})

    lines = ["# Packed transcript", ""]
    for s in segments:
        lines.append(f"- [{_clock(s['start'])} → {_clock(s['end'])}] {s['text']}")
    (proj.root / "transcript.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    data = proj.load()
    data.setdefault("stages", {})["transcript"] = "done" if not missing_chunks else "partial"
    proj.save(data)
    _ledger(proj, "transcript_merge", {"chunk_files": len(files), "segment_count": len(segments),
                                       "missing_chunks": missing_chunks})
    return {
        "tool": "transcript-merge",
        "chunk_files": len(files),
        "segment_count": len(segments),
        "word_count": len(words),
        "missing_chunks": missing_chunks,
        "complete": not missing_chunks,
        "transcript_json": str(proj.root / "transcript.json"),
        "transcript_md": str(proj.root / "transcript.md"),
    }


# --------------------------------------------------------------------------- #
# probe: structural signals for the cut-editor debate (silence + scene cuts)
# --------------------------------------------------------------------------- #
def probe(project: str, input_video: str, scene_threshold: float = 0.4) -> dict[str, Any]:
    proj = Project(Path(project).expanduser().resolve())
    proj.ensure()
    src = Path(input_video).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"input not found: {src}")
    duration = _probe_duration(src)
    silences = detect_silence(src, duration)
    scenes = _detect_scene_cuts(src, scene_threshold)
    analysis = {
        "input": str(src),
        "duration_seconds": duration,
        "silence_count": len(silences),
        "silences": silences,
        "scene_cut_count": len(scenes),
        "scene_cuts_seconds": scenes,
    }
    _write_json(proj.root / "analysis.json", analysis)
    data = proj.load()
    data.setdefault("stages", {})["probe"] = "done"
    proj.save(data)
    _ledger(proj, "probe", {"input": str(src), "silence_count": len(silences),
                            "scene_cut_count": len(scenes)})
    return {"tool": "probe", **{k: analysis[k] for k in ("duration_seconds", "silence_count", "scene_cut_count")}, "output": str(proj.root / "analysis.json")}


def _detect_scene_cuts(src: Path, threshold: float) -> list[float]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-vf",
         f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        text=True, capture_output=True, check=False,
    )
    cuts = [round(float(x), 3) for x in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]
    # a decode failure must not masquerade as "no scene cuts" — the cut debate
    # would then snap to nothing and blame the footage
    if proc.returncode != 0 and not cuts:
        raise RuntimeError(f"scene-cut detection failed: {proc.stderr.strip()[-300:]}")
    return cuts


def _normalize_span(k: Any) -> dict[str, float]:
    """Accept {"start","end"} objects or [start, end] pairs from any agent."""
    if isinstance(k, dict):
        return {"start": float(k["start"]), "end": float(k["end"])}
    if isinstance(k, (list, tuple)) and len(k) >= 2:
        return {"start": float(k[0]), "end": float(k[1])}
    raise ValueError(f"unrecognized keep span: {k!r}")


def _clean_keep_spans(raw: list[Any], duration: float) -> list[dict[str, float]]:
    """Clamp keep spans to the source and merge overlaps/adjacency.

    Agent-authored EDLs can overlap (two lenses merged naively) or run past the
    source end; rendering them as-is duplicates content or silently truncates.
    """
    spans = [_normalize_span(k) for k in raw]
    spans = [
        {"start": max(0.0, s["start"]), "end": min(duration, s["end"])}
        for s in spans
    ]
    spans = [s for s in spans if s["end"] - s["start"] > 0.05]
    spans.sort(key=lambda s: s["start"])
    merged: list[dict[str, float]] = []
    for s in spans:
        if merged and s["start"] <= merged[-1]["end"] + 0.001:
            merged[-1]["end"] = max(merged[-1]["end"], s["end"])
        else:
            merged.append(dict(s))
    return merged


# --------------------------------------------------------------------------- #
# cut: apply an EDL of keep-ranges -> one rendered mp4 (the cut-edit result)
# --------------------------------------------------------------------------- #
def cut(project: str, input_video: str, edl: str, out: str, aspect: str = "source",
        force: bool = False) -> dict[str, Any]:
    """Render keep-ranges from an EDL file into a single video.

    EDL ``keep`` accepts either ``[{"start": s, "end": e}, ...]`` or ``[[s, e], ...]``.
    ``aspect`` is ``source`` (native) or ``9:16`` (vertical with blurred fill).
    """
    if aspect not in ("source", "9:16"):
        raise ValueError(f"cut aspect must be 'source' or '9:16', got {aspect!r}")
    proj = Project(Path(project).expanduser().resolve())
    src = Path(input_video).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"input not found: {src}")
    raw_keep = json.loads(Path(edl).read_text(encoding="utf-8")).get("keep", [])
    keep = _clean_keep_spans(raw_keep, _probe_duration(src))
    if not keep:
        raise ValueError("EDL has no usable keep ranges")
    out_path = _out_path(proj, out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    key = _resume_key("cut", input=str(src), keep=keep, output=str(out_path), aspect=aspect)
    cached = _resume_hit(proj, key, force)
    if cached:
        kept = sum(float(k["end"]) - float(k["start"]) for k in keep)
        return {"tool": "cut", "input": str(src), "output": cached, "aspect": aspect,
                "keep_ranges": len(keep), "kept_seconds": round(kept, 3), "resumed": True,
                "output_duration_seconds": _probe_duration(Path(cached))}

    work = proj.root / "work" / f"cut_{out_path.stem}"
    work.mkdir(parents=True, exist_ok=True)
    seg_paths: list[Path] = []
    for i, k in enumerate(keep):
        seg = work / f"seg_{i:04d}.mp4"
        run_ffmpeg(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{float(k['start']):.3f}", "-to", f"{float(k['end']):.3f}",
             "-i", str(src), *CLEAN_OUT, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(seg)],
            "cut_segment",
        )
        seg_paths.append(seg)

    concat_file = work / "concat.txt"
    concat_file.write_text("".join(f"file '{p}'\n" for p in seg_paths), encoding="utf-8")
    flat_target = out_path if aspect == "source" else work / "flat.mp4"
    run_ffmpeg(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
         "-safe", "0", "-i", str(concat_file), "-c", "copy", "-movflags", "+faststart", str(flat_target)],
        "cut_concat",
    )
    if aspect == "9:16":
        flat_dur = _probe_duration(flat_target)
        _render_vertical_short(flat_target, 0.0, flat_dur, out_path, None, proj.root, f"cut_{out_path.stem}")
    kept = sum(float(k["end"]) - float(k["start"]) for k in keep)
    _ledger(proj, "cut", {"key": key, "output": str(out_path), "keep_ranges": len(keep), "kept_seconds": round(kept, 3)})
    return {
        "tool": "cut",
        "input": str(src),
        "output": str(out_path),
        "aspect": aspect,
        "keep_ranges": len(keep),
        "kept_seconds": round(kept, 3),
        "resumed": False,
        "output_duration_seconds": _probe_duration(out_path),
    }


# --------------------------------------------------------------------------- #
# clip: extract ONE range with aspect (shorts / hooks)
# --------------------------------------------------------------------------- #
def clip(project: str, input_video: str, start: float, end: float, aspect: str = "9:16",
         out: str | None = None, clip_id: str | None = None, burn_srt: str | None = None,
         force: bool = False) -> dict[str, Any]:
    proj = Project(Path(project).expanduser().resolve())
    proj.ensure()
    src = Path(input_video).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"input not found: {src}")
    start, end = float(start), float(end)
    if end <= start:
        raise ValueError(f"clip end ({end}) must be greater than start ({start})")
    src_duration = _probe_duration(src)
    if start >= src_duration:
        raise ValueError(f"clip start ({start}) is past the source end ({src_duration:.3f}s)")
    end = min(end, src_duration)
    # include end in the default id — two clips sharing a start must not collide
    cid = clip_id or f"clip_{int(start):06d}_{int(end):06d}"
    folder = "shorts" if aspect == "9:16" else "long"
    final = _out_path(proj, out) if out else proj.root / folder / f"{cid}.mp4"
    final.parent.mkdir(parents=True, exist_ok=True)

    srt_sig = str(Path(burn_srt).stat().st_mtime) if burn_srt and Path(burn_srt).exists() else None
    key = _resume_key("clip", input=str(src), start=start, end=end, aspect=aspect,
                      output=str(final), burn=srt_sig)
    cached = _resume_hit(proj, key, force)
    if cached:
        return {"tool": "clip", "id": cid, "input": str(src), "start_seconds": start,
                "end_seconds": end, "output": cached, "aspect": aspect, "resumed": True,
                "duration_seconds": _probe_duration(Path(cached))}

    if aspect == "9:16":
        _render_vertical_short(src, start, end, final, burn_srt, proj.root, cid)
    else:
        _render_source_trim(src, start, end, final, burn_srt, proj.root, cid)

    _ledger(proj, "clip", {"key": key, "id": cid, "output": str(final), "aspect": aspect})
    return {
        "tool": "clip",
        "id": cid,
        "input": str(src),
        "start_seconds": start,
        "end_seconds": end,
        "aspect": aspect,
        "output": str(final),
        "resumed": False,
        "duration_seconds": _probe_duration(final),
    }


def _burn_subs(run_dir: Path, video: Path, clip_id: str, srt: str, out: Path) -> None:
    """Hard-burn a clip-relative SRT by compositing Pillow-rendered caption PNGs.

    This build of ffmpeg has no libass `subtitles` filter, so we render each cue to
    a transparent PNG (Korean-capable font) and overlay it for its time window —
    the same approach the legacy renderer uses, kept here so the harness is
    self-contained.
    """
    dur = _probe_duration(video)
    overlays = subtitle_overlay_images(run_dir, clip_id, Path(srt).expanduser().resolve(), dur)
    if not overlays:
        shutil.copyfile(video, out)
        return
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video)]
    for ov in overlays:
        cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(ov["path"])]
    prev = "[0:v]"
    chain = []
    for i, ov in enumerate(overlays, start=1):
        nxt = "[v]" if i == len(overlays) else f"[v{i}]"
        chain.append(
            f"{prev}[{i}:v]overlay=0:0:enable='between(t,{ov['start_seconds']:.3f},{ov['end_seconds']:.3f})'{nxt}"
        )
        prev = nxt
    cmd += ["-filter_complex", ";".join(chain), "-map", "[v]", "-map", "0:a:0?", *CLEAN_OUT,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-movflags", "+faststart", str(out)]
    run_ffmpeg(cmd, "burn_subs")


def _render_vertical_short(src: Path, start: float, end: float, out: Path,
                           burn_srt: str | None, run_dir: Path, clip_id: str) -> None:
    """9:16 short: source centered full-width (fit), top/bottom filled with a
    zoomed, blurred copy of the source — then optional burned subtitles.
    """
    dur = max(0.1, end - start)
    # bg: zoomed, blurred, slightly darkened so the centered video pops even when
    # the source has a white slide background (otherwise the blur is invisible).
    filt = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "gblur=sigma=24,eq=brightness=-0.12:saturation=0.85[bg];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
    )
    target = out if not burn_srt else out.with_name(out.stem + ".nosub.mp4")
    run_ffmpeg(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
         "-filter_complex", filt, "-map", "[v]", "-map", "0:a:0?", *CLEAN_OUT,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(target)],
        "render_short",
    )
    if burn_srt:
        _burn_subs(run_dir, target, clip_id, burn_srt, out)
        target.unlink(missing_ok=True)


def _render_source_trim(src: Path, start: float, end: float, out: Path,
                        burn_srt: str | None, run_dir: Path, clip_id: str) -> None:
    """Source-aspect clip (long-form / hooks kept at native ratio)."""
    dur = max(0.1, end - start)
    target = out if not burn_srt else out.with_name(out.stem + ".nosub.mp4")
    run_ffmpeg(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
         "-map", "0:v:0", "-map", "0:a:0?", *CLEAN_OUT,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(target)],
        "render_clip",
    )
    if burn_srt:
        _burn_subs(run_dir, target, clip_id, burn_srt, out)
        target.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# thumbnail: a hook-matched thumbnail (representative frame + title, or generated)
# --------------------------------------------------------------------------- #
def thumbnail(project: str, input_video: str, start: float, end: float,
              out: str | None = None, aspect: str = "16:9", title: str | None = None,
              at: float | None = None, generate: bool = False, from_frame: bool = False,
              model: str = "gpt-image-2", mock: bool = False, force: bool = False,
              persona: str | None = None, style: str | None = None,
              quality: str = "high", prompt_note: str | None = None,
              composite: bool = False, render_text: bool = False) -> dict[str, Any]:
    """Make a thumbnail matched to a hook window [start,end].

    Default: grab the most *representative* frame in the window (ffmpeg's
    ``thumbnail`` filter), crop to the target aspect, and burn an optional title.
    ``--generate`` instead asks gpt-image for a thumbnail from the title/caption;
    ``--from-frame`` uses the grabbed frame as the generation reference.

    The PRO path (``--persona`` and/or ``--style``) is what makes a generated
    thumbnail look designed instead of AI slop: a real photo of the actual
    speaker is sent as an identity reference (``images.edit`` with high input
    fidelity), the prompt is built from a curated style preset plus the real
    transcript content around the hook, the model is barred from rendering any
    text, and the Korean headline is typeset locally (Pretendard/Apple Gothic,
    gradient scrim — no black-box captions). ``title`` supports light markup:
    ``|`` forces a line break, ``*word*`` colors that word with the style accent.
    """
    proj = Project(Path(project).expanduser().resolve())
    proj.ensure()
    src = Path(input_video).expanduser().resolve()
    start, end = float(start), float(end)
    W, H = (1280, 720) if aspect == "16:9" else (1080, 1920)
    work = proj.root / "work" / "thumbs"
    work.mkdir(parents=True, exist_ok=True)

    default_out = proj.root / "thumbnails" / f"thumb_{int(start)}.{aspect.replace(':', 'x')}.png"
    resume_out = _out_path(proj, out) if out else default_out
    key = _resume_key("thumbnail", input=str(src), start=start, end=end, aspect=aspect,
                      title=title, at=at, generate=generate, from_frame=from_frame,
                      persona=persona, style=style, quality=quality if generate else None,
                      prompt_note=prompt_note, composite=composite, render_text=render_text,
                      output=str(resume_out))
    cached = _resume_hit(proj, key, force)
    if cached:
        return {"tool": "thumbnail", "output": cached, "aspect": aspect,
                "resolution": f"{W}x{H}", "method": "resumed", "title": title,
                "hook": {"start": start, "end": end}, "resumed": True}

    # 1) representative frame from the hook window, cropped to aspect
    frame = work / f"frame_{int(start)}.png"
    ss = start if at is None else float(at)
    span = max(0.2, end - ss)
    run_ffmpeg(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{ss:.3f}", "-t", f"{span:.3f}", "-i", str(src),
         "-vf", f"thumbnail=120,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
         "-frames:v", "1", str(frame)],
        "thumbnail_frame",
    )

    out_path = resume_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    method = "frame"
    pro = generate and bool(persona or style)
    text_budget: int | None = None

    if composite:
        # no-AI path: real cutout on a flat studio background + typography.
        # Nothing is generated, so nothing can look generated.
        if not persona:
            raise ValueError("--composite requires --persona (the real photo IS the thumbnail)")
        method = "composite"
        style_key = style or "editorial"
        cut = _persona_cutout(persona, work)
        canvas, person_left = _compose_flat(cut, W, H, style_key)
        canvas.convert("RGB").save(out_path)
        base_src = out_path
        if W >= H:
            text_budget = max(int(W * 0.3), person_left - int(W * 0.075))
    elif pro:
        method = "generate-pro"
        style_key = style or "clean"
        refs = _persona_refs(persona, work) if persona else []
        if from_frame:
            refs.append(frame)
        content = _hook_content_excerpt(proj, start, end)
        prompt = _style_prompt(style_key, title or "", content, aspect,
                               has_persona=bool(persona), has_frame=from_frame,
                               note=prompt_note, render_text=render_text)
        gen = _generate_thumbnail_image_pro(prompt, W, H, model, mock, refs, quality)
        gen.save(out_path)
        base_src = out_path
    elif generate:
        method = "generate-from-frame" if from_frame else "generate"
        gen = _generate_thumbnail_image(title or "", W, H, model, mock, frame if from_frame else None)
        gen.save(out_path)
        base_src = out_path
    else:
        base_src = frame

    if title and composite:
        _burn_headline(base_src, out_path, title, W, H, style or "editorial", budget_px=text_budget)
    elif title and pro and render_text:
        pass  # the model typeset the headline itself — reviewer must verify spelling
    elif title and pro:
        _burn_headline(base_src, out_path, title, W, H, style or "clean")
    elif title:
        _burn_thumbnail_title(base_src, out_path, title, W, H)
    elif base_src != out_path:
        from PIL import Image
        Image.open(base_src).convert("RGB").save(out_path)

    _ledger(proj, "thumbnail", {"key": key, "output": str(out_path), "aspect": aspect,
                                "method": method, "hook": [start, end]})
    return {
        "tool": "thumbnail",
        "output": str(out_path),
        "aspect": aspect,
        "resolution": f"{W}x{H}",
        "method": method,
        "title": title,
        "style": style if (pro or composite) else None,
        "persona": persona if (pro or composite) else None,
        "hook": {"start": start, "end": end},
        "frame": str(frame),
        "resumed": False,
    }


def _thumb_font(size: int) -> Any:
    from PIL import ImageFont

    for path in (
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _burn_thumbnail_title(base_src: Path, out_path: Path, title: str, W: int, H: int) -> None:
    from PIL import Image, ImageDraw

    img = Image.open(base_src).convert("RGBA").resize((W, H))
    # draw the scrim on a transparent layer and alpha-composite — drawing an
    # RGBA fill straight onto an RGB image ignores alpha (solid black box).
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _thumb_font(int(H * 0.072))
    # wrap to ~16 chars per line (Korean-friendly width)
    words, lines, cur = title.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) > 16 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    lines = lines[:3]
    line_h = int(H * 0.085)
    total = line_h * len(lines)
    y = int(H * 0.72) - total // 2
    for line in lines:
        tw = draw.textlength(line, font=font)
        x = (W - tw) // 2
        # translucent scrim + stroke for readability
        draw.rectangle([x - 24, y - 8, x + tw + 24, y + line_h - 8], fill=(0, 0, 0, 170))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=max(2, H // 360), stroke_fill=(0, 0, 0, 255))
        y += line_h
    Image.alpha_composite(img, overlay).convert("RGB").save(out_path)


def _generate_thumbnail_image(title: str, W: int, H: int, model: str, mock: bool, reference: Path | None) -> Any:
    from PIL import Image

    if mock:
        return Image.new("RGB", (W, H), (20, 24, 32))
    import base64
    import io

    _require_openai_key(f"thumbnail generation ({model})")
    from openai import OpenAI

    client = OpenAI(timeout=180.0)
    size = "1536x1024" if W >= H else "1024x1536"
    prompt = (
        f"YouTube thumbnail, bold high-contrast, clear focal subject, dramatic lighting, "
        f"space for a headline. Topic headline: '{title}'. Punchy, professional, not cluttered."
    )
    if reference is not None:
        with reference.open("rb") as fh:
            r = client.images.edit(model=model, image=fh, prompt=prompt, size=size)
    else:
        r = client.images.generate(model=model, prompt=prompt, size=size)
    data = base64.b64decode(r.data[0].b64_json)
    return Image.open(io.BytesIO(data)).convert("RGB").resize((W, H))


# --------------------------------------------------------------------------- #
# thumbnail PRO path: persona identity + style presets + local typography
# --------------------------------------------------------------------------- #
# Each preset is a full art direction, not an adjective. Shared rules (identity
# fidelity, no rendered text, anti-slop bans) live in _style_prompt.
# Optional keys: `text: "dark"` typesets a black headline with no shadow/stroke,
# `scrim: False` skips the gradient scrim — the print-cover look for light sets.
_THUMB_STYLES: dict[str, dict[str, Any]] = {
    # understated editorial: real-photo look, calm palette, negative space for type.
    "clean": {
        "look": (
            "Understated editorial portrait photograph, like a well-shot Korean tech "
            "YouTube channel thumbnail. Natural skin texture, soft diffused key light, "
            "gentle contrast, colors graded like a mirrorless camera photo (slightly "
            "muted, warm neutrals). 85mm portrait lens feel, shallow depth of field."
        ),
        "background": (
            "Simple real-world environment: a tidy desk with a laptop softly out of "
            "focus, or a plain warm-gray studio wall. Calm, uncluttered, believable."
        ),
        "accent": "#FFD60A",
    },
    # dev-channel tone: higher contrast, saturated single accent, still photographic.
    "bold": {
        "look": (
            "Punchy tech-YouTuber portrait photograph with strong rim light and one "
            "saturated accent color in the scene. High micro-contrast but still a real "
            "photograph — confident expression, dynamic but honest."
        ),
        "background": (
            "Deep charcoal background with a single colored practical light glow "
            "(teal or amber), like a well-lit dev studio. No patterns, no props."
        ),
        "accent": "#FFEB00",
    },
    # white-editorial cover: pure-white background + black headline, print interview-cover grammar.
    "editorial": {
        "look": (
            "Bright editorial studio portrait in the style of a premium Korean AI "
            "podcast channel: a real photograph in soft, even natural light, calm "
            "confident expression (a slight smile or arms crossed reads well), "
            "graded like a print magazine interview cover. Anti-clickbait restraint."
        ),
        "background": (
            "Pure seamless white studio background — clean white with no props, no "
            "furniture, no environment at all. The person stands cleanly against "
            "white like a professional studio portrait session, soft natural shadow. "
            "The person and every part of their body must stay strictly inside the "
            "right 40% of the frame; the rest is untouched empty white."
        ),
        "accent": "#2E6BE6",
        "text": "dark",
        "scrim": False,
        "bg": (247, 247, 245),
    },
    # keynote tone: conference stage mood.
    "keynote": {
        "look": (
            "Conference keynote photograph: the speaker mid-talk on stage, shot from "
            "the audience with an 85mm f/1.8 prime. Strong warm key light from the "
            "front-left stage rig, crisp subject against a dark falloff, faint honest "
            "stage haze."
        ),
        "background": (
            "Dark auditorium bokeh with a faint cool stage wash. A large blurred "
            "presentation screen glow far behind — unreadable, purely atmospheric."
        ),
        "accent": "#8AB4FF",
    },
}


def _persona_refs(persona: str, work: Path) -> list[Path]:
    """Resolve --persona (file or directory) to identity reference image(s).

    A directory picks the highest-resolution photo. References are re-encoded
    to a bounded PNG (EXIF-upright, long side <= 1536) so uploads stay small
    and orientation bugs can't flip the face.
    """
    from PIL import Image, ImageOps

    p = Path(persona).expanduser().resolve()
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    if p.is_dir():
        candidates = [f for f in sorted(p.iterdir()) if f.suffix.lower() in exts]
        if not candidates:
            raise FileNotFoundError(f"no persona images (png/jpg/webp) in {p}")

        def pixels(f: Path) -> int:
            try:
                with Image.open(f) as im:
                    return im.width * im.height
            except Exception:  # noqa: BLE001
                return 0

        chosen = [max(candidates, key=pixels)]
    elif p.exists():
        chosen = [p]
    else:
        raise FileNotFoundError(f"persona reference not found: {p}")

    refs = []
    for i, photo in enumerate(chosen):
        with Image.open(photo) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1536, 1536))
            ref = work / f"persona_{i}.png"
            im.save(ref)
            refs.append(ref)
    return refs


def _hook_content_excerpt(proj: "Project", start: float, end: float, max_chars: int = 400) -> str:
    """Pull what is actually said around the hook from transcript.json, so the
    prompt describes the real content instead of hallucinating props."""
    tj = proj.root / "transcript.json"
    if not tj.exists():
        return ""
    try:
        data = json.loads(tj.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    lo, hi = start - 20.0, end + 20.0
    texts = [s.get("text", "").strip() for s in data.get("segments", [])
             if s.get("end", 0) > lo and s.get("start", 0) < hi]
    joined = " ".join(t for t in texts if t)
    return joined[:max_chars].strip()


def _rendered_text_spec(title: str, style: str, aspect: str) -> str:
    """Instruction block for letting gpt-image-2 typeset the headline itself.

    Korean rendering on v2 is good but PROBABILISTIC — the exact strings are
    quoted per line and the reviewer must verify spelling on every render."""
    preset = _THUMB_STYLES.get(style, _THUMB_STYLES["clean"])
    color = "black (#111111)" if preset.get("text") == "dark" else "white (#FFFFFF)"
    position = (
        "on the left side, vertically centered, left-aligned"
        if aspect == "16:9" else "at the top, horizontally centered"
    )
    lines = _headline_lines(title)
    specs = []
    for i, line in enumerate(lines, 1):
        text = " ".join(w for w, _ in line)
        accents = [w for w, acc in line if acc]
        rule = (
            f' where ONLY "{accents[0]}" is {preset["accent"]} and the rest {color}'
            if accents else f" in {color}"
        )
        specs.append(f'line {i}: "{text}"{rule}')
    return (
        f"Typeset the headline {position}, in a very heavy Korean sans-serif "
        f"(Pretendard Black style), {len(lines)} line(s), tight leading:\n"
        + "\n".join(specs)
        + "\nRender the Korean text EXACTLY as written, correctly spelled, "
        "crisp vector-sharp edges."
    )


def _style_prompt(style: str, title: str, content: str, aspect: str,
                  has_persona: bool, has_frame: bool, note: str | None = None,
                  render_text: bool = False) -> str:
    """Structured gpt-image-2 prompt.

    The model responds to labeled slots with line breaks (Scene / Subject /
    Important details / Use case / Change+Preserve / Constraints), reference
    images labeled by role, photography facts instead of quality words
    ("8K/ultra-realistic/cinematic" push toward plastic), and candid
    imperfection cues. Sources: OpenAI image-gen prompting cookbook, fal.ai
    gpt-image-2 guide.
    """
    preset = _THUMB_STYLES.get(style, _THUMB_STYLES["clean"])
    if aspect == "16:9":
        composition = (
            "a wide environmental shot with the camera pulled well back — the quiet "
            "environment carries the frame and the person is a smaller element within "
            "it (upper body, head height about a quarter of the frame height), placed "
            "on the right third; the left ~55% stays empty calm negative space for a "
            "headline that is typeset later."
        )
    else:
        composition = (
            "a medium-wide shot — the person small in the lower two thirds with "
            "generous breathing room; the top third stays empty calm negative space "
            "for a headline that is typeset later."
        )

    refs = []
    if has_persona:
        refs.append("Image 1 is the actual speaker (identity reference).")
    if has_frame:
        refs.append(
            f"Image {2 if has_persona else 1} is a frame from the actual talk — "
            "mood and context only, never copy its UI or slide text."
        )

    subject = "The speaker from Image 1" if has_persona else "A single speaker"
    details = [
        preset["look"],
        "Real photographic texture: visible skin pores, natural hair strands, true "
        "fabric weave, faint film grain. Calm, unhurried mood: an at-rest posture, "
        "composed neutral expression (a faint smile at most), muted restrained "
        "grading, no glamour pose, no exaggerated reaction, subtly off-center like "
        "a photographer framed it.",
    ]
    if note:
        details.append(note.strip())

    lines = []
    if refs:
        lines.append(" ".join(refs))
    lines.append(f"Scene: {preset['background']} Composition: {composition}")
    lines.append(f"Subject: {subject}.")
    lines.append("Important details: " + " ".join(details))
    topic = " ".join(x for x in [title.replace("|", " ").replace("*", ""), content] if x).strip()
    if topic:
        lines.append(
            f"Context: the video moment is about — {topic}. Let this shape mood and "
            "subtle environment only, not literal diagrams."
        )
    if render_text and title.strip():
        lines.append("Use case: a finished YouTube thumbnail, print-cover style.")
        lines.append(_rendered_text_spec(title, style, aspect))
    else:
        lines.append(
            "Use case: base photograph for a YouTube thumbnail (the headline text is "
            "overlaid separately in post)."
        )
    if has_persona:
        lines.append(
            "Change: build this scene around the speaker. "
            "Preserve: the exact person from Image 1 — identical face, facial "
            "features, glasses, hairstyle, facial hair, skin tone and build; do not "
            "beautify, de-age, slim, or swap identity."
        )
    no_text = (
        "no OTHER text besides the specified headline — no captions, logos, watermarks or UI"
        if render_text and title.strip()
        else "no text, letters, numbers, captions, logos, watermarks or UI anywhere in the image"
    )
    lines.append(
        f"Constraints: {no_text}. No glowing arrows, charts, brains, robots, holograms, "
        "floating icons, fake dashboards, lens flares or cheesy composites. No plastic "
        "skin, no heavy retouching, no symmetry correction. It must read as a "
        "professionally shot and graded photograph, not an AI illustration."
    )
    return "\n".join(lines)


def _generate_thumbnail_image_pro(prompt: str, W: int, H: int, model: str,
                                  mock: bool, refs: list[Path], quality: str) -> Any:
    from PIL import Image

    if mock:
        return Image.new("RGB", (W, H), (26, 28, 34))
    import base64
    import io

    _require_openai_key(f"thumbnail generation ({model})")
    from openai import OpenAI

    client = OpenAI(timeout=600.0)
    size = "1536x1024" if W >= H else "1024x1536"
    if refs:
        handles = [r.open("rb") for r in refs]
        try:
            kwargs: dict[str, Any] = dict(
                model=model, image=handles if len(handles) > 1 else handles[0],
                prompt=prompt, size=size, quality=quality,
            )
            # gpt-image-2 rejects input_fidelity (identity fidelity is always-on);
            # gpt-image-1/1.5 need it explicitly for face preservation.
            if not model.startswith("gpt-image-2"):
                kwargs["input_fidelity"] = "high"
            try:
                r = client.images.edit(**kwargs)
            except Exception as exc:  # noqa: BLE001
                # unknown model/SDK combo: retry once without the fidelity knob
                if "input_fidelity" not in kwargs or "input_fidelity" not in str(exc):
                    raise
                kwargs.pop("input_fidelity")
                r = client.images.edit(**kwargs)
        finally:
            for fh in handles:
                fh.close()
    else:
        r = client.images.generate(model=model, prompt=prompt, size=size, quality=quality)
    data = base64.b64decode(r.data[0].b64_json)
    return Image.open(io.BytesIO(data)).convert("RGB").resize((W, H))


def _persona_cutout(persona: str, work: Path) -> Path:
    """Background-removed persona cutout for the composite (no-AI) path.

    If the chosen photo already carries real transparency it is used as-is;
    otherwise rembg (via uvx, cached per source signature) removes the
    background. Deterministic and offline after the first model download.
    """
    from PIL import Image, ImageOps

    p = Path(persona).expanduser().resolve()
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    if p.is_dir():
        candidates = [f for f in sorted(p.iterdir()) if f.suffix.lower() in exts]
        if not candidates:
            raise FileNotFoundError(f"no persona images (png/jpg/webp) in {p}")

        def pixels(f: Path) -> int:
            try:
                with Image.open(f) as im:
                    return im.width * im.height
            except Exception:  # noqa: BLE001
                return 0

        p = max(candidates, key=pixels)
    if not p.exists():
        raise FileNotFoundError(f"persona reference not found: {p}")

    with Image.open(p) as im:
        im = ImageOps.exif_transpose(im)
        has_alpha = im.mode in {"RGBA", "LA"} and im.getextrema()[-1][0] < 250
        if has_alpha:
            cut = work / f"cutout_{p.stem}.png"
            im.convert("RGBA").save(cut)
            return cut

    sig = hashlib.sha1(f"{p}:{p.stat().st_mtime}".encode()).hexdigest()[:10]
    cut = work / f"cutout_{sig}.png"
    if cut.exists():
        return cut
    import subprocess

    try:
        subprocess.run(
            ["uvx", "--python", "3.11", "--from", "rembg[cpu,cli]",
             "rembg", "i", str(p), str(cut)],
            check=True, capture_output=True, timeout=600,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "composite thumbnails need `uvx` (uv) on PATH to run rembg for the "
            "persona cutout — install uv, or pass an already-cutout RGBA png as --persona"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"rembg background removal failed: {exc.stderr.decode(errors='replace')[-400:]}") from exc
    if not cut.exists():
        raise RuntimeError("rembg reported success but wrote no cutout")
    return cut


def _compose_flat(cutout: Path, W: int, H: int, style: str) -> tuple[Any, int]:
    """Place the real cutout on a flat studio background (the white-cover print
    look, zero generated pixels). Returns (RGBA canvas, person-left-x) so the
    typographer gets a deterministic text budget instead of a guess."""
    from PIL import Image, ImageFilter, ImageOps

    preset = _THUMB_STYLES.get(style, _THUMB_STYLES["editorial"])
    bg_color = tuple(preset.get("bg", (247, 247, 245)))
    person = Image.open(cutout).convert("RGBA")
    person = ImageOps.exif_transpose(person)
    box = person.getbbox()
    if box:
        person = person.crop(box)

    landscape = W >= H
    target_h = int(H * (0.88 if landscape else 0.66))
    ratio = target_h / person.height
    person = person.resize((max(1, int(person.width * ratio)), target_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (W, H), (*bg_color, 255))
    if landscape:
        x = W - person.width + int(W * 0.04)
    else:
        x = (W - person.width) // 2
    y = H - person.height

    # soft contact shadow so the cutout doesn't float
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", person.size, (30, 30, 35, 255))
    shadow.putalpha(person.split()[3].point(lambda a: int(a * 0.16)))
    layer.paste(shadow, (x - 12, y + 10), shadow)
    layer = layer.filter(ImageFilter.GaussianBlur(max(8, H // 45)))
    canvas = Image.alpha_composite(canvas, layer)
    canvas.paste(person, (x, y), person)
    return canvas, x


def _headline_font(size: int) -> Any:
    """Heaviest Korean-capable display font available; falls back gracefully."""
    from PIL import ImageFont

    home = Path.home()
    candidates: list[tuple[str, int]] = [
        (str(home / "Library/Fonts/Pretendard-Black.ttf"), 0),
        (str(home / "Library/Fonts/Pretendard-ExtraBold.ttf"), 0),
        ("/Library/Fonts/Pretendard-Black.ttf", 0),
        ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 16),  # Heavy face
        ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 6),   # Bold face
        ("/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf", 0),
        ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", 0),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ]
    for path, index in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=index)
            except Exception:  # noqa: BLE001
                continue
    return _thumb_font(size)


def _headline_lines(title: str, max_chars: int = 10) -> list[list[tuple[str, bool]]]:
    """Parse headline markup into lines of (word, accented) runs.

    ``|`` = explicit line break, ``*word*`` = accent color. Without explicit
    breaks, wraps at ~max_chars (Korean-friendly). Hard cap: 3 lines.
    """
    def runs(chunk: str) -> list[tuple[str, bool]]:
        out = []
        for word in chunk.split():
            if len(word) > 2 and word.startswith("*") and word.endswith("*"):
                out.append((word[1:-1], True))
            else:
                out.append((word, False))
        return out

    if "|" in title:
        lines = [runs(c) for c in title.split("|") if c.strip()]
    else:
        words, lines, cur = runs(title), [], []
        for word, acc in words:
            trial = " ".join([w for w, _ in cur] + [word])
            if len(trial) > max_chars and cur:
                lines.append(cur)
                cur = [(word, acc)]
            else:
                cur.append((word, acc))
        if cur:
            lines.append(cur)
    return lines[:3]


def _burn_headline(base_src: Path, out_path: Path, title: str, W: int, H: int, style: str,
                   budget_px: int | None = None) -> None:
    """Typeset the headline like a designed thumbnail — no black caption boxes.

    Dark presets: heavy white type over a soft gradient scrim with a blurred
    drop shadow. Light presets (``text: dark``): plain black print-cover type,
    no scrim, no shadow — the white-editorial print-cover look.
    """
    from PIL import Image, ImageDraw, ImageFilter

    preset = _THUMB_STYLES.get(style, _THUMB_STYLES["clean"])
    accent = preset["accent"]
    dark_text = preset.get("text") == "dark"
    img = Image.open(base_src).convert("RGBA").resize((W, H))
    lines = _headline_lines(title)
    if not lines:
        img.convert("RGB").save(out_path)
        return

    landscape = W >= H
    font_px = int(H * (0.118 if len(lines) <= 2 else 0.098)) if landscape else int(H * 0.052)
    font = _headline_font(font_px)
    # shrink to the text budget: light presets must never overlap the subject
    # (no scrim to save them), dark presets just stay inside the frame
    budget = budget_px if budget_px is not None else W * (0.55 if dark_text and landscape else 0.89)
    from PIL import ImageDraw as _ID
    probe = _ID.Draw(Image.new("RGB", (8, 8)))
    widest = max(
        sum(probe.textlength(w, font=font) for w, _ in line)
        + probe.textlength(" ", font=font) * max(0, len(line) - 1)
        for line in lines
    )
    if widest > budget:
        font_px = max(24, int(font_px * budget / widest))
        font = _headline_font(font_px)
    line_h = int(font_px * 1.22)
    block_h = line_h * len(lines)

    if preset.get("scrim", True):
        # soft gradient scrim behind the text zone only (bottom 16:9, top 9:16)
        scrim = Image.new("L", (1, H), 0)
        depth = int(H * 0.62) if landscape else int(H * 0.44)
        for i in range(depth):
            # darkest at the frame edge, easing to 0 at the scrim's inner boundary
            a = int(165 * (1 - i / depth) ** 2.4)
            yy = H - 1 - i if landscape else i
            scrim.putpixel((0, min(max(yy, 0), H - 1)), a)
        black = Image.new("RGBA", (W, H), (8, 9, 12, 255))
        img = Image.composite(black, img, scrim.resize((W, H)))

    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    shadow = ImageDraw.Draw(shadow_layer)
    fill = (17, 17, 17, 255) if dark_text else (255, 255, 255, 255)
    stroke_w = 0 if dark_text else max(1, H // 700)

    if landscape:
        x0 = int(W * 0.055)
        # light presets have no scrim to guarantee contrast at the bottom edge —
        # center the block in the left negative space (print-cover placement)
        # instead of overlapping the subject's lower body
        y = (H - block_h) // 2 + int(H * 0.06) if dark_text else H - int(H * 0.075) - block_h
    else:
        y = int(H * 0.07)
    space = draw.textlength(" ", font=font)
    for line in lines:
        widths = [draw.textlength(word, font=font) for word, _ in line]
        if landscape:
            x = x0
        else:
            x = (W - (sum(widths) + space * (len(line) - 1))) // 2
        for (word, acc), tw in zip(line, widths):
            if not dark_text:
                shadow.text((x + 3, y + 5), word, font=font, fill=(0, 0, 0, 200))
            draw.text((x, y), word, font=font,
                      fill=accent if acc else fill,
                      stroke_width=stroke_w, stroke_fill=(10, 10, 12, 160))
            x += tw + space
        y += line_h
    if not dark_text:
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(max(3, H // 260)))
        img = Image.alpha_composite(img, shadow_layer)
    img = Image.alpha_composite(img, text_layer)
    img.convert("RGB").save(out_path)


# --------------------------------------------------------------------------- #
# subtitle: build an SRT for a time range (optionally clip-relative + translated)
# --------------------------------------------------------------------------- #
def subtitle(project: str, start: float = 0.0, end: float | None = None,
             out: str | None = None, relative: bool = True,
             translate_to: str | None = None, model: str = "gpt-4o-mini",
             mock: bool = False, max_cue_seconds: float = 2.2,
             max_cue_chars: int = 18) -> dict[str, Any]:
    """Slice the merged transcript into an SRT. ``relative`` rebases times to the clip start.

    Source-language captions use WORD-level timing (short, speech-synced cues).
    Translations stay segment-level to preserve sentence context.
    """
    proj = Project(Path(project).expanduser().resolve())
    tj = proj.root / "transcript.json"
    if not tj.exists():
        raise FileNotFoundError("transcript.json missing; run stt + transcript-merge first")
    data = json.loads(tj.read_text(encoding="utf-8"))
    segments = data.get("segments", [])
    words = data.get("words", [])
    start = float(start)
    end = float(end) if end is not None else max((s["end"] for s in segments), default=start)
    off = start if relative else 0.0

    if words and not translate_to:
        # word-timed: short cues that appear as they are spoken
        cues = _cues_from_words(words, start, end, off, max_sec=max_cue_seconds,
                                max_chars=max_cue_chars)
    else:
        window = [s for s in segments if s["end"] > start and s["start"] < end]
        texts = _translate([s["text"] for s in window], translate_to, model, mock) if translate_to else [s["text"] for s in window]
        cues = [
            (max(s["start"], start) - off, min(s["end"], end) - off, texts[i])
            for i, s in enumerate(window)
        ]
    if not cues:
        raise ValueError(
            f"no transcript content in range {start:.1f}-{end:.1f}s; "
            "an empty SRT would burn no captions — check the clip range or re-run stt"
        )
    srt = _render_srt(cues)

    lang = translate_to or "src"
    out_path = _out_path(proj, out) if out else proj.root / "subs" / f"sub_{int(start):06d}.{lang}.srt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(srt, encoding="utf-8")
    return {
        "tool": "subtitle",
        "output": str(out_path),
        "cue_count": len(cues),
        "lang": lang,
        "relative": relative,
        "start_seconds": start,
        "end_seconds": end,
    }


def burn_srt(project: str, input_video: str, srt: str, out: str,
             font_size: int = 22, margin_v: int = 40, force: bool = False) -> dict[str, Any]:
    """Hard-burn an SRT into a video via the ffmpeg subtitles filter."""
    proj = Project(Path(project).expanduser().resolve())
    src = Path(input_video).expanduser().resolve()
    srt_path = Path(srt).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"input not found: {src}")
    if not srt_path.exists():
        raise FileNotFoundError(f"srt not found: {srt_path}")
    out_path = _out_path(proj, out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    key = _resume_key("burn-srt", input=str(src), srt=str(srt_path), output=str(out_path),
                      font_size=font_size, margin_v=margin_v,
                      sigs=[str(src.stat().st_mtime), str(srt_path.stat().st_mtime)])
    cached = _resume_hit(proj, key, force)
    if cached:
        return {"tool": "burn-srt", "input": str(src), "srt": str(srt_path),
                "output": cached, "resumed": True}

    style = f"FontSize={font_size},MarginV={margin_v},Outline=2,Shadow=0"
    escaped = str(srt_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    run_ffmpeg(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-vf", f"subtitles='{escaped}':force_style='{style}'",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", str(out_path)],
        "burn_srt",
    )
    _ledger(proj, "burn_srt", {"key": key, "input": str(src), "srt": str(srt_path), "output": str(out_path)})
    return {"tool": "burn-srt", "input": str(src), "srt": str(srt_path), "output": str(out_path),
            "resumed": False}


# --------------------------------------------------------------------------- #
# concat: join clips into a longform
# --------------------------------------------------------------------------- #
def concat(project: str, inputs: list[str], out: str, force: bool = False) -> dict[str, Any]:
    proj = Project(Path(project).expanduser().resolve())
    proj.ensure()
    srcs = [Path(p).expanduser().resolve() for p in inputs]
    for s in srcs:
        if not s.exists():
            raise FileNotFoundError(f"concat input not found: {s}")
    out_path = _out_path(proj, out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    key = _resume_key("concat", inputs=[str(s) for s in srcs],
                      sigs=[str(s.stat().st_mtime) for s in srcs], output=str(out_path))
    cached = _resume_hit(proj, key, force)
    if cached:
        return {"tool": "concat", "inputs": [str(s) for s in srcs], "output": cached,
                "resumed": True, "output_duration_seconds": _probe_duration(Path(cached))}

    work = proj.root / "work" / f"concat_{out_path.stem}"
    work.mkdir(parents=True, exist_ok=True)

    # normalize each input so concat-by-stream-copy is safe
    norm_paths = []
    for i, s in enumerate(srcs):
        n = work / f"norm_{i:04d}.mp4"
        run_ffmpeg(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(s),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
             # -ac 2: a mono + stereo mix breaks the stream-copy concat below
             "-r", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2",
             *CLEAN_OUT, "-movflags", "+faststart", str(n)],
            "concat_normalize",
        )
        norm_paths.append(n)
    concat_file = work / "concat.txt"
    concat_file.write_text("".join(f"file '{p}'\n" for p in norm_paths), encoding="utf-8")
    run_ffmpeg(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(concat_file), "-c", "copy", "-movflags", "+faststart", str(out_path)],
        "concat",
    )
    _ledger(proj, "concat", {"key": key, "inputs": len(srcs), "output": str(out_path)})
    return {
        "tool": "concat",
        "inputs": [str(s) for s in srcs],
        "output": str(out_path),
        "resumed": False,
        "output_duration_seconds": _probe_duration(out_path),
    }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# verify: mechanical evidence gate
# --------------------------------------------------------------------------- #
# A deliverable's "done" is a claim until evidence proves it. These are the
# video-specific failure modes a "render succeeded" log will happily hide; the
# verifier agent probes the applicable ones.
ADVERSARIAL_CLASSES = {
    "blank_frames": "black/blank frames after the intended end (render ran long)",
    "duration_drift": "output duration far from the intended span",
    "wrong_aspect": "aspect/resolution not what the deliverable contract requires",
    "cut_off_by_one": "a cut starts mid-clause or ends before the payoff",
    "stale_render": "an old file from a previous run survived the rerun",
    "audio_desync": "subtitles/audio drift after a cut or concat join",
    "silent_audio": "audio track present but silent / decode failure",
    "srt_invalid": "zero-length, overlapping, or out-of-order subtitle cues",
    "misleading_success": "manifest/log says success while the artifact is wrong",
}


def verify(project: str, path: str, kind: str = "clip",
           expect_duration: float | None = None, tolerance: float = 1.5,
           expect_aspect: str | None = None, srt: str | None = None) -> dict[str, Any]:
    """Mechanical evidence for one deliverable. Writes evidence/<name>.json.

    This is the $0 fast gate (mechanical tier). It does NOT make editorial calls
    — that is the verifier agent's job (semantic tier). It produces observable
    facts the agent must cite, not "looks correct".
    """
    proj = Project(Path(project).expanduser().resolve())
    target = Path(path).expanduser().resolve()
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    exists = target.exists() and target.stat().st_size > 0
    check("file_exists_nonempty", exists, {"path": str(target), "bytes": target.stat().st_size if target.exists() else 0})

    duration = None
    width = height = None
    has_audio = False
    if exists and target.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        try:
            from PIL import Image, ImageStat

            img = Image.open(target)
            width, height = img.size
            check("image_decodes", True, {"width": width, "height": height})
            if expect_aspect:
                try:
                    aw, ah = (int(x) for x in expect_aspect.split(":"))
                    check("aspect_matches", abs(aw / ah - width / height) < 0.02,
                          {"expect": expect_aspect, "width": width, "height": height})
                except (ValueError, ZeroDivisionError):
                    pass
            # a near-solid image is a grabbed transition/black frame, not a thumbnail
            stat = ImageStat.Stat(img.convert("L"))
            check("image_not_solid", stat.stddev[0] > 4.0,
                  {"luma_stddev": round(stat.stddev[0], 2), "floor": 4.0})
        except Exception as exc:  # noqa: BLE001
            check("image_decodes", False, {"error": str(exc)})
    if exists and target.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4a"}:
        probe = ffprobe(target)
        duration = float(probe["format"].get("duration", 0.0))
        check("duration_positive", duration > 0.1, {"duration_seconds": duration})
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "video":
                width, height = stream.get("width"), stream.get("height")
            if stream.get("codec_type") == "audio":
                has_audio = True
        if target.suffix.lower() != ".m4a":
            # an audio-only mp4 (video stream lost in a bad filter graph) must
            # not pass as a video deliverable
            check("has_video_stream", width is not None, {"width": width, "height": height})
        if expect_duration is not None:
            drift = abs(duration - float(expect_duration))
            check("duration_within_tolerance", drift <= tolerance,
                  {"expected": expect_duration, "actual": duration, "drift": round(drift, 3), "tolerance": tolerance})
        if expect_aspect and width and height:
            try:
                aw, ah = (int(x) for x in expect_aspect.split(":"))
                want = aw / ah
                got = width / height
                check("aspect_matches", abs(want - got) < 0.02, {"expect": expect_aspect, "width": width, "height": height})
            except (ValueError, ZeroDivisionError):
                pass
        check("has_audio_stream", has_audio, {"has_audio": has_audio})
        if has_audio and target.suffix.lower() != ".m4a":
            mv = _mean_volume_db(target)
            check("audio_not_silent", mv is None or mv > -60.0, {"mean_volume_db": mv, "floor_db": -60.0})
        if width:  # a video stream exists
            luma = _frame_luma_at(target, max(0.0, (duration or 0.0) - 0.5))
            mid = _frame_luma_at(target, (duration or 0.0) / 2)
            # relative check: a black TAIL means the end is much darker than the
            # clip's own midpoint. Uniformly dark content (dark slides, mid > 3)
            # is fine; an all-black clip (mid ~ 0-1 after limited-range encode)
            # still fails.
            uniform_dark = (luma is not None and mid is not None
                            and mid > 3.0 and luma >= mid - 4.0)
            check("last_frame_not_black", luma is None or luma > 8.0 or uniform_dark,
                  {"last_frame_luma": luma, "mid_frame_luma": mid, "floor": 8.0,
                   "uniform_dark_content": uniform_dark})

    if exists and target.suffix.lower() == ".srt":
        # an SRT can BE the deliverable (subtitle-agent sidecar)
        ok, detail = _srt_validity(target)
        check("srt_valid", ok, detail)

    if srt:
        ok, detail = _srt_validity(Path(srt).expanduser().resolve())
        check("srt_valid", ok, detail)
        # captions must not run past the video (the clip-`end` default bug class)
        if duration and isinstance(detail, dict) and detail.get("max_end") is not None:
            check("srt_within_video", detail["max_end"] <= duration + 0.5,
                  {"max_cue_end": detail["max_end"], "video_duration": duration})

    passed = all(c["pass"] for c in checks)
    evidence = {
        "deliverable": str(target),
        "kind": kind,
        "verdict": "confirmed" if passed else "needs-fix",
        "mechanical_pass": passed,
        "mechanical_only": True,  # a semantic verifier agent must still probe editorial quality
        "checks": checks,
        "probed_metadata": {"duration_seconds": duration, "width": width, "height": height, "has_audio": has_audio},
        "adversarial_classes_to_probe": list(ADVERSARIAL_CLASSES),
    }
    out = proj.root / "evidence" / f"{target.stem}.verify.json"
    _write_json(out, evidence)
    _ledger(proj, "verify", {"deliverable": str(target), "verdict": evidence["verdict"], "evidence": str(out)})
    return {"tool": "verify", "deliverable": str(target), "verdict": evidence["verdict"],
            "mechanical_pass": passed, "evidence": str(out),
            "checks_passed": sum(1 for c in checks if c["pass"]),
            "checks_total": len(checks),
            "failed_checks": [c["check"] for c in checks if not c["pass"]],
            "failed_details": [c for c in checks if not c["pass"]]}


def _srt_validity(srt_path: Path) -> tuple[bool, Any]:
    if not srt_path.exists():
        return False, {"reason": "srt missing", "path": str(srt_path)}
    text = srt_path.read_text(encoding="utf-8", errors="replace")
    time_re = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})")
    times = time_re.findall(text)
    if not times:
        return False, {"reason": "no cues parsed"}

    def to_s(h: str, m: str, s: str, ms: str) -> float:
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    # cue text = the lines between a timing line and the next blank line
    empty_text = 0
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        ti = next((i for i, ln in enumerate(lines) if time_re.search(ln)), None)
        if ti is not None and not any(ln.strip() for ln in lines[ti + 1:]):
            empty_text += 1

    prev_start = -1.0
    prev_end = -1.0
    bad = []
    max_end = 0.0
    for i, t in enumerate(times):
        start = to_s(*t[:4])
        end = to_s(*t[4:])
        max_end = max(max_end, end)
        if end <= start:
            bad.append({"cue": i + 1, "issue": "zero/negative duration"})
        if start < prev_end - 0.001:
            bad.append({"cue": i + 1, "issue": "overlaps previous"})
        if start < prev_start - 0.001:
            bad.append({"cue": i + 1, "issue": "out of order"})
        prev_start = start
        prev_end = end
    if empty_text:
        bad.append({"issue": "empty cue text", "count": empty_text})
    return (not bad), {"cue_count": len(times), "issues": bad[:10],
                       "empty_text_cues": empty_text, "max_end": round(max_end, 3)}


def _mean_volume_db(path: Path) -> float | None:
    """Mean audio volume in dBFS via ffmpeg volumedetect (None if unavailable)."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        text=True, capture_output=True, check=False,
    )
    m = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", proc.stderr)
    return float(m.group(1)) if m else None


def _frame_luma_at(path: Path, ss: float) -> float | None:
    """Mean brightness (0-255) of the frame at ``ss`` seconds.

    Extract the frame to a tiny PNG and average it with Pillow (build-independent;
    this ffmpeg lacks a reliable signalstats metadata print). None if extraction
    fails, in which case the caller treats the check as inconclusive (not a fail).
    Used pairwise (end vs midpoint) to tell a black TAIL from uniformly dark
    content like a dark presentation slide.
    """
    import tempfile

    ss = max(0.0, ss)
    tmp = Path(tempfile.gettempdir()) / f"_ocluma_{abs(hash((str(path), ss))) % 10_000_000}.png"
    proc = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{ss:.3f}",
         "-i", str(path), "-frames:v", "1", "-vf", "scale=64:-1", str(tmp)],
        text=True, capture_output=True, check=False,
    )
    if proc.returncode != 0 or not tmp.exists():
        return None
    try:
        from PIL import Image, ImageStat

        stat = ImageStat.Stat(Image.open(tmp).convert("L"))
        return float(stat.mean[0])
    except Exception:  # noqa: BLE001
        return None
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def _steer_locked(proj: "Project") -> Iterator[None]:
    """Advisory lock around steering read-modify-write — parallel workers
    steering at once must not collide ids or lose a resolve."""
    proj.ensure()
    lock = proj.root / ".steering.lock"
    fh = lock.open("w")
    try:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass  # best-effort on platforms without flock
        yield
    finally:
        fh.close()


def steer(project: str, note: str, scope: str = "global",
          stage: str | None = None, status_value: str = "open") -> dict[str, Any]:
    """Record a human steering directive that the next wave of subagents must honor.

    The human is the director. Between (or during) waves they drop notes here —
    "cut the intro harder", "keep short #3 vertical-safe", "use the press-kit
    logo, not the generated one" — and every worker reads open directives for its
    scope before acting. ``scope`` can be ``global``, a stage name, a section like
    ``section:0-300``, or a deliverable id like ``short_002``.
    """
    proj = Project(Path(project).expanduser().resolve())
    with _steer_locked(proj):
        directives = _load_steering(proj)
        entry = {
            "id": f"steer_{len(directives) + 1:04d}",
            "scope": scope,
            "stage": stage,
            "note": note,
            "status": status_value,
        }
        with (proj.root / "steering.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _ledger(proj, "steer", {"id": entry["id"], "scope": scope, "note": note})
    return {"tool": "steer", "id": entry["id"], "scope": scope, "open_directives": len(_open_steering(proj))}


def steer_resolve(project: str, directive_id: str) -> dict[str, Any]:
    """Mark a steering directive as addressed so workers stop applying it."""
    proj = Project(Path(project).expanduser().resolve())
    path = proj.root / "steering.jsonl"
    with _steer_locked(proj):
        directives = _load_steering(proj)
        found = False
        for d in directives:
            if d.get("id") == directive_id:
                d["status"] = "resolved"
                found = True
        path.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in directives), encoding="utf-8")
    _ledger(proj, "steer_resolve", {"id": directive_id, "found": found})
    return {"tool": "steer-resolve", "id": directive_id, "resolved": found, "open_directives": len(_open_steering(proj))}


def _load_steering(proj: "Project") -> list[dict[str, Any]]:
    path = proj.root / "steering.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _open_steering(proj: "Project") -> list[dict[str, Any]]:
    return [d for d in _load_steering(proj) if d.get("status") == "open"]


def status(project: str) -> dict[str, Any]:
    """Resumability + steering view: stage flags, recent ledger events, and any
    pending human steering directives the next wave must honor."""
    proj = Project(Path(project).expanduser().resolve())
    data = proj.load()
    events: list[dict[str, Any]] = []
    ledger = proj.root / "ledger.jsonl"
    if ledger.exists():
        events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    open_directives = _open_steering(proj)
    return {
        "tool": "status",
        "project": str(proj.root),
        "stages": data.get("stages", {}),
        "chunk_count": len(data.get("chunks", [])),
        "ledger_events": len(events),
        "recent_events": events[-12:],
        "completed_renders": len(_done_outputs(proj)),
        "open_steering": open_directives,
        "open_steering_count": len(open_directives),
    }


def resume(project: str) -> dict[str, Any]:
    """Real resumption view: which render outputs are already done (and will be
    SKIPPED on a re-run) vs. STT chunks still missing a transcript. A re-run of the
    same flow re-does only what's missing; `--force` overrides per render."""
    proj = Project(Path(project).expanduser().resolve())
    data = proj.load()
    done = _done_outputs(proj)
    chunks = data.get("chunks", [])
    stt_missing = [
        c["index"] for c in chunks
        if not (proj.transcripts_dir / f"chunk_{int(c['index']):03d}.segments.json").exists()
    ]
    return {
        "tool": "resume",
        "project": str(proj.root),
        "stages": data.get("stages", {}),
        "completed_renders": [{"key": k, "output": v} for k, v in done.items()],
        "completed_render_count": len(done),
        "stt_chunks_total": len(chunks),
        "stt_chunks_missing": stt_missing,
        "transcript_ready": (proj.root / "transcript.json").exists(),
        "note": "Re-running the same flow skips completed renders; pass --force to a render to redo it.",
    }


def _mock_chunk_segments(start: float, end: float, chunk: int) -> list[dict[str, Any]]:
    segments = []
    t = start
    i = 0
    while t < end:
        seg_end = min(t + 5.0, end)
        segments.append(
            {"start": round(t, 3), "end": round(seg_end, 3),
             "text": f"[mock chunk {chunk} segment {i}] placeholder transcript line."}
        )
        t = seg_end
        i += 1
    return segments


def _clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _cues_from_words(words: list[dict[str, Any]], start: float, end: float, off: float,
                     max_sec: float = 2.2, max_chars: int = 18, gap: float = 0.45) -> list[tuple[float, float, str]]:
    """Group word-level timestamps into short, speech-synced cues.

    Flush the current group when it would run too long, get too wide, or a natural
    pause (silence gap) to the next word appears — so captions track the voice.
    """
    def _mostly_inside(w: dict[str, Any]) -> bool:
        # a word that barely grazes the range boundary (float dust / next
        # sentence's first word at exactly `end`) must not leak into a cue
        overlap = min(end, w["end"]) - max(start, w["start"])
        dur = max(1e-6, w["end"] - w["start"])
        return overlap >= min(0.1, dur) or overlap / dur >= 0.5

    ws = [w for w in words
          if w["end"] > start and w["start"] < end and str(w.get("word", "")).strip()
          and _mostly_inside(w)]
    ws.sort(key=lambda w: w["start"])

    def join(group: list[dict[str, Any]]) -> str:
        # Whisper drops spaces between Korean word tokens; rejoin on whitespace.
        return " ".join(str(x["word"]).strip() for x in group).strip()

    groups: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for w in ws:
        if cur:
            dur = cur[-1]["end"] - cur[0]["start"]
            nextgap = w["start"] - cur[-1]["end"]
            if dur >= max_sec or len(join(cur)) >= max_chars or nextgap > gap:
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    cues = []
    for g in groups:
        cs = max(g[0]["start"], start) - off
        ce = min(g[-1]["end"], end) - off
        text = join(g)
        if text and ce > cs:
            cues.append((cs, ce, text))
    return cues


def _render_srt(cues: list[tuple[float, float, str]]) -> str:
    out = []
    for i, (start, end, text) in enumerate(cues, start=1):
        if end <= start:
            end = start + 0.5
        out.append(str(i))
        out.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        out.append(text.strip())
        out.append("")
    return "\n".join(out) + "\n"


def _srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _translate(texts: list[str], lang: str, model: str, mock: bool) -> list[str]:
    """Translate subtitle texts. A parse failure retries once with a repair
    prompt, then raises — silently returning the source texts would ship an
    'translated' SRT full of untranslated lines (misleading_success)."""
    if mock:
        return [f"[{lang}] {t}" for t in texts]
    _require_openai_key(f"subtitle translation to {lang}")
    from openai import OpenAI

    client = OpenAI(timeout=120.0)
    payload = json.dumps([{"i": i, "t": t} for i, t in enumerate(texts)], ensure_ascii=False)

    def ask(content: str, system: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            temperature=0,
        )
        raw = resp.choices[0].message.content or "[]"
        return re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()

    system = (f"Translate each item's text to {lang} for subtitles. Return only a JSON array "
              "of objects {i, t} preserving i. No commentary.")
    raw = ask(payload, system)
    for attempt in range(2):
        try:
            parsed = json.loads(raw)
            by_i = {int(o["i"]): str(o["t"]) for o in parsed if "i" in o and "t" in o}
            missing = [i for i in range(len(texts)) if i not in by_i]
            if missing:
                raise ValueError(f"missing indexes {missing[:5]}")
            return [by_i[i] for i in range(len(texts))]
        except Exception as exc:  # noqa: BLE001
            if attempt == 1:
                raise ValueError(f"translation to {lang} failed after repair retry: {exc}") from exc
            repair = (f"Return ONLY a valid JSON array of objects {{i, t}} translating every item to {lang}. "
                      "No markdown, no commentary, no trailing commas.")
            raw = ask(payload, repair)
    raise AssertionError("unreachable")
