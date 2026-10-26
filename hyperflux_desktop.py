"""Desktop window hosting the shared HyperFlux web interface."""

import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox


def data_directory():
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "HyperFlux"


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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HyperFlux AI")
        self.resize(1360, 900)
        self.setMinimumSize(900, 620)

        icon_path = Path(__file__).resolve().with_name("logo_hyperflux") / "dark5.4.png"
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


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("HyperFlux AI")
    try:
        window = HyperFluxWindow()
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
