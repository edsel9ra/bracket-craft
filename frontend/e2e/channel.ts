/**
 * Interceptor del canal de tiempo real desde el navegador (RF-001, Q3).
 *
 * El escenario necesita provocar la indisponibilidad del canal —sondeo y
 * elevación a conexión persistente— **sin** tocar la API HTTP, la sesión ni la
 * interfaz. Por eso se usan dos puntos de intercepción de Playwright:
 *
 * - `page.route` sobre la ruta del canal: sondeo inicial, `POST` de handshake y
 *   el sondeo largo. Tiene tres modos:
 *   - `pass`: la petición sigue su curso normal.
 *   - `hold`: se deja **en vuelo** (ni respuesta ni aborto), de modo que el
 *     intento no falla y el estado manual de producto es observable. Su cota
 *     natural es el `timeout: 10_000` del cliente; el escenario lo libera
 *     explícitamente mucho antes.
 *   - `abort`: falla de inmediato, que es lo que lleva la vista a error.
 * - `page.routeWebSocket` sobre la misma ruta: la elevación. En `pass` se
 *   conecta al servidor real (`connectToServer`) y se cuenta como una conexión
 *   **establecida**; en `hold`/`abort` **nunca** se acepta el handshake, así
 *   que un intento bloqueado no puede convertirse en transporte.
 *
 * El cierre del transporte vigente se hace sobre la conexión persistente
 * **interceptada** (`WebSocketRoute.close()`): el navegador observa el cierre de
 * su propio WebSocket y Socket.IO lo trata como una caída de transporte. No se
 * simula el estado, no se fuerza el cliente y no se usa `setOffline` (que
 * tumbaría también la API).
 *
 * El interceptor registra peticiones (método, ruta sin consulta, estado e
 * instante), apertura y cierre de WebSocket y navegaciones del frame principal,
 * y los expone como traza propia sin cabeceras para el artefacto (RF-005).
 */

import type { Frame, Page, Request, Route, WebSocket, WebSocketRoute } from '@playwright/test';

import {
  redactPath,
  traceNavigation,
  traceRequest,
  traceWebSocket,
  type TraceEntry,
} from './artifacts.ts';

/** Rutas del canal: sondeo y elevación comparten prefijo. */
export const CHANNEL_PATTERN = /\/socket\.io\//;

/** Modos del bloqueo. `pass` es el canal vivo; el resto lo bloquea. */
export type ChannelMode = 'pass' | 'hold' | 'abort';

export type TimeSource = () => number;

export interface ChannelGateOptions {
  /** Reloj del borde; las funciones que deciden reciben los instantes ya tomados. */
  readonly now?: TimeSource;
  /** Intervalo de sondeo de las esperas acotadas. */
  readonly pollIntervalMs?: number;
}

/** Una petición HTTP observada por el navegador, sin cabeceras ni cuerpos. */
export interface ChannelRequestRecord {
  readonly at: number;
  readonly method: string;
  readonly url: string;
  readonly path: string;
  readonly channel: boolean;
  readonly status: number | null;
  readonly failed: boolean;
}

/** Una navegación del frame principal, con su instante. */
export interface ChannelNavigationRecord {
  readonly at: number;
  readonly url: string;
}

export interface ChannelCounts {
  /** Conexiones persistentes aceptadas por el servidor real. */
  readonly established: number;
  /** Conexiones aceptadas mientras el canal estaba bloqueado (debe ser 0). */
  readonly establishedDuringBlock: number;
  /** Peticiones HTTP al canal (sondeo y elevación), incluidas las bloqueadas. */
  readonly attempts: number;
  /** Peticiones al canal retenidas o abortadas por el bloqueo. */
  readonly blocked: number;
  /** Peticiones retenidas ahora mismo (en vuelo, sin handshake aceptado). */
  readonly held: number;
  /** Handshakes WebSocket rechazados por el bloqueo. */
  readonly rejectedHandshakes: number;
}

/** Se agotó una espera acotada del canal: el escenario decide su veredicto. */
export class ChannelTimeoutError extends Error {
  readonly condition: string;

  constructor(condition: string, detail: string) {
    super(`${condition}: ${detail}`);
    this.name = 'ChannelTimeoutError';
    this.condition = condition;
  }
}

interface MutableRequestRecord {
  at: number;
  method: string;
  url: string;
  path: string;
  channel: boolean;
  status: number | null;
  failed: boolean;
}

interface Waiter {
  readonly after: number;
  resolve: (at: number) => void;
}

export interface ChannelGate {
  install(): Promise<void>;
  setMode(mode: ChannelMode): void;
  mode(): ChannelMode;
  isBlocked(): boolean;
  counts(): ChannelCounts;
  /** Peticiones HTTP observadas, en orden de llegada. */
  requests(): readonly ChannelRequestRecord[];
  /** Peticiones al canal, para la traza y el recuento de intentos. */
  channelRequests(): readonly ChannelRequestRecord[];
  navigations(): readonly ChannelNavigationRecord[];
  /** Cierra la conexión persistente interceptada que sostiene el canal. */
  closeEstablishedTransport(): Promise<void>;
  /** Libera los intentos retenidos: fallan y la vista vuelve a error. */
  releaseHeld(): Promise<void>;
  /** Vuelve a `pass`: libera lo retenido y descarta los handshakes bloqueados. */
  unblock(): Promise<void>;
  /** Espera a que haya `count` conexiones persistentes aceptadas. */
  waitForEstablished(count: number, timeoutMs: number): Promise<number>;
  /** Espera una petición al canal posterior a `after`; devuelve su instante. */
  waitForChannelRequestAfter(after: number, timeoutMs: number): Promise<number>;
  /** Espera una ventana sin actividad del canal a partir de `since`. */
  settle(since: number, windowMs: number, timeoutMs: number): Promise<number>;
  /** Reinicia el recuento de navegaciones del documento (línea base). */
  markDocumentBaseline(): void;
  /** Navegaciones del frame principal posteriores a la línea base. */
  documentNavigations(): readonly ChannelNavigationRecord[];
  /** Traza propia sin cabeceras: peticiones del canal, WebSocket y navegación. */
  trace(): readonly TraceEntry[];
  dispose(): Promise<void>;
}

class BrowserChannelGate implements ChannelGate {
  private readonly page: Page;
  private readonly now: TimeSource;
  private readonly pollIntervalMs: number;

  private currentMode: ChannelMode = 'pass';
  private establishedCount = 0;
  private establishedDuringBlockCount = 0;
  private blockedCount = 0;
  private rejectedHandshakes = 0;
  private lastUsable: WebSocketRoute | null = null;
  private lastChannelActivityAt = Number.NEGATIVE_INFINITY;

  private readonly requestRecords: MutableRequestRecord[] = [];
  private readonly requestIndex = new Map<Request, MutableRequestRecord>();
  private readonly heldRoutes: Route[] = [];
  private readonly blockedHandshakes: WebSocketRoute[] = [];
  private readonly waiters: Waiter[] = [];
  private readonly navigationRecords: ChannelNavigationRecord[] = [];
  private readonly traceEntries: TraceEntry[] = [];
  private readonly unlisteners: Array<() => void> = [];
  private baselineNavigationAt: number | null = null;
  private installed = false;

  constructor(page: Page, options: ChannelGateOptions = {}) {
    this.page = page;
    this.now = options.now ?? Date.now;
    this.pollIntervalMs = options.pollIntervalMs ?? 25;
  }

  async install(): Promise<void> {
    if (this.installed) return;
    this.installed = true;

    await this.page.route(CHANNEL_PATTERN, (route) => this.onChannelHttp(route));
    await this.page.routeWebSocket(CHANNEL_PATTERN, (socket) => this.onChannelHandshake(socket));

    const onRequest = (request: Request): void => this.onRequest(request);
    const onFinished = (request: Request): void => this.onRequestFinished(request);
    const onFailed = (request: Request): void => this.onRequestFailed(request);
    const onNavigation = (frame: Frame): void => {
      if (frame.page() !== this.page) return;
      const at = this.now();
      const record = { at, url: frame.url() };
      this.navigationRecords.push(record);
      this.traceEntries.push(traceNavigation({ at, url: record.url }));
    };
    const onWebSocket = (socket: WebSocket): void => {
      const url = socket.url();
      if (!CHANNEL_PATTERN.test(url)) return;
      socket.on('close', () => {
        this.traceEntries.push(traceWebSocket({ at: this.now(), action: 'close', url }));
      });
    };

    this.page.on('request', onRequest);
    this.page.on('requestfinished', onFinished);
    this.page.on('requestfailed', onFailed);
    this.page.on('framenavigated', onNavigation);
    this.page.on('websocket', onWebSocket);

    this.unlisteners.push(
      () => this.page.off('request', onRequest),
      () => this.page.off('requestfinished', onFinished),
      () => this.page.off('requestfailed', onFailed),
      () => this.page.off('framenavigated', onNavigation),
      () => this.page.off('websocket', onWebSocket),
    );
  }

  setMode(mode: ChannelMode): void {
    this.currentMode = mode;
  }

  mode(): ChannelMode {
    return this.currentMode;
  }

  isBlocked(): boolean {
    return this.currentMode !== 'pass';
  }

  counts(): ChannelCounts {
    return {
      established: this.establishedCount,
      establishedDuringBlock: this.establishedDuringBlockCount,
      attempts: this.requestRecords.filter((record) => record.channel).length,
      blocked: this.blockedCount,
      held: this.heldRoutes.length,
      rejectedHandshakes: this.rejectedHandshakes,
    };
  }

  requests(): readonly ChannelRequestRecord[] {
    return this.requestRecords;
  }

  channelRequests(): readonly ChannelRequestRecord[] {
    return this.requestRecords.filter((record) => record.channel);
  }

  navigations(): readonly ChannelNavigationRecord[] {
    return this.navigationRecords;
  }

  documentNavigations(): readonly ChannelNavigationRecord[] {
    const baseline = this.baselineNavigationAt;
    if (baseline === null) return this.navigationRecords;
    return this.navigationRecords.filter((record) => record.at > baseline);
  }

  markDocumentBaseline(): void {
    this.baselineNavigationAt = this.now();
  }

  /**
   * Caída del transporte ya establecido. `close()` sobre la ruta del navegador
   * cierra el WebSocket que la página está usando; el motor lo ve como una
   * caída de transporte y su reconexión automática queda bloqueada. No hay
   * ninguna petición HTTP, ni cambio de sesión, ni estado simulado.
   */
  async closeEstablishedTransport(): Promise<void> {
    const socket = this.lastUsable;
    if (!socket) return;
    this.lastUsable = null;
    try {
      await socket.close({ code: 1000, reason: 'e2e-transport-drop' });
    } catch {
      // El socket ya podía estar cerrado (p. ej. el motor lo sustituyó).
    }
  }

  /** Libera lo retenido: cada intento falla y la vista vuelve a `error`. */
  async releaseHeld(): Promise<void> {
    const held = this.heldRoutes.splice(0, this.heldRoutes.length);
    await Promise.allSettled(held.map((route) => route.abort('failed')));
  }

  /** Desbloqueo: canal vivo, intentos retenidos liberados y handshakes descartados. */
  async unblock(): Promise<void> {
    this.currentMode = 'pass';
    await this.releaseHeld();
    const handshakes = this.blockedHandshakes.splice(0, this.blockedHandshakes.length);
    await Promise.allSettled(handshakes.map((socket) => socket.close()));
  }

  async waitForEstablished(count: number, timeoutMs: number): Promise<number> {
    const deadline = this.now() + timeoutMs;
    for (;;) {
      if (this.establishedCount >= count) return this.establishedCount;
      if (this.now() > deadline) {
        throw new ChannelTimeoutError(
          'established-connection',
          `se esperaban ${count} conexiones persistentes y se observaron ${this.establishedCount} en ${timeoutMs} ms`,
        );
      }
      await this.pause();
    }
  }

  waitForChannelRequestAfter(after: number, timeoutMs: number): Promise<number> {
    const existing = this.requestRecords.find(
      (record) => record.channel && record.at >= after,
    );
    if (existing) return Promise.resolve(existing.at);

    return new Promise<number>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      const waiter: Waiter = {
        after,
        resolve: (at: number) => {
          if (timer !== null) clearTimeout(timer);
          resolve(at);
        },
      };
      this.waiters.push(waiter);
      timer = setTimeout(() => {
        const index = this.waiters.indexOf(waiter);
        if (index >= 0) this.waiters.splice(index, 1);
        reject(
          new ChannelTimeoutError(
            'channel-attempt',
            `ninguna petición al canal posterior a ${after} en ${timeoutMs} ms`,
          ),
        );
      }, timeoutMs);
    });
  }

  async settle(since: number, windowMs: number, timeoutMs: number): Promise<number> {
    const deadline = this.now() + windowMs + timeoutMs;
    for (;;) {
      const now = this.now();
      const quietSince = Math.max(since, this.lastChannelActivityAt);
      if (now - quietSince >= windowMs) return now;
      if (now > deadline) {
        throw new ChannelTimeoutError(
          'settlement-window',
          `el canal siguió iniciando secuencias de conexión durante más de ${windowMs} ms tras ${since}`,
        );
      }
      await this.pause();
    }
  }

  trace(): readonly TraceEntry[] {
    const requests = this.requestRecords.map((record) =>
      traceRequest({
        at: record.at,
        method: record.method,
        url: record.url,
        status: record.status,
      }),
    );
    return [...requests, ...this.traceEntries].sort((left, right) => left.at - right.at);
  }

  async dispose(): Promise<void> {
    for (const unlisten of this.unlisteners.splice(0, this.unlisteners.length)) unlisten();
    await this.releaseHeld().catch(() => undefined);
    for (const waiter of this.waiters.splice(0, this.waiters.length)) {
      waiter.resolve(Number.NaN);
    }
    if (this.installed) {
      this.installed = false;
      // Playwright 1.64 no ofrece `unrouteWebSocket`: la intercepción de la
      // elevación sigue instalada, en `pass`, hasta que se cierre la página.
      // Es inerte para el veredicto (solo reenvía al servidor real).
      await this.page.unroute(CHANNEL_PATTERN).catch(() => undefined);
    }
  }

  private pause(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, this.pollIntervalMs));
  }

  private noteChannelActivity(at: number): void {
    if (at > this.lastChannelActivityAt) this.lastChannelActivityAt = at;
    const pending = this.waiters.filter((waiter) => waiter.after <= at);
    for (const waiter of pending) {
      const index = this.waiters.indexOf(waiter);
      if (index >= 0) this.waiters.splice(index, 1);
      waiter.resolve(at);
    }
  }

  private onRequest(request: Request): void {
    const url = request.url();
    const at = this.now();
    const record: MutableRequestRecord = {
      at,
      method: request.method().toUpperCase(),
      url,
      path: redactPath(url),
      channel: CHANNEL_PATTERN.test(url),
      status: null,
      failed: false,
    };
    this.requestRecords.push(record);
    this.requestIndex.set(request, record);
    if (record.channel) this.noteChannelActivity(at);
  }

  private onRequestFinished(request: Request): void {
    const record = this.requestIndex.get(request);
    if (!record) return;
    void request
      .response()
      .then((response) => {
        record.status = response?.status() ?? null;
      })
      .catch(() => {
        record.status = null;
      })
      .finally(() => this.requestIndex.delete(request));
  }

  private onRequestFailed(request: Request): void {
    const record = this.requestIndex.get(request);
    if (!record) return;
    record.failed = true;
    this.requestIndex.delete(request);
  }

  private async onChannelHttp(route: Route): Promise<void> {
    const mode = this.currentMode;
    if (mode === 'pass') {
      await route.continue().catch(() => undefined);
      return;
    }

    this.blockedCount += 1;
    if (mode === 'hold') {
      // En vuelo: ni respuesta ni aborto. El estado manual es observable y el
      // intento no puede fallar mientras dure la retención.
      this.heldRoutes.push(route);
      return;
    }

    await route.abort('failed').catch(() => undefined);
  }

  private onChannelHandshake(socket: WebSocketRoute): void {
    const at = this.now();
    const url = socket.url();
    this.traceEntries.push(traceWebSocket({ at, action: 'open', url }));
    this.noteChannelActivity(at);

    if (this.currentMode === 'pass') {
      this.establishedCount += 1;
      this.lastUsable = socket;
      try {
        socket.connectToServer();
      } catch {
        this.lastUsable = null;
      }
      return;
    }

    // Sin `connectToServer()` no hay handshake aceptado: el intento se queda
    // sin transporte mientras dure el bloqueo.
    this.rejectedHandshakes += 1;
    this.blockedHandshakes.push(socket);
  }
}

export function createChannelGate(page: Page, options: ChannelGateOptions = {}): ChannelGate {
  return new BrowserChannelGate(page, options);
}
