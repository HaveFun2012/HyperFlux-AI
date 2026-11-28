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

- **Pictures:** attach a photo or screenshot with the paperclip and ask about it, including follow-up questions. HyperFlux keeps seeing the latest picture in the chat. Before sending, you can drag a box around the part that matters, such as small text, so it reaches the model much larger. If HyperFlux can't read something in a picture, it says so instead of guessing. Turn this on once in **Settings → Voice & pictures**, which downloads the vision file for your Gemma 4 E2B or E4B model (about 1 GB).
- **Pictures with any model:** a model that can't see (Granite, Qwen...) still gets your picture. HyperFlux reads its text with the OCR built into Windows (offline, nothing to install; small text is enlarged and read again) and passes it on as notes, so screenshots, coordinates, receipts and error messages work out of the box. For questions about what is *in* a picture, such as the background, colours or objects, turn on the **image helper** in **Settings → Voice & pictures**: a second, small server (Gemma 4 E2B, up to about 4.4 GB one-time download, less if you already have the Gemma 4 E2B model) that runs on the CPU, looks at the picture with your question in mind, and tells the main model what it sees. On a PC with integrated graphics you can run its picture reader there instead (**Run the helper on**); the processor is the default and recommended, because integrated graphics usually draws the desktop too, so Windows and other apps can lag while it works. It starts only when a picture needs it, sleeps after 10 idle minutes, and is refused on PCs with less than 8 GB of RAM. While it is on, **both servers show in the top bar**. Text questions go straight to OCR and scene questions straight to the helper; if neither can answer, HyperFlux says so right away instead of making you wait.
- **Videos (experimental):** attach a video with the paperclip (up to 300 MB) and ask about it. HyperFlux takes still frames spread through it (2 for a clip of up to 3 seconds, 4 up to a minute, 6 for longer ones) with the video decoder built into Windows, so there is nothing extra to install; H.264 MP4, which phones record, works. A model that can see (Gemma 4 with image input) looks at the frames directly; other models get each frame's text and, with the image helper, a description. It sees only those moments, **not the movement between them, and it cannot hear the sound**, and it is told to say so. It is slow on a modest PC: 3 frames took about a minute with Gemma 4 E4B on a 4 GB graphics card. Desktop app only; the video itself is never saved, only the frames.
- **Knows its own app:** ask what HyperFlux can do, or how to use a feature, and the model answers from a short built-in guide that matches the current setup (whether it can see pictures, whether the image helper is on, desktop app or browser). The guide is added only for questions about the app, so other chats keep their context and speed.
- **Read aloud:** a **Read aloud** button under every answer speaks it with the Windows voices; the voice is chosen (and can be tried) in **Settings → Voice & pictures**.
- **Custom instructions:** tell HyperFlux about yourself once (**Settings → Personal**, up to 1,500 characters), and it is sent with every message.
- **Personas:** Default, Tutor, Coder, Concise or Friendly change the tone (**Settings → Personal** or `/persona tutor`).
- **Chats:** every chat is saved on this PC. The box above **Recent Chats** searches titles and message text, and the download icon on a chat (or `/export`) saves it as a Markdown file.
- **Answers:** Copy and Retry on every answer, Edit on your last message, Stop while it writes. Long answers continue automatically instead of being cut off.
- **Formatting:** LaTeX maths, tables and code blocks with Copy buttons.
- **Web search:** HyperFlux decides when a question needs current or specific facts (prices, versions, news, game or product details) and skips searching for maths, coding and chat. It writes short keyword queries and splits multi-part questions into separate searches run at the same time. It opens and reads the top pages, keeps only the paragraphs that answer the question, and answers from them with numbered citations and a **Sources** list. If the sources don't answer the question, it searches once more with new words, then stops. Results are cached for 10 minutes, and the status line shows what is being searched. `/search <question>` always searches.
- **Files:** attach a text or code file for review (the first 3,000 characters are read).
- **Commands:** type `/` to see them: `/help`, `/search`, `/read`, `/persona`, `/export`, `/sys`, `/temp`, `/length`.
- **Settings:** one window with a section for each area: **Personal** (your name, custom instructions, persona), **Model** (creativity, answer length, conversation memory, with plain explanations and a reset), **Appearance** (six colour themes in Dark, Light or Match system, accent colour, text size), **Voice & pictures** and **About**. One **Save** button saves everything; deleting a chat, or all chats, asks first.
- **Look and layout:** a **Modern** (flat, calm) or **Legacy** (glass and particles) interface style; chats grouped by Today / Yesterday / Previous 7 days / Older with the open one highlighted; a hideable sidebar and **Ctrl+K** for chat search; a quiet home page with four quick starts; answers in one centred reading column; theme-coloured scrollbars. New chats name themselves from their first answer.
- **Other models:** HyperFlux is written for Gemma 4, but any GGUF the model picker lists will run. Thinking adapts to the loaded model: Gemma 4 keeps its built-in thinking; other models are asked to think (or not to) in plain words, and Qwen and GLM also get their own `/no_think` switch. Thinking tags and leaked chat tokens from Qwen, GLM, DeepSeek R1, Llama and others are cleaned up, and the picker says when the loaded model isn't Gemma 4. A model is only treated as non-Gemma when its name clearly says so, so a renamed Gemma file (like `model-e4b.gguf`) keeps working as before.
- **Fewer repeats in search answers:** repeated facts are removed from the web pages before the model reads them, the model is told to say each fact once, and repeated sentences and closing recaps are merged out of the answer with every citation kept.
- **Faster on small graphics cards:** on a 4 GB NVIDIA card the desktop app keeps the picture reader (the model's vision file) on the processor, which leaves much more of the model on the graphics card. In one test run per setup on a GTX 1050 with Gemma 4 E4B, 22 layers fitted instead of 7, writing rose from 4.7 to 5.5 tokens a second and reading the prompt almost doubled, while each picture took about 5 seconds longer. **Settings → Model → Pictures or chat speed** switches between Automatic, Faster chat and Faster pictures. The server is also started with your **Conversation memory** size once you save it. **GPU layers → More speed** (off by default) goes further on the one setup it was measured on, the recommended Unsloth E4B on a 4 GB NVIDIA card with 8K conversation memory or less: 36 layers instead of 22 wrote about 44% faster, using 3.4 of 4 GB; if the server stops, HyperFlux returns to Automatic. Changing any of these reloads the model. A model that sees pictures itself never loads the image helper.
- **Model picker:** switch between the GGUF models on this PC without restarting. The recommended Unsloth dynamic Gemma 4 E4B is recognised and runs at temperature 0.5 (Settings shows it, and moving the slider overrides it).
- **Updates:** the installed app checks GitHub at startup and every 6 hours. When a new release is out, a popup shows its patch notes and the files that changed since your version, and asks before installing. **Later** keeps an **Update available** card in the sidebar, even after a restart, until you update or skip that version. Every installer is checked against its SHA-256 before it runs.

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
                           image_helper.py runs the optional second (picture-reading) server
                           ocr.py reads picture text with Windows OCR (PowerShell)
                           video.py takes still frames from a video with Windows' decoder
  web/                     HyperFlux Web.html and logo_hyperflux/ images
  data/                    hf_brain.json (local canned answers)
  scripts/                 setup_assets.ps1, Run_HyperFlux_Terminal.bat, Start_HyperFlux_Server.bat,
                           Publish_Update.bat (tags a release for GitHub to build)
  tools/                   dataset_builder.py (regenerates data/hf_brain.json)
  packaging/               PyInstaller spec, icon builder, Inno Setup installer, release notes
                           (release-notes/versions/v<version>.md: each version's patch notes)
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

## System requirements

These are practical guidelines, not tested limits.

| | Minimum | Recommended |
| :--- | :--- | :--- |
| System | Windows 10 or 11, 64-bit | Windows 11, 64-bit |
| RAM | 8 GB (use Gemma 4 E2B) | 16 GB (for Gemma 4 E4B or the image helper) |
| Graphics | Not required, but replies will be slower | NVIDIA GPU with 4 GB of VRAM or more |

**Speed optimisations** are mainly for NVIDIA GPUs with 4 GB of VRAM, such as 4 GB GTX 10 Series cards or others. What counts is the amount of VRAM, not the series: a GTX 10 Series card with 6 GB or 8 GB doesn't get them automatically. **More speed** also needs the recommended Gemma 4 E4B and a conversation memory of 8,192 or less. They have been tested only on a GTX 1050 4 GB with an i7-8750H and 8 GB of RAM, so results on other PCs may differ.

For download sizes and free space, see [Download and disk-space estimate](#download-and-disk-space-estimate).

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
- **Image input** uses a vision projector file (`mmproj-gemma-4-E2B-it-BF16.gguf` or `mmproj-gemma-4-E4B-it-BF16.gguf`, about 1 GB) saved to `%LOCALAPPDATA%\HyperFlux\models`. It is pinned to the same Hugging Face commits as the models and checked against a fixed SHA-256. When it is present, the desktop app starts KoboldCpp with `--mmproj`. Pictures (or the cropped part) are reduced to at most 1,536 pixels on their longest side before they are sent and saved. Each request sends one picture: the one attached now, or else the latest one in the chat; older pictures are only mentioned, to save context. If chat storage fills up, the oldest pictures are removed first and the text is kept. Answers about pictures are slower, especially on GPUs with 4 GB or less.
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
is pre-selected, and Gemma 4 E4B in Unsloth's dynamic Q4_K_XL quantisation (5.1 GB,
the best quality here but slower, best with 16 GB) is an optional choice. When HyperFlux
runs that exact file it answers with temperature 0.5 instead of 0.7, unless you have
picked your own temperature. Setup shows the PC's RAM as a hint but
never chooses for the user. Each file is pinned to one Hugging Face commit
(`lmstudio-community/gemma-4-E2B-it-GGUF` / `unsloth/gemma-4-E4B-it-GGUF`) and checked
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

Installed copies of HyperFlux only ever update to a **published** GitHub release.
Commits and drafts are never offered, so unfinished work doesn't reach anyone. The
installed app is compiled, so it can't take changed files one by one: each
update is a complete, verified installer.

1. Write the patch notes for the version in
   `src\packaging\release-notes\versions\v<version>.md`, for example `v1.1.0.md`.
   The update popup shows them, so write them for users. When the change is
   important, also update the **Features** list above and the "New in this update"
   notes on the home page (`releaseNotes` in `src\web\HyperFlux Web.html`).
2. Commit everything, then run `src\scripts\Publish_Update.bat`. It asks for the
   new version, checks the patch notes exist, runs the tests, sets
   `__version__`, commits, tags `v<version>` and pushes.
3. GitHub Actions builds and smoke-tests the installer (about 10 minutes) and
   creates a **draft** release with the installer, its SHA-256 and the release
   notes. It refuses to build if the tag and `version.py` differ or the version
   has no patch notes.
4. Open the draft on GitHub, check it, and click **Publish**. Installed copies
   offer the update within about 6 hours, or at their next start.

Publish only after the packaged smoke test, measured installer size, release notes
and legal notice checks have passed. The installer also stays attached to the
workflow run as an artifact for 30 days.

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
