/* SetID content script for youtube.com.
   Runs on all of www.youtube.com because YouTube is a single-page app: going from the
   home page to a /watch page never reloads, so a /watch-only match would miss it.
   Off /watch pages it does nothing except tear down. No remote code, no innerHTML. */
(function () {
  'use strict';
  if (window.__setidLoaded) return;
  window.__setidLoaded = true;

  const C = self.SETID_CONFIG;
  const ROOT_ID = 'setid-root';

  // ---------- helpers ----------
  const ts = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    const hh = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
    return (hh ? hh + ':' + String(m).padStart(2, '0') : String(m).padStart(2, '0')) + ':' + String(ss).padStart(2, '0');
  };
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const k of kids.flat()) if (k != null && k !== false) n.append(k);
    return n;
  }
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function videoIdFromUrl() {
    if (location.pathname !== '/watch') return null;
    const v = new URLSearchParams(location.search).get('v');
    return v && /^[\w-]{6,20}$/.test(v) ? v : null;
  }
  const player = () => document.querySelector('#movie_player');
  const mainVideo = () => document.querySelector('#movie_player video.html5-main-video') || document.querySelector('#movie_player video');
  const adShowing = () => { const p = player(); return !!(p && p.classList.contains('ad-showing')); };

  // Evidence label, mirroring the SetID site's wording.
  function evidence(seg) {
    const t = seg.track;
    if (!t) return '';
    const src = t.source || t.provider;
    const parts = [];
    if (src === 'shazam') {
      parts.push(t.samples ? 'Shazam · ' + plural(t.samples, 'clip', 'clips') : 'Shazam');
      if (t.catalog) parts.push('catalogue agrees');
      if (t.commentVotes) parts.push('also named by ' + t.commentVotes + ' in comments');
      if ((t.samples === 1 || (!t.samples && seg.hits === 1)) && !t.catalog && !t.commentVotes) parts.push('low confidence');
    } else if (src === 'audio' || src === 'both') {
      parts.push('audio match');
      const v = t.commentVotes || (src === 'both' ? t.votes : 0);
      if (v) parts.push('also named by ' + v + ' in comments');
      if (t.pitch) parts.push('pitched ' + (t.pitch > 0 ? '+' : '') + t.pitch + '%');
    } else if (src === 'comments') {
      parts.push('from comments', plural(t.votes || 0, 'person', 'people'));
      if (t.approx) parts.push('time approx');
      parts.push('not audio-confirmed');
    } else if (seg.hits === 1) parts.push('low confidence');
    return parts.join(' · ');
  }
  const weakEvidence = (seg) => {
    const t = seg.track; if (!t) return false;
    const src = t.source || t.provider;
    return src === 'comments' || (src === 'shazam' && (t.samples === 1 || (!t.samples && seg.hits === 1)) && !t.catalog && !t.commentVotes);
  };
  function tempo(t) {
    if (!t || !(t.playedBpm > 0)) return '';
    let s = 'played at ' + Math.round(t.playedBpm) + ' BPM';
    if (t.originalBpm > 0) {
      const pct = Math.round((t.playedBpm / t.originalBpm - 1) * 100);
      s += ' · ' + (pct > 0 ? '+' : pct < 0 ? '−' : '±') + Math.abs(pct) + '%';
    }
    return s;
  }
  const segEnd = (seg, set) => (seg.end == null ? (set.source && set.source.duration) || Infinity : seg.end);
  function segIndexAt(set, t) {
    const segs = set.segments || [];
    for (let i = segs.length - 1; i >= 0; i--) if (segs[i].start != null && t >= segs[i].start) return t < segEnd(segs[i], set) ? i : -1;
    return -1;
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall back */ }
    const ta = el('textarea', { style: 'position:fixed;opacity:0;left:-9999px', 'aria-hidden': 'true' });
    ta.value = text; document.body.append(ta); ta.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove(); return ok;
  }

  // ---------- state ----------
  // st.kind: 'loading' | 'set' | 'none' | 'error'
  let st = null;
  let gen = 0;

  function teardown() {
    gen++;
    const r = document.getElementById(ROOT_ID);
    if (r) r.remove();
    if (st && st.flashT) clearTimeout(st.flashT);
    st = null;
  }

  function mountPoint() {
    // Directly under the player, above the title block.
    return document.querySelector('ytd-watch-flexy #below');
  }
  function attach(root) {
    const mp = mountPoint();
    if (!mp) return false;
    if (root.parentNode !== mp) mp.prepend(root);
    return true;
  }

  async function start(videoId) {
    teardown();
    const my = gen;
    st = { videoId, kind: 'loading', root: null, cur: -2, open: false };
    let res;
    try { res = await chrome.runtime.sendMessage({ type: 'lookup', videoId }); }
    catch (e) { res = { ok: false, error: String(e) }; }
    if (my !== gen) return; // navigated away meanwhile
    if (!res || !res.ok) { st.kind = 'error'; st.error = res && res.error; return; }
    st.key = res.key;
    if (res.set && Array.isArray(res.set.segments)) { st.kind = 'set'; st.set = res.set; buildPanel(); }
    else { st.kind = 'none'; maybeBuildBar(); }
  }

  // ---------- "no tracklist yet" bar ----------
  function maybeBuildBar() {
    if (!st || st.kind !== 'none' || st.root) return;
    const v = mainVideo();
    if (!v || adShowing() || !isFinite(v.duration) || v.duration <= C.LONG_VIDEO_SECONDS) return;
    const watchUrl = 'https://www.youtube.com/watch?v=' + st.videoId;
    st.root = el('div', { id: ROOT_ID, class: 'setid setid-bar', role: 'region', 'aria-label': 'SetID' },
      el('span', { class: 'setid-dot', 'aria-hidden': 'true' }),
      el('span', { class: 'setid-bar-text' }, el('b', { text: 'SetID' }), ': no tracklist yet'),
      el('a', { class: 'setid-btn', href: C.requestUrl(watchUrl), target: '_blank', rel: 'noopener', text: 'Request it' }));
    attach(st.root);
  }

  // ---------- full panel ----------
  function buildPanel() {
    const set = st.set;
    const cover = el('img', { class: 'setid-cover', alt: '', width: 56, height: 56, decoding: 'async', referrerpolicy: 'no-referrer' });
    const coverBox = el('div', { class: 'setid-cover-box', 'aria-hidden': 'true' }, cover);
    const kicker = el('div', { class: 'setid-kicker' }, el('span', { class: 'setid-dot', 'aria-hidden': 'true' }), el('span', { class: 'setid-kicker-text', text: 'Now playing' }));
    const title = el('div', { class: 'setid-title' });
    const meta = el('div', { class: 'setid-meta' });
    const now = el('div', { class: 'setid-now', 'aria-live': 'polite', 'aria-atomic': 'true' }, title, meta);

    const copyBtn = el('button', { type: 'button', class: 'setid-btn setid-btn-primary', onclick: onCopy, text: 'Copy track ID' });
    const listId = 'setid-list-' + st.videoId;
    const toggle = el('button', { type: 'button', class: 'setid-btn', 'aria-expanded': 'false', 'aria-controls': listId, onclick: onToggle },
      el('span', { text: 'Tracklist' }), el('span', { class: 'setid-chev', 'aria-hidden': 'true' }));
    const open = el('a', { class: 'setid-link', href: C.siteSetUrl(st.key), target: '_blank', rel: 'noopener', text: 'Open in SetID ↗' });
    const status = el('span', { class: 'setid-sr', role: 'status' });
    const actions = el('div', { class: 'setid-actions' }, copyBtn, toggle, open, status);

    const ided = set.segments.filter((s) => s.track).length;
    const rows = set.segments.map((seg, i) => {
      const t = seg.track;
      const lab = t ? evidence(seg) : 'no confident match';
      const tp = t ? tempo(t) : '';
      return el('li', null, el('button', {
        type: 'button', class: 'setid-row' + (t ? '' : ' setid-unk') + (weakEvidence(seg) ? ' setid-weak' : ''),
        'data-i': i, onclick: () => seekTo(seg.start),
        'aria-label': ts(seg.start) + ', ' + (t ? t.artist + ' - ' + t.title : 'unidentified') + '. Seek here.',
      },
        el('span', { class: 'setid-ts', text: ts(seg.start) }),
        el('span', { class: 'setid-rt', text: t ? t.title : 'Unidentified' }),
        el('span', { class: 'setid-ra', text: t ? t.artist : ts(seg.start) + ' to ' + ts(segEnd(seg, set)) }),
        el('span', { class: 'setid-rl', text: [lab, tp].filter(Boolean).join(' · ') })));
    });
    const list = el('ol', { class: 'setid-list', id: listId, hidden: true, 'aria-label': 'Tracklist, ' + plural(ided, 'track', 'tracks') + ' identified' }, rows);

    st.root = el('section', { id: ROOT_ID, class: 'setid setid-panel', 'aria-label': 'SetID tracklist' },
      el('div', { class: 'setid-head' }, coverBox, el('div', { class: 'setid-body' }, kicker, now), actions),
      list);
    st.ui = { cover, coverBox, title, meta, kicker: kicker.querySelector('.setid-kicker-text'), copyBtn, toggle, list, status };
    attach(st.root);
    update(true);
  }

  function update(force) {
    if (!st || st.kind !== 'set' || !st.ui) return;
    const v = mainVideo();
    if (!v || adShowing()) return;
    const t = v.currentTime;
    const i = segIndexAt(st.set, t);
    const u = st.ui;
    u.kicker.textContent = 'Now playing · ' + ts(t);
    if (i === st.cur && !force) return;
    st.cur = i;
    const seg = i >= 0 ? st.set.segments[i] : null;
    const tr = seg && seg.track;
    if (tr) {
      u.title.textContent = tr.title;
      u.meta.replaceChildren(
        el('span', { class: 'setid-artist', text: tr.artist }),
        el('span', { class: 'setid-ev' + (weakEvidence(seg) ? ' setid-weak' : ''), text: evidence(seg) }),
        ...(tempo(tr) ? [el('span', { class: 'setid-tempo', text: tempo(tr) })] : []));
      if (tr.cover) { if (u.cover.getAttribute('src') !== tr.cover) u.cover.src = tr.cover; u.coverBox.classList.remove('setid-empty'); }
      else { u.cover.removeAttribute('src'); u.coverBox.classList.add('setid-empty'); }
      u.copyBtn.disabled = false;
    } else {
      u.title.textContent = seg ? 'Not identified yet' : 'Outside the tracklist';
      u.meta.replaceChildren(el('span', { class: 'setid-ev', text: seg ? 'nothing matched between ' + ts(seg.start) + ' and ' + ts(segEnd(seg, st.set)) : '' }));
      u.cover.removeAttribute('src'); u.coverBox.classList.add('setid-empty');
      u.copyBtn.disabled = true;
    }
    st.root.classList.toggle('setid-has-track', !!tr);
    // highlight + keep in view (scroll the list only, never the page)
    const prev = u.list.querySelector('.setid-row[aria-current]');
    if (prev) prev.removeAttribute('aria-current');
    const row = i >= 0 ? u.list.querySelector('.setid-row[data-i="' + i + '"]') : null;
    if (row) { row.setAttribute('aria-current', 'true'); if (st.open) keepInView(row.parentElement); }
  }

  function keepInView(li) {
    const L = st.ui.list;
    const top = li.offsetTop - L.offsetTop, bottom = top + li.offsetHeight;
    if (top >= L.scrollTop && bottom <= L.scrollTop + L.clientHeight) return;
    const target = Math.max(0, top - L.clientHeight / 2 + li.offsetHeight / 2);
    L.scrollTo({ top: target, behavior: reducedMotion() ? 'auto' : 'smooth' });
  }

  function seekTo(sec) {
    const v = mainVideo();
    if (!v || sec == null) return;
    v.currentTime = sec;
    if (v.paused) v.play().catch(() => {});
    update(true);
  }

  async function onCopy() {
    if (!st || st.cur < 0) return;
    const seg = st.set.segments[st.cur];
    if (!seg.track) return;
    const text = ts(seg.start) + ' ' + seg.track.artist + ' - ' + seg.track.title;
    const ok = await copyText(text);
    flash(ok ? 'Copied: ' + text : 'Copy failed');
  }
  function flash(msg) {
    const b = st.ui.copyBtn, s = st.ui.status;
    s.textContent = msg;
    b.textContent = msg.startsWith('Copied') ? 'Copied ✓' : 'Copy failed';
    clearTimeout(st.flashT);
    st.flashT = setTimeout(() => { if (st && st.ui) { st.ui.copyBtn.textContent = 'Copy track ID'; st.ui.status.textContent = ''; } }, 1800);
  }

  function onToggle() {
    st.open = !st.open;
    st.ui.toggle.setAttribute('aria-expanded', String(st.open));
    st.ui.list.hidden = !st.open;
    st.root.classList.toggle('setid-open', st.open);
    if (st.open) { const r = st.ui.list.querySelector('.setid-row[aria-current]'); if (r) keepInView(r.parentElement); }
  }

  // ---------- wiring ----------
  // Media events don't bubble, but a capture listener on document still sees them,
  // so this survives YouTube replacing the <video> element.
  const isMain = (e) => e.target instanceof HTMLVideoElement && e.target.closest('#movie_player');
  for (const ev of ['timeupdate', 'seeking', 'seeked']) document.addEventListener(ev, (e) => { if (isMain(e)) update(ev !== 'timeupdate'); }, true);
  for (const ev of ['loadedmetadata', 'durationchange']) document.addEventListener(ev, (e) => { if (isMain(e)) maybeBuildBar(); }, true);

  let lastId;
  function check() {
    const id = videoIdFromUrl();
    if (id !== lastId) { lastId = id; if (id) start(id); else teardown(); return; }
    if (!st) return;
    if (st.root && !st.root.isConnected) attach(st.root); // not mounted yet, or YouTube re-rendered #below
    if (st.kind === 'none') maybeBuildBar();
  }
  document.addEventListener('yt-navigate-finish', check);
  window.addEventListener('popstate', check);
  setInterval(check, 1000); // cheap fallback for URL changes and remounts
  check();

  // ---------- popup status ----------
  chrome.runtime.onMessage.addListener((msg, _s, reply) => {
    if (!msg || msg.type !== 'status') return;
    const out = { videoId: videoIdFromUrl(), kind: st ? st.kind : 'idle', key: st && st.key };
    if (st && st.kind === 'set') {
      const seg = st.cur >= 0 ? st.set.segments[st.cur] : null;
      out.title = st.set.source && st.set.source.title;
      out.tracks = st.set.segments.filter((s) => s.track).length;
      out.now = seg && seg.track ? { at: ts(seg.start), artist: seg.track.artist, title: seg.track.title } : null;
    }
    reply(out);
  });
})();
