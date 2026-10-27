import { clockLabel, scoreAt } from "../replay";
import type { MatchListing, Replay, ViewerType } from "../types";
import { TEAM_COLOUR } from "./Pitch";

interface Props {
  replay: Replay;
  matches: MatchListing[];
  t: number;
  period: number;
  clock: number;
  playing: boolean;
  speed: number;
  viewer: ViewerType;
  onMatch: (id: string) => void;
  onPlay: () => void;
  onSpeed: (s: number) => void;
  onViewer: (v: ViewerType) => void;
  onNextMoment: () => void;
}

export function TopBar(p: Props) {
  const [h, a] = scoreAt(p.replay, p.t);
  return (
    <header className="topbar">
      <div className="brand">Off<span>Ball</span></div>
      <div className="scoreboard" aria-live="polite">
        <span className="club"><i style={{ background: TEAM_COLOUR.home }} />{p.replay.home.name}</span>
        <span className="score">{h}<em>–</em>{a}</span>
        <span className="club"><i style={{ background: TEAM_COLOUR.away }} />{p.replay.away.name}</span>
        <span className="clock">{clockLabel(p.period, p.clock)}</span>
      </div>
      <div className="controls">
        <select value={p.replay.match_id} onChange={(e) => p.onMatch(e.target.value)} aria-label="Match">
          {p.matches.map((m) => (
            <option key={m.match_id} value={m.match_id}>
              {m.storyline ? m.storyline.replace(/_/g, " ") : m.match_id} · {m.title}
            </option>
          ))}
        </select>
        <div className="seg" role="group" aria-label="Viewer type">
          {(["casual", "analyst"] as const).map((v) => (
            <button key={v} className={p.viewer === v ? "on" : ""} onClick={() => p.onViewer(v)}>{v}</button>
          ))}
        </div>
        <button className="play" onClick={p.onPlay} aria-label={p.playing ? "Pause" : "Play"}>
          {p.playing ? "❚❚" : "▶"}
        </button>
        <div className="seg" role="group" aria-label="Speed">
          {[1, 5, 10].map((s) => (
            <button key={s} className={p.speed === s ? "on" : ""} onClick={() => p.onSpeed(s)}>{s}×</button>
          ))}
        </div>
        <button onClick={p.onNextMoment} title="Jump to the next key moment">Next moment ⏭</button>
      </div>
    </header>
  );
}
