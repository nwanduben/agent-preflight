"""preflight: check a voice agent's webhook tools before production.

  python -m preflight --tools agent/tools --n8n n8n/                  # files only, no network
  python -m preflight --agent-id AGENT --n8n-url https://n8n.x.com    # live configs (read-only)
  ... --probe --auth-header "Bearer ..."                              # also call each webhook
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import elevenlabs, n8n, report, runner


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="preflight", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("agent (pick one)")
    src.add_argument("--tools", help="ElevenLabs tool file, folder of tool files, or exported agent JSON")
    src.add_argument("--agent-id", help="ElevenLabs agent id (reads ELEVENLABS_API_KEY)")
    wf = ap.add_argument_group("n8n (optional)")
    wf.add_argument("--n8n", action="append", default=[], help="Workflow JSON file or folder (repeatable)")
    wf.add_argument("--n8n-url", help="n8n base URL (reads N8N_API_KEY)")
    live = ap.add_argument_group("live calls (off by default)")
    live.add_argument("--probe", action="store_true", help="Call each webhook with sample data")
    live.add_argument("--auth-header", default=os.environ.get("PREFLIGHT_AUTH"),
                      help="Authorization value to send (or PREFLIGHT_AUTH)")
    live.add_argument("--base-url", help="Send probes here instead of the tool's host, e.g. a staging n8n")
    live.add_argument("--only", help="Comma-separated tool names to probe")
    live.add_argument("--allow-writes", action="store_true", help="Also probe tools that change data")
    ap.add_argument("--name", help="Agent name for the report")
    ap.add_argument("--out", help="Write the Markdown report here (JSON goes next to it)")
    args = ap.parse_args(argv)

    if bool(args.tools) == bool(args.agent_id):
        ap.error("pass exactly one of --tools or --agent-id")
    try:
        if args.agent_id:
            tools = elevenlabs.load_agent(args.agent_id, _env("ELEVENLABS_API_KEY"))
        else:
            tools = elevenlabs.load_path(args.tools)
        workflows = None
        if args.n8n_url:
            workflows = n8n.load_api(args.n8n_url, _env("N8N_API_KEY"))
        elif args.n8n:
            workflows = n8n.load_files(args.n8n)
    except (OSError, ValueError) as e:
        print(f"preflight: couldn't load the configs: {e}", file=sys.stderr)
        return 2
    if not tools:
        print("preflight: no webhook tools found", file=sys.stderr)
        return 2

    rep = runner.run(args.name or args.agent_id or Path(args.tools).resolve().parent.name, tools, workflows,
                     live=args.probe, auth_header=args.auth_header, base_url=args.base_url,
                     allow_writes=args.allow_writes, only=set(args.only.split(",")) if args.only else None)
    md = report.to_markdown(rep)
    if args.out:
        Path(args.out).write_text(md)
        Path(args.out).with_suffix(".json").write_text(report.to_json(rep))
        print(f"Report written to {args.out}")
    print(md)
    return 0 if rep.ready else 1


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"set {name} in the environment")
    return value


if __name__ == "__main__":
    sys.exit(main())
