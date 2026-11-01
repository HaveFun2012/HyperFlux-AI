"""Desktop entry point: first-run setup, smoke test, and main window."""

import sys

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMessageBox

from hyperflux.desktop.window import HyperFluxWindow
from hyperflux.paths import DESKTOP_LOGO, WEB_INTERFACE


def run_smoke_test():
    """Load the web interface and check its logos render. Returns a process exit code."""
    if not WEB_INTERFACE.is_file() or not DESKTOP_LOGO.is_file():
        return 2
    view = QWebEngineView()
    loop = QEventLoop()
    result = []
    timeout = QTimer()
    timeout.setSingleShot(True)

    def verify_logo_load(successful):
        if not successful:
            result.append(False)
            loop.quit()
            return
        view.page().runJavaScript(
            "(() => {"
            "const logos = [...document.querySelectorAll("
            "'.hyperflux-logo-img, .flash-model-logo-img')];"
            "return logos.length > 0 && logos.every("
            "image => image.complete && image.naturalWidth > 0);"
            "})()",
            lambda loaded: (result.append(bool(loaded)), loop.quit()),
        )

    view.loadFinished.connect(verify_logo_load)
    timeout.timeout.connect(loop.quit)
    view.load(QUrl.fromLocalFile(str(WEB_INTERFACE)))
    timeout.start(30000)
    loop.exec()
    return 0 if result == [True] else 3


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("HyperFlux AI")
    if "--smoke-test" in sys.argv[1:]:
        return run_smoke_test()

    # Packaged builds manage KoboldCpp themselves; source runs expect it already running.
    runtime_config = None
    if getattr(sys, "frozen", False):
        from hyperflux.desktop.setup_wizard import ensure_runtime

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
