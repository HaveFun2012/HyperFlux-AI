"""First-run asset selection and verified download wizard for packaged Windows builds."""

import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QThread, Signal
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


MODEL_URL = (
    "https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/"
    "d0976223747697cb51e056d85c532013931fe52e/"
    "gemma-3-4b-it-Q4_K_M.gguf?download=true"
)
MODEL_SHA256 = "4996030242583a40aa151ff93f49ed787ac8c25e4120c3ae4588b2e2a7d1ae94"
MODEL_SIZE = 2489758112
KOBOLD_RELEASE_API = "https://api.github.com/repos/LostRuins/koboldcpp/releases/latest"
APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "HyperFlux"
RUNTIME_CONFIG = APP_DATA / "runtime.json"


def _is_gguf(path):
    try:
        with Path(path).open("rb") as source:
            return source.read(4) == b"GGUF"
    except OSError:
        return False


def _is_windows_executable(path):
    try:
        with Path(path).open("rb") as source:
            dos_header = source.read(64)
            if len(dos_header) < 64 or dos_header[:2] != b"MZ":
                return False
            pe_offset = int.from_bytes(dos_header[60:64], "little")
            if not 64 <= pe_offset <= 16 * 1024 * 1024:
                return False
            source.seek(pe_offset)
            pe_header = source.read(6)
            return (
                pe_header[:4] == b"PE\0\0"
                and int.from_bytes(pe_header[4:6], "little") in {0x014C, 0x8664}
            )
    except OSError:
        return False


def _candidate_files(filename, extra_paths=()):
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    )
    local_programs = Path(os.environ.get("LOCALAPPDATA", APP_DATA.parent)) / "Programs"
    candidates = [
        Path(sys.executable).resolve().parent / filename,
        APP_DATA / filename,
        Path.home() / "Downloads" / filename,
        Path.home() / "Documents" / filename,
        Path.home() / "Desktop" / filename,
        local_programs / "KoboldCpp" / filename,
        program_files / "KoboldCpp" / filename,
        program_files_x86 / "KoboldCpp" / filename,
        Path.cwd() / filename,
        *map(Path, extra_paths),
    ]
    return next((path for path in candidates if path.is_file()), None)


def _candidate_gguf_files():
    directories = [
        APP_DATA / "models",
        Path.home() / "Downloads",
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path(sys.executable).resolve().parent,
        Path.cwd(),
    ]
    candidates = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.gguf"):
            if path.is_file() and _is_gguf(path):
                candidates[str(path.resolve()).casefold()] = path.resolve()
    preferred_names = {"model.gguf": 0, "gemma-3-4b-it-q4_k_m.gguf": 1}
    return sorted(
        candidates.values(),
        key=lambda path: (
            preferred_names.get(path.name.casefold(), 2),
            str(path).casefold(),
        ),
    )


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_config():
    try:
        config = json.loads(RUNTIME_CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read saved runtime settings: {error}") from error
    if not isinstance(config, dict):
        raise RuntimeError("Saved runtime settings are not a JSON object.")
    model_value = config.get("model_path")
    kobold_value = config.get("kobold_path")
    if not isinstance(model_value, str) or not isinstance(kobold_value, str):
        raise RuntimeError("Saved runtime settings contain invalid asset paths.")
    model_path = Path(model_value)
    kobold_path = Path(kobold_value)
    if not _is_gguf(model_path):
        return None
    if not _is_windows_executable(kobold_path):
        return None
    return {"model_path": str(model_path), "kobold_path": str(kobold_path)}


def _save_config(model_path, kobold_path):
    APP_DATA.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"model_path": str(model_path.resolve()), "kobold_path": str(kobold_path.resolve())},
        indent=2,
    )
    handle, temporary_path = tempfile.mkstemp(
        prefix="runtime-", suffix=".tmp", dir=APP_DATA
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, RUNTIME_CONFIG)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _download(
    url, destination, expected_size, expected_hash, progress, log, is_cancelled,
    request_headers=None,
):
    destination.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(destination.parent).free
    if free_bytes < expected_size + 64 * 1024 * 1024:
        raise OSError(
            f"Not enough free disk space for {destination.name}; "
            f"at least {expected_size + 64 * 1024 * 1024:,} bytes are required."
        )

    partial = destination.with_suffix(destination.suffix + ".part")
    if destination.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing asset {destination}; choose or remove it explicitly."
        )
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > expected_size:
        partial.unlink()
        offset = 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    headers.update(request_headers or {})
    response = requests.get(url, headers=headers, stream=True, timeout=(20, 90))
    try:
        response.raise_for_status()
        resume = offset > 0 and response.status_code == 206
        if resume and not response.headers.get("Content-Range", "").startswith(
            f"bytes {offset}-"
        ):
            response.close()
            partial.unlink(missing_ok=True)
            raise OSError("Download server returned an invalid range for resume.")
        if offset and not resume:
            offset = 0
            log("Server does not support resuming; restarting this asset download.")
        total = expected_size
        received = offset
        digest = hashlib.sha256()
        if resume:
            with partial.open("rb") as existing:
                for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                    digest.update(chunk)
        mode = "ab" if resume else "wb"
        with partial.open(mode) as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if is_cancelled():
                    raise InterruptedError("Setup cancelled; the partial download is available for retry.")
                if not chunk:
                    continue
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                progress(min(100, received * 100 // total))
        if received != expected_size:
            raise OSError(
                f"Downloaded size mismatch for {destination.name}: "
                f"expected {expected_size:,} bytes, received {received:,}."
            )
        if expected_hash and digest.hexdigest().lower() != expected_hash.lower():
            partial.unlink(missing_ok=True)
            raise OSError(f"SHA-256 verification failed for {destination.name}.")
        os.replace(partial, destination)
    finally:
        response.close()


class _SetupWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    completed = Signal(str, str)

    def __init__(self, model_choice, kobold_choice, download_model, hugging_face_token):
        super().__init__()
        self.model_choice = model_choice
        self.kobold_choice = kobold_choice
        self.download_model = download_model
        self.hugging_face_token = hugging_face_token

    def run(self):
        try:
            if self.isInterruptionRequested():
                raise InterruptedError
            model_path = self.model_choice
            kobold_path = self.kobold_choice
            if self.download_model:
                model_path = str(APP_DATA / "models" / "gemma-3-4b-it-Q4_K_M.gguf")
                existing_model = Path(model_path)
                if existing_model.exists():
                    if (
                        existing_model.stat().st_size != MODEL_SIZE
                        or _sha256(existing_model).lower() != MODEL_SHA256
                    ):
                        raise FileExistsError(
                            "A different file already exists at the Gemma download path. "
                            "It was preserved; move it or select another model before retrying."
                        )
                    self.log.emit("Reusing the existing verified Gemma model.")
                else:
                    self.log.emit("Downloading the explicitly selected Gemma 3 model.")
                    _download(
                        MODEL_URL,
                        existing_model,
                        MODEL_SIZE,
                        MODEL_SHA256,
                        self.progress.emit,
                        self.log.emit,
                        self.isInterruptionRequested,
                        (
                            {"Authorization": f"Bearer {self.hugging_face_token}"}
                            if self.hugging_face_token
                            else None
                        ),
                    )
            if kobold_path == "download":
                self.progress.emit(0)
                self.log.emit("Checking the official KoboldCpp release metadata.")
                metadata = requests.get(
                    KOBOLD_RELEASE_API,
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
                kobold_path = str(APP_DATA / "KoboldCpp" / "koboldcpp.exe")
                existing_kobold = Path(kobold_path)
                if existing_kobold.exists() and _is_windows_executable(existing_kobold):
                    self.log.emit("Reusing the existing KoboldCpp executable.")
                else:
                    self.log.emit(f"Downloading official KoboldCpp {release.get('tag_name', '')}.")
                    _download(
                        url,
                        existing_kobold,
                        size,
                        expected_hash,
                        self.progress.emit,
                        self.log.emit,
                        self.isInterruptionRequested,
                    )
                if not _is_windows_executable(kobold_path):
                    raise OSError("Downloaded KoboldCpp file is not a Windows executable.")
                if not expected_hash:
                    self.log.emit(
                        "GitHub supplied no SHA-256 digest; verified TLS source, "
                        "release asset size, and the Windows MZ executable header."
                    )
            if not _is_gguf(model_path):
                raise OSError("Selected model is not a readable GGUF file.")
            if not _is_windows_executable(kobold_path):
                raise OSError("Selected KoboldCpp path is not a Windows executable.")
            if self.isInterruptionRequested():
                raise InterruptedError
            _save_config(model_path, kobold_path)
            self.completed.emit(model_path, kobold_path)
        except InterruptedError:
            self.cancelled.emit()
        except (OSError, requests.RequestException, ValueError, TypeError) as error:
            self.failed.emit(str(error))


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
            "<p>Choose an existing GGUF model or explicitly download the listed "
            "Gemma model. HyperFlux will never substitute a different model.</p>"
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

        self.download_model = QCheckBox(
            "Download Gemma 3 4B IT Q4_K_M from Hugging Face (2.49 GB)"
        )
        self.download_model.toggled.connect(self._toggle_model_path)
        layout.addWidget(self.download_model)
        self.model_terms = QCheckBox(
            "I have reviewed and accept the applicable Gemma terms for this model."
        )
        layout.addWidget(self.model_terms)
        self.hugging_face_token = QLineEdit()
        self.hugging_face_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.hugging_face_token.setPlaceholderText(
            "Optional Hugging Face token; used for this download only, not saved"
        )
        layout.addWidget(self.hugging_face_token)

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
        self.status = QLabel("Select assets to continue. Downloads run in the background.")
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

        models = _candidate_gguf_files()
        kobold = _candidate_files(
            "koboldcpp.exe", [APP_DATA / "KoboldCpp" / "koboldcpp.exe"]
        )
        for model in models:
            self.detected_models.addItem(str(model), str(model))
        self.detected_models_label.setVisible(len(models) > 1)
        self.detected_models.setVisible(len(models) > 1)
        if models:
            self.model_path.setText(str(models[0]))
            self.download_model.setChecked(False)
        if kobold and _is_windows_executable(kobold):
            self.kobold_path.setText(str(kobold))
            self.download_kobold.setChecked(False)
        self._toggle_model_path(self.download_model.isChecked())
        self._toggle_kobold_path(self.download_kobold.isChecked())

    def _choose_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a GGUF model", str(Path.home()), "GGUF models (*.gguf)"
        )
        if path:
            self.detected_models.setCurrentIndex(-1)
            self.model_path.setText(path)
            self.download_model.setChecked(False)

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
        self.model_path.setEnabled(not downloading)
        self.model_browse.setEnabled(not downloading)
        self.detected_models.setEnabled(not downloading)
        self.model_terms.setEnabled(downloading)
        self.hugging_face_token.setEnabled(downloading)

    def _toggle_kobold_path(self, downloading):
        self.kobold_path.setEnabled(not downloading)
        self.kobold_browse.setEnabled(not downloading)

    def _start(self):
        download_model = self.download_model.isChecked()
        model_path = self.model_path.text().strip()
        kobold_path = "download" if self.download_kobold.isChecked() else self.kobold_path.text().strip()
        if not download_model and not _is_gguf(model_path):
            QMessageBox.warning(self, "Choose a model", "Select a readable GGUF model or choose the explicit Gemma download.")
            return
        if download_model and not self.model_terms.isChecked():
            QMessageBox.warning(self, "Model terms required", "Review and accept the applicable Gemma terms before downloading this model.")
            return
        if kobold_path != "download" and not _is_windows_executable(kobold_path):
            QMessageBox.warning(self, "Choose KoboldCpp", "Select a valid KoboldCpp Windows executable or choose the official download.")
            return

        self.continue_button.setEnabled(False)
        self.status.setText("Validating and preparing selected assets...")
        self.worker = _SetupWorker(
            model_path,
            kobold_path,
            download_model,
            self.hugging_face_token.text().strip(),
        )
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
            log_dir = APP_DATA / "logs"
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
        config = _load_config()
    except RuntimeError as error:
        config = None
        config_error = str(error)
    if config:
        return config
    wizard = SetupWizard(parent)
    if config_error:
        wizard._append_log(f"Saved setup settings need repair: {config_error}")
    elif RUNTIME_CONFIG.exists():
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
