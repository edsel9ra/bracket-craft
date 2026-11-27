# Tareas — Spec 050: Exportaciones PDF (F10, parte 2)

Estado: aprobadas el 2026-11-26 junto con el plan («Apruebo el plan y las tareas. Empieza con T1»).

## Bloque A — Backend (un PR)

- [x] **T1. Dependencia, fuentes y renderizador puro.** RF-002, RNF-001–RNF-005, RNF-008
- Hecho cuando: `reportlab` y `charset-normalizer` fijados en `backend/requirements.txt` y `pypdf` en `requirements-dev.txt`; fuentes TTF y su licencia en `modules/exports/fonts/` (D2); `pdf_format.py` con `render_pdf`; `tests/test_export_pdf.py` falla primero y luego pasa con `cd backend && pytest -q tests/test_export_pdf.py`; `pip-audit -r requirements.txt -r requirements-dev.txt` sin hallazgos.
- Evidencia (2026-11-26): `reportlab==5.1.0` y `charset-normalizer==3.5.2` (las versiones de más de 30 días; 5.1.1/5.1.2 tenían 1–2 días) y `pypdf==6.21.4` en dev (6.21.2 tenía cinco CVE corregidas en 6.21.3/6.21.4). D2: Archivo estática Regular/Bold del repositorio Omnibus-Type/Archivo, con `OFL.txt`. `tests/test_export_pdf.py` falló primero (sin `pdf_format`) y ahora pasa 18/18; con los tests CSV de la 048, 91/91. `pip-audit` sin vulnerabilidades; Ruff, Bandit y compileall limpios; la imagen Docker de la API genera un PDF con «Ñ ł» sin paquetes del sistema. Ajuste: la fuente inicial del lienzo y de las tablas se fija a Archivo, porque ReportLab declaraba Helvetica sin incrustar.
- [x] **T2. PDF de la clasificación.** RF-001–RF-005, RF-007, RF-008, CL-1, CL-6
- Hecho cuando: `pdf_layout.standings_document`, `ExportService.export_standings_pdf` y `GET /tournaments/{id}/exports/standings/pdf`; tests puros de agrupación e igualdad con el CSV y casos de `tests/test_exports_api.py` (200, mismo 404 ajeno, observador, sin auditoría, 422 por límite) en rojo primero y en verde con `RUN_DATABASE_TESTS=1`.
- Evidencia (2026-11-26): `tests/test_export_pdf_layout.py` falló primero (sin `pdf_layout`) y los 11 casos PDF nuevos de `tests/test_exports_api.py` dieron 404 por falta de ruta; ahora pasan 83/83 con `RUN_DATABASE_TESTS=1` (PDF puro, layout, rutas y exportaciones). El nombre de la organización sale de `get_current_organization()`, como en las invitaciones, dentro de la misma transacción con `set_rls_context()`. `test_tournament_routes_order.py` excluye la ruta nueva, como la CSV. Suite sin BD 3447/0; Ruff, Bandit y compileall limpios.
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
