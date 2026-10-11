// Shared helpers for the SetID API (Vercel functions). Files starting with "_" are not deployed as routes.
import { put, list } from '@vercel/blob';

export function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Cache-Control', 'no-store');
}

export function preflight(req, res) {
  cors(res);
  if (req.method === 'OPTIONS') { res.status(204).end(); return true; }
  return false;
}

export async function readJSON(pathname) {
  const { blobs } = await list({ prefix: pathname, limit: 5 });
  const b = blobs.find(x => x.pathname === pathname);
  if (!b) return null;
  const r = await fetch(`${b.url}?ts=${Date.now()}`, { cache: 'no-store' });
  return r.ok ? r.json() : null;
}

export async function readAll(prefix, limit = 60) {
  const { blobs } = await list({ prefix, limit: 1000 });
  const recent = blobs.sort((a, b) => new Date(b.uploadedAt) - new Date(a.uploadedAt)).slice(0, limit);
  const rows = await Promise.all(recent.map(async b => {
    try { const r = await fetch(`${b.url}?ts=${Date.now()}`, { cache: 'no-store' }); return r.ok ? r.json() : null; } catch { return null; }
  }));
  return rows.filter(Boolean);
}

export async function writeJSON(pathname, data) {
  return put(pathname, JSON.stringify(data), {
    access: 'public', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json', cacheControlMaxAge: 60,
  });
}

export function keyFor(url) {
  const s = String(url || '').trim();
  let m = s.match(/(?:youtu\.be\/|[?&]v=|\/shorts\/|\/live\/)([\w-]{11})/) || s.match(/^([\w-]{11})$/);
  if (m) return { key: `youtube-${m[1]}`, url: `https://www.youtube.com/watch?v=${m[1]}`, platform: 'youtube' };
  m = s.match(/soundcloud\.com\/([\w-]+)\/([\w-]+)/);
  if (m) return { key: `soundcloud-${m[1]}-${m[2]}`, url: `https://soundcloud.com/${m[1]}/${m[2]}`, platform: 'soundcloud' };
  return null;
}

export async function body(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  try { return JSON.parse(req.body || '{}'); } catch { return {}; }
}

export const WORKER_STALE_MS = 90 * 1000;
