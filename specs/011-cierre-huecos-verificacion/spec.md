# Spec 011 — Cierre de los huecos de verificación de las specs 009 y 010

Estado: aprobada (2026-10-22)

## Contexto y objetivo

Las specs **009** (ciclo de vida de las invitaciones y salud del worker) y **010** (prueba de extremo a extremo del reintento del tiempo real) están implementadas, validadas y cerradas. En su validación, @reviewer dejó anotados **siete huecos no bloqueantes**: pruebas o evidencias que faltan, más dos observaciones de higiene del arnés. Ninguno es un defecto funcional conocido y ninguno justifica reabrir esas specs.

El riesgo que los huecos dejan abierto es de **verificación**, no de comportamiento: hoy hay contratos y criterios que se declaran cumplidos con evidencia parcial. En concreto:

1. **Atomicidad de C-2 sin prueba de reversión.** La 009 exige que, si falla la reapertura, no quede «una invitación materializada sin reapertura ni una reabierta sin la materialización previa»; solo se prueba el camino feliz.
2. **El worker recuperado no demuestra que procese eventos.** La 009 exige que el worker «procesa eventos con normalidad después de la recuperación»; la verificación operativa solo comprueba que el latido avanza.
3. **Mensajes de fallo que podrían filtrar un enlace con token.** Varias aserciones de la suite de invitaciones usan el cuerpo de la respuesta como mensaje de fallo, y ese cuerpo puede contener el enlace de invitación con su token efímero.
4. **El caso «miembro sin rol» carece de prueba y de contrato escrito.** El endpoint real rechaza con **403** a un miembro activo **sin ninguna fila de rol**, porque la dependencia que resuelve el contexto exige al menos un rol **antes** del handler; la única observación de **200** con `role_code="viewer"` y `permissions=[]` proviene de una prueba que **sustituye** esa dependencia y corresponde en realidad a un miembro con rol `viewer`. El caso no está declarado como contrato ni tiene prueba propia.
5. **La rama del registro del servidor con Docker disponible no tiene artefacto citado.** Su decisión está probada como función pura y el runner **sí se ejecuta**, pero ninguna validación cita un `server.log` con la cabecera y contenido real de los servicios: el hueco es de evidencia, no de código muerto.
6. **El resumen de la corrida cuenta muestras y puede leerse como transiciones.** Además, la captura de pantalla solo se guarda en fallo, mientras el plan de la 010 dijo «o del último estado si pasa».
7. **El paso de integración continua reescribe un artefacto que el arnés ya genera**, duplicando trabajo y pudiendo pisar una captura válida.

**Objetivo:** cerrar esos siete huecos con pruebas, evidencias reproducibles y documentación acotada, **sin reabrir** las specs 009 y 010, **sin cambiar sus contratos** y **sin añadir funcionalidad de producto**: Q1 conserva el contrato vigente (**403** para el miembro sin roles), y Q2 y Q3 conservan el comportamiento observable actual. Todos los requisitos son de verificación y documentación; el alcance se limita a lo que hoy carece de evidencia.

### Estado verificado (2026-10-22)

Comprobado sobre el árbol de trabajo; se describe lo observado, no el diseño:

1. **C-2.** `backend/tests/test_invitations.py:1353` prueba la materialización de la otra pendiente vencida y la reapertura en el mismo camino feliz. No hay ninguna prueba que induzca un fallo entre ambas escrituras. El flujo real materializa, actualiza la revocada y escribe la auditoría dentro de una sola transacción, y solo después del commit envía el correo (`backend/app/modules/invitations/router.py:397-463`). La suite ejecuta cada petición dentro de una transacción anidada (savepoint) que se revierte al terminar (`test_invitations.py:540-547`), así que la reversión que la prueba puede observar es la de ese savepoint, con la misma semántica que la transacción del request.
2. **Worker.** `infra/scripts/verify_worker_loop_health.sh` congela el bucle, observa `healthy → unhealthy → healthy`, comprueba que no hubo reinicio y que el latido avanzó (`:316-329`). No genera ni observa ningún evento de outbox: un worker que recuperase el latido pero no procesase nada pasaría la verificación. El worker reclama eventos con `claim_outbox_events`, publica en el stream y solo después los marca como `processed`; si la publicación falla, los marca como fallidos (`backend/app/workers/outbox.py:71-107`).
3. **Mensajes de fallo.** **37** aserciones de la suite usan el cuerpo de la respuesta como mensaje de fallo (por ejemplo `:626`, `:656`, `:1088`, `:1300`, `:1343`), con **23** apariciones literales de `response.text`: 20 como mensaje de fallo y 3 como **comprobación de contenido** (`assert "access_token" not in response.text`, `assert "token_type" not in response.text` en `:282-283` y `assert "invite_url" not in response.text` en `:1431`), que no son mensajes. Siete de los mensajes corresponden a respuestas que pueden incluir `invite_url` con token (`router.py:127-151`). El saneado `redactLine`/`redactLog` existe en el código de apoyo del arnés, pero no se aplica a los mensajes de fallo de las pruebas.
4. **Miembro sin rol.** `GET /organizations/current/access` está detrás de `get_auth_context` (`backend/app/core/tenancy.py:38-60`), que exige membresía activa **y al menos un rol** antes de llamar al handler: un miembro activo **sin ninguna fila de rol** recibe **403** («Membresía o rol activo no válido») y el handler nunca se ejecuta. La observación de **200** con `role_code="viewer"` y `permissions=[]` se debe a que `_invitation_api` (`backend/tests/test_invitations.py:554-565`) **sustituye** `get_auth_context`, de modo que no ejecuta el endpoint real; además, la cobertura existente (`:1108-1123`) corresponde a dueño, operador y un miembro **con rol `viewer`**, y no ejecuta ninguna acción protegida. Es decir: **no hay prueba del caso sin roles** ni contrato escrito para él, y la prueba actual no puede usarse como evidencia de ese caso.
5. **Registro del servidor.** `frontend/e2e/run.ts:302-332` captura `docker compose logs` cuando Docker está disponible y escribe `e2e-report/server.log` con cabecera y saneado. El runner **se ejecuta** en local y en integración continua y el artefacto se produce; el hueco es que **ninguna validación cita** una corrida con `server.log` de contenido real: la cobertura existente prueba solo la función pura de decisión y saneado (`frontend/tests/e2e-runner.test.ts:391-436`).
6. **Resumen y capturas.** `summary.json` publica por vista un recuento de **muestras** (`frontend/e2e/runModel.ts:151-158`, `formatStates` en `:402-406`) calculado sobre las muestras del observador (`frontend/e2e/artifacts.ts:104-143`), que registra una entrada por observación; con estados repetidos el número puede leerse como transiciones, y no existe ningún campo de transiciones. La captura se toma solo cuando el veredicto no es verde (`frontend/e2e/realtimeScenario.ts:439-441`), mientras el plan de la 010 declara «captura en el instante del fallo (o del último estado si pasa)» (`specs/010-…/plan.md:611`).
7. **CI.** El paso «Collect sanitized server logs» (`.github/workflows/ci.yml:254-268`) vuelca y reescribe `frontend/e2e-report/server.log` siempre, aunque el runner ya lo haya generado (`run.ts:326`). Con `continue-on-error`, un fallo del volcado no cambia el veredicto.

### Alcance

Entra en esta entrega: la prueba de atomicidad de C-2 y la de los mensajes de fallo de la suite de invitaciones; la prueba del caso «miembro sin rol» contra el endpoint auténtico; la extensión de la verificación operativa del worker para que observe un evento propio, con una ejecución real con Docker; la corrida real que produce el registro del servidor; la distinción entre transiciones y muestras en el resumen; la corrección de la expectativa de captura; y el ajuste del paso de integración continua para que no reescriba el artefacto.

No entra: reabrir las specs 009 y 010, cambiar sus contratos o criterios, ni ninguno de los riesgos aceptados de la spec 008. **No hay cambios de producto**: Q1 conserva el **403** vigente y Q2 y Q3 conservan el comportamiento observable actual, de modo que no queda ninguna decisión abierta que pueda introducirlos. La entrega es pequeña y sin dependencias nuevas, **no añade ningún job de integración continua** ni suma la verificación del worker al job existente de extremo a extremo, y se estima en **8 o 9 tareas**.

## Usuarios

- **Responsable de calidad o revisor:** necesita que los criterios ya declarados por las specs 009 y 010 tengan evidencia real, no una declaración, y que la evidencia no venga de una prueba que sustituye lo que quiere verificar.
- **Administrador de organización:** se beneficia de que la reapertura de invitaciones no deje estados a medias si algo falla, y de que su flujo de invitaciones no exponga enlaces en la salida de las pruebas.
- **Miembro sin rol:** necesita que el rechazo —**403** en la consulta de acceso y en toda acción protegida— sea un contrato explícito y estable, en lugar de una consecuencia accidental del código, y que no se confunda con el miembro que sí tiene rol `viewer`.
- **Operador de despliegue:** necesita que la verificación de salud del worker demuestre recuperación funcional, no solo que el proceso siga latiendo.
- **Operador de integración continua:** necesita que la corrida publicada no dependa de un artefacto reescrito y que el resumen no induzca a error al leerlo.

## Roles y visibilidad

- **Público:** sin cambios. No se añaden rutas, proyecciones ni contenido público.
- **Miembro de organización sin rol:** no gana ningún permiso y **no obtiene contexto**: la consulta de acceso y toda ruta protegida responden **403** antes de ejecutar el handler (Q1 corregida). El **200** con `role_code="viewer"` y `permissions=[]` corresponde a un miembro **con rol `viewer`**, no a quien no tiene roles.
- **Dueño y administrador:** sin cambios. No ganan ni pierden visibilidad.
- **Administrador de plataforma:** no aplica.
- **Aislamiento:** toda verificación nueva de invitaciones, roles y worker se ejecuta dentro de una organización de desarrollo; ninguna organización puede ver ni modificar datos de otra, y las pruebas de aislamiento existentes se conservan.

## Historias de usuario

- **HU-1.** Como revisor, quiero que un fallo a mitad de la reapertura deje las dos invitaciones exactamente como estaban, para poder creer la promesa de atomicidad de C-2.
- **HU-2.** Como administrador, quiero saber que el worker que se recupera vuelve a procesar trabajo real, para no acumular retraso silencioso tras un bloqueo.
- **HU-3.** Como revisor, quiero que un fallo de prueba nunca imprima un enlace con token, para que el diagnóstico no se convierta en una fuga.
- **HU-4.** Como miembro sin rol, quiero que mi acceso se rechace de forma estable —**403**, sin llegar al handler— y que ninguna acción protegida me deje pasar, para no depender de una consecuencia accidental del código ni de una etiqueta de presentación.
- **HU-5.** Como operador de integración continua, quiero que el resumen distinga lo que se observó de las transiciones reales y que el artefacto del registro se genere una sola vez.

## Definiciones

- **Hueco de verificación:** criterio o contrato ya exigido por una spec cerrada cuya evidencia actual es parcial, simulada o inexistente. No es un defecto funcional conocido.
- **Fallo inducido:** error provocado por la propia prueba, de forma determinista, en un punto concreto del flujo y **sin añadir ganchos, marcas ni variables al producto**.
- **Después de materializar:** el fallo ocurre cuando la transacción ya ejecutó la escritura que deja la otra pendiente vencida como vencida y antes de confirmarla.
- **Fallo posterior al commit:** error que ocurre cuando la escritura ya está confirmada (por ejemplo, el envío del correo). Conserva el contrato de la 009 y **no** es un caso de atomicidad.
- **Miembro sin rol:** miembro activo de una organización **sin ninguna fila de rol** asignada. No obtiene contexto de organización: el endpoint real le responde **403** antes del handler. No es lo mismo que un miembro con rol `viewer`, cuyo contexto sí se resuelve y cuya lista de permisos es vacía porque ese rol no concede ninguno.
- **Rol mostrado:** etiqueta que la consulta de acceso devuelve cuando la precedencia de roles no produce un código, hoy `viewer`. Solo puede observarse en una membresía con rol activo cuyo código no se resuelve; **no** es la respuesta de un miembro sin roles, no concede permiso alguno y no participa en la autorización.
- **Sustituir el contexto:** reemplazar en una prueba la dependencia que resuelve la organización y el rol del usuario. Una prueba que la sustituye **no** verifica el contrato del endpoint y no cuenta como evidencia de esta spec.
- **Ejecución real con Docker:** corrida del comando documentado sobre la pila de contenedores, distinta de una prueba unitaria con dobles. Es la única evidencia que cierra un hueco operativo; una prueba simulada no la sustituye.
- **Sonda de outbox:** evento que la propia verificación operativa inserta en la cola con un marcador único por corrida y un tipo sin handler de dominio, para observar que el worker lo procesa. No es una operación de producto.
- **Evento procesado por el worker:** evento de outbox que el worker toma y cuyo efecto es observable —queda en estado `processed` con marca de tiempo y su resultado se publica en el stream—, atribuible a esa corrida por el marcador. No basta con que la cola esté vacía ni con que el latido avance.
- **Muestra:** una observación del estado visible en un instante, tal como la registra el observador. Puede repetir el mismo estado varias veces.
- **Transición:** cambio entre dos estados visibles **distintos** y consecutivos. Varias muestras del mismo estado cuentan como una sola transición.
- **Captura en verde:** captura de pantalla del último estado observable cuando la corrida termina sin fallo. Con Q2 el arnés **no** la produce; el término se conserva para nombrar justamente lo que la expectativa histórica del plan de la 010 prometía y esta spec descarta.
- **Registro del servidor:** artefacto `server.log` con la cabecera fija y la salida saneada de los servicios de la pila.
- **Registro del servidor disponible:** `server.log` que existe, conserva la cabecera y contiene al menos una línea de contenido que no sea una declaración `# no disponible:` ni una línea en blanco. Un fichero con **solo la cabecera** no está disponible, y tampoco lo está uno que declare no disponible aunque arrastre la salida del comando fallido.
- **Fallback de CI:** escritura del registro del servidor por parte del paso de integración continua **solo** cuando el arnés no dejó un registro disponible.

## Decisiones de clarificación (2026-10-22, Q1 corregida)

Resueltas con el usuario y el coordinador; **sustituyen** a las dudas de la fase 1 y no dejan ninguna abierta. Ninguna introduce un cambio de producto: Q1 conserva el contrato vigente y Q2 y Q3 conservan el comportamiento observable actual.

- **Q1 (corregida el 2026-10-22) — Miembro sin rol: mantener el contrato real, 403.** Un miembro activo **sin ninguna fila de rol** recibe **403** en la consulta de acceso, porque la dependencia que resuelve el contexto exige membresía activa y al menos un rol **antes** del handler (`backend/app/core/tenancy.py:38-60`). La lectura anterior —**200** con `role_code="viewer"` y `permissions=[]`— describía el efecto de una prueba que sustituye esa dependencia, no el endpoint real, y mezclaba dos casos distintos: el miembro sin roles y el miembro con rol `viewer`. No cambia el producto: se corrige la spec, se añade la prueba del endpoint **auténtico** y se conserva la prueba del miembro con rol `viewer` (200/`viewer`/`[]`). *Alternativa descartada:* hacer que la consulta de acceso responda **200** con rol mostrado a quien no tiene roles, que **sí** sería un cambio de contrato —relajaría en toda la API la exigencia de rol activo— sin mejorar la seguridad, porque la autorización ya falla cerrada por ausencia de permisos. *Alternativa descartada:* responder **404** o un código nuevo por «sin rol», que añadiría un código al contrato sin aportar información sobre una membresía que el cliente ya conoce.
- **Q2 — Captura en verde: solo en fallo.** La captura se queda **solo en fallo**, como exige RF-005 de la 010; el **README** —el documento que enumera los artefactos del arnés— pasa a declarar que `screenshots/` solo se escribe cuando el veredicto de la vista no es verde, y la aclaración histórica de por qué el plan de la 010 decía «o del último estado si pasa» queda en esta spec (Q2 y RF-007), que cita la línea sin editar `specs/010-…`; `AGENTS.md` no menciona capturas y no cambia. *Alternativa descartada:* guardar también una captura del último estado en verde, que añade artefactos, tiempo por vista y superficie de saneado sin mejorar el diagnóstico de un fallo.
- **Q3 — Dónde se verifica el procesamiento de eventos: verificación operativa.** La comprobación de la **sonda de outbox** se añade a la **verificación operativa existente** del worker y su cierre exige una **ejecución real con Docker** declarada en la validación; **no** se añade al job de extremo a extremo ni a ningún job nuevo. «No se amplía el job de extremo a extremo» significa **no añadirle la verificación del worker**; el ajuste del paso que escribe el registro del servidor (RF-008) sigue viviendo en el job `e2e` existente, no añade trabajo —evita reescribir un artefacto— y no cambia su veredicto. *Alternativa descartada:* llevar la verificación a ese job, que la ejecutaría en cada propuesta de cambio a costa de acoplar la salud del worker al job de navegador, alargarlo y no representar mejor a un worker real con outbox.

## Requisitos funcionales

### Invitaciones (huecos de la spec 009)

- **RF-001.** CUANDO la reapertura de una invitación revocada falle de forma determinista **después de materializar** la otra pendiente vencida del mismo correo y **antes de confirmar** la transacción, EL SISTEMA no persistirá ninguna de las dos escrituras.
  *Criterios de aceptación:*
  - La prueba demuestra que el fallo ocurre en ese punto: la materialización ya se ejecutó en la misma transacción cuando se provoca el error, no antes de empezar ni después del commit.
  - La semántica de reversión es la del propio request: la petición corre dentro de una transacción anidada (savepoint) que se revierte, igual que en el resto de la suite, y la prueba afirma el estado persistido **después** de esa reversión.
  - La prueba obtiene una **respuesta HTTP de error** y afirma su código de estado: configura el cliente de pruebas para recibir la respuesta en lugar de una excepción propagada. Una excepción sin respuesta HTTP no es evidencia de C-2 y no se acepta como cierre.
  - Tras la respuesta de error, la otra invitación sigue **almacenada como pendiente** (no materializada), la revocada sigue revocada con su token, su fecha de vencimiento y sus marcas de tiempo originales, no hay filas nuevas y no existe ninguna entrada de auditoría `REOPEN_INVITATION`.
  - No se envía correo y la respuesta de error no incluye enlace ni token.
  - El fallo se induce desde la prueba, sin instrumentación del producto, y es reproducible: la misma causa produce el mismo punto de fallo.
  - Un fallo **posterior al commit** (envío de correo) no se usa para probar atomicidad y conserva el contrato de la 009: escritura confirmada, respuesta de error de envío y estado real reflejado al releer.
  - La prueba requiere PostgreSQL y se ejecuta con `RUN_DATABASE_TESTS=1`; si no se ejecuta, la validación la declara **no ejecutada**.

- **RF-002.** SI un miembro activo de la organización no tiene ninguna fila de rol asignada, ENTONCES EL SISTEMA le responderá **403** en la consulta de acceso —sin ejecutar el handler— y le rechazará con **403** toda acción protegida, sin leer ni modificar invitaciones, sin emitir enlace, sin enviar correo y sin escribir auditoría (Q1 corregida).
  *Criterios de aceptación:*
  - El observable es **403** con el mensaje de rechazo del contexto de organización, sin datos de la organización en el cuerpo. La prueba demuestra que el rechazo se produce en la dependencia que resuelve el contexto, de modo que el handler de la consulta de acceso no llega a ejecutarse.
  - La prueba se ejecuta contra el endpoint **auténtico** y **no** sustituye la dependencia de contexto: solo puede sustituir la identidad del usuario y la sesión de base de datos de pruebas; la comprobación de membresía y rol se ejecuta de verdad contra PostgreSQL.
  - El sujeto de la prueba es un miembro activo **sin ninguna fila de rol**, creado por la prueba con datos ficticios dentro de la organización demo; ningún miembro ni dato de otra organización participa.
  - El caso se distingue de forma explícita del **miembro con rol `viewer`**, que conserva la cobertura existente y sigue recibiendo **200**, `role_code="viewer"` y `permissions=[]`; `viewer` es ahí el rol asignado a esa membresía. Las dos pruebas conviven y ninguna sustituye a la otra.
  - El rechazo se comprueba sobre la gestión de miembros y las cuatro operaciones de invitación (crear, reenviar, reabrir y revocar): todas responden **403** y sobre una invitación concreta se demuestra que no hubo efecto —estado, token, vencimiento y marcas de tiempo intactos, ninguna fila nueva, ninguna entrada de auditoría y ningún correo—. Un 403 no lee ni modifica la invitación porque se emite antes del handler.
  - Una invitación inexistente, una de otra organización y una propia reciben el mismo rechazo: el caso no revela existencia, contenido ni pertenencia.
  - La consulta de acceso es estable entre llamadas sucesivas y no escribe nada; no se añaden rutas, campos, códigos ni mensajes.
  - El contrato se documenta en la documentación de acceso y roles del proyecto: sin rol no hay contexto (**403**) y, con contexto, la autorización se resuelve solo por permisos.
  - Requiere PostgreSQL y `RUN_DATABASE_TESTS=1`; sin esa variable `pytest -q` omite la prueba y la validación la declara **no ejecutada**.

### Salud del worker (hueco de la spec 009)

- **RF-003.** CUANDO el bucle del worker se reanude tras una congelación, EL SISTEMA demostrará, dentro de la verificación operativa ya documentada y **no** en un job de integración continua (Q3), que el worker **procesa una sonda de outbox** insertada por la verificación **después** de la reanudación, con su efecto observable dentro de un tiempo acotado y sin depender de que la cola estuviera vacía antes.
  *Criterios de aceptación:*
  - **Solo desarrollo/local.** La verificación lee el entorno de la aplicación desde la pila y solo continúa con `development`, `dev` o `local`. Con cualquier otro valor, o si no puede determinarlo, **rechaza**: termina con código distinto de 0, informa «no ejecutable» y **no escribe nada** —ni sonda, ni fila, ni artefacto—. No existe opción para forzar el paso.
  - **Identidad y contexto explícitos.** La sonda se inserta con la organización y el usuario **demo ya sembrados**, identificados por su clave de negocio (organización demo y su dueño), fijando el contexto de aislamiento en la misma transacción con la organización y el usuario. Si esos datos no existen o el usuario no es miembro activo, la verificación es **no ejecutable** (código 2) y no escribe.
  - **Evento inocuo y marcador único.** El tipo de evento es propio de la verificación, sin handler de dominio ni consumidor que lo interprete, y el payload lleva un marcador único por corrida. Un evento preexistente, una cola ya drenada o un evento de una corrida anterior **no** pueden hacer pasar la verificación.
  - **Repetible.** Dos corridas consecutivas usan marcadores distintos y ambas pueden pasar; no se reutiliza el marcador ni se supone que la fila anterior siga existiendo.
  - **Efecto observable.** Criterio **principal**: la fila de la sonda queda en estado `processed`, con marca de tiempo de procesamiento y al menos un intento, leída por su marcador. Criterio **corroborante**: la misma fila aparece publicada en el stream del outbox con su identificador de evento. Se elige el estado persistido como principal porque es durable y atribuible —el worker solo lo escribe después de publicar con éxito—, mientras que el stream es de mejor esfuerzo, con tope de longitud aproximado y pérdidas posibles, y no puede ser la única prueba.
  - **Tiempo acotado.** La espera del efecto tiene su propio límite, documentado y configurable, independiente de los tiempos de salud; agotarlo es **fallo** (código 1) con el paso identificado, no «no ejecutable».
  - **Limpieza.** Al terminar, con éxito o con fallo, la fila de la sonda se **elimina**; si no se puede eliminar se informa su identificador y su marcador y la verificación se declara fallida. La copia del stream no se borra a mano: caduca por el tope del stream y no contiene datos personales.
  - Se conserva la distinción actual entre verde, fallo y **no ejecutable** por falta de Docker o de contenedor: sin contenedores no se simula ni se da por buena.
  - La evidencia de cierre es al menos una **ejecución real con Docker** de la verificación completa, citada en la validación. La cobertura automática en cada propuesta de cambio queda fuera de alcance: no se añade al job de extremo a extremo ni a ningún job.
  - No se añaden endpoints, instrumentación en el producto ni cambios en el comportamiento del worker, su cadencia o los umbrales de salud, y la sonda no altera el latido.
  - La implementación actualiza `AGENTS.md` y el `README` con el paso nuevo, su variable de tiempo y su restricción a desarrollo/local; esta spec no los edita.

- **RF-004.** CUANDO una aserción de la suite de invitaciones falle, EL SISTEMA emitirá un mensaje que identifique la prueba y el **código de estado** —y, cuando exista, el identificador de motivo— sin incluir el cuerpo de la respuesta, el enlace de invitación ni el token.
  *Criterios de aceptación:*
  - Ningún **mensaje de fallo** se construye a partir del cuerpo de la respuesta ni de un enlace o token. Hoy son 37 aserciones y 23 apariciones literales de `response.text`, y ninguna puede quedar en esa forma como mensaje.
  - Las **comprobaciones de contenido** no se tocan: `assert "access_token" not in response.text`, `assert "token_type" not in response.text` y `assert "invite_url" not in response.text` comprueban qué contiene la respuesta, no son mensajes de fallo y siguen exactamente igual. La comprobación sobre el fuente distingue ambos usos y no las cuenta como hallazgos.
  - Los cuerpos que hoy se usan como diagnóstico se sustituyen por el estado y el identificador de motivo; la información necesaria para depurar se conserva en esos dos datos.
  - El formateador de mensajes vive en el **código de apoyo de las pruebas**, no en el código de la aplicación: no se añade nada a `app/` ni al producto.
  - Se verifica de dos formas: una prueba sobre el formateador, que demuestra que un cuerpo con enlace y token no aparece en la salida, y una comprobación sobre el fuente de la suite que encuentra **cero** mensajes de fallo construidos desde el cuerpo, el enlace o el token.
  - No cambia el comportamiento del producto ni la cobertura funcional: las aserciones siguen comprobando lo mismo.

### Arnés de extremo a extremo (huecos de la spec 010)

- **RF-005.** CUANDO se ejecute el comando local de la prueba de extremo a extremo en un entorno **con Docker disponible**, EL SISTEMA generará el registro del servidor a partir de la salida real de los servicios, saneada, y la validación citará la corrida concreta que lo demuestra.
  *Criterios de aceptación:*
  - Al menos una ejecución **real**, no unitaria, con Docker disponible produce el artefacto con contenido real de los servicios, con su cabecera y sin tokens, cookies ni credenciales.
  - La rama «Docker no disponible» sigue declarando la diferencia en el propio artefacto y **no** se presenta como captura real.
  - Los unitarios existentes se conservan, pero **no sustituyen** esta evidencia: si el entorno no permite Docker, se declara **no ejecutada**.
  - El artefacto sigue viviendo en el directorio ignorado de informes y no cambia su nombre ni su ruta.

- **RF-006.** EL SISTEMA publicará por vista el recuento de **muestras** en el campo `states` —con ese nombre y esa semántica— y añadirá el recuento de **transiciones** en un campo nuevo `transitions`, de modo que ninguno de los dos pueda confundirse con el otro.
  *Criterios de aceptación:*
  - `transitions` se calcula **por vista**, sobre las muestras de esa vista en orden, contando solo el paso a un estado **distinto** del inmediatamente anterior. Muestras repetidas del mismo estado no lo aumentan; el primer estado observado no cuenta como transición.
  - El cálculo es una función pura sobre los datos del artefacto de la vista, sin leer el reloj ni el entorno, y no se deriva del resumen agregado.
  - `states` conserva el nombre y la semántica de recuento de muestras; el resumen y la tabla legible etiquetan ambos conceptos —muestras y transiciones— con palabras distintas que no se solapan.
  - Un artefacto ausente o inválido no produce transiciones inventadas: el valor se declara ausente y los recuentos de muestras quedan como hoy, sin afectar al veredicto.
  - `schemaVersion` **no cambia**: el campo es aditivo y opcional, un lector que lo ignore sigue interpretando el resumen igual y el significado de los campos existentes no se altera. La decisión se documenta junto al campo.
  - No cambia la lógica del veredicto 0/1/2/3 ni las condiciones de éxito.

- **RF-007.** CUANDO la corrida de extremo a extremo termine **en verde**, EL SISTEMA **no** generará capturas de pantalla: la captura se conserva **solo en fallo**, como exige RF-005 de la 010 (Q2), y el **README** deja de prometer una captura en verde.
  *Criterios de aceptación:*
  - La captura de un fallo se conserva; ninguna captura contiene tokens, cookies ni datos personales; el artefacto publicado sigue limitado al directorio de informes y a la retención declarada.
  - Una corrida verde **no** genera capturas, con una prueba sobre la decisión del arnés que lo comprueba.
  - El **README** —el documento que enumera los artefactos del arnés— pasa a declarar que `screenshots/` solo se escribe cuando el veredicto de la vista **no** es verde. La aclaración histórica de la expectativa del plan de la 010 («o del último estado si pasa») queda registrada en esta spec (Q2 y este requisito), que la cita **sin** editar `specs/010-…`; `AGENTS.md` no menciona capturas y no cambia.
  - En ningún caso la captura influye en el veredicto 0/1/2/3.

- **RF-008.** SI el arnés ya dejó el registro del servidor **disponible**, ENTONCES el paso de integración continua **no** lo reescribirá; el paso solo escribirá el artefacto cuando falte o cuando declare que no está disponible.
  *Criterios de aceptación:*
  - Con un registro **disponible** —existe, conserva la cabecera y tiene al menos una línea de contenido que no sea una declaración `# no disponible:` ni una línea en blanco—, el paso no vuelve a capturar ni reescribe el fichero. Un fichero **solo con la cabecera** no cuenta como disponible, y tampoco uno que declare no disponible aunque arrastre la salida del comando fallido.
  - Si el artefacto falta, está vacío, tiene solo la cabecera o declara no disponible, el paso escribe la captura real saneada con el mismo saneado y la misma cabecera que el arnés.
  - La decisión es una función pura cubierta por pruebas con, al menos, estos casos: disponible, ausente, solo cabecera, declara no disponible, comando con código distinto de 0 y comando agotado por tiempo.
  - El paso mantiene `continue-on-error`, sigue sin condicionar el veredicto del job, no publica registros sin sanear y no cambia el nombre, la ruta ni la retención del artefacto.
  - Se mantiene la compatibilidad con **Node 24**: el paso sigue importando la función pura desde el código TypeScript del arnés con el mecanismo actual, sin dependencias nuevas ni paso de compilación añadido.

## Requisitos no funcionales

- **RNF-001. Sin cambio de producto.** Q1 conserva el contrato vigente —**403** para el miembro sin roles— y Q2 y Q3 conservan el comportamiento observable actual: esta entrega no introduce ningún cambio de comportamiento. Todo son pruebas, artefactos de verificación y documentación. No se añaden rutas, pantallas ni permisos, y no se altera la autorización aditiva por permisos.
- **RNF-002. Sin migraciones ni cambios de esquema.** No se añaden columnas, tablas, índices, políticas ni permisos de base de datos. Si una prueba necesita provocar un fallo, lo hace en tiempo de ejecución y sin tocar el esquema.
- **RNF-003. Determinismo y sin instrumentación del producto.** Los fallos se inducen de forma determinista desde las pruebas; no se añaden ganchos, atributos de prueba, variables globales ni contadores al producto. La sonda de outbox la inserta y la limpia la verificación operativa, no el producto, y solo en desarrollo/local. La verificación del worker conserva sus tiempos máximos y no depende de esperas fijas arbitrarias.
- **RNF-004. Sin secretos ni datos personales en salidas.** Ni los mensajes de fallo, ni el resumen, ni los artefactos, ni el registro del servidor, ni la sonda contienen tokens, enlaces de invitación, cookies ni datos personales reales. Se usan las cuentas y correos ficticios de desarrollo.
- **RNF-005. Honestidad de la evidencia.** Cada hueco se declara cerrado solo con la prueba o la corrida que lo demuestra, citada en la validación. Lo que no se pueda ejecutar en el entorno se declara **no ejecutado**; no se sustituye por una prueba simulada, por una prueba que sustituye la dependencia que se quiere verificar, ni se presenta como realizado.
- **RNF-006. Coste acotado.** No se añade ningún job de integración continua ni se suma la verificación del worker al job de extremo a extremo (Q3); el ajuste del paso que escribe el registro del servidor no añade trabajo a ese job, solo evita reescribir el artefacto. Las comprobaciones nuevas corren dentro de los jobs existentes y de la verificación operativa ya documentada, sin superar el presupuesto declarado (job de extremo a extremo de 25 minutos, vista de 4 minutos) y sin aumentar de forma apreciable la duración de la suite de backend.
- **RNF-007. Trazabilidad documental.** El contrato de acceso —**403** al miembro sin rol y `200`/`viewer`/`[]` solo para el miembro con ese rol—, el significado de los campos del resumen —`states` como muestras y `transitions` como transiciones—, la regla de captura —solo en fallo— y el paso nuevo de la verificación del worker se documentan en la documentación afectada (README, agentes o documentación del arnés) en el mismo cambio. Las specs 009 y 010 **no** se editan: esta spec cita sus requisitos, los aclara y no los sustituye.

## Datos personales y privacidad

- **Datos involucrados:** correo del destinatario de una invitación y nombre y correo del miembro que ejecuta la acción —datos personales—, y el token del enlace, que es un secreto que habilita el acceso. Las pruebas usan datos ficticios de desarrollo.
- **Quién los ve:** solo los miembros con permiso de gestión de miembros de la organización de prueba y quien revisa las pruebas. Ninguna otra organización accede a ellos.
- **Qué no se expone:** ni el token ni el enlace de invitación aparecen en mensajes de fallo, resumen, artefactos ni registros; la captura y el registro del servidor se publican saneados y no contienen cookies ni credenciales. La sonda de outbox no lleva datos personales, solo un marcador de la corrida.
- **Aislamiento:** todas las verificaciones se ejecutan sobre una organización ficticia; no se conectan a producción ni a datos reales.

## Casos límite

1. **Fallo tras materializar y antes de reabrir:** la otra pendiente vuelve a estar almacenada como pendiente y la revocada sigue revocada, con sus valores originales.
2. **Fallo tras reabrir y antes del commit** (por ejemplo, al escribir la auditoría): tampoco persiste nada; el resultado debe ser idéntico al del caso 1 y no debe quedar una reabierta sin su auditoría.
3. **Fallo posterior al commit** (envío de correo): no es un caso de atomicidad; la invitación queda pendiente con token nuevo y la respuesta es de error de envío, tal como fija la 009.
4. **Fallo inducido antes de empezar la transacción:** no cuenta como prueba de C-2 y la validación no lo acepta como evidencia.
5. **Excepción propagada sin respuesta HTTP:** no cuenta como prueba de atomicidad; la prueba debe observar la respuesta de error.
6. **Prueba de atomicidad sin PostgreSQL:** no se ejecuta y se declara **no ejecutada**; nunca se declara verde.
7. **Worker con la cola ya vacía antes de congelar:** la verificación debe insertar su propia sonda con marcador único; una cola vacía no demuestra nada.
8. **Sonda generada antes de la congelación y procesada antes:** no cuenta; la sonda válida es la posterior a la reanudación.
9. **Worker que recupera el latido pero no procesa:** es un fallo de la verificación (código 1), no un resultado no ejecutable.
10. **Entorno sin contenedores:** la verificación del worker y la captura real del registro se declaran **no ejecutadas**; no se simulan.
11. **Verificación del worker en un entorno distinto de desarrollo/local:** rechaza sin escribir nada, incluida la sonda; no hay forma de forzarla.
12. **Entorno sin los datos demo:** la verificación es no ejecutable y no escribe; no crea la organización ni el usuario.
13. **Sonda que no se procesa o que no se puede limpiar:** es un fallo con el paso identificado; el identificador y el marcador de la fila se informan para retirarla a mano.
14. **Miembro sin rol:** la consulta de acceso y toda acción protegida responden **403** antes del handler; no hay lectura ni escritura de la invitación, ni auditoría, ni correo.
15. **Miembro con rol `viewer`:** **200**, `role_code="viewer"` y `permissions=[]`, con la cobertura existente. No es el caso sin roles y no se usa como su evidencia.
16. **Prueba del caso sin rol que sustituye el contexto:** no es evidencia válida; el caso exige el endpoint auténtico.
17. **Miembro sin rol sobre una invitación inexistente o de otra organización:** el rechazo es idéntico en ambos casos y no revela su existencia.
18. **Artefacto de vista ausente o con muestras repetidas:** el resumen distingue muestra y transición; no inventa transiciones ni altera el veredicto.
19. **Corrida en verde:** no aparece ninguna captura; el fallo conserva la suya. En ningún caso la captura cambia el veredicto.
20. **Registro del servidor generado por el arnés y paso de CI después:** no se reescribe; si el arnés no dejó un registro disponible y en CI sí hay Docker, el paso escribe la captura real.
21. **Registro del servidor con solo la cabecera:** no está disponible; el paso de CI lo reescribe con la captura real.
22. **Fallo del volcado en CI:** el paso sigue sin cambiar el veredicto y no publica contenido sin sanear.
23. **Verificación del worker ejecutada sin Docker:** se declara **no ejecutada**; no se acepta una prueba simulada ni la sola cobertura unitaria como cierre del hueco.

## Fuera de alcance

- **Reabrir o editar las specs 009 y 010**, sus contratos, sus criterios de finalización o sus planes y tareas.
- **Riesgos aceptados de la spec 008:** sorteo Swiss en frío, R20, R22, R24, R26 y R32f, y la deuda de dependencias con hallazgos sin parche. No se corrigen aquí.
- **Cualquier cambio de producto**, incluida la respuesta de acceso: Q1 conserva el **403** para el miembro sin roles y no se relaja la exigencia de rol activo en ninguna ruta. No se añaden ni retiran rutas, campos, códigos de estado, permisos ni pantallas.
- Cambiar los umbrales, la cadencia o la semántica de salud del worker; añadir métricas, alertas o monitorización externa.
- Añadir un job de integración continua, un motor de navegador adicional o una suite nueva de componente o de navegador; sumar la verificación del worker al job de extremo a extremo.
- Rehacer el arnés de extremo a extremo, sus vistas, sus localizadores o su forma de provocar la indisponibilidad.
- Ampliar la auditoría organizacional, la superficie pública o los permisos de cualquier rol.
- Pruebas de navegador de otros flujos (invitaciones, planilla, clasificaciones, operación del partido).
- Cambios de esquema, migraciones nuevas o modificación de migraciones aplicadas.

## Criterios de finalización

1. Existe una prueba que induce un fallo después de materializar y antes del commit, demuestra ese punto, obtiene una respuesta HTTP de error sobre la transacción revertida (savepoint) y comprueba que no persiste ninguna de las dos escrituras ni queda auditoría, con PostgreSQL y declarada no ejecutada cuando no se pueda correr (RF-001).
2. El caso «miembro sin rol» queda probado contra el **endpoint auténtico** —sin sustituir el contexto— y declarado como contrato: **403** en la consulta de acceso y en las cuatro operaciones de invitación y en la gestión de miembros, sin leer ni modificar la invitación, sin auditoría y sin correo; se distingue del miembro con rol `viewer` (200/`viewer`/`[]`, cobertura existente) y requiere `RUN_DATABASE_TESTS=1` (RF-002, Q1 corregida).
3. La verificación operativa del worker demuestra que procesa una sonda generada después de la reanudación, con marcador único, estado `processed` como criterio principal y publicación en el stream como corroborante, limpia la fila, falla si no se procesa, tiene tiempo propio y solo se ejecuta en desarrollo/local; al menos una **ejecución real con Docker** queda citada en la validación (RF-003, Q3).
4. Los mensajes de fallo de la suite de invitaciones no incluyen cuerpos con enlace ni token, sin tocar las tres comprobaciones de contenido, verificado con una prueba del formateador —alojado en el código de apoyo de las pruebas— y una comprobación del fuente con cero mensajes construidos desde el cuerpo (RF-004).
5. Al menos una corrida real con Docker disponible genera el registro del servidor con contenido saneado, citada en la validación; sin Docker se declara no ejecutada (RF-005).
6. El resumen publica `states` como muestras y `transitions` como transiciones por vista, calculadas sobre muestras consecutivas distintas, sin cambiar `schemaVersion`, sin inventar transiciones con artefactos ausentes y sin cambiar el veredicto (RF-006).
7. La captura queda limitada al fallo, con prueba de que una corrida verde no genera capturas y el **README** declarando «solo en fallo»; la aclaración histórica queda en esta spec, sin editar la 010 (RF-007, Q2).
8. El paso de CI solo escribe el registro del servidor cuando no está **disponible** —incluido el caso de un fichero con solo la cabecera—, con la decisión cubierta por pruebas, `continue-on-error` y compatibilidad con Node 24, y sin condicionar el veredicto (RF-008).
9. Pasan las verificaciones del proyecto que apliquen (`cd backend && pytest -q`, `cd frontend && pnpm test`, `pnpm run typecheck`, `pnpm run typecheck:e2e`, `pnpm run build` y la verificación operativa del worker). `pytest -q` **sin** `RUN_DATABASE_TESTS=1` omite RF-001 y RF-002: en ese caso ambas se declaran **no ejecutadas** y no cuentan como verdes; si alguna otra no se ejecutó, se declara igual (RNF-005).
10. No hay migraciones, no cambia el esquema ni la superficie pública ni el comportamiento observable, y las specs 009 y 010 permanecen sin editar (RNF-001, RNF-002, RNF-007).

## Dudas abiertas

Ninguna. Las dudas de la fase 1 quedaron resueltas en «Decisiones de clarificación (2026-10-22, Q1 corregida)» y no queda ninguna decisión pendiente que pueda introducir un cambio de producto.
