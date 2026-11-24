# Spec 045 — Guardar la alineación sin despublicar al rival

Estado: aprobada por el usuario el 2026-11-24 («Apruebo la spec 045»). DA-1–DA-4 resueltas el mismo día.

## Decisiones del usuario (2026-11-24)

- **DA-1 = (a).** La formación publicada de un equipo cuya alineación cambia pasa a privada, como hoy: lo público siempre es algo publicado explícitamente.
- **DA-2 = (a).** Cuenta como cambio lo que se ve en público: la formación y, por jugador, si está convocado, su rol y su posición. Los minutos de entrada y salida no cuentan.
- **DA-3 = (a).** Si un guardado va a retirar una formación publicada, el Workspace pide confirmación antes de guardar y nombra al equipo afectado.
- **DA-4 = (a).** Además de la entrada de guardado, la auditoría registra una despublicación por cada equipo cuya formación pasa a privada.

## Contexto y objetivo

En la operación del partido, la planilla y las formaciones de los dos equipos se guardan juntas: guardar envía las dos y el sistema borra y vuelve a crear las formaciones del segmento. Las formaciones recreadas nacen **privadas**, así que guardar despublica también la del equipo que **no se ha tocado**. Pasa igual en todas las modalidades desde la spec 021; Devin Review lo detectó al revisar la 044 y el usuario decidió tratarlo en esta spec (2026-11-24).

Consecuencia hoy: corregir un dorsal o un suplente del local retira de la vista pública la formación del visitante, que hay que volver a publicar a mano. Nada avisa de ello.

**Objetivo:** que guardar solo afecte a la publicación del equipo cuya alineación cambia, y que el operador sepa cuándo un guardado retira una formación de la vista pública.

## Usuarios

- Administrador de organización y operador, que guardan y publican alineaciones.
- Aficionado, que consulta la formación publicada.

## Roles y visibilidad

- **Público (sin sesión):** sigue viendo solo las formaciones publicadas, con los mismos campos que hoy. Una formación publicada que no cambia deja de desaparecer al guardar el rival.
- **Miembro de organización (incluido observador):** sin cambios.
- **Administrador de organización / operador:** guarda y publica con los permisos actuales.
- **Administrador de plataforma:** sin cambios.

## Historias de usuario

- HU-1. Como operador, quiero corregir la alineación de un equipo sin que la formación publicada del otro desaparezca de la vista pública.
- HU-2. Como operador, quiero saber cuándo un guardado retira una formación publicada, para volver a publicarla si procede.
- HU-3. Como aficionado, quiero que la formación publicada de un equipo siga visible mientras el organizador corrige la del rival.

## Definiciones

- **Alineación de un equipo en un segmento:** su formación (o ninguna) y, por jugador convocado, su rol (titular o suplente) y su posición (DA-2). Los minutos de entrada y salida no forman parte de ella.
- **Alineación sin cambios:** la que, tras guardar, tiene la misma formación y los mismos jugadores convocados, con el mismo rol y la misma posición, que la guardada antes para ese equipo y segmento. El orden de los jugadores en la petición no importa.
- **Formación retirada:** una formación publicada que un guardado deja privada (RF-002) o elimina (caso límite 4).

## Requisitos funcionales

- **RF-001.** CUANDO se guarde la planilla de un segmento y la alineación de un equipo quede sin cambios, EL SISTEMA conservará su estado de publicación y su fecha de publicación.
- **RF-002.** CUANDO se guarde la planilla de un segmento y la alineación de un equipo con formación publicada cambie, EL SISTEMA la dejará privada y sin fecha de publicación, como hoy (DA-1). Para volver a mostrarla hay que publicarla explícitamente.
- **RF-003.** CUANDO el operador vaya a guardar y, según el estado cargado en el Workspace, el guardado vaya a retirar alguna formación publicada, EL SISTEMA pedirá confirmación antes de enviar nada, nombrando a cada equipo afectado (DA-3). Si el operador cancela, no se guarda nada. Si ningún equipo publicado cambia, se guarda sin confirmación, como hoy.
- **RF-004.** CUANDO un guardado retire una formación publicada, EL SISTEMA registrará en la auditoría, en la misma transacción y además de la entrada de guardado, una entrada de despublicación por cada equipo afectado, con el segmento y el equipo (DA-4). Un equipo que conserva su publicación no genera entrada de despublicación.
- **RF-008.** EL SISTEMA decidirá qué formaciones se retiran comparando, en el servidor y dentro de la misma transacción, lo guardado con lo que deja el guardado; la confirmación del Workspace (RF-003) es solo informativa y no cambia ese resultado.
- **RF-005.** EL SISTEMA mantendrá las validaciones actuales de guardar y publicar (modalidad, titulares, posiciones, segmento activo, partido sin eventos ni terminado) y la independencia por segmento de la 028.
- **RF-006.** EL SISTEMA aplicará el mismo comportamiento en 5v5, 7v7, 9v9 y 11v11.
- **RF-007.** SI la petición llega de otra organización o el partido no existe, ENTONCES EL SISTEMA responderá como hoy, sin leer ni modificar datos de ninguna organización.

## Requisitos no funcionales

- **RNF-001.** Sin campos públicos nuevos ni cambios en la proyección pública.
- **RNF-002.** Sin migraciones, salvo que el plan demuestre que hacen falta.
- **RNF-003.** Un guardado y una publicación concurrentes del mismo partido terminan en un estado coherente: nunca queda publicada una formación que no cumple las reglas de publicación.
- **RNF-004.** Textos nuevos en ES y EN; los avisos son accesibles (anunciados a lectores de pantalla) y pasan axe en ambos temas.

## Datos personales y privacidad

No se exponen datos nuevos. El efecto es que una formación ya publicada sigue publicada; la auditoría conserva su resumen sin nombres ni contenido de la planilla.

## Casos límite

1. Guardar sin cambiar nada: ninguna formación cambia de estado de publicación.
2. Cambiar solo el local con el visitante publicado: el visitante sigue publicado con la misma fecha.
3. Cambiar los dos equipos: se aplica RF-002 a cada uno; la confirmación nombra a los dos si ambos estaban publicados.
4. Pasar a la planilla clásica (sin formación): la formación es obligatoria para los dos equipos o para ninguno, así que desaparecen las dos. Cada una que estuviera publicada cuenta como retirada (RF-003, RF-004).
5. Formación privada de otra modalidad (044) en el equipo que no se toca: hay que cambiarla para guardar, así que ese equipo sí cambia.
6. Solo cambia el orden de los jugadores en la petición: no cuenta como cambio.
7. Segmento distinto del activo: sigue respondiendo 409 sin tocar nada.
8. Publicación del rival en curso mientras se guarda: se aplica RNF-003; si el estado del Workspace estaba desfasado, la confirmación puede no coincidir, pero el resultado y la auditoría siguen RF-008.
9. Solo cambian los minutos de entrada o salida de un jugador del equipo publicado: no cuenta como cambio y la publicación se conserva (DA-2).
10. Un jugador pasa de titular a suplente o cambia de posición en el equipo publicado: cuenta como cambio (DA-2).

## Fuera de alcance

- Guardar la alineación de un solo equipo por separado (la petición sigue llevando los dos).
- Publicación automática al guardar.
- Cambios en la vista pública, en la precarga entre segmentos (028) o en el partido en vivo (036).

## Criterios de finalización

- Pruebas con base de datos real de los casos límite 1–10, en 11v11 y al menos una modalidad reducida.
- Pruebas del frontend y E2E con axe del comportamiento de RF-003.
- Documentación (README, manual, AGENTS, MEMORY) actualizada; CI en verde.

## Dudas abiertas

Ninguna. DA-1–DA-4 resueltas el 2026-11-24 (ver «Decisiones del usuario»).
