# Deploying the SENTINEL demo

The app runs in **fixture mode with no credentials** — nothing secret is needed
to host it. It serves the React operator surface at `/` and the API at `/api/*`,
binds to `$PORT` (or 8080), and passes a health check at `/api/health`.

Config files are already in the repo: `Dockerfile` (multi-stage: builds the
frontend, serves via FastAPI), `render.yaml`, `fly.toml`, `railway.json`,
`Procfile`, `.dockerignore`.

> Everything is synthetic and test-mode. Do **not** set any `RAZORPAY_*` or
> provider key on the public demo — it is meant to run guardrail-free of real data.

## Option A — Render (simplest, free)
1. Push this repo to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo. It reads `render.yaml`.
3. Deploy. Render builds the Docker image and gives you `https://sentinel-<id>.onrender.com`.
4. Health check `/api/health` must return 200; then open `/` for the operator surface.

(No env vars to set — `render.yaml` pins `SENTINEL_MODE=fixture`, `SENTINEL_CASSETTE=replay`.)

## Option B — Fly.io (CLI)
```bash
brew install flyctl && fly auth login
fly launch --no-deploy --copy-config --name sentinel-demo   # reuses fly.toml
fly deploy
fly open        # opens https://sentinel-demo.fly.dev
```

## Option C — Railway (CLI or dashboard)
- Dashboard: **New Project → Deploy from GitHub repo** → it detects `Dockerfile`/`railway.json`, injects `$PORT`, deploys, and gives a public domain (enable it under Settings → Networking → Generate Domain).
- CLI:
  ```bash
  npm i -g @railway/cli && railway login
  railway init && railway up
  railway domain     # prints the public URL
  ```

## Option D — any Docker host / a plain VM
```bash
docker build -t sentinel .
docker run -p 8080:8080 sentinel      # -> http://localhost:8080
# or on a host that injects a port:
docker run -e PORT=3000 -p 3000:3000 sentinel
```

## After deploying — smoke test
```bash
curl https://YOUR-URL/api/health          # {"status":"ok","mode":"fixture",...}
curl https://YOUR-URL/api/redteam | jq .attack_success_rate_on_pct   # 0.0
open https://YOUR-URL/                     # Run console; try the injected-refund scenario
```

## Notes / limits
- Free tiers sleep on idle; the first request after a sleep is slow (cold start).
- The demo has **no auth** — it is a single-operator fixture demo. Do not put real
  data behind it (there is none in the repo, and there should be none added).
- SSE (`/api/runs/{id}/stream`) needs a host that does not buffer streaming
  responses; Render/Fly/Railway all handle it. If a proxy buffers it, the Run
  console still works — it falls back to rendering the returned trace.
