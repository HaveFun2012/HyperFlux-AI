import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from hyperflux.desktop import runtime_assets, updater

SHA = "a" * 64


class _Response:
    def __init__(self, status=200, payload=None, text="", chunks=(), headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self._chunks = chunks
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise updater.requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size):
        yield from self._chunks

    def close(self):
        pass


def _release(tag="v1.2.0", assets=None, **extra):
    if assets is None:
        assets = [{"name": "HyperFlux-Setup.exe", "size": 1234, "digest": f"sha256:{SHA}",
                   "browser_download_url": f"https://github.com/HaveFun2012/HyperFlux-AI/releases/download/{tag}/HyperFlux-Setup.exe"}]
    return {"tag_name": tag, "draft": False, "prerelease": False, "html_url": "https://github.com/x/releases/tag/" + tag,
            "assets": assets, **extra}


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(runtime_assets, "APP_DATA", Path(self.temp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def _check(self, *responses, current="1.0.0", **kwargs):
        with patch("hyperflux.desktop.updater.requests.get", side_effect=list(responses)):
            return updater.check_for_update(current=current, **kwargs)

    def test_version_comparison(self):
        self.assertTrue(updater.is_newer("v1.0.1", "1.0.0"))
        self.assertTrue(updater.is_newer("1.10.0", "1.9.9"))
        self.assertFalse(updater.is_newer("v1.0.0", "1.0.0"))
        self.assertFalse(updater.is_newer("0.9.0", "1.0.0"))
        self.assertFalse(updater.is_newer("not-a-version", "1.0.0"))

    def test_newer_verified_release_is_offered(self):
        info = self._check(_Response(payload=_release()))
        self.assertEqual(info["version"], "1.2.0")
        self.assertEqual(info["sha256"], SHA)
        self.assertEqual(info["size"], 1234)

    def test_checksum_can_come_from_attached_sha256_file(self):
        assets = [
            {"name": "HyperFlux-Setup.exe", "size": 10, "browser_download_url": "https://github.com/x/HyperFlux-Setup.exe"},
            {"name": "HyperFlux-Setup.exe.sha256", "size": 90, "browser_download_url": "https://github.com/x/HyperFlux-Setup.exe.sha256"},
        ]
        info = self._check(_Response(payload=_release(assets=assets)), _Response(text=f"{'B' * 64}  HyperFlux-Setup.exe\n"))
        self.assertEqual(info["sha256"], "b" * 64)

    def test_unverifiable_or_unsafe_releases_are_refused(self):
        no_hash = [{"name": "HyperFlux-Setup.exe", "size": 10, "browser_download_url": "https://github.com/x/HyperFlux-Setup.exe"}]
        other_host = [{"name": "HyperFlux-Setup.exe", "size": 10, "digest": f"sha256:{SHA}",
                       "browser_download_url": "https://evil.example/HyperFlux-Setup.exe"}]
        http_only = [{"name": "HyperFlux-Setup.exe", "size": 10, "digest": f"sha256:{SHA}",
                      "browser_download_url": "http://github.com/x/HyperFlux-Setup.exe"}]
        for assets in (no_hash, other_host, http_only, []):
            self.assertIsNone(self._check(_Response(payload=_release(assets=assets))))

    def test_older_same_prerelease_and_unreachable_are_ignored(self):
        self.assertIsNone(self._check(_Response(payload=_release(tag="v1.0.0"))))
        self.assertIsNone(self._check(_Response(payload=_release(tag="v0.9.0"))))
        self.assertIsNone(self._check(_Response(payload=_release(prerelease=True))))
        self.assertIsNone(self._check(_Response(status=404)))  # e.g. a private repository
        self.assertIsNone(self._check(updater.requests.ConnectionError("offline")))

    def test_skipped_version_is_not_offered_again_unless_forced(self):
        updater.skip_version("1.2.0")
        self.assertIsNone(self._check(_Response(payload=_release())))
        self.assertIsNotNone(self._check(_Response(payload=_release()), ignore_skipped=True))
        self.assertIsNotNone(self._check(_Response(payload=_release(tag="v1.3.0"))))

    def test_checks_at_most_once_a_day(self):
        self.assertTrue(updater.check_is_due())
        self._check(_Response(status=404))
        self.assertFalse(updater.check_is_due())
        self.assertTrue(updater.check_is_due(now=time.time() + updater.CHECK_INTERVAL_SECONDS + 1))

    def test_download_is_verified_and_reused(self):
        data = b"MZ" + bytes(58) + (64).to_bytes(4, "little") + b"PE\0\0\x64\x86" + b"x" * 200
        info = {"version": "1.2.0", "url": "https://github.com/x/HyperFlux-Setup.exe",
                "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        with patch("hyperflux.desktop.runtime_assets.requests.get", return_value=_Response(chunks=[data])) as get:
            path = updater.download_update(info, lambda _: None, lambda _: None, lambda: False)
            self.assertEqual(path.read_bytes(), data)
            updater.download_update(info, lambda _: None, lambda _: None, lambda: False)
        self.assertEqual(get.call_count, 1)  # second call reused the verified file

    def test_tampered_download_is_rejected(self):
        info = {"version": "1.2.0", "url": "https://github.com/x/HyperFlux-Setup.exe", "size": 5, "sha256": SHA}
        with patch("hyperflux.desktop.runtime_assets.requests.get", return_value=_Response(chunks=[b"MZbad"])):
            with self.assertRaises(OSError):
                updater.download_update(info, lambda _: None, lambda _: None, lambda: False)
        self.assertFalse((Path(self.temp.name) / "updates" / "HyperFlux-Setup-1.2.0.exe").exists())


if __name__ == "__main__":
    unittest.main()
