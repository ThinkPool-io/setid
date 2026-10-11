import { preflight, keyFor, readJSON, writeJSON, body } from './_lib.js';
export default async function handler(req, res) {
  if (preflight(req, res)) return;
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST a {url}' });
  const b = await body(req);
  const k = keyFor(b.url);
  if (!k) return res.status(400).json({ error: 'Paste a YouTube or SoundCloud set link' });
  const every = Math.max(20, Math.min(120, parseInt(b.every, 10) || 40));
  const [existing, done] = await Promise.all([readJSON(`jobs/${k.key}.json`), readJSON(`sets/${k.key}.json`)]);
  if (existing && (existing.state === 'queued' || existing.state === 'running')) return res.status(200).json({ key: k.key, state: existing.state, existing: true });
  if (done && !b.force) return res.status(200).json({ key: k.key, state: 'done', existing: true });
  let title = null, thumbnail = null;
  if (k.platform === 'youtube') {
    try {
      const o = await (await fetch(`https://www.youtube.com/oembed?url=${encodeURIComponent(k.url)}&format=json`)).json();
      title = o.title || null; thumbnail = o.thumbnail_url || null;
    } catch {}
  }
  const job = { key: k.key, url: k.url, every, state: 'queued', queued: Date.now() / 1000, log: [], title, thumbnail };
  await writeJSON(`jobs/${k.key}.json`, job);
  res.status(200).json({ key: k.key, state: 'queued' });
}
