# Screen Logger

[けんすうさんのポスト](https://x.com/kensuu/status/2003012829914501378)に影響を受けて作成しました。

macOSで動作するスクリーンキャプチャ + OCRログ収集ツール。60秒ごとにアクティブウィンドウがあるディスプレイをキャプチャし、Vision FrameworkでOCR処理してJSONL形式で保存します。

## 機能

- アクティブウィンドウのあるディスプレイのみをキャプチャ
- Vision FrameworkによるOCR（日本語・英語対応）
- Electronアプリの実際のアプリ名を取得
- プライバシー保護（除外アプリ・パターン設定）
- ディスプレイスリープ時は自動スキップ
- launchdによる自動実行

## 必要環境

- macOS
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) - Pythonパッケージマネージャー

### uvのインストール

```bash
# Homebrew
brew install uv

# または公式インストーラー
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## セットアップ

### 1. 依存パッケージのインストール

```bash
uv sync
```

### 2. 権限の設定

このツールは以下の権限が必要です。

まず、uvのパスを確認してください（権限設定で使用します）:

```bash
which uv
# 例: /opt/homebrew/bin/uv (Apple Silicon)
#     /usr/local/bin/uv (Intel Mac)
#     ~/.local/bin/uv (公式インストーラー)
```

#### 画面収録（Screen Recording）

スクリーンショットの撮影とOCR処理に必要です。

1. システム設定 > プライバシーとセキュリティ > 画面収録
2. 「+」ボタンをクリック
3. 上記で確認したuvのパスを追加

#### アクセシビリティ（Accessibility）

アクティブウィンドウ情報の取得（AppleScript経由）に必要です。

1. システム設定 > プライバシーとセキュリティ > アクセシビリティ
2. 「+」ボタンをクリック
3. 以下のアプリを追加:
   - 上記で確認したuvのパス
   - 使用するターミナルアプリ（Terminal.app, iTerm, ghostty等）

#### オートメーション（Automation）

Finderを使ってアプリ名を取得するために必要です。初回実行時にダイアログが表示されます。

1. システム設定 > プライバシーとセキュリティ > オートメーション
2. uvまたはターミナルアプリに対して「Finder」と「System Events」を許可

### 3. 動作確認

```bash
uv run capture_screen.py
```

`logs/YYYY-MM-DD.jsonl` にログが出力されれば成功です。

**トラブルシューティング:**

| 症状 | 原因 | 対処 |
|------|------|------|
| OCRテキストが空 | 画面収録権限がない | 画面収録権限を付与 |
| ウィンドウ名が取得できない | アクセシビリティ権限がない | アクセシビリティ権限を付与 |
| アプリ名が「Electron」のまま | オートメーション権限がない | Finder/System Eventsの許可 |

### 4. plistのパス設定

テンプレートファイルをコピーして、パスを自分の環境に合わせて編集してください。

```bash
# テンプレートをコピー
cp com.user.screenlogger.plist.example com.user.screenlogger.plist

# パスを編集（プレースホルダーを実際のパスに置換）
sed -i '' "s|{{PROJECT_PATH}}|$(pwd)|g" com.user.screenlogger.plist
sed -i '' "s|{{UV_PATH}}|$(which uv)|g" com.user.screenlogger.plist
```

### 5. launchdの設定（自動実行）

```bash
# plistをLaunchAgentsにコピー
cp com.user.screenlogger.plist ~/Library/LaunchAgents/

# launchdに登録
launchctl load ~/Library/LaunchAgents/com.user.screenlogger.plist

# 状態確認（PIDが表示されれば成功）
launchctl list | grep screenlogger
```

## 設定

### config.yaml

除外するアプリやウィンドウパターンを設定できます。

```yaml
exclude:
  apps:
    - "1Password"
    - "Keychain Access"
    - "System Preferences"
    - "System Settings"
  window_patterns:
    - "password"
    - "secret"
    - "credential"
```

## ログ形式

`logs/YYYY-MM-DD.jsonl` にJSONL形式で保存されます。

```json
{"timestamp": "2025-01-01T12:00:00.123456", "window": "Antigravity | project-name", "ocr_text": "..."}
```

## launchd操作

```bash
# 停止
launchctl unload ~/Library/LaunchAgents/com.user.screenlogger.plist

# 開始
launchctl load ~/Library/LaunchAgents/com.user.screenlogger.plist

# 設定変更後の再読み込み
launchctl unload ~/Library/LaunchAgents/com.user.screenlogger.plist
cp com.user.screenlogger.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.screenlogger.plist
```

## 日報生成（Claude Code連携）

蓄積されたログをClaude Codeで分析し、作業日報を生成できます。

### 構成

```
.claude/
├── agents/
│   └── screen-log-analyzer.md   # 日報生成エージェント
└── skills/
    └── screen-report/
        └── SKILL.md             # スキル定義
scripts/
└── analyze_log.py               # ログ分析スクリプト
```

### 使用方法

Claude Code上で日報作成を依頼すると、`screen-log-analyzer`エージェントが起動します。

```
# Claude Codeで実行
「今日の日報を作成して」
「12月31日のスクリーンログを分析して」
```

### 分析スクリプト（手動実行）

```bash
# 今日のログを分析（JSON形式）
python3 scripts/analyze_log.py

# 特定日を分析
python3 scripts/analyze_log.py 2025-12-31

# 出力形式を指定
python3 scripts/analyze_log.py 2025-12-31 --format summary   # LLM用コンパクト版
python3 scripts/analyze_log.py 2025-12-31 --format markdown  # 定量レポート
python3 scripts/analyze_log.py 2025-12-31 --format json      # 完全版（デフォルト）
```

### 分析内容

| 項目 | 説明 |
|------|------|
| 作業セッション | アプリ・コンテキストごとの作業時間 |
| 時間帯別作業時間 | 24時間分の作業分布 |
| アプリ使用状況 | アプリ別の使用時間・割合 |
| 放置期間 | 5分以上のアイドル時間 |
| プロジェクト検出 | OCRから推定されたプロジェクト名 |

### 日報出力先

```
reports/YYYY-MM-DD.md
```

## 注意事項

- `ProcessType: Background` により、スリープを妨げません
- Parsec等のリモートデスクトップソフトはディスプレイスリープを妨げる場合があります
- ログファイルは自動削除されないため、定期的な整理が必要です
