# Spec 008 — Higiene del bloque P2 de la auditoría (R18-R32)

Estado: Implementada, validada por @reviewer y cerrada (2026-10-21).

> **Bloque P2 (higiene)** de `docs/auditoria-2026-10-19.md`, acotado por decisión del usuario a los hallazgos **R18 a R32**. El plan de acción del informe incluye además **R11** en el P2; esta spec lo deja **fuera de alcance** de forma explícita. Los hallazgos R01-R17 pertenecen a las specs 001, 003, 004, 005, 006 y 007 y no se reabren aquí.

## Contexto y objetivo

La auditoría del 2026-10-19 cerró los bloques P0 y P1 y dejó un bloque P2 de higiene: defectos pequeños y dispersos que no comprometen el aislamiento ni la integridad de resultados, pero que erosionan la confianza en el producto y en la operación. En conjunto describen cuatro patrones:

1. **Controles que aparentan funcionar y no funcionan.** Un botón de reintento que no reconecta, comprobaciones de seguridad que no alcanzan a las escrituras públicas sin sesión, lecturas que escriben y lecturas que bloquean.
2. **Trazabilidad incompleta.** Acciones sensibles sobre oficiales, planilla y publicación de formación no dejan registro, y una migración ya aplicada endureció funciones con una sustitución de texto que falla en silencio.
3. **Superficie y configuración inconsistentes.** Documentación de variables que no llega a los contenedores, credenciales y marcas heredadas, puertos de desarrollo abiertos de más, contenedores sin verificación de salud y herramientas de prueba dentro de la imagen de producción.
4. **Presentación y detalles de contrato.** Roles y estados mostrados en inglés o como código crudo, un token de sesión en el cuerpo de una respuesta, una organización activa elegida de forma arbitraria y detalles menores de formato.

**Objetivo:** cerrar R18-R32 con el menor cambio posible, dejando explícito para cada hallazgo si se **corrige**, se **documenta** o se **retira**, sin relajar ningún principio de la constitución y sin introducir funcionalidad nueva. Donde la auditoría podía resolverse de más de una forma, la decisión se registra abajo con su alternativa descartada; las decisiones de producto se cerraron el 2026-10-21 y están recogidas en «Decisiones cerradas».

### Estado verificado (2026-10-21)

Comprobado sobre el árbol de trabajo; se describe el comportamiento observado, no el diseño:

1. **R18:** el botón «Reintentar» vuelve a invocar la conexión, pero la conexión existente hace que la llamada termine sin reconectar; el usuario ve el mismo estado de error y el botón sigue visible. Ocurre en la página pública del torneo, en el Workspace y en la operación del partido.
2. **R19:** la imagen del servicio web se ejecuta con el usuario raíz; la del backend crea un usuario sin privilegios y lo usa.
3. **R20:** siete variables documentadas en el archivo de entorno de desarrollo no llegan al servicio de API en contenedores (algoritmo JWT, audiencia de Google, nombre y vigencia de la cookie CSRF, límite de cuerpo, endpoint de firma y vigencia de la firma de almacenamiento), por lo que sus valores documentados no tienen efecto; dos variables que el servicio sí recibe en contenedores (límites de intentos de login y de registro) no están documentadas.
4. **R21:** una petición de escritura sin cookie ni cabecera de autorización omite la validación de origen y de token; solo las rutas de identidad y las peticiones con credenciales la aplican.
5. **R22:** listar invitaciones actualiza en la misma petición las pendientes vencidas.
6. **R23:** la consulta de operación de un partido toma bloqueo de fila del partido, igual que las rutas de escritura, en una lectura que hace varias consultas.
7. **R24:** una migración ya aplicada reconstruyó, sustituyendo texto sobre su definición vigente, las funciones de plataforma que comparaban el rol del actor con `<>` (`platform_set_user_active`, `platform_set_organization_active`, `platform_set_membership_active`, `platform_create_membership` y `requeue_outbox_events`), y reescribió con el mismo mecanismo la vista cruda de formación (`v_public_match_lineups_unpublished`); si el texto no coincide, no hace nada y no avisa.
8. **R25:** interrumpir un segmento y cerrar el acta dejan registro de auditoría organizacional; asignar o retirar oficiales, guardar la planilla y publicar la formación no lo dejan.
9. **R26:** la creación manual de partidos en un borrador acepta un segundo enfrentamiento del mismo par en la misma fase y grupo sin aviso; el desempate directo solo puede calcularse con uno o dos enfrentamientos por par y, con más, deja de aplicarse. La fase guarda tipo y orden, pero **no** las vueltas del sorteo: el formato «ida y vuelta» no es hoy un dato consultable.
10. **R27:** la base de datos solo exige que el minuto y el minuto añadido de un evento no sean negativos; la API acota a 180 y 30, y la regla deportiva efectiva es aún menor.
11. **R28:** la imagen de producción instala las herramientas de prueba porque se declaran junto con las dependencias de ejecución.
12. **R29:** el directorio de miembros y la pantalla de invitación muestran los roles y los estados en inglés y, en el listado de invitaciones, el código crudo; la etiqueta accesible del enlace generado también está en inglés fijo.
13. **R30:** el puerto de la API en desarrollo se publica en todas las interfaces; base de datos, Redis y almacenamiento se publican solo en la interfaz local.
14. **R31:** API, web y worker no declaran verificación de salud; el servicio web depende de la API sin esperar a que esté disponible.
15. **R32 (menores):** la aceptación de invitación devuelve el token de sesión en el cuerpo además de fijar la cookie; el rol de un miembro con varios roles se elige por orden alfabético; el inicio de sesión devuelve una organización ordenada por nombre **sin desempate** y la elige como activa; la versión de la API es un literal fijo; existe una proyección de jugadores por torneo que ningún endpoint consume y que **sí calcula la edad derivada** para el rol de aplicación; el relay entrega todos los eventos de la organización a todos sus miembros sin filtrar por rol; quedan referencias a una marca de almacenamiento anterior en mensajes y valores de desarrollo; el buffer de cuerpo continúa con datos parciales cuando el cliente se desconecta; hay una etiqueta de marcado comentada en una vista.

## Decisiones de tratamiento

| Hallazgo | Tratamiento | Decisión y alternativa descartada |
|---|---|---|
| R18 | **Corregir** | El reintento debe forzar un intento de conexión nuevo. *Descartada:* dejar el botón como informativo o retirarlo, porque el estado de error seguiría sin salida manual. |
| R19 | **Corregir en producción; excepción documentada en desarrollo** | La imagen de producción se ejecuta sin privilegios. En desarrollo el servidor escribe caché en el árbol montado y el identificador del contenedor puede no coincidir con el dueño del host (Linux frente a Windows/WSL), así que el servicio de desarrollo conserva el usuario de la imagen y la excepción se documenta con su motivo y su condición de retiro. *Descartada:* exigir no-root también en desarrollo, que rompería el flujo montado en Windows/WSL. |
| R20 | **Corregir** | El archivo de entorno de desarrollo es la fuente única de documentación y todo lo que un servicio consume debe llegarle en contenedores; las dos variables que solo existían en la composición se documentan. Se define el mapa variable→servicio y las excepciones legítimas (trabajos de infraestructura, conexión administrativa, selector de migraciones, correo del primer administrador, variables de otros servicios y marca de integración continua del servicio web). *Descartada:* reducir el archivo de entorno a lo que hoy llega, que dejaría sin efecto configuraciones legítimas (CSRF, límite de cuerpo, firma). |
| R21 | **Corregir** | La validación de origen se aplica a toda escritura; el token doble se exige solo con credenciales o en rutas de identidad. «Sin origen» significa que no hay ni `Origin` ni `Referer`; si cualquiera de los dos está presente y no está permitido, se rechaza. *Descartada:* exigir token también en escrituras públicas, que rompería a clientes sin sesión y no aporta protección. |
| R22 | **Corregir** | La lectura devuelve el estado efectivo y no escribe; el vencimiento se materializa solo en **crear** (antes de insertar la nueva) y **reenviar**; **revocar** una vencida responde 409 y no reescribe el registro. Así se mantiene la unicidad de invitaciones pendientes sin bloquear para siempre al mismo correo. *Descartada:* mover el vencimiento a una tarea periódica, que añade una pieza operativa para un dato derivable. |
| R23 | **Corregir** | La consulta de operación deja de bloquear filas. *Descartada:* mantener el bloqueo «por coherencia», porque serializa lecturas con cierres sin necesidad. |
| R24 | **Documentar y verificar** | La migración aplicada no se toca (append-only). Se documenta el riesgo y se añade una comprobación automática del estado final esperado. *Descartadas:* editarla (prohibido por la constitución) y emitir una migración que repita la reescritura (no corrige el silencio y añade riesgo). |
| R25 | **Corregir** | Las tres acciones dejan registro en la auditoría organizacional, en la misma transacción. *Descartada:* registrar solo la publicación, que deja sin rastro la composición de la planilla y la asignación de oficiales. |
| R26 | **Corregir, con alcance acotado** | Solo las altas manuales se controlan, y solo en fases que producen clasificación (liga, grupos o suiza). El límite lo fija el **formato de la fase**: una vuelta (máximo uno) o dos vueltas (máximo dos), persistido al generar el calendario; no sale de la configuración de desempates. Cuentan todos los enfrentamientos existentes del par, generados o manuales, salvo los cancelados. Los calendarios generados no se validan. Las fases eliminatorias quedan fuera porque admiten repeticiones legítimas (por ejemplo, la repetición de la gran final). *Descartadas:* unicidad absoluta por par y derivar el límite de la configuración de desempates. |
| R27 | **Corregir** | Una migración nueva añade los topes estructurales de minuto y minuto añadido en base de datos. *Descartada:* confiar solo en la API, porque la base acepta hoy valores que el dominio no admite. |
| R28 | **Corregir** | Las dependencias de prueba se declaran aparte y no entran en la imagen de producción; la verificación de dependencias cubre todos los archivos declarados. *Descartada:* mantenerlas y documentarlo, porque aumenta la superficie de la imagen sin necesidad. |
| R29 | **Corregir** | Roles y estados se muestran traducidos en los dos idiomas soportados. *Descartada:* dejar los códigos crudos «para no traducir datos», porque son vocabulario del producto, no datos. |
| R30 | **Corregir, solo la API** | La API de desarrollo se publica en la interfaz local. El servicio web conserva su publicación actual porque es el punto de entrada documentado y el flujo de desarrollo en Windows/WSL depende de ella; la diferencia se documenta. |
| R31 | **Corregir** | API, web y worker declaran verificación de salud, con semánticas distintas y explícitas: la API refleja su disponibilidad (base de datos y Redis), el servicio web refleja que sirve HTTP (no la salud de la API), y el worker refleja que su bucle avanza. El servicio web espera una sola vez a que la API esté disponible al arrancar. *Descartada:* hacer que la salud de web dependa de la base de datos, que mezclaría responsabilidades y haría parpadear el servicio por fallos ajenos. |
| R32a `access_token` | **Corregir** | La sesión se entrega solo por cookie; el cuerpo no incluye credenciales. No se contempla periodo de transición con doble entrega. |
| R32b rol por `MIN` | **Corregir** | Se muestra el rol de mayor privilegio con precedencia declarada. *Descartada:* mostrar todos los roles, que cambia el contrato de la pantalla sin necesidad. |
| R32c organización al iniciar sesión | **Corregir** | Se restaura la última organización usada en ese navegador; si no hay historial válido, se elige la primera por orden estable. Nunca una organización no accesible o inactiva. |
| R32d versión fija | **Corregir** | Una sola versión del producto declarada en los metadatos del backend, expuesta por la documentación de la API. La versión del contrato de reglas y del motor es otra y no se mezcla. |
| R32e proyección sin consumidor | **Documentar** | La proyección de jugadores por torneo se mantiene como proyección interna documentada y sin consumo; no se retira ni se consume en esta spec. «Público» significa respuesta de la API: la proyección sí calcula la edad derivada para el rol de aplicación, pero ninguna respuesta pública la expone. |
| R32f relay sin filtro de rol | **Documentar como riesgo aceptado** | Se documenta el alcance de la entrega por organización y su mitigación actual (la revalidación de permisos expulsa la sesión). *Descartada:* filtrado por rol y por evento, que es un cambio de tiempo real fuera del P2. |
| R32g «MinIO» residual | **Corregir** | Mensajes de validación, comentarios de configuración y documentación nombran el almacenamiento por su proveedor real. La comprobación se limita a esos tres ámbitos y excluye valores de pruebas y entornos locales. Los valores de credenciales de desarrollo se conservan para no invalidar almacenamiento local existente y se etiquetan como solo desarrollo. |
| R32h cuerpo parcial | **Corregir** | Una petición abortada por el cliente no se procesa como completa. |
| R32i marcado comentado | **Retirar** | Se elimina el marcado comentado; no hay cambio visual. |

## Decisiones cerradas (2026-10-21)

Decisiones de producto aprobadas por el usuario. El plan no puede reabrirlas.

- **Q1 = Bloqueo solo en altas manuales, con límite por formato.** El máximo es **un enfrentamiento por pareja** en la misma fase y grupo; **dos** si la fase es de **ida y vuelta**. Los calendarios generados no cambian. El límite **no** se deriva de la configuración de desempates.
- **Q2 = Restaurar la última organización usada en ese navegador.** Si no hay historial, o el guardado ya no es accesible (organización eliminada, inactiva o sin membresía), se elige la primera por **orden estable**. Nunca se activa una organización ajena.
- **Q3 = Proyección interna documentada y sin consumo.** `public_age` / la proyección de jugadores por torneo se **mantiene** tal cual, no se retira ni se consume, con verificación de que no se expone por la API pública.
- **Q4 = Retirada del token del cuerpo.** `access_token` desaparece del cuerpo de la aceptación de invitación; **no hay periodo de transición** con doble entrega y el cambio de contrato se documenta.
- **Q5 = Solo la API pasa a la interfaz local.** El servicio web en desarrollo conserva su publicación actual y la diferencia se documenta.
- **Q6 = Ciclo de vida de la invitación vencida (opción A).** Al **crear** para un correo con una pendiente vencida, se materializa la anterior como vencida y se crea la nueva (201); **revocar** una vencida responde 409; **reenviar** la reutiliza. Se mantiene la unicidad de pendientes por organización y correo.

## Resoluciones de la revisión QA (2026-10-21)

Cierran los puntos bloqueantes y mayores del @reviewer. No reabren las decisiones cerradas.

- **B1 (R26).** El formato de una fase no está persistido hoy: la fase guarda tipo y orden, y las vueltas son un parámetro del sorteo. Para que el límite de dos sea verificable, esta spec **admite una migración aditiva** que persiste las vueltas de la fase al generar el calendario de liga (valor por defecto: una vuelta) y que las deja inmutables en versiones publicadas por los triggers existentes. La comprobación manual cuenta **todos** los enfrentamientos existentes del par, generados o manuales, salvo los cancelados. La regla se limita a fases que producen clasificación (liga, grupos o suiza); las eliminatorias quedan fuera para no bloquear repeticiones legítimas. Limitación documentada: en una liga a dos vueltas aún no generada, el límite efectivo es uno hasta que se genere el calendario.
- **B2 (R22).** La lectura no escribe; el vencimiento se materializa al **crear** y al **reenviar**, y revocar una vencida responde 409 sin reescribirla. **Q6 resuelta (opción A).**
- **B3 (R31).** Cada servicio declara una salud con semántica propia: API = disponibilidad de sus dependencias; web = sirve HTTP; worker = su bucle avanza. La salud de web no depende de la base de datos ni de la API después del arranque.
- **M4 (R19).** La exigencia de no-root aplica a producción; en desarrollo se documenta la excepción por la caché montada y la diferencia de propietario entre Linux y Windows/WSL.
- **M5 (R20).** Se define el mapa variable→servicio y las excepciones legítimas; la comprobación de paridad es verificable.
- **M6 (R32d).** La versión del producto se declara en los metadatos del backend y es independiente de la versión del contrato de reglas y del motor.
- **M7 (R32c).** El navegador es el único que recuerda la organización; el servidor devuelve la lista en orden estable y el cliente restaura solo si el identificador está en esa lista.
- **M8 (R32b).** El rol mostrado es informativo; la autorización sigue siendo aditiva por permisos y por oficiales del partido.
- **M9 (R32e).** «Público» se refiere a las respuestas de la API; la proyección interna sí calcula la edad para el rol de aplicación y no se retira.
- **M10 (R24).** Se nombran las funciones y la vista afectadas por la migración aplicada.
- **m11 (R21).** «Sin origen» significa sin `Origin` y sin `Referer`; si cualquiera está presente y no está permitido, se rechaza.
- **m12 (R32g).** La comprobación de naming se limita a mensajes, comentarios de configuración y documentación.

## Usuarios

- **Visitante público:** consulta torneos publicados y usa el tiempo real de la página pública; necesita que el reintento funcione sin sesión.
- **Miembro de organización (viewer):** consulta el directorio de miembros y sus propios permisos; necesita leer roles y estados en su idioma.
- **Administrador de organización:** invita, revoca, gestiona miembros y espera que esas acciones sean coherentes y trazables.
- **Operador / árbitro:** compone la planilla, publica formaciones y opera partidos; necesita que la consulta de operación no se bloquee con otras operaciones y que sus acciones queden registradas.
- **Administrador de plataforma:** audita organizaciones; no gana acceso nuevo por esta spec.
- **Operador de despliegue y desarrollador:** levantan el entorno, leen la documentación de variables y necesitan servicios de producción sin privilegios, con verificación de salud y sin herramientas de prueba en producción.
- **Revisor o auditor técnico:** necesita que cada hallazgo quede cerrado o documentado con evidencia.

## Roles y visibilidad

- **Público:** no gana ni pierde acceso. Ve el estado del tiempo real y puede reintentar la conexión; no ve auditoría, roles, invitaciones ni configuración.
- **Miembro de organización:** conserva su acceso actual. Los textos de rol y estado que ya ve se muestran traducidos; no gana visibilidad sobre datos de otras organizaciones ni sobre la auditoría.
- **Administrador de organización (gestión de miembros):** sigue viendo las invitaciones de su organización, incluidas las vencidas, con el estado efectivo; no ve las de otra organización.
- **Operador / árbitro:** conserva el acceso por partido. Sus acciones sobre planilla, publicación de formación y oficiales quedan registradas con su identidad de miembro.
- **Administrador de plataforma:** sin cambios; no obtiene acceso a la auditoría organizacional por esta spec.
- **Aislamiento:** toda lectura y escritura de auditoría, invitaciones y operación de partido sigue sujeta al aislamiento por organización; ninguna otra organización puede ver ni modificar esos datos.

## Historias de usuario

- **HU-1.** Como visitante o miembro, quiero que «Reintentar» recupere realmente la conexión en tiempo real, para no quedarme con datos congelados y un botón que no hace nada.
- **HU-2.** Como operador de despliegue, quiero que los servicios de producción se ejecuten sin privilegios y que el estado de cada servicio sea visible, para detectar fallos sin leer registros a mano.
- **HU-3.** Como desarrollador, quiero que las variables que documento tengan efecto real en los contenedores, para no configurar en vano.
- **HU-4.** Como administrador de organización, quiero que una escritura desde un sitio ajeno sea rechazada aunque no lleve sesión, y que consultar la lista de invitaciones no modifique nada.
- **HU-5.** Como operador, quiero consultar la operación del partido sin bloquear un cierre en curso, y que la planilla, la publicación y los oficiales dejen rastro de quién hizo qué.
- **HU-6.** Como responsable de integridad deportiva, quiero que el sistema me impida duplicar un enfrentamiento manual más allá de lo que admite el formato de la fase (uno por pareja, dos en ida y vuelta), y que la base rechace minutos imposibles.
- **HU-7.** Como administrador, quiero ver roles y estados en mi idioma, y que la sesión no viaje en el cuerpo de una respuesta.
- **HU-8.** Como auditor técnico, quiero que el riesgo de una migración ya aplicada quede documentado y comprobado, y que los riesgos aceptados estén escritos.

## Definiciones

- **Hallazgo P2:** cualquiera de los identificados como R18-R32 en la auditoría del 2026-10-19, con el alcance acotado de esta spec.
- **Tratamiento:** decisión explícita de **corregir** (cambia el comportamiento observable), **documentar** (se deja como está y se registra el motivo y el riesgo) o **retirar** (se elimina el artefacto).
- **Reintento real:** intento de conexión nuevo que cierra el intento anterior; no es una llamada que termina sin efecto.
- **Estado efectivo de una invitación:** el estado almacenado, salvo que esté pendiente y su fecha de vencimiento ya haya pasado, en cuyo caso se presenta como vencida sin modificar el registro.
- **Auditoría organizacional:** registro por organización de acciones administrativas y de operación, con la identidad del miembro que las ejecuta, que no se expone públicamente.
- **Cambio efectivo:** modificación que altera el estado observable; repetir la misma operación con los mismos datos no es un cambio efectivo.
- **Precedencia de rol:** orden fijo dueño, administrador, operador, árbitro, observador; el rol mostrado es el de mayor precedencia que tenga el miembro. Es informativo: la autorización es aditiva por permisos.
- **Fase con clasificación:** fase de liga, de grupos o suiza que alimenta una tabla de posiciones y, por tanto, el desempate directo. Las fases eliminatorias no entran en esa categoría a efectos de esta spec, porque admiten repeticiones legítimas del mismo par (por ejemplo, la repetición de la gran final).
- **Fase de ida y vuelta:** fase con clasificación cuyo calendario se generó con dos vueltas; cada pareja se enfrenta dos veces, una en cada campo. Las vueltas se persisten al generar el calendario y una fase sin ese dato se trata como de una sola vuelta.
- **Enfrentamiento existente:** partido del mismo par en la misma fase y grupo, generado o creado manualmente, cuyo estado no es cancelado.
- **Invitación vencida:** invitación pendiente cuya fecha de vencimiento ya pasó. Su estado efectivo es «vencida» aunque el registro todavía diga «pendiente»; el registro se materializa como vencido al **crear** o **reenviar**, nunca al leer ni al revocar.
- **Disponibilidad de la API:** resultado de comprobar base de datos y Redis; no incluye otras dependencias ni la salud del servicio web.
- **Vitalidad del worker:** frescura de la señal que publica su bucle de procesamiento, con independencia de que haya eventos que procesar.
- **Organización activa restaurada:** organización que el navegador recuerda como última usada, solo si la persona sigue siendo miembro y la organización está activa; en cualquier otro caso se aplica el orden estable.
- **Orden estable:** criterio determinista y documentado para ordenar las organizaciones de una persona (por nombre y, en empate, por identificador) que no depende del orden interno de almacenamiento.
- **Verificación de salud:** comprobación periódica del propio contenedor que distingue «arrancado» de «operativo» según la semántica de cada servicio, incluida la frescura del bucle del worker.
- **Cuerpo parcial:** bytes recibidos de una petición cuya lectura terminó porque el cliente se desconectó, no porque el cuerpo estuviera completo.
- **Tope estructural de minuto:** límite máximo de forma que la base puede garantizar (180 minutos y 30 de descuento); no es la regla deportiva, que depende de la configuración de la fase.
- **Proyección interna:** vista de base de datos disponible para el rol de aplicación que ningún endpoint consume.

## Requisitos funcionales

### R18 — Reintento del tiempo real

- **RF-001.** CUANDO un usuario pulse «Reintentar» mientras el tiempo real está en estado de error, EL SISTEMA cerrará el intento anterior e iniciará un intento de conexión nuevo; MIENTRAS ese intento está en curso, el estado mostrará «conectando» y el botón no permitirá acumular intentos.
  *Criterios de aceptación:*
  - Tras pulsar «Reintentar» desde un estado de error se observa al menos un intento de conexión nuevo y el estado deja de ser «error» en cuanto arranca.
  - Si el intento falla, el estado vuelve a «error» y el botón sigue disponible; no se muestra un éxito falso.
  - Pulsar el botón varias veces seguidas no deja más de una conexión activa ni duplica suscripciones de eventos.
  - Al reconectar con éxito se produce como máximo una recarga de datos por consumidor.
  - El comportamiento es el mismo en la página pública del torneo, en el Workspace y en la pantalla de operación del partido.
  - En la vista de organización, sin sesión u organización activa el botón no aparece, como hoy; en la página pública depende del alcance del torneo.

### R19 — Servicio web sin privilegios

- **RF-002.** EL SISTEMA ejecutará el servicio web **de producción** con un usuario sin privilegios, de modo que el proceso no sea raíz ni pueda escribir en las rutas de la imagen que no sean temporales; en desarrollo se documenta la excepción por la caché del servidor y la propiedad del árbol montado.
  *Criterios de aceptación:*
  - En el perfil de producción, el identificador de usuario efectivo del proceso web no es 0, arranca, sirve la aplicación construida y no escribe en el directorio de la aplicación.
  - El perfil de producción sigue ejecutando los artefactos construidos y no monta código del host.
  - En desarrollo, la excepción está documentada con su motivo (el servidor de desarrollo escribe caché en el árbol montado y el identificador del contenedor puede no coincidir con el dueño del host en Linux frente a Windows/WSL) y con su condición de retiro (cuando el flujo de desarrollo deje de necesitar escritura en el montaje).
  - La excepción de desarrollo no se traslada a producción: la configuración de producción no depende de ella.
  - Ningún otro servicio de ejecución cambia su usuario por esta spec.

### R20 — Configuración efectiva y documentada

- **RF-003.** EL SISTEMA mantendrá un mapa explícito variable→servicio, de modo que toda variable documentada nombre el servicio que la consume y todo servicio reciba en contenedores las variables que consume, con sus excepciones declaradas.
  *Criterios de aceptación:*
  - Las siete variables documentadas hoy sin efecto pasan a tener efecto en el servicio de API: algoritmo de firma, audiencia de Google, nombre y vigencia de la cookie CSRF, límite de cuerpo de la petición, endpoint de firma del almacenamiento y vigencia de la firma.
  - Las dos variables que solo existían en la composición (límites de intentos de inicio de sesión y de registro) quedan documentadas con su default.
  - El mapa distingue, como mínimo, estos servicios y consumidores: API, worker, web, base de datos, trabajo de migraciones, trabajo puntual de cifrado y navegador. Cada variable documentada indica su consumidor o consumidores.
  - Se declaran como **excepciones legítimas**, y la comprobación no las marca: credenciales y parámetros de la base de datos (consumidos por el servicio de base de datos y por las migraciones), el selector de migraciones y el correo del primer administrador (consumidos solo por el trabajo de migraciones), la conexión administrativa del trabajo puntual de cifrado (nunca inyectada a la API), las variables del servicio web (bases de URL y marca de integración continua) y los valores de pruebas o de entornos locales.
  - La comprobación automática falla si una variable documentada no llega a ningún consumidor y no está en la lista de excepciones, si un servicio declara una variable que no está documentada para él, o si una variable documentada se atribuye a un servicio que no la consume.
  - Los defaults siguen siendo solo de desarrollo y el perfil de producción sigue exigiendo secretos externos y rechazando los valores de desarrollo.
  - Cambiar el valor de una de esas variables en el entorno local se refleja en el comportamiento del servicio tras reiniciarlo.

### R21 — Origen en escrituras sin sesión

- **RF-004.** CUANDO llegue una escritura desde un navegador con origen no permitido, EL SISTEMA la rechazará aunque la petición no lleve credenciales de sesión; SI la petición no declara origen —ni `Origin` ni `Referer`— ENTONCES se admitirá sin token, como hoy. Si cualquiera de los dos está presente y no está permitido, se rechaza.
  *Criterios de aceptación:*
  - Una escritura pública sin cookies ni autorización, con `Origin` no permitido, responde 403 y no ejecuta su efecto.
  - Una escritura pública sin credenciales con `Origin` permitido sigue funcionando sin token doble (por ejemplo, aceptar una invitación desde la aplicación).
  - Una petición **sin `Origin` pero con `Referer` no permitido** se rechaza con 403, como ya ocurre hoy.
  - Una petición sin `Origin` y sin `Referer` sigue admitida, para no romper el renderizado en servidor ni los clientes externos.
  - Las peticiones con credenciales de sesión y las rutas de identidad conservan la exigencia de token doble y la validación de origen.
  - Las lecturas seguras no cambian.

### R22 — Lectura sin efectos secundarios

- **RF-005.** CUANDO se listen las invitaciones de una organización, EL SISTEMA devolverá el estado efectivo de cada una sin modificar ningún registro; una invitación pendiente cuya fecha de vencimiento ya pasó se presentará como vencida. El registro se materializa como vencido al **crear** (antes de insertar la nueva) y al **reenviar**; **revocar** evalúa el estado efectivo y no lo reescribe.
  *Criterios de aceptación:*
  - Consultar la lista repetidamente no altera filas ni marcas de tiempo.
  - Una invitación pendiente vencida aparece como vencida en la lista, igual que en la vista previa por enlace.
  - **Crear** una invitación para un correo que tiene una pendiente vencida materializa esa pendiente como vencida y crea la nueva (201). No responde 409 por la unicidad de pendientes, y el correo deja de quedar bloqueado por una invitación que ya no sirve.
  - **Crear** una invitación para un correo con una pendiente **no vencida** sigue respondiendo 409 («ya existe una invitación pendiente»), como hoy.
  - Aceptar una invitación vencida sigue respondiendo 410 y no la consume.
  - **Revocar** una invitación vencida responde 409 («ya no está pendiente»), coherente con la vista previa y con la aceptación; no la marca como revocada, no la convierte en vencida y no borra el registro.
  - **Reenviar** una invitación vencida la materializa y la deja pendiente con token y fecha nuevos.
  - La lista no expone invitaciones de otra organización.
  - Ninguna de estas operaciones deja dos invitaciones pendientes para el mismo correo en la misma organización.

### R23 — Consulta de operación sin bloqueo

- **RF-006.** CUANDO se consulte la operación de un partido, EL SISTEMA responderá con una lectura consistente sin bloquear filas del partido, de modo que no se serialice con un cierre ni con otra escritura en curso.
  *Criterios de aceptación:*
  - La consulta de operación no adquiere bloqueo de fila del partido.
  - Con un cierre en curso que mantiene el bloqueo, la consulta responde con el estado anterior o con el ya confirmado, sin esperar al bloqueo.
  - La consulta no escribe ni inicia trabajo de escritura.
  - Las rutas que sí modifican el partido conservan su bloqueo y su orden.
  - El contenido de la respuesta no cambia (planilla, oficiales, segmentos, interrupciones, estado en campo y contadores).

### R24 — Migración ya aplicada: riesgo documentado y verificado

- **RF-007.** EL SISTEMA documentará que una migración ya aplicada endureció funciones y una vista sustituyendo texto sobre su definición, que esa sustitución falla en silencio cuando el texto no coincide, y dispondrá de una comprobación automática del estado final esperado; no reescribirá, reaplicará ni editará esa migración.
  *Criterios de aceptación:*
  - La documentación de migraciones describe el mecanismo, su alcance exacto y su modo de fallo silencioso.
  - El alcance documentado nombra las cinco funciones afectadas —`platform_set_user_active`, `platform_set_organization_active`, `platform_set_membership_active`, `platform_create_membership` y `requeue_outbox_events`— y la vista reescrita, la vista cruda de formación (`v_public_match_lineups_unpublished`).
  - Una comprobación automática falla si alguna de esas cinco funciones conserva la comparación de rol que admite nulos o si la vista no tiene el orden esperado.
  - La comprobación se ejecuta sobre una base con todas las migraciones aplicadas y también sobre una base nueva; no requiere volver a ejecutar la migración.
  - La comprobación informa de qué función o vista incumple, y la documentación explica cómo restaurar el estado esperado en una base existente.
  - No se edita ninguna migración aplicada y el historial de esquema sigue siendo append-only.
  - La documentación indica que un estado inesperado se corrige con una migración nueva, no con una reescritura.

### R25 — Auditoría de oficiales, planilla y publicación

- **RF-008.** CUANDO se asigne o retire un oficial, se guarde la planilla de un partido o se publique la formación de un equipo, EL SISTEMA registrará una entrada de auditoría organizacional en la misma transacción, con la acción, la entidad afectada, la identidad del miembro que la ejecuta y los datos mínimos de contexto.
  *Criterios de aceptación:*
  - Cada una de las tres acciones produce exactamente una entrada por cambio efectivo.
  - La entrada depende del **tránsito de estado** de la operación (alta o baja de un oficial, guardado de planilla, publicación de formación), no de la reescritura de una marca de tiempo: una petición idéntica que no altera el estado no produce entrada.
  - Repetir la misma publicación sin cambios no produce una entrada nueva, aunque la petición se repita y actualice marcas de tiempo.
  - Si la operación falla o se revierte, no queda ninguna entrada.
  - Las lecturas (por ejemplo, listar oficiales o consultar la operación) no producen entradas.
  - El cierre de acta y la interrupción de segmento conservan su registro actual, sin duplicarse.
  - Los datos registrados no incluyen documentos, fechas de nacimiento ni datos de contacto de jugadores.
  - Las entradas quedan sujetas al aislamiento por organización y no se exponen en ninguna proyección ni ruta pública.

### R26 — Enfrentamientos manuales duplicados

- **RF-009.** CUANDO se cree manualmente un partido de un borrador con ambos equipos definidos en una **fase con clasificación** (liga, grupos o suiza), SI el número de enfrentamientos existentes de ese par en la misma fase y grupo ya alcanzó el máximo del formato —uno, o dos si la liga se generó a ida y vuelta—, ENTONCES EL SISTEMA rechazará la creación con **409** y un mensaje que indique la fase, la pareja y el máximo aplicable; en ningún caso se crea el partido.
  *Criterios de aceptación:*
  - El máximo sale del **formato persistido de la fase**: una vuelta (máximo uno) o dos vueltas (máximo dos), registrado al generar el calendario de liga. No se deriva de la configuración de desempates ni del criterio de clasificación.
  - Una fase con clasificación sin dato de vueltas —no generada, o generada con una sola vuelta— admite un solo enfrentamiento por pareja.
  - Cuentan como enfrentamiento existente **todos** los partidos del par en la misma fase y grupo, generados o creados manualmente, salvo los cancelados. Un duplicado manual de un partido ya generado se rechaza.
  - En una fase de una vuelta, el segundo enfrentamiento manual del par responde 409 con el mensaje de límite (un enfrentamiento por pareja), sin datos personales.
  - En una fase de dos vueltas ya generada, el tercer enfrentamiento responde 409 con el mensaje de límite (dos enfrentamientos).
  - Un enfrentamiento cancelado no cuenta para el máximo y permite crear el sustituto.
  - Los calendarios generados no se validan con esta regla: una liga a dos vueltas se genera completa sin rechazos.
  - Las fases eliminatorias quedan fuera de la regla, porque admiten repeticiones legítimas del mismo par (por ejemplo, la repetición de la gran final en doble eliminación).
  - Un partido manual con un lado vacío no se considera enfrentamiento existente.
  - El mismo par en fases o grupos distintos se acepta.
  - La respuesta 409 no escribe nada: no crea partido ni ningún registro asociado.
  - **Soporte de datos:** una migración **aditiva** nueva persiste las vueltas de la fase al generar el calendario de liga, con valor por defecto una vuelta. La migración se aplica sobre volumen limpio y ya migrado y deja el mismo esquema final; los scripts de inicialización no se editan; las versiones publicadas no se reescriben y los triggers de estructura existentes impiden cambiar el formato de una versión publicada.
  - Mientras no exista el dato de vueltas, el máximo efectivo es uno; esto se documenta como limitación conocida y no se corrige creando partidos manuales.

### R27 — Topes de minuto en base de datos

- **RF-010.** EL SISTEMA rechazará en la base de datos un evento con minuto fuera de 0 a 180 o con minuto añadido fuera de 0 a 30, mediante una migración nueva y sin recortar ni corregir datos existentes.
  *Criterios de aceptación:*
  - Una inserción directa con minuto 181 o con minuto añadido 31 falla con un error de restricción.
  - Los valores 180 y 30 se aceptan.
  - La API sigue aplicando la regla deportiva efectiva de la fase y responde con su error actual cuando se excede; el tope estructural no se presenta como regla de negocio.
  - La migración se aplica sobre un volumen limpio y sobre uno ya migrado y deja el mismo esquema final en ambos.
  - SI existen filas que incumplen el tope, ENTONCES la migración falla con un mensaje explícito y no modifica datos.
  - No se edita ninguna migración aplicada.

### R28 — Dependencias de prueba fuera de producción

- **RF-011.** EL SISTEMA no incluirá herramientas de prueba en la imagen de producción: las dependencias de prueba se declaran por separado, la verificación las instala para ejecutar la suite y la auditoría de dependencias cubre todos los archivos declarados.
  *Criterios de aceptación:*
  - La imagen de producción no contiene las herramientas de prueba ni sus dependencias.
  - La suite de pruebas del backend se ejecuta completa en integración continua con las dependencias de prueba instaladas.
  - La auditoría de dependencias del backend audita todos los archivos de requisitos del proyecto y sigue fallando ante hallazgos accionables.
  - No cambian las versiones de las dependencias existentes.
  - La documentación de comandos reproduce la verificación local con las mismas instrucciones que la integración continua.

### R29 — Roles y estados en el idioma activo

- **RF-012.** CUANDO se muestre un rol, un estado de invitación o un estado de miembro, EL SISTEMA mostrará el texto traducido al idioma activo o, si el valor es desconocido, el valor recibido; nunca el código crudo de un valor conocido ni texto fijo en otro idioma.
  *Criterios de aceptación:*
  - Los cinco roles (dueño, administrador, operador, árbitro, observador), los cuatro estados de invitación (pendiente, aceptada, vencida, revocada) y los dos estados de miembro se muestran traducidos en español e inglés.
  - Al cambiar de idioma, todas esas etiquetas cambian, incluidas las del selector de invitación y el rol de solo lectura del dueño.
  - El listado de invitaciones ya no muestra el código crudo del rol ni el del estado.
  - Las etiquetas accesibles de los controles (por ejemplo, el enlace generado) también están traducidas.
  - Un valor desconocido no se inventa ni se traduce: se muestra tal cual.
  - Los dos catálogos mantienen paridad de claves y las pruebas lo verifican.

### R30 — Publicación de puertos en desarrollo

- **RF-013.** CUANDO se arranque el entorno de desarrollo, EL SISTEMA publicará el puerto de la API solo en la interfaz local, como ya hacen la base de datos, Redis y el almacenamiento.
  *Criterios de aceptación:*
  - La configuración renderizada de desarrollo asocia el puerto de la API a la interfaz local, no a todas las interfaces.
  - El resto de servicios de datos mantiene su publicación actual en la interfaz local.
  - El servicio web **conserva sin cambios** su publicación actual en desarrollo y la documentación explica que es el punto de entrada del desarrollador y que el flujo en Windows/WSL depende de ella.
  - No se modifica la publicación del servicio web en producción.
  - La aplicación sigue siendo accesible desde el navegador local y el renderizado en servidor alcanza la API por la red interna.
  - El perfil de producción no publica ningún puerto.

### R31 — Verificación de salud y orden de arranque

- **RF-014.** EL SISTEMA declarará una verificación de salud para la API, el servicio web y el worker, cada una con una semántica propia y explícita, y el servicio web esperará una sola vez a que la API esté disponible al arrancar.
  *Criterios de aceptación:*
  - **API:** su arranque espera a que las migraciones hayan terminado; se declara sana solo cuando su comprobación de disponibilidad confirma base de datos y Redis. Su salud no depende del servicio web.
  - **Web:** se declara sano cuando responde por HTTP en su propio puerto. Su salud **no** depende de la base de datos ni de la API después del arranque: si la API cae, el servicio web sigue sirviendo y su insanidad se refleja en la API, no en el web.
  - **Worker:** se declara sano mientras su bucle de procesamiento publica una señal de vitalidad al menos cada 30 segundos; la comprobación falla si la señal tiene más de 90 segundos. La señal se publica también cuando no hay eventos que procesar.
  - Con la base de datos detenida, la **API** queda insana; el **worker** sigue declarándose sano mientras su bucle siga avanzando y reintentando, y pasa a insano solo si el bucle se detiene; el **web** sigue sano porque su comprobación solo mide que sirve HTTP.
  - El orden de arranque es: las dependencias de datos sanas, las migraciones completadas, la API sana y después el servicio web. Esa espera ocurre solo al arrancar y no se reevalúa en ejecución.
  - Los intervalos, reintentos y periodos de gracia son acotados y no retrasan el arranque local más allá de lo que ya tarda hoy en condiciones normales.
  - El perfil de producción mantiene las mismas verificaciones y no publica puertos.

### R32 — Menores

- **RF-015.** CUANDO se acepte una invitación creando la cuenta, EL SISTEMA entregará la sesión solo mediante la cookie de sesión y no incluirá ningún token de acceso en el cuerpo de la respuesta; la aceptación con sesión existente no devuelve credenciales.
  *Criterios de aceptación:*
  - El cuerpo de la respuesta no contiene token de acceso ni tipo de token.
  - La cookie de sesión se fija igual que hoy y la persona queda autenticada en el Workspace.
  - No se contempla un periodo de transición: no hay parámetro, cabecera ni versión que reactive el token en el cuerpo.
  - Ningún cliente del producto lee un token del cuerpo.
  - El cambio de contrato se documenta como ruptura para consumidores externos, con la alternativa de usar la cookie de sesión.

- **RF-016.** CUANDO un miembro tenga varios roles, EL SISTEMA mostrará el de mayor precedencia según el orden dueño, administrador, operador, árbitro, observador, de forma consistente en el listado de miembros, en la respuesta de cambio de rol y en los datos de acceso de la sesión.
  *Criterios de aceptación:*
  - Un miembro con dueño y administrador se muestra como dueño.
  - Un miembro con operador y árbitro se muestra como operador.
  - Un miembro sin rol asignado conserva el comportamiento actual (observador por defecto).
  - La precedencia es una regla de **presentación** declarada y única: no altera la autorización, que sigue siendo aditiva por permisos.
  - Un miembro con permiso de operación que no es oficial del partido sigue sin poder operarlo; el rol mostrado no concede permiso por sí mismo.
  - El mismo rol se muestra en todas las pantallas y respuestas que lo exponen.

- **RF-017.** CUANDO una persona inicie sesión y pertenezca a varias organizaciones, EL SISTEMA devolverá sus organizaciones en **orden estable** y el cliente activará la **última organización usada en ese navegador** solo si aparece en esa lista; SI no hay historial válido, ENTONCES activará la primera del orden estable. La organización activa nunca será una organización ajena, inactiva o inexistente.
  *Criterios de aceptación:*
  - El servidor devuelve solo las organizaciones de la persona, activas y con membresía activa, en orden estable por nombre y, en empate, por identificador.
  - El navegador es el único que conserva el historial de la última organización usada; el servidor no guarda estado por navegador.
  - La restauración se decide en el cliente: si el identificador guardado está en la lista devuelta, se activa; si no está, se descarta sin error y se activa la primera del orden estable.
  - El historial se escribe **al cambiar de organización** en el Workspace y, además, al establecerse la organización activa tras un inicio de sesión en el que no había historial válido (para que el siguiente inicio sea estable).
  - Un identificador guardado inválido, de una organización eliminada, inactiva o sin membresía se trata igual: se descarta y se cae al orden estable.
  - Con historial válido de ese navegador se activa exactamente esa organización, aunque no sea la primera del orden estable.
  - Sin historial, dos inicios de sesión consecutivos activan la misma organización.
  - La pertenencia se revalida en el servidor en cada petición, como hoy: el historial del navegador no concede acceso.
  - Una persona sin organizaciones inicia sesión con organización vacía y el Workspace se comporta como hoy.

- **RF-018.** EL SISTEMA declarará una única versión del producto en los metadatos del backend y la expondrá en la descripción de la API; ninguna fuente mantendrá un literal independiente de la versión declarada.
  *Criterios de aceptación:*
  - La versión del producto se declara **una sola vez**, en los metadatos del backend; la documentación de la API la lee de ahí.
  - La versión del producto es independiente de la versión del contrato de reglas (`engine_version`) y de la del motor; ninguna de las dos se usa como versión del producto ni al revés.
  - Cambiar la versión declarada se refleja en la documentación de la API sin editar ningún otro valor.
  - No queda ningún literal de versión del producto fuera de la fuente declarada.
  - La comprobación falla con el estado actual, donde no hay fuente declarada y la versión es un literal: debe existir una prueba que compare la versión expuesta con la declarada y que falle si aparece un literal independiente.

- **RF-019.** EL SISTEMA no expondrá en las **respuestas de la API pública** campos que no estén declarados en el contrato público; la proyección de jugadores por torneo (`public_age`) se **mantendrá** como proyección interna documentada y **sin consumo**: no se retira, no se consume y no se expone por la API pública en esta spec.
  *Criterios de aceptación:*
  - «Público» significa respuesta de la API pública, no el acceso del rol de aplicación a la base: la proyección sí calcula la edad derivada y la devuelve a quien consulte la vista con el rol de aplicación.
  - Ninguna ruta de la API consulta esa proyección.
  - La documentación la describe como proyección interna sin consumo, aclara que calcula la edad derivada y que ninguna respuesta pública la expone, y deja constancia de que retirarla o consumirla requiere una spec propia.
  - La proyección no se retira: conserva su definición, su protección y las pruebas que la cubren.
  - Una prueba verifica que las respuestas públicas de jugadores y alineaciones no incluyen edad, documento ni fecha de nacimiento.
  - La proyección conserva su protección actual (solo filas de torneos publicados y foto solo con consentimiento).

- **RF-020.** EL SISTEMA mantendrá la entrega de eventos por la sala de la organización y documentará que no filtra por rol, junto con su mitigación actual: al cambiar los permisos de una sesión, la sesión deja de recibir eventos.
  *Criterios de aceptación:*
  - La documentación de tiempo real declara el alcance: todo miembro conectado de la organización recibe los eventos de la organización, con independencia de su rol.
  - La documentación describe la mitigación vigente y advierte de que un filtrado por evento y por rol requiere una spec propia.
  - El comportamiento de entrega no cambia en esta spec.
  - La revalidación de permisos sigue expulsando sesiones cuyos permisos cambiaron.

- **RF-021.** EL SISTEMA nombrará el almacenamiento por su proveedor real en mensajes de validación, comentarios de configuración y documentación; no quedará ninguna referencia a la marca anterior en esos tres ámbitos, salvo la nota histórica de la guía de agentes.
  *Criterios de aceptación:*
  - Los mensajes de rechazo de credenciales de desarrollo hablan de credenciales de desarrollo del almacenamiento, sin nombrar la marca anterior.
  - El archivo de entorno de ejemplo y la configuración de desarrollo etiquetan los valores de credenciales como solo desarrollo.
  - El universo de la comprobación son **mensajes de validación, comentarios de configuración y documentación**; los valores de pruebas automatizadas y de entornos locales quedan explícitamente excluidos.
  - Los valores de credenciales de desarrollo se conservan para no invalidar un almacenamiento local ya inicializado.
  - El perfil de producción sigue rechazando esos valores.
  - La nota histórica de la guía de agentes se mantiene.

- **RF-022.** CUANDO el cliente se desconecte a mitad del cuerpo de una petición, EL SISTEMA no procesará la petición como completa: no ejecutará su lógica, no escribirá datos ni responderá con un resultado de dominio.
  *Criterios de aceptación:*
  - Abortar la lectura del cuerpo no produce altas, cambios, eventos de outbox ni entradas de auditoría.
  - No se interpreta un cuerpo parcial como JSON válido ni se ejecuta el manejador.
  - El límite de tamaño de cuerpo y la validación de origen conservan su comportamiento.
  - Una petición completa sigue procesándose igual.

- **RF-023.** EL SISTEMA no entregará marcado comentado en sus vistas: la etiqueta comentada existente se retira.
  *Criterios de aceptación:*
  - No queda marcado comentado en las vistas entregadas.
  - La representación visual de la página no cambia.

## Trazabilidad hallazgo → requisito

| Hallazgo | Descripción breve | Tratamiento | Requisito |
|---|---|---|---|
| R18 | El botón «Reintentar» del tiempo real no reconecta | Corregir | RF-001 |
| R19 | El contenedor web se ejecuta como raíz | Corregir | RF-002 |
| R20 | Deriva entre variables documentadas y variables efectivas | Corregir | RF-003 |
| R21 | Escrituras públicas sin sesión omiten la validación de origen | Corregir | RF-004 |
| R22 | Listar invitaciones modifica filas y el ciclo de vida de la vencida queda indefinido | Corregir | RF-005 |
| R23 | La consulta de operación bloquea el partido | Corregir | RF-006 |
| R24 | Migración aplicada con reescritura por texto y fallo silencioso | Documentar y verificar | RF-007 |
| R25 | Auditoría organizacional incompleta | Corregir | RF-008 |
| R26 | Sin control de enfrentamientos manuales duplicados y formato de fase no persistido | Corregir (alcance acotado) | RF-009 |
| R27 | Minuto de evento sin tope en base de datos | Corregir | RF-010 |
| R28 | Herramientas de prueba en la imagen de producción | Corregir | RF-011 |
| R29 | Roles y estados sin traducir y códigos crudos | Corregir | RF-012 |
| R30 | Puerto de API publicado en todas las interfaces | Corregir | RF-013 |
| R31 | Sin verificaciones de salud ni espera de disponibilidad | Corregir | RF-014 |
| R32 | Token de sesión en el cuerpo | Corregir | RF-015 |
| R32 | Rol mostrado por orden alfabético | Corregir | RF-016 |
| R32 | Organización activa elegida por nombre sin desempate ni memoria del navegador | Corregir | RF-017 |
| R32 | Versión de la API fija | Corregir | RF-018 |
| R32 | Proyección interna sin consumidor que calcula edad derivada | Documentar | RF-019 |
| R32 | Relay sin filtrado por rol | Documentar (riesgo aceptado) | RF-020 |
| R32 | Marca de almacenamiento anterior residual | Corregir | RF-021 |
| R32 | Cuerpo parcial procesado como completo | Corregir | RF-022 |
| R32 | Marcado comentado en una vista | Retirar | RF-023 |

## Requisitos no funcionales

- **RNF-001. Sin secretos ni defaults nuevos.** Los cambios no introducen secretos, credenciales ni valores por defecto de desarrollo fuera del archivo de entorno de desarrollo; el perfil de producción sigue exigiendo valores externos y rechazando los de desarrollo.
- **RNF-002. Historial de esquema append-only.** Los únicos cambios de esquema son **dos migraciones nuevas y aditivas**: los topes de minuto y minuto añadido (R27) y la persistencia de las vueltas de fase que hace verificable el límite de enfrentamientos (R26). Ninguna migración aplicada se edita, incluida la que motivó R24. Las dos migraciones se aplican en orden, dejan el mismo esquema en volumen limpio y ya migrado, y no requieren tocar los scripts de inicialización.
- **RNF-003. Contrato público estable salvo lo declarado.** Los únicos cambios de contrato observable previstos son la retirada del token del cuerpo al aceptar una invitación (RF-015), el 409 nuevo al duplicar un enfrentamiento manual (RF-009) y el estado «vencida» calculado sin escritura (RF-005). Las respuestas públicas no ganan campos, y la edad derivada sigue sin exponerse por la API (RF-019). Todo lo demás conserva forma y contenido.
- **RNF-004. Aislamiento sin regresiones.** Toda consulta y escritura de datos de una organización sigue ejecutándose con contexto de organización y usuario dentro de la transacción; ninguna solución de esta spec eleva el rol de base de datos ni desactiva el aislamiento.
- **RNF-005. Verificación honesta.** Las verificaciones que no puedan ejecutarse en el entorno local se declaran como no ejecutadas con su motivo; ninguna se da por aprobada sin evidencia.
- **RNF-006. Sin afirmaciones de rendimiento no medidas.** La eliminación de bloqueos en la consulta de operación es una garantía de corrección; no se declara mejora de latencia ni de capacidad sin medición.
- **RNF-007. Paridad de idiomas.** Todo texto nuevo o modificado existe en español y en inglés, y la comprobación de paridad de los catálogos sigue pasando.
- **RNF-008. Arranque acotado.** Las verificaciones de salud usan intervalos, reintentos y periodos de gracia acotados y documentados; no introducen esperas indefinidas ni reinicios automáticos no declarados.
- **RNF-009. Despliegue conjunto.** Los cambios de contrato (RF-015, RF-016, RF-017) se despliegan con el cliente y el servidor de la misma versión; la compatibilidad con clientes externos se limita a lo declarado en la documentación.
- **RNF-010. Documentación en el mismo cambio.** Toda modificación de comportamiento observable actualiza la documentación afectada (guía de agentes, README o notas de migraciones) en el mismo cambio.
- **RNF-011. Sin dependencias nuevas.** No se añaden dependencias de ejecución ni de desarrollo salvo que una verificación lo exija; si se añadiera, debe pasar las auditorías de seguridad.
- **RNF-012. Excepción de desarrollo acotada y documentada.** La única excepción de esta spec (servicio web con el usuario de la imagen en desarrollo) está justificada por escrito, limitada a ese perfil, con motivo y condición de retiro, y no altera el perfil de producción, conforme a la sección 5.1 de la constitución.

## Datos personales y privacidad

- **Datos involucrados:** correo electrónico de la persona invitada (invitaciones), nombre y correo de los miembros y oficiales que ejecutan acciones, identificadores internos de jugadores y equipos en la operación del partido, y edad derivada en la proyección interna de jugadores.
- **Quién puede verlos:** el correo de una invitación y el directorio de miembros solo para miembros con permiso de gestión de miembros de esa organización; la auditoría organizacional, solo dentro de la organización y bajo su aislamiento; los datos de operación, para quien puede operar el partido.
- **Qué se expone públicamente:** nada nuevo. «Público» se refiere a las respuestas de la API; la proyección interna (RF-019) no se expone por esa vía, no se retira y sigue calculando la edad derivada solo para el rol de aplicación. La retirada del token del cuerpo (RF-015) reduce la exposición de una credencial.
- **R22** no cambia qué datos se ven, sino que la lectura deja de escribir; el estado efectivo es el mismo que ya mostraba la vista previa por enlace, y materializar el vencimiento al crear o reenviar no altera el correo visible ni su destinatario.
- **R32c** recuerda en el navegador el identificador interno de la organización activa: no es un dato personal ni contiene información de otras organizaciones, y se descarta si deja de ser válido. El servidor solo devuelve las organizaciones de la propia persona.
- **R25** registra la identidad del miembro que actúa (personal de la organización, no jugadores) y datos mínimos de contexto; no registra documentos, fechas de nacimiento, contactos de jugadores ni contenido de la planilla más allá de lo necesario para identificar el cambio.
- **R29** solo traduce vocabulario del producto; no altera datos.
- **R20 y R21** no tratan datos personales; **R21** reduce la superficie de escrituras aceptadas desde terceros.
- La auditoría y las invitaciones siguen sin exponerse en proyecciones públicas y conservan el aislamiento por organización.

## Casos límite

### Reintento y conexión (R18)

1. **Reintento mientras el socket sigue en error:** produce un intento nuevo; no se queda en «error» sin intentar.
2. **Reintento repetido con el botón:** un solo socket activo; no se acumulan suscripciones ni recargas.
3. **Reintento sin sesión en contexto de organización:** el botón no aparece; no se abre conexión de organización.
4. **Reintento en la página pública:** usa el alcance del torneo y no el de la organización.
5. **Reconexión exitosa:** una sola recarga por consumidor, con la deduplicación de eventos vigente.

### Contenedores y configuración (R19, R20, R30, R31)

6. **Arranque del servicio web de producción sin privilegios:** sirve la aplicación construida y no intenta escribir en la imagen.
7. **Servicio web de desarrollo como usuario de la imagen:** escribe la caché en el árbol montado y funciona con el dueño del host en Linux y en Windows/WSL; la excepción está documentada y no se traslada a producción.
8. **Variable documentada con valor no válido:** el servicio falla al arrancar como hoy; el valor no se ignora en silencio.
9. **Variable declarada sin documentar:** la comprobación automática falla con el nombre de la variable.
10. **Variable documentada que el servicio no consume:** la comprobación la señala salvo que esté en la lista de excepciones legítimas (base de datos, migraciones, trabajo puntual de cifrado, correo del primer administrador o variables de otro servicio).
11. **Puerto de API en la interfaz local:** el navegador local sigue accediendo y el renderizado en servidor usa la red interna.
12. **Servicio web en el flujo de desarrollo en Windows/WSL:** conserva su publicación documentada.
13. **Base de datos detenida:** la API queda insana; el worker sigue sano mientras su bucle avanza y reintenta; el web sigue sano porque sirve HTTP. No hay espera indefinida.
14. **Worker sin eventos durante un periodo largo:** la señal se sigue actualizando; no se declara insano por inactividad de dominio.
15. **Worker con el bucle detenido:** la señal deja de actualizarse y la comprobación falla pasados 90 segundos.
16. **Arranque con migraciones pendientes:** la API no se declara sana hasta que las migraciones terminan correctamente; el web no arranca antes.

### Seguridad de peticiones (R21, R22, R32h)

17. **Escritura pública desde origen no permitido:** 403, sin efecto y sin escritura.
18. **Escritura pública desde origen permitido sin credenciales:** se admite sin token doble.
19. **Petición sin `Origin` pero con `Referer` no permitido:** 403.
20. **Petición sin `Origin` y sin `Referer`:** se admite como hoy.
21. **Petición con credenciales y origen permitido pero sin token:** 403, como hoy.
22. **Listar invitaciones dos veces:** sin cambios en filas ni marcas de tiempo.
23. **Invitación pendiente vencida:** se muestra vencida; crear una nueva para ese correo materializa la anterior como vencida y crea la nueva (201); crear con una pendiente vigente responde 409; aceptarla da 410; revocarla da 409; reenviarla la deja pendiente con fecha nueva.
24. **Cliente que aborta a mitad del cuerpo:** no hay efecto de dominio ni fila escrita; la conexión se cierra.

### Operación y auditoría (R23, R25)

25. **Consulta de operación durante un cierre:** responde sin esperar el bloqueo, con estado anterior o confirmado.
26. **Consulta de operación sobre un partido terminado:** sigue devolviendo el estado final sin bloquear.
27. **Publicación repetida sin cambios:** no genera entrada de auditoría nueva, aunque la petición actualice marcas de tiempo.
28. **Fallo al guardar la planilla después de escribir la auditoría:** la transacción se revierte completa; no queda entrada huérfana.
29. **Asignación de un oficial ya asignado:** responde como hoy y no duplica la entrada de auditoría.
30. **Lectura de oficiales o de la operación:** no genera entradas.

### Emparejamientos y minutos (R26, R27)

31. **Segundo enfrentamiento manual del mismo par en una fase de una vuelta:** 409 con el mensaje de límite; no se crea nada.
32. **Fase de dos vueltas ya generada:** dos enfrentamientos admitidos; el tercero responde 409 con el mensaje de límite.
33. **Duplicado manual de un partido generado:** cuenta como enfrentamiento existente y responde 409.
34. **Límite fijado por el formato persistido:** cambiar la configuración de desempates no altera el máximo; el valor sale de las vueltas registradas al generar el calendario.
35. **Fase de liga sin dato de vueltas (no generada):** el máximo efectivo es uno; se documenta como limitación y no se corrige creando partidos manuales.
36. **Fase eliminatoria:** fuera de la regla; el mismo par puede repetirse legítimamente (por ejemplo, la repetición de la gran final).
37. **Enfrentamiento cancelado:** no cuenta; se puede crear el sustituto.
38. **Partido con un lado vacío:** no se considera enfrentamiento existente.
39. **Mismo par en otra fase o grupo:** se admite.
40. **Calendario generado con dos vueltas:** no se valida con la regla de altas manuales y no se rechaza.
41. **Inserción directa en base con minuto 181:** rechazada por restricción.
42. **Inserción directa con minuto añadido 31:** rechazada por restricción.
43. **Datos existentes fuera de rango durante la migración:** la migración falla con un mensaje explícito y no recorta valores.
44. **Regla deportiva de la fase menor que el tope estructural:** la API sigue rechazando con su error actual; el tope estructural no aparece como regla.
45. **Migración de vueltas en volumen limpio y ya migrado:** mismo esquema final; los scripts de inicialización no se editan.
46. **Cambio de vueltas en una versión publicada:** los triggers de estructura lo impiden; el formato no se reescribe.

### Presentación, contrato y detalles (R24, R28, R29, R32)

47. **Base existente con una función no endurecida:** la comprobación falla nombrando la función y la documentación indica corregir con migración nueva.
48. **Base existente con la vista sin el orden esperado:** la comprobación falla nombrando la vista.
49. **Base nueva:** la comprobación pasa sin volver a ejecutar la migración original.
50. **Imagen de producción sin herramientas de prueba:** la suite se ejecuta en integración continua, no en el contenedor de producción.
51. **Rol desconocido en los datos:** se muestra tal cual, sin inventar traducción.
52. **Cambio de idioma en el directorio de miembros:** roles y estados cambian; no queda texto fijo en inglés.
53. **Aceptar invitación con un cliente que esperaba token en el cuerpo:** deja de recibirlo y no hay transición que lo reactive; la sesión por cookie funciona y el cambio se documenta.
54. **Miembro con varios roles:** se muestra el de mayor precedencia; la autorización sigue siendo aditiva y un árbitro que no es oficial del partido no puede operarlo.
55. **Historial de organización válido:** se restaura aunque no sea la primera del orden estable.
56. **Historial de organización que ya no es miembro, está inactiva o fue eliminada:** se descarta sin error y se elige la primera por orden estable.
57. **Historial con un identificador que no corresponde a ninguna organización del usuario:** se descarta y se aplica el orden estable.
58. **Cambio de organización en el Workspace:** actualiza el historial; un inicio de sesión sin historial válido lo escribe al establecerse la organización activa.
59. **Persona sin organizaciones:** inicia sesión con organización vacía, como hoy.
60. **Cambio de versión declarada:** la documentación de la API lo refleja sin editar literales duplicados; un literal independiente hace fallar la prueba.
61. **Versión del contrato de reglas distinta de la del producto:** ambas conviven sin confundirse.
62. **Proyección interna consultada por error desde un endpoint nuevo:** la prueba de contrato público falla si aparece edad o dato sensible; la proyección no se retira y sigue calculando la edad para el rol de aplicación.
63. **Permisos revocados durante una sesión de tiempo real:** la sesión deja de recibir eventos, como hoy.
64. **Almacenamiento local ya inicializado con los valores actuales:** sigue funcionando; los valores se conservan etiquetados como desarrollo.
65. **Valor de prueba o de entorno local con el nombre de la marca anterior:** fuera del universo de la comprobación de naming (mensajes, comentarios de configuración y documentación).
66. **Página con el marcado comentado retirado:** misma representación visual.

## Fuera de alcance

- **R11** (ciclo de vida `live`/`suspended`, transiciones de torneo y eventos de partido por API). Aunque el informe lo agrupa en el P2, el usuario lo excluyó expresamente; no se documenta como resuelto.
- **R01 a R17** y cualquier hallazgo de los bloques P0 y P1 ya tratado por las specs 001 a 007; no se reabre su alcance.
- **Filtrado de eventos de tiempo real por rol o por permiso** (R32f): solo se documenta el riesgo; implementarlo es una spec propia.
- **Exponer públicamente la edad de los jugadores y retirar la proyección interna** (R32e): decisión cerrada Q3; la proyección se mantiene documentada y sin consumo, y cualquier cambio exige una spec propia.
- **Nuevas rutas o pantallas de auditoría organizacional:** se registran las entradas, pero no se añade una interfaz ni un endpoint de consulta.
- **Motor automático de emparejamientos, siembra por clasificación o resolución de slots entre fases.**
- **Reescritura, corrección o reaplicación de migraciones aplicadas**, incluidas las que motivaron R24, R26 y R27.
- **Nuevos formatos de competición o cambios en cómo se generan los calendarios**: las vueltas se persisten para poder verificar el límite, pero el sorteo, el sembrado y la generación no cambian.
- **Control de duplicados en calendarios generados** o en fases eliminatorias: la regla solo cubre altas manuales en fases con clasificación.
- **Corrección o anulación de actas cerradas y resultados confirmados.**
- **Cambios de reglas deportivas, de configuración de torneo o de las reglas de los formatos existentes**, y **cambios en la administración de plataforma**.
- **Rearquitectura de despliegue**, cambios de proveedor de almacenamiento, TLS, balanceadores o política de reinicio de contenedores.
- **Rendimiento medido**: no se fijan objetivos de latencia ni de capacidad.
- **Cambios en el modelo de autorización** (RBAC por organización y oficiales por partido), que se mantiene como está.
- **Rediseño visual** de las pantallas tocadas: solo textos, etiquetas y la retirada de marcado comentado.

## Criterios de finalización

1. **Reintento (R18):** se comprueba que pulsar «Reintentar» en estado de error produce un intento de conexión nuevo y que no se acumulan conexiones, en las tres pantallas afectadas; las pruebas del cliente cubren el cambio de estado y la no duplicación.
2. **Contenedores (R19, R30, R31):** el servicio web de **producción** no se ejecuta como raíz y la excepción de desarrollo está documentada con motivo y condición de retiro; la configuración renderizada de desarrollo asocia el puerto de la API a la interfaz local; API, web y worker declaran verificación de salud con su semántica propia; se demuestra que la API queda insana con la base de datos caída, que el web sigue sano sirviendo HTTP, que el worker pasa a insano al detenerse su bucle y que el web no arranca antes de que la API esté sana.
3. **Configuración (R20):** una comprobación automática verifica el mapa variable→servicio, incluidas las excepciones legítimas, y falla ante una variable documentada sin consumidor, una declarada sin documentar o una atribuida a un servicio que no la consume; se demuestra que las siete variables recuperadas cambian el comportamiento del servicio al modificarlas.
4. **Seguridad de peticiones (R21, R22):** existen pruebas de origen no permitido con y sin credenciales, de `Referer` no permitido sin `Origin`, de petición sin `Origin` ni `Referer` y de listado de invitaciones sin escrituras; se comprueban el vencimiento efectivo, la creación sobre una vencida, la creación sobre una pendiente vigente (409), la aceptación 410, la revocación 409 y el reenvío.
5. **Operación (R23):** existe una prueba que demuestra que la consulta de operación responde mientras otra transacción mantiene el bloqueo del partido, y que la consulta no escribe.
6. **Auditoría (R25):** se comprueba una entrada por cada una de las tres acciones, ninguna entrada en lecturas, ninguna entrada en operaciones fallidas, ninguna entrada al repetir una publicación idéntica aunque cambien marcas de tiempo, y ninguna entrada duplicada en publicaciones idempotentes.
7. **Esquema (R26, R27):** las **dos migraciones nuevas y aditivas** se aplican sobre volumen limpio y ya migrado y ambos terminan con el mismo esquema; la base rechaza minuto 181 y añadido 31; una base con datos fuera de rango hace fallar la migración de minutos con mensaje explícito; la migración de vueltas persiste el formato al generar una liga y no reescribe versiones publicadas; ninguna migración aplicada se modificó y los scripts de inicialización no se editaron.
8. **Migración ya aplicada (R24):** el riesgo está documentado con las cinco funciones y la vista afectadas; la comprobación automática del estado final pasa en limpio y en migrado y se demuestra que detecta y nombra una función no endurecida y una vista con orden incorrecto.
9. **Emparejamientos (R26):** se comprueban el máximo de uno en fases de una vuelta, el máximo de dos en una liga de dos vueltas ya generada, que los partidos generados cuentan como enfrentamiento existente, que el límite no depende de los desempates, la limitación de una liga sin generar, la exclusión de fases eliminatorias, el caso cancelado, el lado vacío, la fase o grupo distinto, que los calendarios generados no se validan y la ausencia de escrituras al rechazar.
10. **Dependencias (R28):** la imagen de producción no contiene herramientas de prueba, la suite completa se ejecuta en integración continua y la auditoría de dependencias cubre todos los archivos declarados.
11. **Presentación (R29):** no quedan roles ni estados conocidos en código crudo o en inglés fijo; el cambio de idioma afecta a todas las etiquetas y la comprobación de paridad de catálogos pasa.
12. **Contrato (R32a-R32d):** el cuerpo de aceptación de invitación no contiene tokens y no existe transición que los reactive; el rol mostrado sigue la precedencia declarada sin alterar la autorización aditiva ni el requisito de ser oficial del partido; la organización activa restaura la última usada en el navegador y, sin historial válido, aplica el orden estable, sin activar nunca una organización ajena, inactiva o inexistente; la versión de la API coincide con la declarada en los metadatos del backend y es independiente de la versión del contrato de reglas y del motor, y la prueba falla si aparece un literal independiente.
13. **Documentación (R32e, R32f):** la proyección interna sin consumidor se mantiene (no se retira), se documenta que calcula la edad para el rol de aplicación y que ninguna respuesta pública la expone, y el alcance del relay por organización queda documentado con su riesgo y su mitigación; las pruebas confirman que no se exponen campos nuevos.
14. **Detalles (R32g-R32i):** no queda la marca anterior en mensajes de validación, comentarios de configuración ni documentación (salvo la nota histórica) y la comprobación excluye valores de pruebas y entornos locales; un cuerpo abortado no produce efectos; no queda marcado comentado.
15. **Global:** pasan los jobs de integración continua aplicables (backend, frontend, infraestructura y seguridad); la documentación afectada se actualiza en el mismo cambio; las verificaciones no ejecutadas se declaran con su motivo; no se editó ninguna migración aplicada; la spec queda aprobada y revisada por una persona distinta del autor antes de declararla implementada.

## Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant garantizado por la base de datos | Sí | Invitaciones, auditoría y operación siguen con contexto de organización y usuario; ninguna ruta nueva lee datos de otra organización (RF-005, RF-008, RF-009). |
| §2.2 La aplicación no puede saltarse RLS | Sí | No se eleva el rol ni se desactiva RLS; las comprobaciones de base de datos se ejecutan con el rol de aplicación (RF-007, RF-010). |
| §2.3 Lo publicado es inmutable | Sí | Las vueltas de fase no se reescriben en versiones publicadas; los triggers de estructura existentes lo impiden (RF-009). |
| §2.4 Historial de esquema append-only | Sí | Solo dos migraciones nuevas y aditivas (R26 y R27); no se edita ninguna aplicada, incluida la que motivó R24 (RNF-002, RF-007). |
| §2.5 Lo público es una proyección mínima | Sí | No se añaden campos públicos; la edad derivada no se expone por la API y la proyección interna no se consume (RF-019, RNF-003). |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | No se añaden secretos; los defaults siguen solo en el archivo de entorno de desarrollo y producción los rechaza (RF-003, RNF-001). |
| §2.7 Administración global separada y auditada | Sí | No se añaden acciones de plataforma; la comprobación de R24 protege las funciones existentes (RF-007). |
| §2.8 Nada se da por terminado sin verificación | Sí | Cada RF tiene criterios verificables y las verificaciones no ejecutables se declaran (RNF-005). |
| §2.9 El código de desarrollo no llega a producción | Sí | Producción sigue sin código del host y sin herramientas de prueba (RF-002, RF-011). |
| §3.1 RLS y migraciones | Sí | Contexto por transacción; dos migraciones con checksum, probadas en limpio y migrado. |
| §3.2 Backend y reglas en JSON | Sí | No se cambian reglas deportivas ni configuración; los minutos siguen saliendo de la configuración. |
| §3.3 Frontend y `useApi.ts` | Sí | Los cambios de cliente (reintento, i18n, organización activa) siguen el cliente HTTP centralizado (RF-001, RF-012, RF-017). |
| §3.4 Seguridad y configuración | Sí | Origen en escrituras, credenciales fuera del cuerpo y auditoría sin datos personales (RF-004, RF-015, RF-008). |
| §3.5 Infraestructura y CI | Sí | `docker compose config -q`, merge de producción y auditorías siguen pasando (RF-013, RF-014, RF-011). |
| §4 Criterios para cambios de BD, backend, frontend e infraestructura | Sí | Migraciones nuevas, pruebas, `pytest`, `compileall`, `pnpm test`, `typecheck`, `build`, Compose y auditorías. |
| §5.1 Excepciones | Sí | La única excepción (web de desarrollo con el usuario de la imagen) está justificada, acotada y con condición de retiro (RNF-012). |
| §6 Definición de cumplimiento | Sí | Revisión humana distinta del autor y CI en verde antes de declarar implementada. |

## Riesgos residuales

- **R32f — relay sin filtrado por rol.** Todo miembro conectado de la organización recibe los eventos de la organización. *Mitigación:* la revalidación de permisos expulsa la sesión cuando cambian sus permisos; el filtrado por evento y por rol requiere una spec propia. Se acepta.
- **R24 — reescritura silenciosa de una migración aplicada.** Una base migrada antes de la comprobación podría conservar funciones sin endurecer y nadie lo habría notado. *Mitigación:* documentación del alcance y comprobación automática que nombra la función o la vista incumplidora; la corrección es una migración nueva. No se reescribe el historial.
- **R22 — unicidad de invitaciones pendientes con vencimiento diferido.** Una pendiente vencida sigue ocupando la unicidad por organización y correo hasta que se materializa en una escritura. *Mitigación:* crear y reenviar materializan el vencimiento y revocar una vencida responde 409 sin reescribirla; dos creaciones simultáneas quedan protegidas por el índice único y la segunda recibe 409. Se acepta con la decisión Q6 (opción A).
- **R26 — formato persistido solo al generar.** Una liga a dos vueltas que aún no se generó admite un solo enfrentamiento manual por pareja. *Mitigación:* la limitación se documenta y el alta manual está serializada por el bloqueo de fase y versión, así que dos altas simultáneas no crean duplicados. Se acepta.
- **R20 — deriva futura de configuración.** La comprobación depende de un mapa mantenido a mano. *Mitigación:* la comprobación falla en integración continua cuando el mapa y la configuración divergen (RF-003).

## Dudas abiertas

No quedan dudas abiertas. Las seis cuestiones se resolvieron el 2026-10-21 y están recogidas como **decisiones cerradas** arriba y en los requisitos indicados:

- **Q1 (R26) — resuelta:** bloqueo solo en altas manuales de fases con clasificación, con un enfrentamiento por pareja y dos si la fase se generó a ida y vuelta; el límite lo fija el formato persistido, no la configuración de desempates (RF-009).
- **Q2 (R32c) — resuelta:** se restaura la última organización usada en el navegador; sin historial válido, orden estable (RF-017).
- **Q3 (R32e) — resuelta:** la proyección de jugadores por torneo se mantiene como interna documentada y sin consumo; no se retira ni se consume (RF-019).
- **Q4 (R32a) — resuelta:** se retira el token del cuerpo y se documenta el cambio de contrato, sin transición (RF-015).
- **Q5 (R30) — resuelta:** solo la API pasa a la interfaz local; el servicio web se queda como está y la diferencia se documenta (RF-013).
- **Q6 (R22) — resuelta (opción A):** al crear se materializa la anterior como vencida y se crea la nueva (201); revocar una vencida responde 409; reenviar la reutiliza; se mantiene la unicidad de pendientes (RF-005).
