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

The `013_create_users.sql` migration seeds two default accounts:

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin` | admin — can edit source trust tiers |
| `analyst` | `analyst` | analyst — read-only |

These default credentials are suitable for local development only. In any public-facing demo, **change these passwords before deployment**. The `seed_default_users()` function in `api/auth.py` runs on a CONFLICT DO NOTHING basis, so manual SQL can be used to set different credentials before the first login.

## Deployment

### Local (full stack)

```bash
docker compose up -d --build
```

This starts: PostgreSQL+PostGIS, PgBouncer, the FastAPI gateway (`api`), pipeline workers, and the Next.js frontend (`frontend-next`). The app is reachable at `http://localhost:3000`.

### Production considerations

- Place the FastAPI gateway behind a reverse proxy (nginx, Caddy, Traefik) with TLS termination
- Set `SENTINEL_ENV=production` and inject `SENTINEL_JWT_SECRET` from a secrets manager
- Set `NEXT_PUBLIC_API_BASE` to the public-facing API URL
- Rate-limit `/auth/login` to prevent brute-force attacks
- Rotate JWT signing keys periodically
- The demo credentials (admin/analyst) must be changed before any public deployment

## Retired Components

- **Streamlit dashboard** (`frontend/`): retired in M3 in favor of `frontend-next/`. Source kept as historical reference only.
