# Real run artifacts

Everything here comes from one real flow-2 run over a 109-minute Korean tech
talk (the maintainer's own harness-engineering lecture) — 22 STT chunks
transcribed in parallel, 11 hook-finder agents fanned out over the transcript,
5 shorts + 2 long-form candidates rendered, every deliverable `confirmed` by an
independent verifier.

| File | What it proves |
|------|----------------|
| [`short_003_frame.jpg`](short_003_frame.jpg) | A frame from a rendered 9:16 short — blurred-fill vertical layout with burned, word-timed Korean captions |
| [`short_004_thumbnail.jpg`](short_004_thumbnail.jpg) | A hook-matched thumbnail: auto-picked representative frame + Pillow-burned headline with translucent scrim |
| [`transcript_excerpt.md`](transcript_excerpt.md) | The merged-transcript segments the hook-finder turned into short_003 (the "idempotency" hook, 3039.7–3077.5s) |
| [`short_003.ko.srt.txt`](short_003.ko.srt.txt) | The word-timed, clip-relative SRT that was burned into short_003 (15 cues over 37.8s) |
| [`short_003.verify.json`](short_003.verify.json) | The mechanical evidence file: 10/10 checks (duration drift 0.002s, 1080×1920, audio −20.7dB, SRT within video) |
| [`ledger_excerpt.jsonl`](ledger_excerpt.jsonl) | Keyed ledger events — the same run resumed after a disk-full crash and skipped every completed render |

Numbers from that run: full-source whisper-1 STT ≈ $0.66, hook-finder wave ran
11 subagents concurrently, and the re-run after the crash re-rendered only the
2 failed shorts (`resumed: true` on the other 5 deliverables).
