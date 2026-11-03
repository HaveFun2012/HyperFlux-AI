# HyperFlux <version>

HyperFlux is a private AI assistant that runs entirely on your own Windows PC,
using a GGUF model served locally by KoboldCpp. It has a desktop app and a
terminal app. This release is a Windows installer; model weights are not
bundled, but setup can download the recommended model for you.

## Highlights

- **Three models:** Flash 1 for quick answers (never thinks), Apex 1 for most
  tasks, and Horizon 1 for complex problems (always thinks deeply). All three run
  on your local model; they differ in thinking, answer length and instructions.
- **Visible thinking:** the reasoning streams live, then folds away when the
  answer starts. Apex 1 lets you turn it on or off with **Think**.
- **Clear answers:** answer first, mostly in prose, with no filler, and length
  that matches the question.
- **Maths, tables and code** render properly, including fractions and equations.
- **Claude-style controls:** Copy, Retry, Edit your last message, Stop
  generating, and Jump to latest.
- **Long answers aren't cut off:** replies that hit the length limit continue
  automatically.
- **Live web search** for current events, with sources.
- **Themes:** six colour themes, each in Dark, Light or Match system.
- **Easy setup:** choose your own GGUF model or download the recommended
  Gemma 4 E2B; KoboldCpp is downloaded from its official release when needed.
- **Automatic updates:** new versions are offered in the app and installed in
  one click, verified by SHA-256.
- Chats and settings stay on your PC, in the per-user application data folder.

## Installation

Download `HyperFlux-Setup.exe` from the release page and run it (no
administrator rights needed). During first-run setup, select an existing GGUF
model, or let setup download the recommended Gemma 4 E2B Q4_K_M (3.4 GB,
Apache 2.0, SHA-256 verified).

## Requirements and downloads

- Windows 10/11, x64
- Installer size: measured by the release workflow
- Model: your own GGUF, or the optional Gemma 4 E2B Q4_K_M download (3.4 GB); not bundled.
- KoboldCpp: downloaded from its official release only when needed
- About 4.5 GB of free disk space for the app, model and KoboldCpp

## Known issues

- On PCs with 8 GB of RAM, the first model load can take a few minutes, and
  Horizon 1 is slow. Use Flash 1 for quick questions.
- Windows SmartScreen may warn about an unrecognised app because the installer
  isn't code-signed. Choose **More info → Run anyway**.

## Notices

See `LICENSES.md` and the release's included third-party notices. Model terms
apply to the user-provided or downloaded weights.
