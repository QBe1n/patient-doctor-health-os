# Health OS — локальные команды
# Все данные в named volumes — переживают down/up.
# `down -v` сотрёт всё (включая БД и MinIO).

.PHONY: help up down restart status logs ps build seed seed-kub backup restore prune nuke shell-pg shell-be ai-up ai-down

help:
	@echo "Health OS — локальные команды"
	@echo ""
	@echo "  make up          - запустить весь стек в фоне"
	@echo "  make down        - остановить стек (данные СОХРАНЯЮТСЯ)"
	@echo "  make restart     - перезапустить"
	@echo "  make status      - статус контейнеров"
	@echo "  make logs        - логи всех сервисов (Ctrl+C для выхода)"
	@echo "  make build       - пересобрать backend/web после правок кода"
	@echo "  make seed-kub    - засеять пациента Кубальскую И.В."
	@echo "  make backup      - бэкап БД и файлов в ./backups/"
	@echo "  make restore F=…  - восстановить из бэкапа (см. backups/)"
	@echo "  make ai-up       - поднять Ollama (LLM-профиль)"
	@echo "  make nuke        - ⚠️  удалить ВСЕ данные (БД + файлы)"
	@echo ""
	@echo "URLs после up:"
	@echo "  Web UI:        http://localhost:3000"
	@echo "  Backend API:   http://localhost:8000/docs"
	@echo "  MinIO console: http://localhost:9001"
	@echo "  HAPI FHIR:     http://localhost:8080"

up:
	@[ -f .env ] || cp .env.example .env
	docker compose up -d --build
	@echo ""
	@echo "✓ Стек запущен. Открой http://localhost:3000"

down:
	docker compose down

restart:
	docker compose restart

status ps:
	docker compose ps

logs:
	docker compose logs -f --tail=200

build:
	docker compose build backend web

seed-kub:
	docker compose exec backend python /app/../scripts/seed_kubalskaya.py || \
	docker compose run --rm -v $(PWD)/scripts:/scripts backend python /scripts/seed_kubalskaya.py

ai-up:
	docker compose --profile ai up -d ollama
	@echo "Ollama: http://localhost:11434"
	@echo "Чтобы скачать модель:  docker exec -it health-os-ollama ollama pull llama3.1:8b"

ai-down:
	docker compose stop ollama

# ── Бэкап ──────────────────────────────────────────────────────
backup:
	@mkdir -p backups
	@TS=$$(date +%Y%m%d-%H%M%S); \
	echo "→ Дамп БД..."; \
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER:-healthos} $${POSTGRES_DB:-healthos} > backups/db-$$TS.sql; \
	echo "→ Архив MinIO..."; \
	docker run --rm -v health_os_miniodata:/data -v $(PWD)/backups:/out alpine \
	  tar czf /out/minio-$$TS.tar.gz -C /data .; \
	echo "✓ backups/db-$$TS.sql"; \
	echo "✓ backups/minio-$$TS.tar.gz"

restore:
	@[ -n "$(F)" ] || (echo "Usage: make restore F=backups/db-YYYY...sql"; exit 1)
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-healthos} -d $${POSTGRES_DB:-healthos} < $(F)
	@echo "✓ восстановлено из $(F)"

# ── Утилиты ────────────────────────────────────────────────────
shell-pg:
	docker compose exec postgres psql -U $${POSTGRES_USER:-healthos} -d $${POSTGRES_DB:-healthos}

shell-be:
	docker compose exec backend bash

prune:
	docker compose down
	docker image prune -f

nuke:
	@echo "⚠️  Это удалит БД, MinIO и Ollama-модели. Повтори через 5 секунд (Ctrl+C для отмены)..."
	@sleep 5
	docker compose down -v
	@echo "✓ всё снесено"
