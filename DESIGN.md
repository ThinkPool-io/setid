# SetID design system: Tonhalle

Swiss concert poster discipline on black: one grotesque, a 12-column grid, rhythm instead of containers. Chosen from the five-direction board (`design/directions.html`, Direction 4).

## Principles

- **No enclosures.** No cards, boxed panels or divider rules. Grouping comes from the grid and spacing.
- **Rank is brightness.** The current or most important item is bone white or vermilion; everything else steps down through the greys. Cover art is greyscale until it is current or hovered.
- **Vermilion is the only signal.** Primary action, the playing track, the Track ID answer, setlist numbers. Never decoration.
- **The data is the graphic.** The home shows a real set as a rhythm of lines (one per identified track, placed at its start time); the set timeline uses the same language.

## Tokens

| Token | Value | Use |
|---|---|---|
| `--bk` | `#0E0E0E` | ground |
| `--wh` | `#F2F0EA` | primary text, identified timeline segments |
| `--g1` | `#B8B6AF` | secondary text, inactive titles |
| `--g2` | `#8E8C86` | tertiary text, captions, unidentified rows (5.4:1 on ground) |
| `--g3` | `#38372F` | inactive marks, underlines at rest; never text |
| `--g4` | `#1B1B19` | the only field colour (progress log, image placeholders) |
| `--vm` | `#E8452C` | signal: primary button, current track, answer, focus ring |
| `--warn` | `#E7A83A` | low-confidence and offline state only |
| `--bad` | `#F06A55` | failed jobs |

## Type

Schibsted Grotesk 400 to 800, one family. Display 800 at up to 160 px, tracking -0.04em. Track ID input 700 at 56 to 84 px. Titles 600. Body 16 px / 1.5. Tabular figures only on tracklist times, the playhead time and setlist numbers (Schibsted's tabular setting also widens punctuation).

## Components

- **Buttons:** square, 1.5 px bone outline, fill on hover. Primary uses vermilion with black text. Icon buttons are bare and turn vermilion on hover.
- **Inputs:** no box; a 2 px bone underline that turns vermilion on focus.
- **Icons:** inline SVG sprite in `index.html` (`#i-yt`, `#i-sp`, `#i-ap`, `#i-dl`, `#i-copy`, `#i-link`, `#i-up`, `#i-down`, `#i-x`, `#i-plus`), 1.8 stroke. No unicode glyphs as icons.
- **Status lines:** 8 px square + text (`#worker .chip`), bone when live, grey when not.

## Motion

One authored moment: the home rhythm lines draw in left to right, staggered 28 ms. Running jobs pulse their square. Everything is off under `prefers-reduced-motion`.

## Layout

12-column grid, 24 px gutter, 48 px page padding (18 px and one column under 760 px). Home: status in columns 1 to 3, headline and paste field in 4 to 12. Set page: player and tracklist 7, setlist 5; single column under 1000 px.
