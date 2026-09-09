"""Unit tests for the shared RFC 6901 JSON Pointer module (issue #122).

Ruling R9/R10 (kernel_scoring_contract_spec.md): trajectory_outcome_paths'
JSON Pointer projection previously lived only in test helpers
(tests/test_shared_runner_scoring_contract.py). This module is the one
production tokenizer/navigator that schemas.py format validation and
evaluation.py's replay-time R10 check both consume.
"""

from __future__ import annotations

import pytest

from aeread.shared_runner.run.json_pointer import JsonPointerError, drop, get, parse


def test_parse_decodes_tilde_one_as_a_literal_slash() -> None:
    assert parse("/a~1b") == ("a/b",)


def test_parse_decodes_tilde_zero_as_a_literal_tilde() -> None:
    assert parse("/a~0b") == ("a~b",)


def test_parse_returns_one_segment_per_slash() -> None:
    assert parse("/a/b/c") == ("a", "b", "c")


def test_parse_rejects_the_empty_string() -> None:
    with pytest.raises(JsonPointerError):
        parse("")


def test_parse_rejects_the_root_pointer() -> None:
    with pytest.raises(JsonPointerError):
        parse("/")


def test_parse_rejects_a_pointer_without_a_leading_slash() -> None:
    with pytest.raises(JsonPointerError):
        parse("history")


def test_parse_rejects_a_doubled_slash() -> None:
    with pytest.raises(JsonPointerError):
        parse("//history")


def test_parse_rejects_a_trailing_slash() -> None:
    with pytest.raises(JsonPointerError):
        parse("/history/")


def test_parse_rejects_a_dangling_tilde_at_the_end_of_a_segment() -> None:
    """RFC 6901: every '~' must be followed by exactly '0' or '1'. A '~'
    with nothing after it is not a valid escape (Codex review R1 finding 4)."""
    with pytest.raises(JsonPointerError):
        parse("/a~")


def test_parse_rejects_an_unrecognized_escape() -> None:
    """'~2' is not '~0' or '~1' -- not a valid RFC 6901 escape."""
    with pytest.raises(JsonPointerError):
        parse("/a~2b")


def test_get_navigates_nested_objects() -> None:
    assert get({"a": {"b": 1}}, "/a/b") == 1


def test_get_raises_on_a_missing_segment() -> None:
    with pytest.raises(JsonPointerError):
        get({"a": {}}, "/a/b")


def test_get_raises_when_an_intermediate_value_is_a_list() -> None:
    with pytest.raises(JsonPointerError):
        get({"a": [1, 2]}, "/a/0")


def test_get_raises_when_the_document_itself_is_not_a_mapping() -> None:
    with pytest.raises(JsonPointerError):
        get([1, 2], "/0")


def test_get_decodes_escaped_segments_during_navigation() -> None:
    assert get({"a/b": 1}, "/a~1b") == 1


def test_drop_removes_a_top_level_field() -> None:
    assert drop({"a": 1, "b": 2}, "/a") == {"b": 2}


def test_drop_removes_a_nested_field_without_disturbing_siblings() -> None:
    assert drop({"a": {"b": 1, "c": 2}, "d": 3}, "/a/b") == {
        "a": {"c": 2},
        "d": 3,
    }


def test_drop_raises_on_a_missing_segment() -> None:
    with pytest.raises(JsonPointerError):
        drop({"a": 1}, "/b")


def test_drop_raises_when_an_intermediate_value_is_a_list() -> None:
    with pytest.raises(JsonPointerError):
        drop({"a": [1, 2]}, "/a/0")
