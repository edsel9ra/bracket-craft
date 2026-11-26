# Spec 049 — Roles por torneo (F7)

Estado: borrador, sin dudas abiertas. Pedida por el usuario el 2026-11-26 («Sigamos con F7 y luego pasemos a PDF»).

## Contexto y objetivo

Hoy la autorización es RBAC por organización: cada miembro tiene un rol (dueño, administrador, operador, árbitro u observador) que vale para todos los torneos. La única delegación más pequeña es por partido: un miembro asignado como oficial en un partido (`match_officials`) puede operarlo y cerrarlo.

Por eso, para que alguien opere los partidos de un solo torneo hay dos salidas, y ninguna sirve: darle un rol de organización, que le deja operar todos los torneos, o asignarlo como oficial partido a partido.

La spec 006 retiró la tabla `tournament_user_roles`, que existía sin uso, y dejó los roles por torneo fuera de alcance. El informe de funciones adicionales los registra como F7: asignar operadores o árbitros a un torneo concreto, sin dar acceso a toda la organización.

Lo que ya existe y se reutiliza: los roles y permisos de la organización, la asignación de oficiales por partido, la autorización del tiempo real por recurso (035) y la auditoría organizacional (041).

**Objetivo:** que un dueño o administrador pueda delegar en un miembro la operación de los partidos de un torneo concreto, sin darle permisos en el resto de torneos de la organización.

## Usuarios

- Dueños y administradores de organizaciones con varios torneos a la vez, cada uno con su propio equipo de mesa.
- Miembros que operan los partidos de un solo torneo.

## Roles y visibilidad

- **Público (sin sesión):** sin cambios.
- **Dueño y administrador:** asignan y retiran roles por torneo en los torneos de su organización, en «Equipo del torneo» (DA-3).
- **Operador del torneo:** además de lo que le da su rol de organización, en los partidos de ese torneo ve el borrador en vivo, lo opera y cierra el acta (DA-1). En el resto de torneos, nada cambia.
- **Resto de miembros:** sin cambios. Siguen viendo todos los torneos (DA-2) y pueden ver quién es operador de cada uno.
- **Administrador de plataforma:** sin cambios.

## Historias de usuario

- HU-1. Como administrador, quiero dar a un miembro el rol de operador del torneo para que opere sus partidos sin tocar los de otros torneos.
- HU-2. Como administrador, quiero ver y retirar los roles por torneo para mantener al día quién opera cada torneo.
- HU-3. Como operador de un torneo, quiero operar en vivo y cerrar las actas de sus partidos sin que me asignen partido a partido.
- HU-4. Como dueño, quiero que cada asignación y retirada quede en la auditoría.

## Definiciones

- **Rol por torneo:** la asignación de un miembro activo de la organización a un torneo de esa organización con un rol del catálogo de roles por torneo. El catálogo tiene un solo rol, «operador del torneo» (DA-1).
- **Permisos efectivos en un partido:** la unión de los permisos del rol de organización del miembro, los de su asignación como oficial de ese partido y los de su rol en el torneo del partido.

## Requisitos funcionales

### Catálogo

- **RF-001.** EL SISTEMA ofrecerá un catálogo cerrado de roles por torneo con un único rol, «operador del torneo», que concede en los partidos de ese torneo ver el borrador en vivo, operarlo y cerrar el acta (DA-1).
- **RF-001a.** EL SISTEMA no concederá al operador del torneo ninguna acción de gestión del torneo: reglas, equipos, plantillas, calendario, oficiales, publicación, rectificaciones, sanciones ni auditoría.
- **RF-002.** EL SISTEMA tratará los roles por torneo como aditivos: nunca quitarán permisos que el miembro ya tenga por su rol de organización o por estar asignado a un partido.

### Asignación

- **RF-003.** CUANDO un dueño o administrador asigne un rol por torneo a un miembro activo de su organización, EL SISTEMA lo registrará y lo aplicará desde la siguiente petición del miembro.
- **RF-003a.** SI un miembro que no es dueño ni administrador intenta asignar o retirar un rol por torneo, ENTONCES EL SISTEMA lo rechazará sin cambiar nada.
- **RF-003b.** CUANDO se asigne el rol a un miembro cuyo rol de organización ya concede esos permisos, EL SISTEMA permitirá la asignación y avisará de que no añade permisos (DA-4).
- **RF-004.** CUANDO un dueño o administrador retire un rol por torneo, EL SISTEMA dejará de aplicarlo desde la siguiente petición del miembro y en la siguiente autorización del tiempo real.
- **RF-005.** SI se intenta asignar un rol por torneo a un miembro inactivo, a un usuario de otra organización o en un torneo de otra organización, ENTONCES EL SISTEMA lo rechazará con el mismo error que un miembro o torneo inexistente.
- **RF-006.** SI se asigna a un miembro un rol que ya tiene en ese torneo, ENTONCES EL SISTEMA no creará una asignación duplicada.
- **RF-007.** MIENTRAS un miembro esté desactivado, EL SISTEMA no le aplicará ningún rol por torneo.

### Autorización

- **RF-008.** CUANDO un operador del torneo actúe sobre un partido de ese torneo, EL SISTEMA le autorizará ver el borrador en vivo, operarlo y cerrar el acta (DA-1) con las mismas reglas de estado y versión que hoy.
- **RF-008a.** EL SISTEMA no cambiará qué torneos, partidos o datos puede leer un miembro por tener o no un rol por torneo (DA-2).
- **RF-009.** CUANDO ese miembro actúe sobre un partido o un torneo distinto, EL SISTEMA aplicará solo su rol de organización y sus asignaciones de partido.
- **RF-010.** EL SISTEMA aplicará los roles por torneo también en la autorización privada del tiempo real (035/036): un miembro con rol en el torneo recibe los avisos del borrador en vivo de sus partidos, y deja de recibirlos al retirarle el rol, sin repetir lo ya enviado.
- **RF-011.** EL SISTEMA aplicará el aislamiento por RLS a los roles por torneo: ninguna organización puede ver, asignar ni usar roles en torneos de otra.

### Consulta y auditoría

- **RF-012.** EL SISTEMA mostrará los roles por torneo de cada torneo en su sección «Equipo del torneo» del Workspace (DA-3), visible para cualquier miembro y editable solo por dueño y administrador.
- **RF-012a.** EL SISTEMA ofrecerá en el Workspace del partido las acciones de operación y cierre al operador del torneo de ese partido, igual que hoy a un operador de organización.
- **RF-013.** CUANDO se asigne o retire un rol por torneo, EL SISTEMA lo registrará en la auditoría organizacional (041) con el torneo, el miembro y el rol.

## Requisitos no funcionales

- **RNF-001.** Sin campos públicos nuevos ni cambios en la proyección pública.
- **RNF-002.** Los textos nuevos están en ES y EN. La gestión se puede usar con teclado y pasa axe en ambos temas.
- **RNF-003.** Retirar un rol con confirmación y sin doble ejecución si se pulsa dos veces.

## Datos personales y privacidad

- Una asignación relaciona un miembro con un torneo. Solo la ven los miembros de la organización; no se publica.
- La auditoría guarda el miembro y el rol, sin el correo.

## Casos límite

1. Un miembro con rol de organización «operador» y además operador en un torneo: la asignación no cambia nada, pero se muestra.
2. Un miembro retirado del torneo a mitad de un partido en vivo: su siguiente comando se rechaza y deja de recibir el borrador (RF-004, RF-010).
3. Un torneo archivado conserva sus asignaciones, pero no admite operación, como hoy.
4. Un miembro desactivado y reactivado recupera sus roles por torneo (RF-007).
5. El último dueño no se ve afectado: los roles por torneo no tocan los roles de organización.
6. Un miembro con roles en varios torneos los tiene por separado.

## Fuera de alcance

- Cambiar los roles de organización o sus permisos.
- Restringir la lectura de torneos a un miembro (DA-2).
- Un «administrador del torneo» u otros roles por torneo (DA-1).
- Roles por torneo para rectificaciones (033), sanciones (034), webhooks (047) o exportaciones (048).
- Notificaciones específicas para los roles por torneo.
- Roles por fase o por partido nuevos; la asignación de oficiales por partido no cambia.

## Criterios de finalización

- Un dueño o administrador asigna y retira roles por torneo en el Workspace, con auditoría.
- Un miembro con rol en un torneo opera sus partidos y no los de otro torneo, en HTTP y en tiempo real.
- Tests con PostgreSQL que prueban el aislamiento entre organizaciones y entre torneos.
- README, AGENTS, manual e informe documentan el nuevo modelo de autorización.

## Decisiones

Respondidas por el usuario el 2026-11-26.

- **DA-1 = (a). Solo «operador del torneo».** En los partidos de ese torneo concede lo mismo que hoy el operador de organización: ver el borrador en vivo (`VIEW_MATCH_LIVE_DRAFT`), operarlo (`OPERATE_MATCH_LIVE`) y cerrar el acta (`CLOSE_MATCH_REPORT`). No gestiona el torneo: ni reglas, ni equipos, ni plantillas, ni calendario, ni oficiales, ni publicación.
- **DA-2 = (a). La lectura no cambia.** El miembro sigue viendo todos los torneos de la organización, como hoy; el rol por torneo solo amplía lo que puede hacer en ese torneo.
- **DA-3 = (a). Dueño y administrador, en «Equipo del torneo».** La gestión está en una sección «Equipo del torneo» dentro de cada torneo del Workspace.
- **DA-4 = (a). Cualquier miembro activo.** Si su rol de organización ya da esos permisos, se avisa de que la asignación no añade nada, pero se permite.
