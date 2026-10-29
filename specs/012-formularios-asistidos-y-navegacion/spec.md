# Spec 012 — Formularios asistidos, navegación independiente y traducciones pendientes

Estado: implementada (2026-10-23; aprobada el 2026-10-22 con DU-1, WP-1, NAV-1, WIZ-1, PLT-1, POS-1, CT-1, AT-1, IN-1, CI-1, RP-1, SG-1, P1, P2, P3, P4, P5, P6, FMT-1, MIN-1, MIN-2, AP-1, RC-1, RL-1, RA-1, BX-1 y EV-1 resueltas)

## Contexto y objetivo

La gestión de un torneo en el Workspace funciona, pero está concentrada: **una sola pantalla** reúne el resumen, las reglas, las fases, los equipos, las plantillas y el calendario, sus formularios se guardan cada uno por su cuenta y el índice del torneo son anclas de esa misma página. Con el torneo creciendo (varias fases, decenas de equipos, plantillas importadas) el operador debe recorrer un documento largo, no puede volver a un punto concreto ni compartir un enlace a una sección, y convive con formularios densos en los que un error de validación aparece lejos del campo que lo provoca.

Al mismo tiempo hay dos deudas concretas de presentación: las **posiciones de juego** se muestran como códigos internos, y queda un **rol de integrante** que se pinta como código crudo. Y hay una ambigüedad de dominio ya resuelta: la **duración** de un encuentro se modela como un *minuto máximo*, pero se presentaba con etiquetas que se leen como tiempo jugado, y la operación y el cierre **no aplicaban el mismo tope**.

**Objetivo:** mejorar la experiencia de uso, la navegación y los formularios de gestión de torneos —asistentes paso a paso para reglas, fases y equipos, direcciones propias para plantillas y calendario, roles y posiciones en el idioma activo y una regla de duración explícita y única— **sin alterar las reglas deportivas ni los permisos existentes**, sin duplicar funcionalidad y sin tocar el modelo de datos.

Las decisiones de producto y de contrato están resueltas y registradas abajo; no queda ninguna duda abierta.

### Ampliación: formato de juego y límites de plantilla

La última petición pide preguntar, al dar las reglas, **cómo serán los torneos** —5v5, 7v7, 9v9 o 11v11— y **cuánto es el mínimo de jugadores por equipo**, aplicándolo de verdad. Hoy **no existe ningún concepto de formato, tamaño de equipo ni mínimo de jugadores**: el editor de reglas no lo pregunta, la configuración no tiene la clave y el dominio solo conoce el catálogo cerrado de cuatro formaciones de **once** posiciones y la regla «al menos un jugador por equipo» al guardar la planilla y al cerrar el acta. La ampliación se resuelve con **tres claves nuevas** de configuración (formato declarativo, mínimo y máximo de plantilla), con **tres superficies de bloqueo** —inscribir el equipo en una fase, crear un equipo con fase destino y abrir el partido— y con avisos destacados, nunca bloqueos por tamaño, al editar la plantilla. Para poder corregir una plantilla fuera de rango se añade una **dependencia imprescindible aprobada**: el **retiro lógico** de un jugador con su reactivación (RF-051). `engine_version` se mantiene en 2026.1 porque el contrato cerrado cubre GF1/GF2 y las formaciones, no estas claves (EV-1).

### Qué ya existe y qué falta (alcance real)

Para no duplicar lo que ya está hecho, esta spec separa explícitamente lo reutilizable de lo que hay que construir:

| Capacidad | Estado hoy | Qué hace esta spec |
|---|---|---|
| Reglas de la versión (puntuación, desempates, sanciones, inscripción, resolución, excepciones) | Editor visual completo con siete bloques y modo JSON avanzado, guardado único | **Reorganizar** en un asistente por pasos; no se añade ni se retira ninguna regla |
| Fases (alta, formato, orden, inscripción de equipos) | Formulario de tres campos + lista, y la inscripción en un panel aparte | **Reorganizar** en un asistente que cubra el alta y la composición de la fase |
| Equipos (alta, código, carga masiva CSV) | Formulario + importación en el mismo panel; el alta exige una fase en la interfaz | **Reorganizar** en un asistente de **alta sin fase**; la inscripción pasa al asistente de fases |
| Administración de plantillas (convocatorias: alta individual, importación CSV/ZIP, foto, consentimiento) | Existe, **embebida** en la configuración del torneo; el alta individual está **duplicada** dentro de la operación del partido; la columna de actividad existe pero **no hay forma de retirar ni reactivar** un jugador | **Darle dirección propia**, dejarla en **una sola pantalla con formulario único** (no es un asistente), **retirar** el alta duplicada y **añadir el retiro lógico con reactivación** (RC-1, RF-051) |
| Calendario (crear partido, sortear, regenerar, listar) | Existe, **embebido** en la configuración del torneo | **Darle dirección propia**; mismo contrato de sorteo, sin segundo generador |
| Operación del partido (segmentos, planilla, oficiales, eventos, cierre) | Existe en su propia pantalla; incluye el alta de jugadores; valida minuto de eventos y de segmentos con el máximo de la fase | **Conservar** todo; **retirar** el alta de jugadores, enlazar a plantillas y **aplicar el máximo del cierre** a eventos y segmentos (DU-1) |
| Roles de integrantes traducidos | Ya traducidos en directorio, invitaciones y selector (R29 de la spec 008) | **Cerrar** el valor crudo que queda y garantizar cobertura |
| Posiciones de juego traducidas | **No** están traducidas: se pinta el código con guiones bajos sustituidos por espacios | **Construir** la localización del catálogo cerrado desde una única fuente, con regla de lado |
| Duración del encuentro | Se modela como minuto máximo; etiquetas ambiguas; operación y cierre con topes distintos | **Alinear la operación con el cierre** y fijar la nomenclatura (DU-1); la regla deportiva no cambia |
| Formato de juego y límites de plantilla | **No existen**: ni el editor ni la configuración los tienen, y el dominio solo conoce formaciones de once y «al menos un jugador por equipo» | **Añadir** la pregunta (formato declarativo, mínimo y máximo) y **aplicar** los límites de plantilla al inscribir un equipo, al crear un equipo con fase destino y al abrir el partido; el formato no altera la alineación y avisa cuando no es 11v11 |

### Estado verificado (2026-10-22)

Comprobado sobre el árbol de trabajo; se describe lo observado, no el diseño. Las rutas se citan en el apéndice B.

1. **Una sola pantalla por torneo.** La configuración del torneo contiene el resumen, el editor de reglas, el alta de fases, la inscripción de equipos en la fase, el alta de equipos, la administración de plantillas, la creación y el sorteo de partidos y la lista de partidos. El índice del torneo son seis anclas de esa misma página —resumen, configuración, calendario, equipos, plantillas y operación— y la pantalla declara **siempre** la sección «Configuración» como activa, así que al abrir el calendario o las plantillas el índice sigue señalando configuración. La entrada «Operación» del índice apunta al listado de partidos de esa página, no a la operación de un partido. La entrada «Configuración» está **oculta** a quien no tiene el permiso de gestión de torneos.
2. **Numeración y orden visibles no coinciden.** Las secciones se anuncian como «01 · Fases», «02 · Equipos» y «03 · Calendario», pero el bloque de plantillas se rotula «04 · Plantillas» y aparece **antes** del calendario.
3. **Plantillas administradas en dos sitios.** La configuración del torneo ofrece importación masiva, foto y consentimiento de imagen por jugador; la pantalla de operación del partido incluye además un formulario de **alta individual de jugador** con nombre, apellidos, documento de identidad, fecha de nacimiento, dorsal y consentimiento de imagen. La misma capacidad, dos formularios, dos sitios.
4. **Reglas en un solo envío.** El editor visual agrupa siete bloques numerados (puntuación, orden de desempates, sustituciones, disciplina, inscripción, resolución y excepciones por fase) con un único botón de guardado. La validación del cliente devuelve **todos** los errores con su campo, pero la pantalla muestra **solo el primero** y sin asociarlo al control; el resto de paneles comparten un mensaje de error al final del documento, además del error propio de cada panel.
5. **Fases y equipos acoplados.** El alta de equipo exige elegir una fase en la interfaz, y la inscripción de equipos en la fase es un panel aparte; el contrato del servidor admite registrar un equipo sin fase. La carga masiva de equipos vive dentro del panel de alta y no declara fase destino propia. Crear una fase y luego inscribir son **dos peticiones distintas**: no hay una operación conjunta.
6. **Idiomas y catálogo.** Existen **dos** idiomas —español por defecto e inglés— con un catálogo plano de 668 claves por idioma en un único módulo y persistencia en cookie. El barrido de claves usadas por las vistas contra el catálogo encuentra **una** clave inexistente: la que se usa cuando falla el sorteo del calendario; en ese caso la vista muestra el identificador de la clave.
7. **Roles.** Los cinco roles de integrante —dueño, administrador, operador, árbitro y observador— están traducidos en el directorio de miembros, en la invitación y en los selectores. Queda un valor crudo: cuando un miembro tiene un rol que no está en la lista editable (el dueño no lo es), su celda de rol pinta el código.
8. **Posiciones.** No hay traducción: la etiqueta se obtiene sustituyendo el guion bajo por un espacio, con **dos** implementaciones equivalentes (una en el catálogo de formaciones y otra copiada en la operación). Se muestran en el campo táctico público, en el modal de planilla pública y en el selector de posición de la operación. El catálogo es **cerrado**: cuatro formaciones y **23** códigos de posición distintos, con y sin lado declarado.
9. **Duración como minuto máximo.** La configuración expresa minutos reglamentarios (90 por defecto) y minutos con prórroga (120 por defecto), con valores por defecto de fase y excepciones por fase; el máximo que informa la operación es el de prórroga cuando la prórroga está habilitada. Al **operar** el tope de los eventos **y de los segmentos** es ese máximo de fase; al **cerrar** el tope de ambos depende de la resolución elegida. Con la prórroga habilitada se pueden registrar eventos y segmentos hasta el minuto 120 y cerrar como tiempo reglamentario, y el cierre los rechaza. Además, el minuto añadido solo puede superar el tope cuando el evento ocurre exactamente en el minuto del tope, de modo que un encuentro «de 90» admite registros hasta 90 + 30. El campo de minutos con prórroga está siempre habilitado aunque la prórroga esté desactivada; el cliente guarda un valor de respaldo de 180 cuando la operación no informa de los límites; y las opciones de resolución del cierre se habilitan con los valores **por defecto** de la versión, ignorando la excepción de la fase que el servidor sí aplica.
10. **Un solo selector de resolución, pero sin estado propio.** La resolución con la que se cerrará se elige en el panel de cierre; no hay ningún estado de «resolución prevista» mientras se opera, y la pantalla no lo usa para acotar nada. El borrador local del partido —eventos y marcador— se guarda en el almacenamiento local del navegador, por usuario, organización y partido, y se restaura al volver.
11. **Permisos y contratos.** La edición se condiciona al permiso de gestión de torneos; las lecturas y escrituras del alcance usan los endpoints actuales de versiones, reglas, fases, equipos de fase, equipos, plantillas, partidos, sorteo y operación. No hay endpoints nuevos previstos, y los dos cambios de contrato que esta spec propone son aditivos y compatibles (CT-1 y SG-1).
12. **No hay formato ni mínimo de jugadores.** La configuración de reglas no contiene ninguna clave de formato, tamaño de equipo ni mínimo de jugadores, y el validador rechaza cualquier propiedad no declarada. Las únicas referencias al tamaño de un equipo son: el catálogo cerrado de cuatro formaciones, todas de **once** posiciones; la validación de planilla, que exige **once titulares con posición** cuando se usa formación; y la regla mínima «al menos un jugador por equipo» al guardar la planilla y al cerrar el acta.
13. **El catálogo de formaciones es de once y cerrado.** Las cuatro formaciones se declaran una sola vez y su `CHECK` en base de datos solo admite esas cuatro; publicar una formación exige once titulares. Un formato de 5, 7 o 9 jugadores no encaja en ninguna formación existente.
14. **Dónde se podría aplicar un mínimo.** No hay validación de cantidad de jugadores en el alta individual, en la importación CSV (solo formato, tamaño de archivo y columnas) ni en la inscripción de equipos a una fase; la tabla de plantillas no impone mínimo ni máximo, solo dorsal único por equipo. Las únicas comprobaciones de cantidad viven en la planilla y en el cierre.
15. **No hay retiro de jugador.** La plantilla solo admite alta individual, importación masiva, foto y consentimiento; la columna de actividad existe en la tabla y el alta ya la escribe, pero **no hay ninguna operación que retire ni reactive** un jugador. Un equipo que supera un máximo nuevo solo puede corregirse hoy borrando filas a mano, algo que el producto no ofrece.

## Decisiones de clarificación

### Primera ronda (2026-10-22)

Resueltas con el usuario; **sustituyen** a las dudas de la fase 1. Todas son la opción recomendada.

- **DU-1 = A — La operación se alinea con el cierre.** Se conserva el criterio de duración que ya aplica al cerrar el acta y se corrige la pantalla de operación para que muestre y valide lo mismo, también en los segmentos. No cambia ninguna regla deportiva ni la configuración efectiva de una versión publicada. *Descartada:* un máximo único por fase (B), que relaja el cierre como tiempo reglamentario y cambia el significado de la resolución; y mantener la incoherencia solo documentada (C).
- **WP-1 = A — Memoria de la pestaña y paso en la dirección.** El paso actual se refleja en la dirección y los datos viven en el almacenamiento de sesión de la pestaña; recargar conserva paso y datos, y no se escribe nada en el servidor ni en almacenamiento persistente del navegador. *Descartadas:* solo memoria (B); almacenamiento persistente (C); borrador en servidor (D).
- **NAV-1 = A — Direcciones propias solo para calendario y plantillas.** Reglas, fases y equipos siguen accesibles desde la configuración del torneo, con la sección activa correcta. *Descartadas:* una dirección por sección (B); pestañas internas sin dirección (C).
- **WIZ-1 = A — Asistentes en reglas, fases y equipos; plantillas no.** La administración de plantillas conserva un formulario de **una sola pantalla** por su flujo de archivos (CSV/ZIP), fotos y consentimiento. *Descartadas:* solo reglas y fases (B); plantillas como asistente (C).
- **PLT-1 = A — «Plantillas de formularios de operación» significa la planilla del partido.** Se refiere a la alineación (titulares, banca, formación y posiciones) que se captura en la operación y se cierra en el acta; debe seguir **independiente** de la administración de plantillas del equipo. No existe ningún mecanismo de plantillas reutilizables de formularios y no se crea.
- **POS-1 = A — Nombre corto localizado por código, con la regla de lado.** Cada uno de los 23 códigos tiene una etiqueta corta en español y en inglés; el lado solo se muestra cuando el código lo declara (RF-027). El código no cambia y sigue siendo lo que viaja a la API. *Descartadas:* abreviatura internacional idéntica (B); nombre por línea sin lado (C).

### Segunda ronda, tras la revisión de QA (2026-10-22)

- **CT-1 = A — Se aprueba el cambio aditivo de contrato.** La respuesta de operación añade el máximo por resolución y las resoluciones habilitadas por la fase, declarado como **contrato que cambia** (RNF-003): aditivo, clientes antiguos intactos, superficie exacta y documentación afectada. La verificación de backend es obligatoria en los criterios de finalización. *Descartada:* deducir los máximos en el cliente a partir de la configuración, que duplicaría la regla del dominio.
- **AT-1 = A — Crear fase e inscribir no es atómico, con recuperación explícita.** El asistente crea la fase con la llamada actual y después inscribe con las llamadas actuales. Si la inscripción falla, la fase queda visible sin equipos, el asistente lo dice y permite **reintentar sobre esa misma fase sin duplicarla**. Nada de degradación silenciosa. *Descartada:* prometer atomicidad que el contrato no ofrece.
- **IN-1 = A — Solo el asistente de fases inscribe.** El asistente de equipos da de alta equipos **sin fase destino**; para inscribir se usa el asistente de fases, y desde plantillas se puede saltar a él. El backend seguirá aceptando la fase en el alta mientras exista ese contrato: la interfaz deja de usarla, no se retira el parámetro. *Descartada:* mantener la fase en el alta de equipos, que reproduce dos caminos para lo mismo.
- **CI-1 = A — Plantillas puede leer los partidos.** Para calcular el aviso de cierre de inscripción, la pantalla de plantillas puede leer los partidos del torneo con el contrato de lectura existente. *Descartada:* duplicar el cálculo del cierre en el cliente o renunciar al aviso.
- **RP-1 = A — La resolución prevista se arrastra al cierre.** Se elige una vez, se conserva al recargar la pestaña y el cierre la usa; si al cerrar se elige otra, se avisa de que los eventos y segmentos registrados pueden salir del límite y se pide confirmación explícita: sin confirmación no se cierra. Un solo control y un solo estado, sin selectores que compitan. *Descartada:* dos selectores independientes, que permiten operar con un límite y cerrar con otro sin avisar.
- **SG-1 = A — Campo opcional `resolution_type` en la creación de segmento.** La petición de `POST /api/v1/matches/{match_id}/segments` admite `resolution_type` opcional; con el campo, el servidor valida el segmento con el máximo de **esa** resolución, y sin el campo conserva el máximo de la fase (P1). Se declara en el mismo bloque de contrato que CT-1 y con la misma verificación de backend. *Descartadas:* no tocar la petición, que deja la API directa divergiendo del cierre (B); y persistir la resolución prevista en el partido, que exigiría migración (C).

### Tercera ronda, tras la segunda revisión de QA (2026-10-22)

- **P1 = A — Sin `resolution_type`, el servidor valida con el máximo de la fase.** Es el comportamiento actual y la prueba `backend/tests/test_match_minutes.py` se conserva intacta; la interfaz envía siempre la resolución prevista y el campo sigue siendo opcional y aditivo. **Corrige el valor por defecto fijado en SG-1**, que era `regular`. *Descartada:* mantener `regular` como valor por defecto, que habría cambiado el resultado de clientes existentes.
- **P2 = A — Bloquear el cambio de resolución incompatible.** Si los segmentos **ya persistidos** superan el máximo de la nueva resolución, el cambio no se permite y se pide resolver primero; no se añade contrato de corrección. *Descartada:* permitir el cambio y corregir segmentos, que exige contrato nuevo y reescribe datos del servidor.
- **P3 = A — La resolución prevista vive solo en la sesión de la pestaña.** El borrador local del formulario de cierre mantiene su comportamiento actual, pero se declara qué guarda y desde cuándo; la prevista no se mezcla con él. *Descartada:* unificar ambos en el almacenamiento local, que haría sobrevivir la prevista al cierre de la pestaña sin necesidad.
- **P4 = A — El cliente puede leer la versión publicada, sus fases y los partidos para el aviso de cierre de inscripción.** Se acepta explícitamente la duplicación de esa regla para evitar un tercer cambio de contrato, y se verifica por **equivalencia con la respuesta real 409** del servidor. *Descartada:* un endpoint de estado de inscripción, que sería contrato nuevo.
- **P5 = A — Rechazo unificado de resolución no habilitada (409).** Un único código y mensaje, `RESOLUTION_NOT_ENABLED`, aplicado a crear segmento, interrumpir y cerrar; la interrupción admite también el campo opcional de resolución y valida el minuto final. Los rechazos estructurales o de minuto fuera de rango conservan su 422. *Descartada:* un 409 por endpoint con mensajes distintos, que obliga al cliente a conocer tres variantes.
- **P6 = A — Escenario propio de operación y cierre en el arnés.** Se añade al arnés de Playwright sin tocar el escenario de reintento ni su veredicto 0/1/2/3; allí se verifica la accesibilidad —foco, teclado y anuncio de los dos mensajes— y se ejecuta con `pnpm run typecheck:e2e` y `pnpm run e2e:test`. *Descartada:* ampliar el escenario de reintento, que mezclaría dos comportamientos y podría alterar su veredicto.

### Cuarta ronda y correcciones de QA: formato, límites y plantilla

- **FMT-1 = A — Formato declarativo.** Se pregunta y se guarda en las reglas, se muestra en las vistas como contexto informativo de la modalidad —sin techos, suelos ni referencia de validación para los límites de plantilla—, pero **no** cambia formaciones ni titulares: la planilla sigue siendo de once y el contrato cerrado (`docs/contrato-reglas.md`, `engine_version 2026.1`) no se toca. La interfaz advierte de que la modalidad real en la alineación llegará con una spec de formaciones. *Descartadas:* formato con efecto real, que exigiría catálogo por modalidad, migración y cambio del contrato del motor; y admitir solo 11v11, que no responde a la petición.
- **MIN-1 = A — Los límites acotan la plantilla inscrita.** Mínimo y máximo cuentan los **jugadores inscritos** del equipo en el torneo, no los alineados ni los titulares, y son **dos claves** de configuración. *Descartadas:* límites sobre jugadores alineados, que castigan la planilla y no la plantilla; y ambos criterios a la vez, con doble clave y doble mensaje.
- **MIN-2 = B — Aviso al editar, bloqueo al inscribir y al abrir.** Editar la plantilla (alta individual, importación, foto, consentimiento) solo avisa de forma destacada y permite guardar; el bloqueo por tamaño se aplica en **tres superficies**: inscribir el equipo en una fase (en la interfaz, solo desde el asistente de fases, IN-1), crear un equipo **con fase destino** por API (BX-1) y **abrir el partido** (AP-1). El **retiro lógico** queda exento del bloqueo por jornada (RL-1) y la **reactivación** se comporta como un alta. *Descartadas:* bloquear también al editar, que impediría construir la plantilla por etapas; y no bloquear en ningún punto, que dejaría los límites sin efecto.
- **AP-1 = A — «Apertura» es abrir el partido y también se bloquea.** Abrir el partido es ponerlo en juego en la operación, que hoy ocurre al crear su primer segmento; mientras la plantilla de un equipo participante siga fuera de los límites, la apertura se rechaza con el mismo 409 `ROSTER_SIZE_OUT_OF_RANGE`, sin cambiar el estado del partido. Editar la plantilla **nunca** se bloquea: solo avisa, y una vez corregida se puede inscribir o abrir. *Descartada:* bloquear solo la inscripción, que permitiría jugar partidos con plantillas fuera de rango.
- **RC-1 = A — Retiro lógico de jugador, dependencia imprescindible aprobada.** Se añade la capacidad mínima para corregir una plantilla: **desactivar** (retirar lógicamente) y **reactivar** un jugador. La fila no se borra: se conserva el histórico, las alineaciones y los eventos ya registrados no cambian; el jugador retirado deja de contar como inscrito activo y no puede alinearse en partidos futuros; la reactivación es la vía de reversión **si el jugador no tiene ya otra fila activa en el torneo**. Mismos permisos que la gestión de plantilla, mismo aislamiento, **sin auditoría** (no está entre las acciones auditadas del proyecto, y el retiro no es una acción administrativa de plataforma). No cambia las respuestas públicas de la API ni el contrato de jugadores, aunque la proyección interna de jugadores por torneo deja de listar al retirado mientras esté inactivo. *Descartada:* el borrado físico, que rompería histórico, alineaciones y eventos.
- **RL-1 = A — El retiro lógico se permite con el bloqueo por jornada activo.** Es una excepción **explícita y única** al bloqueo vigente, porque **solo el retiro reduce la plantilla y no añade a nadie**: el alta, la importación y la **reactivación** siguen bloqueadas con su 409 actual, y únicamente el retiro queda exento. Se documenta con su motivo y no abre la puerta a otras escrituras. *Descartada:* mantener el bloqueo también para el retiro, que dejaría sin salida a un equipo por encima del máximo cuando la jornada de cierre ya está activa.
- **RA-1 = A — La excepción cubre solo el retiro; la reactivación se comporta como un alta.** Reactivar suma un jugador activo, así que queda sujeta a las mismas reglas que el alta: **409** del bloqueo por jornada mientras esté activo, y el mismo control de unicidad del jugador activo en el torneo. *Descartada:* eximir también la reactivación, que reabriría el bloqueo por la puerta de atrás.
- **BX-1 = A — El rechazo por tamaño también cubre el alta con fase destino.** `ROSTER_SIZE_OUT_OF_RANGE` se aplica además al alta individual y a la carga masiva de equipos **cuando llevan `stage_id`**, porque esa vía inscribe en la fase. El lote sigue siendo todo o nada. *Descartada:* dejarlo solo en la inscripción, que permitiría saltarse el límite creando el equipo ya inscrito.
- **EV-1 = A — `engine_version` se mantiene en 2026.1.** El contrato cerrado cubre `GF1`/`GF2` y las formaciones; `game_format`, `min_players_per_team` y `max_players_per_team` son configuración **aditiva con defaults que no cambian el comportamiento**. Se aclara el alcance en `docs/contrato-reglas.md` —que el contrato cerrado no incluye estas claves— y se documentan las claves y sus defaults en `README.md`, `AGENTS.md` y `/docs`. *Descartada:* subir `engine_version`, que declararía un cambio del contrato del motor que no existe.

## Usuarios

- **Administrador de organización con permiso de gestión de torneos:** configura reglas, fases, equipos, plantillas y calendario; es el usuario principal de los asistentes.
- **Operador de partido (árbitro u oficial):** opera segmentos, planilla, eventos y cierre; necesita ver el mismo límite que el cierre aplicará y poder llegar a la plantilla del equipo cuando falta un jugador.
- **Observador (miembro sin permiso de gestión):** consulta la configuración, el calendario y las plantillas sin poder editar; los asistentes deben serle legibles, no trampas.
- **Público:** no accede al Workspace; solo se ve afectado por la localización de las posiciones en la formación publicada.
- **Mantenedor del producto o traductor:** necesita que toda clave usada exista en los dos idiomas y que el catálogo de posiciones no se traduzca «a ojo» en cada pantalla.

## Roles y visibilidad

- **Público:** sin cambios de contenido ni de proyecciones. Único efecto visible: las posiciones de la formación publicada aparecen en el idioma activo, con el mismo dato y el mismo código por debajo.
- **Miembro sin rol:** conserva el contrato vigente (**403** en toda ruta protegida). Ninguna pantalla ni asistente nuevo le concede contexto.
- **Observador (rol `viewer`):** ve la configuración, el calendario y las plantillas en modo lectura. **Cambio de visibilidad:** la entrada «Configuración» deja de ocultarse y se muestra en solo lectura; no es un cambio de permisos y ninguna escritura se habilita (RF-038).
- **Operador y árbitro:** conservan el acceso a la operación del partido con sus reglas actuales. El alta de jugadores, que hoy solo aparece con permiso de gestión, desaparece de esa pantalla; quien lo necesite usa el enlace a la plantilla del equipo.
- **Administrador y dueño:** sin cambio de permisos. Conservan la publicación de versiones, la creación de versiones en borrador y todas las escrituras actuales, incluido el alta de jugadores, que pasa a estar solo en la administración de plantillas.
- **Administrador de plataforma:** no aplica; `/admin` queda fuera del alcance.
- **Aislamiento:** toda pantalla del alcance sigue mostrando solo datos del torneo de la organización activa. Las pantallas nuevas no aceptan identificadores de otra organización, ni los muestran, ni añaden rutas de datos: reutilizan los contratos existentes, que ya filtran por organización con el contexto de aislamiento fijado en la transacción.

## Historias de usuario

- **HU-1.** Como administrador, quiero configurar las reglas en pasos cortos y con un índice, para no perder de vista dónde estoy ni qué me falta, y para poder corregir un error sin rehacer el resto.
- **HU-2.** Como administrador, quiero que al volver a un paso anterior todo lo que ya escribí siga ahí, incluidos los valores de los pasos que no he vuelto a abrir.
- **HU-3.** Como administrador, quiero que un error de validación me diga **qué campo** y **en qué paso**, sin borrar lo que ya introduje.
- **HU-4.** Como administrador, quiero dar de alta una fase y su composición de equipos en un recorrido guiado, y saber si la inscripción falló y cómo reintentarla sin crear la fase dos veces.
- **HU-5.** Como administrador, quiero administrar las plantillas de un equipo en su propia pantalla, con la lista completa, la importación, la foto y el consentimiento en un solo lugar.
- **HU-6.** Como administrador, quiero abrir el calendario del torneo directamente, recargarlo y compartir su dirección, y volver al punto en el que estaba.
- **HU-7.** Como árbitro, quiero que la operación del partido no mezcle el alta de jugadores con el acta, y poder ir a la plantilla del equipo cuando falte alguien.
- **HU-8.** Como observador, quiero leer las posiciones y los roles en mi idioma, para entender la planilla sin conocer los códigos internos.
- **HU-9.** Como operador, quiero que la pantalla me muestre el mismo límite de minutos que el cierre va a aplicar —a los eventos y a los segmentos—, para no descubrir al cerrar que algo que la pantalla aceptó queda fuera de regla.
- **HU-10.** Como administrador, quiero retomar un asistente donde lo dejé al recargar la página, sin que el borrador se quede en el servidor ni en otro equipo.

## Definiciones

- **Asistente (wizard):** recorrido de un formulario dividido en pasos ordenados, con un índice que muestra el paso actual y el estado de cada paso, y con navegación hacia delante y hacia atrás sin perder lo introducido. Esta spec define **tres** asistentes —reglas, fases y equipos—; «wizard» es sinónimo.
- **Paso obligatorio:** no puede quedar vacío; la confirmación exige que esté completo y válido.
- **Paso opcional:** puede quedar sin configurar; se guarda con su valor vigente —el predeterminado o el que ya tenía la versión— y el índice lo marca como **omitido**, nunca como incompleto ni como error (RF-009).
- **Paso alternativo:** conjunto de pasos del que se elige **exactamente uno**. El índice marca el elegido como completo y los demás como **alternativos**; no elegir ninguno impide confirmar.
- **Estado de un paso:** `completo`, `incompleto`, `con error`, `omitido` (opcional sin configurar) o `alternativo` (no elegido).
- **Paso en la dirección:** representación del paso actual en la dirección de la página, de modo que abrir o recargar esa dirección devuelva al usuario a ese paso.
- **Borrador de asistente:** estado de un asistente —paso actual y valores introducidos— mientras la pestaña está abierta. Vive en el almacenamiento de sesión de esa pestaña: no se envía al servidor, no se comparte con otras pestañas ni con otros dispositivos y se descarta al cerrar la pestaña. Recuerda el último paso visitado **también sin cambios**; en ese caso conserva solo el paso y no contiene valores. Es distinto del borrador local del partido (abajo).
- **Borrador local del partido:** estado sin guardar de la operación de un partido que **ya existe hoy** en el almacenamiento local del navegador, por usuario, organización y partido. Guarda los **eventos** registrados y los **datos del formulario de cierre** —marcador, penales, ganador y motivo—, se restaura al volver y se descarta al cerrar el acta o con su acción explícita. **No guarda la resolución prevista** y no contiene nombre, documento ni fecha de nacimiento de ningún jugador.
- **Datos válidos:** los que cumplen las validaciones del cliente que ya existen para ese formulario. La validez definitiva la determina el servidor; el cliente no relaja ni amplía ninguna regla de negocio.
- **Alta de equipo:** registro de un equipo en el torneo, con nombre y código. **No** lo inscribe en ninguna fase.
- **Inscripción:** asignación de un equipo ya registrado a una fase concreta. Es una capacidad distinta del alta y tiene su propio contrato, sus propios códigos de respuesta y un único lugar en la interfaz: el asistente de fases.
- **Plantilla (convocatoria):** lista de jugadores inscritos en un equipo dentro de un torneo, con dorsal, edad derivada, foto y consentimiento de imagen. **No** es la alineación del partido. Se administra en una pantalla propia con formulario único, **no** en un asistente.
- **Planilla (alineación del partido):** selección de titulares, suplentes, formación y posiciones de un equipo **en un partido y un segmento concretos**, que se cierra en el acta. Es lo que la petición original llamó «plantillas de formularios de operación» (PLT-1). Vive en la operación del partido y es **independiente** de la plantilla del equipo.
- **Calendario:** conjunto de partidos de una fase de una versión, con jornada, fecha, equipos, estado y resultado. Incluye las acciones de crear un partido y de sortear o regenerar el calendario. **No** incluye la operación del partido.
- **Duración:** concepto de producto para el intervalo de juego de un encuentro. En el dominio no se guarda una duración, se guardan límites en minutos:
  - **Minuto reglamentario:** valor de `regular_time_minutes` (90 por defecto). Es el minuto en que termina el tiempo reglamentario.
  - **Minuto máximo con prórroga:** valor de `extra_time_minutes` (120 por defecto). Es el minuto en que termina el encuentro si se juega la prórroga; **no** son los minutos que dura la prórroga (con 90 y 120, la prórroga añade 30).
  - **Máximo efectivo:** el minuto que se aplica a un encuentro concreto, resuelto por fase y resolución. Es el máximo con prórroga cuando la resolución es prórroga o penales y la prórroga está habilitada en la fase; en cualquier otro caso, el reglamentario.
  - **Tiempo añadido:** valor de `added_minute` de un evento. Solo puede llevar el registro más allá del máximo efectivo cuando el evento ocurre exactamente en el minuto del máximo, y siempre dentro del tope estructural.
- **Formato de juego:** modalidad declarada del torneo, de un catálogo inicial de **5v5, 7v7, 9v9 y 11v11**, con **11v11 por defecto** para preservar la compatibilidad. Es un dato **puramente declarativo e informativo**: no deriva, no acota ni condiciona el mínimo ni el máximo de plantilla, no impone un número de jugadores, y no cambia el catálogo cerrado de formaciones, los titulares ni la alineación. Cuando el formato declarado no coincide con la planilla soportada —que hoy es de once— la interfaz lo advierte. Un cambio real de modalidad en la alineación exige una spec independiente de formaciones.
- **Límites de plantilla (mínimo y máximo):** dos enteros opcionales por versión que acotan los **jugadores inscritos** de cada equipo en el torneo. Se configuran según las reglas del torneo y son **independientes del formato**: el mismo mínimo y el mismo máximo valen igual con 5v5 que con 11v11. La ausencia de la clave o el valor **0** significan «sin límite», que es el comportamiento por defecto de las configuraciones existentes. Cuando ambos son mayores que cero se exige mínimo ≤ máximo. No acotan la alineación, los titulares, la planilla ni el cierre.
- **Plantilla inscrita:** jugadores **activos** de un equipo en el torneo, es decir, las filas vigentes de su plantilla. Es lo que el alta individual, la importación, el retiro lógico y la reactivación modifican, y lo que comparan los límites de plantilla.
- **Retiro lógico:** desactivar la inscripción de un jugador sin borrar la fila. El jugador deja de contar como inscrito activo, no se ofrece para alinear en partidos futuros y conserva su histórico, sus alineaciones y sus eventos. La **reactivación** —volver a activarla— es la vía de reversión **si el jugador no tiene ya otra fila activa en el torneo**; si la tiene, el jugador ya cuenta por esa fila. No modifica los datos del jugador ni las respuestas públicas de la API, aunque la proyección interna de jugadores por torneo deja de listarlo mientras esté retirado (filtra por actividad).
- **Bloqueo por jornada (cierre de inscripción):** regla vigente que impide dar de alta jugadores e importar plantillas desde la jornada configurada. **Solo el retiro lógico** queda fuera de ese bloqueo (RL-1); la reactivación suma un jugador activo y se comporta como un alta, así que el bloqueo la alcanza (RA-1).
- **Apertura del partido:** acción de poner el partido en juego en la operación, que hoy ocurre al crear su **primer segmento**; no es un endpoint nuevo. Un partido ya abierto no vuelve a abrirse, y los segmentos posteriores no son apertura.
- **Resolución:** forma en que termina un partido —tiempo reglamentario, prórroga, penales, walkover o administrativa— que se envía al cerrar el acta.
- **Resolución prevista:** resolución con la que el operador anuncia que cerrará el acta. Se elige con **un único control y un único valor vigente** en la operación —puede cambiarse, no es inmutable—, determina el máximo efectivo que se muestra y se valida, se envía al crear o interrumpir un segmento y al cerrar, y vive **solo** en el almacenamiento de sesión de la pestaña, donde se restaura al recargar; no se guarda en el servidor ni en el borrador local del partido. Cambiarla está sujeto a RF-033 y RF-034. Por defecto es tiempo reglamentario.
- **Sesión de juego (segmento):** tramo de un partido con minuto inicial, minuto final y estado. No es una sesión de usuario; su extensión queda acotada por el máximo efectivo.
- **Sección del torneo:** cada área de gestión con identidad propia en la navegación. En esta spec: resumen, configuración (que incluye reglas, fases y equipos), calendario, plantillas y operación (de un partido).
- **Dirección propia:** ubicación del Workspace que se puede abrir, recargar y compartir de forma directa y que identifica una sola sección, en lugar de un fragmento dentro de otra pantalla.
- **Pantalla responsable:** la única pantalla que ofrece el formulario de escritura de una capacidad. Las demás pueden enlazarla, nunca replicarla.

## Flujos de navegación y estados de los formularios

Se describen como comportamiento observable, sin detallar la construcción.

### Recorridos de navegación

1. **Reglas.** Torneos → torneo → configuración → asistente de reglas. El índice muestra los pasos y su estado. Entre ellos hay un paso de **formato de juego y límites de plantilla**, donde se elige la modalidad (5v5, 7v7, 9v9 o 11v11) y, opcionalmente, el mínimo y el máximo de jugadores inscritos por equipo (0 = sin límite; el campo vacío se normaliza a 0 al salir de él; sin relación con el formato). Si el formato no es 11v11, el paso muestra la advertencia de que la planilla soportada es de once y que la modalidad real llegará con la spec de formaciones; la advertencia no bloquea. El guardado se ofrece al final y también desde el índice, siempre con el mismo contenido: la configuración completa de la versión. Al terminar, la pantalla muestra los valores devueltos por el servidor y el asistente queda en el primer paso con el estado «sin cambios».
2. **Fases.** Torneo → configuración → asistente de fases. Si se trabaja sobre una fase existente del borrador, se elige en un selector (la primera por orden, si no hay selección): sus datos se muestran en solo lectura y el asistente abre directamente la composición. Para una fase nueva, paso 1: identificar la fase (nombre, orden y formato de fase); paso 2 (**opcional**): inscribir o retirar equipos ya registrados, con el estado de cada equipo respecto de los límites de plantilla y el botón de inscribir explicado cuando está bloqueado; paso 3: revisar y confirmar. Al confirmar se crea la fase; después se aplican las inscripciones. Si la inscripción falla —por los límites de plantilla o por cualquier otro motivo—, la fase queda creada sin equipos, el asistente lo dice y ofrece reintentar sobre ella. La pantalla avisa de que el calendario **no** se regenera solo.
3. **Equipos.** Torneo → configuración → asistente de equipos. Paso 1: selección del modo de alta (`teams.entry`, nuevo, obligatorio). Paso 2: datos del equipo (`teams.details`, solo en vía individual). Paso 3 (**alternativo**): alta individual **o** carga masiva (el paso «Carga masiva» deja de aparecer en el índice; `showInIndex: false`). Paso 4: revisión con nombre y código. El alta **no** inscribe en ninguna fase. (Actualizado por la spec 027.)
4. **Plantillas.** Índice del torneo → plantillas → equipo. La pantalla muestra los jugadores del equipo, permite el alta individual, la importación con fotos, la subida de foto, el consentimiento y el **retiro lógico con reactivación**, avisa de forma destacada cuando la plantilla queda fuera de los límites configurados —sin bloquear—, avisa del cierre de inscripción cuando aplica y ofrece un enlace al asistente de fases para inscribir. Con el cierre de inscripción activo, el alta, la importación **y la reactivación** se rechazan con su 409 actual —la reactivación se comporta como un alta—, y **solo el retiro lógico** sigue disponible (RL-1, RA-1). **No** es un asistente: es un formulario único por equipo, y es la **única** pantalla que da de alta jugadores.
5. **Calendario.** Índice del torneo → calendario → fase → crear partido o sortear. Los partidos listados enlazan a su operación. Regenerar un calendario con partidos existentes pide confirmación explícita antes de reemplazarlo.
6. **Operación.** Partido → segmentos → planilla → eventos → cierre. La primera vez, el operador abre el partido creando el primer segmento: si la plantilla inscrita de algún equipo está fuera de los límites, la apertura se rechaza y el partido no queda en juego; corregida la plantilla —alta, importación o retiro lógico—, se reintenta. Con formato distinto de 11v11, la pantalla muestra la advertencia de la planilla de once. El operador elige la resolución prevista con un único control; la pantalla muestra el máximo de esa resolución y **lo envía al crear cada segmento, al interrumpirlo y al cerrar**, y lo aplica a los segmentos y a los eventos que registra. Un cambio de resolución está bloqueado si los segmentos ya guardados quedan fuera del nuevo máximo. Al cerrar, si la resolución es distinta y compatible, hay aviso y confirmación. Si falta un jugador, la pantalla enlaza a la plantilla del equipo; al volver, el partido, el segmento y el borrador local se conservan.
7. **Retorno y enlaces.** Cada sección tiene su entrada en el índice del torneo —la de operación solo cuando hay un partido en contexto—, marca como activa solo la sección abierta y conserva el torneo y, cuando la sección lo usa, la versión y la fase seleccionadas. El botón atrás del navegador devuelve a la sección o al paso anterior sin perder el estado. Una dirección antigua con fragmento de una sección que pasa a tener dirección propia **redirige** a la dirección nueva.
8. **Recarga y pestañas.** Recargar una página de asistente devuelve al mismo paso con los datos introducidos hasta ese momento. Abrir la misma dirección en otra pestaña o en otro dispositivo empieza desde el estado del servidor, sin el borrador de la primera pestaña. Cerrar la pestaña descarta el borrador del asistente.

### Qué navegaciones piden confirmación

| Acción | ¿Pide confirmación? | Qué ocurre con el borrador |
|---|---|---|
| Cambiar de paso | No | Se conserva |
| Cambiar de sección del torneo | No | Se conserva; al volver, el asistente sigue en su paso |
| Botón atrás del navegador | No | Se conserva |
| Recargar la página | No | Se conserva el paso y los datos |
| Cerrar la pestaña o el navegador | No (el navegador no lo garantiza) | Se descarta |
| Cambiar de versión o de torneo | Sí, si hay cambios | Se descarta: el borrador pertenece a una versión concreta y no se migra |
| Acción explícita «Descartar cambios» | Sí | Se descarta tras confirmar |
| Guardar con éxito | No | Se sustituye por los valores del servidor |
| Cerrar el acta con una resolución prevista distinta | Sí (RF-034), solo si es compatible | No aplica: es el cierre del partido |
| Cambiar la resolución prevista con segmentos guardados fuera del nuevo límite | No aplica: el cambio se bloquea (RF-033) | Se conserva todo; el operador debe resolver primero |

### Estados observables de un formulario o asistente

| Estado | Cuándo se observa | Qué ve el usuario | Qué se conserva |
|---|---|---|---|
| **Limpio** | Al abrir, sin cambios | Valores actuales del servidor y acciones de guardado deshabilitadas si no hay cambios | — |
| **En edición válida** | Hay cambios y ningún error conocido | Aviso de cambios sin guardar; acciones de guardado disponibles | Todos los pasos |
| **Con errores** | Hay valores que incumplen una validación conocida | Cada error junto a su campo y el paso marcado con error; nada se envía | Todos los pasos y todos los valores, incluidos los inválidos |
| **Guardando** | Envío en curso | Acciones de escritura deshabilitadas y sin doble envío | Todos los pasos |
| **Guardado** | El servidor acepta | Confirmación con los valores devueltos; estado «sin cambios» | Valores del servidor |
| **Guardado parcial** | La fase se creó y la inscripción falló | Aviso explícito, fase creada sin equipos y acción de reintentar sobre esa fase | La fase creada y la selección de equipos |
| **Rechazado por el servidor** | El servidor responde con error de negocio o de validación | Motivo comprensible en el idioma activo, sin cerrar el asistente | Todos los pasos y valores |
| **Recuperado tras recarga** | La página se recarga con el asistente abierto | El mismo paso y los mismos datos, con el aviso de cambios sin guardar | Paso actual y, si hay cambios, todos los valores de esa pestaña |
| **Solo lectura** | Versión no editable o falta de permiso | Campos legibles y sin acciones de escritura; se explica por qué | — |
| **Descarte** | Se ejecuta la acción explícita de descartar | Confirmación antes de descartar | Nada, tras confirmar |

### Estados de la operación

| Estado | Cuándo se observa | Qué ve el usuario | Qué se conserva |
|---|---|---|---|
| **Advertencia de formato** | El formato declarado no es 11v11 | Aviso visible de que la planilla soportada es de once y que la modalidad real llegará con la spec de formaciones; no bloquea | Todo |
| **Apertura bloqueada** | Se intenta crear el primer segmento con un equipo fuera de los límites | 409 `ROSTER_SIZE_OUT_OF_RANGE` con equipo, mínimo, máximo y cantidad; el partido no queda en juego | Todo; corregida la plantilla se reintenta |
| **Sin resolución prevista elegida** | Al abrir un partido sin borrador | Tiempo reglamentario como valor por defecto, con el máximo correspondiente | — |
| **Resolución prevista elegida** | El operador la elige | El máximo de esa resolución, aplicado a segmentos y eventos, y el tope de minuto añadido | La resolución, solo en la sesión de la pestaña; el borrador local del partido es un almacén aparte |
| **Registros fuera del límite** | Se intenta reducir el máximo (por cambio de resolución o de configuración) | Si hay **segmentos ya persistidos** fuera del nuevo límite, el cambio se bloquea con un mensaje claro; si solo hay **eventos del borrador**, se avisa y nada se borra ni se envía | Los datos ya guardados y, si el cambio es válido, la resolución elegida |
| **Cierre con resolución distinta** | Se intenta cerrar con otra resolución compatible | Aviso y confirmación explícita; sin confirmar, el acta sigue abierta. Si es incompatible con los segmentos guardados, no se permite | Todo el borrador |
| **Resolución no habilitada** | Se envía una resolución que la fase no habilita | 409 con el mismo mensaje en crear segmento, interrumpir y cerrar; no se escribe nada | La resolución anterior y el borrador |
| **Segmento en creación o interrupción** | Se inicia o se interrumpe un segmento | El máximo de la resolución prevista; si el minuto se excede, el 422 de rango con el máximo aplicable | La resolución, solo en la sesión de la pestaña |

## Requisitos funcionales

### Asistentes (reglas, fases, equipos)

- **RF-001.** CUANDO un usuario abra la edición de reglas de una versión, EL SISTEMA la presentará como un asistente con pasos ordenados y un índice que indique el paso actual, cuántos hay y el estado de cada uno.
  *Criterios de aceptación:*
  - En una ventana de referencia de **1280×800 píxeles**, el índice y el paso actual son visibles sin desplazar la página y se anuncian a un lector de pantalla.
  - En pantallas más estrechas el índice puede ser un control compacto que muestre el paso actual y despliegue el resto; sigue siendo visible sin desplazar el contenido del paso y anuncia el paso actual y su estado.
  - El orden de los pasos es estable mientras el asistente está abierto y el usuario puede ir a cualquiera de ellos en cualquier momento.
  - En una versión no editable o sin permiso de gestión, el asistente se muestra en solo lectura y no ofrece guardar (RF-038).
  - El contenido del formulario sigue siendo la configuración completa de la versión: ningún campo del editor actual queda inaccesible (RF-009).

- **RF-002.** CUANDO un usuario abra la configuración de fases de un borrador, EL SISTEMA la presentará como un asistente que identifique la fase, su formato y la composición de equipos que se inscribirá en ella antes de confirmar.
  *Criterios de aceptación:*
  - El asistente cubre el alta de una fase y, para una fase existente del borrador, la inscripción y la retirada de equipos.
  - Para una fase existente se elige en un selector de fases del borrador (la primera por orden, si no hay selección); sus datos de identificación se muestran en solo lectura y el asistente abre directamente la composición, sin pedir de nuevo un nombre que no se puede cambiar.
  - Es el **único** lugar donde se inscribe o retira un equipo de una fase (RF-021); no se añade edición del nombre ni del formato de una fase existente.
  - La composición es un paso **opcional**: una fase sin equipos es válida y el índice la marca como omitida (RF-006).
  - Desde la administración de plantillas se puede llegar a este asistente para inscribir (RF-017).
  - El resultado de cada petición se informa por separado: la creación de la fase y la inscripción no se presentan como un único guardado (RF-010).

- **RF-003.** CUANDO un usuario abra el alta de equipos de un borrador, EL SISTEMA la presentará como un asistente que dé de alta equipos **sin inscribirlos en ninguna fase**, cuyo **primer paso** sea la selección del modo de alta (`teams.entry`, spec 027) y que declare nombre y código (`shortCode`) de cada equipo **solo cuando la vía elegida sea la individual**; en la vía masiva no se exigen esos campos.
  *Criterios de aceptación:*
  - El asistente no pide fase destino y no envía ninguna fase al dar de alta (IN-1).
  - El contrato del servidor sigue admitiendo una fase en el alta: la interfaz deja de usarla, no se retira el parámetro.
  - Para inscribir, el usuario va al asistente de fases; el asistente de equipos enlaza a él después del alta.
  - Ninguna pantalla ofrece la inscripción dentro del alta de equipos (RF-021).
  - La obligatoriedad de `name`/`shortCode` es **condicional** a la vía elegida en `teams.entry` (spec 027, RF-004): obligatorios solo en vía `individual`; en vía `bulk` no bloquean la confirmación.
  - El paso de revisión (`teams.review`) muestra, en la vía individual, el nombre y el código de los equipos a registrar (sin logo ni otros campos); en la vía masiva muestra un **resumen de la carga**: número de filas del CSV y, si el parseo está disponible, el listado de nombre y código por fila; en caso contrario, el nombre del archivo cargado. No se envía ningún dato al servidor hasta confirmar. [NECESITA ACLARACIÓN] si el resumen debe incluir filas inválidas o solo las válidas: se asume que muestra las filas parseadas (válidas e inválidas) con su estado, sin bloquear la confirmación mientras la carga sea válida en su conjunto.

- **RF-004.** CUANDO el usuario avance al paso siguiente o retroceda a uno anterior, EL SISTEMA conservará todos los valores ya introducidos en el resto de pasos, incluidos los de pasos no visitados en ese momento, y los volverá a mostrar al regresar.
  *Criterios de aceptación:*
  - Se conservan tanto los valores válidos como los inválidos; nada se normaliza ni se vacía al navegar.
  - Se conserva la selección de versión, fase y equipo mientras el usuario permanezca en el asistente.
  - Ninguna navegación entre pasos envía una escritura al servidor.
  - La conservación se verifica con una prueba que recorre todos los pasos de ida y vuelta y compara el estado antes y después.

- **RF-005.** SI un paso contiene datos que incumplen una validación conocida, ENTONCES EL SISTEMA mostrará cada mensaje junto al campo que lo provoca y marcará ese paso como «con error» en el índice, sin descartar ni modificar ningún valor introducido y sin enviar la escritura.
  *Criterios de aceptación:*
  - Se muestran **todos** los errores conocidos del paso, no solo el primero.
  - Cada mensaje identifica el campo y está redactado en el idioma activo; ningún mensaje es el identificador interno de una clave.
  - Los valores inválidos permanecen visibles y editables; el usuario no tiene que volver a escribirlos.
  - Una prueba comprueba que un formulario con dos errores muestra dos mensajes y conserva los dos valores.
  - El mensaje se anuncia al aparecer, queda asociado al campo y se alcanza con el teclado; la verificación se hace en el escenario de navegador de operación y cierre (RNF-005, RNF-008), que comprueba el foco, el recorrido con teclado y el anuncio de los dos mensajes.

- **RF-006.** EL SISTEMA clasificará cada paso de un asistente como **obligatorio**, **opcional** o **alternativo**, reflejará ese estado en el índice y exigirá, para confirmar, que todos los obligatorios estén completos y válidos y que de cada grupo alternativo haya exactamente un paso elegido y válido.
  *Criterios de aceptación:*
  - **Reglas.** Obligatorios: puntuación, orden de desempates, disciplina, resolución y el paso de formato y límites (RF-042, RF-044). Dentro de ese paso, el **formato es obligatorio** (siempre hay un valor válido, 11v11 por defecto) y los **límites son opcionales**: sin valor significan «sin límite». Sustituciones, inscripción y excepciones por fase son pasos opcionales. El modo de texto avanzado no es un paso y es opcional.
  - El índice refleja esa diferencia: el paso de formato y límites se marca **completo** cuando el formato está presente y los límites, si existen, son válidos; un par de límites vacío no lo marca como `omitido` ni como error, porque el formato sigue siendo obligatorio; si los límites son inválidos, el paso se marca `con error`.
  - **Fases.** Obligatorios: identificación y revisión. Opcional: composición de equipos, con 0 a 64 equipos.
  - **Equipos.** Obligatorios: selección del modo (`teams.entry`, con campo `entryPath`) y revisión. Alternativos, excluyentes entre sí: alta individual **o** carga masiva. Datos del equipo (`teams.details`) es obligatorio **solo** cuando la vía elegida es `individual` (spec 027); en vía masiva su estado se clasifica según spec 027 (RF-004) y puede ser `completo` si ambos campos están rellenos y válidos, sin bloquear la confirmación. El paso de carga masiva (`teams.bulk`) tiene `showInIndex: false` (salvo cuando es el paso actual) y no aparece en el índice; su estado es `completo`/`con error`/`incompleto` si `entryPath === 'bulk'`, y `alternativo` en caso contrario. Los campos de la carga masiva (CSV, archivo) viven en el paso `teams.bulk`.
  - El índice distingue `completo`, `incompleto`, `con error`, `omitido` y `alternativo`; un paso opcional sin configurar se muestra como **omitido**, nunca como incompleto ni como error.
  - Con pasos obligatorios incompletos o sin alternativa elegida, confirmar está deshabilitado y se explica qué falta; SI el usuario intenta confirmar de todos modos, ENTONCES el sistema no envía nada y lleva al primer paso que lo impide.
  - *Alternativa descartada:* exigir todos los pasos, que obligaría a configurar sustituciones o excepciones que hoy son opcionales en el contrato.

- **RF-007.** CUANDO el servidor acepte una escritura hecha desde un asistente, EL SISTEMA mostrará los valores devueltos por el servidor y dejará el asistente en estado «sin cambios»; SI el servidor la rechaza, ENTONCES conservará todos los valores introducidos y mostrará el motivo sin cerrar el asistente.
  *Criterios de aceptación:*
  - El rechazo no vacía el formulario ni cambia de paso por sí solo.
  - El motivo mostrado procede del error del servidor o de un mensaje traducido equivalente; nunca de un cuerpo de respuesta volcado.
  - Los códigos de estado y los códigos de conflicto existentes no cambian.

- **RF-008.** SI el usuario ejecuta una acción explícita de descarte sobre un asistente con cambios sin guardar, ENTONCES EL SISTEMA pedirá confirmación antes de descartarlos y lo indicará; las navegaciones que conservan el borrador no piden confirmación.
  *Criterios de aceptación:*
  - No piden confirmación: cambiar de paso, cambiar de sección, usar el botón atrás, recargar ni cerrar la pestaña; en los cuatro primeros el borrador se conserva (RF-014).
  - Sí piden confirmación: la acción explícita de descartar y el cambio de versión o de torneo dentro del asistente, que descarta el borrador porque pertenece a una versión concreta.
  - Cancelar la confirmación mantiene al usuario en el asistente con todo su estado.
  - Confirmar el descarte devuelve el formulario a los valores del servidor y elimina el borrador de la pestaña.

- **RF-009.** EL SISTEMA conservará todas las capacidades del editor de reglas actual: los mismos bloques de configuración, el modo de texto avanzado para las opciones que el asistente no expone y el mismo contenido enviado al guardar.
  *Criterios de aceptación:*
  - Ninguna clave de configuración editable hoy deja de serlo a través del asistente o del modo avanzado.
  - El contenido enviado sigue siendo la configuración completa de la versión; no se envía un subconjunto por paso.
  - «Opcional» es una propiedad **de la interfaz**, no del contrato: un paso opcional sin configurar se envía con su valor vigente —el predeterminado o el que ya tenía la versión— y las claves que el esquema exige, como el mapa de excepciones por fase, viajan siempre, vacías si no hay excepciones. No se omite ninguna clave requerida.
  - El modo avanzado conserva su validación y su mensaje de error por criterio.
  - Ninguna regla deportiva, valor por defecto ni esquema de configuración cambia (RF-036).

- **RF-010.** CUANDO el usuario confirme la creación de una fase con composición de equipos, EL SISTEMA creará la fase con el contrato actual y aplicará después las inscripciones con las llamadas actuales; SI una inscripción falla, ENTONCES informará de que la fase quedó creada sin esa inscripción y permitirá **reintentar sobre esa misma fase sin duplicarla**.
  *Criterios de aceptación:*
  - No se presenta la operación como atómica ni se informa de un éxito total cuando hubo un fallo parcial.
  - Tras un fallo, la fase creada es identificable en la lista y el asistente ofrece reintentar la inscripción sobre ella; reintentar no crea una segunda fase.
  - Si todas las inscripciones fallan, el resultado es una fase sin equipos, visible y válida, con el aviso correspondiente.
  - La selección de equipos se conserva para el reintento.
  - El reintento mantiene el contrato de inscripción: rango admitido, rechazo de duplicados y resultados ya definidos para altas, equipos ya inscritos y retirada idempotente.
  - Quitar o asignar equipos no altera los partidos existentes y no ejecuta ningún sorteo.
  - El aviso de que el calendario no se regenera es visible antes y después de confirmar.

- **RF-011.** EL SISTEMA ofrecerá en el asistente de equipos **dos vías alternativas de alta** —individual o carga masiva—, exigirá exactamente una por confirmación y conservará las validaciones actuales de la carga masiva.
  *Criterios de aceptación:*
  - La carga masiva conserva sus columnas, su límite de filas y sus mensajes por fila (nombre, código, duplicado en la carga, dirección de logo).
  - Elegir una vía marca la otra como `alternativo` en el índice y oculta o deshabilita sus campos, sin borrar los valores ya escritos si el usuario vuelve a la otra.
  - Los campos de la carga masiva (CSV pegado y archivo) viven en el paso **`teams.bulk`**; ese es el paso que aloja la vía masiva y el que se evalúa con sus reglas propias cuando `entryPath === 'bulk'`.
  - El contenido pegado o el archivo elegido se conserva al cambiar de paso y se descarta solo al confirmar o al retirarlo explícitamente.
  - No se añade ni se retira ninguna validación del servidor.

- **RF-012.** EL SISTEMA permitirá completar los asistentes solo con teclado, asociará cada control con su etiqueta y, al cambiar de paso, moverá el foco al título del paso y anunciará el cambio.
  *Criterios de aceptación:*
  - El recorrido completo —abrir, recorrer todos los pasos, corregir un error y confirmar— se realiza sin ratón.
  - El índice de pasos es navegable y anuncia el paso actual y su estado.
  - Los mensajes de error se anuncian al aparecer y quedan asociados al campo correspondiente.
  - La verificación de teclado, foco y anuncio se hace en el escenario de navegador de operación y cierre (RNF-005, RNF-008), junto con la del formulario de operación, y no se declara cumplida por una prueba que solo inspeccione el marcado.

- **RF-013.** CUANDO el usuario se encuentre en un paso de un asistente, EL SISTEMA reflejará ese paso en la dirección de la página, de modo que la dirección identifique el paso actual y abrirla devuelva al usuario a ese paso.
  *Criterios de aceptación:*
  - Cambiar de paso actualiza la dirección sin recargar la página y sin enviar datos al servidor.
  - Abrir la dirección de un paso deja al usuario en ese paso, con el índice en el mismo estado.
  - Recargar conserva el paso.
  - La dirección de un paso nunca contiene valores del formulario.

- **RF-014.** MIENTRAS la pestaña siga abierta, EL SISTEMA conservará el borrador del asistente —paso actual y valores introducidos— en el almacenamiento de sesión de esa pestaña, de modo que recargar o cambiar de sección no pierda nada; el borrador no se comparte con otras pestañas ni con otros dispositivos y se descarta al cerrar la pestaña o la sesión. El **último paso visitado se recuerda también cuando no hay cambios**: en ese caso el borrador contiene solo el paso y ningún valor.
  *Criterios de aceptación:*
  - Recargar conserva el paso y todos los valores introducidos hasta ese momento, incluidos los que estaban en corrección.
  - Cambiar de sección y volver devuelve al usuario al mismo paso con los mismos datos, **haya o no cambios**; sin cambios, el último paso visitado se recuerda igualmente.
  - Sin cambios no se persiste ningún valor: el borrador guarda solo el paso y los valores mostrados siguen siendo los del servidor. Un objeto de valores vacío nunca se guarda.
  - Abrir la misma dirección en otra pestaña o en otro dispositivo empieza desde los valores del servidor: el borrador no se comparte.
  - Cerrar la pestaña o finalizar la sesión descarta el borrador; al volver no se recupera.
  - Nada del borrador se escribe en el servidor ni en almacenamiento persistente del navegador; la verificación lo comprueba sobre las peticiones emitidas y el almacenamiento usado.
  - El borrador se asocia al torneo, la versión y el asistente; un borrador de otro torneo u otra organización no se aplica nunca.

- **RF-015.** SI el usuario abre la dirección de un paso de un asistente **sin borrador previo** en esa pestaña, ENTONCES EL SISTEMA mostrará ese paso con los valores de partida que correspondan a su tipo, y si el paso depende de un dato que aún no existe lo mostrará bloqueado con la explicación y un enlace al paso que lo aporta.
  *Criterios de aceptación:*
  - **Reglas:** no hay estado vacío; se muestran los valores del servidor de la versión —o los predeterminados si la versión aún no tiene configuración— y el paso es editable si hay permiso.
  - **Fases:** sin fase elegida, el paso de composición se muestra bloqueado con la explicación y un enlace al paso de identificación; el resto de pasos se muestran con el formulario vacío.
  - **Equipos:** los pasos se muestran vacíos y el índice marca como incompletos los obligatorios que faltan.
  - No se redirige en silencio a otro paso: la dirección pedida se respeta. *Motivo:* el paso forma parte de la dirección y respetarlo mantiene útil el enlace compartido, sin saltos que parezcan un error.
  - Ningún caso produce una pantalla en blanco ni un error de aplicación.

### Navegación independiente: plantillas y calendario

- **RF-016.** EL SISTEMA ofrecerá una **dirección propia** para el calendario de un torneo, que se pueda abrir, recargar y compartir directamente y que muestre la misma información que hoy se ve en esa sección.
  *Criterios de aceptación:*
  - Abrir la dirección sin haber visitado otra pantalla del torneo muestra el calendario de la versión vigente del borrador —o, si no hay borrador, el de la versión publicada **más reciente**— y permite elegir fase. El modelo admite un solo borrador por torneo, de modo que «vigente» no es ambiguo.
  - Recargar la página conserva la sección, el torneo y la fase elegida.
  - Desde esa dirección se crean partidos y se sortea o regenera el calendario con los mismos contratos y confirmaciones actuales.
  - La dirección no expone identificadores de otra organización y una dirección de un torneo ajeno responde como hoy (no encontrado o prohibido), sin filtrar existencia.

- **RF-017.** EL SISTEMA ofrecerá una **dirección propia** para la administración de plantillas de un torneo, con la lista por equipo, el alta individual, la importación con fotos, la subida de foto y el consentimiento de imagen, en **un formulario único de una sola pantalla**.
  *Criterios de aceptación:*
  - Abrir la dirección directamente muestra la plantilla del equipo seleccionado —o la del primer equipo del torneo— sin depender de otra pantalla.
  - La pantalla no se divide en pasos: la importación con archivo, la foto y el consentimiento conviven con la lista (WIZ-1).
  - La lista muestra dorsal, nombre, edad derivada, foto solo con consentimiento y el estado de inscripción; no muestra documento ni fecha de nacimiento.
  - La dirección conserva el equipo seleccionado al recargar.
  - El aviso de cierre de inscripción se calcula con la **versión publicada más reciente**, sus fases y los partidos del torneo, leídos con los contratos existentes —sin endpoints nuevos— y se muestra antes de intentar la escritura (CI-1, P4).
  - El cálculo replica la regla del servidor y esa duplicación es una **decisión aceptada** (P4): se prefiere a un tercer cambio de contrato, y su verificación obligatoria es la equivalencia con la respuesta real: para el mismo torneo, cuando la pantalla avisa de cierre, la escritura responde **409** con el mensaje de cierre, y cuando no avisa, no responde 409 por ese motivo.
  - La pantalla enlaza al asistente de fases para inscribir al equipo (IN-1).

- **RF-018.** CUANDO el usuario navegue entre las secciones del torneo, EL SISTEMA marcará como activa únicamente la sección cuya dirección está abierta y ofrecerá una entrada por cada sección en el índice del torneo.
  *Criterios de aceptación:*
  - El índice ofrece resumen, configuración, calendario y plantillas, y añade operación cuando hay un partido en contexto.
  - **«Equipos» deja de ser una entrada propia del índice**: el alta y la inscripción se alcanzan desde configuración, dentro del asistente correspondiente, y abrir cualquiera de sus bloques marca configuración como sección activa (NAV-1).
  - Abrir el calendario marca calendario, no configuración; abrir las plantillas marca plantillas; abrir la operación de un partido marca operación.
  - Ninguna entrada lleva a una sección distinta de la que nombra; la operación se abre desde un partido, no desde un listado.

- **RF-019.** CUANDO el usuario use el botón atrás del navegador, EL SISTEMA lo devolverá a la sección o al paso que visitó antes y conservará el estado de destino.
  *Criterios de aceptación:*
  - Volver atrás desde plantillas devuelve a la pantalla anterior —calendario o configuración— con su selección restaurada si sigue existiendo.
  - Volver atrás desde un paso de un asistente devuelve al paso anterior con sus valores.
  - La navegación no genera entradas de historial de más: un movimiento del usuario produce un solo paso atrás.
  - Si el destino ya no es accesible (permiso retirado, recurso eliminado), se muestra el error de la sección y no una pantalla en blanco.

- **RF-020.** SI el usuario abre una dirección antigua con fragmento de una sección que pasa a tener dirección propia, ENTONCES EL SISTEMA lo **redirigirá** a la dirección nueva de esa sección, conservando el torneo y la versión en la medida en que la dirección antigua los identificaba.
  *Criterios de aceptación:*
  - Los fragmentos de calendario y plantillas redirigen a sus direcciones nuevas.
  - Los fragmentos de resumen, configuración, fases y **equipos** siguen resolviendo sobre la configuración: `#equipos` no redirige y sigue llevando al bloque de equipos, ahora dentro de la sección configuración.
  - Un fragmento de operación sin partido identificado lleva al listado de partidos del calendario, que es lo que hoy muestra, sin inventar un partido.
  - La redirección reemplaza la entrada de historial: el botón atrás no vuelve a rebotar.
  - Los marcadores guardados siguen funcionando; ningún fragmento conocido produce error y uno desconocido deja la pantalla usable.
  - No queda una copia del formulario para sostener la dirección vieja (RF-021).

- **RF-021.** EL SISTEMA mantendrá **una sola pantalla responsable** por capacidad: cada escritura del alcance se ofrece en un único formulario, y cualquier otro punto de la interfaz que la necesite enlaza a esa pantalla en lugar de replicarla.
  *Criterios de aceptación:*
  - El alta de equipo existe solo en el asistente de equipos y **no** inscribe en ninguna fase.
  - La inscripción y la retirada de equipos de una fase existen solo en el asistente de fases; ninguna otra pantalla las ofrece.
  - El alta individual de jugadores existe solo en la administración de plantillas; no queda ningún formulario de alta de jugador en la operación del partido.
  - La creación de partidos y el sorteo existen solo en el calendario; la configuración no los replica.
  - Una prueba o una comprobación de revisión demuestra que no hay dos formularios que envíen la misma escritura.

- **RF-022.** EL SISTEMA conservará en la operación del partido los segmentos, la planilla, los oficiales, los eventos y el cierre, y ofrecerá desde ella un enlace a la plantilla del equipo cuando falte un jugador.
  *Criterios de aceptación:*
  - Segmentos, planilla, publicación de formación, oficiales, eventos y cierre mantienen su comportamiento, sus códigos de respuesta y sus validaciones, salvo la regla de minuto de RF-032.
  - La alineación del partido (PLT-1) sigue siendo independiente de la plantilla del equipo: editar una no altera la otra y no comparten pantalla.
  - El enlace identifica el torneo y el equipo y lleva a la dirección de plantillas con ese equipo ya seleccionado.
  - Al volver desde plantillas se conservan el partido, el segmento seleccionado y el **borrador local del partido**, que ya existe hoy en el almacenamiento local del navegador por usuario, organización y partido y se restaura al volver.
  - El borrador local del partido mantiene su comportamiento y sus datos —eventos y formulario de cierre—, se descarta al cerrar el acta o con su acción explícita y no contiene nombre, documento ni fecha de nacimiento. **Cambio observable:** deja de guardar la resolución prevista, que pasa a vivir solo en la sesión de la pestaña (P3, RF-034); un borrador antiguo que contenga ese campo se ignora y se descarta al restaurar, sin romper la restauración de eventos ni del marcador (caso 70).

- **RF-023.** EL SISTEMA reutilizará para el calendario el mismo contrato de creación y de sorteo que ya existe, sin un segundo generador ni una segunda validación paralela.
  *Criterios de aceptación:*
  - Los límites por formato de fase, el tope de equipos, el presupuesto de cálculo y los rechazos por sorteo imposible se conservan con sus códigos actuales.
  - La semilla, los intervalos y las vueltas se siguen enviando y mostrando igual.
  - La confirmación de reemplazo de un calendario existente se mantiene.

- **RF-024.** CUANDO el usuario abra una sección del torneo, EL SISTEMA pedirá solo los recursos que esa sección muestra, reutilizando los contratos de lectura existentes y **sin descargar datos de secciones que no necesita**, salvo las lecturas que una sección justifica para su propio cálculo.
  *Criterios de aceptación:*
  - Abrir el calendario no descarga las plantillas.
  - Abrir las plantillas **puede** leer la versión publicada más reciente, sus fases y los partidos del torneo para calcular el aviso de cierre de inscripción (CI-1, P4); no descarga otros recursos.
  - No se añaden endpoints ni parámetros nuevos para conseguir esto.
  - Cada sección conserva el mismo contrato de paginación que usa hoy.

### Traducciones

- **RF-025.** CUANDO se muestre el rol de un integrante del vocabulario conocido —dueño, administrador, operador, árbitro y observador—, EL SISTEMA mostrará su nombre traducido al idioma activo, incluido el rol que no es editable.
  *Criterios de aceptación:*
  - Los cinco roles se muestran traducidos en el directorio de miembros, en la invitación, en los selectores de rol y en cualquier resumen que los nombre.
  - El rol `owner`, que no se puede cambiar desde el directorio, se muestra traducido igual que los demás.
  - La etiqueta se obtiene de una **única** fuente de verdad; no se repite el vocabulario de roles en varias pantallas.
  - La precedencia de roles mostrada y la autorización no cambian; el rol mostrado es presentación y no concede permisos.

- **RF-026.** SI aparece un código de rol que no pertenece al vocabulario conocido, ENTONCES EL SISTEMA mostrará el valor recibido tal cual, sin inventar una traducción ni dejar el hueco vacío.

- **RF-027.** CUANDO se muestre una posición de juego en cualquier vista del alcance, EL SISTEMA mostrará su nombre corto traducido al idioma activo para los **23** códigos del catálogo cerrado de formaciones, añadiendo el lado **solo cuando el código lo declare**.
  *Criterios de aceptación:*
  - El lado se muestra si y solo si el código lo declara: sufijo `_L`/`_R` (`CM_L`, `CM_R`, `ST_L`, `ST_R`, `CDM_L`, `CDM_R`), prefijo o sufijo de lateral o carrilero (`LB`, `RB`, `LWB`, `RWB`) y pares con inicial de lado (`LCM`, `RCM`, `LCB`, `RCB`, `LM`, `RM`, `LW`, `RW`).
  - Sin lado declarado, la etiqueta no lo menciona: `GK`, `CB`, `CM`, `ST` y `CAM`.
  - Cada uno de los 23 códigos tiene su clave en los dos idiomas; el apéndice C fija la tabla de pares como referencia verificable.
  - La cobertura incluye el selector de posición de la operación, el campo táctico público, el modal de planilla pública y cualquier lista o resumen que nombre una posición.
  - La etiqueta se obtiene de una **única** fuente de verdad: no queda ninguna conversión duplicada ni literales de posición en otras pantallas.
  - El código de la posición no cambia en la API, en la base de datos ni en las respuestas públicas: es lo que viaja; solo se localiza lo que se muestra.

- **RF-028.** SI aparece una posición fuera del catálogo, o si falta la clave de texto de una posición conocida, ENTONCES EL SISTEMA mostrará el código recibido tal cual, sin espacios inventados ni etiqueta vacía.

- **RF-029.** EL SISTEMA garantizará que toda clave de texto usada por una vista del alcance exista en los dos idiomas soportados, de modo que ninguna vista muestre el identificador de una clave.
  *Criterios de aceptación:*
  - La comprobación automática de claves usadas contra el catálogo termina sin ausencias, incluida la que hoy falta en el aviso de fallo del sorteo.
  - El catálogo conserva la paridad entre español e inglés: mismas claves en ambos.
  - Cambiar de idioma en mitad de un asistente conserva todos los valores y traduce las etiquetas y los mensajes.
  - Las fechas y números se siguen formateando según el idioma activo.

- **RF-030.** EL SISTEMA no traducirá datos: nombres de equipos y de personas, códigos de equipo, códigos de llave y la notación de las formaciones se muestran tal como llegan.

### Duración del encuentro

- **RF-031.** CUANDO se muestre la duración de un encuentro, EL SISTEMA la presentará con la semántica del dominio: los minutos reglamentarios y el máximo con prórroga se muestran como el **minuto en que termina** el encuentro, y la prórroga no se presenta como tiempo jugado.
  *Criterios de aceptación:*
  - La etiqueta del máximo con prórroga no se puede leer como «minutos de prórroga»; se distingue del valor reglamentario.
  - Con la prórroga desactivada, el campo de minutos con prórroga se muestra **deshabilitado** y conserva el valor que se aplicaría si se habilitara; no se borra al deshabilitar la prórroga. *Alternativa descartada:* dejarlo editable y marcarlo «no aplicable», que permite escribir un valor sin efecto.
  - El par de minutos se fija con las mismas reglas que hoy: reglamentario entero entre 1 y 179; con prórroga habilitada, mayor que el reglamentario y menor o igual a 180; el cliente rechaza el par inválido y el servidor sigue siendo la autoridad.
  - La operación muestra el máximo efectivo de la resolución prevista y el tope de minuto añadido; no usa un valor de respaldo distinto del que informa el servidor.
  - La misma palabra se usa en la configuración, en la operación y en la documentación del producto.

- **RF-032.** EL SISTEMA aplicará **al registrar eventos, al iniciar o interrumpir segmentos y al cerrar** el mismo máximo de minuto para la resolución prevista, de modo que ningún registro aceptado al operar sea rechazado al cerrar por exceder el máximo; sin resolución indicada, el servidor conserva el criterio que aplica hoy.
  *Criterios de aceptación:*
  - El máximo efectivo de una resolución es el máximo con prórroga cuando la resolución es prórroga o penales y la prórroga está habilitada en la fase; en cualquier otro caso, el minuto reglamentario.
  - La operación y el cierre consumen el mismo cálculo para eventos y para segmentos: se puede citar un único punto del dominio que lo define y ninguna de las dos pantallas lo recalcula con otro criterio.
  - La creación de un segmento y su interrupción informan la resolución prevista y **el servidor valida con el máximo de esa resolución**, no con el máximo de la fase (SG-1, P5).
  - SI la petición llega **sin** resolución, ENTONCES el servidor aplica el **máximo de la fase**: es el comportamiento actual, la prueba de minutos existente se conserva sin cambios y ningún cliente antiguo cambia de resultado (P1).
  - SI el minuto supera el máximo aplicable, ENTONCES el rechazo conserva el **422** que la API ya devuelve hoy para ese caso, con su semántica intacta; el límite que se nombra es el del máximo aplicable.
  - SI la resolución indicada no está habilitada por la configuración efectiva de la fase —incluida su excepción—, ENTONCES la creación de segmento, la interrupción y el cierre se rechazan con **un único** código y mensaje: **409** con `code: RESOLUTION_NOT_ENABLED` y el mismo `detail` en los tres (P5). No se crea el segmento, no se registra la interrupción y no se cierra el acta.
  - El tope sobre minuto más minuto añadido se conserva para los eventos: antes del minuto final la suma no puede pasar el máximo y en el minuto final se admite el añadido dentro del tope estructural.
  - Una prueba de servidor cubre: sin resolución → máximo de fase (prueba existente intacta); con tiempo reglamentario → límite reglamentario; con prórroga o penales habilitados; y con un valor no habilitado → 409 `RESOLUTION_NOT_ENABLED` en los tres puntos.
  - El escenario de navegador de operación y cierre (RNF-005, RNF-008) registra **un segmento y un evento en el límite que muestra la pantalla** —el segmento vigente termina en el minuto máximo y el siguiente empieza en ese mismo minuto, y el evento se registra en ese límite—, cierra con esa resolución sin rechazo por minuto y comprueba que intentar superar el máximo en un segmento y en un evento muestra el aviso correspondiente como `role="alert"` visible, con el máximo aplicable en el texto, sin crear el segmento ni añadir el evento. El aviso **no es enfocable** y el control que lo provoca queda deshabilitado durante la petición: el escenario verifica el anuncio y que no se escribe nada, y **no** promete un movimiento de foco al mensaje que el producto no hace.
  - La configuración efectiva de ninguna versión se reescribe ni se recalcula por este cambio.

- **RF-033.** CUANDO el operador registre eventos o inicie segmentos, EL SISTEMA le mostrará la resolución prevista, el máximo de minuto que se le aplicará y el tope de minuto añadido, y validará cada registro contra ese máximo antes de enviarlo.
  *Criterios de aceptación:*
  - La resolución prevista se elige con **un único control y un único valor vigente** en la operación; puede cambiarse (RF-034), no es un valor inmutable. Por defecto es tiempo reglamentario.
  - La pantalla envía la resolución prevista al crear cada segmento, al interrumpirlo y al cerrar; no envía otra resolución distinta de la mostrada.
  - SI los **segmentos ya persistidos** en el servidor superan el máximo de la nueva resolución, ENTONCES el cambio **no se permite**: se explica que hay segmentos registrados fuera del nuevo límite y se pide resolver primero esa situación. No se ofrece ni se promete corregir segmentos ya guardados.
  - SI solo hay **eventos en el borrador** por encima del nuevo máximo, ENTONCES el cambio sí se permite, se avisa de los eventos afectados y ninguno se envía ni se borra hasta que el operador los corrija o cierre.
  - Solo se ofrecen las resoluciones habilitadas por la configuración **efectiva de la fase**, incluida su excepción, y no por los valores por defecto de la versión.
  - El rechazo previo del cliente y el aviso de límite usan el máximo de la resolución prevista, no el máximo de la fase.
  - La pantalla indica si el máximo procede del tiempo reglamentario o de la prórroga habilitada en la fase.
  - SI el servidor rechaza por resolución no habilitada, ENTONCES se muestra el 409 unificado sin perderse el borrador; si rechaza por minuto fuera de rango, se conserva el 422 actual y se ofrece corregir el minuto.

- **RF-034.** EL SISTEMA conservará la resolución prevista al recargar la pestaña, la usará como resolución del cierre y, SI al cerrar se elige otra **compatible**, ENTONCES avisará de que los eventos del borrador pueden salir del límite de la nueva resolución y pedirá confirmación explícita antes de cerrar.
  *Criterios de aceptación:*
  - La resolución prevista vive **solo** en el almacenamiento de sesión de la pestaña, asociada a usuario, organización y partido, y se restaura al recargar; no se escribe en el servidor ni en el borrador local del partido (P3).
  - El borrador local del partido **deja de persistir** la resolución prevista: si un borrador antiguo contiene ese campo, se ignora y se elimina al restaurar, conservando los eventos y el marcador (caso 70).
  - El cierre envía la resolución prevista con un único control, sin un segundo selector que permita cerrar con otra sin avisar.
  - Cambiar la resolución en el cierre exige confirmación explícita; sin confirmación no se cierra y el acta queda abierta.
  - SI los segmentos ya persistidos superan el máximo de la resolución elegida, ENTONCES el cambio no se permite (RF-033) y el acta sigue abierta: no hay confirmación posible para un cambio incompatible.
  - La confirmación indica qué eventos del borrador quedan por encima del nuevo límite, si los hay.
  - Con la resolución prevista confirmada, el cierre se comporta como hoy y conserva sus códigos de respuesta y sus validaciones, salvo el 409 unificado de resolución no habilitada.

- **RF-035.** EL SISTEMA no revalidará ni modificará las actas cerradas ni las versiones publicadas al alinear la operación con el cierre.
  *Criterios de aceptación:*
  - Un acta confirmada conserva sus eventos, sus segmentos, su resolución y su resultado; no se recalcula ni se le aplica la regla nueva.
  - La configuración efectiva de una versión publicada no se reescribe; un partido de una versión publicada sigue aplicando la configuración de esa versión.
  - En un borrador, un cambio de los minutos avisa antes de guardar si deja eventos o segmentos ya registrados fuera del máximo, y no los borra ni los reescribe.
  - Las actas cerradas no se reabren ni se corrigen por esta spec.

- **RF-036.** EL SISTEMA conservará los límites deportivos vigentes —el minuto reglamentario admitido, la relación entre reglamentario y prórroga, el tope estructural de minuto y el tope de minuto añadido— sin añadir campos de duración al modelo.
  *Criterios de aceptación:*
  - Las validaciones del servidor y del cliente sobre estos valores se mantienen, con sus mismos mensajes de rechazo.
  - Las versiones guardadas no se reescriben y ninguna regla de resolución cambia.
  - No se añade ningún campo de duración al modelo deportivo ni a las respuestas públicas; los campos **aditivos** aprobados en CT-1 solo informan de máximos que el servidor ya calcula y no cambian el significado de los existentes (RNF-003).
  - *Alternativa descartada (DU-1 B):* un único máximo por fase, que aceptaría eventos de prórroga cerrados como tiempo reglamentario y cambiaría el significado de la resolución.

- **RF-037.** EL SISTEMA documentará la regla de duración en la documentación del producto, en un solo lugar y sin contradecir la constitución.
  *Criterios de aceptación:*
  - La regla —minuto reglamentario, máximo con prórroga, máximo efectivo, tiempo añadido y resolución prevista— se describe una sola vez y el resto de documentos la referencian.
  - La actualización de la documentación afectada (`README.md` y `AGENTS.md`) forma parte del cambio, como exige la §4 de la constitución para todo comportamiento observable.
  - No quedan dos descripciones distintas de la misma regla ni una que contradiga a la interfaz.

### Permisos y continuidad

- **RF-038.** EL SISTEMA respetará los permisos vigentes en todas las pantallas y asistentes del alcance, y ajustará únicamente la **visibilidad** de la sección de configuración para que un observador pueda consultarla en solo lectura.
  *Criterios de aceptación:*
  - Sin permiso de gestión, los asistentes y las pantallas se muestran en solo lectura y no ofrecen ninguna acción de escritura.
  - La entrada «Configuración» deja de ocultarse a quien no tiene el permiso de gestión y abre la sección en solo lectura; es un cambio de **visibilidad**, no de permisos. *Alternativa descartada:* mantenerla oculta, que impediría al observador consultar reglas, fases y equipos, objetivo declarado de esta spec.
  - La verificación comprueba los dos lados: un observador ve la sección y no ve ninguna acción de escritura; un miembro con permiso sigue viendo y pudiendo escribir lo mismo que hoy.
  - Ningún rol gana ni pierde permisos y no se añaden permisos nuevos.
  - Un miembro sin rol conserva el rechazo vigente y no obtiene contexto por ninguna pantalla nueva.

- **RF-039.** EL SISTEMA mantendrá al servidor como autoridad de validación: el cliente no relajará, replicará ni sustituirá ninguna regla de negocio, con la **única** excepción declarada del aviso de cierre de inscripción, y todo rechazo del servidor se mostrará sin perder los datos introducidos.
  *Criterios de aceptación:*
  - Los asistentes y la operación no inventan límites distintos de los del servidor; si el servidor rechaza un valor que el cliente aceptó, el mensaje se muestra y el valor se conserva para corregirlo.
  - **Excepción declarada (P4):** el aviso de cierre de inscripción replica en el cliente la regla del servidor. Se acepta para no añadir un tercer cambio de contrato, y se verifica por equivalencia con la respuesta real: cuando el aviso aparece, el servidor responde **409** con el mensaje de cierre; cuando no aparece, no hay 409 por ese motivo. La réplica es solo informativa y nunca impide ni sustituye la validación del servidor.
  - Ninguna otra regla de negocio se replica en el cliente; la comprobación de revisión enumera las réplicas existentes y solo admite esta.
  - El mensaje mostrado está en el idioma activo cuando el cliente puede determinarlo; cuando el servidor responde en otro idioma, se muestra el mensaje traducido equivalente y el detalle del servidor queda disponible, sin mezclar idiomas en la misma frase.
  - Los códigos de estado, los códigos de conflicto y los campos de error existentes no cambian, salvo el 409 nuevo y unificado de resolución no habilitada (RNF-003).

- **RF-040.** EL SISTEMA mantendrá el aislamiento por organización sin cambios: toda pantalla, asistente y enlace del alcance opera sobre el torneo de la organización activa, y ninguna organización puede ver ni modificar datos de otra.
  *Criterios de aceptación:*
  - Las pantallas nuevas no aceptan identificadores de torneo, versión, fase o equipo de otra organización, y responden como hoy cuando se intenta.
  - Ni el borrador de un asistente ni la resolución prevista se aplican sobre un torneo de otra organización.
  - No se añaden endpoints, consultas ni proyecciones; se reutilizan los contratos que ya fijan el contexto de organización en la transacción.
  - Las comprobaciones de aislamiento existentes siguen pasando.

- **RF-041.** EL SISTEMA conservará los flujos actuales: publicar una versión, crear una versión en borrador, sortear y regenerar el calendario, inscribir y retirar equipos de una fase, importar plantillas, gestionar fotos y consentimiento, y operar y cerrar un acta.
  *Criterios de aceptación:*
  - Los códigos de respuesta actuales de esas operaciones se mantienen.
  - Las confirmaciones actuales se conservan y ninguna se sustituye por una escritura silenciosa.
  - Las pruebas existentes de reglas, inscripción de equipos, plantillas y sustituciones siguen pasando sin cambios de contrato.

### Formato de juego y mínimo de jugadores

- **RF-042.** CUANDO el usuario edite las reglas de un borrador, EL SISTEMA le preguntará el **formato de juego** del torneo en un paso propio del asistente, con un catálogo inicial de exactamente cuatro opciones —5v5, 7v7, 9v9 y 11v11—, y guardará la elegida en la configuración de la versión.
  *Criterios de aceptación:*
  - Las cuatro opciones se muestran en español y en inglés, con su etiqueta legible y sin literales duplicados; ninguna otra opción es aceptable en el catálogo inicial.
  - El valor por defecto de una configuración que aún no lo tiene es **11v11**, para preservar la compatibilidad con lo que ya existe.
  - El paso se comporta como los demás: obligatorio, con el formato declarado visible en la revisión, y solo editable en un borrador (RF-038, RF-001).
  - En una versión publicada o archivada el formato se muestra en solo lectura y no se reescribe.
  - Cambiar el formato no altera inscripciones, fases, calendario, límites de plantilla ni partidos (caso 54).

- **RF-043.** EL SISTEMA tratará el formato como **dato puramente declarativo e informativo**: describe la modalidad del torneo y se muestra en las vistas, y **no** deriva, acota ni condiciona el mínimo ni el máximo de plantilla, ni cambia el catálogo cerrado de formaciones, los titulares o la alineación.
  *Criterios de aceptación:*
  - El formato **no** es referencia de validación de los límites: no hay tamaño de referencia, techo ni suelo derivados de la modalidad. Los mismos valores de mínimo y máximo son válidos con 5v5 y con 11v11 (caso 55).
  - Declarar 5v5, 7v7 o 9v9 **no** habilita formaciones nuevas, no reduce los once titulares y no altera la planilla: `docs/contrato-reglas.md` y `engine_version 2026.1` no se tocan y la base sigue admitiendo solo las cuatro formaciones. El documento aclara que el contrato cerrado cubre `GF1`/`GF2` y las formaciones, y **no** estas claves de configuración (EV-1).
  - La planilla soportada es de once. CUANDO el formato declarado sea distinto de 11v11, EL SISTEMA mostrará una **advertencia visible** en tres lugares: el paso de reglas, el resumen de configuración del torneo y la pantalla de operación y planilla. El texto indica que la modalidad real en la alineación llegará con la spec de formaciones; la advertencia **no bloquea** ninguna acción.
  - Con el formato 11v11 la advertencia no aparece; el formato se muestra como contexto informativo junto a los límites, nunca como regla que los determine.
  - La etiqueta del formato se muestra en la configuración y en el resumen del torneo; no se añade a la proyección pública.
  - *Alternativa descartada:* formato con efecto real en formaciones y titulares, que sería un cambio estructural del modelo deportivo y se reserva a una spec independiente (Fuera de alcance).

- **RF-044.** CUANDO el usuario edite las reglas de un borrador, EL SISTEMA le preguntará los **límites de plantilla por equipo** —mínimo y máximo de jugadores inscritos— y los guardará en la configuración de la versión como enteros.
  *Criterios de aceptación:*
  - Ambos son **opcionales e independientes del formato**: la ausencia de la clave o el valor **0** significan «sin límite», y no existe valor recomendado ni derivado de la modalidad.
  - Una configuración existente sin las claves se resuelve sin límite y no cambia ningún comportamiento.
  - Una sola regla para el vacío: **en la interfaz**, dejar el campo vacío lo normaliza a 0 —«sin límite»— al salir del campo; **en la API**, se acepta un entero mayor o igual que cero o la ausencia de la clave, y se rechaza una cadena vacía con **422** (error de validación de la petición), sin guardar nada.
  - Se rechaza cualquier valor negativo o decimal en el cliente y en el servidor, con mensaje en el idioma activo y sin perder el resto de la configuración.
  - CUANDO ambos sean mayores que cero, EL SISTEMA exigirá **mínimo ≤ máximo**; si no se cumple, rechazará el guardado con el error de validación que la API ya usa para una configuración de reglas inválida, sin guardar nada.
  - No se fija un techo adicional al máximo: el único límite es el de un entero no negativo y su relación con el mínimo; no se inventa un tope que el dominio no tiene.
  - La ayuda del paso explica que 0 o vacío significan «sin límite», y la revisión muestra el rango declarado junto al formato como contexto, sin sugerir que el formato lo determine.
  - Solo son editables en un borrador; en una versión publicada se muestran en solo lectura y no se reescriben.

- **RF-045.** CUANDO se inscriba un equipo en una fase, EL SISTEMA comprobará que su **plantilla inscrita** —jugadores activos del equipo en el torneo— está dentro de los límites de plantilla efectivos de la versión de la fase y, si no lo está, rechazará la inscripción sin inscribir ningún equipo del lote.
  *Criterios de aceptación:*
  - Los límites efectivos salen de la configuración de la **versión a la que pertenece la fase**, con la misma resolución que la duración y las sustituciones; no se leen del torneo ni de otra versión, no dependen del formato y **no admiten excepciones por fase**: las tres claves son de versión, a diferencia de los minutos, que sí las admiten.
  - Como la inscripción solo se admite en un borrador —una fase de versión publicada responde como hoy—, el bloqueo se evalúa siempre con la configuración del borrador; en una versión publicada no hay inscripción que bloquear.
  - Sin límites configurados (claves ausentes o 0) no se añade ninguna comprobación y la inscripción conserva exactamente el comportamiento actual.
  - SI la plantilla queda por debajo del mínimo o por encima del máximo, ENTONCES la respuesta es **409** con el `code` aditivo **`ROSTER_SIZE_OUT_OF_RANGE`** y un `detail` que nombre el equipo, el mínimo, el máximo y la cantidad actual, presentando como «sin límite» el valor 0 o ausente; no se inscribe ninguno de los equipos del lote.
  - La comprobación cuenta los jugadores **activos** de la plantilla del equipo en el torneo, que es lo que el alta, la importación, el retiro lógico y la reactivación modifican.
  - CUANDO el lote de inscripción tenga varios equipos fuera de rango, el `detail` los nombra con criterio determinista: **todos** si son diez o menos; si son más, **los diez primeros** —ordenados por nombre y, en empate, por identificador— **y el total**. El mensaje es el mismo para cualquier orden de la petición.
  - Un equipo **por encima del máximo** siempre puede corregirse con el retiro lógico, incluso con el bloqueo por jornada activo (RL-1, RF-051). Un equipo **por debajo del mínimo** se corrige añadiendo jugadores; si el bloqueo por jornada está activo, esa vía está cerrada y el mensaje lo explica nombrando la causa, sin prometer una salida que no existe.
  - El rechazo por tamaño se aplica también al **alta individual de equipo con fase destino** (`POST /api/v1/tournaments/{tournament_id}/teams` con `stage_id`) y a la **carga masiva con fase destino** (`POST /api/v1/tournaments/{tournament_id}/teams/bulk` con `stage_id`), porque ambas vías inscriben en la fase: no se crea el equipo ni se inscribe a nadie en el lote (BX-1).
  - La inscripción de un equipo que ya estaba inscrito sigue siendo idempotente y no se bloquea por haber cambiado los límites después.

- **RF-046.** EL SISTEMA **nunca bloqueará la edición de una plantilla por tamaño**: el alta individual, la importación CSV/ZIP, la subida de foto, el consentimiento y cualquier edición de la plantilla solo avisan y permiten guardar, aunque la plantilla esté fuera de los límites, ya esté inscrita o el partido ya exista. El **bloqueo por jornada de referencia sigue vigente** para el alta, la importación **y la reactivación** (mismo 409 actual), y **solo el retiro lógico** queda exento de él (RL-1, RA-1).
  *Criterios de aceptación:*
  - Ninguna operación de edición de plantilla devuelve un rechazo **por tamaño**: se guarda siempre y se muestra un aviso destacado con la cantidad actual y el rango vigente.
  - La administración de plantillas y la composición del asistente de fases muestran, por equipo, el estado **cumple / por debajo del mínimo / por encima del máximo**.
  - Una plantilla **ya inscrita** que después baja del mínimo o sube del máximo solo se avisa: no hay bloqueo retroactivo ni se retira la inscripción.
  - Bajar el máximo por debajo de plantillas ya inscritas tampoco bloquea las inscripciones existentes: se avisa y solo afecta a las inscripciones nuevas y a las aperturas de partido.
  - El botón de inscribir explica qué falta cuando la inscripción está bloqueada y no oculta el motivo; con el equipo dentro del rango se ofrece normalmente.
  - El mensaje del rechazo de inscripción identifica equipo, mínimo, máximo y cantidad actual, en el idioma activo, y no descarta la selección de equipos del asistente.
  - Con el cierre de inscripción activo, el alta individual, la importación y la **reactivación** siguen respondiendo su 409 actual, sin cambios (`test_roster_lock.py` se conserva); **solo el retiro lógico** queda exento y es la vía para reducir una plantilla que ya no admite altas (RL-1, RA-1).
  - El retiro lógico nunca se bloquea por tamaño ni por jornada; la reactivación no se bloquea por tamaño, pero sigue sujeta al bloqueo por jornada y a la unicidad del jugador activo, igual que un alta.

- **RF-047.** EL SISTEMA mantendrá inmutables las versiones publicadas, las inscripciones existentes y las actas cerradas al introducir el formato y los límites de plantilla.
  *Criterios de aceptación:*
  - Una versión publicada no se reescribe: si se publicó sin las claves, se resuelven con sus valores por defecto (11v11, sin límite) y el comportamiento es el actual.
  - Cambiar los límites en un borrador no altera las inscripciones ya realizadas, el calendario ni los resultados registrados.
  - Un partido y su acta conservan la configuración de su versión; las actas cerradas no se revalidan ni se corrigen por los nuevos límites.
  - La planilla y el cierre **no** aplican estos límites: siguen con sus validaciones actuales, incluida la exigencia de al menos un jugador por equipo.
  - El retiro lógico no borra filas ni reescribe histórico: los eventos, las alineaciones y los resultados ya registrados no cambian. Las **respuestas públicas de la API no cambian**, pero la proyección interna `v_public_tournament_players` **deja de listar** al jugador retirado porque filtra por actividad (migración 017); sigue sin exponer documentos ni fechas de nacimiento.

- **RF-048.** EL SISTEMA aplicará el formato y los límites de plantilla dentro del aislamiento por organización, sin exponerlos fuera de la organización ni aceptar valores de otra.
  *Criterios de aceptación:*
  - Viven en la configuración de la versión del torneo de la organización activa; ninguna otra organización puede leerlos ni modificarlos.
  - No se añaden endpoints ni parámetros para el formato ni para los límites: se reutilizan los de configuración de versión, inscripción de equipos en la fase, operación del partido y plantillas. El retiro lógico (RC-1) es el único endpoint nuevo y usa el mismo permiso y el mismo aislamiento que la gestión de plantilla.
  - Un intento sobre un torneo ajeno responde como hoy (no encontrado o prohibido), sin revelar si existe.

- **RF-049.** EL SISTEMA no alterará las reglas deportivas, los permisos existentes ni el contrato cerrado de formaciones al introducir el formato y los límites de plantilla.
  *Criterios de aceptación:*
  - Puntuación, desempates, disciplina, sustituciones, inscripción y resolución conservan sus claves, sus valores y sus validaciones.
  - Ningún rol gana ni pierde permisos; la escritura sigue exigiendo el permiso de gestión de torneos y la operación del partido, el suyo.
  - `docs/contrato-reglas.md` conserva las cuatro formaciones y `engine_version 2026.1`; no hay formaciones por modalidad ni cambios de titulares.
  - Los límites no se aplican a la creación de partidos, al sorteo del calendario, a la planilla ni al cierre: un equipo fuera de rango conserva su calendario y puede operar si el partido ya estaba abierto.
  - Las pruebas existentes de reglas, planilla, cierre, inscripción y sustituciones siguen pasando sin cambios de contrato.

- **RF-050.** CUANDO se abra un partido —al crear su primer segmento en la operación—, EL SISTEMA comprobará que la plantilla inscrita de cada equipo participante está dentro de los límites efectivos de la versión del partido y, si alguno no lo está, rechazará la apertura sin alterar el estado del partido.
  *Criterios de aceptación:*
  - La apertura es la creación del **primer** segmento (`POST /api/v1/matches/{match_id}/segments` con el partido sin segmentos); no se añade ningún endpoint de apertura. Los segmentos posteriores no son apertura y no se bloquean por esta regla.
  - Los límites efectivos salen de la configuración de la **versión del partido** —la publicada, si el partido pertenece a una versión publicada—, sin depender del formato.
  - SI un equipo participante está por debajo del mínimo o por encima del máximo, ENTONCES la respuesta es **409** con el mismo `code` aditivo **`ROSTER_SIZE_OUT_OF_RANGE`** y un `detail` que nombra el equipo, el mínimo, el máximo y la cantidad actual, presentando «sin límite» cuando el valor sea 0 o ausente.
  - La apertura rechazada **no altera el estado del partido**: no se crea el segmento, el partido no queda en juego y no se escribe ninguna otra fila.
  - Sin límites configurados no se añade ninguna comprobación: abrir un partido se comporta como hoy.
  - Corregida la plantilla —por alta, importación, retiro lógico o reactivación—, la apertura se permite sin pasos adicionales ni permisos nuevos.
  - Un partido ya abierto no se revalida ni se detiene por un cambio posterior de los límites; un partido cerrado no se toca.

- **RF-051.** CUANDO el usuario gestione la plantilla de un equipo, EL SISTEMA permitirá **retirar lógicamente** a un jugador inscrito y **reactivarlo**, sin borrar su fila ni romper el histórico.
  *Criterios de aceptación:*
  - La operación es `PATCH /api/v1/tournaments/{tournament_id}/rosters/{roster_id}/status` con el cuerpo `{ "is_active": true | false }`; sus dos respuestas —retirar y reactivar— usan **un único modelo**: la forma de la **lista** de plantilla, con `roster_id`, `player_id`, `team_id`, `first_name`, `last_name`, `dorsal_number`, `age`, `photo_url`, `photo_consent` e `is_active`. Repetir el mismo valor responde **200** sin cambios (idempotente).
  - Exige el **mismo permiso** que el resto de la gestión de plantilla y fija el contexto de aislamiento en la misma transacción; un roster de otro torneo u otra organización responde **404** como hoy, sin revelar si existe.
  - **No escribe auditoría**: el retiro y la reactivación no están entre las acciones auditadas del proyecto y no se añaden a la auditoría organizacional.
  - Retirar deja la fila con actividad falsa: el jugador **deja de contar** como inscrito activo para los límites y no se ofrece para alinear en partidos futuros; la validación existente que rechaza inscripciones inactivas en la planilla sigue igual.
  - **No se borra nada**: los eventos, las alineaciones y los resultados ya registrados no cambian y las respuestas públicas de la API siguen igual; la proyección interna de jugadores por torneo deja de listar al retirado mientras esté inactivo.
  - La reactivación **no se bloquea por tamaño**: si deja la plantilla por encima del máximo, se avisa y los bloqueos de inscripción y apertura actúan como con cualquier plantilla fuera de rango.
  - Reactivar es la vía de reversión **si el jugador no tiene ya otra fila activa en el torneo**; si la tiene, el jugador ya cuenta por esa fila y la operación no es necesaria. Si la reactivación choca con la unicidad del jugador activo del torneo (`uq_active_player_tournament`), se rechaza con **409** y el error de conflicto que la API ya usa para duplicados, sin cambiar ninguna fila. Si choca con el dorsal ya ocupado por otro jugador activo del mismo equipo, se rechaza también con **409** nombrando el dorsal, sin activar la fila.
  - El **retiro** se permite aunque el bloqueo por jornada esté activo (RL-1) y aunque el equipo ya esté inscrito o el partido ya esté abierto. La **reactivación** queda sujeta al bloqueo por jornada con el mismo **409** del alta (RA-1), y ninguna de las dos altera actas cerradas.

## Requisitos no funcionales

- **RNF-001. Las reglas existentes no cambian; se añade una validación configurable y el retiro lógico.** Las reglas existentes no cambian **salvo la excepción explícita RL-1**: el retiro lógico se permite aunque el bloqueo por jornada esté activo, porque reduce la plantilla. El resto de las reglas —incluidas las de inscripción y la reactivación, que se comporta como un alta— sigue igual, y ningún rol gana ni pierde permisos. Lo que se añade es (a) una **validación configurable de tamaño de plantilla** que solo actúa al inscribir, al crear un equipo con fase destino y al abrir el partido (RF-045, RF-050), con defaults que reproducen el comportamiento actual (sin límite), y (b) el **retiro lógico con reactivación** (RF-051) como dependencia imprescindible para poder corregir una plantilla. Ambos son contratos aditivos, declarados en RNF-003 y RNF-009. La alineación de duración (DU-1) conserva el criterio del cierre y el único cambio de visibilidad es el de la sección de configuración (RF-038).
- **RNF-002. Sin migraciones ni cambios de esquema.** No se añaden tablas, columnas, índices, políticas ni permisos de base de datos: el retiro lógico usa la columna de actividad que ya existe en la plantilla. Ni el borrador de los asistentes ni la resolución prevista se persisten: viven en la pestaña (WP-1, RP-1).
- **RNF-003. Contrato que cambia: aditivo y acotado (CT-1, SG-1, P5, FMT-1, MIN-1, RC-1, BX-1 y EV-1).** Los cambios de contrato son aditivos y compatibles:
  - **Respuesta de operación.** `GET /api/v1/matches/{match_id}/operation` añade dentro de `limits` cuatro campos: `max_minute_regular` (entero), `max_minute_extra` (entero o nulo cuando la prórroga no está habilitada en la fase), `extra_time_enabled` (booleano) y `penalties_enabled` (booleano), todos resueltos con la configuración **efectiva de la fase**. `regular_time_minutes`, `extra_time_minutes`, `max_minute` y `added_minute_max` conservan su significado; el cliente deja de usar `max_minute` para validar eventos y segmentos.
  - **Creación de segmento.** `POST /api/v1/matches/{match_id}/segments` admite un campo opcional `resolution_type`. Con el campo, el servidor valida el minuto inicial con el máximo de esa resolución; **sin el campo, aplica el máximo de la fase**, que es el comportamiento actual y el que cubre `backend/tests/test_match_minutes.py`, sin cambios (P1).
  - **Interrupción de segmento.** `POST /api/v1/matches/{match_id}/segments/{segment_id}/interrupt` admite el mismo campo opcional `resolution_type`, con idéntica regla: con el campo valida el minuto final con el máximo de la resolución, sin el campo mantiene el máximo de la fase.
  - **Cierre.** `POST /api/v1/matches/{match_id}/close` ya recibe `resolution_type`; no cambia su petición y conserva sus validaciones, salvo el rechazo unificado del punto siguiente.
  - **Rechazo unificado de resolución no habilitada (P5).** Los tres puntos —crear segmento, interrumpir y cerrar— rechazan una resolución no habilitada por la configuración efectiva de la fase con **un único** resultado: **409**, `detail` común y el campo aditivo `code: RESOLUTION_NOT_ENABLED`. Estar habilitada significa: tiempo reglamentario siempre; prórroga solo con la prórroga habilitada en la fase; penales solo con los penales habilitados; walkover y administrativa, admitidas como hoy —la administrativa conserva además su permiso propio—.
  - **Lo que no cambia.** Los rechazos estructurales o de minuto fuera de rango conservan su **422** y su semántica actuales; no se renombran campos, no se añade ningún endpoint nuevo salvo el de retiro lógico (RC-1), no hay campos obligatorios nuevos y ningún cliente antiguo cambia de resultado.
  - **Compatibilidad.** Un cliente que no envíe `resolution_type` obtiene el comportamiento de hoy, y un cliente que ignore los campos nuevos de `limits` o el campo `code` sigue funcionando.
  - **Configuración de reglas: formato y límites de plantilla (FMT-1, MIN-1).** La configuración de la versión gana tres claves aditivas: `game_format` (texto, uno de `5v5`, `7v7`, `9v9`, `11v11`; por defecto `11v11`), `min_players_per_team` y `max_players_per_team` (enteros ≥ 0; ausencia o `0` significan «sin límite», que es el valor por defecto). El esquema de reglas rechaza propiedades no declaradas, así que el cambio exige actualizar el esquema del servidor, el validador del cliente y la documentación del contrato de reglas; **no exige migración**, porque la configuración es un documento de la versión. Una configuración guardada sin las claves se sigue leyendo y se resuelve con sus valores por defecto, sin reescribirse. `min_players_per_team > max_players_per_team` con ambos mayores que cero es configuración inválida y se rechaza con el error de validación que la API ya usa para ese caso. El formato es declarativo y no altera el contrato cerrado de formaciones. **`engine_version` se mantiene en 2026.1** (EV-1): el contrato cerrado cubre `GF1`/`GF2` y las formaciones y no incluye estas claves, que son configuración aditiva con defaults que reproducen el comportamiento actual. La aclaración de alcance se añade a `docs/contrato-reglas.md` sin cambiar ninguna regla del contrato.
  - **Rechazos por tamaño de plantilla, con el mismo `code`.** Tres superficies responden **409** con `code: ROSTER_SIZE_OUT_OF_RANGE` y un `detail` con equipo, mínimo, máximo y cantidad actual —«sin límite» para 0 o ausente—: (a) `POST /api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams` (inscripción en fase; el lote no inscribe a nadie); (b) `POST /api/v1/tournaments/{tournament_id}/teams` y `POST /api/v1/tournaments/{tournament_id}/teams/bulk` **cuando llevan `stage_id`**, porque inscriben en la fase (BX-1: no se crea el equipo ni se inscribe a nadie); y (c) `POST /api/v1/matches/{match_id}/segments` cuando es el **primer** segmento (apertura: no crea el segmento ni altera el estado del partido). Con varios equipos fuera de rango, el `detail` los nombra con criterio determinista: todos si son diez o menos; si son más, los diez primeros —por nombre y, en empate, por identificador— y el total. Son 409 nuevos y aditivos: los existentes sin `code` siguen igual, ningún cliente que no lea `code` cambia de comportamiento y los 201/200/204 de las operaciones con el equipo dentro de rango o sin límites se conservan.
  - **Retiro lógico de jugador (RC-1): endpoint nuevo.** `PATCH /api/v1/tournaments/{tournament_id}/rosters/{roster_id}/status` con cuerpo `{ "is_active": boolean }` y respuesta, para retirar y para reactivar, con un **único modelo**: la forma de la **lista** de plantilla (`roster_id`, `player_id`, `team_id`, `first_name`, `last_name`, `dorsal_number`, `age`, `photo_url`, `photo_consent`, `is_active`). Exige el mismo permiso que el resto de la gestión de plantilla y fija el contexto de aislamiento en la misma transacción; un roster de otro torneo u otra organización responde **404**. Es idempotente (mismo valor → **200** sin cambios), **no escribe auditoría** —no está entre las acciones auditadas y no se añade— y no borra la fila: solo cambia su actividad. El **retiro** queda exento del bloqueo por jornada (RL-1); la **reactivación** responde el **409** del bloqueo cuando está activo (RA-1) y **409** con el error de conflicto que la API ya usa para duplicados cuando el jugador ya tiene otra fila activa en el torneo (`uq_active_player_tournament`), sin cambiar filas; también **409** nombrando el dorsal cuando este ya está ocupado por otro jugador activo del mismo equipo. No cambia ninguna respuesta pública de la API ni el contrato de jugadores —aunque la proyección interna de jugadores por torneo deja de listar al retirado—, y no hay endpoint de borrado.
- **Documentación.** Se actualizan en el mismo cambio `README.md`, `AGENTS.md` —declarándolo como contrato que cambia— y la descripción de la API en `/docs`.
  - **Verificación.** La prueba de backend es **obligatoria** y cubre: (a) los cuatro campos de `limits`; (b) segmento e interrupción sin el campo → máximo de fase, con la prueba existente intacta; (c) con tiempo reglamentario → límite reglamentario; (d) con prórroga o penales habilitados; (e) valor no habilitado → 409 `RESOLUTION_NOT_ENABLED` en los tres puntos; (f) configuración de reglas sin las tres claves nuevas → formato 11v11 y sin límite de plantilla; (g) inscripción de un equipo dentro del rango → 201/200; (h) por debajo del mínimo o por encima del máximo → 409 `ROSTER_SIZE_OUT_OF_RANGE` en la inscripción; (i) el mismo 409 al abrir el partido con la plantilla fuera de rango, sin crear segmento ni cambiar el estado; (j) el mismo 409 al crear un equipo con `stage_id` —individual y en lote— cuando la fase destino haría incumplir los límites, sin crear el equipo; (k) apertura e inscripción permitidas tras corregir la plantilla con retiro lógico; (l) retiro y reactivación con el bloqueo por jornada activo, idempotencia, 404 entre organizaciones y 409 por dorsal en conflicto; (m) `min > max` con ambos mayores que cero → error de validación de configuración; (n) cadena vacía en la API → 422; (o) versión publicada sin las claves → sin límite. `test_roster_lock.py` se conserva sin cambios.
- **RNF-004. Paridad de idiomas.** Toda clave nueva existe en español y en inglés en el mismo cambio. Ninguna vista muestra el identificador de una clave ni texto fijo en un idioma distinto del activo.
- **RNF-005. Accesibilidad verificable, con vehículo propio.** Los asistentes y la operación se completan con teclado, cada control tiene etiqueta asociada, el cambio de paso mueve el foco al título del paso y se anuncia, y los errores se anuncian al aparecer. La verificación se hace en el **escenario de navegador de operación y cierre**, añadido al arnés de Playwright sin tocar el escenario de reintento ni su veredicto: comprueba el recorrido de los tres asistentes con teclado, el foco al cambiar de paso, los errores anunciados, el paso de reglas (cuatro opciones y 11v11 por defecto), las tres advertencias de formato, la inscripción y la apertura bloqueadas, el retiro lógico y la reactivación. No se declara cumplida por inspección del marcado ni por una prueba unitaria.
- **RNF-006. Sin duplicación de capacidad.** Cada capacidad del alcance tiene una sola pantalla responsable. La revisión puede señalar la pantalla que envía cada escritura y demostrar que no hay una segunda.
- **RNF-007. Sin instrumentación ni atributos de prueba en el producto.** Las comprobaciones se apoyan en el texto visible, los nombres accesibles y el comportamiento; no se añaden atributos, variables globales ni contadores para las pruebas.
- **RNF-008. Continuidad del arnés de extremo a extremo y escenario nuevo.** Las anclas del arnés son las declaradas en `frontend/e2e/labels.ts` —`E2E_LABELS` (incluidos los textos de inicio de sesión, `match.buildReport`, tipo y minuto de evento y vista previa de sustitución) y `REALTIME_STATUS_TEXT` de las tres vistas, con su estado `retrying`— y la prueba unitaria que comprueba que no derivan del catálogo. Ninguna de esas claves ni sus textos cambian; si un cambio de navegación afecta a alguna, el arnés se actualiza en el mismo cambio y sigue en verde, sin añadir tolerancias ni reintentos. Se **añade un escenario propio de operación y cierre** (P6) con el mismo motor y las mismas reglas (`retries: 0`), sin tocar el escenario de reintento, sus localizadores ni su veredicto 0/1/2/3. Su alcance incluye: paso de reglas con las cuatro opciones, 11v11 por defecto y solo lectura en versión publicada; las tres advertencias de formato; la inscripción bloqueada por tamaño; la apertura bloqueada; el retiro lógico con reactivación; y la accesibilidad y el foco de los asistentes (RF-012, RNF-005). La verificación se ejecuta con `pnpm run typecheck:e2e` y `pnpm run e2e:test` sobre la pila sembrada.
- **RNF-009. Trazabilidad documental.** Se documentan en el mismo cambio: la navegación nueva —secciones y direcciones—, el catálogo de posiciones, el comportamiento del borrador de los asistentes, la resolución prevista, la regla de duración, el rechazo unificado de resolución no habilitada, el formato de juego declarativo y los dos límites de plantilla con sus tres superficies de bloqueo —inscripción, alta con fase destino y apertura del partido—, sus avisos, la corrección mediante **retiro lógico y reactivación** y la **excepción del bloqueo por jornada** (RL-1), y los cambios aditivos de contrato —respuesta de operación, peticiones de segmento e interrupción, los 409 nuevos, las tres claves de configuración de reglas y el endpoint de retiro lógico— (`README.md`, `AGENTS.md` y `/docs`), con las claves y sus defaults documentados en los tres. La documentación no se limita a describir: cumple la §4 de la constitución —actualizar lo que cambie el comportamiento observable— sin contradecirla. `docs/contrato-reglas.md` **aclara su alcance y no cambia ninguna regla**: el catálogo de formaciones y `engine_version 2026.1` se conservan y las tres claves quedan declaradas como configuración aditiva fuera del contrato cerrado (EV-1).
- **RNF-010. Coste acotado.** No se añaden dependencias nuevas, ni trabajos de integración continua, ni motores de navegador: el escenario de operación y cierre corre dentro del job `e2e` existente y del presupuesto declarado (job de 25 minutos, vista de 4). Las demás comprobaciones nuevas corren dentro de la suite existente.
- **RNF-011. Borradores efímeros y sin datos personales.** El borrador de un asistente y la resolución prevista se limitan al almacenamiento de sesión de la pestaña: no se escriben en el servidor, no se comparten entre pestañas ni dispositivos, no sobreviven al cierre y no contienen datos personales —reglas, fases y equipos no los tienen—. El borrador local del partido es una pieza distinta y preexistente: guarda los eventos y los datos del formulario de cierre por usuario, organización y partido, y no contiene nombre, documento ni fecha de nacimiento. **No guarda la resolución prevista**, que vive solo en la sesión de la pestaña (P3) y deja de persistirse en el borrador local; un borrador antiguo que la contenga se limpia al restaurar, sin perder eventos ni marcador. La administración de plantillas no conserva archivos ni datos entre visitas.

## Datos personales y privacidad

- **Datos involucrados:** en la administración de plantillas, nombre y apellidos del jugador, **documento de identidad y fecha de nacimiento** —datos personales, protegidos—, edad derivada, dorsal, foto y consentimiento de imagen. Estos mismos campos personales se envían en el **alta individual** de un jugador y viajan también dentro del archivo de la importación CSV/TXT; ambos caminos existen hoy y esta spec los deja en la misma pantalla. En los asistentes de reglas, fases y equipos no hay datos personales: solo configuración, nombres de equipo y códigos.
- **Quién los ve:** solo los miembros de la organización con permiso para gestionar el torneo o consultarlo. Las pantallas nuevas no amplían quién puede verlos y no los exponen a otras organizaciones.
- **Qué no se expone:** la pantalla de plantillas no muestra documento ni fecha de nacimiento, igual que hoy; tampoco la operación del partido ni ninguna respuesta pública. La foto se muestra solo con consentimiento.
- **Qué no se persiste en el cliente:** el contenido de un archivo de plantilla ni los valores del alta individual —que incluyen documento y fecha de nacimiento— se conservan en la dirección, en el almacenamiento de sesión ni en almacenamiento persistente. La administración de plantillas no es un asistente y no guarda borrador: al salir, los valores y el archivo se descartan.
- **Qué se conserva y dónde:** el borrador de los asistentes de reglas, fases y equipos y la **resolución prevista** —sin datos personales— se guardan **solo** en el almacenamiento de sesión de la pestaña y se descartan al cerrarla. El **borrador local del partido**, preexistente y con su comportamiento actual, guarda en el almacenamiento local del navegador los eventos y los datos del formulario de cierre —marcador, penales, ganador y motivo—, por usuario, organización y partido: no incluye nombre, documento, fecha de nacimiento ni foto, **no guarda la resolución prevista** —deja de persistirla; un borrador antiguo que la contenga se limpia al restaurar—, y ya tiene su acción explícita de descarte. Son dos almacenes distintos y no se mezclan (P3).
- **Retirar el alta de jugadores de la operación:** los mismos datos dejan de circular por una segunda pantalla y pasan a circular solo por la administración de plantillas, con las mismas validaciones y el mismo cifrado en servidor. No se añade exposición; el cambio reduce la superficie.
- **Retiro lógico:** no cambia qué datos personales existen ni quién los ve. La fila del jugador se conserva con su documento cifrado y su fecha cifrada; solo cambia su actividad. El retiro no borra nada y no añade ningún dato nuevo.
- **Aislamiento:** todas las comprobaciones se ejecutan sobre la organización de desarrollo; ninguna pantalla nueva consulta datos de otra organización.

## Casos límite

1. **Cambio de versión con el asistente abierto:** si la versión seleccionada deja de ser el borrador o cambia, el asistente no guarda sobre la versión equivocada: avisa, pide confirmación para descartar el borrador y ofrece recargar los valores de la versión vigente.
2. **Cambio de fase o de equipo con el asistente abierto:** la selección se conserva mientras el asistente viva; si la fase deja de existir, se avisa y no se envía nada.
3. **Dos errores en el mismo paso:** se muestran los dos, cada uno junto a su campo, y no se envía nada.
4. **Error solo detectable en el servidor:** el asistente lo muestra al confirmar, conserva todo y no cambia de paso.
5. **Confirmar sin visitar un paso obligatorio:** el índice lo marca como incompleto y el sistema lleva a él antes de enviar.
6. **Paso opcional sin configurar:** se marca como omitido, se guarda sin él y no impide confirmar.
7. **Ninguna vía de alta elegida en equipos:** es un paso alternativo sin resolver; confirmar está deshabilitado y se explica.
8. **Las dos vías de alta con datos:** solo se envía la elegida; cambiar de vía no borra lo escrito en la otra.
9. **Fallo a mitad de inscripción tras crear la fase:** la fase queda creada y visible sin los equipos que no se inscribieron, el asistente lo dice, la selección se conserva y el reintento se hace sobre esa misma fase sin crear otra.
10. **Fallo en todas las inscripciones:** fase creada sin equipos, aviso claro y reintento disponible; no se presenta como error total ni como éxito.
11. **Reintento tras fallo parcial y equipo ya inscrito:** se informa sin duplicar filas y sin error genérico.
12. **Alta de equipo sin fase:** es el comportamiento normal; el equipo queda registrado y sin inscripción hasta que se use el asistente de fases.
13. **Idioma cambiado a mitad del asistente:** los valores se conservan, las etiquetas y los mensajes se traducen, y el paso actual no cambia.
14. **Recarga de la página con cambios sin guardar:** se conservan el paso y los datos de esa pestaña; el aviso de cambios sin guardar sigue visible.
15. **Enlace compartido a un paso intermedio sin datos:** en reglas se muestran los valores del servidor de la versión; en fases, la composición sin fase se muestra bloqueada con enlace al paso de identificación; en equipos, los pasos se muestran vacíos. No se redirige en silencio.
16. **Misma dirección en otra pestaña o en otro dispositivo:** empieza desde los valores del servidor y no ve el borrador de la primera pestaña.
17. **Cierre de la pestaña con cambios sin guardar:** el borrador del asistente se descarta; al volver, arranca desde el servidor.
18. **Cambio de sección con cambios sin guardar:** no pide confirmación y el borrador se conserva; al volver, el asistente está en el mismo paso.
19. **Atrás del navegador desde un paso intermedio:** devuelve al paso anterior con sus valores, sin enviar nada y sin duplicar entradas de historial.
20. **Atrás del navegador hacia una sección cuyo recurso ya no existe:** se muestra el error de la sección, no una pantalla en blanco.
21. **Dirección antigua con fragmento de calendario o plantillas:** redirige a la dirección nueva; el botón atrás no vuelve a rebotar.
22. **Dirección antigua con fragmento `#equipos`:** no redirige y sigue llevando al bloque de equipos dentro de la configuración.
23. **Dirección antigua con fragmento desconocido:** la pantalla sigue usable y no muestra un error de navegación.
24. **Dirección de otra organización:** responde como hoy y no revela si el recurso existe.
25. **Sesión expirada a mitad del asistente:** el sistema redirige al inicio de sesión, no guarda nada a medias y no reaplica el borrador a otra organización.
26. **Permiso retirado a mitad del asistente:** la siguiente escritura se rechaza, el sistema lo explica y no deja el formulario en un estado que parezca guardado.
27. **Observador sin permiso de gestión:** ve configuración, calendario y plantillas en solo lectura y ninguna acción de escritura.
28. **Versión publicada o archivada:** los asistentes y las pantallas se muestran en solo lectura; no hay acción de guardado ni de sorteo sobre estructura publicada.
29. **Fase sin equipos suficientes para sortear:** el asistente y el calendario explican qué falta y no ofrecen sortear; no se ejecuta ninguna generación parcial.
30. **Calendario existente al regenerar:** se pide confirmación explícita; cancelar no altera nada.
31. **Retirar un equipo que ya no está:** la operación es idempotente y se informa sin fallar.
32. **Carga masiva con una fila inválida:** se informa la fila y el motivo, y ninguna fila válida se pierde del formulario.
33. **Límite de filas de la carga masiva:** se rechaza el conjunto con su mensaje actual, sin truncar en silencio.
34. **Cierre de inscripción activo:** el aviso aparece antes de enviar —calculado con los partidos leídos (CI-1)—; el alta y la importación se rechazan con su mensaje actual y no se sube ninguna foto.
35. **Posición fuera del catálogo, clave de posición ausente o rol desconocido:** se muestra el código recibido tal cual.
36. **Evento por encima del minuto reglamentario con la prórroga desactivada:** se rechaza al registrarlo, con el máximo reglamentario como límite.
37. **Segmento que empieza por encima del máximo de la resolución prevista:** la pantalla no lo ofrece y, si la petición llega igualmente, el servidor la rechaza con el **422** de minuto fuera de rango que ya devuelve hoy, nombrando el máximo aplicable; no se crea el segmento.
38. **Resolución no habilitada por la fase:** crear segmento, interrumpir o cerrar con una resolución no habilitada devuelve **409** con `code: RESOLUTION_NOT_ENABLED` y el mismo mensaje en los tres puntos; no se crea el segmento, no se registra la interrupción y no se cierra el acta.
39. **Cliente antiguo que crea o interrumpe un segmento sin indicar resolución:** el servidor aplica el **máximo de la fase**, que es el comportamiento actual; la prueba de minutos existente se conserva sin cambios y ningún cliente cambia de resultado.
40. **Prórroga configurada pero no jugada:** si la resolución prevista es tiempo reglamentario, el máximo es el reglamentario y la operación avisa antes de registrar o iniciar segmentos por encima; si es prórroga o penales, el máximo es el de prórroga y el cierre lo acepta.
41. **Cambio de la resolución prevista con segmentos ya persistidos por encima del nuevo máximo:** el cambio **no se permite**; se explica que hay segmentos guardados fuera del nuevo límite y se pide resolver primero. No hay corrección de segmentos ni se promete.
42. **Cambio de la resolución prevista con solo eventos del borrador por encima del nuevo máximo:** el cambio se permite, se avisa de los eventos afectados y ninguno se envía ni se borra; el operador los corrige o cierra.
43. **Cierre con una resolución distinta y compatible con lo persistido:** se avisa de los eventos del borrador que pueden salir del límite y se pide confirmación; sin confirmación no se cierra.
44. **Recarga del partido:** se restauran por separado el borrador local —eventos y datos del formulario de cierre— y la resolución prevista de la sesión de esa pestaña.
45. **Evento en el minuto del máximo con minuto añadido:** se acepta dentro del tope estructural, igual al operar y al cerrar.
46. **Partido ya cerrado:** la operación es de solo lectura para eventos y resultado; no se revalida ni se recalcula al cambiar la regla.
47. **Partido de una versión publicada:** aplica la configuración de esa versión, que no se reescribe; si la versión tiene excepción por fase, se aplica esa excepción.
48. **Configuración antigua sin los valores de minutos:** se resuelve con los valores por defecto vigentes y no se reescribe hasta que el usuario guarde.
49. **Mínimo mayor que el máximo:** con ambos mayores que cero, al guardar las reglas se rechaza con el error de validación de configuración que la API ya usa, sin guardar nada; el cliente muestra el mismo rechazo junto al campo de máximo.
50. **Mínimo o máximo negativo o decimal:** se rechaza en el cliente y en el servidor; el campo queda editable y el resto de los pasos se conserva. **Campo vacío:** en la interfaz se normaliza a 0 —«sin límite»— al salir del campo, y una cadena vacía enviada a la API se rechaza con **422** sin guardar nada.
51. **Máximo menor que plantillas ya inscritas:** el cambio se guarda con aviso destacado; no bloquea ni retira las inscripciones existentes y solo afecta a las inscripciones nuevas y a las aperturas de partido.
52. **Mínimo mayor que la plantilla del equipo al inscribir:** la inscripción responde 409 `ROSTER_SIZE_OUT_OF_RANGE` con equipo, mínimo, máximo y cantidad actual; el lote no inscribe ningún equipo y la selección se conserva para reintentar tras completar la plantilla.
53. **Plantilla ya inscrita que después baja del mínimo o sube del máximo:** solo se avisa; no hay bloqueo retroactivo ni se retira la inscripción, y la apertura del partido sí queda bloqueada hasta corregirla.
54. **Cambio de formato con equipos ya inscritos:** se permite en el borrador, no altera inscripciones, fases, calendario, límites ni partidos, y no toca la planilla; si el formato no es 11v11 aparece la advertencia visible en reglas, resumen y operación.
55. **Límites independientes del formato:** el mismo mínimo y el mismo máximo se aceptan, se guardan y se aplican igual con 5v5 que con 11v11; el formato no acota ni sugiere un valor.
56. **Formato distinto de 11v11:** la advertencia de que la planilla soportada es de once se ve en el paso de reglas, en el resumen de configuración y en la operación/planilla; no bloquea inscribir, abrir ni guardar.
57. **Apertura bloqueada por debajo del mínimo:** crear el primer segmento responde 409 `ROSTER_SIZE_OUT_OF_RANGE`, no se crea el segmento y el partido no queda en juego.
58. **Apertura bloqueada por encima del máximo:** mismo 409 y mismo detalle con máximo y cantidad actual; el partido no cambia de estado.
59. **Apertura permitida tras corregir la plantilla:** una vez dentro del rango, el primer segmento se crea con el comportamiento actual y sin pasos ni permisos nuevos.
60. **Edición de plantilla con el equipo ya inscrito o el partido abierto:** el alta, la importación, la foto y el consentimiento guardan siempre y solo avisan **por tamaño**; el bloqueo por jornada sigue vigente para el alta, la importación **y la reactivación** (409 actual) y **solo el retiro lógico** queda exento (RL-1, RA-1).
61. **Versión publicada con las claves:** el formato y los límites se ven en solo lectura y no se reescriben; la inscripción sobre una fase publicada responde como hoy (versión inmutable) y la apertura de un partido de esa versión aplica sus límites.
62. **Versión publicada sin las claves:** se resuelve con los valores por defecto (11v11 y sin límite) y el comportamiento es el actual; no se reescribe la configuración.
63. **Importación CSV por debajo del mínimo o por encima del máximo:** la importación se completa y deja un aviso destacado; no bloquea, y la inscripción y la apertura posteriores sí se bloquean si la plantilla sigue fuera de rango.
64. **Acta ya cerrada:** no se revalida ni se modifica; los límites de plantilla no alcanzan a la planilla ni al cierre, y un partido cerrado no se abre de nuevo.
65. **Formato o límites de otra organización:** la operación responde como hoy y no revela ni aplica valores ajenos.
66. **Sin claves en un borrador (configuración antigua):** sin límite de plantilla y formato 11v11; inscribir y abrir no cambian de comportamiento.
67. **Solo mínimo declarado (máximo 0 o ausente):** se aplica el suelo y no hay techo; el aviso por encima del máximo no existe y el detalle del 409 presenta «sin límite» en el máximo.
68. **Solo máximo declarado (mínimo 0 o ausente):** se aplica el techo y no hay suelo; no se avisa por debajo y el detalle presenta «sin límite» en el mínimo.
69. **Máximo declarado menor que el mínimo, pero uno de los dos es 0:** es válido y significa un único límite; no se aplica la relación mínimo ≤ máximo.
70. **Borrador local antiguo con la resolución prevista:** al restaurar se ignora y se limpia ese campo; los eventos y el marcador se restauran con normalidad y la resolución vigente es la de la sesión de la pestaña.
71. **Alta individual con fase destino fuera de rango:** `POST /teams` con `stage_id` responde 409 `ROSTER_SIZE_OUT_OF_RANGE` y **no crea el equipo** ni lo inscribe.
72. **Carga masiva con fase destino fuera de rango:** el lote responde 409 y no crea ninguno de los equipos, aunque algunos estuvieran dentro del rango; es todo o nada.
73. **409 con varios equipos fuera de rango:** el `detail` los nombra a todos si son diez o menos; si son más, los diez primeros —por nombre y, en empate, por identificador— y el total, con el mismo texto para cualquier orden de la petición.
74. **Retiro y reactivación con el bloqueo por jornada activo:** el **retiro** se permite y reduce la plantilla; la **reactivación** responde el mismo 409 del alta, igual que el alta y la importación (RL-1, RA-1).
75. **Equipo por encima del máximo:** se corrige retirando lógicamente a los jugadores sobrantes; vuelve al rango, se puede inscribir si no lo estaba y abrir el partido.
76. **Jugador retirado:** deja de contar como inscrito activo y la planilla lo rechaza como inscripción inactiva; sus eventos, alineaciones y resultados anteriores no cambian; las respuestas públicas de la API siguen igual y la proyección interna de jugadores por torneo deja de listarlo mientras esté retirado.
77. **Reactivación con el dorsal ocupado:** responde 409 nombrando el dorsal en conflicto y la fila sigue inactiva; con el dorsal libre, la reactivación devuelve el jugador a la plantilla activa.
78. **Equipo por debajo del mínimo con el cierre de inscripción activo:** no puede inscribirse ni abrirse; el rechazo por tamaño explica que faltan jugadores y que el cierre de inscripción impide añadirlos, y no sugiere una vía bloqueada.
79. **Reactivación con el jugador ya activo por otra fila:** si el jugador tiene otra inscripción activa en el torneo, la reactivación de la fila antigua responde 409 con el error de conflicto de duplicados y no cambia ninguna fila; el jugador ya cuenta por la fila activa.

## Fuera de alcance

- **Google OAuth** y cualquier cambio en el inicio de sesión, la sesión o la identidad.
- **Nuevas reglas de eventos** del acta: no se añaden tipos de evento, ni reglas de sustitución, disciplina o resolución, ni se cambia su validación.
- **Un máximo único por fase** (opción B de DU-1) o cualquier cambio de la regla deportiva de duración: se conserva el criterio que ya aplica el cierre.
- **Estadísticas públicas** o cualquier contenido nuevo en las rutas públicas.
- **Cambios estructurales del modelo deportivo:** fases, versiones, partidos, segmentos, plantillas y alineaciones mantienen su forma. No se añaden tablas, columnas ni migraciones.
- **Persistencia en servidor, en almacenamiento persistente o entre pestañas** del borrador de los asistentes y de la resolución prevista (descartado en WP-1 y RP-1).
- **Persistir la resolución prevista en el partido** (opción C de SG-1): la resolución viaja en la petición de segmento y en la del cierre, no se guarda como columna.
- **Atomicidad entre crear la fase e inscribir:** son dos operaciones del contrato; la spec exige recuperación explícita, no una transacción conjunta (AT-1).
- **Corregir segmentos ya persistidos** para que quepan en una resolución nueva: no se añade contrato de corrección; el cambio de resolución incompatible se bloquea (P2).
- **Formaciones, titulares, suplentes y publicación pública adaptados a cada modalidad:** se reservan a una **spec independiente**. Aquí el formato es declarativo (FMT-1): no cambia el catálogo cerrado de formaciones, el número de titulares, la banca ni la publicación pública, y `docs/contrato-reglas.md` con `engine_version 2026.1` no se toca.
- **Bloquear el alta individual, la importación o la subida de foto por quedar fuera de los límites de plantilla:** esas pantallas avisan de forma destacada y permiten guardar (MIN-2).
- **Bloqueo retroactivo de plantillas ya inscritas o de inscripciones existentes al cambiar el mínimo o el máximo:** solo se avisa; los límites alcanzan a las inscripciones nuevas.
- **Aplicar los límites de plantilla a la creación de partidos, al sorteo del calendario, a la planilla o al cierre.**
- **Retirar el parámetro de fase del alta de equipo:** el contrato lo mantiene aunque la interfaz deje de usarlo (IN-1).
- **Plantillas reutilizables de formularios de operación** como funcionalidad nueva: no existen hoy y no se crean; «plantillas de formularios de operación» se interpreta como la planilla del partido (PLT-1).
- **Una dirección propia por cada sección** (opción B de NAV-1): reglas, fases y equipos siguen dentro de la configuración.
- **Convertir la administración de plantillas en un asistente** (opción C de WIZ-1).
- **Rediseño visual completo** del Workspace, cambio de identidad gráfica o sustitución del sistema de estilos.
- **Editor de reglas por fases independientes** o cambio del esquema de configuración de reglas.
- **Reordenación de la operación del partido** más allá de retirar el alta de jugadores, añadir el enlace a plantillas y mostrar el máximo de la resolución prevista.
- **Borrado físico de un jugador o de su inscripción:** el retiro es **lógico** y la reactivación es la reversión cuando el jugador no tiene ya otra fila activa en el torneo; la fila y su histórico se conservan (RC-1).
- **Edición de los datos del jugador** (nombre, documento, fecha, dorsal) más allá del alta: fuera de alcance.
- **Auditoría del retiro lógico:** no se añade a `administrative_audit_logs` porque no está entre las acciones auditadas del proyecto (RC-1); si el producto quiere auditarlo, se decide en otra spec.
- **Nuevas capacidades de plantillas** —edición, baja o traslado de jugadores— que hoy no existen como contrato.
- **Administración de plataforma** (`/admin`), invitaciones, miembros y facturación.

## Criterios de finalización

1. Existen tres asistentes —reglas, fases y equipos— con índice de pasos, estado por paso y guardado al final; se recorren de ida y vuelta conservando todos los valores, incluidos los inválidos; en 1280×800 el índice y el paso actual se ven sin desplazar la página (RF-001 a RF-004).
2. Todo error de validación conocido se muestra junto a su campo, en el idioma activo, sin descartar datos; confirmar con errores no envía nada y lleva al primer paso afectado; el mensaje se anuncia y se alcanza con el teclado (RF-005, RF-006).
3. El guardado exitoso muestra los valores devueltos por el servidor y deja el formulario sin cambios pendientes; un rechazo conserva todos los valores y muestra el motivo sin cerrar el asistente (RF-007).
4. Cada asistente declara qué pasos son obligatorios, opcionales o alternativos; el índice distingue completo, incompleto, con error, omitido y alternativo; confirmar exige los obligatorios y exactamente una alternativa; la carga masiva de equipos conserva sus validaciones y su fase ya no se pide en el alta (RF-006, RF-011).
5. Crear una fase y luego inscribir se presenta como dos resultados: si la inscripción falla, la fase queda visible sin equipos, el asistente lo dice, la selección se conserva y el reintento no duplica la fase (RF-002, RF-010).
6. Cada capacidad tiene una sola pantalla responsable: alta de equipo sin fase, inscripción y retirada solo en el asistente de fases, alta individual de jugador solo en plantillas y creación o sorteo de partidos solo en el calendario (RF-003, RF-021).
7. El asistente de reglas no pierde ninguna capacidad del editor actual, conserva el modo avanzado, envía la configuración completa —incluidas las claves que el esquema exige, aunque un paso opcional quede omitido— y no inventa valores (RF-009).
8. Los asistentes se completan con teclado, anuncian el cambio de paso y asocian cada error a su campo, verificado en el escenario de navegador de operación y cierre (RF-012, RNF-005).
9. El paso actual vive en la dirección y recargar o cambiar de sección conserva paso y datos; otra pestaña u otro dispositivo no comparte el borrador; cerrar la pestaña lo descarta; nada se escribe en servidor ni en almacenamiento persistente (RF-013, RF-014, RNF-011).
10. Ninguna navegación que conserva el borrador pide confirmación, y solo la acción explícita de descartar o el cambio de versión o torneo la piden (RF-008, RF-019).
11. Un enlace a un paso sin borrador previo se comporta según el tipo de asistente: valores del servidor en reglas, composición bloqueada con enlace en fases y pasos vacíos en equipos, sin redirigir en silencio (RF-015).
12. El calendario y las plantillas tienen dirección propia, se abren y recargan directamente y conservan su selección; plantillas es un formulario único de una pantalla que avisa del cierre de inscripción y enlaza al asistente de fases (RF-016, RF-017, RF-024).
13. El aviso de cierre de inscripción es equivalente a la respuesta real: cuando aparece, la escritura responde 409 con el mensaje de cierre; cuando no aparece, no hay 409 por ese motivo (RF-017, RF-039, P4).
14. El índice del torneo marca la sección abierta, incluye resumen, configuración, calendario, plantillas y operación cuando hay partido; «Equipos» ya no es una entrada y `#equipos` sigue resolviendo a configuración; el botón atrás funciona y las direcciones antiguas redirigen sin romper marcadores (RF-018, RF-019, RF-020).
15. La operación conserva segmentos, planilla, oficiales, eventos y cierre, mantiene la planilla independiente de la plantilla, enlaza a la plantilla del equipo y al volver conserva el partido, el segmento y el borrador local (RF-022).
16. El calendario reutiliza el contrato de sorteo existente y cada sección pide solo lo que muestra, con la única lectura adicional justificada por el aviso de cierre —versión publicada más reciente, sus fases y los partidos— (RF-023, RF-024).
17. Roles y posiciones se muestran traducidos en todas las vistas del alcance desde una única fuente; los 23 códigos están cubiertos en los dos idiomas con la regla de lado, y los roles conocidos, las posiciones desconocidas y las claves ausentes se muestran tal cual corresponde (RF-025, RF-026, RF-027, RF-028, apéndice C).
18. La comprobación de claves usadas contra el catálogo termina sin ausencias y hay paridad español/inglés (RF-029, RF-030).
19. La duración se nombra como el minuto en que termina el encuentro; con la prórroga desactivada el campo está deshabilitado y conserva su valor; el par de minutos se valida como hoy (RF-031).
20. La operación muestra la resolución prevista, el máximo efectivo y el tope de minuto añadido, y valida eventos, segmentos e interrupciones con el mismo criterio que el cierre; sin `resolution_type` el servidor aplica el máximo de la fase —prueba de minutos existente intacta— y con el campo aplica el máximo de esa resolución (RF-032).
21. Un cambio a una resolución cuya compatibilidad está comprometida por segmentos ya persistidos se bloquea con un mensaje claro y sin corrección de segmentos; si solo afecta a eventos del borrador, se avisa sin borrar ni enviar (RF-033, P2).
22. La resolución prevista vive solo en la sesión de la pestaña, se restaura al recargar, es la que se envía al crear o interrumpir un segmento y al cerrar y, si se cambia al cerrar de forma compatible, hay aviso con los eventos afectados y confirmación explícita: sin confirmación no se cierra (RF-034).
23. Las actas cerradas y las versiones publicadas no se revalidan ni se reescriben; un cambio de minutos en un borrador avisa antes de guardar; los límites deportivos y los topes estructurales se conservan (RF-035, RF-036).
24. La regla de duración queda documentada una sola vez, sin contradecir la constitución, y la documentación afectada se actualiza en el mismo cambio (RF-037, RNF-009).
25. El observador ve configuración, calendario y plantillas en solo lectura y ninguna acción de escritura; un miembro con permiso conserva exactamente las suyas; el cambio es de visibilidad, no de permisos (RF-038).
26. El servidor sigue siendo la autoridad: la única regla replicada es el aviso de cierre de inscripción, declarada y verificada por equivalencia; los rechazos se muestran sin perder datos y los códigos existentes no cambian salvo el 409 unificado (RF-039).
27. El aislamiento por organización y los flujos actuales se conservan, con sus códigos de respuesta (RF-040, RF-041).
28. **Verificación de backend obligatoria:** `cd backend && pytest -q` y `python -m compileall -q app` pasan en verde con pruebas que cubran: (a) los cuatro campos nuevos de `limits` con su resolución efectiva por fase; (b) creación de segmento e interrupción **sin** `resolution_type` → máximo de fase, con `test_match_minutes.py` sin cambios; (c) con tiempo reglamentario → límite reglamentario; (d) con prórroga o penales habilitados → máximo con prórroga; y (e) valor no habilitado → **409** `RESOLUTION_NOT_ENABLED` con el mismo mensaje al crear segmento, al interrumpir y al cerrar, sin escribir nada (RNF-003, RF-032).
29. Pasan las verificaciones de frontend: `cd frontend && pnpm test`, `pnpm run typecheck`, `pnpm run build`, `pnpm run typecheck:e2e` y, sobre la pila sembrada, `pnpm run e2e:test` con el escenario de operación y cierre en verde y el escenario de reintento sin cambios. Lo que no se pueda ejecutar se declara **no ejecutado** (RNF-005, RNF-008, RNF-010).
30. No hay migraciones, no cambia el esquema, los únicos cambios de contrato son los declarados en RNF-003 y la documentación afectada —incluido el contrato que cambia— queda actualizada (RNF-001 a RNF-003, RNF-009).
31. El asistente de reglas pregunta el formato con exactamente 5v5, 7v7, 9v9 y 11v11, en los dos idiomas, con 11v11 por defecto, y lo muestra en solo lectura en versiones no editables (RF-042).
32. El formato es puramente declarativo: no deriva, acota ni condiciona los límites, no cambia formaciones ni titulares, y el mismo mínimo y máximo funcionan igual con 5v5 que con 11v11 (RF-043).
33. Con formato distinto de 11v11 la advertencia visible aparece en el paso de reglas, en el resumen de configuración y en la operación/planilla, explica que la modalidad real llegará con la spec de formaciones y no bloquea nada; el escenario E2E la comprueba en los tres lugares (RF-043).
34. El mínimo y el máximo son opcionales e independientes del formato, con 0 o ausencia = «sin límite»; se validan como enteros ≥ 0, se exige mínimo ≤ máximo cuando ambos son mayores que cero, una configuración existente sin las claves se resuelve sin límite, la interfaz normaliza el campo vacío a 0 y la API rechaza una cadena vacía con 422 (RF-044).
35. La inscripción de un equipo en una fase se bloquea con **409** `ROSTER_SIZE_OUT_OF_RANGE` —equipo, mínimo, máximo y cantidad actual, con «sin límite» para 0 o ausente— cuando la plantilla queda fuera de rango; el lote no inscribe ninguno y sin límites no se añade comprobación (RF-045).
36. La apertura del partido —primer segmento— se bloquea con el **mismo** 409 y el mismo detalle si algún equipo participante está fuera de rango; la apertura rechazada no crea el segmento ni cambia el estado del partido; corregida la plantilla, la apertura se permite (RF-050).
37. Editar la plantilla —alta individual, importación, foto y consentimiento— **nunca se bloquea por tamaño**: solo avisa; el bloqueo por jornada sigue vigente para el alta y la importación (409 actual, sin cambios) y **solo el retiro lógico** está exento (la reactivación se comporta como un alta); no hay bloqueo retroactivo de plantillas inscritas y bajar el máximo no bloquea inscripciones existentes, solo las nuevas y las aperturas (RF-046, RL-1).
38. Versiones publicadas, actas cerradas y partidos ya abiertos se comportan como fijan RF-047 y RF-050: la planilla y el cierre no aplican estos límites y conservan sus validaciones actuales (RF-047, RF-049).
39. **Verificación obligatoria del cambio:** `cd backend && pytest -q` cubre las tres claves (sin claves → 11v11 y sin límite; dentro de rango → 201/200; por debajo del mínimo y por encima del máximo en la inscripción → 409 `ROSTER_SIZE_OUT_OF_RANGE`; el mismo 409 al abrir el partido; el mismo 409 al crear equipo con `stage_id`, individual y en lote, sin crear el equipo; detalle determinista con varios equipos; apertura e inscripción tras corregir con retiro lógico; retiro y reactivación con bloqueo por jornada activo, idempotencia, 404 entre organizaciones y 409 por dorsal; `min > max` → error de configuración; cadena vacía → 422; versión publicada sin claves → sin límite; edición de plantilla nunca rechazada **por tamaño**; `test_roster_lock.py` sin cambios).
40. `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run build` pasan, con pruebas de la validación de los límites y de las claves de los avisos en los dos idiomas.
41. El escenario E2E de operación y cierre comprueba el paso de reglas (cuatro opciones, 11v11 por defecto y solo lectura en versión publicada), las tres advertencias de formato, la inscripción bloqueada, la apertura bloqueada, el retiro lógico con reactivación y la accesibilidad y el foco de los asistentes; se ejecuta con `pnpm run typecheck:e2e` y `pnpm run e2e:test`, y lo que no se pueda ejecutar se declara **no ejecutado**.
42. Aislamiento por organización, permisos y contrato cerrado de formaciones se conservan (RF-048, RF-049).
43. El retiro lógico y la reactivación funcionan con el mismo permiso que la gestión de plantilla, con aislamiento, sin auditoría y con idempotencia; ambas respuestas usan el modelo de la lista de plantilla —con `player_id` y `age`—; la fila no se borra, el jugador retirado deja de contar, de poder alinearse y de aparecer en la proyección interna, los eventos y alineaciones anteriores no cambian y las respuestas públicas de la API siguen igual (RF-051, RF-047).
44. El borrador local del partido deja de guardar la resolución prevista y un borrador antiguo que la contenga se limpia al restaurar sin perder eventos ni marcador (RF-022, RF-034, RNF-011).
45. `engine_version` sigue en 2026.1, `docs/contrato-reglas.md` aclara que el contrato cerrado no incluye las tres claves y las claves y sus defaults quedan documentados en `README.md`, `AGENTS.md` y `/docs` (RF-043, RNF-003, RNF-009).
46. La reactivación queda sujeta al bloqueo por jornada con el mismo 409 del alta y responde 409 —error de conflicto de duplicados— si el jugador ya tiene otra fila activa en el torneo, sin cambiar ninguna fila; el 409 por dorsal ocupado se conserva (RF-051, RA-1).

## Dudas abiertas

Las veintisiete decisiones de las cuatro rondas de clarificación —DU-1, WP-1, NAV-1, WIZ-1, PLT-1, POS-1, CT-1, AT-1, IN-1, CI-1, RP-1, SG-1, P1, P2, P3, P4, P5, P6, FMT-1, MIN-1, MIN-2, AP-1, RC-1, RL-1, RA-1, BX-1 y EV-1— están registradas en «Decisiones de clarificación». **Ninguna queda abierta**: la petición de formato y límites de plantilla se cerró con formato declarativo, dos claves de configuración y bloqueo por tamaño en tres superficies —inscripción en fase, alta con fase destino y apertura del partido—, con el retiro lógico exento del bloqueo por jornada y la reactivación sujeta a él.

## Apéndice A — Inventario de pantallas y capacidades afectadas

Descriptivo; los nombres de archivo, si hacen falta para desambiguar, están en el apéndice B.

| Pantalla o capacidad | Qué hace hoy | Efecto de esta spec |
|---|---|---|
| Panel del Workspace (lista de torneos) | Lista, crea y abre torneos | Sin cambios; sus textos son ancla del arnés (RNF-008) |
| Configuración del torneo (pantalla única) | Reúne resumen, reglas, fases, equipos, plantillas y calendario; la entrada está oculta sin permiso de gestión | Conserva resumen, reglas, fases y equipos; deja de alojar plantillas y calendario; se marca como sección activa, pasa a ser visible en solo lectura para observadores y muestra la advertencia cuando el formato no es 11v11 |
| Navegación del torneo | Seis anclas de una sola página, sección activa fija | Resumen, configuración, calendario y plantillas con su dirección; «Equipos» deja de ser entrada; operación solo con un partido en contexto; atrás del navegador y redirección de enlaces antiguos |
| Editor de reglas | Siete bloques y modo de texto avanzado, un solo guardado | Asistente por pasos, con pasos obligatorios y opcionales, un paso de formato de juego y mínimo de jugadores, paso en la dirección y borrador de pestaña; conserva bloques, modo avanzado y contenido enviado |
| Alta de fases e inscripción | Formulario de nombre, tipo y orden, y un panel aparte de equipos | Un solo asistente con identificación, composición opcional y revisión; muestra el estado de plantilla de cada equipo y bloquea la inscripción fuera de los límites; creación e inscripción informadas por separado, con reintento sobre la fase creada |
| Alta de equipos y carga masiva | Formulario y pegado/archivo CSV; la interfaz exige fase | Asistente con datos y dos vías alternativas de alta; deja de inscribir en fase |
| Administración de plantillas | Importación CSV/ZIP, foto y consentimiento, embebida en configuración; sin forma de retirar ni reactivar un jugador | Dirección propia, formulario único de una pantalla; añade el alta individual que hoy vive en la operación y el **retiro lógico con reactivación**; avisa del cierre de inscripción y del estado de plantilla frente a los límites (sin bloquear) y enlaza al asistente de fases |
| Calendario | Crear partido, sortear/regenerar, listar partidos | Dirección propia; mismas acciones y confirmaciones |
| Operación del partido | Segmentos, planilla, oficiales, eventos, cierre y alta de jugadores; máximo de la fase | Conserva todo menos el alta de jugadores; bloquea la apertura si la plantilla está fuera de los límites (mismo 409); advierte si el formato no es 11v11; resolución prevista con su ciclo de vida, enviada al crear o interrumpir segmentos y al cerrar; máximo de la resolución prevista para eventos y segmentos; 409 unificado de resolución no habilitada; enlace a plantillas |
| Campo táctico público y modal de planilla pública | Muestran posiciones por código | Muestran la posición traducida con la regla de lado; mismo dato y mismo código |
| Directorio de miembros e invitación | Roles traducidos salvo el rol no editable | Roles traducidos en todos los casos desde una única fuente |
| Selectores de rol y de posición | Rol traducido; posición por código | Ambos traducidos desde una única fuente |
| Mensajes de validación y de error | Errores por panel, a veces el primero solo, y una clave ausente | Errores por campo en el idioma activo, sin claves ausentes |
| Documentación del producto | Explica reglas y operación | Añade la navegación nueva, el catálogo de posiciones, los borradores, la resolución prevista, la regla de duración y el contrato aditivo |

Capacidades que se reutilizan sin cambios de contrato, salvo los cambios aditivos declarados en RNF-003: publicar versión, crear versión en borrador, resolver permisos y contexto de organización, sortear por formato de fase, cerrar acta, firmar y subir fotos, registrar consentimiento y validar configuración de reglas en el servidor.

## Apéndice B — Referencias de inspección

Rutas citadas para desambiguar; no forman parte de los requisitos.

- **Navegación y secciones:** `frontend/app/components/WorkspaceShell.vue:5` (secciones), `:72-89` (índice del torneo como anclas; «configuración» condicionada al permiso), `:282-304` (índice y selector); `frontend/app/pages/workspace/tournaments/[id].vue:946` (sección activa fija en «configuration»), `:1215` (ancla de operación sobre el listado de partidos).
- **Configuración del torneo:** `frontend/app/pages/workspace/tournaments/[id].vue:979-998` (formulario de reglas y guardado), `:1007-1022` (alta de fases), `:1024-1080` (equipos de la fase), `:1082-1111` (alta de equipos y carga masiva), `:1113-1145` (plantillas), `:1147-1218` (calendario, sorteo y lista de partidos), `:1222` (error compartido al final del documento), `:893-899` (solo el primer error de validación), `:1093` (fase obligatoria en la interfaz).
- **Editor de reglas:** `frontend/app/components/RulesEditor.vue:232-367` (bloques y modo avanzado), `:332-337` (prórroga y minutos por defecto), `:353-361` (excepciones por fase), `:204-212` (minutos de prórroga por defecto), `:214-224` (minutos por fase).
- **Validación de reglas:** `frontend/app/utils/rulesConfig.ts:92-135` (códigos y claves de mensaje), `:420-489` (validación por sección), `:522-539` (pareja de minutos); `backend/app/modules/rules_engine/engine.py:35-45` (claves obligatorias del esquema: puntuación, orden de desempates, disciplina, resolución y excepciones).
- **Operación del partido:** `frontend/app/pages/workspace/matches/[id].vue:214-222` (formulario de jugador), `:738-753` (alta de jugador contra plantillas del torneo), `:1094-1103` (formulario de alta dentro de la operación), `:375` (opciones de resolución tomadas de los valores por defecto de la versión, sin la excepción de la fase), `:383-392` y `:1188-1190` (selector de resolución en el cierre), `:339` (límites de la operación), `:800-807` (validación del minuto al registrar), `:198-200` y `:395-475` (borrador local del partido en el almacenamiento del navegador), `:267-283` (roles de oficial traducidos), `:604-606` (segunda implementación de la etiqueta de posición), `:1135-1138` (selector de posición).
- **Formaciones y posiciones:** `frontend/app/constants/formations.ts:1-35` (cuatro formaciones, rejilla y etiqueta por sustitución); `frontend/app/components/public/MatchPitch.vue:78,90`; `frontend/app/components/public/PublicLineupModal.vue:203`; `docs/contrato-reglas.md:46-80` (catálogo cerrado y posiciones); `backend/app/modules/rule_contract.py:25-86`.
- **i18n:** `frontend/app/composables/useI18n.ts:8-1369` (catálogo), `:178-188` (roles y estados), `:487-488` (minutos reglamentarios y con prórroga), `:1371-1425` (idioma, traducción, etiquetas de estado y de formato, mensajes de error). Clave ausente: `setup.noScheduleGeneration`, usada en `frontend/app/pages/workspace/tournaments/[id].vue:639` y **no declarada** en el catálogo (barrido de claves usadas contra el catálogo: 0 ausencias en las demás).
- **Roles:** `frontend/app/utils/labels.ts:11-51`; `frontend/app/pages/workspace/members.vue:197,265,279,300-304`; `frontend/app/pages/invitations/[token].vue:102`; `frontend/tests/labels.test.ts:37-121`.
- **Duración en el servidor:** `backend/app/modules/rules_engine/defaults.py:7-16` (90/120), `backend/app/modules/rules_engine/engine.py:115-145` (esquema de minutos), `:178-216` (resolución efectiva por fase y validación de la pareja), `:241-248` (materialización de valores por defecto); `backend/app/modules/matches/service.py:59-81` (minutos efectivos y máximo), `:84-94` (máximo por resolución, criterio que se conserva), `:97-122` (tope sobre la suma y ventana del último minuto), `:593` (máximo en el cierre para segmentos y eventos); `backend/app/modules/matches/router.py:61-107` (la operación usa la configuración de la versión del partido), `:258-270` (límites que recibe la operación), `:497-510` (tope del segmento con el máximo de la fase), `:591-615` (interrupción: tope con el máximo de la fase y 422 de rango); `backend/app/modules/matches/schemas.py:151-153` (creación de segmento: hoy sin resolución; SG-1 añade el campo opcional), `:156-159` (interrupción: hoy sin resolución; P5 añade el mismo campo), `:78-88` (el cierre ya envía `resolution_type`).
- **Duración en el cliente:** `frontend/app/utils/substitutions.ts:119-128` (límites de respaldo), `:138-155` (normalización de los límites informados).
- **Contratos del alcance (no cambian, salvo lo declarado en RNF-003):** `backend/app/modules/tournaments/router.py` — versiones, reglas, fases, equipos de fase, equipos, equipos en bloque, plantillas, importación, foto, consentimiento, partidos, sorteo y generación de eliminación directa; `backend/app/modules/matches/router.py` — operación, segmentos, interrupción, planilla, publicación, oficiales y cierre; `backend/app/modules/tournaments/schemas.py:54` (fase opcional en el alta de equipo), `:58-79` (alta de jugador con documento y fecha de nacimiento).
- **Formato de juego y mínimo de jugadores (inspección 2026-10-22):** no existe ninguna clave ni validación de formato, tamaño de equipo o mínimo de jugadores en `backend/`, `frontend/app/`, `infra/postgres/migrations/` ni `init/`. Catálogo cerrado y de once: `docs/contrato-reglas.md:46-80` (cuatro formaciones y sus posiciones), `backend/app/modules/rule_contract.py:25-86`, `infra/postgres/migrations/007_tactical_lineups.sql:31-36` (`CHECK` de `formation_code`); planilla con once titulares: `backend/app/modules/matches/router.py:787` y `:972`; mínimo actual de un jugador por equipo: `backend/app/modules/matches/router.py:734` y `backend/app/modules/matches/service.py:570`; esquema de configuración cerrado a propiedades declaradas: `backend/app/modules/rules_engine/engine.py:35-41` y `frontend/app/utils/rulesConfig.ts:167-178,374`; guardado de reglas y bloqueo de versión publicada: `backend/app/modules/tournaments/router.py:740,765`; plantillas sin mínimo ni máximo, solo dorsal único por equipo: `infra/postgres/init/01_schema.sql:270-295`; petición de planilla: `backend/app/modules/matches/schemas.py:183-187`; endpoints de plantilla que hoy existen: `POST /rosters`, `POST /rosters/bulk`, `POST /rosters/{id}/photo` y `PATCH /rosters/{id}/photo-consent` (`backend/app/modules/tournaments/router.py:1898-1920,2065-2066,2157-2158`), sin endpoint de estado; bloqueo por jornada: `backend/app/modules/tournaments/router.py:209-230` (`_enforce_roster_lock`) aplicado en el alta individual `:1911` y en la importación `:1980,2015`, con su prueba `backend/tests/test_roster_lock.py`; bloques del editor de reglas: `frontend/app/components/RulesEditor.vue:257-365`; inscripción de equipos en una fase, hoy sin comprobación de cantidad: `backend/app/modules/tournaments/router.py:1064-1140`; apertura del partido como creación del primer segmento: `backend/app/modules/matches/router.py:488-570` (endpoint y alta del segmento) y `frontend/app/pages/workspace/matches/[id].vue:691` (acción «crear/iniciar segmento»; no existe un endpoint de apertura ni una transición a `live` en la aplicación); conteo de plantilla por equipo: `GET /api/v1/tournaments/{tournament_id}/rosters?team_id=` (`backend/app/modules/tournaments/router.py:1853-1860`).
- **Permisos:** `frontend/app/components/WorkspaceShell.vue:42-43`; `frontend/app/pages/workspace/tournaments/[id].vue:195`; `frontend/app/pages/workspace/matches/[id].vue:303-313`.
- **Arnés de extremo a extremo (anclas que no cambian):** `frontend/e2e/labels.ts:130-154` (`E2E_LABELS`: inicio de sesión, `workspace.private`, `workspace.yourTournaments`, `workspace.configure`, `match.buildReport`, `match.eventType`, `match.minute`, `match.substitutionPreview`) y `:62-123` (`REALTIME_STATUS_TEXT` de las tres vistas); `frontend/e2e/realtime-workspace.spec.ts:39-70`.

## Apéndice C — Tabla de posiciones (referencia verificable de RF-027)

El código es el valor contractual; la etiqueta es presentación. El lado solo aparece cuando el código lo declara. `CM_L` y `LCM` comparten etiqueta en distintas formaciones y son códigos distintos: la tabla tiene 23 filas.

| Código | Español | English | Lado |
|---|---|---|---|
| `GK` | Portero | Goalkeeper | — (no declarado) |
| `CB` | Central | Centre-back | — (no declarado) |
| `LCB` | Central izquierdo | Left centre-back | Izquierdo |
| `RCB` | Central derecho | Right centre-back | Derecho |
| `LB` | Lateral izquierdo | Left back | Izquierdo |
| `RB` | Lateral derecho | Right back | Derecho |
| `LWB` | Carrilero izquierdo | Left wing-back | Izquierdo |
| `RWB` | Carrilero derecho | Right wing-back | Derecho |
| `CDM_L` | Pivote izquierdo | Left defensive midfielder | Izquierdo |
| `CDM_R` | Pivote derecho | Right defensive midfielder | Derecho |
| `CM` | Mediocentro | Central midfielder | — (no declarado) |
| `CM_L` | Mediocentro izquierdo | Left central midfielder | Izquierdo |
| `CM_R` | Mediocentro derecho | Right central midfielder | Derecho |
| `LCM` | Mediocentro izquierdo | Left central midfielder | Izquierdo |
| `RCM` | Mediocentro derecho | Right central midfielder | Derecho |
| `LM` | Interior izquierdo | Left midfielder | Izquierdo |
| `RM` | Interior derecho | Right midfielder | Derecho |
| `CAM` | Mediapunta | Attacking midfielder | — (no declarado) |
| `LW` | Extremo izquierdo | Left winger | Izquierdo |
| `RW` | Extremo derecho | Right winger | Derecho |
| `ST` | Delantero centro | Centre-forward | — (no declarado) |
| `ST_L` | Delantero izquierdo | Left forward | Izquierdo |
| `ST_R` | Delantero derecho | Right forward | Derecho |
