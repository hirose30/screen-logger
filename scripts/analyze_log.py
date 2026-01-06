#!/usr/bin/env python3
"""
Screen Logger ログ分析スクリプト

Usage:
    python3 analyze_log.py [YYYY-MM-DD] [--format json|markdown]

Arguments:
    YYYY-MM-DD: 分析対象日（省略時は今日）
    --format:   出力形式（json または markdown、省略時はjson）

Output:
    JSON形式またはMarkdown形式で分析結果を標準出力
"""

import argparse
import json
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, Counter
from difflib import SequenceMatcher

# ログファイルのディレクトリ（スクリプトの親ディレクトリのlogs/）
LOG_DIR = Path(__file__).parent.parent / "logs"

# idle判定の閾値
SIMILARITY_THRESHOLD = 0.95  # OCRテキストの類似度がこれ以上ならidle（ほぼ同一画面）
IDLE_DURATION_THRESHOLD = 300  # 5分以上のidle期間を「放置」と判定（秒）
MAX_SESSION_MINUTES = 30  # セッションの最大長（これを超えたら分割）

# OCRテキストから除去するノイズパターン
MENU_NOISE_PATTERNS = [
    # macOS メニューバー（各アプリ共通）
    r'^(Ghostty|Chrome|Obsidian|Slack|Finder|Safari|Arc|Electron|Code|Cursor)\s*$',
    r'ファイル\s+編集',
    r'File\s+Edit',
    r'履歴\s+ブックマーク',
    r'プロファイル\s+タブ',
    r'ウィンドウ\s+ヘルプ',
    r'Window\s+Help',
    r'Insert\s+Format',

    # サイドバーUI要素
    r'エクスプローラー',
    r'ソース管理',
    r'アウトライン',
    r'タイムライン',
    r'フォルダー',
    r'[<＜]\s*グラフ',
    r'[<＜]\s*変更',
    r'Generate fa',

    # カレンダーウィジェット
    r'W\d{1,2}\s+W\d{1,2}',  # W49 W50 W51 W52
    r'Q[1-4]\s+\d{4}',  # Q4 2025
    r'Today\s*>>',

    # X/Twitter UI（行全体マッチ）
    r'^ホーム\s*$',
    r'^話題を検索\s*$',
    r'^通知\s*$',
    r'^チャット\s*$',
    r'^Grok\s*$',
    r'^リスト\s*$',
    r'^ブックマーク\s*$',
    r'^コミュニティ\s*$',
    r'^X\s+プレミアム',
    r'^プロフィール\s*$',
    r'^もっと見る\s*$',
    r'^ポストする\s*$',
    r'^トレンド\s*$',
    r'^本日のニュース',
    r'プレミアムにサブスクライブ',
    r'サブスクライブして新機能',
    r'^購入する\s*$',
    r'「いま」を見つけよう',
    r'件のポスト\s*$',
    r'^おすすめ\s*$',
    r'^フォロー中\s*$',
    r'^保存済み\s*$',
    r'^日本のトレンド',

    # Git履歴・コミットログ
    r'^[●•]\s*(docs|feat|fix|chore|refactor|test|style|perf|ci|build|revert):',
    r'^→?origin/',
    r'^[）\)]\s*feature/',

    # VS Code/Cursor UI
    r'accept edits',
    r'shift\+tab to cycle',
    r'\d+,\d+\s*ワード',
    r'\d+\s*文字',
    r'\d+\s*バックリンク',
    r'^on\s*$',

    # 日付・時刻表示（UI要素）
    r'\d{1,2}月\d{1,2}日（[月火水木金土日]）\s*\d{1,2}:\d{2}',

    # その他UI
    r'^80\s*$',
    r'^あ\s*$',
    r'^¢\s*$',
    r'^田\s*$',
    r'^8自動\s*$',
    r'^と\s*$',
]

# 行単位で除去するパターン（短すぎる行、記号のみなど）
LINE_NOISE_PATTERNS = [
    r'^[<>｜|＞＜くＡ]+\s*$',  # 矢印・記号のみ
    r'^[A-Za-z]\s*$',  # アルファベット1文字のみ
    r'^[ァ-ヶー]+$',  # カタカナのみ（短い場合）
    r'^\d{1,2}\s*$',  # 数字1-2桁のみ（カレンダーの日付）
    r'^[★☆♥❤︎●○◆◇■□▶▷◎⑦目口]+\s*$',  # 記号・アイコンのみ
    r'^[\s\-_=+*#♥]+$',  # 空白・記号のみ
    r'^[）\)]\s*\.\.\.\s*$',  # ") ..." のようなパターン
    r'^=\s*[a-z]+\s*$',  # "= tkz" のようなパターン
    r'^8%\s*',  # 8% で始まる
    r'^Q\s*$',
    r'^く変更\s*$',  # 部分的にマッチしたメニュー
    r'^[♥●•]\s*コミット',  # コミットUI
    r'^口\s+ブックマーク',  # Xのブックマークアイコン
    r'^\d+\s+プロフィール',  # 数字+プロフィール
    r'^表示\s*$',  # メニュー項目
    r'^履歴\s*$',  # メニュー項目
    r'^編集\s*$',  # メニュー項目
    r'^ファイル\s*$',  # メニュー項目
    r'^main\s*$',  # gitブランチ名単体
    r'^feature-.*$',  # feature branch partial
]


def clean_ocr_text(ocr_text: str) -> str:
    """OCRテキストからメニュー等のノイズを除去"""
    if not ocr_text:
        return ""

    cleaned = ocr_text

    # パターンベースの除去
    for pattern in MENU_NOISE_PATTERNS:
        cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE | re.IGNORECASE)

    # 行単位のフィルタリング
    lines = cleaned.split('\n')
    filtered_lines = []
    for line in lines:
        line = line.strip()
        # 空行スキップ
        if not line:
            continue
        # 短すぎる行スキップ（3文字未満）
        if len(line) < 3:
            continue
        # ノイズパターンに該当する行スキップ
        is_noise = False
        for pattern in LINE_NOISE_PATTERNS:
            if re.match(pattern, line):
                is_noise = True
                break
        if not is_noise:
            filtered_lines.append(line)

    return '\n'.join(filtered_lines)


def load_log(date_str: str) -> list[dict]:
    """指定日のログを読み込む"""
    log_file = LOG_DIR / f"{date_str}.jsonl"
    if not log_file.exists():
        return []

    entries = []
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def parse_timestamp(ts_str: str) -> datetime:
    """タイムスタンプをパース"""
    # ISO8601形式に対応
    ts_str = ts_str.replace("Z", "+00:00")
    if "+" in ts_str or ts_str.endswith("Z"):
        dt = datetime.fromisoformat(ts_str)
        return dt.replace(tzinfo=None)
    return datetime.fromisoformat(ts_str)


def extract_app_name(window: str) -> str:
    """ウィンドウ文字列からアプリ名を抽出"""
    if " | " in window:
        return window.split(" | ")[0].strip().rstrip(" |")
    return window.strip().rstrip(" |")


def text_similarity(text1: str, text2: str) -> float:
    """2つのテキストの類似度を計算（0.0〜1.0）"""
    if not text1 or not text2:
        return 0.0
    # 長すぎるテキストは先頭部分で比較（パフォーマンス対策）
    max_len = 2000
    t1 = text1[:max_len]
    t2 = text2[:max_len]
    return SequenceMatcher(None, t1, t2).ratio()


def detect_activity_status(entries: list[dict]) -> list[dict]:
    """各エントリのアクティビティ状態を判定

    OCRが空/短い場合は、スクリーンセーバー起動中など非アクティブ状態とみなす

    Returns:
        各エントリに is_active, is_idle フラグを追加したリスト
    """
    if not entries:
        return []

    # OCR空判定の閾値（これ以下の文字数は「空」とみなす）
    MIN_OCR_LENGTH = 20

    results = []
    prev_window = ""
    prev_text = ""
    prev_ts = None

    for entry in entries:
        ts = parse_timestamp(entry["timestamp"])
        window = entry.get("window", "")
        ocr_text = entry.get("ocr_text", "")

        # OCRが空/短い場合は非アクティブ（スクリーンセーバー等）
        ocr_empty = not ocr_text or len(ocr_text.strip()) < MIN_OCR_LENGTH

        # 初回
        if prev_ts is None:
            is_active = not ocr_empty
            is_idle = ocr_empty
        else:
            if ocr_empty:
                # OCR空 = 非アクティブ（スクリーンセーバー、ロック画面等）
                is_active = False
                is_idle = True
            else:
                # ウィンドウが変わった = アクティブ
                window_changed = (window != prev_window)

                # OCRテキストの類似度
                similarity = text_similarity(ocr_text, prev_text)
                text_similar = (similarity >= SIMILARITY_THRESHOLD)

                # アクティブ判定: ウィンドウが変わった OR テキストが大きく変わった
                is_active = window_changed or not text_similar
                is_idle = not is_active

        results.append({
            **entry,
            "parsed_ts": ts,
            "is_active": is_active,
            "is_idle": is_idle,
            "ocr_empty": ocr_empty,
            "app_name": extract_app_name(window)
        })

        prev_window = window
        prev_text = ocr_text
        prev_ts = ts

    return results


def detect_idle_periods(entries_with_status: list[dict]) -> list[dict]:
    """連続するidle期間を検出

    Returns:
        idle期間のリスト [{start, end, duration_seconds, app}]
    """
    idle_periods = []
    current_idle_start = None
    current_idle_app = None

    for i, entry in enumerate(entries_with_status):
        if entry["is_idle"]:
            if current_idle_start is None:
                current_idle_start = entry["parsed_ts"]
                current_idle_app = entry["app_name"]
        else:
            if current_idle_start is not None:
                # idle期間終了
                idle_end = entry["parsed_ts"]
                duration = (idle_end - current_idle_start).total_seconds()

                # 閾値以上のidle期間のみ記録
                if duration >= IDLE_DURATION_THRESHOLD:
                    idle_periods.append({
                        "start": current_idle_start.isoformat(),
                        "end": idle_end.isoformat(),
                        "duration_seconds": int(duration),
                        "duration_minutes": round(duration / 60, 1),
                        "app": current_idle_app
                    })

                current_idle_start = None
                current_idle_app = None

    # 最後のidle期間が続いている場合
    if current_idle_start is not None and entries_with_status:
        last_entry = entries_with_status[-1]
        idle_end = last_entry["parsed_ts"]
        duration = (idle_end - current_idle_start).total_seconds()

        if duration >= IDLE_DURATION_THRESHOLD:
            idle_periods.append({
                "start": current_idle_start.isoformat(),
                "end": idle_end.isoformat(),
                "duration_seconds": int(duration),
                "duration_minutes": round(duration / 60, 1),
                "app": current_idle_app
            })

    return idle_periods


def calculate_basic_stats(entries: list[dict]) -> dict:
    """基本統計を計算"""
    if not entries:
        return {"error": "No entries"}

    timestamps = [parse_timestamp(e["timestamp"]) for e in entries]
    first_ts = min(timestamps)
    last_ts = max(timestamps)
    duration = last_ts - first_ts

    return {
        "first_timestamp": first_ts.isoformat(),
        "last_timestamp": last_ts.isoformat(),
        "duration_minutes": int(duration.total_seconds() / 60),
        "capture_count": len(entries)
    }


def analyze_app_usage(entries_with_status: list[dict]) -> list[dict]:
    """アプリ使用状況を分析（アクティブ時間のみ）"""
    app_total = Counter()
    app_active = Counter()

    for entry in entries_with_status:
        app_name = entry.get("app_name", "")
        app_total[app_name] += 1
        if entry.get("is_active", False):
            app_active[app_name] += 1

    total_all = sum(app_total.values())
    total_active = sum(app_active.values())

    results = []
    for app, count in app_total.most_common():
        percentage = (count / total_all) * 100 if total_all > 0 else 0
        active_count = app_active.get(app, 0)
        active_percentage = (active_count / total_active) * 100 if total_active > 0 else 0

        if active_percentage >= 30:
            frequency = "最多"
        elif active_percentage >= 15:
            frequency = "多"
        elif active_percentage >= 5:
            frequency = "中"
        else:
            frequency = "少"

        results.append({
            "app": app,
            "total_count": count,
            "active_count": active_count,
            "total_percentage": round(percentage, 1),
            "active_percentage": round(active_percentage, 1),
            "frequency": frequency
        })

    # アクティブ率でソート
    results.sort(key=lambda x: x["active_count"], reverse=True)
    return results


def analyze_activity_by_hour(entries_with_status: list[dict]) -> list[dict]:
    """時間帯別アクティビティを分析"""
    hourly_data = defaultdict(lambda: {
        "total": 0,
        "active": 0,
        "idle": 0,
        "apps": Counter(),
        "active_apps": Counter()
    })

    for entry in entries_with_status:
        ts = entry["parsed_ts"]
        hour = ts.hour
        app_name = entry["app_name"]

        hourly_data[hour]["total"] += 1
        hourly_data[hour]["apps"][app_name] += 1

        if entry["is_active"]:
            hourly_data[hour]["active"] += 1
            hourly_data[hour]["active_apps"][app_name] += 1
        else:
            hourly_data[hour]["idle"] += 1

    results = []
    for hour in sorted(hourly_data.keys()):
        data = hourly_data[hour]
        active_rate = (data["active"] / data["total"]) * 100 if data["total"] > 0 else 0

        # アクティブ時の主要アプリ
        top_active_app = ""
        if data["active_apps"]:
            top_active_app = data["active_apps"].most_common(1)[0][0]
        elif data["apps"]:
            top_active_app = data["apps"].most_common(1)[0][0]

        # idle率が高い（90%以上）場合は「放置」と表示
        status = "active" if active_rate >= 10 else "idle"

        results.append({
            "hour": f"{hour:02d}-{(hour+1)%24:02d}",
            "total_captures": data["total"],
            "active_captures": data["active"],
            "idle_captures": data["idle"],
            "active_rate": round(active_rate, 1),
            "main_app": top_active_app,
            "status": status
        })

    return results


def _merge_content_details(target: dict, source: dict) -> None:
    """コンテンツ詳細を集約用dictにマージ"""
    for key in ["keywords", "repos", "documents", "search_queries", "topics"]:
        if source.get(key):
            target[key].update(source[key])

    # raw_snippetsはリストなので別処理
    if source.get("raw_snippets"):
        for snippet in source["raw_snippets"]:
            if snippet not in target["raw_snippets"]:
                target["raw_snippets"].append(snippet)
        target["raw_snippets"] = target["raw_snippets"][:10]  # 最大10件

    # emailsはdict
    if source.get("emails"):
        if source["emails"].get("labels"):
            if "labels" not in target["emails"]:
                target["emails"]["labels"] = set()
            target["emails"]["labels"].update(source["emails"]["labels"])
        if source["emails"].get("contacts"):
            if "contacts" not in target["emails"]:
                target["emails"]["contacts"] = set()
            target["emails"]["contacts"].update(source["emails"]["contacts"])


def _extract_content_details(raw_ocr_text: str) -> dict:
    """OCRテキストから具体的なコンテンツ詳細を抽出

    Returns:
        {
            "keywords": [...],      # 抽出されたキーワード
            "repos": [...],         # GitHubリポジトリ
            "documents": [...],     # ドキュメント名
            "emails": {...},        # メール関連情報
            "search_queries": [...], # 検索クエリ
            "topics": [...],        # トピック/記事タイトル
            "raw_snippets": [...]   # 重要そうなテキスト断片
        }
    """
    details = {
        "keywords": [],
        "repos": [],
        "documents": [],
        "emails": {},
        "search_queries": [],
        "topics": [],
        "raw_snippets": []
    }

    if not raw_ocr_text or len(raw_ocr_text) < 50:
        return details

    ocr_lower = raw_ocr_text.lower()

    # === GitHub リポジトリ ===
    repo_patterns = [
        r'github\.com/([a-zA-Z0-9\-_]+/[a-zA-Z0-9\-_]+)',
        r'([a-zA-Z0-9\-_]+/[a-zA-Z0-9\-_]+)\s*[-–]\s*GitHub',
    ]
    for pattern in repo_patterns:
        matches = re.findall(pattern, raw_ocr_text)
        for match in matches:
            if match not in details["repos"] and '/' in match:
                details["repos"].append(match)

    # GitHub Issue/PR番号
    issue_pr = re.findall(r'(?:Issue|PR|#)[\s#]*(\d{1,5})', raw_ocr_text)
    if issue_pr:
        details["keywords"].extend([f"#{num}" for num in issue_pr[:3]])

    # === ドキュメント名 ===
    doc_patterns = [
        r'([^\s/\\]+\.(?:pdf|docx?|xlsx?|pptx?|md|txt))',
        r'([^\s/\\]+\.(?:py|js|ts|tsx|jsx|go|rs|java|rb|php))',
    ]
    for pattern in doc_patterns:
        matches = re.findall(pattern, raw_ocr_text, re.IGNORECASE)
        for match in matches:
            if len(match) > 3 and match not in details["documents"]:
                details["documents"].append(match)

    # === 検索クエリ ===
    search_patterns = [
        r'google\.com/search\?q=([^&\s]+)',
        r'search\?q=([^&\s]+)',
        r'検索[:：]\s*([^\n]+)',
    ]
    for pattern in search_patterns:
        matches = re.findall(pattern, raw_ocr_text)
        for match in matches:
            query = match.replace('+', ' ').replace('%20', ' ')[:50]
            if query and query not in details["search_queries"]:
                details["search_queries"].append(query)

    # === Gmail情報 ===
    if 'mail.google' in ocr_lower or '受信トレイ' in raw_ocr_text:
        # ラベルを検出
        labels = re.findall(r'(?:^|\s)(Amazon|GitHub|Qiita|Newsletter|Updates|Notifications)(?:\s|$)', raw_ocr_text, re.IGNORECASE)
        if labels:
            details["emails"]["labels"] = list(set(labels))

        # 送信者/件名のパターン（プライバシー配慮）
        sender_patterns = re.findall(r'([A-Za-z]+(?:\s[A-Za-z]+)?)\s*<', raw_ocr_text)
        if sender_patterns:
            details["emails"]["contacts"] = list(set(sender_patterns[:3]))

    # === 技術記事/トピック ===
    # Qiita記事タイトル
    if 'qiita.com' in ocr_lower:
        lines = raw_ocr_text.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) >= 15 and re.search(r'[ぁ-んァ-ヶ一-龥]', line):
                if not re.search(r'(https?://|\.com|^[<>＜＞]|ファイル|編集|表示)', line):
                    details["topics"].append(line[:60])
                    break

    # === X/Twitter トピック ===
    if 'x.com' in ocr_lower or 'twitter' in ocr_lower:
        # ハッシュタグ
        hashtags = re.findall(r'#([a-zA-Z0-9\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]+)', raw_ocr_text)
        if hashtags:
            details["keywords"].extend([f"#{tag}" for tag in hashtags[:5]])

        # 投稿の一部を抽出（日本語含む行）
        lines = raw_ocr_text.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) >= 20 and re.search(r'[ぁ-んァ-ヶ一-龥]', line):
                # UIテキストを除外
                if not re.search(r'(ホーム|話題を検索|通知|チャット|もっと見る|プロフィール|ポストする|フォロー|リスト)', line):
                    details["raw_snippets"].append(line[:80])
                    if len(details["raw_snippets"]) >= 2:
                        break

    # === NotebookLM ===
    if 'notebooklm' in ocr_lower:
        # ソースドキュメント名
        doc_match = re.search(r'([^\n]+\.(?:pdf|md|docx?))', raw_ocr_text, re.IGNORECASE)
        if doc_match:
            details["documents"].append(doc_match.group(1)[:50])

        # Deep Researchトピック
        if 'deep research' in ocr_lower:
            details["keywords"].append("Deep Research")

    # === 一般的な重要キーワード ===
    # プロジェクト名（ユーザーがカスタマイズ可能）
    project_keywords = [
        'screen-logger', 'my-project', 'web-app', 'api-server', 'frontend'
    ]
    for kw in project_keywords:
        if kw in ocr_lower and kw not in [k.lower() for k in details["keywords"]]:
            details["keywords"].append(kw)

    # 技術キーワード
    tech_keywords = [
        'BigQuery', 'Cloud Run', 'Firebase', 'OAuth', 'API',
        'Python', 'TypeScript', 'React', 'Next.js', 'Claude', 'GPT'
    ]
    for kw in tech_keywords:
        if kw.lower() in ocr_lower and kw not in details["keywords"]:
            details["keywords"].append(kw)

    # 重複除去と制限
    details["keywords"] = list(dict.fromkeys(details["keywords"]))[:10]
    details["repos"] = list(dict.fromkeys(details["repos"]))[:5]
    details["documents"] = list(dict.fromkeys(details["documents"]))[:5]
    details["topics"] = list(dict.fromkeys(details["topics"]))[:3]
    details["raw_snippets"] = list(dict.fromkeys(details["raw_snippets"]))[:3]

    return details


def _detect_browser_context(raw_ocr_text: str) -> dict | None:
    """OCRテキストからブラウザの作業コンテキストを検出

    Note: URL検出のため、ノイズ除去前のテキストも一部使用
    複数タブが開いている場合、すべてのサービスを検出してリストで返す
    """
    result = {}
    detected_services = []

    # 生テキストを小文字化（検索用）
    raw_lower = raw_ocr_text.lower()

    # ノイズ除去済みテキストを使用
    ocr_text = clean_ocr_text(raw_ocr_text)

    # === 業務系サイト（ユーザーがカスタマイズ可能） ===
    # 以下は例です。自分の業務で使用するサービスに置き換えてください。
    # if "your-service.com" in raw_lower:
    #     detected_services.append("Your Service")

    # === AI/ドキュメント系 ===

    # NotebookLM
    if "notebooklm" in raw_lower:
        service_name = "NotebookLM"
        # ドキュメント名を抽出
        doc_patterns = [
            r'([^\n]+\.md)',  # .mdファイル
            r'([^\n]+\.pdf)',  # .pdfファイル
        ]
        for pattern in doc_patterns:
            match = re.search(pattern, ocr_text)
            if match:
                doc_name = match.group(1).strip()[:40]
                if doc_name and len(doc_name) > 3:
                    result["document"] = doc_name
                    service_name = f"NotebookLM: {doc_name[:30]}"
                    break
        if "Deep Research" in ocr_text:
            service_name = "NotebookLM Deep Research"
        detected_services.append(service_name)

    # === 一般的なサービス ===

    # Gmail
    if "mail.google" in raw_lower or "受信トレイ" in ocr_text:
        service_name = "Gmail"
        if "受信トレイ" in ocr_text:
            service_name = "Gmail: 受信トレイ"
        elif "下書き" in ocr_text:
            service_name = "Gmail: メール作成"
        detected_services.append(service_name)

    # Google Calendar
    if "calendar.google" in raw_lower or "Googleカレンダー" in ocr_text:
        detected_services.append("Googleカレンダー")

    # Google Drive
    if "drive.google" in raw_lower or "マイドライブ" in ocr_text:
        detected_services.append("Google Drive")

    # Google Docs
    if "docs.google" in raw_lower:
        detected_services.append("Google Docs")

    # Google Sheets
    if "sheets.google" in raw_lower or "スプレッドシート" in ocr_text:
        detected_services.append("Google Sheets")

    # GitHub
    if "github.com" in raw_lower:
        service_name = "GitHub"
        repo_match = re.search(r'github\.com/([a-zA-Z0-9\-_]+/[a-zA-Z0-9\-_]+)', raw_ocr_text)
        if repo_match:
            result["project"] = repo_match.group(1)
            service_name = f"GitHub: {repo_match.group(1)}"
        if "Pull Request" in ocr_text or "pull/" in raw_lower:
            service_name = f"GitHub PR: {result.get('project', '')}"
        elif "Issue" in ocr_text or "issues/" in raw_lower:
            service_name = f"GitHub Issue: {result.get('project', '')}"
        detected_services.append(service_name)

    # Slack
    if "slack.com" in raw_lower or "app.slack" in raw_lower:
        service_name = "Slack (Web)"
        channel_match = re.search(r'#([a-zA-Z0-9\-_]+)', ocr_text)
        if channel_match:
            service_name = f"Slack: #{channel_match.group(1)}"
        detected_services.append(service_name)

    # Claude
    if "claude.ai" in raw_lower:
        detected_services.append("Claude")

    # X/Twitter
    if "x.com" in raw_lower or "twitter.com" in raw_lower:
        detected_services.append("X (Twitter)")

    # YouTube
    if "youtube.com" in raw_lower or "youtu.be" in raw_lower:
        detected_services.append("YouTube")

    # Notion
    if "notion.so" in raw_lower:
        detected_services.append("Notion")

    # Qiita
    if "qiita.com" in raw_lower:
        service_name = "Qiita"
        lines = ocr_text.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) >= 10 and re.search(r'[ぁ-んァ-ヶ一-龥]', line):
                if not re.search(r'(https?://|\.com|^[<>])', line):
                    service_name = f"Qiita: {line[:35]}"
                    break
        detected_services.append(service_name)

    # Confluence
    if "confluence" in raw_lower or "atlassian.net" in raw_lower:
        detected_services.append("Confluence")

    # JIRA
    if "jira" in raw_lower:
        detected_services.append("JIRA")

    # AWS Console
    if "aws.amazon.com" in raw_lower or "console.aws" in raw_lower:
        detected_services.append("AWS Console")

    # GCP Console
    if "console.cloud.google" in raw_lower:
        detected_services.append("GCP Console")

    # Anthropic Console
    if "console.anthropic" in raw_lower:
        detected_services.append("Anthropic Console")

    # OpenAI
    if "platform.openai" in raw_lower or "openai.com" in raw_lower:
        detected_services.append("OpenAI")

    # Figma
    if "figma.com" in raw_lower:
        detected_services.append("Figma")

    # Vercel
    if "vercel.com" in raw_lower:
        detected_services.append("Vercel")

    # === 結果をまとめる ===
    if detected_services:
        # 重複除去して、最大3つまで表示
        unique_services = list(dict.fromkeys(detected_services))[:3]
        result["description"] = ", ".join(unique_services)
        result["all_services"] = unique_services
        return result

    # === フォールバック: ドメインから推定 ===
    domain_match = re.search(r'(?:https?://)?([a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)+)', raw_ocr_text)
    if domain_match:
        domain = domain_match.group(1)
        if any(tld in domain for tld in ['.com', '.co.jp', '.io', '.org', '.dev', '.ai', '.app', '.net', '.jp']):
            noise_domains = ['google.com', 'gstatic.com', 'googleapis.com', 'cloudflare.com']
            if not any(noise in domain for noise in noise_domains):
                result["url_domain"] = domain
                result["description"] = f"Web: {domain}"
                return result

    # === フォールバック: コンテンツから推定 ===
    content_lines = [line for line in ocr_text.split('\n') if len(line) > 30]
    if content_lines:
        main_content = max(content_lines, key=len)[:60]
        result["description"] = f"閲覧: {main_content}"
        return result

    return None


def extract_work_context(raw_ocr_text: str, window: str, app_name: str) -> dict:
    """OCRテキストとウィンドウ情報から作業コンテキストを抽出"""
    context = {
        "project": None,
        "document": None,
        "url_domain": None,
        "page_title": None,
        "description": None
    }

    # OCRテキストのノイズ除去（一般的な処理用）
    ocr_text = clean_ocr_text(raw_ocr_text)

    app_lower = app_name.lower()

    # ブラウザの場合
    if any(browser in app_lower for browser in ["chrome", "arc", "safari", "firefox"]):
        # URLを抽出（生テキストから - ノイズ除去でURLが消える可能性があるため）
        full_url_pattern = r'(https?://[a-zA-Z0-9\-\.]+[^\s\n]*)'
        full_urls = re.findall(full_url_pattern, raw_ocr_text)
        if full_urls:
            context["url_domain"] = full_urls[0][:100]

        # ドメインのみも抽出（生テキストから）
        domain_pattern = r'([a-zA-Z0-9\-]+\.(com|co\.jp|io|org|dev|ai|app|net))'
        domains = re.findall(domain_pattern, raw_ocr_text)
        detected_domain = domains[0][0] if domains else None

        # ページタイトルをウィンドウから抽出
        if " | " in window:
            parts = window.split(" | ")
            if len(parts) >= 2:
                title = parts[1].strip()[:50]
                if title and title not in ["Google Chrome", "Arc", "Safari", "Firefox"]:
                    context["page_title"] = title

        # OCRテキストからサービス・コンテンツを検出（生テキストを渡す）
        browser_context = _detect_browser_context(raw_ocr_text)
        if browser_context:
            context["description"] = browser_context["description"]
            if browser_context.get("document"):
                context["document"] = browser_context["document"]
            if browser_context.get("project"):
                context["project"] = browser_context["project"]

        # OCRが空/短い場合、ウィンドウタイトルからフォールバック
        if not context.get("description") and not raw_ocr_text.strip():
            if context.get("page_title"):
                context["description"] = f"閲覧: {context['page_title']}"
            # 直前のセッションからコンテキストを推定（OCR失敗時）
            context["ocr_failed"] = True

        # サービス検出がなかった場合、ドメインベースで判定
        if not context.get("description") and detected_domain:
            domain = detected_domain
            if "github.com" in domain:
                context["description"] = "GitHub"
                repo_match = re.search(r'github\.com/([^/]+/[^/\s]+)', ocr_text)
                if repo_match:
                    context["project"] = repo_match.group(1)
                    context["description"] = f"GitHub: {repo_match.group(1)}"
            elif "stackoverflow.com" in domain:
                context["description"] = "Stack Overflow 調査"
            elif "google.com" in domain or "google.co.jp" in domain:
                if context["page_title"]:
                    context["description"] = f"Google検索: {context['page_title'][:30]}"
                else:
                    context["description"] = "Google検索"
            elif "notion.so" in domain:
                context["description"] = "Notion"
            elif "slack.com" in domain:
                context["description"] = "Slack (Web)"
            elif "claude.ai" in domain:
                context["description"] = "Claude との対話"
            elif "docs.google.com" in domain:
                if context["page_title"]:
                    context["description"] = f"Google Docs: {context['page_title'][:25]}"
                else:
                    context["description"] = "Google Docs"
            elif "calendar.google.com" in domain:
                context["description"] = "Googleカレンダー"
            elif "anthropic.com" in domain:
                context["description"] = "Anthropic ドキュメント"
            elif "openai.com" in domain:
                context["description"] = "OpenAI ドキュメント"
            else:
                if context["page_title"]:
                    context["description"] = context["page_title"][:40]
                else:
                    context["description"] = domain

    # Obsidianの場合
    if "obsidian" in app_lower:
        # ウィンドウタイトルからファイル名を抽出
        if " | " in window:
            parts = window.split(" | ")
            if len(parts) >= 2:
                doc_name = parts[1].strip()
                if doc_name:
                    context["document"] = doc_name[:60]
                    context["description"] = f"ノート: {doc_name[:40]}"

    # ターミナル/エディタの場合
    if any(term in app_lower for term in ["ghostty", "terminal", "iterm"]):
        # プロジェクトディレクトリを抽出
        dir_patterns = [
            r'\[.+@.+\s+([^\]\s]+)\]',  # [user@host dir]
            r'cd\s+[~/]?([^\s\n]+)',
        ]
        for pattern in dir_patterns:
            match = re.search(pattern, ocr_text)
            if match:
                proj = match.group(1)[:30]
                # 意味のないディレクトリ名を除外
                if proj not in ["~", ".", "..", "Dropbox", "Documents", "dev", "private"]:
                    context["project"] = proj
                    context["description"] = f"ターミナル: {proj}"
                break

        # コマンドの検出
        cmd_patterns = [
            (r'\bgit\s+(push|pull|commit|checkout|branch)', "Git操作"),
            (r'\bnpm\s+(run|install|test)', "npm操作"),
            (r'\bpython3?\s+', "Python実行"),
            (r'\bclaude\s+', "Claude Code"),
        ]
        for pattern, desc in cmd_patterns:
            if re.search(pattern, ocr_text):
                if context.get("project"):
                    context["description"] = f"{desc}: {context['project']}"
                else:
                    context["description"] = desc
                break

    # VS Code / Cursor の場合
    if any(editor in app_lower for editor in ["code", "cursor", "electron"]):
        # ファイル名を抽出
        if " | " in window:
            parts = window.split(" | ")
            if len(parts) >= 2:
                file_part = parts[1].strip()
                if file_part and file_part not in ["Electron"]:
                    context["document"] = file_part[:50]
                    context["description"] = f"編集: {file_part[:35]}"

        # プロジェクト名を抽出（ユーザーがカスタマイズ可能）
        known_projects = [
            "screen-logger", "my-project", "web-app", "api-server"
        ]
        for proj in known_projects:
            if proj.lower() in ocr_text.lower():
                context["project"] = proj
                if not context["description"]:
                    context["description"] = f"開発: {proj}"
                break

    # 汎用的なプロジェクト名検出
    if not context["project"]:
        known_projects = [
            "screen-logger", "my-project", "web-app", "api-server"
        ]
        for proj in known_projects:
            if proj.lower() in ocr_text.lower():
                context["project"] = proj
                break

    return context


def detect_work_sessions(entries_with_status: list[dict]) -> list[dict]:
    """作業セッションを検出（連続した同じアプリ+コンテキストのブロック）

    改善点:
    - 最大セッション長(MAX_SESSION_MINUTES)を超えたら自動分割
    - セッション内のサブ活動（コンテキスト変化）を追跡

    Returns:
        作業セッションのリスト
    """
    if not entries_with_status:
        return []

    sessions = []
    current_session = None

    for entry in entries_with_status:
        # アクティブなエントリのみ処理
        if not entry.get("is_active", False):
            continue

        app_name = entry["app_name"]
        context = extract_work_context(
            entry.get("ocr_text", ""),
            entry.get("window", ""),
            app_name
        )

        # セッションキー（アプリ + 主要コンテキスト）
        session_key = (
            app_name,
            context.get("project"),
            context.get("document"),
            context.get("url_domain")
        )

        # セッション継続判定
        should_start_new = False
        if current_session is None:
            should_start_new = True
        elif session_key != current_session["session_key"]:
            should_start_new = True
        else:
            # 同じsession_keyでも、最大セッション長を超えたら分割
            session_duration = (entry["parsed_ts"] - current_session["start_ts"]).total_seconds() / 60
            if session_duration >= MAX_SESSION_MINUTES:
                should_start_new = True

        # コンテンツ詳細を抽出
        content_details = _extract_content_details(entry.get("ocr_text", ""))

        if should_start_new:
            if current_session is not None:
                sessions.append(_finalize_session(current_session))

            # 新しいセッション開始
            current_session = {
                "start_ts": entry["parsed_ts"],
                "end_ts": entry["parsed_ts"],
                "app": app_name,
                "context": context,
                "session_key": session_key,
                "entry_count": 1,
                "sub_activities": [],  # サブ活動を記録
                "all_descriptions": set(),  # 検出されたすべてのdescription
                "all_content_details": {  # コンテンツ詳細を集約
                    "keywords": set(),
                    "repos": set(),
                    "documents": set(),
                    "search_queries": set(),
                    "topics": set(),
                    "raw_snippets": [],
                    "emails": {}
                }
            }
            if context.get("description"):
                current_session["all_descriptions"].add(context["description"])

            # コンテンツ詳細を追加
            _merge_content_details(current_session["all_content_details"], content_details)
        else:
            # 同じセッション継続
            current_session["end_ts"] = entry["parsed_ts"]
            current_session["entry_count"] += 1

            # サブ活動の追跡: descriptionが変わったら記録
            new_desc = context.get("description")
            if new_desc and new_desc not in current_session["all_descriptions"]:
                current_session["all_descriptions"].add(new_desc)
                current_session["sub_activities"].append({
                    "time": entry["parsed_ts"].strftime("%H:%M"),
                    "description": new_desc
                })

            # コンテンツ詳細を追加
            _merge_content_details(current_session["all_content_details"], content_details)

    # 最後のセッション
    if current_session:
        sessions.append(_finalize_session(current_session))

    return sessions


def _finalize_session(session: dict) -> dict:
    """セッション情報を最終形式に変換"""
    duration_seconds = (session["end_ts"] - session["start_ts"]).total_seconds()
    duration_minutes = max(1, int(duration_seconds / 60))  # 最低1分

    # 作業内容の説明を生成
    context = session["context"]
    app = session["app"]
    description = context.get("description", "")

    # descriptionが空またはアプリ名と同じ場合は代替テキストを使用
    if not description or description == app:
        if context.get("document"):
            description = context["document"]
        elif context.get("page_title"):
            description = context["page_title"]
        elif context.get("project"):
            description = f"プロジェクト: {context['project']}"
        elif context.get("url_domain"):
            description = f"閲覧: {context['url_domain']}"
        else:
            # アプリ別のデフォルト説明
            app_defaults = {
                "Google Chrome": "Webブラウジング",
                "Arc": "Webブラウジング",
                "Safari": "Webブラウジング",
                "Obsidian": "ノート作成",
                "Electron": "エディタ作業",
                "Antigravity": "Claude Code 作業",
                "ghostty": "ターミナル作業",
                "Slack": "チャット",
                "Finder": "ファイル操作",
            }
            description = app_defaults.get(app, f"{app} 作業")

    # サブ活動情報を取得
    sub_activities = session.get("sub_activities", [])
    all_descriptions = list(session.get("all_descriptions", set()))

    result = {
        "start": session["start_ts"].strftime("%H:%M"),
        "end": session["end_ts"].strftime("%H:%M"),
        "duration_minutes": duration_minutes,
        "duration_display": _format_duration(duration_minutes),
        "app": session["app"],
        "description": description,
        "project": context.get("project"),
        "document": context.get("document"),
        "url_domain": context.get("url_domain"),
        "page_title": context.get("page_title")
    }

    # サブ活動がある場合は追加
    if sub_activities:
        result["sub_activities"] = sub_activities
    if len(all_descriptions) > 1:
        result["all_activities"] = all_descriptions

    # コンテンツ詳細を追加（setをlistに変換）
    all_content = session.get("all_content_details", {})
    content_details = {}

    if all_content.get("keywords"):
        content_details["keywords"] = list(all_content["keywords"])[:10]
    if all_content.get("repos"):
        content_details["repos"] = list(all_content["repos"])[:5]
    if all_content.get("documents"):
        content_details["documents"] = list(all_content["documents"])[:5]
    if all_content.get("search_queries"):
        content_details["search_queries"] = list(all_content["search_queries"])[:5]
    if all_content.get("topics"):
        content_details["topics"] = list(all_content["topics"])[:3]
    if all_content.get("raw_snippets"):
        content_details["snippets"] = all_content["raw_snippets"][:5]
    if all_content.get("emails"):
        emails = {}
        if all_content["emails"].get("labels"):
            emails["labels"] = list(all_content["emails"]["labels"])[:10]
        if all_content["emails"].get("contacts"):
            emails["contacts"] = list(all_content["emails"]["contacts"])[:5]
        if emails:
            content_details["emails"] = emails

    if content_details:
        result["content_details"] = content_details

    return result


def _format_duration(minutes: int) -> str:
    """分を表示用フォーマットに変換"""
    if minutes < 60:
        return f"{minutes}分"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}時間"
    return f"{hours}時間{mins}分"


def calculate_hourly_work_minutes(sessions: list[dict]) -> list[dict]:
    """時間帯別作業時間を計算（セッションが時間帯をまたぐ場合は分割）

    Returns:
        24時間分の時間帯別作業時間リスト
    """
    hourly_work = defaultdict(lambda: {'minutes': 0, 'apps': defaultdict(int)})

    for session in sessions:
        start_parts = session['start'].split(':')
        end_parts = session['end'].split(':')
        start_hour = int(start_parts[0])
        start_min = int(start_parts[1])
        end_hour = int(end_parts[0])
        end_min = int(end_parts[1])

        app = session['app']

        if start_hour == end_hour:
            # 同じ時間帯内
            mins = session['duration_minutes']
            hourly_work[start_hour]['minutes'] += mins
            hourly_work[start_hour]['apps'][app] += mins
        else:
            # 時間帯をまたぐ場合
            # 開始時間帯の分数
            first_mins = 60 - start_min
            hourly_work[start_hour]['minutes'] += first_mins
            hourly_work[start_hour]['apps'][app] += first_mins

            # 中間の時間帯（60分ずつ）
            for h in range(start_hour + 1, end_hour):
                hourly_work[h]['minutes'] += 60
                hourly_work[h]['apps'][app] += 60

            # 終了時間帯の分数
            last_mins = end_min
            if last_mins > 0:
                hourly_work[end_hour]['minutes'] += last_mins
                hourly_work[end_hour]['apps'][app] += last_mins

    # 24時間すべてを含む結果を作成
    results = []
    for hour in range(24):
        mins = hourly_work[hour]['minutes']
        main_app = '-'
        if hourly_work[hour]['apps']:
            main_app = max(hourly_work[hour]['apps'].items(), key=lambda x: x[1])[0]

        results.append({
            'hour': f'{hour:02d}-{(hour+1) % 24:02d}',
            'work_minutes': mins,
            'main_app': main_app
        })

    return results


def aggregate_work_sessions(sessions: list[dict]) -> list[dict]:
    """同じ作業内容のセッションを集約"""
    aggregated = {}

    for session in sessions:
        # 集約キー（アプリ + 説明）
        key = (session["app"], session["description"])

        if key not in aggregated:
            aggregated[key] = {
                "app": session["app"],
                "description": session["description"],
                "total_minutes": 0,
                "time_ranges": [],
                "project": session.get("project"),
                "sessions": []
            }

        aggregated[key]["total_minutes"] += session["duration_minutes"]
        aggregated[key]["time_ranges"].append(f"{session['start']}-{session['end']}")
        aggregated[key]["sessions"].append(session)

    # 合計時間でソート
    result = sorted(aggregated.values(), key=lambda x: x["total_minutes"], reverse=True)

    # 表示用フォーマット追加
    for item in result:
        item["total_display"] = _format_duration(item["total_minutes"])
        # 時間帯をまとめる
        if len(item["time_ranges"]) > 3:
            item["time_summary"] = f"{item['time_ranges'][0]} 他{len(item['time_ranges'])-1}回"
        else:
            item["time_summary"] = ", ".join(item["time_ranges"])

    return result


def estimate_main_activities(entries: list[dict], app_usage: list[dict]) -> list[str]:
    """主要作業を推定"""
    activities = []

    # アプリ使用状況から推定
    app_activity_map = {
        "ghostty": "ターミナル操作・開発",
        "Terminal": "ターミナル操作",
        "VS Code": "コーディング",
        "Cursor": "コーディング（AI支援）",
        "Chrome": "ブラウジング・調査",
        "Arc": "ブラウジング・調査",
        "Safari": "ブラウジング",
        "Obsidian": "ノート・ドキュメント作成",
        "Slack": "コミュニケーション",
        "Zoom": "ミーティング",
        "Google Meet": "ミーティング",
        "Finder": "ファイル操作",
    }

    for app_data in app_usage[:5]:  # 上位5アプリ
        app = app_data["app"]
        for key, activity in app_activity_map.items():
            if key.lower() in app.lower():
                if activity not in activities:
                    activities.append(activity)
                break

    return activities[:5]


def analyze(date_str: str) -> dict:
    """メイン分析処理"""
    entries = load_log(date_str)

    if not entries:
        return {
            "date": date_str,
            "error": "ログファイルが存在しないか、エントリがありません",
            "log_path": str(LOG_DIR / f"{date_str}.jsonl")
        }

    # アクティビティ状態を判定
    entries_with_status = detect_activity_status(entries)

    basic_stats = calculate_basic_stats(entries)
    app_usage = analyze_app_usage(entries_with_status)
    hourly_activity = analyze_activity_by_hour(entries_with_status)
    idle_periods = detect_idle_periods(entries_with_status)

    # 作業セッション検出（新機能）
    work_sessions = detect_work_sessions(entries_with_status)
    aggregated_work = aggregate_work_sessions(work_sessions)

    # 時間帯別作業時間（時間をまたぐセッションを正しく分割）
    hourly_work_minutes = calculate_hourly_work_minutes(work_sessions)

    # 統計計算
    total_captures = len(entries_with_status)
    total_active = sum(1 for e in entries_with_status if e["is_active"])
    total_idle = total_captures - total_active
    overall_active_rate = (total_active / total_captures) * 100 if total_captures > 0 else 0

    # idle時間の合計（5分以上の放置期間）
    total_idle_seconds = sum(p["duration_seconds"] for p in idle_periods)
    total_idle_minutes = round(total_idle_seconds / 60, 1)

    # アクティブな時間帯のみをフィルタ
    active_hours = [h for h in hourly_activity if h["status"] == "active"]

    # 作業時間の合計（アクティブセッション）
    total_work_minutes = sum(s["duration_minutes"] for s in work_sessions)

    return {
        "date": date_str,
        "basic_stats": basic_stats,
        "activity_summary": {
            "total_captures": total_captures,
            "active_captures": total_active,
            "idle_captures": total_idle,
            "active_rate": round(overall_active_rate, 1),
            "long_idle_periods": len(idle_periods),
            "total_idle_minutes": total_idle_minutes,
            "total_work_minutes": total_work_minutes,
            "total_work_display": _format_duration(total_work_minutes)
        },
        "work_sessions": work_sessions,  # 詳細な作業セッション
        "aggregated_work": aggregated_work,  # 集約された作業サマリー（本日の作業サマリー用）
        "hourly_work_minutes": hourly_work_minutes,  # 時間帯別作業時間（24時間分）
        "app_usage": app_usage,
        "hourly_activity": hourly_activity,
        "active_hours_only": active_hours,
        "idle_periods": idle_periods
    }


def generate_summary_json(result: dict) -> dict:
    """LLM用のコンパクトなサマリーJSONを生成（定性分析用）"""
    if "error" in result:
        return result

    summary_data = {
        "date": result["date"],
        "basic_stats": result["basic_stats"],
        "activity_summary": result["activity_summary"],
        "hourly_work_minutes": result.get("hourly_work_minutes", []),
    }

    # 作業サマリー（上位10件のみ、詳細なセッション情報は除外）
    aggregated = result.get("aggregated_work", [])
    summary_data["top_work_items"] = [
        {
            "app": w.get("app"),
            "description": w.get("description"),
            "total_minutes": w.get("total_minutes"),
            "total_display": w.get("total_display"),
            "time_summary": w.get("time_summary"),
            "project": w.get("project"),
        }
        for w in aggregated[:10]
    ]

    # 時間帯別の主要セッション（グループ化して要約）
    sessions = result.get("work_sessions", [])
    hourly_sessions = {
        "00-06": [],
        "06-12": [],
        "12-18": [],
        "18-24": [],
    }
    for s in sessions:
        hour = int(s.get("start", "00:00").split(":")[0])
        period = "00-06" if hour < 6 else "06-12" if hour < 12 else "12-18" if hour < 18 else "18-24"
        hourly_sessions[period].append({
            "app": s.get("app"),
            "description": s.get("description"),
            "duration_minutes": s.get("duration_minutes"),
            "project": s.get("project"),
        })

    # 各時間帯の上位5セッションのみ
    summary_data["sessions_by_period"] = {
        period: sorted(sessions, key=lambda x: x.get("duration_minutes", 0), reverse=True)[:5]
        for period, sessions in hourly_sessions.items()
    }

    # アプリ使用状況（上位5つ）
    app_usage = result.get("app_usage", [])
    summary_data["top_apps"] = [
        {
            "app": a.get("app"),
            "active_count": a.get("active_count"),
            "active_percentage": a.get("active_percentage"),
        }
        for a in app_usage[:5]
    ]

    # 放置期間
    idle_periods = result.get("idle_periods", [])
    summary_data["idle_periods"] = [
        {
            "start": p.get("start", "")[-8:-3] if p.get("start") else "",
            "end": p.get("end", "")[-8:-3] if p.get("end") else "",
            "duration_minutes": p.get("duration_minutes"),
        }
        for p in idle_periods[:5]
    ]

    # 検出されたプロジェクト・キーワード
    projects = set()
    keywords = set()
    for s in sessions:
        if s.get("project"):
            projects.add(s["project"])
        content = s.get("content_details", {})
        if content.get("keywords"):
            keywords.update(content["keywords"][:3])
        if content.get("repos"):
            projects.update(content["repos"][:2])

    summary_data["detected_projects"] = list(projects)[:10]
    summary_data["detected_keywords"] = list(keywords)[:15]

    return summary_data


def generate_markdown_report(result: dict) -> str:
    """分析結果からMarkdownレポートを生成"""
    if "error" in result:
        return f"# エラー\n\n{result['error']}"

    date_str = result["date"]
    basic = result["basic_stats"]
    summary = result["activity_summary"]
    sessions = result.get("work_sessions", [])
    aggregated = result.get("aggregated_work", [])
    hourly = result.get("hourly_work_minutes", [])
    app_usage = result.get("app_usage", [])
    idle_periods = result.get("idle_periods", [])

    lines = []

    # ヘッダー
    first_ts = basic.get("first_timestamp", "")[:5] if basic.get("first_timestamp") else ""
    last_ts = basic.get("last_timestamp", "")[-8:-3] if basic.get("last_timestamp") else ""
    if first_ts and len(first_ts) < 5 and basic.get("first_timestamp"):
        first_ts = basic["first_timestamp"][11:16]
    if basic.get("first_timestamp"):
        first_ts = basic["first_timestamp"][11:16]
    if basic.get("last_timestamp"):
        last_ts = basic["last_timestamp"][11:16]

    lines.append(f"# 作業日報 {date_str}")
    lines.append("")
    lines.append(f"記録期間: {first_ts} 〜 {last_ts}")
    lines.append(f"アクティブ作業時間: {summary.get('total_work_display', '0分')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 本日の作業サマリー
    lines.append("## 本日の作業サマリー")
    lines.append("")
    if aggregated:
        lines.append("| 作業内容 | 所要時間 | 時間帯 |")
        lines.append("|---------|---------|--------|")
        for work in aggregated[:10]:  # 上位10件
            app = work.get("app", "")
            desc = work.get("description", "")
            total = work.get("total_display", "")
            time_sum = work.get("time_summary", "")

            # 「アプリ名 - コンテキスト」形式で作業内容を生成
            # descriptionが「{app} 作業」形式の場合はアプリ名のみ
            if desc and desc != f"{app} 作業":
                work_content = f"{app} - {desc}"
            else:
                work_content = app
            lines.append(f"| {work_content} | {total} | {time_sum} |")
    else:
        lines.append("（作業セッションなし）")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 作業詳細（時間軸）
    lines.append("## 作業詳細（時間軸）")
    lines.append("")

    # 時間帯ごとにセッションをグループ化
    time_periods = [
        ("00:00-06:00", "深夜〜早朝", 0, 6),
        ("06:00-12:00", "午前", 6, 12),
        ("12:00-18:00", "午後", 12, 18),
        ("18:00-24:00", "夜", 18, 24),
    ]

    for period_range, period_name, start_h, end_h in time_periods:
        lines.append(f"### {period_range} ｜ {period_name}")
        lines.append("")

        period_sessions = []
        for s in sessions:
            # セッションの開始時間を取得
            start_time = s.get("start", "00:00")
            hour = int(start_time.split(":")[0])
            if start_h <= hour < end_h:
                period_sessions.append(s)

        if period_sessions:
            for s in period_sessions:
                app = s.get("app", "")
                desc = s.get("description", "")
                duration = s.get("duration_display", "")
                lines.append(f"- **{app}**: {desc}（{duration}）")
        else:
            # この時間帯の放置を確認
            has_idle = False
            for idle in idle_periods:
                idle_start = idle.get("start", "")
                if idle_start:
                    idle_hour = int(idle_start[11:13])
                    if start_h <= idle_hour < end_h:
                        has_idle = True
                        break
            if has_idle:
                lines.append("- 放置期間（アイドル）")
            else:
                lines.append("- （記録なし）")
        lines.append("")

    lines.append("---")
    lines.append("")

    # 時間帯別作業時間
    lines.append("## 時間帯別作業時間")
    lines.append("")
    lines.append("| 時間帯 | 作業時間 | 主なアプリ |")
    lines.append("|--------|---------|-----------|")

    for h in hourly:
        hour_range = h.get("hour", "")
        work_mins = h.get("work_minutes", 0)
        main_app = h.get("main_app", "-")
        lines.append(f"| {hour_range}時 | {work_mins}分 | {main_app} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # アプリ使用状況
    lines.append("## アプリ使用状況")
    lines.append("")
    lines.append("| アプリ | 主な用途 |")
    lines.append("|--------|---------|")

    # アプリ別の用途を推定
    app_purpose_map = {
        "Google Chrome": "Webブラウジング・調査",
        "Arc": "Webブラウジング・調査",
        "Safari": "Webブラウジング",
        "Obsidian": "ノート・ドキュメント整理",
        "Slack": "チームコミュニケーション",
        "Electron": "エディタ作業",
        "Antigravity": "Claude Code 作業",
        "ghostty": "ターミナル作業",
        "Finder": "ファイル操作",
        "Cursor": "コーディング（AI支援）",
        "VS Code": "コーディング",
    }

    shown_apps = set()
    for app_data in app_usage[:10]:
        app = app_data.get("app", "")
        if app and app not in shown_apps:
            purpose = app_purpose_map.get(app, f"{app} 作業")
            lines.append(f"| {app} | {purpose} |")
            shown_apps.add(app)

    lines.append("")
    lines.append("---")
    lines.append("")

    # 作業時間サマリー
    lines.append("## 作業時間サマリー")
    lines.append("")
    total_log_mins = basic.get("duration_minutes", 0)
    total_log_display = _format_duration(total_log_mins)
    total_work_mins = summary.get("total_work_minutes", 0)
    total_work_display = summary.get("total_work_display", "0分")
    active_rate = round((total_work_mins / total_log_mins * 100), 1) if total_log_mins > 0 else 0
    idle_count = summary.get("long_idle_periods", 0)
    idle_total = summary.get("total_idle_minutes", 0)

    lines.append(f"- **総ログ時間**: {total_log_display}")
    lines.append(f"- **アクティブ作業時間**: {total_work_display}")
    lines.append(f"- **アクティブ率**: {active_rate}%")
    lines.append(f"- **放置期間**: {idle_count}回（合計{idle_total}分）")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Screen Logger ログ分析スクリプト"
    )
    parser.add_argument(
        "date",
        nargs="?",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="分析対象日（YYYY-MM-DD形式、省略時は今日）"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "markdown", "summary"],
        default="json",
        help="出力形式（json: 完全版, summary: LLM用コンパクト版, markdown: 定量レポート）"
    )

    args = parser.parse_args()
    date_str = args.date

    # 日付形式の検証
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        error_msg = f"Invalid date format: {date_str}. Use YYYY-MM-DD"
        if args.format == "markdown":
            print(f"# エラー\n\n{error_msg}")
        else:
            print(json.dumps({"error": error_msg}))
        sys.exit(1)

    result = analyze(date_str)

    if args.format == "markdown":
        print(generate_markdown_report(result))
    elif args.format == "summary":
        summary = generate_summary_json(result)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
