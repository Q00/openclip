"""Learned taste memory — the harness's GEPA-style personalization loop.

The agent is the mutation operator; this module is the deterministic substrate
(same philosophy as the toolbox: Python holds state, the agent holds judgment).

Loop per domain (e.g. ``thumbnail``):

1. ``taste note``  — every human verdict (liked / disliked / steer) is appended
   to an event log, attributed to the guidance generation that produced it.
2. ``taste show``  — workers read the ACTIVE guidance before designing, plus
   per-generation scoreboards so lineage quality is visible.
3. ``taste evolve``— two-phase reflective mutation: without ``--write`` it
   returns a reflection packet (current guidance + uncovered verdicts +
   per-generation scores + instructions); the agent writes the next guidance
   generation and commits it with ``--write``. Ancestors are archived, so a
   worse generation can be rolled back with ``taste revert``.

Guidance lives in ``toolbox/taste/<domain>/`` (shared across projects, like
learned tools) — it is the channel's taste, not one video's.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .toolbox import _repo_root

_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_-]{1,40}$")

EVOLVE_DUE_AFTER = 3  # uncovered verdicts before evolution is suggested


def _taste_root() -> Path:
    """Where learned taste lives. Three-tier resolution:

    1. ``OPENCLIP_HOME`` env — explicit (shared team volume, tests).
    2. A repo that already carries a ``toolbox/`` — repo-local, git-shareable
       (this repo itself; teams that opt in by committing the dir).
    3. ``~/.openclip/taste`` — the plugin-install default: taste accumulates
       across all of a user's projects without polluting their repos, and
       works outside any git checkout.
    """
    env = os.environ.get("OPENCLIP_HOME")
    if env:
        return Path(env).expanduser() / "taste"
    try:
        root = _repo_root()
        if (root / "toolbox").is_dir():
            return root / "toolbox" / "taste"
    except RuntimeError:
        pass
    return Path.home() / ".openclip" / "taste"


def _taste_dir(domain: str) -> Path:
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"invalid taste domain: {domain!r} (lowercase slug expected)")
    d = _taste_root() / domain
    (d / "history").mkdir(parents=True, exist_ok=True)
    return d


def _events_path(domain: str) -> Path:
    return _taste_dir(domain) / "events.jsonl"


def _guidance_path(domain: str) -> Path:
    return _taste_dir(domain) / "guidance.md"


def _read_events(domain: str) -> list[dict[str, Any]]:
    path = _events_path(domain)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _append_event(domain: str, event: dict[str, Any]) -> None:
    with _events_path(domain).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _parse_guidance(text: str) -> tuple[dict[str, Any], str]:
    """Split ``---`` frontmatter (generation lineage) from the guidance body."""
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            body = parts[2]
    return meta, body.strip()


def _current_generation(domain: str) -> int:
    g = _guidance_path(domain)
    if not g.exists():
        return 0
    meta, _ = _parse_guidance(g.read_text(encoding="utf-8"))
    try:
        return int(meta.get("generation", 0))
    except ValueError:
        return 0


def _generation_scores(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    scores: dict[str, dict[str, int]] = {}
    for ev in events:
        if ev.get("event") != "note":
            continue
        gen = str(ev.get("generation", 0))
        s = scores.setdefault(gen, {"liked": 0, "disliked": 0, "steer": 0})
        verdict = ev.get("verdict", "steer")
        s[verdict] = s.get(verdict, 0) + 1
    return scores


def taste_note(domain: str, note: str, verdict: str = "steer",
               ref: str | None = None, project: str | None = None) -> dict[str, Any]:
    """Record one human verdict against the ACTIVE guidance generation."""
    if verdict not in {"liked", "disliked", "steer"}:
        raise ValueError("verdict must be liked | disliked | steer")
    if not note.strip():
        raise ValueError("--note must say what worked or failed, concretely")
    gen = _current_generation(domain)
    _append_event(domain, {
        "event": "note", "domain": domain, "verdict": verdict, "note": note.strip(),
        "ref": ref, "project": project, "generation": gen,
    })
    uncovered = _uncovered_notes(domain)
    return {"tool": "taste", "action": "note", "domain": domain, "generation": gen,
            "uncovered_notes": len(uncovered), "evolve_due": len(uncovered) >= EVOLVE_DUE_AFTER}


def _uncovered_notes(domain: str) -> list[dict[str, Any]]:
    """Notes not yet reflected into any committed guidance generation."""
    events = _read_events(domain)
    covered_up_to = -1
    for i, ev in enumerate(events):
        if ev.get("event") == "evolve":
            covered_up_to = i
    return [ev for ev in events[covered_up_to + 1:] if ev.get("event") == "note"]


def taste_show(domain: str) -> dict[str, Any]:
    """Active guidance + lineage scoreboard. Workers call this BEFORE designing."""
    g = _guidance_path(domain)
    events = _read_events(domain)
    uncovered = _uncovered_notes(domain)
    meta: dict[str, Any] = {}
    body = ""
    if g.exists():
        meta, body = _parse_guidance(g.read_text(encoding="utf-8"))
    return {
        "tool": "taste",
        "action": "show",
        "domain": domain,
        "storage": str(_taste_dir(domain)),
        "generation": _current_generation(domain),
        "lineage": meta,
        "guidance": body or "(no guidance yet — design from the role's default quality bar)",
        "generation_scores": _generation_scores(events),
        "uncovered_notes": uncovered,
        "evolve_due": len(uncovered) >= EVOLVE_DUE_AFTER,
    }


def taste_evolve(domain: str, write: str | None = None, by: str = "agent") -> dict[str, Any]:
    """Two-phase reflective mutation over the guidance.

    Phase 1 (no ``write``): return the reflection packet — current guidance,
    every uncovered verdict, per-generation scores — plus instructions for
    authoring the next generation.
    Phase 2 (``write=<file>``): commit the agent-authored guidance as the next
    generation; the old one is archived to ``history/gen_<N>.md``.
    """
    current_gen = _current_generation(domain)
    events = _read_events(domain)
    uncovered = _uncovered_notes(domain)

    if write is None:
        return {
            "tool": "taste",
            "action": "evolve",
            "phase": "reflect",
            "domain": domain,
            "generation": current_gen,
            "current_guidance": taste_show(domain)["guidance"],
            "uncovered_notes": uncovered,
            "generation_scores": _generation_scores(events),
            "instructions": (
                "Author the NEXT guidance generation as markdown: keep rules that "
                "produced 'liked' verdicts, rewrite or drop rules implicated in "
                "'disliked' ones, and fold every steer note into a concrete DO/DON'T. "
                "Rules must be specific enough to act on (composition, palette, "
                "headline patterns), max ~25 lines. If the scoreboard shows an older "
                "generation outperforming the current one, start from that ancestor "
                "(history/gen_<N>.md) instead. Save the body to a file and re-run "
                "with --write <file>."
            ),
        }

    source = Path(write).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"guidance draft not found: {source}")
    body = source.read_text(encoding="utf-8").strip()
    if len(body) < 40:
        raise ValueError("guidance draft is too thin to be a real reflection (< 40 chars)")
    if len(body) > 4000:
        # hard constraint gate (GEPA-style): evolution must not drift verbose —
        # a guidance that outgrows a worker's attention span stops being followed
        raise ValueError(
            f"guidance draft too long ({len(body)} chars > 4000): distill it — "
            "keep only rules that changed a verdict, drop narrative"
        )

    g = _guidance_path(domain)
    if g.exists():
        archived = _taste_dir(domain) / "history" / f"gen_{current_gen}.md"
        archived.write_text(g.read_text(encoding="utf-8"), encoding="utf-8")
    next_gen = current_gen + 1
    g.write_text(
        f"---\ngeneration: {next_gen}\nparent: {current_gen}\nauthored_by: {by}\n"
        f"notes_covered: {len(uncovered)}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    _append_event(domain, {"event": "evolve", "domain": domain, "generation": next_gen,
                           "parent": current_gen, "notes_covered": len(uncovered), "by": by})
    return {"tool": "taste", "action": "evolve", "phase": "committed", "domain": domain,
            "generation": next_gen, "parent": current_gen, "notes_covered": len(uncovered)}


def taste_revert(domain: str, to_generation: int, by: str = "human") -> dict[str, Any]:
    """Roll back to an archived generation that scored better (selection step)."""
    current_gen = _current_generation(domain)
    if to_generation == current_gen:
        raise ValueError(f"already on generation {current_gen}")
    archived = _taste_dir(domain) / "history" / f"gen_{to_generation}.md"
    if not archived.exists():
        raise FileNotFoundError(f"no archived generation {to_generation} for {domain}")
    g = _guidance_path(domain)
    if g.exists():
        (_taste_dir(domain) / "history" / f"gen_{current_gen}.md").write_text(
            g.read_text(encoding="utf-8"), encoding="utf-8")
    _, body = _parse_guidance(archived.read_text(encoding="utf-8"))
    next_gen = current_gen + 1
    g.write_text(
        f"---\ngeneration: {next_gen}\nparent: {to_generation}\nauthored_by: {by}\n"
        f"reverted_from: {current_gen}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    _append_event(domain, {"event": "evolve", "domain": domain, "generation": next_gen,
                           "parent": to_generation, "reverted_from": current_gen, "by": by})
    return {"tool": "taste", "action": "revert", "domain": domain,
            "generation": next_gen, "restored_from": to_generation}
