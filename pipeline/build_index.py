#!/usr/bin/env python3
"""Rebuild sets/index.json from the set JSON files."""
import glob, json, os
here = os.path.dirname(os.path.abspath(__file__))
sets_dir = os.path.join(here, "..", "sets")
rows = []
for p in sorted(glob.glob(os.path.join(sets_dir, "*.json"))):
    if p.endswith("index.json"):
        continue
    d = json.load(open(p))
    segs = d["segments"]
    dur = d["source"]["duration"] or 1
    covered = sum(((s["end"] if s["end"] is not None else dur) - s["start"]) for s in segs if s["track"])
    rows.append({
        "key": os.path.basename(p)[:-5], "title": d["source"]["title"], "channel": d["source"]["channel"],
        "url": d["source"]["url"], "thumbnail": d["source"]["thumbnail"], "duration": dur, "views": d["source"].get("views"),
        "tracks": len({s["track"]["id"] for s in segs if s["track"]}), "coverage": round(covered / dur, 3), "ran_at": d["analysed"]["ran_at"],
    })
rows.sort(key=lambda r: -(r["views"] or 0))
json.dump(rows, open(os.path.join(sets_dir, "index.json"), "w"), indent=1)
print(f"{len(rows)} sets indexed")
for r in rows:
    print(f"  {r['key']}: {r['tracks']} tracks, {int(r['coverage']*100)}% covered, {r['title']}")
