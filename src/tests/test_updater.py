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

    def test_offer_has_patch_notes_and_changed_files_and_is_remembered(self):
        body = "# HyperFlux v1.2.0\n\nIntro.\n\n## What's new\n\n- **Pictures.** You can attach them.\n\n## Installation\n\nRun it."
        compare = {"files": [{"filename": "src/web/HyperFlux Web.html", "status": "modified"},
                             {"filename": "src/hyperflux/desktop/vision.py", "status": "added"}],
                   "commits": [{"commit": {"message": "Add pictures\n\nDetails"}}]}
        info = self._check(_Response(payload=_release(body=body)), _Response(payload=compare))
        self.assertEqual(info["notes"], "- **Pictures.** You can attach them.")
        self.assertEqual(info["changes"]["total"], 2)
        self.assertEqual(info["changes"]["files"][1], {"name": "src/hyperflux/desktop/vision.py", "status": "added"})
        self.assertEqual(info["changes"]["commits"], ["Add pictures"])
        # "Later": offered again on the next launch, even offline, until installed or skipped.
        self.assertEqual(updater.pending_update(current="1.0.0")["version"], "1.2.0")
        self.assertIsNone(updater.pending_update(current="1.2.0"))  # installed
        updater.skip_version("1.2.0")
        self.assertIsNone(updater.pending_update(current="1.0.0"))

    def test_missing_compare_never_blocks_the_update(self):
        info = self._check(_Response(payload=_release()), _Response(status=404))
        self.assertIsNotNone(info)
        self.assertIsNone(info["changes"])

    def test_popup_is_shown_once_per_version(self):
        self.assertTrue(updater.should_prompt("1.2.0"))
        updater.mark_prompted("1.2.0")
        self.assertFalse(updater.should_prompt("1.2.0"))
        self.assertTrue(updater.should_prompt("1.3.0"))

    def test_notes_without_a_whats_new_section_are_used_whole(self):
        self.assertEqual(updater.whats_new("Just a fix."), "Just a fix.")
        self.assertEqual(updater.whats_new(None), "")

    def test_release_notes_start_with_this_versions_patch_notes(self):
        from importlib import util
        path = Path(__file__).resolve().parents[1] / "packaging" / "release-notes" / "generate.py"
        spec = util.spec_from_file_location("generate_notes", path)
        generate = util.module_from_spec(spec)
        spec.loader.exec_module(generate)
        notes = generate.build_notes("v1.1.0")
        self.assertIn("## What's new\n\n- **Show HyperFlux a picture.**", notes)
        self.assertLess(notes.index("## What's new"), notes.index("## Highlights"))
        self.assertTrue(updater.whats_new(notes).startswith("- **Show HyperFlux a picture.**"))

    def test_bridge_update_routes_need_the_desktop_token(self):
        import threading
        import requests
        from hyperflux.search.bridge import create_search_bridge

        class FakeUpdates:
            calls = []
            def describe(self): return {"available": True, "version": "1.2.0", "prompt": True}
            def request_install(self): FakeUpdates.calls.append("install"); return True, "ok"
            def skip(self): FakeUpdates.calls.append("skip"); return True
            def mark_prompted(self): FakeUpdates.calls.append("prompted"); return True

        server = create_search_bridge(None, port=0, log_token="tok", update_manager=FakeUpdates())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            self.assertEqual(requests.get(base + "/update", timeout=5).status_code, 403)
            self.assertEqual(requests.get(base + "/update?token=tok", timeout=5).json()["version"], "1.2.0")
            self.assertEqual(requests.post(base + "/update/install", timeout=5).status_code, 403)
            for action in ("prompted", "install", "skip"):
                self.assertLess(requests.post(f"{base}/update/{action}?token=tok", timeout=5).status_code, 300)
            self.assertEqual(FakeUpdates.calls, ["prompted", "install", "skip"])
        finally:
            server.shutdown()
            server.server_close()

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
