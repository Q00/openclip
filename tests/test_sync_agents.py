"""Tests for scripts/sync_agents.py — the canonical-source -> mirror sync.

The repo-level check doubles as CI enforcement: if someone edits agents/*.md or
skills/oc/* without regenerating .claude/ and .agents/, this test fails.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_agents", ROOT / "scripts" / "sync_agents.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sync_agents"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_repo_mirrors_are_in_sync() -> None:
    mod = _load_module()
    assert mod.sync(check=True) == 0, (
        "mirrors are stale — run `python3 scripts/sync_agents.py` after editing "
        "agents/*.md or skills/oc/*"
    )


def test_sync_roundtrip_on_temp_tree(tmp_path: Path, monkeypatch, capsys) -> None:
    mod = _load_module()
    agents = tmp_path / "agents"
    skill = tmp_path / "skills" / "oc"
    agents.mkdir(parents=True)
    skill.mkdir(parents=True)
    (agents / "worker.md").write_text("---\nname: oc-test-worker\n---\nbody\n", encoding="utf-8")
    (skill / "SKILL.md").write_text("---\nname: oc\n---\nskill\n", encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "AGENTS_SRC", agents)
    monkeypatch.setattr(mod, "SKILL_SRC", skill)
    monkeypatch.setattr(mod, "CLAUDE_AGENTS", tmp_path / ".claude" / "agents")
    monkeypatch.setattr(mod, "CLAUDE_SKILL", tmp_path / ".claude" / "skills" / "oc")
    monkeypatch.setattr(mod, "CODEX_SKILLS", tmp_path / ".agents" / "skills")

    # fresh tree is stale, sync writes it, then check passes
    assert mod.sync(check=True) == 1
    assert mod.sync(check=False) == 0
    assert (tmp_path / ".claude" / "agents" / "worker.md").exists()
    assert (tmp_path / ".agents" / "skills" / "oc-test-worker" / "SKILL.md").exists()
    assert mod.sync(check=True) == 0

    # deleting a source prunes its generated mirror (orphan cleanup)
    (agents / "worker.md").unlink()
    assert mod.sync(check=False) == 0
    assert not (tmp_path / ".agents" / "skills" / "oc-test-worker" / "SKILL.md").exists()
