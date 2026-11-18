"""Updates: finds a newer release, and downloads and installs it when the user says so.

The asking happens in the web page: a popup with the patch notes and changed files the
first time a version is found, then an "Update available" card in the sidebar that
stays until the update is installed or skipped ("Later"). The page reads describe()
and calls request_install() / skip() / mark_prompted() through the local bridge, from
the bridge's thread. This slim Qt bar above the page only shows the download.
"""

import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton

from hyperflux.desktop import updater
from hyperflux.version import __version__

_STYLE = """
QFrame#updateBar { background: #0f1b2d; border-bottom: 1px solid #1e3a5f; }
QLabel { color: #e2e8f0; font-size: 13px; }
QPushButton { color: #e2e8f0; background: transparent; border: 1px solid #334155;
              border-radius: 7px; padding: 4px 12px; font-size: 12px; }
QPushButton:hover { border-color: #38bdf8; }
QPushButton#primary { background: #0284c7; border-color: #0284c7; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #0369a1; }
QPushButton:disabled { color: #64748b; border-color: #1e293b; }
QProgressBar { border: 1px solid #334155; border-radius: 5px; background: #0b1220; color: #e2e8f0;
               max-height: 14px; min-width: 160px; text-align: center; font-size: 10px; }
QProgressBar::chunk { background: #0284c7; border-radius: 4px; }
"""


class UpdateBar(QFrame):
    """Hidden except while an update downloads (or a download failed)."""

    install_started = Signal()  # the window should close so the installer can replace it
    _found = Signal(dict)
    _progress = Signal(int)
    _failed = Signal(str)
    _ready = Signal(str)
    _install_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updateBar")
        self.setStyleSheet(_STYLE)
        self._lock = threading.Lock()
        self.info = None
        self._cancel = False
        self._busy = False
        self._percent = 0
        self._error = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 12, 8)
        layout.setSpacing(8)
        self.message = QLabel()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.update_button = QPushButton("Try again")
        self.update_button.setObjectName("primary")
        self.later_button = QPushButton("Cancel")
        layout.addWidget(self.message, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.later_button)
        layout.addWidget(self.update_button)

        self.update_button.clicked.connect(self._update_now)
        self.later_button.clicked.connect(self._later)
        self._found.connect(self._set_info)
        self._progress.connect(self._set_progress)
        self._failed.connect(self._show_error)
        self._ready.connect(self._install)
        self._install_requested.connect(self._update_now)
        self.hide()

    # ---- checking ----------------------------------------------------------------
    def check_in_background(self, force=False):
        """Offer an update found earlier at once, then ask GitHub if a check is due."""
        pending = updater.pending_update()
        if pending:
            self._set_info(pending)
        if not force and not updater.check_is_due():
            return

        def work():
            updater.cleanup_old_downloads(keep_version=pending["version"] if pending else None)
            info = updater.check_for_update(ignore_skipped=force)
            if info:
                self._found.emit(info)
        threading.Thread(target=work, name="HyperFluxUpdateCheck", daemon=True).start()

    def _set_info(self, info):
        with self._lock:
            self.info = info

    def _set_progress(self, percent):
        with self._lock:
            self._percent = percent
        self.progress.setValue(percent)

    # ---- what the page sees and asks for (called from the bridge thread) -------------
    def describe(self):
        with self._lock:
            info, busy, percent, error = self.info, self._busy, self._percent, self._error
        if not info:
            return {"available": False, "current": __version__}
        return {
            "available": True,
            "current": __version__,
            "version": info["version"],
            "size_mb": round(info["size"] / 2**20),
            "notes": info.get("notes") or "",
            "notes_url": info.get("notes_url") or "",
            "changes": info.get("changes"),
            "prompt": updater.should_prompt(info["version"]) and not busy,
            "downloading": busy,
            "progress": percent,
            "error": error,
        }

    def request_install(self):
        with self._lock:
            if not self.info:
                return False, "There is no update to install."
            if self._busy:
                return True, "Already downloading."
        self._install_requested.emit()  # runs on the window's thread
        return True, "Downloading the update."

    def skip(self):
        with self._lock:
            info, busy = self.info, self._busy
            if not info or busy:
                return False
            self.info = None
        updater.skip_version(info["version"])
        return True

    def mark_prompted(self):
        with self._lock:
            info = self.info
        if info:
            updater.mark_prompted(info["version"])
        return bool(info)

    # ---- downloading -------------------------------------------------------------
    def _later(self):
        if self._busy:
            self._cancel = True  # stop the download; the partial file is kept for next time
            self.message.setText("Stopping the download...")
            return
        self.hide()

    def _update_now(self):
        with self._lock:
            if not self.info or self._busy:
                return
            self._busy = True
            self._error = ""
            self._percent = 0
            info = self.info
        self._cancel = False
        self.update_button.hide()
        self.later_button.setText("Cancel")
        self.later_button.setEnabled(True)
        self.progress.setValue(0)
        self.progress.show()
        self.message.setText(f"Downloading HyperFlux {info['version']}...")
        self.show()

        def work():
            try:
                path = updater.download_update(info, self._progress.emit, lambda _msg: None, lambda: self._cancel)
                self._ready.emit(str(path))
            except InterruptedError:
                self._failed.emit("")
            except OSError as error:
                self._failed.emit(str(error))
            except Exception as error:  # never leave the bar stuck in "downloading"
                self._failed.emit(f"Unexpected error: {error!r}")
        threading.Thread(target=work, name="HyperFluxUpdateDownload", daemon=True).start()

    def _show_error(self, message):
        with self._lock:
            self._busy = False
            self._error = message or "The download was paused."
        self.progress.hide()
        self.update_button.show()
        self.later_button.setText("Later")
        self.message.setText(
            "Download paused. Click Try again to resume." if not message
            else f"Update failed: {message}"
        )

    def _install(self, path):
        self.message.setText("Installing the update. HyperFlux will close and reopen by itself...")
        self.progress.hide()
        self.later_button.setEnabled(False)
        try:
            updater.launch_installer(path)
        except OSError as error:
            self._show_error(f"Could not start the installer: {error}")
            return
        self.install_started.emit()
