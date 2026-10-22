# Spec 009 — Ciclo de vida de las invitaciones y salud del worker

Estado: aprobada (2026-10-21)

## Contexto y objetivo

Al cerrar la spec 008 quedaron tres decisiones anotadas que ninguna spec cubría: dos sobre el ciclo de vida visible de las invitaciones y una sobre la semántica de salud del worker. No son hallazgos de auditoría ni defectos nuevos: son huecos de contrato y de verificación que hoy dependen de comportamientos accidentales o de pruebas que no reproducen el escenario real.

1. **Semántica de la acción en estados no pendientes.** La lista de invitaciones ya ofrece «Reenviar» en vencidas y revocadas, pero no distingue qué significa en cada caso: sobre una vencida renueva el enlace de algo que caducó; sobre una revocada hoy la resucita, sin que ningún requisito lo autorice. Falta una acción propia para reabrir, confirmación, feedback del estado real y traducción. **No hay un defecto de visibilidad**: la fila y su estado ya se ven; lo que cambia es **qué acción se ofrece** en cada estado (HU-1).
2. **Reapertura de invitaciones revocadas.** Hoy la operación de reenvío no rechaza una invitación revocada y la vuelve a dejar pendiente. Es decir: revocar deja de ser definitivo, pero ningún requisito lo autoriza, lo describe ni lo audita. Al separar la reapertura del reenvío aparece una **tercera ruta de materialización del vencimiento** —además de crear y reenviar—: reabrir una revocada cuando el mismo correo tiene otra invitación almacenada como pendiente pero ya vencida (Q6).
3. **Transición real del worker a insano por bucle detenido.** La verificación de salud del worker se apoya en la frescura de una señal que publica su propio bucle. Falta definir con precisión qué significa «el bucle se detuvo», demostrar que esa transición ocurre de verdad con un proceso vivo, y separarla de «no hay eventos que procesar», que nunca debe considerarse insano.

**Objetivo:** convertir esas tres decisiones en requisitos verificables, respetando los contratos cerrados por la spec 008 **salvo los dos cambios de contrato declarados y numerados en RNF-004 (C-1 y C-2)** —reenviar una invitación revocada pasa a responder 409 y la reapertura se convierte en una tercera ruta de materialización del vencimiento—, sin cambiar el modelo de autorización y sin ampliar la superficie pública del producto.

La prueba de extremo a extremo en navegador del reintento del tiempo real **no forma parte de esta entrega**; se especifica en `specs/010-e2e-reintento-tiempo-real/` con su propio alcance, su propia pila de pruebas y su propio job de integración continua.

### Estado verificado (2026-10-21)

Comprobado sobre el árbol de trabajo; se describe el comportamiento observado, no el diseño:

1. La lista de invitaciones del Workspace ofrece «Reenviar» para **todo estado distinto de «aceptada»** —también vencidas y revocadas— y «Revocar» solo para pendientes. No existe ninguna acción de reapertura ni una etiqueta propia para ella.
2. La operación de reenvío **solo rechaza la invitación aceptada**. Sobre una revocada, la fila se reutiliza y queda pendiente, con token y fecha nuevos, borrando la marca de revocación. Sobre una vencida hace lo mismo, que es lo que la spec 008 exige.
3. El reenvío comprueba si existe **otra** invitación pendiente del mismo correo y responde 409 sin escribir ni enviar correo en ese caso; la unicidad de pendientes por organización y correo sigue siendo la garantía final.
4. Tras reenviar, el token anterior deja de resolver: el enlace previo responde «no encontrada», no «ya no disponible».
5. Crear una invitación nueva para un correo que solo tiene una invitación revocada responde 201 y crea otra fila; el índice de unicidad solo cubre las pendientes.
6. Entre las **acciones de invitación**, ninguna de las que **no consumen** la invitación escribe auditoría organizacional: crear, reenviar y revocar no dejan entrada. La aceptación es la única acción **de invitación** que **ya** deja entrada (`ACCEPT_INVITATION`, escrita por la migración 014 dentro de la aceptación) y la conserva; lo que falta es una entrada para la reapertura. Las demás entradas de auditoría que existen hoy pertenecen a acciones de otra naturaleza: guardar planilla, publicar o despublicar formación, asignar o retirar oficial, cambiar el rol o el estado activo de un miembro, interrumpir un segmento, cerrar un acta y resolver un partido administrativamente.
7. El worker publica su señal de vitalidad al principio de cada vuelta del bucle y su verificación de salud la considera caducada a los 90 s, con cadencia de 10 s. Un bucle bloqueado deja de publicar y, por tanto, debería pasar a insano; sin embargo, no existe ninguna prueba que lo demuestre, y un bucle que falla de forma permanente pero sigue girando publica la señal igual y permanece sano indefinidamente. El contrato de la spec 008 exige que el worker siga sano mientras el bucle avance aunque la base de datos esté caída.
8. El frontend solo tiene un runner de pruebas unitarias sobre funciones puras (`node --test --experimental-strip-types`) más aserciones que inspeccionan el texto de las páginas y del catálogo de traducciones; **no existe ningún arnés de componentes ni ninguna prueba de componente**, y no hay infraestructura de pruebas de navegador en el repositorio ni en la integración continua. Esa pieza se ha separado a la spec 010 y el método de verificación de esta entrega se fija en RNF-001 (Q8).

### Alcance

Las tres piezas que quedan encajan en una entrega pequeña, sin dependencias nuevas y sin migraciones: contrato de reapertura, qué ofrece la interfaz sobre él y comprobación real de la salud del worker. Son unas seis o siete tareas.

Fuera de esta entrega queda la prueba de extremo a extremo en navegador del reintento del tiempo real (antes llamada pieza 3). Introduce en el repositorio una pila de pruebas que no existe —navegador, servidor de aplicación, dependencias de desarrollo, un job nuevo de integración continua y su política de auditoría—, no cabe en el mismo límite de tareas y arrastra decisiones que no son de invitaciones ni de salud. Su contrato completo vive en la spec 010; nada de esta entrega la sustituye.

## Usuarios

- **Administrador de organización (dueño o administrador):** invita, reenvía, revoca y quiere poder rehabilitar una invitación revocada sin ambigüedad sobre qué enlace está vivo.
- **Persona invitada:** recibe un enlace; necesita que un enlace revocado no vuelva a funcionar por accidente y que el enlace vigente sea el último emitido.
- **Operador de despliegue:** confía en la verificación de salud para detectar un worker que dejó de avanzar, no solo un proceso que murió.
- **Revisor o auditor técnico:** necesita que cada decisión suelta quede cerrada con un requisito y una verificación reproducible.

## Roles y visibilidad

- **Público:** sin cambios. No ve invitaciones ni auditoría.
- **Miembro de organización sin permiso de gestión de miembros:** sin cambios. No ve la lista de invitaciones ni puede reenviar, reabrir o revocar; recibe el mismo rechazo que hoy.
- **Dueño y administrador (permiso de gestión de miembros):** siguen siendo los únicos que ven y operan invitaciones. No ganan visibilidad sobre otras organizaciones; la reapertura no concede permisos nuevos.
- **Persona invitada:** solo ve la previsualización de su enlace y el resultado de aceptarlo. Un enlace revocado sigue sin poder aceptarse y un enlace sustituido deja de existir.
- **Administrador de plataforma:** sin cambios; no gana acceso a las invitaciones ni a la auditoría organizacional.
- **Aislamiento:** toda lectura y escritura de invitaciones y de auditoría sigue sujeta al aislamiento por organización; ninguna otra organización puede ver ni modificar esos datos, y una invitación de otra organización se comporta como inexistente.

## Historias de usuario

- **HU-1.** Como administrador, quiero que una invitación vencida ofrezca «Reenviar» y una revocada ofrezca «Reabrir», para saber si voy a renovar un enlace caducado o a rehabilitar uno revocado.
- **HU-2.** Como administrador, quiero poder reactivar una invitación revocada y recibir un enlace nuevo, para no tener que crear otra invitación desde cero cuando el destinatario sigue siendo el mismo.
- **HU-3.** Como persona invitada, quiero que un enlace revocado no reviva por accidente, para que revocar signifique algo.
- **HU-4.** Como operador de despliegue, quiero que un worker cuyo bucle se detuvo se declare no sano aunque el proceso siga vivo, para poder reiniciarlo antes de acumular retraso.

## Definiciones

- **Acción de reenvío:** operación existente que reutiliza una invitación **pendiente vigente o vencida** y le asigna token y fecha de vencimiento nuevos, sin crear otra fila. Sobre una revocada no está permitida.
- **Reapertura:** acción explícita y distinta del reenvío que deja pendiente y usable una invitación **revocada**, reutilizando el mismo registro y con token y fecha de vencimiento nuevos. El token revocado nunca se reutiliza. La reutilización del registro y la eventual materialización previa (RF-001) ocurren en una sola transacción.
- **Materialización del vencimiento:** escritura que deja una fila almacenada como pendiente en estado vencido porque su fecha ya pasó. Ocurre solo en las rutas de escritura que la spec 008 autoriza (crear y reenviar) y, desde esta entrega, también en la reapertura cuando el mismo correo tiene otra pendiente ya vencida (Q6). Leer y previsualizar nunca materializan.
- **Enlace vigente:** el último enlace emitido por el servidor para una invitación. Todo enlace emitido antes deja de resolver y no puede aceptarse. Tras una reapertura o un reenvío exitoso, el enlace vigente es el de la **última emisión del servidor** para esa invitación: la interfaz no lo deduce del orden en que llegan las respuestas, y mientras una operación está en curso los controles están deshabilitados (RF-006), de modo que una misma pantalla no emite dos operaciones simultáneas sobre la misma invitación.
- **Invitación aceptada:** invitación ya consumida; no puede reenviarse, reabrirse ni revocarse.
- **Invitación vencida:** pendiente cuya fecha de vencimiento ya pasó; se presenta como vencida sin reescribir la fila, según el contrato de la spec 008. Su acción es reenviar, no reabrir.
- **Invitación revocada:** invitación invalidada por decisión administrativa. Reenviar sobre ella no está permitido; solo la reapertura la devuelve a pendiente.
- **Bucle detenido:** estado del worker vivo que **no completa una vuelta de su bucle dentro de 90 s**, haya o no eventos que procesar. Los 90 s son el **umbral de antigüedad máxima** que ya aplica el healthcheck actual; la publicación de la señal ocurre cada **10 s**. «Al menos cada 30 s» no es un umbral independiente: describía de forma imprecisa esa cadencia y queda retirado (Q7). Un fallo de dependencia con el bucle girando y reintentando **no** cuenta como detenido.
- **Vuelta completada:** una iteración del bucle que termina, con o sin trabajo, con o sin error de la dependencia.
- **Señal de vitalidad:** la marca que el bucle publica al principio de cada vuelta y cuya frescura decide la verificación de salud del worker.

## Requisitos funcionales

> El orden sigue la dependencia: primero el contrato de la reapertura (1–4), después lo que la interfaz ofrece sobre ese contrato y el reenvío (5–7), y al final la salud del worker (8–11).

### Reapertura de invitaciones revocadas

- **RF-001.** CUANDO un miembro con permiso de gestión de miembros solicite reabrir una invitación revocada de su organización, EL SISTEMA la dejará pendiente con token y fecha de vencimiento **nuevos**, reutilizando el mismo registro y sin crear otra invitación; el enlace anterior dejará de resolver y el nuevo será el único válido. SI el mismo correo tiene **otra** invitación almacenada como pendiente pero **ya vencida**, ENTONCES EL SISTEMA la materializará como vencida y después reabrirá la revocada, ambas cosas en la misma transacción y en ese orden.
  *Criterios de aceptación:*
  - **Mutación observable:** la invitación reabierta pasa a estado pendiente, recibe token y fecha de vencimiento nuevos, queda **sin marca de revocación** y actualiza su marca de tiempo de modificación; **conserva** su identificador, su fila y su correo y rol.
  - **Respuesta de éxito:** la reapertura responde **200** (el mismo código que un reenvío exitoso) con la representación de la invitación —estado pendiente, fecha de vencimiento nueva, sin marca de revocación— y el enlace nuevo listo para copiar; no devuelve el token como campo aparte ni datos de otra invitación.
  - **Orden y atomicidad (Q6):** primero se materializa la otra pendiente vencida del mismo correo (si existe) y solo después se reabre la revocada. Si cualquiera de los dos pasos falla, no persiste ninguno: no queda una invitación materializada sin reapertura ni una reabierta sin la materialización previa.
  - Una pendiente **vigente** del mismo correo **no** se materializa: bloquea la reapertura con 409 (RF-002).
  - Tras la reapertura hay exactamente una invitación pendiente para ese correo en la organización y un único enlace válido.
  - El enlace emitido antes de revocar no acepta la invitación después de la reapertura y no resuelve como una invitación existente.
  - Solo el enlace nuevo permite previsualizar y aceptar.
  - La operación solo actúa sobre invitaciones de la organización activa; una invitación de otra organización responde como inexistente.
  - Un miembro sin permiso de gestión de miembros recibe el mismo rechazo que hoy y no produce ningún cambio.

- **RF-002.** SI se intenta reabrir una invitación que **no está revocada** —pendiente, vencida o aceptada—, ENTONCES EL SISTEMA responderá **409** sin modificar el registro y sin emitir enlace nuevo; SI existe **otra** invitación pendiente **vigente** para el mismo correo en la organización, ENTONCES responderá **409** sin escribir, sin crear filas y sin enviar correo.
  *Criterios de aceptación:*
  - Reabrir una pendiente vigente responde 409 y **no renueva** su token ni su fecha por accidente.
  - Reabrir una vencida responde 409 y la deja como está: su acción es reenviar.
  - Reabrir una aceptada responde 409 y no cambia su estado, su token ni sus marcas de tiempo.
  - Con otra pendiente **vigente** del mismo correo, la respuesta es 409 y ni la invitación reabierta ni la pendiente existente cambian.
  - Con otra pendiente **vencida** del mismo correo no hay 409: la reapertura procede tras materializarla (RF-001) y al terminar queda una sola pendiente.
  - Ninguna de las respuestas 409 deja filas nuevas ni materializa la otra pendiente vencida si la reapertura se rechaza por otro motivo: un 409 no escribe nada.
  - La unicidad de pendientes por organización y correo se mantiene siempre; al terminar cualquier operación hay como máximo una pendiente por correo y organización.
  - La respuesta 409 no incluye el enlace ni el token de ninguna de las dos invitaciones.

- **RF-003.** SI se solicita reenviar una invitación revocada, ENTONCES EL SISTEMA responderá **409** sin escribir, sin enviar correo y sin devolver enlace, indicando que la invitación está revocada y que debe reabrirse; la fila conservará su estado revocado y su marca de revocación.
  *Criterios de aceptación:*
  - Reenviar una revocada no cambia el estado, el token, la fecha de vencimiento ni la marca de revocación.
  - La respuesta no incluye token, enlace ni correo del destinatario, y su motivo se distingue de los otros 409 de invitación (aceptada, otra pendiente vigente) mediante un identificador estable, sin exponer códigos internos al usuario.
  - Qué ve el administrador ante ese 409 —en su idioma activo y con la acción que debe usar— se especifica en RF-007; el mecanismo para conseguirlo se decide en el plan.
  - Reenviar una vencida sigue respondiendo con éxito y reutilizando la fila con token y fecha nuevos, como exige la spec 008.
  - Reenviar una pendiente vigente conserva el comportamiento actual.
  - La interfaz no ofrece reenviar sobre una revocada; el 409 protege a cualquier consumidor que lo intente.

- **RF-004.** CUANDO la reapertura se ejecute con éxito, EL SISTEMA registrará una entrada de auditoría organizacional con la acción, la invitación afectada y el miembro que la ejecuta, en la misma transacción y solo si hubo cambio efectivo; la entrada no contendrá el correo del destinatario ni el token.
  *Criterios de aceptación:*
  - Una reapertura con éxito produce exactamente una entrada; un intento que responde 409 no produce ninguna.
  - La entrada no incluye correo electrónico, token, enlace ni nombre de la persona.
  - Crear, reenviar y revocar invitaciones **no añaden** entrada; la **aceptación conserva la suya** (`ACCEPT_INVITATION`, migración 014) y la **reapertura añade una**. La materialización previa de otra pendiente vencida (RF-001) no añade una entrada propia: la única entrada de la operación es la de la reapertura.
  - La entrada de la reapertura se distingue de la de aceptación por su acción y queda sujeta al aislamiento por organización; no se expone en ninguna ruta ni proyección pública.
  - Si la operación falla y se revierte, no queda entrada.

### Acción visible y feedback

- **RF-005.** CUANDO la lista de invitaciones muestre una invitación vencida o revocada, EL SISTEMA ofrecerá la acción que corresponda a su estado, con una etiqueta propia y distinta para cada caso: **«Reenviar» en vencidas y «Reabrir» en revocadas**, sin ofrecer ninguna de las dos sobre invitaciones aceptadas.
  *Criterios de aceptación:*
  - Una invitación pendiente vigente conserva las acciones y el comportamiento que tiene hoy: reenviar y revocar.
  - Una vencida ofrece reenviar y no ofrece reabrir; una revocada ofrece reabrir y no ofrece reenviar; una aceptada no ofrece ninguna de las tres.
  - Las etiquetas están traducidas en los dos idiomas soportados por el producto y no muestran códigos internos de estado.
  - La etiqueta accesible de cada control identifica la invitación a la que pertenece con **un dato concreto y no sensible** —el rol invitado y la fecha de vencimiento, por ejemplo—, sin repetir el correo completo en atributos técnicos.
  - Las etiquetas se resuelven al dibujar desde el catálogo del idioma activo y la página no contiene ningún literal fijo en uno de los dos idiomas; que el cambio de idioma se refleje en pantalla pertenece al comportamiento en navegador y se verifica en la prueba de extremo a extremo de la spec 010 (Q8).

- **RF-006.** CUANDO el administrador solicite reabrir una invitación revocada, EL SISTEMA pedirá confirmación explícita antes de ejecutar la operación, y MIENTRAS la operación está en curso no permitirá enviarla dos veces.
  *Criterios de aceptación:*
  - La confirmación indica que el enlace anterior dejará de funcionar y que se enviará un correo nuevo.
  - Cancelar la confirmación no produce ninguna petición ni cambio de estado.
  - Dos activaciones seguidas del mismo control generan como máximo una petición y un solo correo.
  - Mientras hay una operación de invitaciones en curso, los controles que podrían duplicarla están deshabilitados.

- **RF-007.** CUANDO una operación de reapertura o de reenvío termine con éxito, EL SISTEMA mostrará en la lista el estado real, la nueva fecha de vencimiento y el enlace nuevo listo para copiar; SI la operación responde **409**, ENTONCES mostrará, en el idioma activo, cuál es el motivo y **qué acción debe usar** el administrador, sin presentar la invitación como modificada.
  *Criterios de aceptación:*
  - Tras el éxito, la fila muestra estado pendiente y la fecha nueva, sin recargar manualmente la página.
  - El enlace mostrado es el del **último enlace emitido por el servidor** para esa invitación y es el único que permite aceptar; un enlace mostrado antes deja de ofrecerse como válido. La interfaz no depende del orden de llegada de las respuestas: mientras hay una operación de invitaciones en curso, los controles están deshabilitados (RF-006), así que la pantalla no emite dos operaciones simultáneas sobre la misma invitación.
  - Ante un 409 por invitación aceptada, por otra pendiente vigente o por reenviar una revocada, la fila conserva su estado real y el mensaje, en el idioma activo, dice qué acción usar; en el caso de la revocada, indica que debe **reabrirse**.
  - El mensaje de un 409 se muestra en el idioma activo; cómo se consigue (código estable interpretado por el cliente o texto localizado en el servidor) se decide en el plan. En ningún caso el usuario ve un código interno ni un texto sin traducir.
  - SI el correo no se pudo enviar y la operación responde con error de envío después de haber dejado la invitación pendiente, ENTONCES la lista refleja el estado real (pendiente) y permite reintentar el envío, sin presentar el fallo como si no hubiera cambiado nada.
  - El mensaje de error no incluye el token ni el enlace.

### Salud del worker

- **RF-008.** MIENTRAS el bucle del worker no complete una vuelta en **90 s**, EL SISTEMA declarará al worker **no sano**, aunque su proceso siga vivo y su contenedor esté en ejecución, y con independencia de que haya o no eventos que procesar.
  *Criterios de aceptación:*
  - Con el bucle bloqueado y el proceso vivo, la verificación de salud pasa de sana a no sana sin intervención manual y sin reiniciar el contenedor.
  - La transición ocurre dentro del umbral de 90 s más un margen acotado por los reintentos de la comprobación.
  - La salud no depende de que haya eventos que procesar: un worker sin eventos sigue publicando su señal y permanece sano.
  - El umbral efectivo es **90 s** —el que ya aplica el healthcheck actual— y la señal se publica cada **10 s**. Existe **una sola constante** de antigüedad máxima en el código (90 s) y la comprobación de salud la usa en lugar de repetir el número; la cadencia de publicación también es una sola constante. El `interval` de la comprobación en la configuración de servicios puede seguir siendo de 10 s y no se exige que desaparezca.

- **RF-009.** CUANDO el bucle vuelva a avanzar, EL SISTEMA declarará al worker sano de nuevo, en el siguiente ciclo de comprobación y sin reiniciar el proceso ni el contenedor.
  *Criterios de aceptación:*
  - Tras desbloquear el bucle, la salud vuelve a sana dentro del umbral y del intervalo de comprobación.
  - No queda ningún estado persistido que exija limpieza manual.
  - El worker procesa eventos con normalidad después de la recuperación.

- **RF-010.** MIENTRAS una dependencia (base de datos o Redis) esté caída pero el bucle siga completando vueltas y reintentando, EL SISTEMA mantendrá al worker **sano**; el worker solo pasa a no sano cuando deja de completar vueltas.
  *Criterios de aceptación:*
  - Con la base de datos detenida y el bucle girando, el worker sigue sano, como exige el contrato de la spec 008.
  - Con Redis detenido y el bucle girando, el worker sigue sano.
  - El criterio no introduce un umbral de fallos consecutivos: un bucle que gira y falla no se considera detenido.
  - La documentación de salud describe esta distinción con las mismas palabras que la comprobación.

- **RF-011.** EL SISTEMA dispondrá de una verificación reproducible de la transición real —**congelar el bucle de un worker vivo en el contenedor** y observar el paso a no sano y la vuelta a sano— y, cuando no pueda ejecutarse, la declarará **no ejecutada**.
  *Criterios de aceptación:*
  - La verificación congela el bucle de un worker en ejecución (no lo mata) y comprueba la salud reportada por el orquestador.
  - Comprueba también la recuperación tras reanudar el bucle.
  - La verificación es reproducible con un comando documentado y no forma parte de la suite que corre sin contenedores.
  - Si el entorno no dispone de contenedores (por ejemplo, no hay Docker), la verificación **no se ejecuta** y la validación la declara explícitamente como **no ejecutada**; no se sustituye por una prueba simulada ni se presenta como realizada.

## Requisitos no funcionales

- **RNF-001. Sin pila de pruebas nueva y con un método de verificación de interfaz acotado.** Esta entrega no introduce navegador, servidor de pruebas, arnés de componentes ni dependencias de prueba nuevas; la verificación de la transición de salud es un comando de operación reproducible, no una suite, y la prueba de navegador pertenece a la spec 010.
  - **Método efectivo (Q8):** los requisitos de interfaz (RF-005, RF-006 y RF-007) se verifican con lo que el frontend ya ejecuta hoy —`cd frontend && pnpm test`, que corre `node --test --experimental-strip-types` solo sobre funciones puras importables— más `cd frontend && pnpm run typecheck`. **No** se añaden `@vue/test-utils`, `happy-dom` ni ningún arnés de componentes.
  - **Qué se verifica como función pura:** la **selección de acción por estado** (reenviar en vencidas, reabrir en revocadas, ninguna en aceptadas), el **estado de la operación** que decide si los controles están deshabilitados y el **mensaje del 409** a partir de un motivo estable traducido al idioma activo.
  - **Qué se verifica como aserción de fuente** (inspección del texto de la página y del catálogo de traducciones, como ya hace la suite actual): que la pantalla usa esas funciones para decidir la acción y el deshabilitado, que pide confirmación antes de reabrir y que las etiquetas nuevas existen en los dos idiomas.
  - **Qué queda fuera de este método y no se declara verificado aquí:** el comportamiento real en navegador —diálogo de confirmación, doble pulsación, refresco de la fila y copia del enlace—. Lo cubre la prueba de extremo a extremo prevista en la spec 010 (Q8).
- **RNF-002. Sin migraciones ni cambios de esquema.** La reapertura reutiliza el registro existente y los estados permitidos ya existen; no se añaden columnas, tablas, índices ni permisos.
- **RNF-003. Aislamiento y autorización sin cambios.** La reapertura no crea permisos nuevos: usa el permiso de gestión de miembros existente; ninguna consulta nueva elude el contexto de organización.
- **RNF-004. Compatibilidad de contrato.** Se respetan los contratos cerrados por la spec 008: la lectura y la previsualización siguen sin escribir y calculan el vencimiento sin reescribir la fila (200, sin cambios de estado almacenado); crear sobre una vencida responde 201 materializando la anterior; revocar una vencida responde 409 sin reescribirla; reenviar una vencida responde 200 y reutiliza el registro con token y fecha nuevos; la unicidad de pendientes por organización y correo se mantiene; reenviar con **otra** pendiente vigente responde 409; aceptar una vencida responde 410; la aceptación no devuelve token en el cuerpo y **conserva su entrada de auditoría**. Los contratos de la spec 008 que cambian son exactamente **dos**, y ningún otro: **(C-1)** reenviar una invitación revocada pasa de éxito a **409** (RF-003); **(C-2)** la reapertura se convierte en una **tercera ruta de materialización del vencimiento**, junto a crear y reenviar, cuando el mismo correo tiene otra pendiente ya vencida (RF-001, Q6). Además aparece una acción nueva —la reapertura— con sus propios 409 (RF-001, RF-002), que no altera ningún contrato existente. Los dos cambios se reflejan en `README.md` y en `AGENTS.md` al implementar la spec, en el mismo cambio que el código.
- **RNF-005. Trazabilidad documental.** Todo cambio de comportamiento observable se refleja en la documentación de producto y de operación en el mismo cambio, incluida la semántica de salud y el ciclo de vida de la invitación revocada.
- **RNF-006. Sin secretos ni datos reales en pruebas.** Las pruebas usan datos ficticios de desarrollo y no registran tokens ni enlaces en la salida.
- **RNF-007. Valores únicos para el umbral de salud.** El umbral de antigüedad máxima (90 s) existe **una sola vez** en el código y lo usa la comprobación de salud del worker; la cadencia de publicación de la señal (10 s) también es una sola constante. Los documentos de operación citan los mismos valores. No se exige retirar el `interval` de 10 s de la comprobación en la configuración de servicios.

## Datos personales y privacidad

- **Datos involucrados:** correo electrónico del destinatario de la invitación (dato personal), nombre y correo del miembro que ejecuta la acción, y el token del enlace, que es un secreto y no un dato personal pero habilita el acceso.
- **Quién los ve:** solo los miembros con permiso de gestión de miembros de la organización, y la propia persona invitada a través de su enlace. Ninguna otra organización accede a ellos.
- **Qué no se expone:** ni el token ni el correo se incluyen en la auditoría, en mensajes de error, en registros ni en ninguna proyección pública. La auditoría guarda la acción, el identificador de la invitación y el miembro que la ejecuta.
- **Enlaces:** el enlace solo se muestra al administrador que ejecuta la acción y se envía al destinatario; no se registra en la traza. Un enlace revocado o sustituido no vuelve a ser válido.
- **Pruebas:** usan cuentas y correos ficticios de desarrollo; no tocan datos reales.

## Casos límite

1. **Reabrir una revocada que ya tiene otra pendiente vigente del mismo correo:** 409, sin escribir y sin enviar correo; la pendiente existente no cambia y no se materializa nada.
2. **Reabrir una revocada cuyo mismo correo tiene otra pendiente almacenada ya vencida (Q6):** la pendiente vencida se materializa como vencida y después se reabre la revocada, en la misma transacción; al final queda una sola pendiente (la reabierta) y un solo enlace válido. Si la reapertura falla después de materializar, la transacción revierte y la otra invitación sigue como estaba almacenada.
3. **Reabrir una revocada que fue reemplazada por una invitación nueva:** si la nueva sigue vigente, 409; si la nueva ya está aceptada o vencida, la reapertura procede con token y fecha nuevos (y materializa la nueva si estaba vencida y almacenada como pendiente).
4. **Reabrir una aceptada:** 409 y registro intacto.
5. **Reabrir una pendiente vigente o una vencida:** 409 en ambos casos, sin renovar token ni fecha; la vencida se atiende reenviando.
6. **Reabrir la misma revocada dos veces:** la segunda operación encuentra la invitación ya pendiente y responde 409; no hay dos pendientes ni dos enlaces válidos.
7. **Reenviar una revocada:** 409, la fila sigue revocada, no se envía correo y el mensaje indica que debe reabrirse.
8. **Enlace anterior a la reapertura:** no previsualiza ni acepta la invitación; se comporta como un enlace inexistente, nunca como uno válido ni como una aceptación.
9. **Enlace anterior a un reenvío de una vencida:** mismo criterio que el caso 8.
10. **Reapertura y reenvío simultáneos de la misma invitación desde dos pantallas:** la unicidad de pendientes se mantiene; al final hay exactamente una pendiente y un único enlace válido, el **último emitido por el servidor**. Desde una misma pantalla la carrera no se produce porque los controles se deshabilitan mientras hay una operación de invitaciones en curso (RF-006); desde pantallas distintas, cada una muestra el enlace de su propia respuesta y deja de ofrecer como válido cualquier enlace anterior que hubiera mostrado (RF-007).
11. **Fallo de envío de correo después de escribir:** la invitación queda pendiente con el token nuevo aunque la respuesta sea de error; la interfaz refleja el estado real y permite reintentar el envío.
12. **Destinatario que ya es miembro:** la reapertura procede (la invitación es válida como registro), pero aceptar responde el conflicto de pertenencia existente. La interfaz no promete que la aceptación vaya a funcionar.
13. **Invitación de otra organización:** **404**, sin revelar que existe; no se lee ni se escribe la invitación, no se emite enlace y no se escribe auditoría.
14. **Miembro sin permiso de gestión de miembros:** **403**, resuelto antes de leer o escribir la invitación; la respuesta es la misma exista o no la invitación —no revela su existencia—, no se emite enlace, no se envía correo y no se escribe auditoría.
15. **Organización inactiva (o usuario de plataforma inactivo):** la verificación de la sesión de organización falla antes de llegar a la operación y la respuesta es **403 «Membresía no válida»**, el mismo rechazo que recibe hoy cualquier operación del Workspace; no se lee ni se escribe la invitación, no se emite enlace, no se envía correo y no se escribe auditoría.
16. **Worker bloqueado antes de la primera vuelta:** la comprobación lo declara no sano una vez pasado el periodo de gracia; no se confunde con un arranque lento.
17. **Worker sin eventos durante horas:** sigue publicando su señal y permanece sano.
18. **Worker con dependencia caída mucho tiempo:** sigue sano mientras complete vueltas (contrato de la spec 008).
19. **Reloj desplazado:** un latido con marca de tiempo **posterior** al instante con el que mide la comprobación se considera fresco, porque la antigüedad negativa se trata como fresca; un desfase que adelanta la marca del latido no produce un falso negativo. La garantía no es simétrica y no se promete como tal: si el reloj que mide se atrasa respecto al que escribe la marca, la antigüedad calculada crece y el worker puede declararse no sano antes de tiempo; el umbral de 90 s frente a una cadencia de 10 s absorbe los desfases pequeños, y el criterio se documenta junto al umbral.
20. **Doble pulsación de los controles de invitación:** una sola petición y un solo correo.

## Fuera de alcance

- **Prueba de extremo a extremo en navegador del reintento del tiempo real:** se entrega en la spec 010 (`specs/010-e2e-reintento-tiempo-real/`), con su propia pila, su propio job de integración continua y sus propios criterios. Esta entrega no introduce navegador ni arnés de componentes: la interfaz de invitaciones se verifica con funciones puras bajo el runner actual y con aserciones de fuente, y su comportamiento real en navegador queda fuera de esta entrega y se remite a la prueba de extremo a extremo de la spec 010 (Q8, RNF-001).
- Pruebas de navegador de cualquier otro flujo (operación de partido, planilla, clasificaciones).
- Cambiar quién puede gestionar miembros (roles y permisos) o introducir un rol nuevo.
- Deshacer una aceptación, editar el correo o el rol de una invitación existente, o borrar invitaciones.
- Añadir una pantalla o una ruta de consulta de la auditoría organizacional.
- Ampliar la auditoría a crear, reenviar o revocar invitaciones; la aceptación conserva la entrada que ya tiene (`ACCEPT_INVITATION`) y la reapertura aporta la única entrada nueva.
- Recuperar el token en el cuerpo de la aceptación de invitación o cualquier cambio del contrato de sesión.
- Filtrado por rol de los eventos de tiempo real (riesgo aceptado de la spec 008).
- Cambiar el umbral de salud a un valor que contradiga el contrato de la spec 008 sin enmendarlo.
- Añadir métricas, alertas o integración con un sistema de monitorización externo.

## Criterios de finalización

1. La reapertura de una invitación revocada deja la fila pendiente con token y fecha nuevos, sin crear otra fila, responde 200 con la invitación y el enlace nuevo, y el enlace anterior deja de resolver (RF-001).
2. Reabrir una pendiente, una vencida o una aceptada, y reabrir con otra pendiente **vigente**, responden 409 sin escribir ni enviar correo; con otra pendiente **vencida** la reapertura procede materializándola primero, en la misma transacción (RF-001, RF-002).
3. Reenviar una revocada responde 409 sin escribir, sin enviar correo y con un motivo distinguible que remite a reabrir; reenviar una vencida sigue renovando la fila (RF-003).
4. La reapertura con éxito deja exactamente una entrada de auditoría sin correo ni token; crear, reenviar y revocar no añaden entradas, la aceptación conserva la suya y los intentos fallidos no dejan ninguna (RF-004).
5. La lista de invitaciones ofrece «Reenviar» en vencidas y «Reabrir» en revocadas, traducido, sin acciones sobre aceptadas ni reapertura sobre no revocadas (RF-005).
6. La reapertura pide confirmación, no duplica peticiones ni correos y se deshabilita mientras está en curso (RF-006).
7. Tras reabrir o reenviar, la lista muestra el estado real, la fecha nueva y el **último** enlace emitido; un 409 se explica en el idioma activo indicando qué acción usar, sin falsear el estado; un fallo de envío posterior a la escritura no oculta el estado real (RF-007).
8. Un worker vivo con el bucle bloqueado más de 90 s pasa a no sano y vuelve a sano al reanudarse, sin reiniciar; los 90 s de antigüedad máxima y los 10 s de cadencia son valores únicos en el código, usados por la comprobación de salud y por el worker respectivamente (RF-008, RF-009).
9. El worker sigue sano con dependencias caídas mientras complete vueltas, y la documentación lo dice con las mismas palabras que la comprobación (RF-010).
10. La transición real está verificada congelando el bucle de un worker vivo en el contenedor con un comando reproducible, o declarada explícitamente como **no ejecutada** si el entorno no dispone de contenedores (RF-011).
11. Se respetan los contratos de invitación enumerados en RNF-004 y se comprueban con pruebas los **dos** cambios de contrato declarados: **(C-1)** reenviar una revocada responde 409 y **(C-2)** la reapertura materializa previamente la otra pendiente vencida del mismo correo.
12. Los requisitos de interfaz (RF-005, RF-006, RF-007) están verificados con `cd frontend && pnpm test` —funciones puras de selección de acción por estado, de estado de la operación y de mensaje del 409, más aserciones de fuente sobre el cableado y las etiquetas— y con `cd frontend && pnpm run typecheck`; no se introduce navegador ni arnés de componentes, y el comportamiento real en navegador se declara **no verificado en esta entrega** y remitido a la prueba de extremo a extremo de la spec 010 (Q8).
13. Pasan las verificaciones del proyecto que apliquen al cambio y, si alguna no se ejecutó, se declara como no ejecutada.
14. La documentación afectada (producto, operación y agentes) refleja el ciclo de vida de la invitación revocada —incluida la nueva ruta de materialización— y la semántica de salud del worker.

## Decisiones de clarificación (2026-10-21)

- **Q1 — Hueco real de la acción visible.** La lista ya ofrece reenviar en vencidas y revocadas: no es un defecto de visibilidad. Lo que falta es **semántica**: confirmación, feedback del estado real y traducción, separando «Reenviar» (vencida) de «Reabrir» (revocada). Se refleja en RF-005, RF-006 y RF-007.
- **Q2 — Reapertura.** Acción explícita sobre la revocada: misma fila, **token y fecha nuevos** (el enlace revocado nunca revive), permiso de gestión de miembros, confirmación y auditoría. Reabrir una pendiente responde **409** sin renovarla; reabrir una aceptada responde **409**. Reenviar una revocada pasa a **409** con indicación de reabrir. Se refleja en RF-001, RF-002, RF-003 y RF-006.
- **Q3 — Auditoría.** La reapertura deja entrada en la auditoría administrativa: acción, invitación y miembro; **sin correo ni token**. Es la **única entrada nueva**: crear, reenviar y revocar no añaden ninguna y la aceptación **conserva** la suya (`ACCEPT_INVITATION`, migración 014). Se refleja en RF-004.
- **Q4 — Prueba de navegador.** Va a la **spec 010** con **Playwright** y **job propio de integración continua** sobre contenedores. Esta spec entrega solo invitaciones y salud del worker.
- **Q5 — Bucle detenido.** No completa una vuelta en **90 s**, haya o no eventos; un fallo de dependencia con el bucle girando **no** cuenta como detenido y respeta el contrato de la spec 008. La transición real se verifica **congelando el bucle de un worker vivo** en el contenedor y observando no sano → sano. Se refleja en RF-008, RF-010 y RF-011.
- **Q6 — Reabrir con otra pendiente vencida del mismo correo.** Cuando la revocada convive con **otra** invitación del mismo correo almacenada como pendiente pero ya vencida, esa pendiente **se materializa como vencida en la misma transacción** y después se reabre la revocada. Es una **tercera ruta de materialización** del vencimiento, además de crear y reenviar: se declara como cambio de contrato en RNF-004 y obliga a actualizar `README.md` y `AGENTS.md` al implementar. Una pendiente **vigente** sigue bloqueando con 409 y **no** se materializa. Se refleja en RF-001, RF-002, la definición de materialización, RNF-004 y los casos límite 1–3.
- **Q7 — Umbral de salud.** El umbral efectivo es **90 s**, el que ya aplica el healthcheck actual. La frase «publica al menos cada 30 s» de la spec 008 describía de forma imprecisa la cadencia real de **10 s**, **no** un umbral independiente: se retira y se corrige la redacción del RF-014 de la 008 como aclaración sin cambio de comportamiento (nota del 2026-10-21). Se refleja en RF-008, la definición de bucle detenido y RNF-007.
- **Q8 — Método de verificación de la interfaz.** Sin dependencias nuevas: **funciones puras probadas con el runner actual (`node --test --experimental-strip-types`)** para la selección de acción por estado, el estado de la operación y el mensaje del 409, más **aserciones de fuente** para el cableado y las etiquetas. **No** se añaden `@vue/test-utils`, `happy-dom` ni arnés de componentes. El comportamiento real en navegador queda fuera de esa verificación y lo cubrirá la prueba de extremo a extremo de la **spec 010**. Se refleja en RNF-001, en «Fuera de alcance», en el criterio de RF-005 sobre el idioma y en el criterio de finalización 12.

## Dudas abiertas

Ninguna. Las ocho dudas de la clarificación (Q1–Q8) quedaron resueltas el 2026-10-21 y están incorporadas en los requisitos, definiciones y casos límite de esta spec.
