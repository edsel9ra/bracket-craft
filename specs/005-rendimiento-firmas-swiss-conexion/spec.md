# Spec 005 — Rendimiento: firmas de fotos en lote, Swiss acotado y timeouts de conexión

Estado: implementada, validada por @reviewer (APROBADA, 2026-10-20) y cerrada (2026-10-20, commits `37019e7` y `8b5eae0`); §6 aprobada por el usuario (2026-10-21). Checklist de T010 completo.

> Bloque **B (rendimiento)** del P1 de `docs/auditoria-2026-10-19.md`: R15, R16 y R17. El alcance está cerrado por el usuario y no se amplía a otros hallazgos. Las decisiones **P-1 a P-5** (clarificación) y **N-1 y N-2** (transacciones y event loop) están cerradas y el plan no puede reabrirlas. Las observaciones del QA se resolvieron en la sección «Resoluciones del QA». La implementación se validó en la vuelta 1 (399 passed/108 skipped; opt-in no ejecutado por falta de credenciales); la revalidación por @reviewer quedó registrada en esta cabecera y el cierre T010 está completo (véase la evidencia de cierre al final del documento).

## Contexto y objetivo

La auditoría técnica integral del 2026-10-19 registra tres hallazgos **MEDIOS** de rendimiento. Los tres comparten un patrón: trabajo que crece con el tamaño de la entrada y que hoy no tiene cota explícita, ni presupuesto, ni configuración efectiva. Además, dos de ellos ejecutan trabajo costoso dentro de la transacción de base de datos. El estado siguiente se verificó sobre el árbol de trabajo el 2026-10-20.

- **R15 — firma de fotos jugador a jugador.** Cada jugador con consentimiento y foto provoca la construcción de un cliente de almacenamiento nuevo (`backend/app/core/storage.py:33-49`, `boto3.client` en las líneas 36-49) y una firma individual dentro de una llamada off-thread (`storage.py:115-128`, `generate_presigned_url` + `asyncio.to_thread`). El bucle está en `_resolve_roster_photo_urls` (`backend/app/modules/tournaments/router.py:1272-1278`) y se invoca desde la plantilla del Workspace (`router.py:1340`, hasta 1 000 filas por `limit` en `router.py:1306`) y, en el camino público, **dentro del bucle de alineaciones** de `/tournaments/public/{id}/matches` (`router.py:3142`, endpoint en `router.py:3068-3076`). La cota superior teórica de una sola respuesta pública es **500 partidos × 2 equipos × 100 entradas** = 100 000 construcciones de cliente y 100 000 despachos al ejecutor de hilos (`limit` máximo 500 en `router.py:3074`; entradas por alineación máximo 100 en `backend/app/modules/matches/schemas.py:169`).
- **R15 — trabajo dentro de la transacción.** El endpoint público ejecuta sus consultas con `Depends(get_db)` y firma antes de que la sesión termine la transacción implícita; la plantilla del Workspace firma después de `async with db.begin()` (`router.py:1309-1310,1340`), pero el detalle de plantilla resuelve la foto **dentro** de la transacción del alta y la consulta (`router.py:1355-1359,1281-1297`). Mientras se firma, la conexión queda *idle in transaction*.
- **R16 — Swiss con backtracking sin cota.** `pair_remaining` (`backend/app/modules/tournaments/scheduling.py:269-290`) explora combinaciones con recursión y sin memoización, presupuesto ni contador. `build_swiss_pairings` (`scheduling.py:200-314`) lo invoca una vez por candidato a descanso cuando el número de equipos es impar (`scheduling.py:304-308`), de modo que el coste multiplica. No hay tope de equipos para una fase Swiss: el esquema admite hasta 64 rondas (`backend/app/modules/tournaments/schemas.py:149-152`), la llave de eliminación directa sí tiene tope (`MAX_SINGLE_ELIMINATION_TEAMS = 512`, `scheduling.py:7`) y la carga de equipos de la fase no tiene límite (`router.py:2014-2043`). Se ejecuta **en el event loop** y **dentro de la transacción** del request (`POST /tournaments/{id}/matches/draw`, `router.py:2417-2487`, `async with db.begin()` en `router.py:2428`). Si el sorteo no encuentra solución, `ValueError` (`scheduling.py:314`) **no** se traduce a un 4xx: no hay manejador de `ValueError` en `backend/app/main.py` (solo `RequestValidationError` y `DBAPIError`, líneas 594-595), así que la respuesta es un 500.
- **R17 — conexión sin timeouts ni pool explícito.** El engine se crea con una sola opción (`backend/app/core/database.py:12`: `create_async_engine(settings.database_url, pool_pre_ping=True)`). No hay `statement_timeout`, ni `idle_in_transaction_session_timeout`, ni `pool_size`, `max_overflow` o `pool_timeout` declarados: se usan los defaults de SQLAlchemy (5 + 10 de desbordamiento, espera de 30 s) y los de PostgreSQL (sin timeout de sentencia). Ese engine lo comparten la API (`main.py`), el worker del outbox (`backend/app/workers/outbox.py:10,56`) y el seed de desarrollo (`backend/scripts/seed_demo.py:22`). En producción la API corre con `--workers ${API_WORKERS:-2}` (`docker-compose.production.yml:46`), de modo que el pool se multiplica por proceso. El único manejador de errores de base de datos devuelve 500 con el SQLSTATE (`main.py:579-591`) y no cubre el agotamiento del pool, que no es un `DBAPIError`.

**Objetivo:** eliminar el trabajo por fila en la firma de fotos sin tocar la política de privacidad ni el contrato público; acotar el emparejamiento Swiss con un tope, un presupuesto determinista y un *timeout* de seguridad, ejecutándolo fuera del event loop y fuera de la transacción; y fijar timeouts de sesión y dimensionado de pool explícitos, con comportamiento definido y observable al agotarse. Ninguna E/S de almacenamiento ni cálculo de emparejamiento debe ejecutarse con una transacción abierta.

**Cómo se comprobaría:** con contadores en pruebas (construcciones de cliente, despachos off-thread, evaluaciones de pares), con aserciones de frontera de transacción y de event loop, y con verificaciones opt-in contra PostgreSQL. No con latencias.

## Alcance

Incluye:

1. Reutilización de un cliente de firma por proceso y endpoint de firma efectivo, en lugar de uno por jugador.
2. Resolución de fotos en una sola pasada acotada sobre las filas de la respuesta, con deduplicación por clave dentro de la respuesta.
3. Política de fallo de firma (degradación a `null` en público, 503 en Workspace) y TTL de la URL, sin cambios en la decisión de consentimiento.
4. Tope explícito de equipos, presupuesto determinista y *timeout* de seguridad para el emparejamiento Swiss, ejecutado en un hilo aparte.
5. Fallback greedy acotado y resultados de error deterministas (409) en lugar del 500 actual, con errores de validación que conservan su comportamiento.
6. Frontera de transacción explícita: consultas y RLS dentro; firma de fotos, **subida (`put_bytes`)**, **borrado (`delete_key`)** y emparejamiento fuera.
7. Timeouts de sentencia y de transacción inactiva, y dimensionado explícito del pool en la conexión de la aplicación.
8. Comportamiento y observabilidad definidos al agotarse el pool o dispararse un timeout, incluido el agregado de conexiones por proceso.
9. Pruebas unitarias con dobles y verificaciones opt-in contra PostgreSQL, y documentación de los cambios observables.

## No objetivos

- No se persigue mejorar latencias medidas ni se fijan objetivos de tiempo: el entorno de validación no tiene infraestructura real y la spec prohíbe inventar cifras. El *timeout* del emparejamiento es una red de seguridad, no un objetivo de rendimiento.
- No se convierte la firma en un servicio, no se introduce CDN ni caché de URLs firmadas entre peticiones.
- No se cambia el proveedor de almacenamiento, el formato de las claves, el bucket ni la política de consentimiento.
- No se rediseña el formato Swiss ni sus reglas deportivas (puntuación, desempates, metas de local/visitante): solo se acota su coste, se hace determinista su fallo y se saca del event loop y de la transacción.
- No se añaden índices, migraciones ni cambios de esquema.
- No se ajustan los límites de paginación existentes ni el número de rondas permitido.
- No se introducen dependencias nuevas.
- No se reordena el flujo funcional del sorteo más allá de lo que exige la frontera de transacción: las mismas validaciones, las mismas lecturas y los mismos datos de entrada.

## Decisiones cerradas (2026-10-20)

### Alcance

- **S-1.** El bloque se limita a R15, R16 y R17 de la auditoría. Cualquier otro hallazgo (R06, R09/R10, R11/R12, R18-R32) queda fuera y no se documenta como resuelto.
- **S-2.** La implementación se limita a R15, R16 y R17 y no toca la spec 004 ni su comportamiento.
- **S-3.** El contrato público se mantiene: `photo_url` sigue siendo una cadena o `null`, y solo aparece con consentimiento de imagen. Los únicos cambios observables autorizados son los códigos de error y la degradación de foto descritos en esta spec; cualquier otro se detiene y se pregunta.

### Clarificación

Aprobadas por el usuario. El plan no puede reabrirlas.

- **P-1 = A. Tope de 64 equipos y presupuesto de 50 000 evaluaciones de pares por solicitud, como constantes del backend.** Sin variable de entorno ni cambios en Compose o `.env.example`. *Motivo:* 64 cubre con holgura el formato de 36 equipos ya probado, coincide con los topes de 64 ya vigentes para grupos y cabezas de grupo, y el presupuesto contado en pares es determinista y no depende del hardware. *Descartada:* 128 equipos con 200 000 evaluaciones (encarece el peor caso sin un caso de uso demostrado) y la configuración por entorno (añade drift de configuración, R20).
- **P-2 = A. Fallback estricto con «no repetir rivales» y error determinista 4xx (409 en esta spec) si no empareja a todos.** Distingue «presupuesto agotado» de «sorteo imposible». *Motivo:* repetir rivales en silencio alteraría la integridad deportiva del formato Swiss; es preferible un error accionable a un calendario dudoso. *Descartada:* relajar la restricción como último recurso (exigiría un campo aditivo en la respuesta y cambiaría el significado del formato) y no tener fallback (dejaría el 500 actual en los casos de presupuesto agotado con solución existente).
- **P-3 = A. Fallo de firma: degradar a `photo_url: null` en los endpoints públicos y mantener 503 en los del Workspace.** Un solo registro por respuesta. *Motivo:* una foto caída no debe tumbar la ficha pública, mientras que el operador del Workspace necesita ver el fallo para corregir la configuración de almacenamiento. *Descartada:* degradar en todos (oculta el problema al operador) y mantener 503 en todos (acopla la disponibilidad del torneo público al almacenamiento de fotos).
- **P-4 = A. Constantes del backend: `statement_timeout` 15 000 ms, `idle_in_transaction_session_timeout` 30 000 ms, pool 10 + 10 con espera de 10 s.** Sin variables nuevas ni cambios en Compose o `.env.example`. *Motivo:* elimina el drift de configuración y deja valores explícitos revisables en el código; 15 s acota una consulta desbocada sin cortar las consultas actuales y 30 s de inactividad es holgadamente mayor que la latencia de una firma. *Descartada:* variables de entorno cableadas en `api` y `worker` (más superficie de configuración y de error de despliegue, sin necesidad operativa demostrada).
- **P-5 = A. Agotamiento del pool → 503 genérico con aviso estable; `statement_timeout` → 500 saneado actual, registrado.** *Motivo:* el agotamiento del pool es transitorio y reintentable, mientras que un timeout de sentencia suele indicar una consulta que debe corregirse, no reintentarse. *Descartada:* 503 para ambos (enmascara un defecto de consulta como si fuera capacidad) y 500 para ambos (una sobrecarga transitoria dejaría de ser distinguible de un fallo interno y no sería reintentable).
- **N-1 = A. Emparejamiento Swiss en un hilo aparte, con presupuesto determinista y timeout de seguridad.** El cálculo (búsqueda y fallback) no corre en el event loop ni dentro de la transacción. Se ejecuta en un ejecutor dedicado y acotado (**2 hilos**, distinto del ejecutor por defecto que atiende la firma de fotos) con un **timeout de 10 000 ms** que cubre también la espera en cola. Al vencer: **409** con mensaje propio de tiempo máximo de cálculo, el resultado se descarta y se registra como anomalía. Un hilo de Python **no se puede cancelar**: sigue hasta agotar su presupuesto, que garantiza su terminación, y nunca escribe ni comparte estado con la petición. *Motivo:* saca del event loop un cálculo que puede ser largo, sin renunciar al determinismo del presupuesto; el timeout acota la espera del cliente aunque el hilo siga vivo unos instantes. *Descartada:* ejecutarlo en el ejecutor por defecto (una búsqueda desbocada robaría un hilo a la firma de fotos) y confiar solo en el presupuesto sin timeout (dejaría al cliente esperando ante una regresión del algoritmo).
- **N-2 = A. Frontera de transacción explícita.** Orden obligatorio: **transacción de lectura con RLS → commit/cierre → trabajo puro y E/S de almacenamiento fuera → transacción de escritura (solo si hace falta escribir) → respuesta**. Ninguna firma de fotos, **ninguna subida (`put_bytes`)**, **ningún borrado (`delete_key`)** y ningún emparejamiento ocurren con una transacción abierta. En la importación las fotos se suben **antes** de la escritura; los objetos se compensan con `delete_key` solo si el fallo es inequívocamente anterior al commit, y un commit fallido o ambiguo puede dejarlos huérfanos (best-effort, sin filas confirmadas). En la subida individual el orden es lectura → `put_bytes` fuera → escritura → **commit confirmado** → borrado del objeto anterior → firma; si el commit falla o se cancela (ambiguo), se conservan ambos objetos y el nuevo puede quedar huérfano; si el fallo es inequívocamente anterior al commit (validación, permiso, escritura), se compensa el objeto nuevo. Un fallo de firma posterior al commit no borra el objeto nuevo ni revierte filas. El contexto RLS viaja en el `set_config(..., true)` de cada transacción; el trabajo puro recibe datos ya cargados y no consulta la base. *Motivo:* acorta las transacciones y elimina el riesgo de `idle_in_transaction_session_timeout` en los caminos afectados, sin relajar RLS. *Descartada:* mantener la transacción abierta durante la firma, la subida o el cálculo (deja conexiones *idle in transaction*, retiene locks y consume pool) y usar una sola transacción con `SET LOCAL` reutilizado tras el commit (imposible: el contexto es local a la transacción).

### Consecuencias de las decisiones

- El diff **no** toca `docker-compose.yml`, `docker-compose.production.yml` ni `.env.example`: no hay variables nuevas. `docker compose config -q` no es un comando aplicable a este cambio; si el plan necesitara tocarlos, sería una desviación que se detiene y se pregunta.
- Los códigos quedan fijados: **422** al superar el tope de equipos; **409** para presupuesto agotado, sorteo imposible, tiempo máximo de cálculo y estado de la fase cambiado entre lectura y escritura; **503** por agotamiento del pool; **500 saneado** para `statement_timeout` y para los `ValueError` de validación existentes, que conservan su comportamiento y **no** se convierten en 409.
- La política de fotos queda fijada por camino: **público** (sin sesión) degrada a `null`; **Workspace** (con sesión y permiso de gestión) responde 503. Ambos registran una sola entrada por respuesta.
- Las **subidas y borrados** de objetos salen de la transacción: en importación se suben antes de la escritura y se compensan solo si el fallo es inequívocamente anterior al commit (un commit fallido o ambiguo puede dejar huérfanos, best-effort); en la subida individual, lectura → `put_bytes` → escritura → commit confirmado → borrado del anterior → firma. Si el commit falla o se cancela, se conservan el anterior y el nuevo, y el nuevo puede quedar huérfano; se prefiere un huérfano a una referencia rota. Un fallo de firma posterior al commit deja la fila creada, responde 503 y **no** borra el objeto nuevo ni revierte filas.
- La transacción de escritura del sorteo revalida el **permiso de gestión** después de `set_rls_context` y antes de la revalidación de estado: permiso revocado → **403** y cero escrituras.
- El **timeout** del cálculo se registra a nivel `error` como anomalía; el resultado se descarta.
- El cliente de firma cacheado conserva las credenciales resueltas al construirse: **rotar credenciales de almacenamiento exige reiniciar el proceso**. Se documenta como limitación operativa (RF-011) y no se implementa recarga en caliente.
- Los valores de timeouts y pool se entienden **por proceso**. Con `API_WORKERS=2` y un worker: 2 × 20 + 20 = **60 conexiones** teóricas frente a las 100 por defecto de PostgreSQL. Se documenta; no se cambia P-4.

### Correcciones de la vuelta 1 (2026-10-20)

- **C-1 (N-2 ampliado, RF-002).** La frontera cubre también `put_bytes` y `delete_key`: importación sube antes de la escritura y compensa solo fallos inequívocamente anteriores al commit (un commit fallido/ambiguo puede dejar huérfanos); subida individual lectura → `put_bytes` → escritura → commit confirmado → borrado del anterior → firma; un commit fallido/ambiguo conserva ambos y puede dejar el nuevo huérfano. Un fallo de firma posterior al commit no borra el objeto nuevo ni revierte filas.
- **C-2 (H1, RF-006).** `no_valid_pairing` solo si la búsqueda terminó sin alcanzar 40 000 y sin solución; un fallback fallido tras agotar la búsqueda es `budget_exhausted`.
- **C-3 (H3, RF-006).** La escritura revalida el permiso de gestión tras `set_rls_context` y antes del estado; permiso revocado → 403 y cero escrituras.
- **C-4 (H7, riesgos residuales).** En ronda 1 en frío, `FOR UPDATE` no bloquea filas inexistentes y `bracket_code` no es único: dos sorteos concurrentes podrían duplicar el calendario. Aceptado y fuera de alcance.
- **C-5 (H8, RF-005).** El timeout se registra a nivel `error` como anomalía.
- **C-6 (H9, RF-006).** El fallback usa `candidate_key`, el mismo orden de prioridad que la búsqueda.

### Resoluciones del QA (2026-10-20)

- **B-1. Un único contador de presupuesto por solicitud**, compartido por la búsqueda, todos los candidatos a descanso y el fallback, con regla exacta de incremento y consumo (RF-005).
- **B-2. Firma entre sentencias corregida:** firmar entre sentencias deja la conexión *idle in transaction*, no activa. Con N-2 esto no ocurre en los caminos de fotos; si un camino futuro lo hiciera, el servidor corta la conexión a los 30 s, la petición recibe el 500 saneado y se registra el SQLSTATE (RF-008, caso 11).
- **B-3. Documentación obligatoria** de los cambios observables en `README.md` y `AGENTS.md` (RF-011 y criterios de finalización).
- **B-4. «Cliente de firma» y endpoints aclarados:** la caché indexa el endpoint de firma; el endpoint de subida es distinto y no forma parte del requisito (RF-001).
- **B-5. Conjunto contado del tope:** los equipos de la fase cargados por `_load_registered_stage_teams`; en rondas > 1 no se borran marcadores anteriores (RF-005).
- **B-6. Sin escrituras confirmadas:** la transacción de escritura no se abre hasta que el emparejamiento tiene éxito; no se exige reordenar el flujo funcional (RF-006).
- **B-7. Errores nuevos separados de la validación:** 409 solo para resultados del emparejamiento; los `ValueError` de validación conservan su comportamiento (RF-006).
- **B-8. Prueba de concurrencia en frío incluida** (no se retira el criterio) (RF-001, RF-010).
- **B-9. Pruebas unitarias y opt-in declaradas**, con el caso del límite exacto de 50 000 (RF-010).
- **B-10. Punto de prueba definido** para los dos call sites de fotos, con doble de sesión y doble de almacenamiento (RF-002, RF-004, RF-010).
- **B-11. Agregado de conexiones documentado** con `API_WORKERS` y worker frente a `max_connections` (RF-009).
- **B-12. Presupuesto fuera del event loop**, con timeout y coste acotado (RF-005, RNF-003).
- **B-13. Seed y suite opt-in cerrados por decisión:** se aceptan y documentan; un fallo por 15 s se trata como defecto del seed o de la prueba, nunca como motivo para elevar la constante (RF-008).
- **B-14. Pool:** condición observable (`sqlalchemy.exc.TimeoutError`), clasificación como capacidad transitoria (RF-009).
- **B-15. Pool:** una sola regla de registro por agotamiento: un aviso por petición fallida, ninguno por espera ni por éxito (RF-009).
- **B-16. Errata corregida:** «esquemas de respuesta» (RF-007).
- **B-17. Constitución §3.2 justificada:** 64, 50 000 y el timeout son límites de seguridad, no reglas deportivas; precedentes `MAX_SINGLE_ELIMINATION_TEAMS = 512` y topes de 64 (verificación constitucional).

## Usuarios

- **Espectador público:** abre la ficha del torneo y la alineación publicada. Necesita que la página cargue y que una foto caída no le oculte el resto del contenido.
- **Operador o administrador de organización:** gestiona plantillas y genera el calendario de una fase. Necesita que la generación termine o falle con un mensaje accionable, sin bloquear la aplicación ni dejar datos a medias.
- **Operador de plataforma:** despliega y opera. Necesita que una consulta desbocada no bloquee la base, que el pool esté dimensionado por proceso y que el agotamiento sea visible en los registros.
- **Mantenedor o desarrollador:** necesita pruebas deterministas que fijen los topes, el presupuesto, la frontera de transacción y la configuración efectiva sin depender de infraestructura.
- **Revisor humano de cambios:** necesita criterios verificables para aprobar el cambio conforme a la constitución.

## Roles y visibilidad

- **Público:** sigue viendo exactamente la misma información. `photo_url` continúa siendo `null` sin consentimiento o sin clave, y se mantiene la decisión de exponerla en la proyección/vista pública; la capa que firma no amplía ni reduce esa decisión. No aparecen documentos de identidad ni fechas de nacimiento.
- **Miembro y administrador de organización:** la plantilla del Workspace conserva sus campos y su contrato; solo cambia cuántas veces se construye el cliente, cómo se agrupan las firmas y dónde termina la transacción. Un fallo de almacenamiento sigue siendo visible (503).
- **Administrador de plataforma:** no interviene; no hay cambios en `/admin`.
- **Aislamiento entre organizaciones:** la firma opera sobre claves ya seleccionadas por consultas tenant con RLS y contexto fijado dentro de la transacción. El trabajo puro recibe datos ya filtrados y no consulta la base. La caché de clientes no contiene datos de ninguna organización, solo configuración de conexión al almacenamiento. La transacción de escritura del sorteo vuelve a fijar el contexto RLS antes de escribir.
- **Sin cambios de autorización:** no se añaden ni retiran permisos, membresías ni rutas.

## Historias de usuario

- **HU-1.** Como espectador, quiero que la ficha con muchas alineaciones cargue sin multiplicar el trabajo por jugador, para no quedarme con una página vacía por una foto.
- **HU-2.** Como operador de organización, quiero que una foto que no se puede firmar no me oculte el torneo ni la alineación publicada.
- **HU-3.** Como operador de organización, quiero que el sorteo Swiss termine siempre en un calendario válido o en un error claro, sin esperas impredecibles ni un 500 sin explicación.
- **HU-4.** Como operador de plataforma, quiero que ninguna consulta de la aplicación quede abierta indefinidamente y que el pool tenga un tamaño declarado y documentado, para que un pico no degrade la base ni todas las peticiones a la vez.
- **HU-5.** Como mantenedor, quiero pruebas que cuenten construcciones de cliente, despachos, evaluaciones de pares y transacciones abiertas durante la E/S, para verificar la mejora sin medir latencias.
- **HU-6.** Como revisor, quiero que el comportamiento ante fallo de firma, presupuesto agotado, timeout, transacción cortada y pool lleno esté escrito y sea comprobable, para aprobar sin inferencias.
- **HU-7.** Como operador de plataforma, quiero que el sorteo no detenga el resto de la API mientras calcula, para que una generación pesada no degrade las demás peticiones.

## Definiciones

- **Cliente de almacenamiento / cliente de firma:** objeto que habla con el almacenamiento S3-compatible. En esta spec, «cliente de firma» es el que genera URLs firmadas; construir uno tiene coste (carga de configuración y credenciales) y firmar con él no hace ninguna llamada de red.
- **Endpoint de firma efectivo:** URL con la que se firman los enlaces. Se resuelve hoy como `STORAGE_SIGNING_ENDPOINT_URL`, si está definido; si no, el esquema y host de `STORAGE_PUBLIC_BASE_URL`; y si tampoco, `STORAGE_ENDPOINT_URL` (`backend/app/core/storage.py:106-113`). Su resolución no cambia.
- **Endpoint de subida:** `STORAGE_ENDPOINT_URL`, usado por `put_bytes` y `delete_key`. Es distinto del de firma y **no** forma parte del requisito de caché; si el plan reutiliza también el cliente de subida, usa una clave de caché propia y no cambia su contrato.
- **Cliente de firma reutilizado:** cliente construido como máximo una vez por proceso (worker de uvicorn) y por endpoint de firma efectivo, conservado entre peticiones y usado por todas las firmas de ese endpoint. En producción con `API_WORKERS=2` hay hasta 2 construcciones en frío, una por proceso.
- **Pasada acotada:** recorrido único del conjunto de filas de una respuesta para resolver todas las firmas. Su coste depende de las filas, no de un bucle con una construcción o un despacho por fila.
- **Despacho off-thread:** entrega de trabajo de firma al ejecutor de hilos para no bloquear el bucle de eventos.
- **Clave de objeto repetida:** la misma clave de foto que aparece más de una vez dentro de la respuesta (por ejemplo, el mismo jugador en dos alineaciones). Se firma una vez y se reutiliza el resultado dentro de esa respuesta.
- **Transacción de lectura:** transacción que fija el contexto RLS, ejecuta las consultas del endpoint y termina (commit o cierre) antes de cualquier E/S o cálculo.
- **Transacción de escritura:** transacción posterior al cálculo, que vuelve a fijar el contexto RLS, revalida el permiso y las precondiciones y aplica los cambios de forma atómica. Solo se abre si el cálculo tuvo éxito.
- **Trabajo puro:** cálculo que no toca la base de datos, la red ni el reloj; recibe datos ya cargados y devuelve un resultado.
- **Compensación:** borrado con `delete_key` de los objetos subidos cuando el fallo es **inequívocamente anterior al commit** (validación, permiso o escritura). No cubre un fallo de firma posterior al commit ni un commit fallido o ambiguo: en el primer caso la fila queda creada y la respuesta es 503; en el segundo se conservan ambos objetos.
- **Commit confirmado:** la transacción de escritura terminó con éxito y la fila quedó confirmada. Solo entonces se borra el objeto anterior de una subida.
- **Commit fallido o ambiguo:** la transacción no confirma, pero el cliente no puede saber si llegó a confirmarse (por ejemplo, cancelación o fallo durante el `commit`). No se compensa el objeto nuevo ni se borra el anterior: se conservan ambos y el nuevo puede quedar huérfano.
- **Objeto huérfano:** objeto subido sin fila que lo referencie. Es un resultado **aceptado** de un commit fallido o ambiguo y de una importación cuyo commit falla; se prefiere un huérfano a una referencia rota y se limpia fuera de esta spec.
- **Tope de equipos Swiss:** número máximo de equipos de la fase admitidos para generar emparejamientos: **64**.
- **Conjunto contado del tope:** equipos de la fase cargados por `_load_registered_stage_teams` (`router.py:2014-2043`: `stage_teams` unido a `tournament_teams` con `status = 'registered'`, ordenado por `team_id`). Es el mismo conjunto que ya alimenta el sorteo; no se cuenta otra cosa.
- **Evaluación de par:** intento de emparejar dos equipos concretos dentro de la búsqueda o del fallback. Es la unidad del presupuesto porque es contable y determinista, a diferencia del tiempo de reloj.
- **Contador de presupuesto:** contador único por solicitud, que empieza en 0 y solo incrementa al evaluar un par candidato. Nunca se reinicia entre ramas, candidatos a descanso ni fases.
- **Límite de búsqueda (40 000):** valor del contador en el que la fase de backtracking deja de evaluar pares y cede al fallback.
- **Presupuesto total (50 000):** valor máximo del contador por solicitud, incluida la reserva del fallback (10 000 evaluaciones).
- **Fallback greedy:** emparejamiento alternativo, sin retroceso, que recorre los equipos en el mismo orden de prioridad y toma el primer candidato admisible según las restricciones vigentes. Su resultado es determinista.
- **Timeout de emparejamiento:** 10 000 ms desde el envío al ejecutor dedicado hasta obtener el resultado, incluida la espera en cola.
- **Resultado descartado:** resultado de un hilo cuyo timeout ya venció. No se escribe, no se reutiliza y no se comparte con la petición; el hilo termina por el presupuesto.
- **Error de emparejamiento:** resultado de negocio del cálculo (presupuesto agotado, sorteo imposible, timeout). No es un `ValueError` de validación de parámetros.
- **Error de validación existente:** `ValueError` por equipos insuficientes, equipos repetidos, semilla negativa, ronda no positiva o metas inválidas. Conserva su comportamiento actual y no se convierte en 409.
- **Error determinista:** respuesta 4xx con un mensaje estable y sin datos personales, idéntica para la misma entrada y los mismos límites.
- **Timeout de sentencia (`statement_timeout`):** tiempo máximo que PostgreSQL permite que dure una sentencia antes de cancelarla.
- **Timeout de transacción inactiva (`idle_in_transaction_session_timeout`):** tiempo máximo que una transacción puede estar abierta sin ejecutar sentencias antes de que el servidor la termine. Una conexión que espera una firma está *idle in transaction*, no activa.
- **Pool de conexiones:** conjunto de conexiones reutilizables con tamaño base (`pool_size`), desbordamiento máximo (`max_overflow`) y espera máxima para obtener una (`pool_timeout`). Los valores efectivos son los que la aplicación aplica al arrancar, no los defaults implícitos.
- **Agotamiento del pool:** situación en la que una petición no obtiene conexión dentro de `pool_timeout`; se manifiesta como `sqlalchemy.exc.TimeoutError` (no es un `DBAPIError`).
- **Valor efectivo:** valor que la conexión aplica realmente y que puede observarse en el servidor (`SHOW`) o en la configuración del engine, no el que figura en un documento.

## Requisitos funcionales

### RF-001 — Cliente de firma reutilizado por proceso y endpoint (R15)

CUANDO una petición necesita firmar una o varias fotos, EL SISTEMA usa un cliente de firma ya construido para el endpoint de firma efectivo y no construye uno nuevo por jugador.

*Criterios de aceptación:*
- Tras el primer uso, el número de construcciones de cliente de firma para un endpoint es **0**, con independencia del número de fotos. En frío es como máximo **1 por proceso y endpoint**; con `API_WORKERS=2` hay hasta 2 construcciones en frío, una por worker.
- **Índice de caché:** la clave es el endpoint de firma efectivo, no el de subida. Con dos endpoints de firma distintos configurados (por ejemplo, `STORAGE_SIGNING_ENDPOINT_URL` frente al derivado de `STORAGE_PUBLIC_BASE_URL`), cada uno tiene su propio cliente de firma y ninguno se usa para el otro. La prueba lo comprueba con dos valores distintos y verifica que el endpoint pedido al doble es el esperado en cada caso; no usa el endpoint de subida como segundo valor.
- La construcción es segura ante peticiones concurrentes: dos peticiones simultáneas en frío producen exactamente **1** cliente por endpoint. La prueba usa un constructor falso que bloquea hasta que la segunda petición está en curso, y cuenta construcciones. Un fallo al construir no deja la caché envenenada: la siguiente petición vuelve a intentarlo.
- Los endpoints de escritura o borrado (`put_bytes`, `delete_key`) no forman parte del requisito de **caché**; su implementación no cambia, pero sus **call sites** los mueven fuera de la transacción (RF-002). Si el plan los hiciera reutilizar un cliente, usaría una clave de caché por endpoint de subida y no cambiaría su contrato.
- El mecanismo es único para todos los endpoints que ya firmaban fotos (públicos y de Workspace), de modo que la corrección no queda limitada a una ruta. No cambia el contrato de ninguno.
- Los endpoints que no firman fotos no construyen cliente de firma.
- Se mantiene el comportamiento actual de validación de la clave antes de firmar (clave vacía, absoluta o con `..` produce error de almacenamiento y nunca una URL).
- **Credenciales:** el cliente cacheado conserva las credenciales resueltas al construirse. Rotarlas exige reiniciar el proceso; se documenta y no se implementa recarga en caliente.
- La prueba con un doble de S3 cuenta construcciones y demuestra: 0 con la caché caliente al firmar 100 claves; 1 en frío; 1 por endpoint de firma; 1 con dos peticiones concurrentes en frío; y reintento correcto tras un fallo de construcción.

### RF-002 — Fotos fuera de la transacción: firma en lote, subida y borrado (R15, N-2)

CUANDO una respuesta incluye N jugadores con consentimiento y clave de foto, EL SISTEMA resuelve sus `photo_url` en una pasada única sobre el conjunto de filas, con un número de despachos off-thread que no crece con N, **después** de cerrar la transacción de lectura y antes de construir la respuesta. CUANDO se sube o se borra una foto, EL SISTEMA realiza esa E/S fuera de cualquier transacción.

*Criterios de aceptación:*
- El número de despachos off-thread por respuesta es **O(1)** (como máximo un lote), no uno por fila. La prueba lo cuenta con un doble.
- El número de firmas por respuesta es como máximo el de claves distintas de la respuesta: una clave repetida se firma una vez y comparte resultado.
- **Frontera de transacción (N-2):** en el momento de invocar al almacenamiento, la sesión de base de datos del endpoint **no tiene una transacción abierta** (`in_transaction()` es falso) y la conexión no está *idle in transaction*. Ninguna firma, subida (`put_bytes`) ni borrado (`delete_key`) ocurre con una transacción abierta.
- **Orden de la firma:** consultas y RLS dentro de la transacción → commit o cierre → firmas → respuesta. Se verifica con un doble de sesión o una función extraída que reciba la sesión y el firmante; el doble registra `in_transaction()` en el instante de la firma.
- **Importación:** las fotos se suben **antes** de la transacción de escritura. SI el fallo es inequívocamente anterior al commit (una subida posterior, validación, permiso o error de escritura), ENTONCES los objetos subidos se compensan con `delete_key`. SI el commit falla o es ambiguo, ENTONCES no se compensan: pueden quedar objetos huérfanos (best-effort, sin filas confirmadas). Si la firma posterior al commit falla, no se borra el objeto nuevo ni se revierte la fila y la respuesta es 503.
- **Subida individual, commit confirmado:** lectura → `put_bytes` fuera → escritura → **commit confirmado** → borrado del objeto anterior → firma. El borrado del anterior no depende del éxito de la firma.
- **Subida individual, commit fallido o ambiguo:** si la transacción no confirma pero no se puede saber si llegó a confirmarse (cancelación o fallo durante el `commit`), se conservan el objeto anterior y el nuevo; el nuevo puede quedar huérfano. No se compensa y no se borra el anterior: se prefiere un huérfano a una referencia rota.
- **Subida individual, fallo anterior al commit:** si la validación, el permiso o la escritura fallan de forma inequívoca antes del commit y el objeto nuevo ya se subió, se compensa con `delete_key`. La cancelación durante el borrado del objeto anterior se propaga y no se silencia.
- **Retirada de consentimiento:** el borrado del objeto ocurre fuera de la transacción, tras un commit confirmado; la respuesta no firma una foto sin consentimiento.
- El orden de las filas, sus campos y el valor de `photo_url` por jugador son idénticos a los actuales para las mismas entradas. Se verifica con un caso de referencia que compara la respuesta completa antes y después del cambio (mismos identificadores, mismos campos, mismas URLs y mismo orden de claves).
- Con N = 0 (ningún jugador con consentimiento y clave) no se construye cliente, no se despacha trabajo y no se registra error.
- Los límites de paginación existentes acotan N; no se añaden ni se reducen límites.
- Si el plan necesita una consulta adicional después de cerrar la transacción, abre una transacción nueva, vuelve a fijar el contexto RLS y no reutiliza el contexto anterior (que era local a la transacción).
- La prueba cubre los dos call sites de firma (alineaciones públicas y plantilla del Workspace) y los de subida/borrado, y demuestra la misma política y la misma frontera en todos.

### RF-003 — Privacidad y contrato público sin cambios (R15)

CUANDO se sirve una proyección pública, EL SISTEMA mantiene exactamente la política de privacidad vigente: `photo_url` solo si la plantilla tiene consentimiento de imagen, sin documentos de identidad ni fechas de nacimiento.

*Criterios de aceptación:*
- La decisión de exponer la foto sigue tomándola la proyección/vista que ya la toma (el valor llega nulo sin consentimiento) y la capa de firma no la altera: no firma una clave nula, vacía o ausente ni inventa una.
- Un jugador sin consentimiento o sin clave devuelve `photo_url: null` y no consume ninguna firma.
- No se añaden, renombran ni reordenan campos públicos; `photo_url` sigue siendo cadena o `null`. No se añade un campo de «foto no disponible» ni un estado nuevo.
- Las vistas, los `GRANT` y el modelo RLS no cambian. No hay migraciones.
- Ningún registro de esta funcionalidad incluye claves de objeto con identificadores de organización, nombres de jugadores, documentos ni fechas.

### RF-004 — TTL y fallo de firma (R15)

CUANDO una firma falla, EL SISTEMA degrada la foto a `null` en los endpoints públicos, mantiene el 503 en los del Workspace y registra el fallo una sola vez por respuesta, sin datos personales. La URL firmada conserva el TTL vigente.

*Criterios de aceptación:*
- El TTL sigue siendo `STORAGE_PRESIGN_SECONDS` (`backend/app/core/config.py:54`: default 300, rango 60-3600, documentado en `.env.example:43`). No se añade variable nueva, no cambia el default ni el rango, y una URL firmada caduca igual que hoy.
- **Público (sin sesión), decisión P-3:** si una o varias firmas fallan, la respuesta se sirve completa con `photo_url: null` en las fotos afectadas y conserva el resto de campos y de jugadores. El código es el de éxito de la operación (200), no un error.
- **Workspace (con sesión y permiso de gestión):** se conserva el comportamiento actual: 503 con detalle genérico («El almacenamiento de fotos no está disponible») y sin datos internos. No se degrada a `null`.
- Un fallo de firma nunca invalida el resto de la respuesta en el camino público: los demás jugadores conservan su `photo_url`.
- El fallo se registra **una vez por respuesta** en ambos caminos, con un mensaje estable y el número de fotos no firmadas; nunca una entrada por fila ni por jugador.
- No hay reintentos automáticos dentro de la petición: la siguiente petición vuelve a intentar la firma.
- Un proveedor de almacenamiento no soportado o una clave inválida se resuelven con la misma política que un fallo de firma (degradación en público, 503 en Workspace).
- **Punto de prueba (B-10):** un test de endpoint con `get_db` sustituido y un doble de almacenamiento que lanza, que demuestra público → 200 con `null` y Workspace → 503; más la prueba unitaria del resolvedor con firmante inyectado. No basta con probar el resolvedor aislado.

### RF-005 — Tope, presupuesto determinista y ejecución fuera del event loop (R16, N-1, N-2)

CUANDO se solicita generar una ronda Swiss, EL SISTEMA valida el tope de equipos, ejecuta el emparejamiento en un hilo aparte con un presupuesto determinista y un timeout de seguridad, y no lo ejecuta dentro del event loop ni de una transacción.

*Criterios de aceptación:*
- **Tope (P-1):** se rechaza con **422** y el mensaje «La fase Swiss admite como máximo 64 equipos» cualquier fase cuyo conjunto contado (definición) supere **64 equipos**. El rechazo ocurre antes de cualquier escritura y antes de enviar trabajo al ejecutor. Una fase con exactamente 64 equipos se acepta.
- El tope se aplica igual en la ronda 1 y en las rondas posteriores. En rondas > 1 **no se borran** marcadores ni partidos anteriores: el tope solo decide si se genera la ronda solicitada.
- El tope, el presupuesto y el timeout son **constantes del backend** (P-1, N-1). No se añade ninguna variable de entorno y el diff no toca `docker-compose.yml`, `docker-compose.production.yml` ni `.env.example`.
- **Contador único (B-1):** hay un solo contador por solicitud, que empieza en 0. Incrementa **exactamente 1** por cada par candidato `(primero, segundo)` que la búsqueda o el fallback examinan, inmediatamente antes de comprobar su admisibilidad. No incrementan la ordenación, las comparaciones, la selección de descanso, la validación de parámetros ni las opciones de orientación de un par ya contado. El contador **no se reinicia** entre ramas del backtracking, entre candidatos a descanso (campo impar) ni al cambiar al fallback.
- **Consumo (B-1):** la fase de backtracking deja de evaluar pares cuando el contador llega a **40 000** (la evaluación que lo lleva a 40 000 se realiza; la 40 001 no). El fallback continúa desde el valor actual del mismo contador y puede llegar hasta **50 000** (la 50 000 se realiza; la 50 001 no). El total por solicitud nunca supera 50 000.
- **Determinismo:** el resultado (parejas, orientación local/visitante, descanso y valor final del contador) depende solo de la entrada y de las constantes. Dos ejecuciones con la misma entrada producen el mismo resultado y el mismo valor de contador. El timeout es una red de seguridad y no forma parte del resultado normal.
- **Fuera del event loop (N-1):** el cálculo se envía a un ejecutor dedicado y acotado de **2 hilos**, distinto del ejecutor por defecto que atiende la firma de fotos. Mientras calcula, el event loop sigue atendiendo otras peticiones; una prueba con un emparejamiento lento controlado demuestra que otra corrutina progresa antes de liberar el resultado.
- **Timeout (N-1):** 10 000 ms desde el envío hasta el resultado, incluida la espera en cola. Al vencer, la petición responde **409** con el mensaje «tiempo máximo de cálculo del sorteo excedido», el resultado se descarta y se registra a nivel `error` como anomalía (no se espera dentro del presupuesto). El hilo no se cancela: continúa hasta agotar el presupuesto y termina; su resultado no se escribe, no se reutiliza y no comparte estado con la petición.
- **Fuera de la transacción (N-2):** el cálculo recibe datos ya cargados (identificadores, historial, standings, conteos y semilla) y no recibe sesión, conexión ni objetos del event loop. En el instante de enviar el trabajo, la transacción de lectura ya terminó; ninguna transacción permanece abierta mientras se calcula.
- **Salida idéntica dentro del presupuesto:** para toda entrada que hoy encuentra solución sin agotar el presupuesto, el resultado es idéntico al actual (mismas parejas, misma orientación, mismo descanso y mismo orden). Se fija con regresión sobre los casos existentes, incluido el formato de 36 equipos (`backend/tests/test_tournament_scheduling.py:208-235`) y el descanso del campo impar (`:238-254`).
- **Validación:** los parámetros siguen validándose igual (mínimo de equipos, equipos repetidos, semilla no negativa, ronda positiva, metas de local/visitante) y esos `ValueError` conservan su comportamiento actual (definición «error de validación existente»).
- Las pruebas cubren los valores **39 999/40 000/40 001** (cambio de fase) y **49 999/50 000/50 001** (límite total) con un doble que cuenta evaluaciones, sin depender de tiempos reales.

### RF-006 — Fallback acotado, errores deterministas y ninguna escritura confirmada (R16, N-2)

SI la búsqueda por backtracking agota su límite, ENTONCES EL SISTEMA intenta un fallback greedy acotado; SI el fallback no produce un emparejamiento completo, ENTONCES EL SISTEMA responde con **409** determinista y no con un 500. SI el permiso de gestión se revoca antes de la escritura, ENTONCES responde **403** y no escribe. En ningún caso se confirma una escritura.

*Criterios de aceptación:*
- El fallback recorre los equipos con `candidate_key` (puntuación, victorias, ranking, orden por semilla), **el mismo orden de prioridad que la búsqueda**, y **mantiene la restricción de no repetir rivales** y las metas de local/visitante cuando se hayan configurado (P-2). No relaja ninguna restricción en ningún caso.
- El fallback no retrocede, consume del mismo contador y no tiene bucles sin cota ni reintentos.
- El fallback es determinista: misma entrada, mismas parejas y mismo descanso.
- **Clasificación (B-7 y H1):**
  - `no_valid_pairing` **solo** si la búsqueda terminó **sin** alcanzar sus 40 000 y sin solución; en ese caso el fallback no se ejecuta porque la búsqueda completa ya es concluyente. → **409** «no existe un sorteo válido sin repetir rivales».
  - `budget_exhausted` en cualquier corte por presupuesto: la búsqueda alcanzó 40 000 y el fallback no completó (aunque no llegue a 50 000), o el contador alcanzó 50 000. → **409** «presupuesto de emparejamiento agotado».
  - El timeout de 10 000 ms venció antes de cualquiera de los dos resultados → **409** «tiempo máximo de cálculo del sorteo excedido», registrado a nivel `error`.
  - Un `ValueError` de validación existente **no** se convierte en 409: conserva su comportamiento actual (si llegara a la respuesta, seguiría siendo el 500 actual, sin datos internos).
- **Sin escrituras confirmadas (B-6 y N-2):** el cálculo termina antes de abrir la transacción de escritura. La transacción de escritura solo se abre si el emparejamiento tuvo éxito y, si falla, no se emitió ningún `INSERT`/`UPDATE`; el rollback sigue siendo la red de seguridad. No se exige reordenar el flujo funcional más allá de esta frontera.
- **Atomicidad:** en la ronda 1, los marcadores y sus parejas se crean y actualizan en la misma transacción de escritura, después del cálculo. En rondas > 1 se actualizan solo los marcadores existentes. Un fallo en la escritura revierte todo.
- **Permiso en la escritura (H3):** después de `set_rls_context` y **antes** de la revalidación de estado, la transacción de escritura revalida el permiso de gestión (el mismo que exige el endpoint). SI se revocó, ENTONCES responde **403** y no escribe nada.
- **Revalidación de estado (N-2):** tras el permiso, la transacción de escritura comprueba que el estado no cambió desde la lectura (ronda 1: la fase sigue sin partidos; rondas > 1: los marcadores siguen `cancelled` y las rondas previas siguen terminadas). SI cambió, ENTONCES responde **409** «el estado de la fase cambió durante el sorteo; vuelve a intentarlo» y no escribe nada.
- El error no expone equipos, organizaciones ni datos personales.
- Las pruebas cubren: agotamiento con solución existente (el fallback la encuentra); presupuesto agotado sin solución → 409 de presupuesto; fallback fallido tras agotar la búsqueda → 409 de presupuesto, **no** de sorteo imposible; sorteo imposible (búsqueda completa sin límite) → 409 distinto, no 500; timeout (409 propio y registro de error); permiso revocado (403 y sin escrituras); estado cambiado (409 y sin escrituras); y que ningún caso de fallo deja filas nuevas o modificadas.

### RF-007 — Nada de escrituras parciales ni cambios de esquema

EL SISTEMA satisface R15, R16 y R17 sin migraciones, sin cambios de esquema y sin cambios de contrato más allá de lo que esta spec autoriza.

*Criterios de aceptación:*
- El diff no incluye archivos de `infra/postgres/migrations/` ni de `infra/postgres/init/`.
- No cambian tablas, políticas RLS, privilegios del rol de aplicación ni vistas públicas.
- No cambian rutas, permisos, nombres de campos, **esquemas de respuesta** ni el seed de demostración. Los únicos cambios observables son los códigos 422/409/503, la degradación a `null` en público, los timeouts y el pool.
- No se añaden dependencias a `backend/requirements.txt`. Las versiones de referencia (`sqlalchemy 2.1.4`, `asyncpg 0.32.0`, `boto3 1.43.113`) se mantienen.
- **Sin configuración nueva (P-1, P-4):** no se añaden variables de entorno; el diff no toca `docker-compose.yml`, `docker-compose.production.yml` ni `.env.example`. El tope Swiss, el presupuesto, el timeout, los timeouts de sesión y el pool viven como constantes del backend.

### RF-008 — Timeouts de sesión en la conexión de la aplicación (R17)

CUANDO la aplicación abre una conexión a la base de datos, EL SISTEMA aplica un `statement_timeout` y un `idle_in_transaction_session_timeout` explícitos, de modo que ninguna sentencia ni ninguna transacción inactiva quede abierta indefinidamente.

*Criterios de aceptación:*
- Toda conexión obtenida del engine de la aplicación lleva `statement_timeout` de **15 000 ms** e `idle_in_transaction_session_timeout` de **30 000 ms** (P-4), como constantes del backend.
- El valor es efectivo, no declarativo: en la suite con base de datos (opt-in, `RUN_DATABASE_TESTS=1`) `SHOW statement_timeout` y `SHOW idle_in_transaction_session_timeout` devuelven `15s` y `30s` sobre una conexión del engine de la aplicación.
- Sin PostgreSQL real, una prueba unitaria verifica que la configuración de conexión del engine incluye ambas claves con los valores esperados; si el mecanismo elegido no es inspeccionable, se documenta y se cubre con la prueba opt-in, sin declarar verificado lo que no se ejecutó.
- Los timeouts aplican por igual a la API, al worker del outbox y al seed de desarrollo, porque comparten engine. El backfill operativo `scripts.encrypt_birth_dates` usa su propia conexión administrativa y no queda gobernado por estos valores; se documenta esa diferencia.
- La suite opt-in existente construye su propio engine para las fixtures (`backend/tests/conftest.py:49`) y no se ve afectada; las rutas que usan `get_db`/`SessionFactory` sí quedan gobernadas por los timeouts. Ninguna prueba existente afirma su ausencia, así que no hay contradicción que corregir.
- **Conexión cortada por inactividad (B-2):** si una conexión queda *idle in transaction* más de 30 s, el servidor la termina. La siguiente sentencia falla como error de base de datos: la petición recibe el **500 saneado** actual (sin SQL ni parámetros) y se registra el SQLSTATE; el pool descarta la conexión. Con N-2 esto no ocurre en los caminos de fotos ni de emparejamiento, y se declara como riesgo residual para caminos no tocados.
- Un timeout de sentencia se manifiesta como el **500 saneado actual** (P-5), sin SQL, sin parámetros y sin fila, y con una entrada de registro con el SQLSTATE; no como una traza expuesta. No se introduce un manejador nuevo para este caso.
- La suite existente de errores saneados (`backend/tests/test_error_sanitization.py`) sigue pasando sin cambios de expectativas.
- **Decisión sobre el seed y la suite (B-13):** se aceptan y documentan. Un fallo por 15 s en el seed de desarrollo o en una prueba opt-in se trata como defecto del seed (batching) o de la prueba, y **no** como motivo para elevar la constante; corregirlo sería otro cambio.

### RF-009 — Pool dimensionado y agotamiento observable (R17)

CUANDO la aplicación necesita una conexión, EL SISTEMA usa un pool con tamaño, desbordamiento y espera máximos explícitos; SI el pool se agota, ENTONCES EL SISTEMA responde de forma definida y lo registra.

*Criterios de aceptación:*
- El engine declara `pool_size=10`, `max_overflow=10` y `pool_timeout=10` segundos (P-4), como constantes del backend. `pool_pre_ping` se conserva.
- Una prueba unitaria verifica el tamaño efectivo del pool, el desbordamiento máximo y la espera máxima del engine, de modo que un cambio accidental de defaults se detecte sin base de datos.
- **Condición observable (B-14):** el agotamiento se manifiesta como `sqlalchemy.exc.TimeoutError` del pool («QueuePool limit … connection timed out»), que **no** es un `DBAPIError` y por tanto no lo cubre el manejador actual. Se clasifica como **capacidad transitoria** y se mapea a **503** con el detalle genérico «Servicio temporalmente no disponible», sin SQL, sin parámetros y sin nombre de la base.
- **Una sola regla de registro (B-15, corrige la contradicción anterior):** se emite **exactamente una** entrada de aviso por cada petición que falla al adquirir conexión. No se emite ninguna por las peticiones que esperan y luego obtienen conexión, ni una por conexión en espera, ni una por reintento. El mensaje es estable y no incluye datos de la consulta.
- Los valores efectivos de timeouts y pool se registran **una vez al arrancar** (solo números y nombres de parámetro, sin credenciales ni cadena de conexión), para que el operador pueda confirmarlos sin leer el código.
- El agotamiento no se reintenta automáticamente en la misma petición: devuelve el error definido y la siguiente petición vuelve a intentar.
- **Agregado de conexiones (B-11):** el dimensionado es **por proceso**: cada worker de la API y el worker del outbox tienen su propio engine y su propio pool (hasta 20 conexiones cada uno). Con `API_WORKERS=2` y un worker: 2 × 20 + 20 = **60** conexiones teóricas, frente a las 100 por defecto de PostgreSQL, con 40 de margen para migraciones y administración. Si se sube `API_WORKERS` o se reduce `max_connections`, debe revisarse ese agregado; esta spec no cambia P-4. Se documenta en `README.md`/`AGENTS.md` (RF-011).
- **Backfill operativo:** `scripts.encrypt_birth_dates` usa su propia conexión administrativa (`DATABASE_ADMIN_URL`) y **no hereda** el pool ni los timeouts de la aplicación; no puede fallar por ellos. Se documenta.
- La prueba cubre el agotamiento con un pool de tamaño 1 y dos adquisiciones concurrentes. Si se hace con un doble que lanza `sqlalchemy.exc.TimeoutError`, es unitaria; si exige conexiones reales, se marca como opt-in y no se declara verde por inferencia.
- La prueba verifica además que el camino de éxito no emite avisos y que una petición fallida emite exactamente una entrada.

### RF-010 — Pruebas y verificación en CI

CUANDO se ejecutan las verificaciones del proyecto, EL SISTEMA prueba el comportamiento nuevo en los jobs existentes, sin añadir servicios de infraestructura a CI, y distingue lo unitario de lo opt-in.

*Criterios de aceptación:*
- **Unitarias (dobles, overrides y funciones puras; sin PostgreSQL ni S3 reales), en el job `backend`:**
  1. Cliente de firma: 0 con caché caliente, 1 en frío, 1 por endpoint de firma, **1 con dos peticiones concurrentes**, reintento tras fallo.
  2. Lote de fotos: O(1) despachos, una firma por clave repetida, N = 0 sin trabajo, orden/campos/valores de `photo_url` idénticos a la referencia.
  3. Clave inválida (vacía, absoluta, `..`) rechazada antes de firmar.
  4. Frontera de transacción en fotos: el doble de sesión registra `in_transaction() == False` al firmar, en los dos call sites.
  5. Fallo de firma: público → 200 con `null`; Workspace → 503; un solo registro por respuesta; sin datos personales.
  6. TTL: la firma usa `STORAGE_PRESIGN_SECONDS`.
  7. Consentimiento: sin consentimiento no hay firma y `photo_url` es `null`.
  8. Swiss: 64 equipos aceptados; 65 → 422 antes de escribir; conjunto contado según la definición.
  9. Swiss: incremento y consumo del contador; fronteras **39 999/40 000/40 001** y **49 999/50 000/50 001**; determinismo con dos ejecuciones y mismo valor de contador.
  10. Swiss: regresión de los casos actuales (36 equipos y descanso del campo impar).
  11. Swiss: agotamiento con solución → fallback; sin solución → 409 de presupuesto; sorteo imposible → 409 distinto; timeout → 409 propio; validación existente sin cambios.
  12. Swiss: el cálculo corre en el ejecutor dedicado y el event loop progresa mientras un cálculo lento controlado está en curso.
  13. Swiss: sin escrituras en ningún fallo y revalidación con estado cambiado → 409.
  14. Engine: timeouts y pool con los valores declarados.
  15. Pool: `sqlalchemy.exc.TimeoutError` → 503 y exactamente un aviso por petición fallida; ninguna en el camino de éxito.
- **Opt-in (`RUN_DATABASE_TESTS=1`), con PostgreSQL real:**
  1. `SHOW statement_timeout` y `SHOW idle_in_transaction_session_timeout` sobre una conexión del engine de la aplicación.
  2. Frontera de transacción con una sesión real: al firmar (con firmante falso) `in_transaction()` es falso y la conexión no queda *idle in transaction*.
  3. Ningún fallo de emparejamiento deja filas nuevas o modificadas (conteo antes/después).
  4. Aislamiento: la organización A no puede leer ni escribir la fase de la organización B en la transacción de lectura ni en la de escritura, y el contexto RLS se vuelve a fijar en la segunda.
- Las pruebas no dependen de red, reloj, orden no determinista ni de S3 real; usan dobles y contadores. El timeout del emparejamiento se prueba con un doble que no termina y un reloj controlado, o con un límite inyectado; no se mide latencia real.
- Los comandos de verificación local son los mismos que los de CI y deben pasar:
  ```sh
  cd backend && pytest -q
  cd backend && python -m compileall -q app
  ```
  No se toca el frontend ni Compose, así que `pnpm test`/`pnpm run typecheck`/`pnpm run build` y `docker compose config -q` **no** aplican. Si el plan descubriera que necesita tocar cualquiera de los dos, sería una desviación: se detiene y se pregunta antes de implementar.
- No se añaden servicios ni jobs a `ci.yml`; los jobs son los de la §4 de la constitución (`backend`, `frontend`, `infrastructure`, `security` y, desde la enmienda 1.4.0, `e2e`).
- Si alguna verificación no puede ejecutarse en el entorno local, se declara expresamente en la evidencia; no se infiere el verde.

### RF-011 — Documentación de los cambios observables (B-3)

CUANDO se cierre el cambio, EL SISTEMA documenta en `README.md` y `AGENTS.md` los comportamientos que un operador o un revisor necesitan conocer, sin obligarlos a leer el código.

*Criterios de aceptación:*
- `README.md` y `AGENTS.md` documentan: el tope de 64 equipos, el presupuesto de 50 000 evaluaciones, el límite de búsqueda de 40 000, el timeout de 10 000 ms y que el cálculo corre en un hilo aparte con resultado descartable.
- Documentan los códigos y mensajes nuevos: **422** por tope, **409** por presupuesto agotado, sorteo imposible, timeout de cálculo y estado cambiado; y que los `ValueError` de validación existentes conservan su comportamiento.
- Documentan la degradación de fotos: `photo_url: null` en público ante fallo de almacenamiento y 503 en Workspace, con un solo registro por respuesta.
- Documentan los timeouts de sesión (15 s y 30 s), el pool (10 + 10, espera 10 s), el **503** por agotamiento del pool, el agregado de conexiones por proceso (60 con `API_WORKERS=2` y un worker frente a 100 por defecto) y la necesidad de **reiniciar el proceso al rotar credenciales de almacenamiento** por el cliente cacheado.
- Documentan que ninguna firma de fotos ni emparejamiento ocurre dentro de una transacción, y que el contexto RLS es local a cada transacción.
- No se documenta ninguna variable de entorno nueva ni se modifica `.env.example`.
- `MEMORY.md` registra el cierre con la evidencia, sin secretos ni datos personales.
- No se declara resuelto ningún hallazgo distinto de R15, R16 y R17.

## Requisitos no funcionales

- **RNF-001. Mejora medible sin infraestructura.** El criterio de éxito son contadores deterministas: construcciones de cliente por proceso, despachos off-thread por respuesta, firmas por clave distinta, evaluaciones de pares por solicitud y transacciones abiertas durante la E/S (debe ser 0). No se fijan latencias, ni objetivos de milisegundos, ni comparaciones contra un entorno real.
- **RNF-002. Determinismo.** La misma entrada produce el mismo calendario, el mismo error y el mismo valor final del contador, con independencia del hardware, del orden de iteración de diccionarios y del reloj. El timeout es una anomalía operativa, no una fuente de variación del resultado normal.
- **RNF-003. Fallo cerrado, acotado y sin bloqueo del event loop.** Un presupuesto agotado, un sorteo imposible, un timeout, un fallo de firma o un pool agotado tienen comportamiento definido y acotado; ninguno deja escrituras confirmadas, ni bloquea el event loop, ni devuelve datos internos. El timeout acota la espera del cliente a 10 s aunque el hilo termine poco después por el presupuesto.
- **RNF-004. Privacidad.** La capa nueva no amplía la exposición: sin consentimiento no hay foto, y ni los registros ni las respuestas nuevas incluyen documentos, fechas de nacimiento, nombres ni claves de objeto con identificadores de organización.
- **RNF-005. Compatibilidad.** El contrato público y el del Workspace no cambian más allá de los códigos y la degradación documentados; los consumidores actuales siguen funcionando. Un despliegue con la configuración anterior no requiere pasos manuales: no hay variables nuevas ni cambios de Compose.
- **RNF-006. Observabilidad mínima y segura.** Los valores efectivos de timeouts y pool se registran al arrancar una vez; el agotamiento, los fallos de firma, el timeout de cálculo y la conexión cortada por inactividad se registran con mensajes estables, sin SQL, sin credenciales y sin datos personales.
- **RNF-007. Sin dependencias nuevas.** No se añaden paquetes; se usan las capacidades ya presentes en SQLAlchemy, asyncpg, boto3 y la biblioteca estándar (hilos y ejecutores). Versiones fijadas en `backend/requirements.txt:3-4,14`.
- **RNF-008. Trazabilidad.** La spec, la evidencia y `MEMORY.md` registran las decisiones adoptadas, los comandos ejecutados y lo que no pudo verificarse.

## Datos personales y privacidad

**Aplica a fotos de jugadores.** El cambio no altera qué datos se tratan ni con qué base: la foto se sigue publicando solo si la plantilla tiene consentimiento de imagen, y la decisión sigue viviendo en la proyección pública (el valor llega nulo sin consentimiento, `infra/postgres/migrations/015_player_catalog_tenant_isolation.sql:435,474`). Lo que cambia es cómo y cuándo se construye el enlace: se reutiliza el cliente de firma, se agrupan las firmas y se hacen fuera de la transacción, sin ampliar el conjunto de claves firmadas ni el de jugadores expuestos.

- La URL firmada es un enlace temporal al objeto; no contiene documentos ni fechas de nacimiento. El TTL se mantiene en `STORAGE_PRESIGN_SECONDS` (300 s por defecto).
- No se registran claves de objeto, nombres, documentos ni fechas. Los avisos nuevos se limitan a un mensaje estable, un número de fotos no firmadas y, en el caso de base de datos, el SQLSTATE.
- La caché de clientes contiene solo configuración de conexión al almacenamiento (endpoint, región, credenciales de servicio); no contiene datos de jugadores ni de organizaciones y no se comparte entre organizaciones porque no indexa por organización. Rotar sus credenciales exige reiniciar el proceso.
- El trabajo puro del sorteo recibe identificadores de equipos y datos de clasificación ya filtrados por RLS; no recibe datos personales de jugadores.
- No se modifica el consentimiento, ni su retirada, ni las vistas públicas, ni el modelo RLS.

## Medición y evidencia

| Métrica | Hoy (verificado en código) | Objetivo de la spec | Cómo se verifica |
|---|---|---|---|
| Construcciones de cliente por respuesta pública | Una por jugador; cota teórica 100 000 (`router.py:3142`, `limit` 500 × 2 × 100) | 0 con caché caliente; 1 por proceso y endpoint en frío (2 con `API_WORKERS=2`) | Contador en el doble de S3 (RF-001) |
| Despachos off-thread por respuesta | Uno por jugador (`storage.py:121-126`) | O(1): un lote | Contador en el doble (RF-002) |
| Firmas por clave repetida | Una por aparición | Una por clave distinta de la respuesta | Contador por clave (RF-002) |
| Transacciones abiertas durante firma, subida, borrado o emparejamiento | 1 (firma y subida dentro de la transacción implícita; sorteo dentro de `db.begin()`) | 0 | Doble de sesión: `in_transaction()` falso (RF-002, RF-005, RF-010) |
| Bloqueo del event loop durante el sorteo | El cálculo corre en el event loop | 0: ejecutor dedicado de 2 hilos | Prueba de progreso concurrente (RF-005) |
| Coste del Swiss | Sin cota; backtracking con multiplicación por candidato a descanso (`scheduling.py:269-290,304-308`) | ≤ 64 equipos, ≤ 40 000 en búsqueda y ≤ 50 000 totales por solicitud (P-1, N-1) | Contador de evaluaciones (RF-005) |
| Espera máxima del sorteo | Sin cota | 10 000 ms; al vencer, 409 y resultado descartado | Doble con reloj controlado (RF-005) |
| Fallo del sorteo sin solución | 500 (no hay manejador de `ValueError`, `main.py:594-595`) | 409 determinista y distinguible (P-2) | Prueba de endpoint (RF-006) |
| `statement_timeout` | Sin definir (default del servidor: 0) | 15 000 ms efectivos (P-4) | `SHOW` opt-in + configuración del engine (RF-008) |
| `idle_in_transaction_session_timeout` | Sin definir | 30 000 ms efectivos (P-4) | `SHOW` opt-in + configuración del engine (RF-008) |
| Pool | Defaults implícitos 5 + 10, espera 30 s (`database.py:12`) | 10 + 10, espera 10 s, explícitos; 60 conexiones teóricas con `API_WORKERS=2` (P-4) | Inspección del engine (RF-009) |
| Agotamiento del pool | Sin comportamiento definido; no es `DBAPIError` | `sqlalchemy.exc.TimeoutError` → 503 + un aviso por petición (P-5) | Doble con pool de tamaño 1 (RF-009) |

Las cifras de la columna «Hoy» son cotas derivadas del código y de los límites de paginación, no mediciones de latencia. No se declara ninguna mejora de tiempo.

## Casos límite

1. **Respuesta sin fotos (N = 0):** no se construye cliente, no se despacha trabajo y no se registra nada.
2. **Misma clave repetida en la respuesta:** se firma una vez; todas las apariciones comparten la misma URL.
3. **Jugador sin consentimiento o sin clave:** `photo_url` nulo, ninguna firma, ningún error.
4. **Fallo al construir el cliente de firma:** no se cachea el fallo; la siguiente petición reintenta. La respuesta sigue RF-004.
5. **Fallo al firmar una clave entre varias:** en público el resto se sirve completo con `null` en las afectadas; en Workspace responde 503. Un registro por respuesta.
6. **Dos endpoints de firma configurados:** un cliente de firma por endpoint; nunca se firma con el endpoint del otro. El endpoint de subida no cuenta como segundo endpoint.
7. **Proveedor de almacenamiento no soportado:** error de almacenamiento, tratado como fallo de firma; no se construye cliente.
8. **Clave inválida (vacía, absoluta o con `..`):** error antes de firmar; nunca se devuelve una URL.
9. **Dos procesos de API (`API_WORKERS=2`):** cada worker construye su cliente en frío; son 2 construcciones por endpoint en total, no una. El criterio «1» es por proceso.
10. **Rotación de credenciales de almacenamiento:** el cliente cacheado sigue usando las credenciales anteriores hasta reiniciar el proceso. Se documenta; no hay recarga en caliente.
11. **Firma o subida en un camino futuro que no respete N-2:** si un camino nuevo vuelve a firmar, subir o borrar con la transacción abierta, la conexión queda *idle in transaction* (no activa). Pasados 30 s, el servidor la corta; la petición recibe el 500 saneado y se registra el SQLSTATE. En los caminos de esta spec no ocurre.
12. **Fase Swiss con exactamente 64 equipos:** aceptada.
13. **Fase Swiss con 65 equipos o más:** 422 antes de cualquier escritura y antes de enviar trabajo al ejecutor.
14. **Conjunto contado:** se cuenta solo lo que devuelve `_load_registered_stage_teams` (equipos `registered` de la fase). Equipos del torneo no asignados a la fase no cuentan.
15. **Ronda > 1 con 64 equipos:** se genera con el mismo tope; los marcadores y partidos de rondas anteriores no se borran.
16. **Equipos duplicados en la entrada del cálculo:** se conserva el `ValueError` de validación actual; no se convierte en 409 y no se ejecuta el presupuesto.
17. **Contador justo en 40 000 durante la búsqueda:** la evaluación 40 000 se realiza; no se evalúa la 40 001. Se pasa al fallback con el contador en 40 000.
18. **Contador justo en 50 000 en el fallback:** la evaluación 50 000 se realiza; la 50 001 no. Sin emparejamiento completo → 409 de presupuesto.
19. **Búsqueda y fallback terminan sin alcanzar sus límites y no hay emparejamiento:** 409 de sorteo imposible, distinto del de presupuesto.
20. **Presupuesto agotado con solución existente:** el fallback la encuentra dentro de la reserva y el calendario es válido.
21. **Timeout de 10 000 ms antes del resultado:** 409 de tiempo máximo, resultado descartado y registro de anomalía. El hilo sigue hasta agotar el presupuesto; no escribe ni comparte estado.
22. **Ejecutor dedicado ocupado (dos cálculos en curso):** la siguiente petición espera y su timeout de 10 s cuenta desde el envío; si vence, 409 de tiempo máximo y su resultado se descarta. El ejecutor tiene un número fijo de hilos; la cola no se dimensiona en esta spec y la cota efectiva es el timeout por petición más el presupuesto por cálculo.
23. **Estado de la fase cambiado entre lectura y escritura:** 409 «el estado de la fase cambió durante el sorteo» y ninguna escritura.
24. **Fallo de escritura después de un cálculo correcto:** la transacción revierte; no queda un calendario parcial.
25. **Ronda 1:** los marcadores y las parejas se crean en la transacción de escritura, después del cálculo; un fallo no deja marcadores.
26. **Seed de desarrollo con los timeouts nuevos:** se acepta y documenta. Si una sentencia excede 15 s, se trata como defecto del seed (batching) y no se eleva la constante en este cambio.
27. **Suite opt-in con los timeouts nuevos:** las fixtures usan su propio engine (`conftest.py:49`); si una ruta con `get_db` excediera 15 s en una prueba legítima, se trata como defecto de la prueba y no se eleva la constante.
28. **Timeout de sentencia durante una petición:** 500 saneado y registro con SQLSTATE; no se reintenta en la misma petición.
29. **Transacción inactiva más allá de 30 s:** la conexión se termina del lado del servidor; error saneado, SQLSTATE registrado y conexión descartada del pool.
30. **Pool agotado bajo carga:** las peticiones que no obtienen conexión reciben 503 con un aviso cada una; las que la obtienen no se ven afectadas y no generan aviso.
31. **API y worker en procesos distintos:** cada uno tiene su propio pool; el agregado (60 con `API_WORKERS=2`) se documenta frente a `max_connections`.
32. **Backfill operativo `encrypt_birth_dates`:** usa su propia conexión administrativa; no hereda estos timeouts.
33. **Semilla explícita frente a semilla aleatoria:** con semilla explícita, dos solicitudes producen el mismo resultado; con semilla aleatoria, el resultado es reproducible a partir de la semilla devuelta.

## Riesgos residuales aceptados

- **H7 — calendarios duplicados en un sorteo simultáneo en frío (ronda 1).** En la ronda 1 sin partidos previos, `SELECT ... FOR UPDATE` no bloquea filas inexistentes y `bracket_code` no tiene restricción de unicidad. Dos solicitudes concurrentes podrían insertar dos calendarios para la misma fase. Se acepta como riesgo residual: corregirlo exige unicidad o un lock de fase y queda **fuera de alcance** de esta spec. No hay pérdida de datos ni cruce entre organizaciones; el operador puede regenerar la fase.
- **Fallo de firma posterior al commit en alta o importación.** La fila queda creada y la respuesta es 503 (N-2/P-3). El cliente debe releer; un reintento ciego puede producir 409 por duplicado. Es una consecuencia aceptada de no firmar dentro de la transacción.
- **Objetos huérfanos por commit fallido o ambiguo.** Si el `commit` de una subida o de una importación falla o se cancela sin poder saber si confirmó, se conservan el objeto anterior y el nuevo; el nuevo puede quedar huérfano. Se acepta y se prefiere a una referencia rota; la limpieza de huérfanos queda fuera de alcance.

## Fuera de alcance

- **R06** (scoping por torneo muerto) y **R09/R10** (reglas declaradas no aplicadas y constantes de partido).
- **R11/R12** (ciclo de vida de partidos y avance entre fases).
- **R18-R32** (higiene P2), incluidos el botón «Reintentar» del realtime, el usuario no-root del contenedor `web`, el drift de `.env.example` frente a Compose, la auditoría de oficiales y planilla, los GET con efecto secundario, los healthchecks, el i18n y los menores.
- **R13/R14 y cualquier cambio en el outbox, el stream de Redis, Socket.IO o la deduplicación** (spec 004).
- Cambiar el esquema, añadir migraciones o índices.
- Cambiar el proveedor de almacenamiento, la forma de las claves, el bucket, el consentimiento o el TTL por defecto.
- Cachear URLs firmadas entre peticiones, introducir CDN o recargar credenciales en caliente.
- Rediseñar el formato Swiss, sus reglas deportivas o sus metas de local/visitante.
- Cambiar límites de paginación, número de rondas o el tope de la llave de eliminación directa.
- Añadir dependencias, cambiar versiones de referencia o de imágenes.
- Cambiar `API_WORKERS`, `max_connections` o el dimensionado del pool más allá de P-4.
- Corregir H7 (calendarios duplicados en un sorteo simultáneo en frío): requiere unicidad o un lock de fase y no forma parte de esta spec.
- Cualquier cambio de frontend: el contrato no cambia; si apareciera, se detiene y se pregunta.

## Criterios de finalización

1. R15 resuelto: un cliente de firma por proceso y endpoint, sin construcciones por jugador, con firmas agrupadas por respuesta y por clave distinta (RF-001, RF-002).
2. Privacidad intacta: solo con consentimiento, `null` sin él, sin documentos ni fechas, sin cambios de vistas ni de RLS (RF-003).
3. Fallo de firma y TTL definidos y probados según P-3: `null` en público, 503 en Workspace, un registro por respuesta (RF-004).
4. N-2 cumplido: ninguna firma, subida (`put_bytes`), borrado (`delete_key`) ni emparejamiento con una transacción abierta; el contexto RLS se fija en cada transacción (RF-002, RF-005, RF-006).
5. R16 resuelto: tope de 64, contador único con límites 40 000/50 000, timeout de 10 s y ejecución en hilo aparte, con salida idéntica dentro del presupuesto (RF-005).
6. Fallback estricto con el orden de `candidate_key` y sin relajar «no repetir rivales»; 409 distinguibles (presupuesto, sorteo imposible, timeout, estado cambiado), `no_valid_pairing` solo sin corte de presupuesto, permiso revocado → 403, validación existente intacta y ninguna escritura confirmada en fallo (RF-006).
7. Sin migraciones, sin cambios de esquema ni de contrato no autorizados, sin dependencias nuevas y sin configuración nueva: el diff no toca `docker-compose.yml`, `docker-compose.production.yml` ni `.env.example` (RF-007).
8. R17 resuelto: 15 000 ms y 30 000 ms efectivos y verificados; pool 10 + 10 con espera de 10 s; agotamiento clasificado como `sqlalchemy.exc.TimeoutError` → 503 con un aviso por petición; `statement_timeout` con el 500 saneado; agregado de conexiones y exclusión del backfill documentados (RF-008, RF-009).
9. Documentación actualizada en `README.md` y `AGENTS.md` con códigos, degradación de fotos, timeouts, pool, agregado de conexiones y reinicio por rotación de credenciales (RF-011).
10. H7 declarado como riesgo residual aceptado y fuera de alcance, sin presentarlo como resuelto.
11. Pruebas unitarias y opt-in ejecutadas según RF-010, con los comandos aplicables:
    ```sh
    cd backend && pytest -q
    cd backend && python -m compileall -q app
    ```
    Las verificaciones opt-in con `RUN_DATABASE_TESTS=1` se ejecutan o se declaran como no ejecutadas. El seed demo se ejecuta en desarrollo y se reporta; si no puede ejecutarse, se declara. No se toca el frontend ni Compose.
12. Los cinco jobs de CI (`backend`, `frontend`, `infrastructure`, `security` y `e2e`) en verde sobre el commit de `main`, con revisión humana distinta del autor.
13. La evidencia no declara ninguna verificación que no se haya ejecutado y distingue lo medido de lo inferido por inspección.

## Verificación contra la constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| P1. Aislamiento por tenant en la base de datos (RLS) | Sí | Las consultas de plantilla y calendario siguen usando `set_rls_context()` dentro de su transacción (`router.py:1309-1310,2428-2429`); la transacción de escritura vuelve a fijarlo. El trabajo puro recibe datos ya filtrados y no consulta la base. La caché no indexa por organización. |
| P2. La aplicación no salta RLS | Sí | No cambia el rol, el engine ni el contexto. Los timeouts y el pool no alteran privilegios. |
| P3. Lo publicado es inmutable | Sí | El calendario Swiss solo se genera en versión `draft` o en rondas posteriores ya publicadas bajo las reglas actuales (`router.py:2451-2452,2473-2475`); el cambio no permite editar una versión publicada. |
| P4. Historial de esquema append-only | Sí | Sin migraciones (RF-007). |
| P5. Lo público es una proyección mínima | Sí | `photo_url` sigue dependiendo del consentimiento y nunca se añaden documentos ni fechas (RF-003). Un fallo de firma en público resulta en `null`, nunca en una exposición parcial. |
| P6. Ningún secreto por defecto fuera de desarrollo | Sí | No se añaden secretos ni variables (P-1, P-4). La caché usa las credenciales ya configuradas y no las registra; su rotación exige reinicio y se documenta. |
| P7. Administración global separada y auditada | No aplica | No se toca `/admin` ni `platform_admins`. |
| P8. Nada se da por terminado sin verificación | Sí | Criterios de finalización con comandos, pruebas unitarias/opt-in declaradas y reporte honesto de lo no ejecutado (RF-010). |
| P9. El código de desarrollo no llega a producción | Sí | No se añaden seeds ni datos demo; el seed existente solo se usa en desarrollo/local. Los timeouts nuevos aplican también a él, sin relajarlos por entorno. |
| §3.1 RLS y migraciones | Sí | Sin tablas ni políticas nuevas; ninguna migración editada; contexto RLS en cada transacción. |
| §3.2 Backend asíncrono y outbox | Sí | No se añaden efectos síncronos de dominio ni llamadas nuevas en el request; la firma sigue siendo lectura y el emparejamiento es cálculo puro. **Sobre «reglas deportivas como JSON»:** el tope de 64, el presupuesto de 50 000 y el timeout no son reglas deportivas (no cambian puntuación, desempates, disciplina ni transferencias, que siguen en el JSON de la versión), sino límites de seguridad del backend. Hay precedente en el propio código: `MAX_SINGLE_ELIMINATION_TEAMS = 512` (`scheduling.py:7`) y los topes de 64 de grupos y cabezas de grupo (`schemas.py:146-149`). No se requiere excepción §5.1. |
| §3.3 Frontend y `useApi.ts` | No aplica | Sin cambios de frontend. |
| §3.4 Seguridad y configuración | Sí | Sin secretos ni variables nuevas; los valores quedan como constantes del backend y no hay defaults que trasladar a `.env.example`. |
| §3.5 Infraestructura y CI | Sí | Versiones de referencia sin cambios; no hay cambios de Compose (`docker compose config -q` no aplica) y no se añaden pasos a CI. |
| §4 Base de datos | No aplica | Sin cambios de esquema. |
| §4 API/backend | Sí | `pytest -q` y `compileall`; endpoints públicos sin campos sensibles; RLS dentro de la transacción; 422/409/503 sin datos internos. |
| §4 Frontend | No aplica | Sin cambios. |
| §4 Infraestructura | No aplica | Sin cambios de Compose ni de variables de entorno; el despliegue no requiere pasos nuevos. |
| §4 Dependencias | Sí | Sin dependencias nuevas; lockfiles y auditorías sin cambios. |
| §4 Documentación afectada | Sí | `README.md` y `AGENTS.md` actualizados por los cambios observables (RF-011), conforme a la §4 «si altera el comportamiento observable». |

## Dudas abiertas

Ninguna. Las decisiones P-1 a P-5, N-1 y N-2 y las resoluciones del QA B-1 a B-17 cierran las preguntas anteriores; el timeout, la política de credenciales y los casos del seed y de la suite opt-in quedan decididos en esta spec. La implementación se validó en la vuelta 1 (399 passed/108 skipped; opt-in no ejecutado por credenciales); la revalidación por @reviewer quedó registrada el 2026-10-20 y el cierre T010 (CI en `main` y revisión humana) se completa con la evidencia del 2026-10-22 sobre `9ad8db1`.

**Evidencia de cierre (2026-10-22, `main` en `9ad8db1`):** `cd backend && pytest -q` con `RUN_DATABASE_TESTS=1` y base en 023 (999 passed, incluidas las opt-in de `tests/test_database_timeouts.py` y `tests/test_swiss_transaction.py`), `python -m compileall -q app` y los cinco jobs de CI en verde, incluido `e2e`.
