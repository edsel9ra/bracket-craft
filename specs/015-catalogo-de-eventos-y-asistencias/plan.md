# Plan 015 — Catálogo de eventos y asistencias

Spec: `specs/015-catalogo-de-eventos-y-asistencias/spec.md` (17 RF, aprobada el 2026-10-25).
Constitución: `docs/constitution.md` v1.4.0. Contrato interno: `docs/contrato-reglas.md` (`engine_version` **2026.1**, sin cambios).

## 1. Alcance y forma del cambio

Un solo cambio de esquema (**migración 026**) y cambios de contrato aditivos en la API del acta, más la superficie del formulario en la operación del partido. No se crea módulo nuevo: todo vive en `backend/app/modules/matches/` y en `frontend/app/utils/` + `frontend/app/pages/workspace/matches/[id].vue`.

Fuera de este plan (specs 016 y 017): walkover, preflight del cierre, matriz de marcadores, orden de validación, `next_segment` e inmutabilidad del acta.

**Riesgo principal declarado:** el catálogo cerrado en los dos niveles y el identificador de cliente UUID son **rupturas** de contrato (RNF-003). Se documentan en `AGENTS.md` en la misma tanda (tarea T10) y el cliente se actualiza en T7/T8 para que no envíe nada que ahora sea 422.

## 2. Archivos y responsabilidades

### Base de datos

| Archivo | Responsabilidad |
|---|---|
| `infra/postgres/migrations/026_match_event_assists.sql` (nuevo) | Añade `match_events.assist_player_id` (UUID nula), la FK compuesta `(assist_player_id, organization_id) → players(id, organization_id)` y el `CHECK` `chk_match_event_assist` (solo en `goal`, distinto del goleador). Pre-chequeo informativo, sin *backfill*, sin tocar políticas ni grants. |
| `backend/tests/test_migration_026.py` (nuevo, opt-in) | Cadena limpia `init` + 001..026 y salto 025 → 026; forma de la columna, FK, `CHECK`, tolerancia de filas históricas sin asistencia y rechazo de una asistencia en un tipo que no sea `goal`. |

### Backend

| Archivo | Responsabilidad |
|---|---|
| `backend/app/modules/matches/schemas.py` | `EventType` como constante única; `MatchEventPayload` con `extra="forbid"`, `assist_player_id`, `client_event_id` con patrón UUID y validación por tipo (campos y claves de `metadata`). |
| `backend/app/modules/matches/errors.py` | Nueva excepción `HTTPException` de dominio `AssistPlayerInvalid` con `code = "ASSIST_PLAYER_INVALID"` (mismo patrón que `ResolutionNotEnabled`). |
| `backend/app/main.py` | Registra el manejador de `AssistPlayerInvalid` (`api.add_exception_handler(...)`), una línea; el módulo y el router ya están registrados y no cambian. |
| `backend/app/modules/matches/service.py` | `_persist_events` escribe y compara `assist_player_id` y `metadata`; `_validate_substitutions` traduce el error de asistente del motor a `AssistPlayerInvalid`; `roster_entries` sin cambios. |
| `backend/app/modules/rules_engine/substitutions.py` | `MatchEvent` gana `assist_player_id`; `replay_report_state` (vive en `matches/service.py:177`) valida pertenencia, equipo, presencia en campo y distinción del goleador del asistente con el código nuevo `ASSIST_PLAYER_INVALID` del enum puro. |
| `backend/app/modules/matches/router.py` | La consulta de eventos de `GET /{match_id}/operation` añade `me.assist_player_id`. Sin rutas nuevas. |

### Frontend

| Archivo | Responsabilidad |
|---|---|
| `frontend/app/utils/matchEvents.ts` (nuevo) | Fuente única de la UI por tipo: `EVENT_TYPES`, `eventFields(type)`, `assistCandidates(team, scorerId, players)`, `validateAssist(...)`, `isUuid(value)`, `newClientEventId(cryptoSource)`, `buildDraftEvent(form, segmentId, clientEventId)` y `eventSummary(event, resolveName)`. Todo puro. |
| `frontend/app/utils/substitutions.ts` | `DraftEvent` añade `assist_player_id`; `readDraftEvent` lo lee y **descarta** eventos con `client_event_id` que no sea UUID (borradores antiguos) y con asistente en un tipo que no lo admite. |
| `frontend/app/pages/workspace/matches/[id].vue` | Formulario por tipo, selector de asistente solo en `goal`, resumen con asistente, identificador UUID sin respaldo de texto, aviso de eventos descartados del borrador. |
| `frontend/app/composables/useI18n.ts` | Claves nuevas en español e inglés con paridad. |
| `frontend/tests/match-events.test.ts` (nuevo) | Pruebas de las funciones puras nuevas. |
| `frontend/tests/substitutions.test.ts` (existente) | Casos de `readDraftEvent`: asistente válido/ inválido, identificador no UUID descartado, evento antiguo sin asistente conservado. |

### Documentación

| Archivo | Responsabilidad |
|---|---|
| `AGENTS.md` | Catálogo por tipo, asistencia, cierre de `metadata`, `client_event_id` UUID, migración 026 y orden de despliegue. |
| `README.md` | Alcance del producto: qué pide cada evento, asistencia opcional, identificador de cliente. |

## 3. Funciones puras

Ninguna lee el reloj, el entorno, el almacenamiento ni la red. La que necesita una fuente externa la recibe como parámetro: `newClientEventId(cryptoSource)` recibe el objeto `crypto` (o un doble en la prueba) y `eventSummary(event, resolveName)` recibe el resolutor de nombres.

| Función | Firma | Dónde | Por qué es pura |
|---|---|---|---|
| `eventFields` | `(type: EventType) => EventFields` | `matchEvents.ts` | Tabla cerrada por tipo; sin estado. |
| `assistCandidates` | `(players: Player[], teamId, scorerId) => Player[]` | `matchEvents.ts` | Filtra por equipo y excluye al goleador. |
| `validateAssist` | `(assistId, scorerId, players) => AssistResult` | `matchEvents.ts` | Subconjunto cliente de RF-008. |
| `isUuid` | `(value: unknown) => boolean` | `matchEvents.ts` | Forma UUID canónica. |
| `newClientEventId` | `(crypto: CryptoLike) => string \| null` | `matchEvents.ts` | Recibe la fuente; `null` si no hay `randomUUID`. |
| `buildDraftEvent` | `(form, segmentId, clientEventId) => DraftEvent` | `matchEvents.ts` | Mapea formulario → payload sin leer estado global. |
| `eventSummary` | `(event, resolveName) => string` | `matchEvents.ts` | Texto legible; nombres por parámetro. |
| `readDraftEvent` | `(value, eventTypes, limits) => DraftEvent \| null` | `substitutions.ts` (existente, se amplía) | Sanea y valida; sin reloj. |
| `replay_report_state` | `(rosters, events, teamIds, limits) => ReportState` | `matches/service.py:177` | Ya es puro; se amplía con el asistente. |

El backend no necesita funciones nuevas de tiempo: la validación del asistente usa el estado en campo ya derivado, sin reloj.

## 4. Algoritmo y pseudocódigo

### 4.1 Validación del asistente (RF-008)

Dentro del replay canónico, de modo que se usa **el mismo** estado en campo que el resto del acta:

```
para cada evento en orden canónico (minute, added_minute, índice del acta):
    estado ← estados[evento.team_id]            # error TEAM_MISMATCH si no participa

    si evento.es_sustitucion_con_par:
        ... (sin cambios)
        continuar

    si evento.player_id es nulo: continuar

    si no estado.is_in_roster(evento.player_id): → 409 PLAYER_NOT_IN_ROSTER
    validar_player_on_field(estado, evento.player_id, minuto, añadido)   # ya existe

    si evento.assist_player_id no es nulo:
        si evento.event_type ≠ "goal":                          # defensa; el 422 ya lo impidió
            → error estructural
        si evento.assist_player_id = evento.player_id:
            → ASSIST_PLAYER_INVALID
        entrada ← entradas[evento.assist_player_id]              # mapa player_id → RosterEntry
        si entrada es nula o entrada.team_id ≠ evento.team_id:
            → ASSIST_PLAYER_INVALID
        si no estado.is_in_roster(evento.assist_player_id):
            → ASSIST_PLAYER_INVALID
        validar_player_on_field(estado, evento.assist_player_id, minuto, añadido)
            ↑ si falla (no está en campo en ese minuto) → ASSIST_PLAYER_INVALID

    si evento.event_type = "red_card": aplicar expulsión        # ya existe
```

`ASSIST_PLAYER_INVALID` se añade al enum `SubstitutionErrorCode` (puro). `CloseMatchReportService._validate_substitutions` captura `SubstitutionError` con ese código y lanza `AssistPlayerInvalid` (HTTP 409 + `code`), de modo que el resto de errores del motor conservan su 409 sin código y el módulo puro no importa HTTP.

**Orden respecto al marcador:** el replay (paso 8 del orden de la 017) ocurre antes que la coherencia de marcador (paso 11). Un asistente inválido no altera el marcador.

### 4.2 Idempotencia del evento (RF-012)

```
para cada evento de la petición:
    si client_event_id repetido en la petición → 422          # ya existe en el DTO
    buscar fila por (organización, partido, client_event_id)

    si existe:
        normalizar(metadata_fila) ← metadata_fila o {}
        normalizar(metadata_petición) ← evento.metadata o {}
        si (event_type, team_id, beneficiary_team_id, player_id,
            player_out_id, player_in_id, minute, added_minute, segment_id,
            assist_player_id, metadata_petición)
           ≠ (los mismos campos de la fila, metadata_fila):
            → 409 «inmutable»
        reutilizar la fila (no se reinserta)
    si no existe:
        INSERT ... assist_player_id, metadata
```

Consecuencia declarada: una fila histórica con `metadata` no vacía y un reintento con `metadata` vacía ahora es **409** (antes se reutilizaba en silencio).

### 4.3 Regla única de identificadores (RF-014)

```
cargar_partido(match_id, organización):
    si no existe o es de otra organización → 404

cargar_segmento(segment_id, match_id, organización):
    si no existe en ese partido y organización → 404

resolver_jugador(player_id, participantes, planilla_válida):
    si player_id ∉ planilla_válida            → 409 (mensaje de pertenencia existente)
    si el jugador es el asistente             → 409 ASSIST_PLAYER_INVALID
    si el jugador es de otra organización     → 409 (nunca 404, nunca 500 por FK)

resolver_equipo(team_id, participantes):
    si team_id ∉ participantes                → 409 (mensaje existente)
```

No se consulta `players` por `player_id` de otra organización: la pertenencia se decide contra la plantilla del partido, que ya está aislada por RLS; así el 409 es el mismo para «no existe», «existe en otra organización» y «no está inscrito».

## 5. Interfaz

### 5.1 Contrato del evento (petición de cierre, `events[]`)

```jsonc
{
  "client_event_id": "9f1c1e2a-3b4c-4d5e-8f60-718293a4b5c6",  // UUID con guiones (nuevo: 422 si no)
  "event_type": "goal",              // catálogo cerrado de 7
  "team_id": "…",
  "beneficiary_team_id": null,       // solo own_goal; no nulo en otro tipo → 422
  "player_id": "…",                  // obligatorio en todos
  "player_out_id": null,             // solo substitution
  "player_in_id": null,              // solo substitution
  "assist_player_id": "…",           // NUEVO: solo goal; opcional; ≠ player_id
  "minute": 45,
  "added_minute": 2,
  "segment_id": "…",
  "metadata": { "red_card_type": "direct_red" }  // solo en red_card; otra clave → 422
}
```

Cambios observables:

| Caso | Antes | Ahora |
|---|---|---|
| Clave de primer nivel no declarada | se ignora | **422** (`extra="forbid"`) |
| `metadata` con clave distinta de `red_card_type` | se persiste | **422** |
| `metadata.red_card_type` en un tipo que no es `red_card` | **422** (ya) | **422** (igual) |
| `beneficiary_team_id` en `goal` igual al equipo | aceptado | **422** |
| `beneficiary_team_id` en `yellow_card`/`red_card`/`foul`/`substitution` igual al equipo | aceptado | **422** |
| `assist_player_id` en `goal` | campo inexistente | aceptado y validado |
| `assist_player_id` en otro tipo | — | **422** |
| `assist_player_id` igual al goleador | — | **422** |
| `assist_player_id` no elegible o de otro equipo | — | **409** `ASSIST_PLAYER_INVALID` |
| `client_event_id` no UUID | aceptado | **422** |

### 5.2 Respuesta de operación (`GET /api/v1/matches/{match_id}/operation`)

`events[]` añade `assist_player_id` (UUID o `null`). No se añaden nombres: el cliente resuelve el nombre desde `rosters[]`, que ya trae `player_id`, `first_name`, `last_name` y `dorsal_number`.

### 5.3 Errores

| Situación | Código | `detail` | `code` |
|---|---|---|---|
| Campo/clave no declarada por el tipo, `assist` en tipo ajeno, `assist` = goleador, `client_event_id` no UUID | 422 | lista saneada `[{type, loc, msg}]` | — |
| Asistente fuera de plantilla, de otro equipo, expulsado o ya sustituido | 409 | cadena | `ASSIST_PLAYER_INVALID` |
| Evento ya persistido distinto (incluye `metadata` y asistente) | 409 | cadena | — (sin cambio) |
| Partido/segmento/equipo de otra organización | 404 | cadena | — |

`AssistPlayerInvalid` se registra en `app/main.py` con el mismo manejador que `ResolutionNotEnabled`, que ya emite `{"detail": <cadena>, "code": …}` y `Cache-Control: no-store`.

### 5.4 Pantalla de operación (`frontend/app/pages/workspace/matches/[id].vue`)

- **Formulario por tipo:** se conserva el selector de tipo y de equipo; el resto de campos se renderiza desde `eventFields(type)`:
  - `goal`: jugador + **asistente** (opcional; solo jugadores del mismo equipo distintos del goleador).
  - `penalty_goal`, `yellow_card`: jugador.
  - `own_goal`: jugador + beneficiario (equipos distintos del elegido).
  - `red_card`: jugador + clase de roja.
  - `substitution`: sale/entra (como hoy).
  - `foul`: jugador, con la nota de que es informativo.
  - Minuto, minuto añadido y segmento siguen siendo compartidos y visibles en todos.
- **Alta de evento:** `newClientEventId(crypto)`; si devuelve `null`, no se añade y se muestra `match.eventIdUnavailable` (nuevo texto) — no se inventa ningún texto.
- **Lista del acta:** `eventSummary` muestra `Goleador (asist. Asistente)`; para el acta persistida el nombre del asistente sale de `operation.rosters`.
- **Borrador local:** al restaurar, los eventos con `client_event_id` que no sea UUID se descartan y se avisa con el número (`match.draftEventsDropped`); el resto se conserva.

### 5.5 i18n

Claves nuevas, con paridad es/en: `match.assist`, `match.assistNone`, `match.assistHint`, `match.eventIdUnavailable`, `match.draftEventsDropped`, `match.foulInformative`.

## 6. Decisiones justificadas

| # | Decisión | Alternativa descartada y por qué |
|---|---|---|
| D-1 | **Columna nula + FK compuesta + `CHECK`**, sin tabla ni índice nuevos. | *Evento `assist` vinculado*: exigiría FK al evento, unicidad por evento de origen, orden e inmutabilidad propios y abriría asistencias huérfanas. *`metadata`*: sin garantía estructural ni consultable, y contradice el cierre de `metadata`. |
| D-2 | **`CHECK` validado** (no `NOT VALID`) en 026. | `NOT VALID` evitaría el escaneo, pero deja el catálogo en un estado distinto del de un volumen limpio y aquí no hay filas históricas que lo justifiquen (la columna nace nula). Se asume la ventana breve de bloqueo, como en la 022. |
| D-3 | **Sin índice sobre `assist_player_id`.** | Índice parcial `WHERE assist_player_id IS NOT NULL`: no hay ninguna consulta que lo use (no hay estadísticas en este alcance) y añadiría superficie de migración; los jugadores no se borran (`ON DELETE RESTRICT`), así que el coste del FK es despreciable. |
| D-4 | **`extra="forbid"` también en la raíz** del evento. | Cerrar solo `metadata` dejaría un canal de texto libre en la auditoría (`request` completo) y una clave desconocida ignorada que el cliente creería aplicada. El coste es la ruptura declarada en RNF-003. |
| D-5 | **`client_event_id` con patrón UUID en la API, sin `CHECK` en base.** | `CHECK` en base: exigiría `NOT VALID` por los datos históricos y no aporta garantía nueva (la API es el único escritor). Mantener texto libre con solo recorte: no elimina el canal hacia la auditoría. |
| D-6 | **El asistente se devuelve como UUID, no con nombre.** | Devolver `first_name`/`last_name` del asistente añadiría una unión y una superficie de datos personales; el cliente ya tiene la plantilla del partido con los nombres. |
| D-7 | **La validación del asistente vive en el replay** (paso 8 del orden de la 017). | Una pasada aparte sobre los eventos no tendría el estado en campo en ese minuto y duplicaría la lógica; hacerlo en el DTO no conocería la plantilla. |
| D-8 | **Código `ASSIST_PLAYER_INVALID` mediante excepción de dominio** registrada en `main.py`. | Devolver el `code` desde el router exigiría un `try/except` por ruta y duplicaría el mapeo; el patrón de `ResolutionNotEnabled` ya está probado. |
| D-9 | **Los borradores antiguos con id no UUID se descartan con aviso**, no se migran. | Reescribir el id de un borrador local cambiaría la identidad de un evento que aún no existe en el servidor y complicaría la deduplicación; descartar y avisar es explícito y sin ambigüedad. |
| D-10 | **`metadata` entra en la comparación de idempotencia** (sin normalizar más allá de `{}` ↔ `None`). | Comparar solo las claves declaradas dejaría pasar un reintento que cambia `red_card_type`, que es exactamente el defecto detectado. |

## 7. Base de datos — migración 026

- **Número:** `026`, el siguiente libre (el esquema está en **025**). Archivo `infra/postgres/migrations/026_match_event_assists.sql`.
- **Contenido:**
  1. Cabecera con motivo, orden de despliegue y ausencia de rollback.
  2. Pre-chequeo informativo (`NOTICE`): columnas existentes, índice único `uq_player_organization_context` presente y conteo de eventos `goal`. No aborta.
  3. `ALTER TABLE public.match_events ADD COLUMN IF NOT EXISTS assist_player_id UUID;`
  4. `ADD CONSTRAINT fk_match_events_assist_player_organization FOREIGN KEY (assist_player_id, organization_id) REFERENCES public.players (id, organization_id) ON DELETE RESTRICT;`
  5. `ADD CONSTRAINT chk_match_event_assist CHECK ((event_type = 'goal' AND (assist_player_id IS NULL OR assist_player_id <> player_id)) OR (event_type <> 'goal' AND assist_player_id IS NULL));`
- **RLS:** `match_events` ya tiene RLS y su política por organización; no se añade ni se toca ninguna política. La FK compuesta replica el patrón de la 021 para que el aislamiento no dependa solo de RLS.
- **Grants:** los privilegios de `bracket_app` sobre `match_events` son **de tabla** (`GRANT SELECT, INSERT, UPDATE, DELETE ON … match_events … TO bracket_app` en `init/01`), así que la columna nueva queda cubierta sin ningún `GRANT` adicional. Se declara explícitamente porque el caso de `rosters` (020) es distinto: allí son de columna.
- **Sin *backfill*:** ninguna fila se reescribe; los goles históricos quedan con `assist_player_id` nulo y son válidos.
- **Verificación en dos cadenas** (`backend/tests/test_migration_026.py`): (a) volumen limpio `init/00-03` + 001..026; (b) volumen migrado 001..025 y después 026; ambas deben terminar con la misma forma (columna, FK, `CHECK`, políticas y grants) y sin diferencias en `pg_constraint`/`pg_attribute`.
- **Orden de despliegue:** **026 → código**. Sin rollback: cualquier defecto se corrige con una migración nueva (*forward-fix*).
- **`init/01` no se toca** (no es una migración y no tiene checksum).

## 8. Backend

- **Módulo:** `backend/app/modules/matches/`. Sin módulo nuevo, sin router nuevo; `backend/app/main.py` solo gana el registro del manejador de `AssistPlayerInvalid`.
- **RLS:** todas las rutas del cierre ya abren transacción y llaman a `set_rls_context()` antes de cualquier consulta tenant; no se añade ninguna ruta, así que no hay una nueva superficie que fijar.
- **Validación en el esquema (Pydantic)**: catálogo cerrado y `assist_player_id`. Es el 422 estructural que la 017 declara previo al orden de dominio.
- **Validación de negocio**: replay puro + `AssistPlayerInvalid`.
- **Persistencia**: `_persist_events` con la columna nueva y la comparación ampliada.
- **Sin cambios** en: clasificación (`standings/`), sanciones (`evaluate_suspensions`), avance (`advancement/`), marcador (`compute_match_outcome`), `rules_config` y `engine_version`.

## 9. Eventos asíncronos

**No aplica.** No se añade ningún tipo de evento de outbox, ni cambia la carga de `MATCH_CLOSED`, `MATCH_UPDATED` o `STANDINGS_UPDATED`, ni el worker, ni el relay, ni el contrato de Socket.IO. La asistencia no produce notificación.

## 10. Frontend

- Llamadas por `frontend/app/composables/useApi.ts` (la pantalla ya lo hace); no se añaden endpoints.
- Funciones puras en `frontend/app/utils/matchEvents.ts` y ampliación de `substitutions.ts`, probadas con `node --test` en `frontend/tests/`.
- La pantalla `[id].vue` conserva su estructura y sus anclas de prueba; solo cambia la parte del formulario de eventos y el resumen.
- El borrador local (`frontend/app/utils/matchDraft.ts`) no cambia de formato: los eventos se guardan tal cual y `readDraftEvent` es quien valida, de modo que un borrador antiguo sigue siendo legible y se sanea al restaurar.

## 11. Exposición pública

**No aplica ningún cambio.** No se añade ningún campo a `v_public_*`, ni a los endpoints públicos, ni a la alineación publicada. Las asistencias no se publican: ni el detalle público del torneo, ni la clasificación, ni los partidos, ni las alineaciones las exponen. No se introducen datos personales nuevos (el asistente es un jugador ya visible en la operación) y las fotos siguen dependiendo del consentimiento de imagen, que esta spec no toca.

## 12. Configuración y secretos

**No aplica.** Sin variables de entorno nuevas, sin cambios en `.env.example`, `docker-compose*.yml` ni `infra/scripts/check_env_contract.py`. Sin secretos nuevos. `PLAYER_DATA_KEY` y el resto siguen igual.

## 13. Estrategia de tests

### Sin base de datos (`cd backend && pytest -q`)

| Archivo | Qué cubre |
|---|---|
| `backend/tests/test_match_events_contract.py` (nuevo) | Catálogo cerrado en los dos niveles, `assist` solo en `goal`, `assist` = goleador, `beneficiary` fuera de `own_goal`, `client_event_id` no UUID, `metadata` con clave ajena, campo de primer nivel desconocido, y los casos que **siguen** siendo válidos (gol sin asistente, `metadata` correcta en roja). Se prueba el DTO directamente, sin base. |
| `backend/tests/test_match_minutes.py` (existente) | Sin cambios: garantiza que la regla de minutos no se movió. |
| `backend/tests/test_error_sanitization.py` (existente) | Se amplía con el 422 nuevo (no debe ecoar `input`). |

### Opt-in con base (`RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL=…`)

| Archivo | Qué cubre |
|---|---|
| `backend/tests/test_migration_026.py` (nuevo) | Cadena limpia y migrada; forma, FK, `CHECK`; asistencia en `goal` aceptada por la base; asistencia en `yellow_card` o igual al goleador rechazada; filas históricas sin asistencia intactas. |
| `backend/tests/test_match_assists_db.py` (nuevo) | Cierre con asistencia válida (persistida y devuelta por la operación), asistente de otro equipo / fuera de plantilla / expulsado / ya sustituido → **409** `ASSIST_PLAYER_INVALID`, asistente = goleador → **422**, dos goles con el mismo asistente, acta sin asistencia, cierre con y sin asistencia que produce **el mismo marcador, puntos y sanciones** (RF-010), `metadata` en la comparación de idempotencia (reintento idéntico reutiliza, distinto **409**), y jugador de otra organización → **409** (no 404, no 500). |
| `backend/tests/test_substitutions.py` (existente) | Se conserva; añade un caso de regresión: el replay sigue aceptando sustituciones sin asistencia. |

### Frontend (`cd frontend && pnpm test`)

| Archivo | Qué cubre |
|---|---|
| `frontend/tests/match-events.test.ts` (nuevo) | `eventFields` por tipo, `assistCandidates`, `validateAssist`, `isUuid`, `newClientEventId` con y sin `randomUUID`, `buildDraftEvent`, `eventSummary`. |
| `frontend/tests/substitutions.test.ts` (existente) | `readDraftEvent` descarta id no UUID y conserva el resto; asistente inválido descarta el evento; borrador antiguo sin asistente se conserva. |
| `frontend/tests/i18n-catalog.test.ts` / barrido existente | Paridad es/en de las claves nuevas (mecanismo ya existente en el repositorio). |

**Sí se cita `pnpm run e2e:test`:** el proyecto `operation-flow` del arnés recorre el alta de eventos y el cierre del acta (además del reintento del tiempo real), así que su veredicto (0/1/2/3) se exige y se registra; no sustituye a `pnpm test`, que es donde viven las pruebas de utilidad y de contrato (RNF-005 de la spec).

## 14. Trazabilidad RF → archivo/prueba

| RF | Implementación | Prueba |
|---|---|---|
| RF-001 | `matchEvents.ts:EVENT_TYPES/eventFields`; `[id].vue` plantilla | `frontend/tests/match-events.test.ts` |
| RF-002 | `schemas.py` (`extra="forbid"`, validadores por tipo) | `backend/tests/test_match_events_contract.py` |
| RF-003 | `schemas.py` (estructura) + `service.py` (pertenencia) | `test_match_events_contract.py` + `test_match_assists_db.py` |
| RF-004 | `matchEvents.ts:eventFields('foul')`; textos `match.foulInformative` | `match-events.test.ts` + paridad i18n |
| RF-005 | `matchEvents.ts:eventSummary`; `[id].vue` lista | `match-events.test.ts` |
| RF-006 | `matchEvents.ts:validateAssist/buildDraftEvent`; `[id].vue:addEvent` | `match-events.test.ts` |
| RF-007 | `026`, `schemas.assist_player_id`, `service._persist_events`, `substitutions.MatchEvent` | `test_migration_026.py` + `test_match_assists_db.py` |
| RF-008 | `substitutions.replay_report_state` + `errors.AssistPlayerInvalid` + `main.py` | `test_match_assists_db.py` |
| RF-009 | `schemas.py` (asistente solo en `goal`) | `test_match_events_contract.py` + `test_migration_026.py` |
| RF-010 | sin cambios en `engine.compute_match_outcome`/`standings`/`suspensions` | `test_match_assists_db.py` (con y sin asistencia) |
| RF-011 | `router.py` (consulta de eventos) + `service._persist_events` + auditoría existente | `test_match_assists_db.py` |
| RF-012 | `service._persist_events` (comparación) | `test_match_assists_db.py` |
| RF-013 | `026` sin *backfill*; `schemas.py` sin revalidación de históricos | `test_migration_026.py` |
| RF-014 | `service.py` (pertenencia contra la plantilla) | `test_match_assists_db.py` |
| RF-015 | `schemas.py` (patrón) + `matchEvents.newClientEventId` + `readDraftEvent` | `test_match_events_contract.py` + `substitutions.test.ts` |
| RF-016 | sin tocar `rule_contract`/`docs/contrato-reglas.md` | `backend/tests/test_rule_contract.py` (existente) |
| RF-017 | sin rutas ni permisos nuevos | `backend/tests/test_api_access.py` (existente) + `test_match_assists_db.py` (403/404) |

## 15. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 RLS lo garantiza la base | Sí | La tabla afectada (`match_events`) ya tiene RLS y política por organización; no se añade tabla ni se relaja ninguna política. La FK del asistente es compuesta con `organization_id`, así que el aislamiento no depende solo de RLS. |
| §2.2 La aplicación no se salta RLS | Sí | Sin cambios de rol, de `BYPASSRLS` ni de superusuario; sin `GRANT` nuevo (los de `match_events` son de tabla). |
| §2.3 Lo publicado es inmutable | Sí | No se toca ninguna versión publicada ni ningún acta confirmada; los triggers 009/016 siguen intactos y la columna nueva no permite reescribir eventos. |
| §2.4 Historial de esquema *append-only* | Sí | Migración **026** nueva; no se edita ninguna aplicada (el checksum lo impediría) y `init/01` no se toca. |
| §2.5 Lo público es una proyección mínima | Sí | No se añade ningún campo público; las asistencias no se exponen; sin documentos ni fechas de nacimiento; las fotos siguen dependiendo del consentimiento. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Sin variables de entorno ni secretos nuevos. |
| §2.7 Administración global separada y auditada | Sí | `/admin` no se toca; la asistencia no añade acciones de plataforma. |
| §2.8 Nada se termina sin verificación | Sí | Cada tarea declara «Hecho cuando» con comandos reales y la T12 cierra con la verificación completa; lo no ejecutado se declarará. |
| §2.9 El código de desarrollo no llega a producción | Sí | No se toca `scripts.seed_demo`; las pruebas de migración son opt-in y no se ejecutan en producción. |
| §4 Todos: CI correspondiente | Sí | `backend`, `frontend`, `infrastructure` y `security` no cambian de configuración; el cambio pasa los jobs con los comandos de la §4 y de `AGENTS.md`. |
| §4 Todos: sin secretos ni datos personales en el repositorio | Sí | Solo se añaden UUIDs de ejemplo en pruebas; ningún dato personal. |
| §4 Todos: documentación afectada | Sí | `AGENTS.md` y `README.md` en la misma tanda (T10); `docs/contrato-reglas.md` no cambia. |
| §4 Todos: pruebas del comportamiento nuevo | Sí | Nueve archivos de prueba (cuatro nuevos de backend, uno nuevo de frontend) más ampliaciones de los existentes. |
| §4 Base de datos: nueva migración numerada | Sí | **026**, sin editar ninguna aplicada. |
| §4 Base de datos: RLS y políticas en tablas nuevas | No aplica | No hay tabla nueva; la existente conserva su política. |
| §4 Base de datos: volumen limpio y ya migrado | Sí | `test_migration_026.py` construye las dos cadenas y compara la forma final. |
| §4 Base de datos: `sh -n infra/postgres/migrate.sh` | Sí | Se ejecuta en T1 y en la verificación final. |
| §4 API: consultas tenant con `set_rls_context()` | Sí | No se añade ninguna consulta fuera del cierre, que ya fija el contexto en su transacción. |
| §4 API: endpoints públicos sin campos sensibles | Sí | No cambian. |
| §4 API: router nuevo registrado en `main.py` | No aplica | No hay router nuevo; solo se registra un manejador de excepción. |
| §4 API: `pytest -q` y `compileall` | Sí | T2–T5 y T12. |
| §4 Frontend: llamadas por `useApi.ts` | Sí | No se añaden llamadas; la pantalla ya usa el composable. |
| §4 Frontend: `pnpm test`, `typecheck`, `build` | Sí | T6–T9 y T12. |
| §4 Infraestructura: `docker compose config -q` | No aplica | No se toca ningún compose ni variable. |
| §4 Dependencias: lockfiles y auditorías | No aplica | Sin dependencias nuevas. |

## 16. Orden de despliegue

1. `MIGRATION_TARGET=026 docker compose run --rm db-migrate` (o el flujo del runbook).
2. Desplegar el código de la 015.
3. Verificar `GET /docs` (campo nuevo), una operación de partido y un cierre con asistencia.

Sin rollback: cualquier defecto se corrige con una migración nueva.
