#!/usr/bin/env python3
"""Merge catalogue audio matches (catalog_match.py) with comment IDs (comments_tracklist.py) into one set JSON.

Audio matches are the stronger evidence and win on overlap. A comment ID that names the same track
within 3 minutes of an audio match becomes "both" (heard in the audio and named by people).

usage: python merge_sources.py youtube-08__IepUcFA
"""
import asyncio, json, os, re, sys, time
import aiohttp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trackid

def norm(s):
    s = s.lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "", s)

async def main(key):
    setp = os.path.join(HERE, "..", "sets", key + ".json")
    catp = os.path.join(HERE, "logs", key + ".catalog.json")
    d, cat = json.load(open(setp)), json.load(open(catp))
    dur = d["source"]["duration"]
    old_similar = d.get("similar", {})
    comments = [s for s in d["segments"] if s["track"] and s["track"].get("source") in ("comments", "both")]
    comments = [{"start": s["start"], "track": dict(s["track"])} for s in comments]
    for c in comments:  # a re-merge starts from the comment evidence only
        c["track"]["source"] = "comments"

    audio = []
    for f in cat["found"]:
        r = cat["refs"][f["ref"]]
        audio.append({"start": f["start"], "end": min(dur, f["last"] + 20), "track": {
            "id": f["ref"], "artist": r["artist"], "title": r["title"], "cover": r.get("cover"), "deezer": r.get("link"),
            "preview": r.get("preview"), "released": r.get("released"), "album": r.get("album"), "source": "audio",
            "windows": f["n"], "pitch": f["pitch"], "score": f["best"]}})
    # merge consecutive audio segments of the same track separated by a short gap
    merged = []
    for s in sorted(audio, key=lambda x: x["start"]):
        if merged and merged[-1]["track"]["id"] == s["track"]["id"] and s["start"] - merged[-1]["end"] <= 60:
            merged[-1]["end"] = s["end"]; merged[-1]["track"]["windows"] += s["track"]["windows"]
        else:
            merged.append(s)
    audio = merged

    kept = []
    for c in comments:
        ct = c["track"]
        hit = next((a for a in audio if (norm(ct["title"]) in norm(a["track"]["title"]) or norm(a["track"]["title"]) in norm(ct["title"]))
                    and abs(a["start"] - c["start"]) <= 180), None)
        if hit:
            hit["track"]["source"] = "both"; hit["track"]["votes"] = ct.get("votes", 1); hit["track"]["evidence"] = ct.get("evidence", [])
            hit["track"]["commentAt"] = c["start"]
        else:
            kept.append(c)

    segs = [dict(a, hits=a["track"]["windows"]) for a in audio]
    for c in kept:
        start = c["start"]
        inside = next((a for a in audio if a["start"] <= start < a["end"]), None)
        if inside:
            c["track"]["askedAt"] = start; start = inside["end"]
        nxt = min([a["start"] for a in audio if a["start"] > start] + [dur])
        end = dur if c["track"].get("approx") else min(start + 240, nxt)
        if end - start < 20:
            continue
        segs.append({"start": start, "end": end, "track": c["track"], "hits": c["track"].get("votes", 1)})
    segs.sort(key=lambda s: s["start"])
    out, cursor = [], 0
    for s in segs:
        if s["start"] < cursor:  # overlap: audio already placed, trim the later one
            s["start"] = cursor
            if s["end"] is not None and s["end"] - s["start"] < 20:
                continue
        if s["start"] > cursor + 5:
            out.append({"start": cursor, "end": s["start"], "track": None, "hits": 0})
        out.append(s); cursor = s["end"] if s["end"] is not None else dur
    if cursor < dur - 5:
        out.append({"start": cursor, "end": None, "track": None, "hits": 0})
    for i, s in enumerate(out):
        if i + 1 < len(out):
            s["end"] = out[i + 1]["start"]
    out[-1]["end"] = None

    similar = {}
    async with aiohttp.ClientSession() as sess:
        for s in out:
            t = s["track"]
            if not t or t["id"] in similar:
                continue
            if t["id"] in old_similar:
                similar[t["id"]] = old_similar[t["id"]]
            else:
                similar[t["id"]] = await trackid.enrich_track(sess, t)
    n_audio = sum(1 for s in out if s["track"] and s["track"]["source"] in ("audio", "both"))
    n_comm = sum(1 for s in out if s["track"] and s["track"]["source"] == "comments")
    d["segments"], d["similar"] = out, similar
    d["analysed"].update({"method": "comments+audio", "audioMatches": n_audio, "commentOnly": n_comm, "threshold": cat.get("threshold"),
                          "catalogue": cat.get("catalogue"), "catalogueArtists": cat.get("artists"), "identified": n_audio + n_comm,
                          "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    json.dump(d, open(setp, "w"), indent=1)
    print(f"merged: {n_audio} audio-matched rows ({sum(1 for s in out if s['track'] and s['track']['source']=='both')} also named in comments), {n_comm} comment-only rows", file=sys.stderr)
    for s in out:
        t = s["track"]
        print(f"  {int(s['start'])//60:02d}:{int(s['start'])%60:02d}  {(t['artist'] + ' - ' + t['title']) if t else '·'}  {('[' + t['source'] + ']') if t else ''}", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
