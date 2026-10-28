import { useCallback, useEffect, useRef, useState } from "react";
import { CaptionBar } from "./components/CaptionBar";
import { FourWays } from "./components/FourWays";
import { Pitch, TEAM_COLOUR } from "./components/Pitch";
import { SidePanel } from "./components/SidePanel";
import { moments, Timeline } from "./components/Timeline";
import { TopBar } from "./components/TopBar";
import { captionVoice, lastIndex, snapshotAt } from "./replay";
import type { Language, MatchListing, MetricsView, Replay, Side, ViewerType } from "./types";

const BASE = `${import.meta.env.BASE_URL}replays/`;
const VIEWER_TYPES: ViewerType[] = ["casual", "analyst", "supporter", "player"];

/** Who the player-focus view follows when nobody is picked: the latest goal, card or sub. */
function featuredPlayer(r: Replay, t: number): string | null {
  for (let i = lastIndex(r.events, t, (e) => e.t); i >= 0; i--) {
    const e = r.events[i];
    if (e.player && (e.type === "card" || e.type === "sub_on"
        || (e.type === "shot" && e.outcome === "goal"))) return e.player;
  }
  return r.order.find((pid) => r.players[pid]?.position !== "GK") ?? null;
}

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode: choices just aren't remembered */
  }
}

export default function App() {
  const params = new URLSearchParams(location.search);
  const [matches, setMatches] = useState<MatchListing[]>([]);
  const [matchId, setMatchId] = useState<string | null>(params.get("match"));
  const [replay, setReplay] = useState<Replay | null>(null);
  // Performance Metrics side file; optional, the screen works without it
  const [metrics, setMetrics] = useState<MetricsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [viewer, setViewer] = useState<ViewerType>(() => {
    const v = (params.get("type") as ViewerType) || load<ViewerType>("offball.viewer", "casual");
    return VIEWER_TYPES.includes(v) ? v : "casual";
  });
  const [club, setClub] = useState<Side>(
    (params.get("club") as Side) || load<Side>("offball.club", "home"));
  const [fourWays, setFourWays] = useState(params.get("view") === "four");
  const [lang, setLang] = useState<Language>(
    (params.get("lang") as Language) || load<Language>("offball.lang", "en"));
  const [focus, setFocus] = useState<string | null>(null);
  const tRef = useRef(0);

  useEffect(() => {
    fetch(`${BASE}index.json`).then((r) => r.json()).then((list: MatchListing[]) => {
      setMatches(list);
      setMatchId((id) => id ?? list[0]?.match_id ?? null);
    }).catch(() => setError("No replays found. Build one with scripts/build_replay.py."));
  }, []);

  useEffect(() => {
    if (!matchId) return;
    setReplay(null);
    setPlaying(false);
    setMetrics(null);
    fetch(`${BASE}${matchId}.metrics.json`).then((r) => (r.ok ? r.json() : null))
      .then((m: MetricsView | null) => setMetrics(m)).catch(() => setMetrics(null));
    fetch(`${BASE}${matchId}.json`).then((r) => r.json()).then((rep: Replay) => {
      setReplay(rep);
      const start = Number(params.get("t") ?? 0) * 1000;
      tRef.current = start;
      setT(start);
    }).catch(() => setError(`Could not load match ${matchId}.`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId]);

  useEffect(() => save("offball.viewer", viewer), [viewer]);
  useEffect(() => save("offball.club", club), [club]);
  useEffect(() => save("offball.lang", lang), [lang]);

  // Match clock: advances at the viewer's speed, one React render per animation frame
  useEffect(() => {
    if (!playing || !replay) return;
    let raf = 0;
    let last = performance.now();
    const end = replay.periods["2"].t1;
    const tick = (now: number) => {
      tRef.current = Math.min(end, tRef.current + (now - last) * speed);
      last = now;
      setT(tRef.current);
      if (tRef.current >= end) setPlaying(false);
      else raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, replay]);

  const seek = useCallback((to: number) => {
    tRef.current = Math.max(0, to);
    setT(tRef.current);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLSelectElement) return;
      if (e.code === "Space") { e.preventDefault(); setPlaying((p) => !p); }
      if (e.code === "ArrowRight") seek(tRef.current + 10_000);
      if (e.code === "ArrowLeft") seek(tRef.current - 10_000);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [seek]);

  if (error) return <div className="splash">{error}</div>;
  if (!replay) return <div className="splash">Loading match…</div>;

  const snap = snapshotAt(replay, t);
  const next = () => {
    const m = moments(replay).find((x) => x.t - 3000 > t + 500);
    if (m) seek(m.t - 3000);
  };

  const pick = (pid: string) => setFocus((f) => (f === pid ? null : pid));
  // Player focus follows the picked player, or the latest goal, card or sub until one is picked
  const followed = viewer === "player" ? focus ?? featuredPlayer(replay, t) : focus;
  const accent = viewer === "supporter" ? TEAM_COLOUR[club] : undefined;

  return (
    <div className={`app viewer-${viewer}${fourWays ? " four" : ""}`}>
      <TopBar replay={replay} matches={matches} t={t} period={snap?.period ?? 1}
              clock={snap?.clock ?? 0} playing={playing} speed={speed} viewer={viewer}
              club={club} fourWays={fourWays} lang={lang}
              onMatch={(id) => setMatchId(id)} onPlay={() => setPlaying((p) => !p)}
              onSpeed={setSpeed} onViewer={setViewer} onClub={setClub} onFourWays={setFourWays}
              onLang={setLang} onNextMoment={next} />
      {fourWays ? (
        <main className="stage">
          <FourWays replay={replay} metrics={metrics} t={t} lang={lang} club={club}
                    featured={focus ?? featuredPlayer(replay, t)} onPickPlayer={pick} />
        </main>
      ) : (
        <main className="stage">
          <div className="pitch-wrap">
            <Pitch replay={replay} metrics={metrics} t={t}
                   viewer={viewer === "analyst" ? "analyst" : "casual"} focus={followed}
                   onPickPlayer={pick} />
            <CaptionBar replay={replay} t={t} voice={captionVoice(viewer, club)} lang={lang}
                        accent={accent} />
          </div>
          {(viewer === "analyst" || followed) && (
            <SidePanel replay={replay} metrics={metrics} t={t} focus={followed} />
          )}
        </main>
      )}
      <Timeline replay={replay} t={t} onSeek={seek} />
    </div>
  );
}
