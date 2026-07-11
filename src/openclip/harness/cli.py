"""``oc`` CLI — the tool surface subagents call via Bash.

Every subcommand prints a single JSON object to stdout so an agent can parse the
result. Errors print ``{"error": ...}`` to stdout and exit non-zero.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from openclip import __version__

from . import tools


def _load_env(start: str | None = None) -> None:
    """Make OpenAI creds available to every `oc` call (incl. spawned subagents).

    Walks up from cwd (and an optional project dir) for a `.env` and maps the
    legacy `OPEN_API_KEY` to `OPENAI_API_KEY`. Honors `OPENAI_BASE_URL` when set;
    if the key is a Zep CLI-proxy key (`zk_`) and no base url is configured, it
    routes through the proxy so Whisper / gpt-image work. Never overwrites a value
    already set in the real environment.
    """
    roots = []
    if start:
        roots.append(Path(start).expanduser().resolve())
    roots.append(Path.cwd())
    file_vars: dict[str, str] = {}
    seen: set[Path] = set()
    for root in roots:
        for d in [root, *root.parents]:
            env_path = d / ".env"
            if env_path in seen or not env_path.exists():
                continue
            seen.add(env_path)
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                file_vars.setdefault(key, value)
                if key and key not in os.environ:
                    os.environ[key] = value
    # The project `.env` is authoritative for the OpenAI credential — it overrides
    # any proxy key the surrounding shell exported (e.g. a global `zk_` cliproxy
    # key). Prefer an official `OPENAI_API_KEY`, then the legacy `OPEN_API_KEY`.
    dotenv_key = file_vars.get("OPENAI_API_KEY") or file_vars.get("OPEN_API_KEY")
    if dotenv_key:
        os.environ["OPENAI_API_KEY"] = dotenv_key
    elif "OPENAI_API_KEY" not in os.environ and os.environ.get("OPEN_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["OPEN_API_KEY"]
    # Always hit the official OpenAI API; strip any CLI-proxy base url.
    os.environ.pop("OPENAI_BASE_URL", None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="oc", description="Composable video tools for an agent-orchestrated harness.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--project", help="Project directory holding state + artifacts")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("doctor", help="check CLI, ffmpeg, and OpenAI readiness for agent runs")
    sp.add_argument("--real-run", action="store_true", help="also require OPENAI_API_KEY")

    sp = sub.add_parser("proxy", help="LRF/LRV low-res proxy -> mp4")
    sp.add_argument("--input", required=True)
    sp.add_argument("--scale", type=int, default=640, help="target height; 0 = stream copy")
    sp.add_argument("--out")
    sp.add_argument("--force", action="store_true", help="re-encode even if the ledger shows this done")

    sp = sub.add_parser("ingest", help="split source audio into STT fan-out chunks")
    sp.add_argument("--input", required=True)
    sp.add_argument("--max-seconds", type=float, default=None)
    sp.add_argument("--start", type=float, default=0.0, help="start offset (skip silent intros)")
    sp.add_argument("--chunk-seconds", type=float, default=300.0,
                    help="seconds per STT chunk (shorter = wider parallel fan-out)")

    sp = sub.add_parser("stt", help="transcribe ONE chunk (parallel fan-out unit)")
    sp.add_argument("--chunk", type=int, required=True)
    sp.add_argument("--model", default="whisper-1")
    sp.add_argument("--mock", action="store_true")

    sub.add_parser("transcript-merge", help="merge chunk transcripts -> transcript.json + .md")

    sp = sub.add_parser("probe", help="silence + scene-cut signals for the cut-editor debate")
    sp.add_argument("--input", required=True)
    sp.add_argument("--scene-threshold", type=float, default=0.4)

    sp = sub.add_parser("cut", help="apply an EDL of keep-ranges -> one mp4")
    sp.add_argument("--input", required=True)
    sp.add_argument("--edl", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--aspect", default="source")
    sp.add_argument("--force", action="store_true", help="re-render even if the ledger shows this done")

    sp = sub.add_parser("clip", help="extract ONE range with aspect (shorts/hooks)")
    sp.add_argument("--input", required=True)
    sp.add_argument("--start", type=float, required=True)
    sp.add_argument("--end", type=float, required=True)
    sp.add_argument("--aspect", default="9:16")
    sp.add_argument("--id")
    sp.add_argument("--out")
    sp.add_argument("--burn-srt")
    sp.add_argument("--title", default=None,
                    help="persistent headline pinned to the top of the frame for the whole clip "
                         "(| = line break, *word* = accent)")
    sp.add_argument("--force", action="store_true", help="re-render even if the ledger shows this done")

    sp = sub.add_parser("subtitle", help="slice transcript -> SRT (optionally clip-relative + translated)")
    sp.add_argument("--start", type=float, default=0.0)
    sp.add_argument("--end", type=float, default=None)
    sp.add_argument("--out")
    sp.add_argument("--absolute", action="store_true", help="keep source timecodes (default rebases to clip start)")
    sp.add_argument("--translate-to", default=None)
    sp.add_argument("--model", default="gpt-4o-mini")
    sp.add_argument("--mock", action="store_true")
    sp.add_argument("--max-cue", type=float, default=2.2, help="max seconds per word-timed cue")
    sp.add_argument("--max-chars", type=int, default=18, help="max characters per word-timed cue")
    sp.add_argument("--fix-terms", action="store_true",
                    help="restore English/code terms STT phoneticised into Hangul (source captions)")
    sp.add_argument("--terms-hint", default=None,
                    help="comma-separated known English/code terms used in this talk")

    sp = sub.add_parser("thumbnail", help="hook-matched thumbnail (representative frame + title, or generated)")
    sp.add_argument("--input", required=True)
    sp.add_argument("--start", type=float, required=True)
    sp.add_argument("--end", type=float, required=True)
    sp.add_argument("--out")
    sp.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    sp.add_argument("--title", default=None)
    sp.add_argument("--at", type=float, default=None,
                    help="pin an exact frame time; default auto-picks the most representative frame in [start,end]")
    sp.add_argument("--generate", action="store_true", help="use gpt-image instead of a frame grab")
    sp.add_argument("--from-frame", action="store_true", help="use the grabbed frame as generation reference")
    sp.add_argument("--persona", default=None,
                    help="photo (or dir of photos) of the actual speaker; preserved as the thumbnail's identity")
    sp.add_argument("--style", default=None, choices=["clean", "editorial", "bold", "keynote"],
                    help="art-direction preset for generated thumbnails "
                         "(clean = understated studio, editorial = white-cover print style)")
    sp.add_argument("--quality", default="high", choices=["low", "medium", "high"],
                    help="gpt-image quality for the pro path")
    sp.add_argument("--prompt-note", default=None,
                    help="extra art direction appended to the generation prompt's "
                         "'Important details' slot (pose, expression, props, mood)")
    sp.add_argument("--composite", action="store_true",
                    help="no-AI path: real persona cutout on a flat studio background "
                         "+ typeset headline (rembg cutout; nothing is generated)")
    sp.add_argument("--render-text", action="store_true",
                    help="let gpt-image-2 typeset the headline itself (crisper design, "
                         "but PROBABILISTIC — verify spelling on every render)")
    sp.add_argument("--model", default="gpt-image-2")
    sp.add_argument("--mock", action="store_true")
    sp.add_argument("--force", action="store_true", help="re-make even if the ledger shows this done")

    sp = sub.add_parser("burn-srt", help="hard-burn an SRT into a video")
    sp.add_argument("--input", required=True)
    sp.add_argument("--srt", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--font-size", type=int, default=22)
    sp.add_argument("--margin-v", type=int, default=40)
    sp.add_argument("--force", action="store_true", help="re-render even if the ledger shows this done")

    sp = sub.add_parser("concat", help="join clips into a longform")
    sp.add_argument("--inputs", nargs="+", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--force", action="store_true", help="re-render even if the ledger shows this done")

    sp = sub.add_parser("verify", help="mechanical evidence gate for one deliverable")
    sp.add_argument("--path", required=True)
    sp.add_argument("--kind", default="clip")
    sp.add_argument("--expect-duration", type=float, default=None)
    sp.add_argument("--tolerance", type=float, default=1.5)
    sp.add_argument("--expect-aspect", default=None)
    sp.add_argument("--srt", default=None)

    sub.add_parser("status", help="stage flags + ledger + open steering directives")
    sub.add_parser("resume", help="completed units (skippable) + what still needs work")

    sp = sub.add_parser("steer", help="record a human steering directive for the next wave")
    sp.add_argument("--note", required=True)
    sp.add_argument("--scope", default="global", help="global | <stage> | section:<a>-<b> | <deliverable_id>")
    sp.add_argument("--stage", default=None)

    sp = sub.add_parser("steer-resolve", help="mark a steering directive addressed")
    sp.add_argument("--id", required=True)

    tb = sub.add_parser("toolbox", help="self-extending tool library (author + reuse learned tools)")
    tbsub = tb.add_subparsers(dest="tb_command", required=True)
    t = tbsub.add_parser("list", help="discover learned tools (check before authoring)")
    t.add_argument("--query", default=None)
    t.add_argument("--tier", default=None, choices=["local", "shared"])
    t = tbsub.add_parser("new", help="register a new learned tool from a script file")
    t.add_argument("--name", required=True)
    t.add_argument("--desc", required=True)
    t.add_argument("--file", required=True, help="path to the authored script")
    t.add_argument("--lang", default="python", choices=["python", "bash", "sh", "node"])
    t.add_argument("--usage", default="")
    t.add_argument("--selftest", required=True,
                   help="arg string; script must exit 0 and print one JSON object to register")
    t.add_argument("--by", default="agent")
    t = tbsub.add_parser("run", help="run a learned tool (args after --)")
    t.add_argument("--name", required=True)
    t.add_argument("--timeout", type=int, default=600, help="seconds before the tool is killed")
    t.add_argument("args", nargs="*", help="args passed to the tool")
    t = tbsub.add_parser("show", help="print a learned tool's source + usage")
    t.add_argument("--name", required=True)
    t = tbsub.add_parser("promote", help="gate a local tool into SHARED memory")
    t.add_argument("--name", required=True)
    t.add_argument("--reviewed", action="store_true", help="human/auditor approved (required to flip to shared)")
    t.add_argument("--by", default="human")
    t = tbsub.add_parser("propose", help="build a PR-ready packet for an audited shared tool")
    t.add_argument("--name", required=True)
    t.add_argument("--target", default="toolbox", choices=["toolbox", "builtin"])
    t.add_argument("--out", default=None)
    t.add_argument("--min-runs", type=int, default=3,
                   help="required representative runs; must be 3 or higher")
    tbsub.add_parser("learnings", help="list shared learnings (promoted knowledge)").add_argument("--query", default=None)
    t = tbsub.add_parser("remove", help="delete a learned tool")
    t.add_argument("--name", required=True)

    ts = sub.add_parser("taste", help="learned taste memory (GEPA-style guidance evolution per domain)")
    tssub = ts.add_subparsers(dest="taste_command", required=True)
    t = tssub.add_parser("show", help="active guidance + lineage scoreboard (read BEFORE designing)")
    t.add_argument("--domain", required=True, help="e.g. thumbnail")
    t = tssub.add_parser("note", help="record one human verdict against the active guidance")
    t.add_argument("--domain", required=True)
    t.add_argument("--note", required=True, help="what exactly worked / failed")
    t.add_argument("--verdict", default="steer", choices=["liked", "disliked", "steer"])
    t.add_argument("--ref", default=None, help="artifact path the verdict is about")
    t = tssub.add_parser("evolve", help="reflect verdicts into the next guidance generation")
    t.add_argument("--domain", required=True)
    t.add_argument("--write", default=None, help="commit this drafted guidance file as the next generation")
    t.add_argument("--by", default="agent")
    t = tssub.add_parser("revert", help="roll back to an archived generation that scored better")
    t.add_argument("--domain", required=True)
    t.add_argument("--to", type=int, required=True)
    t.add_argument("--by", default="human")

    ap = sub.add_parser("acp", help="Agent Client Protocol adapter (drive the harness from an ACP client)")
    ap.add_subparsers(dest="acp_command", required=True).add_parser("serve", help="serve ACP JSON-RPC over stdio")

    return p


def _doctor(real_run: bool = False) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    python_ok = sys.version_info >= (3, 11)
    api_key = bool(os.environ.get("OPENAI_API_KEY"))
    codex_hooks = Path.cwd() / ".codex" / "hooks.json"
    hook_script = Path.cwd() / "hooks" / "verify_evidence_hook.py"
    evidence_hook_ready = codex_hooks.is_file() and hook_script.is_file()
    mock_ready = python_ok and bool(ffmpeg) and bool(ffprobe)
    real_ready = mock_ready and api_key
    issues: list[str] = []
    if not python_ok:
        issues.append("Python 3.11+ is required.")
    if not ffmpeg:
        issues.append("ffmpeg is not on PATH.")
    if not ffprobe:
        issues.append("ffprobe is not on PATH.")
    if real_run and not api_key:
        issues.append("OPENAI_API_KEY is required for a real run (mock runs do not need it).")
    ready = real_ready if real_run else mock_ready
    return {
        "tool": "doctor",
        "version": __version__,
        "mode": "real" if real_run else "mock-capable",
        "status": "ready" if ready else "needs-setup",
        "ready": ready,
        "mock_ready": mock_ready,
        "real_run_ready": real_ready,
        "agent_gate_ready": evidence_hook_ready,
        "checks": {
            "python": {"ok": python_ok, "version": platform.python_version()},
            "ffmpeg": {"ok": bool(ffmpeg), "path": ffmpeg},
            "ffprobe": {"ok": bool(ffprobe), "path": ffprobe},
            "openai_api_key": {"ok": api_key, "required": real_run},
            "codex_evidence_hook": {
                "ok": evidence_hook_ready,
                "config": str(codex_hooks),
                "script": str(hook_script),
                "required": False,
                "fallback": "skill-only installs must require an independent oc-verifier verdict",
            },
        },
        "issues": issues,
    }


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    c = args.command
    if c == "doctor":
        return _doctor(real_run=args.real_run)
    if c == "proxy":
        return tools.proxy(args.project, args.input, scale=(args.scale or None), out=args.out,
                           force=args.force)
    if c == "ingest":
        return tools.ingest(args.project, args.input, max_seconds=args.max_seconds, start=args.start,
                            chunk_seconds=args.chunk_seconds)
    if c == "stt":
        return tools.stt(args.project, args.chunk, model=args.model, mock=args.mock)
    if c == "transcript-merge":
        return tools.transcript_merge(args.project)
    if c == "probe":
        return tools.probe(args.project, args.input, scene_threshold=args.scene_threshold)
    if c == "cut":
        return tools.cut(args.project, args.input, args.edl, args.out, aspect=args.aspect, force=args.force)
    if c == "clip":
        return tools.clip(args.project, args.input, args.start, args.end, aspect=args.aspect,
                          out=args.out, clip_id=args.id, burn_srt=args.burn_srt,
                          title=args.title, force=args.force)
    if c == "subtitle":
        return tools.subtitle(args.project, start=args.start, end=args.end, out=args.out,
                              relative=not args.absolute, translate_to=args.translate_to,
                              model=args.model, mock=args.mock, max_cue_seconds=args.max_cue,
                              max_cue_chars=args.max_chars, fix_terms=args.fix_terms,
                              terms_hint=args.terms_hint)
    if c == "thumbnail":
        return tools.thumbnail(args.project, args.input, args.start, args.end, out=args.out,
                               aspect=args.aspect, title=args.title, at=args.at, generate=args.generate,
                               from_frame=args.from_frame, model=args.model, mock=args.mock,
                               force=args.force, persona=args.persona, style=args.style,
                               quality=args.quality, prompt_note=args.prompt_note,
                               composite=args.composite, render_text=args.render_text)
    if c == "burn-srt":
        return tools.burn_srt(args.project, args.input, args.srt, args.out,
                              font_size=args.font_size, margin_v=args.margin_v, force=args.force)
    if c == "concat":
        return tools.concat(args.project, args.inputs, args.out, force=args.force)
    if c == "verify":
        return tools.verify(args.project, args.path, kind=args.kind, expect_duration=args.expect_duration,
                            tolerance=args.tolerance, expect_aspect=args.expect_aspect, srt=args.srt)
    if c == "status":
        return tools.status(args.project)
    if c == "resume":
        return tools.resume(args.project)
    if c == "steer":
        return tools.steer(args.project, args.note, scope=args.scope, stage=args.stage)
    if c == "steer-resolve":
        return tools.steer_resolve(args.project, args.id)
    if c == "toolbox":
        from . import toolbox
        tc = args.tb_command
        if tc == "list":
            return toolbox.toolbox_list(args.query, tier=args.tier)
        if tc == "new":
            return toolbox.toolbox_new(args.name, args.desc, args.file, lang=args.lang,
                                       usage=args.usage, selftest=args.selftest, created_by=args.by)
        if tc == "run":
            return toolbox.toolbox_run(args.name, args.args, timeout=args.timeout)
        if tc == "show":
            return toolbox.toolbox_show(args.name)
        if tc == "promote":
            return toolbox.toolbox_promote(args.name, reviewed=args.reviewed, promoted_by=args.by)
        if tc == "propose":
            return toolbox.toolbox_propose(args.name, target=args.target, out=args.out,
                                           min_runs=args.min_runs)
        if tc == "learnings":
            return toolbox.toolbox_learnings(args.query)
        if tc == "remove":
            return toolbox.toolbox_remove(args.name)
        raise AssertionError(tc)
    if c == "taste":
        from . import taste
        tc = args.taste_command
        if tc == "show":
            return taste.taste_show(args.domain)
        if tc == "note":
            return taste.taste_note(args.domain, args.note, verdict=args.verdict,
                                    ref=args.ref, project=args.project)
        if tc == "evolve":
            return taste.taste_evolve(args.domain, write=args.write, by=args.by)
        if tc == "revert":
            return taste.taste_revert(args.domain, args.to, by=args.by)
        raise AssertionError(tc)
    if c == "acp":
        from . import acp
        raise SystemExit(acp.serve())
    raise AssertionError(c)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "doctor" and not args.project:
        parser.error("--project is required for this command")
    _load_env(getattr(args, "project", None))
    try:
        result = _dispatch(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "type": exc.__class__.__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    if result.get("tool") == "toolbox-run" and result.get("returncode", 0) != 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
