"""Regressions for P-T-17's sealed-input derivation and P-T-19's bootstrap order."""
import copy
import json
import shutil

import pytest

from aeread_families.procurement_allocation import pay_or_test_reanalysis as r


@pytest.fixture(scope="module")
def rows():
    return [json.loads(line) for line in (r.OUT / "tables/actions.jsonl").read_text().splitlines()]


def test_original_table_reproduces_including_intervals(rows):
    result = r.derive(rows)["panels"]
    expected = {"sol61": (1.0, 0.2, 2.1, 99.8), "opus55": (5.4, 1.2, 10.6, 98.8),
                "gemini38_flash": (75.2, 48.7, 101.4, 83.3), "gpt6_luna": (74.4, 46.7, 102.7, 83.5),
                "sol61_accounting": (12.2, 4.3, 23.6, 97.3), "opus55_accounting": (19.4, 6.0, 38.2, 95.7)}
    for panel, (mean, low, high, share) in expected.items():
        assert result[panel]["worlds"] == 24
        assert result[panel]["decision_loss_usd"] == {"mean": mean, "low": low, "high": high}
        assert result[panel]["best_policy_share_percent"] == share


def test_jsonl_order_does_not_change_seeded_intervals(rows):
    assert r.derive(rows) == r.derive(list(reversed(rows)))


def test_missing_or_duplicate_world_is_not_silently_dropped(rows):
    with pytest.raises(ValueError, match="incomplete or duplicate"):
        r.derive(rows[1:])
    with pytest.raises(ValueError, match="incomplete or duplicate"):
        r.derive([*rows, rows[0]])


def test_changed_action_cannot_keep_the_original_margin_and_loss(rows):
    changed = copy.deepcopy(rows)
    row = next(x for x in changed if x["panel"] == "sol61" and x["termination_reason"] == "submitted")
    row["action_trace"] = [{"action": "defer", "ordinal": 1, "status": "succeeded"}]
    with pytest.raises(ValueError, match="projected margin|projected headline"):
        r.derive(changed)


def test_manifest_rejects_tampered_projection(tmp_path):
    copy_root = tmp_path / "bundle"
    shutil.copytree(r.OUT, copy_root)
    r.verify_manifest(copy_root)
    path = copy_root / "tables/actions.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="artifact digest"):
        r.verify_manifest(copy_root)


def test_changed_reference_is_rejected_before_recomputation(monkeypatch):
    pins = r.source_pins()
    pins["src/aeread_families/procurement_allocation/pay_or_test_reference.py"] = "0" * 64
    monkeypatch.setattr(r, "source_pins", lambda: pins)
    with pytest.raises(ValueError, match="source pins changed"):
        r.main(["--check"])


def _events(tmp_path, *, parsed_ok=True, success=True, duplicate=False):
    action = {"action": "request_quote", "supplier_id": "supplier_1", "message": "private message"}
    events = []
    payloads = [
        ("logical_action_started", {"request": {"seat_id": "buyer"}}),
        ("action_parsed", {"parse_result": {"ok": parsed_ok, "action": action if parsed_ok else None}}),
        ("logical_action_succeeded" if success else "logical_action_failed", {"valid": success}),
        ("family_outcome_recorded", {"outcome": {"action_count": 1}}),
    ]
    for i, (kind, payload) in enumerate(payloads):
        name = f"payload-{i}.json"
        (tmp_path / name).write_text(json.dumps(payload))
        events.append({"logical_action_id": "act1", "event_type": kind, "payload_ref": name})
    if duplicate:
        events.insert(2, events[1])
    path = tmp_path / "events.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


def test_action_projection_removes_text_and_retains_invalid_status(tmp_path):
    events = _events(tmp_path, parsed_ok=False, success=False)
    actions, _ = r.project_actions(events)
    assert actions == [{"ordinal": 1, "action": "unparseable", "parse_ok": False,
                        "status": "agent_action_failure"}]


def test_valid_projection_drops_message(tmp_path):
    actions, _ = r.project_actions(_events(tmp_path))
    assert "message" not in actions[0]
    assert actions[0]["supplier_id"] == "supplier_1"


def test_duplicate_parse_is_not_overwritten(tmp_path):
    with pytest.raises(ValueError, match="duplicate parse"):
        r.project_actions(_events(tmp_path, duplicate=True))
