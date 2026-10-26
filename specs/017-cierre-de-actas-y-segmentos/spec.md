# Spec 017 — Cierre de actas y segmentos

Estado: implementada (2026-10-25)

## Contexto y objetivo

El cierre de un acta reúne hoy **dieciocho comprobaciones** repartidas entre el esquema, la validación previa del cliente y el servicio, sin un inventario declarado ni un orden explícito: el orden real depende de dónde esté escrita cada comprobación. El acta se cierra con cinco resoluciones, cada una con su propia combinación de marcadores, y la única forma de corregirla es no cerrarla. Los segmentos se crean e interrumpen a mano, el cliente calcula el número siguiente y el minuto de reanudación por su cuenta, y no existe ninguna noción declarada de qué es un segmento más allá de lo que el código hace.

Esta spec fija **el orden único de validación del cierre**, la matriz de marcadores por resolución, la coherencia disciplinaria, la idempotencia, la inmutabilidad del acta confirmada y el ciclo de vida del segmento, incluida la propuesta de siguiente segmento calculada en el servidor.

**Objetivo:** que cerrar un acta sea predecible y verificable, que el acta confirmada no se pueda tocar y que reanudar un partido no dependa de que el cliente adivine dos números.

### Estado verificado (2026-10-25)

| # | Hecho verificado | Evidencia |
|---|---|---|
| 1 | El cierre ejecuta, en este orden real: carga del partido sin bloquear → bloqueo de fase y versión → destinos de avance → bloqueo del partido → permiso → estado → versión publicada → equipos → segmento activo → plantilla → segmentos → minutos → resolución habilitada → segmentos y eventos → sustituciones → marcador contra eventos → sanciones → escritura → clasificación y avance. | `backend/app/modules/matches/service.py:304-518` |
| 2 | Los **422 estructurales** los produce Pydantic **antes** del handler; la respuesta es `{"detail": [ {type, loc, msg} ]}`, saneada de `input` y `ctx`. | `backend/app/main.py:594-615`, `backend/app/modules/matches/schemas.py:55-144` |
| 3 | Los **409 de dominio** devuelven `detail` como **cadena**, con `code` aditivo opcional y sin caché. | `backend/app/main.py:690-701` |
| 4 | La autorización del cierre es una **conjunción**: permiso `CLOSE_MATCH_REPORT` **y** (rol `owner`/`administrator`/`operator` **o** asignado en `match_officials`). La resolución administrativa exige además rol `owner`/`administrator`. | `backend/app/core/permissions.py:22-75`; `service.py:323-338` |
| 5 | Un estado `suspended` no admite cierre, y ninguna ruta asigna `live` ni `suspended`. | `service.py:340-341` |
| 6 | Los goles se separan en reglamentarios y de prórroga con `event.minute <= regular_time_minutes`, **sin mirar `added_minute`**. | `service.py:750-789` |
| 7 | El marcador final se calcula con los eventos y se contrasta con lo informado; un empate solo es válido donde las reglas lo permiten y `GF1`/`GF2` exigen ganador. | `rules_engine/engine.py:387-422`, `:338-351`; `service.py:391-407` |
| 8 | La comparación de idempotencia de eventos **no** mira `metadata`. | `service.py:859-889` |
| 9 | Un resultado confirmado es inmutable en la base: el trigger rechaza cualquier cambio de marcador, ganador, estado, resolución o `result_confirmed`, y el borrado, sin excepción para administradores. | `infra/postgres/migrations/016_confirmed_match_result_immutability.sql` |
| 10 | Un acta confirmada tampoco admite eventos: el trigger rechaza `INSERT`/`UPDATE` de `match_events` en partidos terminados. | `infra/postgres/migrations/009_photo_resolution_and_outbox_hardening.sql:162-231` |
| 11 | Un segmento es una fila con número consecutivo, `minute_start`, `minute_end` opcional y estado `active`/`completed`/`interrupted`; es la unidad de los eventos y del saldo por equipo. | `infra/postgres/init/01_schema.sql:494-510`, `:549-562` |
| 12 | Crear un segmento con otro activo cierra el activo en el minuto de inicio del nuevo; el número debe ser consecutivo y el inicio no puede retroceder; el estado del partido no cambia. | `matches/router.py:629-756` |
| 13 | La interrupción guarda motivo y minuto, cierra el segmento y audita `INTERRUPT_MATCH_SEGMENT`; después el cliente pone a mano el número siguiente y el minuto de reanudación. | `router.py:759-868`; `frontend/app/pages/workspace/matches/[id].vue:712, 879-880, 910` |
| 14 | La operación es una lectura sin bloqueo del partido y no escribe. | `router.py:474-493` |
| 15 | Un `red_card` con `double_yellow_red` genera suspensión por roja **y** sus amarillas cuentan para la acumulación; nada comprueba que existan. | `rules_engine/engine.py:424-465` |
| 16 | El mismo defecto de tiempos responde **422** al crear el segmento (rango de la petición) y **409** al cerrar (regla de dominio sobre datos persistidos): son dos momentos distintos, no un código inestable. | `router.py:672-696` (422), `service.py:613-653` (409) |

### Dependencias con las otras specs

- **015 (catálogo y asistencias)** define los tipos, sus campos y la idempotencia del evento. Esta spec **ordena** esas comprobaciones dentro del cierre y añade las que faltan; no redefine el catálogo.
- **016 (walkover)** define la rama de walkover y **la implementa íntegramente**: la exención de segmento activo y de plantilla, el motivo obligatorio, el marcador derivado de `walkover_score`, su publicación y el preflight del cliente son suyos. Esta spec **no** la implementa ni la exige: hoy el cierre exige segmento activo y plantilla también para `walkover`, y **la 017 no cambia ese comportamiento**.
- **Contrato que esta spec ofrece:** el orden único, la autorización del cierre, la inmutabilidad del acta confirmada y la propuesta de segmento. La 016 los reutiliza; la 015 escribe su catálogo dentro del paso de estructura.

## Usuarios

- **Operador de partido o árbitro:** abre y reanuda segmentos, interrumpe y cierra el acta.
- **Administrador o dueño:** resuelve administrativamente y explica un resultado; revisa por qué se rechazó un cierre.
- **Observador (`viewer`):** consulta la operación en solo lectura.
- **Público:** ve el resultado y la alineación publicada; no ve el acta.
- **Mantenedor:** necesita el orden de validación y la matriz de marcadores escritos.

## Roles y visibilidad

- **Público:** sin cambios.
- **Miembro sin rol (403):** conserva el contrato vigente en toda ruta protegida.
- **Observador (`viewer`):** conserva la lectura de la operación (la ruta de lectura no exige permiso de cierre) y ninguna escritura: no crea ni interrumpe segmentos y no cierra.
- **Operador con el permiso y rol operativo:** cierra, crea e interrumpe.
- **Árbitro asignado en `match_officials` con el permiso:** cierra ese partido; en otro partido no pasa la conjunción.
- **Árbitro con el permiso pero no asignado:** **403** también en segmentos y en el cierre.
- **Observador asignado como oficial:** **403** por falta del permiso.
- **Dueño y administrador:** cierran y además pueden resolver administrativamente; no tienen ninguna vía sobre un acta confirmada.
- **Administrador de plataforma:** no aplica; `/admin` no edita resultados.
- **Aislamiento:** partido, segmento o equipo de otra organización responden **404**; un jugador no elegible o de otra organización responde **409** con su código.

## Historias de usuario

- **HU-1.** Como operador, quiero que el servidor me diga exactamente qué impide cerrar y en qué orden, sin descubrirlo con un error genérico.
- **HU-2.** Como operador, quiero reanudar tras una interrupción sin calcular a mano el número de segmento ni el minuto.
- **HU-3.** Como administrador, quiero que un acta cerrada no se pueda modificar por ninguna vía y que la interfaz lo diga sin tecnicismos.
- **HU-4.** Como responsable de la tabla, quiero que el marcador final no pueda contradecir los goles registrados.
- **HU-5.** Como mantenedor, quiero un único orden de validación y una matriz de marcadores por resolución.

## Definiciones

- **Acta.** Conjunto de eventos de un partido más su resultado; se compone en el cliente y el servidor la valida completa al cerrar. No hay registro incremental de eventos por API.
- **Acta confirmada.** Partido con `result_confirmed = TRUE`; su resultado y sus eventos son inmutables en la base de datos.
- **Segmento.** Ventana de tiempo del partido con número consecutivo, inicio, fin opcional y estado. Unidad de pertenencia de los eventos y del saldo de sustituciones por equipo. **No** es una mitad, ni un periodo reglamentario, ni un reloj independiente.
- **Interrupción.** Suspensión temporal de la cuenta del partido, con motivo y minuto, que cierra el segmento activo. Reanudar exige un segmento nuevo.
- **Propuesta de segmento.** `{segment_number, minute_start, derived}` que el servidor deriva de lo persistido. Es lectura: no crea nada.
- **Resolución.** `regular`, `extra_time`, `penalties`, `walkover` o `administrative`.
- **Gol reglamentario.** Gol cuyo `minute` es menor o igual a los minutos reglamentarios de la fase. El minuto añadido **no** interviene en esa clasificación.
- **Máximo efectivo.** Minuto máximo aplicable según la resolución, resuelto con la configuración efectiva de la fase. No es tiempo jugado.

## Decisiones cerradas

| Código | Decisión | Motivo |
|---|---|---|
| **D-1** (2026-10-25) | La funcionalidad se divide en tres specs; el cierre y los segmentos tienen la suya. | El orden de validación y el ciclo del segmento son verificables por separado. |
| **D-2** (2026-10-25) | La autorización del cierre es la **conjunción** real: permiso **y** (rol operativo **o** asignación como oficial). Sin permisos nuevos. | Es el criterio vigente verificado en el código y el usuario lo confirmó. |
| **DU-8** | Corrección y reapertura de actas cerradas **fuera de alcance**: exigen enmienda constitucional (§5.2, cambio propio) y spec propia. | El principio 3 es innegociable. |
| **DU-9** | Segmentos: **el servidor propone y el operador confirma**. | Una sola fuente para el dato propuesto, sin automatismo ni estados nuevos. |
| **DU-10** | Roja por doble amarilla exige **exactamente dos** amarillas previas del mismo jugador en el mismo partido; si no constan, **409**. | Coherencia de datos, no una regla nueva. |
| **D-4** (2026-10-25, corrección de QA) | La invariante «`detail` es cadena» aplica **solo a los 409**; los 422 devuelven una lista saneada. | Es lo que el manejador de errores hace y no debe prometerse lo contrario. |

## Requisitos funcionales

### Cierre del acta

- **RF-001.** CUANDO se reciba un cierre, EL SISTEMA aplicará **un único orden de dominio** y responderá sin escribir nada al primer incumplimiento: (1) sesión y organización; (2) permiso; (3) estado del partido y versión publicada; (4) dos equipos participantes; (5) resolución habilitada; (6) estructura del acta; (7) plantilla y participantes; (8) estado en campo y sustituciones; (9) asistente del gol; (10) coherencia disciplinaria; (11) marcador frente a eventos; (12) sanciones vigentes; (13) coherencia de la resolución y del ganador; (14) escritura.
  *Criterios de aceptación:*
  - El orden no depende del orden del payload ni del orden de las comprobaciones en el código.
  - La **existencia y el aislamiento** del partido se resuelven al cargarlo, antes del permiso, y responden **404** tanto si no existe como si es de otra organización; eso no revela nada y no cuenta como paso del orden de dominio.
  - **Excepción declarada:** los **422 estructurales** del esquema (campos y claves no aplicables, rangos del modelo, duplicados de `client_event_id` en el acta, más de 500 eventos) se resuelven **antes** del handler y **prevalecen** sobre cualquier paso del orden. Una petición con un defecto de dominio en el paso 3 y un campo no aplicable en el paso 6 recibe el **422**.
  - Entre defectos **de dominio**, una petición con dos informa el del paso anterior.
  - El `walkover` **no tiene rama en esta spec** (D-10): recorre este orden como cualquier resolución y hoy choca con los pasos 6 y 7 (segmento activo y plantilla). Que el paso 9 no tenga nada que validar en él se debe a que el esquema le prohíbe eventos, no a una exención; los pasos 8 y 11 **sí** conservan exenciones preexistentes para `walkover` y `administrative` (`_validate_substitutions` y `_validate_event_score_consistency`), que esta spec **hereda sin cambiarlas**, y el marcador del walkover se comprueba en el paso 13 contra `walkover_score`. La rama que lo exime de estructura, plantilla, estado en campo, asistente, disciplina, marcador contra eventos y sanciones pertenece **íntegramente a la spec 016** y no se implementa ni se exige aquí.
  - Si falla cualquier paso, no se escriben eventos, contadores, marcador, clasificación, avance, sanciones, auditoría ni outbox.

- **RF-002.** EL SISTEMA exigirá para cerrar **y** para abrir, cerrar o interrumpir un segmento el permiso `CLOSE_MATCH_REPORT` **y**, a la vez, rol `owner`, `administrator` u `operator` **o** estar asignado en `match_officials` para ese partido.
  *Criterios de aceptación:*
  - Un miembro con el permiso y sin rol operativo ni asignación responde **403**; uno asignado como oficial y sin el permiso, **403**.
  - La resolución administrativa exige **además** rol `owner` o `administrator` y conserva su permiso propio.
  - No se añade permiso, rol, delegación ni ámbito nuevo; un miembro sin rol conserva su **403** de contexto.
  - El orden de comprobación es el del RF-001: sesión, permiso, estado.

- **RF-003.** EL SISTEMA exigirá que la estructura del acta sea coherente.
  *Criterios de aceptación:*
  - Al menos un segmento, **también en `walkover`** (eximirlo es de la spec 016); números consecutivos y tiempos monótonos.
  - Eventos solo en segmentos activos o completados, y minuto dentro del intervalo de su segmento.
  - Minuto y minuto añadido dentro del máximo efectivo de la resolución: `minute ≤ max` y, salvo en el minuto final, `minute + added_minute ≤ max`.
  - Un incumplimiento de dominio es **409**; la duplicación de `client_event_id` dentro del acta es **422** (esquema).
  - **Mismo defecto, dos momentos:** un segmento con tiempos imposibles responde **422 al crearlo** (es el rango de la petición) y **409 al cerrar** (es una regla de dominio sobre datos ya persistidos). No es un código inestable: son dos operaciones distintas.

- **RF-004.** EL SISTEMA exigirá que participantes y plantilla sean coherentes.
  *Criterios de aceptación:*
  - Solo equipos participantes; al menos un jugador por equipo en la plantilla válida; elegibilidad por fecha del partido.
  - Cada evento con un jugador de la plantilla válida del equipo indicado; el beneficiario de un autogol participante y distinto.
  - Un evento de un jugador de otro equipo, fuera de la plantilla, antes de entrar, después de salir o tras la expulsión es **409**.
  - Un jugador de otra organización es **409**, nunca **404** ni un error de integridad.

- **RF-005.** EL SISTEMA validará el estado en campo y las sustituciones con el motor puro, antes de escribir una sola fila.
  *Criterios de aceptación:*
  - XI inicial de la plantilla; sustituciones y expulsiones aplicadas en orden canónico `(minute, added_minute, índice del acta)`.
  - Límites por equipo y partido, ventanas, reentrada y coherencia de contadores; toda violación es **409**.
  - La proyección por segmento y equipo se recalcula desde los eventos en orden de `segment_number`, nunca decrementando.

- **RF-006.** EL SISTEMA exigirá que una roja marcada como **doble amarilla** tenga **exactamente dos** amarillas previas del mismo jugador en el mismo partido.
  *Criterios de aceptación:*
  - Con cero, una o tres o más amarillas previas responde **409** con `code` aditivo `DOUBLE_YELLOW_INCONSISTENT`, sin escribir.
  - Se cuentan solo los eventos de ese partido, anteriores al minuto de la roja en orden canónico; las amarillas de otros partidos no cuentan.
  - La roja **directa** no se ve afectada y no exige amarillas.
  - No hay derivación automática: una segunda amarilla no crea una roja.
  - Las actas ya cerradas no se revalidan.

- **RF-007.** EL SISTEMA exigirá que el marcador sea coherente con los eventos y con la resolución, según la matriz declarada.
  *Criterios de aceptación:*
  - **Gol reglamentario:** `minute <= regular_time_minutes`; el minuto añadido **no** se tiene en cuenta para clasificar el gol, solo para el tope. Esta regla se conserva tal cual.
  - El reglamentario informado debe coincidir con los goles reglamentarios; el final con reglamentario + goles posteriores, según la resolución.
  - **Matriz por resolución** (obligatorio / opcional / prohibido):

    | Resolución | `home/away_score_regular` | `home/away_score` | `home/away_penalties` | `winner_team_id` | `reason` |
    |---|---|---|---|---|---|
    | `regular` | obligatorio | opcional, debe igualar el reglamentario | prohibido | opcional; nulo si hay empate | prohibido |
    | `extra_time` | obligatorio | obligatorio, ≥ reglamentario | prohibido | obligatorio | prohibido |
    | `penalties` | obligatorio | obligatorio, igual al reglamentario (empate) | obligatorios, con ganador | obligatorio | prohibido |
    | `walkover` | obligatorio y debe igualar `walkover_score` | opcional; si se informa, igual al configurado | prohibido | obligatorio | prohibido |
    | `administrative` | obligatorio | obligatorio, igual al reglamentario | prohibido | obligatorio | obligatorio (texto libre) |

  - Una resolución `regular` no admite goles posteriores al minuto reglamentario.
  - Informar un marcador final sin el reglamentario, o al revés, es **422**; un marcador final menor que el reglamentario es **409**.
  - Un empate solo es válido donde las reglas ya lo permiten; `GF1`/`GF2` exigen ganador y la repetición se activa con su regla.
  - El campo de la petición es **`reason`**; la columna es `resolution_reason`. Los dos nombres no se mezclan en la documentación ni en los mensajes.
  - La fila `walkover` describe el **comportamiento actual**, que esta spec **no** modifica. Su contrato objetivo —marcadores derivados y publicados, motivo obligatorio de catálogo y preflight del cliente— es de la **spec 016** y no se exige aquí.

- **RF-008.** EL SISTEMA mantendrá la idempotencia del acta y de sus eventos.
  *Criterios de aceptación:*
  - Un evento ya persistido e idéntico se reutiliza sin doble conteo; uno con datos distintos responde **409** «inmutable».
  - La comparación incluye `metadata` y el asistente (hoy no mira `metadata`).
  - El mismo `client_event_id` dos veces en la misma petición es **422**.
  - Un acta confirmada no admite un segundo cierre.

- **RF-009.** EL SISTEMA cerrará el acta de forma atómica.
  *Criterios de aceptación:*
  - Marcador, estado, contadores, suspensiones, clasificación, avance, auditoría y outbox se escriben en la misma transacción.
  - Un fallo en cualquier paso deja el partido exactamente como estaba.
  - Se emiten `MATCH_CLOSED`, `MATCH_UPDATED` y `STANDINGS_UPDATED`, sin añadir eventos nuevos.

- **RF-010.** EL SISTEMA mantendrá los códigos de respuesta y su forma.
  *Criterios de aceptación:*
  - Los **409** de dominio llevan `detail` como **cadena** y, cuando se declara, un `code` aditivo; esta invariante **no** aplica a los **422**.
  - Los **422** devuelven `{"detail": [ … ]}` saneado (sin `input` ni `ctx`), con `type`, `loc` y `msg`; no llevan `code`.
  - Códigos nuevos de esta spec: `DOUBLE_YELLOW_INCONSISTENT`; los de la 015 y la 016 se declaran en su spec.
  - Un cliente que ignore `code` conserva su comportamiento.

- **RF-011.** MIENTRAS un acta esté confirmada, EL SISTEMA la mantendrá inmutable y no ofrecerá ninguna vía de cambio.
  *Criterios de aceptación:*
  - No se añade ningún endpoint de reapertura, corrección o anulación, ni se relaja el trigger que protege un resultado confirmado.
  - La operación muestra «acta cerrada, no editable» y no ofrece acciones de escritura; no explica la constitución al operador.
  - La inmutabilidad alcanza al resultado y a sus eventos.
  - La justificación de por qué corregirla exige una enmienda constitucional y una spec propia vive en la documentación, no en la interfaz.

### Segmentos

- **RF-012.** EL SISTEMA tratará el segmento como una ventana de tiempo con número consecutivo, inicio, fin opcional y estado, y no como una mitad ni un periodo reglamentario.
  *Criterios de aceptación:*
  - No existe ni se añade ninguna noción de primer tiempo, segundo tiempo ni descanso.
  - Un partido puede tener cualquier número de segmentos, incluido uno solo.
  - La documentación y la interfaz lo nombran por su número y su intervalo, sin sinónimos de periodo.

- **RF-013.** CUANDO se cree un segmento mientras otro está activo, EL SISTEMA cerrará el activo en el minuto de inicio del nuevo, y rechazará un número no consecutivo o un inicio anterior al final del anterior.
  *Criterios de aceptación:*
  - El cierre del anterior y la creación del nuevo ocurren en la misma transacción.
  - Número no consecutivo o inicio anterior: **422**, con el mismo criterio que hoy.
  - La proyección por segmento y equipo se crea para el nuevo segmento.
  - Un partido terminado no admite segmentos nuevos (**409**).

- **RF-014.** CUANDO se interrumpa el segmento activo, EL SISTEMA registrará el motivo y el minuto, cerrará el segmento en ese minuto y no admitirá eventos en él.
  *Criterios de aceptación:*
  - Solo se interrumpe el segmento activo; otro estado es **409**.
  - Un minuto anterior al inicio del segmento es **422**.
  - Se conserva la auditoría `INTERRUPT_MATCH_SEGMENT`; las notas siguen admitiendo texto libre con su tope de 1 000 caracteres.
  - Un segmento interrumpido no admite eventos, ni en el borrador ni al cerrar.

- **RF-015.** CUANDO se consulte la operación de un partido, EL SISTEMA devolverá la propuesta del siguiente segmento derivada de lo persistido, sin crear ni modificar nada.
  *Criterios de aceptación:*
  - La forma es `next_segment: {segment_number: entero, minute_start: entero | nulo, derived: booleano}` o **nulo** cuando el partido es terminal o su versión no está publicada (no se podría crear ningún segmento).
  - `segment_number` es siempre el siguiente al último (1 si no hay segmentos).
  - `derived` es verdadero y `minute_start` informado en dos casos: último segmento **interrumpido** (el minuto de la interrupción) y último segmento **completado con fin** (su fin).
  - `derived` es falso y `minute_start` nulo cuando no hay nada de lo que derivarlo: último segmento **activo sin interrupción**, o último segmento **completado sin `minute_end`** (posible en datos históricos). El operador lo indica.
  - Sin segmentos, `segment_number` 1, `minute_start` 0 y `derived` verdadero (el comienzo del partido).
  - Consultar no escribe; tras interrumpir, solo cambia la propuesta.
  - El servidor sigue siendo la autoridad al crear: valida número y minuto con RF-013 y RF-014 aunque la propuesta sea correcta.
  - La propuesta es determinista y su campo es aditivo en la respuesta de operación.

- **RF-016.** EL SISTEMA no derivará de los segmentos ninguna regla deportiva nueva.
  *Criterios de aceptación:*
  - El máximo de minutos, la resolución prevista, el tope de minuto añadido y el bloqueo por jornada se resuelven como hoy.
  - Un segmento no cambia el estado del partido: no se introduce ninguna transición a `live` ni a `suspended`.
  - Los contadores de sustitución siguen siendo por equipo y partido, con el saldo por segmento como proyección.

- **RF-017.** SI falta un segmento activo, ENTONCES EL SISTEMA rechazará el cierre con **409** y la operación pedirá abrir o reanudar.
  *Criterios de aceptación:*
  - Sin segmento activo, el cierre es **409** y no escribe, **con cualquier resolución**.
  - La interfaz explica que hay que abrir o reanudar y ofrece la propuesta de RF-015.
  - El `walkover` **no** está exento hoy: también exige segmento activo. La exención la aportará la spec 016, no esta.

- **RF-018.** EL SISTEMA serializará las escrituras del partido con un orden de bloqueo estable y declarado.
  *Criterios de aceptación:*
  - El cierre bloquea **fase → versión → destinos de avance → partido → segmento activo → jugadores** (advisory por jugador).
  - Las rutas de segmento bloquean **solo el partido** y su segmento; no toman fase ni versión, así que no hay ciclo posible con el cierre.
  - Dos cierres simultáneos: el segundo espera, encuentra el partido confirmado y responde **409** sin escribir.
  - Cierre concurrente con una interrupción: si la interrupción llega antes, el cierre la ve y la respeta (el segmento ya no está activo); si llega después, encuentra el partido terminado y responde **409**.
  - Cierre concurrente con la creación de un segmento: la segunda operación ve el estado resultante; ninguna deja dos segmentos activos ni un cierre parcial.
  - El `walkover` no tiene un orden de bloqueo propio en esta spec: recorre el cierre completo. Cualquier cambio de bloqueo que introduzca su rama se justifica en el plan de la **016**.

### Transversales

- **RF-019.** EL SISTEMA conservará el contrato interno de reglas sin cambios: `engine_version` sigue en **`2026.1`** y no se añade ni retira ninguna clave de `rules_config`.
  *Criterios de aceptación:*
  - El cierre y los segmentos siguen leyendo la configuración efectiva de la versión publicada.
  - `docs/contrato-reglas.md` no cambia de versión ni de contenido normativo.

- **RF-020.** EL SISTEMA aplicará una única regla de identificadores y el aislamiento vigente.
  *Criterios de aceptación:*
  - Partido, segmento o equipo de otra organización: **404**.
  - Jugador no elegible o de otra organización: **409** con su código.
  - Toda consulta y validación se ejecuta con el contexto de aislamiento fijado en la transacción.

## Requisitos no funcionales

- **RNF-001 (aislamiento).** Ninguna consulta nueva cruza organizaciones; el contexto se fija dentro de la transacción antes de cualquier lectura del tenant.
- **RNF-002 (privacidad).** Ningún mensaje nuevo incluye nombres, documentos ni fechas de nacimiento. Las vías de texto libre del cierre se declaran: el **motivo administrativo** (`reason`, hasta 1 000 caracteres) y las **notas de interrupción** (`notes`, hasta 1 000 caracteres). No son datos personales por contrato y se conservan; podrían contenerlos, así que se documenta como **riesgo aceptado** y se recuerda que la auditoría los guarda tal cual. El `client_event_id` deja de ser texto libre en la 015.
- **RNF-003 (contratos que cambian).** Se declaran y se documentan: (a) la operación añade `next_segment` (aditivo y anulable); (b) el cierre informa el primer defecto de dominio según un orden declarado, de modo que una petición con varias faltas puede recibir un mensaje distinto al de hoy; (c) los 422 estructurales siguen prevaleciendo y **no** llevan `code`; (d) se añade el `code` `DOUBLE_YELLOW_INCONSISTENT` en **409**; (e) un 409 de dominio sigue con `detail` cadena; (f) **cambia un código de estado**: la coherencia numérica del marcador —final menor que el reglamentario, resolución `regular` con final distinto del reglamentario, `penalties` sin empate y tanda de penales igualada— pasa de **422** (esquema) a **409** (dominio), porque RF-007 la sitúa en el paso 13. **Salvedad:** un cliente que dependiera del **orden** de comprobación, de que un 422 no prevaleciera sobre un 409 o del **422** en esos cuatro casos observa un cambio; se documenta en `AGENTS.md` y en `README.md`.
- **RNF-004 (base de datos).** **Sin migración.** El orden de validación, la matriz de marcadores, la propuesta de segmento y la coherencia disciplinaria se resuelven en la API; no se añade columna, restricción ni índice, y la inmutabilidad ya existe en la 009 y la 016.
- **RNF-005 (verificación).** Pasan `cd backend && pytest -q`, `python -m compileall -q app`, las pruebas con base (`RUN_DATABASE_TESTS=1`), y en el frontend `pnpm test`, `pnpm run typecheck` y `pnpm run build` (siempre dentro del contenedor `web`, porque el host no soporta TypeScript). **El extremo a extremo es obligatorio:** el proyecto `operation-flow` de `frontend/e2e/` recorre la apertura y el límite de segmento, el alta de un evento y el **cierre del acta**, así que esta spec exige `pnpm run e2e:test` con veredicto **0**; **1** es un fallo de comportamiento, **2** de infraestructura y **3** una corrida inválida, y ninguno de los tres se declara verde. La corrida se hace en exclusiva (sin servidor de desarrollo ni build concurrentes) y tras limpiar los torneos «Copa E2E» de corridas anteriores. Lo que no se pueda ejecutar se declara **no ejecutado**.
- **RNF-006 (determinismo).** El orden, la matriz y la propuesta no leen el reloj: mismas entradas, misma respuesta. Los mensajes con varios elementos tienen orden estable.
- **RNF-007 (accesibilidad).** La propuesta de segmento se anuncia al cambiar; el formulario de cierre conserva etiqueta, asociación de error y recorrido con teclado.
- **RNF-008 (rendimiento y bloqueo).** El orden de bloqueo de RF-018 se respeta en todas las rutas. La operación sigue siendo una lectura sin bloqueo y la propuesta no añade consultas: se calcula con los segmentos y las interrupciones que la operación ya lee.
- **RNF-009 (documentación).** Se actualizan `AGENTS.md` (orden del cierre, autorización conjunta, matriz de marcadores, doble amarilla, propuesta de segmento, inmutabilidad) y `README.md`; `/docs` refleja `next_segment` y el código nuevo. `docs/contrato-reglas.md` no cambia.
- **RNF-010 (auditoría).** No se añade ninguna acción auditada: el cierre conserva `CLOSE_MATCH_REPORT` y la interrupción `INTERRUPT_MATCH_SEGMENT`.
- **RNF-011 (tiempo real).** No se añaden eventos de outbox; se conservan los tres del cierre.

## Datos personales y privacidad

- **No se introducen datos personales nuevos.** El cierre trata identificadores de jugadores que ya están en el acta.
- **Vías de texto libre que permanecen:** motivo administrativo y notas de interrupción, ambas con tope de 1 000 caracteres, declaradas como riesgo aceptado. El catálogo de eventos y el identificador de cliente se cierran en la 015.
- **Visibilidad:** la operación se ve en el Workspace con el contrato actual; no se añade ninguna proyección pública ni se exponen eventos.
- **Fotos y consentimiento:** no aplica.
- **Auditoría:** guarda identificadores, resolución y motivo; nunca nombres ni documentos.

## Casos límite

1. **Acta con un defecto de dominio y un campo no aplicable:** responde **422** (el estructural prevalece), no el 409 del paso anterior.
2. **Acta con dos defectos de dominio:** informa el del paso anterior del orden.
3. **Segmento con tiempos imposibles al crearlo:** **422**; el mismo defecto persistido, al cerrar: **409**.
4. **Evento en un segmento interrumpido:** **409** al cerrar y bloqueado en el cliente.
5. **Falta de segmento activo:** **409** al cerrar, también con `walkover` (la exención es de la 016).
6. **Jugador de otra organización en el acta:** **409** con su código, nunca 404.
7. **Partido o segmento de otra organización:** **404**.
8. **Roja por doble amarilla sin amarillas previas:** **409** `DOUBLE_YELLOW_INCONSISTENT`.
9. **Roja por doble amarilla con una sola amarilla previa:** **409**.
10. **Roja por doble amarilla con tres amarillas previas:** **409** (no son exactamente dos).
11. **Roja por doble amarilla con dos amarillas en otro partido:** **409**; el conteo es del partido del acta.
12. **Roja directa sin amarillas:** válida.
13. **Segunda amarilla de un jugador:** no crea ninguna roja.
14. **Gol en el minuto 90+3 con reglamentario 90:** cuenta como **reglamentario** (el añadido no cambia la clasificación) y el tope combinado lo permite.
15. **Gol en el minuto 91 con reglamentario 90:** es de prórroga; una resolución `regular` lo rechaza con **409**.
16. **Marcador final informado sin el reglamentario:** **422**.
17. **Marcador final menor que el reglamentario:** **409**.
18. **Empate con `winner_team_id`:** **409** salvo `penalties`, donde el ganador sale de la tanda.
19. **Penales con marcador final distinto del empate:** **409**.
20. **`reason` en una resolución que no lo admite:** **422**.
21. **Reintento idéntico de un evento:** idempotente, sin doble conteo.
22. **Reintento que cambia `metadata` o el asistente:** **409** «inmutable».
23. **Acta confirmada:** solo lectura; un segundo cierre es **409**.
24. **Dos cierres simultáneos:** el segundo espera y responde **409** sin escribir.
25. **Cierre concurrente con una interrupción:** uno de los dos ve el estado del otro; no queda un cierre parcial ni dos segmentos activos.
26. **Propuesta sin segmentos:** `{1, 0, derived: verdadero}`.
27. **Propuesta tras interrumpir en el minuto 37:** `{n+1, 37, derived: verdadero}`.
28. **Propuesta con el último segmento completado que termina en 45:** `{n+1, 45, derived: verdadero}`.
29. **Propuesta con el último segmento activo y sin interrupción:** `{n+1, nulo, derived: falso}`; la indica el operador.
30. **Propuesta con el último segmento completado sin `minute_end` (dato histórico):** `{n+1, nulo, derived: falso}`.
31. **Propuesta en un partido terminado o de versión no publicada:** `null`.
32. **Recarga tras interrumpir:** la propuesta ya refleja el minuto y no se crea nada.
33. **Reanudación antes del minuto de interrupción:** **422**, aunque la propuesta se haya editado a mano.
34. **Miembro con permiso pero sin rol operativo ni asignación:** **403** en segmentos y en el cierre.
35. **Observador asignado como oficial:** **403**.
36. **Miembro sin rol:** **403** de contexto.

## Fuera de alcance

- **Reapertura, corrección y anulación de actas confirmadas.** Exige **enmienda constitucional** (§5.2, cambio propio) y spec propia; el principio 3 es innegociable y hoy lo impone el trigger de la migración 016.
- **API incremental de eventos** y cualquier escritura de eventos fuera del cierre (R11 de la spec 007).
- **`is_voided`** y las columnas de anulación: legado sin vía operativa.
- **Ciclo de vida `live`/`suspended`:** no se añaden transiciones ni un reloj del partido.
- **Automatización por tiempo real**: nada se crea ni se cierra sin acción del operador.
- **El catálogo de eventos y la asistencia:** spec 015.
- **La rama completa del walkover:** la **exención de segmento activo y de plantilla**, el motivo obligatorio de catálogo, el marcador derivado de `walkover_score` y su publicación en `limits`, y el preflight y el formulario del cliente son de la **spec 016**. La 017 **no** los implementa ni los exige, y el comportamiento actual del W.O. —que exige segmento activo y plantilla— queda **sin cambios por esta spec**.
- **Cambios en `points_system`, `ranking_pipeline`, `discipline` o `substitutions`.**
- **Cambios en el contrato interno** (`engine_version` 2026.1, `GF1`/`GF2`, formaciones).
- **Estadísticas por jugador o cualquier superficie pública nueva.**
- **Restringir el motivo administrativo o las notas de interrupción:** se documentan como riesgo aceptado.
- **Rediseño visual completo** de la operación del partido.

## Criterios de finalización

| # | Criterio de finalización | RF |
|---|---|---|
| 1 | Existe un orden único de validación de dominio, documentado, y un fallo en cualquier paso no escribe eventos, contadores, marcador, clasificación, avance, sanciones, auditoría ni outbox. | RF-001, RF-009 |
| 2 | Los 422 estructurales prevalecen sobre el orden de dominio y están declarados como excepción; entre defectos de dominio se informa el del paso anterior. | RF-001 |
| 3 | La autorización es la conjunción real (permiso **y** rol operativo **o** asignación) en cierre y segmentos; el árbitro no asignado y el observador asignado reciben **403**; la administrativa exige además dueño o administrador. | RF-002 |
| 4 | La estructura del acta se valida con su intervalo, su máximo efectivo y su `client_event_id`; el mismo defecto de tiempos da **422 al crear** y **409 al cerrar**, y la diferencia está documentada. | RF-003 |
| 5 | Participantes y plantilla se validan; un jugador de otra organización responde **409** y un partido o segmento de otra organización **404**. | RF-004, RF-020 |
| 6 | El estado en campo y las sustituciones se validan con el motor puro antes de escribir y la proyección se recalcula por `segment_number`. | RF-005 |
| 7 | Una roja por doble amarilla exige **exactamente dos** amarillas previas del mismo jugador en el mismo partido; cualquier otro caso es **409** `DOUBLE_YELLOW_INCONSISTENT`. | RF-006 |
| 8 | El gol reglamentario se decide por `minute ≤ regular_time_minutes` sin mirar el añadido; la matriz de marcadores por resolución se aplica con sus combinaciones obligatorias, opcionales y prohibidas; el campo se llama `reason` y la columna `resolution_reason`. | RF-007 |
| 9 | La idempotencia incluye `metadata` y el asistente; un evento idéntico se reutiliza y uno distinto responde **409**; un acta confirmada no se re-cierra. | RF-008 |
| 10 | Los **409** de dominio llevan `detail` cadena y los **422** una lista saneada sin `code`; los códigos nuevos son aditivos. | RF-010 |
| 11 | Un acta confirmada es inmutable, no hay ruta de corrección y la interfaz dice «acta cerrada, no editable» sin lenguaje constitucional. | RF-011 |
| 12 | El segmento se define como ventana de tiempo, sin mitades ni periodos, y crear uno con otro activo cierra el anterior en su minuto. | RF-012, RF-013 |
| 13 | La interrupción cierra el segmento en su minuto, conserva su auditoría y bloquea sus eventos. | RF-014 |
| 14 | La operación devuelve `next_segment` con número, minuto y `derived` en los cinco casos declarados, lo omite (`null`) en partido terminal o versión no publicada, y no escribe nada. | RF-015 |
| 15 | Ninguna regla deportiva nueva se deriva de los segmentos y el estado del partido no cambia al abrirlos, cerrarlos o interrumpirlos. | RF-016 |
| 16 | **No aplicable hasta la 016.** El criterio agrupaba dos cosas: (a) sin segmento activo el cierre es **409** y la interfaz ofrece la propuesta — cubierto por RF-017 y RF-015 y verificado en esta spec; y (b) la exención del `walkover`, que **pertenece íntegramente a la 016** y esta spec no implementa ni exige. Queda por tanto **cumplido en su parte (a)** y **pendiente de la 016 en su parte (b)**, que no se puede declarar aquí. | RF-017, RF-015 (016 para la exención) |
| 17 | El orden de bloqueo es el declarado y las cuatro situaciones concurrentes terminan sin cierre parcial ni dos segmentos activos. | RF-018 |
| 18 | `engine_version` sigue en **2026.1**, `docs/contrato-reglas.md` no cambia y no se añade ni retira ninguna clave. | RF-019 |
| 19 | No hay migración, ni acción auditada nueva, ni evento de outbox nuevo; la inmutabilidad se apoya en los triggers existentes. | RNF-004, RNF-010, RNF-011 |
| 20 | Las dos vías de texto libre que permanecen están declaradas con su tope y su riesgo, y ningún mensaje nuevo expone datos personales. | RNF-002 |
| 21 | Pasan `cd backend && pytest -q`, `python -m compileall -q app`, las pruebas con base, `pnpm test`, `pnpm run typecheck` y `pnpm run build` dentro del contenedor `web`; el escenario `operation-flow` de `pnpm run e2e:test` termina en **0** (un **1**, **2** o **3** no es verde); lo no ejecutado se declara **no ejecutado**. | RNF-005 |
| 22 | La validación y la propuesta son deterministas, sin reloj, con orden estable en los mensajes. | RNF-006 |
| 23 | La propuesta y los mensajes del cierre se anuncian y se recorren con teclado. | RNF-007 |
| 24 | `AGENTS.md` y `README.md` describen el orden, la autorización conjunta, la matriz, la doble amarilla, la propuesta de segmento y la inmutabilidad. | RNF-009 |

## Dudas abiertas

**Sin dudas abiertas.** D-1, D-2, D-4, DU-8, DU-9 y DU-10 están cerradas en «Decisiones cerradas» y aplicadas. La spec está **aprobada** desde el 2026-10-25.

## Apéndice A — Inventario de validaciones del cierre

Descriptivo; es el orden que RF-001 fija y que las pruebas deben cubrir una por una.

| Paso | Validación | Hoy | Esta spec |
|---|---|---|---|
| — | Estructura del esquema (campos, claves, rangos, duplicados, 500 eventos) | 422 antes del handler | Prevalece sobre el orden; declarado |
| 1 | Sesión, organización y aislamiento | Sí | Sin cambios |
| 2 | Permiso y asignación como oficial (conjunción) | Sí | Explícito como conjunción |
| 3 | Estado del partido y versión publicada | Sí | Sin cambios |
| 4 | Dos equipos participantes | Sí | Sin cambios |
| 5 | Resolución habilitada por la configuración efectiva | Sí | Sin cambios |
| 6 | Estructura del acta: segmentos, tiempos, intervalo, máximo efectivo, `client_event_id` | Sí, disperso | Ordenado y explícito |
| 7 | Plantilla, participantes y elegibilidad | Sí | Sin cambios |
| 8 | Estado en campo y sustituciones | Sí | Sin cambios |
| 9 | Asistente del gol | No existía | **Nuevo** (015) |
| 10 | Coherencia de la doble amarilla | No existía | **Nuevo** |
| 11 | Marcador frente a eventos y matriz por resolución | Sí, parcial | Matriz completa y regla exacta del minuto |
| 12 | Sanciones vigentes de la plantilla | Sí | Sin cambios; la exención en `walkover` es de la 016 |
| 13 | Coherencia de la resolución y del ganador, `GF1`/`GF2` | Sí | Sin cambios |
| 14 | Escritura atómica, clasificación, avance, auditoría y outbox | Sí | Sin cambios |

## Apéndice B — Referencias de inspección

- Cierre: `backend/app/modules/matches/service.py:304-518`; `:323-338` (permisos); `:347-367` (estado, versión, equipos, segmento, plantilla); `:613-653` (segmentos y eventos); `:655-679` (sustituciones); `:750-789` (marcador y minuto reglamentario); `:822-920` (persistencia e idempotencia); `:949-997` (sanciones); `:1024-1032` (clasificación y avance).
- Esquema del acta: `backend/app/modules/matches/schemas.py:55-144` (contrato y resoluciones), `:155-168` (segmentos).
- Errores: `backend/app/main.py:594-615` (422 saneado), `:690-701` (409 con `code`).
- Autorización: `backend/app/core/permissions.py:22-75`.
- Rutas: `backend/app/modules/matches/router.py:447-472` (cierre), `:474-626` (operación), `:629-756` (crear segmento), `:759-868` (interrumpir).
- Segmentos: `infra/postgres/init/01_schema.sql:494-510`, `:549-562`.
- Reglas: `backend/app/modules/rules_engine/engine.py:332-435`, `:424-465`.
- Inmutabilidad: `infra/postgres/migrations/016_confirmed_match_result_immutability.sql`; `009_photo_resolution_and_outbox_hardening.sql:162-231`.
- Frontend: `frontend/app/pages/workspace/matches/[id].vue:356-359` (segmento seleccionado y activo), `:641-683` (validación previa), `:702-719` (próximo número), `:871-914` (crear e interrumpir), `:1518-1531` (formulario de cierre).
