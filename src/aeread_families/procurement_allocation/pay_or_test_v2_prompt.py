"""The buyer's prompt for pay or test version 2: brief v2 and one more stated fact, the shared source.

``pay_or_test_prompt.PAY_OR_TEST_PROMPT_V2`` states how the order is counted,
what a quote and a sample show, that a quote is final and that the buyer is
judged on its average margin. The version 2 pack adds one thing the buyer
cannot work out from the listings: new listings of one seller kind may share a
source, and when they do they are all of one type. This prompt is that brief
with the shared source stated in the same plain terms, and nothing about whom
to test or in what order. ``tests/test_procurement_pay_or_test_v2.py`` checks the
statement against the generator's draws and every other stated rule against the
environment.
"""

from __future__ import annotations

from .pay_or_test_prompt import PAY_OR_TEST_PROMPT_V2

PROMPT_ID = "procurement_allocation_pay_or_test_shared_source_v1"
TREATMENT_ID = "brief_v2_plus_shared_source_v1"

_SHARED_SOURCE = """- New listings of the same seller_kind may buy from one source. The chance that all the
  new listings of one kind in this search share a source is
  policy.newcomer_sourcing.same_source_probability. If they share one, they are all the
  same: all sound, all unreliable on delivery, or all failing inspection, with the shares
  in their cohort_record. If not, each is sound, unreliable or failing on its own, with
  those shares. New listings of different kinds never share a source, and a listing with a
  marketplace_record is not part of any.
"""
_RETURN = "\nReturn only the next JSON action.\n"
assert PAY_OR_TEST_PROMPT_V2.count(_RETURN) == 1 and PAY_OR_TEST_PROMPT_V2.endswith(_RETURN)
PAY_OR_TEST_V2_PROMPT = PAY_OR_TEST_PROMPT_V2.replace(_RETURN, _SHARED_SOURCE + _RETURN)

__all__ = ["PAY_OR_TEST_V2_PROMPT", "PROMPT_ID", "TREATMENT_ID"]
