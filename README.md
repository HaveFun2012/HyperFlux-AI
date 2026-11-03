# HyperFlux AI

HyperFlux AI is a local Windows assistant built around a GGUF model served by KoboldCpp. Application code, assets, tests and build files are organized under `src\`; the root contains this README, the desktop startup launcher, and repository configuration.

## Project layout

```text
Run_HyperFlux.bat          Desktop launcher (start here)
src/
  hyperflux/               Python package with all application code
    paths.py, config.py    File locations and shared settings
    core/                  Chat engine: routing, prompts, /commands, KoboldCpp client, math
    search/                Web search providers, ranking, and the local search bridge (port 5002)
    terminal/              Rich terminal interface       (python -m hyperflux.terminal)
    desktop/               Qt desktop window + setup     (python -m hyperflux.desktop)
  web/                     HyperFlux Web.html and logo_hyperflux/ images
  data/                    hf_brain.json (local canned answers)
  scripts/                 setup_assets.ps1, Run_HyperFlux_Terminal.bat, Start_HyperFlux_Server.bat
  tools/                   dataset_builder.py (regenerates data/hf_brain.json)
  packaging/               PyInstaller spec, icon builder, Inno Setup installer, release notes
  tests/                   Unit tests
```

- `src\dist\HyperFlux\HyperFlux.exe` — packaged desktop app; the Inno Setup installer creates shortcuts to this executable.
- `src\web\HyperFlux Web.html` — shared web interface, embedded by the desktop app or opened directly in a browser.
- `src\scripts\setup_assets.ps1` — downloads runtime assets and installs Python dependencies.
- `src\scripts\Start_HyperFlux_Server.bat` — starts KoboldCpp and the search bridge separately from either UI.
- `src\scripts\Run_HyperFlux_Terminal.bat` — starts the terminal UI.

Downloaded assets are intentionally ignored by Git:

- `src\python_embed\` — official Python embeddable runtime.
- `src\koboldcpp.exe` — official [KoboldCpp GitHub release](https://github.com/LostRuins/koboldcpp/releases).
- `src\model.gguf` — the locally selected Gemma 4 E2B Q4_K_M GGUF. Model weights are not tracked or bundled.

The GGUF is a local model file, not tracked or included in releases. Setup checks its GGUF signature and preserves it; it does not fetch or replace model weights. Review the model provider's terms and the GGUF source's terms before use or redistribution.

## Setup

On Windows 10 or 11, with PowerShell and internet access:

1. Clone or download this repository.
2. Place your chosen model at `src\model.gguf`, then run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\src\scripts\setup_assets.ps1
   ```

   The script downloads Python 3.14.8 from python.org and the latest official KoboldCpp Windows release from GitHub. It validates and preserves your existing `model.gguf`, then installs packages listed in `requirements.txt`.

3. For a release install, launch HyperFlux from its Start Menu or desktop shortcut. The packaged `.exe` hosts the same `src\web\HyperFlux Web.html` interface and starts the selected local services. For a source checkout, root-level `Run_HyperFlux.bat` prefers a built executable under `src` when available and otherwise falls back to Python (`python -m hyperflux.desktop`); `src\scripts\Run_HyperFlux_Terminal.bat` retains the terminal interface. `src\scripts\Start_HyperFlux_Server.bat` remains available for manual development runs.

The setup script downloads the runtime and KoboldCpp, but not model weights. Ensure adequate disk space and bandwidth. It keeps existing `src\koboldcpp.exe` by default and always preserves `src\model.gguf`; `-Force` only replaces KoboldCpp. `-KoboldVariant` accepts `standard`, `nocuda`, or `oldpc`.

## Runtime and data

- KoboldCpp model API: `http://localhost:5001`
- Search bridge API: `http://127.0.0.1:5002`
- Desktop chat history, settings, and embedded-browser data are stored under `%LOCALAPPDATA%\HyperFlux`.
- KoboldCpp output is written to `%LOCALAPPDATA%\HyperFlux\logs\kobold.log` and is available from the **Server logs** button beside the server status.
- Normal model replies include a collapsed **Thinking summary** that can be opened or hidden; greetings and direct name questions skip it. The summary is a brief user-facing rationale, not private chain-of-thought.
- The embedded desktop interface and the browser interface keep separate `localStorage` histories and settings.
- The terminal and desktop app retain separate chat histories.

The desktop app embeds the same HTML, styles, and JavaScript used by the browser interface through Qt WebEngine. The embedded interface stores its browser data in a desktop-specific profile and imports existing desktop chats and settings on first launch. Both interfaces communicate directly with KoboldCpp for generation and use the search bridge (`src\hyperflux\search\bridge.py`) for search. Start the local servers before using either client.

## Python dependencies

`src\requirements.txt` contains the external packages used by the desktop, terminal and bridge:

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
release. If no model is found, it offers to download the recommended
Gemma 4 E2B Q4_K_M (3.4 GB, Apache 2.0) after showing its licence. The file is
pinned to one Hugging Face commit (`lmstudio-community/gemma-4-E2B-it-GGUF`)
and checked against a fixed SHA-256, and it is saved to
`%LOCALAPPDATA%\HyperFlux\models`. Existing model files are never replaced or
silently substituted. Setup logs are written to
`%LOCALAPPDATA%\HyperFlux\logs\setup.log`, and user assets/settings are kept
outside the application install directory.

### Build locally

On 64-bit Windows with Python 3.14.8 and Inno Setup 6 installed, close HyperFlux
(its files are locked while it runs), then:

```powershell
python -m pip install -r src\requirements-release.txt
python -m unittest discover -s src\tests -t src -v
powershell -ExecutionPolicy Bypass -File src\packaging\build_release.ps1
```

`build_release.ps1` builds the app, smoke-tests it, builds the installer and
writes the release notes. It takes the version from `src\hyperflux\version.py`.
The result is `src\dist\HyperFlux-Setup.exe`, plus its `.sha256` and
`RELEASE-NOTES.md`.

### Releasing a new version

1. Set `__version__` in `src\hyperflux\version.py` (for example `"1.1.0"`).
2. Commit, then tag and push it: `git tag v1.1.0` and `git push origin v1.1.0`.
   The workflow refuses to build if the tag and `version.py` differ.
3. Publish a GitHub release for the tag with `HyperFlux-Setup.exe` attached.
   Installed copies of HyperFlux will then offer the update.

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
review checklist and [TEMPLATE.md](./src/packaging/release-notes/TEMPLATE.md)
for release notes. Redistribution is not approved until the exact Qt/Chromium,
KoboldCpp, dependency, and model terms and required notices have been checked.
