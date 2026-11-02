"""Import settings and chats saved by older desktop versions into the web interface."""

import json
import re

from hyperflux.paths import user_data_directory

OLD_DEFAULT_ACCENT = "#00b4d8"


def _read_legacy_settings(path):
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as source:
        settings = json.load(source)
    if not isinstance(settings, dict):
        raise ValueError("Saved desktop settings must be a JSON object.")

    migrated = {}
    if "temperature" in settings or "max_length" in settings or "context_length" in settings:
        model_settings = {}
        if "temperature" in settings:
            model_settings["temperature"] = settings["temperature"]
        if "max_length" in settings:
            model_settings["maxLength"] = settings["max_length"]
        if "context_length" in settings:
            model_settings["contextLength"] = settings["context_length"]
        migrated["hfx_model_settings"] = model_settings

    if settings.get("appearance") in ("dark", "light"):
        migrated["hfx_theme"] = (
            "theme-light" if settings["appearance"] == "light" else "theme-default"
        )

    personalization = {}
    if isinstance(settings.get("display_name"), str):
        personalization["displayName"] = settings["display_name"][:32]
    # The old app always saved its default #00b4d8; importing it locked every theme
    # to cyan, so only import a colour the user actually changed.
    if (
        isinstance(settings.get("accent_color"), str)
        and re.fullmatch(r"#[0-9a-fA-F]{6}", settings["accent_color"])
        and settings["accent_color"].lower() != OLD_DEFAULT_ACCENT
    ):
        personalization["accentColor"] = settings["accent_color"]
    if settings.get("text_size") in ("small", "medium", "large"):
        personalization["textSize"] = settings["text_size"]
    if personalization:
        migrated["hfx_personalization"] = personalization
    return migrated


def _read_legacy_sessions(path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as source:
        sessions = json.load(source)
    if not isinstance(sessions, list):
        raise ValueError("Saved desktop chat history must be a JSON array.")

    migrated = []
    for session in sessions:
        if not isinstance(session, dict) or not isinstance(session.get("messages"), list):
            continue
        messages = []
        for message in session["messages"]:
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                continue
            role = message.get("role")
            if role not in {"user", "assistant", "ai"}:
                continue
            migrated_message = {
                "role": "ai" if role == "assistant" else role,
                "content": message["content"],
            }
            if message.get("runtime"):
                migrated_message["runtime"] = True
            if isinstance(message.get("attachment"), dict):
                migrated_message["attachment"] = message["attachment"]
            messages.append(migrated_message)
        migrated.append({
            "id": session.get("id") if isinstance(session.get("id"), str) else "",
            "title": session.get("title") if isinstance(session.get("title"), str) else "New chat",
            "messages": messages,
        })
    return migrated


def migration_script():
    """JavaScript that copies legacy data into localStorage, or None if there is none."""
    app_data = user_data_directory()
    settings = _read_legacy_settings(app_data / "settings.json")
    sessions = _read_legacy_sessions(app_data / "sessions.json")
    if sessions is not None:
        settings["hfx_sessions"] = sessions
    if not settings:
        return None

    encoded_settings = json.dumps(settings, ensure_ascii=True)
    encoded_settings = encoded_settings.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"""
(() => {{
  const migrated = {encoded_settings};
  for (const [key, value] of Object.entries(migrated)) {{
    if (localStorage.getItem(key) === null) {{
      localStorage.setItem(key, JSON.stringify(value));
    }}
  }}
}})();
"""
