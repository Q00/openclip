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

## Status

OpenClip is early-stage software. It is usable locally, but APIs, output schemas, and review packet formats may change before a stable release.

## Requirements

- Python 3.11+
- `uv`
- `ffmpeg` and `ffprobe`
- OpenAI API key for real runs

Mock runs do not call external APIs and are useful for development.

## Install

```bash
git clone <repository-url> openclip
cd openclip
uv sync --extra dev
```

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
