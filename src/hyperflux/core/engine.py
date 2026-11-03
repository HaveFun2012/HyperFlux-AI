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
from hyperflux.core.formatting import repair_collapsed_tables
from hyperflux.core.math_solver import SafeMathSolver
from hyperflux.core.models import DEFAULT_MODEL, reply_budget
from hyperflux.core.prompts import (
    MATH_INSTRUCTIONS,
    build_capabilities,
    build_search_prompt,
    build_system_instruction,
    build_gemma4_prompt,
    build_thinking_instruction,
    wants_thinking,
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
        self.last_reasoning = ""
        self.last_thought_seconds = None
        # Toggled with /think on|off. On = better on hard questions, but slower.
        self.thinking_enabled = True
        # Flash 1 / Apex 1 / Horizon 1; switched with /model.
        self.model_id = DEFAULT_MODEL
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
        """Ask KoboldCpp for the loaded model's name and its context size."""
        model_name = kobold.fetch_model_name()
        if model_name:
            self.model_name = model_name
        # Never ask for more context than KoboldCpp was started with; otherwise it
        # silently trims the start of the prompt (the instructions).
        server_context = kobold.fetch_max_context()
        if server_context:
            self.max_context_length = min(self.max_context_length, server_context)

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

    def reply_budget(self):
        """Reply tokens for the active model (Flash is capped, Horizon gets more room)."""
        return reply_budget(self.model_id, self.max_length, self.max_context_length)

    def _build_context_prompt(self, system_instruction, user_prompt, thinking=True):
        """Gemma 4 prompt with as much recent history as fits.

        KoboldCpp reserves max_length tokens of the context for the reply (thinking
        included), so the prompt only gets what's left.
        """
        prompt_tokens = max(512, self.max_context_length - self.reply_budget())
        return build_gemma4_prompt(
            system_instruction,
            [(exchange["user"], exchange["assistant"]) for exchange in self.chat_history],
            user_prompt,
            thinking,
            prompt_tokens * Config.ESTIMATED_CHARS_PER_TOKEN,
        )

    def query_local_llm(
        self,
        user_prompt,
        search_fallback: str | None = None,
        token_callback=None,
        quiet=False,
    ):
        """Generate a reply. token_callback receives the answer so far (never the thinking)."""
        system_instruction = self.system_instruction or build_system_instruction(
            self.get_capabilities(), self.model_id
        )
        thinking_enabled = wants_thinking(user_prompt, self.thinking_enabled, self.model_id)
        system_instruction += "\n\n" + build_thinking_instruction(
            user_prompt, self.thinking_enabled, self.model_id
        )
        full_context_prompt = self._build_context_prompt(
            system_instruction, user_prompt, thinking_enabled
        )
        self.last_context_tokens = math.ceil(
            len(full_context_prompt) / Config.ESTIMATED_CHARS_PER_TOKEN
        )
        payload = {
            "prompt": full_context_prompt,
            "max_context_length": self.max_context_length,
            "max_length": self.reply_budget(),
            "temperature": self.temperature,
            "top_p": 0.95,
            "rep_penalty": 1.05,
            "stop_sequence": ["<turn|>", "<|turn>"],
        }

        try:
            generation_started = time.perf_counter()
            thought_seconds = None
            if not quiet:
                console.print()
            live_context = nullcontext(None) if quiet else Live(
                UI.assistant_panel("", "Thinking..."),
                console=console,
                refresh_per_second=8,
                transient=False,
            )
            with live_context as live:
                collected = []

                def on_token(token):
                    nonlocal thought_seconds
                    collected.append(token)
                    partial_response = "".join(collected)
                    thinking, answer, thinking_done = kobold.split_thinking(partial_response)
                    if not thinking_enabled:
                        thinking = ""
                    if thinking and thinking_done and thought_seconds is None:
                        thought_seconds = time.perf_counter() - generation_started
                    if token_callback is not None and (answer or thinking_done):
                        token_callback(answer)
                    if live is None:
                        return
                    if thinking and not thinking_done:
                        elapsed = time.perf_counter() - generation_started
                        live.update(
                            UI.assistant_panel("", f"Thinking... {elapsed:.0f}s", thinking),
                            refresh=True,
                        )
                    else:
                        live.update(
                            UI.assistant_panel(
                                repair_collapsed_tables(answer), _thought_label(thought_seconds)
                            ),
                            refresh=True,
                        )

                # If KoboldCpp stops because the reply reached max_length, send the text
                # so far back and let the model carry on, so long replies aren't cut off.
                streamed = False
                continuations = 0
                round_payload = payload
                while True:
                    text, finish_reason = kobold.stream_generate(round_payload, on_token)
                    if text is None:
                        if live is not None:
                            live.update(UI.assistant_panel("", "Generating response..."), refresh=True)
                        text, finish_reason = kobold.generate(round_payload)
                        collected.append(text)
                    else:
                        streamed = True
                    if finish_reason != "length" or continuations >= Config.MAX_AUTO_CONTINUE:
                        break
                    so_far = full_context_prompt + "".join(collected)
                    room = (
                        self.max_context_length
                        - math.ceil(len(so_far) / Config.ESTIMATED_CHARS_PER_TOKEN)
                        - 64
                    )
                    if room < 256:
                        finish_reason = "context"
                        break
                    continuations += 1
                    round_payload = {**payload, "prompt": so_far, "max_length": min(self.reply_budget(), room)}
                response_text = "".join(collected)

                reasoning, response_text = kobold.split_reasoning_summary(
                    response_text,
                    thinking_enabled,
                )
                response_text = repair_collapsed_tables(kobold.clean_response(response_text))
                elapsed = time.perf_counter() - generation_started
                if reasoning and thought_seconds is None:
                    thought_seconds = elapsed
                self.last_reasoning = reasoning
                self.last_thought_seconds = thought_seconds if reasoning else None
                generated_tokens_estimate = math.ceil(
                    (len(reasoning) + len(response_text)) / Config.ESTIMATED_CHARS_PER_TOKEN
                )
                self.last_generation_tps = (
                    generated_tokens_estimate / elapsed if elapsed > 0 else 0.0
                )
                if response_text and finish_reason in {"length", "context"}:
                    response_text += (
                        "\n\n_This reply filled the context window. Type \"continue\" for the rest._"
                        if finish_reason == "context"
                        else "\n\n_This reply was very long, so it was paused. Type \"continue\" for the rest._"
                    )
                elif response_text and finish_reason == "error":
                    response_text += "\n\n_KoboldCpp reported an error, so this reply may be incomplete._"
                if not response_text and reasoning:
                    response_text = (
                        "_The reply ran out of room while thinking. Raise the limit with "
                        "`/length`, or ask again._"
                    )
                if search_fallback and _PRINTED_TOOL_CALL.search(response_text):
                    response_text = (
                        "I couldn't summarize the results, so here are the search "
                        f"snippets directly:\n\n{search_fallback}"
                    )
                if token_callback is not None and not streamed:
                    token_callback(response_text)
                if live is not None:
                    live.update(
                        UI.assistant_panel(response_text, _thought_label(self.last_thought_seconds)),
                        refresh=True,
                    )
            self.response_rendered_live = live is not None
            self._remember_exchange(user_prompt, response_text)
            return response_text
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


def _thought_label(seconds):
    """Collapsed thinking line shown above the answer, like "Thought for 12s"."""
    if seconds is None:
        return ""
    return f"✻ Thought for {seconds:.0f}s · /thinking to view"
