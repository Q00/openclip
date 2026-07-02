---
description: "Agent-orchestrated video harness — fan out subagents to cut-edit, subtitle, thumbnail, and assemble video."
aliases: [video, clip]
---

Read `${CLAUDE_PLUGIN_ROOT:-.}/skills/oc/SKILL.md` and `${CLAUDE_PLUGIN_ROOT:-.}/AGENT_GUIDE.md`, then act as the `oc-orchestrator`: route the user's request to the right flow in `flows/`, fan out worker subagents per the manifest, verify deliverables with an independent `oc-verifier`, and report the deliverables. Follow those files exactly.
