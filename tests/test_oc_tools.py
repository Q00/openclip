"""Self-contained tests for the oc tool layer.

Generates a tiny synthetic clip with ffmpeg (no demo.mp4 / no network), then
exercises the composable tools end to end in mock mode.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from openclip.harness import tools

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


def _make_clip(path: Path, seconds: int = 12) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=30:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )


def test_full_chain(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=12)
    project = str(tmp_path / "proj")

    ing = tools.ingest(project, str(src))
    assert ing["chunk_count"] >= 1

    st = tools.stt(project, 0, mock=True)
    assert st["segment_count"] > 0

    merged = tools.transcript_merge(project)
    assert merged["segment_count"] > 0

    sub = tools.subtitle(project, start=2, end=8, mock=True, translate_to="ko")
    assert sub["cue_count"] > 0
    assert Path(sub["output"]).exists()

    clip_out = tmp_path / "clip.mp4"
    c = tools.clip(project, str(src), 2, 8, aspect="9:16", out=str(clip_out))
    assert Path(c["output"]).exists()

    v = tools.verify(project, c["output"], kind="short", expect_duration=6, expect_aspect="9:16")
    assert v["verdict"] == "confirmed", v["failed_checks"]


def test_cut_and_concat(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=20)
    project = str(tmp_path / "proj")

    edl = tmp_path / "edl.json"
    edl.write_text('{"keep":[{"start":1,"end":5},{"start":10,"end":14}]}', encoding="utf-8")
    out = tmp_path / "cut.mp4"
    res = tools.cut(project, str(src), str(edl), str(out))
    assert res["keep_ranges"] == 2
    assert 7.0 < res["output_duration_seconds"] < 9.5  # ~8s kept

    joined = tmp_path / "joined.mp4"
    cc = tools.concat(project, [str(out), str(out)], str(joined))
    assert Path(cc["output"]).exists()


def test_thumbnail_frame_and_title(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=12)
    project = str(tmp_path / "proj")
    out = tmp_path / "thumb.png"
    r = tools.thumbnail(project, str(src), 2, 8, out=str(out), aspect="16:9", title="테스트 후킹 라인")
    assert r["resolution"] == "1280x720"
    from PIL import Image

    assert Image.open(r["output"]).size == (1280, 720)


def test_thumbnail_generate_mock(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=8)
    project = str(tmp_path / "proj")
    out = tmp_path / "gen.png"
    r = tools.thumbnail(project, str(src), 1, 6, out=str(out), aspect="9:16",
                        title="x", generate=True, mock=True)
    assert r["method"] == "generate"
    from PIL import Image

    assert Image.open(r["output"]).size == (1080, 1920)


def test_cut_accepts_pair_edl(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=20)
    project = str(tmp_path / "proj")
    edl = tmp_path / "edl.json"
    edl.write_text('{"keep":[[1,5],[10,14]]}', encoding="utf-8")  # pair form
    out = tmp_path / "cut.mp4"
    res = tools.cut(project, str(src), str(edl), str(out))
    assert res["keep_ranges"] == 2


def test_ingest_start_offset(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=12)
    project = str(tmp_path / "proj")
    r = tools.ingest(project, str(src), max_seconds=6, start=3)
    assert r["window"]["start_seconds"] == 3
    assert r["chunks"][0]["start_seconds"] == 3.0


def test_toolbox_author_reuse(tmp_path: Path, monkeypatch) -> None:
    from openclip.harness import toolbox

    # isolate the toolbox at a temp repo root (has pyproject marker)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "echo_tool.py"
    script.write_text(
        "import argparse,json\n"
        "a=argparse.ArgumentParser();a.add_argument('--msg',default='hi');x=a.parse_args()\n"
        "print(json.dumps({'said':x.msg}))\n",
        encoding="utf-8",
    )
    reg = toolbox.toolbox_new("echo-tool", "echoes a message", str(script), lang="python",
                              selftest="--msg ok", created_by="test")
    assert reg["registered"] == "echo-tool"
    assert reg["selftest"]["returncode"] == 0

    assert toolbox.toolbox_list("echo")["count"] == 1
    run = toolbox.toolbox_run("echo-tool", ["--msg", "reuse"])
    assert run["returncode"] == 0 and "reuse" in run["stdout"]
    # invocation counter persisted
    assert toolbox.toolbox_list("echo")["tools"][0]["invocations"] == 1


def test_toolbox_selftest_gate(tmp_path: Path, monkeypatch) -> None:
    from openclip.harness import toolbox

    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.py"
    bad.write_text("import sys; sys.exit(3)\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        toolbox.toolbox_new("bad-tool", "always fails", str(bad), lang="python", selftest="")
    # a failed self-test must NOT register the tool
    assert toolbox.toolbox_list()["count"] == 0


def test_verify_catches_drift(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=6)
    project = str(tmp_path / "proj")
    v = tools.verify(project, str(src), kind="clip", expect_duration=99)
    assert v["verdict"] == "needs-fix"
    assert "duration_within_tolerance" in v["failed_checks"]


def test_verify_catches_black_and_silent(tmp_path: Path) -> None:
    src = tmp_path / "black.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=black:s=320x240:d=2",
         "-f", "lavfi", "-i", "anullsrc", "-t", "2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)],
        check=True,
    )
    v = tools.verify(str(tmp_path / "proj"), str(src), kind="clip")
    assert v["verdict"] == "needs-fix"
    assert "audio_not_silent" in v["failed_checks"]
    assert "last_frame_not_black" in v["failed_checks"]


def test_toolbox_promote_gate(tmp_path: Path, monkeypatch) -> None:
    from openclip.harness import toolbox

    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    good = tmp_path / "good.py"
    good.write_text("import argparse,json;print(json.dumps({'ok':True}))\n", encoding="utf-8")
    toolbox.toolbox_new("good-tool", "safe", str(good), lang="python", selftest="", created_by="t")

    # promote without review is blocked (human gate)
    r = toolbox.toolbox_promote("good-tool", reviewed=False)
    assert r["promoted"] is False

    # a dangerous tool is caught by the static scan even WITH review
    evil = tmp_path / "evil.py"
    evil.write_text("import os; os.system('echo x')\n", encoding="utf-8")
    toolbox.toolbox_new("evil-tool", "bad", str(evil), lang="python", created_by="t")
    r = toolbox.toolbox_promote("evil-tool", reviewed=True)
    assert r["promoted"] is False and "os.system" in r["gate"]["danger_hits"]

    # safe tool + review promotes to shared and writes a learning
    r = toolbox.toolbox_promote("good-tool", reviewed=True, promoted_by="tester")
    assert r["promoted"] is True and r["tier"] == "shared"
    assert toolbox.toolbox_learnings()["count"] == 1


def test_ledger_resume_skips_and_force_reruns(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=12)
    project = str(tmp_path / "proj")
    out = tmp_path / "clip.mp4"

    first = tools.clip(project, str(src), 2, 8, aspect="9:16", out=str(out))
    assert first["resumed"] is False
    second = tools.clip(project, str(src), 2, 8, aspect="9:16", out=str(out))
    assert second["resumed"] is True  # ledger-based resume: skipped
    forced = tools.clip(project, str(src), 2, 8, aspect="9:16", out=str(out), force=True)
    assert forced["resumed"] is False

    r = tools.resume(project)
    assert r["completed_render_count"] >= 1


def test_ingest_measures_chunk_starts(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=8)
    project = str(tmp_path / "proj")
    r = tools.ingest(project, str(src), max_seconds=8)
    # measured_duration recorded; start_seconds is cumulative (not index*300 guess)
    assert all("measured_duration" in c for c in r["chunks"])


def test_acp_handshake() -> None:
    import io

    from openclip.harness import acp

    inp = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
        '{"jsonrpc":"2.0","id":2,"method":"session/new","params":{"project":"out/acp_unit"}}\n'
    )
    out = io.StringIO()
    acp.AcpServer(inp, out).serve()
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0]["result"]["agent"]["name"] == "openclip"
    assert lines[1]["result"]["sessionId"] == "sess_1"


def test_cut_merges_overlaps_and_clamps(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=12)
    project = str(tmp_path / "proj")
    edl = tmp_path / "edl.json"
    # overlapping spans + span running past the 12s source
    edl.write_text('{"keep":[{"start":1,"end":5},{"start":4,"end":7},{"start":10,"end":99}]}',
                   encoding="utf-8")
    out = tmp_path / "cut.mp4"
    res = tools.cut(project, str(src), str(edl), str(out))
    assert res["keep_ranges"] == 2  # 1-7 merged, 10-12 clamped
    assert 7.0 < res["output_duration_seconds"] < 9.5


def test_cut_vertical_aspect(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=8)
    project = str(tmp_path / "proj")
    edl = tmp_path / "edl.json"
    edl.write_text('{"keep":[{"start":1,"end":5}]}', encoding="utf-8")
    out = tmp_path / "cut_vertical.mp4"
    res = tools.cut(project, str(src), str(edl), str(out), aspect="9:16")
    assert res["aspect"] == "9:16"
    probe = tools.ffprobe(Path(res["output"]))
    video = next(s for s in probe["streams"] if s.get("codec_type") == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    with pytest.raises(ValueError):
        tools.cut(project, str(src), str(edl), str(out), aspect="4:3")


def test_clip_validates_range(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=8)
    project = str(tmp_path / "proj")
    with pytest.raises(ValueError):
        tools.clip(project, str(src), 5, 5, out=str(tmp_path / "a.mp4"))
    with pytest.raises(ValueError):
        tools.clip(project, str(src), 99, 120, out=str(tmp_path / "b.mp4"))
    # end past the source is clamped, not an error
    r = tools.clip(project, str(src), 6, 120, out=str(tmp_path / "c.mp4"))
    assert r["end_seconds"] <= 8.5
    # default ids for same-start different-end clips do not collide
    r1 = tools.clip(project, str(src), 1, 4)
    r2 = tools.clip(project, str(src), 1, 6)
    assert r1["id"] != r2["id"]


def test_subtitle_empty_range_is_an_error(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=12)
    project = str(tmp_path / "proj")
    tools.ingest(project, str(src))
    tools.stt(project, 0, mock=True)
    tools.transcript_merge(project)
    with pytest.raises(ValueError, match="no transcript content"):
        tools.subtitle(project, start=500, end=600, mock=True)


def test_proxy_resumes(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=6)
    project = str(tmp_path / "proj")
    first = tools.proxy(project, str(src), scale=240)
    assert first["resumed"] is False
    second = tools.proxy(project, str(src), scale=240)
    assert second["resumed"] is True
    forced = tools.proxy(project, str(src), scale=240, force=True)
    assert forced["resumed"] is False


def test_thumbnail_resumes(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=8)
    project = str(tmp_path / "proj")
    out = tmp_path / "t.png"
    first = tools.thumbnail(project, str(src), 1, 5, out=str(out), title="한 줄 제목")
    assert first["resumed"] is False
    second = tools.thumbnail(project, str(src), 1, 5, out=str(out), title="한 줄 제목")
    assert second["resumed"] is True
    forced = tools.thumbnail(project, str(src), 1, 5, out=str(out), title="한 줄 제목", force=True)
    assert forced["resumed"] is False


def test_probe_records_stage_and_ledger(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=6)
    project = tmp_path / "proj"
    r = tools.probe(str(project), str(src))
    assert Path(r["output"]).exists()
    manifest = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert manifest["stages"]["probe"] == "done"
    ledger = (project / "ledger.jsonl").read_text(encoding="utf-8")
    assert '"event": "probe"' in ledger


def test_transcript_merge_reports_missing_chunks(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=12)
    project = str(tmp_path / "proj")
    ing = tools.ingest(project, str(src))
    assert ing["chunk_count"] == 1
    # fake a second ingested chunk that was never transcribed
    proj = tools.Project(Path(project))
    data = proj.load()
    data["chunks"].append({"index": 1, "path": "x", "start_seconds": 300, "end_seconds": 310})
    proj.save(data)
    tools.stt(project, 0, mock=True)
    merged = tools.transcript_merge(project)
    assert merged["missing_chunks"] == [1]
    assert merged["complete"] is False
    assert proj.load()["stages"]["transcript"] == "partial"


def test_stt_without_key_fails_actionably(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src.mp4"
    _make_clip(src, seconds=6)
    project = str(tmp_path / "proj")
    tools.ingest(project, str(src))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        tools.stt(project, 0, mock=False)
