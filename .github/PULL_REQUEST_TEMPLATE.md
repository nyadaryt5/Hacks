<!-- Thanks for the PR! Please fill this out. -->

## Summary

<!-- What does this change and why? -->

## Test plan

<!-- How did you verify? Commands run, edge cases covered. -->

## Checklist

- [ ] Tests added/updated (`pytest` green)
- [ ] Coverage gate passes (`pytest --cov=ultron --cov-fail-under=85`)
- [ ] Lint clean (`flake8`, `ruff check`)
- [ ] Types clean (`mypy ultron-v6/ultron`)
- [ ] Security scan clean (`bandit -r ultron-v6/ultron -c pyproject.toml`)
- [ ] CHANGELOG entry added
- [ ] Authorized-testing safety model preserved
