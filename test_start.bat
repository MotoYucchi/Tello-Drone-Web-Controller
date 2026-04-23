@echo off
chcp 65001 >nul


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
pause
