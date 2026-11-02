"""Slash commands that change or report engine state: /sys, /temp, /length, /read."""

import math
import re
from pathlib import Path

from hyperflux.config import Config
from hyperflux.core.prompts import build_file_prompt


def handle_runtime_command(engine, user_input: str, quiet=False, token_callback=None):
    """Return a reply for a runtime command, or None if the input isn't one."""
    lowered = user_input.casefold()
    if lowered == "/sys":
        return _system_status(engine)
    think_match = re.fullmatch(r"/think(?:\s+(\S+))?", user_input.strip(), re.IGNORECASE)
    if think_match:
        return _set_thinking(engine, (think_match.group(1) or "").casefold())
    if lowered == "/thinking":
        if not engine.last_reasoning:
            return "The last answer had no thinking to show."
        return f"### Thinking for the last answer\n\n{engine.last_reasoning}"

    temperature_match = re.fullmatch(r"/temp(?:\s+(.*))?", user_input, re.IGNORECASE)
    if temperature_match:
        return _set_temperature(engine, (temperature_match.group(1) or "").strip())

    length_match = re.fullmatch(r"/length(?:\s+(.*))?", user_input, re.IGNORECASE)
    if length_match:
        return _set_max_length(engine, (length_match.group(1) or "").strip())

    if lowered == "/read" or lowered.startswith("/read "):
        return read_workspace_file(engine, user_input, quiet, token_callback)
    return None


def _system_status(engine):
    context_usage = (
        f"~{engine.last_context_tokens} / {engine.max_context_length} tokens "
        "(estimated)"
        if engine.last_context_tokens is not None
        else f"Not measured yet / {engine.max_context_length} tokens"
    )
    generation_speed = (
        f"~{engine.last_generation_tps:.1f} tokens/second (estimated)"
        if engine.last_generation_tps is not None
        else "Not measured yet"
    )
    return (
        "### HyperFlux system status\n\n"
        f"- **Model:** {engine.model_name}\n"
        f"- **Context usage:** {context_usage}\n"
        f"- **Last generation speed:** {generation_speed}\n"
        f"- **Temperature:** {engine.temperature:.2f}\n"
        f"- **Maximum output:** {engine.max_length} tokens\n"
        f"- **Session memory:** {len(engine.chat_history)} / "
        f"{Config.MAX_MEMORY_EXCHANGES} exchanges\n\n"
        "Context and speed are estimates based on text length; KoboldCPP "
        "does not provide exact token/cache metrics through this client."
    )


def _set_thinking(engine, value):
    if value in {"on", "off"}:
        engine.thinking_enabled = value == "on"
    elif value:
        return "Usage: /think on|off"
    else:
        engine.thinking_enabled = not engine.thinking_enabled
    if engine.thinking_enabled:
        return "Thinking is **on**: better answers to hard questions, but slower."
    return "Thinking is **off**: faster, direct answers."


def _set_temperature(engine, value):
    if not value:
        return f"Current temperature: {engine.temperature:.2f}. Usage: /temp <0-2>"
    try:
        temperature = float(value)
    except ValueError:
        return "Invalid temperature. Usage: /temp <0-2>"
    if not math.isfinite(temperature) or not (
        Config.MIN_TEMPERATURE <= temperature <= Config.MAX_TEMPERATURE
    ):
        return f"Temperature must be between {Config.MIN_TEMPERATURE:g} and {Config.MAX_TEMPERATURE:g}."
    engine.temperature = temperature
    return f"Temperature set to {engine.temperature:.2f}."


def _set_max_length(engine, value):
    usage = f"Usage: /length <1-{Config.MAX_MAX_LENGTH}>"
    if not value:
        return f"Current max output length: {engine.max_length}. {usage}"
    if not value.isdecimal():
        return f"Invalid output length. {usage}"
    max_length = int(value)
    if not Config.MIN_MAX_LENGTH <= max_length <= Config.MAX_MAX_LENGTH:
        return f"Output length must be between {Config.MIN_MAX_LENGTH} and {Config.MAX_MAX_LENGTH}."
    engine.max_length = max_length
    return f"Maximum output length set to {engine.max_length} tokens."


def read_workspace_file(engine, user_input: str, quiet=False, token_callback=None):
    """Handle `/read <path> [task]`: load a workspace file and ask the model about it."""
    match = re.fullmatch(
        r'/read\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))(?:\s+(.*))?',
        user_input,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return "Usage: /read <workspace-relative-path> [what you want me to do]"

    requested_path = Path(match.group(1) or match.group(2) or match.group(3))
    workspace_root = Config.WORKSPACE_ROOT.resolve()
    try:
        resolved_path = requested_path.resolve(strict=True) if requested_path.is_absolute() else (
            workspace_root / requested_path
        ).resolve(strict=True)
        resolved_path.relative_to(workspace_root)
    except (OSError, ValueError):
        return "File not found or path is outside the workspace."
    if not resolved_path.is_file():
        return "The requested workspace path is not a file."

    try:
        with resolved_path.open("r", encoding="utf-8") as source:
            file_content = source.read(Config.MAX_READ_FILE_CHARS + 1)
    except (OSError, UnicodeError) as error:
        return f"Could not read workspace file: {error}"

    truncated = len(file_content) > Config.MAX_READ_FILE_CHARS
    if truncated:
        file_content = file_content[:Config.MAX_READ_FILE_CHARS]
    relative_path = resolved_path.relative_to(workspace_root).as_posix()
    task = (match.group(4) or "").strip() or "Review and explain this file."
    file_prompt = build_file_prompt(task, relative_path, file_content, truncated)
    return engine.query_local_llm(file_prompt, quiet=quiet, token_callback=token_callback)
