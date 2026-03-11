import unittest
from unittest.mock import Mock
import requests

from utils.youtube_api import YouTubeAPI


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class TestYouTubeAPIFallback(unittest.TestCase):
    def test_fallback_to_alternative_key_on_403(self):
        api = YouTubeAPI(api_key="primary_key")
        api.api_key_alt = "alt_key"

        keys_used = []

        def _request(url, params, key):
            keys_used.append(key)
            if len(keys_used) == 1:
                return _FakeResponse(403, {
                    "error": {
                        "message": "The request cannot be completed because you have exceeded your quota.",
                        "errors": [{"reason": "quotaExceeded"}],
                    }
                })
            return _FakeResponse(200, {"items": []})

        api._request = Mock(side_effect=_request)

        data = api._get("search", {"part": "snippet"})

        self.assertEqual(keys_used, ["primary_key", "alt_key"])
        self.assertEqual(data, {"items": []})


if __name__ == "__main__":
    unittest.main()
