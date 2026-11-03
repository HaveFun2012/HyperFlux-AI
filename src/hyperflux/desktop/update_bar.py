"""Slim bar at the top of the window that offers, downloads, and installs updates."""

import threading

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
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
    """Hidden until a newer verified release is found."""

    install_started = Signal()  # the window should close so the installer can replace it
    _found = Signal(dict)
    _progress = Signal(int)
    _failed = Signal(str)
    _ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updateBar")
        self.setStyleSheet(_STYLE)
        self.info = None
        self._cancel = False
        self._busy = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 12, 8)
        layout.setSpacing(8)
        self.message = QLabel()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.notes_button = QPushButton("What's new")
        self.update_button = QPushButton("Update now")
        self.update_button.setObjectName("primary")
        self.skip_button = QPushButton("Skip this version")
        self.later_button = QPushButton("Later")
        layout.addWidget(self.message, 1)
        layout.addWidget(self.progress)
        for button in (self.notes_button, self.skip_button, self.later_button, self.update_button):
            layout.addWidget(button)

        self.notes_button.clicked.connect(self._open_notes)
        self.update_button.clicked.connect(self._update_now)
        self.skip_button.clicked.connect(self._skip)
        self.later_button.clicked.connect(self._later)
        self._found.connect(self._show_update)
        self._progress.connect(self.progress.setValue)
        self._failed.connect(self._show_error)
        self._ready.connect(self._install)
        self.hide()

    # ---- checking ----------------------------------------------------------------
    def check_in_background(self, force=False):
        """Ask GitHub (at most once a day unless forced) without blocking the window."""
        if not force and not updater.check_is_due():
            return

        def work():
            updater.cleanup_old_downloads()
            info = updater.check_for_update(ignore_skipped=force)
            if info:
                self._found.emit(info)
        threading.Thread(target=work, name="HyperFluxUpdateCheck", daemon=True).start()

    def _show_update(self, info):
        self.info = info
        self.message.setText(
            f"<b>HyperFlux {info['version']}</b> is available. You have {__version__}."
        )
        self.show()

    # ---- buttons -----------------------------------------------------------------
    def _open_notes(self):
        if self.info:
            QDesktopServices.openUrl(QUrl(self.info["notes_url"]))

    def _skip(self):
        if self.info:
            updater.skip_version(self.info["version"])
        self.hide()

    def _later(self):
        if self._busy:
            self._cancel = True  # stop the download; the partial file is kept for next time
            self.message.setText("Stopping the download...")
            return
        self.hide()

    def _update_now(self):
        if not self.info or self._busy:
            return
        self._busy = True
        self._cancel = False
        self.update_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.later_button.setText("Cancel")
        self.progress.setValue(0)
        self.progress.show()
        self.message.setText(f"Downloading HyperFlux {self.info['version']}...")

        def work():
            try:
                path = updater.download_update(self.info, self._progress.emit, lambda _msg: None, lambda: self._cancel)
                self._ready.emit(str(path))
            except InterruptedError:
                self._failed.emit("")
            except OSError as error:
                self._failed.emit(str(error))
            except Exception as error:  # never leave the bar stuck in "downloading"
                self._failed.emit(f"Unexpected error: {error!r}")
        threading.Thread(target=work, name="HyperFluxUpdateDownload", daemon=True).start()

    def _show_error(self, message):
        self._busy = False
        self.progress.hide()
        self.update_button.setEnabled(True)
        self.update_button.setText("Try again")
        self.skip_button.setEnabled(True)
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
