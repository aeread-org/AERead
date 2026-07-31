---
name: New integration
about: Connect AERead to another framework, memory system, or training stack
labels: integration
---

**What are you integrating?** (framework/tool + link)

**Which seam?** (see [integrations/README.md](../../integrations/README.md))
- [ ] Submitted agent — `act(observation, phase) -> str` (evaluation, memory, tooling)
- [ ] Episode core — `run_episode(...)` as a reward/rollout primitive (training)

**Does your agent carry state across episodes?** (memory/learning — affects
replay semantics; see the EverOS integration for the pattern)

**Sketch** — what lives in `src/aeread/integrations/<name>.py`, what the
offline tests fake, what the example script demonstrates.
