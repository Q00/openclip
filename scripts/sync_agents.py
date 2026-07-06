#!/usr/bin/env python3
"""Sync canonical agent/skill sources into every distribution layout.

Single source of truth -> generated mirrors (avoids the hardlink-divergence trap):

  agents/<role>.md               (canonical worker role)
  skills/oc/SKILL.md + tools-reference.md   (canonical orchestrator skill)
  flows/*.yaml                   (canonical flow manifests)

  =>  .claude/agents/<role>.md             # Claude Code subagents (repo/plugin)
      .claude/skills/oc/*                  # Claude Code skill (repo/plugin)
      .agents/skills/oc/*                  # Codex orchestrator skill
      .agents/skills/oc-<role>/SKILL.md    # Codex worker skills
      skills/oc-<role>/SKILL.md            # npx-skills catalog (worker roles)
      skills/oc/flows/*.yaml               # flows bundled INSIDE the skill so an
      .claude/skills/oc/flows/*.yaml       # installed copy works outside the repo
      .agents/skills/oc/flows/*.yaml

The `skills/` directory is the catalog `npx skills add <repo>` discovers, so it
must be complete and self-contained: the orchestrator skill carries the flow
manifests, and every worker role is present as a sibling skill.

Run:  python3 scripts/sync_agents.py  [--check]

``--check`` exits non-zero if any mirror is stale (use in CI / pre-commit).
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_SRC = ROOT / "agents"
SKILL_SRC = ROOT / "skills" / "oc"
FLOWS_SRC = ROOT / "flows"

SKILLS_CATALOG = ROOT / "skills"
CLAUDE_AGENTS = ROOT / ".claude" / "agents"
CLAUDE_SKILL = ROOT / ".claude" / "skills" / "oc"
CODEX_SKILLS = ROOT / ".agents" / "skills"


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

    # 2) Claude + Codex orchestrator skill: copy the canonical skill files
    #    (skills/oc/flows/ is generated below, not canonical — skip it here).
    for f in sorted(SKILL_SRC.rglob("*")):
        if f.is_file() and "flows" not in f.relative_to(SKILL_SRC).parts:
            rel = f.relative_to(SKILL_SRC)
            plan[CLAUDE_SKILL / rel] = f.read_text(encoding="utf-8")
            plan[CODEX_SKILLS / "oc" / rel] = f.read_text(encoding="utf-8")

    # 3) Flow manifests bundled inside every copy of the orchestrator skill —
    #    an installed skill lives outside the repo and cannot read flows/.
    if FLOWS_SRC.exists():
        for fy in sorted(FLOWS_SRC.glob("*.yaml")):
            body = fy.read_text(encoding="utf-8")
            plan[SKILL_SRC / "flows" / fy.name] = body
            plan[CLAUDE_SKILL / "flows" / fy.name] = body
            plan[CODEX_SKILLS / "oc" / "flows" / fy.name] = body

    # 4) Worker skills: one skill folder per canonical role, in BOTH the Codex
    #    layout and the npx-skills catalog.
    for md in sorted(AGENTS_SRC.glob("*.md")):
        name = _role_name(md)            # e.g. oc-stt-worker
        body = md.read_text(encoding="utf-8")
        plan[CODEX_SKILLS / name / "SKILL.md"] = body
        plan[SKILLS_CATALOG / name / "SKILL.md"] = body

    return plan


def _generated_roots(plan: dict[Path, str]) -> list[Path]:
    """Directories whose files are ALL generated (safe to orphan-scan)."""
    roots = [CLAUDE_AGENTS, CLAUDE_SKILL, CODEX_SKILLS, SKILL_SRC / "flows"]
    # skills/oc-* catalog dirs are generated wholesale; skills/oc is canonical
    # (except flows/, covered above) so it is NOT scanned as a whole.
    roots.extend(sorted(p for p in SKILLS_CATALOG.glob("oc-*") if p.is_dir()))
    return roots


def _orphans(plan: dict[Path, str]) -> list[Path]:
    """Generated mirror files that are no longer in the plan (deleted sources)."""
    planned = set(plan)
    found: list[Path] = []
    for root in _generated_roots(plan):
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
            if parent not in (CODEX_SKILLS, SKILLS_CATALOG) and not any(parent.iterdir()):
                parent.rmdir()

    if check:
        problems = stale + orphans
        if problems:
            print("STALE mirrors (run scripts/sync_agents.py):")
            for p in problems:
                print(f"  - {p.relative_to(ROOT)}{' (orphan)' if p in orphans else ''}")
            return 1
        print("OK: skills catalog + Claude + Codex mirrors are in sync.")
        return 0

    print(f"Synced {len(plan)} files -> skills/ + .claude/ + .agents/  ({len(stale)} updated, {len(orphans)} pruned)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync canonical agents/skills into all distribution layouts.")
    ap.add_argument("--check", action="store_true", help="report staleness without writing (CI)")
    args = ap.parse_args()
    return sync(args.check)


if __name__ == "__main__":
    raise SystemExit(main())
