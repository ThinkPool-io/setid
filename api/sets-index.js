import { preflight, readAll } from './_lib.js';
export default async function handler(req, res) {
  if (preflight(req, res)) return;
  const rows = await readAll('sets-index/', 200);
  rows.sort((a, b) => (b.views || 0) - (a.views || 0));
  res.status(200).json(rows);
}
