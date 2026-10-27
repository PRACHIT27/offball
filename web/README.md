# OffBall viewer screen

**Live:** https://jolly-cliff-0ccede51e.4.azurestaticapps.net
(red card at 70': https://jolly-cliff-0ccede51e.4.azurestaticapps.net/?match=m001&t=4300&type=analyst)

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

## Performance Metrics view

`{match_id}.metrics.json` sits next to each replay, written by `scripts/build_metrics_view.py`. It
is optional: the screen works without it. It adds:
- **Pitch:** the ball carrier's pressure from metrics (a dashed ring at ≥ 0.75, and the value in
  analyst view); shot-speed and distance-milestone badges; ball speed by the ball while it travels
  (analyst view); open options in each pass arc's label.
- **Side panel:** a shot map (dot size = xG, filled = goal), and passing per team (accuracy, the
  pass model's expected accuracy, average difficulty).
- **Player card:** a 21 × 14 heatmap, for the whole match or the last 15 minutes.

```sh
PYTHONPATH=. python scripts/build_metrics_view.py --storyline red_card --match m001
```

It re-simulates the storyline (deterministic, so the same match as the replay) and never touches
`{match_id}.json`, which also holds Insight Generation's captions.

## Replay file

`scripts/build_replay.py` writes `web/public/replays/{match_id}.json` and updates `index.json`.

- **Positions:** 5 per second, in whole decimetres, with `-1` when a player is off the pitch.
- **Speeds:** once a second.
- **Other contents:** events, the final version of every number-only cue (withdrawn ones
  dropped), xG, totals every minute, tactics series, confirmed notes and triggers.
- **Time:** `t` is ms of play since kick-off, continuous across both halves.
- **Size:** about 7 MB for a full match, about 2 MB gzipped.

## Deploy (Azure Static Web Apps)

Static Web App `offball-web` (Free) in `offball-rg`. `public/staticwebapp.config.json` sets:
- the fallback to `index.html`, so share links work;
- caching: replays 1 h, hashed assets for good.

Responses are brotli-compressed, so a 7 MB replay comes over as about 2 MB.

By hand (needs `az login` on the subscription; the token is never printed or saved):

```sh
cd web && npm ci && npm run build
SWA_TOKEN=$(az staticwebapp secrets list -n offball-web -g offball-rg --query properties.apiKey -o tsv)
npx @azure/static-web-apps-cli@2 deploy ./dist --deployment-token "$SWA_TOKEN" --env production
```

Automatically: `.github/workflows/web.yml` builds on every PR and deploys on pushes to `main`,
once a repo admin adds the secret `AZURE_STATIC_WEB_APPS_API_TOKEN` (the command is in the
workflow file).
