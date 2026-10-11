import { preflight, readJSON, readAll } from './_lib.js';
export default async function handler(req, res) {
  if (preflight(req, res)) return;
  const key = String(req.query.key || '').replace(/[^\w-]/g, '');
  const j = await readJSON(`jobs/${key}.json`);
  if (!j) return res.status(404).json({ error: 'unknown job' });
  let position = 0;
  if (j.state === 'queued') {
    const all = await readAll('jobs/', 200);
    position = all.filter(x => x.state === 'queued' || x.state === 'running').sort((a, b) => a.queued - b.queued).findIndex(x => x.key === key);
  }
  res.status(200).json({ key, state: j.state, position, log: (j.log || []).slice(-25), every: j.every, stage: j.stage || null });
}
