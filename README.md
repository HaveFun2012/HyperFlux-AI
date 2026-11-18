# HyperFlux AI

HyperFlux AI is a local Windows assistant built around a GGUF model served by KoboldCpp. Application code, assets, tests and build files are organized under `src\`; the root contains this README, the desktop startup launcher, and repository configuration.

## Features

**Models.** Three HyperFlux models run on the same local model and differ in speed, thinking and answer length:

| Model | Thinking | Best for |
| :--- | :--- | :--- |
| Flash 1 | Never | Quick everyday questions |
| Apex 1 (default) | **Think** button, off by default | Most tasks |
| Horizon 1 | Always, in depth | Hard maths, code, analysis and planning |

Riddles and real-world "what happens if" questions think automatically even with **Think** off.

**Answer style.** Answers start with the point in the first sentence and match their length to the question: a simple question gets one to three sentences. They are written as plain prose, with lists or tables only where they help, and say "I'm not sure" when that is true. A wrong premise in the question is corrected politely. Apex 1's instructions include short example exchanges, because a small model copies examples better than it follows rules. Today's date is part of every prompt.

**In the desktop app:**

- **Pictures:** attach a photo or screenshot with the paperclip and ask about it. Turn this on once in **Settings → Image input**, which downloads the vision file for your Gemma 4 E2B or E4B model (about 1 GB).
- **Read aloud:** a **Read aloud** button under every answer speaks it with the Windows voices; the voice is chosen in Settings.
- **Custom instructions:** tell HyperFlux about yourself once (**Settings → Custom instructions**, up to 1,500 characters), and it is sent with every message.
- **Personas:** Default, Tutor, Coder, Concise or Friendly change the tone (**Settings → Persona** or `/persona tutor`).
- **Chats:** every chat is saved on this PC. The box above **Recent Chats** searches titles and message text, and the download icon on a chat (or `/export`) saves it as a Markdown file.
- **Answers:** Copy and Retry on every answer, Edit on your last message, Stop while it writes. Long answers continue automatically instead of being cut off.
- **Formatting:** LaTeX maths, tables and code blocks with Copy buttons.
- **Web search:** questions about current events are searched automatically, with sources. `/search <question>` searches on demand.
- **Files:** attach a text or code file for review (the first 3,000 characters are read).
- **Commands:** type `/` to see them: `/help`, `/search`, `/read`, `/persona`, `/export`, `/sys`, `/temp`, `/length`.
- **Looks:** six colour themes in Dark, Light or Match system, a custom accent colour and text size.
- **Model picker:** switch between the GGUF models on this PC without restarting.

**In the terminal app** (`src\scripts\Run_HyperFlux_Terminal.bat`): the same models and answer style, plus `/model`, `/think`, `/thinking`, `/persona`, `/instructions <text>|clear` and `/export`. The persona and custom instructions are remembered between sessions. Pictures, read aloud and chat search are desktop-only.

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
                           vision.py downloads the image-input file and reloads KoboldCpp
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
- When a model thinks (Horizon 1, Apex 1 with **Think** on, or a riddle), its thinking streams live and then folds into a collapsed box above the answer. Greetings and direct name questions never think.
- **Image input** uses a vision projector file (`mmproj-gemma-4-E2B-it-BF16.gguf` or `mmproj-gemma-4-E4B-it-BF16.gguf`, about 1 GB) saved to `%LOCALAPPDATA%\HyperFlux\models`. It is pinned to the same Hugging Face commits as the models and checked against a fixed SHA-256. When it is present, the desktop app starts KoboldCpp with `--mmproj`. Pictures are reduced to at most 1,024 pixels on their longest side before they are sent and saved; if chat storage fills up, the oldest pictures are removed first and the text is kept. Answers about pictures are slower, especially on GPUs with 4 GB or less.
- The embedded desktop interface and the browser interface keep separate `localStorage` histories and settings, including custom instructions and persona.
- The terminal and desktop app retain separate chat histories. The terminal's persona and custom instructions are stored in `%LOCALAPPDATA%\HyperFlux\terminal_settings.json`, and `/export` in the terminal writes to `Documents\HyperFlux exports`.

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
release. If no model is found, it offers to download one after showing its
licence: the recommended Gemma 4 E2B Q4_K_M (3.4 GB, fast, fine on 8 GB of RAM)
is pre-selected, and Gemma 4 E4B Q4_K_M (5.3 GB, better reasoning but slower,
best with 16 GB) is an optional choice. Setup shows the PC's RAM as a hint but
never chooses for the user. Each file is pinned to one Hugging Face commit
(`lmstudio-community/gemma-4-E2B-it-GGUF` / `gemma-4-E4B-it-GGUF`) and checked
against a fixed SHA-256, and it is saved to `%LOCALAPPDATA%\HyperFlux\models`.
To switch models later, close HyperFlux and use the **Change HyperFlux model**
Start menu shortcut (`HyperFlux.exe --setup`). Existing model files are never replaced or
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
local model, and KoboldCpp, plus about **1 GB** if you turn on image input.

See [LICENSES.md](./LICENSES.md) for the release-blocking third-party license
review checklist and [TEMPLATE.md](./src/packaging/release-notes/TEMPLATE.md)
for release notes. Redistribution is not approved until the exact Qt/Chromium,
KoboldCpp, dependency, and model terms and required notices have been checked.
