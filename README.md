<div align="center">

![OpenClip — the agent-orchestrated video editing harness](docs/assets/banner.jpg)

### You direct. A fleet of parallel agents debates the cuts, renders, and proves every deliverable — shorts, long-form, subtitles, thumbnails from one long video.

*Python ships the tools, agents ship the judgment, the human ships the taste.*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

**[Website](https://wpti.dev/openclip/)** · **[Design](docs/HARNESS.md)** · **[Tool reference](skills/oc/tools-reference.md)** · **[Agent guide](AGENT_GUIDE.md)**

**English** | [한국어](README.ko.md) | [中文](README.zh-CN.md) | [日本語](README.ja.md) | [Español](README.es.md)

</div>

---

Open your agent (tested on Claude Code and Codex; installable to Cursor and any
agent speaking the [skills protocol](https://github.com/vercel-labs/skills)), point it at a video,
and say *"make shorts from this"*. The orchestrator agent reads a flow manifest,
**fans out worker subagents in parallel** (transcription, a cut-editing debate,
hook mining, captioning, thumbnails), and every render must survive an
**independent adversarial verifier** before it ships. You stay the director:
steer any decision mid-flight with `oc steer`.

**Are you an AI agent reading this?** Start with [`llms.txt`](llms.txt), then
[`AGENT_GUIDE.md`](AGENT_GUIDE.md) — they route you to the right flow manifest
and worker contracts.

## What it produces

- 30-60 second **vertical shorts** with burned, word-timed captions
- 8-12 minute **long-form candidates** that end on a payoff, not mid-clause
- a **cut-edited original** (silence/filler/repetition debated out, not just detected)
- **SRT subtitles** for `en`, `ko`, `es`, `ja`, `zh-Hans`
- **hook-matched thumbnails** (representative frame + headline, or gpt-image)
- a manifest, EDL, evidence files, and a resumable ledger for every run

**See it, don't take our word:** [docs/examples/](docs/examples/) holds real
artifacts from a 109-minute run — a captioned short frame, a thumbnail, the
transcript slice behind a hook, the SRT, the 10/10 evidence JSON, and the
resume ledger.

## Agent Harness (`oc`)

OpenClip now ships an **agent-orchestrated, human-steered harness** alongside the
original one-shot `openclip run` pipeline. Instead of a fixed workflow, an
orchestrator agent reads a flow manifest and **fans out worker subagents in
parallel** — so a long video is transcribed, debated, and rendered concurrently —
while the human steers every creative decision.

Four flows:

1. **`flows/flow1-cutedit.yaml`** — LRF/LRV proxy → parallel STT (one worker per
   chunk) → a **cut-editing debate** (proposers argue through filler/pacing/
   narrative lenses, a judge reconciles) → cut-edited original + subtitles.
2. **`flows/flow2-shorts.yaml`** — one long video → parallel STT → hook mining →
   captioned 9:16 shorts + thumbnails.
3. **`flows/flow3-assemble.yaml`** — weave N videos into one longform, then mine
   its hook moments into shorts (each short gets captions + a thumbnail).
4. **`flows/flow4-thumbnail.yaml`** — produce thumbnails matched to each hook: a
   representative frame with a burned headline, and/or a gpt-image generated
   thumbnail driven by the hook's caption.

Key pieces:

- **Tools:** `oc --project <DIR> <cmd>` — `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, acp`. Each prints one JSON line;
  `oc --help` is authoritative. See `skills/oc/tools-reference.md`.
- **Human steering:** `oc steer --note "..." --scope "global | <stage> | section:<a>-<b> | <deliverable_id>"`.
  The orchestrator reads `oc status` open directives before every wave and
  injects them into the workers. The director is always in the loop.
- **Evidence gate:** an independent `oc-verifier` checks every render against
  observable evidence and adversarial failure classes; only a `confirmed` verdict
  advances. A `SubagentStop` hook blocks "done without evidence".
- **Dual runtime:** Claude Code (`.claude/agents`, `.claude/skills/oc`) and Codex
  (`.agents/skills/oc*`) are generated from one source (`agents/*.md` +
  `skills/oc/`) via `python3 scripts/sync_agents.py`.

Quick offline sanity check (substitute `demo.mp4` with any short clip of yours):

```bash
oc --project out/demo ingest --input demo.mp4 --max-seconds 60
oc --project out/demo stt --chunk 0 --mock
oc --project out/demo transcript-merge
oc --project out/demo status
```

See `docs/HARNESS.md` for the full design.

## Cost (real runs)

Rough OpenAI list-price ballparks — a 110-minute talk end-to-end (full STT,
5 shorts with burned captions, 2 long-form candidates, thumbnails) lands around
**$1**: whisper-1 ≈ $0.006/min of audio (~$0.66 for 110 min), gpt-image-2
≈ $0.03-0.07 per generated thumbnail (frame-grab thumbnails are free),
gpt-4o-mini subtitle translation is fractions of a cent per clip. `--mock` runs
cost $0, and the resume ledger never re-bills completed STT/renders.

## Status

OpenClip is early-stage software. It is usable locally, but APIs, output schemas, and review packet formats may change before a stable release.

## Requirements

- Python 3.11+
- `uv`
- `ffmpeg` and `ffprobe`
- OpenAI API key for real runs

Mock runs do not call external APIs and are useful for development.

## Install

Prerequisites for every mode: `ffmpeg`/`ffprobe` on PATH, Python 3.11+, and an
`OPENAI_API_KEY` for real runs (mock runs need no key).

### A. One command, any agent (recommended)

Installs the orchestrator skill + all 12 worker skills into Claude Code and
Codex (tested), plus Cursor and [any skills-protocol agent](https://github.com/vercel-labs/skills):

```bash
npx skills add Q00/openclip
```

Then install the `oc` CLI once (the skill also self-checks and offers this on
first use):

```bash
uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

This installs code from the repository — pin to a release tag (shown) and check
the [release notes](https://github.com/Q00/openclip/releases) in sensitive
environments.

Open your agent and say *"make shorts from this video"* (any language works),
or invoke the `oc` skill directly. The
skill folder bundles the flow manifests and tool reference, so it works outside
the repo.

### B. Claude Code plugin (adds subagents + the evidence hook)

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

The plugin registers the `oc-*` subagent types and the `SubagentStop` evidence
gate (skill-only installs run workers as general-purpose subagents without the
hook). The `oc` CLI still comes from `uv tool install` above.

**Codex — enabling the evidence gate.** Skills install via mode A; to also get
the "done without evidence" gate in your own project, copy the two config files
from this repo and keep the hook script path valid:

```bash
mkdir -p .codex hooks
curl -fsSLo .codex/config.toml  https://raw.githubusercontent.com/Q00/openclip/main/.codex/config.toml
curl -fsSLo .codex/hooks.json   https://raw.githubusercontent.com/Q00/openclip/main/.codex/hooks.json
curl -fsSLo hooks/verify_evidence_hook.py https://raw.githubusercontent.com/Q00/openclip/main/hooks/verify_evidence_hook.py
```

`config.toml` sets `features.hooks = true` (required for Codex to load
`hooks.json`); the hook resolves via `${CODEX_PROJECT_DIR:-$PWD}`.

### C. Repo clone (development)

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

Open Claude Code or Codex at the repo root — agents, skills, commands, and hooks
load automatically.

For real OpenAI runs, set an API key in your shell:

```bash
export OPENAI_API_KEY="..."
```

You can also copy `.env.example` to `.env` for local development. Never commit real keys.

## Quick Start — legacy one-shot pipeline

> **Repo clone (mode C) only.** This is the original fixed pipeline that predates
> the agent harness; the harness above is the recommended path. After
> `uv tool install` use `openclip run ...` directly instead of `uv run`.

Run with real OpenAI services:

```bash
uv run openclip run /path/to/input.mp4 --out ./out --strategy-approved
```

Generate all viable short and long candidates and burn Korean subtitles into shorts:

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --strategy-approved \
  --all-short-candidates \
  --all-long-candidates \
  --burn-short-ko-subtitles
```

Run a bounded local smoke test without network calls:

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --mock-openai \
  --max-source-seconds 660 \
  --shorts 1 \
  --long-candidates 1 \
  --strategy-approved
```

## Outputs

OpenClip writes each run under:

```text
OUT_DIR/{input_basename}/
```

Typical outputs include:

- `shorts/*.mp4`
- `long/*.mp4`
- `edited/edited_original.mp4`
- `*.en.srt`, `*.ko.srt`, `*.es.srt`, `*.ja.srt`, `*.zh-Hans.srt`
- `*.thumbnail.png`
- `manifest.json`
- `analysis/candidate_selection.json`
- `analysis/edl.json`
- `analysis/takes_packed.md`
- `analysis/playback_checks/*`
- `analysis/subagent_packets/*`

Generated media, local source videos, `.env`, virtualenvs, caches, and `out/` are ignored by git. Keep rendered outputs out of commits.

## Verification — legacy pipeline (repo clone only)

> These scripts ship in the repo tree, not the installed package. Harness runs
> are verified differently: `oc verify` + the `oc-verifier` agent (see
> `docs/HARNESS.md`).

Validate an existing run:

```bash
python3 codex/skills/openclip/scripts/verify_run_artifacts.py \
  ./out/example/input_basename
```

Run a parallel playback/decode gate:

```bash
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename \
  --workers 6 \
  --full-decode \
  --write-manifest
```

Regenerate Codex subagent review packets for an existing run:

```bash
python3 codex/skills/openclip/scripts/build_subagent_packets.py \
  ./out/example/input_basename
```

## Review Workflow — legacy pipeline

OpenClip's legacy pipeline creates self-contained Codex subagent packets under `analysis/subagent_packets/`.

The review graph is:

1. `collect`: shorts and long-form editors gather independent content claims.
2. `verify`: continuity, playback, and artifact gates check files and manifests.
3. `design`: thumbnail director checks prompt and image fit.
4. `adversarial`: retention critic looks for likely viewer drop-off.
5. `synthesize`: final gate reviewer approves only after every lane has evidence.

Subagent `PASS` results are treated as claims, not proof. The root thread or release process must verify cited paths, manifests, and playback evidence before publishing outputs.

## Development

```bash
uv sync --extra dev
uv run pytest
python3 -m compileall -q src codex/skills/openclip/scripts tests
```

Before opening a PR or publishing a branch, run a secret scan:

```bash
rg -n -e "[s]k-proj-" -e "OPENAI_API_KEY\\s*=\\s*[s]k-" -e "OPEN_API_KEY\\s*=\\s*[s]k-" \
  --glob '!out/**' \
  --glob '!.env' \
  --glob '!demo.mp4' \
  --glob '!lecturer/**' \
  --glob '!.venv/**' .
```

## Security And Privacy

OpenClip processes local media and can send audio, transcript text, subtitle text, and thumbnail prompts/reference frames to OpenAI when not using `--mock-openai`.

Do not run real provider mode on private, regulated, or third-party media unless you have the right to process it with the configured providers. Use `--mock-openai` for local tests that must avoid network calls.

## License

MIT. See [LICENSE](LICENSE).
