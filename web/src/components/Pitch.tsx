import { ballSpeedAt, metricCuesAt, PRESS_RING, pressureAt } from "../metrics";
import { activeCues, latestSeries, snapshotAt, speedsAt, surname } from "../replay";
import type { MetricsView, Replay, ViewerType } from "../types";

const L = 105;
const FAST_TAG_KMH = 20;
const W = 68;
export const TEAM_COLOUR = { home: "#f3efe4", away: "#ff7a59" } as const;
const TEAM_INK = { home: "#13201a", away: "#1a0f0b" } as const;

function difficultyColour(d: number): string {
  if (d < 35) return "#5fbf8a";
  if (d < 65) return "#e8a24f";
  return "#e5484d";
}

function Markings() {
  const line = { fill: "none", stroke: "var(--pitch-line)", strokeWidth: 0.25 };
  const box = (x: number, w: number, h: number) => (
    <rect x={x} y={(W - h) / 2} width={w} height={h} {...line} />
  );
  return (
    <g>
      <rect x={0} y={0} width={L} height={W} fill="var(--pitch)" />
      {Array.from({ length: 10 }, (_, i) => (
        <rect key={i} x={i * 10.5} y={0} width={10.5} height={W}
              fill={i % 2 ? "rgba(255,255,255,0.025)" : "transparent"} />
      ))}
      <rect x={0} y={0} width={L} height={W} {...line} />
      <line x1={L / 2} y1={0} x2={L / 2} y2={W} {...line} />
      <circle cx={L / 2} cy={W / 2} r={9.15} {...line} />
      <circle cx={L / 2} cy={W / 2} r={0.3} fill="var(--pitch-line)" />
      {box(0, 16.5, 40.32)}
      {box(L - 16.5, 16.5, 40.32)}
      {box(0, 5.5, 18.32)}
      {box(L - 5.5, 5.5, 18.32)}
      <circle cx={11} cy={W / 2} r={0.3} fill="var(--pitch-line)" />
      <circle cx={L - 11} cy={W / 2} r={0.3} fill="var(--pitch-line)" />
      <path d={`M 16.5 ${W / 2 - 7.3} A 9.15 9.15 0 0 1 16.5 ${W / 2 + 7.3}`} {...line} />
      <path d={`M ${L - 16.5} ${W / 2 - 7.3} A 9.15 9.15 0 0 0 ${L - 16.5} ${W / 2 + 7.3}`} {...line} />
      <rect x={-1.6} y={W / 2 - 3.66} width={1.6} height={7.32} {...line} />
      <rect x={L} y={W / 2 - 3.66} width={1.6} height={7.32} {...line} />
    </g>
  );
}

interface Props {
  replay: Replay;
  metrics: MetricsView | null;
  t: number;
  viewer: ViewerType;
  focus: string | null;
  onPickPlayer: (pid: string) => void;
}

export function Pitch({ replay: r, metrics, t, viewer, focus, onPickPlayer }: Props) {
  const snap = snapshotAt(r, t);
  if (!snap) return <svg className="pitch" viewBox={`-3 -3 ${L + 6} ${W + 6}`} />;
  const speeds = speedsAt(r, t);
  const cues = activeCues(r, t);
  const arc = cues.find((c) => c.kind === "pass_arc");
  const ghost = cues.find((c) => c.kind === "best_option");
  const decoy = cues.find((c) => c.kind === "decoy_run");
  const alerts = cues.filter((c) => c.kind === "speed_alert");
  // From the metrics side file: pressure on every player, shot speeds, distance milestones
  const pressure = pressureAt(metrics, t);
  const extra = metricCuesAt(metrics, t);
  const ballKmh = ballSpeedAt(metrics, t);

  // Pressure rings: opponents within 2 m of the ball carrier (pressure ≥ 0.75)
  let carrier: string | null = null;
  const pressers: string[] = [];
  if (snap.ball) {
    let best = 1.5;
    snap.players.forEach(([x, y], pid) => {
      const d = Math.hypot(x - snap.ball![0], y - snap.ball![1]);
      if (d < best) { best = d; carrier = pid; }
    });
    if (carrier) {
      const [cx, cy] = snap.players.get(carrier)!;
      const team = r.players[carrier]?.team;
      snap.players.forEach(([x, y], pid) => {
        if (r.players[pid]?.team !== team && Math.hypot(x - cx, y - cy) <= 2) pressers.push(pid);
      });
    }
  }

  const lines = (["home", "away"] as const).map((side) => {
    const club = r[side].club_id;
    const s = latestSeries(r, club, t);
    const lh = s?.values?.line_height_m;
    if (typeof lh !== "number" || s!.period !== snap.period) return null;
    const x = side === "home" ? lh : L - lh;
    return { side, x, lh, club };
  });

  return (
    <svg className="pitch" viewBox={`-3 -3 ${L + 6} ${W + 6}`} role="img"
         aria-label={`${r.home.name} v ${r.away.name}, live positions`}>
      <Markings />

      {lines.map((ln) => ln && (
        <g key={ln.side} className="def-line" opacity={viewer === "analyst" ? 0.9 : 0.55}>
          <line x1={ln.x} y1={1.5} x2={ln.x} y2={W - 1.5} stroke={TEAM_COLOUR[ln.side]}
                strokeWidth={0.22} strokeDasharray="1 0.8" />
          <text x={ln.x + (ln.side === "home" ? 0.6 : -0.6)} y={2.6} className="line-label"
                textAnchor={ln.side === "home" ? "start" : "end"} fill={TEAM_COLOUR[ln.side]}>
            {ln.club} line {ln.lh.toFixed(0)} m
          </text>
        </g>
      ))}

      {decoy && (
        <g className="overlay">
          <path d={`M ${decoy.data.path[0][0]} ${decoy.data.path[0][1]} L ${decoy.data.path[1][0]} ${decoy.data.path[1][1]}`}
                stroke="var(--highlight)" strokeWidth={0.35} fill="none" markerEnd="url(#arrow)" />
          {Object.entries(decoy.data.defenders as Record<string, number[][]>).map(([pid, [a, b]]) => (
            <path key={pid} d={`M ${a[0]} ${a[1]} L ${b[0]} ${b[1]}`} stroke="var(--highlight)"
                  strokeWidth={0.2} strokeDasharray="0.6 0.5" fill="none" markerEnd="url(#arrow)" />
          ))}
        </g>
      )}

      {arc && (() => {
        const [x1, y1] = arc.data.start;
        const [x2, y2] = arc.data.end;
        const mx = (x1 + x2) / 2 - (y2 - y1) * 0.15;
        const my = (y1 + y2) / 2 + (x2 - x1) * 0.15;
        const age = (t - arc.t) / arc.duration_ms;
        return (
          <g className="overlay" opacity={Math.max(0, 1 - age * age)}>
            <path d={`M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`} fill="none"
                  stroke={difficultyColour(arc.data.difficulty)} strokeWidth={0.4}
                  strokeDasharray={arc.data.completed ? undefined : "1 0.7"} markerEnd="url(#arrow)" />
            <text x={mx} y={my - 1} className="arc-label" textAnchor="middle">
              {arc.data.distance_m?.toFixed(0)} m · {arc.data.speed_ms ? `${(arc.data.speed_ms * 3.6).toFixed(0)} km/h · ` : ""}difficulty {arc.data.difficulty}
              {(() => {
                const open = metrics?.passes?.[arc.evidence.event_ids[0]]?.open_options;
                return typeof open === "number" ? ` · ${open} open option${open === 1 ? "" : "s"}` : "";
              })()}
            </text>
          </g>
        );
      })()}

      {ghost && viewer === "analyst" && (
        <g className="overlay ghost">
          <path d={`M ${snap.players.get(ghost.data.passer_id)?.[0] ?? 0} ${snap.players.get(ghost.data.passer_id)?.[1] ?? 0} L ${ghost.data.best.x} ${ghost.data.best.y}`}
                stroke="#cfe8d9" strokeWidth={0.3} strokeDasharray="0.8 0.6" fill="none" markerEnd="url(#arrow)" />
          <text x={ghost.data.best.x} y={ghost.data.best.y - 2.2} className="arc-label" textAnchor="middle">
            better option · decision {ghost.data.decision_score.toFixed(2)}
          </text>
        </g>
      )}

      {carrier && pressure?.has(carrier) && (() => {
        const p = snap.players.get(carrier)!;
        const v = pressure.get(carrier)!;
        return (
          <g className="overlay">
            {v >= PRESS_RING && <circle cx={p[0]} cy={p[1]} r={3.2} className="press-ring under" />}
            {viewer === "analyst" && v > 0 && (
              <text x={p[0]} y={p[1] - 2.2} className="arc-label" textAnchor="middle">
                pressure {(v / 100).toFixed(2)}
              </text>
            )}
          </g>
        );
      })()}

      {extra.map((c, i) => c.anchor && (
        <g key={`m-${i}`} className="overlay metric-cue">
          <rect x={c.anchor.x - 6} y={c.anchor.y - 6.2} width={12} height={2.6} rx={0.6} />
          <text x={c.anchor.x} y={c.anchor.y - 4.4} textAnchor="middle">
            {c.kind === "shot_speed"
              ? `Shot ${c.data.speed_kmh?.toFixed(0)} km/h · xG ${c.data.xg?.toFixed(2)}`
              : `${surname(r, c.data.player_id)}: ${(c.data.distance_m / 1000).toFixed(0)} km covered`}
          </text>
        </g>
      ))}

      {pressers.map((pid) => {
        const p = snap.players.get(pid)!;
        return <circle key={`ring-${pid}`} cx={p[0]} cy={p[1]} r={2.4} className="press-ring" />;
      })}

      {[...snap.players.entries()].map(([pid, [x, y]]) => {
        const info = r.players[pid];
        const side = info?.team ?? "home";
        const alert = alerts.find((a) => a.data.player_id === pid);
        const focused = focus === pid;
        return (
          <g key={pid} className="player" onClick={() => onPickPlayer(pid)}>
            {focused && <circle cx={x} cy={y} r={2.2} className="focus-ring" />}
            <circle cx={x} cy={y} r={1.25} fill={TEAM_COLOUR[side]}
                    stroke={pid === carrier ? "var(--highlight)" : "rgba(0,0,0,0.45)"}
                    strokeWidth={pid === carrier ? 0.35 : 0.15} />
            <text x={x} y={y + 0.45} className="shirt" fill={TEAM_INK[side]} textAnchor="middle">
              {info?.number ?? ""}
            </text>
            {(() => {
              // Name tags: always for the focused player and on alerts; for everyone in analyst
              // view, with the speed only while they are really running
              const kmh = alert ? alert.data.speed_kmh : speeds.get(pid) ?? 0;
              if (!(viewer === "analyst" || focused || alert)) return null;
              const fast = alert || kmh >= FAST_TAG_KMH;
              return (
                <text x={x} y={y + 2.9} className={`tag${fast ? " fast" : ""}`} textAnchor="middle">
                  {surname(r, pid)}{fast ? ` · ${kmh.toFixed(0)} km/h` : ""}
                </text>
              );
            })()}
          </g>
        );
      })}

      {snap.ball && <circle cx={snap.ball[0]} cy={snap.ball[1]} r={0.6} className="ball" />}
      {/* Ball speed only while it travels: at a player's feet the pressure label sits there */}
      {snap.ball && viewer === "analyst" && !carrier && ballKmh !== null && ballKmh >= 20 && (
        <text x={snap.ball[0]} y={snap.ball[1] - 1.2} className="ball-speed" textAnchor="middle">
          {ballKmh} km/h
        </text>
      )}

      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4"
                orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 z" fill="context-stroke" />
        </marker>
      </defs>
    </svg>
  );
}
