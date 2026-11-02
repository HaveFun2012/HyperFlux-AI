"""HTTP client for the local KoboldCpp text-generation API."""

import json
import re

import requests

from hyperflux.config import Config

STREAM_URL = (
    Config.KOBOLD_API_URL.rsplit("/api/v1/generate", 1)[0] + "/api/extra/generate/stream"
)


def stream_generate(payload, on_token):
    """Stream a generation, calling on_token(partial_text) as tokens arrive.

    Returns the full text, or None if streaming is unsupported or produced nothing.
    """
    tokens = []
    with requests.post(
        STREAM_URL,
        json=payload,
        headers={"Accept": "text/event-stream"},
        timeout=(10, 120),
        stream=True,
    ) as response:
        if response.status_code in {404, 405, 501}:
            return None
        response.raise_for_status()
        response.encoding = "utf-8"
        for line in response.iter_lines(chunk_size=1, decode_unicode=True):
            if not isinstance(line, str) or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError as error:
                raise ValueError("KoboldCPP returned malformed streaming data.") from error
            if not isinstance(event, dict):
                raise ValueError("KoboldCPP returned an invalid streaming event.")
            token = event.get("token")
            if isinstance(token, str) and token:
                tokens.append(token)
                on_token("".join(tokens))
    return "".join(tokens) if tokens else None


def generate(payload):
    """Non-streaming generation; used when streaming isn't available."""
    response = requests.post(Config.KOBOLD_API_URL, json=payload, timeout=120)
    response.raise_for_status()
    json_data = response.json()
    if "results" in json_data and isinstance(json_data["results"], list) and json_data["results"]:
        return json_data["results"][0].get("text", "").strip()
    return json_data.get("text", str(json_data)).strip()


def fetch_model_name():
    """Return the loaded model's file name, or None if KoboldCpp doesn't report a real one."""
    try:
        response = requests.get(Config.KOBOLD_MODEL_URL, timeout=5)
        response.raise_for_status()
        model_info = response.json()
    except (requests.exceptions.RequestException, ValueError):
        return None
    model_name = model_info.get("result") if isinstance(model_info, dict) else None
    if not isinstance(model_name, str) or not model_name.strip():
        return None
    model_name = model_name.strip()
    if model_name.casefold().strip("/") in {"model", "koboldcpp/model"}:
        return None
    return model_name.replace("\\", "/").rsplit("/", 1)[-1]


def clean_response(text):
    """Strip turn markers and speaker labels the model sometimes echoes."""
    text = text.replace("<end_of_turn>", "").replace("<turn|>", "").strip()
    return re.sub(
        r'^(?:Copilot|Assistant|HyperFlux|Qwen):\s*',
        '',
        text,
        flags=re.IGNORECASE,
    )


# Gemma 4 native thoughts first, then older tag styles some models emit.
_THOUGHT_BLOCKS = (
    re.compile(r"<\|channel>(?:thought)?\s*([\s\S]*?)(<channel\|>|$)"),
    re.compile(r"<think(?:ing)?\b[^>]*>([\s\S]*?)(</think(?:ing)?>|$)", re.IGNORECASE),
    re.compile(r"<reasoning\b[^>]*>([\s\S]*?)(</reasoning\s*>|$)", re.IGNORECASE),
)
_STRAY_MARKERS = re.compile(
    r"<\|channel>|<channel\|>|</?think(?:ing)?\b[^>]*>|</?reasoning\b[^>]*>",
    re.IGNORECASE,
)


def split_thinking(text):
    """Split model output into (thinking, answer, thinking_done).

    thinking_done is False while a thought block is still open (mid-stream).
    """
    thoughts = []
    thinking_done = True
    for pattern in _THOUGHT_BLOCKS:
        while True:
            match = pattern.search(text)
            if not match:
                break
            thoughts.append(match.group(1).strip())
            if not match.group(2):
                thinking_done = False
            text = text[:match.start()] + text[match.end():]
    answer = _trim_partial_marker(_STRAY_MARKERS.sub("", text).rstrip()).strip()
    return "\n\n".join(t for t in thoughts if t), answer, thinking_done


# Mid-stream (or after Ctrl+C) the text can end with half a marker, like "<|chan".
_STREAM_MARKERS = ("<|channel>", "<channel|>", "<|turn>", "<turn|>", "<think>", "</think>",
                   "<reasoning>", "</reasoning>")


def _trim_partial_marker(text):
    for marker in _STREAM_MARKERS:
        for size in range(len(marker) - 1, 1, -1):
            if text.endswith(marker[:size]):
                return text[:-size]
    return text


def split_reasoning_summary(text, allow_reasoning=True):
    """Return (thinking, answer); thinking is dropped when allow_reasoning is False."""
    thinking, answer, _ = split_thinking(text)
    return (thinking if allow_reasoning else ""), answer
