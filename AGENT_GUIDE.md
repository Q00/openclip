# Agent Guide — OpenClip video harness

Read this before acting on a video request. It routes you to the right flow and
tells you how to fan out. Works for **Claude Code** and **Codex**.

## What this is

An agent-orchestrated video harness. There is **no Python orchestrator** — the
agent (you) is the control plane. Python ships composable tools (`oc` CLI)
and project state; YAML manifests declare the flows; Markdown role files define
the worker subagents you spawn.

## First action: route by intent

| The user wants… | Flow | First step |
|-----------------|------|------------|
| transcribe + cut-edit a long / LRF video | `flows/flow1-cutedit.yaml` | proxy (if .LRF) → ingest |
| N videos → one longform + hook shorts | `flows/flow3-assemble.yaml` | per-video prep (widest fan-out) |
| just shorts from one long video | `flows/flow2-shorts.yaml` | ingest → stt → hooks |
| thumbnails matched to hooks | `flows/flow4-thumbnail.yaml` | one thumbnail-artist per hook |

Open the manifest. Each stage names its worker, fan-out width, exact tool call,
and success criteria.

## How to fan out

- **Claude Code:** spawn workers with the `Agent` tool, `subagent_type` = worker
  name (`oc-stt-worker`, `oc-cut-proposer`, …). Put all spawns for a
  stage in ONE turn so they run concurrently. Worker contracts: `.claude/agents/`.
- **Codex (repo clone):** invoke the matching skill under `.agents/skills/oc-<role>/`.
  **Codex (skills install):** the same contracts are installed as skills named
  `oc-<role>` in your skill store — invoke them by name.
  Spawn parallel sub-tasks per unit where your runtime supports it; otherwise
  loop the units but keep each unit's contract identical.

The fan-out unit per stage:

| Stage | Unit | Width |
|-------|------|-------|
| stt | one audio chunk | `chunk_count` |
| cut_debate | one transcript section × 2-3 lenses | `sections × lenses`, then 1 judge/section |
| find_hooks | one transcript section | `sections` |
| render_shorts | one chosen hook (clip + caption + thumbnail) | `K` |
| thumbnails | one hook/deliverable | `K` |
| prep (flow 3) | one source video | `len(videos)` |

## Human steering (the director is in the loop)

This is a steerable harness, not an autopilot. The human stays in control:

- Before each wave, run `oc --project <P> status` and read `open_steering`. Inject
  every matching directive into the workers' assignments (the `STEERING:` line).
- After each wave — especially `cut_debate`, `find_hooks`, `assemble_longform` —
  surface what the workers proposed and invite steering before you commit a render.
- The human steers with `oc steer --note "..." --scope <global|stage|section|id>`.
  Apply it by re-dispatching only the affected unit, then `oc steer-resolve --id <directive-id>`.
- Steering outranks a worker's default judgment and outranks the evidence gate's
  caution — but a steered render still gets verified.
- Taste is remembered, not re-litigated: creative verdicts (thumbnails today) are
  recorded with `oc taste note --domain <d> --verdict liked|disliked` and, once
  enough accumulate, reflected into the next guidance generation with
  `oc taste evolve` (see tools-reference). Workers read `oc taste show` BEFORE
  designing, so the harness gets more personalized every round.

## Verification honesty (what the gates do and don't prove)

- `oc verify` is the **mechanical** gate only (`mechanical_only: true`): file /
  duration / aspect / audio-not-silent / last-frame-not-black / SRT valid /
  SRT-within-video. A `confirmed` does NOT prove editorial quality — spawn an
  `oc-verifier` to probe cut boundaries, hook strength, caption↔audio match.
- The `SubagentStop` evidence hook only enforces on registered `oc-*` subagent
  types. **Spawning a render worker as `general-purpose` bypasses the gate** — use
  the real `oc-*` `subagent_type` for any deliverable you want mechanically gated.
- Learned tools run in a **scrubbed env** (no OPENAI key/secrets). A tool becomes
  **shared** only via `oc toolbox promote` (clean re-verify + static deny-list scan
  + `oc-tool-auditor` `--reviewed`). Nothing auto-promotes.

## Verify before you advance (non-negotiable)

A worker's "done" is a **claim**, not proof. Before checkpointing a stage:

1. Confirm artifacts exist and are non-trivial (`ls`, `ffprobe` duration > 0,
   `segment_count > 0`, SRT has cues).
2. Check the stage's `success` criteria from the manifest.
3. For creative stages (cut decisions, hook picks, final assembly), run a quick
   adversarial self-review or a human-approval gate — assume the first pass
   missed something and look for the strongest counterexample.
4. If a result is ack-only, thin, or fails a check, re-spawn a **smaller** unit
   rather than trusting it.

Then write the stage flag to `<project>/project.json` and continue. **Resumption
is real, not decorative:** `cut`/`clip`/`concat` record a keyed ledger event, so
re-running the same flow after an interruption SKIPS already-rendered units
(`resumed: true`) and only does what's missing. Call `oc resume` to see completed
vs missing units before re-dispatching; pass `--force` to redo one deliberately.

## Guardrails

- Never transcribe/render a long video in one linear pass — fan out.
- Workers return JSON; you hold the plan.
- Real runs: `OPENAI_API_KEY` set, `OPENAI_BASE_URL` unset (a proxy base url
  breaks Whisper/image).
- Generated media stays out of git.

## Keeping Claude + Codex in sync

Canonical sources: `agents/*.md` + `skills/oc/`. Mirrors in `.claude/` and
`.agents/` are generated. After editing a source: `python3 scripts/sync_agents.py`
(`--check` in CI). Never hand-edit a mirror.
