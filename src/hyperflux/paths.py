"""File locations used across HyperFlux, for both source runs and packaged builds."""

import os
import sys
from pathlib import Path

# The `src` folder in a source checkout, or the unpacked bundle in a PyInstaller build.
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))

WEB_DIR = RESOURCE_ROOT / "web"
WEB_INTERFACE = WEB_DIR / "HyperFlux Web.html"
DESKTOP_LOGO = WEB_DIR / "logo_hyperflux" / "hyperfluxdesktop.png"
DATA_DIR = RESOURCE_ROOT / "data"
BRAIN_PATH = DATA_DIR / "hf_brain.json"

SCRIPTS_DIR = RESOURCE_ROOT / "scripts"
SERVER_LAUNCHER = SCRIPTS_DIR / "Start_HyperFlux_Server.bat"


def documents_directory():
    """The user's real Documents folder (OneDrive can move it away from ~/Documents)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            folder_id = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                             (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            found = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None,
                                                          ctypes.byref(found)) == 0:
                try:
                    return Path(found.value)
                finally:
                    ctypes.windll.ole32.CoTaskMemFree(found)
        except (AttributeError, OSError, TypeError):
            pass
    return Path.home() / "Documents"


def user_data_directory():
    """Per-user folder for settings, logs, and downloaded assets."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "HyperFlux"


KOBOLD_LOG_PATH = user_data_directory() / "logs" / "kobold.log"
# Secret that the desktop page must send to read KoboldCpp logs from the search bridge.
BRIDGE_TOKEN_PATH = user_data_directory() / "bridge_token"
# The terminal app's persona and custom instructions (the desktop app keeps its own).
TERMINAL_SETTINGS_PATH = user_data_directory() / "terminal_settings.json"
# Chats saved with /export in the terminal app.
EXPORT_DIR = documents_directory() / "HyperFlux exports"
