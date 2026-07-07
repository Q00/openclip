<div align="center">

![OpenClip — エージェントがオーケストレーションする動画編集ハーネス](docs/assets/banner.jpg)

### あなたが監督する。並列に走るエージェントの艦隊がカット編集を議論し、レンダリングし、すべての成果物を証明する — 1本の長尺動画から、ショート、長尺、字幕、サムネイルまで。

*Python がツールを届け、エージェントが判断を届け、人間がセンスを届ける。*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![PyPI](https://img.shields.io/pypi/v/openclip-agent?label=pypi)](https://pypi.org/project/openclip-agent/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install openclip-agent
```

**[ウェブサイト](https://wpti.dev/openclip/)** · **[設計](docs/HARNESS.md)** · **[ツールリファレンス](skills/oc/tools-reference.md)** · **[エージェントガイド](AGENT_GUIDE.md)**

[English](README.md) | [한국어](README.ko.md) | [中文](README.zh-CN.md) | **日本語** | [Español](README.es.md)

</div>

---

お使いのエージェントを開き（Claude Code と Codex で動作確認済み。Cursor および
[skills プロトコル](https://github.com/vercel-labs/skills)に対応するあらゆるエージェントにインストール可能）、動画を指定して
*「この動画からショート動画を作って」*と伝えるだけです。オーケストレーターエージェントがフローマニフェストを読み、
**ワーカーサブエージェントを並列にファンアウト**させ（文字起こし、カット編集の議論、
フック探し、字幕付け、サムネイル）、すべてのレンダリングは出荷される前に
**独立した敵対的検証者**を通過しなければなりません。あなたは監督のままです。
`oc steer` で任意の判断を実行の途中で操縦できます。

**あなたはこれを読んでいる AI エージェントですか？** まずは [`llms.txt`](llms.txt) から始め、次に
[`AGENT_GUIDE.md`](AGENT_GUIDE.md) を読んでください — これらが適切なフローマニフェストと
ワーカーコントラクトへとあなたを導きます。

## はじめに — 最初の実行

インストール後（後述）、パイプラインを実行するのではなく、エージェントと会話します。

**1. お使いのエージェントを開きます**（Claude Code または Codex）。動画があるフォルダで開いてください。

**2. やりたいことを、どの言語ででも伝えます**：

```
you    ./talk.mp4 からショート動画を作って

agent  flow2-shorts を読み込み中です。音声をチャンクに分割し、STT ワーカーを
       ファンアウトしています… 文字起こしを統合しました（110分）。
       セクション全体からフックを探索中 — 候補6件をランク付けしました。
       上位3件を、字幕焼き込みとサムネイル付きの 9:16 ショートとして
       カットします。レンダリング前にフックリストを承認しますか？
       [you: yes, drop #4]
       レンダリング中… 各クリップは証拠ゲート（尺、アスペクト比、
       音声、字幕タイミング）をクリアしました。完了 — out/talk/shorts/ を
       ご覧ください。
```

オーケストレーターは本当に重要な意思決定のポイント（どのフックか、どのカットか、
どのサムネイルか）で確認を求め、証拠が伴わない「完了」は必ずブロックします。

**3. 出力を確認します。** すべてはプロジェクトディレクトリの下に生成されます
（ここでは `out/talk/`）：

| フォルダ | 内容 |
| --- | --- |
| `shorts/` | 焼き込み字幕付きの縦型 `.mp4` クリップ |
| `thumbnails/` | 成果物ごとにデザインされたサムネイル1枚 |
| `subs/` | 言語ごとの `.srt` サイドカー |
| `evidence/` | すべてのレンダリングに対する検証者の証拠 JSON |

**コスト：** 110分のトーク全体（STT + ショート数本 + サムネイル）は、OpenAI の定価で
およそ **$1** です。どこにでも `--mock` を付ければコストは **$0** になります —
最初のオフライントライアルに最適です（内訳は[コスト](#コスト)を参照）。

### CLIのみで進めたい方へ（エージェント不要）

エージェントが行う各ステップは、そのまま普通の `oc` コマンドです。次のシーケンスには
API キーは不要で、コストもかかりません — STT は `--mock` で実行され、カットと
サムネイルはローカルの ffmpeg 処理です（OpenAI 呼び出しなし）：

```bash
oc --project out/talk ingest --input talk.mp4 --max-seconds 120
oc --project out/talk stt --chunk 0 --mock
oc --project out/talk transcript-merge
oc --project out/talk clip --input talk.mp4 --start 30 --end 75 --aspect 9:16 --id s1
oc --project out/talk thumbnail --input talk.mp4 --start 30 --end 75 --title "The one trick"
oc --project out/talk status
```

登壇者の写真をお持ちですか？ サムネイルの行を、デザインされた no-AI のカットアウトに
差し替えられます — こちらも無料で、モデルの初回ダウンロード以降はオフラインで動作します：
`… thumbnail --composite --persona speaker.jpg --style editorial --title "…"`。

`oc --help` が正式なコマンド一覧です。すべてのコマンドについては
[`skills/oc/tools-reference.md`](skills/oc/tools-reference.md) を参照してください。

## 何を生み出すのか

- 30〜60秒の**縦型ショート**。単語単位でタイミングを合わせた焼き込み字幕付き
- 8〜12分の**長尺候補**。文の途中ではなく、しっかりとしたオチで終わる
- **カット編集済みのオリジナル**（無音・言い淀み・繰り返しは、単に検出するのではなく議論して取り除く）
- `en`、`ko`、`es`、`ja`、`zh-Hans` の **SRT 字幕**
- **デザインされたサムネイル** — `--persona` による**実在の登壇者本人**のアイデンティティ保持
  （gpt-image 編集）、厳選された `--style` プリセット、生成コスト**ゼロ**の no-AI
  `--composite` カットアウト、または gpt-image レンダー。ハーネスは何ラウンドも重ねるうちに
  あなたのチャンネルの好みを学習します（`oc taste`）
- 実行ごとのマニフェスト、EDL、証拠ファイル、そして再開可能な台帳

**言葉ではなく、実物を見てください：** [docs/examples/](docs/examples/) には、109分の実行から得られた
実物の成果物が入っています — 字幕付きショートのフレーム、サムネイル、フックの裏にある
文字起こしの一片、SRT、10/10 の証拠 JSON、そして再開台帳です。

## インストール

すべてのモードの前提条件：PATH 上の `ffmpeg`／`ffprobe`、Python 3.11+、そして
実際の実行のための `OPENAI_API_KEY`（モック実行にはキーは不要です）。

**どのインストール方法がよいですか？**

| あなたは… | インストール | 得られるもの |
| --- | --- | --- |
| **Claude Code** ユーザー | プラグイン（B） | サブエージェントの種類 + 証拠ゲートフック |
| **Codex / Cursor / その他 skills プロトコル対応エージェント** | `npx skills add`（A） | オーケストレーター + ワーカースキル |
| **CLI だけ**（エージェントなし） | PyPI（`uv tool install`） | `oc` コマンドのみ |

3つはすべて組み合わせられます — skills／プラグインがエージェントを同梱し、CLI がそれらの
呼び出す `oc` ツールを提供します。

### A. スキルカタログ、どのエージェントでも（推奨）

Codex、Cursor、そして[skills プロトコルに対応するあらゆるエージェント](https://github.com/vercel-labs/skills)向けです。
オーケストレーターと全ワーカースキルをインストールします：

```bash
npx skills add Q00/openclip
```

続いて `oc` CLI を一度だけインストールします（スキルも自己チェックを行い、
初回利用時にこれを提案します）：

```bash
uv tool install openclip-agent      # または: pip install openclip-agent
```

お使いのエージェントを開き、*「この動画からショート動画を作って」*（どの言語でも動作します）と伝えるか、
`oc` スキルを直接呼び出してください。スキルフォルダはフローマニフェストと
ツールリファレンスを同梱しているので、リポジトリの外でも動作します。

### B. Claude Code プラグイン（サブエージェント＋証拠フックを追加）

Claude Code ユーザー向けです。`oc-*` サブエージェントタイプと `SubagentStop` の
証拠ゲートを登録します（スキルのみのインストールでは、ワーカーはフックなしの
汎用サブエージェントとして実行されます）：

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

`oc` CLI は依然として上記の `uv tool install openclip-agent` から入手します。

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

### C. CLI だけ（PyPI）

エージェントなしで `oc`／`openclip` ツールだけが欲しい場合：

```bash
uv tool install openclip-agent      # または: pip install openclip-agent
```

### D. リポジトリのクローン（開発）

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

リポジトリのルートで Claude Code または Codex を開いてください — エージェント、スキル、コマンド、
フックが自動的に読み込まれます。実際の OpenAI 実行のためには、シェルで API キーを
設定してください（または `.env.example` を `.env` にコピーしてください。実際のキーは
決してコミットしないでください）：

```bash
export OPENAI_API_KEY="..."
```

## エージェントハーネス（`oc`）

固定されたワークフローの代わりに、オーケストレーターエージェントがフローマニフェストを読み、
人間があらゆるクリエイティブな判断を操縦する一方で、ワーカーサブエージェントを並列にファンアウト
させます。[`agents/`](agents/) には13のロール定義があります — オーケストレーター1つと、
専門化されたワーカー12種類です。

4つのフロー：

1. **`flows/flow1-cutedit.yaml`** — LRF/LRV プロキシ → 並列 STT → **カット編集の議論**（提案者が言い淀み／テンポ／ナラティブのレンズを通して論じ、判定者が調停する）→ カット編集済みオリジナル＋字幕。
2. **`flows/flow2-shorts.yaml`** — 1本の長尺動画 → 並列 STT → フックの発掘 → 字幕付き 9:16 ショート＋サムネイル。
3. **`flows/flow3-assemble.yaml`** — N本の動画を織り合わせて1本の長尺にし、そのフックの瞬間を発掘してショートにする（各ショートには字幕＋サムネイルが付く）。
4. **`flows/flow4-thumbnail.yaml`** — 各フックに合わせたサムネイル：焼き込まれた見出し付きの代表フレーム、および／またはフックのキャプションをもとに生成される gpt-image サムネイル。

主要な構成要素：

- **ツール：** `oc --project <DIR> <cmd>` — `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, taste, acp`。それぞれが JSON 1行を出力します。
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

実行可能なオフラインの動作確認については、上記の[CLI手順](#cliのみで進めたい方へエージェント不要)を
参照してください。完全な設計は `docs/HARNESS.md` にあります。

### v0.2 の新機能：デザインされたサムネイルと学習される好み

**デザインされたサムネイル**（`oc thumbnail`）は、フレーム切り出しではなく、アートディレクションされた
見た目になります：`--persona <photo|dir>` が**実在の登壇者本人**のアイデンティティを保持し
（gpt-image 編集）、`--style clean|editorial|bold|keynote` が厳選されたプリセットを選び、
`--composite` は**no-AI の経路**です（rembg によるカットアウトをスタジオ背景に重ね、活字の見出しを
乗せます — 生成ピクセルはゼロ、**コストもゼロ**、即座に完了）。`--render-text` は gpt-image-2 自身に
見出しを組ませます（確率的な処理のため、レンダリングごとにコントラクトがスペルを検証します）。
`--prompt-note "..."` はレンダリングごとにアートディレクションを追加できます。

**`oc taste`**（`show|note|evolve|revert`）は**パーソナライゼーションのループ**です — ハーネスが
あなたのチャンネルの見た目を学習します。レンダリングされたサムネイルに対する判定を記録し
（`taste note`）、エージェントがそれらを**次のガイダンス世代**へと反映します（`taste evolve`）。
世代ごとのスコアボード、系譜、そして新しい世代のスコアが悪化した場合のロールバック
（`taste revert`）付きです。ガイダンスはドメインごとに保持され、保存先は
`$OPENCLIP_HOME` → リポジトリの `toolbox/`（チームのオプトイン）→ `~/.openclip`
（プラグインのデフォルト）の順に解決されます。

## コスト

OpenAI の定価でのおおまかな目安 — 110分のトークをエンドツーエンドで処理（フル STT、
焼き込み字幕付きショート5本、長尺候補2本、サムネイル）した場合、およそ **$1** に収まります：
whisper-1 は音声1分あたり約 $0.006（110分で約 $0.66）、gpt-image-2 は生成サムネイル1枚あたり
約 $0.03〜0.07（フレーム切り出しと `--composite` のサムネイルは無料）、gpt-4o-mini の字幕翻訳は
クリップあたり1セントの何分の1かです。`--mock` の実行はコスト $0 で、再開台帳が完了済みの
STT／レンダリングを二重に課金することは決してありません。

## 要件とステータス

- PATH 上の Python 3.11+、`uv`、そして `ffmpeg`／`ffprobe`
- 実際の実行のための OpenAI API キー（モック実行は外部 API を一切呼び出しません）

OpenClip は初期段階のソフトウェアです。ローカルで利用可能ですが、安定版リリースの前に
API、出力スキーマ、レビューパケットのフォーマットが変更される可能性があります。

## トラブルシューティング

- **`ffmpeg`／`ffprobe: command not found`** — ffmpeg をインストールし、両方のバイナリが
  `PATH` 上にあることを確認してください（`ffmpeg -version` が表示されるはずです）。
  すべてのレンダリング経路がこれらをシェルアウトで呼び出します。
- **`OPENAI_API_KEY` が見つからない** — 実際の実行のために設定してください
  （`export OPENAI_API_KEY=...`）。`--mock` にはキーは不要です：モックモードは
  ネットワーク呼び出しを一切行いません。
- **実際の実行では `OPENAI_BASE_URL` を未設定にする必要があります** — CLI プロキシの
  ベース URL は Whisper と画像呼び出しを壊してしまいます。実際の実行の前に
  未設定にしてください（`unset OPENAI_BASE_URL`）。
- **初回の `--composite` 実行は一時停止します** — rembg の背景除去モデルを一度だけ
  ダウンロードし、その後は完全にオフラインで動作します。（`uv` に含まれる）`uvx` が
  PATH 上にある必要があります。
- **実際の実行は「成功」したのにファイルが見当たらない** — それは出荷されません：
  証拠ゲートは `confirmed` の判定でしか先に進みません。該当する成果物の
  `evidence/*.json` を確認してください。

<details>
<summary><strong>レガシーのワンショットパイプライン（<code>openclip run</code>）</strong> — 元々の固定パイプライン。引き続きサポート</summary>

> **リポジトリのクローン（モード D）専用。** これはエージェントハーネスに先立つ、元々の
> 固定パイプラインです。上記のハーネスが推奨される道筋です。`uv tool install` の後は、
> `uv run` の代わりに `openclip run ...` を直接使ってください。

### クイックスタート

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

### 出力

各実行は `OUT_DIR/{input_basename}/` の下に書き出されます。典型的な出力には
`shorts/*.mp4`、`long/*.mp4`、`edited/edited_original.mp4`、言語ごとの SRT
（`*.en.srt`、`*.ko.srt`、`*.es.srt`、`*.ja.srt`、`*.zh-Hans.srt`）、`*.thumbnail.png`、
`manifest.json`、そして `analysis/`（candidate_selection.json、edl.json、
takes_packed.md、playback_checks/、subagent_packets/）が含まれます。生成された
メディア、ローカルのソース動画、`.env`、仮想環境、キャッシュ、そして `out/` は
git で無視されます。

### 検証

これらのスクリプトはリポジトリツリーに同梱されており、インストールされるパッケージには
含まれません。ハーネスの実行は別の方法で検証されます：`oc verify` ＋ `oc-verifier`
エージェント（`docs/HARNESS.md` を参照）。

```bash
# 既存の実行を検証する
python3 codex/skills/openclip/scripts/verify_run_artifacts.py ./out/example/input_basename

# 並列の再生／デコードゲート
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename --workers 6 --full-decode --write-manifest

# Codex サブエージェントのレビューパケットを再生成する
python3 codex/skills/openclip/scripts/build_subagent_packets.py ./out/example/input_basename
```

### レビューワークフロー

レガシーパイプラインは、`analysis/subagent_packets/` の下に自己完結型の Codex
サブエージェントパケットを作成します。レビューグラフは次のとおりです：
`collect`（エディターが独立したコンテンツの主張を収集する）→ `verify`
（連続性／再生／アーティファクトのゲート）→ `design`（サムネイルの適合性）→
`adversarial`（リテンション批評役）→ `synthesize`（最終ゲートはすべてのレーンに
証拠が揃った後にのみ承認する）。サブエージェントの `PASS` の結果は、証明ではなく
主張として扱われます。ルートスレッドまたはリリースプロセスは、出力を公開する前に、
引用されたパス、マニフェスト、再生の証拠を検証しなければなりません。

</details>

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

OpenClip はローカルのメディアを処理し、`--mock` を使用しない場合、音声、文字起こしテキスト、
字幕テキスト、サムネイルのプロンプト／参照フレーム（ペルソナ写真を含む）を OpenAI に
送信することがあります。処理する権利を持っていない限り、プライベート、規制対象、または
第三者のメディアに対して実際のプロバイダーモードを実行しないでください。ネットワーク
呼び出しを避けなければならないローカルテストには `--mock` を使用してください。

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。
