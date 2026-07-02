# OpenClip Agent Harness — design

OpenClip's harness is **sub-agent first and human-steered**. It exists because a
long video is too big for one linear pass and too creative for an autopilot. The
design answers two questions: *how do we go fast?* and *how does the human stay in
control?*

## Principles

1. **The agent is the control plane; Python is just tools.** There is no runtime
   orchestrator. A flow manifest (YAML) declares the stages; an orchestrator
   agent reads it, fans out workers, and merges results. All ffmpeg/Whisper work
   lives behind one composable CLI (`oc`), each subcommand JSON-in / JSON-out.

2. **Fan out, don't serialize.** Work is split into independent units — 5-minute
   audio chunks, transcript sections, per-clip renders — and one worker subagent
   runs per unit, concurrently. A 2-hour video is transcribed by N workers at
   once, not one stream. Serialize only on a real named dependency.

3. **The human is the director.** The harness is built to be steered, not to run
   away. Directives (`oc steer`) are read before every wave and injected into the
   workers; proposals are surfaced after every wave; creative decisions pause for
   approval. Steering outranks a worker's default judgment.

4. **A "done" is a claim, not proof.** Every render is checked by an independent
   verifier that probes observable evidence and the video-specific failure
   classes a success log hides (blank tail frames, duration drift, wrong aspect,
   cuts that clip mid-clause, invalid subtitles, stale renders). Only a
   `confirmed` verdict advances a stage.

5. **Debate beats a single voice.** Cuts aren't decided by one editor. For each
   section, proposers argue through different lenses — tighten filler, keep
   pacing, protect the narrative arc — and a judge reconciles them. The result is
   a cut a single pass would miss, and the human can steer the reconciliation.

6. **Resumable by event log.** Tools append to `ledger.jsonl` (events, not
   snapshots) and set stage flags in `project.json`. An interrupted run resumes
   from the last real fact (`oc status`) instead of redoing finished work.

## The shape of a run

```
flow manifest ──▶ orchestrator
                      │  read open steering
        ┌─────────────┼─────────────┐         (parallel wave)
        ▼             ▼             ▼
     worker        worker        worker        ← one per unit
        └─────────────┼─────────────┘
                      ▼  merge JSON
                 surface to human ◀── steer ──┐
                      ▼  (approved)           │
                  render / cut                │
                      ▼                       │
                 oc-verifier  ── needs-fix ───┘  (re-dispatch the unit)
                      ▼  confirmed
                 checkpoint ──▶ next stage
```

## Dual runtime: Claude Code + Codex

The same harness drives both runtimes from one source of truth:

- **Canonical:** `agents/*.md` (worker roles) + `skills/oc/` (orchestrator skill +
  tool reference). Edit these.
- **Generated mirrors:** `.claude/agents/` + `.claude/skills/oc/` (Claude Code),
  `.agents/skills/oc*` (Codex). Run `python3 scripts/sync_agents.py` after edits;
  `--check` fails CI on drift. Never hand-edit a mirror.
- **Routing:** `AGENTS.md` → `AGENT_GUIDE.md` (Codex), `.claude/` skills/commands
  (Claude). Hooks (`hooks/verify_evidence_hook.py`) are wired in both
  `.claude/settings.json` and `.codex/hooks.json`.

## Why not a fully automatic loop?

An auto-converging loop is tempting, but video is a director's medium. The harness
keeps the iterate-on-feedback shape (propose → render → evaluate → refine the weak
unit → re-verify) while putting the human at the wheel of every creative turn. The
machine parallelizes and proves; the person decides.
