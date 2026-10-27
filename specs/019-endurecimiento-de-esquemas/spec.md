# Spec 019 — Endurecimiento de los esquemas de petición

Estado: implementada (2026-10-26)

## Contexto y objetivo

Hoy el sistema **ignora en silencio** cualquier clave que un cliente envíe en el cuerpo de una petición y que el esquema no declare. La única excepción es el **evento del acta**, que desde la spec 015 se rechaza con **422** estructural. Es una excepción consciente y documentada: el evento viaja completo a la auditoría del cierre y una clave ignorada sería un canal de texto libre hacia el acta.

Ese mismo razonamiento vale para el resto de los cuerpos y no se aplicó. Una clave ignorada es, en todos los casos, un canal silencioso: un campo que el cliente cree persistido y no lo está, una bandera de interfaz que se filtra, un dato que alguien intenta colar y el servidor descarta sin decirlo. Y produce un segundo problema, diferido: el día que un esquema se endurezca por otro motivo —una restricción nueva, un campo que pasa a ser obligatorio, un catálogo que se cierra— el cliente que hoy manda la clave de más romperá **sin aviso y sin relación aparente** con el cambio que lo rompe.

Esta spec no corrige un cálculo ni una regla deportiva: convierte una tolerancia implícita en una regla explícita. El cliente deja de poder mentir sobre lo que envía y el servidor deja de aceptar en silencio lo que no entiende.

**Objetivo:** que una clave no declarada en el cuerpo JSON de una petición deje de ignorarse y se rechace con el **422 estructural** que ya existe, **en todos los cuerpos de la API**, sin alterar las respuestas, los datos guardados ni ninguno de los rechazos de dominio vigentes.

### Comportamiento actual verificado

| # | Hecho verificado |
|---|---|
| 1 | De todos los cuerpos de petición de la API, **solo el evento del acta** rechaza una clave de primer nivel que el tipo no declara; el resto la ignora y responde con éxito. |
| 2 | La documentación de la API declara **33 operaciones con cuerpo JSON**, que usan **29 modelos de nivel superior**; con los **5 modelos que solo aparecen anidados** dentro de otro cuerpo, el endurecimiento toca **34 modelos**. Hay además **3 puntos de entrada con cuerpo multipart**, que quedan fuera de alcance. De esos 34 modelos, **solo el del evento** aplica ya la regla. |
| 3 | La **configuración de reglas** está cerrada en sus bloques anidados (una clave de más dentro de un bloque es **422**), pero **no en su primer nivel**: una clave inventada de primer nivel se acepta con **200/201** y se descarta, de modo que el cliente nunca sabe que no se guardó. |
| 4 | Esa configuración admite además un **bloque deprecado** que el servidor acepta, no escribe y del que solo promueve una clave al primer nivel al guardar. Es la única compatibilidad declarada del proyecto en un cuerpo JSON. |
| 5 | Los mapas con claves libres son **tres**, todos dentro de la configuración de reglas: los parámetros de un criterio de desempate, el mapa de overrides indexado por fase y el contenido del bloque deprecado. El `metadata` del evento **no** es libre: su catálogo cerrado es de la spec 015. |
| 6 | Cuatro cuerpos del cliente se envían **sin construirse campo a campo**: tres extendiendo un objeto de formulario reactivo y uno pasando el objeto de formulario completo. Los cuatro envían hoy solo campos declarados, pero **nada lo garantiza**: basta añadir una propiedad al formulario para que viaje. |
| 7 | La fuga **ya ocurrió**: una bandera de interfaz del formulario de segmento llegaba al servidor y solo dejó de hacerlo cuando el cuerpo pasó a construirse campo a campo. Con el esquema cerrado, esa petición habría respondido **422**. |
| 8 | El **422 estructural** se emite antes del manejador, se compone de una **lista** de errores y **no** lleva `code`. Cada elemento conserva el tipo, la ubicación y el mensaje, y **descarta el valor rechazado** y su contexto: el valor de una clave no declarada nunca vuelve al cliente. En los objetos que cierra el modelo de la petición la clave aparece en la **ubicación**; en los bloques que ya cierra el esquema de la configuración, el camino viaja **solo dentro del mensaje**, porque ese error es uno solo y su ubicación es el bloque. |
| 9 | El orden real es **por capas**. Primero van los rechazos de **forma del middleware**: tamaño del cuerpo y `Content-Length` (**400/413**). Después, **también en el middleware**, origen y CSRF (**403**). Después, **dentro de las dependencias**: sesión (**401**), cabecera de organización ausente (**400**) y membresía con rol activo (**403**), y por último el administrador de plataforma (**403**). El cuerpo se valida **después** de esas capas y **antes** del manejador, así que las comprobaciones que viven en el manejador quedan detrás: el permiso de la ruta (**403**) y la resolución del recurso de otra organización (**404**). Hoy, una clave de más junto a cualquiera de esas dos responde **403/404**; junto a una dependencia responde **400/401/403**. |
| 10 | Los cuerpos que **no** son JSON son tres: la importación de plantillas con CSV y ZIP opcional, la foto de un jugador y el escudo de un equipo. Los parámetros de consulta y las cabeceras se validan por otra vía y hoy ignoran lo que no declaran. |
| 11 | Las **respuestas** no dependen de este contrato: el contrato público del producto son las respuestas, y ninguna se valida con esta regla. |
| 12 | La configuración **efectiva** de una versión publicada se lee tal cual: no se revalida al leerla ni se reescribe. |
| 13 | Hay puntos de entrada que **no declaran cuerpo**: el alta con Google (`POST /auth/google`, que responde **410**), el cierre de sesión, el reenvío y la reapertura de una invitación y todas las operaciones de borrado. Hoy ignoran el cuerpo que reciban. El arranque del flujo (`POST /auth/google/start`) **sí** declara cuerpo (`GoogleStartRequest`) y entra en el alcance. |
| 14 | La documentación de la API **no distingue** los tres mapas abiertos de los bloques que la validación cierra en ejecución: `points_system`, `substitutions`, `discipline`, `stage_defaults`, los elementos del pipeline de desempate y el valor de cada override aparecen ahí como objetos abiertos, aunque hoy una clave de más en ellos ya sea **422**. |

Los hechos 6 y 7 son la prueba de que el problema es real y no teórico: la tolerancia no solo acepta basura, también **oculta** el error hasta que otra cosa cambia. El hecho 9 es la parte del contrato que **cambia** y se declara en RNF-004; el hecho 14 es la razón de que el barrido se plantee por comportamiento y no por la forma publicada de los esquemas.

### Alcance

La regla cubre **todos los cuerpos JSON de la API**: las 33 operaciones con cuerpo JSON y sus 29 modelos de nivel superior —34 modelos contando los cinco que solo aparecen anidados—, incluidas las rutas de autenticación, de organización, de plataforma, de torneos, de plantillas y del acta. La garantía es total porque una regla por ruta no se puede citar como garantía y deja abiertos precisamente los canales de mayor valor —la configuración de reglas y las plantillas de jugadores—.

El alcance **no amplía la superficie de escritura**: no añade ningún permiso, pantalla, endpoint ni dato nuevo; solo convierte un rechazo silencioso en uno explícito. El endurecimiento es **recursivo en los objetos declarados** —una clave desconocida anidada, en cualquier profundidad y también dentro de listas, es **422**— y su única excepción son los **mapas abiertos** que ya existen y el **bloque deprecado** de la configuración, enumerados en RF-004.

### Dependencias con otras specs

- **015 (catálogo de eventos):** es la que ya rechaza la clave no declarada en el evento, su `metadata` y sus campos por tipo. Esta spec **no cambia** ese catálogo: lo toma como precedente y lo extiende al resto de cuerpos.
- **017 (cierre de actas):** el **422 estructural** que esta spec añade pertenece a la misma clase que los suyos —se resuelve antes del manejador, prevalece sobre cualquier paso de dominio y no lleva `code`— y se suma a ellos sin mover el orden de 14 pasos.
- **016 (walkover):** el cuerpo del cierre es de las 017/016; esta spec no toca ni el motivo del walkover, ni su catálogo, ni su marcador derivado. Un walkover con una clave de más pasa a ser **422** estructural en lugar de ignorarla, que es exactamente la regla de esta spec.
- **014 (escudos), 012 (plantillas y Workspace), 010/011 (E2E y worker):** no cambian. La importación de plantillas, la foto y el escudo son cuerpos que no son JSON y quedan fuera.

## Usuarios

- **Cliente de la API (la propia aplicación web):** envía cuerpos que ahora deben coincidir exactamente con el esquema; descubre en el desarrollo, y no en producción, cuándo su cuerpo tiene una clave de más.
- **Mantenedor:** necesita que la regla sea única y comprobable, y que un cuerpo nuevo no pueda nacer sin ella.
- **Administrador o dueño de la organización:** depende de que el rechazo del cuerpo no altere la autorización que ya conoce ni le haga perder errores de permiso legítimos sobre peticiones bien formadas.
- **Operador de partido y árbitro:** su trabajo diario —segmentos, planilla, eventos, cierre— no puede volverse más frágil.
- **Responsable de seguridad y privacidad:** espera que un rechazo no devuelva lo que el cliente envió ni deje rastro con datos personales.
- **Administrador de plataforma:** sus cuerpos entran en la misma regla; no pierde ninguna capacidad.

## Roles y visibilidad

- **No cambia ningún rol, permiso ni ámbito.** No se añade ni se retira permiso, rol por organización, delegación por partido ni pantalla. La autorización aditiva y la resolución de recurso conservan su lógica: lo único que cambia es **cuándo** se contestan cuando el cuerpo trae una clave de más.
- **Precedencia por capas.** La petición se contesta en este orden: primero los rechazos de **forma del middleware** —tamaño del cuerpo y `Content-Length` (**400/413**)—; después, **también en el middleware**, origen y CSRF (**403**); después las **dependencias** —sesión (**401**), cabecera de organización ausente (**400**), membresía con rol activo (**403**) y administrador de plataforma (**403**)—; después el **cuerpo**; y por último las comprobaciones que viven en el **manejador** —permiso de la ruta (**403**) y resolución del recurso de otra organización (**404**)—. Con una clave de más, todo lo que precede al cuerpo conserva su respuesta y lo que viene después pasa a **422**. Es el cambio de códigos declarado en RNF-004.
- **Administrador de plataforma:** las cinco operaciones de plataforma con cuerpo comprueban que el usuario lo sea **antes** del cuerpo, así que un usuario que no lo es recibe **403** aunque traiga una clave de más; un perfil de solo lectura de plataforma que pasa esa comprobación falla después, en el manejador, y con una clave de más recibe **422**.
- **Miembro sin rol:** conserva su **403** de contexto, porque la membresía con rol activo precede al cuerpo.
- **Observador (`viewer`):** sin cambios; no gana ni pierde nada, y el rechazo no depende del rol.
- **Público:** no aplica. Las rutas públicas son de solo lectura y no reciben cuerpo; ninguna proyección pública cambia.
- **Aislamiento:** la comprobación del cuerpo no abre transacción ni consulta por sí misma, y el rechazo no revela si un recurso existe —depende solo del cuerpo, nunca del recurso ni del permiso que se habría comprobado después—. Ninguna organización puede ver ni modificar nada de otra a través de esta regla.

## Historias de usuario

- **HU-1.** Como mantenedor, quiero que una clave no declarada se rechace siempre, para no tener que recordar en qué cuerpos la tolerancia sigue viva.
- **HU-2.** Como mantenedor, quiero que un cuerpo nuevo no pueda nacer sin la regla, para que la garantía no se degrade con el tiempo.
- **HU-3.** Como cliente de la API, quiero saber que mi cuerpo no coincide con el contrato antes de que un cambio ajeno me rompa, y quiero que el error me diga dónde está la clave.
- **HU-4.** Como responsable de seguridad y privacidad, quiero que el rechazo no devuelva lo que envié ni lo deje en registros, auditoría ni proyecciones públicas.
- **HU-5.** Como administrador, quiero que el endurecimiento no cambie lo que ya sé —mismos permisos, mismos conflictos de dominio, mismas respuestas— y que el único rechazo que pueda adelantarse sea el del cuerpo mal formado, nunca el de mi sesión, mi membresía ni mi condición de administrador de plataforma.
- **HU-6.** Como operador, quiero que la pantalla de operación no se rompa por una bandera que solo existe en mi navegador.

## Definiciones

- **Cuerpo JSON de petición.** El objeto que un cliente envía como cuerpo de una petición con contenido JSON. No incluye los cuerpos multipart, los parámetros de consulta ni las cabeceras.
- **Punto de entrada con cuerpo JSON.** Cada par método y ruta que la documentación de la API publica con un cuerpo de contenido JSON. Son **33**; los **3** que declaran multipart quedan fuera de alcance, y los que no declaran cuerpo no forman parte de esta regla.
- **Modelo de nivel superior.** El que un punto de entrada declara como cuerpo. Son **29** y no coinciden con los 33 puntos porque un mismo modelo se reutiliza en varias rutas. **Modelo anidado:** el que solo aparece dentro de otro cuerpo; son **5**, así que el endurecimiento toca **34 modelos**.
- **Clave declarada.** La que el esquema del cuerpo enumera como campo. **Clave no declarada:** cualquier otra, incluida la que se parece a una declarada.
- **Primer nivel.** Las claves del objeto raíz del cuerpo. **Anidada:** una clave dentro de un objeto hijo del cuerpo, en cualquier profundidad, incluidos los elementos de una lista.
- **Objeto cerrado.** Un objeto cuyo conjunto de claves está fijado por el contrato. **Mapa abierto:** un objeto cuyas claves son datos y no campos; están enumerados en RF-004 y no hay otros.
- **422 estructural.** El rechazo que se produce **antes** de que el manejador de la petición se ejecute, porque el cuerpo no cumple el esquema. Prevalece sobre los rechazos de permiso, de recurso y de dominio, y **no** lleva `code`.
- **Clave de interfaz.** Un valor que solo existe para gobernar la pantalla —una bandera de «editado a mano», un estado de carga, una selección local— y que **no** forma parte del contrato de la petición.
- **Barrido.** La comprobación que recorre **todos** los cuerpos declarados por la propia API y falla si alguno no aplica la regla, para que la garantía no dependa de recordar añadirla.

## Requisitos funcionales

- **RF-001.** CUANDO una petición lleve en el cuerpo JSON una clave de primer nivel que el esquema del cuerpo no declare, EL SISTEMA responderá **422** estructural y **no ejecutará** la acción.
  *Criterios de aceptación:*
  - Aplica a las **33 operaciones con cuerpo JSON** y a sus **29 modelos de nivel superior** —34 contando los anidados—, sin lista de excepciones por ruta ni por rol.
  - El rechazo **no escribe**: no crea ni modifica filas, no audita, no emite eventos, no envía correo, no emite enlaces y no firma ni sube objetos.
  - La respuesta es la del **422 estructural** vigente, con la forma de RF-010, y **no** lleva `code`.
  - El rechazo se produce también cuando la clave no declarada tiene valor `null`, cadena vacía o un valor del tipo que el campo declarado tendría.
  - El rechazo se produce con independencia de que el resto del cuerpo sea válido, y el mensaje identifica la clave sin repetir su valor.
  - **No** se adelanta a ninguna de las comprobaciones previas al cuerpo —rechazos de forma del middleware (tamaño del cuerpo), origen y CSRF, también del middleware, y dependencias (sesión, cabecera de organización ausente, membresía con rol activo y administrador de plataforma)— (RF-009), y **sí** precede al permiso de la ruta, a la resolución del recurso y a cualquier conflicto de dominio.

- **RF-002.** CUANDO la clave no declarada aparezca dentro de un **objeto declarado anidado**, en cualquier profundidad, EL SISTEMA responderá **422** estructural con la misma forma y la misma ausencia de `code`.
  *Criterios de aceptación:*
  - El rechazo es **recursivo**: no depende de la profundidad ni de que el objeto esté en una lista, y un solo elemento con una clave de más rechaza el cuerpo completo.
  - La única excepción son los **mapas abiertos** y el **bloque deprecado** enumerados en RF-004; no hay ninguna otra.
  - La **ubicación** del error se informa donde el contrato ya puede informarla: en los objetos cuyo cierre impone el modelo de la petición, la clave aparece en la ubicación del error; en los **bloques que ya cierra la validación de la configuración**, el camino viaja **solo dentro del mensaje** y la ubicación señala el bloque. Esta spec **no cambia** el formato de esos errores ya existentes: los describe tal como son.
  - El `metadata` del evento del acta conserva su regla propia (spec 015): no se abre ni se cierra de nuevo.

- **RF-003.** CUANDO una configuración de reglas traiga una clave de primer nivel no declarada, EL SISTEMA responderá **422** en lugar de descartarla en silencio.
  *Criterios de aceptación:*
  - El comportamiento cambia de **200/201 con la clave descartada** a **422**: es el único punto de esta spec donde hoy ya se «pierde» un dato sin avisar.
  - Los bloques **anidados** no cambian: los cerrados ya responden **422**, con el formato descrito en RF-002, y los mapas abiertos de RF-004 ya admiten claves.
  - El bloque **deprecado** se sigue aceptando, se sigue promoviendo su clave al primer nivel al guardar y **no** se escribe. No se retira en esta spec.
  - **Ida y vuelta intacta:** el servidor devuelve la configuración guardada tal como está almacenada y el editor la normaliza antes de reenviarla, descartando lo que no conoce; por eso una configuración **escrita por la API**, tal como la devuelve la lectura, se sigue aceptando al reenviarse. El cambio alcanza solo a lo que un cliente **envía**, nunca a lo que ya está guardado. Un uso que revalide una configuración contra el esquema de configuración ya rechaza hoy una clave no declarada, sea de primer nivel o de un bloque anidado, porque ese esquema es cerrado en la raíz; ningún camino de lectura revalida.
  - Guardar o publicar reglas **no** revalida versiones publicadas, no reescribe ninguna fila y no cambia `schema_version` ni `engine_version`.

- **RF-004.** EL SISTEMA admitirá claves libres **solo** en los mapas abiertos que ya existen, y en ningún otro lugar.
  *Criterios de aceptación:*
  - La lista es **cerrada y enumerada**: los parámetros de un criterio de desempate, las claves del mapa de overrides indexado por fase y el contenido del bloque deprecado de la configuración.
  - Cualquier otra clave, en cualquier otro objeto y en cualquier profundidad, es **422**.
  - Los valores de un mapa abierto se validan por las reglas propias de su contenido, no por esta regla; en el bloque deprecado solo se valida la clave que se promueve al primer nivel.
  - Ampliar la lista exige cambiar esta spec: no es configuración ni se deduce del cuerpo.
  - Un mapa abierto **no** se convierte en una puerta: la clave libre es la que el contrato permite, no cualquier clave en cualquier nivel.

- **RF-005.** CUANDO el cliente componga el cuerpo de una petición, solo incluirá campos declarados; el estado de interfaz **no** viaja.
  *Criterios de aceptación:*
  - Los **cuatro** cuerpos que hoy se envían sin construirse campo a campo se **blindan**: el alta de jugador de la plantilla, la invitación de un miembro y la asignación de oficial de un partido —que extienden el objeto de formulario— y la creación de un torneo desde el listado del Workspace, que pasa el objeto de formulario completo. El resto de los cuerpos ya se envía **campo a campo o con un constructor propio** y no cambia.
  - Cada cuerpo se construye con un **constructor puro** que recibe los valores del formulario y devuelve exactamente las claves declaradas, siguiendo el patrón que ya usa el cuerpo del cierre del acta.
  - **Cada uno de los cuatro** tiene su prueba: se añade una bandera de interfaz al formulario y se comprueba, sobre el constructor, que el cuerpo resultante no la contiene y que sus claves son exactamente las declaradas.
  - Las pruebas son de **utilidad pura**, con un constructor por cuerpo, y corren con el ejecutor de pruebas de Node del proyecto (`node --test`), porque en el proyecto no existe una prueba de componente que pueda ejercitarlo.
  - El servidor no necesita ninguna tolerancia para esto: la garantía es RF-001 y el cliente deja de depender de ella.
  - El cambio es del cliente **y** del servidor, con papeles distintos: el servidor cierra el contrato y el cliente **se blinda** para no enviar nunca una clave que el contrato no declara.

- **RF-006.** EL SISTEMA conservará sin cambios la validación de los cuerpos que **no** son JSON y de lo que no es cuerpo.
  *Criterios de aceptación:*
  - La importación de plantillas con CSV y ZIP opcional, la foto del jugador y el escudo del equipo siguen aceptando y validando lo mismo; un campo de formulario de más no pasa a ser **422** por esta regla.
  - Los parámetros de consulta y las cabeceras conservan su comportamiento actual, incluida su tolerancia.
  - Los puntos de entrada que **no declaran** cuerpo JSON conservan su comportamiento: el cuerpo que reciban se sigue ignorando y el alta con Google —`POST /auth/google`— sigue respondiendo **410**. Su arranque, `POST /auth/google/start`, **sí** declara cuerpo (`GoogleStartRequest`) y entra en el alcance de RF-001.
  - Esta exclusión es de **alcance declarado**, no un olvido: queda registrada como riesgo aceptado (RNF-011).

- **RF-007.** EL SISTEMA no modificará las **respuestas**, los datos guardados ni el estado de las actas.
  *Criterios de aceptación:*
  - Ninguna respuesta gana, pierde, renombra ni estrecha un campo; los modelos de respuesta **no** se tocan.
  - Ninguna fila se revalida ni se reescribe; un evento o una configuración históricos con una forma que hoy ya no se envía se siguen leyendo igual, y la configuración se sigue devolviendo tal como está almacenada.
  - Un acta confirmada sigue siendo inmutable y sin vía de corrección; esta spec no añade ninguna.
  - No hay migración: el esquema de la base de datos no cambia.

- **RF-008.** EL SISTEMA mantendrá intactos los rechazos de dominio y estructurales ya existentes.
  *Criterios de aceptación:*
  - Los **422 estructurales** del acta (campos no aplicables, rangos, identificadores duplicados, número máximo de eventos) se conservan tal cual, prevalecen sobre cualquier paso de dominio y **no** llevan `code`.
  - El **catálogo cerrado** de eventos de la 015, la regla de `metadata`, la asistencia y la forma del identificador de cliente no cambian.
  - Los **409** con `code` aditivo de segmentos, límites de plantilla, asistencia, walkover, cierre y doble amarilla no cambian de código, de orden ni de mensaje.
  - La **coherencia numérica** del marcador sigue siendo **409** sin `code`, y el orden único de 14 pasos del cierre no se mueve.
  - La importación de plantillas, sus avisos y sus límites no cambian.
  - Una petición **bien formada** conserva su rechazo de permiso o de recurso: el **403** y el **404** por organización solo cambian cuando el cuerpo trae una clave de más (RF-009).

- **RF-009.** EL SISTEMA validará el cuerpo **después** de los rechazos de forma y de las comprobaciones declaradas como dependencia, y **antes** de las comprobaciones del manejador.
  *Criterios de aceptación:*
  - **Preceden al cuerpo**, en este orden: los rechazos de **forma del middleware** —tamaño del cuerpo y `Content-Length` (**400/413**)—; después, **también en el middleware**, origen y CSRF (**403**); después, las **dependencias** —sesión (**401**), cabecera de organización ausente (**400**), membresía con rol activo (**403**) y administrador de plataforma (**403**)—. Una petición sin sesión con una clave de más responde **401**, también cuando falta la cabecera de organización; una petición autenticada sin cabecera de organización, **400**; un miembro sin rol, **403**; un usuario que no es administrador de plataforma en una operación de plataforma, **403**.
  - **Quedan después del cuerpo** las comprobaciones que viven en el manejador: el **permiso de la ruta** (**403**) y la **resolución del recurso de otra organización** (**404**). Con una clave de más, ambas respuestas pasan a **422**; es el cambio de códigos declarado en RNF-004 y no altera la autorización de ninguna petición bien formada.
  - Un perfil de solo lectura de plataforma que **sí** pasa la comprobación de dependencia falla después, en el manejador, y con una clave de más recibe **422**.
  - El rechazo de cuerpo no revela la existencia de un recurso, de una cuenta ni de una organización: la respuesta depende solo del cuerpo, nunca del recurso ni del permiso que se habría comprobado después.
  - Ninguna ruta cambia de método, de forma de identificador ni de ámbito, y no se añade ni se retira ningún permiso.

- **RF-010.** EL SISTEMA mantendrá la **forma actual** del error de validación y no añadirá nada al cuerpo del error.
  *Criterios de aceptación:*
  - `detail` sigue siendo una **lista** y cada elemento conserva el tipo, la ubicación y el mensaje; el valor rechazado y su contexto **no** se devuelven.
  - La **ubicación** se informa como hoy: la clave rechazada aparece en la ubicación cuando el cierre lo impone el modelo de la petición, y solo dentro del mensaje cuando el error lo produce un bloque que ya cierra el esquema de la configuración (RF-002).
  - El error **no** lleva `code`, coherente con la clase estructural de la 017; los `code` aditivos de los **409** siguen siendo suyos y no se mezclan.
  - El **nombre** de la clave puede aparecer en la ubicación o en el mensaje, porque es lo que permite corregirlo; ese nombre solo viaja al cliente que lo envió y **no** se escribe en el registro de acceso, en la auditoría ni en ninguna proyección pública.
  - Los mensajes del marco de validación se conservan en su idioma; los mensajes de dominio siguen en español.
  - La documentación interactiva de la API refleja el cierre de los **cuerpos de nivel superior** y de los tres mapas abiertos, que son los que publica como cerrados o abiertos; **no** documenta el cierre de los bloques anidados que la validación ya cierra en ejecución, porque su forma publicada los sigue mostrando abiertos (hecho 14). No se promete esa distinción y la spec no la introduce.

- **RF-011.** EL SISTEMA aplicará la regla **sin leer ni escribir datos de ninguna organización**.
  *Criterios de aceptación:*
  - La comprobación del cuerpo **no abre transacción ni consulta por sí misma**; la autorización previa conserva las suyas y no se altera.
  - El comportamiento es idéntico en todas las organizaciones, sin valores por torneo, por versión ni por rol.
  - Ninguna organización puede ver ni modificar nada de otra a través de esta regla, y el mensaje no distingue organizaciones.

- **RF-012.** EL SISTEMA no añadirá superficie nueva.
  *Criterios de aceptación:*
  - No se añade endpoint, permiso, rol, pantalla, campo público, clave de configuración, evento de outbox ni acción auditada.
  - No hay migración y el esquema de la base de datos no cambia.
  - `engine_version` sigue en **2026.1** y `schema_version` no cambia: el contrato interno de reglas no se toca.

## Requisitos no funcionales

- **RNF-001 (aislamiento).** La comprobación del cuerpo no consulta datos de ninguna organización; ninguna organización influye en el resultado de otra y el rechazo no revela existencia de recursos.
- **RNF-002 (privacidad).** El error no devuelve el valor rechazado ni su contexto, y el nombre de la clave no se registra en el log de acceso, en la auditoría ni en proyecciones públicas. No se introduce ningún dato personal nuevo. Un cuerpo de autenticación con una clave de más responde igual sea cual sea la cuenta, de modo que no sirve para enumerar cuentas.
- **RNF-003 (rendimiento).** La comprobación no añade consultas, lecturas ni llamadas externas y su coste es lineal en el número de claves del cuerpo. No se modifican tiempos de espera, tamaño de petición ni límites de conexión.
- **RNF-004 (contratos que cambian).** Se declaran: (a) una clave no declarada en **cualquier** cuerpo JSON deja de ignorarse y pasa a responder **422**, también en el primer nivel de la configuración de reglas, donde hoy se descartaba en silencio; (b) el cliente **se blinda**: los cuatro cuerpos afectados se construyen con un constructor puro y cada uno tiene su prueba, de modo que no puede volver a enviarse una clave que el contrato no declara; (c) la configuración de reglas cierra su **primer nivel** y conserva sus bloques anidados, su formato de error y su bloque deprecado tal como están, con el ida y vuelta intacto; (d) **la precedencia cambia**: con una clave de más, hoy el permiso de la ruta responde **403** y un recurso de otra organización responde **404**, y desde este cambio ambos responden **422**, porque esas comprobaciones viven en el manejador; todo lo que precede al cuerpo conserva su respuesta —los rechazos de forma del **middleware**, tamaño del cuerpo y `Content-Length` (**400/413**); origen y CSRF (**403**), también en el middleware; y las **dependencias**: sesión (**401**), cabecera de organización ausente (**400**), membresía con rol activo (**403**) y administrador de plataforma (**403**)—; (e) **no** cambia ningún código de respuesta de éxito, ni el catálogo de eventos, ni los `code` aditivos de los **409**, ni `engine_version` (**2026.1**), ni el contrato cerrado, ni los modelos de respuesta, ni la importación de plantillas, ni los cuerpos multipart, ni los parámetros de consulta, ni las cabeceras, ni la versión del producto; (f) el corte es **limpio y en un solo cambio**, sin ventana de gracia ni excepciones por ruta. Un cliente que ignore este aviso conserva su comportamiento salvo en (a), (c) y (d).
- **RNF-005 (base de datos).** **Sin migración**: no se añade columna, restricción, índice ni vista, y no se reescribe ninguna fila. El esquema vigente no cambia.
- **RNF-006 (verificación).** Debe pasar: `cd backend && pytest -q` sin base; la compilación del backend; las pruebas opt-in con base que cubren los cuerpos reales, con `RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL=…` (entre ellas las del cierre, las de configuración y plantillas y las de invitaciones y organizaciones); `cd frontend && pnpm test`; y `cd frontend && pnpm run typecheck` y `cd frontend && pnpm run build`. **El job de extremo a extremo es obligatorio** porque el escenario de operación y cierre envía cuerpos de configuración, equipos, segmentos, planilla y acta: `pnpm run e2e:test` debe terminar con veredicto **0**; **1** es un fallo de comportamiento, **2** de infraestructura y **3** una corrida inválida, y ninguno de los tres se declara verde. Existe además una **prueba de barrido de comportamiento**: **se deriva de las rutas y de la documentación de la propia API** —las **33 operaciones con cuerpo JSON**, sus **29 modelos de nivel superior** y los **5 anidados**, nunca una lista escrita a mano— y, por cada modelo y por cada bloque alcanzable, **construye un cuerpo con una clave extra y exige que se rechace**, en lugar de inspeccionar cómo se publica el esquema. Para los bloques que cierra la validación de la configuración usa **su propio validador**, porque la forma publicada no los distingue (hecho 14); y **excluye únicamente los tres mapas abiertos** de RF-004, donde la clave extra debe aceptarse. Falla si un cuerpo o un bloque nuevo no aplica la regla, de modo que ninguno puede nacer sin ella. Lo que no pueda ejecutarse se declara **no ejecutado**.
- **RNF-007 (documentación).** El cambio de contrato de RNF-004 se documenta en **todas** sus copias y en el mismo cambio: la cláusula de la 015 de «Contratos que cambian» **y** el apartado «Arquitectura Clave» de `AGENTS.md`, la sección del acta de `README.md`, el comentario y la configuración de cierre del modelo del evento en `backend/app/modules/matches/schemas.py` —que hoy justifican la regla como exclusiva del evento— y la documentación interactiva de la API, que la recoge del propio contrato y que seguirá mostrando abiertos los bloques anidados que la validación ya cierra (hecho 14). Se **exige una entrada nueva en «Contratos que cambian»** con la declaración de RNF-004: qué códigos cambian, que la configuración cierra su primer nivel y que el corte no tiene ventana de gracia. El contrato interno de reglas no cambia y `engine_version` sigue en **2026.1**.
- **RNF-008 (auditoría).** No se añade ninguna acción auditada y ningún rechazo de esta regla escribe auditoría. La auditoría del cierre conserva sus campos y su recuento.
- **RNF-009 (tiempo real y outbox).** No se añaden eventos de outbox ni mensajes de tiempo real; un rechazo no emite nada y no altera el estado de la conexión.
- **RNF-010 (sin efectos colaterales).** Un rechazo no deja rastro: ni fila, ni auditoría, ni outbox, ni correo, ni enlace, ni objeto almacenado, ni firma emitida. Repetir la misma petición inválida produce siempre la misma respuesta.
- **RNF-011 (riesgo aceptado).** Los cuerpos multipart, los parámetros de consulta, las cabeceras y los puntos de entrada que no declaran cuerpo **siguen ignorando** lo que no declaran. Se acepta y se registra aquí: cerrarlos exige una spec propia porque afecta a la importación, a los clientes de subida y a los enlaces. Tampoco detecta claves repetidas en el texto JSON de un mismo objeto, porque el análisis del cuerpo deja una sola antes de que la regla pueda verlas.

## Datos personales y privacidad

- **Datos personales involucrados:** el sistema no introduce ninguno nuevo; los cuerpos que ya los llevan (alta de jugador, aceptación de invitación, registro, inicio de sesión) no cambian de contenido.
- **Qué se expone:** nada nuevo. El error de validación no devuelve el valor rechazado ni su contexto, así que una fecha de nacimiento o un documento enviados en la clave equivocada **no** vuelven en la respuesta. El **nombre** de la clave sí puede volver al cliente que la envió, y solo a él.
- **Registros:** el log de acceso sigue registrando método, ruta y estado, sin consulta, cabeceras ni cuerpo; el nombre de la clave no se registra. No hay auditoría ni mensaje de dominio con datos personales.
- **Proyecciones públicas:** no aplica; ninguna cambia y ninguna consume cuerpos de petición.
- **Fotos y consentimiento:** no aplica; la subida de fotos es un cuerpo multipart y queda fuera del alcance (RF-006).

## Casos límite

1. **Clave desconocida de primer nivel con un valor válido del tipo que tendría el campo:** **422** igual (RF-001).
2. **Clave desconocida de primer nivel con `null` explícito:** **422**; `null` es un valor, no una ausencia (RF-001).
3. **Clave declarada con `null` explícito:** no es una clave no declarada; se aplican las reglas vigentes del campo —obligatorio, anulable o con default— (RF-001, RF-007).
4. **Campo declarado que falta:** se aplican las reglas vigentes; esta spec no cambia la obligatoriedad de nada (RF-007).
5. **Clave desconocida anidada en un objeto que cierra el modelo de la petición:** **422** y la clave aparece en la ubicación del error (RF-002).
6. **Clave desconocida anidada en un bloque que ya cierra la validación de la configuración:** **422**, con el camino **dentro del mensaje** y la ubicación señalando el bloque; el formato no cambia (RF-002, RF-010).
7. **Clave desconocida en un elemento de una lista:** **422** del cuerpo completo, y el error señala el índice (RF-002).
8. **Clave desconocida dentro de un mapa abierto —parámetros de desempate, overrides por fase o bloque deprecado—:** no es un error; ese mapa admite claves por contrato (RF-004).
9. **`metadata` del evento con una clave distinta de la declarada:** **422** por la regla de la 015, no por esta; el resultado visible no cambia (RF-002, RF-008).
10. **Cuerpo vacío `{}`:** se aplican las reglas vigentes: aceptado si todos los campos tienen default o son anulables, **422** por campo obligatorio si no; esta regla no añade nada (RF-007).
11. **Cuerpo `null` explícito en un punto de entrada cuyo cuerpo es opcional:** se conserva el comportamiento actual —se trata como ausente—; `null` no es una clave no declarada (RF-007).
12. **Petición sin cuerpo en un punto de entrada que lo admite opcional:** se conserva el comportamiento actual; la ausencia de cuerpo no es una clave no declarada.
13. **Cuerpo que no es un objeto —una lista o un valor suelto—:** **422** de tipo, no de clave no declarada; el mensaje sigue el del marco (RF-010).
14. **`Content-Type` que no es JSON con un cuerpo enviado:** conserva el rechazo actual por cuerpo ausente o inválido; esta regla no interviene ni lo convierte en un 422 por clave (RF-006).
15. **Punto de entrada que no declara cuerpo JSON —el alta con Google `POST /auth/google`, cierre de sesión, reenvío, reapertura y operaciones de borrado—:** el cuerpo se sigue ignorando y el alta con Google sigue respondiendo **410**; el arranque `POST /auth/google/start` **sí** declara cuerpo (`GoogleStartRequest`) y sí entra en el alcance (RF-006, RNF-011).
16. **Cliente antiguo que manda una clave de más:** pasa de **200/201** a **422**; es el cambio declarado en RNF-004.
17. **Cuerpo con una clave de más y un conflicto de dominio —por ejemplo, un segmento con número no consecutivo—:** **422** estructural (RF-001, RF-008).
18. **Clave de más sin sesión, sin membresía con rol activo, con origen o CSRF inválidos, sin cabecera de organización o con el cuerpo por encima del tamaño máximo:** se conserva el **400**, el **401** o el **403** correspondiente; esos rechazos preceden al cuerpo (RF-009).
19. **Clave de más en una operación de plataforma enviada por un usuario que no es administrador de plataforma:** **403**, porque esa comprobación se declara como dependencia y precede al cuerpo (RF-009).
20. **Clave de más en una operación de plataforma enviada por un perfil de solo lectura que sí pasa la comprobación de dependencia:** **422**, porque su rechazo vive en el manejador y llega después del cuerpo (RF-009).
21. **Clave de más con un permiso de ruta insuficiente:** **422**, que gana al **403** de permiso; es el cambio de códigos de RNF-004 (RF-009).
22. **Clave de más sobre un recurso de otra organización:** **422**, que gana al **404** de aislamiento; es el cambio de códigos de RNF-004 (RF-009).
23. **Petición bien formada con un permiso insuficiente o sobre un recurso ajeno:** conserva su **403/404** de siempre; esta spec no toca la autorización (RF-008).
24. **Clave de más en un cuerpo de autenticación:** **422** con independencia de la cuenta y de la contraseña, así que la respuesta no sirve para saber si la cuenta existe (RF-009, RNF-002).
25. **Clave de más en el cuerpo del acta —incluido el evento anidado—:** **422** estructural, como ya ocurre; el orden de 14 pasos no se mueve (RF-008).
26. **Clave de más dentro de un bloque que la validación de la configuración ya cierra** —`points_system`, `substitutions`, `discipline`, `stage_defaults`, un elemento del pipeline o el valor de un override—: **422** como hoy, aunque la documentación de la API lo muestre abierto (RF-002, RNF-006).
27. **Configuración de reglas con una clave de primer nivel inventada:** **422** en lugar del descarte silencioso (RF-003).
28. **Configuración de reglas con el bloque deprecado:** se acepta, se promueve su clave al primer nivel al guardar y el bloque no se escribe (RF-003, RF-004).
29. **Configuración escrita por la API, devuelta por una lectura y reenviada tal cual:** se acepta; el ida y vuelta no se rompe (RF-003).
30. **Configuración guardada con una clave que hoy no se envía:** se lee y se devuelve igual, no se revalida y nada se reescribe; si un cliente la reenvía **sin normalizarla**, responde **422**, y el editor la normaliza antes de enviarla (RF-003, RF-007).
31. **Importación de plantillas con un campo de formulario de más:** sin cambios; no es un cuerpo JSON (RF-006).
32. **Parámetro de consulta de más:** sin cambios; queda fuera de alcance (RF-006, RNF-011).
33. **Cuerpo multipart vacío o con el archivo equivocado:** conserva sus rechazos actuales; esta spec no los toca (RF-006).
34. **Dos claves iguales en el texto JSON de un mismo objeto:** el análisis del cuerpo deja una sola antes de que el servidor las vea; esta regla no puede detectarlas (RNF-011).
35. **Petición repetida con el mismo cuerpo inválido:** misma respuesta siempre, sin efectos y sin rastro (RNF-010).
36. **Cuerpo nuevo añadido en el futuro sin la regla:** el barrido falla, así que no puede entrar (RNF-006).

## Fuera de alcance

- **Cuerpos multipart**, incluidos la importación de plantillas con CSV/ZIP, la foto del jugador y el escudo del equipo (riesgo aceptado en RNF-011).
- **Parámetros de consulta y cabeceras**, que hoy ignoran lo que no declaran (RNF-011).
- **Puntos de entrada que no declaran cuerpo JSON**, incluido el alta con Google, el cierre de sesión, el reenvío y la reapertura de invitaciones y las operaciones de borrado: el cuerpo se sigue ignorando (RNF-011).
- **Modelos de respuesta:** no se endurecen, no se recortan y no se validan con esta regla. El contrato público son las respuestas y endurecerlas no aporta garantía.
- **Los `code` aditivos de los 409** y la clase de **422 estructural** existente: se conservan y no se unifican.
- **Claves repetidas en el texto JSON** y **cualquier validación del contenido libre** de un mapa abierto.
- **Retirar el bloque deprecado** de la configuración: se sigue aceptando y promoviendo; retirarlo es un cambio funcional propio.
- **Cambios en el catálogo de eventos, la asistencia, el walkover, el marcador, las sanciones, los segmentos o las sustituciones.**
- **Cambios en `engine_version`, `schema_version` o el contrato cerrado.**
- **Nuevas superficies**: endpoints, permisos, pantallas, campos públicos, eventos de outbox o acciones auditadas.
- **Migraciones y reescritura de datos.**

## Criterios de finalización

| # | Criterio de finalización | RF |
|---|---|---|
| 1 | Una clave de primer nivel no declarada en **cualquiera** de las 33 operaciones con cuerpo JSON responde **422** estructural, sin escribir nada, sin auditoría, sin outbox, sin correo, sin enlace y sin objetos. | RF-001, RNF-010 |
| 2 | Una clave no declarada dentro de un objeto declarado anidado, en cualquier profundidad y también dentro de listas, responde **422** con la misma forma, y la ubicación se informa donde el contrato ya puede informarla: clave en la ubicación para los objetos que cierra el modelo, camino en el mensaje para los bloques que ya cierra la validación de la configuración. | RF-002, RF-010 |
| 3 | Guardar una configuración de reglas con una clave de primer nivel no declarada responde **422** en lugar de descartarla, sus bloques anidados y su formato de error no cambian y el bloque deprecado se sigue aceptando y promoviendo. | RF-003 |
| 4 | Solo los tres mapas abiertos admiten claves libres; la lista está escrita y cualquier otra clave en cualquier otro objeto es **422**. | RF-004 |
| 5 | Una configuración **escrita por la API**, tal como la devuelve una lectura, se acepta al reenviarse; una configuración guardada con una clave que hoy no se envía se sigue leyendo y devolviendo igual, y solo falla si un cliente la reenvía sin normalizarla. | RF-003, RF-007 |
| 6 | Los cuatro cuerpos afectados del cliente se construyen con un constructor puro, cada uno tiene su prueba pura con el ejecutor de Node, y una bandera de interfaz añadida al formulario no aparece en el cuerpo resultante. | RF-005, RNF-006 |
| 7 | La importación de plantillas, la foto, el escudo, los parámetros de consulta, las cabeceras y los puntos de entrada sin cuerpo conservan su comportamiento, y la exclusión está registrada como riesgo aceptado. | RF-006, RNF-011 |
| 8 | Ninguna respuesta, fila, acta cerrada ni configuración guardada cambia; ningún modelo de respuesta se toca; no hay migración. | RF-007, RNF-004, RNF-005 |
| 9 | Los 422 estructurales del acta, el catálogo de eventos de la 015, los 409 con `code`, la coherencia numérica del marcador, el orden de 14 pasos del cierre, el walkover y los límites de plantilla siguen intactos y probados. | RF-008 |
| 10 | La precedencia por capas se cumple: tamaño del cuerpo o `Content-Length` inválido **400/413** (primera capa), origen o CSRF inválidos **403**, sin sesión **401**, cabecera de organización ausente **400** (tras la sesión, dentro de la dependencia), sin membresía con rol activo **403** y no-administrador de plataforma **403** conservan su respuesta; el **422** del cuerpo gana al **403** de permiso de ruta y al **404** de recurso de otra organización; una petición bien formada conserva su **403/404**. | RF-009, RNF-004 |
| 11 | El error de validación conserva su forma sin `code`, no devuelve el valor rechazado y no deja el nombre de la clave en el log de acceso, la auditoría ni ninguna proyección pública. | RF-010, RNF-002 |
| 12 | El rechazo no consulta ni escribe datos de ninguna organización por sí mismo y su comportamiento es idéntico en todas. | RF-011, RNF-001 |
| 13 | No se añade endpoint, permiso, rol, pantalla, campo público, clave de configuración, evento de outbox ni acción auditada; `engine_version` sigue en **2026.1** y `schema_version` no cambia. | RF-012, RNF-008, RNF-009 |
| 14 | Existe un barrido **de comportamiento**, derivado de las rutas y de la documentación de la API, que por cada modelo y por cada bloque alcanzable construye un cuerpo con una clave extra y exige rechazo —con el validador propio de la configuración para los bloques que ella cierra—, acepta la clave extra solo en los tres mapas abiertos y falla si alguno no aplica la regla. | RNF-006, RF-004 |
| 15 | Pasan `pytest -q` sin base, las pruebas opt-in con base, la compilación del backend, las pruebas, el chequeo de tipos y la construcción del frontend, y `pnpm run e2e:test` termina con veredicto **0**; lo no ejecutado se declara **no ejecutado**. | RNF-006 |
| 16 | La documentación se actualiza en todas sus copias y existe una entrada nueva en «Contratos que cambian» con la declaración de RNF-004. | RNF-007, RNF-004 |

## Dudas abiertas

Ninguna.

| Id | Decisión (2026-10-26) |
|---|---|
| **D-1** | El alcance es **todos** los cuerpos de petición —las 33 operaciones con cuerpo JSON, sus 29 modelos de nivel superior y los 5 anidados—: la garantía es total y no hay regla por ruta. |
| **D-2** | La configuración de reglas se incluye **solo en su primer nivel**; los bloques anidados ya están cerrados y no cambian. |
| **D-3** | El bloque deprecado `transfers` se **sigue aceptando y promoviendo** igual que hoy; no se retira en esta spec. |
| **D-4** | **Corte limpio en un solo cambio**, con el cliente corregido a la vez y el cambio declarado en RNF-004; sin ventana de gracia. Un cliente antiguo con una clave de más pasa de **200/201** a **422**. |
| **D-5** | Se mantiene el **422 estructural** tal cual: lista de errores, **sin `code`** y sin devolver el valor recibido, coherente con la 017. |
| **D-6** | Servidor y cliente, con papeles distintos: el servidor cierra el contrato, el cliente se blinda con constructores puros y **cada cuerpo** tiene su prueba. |
| **D-7** | Los modelos de respuesta **no** se tocan. |
| **D-8** | Multipart (importación CSV/ZIP), parámetros de consulta, cabeceras y puntos de entrada sin cuerpo quedan **fuera**, declarados como riesgo aceptado en RNF-011. |
| **R-1** | El **422 del cuerpo gana** al 403 por permiso y al 404 de recurso de otra organización; preceden el origen, el CSRF, la sesión (401) y la membresía con rol activo (403). |
| **R-2** | El recuento real es **29 modelos de nivel superior** y **33 operaciones con cuerpo JSON**, más 5 modelos que solo aparecen anidados (**34 modelos tocados**) y 3 cuerpos multipart; «punto de entrada» y «modelo de nivel superior» quedan definidos en la spec. |
| **R-3** | La **ubicación** de la clave se informa como hoy: en la ubicación del error para los objetos que cierra el modelo y solo en el mensaje para los bloques que ya cierra el esquema de la configuración; ese formato no se cambia. |
| **R-4** | El barrido **se deriva de las rutas y la documentación de la API**, recorre los esquemas recursivamente con sus cinco anidados y excluye solo los tres mapas abiertos; las pruebas del cliente son **constructores puros con el ejecutor de Node** y cubren los cuatro cuerpos. |
| **R-5** | **Ida y vuelta intacta**: el servidor devuelve la configuración tal como está guardada y el editor la normaliza; una configuración recibida y reenviada se acepta, y solo cambia lo que un cliente **envía** de más. |
| **R-6** | Los puntos de entrada que **no declaran cuerpo JSON** quedan **fuera** y siguen ignorando el cuerpo; el alta con Google conserva su **410**, y se añaden los casos de cuerpo `null` opcional y de `Content-Type` no JSON. |
| **R-7** | La precedencia es **por capas**: los rechazos de forma (400/413), el origen y el CSRF (403) —ambos en el **middleware**— y las comprobaciones de dependencia (sesión 401, cabecera de organización ausente 400, membresía con rol activo 403 y **administrador de plataforma 403**) preceden al cuerpo; el permiso de ruta (403) y el recurso de otra organización (404) viven en el manejador y con una clave de más pasan a **422**. |
| **R-8** | El barrido es **de comportamiento**, no estructural: por cada modelo y bloque alcanzable se construye un cuerpo con una clave extra y se exige rechazo, con el validador propio de la configuración para sus bloques; la documentación de la API no documenta el cierre de esos bloques anidados y no se promete. |
| **R-9** | Orden real de la **cabecera de organización ausente** (**400**): se comprueba **dentro de la dependencia y tras la sesión (401)**, antes de la membresía; origen y CSRF viven en el **middleware**, no en la dependencia. Reclasificada en las cuatro citas del orden (hecho 9, «Roles y visibilidad», RF-009 criterio 1 y criterio 10). **2026-10-26.** |
