import { captionAt } from "../replay";
import type { Language, Replay, ViewerType } from "../types";

const ORIGIN = {
  agent: ["AI", "Written by the agent team and checked against the numbers"],
  template: ["auto", "Written from the numbers by a template"],
  auto: ["auto", "Written from the numbers by the screen"],
} as const;

export function CaptionBar({ replay, t, viewer, lang }:
  { replay: Replay; t: number; viewer: ViewerType; lang: Language }) {
  const c = captionAt(replay, t, viewer, lang);
  return (
    <div className={`caption ${c ? `tone-${c.tone}` : "idle"}`} aria-live="polite">
      {c ? (
        <>
          <span className="caption-text" key={c.source} lang={lang}>{c.text}</span>
          <span className="caption-source" title={ORIGIN[c.origin][1]}>{ORIGIN[c.origin][0]}</span>
        </>
      ) : (
        <span className="caption-text muted">Watching the shape of the game…</span>
      )}
    </div>
  );
}
