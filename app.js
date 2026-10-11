/* SetID prototype UI. Static site: set data lives in sets/*.json, produced by pipeline/trackid.py. */
(function () {
  'use strict';
  const CONFIG = {
    // Register an app at developer.spotify.com, add this page's URL as a redirect URI, paste the client id here
    // and the Spotify button creates a real playlist in the user's account (PKCE, no server needed).
    spotifyClientId: '',
  };
  const $ = s => document.querySelector(s);
  const h = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const ts = s => { s = Math.max(0, Math.floor(s)); const hh = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), ss = s % 60; return (hh ? hh + ':' + String(m).padStart(2, '0') : m) + ':' + String(ss).padStart(2, '0'); };
  const parseTs = str => { const p = String(str).trim().split(':').map(Number); if (p.some(isNaN) || !p.length) return null; return p.reduce((a, v) => a * 60 + v, 0); };
  const PLAY = '<svg viewBox="0 0 14 14"><path d="M3 1.5v11l9-5.5z"/></svg>', STOP = '<svg viewBox="0 0 14 14"><rect x="2.5" y="2.5" width="9" height="9" rx="1"/></svg>';
  const icon = n => `<svg class="ic" aria-hidden="true"><use href="#i-${n}"/></svg>`;

  const state = { index: [], set: null, key: null, tracks: {}, setlist: JSON.parse(localStorage.getItem('setid.setlist') || '[]'), curSeg: -1, api: '', apiOk: false, apiInfo: null };

  // ---------- utils ----------
  let toastT; function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), 2600); }
  function download(name, data, type) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([data], { type })); a.download = name; document.body.appendChild(a); a.click(); a.remove(); toast('Downloaded ' + name); }
  async function copy(text, msg) { try { await navigator.clipboard.writeText(text); toast(msg || 'Copied'); } catch { prompt('Copy this:', text); } }
  const q = s => encodeURIComponent(s);
  const links = t => ({
    yt: t.youtube ? `https://www.youtube.com/watch?v=${t.youtube}` : `https://www.youtube.com/results?search_query=${q(t.artist + ' ' + t.title)}`,
    ytm: t.youtube ? `https://music.youtube.com/watch?v=${t.youtube}` : `https://music.youtube.com/search?q=${q(t.artist + ' ' + t.title)}`,
    sp: `https://open.spotify.com/search/${q(t.artist + ' ' + t.title)}`,
    ap: t.apple || `https://music.apple.com/search?term=${q(t.artist + ' ' + t.title)}`,
    dz: t.deezer, sz: t.shazam,
  });
  function openLinks(t) {
    const l = links(t);
    return `<a class="btn sm yt" target="_blank" rel="noopener" href="${l.yt}">YouTube</a><a class="btn sm sp" target="_blank" rel="noopener" href="${l.sp}">Spotify</a><a class="btn sm ap" target="_blank" rel="noopener" href="${l.ap}">Apple Music</a>${l.dz ? `<a class="btn sm" target="_blank" rel="noopener" href="${l.dz}">Deezer</a>` : ''}${l.sz ? `<a class="btn sm" target="_blank" rel="noopener" href="${l.sz}">Shazam</a>` : ''}`;
  }

  // ---------- preview audio ----------
  const audio = new Audio(); let pvId = null;
  audio.addEventListener('ended', () => { pvId = null; syncPv(); });
  function preview(id) {
    const t = state.tracks[id]; if (!t || !t.preview) return;
    if (pvId === id) { audio.pause(); pvId = null; } else { if (player && player.pauseVideo) try { player.pauseVideo(); } catch { } audio.src = t.preview; audio.volume = .8; audio.play().catch(() => toast('Preview blocked by the browser')); pvId = id; }
    syncPv();
  }
  function syncPv() { document.querySelectorAll('[data-pv]').forEach(b => { const on = b.dataset.pv === pvId; b.classList.toggle('on', on); b.innerHTML = on ? STOP : PLAY; }); }
  const pvBtn = t => `<button class="pv" data-pv="${t.id}" ${t.preview ? '' : 'disabled title="No preview available"'} aria-label="30 second preview">${PLAY}</button>`;

  // ---------- data ----------
  async function loadIndex() {
    try { state.index = await (await fetch('sets/index.json', { cache: 'no-store' })).json(); } catch { state.index = []; }
    try { const c = await (await fetch('api.json', { cache: 'no-store' })).json(); state.api = (c.api || '').replace(/\/$/, ''); } catch { }
    if (state.api) { try { const ctl = new AbortController(); setTimeout(() => ctl.abort(), 8000); const hinfo = await (await fetch(state.api + '/health', { signal: ctl.signal })).json(); state.apiOk = !!hinfo.ok; state.apiInfo = hinfo; const remote = await (await fetch(state.api + '/sets/index.json', { cache: 'no-store' })).json(); const fresh = new Map(remote.map(x => [x.key, x])); state.index = state.index.filter(x => !fresh.has(x.key)).concat(remote); } catch { state.apiOk = false; } }
  }
  async function loadSet(key) {
    let r = state.api ? await fetch(`${state.api}/sets/${key}.json`, { cache: 'no-store' }).catch(() => null) : null;  // the API holds the newest copy
    if (!r || !r.ok) r = await fetch(`sets/${key}.json`, { cache: 'no-store' });
    const d = await r.json();
    d.segments.forEach(s => { if (s.track) state.tracks[s.track.id] = s.track; });
    Object.values(d.similar || {}).flat().forEach(t => { state.tracks[t.id] = t; });
    return d;
  }
  function findKey(input) {
    const s = input.trim(); if (!s) return null;
    const m = s.match(/(?:youtu\.be\/|[?&]v=|\/shorts\/|\/live\/)([\w-]{11})/) || s.match(/^([\w-]{11})$/);
    if (m) { const k = 'youtube-' + m[1]; return state.index.some(x => x.key === k) ? k : { missing: k, url: s }; }
    const sc = s.match(/soundcloud\.com\/([\w-]+\/[\w-]+)/);
    if (sc) { const hit = state.index.find(x => x.url && x.url.includes(sc[1])); return hit ? hit.key : { missing: 'soundcloud', url: s }; }
    const low = s.toLowerCase(); const hit = state.index.find(x => (x.title + ' ' + x.channel).toLowerCase().includes(low));
    return hit ? hit.key : { missing: null, url: s };
  }

  // ---------- home ----------
  let rhythmKey = null;
  async function renderRhythm() {
    const x = state.index.find(v => v.tracks) || state.index[0]; if (!x || rhythmKey === x.key) return;
    let d; try { d = await loadSet(x.key); } catch { return; }
    const dur = d.source.duration, segs = d.segments.filter(s => s.track && s.start != null);
    if (!segs.length || !dur) return;
    rhythmKey = x.key;
    const len = s => (s.end ?? dur) - s.start;
    const longest = segs.reduce((a, s) => len(s) > len(a) ? s : a, segs[0]);
    $('#rhythm').innerHTML = segs.map((s, n) => `<i class="${s === longest ? 'hi' : ''}" style="--n:${n};margin-left:${s.start / dur * 100}%;width:${len(s) / dur * 100}%" title="${ts(s.start)} ${h(s.track.artist + ' - ' + s.track.title)}"></i>`).join('');
    const step = dur > 5400 ? 1200 : 600;
    $('#rhythmX').innerHTML = Array.from({ length: Math.floor(dur / step) + 1 }, (_, k) => `<span style="left:${k * step / dur * 100}%">${ts(k * step)}</span>`).join('');
    $('#rhythmCap').innerHTML = `<a href="#/set/${x.key}">${h(d.source.title)}</a><span>${segs.length} identified segments across ${ts(dur)}. Each line is one track, placed at the moment it played. In vermilion, the longest: ${h(longest.track.title)}.</span>`;
    $('#proof').classList.remove('hidden');
  }
  function renderHome() {
    $('#home').classList.remove('hidden'); $('#set').classList.add('hidden');
    stopPlayer();
    const w = $('#worker'); const info = state.apiInfo || {};
    const online = info.workerOnline !== undefined ? info.workerOnline : state.apiOk;
    w.innerHTML = state.apiOk ? `<span class="chip ${online ? 'acc' : ''}">${online ? 'worker online' : 'worker asleep: new sets wait in the queue'}</span> <span class="chip">Shazam: ${h(info.shazam || '?')}</span> <span class="chip">AudD: ${info.audd ? 'key set' : 'no key'}</span> <span class="chip">ACRCloud: ${info.acrcloud ? 'key set' : 'no key'}</span> <span class="chip">${info.queue || 0} in queue</span>` : '<span class="chip" style="color:var(--warn)">worker offline: only library sets open</span>';
    $('#every').value = localStorage.getItem('setid.every') || 40; $('#audd').value = localStorage.getItem('setid.audd') || '';
    startTracker(); renderRhythm();
    $('#library').innerHTML = state.index.length ? state.index.map(x => `<a class="card" href="#/set/${x.key}"><img src="${x.thumbnail}" alt="" loading="lazy"><div class="b"><div class="t">${h(x.title)}</div><div class="m"><span class="chip acc">${x.tracks} IDs</span><span class="chip">${ts(x.duration)}</span><span class="chip">${Math.round(x.coverage * 100)}% covered</span></div></div></a>`).join('') : '<div class="empty">No sets processed yet.</div>';
  }
  let trackerT = null;
  async function renderTracker() {
    const el = $('#tracker'); if (!el) return;
    if (!state.apiOk) { el.innerHTML = '<div class="empty">Worker offline. Nothing is being processed.</div>'; return; }
    let j; try { j = await (await fetch(state.api + '/jobs', { cache: 'no-store' })).json(); } catch { el.innerHTML = '<div class="empty">Worker unreachable.</div>'; return; }
    const rel = t => { if (!t) return ''; const s = Math.max(0, Math.round(j.now - t)); return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min`; };
    const vid = u => (u.match(/v=([\w-]{11})/) || [])[1];
    const label = x => x.title || (state.index.find(s => s.key === x.key) || {}).title || x.url.replace(/^https?:\/\/(www\.)?/, '');
    if (!j.jobs.length) { el.innerHTML = '<div class="empty">Queue is empty. Paste a set above to start one.</div>'; return; }
    el.innerHTML = j.jobs.map(x => {
      const st = x.state === 'running' ? `listening · ${x.ids} IDs` : x.state === 'queued' ? `queued · #${x.position + 1}` : x.state;
      const right = x.state === 'running' ? `${rel(x.started)} running` : x.state === 'queued' ? `waiting ${rel(x.queued)}` : x.state === 'done' ? `done ${rel(x.finished)} ago` : `failed ${rel(x.finished)} ago`;
      const sub = x.state === 'running' && x.last ? x.last : x.state === 'done' ? 'in the library' : x.state === 'failed' ? 'see log on retry' : '';
      const inner = `<div class="st"><i></i>${h(st)}</div><div style="min-width:0"><div class="t">${h(label(x))}</div><div class="sub">${h(sub)}</div></div><div class="r">${h(right)}</div>`;
      return x.state === 'done' ? `<a class="job ${x.state}" href="#/set/${x.key}" style="text-decoration:none">${inner}</a>` : `<div class="job ${x.state}">${inner}</div>`;
    }).join('');
  }
  function startTracker() { clearInterval(trackerT); renderTracker(); trackerT = setInterval(() => { if ($('#home').classList.contains('hidden')) return; renderTracker(); }, 4000); }
  function onPaste(v) {
    const r = findKey(v);
    if (typeof r === 'string') { location.hash = '#/set/' + r; return; }
    const hint = $('#pasteHint'); hint.classList.add('warn');
    if (!r) { hint.textContent = 'Paste a YouTube or SoundCloud link.'; return; }
    if (!r.missing) { hint.textContent = `No set in the library matches "${v.trim()}". Paste a YouTube or SoundCloud link to a set.`; return; }
    if (!state.apiOk) { hint.textContent = 'That set isn\'t processed yet and the processing worker is offline right now. Try one from the library below.'; return; }
    queueSet(v.trim());
  }
  async function queueSet(url) {
    const hint = $('#pasteHint'); hint.classList.remove('warn');
    const every = +(localStorage.getItem('setid.every') || 40);
    const audd = localStorage.getItem('setid.audd') || '';
    hint.textContent = 'Queuing…';
    let j; try { j = await (await fetch(state.api + '/queue', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, every, audd_token: audd }) })).json(); } catch { hint.classList.add('warn'); hint.textContent = 'Could not reach the worker.'; return; }
    if (j.error) { hint.classList.add('warn'); hint.textContent = j.error; return; }
    if (j.state === 'done') { location.hash = '#/set/' + j.key; return; }
    $('#progress').classList.remove('hidden'); $('#progress').scrollIntoView({ behavior: 'smooth', block: 'center' });
    hint.textContent = '';
    const t0 = Date.now();
    const poll = async () => {
      let st; try { st = await (await fetch(`${state.api}/status/${j.key}`)).json(); } catch { setTimeout(poll, 3000); return; }
      const mins = Math.round((Date.now() - t0) / 60000);
      const ids = st.log.filter(l => /^\s+\d+:\d+\s+\S/.test(l) && !/·\s*$/.test(l)).length;
      $('#progHead').innerHTML = st.state === 'queued' ? `<b>Queued</b> · position ${st.position + 1} · ${h(url)}` : st.state === 'running' ? `<b>Listening…</b> · ${ids} IDs so far · ${mins} min · sampling every ${st.every}s` : st.state === 'done' ? `<b>Done.</b> Opening the tracklist…` : `<b>Failed.</b> The log below says why.`;
      $('#progLog').textContent = st.log.join('\n') || 'Waiting for the worker…';
      $('#progLog').scrollTop = 1e9;
      renderTracker();
      if (st.state === 'done') { await loadIndex(); setTimeout(() => { location.hash = '#/set/' + st.key; }, 800); return; }
      if (st.state === 'failed') return;
      setTimeout(poll, 2500);
    };
    poll();
  }
  $('#pasteForm').addEventListener('submit', e => { e.preventDefault(); onPaste($('#pasteQ').value); });
  $('#every').addEventListener('change', e => localStorage.setItem('setid.every', Math.max(20, Math.min(120, +e.target.value || 40))));
  $('#audd').addEventListener('change', e => localStorage.setItem('setid.audd', e.target.value.trim()));
  $('#progClose').onclick = () => $('#progress').classList.add('hidden');
  $('#navForm').addEventListener('submit', e => { e.preventDefault(); const v = $('#navQ').value; location.hash = '#/'; $('#pasteQ').value = v; onPaste(v); });

  // ---------- YouTube player ----------
  let player = null, ytReady = false, pollT = null, pendingSeek = null;
  window.onYouTubeIframeAPIReady = () => { ytReady = true; if (state.set) mountPlayer(); };
  (function loadYT() { const s = document.createElement('script'); s.src = 'https://www.youtube.com/iframe_api'; document.head.appendChild(s); })();
  function mountPlayer() {
    const vid = state.set.source.id;
    if (player && player.loadVideoById) { player.loadVideoById(vid); return; }
    const el = document.createElement('div'); el.id = 'ytp'; $('#yt').replaceWith(el);
    player = new YT.Player('ytp', { videoId: vid, playerVars: { rel: 0, modestbranding: 1, playsinline: 1 }, events: { onReady: () => { if (pendingSeek != null) { player.seekTo(pendingSeek, true); pendingSeek = null; } }, onError: embedFallback } });
    clearInterval(pollT); pollT = setInterval(tick, 500);
  }
  let noEmbed = false;
  function embedFallback() {
    noEmbed = true; clearInterval(pollT);
    const src = state.set.source;
    $('.player .frame').innerHTML = `<a href="${src.url}" target="_blank" rel="noopener" style="display:block;position:relative;height:100%"><img src="${src.thumbnail}" alt="" style="width:100%;height:100%;object-fit:cover;opacity:.55"><div style="position:absolute;inset:0;display:grid;place-items:center;text-align:center;padding:20px"><div><div style="font-weight:800;font-size:18px">This channel disables embedding</div><div style="color:var(--mute);font-size:13.5px;margin:6px 0 12px">Tracklist clicks open YouTube at the exact moment instead.</div><span class="btn acc">Open on YouTube</span></div></div></a>`;
    renderNow(-1, 0);
  }
  function stopPlayer() { if (player && player.pauseVideo) try { player.pauseVideo(); } catch { } }
  function seek(t) { if (noEmbed) { window.open(`${state.set.source.url}&t=${Math.floor(t)}s`, '_blank'); askAt(t); return; } if (player && player.seekTo) { player.seekTo(t, true); player.playVideo && player.playVideo(); } else pendingSeek = t; audio.pause(); pvId = null; syncPv(); }
  function segAt(t) { const segs = state.set.segments; for (let i = segs.length - 1; i >= 0; i--) if (t >= segs[i].start) return i; return -1; }
  function tick() {
    if (!player || !player.getCurrentTime || !state.set) return;
    let t = 0; try { t = player.getCurrentTime() || 0; } catch { return; }
    const i = segAt(t);
    const ph = $('#timeline .ph'); if (ph) ph.style.left = (t / state.set.source.duration * 100) + '%';
    if (i !== state.curSeg) { state.curSeg = i; renderNow(i, t); document.querySelectorAll('#tl .row, #timeline [data-i]').forEach(r => r.classList.toggle('cur', +r.dataset.i === i)); }
    const pos = $('#now .pos'); if (pos) pos.textContent = ts(t);
  }
  const tempoText = t => t && t.playedBpm ? `played ${Math.round(t.playedBpm)} BPM${t.originalBpm ? ` · released ${Math.round(t.originalBpm)} · ${t.tempoDelta > 0 ? '+' : ''}${t.tempoDelta}%` : ''}` : '';
  function renderTempo() {
    const el = $('#tempo'); if (!el) return;
    const c = (state.set && state.set.tempoCurve) || [], dur = state.set ? state.set.source.duration : 1;
    if (c.length < 3) { el.innerHTML = ''; return; }
    const v = c.map(p => p[1]), lo = Math.min(...v), hi = Math.max(...v), span = Math.max(2, hi - lo), pad = span * 0.25;
    const y = b => 26 - ((b - (lo - pad)) / (span + 2 * pad)) * 22;
    const pts = c.map(p => `${(p[0] / dur * 1000).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
    const first = Math.round(c[0][1]), last = Math.round(c[c.length - 1][1]);
    el.innerHTML = `<svg viewBox="0 0 1000 28" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg><div class="tl">Tempo ${first === last ? `${first} BPM throughout` : `${first} → ${last} BPM`}${hi - lo >= 1 ? ` · range ${Math.round(lo)}–${Math.round(hi)}` : ''}</div>`;
  }
  function renderNow(i, t) {
    const s = state.set.segments[i]; const tr = s && s.track;
    $('#now').innerHTML = tr ? `<img src="${tr.cover || 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22/%3E'}" onerror="this.style.visibility='hidden'" alt=""><div><div class="t">${h(tr.title)}</div><div class="a">${h(tr.artist)}${tr.label ? ' · ' + h(tr.label) : ''}${tr.playedBpm ? ' · ' + h(tempoText(tr)) : ''}</div></div><span class="pos">${ts(t || 0)}</span>`
      : `<div><div class="t" style="color:var(--mute)">${s ? 'Unidentified passage' : 'Press play'}</div><div class="a">${s ? 'Nothing has identified this part yet (a blend, an edit, or unreleased)' : 'The tracklist follows the video as it plays'}</div></div><span class="pos">${ts(t || 0)}</span>`;
  }

  // ---------- set page ----------
  async function renderSet(key, tParam) {
    $('#home').classList.add('hidden'); $('#set').classList.remove('hidden');
    if (state.key !== key) { state.set = await loadSet(key); state.key = key; state.curSeg = -1; noEmbed = false; if (player) { try { player.destroy(); } catch { } player = null; $('.player .frame').innerHTML = '<div id="yt"></div>'; } }
    const d = state.set, src = d.source, segs = d.segments;
    document.title = `${src.title} · tracklist · SetID`;
    $('#setTitle').textContent = src.title;
    const n = new Set(segs.filter(s => s.track).map(s => s.track.id)).size;
    $('#setMeta').innerHTML = `<span>${h(src.channel || '')}</span><span class="chip acc">${n} tracks identified</span><span class="chip">${ts(src.duration)}</span>${d.analysed.method === 'multi' ? `<span class="chip">${[d.analysed.shazamRows ? d.analysed.shazamRows + ' via Shazam' : '', d.analysed.audioRows ? d.analysed.audioRows + ' catalogue matches' : '', d.analysed.commentRows ? d.analysed.commentRows + ' from comments' : ''].filter(Boolean).join(' · ')}</span>` : d.analysed.method === 'comments+audio' ? `<span class="chip">${d.analysed.audioMatches} audio matches · ${d.analysed.commentOnly} from comments</span>` : d.analysed.method === 'comments' ? `<span class="chip">from ${d.analysed.comments} YouTube comments</span>` : `<span class="chip">${Math.round(d.analysed.identified / d.analysed.samples * 100)}% of samples matched</span>`}<a class="btn sm" target="_blank" rel="noopener" href="${src.url}">Open on ${src.platform}</a><button class="btn sm" id="shareSet">Share</button>`;
    $('#shareSet').onclick = () => copy(location.href.split('?')[0], 'Link copied');
    // timeline
    $('#timeline').innerHTML = segs.map((s, i) => { const w = ((s.end ?? src.duration) - s.start) / src.duration * 100; return `<div class="${s.track ? 'tr' : 'gap'}" data-i="${i}" style="width:${w}%" title="${ts(s.start)} ${s.track ? h(s.track.artist + ' - ' + s.track.title) : 'unidentified'}"></div>`; }).join('') + '<div class="ph" style="left:0"></div>';
    renderTempo();
    $('#timeline').onclick = e => { const r = e.currentTarget.getBoundingClientRect(); const t = (e.clientX - r.left) / r.width * src.duration; seek(t); askAt(t); };
    // tracklist
    $('#tl').innerHTML = segs.map((s, i) => {
      const t = s.track, inSl = t && state.setlist.some(x => x.id === t.id);
      if (!t) return `<div class="row unk" data-i="${i}"><div class="ts">${ts(s.start)}</div><div style="grid-column:2/-1"><div class="ti">Unidentified</div><div class="ar">${ts(s.start)} to ${ts(s.end ?? src.duration)} · ${d.analysed.method === 'comments' ? 'nobody has named this part yet' : 'no confident match'}</div></div></div>`;
      const sims = (d.similar || {})[t.id] || [];
      return `<div class="row" data-i="${i}" data-seek="${s.start}">
        <div class="ts">${ts(s.start)}</div><img src="${t.cover || 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22/%3E'}" onerror="this.style.visibility='hidden'" alt="" loading="lazy">
        <div style="min-width:0"><div class="ti">${h(t.title)}</div><div class="ar">${h(t.artist)}${t.label ? ' · ' + h(t.label) : ''}${t.released ? ' · ' + h(t.released) : ''}</div>
          <div class="meta">${t.source === 'shazam' ? `<span class="chip" ${t.samples === 1 && !t.catalog && !t.commentVotes ? 'style="color:var(--warn);border-color:#4a3d18"' : ''} title="Identified by Shazam on ${t.samples} sampled clip${t.samples === 1 ? '' : 's'}">Shazam · ${t.samples} clip${t.samples === 1 ? '' : 's'}${t.catalog ? ' · catalogue agrees' : ''}${t.commentVotes ? ` · also named by ${t.commentVotes} in comments` : ''}${t.samples === 1 && !t.catalog && !t.commentVotes ? ' · low confidence' : ''}</span>` : t.source === 'audio' || t.source === 'both' ? `<span class="chip" title="Fingerprint match against ${h(t.artist)}'s released catalogue">audio match${t.source === 'both' || t.commentVotes ? ` · also named by ${t.commentVotes || t.votes} in comments` : ''}${t.pitch ? ` · pitched ${t.pitch > 0 ? '+' : ''}${t.pitch}%` : ''}</span>` : t.source === 'comments' ? `<span class="chip" style="color:var(--warn);border-color:#4a3d18" title="${h((t.evidence || []).join(' · '))}">from comments · ${t.votes} ${t.votes === 1 ? 'person' : 'people'}${t.approx ? ' · time approx' : ''} · not audio-confirmed</span>` : s.hits === 1 ? '<span class="chip" style="color:var(--warn);border-color:#4a3d18" title="Matched on a single 12-second sample">low confidence</span>' : ''}${t.playedBpm ? `<span class="chip tempo" title="Tempo measured from the set audio${t.originalBpm ? '; released tempo measured from the Deezer preview' : ''}">${h(tempoText(t))}</span>` : t.bpm ? `<span class="chip">${Math.round(t.bpm)} BPM</span>` : ''}${t.genre ? `<span class="chip">${h(t.genre)}</span>` : ''}<span class="chip">${sims.length} similar</span></div></div>
        <div class="acts">${pvBtn(t)}<button class="btn sm" data-add="${t.id}" ${inSl ? 'disabled' : ''}>${inSl ? 'Added' : '+ Setlist'}</button><button class="btn sm ic" data-more="${i}" aria-label="Similar tracks and links">${icon('down')}</button></div>
        <div class="exp"><div class="open">${openLinks(t)}<button class="btn sm" data-idcopy="${i}">${icon('copy')}Copy "track ID" answer</button></div>
          <h4>Similar tracks</h4>
          <div class="sims">${sims.length ? sims.map(x => `<div class="sim"><img src="${x.cover || 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22/%3E'}" onerror="this.style.visibility='hidden'" alt="" loading="lazy"><div style="min-width:0"><div class="ti">${h(x.title)}</div><div class="ar">${h(x.artist)}${x.bpm ? ' · ' + Math.round(x.bpm) + ' BPM' : ''}</div><div class="why">${h(x.why || '')}</div></div><div class="acts">${pvBtn(x)}<a class="btn sm ic yt" target="_blank" rel="noopener" href="${links(x).yt}" title="Open on YouTube" aria-label="Open on YouTube">${icon('yt')}</a><button class="btn sm" data-add="${x.id}" ${state.setlist.some(z => z.id === x.id) ? 'disabled' : ''} aria-label="Add to setlist">${icon('plus')}</button></div></div>`).join('') : '<div class="empty">No similarity data for this one yet.</div>'}</div></div>
      </div>`;
    }).join('');
    $('#setFine').textContent = d.analysed.method === 'multi' ? [d.analysed.shazamSamples ? `Shazam: ${d.analysed.shazamSamples} clips of 12 s, one every ${d.analysed.shazamEvery} s.` : '', d.analysed.catalogue ? `Catalogue: fingerprinted against ${d.analysed.catalogue} released tracks by ${(d.analysed.catalogueArtists || []).join(', ')} (30 s Deezer previews at pitch-fader speeds -6% to +6%), filling stretches Shazam missed; only matches above the false-match level measured on an unrelated set count.` : '', d.analysed.comments ? `Comments: ${d.analysed.comments} YouTube comments and replies mined for "track ID?" answers; ${d.analysed.commentConfirmed || 0} agree with the audio, the rest are labelled not audio-confirmed.` : '', 'Gaps are parts nothing has matched yet.'].filter(Boolean).join(' ') : d.analysed.method === 'comments+audio' ? `Two kinds of evidence. Audio matches: the set was fingerprinted against ${d.analysed.catalogue} released tracks by ${(d.analysed.catalogueArtists || []).join(', ')} (30-second Deezer previews, at pitch-fader speeds from -6% to +6%), keeping only matches that beat the strongest false match measured on an unrelated set. Comment IDs: someone asked "track ID?" and someone else named it; those are labelled "not audio-confirmed". Gaps are parts nobody has matched yet.` : d.analysed.method === 'comments' ? `Tracklist built from ${d.analysed.comments} YouTube comments and replies: each ID is where someone asked "track ID?" and someone else named it. Times mark when it was asked about, so treat them as roughly when the track plays. Not audio-verified yet.` : `Sampled every ${d.analysed.every}s with ${d.analysed.clip}s clips · ${d.analysed.identified}/${d.analysed.samples} samples matched · run ${d.analysed.ran_at.slice(0, 10)} · unidentified stretches are usually blends, edits or unreleased material.`;
    renderNow(-1, 0);
    if (ytReady) mountPlayer();
    if (tParam != null) { seek(tParam); askAt(tParam); }
    syncPv(); renderSetlist();
  }
  $('#tl').addEventListener('click', e => {
    const more = e.target.closest('[data-more]'); if (more) { more.closest('.row').classList.toggle('open'); return; }
    const idc = e.target.closest('[data-idcopy]'); if (idc) { const s = state.set.segments[+idc.dataset.idcopy]; copy(`${ts(s.start)} ${s.track.artist} - ${s.track.title}`, 'Answer copied, paste it in the comments'); return; }
    if (e.target.closest('button,a,.exp')) return;
    const row = e.target.closest('.row[data-seek]'); if (row) seek(+row.dataset.seek);
  });
  function askAt(t) {
    const i = segAt(t), s = state.set.segments[i];
    $('#askT').value = ts(t);
    $('#askAns').innerHTML = s && s.track ? `<b class="at">${h(s.track.title)}</b><span class="aa">${h(s.track.artist)}</span><span>${s.track.source === 'shazam' ? `identified by Shazam from ${ts(s.start)}${s.track.samples === 1 && !s.track.catalog && !s.track.commentVotes ? ' · single clip, treat as a guess' : ''}` : s.track.source === 'audio' ? `heard in the audio from ${ts(s.start)}` : s.track.source === 'both' ? `heard in the audio from ${ts(s.start)}, and named in the comments` : s.track.source === 'comments' ? `named in the comments around ${ts(s.start)} by ${s.track.votes} ${s.track.votes === 1 ? 'person' : 'people'} (not audio-confirmed)` : `playing from ${ts(s.start)}${s.hits === 1 ? ' · single-sample match, treat as a guess' : ''}`}</span>${s.track.playedBpm ? `<span class="tp">${h(tempoText(s.track))}</span>` : ''}<div class="ab"><button class="btn sm" id="askCopy">${icon('copy')}Copy answer</button><a class="btn sm" href="?t=${Math.floor(t)}#/set/${state.key}" id="askLink">${icon('link')}Link to this moment</a></div>`
      : `<b class="at" style="color:var(--wh)">Not identified at ${ts(t)}</b><span>${s ? `nothing matched between ${ts(s.start)} and ${ts(s.end ?? state.set.source.duration)}` : 'outside the set'}</span>`;
    const c = $('#askCopy'); if (c) c.onclick = () => copy(`${ts(t)} ${s.track.artist} - ${s.track.title}`, 'Answer copied');
    const l = $('#askLink'); if (l) l.onclick = ev => { ev.preventDefault(); copy(location.origin + location.pathname + `?t=${Math.floor(t)}#/set/${state.key}`, 'Link copied'); };
  }
  $('#askGo').onclick = () => { const t = parseTs($('#askT').value); if (t == null) return toast('Use m:ss or h:mm:ss'); seek(t); askAt(t); };
  $('#askT').addEventListener('keydown', e => { if (e.key === 'Enter') $('#askGo').click(); });
  $('#copyTl').onclick = () => copy(tracklistText(), 'Tracklist copied');
  $('#addAll').onclick = () => { let n = 0; state.set.segments.forEach(s => { if (s.track && !state.setlist.some(x => x.id === s.track.id)) { state.setlist.push(s.track); n++; } }); saveSl(); toast(`Added ${n} tracks`); renderSet(state.key); };
  function tracklistText() { const d = state.set; return `${d.source.title}\n${d.source.url}\n\n` + d.segments.map(s => `${ts(s.start)} ${s.track ? s.track.artist + ' - ' + s.track.title : 'ID?'}`).join('\n') + '\n\nvia SetID'; }

  // ---------- previews + add (delegated) ----------
  document.addEventListener('click', e => {
    const pv = e.target.closest('[data-pv]'); if (pv) { e.stopPropagation(); preview(pv.dataset.pv); return; }
    const add = e.target.closest('[data-add]'); if (add) { e.stopPropagation(); const t = state.tracks[add.dataset.add]; if (t && !state.setlist.some(x => x.id === t.id)) { state.setlist.push(t); saveSl(); add.disabled = true; add.textContent = add.textContent.trim() === '+' ? '✓' : 'Added'; renderSetlist(); toast(`Added "${t.title}"`); } }
  });

  // ---------- setlist ----------
  function saveSl() { localStorage.setItem('setid.setlist', JSON.stringify(state.setlist)); $('#slCount').textContent = state.setlist.length; }
  function renderSetlist() {
    $('#slCount').textContent = state.setlist.length;
    const L = state.setlist;
    $('#sl').innerHTML = L.length ? L.map((t, i) => `<div class="it"><div class="n">${i + 1}</div><div style="min-width:0"><div class="ti">${h(t.title)}</div><div class="ar">${h(t.artist)}${t.bpm ? ' · ' + Math.round(t.bpm) : ''}</div></div><div class="ctl"><button data-mv="${i}:-1" aria-label="Move up">${icon('up')}</button><button data-mv="${i}:1" aria-label="Move down">${icon('down')}</button><button data-rm="${i}" aria-label="Remove">${icon('x')}</button></div></div>`).join('') : '<div class="empty">Add tracks from the tracklist or from "similar". The setlist stays with you across sets.</div>';
    const withYt = L.filter(t => t.youtube).length;
    $('#slFine').innerHTML = L.length ? `${L.length} tracks · ${withYt} resolved on YouTube · ${L.filter(t => t.apple).length} with Apple Music links.${CONFIG.spotifyClientId ? '' : ' Spotify: one-tap playlist needs a Spotify app id (see README); until then it opens a search per track.'} Apple Music: opens each track; a native playlist needs an Apple developer token.` : '';
  }
  $('#sl').addEventListener('click', e => {
    const mv = e.target.closest('[data-mv]'), rm = e.target.closest('[data-rm]');
    if (mv) { const [i, d] = mv.dataset.mv.split(':').map(Number), j = i + d; if (j >= 0 && j < state.setlist.length) { [state.setlist[i], state.setlist[j]] = [state.setlist[j], state.setlist[i]]; saveSl(); renderSetlist(); } }
    if (rm) { state.setlist.splice(+rm.dataset.rm, 1); saveSl(); renderSetlist(); document.querySelectorAll('[data-add]').forEach(b => { if (!state.setlist.some(x => x.id === b.dataset.add)) { b.disabled = false; b.textContent = b.closest('.sim') ? '+' : '+ Setlist'; } }); }
  });
  $('#slClear').onclick = () => { state.setlist = []; saveSl(); renderSetlist(); if (state.key) renderSet(state.key); };
  $('#exports').addEventListener('click', async e => {
    const b = e.target.closest('[data-x]'); if (!b) return;
    const L = state.setlist; if (!L.length) return toast('Your setlist is empty');
    const k = b.dataset.x;
    if (k === 'yt') { const ids = L.filter(t => t.youtube).map(t => t.youtube).slice(0, 50); if (!ids.length) return toast('No YouTube matches in this setlist'); window.open(`https://www.youtube.com/watch_videos?video_ids=${ids.join(',')}`, '_blank'); toast(`Opened a ${ids.length}-track playlist on YouTube. Save it from the ⋯ menu to keep it.`); }
    if (k === 'sp') { if (CONFIG.spotifyClientId) return spotifyExport(); copy(L.map(t => `${t.artist} - ${t.title}`).join('\n'), 'List copied. Opening Spotify searches…'); L.slice(0, 5).forEach((t, i) => setTimeout(() => window.open(links(t).sp, '_blank'), i * 250)); }
    if (k === 'ap') { copy(L.map(t => `${t.artist} - ${t.title}`).join('\n'), 'List copied. Opening Apple Music…'); L.slice(0, 5).forEach((t, i) => setTimeout(() => window.open(links(t).ap, '_blank'), i * 250)); }
    if (k === 'txt') copy(L.map((t, i) => `${i + 1}. ${t.artist} - ${t.title}`).join('\n') + '\n\nvia SetID', 'Setlist copied');
    if (k === 'm3u') download('setid-setlist.m3u8', '#EXTM3U\n' + L.map(t => `#EXTINF:-1,${t.artist} - ${t.title}\n${links(t).yt}`).join('\n') + '\n', 'audio/x-mpegurl');
    if (k === 'csv') { const qq = v => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`; download('setid-setlist.csv', [['#', 'Artist', 'Title', 'Label', 'BPM', 'YouTube', 'Apple Music', 'Deezer']].concat(L.map((t, i) => [i + 1, t.artist, t.title, t.label, t.bpm ? Math.round(t.bpm) : '', links(t).yt, links(t).ap, t.deezer || ''])).map(r => r.map(qq).join(',')).join('\n') + '\n', 'text/csv'); }
  });

  // ---------- Spotify (PKCE) ----------
  async function spotifyExport() {
    const tok = sessionStorage.getItem('sp.token');
    if (!tok) { sessionStorage.setItem('sp.pending', '1'); return spotifyLogin(); }
    const me = await spGet('/me', tok); if (!me || !me.id) { sessionStorage.removeItem('sp.token'); return spotifyLogin(); }
    const uris = [];
    for (const t of state.setlist) { const r = await spGet(`/search?type=track&limit=1&q=${q(`track:${t.title} artist:${t.artist.split(/[,&]/)[0]}`)}`, tok); const it = r && r.tracks && r.tracks.items[0]; if (it) uris.push(it.uri); }
    if (!uris.length) return toast('Spotify found none of these tracks');
    const pl = await spPost(`/users/${me.id}/playlists`, tok, { name: 'SetID setlist', description: 'Built with SetID', public: false });
    await spPost(`/playlists/${pl.id}/tracks`, tok, { uris });
    toast(`Spotify playlist created with ${uris.length}/${state.setlist.length} tracks`); window.open(pl.external_urls.spotify, '_blank');
  }
  const spGet = (p, tok) => fetch('https://api.spotify.com/v1' + p, { headers: { Authorization: 'Bearer ' + tok } }).then(r => r.ok ? r.json() : null);
  const spPost = (p, tok, body) => fetch('https://api.spotify.com/v1' + p, { method: 'POST', headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json());
  async function spotifyLogin() {
    const verifier = [...crypto.getRandomValues(new Uint8Array(48))].map(b => 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'[b % 62]).join('');
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    const challenge = btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    sessionStorage.setItem('sp.verifier', verifier); sessionStorage.setItem('sp.return', location.hash);
    const redirect = location.origin + location.pathname;
    location.href = `https://accounts.spotify.com/authorize?client_id=${CONFIG.spotifyClientId}&response_type=code&redirect_uri=${q(redirect)}&scope=${q('playlist-modify-private playlist-modify-public')}&code_challenge_method=S256&code_challenge=${challenge}`;
  }
  async function spotifyCallback() {
    const code = new URLSearchParams(location.search).get('code'); if (!code || !CONFIG.spotifyClientId) return;
    const redirect = location.origin + location.pathname;
    const r = await fetch('https://accounts.spotify.com/api/token', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ client_id: CONFIG.spotifyClientId, grant_type: 'authorization_code', code, redirect_uri: redirect, code_verifier: sessionStorage.getItem('sp.verifier') || '' }) }).then(r => r.json());
    if (r.access_token) { sessionStorage.setItem('sp.token', r.access_token); history.replaceState(null, '', location.pathname + (sessionStorage.getItem('sp.return') || '#/')); if (sessionStorage.getItem('sp.pending')) { sessionStorage.removeItem('sp.pending'); setTimeout(spotifyExport, 300); } }
  }

  // ---------- router ----------
  async function route() {
    const m = location.hash.match(/^#\/set\/([\w-]+)/);
    if (m) { const t = new URLSearchParams(location.search).get('t'); await renderSet(m[1], t != null ? +t : null); window.scrollTo({ top: 0 }); }
    else {
      renderHome();
      const q = new URLSearchParams((location.hash.split('?')[1]) || '').get('q');  // e.g. from the extension's "Request it"
      if (q && !state.prefilled) { state.prefilled = true; $('#pasteQ').value = q; onPaste(q); }
    }
  }
  window.addEventListener('hashchange', route);
  (async () => { await loadIndex(); await spotifyCallback(); renderSetlist(); route(); })();
})();
