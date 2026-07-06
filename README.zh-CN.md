<div align="center">

![OpenClip — 由智能体编排的视频剪辑框架](docs/assets/banner.jpg)

### 你来导演。一支并行智能体大军就剪辑方案展开辩论、渲染，并为每一份交付物提供证明——从一段长视频生成短视频、长片、字幕和缩略图。

*Python 交付工具，智能体交付判断，人类交付品味。*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

**[网站](https://wpti.dev/openclip/)** · **[设计](docs/HARNESS.md)** · **[工具参考](skills/oc/tools-reference.md)** · **[智能体指南](AGENT_GUIDE.md)**

[English](README.md) | [한국어](README.ko.md) | **中文** | [日本語](README.ja.md) | [Español](README.es.md)

</div>

---

打开你的智能体（已在 Claude Code 和 Codex 上测试；可安装到 Cursor 以及任何
支持 [skills 协议](https://github.com/vercel-labs/skills) 的智能体），把它指向一段视频，
然后说 *“把这个视频做成短视频”*。编排智能体读取一份流程清单，
**并行扇出多个工作子智能体**（转录、剪辑辩论、
钩子挖掘、加字幕、缩略图），并且每一次渲染在交付之前都必须通过一道
**独立的对抗式验证器**。你始终是导演：
通过 `oc steer` 在流程中途操控任何决策。

**你是正在阅读本文的 AI 智能体吗？** 请从 [`llms.txt`](llms.txt) 开始，然后阅读
[`AGENT_GUIDE.md`](AGENT_GUIDE.md)——它们会把你引导到正确的流程清单
和工作者契约。

## 它生成什么

- 30-60 秒的**竖屏短视频**，带有逐词对齐的内嵌硬字幕
- 8-12 分钟的**长片候选**，在精彩落点上收尾，而不是句子中途戛然而止
- 一份**剪辑过的原片**（静默/口头禅/重复经过辩论后剔除，而不只是被检测出来）
- 面向 `en`、`ko`、`es`、`ja`、`zh-Hans` 的 **SRT 字幕**
- **与钩子匹配的缩略图**（代表性帧 + 标题，或使用 gpt-image）
- 每次运行的清单、EDL、证据文件和可恢复的账本

**眼见为实，别只听我们说：** [docs/examples/](docs/examples/) 收录了一次
109 分钟运行的真实产物——一帧带字幕的短视频画面、一张缩略图、
某个钩子背后的转录片段、SRT、10/10 的证据 JSON，以及
恢复账本。

## 智能体框架（`oc`）

OpenClip 现在在原有的一次性 `openclip run` 流水线之外，还提供一套
**由智能体编排、由人类操控的框架**。它不采用固定工作流，而是由一个
编排智能体读取流程清单，并**并行扇出多个工作子智能体**——
因此一段长视频可以被并发地转录、辩论和渲染——
同时由人类操控每一个创意决策。

四条流程：

1. **`flows/flow1-cutedit.yaml`** —— LRF/LRV 代理文件 → 并行 STT（每个分块
   一个工作者）→ 一场**剪辑辩论**（提案者从口头禅/节奏/
   叙事视角展开论辩，由裁判进行调和）→ 剪辑过的原片 + 字幕。
2. **`flows/flow2-shorts.yaml`** —— 一段长视频 → 并行 STT → 钩子挖掘 →
   带字幕的 9:16 短视频 + 缩略图。
3. **`flows/flow3-assemble.yaml`** —— 将 N 段视频编织成一段长片，然后
   将它的钩子时刻挖掘成短视频（每段短视频都配有字幕 + 一张缩略图）。
4. **`flows/flow4-thumbnail.yaml`** —— 生成与每个钩子匹配的缩略图：一帧
   带内嵌标题的代表性画面，和/或一张由钩子字幕驱动、用 gpt-image 生成的
   缩略图。

关键组成部分：

- **工具：** `oc --project <DIR> <cmd>` —— `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, acp`。每条命令都会打印一行 JSON；
  `oc --help` 是权威依据。参见 `skills/oc/tools-reference.md`。
- **人类操控：** `oc steer --note "..." --scope "global | <stage> | section:<a>-<b> | <deliverable_id>"`。
  编排智能体在每一轮之前都会读取 `oc status` 中开放的指令，
  并将它们注入到工作者中。导演始终在闭环之内。
- **证据关卡：** 一个独立的 `oc-verifier` 会依据可观测的证据和对抗式失败类别
  检查每一次渲染；只有 `confirmed`（确认）的判定
  才能继续推进。一道 `SubagentStop` 钩子会拦截"没有证据就声称完成"的情况。
- **双运行时：** Claude Code（`.claude/agents`、`.claude/skills/oc`）和 Codex
  （`.agents/skills/oc*`）通过 `python3 scripts/sync_agents.py`
  从同一份源（`agents/*.md` + `skills/oc/`）生成。

快速离线自检（把 `demo.mp4` 换成你自己的任意一段短片）：

```bash
oc --project out/demo ingest --input demo.mp4 --max-seconds 60
oc --project out/demo stt --chunk 0 --mock
oc --project out/demo transcript-merge
oc --project out/demo status
```

完整设计参见 `docs/HARNESS.md`。

## 成本（真实运行）

粗略的 OpenAI 目录价估算——一场 110 分钟的演讲从头到尾（完整 STT、
5 段带硬字幕的短视频、2 个长片候选、缩略图）大约落在
**1 美元**：whisper-1 约为 $0.006/分钟音频（110 分钟约 $0.66）、gpt-image-2
每张生成的缩略图约 $0.03-0.07（抓帧缩略图免费）、
gpt-4o-mini 的字幕翻译每段片段只需几分之一美分。`--mock` 运行
花费 $0，而且恢复账本绝不会为已完成的 STT/渲染重复计费。

## 状态

OpenClip 是处于早期阶段的软件。它可以在本地使用，但在稳定版发布之前，API、输出结构（schema）和审查数据包格式都可能发生变化。

## 环境要求

- Python 3.11+
- `uv`
- `ffmpeg` 和 `ffprobe`
- 用于真实运行的 OpenAI API 密钥

Mock 运行不会调用外部 API，适合用于开发。

## 安装

每种模式的前置条件：PATH 上有 `ffmpeg`/`ffprobe`、Python 3.11+，以及用于真实运行的
`OPENAI_API_KEY`（mock 运行无需密钥）。

### A. 一条命令，任意智能体（推荐）

将编排智能体技能 + 全部 12 个工作者技能安装到 Claude Code 和
Codex（已测试），外加 Cursor 以及 [任何 skills 协议智能体](https://github.com/vercel-labs/skills)：

```bash
npx skills add Q00/openclip
```

然后安装一次 `oc` CLI（该技能也会自我检查，并在
首次使用时主动提示安装）：

```bash
uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

这会从仓库安装代码——请固定到某个发布标签（如上所示），并在敏感环境中查看
[发布说明](https://github.com/Q00/openclip/releases)。

打开你的智能体并说 *“把这个视频做成短视频”*（任何语言都可以），
或直接调用 `oc` 技能。该
技能文件夹打包了流程清单和工具参考，因此它在仓库之外也能正常使用。

### B. Claude Code 插件（加入子智能体 + 证据钩子）

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

该插件会注册 `oc-*` 子智能体类型和 `SubagentStop` 证据
关卡（仅安装技能时，工作者会以通用子智能体的身份运行，不带
钩子）。`oc` CLI 仍然来自上面的 `uv tool install`。

**Codex —— 启用证据关卡。** 技能通过模式 A 安装；若要在你自己的项目中
也获得"没有证据就声称完成"的关卡，请从本仓库复制这两个配置文件，
并保持钩子脚本路径有效：

```bash
mkdir -p .codex hooks
curl -fsSLo .codex/config.toml  https://raw.githubusercontent.com/Q00/openclip/main/.codex/config.toml
curl -fsSLo .codex/hooks.json   https://raw.githubusercontent.com/Q00/openclip/main/.codex/hooks.json
curl -fsSLo hooks/verify_evidence_hook.py https://raw.githubusercontent.com/Q00/openclip/main/hooks/verify_evidence_hook.py
```

`config.toml` 设置了 `features.hooks = true`（Codex 加载
`hooks.json` 所必需）；钩子通过 `${CODEX_PROJECT_DIR:-$PWD}` 解析。

### C. 仓库克隆（开发）

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

在仓库根目录打开 Claude Code 或 Codex——智能体、技能、命令和钩子
会自动加载。

若要进行真实的 OpenAI 运行，请在你的 shell 中设置 API 密钥：

```bash
export OPENAI_API_KEY="..."
```

你也可以把 `.env.example` 复制为 `.env` 用于本地开发。切勿提交真实密钥。

## 快速开始 —— 传统一次性流水线

> **仅限仓库克隆（模式 C）。** 这是早于智能体框架的原始固定流水线；
> 上面的框架才是推荐路径。执行 `uv tool install` 之后，直接使用
> `openclip run ...`，而不是 `uv run`。

使用真实的 OpenAI 服务运行：

```bash
uv run openclip run /path/to/input.mp4 --out ./out --strategy-approved
```

生成所有可行的短视频和长片候选，并将韩语字幕压制进短视频：

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --strategy-approved \
  --all-short-candidates \
  --all-long-candidates \
  --burn-short-ko-subtitles
```

运行一次不发起网络调用、范围受限的本地冒烟测试：

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --mock-openai \
  --max-source-seconds 660 \
  --shorts 1 \
  --long-candidates 1 \
  --strategy-approved
```

## 输出

OpenClip 将每次运行写入：

```text
OUT_DIR/{input_basename}/
```

典型输出包括：

- `shorts/*.mp4`
- `long/*.mp4`
- `edited/edited_original.mp4`
- `*.en.srt`、`*.ko.srt`、`*.es.srt`、`*.ja.srt`、`*.zh-Hans.srt`
- `*.thumbnail.png`
- `manifest.json`
- `analysis/candidate_selection.json`
- `analysis/edl.json`
- `analysis/takes_packed.md`
- `analysis/playback_checks/*`
- `analysis/subagent_packets/*`

生成的媒体、本地源视频、`.env`、虚拟环境、缓存以及 `out/` 都被 git 忽略。请不要把渲染输出提交到版本库。

## 验证 —— 传统流水线（仅限仓库克隆）

> 这些脚本随仓库目录树一起发布，而不在已安装的软件包中。框架运行的
> 验证方式不同：`oc verify` + `oc-verifier` 智能体（参见
> `docs/HARNESS.md`）。

验证一次已有的运行：

```bash
python3 codex/skills/openclip/scripts/verify_run_artifacts.py \
  ./out/example/input_basename
```

运行一道并行的播放/解码关卡：

```bash
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename \
  --workers 6 \
  --full-decode \
  --write-manifest
```

为一次已有的运行重新生成 Codex 子智能体审查数据包：

```bash
python3 codex/skills/openclip/scripts/build_subagent_packets.py \
  ./out/example/input_basename
```

## 审查工作流 —— 传统流水线

OpenClip 的传统流水线会在 `analysis/subagent_packets/` 下创建自包含的 Codex 子智能体数据包。

审查图为：

1. `collect`：短视频和长片剪辑者收集各自独立的内容主张。
2. `verify`：连续性、播放和产物关卡检查文件与清单。
3. `design`：缩略图总监检查提示词与图像的契合度。
4. `adversarial`：留存评论者查找观众可能流失的地方。
5. `synthesize`：终审关卡审查者只有在每条通道都有证据后才批准。

子智能体的 `PASS` 结果被视为主张，而非证明。根线程或发布流程必须在发布输出之前，验证所引用的路径、清单和播放证据。

## 开发

```bash
uv sync --extra dev
uv run pytest
python3 -m compileall -q src codex/skills/openclip/scripts tests
```

在开启 PR 或发布分支之前，运行一次密钥扫描：

```bash
rg -n -e "[s]k-proj-" -e "OPENAI_API_KEY\\s*=\\s*[s]k-" -e "OPEN_API_KEY\\s*=\\s*[s]k-" \
  --glob '!out/**' \
  --glob '!.env' \
  --glob '!demo.mp4' \
  --glob '!lecturer/**' \
  --glob '!.venv/**' .
```

## 安全与隐私

OpenClip 处理本地媒体，并且在不使用 `--mock-openai` 时，可能会向 OpenAI 发送音频、转录文本、字幕文本以及缩略图提示词/参考帧。

除非你有权用所配置的服务商处理相关媒体，否则不要在私密、受监管或第三方媒体上运行真实服务商模式。对于必须避免网络调用的本地测试，请使用 `--mock-openai`。

## 许可证

MIT。参见 [LICENSE](LICENSE)。
