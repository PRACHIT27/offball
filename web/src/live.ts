// Live mode (Broadcast LLD §8): the cue manager's state for late joiners, then Web PubSub
// messages, turned into the same Replay shape the screen draws for recorded matches.
import { useEffect, useRef, useState } from "react";
import type { MatchListing, MetricsView, Replay } from "./types";

export const CUES_URL: string = import.meta.env.VITE_CUES_URL
  ?? "https://offball-cues.whitemoss-2f18829c.westus2.azurecontainerapps.io";
export const LIVE_PREFIX = "live:";
const LIVE_DELAY_MS = 1200; // play a little behind the newest frame, so motion stays smooth
const RENDER_EVERY_MS = 200;

export async function listLive(): Promise<MatchListing[]> {
  try {
    const r = await fetch(`${CUES_URL}/api/matches`);
    if (!r.ok) return [];
    const { matches } = await r.json();
    return matches.filter((m: any) => m.last_message_at && Date.now() / 1000 - m.last_message_at < 600)
      .map((m: any) => ({ match_id: `${LIVE_PREFIX}${m.match_id}`, storyline: "live",
        title: m.home ? `${m.home} v ${m.away}` : m.match_id }));
  } catch {
    return [];
  }
}

const dm = (v: number) => Math.round(v * 10);

/** Builds a growing Replay (and a small MetricsView) from live messages. */
class LiveBuilder {
  replay: Replay;
  metrics: MetricsView;
  col = new Map<string, number>();
  lastT = 0;
  lastArrival = performance.now();
  /** True once the late joiner's state is loaded and messages arrive as they happen. */
  streaming = false;

  constructor(matchId: string, prematch: any | null) {
    const players: Replay["players"] = {};
    for (const side of ["home", "away"] as const) {
      for (const p of prematch?.[side]?.players ?? []) {
        players[p.player_id] = { name: p.name, number: p.number, position: p.position, team: side };
      }
    }
    const club = (side: "home" | "away") => ({
      club_id: prematch?.[side]?.club_id ?? side.toUpperCase(),
      name: prematch?.[side]?.name ?? side,
    });
    this.replay = {
      // The picker's key for this match ("live:m001"), so it never collides with a recording
      schema: "offball-live/1", match_id: `${LIVE_PREFIX}${matchId}`, storyline: "live",
      home: club("home"),
      away: club("away"), managers: { home: null, away: null }, players, order: [],
      periods: { "1": { t0: 0, t1: 0 }, "2": { t0: 0, t1: 0 } }, frames: [], speeds: [],
      events: [], cues: [], xg: [], totals: [], tactics: [], insights: [],
    };
    this.metrics = { schema: "offball-metrics-live/1", match_id: matchId, order: this.replay.order,
      heat: { grid: [21, 14], snapshots: [] }, shots: [], passing: [], pressure: [], cues: [],
      ball: [], passes: {} };
  }

  column(pid: string): number {
    let c = this.col.get(pid);
    if (c === undefined) {
      c = this.replay.order.length;
      this.col.set(pid, c);
      this.replay.order.push(pid);
      if (!this.replay.players[pid]) {
        const [club, num] = pid.split("-");
        const side = club === this.replay.home.club_id ? "home" : "away";
        this.replay.players[pid] = { name: pid, number: Number(num) || 0, position: "", team: side };
      }
    }
    return c;
  }

  setPeriods(p1End: number | null) {
    const end = p1End ?? this.lastT;
    this.replay.periods["1"] = { t0: 0, t1: end };
    this.replay.periods["2"] = { t0: end, t1: Math.max(end, this.lastT) };
  }

  apply(env: any) {
    switch (env.type) {
      case "positions": {
        const f = env.frames[env.frames.length - 1];
        for (const pid of Object.keys(f.players)) this.column(pid);
        const pos = new Array(2 * this.replay.order.length).fill(-1);
        for (const [pid, [x, y]] of Object.entries(f.players) as [string, number[]][]) {
          const c = this.col.get(pid)!;
          pos[2 * c] = dm(x);
          pos[2 * c + 1] = dm(y);
        }
        this.replay.frames.push([env.t, env.period, f.match_clock_ms, dm(f.ball[0]), dm(f.ball[1]), pos]);
        this.replay.speeds.push([env.t, this.replay.order.map((pid) => Math.round(env.tags[pid]?.speed_kmh ?? 0))]);
        this.metrics.pressure.push([env.t, this.replay.order.map((pid) =>
          env.tags[pid] ? Math.round(env.tags[pid].pressure * 100) : -1)]);
        if (env.ball_speed_ms != null) this.metrics.ball!.push([env.t, Math.round(env.ball_speed_ms * 3.6)]);
        this.lastT = Math.max(this.lastT, env.t);
        this.lastArrival = performance.now();
        if (env.period === 1) this.setPeriods(this.lastT); else this.setPeriods(this.replay.periods["1"].t1);
        break;
      }
      case "stats": {
        const d = env.data;
        if (d.kind === "shot") {
          // A corrected shot replaces the earlier version; a deleted one goes
          const id = d.evidence.event_ids[0];
          this.replay.events = this.replay.events.filter((e) => e.id !== id);
          this.metrics.shots = this.metrics.shots.filter((s) => s.id !== id);
          if (d.status !== "deleted") {
            this.replay.events.push({ id, t: env.t, type: "shot", period: d.period, clock: d.match_clock_ms,
              team: d.team_id, player: d.player_id, outcome: d.values.outcome, target: null });
            this.replay.events.sort((x, y) => x.t - y.t);
            // The shot message has no location: the shooter's tracked position in the newest frame
            const f = this.replay.frames[this.replay.frames.length - 1];
            const c = this.col.get(d.player_id);
            const at = f && c !== undefined && f[5][2 * c] >= 0 ? [f[5][2 * c] / 10, f[5][2 * c + 1] / 10] : null;
            this.metrics.shots.push({ t: env.t, id, team: d.team_id, player: d.player_id,
              x: at ? at[0] : null, y: at ? at[1] : null, xg: d.values.xg ?? null,
              speed_kmh: d.values.speed_kmh ?? null, outcome: d.values.outcome });
          }
        } else if (d.kind === "xg") {
          this.replay.xg.push({ t: env.t, team: d.team_id, ...d.values });
        } else if (d.kind === "player_totals") {
          this.replay.totals.push({ t: env.t, players: d.values.players });
        } else if (d.kind === "pass") {
          this.metrics.passes![d.evidence.event_ids[0]] = {
            open_options: d.values.open_options, decision_score: d.values.decision_score };
        }
        break;
      }
      case "tactics":
        this.replay.tactics.push({ ...env.data, t: env.t });
        break;
      case "cue": {
        const c = env.cue;
        if (c.kind === "insight") {
          if (c.status === "withdrawn") {
            const iid = c.cue_id.replace(/^ins-/, "");
            this.replay.insights = (this.replay.insights ?? []).filter((x) => x.insight_id !== iid);
          }
          break;
        }
        this.replay.cues = this.replay.cues.filter((x) => x.id !== c.cue_id);
        if (c.status !== "withdrawn") {
          this.replay.cues.push({ t: c.t, id: c.cue_id, kind: c.kind, duration_ms: c.duration_ms,
            data: c.data, evidence: c.evidence });
          this.replay.cues.sort((a, b) => a.t - b.t);
        }
        break;
      }
      case "insight": {
        // The agents take 8–20 s while the match clock runs on (80–200 s at 10×), and the caption
        // bar holds a caption for 10 s from its t: show a live one from when it arrives
        const t = this.streaming ? Math.max(env.data.t, this.lastT) : env.data.t;
        this.replay.insights = [...(this.replay.insights ?? []), { ...env.data, t }].sort((a, b) => a.t - b.t);
        break;
      }
    }
  }
}

export interface LiveMatch {
  replay: Replay;
  metrics: MetricsView;
  /** Where the screen's clock should be now: just behind the newest frame. */
  now: () => number;
  connected: boolean;
}

export function useLive(matchId: string | null): LiveMatch | null {
  const [live, setLive] = useState<LiveMatch | null>(null);
  const builder = useRef<LiveBuilder | null>(null);

  useEffect(() => {
    if (!matchId) return;
    const id = matchId.slice(LIVE_PREFIX.length);
    let ws: WebSocket | null = null;
    let closed = false;
    let dirty = false;
    let connected = false;
    const emit = () => {
      const b = builder.current;
      if (!b) return;
      setLive({ replay: { ...b.replay }, metrics: { ...b.metrics }, connected,
        now: () => Math.min(b.lastT, b.lastT - LIVE_DELAY_MS + (performance.now() - b.lastArrival)) });
    };
    const timer = setInterval(() => { if (dirty) { dirty = false; emit(); } }, RENDER_EVERY_MS);

    (async () => {
      const state = await (await fetch(`${CUES_URL}/api/matches/${encodeURIComponent(id)}/state`)).json();
      const b = new LiveBuilder(id, state.prematch);
      builder.current = b;
      b.setPeriods(state.p1_end);
      for (const env of state.positions) b.apply(env);
      for (const env of state.stats) b.apply(env);
      for (const env of state.tactics) b.apply(env);
      for (const row of state.insights) b.apply({ type: "insight", data: row });
      for (const c of state.cues) if (c.kind !== "insight") b.apply({ type: "cue", cue: c });
      emit();
      b.streaming = true;
      const { url } = await (await fetch(`${CUES_URL}/api/negotiate?match=${encodeURIComponent(id)}`)).json();
      if (closed) return;
      ws = new WebSocket(url);
      ws.onopen = () => { connected = true; dirty = true; };
      ws.onclose = () => { connected = false; dirty = true; };
      ws.onmessage = (m) => {
        try {
          b.apply(JSON.parse(typeof m.data === "string" ? m.data : ""));
          dirty = true;
        } catch { /* a malformed message is skipped */ }
      };
    })().catch(() => setLive(null));

    return () => {
      closed = true;
      clearInterval(timer);
      ws?.close();
      builder.current = null;
      setLive(null);
    };
  }, [matchId]);

  return live;
}
