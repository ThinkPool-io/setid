#!/usr/bin/env python3
"""Merge every evidence source for one set into sets/<key>.json.

Sources (any subset):
  --shazam    set JSON written by trackid.py (Shazam samples)            -> source "shazam"
  --catalog   logs/<key>.catalog.json from catalog_match.py (audfprint) -> source "audio"
  --comments  set JSON written by comments_tracklist.py                 -> source "comments"

Rules: Shazam IDs are placed first. Catalogue matches fill stretches Shazam left unidentified (or agree
with Shazam, which adds evidence). Comment IDs that name a track already heard within 3 minutes become
"confirmed by audio" on that row; the rest are shown only in gaps, labelled not audio-confirmed.

usage: python merge_sources.py <key> [--shazam f] [--catalog f] [--comments f]
       (with no flags, the single-source Adrián layout is reused: sets/<key>.json + logs/<key>.catalog.json)
"""
import argparse, asyncio, copy, json, os, re, sys, time
import aiohttp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trackid

def norm(s):
    s = (s or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ö", "o")):
        s = s.replace(a, b)
    s = re.sub(r"\(.*?\)|\[.*?\]|feat\..*|ft\..*", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)

def same(t1, t2):
    import difflib
    a, b = norm(t1["title"]), norm(t2["title"])
    return bool(a) and bool(b) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8)

def load(p):
    return json.load(open(p)) if p and os.path.exists(p) else None

async def main():
    ap = argparse.ArgumentParser(); ap.add_argument("key")
    ap.add_argument("--shazam"); ap.add_argument("--catalog"); ap.add_argument("--comments")
    a = ap.parse_args()
    setp = os.path.join(HERE, "..", "sets", a.key + ".json")
    shz, cat, com = load(a.shazam), load(a.catalog or os.path.join(HERE, "logs", a.key + ".catalog.json")), load(a.comments)
    if not (a.shazam or a.comments):  # legacy: the existing set file holds the comment IDs
        com = load(setp)
    base = shz or com or load(setp)
    dur = base["source"]["duration"]
    similar = {}
    for src in (shz, com, load(setp)):
        if src:
            similar.update(src.get("similar", {}))

    rows = []  # {start, end, track}
    if shz:
        for s in shz["segments"]:
            if s["track"]:
                t = dict(s["track"]); t["source"] = "shazam"; t["samples"] = s.get("hits", 1)
                rows.append({"start": s["start"], "end": s["end"] if s["end"] is not None else dur, "track": t})
    if cat:
        for f in cat["found"]:
            r = cat["refs"][f["ref"]]
            t = {"id": f["ref"], "artist": r["artist"], "title": r["title"], "cover": r.get("cover"), "deezer": r.get("link"), "claimed": f.get("claimed") or "",
                 "preview": r.get("preview"), "released": r.get("released"), "album": r.get("album"), "source": "audio",
                 "windows": f["n"], "pitch": f["pitch"], "score": f["best"]}
            st, en = f["start"], min(dur, f["last"] + 20)
            if f.get("claimedAt") is not None and abs(st - f["claimedAt"]) > 180 and not any(
                    x["track"]["source"] == "shazam" and same(x["track"], t) and abs(x["start"] - st) <= 180 for x in rows):
                continue  # heard far from where anyone placed it: shared loop or sample, not the track
            agree = next((x for x in rows if x["track"]["source"] == "shazam" and same(x["track"], t) and x["start"] - 120 <= st <= x["end"] + 120), None)
            if agree:
                agree["track"]["catalog"] = True; agree["track"].setdefault("pitch", f["pitch"]); continue
            clash = any(x["track"]["source"] == "shazam" and x["start"] < en and st < x["end"] for x in rows)
            if clash:
                continue  # Shazam already named this stretch as something else
            prev = next((x for x in reversed(rows) if x["track"]["source"] == "audio" and (x["track"]["id"] == t["id"] or same(x["track"], t)) and st - x["end"] <= 60), None)
            if prev:
                prev["end"] = en; prev["track"]["windows"] += f["n"]; continue
            rows.append({"start": st, "end": en, "track": t})
    rows.sort(key=lambda r: r["start"])

    if com:  # a single Shazam clip loses to a comment ID that 3+ people agree on at the same moment
        strong = [c for c in com["segments"] if c["track"] and c["track"].get("votes", 1) >= 3]
        def overruled(r):
            t = r["track"]
            return t["source"] == "shazam" and t.get("samples", 1) == 1 and not t.get("catalog") and any(
                c["start"] - 60 <= r["start"] <= c["start"] + 240 and not same(t, c["track"]) for c in strong)
        dropped = [r for r in rows if overruled(r)]
        rows = [r for r in rows if not overruled(r)]
        for r in dropped:
            print(f"  overruled single Shazam clip at {int(r['start'])//60}:{int(r['start'])%60:02d}: {r['track']['artist']} - {r['track']['title']}", file=sys.stderr)
    comment_only = []
    if com:
        for s in com["segments"]:
            ct = s["track"]
            if not ct or ct.get("source") not in ("comments", "both"):
                continue
            ct = dict(ct); ct["source"] = "comments"
            hit = next((r for r in rows if same(r["track"], ct) and r["start"] - 180 <= s["start"] <= r["end"] + 180), None)
            if not hit and cat:  # same claim the catalogue was built from (title may differ: original vs edit)
                hit = next((r for r in rows if r["track"]["source"] == "audio" and r["track"].get("claimed", "").lower() == f"{ct['artist']} - {ct['title']}".lower()), None)
            if hit:
                hit["track"]["commentVotes"] = hit["track"].get("commentVotes", 0) + ct.get("votes", 1)
                hit["track"]["evidence"] = ct.get("evidence", [])
                differs = norm(ct["title"]) != norm(hit["track"]["title"]) or re.sub(r"[^a-z0-9]", "", ct["title"].lower()) != re.sub(r"[^a-z0-9]", "", hit["track"]["title"].lower())
                if ct.get("votes", 1) >= 3 and (hit["track"]["source"] == "audio" or (hit["track"]["source"] == "shazam" and differs)):
                    hit["track"]["matchedAs"] = f"{hit['track']['artist']} - {hit['track']['title']}"
                    hit["track"]["artist"], hit["track"]["title"] = ct["artist"], ct["title"]
                    hit["start"] = min(hit["start"], s["start"])
            else:
                comment_only.append({"start": s["start"], "track": ct})
    # an uncorroborated single Shazam clip in a mixed set is usually a transition misfire: hide it
    hidden = [r for r in rows if r["track"]["source"] == "shazam" and r["track"].get("samples", 1) == 1
              and not r["track"].get("catalog") and not r["track"].get("commentVotes")]
    rows = [r for r in rows if r not in hidden]
    for r in hidden:
        print(f"  hid single-clip guess at {int(r['start'])//60}:{int(r['start'])%60:02d}: {r['track']['artist']} - {r['track']['title']}", file=sys.stderr)
    claimed_starts = sorted(c["start"] for c in comment_only)
    audio_rows = list(rows)
    for c in comment_only:
        st = c["start"]
        inside = next((r for r in audio_rows if r["start"] <= st < r["end"]), None)
        if inside:
            c["track"]["askedAt"] = st; st = inside["end"]
        # end at the next thing anyone placed: an audio row or the next claimed comment time
        nxt = min([r["start"] for r in audio_rows if r["start"] > st] + [x for x in claimed_starts if x > st] + [dur])
        en = dur if c["track"].get("approx") else min(st + 240, nxt)
        if en - st >= 20:
            rows.append({"start": st, "end": en, "track": c["track"]})
    rows.sort(key=lambda r: r["start"])

    out, cursor = [], 0
    for r in rows:
        if r["start"] < cursor:
            r["start"] = cursor
            if r["end"] - r["start"] < 20:
                continue
        if r["start"] > cursor + 20:
            out.append({"start": cursor, "end": r["start"], "track": None, "hits": 0})
        elif out and r["start"] > cursor:  # sliver gap: let the previous row run on
            out[-1]["end"] = r["start"]
        t = r["track"]
        out.append({"start": r["start"], "end": r["end"], "track": t, "hits": t.get("samples") or t.get("windows") or t.get("votes") or 1})
        cursor = r["end"]
    if cursor < dur - 5:
        out.append({"start": cursor, "end": None, "track": None, "hits": 0})
    for i, s in enumerate(out):
        s["end"] = out[i + 1]["start"] if i + 1 < len(out) else None

    async with aiohttp.ClientSession() as sess:
        for s in out:
            t = s["track"]
            if t and t["id"] not in similar:
                similar[t["id"]] = await trackid.enrich_track(sess, t)
    similar = {k: v for k, v in similar.items() if any(s["track"] and s["track"]["id"] == k for s in out)}

    count = lambda pred: sum(1 for s in out if s["track"] and pred(s["track"]))
    d = copy.deepcopy(base)
    d["segments"], d["similar"] = out, similar
    an = d.setdefault("analysed", {})
    an.update({"method": "multi", "shazamRows": count(lambda t: t["source"] == "shazam"), "audioRows": count(lambda t: t["source"] == "audio"),
               "commentRows": count(lambda t: t["source"] == "comments"), "commentConfirmed": count(lambda t: t.get("commentVotes")),
               "catalogue": cat and cat.get("catalogue"), "catalogueArtists": cat and cat.get("artists"),
               "comments": com and com.get("analysed", {}).get("comments"),
               "shazamSamples": shz and shz["analysed"].get("samples"), "shazamEvery": shz and shz["analysed"].get("every"),
               "hiddenGuesses": len(hidden), "identified": count(lambda t: True), "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    json.dump(d, open(setp, "w"), indent=1)
    print(f"merged -> {setp}: shazam {an['shazamRows']}, catalogue {an['audioRows']}, comment-only {an['commentRows']}, comments confirmed by audio {an['commentConfirmed']}", file=sys.stderr)
    for s in out:
        t = s["track"]
        tag = "" if not t else f"[{t['source']}{'+comments' if t.get('commentVotes') else ''}{'+catalogue' if t.get('catalog') else ''}]"
        print(f"  {int(s['start'])//60:02d}:{int(s['start'])%60:02d}  {(t['artist'] + ' - ' + t['title']) if t else '·'}  {tag}", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main())
