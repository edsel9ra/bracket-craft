# Tareas 033 — Acta rectificativa

Estado: **aprobado** por el usuario el 2026-11-12 («Apruebo las tareas.»). Plan aprobado el 2026-11-12. Cada tarea sigue la Fase 5: tests primero en rojo, código mínimo, verde y marca.

Son 18 tareas, más de las 10 que fija el proceso como límite. En lugar de dividir la spec, que ya tiene sus decisiones cerradas, las agrupo en los cuatro PRs secuenciales del plan (§8). Cada PR se valida y fusiona antes de empezar el siguiente.

Variables de las pruebas de base de datos (como en CI): `RUN_DATABASE_TESTS=1 DATABASE_URL=<rol app> DATABASE_ADMIN_URL=<admin>`.

## PR A — Esquema y lectura de la versión vigente

- [x] **T1. Migración 035: tablas de rectificación, RLS y triggers *append-only*.** RNF-001, RF-002, RF-013
- Hecho cuando: `test_migration_035.py` comprueba tablas, RLS/FORCE, políticas, `GRANT`, rechazo de `UPDATE`/`DELETE` y el índice de una solicitud pendiente sobre volumen limpio y sobre 034→035. Pasan `cd backend && RUN_DATABASE_TESTS=1 … pytest -q tests/test_migration_035.py`, `sh -n infra/postgres/migrate.sh` y `sh infra/scripts/test_migrate_target.sh`.
- [x] **T2. Migración 035: trigger de autoaprobación, permisos nuevos y transición de estados.** RF-007, DA-1
- Hecho cuando: el test inserta una decisión del solicitante y recibe el error del trigger, y verifica los permisos en `role_definitions` y `roles` de `owner`/`administrator` sin duplicados, así como las transiciones de estado permitidas y prohibidas.
- Comando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_migration_035.py`.
- [x] **T3. Migración 035: `match_slot_assignments`, backfill inequívoco y escritura desde cierre y avance.** Plan §5.2
- Hecho cuando: el test de migración cubre el backfill (inequívoco → `advancement_link`; ambiguo → `manual`) y `test_close_match*.py` comprueba que cerrar un acta registra la asignación del destino. `pytest -q` en verde.
- [x] **T4. Vistas `v_match_current_report`/`v_match_current_events` y públicas recreadas con `rectified_at`.** RF-021, RF-022
- Hecho cuando: el test de migración demuestra que, en partidos sin rectificar, la salida de las vistas públicas es la misma que en la 034, y `test_public_field_allowlist.py` y `test_public_access_matrix.py` solo admiten el campo nuevo `rectified_at`.
- Comando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_migration_035.py tests/test_public_field_allowlist.py tests/test_public_access_matrix.py`.
- Decisiones T4 aprobadas: internas `security_invoker`; públicas como propietario con filtros de publicación y overlay directo sobre tablas, contrastado con el interno. La pública conserva eventos anulados del original; la interna los excluye y ambas excluyen los anulados de la versión rectificativa.
- [x] **T5. Lectores sobre la versión vigente y test de inventario.** RF-014, RF-021
- Hecho cuando:
  - clasificación, historial disciplinario del cierre, estadísticas públicas y lecturas del Workspace usan las vistas;
  - `test_rectification_readers.py` falla si un lector nuevo consulta el original;
  - la suite existente sigue en verde (`cd backend && pytest -q && python -m compileall -q app`).

## PR B — Solicitud y decisión

- [x] **T6. Extraer `validate_report_payload` del cierre sin cambiar su comportamiento.** RF-001, RNF-005
- Hecho cuando: un test de equivalencia recorre los casos actuales del cierre con los mismos `code`, y las suites `test_close_match*` pasan sin cambios.
- Comando: `cd backend && pytest -q tests/test_report_payload_validation.py tests/test_close_match*.py`.
- [x] **T7. Presentar, listar y retirar solicitudes.** RF-001–RF-004, RF-020, RF-023
- Hecho cuando: `test_rectification_flow.py` cubre propuesta válida, inválida (409 con el `code` del cierre y nada registrado), `NO_CHANGES`, `ALREADY_OPEN`, `MATCH_NOT_CONFIRMED`, `TOURNAMENT_ARCHIVED`, retirada solo por el solicitante y 404 entre organizaciones.
- Comando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_rectification_flow.py`.
- [x] **T8. Diferencias y vista previa con `ROLLBACK`.** RF-005
- Hecho cuando: tests puros de `diff.py` y un test de base de datos demuestran que la vista previa devuelve efectos y deja sin cambios las filas de todas las tablas afectadas y la outbox.
- Comando: `cd backend && pytest -q tests/test_rectification_diff.py` y `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_rectification_flow.py`.
- [x] **T9. Decisión de miembro: rechazo y aprobación con versión nueva (sin efectos aún).** RF-006–RF-008, RF-010–RF-013, RNF-003
- Hecho cuando: los tests cubren autoaprobación (403 desde el servicio y desde el trigger), sin permiso (403), motivo vacío (422), `STALE`, dos aprobaciones concurrentes que producen una sola versión, versión 3 sobre la 2 y original intacto.
- Comando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_rectification_flow.py`.
- [x] **T10. Autorización de plataforma y decisión excepcional.** RF-008, RF-009, RF-009b; plan §5.1
- Hecho cuando: los tests cubren conceder (solo `owner`, solo `platform_admin` activo, 422 uniforme), revocar, consumir y la verificación al ejecutar; la ausencia de acceso fuera de la transacción, el registro en `platform_audit_logs` y la autoaprobación de un administrador de plataforma que también es solicitante.
- Comando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_rectification_flow.py tests/test_rectification_platform.py`.

## PR C — Efectos de la publicación

- [x] **T11. Clasificación y desempate por sorteo invalidado.** RF-014
- Hecho cuando: `test_rectification_effects.py` demuestra la clasificación recalculada desde la versión vigente y el efecto `tiebreak_draw_invalidated`.
- Aclaración confirmada: resuelto si el grupo llegó empatado a `random_draw` en la clasificación persistida. Se registra cada grupo anterior sin los mismos integrantes después, con integrantes anteriores y grupos posteriores; se conserva el algoritmo y la semilla existentes, sin nueva persistencia de sorteos.
- Comando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_rectification_effects.py`.
- [x] **T12. Sanciones: crear, anular con registro y cumplimiento desde el siguiente partido.** RF-018, DA-8, D5
- Hecho cuando: los tests cubren la sanción nueva, la anulada que conserva sus cumplimientos, que una sanción nueva no se cumpla en un partido ya comenzado y que la acumulación de amarillas de un partido posterior produzca candidatos tipados de impacto para T14, sin tocar sus sanciones ni persistir un estado transitorio (aclaración aprobada). El trigger impide editar otras columnas de una sanción. La 037 cubre procedencia, fecha original, backfill y conservación del criterio sin fecha.
- Comando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_rectification_sanctions.py tests/test_migration_037.py tests/test_rectification_effects.py tests/test_migration_035.py`.
- [x] **T13. Avance con las condiciones de D4.** RF-015, RF-016; plan §5.2
- Hecho cuando: hay una prueba de sustitución válida (ganador y nuevo perdedor, ambos lados), una de rechazo del trigger por cada condición que falla y candidatos de impacto tipados entregados al hook transaccional de T14, todavía sin apertura. La asignación anterior sigue presente, la nueva y su efecto conservan la trazabilidad, y preview revierte todo. La 038 compara literalmente el guard anterior y comprueba las mismas prohibiciones sin contexto.
- Comando adicional de migración: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL=… pytest -q tests/test_migration_038.py`.
- Comando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_rectification_effects.py`.
- [x] **T14. Procedimiento de impacto: apertura, bloqueo y cierre.** RF-016, RF-017, RF-017b
- Hecho cuando: los tests cubren la apertura por destino comenzado y por fase posterior asignada; abrir un segmento o cerrar el acta de un partido afectado responde 409 `COMPETITIVE_IMPACT_OPEN`, y el cierre `keep_as_played` exige motivo y el permiso de aprobación.
- Comando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL=… DATABASE_ADMIN_URL=… pytest -q tests/test_rectification_effects.py tests/test_migration_039.py`.
- [ ] **T15. Outbox, registro de notificaciones y correo al solicitante.** RF-019, RF-024
- Hecho cuando:
  - se encolan `MATCH_UPDATED`, `STANDINGS_UPDATED` y `MATCH_REPORT_RECTIFIED`, solo para la organización;
  - el worker envía `RECTIFICATION_DECISION_EMAIL` sin incluir la evidencia, y un fallo de SMTP deja el evento en reintento;
  - las notificaciones quedan registradas;
  - `cd backend && pytest -q` y `bandit -r app -ll` pasan.

## PR D — Frontend, documentación y E2E

- [ ] **T16. Workspace: versiones del acta, editor de solicitud, bandeja y revisión.** RF-001, RF-004–RF-006, RF-009, RF-017, RF-020, RNF-006
- Hecho cuando: los tests de componentes y composables, el no mostrar el botón de decisión al solicitante y el i18n ES/EN pasan con `cd frontend && pnpm test && pnpm run typecheck && pnpm run lint && pnpm run build`.
- [ ] **T17. `/admin/rectifications` y marca pública «Resultado rectificado».** RF-009b, RF-022
- Hecho cuando: los tests de la pantalla de administración y de la marca en tarjetas, modal y llave pasan con los mismos comandos de T16, y la marca no muestra motivo ni responsables.
- [ ] **T18. E2E y documentación.** Criterios de finalización 1–9
- Hecho cuando:
  - `e2e/rectification.spec.ts` (solicitar → otro miembro aprueba → marca pública) pasa en el proyecto Workspace;
  - `README.md`, `AGENTS.md` y `docs/manual-usuario.md` describen la nueva vía de corrección;
  - CI del PR en verde, con los cinco jobs.
- Comando: `cd frontend && pnpm exec playwright test e2e/rectification.spec.ts --project workspace` y `git_pr_checks` del PR.
