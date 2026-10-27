import { lastIndex, latestWindow, surname } from "../replay";
import type { Replay } from "../types";
import { TEAM_COLOUR } from "./Pitch";

const CW = 300;
const CH = 110;

/** Small time chart: x = play time (0 … now), one polyline per team. */
function TimeChart({ title, unit, series, tEnd, total, markers }: {
  title: string;
  unit: string;
  series: { colour: string; points: [number, number][]; step?: boolean }[];
  tEnd: number;
  total: number;
  markers?: { t: number; label: string }[];
}) {
  const vals = series.flatMap((s) => s.points.map((p) => p[1]));
  const lo = unit === "m" ? Math.max(0, Math.min(...vals, 60) - 5) : 0;
  const hi = unit === "m" ? Math.max(...vals, 0) + 5 : Math.max(0.5, ...vals) * 1.15;
  const x = (t: number) => (t / total) * CW;
  const y = (v: number) => CH - ((v - lo) / (hi - lo)) * CH;
  const path = (pts: [number, number][], step?: boolean) =>
    pts.map(([t, v], i) => {
      if (i === 0) return `M ${x(t)} ${y(v)}`;
      return step ? `H ${x(t)} V ${y(v)}` : `L ${x(t)} ${y(v)}`;
    }).join(" ");
  const latest = series.map((s) => s.points[s.points.length - 1]?.[1]);
  return (
    <section className="chart">
      <h3>{title}</h3>
      <div className="chart-readout">
        {latest.map((v, i) => (
          <span key={i} style={{ color: series[i].colour }}>{v === undefined ? "–" : `${v.toFixed(unit === "m" ? 0 : 2)}${unit === "m" ? " m" : ""}`}</span>
        ))}
      </div>
      <svg viewBox={`0 0 ${CW} ${CH}`} className="chart-svg" preserveAspectRatio="none">
        <line x1={x(tEnd)} y1={0} x2={x(tEnd)} y2={CH} className="now" />
        {markers?.filter((m) => m.t <= tEnd).map((m, i) => (
          <line key={i} x1={x(m.t)} y1={0} x2={x(m.t)} y2={CH} className="marker"><title>{m.label}</title></line>
        ))}
        {series.map((s, i) => (
          <path key={i} d={path(s.step && s.points.length ? [...s.points, [tEnd, s.points[s.points.length - 1][1]]] : s.points, s.step)}
                fill="none" stroke={s.colour} strokeWidth={2} vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
    </section>
  );
}

// Charts span kick-off to now (at least 15 minutes), so early minutes aren't squeezed
const MIN_SPAN_MS = 15 * 60_000;

export function SidePanel({ replay: r, t, focus }: { replay: Replay; t: number; focus: string | null }) {
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
        </section>
      )}
      <TimeChart title="xG race" unit="xg" series={xgPts} tEnd={t} total={total} />
      <p className="chart-note">
        {latestXg.map((p, i) => p && <span key={i} style={{ color: TEAM_COLOUR[sides[i]] }}>{p.text}. </span>)}
      </p>
      <TimeChart title="Defensive line height" unit="m" series={linePts} tEnd={t} total={total} markers={shifts} />
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
