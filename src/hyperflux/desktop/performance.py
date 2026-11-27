"""How HyperFlux starts the model server so it runs as fast as the PC allows.

Measured on a 4 GB GTX 1050 with Gemma 4 E4B (one run per setup, 2026-11-27): with the
vision file on the graphics card only 7 of 43 model layers fitted there; with it on the
CPU, 22 did. Writing went from 4.7 to 5.5 words-pieces a second (6.4 with an 8K context),
reading the prompt almost doubled, and each picture took about 5 s longer. So on a small
card the vision file belongs on the CPU unless the user mostly sends pictures.

Kept free of Qt so it can be tested without a GUI.
"""

import json
import os
import subprocess

from hyperflux.desktop import runtime_assets as assets

SETTINGS_FILE = assets.APP_DATA / "performance.json"
MODES = ("auto", "chat", "pictures")
SMALL_GPU_MB = 4200  # "4 GB" cards report 4096
MIN_CONTEXT, MAX_CONTEXT = 4096, 131072


def load_settings():
    """{'pictures': 'auto'|'chat'|'pictures', 'context': int or None (the server's own default)}."""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return clean_settings(data.get("pictures"), data.get("context"))
    except (OSError, ValueError, AttributeError):
        return {"pictures": "auto", "context": None}


def clean_settings(pictures, context):
    pictures = pictures if pictures in MODES else "auto"
    if isinstance(context, bool) or not isinstance(context, int) or not MIN_CONTEXT <= context <= MAX_CONTEXT:
        context = None
    return {"pictures": pictures, "context": context}


def save_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings), encoding="utf-8")


def gpu_memory_mb():
    """The biggest NVIDIA card's memory in MB, or None (no NVIDIA card, or it can't be asked)."""
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            cwd=os.environ.get("SystemRoot"),  # never pick up a program from the working folder
        ).stdout
        return max(int(line) for line in output.split() if line.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def vision_on_cpu(mode, vram_mb):
    """Should the vision file stay off the graphics card?"""
    if mode == "chat":
        return True
    if mode == "pictures":
        return False
    # Unknown cards are left as KoboldCpp would run them: only small NVIDIA cards were measured.
    return vram_mb is not None and vram_mb <= SMALL_GPU_MB


def launch_arguments(settings, has_vision, vram_mb):
    """The extra KoboldCpp arguments for these settings."""
    arguments = []
    if has_vision and vision_on_cpu(settings["pictures"], vram_mb):
        arguments.append("--mmprojcpu")
    if settings["context"]:
        arguments += ["--contextsize", str(settings["context"])]
    return arguments


SERVER_DEFAULT_CONTEXT = 16384  # what KoboldCpp loads when --contextsize isn't given


class Performance:
    """The speed settings as the page sees them. The bridge calls it from its own thread, so
    `restart` must be safe to call from there (the window passes a Qt signal's emit)."""

    def __init__(self, has_vision, can_restart, restart, vram=gpu_memory_mb):
        self._has_vision = has_vision    # callable: the loaded model is started with a vision file
        self._can_restart = can_restart  # callable: False when HyperFlux didn't start the server
        self._restart = restart
        self._read_vram = vram
        self._vram = None
        self._asked_vram = False

    def vram_mb(self):
        if not self._asked_vram:
            self._vram, self._asked_vram = self._read_vram(), True
        return self._vram

    def launch_arguments(self):
        return self._arguments(load_settings())

    def _arguments(self, settings):
        if settings["context"] == SERVER_DEFAULT_CONTEXT:
            settings = {**settings, "context": None}
        return launch_arguments(settings, self._has_vision(), self.vram_mb())

    def describe(self):
        settings = load_settings()
        has_vision = bool(self._has_vision())
        return {
            "pictures": settings["pictures"],
            "context": settings["context"] or SERVER_DEFAULT_CONTEXT,
            "has_vision": has_vision,
            "vision_on_cpu": has_vision and vision_on_cpu(settings["pictures"], self.vram_mb()),
            "gpu_memory_mb": self.vram_mb(),
            "can_restart": bool(self._can_restart()),
        }

    def update(self, pictures, context):
        """Save the settings; reload the model only if it would now start differently."""
        before = self._arguments(load_settings())
        settings = clean_settings(pictures, context)
        save_settings(settings)
        changed = self._arguments(settings) != before
        restarting = changed and bool(self._can_restart())
        if restarting:
            self._restart()
        return {"restarting": restarting, "changed": changed}
