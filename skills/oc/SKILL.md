---
name: oc
description: >
  Primary public entry point for OpenClip. Use this skill instead of any oc-* worker
  whenever a user provides a video or asks for video editing, shorts/reels/clips,
  cut editing, captions/subtitles/translation, thumbnails, long-form assembly, or
  multi-video composition in any language. It also owns capability gaps: choose
  agent judgment vs a built-in oc command, reuse or author audited toolbox tools,
  and prepare a user-approved upstream proposal when a proven tool should reach
  other users.
---

# OpenClip

A clean, agent-first video harness. **You are the orchestrator** (the
`oc-orchestrator` role). Python only provides composable tools (`oc`
CLI) and project state — all coordination and judgment live in you and the
worker subagents you spawn.

This skill folder is **self-contained**: flow manifests live in `flows/` and the
tool reference in `tools-reference.md`, both **relative to this skill's base
directory** (works installed via `npx skills add`, as a Claude Code plugin, or
from a repo clone).

## ContractPlane Domain Pack

OpenClip is the first substantial media Domain Pack for
[ContractPlane](https://contractplane.dev). The portable contract is bundled at
`domain-pack/openclip.domain.yaml`; precompiled reference plans live under
`domain-pack/compiled/`, and all 13 complete worker contracts live under
`domain-pack/roles/`. Read the Domain Pack before routing, then use the existing
flow manifests for OpenClip-specific command details and compatibility.

The `shorts` plan is the first conformance fixture. ContractPlane v0.1 preserves
fan-out selectors and bindings but does not execute them; this orchestrator still
expands chunks, sections, and hooks into real worker units. `oc domain-pack show`
reports the bundled contract and `oc domain-pack export --out <DIR>` exports it
without requiring ContractPlane at runtime.

Do not confuse ContractPlane's Agent Contract Plane with `oc acp serve`, which
implements the existing editor-facing Agent Client Protocol transport.

## Public entry point

Users should only need one explicit invocation:

```text
$oc make three shorts from ./talk.mp4
```

Natural requests such as "edit this video", "add captions", or "make a thumbnail"
must enter through this skill too. Treat every sibling `oc-*` skill as an internal
worker role; users do not need to know worker names, toolbox commands, or flows.

On every first request in a session: run `oc --version`, run `oc doctor`, choose
the flow, then dispatch the narrow worker skills. Do not ask the user to select a
worker or manifest.

## Setup (check once per session, before the first tool call)

1. **`oc` CLI >= 0.2.4** — probe with `oc --version` (fallback:
   `python3 -m openclip.harness.cli --version` from a repo clone), then run
   `oc doctor`. If the CLI is missing or older, **ask the user for consent first**
   ("Install or upgrade the OpenClip CLI? It runs ffmpeg renders locally.") —
   never install software without an explicit yes. Then:
   ```bash
   uv tool install --force "openclip-agent>=0.2.4" \
     || pipx install --force "openclip-agent>=0.2.4" \
     || pip install --upgrade "openclip-agent>=0.2.4"
   ```
   Confirm with `oc --version && oc doctor`; every command below assumes both
   report a mock-capable setup.
2. **ffmpeg/ffprobe** on PATH (reported by `oc doctor`). Missing → tell the user:
   `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux). Do not proceed
   without it.
3. **`OPENAI_API_KEY`** set (env or a `.env` next to the project dir) and
   `OPENAI_BASE_URL` unset — needed for real STT/translation/gpt-image. Offline
   or dry runs: pass `--mock` to stt/subtitle/thumbnail instead. Run
   `oc doctor --real-run` before a paid run.

## Pick the flow

| User intent | Flow manifest (relative to this skill) |
|-------------|---------------------------------------|
| "transcribe + cut-edit this (LRF/long) video" | `flows/flow1-cutedit.yaml` |
| "just cut shorts from this one long video" | `flows/flow2-shorts.yaml` |
| "weave these N videos into a longform + cut the hooks into shorts" | `flows/flow3-assemble.yaml` |
| "make thumbnails matched to the hooks" | `flows/flow4-thumbnail.yaml` |

Read the chosen manifest. It declares each stage's worker, fan-out width, the
exact tool call, and success criteria. Manifest tool lines write `<P>` for the
project dir — **convention: `out/<input-basename>`** (e.g. `demo.mp4` →
`out/demo`) unless the user names one. In quick-start examples, substitute
`demo.mp4` with the user's actual video path.

## The core idea: fan out, stay steerable, then verify

1. **Split** the work into independent units (5-min chunks, transcript sections,
   per-clip renders).
2. **Fan out** — spawn one worker subagent per unit, all in the same turn so they
   run concurrently (see "Spawning workers" below).
3. **Steer** — before each wave read `oc status` for `open_steering` and inject
   matching directives into the workers; after each wave surface what they
   proposed and invite the human to steer before you commit a render.
4. **Merge** the workers' JSON results.
5. **Verify** before advancing: a worker's "done" is a claim — spawn an
   independent `oc-verifier` and require a `confirmed` verdict. Re-spawn a tighter
   unit if a result is thin, ack-only, or fails verification.
6. **Checkpoint** the stage in `project.json` (tools also append to
   `ledger.jsonl`), then continue.

The human is the director; you are the control plane. Speed comes from parallel
fan-out — never from skipping a creative decision the human hasn't seen.

## Capability gaps

When the requested capability is not a built-in verb, read `tool-lifecycle.md`
and classify the gap before acting:

- creative/editorial judgment → dispatch an agent;
- small deterministic local transform → reuse toolbox, then dispatch
  `oc-toolsmith` only if no healthy tool exists;
- reusable stateful capability needed by several flows → prepare an `oc` builtin
  proposal;
- network/browser/service/credential-heavy capability → dedicated integration,
  never an unreviewed learned script.

After a tool is independently audited, `oc toolbox propose` creates a PR packet.
It never pushes or opens GitHub state. Ask the user explicitly before any branch,
push, issue, or PR action, then use the packet's `PR_BODY.md`.

## Spawning workers

Worker role contracts are the sibling skills `../oc-<role>/SKILL.md` (installed
next to this skill). `.claude/agents/<role>.md`, `.agents/skills/oc-<role>/SKILL.md`,
and `skills/oc-<role>/SKILL.md` all carry the SAME contract — they are generated
mirrors of `agents/<role>.md`; use whichever your runtime resolves.

- **Claude Code with registered `oc-*` agents** (repo clone or plugin install):
  spawn with the Agent tool, `subagent_type` = the worker name
  (`oc-stt-worker`, `oc-cut-proposer`, …). Preferred — the SubagentStop
  evidence hook only enforces on registered `oc-*` types.
- **Skill-only installs** (`npx skills add`, no agent registration): read the
  worker's contract from `../oc-<role>/SKILL.md` and spawn a general-purpose
  subagent with that contract inlined at the top of its prompt. Behavior is
  identical; note the evidence hook does not gate these spawns, so treat the
  verifier's `confirmed` verdict as the only gate.
- **Codex:** invoke the sibling skill `oc-<role>` per unit; run units in
  parallel where the runtime supports it.

## The cut-editing debate (flow 1, the signature move)

Cuts are not decided by one voice. For each transcript section, spawn 2-3
`oc-cut-proposer` agents with different lenses — `filler` (tighten dead air),
`pacing` (keep energy), `narrative` (protect setup→payoff). They argue with
explicit rationale. Then a `oc-cut-judge` reconciles them into a final
keep-EDL (narrative coherence beats tightness; consensus dead-air always cut).
This produces cuts a single pass would miss.

## Workers (subagents)

`oc-proxy-converter`, `oc-stt-worker`, `oc-cut-proposer`,
`oc-cut-judge`, `oc-subtitle-agent`, `oc-hook-finder`, `oc-assembler`,
`oc-thumbnail-artist`,
`oc-verifier` (independent adversarial gate after every render),
`oc-toolsmith` (authors + reuses learned tools so the harness self-improves), and
`oc-tool-auditor` (adversarial promotion gate before a learned tool goes shared).

## Tools

See `tools-reference.md` (next to this file). Quick start (bounded, offline) to
sanity-check setup:

```bash
oc --project out/demo ingest --input demo.mp4 --max-seconds 60
oc --project out/demo stt --chunk 0 --mock
oc --project out/demo transcript-merge
```

## Rules

- Never transcribe/render a long video in a single linear pass — fan out.
- Workers return JSON, not prose; you hold the plan.
- Generated media stays out of git; only harness code + manifests are committed.
- Real runs need `OPENAI_API_KEY` set and `OPENAI_BASE_URL` unset.
