"""Web front end for preflight. Runs on your own machine and binds to localhost only.

    .venv/bin/uvicorn web.app:app --port 8000

It holds no credentials: keys arrive with a request, are used for that check, and are dropped.
Reports live in memory until the process stops.
"""
from __future__ import annotations

import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from preflight import elevenlabs, n8n, report as report_mod, runner  # noqa: E402

app = FastAPI(title="Agent Preflight")
STATIC = Path(__file__).parent / "static"
REPORTS: dict[str, tuple[str, str]] = {}  # id -> (markdown, agent name)
MAX_REPORTS = 50


class CheckRequest(BaseModel):
    name: str = ""
    tools_path: str = ""
    agent_id: str = ""
    elevenlabs_key: str = ""
    n8n_paths: list[str] = Field(default_factory=list)
    n8n_url: str = ""
    n8n_key: str = ""
    probe: bool = False
    auth_header: str = ""
    base_url: str = ""
    allow_writes: bool = False
    only: list[str] = Field(default_factory=list)


@app.post("/api/check")
def check(req: CheckRequest) -> dict:
    if bool(req.tools_path) == bool(req.agent_id):
        raise HTTPException(400, "Give either a tools folder or an agent id, not both")
    if req.probe and not (req.auth_header or req.base_url):
        raise HTTPException(400, "Live calls need an Authorization value, or a base URL to send them to instead")
    try:
        tools = (elevenlabs.load_agent(req.agent_id, req.elevenlabs_key) if req.agent_id
                 else elevenlabs.load_path(req.tools_path))
        workflows = (n8n.load_api(req.n8n_url, req.n8n_key) if req.n8n_url
                     else n8n.load_files(req.n8n_paths) if req.n8n_paths else None)
    except (OSError, ValueError) as e:
        raise HTTPException(400, f"Couldn't load the configs: {e}") from e
    if not tools:
        raise HTTPException(400, "No webhook tools found there")

    rep = runner.run(req.name or req.agent_id or Path(req.tools_path).resolve().parent.name, tools, workflows,
                     live=req.probe, auth_header=req.auth_header or None, base_url=req.base_url or None,
                     allow_writes=req.allow_writes, only=set(req.only) or None)

    report_id = uuid.uuid4().hex[:12]
    if len(REPORTS) >= MAX_REPORTS:
        REPORTS.pop(next(iter(REPORTS)))
    REPORTS[report_id] = (report_mod.to_markdown(rep), rep.agent)
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
def download(report_id: str) -> str:
    if report_id not in REPORTS:
        raise HTTPException(404, "That report is gone; run the check again")
    return REPORTS[report_id][0]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
