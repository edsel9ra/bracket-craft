# Tareas — Spec 049: Roles por torneo (F7)

Estado: aprobado por el usuario el 2026-11-26 («Apruebo el plan y las tareas, empieza por T1»).

## Bloque A — backend (PR apilado sobre el #133)

- [x] **T1. Migración 069.** RF-001, RF-005–RF-007, RF-011
- Hecho cuando: `069_tournament_roles.sql` sigue el plan §3; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_069.py` pasa tras ver fallar primero los tests nuevos; reaplicar la 069 no cambia nada; `sh -n infra/postgres/migrate.sh`.
- Evidencia (2026-11-26): `tests/test_migration_069.py` falló primero (`UndefinedTableError: tournament_member_roles`) y ahora pasa 16/16 (volumen limpio y migrado desde la 068, reaplicación idempotente, RLS forzado, privilegios sin `UPDATE`, aislamiento, FK compuestas, unicidad, rol cerrado, cascadas, desactivación y reactivación, `match_live_has_permission` y `sanction_can_operate_match`). Con la 069 aplicada pasan 629 tests de partido en vivo, sanciones y migraciones 040/056. `sh -n infra/postgres/migrate.sh`, `ruff check .`, `bandit -r app -ll` y `compileall` limpios.
- [x] **T2. Catálogo y autorización por partido.** RF-001, RF-001a, RF-002, RF-008, RF-009
- Hecho cuando: `tournament_roles/catalog.py` y la rama de `require_permission` siguen D2 y D4; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_tournament_roles_catalog.py tests/test_tournament_roles_authorization.py tests/test_permissions_signature.py` pasa tras ver fallar primero los casos nuevos (alineación, segmentos y cierre con sanción en A; 403 en B, en la resolución administrativa y en `MANAGE_TOURNAMENTS`; desactivado y reactivado).
- Evidencia (2026-11-26): fallaron primero los casos nuevos (módulo `tournament_roles` inexistente; 4 de la rama en `test_permissions_signature.py`; 7 de 8 en `test_tournament_roles_authorization.py`, incluidos alineación y segmento en A) y ahora pasan 40/40 contra PostgreSQL real. La rama solo consulta `tournament_operator_allows` con `match_id`, sin `role_codes` y para los tres permisos; la resolución administrativa, `MANAGE_TOURNAMENTS` y la asignación de oficiales siguen en 403. Suite backend completa con base de datos: 4963 pasan; los 27 que fallaron eran dobles o esquemas de test anteriores a la 069 (`test_close_validation_order.py` responde a la consulta nueva; dos tests de `readers` se ejecutan con `last=69`) y ahora pasan 209/209. `ruff check .`, `bandit -r app -ll` y `compileall` limpios.
- [ ] **T3. En vivo y tiempo real.** RF-004, RF-008, RF-010
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_tournament_roles_live.py tests/test_realtime_policy.py` pasa tras ver fallar primero los casos nuevos (`/live/access`, comando aceptado, 403 tras retirar, `ALLOW` → `DENY` en `authorize_realtime_recipients`, espejo puro).
- [ ] **T4. Endpoints «Equipo del torneo» y auditoría.** RF-003–RF-006, RF-003a, RF-011–RF-013
- Hecho cuando: el router está en `main.py` y sigue el plan §4–§5; las dos acciones están en el catálogo de la 041; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_tournament_roles_api.py tests/test_organization_audit_catalog.py` pasa tras ver fallar primero los casos nuevos; `operated_tournament_ids` en el acceso.
- [ ] **T5. Validación del bloque A y PR.** Todos los RF del bloque
- Hecho cuando: la suite backend con BD, `ruff check .`, `bandit -r app -ll` y `python -m compileall -q app` están limpios; volumen limpio y migrado verificados; PR del bloque A con la CI en verde.

## Bloque B — Workspace, E2E y documentación (PR apilado sobre el bloque A)

- [ ] **T6. Utilidades, composable, textos y operación.** RF-012, RF-012a, RNF-002
- Hecho cuando: `utils/tournamentTeam.ts`, `useTournamentTeam`, el uso de `canOperateMatch` en `useMatchOperationState`, las claves ES/EN y el espejo de auditoría siguen el plan §6; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios tras ver fallar primero los tests nuevos.
- [ ] **T7. Página «Equipo del torneo» y navegación.** RF-003b, RF-012, RNF-002, RNF-003
- Hecho cuando: `pages/workspace/tournaments/[id]/team.vue` y la entrada de navegación siguen el plan §6 (aviso DA-4, alta solo con `MANAGE_MEMBERS`, retirada con `useConfirm({ singleFlight: true })`); `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios tras ver fallar primero los tests nuevos.
- [ ] **T8. E2E, documentación y validación.** RNF-001–RNF-003
- Hecho cuando: `e2e/tournament-team.spec.ts` pasa con axe sin violaciones en ambos temas a 1440 y 390 px; README, AGENTS, manual (sección «Equipo del torneo»), informe (F7) y MEMORY actualizados; `pnpm run build`, `pnpm run typecheck:e2e` y la suite backend con BD pasan; PR del bloque B con la CI en verde.
