"""Documentation contract for the native procurement RFQ case."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "procurement_rfq_case.md"


def test_procurement_rfq_case_document_freezes_scope_and_claim_boundaries() -> None:
    text = DOC.read_text()
    required = (
        "Provider-free MVP",
        "RFQ → quote → negotiate → counter → approval → award",
        "private unit cost",
        "target-price disclosure",
        "buyer surplus",
        "full-information terms relaxation",
        "not a paper result",
        "procurement world",
    )
    for phrase in required:
        assert phrase in text
