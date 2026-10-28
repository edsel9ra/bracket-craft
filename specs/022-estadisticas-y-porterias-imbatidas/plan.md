# Plan — Spec 022: Estadísticas deportivas públicas y porterías imbatidas

## 1. Alcance y dependencias

- Depende de **spec 020** (acceso público, matriz de campos, paginación por fase/grupo) y **spec 021** (formación publicada como fuente del portero).
- No cambia `engine_version` (2026.1) ni el contrato interno de reglas.
- **Cadena de esquema:** el punto de partida es **027**; la spec 021 aporta la **028**, y esta spec aporta **029** (`organization_id` en `v_public_tournaments`), **030** (vistas públicas de eventos, segmentos y plantillas) y **031** (proyección interna con **todas** las formaciones publicadas, añadida en esta ronda de corrección). Las tres son **aditivas**, sin rollback y con *forward-fix*.
- No añade campos a los modelos públicos existentes; añade **dos lecturas públicas nuevas** (tablas de jugadores y de equipos) con sus propios modelos, que sí incluyen la columna de posición (`rank`), coherente con `PublicStandingResponse`.
- Esta ronda de corrección (2026-10-27) no cambia la forma de ningún contrato ya declarado: corrige la fuente de la formación del portero, la foto del jugador retirado, el ámbito por defecto, la columna de posición y el endurecimiento de los modelos de respuesta.

## 2. Archivos y responsabilidades

### Backend

| Archivo | Responsabilidad |
|---|---|
| `backend/app/modules/tournaments/router.py` | Dos endpoints públicos: `GET /tournaments/public/{tournament_id}/player-stats` y `GET /tournaments/public/{tournament_id}/team-stats` (filtros `stage_id`, `group_id`, paginación `limit`/`offset`). **Deben declarar `response_model=PublicPlayerStatsResponse` / `response_model=PublicTeamStatsResponse`** (hoy no lo declaran: la lista cerrada no se aplica a la respuesta). La lectura de formaciones pasa a la proyección de la 031. La foto de un roster `is_active = FALSE` no se selecciona (RF-007, RF-034). |
| `backend/app/modules/tournaments/schemas.py` | `PublicPlayerStatsResponse` y `PublicTeamStatsResponse` (ambos ya existen) **más el campo `rank: int`** en cada uno. |
| `backend/app/modules/tournaments/public_stats.py` | Funciones puras: `clean_sheet_team`, `goalkeeper_minutes`, `clean_sheet_goalkeeper`, `compute_player_stats`, `compute_team_stats`, `assign_ranks` y los ayudantes de formación publicada. Sin BD ni reloj. |
| `backend/app/main.py` | Sin cambios (router ya registrado). |

### Base de datos

| Archivo | Responsabilidad |
|---|---|
| `infra/postgres/migrations/029_public_tournament_organization.sql` (ya existe) | `CREATE OR REPLACE VIEW v_public_tournaments` añadiendo `organization_id` (aditivo, solo para uso interno; no se incluye en ninguna respuesta pública). |
| `infra/postgres/migrations/030_public_stats_views.sql` (ya existe) | `v_public_match_events`, `v_public_match_segments` y `v_public_tournament_rosters` (`security_barrier`, `GRANT SELECT` solo a `bracket_app`). |
| `infra/postgres/migrations/031_public_match_formations.sql` (**nueva**) | Proyección **interna** con **todas** las formaciones tácticas **publicadas**, por partido, segmento y equipo, con jugador, `position_slot`, titular/suplente e `is_public`. `security_barrier`, `GRANT SELECT` solo a `bracket_app`, `REVOKE` de `PUBLIC`, filtrada por torneo visible y versión publicada. **No** la consume ninguna ruta pública: alimenta solo el cálculo de estadísticas. Cubre RF-015, RF-026 y los casos 14 y 16b. |

### Frontend

| Archivo | Responsabilidad |
|---|---|
| `frontend/app/pages/tournaments/[id].vue` | Sección «Estadísticas» con las dos tablas, definiciones, estado vacío y paginación «cargar más». **Ámbito por defecto: torneo completo** (no se envía `stage_id` hasta que el usuario elija una fase) y filtro por fase explícito y reversible (RF-021). |
| `frontend/app/utils/publicTournament.ts` | Resolver del ámbito de estadísticas: `null` (torneo completo) por defecto y validación del `stage_id`/`group_id` elegido contra las fases del torneo cargado; la primera fase **no** se preselecciona (RF-021). Función pura y testeable con `node --test`. |
| `frontend/app/components/public/PublicPlayerStatsTable.vue` | Tabla de jugadores: **columna de posición**, foto/iniciales (iniciales si la imagen falla), goles, amarillas, rojas, porterías imbatidas. |
| `frontend/app/components/public/PublicTeamStatsTable.vue` | Tabla de equipos: **columna de posición**, escudo, goles a favor/en contra, porterías imbatidas, fair play. |
| `frontend/app/composables/useI18n.ts` | Definiciones breves es/en de **goles**, **goles en contra**, **porterías imbatidas**, **fair play** y la mención de **partidos incompletos** y de las resoluciones fuera del campo (RF-010, RF-023, RF-029, RF-031). |
| `frontend/app/composables/useApi.ts` | Sin cambios (reutiliza). |

### Tests

| Archivo | Responsabilidad |
|---|---|
| `backend/tests/test_public_stats.py` (puro) | Portería imbatida por equipo y portero, **una prueba por cada una de las 22 filas** de la tabla de casos y por cada caso CL, minutos del portero, regla sobre **todas** las formaciones con comprobación de `is_public`, participación (`player_in_id`), agregación, empates/posición y actas históricas. |
| `backend/tests/test_migration_029.py` (**nuevo, opt-in DB**) | Forma y privilegios de la vista tras la 029; cadena limpia y salto 028 → 029. |
| `backend/tests/test_migration_030.py` (**nuevo, opt-in DB**) | Las tres vistas de la 030: columnas, `security_barrier`, `GRANT`/`REVOKE`, filas de torneos no visibles excluidas; salto 029 → 030. |
| `backend/tests/test_migration_031.py` (**nuevo, opt-in DB**) | Forma de la proyección de la 031, privilegios, **todas** las formaciones publicadas de un partido con varios segmentos (no solo la última) y exclusión de las no publicadas; salto 030 → 031. |
| `backend/tests/test_public_stats_endpoints.py` (opt-in DB) | Endpoints: **`rank`** y empates, ámbito por defecto y filtro por fase, paginación, orden, foto del retirado, estado vacío, 404 indistinguible, **aislamiento con datos sembrados** y **lista cerrada con datos reales** (falla ante una clave extra en la respuesta). |
| `backend/tests/test_public_access_matrix.py` (modificado) | Añadir las **dos rutas de estadísticas** a la matriz (lectura anónima, 404 indistinguible, 422 de parámetros). |
| `frontend/tests/public-stats.test.ts` | Renderizado, columna de posición y empates, ámbito por defecto/filtro por fase, iniciales cuando la imagen falla, paginación, estado vacío, definiciones es/en, 360 px. |

## 3. Funciones puras

Toda función que dependa de datos recibe listas ya cargadas; ninguna lee el reloj ni la BD.

```python
def published_formations(formations) -> list[dict]:
    """Filtra las formaciones con is_public verdadero. La regla NO delega el
    filtro en la vista: comprueba `is_public` aunque el origen ya filtre, para
    que una proyección mal filtrada no publique una formación no publicada
    (RF-026, caso 13)."""

def assign_ranks(rows, visible_criteria, stable_id) -> list[dict]:
    """Ordena por `visible_criteria` y asigna `rank` compartido por las filas
    empatadas en TODOS los criterios visibles; la numeración continúa tras el
    empate (1, 2, 2, 4). El identificador solo ordena dentro del empate
    (RF-006, RF-022)."""

def clean_sheet_team(match, events) -> bool:
    """Partido confirmado y disputado (reglamentario/prórroga/penales), cero
    goles recibidos (gol, penalti, autogol del rival; prórroga incluida;
    penales excluidos)."""

def goalkeeper_minutes(match, gk_id, events, segments, started_at_minute) -> int:
    """Minutos del portero: no sustituido → duración efectiva; sustituido →
    inicio del intervalo → minuto de sustitución (minuto+añadido, acotado);
    expulsado → inicio del intervalo → minuto de expulsión."""

def clean_sheet_goalkeeper(match, formations, events, segments) -> list[UUID]:
    """Una portería imbatida por portero y partido, con la regla completa:
    equipo con clean sheet; portero titular identificado en la formación
    publicada del primer segmento; sustituto identificable si figura como GK
    en CUALQUIER formación publicada posterior; >= 60 minutos."""

def compute_player_stats(matches, events, formations, segments, rosters) -> list[dict]:
    """Agrega por player_id: goles, amarillas, rojas, porterías imbatidas y
    partidos disputados. Una sustitución acredita al que sale (player_out_id)
    y al que entra (player_in_id). Suma entre equipos del mismo jugador."""

def compute_team_stats(matches, events, fair_play) -> list[dict]:
    """Agrega por team_id: goles a favor, en contra, porterías imbatidas y
    puntos de juego limpio. Walkover/administrativa cuentan (goles derivados)."""
```

## 4. Algoritmo (pseudocódigo)

### Portería imbatida del equipo

```
def clean_sheet_team(match, events):
    if match.status not in ('finished', 'administrative_resolution'): return False
    if not match.result_confirmed: return False
    if match.resolution_type in ('walkover', 'administrative'): return False
    # goles recibidos = marcador final (prórroga incluida, penales excluidos),
    # cruzado con los eventos para validar (RF-005); el evento huérfano se excluye.
    return goals_against(match, team_of(match)) == 0
```

### Portería imbatida del portero (todas las formaciones publicadas)

```
def clean_sheet_goalkeeper(match, formations, events, segments):
    if not clean_sheet_team(match): return []          # sin formación publicada no hay portero
    published = [f for f in formations                              # por partido y equipo
                 if f.is_public and f.match_id == match.id]         # el filtro NO se delega en la vista
    if not published: return []                                     # casos 12, 13
    for team in (match.home_team_id, match.away_team_id):
        mine = sorted([f for f in published if f.team_id == team],
                      key=lambda f: (f.segment_number, f.id))
        starter = gk_of(mine[0])                                    # formación del primer segmento
        for gk in goalkeepers_of(mine):                             # titulares y entrantes como GK
            minutes = goalkeeper_minutes(match, gk, events, segments,
                                         started_at_minute(gk, mine, events))
            if minutes >= 60: yield gk                              # casos 1, 2, 3, 14, 16, 16b, 16c
```

- **Portero titular:** `GK` de la formación publicada del **primer segmento** del equipo.
- **Portero entrante:** jugador que sustituye al portero (`player_in_id`) y que figura como `GK` en una formación publicada **posterior**; sus minutos cuentan desde el minuto de la sustitución. Si no figura como `GK` en ninguna formación publicada, no se le atribuye (caso 16c) y el equipo conserva la suya.
- **Expulsión:** los minutos ya jugados cuentan; el umbral 60 se evalúa sobre lo jugado hasta la expulsión (caso 3: 70 ≥ 60 → sí).
- Se emite **como máximo una** atribución por portero y partido.

### Minutos del portero

```
def goalkeeper_minutes(match, gk, events, segments, start):
    duration = effective_duration(segments)      # último minute_end o máximo efectivo de la fase
    sub_out  = first_substitution_out(match, gk.id, events)
    if sub_out: return min(sub_out, duration) - start
    red = first_red_card(match, gk.id, events)
    if red: return min(red.minute + red.added_minute, duration) - start
    return duration - start
```

### Posición (columna de posición)

```
def assign_ranks(rows, visible_criteria, stable_id):
    # identificador estable al final: solo ordena dentro del empate
    ordered = sorted(rows, key=lambda r: (tuple(r[c] for c in visible_criteria), str(r[stable_id])))
    rank, previous = 1, None
    for index, row in enumerate(ordered, start=1):
        visible = tuple(row[c] for c in visible_criteria)
        if visible != previous:
            rank, previous = index, visible
        row['rank'] = rank
    return ordered
```

Criterios visibles: jugadores → `(-goals, matches_played, last_name)`; equipos → `(-goals_for, goals_against, team_name)`. El identificador **no** forma parte de los criterios visibles: solo ordena dentro del empate.

## 5. Interfaz

### Endpoints nuevos

```
GET /tournaments/public/{tournament_id}/player-stats
  Query: stage_id?, group_id?, limit (1..500, default 200), offset (>=0)
  response_model=PublicPlayerStatsResponse
  PublicPlayerStatsResponse = {
    rank, player_id, first_name, last_name, team_name, team_id,
    goals, yellow_cards, red_cards, clean_sheets,
    matches_played, photo_url (firmada o null)
  }

GET /tournaments/public/{tournament_id}/team-stats
  Query: stage_id?, group_id?, limit, offset
  response_model=PublicTeamStatsResponse
  PublicTeamStatsResponse = {
    rank, team_id, team_name, short_code, crest_url,
    goals_for, goals_against, clean_sheets, fair_play_points
  }
```

- Sin `stage_id` ni `group_id` el ámbito es el **torneo completo** (RF-021).
- `rank` se calcula en el **servidor sobre el conjunto completo** y después se pagina; con paginación por `offset` el cliente no puede derivarlo.
- Declarar `response_model` es lo que hace efectiva la lista cerrada de campos: hoy la respuesta sale sin modelo y una clave de más no se detecta.

### Pantallas

- En `/tournaments/{id}` (pública), sección «Estadísticas» con dos tablas (jugadores y equipos): columna de posición, foto o iniciales, paginación «cargar más», selector de fase con la opción **«todo el torneo»** activa por defecto, definiciones es/en y estado vacío.

## 6. Decisiones justificadas

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D1 | Cálculo en Python con funciones puras, cargando datos del torneo en consultas acotadas. | Vistas agregadas en SQL. | Testabilidad de los 22 casos de la tabla y de los CL, y reutilización de la lógica de formaciones/minutos; RNF-003 se cumple porque el número de consultas es fijo por respuesta. |
| D2 | Añadir `organization_id` a `v_public_tournaments` (migración 029, aditiva) para fijar el contexto RLS en el endpoint público. | Consultar tablas tenant sin RLS (BYPASSRLS) o función `SECURITY DEFINER`. | Respeta el principio 1 (RLS en la base); `organization_id` no se incluye en ningún modelo de respuesta público (lista cerrada). |
| D3 | Portería imbatida del equipo: marcador final (goles recibidos) como fuente de verdad, cruzado con los eventos. | Recalcular goles recibidos sumando eventos. | El marcador final ya incluye prórroga y excluye penales; evita doble fuente. Los eventos huérfanos se excluyen sin fallar (RF-004). |
| D4 | Umbral de 60 minutos **fijo en código como criterio de una estadística derivada**, no configurable. | Configurable por torneo o por versión. | RF-027 y RNF-009: el criterio no es una regla de juego, no se evalúa en el motor y no altera resultados ni `engine_version`; por eso **no** requiere excepción a la constitución. Hacerlo configurable rompería la comparabilidad pública entre torneos. |
| D5 | Walkover y resolución administrativa cuentan para estadísticas de equipo (goles derivados) pero no para portero ni porterías imbatidas. | Excluirlos de todo. | Coherente con la clasificación (RF-018, RF-021). |
| D6 | Fotos firmadas en un solo lote después de cerrar la transacción (política `null`). | Firmar dentro de la transacción. | RNF-003 y convención del proyecto. |
| D7 | Proyección interna nueva (**031**) con **todas** las formaciones publicadas, en lugar de reutilizar la proyección pública de alineaciones. | Leer `v_public_match_lineups` (publica solo la última formación por equipo). | La regla del portero necesita la formación del primer segmento y la del portero entrante; con la última por equipo los casos 14 y 16b serían inalcanzables. No se cambia el contrato público de la 021. |
| D8 | La regla pura **comprueba `is_public`** además de recibir datos ya filtrados por la vista. | Confiar en el `WHERE` de la proyección. | Defensa en profundidad: una vista mal filtrada no puede publicar una posición de formación no publicada (RF-026, caso 13). La prueba pura lo verifica sin base. |
| D9 | `rank` se calcula en el **backend**, sobre el conjunto completo, antes de paginar. | Calcular la posición en el frontend. | RNF-002 (reproducibilidad): con paginación por `offset` el cliente no ve el conjunto completo y dos clientes podrían mostrar posiciones distintas; además el orden estable no debe depender del `locale` del navegador. |
| D10 | Ámbito por defecto **torneo completo**; el filtro por fase se envía solo tras una acción explícita del usuario. | Preseleccionar la primera fase (como hace hoy la pantalla). | RF-021: el valor por defecto del producto es el torneo entero; preseleccionar una fase oculta partidos y hace que la cifra pública no coincida con la del torneo. |

## 7. Estrategia de tests

- **Unitarios puros** (`test_public_stats.py`): una prueba por cada una de las **22 filas** de la tabla de porterías imbatidas (1, 2, **3 con expulsión a los 70 min → sí**, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 15b, 16, 16b, 16c, 17, 18, 19), por cada **CL-1..CL-12**, más minutos del portero, `is_public` en la regla pura, participación del jugador entrante, empates/`rank`, eventos huérfanos y actas históricas.
- **Integración opt-in DB** (`RUN_DATABASE_TESTS=1`): endpoints (`rank`, ámbito por defecto, filtros, paginación, orden, foto del retirado, estado vacío, 404), **lista cerrada con datos reales** (una clave extra debe hacer fallar la prueba), **aislamiento con dos organizaciones sembradas** y las migraciones 029/030/031 en cadena limpia y por saltos.
- **Matriz de acceso** (`test_public_access_matrix.py`): las dos rutas de estadísticas incluidas.
- **Frontend** (`public-stats.test.ts` + `node --test` del resolver de ámbito): renderizado, columna de posición, empates, ámbito por defecto y filtro explícito, iniciales cuando la imagen falla, paginación, estado vacío, definiciones es/en, 360 px.
- **CI**: `cd backend && pytest -q`, `python -m compileall -q app`, `cd frontend && pnpm test && pnpm run typecheck && pnpm run build`, `sh -n infra/postgres/migrate.sh`, `docker compose config -q`.

## 8. RF cubiertos por parte

| Parte | RF |
|---|---|
| Migración 029 | RNF-005 (aditivo) |
| Migración 030 | RF-004, RF-018, RF-020 (fuente de eventos, segmentos y plantillas) |
| Migración 031 | RF-015, RF-026, casos 14 y 16b |
| Funciones puras (clean sheet, minutos, agregación) | RF-012..RF-020, RF-024..RF-032 |
| `assign_ranks` (backend) | RF-006, RF-022 |
| Endpoints públicos (`response_model`) | RF-003, RF-004, RF-005, RF-006, RF-009, RF-021, RF-022, RF-036 |
| Fotos en tablas (vigente + consentimiento) | RF-007, RF-008, RF-034 |
| Frontend (tablas, posición, ámbito, definiciones, estado vacío) | RF-001, RF-002, RF-006, RF-010, RF-011, RF-016, RF-017, RF-021, RF-022, RF-023, RF-031, RF-033, RF-034, RF-035 |
| Paginación | RF-009 |
| Lista cerrada de campos públicos | RF-015 (spec 020) actualizada con los dos modelos nuevos |

## 9. Verificación de constitución

| Principio o criterio (docs/constitution.md) | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant en BD | Sí | RLS fijado con `set_rls_context()` usando el `organization_id` del torneo público; las proyecciones filtran por torneo visible y organización activa. |
| §2.2 App sin BYPASSRLS | Sí | Sin cambios de privilegios; las migraciones 029, 030 y 031 solo crean/reemplazan vistas y conceden `SELECT` a `bracket_app`, con `REVOKE` de `PUBLIC`. |
| §2.3 Lo publicado es inmutable | Sí | Solo lecturas; no se editan versiones ni resultados. |
| §2.4 Historial de esquema append-only | Sí | Tres migraciones nuevas (029, 030, 031); no se edita ninguna aplicada. |
| §2.5 Lo público es proyección mínima | Sí | No se exponen documentos, fechas de nacimiento, edad, asistencias ni sanciones; foto solo con inscripción **vigente** y consentimiento (RF-007, RF-034); la formación no publicada nunca se usa (D8). |
| §2.6 Sin secretos por defecto fuera de dev | No | Sin variables nuevas. |
| §2.7 Admin global separado y auditado | No | Sin cambios. |
| §2.8 Nada terminado sin verificación | Sí | Una prueba por caso límite, lista cerrada con datos reales, aislamiento sembrado y los jobs de CI declarados con su resultado real (incluido lo no ejecutado). |
| §2.9 Código de dev no llega a prod | Sí | Sin scripts de seed; los datos de prueba viven en tests opt-in. |
| §3.1 RLS en transacción antes de consulta tenant | Sí | `set_rls_context()` dentro de `db.begin()` en ambos endpoints. |
| §3.2 Backend async, módulo propio, router registrado | Sí | Funciones puras en `public_stats.py`; endpoints en el router existente. **No se declara excepción:** el umbral de 60 min es un criterio de estadística, no una regla deportiva configurable, así que la regla de configuración JSON no le aplica. |
| §3.3 Frontend usa useApi.ts | Sí | Sin llamadas directas; el resolver de ámbito es una función pura en `utils/`. |
| §3.4 Seguridad y auditorías | Sí | Sin dependencias nuevas; el bump de `node-forge` (T21) se valida con la auditoría del frontend del propio job `security`. |
| §3.5 Infraestructura y CI | Sí | `sh -n infra/postgres/migrate.sh`, `docker compose config -q`. |
| §4 Criterios obligatorios (tests, docs, CI) | Sí | Sección 7, T19–T22 de `tasks.md` y `MEMORY.md`. |

## 10. Notas de despliegue

- **Orden: 029 → 030 → 031 → código.** Las tres migraciones son aditivas: la imagen anterior convive con ellas (no selecciona las columnas ni las vistas nuevas), pero el código nuevo necesita las tres (contexto RLS, lectura de eventos/segmentos/plantillas y formaciones publicadas).
- Sin *backfill* y sin reescritura de filas. `init/01`–`init/03` no se tocan; el volumen limpio (`init/00-03` → 001-031) termina con el mismo esquema que una base migrada, que es lo que comprueban `test_migration_029.py`, `test_migration_030.py` y `test_migration_031.py`.
- **Sin rollback:** cualquier defecto se corrige con una migración nueva (*forward-fix*).
- Los runbooks de despliegue (029, 030 y 031) deben quedar en `AGENTS.md` y en el `README.md` (T22).
