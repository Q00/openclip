# Security Policy

## Supported Versions

OpenClip is pre-1.0. Security fixes target the latest `main` branch unless a release branch says otherwise.

## Reporting A Vulnerability

Please report suspected vulnerabilities privately to the repository owner instead of opening a public issue with exploit details.

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

Real provider mode may send audio, transcripts, subtitle text, thumbnail prompts, and reference frames to OpenAI. Use `--mock-openai` when network calls are not acceptable.
