# The live read-only run

Nothing here writes anything. It reads the agent config from ElevenLabs and the workflows from
n8n, and makes no call to your webhooks.

```bash
export ELEVENLABS_API_KEY='...'      # ElevenLabs → profile → API keys
export N8N_API_KEY='...'             # n8n → Settings → n8n API
python3 -m preflight \
  --agent-id <your agent id> \
  --n8n-url https://your-n8n-host \
  --name "ENTIN Bank support agent" \
  --out reports/entin-live.md
```

## What to check in the result

1. **The tool list matches the ElevenLabs UI**, in count and in names. If tools are missing,
   the agent references them by id and the tools endpoint did not return them — tell me and
   I will fix the loader.
2. **Workflow active state is real.** Against files it says "can't tell from the export";
   live it should say nothing, or name the inactive workflow.
3. **Secrets read as filled in**, not `REPLACE_WITH_…`. The repo copies always look unfilled.

## Then, live calls (only against a test copy)

Even the read tools write to the Sessions and Call Log tabs, so point this at a copy of the
sheet, not the real one.

```bash
python3 -m preflight --agent-id <id> --n8n-url https://your-n8n-host \
  --probe --auth-header "Bearer <the ENTIN webhook secret>" \
  --only verify_caller,find_branch_or_atm
```

`--only` limits it to two tools. Drop it to probe them all, and add `--allow-writes` to
include `create_*`, `block_*` and the rest.

## If something looks wrong

Two things are still unverified guesses, and this run is what proves them:
- the ElevenLabs tools endpoint (`GET /v1/convai/tools/{id}`), used to expand `tool_ids`
- the n8n API listing (`GET /api/v1/workflows` with `X-N8N-API-KEY`)

If either 404s or returns a different shape, the error text tells me what to change.
