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

## Optional runtime assets

- **KoboldCpp:** the installer is designed to download the official Windows
  release when no compatible user-selected copy exists. Review the exact
  version's license and redistribution/source-notice requirements. Do not
  bundle its binary until that review is complete.
- **Gemma 4 E2B Q4_K_M GGUF:** the local model file is user-provided and is
  not included in the installer or source repository. Confirm its exact
  hosting/conversion source and review the applicable Gemma and host terms
  before use or redistribution.

## Release checklist

- Record the exact dependency versions and source URLs used for each build.
- Ship the required license texts, attribution, notices, and any source offer.
- Keep API tokens, local histories, settings, and user files out of release artifacts.
- Confirm legal review before distributing third-party binaries or model weights.
