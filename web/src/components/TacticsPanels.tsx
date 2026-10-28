// Tactical Intelligence in the side panel (Audience LLD §7): before/after board, control vs
// chaos, pressing over time, passing network. All values come from the replay's tactics output.
import { useState } from "react";
import { clubName, lastIndex, latestWindow, surname } from "../replay";
import type { Replay, Side, TacticsItem } from "../types";
import { TEAM_COLOUR } from "./Pitch";
import { TimeChart } from "./charts";

const BOARD_SPAN_MS = 5 * 60_000; // compare 5 minutes before with up to 5 minutes after
const BOARD_MIN_AFTER_MS = 60_000; // show once there is a minute of "after"
const REASON: Record<string, string> = {
  red_card: "Red card", goal: "Goal", sub: "Substitution", shift: "Tactic change",
  player_change: "Position change",
};

function MiniPitch({ children }: { children?: React.ReactNode }) {
  return (
    <svg viewBox="-2 -2 109 72" className="mini">
      <rect x={0} y={0} width={105} height={68} className="mini-pitch" />
      <line x1={52.5} y1={0} x2={52.5} y2={68} className="mini-line" />
      <rect x={0} y={13.84} width={16.5} height={40.32} className="mini-line" />
      <rect x={88.5} y={13.84} width={16.5} height={40.32} className="mini-line" />
      {children}
    </svg>
  );
}

function series(r: Replay, club: string, key: string, from: number, to: number, scale = 1) {
  const pts: [number, number][] = [];
  for (const x of r.tactics) {
    if (x.t > to) break;
    if (x.kind === "series" && x.team_id === club && x.t >= from && typeof x.values[key] === "number") {
      pts.push([x.t, x.values[key] * scale]);
    }
  }
  return pts;
}

function mean(pts: [number, number][]): number | null {
  return pts.length ? pts.reduce((s, p) => s + p[1], 0) / pts.length : null;
}

/** What the board compares: a goal or red card if one happened in the last few minutes (they
 *  matter most), else the latest substitution or tactic change; needs a minute of "after". */
function boardTrigger(r: Replay, t: number): TacticsItem | null {
  let fallback: TacticsItem | null = null;
  for (let i = lastIndex(r.tactics, t - BOARD_MIN_AFTER_MS, (x) => x.t); i >= 0; i--) {
    const x = r.tactics[i];
    if (t - x.t > BOARD_SPAN_MS + 60_000) break;
    if (x.kind !== "trigger" || !x.team_id) continue;
    if (x.type === "crux" && (x.reason === "red_card" || x.reason === "goal")) return x;
    if (!fallback && ((x.type === "crux" && x.reason === "sub") || x.type === "shift")) fallback = x;
  }
  return fallback;
}

export function BeforeAfter({ replay: r, t }: { replay: Replay; t: number }) {
  const trig = boardTrigger(r, t);
  if (!trig) return null;
  const sides: Side[] = ["home", "away"];
  const rows = sides.map((side) => {
    const club = r[side].club_id;
    const before = (k: string, s = 1) => mean(series(r, club, k, trig.t - BOARD_SPAN_MS, trig.t, s));
    const after = (k: string, s = 1) => mean(series(r, club, k, trig.t, Math.min(t, trig.t + BOARD_SPAN_MS), s));
    const wBefore = latestWindow(r, club, trig.t);
    const wAfter = latestWindow(r, club, t);
    return { side, club,
      line: [before("line_height_m"), after("line_height_m")],
      press: [before("pressing_per_min"), after("pressing_per_min")],
      control: [before("control_share", 100), after("control_share", 100)],
      shape: [wBefore?.formation ?? null, wAfter?.formation ?? null] };
  });
  const x = (side: Side, lh: number | null) => (lh === null ? null : side === "home" ? lh : 105 - lh);
  const n = (v: number | null, d = 0) => (v === null ? "–" : v.toFixed(d));
  const who = clubName(r, trig.team_id);
  return (
    <section className="chart board">
      <h3>Before / after · {REASON[trig.reason] ?? trig.reason}{trig.player_id ? ` · ${surname(r, trig.player_id)}` : ""}</h3>
      <p className="chart-note muted">{who} · 5 minutes before vs {Math.round(Math.min(t - trig.t, BOARD_SPAN_MS) / 60_000)} after</p>
      <div className="board-pitches">
        {[0, 1].map((k) => (
          <div key={k}>
            <span className="board-label">{k === 0 ? "Before" : "After"}</span>
            <MiniPitch>
              {rows.map((row) => {
                const lx = x(row.side, row.line[k]);
                return lx === null ? null : (
                  <g key={row.side}>
                    <line x1={lx} y1={3} x2={lx} y2={65} stroke={TEAM_COLOUR[row.side]} strokeWidth={1.2}
                          strokeDasharray="3 2" />
                    <text x={lx + (row.side === "home" ? 1.5 : -1.5)} y={9} className="mini-label"
                          textAnchor={row.side === "home" ? "start" : "end"} fill={TEAM_COLOUR[row.side]}>
                      {row.line[k]!.toFixed(0)} m
                    </text>
                  </g>
                );
              })}
            </MiniPitch>
          </div>
        ))}
      </div>
      <table className="stat-table">
        <thead><tr><th /><th>Line</th><th>Pressing/min</th><th>Control</th><th>Shape</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.side} style={{ color: TEAM_COLOUR[row.side] }}>
              <td>{row.club}</td>
              <td>{n(row.line[0])} → {n(row.line[1])} m</td>
              <td>{n(row.press[0], 1)} → {n(row.press[1], 1)}</td>
              <td>{n(row.control[0])} → {n(row.control[1])}%</td>
              <td>{row.shape[0] ?? "–"} → {row.shape[1] ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function ControlAndPressing({ replay: r, t, total, markers }:
  { replay: Replay; t: number; total: number; markers: { t: number; label: string }[] }) {
  const sides: Side[] = ["home", "away"];
  const control = sides.map((side) => ({ colour: TEAM_COLOUR[side],
    points: series(r, r[side].club_id, "control_share", 0, t, 100) }));
  const pressing = sides.map((side) => ({ colour: TEAM_COLOUR[side],
    points: series(r, r[side].club_id, "pressing_per_min", 0, t) }));
  const chaos = series(r, r.home.club_id, "chaos", Math.max(0, t - 60_000), t);
  const chaosNow = chaos.length ? chaos[chaos.length - 1][1] : null;
  return (
    <>
      <TimeChart title="Control (share of play)" unit="%" series={control} tEnd={t} total={total} markers={markers} />
      {chaosNow !== null && (
        <div className="meter" title="Control vs chaos: 0 = calm build-up, 100 = end-to-end chaos">
          <span>Control</span>
          <div className="meter-bar"><i style={{ left: `${Math.min(100, Math.max(0, chaosNow))}%` }} /></div>
          <span>Chaos</span>
          <b>{chaosNow.toFixed(0)}</b>
        </div>
      )}
      <TimeChart title="Pressing (presses per minute)" unit="press" series={pressing} tEnd={t} total={total} markers={markers} />
    </>
  );
}

export function PassingNetwork({ replay: r, t }: { replay: Replay; t: number }) {
  const [side, setSide] = useState<Side>("home");
  const w = latestWindow(r, r[side].club_id, t);
  const net = w?.network as { nodes: Record<string, [number, number]>;
    edges: { from: string; to: string; passes: number; danger: number }[] } | undefined;
  if (!net || !Object.keys(net.nodes).length) return null;
  const maxPasses = Math.max(1, ...net.edges.map((e) => e.passes));
  return (
    <section className="chart">
      <h3>Passing network</h3>
      <div className="seg small" role="group" aria-label="Team">
        {(["home", "away"] as const).map((s) => (
          <button key={s} className={side === s ? "on" : ""} onClick={() => setSide(s)}>{r[s].club_id}</button>
        ))}
      </div>
      <MiniPitch>
        {net.edges.map((e, i) => {
          const a = net.nodes[e.from];
          const b = net.nodes[e.to];
          if (!a || !b) return null;
          return <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={TEAM_COLOUR[side]}
                       strokeWidth={0.6 + 2.6 * (e.passes / maxPasses)} opacity={0.35 + 0.5 * (e.passes / maxPasses)} />;
        })}
        {Object.entries(net.nodes).map(([pid, [nx, ny]]) => (
          <g key={pid}>
            <circle cx={nx} cy={ny} r={2.6} fill={TEAM_COLOUR[side]} stroke="#0f1512" strokeWidth={0.5} />
            <text x={nx} y={ny + 1.1} className="mini-num" textAnchor="middle">{r.players[pid]?.number ?? ""}</text>
          </g>
        ))}
      </MiniPitch>
      <p className="chart-note muted">Last 5 minutes · average positions in possession · line width = passes</p>
    </section>
  );
}
