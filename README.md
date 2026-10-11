# SetID

Track ID for any DJ set. Paste a YouTube or SoundCloud link, get every track with timestamps,
find similar tracks, build a setlist, send it to YouTube, Spotify or Apple Music.

Live prototype: https://thinkpool-io.github.io/setid/

## How it works

`pipeline/trackid.py` does the heavy lifting, all with free, keyless services:

1. **yt-dlp** downloads the set's audio.
2. Every 40 s a 12 s clip goes to **Shazam** (via `shazamio`). Consecutive identical IDs merge into one
   segment; lone one-off IDs sandwiched inside the same track are dropped (false positives on blends).
3. Each identified track is enriched: **Deezer** (BPM, ISRC, 30 s preview, cover),
   **MusicBrainz → ListenBrainz** (track-level "listeners of this also play" similarity),
   Deezer related artists as fallback, and **yt-dlp search** resolves a YouTube video id per track
   so playlist export is a single link.
4. Output is one JSON per set in `site/sets/`. `build_index.py` rebuilds the library index.

The site (`site/`) is static: a YouTube player, a tracklist that follows playback, a "track ID @ time"
lookup that produces a copy-paste answer for comment sections, similar tracks with previews, a setlist
that persists across sets, and exports.

## Run it on a set

```
cd pipeline
python3.11 -m venv .venv && . .venv/bin/activate
pip install shazamio yt-dlp          # ffmpeg must be on PATH
python trackid.py "https://www.youtube.com/watch?v=..."   # ~1 min of compute per hour of audio
python build_index.py
```

## Exports

| Target | Prototype | Full product |
|---|---|---|
| YouTube / YouTube Music | One link opens a playable playlist (`watch_videos?video_ids=`). Works today. | Save to account via YouTube Data API |
| Spotify | PKCE flow is implemented; set `spotifyClientId` in `site/app.js` (register an app at developer.spotify.com with the site URL as redirect) and it creates a real playlist. Without it: copies the list and opens searches. | Same, with the app id configured |
| Apple Music | Opens the Shazam-provided Apple Music link per track, copies the list. | MusicKit JS playlist creation (needs an Apple developer token) |
| M3U8 / CSV / text | Works today | |

## Honest limits

- Shazam misses blends, edits, acapellas and unreleased material. Those show as "Unidentified".
- Similarity coverage is best for tracks with a ListenBrainz footprint; underground releases fall back to related-artist picks.
- The prototype processes sets offline. The product needs a queue worker running the same script.
