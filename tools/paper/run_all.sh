#!/bin/zsh
# Rebuild the HL-D-07 rescoring and the cross-case failure taxonomy cited by the paper (§5.2, Appendix E.5).
# Read-only with respect to every input; outputs land beside the scripts. Inputs (environment):
#   AEREAD_HOUSING_ROOT          checkout of codex/housing-lemons-outside-demand with the v14 run roots under runs/
#   AEREAD_PROCUREMENT_ROOT      checkout of codex/procurement-pay-or-test with the flash-model run roots under runs/
#   AEREAD_PROCUREMENT_CLI_RUNS  directory holding the two CLI-agent pay-or-test run roots
#   AEREAD_DATACENTER_ROOT       checkout of codex/datacenter-agreement (reads its published evidence/ bundles)
#   AEREAD_REPO                  a clone with the origin/codex/refund-gap-analysis ref (reads the published Refund V2.1 gap bundle)
# The Housing and Procurement inputs are sealed run roots that are not yet published as bundles.
set -e
cd "${0:A:h}"
PY=${PYTHON:-python}
export PYTHONDONTWRITEBYTECODE=1
(cd hl_d_07 && PYTHONPATH=$AEREAD_HOUSING_ROOT/src $PY hl_d_07.py > /dev/null)
cd failure_taxonomy
PYTHONPATH=$AEREAD_HOUSING_ROOT/src:../hl_d_07 $PY housing_v14.py
$PY procurement_pay_or_test.py
$PY -I datacenter_agreement.py > /dev/null
$PY -I refund_v21.py
$PY -I build.py
