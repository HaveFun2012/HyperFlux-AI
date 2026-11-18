"""Write src/dist/RELEASE-NOTES.md (and the installer's .sha256) for a release.

The notes start with "## What's new" from versions/<tag>.md, the patch notes for this
version. The in-app updater shows exactly that section when it offers the update, so
write it for users. The rest comes from TEMPLATE.md.
"""

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]  # src/
TEMPLATE = Path(__file__).with_name("TEMPLATE.md")
VERSIONS = Path(__file__).with_name("versions")
INSTALLER = ROOT / "dist" / "HyperFlux-Setup.exe"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def whats_new(version):
    """This version's patch notes, or None if versions/<version>.md doesn't exist."""
    tag = version if version.startswith("v") else f"v{version}"
    path = VERSIONS / f"{tag}.md"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def build_notes(version):
    notes = TEMPLATE.read_text(encoding="utf-8").replace("<version>", version)
    new = whats_new(version)
    if new:
        title, _, rest = notes.partition("\n## ")
        notes = f"{title.rstrip()}\n\n## What's new\n\n{new}\n\n## {rest}"
    return notes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    notes = build_notes(args.version)
    if INSTALLER.is_file():
        installer_bytes = INSTALLER.stat().st_size
        checksum = sha256_file(INSTALLER)
        notes += (
            f"\n\n## Build measurements\n\n"
            f"- Installer size: {installer_bytes:,} bytes "
            f"({installer_bytes / 1024 / 1024:.1f} MiB)\n"
            f"- Installer SHA-256: `{checksum}`\n"
        )
        (ROOT / "dist" / "HyperFlux-Setup.exe.sha256").write_text(
            f"{checksum}  HyperFlux-Setup.exe\n", encoding="ascii"
        )
    (ROOT / "dist" / "RELEASE-NOTES.md").write_text(notes, encoding="utf-8")


if __name__ == "__main__":
    main()
