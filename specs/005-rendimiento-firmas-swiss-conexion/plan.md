# Plan 005 — Rendimiento: firmas de fotos en lote, Swiss acotado y timeouts de conexión

Estado: implementada, validada por @reviewer (APROBADA, 2026-10-20) y cerrada (2026-10-20, commits `37019e7` y `8b5eae0`); §6 aprobada por el usuario (2026-10-21). Checklist de T010 completo.

Spec: `specs/005-rendimiento-firmas-swiss-conexion/spec.md` (aprobada 2026-10-20)

## 1. Resumen técnico

El cambio se divide en tres bloques de backend, documentación y verificación final:

- **R15 — fotos:** un cliente de firma cacheado por proceso y endpoint de firma, una firma por clave distinta y un solo despacho off-thread por respuesta; firma, subida y borrado ocurren **fuera** de la transacción. En importación las fotos se suben antes de la escritura y se compensan solo si el fallo es anterior al commit; en la subida individual, lectura → `put_bytes` → escritura → commit confirmado → borrado del anterior → firma. El fallo de firma degrada a `null` en público y mantiene 503 en Workspace.
- **R16 — Swiss:** tope de 64 equipos, un contador único de evaluaciones de pares (40 000 búsqueda + 10 000 reserva de fallback = 50 000), fallback greedy estricto, ejecución en un ejecutor dedicado de 2 hilos con timeout de 10 s y errores 409 distinguibles. El cálculo ocurre fuera de la transacción y la escritura se hace en una transacción posterior que revalida el permiso y el estado y vuelve a fijar RLS.
- **R17 — conexión:** `statement_timeout` de 15 s, `idle_in_transaction_session_timeout` de 30 s, pool 10 + 10 con espera de 10 s como constantes; agotamiento del pool (`sqlalchemy.exc.TimeoutError`) → 503 con un aviso por petición; valores efectivos registrados al arrancar.

No hay migraciones, cambios de esquema, dependencias nuevas, configuración nueva, cambios de Compose, de `.env.example` ni de frontend. Los endpoints conservan ruta, método y campos; solo aparecen los códigos 422/409/503 y la degradación de foto ya aprobados.

## 2. Estado de partida y supuestos

- **R15:** `ObjectStorage` es un singleton por proceso (`@lru_cache` en `get_object_storage`), pero `_client()` construye un `boto3.client` por llamada (`backend/app/core/storage.py:33-49`) y `signed_url()` firma una clave por llamada dentro de un `to_thread` (`storage.py:115-128`). La resolución de fotos se hace fila a fila en `_resolve_roster_photo_urls` (`router.py:1272-1278`), invocada desde la plantilla del Workspace (`router.py:1340`) y, en público, dentro del bucle de alineaciones (`router.py:3142`). `_load_roster_player` (`router.py:1281-1297`) firma y se llama **dentro** de `db.begin()` en alta, importación, subida de foto y cambio de consentimiento (`router.py:1359,1429,1498,1548`).
- **R15 — frontera:** el endpoint público usa `Depends(get_db)` sin transacción explícita; la sesión mantiene la transacción implícita abierta mientras firma. La plantilla del Workspace firma después del bloque `db.begin()` de la lista (`router.py:1309-1340`), pero no en los demás call sites.
- **R16:** `build_swiss_pairings` (`scheduling.py:200-314`) usa `pair_remaining` (`:269-290`) sin contador; se invoca por cada candidato a descanso (`:304-308`) y corre en el event loop dentro de la transacción del request (`router.py:2417-2487`, `db.begin()` en `:2428`). `_draw_swiss_schedule` (`:2198-2414`) hace lecturas y escrituras; `_clear_stage_schedule` (`:1558+`) se ejecuta antes del sorteo (`:2478-2485`). Un `ValueError` de sorteo imposible (`scheduling.py:314`) no tiene manejador y produce 500.
- **R17:** `engine = create_async_engine(settings.database_url, pool_pre_ping=True)` (`database.py:12`) usa los defaults 5 + 10 y 30 s de espera, sin timeouts de servidor. El engine lo comparten API, worker (`workers/outbox.py:10,56`) y seed (`scripts/seed_demo.py:22`). El único manejador de BD es `DBAPIError` → 500 (`main.py:579-591`); el agotamiento del pool no es `DBAPIError`. En producción la API usa `--workers ${API_WORKERS:-2}` (`docker-compose.production.yml:46`).
- **Solapamiento con la spec 004:** en este checkout la spec 004 está **commiteada** (`3b6210f`), así que `backend/app/main.py`, `backend/tests/test_hardening.py`, `README.md`, `AGENTS.md` y `MEMORY.md` ya contienen sus cambios en el historial. Si al implementar 005 la 004 siguiera **sin commit**, el cambio de 005 en `main.py` se limita a dos hunks (el registro del manejador de agotamiento y la llamada al registro de configuración en `lifespan`), no se toca el relay, `RESYNC`, `parse_envelope` ni `emit_domain_event`, en `test_hardening.py` solo se toca la sección de storage y en los documentos se conservan las secciones de 004. En ese caso, se commitea 004 primero o se separan los hunks con `git add -p`.
- **Pruebas:** la suite actual usa `ASGITransport(app=api)` sin lifespan y `dependency_overrides` con dobles de sesión (`backend/tests/test_api_access.py:11-146`); la suite con PostgreSQL es opt-in (`backend/tests/conftest.py:42-60`). Los dobles de S3 ya existen en `backend/tests/test_hardening.py:138-183`.
- **Versiones de referencia:** Python 3.14, SQLAlchemy 2.1.4, asyncpg 0.32.0 y boto3 1.43.113. No se cambian.
- **Alcance de N-2:** firma de fotos, **subida (`put_bytes`)** y **borrado (`delete_key`)** de objetos, y emparejamiento Swiss. Ninguna de esas operaciones ocurre dentro de una transacción. En la importación las fotos se suben **antes** de la escritura y se compensan solo si el fallo es inequívocamente anterior al commit; un commit fallido o ambiguo puede dejar objetos huérfanos (best-effort). En la subida individual el orden es lectura → `put_bytes` fuera → escritura → **commit confirmado** → borrado del objeto anterior → firma; si el commit falla o se cancela, se conservan ambos y el nuevo puede quedar huérfano; si el fallo es anterior al commit, se compensa el nuevo. Un fallo de firma posterior al commit no borra el objeto nuevo ni revierte filas.

## 3. Archivos y responsabilidades

| Archivo | Responsabilidad | RF |
|---|---|---|
| `backend/app/core/storage.py` | Cliente de firma cacheado por endpoint con bloqueo de hilo; `SignedUrls` y `signed_urls(keys)` en un solo `to_thread`; `signed_url` delega y conserva su contrato de error. `put_bytes`/`delete_key` conservan su implementación; sus **call sites** los mueven fuera de la transacción. | RF-001, RF-002 |
| `backend/app/modules/tournaments/photos.py` (nuevo) | Resolución de fotos por política: agrupa claves, llama una vez a `signed_urls`, aplica `null` (público) o HTTP 503 (Workspace), registra una sola entrada por respuesta sin claves. | RF-002, RF-003, RF-004 |
| `backend/app/modules/tournaments/router.py` | Sustituye `_resolve_photo_url`/`_resolve_roster_photo_urls` por el resolvedor; separa `_load_roster_player` en lectura y presentación; cierra la transacción antes de firmar, subir o borrar en público y Workspace. En el sorteo: tope, split lectura/escritura, llamada al runner, revalidación de permiso y estado. | RF-002 a RF-006 |
| `backend/app/modules/tournaments/scheduling.py` | Constantes del Swiss; `PairingBudget`; búsqueda con contador; fallback greedy con `candidate_key`; `SwissPairingFailure`/`SwissPairingTimeout`; `run_swiss_pairing` async con ejecutor dedicado. | RF-005, RF-006 |
| `backend/app/core/database.py` | Constantes de timeouts y pool; `engine_options()`; engine con `connect_args` y pool explícitos; `log_database_configuration()`. | RF-008, RF-009 |
| `backend/app/main.py` | Registro de `sqlalchemy.exc.TimeoutError` → 503 y llamada a `log_database_configuration()` en `lifespan`. Solo esos hunks. | RF-009 |
| `backend/tests/test_storage_signing.py` (nuevo) | Caché, concurrencia en frío, dos endpoints, lote, deduplicación y claves inválidas. | RF-001, RF-010 |
| `backend/tests/test_photo_resolution.py` (nuevo) | Políticas público/Workspace, orden y valores, una sola entrada de registro, frontera de transacción con doble de sesión, subida/borrado y compensación. | RF-002, RF-003, RF-004, RF-010 |
| `backend/tests/test_swiss_budget.py` (nuevo) | Contador, fronteras 40 000/50 000, determinismo, fallback con `candidate_key`, timeout con registro de error y progreso del event loop. | RF-005, RF-006, RF-010 |
| `backend/tests/test_swiss_transaction.py` (nuevo) | Split lectura/escritura, revalidación de permiso (403) y estado (409), H7 documentado y ausencia de escrituras (dobles y opt-in). | RF-005, RF-006, RF-010 |
| `backend/tests/test_database_config.py` (nuevo) | `engine_options`, pool efectivo, 503 con un aviso, sin aviso en éxito, registro de arranque. | RF-008, RF-009, RF-010 |
| `backend/tests/test_database_timeouts.py` (nuevo, opt-in) | `SHOW` de ambos timeouts y frontera de transacción con sesión real. | RF-008, RF-010 |
| `backend/tests/test_hardening.py` | Adaptar la prueba de firma única al nuevo constructor cacheado; conservar la de traversal. | RF-001, RF-010 |
| `backend/tests/test_tournament_scheduling.py` | Adaptar las llamadas a `build_swiss_pairings` si cambia la firma; conservar 36 equipos y descanso. | RF-005, RF-010 |
| `README.md`, `AGENTS.md` | Códigos, degradación de fotos, timeouts, pool, agregado de conexiones y reinicio por credenciales. | RF-011 |
| `MEMORY.md` | Cierre de la spec con evidencia (al final). | RF-011 |

No se tocan `backend/app/core/config.py`, `infra/postgres/`, `docker-compose*.yml`, `.env.example`, `.github/workflows/ci.yml`, `backend/requirements.txt` ni el frontend.

## 4. Diseño R15 — firma de fotos

### 4.1 Cliente de firma cacheado y lote (RF-001, RF-002)

`ObjectStorage` conserva `_client()` para subida/borrado y añade:

```text
SignedUrls:
    urls: dict[str, str]        # clave -> URL
    failed: tuple[str, ...]     # claves no firmadas (incluidas las inválidas)
    reason: str | None          # "build_failed" | "sign_failed" | None

_clients: dict[str, object]     # endpoint de firma -> cliente
_clients_lock: threading.Lock

_build_client(endpoint) -> client          # cuerpo actual de _client(endpoint)
_get_or_build(endpoint) -> client          # con _clients_lock y doble comprobación
_sign_many(endpoint, keys, ttl) -> SignedUrls   # síncrono; se ejecuta en un hilo
async signed_urls(keys, expires_seconds=None) -> SignedUrls
async signed_url(keys, expires_seconds=None) -> str        # delega y lanza StorageError si falla
```

Reglas:

- La clave de caché es el **endpoint de firma efectivo** (`_signing_endpoint_url()`): `STORAGE_SIGNING_ENDPOINT_URL` → host de `STORAGE_PUBLIC_BASE_URL` → `STORAGE_ENDPOINT_URL`. El endpoint de subida no se usa como clave.
- `signed_urls` deduplica claves conservando el orden, valida cada clave (no vacía, no absoluta, sin `..`) y llama a `_sign_many` **una vez** con las válidas. Con cero claves válidas no construye cliente ni despacha hilo.
- `_sign_many` obtiene/construye el cliente dentro de `_clients_lock` y firma cada clave; un fallo de construcción marca todas como fallidas (`reason="build_failed"`); un fallo de una clave la marca fallida sin afectar a las demás (`reason="sign_failed"`). No registra nada: el registro es responsabilidad del resolvedor, para cumplir «una entrada por respuesta».
- `signed_url` conserva el contrato actual: valida la clave, firma una y lanza `StorageError` si falla. Es la vía que usan los tests existentes y cualquier llamador singular.
- El cliente cacheado conserva las credenciales resueltas al construirse. Rotarlas exige reiniciar el proceso (se documenta en RF-011).

Alternativa descartada: cachear el cliente con `lru_cache` sobre el endpoint. No permite invalidar ni reintentar tras un fallo de construcción y mezcla la memoización con el estado del proceso; un diccionario con bloqueo es explícito y testeable.

### 4.2 Política de presentación y frontera de transacción (RF-002 a RF-004)

`backend/app/modules/tournaments/photos.py` expone una sola función:

```text
async sign_photo_rows(rows, *, key_field, consent_field, policy, logger, storage=None):
    # storage inyectable (por defecto get_object_storage()) para pruebas
    # 1. recolecta (fila, clave) con consentimiento; consent_field=None significa
    #    que la presencia de la clave ya implica consentimiento (vista pública)
    # 2. keys = claves válidas distintas
    # 3. result = await (storage or get_object_storage()).signed_urls(keys)   # un despacho
    # 4. por fila: row[key_field] = result.urls.get(key)  (None si no hay clave)
    # 5. si result.failed:
    #       logger.warning("No se pudieron firmar %d fotos (%s)", len(failed), reason)
    #       if policy == "error": raise HTTPException(503, "El almacenamiento de fotos no está disponible")
    # 6. devuelve rows
```

- `policy="null"` en el endpoint público: la respuesta se sirve completa, con `photo_url: null` en las afectadas y 200.
- `policy="error"` en Workspace: 503 con el mensaje actual, sin datos internos.
- La función no abre transacciones ni consulta la base. Recibe filas ya leídas y **elimina el campo de la clave** (`pop`) antes de devolver, para que no se serialice por accidente; el valor firmado queda en el campo de presentación.
- **Importación (N-2):** primero se suben las fotos con `put_bytes` fuera de la transacción; después se abre la transacción de escritura con las filas y sus claves. SI el fallo es inequívocamente anterior al commit (subida posterior, validación, permiso o escritura), ENTONCES se compensan los objetos subidos con `delete_key` y se revierte la transacción. SI el commit falla o es ambiguo, ENTONCES no se compensan y pueden quedar objetos huérfanos (best-effort, sin filas confirmadas). Un fallo de firma **posterior** al commit no borra el objeto nuevo ni revierte la fila: la respuesta es 503 y el cliente debe releer.
- **Subida individual (N-2):** lectura de consentimiento y clave anterior en la transacción → cierre → `put_bytes` fuera → transacción de escritura con la nueva clave → **commit confirmado** → borrado del objeto anterior → firma. SI el commit falla o se cancela (ambiguo), ENTONCES se conservan el anterior y el nuevo; el nuevo puede quedar huérfano y no se compensa. SI el fallo es inequívocamente anterior al commit (validación, permiso, escritura) y el objeto nuevo ya se subió, ENTONCES se compensa el objeto nuevo. El borrado del anterior no depende del éxito de la firma; una cancelación durante ese borrado se propaga y no se silencia.
- **Retirada de consentimiento:** el borrado del objeto ocurre fuera de la transacción, tras un commit confirmado; no se firma una foto sin consentimiento.
- El registro es una sola entrada por respuesta, con el número de fallos y el motivo; nunca claves, nombres, documentos ni fechas.

Orden obligatorio en cada endpoint con fotos (N-2):

```text
async with db.begin():            # o transacción implícita explícitamente cerrada
    set_rls_context(...)          # solo en Workspace
    ...consultas...
# commit/cierre de la transacción
rows = await sign_photo_rows(...) # fuera de la transacción
return rows
```

- **Público:** `public_matches` envuelve sus lecturas en una transacción explícita y la cierra antes de firmar. No se añade `set_rls_context` porque las vistas públicas son `security_barrier` y el camino es anónimo; no se cambia el modelo de acceso.
- **Workspace:** la lista ya firmaba fuera de `db.begin()`; se cambia al resolvedor por lote. Alta, importación, subida de foto y consentimiento pasan a leer la fila dentro de la transacción y a firmar después de salir.

### 4.3 Call sites (RF-001 a RF-004)

| Endpoint / función | Hoy | Cambio |
|---|---|---|
| `public_matches` (`router.py:3068-3155`) | firma por fila dentro del bucle, con la transacción implícita abierta | construye las alineaciones con la clave, cierra la transacción, firma en lote con `policy="null"` y rellena `photo_url` |
| `list_tournament_rosters` (`:1300-1340`) | firma por fila después de `db.begin()` | resuelve en lote con `policy="error"` |
| `_load_roster_player` (`:1281-1297`) | consulta + firma | se divide en `_load_roster_player_row` (consulta, dentro de la transacción) y presentación con `sign_photo_rows` (fuera) |
| `create_roster_player` (`:1343-1359`) | firma dentro de `db.begin()` | lee la fila dentro, firma después |
| `create_roster_players_bulk` (`:1362-1438`) | N consultas + N firmas + subidas dentro de `db.begin()` | sube las fotos antes de la escritura; lee las filas dentro (una consulta por `id = ANY`); si el fallo es anterior al commit, compensa con `delete_key`; si el commit falla o es ambiguo, puede dejar huérfanos (best-effort); firma en lote después del commit |
| `upload_roster_player_photo` (`:1441-1509`) | firma y `put_bytes` dentro de `db.begin()` | lectura → `put_bytes` fuera → escritura → commit confirmado → borrado del anterior → firma; commit fallido/ambiguo conserva ambos y puede dejar el nuevo huérfano; fallo anterior al commit compensa el nuevo; la cancelación del borrado del anterior se propaga |
| `update_roster_photo_consent` (`:1515-1555`) | firma dentro de `db.begin()` | lee dentro, firma fuera; el borrado del objeto sigue tras un commit confirmado |

`_resolve_photo_url` se retira una vez migrados todos los call sites. No se cambian campos, nombres ni el orden de las claves de respuesta.

Alternativa descartada: mantener `_resolve_photo_url` y añadir un `lru_cache` de URLs firmadas. Caducaría mal (el TTL es de 300 s) y no arregla la frontera de transacción ni el despacho por fila.

## 5. Diseño R16 — Swiss

### 5.1 Constantes y contador único (RF-005)

En `scheduling.py`:

```text
MAX_SWISS_TEAMS = 64
SWISS_SEARCH_LIMIT = 40_000
SWISS_PAIRING_LIMIT = 50_000
SWISS_FALLBACK_RESERVE = SWISS_PAIRING_LIMIT - SWISS_SEARCH_LIMIT   # 10_000
SWISS_PAIRING_TIMEOUT_SECONDS = 10.0
SWISS_PAIRING_MAX_WORKERS = 2

PairingBudget:
    search_limit = SWISS_SEARCH_LIMIT
    total_limit = SWISS_PAIRING_LIMIT
    evaluations = 0

    take(limit) -> bool:
        if evaluations >= limit: return False
        evaluations += 1
        return True
```

- `take` se llama **exactamente una vez por par candidato examinado**, antes de comprobar si repite rival o si admite la orientación. La evaluación que alcanza el límite se realiza; la siguiente se rechaza.
- No incrementan: la ordenación de candidatos, la comparación de puntuaciones, la elección de descanso, la validación de parámetros ni las opciones de orientación de un par ya contado.
- El presupuesto se crea una vez por solicitud y se pasa por referencia a la búsqueda, a todos los candidatos a descanso y al fallback. Nunca se reinicia.
- Los límites son inyectables en pruebas (`PairingBudget(search_limit=…, total_limit=…)`); en producción se usan las constantes.

### 5.2 Búsqueda y fallback (RF-005, RF-006)

```text
build_swiss_pairings(team_ids, ..., budget=None) -> tuple[SwissPairing, ...]
    budget = budget or PairingBudget()
    si impar:
        para cada bye candidato en orden:
            intentar search(rest, budget)
            si hay solución: devolver
            si se alcanzó el límite de búsqueda: romper y pasar a fallback
            si no hay solución y no se alcanzó el límite: siguiente candidato
        si se agotaron los candidatos sin límite: no_valid_pairing
    si par: intentar search(todos, budget); si se alcanzó el límite: fallback

search(remaining, budget):
    si vacío: []
    first = remaining[0]
    para second en candidatos ordenados:
        si not budget.take(SWISS_SEARCH_LIMIT): raise SearchLimitReached
        si repite rival: continuar
        para orientación admisible:
            recursión...
    None

fallback(ordered, budget):
    # greedy sin retroceso; usa candidate_key, el mismo orden que la búsqueda
    mientras queden equipos (con descanso si es impar):
        elegir el primer candidato admisible por candidate_key consumiendo budget.take(SWISS_PAIRING_LIMIT)
        si no hay candidato admisible: devolver None
    devolver parejas

resultado:
    si search completó sin alcanzar el límite y sin solución: raise SwissPairingFailure("no_valid_pairing")
    si search alcanzó el límite y el fallback no completa (incluido llegar a 50 000): raise SwissPairingFailure("budget_exhausted")
```

- El fallback solo se ejecuta cuando la búsqueda se corta por el límite de 40 000 (una búsqueda completa sin solución ya es concluyente). Consume desde el valor actual del contador y se detiene en 50 000.
- **Clasificación (H1):** `no_valid_pairing` **solo** si la búsqueda terminó sin alcanzar sus 40 000 y sin solución. Si la búsqueda alcanzó 40 000 y el fallback falla —aunque no llegue a 50 000—, el resultado es `budget_exhausted`.
- El fallback usa `candidate_key` (puntuación, victorias, ranking, orden por semilla, `str(team_id)`), el mismo orden de prioridad que la búsqueda (H9).
- `SwissPairingFailure` lleva `reason` y `evaluations`; `ValueError` sigue reservado a la validación (equipos insuficientes o repetidos, semilla negativa, ronda no positiva, metas inválidas) y no se convierte.
- El orden de candidatos conserva `score_key` (puntos, victorias, ranking, orden por semilla, `str(team_id)`) y las orientaciones usan `orientation_options`; la salida es idéntica a la actual dentro del presupuesto.

Alternativa descartada: un presupuesto global sin reserva para el fallback. Si la búsqueda consume las 50 000, el fallback nunca corre y el fallback quedaría decorativo; la reserva de 10 000 mantiene un único contador y un fallback útil.

### 5.3 Hilo, timeout y descarte (RF-005, RNF-003)

```text
_executor: ThreadPoolExecutor | None   # perezoso, max_workers=2, nombre "swiss-pairing"

async run_swiss_pairing(..., timeout=SWISS_PAIRING_TIMEOUT_SECONDS):
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_executor(), partial(build_swiss_pairings, ...))
    try:
        return await asyncio.wait_for(future, timeout)
    except (asyncio.TimeoutError, TimeoutError):
        raise SwissPairingTimeout from None
```

- El ejecutor es **dedicado**, no el por defecto: una búsqueda lenta no debe robar un hilo a la firma de fotos. Se crea de forma perezosa y protegida; no se apaga en `lifespan`.
- `wait_for` cubre la espera en cola. Al vencer, la petición responde 409, se registra a nivel **`error`** como anomalía y el resultado se descarta. **Un hilo de Python no se cancela**: sigue hasta que el presupuesto lo detiene (garantía de terminación) y no escribe ni comparte estado.
- Los datos que recibe el hilo son copias inmutables (tupla de equipos, `frozenset` de parejas previas, copias de standings y conteos). El hilo no recibe sesión, conexión ni objetos del event loop.
- `SwissPairingTimeout` es distinto de `SwissPairingFailure`; el router los mapea a mensajes distintos.

Alternativa descartada: `asyncio.to_thread`. Usa el ejecutor por defecto y mezcla el cálculo con la firma de fotos; además no permite acotar el número de cálculos concurrentes.

### 5.4 Router: tope, split y revalidación (RF-005, RF-006)

`draw_stage_schedule` (`router.py:2417-2487`) se divide en un despachador y helpers por tipo de fase:

```text
draw_stage_schedule:
    T1 (lectura):
        set_rls_context
        ensure tournament + permission + stage + team ids
        si tipo != swiss:
            ejecutar el flujo actual dentro de T1 (sin cambios)
            return
        si len(team_ids) > MAX_SWISS_TEAMS: 422 (antes de escribir)
        cargar: rondas configuradas, estado de rondas previas, placeholders,
                historial de parejas, conteos local/visitante, standings, semilla
    # fin de T1 (commit)
    pairings = await run_swiss_pairing(datos_copiados, ...)
        SwissPairingFailure -> 409 (budget_exhausted | no_valid_pairing)
        SwissPairingTimeout -> 409 (timeout)
        ValueError -> se propaga como hoy (validación)
    T2 (escritura):
        set_rls_context
        revalidar permiso de gestión -> si se revocó: 403 y cero escrituras
        revalidar estado: ronda 1 sin partidos (o mismos placeholders si replace),
                   placeholders siguen cancelled, rondas previas siguen terminadas
                   -> si cambió: 409 "el estado de la fase cambió durante el sorteo; vuelve a intentarlo"
        si replace_existing: _clear_stage_schedule aquí (no en T1)
        ronda 1: INSERT de placeholders + UPDATE de parejas
        ronda > 1: UPDATE de los placeholders existentes
    return respuesta con la semilla
```

- El tope se comprueba con el conjunto de `_load_registered_stage_teams` y antes de cualquier escritura.
- `_clear_stage_schedule` se mueve a la transacción de escritura para que un fallo de cálculo no borre nada de forma confirmada.
- El permiso se revalida **después** de `set_rls_context` y **antes** del estado; un permiso revocado responde 403 sin escribir (H3).
- La revalidación de estado usa `FOR UPDATE` sobre los placeholders en T2 (transacción corta) para que dos sorteos concurrentes no se pisen. **H7:** en la ronda 1 no hay filas que bloquear y `bracket_code` no es único; dos sorteos simultáneos en frío podrían duplicar el calendario. Es un riesgo residual aceptado y fuera de alcance (requiere unicidad o un lock de fase).
- Los `ValueError` de validación existentes no se capturan como 409; conservan su comportamiento.

## 6. Diseño R17 — conexión, pool y observabilidad

### 6.1 Engine y timeouts (RF-008, RF-009)

En `database.py`:

```text
DB_STATEMENT_TIMEOUT_MS = 15_000
DB_IDLE_IN_TRANSACTION_TIMEOUT_MS = 30_000
DB_POOL_SIZE = 10
DB_MAX_OVERFLOW = 10
DB_POOL_TIMEOUT_SECONDS = 10

engine_options() -> dict:
    return {
        "pool_size": DB_POOL_SIZE,
        "max_overflow": DB_MAX_OVERFLOW,
        "pool_timeout": DB_POOL_TIMEOUT_SECONDS,
        "connect_args": {"server_settings": {
            "statement_timeout": str(DB_STATEMENT_TIMEOUT_MS),
            "idle_in_transaction_session_timeout": str(DB_IDLE_IN_TRANSACTION_TIMEOUT_MS),
        }},
    }

engine = create_async_engine(settings.database_url, pool_pre_ping=True, **engine_options())
```

- `engine_options` es pura y se prueba sin base de datos; el engine real se inspecciona para el pool.
- Los valores aplican a API, worker y seed porque comparten engine. El backfill `encrypt_birth_dates` usa su propia conexión administrativa (`DATABASE_ADMIN_URL`) y **no hereda** el pool ni los timeouts.
- `log_database_configuration()` registra una vez los cinco valores con un mensaje estable, sin URL, usuario ni credenciales. Se llama en el arranque de la API; el worker comparte las mismas constantes y su pool se documenta, pero no se añade un registro en su proceso para no mezclar este cambio con el arranque del outbox (spec 004).

### 6.2 Agotamiento del pool (RF-009, P-5)

- `sqlalchemy.exc.TimeoutError` (QueuePool, código `3o7r`) **no** es `DBAPIError`; se registra un manejador propio en `main.py` que devuelve **503** con `{"detail": "Servicio temporalmente no disponible"}` y emite **exactamente un** `logger.warning("Pool de conexiones agotado")` por petición fallida. No incluye SQL, parámetros ni nombre de la base.
- El camino de éxito y las peticiones que esperan y obtienen conexión no registran nada.
- El manejador de `DBAPIError` sigue igual: un `statement_timeout` produce el 500 saneado actual con el SQLSTATE.
- Un corte por `idle_in_transaction_session_timeout` produce un `DBAPIError` en la siguiente sentencia: **500 saneado** con el SQLSTATE y conexión descartada del pool. Con N-2 no ocurre en los caminos de fotos ni de emparejamiento; se declara como riesgo residual para caminos no tocados.
- **Solapamiento 004:** solo se añaden el import con alias (`TimeoutError as PoolTimeoutError`), la función del manejador, su registro y la llamada a `log_database_configuration()` en `lifespan`. No se toca el relay ni `RESYNC`.

### 6.3 Agregado de conexiones (RF-009, RF-011)

Por proceso: hasta 20 conexiones (10 + 10). Con `API_WORKERS=2` y un worker: 2 × 20 + 20 = 60, frente a las 100 por defecto de PostgreSQL; 40 de margen para migraciones y administración. Se documenta en `README.md` y `AGENTS.md`; no se cambia P-4 ni Compose.

## 7. Estrategia de pruebas

### 7.1 Unitarias con dobles, overrides y funciones puras

| Caso | RF | Tarea |
|---|---|---|
| Cliente de firma: 0 con caché caliente, 1 en frío, 1 por endpoint de firma, **1 con dos peticiones concurrentes** (constructor falso que bloquea), reintento tras fallo. | RF-001 | T001 |
| Lote: un solo despacho, una firma por clave repetida, N = 0 sin cliente, claves inválidas marcadas. | RF-002 | T001 |
| `signed_url` conserva el error de clave inválida y el TTL de `STORAGE_PRESIGN_SECONDS`. | RF-001, RF-004 | T001 |
| Política: público → `null`; Workspace → 503; una sola entrada de registro; sin claves ni PII. | RF-003, RF-004 | T002 |
| Orden, campos y valores de `photo_url` idénticos a una referencia; deduplicación visible. | RF-002 | T002 |
| Frontera de transacción: doble de sesión registra `in_transaction() == False` al firmar, subir y borrar, en público y Workspace (o en la función de endpoint extraída). | RF-002 | T002, T003 |
| Importación: `put_bytes` antes de la escritura; si el fallo es anterior al commit, compensación con `delete_key`; si el commit falla o es ambiguo, puede dejar huérfanos; un fallo de firma posterior al commit no borra el objeto ni revierte filas. | RF-002, RF-004 | T003 |
| Subida individual: lectura → `put_bytes` fuera → escritura → commit confirmado → borrado del anterior → firma; commit fallido/ambiguo conserva ambos y puede dejar el nuevo huérfano; fallo anterior al commit compensa el nuevo; la cancelación del borrado del anterior se propaga. | RF-002 | T003 |
| Endpoint público con `get_db` sustituido y almacenamiento que lanza: 200 con `null`. | RF-004 | T002 |
| Endpoint de Workspace con `get_db` y `get_auth_context` sustituidos: 503. | RF-004 | T003 |
| Contador: incremento por par, sin reinicio entre ramas/descansos/fallback; fronteras 39 999/40 000/40 001 y 49 999/50 000/50 001. | RF-005 | T004 |
| Determinismo: dos ejecuciones con la misma entrada dan mismas parejas y mismo `evaluations`. | RF-005 | T004 |
| Regresión: 36 equipos y descanso del campo impar idénticos. | RF-005 | T004 |
| Fallback: agotamiento con solución → la encuentra; sin solución → `budget_exhausted`; fallback fallido tras agotar la búsqueda → `budget_exhausted`; búsqueda completa sin solución → `no_valid_pairing`; orden por `candidate_key`; validación intacta. | RF-006 | T004 |
| Timeout: doble que no termina con reloj controlado → `SwissPairingTimeout` y registro de error; resultado descartado. | RF-005 | T004 |
| Event loop: otra corrutina progresa mientras un cálculo lento controlado está en curso. | RF-005 | T004 |
| Router: 64 aceptados, 65 → 422 antes de escribir; pairing failure → 409 con mensajes distintos; `ValueError` intacto. | RF-005, RF-006 | T005 |
| Split y revalidación: sin escrituras en fallo; split en T005; permiso revocado → 403 y estado cambiado → 409 en T006; `_clear_stage_schedule` se mueve a la escritura en T005. | RF-006 | T005, T006 |
| H7: dos sorteos concurrentes en frío pueden duplicar el calendario; la prueba documenta el riesgo aceptado, no lo corrige. | RF-006 | T006 |
| Engine: `engine_options`, pool efectivo, timeouts declarados; `log_database_configuration` con `caplog`. | RF-008, RF-009 | T007 |
| 503: `sqlalchemy.exc.TimeoutError` → 503 con un aviso; éxito sin aviso; `DBAPIError` sigue 500. | RF-009 | T008 |

### 7.2 Opt-in con `RUN_DATABASE_TESTS=1`

| Caso | RF | Tarea |
|---|---|---|
| `SHOW statement_timeout` = `15s` y `SHOW idle_in_transaction_session_timeout` = `30s` sobre una conexión del engine de la aplicación. | RF-008 | T007 |
| Frontera de transacción con sesión real: tras cerrar la lectura y con un firmante falso, `in_transaction()` es falso y `pg_stat_activity` del PID está en `idle`, no `idle in transaction`. | RF-002 | T003 |
| Ningún fallo de emparejamiento deja filas nuevas o modificadas (conteo antes/después, con límites reducidos por monkeypatch). | RF-006 | T006 |
| La transacción de escritura vuelve a fijar RLS: `current_setting('app.current_organization_id')` coincide y la organización B no ve los placeholders de A. | RF-006 | T006 |

### 7.3 Lo que no se cubre y por qué

- **S3/SeaweedFS real y latencia de firma:** la firma es local y el entorno no tiene almacenamiento real; se prueba con dobles que registran argumentos y despachos.
- **Cancelación real del hilo:** Python no la permite; se prueba que el resultado se descarta y que el presupuesto garantiza terminación, no una cancelación inexistente.
- **Agotamiento de pool bajo carga real:** se prueba el manejador y la clasificación con un doble que lanza `TimeoutError`; la contención real no es reproducible en CI.
- **`API_WORKERS=2` en pruebas:** cada proceso construye su cliente; se prueba por proceso y se documenta el agregado.
- **H7 (calendarios duplicados en ronda 1 en frío):** no se reproduce en CI; se declara como riesgo residual aceptado y fuera de alcance.
- **Latencia del seed o de la suite:** no se mide; la decisión de B-13 está documentada.

### 7.4 Comandos y CI

Cada tarea ejecuta y deja en verde:

```sh
cd backend && pytest -q
cd backend && python -m compileall -q app
git -c core.whitespace=cr-at-eol diff --check
```

No aplican `pnpm test`/`typecheck`/`build` (sin frontend) ni `docker compose config -q` (sin cambios de Compose). Los jobs son los de la §4 de la constitución (`backend`, `frontend`, `infrastructure`, `security` y, desde la enmienda 1.4.0, `e2e`); no se añaden pasos nuevos.

## 8. Orden de implementación y cortes verdes

| Tarea | Corte | Contenido | Depende de |
|---|---|---|---|
| T001 | Backend | Cliente de firma cacheado, `signed_urls` y lote; pruebas de storage. | — |
| T002 | Backend | Política de fotos y camino público con frontera de transacción. | T001 |
| T003 | Backend | Caminos del Workspace: lista, alta, importación (subida antes de la escritura y compensación solo si el fallo es anterior al commit), subida y consentimiento fuera de la transacción. | T001, T002 |
| T004 | Backend | Contador, búsqueda, fallback, runner con hilo y timeout; pruebas puras. | — |
| T005 | Backend | Tope, split lectura/escritura, `_clear_stage_schedule` en la escritura y mapeo 409 en el router. | T004 |
| T006 | Backend | Revalidación de permiso (403) y estado, `FOR UPDATE`, 409 de estado cambiado y H7 documentado. | T005 |
| T007 | Backend | Engine con timeouts/pool y registro de arranque. | — |
| T008 | Backend | Manejador 503 del agotamiento con un aviso. | T007 |
| T009 | Docs | README, AGENTS y MEMORY. | T003, T006, T008 |
| T010 | Cierre | Verificación integral y checklist de merge. | T009 |

Cada fila es un commit. T001-T003 y T004-T008 son independientes entre sí; el orden propuesto deja CI verde en cada corte. T005 necesita T004; T006 necesita T005; T008 necesita T007 para que el 503 tenga un pool que lo produzca.

## 9. Verificación de la constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant en la base de datos (RLS) | Sí | Las lecturas de Workspace y el sorteo usan `set_rls_context()` dentro de su transacción; la escritura del sorteo lo vuelve a fijar. El trabajo puro recibe datos ya filtrados. Las vistas públicas no cambian. |
| §2.2 La aplicación no se salta RLS | Sí | No cambia el rol, el engine ni el contexto; los timeouts y el pool no alteran privilegios. |
| §2.3 Lo publicado es inmutable | Sí | El sorteo solo genera en `draft` o en rondas posteriores ya publicadas, con las reglas actuales; no se edita una versión publicada. |
| §2.4 Historial de esquema append-only | Sí | Sin migraciones ni cambios en `infra/postgres/`. |
| §2.5 Lo público es una proyección mínima | Sí | `photo_url` sigue dependiendo del consentimiento; el fallo en público es `null`; no se añaden documentos ni fechas. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Sin variables ni secretos nuevos; el cliente cacheado usa las credenciales ya configuradas y no las registra. |
| §2.7 Administración global separada y auditada | No aplica | No se toca `/admin` ni `platform_admins`. |
| §2.8 Nada se da por terminado sin verificación | Sí | Pruebas unitarias/opt-in, comandos locales y los cinco jobs de CI (incluido `e2e`); lo no ejecutado se declara. |
| §2.9 El código de desarrollo no llega a producción | No aplica | No se tocan seeds ni datos demo; el seed sigue siendo solo de desarrollo. |
| §3.1 Base de datos y multi-tenancy | Sí | Sin tablas ni políticas nuevas; `set_rls_context` en cada transacción tenant. |
| §3.2 Backend asíncrono y reglas configurables | Sí | El acceso sigue siendo asíncrono y el cálculo pesado sale del event loop. Los límites de 64/50 000/10 s son límites de seguridad, no reglas deportivas: puntuación, desempates, disciplina y transferencias siguen en el JSON. Precedentes: `MAX_SINGLE_ELIMINATION_TEAMS = 512` y topes de 64 de grupos/cabezas. No requiere excepción §5.1. |
| §3.3 Frontend y `useApi.ts` | No aplica | Sin cambios de frontend. |
| §3.4 Seguridad y configuración | Sí | Sin variables ni defaults nuevos; todo queda como constantes del backend. |
| §3.5 Infraestructura y CI | Sí | Versiones de referencia y `ci.yml` sin cambios; no se toca Compose, así que `docker compose config -q` no aplica. |
| §4 «Para todos los cambios» | Sí | CI, sin secretos, documentación (RF-011) y pruebas del comportamiento nuevo. |
| §4 «Para cambios de base de datos» | No aplica | Sin cambios de esquema ni migraciones. |
| §4 «Para cambios de API o backend» | Sí | `pytest -q` y `compileall`; endpoints públicos sin campos sensibles; RLS dentro de la transacción; 422/409/503 sin datos internos. |
| §4 «Para cambios de frontend» | No aplica | Sin cambios de frontend. |
| §4 «Para cambios de infraestructura o despliegue» | No aplica | Sin cambios de Compose ni de configuración. |
| §4 «Para cambios de dependencias» | No aplica | Sin dependencias nuevas ni actualizadas. |
| §5.1 Excepciones | No | No se requiere ninguna. |
| §6 Definición de cumplimiento | Sí | Cuatro jobs en verde y revisión humana distinta del autor. |

## 10. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Un hilo no se puede cancelar y sigue tras el timeout | El presupuesto garantiza terminación; el resultado se descarta y el hilo no escribe. Se prueba con un doble y no se apaga el ejecutor en `lifespan`. |
| Saturación del ejecutor de 2 hilos | El timeout cubre la espera en cola; cada cálculo está acotado por el presupuesto. Un timeout no encola trabajo nuevo. |
| Dos peticiones en frío construyen dos clientes | Construcción bajo `threading.Lock` con doble comprobación y prueba de concurrencia. |
| La caché fija credenciales rotadas | Reinicio del proceso documentado en RF-011; no se implementa recarga en caliente. |
| El split de transacciones cambia la semántica del sorteo | Revalidación en T2 con `FOR UPDATE`, pruebas de estado cambiado y de ausencia de escrituras; T006 se puede revertir solo. |
| `_clear_stage_schedule` borra antes de tiempo | Se mueve a la transacción de escritura en T005, después del cálculo; T006 añade la revalidación antes del borrado. |
| El fallo de firma en público enmascara una mala configuración | Un aviso por respuesta con el número de fallos; en Workspace sigue siendo 503 visible. |
| En alta/importación, un fallo de firma ocurre después del commit | La fila queda creada y la respuesta es 503 (P-3/N-2); se documenta que el cliente debe releer y que un reintento ciego puede dar 409. Alternativa descartada: firmar antes del commit, que viola N-2. |
| **H7:** dos sorteos simultáneos en frío (ronda 1) pueden insertar calendarios duplicados | Riesgo residual **aceptado**: `FOR UPDATE` no bloquea filas inexistentes y `bracket_code` no es único. Corregirlo exige unicidad o lock de fase y queda fuera de alcance; se documenta en la spec y en AGENTS. |
| El registro de fotos se multiplica durante una caída de almacenamiento | Una sola entrada por respuesta, sin claves ni PII. |
| El manejador de 503 captura un `TimeoutError` ajeno | Se registra `sqlalchemy.exc.TimeoutError` con alias; una prueba confirma que `DBAPIError` sigue 500. |
| `main.py` arrastra cambios de 004 si esa spec sigue sin commit | En este checkout 004 está commiteada (`3b6210f`). Si no lo estuviera, se commitea primero o se separan los hunks con `git add -p`; el commit de 005 solo incluye el manejador y la llamada al registro. |
| Los 15 s de `statement_timeout` afectan al seed o a la suite opt-in | Decisión B-13: se aceptan y documentan; un fallo se corrige en el seed o la prueba, no elevando la constante. |
| Subidas o borrados con la transacción abierta | Se mueven fuera: importación antes de la escritura con compensación solo si el fallo es anterior al commit; subida lectura → `put_bytes` → escritura → commit confirmado → borrado → firma. Pruebas de frontera en ambos caminos. |
| Commit fallido o ambiguo en una subida o importación | Se conservan el anterior y el nuevo; el nuevo puede quedar huérfano. No se compensa ni se borra el anterior: se prefiere un huérfano a una referencia rota. La cancelación durante el borrado del anterior se propaga. Prueba específica de los tres casos. |
| El fallback cambia resultados en entradas límite | Regresión con 36 equipos, descanso impar y comparación de parejas; la salida dentro del presupuesto debe ser idéntica. |
| Un agotamiento de pool genera una tormenta de avisos | Un aviso por petición fallida; las que esperan y obtienen conexión no registran nada. |

## 11. Reversión y despliegue

- **Un commit por tarea.** `git revert` en orden inverso: T008→T007, T006→T005→T004, T003→T002→T001, T009.
- **Sin migraciones ni datos:** no hay backfill, migración ni ventana de mantenimiento.
- **T007/T008 reversibles por separado:** sin T007, el pool vuelve a los defaults; sin T008, el agotamiento vuelve a un 500 sin clasificar, pero los timeouts siguen.
- **T005/T006 son el corte de mayor riesgo:** revertir T006 restaura la escritura sin revalidación de permiso ni estado; revertir T005 restaura la transacción única y el 500 por sorteo imposible. No hay datos que deshacer porque ningún fallo confirma escrituras.
- **H7 no se corrige en ningún commit:** no hay migración, índice ni lock que revertir; el riesgo aceptado permanece documentado.
- **T001-T003:** revertir T003 deja el camino público ya migrado; revertir T001 exige revertir T002 y T003 (dependencia de API). El orden inverso lo respeta.
- **Despliegue:** sin pasos manuales ni variables nuevas. `API_WORKERS` no cambia. La rotación de credenciales de almacenamiento requiere reinicio, ya documentado.

## 12. Dependencias

**Ninguna nueva.** Se usan `boto3` (ya presente), `asyncio`/`concurrent.futures` de la biblioteca estándar, `SQLAlchemy`/`asyncpg` y `pytest`. Si una prueba exigiera una dependencia nueva, se detiene y se pregunta.

## 13. Cobertura de requisitos

| RF | Tareas |
|---|---|
| RF-001 | T001 (caché y lote), T003 (call sites), T010. |
| RF-002 | T001 (lote), T002 (público y firma), T003 (Workspace, subida y borrado fuera de la transacción), T010. |
| RF-003 | T002 (política pública), T003 (Workspace), T010. |
| RF-004 | T001 (TTL/errores), T002 (público), T003 (Workspace y post-commit), T010. |
| RF-005 | T004 (contador, búsqueda, runner), T005 (tope y split), T010. |
| RF-006 | T004 (fallback y clasificación), T005 (mapeo), T006 (permiso, revalidación y H7 documentado), T010. |
| RF-007 | Todas; T010 verifica el diff. |
| RF-008 | T007 (engine y timeouts), T010. |
| RF-009 | T007 (pool y agregado), T008 (503 y aviso), T009 (documentación), T010. |
| RF-010 | T001-T008 (pruebas por tarea), T010 (comandos y jobs). |
| RF-011 | T009 (README/AGENTS/MEMORY), T010. |

## 14. Contrato e interfaz

- **Sin rutas, métodos ni campos nuevos.** Se mantienen los endpoints públicos y del Workspace.
- **Cambios observables autorizados:**
  - `POST /tournaments/{id}/matches/draw` (Swiss): **422** «La fase Swiss admite como máximo 64 equipos»; **409** «presupuesto de emparejamiento agotado», «no existe un sorteo válido sin repetir rivales», «tiempo máximo de cálculo del sorteo excedido» y «el estado de la fase cambió durante el sorteo; vuelve a intentarlo»; **403** si el permiso de gestión se revoca antes de la escritura.
  - Fotos: en público, `photo_url: null` con 200 si falla la firma; en Workspace, 503 si falla. En alta/importación, un fallo de firma posterior al commit responde 503 sin revertir la fila.
  - Conexión: **503** «Servicio temporalmente no disponible» por agotamiento del pool; el 500 saneado se conserva para `statement_timeout` y `DBAPIError`.
- **Sin cambios de payload exitoso:** mismos campos, mismo orden y mismos valores de `photo_url` cuando la firma funciona.
- **Sin cambios de autorización ni de visibilidad.**

## 15. Decisiones justificadas

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Caché por endpoint de firma con bloqueo de hilo y doble comprobación. | `lru_cache` por endpoint. | Permite reintentar tras un fallo de construcción, no retiene un cliente inválido y es testeable con concurrencia. |
| `signed_urls` devuelve `SignedUrls` con fallos por clave. | Lanzar en el primer fallo. | El público debe conservar el resto de la respuesta; un resultado parcial permite `null` selectivo y un solo registro. |
| Política de fallo en un resolvedor único (`null`/`error`). | Duplicar la lógica en cada endpoint. | Evita divergencias entre público y Workspace y hace verificable el mensaje y el registro. |
| Firma después de cerrar la transacción. | Mantener la firma dentro de la transacción. | Cumple N-2 y evita `idle in transaction`; el coste es un cierre explícito. |
| Presupuesto con reserva de 10 000 para el fallback. | Un único límite de 50 000 sin reserva. | Sin reserva, el fallback nunca corre si la búsqueda agota el total; la reserva mantiene un solo contador y un fallback útil. |
| Ejecutor dedicado de 2 hilos. | `asyncio.to_thread` (ejecutor por defecto). | Aísla el cálculo de la firma de fotos y acota la concurrencia. |
| Timeout de 10 s como red de seguridad. | Confiar solo en el presupuesto. | El presupuesto acota el trabajo, pero no la espera del cliente ante una regresión o una cola saturada. |
| Split lectura/escritura con revalidación de permiso y estado. | Mantener una sola transacción. | N-2 exige no calcular con la transacción abierta; la revalidación evita confirmar sobre un estado o un permiso cambiados. |
| `_clear_stage_schedule` en la escritura. | Borrar antes del cálculo. | Evita que un fallo de cálculo borre de forma confirmada. |
| `TimeoutError` de SQLAlchemy con manejador propio. | Capturar `TimeoutError` integrado o `DBAPIError`. | El agotamiento no es `DBAPIError`; capturar el integrado ocultaría timeouts ajenos. |
| Constantes de 64/50 000/10 s y de 15 s/30 s/10 + 10. | Variables de entorno. | Evita drift de configuración (R20); son límites de seguridad, no reglas deportivas. |
| Subidas y borrados fuera de la transacción, con compensación solo si el fallo es anterior al commit. | Mantener `put_bytes` dentro de la transacción. | N-2 ampliado: evita `idle in transaction` durante la E/S; un commit ambiguo conserva ambos y puede dejar un huérfano, que se prefiere a una referencia rota. |
| H7 no se corrige en esta spec. | Añadir unicidad de `bracket_code` o un lock de fase. | Exige migración o coordinación nueva y queda fuera de R15; se acepta como riesgo residual documentado. |
