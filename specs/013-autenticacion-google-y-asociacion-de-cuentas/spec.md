# Spec 013 — Autenticación con Google y asociación de cuentas

Estado: implementada

## Contexto y objetivo

El registro y el inicio de sesión actuales solo admiten correo y contraseña. Existe una preparación de Google OAuth a medias: la plataforma puede recibir una prueba de identidad de Google enviada por el navegador, comprobar que pertenece a esta aplicación y dar de alta una cuenta nueva; pero no hay ninguna pantalla que la use, no hay flujo interactivo, no hay vinculación con cuentas locales existentes y cualquier coincidencia de correo termina en un conflicto genérico. Ese camino parcial se **retira**: queda un único flujo de redirección con código de autorización canjeado en el servidor.

El objetivo es habilitar el inicio de sesión con Google de extremo a extremo y definir con precisión cómo se vincula una identidad de Google con una cuenta, de modo que:

1. La identidad que se acepta es siempre de Google y emitida para esta aplicación, verificada por el servidor.
2. Nunca se generan cuentas duplicadas ni asociaciones no verificadas, y nunca se produce suplantación de una cuenta ajena.
3. Autenticarse no concede ningún rol, membresía ni permiso: la autorización sigue resolviéndose por organización como hasta ahora.
4. Quien ya tiene cuenta local conserva su acceso con contraseña y puede decidir vincular Google desde su propia sesión; quien no la tiene puede empezar sin pasar por una contraseña.

Por qué importa: el acceso es la puerta de todo el Workspace. Un error en la vinculación mezclaría dos identidades reales en una cuenta, con acceso a organizaciones, torneos y actas que no le corresponden, y rompería el principio de aislamiento y de integridad del producto.

## Usuarios

- **Persona sin cuenta:** quiere entrar con Google sin inventar una contraseña y, si lo decide después, crear su organización.
- **Persona con cuenta local (correo y contraseña):** quiere seguir entrando como siempre y, si lo decide, vincular su cuenta de Google desde su sesión.
- **Persona cuya cuenta se creó con Google:** nunca ha tenido contraseña; solo puede entrar por Google y no puede vincular una segunda identidad.
- **Miembro de una organización:** entra y llega a la organización que ya tenía, con los permisos que ya tenía.
- **Persona autenticada sin organización:** puede crear su primera organización en el paso opcional, en ese momento o más tarde; mientras tanto conserva la sesión y ve el aviso correspondiente.
- **Administrador de organización:** no cambia nada de su autoridad por esta funcionalidad; no puede convertir el inicio de sesión en una vía de alta de miembros.
- **Administrador de plataforma:** puede desactivar cuentas; una cuenta desactivada no puede entrar por ninguna vía.
- **Operador del producto (despliegue):** configura o no configura Google; si no lo configura, el resto del acceso sigue funcionando igual y no queda ningún punto de entrada visible.

## Roles y visibilidad

- **Público (sin sesión):** ve la pantalla de acceso y, solo si Google está habilitado, la opción de continuar con Google; si no está habilitado, la opción no se muestra y el retorno del flujo se rechaza con el aviso de «no disponible», sin contactar con el proveedor. No ve datos de ninguna cuenta, salvo la confirmación de que un correo ya tiene cuenta cuando controla una cuenta de Google con ese correo verificado (RF-15, RF-17).
- **Persona autenticada sin organización activa:** no entra directamente al Workspace; aterriza en la pantalla de creación de organización, donde puede crearla o abandonar el paso y ver el aviso ya existente de «sin organización activa». No obtiene ninguna organización por el hecho de entrar con Google.
- **Persona autenticada que vincula Google:** ve y gestiona únicamente su propia vinculación; no ve datos de otras cuentas ni la existencia de identidades ajenas.
- **Miembro de organización (cualquier rol):** ve y puede lo mismo que antes de esta funcionalidad. El rol mostrado sigue la precedencia dueño → administrador → operador → árbitro → observador y no concede permiso.
- **Administrador de organización:** sin cambios. No puede invitar ni dar de alta a nadie a partir de una identidad de Google; las altas de miembros siguen por invitación.
- **Administrador de plataforma:** conserva la administración global separada del Workspace y puede desactivar cuentas; no puede iniciar sesión en nombre de otra persona ni editar resultados o versiones publicadas.

**Riesgo aceptado de enumeración:** la existencia de una cuenta se revela únicamente a quien controla una cuenta de Google cuyo correo está verificado, y solo a través del mensaje de «cuenta existente». Se acepta porque el mensaje debe ser accionable; la mitigación es el límite de intentos (RNF-1) y el coste residual aceptado es que ese mensaje distingue una cuenta con contraseña de una cuenta solo-Google, sin revelar nombre, datos, membresías ni motivo de desactivación.

Ninguna de estas reglas expone datos de una organización a otra: la identidad y la cuenta son datos de plataforma y la autorización sigue siendo por membresía y roles con el aislamiento por organización ya vigente.

## Historias de usuario

- HU-1. Como persona sin cuenta, quiero entrar con mi cuenta de Google para empezar sin crear una contraseña nueva.
- HU-2. Como persona sin cuenta, quiero decidir después, y de forma explícita, si creo una organización, para no acabar con un espacio que no pedí.
- HU-3. Como persona con cuenta local, quiero seguir entrando con mi contraseña aunque Google esté deshabilitado o caído.
- HU-4. Como persona con cuenta local, quiero que nadie pueda apropiarse de mi cuenta solo por tener una cuenta de Google con mi mismo correo.
- HU-5. Como miembro de una organización, quiero llegar a la organización con la que estaba trabajando —o a la primera de mi orden estable si ya no la tengo— al entrar con Google, con los mismos permisos.
- HU-6. Como administrador de organización, quiero que el inicio de sesión no otorgue roles ni membresías por sí solo.
- HU-7. Como administrador de plataforma, quiero que una cuenta desactivada siga sin poder entrar, sea cual sea el método.
- HU-8. Como persona que vuelve a la aplicación desde una invitación, quiero que al autenticarme con Google se me devuelva a esa invitación para aceptarla sin tener que abrir el enlace otra vez.
- HU-9. Como persona con cuenta local, quiero vincular mi cuenta de Google con una acción explícita y verificada desde mi propia sesión, y no por el simple hecho de que los correos coincidan.
- HU-10. Como persona autenticada sin organización, quiero poder crearla más tarde, aunque haya abandonado el paso opcional o el identificador elegido estuviera ocupado, sin tener que repetir el acceso con Google.

## Definiciones

- **Identidad de Google:** vínculo permanente entre una cuenta de Google (identificada por su identificador estable de cuenta, no por el correo) y una cuenta de la plataforma.
- **Prueba de identidad:** afirmación emitida por Google para esta aplicación, obtenida al canjear en el servidor el código de autorización del retorno. No es un token que el navegador pueda presentar por su cuenta. Las comprobaciones que le corresponden son emisor, audiencia propia, vigencia, sujeto presente y uso único del código.
- **Correo verificado por Google:** correo que Google afirma haber verificado para esa cuenta en el momento del inicio de sesión. Es una afirmación del proveedor, no una verificación hecha por la plataforma.
- **Comparación de correo:** comparación sin distinguir mayúsculas ni minúsculas, sobre el correo tal como lo almacena la plataforma y el correo verificado del proveedor.
- **Cuenta local con contraseña:** cuenta creada por registro con correo y contraseña.
- **Cuenta creada por Google (sin contraseña):** cuenta cuya contraseña es inexistente; solo puede entrar por la identidad de Google que se creó con ella.
- **Vinculación:** alta de la relación entre una identidad de Google y una cuenta existente, siempre a petición de la persona desde una sesión ya iniciada. Es distinta de «crear cuenta», que además crea la cuenta.
- **Vinculación automática:** vinculación que ocurre sin una acción explícita de la persona dentro de una sesión ya iniciada. Esta funcionalidad no la admite en ningún caso.
- **Identidad única:** cada cuenta tiene como máximo una identidad de Google y cada identidad pertenece a exactamente una cuenta. Es un invariante del almacenamiento, no una comprobación previa a la escritura.
- **Asociación no verificada:** vinculación basada en un dato que la plataforma no puede atribuir a la persona (por ejemplo, un correo no verificado, un correo que coincide con una cuenta que no ha dado su consentimiento, o un correo repetido en varias cuentas).
- **Organización activa:** la que la sesión muestra como seleccionada; es la última recordada por el cliente si sigue siendo accesible para la persona y, si no lo es o no hay ninguna recordada, la primera del orden estable ya existente (nombre y, en empate, identificador).
- **Destino de retorno:** ruta interna relativa de la propia aplicación a la que se devuelve a la persona después de autenticarse, capturada al iniciar el flujo y validada de nuevo al volver.
- **Pantalla de vinculación:** pantalla propia del producto, disponible para una sesión ya iniciada con contraseña, desde la que la persona vincula su cuenta de Google.

## Requisitos funcionales

### Disponibilidad y flujo de acceso

- RF-1. MIENTRAS el inicio de sesión con Google no esté configurado, EL SISTEMA no muestra la opción en la pantalla de acceso ni acepta el retorno del flujo de autorización; todo intento de retorno responde con el aviso de «no disponible», sin contactar con el proveedor y sin escribir cuenta, identidad, organización ni sesión.
- RF-2. CUANDO la persona elige continuar con Google, EL SISTEMA la envía al proveedor para autorizar el acceso y solicita únicamente los datos mínimos de identidad (identificador de cuenta, correo, estado de verificación del correo y nombre), sin pedir acceso a otros servicios de la cuenta; ningún token del proveedor pasa por el navegador.
- RF-3. EL SISTEMA no admite ninguna otra forma de acceso o de alta con Google distinta del retorno de ese flujo: no acepta pruebas de identidad presentadas directamente por el cliente, y el retiro del camino anterior se comunica como un cambio de contrato observable, de modo que un cliente antiguo recibe un rechazo con código estable y no una sesión.
- RF-4. CUANDO el proveedor devuelve el control, EL SISTEMA solo acepta el código de autorización y el valor de estado en una dirección de retorno fija y configurada, e ignora cualquier otro parámetro sin usarlo para decidir la cuenta, la sesión ni el destino.
- RF-5. CUANDO llega el retorno, EL SISTEMA canjea el código en el servidor y valida la prueba de identidad —emisor, audiencia propia, vigencia, sujeto presente y que el código no se usó antes— antes de aceptar cualquier identidad; SI alguna comprobación falla, ENTONCES EL SISTEMA rechaza el intento sin crear cuenta, identidad, organización ni sesión.
- RF-6. CUANDO el flujo pasa por el navegador, EL SISTEMA exige un valor de estado impredecible, verificado en el servidor, de un solo uso, ligado al navegador que inició el intento y con caducidad no superior a 10 minutos; SI falta, no coincide, ya se usó o está caducado, ENTONCES EL SISTEMA rechaza el intento sin crear sesión. Un intento nuevo invalida cualquier intento anterior pendiente del mismo navegador.
- RF-7. SI el proveedor cancela la autorización o la persona la rechaza, ENTONCES EL SISTEMA vuelve a la pantalla de acceso con un aviso de «inicio cancelado», sin error técnico y sin crear cuenta, identidad, organización ni sesión.
- RF-8. SI el proveedor no confirma que el correo está verificado, no entrega correo o no entrega identificador de cuenta, ENTONCES EL SISTEMA rechaza el inicio de sesión sin crear ni vincular nada.
- RF-9. CUANDO la persona inicia el flujo desde una dirección interna de la propia aplicación —incluida una invitación—, EL SISTEMA captura ese destino al iniciar, lo guarda en el servidor asociado al valor de estado del intento y no lo incluye nunca en la dirección de retorno del proveedor; al volver, acepta el destino solo si es una ruta interna relativa sin host ni esquema, de longitud no superior a 512 caracteres, y lo valida de nuevo antes de usarlo. Si el destino es válido, redirige a él una sola vez y la persona continúa donde estaba —también si es una invitación, cuyo token aparece en la barra de direcciones igual que al abrir el enlace original—; SI el destino falta, caduca o no es válido, ENTONCES aplica el destino por defecto: el Workspace, o la pantalla de organización si la sesión no tiene ninguna. En ningún caso la persona queda con una dirección del proveedor como destino final.

### Asociación de cuentas

- RF-10. CUANDO la identidad de Google ya está vinculada a una cuenta activa, EL SISTEMA abre una sesión nueva para esa cuenta y devuelve como organización activa la recordada por el cliente si sigue siendo accesible y, si no lo es o no hay ninguna, la primera del orden estable existente.
- RF-11. SI la cuenta vinculada a la identidad está desactivada, ENTONCES EL SISTEMA niega la sesión con el aviso genérico de cuenta desactivada, no la reactiva y no crea ni modifica ninguna otra fila.
- RF-12. CUANDO la identidad no está vinculada y el correo verificado no pertenece a ninguna cuenta, EL SISTEMA crea la cuenta sin contraseña y la identidad en una sola operación, y solo después emite la sesión; si cualquier paso falla, no queda cuenta ni identidad. El nombre para mostrar se toma del proveedor una vez: se recorta a 100 caracteres; si viene vacío, solo con espacios o queda vacío tras el recorte, se usa la parte del correo anterior a la arroba, recortada a 100 caracteres, y si tampoco hay, un nombre neutro estable. El alta nunca falla por el nombre.
- RF-13. EL SISTEMA nunca crea una segunda cuenta para un correo ya existente ni permite que una identidad quede vinculada a más de una cuenta: cada identidad pertenece a exactamente una cuenta y cada cuenta tiene como máximo una identidad de Google. El invariante lo garantiza el propio almacenamiento con una garantía de unicidad —no una comprobación previa seguida de una escritura—, de modo que dos intentos simultáneos no pueden dejar dos cuentas ni dos identidades.
- RF-14. SI una cuenta ya tiene una identidad de Google vinculada y se intenta vincular otra distinta, ENTONCES EL SISTEMA rechaza la segunda sin sustituir la existente, sin desvincular nada y sin fusionar ni mover datos de ninguna de las dos cuentas; repetir la vinculación de la misma identidad ya vinculada no crea ni modifica nada.
- RF-15. SI el correo verificado, comparado sin distinguir mayúsculas, pertenece a una cuenta local activa con contraseña que no tiene identidad de Google, ENTONCES EL SISTEMA no vincula automáticamente, no crea cuenta nueva y responde con un mensaje explícito y accionable —«Ya existe una cuenta con este correo; inicia sesión con tu contraseña»— sin revelar ningún otro dato de la cuenta, ni el nombre de la persona, ni identificadores del proveedor.
- RF-16. SI el correo verificado pertenece a una cuenta desactivada, con identidad de Google o sin ella, ENTONCES EL SISTEMA responde con el aviso genérico de cuenta desactivada —que no puede iniciar sesión y debe contactar con la administración—, sin indicar si tiene contraseña, si es solo-Google ni el motivo de la desactivación, y sin revelar ningún otro dato.
- RF-17. SI el correo verificado pertenece a una cuenta sin contraseña, ENTONCES EL SISTEMA rechaza el inicio de sesión de forma cerrada y no vincula: por la regla de identidad única, una cuenta sin contraseña siempre se creó junto con su identidad de Google, así que este caso solo puede provenir de un estado inconsistente o de un correo repetido en otra cuenta de Google. No se elige ninguna cuenta, no se crea otra y se indica que debe entrar con la cuenta de Google con la que se creó.
- RF-18. CUANDO una persona con sesión ya iniciada abre la pantalla de vinculación y confirma con su cuenta de Google, EL SISTEMA vincula la identidad solo si el correo verificado coincide exactamente, sin distinguir mayúsculas, con el correo de su cuenta; SI no coincide, ENTONCES EL SISTEMA rechaza la vinculación en una sola operación, sin identidad nueva, sin cambios en la cuenta y sin alterar la sesión en uso. Una cuenta con contraseña puede iniciar sesión y vincular; una cuenta solo-Google no puede, porque ya tiene su identidad.
- RF-19. SI la identidad de Google que se intenta vincular ya pertenece a otra cuenta, ENTONCES EL SISTEMA rechaza la vinculación sin modificar la cuenta de origen, la de destino, sus membresías ni la identidad existente.
- RF-20. CUANDO una identidad ya vinculada vuelve a presentarse con un correo distinto del almacenado, porque la cuenta de Google cambió de correo, EL SISTEMA reconoce la identidad por su identificador estable, no reescribe el correo almacenado y no crea ni fusiona cuentas; si el correo nuevo coincide con otra cuenta, esa coincidencia no se usa para vincular ni para mover nada.
- RF-21. EL SISTEMA nunca fusiona cuentas: ni membresías, ni roles, ni auditoría, ni historial de torneos se mueven de una cuenta a otra como consecuencia del inicio de sesión, de una vinculación o de un cambio de correo en el proveedor.
- RF-22. SI dos intentos simultáneos llegan con la misma identidad o con el mismo correo verificado, ENTONCES EL SISTEMA deja una sola cuenta y una sola identidad, y los intentos restantes resuelven sobre la ya creada o reciben el mensaje que corresponda a su caso, sin duplicar filas.

### Organización opcional

- RF-23. CUANDO el flujo de Google termina —con la cuenta y la sesión ya resueltas según RF-10 o RF-12— y la sesión no tiene ninguna organización, EL SISTEMA ofrece una pantalla propia para crear la organización; el paso es opcional y no crea ninguna organización hasta que la persona confirma nombre e identificador explícitos, y la misma pantalla queda disponible después para cualquier sesión sin organización. Si la persona abandona el paso, no se crea ninguna organización, conserva la cuenta y la sesión ya resueltas, ve el aviso de «sin organización activa» y puede retomarlo más tarde.
- RF-24. CUANDO la persona confirma la creación de la organización, EL SISTEMA crea la organización con esa persona como dueña en una sola operación; SI el identificador elegido ya está en uso, ENTONCES rechaza solo ese paso, conserva la cuenta y la sesión, no crea la organización y permite reintentar con otro identificador sin repetir el acceso con Google.
- RF-25. SI la sesión ya tiene al menos una organización, ENTONCES EL SISTEMA no ofrece esa pantalla por esta vía ni permite crear una organización adicional desde ella; el alta de organizaciones adicionales queda fuera de esta funcionalidad.

### Autorización

- RF-26. EL SISTEMA no concede ninguna membresía, rol, permiso ni acceso a organización por el hecho de iniciar sesión con Google: los permisos se resuelven exclusivamente por las membresías y roles existentes, la administración global sigue siendo independiente de la autenticación y ninguna organización se crea a partir de datos inferidos por defecto.

### Sesión y cierre de sesión

- RF-27. CUANDO se completa un inicio de sesión con Google, EL SISTEMA emite la sesión solo después de todas las validaciones, con la misma vigencia y las mismas garantías que el acceso con contraseña; sustituye la sesión anterior del mismo navegador —no la reutiliza ni la prolonga— y no revoca las sesiones abiertas en otros dispositivos.
- RF-28. CUANDO la persona cierra sesión, EL SISTEMA revoca solo la sesión en uso y conserva la cuenta y la vinculación de Google, de modo que el siguiente inicio de sesión con Google vuelve a funcionar.
- RF-29. EL SISTEMA mantiene sin cambios el inicio de sesión con correo y contraseña, la revalidación de sesión y la revocación de sesiones ya existentes.
- RF-30. SI una cuenta sin contraseña intenta iniciar sesión con contraseña, ENTONCES EL SISTEMA responde con el error genérico de credenciales inválidas, sin revelar que la cuenta existe ni que no tiene contraseña.

### Mensajes y estados visibles

- RF-31. CUANDO un inicio de sesión, una vinculación o la creación opcional de organización falla o termina bien, EL SISTEMA muestra el mensaje del catálogo cerrado de esta spec, con su código estable, en español y en inglés, sin incluir tokens, códigos de autorización, identificadores del proveedor, nombres ni datos de la cuenta.
- RF-32. MIENTRAS un inicio de sesión o una vinculación con Google está en curso, EL SISTEMA muestra la acción en estado de espera, impide pulsaciones repetidas, anuncia el estado a lectores de pantalla y deja el formulario de correo y contraseña utilizable en cuanto termina.
- RF-33. La pantalla de vinculación muestra, antes de empezar, si la cuenta ya tiene una identidad vinculada y, si la tiene, no ofrece vincular otra; durante el intento muestra la espera; al terminar con éxito muestra un aviso de vinculación completada y deja la identidad vinculada visible; con Google deshabilitado muestra el aviso de «no disponible» y no inicia el flujo; con cancelación muestra el aviso de cancelación; con el proveedor caído o lento muestra el aviso de «no disponible». Quien recibió el mensaje de cuenta existente llega a esta pantalla iniciando sesión con su contraseña.

## Catálogo de mensajes y códigos estables

| Código estable | Cuándo | Mensaje (español; existe equivalente en inglés) |
|---|---|---|
| `GOOGLE_UNAVAILABLE` | Google no configurado, proveedor inaccesible o intento agotado | «El acceso con Google no está disponible en este momento.» |
| `GOOGLE_CANCELLED` | La persona o el proveedor cancela la autorización | «Se canceló el inicio de sesión con Google.» |
| `GOOGLE_STATE_INVALID` | Estado ausente, repetido, de otro navegador o caducado | «El intento de acceso ha caducado. Vuelve a intentarlo.» |
| `GOOGLE_IDENTITY_INVALID` | Prueba no válida, código ya usado, correo no verificado, campos ausentes o datos inconsistentes | «No se pudo verificar tu cuenta de Google.» |
| `ACCOUNT_DISABLED` | Cuenta desactivada, por cualquier vía | «Esta cuenta no puede iniciar sesión. Contacta con la administración.» |
| `ACCOUNT_EXISTS_PASSWORD` | El correo verificado pertenece a una cuenta local con contraseña | «Ya existe una cuenta con este correo; inicia sesión con tu contraseña.» |
| `ACCOUNT_EXISTS_GOOGLE_ONLY` | El correo verificado pertenece a una cuenta sin contraseña | «Ya existe una cuenta con este correo; inicia sesión con la cuenta de Google con la que se creó.» |
| `GOOGLE_ALREADY_LINKED` | La cuenta ya tiene una identidad de Google | «Esta cuenta ya tiene una cuenta de Google vinculada.» |
| `LINK_EMAIL_MISMATCH` | El correo verificado no coincide con el de la cuenta en sesión | «El correo de esa cuenta de Google no coincide con el de tu cuenta.» |
| `LINK_IDENTITY_TAKEN` | La identidad pertenece a otra cuenta | «Esa cuenta de Google ya está vinculada a otra cuenta.» |
| `RATE_LIMITED` | Se supera el límite de intentos | «Demasiados intentos. Inténtalo de nuevo más tarde.» |
| `ORGANIZATION_SLUG_TAKEN` | Identificador de organización ocupado en el paso opcional | «Ese identificador de organización ya está en uso.» |
| `GOOGLE_LINK_SUCCESS` | Vinculación completada | «Tu cuenta de Google quedó vinculada.» |

## Requisitos no funcionales

- RNF-1. **Límite de intentos.** Se limitan las peticiones de inicio del flujo y de retorno, por origen de red y —solo cuando ya se conoce tras el canje— por identificador de cuenta; el máximo por defecto es de 10 intentos por ventana de 60 segundos, y al superarse la persona ve el mensaje `RATE_LIMITED` con indicación de espera. Los límites son configurables y sus valores de desarrollo viven solo en la configuración de ejemplo.
- RNF-2. **Tiempo de espera con el proveedor.** Ninguna llamada al proveedor supera 5 segundos y el conjunto del intento no supera 10 segundos; al agotarse, el intento falla de forma cerrada con `GOOGLE_UNAVAILABLE` y sin escribir datos. No hay reintentos automáticos más allá de uno.
- RNF-3. **Sin conectividad con Google.** Con el proveedor inaccesible, el inicio de sesión con correo y contraseña sigue funcionando y ninguna sesión existente se ve afectada; solo falla la vía de Google, con `GOOGLE_UNAVAILABLE`.
- RNF-4. **Respuesta del proveedor.** Tras el canje y antes de cualquier escritura se admite como máximo 8 KiB de respuesta; solo se leen los campos admitidos —identificador de cuenta, correo, correo verificado y nombre—, cualquier otro campo se descarta y no se registra, y una respuesta mayor, mal formada o con campos admitidos ausentes se rechaza con `GOOGLE_IDENTITY_INVALID`.
- RNF-5. **Valores transitorios.** El código de autorización, el valor de estado y la prueba de identidad no se persisten, no se registran, no se filtran por `Referer` ni quedan en el historial como valor reutilizable: se consumen una sola vez, su presencia en la dirección de retorno se limita a la del proveedor y a su consumo inmediato, y no se reutilizan en peticiones posteriores. El destino de retorno es un dato distinto: puede contener el token de una invitación, se guarda en el servidor asociado al estado solo mientras dura el intento, se consume una sola vez, no se envía al proveedor, no se registra ni se filtra por `Referer`, y su aparición en la barra de direcciones y en el historial es la misma que al abrir el enlace de invitación, aceptada como riesgo conocido.
- RNF-6. **Cookies y sesión.** La sesión sigue entregándose solo por la cookie de sesión existente, marcada HttpOnly, SameSite y Secure fuera de desarrollo; la sesión no se expone en cuerpos de respuesta ni en direcciones, y no se almacena ningún token del proveedor.
- RNF-7. **Secretos.** El secreto del cliente de Google nunca llega al navegador ni se registra; no se introducen secretos nuevos por defecto en el repositorio y, fuera de desarrollo, la configuración existente sigue rechazando valores por defecto conocidos.
- RNF-8. **Atomicidad por operación.** La cuenta con su identidad se crea en una sola operación; la organización con el derecho de dueño se crea en otra; la sesión se emite solo al final, tras todas las validaciones. Un intento fallido no deja filas parciales y no revierte lo que ya estaba confirmado: tras un identificador ocupado, la cuenta y la sesión siguen existiendo.
- RNF-9. **Compatibilidad de contrato.** Un cliente que ignore la funcionalidad de Google mantiene el comportamiento actual del registro, el acceso con contraseña, el cierre de sesión y la revalidación de sesión; el retiro del camino anterior de acceso con Google es un cambio de contrato observable que se comunica en la documentación y produce un rechazo con código estable, no una sesión; el resto de rechazos añade código aditivo y conserva el mensaje de texto.
- RNF-10. **Accesibilidad y cobertura de idioma.** La opción de Google, la pantalla de vinculación y la pantalla de organización son alcanzables y operables solo con teclado, su estado de espera y sus errores se anuncian a lectores de pantalla, y todos los textos nuevos —incluido el catálogo completo— existen en español y en inglés con paridad de claves.
- RNF-11. **Invariante de identidad única.** La unicidad de la identidad se garantiza en el almacenamiento y se verifica con intentos simultáneos, no con una comprobación previa. Si existieran datos históricos que incumplan el invariante, no se corrigen ni se fusionan automáticamente: el intento afectado falla de forma cerrada con `GOOGLE_IDENTITY_INVALID`, la cuenta conserva la identidad que ya tenía y la anomalía se revisa de forma manual sin registrar datos personales.
- RNF-12. **Verificación.** Todo requisito funcional de esta spec queda cubierto por pruebas automatizadas; las que necesitan base de datos real se ejecutan de forma opt-in y, si no se ejecutan, se declaran como no ejecutadas. El proveedor externo se simula en las pruebas, lo que se declara expresamente, y la comprobación contra un cliente de Google real se hace de forma manual.

## Datos personales y privacidad

- **Qué se almacena al crear una cuenta con Google:** correo, nombre completo (recortado según RF-12) y el identificador estable de cuenta de Google. Nada más.
- **Qué se almacena al vincular una cuenta local existente:** solo el identificador estable de cuenta de Google. El correo de Google no se almacena porque la cuenta ya tiene su propio correo, y el nombre de Google no reemplaza el nombre de la cuenta.
- **Una sola vez:** el correo y el nombre se toman del proveedor en el momento de crear la cuenta y no se resincronizan en inicios de sesión posteriores. Un cambio de correo en la cuenta de Google no reescribe el correo almacenado.
- **Qué no se almacena:** tokens de acceso o de actualización del proveedor, foto, idioma, zona horaria, nombre alternativo, lista de contactos, ni el estado de verificación del correo (se usa durante la validación y se descarta). Tampoco se almacenan el código de autorización ni el valor de estado.
- **Quién los ve:** la propia persona sobre su cuenta; el nombre completo en el listado de miembros de su organización, con las reglas ya existentes; el correo y el nombre en la administración de plataforma, que ya los muestra y sigue separada y auditada. El correo no se expone a otras organizaciones.
- **Qué se expone públicamente:** nada. Ninguna superficie pública muestra correo, nombre de cuenta, identidad de Google ni la existencia de una vinculación. La única revelación es la del mensaje de cuenta existente, limitada a quien controla una cuenta de Google con ese correo verificado, y se declara como riesgo aceptado.
- **Retención y borrado:** la vinculación vive mientras exista la cuenta; esta spec no introduce borrado de identidad ni de cuenta (fuera de alcance).
- **Minimización:** no se pide ningún permiso de Google más allá de la identidad básica, y no se guarda nada que no se use para autenticar o para mostrar el nombre de una cuenta recién creada.

## Casos límite

1. **Correo verificado de una cuenta local activa con contraseña:** no hay vinculación automática (RF-15); se muestra `ACCOUNT_EXISTS_PASSWORD` y, si la persona lo decide, entra con su contraseña y vincula desde la pantalla de vinculación (RF-18, RF-33).
2. **Correo verificado de una cuenta sin contraseña:** rechazo cerrado (RF-17) con `ACCOUNT_EXISTS_GOOGLE_ONLY`; no se elige cuenta, no se vincula y no se crea otra.
3. **Identidad ya vinculada a otra cuenta:** rechazo con `LINK_IDENTITY_TAKEN` sin cambios en ninguna de las dos (RF-19).
4. **Correo que coincide con más de una cuenta:** no puede ocurrir por la unicidad de correo; si los datos llegaran inconsistentes, el intento falla de forma cerrada con `GOOGLE_IDENTITY_INVALID`, no se elige ninguna cuenta y la anomalía se registra sin datos personales para revisión manual.
5. **Cuenta desactivada, con identidad o sin ella:** aviso genérico `ACCOUNT_DISABLED` por cualquier vía (RF-11, RF-16); no se reactiva y no se distingue si tiene contraseña.
6. **Identidad sin cuenta resoluble:** la identidad no sobrevive a la cuenta; si apareciera una referencia sin cuenta, el intento falla de forma cerrada con `GOOGLE_IDENTITY_INVALID` y no crea una cuenta nueva con ese correo en el mismo intento.
7. **Segunda identidad de Google sobre una cuenta que ya tiene una:** rechazo con `GOOGLE_ALREADY_LINKED` (RF-14); no se sustituye la existente y no se fusiona nada. Si la identidad presentada es la misma que ya estaba vinculada, el intento es idempotente y no cambia nada.
8. **Cambio de correo en la cuenta de Google:** la identidad se reconoce por su identificador estable, el correo almacenado no se reescribe y no se crea ni fusiona ninguna cuenta (RF-20, RF-21).
9. **Dos primeras entradas simultáneas con la misma identidad:** una sola cuenta y una sola identidad (RF-13, RF-22, RNF-11).
10. **Dos primeras entradas simultáneas con el mismo correo verificado y distinta cuenta de Google:** una sola cuenta; el segundo intento no crea duplicado y recibe `ACCOUNT_EXISTS_GOOGLE_ONLY`.
11. **Proveedor caído o lento:** falla cerrado con `GOOGLE_UNAVAILABLE`; el acceso con contraseña sigue operativo (RNF-2, RNF-3).
12. **Estado ausente, repetido, de otro navegador o caducado:** rechazo con `GOOGLE_STATE_INVALID` sin sesión (RF-6); un intento nuevo invalida el anterior.
13. **Persona que cancela el consentimiento:** vuelve al acceso con `GOOGLE_CANCELLED` (RF-7).
14. **Nombre del proveedor ausente, vacío o demasiado largo:** se aplica la regla de reserva y el recorte de RF-12; el alta nunca falla por el nombre.
15. **Identificador de organización ocupado en el paso opcional:** rechazo con `ORGANIZATION_SLUG_TAKEN` que afecta solo a ese paso; la cuenta y la sesión siguen existiendo y el reintento no repite Google (RF-24).
16. **Sesión previa del mismo navegador:** se sustituye por la nueva, no se reutiliza (RF-27); la de otros dispositivos no se toca.
17. **Vinculación desde una cuenta solo-Google:** no aplica, porque ya tiene su identidad; la pantalla no ofrece vincular y, si se intenta, se rechaza con `GOOGLE_ALREADY_LINKED` (RF-14, RF-33).
18. **Cuenta sin contraseña que intenta entrar con contraseña:** error genérico de credenciales (RF-30).
19. **Google deshabilitado después de que alguien abriera la pantalla de acceso:** el retorno no se acepta y no se crea nada (RF-1, `GOOGLE_UNAVAILABLE`).
20. **Destino de retorno con un token de invitación:** el destino se captura al iniciar y se guarda en el servidor asociado al estado, nunca en la dirección de retorno del proveedor; al volver se redirige una sola vez a la invitación y el token aparece en la barra de direcciones —y queda en el historial— igual que al abrir el enlace original. No se registra en trazas ni se filtra por `Referer`. Es un riesgo aceptado y conocido, coherente con el enlace de invitación que ya existe; si el destino caduca o no es válido, se aplica el destino por defecto (RF-9, RNF-5).
21. **Persona que abandona la pantalla de organización:** no se crea ninguna organización y mantiene intactas la cuenta y la sesión ya resueltas, ve el aviso de «sin organización activa» y puede retomar el paso más tarde (RF-23).

## Fuera de alcance

- Proveedores distintos de Google (Microsoft, Apple, SAML, LDAP) y acceso con Google Workspace restringido por dominio.
- Varias identidades de Google por cuenta: cada cuenta admite exactamente una.
- Actualización del correo almacenado desde Google, o cualquier sincronización del perfil (foto, nombre, idioma) después del alta.
- Recuperación, establecimiento o cambio de contraseña para cualquier cuenta: las cuentas creadas con Google quedan solo-Google y no obtienen contraseña en esta spec.
- Desvincular una identidad de Google y borrar cuentas o datos personales.
- Crear organizaciones adicionales para una sesión que ya tiene al menos una, y fusionar o migrar cuentas duplicadas existentes.
- Verificación por la plataforma del correo de las cuentas locales.
- Segundo factor, verificación en dos pasos y autenticación sin contraseña por correo.
- Cambios en la administración de plataforma, en la auditoría de plataforma o en las invitaciones.
- Imágenes y escudos de equipos, que se tramitan en la spec 014.

## Criterios de finalización

Cada criterio indica el requisito que lo respalda y el tipo de evidencia que lo demuestra: **A** = prueba automatizada con el proveedor simulado, **B** = prueba automatizada con base de datos real (opt-in), **C** = comprobación manual documentada.

1. **Cobertura.** Los RF-1 a RF-33 y los RNF-1 a RNF-12 están cubiertos, y cada requisito cita al menos una prueba o una comprobación manual. Las pruebas con base real se ejecutan o se declaran no ejecutadas. *(A, B)*
2. **Alta con Google.** Una persona sin cuenta entra con Google, obtiene cuenta, identidad y sesión (RF-12) y, si la sesión no tiene organización, llega a la pantalla opcional sin que se cree ninguna organización automáticamente; quien ya tenía cuenta o identidad no vuelve a crear cuenta, identidad ni sesión (RF-10, RF-23). *(RF-10, RF-12, RF-13, RF-23, RF-26, RF-27; A, B)*
3. **Organización opcional.** Con datos explícitos, la organización se crea con esa persona como dueña; al abandonar el paso se conserva la cuenta y la sesión con el aviso de «sin organización activa»; con el identificador ocupado se rechaza solo ese paso y el reintento no repite Google; una sesión con organización no ve la pantalla. *(RF-23, RF-24, RF-25; A, B)*
4. **Asociación conservadora.** Ninguna cuenta local con contraseña queda vinculada a Google sin que la persona inicie sesión con su contraseña y lo confirme desde su propia sesión; la comparación de correo no distingue mayúsculas. *(RF-15, RF-18; A, B)*
5. **Identidad única y no fusión.** Una cuenta no queda con dos identidades, una identidad no queda en dos cuentas, ninguna operación fusiona cuentas y los datos históricos que incumplan el invariante fallan de forma cerrada sin corrección automática. *(RF-13, RF-14, RF-19, RF-21, RNF-11; B)*
6. **Cuenta desactivada.** El aviso es genérico por cualquier vía, incluida una cuenta local desactivada sin identidad de Google, y no revela el motivo ni si tiene contraseña. *(RF-11, RF-16; A, B)*
7. **Sin concesión de permisos ni organizaciones por defecto.** Iniciar sesión con Google no cambia membresías, roles, permisos ni acceso entre organizaciones. *(RF-26; A, B)*
8. **Fallos limpios y sin filtraciones.** Un intento fallido, cancelado, caducado o con el proveedor caído no deja filas parciales, no persiste ni registra los valores transitorios del proveedor y no los filtra por `Referer` ni al historial. *(RNF-4, RNF-5, RNF-8; A, con revisión de los registros y de las direcciones producidas)*
9. **Retiro del camino anterior.** No existe ninguna otra forma de acceso o alta con Google: un cliente que presente una prueba de identidad directamente recibe un rechazo con código estable y no una sesión, y la documentación declara el cambio de contrato. *(RF-3, RNF-9; A, C)*
10. **Cambio de esquema obligatorio.** El invariante de identidad única se garantiza en el almacenamiento; el cambio se verifica sobre una base nueva y sobre una ya existente, y la unicidad se comprueba con intentos simultáneos. *(RF-13, RNF-11; B)*
11. **Comprobación manual declarada.** El alta y la vinculación se prueban una vez contra un cliente de Google real en un entorno de desarrollo y se documenta el resultado, porque las pruebas automatizadas simulan el proveedor. El job `e2e` **no** es evidencia de esta funcionalidad: no cubre Google. *(A, C)*
12. **Privacidad y límites medibles.** Ninguna superficie pública expone correo, nombre de cuenta ni vinculación; el catálogo no incluye tokens ni identificadores del proveedor; los límites de intentos, tiempos de espera y tamaño de la respuesta del proveedor se verifican con valores medibles. *(RNF-1, RNF-2, RNF-4, RNF-6, RNF-10; A, C)*
13. **CI y documentación.** Pasan los jobs aplicables (`backend`, `frontend`, `infrastructure` y `security`) y la documentación afectada queda actualizada, incluido el retiro del camino anterior. *(RNF-9, RNF-10; A, C)*
14. **Retorno a la invitación.** Una persona que inicia sesión con Google desde una invitación vuelve a esa invitación en una sola redirección y puede aceptarla sin abrir el enlace de nuevo; el token no aparece en la dirección de retorno del proveedor, no se registra y no se filtra por `Referer`; su presencia en la barra de direcciones y en el historial es la del enlace original y se acepta; un destino ausente, caducado o no válido cae en el destino por defecto. *(HU-8, RF-9, RNF-5; A, con revisión de las direcciones y los registros producidos)*

## Dudas abiertas

Ninguna: las decisiones de producto pendientes quedaron resueltas y están incorporadas en los requisitos, las definiciones, los casos límite, el catálogo y el alcance.
