# Deploying AgentOps Sentinel (Vercel + Render + Neon, free tier)

## Live deployment

| Part | URL | Host and plan |
|---|---|---|
| Dashboard (`web/`, Next.js) | https://agentops-sentinel-blush.vercel.app | Vercel Hobby (free) |
| API + worker (`sentinel.asgi:app`, `sentinel.worker`) | https://agentops-sentinel-api.onrender.com/health | Render free web service, Singapore |
| PostgreSQL 17 (`pg_trgm`, `unaccent`) | — | Neon free tier, AWS Singapore |

The browser only talks to Vercel. Vercel proxies `/sentinel-api/*` to the API (see
`web/next.config.ts`), so the API's `SameSite=strict` session cookies keep working.

**Free-tier behavior**

- The Render instance sleeps after 15 minutes without inbound traffic. The first request
  after a sleep takes about a minute; if the dashboard reports a connection error while
  it wakes, retry.
- Render has no free background workers, so the worker runs inside the API instance and
  polls it over loopback every 5 s (see the `startCommand` in `render.yaml`). It only runs
  while the instance is awake.
- Render's 750 free instance hours per month are shared by every free service in the
  workspace. Neon's free plan includes 1 GB of storage and scales to zero when idle.
- Vercel's Hobby plan is intended for non-commercial use.

## Deploy your own copy

Python 3.11 builds with `pip install .`; Docker is not needed locally or on Render.

### 1. Database (Neon)
Create a free Neon project (Postgres 17, region closest to your API). Click **Connect**,
turn **Connection pooling off**, and copy the direct connection string; it contains
`sslmode=require` and no `-pooler` in the hostname. Migrations need a direct connection.

### 2. Secrets and seed (one time, from this repo)
```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_hosted.py secrets
$env:SENTINEL_DATABASE_URL = "<direct connection string>"
$env:SENTINEL_AUTH_PEPPER = "<pepper from above>"
.\.venv\Scripts\python.exe scripts\bootstrap_hosted.py seed --organization "My Team"
```
This applies all migrations and prints four API keys **once** (admin, developer,
reviewer, worker). Store them in a password manager.

### 3. API on Render
In Render choose **New → Blueprint** and pick the repo; it reads `render.yaml` and
creates one free web service. When asked for the unsynced values, enter:

| Variable | Value |
|---|---|
| `SENTINEL_DATABASE_URL` | Neon direct connection string |
| `SENTINEL_AUTH_PEPPER`, `SENTINEL_CREDENTIAL_ENCRYPTION_KEY` | from `bootstrap_hosted.py secrets` |
| `SENTINEL_ALLOWED_ORIGINS` | your dashboard URL, e.g. `https://<project>.vercel.app` |
| `SENTINEL_WORKER_API_KEY` | the worker key from `seed` |

Check it: `https://<render-service>.onrender.com/health` returns `{"status":"ok"}`.

### 4. Dashboard on Vercel
Import the repo in Vercel (**Add New → Project**), set **Root Directory** to `web`, and add:

| Variable | Value |
|---|---|
| `SENTINEL_API_ORIGIN` | `https://<render-service>.onrender.com` |
| `NEXT_PUBLIC_SENTINEL_API_URL` | `/sentinel-api` |

Both are read at build time, so redeploy after changing them. Vercel may add a suffix to
the project domain (for example `-blush`) when the plain name is taken; put the final
domain in Render's `SENTINEL_ALLOWED_ORIGINS`.

### 5. Connect
Open the dashboard, open the connection console, and use the admin key. The API URL is
pre-filled as `https://<vercel-domain>/sentinel-api`.

## Upgrading to an always-on setup

For production use, move the worker into its own service on paid instances (Render has
no free background workers) and keep the API awake:

```yaml
services:
  - type: web
    name: agentops-sentinel-api
    runtime: python
    plan: starter
    region: singapore
    buildCommand: pip install --upgrade pip && pip install .
    startCommand: uvicorn sentinel.asgi:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
    healthCheckPath: /health
    # envVars: as in render.yaml, minus SENTINEL_WORKER_API_KEY
  - type: worker
    name: agentops-sentinel-worker
    runtime: python
    plan: starter
    region: singapore
    buildCommand: pip install --upgrade pip && pip install .
    startCommand: python -m sentinel.worker
    # envVars: PYTHON_VERSION, SENTINEL_API_URL=https://<api>.onrender.com, SENTINEL_WORKER_API_KEY
```

The `Dockerfile` remains available for hosts that require an image (Railway, Fly.io).

## Notes
- Without the two Vercel variables, the dashboard still deploys and shows its demo data,
  but it can't connect to an API.
- The EstateFlow booking example (`SENTINEL_BOOKING_SERVICE_URL`) isn't deployed. It's optional.
