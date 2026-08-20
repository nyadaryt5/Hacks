# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 6.1.x   | :white_check_mark: |
| < 6.1   | :x:                |

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Report vulnerabilities privately via GitHub's
[private vulnerability reporting](https://github.com/nyadaryt5/Hacks/security/advisories/new)
or by contacting the maintainer directly.

Please include:

- A description of the vulnerability and its impact
- Steps to reproduce (or a proof of concept)
- Affected versions

We will acknowledge your report within 7 days and aim to publish a fix
within 30 days. We ask that you allow 90 days before any public disclosure.

## Intended use

ULTRON is a penetration testing framework for **authorized security
assessments only**. Using it against systems without explicit written
permission is illegal in most jurisdictions and not supported. The safety
features (scope validation, command jail, debate protocol) reduce risk but
do not replace authorization, scoping agreements, or professional judgment.

## Threat model

ULTRON is an LLM-driven agent that proposes and executes shell commands
against targets. That combination — an untrusted model output driving a
command executor — is the core of its risk surface. The trust boundaries and
their mitigations are documented below. Treat every mitigation as
defence-in-depth, not a guarantee.

### Trust boundaries

```text
operator ── target scope ──▶ Coordinator ──▶ LLM (Gemini, untrusted output)
                                 │                     │
                                 │              proposes command
                                 ▼                     ▼
                          Safety Jail ◀──── Debate Protocol (risky actions)
                                 │
                                 ▼
                          subprocess (shell=False) ──▶ authorized target only
```

The **untrusted zone** is everything the LLM returns and everything a target
sends back (banners, scan output). The **trusted zone** is the operator's
configuration: the authorized scope, budgets, and denylists.

### Risks and mitigations

| # | Risk | Description | Mitigation |
|---|------|-------------|------------|
| 1 | **LLM prompt injection** | A target's banner, page, or scan output is fed back into the model and could try to steer it into out-of-scope or destructive actions. | Every model-proposed command passes through the Safety Jail before execution (`ultron/safety.py`): destructive-pattern denylist + per-IP scope validation. The system prompt pins the model to an authorized-testing context (`ultron/llm.py`, `GEMINI_CONTEXT_PREFIX`). |
| 2 | **Safety-jail bypass** | An attacker (or a creative model) crafts a command that evades the denylist or smuggles an out-of-scope target. | `SafetyJail.filter_command` (`ultron/safety.py`) matches `FORBIDDEN_PATTERNS` case-insensitively and rejects any IP literal not inside `allowed_networks` / `allowed_targets`. Commands run with `shell=False` (no shell metacharacter expansion). Risky/destructive plans additionally require adversarial approval via the debate protocol (`ultron/debate.py`). Report any bypass privately (see above). |
| 3 | **API key exposure** | `GOOGLE_API_KEY` and rotated keys grant billable API access; leakage means cost and quota abuse. | Keys are read only from the environment (`ultron/config.py`), never logged. In deployed contexts, source them from a secret manager (see below). The Budget Governor (`ultron/budget.py`) caps tokens/cost per session and enforces per-key RPM/RPD limits, bounding the blast radius of a leaked key. |
| 4 | **Out-of-scope targeting** | The agent scans or exploits a host the operator was never authorized to touch — a legal and operational hazard. | `SafetyJail.validate_scope` authorizes only configured targets/networks; any IP literal outside scope is blocked (`ultron/safety.py`). Lateral-movement depth is capped (`ULTRON_MAX_LATERAL_DEPTH`). Operators must still confirm written authorization for every target. |
| 5 | **Runaway cost / DoS-of-wallet** | A loop or misbehaving model burns through API budget or floods a target. | `BudgetGovernor` (`ultron/budget.py`) enforces per-minute/hour/session token budgets and a session USD cap; `ULTRON_MAX_ITERATIONS` bounds the FSM loop. |

### Secret management

`GOOGLE_API_KEY` (and `GOOGLE_API_KEY_1..10`) are read from plain environment
variables. This is acceptable for local, interactive use, but in **any
deployed or shared context** the key should be sourced from a dedicated
secret manager rather than a committed or long-lived `.env` file:

- **AWS Secrets Manager** / **GCP Secret Manager** / **HashiCorp Vault** —
  inject the value into the process environment at start-up.
- **GitHub Actions secrets** — for CI, never hard-code keys in workflow YAML.

Never commit real keys. `.env` is git-ignored; `ultron-v6/.env.example`
documents the variables with placeholder values only.

### Out of scope for this threat model

- Vulnerabilities in the target systems themselves (that is what ULTRON is
  for) and the legality of a given engagement (the operator's responsibility).
- Compromise of the host running ULTRON or of the operator's cloud/API
  credentials outside the mechanisms above.

## Automated security scanning

Every push and pull request runs static and dependency security scans in CI
(`.github/workflows/ci.yml`):

- **bandit** — static analysis of `ultron-v6/ultron`.
- **pip-audit** — known-vulnerability audit of the pinned
  `ultron-v6/requirements.lock`.

Dependency freshness is tracked by Dependabot (`.github/dependabot.yml`).
