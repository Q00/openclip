<div align="center">

![OpenClip — 由智能体编排的视频剪辑框架](docs/assets/banner.jpg)

### 你来导演。一支并行智能体大军就剪辑方案展开辩论、渲染，并为每一份交付物提供证明——从一段长视频生成短视频、长片、字幕和缩略图。

*Python 交付工具，智能体交付判断，人类交付品味。*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![PyPI](https://img.shields.io/pypi/v/openclip-agent?label=pypi)](https://pypi.org/project/openclip-agent/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install openclip-agent
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

OpenClip 也是 [ContractPlane](https://contractplane.dev) 的首个完整媒体
Domain Pack。同一组能力、内部角色、策略、证据门和流程拓扑会作为可移植契约
一同发布。可使用 `oc domain-pack show` 查看，或通过
`oc domain-pack export --out pack` 导出。

**你是正在阅读本文的 AI 智能体吗？** 请从 [`llms.txt`](llms.txt) 开始，然后阅读
[`AGENT_GUIDE.md`](AGENT_GUIDE.md)——它们会把你引导到正确的流程清单
和工作者契约。

## 快速上手——你的第一次运行

安装完成后（见下文），你不需要运行一条流水线——而是直接和你的智能体对话。

**1. 打开你的智能体**（Claude Code 或 Codex），在放着你视频的文件夹中。

**2. 调用 `oc` 技能并说明你想要的结果**：

```
you    $oc 把 ./talk.mp4 做成短视频

agent  正在读取 flow2-shorts。将音频切分成多个分块并派发
       STT 工作者……转录已合并（110 分钟）。正在跨分段挖掘
       钩子——排出了 6 个候选。我打算把排名前 3 的钩子剪成
       9:16 竖屏短视频，每段都带内嵌字幕和一张缩略图。
       渲染前需要你确认一下钩子列表吗？  [you：可以，去掉 #4]
       渲染中……每段片段都通过了证据关卡（时长、画幅、
       音频、字幕时间轴）。完成——见 out/talk/shorts/。
```

编排智能体会在真正需要决策的节点上向你确认（选哪些钩子、怎么剪、
用哪张缩略图），并且会拦截任何没有证据支撑的“完成”。

**3. 收集产物。** 所有内容都会落在你的项目目录下
（这里是 `out/talk/`）：

| 文件夹 | 内容 |
| --- | --- |
| `shorts/` | 带内嵌字幕的竖屏 `.mp4` 片段 |
| `thumbnails/` | 每个交付物一张精心设计的缩略图 |
| `subs/` | `.srt` 字幕文件（按语言区分） |
| `evidence/` | 每一次渲染的验证器证明 JSON |

**成本：** 一场完整 110 分钟的演讲（STT + 若干短视频 + 缩略图）按 OpenAI
目录价大约花费 **1 美元**。在任意位置加上 `--mock`，成本就是 **0 美元**——
非常适合第一次离线试跑（费用明细见[成本](#成本)）。

### 只想用 CLI，不用智能体？

智能体所做的每一步都是一条普通的 `oc` 命令。下面这套流程不需要 API
密钥、也不产生任何费用——STT 以 `--mock` 运行，剪辑和缩略图都是
本地 ffmpeg 操作（不调用 OpenAI）：

```bash
oc --project out/talk ingest --input talk.mp4 --max-seconds 120
oc --project out/talk stt --chunk 0 --mock
oc --project out/talk transcript-merge
oc --project out/talk clip --input talk.mp4 --start 30 --end 75 --aspect 9:16 --id s1
oc --project out/talk thumbnail --input talk.mp4 --start 30 --end 75 --title "The one trick"
oc --project out/talk status
```

有演讲者的照片？把缩略图那一行换成不依赖 AI 的设计版切图——
同样免费，一次性下载模型后也能离线运行：
`… thumbnail --composite --persona speaker.jpg --style editorial --title "…"`。

`oc --help` 是权威的命令列表。每个动词的说明见
[`skills/oc/tools-reference.md`](skills/oc/tools-reference.md)。

## 它生成什么

- 30-60 秒的**竖屏短视频**，带有逐词对齐的内嵌硬字幕
- 8-12 分钟的**长片候选**，在精彩落点上收尾，而不是句子中途戛然而止
- 一份**剪辑过的原片**（静默/口头禅/重复经过辩论后剔除，而不只是被检测出来）
- 面向 `en`、`ko`、`es`、`ja`、`zh-Hans` 的 **SRT 字幕**
- **精心设计的缩略图**——通过 `--persona` 保留真实的演讲者身份，
  提供经过策划的 `--style` 预设，零成本、不依赖 AI 的 `--composite` 切图，
  或是 gpt-image 生成；框架还会在多轮迭代中学习你频道的品味
  （`oc taste`）
- 每次运行的清单、EDL、证据文件和可恢复的账本

**眼见为实，别只听我们说：** [docs/examples/](docs/examples/) 收录了一次
109 分钟运行的真实产物——一帧带字幕的短视频画面、一张缩略图、
某个钩子背后的转录片段、SRT、10/10 的证据 JSON，以及
恢复账本。

## 安装

每种模式的前置条件：PATH 上有 `ffmpeg`/`ffprobe`、Python 3.11+，以及用于真实运行的
`OPENAI_API_KEY`（mock 运行无需密钥）。

**你需要哪种安装方式？**

| 你是…… | 安装方式 | 你会得到 |
| --- | --- | --- |
| **Claude Code** 用户 | 插件（B） | 子智能体类型 + 证据关卡钩子 |
| 使用 **Codex / Cursor / 其他 skills 协议智能体** | `npx skills add`（A） | 编排智能体 + 工作者技能 |
| **只要 CLI**（不用智能体） | PyPI（`uv tool install`） | 只有 `oc` 命令 |

三种方式可以组合使用——技能/插件打包了智能体，CLI 提供它们调用的
`oc` 工具。

### A. 技能目录，适用于任意智能体（推荐）

适用于 Codex、Cursor，以及[任何 skills 协议智能体](https://github.com/vercel-labs/skills)。
安装编排智能体和全部工作者技能：

```bash
npx skills add Q00/openclip
```

然后安装一次 `oc` CLI（该技能会自我检查，并在首次使用时
主动提示安装）：

```bash
uv tool install openclip-agent      # or: pip install openclip-agent
```

打开你的智能体并调用 *`$oc 把这段视频做成短视频`*。只使用自然语言也可以触发，但首次运行时显式调用技能最可靠。该技能文件夹打包了流程清单和工具参考，
因此它在仓库之外也能正常使用。

### B. Claude Code 插件（加入子智能体 + 证据钩子）

适用于 Claude Code 用户。会注册 `oc-*` 子智能体类型和 `SubagentStop`
证据关卡（仅安装技能时，工作者会以通用子智能体的身份运行，不带
钩子）：

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

`oc` CLI 仍然来自上面的 `uv tool install openclip-agent`。

**Codex——启用证据关卡。** 技能通过模式 A 安装；若要在你自己的项目中
也获得“没有证据就声称完成”的关卡，请从本仓库复制这两个配置文件，
并保持钩子脚本路径有效：

```bash
mkdir -p .codex hooks
curl -fsSLo .codex/config.toml  https://raw.githubusercontent.com/Q00/openclip/main/.codex/config.toml
curl -fsSLo .codex/hooks.json   https://raw.githubusercontent.com/Q00/openclip/main/.codex/hooks.json
curl -fsSLo hooks/verify_evidence_hook.py https://raw.githubusercontent.com/Q00/openclip/main/hooks/verify_evidence_hook.py
```

`config.toml` 设置了 `features.hooks = true`（Codex 加载
`hooks.json` 所必需）；钩子通过 `${CODEX_PROJECT_DIR:-$PWD}` 解析。

### C. 只要 CLI（PyPI）

如果你只想要 `oc`/`openclip` 工具，不需要智能体：

```bash
uv tool install openclip-agent      # or: pip install openclip-agent
```

### D. 仓库克隆（开发）

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

在仓库根目录打开 Claude Code 或 Codex——智能体、技能、命令和钩子
会自动加载。若要进行真实的 OpenAI 运行，请在 shell 中设置密钥
（或把 `.env.example` 复制为 `.env`；切勿提交真实密钥）：

```bash
export OPENAI_API_KEY="..."
```

## 智能体框架（`oc`）

编排智能体不采用固定工作流，而是读取一份流程清单，并行扇出多个
工作子智能体，同时由人类操控每一个创意决策。[`agents/`](agents/) 目录下
有十三份角色定义：一个编排智能体，外加十二个专职工作者。

四条流程：

1. **`flows/flow1-cutedit.yaml`** —— LRF/LRV 代理文件 → 并行 STT →
   一场**剪辑辩论**（提案者从口头禅/节奏/叙事视角展开论辩，
   由裁判进行调和）→ 剪辑过的原片 + 字幕。
2. **`flows/flow2-shorts.yaml`** —— 一段长视频 → 并行 STT → 钩子挖掘 →
   带字幕的 9:16 短视频 + 缩略图。
3. **`flows/flow3-assemble.yaml`** —— 将 N 段视频编织成一段长片，然后
   将它的钩子挖掘成短视频（每段短视频都配有字幕 + 一张缩略图）。
4. **`flows/flow4-thumbnail.yaml`** —— 生成与每个钩子匹配的缩略图：一帧
   带内嵌标题的代表性画面，和/或一张由钩子字幕驱动、用 gpt-image 生成的
   缩略图。

关键组成部分：

- **工具：** `oc --project <DIR> <cmd>` —— `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, taste, acp`。每条命令都会打印一行 JSON；
  `oc --help` 是权威依据。参见 `skills/oc/tools-reference.md`。
- **人类操控：** `oc steer --note "..." --scope "global | <stage> | section:<a>-<b> | <deliverable_id>"`。
  编排智能体在每一轮之前都会读取 `oc status` 中开放的指令，
  并将它们注入到工作者中。导演始终在闭环之内。
- **证据关卡：** 一个独立的 `oc-verifier` 会依据可观测的证据和对抗式失败类别
  检查每一次渲染；只有 `confirmed`（确认）的判定
  才能继续推进。一道 `SubagentStop` 钩子会拦截“没有证据就声称完成”的情况。
- **双运行时：** Claude Code（`.claude/agents`、`.claude/skills/oc`）和 Codex
  （`.agents/skills/oc*`）通过 `python3 scripts/sync_agents.py`
  从同一份源（`agents/*.md` + `skills/oc/`）生成。

如果想要一次可运行的离线自检，参见上文的
[CLI 命令序列](#只想用-cli不用智能体)；完整设计见 `docs/HARNESS.md`。

### v0.2 新增：精心设计的缩略图 + 可学习的品味

**精心设计的缩略图**（`oc thumbnail`）看起来像经过美术指导，而不是随手抓帧：
`--persona <photo|dir>` 保留**真实的演讲者身份**（gpt-image 编辑）；
`--style clean|editorial|bold|keynote` 可选取经过策划的预设；
`--composite` 是**不依赖 AI 的路径**（在工作室背景上做 rembg 抠图并
排版标题——零生成像素、**零成本**、即时完成）；`--render-text` 让
gpt-image-2 自己排版标题（结果具有概率性——契约会在每次渲染时校验拼写）；
`--prompt-note "..."` 可以为单次渲染添加额外的美术指导。

**`oc taste`**（`show|note|evolve|revert`）是一个**个性化学习循环**——
框架会学习你频道的风格。你可以为渲染出的缩略图记录评判
（`taste note`）；一个智能体会把这些评判反映进**下一代指导方案**
（`taste evolve`），并附带逐代记分板、谱系记录，以及在新一代表现更差时
的回滚（`taste revert`）。指导方案按领域分别保存；存储路径依次解析
`$OPENCLIP_HOME` → 仓库内的 `toolbox/`（团队可选开启）→ `~/.openclip`
（插件默认路径）。

## 成本

粗略的 OpenAI 目录价估算——一场 110 分钟的演讲从头到尾（完整 STT、
5 段带内嵌字幕的短视频、2 个长片候选、缩略图）大约落在
**1 美元**：whisper-1 约为 $0.006/分钟音频（110 分钟约 $0.66）、gpt-image-2
每张生成的缩略图约 $0.03-0.07（抓帧缩略图和 `--composite` 缩略图都
免费）、gpt-4o-mini 的字幕翻译每段片段只需几分之一美分。`--mock` 运行
花费 $0，而且恢复账本绝不会为已完成的 STT/渲染重复计费。

## 环境要求与状态

- Python 3.11+、`uv`，以及 PATH 上的 `ffmpeg`/`ffprobe`
- 用于真实运行的 OpenAI API 密钥（mock 运行不会调用任何外部 API）

OpenClip 是处于早期阶段的软件。它可以在本地使用，但在稳定版发布之前，
API、输出结构（schema）和审查数据包格式都可能发生变化。

## 常见问题排查

- **`ffmpeg`/`ffprobe: command not found`**——安装 ffmpeg，并确保两个
  可执行文件都在你的 `PATH` 上（运行 `ffmpeg -version` 应该有输出）。
  每一条渲染路径都会调用它们。
- **`OPENAI_API_KEY` 缺失**——真实运行前请设置它
  （`export OPENAI_API_KEY=...`）。`--mock` 模式不需要密钥：mock 模式
  不会发起任何网络调用。
- **真实运行前必须取消设置 `OPENAI_BASE_URL`**——CLI 代理的 base URL
  会破坏 Whisper 和图像调用。真实运行前先取消设置
  （`unset OPENAI_BASE_URL`）。
- **首次运行 `--composite` 会暂停**——它会下载一次 rembg 背景去除模型，
  之后就能完全离线运行。需要 PATH 上有（来自 `uv` 的）`uvx`。
- **真实运行“成功”了，但文件却不见了**——这种情况不该被交付：
  证据关卡只有在判定为 `confirmed` 时才会放行。请检查失败交付物对应的
  `evidence/*.json`。

<details>
<summary><strong>传统一次性流水线（<code>openclip run</code>）</strong>——原始的固定流水线，仍然受支持</summary>

> **仅限仓库克隆（模式 D）。** 这是早于智能体框架的原始固定流水线；
> 上面的框架才是推荐路径。执行 `uv tool install` 之后，请直接使用
> `openclip run ...`，而不是 `uv run`。

### 快速开始

使用真实的 OpenAI 服务运行：

```bash
uv run openclip run /path/to/input.mp4 --out ./out --strategy-approved
```

生成所有可行的短视频和长片候选，并配上简体中文字幕：

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --strategy-approved \
  --all-short-candidates \
  --all-long-candidates \
  --subtitle-langs zh-Hans
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

### 输出

每次运行都会写入 `OUT_DIR/{input_basename}/` 目录下。典型输出包括
`shorts/*.mp4`、`long/*.mp4`、`edited/edited_original.mp4`、按语言区分的 SRT
（`*.en.srt`、`*.ko.srt`、`*.es.srt`、`*.ja.srt`、`*.zh-Hans.srt`）、
`*.thumbnail.png`、`manifest.json`，以及 `analysis/`（candidate_selection.json、
edl.json、takes_packed.md、playback_checks/、subagent_packets/）。生成的
媒体、本地源视频、`.env`、虚拟环境、缓存以及 `out/` 都被 git 忽略。

### 验证

这些脚本随仓库目录树一起发布，而不在已安装的软件包中。框架运行的
验证方式不同：`oc verify` + `oc-verifier` 智能体（参见 `docs/HARNESS.md`）。

```bash
# validate an existing run
python3 codex/skills/openclip/scripts/verify_run_artifacts.py ./out/example/input_basename

# parallel playback/decode gate
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename --workers 6 --full-decode --write-manifest

# regenerate Codex subagent review packets
python3 codex/skills/openclip/scripts/build_subagent_packets.py ./out/example/input_basename
```

### 审查工作流

传统流水线会在 `analysis/subagent_packets/` 下创建自包含的 Codex 子智能体
数据包。审查图为：`collect`（编辑者收集各自独立的内容主张）→ `verify`
（连续性/播放/产物关卡）→ `design`（缩略图契合度）→ `adversarial`
（留存评论者）→ `synthesize`（终审关卡只有在每条通道都有证据后才批准）。
子智能体的 `PASS` 结果被视为主张，而非证明——根线程或发布流程必须在
发布之前，验证所引用的路径、清单和播放证据。

</details>

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

OpenClip 处理本地媒体，并且在不使用 `--mock` 时，可能会向 OpenAI 发送
音频、转录文本、字幕文本，以及缩略图提示词/参考帧（包括人物照片）。

除非你有权用所配置的服务商处理相关媒体，否则不要在私密、受监管或
第三方媒体上运行真实服务商模式。对于必须避免网络调用的本地测试，
请使用 `--mock`。

## 许可证

MIT。参见 [LICENSE](LICENSE)。
