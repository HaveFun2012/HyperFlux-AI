"""Video input: frames from Windows' own decoder, and the bridge route that serves them."""

import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from hyperflux.desktop import video
from hyperflux.search.bridge import create_search_bridge


class DecoderResultTests(unittest.TestCase):
    def test_frames_become_data_urls_with_their_times(self):
        output = json.dumps({"duration": 9.0, "frames": [{"time": 1.1, "jpeg": "AAAA"}]})
        self.assertEqual(video.parse_result(output),
                         {"duration": 9.0, "frames": [{"time": 1.1, "image": "data:image/jpeg;base64,AAAA"}]})

    def test_failures_are_explained(self):
        for output in (json.dumps({"error": "The parameter is incorrect."}), json.dumps({"frames": []}), "garbage"):
            with self.assertRaises(OSError):
                video.parse_result(output)

    def test_only_video_names_are_accepted(self):
        self.assertTrue(video.is_video_name("Holiday.MP4"))
        self.assertFalse(video.is_video_name("script.ps1"))
        self.assertFalse(video.is_video_name(""))


class VideoRouteTests(unittest.TestCase):
    def setUp(self):
        self.server = create_search_bridge(None, port=0, log_token="tok")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/video/frames"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, query, body=b"x" * 200_000):
        return requests.post(self.base + query, data=body, timeout=10)

    def test_needs_the_desktop_token_and_a_video_name(self):
        self.assertEqual(self.post("?name=a.mp4").status_code, 403)
        self.assertEqual(self.post("?token=tok&name=a.exe").status_code, 415)

    def test_upload_reaches_the_decoder_and_is_deleted_afterwards(self):
        seen = {}

        def fake(path):
            seen["path"] = Path(path)
            seen["bytes"] = Path(path).read_bytes()
            return {"duration": 2.0, "frames": []}

        body = bytes(range(256)) * 9000  # larger than one read
        with patch("hyperflux.desktop.video.extract_frames", side_effect=fake):
            response = self.post("?token=tok&name=..%5C..%5Cclip.mp4", body)
        self.assertEqual(response.json(), {"duration": 2.0, "frames": []})
        self.assertEqual(seen["bytes"], body)
        self.assertTrue(seen["path"].name.startswith("hyperflux-video-"))  # not the name that was sent
        self.assertFalse(seen["path"].exists())

    def test_unreadable_video_is_reported(self):
        with patch("hyperflux.desktop.video.extract_frames", side_effect=OSError("Windows could not read this video")):
            response = self.post("?token=tok&name=a.mp4")
        self.assertEqual(response.status_code, 502)
        self.assertIn("could not read", response.json()["error"])


if __name__ == "__main__":
    unittest.main()
