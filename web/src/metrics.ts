// Reading the Performance Metrics side file at a moment t (ms of play since kick-off).
import { lastIndex } from "./replay";
import type { MetricsView } from "./types";

export const PRESS_RING = 75; // pressure ≥ 0.75: an opponent within 2 m (metrics LLD §5.2)

export function pressureAt(m: MetricsView | null, t: number): Map<string, number> | null {
  if (!m) return null;
  const i = lastIndex(m.pressure, t, (x) => x[0]);
  if (i < 0) return null;
  const out = new Map<string, number>();
  m.order.forEach((pid, c) => {
    const v = m.pressure[i][1][c];
    if (v >= 0) out.set(pid, v);
  });
  return out;
}

export function metricCuesAt(m: MetricsView | null, t: number) {
  if (!m) return [];
  const end = lastIndex(m.cues, t, (c) => c.t);
  const out = [];
  for (let i = end; i >= 0 && t - m.cues[i].t < 10_000; i--) {
    if (t - m.cues[i].t <= m.cues[i].duration_ms) out.push(m.cues[i]);
  }
  return out;
}

export function ballSpeedAt(m: MetricsView | null, t: number): number | null {
  if (!m?.ball?.length) return null;
  const i = lastIndex(m.ball, t, (x) => x[0]);
  return i < 0 ? null : m.ball[i][1];
}

export function heatAt(m: MetricsView | null, pid: string, t: number) {
  if (!m) return null;
  const i = lastIndex(m.heat.snapshots, t, (s) => s.t);
  return i < 0 ? null : m.heat.snapshots[i].players[pid] ?? null;
}

export function passingAt(m: MetricsView | null, t: number) {
  if (!m) return null;
  const i = lastIndex(m.passing, t, (p) => p.t);
  return i < 0 ? null : m.passing[i].teams;
}
