# Unit-explicit integrated data-center expansion cases v4

This pack derives from `public_integrated_expansion_v3` after the V8 campaign
showed that plain numeric schema fields did not say whether currency observations
stated in millions should be returned in millions or base currency units.

V4 appends one visible numeric-unit rule to every case prompt. Monetary amounts
must use base currency units; all other numeric values must use the unit named by
the field key. Every observation, response vocabulary, hidden oracle, authority,
project cluster, and world seed is preserved from V3, including Tydal's restored
22nd-day invoice term.

V8 remains immutable evidence for provider pacing and for the unit-contract
defect. V4 is the first expansion pack suitable for interpreting all numeric
leaves without guessing whether a currency value is scaled in millions.
