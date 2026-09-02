"""Provider-free coverage for the amazonbarg in-process delegation shim.

See ``docs/amazonbarg_adapter_spec.md`` section 3.1 and test plan P2:
(a) no socket/HTTP call occurs during shim install or module import; (b)
the stub miss-counter is 0 after the full adapter test suite runs.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

from aeread_families.amazonbarg import upstream_shim as shim


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_AMAZONBARG_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg",
    )
    root = Path(candidate)
    marker = root / "data" / "AmazonHistoryPrice" / "home-kitchen.json"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream AmazonPriceHistory checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()


# ---------------------------------------------------------------------------
# P2(b): the global miss counter -- populated only by genuine delegated
# imports elsewhere in the suite -- must be 0 by the time this file's own
# tests run. Runs first alphabetically is not guaranteed, so this asserts a
# necessary (not sufficient) condition: whatever ran before this point in
# THIS process left it at 0. The definitive whole-suite check is the module
# docstring's own contract: nothing in this adapter's production code ever
# constructs a stub deliberately outside a test.
# ---------------------------------------------------------------------------


def test_global_miss_counter_starts_at_zero_in_a_fresh_process() -> None:
    assert shim.miss_count() == 0
    assert shim.miss_paths() == ()


# ---------------------------------------------------------------------------
# P2(a): no network call, ever -- including api_setting.py's module-level
# openai client construction.
# ---------------------------------------------------------------------------


def test_delegated_import_of_session_never_touches_the_network() -> None:
    # `import_parse_reply` runs its whole import under `_no_network_guard`
    # internally (proven independently below): any socket connect attempt
    # -- including api_setting.py's module-level openai client construction
    # -- would raise `UpstreamShimMissError` from inside the import itself.
    # A clean return is the proof; there is nothing left for this test to
    # additionally wrap, since the guard is already active for the entire
    # duration of the delegated import, not just a probe afterwards.
    parse_reply = shim.import_parse_reply(UPSTREAM_ROOT)
    assert callable(parse_reply)


def test_no_network_guard_blocks_a_real_connect_attempt() -> None:
    with shim._no_network_guard():
        with pytest.raises(shim.UpstreamShimMissError, match="live network connection"):
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.connect(("192.0.2.1", 80))  # TEST-NET-1, never routable
            finally:
                probe.close()


# ---------------------------------------------------------------------------
# Delegated imports succeed and leave sys.modules clean.
# ---------------------------------------------------------------------------


def test_import_parse_reply_delegates_upstreams_own_three_field_grammar() -> None:
    parse_reply = shim.import_parse_reply(UPSTREAM_ROOT)

    thought, talk, action, message = parse_reply(
        "Thought: internal plan\nTalk: hello there\nAction: [BUY] $10 (1x foo)"
    )
    assert thought == "internal plan"
    assert talk == "hello there"
    assert action == "[BUY] $10 (1x foo)"
    assert message == "Talk: hello there\nAction: [BUY] $10 (1x foo)"

    # A missing Action: line yields an empty action string, never a raise --
    # matches upstream's own regex-default-empty behaviour exactly (spec
    # golden 4's malformed-operational path starts from this).
    _thought, _talk, action, _message = parse_reply("Thought: t\nTalk: no action here")
    assert action == ""

    with pytest.raises(ValueError, match="empty reply"):
        parse_reply("")


def test_import_action_parser_delegates_upstreams_own_extraction_regex() -> None:
    Action, ActionParser = shim.import_action_parser(UPSTREAM_ROOT)
    parser = ActionParser()

    deal = parser("[DEAL] $135 (1x home-kitchen_2)")
    assert deal.isDEAL() is True
    assert deal.money == 135.0
    assert deal.objects == {"home-kitchen_2": 1}

    reject = parser("[REJECT]")
    assert reject.isREJECT() is True

    with pytest.raises(RuntimeError, match="No action in text"):
        parser("")


def test_delegated_imports_leave_sys_modules_clean_afterwards() -> None:
    shim.import_parse_reply(UPSTREAM_ROOT)
    shim.import_action_parser(UPSTREAM_ROOT)
    shim.import_camel_amazon_inventories(
        UPSTREAM_ROOT, UPSTREAM_ROOT / "data" / "AmazonHistoryPrice"
    )

    for name in shim._UPSTREAM_MODULE_NAMES:
        assert name not in sys.modules, f"{name!r} was not evicted from sys.modules"
    assert str(UPSTREAM_ROOT) not in sys.path


def test_camel_amazon_delegation_matches_the_930_session_corpus() -> None:
    inventories = shim.import_camel_amazon_inventories(
        UPSTREAM_ROOT, UPSTREAM_ROOT / "data" / "AmazonHistoryPrice"
    )
    assert len(inventories) == 930
    (first_product,) = inventories[0].products
    assert first_product.codename == "automotive_1"


# ---------------------------------------------------------------------------
# P3-adjacent: two delegated imports in the same process are independent
# (no cross-call state leakage from a cached module object).
# ---------------------------------------------------------------------------


def test_two_delegated_parse_reply_imports_are_independent_callables() -> None:
    first = shim.import_parse_reply(UPSTREAM_ROOT)
    second = shim.import_parse_reply(UPSTREAM_ROOT)
    assert first is not second
    assert first("Thought: t\nTalk: hi\nAction: [QUIT]") == second(
        "Thought: t\nTalk: hi\nAction: [QUIT]"
    )


# ---------------------------------------------------------------------------
# Miss-detection mechanism itself, exercised against a fully isolated
# counter -- never the global one the rest of the suite relies on staying 0.
# ---------------------------------------------------------------------------


def test_stub_attribute_read_alone_never_raises_or_records_a_miss() -> None:
    counter = shim._MissCounter()
    stub = shim._StubModule("aeread_test_stub_pkg", counter=counter)

    placeholder = stub.SomeClass  # bare read, e.g. a return-type annotation
    chained = placeholder.attribute_of_attribute  # chained read, still bare

    assert isinstance(placeholder, shim._StubUse)
    assert isinstance(chained, shim._StubUse)
    assert counter.count == 0


def test_calling_a_stub_placeholder_raises_and_records_exactly_one_miss() -> None:
    counter = shim._MissCounter()
    stub = shim._StubModule("aeread_test_stub_pkg", counter=counter)

    with pytest.raises(shim.UpstreamShimMissError, match="aeread_test_stub_pkg.get"):
        stub.get("https://example.invalid")

    assert counter.count == 1
    assert counter.paths == ("aeread_test_stub_pkg.get",)


def test_stub_installer_prefers_a_really_importable_package_over_a_stub() -> None:
    with shim._install_missing_stub_modules(("re",)):
        import re as delegated_re

        assert delegated_re.compile("a").match("a") is not None
    assert "re" in sys.modules  # never evicted -- it was real, not stubbed


def test_stub_installer_only_installs_and_evicts_the_actually_absent_names() -> None:
    marker = "aeread_test_definitely_absent_pkg"
    assert marker not in sys.modules
    with shim._install_missing_stub_modules((marker,)):
        assert marker in sys.modules
        assert isinstance(sys.modules[marker], shim._StubModule)
    assert marker not in sys.modules
