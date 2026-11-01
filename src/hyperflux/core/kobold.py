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
    text = text.replace("<end_of_turn>", "").strip()
    return re.sub(
        r'^(?:Copilot|Assistant|HyperFlux|Qwen):\s*',
        '',
        text,
        flags=re.IGNORECASE,
    )
