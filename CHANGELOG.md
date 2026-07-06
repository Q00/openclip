# Changelog

## v0.1.0 — 2026-07-06

First public release: the agent-orchestrated harness.

### Added
- **`oc` CLI** — composable JSON-in/JSON-out video tools: `proxy, ingest, stt,
  transcript-merge, probe, cut, clip, subtitle, thumbnail, burn-srt, concat,
  verify, status, resume, steer, steer-resolve, toolbox, acp`
- **Four flows** (`flows/*.yaml`): cut-edit with a proposer/judge debate,
  shorts from hooks, multi-video assembly, hook-matched thumbnails
- **13 agent roles** (orchestrator + 12 workers) shipped as Claude Code
  subagents, Codex skills, and an `npx skills add Q00/openclip` catalog
- **Verification stack**: mechanical evidence gate (`oc verify` — duration,
  aspect, video/audio streams, silent-audio, relative black-tail, SRT validity
  incl. empty/ordering, image decode/aspect/not-solid) + independent
  `oc-verifier` agent + `SubagentStop` evidence hook (Claude Code and Codex)
- **Resumable renders**: keyed `ledger.jsonl` events; re-runs skip completed
  proxy/cut/clip/concat/burn-srt/thumbnail work (`--force` to redo)
- **Human steering**: `oc steer` / `steer-resolve` with per-scope directives,
  advisory-locked against parallel workers
- **Self-extending toolbox** with a scrubbed-env, deny-list, human-reviewed
  promotion gate (`oc toolbox …`)
- Word-boundary clip end snapping; `--chunk-seconds`, `--max-chars`,
  `--timeout` tuning flags; ACP adapter with a deterministic `verify` flow

### Distribution
- `npx skills add Q00/openclip` (13 skills, flows bundled inside the oc skill)
- Claude Code plugin (`.claude-plugin/`, hooks via `${CLAUDE_PLUGIN_ROOT}`)
- `uv tool install "git+https://github.com/Q00/openclip@v0.1.0"`
