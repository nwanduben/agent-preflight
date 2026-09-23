"""Hosted mode: login required, no filesystem paths, and no calls to private addresses."""
import importlib
import json
import os
import unittest
from pathlib import Path

from preflight import net

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - depends on the environment
    TestClient = None

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tests" / "fixtures" / "tools"
UPLOADS = [{"name": p.name, "content": p.read_text()} for p in sorted(TOOLS.glob("*.json"))]


class AddressRules(unittest.TestCase):
    def test_public_https_is_allowed(self):
        self.assertEqual(net.check_url("https://example.com/webhook/x", public_only=True), "")

    def test_private_and_local_addresses_are_blocked(self):
        for url in ("https://127.0.0.1/webhook/x", "https://localhost/x", "https://192.168.1.10/x",
                    "https://169.254.169.254/latest/meta-data", "https://metadata.google.internal/x"):
            with self.subTest(url=url):
                self.assertTrue(net.check_url(url, public_only=True))

    def test_http_and_odd_schemes_are_blocked(self):
        self.assertTrue(net.check_url("http://example.com/x", public_only=True))
        self.assertTrue(net.check_url("file:///etc/passwd", public_only=True))

    def test_local_mode_allows_everything_http(self):
        self.assertEqual(net.check_url("http://127.0.0.1:8099/webhook/x", public_only=False), "")


@unittest.skipUnless(TestClient, "fastapi not installed")
class HostedApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update(PREFLIGHT_MODE="hosted", PREFLIGHT_PASSWORD="letmein")
        import web.app
        cls.module = importlib.reload(web.app)
        cls.client = TestClient(cls.module.app)
        cls.auth = ("me", "letmein")

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PREFLIGHT_MODE", None)
        os.environ.pop("PREFLIGHT_PASSWORD", None)
        importlib.reload(cls.module)

    def test_login_required(self):
        self.assertEqual(self.client.get("/").status_code, 401)
        self.assertEqual(self.client.post("/api/check", json={"tools_files": UPLOADS}).status_code, 401)
        self.assertEqual(self.client.get("/", auth=self.auth).status_code, 200)

    def test_wrong_password_rejected(self):
        self.assertEqual(self.client.get("/", auth=("me", "nope")).status_code, 401)

    def test_health_is_open(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_uploads_are_checked(self):
        r = self.client.post("/api/check", json={"tools_files": UPLOADS, "name": "uploaded"}, auth=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(len(d["tools"]), len(UPLOADS))
        self.assertFalse(d["ready"])  # the fixtures carry planted faults

    def test_paths_refused_when_hosted(self):
        r = self.client.post("/api/check", json={"tools_path": str(TOOLS)}, auth=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertIn("upload", r.json()["detail"].lower())

    def test_private_base_url_refused(self):
        r = self.client.post("/api/check", json={"tools_files": UPLOADS, "probe": True,
                                                 "base_url": "http://127.0.0.1:8099"}, auth=self.auth)
        self.assertEqual(r.status_code, 400)

    def test_broken_json_upload_is_explained(self):
        r = self.client.post("/api/check", json={"tools_files": [{"name": "bad.json", "content": "{oops"}]},
                             auth=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertIn("bad.json", r.json()["detail"])

    def test_probe_skips_private_tool_urls(self):
        tool = json.loads((TOOLS / "lookup_contact.json").read_text())
        tool["api_schema"]["url"] = "https://192.168.1.50/webhook/crm/lookup_contact"
        r = self.client.post("/api/check", json={"tools_files": [{"name": "t.json", "content": json.dumps(tool)}],
                                                 "probe": True, "auth_header": "Bearer x"}, auth=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["probes"][0]["skipped"])


if __name__ == "__main__":
    unittest.main()
