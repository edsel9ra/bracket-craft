# Tareas — Spec 041: Auditoría organizacional visible (F5)

Estado: borrador pendiente de aprobación. PR documental (este) y un PR por bloque: A (T1–T3, migración y backend) y B (T4–T7, frontend, E2E, documentación y cierre).

## Bloque A

- [ ] **T1. Migración 064.** RF-001, RF-013, RNF-001
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_064.py` en rojo y luego verde: `VIEW_ORGANIZATION_AUDIT` solo en `owner` y `administrator` (definiciones, roles existentes y organización creada después), índice presente, idempotencia (aplicar dos veces), cadena limpia 001→064 y salto 063→064; `sh -n infra/postgres/migrate.sh`.

- [ ] **T2. Catálogo puro.** RF-007, RF-008
- Hecho cuando: `cd backend && pytest -q tests/test_organization_audit_catalog.py` en rojo y luego verde: proyección por cada acción, omisión de campos ausentes o de tipo distinto, recorte a 1000 caracteres, nombres de miembro, `None` para acciones desconocidas, catálogo sin rutas sensibles e inventario de todas las acciones escritas en `administrative_audit_logs`.

- [ ] **T3. Endpoints de consulta.** RF-001 a RF-006, RF-009, RF-012, RNF-001, RNF-002, RNF-004
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_organization_audit_routes.py` en rojo y luego verde (casos de §6 del plan); inventario de esquemas estrictos de la 019 actualizado; `pytest -q`, `python -m compileall -q app`, `ruff check .` y `bandit -r app -ll` limpios.

## Bloque B

- [ ] **T4. Utilidades y composable.** RF-004, RF-006, RF-007, RF-008, RF-012
- Hecho cuando: `cd frontend && pnpm test -- organization-audit` en rojo y luego verde: etiquetas ES/EN de todas las acciones del catálogo y «Acción no catalogada», conversión de fechas a UTC inclusiva, query de filtros, enlaces según `entity_available` y `VIEW_SANCTION_CASES`, descarte de respuestas al cambiar de organización o de usuario y llamadas solo por `useApi`.

- [ ] **T5. Pantalla y menú.** RF-006, RF-007, RF-008, RF-010, RF-011, RF-012, RNF-003
- Hecho cuando: `cd frontend && pnpm test` en verde con tests nuevos de la página (carga, vacío distinto de error, sin permiso, paginación, diálogo de detalle con foco gestionado) y de `workspace-layout.test.ts` (enlace solo con el permiso); `pnpm run typecheck`, `pnpm run lint` y `pnpm run build` limpios; `design-scales.test.ts` sin excepciones nuevas.

- [ ] **T6. E2E y accesibilidad.** RNF-003, HU-1–HU-3
- Hecho cuando: `cd frontend && pnpm exec playwright test e2e/organization-audit.spec.ts --project workspace` en verde con contratos ficticios: filtros en la URL, paginación, tabla y diálogo de detalle por teclado (foco de entrada y de vuelta, Escape), enlaces, axe sin violaciones en ambos temas a 1440 y 390 px.

- [ ] **T7. Documentación y validación.** Criterios de finalización
- Hecho cuando: README (permiso, endpoint y runbook de la 064), AGENTS, `docs/manual-usuario.md` y MEMORY actualizados; cinco jobs de CI en verde en el PR del bloque B; cada RF y criterio de finalización con su evidencia anotada en esta tarea.
