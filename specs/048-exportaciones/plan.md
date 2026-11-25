# Plan — Spec 048: Exportaciones CSV (F10)

Estado: borrador, pendiente de aprobación. Spec aprobada el 2026-11-25.

## 1. Resumen

Un módulo backend nuevo, `exports`, genera los CSV en el servidor dentro de una transacción con `set_rls_context()`, a partir de lecturas privadas de la organización. No hay migración: las tablas, las vistas internas y la auditoría (041) ya existen. El Workspace añade una página «Exportaciones» por torneo y un botón «Descargar acta» en el partido. Todas las llamadas pasan por `useApi`. No cambia nada público (RNF-004).

## 2. Decisiones

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D1 | El CSV se genera en el **backend**. | Generarlo en el navegador a partir de las lecturas existentes. | Las lecturas existentes paginan (máx. 200–1000) e incluyen campos prohibidos (edad, clave de foto, correo de oficiales). En el servidor se aplican RLS, el límite de 10.000 filas, la neutralización y la auditoría en una sola transacción (RF-004, RF-007, RNF-003). |
| D2 | Sin migración. Las lecturas replican en SQL del módulo los filtros de las vistas públicas 030/031/060 **sin** el filtro de torneo público, y usan `v_match_current_report` (035) para el resultado vigente. | Migración 069 con vistas internas nuevas. | Evita un paso de despliegue. La lógica de «versión vigente» de los hechos (CTE de 060) se aísla en una constante SQL única del módulo y se prueba con un partido rectificado (CL-2). |
| D3 | Los datos salen de la **versión publicada** del torneo (`tournaments.published_version_id`). Sin versión publicada, cada archivo de torneo trae solo la cabecera (CL-1). | Exportar el borrador o pedir la versión. | Es lo que la organización da por vigente. Las plantillas no dependen de la versión y siempre salen completas. |
| D4 | «Estadísticas» se descarga como **dos archivos**: jugadores y equipos. | Un solo CSV con columnas mezcladas o una columna «tipo». | Las dos tablas no comparten columnas; un CSV con columnas vacías es difícil de usar en una hoja de cálculo. El catálogo sigue teniendo cinco exportaciones (RF-001). |
| D5 | Las estadísticas usan `compute_player_stats` y `compute_team_stats` (020/022) con las mismas entradas que la vista pública: partidos de la versión publicada en `scheduled/live/finished/administrative_resolution`, hechos vigentes, segmentos, solo formaciones publicadas (`is_public` y `published_at`) y juego limpio de `standings`. | Calcular con todas las alineaciones guardadas. | RF-001 pide «los mismos criterios que la vista pública». |
| D6 | El acta es **un CSV con secciones**: columnas fijas `sección, equipo, dorsal, jugador, función/tipo, minuto, detalle`. Secciones en orden: resultado, oficiales, alineación (titulares y suplentes de `match_rosters` válidos) y hechos (vigentes, no anulados, por segmento, minuto, minuto añadido e id). | Varios archivos por acta, o un ZIP. | DA-4 pide un archivo por partido. Con columnas fijas se puede filtrar por sección. |
| D7 | «Cerrado» = `status IN ('finished','administrative_resolution')` y `result_confirmed`. Otro estado responde **409 `MATCH_NOT_CLOSED`** (RF-006). | 422 o 404. | Es un conflicto con el estado del partido, explícito y distinto del 404 de RF-005. |
| D8 | Superar 10.000 filas de datos responde **422 `EXPORT_TOO_LARGE`** sin cuerpo CSV. Se lee con `LIMIT 10001`. | Truncar o paginar. | RNF-003. |
| D9 | Idioma con `?lang=es|en` (por defecto `es`), igual que las imágenes de compartir (043). Cabeceras, estados, tipos de hecho, funciones y resoluciones se traducen; los números se escriben sin formato y las fechas en ISO 8601 UTC (`2026-11-25T20:00:00Z`). | Usar `Accept-Language` o formatear según el idioma. | Explícito y testeable. ISO se ordena y se convierte bien en las hojas de cálculo. |
| D10 | Neutralización (RNF-002): solo en celdas de **texto** que empiecen por `=`, `+`, `-`, `@`, `\t` o `\r`, anteponiendo `'`. Los enteros (por ejemplo, la diferencia `-3`) no se tocan. | Neutralizar todo o quitar caracteres. | Es lo que recomienda OWASP y conserva los números. |
| D11 | Auditoría (RF-007): acción `EXPORT_TOURNAMENT_ROSTERS`, entidad `tournaments` (id del torneo), `payload = {"row_count": n}`, responsable `performed_by_member_id`. Se escribe en la misma transacción que la lectura y solo si el archivo se genera; un 422 no deja entrada. | Auditar todas las exportaciones. | DA-3 y RF-007. |
| D12 | Respuesta: `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="<tipo>-<id corto>.csv"` (ASCII) y `Cache-Control: no-store`. El frontend pone su propio nombre de archivo. | Nombre con el del torneo en la cabecera HTTP. | Evita codificar nombres en cabeceras y que un proxy guarde datos personales. |

## 3. Backend

Módulo `backend/app/modules/exports/`. Router registrado en `backend/app/main.py` con `prefix="/api/v1"`.

| Archivo | Responsabilidad | RF |
|---|---|---|
| `catalog.py` | Puro. `EXPORT_KINDS = ("standings", "calendar", "player-stats", "team-stats", "rosters")`, `MAX_ROWS = 10_000`, columnas fijas por tipo y para el acta, con etiquetas ES/EN; etiquetas de estado del partido, tipo de hecho, función del oficial, resolución, rol en la alineación, sí/no y activo/retirado. | RF-001, RF-002, RNF-001 |
| `csv_format.py` | Puro. `neutralize(value)`, `render_csv(header, rows) -> bytes`: BOM UTF-8, comas, `csv.QUOTE_MINIMAL`, fin de línea `\r\n`, `None` como celda vacía y `ExportTooLarge` si hay más de `MAX_ROWS` filas. | RF-003, RNF-001–RNF-003 |
| `builders.py` | Puro. Convierte filas leídas en filas CSV en el orden del catálogo: `standings_rows`, `calendar_rows` (marcador solo si el partido está cerrado; CL-7), `player_stats_rows`, `team_stats_rows` (sin `photo_url`, `crest_url` ni ids), `roster_rows` (sin edad ni foto; CL-4) y `match_report_rows` (W.O.: resultado y motivo, sin hechos; CL-3). Reciben `lang`. No leen el reloj. | RF-001, RF-004 |
| `service.py` | `ExportService`: en cada transacción `set_rls_context(org, user)` y la comprobación de que el torneo o el partido pertenecen a la organización (mismo 404 que hoy: `Torneo no encontrado` / `Partido no encontrado`). Lecturas SQL con columnas explícitas (nunca `national_id`, `birth_date`, `age_*`, `email`, `photo_object_key`). Para las plantillas, escribe la auditoría (D11). | RF-004–RF-008 |
| `router.py` | `GET /tournaments/{tournament_id}/exports/{kind}` y `GET /matches/{match_id}/export`, con `get_auth_context` (miembro activo, sin permiso adicional, DA-3). Traduce `ExportTooLarge` → 422 y `MatchNotClosed` → 409. | RF-001, RF-005, RF-006 |
| `audit.py` | `record_roster_export_audit(db, context, tournament_id, row_count)`. | RF-007 |
| `organization_audit/catalog.py` | `EXPORT_TOURNAMENT_ROSTERS: ActionSpec("tournaments", (_field("row_count", "number"),))`. | RF-007 |

### Columnas (RF-002)

| Tipo | Columnas (ES) | Orden de filas |
|---|---|---|
| Clasificación | Fase, Grupo, Posición, Equipo, PJ, G, E, P, GF, GC, DG, Puntos, Juego limpio | `stage_order`, grupo (sin grupo primero), posición, `team_id` |
| Calendario | Fase, Grupo, Llave, Jornada, Fecha (UTC), Local, Visitante, Estado, Goles local, Goles visitante, Penales local, Penales visitante | fecha (sin fecha al final), jornada, `id` |
| Estadísticas de jugadores | Posición, Nombre, Apellidos, Equipo, Goles, Amarillas, Rojas, Porterías imbatidas, Partidos jugados | `rank` de `compute_player_stats` |
| Estadísticas de equipos | Posición, Equipo, Código, GF, GC, Porterías imbatidas, Juego limpio | `rank` de `compute_team_stats` |
| Plantillas | Equipo, Dorsal, Nombre, Apellidos, Estado, Consentimiento de imagen | equipo, dorsal, apellidos, nombre |
| Acta | Sección, Equipo, Dorsal, Jugador, Función o tipo, Minuto, Detalle | resultado → oficiales → alineación (local, visitante; titulares y luego suplentes; dorsal) → hechos |

En inglés: Stage, Group, Position, Team, P, W, D, L, GF, GA, GD, Points, Fair play, etc. El catálogo es la única fuente de las etiquetas, y el manual las documenta.

### Pseudocódigo del servicio

```
export_tournament(context, tournament_id, kind, lang):
  begin
    set_rls_context(context.org, context.user)
    tournament = SELECT id, published_version_id FROM tournaments
                 WHERE id = :t AND organization_id = :org   # si no → 404
    rows = read_<kind>(tournament)              # LIMIT MAX_ROWS + 1
    csv_rows = builders.<kind>_rows(rows, lang)
    data = render_csv(catalog.header(kind, lang), csv_rows)   # ExportTooLarge → 422
    si kind == "rosters": record_roster_export_audit(..., len(csv_rows))
  commit
  return data

export_match_report(context, match_id, lang):
  begin
    set_rls_context(...)
    match = matches ⨝ v_match_current_report ⨝ teams, de la organización  # si no → 404
    si no cerrado → MatchNotClosed (409)
    officials = match_officials ⨝ organization_users ⨝ users (full_name, función; sin correo)
    lineup = match_rosters (is_valid) ⨝ rosters (dorsal) ⨝ players (nombre)
    events = CURRENT_EVENTS_SQL (versión vigente, no anulados) ⨝ players
    render_csv(header_acta, match_report_rows(...))
  commit
```

## 4. Interfaz

| Método y ruta | Respuesta | Errores |
|---|---|---|
| `GET /api/v1/tournaments/{tournament_id}/exports/{kind}?lang=es\|en` | 200 `text/csv` | 401 sin sesión; 404 torneo ajeno o inexistente (mismo cuerpo); 422 `kind` o `lang` no válidos; 422 `EXPORT_TOO_LARGE` |
| `GET /api/v1/matches/{match_id}/export?lang=es\|en` | 200 `text/csv` | 401; 404 partido ajeno o inexistente (mismo cuerpo); 409 `MATCH_NOT_CLOSED`; 422 `EXPORT_TOO_LARGE` |

## 5. Frontend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `utils/exports.ts` | Puro. Tipos, ruta de cada exportación, `exportFileName(kind, tournamentName, date)` (fecha como parámetro, nombre en ASCII), y `exportErrorKey(error)` para 404, 409 `MATCH_NOT_CLOSED`, 422 `EXPORT_TOO_LARGE` y error genérico. | RF-001, RF-006, RNF-003 |
| `composables/useExports.ts` | `request(path, { query: { lang }, responseType: 'blob' })` vía `useApi`; descarga con un enlace temporal (`URL.createObjectURL`/`revokeObjectURL`, como la plantilla de importación de `rosters.vue`); estado `busy` por tipo y mensaje de error. | RF-001 |
| `pages/workspace/tournaments/[id]/exports.vue` y sección `exports` en `WorkspaceShell` / `tournamentSectionHref` | Página «Exportaciones» con una fila por archivo: clasificación, calendario, estadísticas de jugadores, estadísticas de equipos y plantillas. Esta última avisa de que la descarga queda en la auditoría. Botones nativos (`components/ui/Button.vue`), deshabilitados mientras descargan, mensajes `role="status"` y `role="alert"`. | RF-001, RF-007, RNF-005 |
| `pages/workspace/matches/[id].vue` | Botón «Descargar acta (CSV)», solo si el partido está cerrado (D7), junto a las versiones de la rectificación. | RF-001, RF-006 |
| `composables/useI18n.ts` | Claves `export.*` en ES y EN; etiqueta `audit.action.EXPORT_TOURNAMENT_ROSTERS`, `audit.entity.tournaments` y `audit.field.row_count`. | RNF-005, RF-007 |
| `utils/organizationAudit.ts` | Acción y entidad nuevas en el espejo del catálogo (041). | RF-007 |

No hay cambios en las páginas públicas (DA-1, RNF-004).

## 6. Tests

**Backend**
- `tests/test_export_csv.py` (puro): BOM, `\r\n`, escape de comas, comillas y saltos de línea (CL-5); neutralización de cada prefijo en nombres de equipo y jugador maliciosos, sin tocar los enteros negativos; cabeceras ES/EN y su orden; `ExportTooLarge` con 10.001 filas y no con 10.000.
- `tests/test_export_builders.py` (puro): cada tipo con su orden; calendario sin marcador en `live`/`suspended`/`scheduled` (CL-7); plantillas sin edad ni foto y con estado retirado (CL-4); acta de W.O. con motivo y sin hechos (CL-3); traducción de estados, tipos y funciones; ausencia de claves prohibidas.
- `tests/test_exports_api.py` (`RUN_DATABASE_TESTS=1`, PostgreSQL con datos demo):
  - Las cinco exportaciones y el acta responden 200, `text/csv`, BOM y `no-store`.
  - Un torneo o partido de otra organización da exactamente el mismo 404 que uno inexistente (RF-005, RF-008).
  - Un observador puede descargar (DA-3).
  - Acta de un partido no cerrado → 409 (RF-006).
  - Partido rectificado → marcador y hechos de la última versión (CL-2).
  - Torneo archivado → exportable (CL-6). Sin versión publicada → solo cabecera (CL-1).
  - El CSV no contiene documento, fecha de nacimiento, edad, correo ni clave de foto (RF-004).
  - Plantillas → una entrada de auditoría con `row_count` y sin nombres; las demás exportaciones no dejan entrada; un 422 no deja entrada (RF-007).
  - Con `MAX_ROWS` reducido mediante monkeypatch → 422 sin archivo (RNF-003).
- `tests/test_organization_audit_catalog.py` y `tests/test_audit_frontend.py`: acción nueva y espejo del frontend.

**Frontend**
- `tests/exports.test.ts`: rutas, nombre de archivo y errores.
- `tests/export-components.test.ts`: página con los cinco botones, aviso de auditoría y botón del acta solo con el partido cerrado.
- Paridad ES/EN de `export.*` y etiquetas de auditoría.
- `e2e/exports.spec.ts` (proyecto `workspace`, contratos ficticios): descargas con teclado (evento `download` de Playwright, nombre y BOM), error 409 del acta y axe sin violaciones en ambos temas a 1440 y 390 px.

## 7. Cobertura

| RF/RNF | Dónde |
|---|---|
| RF-001, RF-002 | `catalog.py`, `builders.py`, router, página y botón del acta |
| RF-003, RNF-001, RNF-002 | `csv_format.py` |
| RF-004 | Lecturas con columnas explícitas y builders; test de ausencia de campos |
| RF-005, RF-008 | `set_rls_context` y filtro por organización; test cross-tenant |
| RF-006 | D7, 409 |
| RF-007 | `audit.py`, catálogo 041 y espejo del frontend |
| RNF-003 | `MAX_ROWS` y 422 |
| RNF-004 | Sin cambios en las vistas, endpoints ni páginas públicas |
| RNF-005 | i18n, botones nativos, E2E con teclado y axe |

## 8. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 1. Aislamiento multi-tenant por RLS | Sí | Cada lectura usa `set_rls_context()` dentro de la transacción y filtra por organización; test cross-tenant con el mismo 404. Sin `BYPASSRLS`. |
| 2–4. Reglas, motor y fases | No | Solo lectura; reutiliza el cálculo de clasificación y estadísticas existente. |
| 5. Lo público es una proyección mínima | Sí | No hay nada público nuevo (DA-1). Las exportaciones privadas tampoco llevan documento, fecha de nacimiento ni fotos. |
| Migraciones append-only | No | Sin migración (D2). |
| §3.4 Seguridad y datos personales | Sí | Sin correos ni datos de identidad; `no-store`; neutralización de fórmulas; descarga de plantillas auditada. Sin secretos ni dependencias nuevas. |
| Todo cambio con pruebas | Sí | §6, tests en rojo antes de implementar. |
| Endpoints tenant con `set_rls_context()` | Sí | `service.py`. |
| Frontend vía `useApi.ts` | Sí | `useExports`. |
| Confirmaciones destructivas `useConfirm` | No | Descargar no es destructivo. |
| ES/EN, teclado y axe en ambos temas | Sí | i18n y E2E. |
| Dependencias: `pip-audit`, auditoría pnpm y Trivy | No | Ninguna dependencia nueva (DA-2). |
| Documentación coherente (README, AGENTS, manual) | Sí | T9 actualiza README (endpoints), AGENTS, manual (sección «Exportaciones» con las columnas), informe (F10) y MEMORY. |
