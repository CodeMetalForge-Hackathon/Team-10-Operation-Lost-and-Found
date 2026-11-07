import unittest
import warnings

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
)

from fastapi.testclient import TestClient

from fusion.server import create_app


class OperatorPageTest(unittest.TestCase):
    def test_page_is_an_operations_overview_not_a_dig_map(self):
        app = create_app()

        with TestClient(app) as client:
            page = client.get("/")

        text = page.text
        self.assertEqual(page.status_code, 200)
        self.assertIn("Operation Lost and Found", text)
        self.assertIn("Operations overview", text)
        self.assertNotIn("Where to dig", text)
        self.assertNotIn("metre grid", text)
        self.assertNotIn("ws://127.0.0.1:8765", text)
        self.assertNotIn("ws://127.0.0.1:8000", text)
        self.assertIn("location.host", text)
        self.assertIn(
            "Acoustic cues require verification. Positions are not available.",
            text,
        )
        self.assertIn("msg.v !== 1", text)
        self.assertNotIn("data-cmd=", text)
        self.assertIn('id="replay"', text)
        self.assertIn("hidden", text)
        self.assertIn("/demo", text)
