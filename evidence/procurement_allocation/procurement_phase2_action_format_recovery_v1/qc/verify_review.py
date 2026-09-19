"""Verify the Phase 2 offline review bundle; never dispatch a provider call."""

from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

from aeread_families.procurement_allocation.phase2_admission import (
    contract,
    digest,
    source_pins,
)
from aeread_families.procurement_allocation.phase2_campaign import (
    offline_screen,
    execution_contract,
)
from aeread_families.procurement_allocation.phase2_worlds import build_world, CASE_ROOT


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "review_manifest.json").read_text())
    for path, expected in manifest["artifacts"].items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected, path
    conformance = json.loads((root / "provider_free_conformance.json").read_text())
    assert conformance["passed"] and conformance["implementation_pins"] == source_pins()
    for name, expected in conformance["pytest_results"].items():
        suites = ET.parse(root / f"{name}_pytest.xml").getroot().findall("testsuite")
        actual = {
            k: sum(int(s.attrib.get(k, 0)) for s in suites)
            for k in ("tests", "errors", "failures", "skipped")
        }
        assert actual == expected and actual["errors"] == actual["failures"] == 0
    screen = json.loads((root / "offline_screen.json").read_text())
    assert screen == offline_screen()
    cases = [build_world(i) for i in range(8)]
    for i, c in enumerate(cases):
        assert c == json.loads((CASE_ROOT / f"world_{i+1:02d}.json").read_text())
    core = contract(root)
    assert core == json.loads((root / "contribution_contract.json").read_text())
    assert digest(core) == manifest["contribution_sha256"]
    assert execution_contract(cases, screen) == json.loads(
        (root / "execution_contract.json").read_text()
    )
    print(
        json.dumps(
            {
                "status": "verified",
                "artifacts": len(manifest["artifacts"]),
                "worlds": 8,
                "offline_reference_episodes": 192,
                "live_calls": 0,
                "contribution_sha256": digest(core),
                "human_approval_record_present": (
                    root / "human_qc_approval.json"
                ).exists(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
