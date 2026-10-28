# Spec 020 — Consulta pública: navegación por fases y grupos, y acceso público

Estado: implementada

## Contexto y objetivo

La consulta pública de un torneo (portada y detalle, sin sesión) ya existe y funciona, pero navega mal la estructura real del torneo y no deja claro qué es público y qué sigue protegido. Esta spec (primera de tres) cierra la navegación por fases y grupos y audita el acceso público. Las estadísticas y las formaciones gráficas quedan para las specs 021 y 022.

Problemas concretos a resolver:

1. **Navegación deficiente.** Las fases se apilan una debajo de otra; una fase de grupos mezcla a todos los grupos en una sola tabla; la carga adicional de filas solo se ofrece en la primera fase con tabla; la llave se agrupa por jornada. No hay forma de ir directamente a una fase ni de compartirla.
2. **Defecto de paginación.** La paginación de clasificación y de partidos es global (ordenada por fase) y el botón de «cargar más» solo aparece en la primera fase que lo necesita, de modo que las filas de la segunda fase pueden quedar fuera de la primera página y solo aparecen al pulsar un control colocado en otra fase.
3. **Acceso público no documentado.** No existe una matriz explícita de qué se puede consultar sin sesión y qué debe seguir protegido, ni una verificación automática de la lista cerrada de campos públicos.

**Objetivo:** que cualquier visitante recorra un torneo según su estructura real (una fase a la vez, con grupos independientes) y que quede auditado y verificado qué es público y qué no, sin ampliar lo público más allá de lo mínimo necesario ni tocar lo protegido.

### Comportamiento actual verificado

| # | Hecho verificado |
|---|---|
| 1 | La portada y el detalle del torneo son públicos y no dependen de sesión. Las lecturas públicas son: listado de torneos, detalle (con fases y equipos), clasificación y partidos (con alineaciones publicadas). La página pide 50 filas por vez y ofrece «cargar más». |
| 2 | Un torneo es visible públicamente solo con versión publicada, estado publicado, en juego o finalizado, y organización activa. Los partidos visibles son los programados, en juego, finalizados y de resolución administrativa; los **suspendidos y los cancelados no se publican**. |
| 3 | El detalle público expone de cada fase solo nombre, formato y orden, y de cada equipo nombre, código y escudo. **No expone grupos ni qué equipos pertenecen a qué fase o grupo**; el grupo solo aparece como nombre dentro de cada fila de clasificación o de partido. |
| 4 | La página pública, si hay fases, muestra un panel por fase en su orden: tabla (liga, grupos, suizo) o llave (eliminatorias) más la lista de partidos. En una fase de grupos todas las filas van en **una sola tabla** con el grupo como texto secundario. La llave se agrupa por jornada. La paginación de clasificación y de partidos es **global** (ordenada por fase) y el botón de «cargar más» solo aparece en la primera fase que lo necesita. Sin fases publicadas existe una presentación heredada sin paneles por fase. |
| 5 | La clasificación pública devuelve además de los datos mostrados (posición, equipo, jugados, diferencia, puntos) ganados, empatados, perdidos, goles a favor y en contra y puntos de juego limpio, pero la pantalla solo muestra cuatro columnas. Cuenta partidos finalizados o de resolución administrativa con resultado confirmado y usa el **marcador final** (incluye prórroga y excluye la tanda de penales). En un walkover cuenta el marcador derivado de la configuración (3-0 por defecto). El avance entre fases es **manual** y no existe ninguna regla automática de clasificados. |
| 6 | La alineación pública de un equipo en un partido es: (a) la **formación táctica** (código del catálogo de cuatro formaciones y posición de cada titular) **solo si se publicó explícitamente** desde el Workspace; (b) si el equipo **no tiene** formación táctica para ese partido, la **planilla** (titulares y suplentes, sin posiciones); (c) si existe una formación táctica **sin publicar**, no se publica ni la formación ni la planilla de ese equipo. De varias formaciones publicadas por segmento se publica la **última**. |
| 7 | La pantalla dibuja el campo con las dos formaciones **solo si ambos equipos** tienen formación y todos sus titulares tienen posición; en otro caso muestra listas. Los suplentes van en lista. |
| 8 | La foto de un jugador pertenece a su **inscripción en el torneo** y solo se publica con **consentimiento de imagen**; se entrega como enlace temporal firmado y, si la firma falla, la respuesta sigue siendo correcta con la foto en nulo. Hoy solo aparece en las alineaciones. |
| 9 | Un partido puede tener cualquier número de segmentos (ventanas de tiempo), interrupciones y una duración reglamentaria configurable; un gol cuyo minuto supera el reglamentario es de prórroga. Un **walkover** no tiene eventos, segmentos ni planilla. La resolución administrativa fija ganador y motivo. Los eventos de un acta confirmada son inmutables. |
| 10 | La edad, el documento y la fecha de nacimiento nunca se publican. Existe una proyección interna de jugadores que ningún endpoint consume. |

El hecho 4 (paginación global y mezcla de grupos) es un **defecto observable**, no solo una carencia. Los hechos 6 y 7 condicionan la spec 021 (formaciones) y el hecho 8 la spec 022 (fotos en estadísticas).

## Usuarios

- Aficionado, familiar, jugador o prensa que consulta un torneo **sin cuenta**.
- Administrador de organización y operador, que publican formaciones y deciden el consentimiento de imagen (no cambian).
- Jugador (o su tutor), cuyos datos personales y foto deben seguir protegidos.

## Roles y visibilidad

- **Público (sin sesión):** ve, de torneos visibles públicamente, la estructura por fases y grupos, las clasificaciones, las llaves y los partidos, con sus alineaciones publicadas y fotos con consentimiento. No ve nada de torneos en borrador, sin versión publicada ni de organizaciones inactivas, ni formaciones sin publicar, ni documentos, fechas de nacimiento o edad.
- **Miembro de organización (incluido observador):** sin cambios; sigue viendo todo lo de su organización en el Workspace. Esta spec no añade pantallas ni permisos al Workspace.
- **Administrador de organización / operador:** sin cambios; publican o despublican formaciones y gestionan el consentimiento de imagen como hoy. Lo que publican o autorizan es exactamente lo que el público puede ver, ni más ni menos.
- **Administrador de plataforma:** sin cambios; no edita resultados ni versiones publicadas.

## Historias de usuario

- HU-1. Como aficionado, quiero ir directamente a una fase del torneo y ver sus grupos o rondas tal como se disputan, para entender cómo se compite y dónde está mi equipo.
- HU-2. Como aficionado, quiero una tabla de posiciones completa por grupo, para saber quién clasifica en mi grupo sin mezclarlo con los demás.
- HU-3. Como administrador de organización, quiero que una formación sin publicar o una foto sin consentimiento nunca aparezcan en público, para controlar lo que mi organización muestra.
- HU-4. Como jugador (o tutor), quiero que mi documento, fecha de nacimiento y edad no salgan nunca y que mi foto solo se vea si lo autoricé, para proteger mi privacidad.
- HU-5. Como operador, quiero que cerrar un acta actualice por sí solo las tablas públicas, para no repetir trabajo.

## Definiciones

- **Torneo visible públicamente:** versión publicada, estado publicado, en juego o finalizado, y organización activa (la condición vigente de todo lo público).
- **Partido con resultado confirmado:** partido finalizado o de resolución administrativa cuyo resultado está confirmado. Es el único tipo de partido que puede contribuir a una clasificación. Un partido programado, en juego, suspendido o cancelado no contribuye.
- **Plantilla inscrita:** lista de jugadores inscritos de un equipo en el torneo (con dorsal). No dice quién juega un partido concreto ni dónde.
- **Planilla del partido (alineación sin formación):** titulares y suplentes convocados de un equipo en un partido, sin posiciones.
- **Formación táctica:** código del catálogo cerrado de formaciones (`4-3-3`, `4-4-2`, `3-5-2`, `4-2-3-1`) más la posición asignada a cada titular, guardada por segmento y equipo y publicada explícitamente. Es el único dato del que se puede dibujar un campo.
- **Partido incompleto:** partido con acta confirmada cuya duración registrada es menor que la reglamentaria, o con segmentos interrumpidos. Esta spec no define estadísticas sobre partidos incompletos (corresponde a la spec 022).
- **Fase:** unidad de la estructura de un torneo, con nombre, formato y orden, tal como se define en la versión publicada. Puede ser de liga, grupos, suiza o eliminatoria (simple o doble).
- **Grupo:** subdivisión de una fase de grupos; su nombre aparece en cada fila de clasificación o de partido.
- **Progresión manual:** el avance de equipos entre fases se hace a mano por el administrador; no existe ninguna regla automática que lo calcule a partir de posiciones o umbrales.

## Requisitos funcionales

Todo dato de una organización sigue protegido por el aislamiento entre organizaciones: ningún torneo, equipo o jugador de otra organización puede verse ni mezclarse en una respuesta (RF-017).

### Navegación por fases, grupos y segmentos

- **RF-001.** EL SISTEMA mostrará en la página pública del torneo las fases de su versión publicada en el orden de fase, con desempate estable, identificando cada una por nombre y formato, y ofrecerá un acceso directo a cada una.
- **RF-002.** CUANDO el visitante elija una fase (o un grupo), EL SISTEMA reflejará la elección en la dirección de la página mediante los parámetros `stage` y `group` (identificadores de la fase y del grupo, UUID), de modo que compartirla o recargarla restaure la misma fase y el botón «atrás» del navegador vuelva a la elección anterior. La normalización inicial (fase o grupo inexistente o ausente) se hace con reemplazo de historial; cada cambio del visitante se apila con inserción. Si `stage` apunta a una fase inexistente o no publicada, se restaura a la primera fase publicada; si `group` apunta a un grupo inexistente, se elimina el parámetro y se muestra la fase completa.
- **RF-003.** MIENTRAS una fase sea de grupos, EL SISTEMA mostrará una clasificación **independiente por grupo**, encabezada por el nombre del grupo, y sus partidos agrupados por grupo; ninguna fila de un grupo aparecerá en la clasificación de otro.
- **RF-004.** MIENTRAS una fase sea de liga o suiza, EL SISTEMA mostrará una única clasificación y sus partidos agrupados por jornada o ronda, según conste en cada partido.
- **RF-005.** MIENTRAS una fase sea eliminatoria (simple o doble), EL SISTEMA mostrará la llave por rondas con cada partido, su resultado y el ganador marcado, e indicará **con texto, no solo con color**, cuando el partido se resolvió por prórroga, penales, walkover o resolución administrativa. La prórroga se detecta a partir de los campos ya publicados (`home_score_regular`/`away_score_regular` distintos de `home_score`/`away_score`, o `resolution` equivalente); los penales, a partir de `home_penalties`/`away_penalties` no nulos; el walkover y la resolución administrativa, a partir del estado del partido y del ganador. No se añade ningún campo público nuevo.
- **RF-006.** SI una fase no tiene equipos asignados, partidos o clasificación calculada, ENTONCES EL SISTEMA lo indicará con un estado vacío propio de esa fase, sin tratarlo como un error y sin ocultar la fase.
- **RF-007.** EL SISTEMA **no inferirá ni calculará** qué equipos pasan de una fase a la siguiente a partir de posiciones o de umbrales, porque el avance entre fases es manual y no existe una regla automática. EL SISTEMA no añadirá campos públicos nuevos para la progresión: solo mostrará lo que ya publican las respuestas existentes (fase y grupo de cada partido, ganador marcado, estado). Mostrar equipos asignados a la fase siguiente o el origen de cada participante en una llave exigiría ampliar el contrato público y queda **fuera de alcance** de esta spec (candidato a una spec futura).
- **RF-008.** EL SISTEMA permitirá llegar a **todas** las filas de clasificación y a **todos** los partidos de **cada** fase y grupo, reutilizando los parámetros ya existentes de las lecturas públicas filtrados por fase y grupo (`stage_id`, `group_id`) con paginación propia por cada combinación (fase, grupo). La carga adicional de una fase o grupo no dependerá de haber cargado antes lo de otra, y cada combinación mantendrá su propio desplazamiento y su indicador de «hay más».
- **RF-009.** CUANDO se cierre un acta del torneo, EL SISTEMA actualizará clasificaciones y llaves visibles con el mecanismo de actualización pública existente (aviso en tiempo real o consulta periódica), sin recargar la página y conservando la fase y el grupo elegidos. La actualización reiniciará la paginación de la fase o grupo activo a su primera página, de modo que el visitante vea los datos nuevos completos.
- **RF-010.** EL SISTEMA seguirá mostrando sin errores los torneos sin fases publicadas con la presentación heredada de clasificación y partidos.

### Tabla de posiciones (revisión)

- **RF-011.** EL SISTEMA mostrará en cada fila de la clasificación: posición, equipo con su escudo, jugados, ganados, empatados, perdidos, goles a favor, goles en contra, diferencia de goles, puntos y puntos de juego limpio (este último ya presente en la respuesta pública). EL SISTEMA **no** mostrará el criterio de desempate aplicado, porque no existe fuente pública para ello; si se quisiera exponerlo, sería un cambio de contrato propio.
- **RF-012.** EL SISTEMA garantizará en cada fila de clasificación que jugados = ganados + empatados + perdidos y que diferencia = goles a favor − goles en contra, y que las filas aparecen en el orden de posición.

### Acceso público y datos protegidos

- **RF-013.** EL SISTEMA servirá **sin sesión, sin organización activa y sin credenciales** las lecturas públicas existentes: listado de torneos, detalle del torneo, clasificación y partidos (con alineaciones publicadas). Ninguna otra lectura se añade en esta spec.
- **RF-014.** SI el torneo no es visible públicamente (borrador, sin versión publicada, organización inactiva o inexistente), ENTONCES todas las lecturas públicas responderán el mismo «no encontrado», indistinguible de un torneo inexistente.
- **RF-015.** EL SISTEMA publicará de cada respuesta pública **solo** los campos de una lista cerrada y aprobada, y una verificación automática **fallará** si aparece cualquier campo fuera de esa lista. La lista cerrada es la unión de los campos de los modelos de respuesta públicos vigentes (`PublicTournamentSummaryResponse`, `PublicStageResponse`, `PublicTournamentTeamResponse`, `PublicTournamentResponse`, `PublicStandingResponse`, `PublicLineupPlayerResponse`, `PublicTeamLineupResponse` —que incluye `segment_number` aditivo desde la spec 021—, `PublicMatchLineupResponse`, `PublicMatchResponse`) y de las vistas públicas (`v_public_tournaments`, `v_public_stages`, `v_public_tournament_teams`, `v_public_standings`, `v_public_matches`, `v_public_match_lineups`). La lista se actualiza en el mismo cambio que añade un campo nuevo; no se versiona por separado. El anexo de campos exactos se adjunta en el plan de esta spec.
- **RF-016.** EL SISTEMA no publicará nunca documentos de identidad, fecha de nacimiento, edad, la dirección externa heredada del escudo (`logo_url` heredado, distinta del enlace firmado `crest_url`), claves internas de almacenamiento, el motivo de un walkover o de una resolución administrativa, sanciones y suspensiones, registros de auditoría ni datos de miembros u organizaciones.
- **RF-017.** EL SISTEMA no mezclará en ninguna respuesta pública datos de más de un torneo ni de otra organización, y ningún torneo de otra organización será visible ni modificable a través de las lecturas públicas.
- **RF-018.** EL SISTEMA no añadirá ninguna escritura, permiso, cookie ni dependencia de sesión a la consulta pública; toda escritura sigue exigiendo sesión, organización y permiso como hoy.
- **RF-019.** SI un parámetro de consulta de una lectura pública está fuera de rango, ENTONCES EL SISTEMA responderá con el error estructural vigente: `422` con `detail` en lista (`type`, `loc`, `msg`) y sin `code`. El shape exacto del error de FastAPI/Pydantic para parámetros de consulta se documenta en el plan (no se garantiza la omisión del valor recibido, porque los query params quedan fuera del cierre de la spec 019).
- **RF-020.** EL SISTEMA documentará la **matriz de acceso** (qué es público, qué exige sesión, qué no sale nunca) en la documentación del producto, en el mismo cambio.

## Requisitos no funcionales

- **RNF-001 (solo lectura y compatibilidad).** La consulta pública no escribe datos. Las respuestas públicas existentes solo cambian de forma **aditiva**: un cliente que ignore los campos nuevos conserva su comportamiento. Todo cambio no aditivo se declara aquí y en la documentación. `engine_version` sigue en **2026.1** y el contrato interno de reglas no se toca.
- **RNF-002 (consistencia).** La clasificación pública se deriva únicamente de partidos con resultado confirmado y es reproducible a partir de ellos. Tras cerrar un acta, la clasificación llega al público en el mismo plazo que hoy (aviso en tiempo real o consulta periódica de 30 s como máximo).
- **RNF-003 (rendimiento acotado).** Cada respuesta pública está acotada por un tope de filas y el número de consultas a la base por respuesta **no crece** con el número de partidos ni de filas. Las fotos se firman en un solo lote por respuesta y **después** de cerrar la transacción de lectura, como hoy. No se fija una latencia absoluta porque no se midió.
- **RNF-004 (accesibilidad y adaptación).** Las tablas llevan título y encabezados asociados a sus celdas; ninguna información depende solo del color; todo texto nuevo existe en español e inglés. En una pantalla de 360 px de ancho la página no desborda horizontalmente (las tablas se desplazan dentro de su contenedor).
- **RNF-005 (aislamiento y privilegios).** Toda lectura sobre datos de organizaciones respeta el aislamiento por organización en la base de datos; la aplicación no obtiene ningún privilegio para saltárselo. Cualquier cambio de esquema es **aditivo**, una migración nueva numerada, verificada sobre un volumen limpio y uno ya migrado, y no edita migraciones aplicadas.
- **RNF-006 (privacidad en registros).** Ningún registro del sistema contiene nombres, fotos, claves de objeto ni datos personales de jugadores por el uso de estas lecturas.
- **RNF-007 (verificación).** La garantía de lista cerrada de campos públicos (RF-015) y el aislamiento entre dos organizaciones (RF-017) se verifican con pruebas automáticas. Pasan los cinco jobs de CI.
- **RNF-008 (documentación).** El cambio actualiza la documentación afectada del producto y de los agentes.

## Datos personales y privacidad

- **Datos involucrados:** los mismos que hoy en las lecturas públicas: nombre y apellido, dorsal, equipo y foto de jugadores (algunos pueden ser menores); clasificación y partidos.
- **Ya público hoy:** nombre, apellido, dorsal y posición de los jugadores que figuran en una alineación publicada; foto solo con consentimiento de imagen.
- **Nuevo con esta spec:** **nada nuevo**. Esta spec solo reorganiza la navegación y audita el acceso; no añade campos públicos ni estadísticas.
- **Nunca público:** documento de identidad, fecha de nacimiento, edad, año de referencia de la edad, clave de objeto de la foto, motivo de walkover o de resolución administrativa, sanciones y suspensiones de jugadores, auditoría, datos de miembros.
- **Foto:** solo con consentimiento de imagen de la inscripción en ese torneo, como enlace temporal; retirar el consentimiento la oculta en la siguiente consulta.
- **Quién puede ver qué:** el público, solo lo anterior; los miembros de la organización, lo que ya ven; ninguna otra organización ve ni modifica estos datos.

## Casos límite

1. Torneo **sin fases publicadas** (estructura heredada): presentación actual, sin errores (RF-010).
2. **Fase sin equipos, sin partidos o sin clasificación calculada** (antes del primer cierre): estado vacío propio de la fase (RF-006).
3. **Fase de grupos** con un grupo vacío o con equipos aún sin grupo: el grupo vacío se muestra como tal y un equipo sin grupo no se mezcla en la tabla de otro (RF-003).
4. **Más de 50 filas en una fase y más de una fase:** todas las filas de cada fase son alcanzables sin pulsar controles de otra (RF-008).
5. **Torneo en borrador, sin versión publicada o de una organización inactiva:** «no encontrado» indistinguible (RF-014).
6. **Cierre de un acta mientras el visitante mira una fase:** se actualiza sin perder fase ni grupo (RF-009).
7. **Nombres largos o equipos sin escudo:** el diseño no se rompe; se muestran las iniciales del equipo ya vigentes.
8. **Acceso directo a una fase inexistente o a un grupo inexistente:** se restaura a la primera fase válida sin error.
9. **Organización desactivada o torneo despublicado:** «no encontrado» indistinguible (RF-014).
10. **Fase o grupo inexistente en la dirección:** se restaura a la primera fase publicada sin error (RF-002).
11. **`stage_id` o `group_id` ajeno o inexistente en una lectura pública:** la respuesta es una lista vacía, no un error ni una fuga de datos (RF-017).
12. **Clasificación parcial** (equipos inscritos sin partidos): aparecen con ceros si constan en la clasificación; si no constan, no se inventan filas (RF-012).
13. **Partido de walkover o resolución administrativa en la llave:** el ganador se marca y la resolución se indica con texto (RF-005); el motivo nunca es público (RF-016).
14. **Partido con marcador nulo pero estado de resolución administrativa:** se muestra como resuelto fuera del campo, sin intentar interpretar el marcador.

## Fuera de alcance

- Estadísticas de jugadores y equipos, tablas de porterías imbatidas y fotos en estadísticas: **spec 022**.
- Formaciones gráficas y distinción formación / planilla / plantilla: **spec 021**.
- Editar resultados, actas, formaciones, consentimientos o versiones desde la consulta pública; cualquier escritura nueva.
- Cronología pública partido a partido, estadísticas en vivo minuto a minuto y marcadores en vivo nuevos.
- Estadísticas históricas entre torneos, fichas de jugador, comparativas y clasificaciones globales.
- Cálculo automático de clasificados entre fases o sembrado automático; cualquier cambio al avance manual.
- API pública documentada para terceros, exportaciones, notificaciones y optimización para buscadores o compartir en redes.
- Filtrado del tiempo real por rol (riesgo ya aceptado y fuera de esta spec).

## Dependencias

- **Spec 020 (esta):** independiente. Es la base sobre la que se construyen la 021 y la 022.
- **Spec 021 (formaciones gráficas):** depende de la 020 (acceso público y tabla). Añade un campo aditivo mínimo a la alineación publicada: `segment_number` (entero, nullable) en `PublicTeamLineupResponse`, para etiquetar la formación con su segmento. Se añade a la lista cerrada de campos públicos en el mismo cambio.
- **Spec 022 (estadísticas y porterías imbatidas):** depende de la 020 (acceso público y tabla) y de la 021 (formaciones publicadas, fuente del portero).

## Criterios de finalización

La spec está **implementada** cuando:

1. Cada RF aplicable tiene una prueba o evidencia citada y todos los casos límite de su alcance tienen un caso propio.
2. Un torneo con varias fases, grupos y llave se recorre con acceso directo a cada fase, tablas independientes por grupo y carga completa por fase (RF-001 a RF-008).
3. Una verificación automática enumera los campos de cada respuesta pública y falla ante un campo fuera de la lista cerrada; no aparece ningún documento, fecha de nacimiento ni edad (RF-015, RF-016).
4. Un torneo en borrador, sin versión publicada o de una organización inactiva responde igual que uno inexistente en todas las lecturas públicas (RF-014).
5. Dos organizaciones de prueba demuestran que ninguna respuesta pública mezcla datos entre ellas (RF-017).
6. Los cinco jobs de CI pasan (`backend`, `frontend`, `infrastructure`, `security`, `e2e`), incluidas la comprobación de tipos y la compilación del frontend.
7. La documentación (README, guía de agentes y, si procede, constitución) refleja la matriz de acceso y los contratos que cambian.
8. Todo lo no ejecutado se declara como tal.

## Dudas abiertas

Ninguna. Las decisiones P1 y P9 se incorporaron a los RF correspondientes (RF-002, RF-007, RF-008). Las observaciones del reviewer (lista cerrada sin enumerar, juego limpio/desempate, progresión, paginación, prórroga, error de query params) se resolvieron en esta revisión: RF-015 referencia la lista cerrada, RF-011 se acotó a datos disponibles, RF-007 se acotó a datos ya publicados, RF-008/RF-009 fijan la paginación y la actualización, RF-005 declara la detección de prórroga y RF-019 acota el error de query params.
