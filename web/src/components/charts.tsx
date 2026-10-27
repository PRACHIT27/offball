// Small charts shared by the side panel.

const CW = 300;
const CH = 110;

/** Small time chart: x = play time (0 … now), one polyline per team.
 *  unit: "m" (metres), "%" (0–100) or anything else (plain numbers, 2 decimals). */
export function TimeChart({ title, unit, series, tEnd, total, markers }: {
  title: string;
  unit: string;
  series: { colour: string; points: [number, number][]; step?: boolean }[];
  tEnd: number;
  total: number;
  markers?: { t: number; label: string }[];
}) {
  const vals = series.flatMap((s) => s.points.map((p) => p[1]));
  const lo = unit === "m" ? Math.max(0, Math.min(...vals, 60) - 5) : 0;
  const hi = unit === "m" ? Math.max(...vals, 0) + 5 : unit === "%" ? 100
    : Math.max(0.5, ...vals) * 1.15;
  const fmt = (v: number) => (unit === "m" ? `${v.toFixed(0)} m` : unit === "%" ? `${v.toFixed(0)}%`
    : v.toFixed(2));
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
          <span key={i} style={{ color: series[i].colour }}>{v === undefined ? "–" : fmt(v)}</span>
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
