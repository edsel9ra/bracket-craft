# Plan 035 — Tiempo real privado según permisos de lectura

Fecha: 2026-11-13. Estado: **implementado**, tras la aceptación expresa de F8 el 2026-11-13 («Opción A»: «Acepto F8; ciérrala y empieza la spec de F1»), con #78 fusionado. Evidencia y límites en `verificacion.md`. Aprobación histórica del plan: 2026-11-13 («Apruebo el plan.»), con C1–C4 confirmadas tal como estaban recomendadas; constitución 2.0.0. DA-1–DA-4 siguen cerradas. No autoriza la implementación de F1.

## 1. Idea central y comprobación contra el código

El relay conserva el carril público y sustituye el broadcast organizativo por entregas individuales autorizadas, con catálogo cerrado y lecturas frescas agrupadas. La autorización no procede del room, del cliente ni de la huella obtenida al conectar. Una invalidación privada solo indica qué recurso volver a leer mediante HTTP, que conserva la decisión final de acceso.

Revisión **estática** de la rama del PR #75, base `c0aef6f7c8376db3eaede77fa0a0a5b73a8de1a6`. Los tests descritos son futuros, no resultados de esta revisión.

| Hecho actual y evidencia | Consecuencia del diseño / diferencia respecto a la spec |
|---|---|
| `backend/app/main.py:66,198,231,330–343`: tres nombres públicos; rooms `organization:{id}` y `tournament:{id}`; todo evento del relay se emite primero al room organizativo. | Es R32f, no filtrado por destinatario. Eliminar ese broadcast para eventos de dominio; nunca usar pertenencia al room como prueba de lectura. |
| `main.py:272–296`; `workers/outbox.py:95–112`: parseo genérico y publicación Redis por defecto. `scripts/outbox_probe.py` produce `VERIFICATION_OUTBOX_PROBE`. | Un tipo desconocido hoy puede llegar al canal organizativo. Catálogo cerrado en el límite de entrega; la sonda sigue siendo de verificación worker/Redis, nunca producto ni Socket.IO. No romper la sonda filtrándola antes de Redis. |
| `modules/matches/service.py:992–994,1136–1139` y `modules/advancement/service.py:173–180`: cierres, walkover y bracket reset producen señales con `match_id,tournament_id`. | Declarar también su lectura organizativa; no basta con clasificar los eventos que llevan scope privado. Mantener intacta la variante pública. |
| `modules/rectifications/notifications.py:14–22`: tres eventos con `match_id,tournament_id,version_id,rectified_at,scope=organization`. | Son variantes privadas, incluso con nombre público. El sobre interno conserva la referencia necesaria para verificar la versión; Socket.IO solo entrega la proyección mínima de §4. |
| `core/tenancy.py:19–60`; `matches/router.py:507–532` llama `_load_operation_match(require_operation_permission=False)`; `rectifications/router.py:178–183` y `rectifications/service.py:441–454` permiten leer versiones con contexto organizativo. | Hoy estas lecturas requieren sesión, membresía activa con rol y recurso accesible por RLS, **no** cerrar ni aprobar el acta. Todos esos lectores pueden recibir su invalidación. No inventar `VIEW_*` ni trasladar permisos de escritura al catálogo. |
| `core/permissions.py::require_permission`: consulta multirrol y asignación/exenciones cuando se pasa `match_id`. | Reutilizar la semántica exacta cuando una lectura realmente la exija. La asignación no sustituye al permiso; para el catálogo actual no constituye una restricción adicional. |
| `modules/tournaments/routes/public.py:87–125`: la ruta de clasificaciones existente es `/tournaments/public/{id}/standings`, no una lectura organizativa `/tournaments/{id}/standings`. | No inventar un endpoint ni exigir publicación pública a una invalidación privada. La señal organizativa solo identifica el partido causante y su torneo, verificables por la operación HTTP; no lleva filas de clasificación. |
| `main.py:142–201,546–575`; `032_socket_session_revalidation.sql`: conexión autenticada y revalidación en lote cada 30 s, sin `match_officials`; el error de consulta conserva conexiones. | Es mantenimiento de conexión, no autorización de entrega. DA-2 no se satisface con ese intervalo ni con la huella antigua; un error privado suspende entregas, no desconecta masivamente. |
| `036_rectification_platform_authorization_rls.sql` amplía `fn_verify_user_org_membership` con una autorización excepcional de plataforma. | El nuevo adaptador exige membresía **real**, usuario y rol; limpia contextos excepcionales. Una autorización 033/F9 no abre el canal privado organizativo. |
| `useRealtime.ts:158–174`, `realtimeDispatch.ts:47–63`, `realtimeDedup.ts:18–37`: despacho genérico y deduplicación por `event_id`. Workspace escucha los tres nombres públicos; operación escucha dos; no hay consumidor explícito de `MATCH_REPORT_RECTIFIED`. | Conservar nombres y cantidad de eventos. No añadir un cuarto callback ni una recarga por cada tipo de rectificación. Los consumidores actuales no necesitan `version_id` ni `rectified_at` del evento. |
| `frontend/app/composables/useMatchOperation.ts:72–83,321–326`: `onResync` llega a `requestOperationReload`, pero este retorna si `isTerminal` o `busyAction`. | Una vista de acta cerrada no reconstruiría su estado por RESYNC; una acción ocupada puede perder la señal. Ajuste acotado necesario para RF-017: permitir lectura de terminales y consolidar una recarga aplazada, sin habilitar escritura. No se ha ejecutado todavía una reproducción dinámica. |
| `workers/outbox.py:95–110`: handlers de avisos F9 y correo de rectificación separados. | F9 permanece fuera de Redis/Socket.IO; el correo de rectificación tampoco pasa al catálogo. |
| `infra/postgres/migrations/` termina en 054. | C1 propone **055**, solo función autorizadora/grants; comprobar el siguiente número libre antes de implementar. 032 y demás migraciones aplicadas no se editan. |

No se ha encontrado una contradicción entre la spec aprobada y la constitución. Las diferencias anteriores son comportamiento previo que F8 debe sustituir; no justifican cambiar los RF ni afirmar que hoy hay lectores restringidos por permisos inexistentes. R32f y sus referencias en 008/009/010 y auditorías son antecedentes históricos, no archivos que reescribir para ocultar el riesgo.

## 2. Archivos y responsabilidades

Rutas nuevas propuestas; no existen todavía por este plan. Separación entre núcleo puro, adaptador SQL y orquestación de transporte, sin nuevo router HTTP.

| Archivo / símbolo previsto | Responsabilidad y RF |
|---|---|
| `backend/app/core/realtime_policy.py` (nuevo) | Catálogo cerrado, reglas de lectura, clasificación y validación de sobres, proyección de invalidaciones, deduplicación de destinatarios y decisión pura con hechos precargados. RF-001–005,012–013,019–020. |
| `backend/app/core/realtime_authorization.py` (nuevo) | Transacciones frescas y lotes acotados, contexto RLS, llamada a función SQL, resultado `ALLOW/DENY/INDETERMINATE`, sin caché positiva. RF-006–009,011,014,017. |
| `backend/app/main.py` | Registro local por organización/principal/sid, conectar/desconectar, fanout privado a sid, carril público separado, marcas de suspensión y recuperación. Revalidación 032 permanece como mantenimiento; no sustituye al nuevo gate. RF-001–002,006–011,014,016–018. |
| `backend/app/core/outbox.py`; `backend/app/workers/outbox.py` | Mantener stream, retención, ID y handlers explícitos. No autorizar sockets en el worker: el destinatario puede cambiar después de publicar. Contrato y regresiones RF-011–013,018–020; sin cambios funcionales si los tests acreditan el contrato actual. |
| `backend/app/core/permissions.py`; `backend/app/core/tenancy.py`; `backend/app/core/database.py` | Referencias canónicas de permiso/membresía y `set_rls_context`; compartir solo predicados que puedan extraerse sin modificar HTTP. No endurecer rutas ni defaults; pruebas de paridad RF-001–006. |
| `backend/app/modules/matches/{router,service}.py`; `backend/app/modules/advancement/service.py` | Lectura de referencia y productores públicos actuales: conservar semántica, IDs y transacción; tests contractuales, no nuevos eventos. RF-005,011,016. |
| `backend/app/modules/rectifications/{router,service}.py`; `notifications.py` | Verificación de lectura/versiones y payload interno privado mínimo: retirar timestamp prescindible en nuevas filas; mantener `scope` y referencia de versión para clasificar/verificar. Ninguna modificación de publicación, auditoría o correo. RF-005,012–015. |
| `infra/postgres/migrations/032_socket_session_revalidation.sql` | Solo referencia y regresión, **sin editarla**. |
| `infra/postgres/migrations/055_realtime_delivery_authorization.sql` (prevista por C1 aprobada) | Función batch `SECURITY INVOKER`, permisos de ejecución mínimos; sin tablas, generaciones persistentes, nuevos permisos RBAC ni ampliación de políticas. RF-001–009,011–014. |
| `frontend/app/composables/useRealtime.ts` | Mantener un socket, ciclo de conexión y aislamiento por identidad/organización; impedir que callbacks de una generación anterior actualicen el contexto vigente. RF-010,017–018. |
| `frontend/app/utils/realtimeDispatch.ts`, `realtimeDedup.ts`, `realtimeReload.ts` | Conservar contratos y deduplicación; consolidación de recarga HTTP y recuperación compatibles con clientes actuales (C3). RF-013,015,017–018. |
| `frontend/app/pages/workspace/index.vue`; `frontend/app/composables/useMatchOperation.ts` | Consumir IDs, no datos de negocio; recargar con `useApi`. En operación, RESYNC también para acta terminal y recarga pendiente tras acción, sin tocar edición/borradores. RF-010,015,017–018. |
| `frontend/app/pages/tournaments/[id].vue` | Sin cambio de producto. Tests de contrato público, filtros por torneo, polling/RESYNC y deduplicación permanecen. RF-016,018. |
| `backend/tests/test_realtime_policy.py`, `test_realtime_delivery.py`, `test_realtime_delivery_db.py` (nuevos); tests existentes de outbox/sockets | Núcleo, transporte simulado y PostgreSQL real con rol de aplicación. Matriz y escenarios en §8. |
| `frontend/tests/realtime-*.test.ts`, prueba del composable real de operación; `frontend/e2e/realtime-{workspace,operation,public}.spec.ts` y sus fixtures | Dispatcher, recarga, aislamiento y comprobación de **recepción/no recepción** en el socket del navegador. Integrar en proyectos actuales sin inventar un gate separado. |
| `README.md`, `AGENTS.md`, `docs/manual-usuario.md`, `MEMORY.md`, `specs/035-tiempo-real-por-rol/{spec,plan,tasks,verificacion}.md` | En implementación/validación: sustituir la descripción vigente «todos los miembros» por el contrato real, documentar fallos/recuperación y evidencias RF-001–020. No marcar implementado ni crear tasks/verificación en esta fase. |

## 3. Base de datos, RLS y eficiencia (C1)

### 3.1 Elección recomendada y límites

Proponer `public.authorize_realtime_recipients(organization_id, candidates_jsonb, event_jsonb, evaluation_time)` con resultado por clave de principal/recurso: estado, sin detalle del recurso ni motivo sensible. Solo puede autorizar reglas del catálogo; cualquier código desconocido devuelve denegación. Candidatos del registro del servidor, no de un mensaje del cliente.

- Agrupar primero por organización y luego por `(user_id,session_id)`; varias pestañas de la misma sesión comparten evaluación y se distribuyen a sus sid. Agrupar dentro de SQL las sesiones de un mismo usuario para cargar una vez membresía/roles y comprobar sus sesiones en conjunto.
- Máximo inicial aprobado: **256 principales por lote**, una entrada de stream cada vez, sin acumular una ventana temporal de decisiones. Índice local `organización → principal → sid`; sin escanear sockets de otros tenants para cada evento. Límite de trabajo pendiente y concurrencia acotados; no dejar crecer una cola de autorizaciones ya concedidas.
- Cada lote abre una transacción **nueva, corta, REPEATABLE READ**, sin reutilizar la de un evento anterior, del outbox ni de revalidación. La primera sentencia obtiene `statement_timestamp()` y adquiere una instantánea nueva: ahí comienza la evaluación del lote; ese instante se pasa como `evaluation_time` a toda lógica temporal. No hay transacciones idle retenidas entre eventos.
- Antes de cualquier lectura tenant, `set_rls_context(db, organization_id, primer_user_id)` dentro de esa transacción; el batch SQL fija de nuevo el contexto local para cada usuario, igual que el patrón de 032. Limpiar `app.rectification_authorization_id` y `app.sanction_authorization_id`; no heredar excepciones administrativas. La misma instantánea se conserva al cambiar contexto, no los datos de otro usuario.
- Una llamada de autorización de datos por lote, más el coste constante de iniciar instantánea/contexto; no una ida/vuelta SQL por socket y evento. Hay trabajo SQL por principal distinto dentro de la función y debe medirse, no llamarlo O(1). Para S sockets, U principales y B=256: llamadas de autorización `ceil(U/B)`, más operaciones constantes por lote; memoria O(S+U), sin multiplicar por eventos perdidos.
- Cero candidatos: cero consultas tenant. Registro/datos corruptos, salida faltante o principal duplicado con resultados incompatibles: no permitir; marcar solo los afectados como indeterminados cuando sea fallo de comprobación. El recurso de otro tenant o inexistente se deniega sin revelar cuál de los dos casos ocurrió.

El batch no oculta una consulta de red por sid: las pestañas comparten hechos y las sesiones de un usuario comparten carga de roles/recurso dentro de SQL. Sigue siendo necesario trabajo por usuario distinto, porque RLS se evalúa con su contexto y no se introduce una identidad privilegiada para leer a todos de una vez. En el peor caso de una sesión por usuario no desaparece ese coste; se justifica por la comprobación fresca y el aislamiento, se amortiza el viaje de red y se mide con L1. La aceptación no se basa únicamente en contar una llamada exterior a una función que internamente haga trabajo ilimitado.

### 3.2 Hechos de autorización y equivalencia HTTP

La función lee mediante RLS, para el mismo principal: usuario/organización activos, sesión de ese usuario no revocada y `expires_at > evaluation_time`, membresía real activa y existencia de rol organizativo efectivo, permisos de todos sus roles y el recurso de §4. Un token vencido tampoco permite conservar el canal: guardar en metadatos del servidor la expiración JWT verificada al conectar y compararla con `evaluation_time`; el cliente no la aporta como hecho autorizado. El resultado SQL de sesión puede compartirse entre pestañas, pero la expiración JWT se comprueba por sid con ese mismo instante si sus tokens difieren, sin otra consulta SQL.

Las reglas actuales de partido y versiones no exigen permiso operativo ni oficial; un lector con rol de solo consulta conserva su lectura aunque no esté asignado. La consulta debe reproducir también accesibilidad y relaciones exactas que las rutas HTTP comprueban, no solo comprobar un UUID. Un rol de otra organización no se une por nombre.

Para una regla que realmente necesite permiso/asignación, el predicado tiene los mismos roles, exenciones y conjunciones que HTTP: no mezclar el permiso de una fila de rol con la exención de otra si HTTP exige que concurran en la misma fila. `role_definitions.system_permissions` no se añade como fuente automática de grants si la lectura canónica usa `roles.permissions`. La huella del handshake sirve para mantenimiento, nunca como permiso ni motivo para conservar una autorización retirada. No hay roles por torneo.

No se activa hoy una política de lectura de borradores ni una regla operativa basada en `CLOSE_MATCH_REPORT`: el catálogo actual no contiene esa lectura. RF-004 se cubre con paridad negativa (no exigir asignación donde HTTP no la exige) y tests puros del predicado condicional; una regla de F1 necesitará su propia lectura aprobada antes de incorporarse.

### 3.3 Corte de revocación y alternativa de caché

«Confirmar la retirada» significa commit exitoso del cambio autoritativo, no crear el evento outbox ni recibir una notificación Redis. Toda evaluación iniciada después adquiere instantánea nueva contra **la base primaria**, donde ese commit ya es visible. No usar réplica con retraso ni instantánea compartida de una evaluación anterior. Una revocación concurrente posterior al inicio puede dejar pasar el resultado ya aprobado: es el caso admitido por DA-2, no un TTL de gracia. Un lote posterior, incluso del mismo evento, vuelve a leer. Sesión/JWT vencidos se prueban con igualdad en el límite temporal, sin esperas reales.

La caché positiva con TTL o invalidación vía Redis/pubsub **no cumple** DA-2: entre commit y recepción de la invalidación se puede iniciar otra evaluación con permisos antiguos. La alternativa correcta exigiría generaciones transaccionales actualizadas por **todos** los escritores de sesión, usuario, organización, membresía, roles, permisos y oficiales y una lectura fresca de generación por lote antes de reutilizar hechos. Añade migraciones/triggers, complejidad multirrol y no elimina la consulta fresca. Se estudia y se descarta conforme a C1 aprobada; cambiar esa elección requeriría revisión y aprobación del plan. Tampoco cachear denegaciones que retrasen una concesión RF-009. Solo se cachean metadatos de transporte/catálogo inmutable, nunca autorización de recursos.

### 3.4 Migración y protección

`055_realtime_delivery_authorization.sql`, según C1 aprobada, añade la función invocadora y revoca EXECUTE de PUBLIC, concediéndolo únicamente al rol de aplicación necesario. Sin `SECURITY DEFINER`, superusuario de aplicación, BYPASSRLS, tablas de caché, escrituras de dominio ni ampliación de grants SELECT. No modificar 032 ni políticas existentes para que el batch «funcione»; una RLS que impida comprobar un hecho produce denegación/suspensión y obliga a revisar el diseño.

No hay tablas nuevas que requieran políticas nuevas; las existentes mantienen `ENABLE/FORCE RLS` y sus políticas tenant. Una futura revisión de C1 hacia almacenamiento de generaciones exigiría detallar otra migración nueva, tablas con organización, `ENABLE/FORCE RLS`, `USING/WITH CHECK`, FK tenant y grants mínimos, y obtener una nueva aprobación; este plan no lo autoriza implícitamente.

Verificar migración desde volumen limpio y desde 054, aplicación idempotente por el runner, rol efectivo no superusuario/no BYPASSRLS, grants, contexto local sin fugas al pool, y RLS con dos organizaciones. El adaptador debe probarse con el rol real de aplicación, no solo con un propietario de tablas. El nuevo número se reserva únicamente al implementar.

## 4. Contratos de eventos, sobres y catálogo cerrado (C2)

### 4.1 Sobre Redis y control

Mantener el sobre actual del worker:

```text
{ event_id, id, organization_id, event_type, payload }
```

`event_id` identifica la fila outbox; `id` es alias legado y no un segundo evento. Para privados, aceptar el alias si falta `event_id`; si ambos existen y difieren, o falta un ID válido, denegar. No cambiar el comportamiento legado del carril público. Validar tipos, identificadores, scope y consistencia antes de cualquier decisión privada. El sobre y la clasificación son internos; `organization_id` no se añade al payload público ni hace falta exponerlo en la invalidación privada.

`RESYNC` sigue siendo control del servidor, dirigido al sid: `{event_id, reason}`. Sin IDs de partido/torneo/usuario, cantidad de pérdidas, permisos, errores SQL ni negocio. Los motivos actuales son `JOIN`, `RELAY_START`, `STREAM_TRIMMED`, `REDIS_RESET`. No admitir un evento de dominio con tipo `RESYNC` como orden del cliente o del stream. La recomendación C3 reutiliza `RELAY_START` para reactivar el tramo privado del relay sin ampliar el contrato ni exigir actualizar pestañas abiertas.

### 4.2 Reglas actuales de lectura organizativa

Cada fila es una entrada explícita por **tipo y variante**, no un comodín por nombre. Todas exigen sesión/usuario/membresía/rol y contexto válidos además de la lectura referenciada. El permiso adicional de las lecturas actuales es **ninguno**; no implica autorizar futuros tipos por mera membresía.

| Tipo / variante interna | Fuente y referencia HTTP | Recurso a comprobar | Payload privado Socket.IO recomendado |
|---|---|---|---|
| `MATCH_CLOSED`, sin scope privado | Cierre/walkover; `GET /matches/{match_id}/operation` | Partido legible de la organización y `tournament_id` perteneciente al mismo partido/tenant. | `{event_id,match_id,tournament_id}` |
| `MATCH_UPDATED`, sin scope privado | Cierre/walkover/bracket reset; misma lectura de operación. | La misma relación de partido/torneo. No deducir lectura de permiso de actualizar. | `{event_id,match_id,tournament_id}` |
| `STANDINGS_UPDATED`, sin scope privado | Cierre/walkover; `GET /matches/{match_id}/operation` para el partido causante y su contexto. No entrega filas de clasificación. | Partido legible y torneo de ese partido en la misma organización; sin exigir visibilidad pública. | `{event_id,match_id,tournament_id}` |
| `MATCH_UPDATED`, `scope=organization` | Publicación rectificativa; operación y `GET /matches/{match_id}/report-versions`. | Partido/torneo y versión `version_id` del mismo partido y organización, legible por el destinatario y acta confirmada como exige HTTP. | `{event_id,match_id,tournament_id}` |
| `STANDINGS_UPDATED`, `scope=organization` | Publicación rectificativa; operación del partido causante y lectura de versión de acta. Sin filas de clasificación. | Las mismas relaciones verificadas de partido/torneo/versión confirmada; sin exigir publicación pública del torneo. | `{event_id,match_id,tournament_id}` |
| `MATCH_REPORT_RECTIFIED`, `scope=organization` | Publicación rectificativa; `GET /matches/{match_id}/report-versions`. | Partido/torneo y versión rectificativa legible del mismo tenant, con acta confirmada. | `{event_id,match_id,tournament_id}` |

Los endpoints se referencian sin el prefijo global de la API. Las reglas incluyen los JOIN de accesibilidad de `_load_operation_match`, no solo existencia del partido, y `_require_confirmed` de las versiones. La versión concreta puede contrastarse con `GET /matches/{match_id}/report-versions/{number}`. La lectura de filas públicas de clasificación mantiene su endpoint y visibilidad propios; recibir el ID del partido en el canal organizativo no habilita esa consulta. Antes de implementar se fijarán tests de paridad de **cada** ruta, no una inferencia por nombre del permiso. No incorporar usuarios de plataforma sin membresía real por conocer un expediente o una autorización excepcional.

Recomendación mínima: `match_id` permite filtrar la operación y `tournament_id` seleccionar el ámbito de recarga; `version_id` no es necesario en el navegador, que vuelve a obtener versiones por HTTP. No enviar `rectified_at`, `scope`, estado, marcador, jugadores, sanciones, evidencia, motivos ni auditoría. Los IDs del sobre también son información protegida: ningún sid denegado recibe el nombre del evento ni un payload vacío como señal sustitutiva.

Para nuevas filas privadas de rectificación, el payload outbox será `{match_id,tournament_id,version_id,scope:'organization'}`. `scope` y `version_id` siguen **internos**, necesarios para clasificar y verificar, sin transmitirlos. Aceptar filas históricas con el `rectified_at` conocido e ignorarlo al proyectar. No reescribir outbox ya persistido ni usar la referencia de versión como autorización. Un campo de negocio inesperado o una combinación ajena a estas variantes no habilita una proyección permisiva: se deniega el evento privado incoherente.

### 4.3 Exclusiones y carril público

- Desconocidos, IDs/organización/recursos no verificables, referencias cruzadas, scope no reconocido y `MATCH_REPORT_RECTIFIED` sin scope privado: denegación privada por defecto; log técnico sin payload sensible. No ampliar el catálogo automáticamente desde outbox ni desde `PUBLIC_REALTIME_EVENTS`.
- `VERIFICATION_OUTBOX_PROBE`: excluido del catálogo de producto, **cero emisiones Socket.IO**; worker/Redis y su prueba operativa siguen funcionando.
- `SANCTION_CASE_NOTICE_INTERNAL`, `SANCTION_CASE_NOTICE_EMAIL`, `RECTIFICATION_DECISION_EMAIL`: nunca candidatos realtime, incluso si apareciesen por error en Redis; mantener handlers del worker y probar no difusión. F9 no se migra a este filtro.
- Borradores F1: no hay entrada, nombre reservado que autorice ni permiso inferido; su recepción permanece denegada hasta su spec y lectura aprobadas.
- Público: conservar exactamente `MATCH_CLOSED`, `MATCH_UPDATED`, `STANDINGS_UPDATED`, payload actual `{match_id,tournament_id,event_id}` y compatibilidad de ID existente, rooms de torneo y criterios actuales de emisión. `scope=organization` continúa excluyendo las tres variantes privadas. La nueva proyección privada nunca se reutiliza para fabricar un mensaje público.
- Ejecutar el carril público con su propia gestión de errores: una consulta privada caída no debe impedir emitir una señal pública ya elegible. No añadir `organization_id`, `version_id`, `rectified_at`, scopes ni campos de F9 a lo público. No alterar proyecciones HTTP, fotos/consentimiento ni consultas anónimas.

## 5. Funciones puras y tiempo como parámetro

| Función propuesta | Entrada → salida | Pruebas principales |
|---|---|---|
| `classify_organization_event(envelope, catalog)` | Datos sin confianza → regla normalizada o denegación tipada; validar tipo/variante y compatibilidad de alias. Sin I/O. | Normales/legado, vacío, malformado, desconocido, scope/ID incoherentes y exclusiones. |
| `resolve_event_references(rule, payload)` | Regla/IDs → referencias tipadas a comprobar, no un recurso ya «autorizado». | IDs ausentes, mal tipados, referencias completas de versión; aislamiento se comprueba después por RLS. |
| `group_recipients(server_sessions, organization_id, batch_size)` | Metadatos → principales únicos y sid por principal, lotes deterministas. | Ninguno, varios sid/misma sesión, sesiones distintas, otro tenant, límites de 256/257 y metadatos inválidos. |
| `decide_private_delivery(rule, recipient_facts, resource_facts, evaluation_time)` | Hechos verificados → `ALLOW/DENY/INDETERMINATE`; sin reloj, DB, Redis ni consulta a estado global. | Multirrol, estado/expiración, asignación solo condicional, recursos ajenos, hechos faltantes/error. |
| `build_private_invalidation(event_id, authorized_refs)` | Solo IDs ya autorizados → tres campos permitidos; no copiar el diccionario original. | Normal, referencias vacías/incompletas, dato de negocio inesperado no sale. |
| `reduce_delivery_state(state, result, connection_generation, evaluation_time)` | Estado de suspensión/recuperación → nuevo estado e intención de RESYNC, no emisión. | Fallo repetido, denegación, recuperación, cambio de generación, señal duplicada y vencimiento. |

El reloj solo se consulta en la frontera I/O que obtiene la instantánea/evaluation_time y en el programador de reintentos; la lógica recibe la fecha explícita. Cualquier cálculo de retry recibe `now` y `next_attempt_at`; tests con reloj inyectado, sin sleep. La función SQL recibe `evaluation_time`, no oculta `now()` dentro del predicado temporal. No hay TTL de autorización que permita una entrega antigua.

## 6. Algoritmo de entrega y recuperación

### 6.1 Pseudocódigo de orquestación

```text
al consumir una entrada Redis:
    parsear sobre con compatibilidad de transporte existente
    intentar carril público existente, independiente del resultado privado
    clasificación = classify_organization_event(sobre, catálogo_cerrado)
    si excluido / desconocido / incoherente: no emitir a organización; avanzar
    referencias = resolve_event_references(clasificación, payload)
    candidatos = group_recipients(registro_servidor, organization_id, 256)
    para cada lote de principales, listo para entrega (no precalcular futuros):
        iniciar evaluación con transacción nueva y snapshot fresco
        obtener evaluation_time en esa frontera; fijar contexto RLS
        resultados = autorizar_batch(lote, regla, referencias, evaluation_time)
        # sesión, JWT, usuario, org, membresía real, multirrol, recurso por RLS;
        # permiso/oficial solo donde lo pide la lectura HTTP declarada
        para cada principal y sus sid locales:
            si sid desconectó o cambió generación/contexto: descartar
            si falta resultado o hay error técnico:
                suspender ruta privada afectada; marcar needs_resync; no emitir
            si DENY: no emitir evento ni control que identifique el recurso
            si ALLOW:
                si needs_resync: emitir RESYNC mínimo tras reautorizar contexto
                si control falla: mantener suspensión y marca; no seguir entrega
                emitir proyección privada a cada sid aún vigente, no al room
        cerrar evaluación; no guardar sus ALLOW para otro evento/lote
    avanzar cursor de stream aunque se haya suspendido una entrega privada
```

Ante fallo de transacción completa se suspenden los candidatos de ese lote, no los tenants públicos ni los lotes ya comprobados. Si el error es global DB, todos los privados afectados quedarán suspendidos hasta recuperarse, pero sus sockets no se desconectan por ese error. No inferir permiso porque el SQL no devolvió un sid. No registrar payloads, tokens ni SQL con parámetros sensibles.

Una evaluación puede terminar y enviar después de una revocación concurrente: estaba aprobada en tránsito, según DA-2. No hay barrera que cancele retrospectivamente decisiones ni promesa de retirar datos recibidos. Sí se comprueba la generación de conexión antes de emitir para no aplicar una autorización del usuario A al sid/contexto B.

### 6.2 Recuperación sin replay (C3)

Mantener por sid/generación una marca `needs_resync` y estado suspendido, sin lista de eventos, IDs de recursos perdidos ni caché de permisos. La marca se elimina al desconectar/cambiar contexto o tras recuperación enviada correctamente; memoria acotada al registro de sockets locales.

Reutilizar el ciclo de mantenimiento de 30 s para **intentar** recuperar marcas, y también intentar antes de la siguiente entrega. El intervalo es de recuperación, no una ventana de autorización: cada evento sigue teniendo gate fresco. No prometer un plazo de recuperación si DB no responde.

En cada intento, nueva evaluación agrupada de sesión/JWT/usuario/organización/membresía real con rol. Para el control genérico no se exige un recurso de negocio ni se incluye su ID. Si falla la comprobación, continuar suspendido; si ya no hay sesión/membresía, no emitir. La revalidación 032 puede desconectar una sesión realmente inválida; no se introduce desconexión masiva por error de autorización. Un nuevo socket pasa por JOIN y HTTP de nuevo.

Precisión de implementación de C3, confirmada por el usuario el 2026-11-13,
sin cambiar la decisión: reutilizar `revalidate_socket_sessions` de la migración
032, `SECURITY INVOKER`, con una llamada fresca por lote de hasta 256 sockets
suspendidos. Comprueba sesión, usuario, membresía y huella vigente; los válidos
reciben `RESYNC RELAY_START` dirigido, los inválidos siguen el tratamiento de
desconexión existente de 032. Si la función falla u omite una fila, conservar la
suspensión y reintentar. Comprobar también expiración JWT y generación antes de
emitir. El control no incluye negocio ni concede acceso: las recargas HTTP se
autorizan por separado y cada evento siguiente sigue pasando por 055. No añadir
056 ni modificar 032/055 para esta recuperación.

Con contexto recuperado: enviar al sid `RESYNC {event_id_nuevo, reason:'RELAY_START'}` y habilitar nuevas evaluaciones. Representa reactivación del tramo privado del relay, no asegura reinicio del proceso. Una nueva actualización todavía pasa por la regla de su recurso. Sin recurso pendiente autorizado no se envía evento de negocio. Coalescer fallos repetidos en una recuperación; no enviar un RESYNC por cada evento perdido. Si el envío falla, conservar marca; si la recarga HTTP falla, el cliente muestra/reintenta su error habitual, nunca obtiene datos de eventos perdidos.

El cursor avanza, no se acumulan privados para entregarlos al recuperarse, no se reabre un consumer group de replay ni se reintenta outbox por una denegación de socket. Los mecanismos existentes de recorte/reset/reconexión de Redis mantienen sus RESYNC; cualquier control dirigido a conexiones organizativas debe pasar el gate de contexto vigente antes de emitirse. Los clientes públicos conservan su camino actual.

## 7. Interfaz, frontend y despliegue

### 7.1 API y pantallas

No nuevos endpoints, routers, pantallas, permisos, defaults RBAC ni roles por torneo. Reconstrucción HTTP con `frontend/app/composables/useApi.ts`, su organización activa y tratamiento habitual 401/403/404. El evento no actúa como credencial ni autoriza una escritura. Mantener Composition API, i18n ES/EN y `useConfirm` singleFlight en las acciones existentes; F8 no necesita un diálogo nuevo.

`MATCH_UPDATED` privado ya recarga la operación y, junto a `STANDINGS_UPDATED`, el Workspace. Sus consumidores no usan el timestamp o la versión retirados. **No añadir consumidor explícito de `MATCH_REPORT_RECTIFIED`**: hoy es redundante con esas señales, y añadirlo generaría otra recarga para la misma publicación. Mantener el evento y su catálogo para consumidores genéricos autorizados, sin habilitar listeners por nombre desconocido como permiso de servidor.

El ajuste necesario de `useMatchOperation` distingue lectura y edición: un partido terminal sigue prohibiendo mutaciones, pero no una lectura HTTP autorizada por invalidación/RESYNC. Una señal durante `busyAction` deja una sola recarga pendiente tras finalizar, agrupada por el coordinador existente, no se pierde. No limpiar borradores ni reabrir actas por recibir una señal; mantener la preservación actual de borradores y el tratamiento de conflictos HTTP. Probar expresamente planilla clásica/táctica y borrador local después de recargar.

`useRealtime` mantiene una sola suscripción por contexto, deduplicación por `event_id` y desconexión/limpieza al cambiar organización o identidad. Capturar una generación de contexto en callbacks y recargas: un resultado HTTP o evento de una generación anterior no actualiza la nueva. Una denegación HTTP no conserva una pantalla como si su recarga hubiera sido autorizada; usar el flujo de error/acceso existente, sin reconstruir detalle desde el mensaje.

No cambiar el número de entradas de outbox por rectificación (tres, cada una con ID propio). El baseline actual puede consolidar un evento inicial y otro trailing; RF-018 exige no añadir recargas por el filtro, no convertir tres IDs distintos en uno inventado. Duplicar el mismo `event_id` sigue sin generar otra recarga. La recuperación emite una señal de control por episodio, no además un replay de cada invalidación perdida.

### 7.2 Exposición pública y configuración

Campos públicos realtime exactos: `event_id`, `match_id`, `tournament_id`, con el contrato legado ya soportado; los tres nombres de §4, sin adiciones. No campos HTTP públicos nuevos: documentos, nacimiento, edad sensible, sanciones, evidencias, motivos y auditoría siguen excluidos; las fotos continúan condicionadas al consentimiento. Las variantes `scope=organization` nunca se dirigen a `tournament:{id}`. No hay dependencia nueva de sesión/cookie para lo público.

Sin nuevas dependencias ni variables de entorno, secretos, servicios, transporte polling o cambios de proxy/CI. Conservar WebSocket del cliente, rate limit público y relay por proceso API. La migración debe desplegarse antes de activar el gate. Una función ausente/error durante despliegue produce suspensión privada, **nunca fallback a broadcast**.

En despliegue escalonado no puede convivir un API antiguo que siga haciendo broadcast con otro que filtre. Drenar/reemplazar todos los procesos API organizativos antes de declarar F8 activo; reconexión con JOIN reconstruye por HTTP. Si se requiere continuidad sin esa sustitución coordinada, hay que rediseñar/confirmar el despliegue antes de implementar, no asumir que Redis invalida a los procesos antiguos. Mantener worker y frontend compatibles con mensajes privados históricos, sin reescribir outbox. Público conserva contrato y recuperación; no se ofrece disponibilidad sin interrupción como requisito nuevo.

## 8. Estrategia de tests y criterios verificables

Los identificadores siguientes nombran suites/escenarios previstos, no tareas ni pruebas ya ejecutadas. Cada suite incluye normal, vacío y error; los asserts deben alcanzar el transporte recibido por cada cliente, no solo filtros de UI.

| ID | Ubicación prevista y casos |
|---|---|
| **P1 Catálogo** | `backend/tests/test_realtime_policy.py`: las seis variantes, IDs legado/coincidentes/divergentes, scope inválido, vacío, tipo desconocido, payload con negocio inesperado, sonda/F9/F1 rechazados y whitelist de tres IDs. |
| **P2 Decisión pura** | Mismo archivo: matriz de usuario/sesión/membresía/rol, multirrol/rol homónimo de otro tenant, expiración antes/igual/después con `evaluation_time` inyectado; referencias incompatibles, hechos ausentes y error indeterminado. Predicado permiso+oficial con/sin permiso/asignación/exención, en fixture puramente técnica: no añade una lectura ni un evento de producto. |
| **P3 Agrupación** | Mismo archivo: cero candidatos, 1.000 sockets/100 principales, sesiones distintas de un usuario, 256/257, partición por tenant, generación obsoleta; decisiones no reutilizadas. |
| **D1 Paridad/RLS** | `backend/tests/test_realtime_delivery_db.py`: PostgreSQL con `bracket_app`, dos tenants y recursos con IDs conocidos; comparar cada lectura de §4 por HTTP contra gate. Miembro con rol sin permisos de escritura y sin oficial **sí** recibe cuando HTTP sí lee; perder un rol con otro vigente conserva acceso. Usuario externo/plataforma sin membresía no recibe. Probar versión/partido/torneo cruzados, mismo 404/vacío de referencia y estado inactivo. |
| **D2 Corte/concurrencia** | Mismo archivo: barreras reales de commit, no sleeps. Mantener socket abierto, crear outbox, retirar sesión/membresía/rol/permiso/oficial y comenzar evaluación después del commit: nunca usa hechos antiguos; si la lectura actual no dependía de lo retirado, se conserva acceso como HTTP. Evaluar antes y enviar tras commit está permitido; siguiente lote/evento vuelve a evaluar. Concesión posterior, expiración y dos procesos leyendo el mismo stream. |
| **D3 Migración/contexto** | Migración limpia y 054→055 con runner; grants EXECUTE, no superusuario/no BYPASSRLS, RLS/FORCE, ausencia de fugas al pool/contextos excepcionales y rollback de transacción. Función inexistente, error/resultado parcial y recurso borrado deniegan/suspenden, no abren acceso. |
| **S1 Entrega** | `backend/tests/test_realtime_delivery.py`: `sio.emit` dirigido a sid permitido, nunca broadcast organizativo, cero señal de negocio a denegado; evento pendiente evalúa permisos actuales. Públicos sin cambio aunque falle DB privada; privados con nombre público no llegan a sala pública. Desconexión/cambio de generación entre consulta y emit. |
| **S2 Fallo/recuperación** | Mismo archivo y `test_socket_revalidation*.py`, `test_outbox_{relay,resync}.py`: DB caída, excepción de lote/principal, cero candidatos, varios fallos coalescidos, reintento de recuperación sin nuevo evento, reautorización y un RESYNC mínimo por episodio/sid; sin desconexión masiva, gracia ni replay. La denegación no bloquea cursor ni worker; recuperación parcial no abre otro tenant. |
| **S3 Productores/outbox** | `test_outbox_worker.py`, `test_outbox_probe.py` y pruebas de notificaciones rectificativas: transacción productor/outbox, tres eventos privados mínimos, fila histórica con timestamp, envelope/IDs estables; sonda visible en Redis pero no Socket.IO, F9/correo por handler y rechazados si se inyectan en stream. |
| **F1 Dispatcher/dedup** | `frontend/tests/realtime-dedup.test.ts`, `realtime-reload.test.ts` y prueba del composable real: tres IDs, sin depender de versión/timestamp, duplicados, vacío/malformado; un socket por contexto y callbacks/HTTP antiguos descartados. Públicos conservan los motivos y la deduplicación actuales. |
| **F2 Reconstrucción** | Prueba del composable `useMatchOperation`: RESYNC en acta terminal realmente hace GET pero no habilita edición; señal con acción ocupada provoca recarga trailing única; error HTTP, borrador y alineaciones no se pierden. Workspace/operación no añaden consumidor redundante de `MATCH_REPORT_RECTIFIED`. Recuperación no muestra datos de otra organización ni usa el evento como autorización. |
| **E1 Receptores reales** | Ampliar `realtime-workspace.spec.ts`, `realtime-operation.spec.ts` y fixtures: dos organizaciones, varias identidades/roles/sesiones/pestañas y sockets reales; capturar nombres/payloads antes del dispatcher. Comparar con GET autorizado, revocar mientras sigue abierto, controlar commit/evaluación desde el arnés, comprobar recepción y **ausencia** en desautorizados; evaluar antes del corte es el caso de tránsito permitido. |
| **E2 Recuperación/público** | Mismos E2E y `realtime-public.spec.ts`: interrupción de verificación privada manteniendo socket/conexión pública, recuperación por RESYNC+HTTP sin replay, estado terminal, cambio de organización, deduplicados, reconexión y stream trim/reset; APIs/payloads públicos de la matriz 020 sin F9 ni campos nuevos. Inyección de fallo solo en tests, no endpoint productivo ni seed de producción. |
| **L1 Eficiencia** | Backend/entorno de integración reproducible: 1.000 sockets/100 principales en un tenant → una llamada de autorización por evento, no 1.000; 257 principales → dos, más coste constante de contexto. Dos procesos, roles múltiples, ráfaga acotada, DB lenta/caída: medir consultas, latencias p50/p95, memoria y retraso; registrar dataset y resultados. No fijar un SLA inventado: aceptación estructural es llamadas acotadas, sin cola/memoria creciente ni permisos cacheados. |

RF-004/008 no se demostrarán con una restricción de lectura inventada: hoy quitar `match_officials` o un permiso de escritura no revoca una lectura general. Los tests de paridad deben exigir que HTTP y socket coincidan; tests condicionales de la función pura cubren el requisito para reglas que lo necesiten. F1 no se considera validada por esas fixtures.

Comandos previstos en implementación/validación, desde el entorno cargado y directorios indicados en AGENTS/CI:

```sh
# backend/; PostgreSQL y rol de aplicación para las pruebas DB, según AGENTS/CI
pytest -q tests/test_realtime_policy.py tests/test_realtime_delivery.py tests/test_realtime_delivery_db.py
pytest -q
python -m compileall -q app
ruff check .
bandit -r app -ll

# frontend/
pnpm test
pnpm run typecheck
pnpm run lint
pnpm run build
pnpm run typecheck:e2e
pnpm run e2e:test

# raíz; además de las pruebas de migración limpia/actualizada del runner actual
sh -n infra/postgres/migrate.sh
docker compose config -q
```

Completar los gates `infrastructure`/`security` existentes: perfil de producción con secretos externos de prueba, contratos/versiones y runner MIGRATION_TARGET, pip-audit, auditoría pnpm con filtro constitucional, Trivy fijado y Gitleaks según comandos autoritativos de `.github/workflows/ci.yml`/AGENTS. No rebajar exclusiones para pasar. Verificar CI de `pull_request` y `push`; E2E solo en PR/push main conforme al workflow. `verificacion.md` futuro debe registrar salidas, condiciones, limitaciones y revisión humana; no se certifica ejecución ni inspección visual desde este plan.

## 9. Trazabilidad RF-001–RF-020

| RF | Componente / archivos principales | Tests y aceptación |
|---|---|---|
| RF-001 | Catálogo, adaptador y fanout; `realtime_policy.py`, `realtime_authorization.py`, `main.py`. | D1/S1/E1: solo llega el evento completo al lector HTTP del recurso. |
| RF-002 | Membresía real y recursos por RLS; nueva migración, adaptador. | D1/D3/E1: tenant B y plataforma sin membresía no reciben existencia ni IDs de A. |
| RF-003 | Hechos multirrol; adaptador/función SQL, referencia `permissions.py`. | P2/D1/D2: unión efectiva conforme a HTTP; roles homónimos no se mezclan y no se elige uno por prioridad. |
| RF-004 | Predicado condicional; `realtime_policy.py` y paridad HTTP. | P2/D1: permiso y asignación/exención solo si la lectura lo exige; lecturas actuales sin oficial no se endurecen. |
| RF-005 | Reglas de operación/versiones y señales de su contexto; catálogo y rutas de referencia. | D1/E1: miembro lector sin permiso de escritura ni oficial sigue recibiendo. |
| RF-006 | Handshake y gate por lote; `main.py`, adaptador/SQL. | P2/D1/S1: sesión/JWT/usuario/membresía reales, datos del cliente no conceden autorización. |
| RF-007 | Snapshot fresco y `evaluation_time`; adaptador/SQL. | P2/D2/E1: revocación/desactivación confirmada y expiración bloquean evaluaciones posteriores. |
| RF-008 | Lectura nueva de roles/permisos/oficiales; adaptador/SQL. | D1/D2: retirada afecta solo a lecturas que dependían de ella; rol restante se conserva, sin caché antigua. |
| RF-009 | Evaluaciones sin caché de denegación; gate/recuperación. | D2/S2/E1: concesión permite siguientes actualizaciones tras nueva comprobación, sin historial. |
| RF-010 | Registro/generación de conexión; `main.py`, `useRealtime.ts`, consumidores. | P3/S1/F1/E1: evento/HTTP anterior no modifica nuevo usuario/tenant. |
| RF-011 | Gate en relay, no productor/worker; adaptador y `main.py`. | D2/S1: evento creado antes y evaluado después del commit usa autorización nueva; tránsito previamente aprobado permitido. |
| RF-012 | Clasificación/referencias cerradas; `realtime_policy.py`, SQL. | P1/D1/S1/S3: desconocido, sonda, scope incoherente y referencia cruzada no llegan. |
| RF-013 | Proyección de whitelist; `realtime_policy.py`, `rectifications/notifications.py`. | P1/S3/F1/E1: solo `event_id,match_id,tournament_id`, IDs íntegramente autorizados. |
| RF-014 | Suspensión por principal/lote; adaptador y relay. | S2/E2/L1: DB/error indeterminado no entrega, no usa gracia, no desconecta masivamente ni frena público. |
| RF-015 | Recarga HTTP; `useApi.ts`, Workspace y `useMatchOperation.ts`. | F2/E1/E2: GET vuelve a autorizar, sin reconstrucción de negocio desde evento ni permiso de escritura implícito. |
| RF-016 | Carril público separado; `main.py`, página pública sin cambio. | S1/E2 y regresiones públicas: mismos tres nombres/campos/rooms, privados nunca al torneo. |
| RF-017 | Estado suspendido/RESYNC; `main.py`, `useRealtime.ts`, `realtimeReload.ts`, consumidores. | S2/F2/E2: reautoriza, RESYNC sin recursos y GET del contexto vigente, incluidos terminales; cero replay. |
| RF-018 | Agrupación y dedup existentes; relay, `realtimeDedup.ts`, coordinador. | P3/F1/F2/E2/L1: no sockets duplicados ni recargas añadidas por el filtro para un mismo ID/cambio lógico. |
| RF-019 | Catálogo sin F1; `realtime_policy.py` y documentación. | P1/S3: borrador futuro/lectura no aprobada denegados; F8 no declara implementada F1. |
| RF-020 | Exclusiones catálogo y handlers; worker/relay. | P1/S3/E2: F9 no entra en Redis por su handler ni en Socket.IO incluso si se inyecta allí; matriz pública intacta. |

## 10. Decisiones confirmadas el 2026-11-13

El usuario confirmó C1–C4 tal como estaban recomendadas al aprobar expresamente el **plan** el 2026-11-13 («Apruebo el plan.»). Las alternativas se conservan como justificación de las elecciones, no como dudas abiertas. Las alternativas que incumplen DA-2 o RLS se rechazan, no se ofrecen como excepción constitucional.

| Decisión | Elección aprobada | Alternativas descartadas y motivo |
|---|---|---|
| **C1. Autorización eficiente y migración** | Función batch `SECURITY INVOKER` en nueva 055, lotes de 256 principales, transacción/snapshot nuevos por lote, sin caché de autorización; núcleo puro y adaptador separado (§3). | A: evaluar en Python con consultas agrupadas/contexto por principal; evita función nueva pero multiplica viajes y contexto RLS. B: generaciones transaccionales+caché validada en DB; puede ahorrar hechos pero requiere cubrir todos los escritores y sigue leyendo generación. TTL/pubsub sin barrera se descarta por DA-2. Función/migración y límite inicial confirmados. |
| **C2. Contrato privado y compatibilidad** | Conservar nombres actuales y tres entradas por rectificación; invalidación Socket.IO solo `{event_id,match_id,tournament_id}`. `version_id/scope` internos; aceptar timestamp histórico sin emitirlo. Sin callback frontend nuevo para `MATCH_REPORT_RECTIFIED`. | A: conservar `version_id` en wire, aun legible pero no necesario para consumidores actuales. B: evento privado único con nombre nuevo; más migración de clientes, no aporta una lectura nueva y altera la granularidad de dedup. No se ofrece conservar negocio privado: DA-3 ya lo descartó. |
| **C3. Recuperación y sobre de control** | Marca por sid/generación, reintento en ciclo de 30 s y antes de próxima entrega; tras reautorizar contexto, un `RESYNC` dirigido con motivo existente `RELAY_START` para reactivación del tramo privado. No replay ni nueva variable/contrato público. | A: `AUTHORIZATION_RECOVERED` nuevo, más preciso pero clientes actuales rechazan motivo desconocido y las pestañas abiertas exigirían transición compatible. B: recuperar solo al siguiente evento, no garantiza reconstrucción si no llegan más cambios. Desconexión masiva/gracia no son alternativas admitidas por DA-4. |
| **C4. Partición y despliegue** | Tres PR dependientes A→B→C, gate privado+ajuste mínimo de recarga frontend juntos en B; sustitución coordinada de procesos API antes de declarar activo (§11). | A: cinco PR separados contrato/backend/productores/frontend/cierre, pero deja entre merges un gate sin recuperación o clientes incompatibles. B: uno único, más difícil de revisar. Se pueden desarrollar por partes, nunca desplegar un estado que recupere fanout antiguo o afirme resolver R32f antes de los gates finales. |

## 11. División aprobada en PRs, dependencias y rollback

| PR | Alcance | Dependencia / criterio de fusión | Rollback seguro |
|---|---|---|---|
| **A — Núcleo y autorización inertes** | Catálogo/funciones puras, adaptador y migración batch no invocados aún por el relay; pruebas P1–P3/D1–D3/L1 y documentación del contrato. Sin cambiar entrega observable. | Plan aprobado y tareas posteriores aprobadas. CI y RLS de aplicación verdes; demostrar llamadas por principal/lote y barreras de corte. R32f continúa abierto hasta B/C; no anunciar protección nueva por A. | Retirar integración inerte, dejar migración append-only sin uso; corrección posterior por migración nueva, nunca borrar/editar 055 aplicada. |
| **B — Entrega privada, invalidaciones y recuperación end-to-end** | Activar gate/entrega sid y suspensión/RESYNC, productores privados mínimos con compatibilidad histórica; ajuste de recarga terminal/ocupada y aislamiento frontend. Mantener público/F9. Tests S1–S3/F1–F2 y E1/E2 mínimos con receptores reales. | A. No fusionar backend sin la recuperación compatible ni sin pruebas de no recepción y regresión pública. CI completa y despliegue de migración previo; reemplazar todos los API antiguos, sin fallback a rooms. | No volver al broadcast vulnerable. Release de contingencia probada que suspenda solo las entregas organizativas y mantenga HTTP/públicos mientras se corrige el gate; no borrar outbox ni migraciones. |
| **C — Regresión ampliada, seguridad y cierre** | Ráfagas/dos procesos, fallos y recuperación parcial, E2E ampliado, trazabilidad/evidencia, manual/README/AGENTS y estado final de spec/plan/tasks. | B. Backend/frontend/infra/security/E2E completos, comparación pública, evidencia del corte, carga L1 y revisión humana. Solo aquí proponer cierre R32f y aceptación de F8 como prerrequisito F1; no habilitar borradores. | Revertir documentación/test defectuoso sin desactivar protección. Si aparece fuga, mitigación fail-closed de B y bloqueo de cierre/F1. |

La división se descompone en `tasks.md` conforme a Fase 4; ese documento requiere aprobación expresa antes de implementar. No se declara despliegue productivo, aceptación humana de la implementación, CI futura ni revisión visual cumplidos.

## 12. Verificación constitucional

Verificación de **diseño**, no de ejecución. Sin excepciones solicitadas. El plan y sus decisiones fueron aprobados por el usuario el 2026-11-13, autorizando la fase Tareas; una prueba futura que contradiga RLS/paridad obliga a detenerse y revisar, no relajar la constitución.

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant | Sí | Contexto por principal y recursos por RLS; IDs cruzados denegados. D1/D3/E1. |
| §2.2 Sin superusuario/BYPASSRLS | Sí | Función invocadora, rol de aplicación real y grants mínimos; D3. |
| §2.3 Publicado inmutable | Sí | Solo lecturas y cambios de transporte; no actualización de actas, versiones, sanciones ni cierre. S3 y regresión completa. |
| §2.4 Esquema append-only | Sí con C1 | Nueva 055 o siguiente libre; no editar 032/054 ni migraciones aplicadas. D3. |
| §2.5 Público mínimo | Sí | Nombres/campos/rooms públicos sin cambio, sin datos personales; fotos/consentimiento intactos. S1/E2. |
| §2.6 Secretos fuera de desarrollo | Sí | Sin secretos/configuración nuevos ni logs de tokens/payloads; gates security existentes. |
| §2.7 Plataforma separada y auditada | Sí | No crear canal de plataforma ni derivar membresía de autorización 033/F9; D1/D3. |
| §2.8 Verificación honesta | Sí | Tests/CI/evidencia y revisión humana como gates; plan aprobado, tareas borrador, sin certificación de comportamiento futuro. |
| §2.9 Desarrollo fuera de producción | Sí | Fallos/candidatos demo solo en arnés de tests; sonda permanece local y no producto. S3/E2. |
| §3.1 BD/multi-tenancy | Sí | `set_rls_context` transaccional y contexto por usuario en función; RLS/FORCE existentes, migración limpia/actualizada, grants mínimos. |
| §3.2 Backend | Sí | Núcleo puro, adaptador SQL y orquestación; sin nuevo router HTTP; outbox permanece transaccional y worker no autoriza destinatarios por anticipado. |
| §3.3 Frontend | Sí | Composition API, `useApi`, contexto aislado, recargas/dedup compatibles, sin UI nueva ni omitir i18n/confirmaciones existentes. |
| §3.4 Seguridad/configuración | Sí | Fail-closed por destinatario, sin secretos nuevos; auditorías pip/pnpm con filtro, Bandit/Gitleaks/Trivy sin nuevas exclusiones. |
| §3.5 Infraestructura/CI | Sí | Versiones fijadas, WebSocket/proxy sin cambio, cinco jobs vigentes y migración previa; sustitución coordinada de API evita fanout antiguo. |
| §3.6 Rectificación/sanciones | Sí | Solo invalidar lectura de nuevas versiones; no cambia resolución/acta ni sus autorizaciones; F9 continúa fuera del canal. |
| §4 Todos: CI correspondiente | Sí | CI backend/frontend/infrastructure/security y E2E de PR; comprobar también push. Salidas pendientes de cada implementación. |
| §4 Todos: sin secretos/credenciales/datos personales | Sí | Fixtures sintéticas, controles mínimos, logs sin payload, escaneo del árbol comprometido. |
| §4 Todos: documentación observable | Sí | README/AGENTS/manual y evidencia actualizados en B/C; no declarar resuelto R32f antes de validación. |
| §4 Todos: pruebas del comportamiento | Sí | P/D/S/F/E/L, matriz RF completa, recepción/no recepción y fallo/recuperación. |
| §4 BD: migración nueva | Sí con C1 | 055 o siguiente libre; cualquier forward-fix con número nuevo. |
| §4 BD: tablas tenant con RLS/políticas | Sin tabla nueva | Se conservan ENABLE/FORCE/políticas existentes; si cambia C1 se rediseña esta sección antes de aprobar. |
| §4 BD: volumen limpio y ya migrado | Sí con C1 | D3: cero→última y 054→055, rol de aplicación y runner MIGRATION_TARGET. |
| §4 BD: `sh -n infra/postgres/migrate.sh` | Sí | Gate obligatorio, sin modificar runner para omitir migración. |
| §4 Backend: contexto RLS transaccional | Sí | §3/§6 y D3; ningún SELECT tenant sin su contexto válido. |
| §4 Backend: endpoints públicos sin sensibles | Sí | Sin nuevo endpoint/columna pública; comparación HTTP y eventos de la matriz 020. |
| §4 Backend: router registrado | No nuevo router | Integración en relay/lifespan de `main.py`, sin API nueva. |
| §4 Backend: `pytest -q` y `compileall` | Sí en implementación | Suite completa con DB además de unitarios, compilación; salidas futuras en evidencia. |
| §4 Frontend: HTTP por `useApi.ts` | Sí | No fetch directo de negocio desde handlers ni del sobre Redis. |
| §4 Frontend: tests/typecheck/build | Sí | Añadir lint y typecheck E2E, ejecutar runner; no aceptar solo asserts estáticos para recuperación. |
| §4 Infra: `docker compose config -q` | Sí en validación | Comprobar ambos perfiles y contratos de configuración existentes. |
| §4 Infra: sin defaults de desarrollo en producción | Sí | Sin variables nuevas; gate constitucional conserva rechazo de defaults. |
| §4 Dependencias: lockfiles/auditorías | Sin dependencias nuevas | No cambiar lockfiles ni versiones; mantener auditorías de CI, sin excepciones nuevas. |
| §5–6 Excepciones/revisión humana | Sí | Ninguna excepción; aprobación del plan, pruebas y revisión humana necesarias para declarar cumplimiento. |
