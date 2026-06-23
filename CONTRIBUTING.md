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
