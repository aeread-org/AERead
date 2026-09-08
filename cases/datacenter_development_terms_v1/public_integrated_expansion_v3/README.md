# Answerability-corrected integrated data-center expansion cases v3

This pack derives from `public_integrated_expansion_v2` after the V6 campaign
revealed that Tydal's visible e05 observation omitted the hidden oracle's
invoice-payment-day value. The correction restores the filed term: the final
itemized invoice is due on the 22nd of the month in which project accounts are
submitted, adjusted to the next working day when necessary.

The case prompt, complete indicator-map encoding, response vocabulary, hidden
oracle, authority, project cluster, and world seed are unchanged. Every other
observation is preserved. The manifest now maps every numeric oracle key across
all three cases to a visible evidence ID and requires the corrected Tydal e05 to
contain both the 22nd-day payment term and seven-day suspension notice.

V2 and its V6 campaign remain immutable invalidation evidence. V3 is the first
pack suitable for interpreting the Tydal amount score.
