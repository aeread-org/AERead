from __future__ import annotations

from aeread.shared_runner.registry import TRUSTED_BUILTIN_PLUGIN_KEYS


EXTERNAL_ADAPTER_KEYS = {
    ("agenticpay.bilateral", "0.1.0", "agenticpay_bilateral_environment"),
    ("alympics.wac", "0.1.0", "alympics_wac_environment"),
    ("amazonbarg.bilateral", "0.1.0", "amazonbarg_environment"),
    ("aucarena", "0.1.0", "aucarena_environment"),
    ("collusion", "0.1.0", "collusion_environment"),
    ("econagent_v1", "0.1.0", "econagent_v1_environment"),
    ("econevals", "0.1.0", "econevals_environment"),
    ("govsim", "0.1.0", "govsim_environment"),
    ("negarena", "0.1.0", "negarena_environment"),
    ("steer", "0.1.0", "steer_environment"),
    ("termsbench.overlap", "0.1.0", "termsbench_overlap_environment"),
    ("termsbench.nodeal", "0.1.0", "termsbench_nodeal_environment"),
}


def test_external_adapter_families_are_trusted_builtin_plugins() -> None:
    assert EXTERNAL_ADAPTER_KEYS <= TRUSTED_BUILTIN_PLUGIN_KEYS
