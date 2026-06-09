# M3 — Deployment & Secrets Runbook

## Prerequisites

- Docker + Docker Compose v2
- `.env` files: `sentinel.env` (backend) and `frontend-next/.env.local` (frontend)
- PostgreSQL 15 + PostGIS via `docker compose up -d`
- JWT secret injected via secrets manager in production (see below)

## Environment Setup

### Backend (`sentinel.env`)

```ini
# Copy from template — NEVER commit real secrets
cp sentinel.env.example sentinel.env
```

### Frontend (`frontend-next/.env.local`)

```ini
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_MAP_STYLE=https://demotiles.maplibre.org/style.json
```

## Secrets Management

> **Critical:** `SENTINEL_JWT_SECRET` must never use the default value in production.

The default `SENTINEL_JWT_SECRET` in `sentinel.env.example` is a placeholder. In production, inject the real secret from your secrets manager:

- **Kubernetes:** `envFrom` + `Secret`
- **Docker Compose:** `SENTINEL_JWT_SECRET` in `environment` block, sourced from a `.secrets` file or vault sidecar
- **Manual:** set the env var in the runtime environment, ensuring it is ≥32 bytes and random

The application refuses to start if `SENTINEL_ENV=production` and the secret still matches the compiled-in placeholder.

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SENTINEL_JWT_SECRET` | prod | placeholder | HS256 signing key — inject from secrets manager |
| `SENTINEL_JWT_ALG` | no | HS256 | JWT signing algorithm |
| `SENTINEL_JWT_TTL_MIN` | no | 720 | Token lifetime (minutes) |
| `SENTINEL_ENV` | no | development | Set to `production` to enable the default-secret guard |

## Demo Credentials (local only)

> **⚠️ Must rotate before any public exposure.** Default admin/admin and analyst/analyst credentials undercut the entire auth gate.

The `013_create_users.sql` migration seeds two default accounts:

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin` | admin — can edit source trust tiers |
| `analyst` | `analyst` | analyst — read-only |

**Before any public-facing deployment**, change these passwords:

```sql
-- Connect to the DB and run:
UPDATE users SET password_hash = crypt('new_secure_password', gen_salt('bf'))
WHERE username = 'admin';
```

Or set different credentials in `api/auth.py:seed_default_users()` before the first run (the INSERT uses `ON CONFLICT DO NOTHING`, so first-write wins).

## Deployment

### Local (full stack)

```bash
docker compose up -d --build
```

This starts: PostgreSQL+PostGIS, PgBouncer, the FastAPI gateway (`api`), pipeline workers, and the Next.js frontend (`frontend-next`). The app is reachable at `http://localhost:3000`.

### Production considerations

- Place the FastAPI gateway behind a reverse proxy (nginx, Caddy, Traefik) with TLS termination
- Set `SENTINEL_ENV=production` and inject `SENTINEL_JWT_SECRET` from a secrets manager
- Build the frontend with `NEXT_PUBLIC_API_BASE` set to the **browser-reachable** API URL (this is a build-time arg, not runtime — the value is inlined into the JS bundle):

  ```bash
  docker compose build --build-arg NEXT_PUBLIC_API_BASE=https://api.yourdomain.com frontend-next
  ```
- **Rotate or disable the default demo credentials** (admin/admin, analyst/analyst) before any public deployment
- Rate-limit `/auth/login` to prevent brute-force attacks
- Rotate JWT signing keys periodically

## Accepted Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `/auth/login` has no rate limit | Medium | The only unauthenticated endpoint; brute-force could enumerate credentials. Accept for M3; add rate limiting in a follow-up sprint (FastAPI middleware or reverse-proxy sidecar). |
| Default demo credentials (admin/admin, analyst/analyst) | High | Must be rotated before any public deployment (see above). |
| `NEXT_PUBLIC_*` vars are build-time inlined | Low | Cannot be overridden at runtime. A rebuild is required to change the API base URL. Documented above — always rebuild with `--build-arg` for environment changes. |

## Retired Components

- **Streamlit dashboard** (`frontend/`): retired in M3 in favor of `frontend-next/`. Source kept as historical reference only.
