# Contributing To OpenClip

Thanks for helping improve OpenClip.

## Local Setup

```bash
uv sync --extra dev
uv run pytest
```

For provider-free development, use `--mock-openai`.

```bash
uv run openclip run /path/to/input.mp4 --out ./out --mock-openai --strategy-approved
```

## Pull Request Checklist

- Keep generated media, `.env`, local videos, and `out/` out of commits.
- Add or update tests for behavior changes.
- Run `uv run pytest`.
- Run `python3 -m compileall -q src codex/skills/openclip/scripts tests`.
- Scan for accidental secrets before pushing.

```bash
rg -n -e "[s]k-proj-" -e "OPENAI_API_KEY\\s*=\\s*[s]k-" -e "OPEN_API_KEY\\s*=\\s*[s]k-" \
  --glob '!out/**' \
  --glob '!.env' \
  --glob '!demo.mp4' \
  --glob '!lecturer/**' \
  --glob '!.venv/**' .
```

## Coding Notes

- Keep the CLI local-first and deterministic where possible.
- Prefer manifest-backed evidence over success logs.
- Treat subagent review output as a claim until the root process verifies paths.
- Preserve the `openclip` CLI as the public command name.

## Harness Development (`oc`, agents, flows)

The agent harness has a strict source-of-truth layout — edit canonical files,
never generated mirrors:

- **Worker roles:** `agents/<role>.md` is canonical. `.claude/agents/`,
  `.agents/skills/oc-*/`, and `skills/oc-*/` are generated.
- **Orchestrator skill:** `skills/oc/SKILL.md` + `tools-reference.md` are
  canonical; `skills/oc/flows/` is generated from `flows/*.yaml`.
- After editing any of the above: `python3 scripts/sync_agents.py`. CI runs
  `--check` and fails on drift (`tests/test_sync_agents.py` enforces it too).

Adding capability:

- **New tool verb:** implement in `src/openclip/harness/tools.py`, wire the CLI
  in `src/openclip/harness/cli.py`, document it in
  `skills/oc/tools-reference.md`, and add a test in `tests/test_oc_tools.py`.
  Every verb prints exactly one JSON object; render-shaped verbs must record a
  keyed ledger event and support `--force` (resume contract).
- **New flow:** add `flows/flowN-<name>.yaml` (stages, worker, fan-out width,
  `success` criteria, `checkpoint_required` for creative stages), a
  `commands/oc-<name>.md` entry point, and route it in `AGENT_GUIDE.md` +
  `skills/oc/SKILL.md`.
- **New worker role:** add `agents/<role>.md` with a JSON return contract; if it
  produces file deliverables, add it to the `ENFORCED` regex in
  `hooks/verify_evidence_hook.py` and end its contract with an
  `EVIDENCE_RECORDED:` line.

Run the harness test suite with `uv run pytest tests/ -q` (self-contained; ffmpeg
required, no network).
