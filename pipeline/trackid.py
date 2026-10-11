#!/usr/bin/env python3
"""SetID pipeline: DJ set URL -> timestamped tracklist (Shazam) -> similar tracks -> streaming links.

usage: python trackid.py <youtube-or-soundcloud-url> [--every 40] [--clip 12] [--limit-min 0] [--out ../site/sets]

Sources (all free, no keys): yt-dlp (audio), Shazam (ID), Deezer (BPM, previews, related artists),
MusicBrainz + ListenBrainz (track-level similarity), yt-dlp search (YouTube video ids for playlist export).
"""
import argparse, asyncio, json, os, subprocess, sys, tempfile, time, urllib.parse
import aiohttp
from shazamio import Shazam

UA = {"User-Agent": "setid-prototype/0.1 (https://github.com/ThinkPool-io/setid)"}

def sh(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout

def fetch(url, workdir):
    meta = json.loads(sh(["yt-dlp", "-J", "--no-playlist", url]))
    out = os.path.join(workdir, "set.%(ext)s")
    subprocess.run(["yt-dlp", "-q", "--no-playlist", "-x", "--audio-format", "mp3", "--audio-quality", "6", "-o", out, url], check=True)
    return meta, os.path.join(workdir, "set.mp3")

def clip(src, start, length, workdir):
    dst = os.path.join(workdir, f"clip_{int(start)}.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(length), "-i", src,
                    "-ac", "1", "-ar", "44100", "-b:a", "96k", dst], check=True)
    return dst

def norm(m):
    t = m.get("track") or {}
    if not t.get("key"):
        return None
    hub = t.get("hub") or {}
    links = {}
    for o in hub.get("options", []):
        for a in o.get("actions", []):
            if a.get("type") == "uri" and "music.apple.com" in (a.get("uri") or ""):
                links["apple"] = a["uri"].split("&mttn")[0]
    for a in hub.get("actions", []):
        if a.get("type") == "uri" and (a.get("uri") or "").endswith(".m4a"):
            links["preview"] = a["uri"]
    meta = {}
    for s in (t.get("sections") or []):
        for md in s.get("metadata", []) or []:
            meta[md.get("title", "").lower()] = md.get("text")
    return {"id": "sz" + t["key"], "title": t.get("title"), "artist": t.get("subtitle"),
            "cover": (t.get("images") or {}).get("coverart"), "genre": (t.get("genres") or {}).get("primary"),
            "label": meta.get("label"), "released": meta.get("released"), "shazam": t.get("url"), **links}

async def recognize(shazam, path, retries=3):
    for i in range(retries):
        try:
            return await shazam.recognize(path)
        except Exception:
            await asyncio.sleep(2 + 3 * i)
    return {}

def merge(hits):
    segs = []
    for t, tr in hits:
        if tr and segs and segs[-1]["track"] and segs[-1]["track"]["id"] == tr["id"]:
            segs[-1]["end"] = t; segs[-1]["hits"] += 1
        elif tr:
            if len(segs) >= 2 and segs[-1]["track"] is None and segs[-2]["track"] and segs[-2]["track"]["id"] == tr["id"]:
                segs.pop(); segs[-1]["end"] = t; segs[-1]["hits"] += 1
            else:
                segs.append({"start": t, "end": t, "track": tr, "hits": 1})
        else:
            if not segs or segs[-1]["track"] is not None:
                segs.append({"start": t, "end": t, "track": None, "hits": 0})
            else:
                segs[-1]["end"] = t
    cleaned = []
    for i, s in enumerate(segs):
        if s["track"] and s["hits"] == 1 and 0 < i < len(segs) - 1:
            a, b = segs[i - 1]["track"], segs[i + 1]["track"]
            if a and b and a["id"] == b["id"]:
                continue
        cleaned.append(s)
    # segment end = start of next segment (so the timeline is continuous)
    for i, s in enumerate(cleaned):
        s["end"] = cleaned[i + 1]["start"] if i + 1 < len(cleaned) else None
    return cleaned

# ---------- enrichment ----------
async def getj(sess, url, params=None, headers=None):
    try:
        async with sess.get(url, params=params, headers=headers or UA, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                return None
            return await r.json(content_type=None)
    except Exception:
        return None

async def deezer_track(sess, artist, title):
    d = await getj(sess, "https://api.deezer.com/search", {"q": f"{artist} {title}", "limit": 1})
    if not d or not d.get("data"):
        return None
    t = d["data"][0]
    det = await getj(sess, f"https://api.deezer.com/track/{t['id']}") or {}
    return {"deezer": t.get("link"), "deezerId": t["id"], "artistId": t["artist"]["id"], "isrc": det.get("isrc"),
            "bpm": det.get("bpm") or None, "preview": t.get("preview"), "cover": t.get("album", {}).get("cover_medium"),
            "artist": t["artist"]["name"], "title": t["title"], "album": t.get("album", {}).get("title")}

async def listenbrainz_similar(sess, isrc, limit=8):
    if not isrc:
        return []
    mb = await getj(sess, f"https://musicbrainz.org/ws/2/isrc/{isrc}", {"fmt": "json"})
    await asyncio.sleep(1.0)  # MusicBrainz: 1 req/s
    recs = (mb or {}).get("recordings", [])
    if not recs:
        return []
    lb = await getj(sess, "https://labs.api.listenbrainz.org/similar-recordings/json",
                    {"recording_mbids": recs[0]["id"], "algorithm": "session_based_days_7500_session_300_contribution_5_threshold_15_limit_50_skip_30"})
    rows = lb[0]["data"] if isinstance(lb, list) and lb and isinstance(lb[0], dict) and "data" in lb[0] else (lb or [])
    out = []
    for x in rows[:limit]:
        a, n = x.get("artist_credit_name") or x.get("artist_name"), x.get("recording_name")
        if a and n:
            out.append({"artist": a, "title": n, "why": "listeners of this also play"})
    return out

async def deezer_similar(sess, artist_id, limit=6):
    ra = await getj(sess, f"https://api.deezer.com/artist/{artist_id}/related", {"limit": 4})
    out = []
    for a in (ra or {}).get("data", [])[:3]:
        top = await getj(sess, f"https://api.deezer.com/artist/{a['id']}/top", {"limit": 2})
        for x in (top or {}).get("data", []):
            out.append({"artist": x["artist"]["name"], "title": x["title"], "why": "related artist", "deezer": x.get("link"), "deezerId": x["id"], "preview": x.get("preview"), "cover": x.get("album", {}).get("cover_medium")})
    return out[:limit]

def yt_search(artist, title):
    try:
        j = sh(["yt-dlp", "--flat-playlist", "-j", "--no-warnings", f"ytsearch1:{artist} - {title}"])
        d = json.loads(j.strip().splitlines()[0])
        return {"youtube": d.get("id"), "youtubeTitle": d.get("title")}
    except Exception:
        return {}

async def enrich_track(sess, tr, with_similar=True):
    dz = await deezer_track(sess, tr["artist"], tr["title"])
    if dz:
        tr.setdefault("bpm", dz["bpm"]); tr["deezer"] = dz["deezer"]; tr["isrc"] = dz["isrc"]
        tr.setdefault("preview", dz["preview"]); tr.setdefault("cover", dz["cover"])
    tr.update(await asyncio.get_event_loop().run_in_executor(None, yt_search, tr["artist"], tr["title"]))
    sims = []
    if with_similar:
        sims = await listenbrainz_similar(sess, dz and dz["isrc"])
        if dz and len(sims) < 4:
            sims += await deezer_similar(sess, dz["artistId"])
        seen, uniq = {(tr["artist"].lower(), tr["title"].lower())}, []
        for s in sims:
            k = (s["artist"].lower(), s["title"].lower())
            if k not in seen:
                seen.add(k); uniq.append(s)
        sims = uniq[:8]
        for s in sims:  # enrich similar tracks with deezer preview/cover + youtube id
            if "preview" not in s:
                d2 = await deezer_track(sess, s["artist"], s["title"])
                if d2:
                    s.update({"preview": d2["preview"], "cover": d2["cover"], "deezer": d2["deezer"], "bpm": d2["bpm"]})
            s.update(await asyncio.get_event_loop().run_in_executor(None, yt_search, s["artist"], s["title"]))
            s["id"] = "sim" + str(abs(hash((s["artist"], s["title"]))) % 10**9)
    return sims

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url"); ap.add_argument("--every", type=float, default=40); ap.add_argument("--clip", type=float, default=12)
    ap.add_argument("--limit-min", type=float, default=0); ap.add_argument("--out", default="../site/sets"); ap.add_argument("--no-similar", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    with tempfile.TemporaryDirectory() as wd:
        meta, mp3 = fetch(a.url, wd)
        dur = float(meta.get("duration") or 0)
        if a.limit_min:
            dur = min(dur, a.limit_min * 60)
        print(f"[{meta.get('id')}] {meta.get('title')} ({dur/60:.1f} min) downloaded in {time.time()-t0:.0f}s", file=sys.stderr)
        shazam = Shazam()
        hits, t = [], 0.0
        while t + a.clip <= dur:
            c = clip(mp3, t, a.clip, wd)
            r = await recognize(shazam, c)
            tr = norm(r) if r else None
            hits.append((t, tr))
            print(f"  {int(t)//60:02d}:{int(t)%60:02d}  {tr['artist'] + ' - ' + tr['title'] if tr else '·'}", file=sys.stderr)
            os.remove(c)
            t += a.every
            await asyncio.sleep(0.4)
    segs = merge(hits)
    if segs and segs[-1]['end'] is None and dur < float(meta.get('duration') or 0):
        segs[-1]['end'] = dur
    similar = {}
    async with aiohttp.ClientSession() as sess:
        done = {}
        for s in segs:
            tr = s["track"]
            if not tr:
                continue
            if tr["id"] in done:
                s["track"] = done[tr["id"]]; continue
            print(f"  enriching {tr['artist']} - {tr['title']}", file=sys.stderr)
            similar[tr["id"]] = await enrich_track(sess, tr, with_similar=not a.no_similar)
            done[tr["id"]] = tr
    result = {
        "source": {"url": a.url, "platform": meta.get("extractor_key"), "id": meta.get("id"), "title": meta.get("title"),
                   "channel": meta.get("uploader") or meta.get("channel"), "duration": float(meta.get("duration") or 0),
                   "thumbnail": meta.get("thumbnail"), "upload_date": meta.get("upload_date"), "views": meta.get("view_count")},
        "analysed": {"seconds": dur, "every": a.every, "clip": a.clip, "samples": len(hits),
                     "identified": sum(1 for _, x in hits if x), "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "took": round(time.time() - t0)},
        "segments": segs, "similar": similar,
    }
    key = f"{(meta.get('extractor_key') or 'x').lower()}-{meta.get('id')}"
    path = os.path.join(a.out, key + ".json")
    with open(path, "w") as f:
        json.dump(result, f, indent=1)
    n = len({s['track']['id'] for s in segs if s['track']})
    print(f"done: {n} tracks, {result['analysed']['identified']}/{len(hits)} samples identified, {time.time()-t0:.0f}s -> {path}", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main())
