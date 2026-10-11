#!/usr/bin/env python3
"""SetID pipeline: DJ set URL -> timestamped tracklist (Shazam) -> similar tracks -> streaming links.

usage: python trackid.py <youtube-or-soundcloud-url> [--every 40] [--clip 12] [--limit-min 0] [--out ../sets]

Sources (all free, no keys): yt-dlp (audio), Shazam (ID), Deezer (BPM, previews, related artists),
MusicBrainz + ListenBrainz (track-level similarity), yt-dlp search (YouTube video ids for playlist export).
"""
import argparse, asyncio, json, os, subprocess, sys, tempfile, time, urllib.parse
import aiohttp
from shazamio import Shazam

YTDLP = os.path.join(os.path.dirname(sys.executable), "yt-dlp") if os.path.exists(os.path.join(os.path.dirname(sys.executable), "yt-dlp")) else "yt-dlp"
UA = {"User-Agent": "setid-prototype/0.1 (https://github.com/ThinkPool-io/setid)"}

def sh(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout

def fetch(url, workdir):
    meta = json.loads(sh([YTDLP, "-J", "--no-playlist", url]))
    out = os.path.join(workdir, "set.%(ext)s")
    for attempt in range(4):  # YouTube throws intermittent 403s; retry
        r = subprocess.run([YTDLP, "-q", "--no-playlist", "-x", "--audio-format", "mp3", "--audio-quality", "6", "-o", out, url])
        if r.returncode == 0 and os.path.exists(os.path.join(workdir, "set.mp3")):
            break
        print(f"  download attempt {attempt+1} failed, retrying", file=sys.stderr, flush=True); time.sleep(10 * (attempt + 1))
    else:
        print("failed: could not download the audio after 4 attempts", file=sys.stderr); sys.exit(3)
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

PROVIDERS = [p for p in os.environ.get("SETID_PROVIDERS", "shazam,audd,acrcloud").split(",") if p]
AUDD_TOKEN = os.environ.get("AUDD_TOKEN", "")
ACR = {k: os.environ.get("ACR_" + k, "") for k in ("HOST", "KEY", "SECRET")}
RATE_LIMITED = set()

async def recognize_shazam(shazam, path, retries=2):
    """Returns (normalised track or None, ok). ok=False means the provider failed (not 'no match')."""
    if "shazam" in RATE_LIMITED:
        return None, False
    for i in range(retries):
        try:
            r = await asyncio.wait_for(shazam.recognize(path), timeout=25)
            return norm(r), True
        except Exception as e:
            print(f"    shazam retry {i+1}: {type(e).__name__}", file=sys.stderr)
            await asyncio.sleep([8, 20][i])
    others = (AUDD_TOKEN and "audd" in PROVIDERS) or (ACR["KEY"] and "acrcloud" in PROVIDERS)
    if others:
        RATE_LIMITED.add("shazam")
        print("    shazam unavailable (rate limited or down), switching provider", file=sys.stderr)
        return None, False
    # Shazam is the only provider: wait for the rate limit to lift, then retry this same clip.
    waited = 0
    max_wait = int(os.environ.get("SETID_SHAZAM_MAX_WAIT", str(90 * 60)))
    while waited < max_wait:
        code = await shazam_probe()
        if code != 429:
            print(f"    shazam back after {waited // 60} min, resuming", file=sys.stderr, flush=True)
            try:
                r = await asyncio.wait_for(shazam.recognize(path), timeout=25)
                return norm(r), True
            except Exception as e:
                print(f"    shazam still failing: {type(e).__name__}", file=sys.stderr, flush=True)
        print(f"    waiting for Shazam rate limit to lift ({waited // 60} min so far)", file=sys.stderr, flush=True)
        await asyncio.sleep(120); waited += 120
    RATE_LIMITED.add("shazam")
    print(f"    shazam still rate limited after {max_wait // 60} min, continuing without it", file=sys.stderr)
    return None, False

async def shazam_probe():
    url = "https://amp.shazam.com/discovery/v5/en/GB/iphone/-/tag/0/0?sync=true&webv3=true&sampling=true&connected=&shazamapiversion=v3&sharehub=true&video=v0"
    body = {"timezone": "Europe/London", "signature": {"uri": "data:audio/vnd.shazam.sig;base64,AA==", "samplems": 1000}, "timestamp": 1, "context": {}, "geolocation": {}}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=body, headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=15)) as r:
                return r.status
    except Exception:
        return 0

async def recognize_audd(sess, path):
    if not AUDD_TOKEN:
        return None, False
    try:
        form = aiohttp.FormData(); form.add_field("api_token", AUDD_TOKEN); form.add_field("return", "apple_music,deezer,spotify")
        form.add_field("file", open(path, "rb"), filename="clip.mp3", content_type="audio/mpeg")
        async with sess.post("https://api.audd.io/", data=form, timeout=aiohttp.ClientTimeout(total=30)) as r:
            j = await r.json(content_type=None)
    except Exception as e:
        print(f"    audd error: {type(e).__name__}", file=sys.stderr); return None, False
    if j.get("status") != "success":
        print(f"    audd: {j.get('error', {}).get('error_message', j.get('status'))}", file=sys.stderr); return None, False
    t = j.get("result")
    if not t:
        return None, True
    am, dz, sp = t.get("apple_music") or {}, t.get("deezer") or {}, t.get("spotify") or {}
    return {"id": "ad" + str(abs(hash((t.get("artist"), t.get("title")))) % 10**9), "title": t.get("title"), "artist": t.get("artist"),
            "cover": (am.get("artwork") or {}).get("url", "").replace("{w}", "400").replace("{h}", "400") or (dz.get("album") or {}).get("cover_medium"),
            "label": t.get("label"), "released": (t.get("release_date") or "")[:4] or None, "apple": am.get("url"),
            "preview": (am.get("previews") or [{}])[0].get("url") or dz.get("preview"), "deezer": dz.get("link"),
            "spotifyUri": sp.get("uri"), "provider": "audd"}, True

async def recognize_acr(sess, path):
    if not (ACR["HOST"] and ACR["KEY"] and ACR["SECRET"]):
        return None, False
    import base64, hashlib, hmac
    ts = str(int(time.time()))
    sig = base64.b64encode(hmac.new(ACR["SECRET"].encode(), "\n".join(["POST", "/v1/identify", ACR["KEY"], "audio", "1", ts]).encode(), hashlib.sha1).digest()).decode()
    data = open(path, "rb").read()
    form = aiohttp.FormData()
    for k, v in {"access_key": ACR["KEY"], "sample_bytes": str(len(data)), "timestamp": ts, "signature": sig, "data_type": "audio", "signature_version": "1"}.items():
        form.add_field(k, v)
    form.add_field("sample", data, filename="clip.mp3", content_type="audio/mpeg")
    try:
        async with sess.post(f"https://{ACR['HOST']}/v1/identify", data=form, timeout=aiohttp.ClientTimeout(total=30)) as r:
            j = await r.json(content_type=None)
    except Exception as e:
        print(f"    acrcloud error: {type(e).__name__}", file=sys.stderr); return None, False
    code = (j.get("status") or {}).get("code")
    if code == 1001:
        return None, True
    if code != 0:
        print(f"    acrcloud: {(j.get('status') or {}).get('msg')}", file=sys.stderr); return None, False
    m = ((j.get("metadata") or {}).get("music") or [{}])[0]
    artist = ", ".join(a.get("name", "") for a in m.get("artists", []))
    return {"id": "acr" + str(m.get("acrid", "")[:12]), "title": m.get("title"), "artist": artist, "label": m.get("label"),
            "released": (m.get("release_date") or "")[:4] or None, "provider": "acrcloud"}, True

async def recognize(shazam, sess, path):
    for p in PROVIDERS:
        if p == "shazam":
            tr, ok = await recognize_shazam(shazam, path)
        elif p == "audd":
            tr, ok = await recognize_audd(sess, path)
        elif p == "acrcloud":
            tr, ok = await recognize_acr(sess, path)
        else:
            continue
        if ok:
            if tr: tr.setdefault("provider", p)
            return tr
    return None

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
        j = subprocess.run([YTDLP, "--flat-playlist", "-j", "--no-warnings", f"ytsearch1:{artist} - {title}"], check=True, capture_output=True, text=True, timeout=40).stdout
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
    ap.add_argument("--limit-min", type=float, default=0); ap.add_argument("--out", default="../site/sets"); ap.add_argument("--no-similar", action="store_true"); ap.add_argument("--save-audio", help="keep a copy of the downloaded audio here")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    with tempfile.TemporaryDirectory() as wd:
        meta, mp3 = fetch(a.url, wd)
        if a.save_audio:
            import shutil; shutil.copyfile(mp3, a.save_audio)
        dur = float(meta.get("duration") or 0)
        if a.limit_min:
            dur = min(dur, a.limit_min * 60)
        print(f"[{meta.get('id')}] {meta.get('title')} ({dur/60:.1f} min) downloaded in {time.time()-t0:.0f}s", file=sys.stderr)
        shazam = Shazam()
        hits, t = [], 0.0
        print(f"  providers: {', '.join(p for p in PROVIDERS if p == 'shazam' or (p == 'audd' and AUDD_TOKEN) or (p == 'acrcloud' and ACR['KEY']))}", file=sys.stderr)
        async with aiohttp.ClientSession() as rsess:
          while t + a.clip <= dur:
            c = clip(mp3, t, a.clip, wd)
            tr = await recognize(shazam, rsess, c)
            hits.append((t, tr))
            print(f"  {int(t)//60:02d}:{int(t)%60:02d}  {tr['artist'] + ' - ' + tr['title'] if tr else '·'}", file=sys.stderr, flush=True)
            os.remove(c)
            t += a.every
            await asyncio.sleep(3)
            if len(RATE_LIMITED) >= len([p for p in PROVIDERS if p == 'shazam' or (p == 'audd' and AUDD_TOKEN) or (p == 'acrcloud' and ACR['KEY'])]):
                print("  all identification providers unavailable, stopping early", file=sys.stderr); break
    if not any(h for _, h in hits) and RATE_LIMITED:
        print("failed: no identification provider available (Shazam rate-limited and no AudD/ACRCloud key). Nothing saved.", file=sys.stderr); sys.exit(2)
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
        "analysed": {"providers": sorted({h["provider"] for _, h in hits if h and h.get("provider")}), "seconds": dur, "every": a.every, "clip": a.clip, "samples": len(hits),
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
