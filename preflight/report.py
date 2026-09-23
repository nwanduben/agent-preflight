"""Render a Report as Markdown (for people) or JSON (for the web app and CI)."""
from __future__ import annotations

import json
from dataclasses import asdict

from .runner import Report

ICON = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}


def to_markdown(r: Report) -> str:
    statuses = [r.status(t.name) for t in r.tools]
    lines = [
        f"# Preflight report: {r.agent}",
        "",
        f"**{'Ready for production' if r.ready else 'Not ready for production'}.** "
        f"{len(r.tools)} tools · {statuses.count('pass')} pass · {statuses.count('warn')} warn · "
        f"{statuses.count('fail')} fail · {r.blockers} blocker(s) in total.",
        "",
        f"Checks run: tool config{' · n8n workflow match' if r.n8n_checked else ''}"
        f"{' · live calls' if r.probes else ''}.",
        "",
        "| Tool | Status | Blockers | Warnings |",
        "|---|---|---|---|",
    ]
    for t in r.tools:
        mine = [f for f in r.findings if f.tool == t.name]
        lines.append(f"| `{t.name}` | {ICON[r.status(t.name)]} | "
                     f"{sum(f.severity == 'blocker' for f in mine)} | {sum(f.severity == 'warning' for f in mine)} |")

    lines += ["", "## What to change before production", ""]
    if not r.findings:
        lines.append("Nothing. Every check passed.")
    for sev, title in (("blocker", "Blockers"), ("warning", "Warnings"), ("info", "Notes")):
        group = [f for f in r.findings if f.severity == sev]
        if not group:
            continue
        lines += [f"### {title} ({len(group)})", ""]
        for (message, fix), tools in _group(group).items():
            who = tools[0] if len(tools) == 1 else f"{len(tools)} tools ({', '.join(tools[:3])}{', …' if len(tools) > 3 else ''})"
            lines.append(f"- **{who}** · {message}" + (f"  \n  Fix: {fix}" if fix else ""))
        lines.append("")

    if r.probes:
        lines += ["## Live calls", "", "| Tool | HTTP | Time | Size | JSON |", "|---|---|---|---|---|"]
        for p in r.probes:
            if p.skipped:
                lines.append(f"| `{p.tool}` | skipped: {p.skipped} | | | |")
            else:
                lines.append(f"| `{p.tool}` | {p.status or p.error} | {p.latency_ms} ms | "
                             f"{p.size if p.size is not None else '-'} | {'yes' if p.is_json else 'no'} |")
    return "\n".join(lines).rstrip() + "\n"


def to_json(r: Report) -> str:
    return json.dumps({
        "agent": r.agent,
        "ready": r.ready,
        "blockers": r.blockers,
        "tools": [{"name": t.name, "url": t.url, "status": r.status(t.name)} for t in r.tools],
        "findings": [asdict(f) for f in r.findings],
        "probes": [asdict(p) for p in r.probes],
    }, indent=2)


def _group(findings: list) -> dict:
    """Same message on many tools prints once, e.g. an inactive workflow that every tool depends on."""
    grouped: dict = {}
    for f in findings:
        grouped.setdefault((f.message, f.fix), []).append(f.tool)
    return grouped
