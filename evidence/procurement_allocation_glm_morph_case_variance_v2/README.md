# Procurement allocation GLM case-variance v2

Sanitized, digest-bound review evidence for the declared six-case, three-seed procurement allocation panel. Raw prompts, provider payloads, event logs, and replay stores remain under the ignored `runs/` tree.

`trajectories/sanitized.jsonl` (added 2026-09-07 as a mechanical correction; the manifest was re-sealed, no reported number changed) is the kernel trajectory grain: one row per logical action across the 18 published receipts, carrying the parsed action, legality, outcome, and per-call route/usage/cost facts, and nothing from the prompts or provider text. See `docs/getting-started/reviewing_trajectories.md` §5 for the row schema and how it was produced.
