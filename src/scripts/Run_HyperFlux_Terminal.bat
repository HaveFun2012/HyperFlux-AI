@echo off
title HyperFlux AI Terminal
rem Run from src\ so the hyperflux package is importable.
cd /d "%~dp0.."

if not exist "python_embed\python.exe" (
    echo Python runtime is missing. Run scripts\setup_assets.ps1 first.
    pause
    exit /b 1
)

python_embed\python.exe -m hyperflux.terminal
