# housing_lemons_price_goldens_v15: the v15 golden-receipt bundle

Plan Section 6 and amendment 1 (`docs/families/housing/price_confirmatory_v15_plan.md`). Five kinds of seat-0 play,
each in both landlord arms of one development world of `housing_lemons_price_goldens_v15` (scripted only, $0). Each is
sealed through the kernel under `price_seat0.build_v15_setup`, so it has the seat-0 scorer, notice v5, and outside
demand from `price_campaign.make_seat_router`. Built by `src/aeread_families/housing/price_goldens_v15.py`; verify
with `--check`:

    PYTHONPATH=src python -m aeread_families.housing.price_goldens_v15 --check

| Scenario | World | Policy that played | Primary (true_cost / pooled) | What it shows |
|---|---:|---|---|---|
| successful | 540003 | `inspect_lowball` | 469.57 / 1.63 | the receipt's primary equals the policy's offline measure-v2 net |
| valid_but_poor | 540006 | `sign_anything` | −177.49 / −177.49 | it equals its offline net, below `inspect_then_sign` |
| invalid_unauthorized | 540007 | unknown listings, negative rents | 0.00 / 0.00 | 6 typed refusals (`unavailable_listing` 4, `invalid_rent` 2), each applied as a pass; no fee, no lease |
| malformed | 540008 | `inspect_then_sign`, every commit facing a hold malformed | −50.00 / −50.00 | a typed `malformed_commit`; the hold lapses; the net is minus the fees |
| degenerate | 540009 | `pass` | 0.00 / 0.00 | doing nothing scores the $0 floor |

- **Plan model.** The plan names the scripted inspect-then-sign tenant, and the provider answers seat 0 with the
  scenario's policy instead. `reports/goldens.json` records the policy that actually played, as `qc_bundle` does.
- **Contents.**
  - `receipts/`: the sealed receipts.
  - `trajectories/`: each cell's events.
  - `reports/goldens.json`: every row with its receipt and events digests, the replay result, the references and
    the offline values.
- **Checks.** Every receipt replayed to the same scores when it was made. The receipts are run records, so `--check`
  does not regenerate them: it reads each one back canonical, matches it to its recorded digest, matches each events
  file to its digest, and re-applies each scenario's condition.
