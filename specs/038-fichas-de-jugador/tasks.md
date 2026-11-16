# Tareas — Spec 038: Fichas públicas de jugador

Estado: aprobadas por el usuario el 2026-11-16 («Apruebo plan, tareas y aclaraciones»). Un PR documental y un PR por bloque: A (T1–T5 backend) y B (T6–T10 frontend, documentación y cierre).

- [x] **T1. Migración 061: `v_public_player_profile_rosters`.** RF-002, RF-003, RF-006, RF-007
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_061.py` en rojo y luego verde; `sh -n infra/postgres/migrate.sh`; cadena limpia 001→061 y salto 060→061 con checksums estables.
  - Evidencia (2026-11-16): `test_migration_061.py` rojo sin la migración y verde después (columnas y orden, `security_barrier`, `SELECT` solo para `bracket_app`, torneo no visible excluido, clave de foto anulada sin consentimiento, organización inactiva excluida, salto 060→061 e idempotencia); `sh -n infra/postgres/migrate.sh` verde. `infra/scripts/test_migrate_target.sh` no se ejecutó en local (sin `psql` en la VM): lo cubre el job `infrastructure` de CI.

- [x] **T2. Funciones puras de la ficha.** RF-003, RF-007, RF-009, RF-010, CL-1–CL-11
- Hecho cuando: `pytest -q tests/test_public_player_profile.py` verde tras confirmarlo en rojo.
  - Evidencia (2026-11-16): `pytest -q tests/test_public_player_profile.py` rojo (módulo inexistente) y luego verde: CL-11, desempates deterministas, consentimiento, orden reciente, tope de 50, foto de la vigente autorizada más reciente y totales.

- [x] **T3. Modelos públicos, `profile_available` y lista cerrada.** RF-005, RF-006
- Hecho cuando: `pytest -q tests/test_public_field_allowlist.py` falla ante una clave extra y pasa con los tres modelos nuevos y el campo en los dos existentes.
  - Evidencia (2026-11-16): `pytest -q tests/test_public_field_allowlist.py` rojo sin los modelos y verde con los tres modelos `extra="forbid"`, `profile_available: StrictBool = False` en `PublicPlayerStatsResponse` y `PublicTimelinePlayerResponse`.

- [x] **T4. Endpoint `GET /tournaments/public/players/{player_id}`.** RF-001, RF-002, RF-004, RF-007, RF-008, RF-011, RNF-001
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_public_player_profile_endpoint.py tests/test_public_access_matrix.py` verde (dos organizaciones, cifras iguales a `player-stats`, rectificación, retiro de consentimiento, inscripción retirada, 404 indistinguible); recuento de rutas 34.
  - Evidencia (2026-11-16): `RUN_DATABASE_TESTS=1 pytest -q tests/test_public_player_profile_endpoint.py tests/test_public_access_matrix.py` verde (14): dos organizaciones, varios torneos de una organización con solo los autorizados y totales, cifras iguales a `player-stats` (también tras rectificación), retiro de consentimiento, inscripción retirada sin foto, torneo no visible y el mismo 404 `Torneo público no encontrado`; `test_tournament_routes_order.py` con 34 rutas.

- [x] **T5. `profile_available` en `player-stats` y `timeline`.** RF-009, CL-1, CL-11
- Hecho cuando: tests de endpoint de ambas rutas verdes con inscripciones con y sin consentimiento; suite completa con PostgreSQL 17 y Redis, `ruff check .` y `bandit -q -r app -ll` verdes.
  - Evidencia (2026-11-16): `test_public_player_profile_endpoint.py` cubre `profile_available` en `player-stats` y `timeline` por torneo (con y sin consentimiento, retirado tras revocarlo, sin filtrarse a otro torneo) y `test_public_timeline.py` el indicador puro; suite completa con PostgreSQL 17 y Redis: 4181 passed, 4 skipped (la única falla, `test_match_live_public.py`, usaba una base desechable hasta la 059 y pasa a la 061); `ruff check .` y `bandit -q -r app -ll` verdes.

- [x] **T6. Página pública `/players/[id]`.** RF-001, RF-002, RF-005, RF-007, RNF-002, RNF-003
- Hecho cuando: `pnpm test -- public-player-profile` verde (cabecera, totales, trayectoria, no encontrado, error, ES/EN, foco); lint y typecheck verdes.
  - Evidencia (2026-11-16): `public-player-profile.test.ts` (8) rojo sin la página y verde después: rutas y UUID, enlace solo con `profile_available === true`, nombre/iniciales/foto fallida, lista cerrada de cinco cifras, carga vía `useApi`/`useAsyncData`, 404 y error con reintento, cabecera/totales/trayectoria/foco y paridad ES/EN; `pnpm run lint` y `pnpm run typecheck` verdes.

- [x] **T7. Enlaces desde estadísticas y cronología.** RF-009, CL-1
- Hecho cuando: `public-stats.test.ts` y `public-timeline.test.ts` verdes: enlace solo con `profile_available`, sin cambio para el resto; navegar cierra el diálogo.
  - Evidencia (2026-11-16): `public-stats.test.ts` y `public-timeline.test.ts` verdes con `NuxtLink` condicional (texto plano sin `profile_available`) para el jugador de la tabla, el del hecho y el que entra en la sustitución, y `@click="close"` antes de navegar.

- [x] **T8. Aviso del consentimiento en el Workspace.** RF-012
- Hecho cuando: test de la plantilla verde con el texto ES/EN junto al control de consentimiento.
  - Evidencia (2026-11-16): `roster-lock.test.ts` verde: `setup.photoConsentProfileNote` junto a los dos controles de consentimiento de `rosters.vue` (alta del jugador, enlazado con `aria-describedby`, y tarjeta de la inscripción), en ES y EN.

- [x] **T9. E2E de la ficha.** RNF-002, RNF-003
- Hecho cuando: `pnpm exec playwright test e2e/public-polish.spec.ts --project public --no-deps` verde con la ficha a 1440/390/800 px en ambos temas y el enlace desde estadísticas; `pnpm run build` verde.
  - Evidencia (2026-11-16): `pnpm exec playwright test e2e/public-polish.spec.ts --project public --no-deps` 36 passed (9 nuevos): ficha a 1440/390/800 px en tema oscuro y claro desde el enlace de estadísticas (cabecera con iniciales tras fallar la foto, cinco totales, tres torneos, foco visible por teclado) y desde la cronología, cerrando el diálogo; `pnpm run build`, `pnpm run typecheck:e2e`, `pnpm run lint` y `pnpm test` (1115 passed) verdes. Contrato ficticio, no la pila real.

- [x] **T10. Documentación y cierre.** RF-012, criterios 1–8
- Hecho cuando: README (matriz y runbook de la 061), AGENTS, manual y matriz 020 coherentes; CI 7/7 verde; trazabilidad RF/RNF/CL con evidencia; `MEMORY.md` actualizado.
  - Evidencia (2026-11-16): README (runbook de la 061, fila de la matriz y tests), AGENTS, manual (ficha y nuevo alcance del consentimiento) y ampliación F16 en la matriz de la 020; CI 7/7 verde en #93, #94 y #95. Trazabilidad: RF-001/002/005/007/008/011 y RNF-001 → `test_public_player_profile_endpoint.py`; RF-003/004/010 y CL-1–CL-11 → `test_public_player_profile.py` y el endpoint (cifras iguales a `player-stats`, también tras rectificación); RF-006 → `test_public_field_allowlist.py`; RF-009 → tests de endpoint de `player-stats`/`timeline`, `public-stats.test.ts` y `public-timeline.test.ts`; RF-012 → `roster-lock.test.ts` y manual; RNF-002/003 → `public-player-profile.test.ts` y E2E `public-polish`; criterios 1–8 cubiertos por las anteriores. No ejecutado: la ficha contra la pila real (el E2E usa contrato ficticio), un lector de pantalla real e `infra/scripts/test_migrate_target.sh` en local (sin `psql`; lo cubre el job `infrastructure`).
