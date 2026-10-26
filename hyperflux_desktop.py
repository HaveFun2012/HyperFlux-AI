"""Desktop window hosting the shared HyperFlux web interface."""

import json
import os
import re
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QEventLoop, QProcess, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtNetwork import QTcpSocket
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox


def data_directory():
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "HyperFlux"


def desktop_logo_path():
    logo_directory = Path(__file__).resolve().with_name("logo_hyperflux")
    desktop_logo = logo_directory / "hyperfluxdesktop.png"
    return desktop_logo if desktop_logo.is_file() else logo_directory / "dark5.4.png"


def _read_legacy_settings(path):
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as source:
        settings = json.load(source)
    if not isinstance(settings, dict):
        raise ValueError("Saved desktop settings must be a JSON object.")

    migrated = {}
    if "temperature" in settings or "max_length" in settings or "context_length" in settings:
        model_settings = {}
        if "temperature" in settings:
            model_settings["temperature"] = settings["temperature"]
        if "max_length" in settings:
            model_settings["maxLength"] = settings["max_length"]
        if "context_length" in settings:
            model_settings["contextLength"] = settings["context_length"]
        migrated["hfx_model_settings"] = model_settings

    if settings.get("appearance") in ("dark", "light"):
        migrated["hfx_theme"] = (
            "theme-light" if settings["appearance"] == "light" else "theme-default"
        )

    personalization = {}
    if isinstance(settings.get("display_name"), str):
        personalization["displayName"] = settings["display_name"][:32]
    if isinstance(settings.get("accent_color"), str) and re.fullmatch(
        r"#[0-9a-fA-F]{6}", settings["accent_color"]
    ):
        personalization["accentColor"] = settings["accent_color"]
    if settings.get("text_size") in ("small", "medium", "large"):
        personalization["textSize"] = settings["text_size"]
    if personalization:
        migrated["hfx_personalization"] = personalization
    return migrated


def _read_legacy_sessions(path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as source:
        sessions = json.load(source)
    if not isinstance(sessions, list):
        raise ValueError("Saved desktop chat history must be a JSON array.")

    migrated = []
    for session in sessions:
        if not isinstance(session, dict) or not isinstance(session.get("messages"), list):
            continue
        messages = []
        for message in session["messages"]:
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                continue
            role = message.get("role")
            if role not in {"user", "assistant", "ai"}:
                continue
            migrated_message = {
                "role": "ai" if role == "assistant" else role,
                "content": message["content"],
            }
            if message.get("runtime"):
                migrated_message["runtime"] = True
            if isinstance(message.get("attachment"), dict):
                migrated_message["attachment"] = message["attachment"]
            messages.append(migrated_message)
        migrated.append({
            "id": session.get("id") if isinstance(session.get("id"), str) else "",
            "title": session.get("title") if isinstance(session.get("title"), str) else "New chat",
            "messages": messages,
        })
    return migrated


def _migration_script():
    app_data = data_directory()
    settings = _read_legacy_settings(app_data / "settings.json")
    sessions = _read_legacy_sessions(app_data / "sessions.json")
    if sessions is not None:
        settings["hfx_sessions"] = sessions
    if not settings:
        return None

    encoded_settings = json.dumps(settings, ensure_ascii=True)
    encoded_settings = encoded_settings.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"""
(() => {{
  const migrated = {encoded_settings};
  for (const [key, value] of Object.entries(migrated)) {{
    if (localStorage.getItem(key) === null) {{
      localStorage.setItem(key, JSON.stringify(value));
    }}
  }}
}})();
"""


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

        icon_path = desktop_logo_path()
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        app_data = data_directory()
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
            migration_script = _migration_script()
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

        html_path = Path(__file__).resolve().with_name("HyperFlux Web.html")
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
            self._kobold_process = QProcess(self)
            self._kobold_process.setWorkingDirectory(str(data_directory()))
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
            from hyperflux_interacter import Config, HyperFluxEngine
            from hyperflux_server import create_search_bridge, search_bridge_is_running

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


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("HyperFlux AI")
    if "--smoke-test" in sys.argv[1:]:
        html_path = Path(__file__).resolve().with_name("HyperFlux Web.html")
        logo_path = desktop_logo_path()
        if not html_path.is_file() or not logo_path.is_file():
            return 2
        view = QWebEngineView()
        loop = QEventLoop()
        result = []
        timeout = QTimer()
        timeout.setSingleShot(True)
        view.loadFinished.connect(lambda successful: (result.append(successful), loop.quit()))
        timeout.timeout.connect(loop.quit)
        view.setHtml("<html><body>HyperFlux packaged WebEngine smoke test</body></html>")
        timeout.start(30000)
        loop.exec()
        return 0 if result == [True] else 3
    runtime_config = None
    if getattr(sys, "frozen", False):
        from hyperflux_setup import ensure_runtime

        try:
            runtime_config = ensure_runtime()
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(None, "HyperFlux setup failed", str(error))
            return 1
        if runtime_config is None:
            return 0
    try:
        window = HyperFluxWindow(runtime_config)
    except OSError as error:
        QMessageBox.critical(
            None,
            "HyperFlux could not start",
            f"Could not initialize the desktop app's local browser profile:\n{error}",
        )
        return 1
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
