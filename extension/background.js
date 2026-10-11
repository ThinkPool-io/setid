/* Service worker: the only place that talks to the SetID data origin.
   Content script and popup ask it via messages; it caches in memory. */
importScripts('config.js');
const C = self.SETID_CONFIG;
const cache = new Map(); // url -> {at, value}

async function getJSON(url) {
  const hit = cache.get(url);
  if (hit && Date.now() - hit.at < C.CACHE_MS) return hit.value;
  const r = await fetch(url, { credentials: 'omit' });
  if (r.status === 404) { cache.set(url, { at: Date.now(), value: null }); return null; }
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const value = await r.json();
  cache.set(url, { at: Date.now(), value });
  return value;
}

async function lookup(videoId) {
  const key = 'youtube-' + videoId;
  let index = null;
  try { index = await getJSON(C.INDEX_URL); } catch (e) { /* fall through to direct fetch */ }
  if (Array.isArray(index) && !index.some((x) => x && x.key === key)) return { key, set: null };
  const set = await getJSON(C.setUrl(key)); // null on 404
  return { key, set };
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    try {
      if (msg && msg.type === 'lookup' && /^[\w-]{6,20}$/.test(msg.videoId || '')) reply({ ok: true, ...(await lookup(msg.videoId)) });
      else if (msg && msg.type === 'index') reply({ ok: true, index: (await getJSON(C.INDEX_URL)) || [] });
      else reply({ ok: false, error: 'bad request' });
    } catch (e) { reply({ ok: false, error: String(e && e.message || e) }); }
  })();
  return true; // async reply
});
