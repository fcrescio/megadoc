.PHONY: format lint test up down logs migrate

format:
	python -m black packages services tests
	python -m ruff check --fix packages services tests

lint:
	python -m ruff check packages services tests
	python -m black --check packages services tests

test:
	pytest

up:
	docker compose --env-file .env up --build

down:
	docker compose down -v

logs:
	docker compose logs -f api worker

migrate:
	alembic upgrade head

