<div align="center">

![OpenClip — 에이전트가 오케스트레이션하는 영상 편집 하네스](docs/assets/banner.jpg)

### 당신이 연출합니다. 병렬로 동작하는 에이전트 함대가 컷을 놓고 토론하고, 렌더링하고, 모든 산출물을 증명합니다 — 하나의 긴 영상에서 쇼츠, 롱폼, 자막, 썸네일까지.

*Python은 도구를 내놓고, 에이전트는 판단을 내리고, 사람은 취향을 더합니다.*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

**[웹사이트](https://wpti.dev/openclip/)** · **[설계](docs/HARNESS.md)** · **[도구 레퍼런스](skills/oc/tools-reference.md)** · **[에이전트 가이드](AGENT_GUIDE.md)**

[English](README.md) | **한국어** | [中文](README.zh-CN.md) | [日本語](README.ja.md) | [Español](README.es.md)

</div>

---

에이전트를 열고(Claude Code와 Codex에서 테스트되었으며, Cursor를 비롯해 [skills 프로토콜](https://github.com/vercel-labs/skills)을 지원하는 모든 에이전트에 설치 가능합니다), 영상을 지정한 다음
*"이 영상 쇼츠 만들어줘"*라고 말하세요. 오케스트레이터 에이전트가 플로우 매니페스트를 읽고,
**워커 서브에이전트를 병렬로 펼쳐서**(전사, 컷 편집 토론,
훅 발굴, 자막, 썸네일) 작업하며, 모든 렌더링은 내보내지기 전에
**독립적인 적대적 검증자**를 반드시 통과해야 합니다. 당신은 계속 감독의 자리를 지킵니다:
`oc steer`로 진행 중인 어떤 결정이든 조종할 수 있습니다.

**이 글을 읽는 당신이 AI 에이전트인가요?** [`llms.txt`](llms.txt)로 시작한 다음
[`AGENT_GUIDE.md`](AGENT_GUIDE.md)로 넘어가세요 — 이 문서들이 알맞은 플로우 매니페스트와
워커 계약(contract)으로 안내합니다.

## 무엇을 만들어내는가

- 단어 단위로 타이밍이 맞춰진 자막이 구워진(burned) 30-60초 **세로형 쇼츠**
- 문장 중간이 아니라 결정적 한 방(payoff)으로 끝나는 8-12분 **롱폼 후보**
- **컷 편집된 원본**(단순히 감지하는 것이 아니라, 침묵/군더더기/반복을 토론으로 걸러냄)
- `en`, `ko`, `es`, `ja`, `zh-Hans`에 대한 **SRT 자막**
- **훅에 매칭된 썸네일**(대표 프레임 + 헤드라인, 또는 gpt-image)
- 모든 실행에 대한 매니페스트, EDL, 증거 파일, 그리고 재개 가능한 원장(ledger)

**말로만 믿지 말고 직접 보세요:** [docs/examples/](docs/examples/)에는 109분 실행에서 나온 실제
산출물이 담겨 있습니다 — 자막이 들어간 쇼츠 프레임, 썸네일,
훅 뒤에 있는 전사 조각, SRT, 10/10 증거 JSON, 그리고
재개 원장입니다.

## 에이전트 하네스 (`oc`)

OpenClip은 이제 기존의 원샷 `openclip run` 파이프라인과 함께 **에이전트가 오케스트레이션하고
사람이 조종하는 하네스**를 제공합니다. 고정된 워크플로 대신, 오케스트레이터
에이전트가 플로우 매니페스트를 읽고 **워커 서브에이전트를 병렬로 펼칩니다** — 그래서 긴 영상이
동시에 전사되고, 토론되고, 렌더링되며 —
사람은 모든 창의적 결정을 조종합니다.

네 가지 플로우:

1. **`flows/flow1-cutedit.yaml`** — LRF/LRV 프록시 → 병렬 STT(청크당 워커 하나)
   → **컷 편집 토론**(제안자들이 군더더기/페이싱/
   내러티브 렌즈로 논쟁하고, 심판이 이를 조율) → 컷 편집된 원본 + 자막.
2. **`flows/flow2-shorts.yaml`** — 하나의 긴 영상 → 병렬 STT → 훅 발굴 →
   자막이 들어간 9:16 쇼츠 + 썸네일.
3. **`flows/flow3-assemble.yaml`** — N개의 영상을 하나의 롱폼으로 엮은 다음,
   그 훅 순간들을 발굴해 쇼츠로 제작(각 쇼츠에 자막 + 썸네일 포함).
4. **`flows/flow4-thumbnail.yaml`** — 각 훅에 매칭된 썸네일 생성: 헤드라인이
   구워진 대표 프레임, 그리고/또는 훅의 캡션을 기반으로 gpt-image가 생성한
   썸네일.

핵심 구성 요소:

- **도구:** `oc --project <DIR> <cmd>` — `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, acp`. 각 명령은 JSON 한 줄을 출력합니다;
  `oc --help`가 기준입니다. `skills/oc/tools-reference.md`를 참고하세요.
- **사람의 조종:** `oc steer --note "..." --scope "global | <stage> | section:<a>-<b> | <deliverable_id>"`.
  오케스트레이터는 매 웨이브 전에 `oc status`의 미해결 지시(directive)를 읽고
  워커에 주입합니다. 감독은 항상 루프 안에 있습니다.
- **증거 게이트:** 독립적인 `oc-verifier`가 모든 렌더링을 관찰 가능한 증거와
  적대적 실패 클래스에 비추어 검사합니다; `confirmed` 판정만이
  다음 단계로 진행합니다. `SubagentStop` 훅이 "증거 없는 완료"를 차단합니다.
- **듀얼 런타임:** Claude Code(`.claude/agents`, `.claude/skills/oc`)와 Codex
  (`.agents/skills/oc*`)는 하나의 소스(`agents/*.md` +
  `skills/oc/`)로부터 `python3 scripts/sync_agents.py`를 통해 생성됩니다.

빠른 오프라인 정상 동작 확인(`demo.mp4`를 가지고 있는 아무 짧은 클립으로 바꾸세요):

```bash
oc --project out/demo ingest --input demo.mp4 --max-seconds 60
oc --project out/demo stt --chunk 0 --mock
oc --project out/demo transcript-merge
oc --project out/demo status
```

전체 설계는 `docs/HARNESS.md`를 참고하세요.

## 비용 (실제 실행)

대략적인 OpenAI 정가 기준 — 110분짜리 강연을 처음부터 끝까지(전체 STT,
자막이 구워진 쇼츠 5개, 롱폼 후보 2개, 썸네일) 처리하면 약
**$1** 정도가 나옵니다: whisper-1은 오디오 1분당 ≈ $0.006(110분에 ~$0.66), gpt-image-2는
생성된 썸네일당 ≈ $0.03-0.07(프레임 캡처 썸네일은 무료),
gpt-4o-mini 자막 번역은 클립당 1센트의 몇 분의 일 수준입니다. `--mock` 실행은
비용이 $0이며, 재개 원장은 이미 완료된 STT/렌더링을 다시 청구하지 않습니다.

## 상태

OpenClip은 초기 단계 소프트웨어입니다. 로컬에서 사용할 수 있지만, 안정 릴리스 이전에 API, 출력 스키마, 리뷰 패킷 포맷이 변경될 수 있습니다.

## 요구 사항

- Python 3.11+
- `uv`
- `ffmpeg`와 `ffprobe`
- 실제 실행을 위한 OpenAI API 키

Mock 실행은 외부 API를 호출하지 않으며 개발에 유용합니다.

## 설치

모든 모드의 사전 요구 사항: PATH에 있는 `ffmpeg`/`ffprobe`, Python 3.11+, 그리고
실제 실행을 위한 `OPENAI_API_KEY`(mock 실행에는 키가 필요 없습니다).

### A. 명령 하나로, 어떤 에이전트든 (권장)

오케스트레이터 스킬 + 12개의 워커 스킬 전부를 Claude Code와
Codex(테스트됨)에 설치하며, Cursor와 [skills 프로토콜을 지원하는 모든 에이전트](https://github.com/vercel-labs/skills)에도 설치합니다:

```bash
npx skills add Q00/openclip
```

그런 다음 `oc` CLI를 한 번 설치하세요(스킬이 스스로 확인하고
첫 사용 시 이를 제안하기도 합니다):

```bash
uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

이는 리포지토리의 코드를 설치합니다 — 릴리스 태그(표시됨)에 고정하고
민감한 환경에서는 [릴리스 노트](https://github.com/Q00/openclip/releases)를
확인하세요.

에이전트를 열고 *"이 영상 쇼츠 만들어줘"*라고 말하거나(어떤 언어든 됩니다),
`oc` 스킬을 직접 호출하세요. 스킬
폴더는 플로우 매니페스트와 도구 레퍼런스를 함께 묶어두었기 때문에, 리포지토리
밖에서도 동작합니다.

### B. Claude Code 플러그인 (서브에이전트 + 증거 훅 추가)

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

이 플러그인은 `oc-*` 서브에이전트 타입과 `SubagentStop` 증거
게이트를 등록합니다(스킬만 설치하면 워커가 훅 없이 general-purpose 서브에이전트로
실행됩니다). `oc` CLI는 여전히 위의 `uv tool install`에서 나옵니다.

**Codex — 증거 게이트 활성화.** 스킬은 모드 A로 설치됩니다; 자신의 프로젝트에서도
"증거 없는 완료" 게이트를 얻으려면, 이 리포지토리에서 두 개의 설정 파일을
복사하고 훅 스크립트 경로를 유효하게 유지하세요:

```bash
mkdir -p .codex hooks
curl -fsSLo .codex/config.toml  https://raw.githubusercontent.com/Q00/openclip/main/.codex/config.toml
curl -fsSLo .codex/hooks.json   https://raw.githubusercontent.com/Q00/openclip/main/.codex/hooks.json
curl -fsSLo hooks/verify_evidence_hook.py https://raw.githubusercontent.com/Q00/openclip/main/hooks/verify_evidence_hook.py
```

`config.toml`은 `features.hooks = true`를 설정하며(Codex가 `hooks.json`을
로드하는 데 필수), 훅은 `${CODEX_PROJECT_DIR:-$PWD}`를 통해 경로를 해석합니다.

### C. 리포지토리 클론 (개발)

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

리포지토리 루트에서 Claude Code나 Codex를 열면 — 에이전트, 스킬, 커맨드, 훅이
자동으로 로드됩니다.

실제 OpenAI 실행을 위해서는, 셸에 API 키를 설정하세요:

```bash
export OPENAI_API_KEY="..."
```

로컬 개발을 위해 `.env.example`을 `.env`로 복사할 수도 있습니다. 실제 키는 절대 커밋하지 마세요.

## 빠른 시작 — 레거시 원샷 파이프라인

> **리포지토리 클론(모드 C) 전용.** 이것은 에이전트 하네스보다 앞서 존재했던
> 원래의 고정 파이프라인입니다; 위의 하네스가 권장 경로입니다. `uv tool install`
> 이후에는 `uv run` 대신 `openclip run ...`을 직접 사용하세요.

실제 OpenAI 서비스로 실행:

```bash
uv run openclip run /path/to/input.mp4 --out ./out --strategy-approved
```

가능한 모든 쇼츠와 롱폼 후보를 생성하고 쇼츠에 한국어 자막을 구워 넣기:

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --strategy-approved \
  --all-short-candidates \
  --all-long-candidates \
  --burn-short-ko-subtitles
```

네트워크 호출 없이 범위가 제한된 로컬 스모크 테스트 실행:

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --mock-openai \
  --max-source-seconds 660 \
  --shorts 1 \
  --long-candidates 1 \
  --strategy-approved
```

## 출력

OpenClip은 각 실행 결과를 다음 경로 아래에 기록합니다:

```text
OUT_DIR/{input_basename}/
```

일반적인 출력은 다음을 포함합니다:

- `shorts/*.mp4`
- `long/*.mp4`
- `edited/edited_original.mp4`
- `*.en.srt`, `*.ko.srt`, `*.es.srt`, `*.ja.srt`, `*.zh-Hans.srt`
- `*.thumbnail.png`
- `manifest.json`
- `analysis/candidate_selection.json`
- `analysis/edl.json`
- `analysis/takes_packed.md`
- `analysis/playback_checks/*`
- `analysis/subagent_packets/*`

생성된 미디어, 로컬 소스 영상, `.env`, 가상 환경, 캐시, 그리고 `out/`은 git에서 무시됩니다. 렌더링된 출력을 커밋에 포함하지 마세요.

## 검증 — 레거시 파이프라인 (리포지토리 클론 전용)

> 이 스크립트들은 설치된 패키지가 아니라 리포지토리 트리에 들어 있습니다. 하네스
> 실행은 다르게 검증됩니다: `oc verify` + `oc-verifier` 에이전트(참고:
> `docs/HARNESS.md`).

기존 실행 검증:

```bash
python3 codex/skills/openclip/scripts/verify_run_artifacts.py \
  ./out/example/input_basename
```

병렬 재생/디코드 게이트 실행:

```bash
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename \
  --workers 6 \
  --full-decode \
  --write-manifest
```

기존 실행에 대한 Codex 서브에이전트 리뷰 패킷 재생성:

```bash
python3 codex/skills/openclip/scripts/build_subagent_packets.py \
  ./out/example/input_basename
```

## 리뷰 워크플로 — 레거시 파이프라인

OpenClip의 레거시 파이프라인은 `analysis/subagent_packets/` 아래에 자체 완결적인 Codex 서브에이전트 패킷을 생성합니다.

리뷰 그래프는 다음과 같습니다:

1. `collect`: 쇼츠 및 롱폼 편집자가 독립적인 콘텐츠 주장(claim)을 수집합니다.
2. `verify`: 연속성, 재생, 산출물 게이트가 파일과 매니페스트를 검사합니다.
3. `design`: 썸네일 디렉터가 프롬프트와 이미지 적합성을 검사합니다.
4. `adversarial`: 리텐션 비평가가 시청자 이탈 가능성이 높은 지점을 찾습니다.
5. `synthesize`: 최종 게이트 리뷰어가 모든 레인에 증거가 있을 때만 승인합니다.

서브에이전트 `PASS` 결과는 증명이 아니라 주장(claim)으로 취급됩니다. 루트 스레드나 릴리스 프로세스는 출력을 게시하기 전에 인용된 경로, 매니페스트, 재생 증거를 반드시 검증해야 합니다.

## 개발

```bash
uv sync --extra dev
uv run pytest
python3 -m compileall -q src codex/skills/openclip/scripts tests
```

PR을 열거나 브랜치를 게시하기 전에, 시크릿 스캔을 실행하세요:

```bash
rg -n -e "[s]k-proj-" -e "OPENAI_API_KEY\\s*=\\s*[s]k-" -e "OPEN_API_KEY\\s*=\\s*[s]k-" \
  --glob '!out/**' \
  --glob '!.env' \
  --glob '!demo.mp4' \
  --glob '!lecturer/**' \
  --glob '!.venv/**' .
```

## 보안 및 개인정보

OpenClip은 로컬 미디어를 처리하며, `--mock-openai`를 사용하지 않을 때 오디오, 전사 텍스트, 자막 텍스트, 썸네일 프롬프트/참조 프레임을 OpenAI로 전송할 수 있습니다.

설정된 제공자로 처리할 권리가 없다면, 비공개·규제 대상·제3자 미디어에 실제 제공자 모드를 실행하지 마세요. 네트워크 호출을 피해야 하는 로컬 테스트에는 `--mock-openai`를 사용하세요.

## 라이선스

MIT. [LICENSE](LICENSE)를 참고하세요.
