import { lastIndex, surname } from "../replay";
import type { Replay, Side } from "../types";
import { TEAM_COLOUR } from "./Pitch";

const SIDES = ["home", "away"] as const;
const ON_TARGET = new Set(["goal", "saved"]);

function teamOf(r: Replay, pid: string): Side | null {
  return r.players[pid]?.team ?? null;
}

function totalsAt(r: Replay, t: number) {
  const i = lastIndex(r.totals, t, (x) => x.t);
  return i >= 0 ? r.totals[i].players : {};
}

function seriesValue(r: Replay, club: string, t: number, key: string): number | null {
  for (let i = lastIndex(r.tactics, t, (x) => x.t); i >= 0; i--) {
    const x = r.tactics[i];
    if (x.kind === "series" && x.team_id === club && typeof x.values?.[key] === "number") {
      return x.values[key];
    }
  }
  return null;
}

function teamOffBall(r: Replay, t: number, side: Side) {
  const mine = (pid: string | undefined) => !!pid && teamOf(r, pid) === side;
  const seen = r.cues.filter((c) => c.t <= t);
  const options = seen.filter((c) => c.kind === "best_option" && c.data.best?.open
    && mine(c.data.passer_id));
  return {
    decoyRuns: seen.filter((c) => c.kind === "decoy_run" && mine(c.data.runner_id)).length,
    freeMissed: options.filter((c) => c.data.chosen_id !== c.data.best.player_id).length,
  };
}

function teamStats(r: Replay, t: number, side: Side) {
  const club = r[side].club_id;
  const shots = r.events.filter((e) => e.type === "shot" && e.team === club && e.t <= t);
  const goals = shots.filter((e) => e.outcome === "goal").length;
  const xgPts = r.xg.filter((p) => p.team === club && p.t <= t);
  const xg = xgPts[xgPts.length - 1];
  const players = Object.entries(totalsAt(r, t)).filter(([pid]) => teamOf(r, pid) === side);
  const passes = players.reduce((a, [, v]) => a + v.passes, 0);
  const done = players.reduce((a, [, v]) => a + v.passes * (v.pass_accuracy ?? 0), 0);
  const distance = players.reduce((a, [, v]) => a + v.distance_m, 0);
  return { club, name: r[side].name, goals, shots: shots.length,
    onTarget: shots.filter((e) => ON_TARGET.has(e.outcome ?? "")).length,
    xg: xg?.total_xg ?? 0, xgText: xg?.text ?? "No chances yet", bigChances: xg?.big_chances ?? 0,
    pressing: seriesValue(r, club, t, "pressing_per_min"),
    line: seriesValue(r, club, t, "line_height_m"),
    control: seriesValue(r, club, t, "control_share"),
    ...teamOffBall(r, t, side),
    passes, accuracy: passes ? done / passes : null, distanceKm: distance / 1000, players };
}

function offBall(r: Replay, t: number, pid: string, sinceMs = 0) {
  const recent = r.cues.filter((c) => c.t <= t && c.t >= sinceMs);
  const runs = recent.filter((c) => c.kind === "decoy_run" && c.data.runner_id === pid);
  const freed = new Set(runs.map((c) => c.data.receiver_id).filter(Boolean));
  const pulled = runs.reduce((a, c) => a + (c.data.pulled?.length ?? 0), 0);
  const free = recent.filter((c) => c.kind === "best_option" && c.data.best?.open
    && c.data.best?.player_id === pid && c.data.chosen_id !== pid).length;
  const found = recent.filter((c) => c.kind === "best_option" && c.data.chosen_id === pid).length;
  return { runs: runs.length, pulled, freed: [...freed].map((p) => surname(r, p)), free, found };
}

const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}%`);
const perMin = (v: number | null) => (v === null ? "–" : `${v.toFixed(1)}/min`);
const metres = (v: number | null) => (v === null ? "–" : `${v.toFixed(0)} m`);

function Bar({ label, home, away, fmt = (v: number) => v.toFixed(0) }:
  { label: string; home: number; away: number; fmt?: (v: number) => string }) {
  const total = home + away || 1;
  return (
    <div className="mode-bar">
      <div className="mode-bar-head"><b style={{ color: TEAM_COLOUR.home }}>{fmt(home)}</b>
        <span>{label}</span><b style={{ color: TEAM_COLOUR.away }}>{fmt(away)}</b></div>
      <div className="mode-bar-track">
        <div style={{ width: `${(100 * home) / total}%`, background: TEAM_COLOUR.home }} />
        <div style={{ width: `${(100 * away) / total}%`, background: TEAM_COLOUR.away }} />
      </div>
    </div>
  );
}

export function CasualStats({ replay: r, t }: { replay: Replay; t: number }) {
  const [h, a] = SIDES.map((s) => teamStats(r, t, s));
  const all = Object.entries(totalsAt(r, t));
  const runner = all.sort((x, y) => y[1].distance_m - x[1].distance_m)[0];
  const quickest = [...all].sort((x, y) => y[1].top_speed_ms - x[1].top_speed_ms)[0];
  return (
    <section className="card mode-card">
      <h3>The match so far</h3>
      <Bar label="Shots" home={h.shots} away={a.shots} />
      <Bar label="On target" home={h.onTarget} away={a.onTarget} />
      <Bar label="Share of passes" home={h.passes} away={a.passes}
           fmt={(v) => `${Math.round((100 * v) / (h.passes + a.passes || 1))}%`} />
      <p className="mode-note"><b style={{ color: TEAM_COLOUR.home }}>{h.name}:</b> {h.xgText}.</p>
      <p className="mode-note"><b style={{ color: TEAM_COLOUR.away }}>{a.name}:</b> {a.xgText}.</p>
      {runner && <p className="mode-note">Running the most: <b>{surname(r, runner[0])}</b>, {(runner[1].distance_m / 1000).toFixed(1)} km.</p>}
      {quickest && <p className="mode-note">Quickest: <b>{surname(r, quickest[0])}</b>, {(quickest[1].top_speed_ms * 3.6).toFixed(1)} km/h.</p>}
    </section>
  );
}

export function SupporterStats({ replay: r, t, club }: { replay: Replay; t: number; club: Side }) {
  const other: Side = club === "home" ? "away" : "home";
  const mine = teamStats(r, t, club);
  const theirs = teamStats(r, t, other);
  const best = (players: typeof mine.players) =>
    [...players].sort((x, y) => (y[1].xg - x[1].xg) || (y[1].distance_m - x[1].distance_m))[0];
  const star = best(mine.players);
  const danger = best(theirs.players);
  const workhorse = [...mine.players].sort((x, y) => y[1].distance_m - x[1].distance_m)[0];
  const freeMan = mine.players.map(([pid]) => [pid, offBall(r, t, pid, t - 15 * 60_000).free] as const)
    .sort((x, y) => y[1] - x[1])[0];
  const row = (label: string, a: string, b: string) => (
    <tr><td>{label}</td><td style={{ color: TEAM_COLOUR[club] }}>{a}</td><td style={{ color: TEAM_COLOUR[other] }}>{b}</td></tr>
  );
  return (
    <section className="card mode-card" style={{ borderColor: TEAM_COLOUR[club] }}>
      <h3 style={{ color: TEAM_COLOUR[club] }}>{mine.name}</h3>
      <table className="stat-table">
        <thead><tr><th>Attack</th><th>{mine.club}</th><th>{theirs.club}</th></tr></thead>
        <tbody>
          {row("Goals", `${mine.goals}`, `${theirs.goals}`)}
          {row("Shots (on target)", `${mine.shots} (${mine.onTarget})`, `${theirs.shots} (${theirs.onTarget})`)}
          {row("xG", mine.xg.toFixed(2), theirs.xg.toFixed(2))}
          {row("Big chances", `${mine.bigChances}`, `${theirs.bigChances}`)}
          {row("Decoy runs", `${mine.decoyRuns}`, `${theirs.decoyRuns}`)}
          {row("Free man missed", `${mine.freeMissed}`, `${theirs.freeMissed}`)}
          {row("Pass accuracy", pct(mine.accuracy), pct(theirs.accuracy))}
        </tbody>
      </table>
      <table className="stat-table">
        <thead><tr><th>Defence</th><th>{mine.club}</th><th>{theirs.club}</th></tr></thead>
        <tbody>
          {row("Shots conceded", `${theirs.shots} (${theirs.onTarget})`, `${mine.shots} (${mine.onTarget})`)}
          {row("xG conceded", theirs.xg.toFixed(2), mine.xg.toFixed(2))}
          {row("Pressing", perMin(mine.pressing), perMin(theirs.pressing))}
          {row("Defensive line", metres(mine.line), metres(theirs.line))}
          {row("Control of play", pct(mine.control), pct(theirs.control))}
          {row("Ground covered", `${mine.distanceKm.toFixed(1)} km`, `${theirs.distanceKm.toFixed(1)} km`)}
        </tbody>
      </table>
      {star && <p className="mode-note">Our standout: <b>{surname(r, star[0])}</b>{star[1].xg >= 0.05 ? `, xG ${star[1].xg.toFixed(2)}` : ""}, {(star[1].distance_m / 1000).toFixed(1)} km.</p>}
      {workhorse && workhorse[0] !== star?.[0] && <p className="mode-note">Hardest worker: <b>{surname(r, workhorse[0])}</b>, {(workhorse[1].distance_m / 1000).toFixed(1)} km.</p>}
      {freeMan && freeMan[1] > 0 && <p className="mode-note">Keeps getting free: <b>{surname(r, freeMan[0])}</b>, open {freeMan[1]} times in 15' without the pass.</p>}
      {danger && danger[1].xg >= 0.05 && <p className="mode-note">Their danger man: <b>{surname(r, danger[0])}</b>, xG {danger[1].xg.toFixed(2)}.</p>}
      <p className="mode-note muted">{mine.xgText}.</p>
    </section>
  );
}

export function PlayerOffBall({ replay: r, t, pid }: { replay: Replay; t: number; pid: string }) {
  const all = offBall(r, t, pid);
  const last15 = offBall(r, t, pid, t - 15 * 60_000);
  const me = totalsAt(r, t)[pid];
  const side = teamOf(r, pid);
  const mates = Object.entries(totalsAt(r, t)).filter(([p]) => teamOf(r, p) === side);
  const rank = me ? 1 + mates.filter(([, v]) => v.distance_m > me.distance_m).length : null;
  return (
    <section className="card mode-card">
      <h3>Off the ball</h3>
      <dl>
        <dt>Decoy runs</dt><dd>{all.runs}{last15.runs ? ` · ${last15.runs} in last 15'` : ""}</dd>
        <dt>Defenders pulled</dt><dd>{all.pulled}</dd>
        <dt>Teammates freed</dt><dd>{all.freed.length ? all.freed.slice(0, 3).join(", ") : "–"}</dd>
        <dt>Free, not found</dt><dd>{all.free}{last15.free ? ` · ${last15.free} in last 15'` : ""}</dd>
        <dt>Picked out as the pass</dt><dd>{all.found}</dd>
        {me && rank && <><dt>Ground covered</dt><dd>{(me.distance_m / 1000).toFixed(2)} km · #{rank} in the team</dd></>}
        {me && me.xg > 0 && <><dt>xG</dt><dd>{me.xg.toFixed(2)}</dd></>}
      </dl>
    </section>
  );
}
