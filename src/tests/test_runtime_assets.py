import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyperflux.desktop import runtime_assets


class _FakeResponse:
    def __init__(self, chunks, status_code=200, headers=None):
        self.chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


def _write_fake_executable(path):
    dos_header = bytearray(64)
    dos_header[:2] = b"MZ"
    dos_header[60:64] = (64).to_bytes(4, "little")
    path.write_bytes(dos_header + b"PE\0\0\x64\x86")


class HyperFluxSetupTests(unittest.TestCase):
    def test_asset_signatures_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model.gguf"
            executable = Path(directory) / "koboldcpp.exe"
            model.write_bytes(b"GGUFtest")
            _write_fake_executable(executable)
            self.assertTrue(runtime_assets.is_gguf(model))
            self.assertTrue(runtime_assets.is_windows_executable(executable))
            model.write_bytes(b"nope")
            executable.write_bytes(b"nope")
            self.assertFalse(runtime_assets.is_gguf(model))
            self.assertFalse(runtime_assets.is_windows_executable(executable))

    def test_local_gguf_discovery_lists_available_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            downloads = home / "Downloads"
            downloads.mkdir(parents=True)
            first_model = downloads / "local-one.gguf"
            second_model = downloads / "local-two.gguf"
            first_model.write_bytes(b"GGUF-one")
            second_model.write_bytes(b"GGUF-two")
            with (
                patch.object(runtime_assets.Path, "home", return_value=home),
                patch.object(runtime_assets.Path, "cwd", return_value=root),
                patch.object(runtime_assets, "APP_DATA", root / "data"),
            ):
                found = runtime_assets.find_gguf_models()
            self.assertEqual(set(found), {first_model, second_model})

    def test_download_verifies_hash_and_size(self):
        content = b"verified model bytes"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asset.gguf"
            response = _FakeResponse([content[:5], content[5:]])
            with patch("hyperflux.desktop.runtime_assets.requests.get", return_value=response):
                runtime_assets.download(
                    "https://example.invalid/asset",
                    destination,
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                    lambda _value: None,
                    lambda _message: None,
                    lambda: False,
                )
            self.assertEqual(destination.read_bytes(), content)
            self.assertFalse(destination.with_suffix(".gguf.part").exists())
            self.assertTrue(response.closed)

    def test_download_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asset.gguf"
            destination.write_bytes(b"user data")
            with self.assertRaises(FileExistsError):
                runtime_assets.download(
                    "https://example.invalid/asset",
                    destination,
                    9,
                    "",
                    lambda _value: None,
                    lambda _message: None,
                    lambda: False,
                )
            self.assertEqual(destination.read_bytes(), b"user data")

    def test_hash_failure_removes_bad_complete_partial(self):
        content = b"unverified bytes"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asset.gguf"
            partial = destination.with_suffix(".gguf.part")
            with patch(
                "hyperflux.desktop.runtime_assets.requests.get",
                return_value=_FakeResponse([content]),
            ):
                with self.assertRaisesRegex(OSError, "SHA-256"):
                    runtime_assets.download(
                        "https://example.invalid/asset",
                        destination,
                        len(content),
                        "0" * 64,
                        lambda _value: None,
                        lambda _message: None,
                        lambda: False,
                    )
            self.assertFalse(partial.exists())
            self.assertFalse(destination.exists())

    def test_interrupted_download_resumes_from_partial_file(self):
        content = b"download that can resume"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asset.gguf"
            partial = destination.with_suffix(".gguf.part")
            first_response = _FakeResponse([content[:8], content[8:12]])
            cancellation_checks = iter([False, True])
            with patch(
                "hyperflux.desktop.runtime_assets.requests.get",
                return_value=first_response,
            ):
                with self.assertRaises(InterruptedError):
                    runtime_assets.download(
                        "https://example.invalid/asset",
                        destination,
                        len(content),
                        hashlib.sha256(content).hexdigest(),
                        lambda _value: None,
                        lambda _message: None,
                        lambda: next(cancellation_checks),
                    )
            self.assertEqual(partial.read_bytes(), content[:8])

            resume_response = _FakeResponse(
                [content[8:]],
                status_code=206,
                headers={"Content-Range": f"bytes 8-{len(content) - 1}/{len(content)}"},
            )
            with patch(
                "hyperflux.desktop.runtime_assets.requests.get",
                return_value=resume_response,
            ) as get:
                runtime_assets.download(
                    "https://example.invalid/asset",
                    destination,
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                    lambda _value: None,
                    lambda _message: None,
                    lambda: False,
                )
            self.assertEqual(get.call_args.kwargs["headers"], {"Range": "bytes=8-"})
            self.assertEqual(destination.read_bytes(), content)
            self.assertFalse(partial.exists())

    def test_runtime_config_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            executable = root / "koboldcpp.exe"
            model.write_bytes(b"GGUFmodel")
            _write_fake_executable(executable)
            with (
                patch.object(runtime_assets, "APP_DATA", root / "data"),
                patch.object(runtime_assets, "RUNTIME_CONFIG", root / "data" / "runtime.json"),
            ):
                runtime_assets.save_config(model, executable)
                loaded = runtime_assets.load_config()
            self.assertEqual(Path(loaded["model_path"]), model.resolve())
            self.assertEqual(Path(loaded["kobold_path"]), executable.resolve())

    def test_runtime_config_accepts_string_paths(self):
        # The setup wizard passes plain strings; this used to crash and freeze setup.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            executable = root / "koboldcpp.exe"
            model.write_bytes(b"GGUFmodel")
            _write_fake_executable(executable)
            with (
                patch.object(runtime_assets, "APP_DATA", root / "data"),
                patch.object(runtime_assets, "RUNTIME_CONFIG", root / "data" / "runtime.json"),
            ):
                runtime_assets.save_config(str(model), str(executable))
                loaded = runtime_assets.load_config()
            self.assertEqual(Path(loaded["model_path"]), model.resolve())


if __name__ == "__main__":
    unittest.main()
