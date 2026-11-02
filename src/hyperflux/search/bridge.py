"""Local HTTP search bridge (port 5002) used by the web and desktop interfaces.

Run on its own with:  python -m hyperflux.search.bridge
"""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from hyperflux.paths import KOBOLD_LOG_PATH

_LOG_TAIL_BYTES = 64 * 1024


class _SearchBridgeHandler(BaseHTTPRequestHandler):
    engine = None
    result_count = 3
    kobold_log_path = KOBOLD_LOG_PATH

    def _origin_is_allowed(self):
        origin = self.headers.get("Origin", "")
        return not origin or origin == "null" or origin.startswith("file://") or bool(re.fullmatch(
            r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?",
            origin,
            re.IGNORECASE,
        ))

    def end_headers(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif self._origin_is_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if not self._origin_is_allowed():
            self._send_json(403, {"error": "Origin not allowed."})
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "HyperFlux search"})
            return
        if self.path != "/kobold-logs":
            self._send_json(404, {"error": "Not found."})
            return
        if not self._origin_is_allowed():
            self._send_json(403, {"error": "Origin not allowed."})
            return

        log_path = Path(self.kobold_log_path)
        try:
            with log_path.open("rb") as source:
                source.seek(0, 2)
                size = source.tell()
                truncated = size > _LOG_TAIL_BYTES
                source.seek(max(0, size - _LOG_TAIL_BYTES))
                text = source.read(_LOG_TAIL_BYTES).decode("utf-8", errors="replace")
        except FileNotFoundError:
            self._send_json(200, {"available": False, "text": ""})
            return
        except OSError:
            self._send_json(500, {"error": "Could not read the KoboldCpp log."})
            return

        if truncated:
            text = "[Earlier log output omitted. Showing the most recent 64 KiB.]\n" + text
        self._send_json(200, {"available": True, "text": text})

    def do_POST(self):
        if self.path != "/search":
            self._send_json(404, {"error": "Not found."})
            return
        if not self._origin_is_allowed():
            self._send_json(403, {"error": "Origin not allowed."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Invalid Content-Length."})
            return
        if not 1 <= content_length <= 8192:
            self._send_json(413, {"error": "Search request must be between 1 and 8192 bytes."})
            return
        try:
            request_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON."})
            return
        query = request_data.get("query") if isinstance(request_data, dict) else None
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            self._send_json(400, {"error": "Search query must be 1 to 500 characters."})
            return

        optimized_query = self.engine.optimize_search_query(query)
        if not optimized_query:
            self._send_json(400, {"error": "Search query is empty after cleanup."})
            return
        results = self.engine.search_web(optimized_query, self.result_count)
        if results.startswith("SEARCH ERROR:"):
            self._send_json(502, {"error": results.removeprefix("SEARCH ERROR:").strip()})
            return
        self._send_json(200, {"query": optimized_query, "results": results})

    def log_message(self, format_string, *args):
        return


def create_search_bridge(engine, host="127.0.0.1", port=5002, result_count=3):
    handler = type(
        "HyperFluxSearchBridgeHandler",
        (_SearchBridgeHandler,),
        {"engine": engine, "result_count": result_count},
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def start_search_bridge(engine, host="127.0.0.1", port=5002, result_count=3):
    server = create_search_bridge(engine, host, port, result_count)
    bridge_thread = threading.Thread(
        target=server.serve_forever,
        name="HyperFluxSearchBridge",
        daemon=True,
    )
    bridge_thread.start()
    return server


def search_bridge_is_running(host="127.0.0.1", port=5002):
    try:
        response = requests.get(f"http://{host}:{port}/health", timeout=1)
        return response.ok
    except requests.exceptions.RequestException:
        return False


def run_search_bridge_service():
    from hyperflux.config import Config
    from hyperflux.core.engine import HyperFluxEngine

    server = create_search_bridge(
        HyperFluxEngine(),
        Config.SEARCH_BRIDGE_HOST,
        Config.SEARCH_BRIDGE_PORT,
        Config.SEARCH_RESULT_COUNT,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    run_search_bridge_service()
