# OpenClip

OpenClip is a local, open-source video clipping harness. It turns one long video into short-form candidates, long-form highlight candidates, a cut-edited source video, multilingual subtitles, thumbnails, and review packets for editorial QA.

It is designed for creators and teams who want a repeatable workflow instead of a one-off script:

- transcript-first candidate selection
- 30-60 second vertical shorts
- 8-12 minute long-form candidates
- cut-edited original output with silence/repetition removal
- SRT subtitles for `en`, `ko`, `es`, `ja`, and `zh-Hans`
- optional burned-in Korean subtitles for shorts
- GPT Image thumbnails for every short and long-form candidate
- manifest, EDL, playback checks, and Codex subagent review packets

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

- **Tools:** `oc --project <DIR> <cmd>` — `proxy, ingest (--start offset), stt,
  transcript-merge, probe, cut, clip, subtitle, thumbnail, burn-srt, concat,
  verify, status, steer`. Each prints one JSON line. See
  `skills/oc/tools-reference.md`.
- **Human steering:** `oc steer --note "..." --scope <global|stage|section|id>`.
  The orchestrator reads `oc status` open directives before every wave and
  injects them into the workers. The director is always in the loop.
- **Evidence gate:** an independent `oc-verifier` checks every render against
  observable evidence and adversarial failure classes; only a `confirmed` verdict
  advances. A `SubagentStop` hook blocks "done without evidence".
- **Dual runtime:** Claude Code (`.claude/agents`, `.claude/skills/oc`) and Codex
  (`.agents/skills/oc*`) are generated from one source (`agents/*.md` +
  `skills/oc/`) via `python3 scripts/sync_agents.py`.

Quick offline sanity check:

```bash
oc --project out/demo ingest --input demo.mp4 --max-seconds 60
oc --project out/demo stt --chunk 0 --mock
oc --project out/demo transcript-merge
oc --project out/demo status
```

See `docs/HARNESS.md` for the full design.

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

Installs the orchestrator skill + all 12 worker skills into Claude Code, Codex,
Cursor, and [70+ other agents](https://github.com/vercel-labs/skills):

```bash
npx skills add Q00/openclip
```

Then install the `oc` CLI once (the skill also self-checks and offers this on
first use):

```bash
uv tool install "git+https://github.com/Q00/openclip"
```

Open your agent and say "이 영상 쇼츠 만들어줘" (or invoke the `oc` skill). The
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

## Quick Start

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

## Verification

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

## Review Workflow

OpenClip creates self-contained Codex subagent packets under `analysis/subagent_packets/`.

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
