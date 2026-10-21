# Tareas — Spec 007 (R09/R10)

Convención: cada tarea se implementa en **una sola llamada**, con las pruebas primero y en verde al terminar. `NNN` de migración = **021**. Los comandos se ejecutan desde la raíz salvo que se indique `cd`.

Verificación de whitespace (repetible; `git add -N` para archivos nuevos):

```sh
git add -N <archivos nuevos>
git -c core.whitespace=cr-at-eol diff --check
```

---

- [x] **T001. Enmienda constitucional §3.2 → 1.3.0 (cambio propio, previo).**
  - Objetivo: aplicar el texto exacto de la spec (cabecera `1.3.0`, fecha `2026-10-20`, viñeta §3.2 con «sustituciones»/«ventana de inscripción» y sin «transferencias», fila del historial con motivo/reglas/impacto). No se toca código y este commit no se mezcla con el funcional.
  - RF: 006.
  - Archivos: `docs/constitution.md`.
  - Pruebas/comprobaciones primero: revisar el texto contra la spec antes de editar; después comprobar versión, fecha, viñeta e historial.
  - Hecho cuando:
    - `grep -n "Versión\|Última actualización" docs/constitution.md` muestra `1.3.0` y `2026-10-20`.
    - La viñeta de §3.2 contiene «sustituciones, ventana de inscripción» y «Las transferencias no forman parte de la configuración».
    - Existe la fila `| 1.3.0 | 2026-10-20 |` en §7 con motivo, reglas e impacto.
    - `git status --porcelain` solo lista `docs/constitution.md`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.
    - `python3 infra/scripts/verify_version_sources.py --exclude-constitution` pasa.

- [x] **T002. Migración 021 aditiva + pruebas opt-in.**
  - Objetivo: añadir `player_out_id`/`player_in_id`, FKs compuestas a `players(id, organization_id)`, `CHECK ... NOT VALID` y pre-chequeos informativos; sin tocar `init/01` ni 019/020.
  - RF: 030, 031, 032, 033, 034.
  - Archivos: `infra/postgres/migrations/021_match_event_substitutions.sql` (nuevo), `backend/tests/test_migration_021.py` (nuevo).
  - Pruebas primero (en rojo): base desechable hasta 020 (`throwaway_database(last=20)`), aplicar 021 (`apply_migration(conn, 21)`); columnas nulas; FKs compuestas por nombre y columnas; `CHECK NOT VALID` rechaza una fila nueva inválida y acepta la válida; un evento `substitution` legado se conserva y su `UPDATE` se rechaza; pre-chequeos con conteos; cadena limpia (init + 001..021) idéntica a la migrada.
  - No incluye: cambios de código de aplicación.
  - Hecho cuando:
    - `cd backend && pytest -q` (la opt-in se salta sin variables) y `cd backend && python -m compileall -q app`.
    - `sh -n infra/postgres/migrate.sh`.
    - `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_021.py`.
    - `docker run --rm --network host -v "$PWD/infra:/infra:ro" -e PGHOST=127.0.0.1 -e PGPORT=5432 -e PGUSER=postgres -e PGPASSWORD=postgres_test_password postgres:17-alpine sh /infra/scripts/test_migrate_target.sh`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T003. `rules_config` 3.3.0: esquema tolerante, defaults y pareja efectiva.**
  - Objetivo: aceptar 3.2.0/3.3.0; `substitutions` y `transfers` opcionales; `roster_lock_matchday` de primer nivel con promoción; minutos con defaults 90/120; validación de la pareja efectiva (defaults + `stage_defaults` + overrides parciales) antes de persistir; `DEFAULT_RULES_CONFIG` en 3.3.0 sin `transfers`.
  - RF: 002, 003, 005, 040, 041, 044.
  - Archivos: `backend/app/modules/rules_engine/{defaults.py,engine.py,schemas.py}`, `backend/tests/test_rules_engine.py`, `backend/tests/test_rules_config_compat.py` (nuevo).
  - Pruebas primero: 3.2.0 con bloques deprecados; 3.3.0 sin ellos; `substitutions` ausente → defaults; promoción (solo heredado, solo primer nivel, ambos); `regular` 0/179/180; `extra` ≤ regular/181 con prórroga; prórroga desactivada no valida ni materializa `extra`; `enabled=true` + `regular=150` sin `extra` → 422 sin materializar 120; overrides parciales válidos e inválidos.
  - No incluye: routers ni frontend.
  - Hecho cuando:
    - `cd backend && pytest -q` y `cd backend && python -m compileall -q app`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T004. Motor puro de sustituciones (intervalos, límites, ventanas).**
  - Objetivo: módulo puro con estado en campo por intervalos, validación de una sustitución, reentrada, uso/ventanas por equipo y saldos por segmento; sin reloj ni base de datos.
  - RF: 012, 013, 014, 015.
  - Archivos: `backend/app/modules/rules_engine/substitutions.py` (nuevo), `backend/tests/test_substitutions_rules.py` (nuevo).
  - Pruebas primero: XI inicial; salida/entrada; expulsiones; unión de intervalos con reentrada (gol 65 válido para el que entró en 60 y 409 para el que salió); `allow_reentry`; dos cambios mismo segmento+minuto = una ventana; distinto `added_minute` = dos; segmentos distintos = dos; límites por equipo; `max_per_team=0`; mensajes con saldo; orden canónico `(minute, added, índice)`; saldos por `segment_number`.
  - No incluye: persistencia ni endpoints.
  - Hecho cuando:
    - `cd backend && pytest -q` y `cd backend && python -m compileall -q app`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T005. Cierre con sustituciones + proyección `match_segment_team_state` + `GET /operation`.**
  - Objetivo: integrar el motor en el cierre (validación antes de escribir, persistencia de columnas, idempotencia, minutos de planilla coherentes), asegurar/recalcular filas por segmento y exponer estado y contadores en la operación sin escribir.
  - RF: 004, 010, 011, 016, 017, 018, 045 (parte de estado).
  - Archivos: `backend/app/modules/matches/{service.py,router.py,schemas.py}`, `backend/tests/test_close_substitutions.py` (nuevo, dobles), `backend/tests/test_substitutions.py` (nuevo, opt-in), ajustes mínimos de fixtures en `backend/tests/test_match_result_immutability.py` si alguna acta usa suplentes sin sustitución.
  - Pruebas primero: 409 antes de escribir; contrato 422; límites y ventanas; reentrada; expulsiones; idempotencia (duplicado/igual/distinto); eventos de jugador fuera de intervalo; filas por segmento con saldo y recálculo por `segment_number`; `POST /segments` crea filas de equipos presentes; `GET /operation` expone `substitutions` y no escribe; dos cierres concurrentes.
  - No incluye: minutos configurables (T008), UI (T009).
  - Hecho cuando:
    - `cd backend && pytest -q` y `cd backend && python -m compileall -q app`.
    - `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_substitutions.py`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T006. `roster_lock_matchday` en altas de plantilla.**
  - Objetivo: bloquear altas cuando la jornada de referencia está completa (primera fase por `stage_order` de la versión publicada, todos los partidos confirmados), con dos comprobaciones en la importación y compensación de fotos.
  - RF: 021 (consumo), 022, 024, 025, 026, 027, 028.
  - Archivos: `backend/app/modules/tournaments/router.py`, `backend/tests/test_roster_lock.py` (nuevo, dobles + opt-in mínimo).
  - Pruebas primero: fuente publicada vs borrador; `stage_order` y desempate; partidos confirmados (`finished`/`administrative_resolution` + `result_confirmed`); cancelados fuera; jornada entera cancelada; sin versión/fase/jornada; 409 con jornada y sin nombre de torneo ni datos personales; importación bloqueada antes de subir fotos; bloqueo entre comprobaciones → 409, sin filas y con fotos compensadas.
  - No incluye: editor (T007/T010).
  - Hecho cuando:
    - `cd backend && pytest -q` y `cd backend && python -m compileall -q app`.
    - `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_roster_lock.py` (si el archivo incluye opt-in).
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T007. Retiro de transferencias, promoción al guardar y editor de inscripción.**
  - Objetivo: integrar la promoción en creación/actualización de versiones; retirar `transfers` del editor y de la serialización; añadir el campo de jornada de inscripción.
  - RF: 020, 021, 023 (config), 029, 046 (solo borradores), 047 (promoción al cargar).
  - Archivos: `backend/app/modules/tournaments/router.py`, `frontend/app/utils/rulesConfig.ts`, `frontend/app/components/RulesEditor.vue`, `frontend/app/composables/useI18n.ts`, `frontend/tests/rules-config.test.ts`.
  - Pruebas primero (frontend): cargar 3.2.0 con `transfers.roster_lock_matchday` y sin primer nivel → el campo muestra el valor antes de normalizar; guardar emite la clave y no `transfers`; ambas claves → prevalece el primer nivel; sección Transferencias ausente; campo vacío = nulo; i18n es/en en paridad.
  - No incluye: aceptación de versiones y minutos (T010).
  - Hecho cuando:
    - `cd backend && pytest -q` y `cd backend && python -m compileall -q app`.
    - `cd frontend && pnpm install --frozen-lockfile && pnpm test && pnpm run typecheck && pnpm run build`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T008. Minutos efectivos en el cierre, segmentos e interrupciones.**
  - Objetivo: sustituir 90/120 por `regular_time_minutes`/`extra_time_minutes` efectivos; frontera reglamentario/prórroga desde la configuración; tope `minute + added_minute` con descuento final; validar `POST /segments` y `interrupt` contra el máximo posible; exponer límites en la operación.
  - RF: 040, 042, 043, 045 (límites), 048.
  - Archivos: `backend/app/modules/matches/{service.py,router.py,schemas.py}`, `backend/tests/test_match_minutes.py` (nuevo, unitario + dobles), ampliación de `backend/tests/test_substitutions.py` (opt-in 40/100).
  - Pruebas primero: 40/100 con gol al 50 = prórroga; 90+2 válido; 89+30 → 409; 120+31 → 422; regular en torneo con prórroga topa en el reglamentario; segmento 95 con 120 válido y sin prórroga 422; interrupción 125 → 422; límites en `GET /operation` con override de fase.
  - No incluye: UI del acta (T009) ni editor (T010).
  - Hecho cuando:
    - `cd backend && pytest -q` y `cd backend && python -m compileall -q app`.
    - `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_substitutions.py`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T009. UI del acta: salida/entrada, contadores y errores.**
  - Objetivo: dos selectores por sustitución alimentados por el estado del servidor, filtros de opciones, contadores de vista previa sobre el borrador y errores; sin cambiar el flujo de cierre.
  - RF: 019, 045 (consumo).
  - Archivos: `frontend/app/utils/substitutions.ts` (nuevo), `frontend/app/pages/workspace/matches/[id].vue`, `frontend/app/composables/useI18n.ts`, `frontend/tests/substitutions.test.ts` (nuevo).
  - Pruebas primero: filtros (saliente en campo, entrante en banca), deshabilitado con `max_per_team=0` o sin planilla, contadores de vista previa, reentrada, borrador guardado/restaurado con los campos nuevos, paridad i18n.
  - No incluye: cambios de backend.
  - Hecho cuando:
    - `cd frontend && pnpm test && pnpm run typecheck && pnpm run build`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T010. `rulesConfig.ts` 3.2.0/3.3.0 y minutos en el editor.**
  - Objetivo: aceptar ambas versiones, normalizar siempre a 3.3.0, no exigir `transfers`, y exponer los minutos en `stage_defaults` y overrides.
  - RF: 002, 003, 040, 041, 044, 047.
  - Archivos: `frontend/app/utils/rulesConfig.ts`, `frontend/app/components/RulesEditor.vue`, `frontend/app/composables/useI18n.ts`, `frontend/tests/rules-config.test.ts`.
  - Pruebas primero: `3.2.0` válida; `3.3.0` válida; `3.3.0` sin `substitutions`; normalización a `3.3.0`; rechazo de versión desconocida; minutos con defaults y validación de pareja (incluido override parcial); editor muestra minutos por fase.
  - No incluye: backend.
  - Hecho cuando:
    - `cd frontend && pnpm test && pnpm run typecheck && pnpm run build`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T011. Contrato interno de `GF1`/`GF2` y formaciones.**
  - Objetivo: constantes nombradas de única fuente, documento `docs/contrato-reglas.md` con `engine_version` 2026.1 (cuatro formaciones con posiciones y los dos códigos) y pruebas de coincidencia con código y `CHECK`.
  - RF: 050, 051, 052.
  - Archivos: `backend/app/modules/tournaments/scheduling.py`, `backend/app/modules/matches/{service.py,formations.py}`, `backend/app/modules/advancement/service.py`, `docs/contrato-reglas.md` (nuevo), `backend/tests/test_rule_contract.py` (nuevo), ampliación opt-in en `backend/tests/test_migration_021.py`.
  - Pruebas primero: el calendario produce exactamente `GRAND_FINAL_CODE`/`RESET_CODE`; el cierre y el avance los reconocen; el documento contiene cada formación y código; el `CHECK` de formaciones acepta exactamente las cuatro (opt-in); activación de la repetición desde el cierre de la gran final.
  - Hecho cuando:
    - `cd backend && pytest -q` y `cd backend && python -m compileall -q app`.
    - `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_021.py`.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [x] **T012. Documentación y runbook de la 021.**
  - Objetivo: `README.md`/`AGENTS.md` con sustituciones aplicadas, sin transferencias, ventana de inscripción y su jornada de referencia, minutos, estado de operación, contrato interno en fuentes/estructura y runbook de la 021 (pre-chequeos, orden migración → código, backup, `MIGRATION_TARGET=021`, smoke, *forward-fix*).
  - RF: 001, 006 (referencia), 020-029 (documentación), 030-034 (runbook), 050-052.
  - Archivos: `README.md`, `AGENTS.md`.
  - Pruebas/comprobaciones primero: revisar que no queden menciones a transferencias configurables ni a `is_voided` operativo.
  - Hecho cuando:
    - `python3 infra/scripts/verify_version_sources.py --exclude-constitution` pasa.
    - `grep -rn "transferencias" README.md AGENTS.md` solo muestra la ausencia declarada.
    - `grep -n "MIGRATION_TARGET=021" AGENTS.md README.md` encuentra el runbook.
    - `git -c core.whitespace=cr-at-eol diff --check` sin salida.

- [ ] **T013. Verificación final y checklist de merge.**
  - Objetivo: ejecutar todos los jobs, confirmar cada RF y criterio de la spec y dejar constancia de lo no ejecutado.
  - RF: 001-006, 010-019, 020-029, 030-034, 040-048, 050-052 (todos).
  - Archivos: ninguno (solo evidencias y `tasks.md` marcado).
  - Pruebas/comprobaciones:
    - Backend: `cd backend && pytest -q`; `cd backend && python -m compileall -q app`.
    - Opt-in: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_021.py tests/test_substitutions.py tests/test_roster_lock.py`.
    - Migraciones: `sh -n infra/postgres/migrate.sh`; runner de `MIGRATION_TARGET`; `MIGRATION_TARGET=021 $COMPOSE run --rm db-migrate` sobre copia con backup verificado por `pg_restore -l`.
    - Frontend: `cd frontend && pnpm install --frozen-lockfile && pnpm test && pnpm run typecheck && pnpm run build`.
    - Security: `pip-audit -r backend/requirements.txt`; bloque de auditoría de frontend de `AGENTS.md`; `trivy fs . --skip-dirs frontend/node_modules,frontend/.pnpm-store,.venv --ignore-unfixed --severity CRITICAL,HIGH --exit-code 1`.
    - Infraestructura: `python3 infra/scripts/verify_version_sources.py --exclude-constitution`; `docker compose config -q` (dev y merge dev+prod con variables dummy).
    - `git -c core.whitespace=cr-at-eol diff --check`.
  - Checklist de merge:
    - [ ] Enmienda 1.3.0 mergeada **antes** del cambio funcional y sin mezclarse con él.
    - [ ] 021 aplicada antes del código que usa las columnas; `init/01` sin cambios.
    - [ ] Sustituciones: contrato 422, negocio 409, límites, ventanas, reentrada, contadores y UI verificados.
    - [ ] `roster_lock_matchday` verificado (individual y masiva, dos comprobaciones).
    - [ ] Minutos efectivos y un solo veredicto de negocio (sin 180 como regla).
    - [ ] Contrato interno en `docs/contrato-reglas.md` y en `AGENTS.md`.
    - [ ] Documentación sin promesas de transferencias ni anulación; runbook de la 021 presente.
    - [ ] Opt-in ejecutadas y reportadas con su conteo; las no ejecutadas se declaran explícitamente.
    - [ ] Revisión humana distinta del autor (§6 de la constitución).
  - Hecho cuando: los comandos anteriores pasan o su fallo está declarado, y `tasks.md` queda marcado con la evidencia.
  - **Evidencia local (2026-10-21):** `pytest -q` 614 passed/152 skipped; opt-in completa 764 passed/2 skipped; `compileall` OK; `test_migrate_target.sh` OK; frontend 108 tests, typecheck y build OK; `verify_version_sources` OK; `docker compose config` dev y merge prod OK (`assert_production_compose.py` OK); auditoría frontend OK (2 no accionables sin parche); `pip-audit --local` sin hallazgos; `git diff --check` sin salida.
  - **Correcciones de la revisión (vuelta 1, 2026-10-21):** RF-043 (H1): `MatchLimits` tipado y consumido en el acta (`max_minute`/`added_minute_max` en inputs y borrador; 110 tests frontend). RF-005 (H2): `APPLIED_RULE_KEYS`/`DEPRECATED_RULE_KEYS` en `rules_engine.engine` con prueba de cobertura de `RULES_SCHEMA`. RF-029 (H3): `''` de `roster_lock_matchday` se valida como `null` y se guarda como `null`. RF-017 (H5): un jugador sin intervalos con minutos de planilla se rechaza con 409. RF-002 (H4): impacto operativo de una `3.2.0` publicada documentado en `README.md`/`AGENTS.md`. Evidencia: backend 616 passed/152 skipped; opt-in `test_substitutions.py`+`test_player_catalog_schema.py` 24 passed; frontend 110 tests, typecheck y build OK; `diff --check` sin salida.
  - **Limitaciones declaradas:** no verificables desde este entorno: CI, revisión humana y el despliegue real `MIGRATION_TARGET=021` (Docker daemon ausente). `pip-audit -r` no ejecutable por `ensurepip` ausente (se usó `--local`); Trivy no disponible. T013 sigue `[ ]` hasta CI y revisión humana.
