"""Load ElevenLabs webhook tools from exported files or the ElevenLabs API."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from .models import Param, ToolSpec

API = "https://api.elevenlabs.io/v1/convai"


def _params(schema: dict | None, location: str) -> tuple[list[Param], list[str]]:
    if not schema:
        return [], []
    # Body/query schemas are JSON-Schema objects; path schemas may be a bare {name: {...}} map.
    props = schema.get("properties") if "properties" in schema else schema
    required = schema.get("required", []) if "properties" in schema else []
    params = [
        Param(
            name=name,
            location=location,
            type=spec.get("type", "string"),
            description=spec.get("description", ""),
            required=name in required,
            enum=spec.get("enum"),
            dynamic_variable=spec.get("dynamic_variable") or None,
        )
        for name, spec in (props or {}).items()
        if isinstance(spec, dict)
    ]
    return params, [r for r in required if r not in (props or {})]


def tool_from_config(cfg: dict, source: str = "") -> ToolSpec | None:
    """Accepts a tool file, an API tool ({id, tool_config}) or an inline agent tool."""
    cfg = cfg.get("tool_config", cfg)
    if cfg.get("type") != "webhook":
        return None  # client / system tools make no HTTP call we can check
    api = cfg.get("api_schema", {})
    params, missing = [], []
    for key, loc in (("request_body_schema", "body"), ("query_params_schema", "query"), ("path_params_schema", "path")):
        p, m = _params(api.get(key), loc)
        params += p
        missing += m
    return ToolSpec(
        name=cfg.get("name", "?"),
        platform="elevenlabs",
        url=api.get("url", ""),
        method=(api.get("method") or "GET").upper(),  # ElevenLabs defaults to GET
        description=cfg.get("description", ""),
        timeout_secs=cfg.get("response_timeout_secs"),
        headers=api.get("request_headers") or {},
        params=params,
        required_missing=missing,
        source=source,
    )


def load_path(path: str) -> list[ToolSpec]:
    """A directory of tool files, one tool file, or an exported agent JSON."""
    p = Path(path)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    tools = []
    for f in files:
        data = json.loads(f.read_text())
        inline = data.get("conversation_config", {}).get("agent", {}).get("prompt", {}).get("tools")
        for cfg in inline if inline is not None else [data]:
            t = tool_from_config(cfg, source=str(f))
            if t:
                tools.append(t)
    return tools


def _get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url, headers={"xi-api-key": api_key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load_agent(agent_id: str, api_key: str) -> list[ToolSpec]:
    """Read-only: fetches the agent, then each tool it references by id."""
    agent = _get(f"{API}/agents/{agent_id}", api_key)
    prompt = agent.get("conversation_config", {}).get("agent", {}).get("prompt", {})
    tools = [t for c in prompt.get("tools") or [] if (t := tool_from_config(c, "agent inline"))]
    seen = {t.name for t in tools}
    for tool_id in prompt.get("tool_ids") or []:
        t = tool_from_config(_get(f"{API}/tools/{tool_id}", api_key), f"tool {tool_id}")
        if t and t.name not in seen:
            tools.append(t)
    return tools
