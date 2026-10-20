# Plan 006 — Retiro del scoping por torneo y avance manual entre fases

Estado: Implementada y validada por @reviewer (APROBADA, 2026-10-20); pendiente de CI en main y revisión humana (T011).

Spec: `specs/006-scoping-torneo-y-avance-fases/spec.md` (aprobada 2026-10-20)

## 1. Resumen técnico

El cambio tiene tres bloques y una migración:

1. **R06 — retiro del scoping por torneo.** Se elimina `tournament_user_roles` y el parámetro `tournament_id` de `require_permission`/`require_administrative_resolution`. El modelo queda: RBAC por organización + `match_officials` por partido. La tabla se conserva en `init/01` hasta la 019 (con `ENABLE`/`FORCE` y sin políticas/grants) porque la migración 011 la altera sin guardas.
2. **R12 — avance manual.** Se elimina `stage_edges`, se estrecha el CHECK de `phase_slots.source_type` a `direct_team`/`match_result` y se conserva `phase_slots` como procedencia. Se añaden `GET`, `POST` y `DELETE` de equipos por fase, solo en borradores, con UI mínima.
3. **Migración 019.** Destructiva, transaccional y sin rollback: pre-chequeos antes del primer `DROP`, `DROP ... IF EXISTS` como salvaguarda, CHECK localizado por catálogo y función de inmutabilidad recreada con SQLSTATE **`ZZ409`**.

Se añade un protocolo único de bloqueo **fase → versión → partido(s) → segmentos → jugadores** en las rutas que ya escriben estructura o resultados, incluido el cierre de acta, que pre-bloquea origen y destinos (incluida `GF2`) antes de escribir segmentos/jugadores.

No hay dependencias nuevas, variables de entorno, cambios de Compose ni cambios en proyecciones públicas. No hay eventos de outbox: la asignación manual ocurre en borrador y no genera tiempo real.

## 2. Estado de partida y supuestos

- **Spec 005:** el árbol de trabajo **no** tiene cambios de 005 sin commit. En este checkout 005 está en `8b5eae0` («Fix Spec 005») y toca `AGENTS.md`, `MEMORY.md`, `README.md`, `backend/app/modules/tournaments/router.py`, `backend/tests/test_photo_resolution.py` y sus artefactos SDD. Si al implementar 006 apareciera 005 sin commit, se commitea 005 primero o se separan los hunks con `git add -p` por archivo; 006 toca `router.py` en zonas distintas (stages/teams/clone) y `AGENTS.md`/`README.md` en secciones nuevas, así que la separación es por hunks, no por archivo.
- **Spec 006:** es un directorio nuevo no rastreado; `plan.md` y `tasks.md` se añaden junto a `spec.md`.
- **R06:** `tournament_user_roles` no tiene consumidores en código de aplicación, seed ni frontend. `require_permission` recibía `tournament_id` y no lo usaba; había 5 llamadores externos y el wrapper administrativo. Las únicas referencias actuales están en las pruebas de la 019, que nombran las tablas para verificar el retiro.
- **R12:** `stage_edges` no se inserta en ningún camino salvo el clonado; `phase_slots` se escribe pero no se resuelve. No existe endpoint para asignar un equipo ya registrado a una fase.
- **Bloqueo actual:** no hay ninguna ruta que bloquee versión antes que fase. El cierre bloquea el partido y escribe segmentos/jugadores/standings antes de `_advance_bracket`; `standings` usa un advisory lock por fase.
- **Migración 011:** aplica `FORCE ROW LEVEL SECURITY` a `tournament_user_roles` y `stage_edges` sin guardas. Por eso `init/01` no puede dejar de crear las tablas sin romper un volumen limpio; se mantienen `CREATE TABLE` + `ENABLE`/`FORCE` hasta la 019.
- **Runner:** `infra/postgres/migrate.sh` envuelve cada archivo en `BEGIN`/`COMMIT` y elimina el `BEGIN`/`COMMIT` externo del archivo. La 019 puede incluir su propio `BEGIN`/`COMMIT` por consistencia; la unidad transaccional la garantiza el runner.
- **Pruebas:** la suite de PostgreSQL es opt-in con `RUN_DATABASE_TESTS=1` y `DATABASE_ADMIN_URL`; los tests de migración crean bases desechables. La suite normal usa dobles de sesión y `ASGITransport(app=api)`.
- **Frontend:** la página de configuración del Workspace ya carga fases, equipos, partidos y plantillas con `useApi`; no hay tests de componentes, solo utilidades con `node:test`.

## 3. Decisiones de diseño

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| **D1. Helper único de bloqueo** en `backend/app/core/locking.py`: `lock_stage_and_version`, `lock_matches`, `lock_version`. | Helpers locales en `tournaments/router.py`, `matches/service.py`, `standings/service.py`. | Un solo lugar fija el orden fase → versión → partidos y evita que una ruta nueva lo invierta. Los helpers no fijan RLS; el contexto se fija en la transacción del llamador. |
| **D2. Pre-bloquear origen y destinos del cierre** (enlaces + `GF2` si `GF1`) ordenado por `id`, antes de `_persist_events`. | Bloquear cada destino al actualizarlo en `advancement`. | El orden actual escribe segmentos/jugadores antes de bloquear el destino; dos cierres pueden competir por el mismo partido destino. El pre-bloqueo hace el orden explícito y verificable. |
| **D3. SQLSTATE `ZZ409`** en la función recreada por la 019. | Nombre de constraint o comparación de texto. | El trigger no expone constraint; el texto puede cambiar. `ZZ409` es de clase de usuario y no colisiona con códigos estándar. El backend solo compara `sqlstate`. |
| **D4. Lote atómico con arrays** `assigned`/`already_assigned`; **201** si hay altas, **200** si todo estaba asignado. | Conteos o 202; deduplicar en silencio. | El cliente necesita saber qué IDs entraron y cuáles ya estaban; repetir el lote debe ser idempotente. Los duplicados del payload se rechazan en el esquema. |
| **D5. `GET` dedicado por fase** que devuelve asignados y no asignados de esa versión. | Reutilizar `GET /tournaments/{id}/teams` y filtrar en cliente. | El listado de equipos mezcla `stage_ids` de todas las versiones; el panel necesita una fuente única filtrada por `stage_id` y estado `registered`. |
| **D6. Conservar `phase_slots`** como procedencia y eliminar solo `stage_edges`/valores no usados. | Eliminar también `phase_slots` y `home_slot_id`/`away_slot_id`. | El calendario ya escribe slots y el clonado los replica; eliminarlos amplía el riesgo sobre scheduling sin aportar al avance manual. La spec los declara procedencia no resuelta. |
| **D7. Compatibilidad de init con 011** conservando `CREATE TABLE` + RLS y retirando políticas/grants/trigger. | Editar la 011 o quitar las tablas de init. | §2.4 es innegociable; un volumen limpio ejecuta init antes de 011 y fallaría. El estado intermedio no tiene acceso para `bracket_app`. |
| **D8. Sin outbox ni Socket.IO** para la asignación manual. | Emitir eventos de estructura en borrador. | La operación no cambia resultados ni estado operativo; el tiempo real es de partidos. El consumidor recarga con el `GET`/configuración. |
| **D9. Tests de endpoint con dobles de sesión** y concurrencia real solo opt-in. | Levantar PostgreSQL en cada test. | Mantiene la suite rápida y reproducible; la concurrencia y RLS se prueban en la suite opt-in, declarando lo no ejecutado. |

## 4. Archivos y responsabilidades

| Archivo | Responsabilidad | RF |
|---|---|---|
| `infra/postgres/migrations/019_remove_tournament_roles_and_stage_edges.sql` (nuevo) | Pre-chequeos, DROP de ambas tablas, CHECK estrechado, función con `ZZ409`. | RF-003, RF-004, RF-005, RF-011 |
| `infra/postgres/init/01_schema.sql` | Mantener `CREATE TABLE`/RLS de ambas tablas; quitar políticas, grants y `trg_protect_stage_edges`; conservar el resto. | RF-005, RF-008, RF-010 |
| `infra/postgres/init/03_hardening.sql` | Sin cambios funcionales: conserva los `FORCE` que la 019 hará innecesarios. | RF-010 |
| `backend/app/core/permissions.py` | Quitar `tournament_id` de la firma y del SQL; ajustar `require_administrative_resolution`. | RF-007, RF-008 |
| `backend/app/modules/tournaments/router.py` | Quitar el bloque de clonado de `stage_edges`; retirar el parámetro del helper de permisos; nuevos GET/POST/DELETE; integrar locks en stages/teams/matches. | RF-007, RF-008, RF-011, RF-013 a RF-021 |
| `backend/app/modules/tournaments/schemas.py` | `AssignStageTeamsRequest` (1..64, UUID únicos), respuestas de asignación y de equipos por fase. | RF-013, RF-018 |
| `backend/app/core/locking.py` (nuevo) | Helpers de bloqueo con orden único y sin fijar RLS. | RF-021 |
| `backend/app/modules/matches/service.py` | Cierre: fase → versión → partido origen → destinos → segmentos/jugadores; `standings` con fase bloqueada. | RF-021 |
| `backend/app/modules/matches/router.py` | Alta/baja de oficiales con `lock_matches`; no cambia fase/versión. | RF-021 |
| `backend/app/modules/advancement/service.py` | `lock_targets` ordenado e idempotente; actualización sin bloquear de nuevo. | RF-021 |
| `backend/app/modules/standings/service.py` | Bloqueo de fase antes del advisory lock. | RF-021 |
| `backend/app/main.py` | Mapear `sqlstate == "ZZ409"` a 409 saneado, sin texto. | RF-020, RF-021 |
| `backend/tests/test_migration_019.py` (nuevo) | Migración limpia/migrada, abortos, CHECK y `ZZ409`. | RF-003, RF-004, RF-011 |
| `backend/tests/test_permissions_signature.py` (nuevo) | Firma sin `tournament_id` y llamadores actualizados. | RF-007, RF-008 |
| `backend/tests/test_stage_teams.py` (nuevo) | GET/POST/DELETE: códigos, arrays, atomicidad, locks y múltiples filas. | RF-013 a RF-021 |
| `backend/tests/test_lock_order.py` (nuevo) | Orden fase → versión → partidos/segmentos; todos los partidos con `ORDER BY id`; destinos del cierre y `GF2`; oficiales; advisory de standings. | RF-021 |
| `backend/tests/test_concurrency_006.py` (nuevo, opt-in) | Carreras POST/DELETE/publicación y DELETE/creación de partido. | RF-021 |
| `backend/tests/test_error_sanitization.py` | Añadir `ZZ409` → 409 con texto distinto y PII intacta. | RF-020, RF-021 |
| `backend/tests/test_tournament_scheduling.py` / `test_advancement.py` | Regresión de llaves y del avance dentro de fase. | RF-011, RF-012 |
| `frontend/app/pages/workspace/tournaments/[id].vue` | Panel de equipos de la fase, cargar GET, asignar/quitar, errores, recarga. | RF-018, RF-019 |
| `frontend/app/utils/stageTeams.ts` (nuevo) | Funciones puras de deduplicación/normalización de la respuesta. | RF-019 |
| `frontend/app/composables/useI18n.ts` | Claves es/en del panel y sus errores. | RF-019 |
| `frontend/tests/stage-teams.test.ts` (nuevo) | Pruebas de las funciones puras. | RF-019 |
| `README.md`, `AGENTS.md`, `MEMORY.md` | Modelo de autorización, avance manual, runbook 019 y cierre. | RF-001, RF-002, RF-022 |

## 5. Base de datos: migración 019

**Nombre:** `019_remove_tournament_roles_and_stage_edges.sql`.

**Estructura (pseudocódigo, todo en la transacción del runner):**

```text
BEGIN (opcional; el runner ya envuelve)

DO $$
  -- to_regclass para cada tabla; si existe, count(*) debe ser 0
  -- contar phase_slots con source_type='stage_rank' y 'manual'; ambos 0
  -- si algo falla: RAISE EXCEPTION con nombre y conteo (sin identificadores)
END $$;

DO $$
  -- buscar en pg_constraint el CHECK de phase_slots.source_type
  -- exigir exactamente 1 coincidencia; si no, abortar
  -- DROP CONSTRAINT <descubierta>; ADD CONSTRAINT ... CHECK (direct_team/match_result)
END $$;

DROP TABLE IF EXISTS public.stage_edges;
DROP TABLE IF EXISTS public.tournament_user_roles;

CREATE OR REPLACE FUNCTION public.prevent_published_structure_mutation()
RETURNS TRIGGER ... -- mismo cuerpo y textos actuales
  RAISE EXCEPTION 'La versión publicada o archivada no puede modificarse' USING ERRCODE = 'ZZ409';
  RAISE EXCEPTION 'No se pueden insertar estructuras en una versión publicada' USING ERRCODE = 'ZZ409';

COMMIT (opcional)
```

- **Orden estricto:** los dos `DO` de pre-chequeo terminan antes del primer `DROP`. Si abortan, no se toca nada.
- **Sin CASCADE:** si una FK entrante impide el `DROP`, la migración falla; el runbook la detecta antes.
- **CHECK:** se descubre por catálogo; no se asume el nombre `phase_slots_source_type_check`.
- **`phase_slots` y `home_slot_id`/`away_slot_id`:** no se tocan.
- **Función:** se conservan los textos actuales para no invalidar `backend/tests/test_match_result_immutability.py:784`; solo se añade `USING ERRCODE = 'ZZ409'` en los dos `RAISE`.
- **Volumen limpio:** `init/01` crea ambas tablas con `ENABLE`/`FORCE`; 011 las fuerza; 019 las elimina. El resultado final es el mismo que en un volumen ya migrado.
- **Volumen migrado:** 019 elimina políticas, grants y trigger de `stage_edges` al hacer `DROP TABLE`; no quedan objetos huérfanos.
- **Pre-chequeo de catálogo:** el runbook consulta `pg_class`, `pg_proc`, `pg_views`, `pg_policy` por `polrelid`, `pg_trigger` y FKs entrantes (`pg_constraint.confrelid`); antes de 019 solo debe aparecer la propia tabla y, si existiera, su política/trigger; después, nada. Los conteos usan `to_regclass` + SQL dinámico y funcionan con tablas ausentes.
- **Reejecutabilidad:** `IF EXISTS` es salvaguarda; `schema_migrations`/checksum impiden una segunda aplicación. No se promete que `ADD CONSTRAINT` sea idempotente.
- **Rollback:** no hay `down`. La 019 es destructiva; después solo *forward-fix* con otra migración.

**Verificación de esquema en tests:** aplicar `init/01..03` + migraciones 001-018 en una base desechable, sembrar filas mínimas para probar abortos, aplicar 019 y comprobar: tablas ausentes, CHECK con solo `direct_team`/`match_result`, `pg_get_functiondef` con `ZZ409`, y que `phase_slots`/columnas de slots siguen existiendo.

## 6. Backend

### 6.1 R06 — permisos

- `require_permission(db, context, permission, match_id=None, role_codes=None)`.
- `require_administrative_resolution(db, context, match_id)` y su llamada en `matches/service.py`.
- Llamadores a actualizar: `tournaments/router.py:85` y `3213-3218`, `matches/router.py:82-90/795-800/902-907`, `matches/service.py:29-42`, dobles de `test_photo_resolution.py` y `test_swiss_transaction.py`.
- `_require_tournament_management` pierde el `tournament_id` que solo servía para el permiso; se actualizan sus 15 llamadas.
- No se toca `match_officials`: sigue siendo el ámbito por partido.

### 6.2 R12 — retiro de selectores

- Eliminar el bloque de clonado de `stage_edges` (`router.py:446-478`).
- No cambiar la escritura de `phase_slots` en generación (`2033-2051`, `2207-2220`) ni el clonado de slots (`408-444`).
- El seed no escribe `stage_edges`; no requiere cambios.
- No se toca `phase_config` (se documenta).

### 6.3 Contratos

**`GET /api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams`**

- 200: `{stage_id, version_id, assigned:[{team_id,name,short_code}], unassigned:[...]}`.
- `assigned`: `stage_teams` de esa fase/versión, deduplicado por `team_id`.
- `unassigned`: `tournament_teams.status='registered'` no asignados a esa fase.
- 404 torneo/fase; lectura de organización (RLS), sin `MANAGE_TOURNAMENTS`.

**`POST .../teams`**

- Body: `{team_ids:[UUID,...]}`, 1..64, sin duplicados.
- 422: payload inválido o duplicado (Pydantic).
- 404: torneo/fase.
- 409: versión no borrador; cualquier equipo no `registered` (ninguno se escribe).
- 403: sin `MANAGE_TOURNAMENTS` (solo en borrador).
- 201: al menos un equipo nuevo; body con arrays `assigned`/`already_assigned`.
- 200: todos ya asignados, `assigned=[]`, sin escrituras.

**`DELETE .../teams/{team_id}`**

- 404 torneo/fase; 409 versión no borrador (aunque no estuviera asignado); 403 sin permiso; 409 equipo no registrado; 409 partido de la fase que lo referencie; 409 fila de `standings` en esa fase; 204 idempotente. Si hay varias filas `stage_teams` del mismo equipo en la fase, se eliminan todas; el `GET` las deduplica por `team_id`.

### 6.4 Bloqueo

`backend/app/core/locking.py`:

```text
lock_stage_and_version(db, organization_id, tournament_id, stage_id)
  -> SELECT stages ... FOR UPDATE (404 si no existe)
  -> SELECT tournament_versions.status ... FOR UPDATE
  -> return (version_id, status)

lock_matches(db, organization_id, match_ids)
  -> SELECT id FROM matches WHERE id = ANY(:ids) ORDER BY id FOR UPDATE

lock_version(db, organization_id, version_id)
  -> SELECT status ... FOR UPDATE
```

- **Asignación/borrado:** `lock_stage_and_version` → versión `draft` → permiso.
- **Create match / teams / bulk / generate / draw:** `lock_stage_and_version` antes de leer `stage_teams`; Swiss de ronda >1 en versión publicada conserva su excepción y no exige `draft`.
- **Partidos:** todas las consultas que bloquean partidos usan `ORDER BY id`, incluidas `_clear_stage_schedule` y los placeholders Swiss; no se usa `ORDER BY bracket_code`.
- **Cierre:** leer identidad del partido sin lock → `lock_stage_and_version` → `AdvancementService.lock_targets` (origen + enlaces + `GF2`, orden `id`) → validaciones → `_persist_events` → segmentos → `standings` → `advance`. `GF2` se incluye siempre que el origen sea `GF1` y `GF2` exista, aunque no se active.
- **Advancement:** `lock_targets` bloquea el conjunto; `advance_from_match` actualiza sin volver a bloquear.
- **Oficiales:** alta/baja usan `lock_matches` sobre el partido antes de escribir; no cruzan fase/versión.
- **Standings:** `StandingsService.recalculate` bloquea la fase antes del `pg_advisory_xact_lock`; si el cierre ya la bloqueó, el lock es reentrante.
- **Excepciones version-only:** `create_stage`, `update_version_rules`, clonado y `publish`. `create_stage` bloquea la versión antes de insertar la fase.

### 6.5 Funciones puras

- `plan_stage_team_assignment(existing_ids: set[UUID], requested_ids: list[UUID]) -> AssignmentPlan`: conserva el orden de entrada, devuelve `assigned`/`already_assigned` sin duplicados y decide 201/200. No lee reloj ni base.
- `ordered_target_ids(source_id: UUID, link_targets: Iterable[UUID], reset_id: UUID | None) -> tuple[UUID, ...]`: deduplica, excluye el origen si aparece y ordena por `id` ascendente.
- `dedupeTeamIds(ids: string[])` y `normalizeStageTeamsResponse(value)`: utilidades de UI sin reloj ni estado global.
- Cualquier función futura que dependa de fecha recibirá la fecha como parámetro; esta spec no introduce lógica temporal.

### 6.6 `ZZ409`

- `main.py`: si `_dbapi_sqlstate(exc) == "ZZ409"`, responder **409** con un detalle estable; no registrar SQL ni filas. Otros `DBAPIError` conservan el 500 saneado.
- Las rutas no capturan el trigger para convertirlo por texto; el mapeo central es la única vía.
- No se cambia el texto de los triggers.

## 7. Frontend

- `stageTeams.ts` (puro): `dedupeTeamIds(ids)`, `normalizeStageTeamsResponse(value)`; sin reloj.
- Página `workspace/tournaments/[id].vue`:
  - Estado `stageTeamRows`, `stageTeamSelection`, `stageTeamBusy`, `stageTeamError`.
  - Al cambiar versión/fase: `GET` y actualizar la lista; `rememberStageTeam` para el contador existente.
  - Panel bajo la lista de fases: equipos asignados con «Quitar», selector múltiple de `unassigned` y «Asignar».
  - Controles de asignar/quitar **renderizados y deshabilitados** (no ocultos) sin `canManageTournaments` o fuera de borrador.
  - 201/200: limpiar selección y recargar configuración + equipos de fase.
  - 409/422: mensaje inline con `role="alert"`; no recarga.
  - Aviso: el calendario no se regenera automáticamente.
  - `selectedStageTeams` para el formulario de partido y el generador se alimenta de `assigned` (con respaldo a `teams.stage_ids` durante la carga).
- Claves i18n es/en: título del panel, asignar, quitar, errores, aviso de calendario, vacío.
- Sin nueva ruta ni store.

## 8. Estrategia de pruebas

- **Unitarias con mocks (siempre):**
  - Firma de `require_permission` sin `tournament_id`; llamadores actualizados.
  - Esquema del lote: vacío, >64, UUID inválido, duplicados → 422.
  - `plan_stage_team_assignment` (arrays, 201/200, sin duplicados).
  - Endpoints GET/POST/DELETE con doble de sesión: 404/409/403/409, atomicidad, arrays, múltiples filas, sin escrituras en fallo.
  - Orden de bloqueo con doble de sesión: fase antes que versión; versión antes que partidos; fase antes del advisory; todos los partidos con `ORDER BY id`; destinos de cierre y `GF2` por `id`; oficiales con `lock_matches`.
  - `ZZ409` con texto distinto → 409; otros SQLSTATE → 500 saneado.
  - Clonado sin `stage_edges`; funciones puras de UI y botones renderizados deshabilitados.
- **Integración opt-in (`RUN_DATABASE_TESTS=1`, `DATABASE_ADMIN_URL`):** **23 pruebas** (11 migración + 12 permisos/RLS/concurrencia):
  - Migración 019: limpia, migrada, aborto por filas en cada tabla, aborto por `source_type`, CHECK final y `ZZ409` en `pg_get_functiondef`.
  - Cross-tenant en asignación y GET; dos POST; **dos DELETE**; guarda de `standings` sin partidos.
  - 409 directo en publicada con el equipo **asignado y no asignado**.
  - `ZZ409` por API y real al insertar en versión publicada.
  - `GET` tras clonar sin mezclar versiones; permisos **owner/administrator/operator/referee**.
  - POST/DELETE vs publicación y DELETE vs creación de partido; clonado y proyección pública sin cambios.
- **Evidencia local de la vuelta 1:** backend **469 passed / 131 skipped**; opt-in **23 passed** (11 + 12); frontend **77 passed**, `typecheck` y `build` OK; el runner se ejecutó en el puerto 55432 por credenciales del PostgreSQL local.
- **Frontend:** `pnpm test` para utilidades, `typecheck` y `build`. Sin suite de componentes; prueba manual del flujo.
- **No se cubre:** E2E de navegador, **throughput/latencia medidos**, datos de producción, limpieza de `standings` (fuera de alcance), sembrado automático.

## 9. Riesgos y mitigaciones

- **Deadlock por orden de bloqueo.** Un helper único y pruebas de orden; ninguna ruta toma versión antes que fase ni partido antes que fase/versión. `standings` toma fase antes del advisory.
- **Carrera asignación/publicación.** Lock de fase y versión, relectura de estado y `ZZ409` a 409. Prueba opt-in.
- **Destinos del cierre bloqueados tarde.** Pre-bloqueo del conjunto completo (incluida `GF2`) antes de segmentos/jugadores.
- **Cambio de firma de `require_permission`.** 5 llamadores externos + wrapper + 3 dobles de prueba; criterio `grep -A8` y `inspect.signature`.
- **Volumen limpio vs migrado.** init conserva CREATE/RLS por 011; 019 elimina. Test de ambas rutas.
- **`stage_edges` en clonado.** Se elimina el bloque; si una versión antigua tuviera aristas, 019 aborta por filas y el operador decide.
- **`standings` huérfanas.** El DELETE responde 409 y no borra clasificación; no hay endpoint de limpieza en esta spec. Se documenta.
- **Migración destructiva.** Sin rollback; backup con `pg_restore -l`, pre-chequeo y forward-fix. **Orden de despliegue:** desplegar primero el código nuevo (funciona con el esquema 018), luego aplicar 019; después de 019 no volver a la imagen anterior porque el clonado antiguo lee `stage_edges`.
- **UI desactualizada.** El GET es la fuente única; tras 201/200/204 se recarga configuración y equipos; errores inline.
- **Swiss en versión publicada.** La generación de rondas >1 conserva su excepción; el protocolo de bloqueo no le exige `draft`.
- **Rendimiento no medido.** El cierre serializa por fase como garantía de corrección; no se midió throughput ni latencia. La no degradación queda como objetivo no verificado (RNF-003).

## 10. Reversión

- **Antes de 019:** revertir el commit de código y desplegar la imagen anterior; el esquema 018 sigue intacto.
- **Después de 019:** no hay `down`. Restaurar el backup solo si se acepta perder los cambios posteriores; el camino previsto es *forward-fix* con una migración nueva.
- **Fallo de 019:** al ser transaccional, no deja estado a medias; corregir el pre-chequeo y reintentar. Si falla por una FK entrante, crear la migración que la resuelva.
- **Backup:** `pg_dump -Fc`, `pg_restore -l` para verificar, y smoke de API/Workspace/público después.

## 11. Verificación constitucional

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por RLS | Sí | Las tablas conservadas mantienen `ENABLE`/`FORCE`; las retiradas quedan sin políticas/grants hasta 019. Cada endpoint fija `set_rls_context` y filtra por organización (RF-005). |
| §2.2 Rol sin `BYPASSRLS` | Sí | No se cambia el rol ni se añaden funciones `SECURITY DEFINER`. |
| §2.3 Lo publicado es inmutable | Sí | POST/DELETE solo en borrador; 409 antes de idempotencia; `ZZ409` mapeado; no se tocan triggers (RF-020, RF-021). |
| §2.4 Migraciones append-only | Sí | 019 nueva, sin editar aplicadas; `IF EXISTS` salvaguarda; sin `down` (RF-003). |
| §2.5 Proyección pública mínima | Sí | No se añaden campos; calendario/público sin cambios (RF-011). |
| §2.6 Sin secretos por defecto | No aplica | Sin variables ni secretos nuevos. |
| §2.7 Administración global separada | No aplica | No se toca `/admin` ni `platform_audit_logs`. |
| §2.8 Nada sin verificación | Sí | Tests unitarios/opt-in, CI y declaración de lo no ejecutado (RF-006). |
| §3.1 Base de datos y multi-tenancy | Sí | RLS, checksum, volumen limpio/migrado, pre-chequeos. |
| §3.2 Backend y configuración | Sí | Reglas siguen en JSON; no se añaden constantes deportivas. |
| §3.3 Frontend y `useApi.ts` | Sí | GET/POST/DELETE y UI mínima usan `useApi`; Workspace autenticado. |
| §3.4 Seguridad y configuración | Sí | Sin defaults nuevos; sin PII en logs/pre-chequeo. |
| §3.5 Infraestructura y CI | Sí | Sin cambios de Compose/versiones; jobs `infrastructure` y `security` se ejecutan. |
| §4 Criterios obligatorios | Sí | Jobs backend/frontend, migración con runner, documentación y revisión humana. |

## 12. Cobertura RF → tarea

| RF | Tarea |
|---|---|
| RF-001, RF-002 | T010 |
| RF-003, RF-004 | T001 |
| RF-005 | T001, T002, T005, T006, T007 |
| RF-006 | T011 (y cada tarea) |
| RF-007, RF-008, RF-009 | T002 |
| RF-010 | T001 |
| RF-011, RF-012 | T001 (esquema), T003 |
| RF-013, RF-014, RF-015 | T006 |
| RF-016 | T007 |
| RF-017 | T006, T007 |
| RF-018 | T005 |
| RF-019 | T009 |
| RF-020 | T006, T007, T008 |
| RF-021 | T004, T006, T007, T008 |
| RF-022 | T010 |

## 13. Criterios de plan

- Implementación de T001-T010 completada en la vuelta 1; T011 (CI y revisión humana) permanece abierta.
- Cada tarea escribió primero sus pruebas y dejó el job `backend` (y `frontend` cuando aplica) en verde; la evidencia local está en la sección 8.
- T001-T003 forman una unidad de despliegue: la 019 elimina tablas que el código antiguo aún lee en el clonado; no se despliega 019 con la imagen anterior.
- No se añaden dependencias, variables de entorno, cambios de Compose ni de `.env.example`.
- La migración 019 no se edita después de aplicada; cualquier corrección es una migración nueva.
