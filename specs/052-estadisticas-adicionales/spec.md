# Spec 052 — Estadísticas adicionales (F17)

Estado: aprobada el 2026-11-27 («Apruebo la spec 052»). DA-1–DA-4 resueltas el 2026-11-27. Pedida por el usuario el 2026-11-27 («Sigue con F17»), última función pendiente de P3 en `docs/informe-funciones-adicionales.md`.

## Decisiones del usuario (2026-11-27)

- **DA-1 = (a).** Los minutos solo cuentan en partidos disputados en los que la alineación del equipo del jugador está publicada, para no revelar titulares privados.
- **DA-2 = (a).** La posición principal es la línea (Portero, Defensa, Centrocampista, Delantero) en la que el jugador jugó más partidos según sus posiciones públicas; en empate, la del partido más reciente.
- **DA-3 = (a).** La posición de entrada es opcional y sale del catálogo de posiciones de la modalidad; solo es pública si la formación del equipo en ese partido está publicada.
- **DA-4 = (a).** El penal atajado es un hecho nuevo del acta con el portero que lo ataja, sin efecto en el marcador, solo en juego y fuera de la cronología pública, para no romper `v1`.
- **DA-5 (2026-11-27, «Acepto tu propuesta.»).** La duración efectiva de un partido disputado es el mayor entre el fin del último segmento y el máximo de la fase (reglamentario o, con prórroga o penales, el de la prórroga). El cierre clásico guarda como fin el minuto del último hecho del acta, y ese fin no debe acortar los minutos. Enmienda también la 022 (minutos del portero y porterías imbatidas). El máximo de la fase es el configurado para esa fase (por ejemplo, 50 en una fase de 50 minutos); la superficie pública lo lee de una vista interna que la API no expone (2026-11-27, «La opción (a), que es la recomendada.»).

## Contexto y objetivo

Las estadísticas públicas de jugadores (spec 022) muestran goles, tarjetas, porterías imbatidas y partidos disputados; la ficha de jugador (038) las repite por torneo. La 022 dejó fuera, expresamente, los minutos jugados, las posiciones, el registro de la posición de quien entra en una sustitución y los penales atajados.

Hoy:

- Los minutos de un jugador ya se calculan, pero solo de forma interna y solo para el umbral de 60 minutos de la portería imbatida (definición única de la 022).
- La posición de un titular solo consta en la formación táctica de su equipo, por segmento, y solo es pública si la formación está publicada (constitución §2.5).
- Una sustitución registra quién sale y quién entra, pero no en qué posición entra.
- No existe ningún hecho de penal atajado. La tanda de penales no genera hechos.

**Objetivo:** publicar en las estadísticas de jugadores y en la ficha los minutos jugados, la posición principal y los penales atajados, a partir de actas confirmadas, y permitir registrar en el acta la posición de quien entra y el penal atajado.

## Usuarios

- Público que consulta las estadísticas de un torneo o la ficha de un jugador, incluidos los terceros de la API pública (051).
- Operadores y responsables del acta que registran los hechos del partido.

## Roles y visibilidad

- **Público (sin sesión):** ve en la tabla de jugadores y en la ficha los minutos jugados, la posición principal y los penales atajados. No ve formaciones ni alineaciones no publicadas, ni nada que permita deducirlas.
- **Miembro de organización:** quien hoy puede registrar hechos del acta (cierre clásico, partido en vivo o rectificación) registra también la posición de quien entra y el penal atajado. Los permisos no cambian.
- **Administrador de organización:** sin cambios.
- **Administrador de plataforma:** sin cambios.

Ninguna otra organización puede ver ni modificar los hechos, las formaciones ni las estadísticas privadas de una organización.

## Historias de usuario

- HU-1. Como aficionado, quiero ver cuántos minutos ha jugado cada jugador para valorar su participación.
- HU-2. Como aficionado, quiero ver la posición principal de un jugador en la tabla y en su ficha.
- HU-3. Como aficionado, quiero ver cuántos penales ha atajado un portero.
- HU-4. Como responsable del acta, quiero indicar en qué posición entra un suplente y registrar un penal atajado sin cambiar el marcador.

## Definiciones

- **Minutos jugados en un partido:** la definición única de la 022 (RF-027), aplicada a todo jugador. Un titular juega desde el minuto 0 hasta su salida (sustitución o expulsión) o hasta la duración efectiva del partido, que nunca es menor que el máximo de la fase (DA-5); un suplente, desde su entrada hasta su salida o el final. El minuto de un hecho es minuto + minuto añadido, acotado a la duración efectiva, en el orden canónico del acta. Solo cuentan los partidos disputados (resultado confirmado en tiempo regular, prórroga o penales) en los que la alineación del equipo del jugador está publicada; si no lo está, ese partido no suma minutos a ningún jugador de ese equipo (DA-1).
- **Línea de una posición:** cada código del catálogo de formaciones (`docs/contrato-reglas.md`) pertenece a una sola línea: Portero (`GK`), Defensa, Centrocampista o Delantero. La tabla fija de códigos a líneas se define en el plan y un test exige que cubra todo el catálogo.
- **Posición principal:** la línea en la que el jugador jugó más partidos del torneo, contando su posición de titular en formaciones publicadas y sus posiciones de entrada públicas; un partido cuenta una vez por línea. En empate, gana la línea del partido más reciente (fecha programada y, a igualdad, identificador del partido). Sin ninguna posición pública, es nula (DA-2).
- **Posición de entrada:** la posición en la que entra un suplente en una sustitución. Es opcional y debe ser un código del catálogo de posiciones de la modalidad de la fase. Solo es pública si la formación del equipo en ese partido está publicada (DA-3).
- **Penal atajado:** hecho nuevo del acta, con minuto y el jugador del equipo que defiende el penal y lo ataja. No cambia el marcador ni cuenta como gol, tarjeta o falta. Solo se registra durante el juego: la tanda de penales no genera hechos. No aparece en la cronología pública (DA-4).

## Requisitos funcionales

### Estadísticas públicas

- **RF-001.** EL SISTEMA incluirá en cada fila de la tabla pública de jugadores los **minutos jugados**: la suma de sus minutos en los partidos que cuentan según DA-1, de la versión vigente de cada acta confirmada.
- **RF-002.** EL SISTEMA incluirá en cada fila la **posición principal** según DA-2, o nulo si el jugador no tiene ninguna posición pública en el torneo.
- **RF-003.** EL SISTEMA incluirá en cada fila los **penales atajados** según DA-4.
- **RF-004.** EL SISTEMA mostrará los tres datos en la ficha pública del jugador (038), por torneo, con los mismos valores que la tabla de ese torneo.
- **RF-005.** EL SISTEMA no cambiará el orden, la posición en la tabla ni ninguna otra columna de las estadísticas de jugadores y de equipos.
- **RF-006.** CUANDO un acta se rectifica, EL SISTEMA calculará los tres datos con la versión vigente, sin hechos anulados.

### Registro en el acta

- **RF-007.** CUANDO se registra una sustitución en el cierre clásico, en el partido en vivo o en una rectificación, EL SISTEMA aceptará la posición de entrada según DA-3.
- **RF-008.** SI la posición de entrada no pertenece al catálogo de posiciones de la modalidad de la fase, ENTONCES EL SISTEMA rechazará el hecho con un error de validación y no guardará nada.
- **RF-009.** CUANDO se registra un penal atajado, EL SISTEMA lo guardará como un hecho del acta según DA-4, en los mismos tres flujos.
- **RF-010.** EL SISTEMA no cambiará por la posición de entrada ni por el penal atajado el marcador, la clasificación, las sanciones, el avance de fases, el motor de reglas ni `engine_version` (2026.1).

### Workspace

- **RF-011.** EL SISTEMA ofrecerá en el formulario de sustitución un selector de la posición de entrada y, en el selector de hechos, «Penal atajado», en ES y EN, con teclado y sin violaciones de axe en los dos temas.
- **RF-012.** EL SISTEMA mostrará la posición de entrada y el penal atajado en el acta del Workspace, en su historial de versiones y en el acta exportada en CSV y PDF (048, 050).

### Exportaciones y API pública

- **RF-013.** EL SISTEMA añadirá los tres datos como columnas finales del CSV de estadísticas de jugadores (048), en ES y EN.
- **RF-014.** EL SISTEMA añadirá los tres datos a las respuestas públicas como campos nuevos no obligatorios (cambio compatible de `v1`, 051), actualizará la copia de referencia y anotará el cambio con fecha en el historial de las dos guías.
- **RF-015.** EL SISTEMA no cambiará la cronología pública (037): ni el penal atajado ni la posición de entrada aparecen en ella.

### Aislamiento

- **RF-016.** EL SISTEMA calculará los datos públicos solo con la proyección pública de la organización del torneo visible; un torneo o jugador no visible da el mismo «no encontrado» de hoy.

## Requisitos no funcionales

- **RNF-001.** El cálculo es puro: recibe partidos, hechos, segmentos, alineaciones y formaciones, y no lee la base de datos ni el reloj.
- **RNF-002.** Los cambios de esquema son aditivos, en una migración nueva; las actas existentes siguen siendo válidas sin rellenar nada.
- **RNF-003.** La tabla de jugadores de un torneo de 32 equipos y 300 partidos se calcula en menos de 1 s, como hoy.
- **RNF-004.** Textos ES/EN; sin campos públicos fuera de los de esta spec.

## Datos personales y privacidad

- **Datos involucrados:** nombre del jugador (ya público), minutos, posición y penales atajados, derivados del acta.
- **Lo que no se expone:** documentos, fechas de nacimiento, alineaciones ni formaciones no publicadas. Ni los minutos ni la posición permiten deducir un titular o una posición que no sea pública (DA-1, DA-3).
- **Fotos:** sin cambios; dependen del consentimiento de imagen (038).

## Casos límite

- **CL-1.** Sustitución sin posición de entrada: los minutos cuentan; la posición principal no usa esa entrada.
- **CL-2.** Suplente que entra y después es expulsado o sustituido: minutos desde la entrada hasta la salida.
- **CL-3.** Portero sustituido por un jugador de campo que entra como `GK`: la entrada cuenta como posición `GK`.
- **CL-4.** Walkover o resolución administrativa: no suman minutos ni posiciones (no hay planilla ni hechos).
- **CL-5.** Penal atajado y gol en el rechace: son dos hechos; el gol cuenta como hoy.
- **CL-6.** Tanda de penales: no genera hechos; sus paradas no cuentan.
- **CL-7.** Jugador en dos equipos del mismo torneo: los tres datos se suman, como el resto de su fila.
- **CL-8.** Acta anterior a esta spec: sin posiciones de entrada ni penales atajados; los minutos se calculan igual.

## Fuera de alcance

- Penales fallados fuera de la portería, paradas en general y otras métricas de portero.
- Estadísticas en vivo minuto a minuto, mapas de posición o de calor.
- Nuevas estadísticas de equipo y nuevos criterios de orden de la tabla.
- Posición habitual configurable en la ficha privada del jugador.
- Publicar asistencias, faltas o sanciones (sin cambios respecto a la 022).
- Cambios en la cronología pública (037) o una versión `v2` de la API.

## Criterios de finalización

- Los tres datos aparecen en la tabla de jugadores, en la ficha y en el CSV, con tests de cada caso límite.
- La posición de entrada y el penal atajado se registran en los tres flujos del acta y se ven en el acta del Workspace y en sus exportaciones.
- Un test comprueba que marcador, clasificación, sanciones y avance de fases no cambian.
- `python -m scripts.public_api_reference --check` pasa con la copia actualizada y la entrada en el historial.
- Pasan las suites backend (con BD) y frontend, typecheck, lint y el E2E del flujo, con axe.
- README, AGENTS, manual, informe (F17 implementada) y MEMORY actualizados.

## Dudas abiertas

Ninguna. DA-1–DA-4 están resueltas (ver «Decisiones del usuario»).
