@echo off
title HyperFlux AI Desktop
cd /d "%~dp0"

if not exist "python_embed\pythonw.exe" (
    echo Python runtime is missing. Run setup_assets.ps1 first.
    pause
    exit /b 1
)

python_embed\python.exe -c "from PySide6.QtWebEngineWidgets import QWebEngineView" >nul 2>&1
if errorlevel 1 (
    echo Qt WebEngine is missing. Run setup_assets.ps1 to install desktop dependencies.
    pause
    exit /b 1
)

start "HyperFlux AI" python_embed\pythonw.exe hyperflux_desktop.py
