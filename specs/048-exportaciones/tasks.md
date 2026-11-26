# Tareas — Spec 048: Exportaciones CSV (F10)

Estado: aprobado por el usuario el 2026-11-25 («Apruebo el plan y las tareas. Empieza por T1»).

## Bloque A — backend (PR apilado sobre el #130)

- [x] **T1. Catálogo y formato CSV.** RF-001–RF-003, RNF-001–RNF-003
- Hecho cuando: `exports/catalog.py` y `exports/csv_format.py` siguen el plan §3; `cd backend && pytest -q tests/test_export_csv.py` pasa tras ver fallar primero los tests nuevos; `ruff check .` limpio.
- Evidencia (2026-11-25): `tests/test_export_csv.py` falló primero en la colección (`ModuleNotFoundError: app.modules.exports`) y ahora pasa 45/45; `ruff check .`, `bandit -r app/modules/exports -ll` y `compileall` limpios.
- [x] **T2. Construcción de filas.** RF-001, RF-002, RF-004
- Hecho cuando: `exports/builders.py` sigue el plan §3 (columnas y orden, CL-3, CL-4 y CL-7, sin claves prohibidas); `cd backend && pytest -q tests/test_export_builders.py` pasa tras ver fallar primero los tests nuevos.
- Evidencia (2026-11-25): `tests/test_export_builders.py` falló primero en la colección (`cannot import name 'builders'`) y ahora pasa 25/25 (70/70 con `test_export_csv.py`); `ruff check .`, `bandit -r app/modules/exports -ll` y `compileall` limpios. El acta lleva en «Resultado» una fila por equipo con sus goles, otra por equipo con los penales si los hay y una fila con la resolución y su motivo; el minuto añadido se escribe `45+2`.
- [x] **T3. Exportaciones de clasificación, calendario y estadísticas.** RF-001, RF-002, RF-004, RF-005, RF-008, RNF-003
- Hecho cuando: `service.py` y `router.py` sirven `standings`, `calendar`, `player-stats` y `team-stats`, registrados en `main.py`; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_exports_api.py` pasa (cross-tenant con el mismo 404, observador, CL-1, CL-6, límite → 422) tras ver fallar primero los casos nuevos.
- Evidencia (2026-11-25): `tests/test_exports_api.py` falló primero (24 de 25 casos; la ruta no existía) y ahora pasa 25/25 con PostgreSQL real. La suite backend sin BD pasa 3379 (sin `test_config`, por las variables de Google del `.env` local); `ruff check .`, `bandit -r app/modules/exports -ll` y `compileall` limpios. `test_tournament_routes_order.py` excluye la ruta de exportaciones del inventario de 44 operaciones del módulo de torneos, igual que el escudo. Las estadísticas de jugadores atribuyen el equipo con la inscripción vigente primero.
- [x] **T4. Exportación de plantillas con auditoría.** RF-001, RF-004, RF-007
- Hecho cuando: `rosters` y `audit.py` siguen el plan; `EXPORT_TOURNAMENT_ROSTERS` está en el catálogo de la 041 y en el espejo del frontend con textos ES/EN; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_exports_api.py tests/test_organization_audit_catalog.py tests/test_organization_audit_routes.py tests/test_audit_frontend.py` y `cd frontend && pnpm test` pasan tras ver fallar primero los casos nuevos.
- Evidencia (2026-11-25): primero fallaron 8 casos de `tests/test_exports_api.py`, 2 de `tests/test_organization_audit_catalog.py` y la paridad de `frontend/tests/organization-audit.test.ts`; ahora pasan con PostgreSQL real 164/164 (`test_exports_api.py`, catálogo, rutas de auditoría y tests puros de exportación). El espejo del frontend lo vigila `organization-audit.test.ts` (`tests/test_audit_frontend.py` es el test de `pnpm audit`, no de la 041). Frontend: `pnpm test` 1262/0, typecheck y lint limpios. Backend sin BD 3380; `ruff check .`, Bandit y compileall limpios. La entrada de auditoría muestra «Torneo» sin enlace (`entity_available` sigue en falso para `tournaments`).
- [x] **T5. Exportación del acta.** RF-001, RF-004–RF-006, RF-008
- Hecho cuando: `GET /matches/{id}/export` sigue el plan (409 si no está cerrado, versión vigente tras rectificación, W.O. sin hechos, oficiales sin correo); `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_exports_api.py` pasa tras ver fallar primero los casos nuevos.
- Evidencia (2026-11-25): primero fallaron 10 casos nuevos de `tests/test_exports_api.py` (la ruta no existía) y 4 puros del motivo del W.O.; ahora `test_exports_api.py` pasa 43/43 con PostgreSQL real y los puros 73/73. Backend sin BD 3384; `ruff check .`, Bandit y compileall limpios. El motivo del W.O. se traduce con el catálogo de la 027 (`no_show` → «Incomparecencia»/«No-show»); el de una resolución administrativa se copia tal cual. Los oficiales salen ordenados por función.
- [x] **T6. Validación del bloque A y PR.** Todos los RF del bloque
- Hecho cuando: la suite backend con BD, `ruff check .`, `bandit -r app -ll` y `python -m compileall -q app` están limpios; PR del bloque A con la CI en verde.
- Evidencia (2026-11-25): suite backend con BD 4943 en local (sin `test_config`, por las variables de Google del `.env` local); `ruff check .`, `bandit -r app -ll` y `compileall -q app` limpios. PR #131 con la CI 7/7. Devin Review encontró que una rectificación confirmada a mitad de la descarga podía mezclar el marcador de una versión con los hechos de otra: cada exportación abre ahora su transacción en `REPEATABLE READ` (dos tests de regresión, que fallaron primero; `test_exports_api.py` 45/45).

## Bloque B — Workspace, E2E y documentación (PR apilado sobre el bloque A)

- [x] **T7. Utilidades, composable y textos.** RF-001, RF-006, RNF-003, RNF-005
- Hecho cuando: `utils/exports.ts`, `useExports` y las claves `export.*` ES/EN siguen el plan §5; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios tras ver fallar primero los tests nuevos.
- Evidencia (2026-11-25): `frontend/tests/exports.test.ts` falló primero (no existía `utils/exports.ts`) y ahora pasa 12/12: espejo de tipos, `REPORT_KIND` y `MAX_ROWS` del backend, rutas, nombre de archivo ASCII con la fecha como parámetro, errores (también con el cuerpo como `Blob`), una descarga a la vez, respuesta descartada tras cambiar de organización, solo `useApi` y paridad ES/EN de `export.*`. `pnpm test` 1274/0, typecheck y lint limpios. El guardado del archivo va en `utils/exportDownload.ts` (`saveExportFile`), aparte de las funciones puras.
- [ ] **T8. Página «Exportaciones» y botón del acta.** RF-001, RF-006, RF-007, RNF-005
- Hecho cuando: la página `/workspace/tournaments/[id]/exports`, su enlace en `WorkspaceShell` y el botón del acta en el partido siguen el plan §5; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios tras ver fallar primero los tests nuevos.
- [ ] **T9. E2E, documentación y validación.** RNF-004, RNF-005
- Hecho cuando: `e2e/exports.spec.ts` pasa con axe sin violaciones en ambos temas a 1440 y 390 px; README, AGENTS, manual (sección «Exportaciones» con las columnas), informe y MEMORY actualizados; `pnpm run build`, `pnpm run typecheck:e2e` y la suite backend con BD pasan; PR del bloque B con la CI en verde.
