"""Shared settings for the HyperFlux engine, search, and interfaces."""

from hyperflux import paths


class Config:
    ASSISTANT_NAME = "HyperFlux"
    VERSION = "HyperFlux Gen 1 Gemma4"
    BRAIN_PATH = paths.BRAIN_PATH
    MAX_MEMORY_EXCHANGES = 14
    # Thinking needs room: prompt + history + thoughts + answer must all fit.
    # KoboldCpp's own limit (16384 by default) is the hard ceiling.
    MAX_CONTEXT_LENGTH = 8192
    ESTIMATED_CHARS_PER_TOKEN = 3
    MAX_READ_FILE_CHARS = 3000
    DEFAULT_TEMPERATURE = 0.70
    MIN_TEMPERATURE = 0.0
    MAX_TEMPERATURE = 2.0
    DEFAULT_MAX_LENGTH = 4096
    MIN_MAX_LENGTH = 1
    MAX_MAX_LENGTH = 6144
    # /read only opens files inside this folder.
    WORKSPACE_ROOT = paths.RESOURCE_ROOT
    SEARCH_CONTEXT_MAX_CHARS = 1400
    SEARCH_RESULT_COUNT = 3
    SEARCH_MAX_VARIANTS = 2
    SEARCH_BRIDGE_HOST = "127.0.0.1"
    SEARCH_BRIDGE_PORT = 5002
    TRUSTED_SEARCH_DOMAINS = {
        "docs.python.org",
        "github.com",
        "reuters.com",
        "wikipedia.org",
    }
    KOBOLD_API_URL = "http://localhost:5001/api/v1/generate"
    KOBOLD_MODEL_URL = "http://localhost:5001/api/v1/model"
    # Used to show a model name before KoboldCpp reports one.
    LAUNCHER_PATH = paths.SERVER_LAUNCHER
