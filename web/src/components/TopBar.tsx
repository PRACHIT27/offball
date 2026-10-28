import { clockLabel, scoreAt } from "../replay";
import type { Language, MatchListing, Replay, Side, ViewerType } from "../types";
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
  club: Side;
  fourWays: boolean;
  lang: Language;
  onMatch: (id: string) => void;
  onPlay: () => void;
  onSpeed: (s: number) => void;
  onViewer: (v: ViewerType) => void;
  onClub: (c: Side) => void;
  onFourWays: (on: boolean) => void;
  onLang: (l: Language) => void;
  onNextMoment: () => void;
}

const VIEWERS: [ViewerType, string][] = [
  ["casual", "Casual"], ["analyst", "Analyst"], ["supporter", "Supporter"], ["player", "Player"],
];

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
          {VIEWERS.map(([v, label]) => (
            <button key={v} className={!p.fourWays && p.viewer === v ? "on" : ""}
                    onClick={() => { p.onFourWays(false); p.onViewer(v); }}>{label}</button>
          ))}
          <button className={p.fourWays ? "on" : ""} onClick={() => p.onFourWays(!p.fourWays)}
                  title="The same moment for four viewer types">Four ways</button>
        </div>
        {(p.viewer === "supporter" || p.fourWays) && (
          <div className="seg" role="group" aria-label="Club you support">
            {(["home", "away"] as const).map((side) => (
              <button key={side} className={p.club === side ? "on" : ""} onClick={() => p.onClub(side)}>
                <i className="dot" style={{ background: TEAM_COLOUR[side] }} />{p.replay[side].club_id}
              </button>
            ))}
          </div>
        )}
        <div className="seg lang" role="group" aria-label="Caption language">
          {(["en", "es", "hi"] as const).map((l) => (
            <button key={l} className={p.lang === l ? "on" : ""} onClick={() => p.onLang(l)}>{l}</button>
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
