---
description: "Flow 2 — one long video → parallel STT → hook mining → captioned 9:16 shorts + thumbnails."
---

Read `${CLAUDE_PLUGIN_ROOT:-.}/flows/flow2-shorts.yaml` and `${CLAUDE_PLUGIN_ROOT:-.}/AGENT_GUIDE.md`, then run flow 2 as the `oc-orchestrator`: proxy if .LRF, ingest, fan out one `oc-stt-worker` per chunk, fan out `oc-hook-finder` across transcript sections, surface the ranked hooks for human approval, then render each approved hook (`oc clip --aspect 9:16` + `oc-subtitle-agent` burn + `oc-thumbnail-artist`) and verify every deliverable with an independent `oc-verifier`.
