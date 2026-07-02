"""Self-extending, self-IMPROVING tool library with a shared-memory promotion gate.

Agents author small tools, verify them, and register them. Tools start as
``local`` (this repo only). A tool becomes ``shared`` memory — reusable and
recommended across sessions/people — ONLY through an explicit promotion gate:
re-verified in a CLEAN environment, statically scanned for dangerous calls, and
human/auditor-approved. "A done is a claim, not proof" applies to tools too.

Security posture (learned tools are arbitrary scripts we execute):
- run with a SCRUBBED env — no secrets (OPENAI key etc.) reach a learned tool;
- script paths are pinned inside ``toolbox/scripts`` (no traversal);
- registry writes are file-locked (no lost updates under parallel agents);
- ``--file`` sources and selftest args are validated/shlex-parsed.

Layout (repo-level, git-tracked so it accumulates and shares via git):

    toolbox/
      registry.json          # tools: tier, provenance, reliability, selftest
      learnings.jsonl        # append-only SHARED memory (promotion-gated writes)
      scripts/<name>.<ext>   # authored scripts
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_INTERPRETERS = {"python": [sys.executable], "bash": ["bash"], "sh": ["sh"], "node": ["node"]}
_EXT = {"python": ".py", "bash": ".sh", "sh": ".sh", "node": ".js"}
_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{1,48}")
# env vars a learned tool may see — everything else (esp. secrets) is scrubbed.
_ENV_ALLOW = {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE", "USER", "LOGNAME", "SHELL", "TERM"}
_SECRET_RE = re.compile(r"(key|secret|token|password|passwd|credential|auth|session)", re.I)
# static deny-list: calls that must trigger human review before a tool goes shared.
_DANGER_RE = re.compile(
    r"\b(curl|wget|nc|ncat|ssh|scp|sftp|telnet|sudo|rm\s+-rf|mkfs|dd\s+if=|:\(\)\s*\{|eval\b|exec\b"
    r"|base64\s+-d|/dev/tcp|socket\.|urllib|requests\.|httpx\.|subprocess\.Popen|os\.system|shutil\.rmtree)\b"
)


def _repo_root() -> Path:
    here = Path.cwd().resolve()
    for d in [here, *here.parents]:
        if (d / "pyproject.toml").exists() or (d / ".git").exists():
            return d
    raise RuntimeError(f"could not locate repo root (pyproject.toml/.git) from {here}")


def _toolbox_dir() -> Path:
    d = _repo_root() / "toolbox"
    (d / "scripts").mkdir(parents=True, exist_ok=True)
    return d


def _registry_path() -> Path:
    return _toolbox_dir() / "registry.json"


def _learnings_path() -> Path:
    return _toolbox_dir() / "learnings.jsonl"


@contextmanager
def _locked() -> Iterator[None]:
    """Advisory file lock around a registry read-modify-write."""
    lock = _toolbox_dir() / ".registry.lock"
    fh = lock.open("w")
    try:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass  # best-effort on platforms without flock
        yield
    finally:
        fh.close()


def _load_registry() -> list[dict[str, Any]]:
    p = _registry_path()
    if p.exists():
        return [_migrate_entry(t) for t in json.loads(p.read_text(encoding="utf-8")).get("tools", [])]
    return []


def _migrate_entry(t: dict[str, Any]) -> dict[str, Any]:
    """Normalize a legacy (v1) registry entry in place: created_by ->
    provenance.author, top-level invocations -> reliability. Without this,
    legacy tools list with zero reliability history."""
    if "provenance" not in t:
        t["provenance"] = {"author": t.pop("created_by", "unknown"), "runtime": "", "model": ""}
    if "reliability" not in t:
        n = int(t.pop("invocations", 0) or 0)
        t["reliability"] = {"invocations": n, "successes": n, "failures": 0, "last_error": None}
    t.setdefault("tier", "local")
    t.setdefault("selftest", None)
    return t


def _save_registry(tools: list[dict[str, Any]]) -> None:
    _registry_path().write_text(
        json.dumps({"schema": "oc-toolbox-v2", "tools": tools}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _entry(tools: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((t for t in tools if t["name"] == name), None)


def _script_path(entry: dict[str, Any]) -> Path:
    """Resolve+validate a registry script path stays inside toolbox/scripts."""
    scripts = (_toolbox_dir() / "scripts").resolve()
    p = (_repo_root() / entry["script"]).resolve()
    if scripts not in p.parents:
        raise ValueError(f"registry entry '{entry.get('name')}' points outside toolbox/scripts: {p}")
    return p


def _safe_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOW and not _SECRET_RE.search(k)}
    env["PYTHONPATH"] = str(_repo_root() / "src")
    return env


def _run_script(lang: str, script: Path, args: list[str],
                timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run([*_INTERPRETERS[lang], str(script), *args], text=True,
                          capture_output=True, env=_safe_env(), timeout=timeout)


# --------------------------------------------------------------------------- #
def toolbox_new(name: str, description: str, file: str, lang: str = "python",
                usage: str = "", selftest: str | None = None, created_by: str = "agent",
                runtime: str = "", model: str = "") -> dict[str, Any]:
    """Register a new LOCAL tool from an authored script. Self-test gated."""
    if not _NAME_RE.fullmatch(name):
        raise ValueError("name must be lowercase kebab/snake, 2-49 chars")
    if lang not in _INTERPRETERS:
        raise ValueError(f"lang must be one of {sorted(_INTERPRETERS)}")
    source = Path(file).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"authored script not found: {source}")
    # constrain --file to the repo tree or a temp scratch dir (no /etc/passwd)
    allowed_roots = [_repo_root().resolve(), Path(os.environ.get("TMPDIR", "/tmp")).resolve(), Path("/tmp").resolve()]
    if not any(root in source.parents or root == source.parent for root in allowed_roots):
        raise ValueError(f"--file must live under the repo or a temp dir, got {source}")

    with _locked():
        tools = _load_registry()
        if _entry(tools, name):
            raise ValueError(f"tool '{name}' already exists; pick a new name or promote/update it")
        dest = _toolbox_dir() / "scripts" / f"{name}{_EXT[lang]}"
        shutil.copyfile(source, dest)
        dest.chmod(0o755)

        selftest_result = None
        if selftest is not None:
            args = shlex.split(selftest)
            proc = _run_script(lang, dest, args, timeout=300)
            selftest_result = {"args": args, "returncode": proc.returncode,
                               "stdout_tail": proc.stdout[-500:], "stderr_tail": proc.stderr[-500:]}
            if proc.returncode != 0:
                dest.unlink(missing_ok=True)
                raise RuntimeError(f"selftest failed (exit {proc.returncode}); NOT registered. stderr: {proc.stderr[-400:]}")

        entry = {
            "name": name,
            "description": description,
            "lang": lang,
            "script": str(dest.relative_to(_repo_root())),
            "usage": usage or f"oc toolbox run --name {name} -- <args>",
            "tier": "local",
            "provenance": {"author": created_by, "runtime": runtime, "model": model},
            "selftest": selftest_result,
            "reliability": {"invocations": 0, "successes": 0, "failures": 0, "last_error": None},
        }
        tools.append(entry)
        _save_registry(tools)
    return {"tool": "toolbox-new", "registered": name, "tier": "local", "script": entry["script"], "selftest": selftest_result}


def toolbox_list(query: str | None = None, tier: str | None = None) -> dict[str, Any]:
    tools = _load_registry()
    if query:
        q = query.lower()
        tools = [t for t in tools if q in t["name"].lower() or q in t["description"].lower()]
    if tier:
        tools = [t for t in tools if t.get("tier", "local") == tier]

    def rel(t: dict[str, Any]) -> dict[str, Any]:
        r = t.get("reliability", {})
        n = r.get("invocations", 0)
        rate = (r.get("successes", 0) / n) if n else None
        return {"name": t["name"], "description": t["description"], "usage": t["usage"],
                "lang": t["lang"], "tier": t.get("tier", "local"),
                "invocations": n, "success_rate": rate, "healthy": rate is None or rate >= 0.6}

    return {
        "tool": "toolbox-list",
        "count": len(tools),
        "tools": [rel(t) for t in tools],
        "hint": "Reuse an existing HEALTHY tool before authoring. Promote local->shared with `oc toolbox promote`.",
    }


def toolbox_show(name: str) -> dict[str, Any]:
    tools = _load_registry()
    entry = _entry(tools, name)
    if not entry:
        raise ValueError(f"no learned tool '{name}'")
    src = _script_path(entry).read_text(encoding="utf-8")
    return {"tool": "toolbox-show", **entry, "source": src}


def toolbox_run(name: str, args: list[str]) -> dict[str, Any]:
    with _locked():
        tools = _load_registry()
        entry = _entry(tools, name)
        if not entry:
            raise ValueError(f"no learned tool '{name}'; `oc toolbox list` to discover, or author it")
        script = _script_path(entry)
    proc = _run_script(entry["lang"], script, args, timeout=600)
    with _locked():  # reload to avoid clobbering a concurrent counter update
        tools = _load_registry()
        entry = _entry(tools, name) or entry
        rel = entry.setdefault("reliability", {"invocations": 0, "successes": 0, "failures": 0, "last_error": None})
        rel["invocations"] += 1
        if proc.returncode == 0:
            rel["successes"] += 1
        else:
            rel["failures"] += 1
            rel["last_error"] = proc.stderr[-300:]
        _save_registry(tools)
    return {
        "tool": "toolbox-run", "name": name, "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:] if proc.returncode != 0 else "",
    }


def toolbox_promote(name: str, reviewed: bool = False, promoted_by: str = "human") -> dict[str, Any]:
    """Gate a LOCAL tool into SHARED memory. Mechanical gate here; ``reviewed``
    must be set by a human/auditor for the tier to actually flip.

    Gate = re-run the selftest in a scrubbed env (author's result ignored) +
    static deny-list scan. On pass AND ``reviewed``, flip to shared and append a
    ``tool_promoted`` learning. Otherwise report what blocks promotion.
    """
    with _locked():
        tools = _load_registry()
        entry = _entry(tools, name)
        if not entry:
            raise ValueError(f"no learned tool '{name}'")
        script = _script_path(entry)
    source = script.read_text(encoding="utf-8")

    danger = sorted(set(m.group(0) for m in _DANGER_RE.finditer(source)))
    reverify = None
    st = entry.get("selftest")
    if st and st.get("args") is not None:
        proc = _run_script(entry["lang"], script, list(st["args"]), timeout=300)
        reverify = {"returncode": proc.returncode, "stderr_tail": proc.stderr[-400:]}

    gate = {
        "static_scan": "pass" if not danger else "needs_review",
        "danger_hits": danger,
        "clean_reverify": reverify,
        "reverify_ok": reverify is None or reverify["returncode"] == 0,
        "human_reviewed": bool(reviewed),
    }
    can_promote = (not danger) and gate["reverify_ok"] and reviewed
    if not can_promote:
        return {"tool": "toolbox-promote", "name": name, "promoted": False, "gate": gate,
                "reason": "blocked: " + ", ".join(
                    ([f"static scan hit {danger}"] if danger else [])
                    + ([] if gate["reverify_ok"] else ["clean re-verify failed"])
                    + ([] if reviewed else ["not human/auditor reviewed (pass --reviewed)"]))}

    with _locked():
        tools = _load_registry()
        entry = _entry(tools, name) or entry
        entry["tier"] = "shared"
        _save_registry(tools)
    _append_learning({"kind": "tool_promoted", "name": name, "by": promoted_by,
                       "static_scan": "pass", "clean_reverify_ok": True})
    return {"tool": "toolbox-promote", "name": name, "promoted": True, "tier": "shared", "gate": gate}


def _append_learning(entry: dict[str, Any]) -> None:
    with _learnings_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def toolbox_learnings(query: str | None = None) -> dict[str, Any]:
    p = _learnings_path()
    items = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    if query:
        q = query.lower()
        items = [i for i in items if q in json.dumps(i, ensure_ascii=False).lower()]
    return {"tool": "toolbox-learnings", "count": len(items), "learnings": items}


def toolbox_remove(name: str) -> dict[str, Any]:
    with _locked():
        tools = _load_registry()
        entry = _entry(tools, name)
        if not entry:
            raise ValueError(f"no learned tool '{name}'")
        _script_path(entry).unlink(missing_ok=True)
        tools = [t for t in tools if t["name"] != name]
        _save_registry(tools)
    return {"tool": "toolbox-remove", "removed": name}
