# Plan — Spec 038: Fichas públicas de jugador

Estado: aprobado por el usuario el 2026-11-16 («Apruebo plan, tareas y aclaraciones»).

## 1. Alcance y dependencias

- Depende de **020** (matriz pública y lista cerrada), **022** (cálculo de estadísticas, portería imbatida, consentimiento de foto por inscripción, RF-007/RF-033/RF-034), **029** (`organization_id` en `v_public_tournaments`), **033** (versión vigente del acta) y **037** (cronología).
- No cambia `engine_version` (2026.1), actas, rectificación, permisos ni el consentimiento en sí. No añade escrituras, outbox ni eventos de tiempo real.
- **Cadena de esquema:** punto de partida **060**; esta spec aporta **061**, aditiva y sin rollback (*forward-fix*).
- Añade **una lectura pública nueva** (la ficha) y **un campo** (`profile_available`) en dos modelos públicos existentes (cambio no aditivo 3 de la spec).

## 2. Archivos y responsabilidades

### Base de datos

| Archivo | Responsabilidad |
|---|---|
| `infra/postgres/migrations/061_public_player_profile_rosters.sql` (**nueva**) | Vista interna `public.v_public_player_profile_rosters` (`security_barrier`): por inscripción de torneo visible (join con `v_public_tournaments`, que ya exige versión publicada y organización activa) devuelve `organization_id`, `tournament_id`, `tournament_name`, `start_date`, `team_id`, `team_name`, `player_id`, `first_name`, `last_name`, `is_active`, `valid_from`, `photo_consent` y `photo_object_key` solo si hay consentimiento. `REVOKE ALL FROM PUBLIC`, `GRANT SELECT` solo a `bracket_app`. Sin tablas, columnas, datos ni políticas nuevas. Es proyección interna: ninguna columna sale tal cual en una respuesta. |

### Backend

| Archivo | Responsabilidad |
|---|---|
| `backend/app/modules/tournaments/public_player_profile.py` (**nuevo**) | Funciones puras sin BD: `representative_inscriptions` (CL-11), `authorized_tournaments` (DA-1, orden RF-010, tope 50), `profile_available_ids` (RF-009), `profile_photo_candidate` (RF-007, CL-10), `build_player_profile` (filas por torneo con ceros si no hay partidos, CL-7, y totales). |
| `backend/app/modules/tournaments/schemas.py` | Modelos nuevos `PublicPlayerProfileResponse`, `PublicPlayerProfileTournamentResponse`, `PublicPlayerProfileTotalsResponse` con `extra="forbid"`; `profile_available: bool = False` en `PublicPlayerStatsResponse` y `PublicTimelinePlayerResponse`. |
| `backend/app/modules/tournaments/routes/public.py` | `GET /tournaments/public/players/{player_id}` (ver §4). `player-stats` y `timeline` leen `v_public_player_profile_rosters` del torneo para calcular `profile_available`; `player-stats` ordena además sus inscripciones (vigente primero, luego `valid_from` descendente) para que el equipo atribuido sea determinista y coincida con la ficha (RF-004). |

### Frontend

| Archivo | Responsabilidad |
|---|---|
| `frontend/app/utils/publicPlayerProfile.ts` (**nuevo**) | Tipos del contrato, ruta de la ficha y formato de totales/filas. |
| `frontend/app/pages/players/[id].vue` (**nueva**) | Página pública sin sesión, carga con `useAsyncData` + `useApi` como `tournaments/[id].vue`: cabecera (foto o iniciales, nombre), totales y tabla de trayectoria con enlace a cada torneo; estado «no encontrado» y error. Tokens 029, ambos temas 032, `PublicPreferences`. |
| `frontend/app/components/public/PublicPlayerStatsTable.vue` | El nombre es `NuxtLink` a la ficha solo si `profile_available`; si no, texto como hoy. |
| `frontend/app/components/public/PublicMatchTimeline.vue` + `utils/publicTimeline.ts` | Igual para `player` y `player_in`; navegar cierra el diálogo. |
| `frontend/app/pages/workspace/tournaments/[id]/rosters.vue` | Texto de ayuda junto al control de consentimiento de imagen: también publica la ficha (RF-012). |
| `frontend/app/composables/useI18n.ts` | Textos ES/EN de la ficha, totales, columnas, estados y ayuda del consentimiento. |
| `frontend/app/composables/useApi.ts` | Sin cambios. |

### Tests

| Archivo | Responsabilidad |
|---|---|
| `backend/tests/test_public_player_profile.py` (puro) | CL-1–CL-11, orden y tope, foto, totales, indicador. |
| `backend/tests/test_migration_061.py` (opt-in DB) | Columnas, `security_barrier`, privilegios, foto nula sin consentimiento, torneo no visible y organización inactiva excluidos; cadena 001→061 y salto 060→061. |
| `backend/tests/test_public_player_profile_endpoint.py` (opt-in DB) | Ficha con dos torneos y dos organizaciones; cifras iguales a `player-stats` de cada torneo (RF-004), rectificación vigente, retiro de consentimiento (RF-008), inscripción retirada (CL-2), 404 indistinguible (RF-002) y `profile_available` en `player-stats` y `timeline`. |
| `test_public_field_allowlist.py`, `test_public_access_matrix.py`, `test_tournament_routes_order.py` (modificados) | Lista cerrada con los modelos nuevos y `profile_available`; ruta nueva en la matriz; recuento 33 → 34. |
| `frontend/tests/public-player-profile.test.ts` (nuevo) + `public-stats.test.ts`, `public-timeline.test.ts` | Página, enlaces condicionados, ES/EN, accesibilidad. |
| `frontend/e2e/public-polish.spec.ts` + fixtures | Ficha a 1440/390/800 px en ambos temas con contrato ficticio, sin desbordamiento; enlace desde estadísticas. |

## 3. Funciones puras

```python
def representative_inscriptions(rows) -> dict[tournament_id, row]:
    # CL-11: vigente; si no hay, la retirada con valid_from más reciente (desempate por team_id).

def authorized_tournaments(rows, limit=50) -> list[row]:
    # DA-1: representativas con photo_consent; orden start_date desc, tournament_id (RF-010); tope RNF-001.

def profile_available_ids(rows) -> set[player_id]:
    # RF-009: jugadores cuya representativa en el torneo tiene consentimiento.

def profile_photo_candidate(rows) -> row | None:
    # RF-007/CL-10: autorizada vigente con foto, de torneo más reciente.

def build_player_profile(player, tournaments, stats_by_tournament) -> dict:
    # Filas por torneo con las cinco cifras de compute_player_stats (022) o ceros; totales = suma.
```

Las cifras por torneo salen de `compute_player_stats` de la 022 sin cambios, llamada una vez por torneo con los partidos, eventos, segmentos y formaciones de ese torneo.

## 4. Interfaz

```
GET /tournaments/public/players/{player_id}
  response_model=PublicPlayerProfileResponse
  PublicPlayerProfileResponse = {
    player_id: UUID, first_name: str, last_name: str, photo_url: str | null,
    totals: PublicPlayerProfileTotalsResponse,
    tournaments: list[PublicPlayerProfileTournamentResponse]
  }
  PublicPlayerProfileTournamentResponse = {
    tournament_id: UUID, tournament_name: str, team_id: UUID, team_name: str,
    matches_played: int, goals: int, yellow_cards: int, red_cards: int, clean_sheets: int
  }
  PublicPlayerProfileTotalsResponse = {
    matches_played: int, goals: int, yellow_cards: int, red_cards: int, clean_sheets: int
  }
PublicPlayerStatsResponse      += profile_available: bool
PublicTimelinePlayerResponse   += profile_available: bool
```

Flujo de la ficha, con número fijo de consultas (RNF-001):
1. `organization_id` del jugador en `v_public_player_profile_rosters`; sin filas → 404.
2. `set_rls_context` con esa organización, dentro de `db.begin()`.
3. Inscripciones del jugador → torneos autorizados (puro); ninguno → 404 (RF-002, RF-008).
4. En lote (`ANY(:tournament_ids)`): partidos de `v_public_matches` donde juega algún equipo del jugador en ese torneo, y sus eventos (`v_public_match_events`, versión vigente), segmentos y formaciones (`v_public_match_formations`).
5. Cálculo por torneo con `compute_player_stats` y firma de la foto en lote tras cerrar la transacción (`sign_photo_rows`, `policy="null"`).

El 404 es el mismo `{"detail": …}` de las demás lecturas públicas para: jugador inexistente, sin inscripción autorizada, de organización inactiva o con torneos no visibles. UUID inválido → 422 estructural.

## 5. Decisiones justificadas

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D1 | Ruta bajo `/tournaments/public/players/{player_id}`. | Router nuevo `/public/players`. | Mismo prefijo que el proxy ya limita para lecturas públicas (§3.4) y mismo router; no colisiona con `/public/{tournament_id}` porque el segundo segmento no es literal. |
| D2 | Vista interna 061 con `valid_from` y `start_date`. | Ampliar `v_public_tournament_rosters`. | Esa vista es fuente de la 022/037; una nueva evita tocar sus consumidores y ya filtra con `v_public_tournaments` (versión publicada). |
| D3 | Reutilizar `compute_player_stats` por torneo. | Agregación SQL nueva. | RF-004: mismas definiciones y mismas cifras que la tabla de la 022. |
| D4 | Solo partidos de los equipos del jugador. | Todos los partidos de cada torneo. | Las cifras del jugador solo dependen de esos partidos; acota el volumen (RNF-001). |
| D5 | `profile_available` booleano en las dos respuestas. | Pedir la ficha para saber si existe. | DA-4 exige saber al pintar si el nombre enlaza; un booleano es el mínimo y no revela otros torneos (CL-1). |
| D6 | Sin caché pública. | Caché por jugador. | RF-008: retirar el consentimiento surte efecto en la siguiente lectura. |

## 6. Estrategia de tests

- **Puros:** `test_public_player_profile.py` y `public-player-profile.test.ts`.
- **Opt-in DB** (`RUN_DATABASE_TESTS=1`): migración 061 y endpoint, con dos organizaciones, rectificación, retiro de consentimiento y comparación con `player-stats`.
- **E2E:** extensión de `public-polish.spec.ts` (contrato ficticio, sin escrituras).
- **CI:** `cd backend && pytest -q && ruff check . && bandit -q -r app -ll`; `cd frontend && pnpm run lint && pnpm test && pnpm run typecheck && pnpm run typecheck:e2e && pnpm run build`; `sh -n infra/postgres/migrate.sh`; `docker compose config -q`.

## 7. RF cubiertos por parte

| Parte | RF |
|---|---|
| Migración 061 | RF-002, RF-003, RF-006, RF-007 |
| Funciones puras | RF-003, RF-007, RF-009, RF-010, CL-1–CL-11 |
| Endpoint y modelos | RF-001, RF-002, RF-004–RF-008, RF-011, RNF-001, RNF-004 |
| `profile_available` | RF-009 |
| Frontend | RF-009, RF-012, RNF-002, RNF-003 |
| Documentación | RF-012, criterio 8 |

## 8. Exposición pública

Campos exactos: los de §4. No incluyen documentos, fecha de nacimiento, edad, dorsal, posición, clave de objeto, `photo_consent`, `organization_id`, `is_active`, fechas de inscripción, asistencias, faltas, sanciones, suspensiones, motivos ni auditoría. Cambios no aditivos declarados en la spec: ficha multi-torneo dentro de una organización, alcance del consentimiento de imagen y `profile_available`.

## 9. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §1.3 Privacidad con base y consentimiento | Sí | Solo torneos con consentimiento de imagen de la inscripción representativa; retirarlo surte efecto en la siguiente lectura. |
| §2.1 Aislamiento por tenant en BD | Sí | `set_rls_context()` con la organización del jugador; vistas filtradas por torneo visible y organización activa; prueba con dos organizaciones. |
| §2.2 Sin BYPASSRLS | Sí | 061 solo crea una vista; `GRANT SELECT` a `bracket_app`, `REVOKE` de `PUBLIC`. |
| §2.3 Lo publicado es inmutable | Sí | Solo lectura de la versión vigente. |
| §2.4 Esquema append-only | Sí | Migración nueva 061. |
| §2.5 Proyección mínima | Sí | Lista cerrada de §8; foto solo con consentimiento e inscripción vigente. |
| §2.6 Sin secretos por defecto | No | Sin variables nuevas. |
| §2.7 Administración global | No | Sin cambios. |
| §2.8 Verificación | Sí | Tests por RF/CL, jobs de CI y lo no ejecutado declarado. |
| §2.9 Código de desarrollo | Sí | Datos de prueba solo en tests y fixtures E2E. |
| §3.1 RLS en la transacción | Sí | Todo dentro de `db.begin()`; firma fuera. |
| §3.2 Backend | Sí | Módulo existente, async, sin efectos secundarios. |
| §3.3 Frontend | Sí | `useApi`; página pública sin sesión. |
| §3.4 Seguridad | Sí | Sin dependencias nuevas; el proxy limita la ruta con el resto de `/tournaments/public`. |
| §4 Criterios obligatorios | Sí | T10 y `MEMORY.md`. |

## 10. Notas de despliegue

- Orden: **061 → código**. La imagen anterior convive con la 061.
- Sin *backfill* ni rollback; *forward-fix*. Runbook breve en README y AGENTS (T10).
