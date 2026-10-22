# Tareas 004 — Outbox y tiempo real: stream acotado, `event_id` y `RESYNC`

Spec: `specs/004-outbox-tiempo-real/spec.md` (aprobada 2026-10-19)
Plan: `specs/004-outbox-tiempo-real/plan.md`

Orden: **T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008**. T001-T003 son backend y se mergean antes que T004-T006 para que el contrato `RESYNC` exista cuando el frontend lo consuma. T007 actualiza la documentación y T008 cierra.

Cada tarea se ejecuta en una sola invocación del implementador, escribe primero sus pruebas y deja los cinco jobs de CI en verde (`backend`, `frontend`, `infrastructure`, `security` y `e2e`). No hay migraciones ni cambios de configuración: la reversión es el commit anterior.

## Progreso

- [x] **T001.** Worker: sobre con `event_id` y `XADD` acotado.
- [x] **T002.** Relay: arranque en cola, reanudación y `event_id` en el emit.
- [x] **T003.** Resync: recorte, reinicio de Redis, `JOIN` y `RELAY_START`.
- [x] **T004.** Frontend: deduplicación, despacho separado y `onResync`.
- [x] **T005.** Frontend: reconexión, política de recarga y coalescencia.
- [x] **T006.** Frontend: página pública, `RESYNC` y reset de paginación.
- [x] **T007.** Documentación: README, AGENTS y MEMORY.
- [x] **T008.** Verificación final y checklist de merge.

---

## T001 — Worker: sobre con `event_id` y `XADD` acotado

**Objetivo:** publicar cada evento con `MAXLEN` aproximado fijo de 10 000 entradas y un sobre que incluya `event_id` e `id` con el mismo valor del outbox, sin cambiar el payload de dominio ni el manejo de errores.

**RF:** RF-001, RF-004.

**Archivos previstos:**
- `backend/app/core/outbox.py` (`OUTBOX_STREAM_MAXLEN = 10_000`)
- `backend/app/workers/outbox.py` (`build_stream_message`, `publish_stream_event`, uso en `process_once`)
- `backend/tests/test_outbox_worker.py` (nuevo)

**Pruebas a escribir primero:**
- `build_stream_message` produce un JSON con `event_id`, `id`, `organization_id`, `event_type` y `payload`; `event_id == id`; el payload no cambia.
- `publish_stream_event` llama a `xadd` con `maxlen=10000` y `approximate=True` (o el argumento equivalente de redis-py), y con el mensaje en el campo `event`.
- `publish_stream_event` propaga la excepción de `xadd` para que `process_once` aplique el `fail_outbox_event` existente; no se cambia ese flujo.
- Un payload con tipos no serializables sigue funcionando con `default=str`.
- Un fallo de `xadd` no deja el evento como procesado (la prueba verifica la propagación, no la base de datos).

**Hecho cuando:**
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- El diff no modifica `backend/app/core/config.py`, `docker-compose.yml`, `docker-compose.production.yml` ni `.env.example`.
- `grep -n "OUTBOX_STREAM_MAXLEN" backend/app/core/outbox.py backend/app/workers/outbox.py` muestra la constante y su uso.

**Corte:** backend en verde; un worker nuevo con relay anterior sigue funcionando (el relay ignora `event_id`).

**Depende de:** —.

---

## T002 — Relay: arranque en cola, reanudación y `event_id` en el emit

**Objetivo:** sustituir el arranque en `"0-0"` por una posición en el último id, procesar entrada por entrada y emitir los eventos de dominio con `event_id`, incluyendo compatibilidad con el `id` legado. No incluye todavía la detección de huecos ni `RESYNC`.

**RF:** RF-002, RF-004, RF-005.

**Archivos previstos:**
- `backend/app/main.py` (`RelayState`, `parse_envelope`, `build_realtime_payload`, `stream_id_gt`, `resolve_tail`, `relay_cycle`, `relay_loop`, `emit_domain_event`)
- `backend/tests/test_outbox_relay.py` (nuevo)
- `backend/tests/test_hardening.py` (actualizar la prueba existente del relay)

**Pruebas a escribir primero:**
- Proceso nuevo con stream no vacío: no emite ninguna entrada anterior y entrega la siguiente publicada.
- Proceso nuevo con stream vacío: no emite nada y entrega la primera entrada nueva.
- Redis no disponible al arrancar: el bucle reintenta, resuelve el final en la primera conexión exitosa y no reemite lo acumulado (factoría y `stop` inyectables).
- Pérdida de conexión con Redis con el proceso vivo: conserva la posición, reanuda y reenvía lo retenido.
- Avance por entrada: un fallo después de emitir y antes de avanzar repite como máximo una entrada.
- `parse_envelope`: `event_id` válido; solo `id`; `event_id` inválido con `id` válido; `event_id != id` usa `event_id`; `event_id: null`; numérico; sin identificador; malformado.
- `build_realtime_payload`: conserva `match_id` y `tournament_id`, elimina un `event_id` de dominio y añade el del servidor.
- `emit_domain_event`: emite a organización y, si aplica, a torneo público, con el mismo `event_id`.
- `stream_id_gt` compara `(ms, seq)` (`9-9 < 10-0`).
- La prueba existente de entrada malformada sigue pasando, actualizada a la nueva firma si cambia.

**Hecho cuando:**
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `grep -n "resolve_tail\|relay_cycle\|stream_id_gt" backend/app/main.py` muestra las funciones y `relay_loop` las usa.
- No se modifica `backend/app/core/config.py`, Compose ni `.env.example`.

**Corte:** backend en verde; el relay no reemite histórico y los clientes reciben `event_id`. `RESYNC` aún no existe.

**Depende de:** T001.

---

## T003 — Resync: recorte, reinicio de Redis, `JOIN` y `RELAY_START`

**Objetivo:** detectar huecos de continuidad y emitir `RESYNC` con el contrato aprobado, incluido el `JOIN` dirigido al socket que entra en una sala.

**RF:** RF-002 (recorte y `run_id`), RF-010, RF-003 (parte backend).

**Archivos previstos:**
- `backend/app/main.py` (`RESYNC`, `new_resync_event_id`, `resync_rooms`, `emit_gap_resync`, `emit_join_resync`, comprobaciones de primera/última entrada y `run_id`, llamada en `connect`)
- `backend/tests/test_outbox_resync.py` (nuevo)
- `backend/tests/test_outbox_relay.py` (ampliar con recorte y `run_id`)

**Pruebas a escribir primero:**
- Recorte activo (`position < first`): emite `RESYNC` `STREAM_TRIMMED`, salta al final y no reemite el backlog.
- `run_id` distinto, posición mayor que el último id o stream vacío con posición previa: emite `REDIS_RESET` y resuelve al final.
- `RELAY_START` con `connected_socket_sessions` no vacío; sin salas no emite.
- `JOIN`: `emit_join_resync(sid)` emite `{event_id, reason:"JOIN"}` solo a ese `sid`, después de entrar en la sala; cubre organización y torneo público.
- `resync_rooms` deriva y deduplica `organization:*` y `tournament:*`, y omite sesiones sin alcance.
- Hueco con salas: un `emit` por sala; sin clientes: ninguna emisión y nada guardado.
- `event_id` de `RESYNC` tiene prefijo `resync:`, es único por emisión y participa en la deduplicación del cliente.
- Un fallo de `sio.emit` se registra y el relay continúa; la posición avanza.
- La emisión de `RESYNC` no altera la posición ni provoca una nueva detección.
- `INFO server` sin `run_id` no falla: se usan solo primera/última entrada y se registra la limitación.

**Hecho cuando:**
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `grep -n "RESYNC\|emit_gap_resync\|emit_join_resync" backend/app/main.py` muestra el contrato y las llamadas.
- El payload emitido no contiene `organization_id`, `tournament_id` ni `match_id`.

**Corte:** backend completo en verde; el contrato `RESYNC` está disponible y el frontend puede consumirlo.

**Depende de:** T002.

---

## T004 — Frontend: deduplicación, despacho separado y `onResync`

**Objetivo:** deduplicar entregas por `event_id` antes de invocar cualquier handler y separar `RESYNC` de los eventos de dominio, con utilidades puras testeables.

**RF:** RF-005 (tolerancia del despacho), RF-006, RF-010 (recepción).

**Archivos previstos:**
- `frontend/app/utils/realtimeDedup.ts` (nuevo)
- `frontend/app/utils/realtimeDispatch.ts` (nuevo)
- `frontend/app/composables/useRealtime.ts` (usar el despachador; añadir `onResync` a `RealtimeHandlers`)
- `frontend/tests/realtime-dedup.test.ts` (nuevo)

**Pruebas a escribir primero:**
- Ventana: primera entrega aceptada; duplicado rechazado sin handlers; ids distintos aceptados; `event_id` ausente, `null`, vacío o no cadena aceptado; desalojo FIFO tras 200; reset explícito; reentrega aceptada tras reset.
- Reinicio: socket/`scopeKey` nuevo (incluido organización A→B y público A→B), `disconnect()` y destrucción vacían; el auto-reconnect no vacía.
- Despacho: evento de dominio único invoca `onEvent` y el handler específico una vez; duplicado no invoca ninguno; `RESYNC` válido va a `onResync` y no a handlers de dominio; `RESYNC` inválido se descarta; un `event_id` de dominio no se usa.
- `useRealtime` no altera el estado de conexión al descartar un duplicado.

**Hecho cuando:**
- `cd frontend && pnpm test` pasa.
- `cd frontend && pnpm run typecheck` pasa.
- `cd frontend && pnpm run build` pasa.
- Las utilidades no importan Nuxt, `io` ni APIs del navegador.

**Corte:** frontend en verde; la deduplicación y la recepción de `RESYNC` están probadas sin cambiar todavía la política de recarga.

**Depende de:** T003 (contrato).

---

## T005 — Frontend: reconexión, política de recarga y coalescencia

**Objetivo:** detectar reconexiones, aplicar la política de recarga por consumidor con una sola recarga en curso más una trailing, e integrarla en `/workspace` y en la operación de partido. La ventana de inicialización usa una gracia local de 1500 ms si el `JOIN` no llega, sin configuración por entorno.

**RF:** RF-003, RF-010 (`JOIN` posterior a la inicialización).

**Archivos previstos:**
- `frontend/app/utils/realtimeConnection.ts` (nuevo)
- `frontend/app/utils/realtimeReload.ts` (nuevo)
- `frontend/app/composables/useRealtime.ts` (`onReconnect`, estado de conexión previa y ventana de inicialización)
- `frontend/app/pages/workspace/index.vue` (coordinador en lugar de `realtimeRefreshPending`)
- `frontend/app/pages/workspace/matches/[id].vue` (coordinador en lugar de `realtimeRefreshPending`)
- `frontend/tests/realtime-reload.test.ts` (nuevo)

**Pruebas a escribir primero:**
- `isReconnection`: conexión inicial no; éxito tras `reconnecting`/`error` sí; sin conexión previa no; el auto-reconnect no reinicia el estado de deduplicación.
- Política: `JOIN` en inicialización completa la carga inicial; `JOIN` después recarga Workspace y no público; `reconnect` recarga Workspace y no público; huecos recargan ambos y resetean paginación.
- Coalescencia: una solicitud durante una recarga en curso marca una trailing; varias dejan una; la última gana el disparo; el reset de paginación es acumulativo; `RESYNC` o reconexión durante una recarga no lanzan peticiones concurrentes.
- Fallo de recarga: conserva datos y estado, no programa reintentos automáticos.
- La conexión inicial no dispara la recarga de reconciliación; si el `JOIN` no llega, la gracia cierra la inicialización con la carga HTTP.

**Hecho cuando:**
- `cd frontend && pnpm test` pasa.
- `cd frontend && pnpm run typecheck` pasa.
- `cd frontend && pnpm run build` pasa.
- `grep -rn "realtimeRefreshPending" frontend/app/pages/workspace` no devuelve usos (se sustituyó por el coordinador).

**Corte:** frontend en verde; Workspace y operación recargan una vez por reconexión y no duplican la carga inicial.

**Depende de:** T004.

---

## T006 — Frontend: página pública, `RESYNC` y reset de paginación

**Objetivo:** consumir `RESYNC` en la página pública, mantener el polling de 30 s, completar la inicialización con el primer `JOIN` y reiniciar la paginación ante un resync de hueco.

**RF:** RF-003, RF-010.

**Archivos previstos:**
- `frontend/app/pages/tournaments/[id].vue`
- `frontend/app/utils/realtimeReload.ts` (casos públicos y reset)
- `frontend/tests/realtime-reload.test.ts` (ampliar)

**Pruebas a escribir primero:**
- `JOIN` durante la inicialización completa la carga inicial sin una segunda carga; `JOIN` posterior se ignora en público.
- `STREAM_TRIMMED`, `REDIS_RESET` y `RELAY_START` recargan y marcan `resetPagination: true`.
- El reset vuelve a `offset=0`, descarta las páginas adicionales y reinicia `standingsHasMore`/`matchesHasMore`.
- Una carga de página adicional en curso se descarta; la trailing queda como única recarga pendiente.
- Sin socket o sin `JOIN`, la inicialización cierra con la carga HTTP y la página no se bloquea.
- El polling de 30 s sigue activo mientras el socket no está conectado y no se reduce el intervalo.

**Hecho cuando:**
- `cd frontend && pnpm test` pasa.
- `cd frontend && pnpm run typecheck` pasa.
- `cd frontend && pnpm run build` pasa.
- `grep -n "PUBLIC_REFRESH_INTERVAL_MS = 30_000" "frontend/app/pages/tournaments/[id].vue"` conserva el valor.

**Corte:** frontend completo en verde; la página pública recarga solo ante resync de hueco y conserva el polling.

**Depende de:** T005.

---

## T007 — Documentación: README, AGENTS y MEMORY

**Objetivo:** dejar escrita la semántica de transporte, las garantías por tramo, el tope fijo, `event_id` y `RESYNC` en los documentos de estado actual.

**RF:** RF-009.

**Archivos previstos:**
- `README.md`
- `AGENTS.md`
- `MEMORY.md`

**Contenido obligatorio:**
- Stream como transporte vivo de mejor esfuerzo; tope fijo de 10 000 entradas (aproximado) y sin variable de entorno.
- Distinción entre **reinicio del relay** (arranca al final, sin reemisión) y **pérdida de conexión con Redis con el proceso vivo** (reanuda y puede duplicar).
- Garantías: outbox→stream *at-least-once*; stream→cliente *best-effort* con huecos y duplicados; API HTTP como fuente de verdad.
- `event_id` aditivo, `id` legado durante la transición y deduplicación de 200; `RESYNC` con `event_id`/`reason`, `JOIN`, huecos y política de recarga.
- Polling de 30 s de la página pública y recarga al reconectar en Workspace/operación.
- `MEMORY.md` registra el cierre de la spec y respeta ~50 líneas.

**Hecho cuando:**
- `grep -n "RESYNC\|10 000\|at-least-once\|best-effort" README.md AGENTS.md` muestra los conceptos.
- `grep -n "Spec 004\|RESYNC" MEMORY.md` muestra el registro de la spec.
- `wc -l MEMORY.md` devuelve ≤ 50.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.
- Ningún documento afirma que el stream es duradero ni que la entrega es exactly-once.

**Corte:** documentación alineada; no cambia código ni CI.

**Depende de:** T003, T006.

---

## T008 — Verificación final y checklist de merge

**Objetivo:** comprobar que la spec aprobada está implementada, que no hay cambios fuera de alcance y que el cambio puede fusionarse.

**RF:** RF-001 a RF-010.

**Checklist:**
- [x] `cd backend && pytest -q` pasa. *(2026-10-22: 999 passed, 2 warnings, con `RUN_DATABASE_TESTS=1` y base en 023.)*
- [x] `cd backend && python -m compileall -q app` pasa.
- [x] `cd frontend && pnpm test` pasa. *(236 passed.)*
- [x] `cd frontend && pnpm run typecheck` pasa. *(exit 0.)*
- [x] `cd frontend && pnpm run build` pasa. *(exit 0, 44,6 s.)*
- [x] Los cinco jobs de CI (`backend`, `frontend`, `infrastructure`, `security` y `e2e`) están en verde sobre `main`. *(Corrida de `9ad8db1`, 2026-10-22. En el momento del commit de 004 (`3b6210f`) `ci.yml` tenía cuatro jobs: `e2e` llegó con la enmienda 1.4.0 de la constitución y la spec 010.)*
- [x] `git diff --name-only` no incluye `infra/postgres/migrations/`, `infra/postgres/init/`, `docker-compose.yml`, `docker-compose.production.yml`, `.env.example` ni `frontend/package.json`. *(Verificado con `git show --name-only 3b6210f`, el commit de 004: no aparece ninguna de esas rutas.)*
- [x] El contrato `RESYNC` se verificó con una prueba manual o con los fakes: `JOIN` dirigido, tres motivos de hueco y ausencia de emisión sin sockets. *(`backend/tests/test_outbox_resync.py`: `test_emit_join_resync_targets_only_the_joining_socket`, los motivos `STREAM_TRIMMED`/`REDIS_RESET`/`RELAY_START` y `test_emit_gap_resync_without_clients_emits_nothing_and_stores_nothing`.)*
- [x] No se declara resuelto ningún hallazgo distinto de R13 y R14; R18, R32 y el resto siguen fuera de alcance. *(Sin referencias a otros hallazgos como resueltos; R18 y R32 figuran como fuera de alcance en `spec.md`, y `AGENTS.md` mantiene que el filtrado por rol exige una spec propia.)*
- [x] Lo que no se pudo ejecutar se declara; no se afirma una verificación no realizada. *(Véase la evidencia de cierre al final de este archivo.)*
- [x] La revisión humana es distinta del autor. *(Aprobada por el usuario el 2026-10-22; la validación de @reviewer no sustituye la §6.)*

**Comandos de cierre:**
```sh
cd backend && pytest -q
cd backend && python -m compileall -q app
cd frontend && pnpm test
cd frontend && pnpm run typecheck
cd frontend && pnpm run build
docker compose config -q
git -c core.whitespace=cr-at-eol diff --check
```

`docker compose config -q` se ejecuta sin cambios de Compose para confirmar que el entorno sigue siendo válido; no se espera ningún diff en esos archivos.

**Corte:** cierre de la spec con evidencia de CI y revisión humana.

**Depende de:** T007.

## Cierre

No se crean migraciones, scripts operativos ni variables de entorno. Las tareas T001-T006 son independientes de la base de datos y pueden revertirse commit a commit; T007 y T008 no modifican el comportamiento.

**Evidencia de cierre (2026-10-22, `main` en `9ad8db1`):** `cd backend && pytest -q` con `RUN_DATABASE_TESTS=1` y base en 023 (999 passed, 2 warnings), `python -m compileall -q app`, `pnpm test` (236 passed), `pnpm run typecheck`, `pnpm run build` y los cinco jobs de CI en verde (incluido `e2e`); alcance del commit `3b6210f` comprobado con `git show --name-only`.
