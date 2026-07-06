#!/usr/bin/env python3
"""SubagentStop evidence gate.

A render/verify worker that reports "done" without an observable evidence receipt
is blocked and asked to prove it — up to MAX_ATTEMPTS, then allowed through so the
session never hard-locks. Evidence = a final line `EVIDENCE_RECORDED: <path>`
pointing at a non-empty file (e.g. `evidence/<name>.verify.json`).

This is a safety net, not a cage: it never overrides the human. Steering always
wins. Runtime-agnostic and defensive — any parsing problem defaults to ALLOW
(empty output) and never crashes the session. Wire it on SubagentStop in both
.claude/settings.json (Claude Code) and .codex/hooks.json (Codex).
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

MAX_ATTEMPTS = 3
# Only enforce for workers whose deliverable is a file: renders + the verifier.
ENFORCED = re.compile(r"oc-(verifier|assembler|cut-judge|subtitle-agent|thumbnail-artist|toolsmith|tool-auditor)")
EVIDENCE_RE = re.compile(r"EVIDENCE_RECORDED:\s*(\S+)")


def _read_stdin() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def _agent_label(data: dict) -> str:
    for key in ("agent_type", "subagent_type", "agent", "agent_id", "name"):
        v = data.get(key)
        if isinstance(v, str):
            return v
    return ""


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def _last_assistant_text(transcript_path: str | None) -> str:
    """Last assistant text from a transcript, handling BOTH shapes:
    SDK  {"role":"assistant","content":[{"text":...}]}  and
    CLI  {"type":"assistant","message":{"role":"assistant","content":[{"text":...}]}}.
    """
    if not transcript_path:
        return ""
    p = Path(transcript_path)
    if not p.exists():
        return ""
    last = ""
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("role") != "assistant" and obj.get("type") != "assistant":
                continue
            msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
            text = _text_from_content(msg.get("content") or msg.get("text"))
            if text.strip():
                last = text
    except Exception:
        return ""
    return last


def _state_path(data: dict) -> Path:
    key = f"{data.get('session_id','s')}-{data.get('agent_id', data.get('agent','a'))}"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)
    return Path(tempfile.gettempdir()) / "oc_evidence" / f"{safe}.json"


def _attempts(sp: Path) -> int:
    try:
        return int(json.loads(sp.read_text())["attempts"])
    except Exception:
        return 0


def _write_attempts(sp: Path, n: int) -> None:
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({"attempts": n}), encoding="utf-8")


def _allow() -> int:
    """Allow the subagent to stop. Codex's SubagentStop requires JSON on stdout
    for exit 0 (plain/empty is invalid there); Claude Code treats this payload
    as a no-op. One shape works for both runtimes."""
    print(json.dumps({"continue": True}))
    return 0


def main() -> int:
    data = _read_stdin()
    label = _agent_label(data)
    if not ENFORCED.search(label):
        return _allow()  # not a deliverable-producing worker

    # Prefer the fields the runtime hands us directly; fall back to the subagent's
    # OWN transcript, then the parent transcript.
    text = (
        data.get("last_assistant_message")
        or _last_assistant_text(data.get("agent_transcript_path"))
        or _last_assistant_text(data.get("transcript_path"))
    )
    if not isinstance(text, str):
        text = _text_from_content(text)
    m = EVIDENCE_RE.search(text)
    if m:
        raw = m.group(1)
        # a relative receipt (e.g. toolbox/registry.json) must resolve against
        # the session's cwd/project dir, not wherever the hook process runs
        candidates = [Path(raw)]
        for base_key in ("cwd", "project_dir", "workspace_root"):
            base = data.get(base_key)
            if isinstance(base, str) and base:
                candidates.append(Path(base) / raw)
        if any(ev.exists() and ev.stat().st_size > 0 for ev in candidates):
            sp = _state_path(data)
            if sp.exists():
                sp.unlink()
            return _allow()  # real evidence

    sp = _state_path(data)
    attempts = _attempts(sp)
    if attempts >= MAX_ATTEMPTS:
        sp.unlink(missing_ok=True)
        return _allow()  # give up blocking; surface to the human instead

    _write_attempts(sp, attempts + 1)
    directive = (
        "You reported done without observable evidence. Do not claim success — "
        "prove it. Run `oc --project <PROJECT> verify --path <DELIVERABLE> "
        "[--expect-duration ...] [--expect-aspect 9:16] [--srt ...]`, probe the "
        "applicable adversarial classes (blank_frames, duration_drift, "
        "wrong_aspect, cut_off_by_one, stale_render, srt_invalid), and end your "
        "message with `EVIDENCE_RECORDED: <path to the evidence json>`. "
        f"(attempt {attempts + 1}/{MAX_ATTEMPTS})"
    )
    print(json.dumps({"decision": "block", "reason": directive}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        try:
            print(json.dumps({"continue": True}))
        except Exception:
            pass
        sys.exit(0)  # never break the session
