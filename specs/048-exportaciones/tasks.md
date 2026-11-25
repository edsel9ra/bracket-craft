# Tareas — Spec 048: Exportaciones CSV (F10)

Estado: aprobado por el usuario el 2026-11-25 («Apruebo el plan y las tareas. Empieza por T1»).

## Bloque A — backend (PR apilado sobre el #130)

- [x] **T1. Catálogo y formato CSV.** RF-001–RF-003, RNF-001–RNF-003
- Hecho cuando: `exports/catalog.py` y `exports/csv_format.py` siguen el plan §3; `cd backend && pytest -q tests/test_export_csv.py` pasa tras ver fallar primero los tests nuevos; `ruff check .` limpio.
- Evidencia (2026-11-25): `tests/test_export_csv.py` falló primero en la colección (`ModuleNotFoundError: app.modules.exports`) y ahora pasa 45/45; `ruff check .`, `bandit -r app/modules/exports -ll` y `compileall` limpios.
- [ ] **T2. Construcción de filas.** RF-001, RF-002, RF-004
- Hecho cuando: `exports/builders.py` sigue el plan §3 (columnas y orden, CL-3, CL-4 y CL-7, sin claves prohibidas); `cd backend && pytest -q tests/test_export_builders.py` pasa tras ver fallar primero los tests nuevos.
- [ ] **T3. Exportaciones de clasificación, calendario y estadísticas.** RF-001, RF-002, RF-004, RF-005, RF-008, RNF-003
- Hecho cuando: `service.py` y `router.py` sirven `standings`, `calendar`, `player-stats` y `team-stats`, registrados en `main.py`; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_exports_api.py` pasa (cross-tenant con el mismo 404, observador, CL-1, CL-6, límite → 422) tras ver fallar primero los casos nuevos.
- [ ] **T4. Exportación de plantillas con auditoría.** RF-001, RF-004, RF-007
- Hecho cuando: `rosters` y `audit.py` siguen el plan; `EXPORT_TOURNAMENT_ROSTERS` está en el catálogo de la 041 y en el espejo del frontend con textos ES/EN; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_exports_api.py tests/test_organization_audit_catalog.py tests/test_organization_audit_routes.py tests/test_audit_frontend.py` y `cd frontend && pnpm test` pasan tras ver fallar primero los casos nuevos.
- [ ] **T5. Exportación del acta.** RF-001, RF-004–RF-006, RF-008
- Hecho cuando: `GET /matches/{id}/export` sigue el plan (409 si no está cerrado, versión vigente tras rectificación, W.O. sin hechos, oficiales sin correo); `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_exports_api.py` pasa tras ver fallar primero los casos nuevos.
- [ ] **T6. Validación del bloque A y PR.** Todos los RF del bloque
- Hecho cuando: la suite backend con BD, `ruff check .`, `bandit -r app -ll` y `python -m compileall -q app` están limpios; PR del bloque A con la CI en verde.

## Bloque B — Workspace, E2E y documentación (PR apilado sobre el bloque A)

- [ ] **T7. Utilidades, composable y textos.** RF-001, RF-006, RNF-003, RNF-005
- Hecho cuando: `utils/exports.ts`, `useExports` y las claves `export.*` ES/EN siguen el plan §5; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios tras ver fallar primero los tests nuevos.
- [ ] **T8. Página «Exportaciones» y botón del acta.** RF-001, RF-006, RF-007, RNF-005
- Hecho cuando: la página `/workspace/tournaments/[id]/exports`, su enlace en `WorkspaceShell` y el botón del acta en el partido siguen el plan §5; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios tras ver fallar primero los tests nuevos.
- [ ] **T9. E2E, documentación y validación.** RNF-004, RNF-005
- Hecho cuando: `e2e/exports.spec.ts` pasa con axe sin violaciones en ambos temas a 1440 y 390 px; README, AGENTS, manual (sección «Exportaciones» con las columnas), informe y MEMORY actualizados; `pnpm run build`, `pnpm run typecheck:e2e` y la suite backend con BD pasan; PR del bloque B con la CI en verde.
