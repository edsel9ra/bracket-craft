# Spec 022 — Estadísticas deportivas públicas y porterías imbatidas

Estado: implementada y aprobada por el reviewer (segunda vuelta de validación, 2026-10-27): APROBADO. T1–T22 cerradas; verificación: 73/73 pruebas puras, vue-tsc y nuxt build OK, compileall OK, auditoría frontend sin high. Suites opt-in con PostgreSQL, pnpm test/typecheck/build y jobs security/e2e declarados no ejecutados en este entorno.

## Contexto y objetivo

La consulta pública ya ofrece clasificación, llaves y partidos, pero no ofrece ninguna estadística deportiva más allá de la clasificación: los eventos del acta (goles, tarjetas, asistencias) no se publican en ninguna proyección y el concepto de «portería imbatida» **no existe** en el sistema. Esta spec (tercera de tres) cierra las tablas de estadísticas de jugadores y de equipos y define con precisión la portería imbatida, incluyendo sus casos límite. Depende de la spec 020 (acceso público y tabla) y de la 021 (formaciones publicadas, fuente del portero).

**Objetivo:** que el público consulte tablas de estadísticas **consistentes con los resultados confirmados**, con fotografías cuando exista autorización, y que una portería imbatida signifique siempre lo mismo con una regla única, explícita y documentada, sin ampliar lo público más allá de lo mínimo necesario ni tocar lo protegido ni el contrato interno de reglas.

### Comportamiento actual verificado

| # | Hecho verificado |
|---|---|
| 1 | La clasificación pública cuenta partidos finalizados o de resolución administrativa con resultado confirmado y usa el **marcador final** (incluye prórroga y excluye la tanda de penales). En un walkover cuenta el marcador derivado de la configuración (3-0 por defecto). |
| 2 | Los eventos del acta (siete tipos cerrados: gol, autogol, gol de penalti, amarilla, roja, sustitución, falta) y la asistencia opcional del gol **no se publican en ninguna proyección ni ruta pública**. La spec 015 dejó expresamente fuera las estadísticas por jugador y cualquier superficie pública nueva. Un autogol suma al equipo beneficiario. |
| 3 | La alineación pública de un equipo es la formación táctica **solo si se publicó explícitamente**; si no, la planilla; si existe formación sin publicar, no se publica ni la formación ni la planilla. De varias formaciones publicadas por segmento se publica la **última**, así que el cálculo de estadísticas no puede leer de ahí «todas» las formaciones y necesita una proyección interna propia (ver «Contratos que cambian»). |
| 4 | La identidad del portero solo consta como la **posición `GK` dentro de una formación táctica** (por segmento y equipo). La planilla no tiene posiciones, los jugadores no tienen posición habitual y una sustitución no registra la posición del jugador que entra. |
| 5 | La foto de un jugador pertenece a su **inscripción en el torneo** y solo se publica con **consentimiento de imagen**; se entrega como enlace temporal firmado y, si la firma falla, la respuesta sigue siendo correcta con la foto en nulo. Hoy solo aparece en las alineaciones. |
| 6 | Un partido puede tener cualquier número de segmentos (ventanas de tiempo), interrupciones y una duración reglamentaria configurable; un gol cuyo minuto supera el reglamentario es de prórroga. Un **walkover** no tiene eventos, segmentos ni planilla. La resolución administrativa fija ganador y motivo. Los eventos de un acta confirmada son inmutables. |
| 7 | La edad, el documento y la fecha de nacimiento nunca se publican. Existe una proyección interna de jugadores que ningún endpoint consume. |
| 8 | La formación solo es pública después de publicarse explícitamente desde el Workspace. Las versiones de torneo son inmutables una vez publicadas. |

## Usuarios

- Aficionado, familiar, jugador o prensa que consulta un torneo **sin cuenta**.
- Administrador de organización y operador, que publican formaciones y deciden el consentimiento de imagen (no cambian).
- Jugador (o su tutor), cuyos datos personales y foto deben seguir protegidos.

## Roles y visibilidad

- **Público (sin sesión):** ve, de torneos visibles públicamente, las tablas de estadísticas de jugadores y de equipos y las porterías imbatidas, con fotos cuando exista autorización. No ve documentos, fechas de nacimiento, edad, asistencias, sanciones ni suspensiones.
- **Miembro de organización (incluido observador):** sin cambios.
- **Administrador de organización / operador:** sin cambios; publican formaciones y gestionan el consentimiento de imagen como hoy.
- **Administrador de plataforma:** sin cambios.

## Historias de usuario

- HU-1. Como aficionado, quiero tablas de estadísticas de jugadores y de equipos con fotos cuando existan, para seguir a goleadores y equipos destacados.
- HU-2. Como aficionado, quiero que una portería imbatida signifique siempre lo mismo y que la regla esté a la vista, para confiar en la cifra.
- HU-3. Como administrador de organización, quiero que una foto sin consentimiento nunca aparezca en una tabla, para controlar lo que mi organización muestra.
- HU-4. Como jugador (o tutor), quiero que mi documento, fecha de nacimiento y edad no salgan nunca y que mi foto solo se vea si lo autoricé, para proteger mi privacidad.
- HU-5. Como operador, quiero que cerrar un acta actualice por sí solo las tablas públicas, para no repetir trabajo.

## Definiciones

- **Torneo visible públicamente:** versión publicada, estado publicado, en juego o finalizado, y organización activa.
- **Partido con resultado confirmado:** partido finalizado o de resolución administrativa cuyo resultado está confirmado. Es el único tipo de partido que puede contribuir a una estadística. Un partido programado, en juego, suspendido o cancelado no contribuye.
- **Partido disputado:** partido con resultado confirmado cuya resolución es reglamentaria, prórroga o penales.
- **Partido disputado por un jugador:** partido con resultado confirmado en el que el jugador tiene al menos un evento acreditado (gol, gol de penalti, tarjeta, sustitución) o figura en la alineación publicada (titular o suplente). Una sustitución acredita a **ambos** jugadores implicados: el que sale y el que entra. Se usa para el desempate «menos partidos disputados».
- **Partido resuelto fuera del campo:** partido con resultado confirmado cuya resolución es **walkover** o **administrativa**. El walkover no tiene eventos, segmentos ni planilla; su marcador sale de la configuración y no de lo ocurrido en juego.
- **Gol de un equipo:** gol, gol de penalti o autogol **del rival** acreditado a ese equipo por el acta. **Gol recibido por un equipo:** gol de un jugador del rival (gol o gol de penalti) más el autogol de un jugador **propio**. La **tanda de penales no es gol**: el marcador del sistema la guarda aparte del resultado y no genera eventos.
- **Gol reglamentario / de prórroga:** el gol cuyo minuto no supera / supera la duración reglamentaria de la fase.
- **Plantilla inscrita:** lista de jugadores inscritos de un equipo en el torneo (con dorsal). No dice quién juega un partido concreto ni dónde.
- **Planilla del partido (alineación sin formación):** titulares y suplentes convocados de un equipo en un partido, sin posiciones.
- **Formación táctica:** código del catálogo cerrado de formaciones (`4-3-3`, `4-4-2`, `3-5-2`, `4-2-3-1`) más la posición asignada a cada titular, guardada por segmento y equipo y publicada explícitamente.
- **Portero identificable:** jugador que ocupa la posición `GK` en una formación táctica del equipo en el partido. Sin formación táctica no hay portero identificable.
- **Juego limpio:** puntos de juego limpio asignados al equipo según la disciplina del partido, tal como los calcula la clasificación.

## Portería imbatida — definición única

La portería imbatida se atribuye a **dos unidades independientes**, con definiciones separadas:

### Portería imbatida del equipo

Un equipo tiene una portería imbatida en un partido cuando **todas** las condiciones siguientes se cumplen:

1. El partido tiene **resultado confirmado**.
2. La resolución del partido es **reglamentaria, prórroga o penales** (partido disputado). Los partidos resueltos fuera del campo (walkover o administrativa) **no** cuentan para la portería imbatida del equipo, aunque sí para las demás estadísticas de equipo.
3. El equipo **no recibió ningún gol** en el partido, contando gol, gol de penalti y autogol del rival, incluidos los de prórroga. La tanda de penales **no cuenta** como gol recibido ni como gol marcado, en ningún caso.
4. El partido se considera **disputado en su totalidad** para el equipo: no hay condición de duración mínima para el equipo. Un partido terminado con menos minutos que el reglamentario pero con acta confirmada cuenta como disputado.

Se atribuye **como máximo una** portería imbatida por equipo y partido.

### Portería imbatida del portero

Un portero tiene una portería imbatida en un partido cuando **todas** las condiciones siguientes se cumplen:

1. El equipo tiene portería imbatida en ese partido (según la definición anterior).
2. El portero es **identificable**: ocupa la posición `GK` en una **formación táctica publicada** del equipo en ese partido. Sin formación táctica publicada no se atribuye ninguna portería imbatida a ningún portero.
3. El portero fue **titular** en la formación que lo identifica: el portero inicial es titular de la formación publicada del **primer segmento**; el portero **entrante** es titular de una formación publicada **posterior** en la que figura como `GK` (un suplente que nunca figura como `GK` en una formación publicada no es portero identificable).
4. El portero jugó **al menos 60 minutos** del partido. Los minutos jugados se calculan así: para un portero titular no sustituido, la duración efectiva del partido (último `minute_end` de segmento, o el máximo efectivo de la fase si no hay `minute_end`); para un portero sustituido, desde el inicio hasta el minuto de la sustitución (minuto + minuto añadido, acotado al máximo efectivo); para un portero expulsado, desde el inicio hasta el minuto de la expulsión. El cálculo usa la formación inicial y las sustituciones/expulsiones registradas en el acta, en el orden canónico (minuto, minuto añadido, índice del acta). Si el partido termina antes del reglamentario, se usa la duración real registrada.

(La condición anterior «estaba en campo durante todo el tiempo en que el equipo no recibió gol» se elimina por redundancia: si el equipo tiene portería imbatida —cero goles recibidos—, la condición siempre se cumple. Solo los goles confirmados por el acta cuentan; un gol anulado no existe.)

Se atribuye **como máximo una** portería imbatida por portero y partido.

**Fuente de la formación:** para identificar al portero titular se usa la formación táctica publicada del **primer segmento** del partido. Para identificar a un portero sustituto, se usa **cualquier formación táctica publicada** del mismo partido en la que figure como `GK`. Un portero sustituto solo se considera portero si figura como `GK` en alguna formación publicada del partido; si no figura en ninguna, no se le atribuye portería imbatida (el equipo conserva la suya).

### Criterio fijo de la estadística (no es una regla de juego)

La definición de portería imbatida y su umbral de 60 minutos son un **criterio fijo de la estadística**, no configurable por torneo ni por versión. **No** son una regla del juego: **no** se evalúan en el motor de reglas ni en el cierre del acta, y **no** alteran resultados, marcadores, clasificación, actas, sanciones, suspensiones ni el avance de fases. Son un criterio de presentación que se calcula **solo al leer** estadísticas ya derivadas de actas confirmadas. Por eso `engine_version` sigue en **2026.1** y el contrato interno de reglas no se toca, y por eso **no** se declara ninguna excepción a la constitución: el criterio no contradice ninguna de sus reglas.

Que el criterio sea fijo (y no configurable) es deliberado: una cifra pública que dependiera de una configuración por versión dejaría de ser comparable entre torneos y rompería la reproducibilidad. Sigue siendo un criterio de la estadística, no una regla deportiva configurable.

### Casos límite de la portería imbatida

| # | Caso | Equipo | Portero |
|---|---|---|---|
| 1 | Partido disputado, marcador final 0 recibidos, con formación publicada y portero titular que jugó ≥ 60 min | Sí | Sí |
| 2 | Partido disputado, marcador final 0 recibidos, portero sustituido a los 50 min | Sí | No (menos de 60 min) |
| 3 | Partido disputado, marcador final 0 recibidos, portero expulsado a los 70 min | Sí | Sí (70 ≥ 60 min; la expulsión no reduce los minutos ya jugados) |
| 4 | Partido disputado, el equipo recibió un gol y luego empató (marcador final 1-1) | No | No |
| 5 | Partido disputado, autogol de un jugador propio (cuenta como gol recibido) | No | No |
| 6 | Partido disputado con goles solo en prórroga (marcador final 0 en reglamentario) | Se evalúa con el marcador final (prórroga incluida) | Se evalúa con el marcador final (prórroga incluida) |
| 7 | Partido con tanda de penales (marcador final empatado en reglamentario y prórroga) | Sí si no recibió gol en juego | Sí si cumple el resto |
| 8 | Walkover (no tiene eventos, segmentos ni planilla) | No | No (sin portero identificable) |
| 9 | Resolución administrativa | No | No |
| 10 | Partido suspendido o cancelado | No contribuye (no es resultado confirmado) | No contribuye |
| 11 | Partido terminado con menos minutos que el reglamentario pero con acta confirmada | Sí si no recibió gol | Sí si el portero jugó ≥ 60 min |
| 12 | Equipo sin formación táctica publicada (solo planilla) | Sí si no recibió gol | No (sin portero identificable) |
| 13 | Equipo con formación táctica sin publicar | Sí si no recibió gol | No (sin portero identificable) |
| 14 | Dos porteros en el mismo partido (sustitución del portero) | Sí si no recibió gol | Se atribuye a cada uno que cumpla los criterios y sea identificable (máximo una por portero y partido) |
| 15 | Portero que marca un gol (no autogol) | Sí si no recibió gol | Sí si cumple el resto |
| 15b | Portero que marca un autogol | No (el autogol es gol recibido) | No |
| 16 | Portero expulsado y reemplazado por un jugador de campo | Sí si no recibió gol | Solo si el portero titular cumplió los criterios antes de la expulsión |
| 16b | Portero sustituto que figura como `GK` en una formación publicada posterior | Sí si no recibió gol | Sí si cumple los criterios (incluida la identificabilidad) |
| 16c | Portero sustituto que no figura como `GK` en ninguna formación publicada | Sí si no recibió gol | No (no es portero identificable) |
| 17 | Partido con dos inscripciones del mismo jugador en equipos distintos | Se atribuye por equipo y partido | Se atribuye por portero y partido; la estadística se agrega por jugador (suma de ambos equipos) |
| 18 | Jugador retirado lógicamente | Su histórico no cambia | Su histórico no cambia |
| 19 | Acta confirmada antes de la existencia de la asistencia o con identificadores de texto libre | Se lee sin error ni cifra inventada | Se lee sin error ni cifra inventada |

## Requisitos funcionales

Todo dato de una organización sigue protegido por el aislamiento entre organizaciones.

### Tablas de posiciones y de estadísticas

- **RF-001.** EL SISTEMA mostrará en cada fila de la clasificación: posición, equipo con su escudo, jugados, ganados, empatados, perdidos, goles a favor, goles en contra, diferencia de goles, puntos y puntos de juego limpio (siempre presentes en la respuesta pública). EL SISTEMA **no** mostrará el criterio de desempate aplicado, porque no existe fuente pública para ello (coherente con la spec 020, RF-011).
- **RF-002.** EL SISTEMA garantizará en cada fila de clasificación que jugados = ganados + empatados + perdidos y que diferencia = goles a favor − goles en contra, y que las filas aparecen en el orden de posición.
- **RF-003.** EL SISTEMA ofrecerá una tabla pública de **jugadores** y una de **equipos** con las estadísticas del catálogo aprobado.
- **RF-004.** EL SISTEMA calculará cada estadística **solo** con partidos con resultado confirmado de un torneo visible públicamente; un partido programado, en juego, suspendido o cancelado no contribuirá nunca, y un evento anulado heredado no se contará. Si un evento histórico referencia un jugador, equipo o segmento inexistente o de otra organización, ese evento se **excluye** del cálculo sin fallar la respuesta ni excluir el partido.
- **RF-005.** EL SISTEMA garantizará que, en cada partido disputado, los goles atribuidos a jugadores más los autogoles coinciden con los goles que el **marcador final** concede a los equipos (prórroga incluida, tanda de penales excluida; el autogol cuenta como gol recibido por el equipo del autor). La tanda de penales no es gol y no genera eventos.
- **RF-006.** EL SISTEMA incluirá en **cada tabla** de estadísticas una **columna de posición** y ordenará sus filas por su criterio principal y por desempates estables hasta un identificador estable, de modo que dos consultas con los mismos datos devuelvan el mismo orden y la misma posición; las filas empatadas en **todos** los criterios visibles mostrarán la misma posición y el orden entre ellas será el estable definido.
- **RF-007.** CUANDO una fila corresponda a un jugador con una inscripción **vigente** en el torneo, consentimiento de imagen y foto cargada, EL SISTEMA mostrará su fotografía; SI no cumple **alguna** de esas condiciones, ENTONCES EL SISTEMA mostrará las iniciales del jugador sin hueco ni imagen rota. La condición de foto es exactamente: inscripción **vigente** + consentimiento de imagen + foto cargada. Un jugador **retirado lógicamente** (`is_active` falso) **nunca** publica foto —aunque su inscripción retirada tenga consentimiento y foto cargada— y aparece siempre con sus iniciales, de forma coherente con RF-034; solo si vuelve a estar vigente (reactivación) recupera la condición de foto.
- **RF-008.** SI la preparación del enlace de una foto falla, ENTONCES EL SISTEMA responderá con normalidad con esa foto en nulo y registrará una sola entrada por respuesta, sin claves ni datos personales.
- **RF-009.** EL SISTEMA limitará y paginará cada tabla con un tope máximo de 500 filas por respuesta (reutilizando el tope vigente de los endpoints públicos) y permitirá llegar a todas las filas mediante carga adicional.
- **RF-010.** EL SISTEMA mostrará junto a cada estadística no evidente una **definición breve y visible** en español e inglés (por ejemplo, qué goles cuentan) y mostrará con texto cuando una cifra excluye partidos resueltos fuera del campo.
- **RF-011.** SI una tabla no tiene filas, ENTONCES EL SISTEMA mostrará un estado vacío explicativo, distinto de un error de carga.

### Catálogo de estadísticas

#### Jugadores

- **RF-012.** EL SISTEMA publicará una tabla de jugadores con las siguientes columnas: nombre, equipo, goles, tarjetas amarillas, tarjetas rojas y porterías imbatidas. Solo aparecerán los jugadores con al menos un evento acreditado o con presencia en una alineación publicada en un partido con resultado confirmado. La asistencia no se publica (el contrato de la spec 015 no cambia). Las sanciones y suspensiones no se publican.
- **RF-013.** EL SISTEMA contará como **gol** de un jugador cada gol y cada gol de penalti acreditado a él por el acta. Un autogol **no** cuenta como gol del jugador que lo marca.
- **RF-014.** EL SISTEMA contará como **tarjeta amarilla** y **tarjeta roja** cada una acreditada a un jugador por el acta, incluidas las de un jugador que luego fue expulsado por doble amarilla.
- **RF-015.** EL SISTEMA atribuirá la **portería imbatida** a un jugador-portero según la definición única de esta spec (equipo con portería imbatida + portero identificable en una formación publicada + titular + al menos 60 minutos jugados), sobre **todas** las formaciones publicadas del partido y no solo la última por equipo.
- **RF-016.** EL SISTEMA agregará las estadísticas de un jugador por su identidad de jugador, sumando las de todos los equipos en los que estuvo inscrito en el torneo (incluido el caso de retirada y reactivación en otro equipo).

#### Equipos

- **RF-017.** EL SISTEMA publicará una tabla de equipos con las siguientes columnas: equipo (con escudo), goles a favor, goles en contra, porterías imbatidas y puntos de juego limpio. Solo aparecerán los equipos con al menos un partido con resultado confirmado. El promedio de goles no se publica.
- **RF-018.** EL SISTEMA contará como **gol a favor** de un equipo los goles, goles de penalti y autogoles del rival acreditados por el acta. En los partidos resueltos fuera del campo (walkover), se contarán los goles derivados del marcador configurado (`walkover_score`) como goles a favor y en contra. Contará como **gol en contra** los goles y goles de penalti del rival más los autogoles propios.
- **RF-019.** EL SISTEMA atribuirá la **portería imbatida** a un equipo según la definición única de esta spec (partido disputado, cero goles recibidos, prórroga incluida, tanda excluida).
- **RF-020.** EL SISTEMA sumará los puntos de juego limpio del equipo según la disciplina del partido, tal como los calcula la clasificación.

#### Ámbito, orden y filtro

- **RF-021.** EL SISTEMA mostrará por defecto las tablas del **torneo completo**: al abrir la consulta pública no se aplica ningún filtro de fase ni de grupo y **ninguna fase se preselecciona** por ser la primera. El filtro por **fase** (y por grupo dentro de esa fase) será una **acción explícita** del usuario, ofrecida solo cuando el torneo tenga fases, reversible a «torneo completo» y visible en la pantalla; un partido cuenta en la fase a la que pertenece. El walkover y la resolución administrativa cuentan para las estadísticas de equipo (goles derivados incluidos, como la clasificación) pero no para las de portero ni para porterías imbatidas.
- **RF-022.** EL SISTEMA ordenará la tabla de jugadores por goles descendente y, en empate, por menos partidos disputados, luego por apellido y luego por identificador estable. Ordenará la tabla de equipos por goles a favor descendente y, en empate, por menos goles en contra, luego por nombre y luego por identificador estable. Ambas tablas mostrarán una **columna de posición** derivada de esos criterios: las filas empatadas en todos los criterios visibles compartirán la misma posición y la numeración continúa después del grupo empatado (por ejemplo 1, 2, 2, 4), mientras que el identificador estable solo decide el orden de presentación dentro del empate y **no** lo desempata a efectos de posición.
- **RF-023.** EL SISTEMA mostrará con texto cuando una cifra excluya partidos resueltos fuera del campo (walkover o administrativa) en las estadísticas de portero.

### Porterías imbatidas

- **RF-024.** EL SISTEMA decidirá cada atribución de portería imbatida con **una regla única, explícita y documentada** (la definición única de esta spec), acompañada de la tabla de casos límite, y **nunca** por una comprobación aislada del marcador final.
- **RF-025.** EL SISTEMA atribuirá la portería imbatida al **equipo** y al **portero**, con definiciones separadas, según la definición única de esta spec.
- **RF-026.** EL SISTEMA solo atribuirá una portería imbatida a un **portero identificable** y **nunca inferirá** el portero: SI el equipo no tiene portero identificable en el partido (sin formación táctica publicada), ENTONCES no se atribuirá a ningún portero ni se inventará uno, y la del equipo (si la regla la contempla) se conservará.
- **RF-027.** EL SISTEMA exigirá del portero la participación mínima de **60 minutos** para atribuirle la portería imbatida, según la definición única.
- **RF-028.** EL SISTEMA contará como goles recibidos los que fije el criterio aprobado (gol, gol de penalti y autogol del rival, incluidos los de prórroga), y **nunca** la tanda de penales.
- **RF-029.** EL SISTEMA tratará los partidos resueltos fuera del campo y los incompletos según la definición única y lo indicará en la leyenda de la tabla.
- **RF-030.** EL SISTEMA atribuirá **como máximo una** portería imbatida por equipo y partido y **como máximo una** por portero y partido.
- **RF-031.** EL SISTEMA mostrará la regla vigente de portería imbatida, en español e inglés, junto a toda cifra que la use.
- **RF-032.** EL SISTEMA producirá la misma cifra para los mismos datos: el acta confirmada es inmutable, así que una cifra ya calculada solo cambia al confirmarse otro partido, y los datos anteriores a la asistencia y a los identificadores actuales (actas históricas) se tolerarán sin error ni cifra inventada.

### Privacidad en tablas

- **RF-033.** EL SISTEMA publicará en las tablas de estadísticas el **nombre** del jugador aunque no tenga consentimiento de imagen y aunque no aparezca en una alineación publicada, pero su **foto solo con consentimiento de imagen y con la inscripción vigente** (condición completa de RF-007). Si no cumple las condiciones de foto —incluido el jugador retirado lógicamente—, mostrará las iniciales. **Cambio de contrato no aditivo:** publicar nombres de jugadores que no aparecen en ninguna alineación publicada amplía el conjunto de datos públicos; se declara aquí y se añade a la matriz de acceso de la spec 020. La plantilla inscrita del equipo sigue sin publicarse.
- **RF-034.** EL SISTEMA incluirá en las estadísticas a un jugador **retirado lógicamente**, con su histórico completo y **sin foto** (solo iniciales). Este requisito **prevalece** sobre cualquier lectura de RF-007: una inscripción retirada nunca publica fotografía.
- **RF-035.** EL SISTEMA **no publicará** la plantilla inscrita del equipo (lista de jugadores inscritos en el torneo) en las tablas de estadísticas; solo las estadísticas agregadas.

### Acceso público

- **RF-036.** EL SISTEMA servirá sin sesión todas las lecturas públicas nuevas (tablas de estadísticas), con las mismas reglas de la spec 020: torneo visible públicamente, «no encontrado» indistinguible si no lo es, lista cerrada de campos públicos verificada automáticamente, sin escrituras ni cookies.

## Requisitos no funcionales

- **RNF-001 (solo lectura y compatibilidad).** La consulta pública no escribe datos. Las respuestas públicas existentes solo cambian de forma **aditiva**: un cliente que ignore los campos nuevos conserva su comportamiento. Todo cambio no aditivo se declara aquí y en la documentación. `engine_version` sigue en **2026.1** y el contrato interno de reglas no se toca.
- **RNF-002 (consistencia).** Toda cifra pública se deriva únicamente de partidos con resultado confirmado y es **reproducible** a partir de ellos: mismos datos, misma cifra y mismo orden. Tras cerrar un acta, las estadísticas llegan al público en el mismo plazo que la clasificación (aviso en tiempo real o consulta periódica de 30 s como máximo).
- **RNF-003 (rendimiento acotado).** Cada respuesta pública está acotada por un tope de filas y el número de consultas a la base por respuesta **no crece** con el número de partidos ni de filas. Las fotos se firman en un solo lote por respuesta y **después** de cerrar la transacción de lectura. No se fija una latencia absoluta porque no se midió.
- **RNF-004 (accesibilidad y adaptación).** Las tablas llevan título y encabezados asociados a sus celdas; ninguna información depende solo del color; todo texto nuevo existe en español e inglés. En una pantalla de 360 px de ancho la página no desborda horizontalmente (las tablas se desplazan dentro de su contenedor).
- **RNF-005 (aislamiento y privilegios).** Toda lectura sobre datos de organizaciones respeta el aislamiento por organización en la base de datos; la aplicación no obtiene ningún privilegio para saltárselo. Cualquier cambio de esquema es **aditivo**, una migración nueva numerada, verificada sobre un volumen limpio y uno ya migrado, y no edita migraciones aplicadas.
- **RNF-006 (privacidad en registros).** Ningún registro del sistema contiene nombres, fotos, claves de objeto ni datos personales de jugadores por el uso de estas lecturas.
- **RNF-007 (verificación).** La regla de portería imbatida y el cómputo de cada estadística se verifican con casos que cubren **cada caso límite** de esta spec (una prueba por caso); la garantía de lista cerrada de campos públicos y el aislamiento entre dos organizaciones se verifican con pruebas automáticas. Pasan los cinco jobs de CI.
- **RNF-008 (documentación).** El cambio actualiza la documentación afectada del producto y de los agentes. No se publica la asistencia, por lo que no cambia el contrato de la spec 015.
- **RNF-009 (criterio fijo de una estadística derivada).** La definición de portería imbatida y su umbral de 60 minutos son un **criterio fijo y no configurable de una estadística derivada**, no una regla de juego: no se evalúan en el motor de reglas ni en el cierre del acta, no alteran resultados, clasificación, actas, sanciones ni el avance de fases, y no cambian `engine_version` (2026.1) ni el contrato interno de reglas. Por eso **no** se declara ninguna excepción a la constitución (§3.2 ni ninguna otra) y no hace falta aprobación de excepción: el criterio se calcula solo al leer.

## Datos personales y privacidad

- **Datos involucrados:** nombre y apellido, dorsal, equipo y foto de jugadores (algunos pueden ser menores); estadísticas individuales derivadas del acta (goles, tarjetas, porterías imbatidas); posición asignada en una formación publicada (fuente del portero).
- **Ya público hoy:** nombre, apellido, dorsal y posición de los jugadores que figuran en una alineación publicada; foto solo con consentimiento de imagen.
- **Nuevo con esta spec:** las **tablas de estadísticas agrupan por nombre** hechos que hoy están dispersos y aumentan la capacidad de perfilar a una persona; pueden mostrar a jugadores que no aparecen en ninguna alineación publicada. Por eso la inclusión de un jugador y de las tarjetas se decide de forma explícita (RF-033, RF-034) y no por defecto, y no se publican asistencias ni sanciones.
- **Nunca público:** documento de identidad, fecha de nacimiento, edad, año de referencia de la edad, clave de objeto de la foto, motivo de walkover o de resolución administrativa, sanciones y suspensiones de jugadores, auditoría, datos de miembros, plantilla inscrita, asistencias.
- **Foto:** solo con consentimiento de imagen **de la inscripción en ese torneo y con esa inscripción vigente**, como enlace temporal; un jugador retirado lógicamente nunca publica foto (RF-007, RF-034). Retirar el consentimiento o retirar la inscripción la oculta en la siguiente consulta, pero un enlace ya emitido sigue válido hasta caducar (riesgo ya aceptado desde la spec 014, no se amplía).
- **Estadística con un dato de formación no publicada:** atribuir una portería a un portero a partir de una formación táctica sin publicar revelaría esa posición; por eso solo se atribuye a portero con formación **publicada** (RF-026).
- **Quién puede ver qué:** el público, solo lo anterior; los miembros de la organización, lo que ya ven; ninguna otra organización ve ni modifica estos datos.

## Casos límite

La tabla de porterías imbatidas tiene **22 filas** (numeradas 1 a 19, con 15b, 16b y 16c) y son los casos límite principales: el plan y las tareas citan esos números. Adicionalmente, y numerados aparte para no solaparse con la tabla:

- **CL-1. Tabla sin filas:** estado vacío explicativo, distinto de error de carga (RF-011).
- **CL-2. Jugadores empatados** en una estadística: mismo puesto mostrado y orden estable (RF-006, RF-022).
- **CL-3. Autogol:** no es gol del jugador que lo marca; es gol recibido por su equipo y gol del rival (RF-013, RF-018).
- **CL-4. Gol de prórroga:** cuenta en goles de jugador y en goles recibidos, igual que el marcador final (RF-005).
- **CL-5. Tanda de penales:** nunca cuenta como gol, ni recibido ni marcado; las paradas de penales no se registran y no hay estadística de ellas (RF-028).
- **CL-6. Jugador con consentimiento retirado, sin foto cargada, con la inscripción retirada o con fallo de firma:** iniciales, nunca imagen rota (RF-007, RF-008).
- **CL-7. Jugador retirado lógicamente** de la plantilla: aparece con su histórico y sin foto (RF-034).
- **CL-8. Jugador con dos inscripciones en el mismo torneo** (retirado de un equipo y reactivado en otro): la estadística se agrega por jugador (RF-016).
- **CL-9. Actas históricas** (cerradas antes de la asistencia o con identificadores de texto libre): se leen sin error ni cifra inventada (RF-032).
- **CL-10. Evento anulado heredado:** no se cuenta (RF-004).
- **CL-11. Organización desactivada o torneo despublicado:** «no encontrado» indistinguible (heredado de la spec 020).
- **CL-12. Cierre de un acta mientras el visitante mira una tabla:** se actualiza sin perder filtros ni página (heredado de la spec 020).

## Fuera de alcance

- Navegación por fases y acceso público: **spec 020**.
- Formaciones gráficas y distinción formación / planilla / plantilla: **spec 021**.
- Editar resultados, actas, formaciones, consentimientos o versiones desde la consulta pública; cualquier escritura nueva.
- Cronología pública partido a partido, estadísticas en vivo minuto a minuto y marcadores en vivo nuevos.
- Estadísticas históricas entre torneos, fichas de jugador, comparativas y clasificaciones globales.
- Posiciones habituales de los jugadores, registro de la posición de quien entra en una sustitución, minutos jugados como estadística (salvo el umbral de 60 min de portería imbatida), paradas de penales y atajadas.
- Publicar asistencias, sanciones o suspensiones (el contrato de la spec 015 no cambia).
- Cambios en reglas de puntuación, desempates, disciplina o sustituciones, en `engine_version` o en el contrato interno de reglas.
- API pública documentada para terceros, exportaciones, notificaciones y optimización para buscadores o compartir en redes.

## Contratos que cambian

- **Nombres de jugadores en estadísticas (RF-033):** publicar nombres de jugadores que han participado en partidos con resultado confirmado, aunque no aparezcan en una alineación publicada, es un **cambio no aditivo** respecto al estado actual (hoy el nombre solo sale en alineaciones publicadas). Se declara aquí y se añade a la matriz de acceso de la spec 020. La plantilla inscrita del equipo sigue sin publicarse.
- **Todo cambio no aditivo se declara aquí.** En esta spec solo hay uno, el de RF-033.
- **Fuente de la formación del portero (proyección interna nueva).** La regla del portero necesita **todas** las formaciones publicadas por segmento y equipo, pero la proyección pública de alineaciones publica solo la **última** por equipo. Por eso el cálculo de estadísticas se apoya en una **proyección interna nueva** (de base de datos, no consumida por ninguna ruta pública) con todas las formaciones publicadas. **No** cambia el contrato público de la spec 021, ni `PublicTeamLineupResponse.segment_number`, ni la forma en que `/matches` publica la alineación: esa proyección solo alimenta el cálculo de la portería imbatida (RF-015, RF-026, casos 14 y 16b).
- **Cadena de esquema:** esta spec se implementa sobre las migraciones aditivas **028 → 029 → 030 → 031** (la 028 es de la spec 021; la 029, la 030 y la 031 son de esta spec y todas son aditivas, sin rollback y con *forward-fix*). `schema_version` no forma parte del contrato público.
- **No cambian:** `engine_version` (2026.1), el contrato interno de reglas, el catálogo de eventos del acta, los `code` aditivos de los 409 y la asistencia (sigue sin publicarse).

## Dependencias

- **Spec 020 (navegación y acceso público):** base. Esta spec hereda su matriz de acceso, su aislamiento por organización y su lista cerrada de campos públicos.
- **Spec 021 (formaciones gráficas):** fuente del portero (posición `GK` en formación publicada).

## Criterios de finalización

La spec está **implementada** cuando:

1. Cada RF aplicable tiene una prueba o evidencia citada y todos los casos límite de su alcance tienen un caso propio (una prueba por cada una de las 22 filas de la tabla de porterías imbatidas y por cada caso CL).
2. Las tablas de jugadores y de equipos se calculan correctamente a partir de partidos con resultado confirmado y coinciden con el marcador (RF-004, RF-005).
3. La portería imbatida se atribuye según la definición única y la tabla de casos límite, y una prueba cubre cada caso (RF-024 a RF-032).
4. Las fotos aparecen solo con consentimiento y la firma fallida no rompe la respuesta (RF-007, RF-008).
5. Una verificación automática enumera los campos de cada respuesta pública y falla ante un campo fuera de la lista cerrada (heredado de la spec 020).
6. Dos organizaciones de prueba demuestran que ninguna respuesta pública mezcla datos entre ellas (heredado de la spec 020).
7. Los cinco jobs de CI pasan.
8. La documentación refleja la regla de portería imbatida y la matriz de acceso.
9. Todo lo no ejecutado se declara como tal.

## Dudas abiertas

Ninguna. Las decisiones P2 a P8 se incorporaron a los RF correspondientes (RF-012, RF-025, RF-026, RF-027, RF-028, RF-033, RF-034). Las observaciones del reviewer (minutos del portero, identificabilidad del sustituto, formación a usar, condición redundante, tope de paginación, datos inconsistentes, RF-033 como cambio de contrato, contradicción del criterio de desempate, fair_play condicional) se resolvieron en esta revisión.

### Ronda de corrección tras la validación (2026-10-27)

Las cuatro decisiones de gobernanza de esta ronda están aplicadas aquí y no dejan dudas abiertas:

- **Caso 3 (portero expulsado a los 70 min):** se atribuye la portería imbatida (70 ≥ 60 según RF-027). El umbral solo exige minutos jugados; la expulsión no los reduce.
- **Foto del jugador retirado:** prevalece RF-034 sobre RF-007. La condición de foto es inscripción **vigente** + consentimiento + foto cargada; una inscripción retirada nunca publica foto.
- **Excepción a §3.2:** se retira. La portería imbatida es una **estadística derivada con criterio de presentación fijo**, no una regla de juego (RNF-009 reescrito).
- **Recuento de casos límite:** 22 filas en la tabla de porterías imbatidas (con 15b, 16b y 16c), ordenadas de forma consistente, más CL-1 a CL-12.

Los defectos de implementación detectados por el reviewer no cambian requisitos: se corrigen en el plan y en las tareas (T2, T4, T5, T6, T7, T9 y T10 reabiertas y T11 a T22 nuevas).
