# screen-logger Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-12-28

## Active Technologies

- Python 3.11+ (uv で管理) + pyobjc-framework-Vision, pyobjc-framework-Quartz, PyYAML (001-screen-capture)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11+ (uv で管理): Follow standard conventions

## Recent Changes

- 001-screen-capture: Added Python 3.11+ (uv で管理) + pyobjc-framework-Vision, pyobjc-framework-Quartz, PyYAML

<!-- MANUAL ADDITIONS START -->

## launchd 設定

`com.user.screenlogger.plist` を `~/Library/LaunchAgents/` に配置して使用。

### 主要設定

- `StartInterval`: 60秒間隔で実行
- `RunAtLoad`: ログイン時に自動開始
- `ProcessType: Background`: スリープを妨げない（重要）

### コマンド

```bash
# 設定を反映（plist変更後）
launchctl unload ~/Library/LaunchAgents/com.user.screenlogger.plist
/bin/cp com.user.screenlogger.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.screenlogger.plist

# 状態確認
launchctl list | grep screenlogger

# 停止
launchctl unload ~/Library/LaunchAgents/com.user.screenlogger.plist

# 開始
launchctl load ~/Library/LaunchAgents/com.user.screenlogger.plist
```

### 権限設定

uv（または実行されるPython）に画面収録権限が必要:
- システム設定 > プライバシーとセキュリティ > 画面収録 > uv を追加

<!-- MANUAL ADDITIONS END -->
