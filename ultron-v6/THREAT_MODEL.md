# ULTRON v6 Threat Model

**Status:** maintained
**Last reviewed:** 2026-08-26
**Applies to:** ULTRON 6.2.x

This document models the risks created when an LLM plans commands, an
orchestrator executes them, and target-controlled output returns to the LLM.
It complements the vulnerability-reporting policy in [SECURITY.md](SECURITY.md)
and the component design in [docs/architecture.md](../docs/architecture.md).

## 1. Security objectives

ULTRON should:

1. execute commands only for an operator-authorized target or network;
2. prevent model output and target content from directly reaching a shell;
3. keep Gemini, cloud, Vault, database, and telemetry credentials out of
   source control, logs, reports, traces, and child-tool environments;
4. stop predictably when scope, secret resolution, configuration, or budget
   checks fail;
5. preserve enough structured events and findings for an operator to review
   what happened without recording secret values; and
6. remain installable from auditable, pinned dependency sets.

These are defence-in-depth objectives, not a claim that arbitrary autonomous
command execution can be made risk-free.

## 2. Assets

| Asset | Why it matters | Primary controls |
|---|---|---|
| Written authorization and scope | Crossing it creates legal and operational harm | `SafetyJail`, `ScopeManager`, depth limits, operator approval |
| Gemini API keys and quotas | Keys permit billable model use | secret-manager backends, log exclusion, child-env scrubbing, budget limits |
| AWS/Vault/GCP identity | May read production secrets | SDK default chains, least privilege, no persistence, child-env scrubbing |
| Target data and scan output | May be sensitive and attacker-controlled | local DB/report boundaries, output truncation, isolated execution |
| Findings database and report | Contains engagement intelligence | local file permissions and host isolation (operator responsibility) |
| Coordinator integrity | A compromise can bypass every in-process guard | pinned dependencies, CI audits, unprivileged/containerized runtime |
| Budget and rate limits | Bound wallet and availability impact | pre-request checks, RPM/RPD/session ceilings, max iterations |

## 3. Actors and capabilities

- **Authorized operator:** chooses the initial target, budgets, secret source,
  and deployment boundary. The operator is trusted to possess written
  authorization but can make configuration mistakes.
- **Target-controlled adversary:** controls banners, HTTP content, DNS answers,
  services, and tool output returned from an assessed target. It can attempt
  prompt injection and parser confusion.
- **Untrusted LLM:** may hallucinate, follow injected instructions, produce
  malformed data, or propose destructive/out-of-scope commands. Its output is
  never an authorization decision.
- **Dependency or tool attacker:** may compromise a Python dependency or a
  locally installed pentest binary. Child tools are outside the trusted
  coordinator process.
- **Local host attacker:** can inspect process memory, environment, files, or
  `/proc`. A sufficiently privileged local attacker is outside the protection
  offered by ULTRON's process-level controls.

## 4. Assumptions and non-assumptions

### Required assumptions

- The operator supplied the exact approved target/network and runs ULTRON only
  for an authorized engagement.
- The Python interpreter, operating system, container runtime, and installed
  pentest binaries are initially trustworthy.
- Cloud/Vault workload identities are least-privileged and provider TLS
  validation is enabled.
- Provider-side spend/quota controls and network monitoring exist outside the
  application.

### Explicit non-assumptions

- LLM output is not trusted, even when it conforms to the requested JSON.
- Target output is not trusted, even when produced by a familiar tool.
- A denylist is not assumed to enumerate every harmful executable or argument.
- DNS is not assumed stable between validation and command execution.
- The local SQLite database and markdown reports are not encrypted by ULTRON.
- Optional telemetry and vector stores are not assumed available or trusted.

## 5. Trust boundaries and data flow

```text
                                  UNTRUSTED
                         +------------------------+
 target network -------->| banners / tool output |---+
                         +------------------------+   |
                                                      v
+----------------+   scope/budgets   +------------------------+
| trusted        |------------------>| Coordinator / FSM      |
| operator       |                   | typed configuration    |
+----------------+                   +-----------+------------+
                                                |
                    sanitized prompt/context    | model output
                         +-----------------------+-------------------+
                         v                                           |
                 +---------------+                                   |
                 | Gemini API    |  UNTRUSTED MODEL                  |
                 +---------------+                                   v
                                                        +---------------------+
                                                        | parse + debate      |
                                                        | SafetyJail + scope  |
                                                        +----------+----------+
                                                                   |
                                                    approved argv, shell=False
                                                                   v
                                                        +---------------------+
                                                        | child pentest tool  |
                                                        | sanitized env       |
                                                        +----------+----------+
                                                                   |
                                                                   v
                                                          authorized target

 Secret boundary (trusted configuration):
 AWS Secrets Manager / Vault / GCP --> resolver --> process-only key
                                              X--> logs, DB, reports, child env
```

The critical boundary is between LLM/target-controlled bytes and
`subprocess.run`. The model can propose an action, but parsing, debate, scope,
and jail checks execute in trusted application code first. The executor uses
`shlex.split`, `shell=False`, a temporary working directory, a timeout, and a
credential-scrubbed environment.

## 6. Threat analysis

The table combines STRIDE-style threats with LLM-specific abuse cases.
Likelihood and impact are qualitative and assume an isolated, unprivileged
runtime. Deploying on a privileged host increases both.

| ID | Threat / abuse case | Likelihood | Impact | Existing prevention/detection | Residual risk |
|---|---|---:|---:|---|---|
| T1 | Prompt injection in a target banner steers planning | High | High | fixed authorization context; structured parsing; every action passes debate/scope/jail checks | A harmful command may still be syntactically allowed |
| T2 | Model proposes an unauthorized IPv4/IPv6/domain/URL target | Medium | High | literal and hostname extraction; `validate_scope`; lateral target approval queue | encoded host forms and DNS rebinding can create parser/TOCTOU gaps |
| T3 | Model uses shell chaining, redirection, interpolation, or a reverse shell | Medium | Critical | shell metacharacters rejected; destructive patterns denied; `shell=False` | a non-shell binary can still perform destructive work |
| T4 | Child tool reads Gemini or cloud credentials | Medium | High | `_tool_environment` removes model, Vault, AWS, GCP credential-path, and Sentry variables | same-user tools may inspect process memory or predictable credential files |
| T5 | Secret backend fails and stale env key is used | Medium | High | manager modes are authoritative and fail-closed; errors become `ConfigurationError` | `env` mode intentionally trusts process environment |
| T6 | API key leaks through observability or reports | Low | High | keys are not added to spans/findings/reports; output is bounded; child env scrubbed | a provider or compromised dependency sees values in process memory |
| T7 | Runaway loop or retry drains quota | Medium | Medium/High | max iterations, session token ceiling, RPM/RPD, bounded retries, 429 rotation | local USD estimate is not an authoritative billing cap |
| T8 | Malicious dependency compromises coordinator | Low/Medium | Critical | exact locks; strict pip-audit for all dependency sets; Dependabot; Bandit; immutable CI action SHAs | audits detect known issues only; lockfiles do not prevent a compromised index artifact |
| T9 | Vulnerable Chroma server is exposed | Medium if enabled | Critical | optional Python 3.10/3.11 backend; `<0.4.17` cap outside four current advisory ranges; telemetry disabled; local embeddings; hash fallback elsewhere | older code has maintenance risk; never expose Chroma's Python API publicly |
| T10 | Findings/report disclose sensitive target data | Medium | Medium/High | local-only default storage; ignored DB/report artifacts; output truncation | no built-in encryption or field-level redaction |
| T11 | Forged health/metrics data masks failure | Low | Low/Medium | separate liveness/readiness semantics; injectable readiness check | endpoints have no built-in authentication; bind locally or protect upstream |
| T12 | Scope/database state is tampered with locally | Low | High | typed transitions and explicit approval APIs | local filesystem/process compromise is out of process-level scope |

## 7. Secret lifecycle and failure behavior

### Environment mode

`ULTRON_SECRETS_BACKEND=env` (the local default) reads `GOOGLE_API_KEY`, then
`GOOGLE_API_KEY_1`; numbered keys through 10 are loaded for rotation. Missing
keys cause scan startup to fail. The offline `serve` command does not resolve a
Gemini key merely to expose liveness and metrics.

### Managed mode

1. `ULTRON_SECRETS_BACKEND` selects exactly one of `aws`, `vault`, or `gcp`.
2. Required identifiers are read from non-secret configuration variables.
3. The SDK authenticates using its normal workload identity/credential chain.
4. The returned raw value or JSON `GOOGLE_API_KEY` field becomes the
   process-local key used by pydantic settings and the LLM client.
5. The key is not persisted. Before launching a child tool, the coordinator
   builds a new environment without model/cloud/Vault/telemetry credentials.

The following all stop scan startup and never trigger env fallback:

- unknown backend names;
- missing provider SDKs;
- missing secret id/path/resource, Vault address, or Vault token;
- provider authentication, authorization, transport, or lookup errors; and
- empty or malformed provider payloads that contain no key.

Operators should revoke a suspected key at the provider, rotate every backing
secret, inspect provider usage/audit logs, and treat reports and the findings
DB from that run as potentially exposed.

## 8. Dependency and build boundary

Root `pyproject.toml` is the packaging and direct-dependency source of truth.
`requirements-build.lock`, `requirements.lock`, `requirements-dev.lock`,
`requirements-chroma.lock`, and `requirements-all.lock` pin resolved sets and
are mirrored as regular files at repository root. Python 3.11 is the fixed
marker-resolution baseline; `scripts/lockfiles.py --check` rejects another
interpreter and then recompiles candidates and byte-compares both locations.
CI fails on drift. CI also runs `pip check`,
Bandit without global skips, strict mypy, lint, tests with an 85% coverage
floor, strict pip-audit over every lock, and a package build.

Every resolved artifact is hash-pinned, reducing accidental drift, index
substitution, and known-vulnerability exposure. Hashes do not provide publisher
identity, signatures, or end-to-end provenance. High-assurance deployments
should install from an authenticated internal index, verify attestations, and
scan the built image in their own supply-chain controls.

## 9. Deployment requirements

For anything beyond local experimentation:

- use a dedicated unprivileged account in an ephemeral container or VM;
- do not mount the Docker socket, SSH agent, home directory, or cloud
  credential directories;
- use a read-only root filesystem plus dedicated writable DB/report paths;
- restrict egress to the authorized target range, Gemini endpoint, and chosen
  secret provider using controls outside ULTRON;
- bind health/metrics to loopback or protect them with an authenticated proxy;
- set provider-side spend limits and short-lived, least-privilege identities;
- retain network and provider audit logs outside the runtime; and
- require human review for destructive/high-impact actions.

## 10. Verification map

| Control | Implementation | Regression evidence |
|---|---|---|
| Managed-secret resolution and fail-closed behavior | `ultron/secrets.py`, `ultron/config.py` | `tests/test_secrets.py`, `tests/test_config.py` |
| Child credential scrubbing | `ultron/coordinator.py::_tool_environment` | `tests/test_coordinator.py::test_execute_tool_does_not_inherit_operator_secrets` |
| Scope and command filtering | `ultron/safety.py`, `ultron/scope.py` | `tests/test_safety.py`, `tests/test_scope.py` |
| Budget/rate limits | `ultron/budget.py`, `ultron/llm.py` | `tests/test_budget.py`, `tests/test_llm.py` |
| Bounded agent loop | `ultron/coordinator.py`, `ultron/fsm.py` | `tests/test_coordinator.py`, `tests/test_fsm.py` |
| Dependency drift/audit | `scripts/lockfiles.py`, `.github/workflows/ci.yml` | `make lockfile-check`, CI security jobs |
| Structured logs without required telemetry | `ultron/logging_setup.py`, `ultron/errors.py` | `tests/test_logging.py`, `tests/test_errors.py` |

## 11. Review triggers

Review this model whenever a release changes command execution, scope parsing,
LLM/provider inputs, secret handling, persistence, network services, optional
backends, or deployment privileges. Also review it after any jail bypass,
credential leak, dependency advisory, authorization incident, or new model/tool
integration.
