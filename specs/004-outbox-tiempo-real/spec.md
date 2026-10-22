# Spec 004 — Outbox y tiempo real: stream acotado, entregas deduplicables y resync

Estado: implementada, validada por @reviewer y cerrada (2026-10-20, commit `3b6210f`); §6 aprobada por el usuario (2026-10-22). CI en `main` en verde (cinco jobs, corrida de `9ad8db1` del 2026-10-22) y checklist de T008 completo.

## Contexto y objetivo

La auditoría técnica integral del 2026-10-19 registra dos hallazgos **MEDIOS** que afectan al mismo camino: el worker de outbox publica en un stream de Redis y el relay de la API lo reenvía por Socket.IO.

- **R13.** El worker escribe con `XADD` sin `MAXLEN` (`backend/app/workers/outbox.py:36`), así que el stream crece sin límite mientras el proceso vive. Además, el relay arranca en `"0-0"` (`backend/app/main.py:212`) y, en cada reinicio de la API, reemite por Socket.IO todo el histórico retenido desde el inicio del stream.
- **R14.** La entrega es *at-least-once*: el worker puede reescribir un evento si el `XADD` tuvo éxito y el `complete` falló, o si la plataforma reencola un evento fallido con `requeue_outbox_events`. Ni el sobre del stream ni el objeto emitido a Socket.IO llevan un identificador estable de la fila del outbox, de modo que el frontend no puede deduplicar y cada reentrega provoca recargas repetidas.

El estado actual, verificado al redactar:

- La tabla `outbox_events` ya tiene `id UUID PRIMARY KEY` (`infra/postgres/init/01_schema.sql:792`). El worker ya incluye ese valor como `id` en el JSON del stream, pero el relay lo descarta y emite solo el `payload` de dominio.
- El relay emite el mismo payload a `organization:{organization_id}` y, para `MATCH_CLOSED`, `MATCH_UPDATED` y `STANDINGS_UPDATED` con `tournament_id`, también a `tournament:{tournament_id}` (`backend/app/main.py:167-201`).
- La página pública `/tournaments/{id}` refresca cada 30 s mientras el socket no está conectado (`frontend/app/pages/tournaments/[id].vue:189-191`). Las páginas del Workspace (`/workspace` y la operación de partido) **no** tienen polling de respaldo: dependen solo de Socket.IO.
- `useRealtime` despacha todos los eventos recibidos por `socket.onAny` a un handler genérico y a los handlers específicos (`frontend/app/composables/useRealtime.ts:100-105`). No deduplica.
- El relay no usa grupos de consumo ni persistencia de posición: cada réplica de la API lee el stream desde su propia posición y emite a sus propios clientes.

**Objetivo:** acotar la memoria del stream, hacer que el relay arranque en el último id y no reenvíe el histórico, añadir un identificador estable de entrega que permita al frontend descartar duplicados, y emitir una señal de **resync** cuando el relay detecte un salto de continuidad o cuando un socket entre en una sala, para que el cliente recargue desde la API HTTP. El transporte sigue siendo *at-least-once* desde el outbox al stream y de mejor esfuerzo desde el stream al cliente; la fuente de verdad es PostgreSQL y la API HTTP.

## Alcance

Incluye:

1. `MAXLEN` aproximado en cada `XADD` del worker, con el tope fijo de 10 000 entradas y una semántica de retención explícita.
2. Arranque del relay en el último id del stream, sin reemisión del histórico, y reglas distintas para el reinicio del relay y para la pérdida de conexión con Redis con el proceso vivo.
3. Contrato de `event_id` en el sobre del stream y en el objeto emitido por Socket.IO, con compatibilidad para mensajes sin él.
4. Deduplicación de entregas en el frontend, acotada en memoria y aplicada antes de invocar cualquier handler.
5. Señal de resync desde el backend y reconciliación de los consumidores, incluida la cobertura del hueco entre la carga HTTP inicial y la entrada del socket en la sala.
6. Pruebas unitarias de worker, relay, resync y deduplicación, y su ejecución en los jobs actuales de CI.
7. Documentación de la semántica de pérdida, las garantías por tramo, la deduplicación y el tope fijo.

## No objetivos

- No se busca entrega **exactamente una vez**. Se conserva *at-least-once* desde el outbox al stream; la deduplicación es del lado del consumidor y es de mejor esfuerzo.
- No se busca entrega duradera, reanudable ni con acuse de recibo del cliente. El stream no pasa a ser un registro histórico.
- No se persiste la posición del relay entre procesos ni se introducen grupos de consumo.
- No se cambia el modelo de eventos de dominio, los nombres de evento existentes, las salas existentes, los payloads de dominio ni las proyecciones públicas.
- No se convierte Redis en fuente de verdad de ningún estado visible.
- No se persigue una cota exacta de memoria: `MAXLEN` aproximado acota el orden de magnitud, no el byte exacto.

## Decisiones cerradas (2026-10-19)

Aprobadas por el usuario. El plan no puede reabrirlas.

- **P-1 = A. Tope fijo de 10 000 entradas como constante del backend.** `MAXLEN` aproximado de 10 000 entradas, sin variable de entorno ni cambios en Compose o `.env.example`. *Motivo:* evita el drift de configuración (R20); el cierre de un partido produce 3 eventos y 10 000 entradas cubren varios días de operación normal con unos pocos MB. *Descartada:* variable `OUTBOX_STREAM_MAXLEN`, que añade configuración sin beneficio operativo demostrado.
- **P-2 = A. Arranque en el último id del stream.** Cero reemisión histórica; la corrección de lo perdido llega por resync, polling y reconciliación. *Motivo:* elimina la reemisión masiva en cada reinicio sin convertir el stream en un registro duradero. *Descartada:* reemitir las últimas N entradas, que duplica entregas y hace depender la corrección de la deduplicación.
- **P-3 = A. `event_id` como campo aditivo al mismo nivel.** El objeto emitido es `{...payload, event_id}`, preservando los campos de dominio. *Motivo:* compatibilidad con `payloadTargetsTournament` y con todos los consumidores actuales. *Descartada:* envolver el payload en `{event_id, payload}`, que rompe el contrato vigente.
- **P-4 = A. Recarga al restablecerse la conexión.** `/workspace` y la operación de partido recargan tras una reconexión, no en la primera conexión; la carga inicial se completa con el `JOIN` de entrada, sin recarga de reconciliación. La página pública conserva su polling de 30 s y no recarga por reconexión ordinaria. *Motivo:* recupera los eventos perdidos sin duplicar la carga inicial ni añadir polling al Workspace. *Descartada:* polling periódico adicional en el Workspace, con más carga sobre la API.
- **P-5 = A. Señal de resync desde el backend.** El relay emite el evento `RESYNC` cuando detecta un salto de continuidad y cuando un socket entra en una sala; el frontend recarga al recibirlo según su política. *Motivo:* cubre huecos que ni la reemisión histórica ni la reconexión resuelven (recorte del stream, pérdida de datos de Redis y el hueco entre la carga HTTP inicial y la entrada en la sala) sin convertir el stream en un registro duradero. *Descartada:* confiar solo en el polling y la reconexión, que deja sin cubrir el hueco inicial y los recortes.

## Usuarios

- **Espectador público:** consulta el marcador y la clasificación de un torneo. Espera que la vista se actualice sola y que un reinicio o un recorte no la deje desactualizada ni la inunde de recargas.
- **Operador o administrador de organización:** sigue el estado de los partidos desde el Workspace y depende del tiempo real para operar. Necesita que un evento perdido no le oculte un resultado cerrado.
- **Mantenedor o desarrollador:** necesita que el stream no crezca sin control, que el arranque no reemita el histórico y que las pruebas cubran la semántica nueva, incluido el resync.
- **Operador de plataforma:** despliega y reinicia servicios. Necesita que el comportamiento tras un reinicio, una pérdida de conexión con Redis o un recorte esté definido y documentado, sin pasos manuales.
- **Revisor humano de cambios:** necesita criterios verificables para aprobar el cambio conforme a la constitución.

## Roles y visibilidad

**No cambia el modelo de acceso.** El cambio no introduce ni modifica roles, permisos, rutas, membresías ni endpoints.

- Las salas siguen siendo `organization:{organization_id}` y `tournament:{tournament_id}`; un socket entra en una sola de ellas. La emisión pública de eventos de dominio sigue limitada a `PUBLIC_REALTIME_EVENTS`.
- `RESYNC` no transporta datos de negocio, identificadores de organización, de torneo ni de partidos: solo `event_id` y `reason`. No altera qué ve cada rol ni permite inferir datos de otra organización.
- La emisión de `RESYNC` se dirige únicamente a salas que ya tienen sockets conectados y autorizados; no crea salas ni amplía el alcance de un socket.
- El filtrado por rol dentro de la sala de organización (hallazgo R32) queda fuera de alcance.

## Historias de usuario

- **HU-1.** Como operador de plataforma, quiero que el stream de Redis tenga un tope para que un fallo del worker o del relay no consuma memoria sin límite.
- **HU-2.** Como operador de plataforma, quiero que al reiniciar la API no se reemita todo el histórico por Socket.IO, para no saturar a los clientes ni la base de datos con recargas.
- **HU-3.** Como espectador, quiero que un reinicio, un recorte o una pérdida de conexión con Redis no me deje con un marcador viejo, aunque el evento se haya perdido.
- **HU-4.** Como operador de organización, quiero que una reentrega del mismo evento no dispare recargas duplicadas ni parpadeos en la operación del partido.
- **HU-5.** Como mantenedor, quiero pruebas que fijen la semántica de pérdida, reanudación, resync y deduplicación para no depender de supuestos al cambiar el relay.
- **HU-6.** Como revisor, quiero que la semántica de «qué se pierde y cómo se recupera» esté escrita y sea verificable, para aprobar el cambio sin inferencias.

## Definiciones

- **Stream de outbox:** el stream de Redis `bracket_craft.events` (`backend/app/core/outbox.py`) que el worker alimenta y el relay consume. Es un canal de transporte, no un registro duradero ni la fuente de verdad.
- **Sobre del stream:** el JSON que el worker escribe en el campo `event` de cada entrada. Contiene `event_id`, `id` (legado, durante la transición), `organization_id`, `event_type` y `payload`.
- **`event_id`:** identificador estable e inmutable de una fila de `outbox_events`; es su `id` UUID, se conserva en reintentos y reencolados y es único por evento. Es opaco para el frontend: se compara por igualdad, no se parsea.
- **Evento de dominio:** los eventos existentes (`MATCH_CLOSED`, `MATCH_UPDATED`, `STANDINGS_UPDATED`) con su payload de negocio (`match_id`, `tournament_id`).
- **`RESYNC`:** evento de control emitido por el backend, no escrito en el stream, que pide a los clientes de una sala recargar desde la API HTTP. Su payload mínimo es `{event_id, reason}`.
- **`reason` de `RESYNC`:** valor cerrado entre `JOIN`, `RELAY_START`, `STREAM_TRIMMED` y `REDIS_RESET`.
- **`MAXLEN` aproximado:** `XADD ... MAXLEN ~ N`, que recorta en bloques internos de Redis y deja la longitud alrededor de N, no exactamente N. El recorte elimina las entradas más antiguas.
- **Tope del stream:** constante del backend de 10 000 entradas aplicada como `MAXLEN` aproximado en cada escritura; no es configurable por entorno.
- **Posición del relay:** el último id de stream procesado por el proceso de la API. Vive solo en memoria del proceso; no se persiste.
- **Reinicio del relay:** arranque de un proceso nuevo del relay. Resuelve la posición en el último id del stream y **no reemite** ninguna entrada anterior. Los clientes que se reconecten reciben `RESYNC` con `reason=JOIN`.
- **Pérdida de conexión con Redis (proceso vivo):** el relay sigue en el mismo proceso pero pierde la conexión con Redis. Al reconectar conserva su posición y **reanuda** desde ahí, reenviando las entradas retenidas que sigan existiendo; puede producir duplicados. Si detecta un reinicio de datos de Redis (`run_id` distinto) o la posición ya no es alcanzable, salta al final y emite `RESYNC` `REDIS_RESET`.
- **Hueco (gap):** intervalo de entradas que el relay no reenviará porque fueron recortadas, porque Redis perdió datos o porque el proceso no estaba activo. No se reconstruye desde el stream; se cubre con `RESYNC`, polling o reconciliación.
- **Transporte vivo de mejor esfuerzo:** el relay solo reenvía eventos que ocurren mientras está conectado y con clientes conectados. Un evento no entregado no se reintenta por Socket.IO.
- **Reconciliación:** recarga de datos desde la API HTTP por parte de un consumidor, para corregir cualquier estado perdido por el canal de tiempo real. No usa el stream ni depende de eventos.
- **Deduplicación:** descarte, en el cliente, de una entrega cuyo `event_id` ya fue procesado en la sesión de socket actual, antes de invocar cualquier handler.
- **Ventana de deduplicación:** conjunto acotado de los últimos 200 `event_id` procesados, con descarte FIFO del más antiguo al superar el tope.
- **Reentrega:** mismo evento con el mismo `event_id` recibido más de una vez (reintento del worker, reencolado, relectura del relay o reenvío accidental).
- **Reconexión (cliente):** conexión exitosa posterior a una conexión exitosa previa en la misma página, con al menos un handshake fallido entre ambas; un cierre de transporte observado también cuenta como reconexión a efectos de recarga. La conexión inicial desde `connecting` no es una reconexión. El botón «Reintentar» (R18) queda fuera de alcance y no forma parte de esta definición.
- **Ventana de inicialización:** periodo desde el montaje de la página hasta procesar el primer `RESYNC` con `reason=JOIN` y completar la carga inicial. Un `RESYNC` de entrada dentro de esta ventana se absorbe en la carga inicial; no genera una recarga adicional.
- **Coalescencia:** con una recarga en curso, las solicitudes nuevas no se encolan sin límite: se marca una sola recarga *trailing* y la última solicitud gana para el disparo; el reset de paginación es acumulativo. Al terminar la recarga en curso se ejecuta como máximo una recarga trailing.
- **Despliegue progresivo:** convivencia temporal de un worker anterior (sobre sin `event_id`) con un relay nuevo, o al revés. La compatibilidad es obligatoria en ambos sentidos.

## Garantías por tramo

| Tramo | Garantía | Consecuencia |
|---|---|---|
| `outbox_events` → stream | **At-least-once** | Un evento puede escribirse más de una vez con el mismo `event_id`; no se promete orden estricto entre reintentos ni entre réplicas del worker. |
| Stream → relay | **Al menos una lectura por entrada retenida** mientras el proceso está conectado | El avance por entrada puede repetir como máximo la última entrada tras un fallo; el recorte puede eliminar entradas antes de que se lean. |
| Relay → cliente (Socket.IO) | **Best-effort** | Hay huecos posibles (reinicio del relay, recorte, pérdida de conexión con Redis, cliente desconectado) y duplicados posibles (reentrega o relectura). Se mitigan con `RESYNC`, deduplicación, polling y reconciliación; no se eliminan. |
| Cliente → API HTTP | **Fuente de verdad** | Cualquier estado visible debe poder reconstruirse con una recarga HTTP; el tiempo real es una optimización, no la fuente. |

`RESYNC` es una notificación de control, no un evento duradero: no se escribe en el stream, no se reintenta y no se recupera si no hay clientes conectados. Los clientes que entren después reciben `JOIN` y los que estén conectados en el momento del hueco reciben `RESYNC` con el motivo correspondiente.

## Requisitos funcionales

### RF-001 — Stream acotado con `MAXLEN` aproximado

CUANDO el worker publica un evento del outbox en el stream, EL SISTEMA lo escribe con `MAXLEN` aproximado de 10 000 entradas definido como constante del backend, de forma que la longitud del stream no crezca sin límite.

*Criterios de aceptación:*
- Toda escritura del worker en el stream incluye `MAXLEN` aproximado (`~`) con exactamente 10 000 entradas (P-1). No queda ninguna ruta de escritura sin tope.
- El tope es una constante del backend. No se añade ninguna variable de entorno, no se modifica `backend/app/core/config.py` para incorporar un ajuste nuevo y el diff no toca `docker-compose.yml`, `docker-compose.production.yml` ni `.env.example`. No hay drift de configuración.
- El recorte es aproximado: la longitud puede superar el tope en el margen de los bloques internos de Redis; la spec no exige una cota exacta y la documentación lo dice.
- El sobre conserva `organization_id`, `event_type` y `payload` de dominio sin cambios; la **única** adición es el campo `event_id` de RF-004. Esta excepción explícita elimina la contradicción con RF-004.
- El comportamiento del worker ante éxito o fallo del `XADD` no cambia.
- El recorte solo puede eliminar entradas antiguas; no altera entradas recientes ni el id asignado por Redis.
- La prueba unitaria con un Redis falso exige el modo aproximado (`approximate=True` o el argumento equivalente que produzca `MAXLEN ~`) y `maxlen=10000`. No basta con comprobar que existe un tope; se verifica también que no se use recorte exacto. No requiere un Redis real ni un servicio nuevo en CI.

### RF-002 — Arranque y reanudación del relay sin reemisión histórica

CUANDO el proceso del relay arranca con Redis disponible, EL SISTEMA resuelve la posición inicial en el último id del stream (P-2) y no reenvía ninguna entrada anterior. SI el stream está vacío, ENTONCES deja la posición sin entradas y entrega la primera que se publique después.

*Criterios de aceptación:*
- **Reinicio del relay (proceso nuevo):** sobre un stream no vacío, no se reenvía ninguna entrada anterior al arranque. La prueba verifica el comportamiento observable (no se emiten entradas previas), no un literal `"0-0"`.
- **Stream vacío al arrancar:** no se emite nada; la primera entrada publicada después se entrega con normalidad.
- **Redis no disponible al arrancar:** el relay reintenta y, en la primera conexión exitosa, resuelve el final del stream y no reemite lo acumulado durante la indisponibilidad. La prueba cubre este caso.
- **Pérdida de conexión con Redis con el proceso vivo:** conserva la última posición en memoria y reanuda desde ahí al reconectar. Las entradas publicadas durante la caída se reenvían mientras la posición siga siendo igual o posterior a la entrada más antigua retenida. Esta reanudación puede producir duplicados; el `event_id` y la deduplicación los absorben.
- **Detección de reinicio de datos de Redis:** el relay registra el identificador de ejecución de Redis (`run_id` de `INFO server`) al conectar. SI al reconectar el `run_id` cambió, ENTONCES trata la conexión como pérdida o reinicio de datos: emite `RESYNC` `REDIS_RESET` y resuelve la posición al final, aunque Redis conserve datos. Es una decisión conservadora que prioriza la reconciliación sobre el reenvío de un backlog dudoso. SI `INFO server` no está disponible, ENTONCES usa solo las comprobaciones de posición, registra la limitación y no falla el relay.
- **Comprobación del recorte:** en cada ciclo de lectura, antes de bloquear en `XREAD`, el relay compara su posición con la entrada más antigua retenida. El coste es una consulta acotada (`XRANGE - + COUNT 1` o equivalente) por ciclo y por réplica, sin consultas a PostgreSQL. La comprobación se repite también al establecer o restablecer la conexión.
- SI la posición es anterior a la entrada más antigua retenida (recorte activo), ENTONCES el relay emite `RESYNC` con `reason=STREAM_TRIMMED` (RF-010) y salta al final del stream; no reemite el backlog retenido. La prueba usa un recorte activo, no simulado por ausencia de datos.
- SI la posición es mayor que el último id del stream, o el stream está vacío con una posición previa (pérdida o reinicio de datos de Redis), ENTONCES emite `RESYNC` con `reason=REDIS_RESET` y vuelve a resolver la posición al final.
- **Reinicio de la tarea del relay dentro de un proceso vivo:** emite `RESYNC` con `reason=RELAY_START` a las salas con sockets conectados y resuelve la posición al final. Cubre la ventana en la que la tarea no estuvo leyendo.
- **Avance de la posición:** avanza **por entrada**, después de emitirla u omitirla, no por lote. SI el proceso falla después de emitir una entrada y antes de avanzar, la relectura repite como máximo esa última entrada; la deduplicación la absorbe. La prueba lo cubre.
- La reanudación no introduce grupos de consumo, claves de posición persistidas ni cambios en la topología de Redis.
- El relay conserva el comportamiento actual ante entradas malformadas: las omite sin bloquear las siguientes.
- El arranque no añade consultas a PostgreSQL ni bloquea el inicio de la API; la resolución de posición y las comprobaciones ocurren dentro de la tarea del relay.

### RF-003 — Reconciliación de los consumidores y política de recarga

EL SISTEMA garantiza que cualquier estado visible pueda reconstruirse desde la API HTTP y aplica una política de recarga distinta según el consumidor, sin lanzar dos cargas iniciales del cliente ni encadenar recargas de reconciliación.

*Criterios de aceptación:*
- La documentación declara, sin ambigüedad, qué se pierde: eventos anteriores al arranque del relay, eventos emitidos mientras el relay está caído, eventos recortados por `MAXLEN`, eventos perdidos por un reinicio de datos de Redis y eventos ocurridos mientras un cliente está desconectado. Ninguno se reenvía por Socket.IO.
- **Política por consumidor:**

  | Consumidor | Conexión inicial | Reconexión | `RESYNC` `JOIN` tras inicializar | `RESYNC` de hueco |
  |---|---|---|---|---|
  | Página pública | Carga inicial completada con el primer `JOIN`; sin recarga de reconciliación | No recarga; mantiene el polling de 30 s mientras está desconectada | Ignora | Recarga y reinicia la paginación |
  | `/workspace` y operación de partido | Carga inicial completada con el primer `JOIN`; sin recarga de reconciliación | Una recarga, disparada al procesar el `JOIN` de esa reconexión | Recarga | Recarga |

- **Reconexión en Workspace:** la recarga por reconexión se ejecuta una sola vez y se dispara al procesar el `JOIN` posterior a la reconexión, no en el evento `connected`, para incluir el hueco hasta la entrada en la sala. SI el `JOIN` no llega (por ejemplo, fallo de emisión), ENTONCES se usa `connected` como respaldo una sola vez, sin temporizador repetitivo.
- **Coalescencia:** cada consumidor mantiene como máximo una recarga en curso y una recarga *trailing*. SI llega una solicitud (reconexión, `RESYNC` o evento de dominio) mientras hay una recarga en curso, ENTONCES no se lanza otra petición concurrente: se marca la trailing y gana la última solicitud para el disparo. No hay cola ilimitada ni ráfagas. El **reset de paginación es acumulativo**: si cualquiera de las solicitudes coalescidas lo requiere, la recarga trailing se hace desde la primera página. Al terminar la recarga en curso se ejecuta como máximo una recarga trailing.
- La página pública mantiene el refresco periódico de 30 s mientras el socket no está conectado; el valor no se reduce ni se elimina. La reconexión ordinaria no dispara una recarga adicional en la página pública. Se ignoran los `JOIN` posteriores a una inicialización que ya procesó su `JOIN`; si la inicialización se cerró sin él (por ejemplo, el socket no conectó), el primer `JOIN` posterior la completa con una carga.
- **Ventana de inicialización:** la carga inicial del cliente se completa después de procesar el primer `RESYNC` `JOIN`. Los datos obtenidos antes (por ejemplo, por SSR) son provisionales y no cuentan como una segunda carga: no se lanzan dos cargas de cliente ni una recarga de reconciliación. La inicialización no se marca completa hasta procesar el `JOIN`, por lo que el hueco entre la primera carga HTTP y la entrada en la sala queda cubierto con una única carga inicial del cliente. SI el socket no conecta o el `JOIN` no llega, ENTONCES la ventana se cierra con la carga HTTP normal y la página no se bloquea esperando el evento.
- Una recarga de reconciliación usa la API HTTP a través de `useApi` (o los stores que ya la usan); no consulta el stream ni introduce endpoints nuevos.
- La reconciliación es idempotente: repetirla no altera el estado ni produce efectos secundarios.
- Si una recarga falla, el consumidor conserva los datos previos y su estado de error actual, y **no** programa reintentos automáticos: el siguiente intento ocurre en la próxima reconexión, en el siguiente `RESYNC` o por una acción del usuario (recarga manual o polling).
- **Paginación pública:** un `RESYNC` de hueco reinicia la paginación a la primera página y descarta las páginas adicionales cargadas. Es la opción más simple y evita mezclar páginas con un conjunto de datos que cambió. Una recarga que se cruce con una carga de página adicional la descarta y deja la trailing como única recarga pendiente.
- Un `RESYNC` `JOIN` recibido después de la inicialización no reinicia la paginación pública porque la página pública lo ignora.
- La UI no muestra un estado «conectado» que oculte datos sabidamente viejos: mientras el socket no está conectado, el estado de tiempo real sigue reflejando `connecting`, `reconnecting` o `error` como hoy.

### RF-004 — `event_id` estable en el sobre del stream

CUANDO el worker publica un evento, EL SISTEMA incluye en el sobre un `event_id` no vacío igual al `id` de la fila de `outbox_events`, conserva `id` durante la transición y exige que ambos coincidan cuando coexistan.

*Criterios de aceptación:*
- El sobre contiene `event_id` con el mismo valor que el `id` de la fila reclamada; es único por evento y no cambia entre reintentos ni tras un reencolado.
- **Transición:** el worker nuevo escribe también `id` con el mismo valor. Mientras coexistan, el relay exige `event_id == id`; si difieren, usa `event_id` como canónico y registra la anomalía sin payload, sin descartar el evento. Retirar `id` del sobre requiere otra spec.
- El `payload` de dominio se escribe sin añadir, quitar ni renombrar campos; `event_id` vive en el sobre, no dentro del payload del stream.
- **Precedencia y nulos:** el relay usa `event_id` si es una cadena no vacía; si falta, es `null`, no es cadena o está vacía, usa `id` si cumple la misma condición; si ninguno es válido, trata el evento como «sin identificador». No se inventa un identificador ni se convierte `null` en texto.
- El relay acepta mensajes de un worker anterior que solo traen `id`: usa ese valor como `event_id` para que la deduplicación funcione durante un despliegue progresivo.
- SI el sobre no trae un identificador válido, ENTONCES el relay reenvía el evento sin `event_id` (no lo descarta) y registra una advertencia sin payload ni datos personales, para no romper la compatibilidad.
- La prueba unitaria cubre: sobre nuevo con `event_id == id`; sobre legado con `id`; `event_id` inválido con `id` válido; `event_id` e `id` distintos; ni `event_id` ni `id`; `event_id: null`; `event_id` numérico; y sobre malformado.

### RF-005 — `event_id` en el emit de Socket.IO

CUANDO el relay reenvía un evento de dominio, EL SISTEMA incluye `event_id` al mismo nivel que los campos del payload emitido, tanto en la sala de organización como en la de torneo, sin cambiar los nombres de evento, las salas ni los campos existentes.

*Criterios de aceptación:*
- El objeto emitido contiene todos los campos del payload de dominio más `event_id` (P-3). `match_id`, `tournament_id` y el resto conservan nombre, tipo y valor.
- Las dos emisiones del mismo evento (organización y torneo) llevan el mismo `event_id`.
- **`event_id` del payload de dominio:** si el payload trae un campo `event_id`, se elimina del objeto emitido y nunca se usa para deduplicar; solo cuenta el `event_id` que añade el servidor desde el sobre. La prueba verifica que un `event_id` de dominio no aparece en el emit ni sustituye al del servidor.
- Un evento sin `event_id` en el sobre se emite con el payload de dominio tal cual, sin campo añadido, y no se descarta (compatibilidad de RF-004).
- La lógica de emisión de eventos de dominio a la sala pública sigue limitada a `PUBLIC_REALTIME_EVENTS` y a la presencia de `tournament_id`; `event_id` no altera esa decisión. `RESYNC` no forma parte de `PUBLIC_REALTIME_EVENTS` y se rige por RF-010.
- Las pruebas del relay se actualizan para exigir `event_id` en el emit y cubrir los casos con y sin identificador, incluido el payload de dominio con `event_id`.

### RF-006 — Deduplicación de entregas en el frontend

CUANDO el cliente recibe un evento con un `event_id` ya procesado en la sesión de socket actual, EL SISTEMA descarta la entrega antes de invocar el handler genérico y los handlers específicos, de modo que una reentrega no produzca recargas ni efectos repetidos.

*Criterios de aceptación:*
- La deduplicación se aplica en el único punto de despacho de `useRealtime` (`socket.onAny`), antes de invocar el handler genérico y los handlers específicos, de forma que un evento único invoca el handler genérico y el específico exactamente una vez, y un duplicado no invoca ninguno.
- La clave es `event_id` por igualdad, sin parsear ni asumir formato UUID. No se usa el nombre del evento como parte de la clave. Se aplica también a `RESYNC`.
- Solo se deduplica un `event_id` que sea cadena no vacía en el nivel superior del objeto recibido. SI el payload no es objeto, o `event_id` falta, es `null`, está vacío o no es cadena, ENTONCES la entrega se acepta siempre; no se deduplica a ciegas.
- Un `event_id` aportado por el payload de dominio no se considera identificador de entrega: el servidor lo elimina del objeto emitido (RF-005) y el frontend solo lee el nivel superior del evento emitido.
- La ventana de deduplicación es de 200 identificadores con descarte FIFO del más antiguo; no crece con el número de eventos de la sesión.
- **Vaciado de la ventana:** se vacía en (a) cualquier socket lógico nuevo (nueva instancia de `io(...)`) o cambio de `scopeKey`, incluidos organización A→organización B y torneo público A→torneo público B; (b) al ejecutar `disconnect()` sobre el composable; (c) al destruirse el composable. **El auto-reconnect de Socket.IO no vacía la ventana**, porque es la misma sesión lógica y la deduplicación debe sobrevivir a la reentrega.
- Un evento descartado no produce ninguna petición HTTP, recarga, navegación ni cambio de estado; en particular, no altera el estado de conexión.
- La deduplicación y el despacho se implementan como una utilidad pura, sin dependencias de Nuxt ni del socket, de modo que las pruebas invocan el despacho dos veces con el mismo payload y comprueban que los handlers se ejecutan una sola vez. Es verificable con `node --test --experimental-strip-types`.
- Las pruebas cubren: primera entrega aceptada; duplicado rechazado sin invocar handlers; identificadores distintos aceptados; evento sin identificador aceptado siempre; `event_id` nulo, vacío o no cadena aceptado; desalojo tras 200; vaciado al cambiar de alcance (incluidos A→B del mismo tipo), al desconectar y al destruir; reentrega aceptada tras el vaciado; y que el auto-reconnect **no** vacía la ventana.

### RF-007 — Sin migraciones ni cambios de esquema, REST o configuración

EL SISTEMA satisface R13, R14 y la señal de resync sin migraciones de base de datos, sin modificar contratos HTTP REST, proyecciones públicas, Compose ni configuración por entorno.

*Criterios de aceptación:*
- No se añade ni se edita ninguna migración en `infra/postgres/migrations/`, ni scripts de `infra/postgres/init/`; el diff no incluye archivos de esas rutas.
- `outbox_events` conserva su esquema; `event_id` se deriva de la columna `id` existente.
- No cambian endpoints REST, esquemas de respuesta, permisos, vistas públicas ni el seed de demostración.
- No cambian las tablas, políticas RLS ni privilegios del rol de aplicación.
- No se introducen secretos ni variables nuevas; el diff no toca `docker-compose.yml`, `docker-compose.production.yml` ni `.env.example`.
- **Cambios observables permitidos:** el campo aditivo `event_id` en los eventos de dominio emitidos y el evento de control `RESYNC` con su contrato de RF-010. No se cambian los nombres ni los payloads de los eventos de dominio existentes.
- Los consumidores que ignoran eventos desconocidos siguen funcionando; `RESYNC` es aditivo y no requiere una versión nueva de Socket.IO.

### RF-008 — Pruebas y verificación en CI

CUANDO se ejecutan las verificaciones del proyecto, EL SISTEMA prueba el comportamiento nuevo en los jobs existentes, sin añadir servicios de infraestructura a CI.

*Criterios de aceptación:*
- El job `backend` ejecuta, como mínimo, estas pruebas unitarias con dobles de Redis (sin PostgreSQL ni Redis reales):
  1. Escritura con `maxlen=10000` y modo aproximado; el sobre conserva `organization_id`, `event_type` y `payload` salvo `event_id`.
  2. Sobre nuevo con `event_id == id`; `id` legado conservado; sobre antiguo solo con `id`; discrepancia `event_id != id` usa `event_id` y no descarta.
  3. Precedencia y nulos: `event_id` válido; `null`; vacío; numérico; sin identificador válido; evento malformado.
  4. Emit con `event_id` en las salas de organización y de torneo; `match_id` y `tournament_id` conservados; `event_id` del payload de dominio eliminado.
  5. Reinicio del relay con stream no vacío: no se emite ninguna entrada anterior y se entrega la siguiente.
  6. Reinicio del relay con stream vacío: no se emite nada y se entrega la primera entrada nueva.
  7. Redis no disponible al arrancar: reintenta, resuelve el final en la primera conexión exitosa y no reemite lo acumulado.
  8. Pérdida de conexión con Redis con el proceso vivo: reanuda desde la última posición y reenvía lo retenido.
  9. Recorte activo (posición anterior a la entrada más antigua): emite `RESYNC` `STREAM_TRIMMED`, salta al final y no reemite el backlog.
  10. Pérdida o reinicio de datos de Redis: cambio de `run_id`, posición mayor que el último id, o stream vacío con posición previa; emite `RESYNC` `REDIS_RESET` y resuelve al final.
  11. Reinicio de la tarea del relay con salas conectadas: emite `RESYNC` `RELAY_START`.
  12. `RESYNC` `JOIN` dirigido al socket que entra en la sala, en organización y en torneo público.
  13. `RESYNC` de hueco a las salas con sockets conectados, ninguno si no hay sockets, y un fallo de `sio.emit` no interrumpe el relay.
  14. Avance de posición por entrada: un fallo después de emitir y antes de avanzar repite como máximo la última entrada; la deduplicación la descarta.
  15. Entrada malformada: se omite y las siguientes se reenvían.
- El job `frontend` ejecuta pruebas de las utilidades puras de deduplicación, despacho y política de recarga que cubren:
  1. Deduplicación: primera aceptada; duplicado sin handlers; ids distintos; sin id; `null`/vacío/no cadena; desalojo tras 200; vaciado por socket/scopeKey nuevo (incluido A→B del mismo tipo), por `disconnect()` y por destrucción; reentrega tras vaciado; auto-reconnect sin vaciado.
  2. Despacho: evento duplicado no invoca handlers; `RESYNC` se entrega como evento; un `RESYNC` repetido con el mismo `event_id` no provoca una segunda recarga; el handler genérico y el específico se invocan una vez.
  3. Detección de reconexión: conexión inicial no es reconexión; conexión exitosa tras un handshake fallido sí; conexión tras cierre de transporte observado sí.
  4. Política de recarga: una recarga por reconexión en Workspace y operación, disparada por el `JOIN` de la reconexión con `connected` como respaldo si el `JOIN` no llega; ninguna recarga de reconciliación en la conexión inicial, donde el `JOIN` completa la carga inicial sin una segunda carga; si el socket no conecta, la inicialización se cierra con la carga HTTP; la página pública no recarga por reconexión ordinaria; `JOIN` tras inicializar recarga Workspace y no público; `STREAM_TRIMMED`/`REDIS_RESET`/`RELAY_START` recargan todos y reinician la paginación pública.
  5. Coalescencia: una solicitud durante una recarga en curso marca una trailing; varias solicitudes dejan una sola; una resync o reconexión durante una recarga no lanza peticiones concurrentes; al terminar se ejecuta una única trailing; la última solicitud gana el disparo y el reset de paginación es acumulativo.
  6. Fallo de recarga: conserva datos y estado; no programa reintentos automáticos.
  7. Paginación: un `RESYNC` de hueco vuelve a la primera página; un `JOIN` posterior a la inicialización no la reinicia en público.
- La lógica de despacho, deduplicación, detección de reconexión, coalescencia y reset de paginación se extrae a utilidades puras; no se prueba el DOM ni se añaden dependencias de test nuevas. Si alguna parte no se puede aislar, se documenta por qué y se cubre con la prueba de la utilidad que sí lo está.
- Los comandos de verificación local son los mismos que los de CI y deben pasar:
  ```sh
  cd backend && pytest -q
  cd backend && python -m compileall -q app
  cd frontend && pnpm test
  cd frontend && pnpm run typecheck
  cd frontend && pnpm run build
  ```
- Se actualizan las pruebas existentes del relay (`backend/tests/test_hardening.py`) para el nuevo contrato, sin eliminar la cobertura de entradas malformadas.
- No se añaden servicios ni jobs a `ci.yml` ni se depende de `RUN_DATABASE_TESTS=1`; los jobs son los de la §4 de la constitución (`backend`, `frontend`, `infrastructure`, `security` y, desde la enmienda 1.4.0, `e2e`).
- Si alguna verificación no puede ejecutarse en el entorno local, se declara expresamente en la evidencia; no se infiere el verde.
- El cierre exige los cinco jobs de CI (`backend`, `frontend`, `infrastructure`, `security` y `e2e`) en verde sobre el commit de `main`.

### RF-009 — Documentación de la semántica, las garantías y el resync

CUANDO se cierre el cambio, EL SISTEMA documenta la nueva semántica en los documentos de estado actual, de forma que operadores y revisores no dependan del código para saber qué se pierde y cómo se recupera.

*Criterios de aceptación:*
- `README.md` y `AGENTS.md` describen el stream como transporte vivo de mejor esfuerzo, el tope fijo de 10 000 entradas (aproximado), el arranque en el último id, la ausencia de reemisión histórica, la diferencia entre **reinicio del relay** y **pérdida de conexión con Redis con el proceso vivo**, la reconciliación y el polling de 30 s de la página pública.
- La documentación reproduce la tabla de **Garantías por tramo**: outbox→stream *at-least-once*; stream→cliente *best-effort* con huecos y duplicados posibles; API HTTP como fuente de verdad.
- Se documenta `event_id`: de dónde sale, que es aditivo, que el `id` legado se conserva durante la transición y cómo lo usa el frontend para deduplicar.
- Se documenta `RESYNC`: nombre, `reason`, payload mínimo, a qué salas se emite, comportamiento sin clientes conectados, política por consumidor y su relación con la deduplicación.
- Se documenta que el tope es una constante del backend, sin variable de entorno, y el criterio de dimensionamiento; no se documenta ninguna variable nueva ni se modifica `.env.example` o Compose.
- `MEMORY.md` registra el cierre de la spec con su evidencia, sin secretos ni datos personales.
- No se declara resuelto ningún hallazgo distinto de R13 y R14; R32, R18 y el resto siguen citados como fuera de alcance.

### RF-010 — Señal de resync

CUANDO el relay detecta un salto de continuidad (recorte del stream, pérdida o reinicio de datos de Redis, o reinicio de la tarea), EL SISTEMA emite el evento `RESYNC` a las salas con sockets conectados. CUANDO un socket entra por primera vez en una sala, EL SISTEMA le emite `RESYNC` dirigido a ese socket.

*Criterios de aceptación:*
- **Nombre y tipo:** el evento se llama `RESYNC` y se emite por Socket.IO como evento independiente, no como un `event_type` del outbox. No se escribe en el stream ni se persiste.
- **Payload mínimo:** `{ "event_id": "<cadena opaca no vacía>", "reason": "JOIN" | "RELAY_START" | "STREAM_TRIMMED" | "REDIS_RESET" }`. No incluye `organization_id`, `tournament_id`, `match_id` ni datos de negocio.
- **`event_id`:** sintético, generado por el servidor, único por emisión y con prefijo que lo distingue de un UUID del outbox (por ejemplo `resync:`). Participa en la deduplicación de RF-006 como cualquier otro evento; no procede de `outbox_events` ni se reutiliza entre emisiones.
- **Registro de handlers:** el cliente registra sus handlers antes de iniciar la conexión, de modo que el `RESYNC` `JOIN` no se pierde por orden de registro.
- **`JOIN`:** se emite al `sid` que acaba de entrar en la sala, después de `enter_room`, tanto en organización como en torneo público. Es la cobertura del hueco entre la carga HTTP inicial y la entrada en la sala: el cliente lo absorbe en la ventana de inicialización y completa su carga inicial tras él, sin una recarga de reconciliación.
- **`STREAM_TRIMMED`:** se emite cuando la posición del relay es anterior a la entrada más antigua retenida (RF-002).
- **`REDIS_RESET`:** se emite cuando la posición es mayor que el último id del stream, cuando el stream está vacío con una posición previa, o cuando cambia el `run_id` de Redis al reconectar (RF-002).
- **`RELAY_START`:** se emite cuando la tarea del relay arranca dentro de un proceso vivo con salas ya conectadas (RF-002).
- **Salas de destino:** `JOIN` va solo al socket que entra. Los resync de hueco van a cada sala `organization:*` y `tournament:*` que tenga al menos un socket conectado en el momento de la emisión. No se puede determinar la organización afectada desde un stream ya recortado; la emisión a todas las salas conectadas es segura porque el payload no contiene datos y solo provoca una recarga.
- **Sin clientes conectados:** no se emite nada y no se guarda para después; el siguiente socket que entre recibe `JOIN`. No hay reintento ni persistencia del resync.
- **Relación con la deduplicación:** un `RESYNC` repetido con el mismo `event_id` se descarta en el cliente; uno nuevo con otro `event_id` provoca la recarga que corresponda. Un `RESYNC` no se confunde con un evento de dominio.
- **Sin bucles:** la emisión de `RESYNC` no altera la posición del relay ni provoca nuevas detecciones; el cliente no responde con otro evento y una recarga no emite `RESYNC`. La única recarga adicional posible es la trailing acotada de RF-003.
- **Despacho separado:** el cliente distingue `RESYNC` de los eventos de dominio y no lo entrega a los handlers de `MATCH_CLOSED`, `MATCH_UPDATED` ni `STANDINGS_UPDATED`. Un `RESYNC` no provoca un cambio de estado de conexión.
- **Fallo de emisión:** si `sio.emit` falla, el relay registra el error y continúa; el resync no se reintenta y la posición avanza según RF-002. La siguiente comprobación o el siguiente `JOIN` cubren el hueco.
- **Compatibilidad:** un cliente anterior que ignora eventos desconocidos sigue funcionando; `RESYNC` es aditivo y no cambia las salas ni los permisos.
- **Pruebas:** `JOIN` dirigido al socket correcto; emisión de cada motivo en su condición; ausencia de emisión sin sockets; payload mínimo sin datos de negocio; `event_id` único y con prefijo; deduplicación de un `RESYNC` repetido; y que un `RESYNC` no reinicia el relay ni genera otro `RESYNC`.

## Requisitos no funcionales

- **RNF-001. Memoria acotada.** El stream no supera el orden de magnitud del tope fijo y la ventana de deduplicación del cliente no crece con la sesión. El relay no acumula el stream en memoria: procesa por lotes como hoy.
- **RNF-002. Privacidad.** `event_id` es un identificador interno del outbox y `RESYNC` no transporta datos de negocio ni personales. Ni los logs de salto de hueco ni las advertencias de compatibilidad incluyen payloads, documentos ni fechas.
- **RNF-003. Determinismo de las pruebas.** Las pruebas no dependen de red, reloj, orden no determinista ni de un Redis real; usan dobles y datos fijos.
- **RNF-004. Compatibilidad de despliegue progresivo.** Worker nuevo con relay anterior y relay nuevo con worker anterior funcionan sin pérdida de eventos ni errores. La ausencia de `event_id` degrada la deduplicación, nunca la entrega. Un cliente que ignora `RESYNC` sigue recibiendo los eventos de dominio.
- **RNF-005. Sin degradación perceptible.** El `MAXLEN` no añade latencia apreciable al `XADD`; el arranque del relay añade una consulta de posición por conexión y la comprobación de recorte añade una consulta acotada por ciclo de lectura; la deduplicación es una comprobación en memoria de coste constante.
- **RNF-006. Trazabilidad.** La spec, la evidencia de verificación y `MEMORY.md` registran las decisiones P-1 a P-5 aprobadas, los comandos ejecutados y el resultado de CI.
- **RNF-007. Fallo cerrado en lo que importa.** Un mensaje malformado no bloquea el relay; una imposibilidad de deducir la posición inicial no provoca una lectura del histórico sobre un stream no vacío (se reintenta la resolución o se salta al final). Un fallo de `RESYNC` no bloquea el relay.
- **RNF-008. Garantías explícitas.** La documentación y la spec declaran las garantías por tramo: *at-least-once* del outbox al stream, *best-effort* del stream al cliente con huecos y duplicados posibles, y la API HTTP como fuente de verdad. No se promete *exactly-once* en ningún tramo.

## Datos personales y privacidad

**No aplica** a datos de jugadores. El cambio no toca altas, importaciones, proyecciones públicas ni consentimiento de imagen. `event_id` es un UUID interno de la fila del outbox y no identifica a una persona. Los payloads de dominio emitidos siguen siendo los mismos (`match_id`, `tournament_id`). `RESYNC` solo contiene `event_id` y `reason`; no incluye identificadores de organización, torneo o partido. Las advertencias y registros del relay no incluyen payloads ni datos personales.

## Casos límite

1. **Stream vacío al arrancar el relay:** no se emite nada; la primera entrada nueva se entrega.
2. **Redis no disponible al arrancar:** el relay reintenta; en la primera conexión exitosa resuelve el final del stream y no reemite lo acumulado.
3. **Reinicio del relay (proceso nuevo):** posición en el último id, sin reemisión; no se emite `RESYNC` de hueco porque no hay continuidad que recuperar. Los clientes que se reconecten reciben `JOIN`.
4. **Reinicio de la tarea del relay con el proceso vivo:** emite `RELAY_START` a las salas conectadas y resuelve al final; los clientes recargan una vez.
5. **Pérdida de conexión con Redis con el proceso vivo:** reanuda desde su posición; los eventos retenidos se reenvían y los duplicados se deduplican. No se emite `RESYNC` salvo que la posición ya no sea alcanzable o cambie el `run_id` de Redis.
6. **Recorte por `MAXLEN` antes de que el relay lea:** posición anterior a la entrada más antigua; emite `STREAM_TRIMMED`, salta al final y no reemite el backlog.
7. **Redis pierde los datos o se reinicia:** cambio de `run_id`, posición mayor que el último id o stream vacío con posición previa; emite `REDIS_RESET` y resuelve al final; no se queda bloqueado esperando ids futuros.
8. **Hueco entre la carga HTTP inicial y la entrada en la sala:** el `JOIN` dirigido cubre el hueco; el cliente lo absorbe en la ventana de inicialización y completa una sola carga.
9. **Hueco sin clientes conectados:** no se emite nada; el siguiente `JOIN` cubre la inicialización y el polling/reconexión cubre lo perdido.
10. **Cliente público desconectado:** los eventos de la desconexión no se reenvían; el polling de 30 s lo cubre y, al reconectar, no hay recarga por reconexión ordinaria. Un resync de hueco sí recarga. Puede persistir un hueco menor que el intervalo de polling hasta el siguiente resync; es la consecuencia aceptada de no recargar por reconexión.
11. **Cliente de Workspace desconectado:** los eventos de la desconexión no se reenvían; al reconectar recarga una vez. Un `JOIN` o un resync de hueco se coalescen con esa recarga.
12. **Resync o reconexión durante una recarga en curso:** no se lanza una petición concurrente; se marca una trailing y se ejecuta al terminar. Varias solicitudes dejan una sola trailing.
13. **Recarga fallida:** se conservan los datos y el estado de error; no hay reintentos automáticos hasta la próxima reconexión, resync o acción del usuario.
14. **Paginación pública cargada:** un resync de hueco vuelve a la primera página y descarta las páginas adicionales; una carga de página adicional en curso se descarta y deja la trailing como única recarga.
15. **Worker reintenta tras un `XADD` exitoso y un `complete` fallido:** el mismo evento vuelve al stream con el mismo `event_id`; el frontend descarta la segunda entrega.
16. **Evento reencolado con `requeue_outbox_events`:** conserva su `id`; si el cliente nunca lo recibió, se entrega; si ya lo recibió, se descarta (la recarga es idempotente).
17. **Despliegue progresivo con worker anterior:** el sobre trae `id` y no `event_id`; el relay lo deriva y el frontend deduplica igual.
18. **Sobre con identificador inválido:** `event_id` ausente, `null`, vacío o no cadena, y `id` también inválido; se emite sin identificador y se registra una advertencia; no se descarta el evento.
19. **`event_id` e `id` distintos:** se usa `event_id`, se registra la anomalía y no se descarta el evento.
20. **Entrada malformada en el stream:** se omite sin bloquear las siguientes, como hoy.
21. **Varias réplicas de la API:** cada una lee el stream desde su propia posición y emite a sus propios clientes; un `STREAM_TRIMMED` o `REDIS_RESET` puede emitir resync desde más de una réplica y el cliente deduplica por `event_id`.
22. **Recorte aproximado:** la longitud puede exceder el tope en el margen de los bloques de Redis; se documenta como cota de orden de magnitud.
23. **Colisión de `event_id` con un campo del payload de dominio:** se elimina el del dominio; prevalece el del servidor.
24. **Duplicado fuera de la ventana de deduplicación:** puede volver a invocar el handler; las recargas son idempotentes y el coste está acotado por la ventana.
25. **Cambio de alcance del socket (organización A→B o público A→B):** la ventana de deduplicación se vacía; un evento del alcance anterior no se confunde con uno del nuevo. El auto-reconnect no la vacía.
26. **Volumen alto sostenido por encima de la capacidad del relay:** puede haber pérdida entre lectura y recorte; el resync, el polling y la reconciliación hacen converger la UI.
27. **Fallo al emitir `RESYNC`:** se registra y el relay continúa; no se reintenta y la siguiente comprobación o el siguiente `JOIN` cubren el hueco.
28. **Cliente que ignora `RESYNC`:** sigue recibiendo los eventos de dominio y el polling/reconexión lo mantienen funcional; no se rompe la compatibilidad.

## Criterios de finalización

1. R13 resuelto: toda escritura del worker usa `MAXLEN` aproximado con el tope fijo de 10 000 entradas y el relay no reemite el histórico al arrancar (RF-001, RF-002).
2. R14 resuelto: `event_id` estable en el sobre del stream y en el emit como `{...payload, event_id}`, con `id` legado y compatibilidad para mensajes sin él (RF-004, RF-005).
3. La semántica de pérdida y las garantías por tramo están definidas por escrito; cada consumidor aplica su política de recarga con coalescencia y sin lanzar dos cargas iniciales del cliente (RF-003, RF-009).
4. `RESYNC` está implementado con su contrato, cubre el hueco inicial con `JOIN` y los huecos por recorte, reinicio de datos de Redis y reinicio de la tarea (RF-010).
5. El frontend deduplica entregas con ventana de 200, vaciado por socket/scope nuevo, `disconnect()` y destrucción, y sin vaciado por auto-reconnect (RF-006).
6. No hay migraciones, cambios de esquema, REST, proyecciones ni configuración por entorno; los cambios observables son solo `event_id` y `RESYNC` (RF-007).
7. Pasan las pruebas concretas de RF-008: las 15 pruebas unitarias del backend con dobles de Redis y las pruebas de utilidades puras del frontend, incluidas reconexión, coalescencia, paginación, nulos y resync.
8. Pasan los comandos de verificación, idénticos a CI:
   ```sh
   cd backend && pytest -q
   cd backend && python -m compileall -q app
   cd frontend && pnpm test
   cd frontend && pnpm run typecheck
   cd frontend && pnpm run build
   ```
9. La documentación de estado actual describe la nueva semántica, el tope fijo, `event_id`, `RESYNC` y la ausencia de configuración nueva (RF-009).
10. Los cinco jobs de CI (`backend`, `frontend`, `infrastructure`, `security` y `e2e`) están en verde sobre el commit de `main` y el cambio tiene revisión humana distinta del autor.
11. Lo que no se pueda ejecutar se declara; no se afirma ninguna verificación no realizada.

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Pérdida de eventos durante reinicios, pérdidas de conexión con Redis o recortes | Vista desactualizada hasta el siguiente resync o reconciliación | `RESYNC` de hueco y `JOIN`, polling de 30 s y recarga al reconectar en Workspace y operación (RF-003, RF-010). |
| Tormenta de recargas tras un resync o una reconexión | Carga sobre la API y parpadeo de UI | Una recarga en curso más una trailing; sin cola ilimitada ni reintentos inmediatos. |
| Salto al final tras un recorte deja un hueco | Un evento concreto no se ve en tiempo real | `RESYNC` `STREAM_TRIMMED` a las salas conectadas; el cliente recarga desde la API. |
| Resync broadcast a todas las salas conectadas | Recargas innecesarias en organizaciones no afectadas | Payload vacío y una sola recarga coalescida por cliente; el coste es acotado y no hay filtración de datos. |
| `RESYNC` perdido porque no hay clientes | Un cliente conectado después no recibe el aviso de un hueco anterior | `JOIN` al entrar y API HTTP como fuente de verdad; no se intenta persistir el resync. |
| Tope de `MAXLEN` demasiado bajo | Pérdida en operación normal, no solo en caídas | Tope fijo de 10 000 entradas con criterio de dimensionamiento documentado; el tope es de transporte, no de negocio. |
| Deduplicación con ventana demasiado pequeña | Recargas repetidas ante muchas reentregas | Ventana fija de 200; un duplicado fuera de ventana solo repite una recarga idempotente. |
| Entrega at-least-once se percibe como exactly-once | Expectativas incorrectas | Documentación explícita de garantías por tramo y contrato de `event_id` como best-effort. |
| Despliegue progresivo con versiones mixtas | Pérdida de deduplicación o de eventos | `id` legado conservado, derivación en el relay y emisión sin `event_id` cuando falta; pruebas de ambos sentidos. |
| Varias réplicas de la API con posiciones distintas | Un cliente puede no recibir un evento si cambia de réplica al reconectar | Resync y reconciliación; las réplicas pueden emitir el mismo resync y el cliente deduplica. |
| Cambio futuro que reintroduzca `XADD` sin tope o arranque en el histórico | Regresión de R13 | Pruebas unitarias que fijan el tope y la ausencia de reemisión; revisión en cada cambio del relay. |

## Fuera de alcance

- Migraciones, cambios de esquema, limpieza o retención de filas de `outbox_events` y políticas de purga.
- Entrega exactamente una vez, acuses de recibo, reanudación por cliente, posición persistida, grupos de consumo o *dead-letter queue*.
- Persistencia o reintento de `RESYNC`; recuperación de un resync perdido por ausencia de clientes.
- Configuración de persistencia de Redis (AOF/RDB) y garantías de durabilidad del stream.
- Socket.IO con adaptador de Redis, escalado horizontal del relay o emisión entre réplicas.
- Cambiar los nombres o payloads de los eventos de dominio existentes; añadir `event_id` y `RESYNC` es lo único permitido.
- Filtrado por rol dentro de la sala de organización (R32) y cualquier cambio de autorización.
- El botón «Reintentar» del tiempo real (R18) y el ciclo de vida de estados de partido y torneo (R11).
- Cambiar `PUBLIC_REALTIME_EVENTS`, las proyecciones públicas o los endpoints REST.
- Endpoints nuevos o cambios en `useApi` más allá del uso existente para reconciliar.
- Observabilidad nueva (métricas, trazas, alertas) más allá de los registros descritos.
- Pruebas con Redis o PostgreSQL reales en CI; las pruebas nuevas son unitarias con dobles.
- Los demás hallazgos de la auditoría (R05, R06, R07, R09, R10, R12, R15-R17, R19-R32).

## Dudas abiertas

Ninguna.

**Evidencia de cierre (2026-10-22, `main` en `9ad8db1`):** `cd backend && pytest -q` con `RUN_DATABASE_TESTS=1` y base en 023 (999 passed), `python -m compileall -q app`, `pnpm test` (236 passed), `pnpm run typecheck`, `pnpm run build` y los cinco jobs de CI en verde, incluido `e2e`.
