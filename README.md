# HyperFlux AI

HyperFlux AI is a local Windows assistant built around a GGUF model served by KoboldCpp. This repository keeps the application source and downloads the large runtime assets during setup instead of syncing them to GitHub.

## Project components

- `dist\HyperFlux\HyperFlux.exe` — packaged desktop app; the Inno Setup installer creates shortcuts to this executable.
- `hyperflux_desktop.py` — desktop source entry point for development and fallback launches.
- `hyperflux_interacter.py` — preserved terminal interface and reusable chat/search logic.
- `hyperflux_server.py` — local search bridge used by both interfaces.
- `HyperFlux Web.html` — shared web interface, embedded by the desktop app or opened directly in a browser.
- `setup_assets.ps1` — downloads runtime assets and installs Python dependencies.
- `Start_HyperFlux_Server.bat` — starts KoboldCpp and the search bridge separately from either UI.
- `Run_HyperFlux.bat` — starts the PySide6 desktop UI.
- `Run_HyperFlux_Terminal.bat` — starts the preserved terminal UI.

Downloaded assets are intentionally ignored by Git:

- `python_embed\` — official Python embeddable runtime.
- `koboldcpp.exe` — official [KoboldCpp GitHub release](https://github.com/LostRuins/koboldcpp/releases).
- `model.gguf` — the locally selected Gemma 4 E2B Q4_K_M GGUF. Model weights are not tracked or bundled.

The GGUF is a local model file, not tracked or included in releases. Setup checks its GGUF signature and preserves it; it does not fetch or replace model weights. Review the model provider's terms and the GGUF source's terms before use or redistribution.

## Setup

On Windows 10 or 11, with PowerShell and internet access:

1. Clone or download this repository.
2. Place your chosen model at `model.gguf` in the project folder, then run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup_assets.ps1
   ```

   The script downloads Python 3.14.8 from python.org and the latest official KoboldCpp Windows release from GitHub. It validates and preserves your existing `model.gguf`, then installs packages listed in `requirements.txt`.

3. For a release install, launch HyperFlux from its Start Menu or desktop shortcut. The packaged `.exe` hosts the same `HyperFlux Web.html` interface and starts the selected local services. For a source checkout, `Run_HyperFlux.bat` prefers a built executable when available and otherwise falls back to Python; `Run_HyperFlux_Terminal.bat` retains the terminal interface. `Start_HyperFlux_Server.bat` remains available for manual development runs.

The setup script downloads the runtime and KoboldCpp, but not model weights. Ensure adequate disk space and bandwidth. It keeps existing `koboldcpp.exe` by default and always preserves `model.gguf`; `-Force` only replaces KoboldCpp. `-KoboldVariant` accepts `standard`, `nocuda`, or `oldpc`.

## Runtime and data

- KoboldCpp model API: `http://localhost:5001`
- Search bridge API: `http://127.0.0.1:5002`
- Desktop chat history, settings, and embedded-browser data are stored under `%LOCALAPPDATA%\HyperFlux`.
- The embedded desktop interface and the browser interface keep separate `localStorage` histories and settings.
- The terminal and desktop app retain separate chat histories.

The desktop app embeds the same HTML, styles, and JavaScript used by the browser interface through Qt WebEngine. The embedded interface stores its browser data in a desktop-specific profile and imports existing desktop chats and settings on first launch. Both interfaces communicate directly with KoboldCpp for generation and use `hyperflux_server.py` for search. Start the local servers before using either client.

## Python dependencies

`requirements.txt` contains the external packages used by the desktop, terminal and bridge:

- `PySide6-Essentials` — PySide6 Qt widgets.
- `PySide6-WebEngine` — embeds the shared web interface in the desktop app.
- `requests` — local API and online search HTTP requests.
- `rich` — terminal interface.
- `ddgs` — preferred optional web-search provider, with HTTP fallbacks in the source.

All other imports in the Python application are from the Python standard library.

## Windows release installer

The tagged Windows build creates a PyInstaller `onedir` application bundle and
wraps it in an Inno Setup installer named `HyperFlux-Setup.exe`. The installer
does not contain model weights or a KoboldCpp binary. On first launch, the
setup wizard looks for common local asset locations and lets you browse for an
existing GGUF/KoboldCpp executable; otherwise it offers the official KoboldCpp
release. Model weights must be selected locally and are never downloaded or
silently substituted. Setup logs are written to
`%LOCALAPPDATA%\HyperFlux\logs\setup.log`, and user assets/settings are kept
outside the application install directory.

### Build locally

On 64-bit Windows with Python 3.14.8 and Inno Setup 6 installed:

```powershell
python -m pip install -r requirements-release.txt
python packaging\build_icon.py
python -m PyInstaller --noconfirm --clean packaging\hyperflux.spec
$env:HYPERFLUX_VERSION = "0.0.0-dev"
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" packaging\installer\HyperFlux.iss
python -m unittest discover -s tests -v
.\dist\HyperFlux\HyperFlux.exe --smoke-test
```

The setup workflow runs on a `v*` tag and stores the installer, its SHA-256,
and generated release notes as a GitHub Actions artifact. It does not create
or publish a GitHub Release. Review and manually publish the artifact only
after the packaged smoke test, measured artifact size, release notes, and
legal notice checks have passed.

### Download and disk-space estimate

The local Windows build measured about **158 MiB** for `HyperFlux-Setup.exe`
and **609 MiB** for the installed desktop payload. The current local Gemma 4
E2B Q4_K_M model is about **3.43 GB (3.19 GiB)** and is not included in releases.
KoboldCpp is fetched separately from its current official release; its size
varies by release (the local checkout's existing copy is about 607 MiB). For
a fresh install, reserve roughly **4.5 GB** for the installer, installed app,
local model, and KoboldCpp.

See [LICENSES.md](./LICENSES.md) for the release-blocking third-party license
review checklist and [release-notes/TEMPLATE.md](./release-notes/TEMPLATE.md)
for release notes. Redistribution is not approved until the exact Qt/Chromium,
KoboldCpp, dependency, and model terms and required notices have been checked.
