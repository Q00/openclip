# OpenClip tool reference

Run `oc --version` to inspect the installed CLI and `oc doctor` to check Python,
ffmpeg/ffprobe, and API-key readiness. Every project tool is
`oc --project <DIR> <subcommand> [flags]` and prints ONE JSON object to stdout.
Errors print `{"error": ..., "type": ...}` and exit non-zero. Run from the repo
root (or after `uv sync` / `pip install -e .` so `oc` is on PATH; otherwise
`python3 -m openclip.harness.cli`).

`<DIR>` is the project state folder. Tools read/write:
`project.json`, `audio/`, `transcripts/`, `transcript.json|.md`, `analysis.json`,
`proxy/`, `clips|shorts/`, `subs/`, `edl/`, `out/`, `work/`.

| Subcommand | Purpose | Key flags |
|------------|---------|-----------|
| `doctor` | agent-readable local readiness check; does not need `--project` | `--real-run` (also require `OPENAI_API_KEY`) |
| `proxy` | LRF/LRV/heavy source → review mp4 (resumable) | `--input` `--scale 640` (`0`=stream copy) `--out` `--force` |
| `ingest` | split source audio into STT chunks | `--input` `--max-seconds` `--start` `--chunk-seconds 300` |
| `stt` | transcribe ONE chunk (fan-out unit) | `--chunk N` `--model whisper-1` `--mock` |
| `transcript-merge` | merge chunk transcripts → transcript.json + .md; reports `missing_chunks`/`complete` | — |
| `probe` | silence + scene-cut signals for cut debate | `--input` `--scene-threshold 0.4` |
| `cut` | apply keep-EDL → one mp4 (spans clamped + overlap-merged) | `--input` `--edl file.json` `--out` `--aspect source\|9:16` `--force` |
| `clip` | extract ONE range w/ aspect (shorts/hooks) | `--input` `--start` `--end` `--aspect 9:16` `--id` `--out` `--burn-srt` `--force` |
| `subtitle` | transcript slice → SRT (WORD-timed, clip-relative) | `--start` `--end` `--out` `--absolute` `--translate-to ko` `--max-cue 2.2` `--max-chars 18` `--mock` |
| `thumbnail` | hook-matched thumbnail: frame+title, `--composite` (no-AI: real persona cutout on flat bg + typeset headline — default look), or `--generate` (gpt-image scene w/ persona identity + style preset) | `--input` `--start` `--end` `--aspect 16:9\|9:16` `--title` (`\|`=line break, `*word*`=accent) `--at` `--composite` `--generate` `--from-frame` `--persona <photo\|dir>` `--style clean\|editorial\|bold\|keynote` `--quality` `--prompt-note "<art direction>"` `--render-text` (model typesets the headline — verify spelling every render) `--out` `--force` |
| `burn-srt` | hard-burn an SRT into a video (resumable) | `--input` `--srt` `--out` `--font-size` `--margin-v` `--force` |
| `concat` | normalize (fps/codec/stereo) + join clips → longform | `--inputs a.mp4 b.mp4 ...` `--out` `--force` |
| `verify` | mechanical evidence gate — video, image (png/jpg), or SRT deliverable | `--path` `--kind` `--expect-duration` `--expect-aspect 9:16` `--srt` `--tolerance` |
| `status` | stage flags + ledger + open steering directives | — |
| `resume` | completed renders (skippable) + missing STT chunks | — |
| `steer` | record a human steering directive for the next wave | `--note` `--scope global\|<stage>\|section:<a>-<b>\|<id>` `--stage` |
| `steer-resolve` | mark a steering directive addressed | `--id` |
| `toolbox list` | discover learned (agent-authored) tools | `--query` |
| `toolbox new` | register a new learned tool (self-test gated) | `--name` `--desc` `--file` `--lang` `--usage` `--selftest` `--by` |
| `toolbox run` | run a learned tool (args after `--`, scrubbed env) | `--name` `--timeout 600` `-- <args>` |
| `toolbox promote` | gate a local tool into SHARED memory | `--name` `--reviewed` `--by` |
| `toolbox learnings` | list promoted shared knowledge | `--query` |
| `toolbox show` / `remove` | print source+usage / delete a learned tool | `--name` |
| `taste show` | active taste guidance + generation scoreboard (read BEFORE designing) | `--domain thumbnail` |
| `taste note` | record one human verdict against the active guidance | `--domain` `--verdict liked\|disliked\|steer` `--note` `--ref` |
| `taste evolve` | reflect verdicts into the next guidance generation (2-phase) | `--domain` `--write <draft.md>` `--by` |
| `taste revert` | roll back to an archived generation that scored better | `--domain` `--to N` |
| `acp serve` | Agent Client Protocol adapter over stdio | (drive harness from a client) |

## Self-extending toolbox (self-improvement + shared memory)

Built-in verbs cover the common path. When you need something they don't,
`oc-toolsmith` authors a small script, verifies it with `--selftest` (must exit 0
to register), and it persists as a **local** tool in git-tracked `toolbox/`.

Tools become **shared memory** (reusable/recommended across sessions & people)
only through a gate: `oc toolbox promote` re-verifies in a **scrubbed env** (no
secrets reach learned tools), runs a **static deny-list scan** (network/shell/
fs-destroy/secrets), and requires **`--reviewed`** by `oc-tool-auditor` (adversarial).
Promotions append to `toolbox/learnings.jsonl`. Reliability (`success_rate`) is
tracked; unhealthy tools are flagged by `toolbox list`.

```bash
oc --project <P> toolbox list --query gif          # reuse before authoring
oc --project <P> toolbox run  --name gif-preview -- --input v.mp4 --start 10 --end 15 --out p.gif
oc --project <P> toolbox promote --name gif-preview --reviewed --by <auditor>
```

## Learned taste (GEPA-style personalization)

`taste` is the channel's remembered preference, per domain (`thumbnail`, …).
Storage resolves in three tiers so plugin installs work out of the box:
`$OPENCLIP_HOME/taste` if set → `<repo>/toolbox/taste/` when the repo already
carries a `toolbox/` (git-shareable team opt-in; this repo itself) →
`~/.openclip/taste/` otherwise (plugin default: taste follows the USER across
projects, never injects dirs into their repos). `taste show` prints the
resolved `storage`. The loop: workers read the
active guidance BEFORE designing (`taste show`), every human verdict is recorded
against the generation that produced it (`taste note`), and once enough
uncovered verdicts accumulate (`evolve_due: true`) an agent runs `taste evolve`
— phase 1 returns a reflection packet (guidance + verdicts + per-generation
scoreboard), the agent authors the next guidance generation, phase 2
(`--write draft.md`) commits it with lineage. Generations are archived, scored
by their liked/disliked ratio, and a regression is rolled back with
`taste revert --to N`. The agent is the mutation operator; the CLI is the
deterministic substrate + selection memory.

```bash
oc --project <P> taste show --domain thumbnail                  # before designing
oc --project <P> taste note --domain thumbnail --verdict liked \
  --ref thumbnails/s1.png --note "clean style + real-photo identity preservation worked"
oc --project <P> taste evolve --domain thumbnail                # reflection packet
oc --project <P> taste evolve --domain thumbnail --write /tmp/gen2.md
```

## ACP (Agent Client Protocol)

ACP is a **transport**, not memory. `oc acp serve` exposes the harness to an ACP
client (Zed, etc.) so it can drive deterministic flows and answer steering/render
gates via `session/request_permission`. Creative flows still need an LLM
orchestrator. Shared memory is the git toolbox, NOT ACP.

## Verification honesty

`verify` is the **mechanical** gate (`mechanical_only: true`): it checks file /
duration / aspect / **video-stream-present** / **audio-not-silent** /
**last-frame-not-black** / SRT validity (incl. empty-text + out-of-order cues) /
SRT-within-video, and for image deliverables decode / aspect / **not-solid-frame**.
A `confirmed` here does NOT prove editorial quality — an
`oc-verifier` agent must still probe cut boundaries, hook strength, and caption↔
audio match. Note: the `SubagentStop` evidence hook only enforces on registered
`oc-*` subagent types; **general-purpose spawns bypass it** — spawn the real
worker types for renders you want gated.

## Human steering

The human is the director. Drop a directive any time:

```bash
oc --project <DIR> steer --note "cut the intro hard; keep the symposium payoff" --scope cut_debate
```

`oc status` lists `open_steering`. The orchestrator reads it before every wave and
injects each matching directive into the workers' assignments; workers honor
steering over their own defaults. Resolve with `oc steer-resolve --id <id>`.

## Verdicts (from `verify` / the verifier agent)

`confirmed` (only pass) · `needs-fix` (nameable fix) · `needs-human-review`
(editorial judgment) · `false-positive` (claim was wrong). Only `confirmed`
advances a stage.

## EDL format (for `cut`)

```json
{"keep": [{"start": 2.1, "end": 41.8}, {"start": 47.0, "end": 120.5}]}
```
Seconds, absolute source time, non-overlapping, ascending. Spans < 0.05s dropped.

## Conventions

- **Parallel-safe:** `stt --chunk N` and per-clip `clip`/`thumbnail` calls touch
  disjoint files — safe to run many at once across subagents.
- **Real resumption:** `cut`/`clip`/`concat` record a `key` (input signature) +
  output in `ledger.jsonl`. Re-running the same flow SKIPS already-rendered units
  (`resumed: true`); `oc resume` lists what's done vs missing. Pass `--force` to
  re-render one. An interrupted long run continues instead of redoing everything.
- **Absolute timecodes:** `ingest` records each chunk's MEASURED duration, so
  word/segment times don't drift over long sources (no `index*300` assumption).
- **Idempotent:** STT caches per chunk; re-running a stage is cheap.
- **Mock:** `--mock` (stt/subtitle) avoids all network calls for dev/offline.
- **Real OpenAI:** ensure `OPENAI_API_KEY` is set and `OPENAI_BASE_URL` is unset
  (a CLI proxy base url breaks Whisper/image calls).
