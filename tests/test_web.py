"""Web API tests. Skipped when FastAPI isn't installed (the CLI needs no dependencies)."""
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from web.app import app
except ImportError:  # pragma: no cover - depends on the environment
    TestClient = None

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tests" / "fixtures" / "tools"
WORKFLOW = ROOT / "tests" / "fixtures" / "workflow.json"


@unittest.skipUnless(TestClient, "fastapi not installed")
class WebApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_page_loads(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Agent Preflight", r.text)

    def test_check_returns_per_tool_findings(self):
        r = self.client.post("/api/check", json={"tools_path": str(TOOLS), "n8n_paths": [str(WORKFLOW)]})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertFalse(d["ready"])
        by_name = {t["name"]: t for t in d["tools"]}
        self.assertEqual(by_name["lookup_contact"]["status"], "pass")
        self.assertEqual(by_name["transfer_call"]["status"], "fail")
        self.assertTrue(any(f["check"] == "n8n.placeholder" for f in d["other_findings"]))

    def test_report_can_be_downloaded_then_missing_id_is_404(self):
        d = self.client.post("/api/check", json={"tools_path": str(TOOLS)}).json()
        md = self.client.get(f"/api/report/{d['report_id']}.md")
        self.assertEqual(md.status_code, 200)
        self.assertIn("# Preflight report:", md.text)
        self.assertEqual(self.client.get("/api/report/nope.md").status_code, 404)

    def test_bad_input_is_rejected(self):
        for payload, reason in (
            ({}, "no source"),
            ({"tools_path": str(TOOLS), "agent_id": "a"}, "both sources"),
            ({"tools_path": str(TOOLS), "probe": True}, "probe with no auth or base url"),
            ({"tools_path": "/nope/does-not-exist"}, "bad path"),
        ):
            with self.subTest(reason=reason):
                self.assertEqual(self.client.post("/api/check", json=payload).status_code, 400)


if __name__ == "__main__":
    unittest.main()
