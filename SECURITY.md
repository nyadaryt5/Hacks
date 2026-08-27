# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 6.2.x   | :white_check_mark: |
| < 6.2   | :x:                |

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
| 1 | **LLM prompt injection** | A target's banner, page, or scan output is fed back into the model and could try to steer it into out-of-scope or destructive actions. | Every model-proposed command passes through the Safety Jail before execution (`ultron-v6/ultron/safety.py`): destructive-pattern denylist + per-IP scope validation. The system prompt pins the model to an authorized-testing context (`ultron-v6/ultron/llm.py`, `GEMINI_CONTEXT_PREFIX`). |
| 2 | **Safety-jail bypass** | An attacker (or a creative model) crafts a command that evades the denylist or smuggles an out-of-scope target. | `SafetyJail.filter_command` (`ultron-v6/ultron/safety.py`) matches `FORBIDDEN_PATTERNS` case-insensitively and rejects unauthorized IPv4, IPv6, URL hosts, and bare DNS names. Commands run with `shell=False` and shell metacharacters are refused. Risky/destructive plans additionally require adversarial approval via the debate protocol (`ultron-v6/ultron/debate.py`). Report any bypass privately (see above). |
| 3 | **API/cloud key exposure** | Model, Vault, cloud, and telemetry credentials grant billable or privileged access; leakage means data, quota, or wallet abuse. | Deployed contexts resolve Gemini keys from a manager (see below), values are never logged, and manager failures are fail-closed. `_tool_environment()` strips Gemini, Vault, AWS, GCP-credential-path, and Sentry values before launching untrusted tools. The Budget Governor caps estimated tokens and per-key RPM/RPD. Provider-side IAM, revocation, spend, and quota limits remain authoritative. |
| 4 | **Out-of-scope targeting** | The agent scans or exploits a host the operator was never authorized to touch — a legal and operational hazard. | `SafetyJail.validate_scope` authorizes only configured targets/networks; any IP literal outside scope is blocked (`ultron-v6/ultron/safety.py`). Lateral-movement depth is capped (`ULTRON_MAX_LATERAL_DEPTH`). Operators must still confirm written authorization for every target. |
| 5 | **Runaway cost / DoS-of-wallet** | A loop or misbehaving model burns through API budget or floods a target. | `BudgetGovernor` (`ultron-v6/ultron/budget.py`) enforces the session token ceiling and per-key request limits; its warning and graceful-termination paths provide operator intervention points. `ULTRON_MAX_ITERATIONS` bounds the FSM loop. Configure conservative limits for the deployment and monitor provider-side spend/quota as the authoritative USD control. |

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

`GOOGLE_API_KEY` (and `GOOGLE_API_KEY_1` … `GOOGLE_API_KEY_10`) may be
read from the process environment for local use. In **any deployed or shared
context**, set `ULTRON_SECRETS_BACKEND` to `aws`, `vault`, or `gcp`.
`ultron-v6/ultron/secrets.py` then fetches the key through boto3 Secrets Manager,
HashiCorp Vault KV v2 (`hvac`), or GCP Secret Manager before settings load.

The secret data flow and failure policy are explicit:

1. The selected provider authenticates using workload identity or its SDK's
   standard credential chain; provider credentials are not stored by ULTRON.
2. The provider payload may be a raw key or JSON containing
   `GOOGLE_API_KEY`. The resolved value replaces `GOOGLE_API_KEY` in this
   process so settings and the LLM client have one source of truth.
3. The value is never written to the database, reports, traces, or logs.
   Child pentest tools receive a sanitized environment with model, Vault,
   cloud, and telemetry credentials removed.
4. Manager mode is **fail-closed**. Unknown backends, missing SDKs or manager
   settings, access errors, and empty payloads abort startup with
   `ConfigurationError`; ULTRON does not fall back to a stale env key.
5. `env` mode alone permits `GOOGLE_API_KEY` / numbered-key fallback. The
   offline health server does not resolve a key at startup.

CI uses no live Gemini credential. If a future workflow needs a credential,
use GitHub Actions secrets or OIDC workload identity and never hard-code it in
workflow YAML.

For example, an AWS-backed scan can rely on the SDK credential chain without
putting the Gemini value in a compose file or shell history:

```bash
python -m pip install -r ultron-v6/requirements-all.lock
export ULTRON_SECRETS_BACKEND=aws
export ULTRON_AWS_SECRET_ID=ultron/google-api-key
export ULTRON_AWS_REGION=us-east-1
exec ultron-v6 run authorized.example
```

Use short-lived workload identity, least-privilege read access to only the
configured secret, provider audit logs, and automatic rotation. Vault tokens
should have a short TTL and a policy limited to `ULTRON_VAULT_SECRET_PATH`;
GCP workloads should use Application Default Credentials with only Secret
Accessor on `ULTRON_GCP_SECRET_NAME`.

Never commit real keys. Real `.env` variants are excluded from Git and Docker
build contexts; the only explicit exceptions are root and package
`.env.example` templates, whose credential fields are empty.

### Known residual risks

- **A denylist is not a sandbox.** `SafetyJail`, `shell=False`, scope parsing,
  and debate reduce risk but cannot prove an arbitrary binary invocation safe.
  Run ULTRON as an unprivileged user in an isolated container/VM with a
  read-only base filesystem, restricted egress, and no host/cloud credentials.
- **DNS and parser ambiguity remain.** A domain can change resolution after a
  scope check, tools may accept unusual numeric/encoded host forms, and future
  command syntaxes may introduce parser gaps. Authorize exact targets, monitor
  traffic externally, and treat any jail bypass as a vulnerability.
- **Prompt injection is not eliminated.** Target-controlled banners and pages
  remain untrusted even after command filtering; a model can still propose a
  harmful but syntactically allowed action. Human supervision is required for
  sensitive engagements.
- **ChromaDB is optional and constrained.** Versions 0.4.17 and newer are in
  unpatched CVE-2026-45829, CVE-2026-45830, CVE-2026-45831, and
  CVE-2026-45833 ranges, so the lock is capped below 0.4.17 and the built-in
  hash-memory fallback remains the default. That safe cap supports Python
  3.10/3.11 only; Python 3.12 always uses the fallback. ULTRON disables Chroma
  telemetry and supplies its own local embeddings, preventing a runtime model
  download. Do not expose a Chroma Python API server to untrusted networks.
- **Local host compromise defeats process-level controls.** A process with
  sufficient access can inspect memory or `/proc`, alter dependencies, or
  tamper with scope configuration. Host hardening is an operator control.

The expanded abuse-case analysis, assets, assumptions, and data-flow diagram
are in [THREAT_MODEL.md](THREAT_MODEL.md).

### Out of scope for this threat model

- Vulnerabilities in the target systems themselves (that is what ULTRON is
  for) and the legality of a given engagement (the operator's responsibility).
- Compromise of the host running ULTRON or of the operator's cloud/API
  credentials outside the mechanisms above.

## Automated security scanning

Every push and pull request runs static and dependency security scans in CI
(`.github/workflows/ci.yml`):

- **bandit** — static analysis of `ultron-v6/ultron`; no test ID is skipped
  globally (the two intentional `subprocess` boundaries carry narrow,
  reviewed inline suppressions).
- **pip-audit --strict** — known-vulnerability audits of build, core runtime,
  development, Chroma, and cross-version-integration lockfiles. Every resolved
  distribution is also hash-pinned.
- **pip check** — verifies core/dev installs plus all optional integrations on
  the oldest and newest supported Python versions.
- **CycloneDX SBOMs** — CI emits the cross-version and constrained-Chroma
  production graphs as downloadable build artifacts.
- **lockfile drift check** — recompiles every lock from root `pyproject.toml`,
  byte-compares root/package mirrors, and fails on drift.

GitHub Actions are pinned to immutable commit SHAs. Dependency freshness is
tracked weekly by Dependabot (`.github/dependabot.yml`).
