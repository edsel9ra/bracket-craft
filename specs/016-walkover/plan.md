# Plan 016 — Walkover

Spec: `specs/016-walkover/spec.md` (13 RF, aprobada el 2026-10-25).
Constitución: `docs/constitution.md` v1.4.0. Contrato interno: `docs/contrato-reglas.md` (`engine_version` **2026.1**, sin cambios).
Estado del código: leído el 2026-10-25, **después** de la 015 (catálogo cerrado, asistencia, migración 026) y de la **017** (`CloseMatchReportService.execute` con 14 pasos, `replay_report_state` con el error del asistente retenido, `next_segment`, `DOUBLE_YELLOW_INCONSISTENT`). Esquema actual: **026**.

## 1. Alcance

Casi todo es backend en `backend/app/modules/matches/` (rama del walkover dentro del orden único de la 017, marcador derivado, motivo de catálogo, tres códigos nuevos) más una parte de la pantalla de operación (validación previa, formulario, cuerpo del cierre) y una **migración correctiva** (§8). No hay endpoints, módulos ni routers nuevos.

Lo que la 016 **no** toca: el orden de 14 pasos de la 017 (la rama se **inserta**), la matriz de marcadores de `regular`/`extra_time`/`penalties`/`administrative`, la doble amarilla, `next_segment`, el catálogo de eventos y la asistencia (015), la inmutabilidad del acta confirmada (016-migración/017) y `rules_config` (`engine_version` 2026.1).

**Riesgo global 1 — contrato observable:** un cliente antiguo que declare un walkover con marcadores 3-0 y **sin** motivo pasa de **201/200** a **422**. Está declarado en RNF-003(d) de la spec; el plan lo cubre con pruebas explícitas.

**Riesgo global 2 — superficie de base de datos:** el motivo del walkover no cabe en `resolution_reason` con el esquema actual (§2). La 016 necesita una migración; la spec lo recoge como **D-6** y corrige RNF-004, RF-007 y el criterio de finalización 20.

## 2. Hallazgo bloqueante verificado (2026-10-25): el motivo no cabe en la columna

`infra/postgres/init/01_schema.sql:416-424` (creada por `009_photo_resolution_and_outbox_hardening.sql:26-45`, idempotente) impone:

```sql
CONSTRAINT chk_administrative_resolution_reason CHECK (
    (resolution_type = 'administrative' AND resolution_reason IS NOT NULL AND LENGTH(BTRIM(resolution_reason)) BETWEEN 1 AND 1000)
    OR (resolution_type IS DISTINCT FROM 'administrative' AND resolution_reason IS NULL)
)
```

Es decir: **cualquier** resolución distinta de `administrative` debe llevar `resolution_reason` **nulo**. El cierre de hoy cumple eso (`service.py:757` escribe `dto.reason` solo para `administrative`). Guardar el código `no_show`/`withdrawal`/… en esa columna **viola la restricción** y el `UPDATE` fallaría con `IntegrityError` → el router respondería **409** «El acta no cumple las reglas de integridad del partido».

La spec afirmaba «sin migración» (RNF-004) y «sin ninguna restricción nueva» (RF-007) razonando que un `CHECK ... IN (...)` acepta `NULL` y no puede imponer la obligación. Ese razonamiento es correcto para la **obligatoriedad** (que sigue siendo de la API) pero no cubre el hecho de que la restricción **existente prohíbe el valor**. Se resuelve con la migración **027** de §8, que solo **relaja** la restricción, y con la decisión **D-6** registrada en la spec.

## 3. Archivos y responsabilidades

### Base de datos

| Archivo | Responsabilidad |
|---|---|
| `infra/postgres/migrations/027_walkover_resolution_reason.sql` (**nuevo**) | Reemplaza `chk_administrative_resolution_reason` por una versión que admite el código de walkover del catálogo cerrado (o `NULL`, para filas históricas) sin imponer la obligatoriedad. Sin columnas, sin índices, sin datos reescritos, sin tocar `init/01`. |

### Backend

| Archivo | Responsabilidad |
|---|---|
| `backend/app/modules/rules_engine/engine.py` | Nueva función pura `validate_walkover_score(config)` (RF-011): pareja efectiva de `stage_defaults` y de **cada** override con `winner > loser`. **No** se llama desde `validate_rules_config` (ver D-2). |
| `backend/app/modules/rules_engine/schemas.py` | `TournamentRulesConfig.validate_config` invoca `validate_walkover_score` tras normalizar → **422** al guardar y actualizar reglas. |
| `backend/app/modules/tournaments/router.py` | La publicación añade `validate_walkover_score(version["rules_config"])` dentro del `try` que ya mapea `ValueError` a **422** (línea 4291-4294). Nada más. |
| `backend/app/modules/matches/schemas.py` | (a) `home_score_regular`/`away_score_regular` pasan a `int \| None = None` y el validador exige su presencia en **toda** resolución salvo `walkover` (422); (b) `reason` en `walkover` es **obligatorio** y de catálogo cerrado (`no_show`, `withdrawal`, `insufficient_players`, `sanction`), mantiene el texto libre solo en `administrative` y sigue prohibido en el resto; (c) se conserva `extra="forbid"` y la prohibición de eventos en walkover/administrativa. |
| `backend/app/modules/matches/errors.py` | `WalkoverStateNotAllowed`, `WalkoverScoreMismatch`, `WalkoverConfigInconsistent` (las tres **409**) con `code` estable, en el patrón de `ResolutionNotEnabled`/`AssistPlayerInvalid`/`DoubleYellowInconsistent`. |
| `backend/app/main.py` | `api.add_exception_handler(...)` para las tres, con el `_coded_exception_handler` existente. |
| `backend/app/modules/matches/service.py` | (a) Nueva función pura `derive_walkover_score(...)`; (b) la **rama del walkover** como método `_execute_walkover(...)` invocado tras el paso 5 y antes de cargar plantilla (pasos 6′–14′, §5.1); (c) el bloque de plantilla + bloqueos de jugador se mueve **después** del paso 5 (RNF-008, sin cambio de orden de bloqueo); (d) `resolution_reason` escribe el código en walkover; (e) `audit_payload` añade `resolution_reason`; (f) docstrings del orden actualizados con la rama. |
| `backend/app/modules/matches/router.py` | `_build_operation_limits` añade `walkover_score` con la pareja **efectiva** (`effective_stage_rules`), sin tocar las ocho claves existentes. `close_match` no cambia (los códigos viajan por el manejador de `main.py`). |

### Frontend

| Archivo | Responsabilidad |
|---|---|
| `frontend/app/utils/matchClose.ts` (**nuevo**) | Puro: `WALKOVER_REASONS`, `WALKOVER_REASON_LABEL_KEYS`, `walkoverScoreFrom(limits)`, `closePreflight(input)` y `buildCloseReportBody(input)`. Sin reloj, sin red ni almacenamiento. |
| `frontend/app/utils/matchResolution.ts` | `OperationLimits` gana `walkover_score` opcional; nuevos códigos `WALKOVER_STATE_NOT_ALLOWED`, `WALKOVER_SCORE_MISMATCH`, `WALKOVER_CONFIG_INCONSISTENT` y sus `MatchConflictKind`; `resolutionChangeOutcome` y `closeResolutionDecision` dejan de bloquear por **segmentos persistidos fuera del máximo** cuando la resolución elegida es `walkover` (el W.O. no valida segmentos). |
| `frontend/app/utils/matchSegments.ts` | `CLOSE_CONFLICT_MESSAGE_LABEL_KEYS` gana una fila por `MatchConflictKind` nuevo (la tabla es exhaustiva por tipo: sin fila no compila). |
| `frontend/app/pages/workspace/matches/[id].vue` | `closeValidationError` pasa a delegar en `closePreflight`; el formulario de walkover pide ganador y motivo, muestra el marcador efectivo en solo lectura y oculta los seis campos de marcador; el cuerpo del cierre se construye con `buildCloseReportBody`; el botón deja de exigir segmento activo **solo** cuando la resolución es `walkover`. |
| `frontend/app/composables/useI18n.ts` | Claves es/en: `match.walkoverReason`, `match.walkoverReasonNoShow`/`Withdrawal`/`InsufficientPlayers`/`Sanction`, `match.walkoverReasonRequired`, `match.walkoverScore`, `match.walkoverNoSegment`, `match.walkoverConfigInconsistent`, `match.walkoverScoreMismatch`, `match.walkoverStateNotAllowed`. |

### Documentación (tarea propia)

| Archivo | Responsabilidad |
|---|---|
| `AGENTS.md` | Walkover: estados admitidos, autorización (conjunción, sin permisos nuevos), motivo de catálogo, marcador derivado y publicado en `limits`, efecto en resultado/clasificación/avance, sanciones no servidas, códigos nuevos, validación `winner > loser` al guardar/publicar y la guarda de cierre; migración 027 y su orden de despliegue. |
| `README.md` | Reescribir la frase de la línea 636 («`walkover` conserva su comportamiento actual y su contrato queda para la spec 016») con el contrato final y el runbook de la 027. |
| `docs/contrato-reglas.md` | **No cambia** (RF-013). |

## 4. Funciones puras

Ninguna lee el reloj, el entorno, el almacenamiento ni la red. El cierre no recibe ninguna fecha nueva: el walkover no depende del tiempo.

| Función | Firma | Dónde | Nota |
|---|---|---|---|
| `derive_walkover_score` | `(config, stage_id, home_team_id, away_team_id, winner_team_id) -> WalkoverScore \| None` | `matches/service.py` | Resuelve la pareja con `effective_stage_rules` (default + `stage_defaults` + override de fase, clave por clave) y la orienta a local/visitante. `None` = el ganador no participa. |
| `WalkoverScore.is_coherent` | propiedad de `WalkoverScore(home_score, away_score, winner_score, loser_score)` | `matches/service.py` | `winner_score > loser_score` (D-3/D-5). |
| `validate_walkover_score` | `(config) -> None` | `rules_engine/engine.py` | Recorre `stage_defaults` y **cada** override con el mismo merge que `validate_effective_rules`; overrides ordenados por `str(stage_id)` para que el mensaje sea estable (RNF-006). |
| `closePreflight` | `(input: ClosePreflightInput) -> ClosePreflightIssue \| null` | `matchClose.ts` | Devuelve el **primer** problema con una clave i18n y sus parámetros; sin `ref`s, sin DOM. |
| `buildCloseReportBody` | `(input: CloseReportBodyInput) -> Record<string, unknown>` | `matchClose.ts` | Cuerpo exacto del `POST /close`; para `walkover` **no emite** ninguna de las seis claves de marcador. |
| `walkoverScoreFrom` | `(limits) -> { winner, loser } \| null` | `matchClose.ts` | Tolerante a un servidor anterior (clave ausente → `null`, la pantalla muestra «—»). |

`compute_match_outcome` (motor) sigue siendo puro y se reutiliza con la pareja derivada (§5.2).

## 5. Pseudocódigo

### 5.1 La rama del walkover dentro de los 14 pasos (RF-001, RF-003, RF-004, RF-009, RNF-008)

La rama **se inserta**; no reordena nada. Los pasos 1-5 son los de la 017, sin cambios. Los pasos 6-12 **no se ejecutan** para el walkover y el 13-14 tienen su versión reducida.

```
execute(context, match_id, dto):
    transacción; set_rls_context
    # 1. sesión, organización y aislamiento (404 al cargar; no es paso)
    identity = _load_match_identity(...)
    lock(fase); lock(versión); lock(destinos); match = lock_partido()

    # 2. permiso (conjunción) — SIN CAMBIOS para walkover
    si dto.resolution_type == "administrative": require_administrative_resolution(...)
    sino: require_permission("CLOSE_MATCH_REPORT", match_id)      # permiso Y (rol op || oficial)

    # 3. estado y versión
    si match.status en {finished, cancelled, administrative_resolution, suspended}:
        si dto.resolution_type == "walkover": raise WalkoverStateNotAllowed(match.status)   # 409 + code
        raise ValueError(...)                                                              # resto: sin code
    si match.version_status != "published": 409

    # 4. dos equipos
    si faltan local o visitante: 409

    # bloqueo del segmento activo (ya existía: FOR UPDATE, no es validación)
    active_segment_row = SELECT ... status='active' FOR UPDATE
    minutes = effective_match_minutes(...)

    # 5. resolución habilitada
    si not resolution_enabled(minutes, dto.resolution_type): 409 RESOLUTION_NOT_ENABLED

    # >>> INSERCIÓN DE LA 016: la rama vuelve aquí, antes de tocar la plantilla <<<
    si dto.resolution_type == "walkover":
        return await self._execute_walkover(context, match, dto, active_segment_row)

    # --- camino normal de la 017, sin cambios (pasos 6-14) -------------------
    rosters = _load_match_rosters(...)      # MOVIDO aquí (antes estaba antes del paso 5)
    lock de jugadores                       # mismo orden: partido → segmento → jugadores
    segments = _load_match_segments(...)
    # 6. estructura ... 12. sanciones ... 13. resultado ... 14. escritura
```

`_execute_walkover(context, match, dto, active_segment_row)`:

```
# Omite 6 (estructura/segmento activo), 7 (participantes/plantilla),
# 8 (estado en campo/sustituciones), 9 (asistente), 10 (doble amarilla),
# 11 (marcador contra eventos) y 12 (sanciones): no hay acta que validar.

# 13′. marcador derivado y coherencia (antes de escribir)
pair = derive_walkover_score(config, stage_id, home, away, dto.winner_team_id)
si pair is None: raise ValueError("El ganador informado no participa en el partido")   # 409, sin code (mensaje del motor)
si not pair.is_coherent: raise WalkoverConfigInconsistent(pair)                        # 409 + code
si algún marcador informado (4 campos) != pareja derivada:
    raise WalkoverScoreMismatch(pair)                                                   # 409 + code
outcome = compute_match_outcome(config, [], "walkover", home, away,
                                pair.home_score, pair.away_score,
                                pair.home_score, pair.away_score,
                                None, None, dto.winner_team_id)                        # revalida ganador y pareja

# 14′. escritura atómica, sin eventos, sin proyección y sin sanciones
UPDATE matches SET home_score_regular = pair.home, away_score_regular = pair.away,
                   home_score = pair.home, away_score = pair.away,
                   home_penalties = NULL, away_penalties = NULL,
                   winner_team_id = dto.winner_team_id,
                   status = 'finished', resolution_type = 'walkover',
                   resolution_reason = dto.reason,          # código del catálogo
                   result_confirmed = TRUE, updated_at = now
si active_segment_row:
    UPDATE match_segments SET status='completed', minute_end = COALESCE(minute_end, minute_start)
    # RF-004: el activo se cierra en su minuto de inicio; el resto no se toca
# NO _persist_events · NO _rewrite_segment_team_state · NO _load_discipline_history
# NO _serve_suspensions · NO _insert_suspensions · NO evaluate_suspensions
_recalculate_standings(...)          # jugado, puntos, goles y diferencia (DU-6)
_advance_bracket(..., outcome)       # avance de llave y reset de doble eliminación
INSERT administrative_audit_logs (action='CLOSE_MATCH_REPORT', payload + resolution_reason)
INSERT outbox (MATCH_CLOSED, MATCH_UPDATED, STANDINGS_UPDATED)
return {status, match_id, home_score, away_score, winner_team_id}
```

Notas de fidelidad:

- **Por qué la plantilla se carga después del paso 5:** RNF-008 exige que la rama no consulte plantilla; el `SELECT` de `match_rosters` y los bloqueos de jugador se ejecutan hoy **antes** del paso 5. Moverlos detrás de la comprobación de resolución es neutro para el camino normal (el paso 5 precede al 7 en el orden declarado por la 017) y evita tomar bloqueos de jugador en una operación que no los necesita. El **orden de bloqueo** no cambia: fase → versión → destinos → partido → segmento → jugadores (RF-018 de la 017).
- **Exenciones que ya existen en el tronco común** y que la 016 **no** duplica: `_validate_event_team_scope` (`service.py:995`), `_validate_event_participants` (`:1039`), `_validate_substitutions` (`:1083`) y `_validate_event_score_consistency` (`:1200`) ya devuelven sin hacer nada para `walkover`. Con la rama quedan **inalcanzables** para el walkover y siguen siendo la exención de `administrative`. Se conservan (defensa en profundidad): retirarlas dejaría una trampa silenciosa si alguien mueve una llamada por delante de la rama. No son el mecanismo de la 016.
- **`_persist_events` (`:1302`)**: su guarda «Esta resolución no permite eventos individuales» ya es inalcanzable hoy (el DTO responde **422** antes del handler). No se toca.
- **`_validate_rosters` (`:906-920`) no tiene exención:** es la única de las validaciones del paso 7 sin guarda. La rama la **omite** en lugar de añadirle un `if`.
- **Doble confirmación de participación:** `derive_walkover_score` devuelve `None` cuando el ganador no participa y `compute_match_outcome` vuelve a comprobarlo. Es intencionado: la derivación necesita saber a qué lado asignar la pareja (no puede inventarla) y el motor sigue siendo la autoridad del desenlace.

### 5.2 Marcador derivado (RF-005, RF-008, RNF-006)

```
derive_walkover_score(config, stage_id, home, away, winner):
    effective = effective_stage_rules(config, stage_id)      # default 3-0 + stage_defaults + override
    pair = effective["walkover_score"]                       # {"winner": int, "loser": int}
    si winner == home:  return WalkoverScore(pair.winner, pair.loser, pair.winner, pair.loser)
    si winner == away:  return WalkoverScore(pair.loser,  pair.winner, pair.winner, pair.loser)
    return None
```

- El **mismo** `effective_stage_rules` alimenta `_build_operation_limits`, así que la operación publica exactamente la pareja que el cierre aplicará (no hay dos resoluciones distintas).
- `_lock_match` ya copia el override de la fase sobre `stage_defaults`; volver a aplicarlo es idempotente (mismas claves, mismos valores). Se documenta para que nadie lo «arregle» quitando una de las dos.
- Las pruebas cubren: default, override de fase (caso límite 8), **3-1** (caso 19) y pareja incoherente 0-3 (18).

### 5.3 Validación `winner > loser` (RF-011) en dos límites, nunca en el cierre

```
# LÍMITE DE CONFIGURACIÓN — guardar (pydantic) y publicar (router)
def validate_walkover_score(config):
    ámbitos = [("stage_defaults", _merged_stage_rules(config))]
    for stage_id in sorted((config.get("stage_overrides") or {}), key=str):
        ámbitos.append((f"stage_id {stage_id}", _merged_stage_rules(config, override(s)))
    para (ámbito, effective) en ámbitos:
        w, l = effective.walkover_score["winner"], effective.walkover_score["loser"]
        si w <= l:
            raise ValueError(f"Configuración de reglas inválida: {ámbito}: el marcador de "
                             f"walkover requiere un ganador por delante (par {w}-{l})")
```

- **No** se llama desde `validate_rules_config`: esa función corre en el **cierre** (`compute_match_outcome`), en la **clasificación** (`StandingsService.recalculate`, `standings/service.py:54`) y en el **clonado** de versiones. Meterla ahí haría que una versión publicada antes de D-3 fallara **todas** las resoluciones y todas las tablas de la fase — lo contrario de RF-011 («no en el cierre ni en la clasificación») y de «las versiones ya publicadas no se revalidan».
- **Publicar** sí valida el borrador persistido: un borrador clonado de una versión histórica incoherente responde **422** hasta que se corrija la pareja. Es el único camino por el que esa pareja podría volver a publicarse.
- El **clonado** (`normalize_rules_config` sobre la config publicada, `tournaments/router.py:597`) **no** valida la pareja: copiar una versión publicada no es «guardar» y un `ValueError` sin captura allí sería un **500**.

## 6. Interfaz

### 6.1 `GET /api/v1/matches/{match_id}/operation`

`limits` gana **una** clave (aditiva, las ocho existentes no cambian):

```jsonc
"limits": {
  "regular_time_minutes": 90,
  "extra_time_minutes": 120,
  "max_minute": 90,
  "added_minute_max": 30,
  "max_minute_regular": 90,
  "max_minute_extra": null,
  "extra_time_enabled": false,
  "penalties_enabled": false,
  "walkover_score": { "winner": 3, "loser": 0 }   // NUEVO: pareja efectiva (default + fase)
}
```

`next_segment` y el resto de la respuesta no cambian. Tras el cierre, `match.resolution_type = "walkover"` y `match.resolution_reason = "<código>"`.

### 6.2 `POST /api/v1/matches/{match_id}/close` — contrato del walkover

Petición mínima: `{"resolution_type": "walkover", "winner_team_id": "<uuid>", "reason": "no_show", "events": []}`.
Los seis campos de marcador pasan a ser **opcionales** en walkover (siguen siendo obligatorios en el resto, con el mismo 422 de hoy).

| Situación | HTTP | `detail` | `code` |
|---|---|---|---|
| Estado `finished`/`cancelled`/`administrative_resolution`/`suspended` | **409** | «El estado … no admite la declaración de un walkover» | `WALKOVER_STATE_NOT_ALLOWED` (**nuevo**) |
| Marcadores informados ≠ pareja efectiva | **409** | «El marcador de walkover informado no coincide con la configuración (3-0)» | `WALKOVER_SCORE_MISMATCH` (**nuevo**) |
| Pareja efectiva con `winner <= loser` (versión publicada antes de D-3) | **409** | «El marcador de walkover configurado (0-3) no da la victoria al ganador declarado; declara el resultado como resolución administrativa» | `WALKOVER_CONFIG_INCONSISTENT` (**nuevo**) |
| Ganador que no participa | 409 | «El ganador informado no participa en el partido» (mensaje del motor) | — |
| Motivo ausente / fuera del catálogo | **422** | lista saneada | — |
| Eventos en un walkover | 422 | lista saneada (prohibición vigente) | — |
| Falta `winner_team_id` | 422 | lista saneada | — |
| Sin permiso (conjunción) | 403 | «Permiso requerido: CLOSE_MATCH_REPORT» | — |
| Partido de otra organización | 404 | «Partido no encontrado» | — |

`detail` sigue siendo **cadena** en los 409 y los 422 **no** llevan `code`.

### 6.3 Guardar y publicar reglas

`walkover_score` con `winner <= loser` en `stage_defaults` o en el override de una fase responde **422** con el mensaje que nombra la pareja (`… (par 0-3)`); no se guarda ni se publica nada. `winner > loser` se acepta con cualquier cifra no negativa (3-1, 5-0).

### 6.4 Pantalla de operación (RF-012, RNF-007)

Con la resolución prevista `walkover`:

- **No** pide segmento activo ni planilla: `closePreflight` deja de exigir esos dos requisitos y el botón «Cerrar acta» deja de estar deshabilitado por `!selectedSegmentIsActive`.
- **No** se bloquea el cambio a `walkover` por segmentos persistidos fuera del máximo (D-13): el W.O. no valida segmentos, así que `resolutionChangeOutcome` los ignora para esa resolución y `closeResolutionDecision` no puede devolver `blocked` con ella.
- **Ganador** (selector que ya existe para toda resolución ≠ `regular`) y **motivo** (selector nuevo de cuatro códigos, obligatorio).
- **Marcador efectivo en solo lectura** («Marcador de walkover: 3-0») desde `limits.walkover_score`; los seis campos numéricos se ocultan y **no** se envían.
- Nota `match.walkoverNoSegment` bajo el panel para explicar por qué está habilitado sin segmento (decisión D-7).
- Los 409 nuevos se explican por su `code` (`classifyCloseConflict` → `closeConflictMessageKey`); el mensaje del servidor queda como respaldo y **no** se pierde lo escrito.
- El resto de resoluciones conserva su validación, su formulario y su botón **sin cambios**; las anclas del arnés (`closeReport`, `reportClosed`) se mantienen.

## 7. Decisiones justificadas

| # | Decisión | Alternativa descartada y por qué |
|---|---|---|
| D-1 | La rama es un **método privado** (`_execute_walkover`) invocado entre el paso 5 y el 6, con sus pasos numerados 13′/14′ y el comentario de qué omite. | Condicionales `if walkover: skip` repartidos por los 14 pasos: deja el orden ilegible, obliga a cargar plantilla igualmente y multiplica los puntos donde un cambio futuro puede eximir de más. Reordenar los pasos: prohibido por la 017. |
| D-2 | `validate_walkover_score` es una función **aparte**, llamada solo en guardar y publicar. | Meterla en `validate_rules_config`: se ejecutaría en el cierre, en la clasificación y en el clonado, rompiendo RF-011 y provocando un **500** al clonar una versión histórica. Validar además en el cierre: contradice «no se revalidan las versiones publicadas»; para eso está la guarda D-5. |
| D-3 | El marcador se **deriva** en un módulo puro y se pasa al motor (`compute_match_outcome`) en vez de construir el `MatchOutcome` a mano. | Construirlo a mano: duplica la validación de participación del ganador y separa el walkover de la matriz del paso 13. Dejar que el cliente lo envíe: es el defecto de hoy (HU-2). |
| D-4 | La guarda de coherencia (`winner <= loser` → 409) corre **antes** que la comprobación de marcador informado y que el motor. | Dejarla al motor: el motor acepta la pareja incoherente (solo compara con la configurada) y la clasificación daría la victoria al otro equipo. Ponerla después del motor: el 409 del motor por marcador incoherente ganaría y perdería el `code` y la salida documentada. |
| D-5 | El **motivo** se guarda en `resolution_reason` y por eso entra la migración 027; la obligatoriedad y el catálogo son de la API. | Guardarlo solo en la auditoría: incumple RF-007 («se guarda como código en `resolution_reason`») y deja el acta sin motivo. Añadir una columna nueva: más superficie que relajar un `CHECK` que ya existe. Imponer el catálogo en la base: la spec lo descarta (un `CHECK ... IN (...)` acepta `NULL`). |
| D-6 | La plantilla y los bloqueos de jugador se cargan **después** del paso 5. | Dejarlos antes: la rama consultaría plantilla y tomaría bloqueos que no necesita (RNF-008). Duplicar la carga con una guarda: dos consultas para el mismo dato. |
| D-7 | Una nota explica que el walkover no necesita segmento ni planilla. | No añadirla: el botón habilitado junto a un requisito marcado como pendiente parece un defecto. Ocultar los ítems del checklist: la 016 no cambia el checklist y el dato («no hay segmento») sigue siendo cierto. |
| D-8 | `reason` es el **mismo** campo del DTO con dos dominios (catálogo en walkover, texto en administrativa). | Un campo nuevo `walkover_reason`: RF-007 fija el nombre `reason`, y dos campos con el mismo destino en la misma columna obligan a decidir cuál gana. |
| D-9 | Los marcadores regulares del DTO pasan a opcionales y el validador exige su presencia fuera del walkover. | Mantenerlos obligatorios y aceptar `0` como «no informado»: un walkover 0-3 legítimo (versión histórica) sería indistinguible de un cliente que envía 0-0 por defecto —que es exactamente lo que hace hoy la pantalla—. |
| D-10 | El cliente deja de enviar los seis marcadores en walkover y el servidor los **ignora** si coinciden. | Confiar en lo que teclee el operador (estado actual): el marcador del W.O. no es una decisión del operador (HU-2). Rechazar siempre los marcadores informados: rompe a un cliente antiguo que hoy funciona (RF-005). |
| D-11 | La coherencia de la pareja no se exige en el **clonado** de versiones. | Exigirla: convertiría una copia en una reescritura de la configuración publicada y podría fallar con 500 al clonar. |
| D-12 | El `audit_payload` gana `resolution_reason` en la raíz. | Dejarlo solo dentro de `request`: el motivo quedaría enterrado en el volcado del DTO; RNF-010 pide que el contenido incluya resolución, ganador, marcador y motivo. |
| D-13 | El cliente **no** bloquea el cambio a `walkover` por segmentos persistidos fuera del máximo (`resolutionChangeOutcome` los ignora cuando la resolución es `walkover`), pero sigue avisando de los eventos del borrador. | Dejarlo como está en la 017: un partido con un segmento abierto en el minuto 100 (creado con prórroga) no se podría cerrar como W.O. desde la pantalla, aunque el servidor lo acepte (la rama no valida segmentos). Ignorar también los eventos: el acta con eventos del borrador se rechaza en la validación previa con un mensaje concreto y perder ese aviso al cambiar de resolución sería engañoso. |

## 8. Base de datos

**Migración 027 — `027_walkover_resolution_reason.sql`** (la 016 **sí** necesita migración; ver §2 y D-5).

- **Qué hace:** `ALTER TABLE public.matches DROP CONSTRAINT IF EXISTS chk_administrative_resolution_reason;` y la vuelve a crear, **validada**, con:

```sql
CHECK (
    (resolution_type = 'administrative' AND resolution_reason IS NOT NULL
     AND LENGTH(BTRIM(resolution_reason)) BETWEEN 1 AND 1000)
 OR (resolution_type = 'walkover'
     AND (resolution_reason IS NULL
          OR resolution_reason IN ('no_show', 'withdrawal', 'insufficient_players', 'sanction')))
 OR (resolution_type IS DISTINCT FROM 'administrative'
     AND resolution_type IS DISTINCT FROM 'walkover'
     AND resolution_reason IS NULL)
)
```

- **Qué NO hace:** no añade columnas, índices, políticas, RLS ni grants; no reescribe filas (todas las de `walkover` tienen hoy `resolution_reason` nulo); no toca `init/01`, `init/02` ni `init/03`; no cambia `schema_migrations` más allá de registrarse.
- **Por qué es seguro sobre volumen limpio y migrado:** en el limpio, `init/01` crea la restricción con el nombre exacto y la 009 la da por existente; la 027 la reemplaza. En uno ya migrado, la 027 encuentra la misma restricción de la 009. Un `DROP`+`ADD` validado recorre la tabla una vez; es aceptable por el tamaño de `matches` y no hay filas que puedan incumplir.
- **`NULL` sigue permitido en walkover** para las filas históricas y para un despliegue en el que la migración llegue antes que el código.
- **Orden de despliegue: 027 → código.** El código nuevo escribe un motivo no nulo; contra el esquema 026 el `UPDATE` violaría la restricción y el cierre devolvería un 409 de integridad engañoso. La imagen anterior convive con la 027 sin cambios (sigue escribiendo `NULL`).
- **Sin rollback:** cualquier defecto se corrige con una migración nueva (*forward-fix*). El esquema de trabajo pasa de **026** a **027** en `AGENTS.md`.
- **Verificación:** `sh -n infra/postgres/migrate.sh`, `backend/tests/test_migration_027.py` (cadena limpia `init` + 001…027 y salto 026 → 027) y, en el volumen de desarrollo, `MIGRATION_TARGET=027 $COMPOSE run --rm db-migrate`.

## 9. Backend, RLS y bloqueo

- **Módulo:** `backend/app/modules/matches/`; el router ya está registrado en `main.py`, que solo gana tres líneas de manejador. No hay módulo ni router nuevos.
- **RLS:** el cierre abre transacción y llama a `set_rls_context()` antes de cualquier consulta (sin cambios). La rama no añade consultas tenant: usa el partido, el segmento activo y la regla que ya se cargaron, y escribe con el mismo `organization_id` del contexto. `derive_walkover_score` no consulta.
- **Bloqueo (RNF-008):** se conserva fase → versión → destinos de avance → partido → segmento → jugadores. La rama toma el bloqueo del partido y (si existe) del segmento activo, y **no** toma bloqueos de jugador. El cierre serializa igual por fase.
- **Errores:** los tres códigos nuevos se lanzan desde el servicio y los traduce el manejador único de `main.py` (patrón de la 017). Los 422 estructurales siguen saliendo antes del handler y sin `code`.

## 10. Eventos asíncronos

**Sin cambios de contrato.** La rama emite los mismos tres eventos que un cierre normal (`MATCH_CLOSED`, `MATCH_UPDATED`, `STANDINGS_UPDATED`) con la misma carga `{match_id, tournament_id}`; el worker y el relay no se tocan y no se añade ningún tipo nuevo. La pantalla de operación se refresca por el mismo camino (socket → `requestOperationReload`), sin estado nuevo.

## 11. Frontend

- Toda llamada pasa por `frontend/app/composables/useApi.ts`; **no** hay llamadas nuevas (el cierre y la operación ya existen).
- Lógica nueva en `frontend/app/utils/matchClose.ts`, probada con `node --test` en `frontend/tests/`. La pantalla solo cablea.
- El host no tiene Node con TypeScript: **todas** las verificaciones se ejecutan en el contenedor (`docker compose exec -T web pnpm test`, `… pnpm run typecheck`, `… pnpm run build`).
- Anclas que no deben moverse: `closeReport`, `reportClosed`, `segmentStartField`, `createSegment`, `eventAdd` (el arnés `operation-flow` las usa).

## 12. Exposición pública

- **El resultado de un W.O. sí es visible**, y no cambia nada: `GET /api/v1/tournaments/public/{id}/matches` ya devuelve `home_score`, `away_score`, `winner_team_id`, `status` y `resolution_type` desde `v_public_matches`; la clasificación pública sale de `GET …/public/{id}/standings`, que cuenta el partido como jugado con el marcador configurado (DU-6).
- **No se añade ningún campo público**: `resolution_reason` (el motivo) **no** se publica —la consulta pública no lo selecciona— y no se añade ninguna marca de W.O. a las estadísticas ni a la tabla (RF-008). El `resolution_type = "walkover"` ya existía en el contrato público antes de esta spec.
- **Datos personales:** ninguno nuevo. La rama no lee ni escribe jugadores, alineaciones, documentos ni fechas de nacimiento; el motivo es un código de catálogo; la auditoría guarda resolución, ganador, marcador y código. Fotos y consentimiento: no aplica.

## 13. Configuración y secretos

**No aplica.** Sin variables de entorno nuevas, sin cambios en `.env.example`, compose, `check_env_contract.py` ni secretos. `MIGRATION_TARGET=027` es la variable existente del servicio `db-migrate`.

## 14. Lo que la 017 delegó a la 016 (cierre formal)

La 017 dejó fuera de su alcance, y la 016 los asume **todos** aquí:

| Delegado por la 017 | Dónde se implementa | Prueba |
|---|---|---|
| Exención del **segmento activo** (paso 6) | `_execute_walkover` (no ejecuta el paso 6) | `test_walkover.py`, DB en `test_match_resolution_db.py` |
| Exención de la **estructura de segmentos** (minutos/máximo del paso 6) | idem | DB |
| Exención de la **plantilla** (paso 7, incluido `_validate_rosters`) | idem; la carga se mueve detrás del paso 5 | DB: equipo sin ningún jugador |
| **Motivo** obligatorio de catálogo | DTO + `resolution_reason` + migración 027 | `test_walkover.py` (422) + DB |
| **Marcador derivado** y publicado | `derive_walkover_score` + `limits.walkover_score` | `test_walkover.py` + puro frontend |
| **Preflight del cliente** | `closePreflight` + pantalla | `match-close.test.ts` + barrido |
| Estados en que se admite (sin transiciones nuevas) | paso 3 con `WALKOVER_STATE_NOT_ALLOWED` | `test_close_validation_order.py` |
| Criterio 16 de la 017 («no aplicable hasta la 016») | queda **cumplido**; no se edita la 017 | — |

Lo que la 016 **no** reabre: los 14 pasos y su precedencia, los 422/409 de la matriz de marcadores del resto de resoluciones, `DOUBLE_YELLOW_INCONSISTENT`, `next_segment`, `ASSIST_PLAYER_INVALID`, la regla única de identificadores, la idempotencia y la inmutabilidad del acta confirmada.

## 15. Estrategia de tests

### Sin base de datos (`cd backend && pytest -q`)

| Archivo | Qué cubre |
|---|---|
| `backend/tests/test_walkover.py` (**nuevo, puro**) | `derive_walkover_score`: default 3-0, override de fase, 3-1, orientación local/visitante, ganador ajeno → `None`, pareja incoherente → `is_coherent` falso. `validate_walkover_score`: 3-0 y 3-1 aceptados; 0-0, 0-3 y override incoherente → `ValueError` con la pareja en el mensaje y orden estable con dos overrides. DTO: walkover sin marcadores = válido; `reason` ausente / `home_win` fuera del catálogo → `ValidationError`; eventos → `ValidationError`; falta `winner_team_id` → `ValidationError`; `regular`/`extra_time`/`penalties` siguen exigiendo la pareja reglamentaria; `reason` sigue prohibido fuera de `walkover`/`administrative`. |
| `backend/tests/test_close_validation_order.py` (existente, ampliado) | Precedencia con dobles: walkover **sin** segmento activo ni plantilla **pasa** hasta la escritura; `403` de la conjunción antes de la rama; `409 WALKOVER_STATE_NOT_ALLOWED` gana a cualquier defecto del acta; `409 WALKOVER_CONFIG_INCONSISTENT` gana a `WALKOVER_SCORE_MISMATCH`; 422 estructural (motivo) gana a cualquier 409; en todos los fallos `assert_nothing_was_written`. |
| `backend/tests/test_lock_order.py` (existente, ajustado) | El caso de cierre deja de suponer que un walkover recorre el tronco: se detiene en la primera escritura de la rama y sigue exigiendo identidad → fase → versión → destinos → partido antes de escribir. |
| `backend/tests/test_match_minutes.py`, `test_rule_contract.py` (existentes) | Siguen verdes: `resolution_enabled` admite walkover y `engine_version` sigue en `2026.1`. |

### Opt-in con PostgreSQL (`RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL=…`)

| Archivo | Qué cubre |
|---|---|
| `backend/tests/test_migration_027.py` (**nuevo**) | Cadena limpia `init` + 001…027 y salto 026 → 027: la restricción admite walkover con los cuatro códigos y con `NULL`, rechaza un código fuera del catálogo, sigue exigiendo motivo en `administrative` y sigue prohibiendo motivo en `regular`; filas históricas de walkover con `NULL` intactas; cadenas limpias y migradas equivalentes. |
| `backend/tests/test_match_resolution_db.py` (existente, ampliado) | **Sin segmento y sin plantilla** el walkover cierra (casos 1 y 2). **Con segmento activo**, queda `completed` con `minute_end = minute_start` y `match_segment_team_state` **no** cambia (caso 3/4). Marcador derivado en reglamentario y final (3-0 y override 3-1). `status='finished'`, `result_confirmed`, `resolution_reason` con el código. Clasificación: `played`, `won/lost`, puntos y goles en la diferencia. Avance: el ganador llega al destino. **Suspensiones:** un jugador suspendido no cumple sanción en el W.O. y no se crea ninguna. **409 con `code`** de los tres casos y **cero escrituras**. **Segundo intento** sobre el acta confirmada → 409 sin escritura. **Concurrencia** con la creación de un segmento y con una interrupción, en las dos órdenes (casos 15-17). |
| `backend/tests/test_close_authorization_db.py` (existente) | Sigue verde; el walkover usa la misma conjunción que el cierre (no se añade caso nuevo: el 403 se prueba con dobles en la matriz). |

### Frontend (`docker compose exec -T web pnpm test`)

| Archivo | Qué cubre |
|---|---|
| `frontend/tests/match-close.test.ts` (**nuevo**) | `closePreflight`: walkover sin segmento y sin planilla → sin problema; `regular` sin segmento → `needSegmentLineup`; walkover sin motivo o con motivo fuera del catálogo → `walkoverReasonRequired`; walkover con eventos → error; walkover sin ganador → error; `administrative` conserva su texto libre; `reason` sigue prohibido en las demás. `buildCloseReportBody`: walkover **no** emite ninguna de las seis claves de marcador y sí `winner_team_id` y `reason`; el resto de resoluciones conserva el cuerpo actual. `walkoverScoreFrom`: clave presente, ausente y nula. |
| `frontend/tests/match-resolution.test.ts` (existente) | `classifyMatchConflict` con los tres códigos nuevos y un 409 sin `code` → `other`; `resolutionChangeOutcome`/`closeResolutionDecision` con `walkover` **no** devuelven `blocked` con segmentos fuera del máximo y sí siguen avisando de los eventos del borrador. |
| `frontend/tests/match-operation-screen.test.ts` (existente) | Barrido de la pantalla: el selector de motivo existe con sus cuatro opciones y `aria-describedby`; el marcador efectivo se muestra en solo lectura; el `disabled` del botón ya no incluye `!selectedSegmentIsActive` para walkover; el cuerpo del cierre sale de `buildCloseReportBody`; paridad es/en y uso real de las claves nuevas (mismo mecanismo de `extractUsedKeys`). |

### Extremo a extremo (`frontend/e2e`, proyecto `operation-flow`) — **obligatorio**

La 016 cambia la pantalla que el arnés recorre (apertura, alta de evento, **cierre del acta**). Debe ejecutarse **en exclusiva**, sin `typecheck` ni `build` concurrentes (comparten `.nuxt` y producen `view-timeout`), limpiando los torneos «Copa E2E» de corridas anteriores (a 50 ocultan el demo por paginación y el `short_code` derivado del reloj colisiona):

```sh
# 1. Exclusiva: sin dev server ni build en paralelo.
docker compose up -d --wait
# 2. Limpiar residuos de corridas anteriores.
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
BEGIN;
SET LOCAL session_replication_role = replica;  -- solo dentro de la transacción
DELETE FROM matches WHERE tournament_id IN (SELECT id FROM tournaments WHERE name LIKE 'Copa E2E%');
DELETE FROM stages WHERE tournament_id IN (SELECT id FROM tournaments WHERE name LIKE 'Copa E2E%');
DELETE FROM tournament_versions WHERE tournament_id IN (SELECT id FROM tournaments WHERE name LIKE 'Copa E2E%');
DELETE FROM tournaments WHERE name LIKE 'Copa E2E%';
COMMIT;
SQL
# El borrado directo falla por FK (tournament_versions) y el de equipos «Límites/Frontera … FC»
# por las plantillas: borra en orden o usa el bloque de arriba. Sin esto, el residuo se acumula.
# 3. Correr el escenario.
cd frontend && pnpm run e2e:test
```

Interpretación: **0** verde (las tres vistas y `operation-flow` en `passed`), **1** fallo de comportamiento, **2** fallo de infraestructura, **3** corrida inválida. Solo **0** abre el gate; un 2 o un 3 **no** se declaran verdes. Si se ejecutó un `build`, reiniciar `web` antes de la corrida.

## 16. Trazabilidad RF → archivo/prueba

| RF | Implementación | Prueba |
|---|---|---|
| RF-001 (estados, ganador, versión) | `service.execute` paso 3 con `WalkoverStateNotAllowed`; rama tras el paso 5 | `test_close_validation_order.py` (estado) + DB (`suspended`, terminales) |
| RF-002 (autorización) | `service.execute` paso 2 (sin cambios) | `test_close_validation_order.py` (403 antes de la rama) + `test_close_authorization_db.py` |
| RF-003 (sin segmento ni plantilla) | `_execute_walkover` omite 6 y 7; carga de plantilla detrás del paso 5 | DB: partido sin segmento y equipo sin jugadores |
| RF-004 (segmento activo y proyección) | UPDATE del segmento con `minute_end = minute_start`; sin `_rewrite_segment_team_state` | DB: segmento cerrado, proyección intacta, sin segmentos no se crea |
| RF-005 (`limits`, derivado, `WALKOVER_SCORE_MISMATCH`) | `derive_walkover_score`; `_build_operation_limits`; DTO con marcadores opcionales | `test_walkover.py` + DB (3-0, override 3-1, mismatch 409 con `code`) |
| RF-006 (422 con eventos) | DTO (`schemas.py:198`) | `test_walkover.py` + `test_match_resolution_db.py` (existente) |
| RF-007 (motivo de catálogo) | DTO + `resolution_reason` + migración 027 + auditoría | `test_walkover.py` (422) + `test_migration_027.py` + DB |
| RF-008 (efecto y coherencia del ganador) | Rama 13′/14′: pareja, guarda, motor, clasificación, avance, sin sanciones | DB (tabla, goles, avance) + `test_walkover.py` (`is_coherent`) |
| RF-009 (sin sanciones) | La rama no llama a `_validate_suspensions`, `_serve_suspensions`, `_insert_suspensions` ni `evaluate_suspensions` | DB: suspensión activa no servida y ningún registro nuevo |
| RF-010 (acta confirmada inmutable) | paso 3 (`finished`) + trigger 016 de la migración 016 | DB: segundo intento 409 con `code` |
| RF-011 (`winner > loser` al guardar/publicar) | `validate_walkover_score` en `rules_engine/schemas.py` y en la publicación | `test_walkover.py` (puro) + ruta 422 |
| RF-012 (preflight y formulario) | `closePreflight`, `buildCloseReportBody`, `resolutionChangeOutcome` exento de segmentos en walkover, pantalla e i18n | `match-close.test.ts` + `match-resolution.test.ts` + `match-operation-screen.test.ts` |
| RF-013 (`engine_version` 2026.1, sin claves nuevas) | Sin cambios en `rules_config` | `test_rule_contract.py` (existente) |
| RNF-001 (aislamiento) | 404 al cargar el partido; mismo `organization_id` en las escrituras | DB + `test_close_validation_order.py` |
| RNF-002 (privacidad) | Motivo = código; auditoría sin nombres | `test_walkover.py` (catálogo cerrado) + DB (payload) |
| RNF-003 (contratos que cambian) | §6 y §14 + `AGENTS.md`/`README.md` | las pruebas de las filas anteriores |
| RNF-004 (base de datos) | Migración 027 | `test_migration_027.py` |
| RNF-005 (verificación) | T10 | `pytest -q`, `compileall`, `pnpm test`, `typecheck`, `build`, `e2e:test` |
| RNF-006 (determinismo) | Derivación pura; overrides ordenados; sin reloj | `test_walkover.py` |
| RNF-007 (accesibilidad) | Selector de ganador y de motivo, cada uno con su etiqueta y su error asociado (`aria-invalid`/`aria-describedby` + `role="alert"`); aviso `role="status"` del marcador | `match-operation-screen.test.ts` (barrido de la fuente de la pantalla y de la clave del error). El recorrido real con teclado del W.O. **no** lo cubre el E2E: `frontend/e2e/` no menciona el walkover |
| RNF-008 (rendimiento y bloqueo) | Rama sin plantilla/contadores/sanciones; mismo orden de bloqueo | `test_lock_order.py` + DB |
| RNF-009 (documentación) | `AGENTS.md`, `README.md` (runbook 027) | revisión + `verify_version_sources.py` |
| RNF-010 (auditoría) | `CLOSE_MATCH_REPORT` con `resolution_reason` | DB (payload de auditoría) |
| RNF-011 (tiempo real) | Mismos tres eventos de outbox | DB (outbox); el E2E no observa el outbox |

## 17. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 RLS lo garantiza la base | Sí | Sin tablas nuevas; la rama escribe con el mismo `set_rls_context()` y el mismo `organization_id` en cada sentencia. |
| §2.2 La aplicación no se salta RLS | Sí | Sin cambios de rol, `BYPASSRLS`, superusuario ni grants (la 027 no concede nada). |
| §2.3 Lo publicado es inmutable | Sí | El walkover es una primera escritura, no una corrección; el acta confirmada la protegen el trigger 016 y el paso 3. No hay ruta de anulación. |
| §2.4 Historial de esquema *append-only* | Sí | La 027 es una migración **nueva** y numerada; no se edita ninguna aplicada ni `init/01`. |
| §2.5 Lo público es una proyección mínima | Sí | Ningún campo público nuevo; `resolution_reason` no se publica; sin datos personales; fotos con consentimiento, sin cambios. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Sin variables ni secretos nuevos. |
| §2.7 Administración global separada y auditada | Sí | `/admin` no se toca; la acción auditada es la del cierre, ya existente. |
| §2.8 Nada se termina sin verificación | Sí | Cada tarea declara «Hecho cuando» con comandos reales; la última incluye backend, migración, frontend, `typecheck`, `build` y **E2E en exclusiva**; lo no ejecutado se declara. |
| §2.9 El código de desarrollo no llega a producción | Sí | No se toca el seed; las pruebas de base son opt-in. |
| §4 Todos: CI correspondiente | Sí | `backend`, `frontend`, `infrastructure` y `security` pasan; el job `e2e` de CI (reintento) no cubre el escenario de operación, que se ejecuta a mano por exigencia de RNF-005. |
| §4 Todos: sin secretos ni datos personales | Sí | Solo identificadores en pruebas; el motivo es un código. |
| §4 Todos: documentación afectada | Sí | `AGENTS.md` y `README.md` en la tarea de documentación; `docs/contrato-reglas.md` no cambia. |
| §4 Todos: pruebas del comportamiento nuevo | Sí | Dos archivos backend nuevos (`test_walkover.py`, `test_migration_027.py`), dos ampliados (`test_close_validation_order.py`, `test_match_resolution_db.py`), uno ajustado (`test_lock_order.py`), uno frontend nuevo (`match-close.test.ts`), dos ampliados y el E2E. |
| §4 Base de datos: nueva migración numerada | Sí | 027, sin editar aplicadas. |
| §4 Base de datos: RLS y políticas en tablas nuevas | No aplica | No hay tablas nuevas. |
| §4 Base de datos: volumen limpio y migrado | Sí | `test_migration_027.py` construye las dos cadenas y las compara. |
| §4 Base de datos: `sh -n migrate.sh` | Sí | En la tarea de la migración y en la verificación final. |
| §4 API: consultas tenant con `set_rls_context()` | Sí | Sin consultas nuevas fuera de la transacción del cierre. |
| §4 API: endpoints públicos sin campos sensibles | Sí | Sin campos nuevos; `resolution_reason` fuera de lo público. |
| §4 API: router nuevo registrado en `main.py` | No aplica | Solo se registran tres manejadores de excepción. |
| §4 API: `pytest -q` y `compileall` | Sí | Todas las tareas de backend y la verificación final. |
| §4 Frontend: llamadas por `useApi.ts` | Sí | No hay llamadas nuevas. |
| §4 Frontend: `pnpm test`, `typecheck`, `build` | Sí | Tareas de frontend y verificación final, dentro del contenedor `web`. |
| §4 Infraestructura: `docker compose config -q` | No aplica | Sin cambios de compose; la 027 se aplica con `MIGRATION_TARGET`. |
| §4 Dependencias: lockfiles y auditorías | No aplica | Sin dependencias nuevas. |
