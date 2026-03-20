/**
 * Service Worker — Souza Pinto PWA Offline
 * Versão: 1.0.0
 *
 * Estratégias:
 * - Cache First → assets estáticos (CSS, JS, fontes, imagens)
 * - Network First com fallback → GET /api/mobile/delivery/my-routes
 * - Background Sync → fila de ações offline (IndexedDB)
 */

const SW_VERSION = 'nl-entregas-v1.0.1';
const ASSETS_CACHE = `${SW_VERSION}-assets`;
const DATA_CACHE = `${SW_VERSION}-data`;
const SYNC_TAG = 'delivery-sync';

// Assets que devem ser cacheados na instalação
const PRECACHE_ASSETS = [
  '/static/css/mobile.css',
  '/static/styles.css',
  '/static/manifest.json',
];

// Rotas que devem ser servidas do cache se offline
const CACHEABLE_API_ROUTES = [
  '/api/mobile/delivery/my-routes',
];

// ──────────────────────────────────────────────
// INSTALL — pré-cacheia assets essenciais
// ──────────────────────────────────────────────
self.addEventListener('install', (event) => {
  console.log('[SW] Instalando versão:', SW_VERSION);
  event.waitUntil(
    caches.open(ASSETS_CACHE).then(async (cache) => {
      // Cacheia assets individualmente para não falhar tudo se um não existir
      for (const url of PRECACHE_ASSETS) {
        try {
          await cache.add(url);
        } catch (e) {
          console.warn('[SW] Não foi possível pré-cachear:', url, e.message);
        }
      }
      console.log('[SW] Assets pré-cacheados.');
    })
  );
  self.skipWaiting();
});

// ──────────────────────────────────────────────
// ACTIVATE — limpa caches antigos
// ──────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  console.log('[SW] Ativando:', SW_VERSION);
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((k) => k !== ASSETS_CACHE && k !== DATA_CACHE)
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
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Ignora requisições não-GET para não interceptar mutations online
  // (mutations offline são tratadas pelo cliente via IndexedDB)
  if (request.method !== 'GET') return;

  // Ignora origens externas (CDN, Google Fonts, etc.)
  if (url.origin !== self.location.origin) return;

  // Estratégia: Network First com fallback para API de rotas
  if (CACHEABLE_API_ROUTES.some((r) => url.pathname === r)) {
    event.respondWith(networkFirstWithCache(request, DATA_CACHE));
    return;
  }

  // Estratégia: Cache First apenas para assets estáticos
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirstWithNetwork(request, ASSETS_CACHE));
    return;
  }

  // Páginas mobile são dinâmicas: preferir rede e usar cache só como fallback offline.
  if (url.pathname.startsWith('/mobile/')) {
    event.respondWith(networkFirstWithCache(request, ASSETS_CACHE));
  }
});

/**
 * Network First: tenta rede, se falhar usa cache.
 * Sempre atualiza o cache com a resposta bem-sucedida.
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
    const cached = await cache.match(request);
    if (cached) {
      console.log('[SW] Offline — servindo do cache:', request.url);
      return cached;
    }
    // Resposta de fallback para API
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
 */
async function cacheFirstWithNetwork(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const networkResp = await fetch(request.clone());
    if (networkResp && networkResp.ok) {
      await cache.put(request, networkResp.clone());
    }
    return networkResp;
  } catch {
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

