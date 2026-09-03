# Indicator-map public integrated data-center project cases v4

This pack derives from corrected `public_integrated_v2`. It preserves all three
project observations, source clusters, authority, world seeds, state vocabulary,
and hidden oracle leaves. The only change is a final prompt instruction encoding
actions, claims, and evidence IDs as complete boolean classifier maps and the
external-action signal as one boolean.

The matching campaign must enable the indicator-map schema and normalize its
selected booleans to the family’s canonical label arrays before scoring. This
avoids duplicate-label ambiguity without depending on the unsupported JSON
Schema `uniqueItems` keyword. The pack remains exploratory and does not support
population generalization or inferential model ranking.
