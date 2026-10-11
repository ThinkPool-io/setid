/* SetID extension config. The ONE place the data/site origin lives.
   To move to another host (e.g. a Vercel domain), change BASE here and the
   matching entry in manifest.json "host_permissions". */
(function (g) {
  'use strict';
  const BASE = 'https://setid.vercel.app';
  g.SETID_CONFIG = Object.freeze({
    BASE,
    INDEX_URL: BASE + '/api/sets/index.json',
    setUrl: (key) => BASE + '/api/sets/' + encodeURIComponent(key) + '.json',
    siteSetUrl: (key) => BASE + '/#/set/' + encodeURIComponent(key),
    // The site reads q= and queues that set straight away.
    requestUrl: (watchUrl) => BASE + '/#/?q=' + encodeURIComponent(watchUrl),
    HOME_URL: BASE + '/',
    LONG_VIDEO_SECONDS: 20 * 60, // only nag "no tracklist yet" on videos longer than this
    CACHE_MS: 2 * 60 * 1000,
  });
})(typeof self !== 'undefined' ? self : this);
