@echo off
title HyperFlux Launcher
cd /d "%~dp0"

echo [1/3] Launching Kobold - HyperFlux Server...
start /b koboldcpp.exe --model model.gguf --port 5001 --skiplaunch

echo Waiting for model to spin up...
timeout /t 5 /nobreak > nul

echo [2/3] Launching the local web search service...
start "" /b python_embed\pythonw.exe main.py --search-bridge
timeout /t 2 /nobreak > nul

echo [3/3] Launching HyperFlux - HyperFlux Gen 5.4 Gemma3...
start "HyperFlux - HyperFlux Gen 5.4 Gemma3" python_embed\python.exe main.py

echo HyperFlux and the local web search service are running.
pause