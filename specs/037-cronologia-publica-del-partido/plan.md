# Plan — Spec 037: Cronología pública del partido

Estado: aprobado por el usuario el 2026-11-15 («Apruebo plan y tareas»).

## 1. Alcance y dependencias

- Depende de **020** (matriz pública y lista cerrada), **022** (vistas 030 de eventos, segmentos y plantillas; criterio de eventos huérfanos), **033** (versión vigente del acta y `rectified_at`) y **036** (proyección del `live`/`suspended`, que no cambia).
- No cambia `engine_version` (2026.1), el catálogo 015, el cierre 017, la rectificación 033 ni permisos. No añade escrituras, eventos de outbox ni eventos de tiempo real.
- **Cadena de esquema:** punto de partida **059**; esta spec aporta **060**, aditiva y sin rollback (*forward-fix*).
- Añade **una lectura pública nueva**, con modelos propios, cargada bajo demanda por partido (RNF-004). No añade campos a los modelos públicos existentes (RNF-003).

## 2. Archivos y responsabilidades

### Base de datos

| Archivo | Responsabilidad |
|---|---|
| `infra/postgres/migrations/060_public_match_event_segments.sql` (**nueva**) | `CREATE OR REPLACE VIEW public.v_public_match_events` repitiendo la definición vigente de la 035 y **añadiendo al final** la columna `segment_id` (las dos ramas de `current_events` ya la tienen en sus tablas origen). Mantiene `security_barrier`, filtros de torneo visible/versión publicada/organización activa, `REVOKE ALL FROM PUBLIC` y `GRANT SELECT` solo a `bracket_app`. Sin datos nuevos ni cambio de filas. |

### Backend

| Archivo | Responsabilidad |
|---|---|
| `backend/app/modules/tournaments/public_timeline.py` (**nuevo**) | Funciones puras sin BD ni reloj: `timeline_availability`, `build_public_timeline`, `timeline_sort_key`, `public_red_card_type`, `timeline_matches_score`. |
| `backend/app/modules/tournaments/schemas.py` | Modelos `PublicTimelinePlayerResponse`, `PublicTimelineEventResponse`, `PublicMatchTimelineResponse` con `extra="forbid"`. |
| `backend/app/modules/tournaments/routes/public.py` | `GET /tournaments/public/{tournament_id}/matches/{match_id}/timeline` con `response_model=PublicMatchTimelineResponse`. Una transacción: `_ensure_public_tournament`, contexto RLS con el `organization_id` de `v_public_tournaments`, partido en `v_public_matches` o suspendido en `v_match_live_public_selection`, eventos de `v_public_match_events`, segmentos de `v_public_match_segments` y nombres de `v_public_tournament_rosters`. |
| `backend/app/main.py` | Sin cambios (router ya registrado). |

### Frontend

| Archivo | Responsabilidad |
|---|---|
| `frontend/app/utils/publicTimeline.ts` (**nuevo**) | Tipos del contrato y funciones puras: formato del minuto público (`45+2'`), separadores por segmento (solo si hay más de uno), clave i18n por tipo y roja, y decisión de recarga cuando cambia el partido abierto. |
| `frontend/app/components/public/PublicMatchTimeline.vue` (**nuevo**) | Diálogo accesible con la cronología: lista única, separadores, icono con nombre accesible y texto por tipo, autogol con beneficiado, sustitución sale/entra, estados `pending`/`not_played`/vacío/error y aviso de descuadre. Tokens 029, ambos temas 032. |
| `frontend/app/pages/tournaments/[id].vue` | Disparador «Cronología» en las tarjetas de partidos `finished` (mismas ubicaciones que el de alineación), carga mediante `useApi` al abrir y recarga cuando el refresco público existente cambia `status`, marcador o `rectified_at` del partido abierto. |
| `frontend/app/composables/useI18n.ts` | Textos ES/EN: título, tipos, «roja directa», «roja por doble amarilla», «autogol (a favor de …)», «sale/entra», segmento N, estados y aviso. |
| `frontend/app/composables/useApi.ts` | Sin cambios. |

### Tests

| Archivo | Responsabilidad |
|---|---|
| `backend/tests/test_public_timeline.py` (puro) | Disponibilidad por estado/resolución, tipos permitidos y excluidos (`foul`, asistencia), orden estable, roja clasificada/histórica, autogol, sustitución, huérfanos, coincidencia con el marcador, prórroga/penales. |
| `backend/tests/test_migration_060.py` (opt-in DB) | Columna `segment_id` al final, `security_barrier`, privilegios, cadena limpia 001→060 y salto 059→060 con checksums estables. |
| `backend/tests/test_public_timeline_endpoint.py` (opt-in DB) | Endpoint con datos sembrados: disponibilidad, versión vigente tras rectificación, anulados, 404 indistinguible (torneo no visible, organización inactiva, cancelado, partido de otro torneo), aislamiento con dos organizaciones y lista cerrada con datos reales. |
| `backend/tests/test_public_field_allowlist.py` / `test_public_access_matrix.py` (modificados) | Tres modelos nuevos en la lista cerrada; ruta nueva en la matriz (anónima, 404 indistinguible, 422 de UUID inválido). |
| `frontend/tests/public-timeline.test.ts` (nuevo) | Utilidades puras y componente: minuto, separadores, textos ES/EN, estados, accesibilidad (rol diálogo, nombres accesibles, foco), recarga por cambio del partido. |
| `frontend/e2e/public-polish.spec.ts` + fixtures (modificados) | Diálogo de cronología a 1440/390 px en ambos temas con contrato ficticio, sin desbordamiento. |

## 3. Funciones puras

```python
def timeline_availability(status: str, resolution_type: str | None) -> Literal["pending", "not_played", "available"]:
    # scheduled/live/suspended -> pending (RF-002)
    # administrative_resolution, o finished con resolution_type walkover/administrative -> not_played (RF-003)
    # finished con regular/extra_time/penalties o NULL histórico -> available (RF-001)

PUBLIC_TYPES = {"goal", "penalty_goal", "own_goal", "yellow_card", "red_card", "substitution"}  # RF-006

def public_red_card_type(event_type, metadata) -> Literal["direct_red", "double_yellow_red"] | None:
    # solo red_card; valor del acta si es uno de los dos; si falta o es otro -> None (RF-008)

def timeline_sort_key(event, segment_number) -> tuple:
    return (segment_number, event.minute, event.added_minute, event.id)  # RF-009

def build_public_timeline(events, segments, names, match) -> PublicTimeline:
    # descarta is_voided y tipos fuera de PUBLIC_TYPES
    # descarta huérfanos: segmento ausente, equipo no participante, jugador/entrante/saliente sin nombre público (RF-011)
    # nunca lee assist_player_id ni otras claves de metadata
    # segment_numbers = todos los segmentos públicos del partido, ascendentes (DA-4)
    # score_consistent = timeline_matches_score(eventos publicados, match)

def timeline_matches_score(events, match) -> bool:
    # goal/penalty_goal suman a team_id; own_goal suma a beneficiary_team_id
    # compara con home_score/away_score finales (prórroga incluida, penales excluidos) (RF-010)
```

## 4. Interfaz

```
GET /tournaments/public/{tournament_id}/matches/{match_id}/timeline
  response_model=PublicMatchTimelineResponse
  PublicMatchTimelineResponse = {
    match_id: UUID,
    availability: "pending" | "not_played" | "available",
    score_consistent: bool,
    segment_numbers: list[int],
    events: list[PublicTimelineEventResponse]
  }
  PublicTimelineEventResponse = {
    event_type: "goal" | "penalty_goal" | "own_goal" | "yellow_card" | "red_card" | "substitution",
    minute: int, added_minute: int, segment_number: int,
    team_id: UUID, beneficiary_team_id: UUID | null,
    red_card_type: "direct_red" | "double_yellow_red" | null,
    player: PublicTimelinePlayerResponse,
    player_in: PublicTimelinePlayerResponse | null
  }
  PublicTimelinePlayerResponse = { player_id: UUID, first_name: str, last_name: str }
```

- `pending` y `not_played` devuelven `events=[]`, `segment_numbers=[]` y `score_consistent=true`; nunca leen eventos.
- En una sustitución `player` es quien sale y `player_in` quien entra; en el resto `player_in` es `null`.
- Torneo no visible, organización inactiva, partido cancelado, inexistente o de otro torneo: el mismo 404 de las lecturas públicas.
- La pantalla pública añade el disparador «Cronología» solo en partidos `finished`; el diálogo distingue vacío, `not_played` y error de carga.

## 5. Decisiones justificadas

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D1 | Lectura propia por partido, cargada al abrir. | Incrustar los eventos en `PublicMatchResponse`. | RNF-003 (contrato existente intacto) y RNF-004 (abrir el torneo no carga todas las cronologías). |
| D2 | Migración 060 añade `segment_id` al final de `v_public_match_events`. | Vista pública nueva duplicando la resolución de versión vigente. | Una sola fuente de «versión vigente» para estadísticas y cronología (033 RF-021); `CREATE OR REPLACE` solo admite añadir al final, sin romper consumidores. |
| D3 | Nombres desde `v_public_tournament_rosters`, sin dorsal ni foto en la respuesta. | Leer `players` o reutilizar `PublicLineupPlayerResponse`. | Proyección mínima y DA-2 (a); el modelo de alineación lleva dorsal y foto. |
| D4 | Construcción en Python con funciones puras. | Agregación SQL. | Testear orden, huérfanos, roja histórica y coincidencia sin base, como 022. |
| D5 | Refresco reutilizando la recarga pública existente (`MATCH_CLOSED`/`MATCH_UPDATED`/`RESYNC`/sondeo) y recargando el diálogo abierto si cambia el partido. | Evento público nuevo con hechos. | RF-014: sin canal ni evento nuevo y sin hechos por tiempo real. |
| D6 | `availability` explícita en vez de 404 para `pending`/`not_played`. | 404 para partidos sin cronología. | Un 404 confundiría «no visible» con «aún sin cronología» y rompería la indistinguibilidad de RF-004. |
| D7 | `score_consistent` como único indicador de descuadre. | Ocultar la cronología o inventar el hecho que falta. | RF-011: excluir sin fallar y avisar con texto. |

## 6. Estrategia de tests

- **Puros:** `test_public_timeline.py` (un caso por RF-001–RF-013 aplicable y por CL-1–CL-14) y `public-timeline.test.ts`.
- **Opt-in DB** (`RUN_DATABASE_TESTS=1`): migración 060 y endpoint, con dos organizaciones, rectificación, anulados y lista cerrada con datos reales.
- **E2E:** extensión de `public-polish.spec.ts` (contrato ficticio, sin escrituras).
- **CI:** `cd backend && pytest -q && ruff check . && bandit -q -r app -ll`; `cd frontend && pnpm run lint && pnpm test && pnpm run typecheck && pnpm run typecheck:e2e && pnpm run build`; `sh -n infra/postgres/migrate.sh`; `docker compose config -q`.

## 7. RF cubiertos por parte

| Parte | RF |
|---|---|
| Migración 060 | RF-005, RF-009 (segmento), RF-016 |
| Funciones puras | RF-002, RF-003, RF-005–RF-012 |
| Endpoint y modelos | RF-001, RF-004, RF-007, RF-013, RF-015, RF-016 |
| Frontend | RF-007–RF-009, RF-012–RF-014, RNF-002 |
| Documentación | RF-017 |

## 8. Exposición pública

Campos exactos: los de §4. No incluyen documentos, fecha de nacimiento, edad, dorsal, foto, asistencia, `metadata` libre, motivos, notas, sanciones, `organization_id` ni identificadores de evento, segmento o versión. `red_card_type` es la clasificación de la tarjeta (015/018), no la sanción. Cambio no aditivo declarado: nombre y apellido del jugador que entra en una sustitución.

## 9. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant en BD | Sí | `set_rls_context()` con el `organization_id` del torneo público; vistas filtradas por torneo visible y organización activa; prueba con dos organizaciones. |
| §2.2 Sin BYPASSRLS | Sí | 060 solo reemplaza una vista; `GRANT SELECT` a `bracket_app`, `REVOKE` de `PUBLIC`. |
| §2.3 Lo publicado es inmutable | Sí | Solo lectura de la versión vigente; nada edita actas ni versiones. |
| §2.4 Esquema append-only | Sí | Migración nueva 060; ninguna aplicada se edita. |
| §2.5 Proyección mínima | Sí | Lista cerrada de §8, sin documentos, fechas, edad ni fotos; asistencias y sanciones excluidas. |
| §2.6 Sin secretos por defecto | No | Sin variables nuevas. |
| §2.7 Administración global | No | Sin cambios. |
| §2.8 Verificación | Sí | Tests por RF/CL, jobs de CI y lo no ejecutado declarado. |
| §2.9 Código de desarrollo | Sí | Datos de prueba solo en tests y fixtures E2E. |
| §3.1 RLS en la transacción | Sí | Todo dentro de `db.begin()`. |
| §3.2 Backend | Sí | Módulo existente, router registrado, async; sin efectos secundarios ni outbox. |
| §3.3 Frontend | Sí | `useApi`; ruta pública sin sesión. |
| §3.4 Seguridad | Sí | Sin dependencias nuevas; proxy limita las lecturas públicas como hoy. |
| §4 Criterios obligatorios | Sí | Tareas T9–T10 y `MEMORY.md`. |

## 10. Notas de despliegue

- Orden: **060 → código**. La imagen anterior convive con la 060 (no selecciona la columna nueva).
- Sin *backfill*, sin rollback; *forward-fix*. Runbook breve en README y AGENTS (T9).
