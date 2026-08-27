SHELL := /bin/bash
.DEFAULT_GOAL := help

export PYTHONPATH := src
export TF_CPP_MIN_LOG_LEVEL := 3

# Default to a zero-infra SQLite DB so every target works out of the box on a
# clean clone; override with `make seed DATABASE_URL=postgresql+psycopg2://...`
# or by exporting DATABASE_URL / creating .env.
DATABASE_URL ?= sqlite:///$(CURDIR)/artifacts/hwval.db
export DATABASE_URL

PY := python3
HWVAL := $(PY) -m hwval.cli

.PHONY: help install install-dev seed train evaluate score report testplan \
        maintain demo ask ui mcp test lint fmt docker-up docker-down clean

help: ## Show this help
	@echo "hwval — available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies (requirements.txt) + the package itself
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install -e .

install-dev: ## Install dev + tensorflow extras on top of the runtime deps
	$(PY) -m pip install -r requirements-dev.txt
	$(PY) -m pip install -e .

seed: ## Populate the database with synthetic validation data (override with DUTS=n)
	$(HWVAL) init
	$(HWVAL) seed --duts $${DUTS:-60}

train: ## Train the sklearn models + LSTM autoencoder (falls back to PCA without TF)
	$(HWVAL) train

evaluate: ## Compare trained models vs the naive spec-limit screen
	$(HWVAL) evaluate

score: ## Score all runs for anomalies and persist anomaly_event rows
	$(HWVAL) score

report: ## Build the validation report (override with FMT=md|html|pdf)
	$(HWVAL) report --fmt $${FMT:-html}

testplan: ## Generate a test plan (override with PRODUCT=..., STANDARD=...)
	$(HWVAL) testplan --product $${PRODUCT:-S32K344} --standard $${STANDARD:-AEC-Q100}

maintain: ## Run the DB maintenance plan (dry run; pass EXECUTE=1 to actually run it)
	$(HWVAL) maintain $$( [ "$$EXECUTE" = "1" ] && echo --execute )

demo: ## Run the full pipeline end to end (seed -> train -> score -> evaluate -> report -> ask)
	$(HWVAL) demo

ask: ## Ask the agent a question: make ask Q="What is the yield by corner?"
	$(HWVAL) ask "$(Q)"

ui: ## Launch the Streamlit demo app
	streamlit run app/streamlit_app.py

mcp: ## Run the MCP server (stdio by default; pass HTTP=8765 for streamable HTTP)
	$(PY) -m hwval.mcp_server.server $$( [ -n "$$HTTP" ] && echo --http $$HTTP )

test: ## Run the pytest suite with coverage
	$(PY) -m pytest --cov=hwval --cov-report=term-missing

lint: ## Run ruff checks
	ruff check .

fmt: ## Auto-fix lint issues and format
	ruff check --fix .
	ruff format .

docker-up: ## Start the docker-compose stack (db + app)
	docker compose up --build -d

docker-down: ## Stop the docker-compose stack
	docker compose down

clean: ## Remove caches and generated artifacts
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name '__pycache__' -not -path './.git/*' -exec rm -rf {} +
	rm -rf artifacts/models artifacts/figures artifacts/reports artifacts/*.db
