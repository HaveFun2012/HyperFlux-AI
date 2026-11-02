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


def user_data_directory():
    """Per-user folder for settings, logs, and downloaded assets."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "HyperFlux"


KOBOLD_LOG_PATH = user_data_directory() / "logs" / "kobold.log"
# Secret that the desktop page must send to read KoboldCpp logs from the search bridge.
BRIDGE_TOKEN_PATH = user_data_directory() / "bridge_token"
