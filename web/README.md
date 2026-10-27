# OffBall viewer screen

The viewer screen from [lld-audience.md](../docs/design/lld-audience.md): the pitch, a caption bar,
a side panel and a timeline. React + TypeScript + Vite, with the pitch drawn in SVG.

**Today it plays recorded matches.** Each replay file is a simulated match run through the real
engine: ingestion, Performance Metrics and Tactical Intelligence. So everything on screen is the
engine's own output, and nothing comes from the answer key. Live mode (the `stats` hub through Web
PubSub) is the next step.

## Run it

```sh
# 1. Build replays (from the repo root, with the Python .venv)
PYTHONPATH=. python scripts/build_replay.py --storyline red_card --out web/public/replays
PYTHONPATH=. python scripts/build_replay.py --storyline comeback --out web/public/replays
PYTHONPATH=. python scripts/build_replay.py --storyline switch   --out web/public/replays

# 2. Start the screen
cd web && npm install && npm run dev      # http://localhost:5173
npm run build                             # static site in web/dist (Static Web Apps)
```

Add `--minutes 10` to build a quick short match.

## What it shows

| Area | What | From |
|---|---|---|
| Top bar | Score, broadcast clock, match picker, casual / analyst, play, 1× / 5× / 10×, next key moment | events, frames |
| Pitch | Players and ball at 60 fps (interpolated from 5 frames per second), shirt numbers, name tags with speed when running, pressure rings on the carrier, both defensive lines with their height | metrics `positions`, tactics `series` |
| Overlays | Pass arc coloured by difficulty (distance, speed, difficulty); ghost arrow to the better option (analyst); decoy runs | metrics cues |
| Caption bar | One caption at a time: goals, cards, subs, tactic changes (before → after), speed alerts, shot speed + xG. Written from the numbers and marked `auto`; agent captions replace them later | events, tactics triggers, cues |
| Side panel (analyst, or tap a player) | xG race and chance story, defensive line height with tactic-change markers, shape, speed and distance leaders, player card | metrics `xg`, `player_totals`; tactics |
| Timeline | Goals, cards, subs, tactic changes; click to jump there | events, triggers |

Keys: space plays and pauses, ← → move 10 s. Links can open a moment:
`/?match=m001&t=4200&type=analyst` (t in seconds of play).

## Replay file

`scripts/build_replay.py` writes `web/public/replays/{match_id}.json` and updates `index.json`.

- **Positions:** 5 per second, in whole decimetres, with `-1` when a player is off the pitch.
- **Speeds:** once a second.
- **Other contents:** events, the final version of every number-only cue (withdrawn ones
  dropped), xG, totals every minute, tactics series, confirmed notes and triggers.
- **Time:** `t` is ms of play since kick-off, continuous across both halves.
- **Size:** about 7 MB for a full match, about 2 MB gzipped.
