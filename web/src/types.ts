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
}

export interface MatchListing {
  match_id: string;
  storyline: string | null;
  title: string;
}

export type ViewerType = "casual" | "analyst";
