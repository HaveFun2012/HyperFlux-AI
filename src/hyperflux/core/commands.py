"""Slash commands that change or report engine state: /sys, /temp, /length, /read,
/persona, /instructions, /export."""

import math
import re
from datetime import datetime
from pathlib import Path

from hyperflux import paths
from hyperflux.config import Config
from hyperflux.core.models import MAX_CUSTOM_INSTRUCTIONS, MODELS, PERSONAS, get_model
from hyperflux.core.prompts import build_file_prompt


def handle_runtime_command(engine, user_input: str, quiet=False, token_callback=None):
    """Return a reply for a runtime command, or None if the input isn't one."""
    lowered = user_input.casefold()
    if lowered == "/sys":
        return _system_status(engine)
    model_match = re.fullmatch(r"/model(?:\s+(\S+))?", user_input.strip(), re.IGNORECASE)
    if model_match:
        return _set_model(engine, (model_match.group(1) or "").casefold())
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

    persona_match = re.fullmatch(r"/persona(?:\s+(\S+))?", user_input.strip(), re.IGNORECASE)
    if persona_match:
        return _set_persona(engine, (persona_match.group(1) or "").casefold())
    instructions_match = re.fullmatch(r"/instructions(?:\s+(.*))?", user_input.strip(), re.IGNORECASE | re.DOTALL)
    if instructions_match:
        return _set_instructions(engine, (instructions_match.group(1) or "").strip())
    if lowered == "/export":
        return export_chat(engine)

    if lowered == "/read" or lowered.startswith("/read "):
        return read_workspace_file(engine, user_input, quiet, token_callback)
    return None


def _set_persona(engine, value):
    if value:
        if value not in PERSONAS:
            return f"Unknown persona. Usage: /persona {' | '.join(PERSONAS)}"
        engine.persona = value
        saved = engine.save_terminal_settings()
        note = "" if saved else " (It couldn't be saved, so it lasts until you close the app.)"
        return f"Persona set to **{PERSONAS[value]['name']}**: {PERSONAS[value]['description']}{note}"
    lines = [f"Active persona: **{PERSONAS[engine.persona]['name']}**.", ""]
    lines += [f"- `/persona {key}`: {p['description']}" for key, p in PERSONAS.items()]
    return "\n".join(lines)


def _set_instructions(engine, value):
    if not value:
        if not engine.custom_instructions:
            return ("No custom instructions are set. Add some with `/instructions <text>`, "
                    "for example: `/instructions I'm a student in Malaysia; keep answers simple`.")
        return (f"### Your custom instructions\n\n{engine.custom_instructions}\n\n"
                "Change them with `/instructions <text>`, or remove them with `/instructions clear`.")
    if value.casefold() == "clear":
        engine.custom_instructions = ""
        engine.save_terminal_settings()
        return "Custom instructions removed."
    engine.custom_instructions = value[:MAX_CUSTOM_INSTRUCTIONS]
    saved = engine.save_terminal_settings()
    cut = " (shortened to the first 1,500 characters)" if len(value) > MAX_CUSTOM_INSTRUCTIONS else ""
    note = "" if saved else " They couldn't be saved, so they last until you close the app."
    return f"Custom instructions saved{cut}. HyperFlux will follow them in every answer.{note}"


def export_chat(engine, folder=None, now=None):
    """Save this session's conversation as a Markdown file. Returns a reply."""
    if not engine.chat_history:
        return "There is nothing to export yet: this session has no messages."
    now = now or datetime.now()
    folder = Path(folder or paths.EXPORT_DIR)
    lines = ["# HyperFlux chat", "", f"Exported {now:%A, %d %B %Y at %H:%M}", ""]
    for exchange in engine.chat_history:
        lines += ["## You", "", exchange["user"], "", "## HyperFlux", "", exchange["assistant"], ""]
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"HyperFlux chat {now:%Y-%m-%d %H%M%S}.md"
        target.write_text("\n".join(lines), encoding="utf-8")
    except OSError as error:
        return f"Could not export the chat: {error}"
    return f"Chat exported to `{target}`."


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
        f"- **HyperFlux model:** {get_model(engine.model_id)['name']}\n"
        f"- **Persona:** {PERSONAS[engine.persona]['name']}\n"
        f"- **Custom instructions:** {'set' if engine.custom_instructions else 'none'}\n"
        f"- **Loaded model file:** {engine.model_name}\n"
        f"- **Context usage:** {context_usage}\n"
        f"- **Last generation speed:** {generation_speed}\n"
        f"- **Temperature:** {engine.temperature:.2f}\n"
        f"- **Maximum output:** {engine.max_length} tokens\n"
        f"- **Session memory:** {len(engine.chat_history)} / "
        f"{Config.MAX_MEMORY_EXCHANGES} exchanges\n\n"
        "Context and speed are estimates based on text length; KoboldCPP "
        "does not provide exact token/cache metrics through this client."
    )


def _set_model(engine, value):
    choices = " | ".join(MODELS)
    if value:
        if value not in MODELS:
            return f"Unknown model. Usage: /model {choices}"
        engine.model_id = value
    model = get_model(engine.model_id)
    lines = [f"Active model: **{model['name']}**. {model['purpose']}", ""]
    lines += [f"- `/model {key}`: {m['short']}. {m['purpose']}" for key, m in MODELS.items()]
    return "\n".join(lines)


def _set_thinking(engine, value):
    locked = get_model(engine.model_id)["thinking"]
    if locked != "toggle":
        state = "never thinks" if locked == "never" else "always thinks"
        return f"{get_model(engine.model_id)['short']} {state}. Use `/model apex` to choose with /think."
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
