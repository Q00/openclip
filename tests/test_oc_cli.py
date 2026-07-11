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
    a = p.parse_args(["--project", "x", "toolbox", "propose", "--name", "t", "--target", "builtin"])
    assert a.target == "builtin"
    a = p.parse_args(["domain-pack", "export", "--out", "pack", "--force"])
    assert a.force is True


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
    assert "agent_gate_ready" in payload
    assert payload["contractplane_pack_ready"] is True


def test_domain_pack_show_and_export_do_not_require_project(tmp_path: Path, capsys) -> None:
    rc = main(["domain-pack", "show"])
    assert rc == 0
    shown = json.loads(capsys.readouterr().out.strip())
    assert shown["domain"] == "openclip"
    assert shown["integrity_ok"] is True
    assert shown["runtime_dependency_required"] is False
    assert len(shown["role_contracts"]) == 13

    out = tmp_path / "pack"
    rc = main(["domain-pack", "export", "--out", str(out)])
    assert rc == 0
    exported = json.loads(capsys.readouterr().out.strip())
    assert exported["out"] == str(out.resolve())
    assert exported["forced"] is False
    assert (out / "openclip.domain.yaml").is_file()
    assert (out / "compiled" / "shorts.plan.json").is_file()
    assert (out / "roles" / "oc-orchestrator.md").is_file()

    rc = main(["domain-pack", "export", "--out", str(out)])
    assert rc == 2
    refused = json.loads(capsys.readouterr().out.strip())
    assert refused["type"] == "FileExistsError"

    rc = main(["domain-pack", "export", "--out", str(out), "--force"])
    assert rc == 0
    forced = json.loads(capsys.readouterr().out.strip())
    assert forced["forced"] is True


def test_toolbox_run_failure_exits_nonzero(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "conditional.py"
    script.write_text(
        "import argparse,json,sys\n"
        "a=argparse.ArgumentParser();a.add_argument('--fail',action='store_true');x=a.parse_args()\n"
        "print(json.dumps({'ok':not x.fail}));sys.exit(7 if x.fail else 0)\n",
        encoding="utf-8",
    )
    project = str(tmp_path / "project")
    assert main(["--project", project, "toolbox", "new", "--name", "conditional-tool",
                 "--desc", "fails on demand", "--file", str(script), "--selftest", ""]) == 0
    capsys.readouterr()
    assert main(["--project", project, "toolbox", "run", "--name", "conditional-tool", "--", "--fail"]) == 2
    result = json.loads(capsys.readouterr().out.strip())
    assert result["script_returncode"] == 7
    assert result["returncode"] == 7


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
