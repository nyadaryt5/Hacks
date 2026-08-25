# Contributing to ULTRON v6

Thanks for contributing! A few conventions keep the project healthy.

## Development setup

```bash
git clone https://github.com/nyadaryt5/Hacks.git
cd Hacks
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./ultron-v6[dev]"
pre-commit install
```

## Quality gates (run before pushing)

```bash
make test        # pytest
make coverage    # 85% coverage gate
make lint        # flake8 + ruff
make typecheck   # strict mypy
make security    # bandit + pip-audit
```

CI runs the same checks on every push and PR
(`.github/workflows/ci.yml`) across Python 3.10–3.12.

## Commit conventions

- One logical change per commit; ship each fix **together with its test**
  so history shows fix+test pairs.
- Conventional-commit style prefixes: `fix:`, `feat:`, `refactor:`,
  `test:`, `docs:`, `build:`, `ci:`, `chore:`.
- Add a CHANGELOG entry for user-visible changes.

## Pull requests

- Reference the issue you're fixing.
- **Each PR must include tests for its behavior change** — new public
  behavior ships with the tests that pin it in the same commit.
- Keep the diff focused; no bulk formatting mixed with features.
- Wait for CI to pass before requesting review.

## Style

- Python 3.10+; type hints everywhere (mypy strict).
- Line length 88 (see `pyproject.toml`); ruff/flake8 must be clean.
- Public API changes must stay re-exported from `ultron_v6` for
  backwards compatibility.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
