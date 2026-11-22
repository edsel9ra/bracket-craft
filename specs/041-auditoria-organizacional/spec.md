# Spec 041 — Auditoría organizacional visible (F5)

Estado: borrador

## Contexto y objetivo

La organización ya registra en su auditoría interna las acciones sensibles: cierre de actas, W.O., interrupción de segmentos, planillas y formaciones, oficiales asignados, escudos, cambios de rol y de estado de miembros, invitaciones reabiertas y aceptadas, rectificaciones, procedimientos de impacto competitivo, casos de sanción, comandos del partido en vivo y avance entre fases. Ninguna pantalla ni endpoint permite consultarla: las specs 008, 009 y 011 lo dejaron fuera de alcance de forma explícita y el informe de funciones adicionales lo recoge como F5.

F5 añade una **consulta de solo lectura** de esa auditoría, dentro del Workspace, paginada y con filtros, para que la organización pueda responder «quién hizo qué y cuándo» sin acceso a la base de datos. No crea entradas nuevas, no cambia qué se registra y no permite editar ni borrar nada.

Relación con la constitución: §2.1–2.2 (la lectura corre con el aislamiento por organización de la base de datos), §2.7 (la auditoría de plataforma sigue separada en `/admin`) y §3.4 (la auditoría no contiene datos personales de jugadores). No requiere enmienda.

## Usuarios

- Propietarios y administradores de una organización.

## Roles y visibilidad

- **Público:** no ve nada.
- **Miembro de organización sin permiso de auditoría:** no ve la sección ni puede consultarla (403).
- **Usuario con permiso de auditoría de la organización:** consulta las entradas de su organización activa. Quién recibe el permiso por defecto: ver DA-1.
- **Administrador de plataforma:** sin acciones nuevas; su auditoría propia sigue en `/admin`. Las decisiones que tomó dentro de una organización (rectificaciones y sanciones con autorización expresa) ya están en la auditoría de esa organización y se muestran en ella (ver RF-006).
- Ninguna organización ve las entradas de otra.

## Historias de usuario

- HU-1. Como propietario, quiero ver la lista de acciones registradas en mi organización, de la más reciente a la más antigua, para saber quién cambió qué.
- HU-2. Como propietario, quiero filtrar por tipo de acción, por responsable y por rango de fechas, para encontrar una acción concreta.
- HU-3. Como propietario, quiero abrir una entrada y ver su detalle legible, para entender el cambio sin leer JSON.

## Definiciones

- **Entrada de auditoría:** registro existente de la organización con tipo de acción, entidad afectada, responsable, fecha y contenido.
- **Responsable:** el miembro de la organización que ejecutó la acción o, si la ejecutó un administrador de plataforma con autorización expresa, la administración de plataforma.
- **Catálogo de acciones:** lista cerrada de tipos de acción que la consulta conoce, cada uno con su etiqueta ES/EN y los campos de detalle que puede mostrar.

## Requisitos funcionales

- **RF-001.** CUANDO un usuario con permiso de auditoría consulte la auditoría, EL SISTEMA devolverá las entradas de su organización activa ordenadas por fecha descendente y, a igualdad, por identificador descendente, en páginas de 1 a 100 entradas (50 por defecto).
- **RF-002.** SI quien consulta no pertenece a la organización activa o no tiene permiso de auditoría, ENTONCES EL SISTEMA responderá 403 sin devolver ninguna entrada ni revelar si existen.
- **RF-003.** EL SISTEMA solo devolverá entradas de la organización activa; ninguna otra organización puede ver ni filtrar entradas ajenas, tampoco indicando identificadores de otra organización en los filtros (en ese caso la página sale vacía).
- **RF-004.** CUANDO se indiquen filtros, EL SISTEMA aplicará en conjunción: tipo de acción (uno o varios del catálogo), responsable (un miembro de la organización) y rango de fechas (desde/hasta, inclusivos, en UTC). Ver DA-3 para el filtro por torneo.
- **RF-005.** SI un filtro tiene un valor fuera del catálogo, una fecha inválida, un rango invertido o un tamaño de página fuera de límites, ENTONCES EL SISTEMA responderá 422 sin ejecutar la consulta.
- **RF-006.** EL SISTEMA mostrará por entrada: fecha, etiqueta de la acción, tipo e identificador de la entidad afectada y responsable (nombre del miembro, o «Administración de plataforma» sin correo ni identidad del administrador).
- **RF-007.** CUANDO se abra el detalle de una entrada, EL SISTEMA mostrará solo los campos de contenido que el catálogo declara para esa acción (ver DA-2), con etiquetas ES/EN; nunca correos, tokens, enlaces, documentos ni fechas de nacimiento.
- **RF-008.** SI una entrada tiene un tipo de acción que no está en el catálogo, ENTONCES EL SISTEMA la listará con la etiqueta «Acción no catalogada» y su código, sin mostrar contenido.
- **RF-009.** EL SISTEMA no permitirá crear, editar ni borrar entradas desde esta consulta; consultarla no genera entradas nuevas.
- **RF-010.** CUANDO no haya entradas que cumplan los filtros, EL SISTEMA mostrará un estado vacío que lo indique, distinto de un error de carga.
- **RF-011.** EL SISTEMA mostrará la sección de auditoría en la navegación del Workspace solo a quien tenga el permiso de auditoría.

## Requisitos no funcionales

- **RNF-001.** Una página se obtiene con un número de consultas acotado e independiente del número de entradas de la organización.
- **RNF-002.** Todas las lecturas corren con RLS de la organización activa; la aplicación no elude RLS.
- **RNF-003.** Pantalla en ES/EN, accesible (tabla navegable por teclado, detalle en diálogo con foco gestionado) y correcta en los temas claro y oscuro, a 1440 y 390 px.
- **RNF-004.** El contrato de la respuesta rechaza campos no declarados, como el resto de la API.

## Datos personales y privacidad

- Se muestra el **nombre** del miembro responsable a quien tiene permiso de auditoría de esa misma organización; no se muestra su correo.
- Los administradores de plataforma aparecen solo como «Administración de plataforma».
- Las entradas actuales guardan identificadores, códigos y contadores; algunas guardan **texto libre escrito por miembros** (motivo de W.O., notas de interrupción, motivos de rectificación y de sanción). Si se muestran o no: DA-2.
- Nada de esto es público.

## Casos límite

- CL-1. Miembro responsable desactivado o retirado después de la acción: la entrada sigue mostrando su nombre.
- CL-2. Entrada de una acción de plataforma con autorización expresa: responsable «Administración de plataforma».
- CL-3. Volumen alto de comandos del partido en vivo (una entrada por comando): se filtran por tipo de acción como cualquier otra.
- CL-4. Entidad afectada borrada o inaccesible: la entrada se muestra con su identificador, sin enlace.
- CL-5. El usuario cambia de organización activa con la pantalla abierta: la lista se vacía y se recarga para la nueva organización, sin mezclar entradas.
- CL-6. Entradas añadidas mientras se pagina: el orden por fecha e identificador evita duplicar o saltar entradas ya mostradas al pedir la página siguiente con el mismo filtro (ver plan).

## Fuera de alcance

- Exportar la auditoría (F10).
- Notificaciones sobre entradas de auditoría (F6).
- Consultar `platform_audit_logs` desde el Workspace.
- Registrar acciones que hoy no se registran o cambiar el contenido de las existentes.
- Retención, archivado o purga de la auditoría.
- Búsqueda de texto libre dentro del contenido.

## Criterios de finalización

- RF-001–RF-011 y RNF-001–RNF-004 verificados con pruebas de backend (incluidas dos organizaciones y RLS), frontend y E2E del flujo HU-1–HU-3.
- README, AGENTS y manual de usuario describen la sección y su permiso.
- CI completa en verde y aceptación expresa del usuario.

## Dudas abiertas

- [NECESITA ACLARACIÓN] **DA-1. Quién consulta por defecto.** (a) Propietario y administrador, con un permiso nuevo y específico de auditoría (recomendada); (b) solo propietario; (c) cualquier miembro activo, incluido «viewer».
- [NECESITA ACLARACIÓN] **DA-2. Contenido del detalle.** (a) Lista cerrada de campos por acción, incluidos los motivos y notas en texto libre (recomendada: el motivo es la razón de ser de la auditoría y ya lo escriben miembros de la misma organización); (b) lista cerrada sin texto libre; (c) el contenido completo tal como está guardado.
- [NECESITA ACLARACIÓN] **DA-3. Filtro por torneo.** (a) No en esta spec: tipo, responsable y fechas (recomendada; no todas las entradas guardan el torneo y habría que derivarlo por entidad); (b) sí, derivando el torneo desde la entidad afectada.
- [NECESITA ACLARACIÓN] **DA-4. Enlace a la entidad.** (a) Enlace a la pantalla del Workspace cuando la entidad es un partido, equipo o caso de sanción que el usuario puede abrir (recomendada); (b) solo identificador, sin enlaces.
