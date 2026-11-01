# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve().parent  # src/
sys.path.insert(0, str(root))

a = Analysis(
    [str(root / "hyperflux" / "desktop" / "__main__.py")],
    pathex=[str(root)],
    binaries=[],
    # Keep the same web/ and data/ layout as src/ so hyperflux.paths works in both.
    datas=[
        (str(root / "web"), "web"),
        (str(root / "data"), "data"),
        (str(root.parent / "LICENSES.md"), "."),
    ],
    # Some modules are imported lazily inside functions.
    hiddenimports=collect_submodules("hyperflux"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest"],
    noarchive=False,
)

# The interface uses Qt WebEngine Widgets, not Qt Quick. The automatic Qt hooks
# collect optional Qt Quick tooling and generated build artifacts that are not
# used by this app and can exceed Windows installer path limits.
def is_qt_quick_data(entry):
    target = entry[0].replace("\\", "/").casefold()
    return target.startswith("pyside6/qml/")


a.datas = [entry for entry in a.datas if not is_qt_quick_data(entry)]
a.binaries = [entry for entry in a.binaries if not is_qt_quick_data(entry)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HyperFlux",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "packaging" / "hyperflux.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="HyperFlux",
)
