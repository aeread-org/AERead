# datacenter_risk_allocation_tender_pilot_v1

The tender of the integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`): three scripted firms, each managed or turnkey with its own private type, bid once each on their standard contracts; the model, as client, accepts a standing offer, walks to managing the deployment itself, or negotiates with any of the firms in the same turn (counters and price requests on any contract of each firm's menu). The firms price every contract by a policy the client is not told. Sealed, verified and replayed through the shared runner. It does not rank models.

Decision regret ($ thousands) is what each turn gave up against a client who knows how the firms price their contracts (each bid then reveals its firm's type), summed over the episode.

| arm / client | valid | decision regret [95% CI] | zero regret | signed with a best firm | a best contract with it | walked where walking is best | cost over best attainable | bidders per negotiating turn |
|---|---|---|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | 10/10 | 224.627 [129.361, 317.088] | 0 | 3 of 8 | 0 | 2 of 2 | 306.551 | 2.5 |
| low_effort/gemini38_flash | 24/24 | 444.065 [402.151, 487.457] | 0 | 13 of 20 | 1 | 0 of 4 | 495.576 | 2.042 |
| low_effort/glm53_flash | 21/24 | 345.339 [268.35, 424.596] | 0 | 14 of 17 | 2 | 1 of 4 | 389.043 | 2.4 |
| scripted_controls/scripted_accept_the_lowest_bid | 24/24 | 611.133 [544.058, 681.605] | 0 | 7 of 20 | 2 | 0 of 4 | 658.7 | None |
| scripted_controls/scripted_every_protection_everywhere | 24/24 | 485.553 [424.199, 542.309] | 0 | 14 of 20 | 1 | 0 of 4 | 541.153 | 3.0 |
| scripted_controls/scripted_haggle_the_lowest_bid | 24/24 | 390.024 [305.043, 486.118] | 0 | 8 of 20 | 2 | 0 of 4 | 461.43 | 1.0 |
| scripted_controls/scripted_reference | 24/24 | 0.0 [0.0, 0.0] | 24 | 17 of 20 | 17 | 4 of 4 | 50.717 | 1.081 |
| scripted_controls/scripted_self_manage | 24/24 | 328.022 [216.431, 445.383] | 4 | 0 of 20 | 0 | 4 of 4 | 375.588 | None |

## The declared contrast

at low effort, the mean paired difference in decision regret, GLM 5.3 Flash minus Gemini 3.8 Flash, over worlds valid for both, with its interval; reported as the size a later run must resolve, not as a result. 95% percentile bootstrap, 2000 draws, seed 20260926, worlds resampled. Positive means GLM gave up more.

| arm | worlds | GLM minus Gemini | sd of the per-world difference | worlds at one seed for a half-width of 25 / 50 / 75 |
|---|---|---|---|---|
| low_effort | 21 | -113.079 [-191.589, -41.325] | 181.265 | 202 / 51 / 23 |

Default reasoning minus low effort, same worlds (default reasoning is seated on the declared subset only):

| client | worlds | difference |
|---|---|---|
| gemini38_flash | 10 | -210.269 [-327.125, -90.06] |
| glm53_flash | 0 | not seated |

## Where the cost comes from

Each valid episode's cost over the best attainable (the lowest of every firm's best contract at its last-round price and managing it yourself), split into the firm chosen (its best contract's cost over the best firm's), the contract signed with it (over that firm's best), the price paid over that firm's last-round price for it, walking when a deal was better, and refused counters (declined requests included). The parts sum to the cost over the best attainable, not to decision regret, which is scored on the client's information (DC-J-04).

| arm / client | firm chosen | contract | price over last-round price | walking | refused counters |
|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | 17.286 | 42.733 | 118.35 | 65.682 | 62.5 |
| low_effort/gemini38_flash | 77.391 | 109.135 | 258.008 | 0.0 | 51.042 |
| low_effort/glm53_flash | 41.235 | 89.212 | 176.719 | 8.068 | 73.81 |
| scripted_controls/scripted_accept_the_lowest_bid | 134.221 | 124.479 | 400.0 | 0.0 | 0.0 |
| scripted_controls/scripted_every_protection_everywhere | 79.71 | 109.612 | 267.142 | 9.689 | 75.0 |
| scripted_controls/scripted_haggle_the_lowest_bid | 143.284 | 124.396 | 150.0 | 0.0 | 43.75 |
| scripted_controls/scripted_reference | 0.0 | 0.0 | 0.0 | 26.759 | 23.958 |
| scripted_controls/scripted_self_manage | 0.0 | 0.0 | 0.0 | 375.588 | 0.0 |

Terms that differ from the chosen firm's nearest best contract, over signed deals in worlds where a deal is best:

| arm / client | signed deals | warranty | damages | liability_cap | readiness | consequential | deposit | escrow | burn_in |
|---|---|---|---|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | 5 | 2 | 3 | 1 | 1 | 0 | 5 | 0 | 0 |
| low_effort/gemini38_flash | 20 | 1 | 13 | 5 | 8 | 6 | 14 | 0 | 5 |
| low_effort/glm53_flash | 16 | 2 | 5 | 3 | 4 | 5 | 13 | 1 | 6 |
| scripted_controls/scripted_accept_the_lowest_bid | 20 | 14 | 14 | 9 | 0 | 9 | 5 | 0 | 4 |
| scripted_controls/scripted_every_protection_everywhere | 19 | 3 | 9 | 1 | 5 | 9 | 15 | 0 | 15 |
| scripted_controls/scripted_haggle_the_lowest_bid | 20 | 11 | 14 | 8 | 1 | 9 | 7 | 0 | 6 |
| scripted_controls/scripted_reference | 17 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| scripted_controls/scripted_self_manage | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Missing cells by cause: low_effort/glm53_flash: 1 bidder_not_negotiating, 1 no_such_offer, 1 truncated_reply.

Not seated: default_reasoning/glm53_flash (DC-O-14).

Seated on a declared subset: default_reasoning (the first world of each world type and situation, in pack order).

Claim: descriptive: no winner, no ranking, no causal effect.

The reference graded zero regret on every cell: True.

## Accounting

178 of 178 planned cells executed, 0 sealed as typed exclusions, 0 not attempted; 175 valid episodes. Replay verified: True. Cost $0.59 (exact): every answered provider call of every cell, read from the sealed event logs at the declared per-token prices.

Plan `08281c1c2cbd`.
