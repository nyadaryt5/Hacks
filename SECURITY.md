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
| 3 | **API key exposure** | `GOOGLE_API_KEY` and rotated keys grant billable API access; leakage means cost and quota abuse. | Keys are read only from the environment (`ultron/config.py`), never logged. In deployed contexts, source them from a secret manager (see below). The Budget Governor (`ultron/budget.py`) caps estimated tokens per session and enforces per-key RPM/RPD limits, bounding the blast radius of a leaked key. Provider-side spend and quota limits remain the authoritative USD control. |
| 4 | **Out-of-scope targeting** | The agent scans or exploits a host the operator was never authorized to touch — a legal and operational hazard. | `SafetyJail.validate_scope` authorizes only configured targets/networks; any IP literal outside scope is blocked (`ultron/safety.py`). Lateral-movement depth is capped (`ULTRON_MAX_LATERAL_DEPTH`). Operators must still confirm written authorization for every target. |
| 5 | **Runaway cost / DoS-of-wallet** | A loop or misbehaving model burns through API budget or floods a target. | `BudgetGovernor` (`ultron/budget.py`) enforces the session token ceiling and per-key request limits; its warning and graceful-termination paths provide operator intervention points. `ULTRON_MAX_ITERATIONS` bounds the FSM loop. Configure conservative limits for the deployment and monitor provider-side spend/quota as the authoritative USD control. |

### Key rotation and budget controls

The LLM client and budget governor are deliberately separate controls:

- `GoogleAIClient` (`ultron-v6/ultron/llm.py`) collects the primary
  `GOOGLE_API_KEY` plus `GOOGLE_API_KEY_1` through `GOOGLE_API_KEY_10`. It
  selects keys round-robin under a lock, never includes key values in logs or
  tracing attributes, and moves to the next key after an HTTP 429. Retries
  are bounded by `max_retries`; rotation is not a substitute for revoking a
  compromised key.
- `BudgetGovernor` (`ultron-v6/ultron/budget.py`) checks the estimated token
  cost before each request, enforces the session token ceiling, and tracks
  per-key requests-per-minute and requests-per-day limits. Successful calls
  record actual response-token usage. It emits a warning at the configured
  session threshold and supports graceful termination so an exposed key has
  a bounded blast radius.
- `ULTRON_MAX_ITERATIONS` independently bounds the coordinator loop. Keep
  the session and per-key limits conservative for production deployments.

If a key may have leaked, immediately revoke it with Google, replace it in
all secret stores, and review the usage and findings database. Do not rely on
rotation alone: a key that has already been copied can be used outside this
application.

### Secret management

`GOOGLE_API_KEY` (and `GOOGLE_API_KEY_1..10`) are read from plain environment
variables. This is acceptable for local, interactive use, but in **any
deployed or shared context** the key should be sourced from a dedicated
secret manager rather than a committed or long-lived `.env` file:

- **AWS Secrets Manager** / **GCP Secret Manager** / **HashiCorp Vault** —
  inject the value into the process environment at start-up.
- **GitHub Actions secrets** — for CI, never hard-code keys in workflow YAML.

For example, a deployment wrapper can fetch a secret without putting it in a
compose file or shell history (the exact IAM/Vault authentication is
platform-specific):

```bash
# AWS example: the process receives the value only in its environment.
export GOOGLE_API_KEY="$(aws secretsmanager get-secret-value \
  --secret-id ultron/google-api-key \
  --query SecretString --output text)"
exec ultron-v6 serve --host 0.0.0.0 --port 8080
```

For Vault, use the same pattern with a short-lived workload identity, for
example `vault kv get -field=GOOGLE_API_KEY secret/ultron`, and export the
result immediately before starting the process. Prefer short TTLs, least
privilege, audit logging, and automatic rotation in the provider.

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
