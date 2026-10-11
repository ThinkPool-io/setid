#!/usr/bin/env python3
"""Comment miner: build a set tracklist from YouTube comments, no audio recognition needed.

Sources, in order of trust:
  1. full tracklists posted in the description or a comment (5+ timestamped lines)
  2. "track ID @ 24:20?" questions paired with replies that answer "Artist - Title"
Answers that are just "ID", "?" or "ID - ID" are ignored. Each track records how many people gave it.

usage: python comments_tracklist.py <youtube-url> [--out ../sets] [--max 3000]
"""
import argparse, asyncio, json, os, re, subprocess, sys, time
from collections import defaultdict
import aiohttp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trackid  # reuse enrichment (Deezer, YouTube search, similar tracks)

TS = re.compile(r"(?<![\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?![\d:])")
ANSWER = re.compile(r"^\s*(?:\(soundcloud\)\s*)?(.+?)\s+[-–]\s+(.+?)\s*$", re.I)
JUNK = re.compile(r"^\s*(id|\?+|unknown|unreleased)\s*$", re.I)
FIRST = re.compile(r"\b(1st|first|opening|intro)\s+(track|song|tune)\b", re.I)
LAST = re.compile(r"\b(last|final|closing)\s+(track|song|tune|trackk)\b", re.I)

def secs(t):
    p = [int(x) for x in t.split(":")]
    return p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]

def clean(s):
    s = re.sub(r"@\S+", " ", s)                       # @mentions
    s = re.sub(r"\((?:soundcloud|sc)\)", " ", s, flags=re.I)
    s = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", " ", s)  # emoji
    return re.sub(r"\s+", " ", s).strip(" -–·|")

def parse_answer(text):
    lines = [clean(l) for l in text.splitlines() if clean(l)]
    if not lines:
        return None
    m = ANSWER.match(lines[0])
    if not m:
        return None
    a, b = m.group(1).strip(), m.group(2).strip()
    if JUNK.match(a) or JUNK.match(b) or len(a) < 2 or len(b) < 2 or len(a) + len(b) > 120:
        return None
    return a, b

def key_of(a, b):
    """Order-insensitive identity: people write both 'Artist - Title' and 'Title - Artist'."""
    norm = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower().replace("á", "a").replace("é", "e"))
    return tuple(sorted([norm(a), norm(b)]))

def orient(pairs, dj):
    """Pick 'Artist - Title' orientation: the side that contains the DJ name or a known artist is the artist."""
    a, b = pairs[0]
    djn = dj.lower().split()[-1] if dj else ""
    for x, y in pairs:
        if djn and djn in y.lower() and djn not in x.lower():
            return y, x
        if djn and djn in x.lower():
            return x, y
    return a, b

def fetch(url, max_comments):
    out = subprocess.run([trackid.YTDLP, "--skip-download", "--write-comments", "--no-warnings", "--extractor-args",
                          f"youtube:max_comments={max_comments},all,200,30;comment_sort=top", "-J", url],
                         capture_output=True, text=True, timeout=600).stdout
    return json.loads(out)

def mine(meta):
    cs = meta.get("comments") or []
    byid = {c["id"]: c for c in cs}
    dur = float(meta.get("duration") or 0)
    found = defaultdict(lambda: {"times": [], "votes": 0, "likes": 0, "pairs": [], "evidence": []})
    # 1) full tracklists in description or comments
    for src, text, likes in [("description", meta.get("description") or "", 0)] + [("comment", c.get("text", ""), c.get("like_count") or 0) for c in cs]:
        rows = []
        for line in text.splitlines():
            m = TS.search(line)
            if not m:
                continue
            rest = clean(line[m.end():])
            ans = parse_answer(rest) if rest else None
            if ans:
                rows.append((secs(m.group(1)), ans))
        if len(rows) >= 5:
            for t, (a, b) in rows:
                f = found[key_of(a, b)]; f["times"].append(t); f["votes"] += 2; f["likes"] += likes; f["pairs"].append((a, b)); f["evidence"].append(f"{src} tracklist")
    # 2) question -> answer replies
    for c in cs:
        if c.get("parent") in (None, "root"):
            continue
        ans = parse_answer(c.get("text", ""))
        if not ans:
            continue
        q = byid.get(c["parent"], {}).get("text", "")
        m = TS.search(q)
        if m:
            t = secs(m.group(1))
        elif FIRST.search(q):
            t = 0
        elif LAST.search(q):
            t = None  # placed at the end below
        else:
            continue
        f = found[key_of(*ans)]
        if t is not None:
            f["times"].append(t)
        else:
            f["last"] = True
        f["votes"] += 1; f["likes"] += c.get("like_count") or 0; f["pairs"].append(ans)
        f["evidence"].append(f"reply to \"{q.strip()[:60]}\"")
    # merge near-duplicates: one key's text contained in another's (e.g. a mangled @mention dropped a letter)
    keys = sorted(found, key=lambda k: -len("".join(k)))
    for i, big in enumerate(keys):
        if big not in found:
            continue
        for small in keys[i + 1:]:
            if small in found and small != big and all(any(x in y for y in big) for x in small):
                f, g = found[big], found.pop(small)
                f["times"] += g["times"]; f["votes"] += g["votes"]; f["likes"] += g["likes"]; f["evidence"] += g["evidence"]
                f["last"] = f.get("last") or g.get("last")
                f["pairs"] = f["pairs"] + g["pairs"]  # longer (more complete) spelling stays first
    dj = (meta.get("title") or "").split("|")[0].split("-")[-1].strip()
    rows = []
    for k, f in found.items():
        artist, title = orient(f["pairs"], dj)
        # prefer the best-capitalised spelling people used for each side
        caps = lambda x: sum(ch.isupper() for ch in x) + (2 if x[:1].isupper() else 0)
        def best(side):
            opts = [x for p in f["pairs"] for x in p if key_of(x, "") == key_of(side, "")]
            return max(opts, key=lambda x: (caps(x), len(x))) if opts else side
        artist, title = best(artist), best(title)
        start = min(f["times"]) if f["times"] else (max(0, dur - 240) if f.get("last") else None)
        if start is None:
            continue
        rows.append({"start": start, "artist": artist, "title": title, "votes": f["votes"], "likes": f["likes"],
                     "approx": not f["times"], "evidence": f["evidence"][:4]})
    # one spelling per artist across the whole set (best capitalised, accented if anyone used the accent)
    variants = defaultdict(list)
    for r in rows:
        variants[key_of(r["artist"], "")].append(r["artist"])
    score = lambda x: (sum(ch.isupper() for ch in x), sum(ord(ch) > 127 for ch in x), len(x))
    for r in rows:
        r["artist"] = max(variants[key_of(r["artist"], "")], key=score)
    rows.sort(key=lambda r: r["start"])
    return rows, len(cs)

def segments(rows, dur, span=240):
    """Each comment ID covers from its time until the next ID, capped at `span` seconds; gaps stay unidentified."""
    segs, cursor = [], 0
    for i, r in enumerate(rows):
        if r["start"] > cursor:
            segs.append({"start": cursor, "end": r["start"], "track": None, "hits": 0})
        nxt = rows[i + 1]["start"] if i + 1 < len(rows) else dur
        end = min(nxt, r["start"] + span) if not r["approx"] else dur
        tr = {"id": "cm" + str(abs(hash((r["artist"].lower(), r["title"].lower()))) % 10**9), "artist": r["artist"], "title": r["title"],
              "source": "comments", "votes": r["votes"], "likes": r["likes"], "approx": r["approx"], "evidence": r["evidence"]}
        segs.append({"start": r["start"], "end": end, "track": tr, "hits": r["votes"]})
        cursor = end
    if cursor < dur:
        segs.append({"start": cursor, "end": None, "track": None, "hits": 0})
    return segs

async def main():
    ap = argparse.ArgumentParser(); ap.add_argument("url"); ap.add_argument("--out", default=os.path.join(HERE, "..", "sets")); ap.add_argument("--max", type=int, default=3000)
    a = ap.parse_args(); t0 = time.time()
    meta = fetch(a.url, a.max)
    dur = float(meta.get("duration") or 0)
    rows, n = mine(meta)
    print(f"{n} comments scanned, {len(rows)} tracks named", file=sys.stderr)
    for r in rows:
        print(f"  {int(r['start'])//60:02d}:{int(r['start'])%60:02d}  {r['artist']} - {r['title']}  ({r['votes']} people{', time approximate' if r['approx'] else ''})", file=sys.stderr)
    segs = segments(rows, dur)
    similar = {}
    async with aiohttp.ClientSession() as sess:
        for s in segs:
            if s["track"]:
                similar[s["track"]["id"]] = await trackid.enrich_track(sess, s["track"])
    result = {
        "source": {"url": a.url, "platform": meta.get("extractor_key"), "id": meta.get("id"), "title": meta.get("title"),
                   "channel": meta.get("uploader") or meta.get("channel"), "duration": dur, "thumbnail": meta.get("thumbnail"),
                   "upload_date": meta.get("upload_date"), "views": meta.get("view_count")},
        "analysed": {"method": "comments", "comments": n, "named": len(rows), "samples": max(1, n), "identified": len(rows),
                     "every": 0, "clip": 0, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "took": round(time.time() - t0)},
        "segments": segs, "similar": similar,
    }
    path = os.path.join(a.out, f"{(meta.get('extractor_key') or 'x').lower()}-{meta.get('id')}.json")
    json.dump(result, open(path, "w"), indent=1)
    print(f"done: {len(rows)} tracks from comments -> {path}", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main())
