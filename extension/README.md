# SetID for YouTube (Chrome extension, Manifest V3)

Shows SetID's timestamped tracklist right under DJ sets on youtube.com:

- **Now playing**: cover, title, artist, how it was identified (Shazam / audio match / from comments, not audio-confirmed) and the played-at tempo when the data has it. Updates live as the video plays or you scrub.
- **Tracklist**: expands inside the panel. Click a row to jump the video there; the current track stays highlighted and in view.
- **Copy track ID**: copies `MM:SS Artist - Title` for what's playing, ready to paste as a comment reply.
- **Open in SetID**: opens the full set page.
- Videos that aren't in the library yet and run longer than 20 minutes get a one-line "SetID: no tracklist yet · Request it" bar. Shorter videos get nothing.
- The toolbar popup shows this tab's status and a short list of sets in the library.

## Install (Chrome, Arc, Brave, Edge)

1. Download `setid-extension.zip` and unzip it. You get a folder with `manifest.json` in it.
2. Open the extensions page: `chrome://extensions` (Chrome and Arc), `brave://extensions` (Brave) or `edge://extensions` (Edge).
3. Turn on **Developer mode** (top right in Chrome/Brave/Arc; left sidebar in Edge).
4. Click **Load unpacked** and choose the unzipped folder. Open a set such as https://www.youtube.com/watch?v=kBTYHEjtJhI and the panel appears under the player.

## How it works

| File | Role |
|---|---|
| `config.js` | The one place the SetID origin lives (`BASE`). Shared by all three contexts. |
| `background.js` | Service worker. The only code that fetches `sets/index.json` and `sets/<key>.json`; caches for 10 minutes. |
| `content.js` / `content.css` | Finds the video id, asks the worker for the set, renders the panel into `ytd-watch-flexy #below` (directly under the player, above the title). Builds DOM with `createElement`/`textContent`, never `innerHTML`. |
| `popup.html` / `popup.js` / `popup.css` | Toolbar popup. Asks the content script for the tab's status. |
| `icons/` | 16/32/48/128 PNG. |

**Moving to another domain** (e.g. Vercel): change `BASE` in `config.js` and the matching entry in `manifest.json` → `host_permissions`. Nothing else references the origin.

**Permissions.** One host permission: the SetID data origin. No `tabs`, `storage`, `scripting` or other API permissions. The content script is declared for `https://www.youtube.com/*`, not just `/watch*`, because YouTube is a single-page app: going from the home page or search to a video never reloads the page, so a `/watch`-only script would never be injected. Off watch pages the script only tears down.

**YouTube SPA handling.** Navigation is detected via `yt-navigate-finish`, `popstate` and a 1 s URL check. Media events are listened to in the capture phase on `document`, so they keep working when YouTube swaps the `<video>` element. The panel is re-attached if YouTube re-renders `#below`, and removed on navigation away. During pre-roll ads (`#movie_player.ad-showing`) the panel holds still and the "no tracklist yet" bar waits for the real video's duration.

**Theming.** Uses YouTube's `--yt-spec-*` variables when present, with fallbacks matching YouTube's light palette and its dark palette under `html[dark]` (recent YouTube builds no longer define some of those variables). Vermilion `#E8452C` is the only accent: the now-playing dot, the current-row marker and the focus ring.

**Accessibility.** Every control is a real `<button>` or link with a visible focus ring; the toggle uses `aria-expanded`/`aria-controls`; the current row carries `aria-current`; the now-playing block is a polite live region; smooth scrolling and the chevron animation are off under `prefers-reduced-motion`.

**Request link.** "Request it" opens `<BASE>/#/?q=<watch url>`. The site doesn't read `q` yet, so today it simply lands on the SetID home page; once the site supports it the URL will be prefilled.
