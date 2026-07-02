#!/usr/bin/env python3
"""Sync canonical agent/skill sources into the Claude and Codex layouts.

Single source of truth -> generated mirrors (avoids the hardlink-divergence trap):

  agents/<role>.md          (canonical worker role)
  skills/oc/*          (canonical orchestrator skill + tool reference)

  =>  .claude/agents/<role>.md            # Claude Code subagents
      .claude/skills/oc/*            # Claude Code skill
      .agents/skills/oc/*            # Codex orchestrator skill
      .agents/skills/oc-<role>/SKILL.md   # Codex worker skills

Run:  python3 scripts/sync_agents.py  [--check]

``--check`` exits non-zero if any mirror is stale (use in CI / pre-commit).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_SRC = ROOT / "agents"
SKILL_SRC = ROOT / "skills" / "oc"

CLAUDE_AGENTS = ROOT / ".claude" / "agents"
CLAUDE_SKILL = ROOT / ".claude" / "skills" / "oc"
CODEX_SKILLS = ROOT / ".agents" / "skills"

BANNER = "<!-- GENERATED from canonical source by scripts/sync_agents.py — edit the source, not this file. -->\n"


def _role_name(md: Path) -> str:
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("name:"):
            return line.split("name:", 1)[1].strip()
    return md.stem


def _planned() -> dict[Path, str]:
    """Map of target path -> desired content."""
    plan: dict[Path, str] = {}

    # 1) Claude subagents: verbatim copies of canonical role files.
    for md in sorted(AGENTS_SRC.glob("*.md")):
        plan[CLAUDE_AGENTS / md.name] = md.read_text(encoding="utf-8")

    # 2) Claude + Codex orchestrator skill: copy the whole skill folder.
    for f in sorted(SKILL_SRC.rglob("*")):
        if f.is_file():
            rel = f.relative_to(SKILL_SRC)
            plan[CLAUDE_SKILL / rel] = f.read_text(encoding="utf-8")
            plan[CODEX_SKILLS / "oc" / rel] = f.read_text(encoding="utf-8")

    # 3) Codex worker skills: one skill folder per canonical role.
    for md in sorted(AGENTS_SRC.glob("*.md")):
        name = _role_name(md)            # e.g. oc-stt-worker
        body = md.read_text(encoding="utf-8")
        plan[CODEX_SKILLS / name / "SKILL.md"] = body

    return plan


def _orphans(plan: dict[Path, str]) -> list[Path]:
    """Generated mirror files that are no longer in the plan (deleted sources)."""
    planned = set(plan)
    found: list[Path] = []
    for root in (CLAUDE_AGENTS, CLAUDE_SKILL, CODEX_SKILLS):
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f not in planned:
                found.append(f)
    return found


def sync(check: bool) -> int:
    plan = _planned()
    stale: list[Path] = []
    for target, content in plan.items():
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current != content:
            stale.append(target)
            if not check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

    orphans = _orphans(plan)
    if not check:
        for o in orphans:
            o.unlink()
            # prune now-empty skill dirs
            parent = o.parent
            if parent != CODEX_SKILLS and not any(parent.iterdir()):
                parent.rmdir()

    if check:
        problems = stale + orphans
        if problems:
            print("STALE mirrors (run scripts/sync_agents.py):")
            for p in problems:
                print(f"  - {p.relative_to(ROOT)}{' (orphan)' if p in orphans else ''}")
            return 1
        print("OK: Claude + Codex mirrors are in sync.")
        return 0

    print(f"Synced {len(plan)} files -> .claude/ + .agents/  ({len(stale)} updated, {len(orphans)} pruned)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync canonical agents/skills into Claude + Codex layouts.")
    ap.add_argument("--check", action="store_true", help="report staleness without writing (CI)")
    args = ap.parse_args()
    return sync(args.check)


if __name__ == "__main__":
    raise SystemExit(main())
