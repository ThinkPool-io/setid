import { preflight, readAll } from './_lib.js';
const SAMPLE = /^\s+\d+:\d+\s+\S/;
export default async function handler(req, res) {
  if (preflight(req, res)) return;
  const jobs = await readAll('jobs/', 60);
  const active = jobs.filter(j => j.state === 'queued' || j.state === 'running').sort((a, b) => a.queued - b.queued).map(j => j.key);
  const rows = jobs.sort((a, b) => (b.queued || 0) - (a.queued || 0)).slice(0, 30).map(j => {
    const log = j.log || [];
    const ids = log.filter(l => SAMPLE.test(l) && !/·\s*$/.test(l)).length;
    const last = [...log].reverse().find(l => SAMPLE.test(l) || /waiting for Shazam|stage:/i.test(l)) || '';
    return { key: j.key, url: j.url, state: j.state, ids: j.ids ?? ids, last: (j.stage ? `${j.stage} · ` : '') + last.trim().slice(0, 80),
      position: active.includes(j.key) ? active.indexOf(j.key) : null, started: j.started || null, finished: j.finished || null, queued: j.queued || null, title: j.title || null };
  });
  res.status(200).json({ now: Date.now() / 1000, jobs: rows });
}
