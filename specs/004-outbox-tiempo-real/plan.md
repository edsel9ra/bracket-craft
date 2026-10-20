# Plan 004 — Outbox y tiempo real: stream acotado, `event_id` y `RESYNC`

Estado: Implementada y validada (APROBADA por @reviewer, 2026-10-20); pendiente de CI en main y revisión humana (T008)

Spec: `specs/004-outbox-tiempo-real/spec.md` (aprobada 2026-10-19)

## 1. Resumen técnico

La implementación se divide en tres cortes de backend y tres de frontend, más documentación y verificación final:

- **Worker/stream:** `XADD` con `MAXLEN` aproximado fijo de 10 000 entradas; el sobre añade `event_id` y conserva `id` durante la transición.
- **Relay:** arranca en el último id del stream, no reemite histórico, avanza la posición por entrada y distingue **reinicio del relay** de **pérdida de conexión con Redis con el proceso vivo**.
- **Resync:** detecta recorte y reinicio de datos de Redis (`run_id`), emite `RESYNC` a las salas conectadas y emite `JOIN` dirigido al socket que entra en una sala.
- **Frontend:** deduplica por `event_id`, separa `RESYNC` de los eventos de dominio, detecta reconexiones, aplica una política de recarga con coalescencia y reinicia la paginación pública ante un resync de hueco.
- **Sin cambios de esquema, REST, Compose ni configuración.** No hay migraciones; el revert es el commit anterior.

No se añaden dependencias. Todo el comportamiento nuevo se apoya en `redis.asyncio`, `socket.io`, `vue` y `node:test` ya presentes.

## 2. Estado de partida y supuestos

- `outbox_events.id` es UUID y ya viaja como `id` en el sobre del stream (`backend/app/workers/outbox.py`); el relay lo descarta hoy.
- El relay actual arranca en `"0-0"`, lee por lotes de 100 con bloqueo de 1 s y emite a `organization:{id}` y, para `PUBLIC_REALTIME_EVENTS`, a `tournament:{id}` (`backend/app/main.py`).
- Cada socket entra en **una sola** sala (`organization:*` o `tournament:*`); no existe doble emisión a salas para un mismo socket.
- `connected_socket_sessions` ya mantiene el alcance por `sid`; se usa para enumerar salas con clientes sin depender de la API interna del manager de Socket.IO.
- `useRealtime` ya centraliza el socket, el estado de conexión y el despacho por `socket.onAny`; las páginas consumen `MATCH_CLOSED`, `MATCH_UPDATED` y `STANDINGS_UPDATED`.
- La página pública ya refresca cada 30 s mientras no está conectada y pagina con `offset` y `PAGE_SIZE = 50`; el Workspace y la operación de partido no tienen polling.
- Versiones de referencia: Python 3.14, Node 24 y pnpm 12.12.1. Las pruebas unitarias nuevas no requieren Redis ni PostgreSQL reales.
- No se modifica la tabla `outbox_events`, ni `infra/postgres/`, ni `.env.example`, ni Compose.
- Los mensajes de un worker anterior (solo `id`), un relay anterior (ignora `RESYNC` y `event_id`) y un frontend anterior (ignora eventos desconocidos) deben seguir funcionando durante un despliegue progresivo.

## 3. Archivos y responsabilidades

| Archivo | Responsabilidad | RF |
|---|---|---|
| `backend/app/core/outbox.py` | `OUTBOX_STREAM_MAXLEN = 10_000` junto a `OUTBOX_STREAM`. Constante, sin configuración por entorno. | RF-001 |
| `backend/app/workers/outbox.py` | Construir el sobre con `event_id` e `id`; publicar con `maxlen` aproximado. Conserva el manejo de éxito/fallo actual. | RF-001, RF-004 |
| `backend/app/main.py` | Relay por estado: arranque en cola, reanudación, comprobación de recorte y `run_id`, avance por entrada, emit con `event_id`, emisión de `RESYNC` y `JOIN`. | RF-002, RF-004, RF-005, RF-010 |
| `backend/tests/test_outbox_worker.py` (nuevo) | Pruebas del sobre y de la llamada `XADD` con Redis falso. | RF-001, RF-004 |
| `backend/tests/test_outbox_relay.py` (nuevo) | Pruebas del arranque, reanudación, avance por entrada, parseo y emit. | RF-002, RF-004, RF-005 |
| `backend/tests/test_outbox_resync.py` (nuevo) | Pruebas de `RESYNC` por motivo, `JOIN`, salas, sin clientes, fallo de emisión y ausencia de bucles. | RF-010, RF-003 |
| `backend/tests/test_hardening.py` | Se actualiza la prueba existente del relay al nuevo contrato, sin perder entradas malformadas. | RF-002, RF-005 |
| `frontend/app/utils/realtimeDedup.ts` (nuevo) | Ventana FIFO de 200 `event_id`, lectura del identificador de nivel superior y `reset()`. | RF-006 |
| `frontend/app/utils/realtimeDispatch.ts` (nuevo) | Despacho único con deduplicación, separación de `RESYNC` y parseo del payload de control. | RF-005, RF-006, RF-010 |
| `frontend/app/utils/realtimeConnection.ts` (nuevo) | Clasificación de conexión inicial/reconexión a partir del estado y de la conexión previa. | RF-003 |
| `frontend/app/utils/realtimeReload.ts` (nuevo) | Decisión de recarga por consumidor y coordinador «una en curso + una trailing». | RF-003 |
| `frontend/app/composables/useRealtime.ts` | Usa el despachador, añade `onReconnect`/`onResync`, conserva la ventana en auto-reconnect y la vacía en socket/scope nuevo, `disconnect()` y destrucción. | RF-003, RF-006, RF-010 |
| `frontend/app/pages/workspace/index.vue` | Recarga con coordinador ante reconexión y `RESYNC`; sin recarga de reconciliación en la conexión inicial. | RF-003 |
| `frontend/app/pages/workspace/matches/[id].vue` | Igual que el Workspace, con su `refreshOperation` y el guard existente reemplazado por coalescencia. | RF-003 |
| `frontend/app/pages/tournaments/[id].vue` | Polling de 30 s, `RESYNC` `JOIN` de inicialización, resync de hueco con recarga y reset de paginación; ignora `JOIN` posteriores. | RF-003, RF-010 |
| `frontend/tests/realtime-dedup.test.ts` (nuevo) | Casos de la ventana y del despacho. | RF-006 |
| `frontend/tests/realtime-reload.test.ts` (nuevo) | Detección de reconexión, política por consumidor, coalescencia, fallo y paginación. | RF-003, RF-010 |
| `README.md`, `AGENTS.md`, `MEMORY.md` | Semántica de transporte, garantías, `event_id`, `RESYNC`, tope fijo y cierre. | RF-009 |

No se tocan `frontend/app/composables/useApi.ts`, routers, migraciones, `docker-compose*.yml`, `.env.example`, `.github/workflows/ci.yml` ni `frontend/package.json`.

## 4. Diseño backend

### 4.1 Worker y sobre del stream (RF-001, RF-004)

- `OUTBOX_STREAM_MAXLEN = 10_000` en `backend/app/core/outbox.py`; no se añade un campo a `Settings` ni una variable de entorno.
- `build_stream_message(event) -> str` puro: JSON con `event_id`, `id`, `organization_id`, `event_type` y `payload`. `event_id` e `id` toman el mismo valor (`str(event["id"])`); el payload no se modifica. Se mantiene `default=str`.
- `publish_stream_event(redis, event) -> None`: `await redis.xadd(OUTBOX_STREAM, {"event": message}, maxlen=OUTBOX_STREAM_MAXLEN, approximate=True)`.
- `process_once()` usa `publish_stream_event`; el `fail_outbox_event` y el `complete_outbox_event` actuales no cambian. Un `XADD` exitoso y un `complete` fallido sigue produciendo reentrega con el mismo `event_id`.
- Alternativa descartada: `maxlen` exacto. Recorre nodos internos en cada escritura y no aporta precisión útil; la spec acepta el margen aproximado.
- Alternativa descartada: retirar `id` del sobre en este cambio. Rompe a un relay anterior que aún no conoce `event_id`; se conserva hasta otra spec (RF-004).

### 4.2 Relay por estado (RF-002, RF-004, RF-005)

Se sustituye el bucle monolítico por funciones pequeñas y un estado explícito:

```text
RelayState:
    position: str | None       # último id procesado
    run_id: str | None         # INFO server -> run_id
    started: bool              # False solo en un proceso nuevo
```

Funciones puras:

- `parse_envelope(fields) -> ParsedEvent | None`: valida `event_type`, `organization_id`, `payload` y el identificador. Precedencia `event_id` válido → `id` válido → sin identificador. Si ambos existen y difieren, usa `event_id` y registra la anomalía sin payload.
- `build_realtime_payload(payload, event_id) -> dict`: copia el payload, elimina cualquier `event_id` de dominio y añade el del servidor si existe.
- `stream_id_gt(left, right) -> bool`: comparación por `(ms, seq)`; evita comparar ids como cadenas.
- `parse_run_id(info) -> str | None`: tolera `INFO` deshabilitado o sin `run_id`.

Funciones de E/S acotadas:

- `resolve_tail(redis) -> str | None`: último id (`XREVRANGE ... COUNT 1`).
- `resolve_first(redis) -> str | None`: primera entrada retenida.
- `emit_domain_event(event)`: dos `sio.emit` (organización y torneo público) con el mismo payload y `event_id`, conservando la condición `PUBLIC_REALTIME_EVENTS` y `tournament_id`.
- `relay_cycle(redis, state, emit, emit_resync=None) -> RelayState`: una iteración completa, testeable. T002 lo implementa sin detección de huecos (`emit_resync=None`); T003 conecta la detección y la emisión. En el primer ciclo de un proceso:
  - registra `run_id` y resuelve `position` al último id; no emite nada anterior;
  - si el stream está vacío, deja la posición lista para leer la primera entrada nueva;
  - no emite `RESYNC` de hueco por el mero arranque.
- En ciclos posteriores y tras reconectar:
  - comprueba `run_id` (si cambió, `REDIS_RESET`), primera entrada (si `position < first`, `STREAM_TRIMMED`) y último id (si `position > last` o el stream está vacío con posición previa, `REDIS_RESET`);
  - en caso de hueco, delega la emisión en `emit_resync` y salta al final;
  - lee con `XREAD` (100, bloqueo 1 s) y procesa **entrada por entrada**: emite, avanza `position` y continúa. Si falla antes de avanzar, la relectura duplica como máximo esa entrada.
- `relay_loop(redis_factory=Redis.from_url, stop: asyncio.Event | None = None)`: crea/recrea el cliente, conserva `state` entre reconexiones y atiende `CancelledError`. El parámetro `stop` y la factoría inyectable permiten probar el reintento sin un Redis real y sin bucle infinito.
- El arranque no consulta PostgreSQL ni bloquea el `lifespan`; la tarea sigue creándose en `lifespan` como hoy.

La comprobación de recorte se hace al inicio de cada ciclo, antes de `XREAD`; el coste es una consulta acotada por ciclo y por réplica. `INFO server` se consulta al conectar y al reconectar; si no está disponible, se usan solo primera/última entrada y se registra la limitación.

### 4.3 Resync (RF-010 y parte backend de RF-003)

Contrato emitido por Socket.IO:

```text
evento: "RESYNC"
payload: { "event_id": "resync:<uuid>", "reason": "JOIN" | "RELAY_START" | "STREAM_TRIMMED" | "REDIS_RESET" }
```

- `new_resync_event_id() -> str`: `resync:` + UUID4; opaco y único por emisión. No se escribe en el stream.
- `resync_rooms(sessions) -> list[str]`: deriva `organization:{id}` y `tournament:{id}` de `connected_socket_sessions`; deduplica y omite salas sin sockets.
- `emit_gap_resync(reason, sessions)`: emite a cada sala de `resync_rooms`; si la lista está vacía no emite y no guarda nada. Un fallo de `sio.emit` se registra y no interrumpe el relay.
- `emit_join_resync(sid)`: se llama en `connect` **después** de `enter_room` y `save_session`; emite solo a ese `sid`, en organización y en torneo público.
- `RELAY_START`: al iniciar la tarea del relay, si `connected_socket_sessions` no está vacío, emite a las salas conectadas y resuelve la posición al final. En un arranque de proceso normal la lista está vacía y no hay emisión.
- `JOIN` cubre el hueco entre la carga HTTP inicial y la entrada en la sala; no se emite `RESYNC` de hueco por arranque.
- La emisión no altera `state.position` ni provoca otra detección; el cliente no responde con eventos y una recarga no emite `RESYNC`.
- El relay no consulta la base de datos para decidir la organización afectada: un stream recortado ya no permite saberlo. La emisión a las salas conectadas es segura porque el payload no contiene datos y solo provoca una recarga coalescida.

## 5. Diseño frontend

### 5.1 Deduplicación y despacho (RF-005, RF-006, RF-010)

`frontend/app/utils/realtimeDedup.ts`:

- `readDeliveryId(payload) -> string | null`: solo un `event_id` de nivel superior, cadena no vacía; `null` en cualquier otro caso.
- `createEventDeduplicator(limit = 200)`: `accept(eventName, payload) -> boolean` y `reset()`. La clave es `event_id` por igualdad; usa un `Set` con orden de inserción y elimina el más antiguo al superar 200. Un `event_id` ausente, `null`, vacío o no cadena se acepta siempre.
- No depende de Nuxt ni del socket; se prueba con `node --test`.

`frontend/app/utils/realtimeDispatch.ts`:

- Constantes `RESYNC_EVENT = 'RESYNC'`, `type ResyncReason`, `parseResyncPayload(payload)`.
- `createRealtimeDispatcher({ dedupe, handlers })` devuelve `dispatch(event, payload)`:
  - aplica `dedupe.accept` antes de cualquier handler;
  - si `event === RESYNC`, valida el payload y llama solo a `onResync`; no invoca handlers de dominio;
  - si es un evento de dominio, llama a `onEvent` y al handler específico, una vez;
  - un `RESYNC` inválido se descarta sin handlers y sin cambio de estado.
- `useRealtime` usa este despachador en `socket.onAny` y añade `onResync` y `onReconnect` a `RealtimeHandlers`. El handler genérico deja de recibir `RESYNC` para mantener la separación.

### 5.2 Conexión, recarga y coalescencia (RF-003)

`frontend/app/utils/realtimeConnection.ts`:

- `isReconnection({ hasConnectedOnce, previousStatus, nextStatus }) -> boolean`: verdadero si `nextStatus === 'connected'`, hubo una conexión previa y el estado anterior fue `reconnecting` o `error`. La conexión inicial desde `connecting` no lo es.
- `useRealtime` conserva `hasConnectedOnce` y `sawConnectionLoss`; el auto-reconnect de Socket.IO no reinicia la ventana de deduplicación ni `hasConnectedOnce`. `disconnect()` y un socket/scope nuevo reinician ambos.

`frontend/app/utils/realtimeReload.ts`:

- `decideReload({ consumer, trigger, initialized, initializedWithJoin }) -> { action, resetPagination }`:
  - `consumer: 'public' | 'workspace'`;
  - `trigger`: `'reconnect'`, `'resync-join'`, `'resync-gap'` o `'event'`;
  - `resync-join` durante la inicialización → completa la carga inicial; `resync-join` posterior → Workspace recarga, público ignora;
  - `resync-gap` → recarga en ambos y `resetPagination: true`;
  - `reconnect` → recarga en Workspace, ninguna en público.
- `createReloadCoordinator(run)`: mantiene `inFlight` y una única `trailing`; `request({ resetPagination })` no lanza peticiones concurrentes, acumula `resetPagination` y ejecuta una sola trailing al terminar. Un fallo conserva el estado y no programa reintentos.
- Ventana de inicialización: el consumidor la cierra al procesar el primer `RESYNC` `JOIN` o al vencer una gracia corta tras `connected` si el `JOIN` no llega (constante local `INITIALIZATION_GRACE_MS = 1500`, sin configuración). La carga HTTP no se bloquea esperando el socket.

`useRealtime` emite `onReconnect` cuando `isReconnection` es verdadero y `onResync` con el payload validado. El Workspace y la operación de partido sustituyen el booleano `realtimeRefreshPending` por el coordinador: una recarga por reconexión, una trailing si llega otra solicitud y sin recarga de reconciliación en la conexión inicial.

### 5.3 Página pública, resync y paginación (RF-003, RF-010)

- La página pública conserva el polling de 30 s con `PUBLIC_REFRESH_INTERVAL_MS`; no usa `onReconnect`.
- `onResync`:
  - `JOIN` durante la inicialización: completa la carga inicial (coalescida);
  - `JOIN` posterior: se ignora;
  - `STREAM_TRIMMED`, `REDIS_RESET`, `RELAY_START`: recarga con `resetPagination: true`.
- `refreshPublicData` pasa a usar el coordinador y, con reset, vuelve al `offset=0` de `useAsyncData`, descarta las páginas adicionales y reinicia `standingsHasMore`/`matchesHasMore`. Una carga de página adicional en curso se descarta y deja la trailing como única pendiente.
- Si el socket no conecta o el `JOIN` no llega, la inicialización se cierra con la carga HTTP; la página no se bloquea.
- Alternativa descartada: preservar las páginas cargadas tras un resync. Exigiría recalcular offsets y mezclar páginas con un conjunto que cambió; el reset es más simple y consistente con la spec.

## 6. Estrategia de pruebas

### 6.1 Backend: unitarias con dobles de Redis (sin Redis ni PostgreSQL reales)

Se añaden fakes locales por archivo (no se crea infraestructura de test nueva):

- `FakeRedis`: registra `xadd` (nombre, campos, `maxlen`, `approximate`), sirve `xread`/`xrange`/`xrevrange`/`info` con guiones y puede fallar una vez para probar el reintento.
- `FakeSio`: registra `emit(event, payload, room=..., to=...)`; puede lanzar para probar el fallo de emisión.
- `FakeSessions`: diccionario de `sid -> metadata` para derivar salas.

Casos mínimos (mapeados a RF y tareas):

| Caso | RF | Tarea |
|---|---|---|
| `XADD` con `maxlen=10000` y `approximate=True`; sobre con `event_id == id` y payload intacto. | RF-001, RF-004 | T001 |
| Sobre legado solo con `id`; `event_id` inválido con `id` válido; ambos distintos; sin identificador; malformado. | RF-004 | T001/T002 |
| Emit con `event_id` en organización y torneo; `event_id` de dominio eliminado. | RF-005 | T002 |
| Reinicio del relay con stream no vacío no emite entradas previas; stream vacío entrega la primera. | RF-002 | T002 |
| Redis no disponible al arrancar: reintenta, resuelve el final en la primera conexión exitosa y no reemite. | RF-002 | T002 |
| Pérdida de conexión con Redis con el proceso vivo: reanuda y reenvía lo retenido. | RF-002 | T002 |
| Avance por entrada: fallo después de emitir y antes de avanzar repite como máximo una entrada. | RF-002 | T002 |
| Recorte activo: `STREAM_TRIMMED`, salto al final, sin backlog. | RF-002, RF-010 | T003 |
| `run_id` distinto, posición mayor que el último id o stream vacío con posición: `REDIS_RESET`. | RF-002, RF-010 | T003 |
| `RELAY_START` con salas y sin salas; `JOIN` dirigido al `sid`; resync de hueco a salas conectadas. | RF-010 | T003 |
| Payload de `RESYNC` mínimo, `event_id` con prefijo y único; fallo de `sio.emit` no interrumpe. | RF-010 | T003 |
| Entrada malformada se omite y las siguientes se procesan. | RF-002 | T002/T003 |

`process_once` con base de datos no se prueba aquí: no hay cambio de esquema y la suite de BD es opt-in; la lógica nueva de mensaje y publicación se extrae y se prueba sin sesión. Se documenta como no cubierto.

### 6.2 Frontend: utilidades puras con `node --test --experimental-strip-types`

Los tests viven en `frontend/tests/*.test.ts` e importan desde `../app/utils/...`, como los actuales. No se añaden dependencias ni se prueba el DOM.

| Caso | RF | Tarea |
|---|---|---|
| Dedupe: primera aceptada; duplicado rechazado; ids distintos; sin id/`null`/vacío/no cadena; desalojo tras 200; reset por socket/scope (incluido A→B del mismo tipo), `disconnect()` y destrucción; reentrega tras reset; auto-reconnect no resetea. | RF-006 | T004 |
| Despacho: duplicado no invoca handlers; `RESYNC` válido va a `onResync` y no a handlers de dominio; `RESYNC` repetido no recarga dos veces; `RESYNC` inválido se descarta. | RF-006, RF-010 | T004 |
| Reconexión: conexión inicial no; éxito tras `error`/`reconnecting` sí; `hasConnectedOnce` falso no. | RF-003 | T005 |
| Política: una recarga por reconexión en Workspace; ninguna de reconciliación en la inicial; público no recarga por reconexión; `JOIN` post-inicialización recarga Workspace y no público; huecos recargan ambos y resetean paginación. | RF-003, RF-010 | T005/T006 |
| Coalescencia: una en curso + una trailing; varias solicitudes dejan una; reset acumulativo; `RESYNC` o reconexión durante una recarga no lanzan peticiones concurrentes; fallo no reintenta. | RF-003 | T005 |
| Paginación: resync de hueco vuelve a la primera página; `JOIN` posterior no la reinicia en público. | RF-003 | T006 |

### 6.3 Lo que no se cubre y por qué

- **Redis real y Socket.IO real:** CI no tiene servicio de Redis y no se añade; la interacción es fina y se prueba con fakes que registran los argumentos exactos.
- **Contra el DOM, hidratación de Nuxt y temporizadores reales:** se extrae la decisión a utilidades puras; la integración se verifica con `typecheck`/`build` y una prueba manual de humo.
- **Base de datos en `process_once`:** la suite de BD es opt-in y no hay cambio de esquema; la lógica nueva se prueba sin sesión.
- **Comportamiento exacto de reconexión del navegador:** depende del transporte; se prueba la clasificación de estados, no los tiempos de Socket.IO.
- **Carga/estrés del relay:** el tope de 10 000 y el procesamiento por lotes son cotas de diseño; no se añade una prueba de carga.

### 6.4 Comandos y CI

Cada tarea ejecuta los comandos de su lado y deja los cuatro jobs en verde:

```sh
cd backend && pytest -q
cd backend && python -m compileall -q app
cd frontend && pnpm test
cd frontend && pnpm run typecheck
cd frontend && pnpm run build
```

No se modifica `ci.yml`; los jobs `infrastructure` y `security` no cambian de comportamiento.

## 7. Orden de implementación y cortes verdes

| Tarea | Corte | Contenido | Depende de |
|---|---|---|---|
| T001 | Backend | Constante, sobre con `event_id`/`id` y `XADD` acotado; pruebas del worker. | — |
| T002 | Backend | Relay por estado, arranque en cola, reanudación, avance por entrada, parseo y emit con `event_id`. | T001 |
| T003 | Backend | Detección de recorte/`run_id`, `RESYNC` de hueco, `JOIN` y `RELAY_START`. | T002 |
| T004 | Frontend | Deduplicación, despacho y `onResync` en `useRealtime`. | T003 (contrato) |
| T005 | Frontend | Reconexión, política de recarga, coalescencia y Workspace/operación. | T004 |
| T006 | Frontend | Página pública, resync de hueco y reset de paginación. | T005 |
| T007 | Docs | README, AGENTS y MEMORY. | T003, T006 |
| T008 | Cierre | Verificación integral y checklist de merge. | T007 |

Cada fila es un commit o un PR pequeño; T001-T003 se mergean antes que T004-T006 para que el backend emita `RESYNC` cuando el frontend lo consuma. Un backend nuevo con frontend anterior es compatible (ignora `RESYNC` y el campo aditivo); un frontend nuevo con backend anterior se apoya en la gracia de inicialización y en la ausencia de `event_id` (dedupe desactivada, entrega normal).

## 8. Verificación de la constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant en la base de datos | No | No se tocan tablas, RLS ni datos. `RESYNC` no lleva identificadores de organización ni de torneo. |
| §2.2 La aplicación no se salta RLS | No | No se cambia el rol ni se añaden consultas; el relay no consulta PostgreSQL. |
| §2.3 Lo publicado es inmutable | No | No se tocan versiones, resultados ni cierres. |
| §2.4 Historial de esquema append-only | No | No hay migraciones ni cambios en `infra/postgres/`. |
| §2.5 Lo público es una proyección mínima | Sí | No se amplían proyecciones ni payloads de dominio; `RESYNC` no contiene datos de negocio ni PII. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | No se añaden secretos ni variables; no se toca `.env.example` ni Compose. |
| §2.7 Administración global separada y auditada | No | No se toca `/admin` ni `platform_audit_logs`. |
| §2.8 Nada se da por terminado sin verificación | Sí | Pruebas unitarias, comandos locales y cuatro jobs de CI; lo no ejecutado se declara. |
| §2.9 El código de desarrollo no llega a producción | No | No se tocan seeds ni datos demo. |
| §3.1 Base de datos y multi-tenancy | No | Sin migraciones, tablas, políticas ni `set_rls_context()`. |
| §3.2 Backend | Sí | El worker y el relay son asíncronos; no se añade router ni se mueven efectos de dominio fuera del outbox. |
| §3.3 Frontend | Sí | Las recargas usan `useApi` o los stores existentes; no hay endpoints nuevos ni acceso directo a la API. |
| §3.4 Seguridad y configuración | Sí | Sin secretos, sin variables nuevas y sin defaults de desarrollo nuevos. |
| §3.5 Infraestructura y CI | Sí | Python 3.14, Node 24 y pnpm 12.12.1 sin cambios; `ci.yml` y Compose intactos. |
| §4 «Para todos los cambios» | Sí | CI en verde, sin secretos, documentación actualizada y pruebas del comportamiento nuevo. |
| §4 «Para cambios de base de datos» | No | No hay cambios de base de datos. |
| §4 «Para cambios de API o backend» | Sí | `pytest -q` y `compileall`; no hay endpoints públicos nuevos ni campos sensibles; no aplica `set_rls_context()` porque no hay consultas tenant. |
| §4 «Para cambios de frontend» | Sí | `pnpm test`, `pnpm run typecheck` y `pnpm run build`; las llamadas pasan por `useApi`. |
| §4 «Para cambios de infraestructura o despliegue» | No | No se modifica Compose ni el despliegue; `docker compose config -q` sigue pasando sin cambios. |
| §4 «Para cambios de dependencias» | No | No se añaden ni actualizan dependencias. |
| §5.1 Excepciones | No | No se requiere ninguna excepción. |
| §6 Definición de cumplimiento | Sí | Jobs en verde y revisión humana distinta del autor. |

## 9. Riesgos de implementación y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El bucle del relay no es testeable o se cuelga en pruebas | Se extrae `relay_cycle`, se inyectan `redis_factory` y `stop`, y las pruebas ejecutan ciclos acotados con fakes. |
| Comparar ids de stream como cadenas produce falsos huecos | `stream_id_gt` compara `(ms, seq)` y tiene pruebas de borde (`9-9` < `10-0`). |
| `INFO server` no está disponible en Redis gestionado | Se registra la limitación y se usan solo primera/última entrada; no se falla el relay. |
| Un resync broadcast genera tormenta de recargas | Una recarga en curso + una trailing por consumidor; sin reintentos ni cascada. |
| El frontend nuevo se despliega antes que el backend y no llega `JOIN` | Gracia corta de inicialización que cierra con la carga HTTP; la página no se bloquea. |
| El nuevo contrato rompe `test_hardening.py` | T002 actualiza la prueba en el mismo commit, conservando el caso de entrada malformada. |
| El reset de paginación pública pierde páginas cargadas | Comportamiento documentado y probado; es la opción más simple y evita mezclar páginas. |
| La ventana de deduplicación desaloja un `event_id` y se repite una recarga | Recarga idempotente y coste acotado; no afecta a la corrección. |
| Varias réplicas emiten el mismo resync | `event_id` sintético distinto por emisión; el cliente está en una sola réplica y la recarga es coalescida. |
| Sin Redis real no se detectan diferencias de protocolo | Fakes registran argumentos exactos; se añade un smoke manual con `docker compose` en la verificación final. |
| El relay no debe bloquear el `lifespan` | La tarea sigue siendo `asyncio.create_task`; la resolución inicial ocurre dentro de ella. |

## 10. Reversión y despliegue

- **Reversión:** un commit por tarea; `git revert` en orden inverso (T003→T002→T001 para backend; T006→T005→T004 para frontend; T007 docs). No hay migraciones, datos ni configuración que deshacer.
- **Compatibilidad en ambos sentidos:** el frontend anterior ignora `RESYNC` y el campo aditivo; el backend anterior no emite `JOIN` y el frontend nuevo cierra la inicialización por gracia. La deduplicación tolera la ausencia de `event_id`.
- **Orden recomendado:** backend (T001-T003) antes que frontend (T004-T006). Si se revierte el backend con el frontend nuevo desplegado, la gracia y el polling cubren la ausencia de `RESYNC`.
- **Sin pasos de datos:** no hay backfill, migración ni ventana de mantenimiento.

## 11. Dependencias

**Ninguna nueva.** Se usan `redis.asyncio`, `socket.io`, `vue`, `node:test` y `pytest` ya presentes. Si una prueba exigiera una dependencia nueva, se detiene y se pregunta.

## 12. Cobertura de requisitos

| RF | Tareas |
|---|---|
| RF-001 | T001 (tope y sobre), T003 (recorte), T008 (CI). |
| RF-002 | T002 (arranque, reanudación, avance), T003 (recorte, `run_id`), T008. |
| RF-003 | T003 (resync backend), T005 (reconexión/coalescencia), T006 (público/paginación), T008. |
| RF-004 | T001 (worker), T002 (parseo y legado), T008. |
| RF-005 | T002 (emit), T004 (tolerancia del despacho), T008. |
| RF-006 | T004 (ventana, despacho), T005 (integración), T008. |
| RF-007 | Todas; T008 verifica el diff sin esquema, REST, Compose ni configuración. |
| RF-008 | T001-T006 (pruebas por tarea), T008 (comandos y jobs). |
| RF-009 | T007. |
| RF-010 | T003 (contrato y emisión), T004-T006 (recepción y política), T008. |

## 13. Contrato e interfaz

**No hay REST, rutas ni pantallas nuevas.** El único contrato nuevo es Socket.IO:

```text
RESYNC  { event_id: "resync:<uuid>", reason: "JOIN" | "RELAY_START" | "STREAM_TRIMMED" | "REDIS_RESET" }
```

- `JOIN` se emite al `sid` que entra en una sala.
- Los huecos se emiten a las salas con sockets conectados.
- Los eventos de dominio conservan su nombre y payload; solo se les añade `event_id`.
- No se cambia `PUBLIC_REALTIME_EVENTS`; `RESYNC` no forma parte de ese conjunto.

## 14. Decisiones justificadas

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| `MAXLEN` fijo de 10 000 como constante. | Variable de entorno. | Evita drift de configuración (R20) y no hay necesidad operativa demostrada. |
| Arranque en el último id. | Reemitir las últimas N entradas. | Evita duplicados y no convierte el stream en un registro; la corrección llega por `JOIN`/polling/reconciliación. |
| Avance de posición por entrada. | Avance por lote. | Acota la reentrega tras un fallo a una entrada y simplifica la detección de huecos. |
| `RESYNC` no persistido. | Guardarlo en Redis o en una cola. | Es una notificación de control; si no hay clientes, `JOIN` cubre la inicialización y la API es la fuente de verdad. |
| Broadcast a salas conectadas. | Intentar deducir la organización afectada. | Un stream recortado ya no contiene esa información; el payload vacío hace segura la emisión. |
| `event_id` sintético con prefijo `resync:`. | UUID sin prefijo. | Distingue el evento de control de un UUID del outbox en logs y pruebas; el cliente no lo parsea. |
| Utilidades puras de frontend. | Probar el composable con Nuxt montado. | El runner actual es `node --test` sin DOM ni Nuxt; extraer la lógica permite probar la política sin nuevas dependencias. |
| Gracias corta para el `JOIN` inicial. | Bloquear la carga hasta el `JOIN`. | Un backend anterior o un socket caído no deben dejar la página sin datos. |
| Reset de paginación pública. | Preservar páginas cargadas. | Recalcular offsets y mezclar páginas con datos nuevos es más complejo; el reset es consistente y verificable. |
| Sin nuevas dependencias. | Añadir una librería de colas o de estado. | El problema se resuelve con `Set`, promesas y `asyncio`; una dependencia nueva no aporta. |
