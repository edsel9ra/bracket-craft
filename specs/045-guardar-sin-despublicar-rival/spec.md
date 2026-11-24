# Spec 045 — Guardar la alineación sin despublicar al rival

Estado: borrador

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

- **Alineación de un equipo en un segmento:** su formación (o ninguna) y, por jugador, su rol (titular o suplente) y su posición. [NECESITA ACLARACIÓN] DA-2: si los minutos de entrada y salida también cuentan.
- **Alineación sin cambios:** la que, tras guardar, es idéntica a la que había guardada antes para ese equipo y segmento.

## Requisitos funcionales

- **RF-001.** CUANDO se guarde la planilla de un segmento y la alineación de un equipo quede sin cambios, EL SISTEMA conservará su estado de publicación y su fecha de publicación.
- **RF-002.** CUANDO se guarde la planilla de un segmento y la alineación de un equipo con formación publicada cambie, EL SISTEMA [NECESITA ACLARACIÓN] DA-1: la dejará privada (como hoy) o la mantendrá publicada con el contenido nuevo.
- **RF-003.** CUANDO un guardado retire de la vista pública una formación publicada, EL SISTEMA [NECESITA ACLARACIÓN] DA-3: lo confirmará antes, lo avisará después o no dirá nada.
- **RF-004.** CUANDO un guardado retire una formación publicada, EL SISTEMA [NECESITA ACLARACIÓN] DA-4: registrará o no, además del guardado, una entrada de despublicación de ese equipo en la auditoría.
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
3. Cambiar los dos equipos: se aplica RF-002 a cada uno.
4. Pasar a la planilla clásica (sin formación): la formación es obligatoria para los dos equipos o para ninguno, así que desaparecen las dos y con ellas su publicación.
5. Formación privada de otra modalidad (044) en el equipo que no se toca: hay que cambiarla para guardar, así que ese equipo sí cambia.
6. Solo cambia el orden de los jugadores en la petición: no cuenta como cambio.
7. Segmento distinto del activo: sigue respondiendo 409 sin tocar nada.
8. Publicación del rival en curso mientras se guarda: se aplica RNF-003.

## Fuera de alcance

- Guardar la alineación de un solo equipo por separado (la petición sigue llevando los dos).
- Publicación automática al guardar.
- Cambios en la vista pública, en la precarga entre segmentos (028) o en el partido en vivo (036).

## Criterios de finalización

- Pruebas con base de datos real de los casos límite 1–8 en las cuatro modalidades representativas.
- Pruebas del frontend y E2E con axe del comportamiento de RF-003.
- Documentación (README, manual, AGENTS, MEMORY) actualizada; CI en verde.

## Dudas abiertas

- [NECESITA ACLARACIÓN] DA-1 (RF-002): qué pasa con la publicación del equipo cuya alineación cambia.
- [NECESITA ACLARACIÓN] DA-2 (Definiciones): si los minutos de entrada y salida cuentan como cambio.
- [NECESITA ACLARACIÓN] DA-3 (RF-003): cómo se entera el operador de que un guardado retira una formación publicada.
- [NECESITA ACLARACIÓN] DA-4 (RF-004): si la retirada se registra como despublicación en la auditoría.
