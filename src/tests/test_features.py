"""Personas, custom instructions and chat export (terminal), plus image-input assets."""

import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyperflux import paths
from hyperflux.core.commands import export_chat
from hyperflux.core.engine import HyperFluxEngine
from hyperflux.core.prompts import build_capabilities, build_system_instruction


class _TempSettings:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Path(self.tmp.name) / "terminal_settings.json"
        self.patch = patch.object(paths, "TERMINAL_SETTINGS_PATH", self.settings)
        self.patch.start()
        with patch.object(HyperFluxEngine, "_load_model_name"):
            self.engine = HyperFluxEngine()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()


class PersonaAndInstructionTests(_TempSettings, unittest.TestCase):
    def test_persona_and_instructions_reach_the_prompt(self):
        prompt = build_system_instruction(build_capabilities("m"), "apex", "tutor", "I live in Malaysia; use RM.")
        self.assertIn("Persona: a patient tutor", prompt)
        self.assertIn("The user's custom instructions", prompt)
        self.assertIn("I live in Malaysia; use RM.", prompt)
        plain = build_system_instruction(build_capabilities("m"), "apex")
        self.assertNotIn("Persona:", plain)
        self.assertNotIn("custom instructions", plain)

    def test_commands_change_and_remember_settings(self):
        self.assertIn("Tutor", self.engine.handle_runtime_command("/persona tutor"))
        self.assertIn("Unknown persona", self.engine.handle_runtime_command("/persona pirate"))
        self.assertIn("saved", self.engine.handle_runtime_command("/instructions Keep it simple, please."))
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")),
                         {"persona": "tutor", "custom_instructions": "Keep it simple, please."})
        with patch.object(HyperFluxEngine, "_load_model_name"):
            again = HyperFluxEngine()  # a new terminal session remembers them
        self.assertEqual((again.persona, again.custom_instructions), ("tutor", "Keep it simple, please."))
        self.assertIn("Keep it simple", again.handle_runtime_command("/instructions"))
        self.assertIn("removed", again.handle_runtime_command("/instructions clear"))
        self.assertIn("Persona:** Tutor", again.handle_runtime_command("/sys"))

    def test_settings_file_is_used_in_requests(self):
        self.engine.handle_runtime_command("/persona coder")
        self.engine.handle_runtime_command("/instructions Use Python 3.12.")

        from tests.test_core import FakeStreamResponse
        with patch("hyperflux.core.kobold.requests.post", return_value=FakeStreamResponse()) as post:
            self.engine.query_local_llm("Write a loop.", quiet=True)
        prompt = post.call_args.kwargs["json"]["prompt"]
        self.assertIn("Persona: a senior software engineer", prompt)
        self.assertIn("Use Python 3.12.", prompt)


class ExportTests(_TempSettings, unittest.TestCase):
    def test_export_writes_markdown(self):
        self.assertIn("nothing to export", export_chat(self.engine, self.tmp.name))
        self.engine.chat_history = [{"user": "What is 2+2?", "assistant": "4."}]
        reply = export_chat(self.engine, self.tmp.name, now=datetime.datetime(2026, 11, 18, 9, 30, 5))
        target = Path(self.tmp.name) / "HyperFlux chat 2026-11-18 093005.md"
        self.assertIn(str(target), reply)
        text = target.read_text(encoding="utf-8")
        self.assertIn("## You\n\nWhat is 2+2?", text)
        self.assertIn("## HyperFlux\n\n4.", text)


class VisionAssetTests(unittest.TestCase):
    def setUp(self):
        from hyperflux.desktop import runtime_assets
        self.assets = runtime_assets
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patch = patch.object(runtime_assets, "APP_DATA", self.dir / "appdata")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _file(self, name, size=64):
        path = self.dir / name
        path.write_bytes(b"GGUF" + b"\0" * (size - 4))
        return path

    def test_model_family_and_matching_vision_file(self):
        e4b = self._file("model-e4b.gguf")
        self.assertEqual(self.assets.model_family(e4b), "e4b")
        self.assertEqual(self.assets.model_family(self._file("gemma-4-E2B-it-Q4_K_M.gguf")), "e2b")
        self.assertIsNone(self.assets.model_family(self._file("my-model.gguf")))
        self.assertIsNone(self.assets.vision_file_for(e4b))
        info = self.assets.VISION_FILES["e4b"]
        with patch.object(self.assets, "VISION_FILES", {**self.assets.VISION_FILES, "e4b": {**info, "size": 64}}):
            vision = self._file(info["filename"])  # next to the model
            self.assertEqual(self.assets.vision_file_for(e4b), vision)

    def test_vision_files_are_never_offered_as_chat_models(self):
        model = self._file("model.gguf")
        self._file("mmproj-gemma-4-E4B-it-BF16.gguf")
        with patch.object(self.assets, "find_gguf_models", return_value=[]):
            names = [m["file"] for m in self.assets.describe_local_models(str(model))]
        self.assertEqual(names, ["model.gguf"])

    def test_bridge_vision_routes_need_the_desktop_token(self):
        import threading

        import requests

        from hyperflux.search.bridge import create_search_bridge

        class FakeVision:
            installs = 0
            def describe(self): return {"supported": True, "installed": False, "downloading": False}
            def request_install(self):
                FakeVision.installs += 1
                return True, "Downloading."

        server = create_search_bridge(None, port=0, log_token="tok", vision_manager=FakeVision())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            self.assertEqual(requests.get(base + "/vision", timeout=5).status_code, 403)
            self.assertTrue(requests.get(base + "/vision?token=tok", timeout=5).json()["supported"])
            self.assertEqual(requests.post(base + "/vision/install", timeout=5).status_code, 403)
            self.assertEqual(requests.post(base + "/vision/install?token=tok", timeout=5).status_code, 202)
            self.assertEqual(FakeVision.installs, 1)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
