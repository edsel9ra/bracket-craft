# Tareas — Spec 040: Avance automático entre fases (F2)

Estado: aprobadas por el usuario el 2026-11-16. PR documental y un PR por bloque: A (T1–T6, migración y backend) y B (T7–T11, frontend, E2E, documentación y cierre).

## Bloque A

- [x] **T1. Migración 063.** RF-003, RF-007, RNF-002, RNF-003
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_063.py` en rojo y luego verde (CHECK con `stage_rank`, RLS/FORCE y políticas, `UNIQUE (stage_id)`, append-only, excepción solo para `INSERT` en `stage_teams` con resolución válida, rechazo con resolución de otra fase u organización); cadena limpia 001→063 y salto 062→063; `sh -n infra/postgres/migrate.sh`.
- Evidencia: sin la 063, `test_migration_063.py` en rojo (14 failed); con ella, 14 passed contra PostgreSQL 17: RLS `ENABLE`+`FORCE` con una política, `bracket_app` solo `SELECT, INSERT`, trigger sin `SECURITY DEFINER`, vista `security_barrier` solo para `bracket_app`; ocho referencias `stage_rank` mal formadas rechazadas (el primer verde destapó que un CHECK con `NULL` pasaba: se envolvió en `COALESCE(..., FALSE)`); en lo publicado `stage_teams` solo admite, con `app.stage_slot_resolution_id`, equipos de esa resolución y fase, sin grupo y sin duplicar; `DELETE` sigue en 409; segunda resolución rechazada por `UNIQUE`; resolución solo para llaves de versión publicada; asignación `stage_rank` exige su resolución; la vista solo etiqueta plazas sin resolver de torneos visibles; salto 062→063 aplicado dos veces. `sh -n infra/postgres/migrate.sh` correcto. Regresión 019, 035, 038 y 062 en verde.

- [x] **T2. Funciones puras.** RF-002, RF-006, RF-008, RF-012, RF-013, CL-1, CL-2, CL-7, CL-8
- Hecho cuando: `cd backend && pytest -q tests/test_stage_slot_origins.py` en rojo y luego verde (validación, plantilla clásica, cabezas de serie y pases libres, mejores N.º sin enfrentamiento directo, empates no resolubles, huella estable, fase terminada).
- Evidencia: `test_stage_slot_origins.py` en rojo (módulo inexistente) y luego 43 passed: `seed_order`/`first_round_pairs` (1 contra N, pases libres a las cabezas altas), `validate_origins` con un código por plaza (fase no válida, grupo obligatorio o inexistente, posición u ordinal fuera de rango, grupos desiguales, origen duplicado o solapado entre «N.º del grupo» y «mejores N.º» de la misma posición), `classic_template` (1.º A contra 2.º B, 1.º B contra 2.º A…, sin cruces del mismo grupo en 3×4, 4×4, 6×4 y 3+4, pases libres a primeros, `unequal_groups`/`not_enough_teams`), `resolve_slots` (empate no resoluble solo en la plaza afectada, «mejores N.º» sin enfrentamiento directo y con sorteo determinista de clave propia, fase sin terminar, equipo descalificado, tamaño de grupo cambiado) y `standings_fingerprint` estable al reordenar y sensible a cifras, estados de equipo y partidos. El orden por criterios se extrajo de `StandingsService` a `standings/ranking.py` (`rank_buckets`) sin cambiar su resultado: `test_standings_head_to_head.py`, `test_lock_order.py`, `test_rectification_effects.py`, `test_rectification_readers.py`, `test_concurrency_006.py` y `test_public_stats_endpoints.py` en verde (132 passed con base).

- [x] **T3. Declarar orígenes y generar la llave en borrador.** RF-001, RF-001b, RF-002, RF-003, RF-011, CL-5
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_stage_advancement_routes.py -k origins` en rojo y luego verde: borrador 200, publicado 409, 422 por plaza, doble eliminación solo con potencia de dos, avance manual y sorteo 409 en llave con orígenes.
- Evidencia: `tests/test_stage_advancement_routes.py -k origins` 9 failed sin el código (rutas inexistentes) → 9 passed contra PostgreSQL 17. Llave generada con plazas `stage_rank` vacías (1 contra 4, 2 contra 3; pases libres a las cabezas de serie), doble eliminación solo con potencia de dos y orígenes solo en el cuadro de ganadores, 422 por plaza sin escrituras ni eco del valor, publicado 409 y estado `frozen`, asignación manual y sorteo 409. Añadido `DELETE slot-origins` (solo borrador) para volver al avance manual. Suite completa con BD: 4318 passed, 4 skipped; ruff limpio. Inventarios actualizados: 50 operaciones JSON/62 modelos estrictos (019) y 38 rutas de torneo.

- [ ] **T4. Vista previa.** RF-004, RF-005, RF-006, RF-012, RF-013, CL-2, CL-3, CL-4
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_stage_advancement_routes.py -k preview` en rojo y luego verde: sin escrituras, motivos por plaza y número de consultas constante (RNF-001).

- [ ] **T5. Confirmación.** RF-007, RF-008, RF-009, RNF-002
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_stage_advancement_routes.py -k resolution` en rojo y luego verde: llena todo o nada, 409 por huella obsoleta o ya resuelta, carrera de dos confirmaciones → una, auditoría `STAGE_SLOTS_RESOLVED` y `MATCH_UPDATED` por partido, 404 entre organizaciones.

- [ ] **T6. Clonado, rectificación y lectura pública.** RF-010, CL-6, §8 del plan
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_stage_advancement_routes.py -k "clone or rectification or public"` en rojo y luego verde (el clon reasigna IDs, una rectificación posterior abre `later_phase` sin cambiar plazas, `home_origin`/`away_origin` solo en plazas sin resolver); después `cd backend && RUN_DATABASE_TESTS=1 pytest -q`, `python -m compileall -q app`, `ruff check .` y `bandit -r app -ll` en verde.

## Bloque B

- [ ] **T7. Editor de orígenes en el borrador.** RF-001, RF-001b, RF-002, RNF-004
- Hecho cuando: `cd frontend && pnpm test -- stage-advancement` en rojo y luego verde (modelo puro, etiquetas ES/EN, aceptar/editar la plantilla, errores por plaza del 422, sin guardar sin acción del gestor); `pnpm run typecheck` y `pnpm run lint` en verde.

- [ ] **T8. Panel de resolución en lo publicado.** RF-004–RF-008, RNF-004
- Hecho cuando: `cd frontend && pnpm test -- stage-advancement` verde con los casos del panel (vista previa por plaza, motivos de bloqueo, confirmación con `useConfirm` y `singleFlight`, 409 que pide una nueva vista previa); `pnpm run typecheck` y `pnpm run lint` en verde.

- [ ] **T9. Etiqueta de origen en la llave pública.** RF-009, §8 del plan
- Hecho cuando: `cd frontend && pnpm test -- public-bracket` en rojo y luego verde (etiqueta ES/EN solo en plazas sin resolver, nombre del equipo al llenarse); `pnpm run typecheck` en verde.

- [ ] **T10. E2E.** RNF-004, criterios 1–4
- Hecho cuando: `cd frontend && pnpm exec playwright test e2e/stage-advancement.spec.ts --project workspace` y `pnpm exec playwright test e2e/public-polish.spec.ts --project public --no-deps` en verde a 1440/390 px en los dos temas, con axe sin violaciones; `pnpm run typecheck:e2e` en verde.

- [ ] **T11. Documentación y cierre.** Criterios de finalización
- Hecho cuando: runbook de la 063 en README, AGENTS, manual, matriz de la 020 y MEMORY actualizados; evidencia por RF, RNF y CL en este archivo; `cd frontend && pnpm test && pnpm run typecheck && pnpm run build && pnpm run lint`, la suite backend completa y el CI de los PR (7/7) en verde.
