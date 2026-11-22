"""Image helper: a second, small KoboldCpp server (Gemma 4 E2B plus its vision file) that
looks at pictures for a main model that cannot, such as Granite or Qwen.

It runs on the CPU so the main model keeps the graphics card, and it starts only when a
picture needs it and goes back to sleep after a few idle minutes, because this PC class
(8 GB of RAM) cannot keep two models in memory all the time.

The search bridge calls these methods from its own thread; the processes themselves are
started and stopped on the window's thread through the signals.
"""

import json
import threading
import time

import requests
from PySide6.QtCore import QObject, Signal

from hyperflux.desktop import runtime_assets as assets

HELPER_PORT = 5003
IDLE_SECONDS = 10 * 60
NEEDED_GB = 4.5      # the E2B model + its vision file + working memory
MIN_TOTAL_GB = 7      # an "8 GB" PC reports about 7.9 GB (some is reserved by the hardware)
SETTINGS_FILE = assets.APP_DATA / "image_helper.json"


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


def find_helper_model():
    """The Gemma 4 E2B model file on this PC (downloaded by HyperFlux or kept by the user), else None."""
    pinned = assets.model_download_path("e2b")
    candidates = [pinned] + list(assets.find_gguf_models())
    for path in candidates:
        try:
            if path.is_file() and assets.model_family(path) == "e2b" and assets.is_gguf(path):
                return path
        except OSError:
            continue
    return None


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {"enabled": bool(data.get("enabled"))}
    except (OSError, ValueError, AttributeError):
        return {"enabled": False}


def save_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings), encoding="utf-8")


class ImageHelper(QObject):
    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self, main_model_is_vision, parent=None, port=HELPER_PORT):
        super().__init__(parent)
        self._main_model_is_vision = main_model_is_vision  # callable: the main model can see pictures itself
        self.port = port
        self._lock = threading.Lock()
        self._enabled = load_settings()["enabled"]
        self._running = False   # the process is up (set by the window)
        self._starting = False  # asked to start, not answering yet
        self._last_used = time.monotonic()
        self._state = {"downloading": False, "progress": 0, "message": "", "error": ""}

    # ----- status -----------------------------------------------------------------------

    def _answering(self):
        try:
            return requests.get(f"http://127.0.0.1:{self.port}/api/v1/model", timeout=0.4).ok
        except requests.RequestException:
            return False

    def describe(self):
        total, available = memory_gb()
        model, vision = find_helper_model(), assets.VISION_FILES["e2b"]
        vision_ready = (assets.vision_download_path("e2b").is_file()
                        and assets.vision_download_path("e2b").stat().st_size == vision["size"]) if model else False
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
        verdict = hardware_verdict(total, available, self._needed_gb(find_helper_model()))
        if not verdict["ok"]:
            return False, verdict["note"]
        with self._lock:
            if self._state["downloading"]:
                return True, "Already downloading."
            self._enabled = True
            self._state = {"downloading": False, "progress": 0, "message": "", "error": ""}
        self._remember()
        model = find_helper_model()
        if model is None or not self._vision_ready():
            with self._lock:
                self._state = {"downloading": True, "progress": 0, "error": "", "message": "Starting the download..."}
            threading.Thread(target=self._download, name="HyperFluxHelperDownload", daemon=True).start()
            return True, "Downloading the image helper."
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
        model = find_helper_model()
        if model is None or not self._vision_ready():
            return None
        return ["--model", str(model), "--mmproj", str(assets.vision_download_path("e2b")),
                "--port", str(self.port), "--skiplaunch", "--usecpu", "--contextsize", "4096"]

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
            save_settings({"enabled": self._enabled})
        except OSError:
            pass  # the choice just won't survive a restart

    def _vision_ready(self):
        path = assets.vision_download_path("e2b")
        try:
            return path.is_file() and path.stat().st_size == assets.VISION_FILES["e2b"]["size"]
        except OSError:
            return False

    def _set(self, **changes):
        with self._lock:
            self._state.update(changes)

    def _download(self):
        try:
            if find_helper_model() is None:
                assets.download_gemma_model(
                    lambda percent: self._set(progress=round(percent * 0.78)),  # the model is ~78% of the bytes
                    lambda message: self._set(message=message), lambda: False, "e2b")
            if not self._vision_ready():
                assets.download_vision_file(
                    find_helper_model(),
                    lambda percent: self._set(progress=78 + round(percent * 0.22)),
                    lambda message: self._set(message=message), lambda: False)
        except (OSError, ValueError) as error:
            self.finish_with_error(str(error))
            return
        self._set(downloading=False, progress=100, message="")
        self.wake()
