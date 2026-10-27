// The replay file written by scripts/build_replay.py ("offball-replay/1").
// Positions are whole decimetres, -1 when a player is off the pitch.

export type Side = "home" | "away";

export interface Club {
  club_id: string;
  name: string;
}

export interface PlayerInfo {
  name: string;
  number: number;
  position: string;
  team: Side;
}

/** [t, period, clock, ballX, ballY, positions] */
export type Frame = [number, number, number, number, number, number[]];

export interface MatchEvent {
  id: string;
  t: number;
  type: string;
  period: number;
  clock: number;
  team: string | null;
  player: string | null;
  outcome: string | null;
  target: string | null;
}

export interface Cue {
  t: number;
  id: string;
  kind: string;
  duration_ms: number;
  data: Record<string, any>;
  evidence: { event_ids: string[]; frames: number[] };
}

export interface XgPoint {
  t: number;
  team: string;
  total_xg: number;
  range: [number, number];
  shots: number;
  big_chances: number;
  text: string;
}

export interface TotalsPoint {
  t: number;
  players: Record<string, { distance_m: number; top_speed_ms: number; sprints: number;
    passes: number; pass_accuracy: number | null; xg: number }>;
}

export interface TacticsItem {
  t: number;
  kind: "series" | "note" | "trigger" | "window";
  team_id: string | null;
  period: number;
  at_ms: number;
  [key: string]: any;
}

export interface Replay {
  schema: string;
  match_id: string;
  storyline: string | null;
  home: Club;
  away: Club;
  managers: Record<Side, string | null>;
  players: Record<string, PlayerInfo>;
  order: string[];
  periods: Record<string, { t0: number; t1: number }>;
  frames: Frame[];
  speeds: [number, number[]][];
  events: MatchEvent[];
  cues: Cue[];
  xg: XgPoint[];
  totals: TotalsPoint[];
  tactics: TacticsItem[];
  /** Insight Generation output (absent in replays built before it existed). */
  insights?: Insight[];
}

export type Language = "en" | "es" | "hi";

export interface Insight {
  t: number;
  insight_id: string;
  trigger_id: string;
  kind: "expect" | "confirmed" | "retracted" | "shift" | "check_in" | "summary" | "external";
  team_id: string | null;
  /** Keyed `{viewer_type}.{language}`, e.g. `analyst.es`. */
  captions: Record<string, string>;
  evidence: { event_ids: string[]; window_ids: string[] };
  caption_source: "agent" | "template";
}

export interface MatchListing {
  match_id: string;
  storyline: string | null;
  title: string;
}

export type ViewerType = "casual" | "analyst";

/** Performance Metrics side file (`{match_id}.metrics.json`, scripts/build_metrics_view.py). */
export interface MetricsView {
  schema: string;
  match_id: string;
  order: string[];
  heat: {
    grid: [number, number];
    /** Per-mille shares of each player's frames per 5 m cell, every 5 minutes. */
    snapshots: { t: number; players: Record<string, { match: number[][]; last_15: number[][] | null }> }[];
  };
  shots: { t: number; id: string; team: string; player: string; x: number | null; y: number | null;
    xg: number | null; speed_kmh: number | null; outcome: string }[];
  passing: { t: number; teams: Record<string, { attempts: number; accuracy: number;
    avg_difficulty: number; completion_vs_expected: number }> }[];
  /** [t, pressure 0–100 per player in `order`, -1 when off the pitch], once a second. */
  pressure: [number, number[]][];
  /** [t, ball speed km/h], 5 per second (absent in side files built before it existed). */
  ball?: [number, number][];
  /** Per pass event: open options and decision score (PM-16, PM-17). */
  passes?: Record<string, { open_options: number | null; decision_score: number | null }>;
  cues: { t: number; kind: string; duration_ms: number; anchor: { x: number; y: number } | null;
    data: Record<string, any> }[];
}
