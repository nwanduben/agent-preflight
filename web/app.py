"""Web front end for preflight.

Two modes, set by PREFLIGHT_MODE:

  local (default)  reads config folders from this machine, allows calls to any address.
                   Bind it to 127.0.0.1 and keep it to yourself.
  hosted           no filesystem paths: configs are uploaded or read from the platform
                   APIs, and every outbound call must be public https.

Set PREFLIGHT_PASSWORD to require a login (any username). Hosted mode refuses to serve
without one. It holds no credentials: keys arrive with a request, are used for that
check, and are dropped. Reports live in memory until the process stops.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from preflight import elevenlabs, n8n, net, report as report_mod, runner  # noqa: E402

HOSTED = os.environ.get("PREFLIGHT_MODE", "local").lower() == "hosted"
PASSWORD = os.environ.get("PREFLIGHT_PASSWORD", "")
MAX_UPLOAD_FILES = 60
MAX_UPLOAD_CHARS = 2_000_000
MAX_REPORTS = 50

if HOSTED and not PASSWORD:
    raise SystemExit("PREFLIGHT_MODE=hosted needs PREFLIGHT_PASSWORD set, or anyone could use this server")

app = FastAPI(title="Agent Preflight")
STATIC = Path(__file__).parent / "static"
REPORTS: dict[str, str] = {}
basic = HTTPBasic(auto_error=False)


def require_login(creds: HTTPBasicCredentials | None = Depends(basic)) -> None:
    if not PASSWORD:
        return
    if not creds or not secrets.compare_digest(creds.password, PASSWORD):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to use this",
                            headers={"WWW-Authenticate": "Basic"})


class UploadedFile(BaseModel):
    name: str
    content: str


class CheckRequest(BaseModel):
    name: str = ""
    tools_path: str = ""
    tools_files: list[UploadedFile] = Field(default_factory=list)
    agent_id: str = ""
    elevenlabs_key: str = ""
    n8n_paths: list[str] = Field(default_factory=list)
    n8n_files: list[UploadedFile] = Field(default_factory=list)
    n8n_url: str = ""
    n8n_key: str = ""
    probe: bool = False
    auth_header: str = ""
    base_url: str = ""
    allow_writes: bool = False
    only: list[str] = Field(default_factory=list)


def parse_uploads(files: list[UploadedFile]) -> list[tuple[str, dict]]:
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(400, f"Too many files at once (limit {MAX_UPLOAD_FILES})")
    out = []
    for f in files:
        if len(f.content) > MAX_UPLOAD_CHARS:
            raise HTTPException(400, f"{f.name} is too big (limit {MAX_UPLOAD_CHARS:,} characters)")
        try:
            out.append((f.name, json.loads(f.content)))
        except ValueError as e:
            raise HTTPException(400, f"{f.name} is not valid JSON: {e}") from e
    return out


def guard(url: str, what: str) -> None:
    reason = net.check_url(url, public_only=HOSTED)
    if reason:
        raise HTTPException(400, f"{what}: {reason}")


@app.get("/api/config")
def config(_: None = Depends(require_login)) -> dict:
    return {"hosted": HOSTED, "allow_paths": not HOSTED}


@app.post("/api/check")
def check(req: CheckRequest, _: None = Depends(require_login)) -> dict:
    sources = [bool(req.tools_path), bool(req.tools_files), bool(req.agent_id)]
    if sum(sources) != 1:
        raise HTTPException(400, "Give exactly one of: a tools folder, uploaded tool files, or an agent id")
    if HOSTED and (req.tools_path or req.n8n_paths):
        raise HTTPException(400, "This server can't read files from your machine; upload them instead")
    if req.probe and not (req.auth_header or req.base_url):
        raise HTTPException(400, "Live calls need an Authorization value, or a base URL to send them to instead")
    for url, what in ((req.n8n_url, "n8n URL"), (req.base_url, "Base URL for live calls")):
        if url:
            guard(url, what)

    try:
        if req.agent_id:
            tools = elevenlabs.load_agent(req.agent_id, req.elevenlabs_key)
        elif req.tools_files:
            tools = elevenlabs.load_objects(parse_uploads(req.tools_files))
        else:
            tools = elevenlabs.load_path(req.tools_path)

        if req.n8n_url:
            workflows = n8n.load_api(req.n8n_url, req.n8n_key)
        elif req.n8n_files:
            workflows = [w for _, w in parse_uploads(req.n8n_files)]
        elif req.n8n_paths:
            workflows = n8n.load_files(req.n8n_paths)
        else:
            workflows = None
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(400, f"Couldn't load the configs: {e}") from e
    if not tools:
        raise HTTPException(400, "No webhook tools found there")

    rep = runner.run(req.name or req.agent_id or "agent", tools, workflows,
                     live=req.probe, auth_header=req.auth_header or None, base_url=req.base_url or None,
                     allow_writes=req.allow_writes, only=set(req.only) or None, public_only=HOSTED)

    report_id = uuid.uuid4().hex[:12]
    if len(REPORTS) >= MAX_REPORTS:
        REPORTS.pop(next(iter(REPORTS)))
    REPORTS[report_id] = report_mod.to_markdown(rep)
    statuses = [rep.status(t.name) for t in rep.tools]
    return {
        "report_id": report_id,
        "agent": rep.agent,
        "ready": rep.ready,
        "blockers": rep.blockers,
        "counts": {s: statuses.count(s) for s in ("pass", "warn", "fail")},
        "n8n_checked": rep.n8n_checked,
        "tools": [{"name": t.name, "url": t.url, "method": t.method, "status": rep.status(t.name),
                   "findings": [asdict(f) for f in rep.findings if f.tool == t.name]} for t in rep.tools],
        "other_findings": [asdict(f) for f in rep.findings if f.tool not in {t.name for t in rep.tools}],
        "probes": [asdict(p) for p in rep.probes],
    }


@app.get("/api/report/{report_id}.md", response_class=PlainTextResponse)
def download(report_id: str, _: None = Depends(require_login)) -> str:
    if report_id not in REPORTS:
        raise HTTPException(404, "That report is gone; run the check again")
    return REPORTS[report_id]


@app.get("/")
def index(_: None = Depends(require_login)) -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
