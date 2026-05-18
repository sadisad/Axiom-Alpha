/* Axiom Alpha service worker.
 *
 * Strategy:
 *   - HTML pages: network-first, fall back to cached "/offline" (or last-good copy).
 *   - Static assets (CSS/JS/images): stale-while-revalidate.
 *   - API endpoints (/api/*): network-only, no caching (data is live).
 *
 * Bump SW_VERSION when CSS/JS changes so old caches are evicted.
 */
const SW_VERSION = 'axiom-v1';
const STATIC_CACHE = `static-${SW_VERSION}`;
const PAGE_CACHE   = `pages-${SW_VERSION}`;

// Pre-cache the bare minimum to render an offline shell.
const PRECACHE = [
  '/static/alerts/css/base.css',
  '/static/alerts/images/AxiomAlpha-logo-transparent.png',
  '/static/alerts/images/favicon.ico',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !k.endsWith(SW_VERSION)).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isStatic(url) {
  return /\.(css|js|png|jpg|jpeg|svg|ico|woff2?|ttf)$/.test(url.pathname) ||
         url.pathname.startsWith('/static/');
}
function isApi(url) {
  return url.pathname.startsWith('/api/');
}
function isHtml(request) {
  return request.mode === 'navigate' ||
         (request.headers.get('accept') || '').includes('text/html');
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Only handle same-origin requests; let TradingView, Google Fonts, etc. through.
  if (url.origin !== location.origin) return;

  // Never cache POST or non-GET
  if (event.request.method !== 'GET') return;

  // API: always go to network, never cache.
  if (isApi(url)) return;

  if (isStatic(url)) {
    // Stale-while-revalidate
    event.respondWith(
      caches.open(STATIC_CACHE).then(async (cache) => {
        const cached = await cache.match(event.request);
        const networkPromise = fetch(event.request).then((res) => {
          if (res && res.status === 200) cache.put(event.request, res.clone());
          return res;
        }).catch(() => cached);
        return cached || networkPromise;
      })
    );
    return;
  }

  if (isHtml(event.request)) {
    // Network-first with cache fallback.
    event.respondWith(
      fetch(event.request).then((res) => {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(PAGE_CACHE).then((c) => c.put(event.request, copy));
        }
        return res;
      }).catch(() => caches.match(event.request).then((m) => m || caches.match('/')))
    );
  }
});
