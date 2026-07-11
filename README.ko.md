<div align="center">

![OpenClip — 에이전트가 오케스트레이션하는 영상 편집 하네스](docs/assets/banner.jpg)

### 당신이 연출합니다. 병렬로 동작하는 에이전트 함대가 컷을 놓고 토론하고, 렌더링하고, 모든 산출물을 증명합니다 — 하나의 긴 영상에서 쇼츠, 롱폼, 자막, 썸네일까지.

*Python은 도구를 내놓고, 에이전트는 판단을 내리고, 사람은 취향을 더합니다.*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![PyPI](https://img.shields.io/pypi/v/openclip-agent?label=pypi)](https://pypi.org/project/openclip-agent/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install openclip-agent
```

**[웹사이트](https://wpti.dev/openclip/)** · **[설계](docs/HARNESS.md)** · **[도구 레퍼런스](skills/oc/tools-reference.md)** · **[에이전트 가이드](AGENT_GUIDE.md)**

[English](README.md) | **한국어** | [中文](README.zh-CN.md) | [日本語](README.ja.md) | [Español](README.es.md)

</div>

---

에이전트를 열고(Claude Code와 Codex에서 테스트되었으며, Cursor를 비롯해
[skills 프로토콜](https://github.com/vercel-labs/skills)을 지원하는 모든 에이전트에 설치 가능합니다), 영상을 지정한 다음
*"이 영상 쇼츠 만들어줘"*라고 말하세요. 오케스트레이터 에이전트가 플로우 매니페스트를 읽고,
**워커 서브에이전트를 병렬로 펼쳐서**(전사, 컷 편집 토론,
훅 발굴, 자막, 썸네일) 작업하며, 모든 렌더링은 내보내지기 전에
**독립적인 적대적 검증자**를 반드시 통과해야 합니다. 당신은 계속 감독의 자리를 지킵니다:
`oc steer`로 진행 중인 어떤 결정이든 조종할 수 있습니다.

**이 글을 읽는 당신이 AI 에이전트인가요?** [`llms.txt`](llms.txt)로 시작한 다음
[`AGENT_GUIDE.md`](AGENT_GUIDE.md)로 넘어가세요 — 이 문서들이 알맞은 플로우 매니페스트와
워커 계약(contract)으로 안내합니다.

## 시작하기 — 첫 실행

설치를 마치면(아래 참고), 파이프라인을 실행하는 게 아니라 에이전트와 대화합니다.

**1. 영상이 있는 폴더에서 에이전트를 여세요** (Claude Code 또는 Codex).

**2. `oc` 스킬을 호출하고 원하는 것을 말하세요:**

```
you    $oc ./talk.mp4로 쇼츠 만들어줘

agent  flow2-shorts를 읽는 중입니다. 오디오를 청크로 나눠 STT 워커를
       병렬로 펼치는 중… 전사 병합 완료(110분). 전체 구간에서 훅을
       발굴 중 — 후보 6개 순위화. 상위 3개를 9:16 쇼츠로 잘라
       자막을 굽고 각각 썸네일을 만들겠습니다. 렌더링 전에 훅 목록을
       승인해 주시겠어요?  [you: 네, 4번은 빼주세요]
       렌더링 중… 각 클립이 증거 게이트(길이, 비율, 오디오, 자막
       타이밍)를 통과했습니다. 완료 — out/talk/shorts/ 를 확인하세요.
```

오케스트레이터는 진짜 의사결정 지점(어떤 훅, 어떤 컷, 어떤 썸네일)에서 확인을
구하며, 증거가 뒷받침되지 않는 "완료"는 차단합니다.

**3. 결과물을 확인하세요.** 모든 산출물은 프로젝트 디렉터리 아래(여기서는
`out/talk/`)에 놓입니다:

| 폴더 | 내용 |
| --- | --- |
| `shorts/` | 자막이 구워진 세로형 `.mp4` 클립 |
| `thumbnails/` | 산출물마다 하나씩 디자인된 썸네일 |
| `subs/` | 언어별 `.srt` 사이드카 |
| `evidence/` | 모든 렌더링에 대한 검증자의 증거 JSON |

**비용:** 110분짜리 강연 전체(STT + 쇼츠 여러 개 + 썸네일)를 처리하면 OpenAI
정가 기준으로 약 **$1** 정도입니다. 어디에든 `--mock`을 붙이면 비용이 **$0**입니다
— 오프라인으로 처음 시험해보기에 이상적입니다(세부 내역은 [비용](#비용) 참고).

### 에이전트 없이 CLI만 쓰고 싶다면?

에이전트가 수행하는 모든 단계는 그냥 `oc` 명령입니다. 아래 시퀀스는 API 키가
필요 없고 비용도 들지 않습니다 — STT는 `--mock`으로 실행되고, 컷과 썸네일은
로컬 ffmpeg 작업입니다(OpenAI 호출 없음):

```bash
oc --project out/talk ingest --input talk.mp4 --max-seconds 120
oc --project out/talk stt --chunk 0 --mock
oc --project out/talk transcript-merge
oc --project out/talk clip --input talk.mp4 --start 30 --end 75 --aspect 9:16 --id s1
oc --project out/talk thumbnail --input talk.mp4 --start 30 --end 75 --title "The one trick"
oc --project out/talk status
```

발표자 사진이 있나요? 썸네일 라인을 디자인된 no-AI 컷아웃으로 바꾸세요 —
여전히 무료이고, 모델을 한 번만 다운로드하면 이후로는 오프라인입니다:
`… thumbnail --composite --persona speaker.jpg --style editorial --title "…"`.

`oc --help`가 기준이 되는 명령 목록입니다. 모든 동작(verb)은
[`skills/oc/tools-reference.md`](skills/oc/tools-reference.md)를 참고하세요.

## 무엇을 만들어내는가

- 단어 단위로 타이밍이 맞춰진 자막이 구워진(burned) 30-60초 **세로형 쇼츠**
- 문장 중간이 아니라 결정적 한 방(payoff)으로 끝나는 8-12분 **롱폼 후보**
- **컷 편집된 원본**(단순히 감지하는 것이 아니라, 침묵/군더더기/반복을 토론으로 걸러냄)
- `en`, `ko`, `es`, `ja`, `zh-Hans`에 대한 **SRT 자막**
- **디자인된 썸네일** — `--persona`로 실제 발표자의 정체성을 보존하고, 큐레이션된
  `--style` 프리셋을 고르거나, 비용이 들지 않는 no-AI `--composite` 컷아웃,
  또는 gpt-image 렌더링 중 선택합니다; 하네스는 여러 라운드를 거치며 채널의
  취향을 학습합니다(`oc taste`)
- 모든 실행에 대한 매니페스트, EDL, 증거 파일, 그리고 재개 가능한 원장(ledger)

**말로만 믿지 말고 직접 보세요:** [docs/examples/](docs/examples/)에는 109분 실행에서 나온 실제
산출물이 담겨 있습니다 — 자막이 들어간 쇼츠 프레임, 썸네일,
훅 뒤에 있는 전사 조각, SRT, 10/10 증거 JSON, 그리고
재개 원장입니다.

## 설치

모든 모드의 사전 요구 사항: PATH에 있는 `ffmpeg`/`ffprobe`, Python 3.11+, 그리고
실제 실행을 위한 `OPENAI_API_KEY`(mock 실행에는 키가 필요 없습니다).

**어떤 설치를 원하시나요?**

| 당신은… | 설치 | 얻는 것 |
| --- | --- | --- |
| **Claude Code** 사용자 | 플러그인 (B) | 서브에이전트 타입 + 증거 게이트 훅 |
| **Codex / Cursor / 그 외 skills 프로토콜 에이전트** 사용자 | `npx skills add` (A) | 오케스트레이터 + 워커 스킬 |
| **CLI만** 필요 (에이전트 없이) | PyPI (`uv tool install`) | `oc` 명령만 |

셋 다 조합할 수 있습니다 — 스킬/플러그인은 에이전트를 담고, CLI는 그들이
호출하는 `oc` 도구를 제공합니다.

### A. 스킬 카탈로그, 어떤 에이전트든 (권장)

Codex, Cursor, 그리고 [skills 프로토콜을 지원하는 모든 에이전트](https://github.com/vercel-labs/skills)를
위한 것입니다. 오케스트레이터와 모든 워커 스킬을 설치합니다:

```bash
npx skills add Q00/openclip
```

그런 다음 `oc` CLI를 한 번 설치하세요(스킬이 스스로 확인하고
첫 사용 시 이를 제안하기도 합니다):

```bash
uv tool install openclip-agent      # 또는: pip install openclip-agent
```

에이전트를 열고 *`$oc 이 영상 쇼츠 만들어줘`*라고 호출하세요. 자연어 요청도
동작하지만 첫 실행에는 명시적 스킬 호출이 가장 확실합니다. 스킬 폴더는 플로우 매니페스트와 도구 레퍼런스를
함께 묶어두었기 때문에, 리포지토리 밖에서도 동작합니다.

### B. Claude Code 플러그인 (서브에이전트 + 증거 훅 추가)

Claude Code 사용자를 위한 것입니다. `oc-*` 서브에이전트 타입과
`SubagentStop` 증거 게이트를 등록합니다(스킬만 설치하면 워커가 훅 없이
general-purpose 서브에이전트로 실행됩니다):

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

`oc` CLI는 여전히 위의 `uv tool install openclip-agent`에서 나옵니다.

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

### C. CLI만 (PyPI)

에이전트 없이 `oc`/`openclip` 도구만 원한다면:

```bash
uv tool install openclip-agent      # 또는: pip install openclip-agent
```

### D. 리포지토리 클론 (개발)

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

리포지토리 루트에서 Claude Code나 Codex를 열면 — 에이전트, 스킬, 커맨드, 훅이
자동으로 로드됩니다. 실제 OpenAI 실행을 위해서는 셸에 키를 설정하세요(또는
`.env.example`을 `.env`로 복사하세요; 실제 키는 절대 커밋하지 마세요):

```bash
export OPENAI_API_KEY="..."
```

## 에이전트 하네스 (`oc`)

고정된 워크플로 대신, 오케스트레이터 에이전트가 플로우 매니페스트를 읽고
워커 서브에이전트를 병렬로 펼치며, 사람은 모든 창의적 결정을 조종합니다.
[`agents/`](agents/)에는 열세 개의 역할 정의가 있습니다: 오케스트레이터 하나와
전문화된 워커 열둘입니다.

네 가지 플로우:

1. **`flows/flow1-cutedit.yaml`** — LRF/LRV 프록시 → 병렬 STT → **컷 편집 토론**(제안자들이 군더더기/페이싱/내러티브 렌즈로 논쟁하고, 심판이 이를 조율) → 컷 편집된 원본 + 자막.
2. **`flows/flow2-shorts.yaml`** — 하나의 긴 영상 → 병렬 STT → 훅 발굴 → 자막이 들어간 9:16 쇼츠 + 썸네일.
3. **`flows/flow3-assemble.yaml`** — N개의 영상을 하나의 롱폼으로 엮은 다음, 그 훅을 발굴해 쇼츠로 제작(각각 자막 + 썸네일 포함).
4. **`flows/flow4-thumbnail.yaml`** — 각 훅에 매칭된 썸네일: 헤드라인이 구워진 대표 프레임, 그리고/또는 훅의 캡션을 기반으로 한 gpt-image 렌더링.

핵심 구성 요소:

- **도구:** `oc --project <DIR> <cmd>` — `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, taste, acp`. 각 명령은 JSON 한 줄을 출력합니다;
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

실행 가능한 오프라인 정상 동작 확인은 위의
[CLI 시퀀스](#에이전트-없이-cli만-쓰고-싶다면)를 참고하세요; 전체 설계는
`docs/HARNESS.md`에 있습니다.

### v0.2 신규 기능: 디자인된 썸네일 + 학습되는 취향

**디자인된 썸네일**(`oc thumbnail`)은 프레임을 그냥 캡처한 것이 아니라 아트
디렉팅을 거친 것처럼 보입니다: `--persona <photo|dir>`는 **실제 발표자의
정체성**을 보존합니다(gpt-image 편집); `--style clean|editorial|bold|keynote`는
큐레이션된 프리셋을 고릅니다; `--composite`는 **no-AI 경로**입니다(스튜디오
배경 위에 rembg 컷아웃과 타이포그래피 헤드라인 — 생성된 픽셀 없음, **비용
없음**, 즉시 처리); `--render-text`는 gpt-image-2가 헤드라인 자체를 조판하게
합니다(확률적이므로 — 계약이 매 렌더링마다 철자를 검증합니다);
`--prompt-note "..."`는 렌더링별 아트 디렉션을 추가합니다.

**`oc taste`**(`show|note|evolve|revert`)는 **개인화 루프**입니다 — 하네스가
당신 채널의 룩을 학습합니다. 렌더링된 썸네일에 대해 판정을 기록하면
(`taste note`), 에이전트가 이를 반영해 **다음 세대의 가이드**를 만듭니다
(`taste evolve`). 세대별 스코어보드, 계보(lineage), 그리고 더 새로운 세대가
더 낮은 점수를 받으면 롤백(`taste revert`)까지 제공합니다. 가이드는 도메인별로
유지되며, 저장 위치는 `$OPENCLIP_HOME` → 리포지토리의 `toolbox/`(팀 옵트인) →
`~/.openclip`(플러그인 기본값) 순으로 결정됩니다.

## 비용

대략적인 OpenAI 정가 기준 — 110분짜리 강연을 처음부터 끝까지(전체 STT,
자막이 구워진 쇼츠 5개, 롱폼 후보 2개, 썸네일) 처리하면 약
**$1** 정도가 나옵니다: whisper-1은 오디오 1분당 ≈ $0.006(110분에 ~$0.66), gpt-image-2는
생성된 썸네일당 ≈ $0.03-0.07(프레임 캡처 및 `--composite` 썸네일은 무료),
gpt-4o-mini 자막 번역은 클립당 1센트의 몇 분의 일 수준입니다. `--mock` 실행은
비용이 $0이며, 재개 원장은 이미 완료된 STT/렌더링을 다시 청구하지 않습니다.

## 요구 사항 및 상태

- Python 3.11+, `uv`, PATH에 있는 `ffmpeg`/`ffprobe`
- 실제 실행을 위한 OpenAI API 키(mock 실행은 외부 API를 호출하지 않습니다)

OpenClip은 초기 단계 소프트웨어입니다. 로컬에서 사용할 수 있지만, 안정
릴리스 이전에 API, 출력 스키마, 리뷰 패킷 포맷이 변경될 수 있습니다.

## 문제 해결

- **`ffmpeg`/`ffprobe: command not found`** — ffmpeg를 설치하고 두 바이너리
  모두 `PATH`에 있는지 확인하세요(`ffmpeg -version`이 출력되어야 합니다).
  모든 렌더링 경로가 이 바이너리들을 셸에서 호출합니다.
- **`OPENAI_API_KEY` 누락** — 실제 실행을 위해 설정하세요
  (`export OPENAI_API_KEY=...`). `--mock`에는 필요 없습니다: mock 모드는
  네트워크 호출을 하지 않습니다.
- **실제 실행에서는 `OPENAI_BASE_URL`을 설정 해제해야 합니다** — CLI 프록시
  base URL이 있으면 Whisper와 이미지 호출이 깨집니다. 실제 실행 전에 설정을
  해제하세요(`unset OPENAI_BASE_URL`).
- **첫 `--composite` 실행은 잠시 멈춥니다** — rembg 배경 제거 모델을 한 번
  다운로드한 뒤에는 완전히 오프라인으로 동작합니다. PATH에 `uv`가 제공하는
  `uvx`가 필요합니다.
- **실제 실행이 "성공"했는데 파일이 없다** — 그건 내보내질 수 없습니다:
  증거 게이트는 `confirmed` 판정에서만 다음 단계로 진행합니다. 실패한
  산출물의 `evidence/*.json`을 확인하세요.

<details>
<summary><strong>레거시 원샷 파이프라인(<code>openclip run</code>)</strong> — 원래의 고정 파이프라인, 여전히 지원됨</summary>

> **리포지토리 클론(모드 D) 전용.** 이것은 에이전트 하네스보다 앞서 존재했던
> 원래의 고정 파이프라인입니다; 위의 하네스가 권장 경로입니다. `uv tool install`
> 이후에는 `uv run` 대신 `openclip run ...`을 직접 사용하세요.

### 빠른 시작

실제 OpenAI 서비스로 실행:

```bash
uv run openclip run /path/to/input.mp4 --out ./out --strategy-approved
```

가능한 모든 쇼츠와 롱폼 후보를 한국어 자막과 함께 생성하기:

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --strategy-approved \
  --all-short-candidates \
  --all-long-candidates \
  --subtitle-langs ko
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

### 출력

각 실행은 `OUT_DIR/{input_basename}/` 아래에 결과를 기록합니다. 일반적인
출력은 `shorts/*.mp4`, `long/*.mp4`, `edited/edited_original.mp4`, 언어별 SRT
(`*.en.srt`, `*.ko.srt`, `*.es.srt`, `*.ja.srt`, `*.zh-Hans.srt`),
`*.thumbnail.png`, `manifest.json`, 그리고 `analysis/`(candidate_selection.json,
edl.json, takes_packed.md, playback_checks/, subagent_packets/)를 포함합니다.
생성된 미디어, 로컬 소스, `.env`, 가상 환경, 캐시, 그리고 `out/`은 git에서
무시됩니다.

### 검증

이 스크립트들은 설치된 패키지가 아니라 리포지토리 트리에 들어 있습니다.
하네스 실행은 다르게 검증됩니다: `oc verify` + `oc-verifier` 에이전트(참고:
`docs/HARNESS.md`).

```bash
# validate an existing run
python3 codex/skills/openclip/scripts/verify_run_artifacts.py ./out/example/input_basename

# parallel playback/decode gate
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename --workers 6 --full-decode --write-manifest

# regenerate Codex subagent review packets
python3 codex/skills/openclip/scripts/build_subagent_packets.py ./out/example/input_basename
```

### 리뷰 워크플로

레거시 파이프라인은 `analysis/subagent_packets/` 아래에 자체 완결적인 Codex
서브에이전트 패킷을 생성합니다. 리뷰 그래프는 다음과 같습니다: `collect`
(편집자들이 독립적인 콘텐츠 주장을 수집) → `verify`(연속성/재생/산출물
게이트) → `design`(썸네일 적합성) → `adversarial`(리텐션 비평가) →
`synthesize`(모든 레인에 증거가 있을 때만 최종 게이트가 승인). 서브에이전트의
`PASS` 결과는 증명이 아니라 주장(claim)입니다 — 루트 스레드나 릴리스
프로세스는 게시하기 전에 인용된 경로, 매니페스트, 재생 증거를 반드시
검증해야 합니다.

</details>

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

OpenClip은 로컬 미디어를 처리하며, `--mock`을 사용하지 않을 때 오디오, 전사
텍스트, 자막 텍스트, 썸네일 프롬프트/참조 프레임(페르소나 사진 포함)을
OpenAI로 전송할 수 있습니다. 설정된 제공자로 처리할 권리가 없다면, 비공개·
규제 대상·제3자 미디어에 실제 제공자 모드를 실행하지 마세요. 네트워크
호출을 피해야 하는 로컬 테스트에는 `--mock`을 사용하세요.

## 라이선스

MIT. [LICENSE](LICENSE)를 참고하세요.
