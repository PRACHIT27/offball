import { clubName, surname } from "../replay";
import type { Replay } from "../types";

export interface Moment {
  t: number;
  kind: "goal" | "red" | "yellow" | "sub" | "shift" | "insight";
  label: string;
}

export function moments(r: Replay): Moment[] {
  const out: Moment[] = [];
  for (const e of r.events) {
    if (e.type === "shot" && e.outcome === "goal") out.push({ t: e.t, kind: "goal", label: `Goal · ${surname(r, e.player)} (${e.team})` });
    else if (e.type === "card") out.push({ t: e.t, kind: e.outcome === "red" ? "red" : "yellow", label: `${e.outcome} card · ${surname(r, e.player)}` });
    else if (e.type === "sub_on") out.push({ t: e.t, kind: "sub", label: `Sub · ${surname(r, e.player)} on` });
  }
  for (const x of r.tactics) {
    if (x.kind === "trigger" && x.type === "shift") {
      const key = Object.keys(x.after)[0];
      const what = key === "player_position"
        ? `${x.player_id ? surname(r, x.player_id) : "a player"} moves position`
        : `${key?.replace(/_m$/, "").replace(/_/g, " ")} changed`;
      out.push({ t: x.t, kind: "shift", label: `${clubName(r, x.team_id)}: ${what}` });
    }
  }
  // Insight Generation's explanations, as small markers under the key moments
  for (const x of r.insights ?? []) {
    const text = x.captions["analyst.en"] ?? x.captions["casual.en"] ?? x.kind;
    out.push({ t: x.t, kind: "insight", label: `Insight · ${text.length > 110 ? `${text.slice(0, 107)}…` : text}` });
  }
  return out.sort((a, b) => a.t - b.t);
}

export function Timeline({ replay: r, t, onSeek }: { replay: Replay; t: number; onSeek: (t: number) => void }) {
  const total = r.periods["2"].t1 || 1;
  const half = r.periods["1"].t1 / total;
  const ms = moments(r);
  return (
    <div className="timeline">
      <div className="track" onClick={(e) => {
        const box = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
        onSeek(((e.clientX - box.left) / box.width) * total);
      }}>
        <div className="played" style={{ width: `${(t / total) * 100}%` }} />
        <div className="half" style={{ left: `${half * 100}%` }} title="Half-time" />
        {ms.map((m, i) => (
          <button key={i} className={`moment ${m.kind}`} style={{ left: `${(m.t / total) * 100}%` }}
                  title={m.label} aria-label={m.label}
                  onClick={(e) => { e.stopPropagation(); onSeek(Math.max(0, m.t - 3000)); }} />
        ))}
      </div>
      <div className="legend">
        <span className="goal">Goal</span><span className="red">Red card</span><span className="yellow">Yellow</span>
        <span className="sub">Sub</span><span className="shift">Tactic change</span>
        <span className="insight">Insight</span>
      </div>
    </div>
  );
}
