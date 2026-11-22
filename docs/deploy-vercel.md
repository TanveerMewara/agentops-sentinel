# Deploying AgentOps Sentinel (Vercel + Render + hosted Postgres)

| Part | Where | Why |
|---|---|---|
| Dashboard (`web/`, Next.js) | Vercel | Standard Next.js build |
| API (`sentinel.asgi:app`) + worker (`sentinel.worker`) | Render (native Python runtime, no Docker), or Railway/Fly.io via the `Dockerfile` | Long-running processes; Vercel can't host the worker |
| PostgreSQL 15+ with `pg_trgm`, `unaccent` | Neon, Supabase or Render Postgres | Both extensions are available on all three |

The browser only talks to Vercel. Vercel proxies `/sentinel-api/*` to the API
(see `web/next.config.ts`), so the API's `SameSite=strict` session cookies work.

## 1. Database
Create a Postgres database and copy its connection string (with `sslmode=require`).

## 2. Secrets and seed (one time, from this repo)
```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_hosted.py secrets
$env:SENTINEL_DATABASE_URL = "<connection string>"
$env:SENTINEL_AUTH_PEPPER = "<pepper from above>"
.\.venv\Scripts\python.exe scripts\bootstrap_hosted.py seed --organization "My Team"
```
This prints four API keys **once** (admin, developer, reviewer, worker). Save them.

## 3. Backend on Render
Push the repo to GitHub. In Render, choose **New → Blueprint** and pick the repo (it reads `render.yaml`).
Both services build with `pip install .` on Python 3.11 — Docker is not needed locally or on Render.
- `sentinel-api`: `SENTINEL_DATABASE_URL`, `SENTINEL_AUTH_PEPPER`,
  `SENTINEL_CREDENTIAL_ENCRYPTION_KEY`, and
  `SENTINEL_ALLOWED_ORIGINS=https://<your-vercel-domain>`
- `sentinel-worker`: `SENTINEL_API_URL=https://<sentinel-api URL>` and
  `SENTINEL_WORKER_API_KEY=<worker key>`

Check it: `https://<sentinel-api URL>/health`.

## 4. Dashboard on Vercel
```powershell
npm i -g vercel
vercel login
cd web
vercel link            # create the project; Root Directory = web
vercel env add SENTINEL_API_ORIGIN production            # https://<sentinel-api URL>
vercel env add NEXT_PUBLIC_SENTINEL_API_URL production   # /sentinel-api
vercel --prod
```
If you deploy through Vercel's Git integration instead, set **Root Directory** to `web` and add the same two variables.

## 5. Connect
Open the Vercel URL, open the connection console, and use the admin key. The API URL is
pre-filled as `https://<vercel-domain>/sentinel-api`.

## Notes
- Without the two Vercel variables, the dashboard still deploys and shows its demo data,
  but it can't connect to an API.
- The Cloudflare/vinext build files are backed up in `.local/cloudflare-build-backup/`.
- The EstateFlow booking example (`SENTINEL_BOOKING_SERVICE_URL`) isn't deployed. It's optional.
