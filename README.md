# Patient & Doctor Health OS

> Local-first family health OS — your medical history, on your laptop. No cloud, no vendor, no NDA.

[![status: alpha](https://img.shields.io/badge/status-alpha-orange)](https://github.com/QBe1n/patient-doctor-health-os)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![FHIR R4](https://img.shields.io/badge/FHIR-R4-red)](https://hl7.org/fhir/R4/)
[![docker compose](https://img.shields.io/badge/docker-compose-2496ed?logo=docker&logoColor=white)](docker-compose.yml)
[![self-hosted](https://img.shields.io/badge/self--hosted-✓-success)]()

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│   Family ──< Patient ──< Visit ──< Observation (FHIR-style)          │
│                │                                                     │
│                ├──< Active problem ──> CarePlan template             │
│                │           │                                         │
│                │           └──< Personal task                        │
│                │                                                     │
│                └──< Files (PDF / images, stored in MinIO)            │
│                                                                      │
│   Postgres + pgvector  ·  MinIO  ·  HAPI FHIR  ·  FastAPI  ·  HTMX   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## Why

You see five different doctors. Each one has a partial picture, on paper, in their CRM, on a USB stick. Your last lipid panel is in a PDF you can't find. Three years of IOP readings are scattered across photos in your camera roll.

Health OS is a single timeline for one family (1–3 patients, in practice). Add a visit, paste in HbA1c, drop a PDF, mark a task done. Next time the doctor asks "when did this start?" — you have an answer, not a guess.

It runs entirely on your machine. Turn it off when you don't need it, turn it back on next month, all your data is still there.

**This is not a medical device.** It's a personal record-keeping tool and checklist. All clinical decisions belong to your physician.

## Quick start (60 seconds)

```bash
git clone https://github.com/QBe1n/patient-doctor-health-os
cd patient-doctor-health-os/local-stack
make up
```

Open <http://localhost:3000>. Add a family. Add a patient. Done.

Want a populated example? `make seed-kub` loads a realistic patient (3 visits, 9 observations, 5 active problems, 9 follow-up tasks) so you can see what a filled-in chart looks like before entering your own data.

## What you get

| URL | What it is |
|---|---|
| <http://localhost:3000> | Web UI — patients, visits, observations, tasks, files |
| <http://localhost:8000/docs> | REST API with Swagger — for scripts, automations, ingest agents |
| <http://localhost:9001> | MinIO console — every uploaded PDF, scan, photo |
| <http://localhost:8080> | HAPI FHIR R4 server — for interoperability with real medical systems |

All on `localhost`. Nothing leaves your machine.

## A real example

A patient is monitored for suspected glaucoma. Three visits over four months. Without Health OS you have a stack of paper. With it:

```bash
# add the visit
curl -X POST http://localhost:8000/visits \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":"…","visit_date":"2026-02-09","specialty":"ophth",
       "practitioner":"Dr. Pliss","summary":"IOP OS rose to 21.5 mmHg, perimetry recommended"}'

# log the readings — auto-flagged against reference range
curl -X POST http://localhost:8000/observations \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":"…","code":"IOP_OS","value_num":21.5,"unit":"mmHg",
       "ref_low":10,"ref_high":21,"observed_at":"2026-02-09T10:00:00+03:00"}'
# → flag: "high" (set automatically)

# upload the report PDF
curl -X POST http://localhost:8000/files \
  -F patient_id=… -F file=@report.pdf
```

Now the patient page shows the full IOP timeline (16.6 → 21.5), the linked PDF, the active problem ("Suspected glaucoma OS"), and a critical-priority task ("Perimetry + gonioscopy + OCT") with a deadline.

## How data persists

Everything lives in named Docker volumes:

```
health_os_pgdata      ← Postgres (patients, visits, observations, tasks)
health_os_miniodata   ← MinIO (every PDF and image you upload)
health_os_ollamadata  ← Ollama models (only if you use the AI profile)
```

`docker compose down` does **not** touch them. They survive reboots, OS upgrades, and Docker Desktop restarts. The only command that wipes data is `make nuke` (with a 5-second pause to think).

## Day-to-day commands

```bash
make up         # start the stack
make down       # stop (data is preserved)
make seed-kub   # load the example patient (idempotent)
make backup     # dump DB + tar MinIO into ./backups/
make restore F=backups/db-YYYY-MM-DD.sql
make logs       # tail logs
make ai-up      # start Ollama for local LLM ingest (optional)
make nuke       # ⚠️  wipe everything (with confirmation)
```

## Two stacks in one repo

This repo has two compose stacks. Pick one.

**`local-stack/`** — the recommended starting point. FastAPI + HTMX UI, Postgres + pgvector, MinIO, HAPI FHIR, optional Ollama. Boots in 30 seconds. Storage-only auth (localhost only). This is what `make up` above runs.

**Root `docker-compose.yml`** — the heavier "ingest research" stack. HAPI FHIR R4 + LOINC seed data + 14B+ LLMs via Ollama profiles. Aimed at building a lab-PDF ingestion pipeline. Documented separately in [`docs/health-os-plan-rf.md`](docs/health-os-plan-rf.md). Skip it unless you specifically want that.

## Roadmap

- [x] Family Mode schema (families → patients → visits → observations → problems → tasks)
- [x] Local Docker stack with persistent volumes
- [x] Web UI for manual entry
- [x] FHIR R4 endpoint for interop
- [ ] PDF ingest agent (lab reports → observations, with LOINC mapping)
- [ ] Trend charts in the UI (IOP, HbA1c, lipids over time)
- [ ] CarePlan template library (NAFLD, hypertension, glaucoma monitoring) → instantiated per patient
- [ ] Optional Notion mirror (this is the source of truth, Notion as read view)
- [ ] FHIR Bundle export (so you can move to a real EHR if needed)

## Status

Alpha. Built and used by one family. The schema works, the stack boots, data persists. Expect rough edges, no auth (localhost-only by design), and breaking schema changes before 1.0. PRs and issues welcome — especially from anyone running it for their own family.

## Contributing

This started as a personal tool. If you're using it for your own family, open an issue with what's missing or broken. Pull requests for ingest agents, CarePlan templates, or UI improvements are welcome.

For larger changes, open a discussion first. Code style: [Karpathy-grade simplicity](https://karpathy.bearblog.dev/simplicity/) — small files, obvious names, no premature abstractions.

## License

[MIT](LICENSE). Use it, fork it, run it for your grandmother.

## Disclaimer

Patient & Doctor Health OS is **not a medical device**, **not a substitute for medical advice**, and **not certified for clinical use**. It's a personal data tool and checklist. All diagnoses, treatments, and clinical decisions belong to a licensed physician.
