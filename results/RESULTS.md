# OffBall results

6 simulated matches, `light` feed mess, full pipeline (two messy feeds → ingestion → metrics + tactics), scored against each match's hidden answer key by `scripts/results.py`.

| Storyline | Events recovered | Clock offset error | Tactic changes found | False alarms | Avg lag | Distance error (median) | Top speed ±0.3 m/s | Sprints ±2 | Engine p95 per batch |
|---|---|---|---|---|---|---|---|---|---|
| red_card | 100.0% | 0 ms | 3 of 7 | 11 | 198 s | 6.7% | 100.0% | 16.7% | 5.79 ms |
| comeback | 100.0% | 40 ms | 1 of 7 | 13 | 60 s | 6.0% | 100.0% | 8.3% | 7.97 ms |
| switch | 100.0% | 40 ms | 2 of 4 | 9 | 100 s | 6.2% | 95.7% | 8.7% | 7.79 ms |
| late_drama | 100.0% | 40 ms | 4 of 6 | 13 | 227 s | 5.8% | 100.0% | 4.3% | 6.39 ms |
| press_fade | 100.0% | 20 ms | 2 of 9 | 7 | 185 s | 6.7% | 91.3% | 13.0% | 6.66 ms |
| storm | 100.0% | 20 ms | 2 of 4 | 14 | 140 s | 6.5% | 87.0% | 13.0% | 5.84 ms |

**Totals:**
- Tactic changes detected: **14 of 37** (38%), 67 false alarms.
- Events recovered from the messy feeds: **100.0%** on average.
- Triggers raised for the agents: 182.
