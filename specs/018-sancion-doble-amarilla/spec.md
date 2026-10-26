# Spec 018 — Sanción única por doble amarilla

Estado: implementada (2026-10-25)

## Contexto y objetivo

Cuando un jugador es expulsado por doble amarilla, el sistema le impone hoy **dos sanciones que se suman**: una por la roja y otra por la acumulación de amarillas, si una de las amarillas que componen la expulsión es además la que alcanza el umbral configurado. El jugador cumple dos partidos de suspensión por una sola jugada: una por la expulsión y otra por haber llegado al umbral con una tarjeta que ya estaba siendo sancionada.

La disciplina es **configuración de la versión del torneo**, no contrato cerrado: el contrato interno del motor (`engine_version` `2026.1`) cubre únicamente los códigos de llave y el catálogo de formaciones, y no incluye las claves de disciplina, que son aditivas y viven fuera de él. **La corrección se aplica de forma fija en el motor y no añade ninguna clave de configuración**, porque es una corrección de coherencia —una jugada, una sanción— y no una regla deportiva nueva: tiene el mismo carácter que la regla de «exactamente dos amarillas previas» que ya vive en el motor desde el cierre de actas. Como la disciplina es configuración, esta decisión **se ampara en la excepción acotada de §5.1**, declarada en la subsección siguiente.

Hoy la disciplina se compone de cinco claves —límite de amarillas para la acumulación, partidos que dura la sanción por acumulación, partidos que dura la sanción por expulsión, reinicio de amarillas al cambiar de fase y puntos de *fair play* para la clasificación—. **Ninguna** gobierna la relación entre la acumulación y la expulsión por doble amarilla: esa relación es precisamente lo que esta spec fija. Los puntos de *fair play* son una magnitud del desempate y **no** una duración de suspensión; no se confunden con ella.

Además del doble castigo, esta spec absorbe el **segundo defecto registrado** del proyecto: la roja que se registra en el mismo cierre se evalúa sin su clasificación (doble amarilla o directa) y se sanciona como directa, de modo que la regla de esta spec no se aplicaría hasta un cierre posterior. Aquí se corrige: la sanción se deriva del tipo de roja tal como queda registrado en el acta, también en el cierre que la registra.

**Objetivo:** que, **desde esta corrección**, una misma jugada produzca **exactamente una** sanción, que su duración sea predecible y verificable, y que la corrección no altere actas cerradas, el orden de cierre vigente ni el resto de las reglas disciplinarias.

### Comportamiento actual verificado

| # | Hecho verificado |
|---|---|
| 1 | Las sanciones se derivan **al cerrar el acta**, de los eventos del acta más el historial disciplinario del jugador en el mismo torneo; con el reinicio por cambio de fase activo, el historial se limita a la misma fase y versión. |
| 2 | Cada amarilla incrementa un contador por jugador y **cada múltiplo** del límite configurado emite una sanción por acumulación, referida al evento de amarilla que alcanzó el múltiplo. |
| 3 | **Toda** roja emite otra sanción independiente, referida al evento de la roja, con motivo de doble amarilla o de roja directa. |
| 4 | Las dos reglas no se excluyen: en la misma acta conviven, y sus partidos de suspensión **se suman**. Con límite 3, una amarilla histórica y dos amarillas más una roja por doble amarilla en el acta, el jugador cumple **2 partidos**. |
| 5 | La deduplicación es por torneo, jugador, evento y motivo: dos motivos distintos sobre la **misma** jugada son dos filas distintas y no se descartan entre sí. |
| 6 | El contador de amarillas **no se reinicia** con la roja, así que la amarilla que precede a la expulsión sigue contando para umbrales posteriores. |
| 7 | Una sanción se considera cumplida por un partido en el que el equipo del jugador juega y el jugador **no** figura en la convocatoria válida; cada sanción se cumple por separado y bloquea la planilla mientras esté vigente. |
| 8 | Cerrar un acta **vuelve a evaluar el historial completo**; la clave de deduplicación evita que la re-evaluación multiplique sanciones ya creadas. |
| 9 | Las actas cerradas son inmutables y **no se revalidan**; el walkover **no genera ni sirve sanciones**. |
| 10 | La roja registrada en el mismo cierre se evalúa **sin su clasificación** (doble amarilla o directa) porque ese dato no vuelve en la inserción, y se etiqueta como roja directa; al releerla de la base se etiqueta bien. |

La fila 4 es el defecto que motiva esta spec y se corrige con RF-001 y RF-002. La fila 10 es el segundo defecto registrado del proyecto y esta spec **también lo corrige** (RF-010): no queda como riesgo aceptado. La fila 8 describe el origen actual de las sanciones —cerrar un acta vuelve a derivar el historial y puede insertar por él—; **desde esta corrección solo los eventos del acta que se cierra originan sanciones** (RF-005, RNF-004).

### Dependencias con otras specs

- **015 (catálogo de eventos):** los tipos de evento, sus campos y la clasificación de la roja (`direct_red`/`double_yellow_red`) son suyos y no se tocan.
- **017 (cierre de actas):** el orden único de 14 pasos, el paso 10 (coherencia de la doble amarilla) y el paso 12 (sanciones vigentes) se conservan tal cual. Esta spec **no añade un paso de validación**: la sanción no es una comprobación del cierre, sino una consecuencia de la escritura.
- **016 (walkover):** su rama no genera ni sirve sanciones; esta spec no la altera.
- **Contrato que esta spec ofrece:** la regla de sanción única por jugada, su duración, su efecto en la elegibilidad y su estabilidad cuando el acta pasa a ser historial.

### Excepción declarada a §3.2

La disciplina es una regla deportiva configurable y §3.2 exige que viva en la configuración de la versión, no como constante. Esta spec mantiene la regla **fija en el motor** y declara la excepción con los cuatro elementos que exige §5.1:

- **Justificación escrita.** Es una corrección de coherencia —una jugada, una sanción—, no una regla deportiva nueva: no añade una decisión que una organización pueda querer distinta, sino que impide sancionar dos veces el mismo hecho. Tiene el precedente de la regla de «exactamente dos amarillas previas» del cierre de actas, ya fija en el motor y aceptada en la spec 017.
- **Alcance acotado.** La absorción de la sanción por acumulación de la misma jugada de doble amarilla **y** la unicidad de sanción por evento de roja (RF-005), que también queda fija en el motor y forma parte de la misma corrección de coherencia. **No** alcanza a la roja directa, ni a las duraciones, ni a los umbrales, ni a ninguna otra regla disciplinaria, ni a ninguna otra configuración del torneo.
- **Responsable.** El propietario del producto, que aprueba esta spec y responde de la excepción.
- **Aprobación de un revisor distinto del autor.** @reviewer **aprueba esta excepción** en el veredicto favorable de la fase 2 (2026-10-25), y no es su autor.

**No hay enmienda de la constitución.** Si el alcance creciera —por ejemplo, hacia la roja directa o hacia una clave nueva de configuración—, habría que volver a pasar por §5.1 con una justificación, un alcance y una aprobación nuevas.

## Usuarios

- **Administrador o dueño de la organización:** configura la disciplina y espera que las sanciones sean coherentes con lo que se ve en el campo.
- **Operador de partido o árbitro:** registra el acta; no decide sanciones, pero su trabajo se bloquea si la sanción derivada es incorrecta.
- **Jugador y equipo (a través del administrador):** cumplen la sanción y vuelven a ser elegibles cuando corresponde.
- **Responsable de integridad:** espera que ninguna acta cerrada ni sanción ya emitida se reescriba.
- **Mantenedor:** necesita la regla escrita y verificable para no reintroducir la doble sanción.

## Roles y visibilidad

- **No cambia ningún rol, permiso ni ámbito.** No se añade permiso, rol por torneo ni delegación; la disciplina se sigue leyendo de la configuración efectiva de la versión publicada.
- **Observador (`viewer`):** sin cambios; no gana ninguna acción ni ninguna pantalla.
- **Miembro sin rol:** conserva su **403** de contexto en toda ruta protegida.
- **Administrador de plataforma:** no aplica; no edita resultados ni configuración de organizaciones.
- **Público:** no aplica; las sanciones no se publican y ninguna proyección pública cambia.
- **Aislamiento:** toda derivación se limita a la organización del torneo; ninguna organización ve ni modifica las sanciones de otra.

## Historias de usuario

- **HU-1.** Como administrador, quiero que una expulsión por doble amarilla cueste **una** sanción y no dos, para que el jugador no pierda partidos de más.
- **HU-2.** Como administrador, quiero entender en cuántos partidos se traduce una jugada, para poder explicarlo al equipo.
- **HU-3.** Como operador, quiero que la corrección no cambie lo que ya sé del cierre: mismas validaciones, mismos errores, mismo orden.
- **HU-4.** Como mantenedor, quiero una regla única y determinista que no dependa del orden en que lleguen los eventos ni de cuándo se cierre otra acta.
- **HU-5.** Como responsable de integridad, quiero que ninguna acta cerrada ni sanción ya emitida se reescriba por esta corrección.

## Definiciones

- **Jugada.** La unidad disciplinaria mínima que se sanciona: en esta spec, la **expulsión por doble amarilla** de un jugador en un partido, junto con las amarillas que la componen. El acta no declara jugadas: se identifica por el **evento de roja** marcado como doble amarilla y las dos amarillas previas del mismo jugador en el mismo partido. Una jugada nunca abarca dos actas.
- **Sanción.** Registro de suspensión derivado de una jugada, con un motivo, una duración en partidos y una referencia al partido y al evento que la originan. Una sanción está **vigente** hasta que se cumplen sus partidos.
- **Sanción por acumulación.** La que se emite al alcanzar un múltiplo del límite de amarillas configurado.
- **Sanción por roja.** La que se emite por una expulsión: por doble amarilla o directa.
- **Absorción.** Efecto por el cual, cuando una sanción por acumulación recae sobre la **misma jugada** que una expulsión por doble amarilla, la de acumulación no se emite y solo queda la de la expulsión.
- **Partido de suspensión.** Partido del torneo en el que el equipo del jugador compite y el jugador **no** está en la convocatoria válida. Es la unidad en que se mide y se cumple una sanción; no es un partido cualquiera del calendario ni un periodo de tiempo.
- **Historial disciplinario.** Amarillas y rojas del jugador en el mismo torneo, y en la misma fase y versión cuando el reinicio por cambio de fase está activo, **excluido** el partido que se está cerrando. Cada tarjeta del historial **identifica el partido** al que pertenece y el historial se ordena con un **orden total y estable** construido solo con datos persistidos: primero el partido —por su fecha de juego y, en empate de fecha, por su identificador; un partido sin fecha se ordena por su identificador y antes que cualquiera con fecha— y después, dentro del partido, minuto, minuto añadido e identificador del evento. El **índice del acta** solo existe en el acta que se está cerrando y **no** forma parte del historial. El historial **solo cuenta y empareja: nunca origina sanciones nuevas**.
- **Ámbito disciplinario.** Conjunto de actas cuyas tarjetas se cuentan juntas para decidir si se cruza un umbral: el torneo completo, o la fase y versión cuando el reinicio por cambio de fase está activo. **No** amplía ni reduce el emparejamiento entre una acumulación y su expulsión, que ocurre siempre dentro del acta que se cierra.

## Requisitos funcionales

- **RF-001.** CUANDO se cierre un acta en la que un jugador ha sido expulsado por doble amarilla, EL SISTEMA emitirá **exactamente una** sanción atribuible a esa jugada.
  *Criterios de aceptación:*
  - La jugada produce exactamente **una** sanción vigente, nunca dos, aunque sus amarillas alcancen un umbral de acumulación.
  - El acta cierra con normalidad: esta regla no introduce ningún error nuevo ni cambia el resultado del cierre.
  - El resto de sanciones del acta (otros jugadores u otras jugadas) no se ve afectado.
  - La garantía rige para las actas que se cierren desde esta corrección; una jugada de un acta ya cerrada conserva sus sanciones y no se recalcula (RF-006).

- **RF-002.** SI una de las amarillas que componen una expulsión por doble amarilla alcanza un múltiplo del límite de acumulación, ENTONCES EL SISTEMA **no** emitirá la sanción por acumulación y conservará únicamente la sanción por la expulsión.
  *Criterios de aceptación:*
  - La absorción alcanza a **cualquier** amarilla del acta que componga la expulsión —la primera o la última— y a **todos** los umbrales que cruce, incluido el caso de dos umbrales en la misma acta.
  - El emparejamiento entre la acumulación y la expulsión se decide **solo dentro del acta** que se cierra: una roja **no** absorbe un umbral cruzado y ya sancionado en un acta anterior.
  - No se absorbe ninguna otra sanción: ni la acumulación de otro jugador, ni la de una jugada anterior.
  - El motivo de la sanción conservada es el de la expulsión por doble amarilla y queda trazable al evento de la roja.

- **RF-003.** EL SISTEMA fijará la duración de la sanción única de una expulsión por doble amarilla en **la duración configurada para la sanción por expulsión**, aplicada **una sola vez**.
  *Criterios de aceptación:*
  - La duración se toma de la configuración efectiva de la versión publicada; es la misma que se aplica a cualquier otra expulsión y nunca un valor incrustado.
  - La acumulación **no** alarga la sanción y la duración no depende de cuántas amarillas ni de cuántos umbrales cruzó la jugada.
  - Las duraciones de sanción configuradas no admiten 0 partidos, así que la sanción derivada de esta regla siempre tiene al menos un partido.
  - Los **partidos de suspensión cumplidos** coinciden exactamente con la duración configurada, según la definición vigente de partido de suspensión.

- **RF-004.** EL SISTEMA contará **todas** las amarillas que componen la expulsión por doble amarilla —incluida la que la provoca— para las acumulaciones posteriores y derivará el conteo del historial de forma determinista.
  *Criterios de aceptación:*
  - **No se descuenta ninguna** de las dos amarillas que componen la expulsión.
  - El conteo se deriva del historial y del acta, no de un saldo acumulado que haya que mantener.
  - El historial **identifica el partido** de cada tarjeta y la derivación usa esa pertenencia para no cruzar tarjetas de actas distintas.
  - El historial se ordena con un **orden total y estable** y solo con datos persistidos: primero el partido —por su fecha de juego y, en empate o sin fecha, por su identificador— y después, dentro del partido, minuto, minuto añadido e identificador del evento. El **índice del acta** solo existe para el acta que se está cerrando y no se usa para ordenar el historial.
  - El orden de conteo es siempre el mismo: **primero el historial** en ese orden, **después el acta en cierre** en su orden canónico, que incluye el índice del payload. El orden del historial es estable y el conteo es conmutativo; el acta en cierre fija su umbral con su orden canónico y una acumulación histórica no se vuelve a originar.
  - El requisito es **determinismo**: las mismas entradas dan el mismo resultado y la derivación no depende del orden de llegada ni del orden de lectura. Contar amarillas es conmutativo; lo que debe ser reproducible es **qué evento cruza cada umbral**.
  - Una amarilla **descartada** por el reinicio de fase no cuenta (RF-008).

- **RF-005.** EL SISTEMA solo creará sanciones a partir de los **eventos del acta que se está cerrando**; el historial disciplinario solo cuenta y empareja y **nunca origina sanciones nuevas**.
  *Criterios de aceptación:*
  - Cerrar un acta no crea ninguna sanción por un evento del historial: ni la acumulación absorbida, ni una sanción nueva por una roja histórica, ni la corrección de una sanción ya registrada.
  - **Un evento de roja tiene como máximo una sanción, con cualquier motivo.** La comprobación se hace **sobre los eventos de roja del acta que se cierra**, con una **lectura acotada a ese conjunto**, y **aparte** de la identidad por jugador, evento y motivo: si alguno de esos eventos ya tiene una sanción —por ejemplo, porque el evento se reutilizó de forma idempotente o porque un cierre anterior dejó la fila—, no se crea otra con el motivo corregido y la existente no se reescribe.
  - La identidad de una sanción —**torneo**, jugador, evento de origen y motivo— no cambia; no se relaja ni se comparte entre motivos distintos. **Esa identidad, por sí sola, no basta** para la unicidad por evento de roja: como incluye el motivo, dos sanciones con motivos distintos sobre el mismo evento no colisionan entre sí, y ese es exactamente el defecto que esta spec corrige.
  - La regla se aplica igual la primera vez (cuando la jugada se registra) y las siguientes: el resultado no depende del momento del cierre.
  - Un cierre rechazado no deja ninguna sanción intermedia.

- **RF-006.** EL SISTEMA no modificará, revocará ni reescribirá las sanciones ya **registradas**: la corrección es **solo hacia delante** y la re-evaluación del historial no las altera **ni las origina**.
  *Criterios de aceptación:*
  - Ninguna sanción registrada cambia de motivo, duración o estado por esta corrección.
  - Una sanción histórica de una roja que quedó con el motivo de roja directa **no** se reescribe ni se duplica con el motivo corregido (RF-005).
  - Ninguna acta confirmada se revalida ni se vuelve a cerrar.
  - Una acta **abierta** en el momento del cambio aplica la regla nueva cuando se cierre.
  - Los partidos de suspensión ya cumplidos se conservan como cumplidos.

- **RF-007.** EL SISTEMA aplicará la regla de forma **fija en el motor, sin clave nueva de configuración**.
  *Criterios de aceptación:*
  - No se añade ni se retira ninguna clave de la configuración de disciplina y `schema_version` no cambia.
  - `engine_version` sigue en **`2026.1`** y el contrato cerrado no cambia.
  - Una versión ya publicada conserva exactamente su configuración; guardar o publicar reglas no introduce ni altera esta regla.
  - La regla se aplica igual en todas las organizaciones, sin valores por torneo ni por versión.

- **RF-008.** CUANDO el reinicio de amarillas por cambio de fase esté activo, EL SISTEMA aplicará **primero** el reinicio y contará solo las amarillas de la fase y versión actuales para decidir si una jugada cruza un umbral; sin el reinicio, contará todas las del torneo.
  *Criterios de aceptación:*
  - El ámbito afecta al **conteo del umbral**, no al emparejamiento: la acumulación se empareja con la expulsión **siempre dentro del acta** que se cierra, y el ámbito no lo amplía ni lo reduce.
  - Con el reinicio activo, las amarillas de otra fase o versión no cuentan para el umbral.
  - Sin el reinicio, cuentan todas las amarillas del torneo, también las de fases anteriores.
  - La absorción no altera el reinicio: no se «arrastran» amarillas de una fase a otra para justificar una sanción.

- **RF-009.** SI un jugador recibe una **roja directa** en un acta en la que además alcanza un umbral de acumulación, ENTONCES EL SISTEMA **mantendrá las dos sanciones**.
  *Criterios de aceptación:*
  - Son dos hechos distintos: el umbral se cruza con una amarilla y la expulsión es otra tarjeta.
  - La absorción de esta spec se limita a la jugada de doble amarilla y **no** se aplica a la roja directa.
  - Una roja directa sigue sin exigir amarillas previas (017 intacta).
  - La duración de cada una de las dos sanciones es la que corresponde a su motivo: la acumulación con la duración configurada para la acumulación y la expulsión con la duración configurada para la sanción por expulsión.

- **RF-010.** EL SISTEMA derivará la sanción del **tipo de roja tal como queda registrada en el acta**, también en el mismo cierre que la registra.
  *Criterios de aceptación:*
  - Una roja marcada como doble amarilla produce el motivo de doble amarilla en ese mismo cierre; una roja directa produce el suyo.
  - El tipo nunca se infiere del número de amarillas del acta.
  - El tipo registrado y el usado para sancionar coinciden siempre, en el cierre que la registra y en cualquier cierre posterior.
  - La absorción de RF-002 se aplica ya en ese primer cierre.

- **RF-011.** CUANDO se emita la sanción única de una jugada, EL SISTEMA la tratará como **una sola** sanción a efectos de elegibilidad y de partidos cumplidos.
  *Criterios de aceptación:*
  - No queda ninguna sanción vigente residual de la misma jugada.
  - El jugador vuelve a ser elegible cuando cumple los **partidos de suspensión** de la duración configurada, según la definición vigente de partido de suspensión.
  - El bloqueo de planilla por sanción vigente sigue funcionando igual para el resto de sanciones.
  - Cumplir la sanción no se ve afectado por el hecho de que la jugada cruzara un umbral.

- **RF-012.** EL SISTEMA registrará la sanción resultante de forma trazable y sin datos personales.
  *Criterios de aceptación:*
  - La sanción conserva la referencia al partido y al evento que la originan.
  - El motivo distingue la regla aplicada y, **desde esta corrección**, no hay dos motivos para una misma jugada; una jugada de un acta cerrada antes conserva sus dos filas (RF-006).
  - **Una roja no tiene dos sanciones con motivos distintos**, ni siquiera cuando la primera quedó con un motivo heredado de una versión anterior de la regla (RF-005).
  - El recuento que la auditoría del cierre registra es el de las **sanciones realmente creadas**, no el tamaño de la lista derivada antes de descartar absorciones ni sanciones ya existentes.
  - Ni el motivo ni ningún mensaje contienen nombres, documentos ni fechas de nacimiento.

- **RF-013.** EL SISTEMA conservará sin cambios el cierre del acta y sus reglas vecinas.
  *Criterios de aceptación:*
  - El orden único de 14 pasos no cambia y **no** se añade un paso de validación por esta regla.
  - La coherencia de la doble amarilla (exactamente dos amarillas previas del mismo jugador en el mismo partido, con su **409** y su código) se mantiene tal cual.
  - El catálogo cerrado de eventos, sus campos y sus restricciones no cambian.
  - El walkover sigue **sin generar ni servir** sanciones.
  - Un acta confirmada sigue siendo inmutable y sin vía de corrección.

- **RF-014.** EL SISTEMA derivará las sanciones **solo** con datos de la organización del torneo.
  *Criterios de aceptación:*
  - Eventos, historial y sanciones de otra organización no influyen en el resultado, ni siquiera si coinciden jugador o identificadores.
  - Toda lectura y escritura se ejecuta con el contexto de aislamiento fijado en la transacción.
  - Ninguna organización puede ver ni modificar las sanciones de otra.

- **RF-015.** EL SISTEMA no añadirá ninguna superficie nueva para consultar sanciones; el efecto visible para el operador sigue siendo el bloqueo de la planilla y el recuento del cierre.
  *Criterios de aceptación:*
  - No se añade endpoint, pantalla ni campo público.
  - Lo que el operador ya ve tras cerrar (bloqueo de planilla por sanción vigente) sigue siendo correcto y coherente con la sanción única.

## Requisitos no funcionales

- **RNF-001 (aislamiento).** Ninguna consulta nueva cruza organizaciones; el contexto se fija dentro de la transacción antes de cualquier lectura del tenant. La regla se verifica también con un acta de otra organización que **no** altera el resultado.
- **RNF-002 (privacidad).** No se introduce ningún dato personal nuevo: la regla trabaja con identificadores de jugador que ya están en el acta. Ningún mensaje, motivo o recuento incluye nombres, documentos ni fechas de nacimiento. Nada se publica.
- **RNF-003 (determinismo).** La regla no lee el reloj ni depende del orden de llegada de los eventos: mismas entradas, mismo resultado. El historial se ordena con un **orden total y estable** y solo con datos persistidos —primero el partido por su fecha de juego y, en empate o sin fecha, por su identificador; después minuto, minuto añadido e identificador del evento—; el acta en cierre se ordena con su orden canónico, que incluye el índice del payload. Los mensajes tienen orden estable.
- **RNF-004 (contratos que cambian).** Se declaran: (a) el número de partidos que cumple un jugador expulsado por doble amarilla en el caso de coincidencia, que baja; (b) la etiqueta del motivo de una roja recién registrada, que pasa a ser la correcta en el mismo cierre; (c) **el origen de las sanciones**: hoy cerrar un acta vuelve a derivar el historial y puede insertar sanciones por él, y desde esta corrección **solo los eventos del acta que se cierra las originan**; (d) el recuento de sanciones de la auditoría del cierre, que pasa a ser el número de **sanciones realmente creadas** —no el tamaño de la lista derivada— y por tanto puede bajar; (e) **no** cambia ningún código de respuesta, ni la configuración, ni `schema_version`, ni `engine_version`, ni el catálogo de eventos, ni el contrato cerrado. Un cliente que ignore todo esto conserva su comportamiento.
- **RNF-005 (base de datos).** **Sin migración.** La regla se resuelve en la derivación de sanciones: no se añade columna, restricción ni índice, y no se reescribe ninguna fila existente.
- **RNF-006 (verificación).** Pasan las pruebas del backend sin base y con base (`RUN_DATABASE_TESTS=1`), la compilación del backend, y en el frontend las pruebas, el chequeo de tipos y la construcción. **El job de extremo a extremo es obligatorio** porque esta corrección toca la ruta de cierre que ese escenario recorre: `pnpm run e2e:test` debe terminar con veredicto **0**; **1** es un fallo de comportamiento, **2** de infraestructura y **3** una corrida inválida, y ninguno de los tres se declara verde. Se declara **no ejecutado** lo que no se pueda correr.
- **RNF-007 (documentación).** Se actualizan las guías del proyecto que describen la disciplina y las sanciones; el contrato interno de reglas **no** cambia y `engine_version` sigue en `2026.1`.
- **RNF-008 (auditoría).** No se añade ninguna acción auditada nueva; se conserva la del cierre y su recuento pasa a ser el de **sanciones realmente creadas** (RF-012).
- **RNF-009 (tiempo real).** No se añaden eventos de outbox; se conservan los del cierre.
- **RNF-010 (rendimiento).** La derivación sigue siendo una sola pasada sobre el historial y el acta, con un **número fijo de consultas** —sin consultas por jugador ni por evento—; la lectura de sanciones existentes queda **acotada a los eventos de roja del acta en cierre** (RF-005), así que el número de consultas no crece con el historial ni depende de cuántos eventos tenga el torneo.

## Datos personales y privacidad

- **No aplica como cambio de privacidad.** No se introducen datos personales nuevos: solo se usan identificadores de jugador ya presentes en el acta y en el historial.
- **Visibilidad:** las sanciones no se publican en ninguna proyección ni respuesta pública, y esta spec no añade ninguna.
- **Fotos y consentimiento:** no aplica.
- **Auditoría:** conserva identificadores, nunca nombres ni documentos; el motivo de la sanción es un código, no texto libre.

## Casos límite

1. **Umbral cruzado por la segunda amarilla del acta, que es la que provoca la expulsión:** una sola sanción (RF-001, RF-002).
2. **Umbral cruzado por la primera amarilla del acta y roja por doble amarilla después:** misma regla; no queda sanción por acumulación (RF-002).
3. **Dos umbrales cruzados en el mismo acta con expulsión por doble amarilla:** una sola sanción por la jugada (RF-002).
4. **Umbral cruzado y sancionado en un acta anterior, con roja por doble amarilla en esta:** no hay coincidencia; la sanción de la acumulación anterior no se absorbe y sigue su curso.
5. **Límite de amarillas igual a 1:** toda amarilla cruza el umbral; toda expulsión por doble amarilla coincidiría y produce una sola sanción.
6. **Jugador con tres amarillas previas y una roja marcada como doble amarilla:** el cierre se rechaza antes de sancionar (regla de la 017); no se deriva nada.
7. **Dos rojas por doble amarilla del mismo jugador en un acta:** defecto del acta (estado en campo), rechazado antes de sancionar.
8. **Reinicio por cambio de fase activo:** el umbral se cuenta solo con las amarillas de la fase y versión actuales; el emparejamiento con la expulsión sigue siendo dentro del acta.
9. **Reinicio desactivado:** cuentan todas las amarillas del torneo, también las de fases anteriores; la absorción se sigue decidiendo solo con las amarillas del acta que se cierra.
10. **Cierre de un partido posterior con el mismo jugador:** el historial no origina sanciones, así que no reaparece la absorbida ni se duplica la conservada (RF-005).
11. **Reintento del mismo cierre:** el acta ya está cerrada y no se admite un segundo cierre; no hay doble sanción por reintento.
12. **Roja directa con umbral cruzado en la misma acta:** se mantienen las dos sanciones; la absorción no se aplica (RF-009).
13. **Roja marcada como doble amarilla sin dos amarillas previas:** **409** de la 017, sin escritura ni sanciones.
14. **Roja recién registrada en el mismo cierre:** la sanción se deriva de su tipo registrado, es la de doble amarilla cuando corresponde y la absorción se aplica ya en ese cierre (RF-010).
15. **Roja histórica guardada con el motivo de roja directa por el defecto de etiqueta, al cerrar un partido posterior:** el historial no origina sanciones, así que no se crea ninguna fila nueva ni se reescribe la existente (RF-005, RF-006).
16. **Dos cierres seguidos del mismo jugador, el segundo con otra expulsión:** el segundo evento de roja tiene su propia sanción, la primera no se toca y la acumulación absorbida de la primera jugada no se reemite.
17. **Historial sin partido identificable:** no puede darse; toda tarjeta nace ligada a un partido y esa pertenencia forma parte del contrato del historial (RF-004).
18. **Dos amarillas del historial con el mismo minuto y el mismo minuto añadido en un partido:** el desempate por identificador del evento da un orden estable, así que el evento que cruza el umbral es siempre el mismo y no depende del orden de lectura (RF-004).
19. **Duración configurada en el mínimo (1 partido):** la sanción única sigue siendo un solo partido, aunque la jugada cruzara un umbral.
20. **Walkover:** no genera ni sirve sanciones; la regla no interviene.
21. **Acta de otra organización en el historial:** no cuenta y no altera el resultado.
22. **Acta con resolución administrativa:** no tiene eventos, así que no deriva sanciones.
23. **Jugador sancionado que no vuelve a ser convocado:** la sanción no se cumple por partidos en los que su equipo no juega; esta spec no cambia ese criterio.
24. **Otra sanción vigente del mismo jugador por una jugada anterior:** se cumple con normalidad y no se absorbe ni se altera.
25. **Otra acumulación del mismo jugador en la misma acta por una jugada distinta:** no existe, porque la jugada de doble amarilla agota las dos amarillas previas del acta; si el jugador tuviera más amarillas, el cierre se rechaza antes de sancionar (caso 6).

## Fuera de alcance

- **Retroactividad:** la corrección es solo hacia delante; ninguna acta cerrada se revalida y ninguna sanción existente cambia de motivo, duración o estado (RF-006).
- **Absorción de la roja directa junto a un umbral de acumulación:** se mantienen las dos sanciones (RF-009).
- **Una clave de configuración de la absorción:** la regla es fija en el motor (RF-007).
- **Reapertura, corrección o anulación de actas confirmadas** (exige enmienda constitucional y spec propia).
- **Apelaciones, recursos, indultos y anulación de sanciones** (`appealed`/`cancelled` siguen sin vía operativa).
- **Sanciones administrativas, multas, sanciones a equipos o a cuerpos técnicos.**
- **Duración de las sanciones por acumulación o por expulsión:** se conservan como están configuradas.
- **Puntos de *fair play* de la clasificación:** son otra magnitud y no cambian.
- **Sanciones por acumulación de rojas** (dos amarillas en partidos distintos, ciclos por rojas) y cualquier regla disciplinaria nueva.
- **Catálogo de eventos, asistencia, marcador, sustituciones, segmentos y walkover:** fuera de alcance.
- **Superficies nuevas de consulta de sanciones**, paneles, informes o exportaciones.
- **Cambios en `engine_version` o en el contrato cerrado.**

## Criterios de finalización

| # | Criterio de finalización | RF |
|---|---|---|
| 1 | Desde esta corrección, una expulsión por doble amarilla produce **exactamente una** sanción, también cuando una de sus amarillas cruza un umbral de acumulación. | RF-001, RF-002 |
| 2 | La sanción única dura lo que la configuración efectiva de la versión publicada fija para la sanción por expulsión, y los partidos de suspensión cumplidos coinciden con esa duración. | RF-003 |
| 3 | Ninguna de las dos amarillas de la expulsión se descuenta; el conteo usa el historial en un orden total y estable y después el acta en cierre, el índice del acta solo se aplica al acta en cierre, el conteo es conmutativo y una acumulación histórica no se vuelve a originar. | RF-004 |
| 4 | Cerrar un acta solo origina sanciones por sus propios eventos: el historial no crea ni reintroduce ninguna, no duplica la conservada y no añade una segunda sanción por un evento de roja del acta —comprobado aparte de la identidad por motivo—. | RF-005 |
| 5 | Ninguna acta cerrada se revalida, ninguna sanción existente cambia de motivo, duración o estado, y una sanción histórica etiquetada como roja directa no se reescribe ni se duplica. | RF-006 |
| 6 | La regla es fija en el motor: no hay clave nueva, `schema_version` no cambia, `engine_version` sigue en `2026.1`, el contrato cerrado no cambia y la excepción a §3.2 está declarada con sus cuatro elementos. | RF-007, RNF-004 |
| 7 | El reinicio por cambio de fase se aplica primero y delimita el conteo del umbral; el emparejamiento se decide siempre dentro del acta. | RF-008 |
| 8 | La roja directa con umbral cruzado mantiene sus dos sanciones y está probado. | RF-009 |
| 9 | La sanción se deriva del tipo de roja registrado, también en el cierre que la registra, y la absorción se aplica en ese mismo cierre. | RF-010 |
| 10 | No queda ninguna sanción residual de la misma jugada y el jugador vuelve a ser elegible al cumplir los partidos de suspensión de la duración configurada. | RF-011 |
| 11 | La sanción es trazable a su partido y evento, y desde esta corrección un mismo evento de roja no tiene dos sanciones ni una jugada dos motivos; el recuento auditorado es el de las sanciones realmente creadas. | RF-012 |
| 12 | El orden de 14 pasos, la coherencia de la doble amarilla, el catálogo de eventos, la inmutabilidad y el walkover siguen intactos. | RF-013 |
| 13 | Ningún dato de otra organización influye en la sanción y ningún mensaje expone datos personales. | RF-014, RNF-001, RNF-002 |
| 14 | No se añade superficie nueva ni se altera ninguna proyección pública. | RF-015 |
| 15 | No hay migración ni filas reescritas. | RNF-005 |
| 16 | Pasan las pruebas sin base y con base, la compilación del backend y las comprobaciones del frontend que apliquen; `pnpm run e2e:test` termina con veredicto **0**; lo no ejecutado se declara **no ejecutado**. | RNF-006 |
| 17 | La documentación del proyecto describe la regla y `engine_version` sigue en `2026.1`. | RNF-007 |

## Dudas abiertas

Ninguna.

| Id | Decisión (2026-10-25) |
|---|---|
| **Q-1** | Una sola sanción con la duración configurada para la sanción por expulsión, aplicada una vez; la acumulación no la alarga. |
| **Q-2** | Se absorbe cualquier umbral cruzado por las amarillas del acta que compone la expulsión, sea la primera o la última, y también si se cruzan dos umbrales; el emparejamiento se decide solo dentro del acta. |
| **Q-3** | La amarilla que provoca la expulsión sigue contando para futuras acumulaciones; no se reescribe el conteo. |
| **Q-4** | Solo hacia delante: ninguna acta cerrada se revalida y ninguna sanción existente cambia; una acta abierta aplica la regla al cerrarse. |
| **Q-5** | Fija en el motor, sin clave nueva; `engine_version` sigue en `2026.1` y el contrato cerrado no cambia. |
| **Q-6** | El reinicio de fase manda: se aplica primero y delimita el conteo del umbral (fase y versión con el reinicio activo; todo el torneo sin él). |
| **Q-7** | La roja directa junto a un umbral queda fuera de alcance: se mantienen las dos sanciones. |
| **Q-8** | Se corrige aquí la etiqueta de la roja recién registrada: la sanción se deriva del tipo tal como queda registrado, también en el cierre que la registra. |
| **Q-9** | Sin pantalla ni endpoint nuevos: el efecto visible sigue siendo el bloqueo de planilla y el recuento del cierre. |
| **R-1** | Se mantiene la regla fija en el motor y se declara la excepción acotada de §5.1 (justificación, alcance, responsable y aprobación del revisor), sin enmienda de la constitución. |
| **R-2** | La sanción única usa la única duración de expulsión de la configuración (hoy 1 partido por defecto, aplicada a toda roja); no se añade ni se renombra ninguna clave. |
| **R-3** | Un evento de roja tiene como máximo una sanción, con cualquier motivo: si ya tiene una —aunque esté guardada como roja directa— no se crea otra con el motivo corregido ni se reescribe la existente. |
| **R-4** | El historial identifica el partido de cada tarjeta y la derivación es determinista con datos persistidos (R-6), como requisito verificable. |
| **R-5** | La auditoría del cierre registra el número de sanciones realmente creadas, no el tamaño de la lista derivada. |
| **R-6** | El desempate del historial no se persiste: se ordena por partido, minuto, minuto añadido e identificador del evento (desempate estable), y el índice del acta solo aplica al acta que se está cerrando; sin columna nueva, el requisito es determinismo. |
| **R-7** | Solo los eventos del acta que se cierra originan sanciones; el historial disciplinario solo cuenta amarillas y empareja, y nunca crea sanciones nuevas. |
