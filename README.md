<div align="center">

![OpenClip — the agent-orchestrated video editing harness](docs/assets/banner.jpg)

### You direct. A fleet of parallel agents debates the cuts, renders, and proves every deliverable — shorts, long-form, subtitles, thumbnails from one long video.

*Python ships the tools, agents ship the judgment, the human ships the taste.*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![PyPI](https://img.shields.io/pypi/v/openclip-agent?label=pypi)](https://pypi.org/project/openclip-agent/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install openclip-agent
```

**[Website](https://contractplane.dev/openclip/)** · **[Design](docs/HARNESS.md)** · **[Tool reference](skills/oc/tools-reference.md)** · **[Agent guide](AGENT_GUIDE.md)**

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

OpenClip is also the first substantial media Domain Pack for
[ContractPlane](https://contractplane.dev): the same capabilities, private roles,
policies, evidence gates, and flow topology ship as a portable contract. Inspect
it with `oc domain-pack show` or export it with `oc domain-pack export --out pack`.

**Are you an AI agent reading this?** Start with [`llms.txt`](llms.txt), then
[`AGENT_GUIDE.md`](AGENT_GUIDE.md) — they route you to the right flow manifest
and worker contracts.

## Getting started — your first run

After installing (below), you don't run a pipeline — you talk to your agent.

**1. Open your agent** (Claude Code or Codex) in a folder with your video.

**2. Invoke the `oc` skill and say what you want:**

```
you    $oc make shorts from ./talk.mp4

agent  Reading flow2-shorts. Splitting audio into chunks and fanning out
       STT workers… transcript merged (110 min). Mining hooks across
       sections — 6 candidates ranked. I'll cut the top 3 as 9:16 shorts
       with burned captions and a thumbnail each. Approve the hook list
       before I render?  [you: yes, drop #4]
       Rendering… each clip cleared the evidence gate (duration, aspect,
       audio, caption timing). Done — see out/talk/shorts/.
```

The orchestrator checks in at the real decision points (which hooks, which
cuts, which thumbnail) and blocks any "done" that has no evidence behind it.

**3. Collect the outputs.** Everything lands under your project directory
(here `out/talk/`):

| Folder | What's in it |
| --- | --- |
| `shorts/` | vertical `.mp4` clips with burned captions |
| `thumbnails/` | one designed thumbnail per deliverable |
| `subs/` | `.srt` sidecars (per language) |
| `evidence/` | the verifier's proof JSON for every render |

**Cost:** a full 110-minute talk (STT + several shorts + thumbnails) runs
around **$1** on OpenAI list prices. Add `--mock` anywhere and it costs **$0**
— ideal for a first offline trial (see [Cost](#cost) for the breakdown).

### Prefer the CLI, no agent?

Every step the agents take is a plain `oc` command. This sequence needs no API
key and costs nothing — STT runs in `--mock`, and the cut and thumbnail are
local ffmpeg work (no OpenAI call):

```bash
oc --project out/talk ingest --input talk.mp4 --max-seconds 120
oc --project out/talk stt --chunk 0 --mock
oc --project out/talk transcript-merge
oc --project out/talk clip --input talk.mp4 --start 30 --end 75 --aspect 9:16 --id s1
oc --project out/talk thumbnail --input talk.mp4 --start 30 --end 75 --title "The one trick"
oc --project out/talk status
```

Have a photo of the speaker? Swap the thumbnail line for the designed no-AI
cutout — still free, still offline after a one-time model download:
`… thumbnail --composite --persona speaker.jpg --style editorial --title "…"`.

`oc --help` is the authoritative command list. See
[`skills/oc/tools-reference.md`](skills/oc/tools-reference.md) for every verb.

## What it produces

- 30-60 second **vertical shorts** with burned, word-timed captions
- 8-12 minute **long-form candidates** that end on a payoff, not mid-clause
- a **cut-edited original** (silence/filler/repetition debated out, not just detected)
- **SRT subtitles** for `en`, `ko`, `es`, `ja`, `zh-Hans`
- **designed thumbnails** — real speaker identity preserved via `--persona`,
  curated `--style` presets, a zero-cost no-AI `--composite` cutout, or a
  gpt-image render; the harness learns your channel's taste over rounds
  (`oc taste`)
- a manifest, EDL, evidence files, and a resumable ledger for every run

**See it, don't take our word:** [docs/examples/](docs/examples/) holds real
artifacts from a 109-minute run — a captioned short frame, a thumbnail, the
transcript slice behind a hook, the SRT, the 10/10 evidence JSON, and the
resume ledger.

## Install

Prerequisites for every mode: `ffmpeg`/`ffprobe` on PATH, Python 3.11+, and an
`OPENAI_API_KEY` for real runs (mock runs need no key).

**Which install do you want?**

| You are… | Install | You get |
| --- | --- | --- |
| a **Claude Code** user | plugin (B) | subagent types + the evidence-gate hook |
| on **Codex / Cursor / another skills-protocol agent** | `npx skills add` (A) | the orchestrator + worker skills |
| **just the CLI** (no agent) | PyPI (`uv tool install`) | the `oc` command only |

All three can be combined — the skills/plugin bundle the agents, the CLI ships
the `oc` tools they call.

### A. Skills catalog, any agent (recommended)

For Codex, Cursor, and [any skills-protocol agent](https://github.com/vercel-labs/skills).
Installs the orchestrator plus every worker skill:

```bash
npx skills add Q00/openclip
```

The default command discovers all **14** OpenClip skills (the `oc`
orchestrator plus 13 role contracts); no `--full-depth` flag is required.

Then install the `oc` CLI once (the skill self-checks and offers this on first
use):

```bash
uv tool install openclip-agent      # or: pip install openclip-agent
oc --version
oc doctor
```

Open your agent and invoke *`$oc make shorts from this video`*. Natural-language
requests also work, but the explicit skill call is the most reliable first run.
The skill folder bundles the flow manifests
and tool reference, so it works outside the repo.

### B. Claude Code plugin (adds subagents + the evidence hook)

For Claude Code users. Registers the `oc-*` subagent types and the
`SubagentStop` evidence gate (skill-only installs run workers as
general-purpose subagents without the hook):

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

The `oc` CLI still comes from `uv tool install openclip-agent` above.

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

### C. Just the CLI (PyPI)

If you only want the `oc`/`openclip` tools with no agent:

```bash
uv tool install openclip-agent      # or: pip install openclip-agent
```

### D. Repo clone (development)

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

Open Claude Code or Codex at the repo root — agents, skills, commands, and hooks
load automatically. For real OpenAI runs, set a key in your shell (or copy
`.env.example` to `.env`; never commit real keys):

```bash
export OPENAI_API_KEY="..."
```

## Agent Harness (`oc`)

Instead of a fixed workflow, an orchestrator agent reads a flow manifest and
fans out worker subagents in parallel while the human steers every creative
decision. Thirteen role definitions live in [`agents/`](agents/): one
orchestrator plus twelve specialized workers.

Four flows:

1. **`flows/flow1-cutedit.yaml`** — LRF/LRV proxy → parallel STT → a **cut-editing debate** (proposers argue filler/pacing/narrative lenses, a judge reconciles) → cut-edited original + subtitles.
2. **`flows/flow2-shorts.yaml`** — one long video → parallel STT → hook mining → captioned 9:16 shorts + thumbnails.
3. **`flows/flow3-assemble.yaml`** — weave N videos into one longform, then mine its hooks into shorts (each with captions + a thumbnail).
4. **`flows/flow4-thumbnail.yaml`** — thumbnails matched to each hook: a frame with a burned headline, and/or a gpt-image render driven by the hook's caption.

Key pieces:

- **One public skill:** users invoke `$oc`; the orchestrator selects every
  internal `oc-*` worker, manifest, verifier, and toolbox action.
- **Tools:** `oc --project <DIR> <cmd>` — `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, taste, acp`. Each prints one JSON line;
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
- **Capability promotion:** deterministic gaps start as audited local toolbox
  tools. After representative runs, `oc toolbox propose` creates a PR packet;
  branch/push/PR actions happen only after explicit user approval.

For a runnable offline sanity check, see the [CLI sequence](#prefer-the-cli-no-agent)
above; `docs/HARNESS.md` has the full design.

### New in v0.2: designed thumbnails + learned taste

**Designed thumbnails** (`oc thumbnail`) look art-directed, not frame-grabbed:
`--persona <photo|dir>` preserves the **real speaker's identity** (gpt-image
edit); `--style clean|editorial|bold|keynote` picks a curated preset;
`--composite` is the **no-AI path** (rembg cutout on a studio background with a
typeset headline — zero generated pixels, **zero cost**, instant);
`--render-text` lets gpt-image-2 typeset the headline itself (probabilistic —
the contract verifies spelling every render); `--prompt-note "..."` adds
per-render art direction.

**`oc taste`** (`show|note|evolve|revert`) is a **personalization loop** — the
harness learns your channel's look. You record verdicts on rendered thumbnails
(`taste note`); an agent reflects them into the **next guidance generation**
(`taste evolve`) with per-generation scoreboards, lineage, and rollback
(`taste revert`) when a newer generation scores worse. Guidance is kept per
domain; storage resolves `$OPENCLIP_HOME` → the repo's `toolbox/` (team opt-in)
→ `~/.openclip` (plugin default).

## Cost

Rough OpenAI list-price ballparks — a 110-minute talk end-to-end (full STT,
5 shorts with burned captions, 2 long-form candidates, thumbnails) lands around
**$1**: whisper-1 ≈ $0.006/min of audio (~$0.66 for 110 min), gpt-image-2
≈ $0.03-0.07 per generated thumbnail (frame-grab and `--composite` thumbnails
are free), gpt-4o-mini subtitle translation is fractions of a cent per clip.
`--mock` runs cost $0, and the resume ledger never re-bills completed
STT/renders.

## Requirements & status

- Python 3.11+, `uv`, and `ffmpeg`/`ffprobe` on PATH
- OpenAI API key for real runs (mock runs call no external APIs)

OpenClip is early-stage software. It is usable locally, but APIs, output
schemas, and review packet formats may change before a stable release.

## Troubleshooting

- **`ffmpeg`/`ffprobe: command not found`** — install ffmpeg and make sure both
  binaries are on your `PATH` (`ffmpeg -version` should print). Every render
  path shells out to them.
- **`OPENAI_API_KEY` missing** — set it for real runs (`export OPENAI_API_KEY=...`).
  You don't need one for `--mock`: mock mode makes no network calls.
- **`OPENAI_BASE_URL` must be unset for real runs** — a CLI-proxy base URL
  breaks the Whisper and image calls. Unset it (`unset OPENAI_BASE_URL`) before
  a real run.
- **First `--composite` run pauses** — it downloads the rembg background-removal
  model once, then runs fully offline. Needs `uvx` (from `uv`) on PATH.
- **Real run "succeeds" but a file is missing** — that can't ship: the evidence
  gate only advances on a `confirmed` verdict. Check the `evidence/*.json` for
  the failing deliverable.

<details>
<summary><strong>Legacy one-shot pipeline (<code>openclip run</code>)</strong> — the original fixed pipeline, still supported</summary>

> **Repo clone (mode D) only.** This is the original fixed pipeline that predates
> the agent harness; the harness above is the recommended path. After
> `uv tool install` use `openclip run ...` directly instead of `uv run`.

### Quick start

Run with real OpenAI services:

```bash
uv run openclip run /path/to/input.mp4 --out ./out --strategy-approved
```

Generate all viable short and long candidates with English subtitles:

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --strategy-approved \
  --all-short-candidates \
  --all-long-candidates \
  --subtitle-langs en
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

### Outputs

Each run writes under `OUT_DIR/{input_basename}/`. Typical outputs include
`shorts/*.mp4`, `long/*.mp4`, `edited/edited_original.mp4`, per-language SRTs
(`*.en.srt`, `*.ko.srt`, `*.es.srt`, `*.ja.srt`, `*.zh-Hans.srt`),
`*.thumbnail.png`, `manifest.json`, and `analysis/` (candidate_selection.json,
edl.json, takes_packed.md, playback_checks/, subagent_packets/). Generated
media, local sources, `.env`, virtualenvs, caches, and `out/` are gitignored.

### Verification

These scripts ship in the repo tree, not the installed package. Harness runs are
verified differently: `oc verify` + the `oc-verifier` agent (see `docs/HARNESS.md`).

```bash
# validate an existing run
python3 codex/skills/openclip/scripts/verify_run_artifacts.py ./out/example/input_basename

# parallel playback/decode gate
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename --workers 6 --full-decode --write-manifest

# regenerate Codex subagent review packets
python3 codex/skills/openclip/scripts/build_subagent_packets.py ./out/example/input_basename
```

### Review workflow

The legacy pipeline creates self-contained Codex subagent packets under
`analysis/subagent_packets/`. The review graph is: `collect` (editors gather
independent content claims) → `verify` (continuity/playback/artifact gates) →
`design` (thumbnail fit) → `adversarial` (retention critic) → `synthesize`
(final gate approves only after every lane has evidence). Subagent `PASS`
results are claims, not proof — the root thread or release process must verify
cited paths, manifests, and playback evidence before publishing.

</details>

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

## Security & privacy

OpenClip processes local media and can send audio, transcript text, subtitle
text, and thumbnail prompts/reference frames (including persona photos) to
OpenAI when not using `--mock`. Do not run real provider mode on private,
regulated, or third-party media unless you have the right to process it with the
configured providers. Use `--mock` for local tests that must avoid network calls.

## License

MIT. See [LICENSE](LICENSE).
