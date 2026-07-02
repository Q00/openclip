# OpenClip — Codex entry

**Read `AGENT_GUIDE.md` before acting on any video request.** It routes you to the
right flow and tells you how to fan out and verify.

This repo is an agent-orchestrated video harness. You (Codex) are the control
plane. Python ships composable tools (`oc` CLI); YAML manifests in `flows/`
declare the pipelines; worker roles live as skills under `.agents/skills/`.

- Orchestrator skill: `.agents/skills/oc/SKILL.md`
- Worker skills: `.agents/skills/oc-<role>/SKILL.md`
- Tool reference: `.agents/skills/oc/tools-reference.md`

Do not hand-edit `.agents/` or `.claude/` mirrors — they are generated from
`agents/*.md` + `skills/oc/` via `python3 scripts/sync_agents.py`.
