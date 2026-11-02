import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from hyperflux.core.engine import HyperFluxEngine
from hyperflux.core.kobold import split_reasoning_summary, split_thinking
from hyperflux.core.math_solver import SafeMathSolver
from hyperflux.core.prompts import is_thinking_exempt
from hyperflux.search.bridge import create_search_bridge, load_or_create_token


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


class FakeNativeThinkingStreamResponse(FakeStreamResponse):
    @staticmethod
    def iter_lines(chunk_size, decode_unicode):
        yield 'data: {"token":"<|channel>thought\\nI need 6 times 7."}'
        yield 'data: {"token":"<channel|>"}'
        yield 'data: {"token":"The answer is 42."}'
        yield "data: [DONE]"


class FakeUnfinishedThinkingStreamResponse(FakeStreamResponse):
    @staticmethod
    def iter_lines(chunk_size, decode_unicode):
        yield 'data: {"token":"<|channel>thought\\nThis is a long problem..."}'
        yield "data: [DONE]"


TEST_TOKEN = "test-token"


class HyperFluxCoreTests(unittest.TestCase):
    def setUp(self):
        self.server = create_search_bridge(
            FakeSearchEngine(),
            host="127.0.0.1",
            port=0,
            result_count=2,
            log_token=TEST_TOKEN,
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
                f"{self.base_url}/kobold-logs?token={TEST_TOKEN}",
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
        response = requests.get(f"{self.base_url}/kobold-logs?token={TEST_TOKEN}", timeout=2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"available": False, "text": ""})

    def test_kobold_log_endpoint_requires_token(self):
        # A sandboxed iframe on any website sends Origin: null.
        for url in (f"{self.base_url}/kobold-logs", f"{self.base_url}/kobold-logs?token=wrong"):
            response = requests.get(url, headers={"Origin": "null"}, timeout=2)
            self.assertEqual(response.status_code, 403)

    def test_bridge_rejects_dns_rebinding_host(self):
        headers = {"Host": "evil.example:5002"}
        self.assertEqual(
            requests.get(f"{self.base_url}/kobold-logs?token={TEST_TOKEN}", headers=headers, timeout=2).status_code,
            403,
        )
        self.assertEqual(
            requests.post(f"{self.base_url}/search", json={"query": "x"}, headers=headers, timeout=2).status_code,
            403,
        )

    def test_bridge_token_is_created_once_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "bridge_token"
            first = load_or_create_token(path)
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(load_or_create_token(path), first)

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

    def test_default_prompt_uses_gemma4_native_thinking(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()) as post:
            engine.query_local_llm("Compare two approaches to this complex problem.", quiet=True)
        payload = post.call_args.kwargs["json"]
        prompt = payload["prompt"]
        self.assertTrue(prompt.startswith("<|turn>system\n<|think|>\n"))
        self.assertTrue(prompt.endswith("<|turn>user\nCompare two approaches to this complex problem.<turn|>\n<|turn>model\n"))
        self.assertIn("scale the depth of your thinking", prompt)
        self.assertNotIn("1-3 concise sentences", prompt)
        self.assertIn("<turn|>", payload["stop_sequence"])

    def test_name_question_prompt_skips_thinking(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()) as post:
            engine.query_local_llm("What's your name?", quiet=True)
        prompt = post.call_args.kwargs["json"]["prompt"]
        self.assertNotIn("<|think|>", prompt)
        self.assertIn("without a separate thinking section", prompt)

    def test_think_toggle_turns_native_thinking_off_and_on(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        self.assertIn("**off**", engine.handle_runtime_command("/think off"))
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()) as post:
            engine.query_local_llm("Solve this hard puzzle.", quiet=True)
        self.assertNotIn("<|think|>", post.call_args.kwargs["json"]["prompt"])
        self.assertIn("**on**", engine.handle_runtime_command("/think"))
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()) as post:
            engine.query_local_llm("Solve this hard puzzle.", quiet=True)
        self.assertIn("<|think|>", post.call_args.kwargs["json"]["prompt"])
        self.assertEqual(engine.handle_runtime_command("/think maybe"), "Usage: /think on|off")

    def test_history_fits_inside_context_minus_reply_room(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        engine.chat_history = [{"user": "q" * 4000, "assistant": "a" * 4000} for _ in range(10)]
        prompt = engine._build_context_prompt("system", "latest question")
        limit = (engine.max_context_length - engine.max_length) * 3
        self.assertLessEqual(len(prompt), limit)
        self.assertIn("latest question", prompt)
        self.assertIn("system", prompt)

    def test_thinking_is_kept_out_of_answer_and_memory(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch(
            "hyperflux.core.kobold.requests.post",
            return_value=FakeNativeThinkingStreamResponse(),
        ):
            response = engine.query_local_llm("What is the result?", quiet=True)
        self.assertEqual(response, "The answer is 42.")
        self.assertEqual(engine.chat_history[-1]["assistant"], "The answer is 42.")
        self.assertIn("6 times 7", engine.last_reasoning)
        self.assertIn("6 times 7", engine.handle_runtime_command("/thinking"))

    def test_stream_callback_receives_answer_only(self):
        partial = []
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch(
            "hyperflux.core.kobold.requests.post",
            return_value=FakeNativeThinkingStreamResponse(),
        ):
            engine.query_local_llm(
                "What is the result?",
                token_callback=partial.append,
                quiet=True,
            )
        self.assertTrue(partial)
        self.assertTrue(all("6 times 7" not in update and "<|channel>" not in update for update in partial))
        self.assertEqual(partial[-1], "The answer is 42.")

    def test_out_of_room_while_thinking_says_so(self):
        with patch.object(HyperFluxEngine, "_load_model_name"):
            engine = HyperFluxEngine()
        with patch(
            "hyperflux.core.kobold.requests.post",
            return_value=FakeUnfinishedThinkingStreamResponse(),
        ):
            response = engine.query_local_llm("Hard question", quiet=True)
        self.assertIn("ran out of room while thinking", response)

    def test_greetings_and_name_questions_skip_thinking_summary(self):
        self.assertTrue(is_thinking_exempt("Hello!"))
        self.assertTrue(is_thinking_exempt("Hi HyperFlux!"))
        self.assertTrue(is_thinking_exempt("Hey, what's your name?"))
        self.assertTrue(is_thinking_exempt("What is your name?"))
        self.assertTrue(is_thinking_exempt("Who are you?"))
        self.assertFalse(is_thinking_exempt("Hello, can you explain recursion?"))
        self.assertFalse(is_thinking_exempt("Please introduce yourself."))

    def test_thinking_parser_keeps_native_and_legacy_thoughts(self):
        thinking, answer, done = split_thinking(
            "<|channel>thought\nStep one.\nStep two.<channel|>The result is 42."
        )
        self.assertEqual((thinking, answer, done), ("Step one.\nStep two.", "The result is 42.", True))
        thinking, answer = split_reasoning_summary("<reasoning>I checked.</reasoning>Hi")
        self.assertEqual((thinking, answer), ("I checked.", "Hi"))

    def test_thinking_parser_hides_half_received_markers(self):
        self.assertEqual(split_thinking("<|chan"), ("", "", True))
        self.assertEqual(split_thinking("The answer is 42.<tu")[1], "The answer is 42.")
        self.assertEqual(split_thinking("Use a < b here")[1], "Use a < b here")

    def test_thinking_parser_reports_unfinished_thought(self):
        thinking, answer, done = split_thinking("<|channel>thought\nStill working")
        self.assertEqual((thinking, answer, done), ("Still working", "", False))

    def test_reasoning_parser_can_suppress_summary_for_exempt_prompts(self):
        summary, answer = split_reasoning_summary(
            "<reasoning>Unneeded summary.</reasoning>Hello!",
            allow_reasoning=False,
        )
        self.assertEqual(summary, "")
        self.assertEqual(answer, "Hello!")


if __name__ == "__main__":
    unittest.main()
