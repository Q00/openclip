# Changelog

## v0.2.2 — 2026-07-11

### Fixed
- Replaced the `skills/oc*` directory symlinks with real, self-contained skill
  directories. `npx skills add Q00/openclip` now discovers all 14 OpenClip
  skills instead of only `oc-thumbnail-designer`.
- Kept the import package version in sync with distribution metadata; the
  previously published CLI reported the stale internal version `0.1.0`.

### Added
- `oc --version` and agent-readable `oc doctor [--real-run]` setup checks so
  Codex can identify stale CLI installs, missing ffmpeg/ffprobe, and missing
  API credentials before starting a flow.
- CI regression coverage requiring the public skills catalog to use real
  directories and bundle the orchestrator flows/tool reference.

## v0.2.1 — 2026-07-07

### Changed
- PyPI distribution is named **`openclip-agent`** (`pip install openclip-agent`)
  — the `openclip` name is claimed on PyPI. Import package (`openclip`) and
  CLIs (`oc`, `openclip`) are unchanged. First release published to PyPI.

## v0.2.0 — 2026-07-07

Designed thumbnails and a personalization loop: the harness now remembers what
the director likes and gets better every round.

### Added
- **Thumbnail pro path** (`oc thumbnail`): `--persona <photo|dir>` preserves
  the real speaker's identity via gpt-image edit; `--style
  clean|editorial|bold|keynote` curated art-direction presets; structured
  gpt-image-2 prompt builder (labeled Scene/Subject/Details/Change+Preserve/
  Constraints slots, reference images labeled by role, photography facts
  instead of quality words, anti-slop constraint block); `--prompt-note` for
  per-render art direction; `--quality low|medium|high`
- **`--composite`** — the no-AI path: rembg cutout of the real persona photo
  on a flat studio background with a measured headline budget. Zero generated
  pixels, zero cost, instant
- **`--render-text`** — let gpt-image-2 typeset the headline itself (crisper
  single-pass design; the designer contract mandates a character-by-character
  spelling check per render)
- **Local typography engine**: heavy CJK-capable font stack, `|` line breaks
  and `*word*` accent markup, gradient scrim or print-cover dark text,
  width-fit autoscaling — no more black-box captions
- **`oc taste`** (`show|note|evolve|revert`) — GEPA-style learned taste
  memory per domain: human verdicts accumulate against the active guidance
  generation; an agent reflects them into the next generation with lineage,
  per-generation scoreboards, and rollback. Storage resolves
  `$OPENCLIP_HOME` → repo `toolbox/` (team opt-in) → `~/.openclip` (plugin
  default)
- **`oc-thumbnail-designer`** worker: taste-first design loop with an
  anti-slop self-review checklist and gpt-image-2 prompting rules, shipped
  for Claude Code, Codex, and the skills catalog

### Fixed
- Relative `--out` paths now resolve against the project root on every verb
  (they used to land in the process CWD, contradicting the flow docs)
- `input_fidelity` is only sent to models that accept it (gpt-image-2 rejects
  it; identity fidelity is always-on there)
- The SubagentStop evidence gate now covers `oc-thumbnail-designer`, with
  drift-guard tests asserting every evidence-demanding contract is gated and
  both runtimes wire the same hook

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
