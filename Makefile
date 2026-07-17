.PHONY: sync lint typecheck test analyze doctor infra-fmt infra-validate schema

sync:
	uv sync --extra dev

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy --strict src

test:
	uv run pytest --cov-report=json --cov-report=term-missing --cov-fail-under=80
	uv run python scripts/check_coverage_gates.py

analyze:
	uv run slowlog analyze

doctor:
	uv run slowlog doctor

schema:
	mkdir -p schemas
	uv run python -m slowlog_agent.schemas > schemas/analysis_report.schema.json

infra-fmt:
	terraform -chdir=terraform fmt -check

infra-validate:
	terraform -chdir=terraform init -backend=false && terraform -chdir=terraform validate

infra: infra-fmt infra-validate
	terraform -chdir=terraform apply
