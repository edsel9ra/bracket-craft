# Plan — Spec 050: Exportaciones PDF (F10, parte 2)

Estado: aprobado el 2026-11-26 («Apruebo el plan y las tareas. Empieza con T1»). Spec aprobada el 2026-11-26 («Apruebo la spec 050»).

## 1. Resumen

El módulo `exports` de la 048 añade dos rutas que devuelven PDF: la clasificación del torneo y el acta de un partido cerrado. Reutilizan las mismas lecturas, la misma instantánea `REPEATABLE READ`, el mismo `set_rls_context()` y los mismos builders que el CSV, así que el contenido es por construcción el del CSV (RF-001, RF-004). Solo cambia el formato de salida: un renderizador puro con ReportLab compone un A4 paginado con fuentes TTF incrustadas. No hay migración ni variables nuevas. En el Workspace, la fila de la clasificación y el bloque del acta añaden un botón «PDF» junto al CSV, siempre vía `useApi`. No cambia nada público (RNF-006).

## 2. Decisiones

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D1 | Biblioteca **ReportLab** (licencia BSD, wheel puro Python, en uso desde hace más de 20 años), versión exacta fijada en `backend/requirements.txt`. Su única dependencia nueva es `charset-normalizer`; `pillow` ya está fijada (13.0.0) y cumple su requisito. | fpdf2 (LGPL); WeasyPrint (necesita Pango y librerías del sistema en la imagen); generar el PDF en el navegador. | DA-2: dependencia Python madura, sin paquetes del sistema en el `Dockerfile`, y tablas con cabecera repetida y ajuste de línea (Platypus). |
| D2 | **Fuente TTF incrustada:** Archivo estática (Regular y Bold, licencia OFL), la misma familia del sistema de diseño (029), en `backend/app/modules/exports/fonts/` junto a su `OFL.txt`. Si no hubiera versión estática disponible, DejaVu Sans (licencia libre), decidido en T1 y anotado. **Respaldo (2026-11-26, pedido por el usuario tras Devin Review):** DejaVu Sans 2.37 Regular y Bold, con su `DejaVu-LICENSE.txt`, solo para los tramos de letras que Archivo no tiene (p. ej. «Ɓ», «Ŋ»); se incrusta solo si se usa. | Las fuentes estándar de PDF (Helvetica). | Las estándar solo cubren Latin-1: un nombre con «ł» o «ř» saldría con caracteres sustituidos (RNF-002). |
| D3 | Rutas nuevas, separadas del CSV: `GET /tournaments/{id}/exports/standings/pdf` y `GET /matches/{id}/export/pdf`, con `?lang=es|en`. | Un parámetro `format` en las rutas actuales. | Con `format`, los otros cuatro tipos tendrían que rechazar `pdf` con un 422 más; con rutas propias el catálogo PDF es cerrado (DA-1) y las rutas CSV no cambian. |
| D4 | **Mismo contenido que el CSV:** el servicio obtiene las filas con los builders de la 048 (`standings_rows`, `match_report_rows`) y el PDF solo las agrupa: la clasificación en una tabla por fase y grupo (sin las columnas Fase y Grupo, que pasan al título de la tabla); el acta en bloques Resultado, Oficiales, Alineación (local y visitante) y Hechos, según la columna «Sección». | Lecturas o builders propios del PDF. | Garantiza RF-001 y RF-004 sin duplicar lógica; un test compara las celdas del PDF con las del CSV. |
| D5 | Cabecera (RF-002): organización, torneo, en el acta el partido («Local vs Visitante», fase, fecha UTC) y «Generado el … (UTC)». La hora de generación la pasa el router (`datetime.now(UTC)`) al renderizador, que no lee el reloj. | Hora local del usuario. | Funciones puras con la fecha como parámetro; UTC como en el CSV. |
| D6 | **Texto literal (RNF-003):** cada celda se escapa con `xml.sax.saxutils.escape` antes de crear el `Paragraph`, porque Platypus interpreta marcas (`<b>`, `<a>`). | Pasar el texto tal cual. | Un nombre `<b>Equipo</b>` o `A & B` se ve literal y no rompe el documento. |
| D7 | **Límite (RNF-004):** se reutiliza `ExportTooLarge` y la lectura `LIMIT MAX_ROWS + 1`: más de 10.000 filas de datos → 422 `EXPORT_TOO_LARGE`, sin documento. | Paginar o truncar. | Mismo contrato que el CSV. |
| D8 | Respuesta: `application/pdf`, `Content-Disposition: attachment; filename="standings-<id corto>.pdf"` o `match-report-<id corto>.pdf`, `Cache-Control: no-store`. El frontend pone su propio nombre con la extensión `.pdf`. | Nombre con el torneo en la cabecera HTTP. | Igual que D12 de la 048. |
| D9 | **Determinismo en tests:** el renderizador acepta `invariant=True` (ReportLab fija fecha e identificador del documento) para que dos generaciones iguales den los mismos bytes en los tests. En producción los metadatos llevan la fecha de generación. | Comparar solo el texto. | Permite tests estables sin depender del reloj. |
| D10 | Los tests leen el texto del PDF con **pypdf** (BSD), solo en `backend/requirements-dev.txt`. | Buscar texto en el flujo binario. | Con fuentes incrustadas el texto va codificado por glifos; pypdf lo extrae y permite verificar contenido, acentos y ausencia de campos. |

## 3. Backend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `requirements.txt`, `requirements-dev.txt` | `reportlab==<versión fijada>` y `charset-normalizer==<versión fijada>`; `pypdf==<versión fijada>` en dev. | RNF-008 |
| `modules/exports/fonts/` | `Archivo-Regular.ttf`, `Archivo-Bold.ttf` y `OFL.txt` (D2). | RNF-002 |
| `modules/exports/catalog.py` | `PDF_KINDS = ("standings", "match-report")`; títulos y textos fijos ES/EN del documento (título, «Generado el», «Página n de m», «Sin clasificación todavía», nombres de los bloques del acta). | RF-001, RF-002, RNF-001 |
| `modules/exports/pdf_format.py` | Puro. `render_pdf(document, lang, generated_at, *, invariant=False) -> bytes`. `document` = título, líneas de cabecera y secciones `(subtítulo, cabecera, filas)`. A4 vertical, márgenes 18 mm, fuentes registradas una vez, `Table(repeatRows=1)` con `Paragraph` escapado (D6), pie «Página n de m» con un lienzo de dos pasadas, metadatos `title` y `lang`. `ExportTooLarge` si las filas superan `MAX_ROWS`. | RF-002, RNF-001–RNF-004 |
| `modules/exports/pdf_layout.py` | Puro. `standings_document(rows, header_info, lang)` agrupa por fase y grupo (CL-1 con aviso si no hay filas); `match_report_document(rows, header_info, lang)` agrupa por sección (CL-3: sin bloque de hechos). | RF-001, CL-1, CL-3, CL-5 |
| `modules/exports/service.py` | `export_standings_pdf` y `export_match_report_pdf`: misma transacción y lecturas que el CSV más el nombre de la organización y del torneo (`organizations.name`, `tournaments.name`, filtrados por organización); devuelven el `document` para el renderizador. Mismos `ExportNotFound` y `MatchNotClosed`. | RF-004–RF-006, RF-008 |
| `modules/exports/router.py` | Dos rutas (D3) con `get_auth_context`; `datetime.now(UTC)` → `render_pdf`; 404, 409 y 422 como el CSV. | RF-001, RF-003, RF-005, RF-006 |

Sin auditoría (DA-4, RF-007): las rutas PDF no llaman a `record_roster_export_audit` ni a ninguna otra. Sin cambios en `main.py`: el router de `exports` ya está registrado.

### Pseudocódigo

```
export_standings_pdf(context, tournament_id, lang):
  begin (REPEATABLE READ) + set_rls_context
    t = tournaments ⨝ organizations WHERE id = :t AND organization_id = :org   # si no → 404
    rows = standings_rows(read_standings(...), lang) si hay versión publicada, si no []
  return standings_document(rows, {org: t.org_name, tournament: t.name}, lang)

router: render_pdf(document, lang, generated_at=datetime.now(UTC))   # ExportTooLarge → 422

standings_document(rows, info, lang):
  secciones = agrupar rows por (Fase, Grupo) en el orden recibido
  cada sección: subtítulo "Fase · Grupo" y columnas Posición…Juego limpio
  si no hay filas: una sección vacía con el aviso «Sin clasificación todavía»
```

## 4. Interfaz

| Método y ruta | Respuesta | Errores |
|---|---|---|
| `GET /api/v1/tournaments/{tournament_id}/exports/standings/pdf?lang=es\|en` | 200 `application/pdf` | 401; 404 torneo ajeno o inexistente (mismo cuerpo); 422 `lang` no válido; 422 `EXPORT_TOO_LARGE` |
| `GET /api/v1/matches/{match_id}/export/pdf?lang=es\|en` | 200 `application/pdf` | 401; 404 partido ajeno o inexistente (mismo cuerpo); 409 `MATCH_NOT_CLOSED`; 422 `EXPORT_TOO_LARGE` |

## 5. Frontend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `utils/exports.ts` | Puro. `ExportFormat = 'csv' \| 'pdf'`, `PDF_EXPORT_KINDS = ['standings', 'match-report']`, rutas PDF y `exportFileName(kind, name, date, format)` con extensión `.pdf`. Los errores reutilizan `exportErrorKey`. | RF-001, RF-003 |
| `composables/useExports.ts` | `busy` pasa a identificar tipo y formato (`standings:pdf`); `downloadTournament(..., format)` y `downloadMatchReport(..., format)`; una descarga a la vez y descarte por cambio de organización, como en la 048. | RF-003, CL-7 |
| `pages/workspace/tournaments/[id]/exports.vue` | La fila de la clasificación añade el botón «Descargar PDF» junto a «Descargar CSV», con su propio `aria-describedby`. | RF-003, RNF-007 |
| `components/match/MatchReportExport.vue` | Añade «Descargar acta (PDF)» junto al CSV, con la misma condición de partido cerrado. | RF-003, RF-006 |
| `composables/useI18n.ts` | Claves `export.format.*`, `export.downloadPdf` y `export.kind.match-report.pdfTitle` en ES y EN. | RNF-007 |

No hay cambios en páginas públicas (RNF-006).

## 6. Tests

**Backend**
- `tests/test_export_pdf.py` (puro, pypdf):
  - Cabecera con organización, torneo y fecha de generación (RF-002).
  - A4 y «Página n de m»; una clasificación de 8 grupos de 8 equipos y un acta con 44 jugadores y 60 hechos ocupan varias páginas con la cabecera de tabla repetida (RNF-001, CL-5).
  - Acentos, «ñ», «ł» y «ř» extraídos tal cual (RNF-002).
  - `<b>`, `&` y comillas en nombres salen literales (RNF-003).
  - Un nombre de 120 caracteres se parte en líneas sin salir de la página (CL-4).
  - `ExportTooLarge` con 10.001 filas (RNF-004).
  - Ambos documentos se generan en menos de 5 s (RNF-005).
  - Con `invariant=True`, dos generaciones dan los mismos bytes (D9).
- `tests/test_export_pdf_layout.py` (puro): agrupación por fase y grupo; aviso sin clasificación (CL-1); acta de W.O. sin bloque de hechos (CL-3); las celdas del documento son exactamente las filas del CSV (D4).
- `tests/test_exports_api.py` (`RUN_DATABASE_TESTS=1`):
  - Las dos rutas responden 200, `application/pdf`, `%PDF-` y `no-store`; un observador puede descargarlas.
  - Torneo o partido de otra organización → el mismo 404 que uno inexistente (RF-005, RF-008).
  - Acta no cerrada → 409; partido rectificado → última versión (CL-2); torneo archivado → exportable (CL-6).
  - El texto no contiene documento, fecha de nacimiento, edad ni correo (RF-004).
  - Ninguna entrada nueva en la auditoría (RF-007).
  - `MAX_ROWS` reducido con monkeypatch → 422 sin documento (RNF-004).
- Test de rutas: las dos rutas nuevas se excluyen del recuento de rutas de torneos y partidos, como las CSV.

**Frontend**
- `tests/exports.test.ts`: rutas PDF, nombre `.pdf` y catálogo `PDF_EXPORT_KINDS` igual al `PDF_KINDS` del backend.
- `tests/export-components.test.ts`: el botón PDF solo en la clasificación y en el acta de un partido cerrado; una descarga a la vez.
- Paridad ES/EN de las claves nuevas.
- `e2e/exports.spec.ts` (ampliado): descarga del PDF de la clasificación y del acta con teclado (evento `download`, nombre `.pdf` y bytes `%PDF-`); axe sin violaciones en ambos temas a 1440 y 390 px.

## 7. Cobertura

| RF/RNF | Dónde |
|---|---|
| RF-001, RF-002 | `pdf_layout.py`, `pdf_format.py`, builders de la 048 (D4) |
| RF-003 | Rutas (D3), página y botón del acta |
| RF-004 | Mismas lecturas y builders del CSV; test de ausencia de campos |
| RF-005, RF-008 | `set_rls_context` y filtro por organización; test cross-tenant |
| RF-006 | `MatchNotClosed` → 409 |
| RF-007 | Sin llamadas de auditoría; test sin entradas nuevas |
| RNF-001–RNF-005 | `pdf_format.py` y sus tests |
| RNF-006 | Sin cambios públicos |
| RNF-007 | i18n, botones nativos, E2E con teclado y axe |
| RNF-008 | Versiones fijadas; `pip-audit` y Trivy en CI |

## 8. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 1. Aislamiento multi-tenant por RLS | Sí | Mismas lecturas con `set_rls_context()` dentro de la transacción; test cross-tenant con el mismo 404. Sin `BYPASSRLS`. |
| 2–4. Reglas, motor y fases | No | Solo lectura; reutiliza la clasificación calculada. |
| 5. Lo público es una proyección mínima | Sí | Nada público nuevo. Los PDF privados no llevan documento, fecha de nacimiento, edad, correo ni fotos. |
| Migraciones append-only | No | Sin migración. |
| §3.4 Seguridad y datos personales | Sí | Sin datos de identidad; `no-store`; texto escapado (D6); sin secretos ni variables nuevas. |
| §3.4 Dependencias: `pip-audit`, auditoría pnpm y Trivy | Sí | ReportLab, charset-normalizer y pypdf con versión exacta; `pip-audit -r requirements.txt -r requirements-dev.txt` y Trivy en CI. Sin dependencias nuevas en el frontend. |
| §4 Cambios de dependencias: lockfiles y auditorías | Sí | `requirements*.txt` actualizados en T1 y auditorías en verde en el PR del bloque A. |
| Todo cambio con pruebas | Sí | §6, tests en rojo antes de implementar. |
| Endpoints tenant con `set_rls_context()` | Sí | `service.py`. |
| Frontend vía `useApi.ts` | Sí | `useExports`. |
| Confirmaciones destructivas `useConfirm` | No | Descargar no es destructivo. |
| ES/EN, teclado y axe en ambos temas | Sí | i18n y E2E. |
| Documentación coherente (README, AGENTS, manual) | Sí | T7 actualiza README (rutas y dependencia), AGENTS, manual (PDF en «Exportaciones»), informe (F10 completa) y MEMORY. |
