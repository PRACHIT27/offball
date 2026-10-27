import { captionAt } from "../replay";
import type { Replay } from "../types";

export function CaptionBar({ replay, t }: { replay: Replay; t: number }) {
  const c = captionAt(replay, t);
  return (
    <div className={`caption ${c ? `tone-${c.tone}` : "idle"}`} aria-live="polite">
      {c ? (
        <>
          <span className="caption-text" key={c.source}>{c.text}</span>
          <span className="caption-source" title="Written from the numbers; AI captions come later">auto</span>
        </>
      ) : (
        <span className="caption-text muted">Watching the shape of the game…</span>
      )}
    </div>
  );
}
