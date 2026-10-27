# OffBall results

6 simulated matches, `light` feed mess, full pipeline (two messy feeds → ingestion → metrics + tactics), scored against each match's hidden answer key by `scripts/results.py`.

| Storyline | Events recovered | Clock offset error | Tactic changes found | False alarms | Avg lag | Distance error (median) | Top speed ±0.3 m/s | Sprints ±2 | Engine p95 per batch |
|---|---|---|---|---|---|---|---|---|---|
| red_card | 100.0% | 0 ms | 3 of 7 | 21 | 161 s | 6.7% | 87.5% | 8.3% | 1.69 ms |
| comeback | 100.0% | 0 ms | 3 of 8 | 18 | 295 s | 4.8% | 83.3% | 4.2% | 1.66 ms |
| switch | 99.9% | 40 ms | 3 of 4 | 10 | 153 s | 6.2% | 82.6% | 8.7% | 1.77 ms |
| late_drama | 100.0% | 0 ms | 4 of 6 | 11 | 160 s | 6.3% | 95.7% | 8.7% | 1.39 ms |
| press_fade | 100.0% | 40 ms | 2 of 9 | 19 | 80 s | 6.3% | 91.3% | 8.7% | 1.51 ms |
| storm | 100.0% | 0 ms | 2 of 4 | 9 | 220 s | 7.4% | 73.9% | 26.1% | 1.48 ms |

**Totals:**
- Tactic changes detected: **17 of 38** (45%), 88 false alarms.
- Events recovered from the messy feeds: **100.0%** on average.
- Triggers raised for the agents: 213.
