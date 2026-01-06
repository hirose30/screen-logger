---
name: screen-report
description: Screen Loggerのログ分析と日報生成。専用スクリプトを使用して分析を実行。
invoke_via_agent: true
agent: screen-log-analyzer
---

# Screen Report スキル

Screen Logger が蓄積したログを分析し、作業日報を生成する。

**このスキルは直接実行せず、Task tool で `subagent_type: screen-log-analyzer` を使用すること。**
詳細なレポートフォーマットとルールはエージェント側に定義されている。

## 呼び出し経路

```
ユーザー依頼「日報作成」「スクリーンログ分析」
    ↓
Task tool (subagent_type: screen-log-analyzer)
    ↓
screen-log-analyzer エージェント
    ↓
このスキル（分析スクリプト実行）
    ↓
エージェントの詳細ルールに従ってレポート生成
```

**重要**: 詳細なレポートフォーマットとルールは `agents/screen-log-analyzer.md` に記載。
このスキルは分析スクリプトの実行とJSONデータの取得のみを担当。

## 分析スクリプト

```bash
python3 scripts/analyze_log.py [YYYY-MM-DD]
```

### 引数

- `YYYY-MM-DD`: 分析対象日（省略時は今日）

### 出力（JSON）

| キー | 内容 |
|------|------|
| `basic_stats` | 記録期間、キャプチャ数 |
| `activity_summary` | アクティブ率、総作業時間 |
| `work_sessions` | 作業セッション（時刻、アプリ、content_details） |
| `aggregated_work` | 作業内容ごとの集約（本日の作業サマリー用: total_display, time_summary） |
| `hourly_work_minutes` | 時間帯別作業時間（24時間分、時間またぎを正しく分割） |
| `active_hours_only` | 時間帯ごとのアクティビティ |
| `idle_periods` | 放置期間 |

## 保存先

日報の保存先はエージェント側で指定されます。デフォルトは:
```
reports/YYYY-MM-DD.md
```

## 注意事項

- ログファイルが存在しない場合、スクリプトはエラーJSONを返す
- プライバシー情報（パスワード等）は日報に含めない
