# Hosting it on Render

**Live since 2026-09-24:** https://agent-preflight.onrender.com (Render service `srv-daq25imk1f9s73dn9slg`,
free plan, blueprint-managed from `main`). Sign in with any username and the `PREFLIGHT_PASSWORD` set in
the Render dashboard. Pushing to `main` redeploys it.

The app runs in one of two modes, set by `PREFLIGHT_MODE`:

| | `local` (default) | `hosted` |
|---|---|---|
| Config source | folders on the machine it runs on, or uploads | uploads, or the ElevenLabs/n8n APIs |
| Outbound calls | any address, including localhost | public https only |
| Login | optional | required; it refuses to start without `PREFLIGHT_PASSWORD` |

## Steps

1. Push this repo to GitHub (done: `nwanduben/agent-preflight`, private).
2. In Render, create a **Web Service** from the repo. `render.yaml` sets the build and start
   commands, the health check and `PREFLIGHT_MODE=hosted`.
3. Set **`PREFLIGHT_PASSWORD`** in the Render dashboard. It is deliberately not in the repo.
   Use a long random value; it is the only thing between the internet and this tool.
4. Deploy, open the URL, and sign in with any username and that password.

The Dockerfile is there if you would rather deploy a container; it needs the same
environment variables.

## What hosted mode protects against

- **Reaching private networks.** Every outbound URL (tool webhooks, the n8n API, the base URL
  for live calls) must be https and must resolve to a public address. Loopback, private ranges,
  link-local and cloud metadata addresses are refused, so the server cannot be used to probe
  a network it happens to sit inside.
- **Strangers using your instance.** HTTP Basic auth on every route except `/healthz`.
- **Oversized uploads.** At most 60 files and 2,000,000 characters per file.

## If the login keeps reappearing

Basic auth re-prompts instead of showing an error, so a repeating box means the password is wrong:
- Reveal `PREFLIGHT_PASSWORD` in Render's Environment tab (eye icon) and compare character by character;
  a trailing space from a paste is invisible in the box.
- Check the values did not land in the wrong rows — one `PREFLIGHT…` row must read exactly `hosted`.
- Try a private window: browsers resend cached Basic auth credentials without asking again.
- Do not use Render's **Generate** button for this variable; it creates a value you cannot read back.

## What it still does not do

- **One shared password, no accounts.** Everyone who signs in sees the same thing. Fine for
  you and a colleague; not enough to let clients in.
- **Reports live in memory.** A restart, a redeploy, or an idle instance spinning down loses
  them. Download the Markdown if you want to keep a report.
- **Checks run inside the request.** Thirteen tools with a slow webhook can take a while, and
  a platform request timeout would cut it off. A job queue is the fix when that starts hurting.
- **Keys travel to the server** when you use the API fields. They are used for that one check
  and never written down, but on a hosted box that is still your key on someone else's machine.
  Uploading files avoids it entirely.
