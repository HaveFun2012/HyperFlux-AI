"""First-run setup dialog: pick a GGUF model and a (possibly downloaded) KoboldCpp."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from hyperflux.desktop import runtime_assets as assets


class _SetupWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    completed = Signal(str, str)

    def __init__(self, model_choice, kobold_choice):
        super().__init__()
        self.model_choice = model_choice
        self.kobold_choice = kobold_choice

    def run(self):
        try:
            if self.isInterruptionRequested():
                raise InterruptedError
            model_path = self.model_choice
            kobold_path = self.kobold_choice
            if model_path == "download":
                self.progress.emit(0)
                model_path = str(assets.download_gemma_model(
                    self.progress.emit, self.log.emit, self.isInterruptionRequested
                ))
                if self.isInterruptionRequested():
                    raise InterruptedError
            if kobold_path == "download":
                self.progress.emit(0)
                self.log.emit("Checking the official KoboldCpp release metadata.")
                metadata = requests.get(
                    assets.KOBOLD_RELEASE_API,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "HyperFlux-Setup",
                    },
                    timeout=(20, 60),
                )
                metadata.raise_for_status()
                release = metadata.json()
                asset = next(
                    (
                        item for item in release.get("assets", [])
                        if item.get("name") == "koboldcpp.exe"
                    ),
                    None,
                )
                if not isinstance(asset, dict):
                    raise OSError("Official KoboldCpp release has no Windows executable.")
                url = asset.get("browser_download_url", "")
                if urlparse(url).hostname != "github.com":
                    raise OSError("KoboldCpp download URL is not on official GitHub.")
                size = asset.get("size")
                if not isinstance(size, int) or size <= 0:
                    raise OSError("Official KoboldCpp release has no valid asset size.")
                digest = asset.get("digest", "")
                expected_hash = (
                    digest.split(":", 1)[1]
                    if isinstance(digest, str)
                    and digest.startswith("sha256:")
                    and len(digest.split(":", 1)[1]) == 64
                    else ""
                )
                kobold_path = str(assets.APP_DATA / "KoboldCpp" / "koboldcpp.exe")
                existing_kobold = Path(kobold_path)
                if existing_kobold.exists() and assets.is_windows_executable(existing_kobold):
                    self.log.emit("Reusing the existing KoboldCpp executable.")
                else:
                    self.log.emit(f"Downloading official KoboldCpp {release.get('tag_name', '')}.")
                    assets.download(
                        url,
                        existing_kobold,
                        size,
                        expected_hash,
                        self.progress.emit,
                        self.log.emit,
                        self.isInterruptionRequested,
                    )
                if not assets.is_windows_executable(kobold_path):
                    raise OSError("Downloaded KoboldCpp file is not a Windows executable.")
                if not expected_hash:
                    self.log.emit(
                        "GitHub supplied no SHA-256 digest; verified TLS source, "
                        "release asset size, and the Windows MZ executable header."
                    )
            if not assets.is_gguf(model_path):
                raise OSError("Selected model is not a readable GGUF file.")
            if not assets.is_windows_executable(kobold_path):
                raise OSError("Selected KoboldCpp path is not a Windows executable.")
            if self.isInterruptionRequested():
                raise InterruptedError
            assets.save_config(model_path, kobold_path)
            self.completed.emit(model_path, kobold_path)
        except InterruptedError:
            self.cancelled.emit()
        except (OSError, requests.RequestException, ValueError, TypeError) as error:
            self.failed.emit(str(error))
        except Exception as error:
            # Never let the thread die silently: the dialog would wait forever.
            self.failed.emit(f"Unexpected setup error: {error!r}")


class SetupWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HyperFlux setup")
        self.setMinimumWidth(620)
        self.worker = None
        self.result_config = None
        self._log_warning_shown = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<h2>Set up HyperFlux</h2>"
            "<p>Choose a GGUF model you already have, or download the recommended "
            "model. HyperFlux never replaces or silently substitutes model files.</p>"
        ))

        model_row = QHBoxLayout()
        self.model_path = QLineEdit()
        self.model_path.setPlaceholderText("Select an existing .gguf model")
        self.model_browse = QPushButton("Browse...")
        self.model_browse.clicked.connect(self._choose_model)
        model_row.addWidget(self.model_path, 1)
        model_row.addWidget(self.model_browse)
        layout.addLayout(model_row)

        self.detected_models_label = QLabel("Detected local GGUF models")
        self.detected_models = QComboBox()
        self.detected_models.currentIndexChanged.connect(self._select_detected_model)
        layout.addWidget(self.detected_models_label)
        layout.addWidget(self.detected_models)

        model_info = assets.GEMMA_MODEL
        self.download_model = QCheckBox(
            f"Download the recommended model: {model_info['label']}, "
            f"{model_info['size'] / 1e9:.1f} GB, from Hugging Face"
        )
        self.download_model.toggled.connect(self._toggle_model_path)
        layout.addWidget(self.download_model)
        model_note = QLabel(
            f"Released by Google under the <a href=\"{model_info['license_url']}\">"
            f"{model_info['license_name']}</a>. Saved to your HyperFlux data folder; "
            "the download is checked against a fixed SHA-256 fingerprint."
        )
        model_note.setOpenExternalLinks(True)
        model_note.setWordWrap(True)
        model_note.setStyleSheet("color: palette(placeholder-text); margin-left: 22px;")
        layout.addWidget(model_note)

        layout.addWidget(QLabel("KoboldCpp Windows executable"))
        kobold_row = QHBoxLayout()
        self.kobold_path = QLineEdit()
        self.kobold_path.setPlaceholderText("Select existing koboldcpp.exe")
        self.kobold_browse = QPushButton("Browse...")
        self.kobold_browse.clicked.connect(self._choose_kobold)
        kobold_row.addWidget(self.kobold_path, 1)
        kobold_row.addWidget(self.kobold_browse)
        layout.addLayout(kobold_row)
        self.download_kobold = QCheckBox(
            "Download KoboldCpp from its official GitHub release when no local copy is selected"
        )
        self.download_kobold.setChecked(True)
        self.download_kobold.toggled.connect(self._toggle_kobold_path)
        layout.addWidget(self.download_kobold)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(500)
        layout.addWidget(self.progress)
        layout.addWidget(self.log_output)
        self.status = QLabel(
            "Choose or download a model and KoboldCpp. Downloads run in the background and can be resumed."
        )
        layout.addWidget(self.status)

        button_row = QHBoxLayout()
        self.continue_button = QPushButton("Validate and continue")
        self.continue_button.clicked.connect(self._start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.continue_button)
        layout.addLayout(button_row)

        models = assets.find_gguf_models()
        kobold = assets.find_file(
            "koboldcpp.exe", [assets.APP_DATA / "KoboldCpp" / "koboldcpp.exe"]
        )
        for model in models:
            self.detected_models.addItem(str(model), str(model))
        self.detected_models_label.setVisible(len(models) > 1)
        self.detected_models.setVisible(len(models) > 1)
        if models:
            self.model_path.setText(str(models[0]))
        # Offer the download by default only when no model was found on this PC.
        self.download_model.setChecked(not models)
        self._toggle_model_path(self.download_model.isChecked())
        if kobold and assets.is_windows_executable(kobold):
            self.kobold_path.setText(str(kobold))
            self.download_kobold.setChecked(False)
        self._toggle_kobold_path(self.download_kobold.isChecked())

    def _choose_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a GGUF model", str(Path.home()), "GGUF models (*.gguf)"
        )
        if path:
            self.detected_models.setCurrentIndex(-1)
            self.model_path.setText(path)

    def _select_detected_model(self, index):
        if index >= 0:
            self.model_path.setText(self.detected_models.itemData(index))

    def _choose_kobold(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose KoboldCpp", str(Path.home()), "Windows applications (*.exe)"
        )
        if path:
            self.kobold_path.setText(path)
            self.download_kobold.setChecked(False)

    def _toggle_model_path(self, downloading):
        for widget in (self.model_path, self.model_browse, self.detected_models):
            widget.setEnabled(not downloading)

    def _confirm_model_licence(self):
        """Show the model's licence and size; True only if the user accepts."""
        info = assets.GEMMA_MODEL
        box = QMessageBox(self)
        box.setWindowTitle("Download Gemma 4 E2B")
        box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"HyperFlux will download <b>{info['label']}</b> "
            f"({info['size'] / 1e9:.1f} GB) from "
            f"<a href=\"{info['source_page']}\">Hugging Face</a>.<br><br>"
            f"Gemma 4 is made by Google and released under the "
            f"<a href=\"{info['license_url']}\">{info['license_name']}</a>. "
            "By downloading it you agree to those terms.<br><br>"
            "You need about 3.5 GB of free disk space. You can cancel and resume later."
        )
        accept = box.addButton("Accept and download", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is accept

    def _toggle_kobold_path(self, downloading):
        self.kobold_path.setEnabled(not downloading)
        self.kobold_browse.setEnabled(not downloading)

    def _start(self):
        downloading_model = self.download_model.isChecked()
        model_path = "download" if downloading_model else self.model_path.text().strip()
        kobold_path = "download" if self.download_kobold.isChecked() else self.kobold_path.text().strip()
        if downloading_model:
            if not self._confirm_model_licence():
                return
        elif not assets.is_gguf(model_path):
            QMessageBox.warning(
                self,
                "Choose a model",
                "Select a readable GGUF model, or tick the option to download the recommended one.",
            )
            return
        if kobold_path != "download" and not assets.is_windows_executable(kobold_path):
            QMessageBox.warning(self, "Choose KoboldCpp", "Select a valid KoboldCpp Windows executable or choose the official download.")
            return

        self.continue_button.setEnabled(False)
        self.status.setText("Validating and preparing selected assets...")
        self.worker = _SetupWorker(model_path, kobold_path)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.log.connect(self._append_log)
        self.worker.failed.connect(self._failed)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.completed.connect(self._completed)
        self.worker.start()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.status.setText("Stopping safely. The partial download will be kept for retry.")
            self.cancel_button.setEnabled(False)
            return
        super().reject()

    def _failed(self, message):
        if self.worker is not None:
            self.worker.wait()
        self._append_log(f"ERROR: {message}")
        self.status.setText("Setup did not complete. Review the error and retry.")
        self.continue_button.setText("Retry")
        self.continue_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        QMessageBox.critical(self, "HyperFlux setup failed", message)

    def _cancelled(self):
        if self.worker is not None:
            self.worker.wait()
        self.status.setText("Setup cancelled. You can resume a partial download next time.")
        super().reject()

    def _completed(self, model_path, kobold_path):
        if self.worker is not None:
            self.worker.wait()
        self.result_config = {"model_path": model_path, "kobold_path": kobold_path}
        self._append_log("Assets validated and settings saved.")
        self.accept()

    def _append_log(self, message):
        line = f"{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')} {message}"
        self.log_output.appendPlainText(line)
        try:
            log_dir = assets.APP_DATA / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / "setup.log").open("a", encoding="utf-8") as destination:
                destination.write(line + "\n")
        except OSError as error:
            if not self._log_warning_shown:
                self._log_warning_shown = True
                self.log_output.appendPlainText(f"Could not write setup log file: {error}")


def ensure_runtime(parent=None):
    config_error = None
    try:
        config = assets.load_config()
    except RuntimeError as error:
        config = None
        config_error = str(error)
    if config:
        return config
    wizard = SetupWizard(parent)
    if config_error:
        wizard._append_log(f"Saved setup settings need repair: {config_error}")
    elif assets.RUNTIME_CONFIG.exists():
        wizard._append_log(
            "Saved asset paths are no longer valid. Select current assets to continue."
        )
    if wizard.exec() != QDialog.DialogCode.Accepted or not wizard.result_config:
        return None
    return wizard.result_config


def main():
    application = QApplication(sys.argv)
    if ensure_runtime() is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
