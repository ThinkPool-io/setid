#!/usr/bin/env python3
"""SetID worker for the Vercel deployment.

Polls Vercel Blob for queued jobs (no inbound connection, no tunnel), runs the full pipeline on each set,
streams progress into the job record (which the site's tracker reads), and publishes the finished set.

Start it with project credentials injected by the Vercel CLI (nothing secret on disk or in the shell):
    cd ~/projects/setid && vercel env run -e production -- pipeline/.venv/bin/python pipeline/vworker.py

Stages per set: Shazam (12 s clips) -> YouTube comments -> targeted audio check of named tracks ->
merge -> played-at tempo. Each stage is optional; the set is published with whatever evidence exists.
"""
import json, os, re, shutil, socket, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(HERE, ".venv", "bin", "python")
LOGS = os.path.join(HERE, "logs")
NULL_AUDIO = os.path.join(HERE, "cache", "null.mp3")  # an unrelated set, for false-match calibration
POLL = 10

def blob(*args):
    r = subprocess.run(["node", os.path.join(HERE, "blob.mjs"), *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"blob {args[0]} failed: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout or "null")

def put_json(pathname, data):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        tmp = f.name
    try:
        return blob("put", pathname, tmp)
    finally:
        os.unlink(tmp)

def fetch_json(url):
    with urllib.request.urlopen(f"{url}?ts={int(time.time() * 1000)}", timeout=30) as r:
        return json.load(r)

def list_jobs():
    out = []
    for b in blob("list", "jobs/"):
        try:
            out.append(fetch_json(b["url"]))
        except Exception:
            pass
    return out

def shazam_state():
    try:
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "8", "-X", "POST", "-H", "Content-Type: application/json",
                            "-H", "User-Agent: Mozilla/5.0", "-d", '{"timezone":"Europe/London","signature":{"uri":"data:audio/vnd.shazam.sig;base64,AA==","samplems":1000},"timestamp":1,"context":{},"geolocation":{}}',
                            "https://amp.shazam.com/discovery/v5/en/GB/iphone/-/tag/0/0?sync=true&webv3=true&sampling=true&connected=&shazamapiversion=v3&sharehub=true&video=v0"],
                           capture_output=True, text=True, timeout=12)
        return "rate-limited" if r.stdout == "429" else "ok" if r.stdout else "unknown"
    except Exception:
        return "unknown"

def heartbeat(state):
    put_json("worker/heartbeat.json", {"at": int(time.time() * 1000), "shazam": state, "host": socket.gethostname(), "audd": False, "acrcloud": False})

class Job:
    def __init__(self, rec):
        self.rec = rec; self.key = rec["key"]; self.log = list(rec.get("log", [])); self.last_push = 0

    def push(self, force=False, **fields):
        self.rec.update(fields)
        if force or time.time() - self.last_push > 6:
            self.rec["log"] = self.log[-60:]
            put_json(f"jobs/{self.key}.json", self.rec); self.last_push = time.time()

    def say(self, line):
        print(f"[{self.key}] {line}", flush=True); self.log.append(line); self.push()

    def run(self, stage, cmd, env=None, timeout=4 * 3600):
        self.say(f"stage: {stage}"); self.push(force=True, stage=stage)
        p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, **(env or {})})
        t0 = time.time()
        for line in p.stdout:
            line = line.rstrip()
            if not line or line.startswith("[download]") or "libmpg123" in line:
                continue
            self.log.append(line); self.push()
            if time.time() - t0 > timeout:
                p.kill(); self.say(f"{stage}: timed out"); break
        p.wait()
        ok = p.returncode == 0
        if not ok:
            self.say(f"{stage}: finished with code {p.returncode}, continuing with what we have")
        return ok

def summary(d, key):
    segs = d["segments"]; dur = d["source"]["duration"] or 1
    covered = sum(((s["end"] if s["end"] is not None else dur) - s["start"]) for s in segs if s["track"])
    return {"key": key, "title": d["source"]["title"], "channel": d["source"].get("channel"), "url": d["source"]["url"],
            "thumbnail": d["source"].get("thumbnail"), "duration": dur, "views": d["source"].get("views"),
            "tracks": len({s["track"]["id"] for s in segs if s["track"]}), "coverage": round(covered / dur, 3), "ran_at": d.get("analysed", {}).get("ran_at")}

def process(rec):
    job = Job(rec); key = job.key; url = rec["url"]; every = str(rec.get("every") or 40)
    audio = os.path.join(tempfile.gettempdir(), f"setid-{key}.mp3")
    shz = os.path.join(LOGS, "shazam", f"{key}.json"); com = os.path.join(LOGS, "comments", f"{key}.json"); cat = os.path.join(LOGS, f"{key}.catalog.json")
    for p in (shz, com, cat):
        if os.path.exists(p): os.remove(p)
    os.makedirs(os.path.dirname(shz), exist_ok=True); os.makedirs(os.path.dirname(com), exist_ok=True)
    job.run("Shazam", [PY, "trackid.py", url, "--every", every, "--out", os.path.dirname(shz), "--save-audio", audio], env={"SETID_SHAZAM_MAX_WAIT": "600"})
    if url.startswith("https://www.youtube.com/"):
        job.run("Comments", [PY, "comments_tracklist.py", url, "--out", os.path.dirname(com)], timeout=1800)
    named = com if os.path.exists(com) else shz if os.path.exists(shz) else None
    if named and os.path.exists(audio) and os.path.exists(NULL_AUDIO):
        job.run("Audio check", [PY, "catalog_match.py", url, "--tracks-from", named, "--wide", "--audio", audio, "--null", NULL_AUDIO], timeout=3600)
    if not (os.path.exists(shz) or os.path.exists(com)):
        job.say("failed: neither Shazam nor the comments produced anything")
        job.push(force=True, state="failed", stage=None, finished=time.time())
        return
    args = [PY, "merge_sources.py", key] + (["--shazam", shz] if os.path.exists(shz) else []) + (["--comments", com] if os.path.exists(com) else []) + (["--catalog", cat] if os.path.exists(cat) else [])
    job.run("Merge", args, timeout=1800)
    if os.path.exists(audio):
        job.run("Tempo", [PY, "tempo.py", key, "--audio", audio], timeout=1800)
    setp = os.path.join(ROOT, "sets", f"{key}.json")
    d = json.load(open(setp))
    put_json(f"sets/{key}.json", d)
    put_json(f"sets-index/{key}.json", summary(d, key))
    n = len([s for s in d["segments"] if s["track"]])
    job.say(f"done: {n} tracks published")
    job.push(force=True, state="done", stage=None, finished=time.time(), title=d["source"]["title"], ids=n)
    if os.path.exists(audio): os.remove(audio)

def main():
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        sys.exit("Run me through `vercel env run -e production -- ...` so the Blob credentials are injected.")
    print("SetID worker polling Vercel Blob", flush=True)
    sz, sz_at = "unknown", 0
    while True:
        try:
            if time.time() - sz_at > 120:
                sz, sz_at = shazam_state(), time.time()
            heartbeat(sz)
            queued = sorted((j for j in list_jobs() if j.get("state") == "queued"), key=lambda j: j.get("queued", 0))
            if queued:
                rec = queued[0]; rec["state"] = "running"; rec["started"] = time.time(); rec["log"] = ["claimed by worker"]
                put_json(f"jobs/{rec['key']}.json", rec)
                try:
                    process(rec)
                except Exception as e:
                    print(f"job {rec['key']} crashed: {e}", flush=True)
                    rec["state"] = "failed"; rec["finished"] = time.time(); rec.setdefault("log", []).append(f"worker error: {type(e).__name__}: {str(e)[:200]}")
                    put_json(f"jobs/{rec['key']}.json", rec)
                continue
        except Exception as e:
            print(f"poll error: {e}", flush=True)
        time.sleep(POLL)

if __name__ == "__main__":
    main()
