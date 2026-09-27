# datacenter_risk_allocation_tender_eval_v1

The tender of the integrator-client risk-allocation case (`docs/families/datacenter/risk_allocation_case.md`): three scripted firms, each managed or turnkey with its own private type, bid once each on their standard contracts; the model, as client, accepts a standing offer, walks to managing the deployment itself, or negotiates with any of the firms in the same turn (counters and price requests on any contract of each firm's menu). The firms price every contract by a policy the client is not told. Sealed, verified and replayed through the shared runner. It does not rank models.

Decision regret ($ thousands) is what each turn gave up against a client who knows how the firms price their contracts (each bid then reveals its firm's type), summed over the episode.

| arm / client | valid | decision regret [95% CI] | zero regret | signed with a best firm | a best contract with it | walked where walking is best | cost over best attainable | bidders per negotiating turn |
|---|---|---|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | 20/20 | 351.345 [286.198, 420.217] | 0 | 10 of 16 | 0 | 1 of 4 | 419.141 | 2.286 |
| low_effort/gemini38_flash | 60/60 | 446.326 [408.302, 485.805] | 0 | 30 of 50 | 1 | 0 of 10 | 494.975 | 2.033 |
| low_effort/glm53_flash | 54/60 | 353.325 [302.408, 401.327] | 0 | 26 of 44 | 1 | 3 of 10 | 402.432 | 2.605 |
| scripted_controls/scripted_accept_the_lowest_bid | 60/60 | 609.396 [564.517, 656.765] | 0 | 18 of 50 | 4 | 0 of 10 | 656.482 | None |
| scripted_controls/scripted_every_protection_everywhere | 60/60 | 485.909 [452.934, 520.429] | 0 | 36 of 50 | 3 | 0 of 10 | 532.6 | 3.0 |
| scripted_controls/scripted_haggle_the_lowest_bid | 60/60 | 354.889 [299.361, 414.84] | 0 | 17 of 50 | 3 | 0 of 10 | 401.426 | 1.0 |
| scripted_controls/scripted_reference | 60/60 | 0.0 [0.0, 0.0] | 60 | 44 of 50 | 44 | 10 of 10 | 48.037 | 1.031 |
| scripted_controls/scripted_self_manage | 60/60 | 270.271 [220.516, 323.279] | 10 | 0 of 50 | 0 | 10 of 10 | 317.357 | None |

## The declared contrast

at low effort, the mean paired difference in decision regret, GLM 5.3 Flash minus Gemini 3.8 Flash, over worlds valid for both, with its interval (the pilot, on 21 other worlds: -113 [-192, -41]). 95% percentile bootstrap, 2000 draws, seed 20260926, worlds resampled. Positive means GLM gave up more.

| arm | worlds | GLM minus Gemini | sd of the per-world difference | worlds at one seed for a half-width of 25 / 50 / 75 |
|---|---|---|---|---|
| low_effort | 54 | -98.518 [-143.878, -52.434] | 180.315 | 200 / 50 / 23 |

Default reasoning minus low effort, same worlds (default reasoning is seated on the declared subset only):

| client | worlds | difference |
|---|---|---|
| gemini38_flash | 20 | -113.85 [-190.578, -54.065] |
| glm53_flash | 0 | not seated |

## Where the cost comes from

Each valid episode's cost over the best attainable (the lowest of every firm's best contract at its last-round price and managing it yourself), split into the firm chosen (its best contract's cost over the best firm's), the contract signed with it (over that firm's best), the price paid over that firm's last-round price for it, walking when a deal was better, and refused counters (declined requests included). The parts sum to the cost over the best attainable, not to decision regret, which is scored on the client's information (DC-J-04).

| arm / client | firm chosen | contract | price over last-round price | walking | refused counters |
|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | 59.382 | 62.52 | 202.51 | 35.979 | 58.75 |
| low_effort/gemini38_flash | 100.802 | 94.174 | 249.165 | 0.0 | 50.833 |
| low_effort/glm53_flash | 56.225 | 65.56 | 183.763 | 22.81 | 74.074 |
| scripted_controls/scripted_accept_the_lowest_bid | 129.0 | 127.483 | 400.0 | 0.0 | 0.0 |
| scripted_controls/scripted_every_protection_everywhere | 71.913 | 106.668 | 279.018 | 0.0 | 75.0 |
| scripted_controls/scripted_haggle_the_lowest_bid | 133.796 | 128.88 | 93.333 | 0.0 | 45.417 |
| scripted_controls/scripted_reference | 5.514 | 0.276 | 7.03 | 13.133 | 22.083 |
| scripted_controls/scripted_self_manage | 0.0 | 0.0 | 0.0 | 317.357 | 0.0 |

Terms that differ from the chosen firm's nearest best contract, over signed deals in worlds where a deal is best:

| arm / client | signed deals | warranty | damages | liability_cap | readiness | consequential | deposit | escrow | burn_in |
|---|---|---|---|---|---|---|---|---|---|
| default_reasoning/gemini38_flash | 13 | 4 | 6 | 3 | 3 | 4 | 10 | 0 | 2 |
| low_effort/gemini38_flash | 50 | 1 | 30 | 14 | 16 | 15 | 39 | 0 | 9 |
| low_effort/glm53_flash | 39 | 2 | 16 | 3 | 7 | 10 | 30 | 0 | 10 |
| scripted_controls/scripted_accept_the_lowest_bid | 50 | 32 | 30 | 25 | 0 | 23 | 10 | 0 | 16 |
| scripted_controls/scripted_every_protection_everywhere | 50 | 9 | 20 | 1 | 7 | 21 | 40 | 0 | 37 |
| scripted_controls/scripted_haggle_the_lowest_bid | 50 | 30 | 33 | 23 | 4 | 24 | 13 | 0 | 16 |
| scripted_controls/scripted_reference | 47 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| scripted_controls/scripted_self_manage | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Missing cells by cause: low_effort/glm53_flash: 1 provider_rejected, 5 truncated_reply.

Not seated: default_reasoning/glm53_flash (DC-O-14).

Seated on a declared subset: default_reasoning (the first two worlds of each world type and situation, in pack order).

Claim: descriptive: no winner, no ranking, no causal effect.

The reference graded zero regret on every cell: True.

## Accounting

439 of 440 planned cells executed, 1 sealed as typed exclusions, 0 not attempted; 434 valid episodes. Replay verified: True. Cost $1.32 (exact): every answered provider call of every cell, read from the sealed event logs at the declared per-token prices.

Plan `88e4c0bb179c`.
