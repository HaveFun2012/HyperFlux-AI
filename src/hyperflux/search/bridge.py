"""Local HTTP search bridge (port 5002) used by the web and desktop interfaces.

Run on its own with:  python -m hyperflux.search.bridge
"""

import hmac
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

from hyperflux.desktop import ocr, video
from hyperflux.paths import BRIDGE_TOKEN_PATH, KOBOLD_LOG_PATH
from hyperflux.search import research

_LOG_TAIL_BYTES = 64 * 1024
OCR_REQUEST_LIMIT = 34 * 1024 * 1024  # a 25 MB picture as base64 inside JSON
# Blocks DNS-rebinding pages, which reach 127.0.0.1 under their own host name.
_ALLOWED_HOSTS = re.compile(r"(?:localhost|127\.0\.0\.1)(?::\d+)?", re.IGNORECASE)


def load_or_create_token(path=BRIDGE_TOKEN_PATH):
    """Return the shared bridge token, creating it on first use.

    Any website can send requests with `Origin: null` (sandboxed iframes), so the
    origin check alone can't protect the logs. Only the desktop app reads this file.
    """
    path = Path(path)
    try:
        token = path.read_text(encoding="ascii").strip()
        if token:
            return token
    except (OSError, UnicodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        # "x" mode: if another process created it first, use theirs.
        with path.open("x", encoding="ascii") as destination:
            destination.write(token)
    except FileExistsError:
        return path.read_text(encoding="ascii").strip()
    except OSError:
        pass
    return token


class _SearchBridgeHandler(BaseHTTPRequestHandler):
    engine = None
    result_count = 3
    kobold_log_path = KOBOLD_LOG_PATH
    log_token = ""
    model_manager = None  # desktop app only: lists and switches local models
    vision_manager = None  # desktop app only: downloads the image-input file
    performance_manager = None  # desktop app only: speed settings
    image_helper = None  # desktop app only: the second, picture-reading server
    update_manager = None  # installed desktop app only: offers and installs updates

    def _host_is_allowed(self):
        return bool(_ALLOWED_HOSTS.fullmatch(self.headers.get("Host", "")))

    def _log_token_is_valid(self):
        query = parse_qs(urlsplit(self.path).query)
        supplied = (query.get("token") or [""])[0]
        return bool(self.log_token) and hmac.compare_digest(supplied, self.log_token)

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
        if not self._host_is_allowed() or not self._origin_is_allowed():
            self._send_json(403, {"error": "Origin not allowed."})
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._host_is_allowed():
            self._send_json(403, {"error": "Host not allowed."})
            return
        route = urlsplit(self.path).path
        if route == "/health":
            self._send_json(200, {"status": "ok", "service": "HyperFlux search"})
            return
        if route not in ("/kobold-logs", "/local-models", "/vision", "/update", "/image-helper", "/performance"):
            self._send_json(404, {"error": "Not found."})
            return
        if not self._origin_is_allowed():
            self._send_json(403, {"error": "Origin not allowed."})
            return
        if not self._log_token_is_valid():
            self._send_json(403, {"error": "Live logs are only available in the HyperFlux desktop app."})
            return
        if route == "/update":
            if self.update_manager is None:
                self._send_json(200, {"available": False})
            else:
                self._send_json(200, self.update_manager.describe())
            return
        if route == "/performance":
            if self.performance_manager is None:
                self._send_json(200, {"unavailable": True})
            else:
                self._send_json(200, self.performance_manager.describe())
            return
        if route == "/image-helper":
            if self.image_helper is None:
                self._send_json(200, {"unavailable": True, "enabled": False, "status": "off"})
            else:
                self._send_json(200, self.image_helper.describe())
            return
        if route == "/vision":
            if self.vision_manager is None:
                # A bridge started outside the desktop app can't download or restart anything.
                self._send_json(200, {"supported": False, "installed": False, "downloading": False,
                                      "unavailable": True})
            else:
                self._send_json(200, self.vision_manager.describe())
            return
        if route == "/local-models":
            if self.model_manager is None:
                self._send_json(200, {"available": False, "switching": False, "models": []})
            else:
                self._send_json(200, self.model_manager.describe())
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

    def _discard_body(self):
        # Read a small request body before refusing it. Replying with the body still
        # unread makes Windows reset the connection, so the client never sees the error.
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < length <= 8192:
            self.rfile.read(length)

    def do_POST(self):
        if not self._host_is_allowed():
            self._discard_body()
            self._send_json(403, {"error": "Host not allowed."})
            return
        route = urlsplit(self.path).path
        if route not in ("/search", "/research/plan", "/research/sources", "/research/tidy",
                         "/local-models/switch", "/vision/install", "/update/install", "/update/skip",
                         "/update/prompted", "/image-helper/enable", "/image-helper/disable",
                         "/image-helper/wake", "/image-helper/used",
                         "/image-helper/runner-cpu", "/image-helper/runner-igpu", "/image/read", "/video/frames", "/performance"):
            self._discard_body()
            self._send_json(404, {"error": "Not found."})
            return
        if not self._origin_is_allowed():
            self._discard_body()
            self._send_json(403, {"error": "Origin not allowed."})
            return
        if route == "/local-models/switch":
            self._switch_model()
            return
        if route.startswith("/update/"):
            self._discard_body()
            if not self._log_token_is_valid() or self.update_manager is None:
                self._send_json(403, {"error": "Updates are only available in the installed HyperFlux app."})
                return
            if route == "/update/install":
                accepted, message = self.update_manager.request_install()
                self._send_json(202 if accepted else 409, {"accepted": accepted, "message": message})
            elif route == "/update/skip":
                self._send_json(200, {"skipped": self.update_manager.skip()})
            else:
                self._send_json(200, {"ok": self.update_manager.mark_prompted()})
            return
        if route.startswith("/research/"):
            self._research(route)
            return
        if route == "/performance":
            self._save_performance()
            return
        if route == "/video/frames":
            self._video_frames()
            return
        if route == "/image/read":
            self._read_image_text()
            return
        if route.startswith("/image-helper/"):
            self._discard_body()
            if not self._log_token_is_valid() or self.image_helper is None:
                self._send_json(403, {"error": "The image helper is only available in the HyperFlux desktop app."})
                return
            action = route.rsplit("/", 1)[1]
            if action == "used":
                self.image_helper.touch()
                self._send_json(200, {"ok": True})
                return
            if action.startswith("runner-"):
                accepted, message = self.image_helper.set_runner(action.removeprefix("runner-"))
                self._send_json(200 if accepted else 409, {"accepted": accepted, "message": message})
                return
            if action == "wake":
                self._send_json(200, {"accepted": self.image_helper.wake()})
                return
            accepted, message = (self.image_helper.request_enable() if action == "enable"
                                 else self.image_helper.request_disable())
            self._send_json(202 if accepted else 409, {"accepted": accepted, "message": message})
            return
        if route == "/vision/install":
            self._discard_body()
            if not self._log_token_is_valid() or self.vision_manager is None:
                self._send_json(403, {"error": "Image input can only be set up in the HyperFlux desktop app."})
                return
            accepted, message = self.vision_manager.request_install()
            self._send_json(202 if accepted else 409, {"accepted": accepted, "message": message})
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

    def _save_performance(self):
        """/performance {pictures: auto|chat|pictures, context: int, layers: auto|speed}
        -> {restarting, changed}"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 1 <= length <= 1024:
            self._discard_body()
            self._send_json(413, {"error": "Request must be between 1 and 1024 bytes."})
            return
        body = self.rfile.read(length)
        if not self._log_token_is_valid() or self.performance_manager is None:
            self._send_json(403, {"error": "Speed settings are only available in the HyperFlux desktop app."})
            return
        try:
            data = json.loads(body.decode("utf-8"))
            pictures, context = data["pictures"], data["context"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            self._send_json(400, {"error": "Send pictures and context."})
            return
        try:
            self._send_json(200, self.performance_manager.update(pictures, context, data.get("layers", "auto")))
        except OSError as error:
            self._send_json(500, {"error": f"The settings could not be saved: {error}"})

    def _video_frames(self):
        """/video/frames?name=clip.mp4 with the video file as the body -> {duration, frames:
        [{time, image}]}: still frames taken by Windows' own decoder, for a model to look at."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        name = (parse_qs(urlsplit(self.path).query).get("name") or [""])[0]
        problem = None
        if not self._log_token_is_valid():
            problem = (403, "Reading videos is only available in the HyperFlux desktop app.")
        elif not video.is_video_name(name):
            problem = (415, "That isn't a video format HyperFlux can read.")
        elif not 1 <= length <= video.MAX_VIDEO_BYTES:
            problem = (413, f"The video must be smaller than {video.MAX_VIDEO_BYTES // (1024 * 1024)} MB.")
        if problem:
            self._drain(length)
            self._send_json(problem[0], {"error": problem[1]})
            return
        # Only the extension comes from the request; the file's name is ours.
        handle, temporary = tempfile.mkstemp(suffix=Path(name).suffix.lower(), prefix="hyperflux-video-")
        try:
            with os.fdopen(handle, "wb") as target:
                remaining = length
                while remaining:  # copied in pieces so a large video is never held in memory
                    piece = self.rfile.read(min(remaining, 1024 * 1024))
                    if not piece:
                        raise ValueError("The video did not arrive completely.")
                    target.write(piece)
                    remaining -= len(piece)
            result = video.extract_frames(temporary)
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return
        except (OSError, subprocess.SubprocessError) as error:
            self._send_json(502, {"error": " ".join(str(error).split())})
            return
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        self._send_json(200, result)

    def _drain(self, length):
        """Read and throw away a refused upload, so the client gets the reason instead of a reset."""
        remaining = min(max(length, 0), video.MAX_VIDEO_BYTES)
        while remaining:
            piece = self.rfile.read(min(remaining, 1024 * 1024))
            if not piece:
                return
            remaining -= len(piece)

    def _read_image_text(self):
        """/image/read {image: data URL} -> {text}: the text in a picture, read by Windows' own OCR."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 1 <= length <= OCR_REQUEST_LIMIT:
            self._discard_body()
            self._send_json(413, {"error": "The picture must be smaller than 25 MB."})
            return
        body = self.rfile.read(length)
        if not self._log_token_is_valid():
            self._send_json(403, {"error": "Reading pictures is only available in the HyperFlux desktop app."})
            return
        try:
            data = json.loads(body.decode("utf-8"))
            text = ocr.read_data_url(data.get("image") if isinstance(data, dict) else None)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._send_json(400, {"error": str(error) or "Request body must be valid JSON."})
            return
        except (OSError, subprocess.SubprocessError) as error:
            self._send_json(502, {"error": f"The text reader failed: {error}"})
            return
        self._send_json(200, {"text": text})

    def _research(self, route):
        """The web research pipeline, in two calls so the page can show each stage:
        /research/plan     {question, force?, previous?}  -> {search, need, queries}
        /research/sources  {question, queries}            -> {sources, context, prompt, pages_read}
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        limit = 65536 if route == "/research/tidy" else 8192  # a finished answer is longer than a question
        if not 1 <= length <= limit:
            self._discard_body()
            self._send_json(413, {"error": f"Request must be between 1 and {limit} bytes."})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON."})
            return
        if route == "/research/tidy":
            answer = data.get("answer") if isinstance(data, dict) else None
            if not isinstance(answer, str):
                self._send_json(400, {"error": "Give the answer text."})
                return
            self._send_json(200, {"answer": research.dedupe_sentences(answer)})
            return
        question = data.get("question") if isinstance(data, dict) else None
        if not isinstance(question, str) or not question.strip() or len(question) > 4000:
            self._send_json(400, {"error": "The question must be 1 to 4000 characters."})
            return
        if route == "/research/plan":
            previous = [str(q)[:100] for q in (data.get("previous") or [])][:6]
            self._send_json(200, research.plan(question, force=bool(data.get("force")), previous=previous))
            return
        queries = [str(q).strip()[:100] for q in (data.get("queries") or []) if str(q).strip()][:3]
        if not queries:
            self._send_json(400, {"error": "Give 1 to 3 search queries."})
            return
        found = research.gather_sources(question, queries)
        if not found["sources"]:
            self._send_json(502, {"error": "The web search returned no usable results.", **found})
            return
        self._send_json(200, {**found, "prompt": research.build_answer_prompt(question, found["context"])})

    def _switch_model(self):
        if not self._log_token_is_valid() or self.model_manager is None:
            self._discard_body()
            self._send_json(403, {"error": "Model switching is only available in the HyperFlux desktop app."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 1 <= length <= 4096:
            self._discard_body()
            self._send_json(400, {"error": "Invalid request."})
            return
        try:
            request_data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON."})
            return
        path = request_data.get("path") if isinstance(request_data, dict) else None
        accepted, message = self.model_manager.request_switch(path)
        self._send_json(202 if accepted else 409, {"accepted": accepted, "message": message})

    def log_message(self, format_string, *args):
        return


def create_search_bridge(engine, host="127.0.0.1", port=5002, result_count=3, log_token=None,
                         model_manager=None, vision_manager=None, update_manager=None, image_helper=None,
                         performance_manager=None):
    handler = type(
        "HyperFluxSearchBridgeHandler",
        (_SearchBridgeHandler,),
        {
            "engine": engine,
            "result_count": result_count,
            "log_token": load_or_create_token() if log_token is None else log_token,
            "model_manager": model_manager,
            "vision_manager": vision_manager,
            "image_helper": image_helper,
            "performance_manager": performance_manager,
            "update_manager": update_manager,
        },
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
