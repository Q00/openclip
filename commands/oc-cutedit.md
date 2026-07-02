---
description: "Flow 1 — LRF/long video → parallel STT → cut-editing debate → cut-edited original + subtitles."
---

Read `${CLAUDE_PLUGIN_ROOT:-.}/flows/flow1-cutedit.yaml` and `${CLAUDE_PLUGIN_ROOT:-.}/AGENT_GUIDE.md`, then run flow 1 as the `oc-orchestrator`: proxy if .LRF, ingest, fan out one `oc-stt-worker` per chunk, run the cut-editing debate (`oc-cut-proposer` × {filler,pacing,narrative} → `oc-cut-judge`), render the cut, subtitle, and verify with `oc-verifier`.
