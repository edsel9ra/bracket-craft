# Tareas 006 — Retiro del scoping por torneo y avance manual entre fases

Spec: `specs/006-scoping-torneo-y-avance-fases/spec.md` (aprobada 2026-10-20)
Plan: `specs/006-scoping-torneo-y-avance-fases/plan.md`

Orden: **T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009 → T010 → T011**. Cada tarea se ejecuta en **una sola llamada de implementación**, escribe primero sus pruebas y deja en verde el job que le corresponda.

**Unidad de despliegue:** T001-T003 son una sola unidad. La 019 elimina tablas que el código anterior aún lee en el clonado; **no se aplica 019 con la imagen anterior**. El código nuevo se despliega primero (funciona con el esquema 018) y la 019 se aplica después.

**Solapamiento con 005:** en este checkout 005 está commiteada (`8b5eae0`). Si apareciera sin commit, se commitea antes o se separan los hunks con `git add -p`; 006 toca `tournaments/router.py` en zonas distintas y añade secciones nuevas en `AGENTS.md`/`README.md`.

**Sin dependencias, variables, Compose ni `.env.example`.**

## Progreso

- [x] **T001.** Migración 019, init, pre-chequeos y pruebas de esquema.
- [x] **T002.** R06: retiro de `tournament_user_roles` y firma de permisos.
- [x] **T003.** R12: retiro de `stage_edges`, CHECK y clonado/generación/seed.
- [x] **T004.** Protocolo de bloqueo en rutas existentes.
- [x] **T005.** `GET` de equipos por fase.
- [x] **T006.** `POST` atómico de equipos por fase.
- [x] **T007.** `DELETE` con guardas.
- [x] **T008.** Mapeo `ZZ409` → 409.
- [x] **T009.** UI mínima del panel de fase.
- [x] **T010.** Documentación y runbook.
- [ ] **T011.** Verificación final y checklist de merge.

**Estado de la vuelta 1:** T001-T010 implementadas. Evidencia local: backend **469 passed / 131 skipped**; opt-in **23 passed** (11 migración + 12 permisos/RLS/concurrencia); frontend **77 passed**, `typecheck` y `build` OK; el runner de migraciones se ejecutó en el puerto 55432 por las credenciales del PostgreSQL local. **T011 sigue `[ ]`** hasta CI en `main` y revisión humana; `MEMORY.md` dice «T011 ejecutada localmente, sin marcar».

---

## T001 — Migración 019, init y pre-chequeos

**Objetivo:** añadir la migración destructiva 019 con los tres pre-chequeos antes del primer `DROP`, el CHECK estrechado y la función con `ZZ409`; ajustar `init/01` para que un volumen limpio siga pasando por la 011; demostrar el resultado con pruebas opt-in.

**RF:** RF-003, RF-004, RF-005, RF-010, RF-011 (parte de esquema).

**Archivos:** `infra/postgres/migrations/019_remove_tournament_roles_and_stage_edges.sql` (nuevo), `infra/postgres/init/01_schema.sql`, `infra/postgres/init/03_hardening.sql` (solo si hace falta conservar `FORCE`), `backend/tests/migration_helpers.py` (nuevo, si se reutiliza), `backend/tests/test_migration_019.py` (nuevo).

**Pruebas primero:** escribir `test_migration_019.py` con: cadena limpia `init + 001..018 + 019`; volumen migrado a 018 y luego 019; RLS `ENABLE`/`FORCE` y ausencia de políticas/grants en `init` para ambas tablas; aborto con filas en `tournament_user_roles`; aborto con filas en `stage_edges`; aborto con `source_type='stage_rank'` y `'manual'`; aborto si no hay exactamente una constraint CHECK coincidente; CHECK final; `pg_get_functiondef` con `ZZ409`; `phase_slots` y columnas de slots presentes. Confirmarlas en rojo.

**Hecho cuando:**
- `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_019.py`
- `cd backend && pytest -q`
- `cd backend && python -m compileall -q app`
- `sh -n infra/postgres/migrate.sh`
- Runner de migraciones:
  `docker run --rm --network host -v "$PWD/infra:/infra:ro" -e PGHOST=127.0.0.1 -e PGPORT=5432 -e PGUSER=postgres -e PGPASSWORD=postgres_test_password postgres:17-alpine sh /infra/scripts/test_migrate_target.sh`
- `git -c core.whitespace=cr-at-eol diff --check`
- Nota: si no hay PostgreSQL disponible, se declara la prueba opt-in como **no ejecutada** y se completa en T011; el job `backend` normal debe quedar verde.
- Nota: la 019 se prueba en una base desechable; no se aplica a la base de desarrollo compartida hasta T011 y con la imagen nueva ya desplegada.

---

## T002 — R06: retiro de `tournament_user_roles` y firma de permisos

**Objetivo:** eliminar el parámetro de ámbito por torneo de `require_permission` y `require_administrative_resolution`, actualizar todos los llamadores y dobles, retirar el parámetro del helper de gestión y dejar el modelo documentado en pruebas.

**RF:** RF-007, RF-008, RF-009, RF-002(d), RF-005.

**Archivos:** `backend/app/core/permissions.py`, `backend/app/modules/tournaments/router.py` (helper y llamadas), `backend/app/modules/matches/router.py`, `backend/app/modules/matches/service.py`, `backend/app/modules/advancement/service.py` (si usa la firma), `backend/tests/test_permissions_signature.py` (nuevo), `backend/tests/test_photo_resolution.py`, `backend/tests/test_swiss_transaction.py`, `backend/tests/test_invitations.py` (revisar).

**Pruebas primero:** prueba de `inspect.signature` sin `tournament_id`; prueba de que el SQL/decisión no cambia el comportamiento de organización; actualizar los dobles `permission(db, context, code, tournament_id=None, **kwargs)` a la nueva firma; prueba de que `require_administrative_resolution` no recibe torneo. Confirmar en rojo.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_permissions_signature.py tests/test_photo_resolution.py tests/test_swiss_transaction.py tests/test_invitations.py`
- `cd backend && pytest -q`
- `cd backend && python -m compileall -q app`
- `grep -rn -A8 "require_permission(" backend/app backend/tests --include='*.py'` no muestra ningún `tournament_id=`
- `cd backend && python -c "import inspect; from app.core.permissions import require_permission; assert 'tournament_id' not in inspect.signature(require_permission).parameters"`
- `git -c core.whitespace=cr-at-eol diff --check`

---

## T003 — R12: retiro de `stage_edges`, CHECK y clonado/generación/seed

**Objetivo:** eliminar el bloque de clonado de `stage_edges`, ajustar el código que emitía o leía valores retirados y cubrir con pruebas que el clonado y la generación siguen intactos; el CHECK y el `DROP` ya vienen de T001.

**RF:** RF-011, RF-012, RF-002(a)(b).

**Archivos:** `backend/app/modules/tournaments/router.py` (clonado, generación), `backend/scripts/seed_demo.py` (solo si referencia valores retirados), `backend/tests/test_tournament_scheduling.py`, `backend/tests/test_version_clone.py` (nuevo), `backend/tests/test_advancement.py`.

**Pruebas primero:** prueba de clonado con doble de sesión que verifica que no se consulta/inserta `stage_edges` y que `phase_slots` se clona; prueba de generación con `source_type` solo `direct_team`/`match_result`; regresión de llaves y avance dentro de fase. Confirmar en rojo.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_version_clone.py tests/test_tournament_scheduling.py tests/test_advancement.py`
- `cd backend && pytest -q`
- `cd backend && python -m compileall -q app`
- `grep -rn "stage_edges" backend/app backend/scripts --include='*.py'` no devuelve referencias
- `git -c core.whitespace=cr-at-eol diff --check`

---

## T004 — Protocolo de bloqueo en rutas existentes

**Objetivo:** introducir `core/locking.py` y aplicarlo a creación de partido, alta/bulk de equipos, generación/sorteo, cierre, `advancement` y `standings`, con el orden fase → versión → partido(s) → segmentos → jugadores y el pre-bloqueo de destinos del cierre.

**RF:** RF-021, RF-017, RF-005.

**Archivos:** `backend/app/core/locking.py` (nuevo), `backend/app/modules/tournaments/router.py`, `backend/app/modules/matches/service.py`, `backend/app/modules/advancement/service.py`, `backend/app/modules/standings/service.py`, `backend/tests/test_lock_order.py` (nuevo).

**Pruebas primero:** doble de sesión que registra sentencias y verifica: fase antes que versión en POST/DELETE/creación/equipos/generación; versión antes que partidos; **todas las consultas de partidos con `ORDER BY id`**, incluidas `_clear_stage_schedule` y placeholders Swiss; cierre bloquea origen y destinos (incluida `GF2` si el origen es `GF1` y existe) por `id` antes de `_persist_events`; oficiales con `lock_matches`; `recalculate` bloquea fase antes del advisory; rutas version-only no invierten el orden. Confirmar en rojo.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_lock_order.py tests/test_swiss_transaction.py tests/test_tournament_scheduling.py`
- `cd backend && pytest -q`
- `cd backend && python -m compileall -q app`
- `git -c core.whitespace=cr-at-eol diff --check`

---

## T005 — `GET` de equipos por fase

**Objetivo:** añadir el contrato de lectura `GET /tournaments/{id}/stages/{stage_id}/teams` con asignados de la fase/versión y no asignados `registered`, sin mezclar versiones.

**RF:** RF-018, RF-005, RF-014 (404).

**Archivos:** `backend/app/modules/tournaments/schemas.py`, `backend/app/modules/tournaments/router.py`, `backend/tests/test_stage_teams.py` (nuevo, sección GET).

**Pruebas primero:** 404 torneo/fase; 200 con asignados deduplicados y no asignados; equipo de otra versión no aparece; equipo no `registered` no aparece en `unassigned`; RLS/cross-tenant con doble. Confirmar en rojo.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_stage_teams.py`
- `cd backend && pytest -q`
- `cd backend && python -m compileall -q app`
- `git -c core.whitespace=cr-at-eol diff --check`

---

## T006 — `POST` atómico de equipos por fase

**Objetivo:** implementar la asignación en lote con validación de esquema, orden de códigos, bloqueo, atomicidad, arrays `assigned`/`already_assigned` y 201/200.

**RF:** RF-013, RF-014, RF-015, RF-020, RF-021, RF-017.

**Archivos:** `backend/app/modules/tournaments/schemas.py`, `backend/app/modules/tournaments/router.py`, `backend/tests/test_stage_teams.py` (sección POST).

**Pruebas primero:** 422 vacío/>64/UUID inválido/duplicado; 404 torneo/fase; 409 versión publicada antes de permiso; 403 en borrador; 409 con un equipo no `registered` y cero escrituras; 201 lote nuevo/mixto; 200 si todos ya estaban; arrays sin duplicados; lock fase → versión; el cuerpo no acepta 200 para altas. Confirmar en rojo.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_stage_teams.py`
- `cd backend && pytest -q`
- `cd backend && python -m compileall -q app`
- `git -c core.whitespace=cr-at-eol diff --check`

---

## T007 — `DELETE` con guardas

**Objetivo:** implementar el retiro de un equipo de una fase con precedencia 404 → 409 versión → 403 → 409 equipo/partido/`standings` → 204, incluyendo múltiples filas `stage_teams`.

**RF:** RF-016, RF-020, RF-021, RF-017.

**Archivos:** `backend/app/modules/tournaments/router.py`, `backend/tests/test_stage_teams.py` (sección DELETE).

**Pruebas primero:** 404 torneo/fase; 409 en publicada aunque no estuviera asignado; 403 sin permiso; 409 equipo no registrado; 409 con partido; 409 con `standings` y sin partidos; 204 idempotente; 204 borra todas las filas de un equipo con grupos; lock fase → versión. Confirmar en rojo.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_stage_teams.py`
- `cd backend && pytest -q`
- `cd backend && python -m compileall -q app`
- `git -c core.whitespace=cr-at-eol diff --check`

---

## T008 — Mapeo `ZZ409` → 409

**Objetivo:** mapear el SQLSTATE `ZZ409` a 409 en el manejador central, sin comparar texto ni filtrar SQL/filas, y añadir las pruebas opt-in de concurrencia de las carreras críticas.

**RF:** RF-020, RF-021.

**Archivos:** `backend/app/main.py`, `backend/tests/test_error_sanitization.py`, `backend/tests/test_concurrency_006.py` (nuevo, opt-in), `backend/tests/test_stage_teams.py` (si hace falta endpoint).

**Pruebas primero:** `DBAPIError` con `orig.sqlstate='ZZ409'` y texto distinto → 409; `23502` sigue 500 saneado; el log no contiene SQL ni PII; opt-in con los **12 casos** de cross-tenant, dos DELETE, guarda de `standings`, 409 en publicada con equipo asignado y no asignado, `ZZ409` por API, `GET` tras clonar y permisos owner/administrator/operator/referee, además de dos POST/DELETE simultáneos, POST/DELETE vs publicación y DELETE vs creación de partido sin 500 ni estado parcial. Confirmar en rojo.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_error_sanitization.py tests/test_stage_teams.py`
- `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_concurrency_006.py`
- `cd backend && pytest -q`
- `cd backend && python -m compileall -q app`
- `git -c core.whitespace=cr-at-eol diff --check`

---

## T009 — UI mínima del panel de fase

**Objetivo:** mostrar equipos asignados, asignar varios `registered` no asignados y quitar uno, con **botones renderizados y deshabilitados** sin permiso o fuera de borrador, estados de error, aviso de calendario y recarga, usando el `GET`/`POST`/`DELETE` y `useApi`.

**RF:** RF-019, RF-018.

**Archivos:** `frontend/app/pages/workspace/tournaments/[id].vue`, `frontend/app/utils/stageTeams.ts` (nuevo), `frontend/app/composables/useI18n.ts`, `frontend/tests/stage-teams.test.ts` (nuevo).

**Pruebas primero:** utilidades puras de deduplicación/normalización; casos de respuesta 201/200/204 y error; después `typecheck/build`. Confirmar la utilidad en rojo.

**Hecho cuando:**
- `cd frontend && pnpm install --frozen-lockfile`
- `cd frontend && pnpm test`
- `cd frontend && pnpm run typecheck`
- `cd frontend && pnpm run build`
- `git -c core.whitespace=cr-at-eol diff --check`

---

## T010 — Documentación y runbook

**Objetivo:** documentar el modelo de autorización y el avance manual, retirar promesas de `stage_rank`/selectores, y publicar el runbook 019 con copia, `pg_restore -l`, pre-chequeo con `to_regclass` + SQL dinámico, catálogo, transacción, smoke y forward-fix.

**RF:** RF-001, RF-002, RF-022.

**Archivos:** `README.md`, `AGENTS.md`, (T011) `MEMORY.md`.

**Pruebas primero:** revisar que las consultas y comandos del runbook son ejecutables; `grep` de que no queda `stage_rank` como capacidad ni roles por torneo; contraste de secciones con la spec.

**Hecho cuando:**
- `grep -rn "stage_rank\|tournament_user_roles\|avance automático" README.md AGENTS.md` muestra solo las notas de «no soportado»/«retirado»
- `grep -n "pg_restore -l\|to_regclass\|incoming_fk\|ZZ409" README.md AGENTS.md`
- `git -c core.whitespace=cr-at-eol diff --check`

---

## T011 — Verificación final y checklist de merge

**Objetivo:** ejecutar la verificación completa, incluidas las pruebas opt-in de migración/concurrencia, y cerrar con un reporte honesto de lo ejecutado y lo no verificado; actualizar `MEMORY.md`.

**RF:** RF-006 y verificación de RF-001 a RF-022.

**Estado:** ejecutada localmente (2026-10-20) con la evidencia del encabezado; **sin marcar** hasta CI en `main` y revisión humana distinta del autor.

**Archivos:** `MEMORY.md` y el reporte de verificación.

**Pruebas primero:** no aplica; es la ejecución de la suite y el checklist.

**Hecho cuando:**
- `cd backend && pytest -q`
- `cd backend && python -m compileall -q app`
- `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_019.py tests/test_concurrency_006.py`
- `sh -n infra/postgres/migrate.sh`
- Runner de migraciones:
  `docker run --rm --network host -v "$PWD/infra:/infra:ro" -e PGHOST=127.0.0.1 -e PGPORT=5432 -e PGUSER=postgres -e PGPASSWORD=postgres_test_password postgres:17-alpine sh /infra/scripts/test_migrate_target.sh`
- `cd frontend && pnpm install --frozen-lockfile && pnpm test && pnpm run typecheck && pnpm run build`
- `python3 infra/scripts/verify_version_sources.py --exclude-constitution`
- `docker compose config -q` (no hay cambios de Compose; si el entorno lo ejecuta, debe pasar)
- `pip-audit -r backend/requirements.txt`
- Auditoría del frontend desde la raíz:
  ```sh
  AUDIT_JSON="/tmp/pnpm-audit.json"
  trap 'rm -f "$AUDIT_JSON"' EXIT
  if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
  PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
  ```
- `trivy fs . --skip-dirs frontend/node_modules,frontend/.pnpm-store,.venv --ignore-unfixed --severity CRITICAL,HIGH --exit-code 1`
- `git -c core.whitespace=cr-at-eol diff --check`
- Checklist de merge:
  - [ ] 005 no aparece en el diff de 006; si aparece, se separó con `git add -p`.
  - [ ] La 019 se aplicó/validó después del código nuevo; no se desplegó con la imagen anterior.
  - [ ] Backup verificado con `pg_restore -l` y pre-chequeo documentado.
  - [ ] Pruebas opt-in ejecutadas o declaradas **no ejecutadas** con el motivo.
  - [ ] `MEMORY.md` actualizado con la migración 019, `ZZ409`, el orden de bloqueo y el riesgo de no rollback.
  - [ ] Revisión humana distinta del autor.
