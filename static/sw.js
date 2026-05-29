/**
 * Service Worker — Souza Pinto PWA Offline
 * Versão: 1.1.7 (sem cache para admin routes)
 *
 * Estratégias:
 * - Cache First → assets estáticos (CSS, JS) e CDN (Alpine, Lucide, fontes)
 * - Network First com fallback → páginas /mobile/* ; GET my-routes não passa pelo SW (sempre rede)
 * - Fallback HTML offline para navegação sem cache
 * - Background Sync → fila de ações offline (IndexedDB)
 */

const SW_VERSION = 'nl-entregas-v1.1.8';
const ASSETS_CACHE = `${SW_VERSION}-assets`;
const DATA_CACHE = `${SW_VERSION}-data`;
const CDN_CACHE = `${SW_VERSION}-cdn`;
const SYNC_TAG = 'delivery-sync';

// Assets do nosso servidor — pré-cache na instalação
const PRECACHE_ASSETS = [
  '/static/css/mobile.css',
  '/static/styles.css',
  '/static/manifest.json',
  '/static/icons/pwa-192.png',
  '/static/icons/pwa-512.png',
];

// URLs de CDN que o mobile usa — cacheadas para funcionar offline
const PRECACHE_CDN = [
  'https://cdn.jsdelivr.net/npm/alpinejs@3.14.7/dist/cdn.min.js',
  'https://cdn.jsdelivr.net/npm/lucide@0.469.0/dist/umd/lucide.min.js',
  'https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.2/dist/confetti.browser.min.js',
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap',
  'https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Sora:wght@600;700&display=swap',
];

// APIs com cache SW (offline). Admin routes não entra aqui para evitar dado stale.
const CACHEABLE_API_ROUTES = [
];

// HTML mínimo exibido quando o usuário está offline e a página não está em cache
const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Offline - Souza Pinto</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0; min-height: 100vh; display: flex; flex-direction: column;
      align-items: center; justify-content: center; padding: 24px;
      background: #0f172a; color: #e2e8f0; text-align: center;
    }
    h1 { font-size: 1.5rem; margin-bottom: 8px; }
    p { color: #94a3b8; margin-bottom: 24px; }
    a { color: #60a5fa; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .retry { margin-top: 16px; padding: 10px 20px; background: #3b82f6; color: white; border-radius: 8px; border: none; font-size: 1rem; cursor: pointer; }
    .retry:hover { background: #2563eb; }
  </style>
</head>
<body>
  <h1>Você está offline</h1>
  <p>Conecte-se à internet para usar o app. Páginas que você já visitou podem funcionar com dados em cache.</p>
  <button class="retry" onclick="window.location.reload()">Tentar novamente</button>
  <p style="margin-top: 24px;"><a href="/mobile/dashboard">Abrir início (quando online)</a></p>
</body>
</html>`;

// HTML exibido quando o servidor está online, mas temporariamente indisponível (ex.: DB iniciando).
const SERVER_UNAVAILABLE_HTML = `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Serviço a iniciar - Souza Pinto</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0; min-height: 100vh; display: flex; flex-direction: column;
      align-items: center; justify-content: center; padding: 24px;
      background: #0f172a; color: #e2e8f0; text-align: center;
    }
    h1 { font-size: 1.5rem; margin-bottom: 8px; }
    p { color: #94a3b8; margin-bottom: 24px; }
    a { color: #60a5fa; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .retry { margin-top: 16px; padding: 10px 20px; background: #3b82f6; color: white; border-radius: 8px; border: none; font-size: 1rem; cursor: pointer; }
    .retry:hover { background: #2563eb; }
  </style>
</head>
<body>
  <h1>Serviço a iniciar</h1>
  <p>Você está online, mas o servidor ainda está preparando a base de dados. Tente novamente em instantes.</p>
  <button class="retry" onclick="window.location.reload()">Tentar novamente</button>
  <p style="margin-top: 24px;"><a href="/mobile/dashboard">Abrir início</a></p>
</body>
</html>`;

// ──────────────────────────────────────────────
// INSTALL — pré-cacheia assets e CDN
// ──────────────────────────────────────────────
self.addEventListener('install', (event) => {
  console.log('[SW] Instalando versão:', SW_VERSION);
  event.waitUntil(
    (async () => {
      const [assetsCache, cdnCache] = await Promise.all([
        caches.open(ASSETS_CACHE),
        caches.open(CDN_CACHE),
      ]);
      for (const url of PRECACHE_ASSETS) {
        try {
          await assetsCache.add(url);
        } catch (e) {
          console.warn('[SW] Não foi possível pré-cachear:', url, e.message);
        }
      }
      for (const url of PRECACHE_CDN) {
        try {
          const req = new Request(url, { mode: 'cors', credentials: 'omit' });
          const res = await fetch(req);
          if (res && res.ok) {
            await cdnCache.put(req, res.clone());
          } else {
            console.warn('[SW] CDN respondeu com', res.status, url);
          }
        } catch (e) {
          console.warn('[SW] CDN não pré-cacheado:', url, e.message);
        }
      }
      console.log('[SW] Assets e CDN pré-cacheados.');
    })()
  );
  self.skipWaiting();
});

// ──────────────────────────────────────────────
// ACTIVATE — limpa caches antigos
// ──────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  console.log('[SW] Ativando:', SW_VERSION);
  const keepCaches = [ASSETS_CACHE, DATA_CACHE, CDN_CACHE];
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((k) => !keepCaches.includes(k))
          .map((k) => {
            console.log('[SW] Removendo cache antigo:', k);
            return caches.delete(k);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// ──────────────────────────────────────────────
// FETCH — estratégia por tipo de rota
// ──────────────────────────────────────────────
function isPrecachedCdnUrl(url) {
  const u = url.toString();
  return PRECACHE_CDN.some((c) => u === c || u.startsWith(c.split('?')[0]));
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;

  // Só interceptamos CDN que realmente precacheamos (não gstatic — fontes são dinâmicas)
  const isCdnWeCache =
    isPrecachedCdnUrl(url) ||
    (url.origin === 'https://cdn.jsdelivr.net' && url.pathname.includes('/npm/'));
  if (isCdnWeCache) {
    event.respondWith(cacheFirstWithNetwork(request, CDN_CACHE));
    return;
  }

  if (url.origin !== self.location.origin) return;

  // API com cache permitido: Network First com fallback em cache
  if (CACHEABLE_API_ROUTES.some((r) => url.pathname === r)) {
    event.respondWith(networkFirstWithCache(request, DATA_CACHE));
    return;
  }

  // Admin Routes precisa SEMPRE vir da rede (sem cache SW), para evitar divergência
  // entre ambiente local e Render quando houver HTML/JSON antigo em cache.
  if (url.pathname === '/api/mobile/admin/routes' || url.pathname === '/mobile/admin/routes') {
    event.respondWith(
      fetch(request).catch(async () => {
        if (request.mode === 'navigate') {
          return tryCacheThenOffline(request, ASSETS_CACHE);
        }
        return new Response('Sem conexão.', { status: 503 });
      })
    );
    return;
  }

  // Assets estáticos do nosso servidor
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirstWithNetwork(request, ASSETS_CACHE));
    return;
  }

  // Logout offline: redireciona para login (evita 503; login pode vir do cache)
  if (url.pathname === '/mobile/logout' && request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(null, { status: 303, headers: { Location: '/mobile/login' } })
      )
    );
    return;
  }

  // Páginas /mobile/*: Network First; erro ou sem cache → cache por URL ou página offline
  if (url.pathname.startsWith('/mobile')) {
    event.respondWith(
      networkFirstWithCache(request, ASSETS_CACHE)
        .then((response) => {
          if (request.mode !== 'navigate') return response;
          if (response && response.status === 503) {
            return new Response(SERVER_UNAVAILABLE_HTML, {
              status: 503,
              headers: { 'Content-Type': 'text/html; charset=utf-8' },
            });
          }
          if (response && !response.ok) {
            return tryCacheThenOffline(request, ASSETS_CACHE);
          }
          return response;
        })
        .catch(() => {
          if (request.mode === 'navigate') {
            return tryCacheThenOffline(request, ASSETS_CACHE);
          }
          return new Response('Sem conexão.', { status: 503 });
        })
    );
    return;
  }
});

/**
 * Para navegação: tenta cache por request e por URL; se não achar, retorna página offline.
 */
async function tryCacheThenOffline(request, cacheName) {
  const cache = await caches.open(cacheName);
  let cached = await cache.match(request);
  if (!cached && request.url) cached = await cache.match(request.url);
  if (cached && cached.ok) {
    console.log('[SW] Servindo do cache (fallback):', request.url);
    return cached;
  }
  return new Response(OFFLINE_HTML, {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}

/**
 * Network First: tenta rede, se falhar usa cache.
 * Só guarda no cache resposta ok (2xx).
 */
async function networkFirstWithCache(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const networkResp = await fetch(request.clone());
    if (networkResp && networkResp.ok) {
      await cache.put(request, networkResp.clone());
    }
    return networkResp;
  } catch (err) {
    let cached = await cache.match(request);
    if (!cached && request.url) cached = await cache.match(request.url);
    if (cached && cached.ok) {
      console.log('[SW] Offline — servindo do cache:', request.url);
      return cached;
    }
    if (request.url.includes('/api/')) {
      return new Response(
        JSON.stringify({
          success: false,
          offline: true,
          error: 'Sem conexão. Dados do cache não disponíveis.',
          routes: [],
          day_cards: [],
          session_open: false,
        }),
        { headers: { 'Content-Type': 'application/json' } }
      );
    }
    return new Response('Sem conexão e sem cache disponível.', { status: 503 });
  }
}

/**
 * Cache First: serve do cache se disponível, senão busca na rede e cacheia.
 * Para CDN usa também match por URL (evita falha por diferença do Request).
 */
async function cacheFirstWithNetwork(request, cacheName) {
  const cache = await caches.open(cacheName);
  let cached = await cache.match(request);
  if (!cached && request.url) {
    cached = await cache.match(request.url);
  }
  if (cached) return cached;
  try {
    const networkResp = await fetch(request.clone());
    if (networkResp && networkResp.ok) {
      await cache.put(request, networkResp.clone());
    }
    return networkResp;
  } catch {
    const isCssOrFont =
      request.url.includes('fonts.googleapis.com') ||
      request.url.includes('css2') ||
      request.url.includes('fonts.gstatic.com') ||
      (request.headers.get('accept') || '').includes('text/css');
    if (isCssOrFont) {
      return new Response('/* offline */', {
        status: 200,
        headers: { 'Content-Type': 'text/css; charset=utf-8' },
      });
    }
    return new Response('Asset não disponível offline.', { status: 503 });
  }
}

// ──────────────────────────────────────────────
// BACKGROUND SYNC — drena fila quando reconecta
// ──────────────────────────────────────────────
self.addEventListener('sync', (event) => {
  if (event.tag === SYNC_TAG) {
    console.log('[SW] Background Sync disparado — drenando fila...');
    event.waitUntil(drainOfflineQueue());
  }
});

/**
 * Drena a fila de ações offline do IndexedDB.
 * Chama POST /api/mobile/delivery/sync-batch com todas as ações pendentes.
 */
async function drainOfflineQueue() {
  try {
    const actions = await readAllQueuedActions();
    if (!actions || actions.length === 0) {
      console.log('[SW] Fila vazia — nada a sincronizar.');
      return;
    }

    console.log(`[SW] Sincronizando ${actions.length} ação(ões)...`);

    const resp = await fetch('/api/mobile/delivery/sync-batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actions }),
    });

    if (!resp.ok) {
      console.error('[SW] Falha no sync-batch — servidor retornou', resp.status);
      return; // Mantém na fila para próxima tentativa
    }

    const result = await resp.json();
    console.log('[SW] sync-batch resultado:', result);

    // Remove ações bem-sucedidas da fila
    const successIds = (result.results || [])
      .filter((r) => r.success || r.already_done)
      .map((r) => r.queue_id)
      .filter(Boolean);

    await removeFromQueue(successIds);

    // Notifica tabs abertas para recarregar dados
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach((client) => {
      client.postMessage({
        type: 'SYNC_COMPLETE',
        synced: successIds.length,
        total: actions.length,
        results: result.results || [],
      });
    });

    console.log(`[SW] Sincronização concluída: ${successIds.length}/${actions.length} ações.`);
  } catch (err) {
    console.error('[SW] Erro ao drenar fila:', err);
  }
}

// ──────────────────────────────────────────────
// IndexedDB helpers — lidos pelo SW
// ──────────────────────────────────────────────

const DB_NAME = 'nl-entregas-offline';
const DB_VERSION = 1;
const STORE_NAME = 'delivery_queue';

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, {
          keyPath: 'queue_id',
          autoIncrement: true,
        });
        store.createIndex('ts', 'ts', { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function readAllQueuedActions() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const req = store.index('ts').getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

async function removeFromQueue(ids) {
  if (!ids || ids.length === 0) return;
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    let done = 0;
    for (const id of ids) {
      const req = store.delete(id);
      req.onsuccess = () => { if (++done === ids.length) resolve(); };
      req.onerror = () => reject(req.error);
    }
    if (ids.length === 0) resolve();
  });
}

// ──────────────────────────────────────────────
// PUSH — preparado para notificações futuras
// ──────────────────────────────────────────────
self.addEventListener('push', (event) => {
  const data = event.data?.json() || {};
  self.registration.showNotification(data.title || 'Souza Pinto', {
    body: data.body || '',
    icon: '/static/icons/pwa-192.png',
    badge: '/static/icons/pwa-192.png',
  });
});
