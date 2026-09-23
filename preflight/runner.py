"""Run every check and fold the findings into one report object."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import checks, n8n, probe as probe_mod
from .models import BLOCKER, SEVERITY_ORDER, WARN, Finding, ProbeResult, ToolSpec


@dataclass
class Report:
    agent: str
    tools: list[ToolSpec]
    findings: list[Finding]
    probes: list[ProbeResult] = field(default_factory=list)
    n8n_checked: bool = False

    def status(self, tool: str) -> str:
        sev = [f.severity for f in self.findings if f.tool == tool]
        return "fail" if BLOCKER in sev else "warn" if WARN in sev else "pass"

    @property
    def blockers(self) -> int:
        return sum(f.severity == BLOCKER for f in self.findings)

    @property
    def ready(self) -> bool:
        return self.blockers == 0


def run(agent: str, tools: list[ToolSpec], workflows: list[dict] | None = None, *, live: bool = False,
        auth_header: str | None = None, base_url: str | None = None, allow_writes: bool = False,
        only: set[str] | None = None, public_only: bool = False) -> Report:
    findings: list[Finding] = []
    for t in tools:
        findings += checks.check_tool(t)

    if workflows is not None:
        hooks = [h for w in workflows for h in n8n.index_workflow(w)]
        sent = {p.name for t in tools for p in t.params}
        for t in tools:
            findings += checks.check_against_n8n(t, hooks, sent)
        findings = _fold_shared(findings, tools, hooks)
        findings += checks.check_workflows(workflows, n8n.placeholders)

    probes = []
    if live:
        for t in tools:
            if only and t.name not in only:
                continue
            result, extra = probe_mod.probe(t, auth_header, base_url, allow_writes, public_only)
            probes.append(result)
            findings += extra

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.tool, f.check))
    return Report(agent, tools, findings, probes, workflows is not None)


def _fold_shared(findings: list[Finding], tools: list[ToolSpec], hooks) -> list[Finding]:
    """Workflow-level findings repeat for every tool on a shared workflow; keep one, owned by the workflow."""
    by_tool = {t.name: checks.match_webhook(t, hooks) for t in tools}
    out, seen = [], set()
    for f in findings:
        if f.check in ("n8n.field_never_sent", "n8n.active_unknown"):
            h = by_tool.get(f.tool)
            key = (f.check, f.message)
            if key in seen:
                continue
            seen.add(key)
            f = Finding(f"workflow: {h.workflow}" if h else f.tool, f.check, f.severity, f.message, f.fix)
        out.append(f)
    return out
