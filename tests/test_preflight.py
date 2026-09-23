import contextlib
import io
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from preflight import elevenlabs, n8n, report, runner
from preflight.cli import main
from preflight.models import BLOCKER, Param, ToolSpec

FIX = Path(__file__).parent / "fixtures"


def fixture_report():
    return runner.run("fixture", elevenlabs.load_path(FIX / "tools"), n8n.load_files([FIX / "workflow.json"]))


def checks_for(rep, tool):
    return {f.check for f in rep.findings if f.tool == tool}


class StaticChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = fixture_report()

    def test_clean_tool_passes(self):
        self.assertEqual(self.rep.status("lookup_contact"), "pass")
        self.assertEqual(checks_for(self.rep, "lookup_contact"), set())

    def test_seeded_faults_are_blockers(self):
        expected = {
            "check_availability": "url.test_webhook",
            "send_sms_confirmation": "n8n.param_mismatch",
            "transfer_call": "n8n.no_webhook",
            "get_hours": "auth.placeholder",
            "cancel_booking": "n8n.no_response",
        }
        for tool, check in expected.items():
            with self.subTest(tool=tool):
                self.assertIn(check, checks_for(self.rep, tool))
                self.assertEqual(self.rep.status(tool), "fail")

    def test_get_hours_warnings(self):
        self.assertTrue({"desc.weak", "timeout.long", "schema.conv_id_llm"} <= checks_for(self.rep, "get_hours"))

    def test_workflow_placeholder(self):
        self.assertIn("n8n.placeholder", checks_for(self.rep, "workflow: Acme CRM tools"))

    def test_not_ready_and_exit_code(self):
        self.assertFalse(self.rep.ready)
        wf = json.loads((FIX / "workflow.json").read_text())
        wf["nodes"] = [n for n in wf["nodes"] if n["name"] != "Post-call HMAC"]
        clean = FIX / "_clean_workflow_tmp.json"
        clean.write_text(json.dumps(wf))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--tools", str(FIX / "tools"), "--n8n", str(FIX / "workflow.json")]), 1)
                self.assertEqual(main(["--tools", str(FIX / "tools" / "lookup_contact.json"), "--n8n", str(clean)]), 0)
        finally:
            clean.unlink()

    def test_inactive_workflow_blocks(self):
        wf = json.loads((FIX / "workflow.json").read_text()) | {"active": False}
        rep = runner.run("x", elevenlabs.load_path(FIX / "tools" / "lookup_contact.json"), [wf])
        self.assertIn("n8n.inactive", checks_for(rep, "lookup_contact"))

    def test_body_alias_reads(self):
        text = "const b = c.body\nx = b.card_last4; y = $json.body['amount']; const body = hook.body || {}; body.ref"
        self.assertEqual(n8n.body_reads(text), {"card_last4", "amount", "ref"})

    def test_agent_export_with_inline_tools(self):
        tool = json.loads((FIX / "tools" / "lookup_contact.json").read_text())
        agent = {"conversation_config": {"agent": {"prompt": {"tools": [tool, {"type": "system", "name": "end_call"}]}}}}
        path = FIX / "_agent_tmp.json"
        path.write_text(json.dumps(agent))
        try:
            self.assertEqual([t.name for t in elevenlabs.load_path(path)], ["lookup_contact"])
        finally:
            path.unlink()

    def test_markdown_and_json_render(self):
        self.assertIn("Not ready for production", report.to_markdown(self.rep))
        self.assertFalse(json.loads(report.to_json(self.rep))["ready"])


class MockHook(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        route = self.path.rsplit("/", 1)[-1]
        if self.headers.get("Authorization") != "Bearer good":
            return self._send(401, b'{"ok":false}')
        if route == "slow":
            time.sleep(1.5)
        payload = {
            "ok": b'{"found": true, "echo": %s}' % json.dumps(body).encode(),
            "err": b'{"error": "boom"}',
            "big": json.dumps({"rows": "x" * 20_000}).encode(),
            "text": b"Workflow was started",
            "slow": b'{"ok": true}',
        }.get(route)
        self._send(500 if route == "err" else 200 if payload else 404, payload or b"")

    def _send(self, code, data):
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class LiveProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHook)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_probe(self, route, timeout=10, auth="Bearer good", name=None):
        t = ToolSpec(name=name or f"get_{route}", platform="elevenlabs", url=f"https://n8n.acme.com/webhook/t/{route}",
                     timeout_secs=timeout, params=[Param("conversation_id", "body", dynamic_variable="system__conversation_id"),
                                                    Param("kind", "body", enum=["a", "b"])])
        return runner.run("x", [t], live=True, auth_header=auth, base_url=self.base)

    def probe_checks(self, rep):
        return {f.check for f in rep.findings if f.check.startswith("probe.")}

    def test_ok(self):
        rep = self.run_probe("ok")
        self.assertEqual(self.probe_checks(rep), set())
        self.assertEqual(rep.probes[0].status, 200)

    def test_sample_body_uses_dynamic_var_and_enum(self):
        from preflight.probe import build_request
        t = ToolSpec("x", "elevenlabs", "https://h/webhook/a", params=[
            Param("conversation_id", "body", dynamic_variable="system__conversation_id"), Param("kind", "body", enum=["a"])])
        body = json.loads(build_request(t, None, None).data)
        self.assertTrue(body["conversation_id"].startswith("preflight-"))
        self.assertEqual(body["kind"], "a")

    def test_faults(self):
        cases = {"err": "probe.status", "big": "probe.too_big", "text": "probe.not_json", "missing": "probe.not_found"}
        for route, check in cases.items():
            with self.subTest(route=route):
                self.assertIn(check, self.probe_checks(self.run_probe(route)))

    def test_bad_auth(self):
        self.assertIn("probe.auth", self.probe_checks(self.run_probe("ok", auth="Bearer wrong")))

    def test_timeout_is_blocker(self):
        rep = self.run_probe("slow", timeout=1)
        self.assertIn("probe.unreachable", self.probe_checks(rep))
        self.assertTrue(any(f.severity == BLOCKER for f in rep.findings))

    def test_write_tools_skipped_by_default(self):
        rep = self.run_probe("ok", name="create_ticket")
        self.assertTrue(rep.probes[0].skipped)
        self.assertIsNone(rep.probes[0].status)


if __name__ == "__main__":
    unittest.main()
