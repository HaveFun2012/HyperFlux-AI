"""Image input: downloads the vision file for the loaded Gemma 4 model, then asks the
window to restart KoboldCpp with it (--mmproj).

The search bridge calls describe() and request_install() from its own thread; the
restart itself happens on the window's thread through the restart_requested signal.
"""

import threading

from PySide6.QtCore import QObject, Signal

from hyperflux.desktop import runtime_assets as assets


class VisionInstaller(QObject):
    restart_requested = Signal()

    def __init__(self, model_path, can_restart, parent=None):
        super().__init__(parent)
        self._model_path = model_path    # callable: the model KoboldCpp runs now
        self._can_restart = can_restart  # callable: False when HyperFlux didn't start the server
        self._lock = threading.Lock()
        self._state = {"downloading": False, "progress": 0, "error": "", "message": ""}

    def describe(self):
        model = self._model_path()
        family = assets.model_family(model)
        with self._lock:
            state = dict(self._state)
        info = assets.VISION_FILES.get(family) if family else None
        return {
            "supported": info is not None,
            "installed": assets.vision_file_for(model) is not None,
            "size_mb": round(info["size"] / 1e6) if info else None,
            "label": info["label"] if info else None,
            "can_restart": bool(self._can_restart()),
            **state,
        }

    def request_install(self):
        """Start the download in the background. Returns (accepted, message)."""
        model = self._model_path()
        if assets.model_family(model) is None:
            return False, "Image input needs a Gemma 4 E2B or E4B model."
        with self._lock:
            if self._state["downloading"]:
                return True, "Already downloading."
            self._state = {"downloading": True, "progress": 0, "error": "", "message": "Starting the download..."}
        threading.Thread(target=self._download, args=(model,), name="HyperFluxVisionDownload", daemon=True).start()
        return True, "Downloading."

    def _set(self, **changes):
        with self._lock:
            self._state.update(changes)

    def _download(self, model):
        try:
            assets.download_vision_file(model, lambda percent: self._set(progress=percent),
                                        lambda message: self._set(message=message), lambda: False)
        except (OSError, ValueError) as error:
            self._set(downloading=False, error=str(error), message="")
            return
        restart = self._can_restart()
        self._set(downloading=False, progress=100, message=(
            "Image input is ready. Reloading the model..." if restart
            else "Image input is ready. Restart HyperFlux to turn it on."))
        if restart:
            self.restart_requested.emit()
