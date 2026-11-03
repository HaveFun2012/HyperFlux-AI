# HyperFlux <version>

HyperFlux includes the Gemma4 Flash 1 interface and the Gen1 Gemma4 terminal
interface. This release is a Windows desktop installer; model weights are not
bundled, but setup can download the recommended model for you.

## Highlights

- Shared Gemma4 Flash 1 desktop interface and Gen1 Gemma4 terminal fallback.
- First-run setup reuses a local GGUF model and can download KoboldCpp from its official release.
- Desktop settings and chat history remain in the per-user local application data folder.

## Installation

Download `HyperFlux-Setup.exe` from the release page. During first-run setup,
select an existing GGUF model, or let setup download the recommended
Gemma 4 E2B Q4_K_M (3.4 GB, Apache 2.0, SHA-256 verified).

## Requirements and downloads

- Windows 10/11, x64
- Installer size: measured by the release workflow
- Model: your own GGUF, or the optional Gemma 4 E2B Q4_K_M download (3.4 GB); not bundled.
- KoboldCpp: downloaded from its official release only when needed

## Known issues

- Model inference must be validated on the target hardware and selected KoboldCpp/model combination.

## Notices

See `LICENSES.md` and the release's included third-party notices. Model terms
apply to the user-provided weights.
