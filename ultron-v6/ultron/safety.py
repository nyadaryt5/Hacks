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

#: Hostnames taken from URL schemes (http/https/ftp/ssh).
_URL_HOSTS = re.compile(r"(?:https?|ftp|ssh)://([A-Za-z0-9][A-Za-z0-9.-]*)")

#: Bare FQDNs (at least two dots) used as bare arguments, e.g. ``nmap host``.
_FQDNS = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9][A-Za-z0-9-]*){2,})\b"
)


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
        try:
            ip = ipaddress.ip_address(target.split(":", maxsplit=1)[0])
            return any(
                ip in net for net in self.allowed_networks
            ) or target in self.allowed_targets
        except ValueError:
            return any(
                target == allowed or target.endswith("." + allowed)
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
        targets = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", cmd)
        for target in targets:
            if not self.validate_scope(target):
                return False, f"BLOCKED: {target} out of scope"
        for host in _URL_HOSTS.findall(cmd):
            if not self.validate_scope(host):
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
