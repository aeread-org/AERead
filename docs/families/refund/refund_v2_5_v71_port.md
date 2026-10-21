# V7.1 port to the published shared runner

This port is provider-free and developmental. It does not restart historical
experiments or reproduce their run-plan identities. Historical results remain
bound to their original frozen runner and source hashes.

## Scope and compatibility

The original target kernel was GitHub `main@dec1a40f8de6fcef1dca950e965df37544d3c3a6`.
The port lives on the existing `codex/refund-v25-shared-runner` worktree/PR base.
There are **no changes to `src/aeread/shared_runner`** relative to that main
commit. V7.1 uses its registry, resolved plans, phase scheduler, sealed receipts,
typed scorers and independent replay/audit APIs.

Added modules are the V6.2.1 reference dependencies, the V7 structure builder and
the V7.1 validity repair. The only portability changes to those historical
modules are the proposal-asset location and QC evidence-root selection. The
proposal is shipped as `cases/refund_v25/design/v7_design_proposal.json` and
checked against its original SHA-256; wheel builds include it with the QC assets.
No historical case, reference rule, enum, prompt rule, transition or scorer was
redesigned in this port.

The public entrypoint now accepts `v71_intake` and `v71_customer`. Each contains
32 developmental variants per world seed. It still selects exactly one active
seat and uses deterministic reference providers for all four seats during
provider-free qualification.

```bash
python -m aeread_families.refund.v2_5_release \
  --panel v71_intake --active-agents intake --seed 301 \
  --output /tmp/refund-v71-intake-new
python -m aeread_families.refund.v2_5_release \
  --panel v71_customer --active-agents customer --seed 301 \
  --output /tmp/refund-v71-customer-new
python -m pytest -q tests/test_refund_v25_v71_port.py \
  tests/test_refund_v25_seat_extension_v6_2_1.py \
  tests/test_refund_v25_seat_extension_v7.py \
  tests/test_refund_v25_seat_extension_v7_1.py
```

Fresh outputs are mandatory. The setup factory
`aeread_families.refund.v2_5_release:replay_setup` reconstructs public V7.1
receipts using `AEREAD_REFUND_V25_RUN_ROOT`, as for the earlier public panels.

## Verification

- 98 extension/branch/visibility tests passed.
- 165 core/release/collection-budget regression tests passed.
- 5 preservation, packaged-design and public replay tests passed.
- 100 shared-runner compatibility tests passed; one pre-existing expected failure.
- 960/960 scripted trajectories completed across three seeds, both panels and
  four controlled seats, including reserved development templates. All score
  leaves and collaboration values/coverage are full; all trajectories replayed
  and all 960 durable receipts independently audited against reconstructed plans.
- An installed wheel outside the repository completed and independently audited
  32/32 public Intake trajectories with zero paid calls. The packaged proposal
  and QC evidence resolved without a checkout-local configuration directory.
- Full serialized case-contract hashes match the historical implementation for
  all six seed/panel combinations (240 instances including reserved templates).
  Frozen hash assertions are included in `test_refund_v25_v71_port.py`.

Reserved templates are used here only for offline environment qualification.
Published templates are not a secret held-out model test set. These checks do
not establish real-world business utility or independent normative validity.
Intake release checkpoints and utilities remain explicitly synthetic.

## Historical results and remaining boundary

The historical runner source snapshot, frozen configuration, SHA-256 manifest,
case-parity record, conformance receipts and installed-wheel evidence are kept
under `artifacts/refund_v25_latest_runner_port1` in the original experiment
workspace. That source archive excludes credentials. It is a runner preservation
snapshot, not a claim that a new checkout can regenerate historical run-plan IDs.

The paid calibration stopped with 1,642/1,728 complete outcomes at its declared
known-spend threshold. Those measurements, original failure receipts and unknown
historical charges remain untouched. They are not relabelled as measurements
on the current GitHub kernel, nor used here for incomplete-panel rankings.

**Compatibility is provider-free, not paid-Arena equivalence.** The historical
Arena adapter and SDK workaround are not copied into the published kernel.
Public paid execution remains blocked before credential/client initialization.
See [#267](https://github.com/aeread-org/AERead/issues/267) and
[#264](https://github.com/aeread-org/AERead/issues/264). A live campaign on this
kernel requires separately qualified adapter behavior, full-trajectory gates,
frozen profiles and explicit budget/operational-stop rules. This port makes no
paid calls and does not authorize resuming the stopped calibration.

## 2026-10-21 PR refresh

This extension is included in the update prepared for draft
[PR #269](https://github.com/aeread-org/AERead/pull/269); it is not a claim of
merge into GitHub main. The base branch is not silently rebased over the
previously prepared changes.

At this review, current GitHub main is
`1dd48cf5a443c94eccdd0597144fbf1c0e693525`. Its shared-runner tree differs from
the original port target. A read-only Git archive of its exact `src/aeread`
tree was placed first on `PYTHONPATH`, with the prepared V2.5 family loaded
from this PR worktree. Imported module paths were checked explicitly. This
tests family interoperability with that kernel, not a full merged-tree CI run.

- 265 focused core, branch, release, V6.2.1/V7/V7.1 and preservation/replay tests
  passed against that current-main kernel snapshot.
- All 13 public panels × four controlled seats completed 1,072/1,072 reference
  trajectories on seed 301 against that same snapshot. Every trajectory had
  full scores and independently replayed/audited receipts, with zero operational
  exclusions and zero paid calls. A fresh repeat after EOF-only cleanup also
  completed 1,072/1,072. These are conformance checks, not LLM measurements.
- 125 port/release regression tests separately passed against the original
  PR kernel.
- The generated family/case catalogs were refreshed; all 6 catalog tests pass.
  This repairs the precise stale-catalog failure in the prior GitHub CI run.
- A final combined overlay run passed all 265 family tests but its catalog
  registry-consistency test failed (270 passed, 1 failed overall): that test
  intentionally compares the checkout's on-disk registry with the imported
  registry, and an old-checkout/new-kernel overlay has different trusted keys.
  Catalog tests are therefore qualified in the native PR checkout, not claimed
  as passing in that mixed tree. This is another reason not to describe the
  overlay check as merged-tree integration CI.

Full repository integration CI must rerun on the updated PR. Scripted
conformance is not model-performance evidence. Full publication QC remains
unsatisfied for the reasons in [#290](https://github.com/aeread-org/AERead/issues/290);
the separate Refund V3 repair is paused and excluded from this update.
