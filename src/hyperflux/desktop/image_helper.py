"""Image helper: a second, small KoboldCpp server (Gemma 4 E2B plus its vision file) that
looks at pictures for a main model that cannot, such as Granite or Qwen.

It runs on the CPU so the main model keeps the graphics card, and it starts only when a
picture needs it and goes back to sleep after a few idle minutes, because this PC class
(8 GB of RAM) cannot keep two models in memory all the time.

The search bridge calls these methods from its own thread; the processes themselves are
started and stopped on the window's thread through the signals.
"""

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import requests
from PySide6.QtCore import QObject, Signal

from hyperflux.desktop import runtime_assets as assets

HELPER_PORT = 5003
IDLE_SECONDS = 10 * 60
NEEDED_GB = 4.5      # the E2B model + its vision file + working memory
MIN_TOTAL_GB = 7      # an "8 GB" PC reports about 7.9 GB (some is reserved by the hardware)
SETTINGS_FILE = assets.APP_DATA / "image_helper.json"
RUNNERS = ("cpu", "igpu")  # the processor, or the graphics built into it


def memory_gb():
    """(total, available) memory in GB; (None, None) if Windows doesn't say."""
    try:
        import ctypes

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                        ("available_extended", ctypes.c_ulonglong)]

        status = _MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, None
        return status.total / 1024 ** 3, status.available / 1024 ** 3
    except (AttributeError, OSError):
        return None, None


def hardware_verdict(total_gb, available_gb, needed_gb=NEEDED_GB):
    """Can this PC run the helper next to the main model? -> {ok, note}."""
    if total_gb is None:
        return {"ok": True, "note": "Could not read this PC's memory, so it can't be checked first."}
    if total_gb < MIN_TOTAL_GB:
        return {"ok": False, "note": f"This PC has {total_gb:.1f} GB of RAM; the image helper needs a PC with 8 GB or more."}
    if available_gb is not None and available_gb < needed_gb - 1.5:
        return {"ok": True, "note": f"Only {available_gb:.1f} GB of RAM is free right now. It will run, but "
                                    "slowly. Closing other programs helps."}
    return {"ok": True, "note": "This PC has enough memory. The helper runs on the CPU and only while it is used."}


def find_helper_model(extra_folder=None):
    """The Gemma 4 E2B model file on this PC (downloaded by HyperFlux or kept by the user), else None."""
    pinned = assets.model_download_path("e2b")
    # extra_folder: where the main model is. The general search only covers the usual folders and
    # whichever one HyperFlux was started from, so a helper kept beside the model could be missed.
    beside = sorted(extra_folder.glob("*.gguf")) if extra_folder and extra_folder.is_dir() else []
    candidates = [pinned] + [p for p in beside if not assets.is_vision_file(p)] + list(assets.find_gguf_models())
    for path in candidates:
        try:
            if path.is_file() and assets.model_family(path) == "e2b" and assets.is_gguf(path):
                return path
        except OSError:
            continue
    return None


def parse_integrated_gpu(summary):
    """(Vulkan device number, name) of the integrated GPU in `vulkaninfo --summary`, else None."""
    for block in re.split(r"^GPU(?=\d+:)", summary, flags=re.MULTILINE)[1:]:
        number = re.match(r"(\d+):", block)
        name = re.search(r"deviceName\s*=\s*(.+)", block)
        if number and name and "PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU" in block:
            return int(number.group(1)), name.group(1).strip()
    return None


def find_integrated_gpu():
    tool = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "vulkaninfo.exe")
    try:
        output = subprocess.run([tool, "--summary"], capture_output=True, text=True, timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return parse_integrated_gpu(output)


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        runner = data.get("runner")
        return {"enabled": bool(data.get("enabled")), "runner": runner if runner in RUNNERS else "cpu"}
    except (OSError, ValueError, AttributeError):
        return {"enabled": False, "runner": "cpu"}


def save_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings), encoding="utf-8")


class ImageHelper(QObject):
    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self, main_model_is_vision, parent=None, port=HELPER_PORT, main_model=lambda: None):
        super().__init__(parent)
        self._main_model = main_model  # callable: the main model's path, to look beside it
        self._main_model_is_vision = main_model_is_vision  # callable: the main model can see pictures itself
        self.port = port
        self._lock = threading.Lock()
        settings = load_settings()
        self._enabled = settings["enabled"]
        self._runner = settings["runner"]
        self._integrated = None  # (device number, name), looked up once
        self._looked_for_gpu = False
        self._running = False   # the process is up (set by the window)
        self._starting = False  # asked to start, not answering yet
        self._last_used = time.monotonic()
        self._state = {"downloading": False, "progress": 0, "message": "", "error": ""}

    def find_model(self):
        main = self._main_model()
        return find_helper_model(Path(main).parent if main else None)

    def integrated_gpu(self):
        if not self._looked_for_gpu:
            self._integrated, self._looked_for_gpu = find_integrated_gpu(), True
        return self._integrated

    def runner(self):
        """'igpu' only while the PC really has an integrated GPU."""
        return "igpu" if self._runner == "igpu" and self.integrated_gpu() else "cpu"

    def set_runner(self, runner):
        if runner not in RUNNERS or (runner == "igpu" and not self.integrated_gpu()):
            return False, "This PC has no integrated graphics the helper can use."
        with self._lock:
            changed = runner != self._runner
            self._runner = runner
            self._state["error"] = ""
        if changed:
            self._remember()
            self.stop_requested.emit()  # the next picture starts it on the new one
        return True, "Saved."

    def process_exited(self):
        """The window saw the server stop by itself."""
        with self._lock:
            failed_to_load = self._starting
        if failed_to_load:
            advice = " Choose the processor (CPU) instead." if self.runner() == "igpu" else " See kobold-helper.log."
            self.finish_with_error("The image helper stopped while loading." + advice)
        self.set_running(False)

    # ----- status -----------------------------------------------------------------------

    def _answering(self):
        try:
            return requests.get(f"http://127.0.0.1:{self.port}/api/v1/model", timeout=0.4).ok
        except requests.RequestException:
            return False

    def describe(self):
        total, available = memory_gb()
        model, vision = self.find_model(), assets.VISION_FILES["e2b"]
        vision_ready = self._vision_file(model) is not None
        with self._lock:
            enabled, running, starting, state = self._enabled, self._running, self._starting, dict(self._state)
        answering = running and self._answering()
        if answering:
            with self._lock:
                self._starting = starting = False
        if state["error"]:
            status = "error"
        elif state["downloading"]:
            status = "downloading"
        elif answering:
            status = "ready"
        elif running or starting:
            status = "starting"
        else:
            status = "sleeping" if enabled else "off"
        needs_files = model is None or not vision_ready
        missing = (0 if model else assets.GEMMA_MODELS["e2b"]["size"]) + (0 if vision_ready else vision["size"])
        size_mb = round(missing / 1e6)
        return {
            "enabled": enabled,
            "status": status,
            "port": self.port,
            "runner": self.runner(),
            "integrated_gpu": (self.integrated_gpu() or (None, None))[1],
            "name": "Gemma 4 E2B",
            "needs_download": needs_files,
            "download_mb": size_mb,
            "hardware": {**hardware_verdict(total, available, self._needed_gb(model)),
                         "total_gb": None if total is None else round(total, 1),
                         "free_gb": None if available is None else round(available, 1)},
            "main_model_sees_pictures": bool(self._main_model_is_vision()),
            "idle_minutes": IDLE_SECONDS // 60,
            **state,
        }

    # ----- actions (from the page, via the bridge) ----------------------------------------

    @staticmethod
    def _needed_gb(model):
        """Memory the helper needs: the E2B file you have (a smaller quantisation needs less),
        its vision file, and about 0.6 GB of working memory."""
        try:
            return (model.stat().st_size + assets.VISION_FILES["e2b"]["size"]) / 1024 ** 3 + 0.6
        except (AttributeError, OSError):
            return NEEDED_GB

    def request_enable(self):
        """Turn the feature on. Downloads what is missing, then starts the server. -> (accepted, message)"""
        total, available = memory_gb()
        verdict = hardware_verdict(total, available, self._needed_gb(self.find_model()))
        if not verdict["ok"]:
            return False, verdict["note"]
        with self._lock:
            if self._state["downloading"]:
                return True, "Already downloading."
            self._enabled = True
            self._state = {"downloading": False, "progress": 0, "message": "", "error": ""}
        self._remember()
        model = self.find_model()
        if model is None or self._vision_file(model) is None:
            with self._lock:
                self._state = {"downloading": True, "progress": 0, "error": "", "message": "Starting the download..."}
            threading.Thread(target=self._download, name="HyperFluxHelperDownload", daemon=True).start()
            return True, "Downloading the image helper."
        if self._main_model_is_vision():
            return True, "On. The loaded model sees pictures itself, so the helper stays asleep."
        self.wake()
        return True, "Starting the image helper."

    def request_disable(self):
        with self._lock:
            self._enabled = False
            self._starting = False
            self._state = {"downloading": self._state["downloading"], "progress": 0, "message": "", "error": ""}
        self._remember()
        self.stop_requested.emit()
        return True, "The image helper is off."

    def wake(self):
        """Start the server if it is asleep (a picture needs it). -> True when it is starting or up."""
        with self._lock:
            if not self._enabled or self._state["downloading"]:
                return False
            self._last_used = time.monotonic()
            if self._running or self._starting:
                return True
            self._starting = True
        self.start_requested.emit()
        return True

    def touch(self):
        with self._lock:
            self._last_used = time.monotonic()

    # ----- window side ------------------------------------------------------------------------

    def start_arguments(self):
        """KoboldCpp arguments for the helper, or None when its files are missing."""
        model = self.find_model()
        vision = self._vision_file(model)
        if model is None or vision is None:
            return None
        if self.runner() == "igpu":
            # Only the picture reader goes to the integrated GPU: putting the whole model there
            # failed to load on the PC this was tested on (Intel UHD 630).
            device = ["--usevulkan", str(self.integrated_gpu()[0]), "--gpulayers", "0"]
        else:
            device = ["--usecpu"]
        return ["--model", str(model), "--mmproj", str(vision),
                "--port", str(self.port), "--skiplaunch", "--contextsize", "4096"] + device

    def set_running(self, running):
        with self._lock:
            self._running = running
            if not running:
                self._starting = False

    def sleep_if_idle(self):
        """Called every minute by the window: stop the server once nobody has used it for a while."""
        with self._lock:
            idle = self._running and time.monotonic() - self._last_used > IDLE_SECONDS
        if idle:
            self.stop_requested.emit()
        return idle

    def finish_with_error(self, message):
        with self._lock:
            self._state = {"downloading": False, "progress": 0, "message": "", "error": message}
            self._starting = False

    def clear_error(self):
        with self._lock:
            self._state["error"] = ""

    # ----- internals ---------------------------------------------------------------------------

    def _remember(self):
        try:
            save_settings({"enabled": self._enabled, "runner": self._runner})
        except OSError:
            pass  # the choice just won't survive a restart

    @staticmethod
    def _vision_file(model):
        """The helper's vision file: HyperFlux's own download, or one kept next to the model
        (the same two places the main model's image input looks)."""
        return assets.vision_file_for(model) if model else None

    def _download(self):
        try:
            if self.find_model() is None:
                assets.download_gemma_model(
                    lambda percent: self._set(progress=round(percent * 0.78)),  # the model is ~78% of the bytes
                    lambda message: self._set(message=message), lambda: False, "e2b")
            if self._vision_file(self.find_model()) is None:
                assets.download_vision_file(
                    self.find_model(),
                    lambda percent: self._set(progress=78 + round(percent * 0.22)),
                    lambda message: self._set(message=message), lambda: False)
        except (OSError, ValueError) as error:
            self.finish_with_error(str(error))
            return
        self._set(downloading=False, progress=100, message="")
        if not self._main_model_is_vision():
            self.wake()
