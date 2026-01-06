#!/usr/bin/env python3
"""Screen Logger - スクリーンショット + OCR ログ収集"""

import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

import Quartz.CoreGraphics as CG
import Vision
import yaml
from Foundation import NSURL


def log_error(message: str):
    """タイムスタンプ付きでエラーを出力"""
    timestamp = datetime.now().isoformat()
    print(f"[{timestamp}] ERROR: {message}", file=sys.stderr)


def get_active_window() -> str:
    """アクティブなアプリ名とウィンドウタイトルを取得"""
    script = '''
    tell application "System Events"
        set frontProcess to first application process whose frontmost is true
        set processName to name of frontProcess
        set frontWindow to ""
        try
            tell frontProcess
                set frontWindow to name of front window
            end tell
        end try
    end tell

    -- Finderで実際のアプリ名を取得（Electronアプリ対応）
    set appName to processName
    try
        tell application "Finder"
            set appPath to (application file of application process processName) as alias
            set appName to displayed name of appPath
            if appName ends with ".app" then
                set appName to text 1 thru -5 of appName
            end if
        end tell
    end try

    return appName & " | " & frontWindow
    '''
    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


def is_display_asleep() -> bool:
    """ディスプレイがスリープ中かどうかを判定"""
    err, display_ids, count = CG.CGGetActiveDisplayList(10, None, None)
    if err != 0 or count == 0:
        return True  # エラー時はスリープ扱い

    # メインディスプレイがスリープ中かチェック
    main_display = CG.CGMainDisplayID()
    return CG.CGDisplayIsAsleep(main_display) == 1


def get_active_window_display() -> int:
    """アクティブウィンドウがあるディスプレイ番号を取得（1-indexed）"""
    # アクティブウィンドウの位置を取得
    windows = CG.CGWindowListCopyWindowInfo(
        CG.kCGWindowListOptionOnScreenOnly | CG.kCGWindowListExcludeDesktopElements,
        CG.kCGNullWindowID
    )

    window_x = None
    for w in windows:
        layer = w.get('kCGWindowLayer', 999)
        if layer == 0:  # 通常のウィンドウレイヤー
            bounds = w.get('kCGWindowBounds', {})
            window_x = bounds.get('X', 0)
            break

    if window_x is None:
        return 1  # デフォルトはメインディスプレイ

    # 各ディスプレイの境界を取得
    err, display_ids, count = CG.CGGetActiveDisplayList(10, None, None)
    if err != 0:
        return 1

    for i, did in enumerate(display_ids[:count]):
        bounds = CG.CGDisplayBounds(did)
        x_min = bounds.origin.x
        x_max = x_min + bounds.size.width
        if x_min <= window_x < x_max:
            return i + 1  # screencaptureは1-indexed

    return 1  # デフォルトはメインディスプレイ


def capture_active_display(tmp_dir: Path, timestamp: str) -> Path:
    """アクティブウィンドウがあるディスプレイのみをキャプチャ"""
    display_num = get_active_window_display()
    path = tmp_dir / f"capture_{timestamp}.png"
    subprocess.run(['screencapture', '-x', f'-D{display_num}', str(path)])
    return path


def ocr_image(image_path: Path) -> str:
    """Vision FrameworkでOCR処理"""
    image_url = NSURL.fileURLWithPath_(str(image_path))

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLanguages_(["ja", "en"])
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)

    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
        image_url, None
    )
    success, error = handler.performRequests_error_([request], None)

    if not success:
        return ""

    results = request.results()
    text_lines = []
    for observation in results:
        candidates = observation.topCandidates_(1)
        if candidates:
            text_lines.append(candidates[0].string())

    return "\n".join(text_lines)


def save_log(timestamp: datetime, window: str, ocr_text: str, log_dir: Path):
    """ログをJSONL形式で保存"""
    log_entry = {
        "timestamp": timestamp.isoformat(),
        "window": window,
        "ocr_text": ocr_text
    }

    log_file = log_dir / f"{timestamp.strftime('%Y-%m-%d')}.jsonl"
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def load_config(config_path: Path) -> dict:
    """設定ファイル読み込み"""
    if not config_path.exists():
        return {}
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def should_exclude(window: str, config: dict) -> bool:
    """除外対象かどうか判定"""
    exclude = config.get('exclude', {})
    app_name = window.split(" | ")[0] if " | " in window else window

    # 除外アプリ
    if app_name in exclude.get('apps', []):
        return True

    # 除外パターン
    for pattern in exclude.get('window_patterns', []):
        if pattern.lower() in window.lower():
            return True

    return False


def main():
    screenshot_path = None
    try:
        # パス設定
        base_dir = Path(__file__).parent
        config_path = base_dir / "config.yaml"
        log_dir = base_dir / "logs"
        tmp_dir = base_dir / "tmp"

        # ディレクトリ作成
        log_dir.mkdir(exist_ok=True)
        tmp_dir.mkdir(exist_ok=True)

        # 設定読み込み
        config = load_config(config_path)

        # ディスプレイスリープ中はスキップ
        if is_display_asleep():
            return

        # タイムスタンプ
        now = datetime.now()

        # 1. ウィンドウ名取得
        window = get_active_window()

        # 除外チェック
        if should_exclude(window, config):
            return

        # 2. アクティブウィンドウがあるディスプレイのみスクリーンショット
        timestamp_str = now.strftime('%Y%m%d_%H%M%S')
        screenshot_path = capture_active_display(tmp_dir, timestamp_str)

        # 3. OCR
        ocr_text = ocr_image(screenshot_path)

        # OCRテキストが空の場合はスキップ
        if not ocr_text.strip():
            return

        # 4. ログ保存
        save_log(now, window, ocr_text, log_dir)

    except Exception as e:
        log_error(f"{type(e).__name__}: {e}")
        log_error(traceback.format_exc())
    finally:
        # 5. 画像削除（エラー時も確実に削除）
        if screenshot_path and screenshot_path.exists():
            screenshot_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
