# Plan — Spec 052: Estadísticas adicionales (F17)

Estado: aprobado el 2026-11-27 («Apruebo el plan y las tareas, empieza por T1»). Spec aprobada el 2026-11-27 («Apruebo la spec 052»).

## 1. Resumen

- **Migración 070:** tipo de hecho `penalty_saved` y columna `player_in_position` en las tres tablas de hechos (acta, versiones rectificadas y borrador en vivo); `v_public_match_events` añade la columna al final.
- **Acta:** `MatchEventPayload` acepta `penalty_saved` y `player_in_position`; la posición se valida contra el catálogo de la modalidad del partido. Se persiste en cierre clásico, en vivo y rectificación.
- **Cálculo puro:** `compute_player_stats` añade `minutes_played`, `main_position` y `penalties_saved` (RF-001–RF-006).
- **Superficies:** `player-stats`, ficha pública, CSV de estadísticas, acta exportada, Workspace (formularios y tabla pública) y copia de referencia de `v1`.

## 2. Decisiones

| # | Decisión | Alternativa descartada y motivo |
|---|---|---|
| D1 | `player_in_position VARCHAR(20)` como **columna** nueva, con `CHECK (player_in_position IS NULL OR (event_type = 'substitution' AND player_in_position ~ '^[A-Z0-9_]+$'))`. | Clave en `metadata`: hoy `metadata` solo admite `red_card_type` (API y `CHECK` del borrador en vivo); abrirla mezcla dos contratos y complica la vista pública. |
| D2 | `event_type = 'penalty_saved'`: `team_id` = equipo que defiende el penal, `player_id` = quien lo ataja. Sin `beneficiary_team_id`, asistencia, par de sustitución ni `metadata`. Se valida como cualquier hecho de jugador: inscrito en la plantilla del equipo y en campo en ese minuto. No exige que ocupe `GK`. | Exigir `GK` en la formación: una formación no publicada o desactualizada bloquearía el acta; la spec solo pide «el portero que lo ataja». |
| D3 | La posición de entrada se valida contra `positions_for_game_format(game_format)`: la unión de `FORMATION_SLOTS` de las formaciones de la modalidad del partido (`rules_config.game_format`, 044). Fuera del catálogo → 422 sin guardar (RF-008). | Validar contra la formación vigente del equipo: no siempre hay formación, y DA-3 dice «catálogo de la modalidad». |
| D4 | `POSITION_LINES` en `rule_contract.py`: código → `goalkeeper` / `defender` / `midfielder` / `forward`. `GK` → portero; `CB`, `LCB`, `RCB`, `LB`, `RB`, `LWB`, `RWB` → defensa; `CDM_L`, `CDM_R`, `CM`, `CM_L`, `CM_R`, `LCM`, `RCM`, `LM`, `RM`, `CAM` → centrocampista; `ST`, `ST_L`, `ST_R`, `LW`, `RW` → delantero. Un test exige que cubra exactamente los códigos de `FORMATION_SLOTS`. | Calcular la línea por el índice del código en la formación: frágil y no documentado. |
| D5 | Las respuestas públicas usan los códigos `goalkeeper`/`defender`/`midfielder`/`forward`; el frontend los traduce. Campos nuevos con valor por defecto (`0` / `null`): cambio compatible de `v1` según `compat.py`. | Texto ES/EN en la API: la API pública no localiza campos de datos. |
| D6 | La migración localiza cada `CHECK` de `event_type` sin nombre por `pg_constraint` (`contype = 'c'`, definición con `event_type` e `IN`/`ANY`), exige exactamente uno por tabla y lo sustituye por uno con nombre, como la 063. | Suponer el nombre autogenerado: no está garantizado entre volúmenes. |
| D7 | Bloques: A (backend, T1–T5) y B (Workspace, sitio público, E2E y documentación, T6–T8), como en las 048–050. | Un solo PR: demasiado grande para revisar. |

## 3. Base de datos — migración `070_additional_player_stats.sql`

En `match_events`, `match_report_version_events` y `match_live_events`:

1. Sustituir el `CHECK` de `event_type` por `chk_<tabla>_event_type` con los ocho tipos (D6).
2. `ADD COLUMN IF NOT EXISTS player_in_position VARCHAR(20)` y `chk_<tabla>_player_in_position` (D1).

`CREATE OR REPLACE VIEW public.v_public_match_events` con la misma salida de la 060 más `player_in_position` al final (ambas ramas del `UNION ALL`). Sin tablas, políticas RLS ni permisos nuevos: las tablas ya tienen RLS por organización y la vista conserva `security_barrier` y sus permisos.

Verificación (`tests/test_migration_070.py`, BD): sobre un volumen limpio y sobre uno migrado hasta la 069 con hechos existentes; los hechos antiguos siguen siendo válidos y leen `NULL`; `penalty_saved` se acepta en las tres tablas; una posición en un hecho que no es sustitución o con minúsculas se rechaza; la vista devuelve la columna; aplicar la migración dos veces no falla.

## 4. Backend

- `rule_contract.py`: `POSITION_LINES` (D4) y `positions_for_game_format(game_format) -> frozenset[str]` (D3).
- `matches/schemas.py`: `EVENT_TYPES` += `"penalty_saved"`; `player_in_position: str | None = Field(default=None, max_length=20, pattern="^[A-Z0-9_]+$")`, solo en `substitution` (422 en otro tipo). El comentario del catálogo cerrado cita la 052 como ampliación de la 015.
- `matches/service.py`: validación del catálogo (D3) dentro de la validación del acta; `INSERT INTO match_events` y la comparación de inmutabilidad incluyen la columna. `penalty_saved` sigue el camino genérico (plantilla y en campo).
- `matches/live_service.py` y `live_close.py`: el borrador en vivo guarda y devuelve `player_in_position`; la revisión y el cierre lo copian.
- `rectifications/service.py`: `INSERT INTO match_report_version_events` con la columna; el diff ya recorre `MatchEventPayload.model_fields`.
- `rules_engine/engine.py`, sanciones y fair play: sin cambios; un test fija que `penalty_saved` no altera marcador, clasificación, sanciones ni fair play (RF-010).
- `tournaments/public_timeline.py`: sin cambios; `PUBLIC_TIMELINE_TYPES` ya excluye el tipo nuevo y el modelo no tiene la posición (RF-015). Test de regresión.
- `tournaments/public_stats.py` (puro, §5) y `schemas.py`:
  - `PublicPlayerStatsResponse` += `minutes_played: int = 0`, `main_position: MainPosition | None = None`, `penalties_saved: int = 0`.
  - `PublicPlayerProfileTotalsResponse` += `minutes_played`, `penalties_saved`; `PublicPlayerProfileTournamentResponse` += `main_position`.
- `tournaments/routes/public.py` (`player-stats` y ficha) y `exports/service.py`: añaden `match_date` a la lectura de partidos y `player_in_position` a la de hechos, dentro de la misma transacción con `set_rls_context()`.
- `exports/catalog.py` y `builders.py`: columnas finales «Minutos jugados», «Posición principal», «Penales atajados» (ES/EN) en el CSV de estadísticas de jugadores (RF-013); etiqueta «Penal atajado» y detalle «Entra: Nombre · Posición: LCB» en el acta CSV/PDF (RF-012).
- `docs/api-publica/openapi-v1.json` regenerada con `--update` (compatible), ejemplos y una entrada fechada en el historial de las dos guías (RF-014).

## 5. Algoritmo (`compute_player_stats`)

```
played(m) = confirmado(m) y resolución ∈ {regular, extra_time, penalties}
para cada partido m con played(m):
  segs = segmentos(m); primero = min(segment_number)
  para cada equipo t de m:
    pubs = formaciones publicadas de t en m
    subs = sustituciones no anuladas de t en m
    si existe f ∈ pubs con segment_number == primero:          # DA-1
      titulares = jugadores de f con is_starter
      para p ∈ titulares ∪ {s.player_in_id | s ∈ subs}:
        minutos[p] += _player_minutes(m, p, hechos(m), segs, started = p ∈ titulares)
    si pubs no está vacío:                                      # DA-3
      para cada f ∈ pubs, para cada titular p con position_slot: lineas[p][m] ∪= {LINEA[slot]}
      para cada s ∈ subs con player_in_position: lineas[s.player_in_id][m] ∪= {LINEA[pos]}
para cada hecho penalty_saved no anulado de un partido confirmado: atajados[player_id] += 1
main_position(p) = argmax_l |{m : l ∈ lineas[p][m]}|
  empate → la línea cuyo partido más reciente es mayor por (match_date no nula, match_date, str(match_id))
  sin líneas → null
```

Se mantienen las exclusiones de hoy: jugador fuera de la plantilla cargada, hecho anulado, partido sin resultado confirmado. Walkover y resolución administrativa no suman minutos ni posiciones (CL-4). La ficha usa la misma función por torneo, así que coincide con la tabla (RF-004).

## 6. Frontend

- **Workspace** (todo vía `useApi.ts`):
  - `utils/matchEvents.ts`: `penalty_saved` en `EVENT_TYPES`, con los campos equipo y jugador.
  - `utils/substitutions.ts` / `DraftEvent`: `player_in_position` opcional; opciones = posiciones de las formaciones de la modalidad del partido (`FORMATIONS_BY_GAME_FORMAT` + `FORMATIONS_GRID`), con `positionLabel`.
  - `MatchEventsSection.vue`, `MatchLiveSection.vue` (`matchLiveCapture.ts`) y `RectificationEditor.vue`: selector «Posición de entrada (opcional)» y tipo «Penal atajado»; el acta y el historial muestran ambos (RF-011, RF-012).
- **Sitio público:** `PublicPlayerStatsTable.vue` añade «Min.», «Pos.» y «Pen. at.» con `<abbr title>`; `utils/publicPlayerProfile.ts` añade minutos y penales atajados a los totales y la posición por torneo.
- **i18n ES/EN** en `useI18n.ts`: tipo de hecho, selector, líneas (`public.line.goalkeeper`…) y cabeceras.

## 7. Tests

- **Puros backend:** `test_public_stats_additional.py` — minutos con y sin alineación publicada (DA-1), suplente que entra y sale o es expulsado (CL-2), prórroga, walkover/administrativa (CL-4), posición principal por línea y desempate (DA-2), entrada sin posición (CL-1), portero de campo que entra como `GK` (CL-3), formación no publicada no aporta posiciones (DA-3), penales atajados y anulados, jugador en dos equipos (CL-7), acta rectificada (RF-006) y rendimiento de 32 equipos/300 partidos < 1 s (RNF-003). `test_rule_contract.py`: `POSITION_LINES` cubre todo el catálogo.
- **Esquema:** `test_match_event_payload*.py` — `penalty_saved` válido, posición solo en sustitución, patrón.
- **BD:** `test_migration_070.py`; cierre clásico, en vivo y rectificación guardan y devuelven la posición y el penal atajado, posición fuera del catálogo → 422 sin escritura (RF-008); marcador, clasificación, sanciones y fair play iguales con y sin `penalty_saved` (RF-010); cronología sin cambios (RF-015); `player-stats` y ficha con los campos y el mismo 404 (RF-016); CSV con las columnas nuevas.
- **Contrato:** `test_public_field_allowlist.py` (lista cerrada ampliada solo con los tres campos), `test_public_api_compat.py` y `--check`, ejemplos de las guías.
- **Frontend:** `node --test`/vitest de `matchEvents`, `substitutions`, `publicPlayerProfile` y componentes; typecheck, lint y build.
- **E2E:** `operationFlow.spec.ts` (sustitución con posición y penal atajado en el acta clásica) y `public-polish.spec.ts` (columnas nuevas en tabla y ficha), con axe en los dos temas a 1440 y 390 px.

## 8. Cobertura

| Parte | RF |
|---|---|
| Migración 070 | RF-007, RF-009, RNF-002 |
| Esquema, validación y persistencia | RF-007–RF-010 |
| `compute_player_stats` | RF-001–RF-006, RNF-001, RNF-003 |
| Rutas públicas y ficha | RF-001–RF-004, RF-016 |
| Exportaciones | RF-012, RF-013 |
| Referencia `v1` y guías | RF-014, RF-015 |
| Workspace y sitio público | RF-004, RF-011, RF-012, RNF-004 |

## 9. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 1. Aislamiento multi-tenant por RLS | Sí | Sin tablas nuevas; columnas en tablas con RLS; lecturas tras `set_rls_context()`; test del mismo 404 entre organizaciones. |
| 2. Reglas configurables y motor reproducible | Sí | `engine_version` 2026.1 sin cambios; `penalty_saved` no entra en el motor; test de RF-010. |
| 3–4. Fases e inmutabilidad del acta | Sí | Los hechos nuevos siguen las mismas reglas de inmutabilidad y versiones; la rectificación conserva el original. |
| 5. Lo público es una proyección mínima | Sí | Solo tres campos nuevos en la lista cerrada; minutos solo con alineación publicada y posiciones solo de formaciones publicadas; sin documentos ni fechas de nacimiento; fotos sin cambios. |
| Migraciones append-only | Sí | `070` nueva; ninguna existente se edita. |
| §3.6 Rectificación de actas | Sí | La versión rectificada guarda la columna; el cálculo usa la versión vigente. |
| Todo cambio con pruebas | Sí | §7, en rojo antes de implementar. |
| Frontend vía `useApi.ts`, Composition API | Sí | Sin llamadas nuevas fuera de `useApi`; componentes `<script setup>`. |
| ES/EN y accesibilidad | Sí | Textos en los dos idiomas; E2E con axe en los dos temas. |
| Documentación coherente | Sí | T8: README, AGENTS, manual, informe (F17), guías de la API y MEMORY. |
