PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
PACKAGE := ./ultron-v6

.PHONY: install dev test coverage lint typecheck security build \
        docker-up docker-down docker-test lockfile-check clean

install:            ## Install the package from the pinned runtime lockfile
	$(PIP) install -r "$(PACKAGE)/requirements.lock"
	$(PIP) install --no-deps -e "$(PACKAGE)"

dev:                ## Install the package from pinned runtime and dev lockfiles
	$(PIP) install -r "$(PACKAGE)/requirements.lock"
	$(PIP) install -r "$(PACKAGE)/requirements-dev.lock"
	$(PIP) install --no-deps -e "$(PACKAGE)"

test:               ## Run the test suite
	$(PYTEST) tests

coverage:           ## Run tests with the coverage gate
	$(PYTEST) tests --cov=ultron --cov-report=term-missing --cov-fail-under=85

lint:               ## Run flake8 and ruff
	$(PYTHON) -m flake8 ultron-v6/ultron ultron-v6/ultron_v6.py tests
	$(PYTHON) -m ruff check ultron-v6/ultron ultron-v6/ultron_v6.py

typecheck:          ## Run strict mypy
	$(PYTHON) -m mypy ultron-v6/ultron ultron-v6/ultron_v6.py

security:           ## Run bandit and pip-audit
	$(PYTHON) -m bandit -r ultron-v6/ultron -c pyproject.toml
	$(PYTHON) -m pip_audit --requirement ultron-v6/requirements.lock

build:              ## Build wheel and sdist
	$(PYTHON) -m build ultron-v6 --outdir dist

docker-up:          ## Start the app with docker compose
	docker compose up --build -d

docker-down:        ## Stop the compose stack
	docker compose down

docker-test:        ## Run the test suite inside the container
	docker compose run --rm test

lockfile-check:     ## Fail if pip-compile would change committed lockfiles
	cd ultron-v6 && pip-compile --dry-run --quiet --output-file=requirements.lock requirements.in
	cd ultron-v6 && pip-compile --dry-run --quiet --output-file=requirements-dev.lock requirements-dev.in
	cd ultron-v6 && pip-compile --dry-run --quiet --output-file=requirements-chroma.lock requirements-chroma.in

clean:              ## Remove build artifacts
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
