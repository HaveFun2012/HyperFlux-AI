@echo off
title HyperFlux AI Desktop
set "PROJECT_DIR=%~dp0src"
cd /d "%PROJECT_DIR%"

if exist "%PROJECT_DIR%\HyperFlux.exe" (
    start "HyperFlux AI" "%PROJECT_DIR%\HyperFlux.exe"
    exit /b 0
)

if exist "%PROJECT_DIR%\dist\HyperFlux\HyperFlux.exe" (
    start "HyperFlux AI" "%PROJECT_DIR%\dist\HyperFlux\HyperFlux.exe"
    exit /b 0
)

if not exist "%PROJECT_DIR%\python_embed\pythonw.exe" (
    echo Python runtime is missing. Run src\scripts\setup_assets.ps1 first.
    pause
    exit /b 1
)

"%PROJECT_DIR%\python_embed\python.exe" -c "from PySide6.QtWebEngineWidgets import QWebEngineView" >nul 2>&1
if errorlevel 1 (
    echo Qt WebEngine is missing. Run src\scripts\setup_assets.ps1 to install desktop dependencies.
    pause
    exit /b 1
)

start "HyperFlux AI" "%PROJECT_DIR%\python_embed\pythonw.exe" -m hyperflux.desktop
