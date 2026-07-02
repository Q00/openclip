---
description: "Flow 4 — hook-matched thumbnails (representative frame + title, or gpt-image)."
---

Read `${CLAUDE_PLUGIN_ROOT:-.}/flows/flow4-thumbnail.yaml` and `${CLAUDE_PLUGIN_ROOT:-.}/AGENT_GUIDE.md`, then run flow 4 as the `oc-orchestrator`: for each hook (or deliverable) fan out one `oc-thumbnail-artist` concurrently (`oc thumbnail --start S --end E --title "<headline>"`, add `--generate [--from-frame]` for the designed variant), pause at the human-approval checkpoint with the candidates, and verify each chosen thumbnail with `oc verify --kind thumbnail --expect-aspect <A>` plus an independent `oc-verifier`.
