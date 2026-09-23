"""End to end: the fake n8n server stands in for the real one, and the probe grades it."""
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from preflight import elevenlabs, runner

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tests" / "fixtures" / "tools"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeServerEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "tools" / "fake_n8n.py"), "--tools", str(TOOLS), "--port", str(cls.port),
             "--secret", "Bearer test", "--error", "cancel_booking", "--text", "get_hours",
             "--missing", "lookup_contact", "--big", "send_sms_confirmation"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/ping", timeout=1)
            except urllib.error.HTTPError:
                return  # answering (404 for an unknown path) means it is up
            except OSError:
                time.sleep(0.1)
        cls.tearDownClass()
        raise AssertionError("fake server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def report(self, auth="Bearer test"):
        return runner.run("fake", elevenlabs.load_path(TOOLS), live=True, auth_header=auth,
                          base_url=f"http://127.0.0.1:{self.port}", allow_writes=True)

    def test_each_planted_server_fault_is_caught(self):
        by_tool = {}
        for f in self.report().findings:
            by_tool.setdefault(f.tool, set()).add(f.check)
        for tool, check in (("cancel_booking", "probe.status"), ("get_hours", "probe.not_json"),
                            ("lookup_contact", "probe.not_found"), ("send_sms_confirmation", "probe.too_big")):
            with self.subTest(tool=tool):
                self.assertIn(check, by_tool.get(tool, set()))

    def test_healthy_tool_answers_with_the_fields_it_was_sent(self):
        probe = next(p for p in self.report().probes if p.tool == "transfer_call")
        self.assertEqual((probe.status, probe.is_json), (200, True))

    def test_wrong_secret_is_rejected(self):
        checks = {f.check for f in self.report(auth="Bearer wrong").findings}
        self.assertIn("probe.auth", checks)


if __name__ == "__main__":
    unittest.main()
