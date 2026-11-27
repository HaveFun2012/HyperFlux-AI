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
LAYER_MODES = ("auto", "speed")
# "More speed" forces this many layers onto the card, but only in the one setup it was measured in
# (about 44% faster writing than the 22 layers autofit chose, using 3.4 of 4 GB): the recommended
# Unsloth E4B, a 4 GB NVIDIA card, the vision file off the card and a context of 8K or less.
SPEED_LAYERS = 36
SPEED_MAX_CONTEXT = 8192
SPEED_MIN_GPU_MB = 3900
SMALL_GPU_MB = 4200  # "4 GB" cards report 4096
MIN_CONTEXT, MAX_CONTEXT = 4096, 131072


def load_settings():
    """{'pictures': 'auto'|'chat'|'pictures', 'context': int or None (the server's own default),
    'layers': 'auto'|'speed'}."""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return clean_settings(data.get("pictures"), data.get("context"), data.get("layers"))
    except (OSError, ValueError, AttributeError):
        return {"pictures": "auto", "context": None, "layers": "auto"}


def clean_settings(pictures, context, layers="auto"):
    pictures = pictures if pictures in MODES else "auto"
    layers = layers if layers in LAYER_MODES else "auto"
    if isinstance(context, bool) or not isinstance(context, int) or not MIN_CONTEXT <= context <= MAX_CONTEXT:
        context = None
    return {"pictures": pictures, "context": context, "layers": layers}


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


def speed_blocker(settings, has_vision, vram_mb, tuned_model):
    """Why "More speed" can't be used right now ('' when it can)."""
    if not tuned_model:
        return "it was only tested with the recommended Unsloth Gemma 4 E4B"
    if vram_mb is None or not SPEED_MIN_GPU_MB <= vram_mb <= SMALL_GPU_MB:
        return "it was only tested on a 4 GB NVIDIA graphics card"
    if has_vision and not vision_on_cpu(settings["pictures"], vram_mb):
        return "the picture reader has to be on the processor, so don't choose Faster pictures"
    if not settings["context"] or settings["context"] > SPEED_MAX_CONTEXT:
        return f"Conversation memory has to be {SPEED_MAX_CONTEXT:,} or less"
    return ""


def launch_arguments(settings, has_vision, vram_mb, tuned_model=False):
    """The extra KoboldCpp arguments for these settings."""
    arguments = []
    if has_vision and vision_on_cpu(settings["pictures"], vram_mb):
        arguments.append("--mmprojcpu")
    if settings["context"]:
        arguments += ["--contextsize", str(settings["context"])]
    if settings.get("layers") == "speed" and not speed_blocker(settings, has_vision, vram_mb, tuned_model):
        arguments += ["--gpulayers", str(SPEED_LAYERS)]
    return arguments


SERVER_DEFAULT_CONTEXT = 16384  # what KoboldCpp loads when --contextsize isn't given


class Performance:
    """The speed settings as the page sees them. The bridge calls it from its own thread, so
    `restart` must be safe to call from there (the window passes a Qt signal's emit)."""

    def __init__(self, has_vision, can_restart, restart, vram=gpu_memory_mb, model=lambda: None):
        self._model = model              # callable: the loaded model's path
        self._forced_layers = False      # the running server was started with "More speed"
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

    def _tuned_model(self):
        """The one model "More speed" was measured with (it is also the one with its own temperature)."""
        path = self._model()
        return bool(path) and assets.recommended_temperature(path) is not None

    def launch_arguments(self):
        """For the server about to be started."""
        arguments = self._arguments(load_settings())
        self._forced_layers = "--gpulayers" in arguments
        return arguments

    def fall_back(self):
        """The server stopped by itself. If it had the extra layers, go back to Automatic.
        -> True when it did, so the window should start the server again."""
        if not self._forced_layers:
            return False
        self._forced_layers = False
        settings = {**load_settings(), "layers": "auto"}
        try:
            save_settings(settings)
        except OSError:
            return False  # it would only force the layers again
        return True

    def _arguments(self, settings):
        if settings["context"] == SERVER_DEFAULT_CONTEXT:
            settings = {**settings, "context": None}
        return launch_arguments(settings, self._has_vision(), self.vram_mb(), self._tuned_model())

    def describe(self):
        settings = load_settings()
        has_vision = bool(self._has_vision())
        return {
            "pictures": settings["pictures"],
            "layers": settings["layers"],
            "speed_blocker": speed_blocker(settings, has_vision, self.vram_mb(), self._tuned_model()),
            "context": settings["context"] or SERVER_DEFAULT_CONTEXT,
            "has_vision": has_vision,
            "vision_on_cpu": has_vision and vision_on_cpu(settings["pictures"], self.vram_mb()),
            "gpu_memory_mb": self.vram_mb(),
            "can_restart": bool(self._can_restart()),
        }

    def update(self, pictures, context, layers="auto"):
        """Save the settings; reload the model only if it would now start differently."""
        before = self._arguments(load_settings())
        settings = clean_settings(pictures, context, layers)
        save_settings(settings)
        changed = self._arguments(settings) != before
        restarting = changed and bool(self._can_restart())
        if restarting:
            self._restart()
        return {"restarting": restarting, "changed": changed}
