/* Toolbar popup: status of the current tab (asked from the content script) and a short library list. */
(function () {
  'use strict';
  const C = self.SETID_CONFIG;
  const $ = (s) => document.querySelector(s);
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) { if (k === 'text') n.textContent = v; else if (k === 'class') n.className = v; else n.setAttribute(k, v); }
    n.append(...kids.filter(Boolean)); return n;
  };
  const dur = (s) => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? h + ' h ' + m + ' min' : m + ' min'; };
  $('#home').href = C.HOME_URL;

  function showStatus(info) {
    const box = $('#status');
    box.className = '';
    if (!info || !info.videoId) { box.replaceChildren(el('p', { class: 'muted', text: 'Open a YouTube video to see its tracklist here.' })); return; }
    if (info.kind === 'set') {
      box.className = 'ok';
      const kids = [el('p', { class: 'k', text: 'This video · ' + info.tracks + ' tracks identified' })];
      if (info.now) kids.push(el('p', { class: 't', text: info.now.title }), el('p', { class: 'a', text: info.now.artist + ' · from ' + info.now.at }));
      else kids.push(el('p', { class: 'muted', text: 'Nothing identified at this moment.' }));
      kids.push(el('p', {}, el('a', { href: C.siteSetUrl(info.key), target: '_blank', rel: 'noopener', text: 'Open in SetID ↗' })));
      box.replaceChildren(...kids); return;
    }
    if (info.kind === 'none') {
      box.replaceChildren(el('p', { text: 'No tracklist for this video yet.' }),
        el('p', {}, el('a', { href: C.requestUrl('https://www.youtube.com/watch?v=' + info.videoId), target: '_blank', rel: 'noopener', text: 'Request it ↗' })));
      return;
    }
    if (info.kind === 'error') { box.replaceChildren(el('p', { class: 'muted', text: 'Could not reach SetID right now.' })); return; }
    box.replaceChildren(el('p', { class: 'muted', text: 'Looking this video up…' }));
  }

  chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
    if (!tab || tab.id == null) return showStatus(null);
    chrome.tabs.sendMessage(tab.id, { type: 'status' }).then(showStatus, () => showStatus(null));
  });

  chrome.runtime.sendMessage({ type: 'index' }).then((res) => {
    const ul = $('#sets');
    if (!res || !res.ok) { ul.replaceChildren(el('li', { class: 'muted', text: 'Could not load the library.' })); return; }
    const items = res.index.slice(0, 8).map((x) => el('li', {}, el('a', { href: x.url || ('https://www.youtube.com/watch?v=' + String(x.key).replace(/^youtube-/, '')), target: '_blank', rel: 'noopener' },
      el('span', { class: 't1', text: x.title }),
      el('span', { class: 's', text: [x.channel, x.tracks != null ? x.tracks + ' tracks' : '', x.duration ? dur(x.duration) : ''].filter(Boolean).join(' · ') }))));
    ul.replaceChildren(...(items.length ? items : [el('li', { class: 'muted', text: 'The library is empty.' })]));
  });
})();
