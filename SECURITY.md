# Security Policy

## Supported Versions

OpenClip is pre-1.0. Security fixes target the latest `main` branch unless a release branch says otherwise.

## Reporting A Vulnerability

Use GitHub's private vulnerability reporting:
<https://github.com/Q00/openclip/security/advisories/new> — do not open a public
issue with exploit details.

Include:

- affected commit or version
- reproduction steps
- impact
- whether secrets, local files, or provider credentials are involved

## Sensitive Data

Do not commit:

- `.env`
- OpenAI API keys
- source videos
- generated videos
- generated subtitles
- generated thumbnails
- lecturer/reference images
- `out/`

Real provider mode may send audio, transcripts, subtitle text, thumbnail prompts, and reference frames to OpenAI. Use `--mock-openai` (legacy pipeline) or `--mock` (`oc` tools) when network calls are not acceptable.

## Harness Security Controls

The agent harness executes agent-authored scripts and installs software; these
are the controls around that:

- **Learned-tool env isolation.** `oc toolbox run` executes scripts with a
  scrubbed environment: a small allowlist (`PATH`, `HOME`, locale, …) plus a
  secret-pattern filter — `OPENAI_API_KEY` and other credentials never reach a
  learned tool. Script paths are pinned inside `toolbox/scripts/`.
- **Promotion gate.** A tool becomes `shared` only after a clean re-verify in a
  scrubbed env, a static deny-list scan (network/shell/fs-destroy/dynamic-load
  patterns), and an explicit `--reviewed` flag from a human or the
  `oc-tool-auditor` role. A deny-list hit blocks promotion even when reviewed.
- **Evidence gate.** The `SubagentStop` hook (Claude Code and Codex,
  `features.hooks = true`) blocks render workers that claim "done" without an
  `EVIDENCE_RECORDED:` receipt, up to 3 attempts; it fails open (never locks a
  session) and defaults to allow on any parse error.
- **Credential redirection.** The `oc` CLI unconditionally unsets
  `OPENAI_BASE_URL` at startup so credentials cannot be silently redirected to
  a third-party endpoint. Do not rely on it for proxy routing.
- **Install pinning.** Prefer `uv tool install "git+https://github.com/Q00/openclip@v0.1.0"`
  (a release tag) over the default branch; the `oc` skill must ask for user
  consent before bootstrapping any install.
