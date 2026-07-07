"""Tests for the SubagentStop evidence gate (hooks/verify_evidence_hook.py).

The hook is run exactly as the runtime runs it: a subprocess fed JSON on stdin.
A block decision is a JSON line on stdout; an allow is empty output + exit 0.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "verify_evidence_hook.py"


def run_hook(payload: dict) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout.strip()


def _ids() -> dict:
    return {"session_id": f"s-{uuid.uuid4().hex[:8]}", "agent_id": f"a-{uuid.uuid4().hex[:8]}"}


def test_non_enforced_agent_is_allowed() -> None:
    code, out = run_hook({"agent_type": "oc-stt-worker", "last_assistant_message": "done", **_ids()})
    assert code == 0 and json.loads(out) == {"continue": True}


def test_enforced_agent_without_evidence_is_blocked() -> None:
    code, out = run_hook({"agent_type": "oc-assembler", "last_assistant_message": "all done!", **_ids()})
    assert code == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "EVIDENCE_RECORDED" in decision["reason"]


def test_enforced_agent_with_real_evidence_is_allowed(tmp_path: Path) -> None:
    ev = tmp_path / "clip.verify.json"
    ev.write_text('{"verdict":"confirmed"}', encoding="utf-8")
    code, out = run_hook({
        "agent_type": "oc-verifier",
        "last_assistant_message": f"verified. EVIDENCE_RECORDED: {ev}",
        **_ids(),
    })
    assert code == 0 and json.loads(out) == {"continue": True}


def test_evidence_pointing_at_missing_file_is_blocked(tmp_path: Path) -> None:
    code, out = run_hook({
        "agent_type": "oc-verifier",
        "last_assistant_message": f"EVIDENCE_RECORDED: {tmp_path}/nope.json",
        **_ids(),
    })
    assert json.loads(out)["decision"] == "block"


def test_relative_evidence_resolves_against_cwd(tmp_path: Path) -> None:
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "x.json").write_text("{}", encoding="utf-8")
    code, out = run_hook({
        "agent_type": "oc-thumbnail-artist",
        "last_assistant_message": "EVIDENCE_RECORDED: evidence/x.json",
        "cwd": str(tmp_path),
        **_ids(),
    })
    assert code == 0 and json.loads(out) == {"continue": True}


def test_gives_up_after_max_attempts() -> None:
    ids = _ids()
    payload = {"agent_type": "oc-cut-judge", "last_assistant_message": "done", **ids}
    for _ in range(3):
        code, out = run_hook(payload)
        assert json.loads(out)["decision"] == "block"
    code, out = run_hook(payload)  # 4th: surface to the human instead of hard-locking
    assert code == 0 and json.loads(out) == {"continue": True}


def test_malformed_stdin_never_breaks_the_session() -> None:
    proc = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True,
                          capture_output=True, timeout=30)
    assert proc.returncode == 0
    # Codex requires JSON on stdout for exit 0 — even the defensive path emits it
    assert json.loads(proc.stdout) == {"continue": True}


def test_thumbnail_designer_is_gated(tmp_path: Path) -> None:
    """The designer produces file deliverables — it must not slip the gate."""
    code, out = run_hook({"agent_type": "oc-thumbnail-designer",
                          "last_assistant_message": "thumbnail ready!", **_ids()})
    assert code == 0 and json.loads(out)["decision"] == "block"
    ev = tmp_path / "thumb.png"
    ev.write_bytes(b"png")
    code, out = run_hook({"agent_type": "oc-thumbnail-designer",
                          "last_assistant_message": f"EVIDENCE_RECORDED: {ev}", **_ids()})
    assert code == 0 and json.loads(out) == {"continue": True}


def test_enforced_list_covers_every_evidence_contract() -> None:
    """Drift guard: any agent whose contract demands EVIDENCE_RECORDED must be
    matched by the hook's ENFORCED regex — on BOTH runtimes (same script)."""
    import re

    enforced = re.search(r'ENFORCED = re\.compile\(\s*r"([^"]+)"', HOOK.read_text(encoding="utf-8"))
    assert enforced, "ENFORCED regex not found in hook"
    pattern = re.compile(enforced.group(1))
    agents_dir = HOOK.parent.parent / "agents"
    missing = []
    for md in sorted(agents_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        if "EVIDENCE_RECORDED" not in text:
            continue
        role = next((line.split("name:", 1)[1].strip() for line in text.splitlines()
                     if line.strip().startswith("name:")), md.stem)
        if not pattern.search(role):
            missing.append(role)
    assert not missing, f"agents demanding evidence but not gated by the hook: {missing}"


def test_both_runtimes_wire_the_same_hook() -> None:
    """Claude (.claude/settings.json) and Codex (.codex/hooks.json) must both
    run hooks/verify_evidence_hook.py on SubagentStop."""
    root = HOOK.parent.parent
    for wiring in (root / ".claude" / "settings.json", root / ".codex" / "hooks.json"):
        data = json.loads(wiring.read_text(encoding="utf-8"))
        entries = data["hooks"]["SubagentStop"]
        commands = [h["command"] for e in entries for h in e["hooks"]]
        assert any("verify_evidence_hook.py" in c for c in commands), wiring
    toml = (root / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "hooks = true" in toml  # Codex only loads hooks.json with the feature on
