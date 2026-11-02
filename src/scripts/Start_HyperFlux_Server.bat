@echo off
title HyperFlux AI Local Servers
rem Run from src\, where the runtime assets live.
cd /d "%~dp0.."

if not exist "python_embed\pythonw.exe" (
    echo Python runtime is missing. Run scripts\setup_assets.ps1 first.
    pause
    exit /b 1
)
if not exist "koboldcpp.exe" (
    echo KoboldCpp is missing. Run scripts\setup_assets.ps1 first.
    pause
    exit /b 1
)
if not exist "model.gguf" (
    echo GGUF model is missing. Run scripts\setup_assets.ps1 first.
    pause
    exit /b 1
)

if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "LOG_DIR=%LOCALAPPDATA%\HyperFlux\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "KOBOLD_LOG=%LOG_DIR%\kobold.log"

echo Starting KoboldCpp on port 5001...
start "HyperFlux KoboldCpp server" /b koboldcpp.exe --model model.gguf --port 5001 --skiplaunch > "%KOBOLD_LOG%" 2>&1
timeout /t 5 /nobreak > nul

echo Starting the local search bridge on port 5002...
start "HyperFlux search bridge" /b python_embed\pythonw.exe -m hyperflux.search.bridge

echo Local server processes started. Launch Run_HyperFlux.bat or scripts\Run_HyperFlux_Terminal.bat.
