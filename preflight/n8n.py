"""Index the n8n webhooks a voice agent's tools point at, from exports or the n8n API."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .models import WebhookNode

PLACEHOLDER = re.compile(r"\b(?:PASTE_[A-Z0-9_]+|REPLACE_[A-Z0-9_]+|YOUR_[A-Z0-9_]+|CHANGE_?ME)\b")
ALIAS = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*[\w$.()'\"\[\]]*\.body\b(?!\.)")
READ = r"(?:\.(\w+)|\[\s*['\"](\w+)['\"]\s*\])"


def _downstream(workflow: dict, start: str) -> list[str]:
    conns = workflow.get("connections", {})
    seen, queue = [start], [start]
    while queue:
        for outputs in conns.get(queue.pop(0), {}).values():
            for branch in outputs or []:
                for link in branch or []:
                    if link["node"] not in seen:
                        seen.append(link["node"])
                        queue.append(link["node"])
    return seen


def body_reads(text: str) -> set[str]:
    """Field names the workflow reads off the incoming webhook body."""
    names = {"body"} | set(ALIAS.findall(text))
    reads = set()
    for name in names:
        for a, b in re.findall(rf"(?<![\w.]){re.escape(name)}{READ}", text):
            reads.add(a or b)
    for a, b in re.findall(rf"\.body{READ}", text):
        reads.add(a or b)
    return reads


def index_workflow(workflow: dict) -> list[WebhookNode]:
    nodes = {n["name"]: n for n in workflow.get("nodes", [])}
    out = []
    for n in nodes.values():
        if n.get("type") != "n8n-nodes-base.webhook":
            continue
        p = n.get("parameters", {})
        down = _downstream(workflow, n["name"])
        text = "\n".join(json.dumps(nodes[d].get("parameters", {})) for d in down if d in nodes)
        # json.dumps escapes quotes inside Code nodes; undo that so regexes see real source.
        text = text.encode().decode("unicode_escape", errors="ignore")
        out.append(WebhookNode(
            workflow=workflow.get("name", "?"),
            workflow_active=workflow.get("active"),
            node=n["name"],
            path=str(p.get("path", "")).strip("/"),
            method=str(p.get("httpMethod", "GET")).upper(),
            auth=p.get("authentication", "none"),
            response_mode=p.get("responseMode", "onReceived"),
            disabled=bool(n.get("disabled")),
            reachable_nodes=down,
            reachable_text=text,
            body_reads=body_reads(text),
            has_respond_node=any(
                nodes[d].get("type") == "n8n-nodes-base.respondToWebhook" and not nodes[d].get("disabled")
                for d in down if d in nodes
            ),
        ))
    return out


def placeholders(workflow: dict) -> list[tuple[str, str]]:
    """(node, placeholder) pairs for unfilled template values."""
    hits = []
    for n in workflow.get("nodes", []):
        for m in sorted(set(PLACEHOLDER.findall(json.dumps(n.get("parameters", {}))))):
            hits.append((n["name"], m))
    return hits


def load_files(paths: list[str]) -> list[dict]:
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    return [json.loads(f.read_text()) for f in files]


def load_api(base_url: str, api_key: str) -> list[dict]:
    """Read-only: lists every workflow with its nodes via the n8n public API."""
    workflows, cursor = [], None
    while True:
        q = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        url = f"{base_url.rstrip('/')}/api/v1/workflows?{urllib.parse.urlencode(q)}"
        req = urllib.request.Request(url, headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            page = json.loads(r.read())
        workflows += page.get("data", [])
        cursor = page.get("nextCursor")
        if not cursor:
            return workflows
