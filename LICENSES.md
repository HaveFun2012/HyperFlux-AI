# Third-party notices and distribution review

This file is an inventory for release preparation, not legal advice or a
substitute for including the exact notices required by each redistributed
component. The release build must be blocked until the applicable source,
binary, and model terms have been reviewed and the required notices are
included with the installer.

## Application dependencies

| Component | Intended use | Review required |
| --- | --- | --- |
| Python | Runtime bundled in the application | Include the Python license and notices for bundled standard-library/runtime components. |
| PySide6 and Qt WebEngine | Desktop window and embedded Chromium-based web view | Confirm the selected Qt license, LGPL compliance obligations or other applicable terms, Qt/Chromium notices, and required relinking/source materials. |
| requests | HTTP client | Include its license and notices for transitive packages. |
| rich | Terminal fallback | Include its license and notices. |
| ddgs | Optional web-search provider | Include its license and notices for transitive packages. |
| PyInstaller | Build tool; output bootloader is distributed | Include the applicable bootloader license notice. |
| Inno Setup | Installer compiler | Confirm distribution terms for the generated installer and include required notices. |
| KaTeX 0.16.11 | Maths rendering in the web interface, bundled in `src/web/vendor/katex/` (MIT; from the npm registry, SHA-1 `4bc84d5584f996abece5f01c6ad11304276a33f5`) | MIT license text is included as `src/web/vendor/katex/LICENSE`; keep it with the bundled files. |

## Optional runtime assets

- **KoboldCpp:** the installer is designed to download the official Windows
  release when no compatible user-selected copy exists. Review the exact
  version's license and redistribution/source-notice requirements. Do not
  bundle its binary until that review is complete.
- **Gemma 4 E2B Q4_K_M GGUF:** not included in the installer or source
  repository. Setup can download it on the user's request, after showing the
  licence: `lmstudio-community/gemma-4-E2B-it-GGUF`, commit
  `eed445ccfb8aef2e279df1a97e133baf06e443b4`, file
  `gemma-4-E2B-it-Q4_K_M.gguf`, 3,427,880,384 bytes, SHA-256
  `71e6e8cb64a76da1a734fb8f6ba389d2784950d9902f5e87244fca0a15190c94`.
  Gemma 4 is released by Google under the Apache License 2.0
  (https://ai.google.dev/gemma/docs/gemma_4_license). HyperFlux does not
  redistribute the weights; users download them directly from Hugging Face.

## Release checklist

- Record the exact dependency versions and source URLs used for each build.
- Ship the required license texts, attribution, notices, and any source offer.
- Keep API tokens, local histories, settings, and user files out of release artifacts.
- Confirm legal review before distributing third-party binaries or model weights.
