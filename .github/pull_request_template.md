## What

<!-- one paragraph: what changes and why -->

## Checklist

- [ ] `uv run pytest -q` passes
- [ ] If `agents/*.md`, `skills/oc/*`, or `flows/*.yaml` changed: ran `python3 scripts/sync_agents.py` (CI enforces `--check`)
- [ ] No generated media, `.env`, or `out/` artifacts committed
- [ ] Tool behavior changes are reflected in `skills/oc/tools-reference.md`
