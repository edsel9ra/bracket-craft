# Spec 046 — Notificaciones (F6)

Estado: borrador (2026-11-24). Pedida por el usuario el 2026-11-24 («Acepto la 045, fusiona los PR y empieza F6»).

## Contexto y objetivo

Hoy los miembros de una organización solo se enteran de lo que pasa en sus torneos si abren el Workspace. Los únicos avisos que existen son los de casos concretos de gobierno: la decisión de una rectificación al solicitante (033) y los avisos de expedientes de sanción (034). No hay avisos de la operación ordinaria, ni forma de elegir cómo recibirlos, ni de integrar a terceros.

Las specs 016, 020 y 022 dejaron fuera las «notificaciones, correo o webhooks», y el informe de funciones adicionales las registra como F6: avisos de partido programado, resultado confirmado, W.O. y sanción, salidos del outbox (§3.2), con preferencias por usuario y webhooks firmados por organización.

Lo que ya existe y se reutiliza: el outbox y su worker con reintentos, el envío de correo por SMTP y el patrón de avisos internos con revalidación del destinatario en la entrega (034). Los únicos datos de contacto del sistema son los correos de las cuentas de usuario: los equipos y los jugadores no tienen correo.

**Objetivo:** que cada miembro reciba, por los canales que elija, los avisos de los hechos relevantes de los torneos de su organización, y que la organización pueda enviarlos a sistemas propios mediante webhooks firmados.

## Usuarios

- Miembros de la organización (owner, administrador, operador, árbitro, observador), que reciben los avisos.
- Administrador de organización, que configura los webhooks.
- Sistemas externos de la organización, que reciben los webhooks.

## Roles y visibilidad

- **Público (sin sesión):** no aplica. No recibe avisos ni ve nada nuevo.
- **Miembro de organización (incluido observador):** recibe en la bandeja de la app los avisos de su organización y elige sus canales en sus preferencias. Solo ve sus propios avisos y preferencias.
- **Administrador de organización:** además, da de alta, prueba, desactiva y elimina los webhooks de su organización y consulta sus entregas. Necesita un permiso nuevo y específico, que tienen owner y administrador.
- **Administrador de plataforma:** sin cambios. No ve avisos ni webhooks de ninguna organización.

## Historias de usuario

- HU-1. Como operador, quiero recibir un aviso cuando se confirme el resultado de un partido de mi organización, sin tener que abrir el Workspace.
- HU-2. Como miembro, quiero elegir qué avisos recibo y por qué canal (app o correo), para no recibir correo que no quiero.
- HU-3. Como administrador, quiero registrar un webhook firmado, para que el sistema de mi club o federación reciba los resultados al momento y pueda comprobar que vienen de Bracket Craft.
- HU-4. Como miembro, quiero una bandeja con mis avisos recientes en el Workspace, marcados como leídos o no leídos.

## Definiciones

- **Tipo de aviso:** uno de un catálogo cerrado: partido programado, resultado confirmado, W.O. declarado y sanción generada (RF-001).
- **Canal:** bandeja de la app, correo o webhook. Los dos primeros son por miembro; el webhook es por organización.
- **Webhook:** una URL HTTPS de la organización a la que el sistema envía cada aviso de los tipos que tenga suscritos, firmado con un secreto compartido.
- **Entrega:** cada intento de enviar un aviso por un canal a un destinatario o a un webhook, con su resultado.

## Requisitos funcionales

### Catálogo y origen

- **RF-001.** EL SISTEMA tendrá un catálogo cerrado de tipos de aviso:
  - **Partido programado:** se crean partidos con fecha en un torneo, por generación de calendario o alta manual ([NECESITA ACLARACIÓN] DA-3).
  - **Resultado confirmado:** se cierra el acta de un partido con resultado deportivo.
  - **W.O. declarado:** se cierra un partido por walkover.
  - **Sanción generada:** el cierre de un acta genera una suspensión ([NECESITA ACLARACIÓN] DA-4).
- **RF-002.** CUANDO ocurra un hecho del catálogo, EL SISTEMA registrará sus avisos y los encolará en el outbox dentro de la misma transacción que el hecho. El envío lo hace el worker, nunca la petición. Si la transacción se revierte, no queda ningún aviso.
- **RF-003.** EL SISTEMA no cambiará los avisos existentes de la 033 (decisión de rectificación) ni de la 034 (expedientes de sanción). Siguen sus reglas, sus destinatarios y sus pantallas.

### Destinatarios y preferencias

- **RF-004.** CUANDO se registre un aviso, EL SISTEMA lo dirigirá a los miembros activos de la organización del torneo, según sus preferencias ([NECESITA ACLARACIÓN] DA-2). Nunca a miembros de otra organización ni a usuarios sin membresía activa.
- **RF-005.** EL SISTEMA permitirá a cada miembro activar o desactivar, por tipo de aviso, la bandeja y el correo de su organización activa. Solo él puede ver y cambiar sus preferencias.
- **RF-006.** CUANDO el worker vaya a entregar un aviso por la bandeja o por correo, EL SISTEMA volverá a comprobar que el destinatario sigue siendo miembro activo de la organización y que mantiene ese canal activado, como hace la 034. Si no se cumple, no lo entregará y lo registrará como no entregado, sin reintentarlo.

### Bandeja de la app

- **RF-007.** EL SISTEMA mostrará en el Workspace una bandeja con los avisos entregados al miembro en su organización activa, del más reciente al más antiguo, paginada, con su tipo, fecha, torneo y partido, y un enlace a la pantalla correspondiente. Marcará cuántos hay sin leer.
- **RF-008.** EL SISTEMA permitirá marcar un aviso, o todos, como leídos. Cada miembro solo lee y marca sus propios avisos.

### Correo

- **RF-009.** CUANDO se entregue un aviso por correo, EL SISTEMA enviará al correo de la cuenta un mensaje con el tipo, el torneo, el partido y un enlace al Workspace. No incluirá documentos, fechas de nacimiento ni ningún dato que la vista pública no muestre, salvo lo que fije DA-4.
- **RF-010.** SI el envío de un correo falla, ENTONCES EL SISTEMA lo reintentará con el mecanismo del outbox sin duplicar el aviso, y no revertirá el hecho que lo originó.

### Webhooks

- **RF-011.** EL SISTEMA permitirá a un miembro con el permiso de webhooks dar de alta, listar, desactivar, reactivar y eliminar webhooks de su organización, cada uno con una URL `https://` y los tipos de aviso suscritos. Ninguna otra organización puede verlos ni modificarlos ([NECESITA ACLARACIÓN] DA-1).
- **RF-012.** CUANDO se dé de alta un webhook, EL SISTEMA generará un secreto de firma, lo mostrará una sola vez y lo guardará cifrado. Permitirá rotarlo, mostrando el nuevo también una sola vez.
- **RF-013.** CUANDO se entregue un aviso a un webhook, EL SISTEMA enviará un `POST` JSON con el tipo, un identificador de entrega único, la fecha y los identificadores de organización, torneo y partido, firmado con HMAC-SHA256 sobre la marca de tiempo y el cuerpo. Solo incluirá campos de la proyección pública, más el estado privado del aviso.
- **RF-014.** SI la URL resuelve a una dirección privada, de loopback, de enlace local o de metadatos, o el destino responde con una redirección, ENTONCES EL SISTEMA no completará la entrega y la registrará como rechazada, sin seguir la redirección.
- **RF-015.** SI el destino no responde con 2xx en el tiempo límite, ENTONCES EL SISTEMA reintentará con espera creciente un número máximo de veces y después la marcará como fallida. El administrador podrá consultar las últimas entregas de cada webhook con su resultado y enviar un aviso de prueba.

### Aislamiento y auditoría

- **RF-016.** EL SISTEMA aislará avisos, preferencias, webhooks y entregas por organización con RLS. Ninguna organización puede ver, modificar ni deducir los de otra.
- **RF-017.** CUANDO se dé de alta, modifique, rote, desactive o elimine un webhook, EL SISTEMA lo registrará en la auditoría de la organización (041), sin el secreto ni la URL completa.

## Requisitos no funcionales

- **RNF-001.** Sin campos públicos nuevos ni cambios en la proyección pública.
- **RNF-002.** Un SMTP lento o un webhook caído no retrasan el tiempo real ni los demás avisos.
- **RNF-003.** El secreto de los webhooks nunca aparece en logs, auditoría, respuestas posteriores al alta ni en el repositorio. Las variables nuevas solo llevan valores por defecto en `.env.example`.
- **RNF-004.** Textos nuevos en ES y EN. La bandeja, las preferencias y la gestión de webhooks son accesibles con teclado y pasan axe en ambos temas.

## Datos personales y privacidad

- Se usan los correos de las cuentas de los miembros, que solo ven ellos.
- Los avisos de la bandeja y del correo solo contienen datos que el miembro ya puede ver en el Workspace. DA-4 decide si una sanción nombra al jugador.
- Los webhooks solo llevan identificadores y datos de la proyección pública. Nunca nombres de jugadores sin ficha pública autorizada, documentos ni fechas de nacimiento.

## Casos límite

1. Un miembro que pierde la membresía entre el hecho y la entrega no recibe el aviso (RF-006).
2. Un partido cerrado que después se rectifica no genera un segundo «resultado confirmado»: los avisos de la rectificación siguen la 033.
3. Generar un calendario de muchos partidos no inunda la bandeja ni el correo (DA-3).
4. Un hecho de un torneo en borrador o archivado se notifica igual que en uno publicado, salvo que DA-3 diga otra cosa.
5. Un webhook desactivado o eliminado no recibe entregas nuevas; las pendientes se descartan.
6. Una URL que pasa a resolver a una IP privada después del alta se rechaza en la entrega (RF-014).
7. Sin SMTP configurado, el correo se registra como fallido y se reintenta, como en la 034; la bandeja funciona igual.

## Fuera de alcance

- Avisos a equipos, jugadores o al público: no tienen cuenta ni correo.
- Notificaciones push del navegador o móviles, SMS y mensajería instantánea.
- Avisos de partido en vivo (gol, tarjeta) y recordatorios previos a un partido.
- Cambiar los avisos de la 033 y la 034 o moverlos a la bandeja nueva.
- Plantillas de correo personalizables por la organización.
- Webhooks de plataforma o entre organizaciones.

## Criterios de finalización

| # | Criterio | RF |
|---|---|---|
| 1 | Cada hecho del catálogo registra sus avisos en la misma transacción y el worker los entrega. | RF-001, RF-002 |
| 2 | Preferencias por tipo y canal, solo del propio miembro, revalidadas en la entrega. | RF-004–RF-006 |
| 3 | Bandeja paginada con no leídos y marcado. | RF-007, RF-008 |
| 4 | Correo mínimo con reintento sin duplicar. | RF-009, RF-010 |
| 5 | Webhooks HTTPS firmados con HMAC, secreto mostrado una vez, protección SSRF, reintentos y prueba. | RF-011–RF-015 |
| 6 | Aislamiento por RLS y auditoría de webhooks sin secretos. | RF-016, RF-017 |
| 7 | ES/EN, teclado y axe en ambos temas. | RNF-004 |

## Dudas abiertas

- [NECESITA ACLARACIÓN] **DA-1. Alcance de esta spec.** ¿Bandeja, correo y webhooks en una sola spec, o bandeja y correo aquí y los webhooks en la 047?
- [NECESITA ACLARACIÓN] **DA-2. Valores por defecto.** ¿Qué recibe un miembro que no ha tocado sus preferencias?
- [NECESITA ACLARACIÓN] **DA-3. «Partido programado».** ¿Un aviso por partido o uno por cada generación de calendario o alta?
- [NECESITA ACLARACIÓN] **DA-4. Contenido del aviso de sanción.** ¿Nombra al jugador sancionado?
