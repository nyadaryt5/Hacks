"""Safety jail: scope validation and destructive-command filtering.

Commands are checked, in order, against:

1. a shell-metacharacter blocklist (the executor uses ``shell=False``, so
   anything that chains, redirects or interpolates is refused outright),
2. a denylist of destructive patterns,
3. scope validation of every IP literal, URL host and bare FQDN in the
   command — anything outside the authorized scope is blocked.

Note the conservative consequences: URL query strings containing ``&`` and
arguments with dotted extensions (``scan.report.txt``) are rejected; the
planner must URL-encode or rename such values.
"""

from __future__ import annotations

import ipaddress
import re
import shlex
from urllib.parse import urlsplit

FORBIDDEN_PATTERNS = [
    r"rm\s+-rf\s+/",
    r">\s*/etc/",
    r">\s*/var/",
    r">\s*/usr/",
    r"nc\s+-e\s+/bin/",
    r"mkfifo\s+/tmp/",
    r"bash\s+-i\s+>&\s*/dev/tcp/",
    r"python\s+-c\s+.*socket",
    r"perl\s+-e\s+.*socket",
    r"ruby\s+-rsocket",
]

#: Chaining / redirection / interpolation characters. Commands run with
#: ``shell=False``, so these can never do useful work — refuse them.
SHELL_METACHARACTERS = re.compile(r"[;|&`$<>\r\n]")

#: URLs whose hostname must be checked independently of paths and ports.
_URLS = re.compile(r"(?:https?|ftp|ssh)://[^\s]+", re.IGNORECASE)

#: Bare DNS names, including ordinary two-label names such as ``example.com``.
#: Requiring an alphabetic final label avoids treating version numbers as hosts.
_FQDNS = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9-]*"
    r"(?:\.[A-Za-z0-9][A-Za-z0-9-]*)*\.[A-Za-z]{2,63})\b"
)


def _token_ip_literals(cmd: str) -> set[str]:
    """Extract IPv4/IPv6 literals from shell-free command arguments."""
    literals: set[str] = set()
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return literals
    for token in tokens:
        candidate = token.rsplit("=", maxsplit=1)[-1].strip("'\"(),")
        if "://" in candidate:
            continue
        if candidate.startswith("[") and "]" in candidate:
            candidate = candidate[1 : candidate.index("]")]
        elif candidate.count(":") == 1:
            host, port = candidate.rsplit(":", maxsplit=1)
            if port.isdigit():
                candidate = host
        candidate = candidate.removesuffix("/32").removesuffix("/128")
        try:
            literals.add(str(ipaddress.ip_address(candidate)))
        except ValueError:
            continue
    return literals


class SafetyJail:
    """Validates that targets and commands stay inside the authorized scope."""

    def __init__(
        self,
        allowed_targets: set[str],
        allowed_networks: list[
            ipaddress.IPv4Network | ipaddress.IPv6Network
        ],
    ):
        self.allowed_targets = allowed_targets
        self.allowed_networks = allowed_networks

    def validate_scope(self, target: str) -> bool:
        if not target:
            return True
        host = target.strip().rstrip(".").lower()
        if host.startswith("[") and "]" in host:
            host = host[1 : host.index("]")]
        elif host.count(":") == 1:
            possible_host, port = host.rsplit(":", maxsplit=1)
            if port.isdigit():
                host = possible_host
        try:
            ip = ipaddress.ip_address(host)
            return any(ip in net for net in self.allowed_networks) or any(
                host == allowed.strip().lower()
                for allowed in self.allowed_targets
            )
        except ValueError:
            return any(
                host == allowed.strip().rstrip(".").lower()
                or host.endswith("." + allowed.strip().rstrip(".").lower())
                for allowed in self.allowed_targets
            )

    def filter_command(self, cmd: str) -> tuple[bool, str]:  # noqa: PLR0911 (ladder)
        if not cmd or not cmd.strip():
            return False, "BLOCKED: empty command"

        if SHELL_METACHARACTERS.search(cmd):
            return False, "BLOCKED: shell metacharacters are not allowed"

        for pattern in FORBIDDEN_PATTERNS:
            try:
                if re.search(pattern, cmd, re.IGNORECASE):
                    return False, f"BLOCKED: {pattern}"
            except re.error:
                continue
        targets = set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", cmd))
        targets.update(_token_ip_literals(cmd))
        for target in sorted(targets):
            if not self.validate_scope(target):
                return False, f"BLOCKED: {target} out of scope"
        for raw_url in _URLS.findall(cmd):
            host = urlsplit(raw_url).hostname
            if host and not self.validate_scope(host):
                return False, f"BLOCKED: {host} out of scope"
        for host in _FQDNS.findall(cmd):
            if not self.validate_scope(host):
                return False, f"BLOCKED: {host} out of scope"
        return True, "OK"


__all__ = [
    "FORBIDDEN_PATTERNS",
    "SafetyJail",
    "SHELL_METACHARACTERS",
]
