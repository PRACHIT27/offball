# OffBall results

6 simulated matches, `light` feed mess, full pipeline (two messy feeds → ingestion → metrics + tactics), scored against each match's hidden answer key by `scripts/results.py`.

| Storyline | Events recovered | Clock offset error | Tactic changes found | False alarms | Avg lag | Distance error (median) | Top speed ±0.3 m/s | Sprints ±2 | Engine p95 per batch |
|---|---|---|---|---|---|---|---|---|---|
| red_card | 100.0% | 0 ms | 4 of 7 | 13 | 122 s | 4.1% | 83.3% | 20.8% | 5.94 ms |
| comeback | 100.0% | 0 ms | 4 of 7 | 22 | 185 s | 3.9% | 95.8% | 8.3% | 12.82 ms |
| switch | 100.0% | 20 ms | 2 of 4 | 14 | 150 s | 4.1% | 87.0% | 8.7% | 4.72 ms |
| late_drama | 100.0% | 40 ms | 3 of 6 | 16 | 173 s | 4.3% | 87.0% | 8.7% | 4.34 ms |
| press_fade | 100.0% | 0 ms | 0 of 9 | 14 | – | 4.3% | 91.3% | 13.0% | 14.08 ms |
| storm | 100.0% | 0 ms | 1 of 4 | 20 | 350 s | 4.2% | 78.3% | 13.0% | 4.74 ms |

**Totals:**
- Tactic changes detected: **14 of 37** (38%), 99 false alarms.
- Events recovered from the messy feeds: **100.0%** on average.
- Triggers raised for the agents: 229.
