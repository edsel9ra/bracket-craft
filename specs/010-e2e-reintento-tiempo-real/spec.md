# Spec 010 — Prueba de extremo a extremo del reintento del tiempo real

Estado: borrador

## Contexto y objetivo

La spec 008 corrigió el reintento manual del tiempo real: cuando la conexión entra en error, el usuario ve «Reintentar» y al pulsarlo debe abrirse una conexión nueva sin acumular conexiones ni duplicar suscripciones. Esa corrección se verificó solo con pruebas de la función pura que decide si hay que derribar la conexión actual. No existe ninguna prueba que demuestre, en un navegador real contra un servidor real, que pulsar «Reintentar» devuelve la conexión y que la interfaz no miente sobre su estado.

La spec 009 separó expresamente esta pieza para no mezclar la verificación del tiempo real con el ciclo de vida de las invitaciones y la salud del worker. Este documento fija su contrato completo.

**Objetivo:** demostrar de extremo a extremo, en un navegador real y en las tres vistas donde existe el control, que el reintento reconecta de verdad, que el estado visible pasa de error a conectado y que no se duplican suscripciones ni se recarga la vista; y hacerlo de forma reproducible en la integración continua con un job propio.

**Decisión ya tomada:** la prueba se implementa con **Playwright**, en **navegador headless**, en un **job propio de integración continua** que arranca la pila de contenedores del proyecto. No se reabre la elección de herramienta ni el lugar donde vive la prueba.

### Estado verificado (2026-10-21)

1. La decisión de reintento está cubierta por pruebas unitarias de una función pura; no hay ninguna prueba de navegador.
2. El control «Reintentar» solo se muestra cuando el estado de conexión es error, y existe en tres vistas: la página pública del torneo, el panel del Workspace y la operación del partido.
3. No hay infraestructura de pruebas de navegador en el repositorio ni ningún job de integración continua que levante la pila completa. Los jobs actuales son `backend`, `frontend`, `infrastructure` y `security`.
4. Feedback del consumidor y recarga de datos dependen de la conexión; el transporte de tiempo real es de mejor esfuerzo y el cliente deduplica entregas.

## Usuarios

- **Visitante o lector de la página pública del torneo:** usa el tiempo real y necesita que el reintento le devuelva los resultados en vivo.
- **Miembro de organización en el Workspace:** trabaja con datos que se actualizan en vivo y no quiere que el reintento le recargue la vista ni le duplique actualizaciones.
- **Operador de partido:** opera un partido en curso; un reintento que no reconecta lo deja viendo datos congelados sin saberlo.
- **Revisor o responsable de calidad:** necesita una prueba automática que detecte una regresión del reintento antes de que llegue a producción.
- **Operador de integración continua:** necesita que la prueba sea determinista, acotada en tiempo y con artefactos suficientes cuando falla.

## Roles y visibilidad

- **Público:** sin cambios. La prueba no introduce rutas, datos ni contenido público nuevo; usa la página pública tal como está.
- **Miembro de organización:** sin cambios. La prueba usa una cuenta ficticia de desarrollo con permiso para el Workspace y para la operación del partido.
- **Administrador de organización:** sin cambios; no se prueban sus acciones.
- **Administrador de plataforma:** no aplica.
- **Persona invitada:** no aplica.
- **Aislamiento:** la prueba se ejecuta sobre datos ficticios de una única organización de desarrollo; no accede a datos de otras organizaciones, no usa datos personales reales y no se ejecuta contra producción.

## Historias de usuario

- **HU-1.** Como visitante, quiero que «Reintentar» me devuelva los resultados en vivo, para no quedarme mirando un aviso que dice que lo intentó.
- **HU-2.** Como miembro del Workspace u operador de partido, quiero que el reintento no me recargue la vista ni me duplique las actualizaciones, para no perder el contexto de lo que estaba haciendo.
- **HU-3.** Como responsable de calidad, quiero una prueba automática en navegador que falle cuando el reintento deje de reconectar, para detectarlo antes de desplegar.
- **HU-4.** Como operador de integración continua, quiero que la prueba falle por una aserción concreta y deje artefactos, para no confundir un comportamiento roto con una espera agotada.

## Definiciones

- **Escenario:** la secuencia que lleva una vista al estado de error del tiempo real, pulsa «Reintentar», restablece el servicio y observa el estado visible y las recargas.
- **Estado visible:** lo que el usuario percibe de la conexión (error, conectando/reconectando, conectado); es lo que la prueba observa, no el estado interno del transporte.
- **Conexión nueva:** una conexión que sustituye a la anterior porque esta no se puede reutilizar; no es una reutilización ni un reintento automático del transporte.
- **Suscripción duplicada:** dos registros activos del mismo consumidor para el mismo evento, que producen dos recargas o dos actualizaciones por una sola entrega.
- **Recarga de vista:** recarga de datos de un consumidor tras reconectar. No es una recarga del documento.
- **Recarga del documento:** navegación completa de la página; el reintento nunca debe provocarla.
- **Corrida completa:** arranque de la pila, preparación de datos y ejecución del escenario en las tres vistas.
- **Fallo de comportamiento:** la aplicación no reconecta, no cambia el estado visible, duplica suscripciones o recarga la vista.
- **Fallo de infraestructura:** la pila no arranca, un puerto está ocupado o el navegador no está disponible; se distingue del anterior por el mensaje y los artefactos.
- **En verde:** ver RF-004.

## Requisitos funcionales

- **RF-001.** CUANDO se ejecute el escenario en un navegador real contra la aplicación real, EL SISTEMA demostrará que, partiendo del **estado de error** del tiempo real, pulsar «Reintentar» inicia una **conexión nueva** y que el estado visible pasa por conectando hasta **conectado** cuando el servicio vuelve a estar disponible.
  *Criterios de aceptación:*
  - El estado de error se provoca por indisponibilidad real del canal de tiempo real, no simulando la interfaz ni forzando el estado interno del cliente.
  - La prueba observa un intento de conexión nuevo después de pulsar el control, no la reutilización de la conexión caída.
  - El estado visible nunca muestra conectado mientras el servicio sigue indisponible.
  - Al restablecerse el servicio, el estado visible llega a conectado dentro del tiempo máximo declarado.
  - El control «Reintentar» solo está presente en el estado de error y desaparece al reconectar.

- **RF-002.** CUANDO la conexión se restablezca tras el reintento, EL SISTEMA demostrará que cada consumidor recarga sus datos **exactamente una vez**, que no quedan suscripciones duplicadas, que no hay más de una conexión activa y que **no se recarga el documento**.
  *Criterios de aceptación:*
  - Se observa exactamente una recarga por consumidor tras la reconexión; una segunda recarga es un fallo.
  - Pulsar «Reintentar» varias veces seguidas no deja más de una conexión activa ni duplica suscripciones ni recargas.
  - El estado propio de la vista sobrevive al reintento: la prueba comprueba que el documento no se ha recargado.
  - Se distingue una recarga duplicada por suscripción de una entrega duplicada del transporte de mejor esfuerzo: solo la primera es un fallo de esta prueba.
  - Con el servicio todavía caído, el estado vuelve a error y el control sigue disponible, sin éxito falso.

- **RF-003.** EL SISTEMA ejecutará el escenario en las **tres vistas donde existe el control** —página pública del torneo, panel del Workspace y operación del partido— dentro de la misma corrida.
  *Criterios de aceptación:*
  - Las tres vistas se ejecutan y cada una informa su propio resultado.
  - Si una vista deja de ofrecer el control, la prueba falla; no se omite en silencio ni se marca como no aplicable.
  - El fallo de una vista no oculta el resultado de las otras dos.
  - La preparación de datos es la misma para las tres y no depende del orden entre ellas.

- **RF-004.** EL SISTEMA ejecutará el escenario en un **job propio de integración continua**, con navegador headless, sobre la pila de contenedores del proyecto y con datos ficticios de desarrollo; el job se considerará **en verde** solo si la corrida completa pasa las tres vistas sin omisiones y sin reintentos que oculten intermitencia, dentro de la duración máxima declarada.
  *Criterios de aceptación:*
  - El job es propio y su resultado forma parte del veredicto del cambio; no sustituye ni duplica los jobs existentes.
  - La pila se arranca desde cero en el mismo job y no depende de servicios ya levantados ni de un servidor de correo real.
  - La duración máxima de la corrida completa es de **15 minutos** y la de una vista individual de **4 minutos**; superarlas es un fallo declarado como tal.
  - Un fallo de infraestructura se informa como tal y se distingue de un fallo de comportamiento.
  - No se reintenta el escenario para ponerlo en verde: un fallo intermitente se investiga y se corrige.
  - Las dependencias que introduzca son solo de desarrollo: no entran en la imagen de producción y las auditorías de dependencias y el escaneo del sistema de archivos siguen pasando sin exclusiones.

- **RF-005.** SI el escenario falla, ENTONCES EL SISTEMA fallará por la **aserción incumplida** —identificando la vista y la condición— y publicará artefactos de diagnóstico suficientes para reconstruir lo ocurrido.
  *Criterios de aceptación:*
  - El fallo no se produce por un tiempo de espera agotado sin diagnóstico; si se agota un tiempo máximo, el mensaje identifica la condición que no se cumplió.
  - En fallo se publican captura de pantalla, traza del navegador y registro del navegador y del servidor, retenidos por el servicio de integración continua.
  - En éxito se publica un resumen legible con el resultado de las tres vistas y la duración.
  - Los artefactos no contienen tokens, cookies de sesión ni datos personales reales.

- **RF-006.** EL SISTEMA dispondrá de un **comando reproducible en local** que ejecuta el escenario sobre el entorno de contenedores con el mismo resultado que la integración continua, y su resultado se declarará en la validación del cambio.
  *Criterios de aceptación:*
  - El comando está documentado y arranca y detiene lo que necesita, sin pasos manuales no documentados.
  - Reproduce las tres vistas y produce los mismos artefactos en fallo.
  - No depende de secretos reales: usa los valores de desarrollo documentados.
  - Si no se puede ejecutar en un entorno concreto, se declara como no ejecutada; no se presenta como realizada.

## Requisitos no funcionales

- **RNF-001. Determinismo.** La prueba espera condiciones observables con tiempos máximos acotados y no usa esperas fijas arbitrarias ni depende de la velocidad de la máquina; un fallo señala la aserción incumplida.
- **RNF-002. Coste acotado y aislado.** El escenario tiene una duración máxima declarada, vive en su propio job y no convierte la suite actual en una suite de navegador.
- **RNF-003. Sin superficie de producción.** Ninguna dependencia de pruebas entra en las imágenes de producción; los lockfiles quedan actualizados y las auditorías y el escaneo de archivos pasan sin exclusiones ni listas de supresión.
- **RNF-004. Sin cambios de comportamiento del producto.** La prueba no altera la aplicación, la interfaz ni el contrato del tiempo real; si para poder probarla hiciera falta un cambio observable, se propone primero como cambio de requisitos y no se implementa de paso.
- **RNF-005. Localizadores estables.** La prueba se apoya en lo que el usuario ve —texto y nombre accesible del control— y no en detalles internos de maquetación; se ejecuta con la interfaz fijada en un idioma para que el texto del control no dependa del entorno del runner.
- **RNF-006. Sin secretos ni datos reales.** La prueba usa la organización y las cuentas ficticias de desarrollo, no usa datos personales reales y no registra tokens, enlaces ni cookies en la salida.
- **RNF-007. Honestidad del veredicto.** La prueba no se declara verde si se omitió una vista, si se saltó por falta de infraestructura o si se reintentó hasta pasar.

## Datos personales y privacidad

- **Datos involucrados:** los de las cuentas ficticias de desarrollo (correo y nombre inventados). No se usan datos de jugadores, documentos, fechas de nacimiento ni invitaciones reales.
- **Quién los ve:** quien ejecuta la prueba en local y quien consulta los artefactos del job de integración continua.
- **Qué no se expone:** la prueba no accede a proyecciones con datos personales, no captura credenciales reales y los artefactos no contienen tokens ni cookies de sesión.
- **Aislamiento:** la pila de la prueba es desechable y de una sola organización ficticia; no se conecta a bases de datos ni a entornos de producción.

## Casos límite

1. **Servicio de tiempo real caído desde el inicio de la vista:** la prueba debe poder llegar al estado de error con un procedimiento declarado y no depender de que la conexión inicial falle por casualidad.
2. **Servicio que se recupera antes de pulsar «Reintentar»:** la prueba vuelve a provocar el error o invierte el orden de forma declarada; nunca pulsa el control en estado conectado.
3. **Doble pulsación rápida del control:** una conexión activa como máximo y ninguna recarga duplicada.
4. **Reintento con el servicio todavía caído:** vuelve a error, el control sigue disponible y no se muestra éxito falso.
5. **Corte durante la reconexión:** el estado visible nunca muestra conectado sin una conexión activa.
6. **Idioma del entorno del runner distinto del de la interfaz:** la prueba fija el idioma y localiza el control por su nombre accesible en ese idioma.
7. **Sesión del Workspace caducada durante el escenario:** la prueba se reautentica de forma declarada y no confunde la redirección con un fallo del reintento.
8. **Entrega duplicada del transporte de mejor esfuerzo:** no se cuenta como suscripción duplicada; el cliente deduplica entregas.
9. **Vista que deja de mostrar el control:** la prueba falla en esa vista en lugar de omitirla.
10. **Fallo de infraestructura (contenedor que no arranca, puerto ocupado, navegador ausente):** se informa como fallo de infraestructura con su artefacto, distinto de un fallo de comportamiento.
11. **Arranque lento de la pila:** el tiempo de arranque está acotado y se informa por separado; no se cuenta como fallo del reintento.
12. **Navegador headless sin aceleración gráfica:** el escenario no depende de animaciones ni de tiempos de pintado.

## Fuera de alcance

- **Sustituir las pruebas unitarias existentes** de la función pura que decide el reintento: siguen siendo la verificación de la decisión y esta prueba cubre el comportamiento observable en el navegador.
- Pruebas de navegador de otros flujos: planilla, clasificaciones, invitaciones, gestión de miembros o la operación completa del partido.
- Navegadores móviles reales, dispositivos físicos, emulación de red móvil y matrices amplias de navegadores más allá de lo que resuelva la duda abierta.
- Medir rendimiento, latencia, throughput o capacidad del tiempo real (el RNF-003 de la spec 005 sigue sin medirse).
- Filtrado por rol de los eventos de tiempo real (riesgo aceptado de la spec 008).
- Regresión visual, auditoría de accesibilidad o comparación de capturas.
- Cambiar el comportamiento del reintento, la interfaz del control o el transporte de tiempo real.
- Ejecutarse contra entornos de producción o con datos reales.

## Criterios de finalización

1. El escenario demuestra en navegador real que, desde el estado de error, «Reintentar» abre una conexión nueva y el estado visible llega a conectado cuando el servicio vuelve (RF-001).
2. Tras reconectar hay exactamente una recarga por consumidor, no quedan suscripciones duplicadas ni más de una conexión, y el documento no se recarga; una doble pulsación no duplica nada; con el servicio caído no hay éxito falso (RF-002).
3. Las tres vistas —pública, Workspace y operación del partido— ejecutan el escenario y fallan por separado si dejan de ofrecer el control (RF-003).
4. Existe un job propio de integración continua con Playwright headless sobre la pila de contenedores, con la definición de «en verde» y las duraciones máximas declaradas (RF-004).
5. Un fallo produce la aserción incumplida y artefactos de diagnóstico sin secretos, y no se pone en verde reintentando (RF-005).
6. Existe un comando local documentado que reproduce la prueba, y su resultado se declara en la validación (RF-006).
7. Las dependencias son solo de desarrollo, los lockfiles están actualizados y las auditorías y el escaneo pasan sin exclusiones (RNF-003).
8. La documentación afectada (producto, operación y agentes) describe cómo se ejecuta la prueba y qué significa que falle.

## Dudas abiertas

- **[NECESITA ACLARACIÓN] Q1 — ¿Con qué frecuencia se ejecuta el job?** Opciones:
  - **(a) (recomendada)** En cada `pull_request` y en cada `push` a `main`, como el resto de jobs: es la única prueba de navegador del reintento y una regresión debe bloquear la fusión. Coste: la corrida completa se suma a cada PR.
  - **(b)** Solo en `push` a `main`: más barato en PR, pero una regresión llega a `main` antes de detectarse.
  - **(c)** Solo bajo demanda y en una ejecución programada: coste mínimo, sin protección real en la fusión.
- **[NECESITA ACLARACIÓN] Q2 — ¿Qué navegadores cubre la prueba?** Opciones:
  - **(a) (recomendada)** Solo Chromium headless: el fallo que se persigue es de lógica de conexión y estado, no de maquetación; una sola implementación mantiene la corrida dentro del tiempo declarado.
  - **(b)** Chromium y WebKit: cubre el motor de Safari con dos ejecuciones y aproximadamente el doble de tiempo.
  - **(c)** Chromium, Firefox y WebKit: cobertura máxima, con el mayor coste y la mayor superficie de intermitencia.
- **[NECESITA ACLARACIÓN] Q3 — ¿Cómo se provoca la indisponibilidad del tiempo real?** La aplicación sirve la interfaz y el canal de tiempo real desde el mismo origen; la forma de cortarlo cambia la fidelidad y el alcance del escenario. Opciones:
  - **(a) (recomendada)** Bloquear desde el navegador solo el tráfico del canal de tiempo real: la indisponibilidad es real a nivel de transporte, la interfaz y sus datos por HTTP siguen funcionando, y basta desbloquear para recuperar el servicio.
  - **(b)** Detener y volver a arrancar el contenedor que sirve el tiempo real: es una caída total y real, pero también tumba las peticiones HTTP, puede expulsar la sesión del Workspace y mezcla el fallo del reintento con otros fallos.
  - **(c)** Deshabilitar el canal con una bandera de configuración: es lo más estable, pero no reproduce una caída de red y podría no ejercitar el mismo camino.
