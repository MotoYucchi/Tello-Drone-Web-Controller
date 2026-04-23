@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
:: Tello Drone Web Controller — Launcher (Windows)
:: ============================================================

title Tello Drone Web Controller

echo.
echo  ============================================================
echo   Tello Drone Web Controller - Setup ^& Launcher
echo  ============================================================
echo.
echo   Please select your language / 言語を選択してください
echo.
echo     [1] English
echo     [2] 日本語
echo.
set /p LANG_CHOICE="  Select [1/2]: "

if "%LANG_CHOICE%"=="2" goto :LANG_JA
goto :LANG_EN

:: ============================================================
:: ENGLISH
:: ============================================================
:LANG_EN
cls
echo.
echo  ============================================================
echo   Tello Drone Web Controller - Setup ^& Launcher
echo  ============================================================
echo.

echo  [1/4] Checking uv installation...
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   uv is not installed.
    echo   Installing uv...
    echo.
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if %errorlevel% neq 0 (
        echo.
        echo   [ERROR] Failed to install uv.
        echo   Please install manually: https://docs.astral.sh/uv/
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   uv installed successfully!
    echo   NOTE: You may need to restart this script for PATH changes to take effect.
    echo.

    :: Refresh PATH to pick up new uv installation
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"

    :: Verify again
    where uv >nul 2>&1
    if %errorlevel% neq 0 (
        echo   [WARNING] uv not found in PATH after install.
        echo   Trying common install locations...
        if exist "%USERPROFILE%\.local\bin\uv.exe" (
            set "PATH=%USERPROFILE%\.local\bin;%PATH%"
            echo   Found uv at %USERPROFILE%\.local\bin
        ) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
            set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
            echo   Found uv at %USERPROFILE%\.cargo\bin
        ) else (
            echo.
            echo   [ERROR] Cannot find uv. Please restart this script after installation.
            pause
            exit /b 1
        )
    )
) else (
    for /f "tokens=*" %%v in ('uv --version 2^>nul') do set UV_VER=%%v
    echo   uv is installed: !UV_VER!
)

echo.
echo  [2/4] Synchronizing dependencies with uv sync...
echo.
uv sync
if %errorlevel% neq 0 (
    echo.
    echo   [ERROR] uv sync failed.
    echo   Please check the error messages above.
    echo.
    pause
    exit /b 1
)

echo.
echo   Dependencies synchronized successfully!

echo.
echo  [3/4] Ready to start!
echo.
echo   #################################################
echo     Server will start at:  http://localhost:8000
echo     Press Ctrl+C to stop the server.           
echo   #################################################
echo.
echo  [4/4] Starting Tello Web Controller...
echo.

uv run python -m src

echo
echo Server has been stopped.
goto :END


:: ============================================================
:: 日本語
:: ============================================================
:LANG_JA
cls
echo.
echo  ============================================================
echo   Tello Drone Web Controller − セットアップ ＆ ランチャー
echo  ============================================================
echo.

echo  [1/4] uv のインストール確認中...
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   uv がインストールされていません。
    echo   uv をインストールします...
    echo.
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if %errorlevel% neq 0 (
        echo.
        echo   [エラー] uv のインストールに失敗しました。
        echo   手動でインストールしてください: https://docs.astral.sh/uv/
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   uv のインストールが完了しました！
    echo   ※ PATHの反映のため、スクリプトの再起動が必要な場合があります。
    echo.

    :: PATHを更新してインストールされたuvを認識
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"

    :: 再確認
    where uv >nul 2>&1
    if %errorlevel% neq 0 (
        echo   [警告] インストール後もuvがPATHに見つかりません。
        echo   既知のインストール先を確認中...
        if exist "%USERPROFILE%\.local\bin\uv.exe" (
            set "PATH=%USERPROFILE%\.local\bin;%PATH%"
            echo   %USERPROFILE%\.local\bin に見つかりました
        ) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
            set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
            echo   %USERPROFILE%\.cargo\bin に見つかりました
        ) else (
            echo.
            echo   [エラー] uv が見つかりません。インストール完了後にスクリプトを再起動してください。
            pause
            exit /b 1
        )
    )
) else (
    for /f "tokens=*" %%v in ('uv --version 2^>nul') do set UV_VER=%%v
    echo   uv インストール済み: !UV_VER!
)

echo.
echo  [2/4] uv sync で依存パッケージを同期中...
echo.
uv sync
if %errorlevel% neq 0 (
    echo.
    echo   [エラー] uv sync に失敗しました。
    echo   上記のエラーメッセージを確認してください。
    echo.
    pause
    exit /b 1
)

echo.
echo   依存パッケージの同期が完了しました！

echo.
echo  [3/4] 起動準備完了！
echo.
echo   #################################################
echo     サーバーアドレス:  http://localhost:8000  
echo     停止するには Ctrl+C を押してください             
echo   #################################################
echo.
echo  [4/4] Tello Web Controller を起動中...
echo.

uv run python -m src


echo
echo サーバーが停止しました。

:END
endlocal