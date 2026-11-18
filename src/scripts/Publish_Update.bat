@echo off
title HyperFlux - publish an update
rem Tags a new version and lets GitHub build it as a draft release. See publish_update.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_update.ps1"
pause
