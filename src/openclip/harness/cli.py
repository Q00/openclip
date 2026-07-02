"""``oc`` CLI — the tool surface subagents call via Bash.

Every subcommand prints a single JSON object to stdout so an agent can parse the
result. Errors print ``{"error": ...}`` to stdout and exit non-zero.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

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
    p.add_argument("--project", required=True, help="Project directory holding state + artifacts")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("proxy", help="LRF/LRV low-res proxy -> mp4")
    sp.add_argument("--input", required=True)
    sp.add_argument("--scale", type=int, default=640, help="target height; 0 = stream copy")
    sp.add_argument("--out")

    sp = sub.add_parser("ingest", help="split source audio into STT fan-out chunks")
    sp.add_argument("--input", required=True)
    sp.add_argument("--max-seconds", type=float, default=None)
    sp.add_argument("--start", type=float, default=0.0, help="start offset (skip silent intros)")

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

    sp = sub.add_parser("thumbnail", help="hook-matched thumbnail (representative frame + title, or generated)")
    sp.add_argument("--input", required=True)
    sp.add_argument("--start", type=float, required=True)
    sp.add_argument("--end", type=float, required=True)
    sp.add_argument("--out")
    sp.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    sp.add_argument("--title", default=None)
    sp.add_argument("--at", type=float, default=None, help="frame time (default = window midpoint)")
    sp.add_argument("--generate", action="store_true", help="use gpt-image instead of a frame grab")
    sp.add_argument("--from-frame", action="store_true", help="use the grabbed frame as generation reference")
    sp.add_argument("--model", default="gpt-image-2")
    sp.add_argument("--mock", action="store_true")

    sp = sub.add_parser("burn-srt", help="hard-burn an SRT into a video")
    sp.add_argument("--input", required=True)
    sp.add_argument("--srt", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--font-size", type=int, default=22)
    sp.add_argument("--margin-v", type=int, default=40)

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
    t.add_argument("--selftest", default=None, help="arg string; script must exit 0 to register")
    t.add_argument("--by", default="agent")
    t = tbsub.add_parser("run", help="run a learned tool (args after --)")
    t.add_argument("--name", required=True)
    t.add_argument("args", nargs="*", help="args passed to the tool")
    t = tbsub.add_parser("show", help="print a learned tool's source + usage")
    t.add_argument("--name", required=True)
    t = tbsub.add_parser("promote", help="gate a local tool into SHARED memory")
    t.add_argument("--name", required=True)
    t.add_argument("--reviewed", action="store_true", help="human/auditor approved (required to flip to shared)")
    t.add_argument("--by", default="human")
    tbsub.add_parser("learnings", help="list shared learnings (promoted knowledge)").add_argument("--query", default=None)
    t = tbsub.add_parser("remove", help="delete a learned tool")
    t.add_argument("--name", required=True)

    ap = sub.add_parser("acp", help="Agent Client Protocol adapter (drive the harness from an ACP client)")
    ap.add_subparsers(dest="acp_command", required=True).add_parser("serve", help="serve ACP JSON-RPC over stdio")

    return p


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    c = args.command
    if c == "proxy":
        return tools.proxy(args.project, args.input, scale=(args.scale or None), out=args.out)
    if c == "ingest":
        return tools.ingest(args.project, args.input, max_seconds=args.max_seconds, start=args.start)
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
                          out=args.out, clip_id=args.id, burn_srt=args.burn_srt, force=args.force)
    if c == "subtitle":
        return tools.subtitle(args.project, start=args.start, end=args.end, out=args.out,
                              relative=not args.absolute, translate_to=args.translate_to,
                              model=args.model, mock=args.mock, max_cue_seconds=args.max_cue,
                              max_cue_chars=args.max_chars)
    if c == "thumbnail":
        return tools.thumbnail(args.project, args.input, args.start, args.end, out=args.out,
                               aspect=args.aspect, title=args.title, at=args.at, generate=args.generate,
                               from_frame=args.from_frame, model=args.model, mock=args.mock)
    if c == "burn-srt":
        return tools.burn_srt(args.project, args.input, args.srt, args.out,
                              font_size=args.font_size, margin_v=args.margin_v)
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
            return toolbox.toolbox_run(args.name, args.args)
        if tc == "show":
            return toolbox.toolbox_show(args.name)
        if tc == "promote":
            return toolbox.toolbox_promote(args.name, reviewed=args.reviewed, promoted_by=args.by)
        if tc == "learnings":
            return toolbox.toolbox_learnings(args.query)
        if tc == "remove":
            return toolbox.toolbox_remove(args.name)
        raise AssertionError(tc)
    if c == "acp":
        from . import acp
        raise SystemExit(acp.serve())
    raise AssertionError(c)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_env(getattr(args, "project", None))
    try:
        result = _dispatch(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "type": exc.__class__.__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
