# Health OS — Local Stack

> One-command local health record for your family. Postgres + MinIO + FHIR + a tiny web UI, all on localhost.

[![status: alpha](https://img.shields.io/badge/status-alpha-orange)](https://github.com/QBe1n/patient-doctor-health-os)
[![docker compose](https://img.shields.io/badge/docker-compose-2496ed?logo=docker&logoColor=white)](docker-compose.yml)
[![FHIR R4](https://img.shields.io/badge/FHIR-R4-red)](https://hl7.org/fhir/R4/)
[![persistent volumes](https://img.shields.io/badge/data-persistent-success)]()

```
┌───────── http://localhost:3000 (Web UI, Jinja+HTMX) ─────────┐
│                                                              │
│   Family ──< Patient ──< Visit ──< Observation               │
│                │                                             │
│                ├──< Active problem ──< Personal task         │
│                └──< Files (PDF / images)                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                            │
   ┌────────────────────────┼────────────────────────┐
   ▼                        ▼                        ▼
 :8000  FastAPI         :9001  MinIO             :8080  HAPI FHIR R4
 (CRUD + uploads)       (PDF/photo storage)      (interop endpoint)
                            │
                            ▼
        Postgres 16 + pgvector  (named volume: health_os_pgdata)
```

## Quick start

```bash
make up                # start everything
make seed-kub          # (optional) load a fully-populated example patient
open http://localhost:3000
```

That's it. ~30 seconds on subsequent runs, ~2 minutes on the first build.

## The daily loop

> "Boot it up → enter data → shut it down → boot it up next month → all data still there."

```bash
make up        # morning
# work in the browser:
#   + new visit "GP, April 25"
#   + add HbA1c, LDL, blood pressure
#   + upload the lab PDF
#   + tick off "✓ done" on a follow-up task
make down      # evening, laptop goes to sleep

# next week:
make up        # everything is exactly where you left it
```

`docker compose down` keeps your data. Only `make nuke` deletes it.

## Services

| Service | Port | Persisted in |
|---|---|---|
| **Web UI** | 3000 | — |
| **Backend API** (FastAPI) | 8000 | — |
| **PostgreSQL 16 + pgvector** | 5432 | `health_os_pgdata` |
| **MinIO** (S3 + console) | 9000 / 9001 | `health_os_miniodata` |
| **HAPI FHIR R4** | 8080 | (in Postgres `fhir` DB) |
| **Ollama** *(opt-in)* | 11434 | `health_os_ollamadata` |

Ollama is gated behind `make ai-up` (compose profile `ai`). Skip it unless you want local LLMs for PDF ingestion.

## Commands

| Command | What it does |
|---|---|
| `make up` | Boot the whole stack |
| `make down` | Stop containers (data preserved) |
| `make restart` | Restart |
| `make seed-kub` | Idempotent seed: family + patient + visits + observations + problems + tasks |
| `make backup` | `pg_dump` + tar MinIO volume → `./backups/` |
| `make restore F=backups/db-…sql` | Restore the DB |
| `make logs` | Tail all service logs |
| `make shell-pg` | Open `psql` inside the Postgres container |
| `make shell-be` | Bash inside the backend container |
| `make ai-up` / `make ai-down` | Start/stop Ollama (compose profile `ai`) |
| `make nuke` | ⚠️ Delete all data (5-second pause) |

## Adding data

**Through the UI** (easiest): click around at `localhost:3000`.

**Through the API** (for scripts, automations, batch import):

```bash
# create a patient
curl -X POST http://localhost:8000/patients \
  -H 'Content-Type: application/json' \
  -d '{"full_name":"Jane Doe","birth_date":"1980-03-15","sex":"f"}'

# log an observation (auto-flagged against ref range)
curl -X POST http://localhost:8000/observations \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":"…","code":"HBA1C","value_num":5.4,"unit":"%",
       "ref_low":4.0,"ref_high":5.7,"observed_at":"2026-04-25T10:00:00+03:00"}'

# upload a PDF
curl -X POST http://localhost:8000/files \
  -F patient_id=… -F file=@results.pdf -F description="Lipid panel, April 2026"
```

Full Swagger UI at <http://localhost:8000/docs>.

## Backups

```bash
make backup
# → backups/db-20260425-120000.sql
# → backups/minio-20260425-120000.tar.gz

# copy off-machine
cp backups/db-*.sql /Volumes/MyBackup/health-os/
cp backups/minio-*.tar.gz /Volumes/MyBackup/health-os/
```

Restore:

```bash
make up
make restore F=backups/db-20260425-120000.sql

# MinIO restore (manual):
docker run --rm -v health_os_miniodata:/data -v $(pwd)/backups:/in alpine \
  sh -c "rm -rf /data/* && tar xzf /in/minio-20260425-120000.tar.gz -C /data"
```

## How it persists

```bash
docker volume ls | grep health_os
# health_os_pgdata
# health_os_miniodata
# health_os_ollamadata  (only if you ran make ai-up)
```

Volumes are independent of containers. `docker compose down`, OS reboot, Docker Desktop restart — none of those touch the data. The volumes only disappear when you explicitly run `docker compose down -v` (`make nuke`).

## Configuration

Copy `.env.example` to `.env` and edit if needed. Defaults are fine for localhost. **Change `MINIO_ROOT_PASSWORD` and `POSTGRES_PASSWORD` before exposing anything beyond your machine.**

## Architecture

- `db/init.sql` — schema (families, patients, visits, observations, active problems, personal tasks, files)
- `backend/` — FastAPI + SQLAlchemy + 20+ CRUD endpoints, MinIO uploads
- `web/` — Jinja2 + HTMX, server-rendered, no build step
- `scripts/seed_kubalskaya.py` — example data seeder
- `docker-compose.yml` — orchestration with named volumes

## Requirements

- Docker Desktop 24+ or Docker Engine + Compose plugin v2
- ~2 GB free RAM, ~4 GB disk (without Ollama; +10–30 GB with it)
- macOS, Linux, or Windows via WSL2

## Security

The stack listens on `localhost` only. To access from another device on your LAN, use [Tailscale](https://tailscale.com) — it handles encryption and access control. Don't expose these ports to the internet directly; there's no auth.

## Disclaimer

This is **not a medical device**. It's a personal record-keeping tool. All clinical decisions belong to a licensed physician.
