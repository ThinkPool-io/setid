#!/usr/bin/env python3
"""Catalogue matcher: identify tracks in a DJ set without Shazam.

1. Build a reference catalogue from public 30 s Deezer previews of the artists we expect in the set
   (the DJ, plus anyone named in the comments), across all of their releases.
2. Fingerprint the previews with audfprint (open-source landmark fingerprinting, dpwe/audfprint),
   plus speed-shifted copies (-6 %..+6 %) because DJs ride the pitch fader.
3. Slide a window over the set, match each window against the catalogue, merge consecutive hits.
4. Merge the result into the set's JSON: audio matches become confirmed IDs; comment IDs they agree
   with are marked as confirmed by audio.

usage: python catalog_match.py <youtube-url> --artists "Adrian Mills,Stef de Haan" [--audio /path/set.mp3]
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
AFP = [sys.executable, os.path.join(HERE, "vendor", "audfprint", "audfprint.py")]
CACHE = os.path.join(HERE, "cache"); os.makedirs(CACHE, exist_ok=True)
SPEEDS = [0.94, 0.96, 0.98, 1.0, 1.02, 1.04, 1.06]

def dz(path):
    url = path if path.startswith("http") else "https://api.deezer.com" + path
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(url, timeout=20))
        except Exception:
            time.sleep(1 + i)
    return {}

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o"))

def catalogue(artist_names):
    """All tracks on all releases of each artist, deduped by title. Returns list of dicts with preview URLs."""
    tracks, seen = [], set()
    for name in artist_names:
        r = dz("/search/artist?q=" + urllib.parse.quote(name)).get("data", [])
        cand = [a for a in r if norm(a["name"]) == norm(name)]
        if not cand:
            print(f"  no Deezer artist for {name}", file=sys.stderr); continue
        a = cand[0]
        albums = dz(f"/artist/{a['id']}/albums?limit=200").get("data", [])
        print(f"  {a['name']}: {len(albums)} releases", file=sys.stderr)
        for al in albums:
            for t in dz(f"/album/{al['id']}/tracks?limit=100").get("data", []):
                k = norm(t["artist"]["name"] + t["title"])
                if k in seen or not t.get("preview"):
                    continue
                seen.add(k)
                tracks.append({"dz": t["id"], "artist": t["artist"]["name"], "title": t["title"], "preview": t["preview"],
                               "album": al["title"], "cover": al.get("cover_medium"), "link": t.get("link"), "released": (al.get("release_date") or "")[:4]})
    return tracks

def fetch_preview(t):
    """Polite download: Deezer rate-limits bursts, so go one at a time with backoff; never crash the run."""
    dst = os.path.join(CACHE, f"dz{t['dz']}.mp3")
    if os.path.exists(dst) and os.path.getsize(dst) > 10000:
        return dst
    url = t["preview"]
    for i in range(5):
        try:
            urllib.request.urlretrieve(url, dst)
            if os.path.getsize(dst) > 10000:
                time.sleep(0.4)
                return dst
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(5 * (i + 1)); continue
            if e.code in (403, 410):  # signed preview URL expired: get a fresh one
                url = dz(f"/track/{t['dz']}").get("preview") or url; continue
        except Exception:
            time.sleep(2)
    return None

def speed_variants(src, workdir):
    """Pitch-fader style speed change (tempo and pitch together), like a CDJ/turntable without key lock."""
    out = []
    for sp in SPEEDS:
        dst = os.path.join(workdir, f"{os.path.basename(src)[:-4]}@{sp:.2f}.wav")
        if sp == 1.0:
            filt = "aresample=11025"
        else:
            filt = f"asetrate={int(44100 * sp)},aresample=11025"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-af", filt, dst], check=True)
        out.append(dst)
    return out

def build_db(tracks, workdir, db):
    files = []
    paths = []
    for i, t in enumerate(tracks):
        paths.append(fetch_preview(t))
        if (i + 1) % 25 == 0:
            print(f"    {i+1}/{len(tracks)} previews", file=sys.stderr, flush=True)
    ok = [(t, p) for t, p in zip(tracks, paths) if p]
    print(f"  previews: {len(ok)}/{len(tracks)} downloaded", file=sys.stderr)
    with ThreadPoolExecutor(6) as ex:
        for vs in ex.map(lambda tp: speed_variants(tp[1], workdir), ok):
            files += vs
    listf = os.path.join(workdir, "refs.txt"); open(listf, "w").write("\n".join(files))
    subprocess.run(AFP + ["new", "--dbase", db, "--density", "40", "--samplerate", "11025", "--ncores", "6", "--list", listf],
                   check=True, capture_output=True)
    return {f"dz{t['dz']}": t for t, _ in ok}

def windows(set_audio, workdir, dur, win=20, hop=10):
    wav = os.path.join(workdir, "set.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", set_audio, "-ac", "1", "-ar", "11025", wav], check=True)
    outs, t = [], 0
    while t + win <= dur:
        dst = os.path.join(workdir, f"w_{t:05d}.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-t", str(win), "-i", wav, dst], check=True)
        outs.append((t, dst)); t += hop
    return outs

def match(db, wins, workdir):
    listf = os.path.join(workdir, "q.txt"); open(listf, "w").write("\n".join(p for _, p in wins))
    r = subprocess.run(AFP + ["match", "--dbase", db, "--density", "100", "--samplerate", "11025", "--ncores", "6", "--shifts", "4",
                              "--min-count", "6", "--max-matches", "1", "--list", listf],
                       capture_output=True, text=True)
    open(os.path.join(HERE, "logs", "last_match_raw.txt"), "w").write(r.stdout + "\n" + r.stderr[-2000:])
    hits = {}
    for line in r.stdout.splitlines():
        # "Matched /path/w_00120.wav 20.0 sec 1234 raw hashes as /path/dz123@1.02.wav at   3.2 s with    25 of    40 common hashes"
        # "Matched /tmp/w_00120.wav 19.8 sec 5583 raw hashes as /tmp/dz123@1.02.wav at 20.5 s with 9 of 285 common hashes at rank 0"
        m = re.search(r"Matched\s+(\S*w_(\d+)\.wav)\s.*?\sas\s+(\S*?(dz\d+)@([\d.]+)\.wav)\s.*?with\s+(\d+)\s+of\s+(\d+)", line)
        if m:
            hits[int(m.group(2))] = {"ref": m.group(4), "speed": float(m.group(5)), "common": int(m.group(6)), "of": int(m.group(7))}
    return hits

def merge_hits(hits, refs, hop=10, gap=3):
    segs = []
    for t in sorted(hits):
        h = hits[t]
        if segs and segs[-1]["ref"] == h["ref"] and t - segs[-1]["last"] <= hop * gap:
            segs[-1]["last"] = t; segs[-1]["n"] += 1; segs[-1]["best"] = max(segs[-1]["best"], h["common"]); segs[-1]["speeds"].append(h["speed"])
        else:
            segs.append({"ref": h["ref"], "start": t, "last": t, "n": 1, "best": h["common"], "speeds": [h["speed"]]})
    out = []
    for s in segs:
        if s["n"] < 2:  # a single window above threshold is not enough on its own
            continue
        r = refs[s["ref"]]
        sp = sorted(s["speeds"])[len(s["speeds"]) // 2]
        out.append({**s, "artist": r["artist"], "title": r["title"], "pitch": round((sp - 1) * 100)})
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("url"); ap.add_argument("--artists", required=True)
    ap.add_argument("--audio"); ap.add_argument("--out", default=os.path.join(HERE, "..", "sets"))
    ap.add_argument("--null", help="audio of an unrelated set, used to calibrate the false-match threshold")
    a = ap.parse_args(); t0 = time.time()
    meta = json.loads(subprocess.run([os.path.join(HERE, ".venv", "bin", "yt-dlp"), "-J", "--no-playlist", "--no-warnings", a.url], capture_output=True, text=True).stdout)
    key = f"{meta['extractor_key'].lower()}-{meta['id']}"; dur = float(meta["duration"])
    wd = tempfile.mkdtemp(prefix="cm_")
    try:
        audio = a.audio
        if not audio or not os.path.exists(audio):
            subprocess.run([os.path.join(HERE, ".venv", "bin", "yt-dlp"), "-q", "-x", "--audio-format", "mp3", "-o", os.path.join(wd, "set.%(ext)s"), a.url], check=True)
            audio = os.path.join(wd, "set.mp3")
        names = [x.strip() for x in a.artists.split(",") if x.strip()]
        print(f"building catalogue for: {', '.join(names)}", file=sys.stderr)
        tracks = catalogue(names)
        print(f"  {len(tracks)} unique tracks", file=sys.stderr)
        import hashlib
        tag = hashlib.sha1(("|".join(sorted(norm(n) for n in names)) + str(SPEEDS)).encode()).hexdigest()[:10]
        db = os.path.join(CACHE, f"cat_{tag}.pklz"); refsf = os.path.join(CACHE, f"cat_{tag}.json")
        if os.path.exists(db) and os.path.exists(refsf):
            refs = json.load(open(refsf)); print(f"  reusing fingerprint db ({len(refs)} tracks)", file=sys.stderr)
        else:
            refs = build_db(tracks, wd, db); json.dump(refs, open(refsf, "w"))
        print(f"  fingerprinted {len(refs)} tracks x {len(SPEEDS)} speeds in {time.time()-t0:.0f}s", file=sys.stderr)
        wins = windows(audio, wd, dur)
        hits = match(db, wins, wd)
        thr = 15
        if a.null and os.path.exists(a.null):
            nd = json.loads(subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", a.null], capture_output=True, text=True).stdout)["format"]["duration"]
            nwd = os.path.join(wd, "null"); os.makedirs(nwd)
            nhits = match(db, windows(a.null, nwd, min(float(nd), 3600), hop=25), nwd)
            ns = sorted(h["common"] for h in nhits.values())
            if ns:
                thr = max(12, ns[int(len(ns) * 0.99) - 1] + 1)
                print(f"  null calibration: {len(ns)} false matches on unrelated set, max {ns[-1]}, 99th pct {ns[int(len(ns)*0.99)-1]} -> threshold {thr}", file=sys.stderr)
        strong = {t: h for t, h in hits.items() if h["common"] >= thr}
        print(f"  {len(strong)}/{len(wins)} windows above threshold {thr}", file=sys.stderr)
        found = merge_hits(strong, refs, gap=3)
        print(f"  {len(hits)}/{len(wins)} windows matched, {len(found)} track segments", file=sys.stderr)
        for f in found:
            print(f"  {f['start']//60:02d}:{f['start']%60:02d}-{f['last']//60:02d}:{f['last']%60:02d}  {f['artist']} - {f['title']}  ({f['n']} windows, pitch {f['pitch']:+d}%)", file=sys.stderr)
        json.dump({"key": key, "threshold": thr, "found": found, "refs": refs, "windows": len(wins), "matched": len(hits), "catalogue": len(tracks), "artists": names,
                   "took": round(time.time() - t0)}, open(os.path.join(HERE, "logs", key + ".catalog.json"), "w"), indent=1)
    finally:
        shutil.rmtree(wd, ignore_errors=True)

if __name__ == "__main__":
    main()
