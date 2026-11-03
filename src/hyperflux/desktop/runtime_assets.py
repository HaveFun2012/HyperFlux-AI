"""Runtime asset handling for the first-run setup: file checks, saved paths, downloads.

Kept free of Qt so it can be tested and reused without a GUI.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import requests

from hyperflux.paths import user_data_directory

KOBOLD_RELEASE_API = "https://api.github.com/repos/LostRuins/koboldcpp/releases/latest"
APP_DATA = user_data_directory()
RUNTIME_CONFIG = APP_DATA / "runtime.json"

# Downloadable models, each pinned to one exact file: a fixed repository commit, size,
# and SHA-256, so the download can't silently change. (Checked against Hugging Face
# on 2026-11-03.) E2B is the default; E4B is optional and never chosen for the user.
_GEMMA_LICENSE = {
    "license_name": "Apache License 2.0",
    "license_url": "https://ai.google.dev/gemma/docs/gemma_4_license",
}


def _pinned_gemma(size_name, commit, size, sha256, **details):
    repo = f"lmstudio-community/gemma-4-{size_name}-it-GGUF"
    filename = f"gemma-4-{size_name}-it-Q4_K_M.gguf"
    return {
        "label": f"Gemma 4 {size_name} (Q4_K_M)",
        "filename": filename,
        "url": f"https://huggingface.co/{repo}/resolve/{commit}/{filename}",
        "size": size,
        "sha256": sha256,
        "source_page": f"https://huggingface.co/{repo}",
        **_GEMMA_LICENSE,
        **details,
    }


GEMMA_MODELS = {
    # The model HyperFlux was developed and tested with.
    "e2b": _pinned_gemma(
        "E2B", "eed445ccfb8aef2e279df1a97e133baf06e443b4", 3_427_880_384,
        "71e6e8cb64a76da1a734fb8f6ba389d2784950d9902f5e87244fca0a15190c94",
        summary="Recommended. Fast, and runs well on 8 GB of RAM.",
        min_ram_gb=8,
    ),
    # Better at trick questions and real-world reasoning, but slower and heavier.
    "e4b": _pinned_gemma(
        "E4B", "99210a71094c6aa8559f764e0cadedd7d89de94d", 5_335_291_936,
        "0ffb122c8b6921f13cbc34186e052524d0b5803b17f4867b7197a561400b3770",
        summary="Optional. Better reasoning, but slower; best with 16 GB of RAM.",
        min_ram_gb=16,
    ),
}
DEFAULT_GEMMA = "e2b"
GEMMA_MODEL = GEMMA_MODELS[DEFAULT_GEMMA]


def total_ram_gb():
    """This PC's installed memory in GB, or None if Windows doesn't say."""
    try:
        import ctypes

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                        ("available_extended", ctypes.c_ulonglong)]

        status = _MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.total / 1024 ** 3
    except (AttributeError, OSError):
        return None


def is_gguf(path):
    try:
        with Path(path).open("rb") as source:
            return source.read(4) == b"GGUF"
    except OSError:
        return False


def is_windows_executable(path):
    try:
        with Path(path).open("rb") as source:
            dos_header = source.read(64)
            if len(dos_header) < 64 or dos_header[:2] != b"MZ":
                return False
            pe_offset = int.from_bytes(dos_header[60:64], "little")
            if not 64 <= pe_offset <= 16 * 1024 * 1024:
                return False
            source.seek(pe_offset)
            pe_header = source.read(6)
            return (
                pe_header[:4] == b"PE\0\0"
                and int.from_bytes(pe_header[4:6], "little") in {0x014C, 0x8664}
            )
    except OSError:
        return False


def find_file(filename, extra_paths=()):
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    )
    local_programs = Path(os.environ.get("LOCALAPPDATA", APP_DATA.parent)) / "Programs"
    candidates = [
        Path(sys.executable).resolve().parent / filename,
        APP_DATA / filename,
        Path.home() / "Downloads" / filename,
        Path.home() / "Documents" / filename,
        Path.home() / "Desktop" / filename,
        local_programs / "KoboldCpp" / filename,
        program_files / "KoboldCpp" / filename,
        program_files_x86 / "KoboldCpp" / filename,
        Path.cwd() / filename,
        *map(Path, extra_paths),
    ]
    return next((path for path in candidates if path.is_file()), None)


def find_gguf_models():
    directories = [
        APP_DATA / "models",
        Path.home() / "Downloads",
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path(sys.executable).resolve().parent,
        Path.cwd(),
    ]
    candidates = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.gguf"):
            if path.is_file() and is_gguf(path):
                candidates[str(path.resolve()).casefold()] = path.resolve()
    preferred_names = {"model.gguf": 0}
    return sorted(
        candidates.values(),
        key=lambda path: (
            preferred_names.get(path.name.casefold(), 2),
            str(path).casefold(),
        ),
    )


def describe_local_models(active_path):
    """The GGUF models this PC has, for the model picker: the active one first-class,
    friendly names for the downloadable Gemma files, file names for the rest."""
    # Recognised by file name, or by exact size when renamed (e.g. model.gguf).
    known = {info["filename"].casefold(): info["label"].replace(" (Q4_K_M)", "") for info in GEMMA_MODELS.values()}
    known_sizes = {info["size"]: info["label"].replace(" (Q4_K_M)", "") for info in GEMMA_MODELS.values()}
    paths = {}
    for path in [Path(active_path)] if active_path else []:
        if path.is_file():
            paths[str(path.resolve()).casefold()] = path.resolve()
    for path in find_gguf_models():
        paths.setdefault(str(path).casefold(), path)
    active_key = str(Path(active_path).resolve()).casefold() if active_path else ""
    models = []
    for key, path in paths.items():
        try:
            size = path.stat().st_size
        except OSError:
            continue
        models.append({
            "path": str(path),
            "name": known.get(path.name.casefold()) or known_sizes.get(size) or path.stem,
            "file": path.name,
            "size_gb": round(size / 1e9, 1),
            "active": key == active_key,
        })
    models.sort(key=lambda model: (not model["active"], model["name"].casefold()))
    return models


def load_config():
    try:
        config = json.loads(RUNTIME_CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read saved runtime settings: {error}") from error
    if not isinstance(config, dict):
        raise RuntimeError("Saved runtime settings are not a JSON object.")
    model_value = config.get("model_path")
    kobold_value = config.get("kobold_path")
    if not isinstance(model_value, str) or not isinstance(kobold_value, str):
        raise RuntimeError("Saved runtime settings contain invalid asset paths.")
    model_path = Path(model_value)
    kobold_path = Path(kobold_value)
    if not is_gguf(model_path):
        return None
    if not is_windows_executable(kobold_path):
        return None
    return {"model_path": str(model_path), "kobold_path": str(kobold_path)}


def save_config(model_path, kobold_path):
    APP_DATA.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        # Callers may pass str or Path (the setup wizard passes str).
        {
            "model_path": str(Path(model_path).resolve()),
            "kobold_path": str(Path(kobold_path).resolve()),
        },
        indent=2,
    )
    handle, temporary_path = tempfile.mkstemp(
        prefix="runtime-", suffix=".tmp", dir=APP_DATA
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, RUNTIME_CONFIG)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def download(
    url, destination, expected_size, expected_hash, progress, log, is_cancelled,
    request_headers=None,
):
    destination.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(destination.parent).free
    if free_bytes < expected_size + 64 * 1024 * 1024:
        raise OSError(
            f"Not enough free disk space for {destination.name}; "
            f"at least {expected_size + 64 * 1024 * 1024:,} bytes are required."
        )

    partial = destination.with_suffix(destination.suffix + ".part")
    if destination.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing asset {destination}; choose or remove it explicitly."
        )
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > expected_size:
        partial.unlink()
        offset = 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    headers.update(request_headers or {})
    response = requests.get(url, headers=headers, stream=True, timeout=(20, 90))
    try:
        response.raise_for_status()
        resume = offset > 0 and response.status_code == 206
        if resume and not response.headers.get("Content-Range", "").startswith(
            f"bytes {offset}-"
        ):
            response.close()
            partial.unlink(missing_ok=True)
            raise OSError("Download server returned an invalid range for resume.")
        if offset and not resume:
            offset = 0
            log("Server does not support resuming; restarting this asset download.")
        total = expected_size
        received = offset
        digest = hashlib.sha256()
        if resume:
            with partial.open("rb") as existing:
                for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                    digest.update(chunk)
        mode = "ab" if resume else "wb"
        with partial.open(mode) as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if is_cancelled():
                    raise InterruptedError("Setup cancelled; the partial download is available for retry.")
                if not chunk:
                    continue
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                progress(min(100, received * 100 // total))
        if received != expected_size:
            raise OSError(
                f"Downloaded size mismatch for {destination.name}: "
                f"expected {expected_size:,} bytes, received {received:,}."
            )
        if expected_hash and digest.hexdigest().lower() != expected_hash.lower():
            partial.unlink(missing_ok=True)
            raise OSError(f"SHA-256 verification failed for {destination.name}.")
        os.replace(partial, destination)
    finally:
        response.close()




def sha256_of(path, is_cancelled=lambda: False):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            if is_cancelled():
                raise InterruptedError("Setup cancelled.")
            digest.update(chunk)
    return digest.hexdigest()


def _gemma(model_key):
    if model_key is None:
        return GEMMA_MODEL  # looked up at call time so tests can replace it
    if model_key not in GEMMA_MODELS:
        raise ValueError(f"Unknown model choice: {model_key!r}")
    return GEMMA_MODELS[model_key]


def model_download_path(model_key=None):
    """Where a downloadable model is saved (outside the install folder, per user)."""
    return APP_DATA / "models" / _gemma(model_key)["filename"]


def download_gemma_model(progress, log, is_cancelled, model_key=None):
    """Download a pinned model (E2B unless model_key says otherwise), or reuse a
    verified copy; returns its path.

    The file must match the pinned size and SHA-256. An unfinished download resumes
    from its .part file; an unexpected file at the destination is never overwritten.
    """
    model = _gemma(model_key)
    destination = model_download_path(model_key)
    if destination.exists():
        log("Checking the model that was downloaded earlier...")
        if destination.stat().st_size == model["size"] and sha256_of(destination, is_cancelled) == model["sha256"]:
            log("Reusing the verified model already on this PC.")
            return destination
        raise OSError(
            f"{destination} exists but is not the expected model. "
            "Move or delete it, then retry."
        )
    log(f"Downloading {model['label']} ({model['size'] / 1e9:.1f} GB) from Hugging Face. "
        "This can take a while; you can cancel and resume later.")
    download(model["url"], destination, model["size"], model["sha256"], progress, log, is_cancelled)
    log("Model downloaded and verified (SHA-256 matches).")
    return destination
