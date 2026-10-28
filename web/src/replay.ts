// Reading a replay at any moment t (ms of play since kick-off, continuous across halves).
import type { CaptionVoice, Cue, Language, Replay, Side, TacticsItem, ViewerType } from "./types";

export interface Snapshot {
  period: number;
  clock: number;
  ball: [number, number] | null;
  players: Map<string, [number, number]>;
}

/** Index of the last item with item.t <= t (or -1). Items are sorted by t. */
export function lastIndex<T>(items: T[], t: number, key: (x: T) => number): number {
  let lo = 0;
  let hi = items.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (key(items[mid]) <= t) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found;
}

const MAX_GAP_MS = 1000; // don't glide players across a gap in the frames

/** Positions at t, interpolated between the 5-per-second frames. */
export function snapshotAt(r: Replay, t: number): Snapshot | null {
  const i = lastIndex(r.frames, t, (f) => f[0]);
  if (i < 0) return null;
  const a = r.frames[i];
  const b = r.frames[i + 1];
  const s = b && b[1] === a[1] && b[0] - a[0] <= MAX_GAP_MS ? (t - a[0]) / (b[0] - a[0]) : 0;
  const mix = (u: number, v: number) => (v < 0 ? u : u + (v - u) * s) / 10;
  const players = new Map<string, [number, number]>();
  r.order.forEach((pid, c) => {
    const x = a[5][2 * c];
    if (x === undefined || x < 0) return;
    const y = a[5][2 * c + 1];
    const bx = b?.[5][2 * c] ?? -1;
    const by = b?.[5][2 * c + 1] ?? -1;
    players.set(pid, [mix(x, bx), mix(y, by)]);
  });
  const ball: [number, number] | null =
    a[3] < 0 ? null : [mix(a[3], b?.[3] ?? -1), mix(a[4], b?.[4] ?? -1)];
  return { period: a[1], clock: a[2] + (b && s ? (b[2] - a[2]) * s : 0), ball, players };
}

export function speedsAt(r: Replay, t: number): Map<string, number> {
  const out = new Map<string, number>();
  const i = lastIndex(r.speeds, t, (x) => x[0]);
  if (i < 0) return out;
  r.order.forEach((pid, c) => out.set(pid, r.speeds[i][1][c] ?? 0));
  return out;
}

export function activeCues(r: Replay, t: number, kinds?: string[]): Cue[] {
  const end = lastIndex(r.cues, t, (c) => c.t);
  const out: Cue[] = [];
  for (let i = end; i >= 0; i--) {
    const c = r.cues[i];
    if (t - c.t > 10_000) break;
    if (t - c.t <= c.duration_ms && (!kinds || kinds.includes(c.kind))) out.push(c);
  }
  return out;
}

export function sideOf(r: Replay, teamId: string | null): Side | null {
  if (teamId === r.home.club_id) return "home";
  if (teamId === r.away.club_id) return "away";
  return null;
}

export function scoreAt(r: Replay, t: number): [number, number] {
  let home = 0;
  let away = 0;
  for (const e of r.events) {
    if (e.t > t) break;
    if (e.type === "shot" && e.outcome === "goal") {
      if (e.team === r.home.club_id) home++;
      else away++;
    }
  }
  return [home, away];
}

/** Broadcast clock: 45+2' style in stoppage time. */
export function clockLabel(period: number, clock: number): string {
  const base = period === 1 ? 0 : 45 * 60_000;
  const limit = base + 45 * 60_000;
  const fmt = (ms: number) => {
    const m = Math.floor(ms / 60_000);
    const sec = Math.floor((ms % 60_000) / 1000);
    return `${m}:${String(sec).padStart(2, "0")}`;
  };
  if (clock >= limit) return `${period === 1 ? 45 : 90}+${Math.floor((clock - limit) / 60_000) + 1}'`;
  return fmt(clock);
}

export function surname(r: Replay, pid: string | null | undefined): string {
  if (!pid) return "";
  const p = r.players[pid];
  return p ? p.name.split(" ").slice(-1)[0] : pid;
}

export function latestSeries(r: Replay, team: string, t: number): TacticsItem | null {
  for (let i = lastIndex(r.tactics, t, (x) => x.t); i >= 0; i--) {
    const x = r.tactics[i];
    if (x.kind === "series" && x.team_id === team) return x;
  }
  return null;
}

export function latestWindow(r: Replay, team: string, t: number): TacticsItem | null {
  for (let i = lastIndex(r.tactics, t, (x) => x.t); i >= 0; i--) {
    const x = r.tactics[i];
    if (x.kind === "window" && x.team_id === team) return x;
  }
  return null;
}

export function clubName(r: Replay, teamId: string | null): string {
  if (teamId === r.home.club_id) return r.home.name;
  if (teamId === r.away.club_id) return r.away.name;
  return "";
}

const CHANGE_LABEL: Record<string, string> = {
  line_height_m: "defensive line",
  pressing_per_min: "pressing",
  formation_out: "shape",
  style_dial: "style",
  length_m: "team length",
  width_m: "team width",
};

export interface Caption {
  t: number;
  text: string;
  tone: "goal" | "card" | "tactic" | "info";
  source: string;
  /** "agent" or "template" for Insight Generation captions; "auto" for the screen's own. */
  origin: "agent" | "template" | "auto";
}

const INSIGHT_TONE: Record<string, Caption["tone"]> = {
  expect: "tactic", confirmed: "tactic", retracted: "tactic", shift: "tactic",
  summary: "tactic", check_in: "info", external: "info",
};

/** Captions written from the numbers alone (caption_source "template"); agents add theirs later. */
/** Which caption set a viewer type reads; player focus reads the casual captions. */
export function captionVoice(viewer: ViewerType, club: Side): CaptionVoice {
  if (viewer === "analyst") return "analyst";
  if (viewer === "supporter") return club === "home" ? "supporter_home" : "supporter_away";
  return "casual";
}

// A goal or card caption that an insight follows gives way after this long, so the agents'
// expectation written at that moment still gets its full 10 s on screen
const EVENT_FIRST_MS = 4_000;
const EVENT_HOLD: Record<string, number> = { goal: 10_000, card: 8_000 };

function headline(e: Replay["events"][number]): "goal" | "card" | null {
  if (e.type === "shot" && e.outcome === "goal") return "goal";
  return e.type === "card" ? "card" : null;
}

// Insights for the same moment take turns: each gets at least this long before the next one
const INSIGHT_TURN_MS = 6_000;
const schedules = new WeakMap<object, { events: number; starts: Map<string, number> }>();

/** When each insight starts on screen: after any goal or card caption it lands inside, and
 *  after the insight before it has had its turn. Cached per insights list (live mode makes a new
 *  list for every new insight). */
function insightStarts(r: Replay): Map<string, number> {
  const ins = r.insights ?? [];
  const hit = schedules.get(ins);
  if (hit && hit.events === r.events.length) return hit.starts;
  const starts = new Map<string, number>();
  let prev = -Infinity;
  for (const x of ins) {
    const start = Math.max(afterHeadline(r, x), prev + INSIGHT_TURN_MS);
    starts.set(x.insight_id, start);
    prev = start;
  }
  schedules.set(ins, { events: r.events.length, starts });
  return starts;
}

function afterHeadline(r: Replay, x: { t: number }): number {
  let start = x.t;
  for (let i = lastIndex(r.events, x.t, (e) => e.t); i >= 0 && x.t - r.events[i].t < 10_000; i--) {
    const h = headline(r.events[i]);
    if (h && x.t - r.events[i].t < EVENT_HOLD[h]) start = Math.max(start, r.events[i].t + EVENT_FIRST_MS);
  }
  return start;
}

/** How long a goal or card caption holds: shorter when an insight follows inside its window. */
function eventHold(r: Replay, e: { t: number }, hold: number): number {
  const ins = r.insights ?? [];
  const i = lastIndex(ins, e.t + hold - 1, (x) => x.t);
  return i >= 0 && ins[i].t >= e.t ? Math.min(hold, EVENT_FIRST_MS) : hold;
}

export function captionAt(r: Replay, t: number, viewer: CaptionVoice = "casual",
                          lang: Language = "en"): Caption | null {
  let best: Caption | null = null;
  const consider = (c: Caption, hold: number, rank: number) => {
    if (t < c.t || t - c.t > hold) return;
    const score = rank * 1e9 + c.t;
    const bestScore = best ? (best as any)._s : -1;
    if (score > bestScore) best = Object.assign(c, { _s: score });
  };
  // Insight Generation captions replace the screen's own trigger captions
  const insights = r.insights ?? [];
  const explained = new Set(insights.map((x) => x.trigger_id));
  const starts = insightStarts(r);
  for (let i = lastIndex(insights, t, (x) => x.t); i >= 0 && t - insights[i].t < 30_000; i--) {
    const x = insights[i];
    const text = x.captions[`${viewer}.${lang}`] ?? x.captions[`${viewer}.en`];
    if (!text) continue;
    const rank = x.evidence.event_ids.length && x.kind === "expect" ? 3.5 : 2.5;
    consider({ t: starts.get(x.insight_id) ?? x.t, tone: INSIGHT_TONE[x.kind] ?? "info", source: x.insight_id, text,
               origin: x.caption_source }, 10_000, rank);
  }
  for (let i = lastIndex(r.events, t, (e) => e.t); i >= 0 && t - r.events[i].t < 12_000; i--) {
    const e = r.events[i];
    if (e.type === "shot" && e.outcome === "goal") {
      const [h, a] = scoreAt(r, e.t);
      consider({ t: e.t, tone: "goal", source: e.id, origin: "auto",
        text: `Goal — ${surname(r, e.player)} for ${clubName(r, e.team)}. ${r.home.name} ${h}–${a} ${r.away.name}` },
        eventHold(r, e, EVENT_HOLD.goal), 4);
    } else if (e.type === "card") {
      consider({ t: e.t, tone: "card", source: e.id, origin: "auto",
        text: `${e.outcome === "red" ? "Red" : "Yellow"} card — ${surname(r, e.player)} (${clubName(r, e.team)})` },
        eventHold(r, e, EVENT_HOLD.card), 3);
    } else if (e.type === "sub_on") {
      consider({ t: e.t, tone: "info", source: e.id, origin: "auto",
        text: `Substitution — ${surname(r, e.player)} comes on for ${clubName(r, e.team)}` }, 6_000, 1);
    }
  }
  for (let i = lastIndex(r.tactics, t, (x) => x.t); i >= 0 && t - r.tactics[i].t < 12_000; i--) {
    const x = r.tactics[i];
    if (x.kind !== "trigger" || x.type !== "shift" || explained.has(x.trigger_id)) continue;
    const key = Object.keys(x.after ?? {})[0];
    if (!key) continue;
    if (key === "player_position") {
      consider({ t: x.t, tone: "tactic", source: x.trigger_id, origin: "auto",
        text: `${x.player_id ? surname(r, x.player_id) : "A player"} takes up a new position for ${clubName(r, x.team_id)}` }, 8_000, 2);
      continue;
    }
    const label = CHANGE_LABEL[key] ?? key.replace(/_/g, " ");
    const fmt = (v: any) => (typeof v === "number" ? (key.endsWith("_m") ? `${v.toFixed(0)} m` : v.toFixed(1)) : String(v));
    consider({ t: x.t, tone: "tactic", source: x.trigger_id, origin: "auto",
      text: `${clubName(r, x.team_id)} change their ${label}: ${fmt(x.before[key])} → ${fmt(x.after[key])}` }, 10_000, 2);
  }
  for (const c of activeCues(r, t, ["speed_alert", "shot_speed"])) {
    const text = c.kind === "speed_alert"
      ? `${surname(r, c.data.player_id)} hits ${c.data.speed_kmh} km/h`
      : `Shot by ${surname(r, c.data.player_id)} at ${c.data.speed_kmh} km/h · xG ${c.data.xg?.toFixed(2)}`;
    consider({ t: c.t, tone: "info", source: c.id, origin: "auto", text }, 4_000, c.kind === "shot_speed" ? 2 : 1);
  }
  return best;
}
