# Tareas 005 — Rendimiento: firmas de fotos en lote, Swiss acotado y timeouts de conexión

Spec: `specs/005-rendimiento-firmas-swiss-conexion/spec.md` (aprobada 2026-10-20)
Plan: `specs/005-rendimiento-firmas-swiss-conexion/plan.md`

Orden: **T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009 → T010**. T001-T003 son R15 y dependen entre sí; T004-T006 son R16 y dependen entre sí; T007-T008 son R17 y son independientes de los dos bloques anteriores. T009 documenta y T010 cierra.

Cada tarea se ejecuta en una sola invocación del implementador, escribe primero sus pruebas y deja CI en verde. No hay migraciones, dependencias, configuración, Compose ni frontend: la reversión es el commit anterior.

**Solapamiento con la spec 004:** en este checkout la 004 está commiteada (`3b6210f`). Si al implementar 005 siguiera sin commit, `backend/app/main.py`, `backend/tests/test_hardening.py`, `README.md`, `AGENTS.md` y `MEMORY.md` contendrían cambios suyos en el working tree: en `main.py` se tocarían **solo** el import con alias, el manejador y su registro, y la llamada al registro de configuración en `lifespan`; en `test_hardening.py` solo la sección de storage; en los documentos se conservarían sus secciones. En ese caso se commitea 004 primero o se separan los hunks con `git add -p`. En el estado actual, el diff de 005 no incluye ni revierte nada de 004.

## Progreso

- [x] **T001.** R15: cliente de firma cacheado y firma en lote.
- [x] **T002.** R15: política de fotos y camino público fuera de la transacción.
- [x] **T003.** R15: caminos del Workspace fuera de la transacción.
- [x] **T004.** R16: contador, fallback, hilo y timeout.
- [x] **T005.** R16: tope, split lectura/escritura y 409 en el router.
- [x] **T006.** R16: revalidación en la escritura y RLS.
- [x] **T007.** R17: engine con timeouts y pool explícitos.
- [x] **T008.** R17: agotamiento del pool → 503 con un aviso.
- [x] **T009.** Documentación: README, AGENTS y MEMORY.
- [x] **T010.** Verificación final y checklist de merge.

---

## T001 — R15: cliente de firma cacheado y firma en lote

**Objetivo:** construir como máximo un cliente de firma por proceso y endpoint de firma efectivo, firmar una sola vez por clave distinta y resolver un lote completo con un solo despacho off-thread, sin cambiar el contrato de subida/borrado ni la firma singular.

**RF:** RF-001, RF-002, RF-010.

**Archivos previstos:**
- `backend/app/core/storage.py`
- `backend/tests/test_storage_signing.py` (nuevo)
- `backend/tests/test_hardening.py` (solo las pruebas de storage)

**Pruebas a escribir primero:**
- `signed_urls([])` no construye cliente, no despacha hilo y devuelve `urls={}`, `failed=()`.
- Con la caché caliente, firmar 100 claves produce **0** construcciones y **1** despacho; en frío, **1** construcción.
- Dos endpoints de firma configurados producen **1** construcción por endpoint y cada firma recibe el endpoint correcto; el endpoint de subida no se usa como clave.
- Dos peticiones concurrentes en frío con un constructor que bloquea producen **exactamente 1** construcción por endpoint.
- Una clave repetida se firma una vez (`generate_presigned_url` una vez por clave única).
- Claves inválidas (vacía, absoluta, con `..`) quedan en `failed` y no llegan al cliente.
- Un fallo de una clave no impide firmar las demás; un fallo de construcción marca todas como fallidas (`build_failed`) y no envenena la caché (la siguiente llamada reintenta).
- `signed_url` lanza `StorageError` si la clave es inválida o falla, y devuelve la URL con `ExpiresIn=300` o el TTL explícito.
- La prueba existente de traversal sigue pasando; la prueba de firma singular se adapta al nuevo constructor cacheado.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_storage_signing.py` pasa.
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `grep -n "signed_urls\|_clients_lock\|SignedUrls" backend/app/core/storage.py` muestra la API y el bloqueo.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.
- El diff no toca `backend/app/core/config.py`, Compose, `.env.example` ni `backend/requirements.txt`.

**Corte:** backend en verde; el almacenamiento ya ofrece lote y caché, pero los endpoints aún no lo usan.

**Depende de:** —.

---

## T002 — R15: política de fotos y camino público fuera de la transacción

**Objetivo:** resolver `photo_url` en lote en el endpoint público, con degradación a `null` y una sola entrada de registro por respuesta, después de cerrar la transacción de lectura.

**RF:** RF-002, RF-003, RF-004, RF-010.

**Archivos previstos:**
- `backend/app/modules/tournaments/photos.py` (nuevo)
- `backend/app/modules/tournaments/router.py` (`public_matches` y helpers de presentación)
- `backend/tests/test_photo_resolution.py` (nuevo)

**Pruebas a escribir primero:**
- `sign_photo_rows(policy="null")` con firmas fallidas devuelve las filas completas, `photo_url: null` en las afectadas y conserva el resto de campos y el orden.
- `sign_photo_rows(policy="error")` lanza `HTTPException(503)` con el mensaje actual y sin datos internos.
- Una sola entrada de registro por respuesta, con el número de fallos y el motivo, sin claves, nombres, documentos ni fechas.
- Sin claves no se llama al almacenamiento y no se registra nada; con claves repetidas se firma una vez.
- Endpoint público con `get_db` sustituido (tournament, matches y lineups canónicos) y almacenamiento que lanza: **200**, `photo_url: null`, resto de la alineación intacto.
- El doble de sesión registra `in_transaction() == False` en el instante de firmar.
- Con firmas correctas, la respuesta conserva los mismos valores y el mismo orden que una referencia fija.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_photo_resolution.py` pasa.
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `grep -n "sign_photo_rows" backend/app/modules/tournaments/router.py` muestra el camino público usando la política `null`.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.

**Corte:** el camino público firma en lote fuera de la transacción y degrada a `null`; el Workspace sigue con el comportamiento anterior (hasta T003).

**Depende de:** T001.

---

## T003 — R15: caminos del Workspace fuera de la transacción

**Objetivo:** migrar lista, alta, importación, subida de foto y consentimiento al resolvedor por lote, con 503 ante fallo. Ninguna firma, subida (`put_bytes`) ni borrado (`delete_key`) ocurre con una transacción abierta: la importación sube las fotos antes de la escritura y solo compensa si el fallo es inequívocamente anterior al commit; la subida individual sigue lectura → `put_bytes` fuera → escritura → commit confirmado → borrado del anterior → firma, conservando ambos objetos si el commit falla o es ambiguo.

**RF:** RF-001, RF-002, RF-004, RF-010.

**Archivos previstos:**
- `backend/app/modules/tournaments/router.py` (`list_tournament_rosters`, `_load_roster_player`, `create_roster_player`, `create_roster_players_bulk`, `upload_roster_player_photo`, `update_roster_photo_consent`; retirar `_resolve_photo_url`/`_resolve_roster_photo_urls`)
- `backend/tests/test_photo_resolution.py` (ampliar)
- `backend/tests/test_database_timeouts.py` (nuevo, opt-in para la frontera con sesión real)

**Pruebas a escribir primero:**
- Lista de plantilla con `get_db` y `get_auth_context` sustituidos, `require_permission` sustituido por un no-op y almacenamiento que lanza: **503** con el mensaje actual.
- Lista correcta: URLs en lote, orden y campos idénticos; una clave repetida se firma una vez.
- Alta, lista y consentimiento: la fila se lee dentro de la transacción; la firma ocurre después, con el doble de sesión registrando `in_transaction() == False`.
- Importación, fallo anterior al commit: `put_bytes` se ejecuta **antes** de la transacción de escritura y con `in_transaction() == False` (`put_transaction_states == [False, …]`); si una subida posterior, la validación, el permiso o la escritura fallan, se compensa con `delete_key` y `delete_transaction_states == [False, …]`.
- Importación, commit fallido o ambiguo: no se compensa; los objetos pueden quedar huérfanos (best-effort, sin filas confirmadas) y la prueba fija ese comportamiento aceptado.
- Subida individual, commit confirmado: lectura → `put_bytes` fuera → escritura → commit confirmado → borrado del anterior → firma; `put_transaction_states` y `delete_transaction_states` contienen solo `False`.
- Subida individual, commit fallido o ambiguo: se conservan el objeto anterior y el nuevo; el nuevo puede quedar huérfano; no se compensa y no se borra el anterior (se prefiere un huérfano a una referencia rota).
- Subida individual, fallo anterior al commit: si la validación, el permiso o la escritura fallan de forma inequívoca antes del commit y el objeto nuevo ya se subió, se compensa el objeto nuevo; la cancelación durante el borrado del anterior se propaga y no se silencia.
- Importación con varias filas: una sola llamada al resolvedor y no N firmas.
- Un fallo de firma en el alta no revierte la fila ya confirmada: la respuesta es 503 después del commit. La prueba fija ese comportamiento y el plan lo declara como consecuencia de N-2 (el cliente debe releer; un reintento ciego puede dar 409).
- En la importación y en la subida, un fallo de firma posterior al commit **no** borra las claves subidas ni revierte filas; la compensación cubre solo fallos inequívocamente anteriores al commit, no un fallo de firma posterior ni un commit fallido o ambiguo. El borrado del objeto anterior no depende del éxito de la firma.
- El campo de la clave de objeto no se serializa en la respuesta (se elimina de la fila, como hoy).
- Opt-in (`RUN_DATABASE_TESTS=1`): tras cerrar la lectura, con firmante falso, `session.in_transaction()` es falso y `pg_stat_activity` del PID está en `idle`, no `idle in transaction`.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_photo_resolution.py` pasa.
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `grep -rn "_resolve_photo_url\|_resolve_roster_photo_urls" backend/app` no devuelve usos.
- La prueba opt-in se ejecuta con `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_database_timeouts.py` o se declara no ejecutada.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.

**Corte:** R15 completo en verde; no queda firma por fila ni firma, subida o borrado dentro de una transacción en los caminos de fotos.

**Depende de:** T001, T002.

---

## T004 — R16: contador, fallback, hilo y timeout

**Objetivo:** implementar el presupuesto determinista de 50 000 evaluaciones (40 000 búsqueda + 10 000 reserva), el fallback estricto, las excepciones de resultado y el runner en un ejecutor dedicado de 2 hilos con timeout de 10 s.

**RF:** RF-005, RF-006, RF-010.

**Archivos previstos:**
- `backend/app/modules/tournaments/scheduling.py`
- `backend/tests/test_swiss_budget.py` (nuevo)
- `backend/tests/test_tournament_scheduling.py` (adaptar si cambia la firma)

**Pruebas a escribir primero:**
- `PairingBudget.take` incrementa 1 por par examinado, no incrementa por ordenación, validación ni orientación, y no reinicia entre ramas, descansos ni fallback.
- Fronteras con límites inyectados pequeños (`search_limit=3`, `total_limit=5`): la evaluación que alcanza el límite se realiza y la siguiente no (semántica n−1/n/n+1), sin reinicio entre fases.
- Las constantes de producción son exactamente 64 equipos, 40 000 de búsqueda y 50 000 totales; se comprueban por introspección además de la semántica anterior.
- Determinismo: dos ejecuciones con la misma entrada producen las mismas parejas, el mismo descanso y el mismo `evaluations`.
- Regresión: 36 equipos y descanso del campo impar idénticos a los actuales.
- Fallback: agotamiento con solución existente la encuentra dentro de la reserva; agotamiento sin solución → `SwissPairingFailure("budget_exhausted")`; búsqueda completa sin solución → `SwissPairingFailure("no_valid_pairing")`; el fallback nunca repite rivales.
- Validación: equipos insuficientes o repetidos, semilla negativa y metas inválidas siguen lanzando `ValueError`.
- `run_swiss_pairing` con un doble que no termina y timeout inyectado corto lanza `SwissPairingTimeout` y no escribe nada.
- Una corrutina concurrente progresa mientras un cálculo lento controlado está en curso (el event loop no se bloquea).
- El ejecutor es dedicado, de 2 hilos, y no es el ejecutor por defecto.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_swiss_budget.py` pasa.
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `grep -n "MAX_SWISS_TEAMS\|SWISS_SEARCH_LIMIT\|SWISS_PAIRING_LIMIT\|run_swiss_pairing" backend/app/modules/tournaments/scheduling.py` muestra constantes y runner.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.

**Corte:** el algoritmo está acotado y probado; el router aún no lo usa y el fallo de sorteo sigue siendo 500.

**Depende de:** —.

---

## T005 — R16: tope, split lectura/escritura y 409 en el router

**Objetivo:** aplicar el tope de 64 equipos, ejecutar el cálculo fuera de la transacción, escribir en una transacción posterior y mapear los fallos del emparejamiento a 409 distinguibles.

**RF:** RF-005, RF-006, RF-007, RF-010.

**Archivos previstos:**
- `backend/app/modules/tournaments/router.py` (`draw_stage_schedule`, `_draw_swiss_schedule`, carga de entradas y escritura)
- `backend/tests/test_swiss_transaction.py` (nuevo)

**Pruebas a escribir primero:**
- 65 equipos → **422** «La fase Swiss admite como máximo 64 equipos» antes de cualquier escritura y antes de enviar trabajo al ejecutor; 64 → aceptado.
- El conjunto contado es el de `_load_registered_stage_teams`; equipos no asignados a la fase no cuentan.
- En rondas > 1 no se borran marcadores ni partidos anteriores.
- El cálculo se envía después de cerrar la transacción de lectura (doble de sesión o de runner que registra `in_transaction()`).
- `budget_exhausted`, `no_valid_pairing` y `SwissPairingTimeout` → 409 con mensajes distintos; `ValueError` de validación conserva su comportamiento (no se convierte en 409).
- Ningún fallo de emparejamiento emite `INSERT`/`UPDATE`: el doble de base cuenta las escrituras y son 0.
- En la ronda 1, los marcadores y las parejas se crean en la transacción de escritura, después del cálculo; `_clear_stage_schedule` se ejecuta en la escritura, no en la lectura.
- Un fallo de escritura revierte todo; no queda calendario parcial.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_swiss_transaction.py` pasa.
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `grep -n "MAX_SWISS_TEAMS\|run_swiss_pairing" backend/app/modules/tournaments/router.py` muestra el tope y la llamada.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.

**Corte:** el sorteo Swiss está acotado, corre fuera de la transacción y devuelve 409 en lugar de 500; la revalidación de estado llega en T006.

**Depende de:** T004.

---

## T006 — R16: revalidación en la escritura y RLS

**Objetivo:** en la transacción de escritura, fijar de nuevo el contexto RLS, revalidar el permiso de gestión y el estado de la fase, y responder **403** si el permiso se revocó o **409** si algo cambió entre la lectura y la escritura, sin escribir nada.

**RF:** RF-006, RF-010.

**Archivos previstos:**
- `backend/app/modules/tournaments/router.py` (transacción de escritura del Swiss)
- `backend/tests/test_swiss_transaction.py` (ampliar)

**Pruebas a escribir primero:**
- Permiso revocado entre lectura y escritura → **403** y cero escrituras; la revalidación del permiso ocurre después de `set_rls_context` y antes de la revalidación de estado (doble que registra el orden).
- Ronda 1: si apareció un partido entre lectura y escritura → **409** «el estado de la fase cambió durante el sorteo; vuelve a intentarlo» y ninguna escritura.
- Rondas > 1: si un placeholder dejó de estar `cancelled` o una ronda previa dejó de estar terminada → 409 y ninguna escritura.
- Camino feliz: la escritura se confirma y el estado queda como el actual (mismas parejas y marcadores).
- La transacción de escritura llama a `set_rls_context` antes de cualquier consulta (doble que registra el orden).
- Los placeholders se leen con `FOR UPDATE` en la escritura (doble que registra el bloqueo).
- Opt-in (`RUN_DATABASE_TESTS=1`), sin escrituras con BD real: un fallo de emparejamiento no cambia el conteo de `matches`.
- Opt-in (`RUN_DATABASE_TESTS=1`), aislamiento RLS A/B: en el camino feliz `current_setting('app.current_organization_id')` coincide con la organización y la organización B no ve los placeholders de A.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_swiss_transaction.py` pasa.
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `grep -n "el estado de la fase cambió\|FOR UPDATE" backend/app/modules/tournaments/router.py` muestra el mensaje y el bloqueo.
- `grep -n "set_rls_context\|_require_tournament_management\|_revalidate_swiss_draw_state" backend/app/modules/tournaments/router.py` muestra el orden en la transacción de escritura.
- Las pruebas opt-in se ejecutan o se declaran no ejecutadas.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.

**Corte:** R16 completo en verde; permiso revocado → 403, estado cambiado → 409, ningún fallo confirma escrituras y la escritura no se apoya en un estado viejo.

**Depende de:** T005.

---

## T007 — R17: engine con timeouts y pool explícitos

**Objetivo:** fijar `statement_timeout` de 15 s, `idle_in_transaction_session_timeout` de 30 s, pool 10 + 10 con espera de 10 s y registrar los valores efectivos al arrancar.

**RF:** RF-008, RF-009, RF-010.

**Archivos previstos:**
- `backend/app/core/database.py`
- `backend/tests/test_database_config.py` (nuevo)
- `backend/tests/test_database_timeouts.py` (ampliar con el `SHOW`)

**Pruebas a escribir primero:**
- `engine_options()` devuelve exactamente `pool_size=10`, `max_overflow=10`, `pool_timeout=10` y `connect_args.server_settings` con `"15000"` y `"30000"`.
- El engine real tiene tamaño de pool 10, desbordamiento 10 y espera 10 s; `pool_pre_ping` sigue activo.
- `log_database_configuration()` emite una sola entrada con los cinco valores y sin URL, usuario ni credenciales (caplog).
- Opt-in (`RUN_DATABASE_TESTS=1`): `SHOW statement_timeout` devuelve `15s` y `SHOW idle_in_transaction_session_timeout` devuelve `30s` sobre una conexión del engine de la aplicación.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_database_config.py` pasa.
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `grep -n "DB_STATEMENT_TIMEOUT_MS\|DB_POOL_SIZE\|engine_options" backend/app/core/database.py` muestra constantes y función.
- La prueba opt-in se ejecuta con `RUN_DATABASE_TESTS=1` o se declara no ejecutada.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.

**Corte:** la conexión tiene timeouts y pool efectivos; el agotamiento aún devuelve el comportamiento por defecto hasta T008.

**Depende de:** —.

---

## T008 — R17: agotamiento del pool → 503 con un aviso

**Objetivo:** mapear `sqlalchemy.exc.TimeoutError` a 503 con un único aviso por petición fallida y registrar la configuración al arrancar.

**RF:** RF-009, RF-010.

**Archivos previstos:**
- `backend/app/main.py` (import con alias, manejador nuevo, registro y llamada a `log_database_configuration()` en `lifespan`; nada más)
- `backend/tests/test_database_config.py` (ampliar)

**Pruebas a escribir primero:**
- Una ruta que lanza `sqlalchemy.exc.TimeoutError` responde **503** con `{"detail": "Servicio temporalmente no disponible"}` y emite **exactamente una** entrada de aviso.
- El aviso no contiene SQL, parámetros, nombre de la base ni credenciales.
- Una ruta que lanza `DBAPIError` sigue respondiendo 500 con el SQLSTATE (prueba existente sin cambios).
- Una ruta correcta no emite avisos de pool.
- `lifespan` llama una vez a `log_database_configuration()`: se sustituyen `relay_loop`, `_revalidate_socket_sessions` y `validate_application_role` por dobles, se entra y se sale del contexto y se comprueba la llamada; no se arranca el relay real.

**Hecho cuando:**
- `cd backend && pytest -q tests/test_database_config.py` pasa.
- `cd backend && pytest -q` pasa.
- `cd backend && python -m compileall -q app` pasa.
- `git diff -U0 backend/app/main.py` no añade hunks de 005 fuera del manejador y la llamada al registro; si 004 siguiera sin commit, sus hunks no se modifican.
- `grep -n "Pool de conexiones agotado\|Servicio temporalmente no disponible" backend/app/main.py` muestra el contrato.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.

**Corte:** R17 completo en verde; el agotamiento es 503 y observable, y el resto de errores de base siguen igual.

**Depende de:** T007.

---

## T009 — Documentación: README, AGENTS y MEMORY

**Objetivo:** documentar los cambios observables y las decisiones operativas, sin afirmar nada que no se haya implementado.

**RF:** RF-011.

**Archivos previstos:**
- `README.md`
- `AGENTS.md`
- `MEMORY.md`

**Contenido obligatorio:**
- `README.md`, `AGENTS.md` y `MEMORY.md`: en este checkout la 004 está commiteada (`3b6210f`); si al implementar 005 siguiera sin commit, se conservan sus secciones y se editan solo las de rendimiento, fotos, conexión y errores de 005.
- Tope Swiss de 64 equipos, presupuesto de 50 000 evaluaciones (40 000 búsqueda + 10 000 reserva), timeout de 10 s y ejecución en un ejecutor dedicado de 2 hilos con resultado descartable.
- Códigos y mensajes: 422 por tope; 409 por presupuesto, sorteo imposible, timeout y estado cambiado; los `ValueError` de validación conservan su comportamiento.
- Fotos: `photo_url: null` en público ante fallo de firma, 503 en Workspace, un registro por respuesta. En alta o importación, un fallo de firma posterior al commit deja la fila creada y responde 503; el cliente debe releer.
- Conexión: 15 s / 30 s, pool 10 + 10 con espera de 10 s, 503 por agotamiento, agregado de 60 conexiones con `API_WORKERS=2` y un worker frente a 100 por defecto.
- Reinicio del proceso al rotar credenciales de almacenamiento por el cliente cacheado.
- Ninguna firma de fotos ni emparejamiento dentro de una transacción; el contexto RLS es local a cada transacción.
- `MEMORY.md` registra el cierre con evidencia, sin secretos ni datos personales, y respeta ~50 líneas.
- No se documentan variables nuevas ni se modifica `.env.example`.

**Hecho cuando:**
- `grep -n "64 equipos\|50 000\|10 s\|API_WORKERS\|503\|idle_in_transaction" README.md AGENTS.md` muestra los conceptos.
- `grep -n "Spec 005" MEMORY.md` muestra el registro.
- `wc -l MEMORY.md` devuelve ≤ 50.
- `git -c core.whitespace=cr-at-eol diff --check` pasa.
- Ningún documento afirma que se añadieron variables de entorno, migraciones o dependencias.

**Corte:** documentación alineada; no cambia código ni CI.

**Depende de:** T003, T006, T008.

---

## T010 — Verificación final y checklist de merge

**Objetivo:** comprobar que la spec aprobada está implementada, que no hay cambios fuera de alcance y que el cambio puede fusionarse.

**RF:** RF-001 a RF-011.

**Checklist:**
- [x] `cd backend && pytest -q` pasa. *(2026-10-22, con `RUN_DATABASE_TESTS=1` y base en 023: 999 passed, 2 warnings. Una corrida local previa falló 3 pruebas de `test_birth_date_backfill.py`; el archivo pasa en aislamiento (21 passed) y la corrida completa siguiente fue verde: fallo transitorio, no del producto.)*
- [x] `cd backend && python -m compileall -q app` pasa.
- [x] Las pruebas opt-in de `tests/test_database_timeouts.py` y `tests/test_swiss_transaction.py` se ejecutaron con `RUN_DATABASE_TESTS=1` o se declararon no ejecutadas con su motivo, incluidas las dos nuevas de Swiss: sin escrituras con BD real y aislamiento RLS A/B. *(Se ejecutaron dentro de la corrida completa con `RUN_DATABASE_TESTS=1`: las dos de `test_database_timeouts.py` y `test_opt_in_pairing_failure_leaves_no_new_or_modified_matches` / `test_opt_in_rls_isolation_and_write_phase_reapplies_the_context`; el resumen no registra pruebas omitidas.)*
- [x] Los cinco jobs de CI (`backend`, `frontend`, `infrastructure`, `security` y `e2e`) están en verde sobre `main`. *(Corrida de `9ad8db1`, 2026-10-22. En el momento del commit de 005 (`37019e7`, `8b5eae0`) `ci.yml` tenía cuatro jobs: `e2e` llegó con la enmienda 1.4.0 de la constitución y la spec 010.)*
- [x] El commit de 005 no incluye `infra/postgres/`, `docker-compose.yml`, `docker-compose.production.yml`, `.env.example`, `backend/requirements.txt`, `.github/workflows/ci.yml` ni `frontend/`. *(Verificado con `git show --name-only 37019e7 8b5eae0`: ninguna de esas rutas.)*
- [x] Si la spec 004 siguiera sin commit, sus archivos (`backend/app/workers/outbox.py`, el relay de `backend/app/main.py`, `backend/tests/test_outbox_*.py`, el frontend de tiempo real y las secciones de docs) no forman parte del commit de 005; si ya está commiteada (`3b6210f`), el commit de 005 no la revierte. *(004 está en `3b6210f`; los commits de 005 no tocan `backend/app/workers/outbox.py`, `backend/tests/test_outbox_*.py`, el frontend de tiempo real ni `specs/004-*`, y sus pruebas siguen en verde.)*
- [x] `git diff -U0 backend/app/main.py backend/tests/test_hardening.py` no añade hunks de 005 fuera de los esperados (manejador, registro, llamada al log y pruebas de storage); si 004 siguiera sin commit, sus hunks permanecen intactos. *(`37019e7` solo añade el import con alias, el manejador de agotamiento, su registro y la llamada a `log_database_configuration()` en `lifespan`, más la sección de storage de `test_hardening.py`; `8b5eae0` no toca esos archivos.)*
- [x] RF-001 a RF-004 verificados con `tests/test_storage_signing.py` y `tests/test_photo_resolution.py`.
- [x] Caso de commit fallido o ambiguo documentado y probado en subida e importación: se conservan ambos objetos, el nuevo puede quedar huérfano, no se compensa y no se borra el anterior; la cancelación durante el borrado del anterior se propaga. *(`test_upload_photo_keeps_both_objects_when_cancelled_during_commit`, `test_upload_photo_keeps_the_previous_object_when_the_commit_fails`, `test_bulk_import_keeps_orphans_when_the_commit_fails` y `test_bulk_import_does_not_delete_objects_when_cancelled_during_commit`; descrito en `README.md`.)*
- [x] RF-005 y RF-006 verificados con `tests/test_swiss_budget.py` y `tests/test_swiss_transaction.py`.
- [x] RF-008 y RF-009 verificados con `tests/test_database_config.py` y `tests/test_database_timeouts.py`.
- [x] RF-011 verificado con la revisión de `README.md`, `AGENTS.md` y `MEMORY.md`. *(El tope de 64, las 50 000 evaluaciones, el timeout de 10 s y el 503 por agotamiento aparecen en `README.md` y `AGENTS.md`.)*
- [x] Riesgo residual aceptado declarado: dos sorteos simultáneos en frío en la ronda 1 pueden insertar calendarios duplicados (`FOR UPDATE` no bloquea filas inexistentes y `bracket_code` no es único); no se presenta como resuelto ni se corrige en esta spec. *(`README.md` y `AGENTS.md` lo registran como riesgo aceptado de la spec 005.)*
- [x] No se declara resuelto ningún hallazgo distinto de R15, R16 y R17; R06, R09/R10, R11/R12 y R18-R32 siguen fuera de alcance. *(La decisión S-1 y los documentos de estado actual mantienen el resto fuera de alcance; el filtrado por rol exige una spec propia.)*
- [x] Lo que no se pudo ejecutar se declara; no se afirma una verificación no realizada. *(Véase la evidencia de cierre al final de este archivo.)*
- [x] La revisión humana es distinta del autor. *(Registrada en `spec.md`: «validada por @reviewer (APROBADA, 2026-10-20)»; la identidad del autor no consta en el repositorio.)*

**Comandos de cierre:**
```sh
cd backend && pytest -q
cd backend && python -m compileall -q app
cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_database_timeouts.py tests/test_swiss_transaction.py
git -c core.whitespace=cr-at-eol diff --check
git diff --name-only
```

La ejecución opt-in requiere `DATABASE_URL` con el rol de aplicación; si no hay PostgreSQL disponible, se declara como no ejecutada. `docker compose config -q` **no aplica**: no hay cambios de Compose. `pnpm test`/`typecheck`/`build` **no aplican**: no hay cambios de frontend. Si el diff los incluyera, se detiene y se reporta antes de cerrar.

**Corte:** cierre de la spec con evidencia de CI y revisión humana.

**Depende de:** T009.

## Cierre

No se crean migraciones, scripts operativos ni variables de entorno. T001-T008 se pueden revertir commit a commit; T009 y T010 no cambian comportamiento. El único riesgo de reversión con efecto funcional es el split de transacciones (T005/T006): revertirlo restaura la transacción única y el 500 por sorteo imposible, sin datos que deshacer porque ningún fallo confirma escrituras.

**Evidencia de cierre (2026-10-22, `main` en `9ad8db1`):** `cd backend && pytest -q` con `RUN_DATABASE_TESTS=1` y base en 023 (999 passed, incluidas las opt-in), `python -m compileall -q app` y los cinco jobs de CI en verde (incluido `e2e`); el alcance de `37019e7` y `8b5eae0` se comprobó con `git show --name-only`.
