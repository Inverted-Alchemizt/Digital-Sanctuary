// ─── Digital Sanctuary PWA Service Worker ────────────────────────────────────
// Cache-first for shell assets, Network-first for data files.

const CACHE_NAME = 'ds-shell-v3';
const DATA_CACHE_NAME = 'ds-data-v3';

// Core app shell files — cached on install
const SHELL_ASSETS = [
  './index.html',
  './data.js',
  './data_central.js',
  // External CDN resources cached on first visit (runtime caching handles these)
];

// Data files — always fetch fresh from network first
const DATA_FILES = [
  './data.json',
  './data_central.json',
];

// ─── Install ──────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log('[SW] Pre-caching app shell');
      return cache.addAll(SHELL_ASSETS);
    })
  );
  self.skipWaiting(); // Activate immediately
});

// ─── Activate ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME && k !== DATA_CACHE_NAME)
          .map(k => {
            console.log('[SW] Deleting old cache:', k);
            return caches.delete(k);
          })
      )
    )
  );
  self.clients.claim(); // Take control of open pages immediately
});

// ─── Fetch ────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Only handle same-origin GET requests
  if (event.request.method !== 'GET') return;

  // ── Strategy: Network First for index.html / root to prevent outdated caching ──
  const isHtml = url.pathname === '/' || url.pathname.endsWith('index.html');
  if (isHtml) {
    event.respondWith(networkFirst(event.request, CACHE_NAME));
    return;
  }

  // ── Strategy: Network First for data.json / data_central.json ──────────────
  const isDataFile = DATA_FILES.some(f => url.pathname.endsWith(f.replace('./', '')));
  if (isDataFile) {
    event.respondWith(networkFirst(event.request, DATA_CACHE_NAME));
    return;
  }

  // ── Strategy: Cache First (with network fallback) for shell assets ──────────
  // Only apply to same-origin requests to avoid issues with CDN opaque responses
  if (url.origin === self.location.origin && !url.pathname.startsWith('/api/')) {
    event.respondWith(cacheFirst(event.request, CACHE_NAME));
  }
  // For cross-origin (CDN) requests, let the browser handle normally
});

// ─── Network First: try network, fall back to cache ──────────────────────────
async function networkFirst(request, cacheName) {
  const urlWithoutQuery = request.url.split('?')[0];
  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.status === 200) {
      const cache = await caches.open(cacheName);
      cache.put(urlWithoutQuery, networkResponse.clone());
    }
    return networkResponse;
  } catch (err) {
    console.warn('[SW] Network failed for', request.url, '— serving from cache');
    const cache = await caches.open(cacheName);
    const cached = await cache.match(urlWithoutQuery);
    return cached || new Response(JSON.stringify({ jobs: [], last_updated: null, error: 'offline' }), {
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

// ─── Cache First: serve from cache, update in background ─────────────────────
async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.status === 200) {
      const cache = await caches.open(cacheName);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (err) {
    console.warn('[SW] Cache miss and network failed for', request.url);
    return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
  }
}
