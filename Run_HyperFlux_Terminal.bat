@echo off
title HyperFlux AI Terminal
cd /d "%~dp0"

if not exist "python_embed\python.exe" (
    echo Python runtime is missing. Run setup_assets.ps1 first.
    pause
    exit /b 1
)

python_embed\python.exe hyperflux_interacter.py
