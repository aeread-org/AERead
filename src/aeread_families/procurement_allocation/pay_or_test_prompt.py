"""The buyer's prompt for the pay-or-test pack: how the order is counted, what a request shows, no procedure.

The pack scores a buyer by the dollars each action gives up against the best
action available with what the buyer knew. That is only a measure of judgment
if the buyer knows the rules the dollars follow, so this prompt states them:
how kits are counted, what a void award is worth, when a delivery is too late,
and what a quote and a sample each show. It says nothing about whom to test,
in what order, or when to stop. ``tests/test_procurement_pay_or_test.py``
checks each stated rule against the environment.
"""

from __future__ import annotations

PROMPT_ID = "procurement_allocation_pay_or_test_neutral_v1"
TREATMENT_ID = "order_accounting_and_request_facts_no_procedure_v1"

PAY_OR_TEST_PROMPT = """You are the EasyCircuit procurement buyer. Work through the supplied
interactive sourcing episode and return exactly one JSON action on every turn.

Marketplace listings and verbal supplier claims are provisional. A final award is
eligible only when each referenced supplier has an unexpired formal offer, a verified
sample, and the exact required variant. Information requests, quotes, counters, and
samples consume action, time, and monetary budgets.

Allowed actions:
- inquire: supplier_id, fields, message
- request_quote: supplier_id, message
- counter_offer: supplier_id, offer_id, proposal, message
- request_sample: supplier_id, message
- submit_award: award_lines containing offer_id and quantity
- defer: reason

Your objective is buyer contribution margin from completed on-time kits after landed
cost, quality loss, return recovery, financing, information cost, and shortfall
penalties. A displayed listing price or a verbal statement is not a binding offer, and
a counter_offer is valid only against a formal offer you hold.

How this order is counted:
- You have committed to supply objective.target_kits. Completed kits are the good units
  you can expect on time from what you order: quantity times the supplier's yield times
  its on-time rate, rounded down, and never more than the target. Each kit short of the
  target costs objective.shortfall_penalty_per_kit_usd.
- An award that completes fewer than objective.minimum_service_kits is void. A void
  award, walking away with defer, and running out of actions all count as supplying
  nothing, which is worth objective.defer_value_usd. What you spent on information is
  lost either way.
- Every request adds days to elapsed_days. An award line delivers only if elapsed_days
  at the moment you award plus that offer's lead_time_days is no more than
  objective.deadline_days.

What each request costs and shows:
- A formal quote costs policy.process.quote_fee_usd and takes policy.process.quote_days.
  It states the supplier's binding price, order sizes and lead time, and its on-time rate.
- A sample costs the sample_fee_usd and takes the sample_days on the listing. It states
  the supplier's yield.
- actions_left counts every action you take, the award included. Each supplier named in
  an award needs its own formal quote and its own verified sample before the award.

Facts about this marketplace:
- A listing may carry a marketplace_record: what earlier buyers of that listing reported,
  namely orders and how many arrived late, units inspected and how many were defective,
  and the largest order it filled in full.
- A listing with no reported orders is new and carries a cohort_record instead: of the
  new sellers of the same kind that the marketplace tracked, how many proved unreliable
  on delivery (on time for about half their orders) and how many failed inspection
  (about half their units good). The rest were sound. A record of either kind is neither
  a formal offer nor a verified sample.

Return only the next JSON action.
"""

# Version 2 states two things the first panels showed the first version left open
# (incident rows P-D-19 and P-D-21): that a quote is final, and that the buyer is
# judged on its average over many such orders. Without the first, a counter-offer
# is a reasonable thing to try and costs a day. Without the second, a cautious
# move that gives up expected margin is not clearly a mistake.
PROMPT_ID_V2 = "procurement_allocation_pay_or_test_neutral_v2"
TREATMENT_ID_V2 = "order_accounting_request_facts_final_quotes_average_objective_v2"

_AVERAGE = """- You place many orders like this one and are judged on your average margin across
  them, not on how any single order turns out.
"""
_FINAL = """- A formal quote is the supplier's final price and terms. A counter_offer cannot
  improve them; it costs policy.process.counter_fee_usd and policy.process.counter_days.
"""
_COUNTED = "What each request costs and shows:\n"
_FACTS = "Facts about this marketplace:\n"
assert PAY_OR_TEST_PROMPT.count(_COUNTED) == 1 and PAY_OR_TEST_PROMPT.count(_FACTS) == 1
PAY_OR_TEST_PROMPT_V2 = (
    PAY_OR_TEST_PROMPT
    .replace("\n" + _COUNTED, _AVERAGE + "\n" + _COUNTED)
    .replace("\n" + _FACTS, _FINAL + "\n" + _FACTS)
)

__all__ = ["PAY_OR_TEST_PROMPT", "PAY_OR_TEST_PROMPT_V2", "PROMPT_ID", "PROMPT_ID_V2", "TREATMENT_ID", "TREATMENT_ID_V2"]
