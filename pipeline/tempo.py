#!/usr/bin/env python3
"""Played-at tempo: how fast the DJ actually played each track, versus its released tempo.

played BPM   : estimated from the set audio inside each identified segment (librosa onset tempo)
released BPM : estimated the same way from the track's 30 s Deezer preview, so both numbers come from
               one estimator (Deezer's own bpm field is mostly 0 for this music)
delta        : played / released, folded across half/double-time; dropped if implausible (>30 %)
The catalogue matcher's fingerprint speed (pitch %) is used as a cross-check when present.

usage: python tempo.py <set-key> --audio /path/to/set.mp3
"""
import argparse, json, os, re, sys, urllib.request, warnings
import numpy as np
warnings.filterwarnings("ignore")
import librosa

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
SR = 22050

def tempo_of(y, sr=SR, lo=95, hi=190):
    """Precise tempo: coarse estimate, then beat tracking at a fine hop, then a straight-line fit through the beat
    times (period = slope). Precision is well under 1 %, unlike the ~6 % grid of a plain tempogram peak.
    Returns (bpm, steadiness 0-1) or (None, 0)."""
    if y is None or len(y) < sr * 8:
        return None, 0.0
    if float(np.sqrt(np.mean(np.square(y)))) < 1e-3:  # silence
        return None, 0.0
    hop = 128
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, aggregate=np.median)
    coarse = float(librosa.feature.tempo(onset_envelope=oenv, sr=sr, hop_length=hop, start_bpm=140, max_tempo=320)[0])
    if coarse <= 0:
        return None, 0.0
    while coarse < lo: coarse *= 2
    while coarse >= hi: coarse /= 2
    _, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, hop_length=hop, bpm=coarse, tightness=400, units="time")
    if len(beats) < 12:
        return None, 0.0
    idx = np.arange(len(beats))
    slope, icpt = np.polyfit(idx, beats, 1)
    resid = beats - (slope * idx + icpt)
    steadiness = float(max(0.0, 1.0 - np.std(resid) / (slope * 0.15)))  # jitter vs 15 % of a beat
    bpm = 60.0 / slope
    while bpm < lo: bpm *= 2
    while bpm >= hi: bpm /= 2
    return round(bpm, 1), round(steadiness, 2)

def load_set(path):
    y, _ = librosa.load(path, sr=SR, mono=True)
    return y

def preview_audio(t):
    m = re.search(r"/track/(\d+)", t.get("deezer") or "") or re.match(r"dz(\d+)$", t.get("id", ""))
    dz_id = m.group(1) if m else None
    path = os.path.join(CACHE, f"dz{dz_id}.mp3") if dz_id else None
    if path and not os.path.exists(path):
        url = None
        try:
            url = json.load(urllib.request.urlopen(f"https://api.deezer.com/track/{dz_id}", timeout=15)).get("preview")
        except Exception:
            pass
        url = url or t.get("preview")
        if url:
            try:
                urllib.request.urlretrieve(url, path)
            except Exception:
                path = None
    if path and os.path.exists(path) and os.path.getsize(path) > 10000:
        try:
            y, _ = librosa.load(path, sr=SR, mono=True)
            return y
        except Exception:
            return None
    return None

def fold_ratio(played, orig):
    best = None
    for k in (0.5, 1.0, 2.0):
        o = orig * k
        r = played / o
        if best is None or abs(np.log(r)) < abs(np.log(best[1])):
            best = (o, r)
    return best

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("key"); ap.add_argument("--audio", required=True)
    a = ap.parse_args()
    setp = os.path.join(HERE, "..", "sets", a.key + ".json")
    d = json.load(open(setp))
    y = load_set(a.audio)
    dur = len(y) / SR
    # set-wide tempo curve: 20 s windows every 10 s, steady readings only, then a 2-minute rolling median
    pts = []
    for w0 in np.arange(0, max(0, dur - 20), 10):
        bpm, st = tempo_of(y[int(w0 * SR):int((w0 + 20) * SR)])
        if bpm and st >= 0.5:
            pts.append((w0 + 10, bpm))
    if pts:
        med = float(np.median([b for _, b in pts]))
        pts = [(t, b) for t, b in pts if abs(b - med) / med <= 0.10]  # half/three-quarter-time misreads
    def curve_at(t0, t1):
        vals = [b for t, b in pts if t0 <= t <= t1]
        if len(vals) < 2:
            mid = (t0 + t1) / 2
            vals = [b for t, b in pts if abs(t - mid) <= 90]
        return round(float(np.median(vals)), 1) if len(vals) >= 2 else None
    smooth = []
    for t in np.arange(0, dur, 30):
        v = curve_at(t - 60, t + 60)
        if v:
            smooth.append([int(t), v])
    d["tempoCurve"] = smooth
    print(f"  tempo curve: {len(pts)} steady windows, {smooth[0][1] if smooth else '-'} -> {smooth[-1][1] if smooth else '-'} BPM", file=sys.stderr)
    n_played = n_orig = 0
    for s in d["segments"]:
        t = s["track"]
        if not t:
            continue
        st = s["start"]; en = s["end"] if s["end"] is not None else dur
        # middle of the segment, away from the mixes in/out
        mid0 = st + (en - st) * 0.25; mid1 = min(en - (en - st) * 0.15, mid0 + 60)
        if mid1 - mid0 < 10:
            mid0, mid1 = st, en
        played, conf = curve_at(st + 10, en - 10), 1.0
        for k in ("playedBpm", "originalBpm", "tempoDelta", "tempoConf"):
            t.pop(k, None)
        if not played or conf < 0.35:
            print(f"  {int(st)//60:02d}:{int(st)%60:02d}  {t['artist']} - {t['title']}: no steady beat (conf {conf})", file=sys.stderr)
            continue
        t["playedBpm"] = round(played, 1); t["tempoConf"] = conf; n_played += 1
        py = preview_audio(t)
        orig, oconf = tempo_of(py, lo=60, hi=200) if py is not None else (None, 0)
        if orig and oconf >= 0.35:
            o, r = fold_ratio(played, orig)
            delta = (r - 1) * 100
            pitch = t.get("pitch")  # fingerprint speed, coarse but independent
            agree = pitch is None or abs(delta - pitch) <= 6
            if abs(delta) <= 30 and agree:
                t["originalBpm"] = round(o, 1); t["tempoDelta"] = round(delta, 1); n_orig += 1
            elif pitch is not None and abs(pitch) <= 30:
                t["originalBpm"] = round(played / (1 + pitch / 100)); t["tempoDelta"] = pitch; n_orig += 1
        elif t.get("pitch") is not None and t.get("source") in ("audio",) :
            t["originalBpm"] = round(played / (1 + t["pitch"] / 100)); t["tempoDelta"] = t["pitch"]; n_orig += 1
        extra = f", released {t['originalBpm']} ({t['tempoDelta']:+.1f}%)" if "originalBpm" in t else ""
        print(f"  {int(st)//60:02d}:{int(st)%60:02d}  {t['artist']} - {t['title']}: played {t['playedBpm']}{extra}", file=sys.stderr)
    # sanity: DJs move tempo gradually; a reading far from the set's median is a misread (half/three-quarter time)
    vals = [s["track"]["playedBpm"] for s in d["segments"] if s["track"] and s["track"].get("playedBpm")]
    if vals:
        med = float(np.median(vals))
        for s in d["segments"]:
            t = s["track"]
            if t and t.get("playedBpm") and abs(t["playedBpm"] - med) / med > 0.10:
                print(f"  dropped misread {t['playedBpm']} BPM for {t['title']} (set median {med:.0f})", file=sys.stderr)
                for k in ("playedBpm", "originalBpm", "tempoDelta", "tempoConf"):
                    t.pop(k, None)
                n_played -= 1
            elif t and t.get("tempoDelta") is not None and abs(t["tempoDelta"]) > 20:
                t.pop("originalBpm", None); t.pop("tempoDelta", None); n_orig -= 1
    d.setdefault("analysed", {})["tempo"] = {"played": n_played, "withOriginal": n_orig}
    json.dump(d, open(setp, "w"), indent=1)
    print(f"tempo: {n_played} tracks with played BPM, {n_orig} with released BPM", file=sys.stderr)

if __name__ == "__main__":
    main()
