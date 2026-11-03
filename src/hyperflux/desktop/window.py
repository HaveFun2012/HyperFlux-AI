"""Desktop window hosting the shared HyperFlux web interface."""

import json
import threading

from PySide6.QtCore import QProcess, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtNetwork import QTcpSocket
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QVBoxLayout, QWidget

from hyperflux.desktop.migration import migration_script as build_migration_script
from hyperflux.desktop.model_switcher import LocalModels
from hyperflux.desktop.process_tree import descendant_pids, terminate_pid
from hyperflux.desktop.runtime_assets import save_config
from hyperflux.desktop.update_bar import UpdateBar
from hyperflux.search.bridge import load_or_create_token
from hyperflux.paths import (
    DESKTOP_LOGO,
    KOBOLD_LOG_PATH,
    WEB_INTERFACE,
    user_data_directory,
)


def apply_page_settings(page):
    """Settings the web interface needs. Shared with the smoke test so it checks the same setup."""
    attributes = QWebEngineSettings.WebAttribute
    settings = page.settings()
    settings.setAttribute(attributes.LocalStorageEnabled, True)
    # The page is a local file that calls KoboldCpp (5001) and the bridge (5002).
    settings.setAttribute(attributes.LocalContentCanAccessRemoteUrls, True)
    # Must be set explicitly alongside the line above: otherwise Qt blocks the
    # page's own local files (logo images, KaTeX script, styles, and fonts).
    settings.setAttribute(attributes.LocalContentCanAccessFileUrls, True)
    # Lets the Copy buttons write to the clipboard (writing only, no reading).
    settings.setAttribute(attributes.JavascriptCanAccessClipboard, True)


class HyperFluxWindow(QMainWindow):
    service_error = Signal(str)

    def __init__(self, runtime_config=None, check_updates=False):
        super().__init__()
        self.runtime_config = runtime_config
        self._kobold_process = None
        self._search_server = None
        self._search_thread = None
        self._shutting_down = False
        self._restarting_kobold = False
        self._kobold_alive = False
        self.local_models = None
        self.setWindowTitle("HyperFlux AI")
        self.resize(1360, 900)
        self.setMinimumSize(900, 620)

        icon_path = DESKTOP_LOGO
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        app_data = user_data_directory()
        profile_path = app_data / "desktop_web_profile"
        cache_path = app_data / "desktop_web_cache"
        profile_path.mkdir(parents=True, exist_ok=True)
        cache_path.mkdir(parents=True, exist_ok=True)

        self.profile = QWebEngineProfile("HyperFluxDesktop", self)
        self.profile.setPersistentStoragePath(str(profile_path))
        self.profile.setCachePath(str(cache_path))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )

        self.page = QWebEnginePage(self.profile, self)
        apply_page_settings(self.page)
        self.page.newWindowRequested.connect(self._open_external_link)

        try:
            migration_script = build_migration_script()
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            QMessageBox.warning(
                self,
                "Saved desktop data could not be imported",
                f"The previous desktop settings or chats could not be imported:\n{error}",
            )
            migration_script = None
        if migration_script is not None:
            script = QWebEngineScript()
            script.setName("HyperFlux legacy desktop data migration")
            script.setInjectionPoint(
                QWebEngineScript.InjectionPoint.DocumentCreation
            )
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setRunsOnSubFrames(False)
            script.setSourceCode(migration_script)
            self.page.scripts().insert(script)

        # Lets this page (and no website) read live KoboldCpp logs from the bridge.
        token_script = QWebEngineScript()
        token_script.setName("HyperFlux bridge token")
        token_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        token_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        token_script.setRunsOnSubFrames(False)
        token_script.setSourceCode(
            f"window.HYPERFLUX_BRIDGE_TOKEN = {json.dumps(load_or_create_token())};"
        )
        self.page.scripts().insert(token_script)

        self.view = QWebEngineView(self)
        self.view.setPage(self.page)
        self.view.loadFinished.connect(self._page_loaded)
        # Update bar (hidden unless a newer release is found) above the web interface.
        self.update_bar = UpdateBar(self)
        self.update_bar.install_started.connect(self._close_for_update)
        central = QWidget(self)
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.update_bar)
        column.addWidget(self.view, 1)
        self.setCentralWidget(central)
        if check_updates:
            self.update_bar.check_in_background()

        html_path = WEB_INTERFACE
        if not html_path.is_file():
            QMessageBox.critical(
                self,
                "HyperFlux interface unavailable",
                f"Could not find the web interface:\n{html_path}",
            )
            return
        self.view.load(QUrl.fromLocalFile(str(html_path)))
        if runtime_config:
            self.service_error.connect(
                lambda message: QMessageBox.critical(self, "Local service failed", message)
            )
            self._start_local_services()

    def _open_external_link(self, request):
        QDesktopServices.openUrl(request.requestedUrl())

    def _page_loaded(self, successful):
        if not successful:
            QMessageBox.critical(
                self,
                "HyperFlux interface failed to load",
                "The desktop window could not load HyperFlux Web.html. "
                "Check that the project files are present and try again.",
            )

    def _start_local_services(self):
        model_socket = QTcpSocket(self)
        model_socket.connectToHost("127.0.0.1", 5001)
        model_running = model_socket.waitForConnected(250)
        model_socket.abort()
        if not model_running:
            self._start_kobold()

        # The model picker can switch models only when HyperFlux runs the server itself.
        self.local_models = LocalModels(
            self.runtime_config["model_path"],
            can_switch=lambda: self._kobold_process is not None,
            is_running=self._kobold_running,
            parent=self,
        )
        self.local_models.switch_requested.connect(self._switch_model)

        self._search_thread = threading.Thread(
            target=self._run_search_bridge,
            name="HyperFluxSearchBridge",
            daemon=True,
        )
        self._search_thread.start()

    def _start_kobold(self):
        executable = self.runtime_config["kobold_path"]
        model = self.runtime_config["model_path"]
        KOBOLD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._kobold_process = QProcess(self)
        self._kobold_process.setWorkingDirectory(str(user_data_directory()))
        self._kobold_process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )
        self._kobold_process.setStandardOutputFile(str(KOBOLD_LOG_PATH))
        self._kobold_process.errorOccurred.connect(self._kobold_error)
        self._kobold_process.finished.connect(self._kobold_finished)
        self._kobold_alive = True
        self._kobold_process.start(
            executable,
            ["--model", model, "--port", "5001", "--skiplaunch"],
        )
        if self._kobold_process.state() == QProcess.ProcessState.NotRunning:
            self._kobold_alive = False

    def _kobold_running(self):
        # Read from the bridge thread, so it reads a flag the window thread keeps.
        return self._kobold_alive

    def _switch_model(self, model_path):
        """Stop the server and start it again with another model (model picker)."""
        previous = self.runtime_config["model_path"]
        self._restarting_kobold = True
        old_process = self._kobold_process
        try:
            self._stop_kobold()
        finally:
            self._restarting_kobold = False
        if old_process is not None:
            old_process.deleteLater()
        self.runtime_config = {**self.runtime_config, "model_path": model_path}
        try:
            save_config(model_path, self.runtime_config["kobold_path"])  # used next launch too
        except OSError as error:
            self.service_error.emit(f"The model was switched, but the choice could not be saved: {error}")
        self._start_kobold()
        failed = self._kobold_process.state() == QProcess.ProcessState.NotRunning
        if failed:
            self.runtime_config = {**self.runtime_config, "model_path": previous}
        self.local_models.finished(model_path, failed=failed, previous_path=previous)

    def _kobold_error(self, error):
        # Crashes are reported once, by _kobold_finished.
        if self._shutting_down or self._restarting_kobold or error == QProcess.ProcessError.Crashed:
            return
        if error == QProcess.ProcessError.FailedToStart:
            self._kobold_alive = False
            message = (
                "Could not start KoboldCpp. "
                "Reopen setup and check the selected executable."
            )
        else:
            message = f"KoboldCpp reported an error ({error.name}). See {KOBOLD_LOG_PATH}."
        self.service_error.emit(message)

    def _kobold_finished(self, exit_code, _status):
        if self.sender() is self._kobold_process:  # not an old, replaced process
            self._kobold_alive = False
        if self._shutting_down or self._restarting_kobold or exit_code == 0:
            return
        self.service_error.emit(
            f"KoboldCpp stopped unexpectedly (exit code {exit_code}). See {KOBOLD_LOG_PATH}."
        )

    def _stop_kobold(self):
        process = self._kobold_process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return
        # The real server is a child of the launcher we started. Stop it first so
        # the launcher exits on its own and deletes its unpacked temp folder.
        for pid in descendant_pids(process.processId()):
            terminate_pid(pid)
        if not process.waitForFinished(5000):
            process.kill()
            process.waitForFinished(1000)

    def _run_search_bridge(self):
        try:
            from hyperflux.config import Config
            from hyperflux.core.engine import HyperFluxEngine
            from hyperflux.search.bridge import create_search_bridge, search_bridge_is_running

            if search_bridge_is_running(Config.SEARCH_BRIDGE_HOST, Config.SEARCH_BRIDGE_PORT):
                return
            engine = HyperFluxEngine()
            server = create_search_bridge(
                engine,
                Config.SEARCH_BRIDGE_HOST,
                Config.SEARCH_BRIDGE_PORT,
                Config.SEARCH_RESULT_COUNT,
                model_manager=self.local_models,
            )
            self._search_server = server
            server.serve_forever()
        except OSError as error:
            self.service_error.emit(f"Could not start the local search bridge: {error}")

    def _close_for_update(self):
        # The installer replaces HyperFlux's files, so close (stopping KoboldCpp too).
        self.close()
        QApplication.quit()

    def closeEvent(self, event):
        # Stopping services on purpose must not show "stopped unexpectedly" popups.
        self._shutting_down = True
        if self._search_server is not None:
            self._search_server.shutdown()
            self._search_server.server_close()
        self._stop_kobold()
        super().closeEvent(event)
