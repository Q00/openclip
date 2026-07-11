"""Tests for scripts/sync_agents.py — the canonical-source -> mirror sync.

The repo-level check doubles as CI enforcement: if someone edits agents/*.md or
skills/oc/* without regenerating .claude/ and .agents/, this test fails.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
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


def test_npx_skills_catalog_uses_real_directories() -> None:
    """GitHub clones do not reliably traverse catalog directory symlinks."""
    mod = _load_module()
    expected = {"oc"}
    expected.update(mod._role_name(path) for path in (ROOT / "agents").glob("*.md"))
    catalog_dirs = {path.name: path for path in (ROOT / "skills").glob("oc*")}

    assert set(catalog_dirs) == expected
    assert len(catalog_dirs) == 14
    for name, path in catalog_dirs.items():
        assert not path.is_symlink(), f"{name} must be a real directory for npx skills discovery"
        assert (path / "SKILL.md").is_file()

    assert (catalog_dirs["oc"] / "tools-reference.md").is_file()
    assert {path.name for path in (catalog_dirs["oc"] / "flows").glob("*.yaml")} == {
        path.name for path in (ROOT / "flows").glob("*.yaml")
    }

    lock = json.loads((ROOT / "skills-lock.json").read_text(encoding="utf-8"))
    assert set(lock["skills"]) == expected
    for name, path in catalog_dirs.items():
        digest = hashlib.sha256()
        files = sorted(
            (file for file in path.rglob("*") if file.is_file()),
            key=lambda file: file.relative_to(path).as_posix(),
        )
        for file in files:
            digest.update(file.relative_to(path).as_posix().encode())
            digest.update(file.read_bytes())
        assert lock["skills"][name]["computedHash"] == digest.hexdigest()


def test_sync_roundtrip_on_temp_tree(tmp_path: Path, monkeypatch, capsys) -> None:
    mod = _load_module()
    agents = tmp_path / "agents"
    skill = tmp_path / "skills" / "oc"
    flows = tmp_path / "flows"
    toolbox = tmp_path / "toolbox"
    agents.mkdir(parents=True)
    skill.mkdir(parents=True)
    flows.mkdir(parents=True)
    toolbox.mkdir(parents=True)
    (agents / "worker.md").write_text("---\nname: oc-test-worker\n---\nbody\n", encoding="utf-8")
    (skill / "SKILL.md").write_text("---\nname: oc\n---\nskill\n", encoding="utf-8")
    (flows / "flow1.yaml").write_text("name: flow1\n", encoding="utf-8")
    (toolbox / "registry.json").write_text('{"schema":"oc-toolbox-v2","tools":[]}\n', encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "AGENTS_SRC", agents)
    monkeypatch.setattr(mod, "SKILL_SRC", skill)
    monkeypatch.setattr(mod, "FLOWS_SRC", flows)
    monkeypatch.setattr(mod, "SHARED_TOOLBOX_SRC", toolbox)
    monkeypatch.setattr(mod, "SKILLS_CATALOG", tmp_path / "skills")
    monkeypatch.setattr(mod, "CLAUDE_AGENTS", tmp_path / ".claude" / "agents")
    monkeypatch.setattr(mod, "CLAUDE_SKILL", tmp_path / ".claude" / "skills" / "oc")
    monkeypatch.setattr(mod, "CODEX_SKILLS", tmp_path / ".agents" / "skills")
    monkeypatch.setattr(mod, "PYTHON_SHARED_TOOLBOX", tmp_path / "src" / "openclip" / "_shared_toolbox")

    # fresh tree is stale, sync writes it, then check passes
    assert mod.sync(check=True) == 1
    assert mod.sync(check=False) == 0
    assert (tmp_path / ".claude" / "agents" / "worker.md").exists()
    assert (tmp_path / ".agents" / "skills" / "oc-test-worker" / "SKILL.md").exists()
    # npx-skills catalog: worker skill + flows bundled inside the oc skill
    assert (tmp_path / "skills" / "oc-test-worker" / "SKILL.md").exists()
    assert (tmp_path / "skills" / "oc" / "flows" / "flow1.yaml").exists()
    assert (tmp_path / ".claude" / "skills" / "oc" / "flows" / "flow1.yaml").exists()
    assert mod.sync(check=True) == 0

    # deleting a source prunes its generated mirrors (orphan cleanup)
    (agents / "worker.md").unlink()
    assert mod.sync(check=False) == 0
    assert not (tmp_path / ".agents" / "skills" / "oc-test-worker" / "SKILL.md").exists()
    assert not (tmp_path / "skills" / "oc-test-worker").exists()
