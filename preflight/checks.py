"""Static checks: tool config on its own, then tool config against the n8n workflow behind it."""
from __future__ import annotations

import difflib
import re
from urllib.parse import urlparse

from .models import BLOCKER, INFO, WARN, Finding, ToolSpec, WebhookNode
from .n8n import PLACEHOLDER

LOCAL_HOSTS = re.compile(r"(^localhost$|^127\.|^0\.0\.0\.0$|^192\.168\.|^10\.|\.local$|ngrok|trycloudflare\.com$|loca\.lt$)")
URL_PLACEHOLDER = re.compile(r"(your-n8n|example\.com|<[^>]+>|\{\{|REPLACE|CHANGEME)", re.I)
SLOW_SECS = 20  # beyond this the caller hears a long silence


def webhook_path(url: str) -> tuple[str, str]:
    """('webhook' | 'webhook-test' | '', path after it)."""
    m = re.search(r"/(webhook-test|webhook)/(.+?)/?$", urlparse(url).path)
    return (m.group(1), m.group(2)) if m else ("", "")


def check_tool(t: ToolSpec) -> list[Finding]:
    f = []
    add = lambda check, sev, msg, fix="": f.append(Finding(t.name, check, sev, msg, fix))
    u = urlparse(t.url)

    if not t.url:
        add("url.missing", BLOCKER, "Tool has no URL", "Set the webhook URL on the tool")
        return f
    if URL_PLACEHOLDER.search(t.url):
        add("url.placeholder", BLOCKER, f"URL still has a placeholder: {t.url}", "Replace it with the real n8n host")
    if u.scheme != "https":
        add("url.not_https", BLOCKER, f"URL is {u.scheme or 'missing a scheme'}, not https", "Serve the webhook over https")
    if u.hostname and LOCAL_HOSTS.search(u.hostname):
        add("url.local", BLOCKER, f"URL points at a local or tunnel host ({u.hostname})",
            "Use the production n8n domain; tunnels die when your laptop sleeps")
    kind, path = webhook_path(t.url)
    if kind == "webhook-test":
        add("url.test_webhook", BLOCKER, "URL uses the n8n test webhook, which only listens while the editor is open",
            f"Change /webhook-test/{path} to /webhook/{path} and activate the workflow")

    for name, value in t.headers.items():
        secret = value.get("secret_id", "") if isinstance(value, dict) else str(value)
        if not secret or PLACEHOLDER.search(secret) or URL_PLACEHOLDER.search(secret):
            add("auth.placeholder", BLOCKER, f"Header '{name}' has no real secret ({secret or 'empty'})",
                "Create the secret in ElevenLabs and select it on this header")
        elif not isinstance(value, dict) and name.lower() == "authorization":
            add("auth.plaintext", WARN, "Authorization header is stored as plain text on the tool",
                "Store it as an ElevenLabs secret instead")

    if len(t.description.strip()) < 20:
        add("desc.weak", WARN, "Description is missing or too short for the LLM to know when to call this tool",
            "Say what the tool does and when to use it, in one or two sentences")
    if t.timeout_secs is None:
        add("timeout.default", INFO, "No response timeout set; the platform default applies")
    elif t.timeout_secs > SLOW_SECS:
        add("timeout.long", WARN, f"Timeout is {t.timeout_secs:g}s; the caller may sit in silence that long",
            f"Keep it at {SLOW_SECS}s or less and make the workflow faster")

    for name in t.required_missing:
        add("schema.required_undefined", BLOCKER, f"'{name}' is required but not defined as a parameter",
            f"Define '{name}' or remove it from required")
    for p in t.params:
        if not p.dynamic_variable and not p.description.strip():
            add("schema.param_no_desc", WARN, f"Parameter '{p.name}' has no description, so the LLM has to guess it",
                f"Describe the format of '{p.name}', e.g. YYYY-MM-DD")
        if "conversation_id" in p.name and not p.dynamic_variable:
            add("schema.conv_id_llm", WARN, f"'{p.name}' is filled by the LLM, which can invent it",
                "Bind it to the dynamic variable system__conversation_id")
        if p.enum is not None and not p.enum:
            add("schema.empty_enum", BLOCKER, f"'{p.name}' has an empty enum, so no value is valid", "Add the allowed values")
    return f


def similar_names(name: str, candidates: list[str]) -> list[str]:
    """Field names that look like a rename of `name`: one contains the other, or they share most word parts."""
    parts = set(name.split("_"))
    hits = [c for c in candidates
            if name in c or c in name
            or len(parts & set(c.split("_"))) / max(len(parts | set(c.split("_"))), 1) >= 0.5]
    return hits or difflib.get_close_matches(name, candidates, n=1, cutoff=0.85)


def match_webhook(t: ToolSpec, hooks: list[WebhookNode]) -> WebhookNode | None:
    _, path = webhook_path(t.url)
    same = [h for h in hooks if h.path == path]
    return next((h for h in same if h.method == t.method), same[0] if same else None)


def check_against_n8n(t: ToolSpec, hooks: list[WebhookNode], all_sent: set[str]) -> list[Finding]:
    f = []
    add = lambda check, sev, msg, fix="": f.append(Finding(t.name, check, sev, msg, fix))
    kind, path = webhook_path(t.url)
    if not kind:
        add("n8n.not_n8n_url", INFO, "URL is not an n8n webhook, so the workflow was not checked")
        return f
    h = match_webhook(t, hooks)
    if h is None:
        add("n8n.no_webhook", BLOCKER, f"No n8n webhook listens on path '{path}'",
            "Fix the path on the tool or the Webhook node so they match exactly")
        return f
    where = f"'{h.node}' in '{h.workflow}'"
    if h.method != t.method:
        add("n8n.method", BLOCKER, f"Tool sends {t.method} but {where} expects {h.method}",
            f"Set both to {t.method}")
    if h.disabled:
        add("n8n.node_disabled", BLOCKER, f"{where} is disabled", "Enable the Webhook node")
    if h.workflow_active is False:
        add("n8n.inactive", BLOCKER, f"Workflow '{h.workflow}' is not active, so /webhook/ URLs return 404",
            "Activate the workflow")
    elif h.workflow_active is None:
        add("n8n.active_unknown", INFO, f"Can't tell from the export whether '{h.workflow}' is active",
            "Run with --n8n-url to check it live")

    sends_auth = any(k.lower() == "authorization" for k in t.headers)
    if h.auth == "none":
        add("n8n.no_auth", WARN, f"{where} has no authentication, so anyone with the URL can call it",
            "Turn on Header Auth and send the matching Authorization secret from the tool")
    elif h.auth == "headerAuth" and not t.headers:
        add("n8n.auth_missing", BLOCKER, f"{where} requires Header Auth but the tool sends no headers",
            "Add an Authorization header backed by a secret")
    elif h.auth == "basicAuth" and not sends_auth:
        add("n8n.auth_missing", BLOCKER, f"{where} requires Basic Auth but the tool sends no Authorization header",
            "Add an Authorization header backed by a secret")

    if h.response_mode == "responseNode" and not h.has_respond_node:
        add("n8n.no_response", BLOCKER, f"{where} waits for a Respond to Webhook node, but none is connected",
            "Connect a Respond to Webhook node on every branch, including errors")
    elif h.response_mode == "onReceived":
        add("n8n.responds_immediately", WARN, f"{where} replies 'Workflow was started' before doing any work",
            "Set Respond to 'Using Respond to Webhook node' so the agent gets real data")

    unsent_reads = sorted(h.body_reads - all_sent)
    for p in t.params:
        if p.location == "body" and not re.search(rf"\b{re.escape(p.name)}\b", h.reachable_text):
            near = similar_names(p.name, unsent_reads)
            if near:
                add("n8n.param_mismatch", BLOCKER, f"Tool sends '{p.name}' but the workflow reads '{near[0]}'",
                    f"Rename the tool parameter to '{near[0]}' (or change the workflow to read body.{p.name})")
            else:
                similar = similar_names(p.name, sorted(h.body_reads))
                hint = f"; the workflow reads a similar field '{similar[0]}'" if similar else ""
                add("n8n.param_unread", WARN, f"Tool sends '{p.name}' but the workflow never reads it{hint}",
                    f"Rename it to '{similar[0]}'" if similar else f"Rename it to what the workflow expects, or read body.{p.name}")
    for name in sorted(h.body_reads - all_sent):
        add("n8n.field_never_sent", WARN, f"Workflow reads body.{name} but no tool sends '{name}'",
            f"Add '{name}' to the tool's parameters or remove the read")
    return f


def check_workflows(workflows: list[dict], placeholders_fn) -> list[Finding]:
    f = []
    for w in workflows:
        for node, value in placeholders_fn(w):
            f.append(Finding(f"workflow: {w.get('name', '?')}", "n8n.placeholder", BLOCKER,
                             f"Node '{node}' still contains {value}", "Replace it with the real value"))
    return f
