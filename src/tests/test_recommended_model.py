"""The Unsloth dynamic E4B is HyperFlux's recommended optional model, and runs at temperature 0.5."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyperflux.desktop import runtime_assets


def gguf(directory, name):
    path = Path(directory) / name
    path.write_bytes(b"GGUF" + b"x" * 64)
    return path.resolve()


class RecommendedModelTests(unittest.TestCase):
    def test_pinned_entry_is_the_unsloth_dynamic_file(self):
        info = runtime_assets.GEMMA_MODELS["e4b"]
        self.assertEqual(info["filename"], "gemma-4-E4B-it-UD-Q4_K_XL.gguf")
        self.assertIn("unsloth/gemma-4-E4B-it-GGUF/resolve/bfc15c382204943c3a8fff0c750b94ae2364d7a3/", info["url"])
        self.assertEqual(info["size"], 5_126_306_944)
        self.assertEqual(info["temperature"], 0.5)
        self.assertNotIn("temperature", runtime_assets.GEMMA_MODELS["e2b"])

    def test_only_the_recommended_file_gets_a_temperature(self):
        with tempfile.TemporaryDirectory() as directory:
            ud = gguf(directory, "gemma-4-E4B-it-UD-Q4_K_XL.gguf")
            old = gguf(directory, "gemma-4-E4B-it-Q4_K_M.gguf")
            e2b = gguf(directory, "gemma-4-E2B-it-Q4_K_M.gguf")
            with patch.object(runtime_assets, "find_gguf_models", return_value=[ud, old, e2b]):
                models = {m["file"]: m for m in runtime_assets.describe_local_models(str(ud))}
        self.assertEqual(models[ud.name]["temperature"], 0.5)
        self.assertEqual(models[ud.name]["name"], "Gemma 4 E4B")
        self.assertNotIn("temperature", models[old.name])
        self.assertEqual(models[old.name]["name"], "Gemma 4 E4B")  # earlier downloads keep working
        self.assertNotIn("temperature", models[e2b.name])

    def test_renamed_file_of_the_exact_size_is_still_recognised(self):
        with tempfile.TemporaryDirectory() as directory:
            renamed = gguf(directory, "model.gguf")
            with patch.dict(runtime_assets.GEMMA_MODELS["e4b"], {"size": renamed.stat().st_size}):
                self.assertEqual(runtime_assets.recommended_temperature(renamed), 0.5)
                self.assertEqual(runtime_assets.model_family(renamed), "e4b")

    def test_earlier_e4b_download_is_still_an_e4b(self):
        with tempfile.TemporaryDirectory() as directory:
            old = gguf(directory, "gemma-4-E4B-it-Q4_K_M.gguf")
            self.assertEqual(runtime_assets.model_family(old), "e4b")
            self.assertIsNone(runtime_assets.recommended_temperature(old))


if __name__ == "__main__":
    unittest.main()
