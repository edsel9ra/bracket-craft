# Tareas — Spec 038: Fichas públicas de jugador

Estado: aprobadas por el usuario el 2026-11-16 («Apruebo plan, tareas y aclaraciones»). Un PR documental y un PR por bloque: A (T1–T5 backend) y B (T6–T10 frontend, documentación y cierre).

- [ ] **T1. Migración 061: `v_public_player_profile_rosters`.** RF-002, RF-003, RF-006, RF-007
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_061.py` en rojo y luego verde; `sh -n infra/postgres/migrate.sh`; cadena limpia 001→061 y salto 060→061 con checksums estables.

- [ ] **T2. Funciones puras de la ficha.** RF-003, RF-007, RF-009, RF-010, CL-1–CL-11
- Hecho cuando: `pytest -q tests/test_public_player_profile.py` verde tras confirmarlo en rojo.

- [ ] **T3. Modelos públicos, `profile_available` y lista cerrada.** RF-005, RF-006
- Hecho cuando: `pytest -q tests/test_public_field_allowlist.py` falla ante una clave extra y pasa con los tres modelos nuevos y el campo en los dos existentes.

- [ ] **T4. Endpoint `GET /tournaments/public/players/{player_id}`.** RF-001, RF-002, RF-004, RF-007, RF-008, RF-011, RNF-001
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_public_player_profile_endpoint.py tests/test_public_access_matrix.py` verde (dos organizaciones, cifras iguales a `player-stats`, rectificación, retiro de consentimiento, inscripción retirada, 404 indistinguible); recuento de rutas 34.

- [ ] **T5. `profile_available` en `player-stats` y `timeline`.** RF-009, CL-1, CL-11
- Hecho cuando: tests de endpoint de ambas rutas verdes con inscripciones con y sin consentimiento; suite completa con PostgreSQL 17 y Redis, `ruff check .` y `bandit -q -r app -ll` verdes.

- [ ] **T6. Página pública `/players/[id]`.** RF-001, RF-002, RF-005, RF-007, RNF-002, RNF-003
- Hecho cuando: `pnpm test -- public-player-profile` verde (cabecera, totales, trayectoria, no encontrado, error, ES/EN, foco); lint y typecheck verdes.

- [ ] **T7. Enlaces desde estadísticas y cronología.** RF-009, CL-1
- Hecho cuando: `public-stats.test.ts` y `public-timeline.test.ts` verdes: enlace solo con `profile_available`, sin cambio para el resto; navegar cierra el diálogo.

- [ ] **T8. Aviso del consentimiento en el Workspace.** RF-012
- Hecho cuando: test de la plantilla verde con el texto ES/EN junto al control de consentimiento.

- [ ] **T9. E2E de la ficha.** RNF-002, RNF-003
- Hecho cuando: `pnpm exec playwright test e2e/public-polish.spec.ts --project public --no-deps` verde con la ficha a 1440/390/800 px en ambos temas y el enlace desde estadísticas; `pnpm run build` verde.

- [ ] **T10. Documentación y cierre.** RF-012, criterios 1–8
- Hecho cuando: README (matriz y runbook de la 061), AGENTS, manual y matriz 020 coherentes; CI 7/7 verde; trazabilidad RF/RNF/CL con evidencia; `MEMORY.md` actualizado.
