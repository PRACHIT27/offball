import { useState } from "react";
import { heatAt, passingAt } from "../metrics";
import { lastIndex, latestWindow, surname } from "../replay";
import type { MetricsView, Replay } from "../types";
import { TimeChart } from "./charts";
import { TEAM_COLOUR } from "./Pitch";
import { BeforeAfter, ControlAndPressing, PassingNetwork } from "./TacticsPanels";

// Charts span kick-off to now (at least 15 minutes), so early minutes aren't squeezed
const MIN_SPAN_MS = 15 * 60_000;

/** Shot map on the whole pitch: dots sized by xG, goals filled. */
function ShotMap({ replay: r, metrics, t }: { replay: Replay; metrics: MetricsView; t: number }) {
  const shots = metrics.shots.filter((s) => s.t <= t && s.x !== null && s.y !== null);
  return (
    <section className="chart">
      <h3>Shot map</h3>
      <svg viewBox="-2 -2 109 72" className="shotmap">
        <rect x={0} y={0} width={105} height={68} className="mini-pitch" />
        <line x1={52.5} y1={0} x2={52.5} y2={68} className="mini-line" />
        <rect x={0} y={13.84} width={16.5} height={40.32} className="mini-line" />
        <rect x={88.5} y={13.84} width={16.5} height={40.32} className="mini-line" />
        {shots.map((s) => {
          const side = s.team === r.home.club_id ? "home" : "away";
          const radius = 1.2 + 6 * Math.sqrt(s.xg ?? 0);
          return (
            <circle key={s.id} cx={s.x!} cy={s.y!} r={radius}
                    fill={s.outcome === "goal" ? TEAM_COLOUR[side] : "none"}
                    stroke={TEAM_COLOUR[side]} strokeWidth={0.5} opacity={0.9}>
              <title>{`${surname(r, s.player)} · xG ${s.xg?.toFixed(2)} · ${s.outcome}${s.speed_kmh ? ` · ${s.speed_kmh.toFixed(0)} km/h` : ""}`}</title>
            </circle>
          );
        })}
      </svg>
      <p className="chart-note muted">Dot size is xG; filled dots are goals.</p>
    </section>
  );
}

function Passing({ replay: r, metrics, t }: { replay: Replay; metrics: MetricsView; t: number }) {
  const teams = passingAt(metrics, t);
  if (!teams) return null;
  return (
    <section className="chart">
      <h3>Passing</h3>
      <table className="stat-table">
        <thead><tr><th /><th>Passes</th><th>Accuracy</th><th>Expected</th><th>Difficulty</th></tr></thead>
        <tbody>
          {(["home", "away"] as const).map((side) => {
            const v = teams[r[side].club_id];
            if (!v) return null;
            return (
              <tr key={side} style={{ color: TEAM_COLOUR[side] }}>
                <td>{r[side].club_id}</td>
                <td>{v.attempts}</td>
                <td>{(v.accuracy * 100).toFixed(0)}%</td>
                <td>{((v.accuracy - v.completion_vs_expected / v.attempts) * 100).toFixed(0)}%</td>
                <td>{v.avg_difficulty.toFixed(0)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="chart-note muted">Expected: the accuracy the pass model predicts from distance, lane and pressure. Difficulty 0–100 per pass.</p>
    </section>
  );
}

/** A player's share of time in each 5 m cell, drawn on a mini pitch. */
function Heatmap({ grid }: { grid: number[][] }) {
  const max = Math.max(1, ...grid.flat());
  const cw = 105 / grid.length;
  const ch = 68 / grid[0].length;
  return (
    <svg viewBox="-1 -1 107 70" className="heatmap">
      <rect x={0} y={0} width={105} height={68} className="mini-pitch" />
      {grid.map((col, i) => col.map((v, j) => v > 0 && (
        <rect key={`${i}-${j}`} x={i * cw} y={j * ch} width={cw} height={ch}
              fill="var(--highlight)" opacity={Math.min(0.95, 0.12 + 0.85 * (v / max))} />
      )))}
      <line x1={52.5} y1={0} x2={52.5} y2={68} className="mini-line" />
    </svg>
  );
}

export function SidePanel({ replay: r, metrics, t, focus }: { replay: Replay; metrics: MetricsView | null; t: number; focus: string | null }) {
  const [heatSpan, setHeatSpan] = useState<"match" | "last_15">("match");
  const total = Math.max(t, MIN_SPAN_MS);
  const sides = ["home", "away"] as const;
  const xgPts = sides.map((side) => {
    const club = r[side].club_id;
    const pts: [number, number][] = [[0, 0]];
    for (const p of r.xg) if (p.team === club && p.t <= t) pts.push([p.t, p.total_xg]);
    return { colour: TEAM_COLOUR[side], points: pts, step: true };
  });
  const linePts = sides.map((side) => {
    const club = r[side].club_id;
    const pts: [number, number][] = [];
    for (const x of r.tactics) {
      if (x.t > t) break;
      if (x.kind === "series" && x.team_id === club && typeof x.values.line_height_m === "number") {
        pts.push([x.t, x.values.line_height_m]);
      }
    }
    return { colour: TEAM_COLOUR[side], points: pts };
  });
  const shifts = r.tactics.filter((x) => x.kind === "trigger" && x.type === "shift")
    .map((x) => ({ t: x.t, label: `${x.team_id} ${Object.keys(x.after)[0]}` }));
  const latestXg = sides.map((side) => {
    const pts = r.xg.filter((p) => p.team === r[side].club_id && p.t <= t);
    return pts[pts.length - 1];
  });

  const ti = lastIndex(r.totals, t, (x) => x.t);
  const totals = ti >= 0 ? r.totals[ti].players : {};
  const leaders = (key: "top_speed_ms" | "distance_m") =>
    Object.entries(totals).sort((a, b) => b[1][key] - a[1][key]).slice(0, 3);

  const shapes = sides.map((side) => latestWindow(r, r[side].club_id, t)?.formation);
  const card = focus ? totals[focus] : null;

  return (
    <aside className="side">
      {focus && (
        <section className="card">
          <h3>{r.players[focus]?.name} <small>#{r.players[focus]?.number} · {r.players[focus]?.position}</small></h3>
          {card ? (
            <dl>
              <dt>Distance</dt><dd>{(card.distance_m / 1000).toFixed(2)} km</dd>
              <dt>Top speed</dt><dd>{(card.top_speed_ms * 3.6).toFixed(1)} km/h</dd>
              <dt>Sprints</dt><dd>{card.sprints}</dd>
              <dt>Passes</dt><dd>{card.passes}{card.pass_accuracy !== null ? ` · ${(card.pass_accuracy * 100).toFixed(0)}%` : ""}</dd>
            </dl>
          ) : <p className="muted">No totals yet.</p>}
          {(() => {
            const heat = heatAt(metrics, focus, t);
            const grid = heat ? heat[heatSpan] : null;
            if (!heat) return null;
            return (
              <div className="heat-block">
                <div className="seg small" role="group" aria-label="Heatmap span">
                  <button className={heatSpan === "match" ? "on" : ""} onClick={() => setHeatSpan("match")}>Match</button>
                  <button className={heatSpan === "last_15" ? "on" : ""} onClick={() => setHeatSpan("last_15")}>Last 15'</button>
                </div>
                {grid ? <Heatmap grid={grid} /> : <p className="muted">No time on the pitch in this span.</p>}
              </div>
            );
          })()}
        </section>
      )}
      <BeforeAfter replay={r} t={t} />
      <TimeChart title="xG race" unit="xg" series={xgPts} tEnd={t} total={total} />
      <p className="chart-note">
        {latestXg.map((p, i) => p && <span key={i} style={{ color: TEAM_COLOUR[sides[i]] }}>{p.text}. </span>)}
      </p>
      {metrics && <ShotMap replay={r} metrics={metrics} t={t} />}
      {metrics && <Passing replay={r} metrics={metrics} t={t} />}
      <TimeChart title="Defensive line height" unit="m" series={linePts} tEnd={t} total={total} markers={shifts} />
      <ControlAndPressing replay={r} t={t} total={total} markers={shifts} />
      <PassingNetwork replay={r} t={t} />
      <section className="chart">
        <h3>Shape</h3>
        <div className="shapes">
          {sides.map((side, i) => (
            <span key={side} style={{ color: TEAM_COLOUR[side] }}>{r[side].club_id} {shapes[i] ?? "–"}</span>
          ))}
        </div>
      </section>
      <section className="chart leaders">
        <h3>Leaders</h3>
        <div className="cols">
          <ol>{leaders("top_speed_ms").map(([pid, v]) => (
            <li key={pid}><span>{surname(r, pid)}</span><b>{(v.top_speed_ms * 3.6).toFixed(1)} km/h</b></li>
          ))}</ol>
          <ol>{leaders("distance_m").map(([pid, v]) => (
            <li key={pid}><span>{surname(r, pid)}</span><b>{(v.distance_m / 1000).toFixed(2)} km</b></li>
          ))}</ol>
        </div>
      </section>
    </aside>
  );
}
