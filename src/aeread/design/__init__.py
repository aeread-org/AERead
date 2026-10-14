"""Design-time calculations a campaign makes before it runs.

Nothing here executes or scores a cell. A campaign uses these to decide how
many worlds to freeze, to state what its screen can miss, and to say how
reproducible its comparison is, and it seals the result with the design.
"""

from aeread.design.aa import aa_check
from aeread.design.reliability import (
    reliability,
    sign_agreement,
    variance_components,
    worlds_for_reliability,
)
from aeread.design.screens import admit_probability, screen_plan
from aeread.design.sizing import (
    detection_rate,
    sd_of_differences,
    sizing_record,
    smallest_detectable_effect,
    verify_sizing_record,
    worlds_needed,
)

__all__ = [
    "aa_check",
    "admit_probability",
    "detection_rate",
    "reliability",
    "screen_plan",
    "sd_of_differences",
    "sign_agreement",
    "sizing_record",
    "smallest_detectable_effect",
    "variance_components",
    "verify_sizing_record",
    "worlds_for_reliability",
    "worlds_needed",
]
