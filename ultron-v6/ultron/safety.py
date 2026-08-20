"""Safety jail: scope validation and destructive-command filtering.

Commands are checked against a denylist of destructive patterns and every
IP literal in a command must fall inside the authorized scope before
execution is allowed.
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

    def filter_command(self, cmd: str) -> tuple[bool, str]:
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
        return True, "OK"


__all__ = ["FORBIDDEN_PATTERNS", "SafetyJail"]
