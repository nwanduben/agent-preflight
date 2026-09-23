"""Canonical shapes every loader produces and every check consumes."""
from __future__ import annotations

from dataclasses import dataclass, field

BLOCKER, WARN, INFO = "blocker", "warning", "info"
SEVERITY_ORDER = {BLOCKER: 0, WARN: 1, INFO: 2}


@dataclass
class Param:
    name: str
    location: str  # body | query | path
    type: str = "string"
    description: str = ""
    required: bool = False
    enum: list | None = None
    dynamic_variable: str | None = None


@dataclass
class ToolSpec:
    """One webhook tool as the voice platform will call it."""
    name: str
    platform: str  # elevenlabs | retell
    url: str
    method: str = "POST"
    description: str = ""
    timeout_secs: float | None = None
    headers: dict = field(default_factory=dict)  # name -> literal str or {"secret_id": ...}
    params: list[Param] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)  # names in `required` with no property
    source: str = ""


@dataclass
class WebhookNode:
    workflow: str
    workflow_active: bool | None  # None = unknown (file export)
    node: str
    path: str
    method: str
    auth: str  # none | headerAuth | basicAuth | jwtAuth
    response_mode: str  # onReceived | lastNode | responseNode
    disabled: bool
    reachable_nodes: list[str] = field(default_factory=list)
    reachable_text: str = ""  # code + expressions of every node downstream
    body_reads: set[str] = field(default_factory=set)
    has_respond_node: bool = False


@dataclass
class Finding:
    tool: str
    check: str
    severity: str
    message: str
    fix: str = ""


@dataclass
class ProbeResult:
    tool: str
    skipped: str = ""
    status: int | None = None
    latency_ms: int | None = None
    size: int | None = None
    is_json: bool | None = None
    error: str = ""
