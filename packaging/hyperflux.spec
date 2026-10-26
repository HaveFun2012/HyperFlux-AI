# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

root = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(root / "hyperflux_desktop.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "HyperFlux Web.html"), "."),
        (str(root / "logo_hyperflux"), "logo_hyperflux"),
        (str(root / "hf_brain.json"), "."),
        (str(root / "LICENSES.md"), "."),
    ],
    hiddenimports=[
        "hyperflux_setup",
        "hyperflux_interacter",
        "hyperflux_server",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest"],
    noarchive=False,
)
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
