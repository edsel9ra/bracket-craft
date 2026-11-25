# Spec 047 — Webhooks firmados por organización (F6, parte 2)

Estado: aprobada por el usuario el 2026-11-24 («Apruebo la spec 046 y la enmienda de la constitución y fusiona», en respuesta a la pregunta de aprobar la 047; la 046 ya estaba aceptada). DA-1–DA-4 resueltas el 2026-11-24. Enmienda de la §3.4 (constitución 2.1.0) fusionada en el PR #126. Pedida por el usuario el 2026-11-24 («Sigue con la spec 047»), tras aceptar la 046 (DA-1 de la 046: los webhooks firmados van en una spec aparte).

## Decisiones del usuario (2026-11-24)

- **DA-1 = (a).** Un permiso nuevo, `MANAGE_WEBHOOKS`, que tienen por defecto el owner y el administrador. Ningún otro rol lo tiene.
- **DA-2 = (a).** El cuerpo lleva los identificadores y los datos públicos del hecho: el torneo, los equipos, el marcador y el número de partidos. La sanción no lleva ni el jugador ni su equipo.
- **DA-3 = (a).** El secreto se cifra con una clave propia, `WEBHOOK_SECRET_KEY`. Antes de implementar hay que enmendar la §3.4 de la constitución en un PR aparte, para añadirla a los secretos que se cambian fuera de desarrollo.
- **DA-4 = (a).** Hasta 6 intentos con espera creciente, de 1 minuto a unas 2 horas entre intentos. Se pueden consultar las últimas 50 entregas de cada webhook de los últimos 30 días. El webhook no se desactiva solo por fallar.
- **DA-5 = (a)** (2026-11-25, tras Devin Review del PR #128). Mientras el torneo no sea público, un aviso no crea entregas de webhook; la bandeja y el correo internos no cambian. Así el cuerpo nunca adelanta datos que la proyección pública aún no muestra (RF-006).

## Contexto y objetivo

La 046 dejó a cada miembro recibir en la bandeja o por correo los avisos de partido programado, resultado confirmado, W.O. declarado y sanción generada. Las organizaciones que tienen sistemas propios (la web de un club, la de una federación, una hoja de cálculo automatizada) no pueden recibir esos hechos sin consultar la API pública de forma periódica.

El informe de funciones adicionales registra F6 con «webhooks firmados por organización». Esta spec completa F6 con ese canal: la organización registra URLs HTTPS a las que el sistema envía cada aviso del catálogo de la 046, firmado para que el receptor compruebe que viene de Bracket Craft.

Lo que ya existe y se reutiliza: el catálogo de avisos y su registro en la transacción del hecho (046), el outbox y su worker con reintentos, y la auditoría de la organización (041).

**Objetivo:** que una organización reciba en sus propios sistemas, en cuanto ocurren y de forma verificable, los hechos del catálogo de la 046 de sus torneos, sin exponer nada que no sea ya público.

## Usuarios

- Owner y administradores de la organización, que configuran los webhooks.
- Sistemas externos de la organización, que reciben las entregas.

## Roles y visibilidad

- **Público (sin sesión):** no aplica. No ve webhooks ni entregas.
- **Owner y administrador de organización:** dan de alta, editan, prueban, desactivan, reactivan y eliminan los webhooks de su organización, rotan su secreto y consultan sus entregas recientes. Lo hacen con el permiso nuevo `MANAGE_WEBHOOKS`, que tienen por defecto (DA-1).
- **Resto de miembros (operador, árbitro, observador):** no ven los webhooks, sus URLs ni sus entregas.
- **Administrador de plataforma:** sin cambios. No ve webhooks ni entregas de ninguna organización.

## Historias de usuario

- HU-1. Como administrador, quiero registrar un webhook, para que la web de mi club reciba los resultados en cuanto se confirman.
- HU-2. Como responsable del sistema receptor, quiero comprobar la firma de cada entrega, para descartar las que no vienen de Bracket Craft o han sido alteradas.
- HU-3. Como administrador, quiero ver las últimas entregas de cada webhook y enviar una de prueba, para saber si mi sistema las está recibiendo.

## Definiciones

- **Webhook:** una URL `https://` de la organización, con los tipos de aviso a los que está suscrita, un estado (activo o desactivado) y un secreto de firma.
- **Secreto de firma:** valor aleatorio que comparten el sistema y el receptor. Con él se firma cada entrega.
- **Entrega:** cada envío de un aviso a un webhook, con sus intentos y su resultado final (entregada, fallida o rechazada).
- **Entrega de prueba:** una entrega de un tipo fijo de prueba, sin hecho de torneo detrás, que el administrador lanza a mano.

## Requisitos funcionales

### Gestión

- **RF-001.** EL SISTEMA permitirá a quien tenga `MANAGE_WEBHOOKS` dar de alta, listar, editar (URL y tipos suscritos), desactivar, reactivar y eliminar los webhooks de su organización activa. Ninguna otra organización puede verlos, modificarlos ni deducir que existen.
- **RF-002.** SI la URL no usa `https://`, lleva usuario o contraseña, o supera 2048 caracteres, ENTONCES EL SISTEMA rechazará el alta o la edición sin guardar nada. Una organización tendrá como máximo 10 webhooks.
- **RF-003.** CUANDO se dé de alta un webhook, EL SISTEMA generará su secreto, lo mostrará una sola vez en la respuesta del alta y lo guardará cifrado. Permitirá rotarlo; el secreto nuevo también se muestra una sola vez y el anterior deja de firmar en el acto. Ninguna otra respuesta lo devuelve. Se cifra con la clave propia `WEBHOOK_SECRET_KEY` (DA-3); sin esa clave, o con su valor de desarrollo fuera de desarrollo, el backend no arranca.
- **RF-004.** CUANDO se dé de alta, edite, rote, desactive, reactive o elimine un webhook, EL SISTEMA lo registrará en la auditoría de la organización (041) con el responsable, sin el secreto ni la ruta ni la consulta de la URL: solo su dominio.

### Entrega

- **RF-005.** CUANDO se registre un aviso del catálogo de la 046, EL SISTEMA creará en la misma transacción una entrega por cada webhook activo de la organización del torneo suscrito a ese tipo, y la encolará en el outbox. Si el torneo aún no es público, no creará ninguna (DA-5). La envía el worker, nunca la petición. Si la transacción se revierte, no queda ninguna entrega.
- **RF-006.** CUANDO el worker envíe una entrega, EL SISTEMA hará un `POST` con un cuerpo JSON que lleva el tipo, el identificador único de la entrega, la fecha del hecho, los identificadores de organización, torneo y, si lo hay, partido, y solo datos que ya aparecen en la proyección pública (DA-2):
  - **Partido programado:** el nombre del torneo y el número de partidos creados.
  - **Resultado confirmado y W.O. declarado:** el nombre del torneo, los dos equipos y el marcador final; en el W.O., también el equipo ganador.
  - **Sanción generada:** el nombre del torneo y el partido, sin el jugador ni su equipo.

  Nunca incluirá el nombre de un jugador, documentos ni fechas de nacimiento.
- **RF-007.** EL SISTEMA firmará cada entrega con HMAC-SHA256 sobre la marca de tiempo del envío y el cuerpo exacto, y enviará la marca de tiempo, la firma y el identificador de la entrega en cabeceras. Los reintentos de una misma entrega conservan su identificador, para que el receptor pueda descartar duplicados.
- **RF-008.** MIENTRAS un webhook esté desactivado o eliminado, EL SISTEMA no creará entregas nuevas para él, y las pendientes se descartarán sin enviarse. Antes de cada intento, el worker volverá a comprobar que el webhook sigue activo y suscrito a ese tipo.

### Protección de la red

- **RF-009.** SI la URL resuelve, en el momento del intento, a una dirección privada, de loopback, de enlace local, compartida (CGNAT), de multidifusión, reservada o de metadatos de la nube, ENTONCES EL SISTEMA no enviará la entrega y la registrará como rechazada, sin reintentarla. La conexión se hace a la misma dirección que se comprobó.
- **RF-010.** SI el destino responde con una redirección, ENTONCES EL SISTEMA no la seguirá y tratará el intento como fallido.

### Reintentos e historial

- **RF-011.** SI el destino no responde con un código 2xx dentro de 10 segundos, ENTONCES EL SISTEMA reintentará la entrega con espera creciente hasta 6 intentos en total, con esperas de 1, 5, 15 y 30 minutos y de 2 horas, y después la marcará como fallida (DA-4). El webhook sigue activo aunque falle. El cuerpo de la respuesta del destino no se guarda.
- **RF-012.** EL SISTEMA permitirá a quien tenga `MANAGE_WEBHOOKS` consultar las últimas 50 entregas de cada webhook de los últimos 30 días (DA-4), con su tipo, fecha, número de intentos, último código HTTP y resultado, y enviar una entrega de prueba, que sigue las mismas reglas de firma, red y reintentos.

### Aislamiento

- **RF-013.** EL SISTEMA aislará con RLS los webhooks y sus entregas por organización. Ninguna organización puede ver, modificar ni deducir los de otra.

## Requisitos no funcionales

- **RNF-001.** Un webhook lento o caído no retrasa el tiempo real, la bandeja, el correo ni los demás webhooks.
- **RNF-002.** El secreto nunca aparece en logs, auditoría, respuestas posteriores al alta o la rotación, errores ni en el repositorio. Las variables nuevas solo llevan valores por defecto en `.env.example`, y fuera de desarrollo el backend rechaza esos valores (principio 6).
- **RNF-003.** Sin campos públicos nuevos ni cambios en la proyección pública.
- **RNF-004.** Los textos nuevos están en ES y EN. La gestión de webhooks se puede usar con teclado y pasa axe en ambos temas.

## Datos personales y privacidad

- Las entregas salen de la plataforma hacia sistemas de la organización, así que solo llevan identificadores y datos ya públicos (RF-006). Ningún nombre de jugador, documento ni fecha de nacimiento.
- La URL de un webhook puede llevar datos de la organización en la ruta o la consulta. Solo la ven quienes tienen `MANAGE_WEBHOOKS`, y la auditoría guarda solo el dominio.
- El secreto es una credencial de la organización: se guarda cifrado y solo se muestra al crearlo o rotarlo.

## Casos límite

1. Un cierre que genera varias suspensiones produce, en cada webhook suscrito a «sanción generada», una entrega por suspensión.
2. Un webhook que se desactiva con entregas pendientes no recibe ninguna más; al reactivarlo no se reenvían las descartadas.
3. Rotar el secreto mientras una entrega está en reintento: los intentos siguientes se firman con el secreto nuevo.
4. Una URL que resuelve a una dirección pública al darla de alta y a una privada al entregar se rechaza en la entrega (RF-009).
5. Un destino que responde 3xx, 4xx o 5xx, o no responde, cuenta como intento fallido; el rechazo por red (RF-009) no se reintenta.
6. Un torneo o partido que se archiva después del hecho no impide la entrega; el cuerpo lleva los datos del momento del hecho.
7. Un aviso que no tiene webhooks suscritos no crea entregas; la bandeja y el correo siguen igual.
8. Una rectificación (033) no genera un segundo «resultado confirmado», tampoco en los webhooks.
9. Un calendario generado antes de publicar el torneo crea el aviso interno, pero ninguna entrega de webhook; publicar después no las crea a posteriori (DA-5).

## Fuera de alcance

- Webhooks de plataforma o que reciban hechos de varias organizaciones.
- Tipos de aviso fuera del catálogo de la 046, como hechos del partido en vivo o cambios de inscripción.
- Reenviar a mano una entrega fallida o descartada, y entregas ordenadas.
- Firma con clave asimétrica, autenticación mutua TLS o cabeceras personalizadas por webhook.
- Cambiar la bandeja, el correo o los avisos de la 033 y la 034.

## Criterios de finalización

| # | Criterio | RF |
|---|---|---|
| 1 | Gestión de webhooks solo con `MANAGE_WEBHOOKS`, con URL HTTPS validada, máximo 10 por organización y auditoría sin secreto. | RF-001–RF-004 |
| 2 | Secreto mostrado una sola vez, cifrado con `WEBHOOK_SECRET_KEY` y rotable; enmienda de la §3.4 fusionada antes de implementar. | RF-003, RNF-002 |
| 3 | Cada aviso suscrito crea su entrega en la transacción del hecho y el worker la envía firmada, sin datos fuera de la proyección pública. | RF-005–RF-008 |
| 4 | Direcciones internas y redirecciones rechazadas. | RF-009, RF-010 |
| 5 | 6 intentos como máximo, historial de 50 entregas en 30 días y entrega de prueba. | RF-011, RF-012 |
| 6 | Aislamiento por RLS entre organizaciones. | RF-013 |
| 7 | ES/EN, teclado y axe en ambos temas. | RNF-004 |

## Dudas abiertas

Ninguna.
