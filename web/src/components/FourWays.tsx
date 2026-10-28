// "The same moment four ways" (Audience LLD §5): four small pitches with their own caption
// bars, one per viewer type, locked to the same match clock.
import { captionVoice, sideOf, surname } from "../replay";
import type { Language, MetricsView, Replay, Side, ViewerType } from "../types";
import { CaptionBar } from "./CaptionBar";
import { Pitch, TEAM_COLOUR } from "./Pitch";

interface Props {
  replay: Replay;
  metrics: MetricsView | null;
  t: number;
  lang: Language;
  club: Side;
  /** The player the player-focus tile follows. */
  featured: string | null;
  onPickPlayer: (pid: string) => void;
}

export function FourWays({ replay: r, metrics, t, lang, club, featured, onPickPlayer }: Props) {
  const tiles: { viewer: ViewerType; title: string; focus: string | null; accent?: string }[] = [
    { viewer: "casual", title: "Casual fan", focus: null },
    { viewer: "analyst", title: "Analyst", focus: null },
    { viewer: "supporter", title: `${r[club].name} supporter`, focus: null,
      accent: TEAM_COLOUR[club] },
    { viewer: "player", title: featured ? `Following ${surname(r, featured)}` : "Player focus",
      focus: featured,
      accent: featured ? TEAM_COLOUR[sideOf(r, featured.split("-")[0]) ?? "home"] : undefined },
  ];
  return (
    <div className="four-ways">
      {tiles.map((tile) => (
        <section key={tile.viewer} className="four-tile">
          <h3 style={tile.accent ? { color: tile.accent } : undefined}>{tile.title}</h3>
          <Pitch replay={r} metrics={metrics} t={t}
                 viewer={tile.viewer === "analyst" ? "analyst" : "casual"}
                 focus={tile.focus} onPickPlayer={onPickPlayer} />
          <CaptionBar replay={r} t={t} voice={captionVoice(tile.viewer, club)} lang={lang}
                      accent={tile.accent} />
        </section>
      ))}
    </div>
  );
}
