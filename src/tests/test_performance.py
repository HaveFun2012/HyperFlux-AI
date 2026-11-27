"""Speed settings: how the model server is started, and when it has to be reloaded."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from hyperflux.desktop import performance
from hyperflux.search.bridge import create_search_bridge


class LaunchArgumentTests(unittest.TestCase):
    def arguments(self, pictures="auto", context=None, vision=True, vram=4096):
        return performance.launch_arguments({"pictures": pictures, "context": context}, vision, vram)

    def test_small_cards_keep_the_vision_file_on_the_processor(self):
        self.assertEqual(self.arguments(), ["--mmprojcpu"])
        self.assertEqual(self.arguments(vram=8192), [])
        self.assertEqual(self.arguments(vram=None), [])  # a card we couldn't ask is left as it was

    def test_the_users_choice_wins_over_the_card(self):
        self.assertEqual(self.arguments("pictures"), [])
        self.assertEqual(self.arguments("chat", vram=24576), ["--mmprojcpu"])

    def test_a_model_without_vision_gets_no_vision_option(self):
        self.assertEqual(self.arguments("chat", vision=False), [])

    def test_context_is_passed_on(self):
        self.assertEqual(self.arguments(context=8192, vision=False), ["--contextsize", "8192"])

    def test_bad_saved_values_fall_back_safely(self):
        for context in (None, 12, 10**9, "8192", True, 8192.5):
            self.assertIsNone(performance.clean_settings("auto", context)["context"], context)
        self.assertEqual(performance.clean_settings("--evil", 8192), {"pictures": "auto", "context": 8192})


class ReloadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        patcher = patch.object(performance, "SETTINGS_FILE", Path(self.folder.name) / "performance.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)
        self.reloads = []
        self.control = performance.Performance(
            has_vision=lambda: True, can_restart=lambda: True,
            restart=lambda: self.reloads.append(1), vram=lambda: 4096)

    def test_first_start_uses_the_defaults(self):
        self.assertEqual(self.control.launch_arguments(), ["--mmprojcpu"])
        self.assertEqual(self.control.describe()["context"], 16384)

    def test_reloads_only_when_the_server_would_start_differently(self):
        # "chat" and the server's own context are what a 4 GB card already gets
        self.assertFalse(self.control.update("chat", 16384)["restarting"])
        self.assertTrue(self.control.update("chat", 8192)["restarting"])
        self.assertFalse(self.control.update("chat", 8192)["restarting"])
        self.assertTrue(self.control.update("pictures", 8192)["restarting"])
        self.assertEqual(len(self.reloads), 2)
        self.assertEqual(self.control.launch_arguments(), ["--contextsize", "8192"])

    def test_a_server_hyperflux_did_not_start_is_left_alone(self):
        self.control._can_restart = lambda: False
        self.assertEqual(self.control.update("pictures", 16384), {"restarting": False, "changed": True})
        self.assertEqual(self.reloads, [])

    def test_bridge_routes_need_the_desktop_token(self):
        server = create_search_bridge(None, port=0, log_token="tok", performance_manager=self.control)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}/performance"
        try:
            body = {"pictures": "pictures", "context": 8192}
            self.assertEqual(requests.get(base, timeout=5).status_code, 403)
            self.assertEqual(requests.post(base, json=body, timeout=5).status_code, 403)
            self.assertEqual(self.reloads, [])
            self.assertEqual(requests.post(base + "?token=tok", json={"nope": 1}, timeout=5).status_code, 400)
            self.assertTrue(requests.post(base + "?token=tok", json=body, timeout=5).json()["restarting"])
            self.assertEqual(requests.get(base + "?token=tok", timeout=5).json()["pictures"], "pictures")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
