"""Opt-in live probe: call each tool URL the way the voice platform would and measure the reply."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .models import BLOCKER, WARN, Finding, ProbeResult, ToolSpec

# Tools that change data are skipped unless the user passes --allow-writes.
WRITE_VERB = re.compile(r"^(create|block|update|delete|cancel|book|send|report|request|submit|add|remove|transfer|pay)_")
MAX_RESPONSE_CHARS = 15_000  # Retell's documented cap; a sane budget for any voice agent


def sample_value(p) -> object:
    if p.dynamic_variable:
        return f"preflight-{uuid.uuid4().hex[:8]}" if "conversation_id" in p.dynamic_variable else f"preflight-{p.dynamic_variable}"
    if p.enum:
        return p.enum[0]
    return {"number": 1, "integer": 1, "boolean": False, "array": [], "object": {}}.get(p.type, "preflight-test")


def build_request(t: ToolSpec, auth_header: str | None, base_url: str | None) -> urllib.request.Request:
    url = t.url
    if base_url:
        u = urllib.parse.urlparse(url)
        url = base_url.rstrip("/") + u.path + (f"?{u.query}" if u.query else "")
    for p in t.params:
        if p.location == "path":
            url = url.replace("{" + p.name + "}", urllib.parse.quote(str(sample_value(p))))
    query = {p.name: sample_value(p) for p in t.params if p.location == "query"}
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    body = {p.name: sample_value(p) for p in t.params if p.location == "body"}
    headers = {"Content-Type": "application/json", "User-Agent": "agent-preflight/0.1"}
    for name, value in t.headers.items():
        if isinstance(value, str) and name.lower() != "authorization":
            headers[name] = value
    if auth_header:
        headers["Authorization"] = auth_header
    data = json.dumps(body).encode() if t.method in ("POST", "PUT", "PATCH") else None
    return urllib.request.Request(url, data=data, headers=headers, method=t.method)


def probe(t: ToolSpec, auth_header: str | None = None, base_url: str | None = None,
          allow_writes: bool = False) -> tuple[ProbeResult, list[Finding]]:
    r = ProbeResult(tool=t.name)
    if WRITE_VERB.match(t.name) and not allow_writes:
        r.skipped = "changes data; rerun with --allow-writes against a test copy"
        return r, []
    timeout = t.timeout_secs or 20
    start = time.monotonic()
    try:
        with urllib.request.urlopen(build_request(t, auth_header, base_url), timeout=timeout) as resp:
            r.status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        with e:
            r.status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        r.latency_ms = int((time.monotonic() - start) * 1000)
        reason = getattr(e, "reason", e)
        r.error = "timed out" if "timed out" in str(reason) else str(reason)
        return r, [Finding(t.name, "probe.unreachable", BLOCKER,
                           f"Live call failed after {r.latency_ms} ms: {r.error}",
                           "Check the URL, that the workflow is active, and the timeout")]
    r.latency_ms = int((time.monotonic() - start) * 1000)
    text = raw.decode("utf-8", errors="replace")
    r.size = len(text)
    try:
        json.loads(text)
        r.is_json = True
    except ValueError:
        r.is_json = False

    f = []
    add = lambda check, sev, msg, fix="": f.append(Finding(t.name, check, sev, msg, fix))
    if r.status in (401, 403):
        add("probe.auth", BLOCKER, f"Webhook rejected the request ({r.status})",
            "Make the tool's Authorization secret match the n8n credential")
    elif r.status == 404:
        add("probe.not_found", BLOCKER, "Webhook returned 404: wrong path or the workflow is not active",
            "Activate the workflow and check the path")
    elif not 200 <= r.status < 300:
        add("probe.status", BLOCKER, f"Webhook returned HTTP {r.status}", "Open the failed execution in n8n")
    if r.size > MAX_RESPONSE_CHARS:
        add("probe.too_big", BLOCKER, f"Response is {r.size:,} characters (limit {MAX_RESPONSE_CHARS:,})",
            "Return only the fields the agent needs to say")
    if 200 <= r.status < 300 and not r.is_json:
        add("probe.not_json", WARN, "Response is not JSON, so the agent can't read fields from it",
            "Respond with a JSON object")
    if r.latency_ms > 3000:
        add("probe.slow", WARN, f"Took {r.latency_ms / 1000:.1f}s; the caller hears silence meanwhile",
            "Speed up the workflow or add a 'one moment' message before the tool runs")
    return r, f
