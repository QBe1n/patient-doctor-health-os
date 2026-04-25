SHELL := /bin/bash

.DEFAULT_GOAL := help

## Создать секреты, если их ещё нет
secrets:
	@mkdir -p secrets
	@test -s secrets/pg_user        || echo -n "healthos"   > secrets/pg_user
	@test -s secrets/pg_password    || openssl rand -base64 32 | tr -d '\n' > secrets/pg_password
	@test -s secrets/minio_user     || echo -n "minioadmin" > secrets/minio_user
	@test -s secrets/minio_password || openssl rand -base64 32 | tr -d '\n' > secrets/minio_password
	@chmod 600 secrets/pg_password secrets/minio_password
	@echo "✓ Секреты готовы в ./secrets/"

## Поднять весь стек (первый запуск тянет образы и модели — 15–30 минут)
up: secrets
	docker compose up -d
	@echo ""
	@echo "Ждите пока все healthcheck'и станут healthy:"
	@echo "  make wait"

## Остановить, НЕ трогая данные
down:
	docker compose down

## СТЕРЕТЬ ВСЁ (включая volumes с данными) — осторожно
nuke:
	docker compose down -v

## Статусы сервисов
ps:
	docker compose ps

## Логи всех сервисов
logs:
	docker compose logs -f --tail=100

## Ждём пока всё поднимется и healthy
wait:
	@echo "Жду HAPI FHIR…"
	@until curl -fsS http://localhost:8080/fhir/metadata >/dev/null 2>&1; do sleep 3; done
	@echo "✓ HAPI готов"
	@echo "Жду MinIO…"
	@until curl -fsS http://localhost:9000/minio/health/ready >/dev/null 2>&1; do sleep 2; done
	@echo "✓ MinIO готов"
	@echo "Жду Ollama…"
	@until curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; do sleep 2; done
	@echo "✓ Ollama готов"

## Smoke test: пишем и читаем минимальный Patient в HAPI
smoke:
	@echo "→ Создаю тестового Patient в HAPI…"
	@curl -sS -X POST http://localhost:8080/fhir/Patient \
	  -H "Content-Type: application/fhir+json" \
	  -d '{"resourceType":"Patient","name":[{"family":"Test","given":["Smoke"]}],"gender":"male","birthDate":"1990-01-01"}' \
	  | jq '.id,.meta.versionId' || true
	@echo "→ Запрашиваю список Patient…"
	@curl -sS "http://localhost:8080/fhir/Patient?_count=3" | jq '.total, .entry[]?.resource.name' || true
	@echo "→ Список моделей Ollama:"
	@curl -sS http://localhost:11434/api/tags | jq '.models[].name' || true
	@echo "→ Бакеты MinIO:"
	@docker compose exec -T minio mc alias set local http://localhost:9000 \
	  "$$(cat secrets/minio_user)" "$$(cat secrets/minio_password)" >/dev/null 2>&1 || true
	@docker compose exec -T minio mc ls local 2>/dev/null || true

## psql shell в ingest-базу
psql-ingest:
	docker compose exec postgres psql -U "$$(cat secrets/pg_user)" -d ingest

## psql shell в hapi-базу
psql-hapi:
	docker compose exec postgres psql -U "$$(cat secrets/pg_user)" -d hapi

## Подтянуть новые модели Ollama (перечитывает ollama/init.sh)
ollama-pull:
	docker compose run --rm --no-deps ollama-init

help:
	@awk 'BEGIN{FS=":.*##"; printf "\nHealth OS — локальный стек\n\nКоманды:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 } /^##/ { sub(/^## */, ""); printf "  %s\n", $$0 }' $(MAKEFILE_LIST) | sort -u

.PHONY: secrets up down nuke ps logs wait smoke psql-ingest psql-hapi ollama-pull help
