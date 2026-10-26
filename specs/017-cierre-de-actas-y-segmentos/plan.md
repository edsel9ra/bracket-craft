# Plan 017 — Cierre de actas y segmentos

Spec: `specs/017-cierre-de-actas-y-segmentos/spec.md` (20 RF, aprobada el 2026-10-25).
Constitución: `docs/constitution.md` v1.4.0. Contrato interno: `docs/contrato-reglas.md` (`engine_version` **2026.1**, sin cambios).
Estado del código: leído el 2026-10-25, **después** de la 015 (asistencia, migración 026, catálogo cerrado, regla de identificadores).

## 1. Alcance

Casi todo es backend en `backend/app/modules/matches/` (orden de validación, matriz de marcadores, doble amarilla, `next_segment`) y una parte de la pantalla de operación (consumir la propuesta, aviso de acta cerrada, mensaje del código nuevo). **Sin migración.**

Lo que la 017 **no** toca: walkover (016: esta spec no le da rama ni exención y el cierre lo trata como cualquier resolución), catálogo y asistencia (015, ya implementados), `rules_config` y `engine_version`.

**Riesgo global:** reordenar validaciones cambia **qué mensaje** ve una petición con varios defectos. Es un cambio observable sin cambio de código de estado, declarado en RNF-003(b) de la spec; el plan lo cubre con una prueba de orden explícita.

**Alcance delegado (cambio del 2026-10-25):** el **criterio de finalización 16** de la spec tenía dos partes; la exención del walkover pertenece íntegramente a la **016** y **no se implementa ni se verifica aquí**. El plan no incluye ninguna tarea para ella.

## 2. Archivos y responsabilidades

### Backend

| Archivo | Responsabilidad |
|---|---|
| `backend/app/modules/matches/service.py` | (a) Reordenar `CloseMatchReportService.execute` al orden de dominio de RF-001, con el orden escrito como pasos numerados; (b) mover el chequeo de **participantes** de `_persist_events` a un nuevo `_validate_event_participants` en el paso 7; (c) mover `compute_match_outcome` **antes** de persistir, calculándolo con los eventos de la petición; (d) nueva función pura `double_yellow_violations(events)`; (e) nueva función pura `next_segment_proposal(...)`; (f) `_double_yellow_consistency` que lanza la excepción de dominio; (g) `replay_report_state` **retiene** el error del asistente y lo lanza al terminar su única pasada, para que el paso 8 gane al 9 sin duplicar el motor (corrección de la validación, fase 6). |
| `backend/app/modules/matches/schemas.py` | Quitar de `CloseMatchReportDTO.validate_resolution` las comprobaciones de **coherencia numérica** (`final < reglamentario`, `regular` con final distinto, `penalties` sin empate y tanda igualada): pasan al paso 13 y responden **409**. Se conservan las de **presencia** (pareja obligatoria, final obligatorio por resolución, penales obligatorios, ganador obligatorio, razón) y las de combinación de eventos. Añadir `NextSegmentProposal` y el campo `next_segment` a `MatchOperationResponse`. |
| `backend/app/modules/matches/errors.py` | Nueva `DoubleYellowInconsistent` (409) con `code = "DOUBLE_YELLOW_INCONSISTENT"`, en el patrón de `ResolutionNotEnabled`/`AssistPlayerInvalid`. |
| `backend/app/main.py` | Registrar el manejador: `api.add_exception_handler(DoubleYellowInconsistent, _coded_exception_handler)`. |
| `backend/app/modules/matches/router.py` | `GET /{match_id}/operation` devuelve `next_segment` construido con `next_segment_proposal(match["status"], match["version_status"], segments, interruptions)`; docstring del contrato. Ninguna ruta nueva. |
| `backend/app/modules/rules_engine/*` | **Sin cambios.** `compute_match_outcome` ya valida el ganador, el empate de penales y el final ≥ reglamentario: al retirar la duplicación del DTO, esos casos pasan a **409** por el camino que ya existe. |

### Frontend

| Archivo | Responsabilidad |
|---|---|
| `frontend/app/utils/matchSegments.ts` (nuevo) | Funciones puras: `applySegmentProposal(current, proposal, options)` (número siempre; minuto solo si procede), `segmentProposalHint(proposal)` y el tipo `NextSegmentProposal`. Sin reloj ni estado. |
| `frontend/app/utils/matchResolution.ts` | `classifyMatchConflict` reconoce `DOUBLE_YELLOW_INCONSISTENT` → nuevo `MatchConflictKind` `'double_yellow_inconsistent'`; constante del código. |
| `frontend/app/pages/workspace/matches/[id].vue` | Consumir `next_segment` en `applyOperation` con la regla de campo no editado; aviso `reportLocked` cuando `isTerminal`; mensaje del 409 nuevo al cerrar; retirar el cálculo local del número (línea ~810) y el `minute_start = interruptionForm.minute` (línea ~995) dejando que la propuesta los fije. |
| `frontend/app/composables/useI18n.ts` | Claves es/en: `match.reportLocked`, `match.doubleYellowInconsistent`, `match.segmentProposalDerived`, `match.segmentProposalManual`. |
| `frontend/tests/match-segments.test.ts` (nuevo) | `applySegmentProposal` en los cinco casos + número siempre + minuto solo cuando toca. |
| `frontend/tests/match-resolution.test.ts` (existente) | `classifyMatchConflict` con el código nuevo y con un 409 sin `code`. |
| `frontend/tests/match-events.test.ts` (existente, de la 015) | Añade las claves nuevas a su lista de textos del acta y comprueba con ella paridad es/en, declaración única y uso real (`extractUsedKeys`). |

### Documentación (tarea propia, no ahora)

| Archivo | Responsabilidad |
|---|---|
| `AGENTS.md` | Orden único del cierre, conjunción de autorización, matriz de marcadores, doble amarilla, `next_segment`, acta cerrada. |
| `README.md` | Operación: propuesta de segmento y qué significa un segmento. |

## 3. Funciones puras

Ninguna lee el reloj, el entorno, el almacenamiento ni la red. Las que podrían depender del tiempo, no lo hacen: el cierre recibe fechas del partido ya cargadas.

| Función | Firma | Dónde | Nota |
|---|---|---|---|
| `double_yellow_violations` | `(events: Sequence[MatchEventPayload \| Mapping]) -> tuple[int, ...]` | `service.py` | Devuelve los índices de payload en orden canónico que incumplen «exactamente dos amarillas previas». |
| `next_segment_proposal` | `(match_status, version_status, segments, interruptions) -> dict \| None` | `service.py` | Determinista; no escribe. |
| `_validate_event_participants` | `(dto, match) -> None` | `service.py` | Puro salvo la excepción; sin consultas. |
| `applySegmentProposal` | `(current, proposal, {forceMinute}) -> SegmentForm` | `matchSegments.ts` | Recibe el estado del formulario; no lee `ref`s. |
| `classifyMatchConflict` | `(cause) -> MatchConflictKind` | `matchResolution.ts` | Ya existe; se amplía. |

`compute_match_outcome` (engine) sigue siendo puro y recibe la lista de eventos por parámetro.

## 4. Pseudocódigo

### 4.1 Orden único de validación (RF-001)

```
execute(context, match_id, dto):
    transacción; set_rls_context

    # --- preparación (no es validación de dominio) -------------------------
    identidad = _load_match_identity(...)                 # 404 si no existe / otra org
    lock(fase, versión); lock(destinos de avance); match = lock_partido()

    # --- 2. permiso (conjunción) -------------------------------------------
    si dto.resolution_type == "administrative":
        require_administrative_resolution(...)            # además owner/admin
    sino:
        require_permission(CLOSE_MATCH_REPORT, match)     # permiso Y (rol op || oficial)

    # --- 3. estado y versión ------------------------------------------------
    si match.status en {finished, cancelled, administrative_resolution, suspended}: 409
    si match.version_status != published: 409
    # --- 4. dos equipos ------------------------------------------------------
    si home_team_id o away_team_id nulos: 409

    cargar segmento activo, rosters (con locks de jugador), segmentos, minutos

    # --- 5. resolución habilitada (antes que estructura y plantilla) --------
    si not resolution_enabled(minutos, dto.resolution_type): 409 RESOLUTION_NOT_ENABLED

    # --- 6. estructura del acta --------------------------------------------
    # Sin excepción por resolución: el walkover también pasa por aquí (D-10).
    si no hay segmento activo: 409                       # RF-017
    _validate_segments(dto, segmentos, minutos)          # 404 segmento ajeno; 409 resto

    # --- 7. participantes y plantilla ---------------------------------------
    _validate_event_team_scope(...)                      # 404 equipo/beneficiario de otra org
    _validate_event_participants(...)                    # 409 equipo de la org que no juega
    _validate_rosters(match, rosters)                    # 409 plantilla/elegibilidad

    # --- 8 y 9. estado en campo, sustituciones y asistente ------------------
    # Una sola pasada del motor: el replay retiene el error del asistente y lo
    # lanza al terminar, así el paso 8 se informa siempre primero (RF-001).
    _validate_substitutions(...)                         # replay; 409 / 409 ASSIST_PLAYER_INVALID

    # --- 10. coherencia disciplinaria --------------------------------------
    _validate_double_yellow(dto)                         # 409 DOUBLE_YELLOW_INCONSISTENT

    # --- 11. marcador frente a eventos --------------------------------------
    _validate_event_score_consistency(...)               # 409

    # --- 12. sanciones ------------------------------------------------------
    _validate_suspensions(...)                           # 409

    # --- 13. coherencia de la resolución y del ganador (antes de escribir) --
    outcome = compute_match_outcome(config, eventos_de_la_peticion, ...)   # 409
    si requires_decisive_winner(bracket_code) y outcome.winner is None: 409

    # --- 14. escritura ------------------------------------------------------
    persistir eventos; actualizar partido; cerrar segmento; proyección;
    sanciones; clasificación; avance; auditoría; outbox
```

Notas de fidelidad con el código actual:
- `_validate_event_team_scope` (404) va **antes** de participantes (409): un equipo de otra organización no puede caer en el 409 de «no participa».
- `_validate_segments` lanza `LookupError` para un segmento ajeno/inexistente (lo traduce el router a 404); ese 404 también precede a los 409 de plantilla.
- Los **locks de jugador** se toman al cargar la plantilla, antes del paso 5; son bloqueo, no validación, y su orden no cambia (RF-018).
- **El walkover no tiene rama en esta spec (D-10):** recorre los 14 pasos como cualquier resolución, incluidos el segmento activo (paso 6) y la plantilla (paso 7). La exención, el motivo, el marcador derivado y el preflight son de la **016** y este plan no los implementa. La spec **no** promete ningún `si resolution_type != "walkover"`: si la 016 introduce ramas, las añadirá ella y actualizará esta nota.

### 4.2 Matriz de marcadores (RF-007)

`CloseMatchReportDTO` conserva (422):

```
pareja reglamentaria presente                     # home_score_regular, away_score_regular
pareja final presente si se informa uno de los dos
pareja final presente si la resolución es extra_time | penalties | administrative
pareja de penales presente si penalties; ninguna en otra resolución
winner presente si la resolución no es regular
reason presente si administrative; prohibido en el resto
sin eventos si walkover | administrative
client_event_id únicos (comparados en minúsculas)
```

Pasa al dominio (409, paso 13, `compute_match_outcome`):

```
final < reglamentario                         → 409
regular: final (si se informó) != reglamentario → 409
penalties: final != reglamentario (empate)    → 409
penalties: tanda igualada                     → 409
winner informado != ganador calculado         → 409
```

La fila **walkover** de la matriz **no se implementa en la 017**: describe el comportamiento **actual** (reglamentario igual al configurado, final opcional validado contra él, ganador obligatorio, sin motivo) y su contrato objetivo —marcadores derivados y publicados, motivo de catálogo— queda **delegado a la 016**. La 017 no añade `si resolution_type != "walkover"` en ningún paso.

El gol reglamentario se sigue decidiendo con `event.minute <= regular_time_minutes` y **sin** mirar `added_minute` (regla que se conserva y se prueba).

### 4.3 Doble amarilla (RF-006)

```
def double_yellow_violations(events):
    orden = sorted(enumerate(events), key=(minute, added_minute, índice))
    amarillas = defaultdict(int); violaciones = []
    para (índice, evento) en orden:
        si evento.event_type == "yellow_card" y evento.player_id:
            amarillas[player_id] += 1
        si evento.event_type == "red_card"
           y metadata.red_card_type == "double_yellow_red":
            si amarillas[player_id] != 2:
                violaciones.append(índice)
    return tuple(violaciones)
```

- «Exactamente dos»: 0, 1 o ≥3 son violación.
- Solo cuenta ese partido (la función recibe el acta completa de la petición, que es el partido).
- La roja directa no se mira.
- La función no lee el DTO: acepta mappings, para probarla con dicts.
- El servicio toma la primera violación y lanza `DoubleYellowInconsistent` con el minuto en el mensaje (sin nombres).

### 4.4 `next_segment` (RF-015)

```
def next_segment_proposal(match_status, version_status, segments, interruptions):
    si match_status en {finished, cancelled, administrative_resolution}: return None
    si version_status != "published": return None

    si no segments:
        return {segment_number: 1, minute_start: 0, derived: True}

    último = max(segments, key=segment_number)
    número = último.segment_number + 1

    si último.status == "interrupted":
        interrupción = la de último.id con (minute, created_at, id) mayor
        si interrupción: return {número, interrupción.minute, derived: True}
        return {número, None, derived: False}          # dato anómalo: sin base

    si último.status == "completed" y último.minute_end is not None:
        return {número, último.minute_end, derived: True}

    return {número, None, derived: False}              # activo, o completed sin fin
```

`suspended` **sí** recibe propuesta: la ruta de creación de segmento lo admite hoy, así que negarla sería ofrecer menos de lo que el servidor permite.

### 4.5 Aplicación de la propuesta en el cliente (RF-015, RNF-007)

```
applySegmentProposal(actual, propuesta, {forceMinute}):
    si propuesta es nula: return actual                # partido terminal: no se toca
    número = propuesta.segment_number                  # siempre del servidor
    minuto = actual.minute_start
    si propuesta.derived y (forceMinute o not actual.minuteDirty):
        minuto = propuesta.minute_start
    return {segment_number: número, minute_start: minuto}
```

`forceMinute` es verdadero al montar la pantalla y tras crear o interrumpir con éxito; falso en cualquier refresco (incluido el que provoca el socket). Así una recarga de la operación **no** pisa el minuto que el operador está escribiendo.

## 5. Interfaz

### 5.1 `GET /api/v1/matches/{match_id}/operation`

Campo **nuevo** en la raíz de la respuesta (aditivo y anulable):

```jsonc
{
  "match": { … },
  "segments": [ … ],
  "interruptions": [ … ],
  "officials": [ … ],
  "eligible_officials": [ … ],
  "rosters": [ … ],
  "lineup": [ … ],
  "tactical_lineups": [ … ],
  "events": [ … ],           // 18 claves por evento; sin cambios
  "substitutions": { … },
  "limits": { … },           // ocho claves; sin cambios
  "next_segment": {          // NUEVO: null si el partido es terminal o la versión no está publicada
    "segment_number": 3,
    "minute_start": 37,      // null cuando no hay nada de lo que derivarlo
    "derived": true
  }
}
```

### 5.2 Códigos de error

| Situación | HTTP | `detail` | `code` |
|---|---|---|---|
| Roja `double_yellow_red` con 0, 1 o ≥3 amarillas previas del mismo jugador en el partido | **409** | cadena con el minuto (sin nombres) | `DOUBLE_YELLOW_INCONSISTENT` (nuevo) |
| Resolución no habilitada | 409 | cadena | `RESOLUTION_NOT_ENABLED` (ya existe) |
| Asistente inválido | 409 | cadena | `ASSIST_PLAYER_INVALID` (015, ya existe) |
| Marcador final < reglamentario, `regular` con final distinto, `penalties` sin empate o con tanda igualada | **409** | cadena (mensaje del motor) | — (sin cambio de forma) |
| Defecto estructural (campo no aplicable, duplicado, rango) | 422 | lista saneada | — |

**Cambio observable declarado:** los cuatro casos de coherencia de marcadores pasan de **422** (DTO) a **409** (paso 13). Se añade a RNF-003 de la spec.

### 5.3 Pantalla de operación

- **Formulario de segmento:** el número lo fija la propuesta; el minuto se prerrellena solo si la propuesta es derivada y el operador no lo ha editado. Etiqueta accesible del origen («propuesto» / «indícalo tú»).
- **Acta cerrada:** aviso `role="status"` «Acta cerrada, no editable» junto a la cabecera del acta cuando el partido es terminal; las acciones siguen deshabilitadas. Sin lenguaje constitucional.
- **Cierre rechazado por doble amarilla:** el mensaje traducido usa el `code`; el texto del servidor queda como respaldo.
- **Sin cambios** en: botones de apertura/creación de segmento (mismas etiquetas), formulario de cierre, marcadores y resolución prevista.

## 6. Decisiones justificadas

| # | Decisión | Alternativa descartada y por qué |
|---|---|---|
| D-1 | El orden se implementa **en `execute` con pasos numerados** y se verifica con una **matriz de precedencia**. | Una lista de validadores encadenados: indirección que esconde el orden y complica el acceso a dependencias (segmentos, rosters, minutos). **Ajuste (corrección de la validación, fase 6):** este plan prometía una «prueba de integración» y lo que se entregó es una **prueba pura con dobles** (`test_close_validation_order.py`): la precedencia es una propiedad del orden de los pasos, no del esquema, y los dobles permiten inyectar los 17 defectos y recorrer las 128 parejas de pasos distintos en 2 s sin PostgreSQL. La integración con base se reserva para lo que los dobles no pueden distinguir: los **dos motivos del 403** con roles reales (`test_close_authorization_db.py`). |
| D-2 | La coherencia **numérica** del marcador vive en el motor (409) y se **retira** del DTO. | Dejarla en el DTO: contradice RF-007 (criterio «final menor → 409») y el paso 13. Duplicar una función de coherencia nueva: reimplementa lo que `compute_match_outcome` ya hace. |
| D-3 | `double_yellow_violations` vive en `matches/service.py` (puro, sobre la petición). | Ponerla en `rules_engine/engine.py` junto a `evaluate_suspensions`: esa función trabaja sobre eventos persistidos con `id` y genera suspensiones; aquí la entrada es el acta de la petición con índices de payload. |
| D-4 | `next_segment` se calcula en el servidor y se expone como modelo tipado en la respuesta de operación. | Calcularlo en el cliente (estado actual): dos fuentes y el número depende de un refresco. Endpoint nuevo: contrato de más para un dato derivado. |
| D-5 | La propuesta **no pisa** el minuto editado por el operador (`minuteDirty` + `forceMinute`). | Pisarlo siempre: el operador pierde lo que escribe en cada refresco del socket y se rompe el hito `segment-limit-announced` del E2E. No prerrellenar: no hay automatización. |
| D-6 | `DOUBLE_YELLOW_INCONSISTENT` como `HTTPException` de dominio registrada en `main.py`. | Devolver el `code` desde el router: duplica el mapeo por ruta; el patrón ya existe con `ResolutionNotEnabled` y `AssistPlayerInvalid`. |
| D-7 | `next_segment` es `null` en partido terminal o versión no publicada. | Devolver siempre un objeto: ofrecería crear un segmento que la ruta rechaza. |
| D-8 | **Sin migración.** | Un `CHECK` para la doble amarilla: exige leer los eventos en un trigger, añade superficie y ya es 409 en la API; el orden y la propuesta son cálculo. |
| D-9 | Aviso de acta cerrada como nota `role="status"`. | Confiar solo en los botones deshabilitados: la spec exige un mensaje explícito. |
| D-10 | El walkover **no se toca** en la 017: sin rama, sin exención de segmento ni de plantilla, sin motivo, sin marcador derivado y sin preflight. Todo eso es de la **016**, y el **criterio 16** de la 017 queda **no aplicable hasta la 016** en su parte de exención. | Implementarla aquí: duplicaría la 016, obligaría a cambiar su DTO y dejaría dos artefactos atribuyéndose el mismo trabajo. |

## 7. Base de datos

**La 017 no necesita migración.** Justificación:

1. No añade columnas ni tablas: la doble amarilla se deriva de `match_events` ya persistidos, `next_segment` se calcula con `match_segments` y `match_segment_interruptions` que ya existen.
2. La inmutabilidad del acta confirmada ya la imponen `trg_protect_confirmed_match_result` (016) y `trg_validate_match_event_context` (009); la 017 se limita a **no** añadir ninguna vía de corrección.
3. El orden de validación y la matriz son reglas de la API, no restricciones que la base pueda expresar sin duplicar el motor.
4. La 026 (asistencia) es de la 015 y **ya está aplicada**; la 017 no la modifica.

El esquema queda en **026** durante toda la 017.

## 8. Backend, RLS y eventos asíncronos

- **Módulo:** `backend/app/modules/matches/`; el router ya está registrado en `main.py`, que solo gana una línea de manejador. No hay módulo ni router nuevos.
- **RLS:** el cierre ya abre transacción y llama a `set_rls_context()` antes de cualquier consulta; la operación hace lo mismo. La 017 no añade consultas tenant fuera de esas transacciones; `next_segment` usa los segmentos y las interrupciones que la operación ya lee, sin consultas nuevas.
- **Eventos asíncronos:** **sin cambios de contrato.** Se conservan `MATCH_CLOSED`, `MATCH_UPDATED` y `STANDINGS_UPDATED` con su carga actual; no se añade ni se retira ninguno. **Interacción relevante:** el refresco que provoca el socket sobre la pantalla de operación puede reescribir el formulario de segmento; por eso existe la regla del campo no editado (D-5). El relay y el worker no cambian.

## 9. Frontend

- Toda llamada HTTP sigue pasando por `frontend/app/composables/useApi.ts`; no se añaden llamadas (la operación ya se consulta).
- Funciones puras nuevas en `frontend/app/utils/matchSegments.ts` y ampliación de `matchResolution.ts`, probadas con `node --test` en `frontend/tests/`.
- El host no soporta TypeScript: **todas** las verificaciones de frontend se ejecutan dentro del contenedor (`docker compose exec -T web pnpm test`, `… pnpm run typecheck`, `… pnpm run build`).
- Se conservan las anclas del arnés: etiquetas de `startNextSegment`, `createSegment`, `segmentStartField`, `segmentNumberField`, `eventAdd`, `closeReport` y `reportClosed`.

## 10. Exposición pública

**No aplica ningún cambio.** No se añade ningún campo a `v_public_*` ni a las rutas públicas: `next_segment` vive en la operación del Workspace, que exige sesión y organización; los segmentos, interrupciones y eventos no se publican en ninguna proyección. No se introducen datos personales nuevos y las fotos siguen dependiendo del consentimiento de imagen, que esta spec no toca.

## 11. Configuración y secretos

**No aplica.** Sin variables de entorno, sin cambios en `.env.example`, compose ni `check_env_contract.py`. Sin secretos nuevos.

## 12. Estrategia de tests

### Sin base de datos (`cd backend && pytest -q`)

| Archivo | Qué cubre |
|---|---|
| `backend/tests/test_next_segment.py` (**nuevo**) | Los cinco casos de la propuesta, `null` en partido terminal y en versión no publicada, `suspended` sí propone, determinismo (misma entrada, misma salida). |
| `backend/tests/test_double_yellow.py` (**nuevo**) | Función pura: 0, 1, 2 y 3 amarillas previas; amarillas después de la roja no cuentan; roja directa intacta; dos rojas por doble amarilla del mismo jugador; orden por `(minute, added_minute, índice)`. |
| `backend/tests/test_match_events_contract.py` (existente) | Sigue verde: el catálogo cerrado no se toca. |
| `backend/tests/test_close_substitutions.py` (existente) | Sigue verde: el DTO conserva las reglas de presencia y de sustitución. |

### Opt-in con base (`RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL=…`) y la matriz pura

| Archivo | Qué cubre |
|---|---|
| `backend/tests/test_close_validation_order.py` (**nuevo, puro**) | Matriz de precedencia con peticiones de **dos defectos**: resolución no habilitada gana a segmento activo/plantilla; estructura gana a plantilla; 404 de segmento/equipo ajeno gana al 409 de participantes; participantes gana a marcador; marcador gana a sanciones; doble amarilla gana a marcador; **8 gana a 9** y **9 gana a 10–13**; **422 estructural gana a cualquier 409** por la ruta HTTP real; en todos los casos, cero escrituras (segmento, marcador, eventos, clasificación, outbox). **Corrección de la validación (fase 6):** es una prueba pura con **dobles** (`CloseOrderSession`), no reutiliza `ClosableMatch`; el porqué está en D-1. |
| `backend/tests/test_close_authorization_db.py` (**nuevo, con base**) | Los dos motivos del **403** con roles reales: árbitro con el permiso y sin asignación; observador asignado como oficial; control positivo del mismo árbitro asignado y del propietario. |
| `backend/tests/test_double_yellow.py` (misma suite) | 409 con `code` `DOUBLE_YELLOW_INCONSISTENT` y `detail` cadena; sin escritura; acta con roja directa cierra. |
| `backend/tests/test_match_resolution_db.py` (existente) | Se ajusta la expectativa de los casos que ahora son **409** (final < reglamentario; `penalties` sin empate) y se añade el caso de `regular` con final distinto. |
| `backend/tests/test_match_assists_db.py` (existente) | Sigue verde: la regla de identificadores y el asistente no cambian. |
| `backend/tests/test_substitutions.py` (existente) | Sigue verde; se conserva `test_two_simultaneous_closes_serialise_on_the_match`. Las concurrencias de cierre frente a interrupción y frente a un segmento nuevo viven en `test_match_resolution_db.py` (fase 6). |

### Frontend (`docker compose exec -T web pnpm test`)

| Archivo | Qué cubre |
|---|---|
| `frontend/tests/match-segments.test.ts` (**nuevo**) | `applySegmentProposal`: número siempre; minuto solo si `derived`; no pisa si el operador editó y `forceMinute` es falso; sí pisa con `forceMinute`; propuesta nula no toca nada. |
| `frontend/tests/match-resolution.test.ts` (existente) | `classifyMatchConflict` con `DOUBLE_YELLOW_INCONSISTENT` y con un 409 sin `code` → `other`. |
| `frontend/tests/match-events.test.ts` (existente) | Paridad es/en, declaración única y uso de las claves nuevas (mismo mecanismo que ya valida los textos del acta). |

### Extremo a extremo (`frontend/e2e`, proyecto `operation-flow`)

**Obligatorio: la 017 toca la pantalla de operación y el cierre.** El proyecto `operation-flow` recorre apertura de segmento, segmento en el límite, aviso de segmento fuera de límite, planilla, evento en el límite (amarilla en 90+1), aviso de evento fuera de límite y **cierre del acta** (`report-closed`).

```sh
# 1. En exclusiva: sin dev server ni build concurrentes (comparten .nuxt).
docker compose up -d --wait
# 2. Limpiar residuos de corridas anteriores («Copa E2E» acumuladas rompen la
#    paginación del listado y el short_code derivado del reloj colisiona).
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "DELETE FROM tournaments WHERE name LIKE 'Copa E2E%';"
# 3. Correr el escenario.
cd frontend && pnpm run e2e:test
```

Interpretación del código de salida: **0** verde (las tres vistas y `operation-flow` en `passed`), **1** fallo de comportamiento (incluye un hito del acta), **2** fallo de infraestructura (pila, datos demo, navegador), **3** corrida inválida (proyecto o vista omitida, artefacto ausente). Solo **0** abre el gate. Un **2** o un **3** no se declaran verdes: se corrigen el entorno y la corrida y se repite.

## 13. Trazabilidad RF → archivo/prueba

| RF | Implementación | Prueba |
|---|---|---|
| RF-001 (orden único, 422 prevalece) | `service.execute` reordenado; `schemas` sin duplicación | `test_close_validation_order.py` (matriz de dos defectos) |
| RF-002 (conjunción) | `service.execute` + `permissions.require_permission` (sin cambios de permiso) | `test_close_validation_order.py` (403 con dobles) + `test_close_authorization_db.py` (403/403 con roles reales) |
| RF-003 (estructura) | `service._validate_segments` + paso 5 antes del 6 | `test_close_validation_order.py` (resolución > estructura; 422 al crear / 409 al cerrar) |
| RF-004 (participantes y plantilla) | `_validate_event_team_scope` + **nuevo** `_validate_event_participants` + `_validate_rosters` | `test_close_validation_order.py` (404 antes de 409; participantes antes de marcador) |
| RF-005 (estado en campo) | `replay_report_state` (sin cambios) | `test_substitutions.py`, `test_close_substitutions.py` (existentes) |
| RF-006 (doble amarilla) | `double_yellow_violations` + `_validate_double_yellow` + `DoubleYellowInconsistent` | `test_double_yellow.py` (puro y base) |
| RF-007 (marcador y matriz) | `compute_match_outcome` (existente) + DTO sin coherencia numérica | `test_match_resolution_db.py` (422→409), `test_close_validation_order.py` |
| RF-008 (idempotencia) | `_persist_events` (015) | `test_match_assists_db.py` (existente) |
| RF-009 (atomicidad) | transacción única + orden (todo valida antes de escribir) | `test_close_validation_order.py` (cero escrituras) + `test_match_result_immutability.py` |
| RF-010 (códigos) | `errors.DoubleYellowInconsistent` + `main.py` | `test_double_yellow.py` + `test_error_sanitization.py` |
| RF-011 (acta inmutable y aviso) | `[id].vue` aviso `reportLocked`; sin ruta nueva | `i18n` (barrido) + E2E `report-closed` + `test_match_result_immutability.py` |
| RF-012 (segmento = ventana) | docs + textos; sin sinónimos | `test_next_segment.py` + barrido i18n |
| RF-013 (crear/cerrar anterior) | `router.create_match_segment` (sin cambios) | `test_match_resolution_db.py` + E2E `segment-opened`/`segment-at-limit` |
| RF-014 (interrupción) | `router.interrupt_match_segment` (sin cambios) | `test_match_resolution_db.py` (existente) |
| RF-015 (`next_segment`) | `next_segment_proposal` + modelo + router + `matchSegments.ts` + `[id].vue` | `test_next_segment.py` + `match-segments.test.ts` + E2E |
| RF-016 (sin reglas nuevas) | no se toca el estado del partido | `test_match_resolution_db.py` (estados) + E2E |
| RF-017 (sin segmento activo) | paso 6 | `test_close_validation_order.py` |
| RF-018 (bloqueo) | orden de locks intacto | `test_substitutions.py` (dos cierres) + `test_match_resolution_db.py` (cierre vs interrupción y cierre vs segmento nuevo, en las dos órdenes) |
| RF-019 (`engine_version`) | sin cambios | `test_rule_contract.py` (existente) |
| RF-020 (identificadores) | `_validate_event_team_scope`, `_validate_segments` (LookupError) | `test_match_assists_db.py` (existente) + `test_close_validation_order.py` |

## 14. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 RLS lo garantiza la base | Sí | No hay tabla nueva; el cierre y la operación ya fijan el contexto. `next_segment` no añade consultas. |
| §2.2 La aplicación no se salta RLS | Sí | Sin cambios de rol, `BYPASSRLS`, superusuario ni grants. |
| §2.3 Lo publicado es inmutable | Sí | La 017 no añade ninguna vía de corrección; se apoya en los triggers 009 y 016 y lo verifica `test_match_result_immutability.py`. |
| §2.4 Historial de esquema *append-only* | Sí | **Sin migración**; no se edita ninguna aplicada y el esquema sigue en 026. |
| §2.5 Lo público es una proyección mínima | Sí | Ningún campo público nuevo; `next_segment` es del Workspace; sin datos personales; fotos con consentimiento, sin cambios. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Sin variables ni secretos nuevos. |
| §2.7 Administración global separada y auditada | Sí | `/admin` no se toca; no se añaden acciones auditadas. |
| §2.8 Nada se termina sin verificación | Sí | Cada tarea declara «Hecho cuando» con comandos reales; la última incluye backend, frontend, `typecheck`, `build` y **E2E obligatorio**; lo no ejecutado se declara. |
| §2.9 El código de desarrollo no llega a producción | Sí | No se toca el seed; las pruebas de base son opt-in. |
| §4 Todos: CI correspondiente | Sí | `backend`, `frontend`, `infrastructure` y `security` sin cambios de configuración; el cambio pasa los cuatro y no requiere el job `e2e` de CI (que corre el escenario de reintento), aunque el escenario de operación se ejecuta a mano por exigencia de la spec. |
| §4 Todos: sin secretos ni datos personales | Sí | Solo identificadores en pruebas. |
| §4 Todos: documentación afectada | Sí | `AGENTS.md` y `README.md` en T9; `docs/contrato-reglas.md` no cambia. |
| §4 Todos: pruebas del comportamiento nuevo | Sí | Cuatro archivos de prueba nuevos (dos puros, uno de orden con base, uno de frontend) y ampliación de tres existentes, más el E2E. |
| §4 Base de datos: nueva migración numerada | No aplica | La 017 no cambia el esquema; se justifica en §7. |
| §4 Base de datos: RLS y políticas en tablas nuevas | No aplica | No hay tablas nuevas. |
| §4 Base de datos: volumen limpio y migrado / `sh -n migrate.sh` | No aplica | Sin migración; `migrate.sh` no se toca. |
| §4 API: consultas tenant con `set_rls_context()` | Sí | Sin consultas nuevas; las existentes ya lo cumplen. |
| §4 API: endpoints públicos sin campos sensibles | Sí | No cambian. |
| §4 API: router nuevo registrado en `main.py` | No aplica | Solo se registra un manejador de excepción. |
| §4 API: `pytest -q` y `compileall` | Sí | T1–T6 y la verificación final. |
| §4 Frontend: llamadas por `useApi.ts` | Sí | No hay llamadas nuevas. |
| §4 Frontend: `pnpm test`, `typecheck`, `build` | Sí | T7–T8 y la verificación final, **dentro del contenedor `web`**. |
| §4 Infraestructura: `docker compose config -q` | No aplica | Sin cambios de compose. |
| §4 Dependencias: lockfiles y auditorías | No aplica | Sin dependencias nuevas. |
