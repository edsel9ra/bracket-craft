# Tareas — Spec 037: Cronología pública del partido

Estado: aprobadas por el usuario el 2026-11-15 («Apruebo plan y tareas»). Un solo PR por bloque: A (T1–T4 backend) y B (T5–T10 frontend, documentación y cierre).

- [x] **T1. Migración 060: `segment_id` en `v_public_match_events`.** RF-005, RF-009, RF-016
- Hecho cuando: `test_migration_060.py` en rojo y luego verde con `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_060.py`; `sh -n infra/postgres/migrate.sh`; cadena limpia 001→060 y salto 059→060 con checksums estables.
- Evidencia: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_060.py tests/test_migration_030.py` → 11 passed (PostgreSQL 17); `infra/scripts/test_migrate_target.sh` OK; `sh -n infra/postgres/migrate.sh` OK; `pytest -q` → 2933 passed, 1188 skipped; `ruff check .` limpio.

- [x] **T2. Funciones puras de la cronología.** RF-002, RF-003, RF-005–RF-012
- Hecho cuando: `cd backend && pytest -q tests/test_public_timeline.py` verde tras confirmarlo en rojo, cubriendo CL-1–CL-14 aplicables.
- Evidencia: `pytest -q tests/test_public_timeline.py` → 34 passed (disponibilidad, tipos, orden estable, roja, autogol, sustitución, huérfanos, marcador con prórroga/penales); `ruff check` limpio.

- [ ] **T3. Modelos públicos y lista cerrada.** RF-007, RF-015
- Hecho cuando: `pytest -q tests/test_public_field_allowlist.py` falla ante una clave extra y pasa con los tres modelos nuevos.

- [ ] **T4. Endpoint `GET /tournaments/public/{tournament_id}/matches/{match_id}/timeline`.** RF-001, RF-004, RF-013, RF-016
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_public_timeline_endpoint.py tests/test_public_access_matrix.py` verde (dos organizaciones, rectificación, anulados, 404 indistinguible); `pytest -q`, `ruff check .` y `bandit -q -r app -ll` verdes.

- [ ] **T5. Utilidades frontend `utils/publicTimeline.ts`.** RF-008, RF-009, RF-014
- Hecho cuando: `cd frontend && pnpm test` incluye `public-timeline.test.ts` (minuto, separadores, clave por tipo/roja, decisión de recarga) en verde.

- [ ] **T6. Componente `PublicMatchTimeline.vue` e i18n ES/EN.** RF-007, RF-008, RF-012, RNF-002
- Hecho cuando: pruebas del componente (estados, nombres accesibles, foco, ambos idiomas) verdes; `pnpm run lint` y `pnpm run typecheck` verdes; `design-scales.test.ts` sin excepciones nuevas.

- [ ] **T7. Integración en `/tournaments/{id}` y recarga.** RF-001, RF-002, RF-013, RF-014
- Hecho cuando: pruebas de la página verifican el disparador solo en `finished`, la carga vía `useApi` y la recarga del diálogo abierto al cambiar `status`, marcador o `rectified_at`; `pnpm test` y `pnpm run build` verdes.

- [ ] **T8. E2E público de la cronología.** RNF-002, CL-9, CL-13
- Hecho cuando: `pnpm run typecheck:e2e` verde y `public-polish.spec.ts` ejecutado con el diálogo a 1440/390 px en ambos temas, sin desbordamiento (en CI o en contenedor Playwright 1.65).

- [ ] **T9. Documentación: matriz de acceso, AGENTS, manual y 020.** RF-017
- Hecho cuando: README (matriz y runbook 060), `AGENTS.md`, `docs/manual-usuario.md` y la referencia en la spec 020 describen la ruta, la lista cerrada y el cambio no aditivo; pruebas de coherencia documental verdes.

- [ ] **T10. Validación y cierre.** Criterios de finalización 1–8
- Hecho cuando: los cinco jobs de CI pasan en el PR, cada RF/CL tiene evidencia citada en este archivo, la verificación de constitución está confirmada y `MEMORY.md` actualizado; lo no ejecutado se declara.
