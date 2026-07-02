---
description: "Flow 3 — weave N videos into one longform, then cut its hook moments into shorts."
---

Read `${CLAUDE_PLUGIN_ROOT:-.}/flows/flow3-assemble.yaml`, then run flow 3 as the `oc-orchestrator`: prep each source in parallel (proxy + ingest + fan-out STT), assemble the longform with `oc-assembler`, fan out `oc-hook-finder` across the timeline, render the chosen hooks as shorts (with `oc-subtitle-agent` burns), and verify each with `oc-verifier`.
