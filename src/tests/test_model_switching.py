import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from PySide6.QtCore import QCoreApplication

from hyperflux.desktop import runtime_assets
from hyperflux.desktop.model_switcher import LocalModels
from hyperflux.search.bridge import create_search_bridge

TOKEN = "switch-token"
_app = QCoreApplication.instance() or QCoreApplication([])


def _gguf(directory, name, size=64):
    path = Path(directory) / name
    path.write_bytes(b"GGUF" + b"\0" * (size - 4))
    return path


class LocalModelListTests(unittest.TestCase):
    def test_lists_models_with_friendly_names_and_the_active_one_first(self):
        with tempfile.TemporaryDirectory() as directory:
            e2b = _gguf(directory, "gemma-4-E2B-it-Q4_K_M.gguf")
            e4b = _gguf(directory, "gemma-4-E4B-it-Q4_K_M.gguf")
            other = _gguf(directory, "my-model.gguf")
            with patch.object(runtime_assets, "find_gguf_models", return_value=[e2b.resolve(), e4b.resolve(), other.resolve()]):
                models = runtime_assets.describe_local_models(str(e4b))
        self.assertEqual([m["name"] for m in models], ["Gemma 4 E4B", "Gemma 4 E2B", "my-model"])
        self.assertEqual([m["active"] for m in models], [True, False, False])

    def test_name_is_read_from_the_gguf_header_and_neighbours_are_listed(self):
        import struct

        def text(value):
            data = value.encode()
            return struct.pack("<Q", len(data)) + data

        header = b"GGUF" + struct.pack("<IQQ", 3, 0, 3)
        header += text("general.architecture") + struct.pack("<I", 8) + text("gemma4")
        header += text("general.quantized_by") + struct.pack("<I", 8) + text("Unsloth")
        header += text("general.basename") + struct.pack("<I", 8) + text("Gemma-4-E4B-It")
        with tempfile.TemporaryDirectory() as directory:
            active = _gguf(directory, "model.gguf")
            neighbour = Path(directory) / "model-e4b.gguf"
            neighbour.write_bytes(header + b"\0" * 32)
            self.assertEqual(runtime_assets.gguf_model_name(neighbour), "Gemma 4 E4B")
            self.assertIsNone(runtime_assets.gguf_model_name(active))  # no metadata: falls back
            with patch.object(runtime_assets, "find_gguf_models", return_value=[]):
                models = runtime_assets.describe_local_models(str(active))
        self.assertEqual([m["name"] for m in models], ["model", "Gemma 4 E4B"])

    def test_renamed_official_model_is_recognised_by_its_size(self):
        with tempfile.TemporaryDirectory() as directory:
            renamed = _gguf(directory, "model.gguf")
            size = renamed.stat().st_size
            fake = {"e2b": {**runtime_assets.GEMMA_MODELS["e2b"], "size": size}}
            with patch.dict(runtime_assets.GEMMA_MODELS, fake, clear=True), \
                    patch.object(runtime_assets, "find_gguf_models", return_value=[renamed.resolve()]):
                models = runtime_assets.describe_local_models(str(renamed))
        self.assertEqual(models[0]["name"], "Gemma 4 E2B")


class SwitchRequestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.e2b = _gguf(self.directory.name, "gemma-4-E2B-it-Q4_K_M.gguf").resolve()
        self.e4b = _gguf(self.directory.name, "gemma-4-E4B-it-Q4_K_M.gguf").resolve()
        patcher = patch.object(runtime_assets, "find_gguf_models", return_value=[self.e2b, self.e4b])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.directory.cleanup)
        self.manager = LocalModels(self.e2b, can_switch=lambda: True)
        self.requested = []
        self.manager.switch_requested.connect(self.requested.append)

    def test_switches_only_to_listed_models(self):
        self.assertFalse(self.manager.request_switch(r"C:\Windows\notepad.exe")[0])
        self.assertFalse(self.manager.request_switch(None)[0])
        self.assertEqual(self.requested, [])
        self.assertTrue(self.manager.request_switch(str(self.e4b))[0])
        self.assertEqual(self.requested, [str(self.e4b)])
        self.assertTrue(self.manager.describe()["switching"])
        # A second switch must wait until the first model has loaded.
        self.assertFalse(self.manager.request_switch(str(self.e2b))[0])
        self.manager.finished(str(self.e4b))
        active = [m for m in self.manager.describe()["models"] if m["active"]]
        self.assertEqual(active[0]["path"], str(self.e4b))

    def test_failed_load_keeps_the_previous_model_active(self):
        self.manager.request_switch(str(self.e4b))
        self.manager.finished(str(self.e4b), failed=True, previous_path=str(self.e2b))
        active = [m for m in self.manager.describe()["models"] if m["active"]]
        self.assertEqual(active[0]["path"], str(self.e2b))

    def test_no_switching_when_hyperflux_did_not_start_the_server(self):
        manager = LocalModels(self.e2b, can_switch=lambda: False)
        self.assertFalse(manager.request_switch(str(self.e4b))[0])
        self.assertFalse(manager.describe()["available"])

    def test_bridge_endpoints_need_the_desktop_token(self):
        server = create_search_bridge(object(), port=0, log_token=TOKEN, model_manager=self.manager)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(2)))
        base = f"http://127.0.0.1:{server.server_address[1]}"

        self.assertEqual(requests.get(f"{base}/local-models", timeout=2).status_code, 403)
        listing = requests.get(f"{base}/local-models?token={TOKEN}", headers={"Origin": "null"}, timeout=2)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()["models"]), 2)

        refused = requests.post(f"{base}/local-models/switch?token=wrong", json={"path": str(self.e4b)}, timeout=2)
        self.assertEqual(refused.status_code, 403)
        refused = requests.post(f"{base}/local-models/switch", json={"path": str(self.e4b)},
                                headers={"Origin": "https://example.com"}, timeout=2)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self.requested, [])

        accepted = requests.post(f"{base}/local-models/switch?token={TOKEN}", json={"path": str(self.e4b)}, timeout=2)
        self.assertEqual(accepted.status_code, 202)
        # The bridge thread hands the restart to the window's thread (its event loop).
        _app.processEvents()
        self.assertEqual(self.requested, [str(self.e4b)])


if __name__ == "__main__":
    unittest.main()
