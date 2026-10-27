import { useCallback, useEffect, useRef, useState } from "react";
import { CaptionBar } from "./components/CaptionBar";
import { Pitch } from "./components/Pitch";
import { SidePanel } from "./components/SidePanel";
import { moments, Timeline } from "./components/Timeline";
import { TopBar } from "./components/TopBar";
import { snapshotAt } from "./replay";
import type { Language, MatchListing, Replay, ViewerType } from "./types";

const BASE = `${import.meta.env.BASE_URL}replays/`;

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
  const [error, setError] = useState<string | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [viewer, setViewer] = useState<ViewerType>(
    (params.get("type") as ViewerType) || load<ViewerType>("offball.viewer", "casual"));
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
    fetch(`${BASE}${matchId}.json`).then((r) => r.json()).then((rep: Replay) => {
      setReplay(rep);
      const start = Number(params.get("t") ?? 0) * 1000;
      tRef.current = start;
      setT(start);
    }).catch(() => setError(`Could not load match ${matchId}.`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId]);

  useEffect(() => save("offball.viewer", viewer), [viewer]);
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

  return (
    <div className={`app viewer-${viewer}`}>
      <TopBar replay={replay} matches={matches} t={t} period={snap?.period ?? 1}
              clock={snap?.clock ?? 0} playing={playing} speed={speed} viewer={viewer}
              lang={lang} onMatch={(id) => setMatchId(id)} onPlay={() => setPlaying((p) => !p)}
              onSpeed={setSpeed} onViewer={setViewer} onLang={setLang} onNextMoment={next} />
      <main className="stage">
        <div className="pitch-wrap">
          <Pitch replay={replay} t={t} viewer={viewer} focus={focus}
                 onPickPlayer={(pid) => setFocus((f) => (f === pid ? null : pid))} />
          <CaptionBar replay={replay} t={t} viewer={viewer} lang={lang} />
        </div>
        {(viewer === "analyst" || focus) && <SidePanel replay={replay} t={t} focus={focus} />}
      </main>
      <Timeline replay={replay} t={t} onSeek={seek} />
    </div>
  );
}
