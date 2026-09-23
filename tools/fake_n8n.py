"""A stand-in for n8n: answers a voice agent's webhook paths so probes can be tested safely.

It reads the agent's tool files, serves every path they point at, and can be told to misbehave
on chosen tools so you can see the checker catch each fault.

  python3 tools/fake_n8n.py --tools "<agent>/agent/tools" --port 8099 \
      --slow verify_caller --error create_ticket --big get_ticket_status --text assess_request \
      --missing find_branch_or_atm --secret "Bearer test-secret"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from preflight import elevenlabs  # noqa: E402

REPLY = {  # what a healthy ENTIN-style workflow would say back to the agent
    "verify_caller": {"verified": True, "tier": "T2", "customer_name": "Gerald A.", "spoken": "Thanks Gerald, you're verified."},
    "find_transactions": {"matches": [{"txn_id": "TXN-99012", "amount_naira": 45000, "status": "FAILED"}],
                          "spoken": "I found a failed transfer of 45,000 naira yesterday."},
    "block_card": {"blocked": ["1234"], "ticket": "TKT-00891", "spoken": "That card is blocked now."},
}
DEFAULT = {"ok": True, "spoken": "Done."}


def make_handler(paths: dict[str, str], faults: dict[str, str], secret: str | None, delay: float):
    class Handler(BaseHTTPRequestHandler):
        server_version = "fake-n8n/0.1"

        def log_message(self, fmt, *args):
            print(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}", file=sys.stderr)

        def do_GET(self):
            self._handle(b"")

        def do_POST(self):
            self._handle(self.rfile.read(int(self.headers.get("Content-Length") or 0)))

        def _handle(self, raw):
            path = self.path.split("?")[0].strip("/")
            tool = paths.get(path)
            if tool is None or faults.get(tool) == "missing":
                return self._send(404, {"message": "This webhook is not registered"})
            if secret and self.headers.get("Authorization") != secret:
                return self._send(403, {"message": "Authorization data is wrong"})

            fault = faults.get(tool)
            if fault == "slow":
                time.sleep(delay)
            if fault == "error":
                return self._send(500, {"message": "Error in workflow"})
            if fault == "text":
                return self._send(200, "Workflow was started", raw_text=True)
            if fault == "big":
                return self._send(200, {"rows": [{"txn_id": f"TXN-{i:05d}", "note": "x" * 80} for i in range(200)]})

            body = json.loads(raw or b"{}") if raw else {}
            reply = dict(REPLY.get(tool, DEFAULT))
            reply["tool"] = tool
            reply["received"] = sorted(body)
            self._send(200, reply)

        def _send(self, code, payload, raw_text=False):
            data = payload.encode() if raw_text else json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain" if raw_text else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tools", required=True, help="Folder of agent tool files (or an exported agent JSON)")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--secret", help="Require this exact Authorization header")
    ap.add_argument("--delay", type=float, default=6.0, help="Seconds a --slow tool waits (default 6)")
    for fault, help_text in (("slow", "answers after --delay seconds"), ("error", "returns HTTP 500"),
                             ("big", "returns a reply far over the size limit"), ("text", "returns plain text, not JSON"),
                             ("missing", "returns 404, as an inactive workflow would")):
        ap.add_argument(f"--{fault}", action="append", default=[], metavar="TOOL", help=f"Tool that {help_text}")
    args = ap.parse_args(argv)

    tools = elevenlabs.load_path(args.tools)
    if not tools:
        print("No webhook tools found", file=sys.stderr)
        return 2
    paths = {t.url.split("://", 1)[-1].split("/", 1)[-1].strip("/"): t.name for t in tools}
    faults = {name: fault for fault in ("slow", "error", "big", "text", "missing") for name in getattr(args, fault)}
    unknown = sorted(set(faults) - {t.name for t in tools})
    if unknown:
        print(f"Unknown tool name(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(paths, faults, args.secret, args.delay))
    print(f"Fake n8n on http://127.0.0.1:{args.port} serving {len(paths)} paths"
          + (f"; faults: {faults}" if faults else "") + "\nCtrl-C to stop", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
