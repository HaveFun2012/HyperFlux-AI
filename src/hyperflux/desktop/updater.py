"""Check GitHub Releases for a newer HyperFlux, download the installer safely, run it.

Kept free of Qt so it can be tested without a GUI. Rules:
  * Only the latest published (non-draft, non-pre-release) release is considered.
  * The installer must come from GitHub over HTTPS and match a SHA-256 published
    with the release (GitHub's asset digest or the attached .sha256 file).
    Without a checksum, the update is refused.
  * Checks happen at most once a day, and the user can skip a version.
"""

import json
import os
import re
import subprocess
import time
from urllib.parse import urlparse

import requests

from hyperflux.desktop import runtime_assets
from hyperflux.version import GITHUB_REPO, __version__

INSTALLER_NAME = "HyperFlux-Setup.exe"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": f"HyperFlux/{__version__}"}


def _state_path():
    return runtime_assets.APP_DATA / "update_state.json"


def parse_version(text):
    """'v1.2.3' -> (1, 2, 3). Pre-release suffixes like '-beta' are ignored. None if unparsable."""
    match = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or "").strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def is_newer(candidate, current=__version__):
    new, old = parse_version(candidate), parse_version(current)
    return bool(new and old and new > old)


# ---- Throttling and "skip this version" ------------------------------------------

def load_state():
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(**changes):
    state = {**load_state(), **changes}
    try:
        _state_path().parent.mkdir(parents=True, exist_ok=True)
        _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass  # never let update bookkeeping break the app


def check_is_due(now=None):
    last = load_state().get("last_check", 0)
    now = time.time() if now is None else now
    return not isinstance(last, (int, float)) or now - last >= CHECK_INTERVAL_SECONDS


def skip_version(version):
    save_state(skipped_version=version)


# ---- Finding the update -------------------------------------------------------------

def _is_github_https(url):
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and parsed.hostname == "github.com"


def _published_sha256(release, installer):
    """The installer's SHA-256 from GitHub's asset digest, or from an attached .sha256 file."""
    digest = installer.get("digest") or ""
    if isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        return digest.split(":", 1)[1].lower()
    for asset in release.get("assets", []):
        if asset.get("name") == INSTALLER_NAME + ".sha256" and _is_github_https(asset.get("browser_download_url")):
            response = requests.get(asset["browser_download_url"], headers=_HEADERS, timeout=(10, 30))
            response.raise_for_status()
            match = re.match(r"\s*([0-9a-fA-F]{64})\b", response.text)
            if match:
                return match.group(1).lower()
    return None


def check_for_update(current=__version__, ignore_skipped=False):
    """Return update info if a newer verified release exists, else None.

    Records the check time. Network or API problems (including a private repo,
    which GitHub reports as 404) return None quietly.
    """
    save_state(last_check=time.time())
    try:
        response = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers=_HEADERS,
            timeout=(10, 30),
        )
        if response.status_code != 200:
            return None
        release = response.json()
        version = str(release.get("tag_name") or "").lstrip("v")
        if release.get("draft") or release.get("prerelease") or not is_newer(version, current):
            return None
        if not ignore_skipped and load_state().get("skipped_version") == version:
            return None
        installer = next((a for a in release.get("assets", []) if a.get("name") == INSTALLER_NAME), None)
        if not installer or not _is_github_https(installer.get("browser_download_url")):
            return None
        size = installer.get("size")
        sha256 = _published_sha256(release, installer)
        if not isinstance(size, int) or size <= 0 or not sha256:
            return None  # can't verify it, so don't offer it
        return {
            "version": version,
            "url": installer["browser_download_url"],
            "size": size,
            "sha256": sha256,
            "notes_url": release.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest",
        }
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        return None


# ---- Downloading and installing -------------------------------------------------------

def download_update(info, progress, log, is_cancelled):
    """Download (or reuse) the verified installer for `info`; returns its path."""
    destination = runtime_assets.APP_DATA / "updates" / f"HyperFlux-Setup-{info['version']}.exe"
    if destination.exists():
        if destination.stat().st_size == info["size"] and runtime_assets.sha256_of(destination, is_cancelled) == info["sha256"]:
            log("Using the update that was downloaded earlier.")
            return destination
        destination.unlink()  # our own leftover that failed verification; safe to replace
    log(f"Downloading HyperFlux {info['version']} ({info['size'] / 2**20:.0f} MB)...")
    runtime_assets.download(info["url"], destination, info["size"], info["sha256"], progress, log, is_cancelled)
    if not runtime_assets.is_windows_executable(destination):
        destination.unlink(missing_ok=True)
        raise OSError("The downloaded update is not a valid Windows installer.")
    return destination


def launch_installer(path):
    """Start the installer quietly; it closes HyperFlux, updates it, then relaunches it."""
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen(
        [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
        creationflags=flags,
        close_fds=True,
    )


def cleanup_old_downloads(keep_version=None):
    """Delete installers left from earlier updates (they are large)."""
    folder = runtime_assets.APP_DATA / "updates"
    if not folder.is_dir():
        return
    for item in folder.glob("HyperFlux-Setup-*.exe*"):
        if keep_version and item.name.startswith(f"HyperFlux-Setup-{keep_version}.exe"):
            continue
        try:
            item.unlink()
        except OSError:
            pass
