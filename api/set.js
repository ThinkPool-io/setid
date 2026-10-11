import { preflight, readJSON } from './_lib.js';
export default async function handler(req, res) {
  if (preflight(req, res)) return;
  const key = String(req.query.key || '').replace(/[^\w-]/g, '');
  const d = await readJSON(`sets/${key}.json`);
  if (!d) return res.status(404).json({ error: 'no such set' });
  res.status(200).json(d);
}
