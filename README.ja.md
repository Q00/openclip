<div align="center">

![OpenClip — エージェントがオーケストレーションする動画編集ハーネス](docs/assets/banner.jpg)

### あなたが監督する。並列に走るエージェントの艦隊がカット編集を議論し、レンダリングし、すべての成果物を証明する — 1本の長尺動画から、ショート、長尺、字幕、サムネイルまで。

*Python がツールを届け、エージェントが判断を届け、人間がセンスを届ける。*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

**[ウェブサイト](https://wpti.dev/openclip/)** · **[設計](docs/HARNESS.md)** · **[ツールリファレンス](skills/oc/tools-reference.md)** · **[エージェントガイド](AGENT_GUIDE.md)**

[English](README.md) | [한국어](README.ko.md) | [中文](README.zh-CN.md) | **日本語** | [Español](README.es.md)

</div>

---

お使いのエージェントを開き（Claude Code と Codex で動作確認済み。Cursor および
[skills プロトコル](https://github.com/vercel-labs/skills)に対応するあらゆるエージェントにインストール可能）、動画を指定して
*「この動画からショート動画を作って」*（どの言語でも動作します）と伝えるだけです。オーケストレーターエージェントがフローマニフェストを読み、
**ワーカーサブエージェントを並列にファンアウト**させ（文字起こし、カット編集の議論、
フック探し、字幕付け、サムネイル）、すべてのレンダリングは出荷される前に
**独立した敵対的検証者**を通過しなければなりません。あなたは監督のままです。
`oc steer` で任意の判断を実行の途中で操縦できます。

**あなたはこれを読んでいる AI エージェントですか？** まずは [`llms.txt`](llms.txt) から始め、次に
[`AGENT_GUIDE.md`](AGENT_GUIDE.md) を読んでください — これらが適切なフローマニフェストと
ワーカーコントラクトへとあなたを導きます。

## 何を生み出すのか

- 30〜60秒の**縦型ショート**。単語単位でタイミングを合わせた焼き込み字幕付き
- 8〜12分の**長尺候補**。文の途中ではなく、しっかりとしたオチで終わる
- **カット編集済みのオリジナル**（無音・言い淀み・繰り返しは、単に検出するのではなく議論して取り除く）
- `en`、`ko`、`es`、`ja`、`zh-Hans` の **SRT 字幕**
- **フックに合わせたサムネイル**（代表フレーム＋見出し、または gpt-image）
- 実行ごとのマニフェスト、EDL、証拠ファイル、そして再開可能な台帳

**言葉ではなく、実物を見てください：** [docs/examples/](docs/examples/) には、109分の実行から得られた
実物の成果物が入っています — 字幕付きショートのフレーム、サムネイル、フックの裏にある
文字起こしの一片、SRT、10/10 の証拠 JSON、そして再開台帳です。

## エージェントハーネス（`oc`）

OpenClip は、元々のワンショット `openclip run` パイプラインと並んで、
**エージェントがオーケストレーションし、人間が操縦するハーネス**を提供するようになりました。固定されたワークフローの代わりに、
オーケストレーターエージェントがフローマニフェストを読み、**ワーカーサブエージェントを並列に
ファンアウト**させます — こうして長尺動画は同時並行で文字起こし・議論・レンダリングされ、
その一方で人間はすべてのクリエイティブな判断を操縦します。

4つのフロー：

1. **`flows/flow1-cutedit.yaml`** — LRF/LRV プロキシ → 並列 STT（チャンクごとに
   1ワーカー）→ **カット編集の議論**（提案者が言い淀み／テンポ／
   ナラティブのレンズを通して論じ、判定者が調停する）→ カット編集済みオリジナル＋字幕。
2. **`flows/flow2-shorts.yaml`** — 1本の長尺動画 → 並列 STT → フックの発掘 →
   字幕付き 9:16 ショート＋サムネイル。
3. **`flows/flow3-assemble.yaml`** — N本の動画を織り合わせて1本の長尺にし、その後
   そのフックの瞬間を発掘してショートにする（各ショートには字幕＋サムネイルが付く）。
4. **`flows/flow4-thumbnail.yaml`** — 各フックに合わせたサムネイルを生成する：
   焼き込まれた見出し付きの代表フレーム、および／またはフックのキャプションをもとに生成される
   gpt-image サムネイル。

主要な構成要素：

- **ツール：** `oc --project <DIR> <cmd>` — `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, acp`。それぞれが JSON 1行を出力します。
  `oc --help` が正式なリファレンスです。`skills/oc/tools-reference.md` を参照してください。
- **人間による操縦：** `oc steer --note "..." --scope "global | <stage> | section:<a>-<b> | <deliverable_id>"`。
  オーケストレーターは各ウェーブの前に `oc status` の未解決ディレクティブを読み、
  それらをワーカーに注入します。監督は常にループの中にいます。
- **証拠ゲート：** 独立した `oc-verifier` が、すべてのレンダリングを観測可能な証拠と
  敵対的な失敗クラスに照らして検査します。`confirmed` の判定のみが
  先へ進みます。`SubagentStop` フックが「証拠なしの完了」をブロックします。
- **デュアルランタイム：** Claude Code（`.claude/agents`、`.claude/skills/oc`）と Codex
  （`.agents/skills/oc*`）は、`python3 scripts/sync_agents.py` を通じて1つのソース
  （`agents/*.md` ＋ `skills/oc/`）から生成されます。

手早いオフラインの動作確認（`demo.mp4` をお手元の任意の短いクリップに置き換えてください）：

```bash
oc --project out/demo ingest --input demo.mp4 --max-seconds 60
oc --project out/demo stt --chunk 0 --mock
oc --project out/demo transcript-merge
oc --project out/demo status
```

完全な設計については `docs/HARNESS.md` を参照してください。

## コスト（実際の実行）

OpenAI の定価でのおおまかな目安 — 110分のトークをエンドツーエンドで処理（フル STT、
焼き込み字幕付きショート5本、長尺候補2本、サムネイル）した場合、およそ
**$1** に収まります：whisper-1 は音声1分あたり約 $0.006（110分で約 $0.66）、gpt-image-2
は生成サムネイル1枚あたり約 $0.03〜0.07（フレーム切り出しのサムネイルは無料）、
gpt-4o-mini の字幕翻訳はクリップあたり1セントの何分の1かです。`--mock` の実行は
コスト $0 で、再開台帳が完了済みの STT／レンダリングを二重に課金することは決してありません。

## ステータス

OpenClip は初期段階のソフトウェアです。ローカルで利用可能ですが、API、出力スキーマ、レビューパケットのフォーマットは、安定版リリースの前に変更される可能性があります。

## 要件

- Python 3.11+
- `uv`
- `ffmpeg` と `ffprobe`
- 実際の実行のための OpenAI API キー

モック実行は外部 API を呼び出さず、開発に便利です。

## インストール

すべてのモードの前提条件：PATH 上の `ffmpeg`／`ffprobe`、Python 3.11+、そして
実際の実行のための `OPENAI_API_KEY`（モック実行にはキーは不要です）。

### A. 1つのコマンドで、どのエージェントでも（推奨）

オーケストレータースキル＋全12のワーカースキルを Claude Code と
Codex（動作確認済み）、さらに Cursor と [skills プロトコルに対応するあらゆるエージェント](https://github.com/vercel-labs/skills)にインストールします：

```bash
npx skills add Q00/openclip
```

続いて `oc` CLI を一度だけインストールします（スキルも自己チェックを行い、
初回利用時にこれを提案します）：

```bash
uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

これはリポジトリからコードをインストールします — リリースタグ（上記で示したもの）に固定し、
機密性の高い環境では[リリースノート](https://github.com/Q00/openclip/releases)を確認してください。

お使いのエージェントを開き、*「この動画からショート動画を作って」*（どの言語でも動作します）と伝えるか、
`oc` スキルを直接呼び出してください。
スキルフォルダはフローマニフェストとツールリファレンスを同梱しているので、
リポジトリの外でも動作します。

### B. Claude Code プラグイン（サブエージェント＋証拠フックを追加）

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

このプラグインは `oc-*` サブエージェントタイプと `SubagentStop` の証拠ゲートを
登録します（スキルのみのインストールでは、ワーカーはフックなしの汎用サブエージェントとして
実行されます）。`oc` CLI は依然として上記の `uv tool install` から入手します。

**Codex — 証拠ゲートを有効にする。** スキルはモード A でインストールされます。ご自身のプロジェクトでも
「証拠なしの完了」ゲートを得るには、このリポジトリから2つの設定ファイルをコピーし、
フックスクリプトのパスを有効に保ってください：

```bash
mkdir -p .codex hooks
curl -fsSLo .codex/config.toml  https://raw.githubusercontent.com/Q00/openclip/main/.codex/config.toml
curl -fsSLo .codex/hooks.json   https://raw.githubusercontent.com/Q00/openclip/main/.codex/hooks.json
curl -fsSLo hooks/verify_evidence_hook.py https://raw.githubusercontent.com/Q00/openclip/main/hooks/verify_evidence_hook.py
```

`config.toml` は `features.hooks = true` を設定します（Codex が `hooks.json` を
読み込むために必須）。フックは `${CODEX_PROJECT_DIR:-$PWD}` を通じて解決されます。

### C. リポジトリのクローン（開発）

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

リポジトリのルートで Claude Code または Codex を開いてください — エージェント、スキル、コマンド、フックが
自動的に読み込まれます。

実際の OpenAI 実行のために、シェルで API キーを設定してください：

```bash
export OPENAI_API_KEY="..."
```

ローカル開発のために `.env.example` を `.env` にコピーすることもできます。実際のキーを決してコミットしないでください。

## クイックスタート — レガシーのワンショットパイプライン

> **リポジトリのクローン（モード C）のみ。** これはエージェントハーネスに先立つ、元々の固定パイプラインです。
> 上記のハーネスが推奨される道筋です。`uv tool install` の後は、
> `uv run` の代わりに `openclip run ...` を直接使ってください。

実際の OpenAI サービスで実行する：

```bash
uv run openclip run /path/to/input.mp4 --out ./out --strategy-approved
```

実行可能なすべてのショートと長尺の候補を生成し、ショートに韓国語字幕を焼き込む：

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --strategy-approved \
  --all-short-candidates \
  --all-long-candidates \
  --burn-short-ko-subtitles
```

ネットワーク呼び出しなしで、範囲を限定したローカルのスモークテストを実行する：

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --mock-openai \
  --max-source-seconds 660 \
  --shorts 1 \
  --long-candidates 1 \
  --strategy-approved
```

## 出力

OpenClip は各実行を次の場所に書き出します：

```text
OUT_DIR/{input_basename}/
```

典型的な出力には次のものが含まれます：

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

生成されたメディア、ローカルのソース動画、`.env`、仮想環境、キャッシュ、そして `out/` は git で無視されます。レンダリングされた出力をコミットに含めないでください。

## 検証 — レガシーパイプライン（リポジトリのクローンのみ）

> これらのスクリプトはリポジトリツリーに同梱されており、インストールされるパッケージには含まれません。ハーネスの実行は
> 別の方法で検証されます：`oc verify` ＋ `oc-verifier` エージェント（`docs/HARNESS.md` を
> 参照）。

既存の実行を検証する：

```bash
python3 codex/skills/openclip/scripts/verify_run_artifacts.py \
  ./out/example/input_basename
```

並列の再生／デコードゲートを実行する：

```bash
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename \
  --workers 6 \
  --full-decode \
  --write-manifest
```

既存の実行に対して Codex サブエージェントのレビューパケットを再生成する：

```bash
python3 codex/skills/openclip/scripts/build_subagent_packets.py \
  ./out/example/input_basename
```

## レビューワークフロー — レガシーパイプライン

OpenClip のレガシーパイプラインは、`analysis/subagent_packets/` の下に自己完結型の Codex サブエージェントパケットを作成します。

レビューグラフは次のとおりです：

1. `collect`：ショートと長尺のエディターが、独立したコンテンツの主張を収集する。
2. `verify`：連続性、再生、アーティファクトのゲートがファイルとマニフェストを検査する。
3. `design`：サムネイルディレクターがプロンプトと画像の適合性を検査する。
4. `adversarial`：リテンション批評役が、視聴者が離脱しそうな箇所を探す。
5. `synthesize`：最終ゲートのレビュアーが、すべてのレーンに証拠が揃った後にのみ承認する。

サブエージェントの `PASS` の結果は、証明ではなく主張として扱われます。ルートスレッドまたはリリースプロセスは、出力を公開する前に、引用されたパス、マニフェスト、再生の証拠を検証しなければなりません。

## 開発

```bash
uv sync --extra dev
uv run pytest
python3 -m compileall -q src codex/skills/openclip/scripts tests
```

PR を開いたりブランチを公開したりする前に、シークレットスキャンを実行してください：

```bash
rg -n -e "[s]k-proj-" -e "OPENAI_API_KEY\\s*=\\s*[s]k-" -e "OPEN_API_KEY\\s*=\\s*[s]k-" \
  --glob '!out/**' \
  --glob '!.env' \
  --glob '!demo.mp4' \
  --glob '!lecturer/**' \
  --glob '!.venv/**' .
```

## セキュリティとプライバシー

OpenClip はローカルのメディアを処理し、`--mock-openai` を使用しない場合、音声、文字起こしテキスト、字幕テキスト、サムネイルのプロンプト／参照フレームを OpenAI に送信することがあります。

処理する権利を持っていない限り、プライベート、規制対象、または第三者のメディアに対して実際のプロバイダーモードを実行しないでください。ネットワーク呼び出しを避けなければならないローカルテストには `--mock-openai` を使用してください。

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。
