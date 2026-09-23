# Project kickoff: Agent Preflight

A QA tool that checks a voice agent's webhook tools (and the n8n workflows behind them) before production, and lists exactly what to change. It will end up as a web app; the checking engine comes first.

## Active goal

> Build a runnable Python engine, `preflight`, that loads an ElevenLabs agent's webhook tools (from files or the API) and the n8n workflows behind them, runs static checks and an opt-in live probe, and writes a pass/fail report of required changes. Done when (a) tests prove it flags seeded faults (n8n `/webhook-test/` URL, no matching webhook, param name mismatch, missing Respond node, placeholder secret, inactive workflow, non-2xx, over 15,000 chars, timeout, non-JSON, bad auth) and passes a clean tool, and (b) it runs read-only against the ENTIN Bank agent's files. Stop before live calls to ENTIN, the web UI, or Retell/GHL support without the user's approval.

**Phase:** prototype. **Status (2026-09-23):** (a) met, with 18 tests passing; (b) met against ENTIN's repo files; a broken copy of ENTIN's config (7 planted faults) is caught in full; the probe path is proven end to end against `tools/fake_n8n.py` (5 planted server faults caught). Not yet run against the live ElevenLabs agent or n8n instance.

Evidence labels: **observed** (seen in this project), **source-backed** (primary docs, linked), **user-decided**, **hypothesis**.

## Six Ps

**Pain.** Hypothesis: agency builders ship ElevenLabs/Retell agents whose tool wiring breaks in production. The user proposed this and it isn't validated with other builders yet. **Observed** in ENTIN's own files:
- All 13 tool files still carry a placeholder secret id. That's expected, because `build_tools.py` fills them in, but it's exactly what gets forgotten.
- The post-call workflow still contains `PASTE_ELEVENLABS_WEBHOOK_SECRET_HERE`.
- `report_security_event` sends `note`, but no node in the workflow reads it, even though `docs/design/api-contracts.md` specifies it.

**Falsifier:** 5 builders say one manual test call is enough. **Owner:** user.

**Promise.** "Connect your agent and get every tool connection that will break in production, with the fix, before your client hears it fail." (hypothesis)

**Product.**
- **v0 (built):** a command-line tool plus Markdown/JSON reports.
- **v1 (built):** a local web app (FastAPI + one page) over the same engine: form, readiness banner, per-tool rows that expand into findings and fixes, Markdown download.
- **Non-goals for now:** conversation simulation or LLM grading (Hamming, Cekura and Coval cover that), Retell, GHL, and production monitoring.

**Plumbing.**
- Python standard library only, with no dependencies.
- Read-only APIs:
  - ElevenLabs `GET /v1/convai/agents/{id}` ([docs](https://elevenlabs.io/docs/api-reference/agents/get)). `GET /v1/convai/tools/{id}` is a **hypothesis**, not yet verified live.
  - n8n `GET /api/v1/workflows` with `X-N8N-API-KEY`. This is a **hypothesis** until run against the user's instance.
- The live probe is opt-in. Tools whose names start with a write verb are skipped unless `--allow-writes` is passed.
- **Caveat:** in ENTIN, even read tools write to the Sessions and Call Log tabs, so probe a test copy.

**Packaging.** Local web app, README, example reports. Not deployed or multi-user; it reads files from the machine it runs on and binds to localhost.

**Proof.**
1. **Prototype:** done (tests plus seeded faults).
2. **Real-world:** run on the live ENTIN agent and n8n instance. Pending the user's API keys and approval.
3. **Customer:** 3 external builders use it before a go-live. Not claimed.

## Decision log

| Decision | By | Why |
| --- | --- | --- |
| ~~Start with Retell~~ → start with ElevenLabs + n8n | user (chose option 1) | Matches the user's ENTIN build, so a real test case exists from day one |
| Web app in the end, engine first | user asked; assistant recommended the order | The UI shows real results instead of mock ones |
| Python, standard library only | assistant | Matches voiceroi-report; nothing to install |
| Static checks by default; probe opt-in; writes need `--allow-writes` | assistant | Tools write to live data (Sheets, CRM) |
| Param-name mismatch is a blocker; an unread param alone is a warning | assistant | A mismatch silently drops data; an unread optional field may be deliberate |
| Repeated identical findings print once, grouped by tool count | assistant | An inactive workflow otherwise repeats for all 13 tools |
| Test the probe against a fake n8n before any live webhook | user asked; assistant built | No test copy of the ENTIN sheet exists yet |

**Open questions**
- ElevenLabs and n8n API keys for a read-only live run. **Owner:** user.
- Is there a test copy of the ENTIN sheet for live probes? **Owner:** user.
- Internal agency tool or a product to sell? **Owner:** user.
- ~~Web app stack~~: FastAPI plus one page, matching voiceroi-report. **Decided.**
- Should the web app be hosted for clients, or stay local? **Owner:** user.

## Next milestone and proof checks
1. Live read-only run: `ELEVENLABS_API_KEY=… N8N_API_KEY=… python3 -m preflight --agent-id <id> --n8n-url <url>`. Check: the tool list matches the ElevenLabs UI and "active" is reported correctly.
2. Probe the ENTIN test copy with `--probe --only verify_caller,find_branch_or_atm`. Check: latency is recorded, and the sheet rows written are ones we expected.
3. ~~Web app~~ done: `web/app.py` + `web/static/index.html`, verified in a browser against ENTIN files and the fake server (22 tests).
4. Decide whether this stays a local tool or becomes hosted (needs auth, per-user config storage and a job queue before anyone else can use it).
