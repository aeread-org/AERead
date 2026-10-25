# Refund V3.4: portable developmental research package

Start with the [public evidence bundle](../../evidence/refund/refund_v34_developmental_20261025/README.md).
This package does not register an official family, modify the shared-runner kernel,
change the project's package version, or authorize live execution.

## Contents and source boundary

`source/aeread_families/refund/` holds the frozen V3.4 native case/scorer/transition
modules and their legacy dependency closure. The native V3.4 modules and protocol
are byte-preserved. One legacy CLI-only default for a credential file is changed
to a relative path to avoid disclosing a personal filesystem path. Original and
public source hashes and this exception are declared in the runtime bindings.
No scientific case, scoring or transition function is edited for publication.

`reproduce.py` overlays these research modules onto the repository runtime;
it does not change the official registry. The shared-runner bytes are pinned
to upstream commit `1e2ae36748b69a928494d4a673c84b3c47105407` by the bundle.
Historical names such as `v32_holdout` and split labels are lineage, not a claim
that the V3.4 panel is still unseen. The checked-in source seed lists are
development-exposed; no private held-out evaluation data is included or executed.

```sh
pip install -e '.[dev]'
python research/refund_v34/reproduce.py
python -m pytest -q --noconftest research/refund_v34/test_publication.py
```

No credentials are needed. Verification blocks sockets and only uses the public
bundle. It does not import the live adapters or construct a provider client.
Do not run legacy archived CLI entry points to reproduce this publication.

## V3.4 versus V3.3

V3.4 repairs attribution: Intake's target is derived from the initial public
observation even after an illegal first request; Payments binding IDs are scored
separately from capacity, duplicate and execution errors. A source pair sharing
an optimal Intake plan becomes diagnostic at all seeds; selection is based on
source structure, not model success. The selected panel has 220 cases.

The output envelope `refund_json_outer_fence/1` is separately versioned and
does not repair action values or schema. New Pro, GPT low and GPT medium stages
use it; Lite and GPT none retain historical collection semantics. Lite was
collected under V3.3, then replayed/scored under V3.4, not freshly re-collected.

## Maintainer-only re-export

`export_local.py --source-workspace <retained-workspace> --publication-root <new-root>`
reads whitelisted fields from retained local run stores and verifies their
seals before projecting them with the kernel's canonical sanitizer. It refuses
an already sealed destination. Public reviewers do not need those private runs.
The exporter and verifier are versioned separately from all original experiment
scripts; the original low analysis-export bug remains unchanged in its source.

This release is developmental/exploratory, not full QC, held-out evaluation,
isolated causal inference, or a confirmatory ranking. It does not fix issue #309.
