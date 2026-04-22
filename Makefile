.PHONY: help install install-dev lint format typecheck security validate-feature-views test test-unit test-integration ci compose-up compose-down compose-clean bootstrap-local seed-sample-events run-streaming-features train-local generate-baseline check-drift feast-sync clean all

PYTHON := python3.11
VENV := .venv
VENV_BIN := $(VENV)/bin

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-28s\033[0m %s\n", $$1, $$2}'

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(VENV_BIN)/pip install --upgrade pip setuptools wheel

install: $(VENV)/bin/activate  ## Install runtime deps
	$(VENV_BIN)/pip install -e .

install-dev: $(VENV)/bin/activate  ## Install dev deps
	$(VENV_BIN)/pip install -e ".[dev]"

lint:  ## Ruff lint
	$(VENV_BIN)/ruff check src tests scripts

format:  ## Auto-format
	$(VENV_BIN)/ruff format src tests scripts
	$(VENV_BIN)/ruff check --fix src tests scripts

typecheck:  ## mypy type check
	$(VENV_BIN)/mypy src --ignore-missing-imports

security:  ## Bandit security scan
	$(VENV_BIN)/bandit -c pyproject.toml -r src scripts -lll

validate-feature-views:  ## Validate Feast feature views
	$(VENV_BIN)/python scripts/validate_feature_views.py src/feast_repo/feature_views/

test-unit:  ## Fast unit tests
	$(VENV_BIN)/pytest tests/unit -v -m unit

test-integration:  ## Integration tests (requires compose-up)
	$(VENV_BIN)/pytest tests/integration -v -m integration

test: test-unit  ## Alias for test-unit

ci: lint typecheck security validate-feature-views test-unit  ## Full local CI

compose-up:  ## Start LocalStack + Postgres + Redis + MLflow
	docker compose -f compose/docker-compose.yml up -d
	@sleep 10
	@echo "Stack started. Run 'make bootstrap-local' to provision test resources."

compose-down:  ## Stop containers (keeps data)
	docker compose -f compose/docker-compose.yml down

compose-clean:  ## Stop + destroy volumes
	docker compose -f compose/docker-compose.yml down -v

bootstrap-local:  ## Create Kinesis + DynamoDB + S3 + Feast registry locally
	bash compose/localstack-init.sh

seed-sample-events:  ## Push synthetic events to local Kinesis
	$(VENV_BIN)/python scripts/seed_sample_events.py

run-streaming-features:  ## Run the streaming feature Lambda as a local process
	LOCAL_DEV=true $(VENV_BIN)/python -m lambdas.streaming_feature_pipeline_local

train-local:  ## Train locally on synthetic data
	$(VENV_BIN)/features train \
		--model-type xgboost \
		--training-data-path ./data/local_training.parquet \
		--label-column churned \
		--mlflow-tracking-uri http://localhost:5000 \
		--output-dir ./model-output

generate-baseline:  ## Generate Model Monitor baseline
	$(VENV_BIN)/features generate-baseline \
		--input-path ./data/local_training.parquet \
		--output-dir ./baseline/

check-drift:  ## Run drift detection locally
	$(VENV_BIN)/features check-drift \
		--baseline-path ./baseline/baseline.parquet \
		--current-path ./data/local_current.parquet \
		--output-path ./drift-report.json

feast-sync:  ## Apply Feast registry (dry-run by default)
	$(VENV_BIN)/features feast-sync --dry-run

terraform-init-dev:
	cd infra/terraform && terraform init -backend-config=envs/dev.backend.hcl

terraform-plan-dev:
	cd infra/terraform && terraform plan -var-file=envs/dev.tfvars

terraform-apply-dev:
	cd infra/terraform && terraform apply -var-file=envs/dev.tfvars

clean:  ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info/
	rm -rf .pytest_cache/ .coverage htmlcov/
	rm -rf spark-warehouse/ metastore_db/ derby.log *.log
	rm -rf mlruns/ mlartifacts/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

all: install-dev ci  ## Install + run full CI
