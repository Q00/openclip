#!/usr/bin/env python3
"""Sync canonical agent/skill sources into every distribution layout.

Single source of truth -> generated mirrors (avoids the hardlink-divergence trap):

  agents/<role>.md               (canonical worker role)
  skills/oc/SKILL.md + tools-reference.md   (canonical orchestrator skill)
  flows/*.yaml                   (canonical flow manifests)
  contractplane/*                (canonical ContractPlane Domain Pack + plans)
  agents/*.md -> contractplane/roles/*.md  (generated portable role bundle)
  toolbox/registry.json + shared scripts     (canonical shared learned tools)

  =>  .claude/agents/<role>.md             # Claude Code subagents (repo/plugin)
      .claude/skills/oc/*                  # Claude Code skill (repo/plugin)
      .agents/skills/oc/*                  # Codex orchestrator skill
      .agents/skills/oc-<role>/SKILL.md    # Codex worker skills
      skills/oc-<role>/SKILL.md            # npx-skills catalog (worker roles)
      skills/oc/flows/*.yaml               # flows bundled INSIDE the skill so an
      .claude/skills/oc/flows/*.yaml       # installed copy works outside the repo
      .agents/skills/oc/flows/*.yaml
      */skills/oc/domain-pack/*              # portable Domain Pack for agents
      contractplane/roles/*                  # repo-level portable role bundle
      src/openclip/_domain_pack/*             # wheel-bundled Domain Pack
      src/openclip/_shared_toolbox/*          # wheel-bundled shared tools

The `skills/` directory is the catalog `npx skills add <repo>` discovers, so it
must be complete and self-contained: the orchestrator skill carries the flow
manifests, and every worker role is present as a sibling skill.

Run:  python3 scripts/sync_agents.py  [--check]

``--check`` exits non-zero if any mirror is stale (use in CI / pre-commit).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_SRC = ROOT / "agents"
SKILL_SRC = ROOT / "skills" / "oc"
FLOWS_SRC = ROOT / "flows"
SHARED_TOOLBOX_SRC = ROOT / "toolbox"
CONTRACTPLANE_SRC = ROOT / "contractplane"

SKILLS_CATALOG = ROOT / "skills"
CLAUDE_AGENTS = ROOT / ".claude" / "agents"
CLAUDE_SKILL = ROOT / ".claude" / "skills" / "oc"
CODEX_SKILLS = ROOT / ".agents" / "skills"
PYTHON_SHARED_TOOLBOX = ROOT / "src" / "openclip" / "_shared_toolbox"
PYTHON_DOMAIN_PACK = ROOT / "src" / "openclip" / "_domain_pack"


def _role_name(md: Path) -> str:
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("name:"):
            return line.split("name:", 1)[1].strip()
    return md.stem


def _worker_skill_body(body: str) -> str:
    """Add public-entry routing metadata without changing Claude agent roles."""
    marker = "description: >\n"
    if marker not in body:
        return body
    notice = (
        "  Internal OpenClip worker. Invoke only when dispatched by the public `oc` skill;\n"
        "  do not use this role as the user-facing entry point.\n"
    )
    return body.replace(marker, marker + notice, 1)


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as source:
        return str(tomllib.load(source)["project"]["version"])


def _manifest_value(manifest: str, key: str) -> str:
    """Read a scalar from the small, stable Domain Pack metadata header."""
    if key == "apiVersion":
        for line in manifest.splitlines():
            if line.startswith("apiVersion:"):
                return line.partition(":")[2].strip()
    if key == "version":
        in_metadata = False
        for line in manifest.splitlines():
            if line == "metadata:":
                in_metadata = True
                continue
            if in_metadata and line and not line.startswith(" "):
                break
            if in_metadata and line.startswith("  version:"):
                return line.partition(":")[2].strip().strip('"').strip("'")
    raise ValueError(f"missing {key} in ContractPlane manifest")


def _domain_lock_body(
    manifest: str,
    role_files: dict[Path, str],
    compiled_files: dict[Path, str],
) -> str:
    """Build the portable resource lock from canonical OpenClip sources."""
    previous: dict[str, object] = {}
    lock_path = CONTRACTPLANE_SRC / "lock.json"
    if lock_path.is_file():
        try:
            previous = json.loads(lock_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}

    plans: list[dict[str, object]] = []
    for relative, body in sorted(compiled_files.items()):
        payload = json.loads(body)
        plan_digest = payload.get("planDigest")
        if not isinstance(plan_digest, str) or len(plan_digest) != 64:
            raise ValueError(f"compiled plan has no valid planDigest: {relative}")
        plans.append(
            {
                "flow": payload.get("flow"),
                "entrypoint": payload.get("entrypoint"),
                "path": relative.as_posix(),
                "sha256": _sha256(body),
                "planDigest": plan_digest,
                "status": "reference-fixture",
            }
        )

    roles = [
        {
            "role": relative.stem,
            "path": relative.as_posix(),
            "sha256": _sha256(body),
        }
        for relative, body in sorted(role_files.items())
    ]
    lock = {
        "schema": "openclip-contractplane-lock-v2",
        "apiVersion": _manifest_value(manifest, "apiVersion"),
        "domain": "openclip",
        "domainVersion": _manifest_value(manifest, "version"),
        "contractplaneVersion": previous.get("contractplaneVersion", "0.1.0"),
        "openclipVersion": _project_version(),
        "packSha256": _sha256(manifest),
        "source": {
            "repository": "https://github.com/Q00/openclip",
            "release": "pending",
            "revision": "current-worktree",
            "path": "contractplane/openclip.domain.yaml",
        },
        "roleContracts": roles,
        "compiledPlans": plans,
    }
    return json.dumps(lock, ensure_ascii=False, indent=2) + "\n"


def _planned() -> dict[Path, str]:
    """Map of target path -> desired content."""
    plan: dict[Path, str] = {}

    # 1) Claude subagents: verbatim copies of canonical role files.
    for md in sorted(AGENTS_SRC.glob("*.md")):
        plan[CLAUDE_AGENTS / md.name] = md.read_text(encoding="utf-8")

    # 2) Claude + Codex orchestrator skill: copy the canonical skill files
    #    (skills/oc/flows/ is generated below, not canonical — skip it here).
    for f in sorted(SKILL_SRC.rglob("*")):
        if f.is_file() and not ({"flows", "domain-pack"} & set(f.relative_to(SKILL_SRC).parts)):
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

    # 4) The ContractPlane pack is canonical domain knowledge. Bundle the same
    #    source + precompiled contracts into every agent surface and the wheel;
    #    consumers do not need the ContractPlane Python package at runtime.
    domain_files: dict[Path, str] = {}
    manifest = CONTRACTPLANE_SRC / "openclip.domain.yaml"
    if manifest.is_file():
        manifest_body = manifest.read_text(encoding="utf-8")
        compiled_files: dict[Path, str] = {}
        compiled = CONTRACTPLANE_SRC / "compiled"
        if compiled.is_dir():
            for item in sorted(compiled.glob("*.json")):
                relative = Path("compiled") / item.name
                compiled_files[relative] = item.read_text(encoding="utf-8")
        role_files = {
            Path("roles") / f"{_role_name(md)}.md": md.read_text(encoding="utf-8")
            for md in sorted(AGENTS_SRC.glob("*.md"))
        }
        lock_body = _domain_lock_body(manifest_body, role_files, compiled_files)
        # The lock is generated from the canonical manifest, roles, plans, and
        # project version. Keeping it in the plan makes --check catch stale hashes.
        plan[CONTRACTPLANE_SRC / "lock.json"] = lock_body
        for rel, body in role_files.items():
            plan[CONTRACTPLANE_SRC / rel] = body
        domain_files[Path("openclip.domain.yaml")] = manifest_body
        domain_files[Path("lock.json")] = lock_body
        domain_files.update(role_files)
        domain_files.update(compiled_files)

        plan[PYTHON_DOMAIN_PACK / "__init__.py"] = (
            '"""Generated OpenClip ContractPlane Domain Pack resources."""\n\n'
            f'LOCK_SHA256 = "{_sha256(lock_body)}"\n'
        )
        for rel, body in domain_files.items():
            plan[PYTHON_DOMAIN_PACK / rel] = body
            plan[SKILL_SRC / "domain-pack" / rel] = body
            plan[CLAUDE_SKILL / "domain-pack" / rel] = body
            plan[CODEX_SKILLS / "oc" / "domain-pack" / rel] = body

    # 5) Worker skills: one skill folder per canonical role, in BOTH the Codex
    #    layout and the npx-skills catalog.
    for md in sorted(AGENTS_SRC.glob("*.md")):
        name = _role_name(md)            # e.g. oc-stt-worker
        body = _worker_skill_body(md.read_text(encoding="utf-8"))
        plan[CODEX_SKILLS / name / "SKILL.md"] = body
        plan[SKILLS_CATALOG / name / "SKILL.md"] = body

    # 6) Shared learned tools ship inside the Python wheel so skills-only users
    #    start with the same audited toolbox as repo-clone users.
    registry_path = SHARED_TOOLBOX_SRC / "registry.json"
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        shared = [tool for tool in registry.get("tools", []) if tool.get("tier") == "shared"]
        packaged = {"schema": registry.get("schema", "oc-toolbox-v2"), "tools": shared}
        plan[PYTHON_SHARED_TOOLBOX / "registry.json"] = (
            json.dumps(packaged, ensure_ascii=False, indent=2) + "\n"
        )
        for tool in shared:
            rel = Path(str(tool["script"]).removeprefix("toolbox/"))
            source = SHARED_TOOLBOX_SRC / rel
            if source.is_file():
                plan[PYTHON_SHARED_TOOLBOX / rel] = source.read_text(encoding="utf-8")

    return plan


def _generated_roots(plan: dict[Path, str]) -> list[Path]:
    """Directories whose files are ALL generated (safe to orphan-scan)."""
    roots = [
        CLAUDE_AGENTS,
        CLAUDE_SKILL,
        CODEX_SKILLS,
        SKILL_SRC / "flows",
        SKILL_SRC / "domain-pack",
        CONTRACTPLANE_SRC / "roles",
        PYTHON_SHARED_TOOLBOX,
        PYTHON_DOMAIN_PACK,
    ]
    # skills/oc-* catalog dirs are generated wholesale; skills/oc is canonical
    # (except flows/, covered above) so it is NOT scanned as a whole.
    roots.extend(sorted(p for p in SKILLS_CATALOG.glob("oc-*") if p.is_dir()))
    return roots


def _orphans(plan: dict[Path, str]) -> list[Path]:
    """Generated mirror files that are no longer in the plan (deleted sources)."""
    # `.claude/skills/oc` is a symlink to `.agents/skills/oc` in the repository.
    # Compare and deduplicate real paths so an orphan is not unlinked twice through
    # the two distribution aliases (and a planned alias is never deleted).
    planned = {path.resolve() for path in plan}
    seen: set[Path] = set()
    found: list[Path] = []
    for root in _generated_roots(plan):
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if "__pycache__" in f.parts or f.suffix in {".pyc", ".pyo"}:
                continue
            real = f.resolve()
            if real in seen:
                continue
            seen.add(real)
            if f.is_file() and real not in planned:
                found.append(f)
    return found


def sync(check: bool) -> int:
    catalog_symlinks = sorted(p for p in SKILLS_CATALOG.glob("oc*") if p.is_symlink())
    if catalog_symlinks:
        print("INVALID skills catalog: directory symlinks are not portable to npx skills clones:")
        for p in catalog_symlinks:
            print(f"  - {p.relative_to(ROOT)} (symlink)")
        return 1

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
