"""Lets the page's model picker list the local GGUF models and switch between them.

The search bridge calls this from its own thread; the actual restart of KoboldCpp
happens on the window's thread through the switch_requested signal. Only one model
is ever loaded, so switching frees the old model's memory before loading the new one.
"""

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from hyperflux.desktop import runtime_assets as assets


class LocalModels(QObject):
    switch_requested = Signal(str)

    def __init__(self, active_path, can_switch, is_running=lambda: True, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._active_path = str(active_path)
        self._can_switch = can_switch  # False when HyperFlux didn't start the server
        self._is_running = is_running  # False once the server process has stopped
        self._switching = False

    def describe(self):
        with self._lock:
            active, switching = self._active_path, self._switching
        return {
            "available": bool(self._can_switch()),
            "switching": switching,
            "server_running": bool(self._is_running()),
            "models": assets.describe_local_models(active),
        }

    def request_switch(self, path):
        """Ask to load another model. Returns (accepted, message)."""
        if not self._can_switch():
            return False, "Restart HyperFlux to switch models; it did not start this server."
        if not isinstance(path, str) or not path:
            return False, "Choose a model."
        wanted = str(Path(path).resolve()).casefold()
        with self._lock:
            # Only files this PC's model list offers; never an arbitrary path.
            listed = {model["path"].casefold(): model["path"]
                      for model in assets.describe_local_models(self._active_path)}
            if wanted not in listed:
                return False, "That model is not in the list of models on this PC."
            if self._switching:
                return False, "Another model is still loading."
            if wanted == str(Path(self._active_path).resolve()).casefold():
                return True, "That model is already loaded."
            self._switching = True
            self._active_path = listed[wanted]
        self.switch_requested.emit(listed[wanted])
        return True, "Loading the model."

    def finished(self, active_path=None, failed=False, previous_path=None):
        with self._lock:
            if failed and previous_path:
                self._active_path = str(previous_path)
            elif active_path:
                self._active_path = str(active_path)
            self._switching = False
