# Agent Preflight

Checks a voice agent's webhook tools, and the n8n workflows behind them, before the agent goes to production. It prints what will break and how to fix it. The exit code is 1 when there are blockers, so it can gate CI.

Python 3.10+, standard library only.

```bash
# Files only, no network
python3 -m preflight --tools path/to/agent/tools --n8n path/to/n8n --out reports/agent.md

# Live configs, read-only
ELEVENLABS_API_KEY=... N8N_API_KEY=... python3 -m preflight --agent-id <agent_id> --n8n-url https://your-n8n

# Also call each webhook (tools that change data are skipped unless --allow-writes)
python3 -m preflight ... --probe --auth-header "Bearer <secret>" --only verify_caller

# Tests
python3 -m unittest discover -s tests -t .
```

## Web app

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn web.app:app --port 8000     # then open http://127.0.0.1:8000
```

Paste a tools folder and an n8n folder, or open "Read live configs" and give an agent id plus API keys. Keys are used for that one check and never stored. "Call each webhook for real" is off by default, and can be pointed at a test server with "Send calls here instead". Each tool row expands to show its findings, fixes and live-call timing; the whole report downloads as Markdown.

Hosted, it runs in a locked-down mode: uploads instead of file paths, a password, and public https addresses only. See [docs/deploy.md](docs/deploy.md). For the live read-only run against a real agent, see [docs/live-run.md](docs/live-run.md).

## What it checks

| Area | Blockers | Warnings |
|---|---|---|
| Tool URL | `/webhook-test/` URL, localhost/ngrok/tunnel URL, not https, placeholder host | |
| Auth | placeholder or empty secret; n8n requires auth but the tool sends none | webhook has no auth; auth stored as plain text |
| Schema | `required` field not defined, empty enum | param has no description, LLM-filled `conversation_id`, weak tool description, timeout over 20 s |
| n8n match | no webhook on that path, method mismatch, node disabled, workflow inactive, no Respond to Webhook node, param name mismatch (`phone` vs `phone_number`), unfilled `PASTE_…`/`REPLACE_…` values | param never read, field read but never sent, responds before the work is done |
| Live probe | 401/403, 404, non-2xx, timeout or unreachable, response over 15,000 chars | non-JSON reply, slower than 3 s |

## Testing without touching anything real

`tools/fake_n8n.py` stands in for n8n: it reads the agent's tool files, serves every path they point at, and misbehaves on the tools you name.

```bash
python3 tools/fake_n8n.py --tools "<agent>/agent/tools" --port 8099 --secret "Bearer test-secret" \
    --slow verify_caller --error create_ticket --big get_ticket_status --text assess_request --missing find_branch_or_atm

python3 -m preflight --tools <tools> --n8n <workflows> \
    --probe --base-url http://127.0.0.1:8099 --auth-header "Bearer test-secret" --allow-writes
```

Faults: `--slow` (waits `--delay`, default 6 s), `--error` (HTTP 500), `--big` (reply over the size limit), `--text` (plain text, not JSON), `--missing` (404, like an inactive workflow). `tests/test_fake_server.py` runs this whole loop automatically.

## Layout
- `preflight/elevenlabs.py`: loads tools from tool files, an agent export, or the API.
- `preflight/n8n.py`: indexes webhooks, follows the nodes downstream of each, and finds the `body.*` fields they read.
- `preflight/checks.py`, `probe.py`: the checks and the live calls.
- `preflight/runner.py`, `report.py`, `cli.py`
- `tools/fake_n8n.py`: the stand-in server.
- `tests/`: fixtures with planted faults, a fake webhook server, and the end-to-end test.
- `docs/project-kickoff.md`: goal, six Ps, decisions.
