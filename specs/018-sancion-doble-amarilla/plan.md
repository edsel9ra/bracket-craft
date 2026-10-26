# Plan 018 — Sanción única por doble amarilla

Spec: `specs/018-sancion-doble-amarilla/spec.md` (15 RF, aprobada el 2026-10-25).
Constitución: `docs/constitution.md` v1.4.0. Contrato interno: `docs/contrato-reglas.md` (`engine_version` **2026.1**, sin cambios).
Estado del código: leído el 2026-10-25, **después** de la 015 (catálogo de eventos y asistencia), la 016 (walkover) y la 017 (orden único del cierre). Esquema en **027**.

## 1. Alcance

Todo el cambio vive en la **derivación de sanciones** al cerrar el acta: funciones puras del motor (`rules_engine`), el cableado del cierre (`matches/service.py`) y ninguna otra capa. **Sin migración**, **sin endpoint nuevo**, **sin pantalla nueva** y **sin eventos de outbox nuevos**.

Lo que la spec cambia y el plan implementa:

1. Una jugada (expulsión por doble amarilla) produce **una** sanción: la acumulación de sus amarillas se absorbe (RF-001, RF-002).
2. La sanción se deriva del **tipo de roja registrado**, también en el cierre que la registra (RF-010).
3. **Solo los eventos del acta que se cierra originan sanciones**; el historial cuenta y empareja, nunca crea (RF-005).
4. Un evento de roja tiene **como máximo una sanción**, con cualquier motivo, comprobado **aparte** de la identidad torneo+jugador+evento+motivo (RF-005, R-3).
5. El **recuento auditado** pasa a ser el de sanciones **realmente creadas** (RF-012, R-5).

Lo que la 018 **no** toca: el orden único de 14 pasos y la coherencia de la doble amarilla de la 017 (RF-013), la rama del walkover (016), el catálogo de eventos y la asistencia (015), `rules_config`, `schema_version`, `engine_version` y las duraciones configuradas.

**Riesgo global:** el punto 3 es un **cambio de comportamiento** que hoy no está documentado en ninguna spec (el historial podía originar filas nuevas y, con la etiqueta heredada, una **segunda** fila con otro motivo). El plan lo trata como contrato declarado en RNF-004(c) y lo cubre con pruebas explícitas de «no origen» y de «roja histórica que no se duplica».

## 2. Archivos y responsabilidades

### Backend

| Archivo | Responsabilidad |
|---|---|
| `backend/app/modules/rules_engine/engine.py` | (a) **Reescribir** `evaluate_suspensions(config, current_events, historical_events)` con la separación acta/historial, el conteo de amarillas y la absorción; (b) nuevas funciones puras `discipline_history_order_key(event)`, `order_discipline_history(events)` y `drop_recorded_red_sanctions(suspensions, recorded_event_ids)`; (c) la roja toma su motivo de `metadata.red_card_type` **del evento tal como está registrado**. Sin claves nuevas de configuración y sin tocar `validate_rules_config`, `RULES_SCHEMA`, `compute_match_outcome` ni `deterministic_tie_value`. |
| `backend/app/modules/matches/service.py` | (a) `_persist_events`: añadir `metadata` al `RETURNING` del `INSERT` (**de ahí sale el tipo fiable de la roja del mismo cierre**, RF-010); (b) `_load_discipline_history`: devolver `minute`, `added_minute`, `event.id`, `me.match_id` y `m.match_date`, sin cambiar el filtro de ámbito (fase/versión con el reinicio activo, RF-008); (c) nuevo `_load_recorded_red_suspensions(context, red_event_ids)` — una sola lectura **acotada a los eventos de roja del acta**, sin filtro de estado (RF-005, RNF-010); (d) el bloque de cierre deriva (la absorción ocurre dentro de la función pura), aplica **después** la unicidad por evento de roja e inserta; (e) `_insert_suspensions` devuelve el número de filas **realmente creadas** (`RETURNING id`) y la auditoría usa ese número (RF-012). No se toca el orden de los 14 pasos, ni `_validate_double_yellow`, ni `_serve_suspensions`, ni `_execute_walkover`. |
| `backend/tests/test_sanctions.py` (**nuevo, puro**) | Derivación, absorción, conteo, orden del historial y unicidad por evento de roja, sin base y sin reloj. |
| `backend/tests/test_sanctions_db.py` (**nuevo, opt-in**) | Cierre real: absorción, no origen por historial, roja histórica mal etiquetada que no se duplica, recuento auditado y aislamiento. |
| `backend/tests/test_close_validation_order.py` (existente) | El doble `CloseOrderSession` **aprende** la consulta nueva (rama por `source_event_id` en `FROM player_suspensions`) y devuelve `metadata` en la fila del `INSERT INTO match_events`, para que el escenario de doble amarilla represente lo que la base devuelve. Sin cambios de comportamiento esperados. |
| `backend/tests/test_rules_engine.py` (existente) | `test_suspensions_are_created_for_card_thresholds_and_red_cards` sigue siendo válido (la amarilla que cruza el umbral es **del acta**): solo se revisa su comentario si menciona el origen histórico. |
| `backend/tests/test_double_yellow.py` (existente) | Se conserva; su escenario de doble amarilla válida espera **1** sanción y sigue igual. Se añade, si el caso no existe, el escenario de la fila con `reason` de doble amarilla (**RF-010**). |

### Frontend

**Sin cambios.** La spec no añade superficie (RF-015) y el cierre devuelve solo `{status, match_id, home_score, away_score, winner_team_id}` (`service.execute`, líneas 923-929): el recuento de sanciones vive únicamente en el `payload` de auditoría, que **no tiene endpoint de consulta**. Verificación de que no se toca nada:

```sh
git grep -n "suspension" -- frontend/app frontend/tests frontend/e2e
```

Hoy solo aparecen los textos de reglas (`rules.*SuspensionMatches`) y el comentario de autoridad del servidor en `frontend/app/pages/workspace/matches/[id].vue:1245`; ninguno lee sanciones derivadas. **No** se toca `[id].vue`, `useI18n.ts` ni `useApi.ts`, y **no** se añade clave de traducción: no hay texto nuevo que traducir.

### Documentación (tarea propia)

| Archivo | Responsabilidad |
|---|---|
| `AGENTS.md` | Nuevo apartado «Sanciones y disciplina (spec 018)» en «Arquitectura Clave»: sanción única por jugada, absorción de todos los umbrales del acta, duración única de expulsión, la amarilla que provoca la roja cuenta, origen de las sanciones (acta, no historial), unicidad por evento de roja, tipo de roja del mismo cierre y recuento auditado. Entrada en «Contratos que cambian» con RNF-004(a)-(d). Línea en «Testing» con los dos archivos nuevos y su opt-in. |
| `README.md` | Sección de disciplina/sanciones del cierre: qué cuesta una expulsión por doble amarilla, qué es un partido de suspensión (sin cambios) y qué **no** cambia (duraciones, umbrales, *fair play*, walkover, contratos HTTP). |
| `docs/contrato-reglas.md` | **No cambia**: la disciplina y las sanciones no forman parte del contrato cerrado. Se comprueba con `git diff docs/contrato-reglas.md` vacío. |

## 3. Funciones puras

Ninguna lee el reloj, el entorno, el almacenamiento ni la red. La fecha de juego llega **resuelta** desde la consulta; el orden se calcula sobre datos ya persistidos.

| Función | Firma | Dónde | Nota |
|---|---|---|---|
| `evaluate_suspensions` | `(config: Mapping, current_events: Sequence[Mapping], historical_events: Sequence[Mapping]) -> list[dict]` | `rules_engine/engine.py` | **Contrato nuevo, mismo nombre y firma.** `current_events` = eventos del acta en cierre, en orden canónico del payload; `historical_events` = historial, en cualquier orden (la función ordena). Solo `current_events` originan. No lee el reloj ni escribe. |
| `discipline_history_order_key` | `(event: Mapping) -> tuple` | `rules_engine/engine.py` | Clave **total y estable**: `(fecha_de_juego o −inf, str(match_id), minute, added_minute, str(event_id))`. Un evento sin fecha va antes que cualquiera con fecha. |
| `order_discipline_history` | `(events: Iterable[Mapping]) -> list[Mapping]` | `rules_engine/engine.py` | `sorted(events, key=discipline_history_order_key)`; idempotente y estable. |
| `drop_recorded_red_sanctions` | `(suspensions: Sequence[Mapping], recorded_event_ids: AbstractSet[UUID \| str]) -> list[Mapping]` | `rules_engine/engine.py` | Quita las sanciones **de roja** cuyo `source_event_id` ya está registrado, con **cualquier motivo**. No reescribe nada. |

`compute_match_outcome` y `deterministic_tie_value` (motor) no se tocan. `double_yellow_violations` (017, en `matches/service.py`) tampoco: es la coherencia del acta, otra regla.

## 4. Pseudocódigo

### 4.1 Derivación: separar acta e historial, contar y absorber (RF-001, RF-002, RF-004, RF-008, RF-009, RF-010)

```
def evaluate_suspensions(config, act_events, historical_events):
    limit        = config["discipline"]["yellow_card_limit"]              # >= 1 (RULES_SCHEMA)
    yellow_days  = config["discipline"]["yellow_card_suspension_matches"]
    red_days     = config["discipline"]["direct_red_suspension_matches"]  # única duración de expulsión

    # --- 1. HISTORIAL: solo cuenta amarillas; nunca origina -----------------
    yellows = defaultdict(int)
    for event in order_discipline_history(historical_events):
        if event["event_type"] == "yellow_card" and event.get("player_id"):
            yellows[event["player_id"]] += 1

    # --- 2. ACTA: una pasada en orden canónico (índice del payload) ---------
    derived   = []                       # en el orden del acta, determinista
    double_yellow_players = set()
    for event in act_events:             # orden = el de `_persist_events`
        player = event.get("player_id")
        if not player:
            continue
        if event["event_type"] == "yellow_card":
            yellows[player] += 1
            if yellows[player] % limit == 0:
                derived.append(sanction(player, event["id"], yellow_days,
                                        "yellow_card_accumulation"))
        elif event["event_type"] == "red_card":
            recorded = (event.get("metadata") or {}).get("red_card_type")
            if recorded == "double_yellow_red":
                double_yellow_players.add(player)
                derived.append(sanction(player, event["id"], red_days,
                                        "double_yellow_red"))       # RF-010
            else:
                derived.append(sanction(player, event["id"], red_days,
                                        "direct_red_card"))         # roja directa: se queda

    # --- 3. ABSORCIÓN: una jugada, una sanción (RF-001, RF-002, RF-009) -----
    # Después de recorrer el acta: se absorben TODOS los umbrales que crucen
    # las amarillas de ese jugador en este acta, no solo el último.
    return [s for s in derived
            if not (s.reason == "yellow_card_accumulation"
                    and s.player_id in double_yellow_players)]
```

Propiedades que fija el plan:

- **La absorción se aplica al final**, sobre la lista completa del acta, para que dos umbrales del mismo acta caigan juntos (caso límite 3).
- **Absorción por jugador en el acta**, no por comparación de minutos: la 017 garantiza exactamente dos amarillas **previas** a la roja del mismo jugador y su paso 8 rechaza una amarilla posterior a la roja (el jugador ya no está en campo, prueba existente `test_double_yellow.py::test_yellows_after_the_red_are_reported_by_the_field_state_first`). No hay, por tanto, amarilla de ese jugador en el acta que no componga la expulsión.
- **No se absorbe la roja directa** (RF-009): el conjunto `double_yellow_players` solo se llena con `metadata.red_card_type == "double_yellow_red"`.
- **La roja no reinicia el contador**: `yellows[player]` se incrementa antes de mirar la roja y no se limpia (RF-004, criterio «no se descuenta ninguna»).
- **Sin historial en la salida**: ninguna rama de la parte 1 añade a `derived` (RF-005). El historial sigue trayendo amarillas **y rojas** (así lo define la spec), pero las rojas no se leen: no cruzan umbrales y no originan, y por eso el `WHERE` de `_load_discipline_history` no se estrecha.
- La lista de salida es determinista: orden del acta, sin `dict` por clave (la clave de deduplicación actual `jugador:evento:motivo` desaparece porque ya no hay dos motivos por evento: lo impide la unicidad del paso siguiente).

### 4.2 Unicidad por evento de roja (RF-005, R-3) — en el servicio, no en la firma pura

```
# En execute(), después de _persist_events (los ids ya existen) y antes de insertar:
red_event_ids = [e["id"] for e in persisted_events if e["event_type"] == "red_card"]
recorded      = await _load_recorded_red_suspensions(context, red_event_ids)   # 1 consulta, 0 si no hay rojas
suspensions   = drop_recorded_red_sanctions(suspensions, recorded)
```

```
def _load_recorded_red_suspensions(context, red_event_ids):
    si no red_event_ids: return set()
    SELECT DISTINCT source_event_id
    FROM player_suspensions
    WHERE organization_id = :organization_id
      AND source_event_id = ANY(CAST(:red_event_ids AS uuid[]))
    # sin filtro de status: una fila `served`, `cancelled` o `appealed` también cuenta
```

- La lectura está **acotada al conjunto de eventos de roja del acta** (RNF-010): no depende del historial ni del tamaño del torneo y desaparece cuando el acta no tiene rojas.
- Va **después de la absorción**: si el acta tiene una roja por doble amarilla ya sancionada y sus amarillas cruzan un umbral, la acumulación **se absorbe igualmente** (la jugada existió) y no se crea nada.

### 4.3 Conteo auditado (RF-012, R-5, RNF-008)

```
created = await _insert_suspensions(context, match, suspensions)   # INSERT ... ON CONFLICT DO NOTHING RETURNING id; created = len(filas)
audit_payload["suspensions"] = created        # antes: len(suspensions) derivadas
```

El `INSERT` conserva `ON CONFLICT (dedupe_key) DO NOTHING` como red de seguridad; el recuento deja de ser el tamaño de la lista derivada. El nombre de la clave (`suspensions`) **no** cambia: no hay consumidor de la auditoría (no existe endpoint de consulta).

### 4.4 De dónde sale el tipo de roja del mismo cierre (RF-010)

`_persist_events` devuelve la fila del `INSERT` con `RETURNING` que hoy **omite `metadata`** (líneas 1657-1659). Se añade `metadata` a ese `RETURNING`; la rama de reutilización idempotente ya la devuelve (`SELECT … metadata`, línea 1610). A partir de ahí:

- el evento que se acaba de insertar y el reutilizado tienen **la misma forma**, así que `evaluate_suspensions` lee siempre el tipo **registrado**;
- no se reconstruye el tipo desde el DTO (la fila es la autoridad, igual que en un cierre posterior);
- el doble `CloseOrderSession` devuelve también `metadata` en `_persist_event_row` para no divergir de la base.

### 4.5 Orden del historial (RF-004, RNF-003)

```
def discipline_history_order_key(event):
    match_date = event.get("match_date")
    return (
        match_date.timestamp() if match_date is not None else float("-inf"),   # sin fecha, primero
        str(event["match_id"]),          # empate de fecha o sin fecha
        int(event["minute"]),
        int(event["added_minute"]),
        str(event["id"]),                # desempate estable del evento
    )
```

No se persiste ningún desempate (R-6, RNF-005): la clave se calcula. `_load_discipline_history` añade `me.match_id` y `m.match_date` a su `SELECT` y **no** necesita `ORDER BY`; el orden lo fija la clave pura, que así queda cubierta por una prueba sin base. El ámbito (fase y versión con el reinicio activo) se sigue aplicando **antes**, en el `WHERE` (RF-008, sin cambios).

## 5. Interfaz

**No cambia ningún endpoint, código de respuesta ni contrato.** Confirmación contra RNF-004(e):

- `POST /api/v1/matches/{id}/close`: misma petición, misma respuesta (`status`, `match_id`, `home_score`, `away_score`, `winner_team_id`), mismos códigos (403/404/409/422) y mismos `code` aditivos. La regla **no añade un paso de validación** (RF-013): la sanción se deriva después de que todo haya validado, dentro de la misma transacción, y no puede provocar un error nuevo.
- `GET /api/v1/matches/{id}/operation`: sin campos nuevos (RF-015). El recuento de sanciones no se expone.
- Configuración de reglas (`PATCH /tournaments/{id}/versions/{version_id}/rules`, `POST /tournaments/{id}/versions/{version_id}/publish`): mismas claves, mismo `schema_version` `3.3.0`, mismo `engine_version` `2026.1`, mismos 422. No hay clave de absorción (RF-007) y `fair_play_penalties` no se toca.
- Persistencia: misma tabla `player_suspensions`, mismas columnas y misma `dedupe_key`; sin migración (RNF-005).

Si el plan detectara un cambio de contrato tendría que justificarlo contra RNF-004; no lo detecta, así que lo que se declara es solo lo que RNF-004 ya enumera: partidos cumplidos que bajan (a), etiqueta de la roja recién registrada que pasa a ser la correcta (b), origen de las sanciones (c) y recuento auditado (d).

## 6. Decisiones justificadas

| # | Decisión | Alternativa descartada y por qué |
|---|---|---|
| D-1 | **Cómo se separa acta/historial:** `evaluate_suspensions` conserva nombre y firma; `current_events` **origina**, `historical_events` **solo cuenta amarillas**. | Dos funciones (`count_yellows` + `derive`) encadenadas en el servicio: la separación se podría olvidar en cualquier llamada futura y la regla quedaría repartida. Añadir un parámetro `origins` booleano: deja abierta la puerta a «originar desde el historial» que la spec prohíbe. `current_events` es, por contrato del cierre, el acta en cierre. |
| D-2 | **El tipo de roja sale del `metadata` de la fila persistida** (`RETURNING metadata` en el `INSERT`). | Cruzar el payload por `client_event_id` con `persisted_events`: el acta ya trae `metadata`, pero introduce una segunda fuente y depende de que la fila sea siempre la del payload (la reutilizada puede venir normalizada). Inferirlo del número de amarillas: RF-010 lo prohíbe expresamente. Leer la fila con un `SELECT` extra: una consulta más por evento, contra RNF-010. |
| D-3 | **Unicidad por evento de roja en una lectura aparte** (`source_event_id = ANY(red_event_ids)`), **después de la absorción**, y aplicada a cualquier motivo y a cualquier `status`. | Confiar en `dedupe_key` (torneo+jugador+evento+motivo): es exactamente el defecto (dos motivos no colisionan, RF-005). Consultar todas las sanciones del torneo: crece con el historial y RNF-010 lo acota a las rojas del acta. Filtrar antes de absorber: dejaría una acumulación sin absorber y sin roja nueva, que es justo la doble sanción que la spec corrige. |
| D-4 | **La idempotencia se conserva en tres capas ya existentes:** `match_events.client_event_id` (reutiliza la fila y `409` si difiere), absorción determinista (mismas entradas, misma lista) y `ON CONFLICT (dedupe_key) DO NOTHING`. La unicidad por roja añade la cuarta: reutilizar un evento de roja **no** crea la fila corregida. | Clave única nueva en la base por `(organization_id, source_event_id)` para rojas: exige migración (RNF-005), no puede expresarse solo para un `event_type` sin un índice parcial nuevo y rompería el histórico (dos filas de la misma jugada en actas antiguas). Recalcular y borrar filas: RF-006 lo prohíbe. |
| D-5 | **Absorción por jugador en el acta**, al final del recorrido. | Emparejar por minutos (solo las dos amarillas anteriores a la roja): reproduce la regla de la 017 dentro de la de sanciones, añade una segunda implementación que puede divergir y no cambia ningún caso alcanzable (una amarilla posterior del mismo jugador la rechaza el paso 8). |
| D-6 | El **recuento auditado** sale del `RETURNING` del `INSERT` (filas creadas). | `COUNT(*)` después de insertar: una consulta más para un dato que la inserción ya devuelve. Mantener `len(suspensions)`: es el defecto que RF-012 corrige. |
| D-7 | **Sin migración.** | Un `CHECK`/índice parcial para la unicidad por roja: la regla depende del motivo registrado y de filas históricas que la incumplen (dos motivos de la misma jugada); un índice único rompería el histórico y RF-006 prohíbe tocarlo. La absorción y el conteo son cálculo. |
| D-8 | El **orden del historial** se calcula con una clave pura en Python; la consulta no ordena. | `ORDER BY` en SQL: el orden quedaría fuera del alcance de las pruebas puras y duplicaría la definición (dos fuentes que pueden divergir). Ordenar por `created_at`: no es un dato del juego y no cumple RF-004. |
| D-9 | La rama del **walkover** no se toca (auditoría con `suspensions: 0` literal). | Reutilizar el mismo recuento: no crea sanciones por definición; cambiarlo sería ruido en un camino que la 016 cerró. |
| D-10 | **Sin cambio de frontend.** | Añadir un contador de sanciones al cierre: superficie nueva prohibida por RF-015. |

## 7. Base de datos

**La 018 no necesita migración.** El esquema se queda en **027**. Justificación:

1. No hay columna, restricción, índice, política ni vista nueva: la regla es cálculo sobre `match_events` y `player_suspensions`, ambas ya existentes.
2. La unicidad por evento de roja **no puede** expresarse como restricción sin romper el histórico (conviven dos motivos de la misma jugada en actas anteriores) ni sin un índice parcial que la spec no autoriza (RNF-005).
3. No se reescribe ninguna fila: las sanciones existentes conservan motivo, duración y estado (RF-006).
4. `sh -n infra/postgres/migrate.sh` no se toca; ninguna prueba debe exigir columnas nuevas.

## 8. Backend, RLS y eventos asíncronos

- **Módulos:** `backend/app/modules/rules_engine/` (funciones puras) y `backend/app/modules/matches/` (cableado). Sin router nuevo, sin registro en `main.py`, sin permiso nuevo.
- **RLS:** el cierre ya abre transacción y llama a `set_rls_context()` antes de cualquier lectura; la consulta nueva de sanciones registradas y la del historial se ejecutan **dentro** de esa transacción y con `organization_id = :organization_id` explícito (RNF-001). No se añade ninguna lectura fuera de transacción.
- **Consultas:** el cierre pasa de 2 a **3** lecturas de disciplina como máximo (historial, sanciones de roja del acta, y las de plantilla que ya existían), con un número **fijo**: ninguna depende del número de jugadores, de eventos ni del tamaño del historial (RNF-010). Sin rojas en el acta, la lectura nueva no se ejecuta.
- **Eventos asíncronos:** **sin cambios**. Se conservan `MATCH_CLOSED`, `MATCH_UPDATED` y `STANDINGS_UPDATED` con su carga (`match_id`, `tournament_id`); no se añade ni se retira ninguno (RNF-009). El worker, el relay y Socket.IO no se tocan.
- **Bloqueos:** el orden fase → versión → destinos → partido → segmento → jugadores no cambia; la derivación no toma bloqueos nuevos (las filas de `player_suspensions` se insertan con la transacción del cierre, como hoy).

## 9. Frontend

**No aplica ningún cambio** (RF-015). Verificación explícita:

- `frontend/app/pages/workspace/matches/[id].vue` no consume sanciones; su comentario de la línea 1245 dice que las sanciones son autoridad del servidor y sigue siendo cierto.
- No se añaden claves a `frontend/app/composables/useI18n.ts`: la regla no cambia ningún texto visible (el bloqueo de planilla y el recuento del cierre ya existen).
- No hay llamadas nuevas: todo pasa por `useApi.ts` y no se toca.
- Se comprueba con `docker compose exec -T web pnpm test`, `… pnpm run typecheck` y `… pnpm run build` **sin cambios en el árbol** (deben seguir verdes) y con el E2E del apartado 12.

## 10. Exposición pública

**No aplica ningún cambio.** Las sanciones no se publican en ninguna proyección ni ruta pública y la 018 no añade ninguna: `v_public_*` no se toca, no hay campo nuevo, no se introducen datos personales (solo identificadores de jugador ya presentes en el acta) y las fotos siguen dependiendo del consentimiento de imagen, que esta spec no toca (RNF-002).

## 11. Configuración y secretos

**No aplica.** Sin variables de entorno, sin cambios en `.env.example`, en los compose ni en `check_env_contract.py`. Sin secretos nuevos. Sin claves nuevas en `rules_config`: se usan las cinco existentes de `discipline`, y en concreto la **única** duración de expulsión (`direct_red_suspension_matches`) para la sanción de la jugada (RF-003, RF-007).

## 12. Estrategia de tests

### 12.1 Sin base — motor puro (`cd backend && pytest -q`)

Archivo nuevo **`backend/tests/test_sanctions.py`** (mismo estilo que `test_double_yellow.py`: constructores `yellow(...)`/`red(...)`, sin reloj, `UUID(int=…)`).

| Caso | RF |
|---|---|
| Umbral cruzado por la **segunda** amarilla del acta y roja por doble amarilla → **una** sanción, motivo `double_yellow_red`, duración de expulsión | RF-001, RF-002, RF-003 |
| Umbral cruzado por la **primera** amarilla del acta y roja después → una sola sanción | RF-002 |
| **Dos umbrales** en el mismo acta (`limit` 1 y 2 amarillas) con doble amarilla → una sola sanción | RF-002 |
| Umbral cruzado y sancionado en un **acta anterior** (historial) + roja por doble amarilla en esta: la acumulación histórica **no** se reemite ni se absorbe | RF-002, RF-005 |
| **Ninguna** sanción se origina desde el historial: roja histórica sola → lista vacía | RF-005 |
| Roja **directa** + umbral en el mismo acta → **dos** sanciones, cada una con su duración | RF-009 |
| El tipo de roja se toma de `metadata.red_card_type` (`direct_red`, `double_yellow_red`, ausente → directa) y **no** del número de amarillas | RF-010 |
| **No se descuenta** ninguna amarilla: dos amarillas + roja con `limit` 2 y una amarilla histórica → una sola sanción y el contador posterior sigue contando desde 3 | RF-004 |
| Conteo con **baseline histórico** de fase (`clear_yellows_on_stage_change` aplicado aguas arriba): solo cuenta lo que recibe | RF-008 |
| Orden: `act_events` desordenado **no** se ordena (lo garantiza el servicio) y una permutación del **historial** da el mismo resultado (conteo conmutativo) | RF-004, RNF-003 |
| `discipline_history_order_key`: sin fecha antes que con fecha; empate de fecha por `match_id`; dentro del partido `minute`, `added_minute`, `id`; dos eventos idénticos en minuto y añadido se desempatan por id | RF-004 |
| `drop_recorded_red_sanctions`: quita la roja ya registrada **con cualquier motivo** y **no** quita la acumulación | RF-005, RF-012 |
| Lista de salida determinista (misma entrada dos veces → misma lista y mismo orden) | RNF-003 |

### 12.2 Opt-in con base (`RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL=…`)

Archivo nuevo **`backend/tests/test_sanctions_db.py`**, con los ayudantes ya existentes (`committed_application`, `seeded_match`, `create_closable_match`, `context_for`, `report`, `close_in_session`, `act_state`) y **un ayudante nuevo** `create_sibling_match(...)` que inserta un segundo partido en el **mismo torneo y versión**, con la fase del primero por defecto y otra fase cuando el caso lo pide (fila en `matches` con `match_date` opcional, un `match_segments` y las filas de `match_rosters` reutilizando los `rosters` del primero). El historial se siembra con `INSERT INTO match_events` directo, como ya hace `seed_other_match_yellows` de `test_double_yellow.py`.

| Caso | RF |
|---|---|
| `limit` 3, 1 amarilla histórica (otro partido del torneo) + 2 amarillas y una roja por doble amarilla en el acta → **1** fila en `player_suspensions`, `reason` `double_yellow_red`, `matches_suspended` = `direct_red_suspension_matches` | RF-001, RF-002, RF-003, RF-010 |
| La misma acta con `direct_red_suspension_matches` distinto de `yellow_card_suspension_matches` (p. ej. 2 y 4) → la fila conserva la duración **de expulsión** (2) y no hay segunda fila | RF-003 |
| **La roja recién registrada lleva su motivo correcto en el mismo cierre** (`metadata` del `RETURNING`): se cierra y se lee `reason` de la tabla | RF-010 |
| Los partidos de suspensión **cumplidos** coinciden con la duración configurada: se cierra un tercer partido sin convocar al jugador y la sanción queda `served` con **una** fila | RF-011 |
| **No origen por historial**: acta A con roja directa (y su fila), acta B posterior del mismo jugador sin tarjetas → **0** filas nuevas | RF-005, RF-006 |
| **Roja histórica mal etiquetada**: se siembra a mano la roja con `double_yellow_red` y una fila con `reason` `direct_red_card`; se cierra el acta siguiente del mismo jugador → **0** filas nuevas y la existente **no** cambia (motivo, duración y estado) | RF-005, RF-006, R-3 |
| **Unicidad por evento de roja, aparte del motivo**: evento de roja preexistente con una sanción; el acta lo reutiliza y sus amarillas cruzan un umbral → **0** filas nuevas | RF-005, RF-012 |
| **Recuento auditado**: tras el cierre, `payload->>'suspensions'` en `administrative_audit_logs` **es** el `count(*)` de `player_suspensions` con `origin_match_id` del partido, y **no** el tamaño de la lista derivada (caso de absorción: 1, no 2; caso de roja ya sancionada: 0) | RF-012, RNF-008 |
| **Aislamiento**: `_load_discipline_history` con el contexto de **otra** organización devuelve `[]`; y cerrar con datos de otra organización no altera el número ni el motivo de las sanciones | RF-014, RNF-001 |
| **Reinicio de fase**: con `clear_yellows_on_stage_change` activo, dos amarillas del mismo jugador en otra fase del torneo no cuentan para el umbral; con él desactivado, sí (dos partidos, `stage_id` distinto en el mismo torneo y versión) | RF-008 |
| Roja **directa** + umbral en el mismo cierre → **2** filas (acumulación con su duración y expulsión con la suya) | RF-009 |
| Acta con tres amarillas previas y roja doble amarilla → **409** `DOUBLE_YELLOW_INCONSISTENT`, **0** filas (regresión de la 017) | RF-013 |

### 12.3 Regresión (sin cambios de comportamiento esperados)

| Archivo | Qué se comprueba |
|---|---|
| `backend/tests/test_rules_engine.py` | La sanción por umbral y la de roja siguen creándose cuando la jugada **no** coincide. |
| `backend/tests/test_double_yellow.py` | La doble amarilla válida cierra con **1** sanción (hoy ya lo espera); el 409 y la escritura cero siguen igual. |
| `backend/tests/test_close_validation_order.py` | El orden de 14 pasos no cambia con el doble actualizado. |
| `backend/tests/test_match_resolution_db.py`, `test_walkover_close.py`, `test_match_assists_db.py`, `test_substitutions.py` | Sin migración, sin cambio de contrato ni de outbox: deben seguir verdes sin tocarlos (walkover con `suspensions: 0`). |

### 12.4 Frontend y extremo a extremo

| Comprobación | Qué cubre |
|---|---|
| `docker compose exec -T web pnpm test`, `… pnpm run typecheck`, `… pnpm run build` | Que **no** hay cambio de frontend y nada se rompe (RF-015). |
| `pnpm run e2e:test` (**obligatorio**, RNF-006) | La ruta de cierre que recorre `operation-flow` (31 hitos, incluido `report-closed`) y las tres vistas del reintento. Veredicto **0**; **1** comportamiento, **2** infraestructura y **3** corrida inválida no se declaran verdes. |

El arnés se ejecuta **en exclusiva** (sin `dev` ni `build` concurrentes, comparten `.nuxt`) y tras limpiar residuos de «Copa E2E»:

```sh
docker compose up -d --wait
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "DELETE FROM tournaments WHERE name LIKE 'Copa E2E%';"
docker compose exec -T api python -m scripts.seed_demo
cd frontend && pnpm run e2e:test
```

## 13. Trazabilidad RF → implementación y prueba

| RF | Implementación | Prueba |
|---|---|---|
| RF-001 (una sanción por jugada) | `evaluate_suspensions` (absorción) | `test_sanctions.py` (puro) + `test_sanctions_db.py` (`limit` 3 con historial) |
| RF-002 (absorción de todos los umbrales del acta) | absorción al final del recorrido, por jugador del acta | `test_sanctions.py` (primera/última amarilla, dos umbrales, umbral histórico) |
| RF-003 (duración única de expulsión) | `red_days = direct_red_suspension_matches`, una sola fila | `test_sanctions.py` + `test_sanctions_db.py` (duración 2 vs 4 y partidos cumplidos) |
| RF-004 (todas las amarillas cuentan, orden estable) | contador que no se reinicia; `discipline_history_order_key` | `test_sanctions.py` (permutación del historial, clave total) |
| RF-005 (solo el acta origina; unicidad por roja) | separación en `evaluate_suspensions`; lectura acotada + `drop_recorded_red_sanctions` | `test_sanctions.py` + `test_sanctions_db.py` (no origen, roja histórica, evento reutilizado) |
| RF-006 (nada se reescribe) | no hay `UPDATE`/`DELETE` de `player_suspensions` | `test_sanctions_db.py` (fila histórica intacta) |
| RF-007 (regla fija, sin clave nueva) | uso de las claves existentes; sin `RULES_SCHEMA` nuevo | `test_rule_contract.py` y `test_rules_engine.py` (esquema sin cambios) |
| RF-008 (reinicio de fase primero) | `WHERE` de `_load_discipline_history` sin cambios | `test_sanctions_db.py` (historial de otra fase con reinicio activo no cuenta) |
| RF-009 (roja directa + umbral = dos) | absorción solo para `double_yellow_red` | `test_sanctions.py` + `test_sanctions_db.py` (2 filas) |
| RF-010 (tipo de roja del mismo cierre) | `metadata` en el `RETURNING` del `INSERT` | `test_sanctions_db.py` (reason en el cierre que la registra) |
| RF-011 (elegibilidad y partidos cumplidos) | misma fila, misma `_serve_suspensions` | `test_sanctions_db.py` (tercer partido sin convocar → `served`) |
| RF-012 (trazabilidad y recuento real) | `source_event_id` intacto; `created` en la auditoría | `test_sanctions_db.py` (auditoría vs `count(*)`) |
| RF-013 (cierre y vecinos intactos) | no se toca el orden, ni el paso 10, ni el walkover | `test_close_validation_order.py`, `test_double_yellow.py`, `test_walkover_close.py`, suite completa |
| RF-014 (aislamiento) | `organization_id` en las dos consultas | `test_sanctions_db.py` (historial bajo otro contexto) |
| RF-015 (sin superficie nueva) | sin ruta, campo ni pantalla | `git grep` en frontend + `pnpm test/typecheck/build` + E2E |
| RNF-005 (sin migración) | cálculo puro | `git diff infra/postgres/migrations` vacío; esquema 027 |
| RNF-009 (outbox intacto) | sin eventos nuevos; la emisión de los tres eventos del cierre no se toca | `git diff backend/app/modules/matches/service.py` **no** cambia la emisión de `MATCH_CLOSED`, `MATCH_UPDATED` ni `STANDINGS_UPDATED`, y las pruebas de cierre existentes siguen verdes; los tres tipos en un cierre normal los fija `test_match_assists_db.py::test_the_assist_never_changes_result_standings_sanctions_or_outbox` |
| RNF-010 (consultas fijas) | 1 lectura acotada a las rojas del acta | revisión del número de `execute` en `test_close_validation_order.py` (doble) |

## 14. Riesgos

| # | Riesgo | Declarado en | Mitigación |
|---|---|---|---|
| R1 | Es un **cambio de comportamiento** del recuento visible (el jugador cumple menos partidos) y del origen de las sanciones. | RNF-004 (a), (c) | Se documenta en `AGENTS.md` y `README.md`; solo hacia delante y sin reescritura de filas. |
| R2 | El recuento auditado **puede bajar** y la auditoría no es comparable con la histórica. | RNF-004 (d), R-5 | Se documenta; la clave `suspensions` mantiene el nombre. |
| R3 | Un acta **incluida** en el historial de otra ya no produce la fila que la versión anterior habría producido. | RF-005 | Pruebas de no origen y de etiqueta heredada; sin retroactividad. |
| R4 | Si algún día se permitiera una amarilla **posterior** a la roja del mismo jugador, la absorción por jugador sería más amplia que «las amarillas que componen la expulsión». | (invariante 017) | El paso 8 lo rechaza hoy y hay prueba; se anota en `AGENTS.md` junto a la regla. |
| R5 | El `metadata` del `RETURNING` debe llegar como objeto (no como texto) para que la clasificación funcione. | RF-010 | La prueba con base lee el `reason` de la tabla en el mismo cierre; si llegara como texto, esa prueba se pone roja. |
| R6 | Cualquier asunción de orden en el acta (índice del payload) depende de que `_persist_events` preserve el orden de la petición. | RF-004, RNF-003 | Es el orden actual (append en el bucle de `dto.events`) y la prueba pura fija el contrato de la función. |

**Riesgos aceptados que esta spec no elimina** (declarados en ella): una sanción histórica del período anterior conserva su motivo heredado (RF-006); no hay vía de corrección ni de anulación; las actas cerradas no se revalidan; el walkover sigue sin generar ni servir sanciones.

## 15. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 RLS lo garantiza la base | Sí | Sin tabla nueva; las dos consultas nuevas corren dentro de la transacción del cierre con `organization_id` explícito y RLS activo (`test_sanctions_db.py`, aislamiento). |
| §2.2 La aplicación no se salta RLS | Sí | Sin cambios de rol, grants ni `BYPASSRLS`. |
| §2.3 Lo publicado es inmutable | Sí | No se reescribe ninguna sanción ni acta cerrada; RF-006 cubierto por prueba y por la ausencia de `UPDATE`/`DELETE` sobre `player_suspensions`. |
| §2.4 Historial de esquema *append-only* | Sí | **Sin migración**: no se añade ni se edita ninguna; el esquema sigue en 027. |
| §2.5 Lo público es una proyección mínima | Sí | Sin campos públicos nuevos; solo identificadores de jugador; fotos con consentimiento, sin cambios. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Sin variables ni secretos nuevos. |
| §2.7 Administración global separada y auditada | Sí | `/admin` no se toca; no se añaden acciones auditadas (se conserva `CLOSE_MATCH_REPORT`). |
| §2.8 Nada se termina sin verificación | Sí | Cada tarea declara «Hecho cuando» con comandos reales; la última incluye backend sin base y con base, frontend, `typecheck`, `build`, E2E e infra, y declara **no ejecutado** lo que no corra. |
| §2.9 El código de desarrollo no llega a producción | Sí | No se toca el seed; las pruebas con base son opt-in. |
| **§3.2 Backend — reglas deportivas configurables como JSON** | **Sí, con la excepción de §5.1 ya declarada y aprobada en la spec** | La absorción de la acumulación de la misma jugada y la unicidad por evento de roja quedan **fijas en el motor**, sin clave nueva. Los cuatro elementos de §5.1 están en `spec.md` → «Excepción declarada a §3.2»: justificación escrita (corrección de coherencia con precedente en la 017), alcance acotado (solo la jugada de doble amarilla y la unicidad por roja; no toca roja directa, duraciones, umbrales ni ninguna otra configuración), responsable (propietario del producto) y aprobación de un revisor distinto del autor (@reviewer, 2026-10-25). **No** hay enmienda de la constitución. |
| §3.2 Backend — módulo y router | Sí | Módulos existentes; sin router ni registro nuevo en `main.py`. |
| §3.2 Backend — acceso asíncrono | Sí | Sin consultas nuevas síncronas. |
| §3.2 Backend — efectos por outbox | Sí | La sanción es efecto del cierre en la misma transacción (comportamiento actual, no se cambia); el outbox conserva sus tres eventos. |
| §4 Todos: CI correspondiente (`backend`, `frontend`, `infrastructure`, `security`, `e2e`) | Sí | El cambio pasa los cinco; el `e2e` de CI y la corrida local cubren `operation-flow`, que recorre el cierre. |
| §4 Todos: sin secretos ni datos personales | Sí | Solo identificadores en pruebas; ningún mensaje nuevo. |
| §4 Todos: documentación afectada | Sí | `AGENTS.md` y `README.md` en T6; `docs/contrato-reglas.md` **no** cambia (comprobado con `git diff`). |
| §4 Todos: pruebas del comportamiento nuevo | Sí | Dos archivos nuevos (puro y con base) y el doble del orden actualizado; cada RF de la tabla 13 con su prueba. |
| §4 Base de datos: nueva migración numerada | No aplica | Sin cambio de esquema (§7). |
| §4 Base de datos: RLS y políticas en tablas nuevas | No aplica | No hay tablas nuevas. |
| §4 Base de datos: volumen limpio y migrado / `sh -n migrate.sh` | No aplica | Sin migración; `migrate.sh` no se toca. |
| §4 API: consultas tenant con `set_rls_context()` | Sí | Las dos lecturas nuevas viven en la transacción del cierre, que ya lo fija antes de cualquier consulta. |
| §4 API: endpoints públicos sin campos sensibles | Sí | No cambian. |
| §4 API: router nuevo registrado en `main.py` | No aplica | Sin rutas nuevas. |
| §4 API: `pytest -q` y `compileall` | Sí | T1–T5 y la verificación final. |
| §4 Frontend: llamadas por `useApi.ts` | Sí | No hay llamadas nuevas; no se toca el cliente. |
| §4 Frontend: `pnpm test`, `typecheck`, `build` | Sí | T8 (dentro del contenedor `web`), sin cambios en el árbol. |
| §4 Infraestructura: `docker compose config -q` | No aplica | Sin cambios de compose; se ejecuta igualmente en la verificación final. |
| §4 Dependencias: lockfiles y auditorías | No aplica | Sin dependencias nuevas. |
| §5.1 Excepción válida | Sí | La única excepción es la de §3.2, con sus cuatro elementos; no se invoca ninguna otra. |
| §6 (definición de cumplimiento), punto 5 | Sí | El cambio lo revisa una persona distinta del autor antes de fusionar (fuera del alcance de este plan). |
