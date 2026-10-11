import { preflight, readJSON, readAll, WORKER_STALE_MS } from './_lib.js';
export default async function handler(req, res) {
  if (preflight(req, res)) return;
  const [hb, jobs] = await Promise.all([readJSON('worker/heartbeat.json'), readAll('jobs/', 200)]);
  const age = hb ? Date.now() - hb.at : null;
  const queue = jobs.filter(j => j.state === 'queued' || j.state === 'running').length;
  res.status(200).json({
    ok: true, workerOnline: age !== null && age < WORKER_STALE_MS, workerSeenSecondsAgo: age === null ? null : Math.round(age / 1000),
    queue, shazam: hb?.shazam || 'unknown', audd: Boolean(hb?.audd), acrcloud: Boolean(hb?.acrcloud),
  });
}
