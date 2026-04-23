#!/usr/bin/env bash
# ============================================================
# Tello Drone Web Controller — Launcher (macOS / Linux)
# ============================================================

set -e

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# --- Change to script directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================
# Language Selection
# ============================================================
echo ""
echo -e "${BOLD} ============================================================${NC}"
echo -e "${BOLD}  Tello Drone Web Controller - Setup & Launcher${NC}"
echo -e "${BOLD} ============================================================${NC}"
echo ""
echo "  Please select your language / 言語を選択してください"
echo ""
echo "    [1] English"
echo "    [2] 日本語"
echo ""
read -rp "  Select [1/2]: " LANG_CHOICE

# ============================================================
# English Messages
# ============================================================
if [ "$LANG_CHOICE" != "2" ]; then

    clear
    echo ""
    echo -e "${BOLD} ============================================================${NC}"
    echo -e "${BOLD}  Tello Drone Web Controller - Setup & Launcher${NC}"
    echo -e "${BOLD} ============================================================${NC}"
    echo ""

    # --- Step 1: Check uv ---
    echo -e " ${CYAN}[1/4]${NC} Checking uv installation..."

    if ! command -v uv &>/dev/null; then
        echo ""
        echo -e "  ${YELLOW}uv is not installed.${NC}"
        echo "  Installing uv..."
        echo ""

        curl -LsSf https://astral.sh/uv/install.sh | sh

        if [ $? -ne 0 ]; then
            echo ""
            echo -e "  ${RED}[ERROR] Failed to install uv.${NC}"
            echo "  Please install manually: https://docs.astral.sh/uv/"
            exit 1
        fi

        echo ""
        echo -e "  ${GREEN}uv installed successfully!${NC}"

        # Refresh PATH
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

        # Source shell profile if available
        if [ -f "$HOME/.bashrc" ]; then
            source "$HOME/.bashrc" 2>/dev/null || true
        elif [ -f "$HOME/.zshrc" ]; then
            source "$HOME/.zshrc" 2>/dev/null || true
        fi

        # Verify
        if ! command -v uv &>/dev/null; then
            echo ""
            echo -e "  ${RED}[ERROR] Cannot find uv in PATH after installation.${NC}"
            echo "  Please restart your terminal and run this script again."
            exit 1
        fi
    else
        UV_VER=$(uv --version 2>/dev/null || echo "unknown")
        echo -e "  uv is installed: ${GREEN}${UV_VER}${NC}"
    fi

    # --- Step 2: uv sync ---
    echo ""
    echo -e " ${CYAN}[2/4]${NC} Synchronizing dependencies with uv sync..."
    echo ""

    uv sync

    if [ $? -ne 0 ]; then
        echo ""
        echo -e "  ${RED}[ERROR] uv sync failed.${NC}"
        echo "  Please check the error messages above."
        exit 1
    fi

    echo ""
    echo -e "  ${GREEN}Dependencies synchronized successfully!${NC}"

    # --- Step 3: Ready ---
    echo ""
    echo -e " ${CYAN}[3/4]${NC} Ready to start!"
    echo ""
    echo "  ┌─────────────────────────────────────────────┐"
    echo "  │  Server will start at:  http://localhost:8000│"
    echo "  │  Press Ctrl+C to stop the server.           │"
    echo "  └─────────────────────────────────────────────┘"
    echo ""

    # --- Step 4: Launch ---
    echo -e " ${CYAN}[4/4]${NC} Starting Tello Web Controller..."
    echo ""

    uv run python -m src

# ============================================================
# Japanese Messages (日本語)
# ============================================================
else

    clear
    echo ""
    echo -e "${BOLD} ============================================================${NC}"
    echo -e "${BOLD}  Tello Drone Web Controller − セットアップ ＆ ランチャー${NC}"
    echo -e "${BOLD} ============================================================${NC}"
    echo ""

    # --- Step 1: uv 確認 ---
    echo -e " ${CYAN}[1/4]${NC} uv のインストール確認中..."

    if ! command -v uv &>/dev/null; then
        echo ""
        echo -e "  ${YELLOW}uv がインストールされていません。${NC}"
        echo "  uv をインストールします..."
        echo ""

        curl -LsSf https://astral.sh/uv/install.sh | sh

        if [ $? -ne 0 ]; then
            echo ""
            echo -e "  ${RED}[エラー] uv のインストールに失敗しました。${NC}"
            echo "  手動でインストールしてください: https://docs.astral.sh/uv/"
            exit 1
        fi

        echo ""
        echo -e "  ${GREEN}uv のインストールが完了しました！${NC}"

        # PATHを更新
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

        # シェルプロファイルを読み込み
        if [ -f "$HOME/.bashrc" ]; then
            source "$HOME/.bashrc" 2>/dev/null || true
        elif [ -f "$HOME/.zshrc" ]; then
            source "$HOME/.zshrc" 2>/dev/null || true
        fi

        # 再確認
        if ! command -v uv &>/dev/null; then
            echo ""
            echo -e "  ${RED}[エラー] インストール後もuvがPATHに見つかりません。${NC}"
            echo "  ターミナルを再起動してから再実行してください。"
            exit 1
        fi
    else
        UV_VER=$(uv --version 2>/dev/null || echo "不明")
        echo -e "  uv インストール済み: ${GREEN}${UV_VER}${NC}"
    fi

    # --- Step 2: uv sync ---
    echo ""
    echo -e " ${CYAN}[2/4]${NC} uv sync で依存パッケージを同期中..."
    echo ""

    uv sync

    if [ $? -ne 0 ]; then
        echo ""
        echo -e "  ${RED}[エラー] uv sync に失敗しました。${NC}"
        echo "  上記のエラーメッセージを確認してください。"
        exit 1
    fi

    echo ""
    echo -e "  ${GREEN}依存パッケージの同期が完了しました！${NC}"

    # --- Step 3: 準備完了 ---
    echo ""
    echo -e " ${CYAN}[3/4]${NC} 起動準備完了！"
    echo ""
    echo "  ┌──────────────────────────────────────────────────┐"
    echo "  │  サーバーアドレス:  http://localhost:8000         │"
    echo "  │  停止するには Ctrl+C を押してください             │"
    echo "  └──────────────────────────────────────────────────┘"
    echo ""

    # --- Step 4: 起動 ---
    echo -e " ${CYAN}[4/4]${NC} Tello Web Controller を起動中..."
    echo ""

    uv run python -m src

fi
