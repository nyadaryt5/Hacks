PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
PACKAGE := ./ultron-v6
PROJECT := .

.PHONY: install dev test coverage lint typecheck security build \
        docker-up docker-down docker-test lockfiles lockfile-upgrade \
        lockfile-check clean

install:            ## Install from pinned build/runtime lockfiles
	$(PIP) install -r "$(PACKAGE)/requirements-build.lock"
	$(PIP) install -r "$(PACKAGE)/requirements.lock"
	$(PIP) install --no-build-isolation --no-deps -e "$(PROJECT)"

dev:                ## Install from pinned build/runtime/dev lockfiles
	$(PIP) install -r "$(PACKAGE)/requirements-build.lock"
	$(PIP) install -r "$(PACKAGE)/requirements.lock"
	$(PIP) install -r "$(PACKAGE)/requirements-dev.lock"
	$(PIP) install --no-build-isolation --no-deps -e "$(PROJECT)"

test:               ## Run the test suite
	$(PYTEST) tests

coverage:           ## Run tests with the coverage gate
	$(PYTEST) tests --cov=ultron --cov-report=term-missing --cov-fail-under=85

lint:               ## Run flake8 and ruff
	$(PYTHON) -m flake8 ultron-v6/ultron ultron-v6/ultron_v6.py tests
	$(PYTHON) -m ruff check ultron-v6/ultron ultron-v6/ultron_v6.py

typecheck:          ## Run strict mypy
	$(PYTHON) -m mypy ultron-v6/ultron ultron-v6/ultron_v6.py

security:           ## Run Bandit and strict audits for every dependency set
	$(PYTHON) -m bandit -r ultron-v6/ultron -c pyproject.toml
	@for lock in requirements-build.lock requirements.lock requirements-dev.lock \
		requirements-chroma.lock requirements-all.lock; do \
		$(PYTHON) -m pip_audit --strict --progress-spinner=off \
			--requirement "ultron-v6/$$lock" || exit $$?; \
	done

build:              ## Build wheel and sdist
	$(PYTHON) -m build --no-isolation "$(PROJECT)" --outdir dist

docker-up:          ## Start the app with docker compose
	docker compose up --build -d

docker-down:        ## Stop the compose stack
	docker compose down

docker-test:        ## Run the test suite inside the container
	docker compose run --rm test

lockfiles:          ## Regenerate locks with Python 3.11, preserving pins
	$(PYTHON) scripts/lockfiles.py --write

lockfile-upgrade:   ## Upgrade locks with the Python 3.11 baseline
	$(PYTHON) scripts/lockfiles.py --write --upgrade

lockfile-check:     ## Fail on manifest drift or mismatched root mirrors
	$(PYTHON) scripts/lockfiles.py --check

clean:              ## Remove build artifacts
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
