# HyperFlux <version>

HyperFlux includes the Gemma3 Flash 1 interface and the Gen1 Gemma3 terminal
interface. This release is a Windows desktop installer; model weights are not
bundled.

## Highlights

- Shared Gemma3 Flash 1 desktop interface and Gen1 Gemma3 terminal fallback.
- First-run setup can reuse local GGUF/KoboldCpp assets or download selected official assets.
- Desktop settings and chat history remain in the per-user local application data folder.

## Installation

Download `HyperFlux-Setup.exe` from the release page. During first-run setup,
select an existing GGUF or explicitly choose a supported model download.

## Requirements and downloads

- Windows 10/11, x64
- Installer size: measured by the release workflow
- Model download: only if selected; size and SHA-256 are shown/verified by setup
- KoboldCpp: downloaded from its official release only when needed

## Known issues

- Model inference must be validated on the target hardware and selected KoboldCpp/model combination.

## Notices

See `LICENSES.md` and the release's included third-party notices. Model terms
apply to downloaded weights.
