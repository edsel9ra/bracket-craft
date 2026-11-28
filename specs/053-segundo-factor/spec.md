# Spec 053 — Segundo factor TOTP (F18)

Estado: borrador. Pedida por el usuario el 2026-11-28 («continúa con la P4»). F18 es la primera función del bloque P4 de `docs/informe-funciones-adicionales.md`.

## Contexto y objetivo

Hoy se puede entrar con correo y contraseña o con Google (013); una cuenta creada solo con Google no tiene contraseña. Ambas vías dan una sesión revocable. La recuperación y el cambio de contraseña (039) no inician sesión y ya tienen reglas propias de revocación. Los roles de propietario y administrador se conceden por organización; el acceso de plataforma es independiente y se audita por separado.

**Objetivo:** exigir una segunda prueba, independiente de la credencial de entrada, para proteger las cuentas con acceso administrativo. La persona configura una aplicación autenticadora y puede volver a entrar si pierde el dispositivo, según la política de recuperación que se apruebe. No cambian las membresías, los permisos ni lo que se publica.

## Usuarios

- Propietarios y administradores de organizaciones.
- Personal con acceso a la administración de plataforma, incluido soporte con acceso de solo lectura.
- Otros titulares de cuenta, si la política aprobada les permite activar el segundo factor (DA-1).

## Roles y visibilidad

- **Público (sin sesión):** puede iniciar sesión como hoy, pero no consultar si una cuenta existe, tiene segundo factor o tiene acceso administrativo.
- **Titular de la cuenta:** ve y gestiona únicamente el estado de su propio segundo factor. El factor pertenece a la cuenta, no a la organización activa.
- **Propietario y administrador de organización:** además de gestionar su propio factor si les corresponde, conservan sus permisos cuando cumplen la política de acceso (DA-1). Ninguna organización ve ni modifica el factor o los códigos de sus miembros, ni los datos de autenticación de otra organización.
- **Administración de plataforma:** el segundo factor no concede acceso de plataforma ni permisos de escritura a soporte. La administración y su auditoría siguen separadas de las organizaciones; no se concede acceso a secretos de otras cuentas.

## Historias de usuario

- HU-1. Como administrador, quiero confirmar un código de mi aplicación al entrar para que robar mi contraseña no baste para acceder a mis funciones administrativas.
- HU-2. Como titular que entra con Google, quiero saber cómo completar la verificación sin crear una contraseña si mi cuenta no la tiene.
- HU-3. Como titular que perdió el dispositivo, quiero saber cómo recuperar el acceso sin que el correo de recuperación de contraseña se convierta en una forma de saltar el segundo factor.
- HU-4. Como titular, quiero reemplazar un dispositivo o desactivar el factor cuando esté permitido, sin dejar otras sesiones con acceso que ya no corresponda.

## Definiciones

- **TOTP:** código temporal de una sola aceptación, generado por una aplicación autenticadora a partir de un secreto de la cuenta y la hora.
- **Verificación pendiente:** prueba de la primera credencial aceptada, de vigencia limitada y ligada a la cuenta y al intento que la obtuvo. No es una sesión autenticada.
- **Código de recuperación:** credencial de reserva de un solo uso que, si DA-2 la admite, puede acreditar el segundo factor, pero nunca sustituye la primera credencial.

## Requisitos funcionales

### Activación y gestión

- **RF-001.** CUANDO un titular elegible inicie la configuración después de volver a acreditar su primera credencial, EL SISTEMA le mostrará un QR y una clave para configurar manualmente la aplicación, solo durante esa configuración. No activará el factor hasta validar un TOTP generado con la clave nueva.
- **RF-002.** SI la configuración caduca, se cancela o recibe un código incorrecto, ENTONCES EL SISTEMA no activará el factor pendiente; si se estaba reemplazando uno activo, ese factor seguirá vigente.
- **RF-003.** MIENTRAS a una cuenta se le exija TOTP y no haya completado su activación, EL SISTEMA le permitirá completar la configuración sin conceder el acceso sujeto a esa exigencia (DA-1). Esto se aplica también a cuentas existentes y cuando se adquiere un rol que exige el factor, incluso en una sesión ya abierta.
- **RF-004.** CUANDO el titular pida desactivar o reemplazar el factor, EL SISTEMA exigirá una primera credencial recién acreditada y una prueba del factor vigente o la vía de recuperación aprobada (DA-2, DA-4). Si la política exige el factor, permitirá reemplazarlo, pero no dejar la cuenta sin protección. Al confirmar el reemplazo, invalidará el factor anterior y sus códigos de recuperación, si los había.

### Inicio de sesión

- **RF-005.** CUANDO una cuenta con factor activo presente su contraseña válida o complete una entrada con Google a la que aplique el segundo paso (DA-3), EL SISTEMA pedirá el código sin emitir una sesión autenticada. No admitirá la verificación pendiente para leer o modificar datos privados, operar en el Workspace, entrar a la administración de plataforma ni abrir una conexión privada de tiempo real.
- **RF-006.** CUANDO se presente un TOTP válido y aún no aceptado para una verificación pendiente vigente, EL SISTEMA revalidará la cuenta y la vigencia de la prueba inicial, consumirá el intento y emitirá la sesión habitual con los permisos ya concedidos. Si DA-2 admite un código de recuperación, su consumo y el uso exitoso del intento serán indivisibles.
- **RF-007.** SI el código es incorrecto, caducado o ya aceptado, o si la verificación pendiente falta, caducó, ya se usó o se presenta fuera del intento de origen, ENTONCES EL SISTEMA rechazará el acceso sin emitir sesión ni distinguir la causa en el mensaje.
- **RF-008.** EL SISTEMA conservará el límite y el 401 genérico del acceso local inválido. Verificará la contraseña incluso cuando la cuenta no exista, esté desactivada o no tenga contraseña, sin revelar el estado del factor antes de validar la primera credencial.
- **RF-009.** EL SISTEMA limitará por IP y por cuenta los intentos de comprobar el segundo factor, incluso al iniciar verificaciones nuevas. Al agotar el límite responderá 429 con tiempo de espera; si no puede aplicar el límite o comprobar el factor, fallará cerrado y no emitirá sesión.
- **RF-010.** EL SISTEMA conservará la asociación explícita de cuentas de la 013: no vinculará por coincidencia de correo, no creará una contraseña para cuentas solo-Google y no emitirá una sesión al vincular una identidad. La vía Google seguirá sujeta a DA-3 y no permitirá eludir un requisito de acceso administrativo.

### Recuperación, sesiones y avisos

- **RF-011.** CUANDO la política permita emitir códigos de recuperación, EL SISTEMA los mostrará al titular únicamente al generarlos, no podrá volver a mostrarlos y aceptará cada código una sola vez. Si se emite un conjunto nuevo, invalidará todo el anterior; para regenerarlo exigirá las mismas pruebas de identidad que para reemplazar el factor.
- **RF-012.** CUANDO se complete la recuperación o el cambio de contraseña (039), EL SISTEMA conservará la configuración TOTP y sus reglas de acceso y aplicará la revocación de sesiones ya establecida por la 039. Las verificaciones pendientes basadas en la contraseña anterior dejarán de servir.
- **RF-013.** CUANDO se active, desactive o sustituya un factor, EL SISTEMA aplicará la política de revocación aprobada (DA-4) también a las conexiones privadas en su siguiente revalidación. Ningún intento pendiente podrá acreditar un factor que ya no esté vigente.
- **RF-014.** CUANDO se active, desactive, sustituya o recupere un factor, o se utilice un código de recuperación, EL SISTEMA registrará fecha, identificador de cuenta y clase de acción, sin credenciales. Los eventos de autenticación de la cuenta no serán visibles en la auditoría organizacional (041); cualquier intervención de plataforma aprobada se auditará en la auditoría de plataforma.
- **RF-015.** EL SISTEMA mostrará en ES/EN, en tema claro y oscuro, el estado del factor, la configuración pendiente, los rechazos y la vía de recuperación aprobada. La configuración manual y la entrada del código serán utilizables solo con teclado y sin depender del QR.

## Requisitos no funcionales

- **RNF-001 (custodia).** El secreto TOTP se protege cifrado en reposo; los códigos de recuperación se conservan solo en una forma no reversible. No se guardan secretos en el repositorio ni se aceptan valores de desarrollo por defecto fuera de desarrollo.
- **RNF-002 (concurrencia).** Dos envíos concurrentes del mismo TOTP para la misma cuenta y el mismo intervalo, del mismo código de recuperación o del mismo intento pendiente no pueden completar dos verificaciones. La activación o sustitución nunca deja dos factores vigentes.
- **RNF-003 (aislamiento).** El estado y las credenciales del factor son privados de la cuenta. Se mantienen el aislamiento por organización y RLS, la separación de plataforma y las protecciones vigentes de sesión; no se añade ningún dato al acceso público.
- **RNF-004 (accesibilidad).** Las pantallas nuevas se comprueban con teclado y axe en ambos temas, tanto en escritorio como a 390 px.

## Datos personales y privacidad

- **Datos involucrados:** identificador de cuenta, estado del factor, secreto TOTP, verificadores de códigos de recuperación si se ofrecen y metadatos mínimos de auditoría.
- **Quién los ve:** el titular ve el estado y recibe el material de configuración o recuperación solo cuando se genera. Ni las organizaciones ni el personal de plataforma obtienen los secretos de otra cuenta.
- **Lo que no se expone:** secretos, QR, códigos de entrada y recuperación y credenciales de intentos pendientes no van en direcciones, logs, auditoría ni mensajes de error. No se exponen datos de autenticación en las vistas públicas ni en la auditoría organizacional.

## Casos límite

- **CL-1.** Correo inexistente, cuenta desactivada, solo-Google o contraseña errónea: el mismo 401 del login local, sin reto (RF-008).
- **CL-2.** Código fuera de su ventana de aceptación o presentado con una verificación pendiente ajena: no se completa el acceso. Código repetido o simultáneo: no se completa una segunda sesión (RF-007, RNF-002).
- **CL-3.** Cuenta desactivada, contraseña cambiada o factor reemplazado entre el primer paso y el segundo: el intento anterior no da acceso (RF-006, RF-012, RF-013).
- **CL-4.** Alta solo-Google o acceso con Google vinculado: se aplica la política de DA-3 sin vincular por correo ni perder el destino de retorno válido de la 013.
- **CL-5.** Propietario de una organización y miembro sin privilegios de otra, o miembro de plataforma sin organización: cambiar de organización o volver a iniciar sesión por otra vía no elimina la exigencia aplicable (RF-003, RF-010).
- **CL-6.** Dispositivo perdido, códigos agotados o generación abandonada: se indica la vía aprobada sin desactivar el factor por defecto (RF-002, RF-011, DA-4).
- **CL-7.** Sesión anterior a una promoción, activación o sustitución: no conserva acceso que la política ya no permite (RF-003, RF-013).

## Fuera de alcance

- SMS, correo como segundo factor, llaves de seguridad, passkeys y «recordar este dispositivo».
- Múltiples factores TOTP activos por cuenta y políticas configurables por organización.
- Verificación de correo local (F20), gestión de varias organizaciones (F21), nuevos proveedores de identidad (F22) y cambios en la asociación o desvinculación de Google (F19).
- Cambios a los roles, al contenido público o a la auditoría organizacional de la 041.

## Criterios de finalización

1. El titular elegible activa el factor con un código válido; un QR no confirmado, una cancelación o un código erróneo no lo activa. La política aprobada bloquea el acceso administrativo sin activación cuando corresponde, también al adquirir un rol con sesión abierta (RF-001–RF-004).
2. El flujo local y el de Google según la política elegida comprueban el segundo paso en las cuentas que corresponda. Se prueban código válido, inválido, caducado, reutilizado y simultáneo, y el rechazo de intentos pendientes en HTTP privado y tiempo real (RF-005–RF-010, RNF-002).
3. Se demuestra la política elegida de recuperación y revocación con dos sesiones y con una cuenta que pierde el dispositivo. Recuperar o cambiar la contraseña no permite eludir TOTP ni cambia la revocación de la 039 (RF-011–RF-013).
4. Se verifica que el acceso público y la auditoría de otra organización no muestran datos del factor, que los secretos no aparecen en registros y que los roles de plataforma conservan sus permisos distintos (RF-014, RNF-001, RNF-003).
5. Las pantallas se prueban en ES/EN, con teclado y axe, en ambos temas. Se actualizan README, manual, AGENTS, informe y MEMORY al implementar; pasan los checks de CI aplicables, incluido E2E (RF-015, RNF-004).

## Dudas abiertas

- **DA-1. [NECESITA ACLARACIÓN] ¿A quién se le exige y a quién se le ofrece TOTP?** (a) Obligatorio para quienes tienen acceso a plataforma (administración y soporte) y para propietarios y administradores de organización antes de ejercer ese acceso; opcional para el resto (recomendada: protege tanto la plataforma como la gestión de cada organización). (b) Obligatorio solo para plataforma y opcional para todas las demás cuentas. (c) Opcional para todas las cuentas, incluidas las de plataforma.
- **DA-2. [NECESITA ACLARACIÓN] ¿Se entregan códigos de recuperación?** (a) Diez códigos aleatorios de un solo uso al activar o regenerar el conjunto (recomendada: permite guardar copias fuera del dispositivo y recuperar el acceso sin depender de soporte). (b) Cinco códigos aleatorios de un solo uso, con las mismas reglas de emisión. (c) No se entregan códigos de recuperación.
- **DA-3. [NECESITA ACLARACIÓN] ¿Cómo se aplica TOTP al acceso con Google?** (a) Google acredita solo el primer paso; si el factor está activo, se pide TOTP antes de emitir sesión, tanto para cuentas vinculadas como solo-Google (recomendada: ninguna vía de entrada reduce la protección elegida). (b) Mientras el factor esté activo, una cuenta vinculada con contraseña solo puede entrar con contraseña y TOTP; las cuentas solo-Google entran con Google y TOTP. (c) Google puede dar acceso limitado sin TOTP; exige el código antes de entrar a las áreas administrativas protegidas.
- **DA-4. [NECESITA ACLARACIÓN] ¿Qué sesiones se revocan y cómo se recupera el acceso al perder el dispositivo?** (a) Al activar, desactivar o reemplazar el factor se cierran todas las sesiones, incluida la actual. Si se ofrecen códigos de recuperación, la primera credencial y un solo código permiten iniciar el reemplazo del factor perdido; sin código no hay desbloqueo automático ni asistido en esta spec (recomendada: no queda una sesión previa y ni el correo ni una petición a soporte sustituyen al segundo factor). (b) Se conserva solo la sesión actual, si se verificó de nuevo al realizar el cambio; la pérdida se trata como en (a). (c) Se cierran todas las sesiones y, si no hay códigos disponibles, se habilita una recuperación excepcional de plataforma con comprobación de identidad y auditoría, sin entregar los secretos existentes.
