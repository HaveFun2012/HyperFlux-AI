"""HyperFluxEngine: holds chat state and routes each message to the right handler."""

import json
import math
import re
import time
from contextlib import nullcontext
from pathlib import Path

import requests
from rich.live import Live
from rich.text import Text

from hyperflux.config import Config
from hyperflux.core import kobold, routing
from hyperflux.core.commands import handle_runtime_command
from hyperflux.core.math_solver import SafeMathSolver
from hyperflux.core.prompts import (
    MATH_INSTRUCTIONS,
    build_capabilities,
    build_search_prompt,
    build_system_instruction,
    build_thinking_instruction,
    is_thinking_exempt,
)
from hyperflux.search import text as search_text
from hyperflux.search.web_search import search_web as run_web_search
# The terminal panel is drawn while tokens stream in (skipped when quiet=True).
from hyperflux.terminal.ui import UI, console

_PRINTED_TOOL_CALL = re.compile(
    r"\b(?:google_search|web_search|browser_search)\s*\.\s*(?:search|query|run)\s*\(",
    re.IGNORECASE,
)


class HyperFluxEngine:
    def __init__(self):
        self.math_solver = SafeMathSolver()
        self.local_brain = {}
        self.chat_history = []
        self.response_rendered_live = False
        self.temperature = Config.DEFAULT_TEMPERATURE
        self.max_length = Config.DEFAULT_MAX_LENGTH
        self.max_context_length = Config.MAX_CONTEXT_LENGTH
        self.system_instruction = None
        self.model_name = self._configured_model_name()
        self.last_context_tokens = None
        self.last_generation_tps = None
        self._load_model_name()
        self._load_local_brain()

    # ----- setup -------------------------------------------------------------

    @staticmethod
    def _configured_model_name():
        """Read the --model argument from the server launcher script."""
        launcher = Config.LAUNCHER_PATH
        if not launcher.exists():
            return "Unknown model"
        launcher_text = launcher.read_text(encoding="utf-8")
        match = re.search(r'--model\s+(?:"([^"]+)"|([^\s]+))', launcher_text, re.IGNORECASE)
        if not match:
            return "Unknown model"
        configured_path = match.group(1) or match.group(2)
        return Path(configured_path.replace("\\", "/")).name

    def _load_model_name(self):
        model_name = kobold.fetch_model_name()
        if model_name:
            self.model_name = model_name

    def _load_local_brain(self):
        if Config.BRAIN_PATH.exists():
            try:
                with open(Config.BRAIN_PATH, "r", encoding="utf-8") as f:
                    self.local_brain = json.load(f)
            except Exception:
                pass

    # ----- public helpers used by the search bridge and prompts --------------

    optimize_search_query = staticmethod(search_text.optimize_search_query)

    @staticmethod
    def search_web(query: str, max_results=3) -> str:
        return run_web_search(query, max_results)

    def get_capabilities(self):
        return build_capabilities(self.model_name)

    def handle_runtime_command(self, user_input: str, quiet=False, token_callback=None):
        return handle_runtime_command(self, user_input, quiet, token_callback)

    # ----- model calls -------------------------------------------------------

    def _remember_exchange(self, user_input, response):
        self.chat_history.append({"user": user_input, "assistant": response})
        if len(self.chat_history) > Config.MAX_MEMORY_EXCHANGES:
            self.chat_history.pop(0)

    def _build_context_prompt(self, system_instruction, user_prompt):
        """Gemma-format prompt: as much recent history as fits, then the current turn."""
        current_turn = (
            f"<start_of_turn>user\n{system_instruction}\n\n"
            f"{user_prompt}<end_of_turn>\n<start_of_turn>model\n"
        )
        history_budget = max(
            0,
            self.max_context_length * Config.ESTIMATED_CHARS_PER_TOKEN - len(current_turn),
        )
        recent_history = []
        used_history_chars = 0
        for exchange in reversed(self.chat_history):
            formatted_exchange = (
                f"<start_of_turn>user\n{exchange['user']}<end_of_turn>\n"
                f"<start_of_turn>model\n{exchange['assistant']}<end_of_turn>\n"
            )
            if used_history_chars + len(formatted_exchange) > history_budget:
                break
            recent_history.append(formatted_exchange)
            used_history_chars += len(formatted_exchange)
        return "".join(reversed(recent_history)) + current_turn

    def query_local_llm(
        self,
        user_prompt,
        search_fallback: str | None = None,
        token_callback=None,
        quiet=False,
    ):
        system_instruction = self.system_instruction or build_system_instruction(
            self.get_capabilities()
        )
        allow_reasoning = not is_thinking_exempt(user_prompt)
        system_instruction += "\n\n" + build_thinking_instruction(user_prompt)
        full_context_prompt = self._build_context_prompt(system_instruction, user_prompt)
        self.last_context_tokens = math.ceil(
            len(full_context_prompt) / Config.ESTIMATED_CHARS_PER_TOKEN
        )
        payload = {
            "prompt": full_context_prompt,
            "max_context_length": self.max_context_length,
            "max_length": self.max_length,
            "temperature": self.temperature,
            "top_p": 0.90,
            "rep_penalty": 1.15,
            "stop_sequence": ["<end_of_turn>", "<start_of_turn>"],
        }

        try:
            generation_started = time.perf_counter()
            if not quiet:
                console.print()
            live_context = nullcontext(None) if quiet else Live(
                UI.assistant_panel("", "Thinking..."),
                console=console,
                refresh_per_second=8,
                transient=False,
            )
            with live_context as live:
                def on_token(partial_response):
                    reasoning, answer = kobold.split_reasoning_summary(
                        partial_response,
                        allow_reasoning,
                    )
                    visible_response = _format_reasoning_response(reasoning, answer)
                    if token_callback is not None:
                        token_callback(visible_response)
                    if live is not None:
                        live.update(UI.assistant_panel(visible_response), refresh=True)

                response_text = kobold.stream_generate(payload, on_token)
                streamed = response_text is not None
                if not streamed:
                    if live is not None:
                        live.update(UI.assistant_panel("", "Generating response..."), refresh=True)
                    response_text = kobold.generate(payload)

                response_text = kobold.clean_response(response_text)
                reasoning, response_text = kobold.split_reasoning_summary(
                    response_text,
                    allow_reasoning,
                )
                elapsed = time.perf_counter() - generation_started
                generated_tokens_estimate = math.ceil(
                    len(response_text) / Config.ESTIMATED_CHARS_PER_TOKEN
                )
                self.last_generation_tps = (
                    generated_tokens_estimate / elapsed if elapsed > 0 else 0.0
                )
                if search_fallback and _PRINTED_TOOL_CALL.search(response_text):
                    response_text = (
                        "I couldn't summarize the results, so here are the search "
                        f"snippets directly:\n\n{search_fallback}"
                    )
                if token_callback is not None and not streamed:
                    token_callback(_format_reasoning_response(reasoning, response_text))
                if live is not None:
                    live.update(
                        UI.assistant_panel(
                            _format_reasoning_response(reasoning, response_text)
                        ),
                        refresh=True,
                    )
            self.response_rendered_live = live is not None
            self._remember_exchange(user_prompt, response_text)
            return _format_reasoning_response(reasoning, response_text)
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            return f"[error]Pipeline Error: {str(e)}[/error]"

    # ----- message routing ---------------------------------------------------

    def process_chat(self, user_input, quiet=False, token_callback=None):
        self.response_rendered_live = False
        low_input = user_input.lower().strip()

        command_response = self.handle_runtime_command(user_input.strip(), quiet, token_callback)
        if command_response is not None:
            return command_response

        # 1. Current-events questions: search first, then let the model answer.
        if routing.is_search_intent(low_input):
            return self._answer_with_search(user_input, quiet, token_callback)

        # 2. Plain arithmetic is solved locally.
        if routing.looks_like_arithmetic(low_input):
            solved = self.math_solver.solve(user_input)
            if solved:
                return solved

        # 3. Canned answers from the local brain file.
        brain_answer = routing.brain_lookup(self.local_brain, low_input)
        if brain_answer is not None:
            return brain_answer

        # 4. Everything else goes to the model.
        final_prompt = user_input
        if routing.is_math_request(low_input):
            final_prompt += MATH_INSTRUCTIONS
        return self.query_local_llm(final_prompt, token_callback=token_callback, quiet=quiet)

    def _answer_with_search(self, user_input, quiet, token_callback):
        query = self.optimize_search_query(user_input)
        search_status = nullcontext() if quiet else console.status(
            Text(f"Searching the web: {query[:70]}", style="brand"),
            spinner="dots",
            spinner_style="brand",
        )
        with search_status:
            web_data = self.search_web(query, Config.SEARCH_RESULT_COUNT)
        if web_data.startswith("SEARCH ERROR:"):
            return f"[error]{web_data}[/error]"
        return self.query_local_llm(
            build_search_prompt(user_input, web_data),
            search_fallback=web_data,
            token_callback=token_callback,
            quiet=quiet,
        )


def _format_reasoning_response(reasoning, answer):
    if not reasoning:
        return answer
    return f"**Thinking summary**\n\n{reasoning}\n\n{answer}"
