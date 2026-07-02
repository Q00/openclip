---
name: oc
description: >
  Agent-orchestrated video harness. Turn long video(s) into cut-edited originals,
  shorts, long-form, hook-matched thumbnails, and subtitled deliverables by
  fanning out subagents in parallel. Use when the user gives a video (incl.
  .LRF/.LRV proxy) and wants cuts, clips, subtitles, thumbnails, or assembly.
---

# OpenClip

A clean, agent-first video harness. **You are the orchestrator** (the
`oc-orchestrator` role). Python only provides composable tools (`oc`
CLI) and project state — all coordination and judgment live in you and the
worker subagents you spawn.

## Pick the flow

| User intent | Flow manifest |
|-------------|---------------|
| "transcribe + cut-edit this (LRF/long) video" | `flows/flow1-cutedit.yaml` |
| "weave these N videos into a longform + cut the hooks into shorts" | `flows/flow3-assemble.yaml` |
| "make thumbnails matched to the hooks" | `flows/flow4-thumbnail.yaml` |

Read the chosen manifest. It declares each stage's worker, fan-out width, the
exact tool call, and success criteria.

## The core idea: fan out, stay steerable, then verify

1. **Split** the work into independent units (5-min chunks, transcript sections,
   per-clip renders).
2. **Fan out** — spawn one worker subagent per unit, all in the same turn so they
   run concurrently. Use `subagent_type` = the worker name (`oc-stt-worker`,
   `oc-cut-proposer`, etc.).
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
`oc-verifier` (independent adversarial gate after every render), and
`oc-toolsmith` (authors + reuses learned tools so the harness self-improves).

Their full role contracts live in `agents/*.md` (Claude: `.claude/agents/`;
Codex: `.agents/skills/oc-*`).

## Tools

See `tools-reference.md`. Quick start (bounded, offline) to sanity-check setup:

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
