"""Desktop window hosting the shared HyperFlux web interface."""

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
from PySide6.QtWidgets import QMainWindow, QMessageBox

from hyperflux.desktop.migration import migration_script as build_migration_script
from hyperflux.paths import (
    DESKTOP_LOGO,
    KOBOLD_LOG_PATH,
    WEB_INTERFACE,
    user_data_directory,
)


class HyperFluxWindow(QMainWindow):
    service_error = Signal(str)

    def __init__(self, runtime_config=None):
        super().__init__()
        self.runtime_config = runtime_config
        self._kobold_process = None
        self._search_server = None
        self._search_thread = None
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
        self.page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalStorageEnabled,
            True,
        )
        self.page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True,
        )
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

        self.view = QWebEngineView(self)
        self.view.setPage(self.page)
        self.view.loadFinished.connect(self._page_loaded)
        self.setCentralWidget(self.view)

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
            executable = self.runtime_config["kobold_path"]
            model = self.runtime_config["model_path"]
            KOBOLD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._kobold_process = QProcess(self)
            self._kobold_process.setWorkingDirectory(str(user_data_directory()))
            self._kobold_process.setProcessChannelMode(
                QProcess.ProcessChannelMode.MergedChannels
            )
            self._kobold_process.setStandardOutputFile(str(KOBOLD_LOG_PATH))
            self._kobold_process.errorOccurred.connect(
                lambda error: self.service_error.emit(
                    f"Could not start KoboldCpp ({error.name}). "
                    "Reopen setup and check the selected executable."
                )
            )
            self._kobold_process.finished.connect(
                lambda exit_code, _status: self.service_error.emit(
                    f"KoboldCpp stopped unexpectedly (exit code {exit_code})."
                )
                if exit_code != 0
                else None
            )
            self._kobold_process.start(
                executable,
                ["--model", model, "--port", "5001", "--skiplaunch"],
            )

        self._search_thread = threading.Thread(
            target=self._run_search_bridge,
            name="HyperFluxSearchBridge",
            daemon=True,
        )
        self._search_thread.start()

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
            )
            self._search_server = server
            server.serve_forever()
        except OSError as error:
            self.service_error.emit(f"Could not start the local search bridge: {error}")

    def closeEvent(self, event):
        if self._search_server is not None:
            self._search_server.shutdown()
            self._search_server.server_close()
        if self._kobold_process is not None:
            self._kobold_process.terminate()
            if not self._kobold_process.waitForFinished(3000):
                self._kobold_process.kill()
                self._kobold_process.waitForFinished(1000)
        super().closeEvent(event)
