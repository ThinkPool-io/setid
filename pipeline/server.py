#!/usr/bin/env python3
"""SetID queue server. Stdlib only.

POST /queue   {"url": "...", "every": 40, "audd_token": "optional"}  -> {"key", "state"}
GET  /status/<key>   -> {"state": queued|running|done|failed, "log": [...last lines], "position": n}
GET  /sets/<key>.json -> result JSON (also copied into ../sets and pushed to GitHub so Pages keeps it)
GET  /health -> {"ok": true, "queue": n, "providers": [...]}
"""
import json, os, re, subprocess, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SETS = os.path.join(HERE, "..", "sets")
LOGS = os.path.join(HERE, "logs"); os.makedirs(LOGS, exist_ok=True)
PY = os.path.join(HERE, ".venv", "bin", "python")
jobs, order, lock = {}, [], threading.Lock()

def key_for(url):
    m = re.search(r"(?:youtu\.be/|[?&]v=|/shorts/|/live/)([\w-]{11})", url) or re.match(r"^([\w-]{11})$", url.strip())
    if m:
        return "youtube-" + m.group(1), "https://www.youtube.com/watch?v=" + m.group(1)
    m = re.search(r"soundcloud\.com/([\w-]+)/([\w-]+)", url)
    if m:
        return "soundcloud-" + m.group(1) + "-" + m.group(2), url.split("?")[0]
    return None, None

def worker():
    while True:
        job = None
        with lock:
            for k in order:
                if jobs[k]["state"] == "queued":
                    job = jobs[k]; job["state"] = "running"; job["started"] = time.time(); break
        if not job:
            time.sleep(1); continue
        env = dict(os.environ)
        if job.get("audd_token"):
            env["AUDD_TOKEN"] = job["audd_token"]
        logp = os.path.join(LOGS, job["key"] + ".server.log")
        with open(logp, "w") as lf:
            p = subprocess.Popen([PY, os.path.join(HERE, "trackid.py"), job["url"], "--every", str(job["every"]), "--out", SETS],
                                 stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=HERE)
            while p.poll() is None:
                try:
                    job["log"] = [l.rstrip() for l in open(logp, errors="replace").read().splitlines() if not l.startswith("[download]")][-40:]
                except Exception:
                    pass
                time.sleep(1.5)
        job["log"] = [l.rstrip() for l in open(logp, errors="replace").read().splitlines() if not l.startswith("[download]")][-60:]
        ok = p.returncode == 0 and os.path.exists(os.path.join(SETS, job["key"] + ".json"))
        job["state"] = "done" if ok else "failed"; job["finished"] = time.time()
        if ok:
            subprocess.run([sys.executable, os.path.join(HERE, "build_index.py")], capture_output=True)
            try:  # persist to GitHub Pages
                subprocess.run(["git", "add", "sets"], cwd=os.path.join(HERE, ".."), check=True, capture_output=True)
                subprocess.run(["git", "-c", "user.name=Bradical247", "-c", "user.email=108717148+Bradical247@users.noreply.github.com",
                                "commit", "-q", "-m", f"Add set {job['key']}\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"], cwd=os.path.join(HERE, ".."), capture_output=True)
                subprocess.run(["git", "push", "-q"], cwd=os.path.join(HERE, ".."), capture_output=True, timeout=60)
            except Exception as e:
                job["log"].append(f"push failed: {e}")

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS"); self.send_header("Cache-Control", "no-store"); self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a): pass
    def do_OPTIONS(self): self._send(204, b"")
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            with lock: q = sum(1 for j in jobs.values() if j["state"] in ("queued", "running"))
            return self._send(200, {"ok": True, "queue": q, "shazam": shazam_state(), "audd": bool(os.environ.get("AUDD_TOKEN")), "acrcloud": bool(os.environ.get("ACR_KEY"))})
        m = re.match(r"^/status/([\w-]+)$", path)
        if m:
            j = jobs.get(m.group(1))
            if not j: return self._send(404, {"error": "unknown job"})
            with lock: pos = [k for k in order if jobs[k]["state"] in ("queued", "running")].index(j["key"]) if j["state"] in ("queued", "running") else 0
            return self._send(200, {"key": j["key"], "state": j["state"], "position": pos, "log": j.get("log", [])[-25:], "every": j["every"]})
        m = re.match(r"^/sets/([\w-]+)\.json$", path)
        if m:
            p = os.path.join(SETS, m.group(1) + ".json")
            if not os.path.exists(p): return self._send(404, {"error": "no such set"})
            return self._send(200, open(p, "rb").read())
        if path == "/sets/index.json":
            p = os.path.join(SETS, "index.json"); return self._send(200, open(p, "rb").read() if os.path.exists(p) else b"[]")
        self._send(404, {"error": "not found"})
    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/queue": return self._send(404, {"error": "not found"})
        try: body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        except Exception: return self._send(400, {"error": "bad json"})
        key, url = key_for(str(body.get("url", "")))
        if not key: return self._send(400, {"error": "Paste a YouTube or SoundCloud track/set link"})
        every = max(20, min(120, int(body.get("every") or 40)))
        with lock:
            if key in jobs and jobs[key]["state"] in ("queued", "running"):
                return self._send(200, {"key": key, "state": jobs[key]["state"], "existing": True})
            if os.path.exists(os.path.join(SETS, key + ".json")) and not body.get("force"):
                return self._send(200, {"key": key, "state": "done", "existing": True})
            jobs[key] = {"key": key, "url": url, "every": every, "state": "queued", "log": [], "queued": time.time(), "audd_token": (body.get("audd_token") or "").strip()}
            if key in order: order.remove(key)
            order.append(key)
        self._send(200, {"key": key, "state": "queued"})

def shazam_state():
    try:
        out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "8", "-X", "POST", "-H", "Content-Type: application/json", "-H", "User-Agent: Mozilla/5.0",
                              "-d", '{"timezone":"Europe/London","signature":{"uri":"data:audio/vnd.shazam.sig;base64,AA==","samplems":1000},"timestamp":1,"context":{},"geolocation":{}}',
                              "https://amp.shazam.com/discovery/v5/en/GB/iphone/-/tag/0/0?sync=true&webv3=true&sampling=true&connected=&shazamapiversion=v3&sharehub=true&video=v0"], capture_output=True, text=True, timeout=12).stdout
        return "rate-limited" if out == "429" else "ok" if out else "unknown"
    except Exception:
        return "unknown"

if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"SetID queue server on :{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
