# Spec 046 — Notificaciones en la app y por correo (F6, parte 1)

Estado: borrador (2026-11-24). DA-1–DA-4 resueltas el 2026-11-24. Pedida por el usuario el 2026-11-24 («Acepto la 045, fusiona los PR y empieza F6»).

## Decisiones del usuario (2026-11-24)

- **DA-1 = (a).** Esta spec cubre la bandeja de la app y el correo. Los webhooks firmados por organización van en una spec 047 aparte.
- **DA-2 = (a).** Un miembro que no ha tocado sus preferencias recibe todos los tipos en la bandeja. El correo está desactivado hasta que él lo active.
- **DA-3 = (a).** «Partido programado» genera un aviso por cada generación de calendario o alta, con el torneo y el número de partidos creados, no uno por partido.
- **DA-4 = (a).** El aviso de sanción nombra al jugador y el partido en la bandeja. El correo no lo nombra y enlaza al Workspace.

## Contexto y objetivo

Hoy los miembros de una organización solo se enteran de lo que pasa en sus torneos si abren el Workspace. Los únicos avisos que existen son de casos concretos de gobierno: la decisión de una rectificación al solicitante (033) y los avisos de expedientes de sanción (034). No hay avisos de la operación ordinaria ni forma de elegir cómo recibirlos.

Las specs 016, 020 y 022 dejaron fuera las «notificaciones, correo o webhooks». El informe de funciones adicionales las registra como F6: avisos de partido programado, resultado confirmado, W.O. y sanción, salidos del outbox (§3.2), con preferencias por usuario y webhooks firmados por organización. Esta spec cubre la bandeja y el correo; los webhooks quedan para la 047 (DA-1).

Lo que ya existe y se reutiliza: el outbox y su worker con reintentos, el envío de correo por SMTP y el patrón de avisos internos con revalidación del destinatario en la entrega (034). Los únicos datos de contacto del sistema son los correos de las cuentas de usuario: los equipos y los jugadores no tienen correo.

**Objetivo:** que cada miembro reciba, por los canales que elija, los avisos de los hechos relevantes de los torneos de su organización.

## Usuarios

- Miembros de la organización (owner, administrador, operador, árbitro y observador), que reciben los avisos y eligen sus canales.

## Roles y visibilidad

- **Público (sin sesión):** no aplica. No recibe avisos ni ve nada nuevo.
- **Miembro de organización (cualquier rol, incluido observador):** recibe los avisos de su organización en la bandeja y, si lo activa, por correo. Elige sus canales en sus preferencias. Solo ve sus propios avisos y preferencias. No hacen falta permisos nuevos.
- **Administrador de plataforma:** sin cambios. No ve avisos ni preferencias de ninguna organización.

## Historias de usuario

- HU-1. Como operador, quiero recibir un aviso cuando se confirme el resultado de un partido de mi organización, sin tener que abrir el Workspace.
- HU-2. Como miembro, quiero elegir qué avisos recibo y por qué canal (bandeja o correo), para no recibir correo que no quiero.
- HU-3. Como miembro, quiero una bandeja con mis avisos recientes en el Workspace, con los no leídos marcados.

## Definiciones

- **Tipo de aviso:** uno del catálogo cerrado de RF-001.
- **Canal:** bandeja de la app o correo, elegidos por cada miembro.
- **Entrega:** cada intento de llevar un aviso a un miembro por un canal, con su resultado.

## Requisitos funcionales

### Catálogo y origen

- **RF-001.** EL SISTEMA tendrá un catálogo cerrado de cuatro tipos de aviso:
  - **Partido programado:** una generación de calendario o un alta manual crea partidos en un torneo. Hay un aviso por operación, con el torneo y el número de partidos creados (DA-3).
  - **Resultado confirmado:** se cierra el acta de un partido con resultado deportivo.
  - **W.O. declarado:** se cierra un partido por walkover.
  - **Sanción generada:** el cierre de un acta genera una suspensión de jugador. Hay un aviso por suspensión.
- **RF-002.** CUANDO ocurra un hecho del catálogo, EL SISTEMA registrará sus avisos y los encolará en el outbox dentro de la misma transacción que el hecho. La entrega la hace el worker, nunca la petición. Si la transacción se revierte, no queda ningún aviso.
- **RF-003.** EL SISTEMA no cambiará los avisos de la 033 (decisión de rectificación) ni los de la 034 (expedientes de sanción): siguen sus reglas, sus destinatarios y sus pantallas. Rectificar un acta no genera un segundo «resultado confirmado».

### Destinatarios y preferencias

- **RF-004.** CUANDO se registre un aviso, EL SISTEMA lo dirigirá a los miembros activos de la organización del torneo según sus preferencias. Nunca lo dirigirá a miembros de otra organización ni a usuarios sin membresía activa.
- **RF-005.** EL SISTEMA permitirá a cada miembro activar o desactivar la bandeja y el correo para cada tipo de aviso de su organización activa. Solo él puede ver y cambiar sus preferencias.
- **RF-006.** MIENTRAS un miembro no haya guardado preferencias para un tipo, EL SISTEMA le entregará ese tipo en la bandeja y no por correo (DA-2).
- **RF-007.** CUANDO el worker vaya a entregar un aviso, EL SISTEMA volverá a comprobar que el destinatario sigue siendo miembro activo de la organización y que mantiene ese canal activado, como hace la 034. Si no se cumple, no lo entregará y lo registrará como no entregado, sin reintentarlo.

### Bandeja de la app

- **RF-008.** EL SISTEMA mostrará en el Workspace una bandeja con los avisos entregados al miembro en su organización activa. Irán ordenados del más reciente al más antiguo y paginados. Cada aviso mostrará su tipo, su fecha, el torneo y, si lo hay, el partido, con un enlace a la pantalla correspondiente. La bandeja marcará cuántos avisos quedan sin leer.
- **RF-009.** CUANDO el aviso sea de «sanción generada», EL SISTEMA mostrará en la bandeja el nombre del jugador, su equipo, el partido y el número de partidos de suspensión (DA-4). El nombre se lee al mostrarlo, no se copia en el aviso.
- **RF-010.** EL SISTEMA permitirá marcar como leído un aviso, o todos a la vez. Cada miembro solo lee y marca sus propios avisos.

### Correo

- **RF-011.** CUANDO se entregue un aviso por correo, EL SISTEMA enviará al correo de la cuenta del miembro un mensaje con el tipo, el torneo, el partido si lo hay y un enlace al Workspace. El correo no nombrará a ningún jugador (DA-4) ni incluirá documentos, fechas de nacimiento u otros datos que no aparezcan en la vista pública.
- **RF-012.** SI el envío de un correo falla, ENTONCES EL SISTEMA lo reintentará con el mecanismo del outbox, sin duplicar el aviso y sin revertir el hecho que lo originó.

### Aislamiento

- **RF-013.** EL SISTEMA aislará con RLS los avisos, las preferencias y las entregas de cada organización. Ninguna organización puede ver, modificar ni deducir los de otra, y ningún miembro puede ver los avisos ni las preferencias de otro.

## Requisitos no funcionales

- **RNF-001.** Sin campos públicos nuevos ni cambios en la proyección pública.
- **RNF-002.** Un SMTP lento o caído no retrasa el tiempo real ni la entrega en la bandeja.
- **RNF-003.** Los textos nuevos están en ES y EN. La bandeja y las preferencias se pueden usar con teclado y pasan axe en ambos temas.

## Datos personales y privacidad

- Se usan los correos de las cuentas de los miembros, y cada uno solo ve el suyo.
- La bandeja solo muestra datos que el miembro ya puede ver en el Workspace. El nombre del jugador sancionado aparece solo en la bandeja (DA-4).
- El correo no lleva nombres de jugadores, documentos ni fechas de nacimiento.

## Casos límite

1. Un miembro que pierde la membresía entre el hecho y la entrega no recibe el aviso (RF-007).
2. Un miembro que desactiva un canal después del hecho y antes de la entrega no lo recibe por ese canal (RF-007).
3. Generar un calendario de muchos partidos produce un solo aviso de «partido programado» (DA-3).
4. Una generación o un alta que no crea ningún partido no genera aviso.
5. Un cierre que genera varias suspensiones produce un aviso de sanción por cada una, además del de resultado o W.O.
6. Un miembro de varias organizaciones solo ve en la bandeja los avisos de su organización activa, y tiene preferencias separadas en cada una.
7. Sin SMTP configurado, el correo se registra como fallido y se reintenta, como en la 034. La bandeja funciona igual.
8. Un torneo o un jugador que deja de existir o se archiva después del aviso: el aviso sigue en la bandeja y el enlace lleva a la pantalla que corresponda, sin error.

## Fuera de alcance

- Webhooks firmados por organización: spec 047 (DA-1).
- Avisos a equipos, jugadores o al público, que no tienen cuenta ni correo.
- Notificaciones push del navegador o móviles, SMS y mensajería instantánea.
- Avisos durante el partido en vivo (goles, tarjetas) y recordatorios antes de un partido.
- Cambiar los avisos de la 033 y la 034 o moverlos a la bandeja nueva.
- Plantillas de correo personalizables por la organización y resúmenes periódicos.

## Criterios de finalización

| # | Criterio | RF |
|---|---|---|
| 1 | Cada hecho del catálogo registra sus avisos en la misma transacción y el worker los entrega; un calendario produce un solo aviso. | RF-001–RF-003 |
| 2 | Preferencias por tipo y canal, solo del propio miembro, con bandeja activada y correo desactivado por defecto, revalidadas en la entrega. | RF-004–RF-007 |
| 3 | Bandeja paginada con no leídos y marcado como leído; la sanción nombra al jugador solo en la bandeja. | RF-008–RF-010 |
| 4 | Correo mínimo sin nombres de jugadores, con reintento sin duplicar. | RF-011, RF-012 |
| 5 | Aislamiento por RLS entre organizaciones y entre miembros. | RF-013 |
| 6 | ES/EN, teclado y axe en ambos temas. | RNF-003 |

## Dudas abiertas

Ninguna.
