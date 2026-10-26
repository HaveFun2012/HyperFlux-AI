import threading
import unittest
from unittest.mock import patch

import requests

from hyperflux_interacter import HyperFluxEngine, SafeMathSolver
from hyperflux_server import create_search_bridge


class FakeSearchEngine:
    @staticmethod
    def optimize_search_query(query):
        return query.strip()

    @staticmethod
    def search_web(query, result_count):
        return f"results for {query} ({result_count})"


class FakeStreamResponse:
    status_code = 200
    encoding = "utf-8"

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        return False

    @staticmethod
    def raise_for_status():
        return None

    @staticmethod
    def iter_lines(chunk_size, decode_unicode):
        yield 'data: {"token":"Hello"}'
        yield "data: [DONE]"


class HyperFluxCoreTests(unittest.TestCase):
    def setUp(self):
        self.server = create_search_bridge(
            FakeSearchEngine(),
            host="127.0.0.1",
            port=0,
            result_count=2,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_health_endpoint(self):
        response = requests.get(f"{self.base_url}/health", timeout=2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["service"], "HyperFlux search")

    def test_search_endpoint_returns_engine_results(self):
        response = requests.post(
            f"{self.base_url}/search",
            json={"query": "  local search  "},
            timeout=2,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["query"], "local search")
        self.assertEqual(response.json()["results"], "results for local search (2)")

    def test_search_rejects_untrusted_origin(self):
        response = requests.post(
            f"{self.base_url}/search",
            json={"query": "search"},
            headers={"Origin": "https://example.com"},
            timeout=2,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Origin not allowed.")

    def test_safe_math_solver(self):
        self.assertEqual(SafeMathSolver.solve("2 + 3 * 4"), "Calculated value: **14**")
        self.assertIsNone(SafeMathSolver.solve("__import__('os').system('whoami')"))

    def test_quiet_generation_streams_partial_text_without_rich_ui(self):
        partial = []
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch("hyperflux_interacter.requests.post", return_value=FakeStreamResponse()):
            response = engine.query_local_llm("test prompt", token_callback=partial.append, quiet=True)
        self.assertEqual(response, "Hello")
        self.assertEqual(partial, ["Hello"])
        self.assertEqual(engine.chat_history[-1]["user"], "test prompt")
        self.assertFalse(engine.response_rendered_live)


if __name__ == "__main__":
    unittest.main()
