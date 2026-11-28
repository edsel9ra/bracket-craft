# Spec 053 — Verificación del correo (F20)

Estado: borrador. Pedida por el usuario el 2026-11-28 («Empieza por F20»). Corresponde a F20 del bloque P4 de `docs/informe-funciones-adicionales.md`; la spec 013 dejó fuera la verificación por la plataforma del correo de las cuentas locales.

## Contexto y objetivo

Hoy el registro local guarda el correo indicado, crea una organización para la cuenta y abre una sesión sin confirmar el buzón. Las invitaciones prueban posesión de un enlace, pero no necesariamente del buzón: quien gestiona la invitación también recibe su enlace. Google exige que el proveedor confirme el correo al validar la identidad; esa afirmación no se guarda y nunca vincula por sí sola una cuenta local. La recuperación de contraseña (039) ya envía un enlace de un solo uso por correo, pero completar ese flujo no registra una verificación. Las notificaciones de la 046 envían correos al buzón registrado solo por elección del titular.

**Objetivo:** permitir que la persona confirme que controla el correo de su cuenta local y que la plataforma distinga ese estado del mero registro de una dirección. La verificación no cambia los roles ni las membresías y no abre una sesión por sí sola. No cambia lo que se publica.

## Usuarios

- Titular de una cuenta local nueva o existente, incluida una cuenta creada mediante invitación.
- Titular de una cuenta con Google, cuando corresponda reconocer la prueba del proveedor (DA-2).

## Roles y visibilidad

- **Público (sin sesión):** no puede consultar el estado de un correo ni pedir que se envíe una verificación a un correo elegido por él. Puede abrir la pantalla del enlace y acceder a su cuenta para completarlo.
- **Titular de la cuenta:** puede ver el estado de su propio correo, pedir otro enlace si está pendiente y confirmar el que recibió. Las restricciones de acceso se aplican según DA-1.
- **Miembros y administradores de organización:** no pueden consultar ni modificar el estado de verificación de otra cuenta, dentro o fuera de su organización. Una invitación no concede acceso a ese estado.
- **Administración de plataforma:** no obtiene acciones para verificar manualmente cuentas ni nuevos datos en su interfaz. Si se elige una intervención de plataforma en DA-4 se mantiene separada y auditada, y no sustituye la prueba de control del buzón.

## Historias de usuario

- HU-1. Como titular de una cuenta local, quiero confirmar mi correo para que la plataforma sepa que puedo recibir mensajes allí.
- HU-2. Como titular que no recibió el enlace o lo dejó caducar, quiero pedir otro desde mi cuenta sin crear una cuenta duplicada.
- HU-3. Como titular con notificaciones activadas, quiero que los avisos por correo se entreguen conforme a la política mientras mi buzón está pendiente, sin perder mi acceso a la verificación ni los avisos de la bandeja.

## Definiciones

- **Cuenta local:** cuenta con contraseña, haya vinculado o no Google.
- **Correo verificado:** dirección actual cuya posesión se acreditó con una prueba aceptada por la política de esta spec. La comparación de direcciones no distingue mayúsculas. Una excepción de transición (DA-2) no equivale a acreditar el buzón.
- **Enlace de verificación:** prueba aleatoria de uso único y vigencia limitada, emitida para una cuenta, su dirección actual y solo para confirmar ese correo; no es un enlace de invitación ni de recuperación de contraseña.

## Requisitos funcionales

### Estado y compatibilidad

- **RF-001.** CUANDO se registre una cuenta local directamente, EL SISTEMA conservará la creación inicial de cuenta y organización y el 409 existente para correo o identificador en conflicto. Si el registro se confirma, dejará el correo pendiente y pondrá en cola un primer envío sin esperar al servicio de correo. La cuenta tendrá acceso a la verificación aun si DA-1 limita sus demás funciones.
- **RF-002.** EL SISTEMA aplicará a las cuentas existentes, las altas por invitación y las cuentas con Google la política de pruebas de DA-2. La antigüedad, la coincidencia de un correo, una invitación o una identidad histórica no se registrarán como una confirmación que no ocurrió.
- **RF-003.** CUANDO se use Google, EL SISTEMA mantendrá las reglas de la 013: comprobará que el proveedor declara verificado su correo, no vinculará por mera coincidencia, no cambiará el correo guardado ni creará una contraseña para una cuenta solo-Google. Si DA-2 acepta la prueba de Google para una cuenta local, solo la reconocerá tras un acceso con una identidad ya vinculada o una vinculación explícita exitosa, con una prueba vigente del proveedor para la dirección actual de esa cuenta.
- **RF-004.** MIENTRAS el correo esté pendiente, EL SISTEMA aplicará la restricción aprobada en DA-1 también en el servidor y a las sesiones vigentes. Mantendrá el acceso a la pantalla de verificación y reenvío para el titular autenticado, y no revelará el estado antes de validar las credenciales. El 401 genérico del login local, la verificación de contraseña y su límite de intentos no cambian.

### Emisión y confirmación

- **RF-005.** CUANDO la política exija un primer envío para una cuenta nueva o el titular autenticado pida otro enlace desde su cuenta pendiente activa, EL SISTEMA enviará el enlace únicamente a la dirección registrada, sin aceptar un destinatario proporcionado por el solicitante. Si ya está verificada, no emitirá ni enviará otro enlace.
- **RF-006.** CUANDO emita un enlace nuevo, EL SISTEMA invalidará las pruebas anteriores pendientes para esa cuenta y aplicará la vigencia de DA-3. El mensaje indicará qué confirma, cuándo caduca y qué hacer si no se solicitó; el destino será el sitio oficial configurado para el entorno, no el indicado por la petición.
- **RF-007.** CUANDO se abra un enlace, EL SISTEMA mostrará el paso de confirmación sin cambiar el estado ni consumir el enlace. Solo después de una acción explícita del titular autenticado de la cuenta destinataria, con enlace vigente y dirección aún coincidente, registrará la verificación. No modificará la contraseña, la sesión ni las membresías.
- **RF-008.** SI el enlace falta, es inválido, caducó, se usó, fue reemplazado, corresponde a otra cuenta o dirección, o la cuenta ya no está activa, ENTONCES EL SISTEMA no confirmará el correo y mostrará el mismo rechazo genérico sin indicar a qué cuenta pertenecía.
- **RF-009.** EL SISTEMA aplicará límites al reenvío por cuenta e IP y a los intentos de confirmación por IP y enlace, sin revelar el estado a terceros. Al superar el límite responderá 429 con tiempo de espera; si el limitador no puede aplicarse, responderá 503 sin emitir ni confirmar una prueba. La frecuencia de reenvío por cuenta depende de DA-3.
- **RF-010.** SI el envío del correo de confirmación falla, ENTONCES EL SISTEMA lo reintentará de forma acotada, mantendrá el estado pendiente y no revertirá un registro ya confirmado. Un trabajo atrasado no enviará un enlace para una cuenta desactivada, un correo ya verificado o una dirección que no sea la actual.

### Otros flujos y experiencia

- **RF-011.** EL SISTEMA mantendrá separados los enlaces de invitación, de recuperación de contraseña (039) y de confirmación de correo. Ninguno se aceptará en un flujo ajeno; recuperar o cambiar la contraseña no marcará el correo como verificado ni cambiará las reglas de revocación de sesiones de la 039.
- **RF-012.** CUANDO la política elegida limite notificaciones por correo, EL SISTEMA comprobará la verificación al entregar los avisos de la 046 y omitirá ese envío si no se cumple. No cambiará la preferencia guardada ni la entrega en la bandeja. La verificación no habilitará una preferencia de correo desactivada ni reenviará avisos omitidos por ese motivo. Los correos de confirmación y de la 039 no dependen de esa preferencia.
- **RF-013.** EL SISTEMA mostrará en la cuenta si el correo está pendiente o verificado, el reenvío cuando proceda y los resultados de confirmación en ES/EN, con teclado, en los temas claro y oscuro. No añadirá edición de la dirección salvo que se apruebe en DA-4; si se aprueba, la dirección nueva no sustituirá a la actual antes de probar su control.
- **RF-014.** CUANDO se confirme el correo mediante una prueba admitida, EL SISTEMA invalidará los enlaces pendientes de la cuenta y conservará fecha y origen de la prueba junto al estado de la cuenta, sin registrar el enlace ni su código en la auditoría. El estado de verificación no aparecerá en la auditoría organizacional.

## Requisitos no funcionales

- **RNF-001 (secreto de un solo uso).** Se almacena solo un verificador no reversible del código; el secreto aleatorio ofrece al menos 256 bits. Dos confirmaciones simultáneas del mismo enlace solo pueden producir una confirmación efectiva.
- **RNF-002 (independencia del correo).** Registrar la cuenta o pedir otro enlace no espera a que se entregue el mensaje. El fallo de entrega no modifica los permisos ni impide volver a solicitar el enlace conforme a la política.
- **RNF-003 (aislamiento).** Se preservan la separación de plataforma y el aislamiento por organización, incluido RLS si se consultan datos de un tenant. No se introducen credenciales en el repositorio ni defaults de desarrollo fuera de desarrollo.
- **RNF-004 (accesibilidad).** Las pantallas nuevas se comprueban con teclado y axe, en ambos temas y a 390 px y escritorio.

## Datos personales y privacidad

- **Datos involucrados:** dirección ya registrada, identificador de cuenta, estado, fecha y origen de la confirmación. Los intentos se retienen solo el tiempo necesario para impedir usos fuera de su vigencia.
- **Quién los ve:** solo el titular obtiene el estado desde su cuenta. El correo de verificación se entrega únicamente a la dirección que se quiere confirmar y no contiene datos de organizaciones ni de jugadores.
- **Lo que no se expone:** ni la dirección ni el enlace de confirmación se incluyen en registros, auditorías de organizaciones, respuestas de error o vistas públicas. El secreto no se transmite en el referente ni se incluye en direcciones recibidas por servicios de terceros.

## Casos límite

- **CL-1.** Conflicto de registro por correo o identificador, incluida una solicitud concurrente: el intento fallido no genera una cuenta adicional ni un envío de verificación (RF-001).
- **CL-2.** Invitación legítima o reenviada que se acepta con una cuenta nueva o existente: la pertenencia se rige por la invitación; la verificación del buzón, por DA-2 (RF-002).
- **CL-3.** Google afirma otra dirección o no la declara verificada: no sustituye ni confirma la dirección guardada; se conserva el resultado de acceso o vinculación previsto por la 013 (RF-003).
- **CL-4.** Navegación con otra cuenta, enlace vencido o reemplazado, doble confirmación o escáner de enlaces del correo: no confirma la cuenta incorrecta ni se consume por abrir la página (RF-007–RF-008, RNF-001).
- **CL-5.** Servicio de correo caído o mensajes entregados fuera de orden: el estado sigue pendiente hasta una prueba válida y solo el último enlace vigente puede confirmarlo (RF-006, RF-010).
- **CL-6.** Correo pendiente con avisos activados, o verificado con avisos desactivados: se conserva la elección del titular y los canales se aplican de acuerdo con DA-1 (RF-012).
- **CL-7.** Cuenta desactivada con un enlace pendiente o intento de usar un enlace de contraseña como verificación: no se registra una prueba (RF-008, RF-011).

## Fuera de alcance

- Crear o desvincular proveedores, segundo factor (F18), borrado o exportación de datos (F19) y cambios al modelo de organizaciones (F21).
- Verificar correos de contacto ajenos a cuentas, usar verificación por SMS o gestionar rebotes de correo.
- Nuevos métodos de inicio de sesión o cambios a las preferencias por defecto de notificación, la visibilidad pública o los permisos organizacionales.

## Criterios de finalización

1. Se prueban el alta local, el conflicto 409, la cuenta existente, la aceptación por invitación y Google con direcciones coincidentes y distintas según DA-2 (RF-001–RF-003).
2. Con un correo pendiente se demuestra qué operaciones se permiten y cuáles se impiden según DA-1, incluida la entrega de un aviso con correo activado y la bandeja sin cambios (RF-004, RF-012).
3. Se comprueban la confirmación explícita, caducidad, reenvío, límites, cuenta incorrecta, desactivación, concurrencia y fallo de envío, sin fuga de secretos ni cambios de sesión (RF-005–RF-011, RNF-001–RNF-003).
4. Se prueba la decisión sobre el cambio de correo y se revisan privacidad, auditoría y accesibilidad en ES/EN y en ambos temas (RF-013–RF-014, RNF-004).
5. Al implementar se actualizan README, manual, AGENTS, informe y MEMORY. Pasan los checks de CI aplicables, incluido E2E.

## Dudas abiertas

- **DA-1. [NECESITA ACLARACIÓN] ¿Qué se restringe mientras el correo esté pendiente?** (a) Solo la entrega de avisos opcionales por correo de la 046; se mantiene el acceso al Workspace y a la bandeja (recomendada: evita enviar avisos a un buzón no confirmado sin bloquear la gestión si falla el correo). (b) Lo anterior y el envío de invitaciones de organización desde esa cuenta. (c) Todo acceso privado salvo el área de cuenta necesaria para verificar o reenviar, tras validar las credenciales.
- **DA-2. [NECESITA ACLARACIÓN] ¿Qué pruebas o excepciones se aceptan para cuentas existentes, invitadas y con Google?** (a) Las locales existentes sin prueba y las nuevas por invitación quedan pendientes; solo se reconoce un enlace de confirmación o la prueba vigente de Google para la dirección actual de una cuenta creada con Google o vinculada explícitamente (recomendada: ni la antigüedad ni una invitación compartible prueban control del buzón). (b) Igual que (a), pero las cuentas locales existentes quedan exentas de las restricciones, sin marcarlas como verificadas. (c) Las cuentas locales siempre deben confirmar por correo, incluso con Google vinculado; solo se acepta la prueba de Google para cuentas solo-Google, con dirección coincidente.
- **DA-3. [NECESITA ACLARACIÓN] ¿Cuánto dura un enlace y cuándo puede pedirse otro?** (a) Dura 24 horas desde su emisión; máximo tres solicitudes de reenvío por cuenta en 24 horas, con al menos cinco minutos entre envíos solicitados (recomendada: da margen para abrir el correo sin facilitar envíos repetidos). (b) Dura una hora y conserva esos límites de reenvío. (c) Dura 48 horas y admite hasta cinco solicitudes de reenvío por cuenta en 24 horas, con al menos cinco minutos entre envíos solicitados.
- **DA-4. [NECESITA ACLARACIÓN] ¿Se incluye el cambio de correo de una cuenta existente?** (a) No: se confirma la dirección registrada y el cambio queda para otra spec (recomendada: hoy no hay edición de correo y cambiarlo afecta al acceso, la recuperación y la vinculación con Google). (b) Sí, autoservicio con nueva acreditación de la cuenta y confirmación en los buzones anterior y nuevo. (c) Sí, mediante un procedimiento excepcional de plataforma, con comprobación de identidad, confirmación del buzón nuevo y auditoría.
