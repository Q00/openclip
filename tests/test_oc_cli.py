"""Smoke tests for the `oc` CLI surface: parsing, dispatch, and the JSON error
contract every subagent depends on (single JSON object on stdout, exit != 0)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from openclip import __version__
from openclip.harness.cli import build_parser, main

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


def _make_clip(path: Path, seconds: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )


def test_parser_accepts_new_flags() -> None:
    p = build_parser()
    a = p.parse_args(["--project", "x", "ingest", "--input", "v.mp4", "--chunk-seconds", "60"])
    assert a.chunk_seconds == 60.0
    a = p.parse_args(["--project", "x", "subtitle", "--start", "0", "--max-chars", "24"])
    assert a.max_chars == 24
    a = p.parse_args(["--project", "x", "cut", "--input", "v", "--edl", "e", "--out", "o",
                      "--aspect", "9:16"])
    assert a.aspect == "9:16"
    a = p.parse_args(["--project", "x", "toolbox", "run", "--name", "t", "--timeout", "30"])
    assert a.timeout == 30


def test_version_does_not_require_project(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"oc {__version__}"


def test_doctor_does_not_require_project(capsys) -> None:
    rc = main(["doctor"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["tool"] == "doctor"
    assert payload["version"] == __version__
    assert payload["mock_ready"] is True
    assert payload["checks"]["ffmpeg"]["ok"] is True
    assert payload["checks"]["ffprobe"]["ok"] is True


def test_error_contract_json_and_exit_code(tmp_path: Path, capsys) -> None:
    rc = main(["--project", str(tmp_path / "p"), "stt", "--chunk", "0", "--mock"])
    assert rc == 2  # chunk not ingested yet
    err = json.loads(capsys.readouterr().out.strip())
    assert "error" in err and err["type"] == "ValueError"


def test_happy_path_prints_single_json(tmp_path: Path, capsys) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src)
    project = str(tmp_path / "proj")
    rc = main(["--project", project, "ingest", "--input", str(src)])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    payload = json.loads(out[0])
    assert payload["tool"] == "ingest" and payload["chunk_count"] >= 1

    rc = main(["--project", project, "status"])
    assert rc == 0
    status = json.loads(capsys.readouterr().out.strip())
    assert status["stages"]["ingest"] == "done"
