---
name: openclip
description: "Codex app entrypoint for running OpenClip: transcript-first shorts, 10-minute long-form candidates, subagent review, thumbnails, multilingual SRTs, and manifest verification from a local video."
---

# OpenClip

Use this skill when the user asks to turn a local video into shorts, long-form candidates, cut-edited originals, transcripts, subtitles, thumbnails, or a video-use-style review workflow.

## What This Skill Does

The Codex app is the starting point. Do not ask the user to run the Python CLI manually unless they explicitly want that. Codex should orchestrate the workflow, call the bundled wrapper script, inspect artifacts, and use subagents/personas when content judgment is needed.

The local implementation lives at the repository root.

When this skill is installed in Codex, run commands from that root directory.

The wrapper script is:

`codex/skills/openclip/scripts/run_openclip.py`

## Default Run

For a real OpenAI run, call:

```bash
python3 codex/skills/openclip/scripts/run_openclip.py \
  INPUT_VIDEO \
  --out OUT_DIR \
  --strategy-approved
```

For user-requested expanded candidates and Korean subtitles burned into shorts, add:

```bash
--all-short-candidates --all-long-candidates --burn-short-ko-subtitles
```

Pass OpenAI credentials only through the process environment. Prefer `OPENAI_API_KEY`; if a local `.env` contains the legacy project key name `OPEN_API_KEY`, map it to `OPENAI_API_KEY` in-process only. Do not write API keys into files. If the environment contains `OPENAI_BASE_URL`, the wrapper or orchestration script must remove it so the official OpenAI API is used instead of a CLI proxy.

Normal production runs use official OpenAI services:

- STT: official OpenAI Whisper/STT, default `whisper-1`.
- Subtitle cleanup: one post-STT refinement pass that fixes obvious recognition errors while preserving cue timing and meaning.
- Thumbnails: official `gpt-image-2` for every rendered short and every rendered long-form candidate.

For bounded checks:

```bash
python3 codex/skills/openclip/scripts/run_openclip.py \
  INPUT_VIDEO \
  --out OUT_DIR \
  --mock-openai \
  --max-source-seconds 660 \
  --shorts 1 \
  --long-candidates 1 \
  --strategy-approved
```

## Workflow

This skill is an OpenClip meta-harness loop, not a one-shot CLI wrapper. The Codex app thread owns the loop until all hard gates pass and the editorial subagents approve, or until a real blocker is reached.

### Phase 1: Produce Draft Artifacts

1. Validate input video path and output directory.
2. Run the wrapper script from Codex.
3. Monitor until completion. If a provider/translation/render step fails but cached partials exist, fix the issue and resume in the same output root when safe.
4. Run mechanical verification with:

```bash
python3 codex/skills/openclip/scripts/verify_run_artifacts.py RUN_DIR
```

5. Run Codex-app-thread-owned parallel playback verification with:

```bash
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  RUN_DIR \
  --workers 6 \
  --write-manifest
```

Use `--full-decode` when the user asks for a heavier publish gate. The default playback gate still opens every final MP4 in parallel, samples frames from the start/middle/end portions of each video, verifies frames are not blank, decodes a representative audio sample, writes `analysis/playback_checks/playback_check.json`, and creates `analysis/playback_checks/playback_contact_sheet.jpg`.

Hard mechanical gates:
   - `manifest.json` status is `success`.
   - Final MP4s have only video/audio streams, no `data` stream.
   - Shorts are 9:16 and 30-60 seconds.
   - If requested, shorts keep Korean SRT sidecars and also visibly burn Korean subtitles into the MP4.
   - Burned Korean subtitles are speech-cue aligned, split into readable short chunks, and never use `...` or `…` truncation.
   - Long-form outputs are source-aspect and 8-12 minutes.
   - SRT sidecars exist for `en`, `ko`, `es`, `ja`, and `zh-Hans`.
   - SRT text has passed a refinement step after STT/translation and remains aligned to the final output timeline.
   - `analysis/candidate_selection.json` exists and records persona review.
   - Thumbnails exist beside every short and every long output.
   - Thumbnail prompts are built from the output's SRT text: summarize the subtitles, choose the most hook-worthy idea, then generate a thumbnail prompt from that hook.
   - Thumbnail generation records prompt JSON and, when possible, a representative video screenshot/reference frame. Use a user-provided lecturer image only when the prompt explicitly needs a person; default to no person or face.
   - Parallel playback verification passes in the Codex app thread: every final MP4 can be opened, sampled video frames across the timeline decode as nonblank, representative audio samples decode successfully, and a playback contact sheet is written for visual inspection.

If any hard gate fails, fix the Python harness or rerender artifacts before asking editorial subagents to approve.

6. Build OpenClip self-contained subagent packets:

```bash
python3 codex/skills/openclip/scripts/build_subagent_packets.py RUN_DIR
```

The packet index is written to `analysis/subagent_packets/index.json` and
mirrored into `manifest.json` as `subagent_packet_index`.

### Phase 2: Actual Codex Subagent Review

After mechanical gates pass, spawn actual Codex subagents. Do not substitute the Python-internal persona JSON for this step.

#### OpenClip Subagent Contract

Every spawned subagent receives a self-contained packet from
`analysis/subagent_packets/`. The prompt must start with `TASK:` and include
these exact sections:

- `TASK:`
- `DELIVERABLE:`
- `SCOPE:`
- `VERIFY:`
- `EVIDENCE:`
- `ADVERSARIAL_CHECKS:`
- `CLEANUP:`

Use `fork_context: false` by default. Do not rely on the subagent inheriting
parent-thread context; paste or reference the packet content directly.

Treat every child `PASS` as an untrusted claim until the root Codex thread
checks the cited paths, reruns the relevant verifier, or gets a gate-review
subagent to validate the evidence. A timeout means mailbox silence, not proof
of failure. If a child result is ack-only, missing the JSON deliverable, lacks
checked paths, or is inconclusive, respawn a smaller scoped packet instead of
counting it as pass.

Run subagents in the OpenClip evidence-review graph:

1. `collect`: shorts and long-form editors gather independent content claims.
2. `verify`: continuity, playback, and artifact gates check claims against files.
3. `design`: thumbnail director checks prompt/image choices from subtitle hooks.
4. `adversarial`: retention critic tries to break the candidate choices.
5. `synthesize`: final gate reviewer approves only after every lane has evidence.

Subagents that take more than one wait cycle should return
`WORKING: <role> - <phase>`. `BLOCKED:<reason>` is only valid when the packet is
insufficient to make progress; concrete content problems should be returned as
`NEEDS_CHANGES` with output IDs and edit suggestions.

The root Codex thread must track:

- exact packet path used for each subagent
- returned JSON verdict
- evidence paths cited by the child
- mechanical verifier commands rerun after any rerender
- cleanup receipts for temporary inspection files

Adversarial checks to keep in every gate:

- stale run directory or stale manifest paths after rerender
- dirty worktree or generated outputs accidentally staged for git
- misleading success output where manifest status is success but artifacts fail
- hung command, repeated interruption, or timeout misread as approval
- natural-boundary failure hidden by deterministic duration checks
- thumbnail prompt/image mismatch hidden by file existence

Use these five review agents:

- `shorts_editor`: checks hook, context independence, payoff, and whether each short can stand alone.
- `longform_editor`: checks coherent 8-12 minute arc, natural start, and natural ending.
- `retention_critic`: attacks weak openings, repetition, filler, and likely drop-off.
- `continuity_editor`: checks transcript boundary quality, mid-sentence starts/ends, subtitle timing, and cut continuity.
- `thumbnail_director`: checks thumbnail prompt, thumbnail image suitability, aspect, clarity, and mismatch risk.

Give each subagent the same artifact packet:

- `manifest.json`
- `analysis/takes_packed.md`
- `analysis/candidate_selection.json`
- `analysis/edl.json`
- final MP4 paths
- thumbnail paths
- any known user complaints

Prefer using the generated packet for the matching role instead of hand-building
the prompt. If a role needs narrower review, copy the packet and remove outputs
outside that lane while preserving all required sections.

Require each subagent to return:

```json
{
  "verdict": "PASS or NEEDS_CHANGES",
  "blocking_issues": [
    {
      "output_id": "short_001",
      "issue": "why it fails",
      "required_change": "specific edit needed",
      "suggested_start_seconds": 123.0,
      "suggested_end_seconds": 176.0
    }
  ],
  "non_blocking_notes": [],
  "approval_conditions": []
}
```

### Phase 3: Revision Loop

Loop until every subagent returns `PASS`:

1. Merge all blocking issues into `analysis/subagent_review_round_N.json`.
2. Convert required changes into a concrete edit plan: candidate start/end changes, dropped candidates, merged shorts, long-form endpoint extensions, subtitle cleanup, thumbnail regeneration, or code fixes.
3. Apply the edit plan. Prefer rerendering from cached transcript/analysis over redoing STT.
4. Re-run mechanical verification.
5. Re-run only the subagents affected by the changes; run all five again before final signoff.
6. Stop only when mechanical gates pass and all five subagents return `PASS`.

If three consecutive rounds fail for the same unresolved reason, report the blocker with the exact artifact and subagent evidence. Otherwise keep going.

### Phase 4: Final Report

Report:

- final run directory
- mechanical verification summary
- subagent round count
- final `PASS` summary by subagent
- changed candidates/thumbnails
- key rotation reminder when the user's API key was used

## Persona/Subagent Use

For content quality, use Codex subagents when available. Recommended roles:

- `shorts_editor`: checks hook, context independence, and payoff for shorts.
- `longform_editor`: checks 8-12 minute story arc and natural ending.
- `retention_critic`: attacks weak openings, repetition, and drop-off risks.
- `continuity_editor`: checks whether cuts start/end at natural transcript boundaries.
- `thumbnail_director`: checks thumbnail prompt/visual suitability.
- `playback_probe`: checks the parallel playback report/contact sheet and flags blank frames, decode failures, or duration mismatches.

Use subagents after transcript/analysis artifacts exist, especially when the user says candidates feel awkward, endings feel abrupt, or the selected moment is unclear. Give subagents only the relevant artifact paths, such as `analysis/takes_packed.md`, `analysis/candidate_selection.json`, `manifest.json`, and rendered output paths.

When the user asks for Codex app thread-based video checking, run the parallel playback verifier in the main thread first, then dispatch playback-focused subagents over disjoint artifact groups if more assurance is needed. The main thread remains responsible for merging the verdicts and rerunning the verifier after any rerender.

The Python harness also writes a deterministic persona-style artifact at `analysis/candidate_selection.json`; use that as the baseline. It is not a replacement for actual Codex subagent review when this skill is running in the Codex app.

## Notes

- This skill is an app-level orchestrator. The OpenClip Python package remains the rendering/extraction engine.
- If using the user's API key from chat, remind them to rotate it afterward.
- Keep partial outputs when debugging unless the user requests cleanup.
