"""Tests for ultron.json_utils — LLM output tolerance."""

import pytest

from ultron.json_utils import parse_json_response


def test_plain_json_object():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_json_with_whitespace():
    assert parse_json_response('  {"a": [1, 2, 3]}  ') == {"a": [1, 2, 3]}


def test_json_array():
    assert parse_json_response("[1, 2, 3]") == [1, 2, 3]


def test_json_fenced_block():
    response = 'Sure! Here you go:\n```json\n{"verdict": "proceed"}\n```'
    assert parse_json_response(response) == {"verdict": "proceed"}


def test_generic_fenced_block():
    response = '```\n{"x": true}\n```'
    assert parse_json_response(response) == {"x": True}


def test_json_embedded_in_prose():
    response = 'The analysis says {"success": true} and nothing else.'
    assert parse_json_response(response) == {"success": True}


def test_empty_response_is_none():
    assert parse_json_response("") is None
    assert parse_json_response("   ") is None


def test_error_and_budget_prefixes_are_none():
    assert parse_json_response("[ERROR] API failed: timeout") is None
    assert parse_json_response("[BUDGET] Rate limit reached") is None


def test_non_json_text_is_none():
    assert parse_json_response("just some words") is None


@pytest.mark.parametrize("bad", ["{invalid json", "[1, 2", "{} extra}"])
def test_malformed_json_is_none(bad):
    assert parse_json_response(bad) is None
