# HyperFlux AI

HyperFlux AI is a Windows-based local AI assistant built around a GGUF model served by KoboldCPP. It brings together a terminal interface, a companion browser UI, local web-search support, and workspace-aware tools in one lightweight setup.

This project is designed for users who want to run an AI locally without relying on cloud-based services for every interaction.

## Overview

HyperFlux AI is a local-first assistant that connects to a model running through Kobold - HyperFlux Server and exposes it through a clean interactive experience. It supports chat, file reading, session memory, web search, and lightweight utility commands.

The project includes:
- a terminal-based chat interface
- a companion HTML interface
- local search bridge support
- workspace file inspection commands
- model status and runtime controls
- safe math handling for quick calculations

## Current Features

- Local chat with a GGUF model via KoboldCPP
- Rich terminal UI with embedded status and command support
- Companion browser interface for a more visual workflow
- Local web search bridge with fallback search providers
- Workspace-aware file reading using `/read`
- Session memory and local knowledge support
- Runtime commands for help, status, search, temperature, and output length
- Safe arithmetic evaluation for simple math queries
- Adjustable generation settings such as temperature and max output length
- Separate conversation histories between the terminal and HTML interface

## Requirements

Before running HyperFlux AI, make sure the following files are present in the project folder:

- `koboldcpp.exe`
- `model.gguf`
- `python_embed\`
- `Run_HyperFlux.bat`
- `main.py`

Recommended environment:
- Windows 10 or Windows 11
- Local internet access for downloading required assets and web search results
- A valid GGUF model compatible with KoboldCPP

## Setup

1. Place the required files in the same project directory as `main.py`.
2. Make sure `koboldcpp.exe` and `model.gguf` are available at the root of the project.
3. Confirm that the bundled Python runtime exists inside `python_embed\`.
4. Ensure the model is compatible with KoboldCPP before starting the app.

> Note: A future improvement would be to add an automatic downloader for `python_embed`, `koboldcpp.exe`, and `model.gguf`.

## Running the Project

### Option 1: Use the launcher
Double-click:

```bat
Run_HyperFlux.bat