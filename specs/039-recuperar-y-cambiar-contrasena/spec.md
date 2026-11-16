# Spec 039 — Recuperar y cambiar la contraseña

Estado: borrador; DA-1–DA-4 decididas por el usuario el 2026-11-16, pendiente de aprobación

Fecha: 2026-11-16. Corresponde a F3 del informe de funciones adicionales (`docs/informe-funciones-adicionales.md`, tabla §3 y corto plazo §6). La spec 013 dejó expresamente fuera de alcance la recuperación, el establecimiento y el cambio de contraseña.

## Contexto y objetivo

Hoy una cuenta local entra con correo y contraseña, pero no existe ninguna vía para recuperar una contraseña olvidada ni para cambiarla desde la propia cuenta. Quien la olvida pierde el acceso al Workspace hasta que alguien intervenga a mano.

El objetivo es ofrecer:

1. **Recuperación:** «¿Olvidaste tu contraseña?» envía al correo de la cuenta un enlace de un solo uso y caducidad corta que permite fijar una contraseña nueva.
2. **Cambio:** desde la cuenta, con sesión iniciada, cambiar la contraseña indicando la actual.

Fuentes y límites: constitución 2.0.0 (§2.6 ningún secreto por defecto fuera de desarrollo, §2.8 verificación, §3.2 efectos secundarios por outbox, §3.4 seguridad), spec 009 (invitaciones: token con hash, caducidad y un solo uso), spec 013 (cuentas solo-Google, `ACCOUNT_DISABLED`, login que no revela si la cuenta existe), auditoría A1–A3 (Argon2 en hilos, rate limit con Redis, token solo con hash).

**Compatibilidad constitucional:** no se propone enmienda. No toca datos de tenants ni proyecciones públicas.

## Usuarios

- Persona con cuenta local (correo y contraseña) que olvidó su contraseña o quiere cambiarla.
- Persona con cuenta solo-Google (013): no tiene contraseña y sigue sin tenerla; si pide la recuperación recibe un recordatorio de entrar con Google (DA-1).
- Administrador de plataforma: sin cambios en sus pantallas; una cuenta desactivada sigue sin poder entrar.

## Roles y visibilidad

- **Público (sin sesión):** puede pedir la recuperación indicando un correo y usar un enlace de recuperación recibido. Nunca sabe si el correo corresponde a una cuenta.
- **Usuario con sesión:** puede cambiar su propia contraseña. Nadie puede cambiar la contraseña de otra cuenta, tampoco un administrador de organización o de plataforma.
- **Organizaciones:** la contraseña es de la cuenta, no de una organización; ninguna organización ve ni modifica datos de autenticación de sus miembros.

## Historias de usuario

- HU-1. Como persona que olvidó su contraseña, quiero recibir un enlace en mi correo para fijar una nueva y volver a entrar.
- HU-2. Como usuario con sesión, quiero cambiar mi contraseña indicando la actual.
- HU-3. Como titular de la cuenta, quiero que un cambio de contraseña cierre las sesiones que pudieran estar abiertas por otra persona y que se me avise por correo.

## Definiciones

- **Cuenta local:** cuenta activa con contraseña.
- **Enlace de recuperación:** URL con un token aleatorio de un solo uso. Solo se guarda su hash, nunca el token.
- **Respuesta genérica:** mismo código, mismo cuerpo y tiempo de respuesta sin dependencia de que el correo exista.

## Requisitos funcionales

- **RF-001.** CUANDO alguien pida la recuperación indicando un correo, EL SISTEMA responderá siempre la misma respuesta genérica, exista o no una cuenta, esté activa o desactivada y tenga o no contraseña.
- **RF-002.** CUANDO el correo corresponda a una cuenta local activa, EL SISTEMA enviará a ese correo un enlace de recuperación que caduca a los 30 minutos (DA-3). El envío no se hace dentro de la petición: la respuesta no espera al correo.
- **RF-002b.** CUANDO el correo corresponda a una cuenta activa sin contraseña (solo-Google), EL SISTEMA no emitirá enlace y enviará a ese correo un recordatorio de que la cuenta entra con Google, sin enlaces de acción (DA-1). A una cuenta desactivada o a un correo sin cuenta no se envía nada.
- **RF-003.** CUANDO se emita un enlace nuevo para una cuenta, EL SISTEMA invalidará los enlaces anteriores de esa cuenta que sigan pendientes.
- **RF-004.** CUANDO se presente un enlace válido (no usado, no caducado, no invalidado, de una cuenta local activa) con una contraseña nueva que cumpla RF-009, EL SISTEMA fijará la contraseña nueva, marcará el enlace como usado y cerrará todas las sesiones de la cuenta (DA-2); la persona entra después con la contraseña nueva.
- **RF-005.** SI el enlace no existe, está usado, caducado o invalidado, o la cuenta ya no está activa, ENTONCES EL SISTEMA rechazará el cambio con un único error genérico «enlace no válido o caducado», sin distinguir el motivo y sin cambiar nada.
- **RF-006.** CUANDO un usuario con sesión cambie su contraseña indicando la actual correcta y una nueva que cumpla RF-009, EL SISTEMA la cambiará, cerrará todas las demás sesiones de la cuenta y mantendrá la sesión desde la que se hizo el cambio (DA-2).
- **RF-007.** SI la contraseña actual no es correcta, ENTONCES EL SISTEMA rechazará el cambio sin modificar nada, con el mismo límite de intentos que el login.
- **RF-008.** CUANDO se cambie o recupere la contraseña, EL SISTEMA invalidará todos los enlaces de recuperación pendientes de esa cuenta y enviará al correo de la cuenta un aviso de que la contraseña cambió, con la fecha y sin enlaces de acción (DA-4). Un fallo del aviso no revierte el cambio.
- **RF-009.** EL SISTEMA exigirá para la contraseña nueva la misma política que el registro (8 a 128 caracteres) y rechazará que sea igual a la actual.
- **RF-010.** EL SISTEMA limitará por IP y por correo las peticiones de recuperación, y por IP y por enlace los intentos de usarlo, con 429 y `Retry-After`; si el limitador no está disponible, fallará cerrado (503), como el login.
- **RF-011.** EL SISTEMA no incluirá el token, el enlace, la contraseña ni su hash en logs, auditorías, respuestas de error ni respuestas de la petición de recuperación, tampoco en desarrollo.
- **RF-012.** CUANDO se recupere o cambie una contraseña, EL SISTEMA lo registrará en una auditoría técnica con cuenta, tipo (recuperación o cambio) y fecha, sin el correo ni ningún secreto.
- **RF-013.** EL SISTEMA ofrecerá en el login un enlace «¿Olvidaste tu contraseña?», una pantalla para pedir la recuperación, otra para fijar la contraseña nueva desde el enlace y, en la cuenta, una pantalla para cambiarla; todas en ES/EN, accesibles y en tema oscuro y claro.

## Requisitos no funcionales

- **RNF-001 (no enumeración).** La petición de recuperación no revela, ni por contenido ni por tiempo de respuesta, si un correo tiene cuenta: no consulta Argon2 ni SMTP en la petición y responde lo mismo en todos los casos (RF-001).
- **RNF-002 (secreto del token).** El token tiene al menos 256 bits aleatorios, solo se guarda su hash y se compara por hash.
- **RNF-003 (concurrencia).** Dos usos simultáneos del mismo enlace producen como mucho un cambio de contraseña.
- **RNF-004 (coste).** Argon2 se ejecuta fuera del event loop, como en el login (A1).
- **RNF-005 (verificación).** No enumeración, un solo uso, caducidad, invalidación, revocación de sesiones y límites se verifican con pruebas automáticas. Pasan los cinco jobs de CI.

## Datos personales y privacidad

- Datos involucrados: correo de la cuenta y hash de la contraseña. No hay datos de jugadores ni nada público.
- El correo solo se usa para enviar el enlace y el aviso de DA-4; no aparece en la auditoría (RF-012) ni en logs.
- Los enlaces se conservan solo el tiempo necesario y luego se eliminan (retención acotada, como en 034).

## Casos límite

- **CL-1.** Correo inexistente, de cuenta desactivada o de cuenta solo-Google: misma respuesta genérica (RF-001); solo la cuenta solo-Google recibe el recordatorio de RF-002b.
- **CL-2.** Varias peticiones seguidas: solo el último enlace es válido (RF-003), dentro del límite de RF-010.
- **CL-3.** Cuenta desactivada entre la emisión y el uso del enlace: el enlace se rechaza (RF-005).
- **CL-4.** Contraseña cambiada desde la cuenta mientras hay un enlace pendiente: el enlace queda invalidado (RF-008).
- **CL-5.** Enlace abierto con sesión iniciada de otra cuenta: el enlace actúa sobre su propia cuenta; la sesión abierta no cambia de cuenta.
- **CL-6.** SMTP no configurado en desarrollo: la petición responde igual; el enlace no se muestra ni se registra (RF-011).
- **CL-7.** Fallo del envío del correo: no cambia la respuesta ya dada; se reintenta según el worker y no deja un enlace utilizable sin entregar más allá de su caducidad.
- **CL-8.** Mayúsculas o espacios en el correo: se compara igual que el login.

## Fuera de alcance

- Establecer contraseña en cuentas solo-Google (DA-1): siguen siendo solo-Google, como en la 013.
- Cambiar el correo de la cuenta, verificación del correo de cuentas locales y borrado de cuentas.
- Segundo factor, inicio de sesión sin contraseña por correo y preguntas de seguridad.
- Reglas de complejidad más allá de la longitud, listas de contraseñas filtradas y caducidad periódica de contraseñas.
- Que un administrador de organización o de plataforma restablezca la contraseña de otra cuenta.

## Criterios de finalización

1. La petición de recuperación responde igual para cuenta local, inexistente, desactivada y solo-Google (RF-001, RNF-001).
2. Un enlace válido fija la contraseña nueva y queda usado; reutilizarlo, usar uno caducado o uno anterior da el error genérico (RF-003–RF-005, RNF-003).
3. El cambio desde la cuenta exige la contraseña actual (RF-006, RF-007).
4. Tras recuperar o cambiar, las sesiones quedan cerradas según DA-2 (todas al recuperar, todas salvo la actual al cambiar), las de Socket.IO incluidas en su siguiente revalidación, y los enlaces pendientes invalidados (RF-008).
5. Ni el token ni la contraseña aparecen en logs, auditoría ni respuestas (RF-011, RF-012).
6. La cuenta solo-Google recibe el recordatorio y ningún enlace (RF-002b); se envía el aviso de cambio (RF-008).
7. Límites de RF-010 con 429 y 503.
8. Pantallas ES/EN, accesibles y en ambos temas (RF-013).
9. Pasan los cinco jobs de CI.

## Decisiones del usuario (2026-11-16)

- **DA-1 (a):** las cuentas solo-Google siguen sin contraseña; si piden la recuperación reciben un recordatorio de entrar con Google (RF-002b).
- **DA-2 (a):** recuperar cierra todas las sesiones; cambiar desde la cuenta cierra las demás y mantiene la actual (RF-004, RF-006).
- **DA-3 (a):** el enlace caduca a los 30 minutos (RF-002).
- **DA-4 (a):** al recuperar o cambiar la contraseña se envía un aviso sin enlaces de acción (RF-008).

## Dudas abiertas

Ninguna.
