import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).with_name("TEMPLATE.md")
INSTALLER = ROOT / "dist" / "HyperFlux-Setup.exe"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    notes = TEMPLATE.read_text(encoding="utf-8").replace("<version>", args.version)
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
