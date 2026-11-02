import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from hyperflux.core.engine import HyperFluxEngine
from hyperflux.core.kobold import split_reasoning_summary
from hyperflux.core.math_solver import SafeMathSolver
from hyperflux.core.prompts import is_thinking_exempt
from hyperflux.search.bridge import create_search_bridge


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


class FakeReasoningStreamResponse(FakeStreamResponse):
    @staticmethod
    def iter_lines(chunk_size, decode_unicode):
        yield 'data: {"token":"<reasoning>I checked the result.</reasoning>"}'
        yield 'data: {"token":"The answer is 42."}'
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

    def test_kobold_log_endpoint_returns_current_log_text(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "kobold.log"
            log_path.write_text("model loaded\nprompt processed\n", encoding="utf-8")
            self.server.RequestHandlerClass.kobold_log_path = log_path

            response = requests.get(
                f"{self.base_url}/kobold-logs",
                headers={"Origin": "null"},
                timeout=2,
            )

            result = response.json()
            result["text"] = result["text"].replace("\r\n", "\n")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(result, {"available": True, "text": "model loaded\nprompt processed\n"})

    def test_kobold_log_endpoint_rejects_untrusted_origin(self):
        response = requests.get(
            f"{self.base_url}/kobold-logs",
            headers={"Origin": "https://example.com"},
            timeout=2,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Origin not allowed.")

    def test_kobold_log_endpoint_reports_missing_log(self):
        self.server.RequestHandlerClass.kobold_log_path = Path(
            tempfile.gettempdir()
        ) / "hyperflux-missing-kobold.log"
        response = requests.get(f"{self.base_url}/kobold-logs", timeout=2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"available": False, "text": ""})

    def test_safe_math_solver(self):
        self.assertEqual(SafeMathSolver.solve("2 + 3 * 4"), "Calculated value: **14**")
        self.assertIsNone(SafeMathSolver.solve("__import__('os').system('whoami')"))

    def test_quiet_generation_streams_partial_text_without_rich_ui(self):
        partial = []
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()):
            response = engine.query_local_llm("test prompt", token_callback=partial.append, quiet=True)
        self.assertEqual(response, "Hello")
        self.assertEqual(partial, ["Hello"])
        self.assertEqual(engine.chat_history[-1]["user"], "test prompt")
        self.assertFalse(engine.response_rendered_live)

    def test_custom_system_instruction_replaces_default_prompt(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        engine.system_instruction = "Desktop-specific instructions."
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()) as post:
            engine.query_local_llm("test prompt", quiet=True)
        prompt = post.call_args.kwargs["json"]["prompt"]
        self.assertIn("Desktop-specific instructions.", prompt)
        self.assertNotIn("This terminal interface", prompt)

    def test_default_prompt_guides_careful_reasoning_without_exposing_chain_of_thought(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()) as post:
            engine.query_local_llm("Compare two approaches to this complex problem.", quiet=True)
        prompt = post.call_args.kwargs["json"]["prompt"]
        self.assertIn("reason carefully before answering", prompt)
        self.assertIn("not private chain-of-thought", prompt)
        self.assertIn("<reasoning>...</reasoning>", prompt)

    def test_name_question_prompt_skips_reasoning_summary(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()) as post:
            engine.query_local_llm("What's your name?", quiet=True)
        prompt = post.call_args.kwargs["json"]["prompt"]
        self.assertIn("without a reasoning summary", prompt)
        self.assertNotIn("Thinking mode is enabled.", prompt)

    def test_model_summary_is_shown_but_not_added_to_chat_memory(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch(
            "hyperflux.core.kobold.requests.post",
            return_value=FakeReasoningStreamResponse(),
        ):
            response = engine.query_local_llm("What is the result?", quiet=True)
        self.assertIn("Thinking summary", response)
        self.assertIn("I checked the result.", response)
        self.assertIn("The answer is 42.", response)
        self.assertEqual(engine.chat_history[-1]["assistant"], "The answer is 42.")

    def test_stream_callback_receives_summary_without_hidden_thought(self):
        partial = []
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch(
            "hyperflux.core.kobold.requests.post",
            return_value=FakeReasoningStreamResponse(),
        ):
            engine.query_local_llm(
                "What is the result?",
                token_callback=partial.append,
                quiet=True,
            )
        self.assertTrue(partial)
        self.assertTrue(all("<reasoning>" not in update for update in partial))
        self.assertIn("I checked the result.", partial[-1])
        self.assertIn("The answer is 42.", partial[-1])

    def test_greetings_and_name_questions_skip_thinking_summary(self):
        self.assertTrue(is_thinking_exempt("Hello!"))
        self.assertTrue(is_thinking_exempt("Hi HyperFlux!"))
        self.assertTrue(is_thinking_exempt("Hey, what's your name?"))
        self.assertTrue(is_thinking_exempt("What is your name?"))
        self.assertTrue(is_thinking_exempt("Who are you?"))
        self.assertFalse(is_thinking_exempt("Hello, can you explain recursion?"))
        self.assertFalse(is_thinking_exempt("Please introduce yourself."))

    def test_reasoning_parser_discards_native_thought_and_keeps_summary(self):
        summary, answer = split_reasoning_summary(
            "<think>private scratch work</think>"
            "<reasoning>I checked the two cases.</reasoning>"
            "The result is 42."
        )
        self.assertEqual(summary, "I checked the two cases.")
        self.assertEqual(answer, "The result is 42.")

    def test_reasoning_parser_can_suppress_summary_for_exempt_prompts(self):
        summary, answer = split_reasoning_summary(
            "<reasoning>Unneeded summary.</reasoning>Hello!",
            allow_reasoning=False,
        )
        self.assertEqual(summary, "")
        self.assertEqual(answer, "Hello!")


if __name__ == "__main__":
    unittest.main()
