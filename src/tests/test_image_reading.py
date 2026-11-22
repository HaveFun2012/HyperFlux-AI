"""Image reading without a vision model: Windows OCR, and the image-helper routes."""

import threading
import unittest
from unittest.mock import patch

import requests

from hyperflux.desktop import ocr
from hyperflux.search.bridge import create_search_bridge


def word(text, x, y, h=10):
    return {"t": text, "x": x, "y": y, "h": h}


class OcrTests(unittest.TestCase):
    def test_words_on_one_row_are_joined_in_reading_order(self):
        # OCR hands back a receipt column by column; people read it by row.
        words = [word("Teh", 0, 0), word("Nasi", 0, 20), word("3.50", 90, 1), word("6.00", 90, 21), word("tarik", 30, 0),
                 word("lemak", 30, 21)]
        self.assertEqual(ocr.group_rows(words), "Teh tarik 3.50\nNasi lemak 6.00")

    def test_no_words_is_no_text(self):
        self.assertEqual(ocr.group_rows([]), "")

    def test_small_text_prefers_the_enlarged_reading(self):
        small = [word("a", 0, 0, 6)] * 3
        enlarged = [word("a", 0, 0, 6)] * 19
        self.assertEqual(ocr.choose_pass([{"scale": 1, "words": small}, {"scale": 3, "words": enlarged}]), enlarged)
        # ...unless it lost most of the words
        poor = [word("a", 0, 0, 6)] * 2
        full = [word("a", 0, 0, 6)] * 10
        self.assertEqual(ocr.choose_pass([{"scale": 1, "words": full}, {"scale": 3, "words": poor}]), full)

    def test_normal_text_keeps_the_original_reading(self):
        original = [word("a", 0, 0, 16)] * 5
        enlarged = [word("b", 0, 0, 16)] * 9
        self.assertEqual(ocr.choose_pass([{"scale": 1, "words": original}, {"scale": 3, "words": enlarged}]), original)

    def test_bad_pictures_are_refused(self):
        for bad in (None, "no comma", "data:image/png;base64,"):
            with self.assertRaises(ValueError):
                ocr.read_data_url(bad)

    @unittest.skipUnless(__import__("sys").platform == "win32", "Windows OCR")
    def test_reads_text_from_a_real_picture(self):
        import base64
        import io
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self.skipTest("Pillow is not installed")
        picture = Image.new("RGB", (420, 80), "white")
        ImageDraw.Draw(picture).text((10, 20), "HYPERFLUX 1234", fill="black", font=ImageFont.load_default(size=36))
        buffer = io.BytesIO()
        picture.save(buffer, "PNG")
        text = ocr.read_data_url("data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode())
        self.assertIn("1234", text)


class BridgeImageTests(unittest.TestCase):
    def setUp(self):
        class FakeHelper:
            calls = []
            def describe(self): return {"enabled": True, "status": "sleeping"}
            def request_enable(self): self.calls.append("enable"); return True, "Starting."
            def request_disable(self): self.calls.append("disable"); return True, "Off."
            def wake(self): self.calls.append("wake"); return True
            def touch(self): self.calls.append("used")

        self.helper = FakeHelper()
        self.server = create_search_bridge(None, port=0, log_token="tok", image_helper=self.helper)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_image_helper_routes_need_the_desktop_token(self):
        self.assertEqual(requests.get(self.base + "/image-helper", timeout=5).status_code, 403)
        self.assertEqual(requests.get(self.base + "/image-helper?token=tok", timeout=5).json()["status"], "sleeping")
        self.assertEqual(requests.post(self.base + "/image-helper/enable", timeout=5).status_code, 403)
        self.assertEqual(requests.post(self.base + "/image-helper/enable?token=tok", timeout=5).status_code, 202)
        self.assertEqual(requests.post(self.base + "/image-helper/wake?token=tok", timeout=5).json(), {"accepted": True})
        requests.post(self.base + "/image-helper/used?token=tok", timeout=5)
        requests.post(self.base + "/image-helper/disable?token=tok", timeout=5)
        self.assertEqual(self.helper.calls, ["enable", "wake", "used", "disable"])

    def test_read_image_needs_the_token_and_returns_the_text(self):
        body = {"image": "data:image/png;base64,AAAA"}
        self.assertEqual(requests.post(self.base + "/image/read", json=body, timeout=5).status_code, 403)
        with patch("hyperflux.desktop.ocr.read_data_url", return_value="XYZ: 1 2 3") as reader:
            response = requests.post(self.base + "/image/read?token=tok", json=body, timeout=5)
        self.assertEqual(response.json(), {"text": "XYZ: 1 2 3"})
        reader.assert_called_once_with("data:image/png;base64,AAAA")

    def test_read_image_reports_a_failing_reader(self):
        with patch("hyperflux.desktop.ocr.read_data_url", side_effect=OSError("no OCR language")):
            response = requests.post(self.base + "/image/read?token=tok", json={"image": "data:,x"}, timeout=5)
        self.assertEqual(response.status_code, 502)


@unittest.skipUnless(__import__("importlib").util.find_spec("PySide6"), "needs PySide6")
class HelperHardwareTests(unittest.TestCase):
    def test_hardware_verdict(self):
        from hyperflux.desktop.image_helper import hardware_verdict
        self.assertFalse(hardware_verdict(4, 2)["ok"])
        self.assertTrue(hardware_verdict(8, 5)["ok"])
        slow = hardware_verdict(8, 1.2)
        self.assertTrue(slow["ok"])
        self.assertIn("slowly", slow["note"])
        self.assertTrue(hardware_verdict(None, None)["ok"])


if __name__ == "__main__":
    unittest.main()
