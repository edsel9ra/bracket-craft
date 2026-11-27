# Tareas — Spec 050: Exportaciones PDF (F10, parte 2)

Estado: borrador, pendiente de aprobación junto con el plan.

## Bloque A — Backend (un PR)

- [ ] **T1. Dependencia, fuentes y renderizador puro.** RF-002, RNF-001–RNF-005, RNF-008
- Hecho cuando: `reportlab` y `charset-normalizer` fijados en `backend/requirements.txt` y `pypdf` en `requirements-dev.txt`; fuentes TTF y su licencia en `modules/exports/fonts/` (D2); `pdf_format.py` con `render_pdf`; `tests/test_export_pdf.py` falla primero y luego pasa con `cd backend && pytest -q tests/test_export_pdf.py`; `pip-audit -r requirements.txt -r requirements-dev.txt` sin hallazgos.
- [ ] **T2. PDF de la clasificación.** RF-001–RF-005, RF-007, RF-008, CL-1, CL-6
- Hecho cuando: `pdf_layout.standings_document`, `ExportService.export_standings_pdf` y `GET /tournaments/{id}/exports/standings/pdf`; tests puros de agrupación e igualdad con el CSV y casos de `tests/test_exports_api.py` (200, mismo 404 ajeno, observador, sin auditoría, 422 por límite) en rojo primero y en verde con `RUN_DATABASE_TESTS=1`.
- [ ] **T3. PDF del acta.** RF-001–RF-008, CL-2, CL-3
- Hecho cuando: `pdf_layout.match_report_document`, `ExportService.export_match_report_pdf` y `GET /matches/{id}/export/pdf`; tests de 409 sin cerrar, rectificado, W.O. sin hechos, ausencia de documento, fecha de nacimiento, edad y correo, y mismo 404 ajeno, en rojo primero y en verde con `RUN_DATABASE_TESTS=1`.
- [ ] **T4. Suite completa y PR del bloque A.** RNF-008
- Hecho cuando: suite backend completa con BD, `ruff check .`, `bandit -r app -ll` y `python -m compileall -q app` limpios; PR del bloque A con la CI en verde (incluidos `pip-audit` y Trivy).

## Bloque B — Workspace, E2E y documentación (otro PR, apilado sobre el A)

- [ ] **T5. Utilidades, composable y textos.** RF-003, RNF-007
- Hecho cuando: `utils/exports.ts` (formato, rutas PDF, nombre `.pdf`, espejo de `PDF_KINDS`), `useExports` con tipo y formato, y claves ES/EN; tests en rojo primero y `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios.
- [ ] **T6. Botones PDF en «Exportaciones» y en el acta.** RF-003, RF-006, RNF-007
- Hecho cuando: botón «Descargar PDF» en la fila de la clasificación y «Descargar acta (PDF)» en el partido cerrado; tests de componentes en rojo primero y `pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios.
- [ ] **T7. E2E, documentación y validación.** RNF-001–RNF-008
- Hecho cuando: `e2e/exports.spec.ts` ampliado pasa con axe sin violaciones en ambos temas a 1440 y 390 px; README, AGENTS, manual («Exportaciones» con el PDF), informe (F10 completa) y MEMORY actualizados; `pnpm run build`, `pnpm run typecheck:e2e` y la suite backend con BD pasan; PR del bloque B con la CI en verde.
