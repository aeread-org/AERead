# Examples

| Script | What it shows |
|---|---|
| [`run_episode_minimal.py`](run_episode_minimal.py) | The smallest loop: one seeded episode of any case, your model in the under-test seat, frozen panel everywhere else, per-episode AER printed. Start here. |

Integration-specific examples live with their integration:

- **EverOS memory A/B** → [`integrations/everos/everos_memory_ab.py`](../integrations/everos/everos_memory_ab.py)
  (moved here from `examples/` — memory-on vs memory-off arms with pooled AER + bootstrap CI)

For the fully offline path (no API keys at all), see the 60-second quickstart
in the [README](../README.md) — scripted policies and provider-free baselines
exercise the whole arena on pure CPU.
