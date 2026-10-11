# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences share one surface:

- **Casual listeners** who watch DJ sets on YouTube or SoundCloud and want to know what is playing at a moment, the person who types "track ID @ 47:12?" in the comments. Their job: get a name for the track they heard and, often, paste the answer back into the comments.
- **DJs** who mine sets for material. Their job: find the tracks, find similar tracks, and collect them into a setlist they can export to YouTube, Spotify, Apple Music, M3U8 or CSV.

## Product Purpose

SetID turns a DJ set link into a timestamped tracklist. Paste a YouTube or SoundCloud URL, a worker listens through the set and returns every identified track with its timestamp, cover, artist, label and (where available) BPM, plus similar tracks and export targets. Success: the listener gets their answer in seconds; the DJ leaves with a setlist in their own library.

## Positioning

SetID listens to the whole set itself rather than waiting for a commenter or a crowd-sourced tracklist: every 40 s a 12 s clip goes to Shazam, consecutive hits merge into segments, and each track is enriched with preview, cover, BPM and similarity. Any moment in the set can be asked about by time.

## Operating Context

- Input: a YouTube or SoundCloud link. Output: one JSON per set in `sets/` (source, analysis stats, segments with start/end and track, similar tracks per track).
- A queue worker runs the identification (worker status, Shazam status and queue depth are real states of the product).
- Answers are pasted into YouTube comment sections; setlists go to streaming libraries.

## Capabilities and Constraints

- Static site (`index.html` + `app.js`), no build step. Pipeline in `pipeline/`.
- Exports: YouTube playlist link works today; Spotify needs a configured client id (otherwise copies list and opens searches); Apple Music opens per-track links and copies the list; M3U8/CSV/text work today.
- Shazam misses blends, edits, acapellas and unreleased material: those show as "Unidentified". Gaps are a normal, honest state.
- BPM comes from Deezer and is often missing. Similarity coverage is uneven for underground releases.

## Evidence on Hand

- Real analysed set: `sets/youtube-c0-hvjV2A5Y.json` (Fred again.. | Boiler Room: London, 1:11:44, 108 samples, 87 identified). Real titles, artists, labels, covers, timestamps.
- No testimonials, user counts, or pricing exist. Do not invent them.

## Product Principles

1. The answer first: a timestamp in, a track name out, copyable in one action.
2. Honest about gaps: unidentified stretches are shown, never papered over.
3. One surface, two depths: the casual question and the DJ's dig live together without one burying the other.
4. Leave with something: every track path ends in an open-in or a setlist export.

<!-- Source: inferred from the conductor brief (relayed 2026-10-11) and README.md; confirmed for writing by the room. -->
