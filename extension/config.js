/* SetID extension config. The ONE place the data/site origin lives.
   To move to another host (e.g. a Vercel domain), change BASE here and the
   matching entry in manifest.json "host_permissions". */
(function (g) {
  'use strict';
  const BASE = 'https://thinkpool-io.github.io/setid';
  g.SETID_CONFIG = Object.freeze({
    BASE,
    INDEX_URL: BASE + '/sets/index.json',
    setUrl: (key) => BASE + '/sets/' + encodeURIComponent(key) + '.json',
    siteSetUrl: (key) => BASE + '/#/set/' + encodeURIComponent(key),
    // The site ignores unknown hash params today and just shows the home page; harmless and forward-compatible.
    requestUrl: (watchUrl) => BASE + '/#/?q=' + encodeURIComponent(watchUrl),
    HOME_URL: BASE + '/',
    LONG_VIDEO_SECONDS: 20 * 60, // only nag "no tracklist yet" on videos longer than this
    CACHE_MS: 10 * 60 * 1000,
  });
})(typeof self !== 'undefined' ? self : this);
