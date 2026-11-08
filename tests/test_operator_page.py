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
            script = client.get("/assets/review.js")
            chart = client.get("/assets/vendor/echarts.min.js")

        text = page.text + script.text
        self.assertEqual(page.status_code, 200)
        self.assertEqual(script.status_code, 200)
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
        self.assertIn("/assets/vendor/echarts.min.js", page.text)
        self.assertIn("/assets/vendor/tabler.min.css", page.text)
        self.assertNotIn("cdn.", page.text)
        self.assertNotIn("fonts.googleapis", page.text)
        self.assertEqual(chart.status_code, 200)
        self.assertGreater(len(chart.content), 100000)


class ReviewPolicyTest(unittest.TestCase):
    def test_selection_window_and_replay_detection(self):
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        done = subprocess.run(
            ["node", "tests/review_policy_check.cjs"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("review policy ok", done.stdout)
