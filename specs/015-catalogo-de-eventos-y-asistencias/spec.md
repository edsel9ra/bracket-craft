# Spec 015 — Catálogo de eventos y asistencias

Estado: implementada (2026-10-25)

## Contexto y objetivo

El acta de un partido se compone con un **único formulario para siete tipos de evento**: todos comparten el mismo payload, el tipo no cambia lo que se pide y ningún campo declara a qué tipo pertenece. `metadata` es un diccionario libre que viaja íntegro a la auditoría del cierre, `foul` se registra sin ningún efecto ni consumidor y **no existe ningún concepto de asistencia** en el modelo, la API, la interfaz, el motor ni las proyecciones.

Esta spec **no añade reglas de fútbol nuevas**: fija qué campos pide cada tipo, cierra el catálogo, formaliza la asistencia como dato del gol y declara la coherencia estructural que el servidor ya debería exigir. El cierre del acta y el walkover **no** están aquí: son las specs **016** (walkover) y **017** (cierre de actas y segmentos).

**Objetivo:** que cada tipo de evento tenga su formulario, que la API rechace lo que no aplica a cada tipo, que la asistencia exista una sola vez y ligada a su gol, y que ni la `metadata` ni el identificador de cliente sean canales de texto libre hacia el acta.

### Estado verificado (2026-10-25)

Comprobado sobre el árbol de trabajo; se describe lo observado, no el diseño.

| # | Hecho verificado | Evidencia |
|---|---|---|
| 1 | El catálogo es un `Literal` de **siete** tipos y todos comparten un único payload con `player_id`, `beneficiary_team_id`, `player_out_id`/`player_in_id`, `minute`, `added_minute`, `segment_id` y `metadata`. | `backend/app/modules/matches/schemas.py:32-79` |
| 2 | El tipo no condiciona los campos: un `yellow_card` acepta `beneficiary_team_id` igual a su propio equipo y solo una comprobación de base lo tolera (`chk_own_goal_beneficiary`); un `goal` lo acepta si coincide con su equipo. | `schemas.py:68-72`, `infra/postgres/init/01_schema.sql:594-597` |
| 3 | `metadata` es libre (tope de 50 claves y 10 000 caracteres); solo se valida `red_card_type` en `red_card`. | `schemas.py:46-52, 73-78` |
| 4 | La petición **no** usa `extra="forbid"`: una clave desconocida de primer nivel se ignora en silencio. | `schemas.py:32-46` (sin `model_config`) |
| 5 | La auditoría del cierre guarda la petición completa, con `metadata` y `client_event_id`. | `backend/app/modules/matches/service.py:470-478` |
| 6 | `client_event_id` es texto libre de hasta 100 caracteres, único por partido. | `schemas.py:33`, `init/01_schema.sql:577,592` |
| 7 | La comparación de idempotencia **no** mira `metadata`: un reintento que cambia `red_card_type` se reutiliza en silencio. | `service.py:859-889` |
| 8 | Un jugador que no está en la planilla del partido responde **409** («no está en la planilla»), también si es de otra organización; nunca 404. | `service.py:838-839`, `service.py:242-246` |
| 9 | `foul` se registra y **no tiene consumidor**: no cuenta goles, no entra en disciplina, no genera sanciones y no se lee en clasificación; el motor lo valida como evento de jugador (pertenencia y presencia en campo). | `backend/app/modules/rules_engine/substitutions.py`, `service.py:177-264` |
| 10 | **No existe asistencia** en modelo, API, interfaz, motor, clasificación ni auditoría. | búsqueda en `backend/`, `frontend/app/`, `infra/` |
| 11 | El marcador se calcula solo con `goal`, `own_goal` y `penalty_goal`, acreditando al beneficiario en el autogol. | `service.py:750-789`, `rules_engine/engine.py:332-335` |
| 12 | La operación devuelve los eventos con `player_id` y el nombre del jugador resuelto en la consulta; la plantilla del partido ya devuelve nombre y apellidos por `player_id`. | `backend/app/modules/matches/router.py:577-591`, `:551-568` |

### Dependencias con las otras specs

- **017 (cierre de actas y segmentos)** es quien **escribe** el acta: la autorización de la escritura, el orden de validación del cierre y la inmutabilidad del acta confirmada viven allí. Esta spec define el catálogo y la estructura del evento; la 017 los consume al cerrar.
- **016 (walkover)** usa este catálogo para declarar que un walkover **no admite eventos**. Esta spec no decide nada del walkover.
- Esta spec **no** depende de ninguna migración de las otras dos: su único cambio de esquema es el de la asistencia (`026`).

## Usuarios

- **Operador de partido:** compone el acta; es quien elige el tipo y rellena solo sus campos.
- **Administrador o dueño de la organización:** revisa y explica un acta; necesita que un hecho esté descrito con los datos que le corresponden.
- **Observador (`viewer`):** consulta el acta en solo lectura.
- **Público:** no ve el acta ni las asistencias.
- **Mantenedor del producto:** necesita el catálogo escrito, tipo por tipo, para no deducirlo del código.

## Roles y visibilidad

- **Público:** sin cambios. No se añade ninguna proyección, ni eventos individuales, ni asistencias.
- **Miembro sin rol (403):** conserva el contrato vigente en toda ruta protegida.
- **Observador (`viewer`):** conserva la lectura de la operación y ninguna escritura. El formulario por tipo es legible en solo lectura.
- **Operador y árbitro:** componen el acta con la autorización de cierre que define la **017** (permiso `CLOSE_MATCH_REPORT` **y** rol `owner`/`administrator`/`operator` o estar asignado en `match_officials`). Esta spec no concede ninguna escritura nueva ni cambia ese criterio.
- **Administrador de plataforma:** no aplica; `/admin` no edita actas ni resultados.
- **Aislamiento:** toda lectura y validación se ejecuta con el contexto de aislamiento fijado. La regla de identificadores es única (RF-014).

## Historias de usuario

- **HU-1.** Como operador, quiero que al elegir «gol» el formulario me pida solo lo de un gol, para no dudar de qué es obligatorio ni rellenar campos que no aplican.
- **HU-2.** Como operador, quiero registrar quién dio la asistencia sin crear un evento aparte que pueda duplicarse o desalinearse del gol.
- **HU-3.** Como operador, quiero que el acta me impida describir un hecho imposible (un autogol con asistencia, una tarjeta con equipo beneficiario, un asistente que no jugó).
- **HU-4.** Como administrador, quiero que un texto libre no acabe guardado en el acta ni en la auditoría sin querer.
- **HU-5.** Como mantenedor, quiero el catálogo y la asistencia escritos para no deducirlos del código.

## Definiciones

- **Evento.** Hecho deportivo del acta con un tipo del catálogo cerrado, un equipo, un segmento, un minuto y un `client_event_id` idempotente.
- **Campo propio.** Campo que solo existe en un tipo; informarlo en otro es **422**.
- **Campo compartido.** Campo presente en todos los tipos: equipo, minuto, minuto añadido, segmento y tipo.
- **Asistencia.** Pase o acción del compañero que precede inmediatamente a un gol. **No es un evento**: es el campo `assist_player_id` del evento de gol, opcional y como máximo uno por gol.
- **Catálogo cerrado.** Ni la lista de tipos ni el conjunto de campos admitidos por tipo se amplían sin cambiar esta spec.
- **Identificador de cliente.** `client_event_id`, token opaco que hace idempotente un evento dentro de un partido.

## Decisiones cerradas

| Código | Decisión | Motivo |
|---|---|---|
| **D-1** (2026-10-25) | La funcionalidad se divide en tres specs: 015 (catálogo y asistencias), 016 (walkover) y 017 (cierre y segmentos). | Cada una tiene un disparador, un riesgo y una verificación distintos; el artefacto único tenía 28 hallazgos de QA. |
| **DU-1** | Asistencia = columna nueva `assist_player_id` del evento de gol, 0..1 estructural, con clave foránea al jugador. | Garantiza «una por gol» de forma estructural y no puede desalinearse ni duplicarse. |
| **DU-2** | La asistencia es **opcional siempre**. | No bloquea el cierre cuando el operador no la conoce ni obliga a inventarla. |
| **DU-3** | **Penalti y autogol no admiten asistencia** (**422**). | El autogol ya tiene beneficiario y el penalti no nace de un pase. |
| **DU-4** | `foul` **se conserva** como informativo, con formulario mínimo propio. | No invalida datos ni clientes y cierra la ambigüedad. |
| **D-2** (2026-10-25, corregida) | La autorización del acta es la **conjunción** real: permiso `CLOSE_MATCH_REPORT` **y** (rol `owner`/`administrator`/`operator` **o** asignación en `match_officials`). | Es el criterio vigente verificado en el código y el usuario lo confirmó; esta spec no lo cambia. |

## Requisitos funcionales

### Catálogo y formularios

- **RF-001.** CUANDO el operador elija un tipo de evento, EL SISTEMA mostrará únicamente los campos que ese tipo admite, con los obligatorios marcados y los no aplicables **ausentes**, no deshabilitados ni ocultos con un valor residual.
  *Criterios de aceptación:*
  - Compartidos por todos los tipos: equipo, minuto, minuto añadido, segmento y tipo.
  - `goal`: jugador (goleador) y **asistente opcional** (RF-007).
  - `penalty_goal`: jugador, **sin asistente**.
  - `own_goal`: jugador (autor en su propio equipo) y equipo beneficiario, obligatorio y distinto del equipo del jugador; **sin asistente**.
  - `yellow_card`: jugador.
  - `red_card`: jugador y clase de roja (`direct_red` o `double_yellow_red`), con `direct_red` por defecto.
  - `substitution`: jugador que sale y jugador que entra.
  - `foul`: **solo añade el jugador**; minuto, minuto añadido, segmento y equipo siguen siendo compartidos. Se describe como informativo y sin efecto (DU-4).
  - Al cambiar de tipo se descarta el valor escrito en un campo que el nuevo tipo no admite; ningún valor viaja a un tipo que no lo declara.

- **RF-002.** EL SISTEMA rechazará con **422** cualquier evento que lleve un campo o una clave que su tipo no declara, en la raíz del evento y en su información adicional.
  *Criterios de aceptación:*
  - `beneficiary_team_id` solo en `own_goal`; informado en cualquier otro tipo es **422** (hoy se tolera en un gol si coincide con su equipo y en las tarjetas sin comprobación).
  - `player_out_id` y `player_in_id` solo en `substitution` (ya vigente).
  - La clase de roja solo en `red_card` (ya vigente).
  - El asistente solo en `goal`; en los otros seis tipos es **422**.
  - `metadata` solo admite `red_card_type` en `red_card`; cualquier otra clave, en cualquier tipo, es **422** y no se persiste ni llega a la auditoría.
  - Una clave desconocida **en la raíz** del evento es **422**: el catálogo cerrado aplica a los dos niveles.
  - Todo lo anterior se resuelve en el esquema, antes del handler, y no escribe nada.

- **RF-003.** EL SISTEMA exigirá que el jugador de cada evento sea coherente con su tipo y con el equipo indicado.
  *Criterios de aceptación:*
  - En `own_goal`, el jugador pertenece al equipo que concede (el del evento) y el beneficiario es el otro participante.
  - En `goal` y `penalty_goal`, el equipo del evento es el equipo del jugador.
  - El jugador consta en la plantilla válida del partido para ese equipo; el equipo y el beneficiario son participantes.
  - La violación de estructura es **422**; la de pertenencia es **409** (RF-014).

- **RF-004.** EL SISTEMA conservará los siete tipos y su efecto deportivo, con `foul` como tipo informativo.
  *Criterios de aceptación:*
  - Ningún tipo cambia de efecto sobre el marcador, la clasificación, el fair play o las sanciones.
  - `foul` se registra con jugador, equipo, minuto, minuto añadido y segmento, sin efecto contable ni disciplinario, y la interfaz lo describe como informativo.
  - `foul` no se retira ni de la interfaz ni de la API; sus eventos históricos se conservan y no se revalidan.

- **RF-005.** EL SISTEMA mostrará el acta como una lista en la que cada tipo se lee con sus datos pertinentes, sin columnas comunes vacías.
  *Criterios de aceptación:*
  - Gol: goleador, asistente (si lo hay) y equipo acreditado.
  - Autogol: autor y equipo beneficiado, sin asistente.
  - Tarjeta: jugador y clase; la roja por doble amarilla se distingue de la directa.
  - Sustitución: sale y entra. Falta: jugador, sin efecto.
  - Ningún tipo muestra un campo que no le corresponde.

- **RF-006.** CUANDO el operador añada un evento al borrador, EL SISTEMA comprobará en el cliente **exactamente** este subconjunto y no añadirá el evento si alguno falla.
  *Criterios de aceptación:*
  - Minuto y minuto añadido contra el máximo efectivo de la resolución prevista (regla de la spec 012).
  - Segmento seleccionado y activo, y minuto dentro de su intervalo cuando el segmento tiene fin.
  - Jugador en la plantilla activa del equipo elegido.
  - Par de sustitución completo, con jugadores distintos y ambos elegibles.
  - Asistente distinto del goleador, del mismo equipo y con jugador seleccionado; el resto de la validez del asistente es **autoridad del servidor**.
  - Autogol con beneficiario distinto; ausencia de asistente en los tipos que no lo admiten.
  - El error se muestra junto al campo, en el idioma activo, y no borra lo escrito.
  - Lo que el cliente **no** replica —presencia real en campo en ese minuto, límites y ventanas de sustitución, coherencia con eventos ya persistidos, sanciones— se declara como autoridad del servidor.

### Asistencias

- **RF-007.** EL SISTEMA registrará la asistencia como un campo del evento de gol —`assist_player_id`, nulo salvo que se informe— con cardinalidad estructural **0..1 por gol**; no existirá un evento de asistencia ni una asistencia sin gol.
  *Criterios de aceptación:*
  - Es una columna nueva del acta, opcional, con clave foránea compuesta con la organización al jugador; ninguna fila nueva de evento y ningún tipo nuevo en el catálogo.
  - Un gol admite **como máximo un asistente**: el modelo no permite más y lo impide la estructura, no solo la validación de la API.
  - La asistencia viaja en el mismo evento y con el mismo `client_event_id`, así que un reintento no puede duplicarla ni crear una huérfana.
  - Es opcional siempre: omitirla no impide añadir el gol ni cerrar el acta.
  - La interfaz no ofrece el campo en ningún tipo distinto de `goal`.

- **RF-008.** SI se informa un asistente, ENTONCES EL SISTEMA comprobará que pertenece a la plantilla válida del partido, al **mismo equipo** que el goleador, que es distinto de él y que está en el campo en el minuto del gol.
  *Criterios de aceptación:*
  - Asistente de otro equipo, fuera de la plantilla del partido, expulsado o ya sustituido en ese minuto: **409** con `code` aditivo `ASSIST_PLAYER_INVALID`.
  - Asistente igual al goleador: **422**, por incoherencia estructural (no 409).
  - La comprobación usa el mismo estado en campo derivado que el resto del acta, no una segunda implementación.
  - Un mismo jugador puede asistir dos goles distintos del mismo partido: es válido y no consume ningún cupo.

- **RF-009.** SI el tipo de evento es `own_goal`, `penalty_goal`, `substitution`, `yellow_card`, `red_card` o `foul`, ENTONCES EL SISTEMA rechazará cualquier asistente con **422**.
  *Criterios de aceptación:*
  - Ni el autogol ni el penalti admiten asistencia: el primero ya tiene beneficiario y el segundo no nace de un pase.
  - Una sustitución, una tarjeta y una falta tampoco la admiten.
  - El rechazo es estructural, antes del handler, y no escribe.

- **RF-010.** EL SISTEMA no contará la asistencia como gol ni como hecho disciplinario: no altera el marcador reglamentario ni el final, no suma fair play, no genera suspensiones, no interviene en desempates y no cambia el ganador.
  *Criterios de aceptación:*
  - El marcador se sigue calculando solo con `goal`, `own_goal` y `penalty_goal`.
  - La clasificación y las sanciones dan el mismo resultado con y sin asistencias.
  - Una prueba compara el cierre con y sin asistencia y exige marcador, puntos y sanciones idénticos.

- **RF-011.** CUANDO se cierre un acta con una asistencia, EL SISTEMA la conservará con el resto del acta, la devolverá en la operación del partido y la incluirá en el registro de auditoría del cierre, sin publicarla.
  *Criterios de aceptación:*
  - La respuesta de operación devuelve `assist_player_id` (UUID) en cada evento; **no** añade nombre ni apellidos, y el cliente lo resuelve desde la plantilla del partido que ya recibe.
  - La auditoría guarda el identificador del jugador, nunca su nombre.
  - Ninguna ruta pública ni vista pública expone asistencias.

- **RF-012.** EL SISTEMA mantendrá la idempotencia del evento y la extenderá a todo lo que el evento declara.
  *Criterios de aceptación:*
  - `client_event_id` repetido dentro del mismo acta es **422**.
  - Un evento ya persistido idéntico se reutiliza sin doble conteo; uno con datos distintos responde **409** «inmutable».
  - La comparación incluye `metadata` (hoy no la mira: un reintento que cambia `red_card_type` se reutiliza en silencio) y el asistente.
  - Un reintento idéntico es idempotente aunque el primero no llevara asistente.

- **RF-013.** EL SISTEMA no reescribirá ningún dato existente: los goles ya cerrados quedan sin asistente y **siguen siendo válidos**, y los eventos históricos conservan su información adicional actual.
  *Criterios de aceptación:*
  - Un gol sin asistente nunca se considera inválido, ni antes ni después de la migración.
  - No hay *backfill* ni relleno por inferencia.
  - Los eventos con claves de `metadata` que hoy no se declaran no se revalidan al leer ni al consultar el acta; solo un evento **nuevo** pasa por el catálogo cerrado.

### Identificadores y aislamiento

- **RF-014.** EL SISTEMA aplicará una única regla de identificadores, la misma en todas las rutas del acta.
  *Criterios de aceptación:*
  - Partido, segmento o equipo de otra organización: **404**, sin revelar existencia.
  - Jugador no elegible, fuera de la plantilla del partido **o de otra organización**: **409**; el asistente lleva el `code` `ASSIST_PLAYER_INVALID`, el jugador de cualquier otro evento conserva el mensaje de pertenencia que ya existe. Nunca 404 y nunca un 500 por clave foránea.
  - La regla se aplica igual al goleador, al asistente, al jugador que sale y al que entra.

- **RF-015.** EL SISTEMA exigirá que `client_event_id` sea un identificador opaco con forma de UUID.
  *Criterios de aceptación:*
  - Un valor que no tenga forma de UUID responde **422**; no se persiste.
  - El cliente genera `crypto.randomUUID()`; si el navegador no lo ofrece, **no** añade el evento y lo explica, en lugar de inventar un texto.
  - El identificador deja de ser un canal de texto libre hacia `match_events` y hacia la auditoría.
  - Los eventos históricos con identificadores de otra forma se conservan y no se revalidan.

### Transversales

- **RF-016.** EL SISTEMA conservará el contrato interno de reglas sin cambios: `engine_version` sigue en **`2026.1`**, el catálogo de formaciones y `GF1`/`GF2` no se tocan y ninguna clave nueva entra en `rules_config`.
  *Criterios de aceptación:*
  - El catálogo de eventos y la asistencia son **aditivos y quedan fuera** del contrato cerrado, que solo cubre los códigos de llave y las formaciones.
  - `docs/contrato-reglas.md` no cambia de versión ni de contenido normativo.

- **RF-017.** EL SISTEMA no añadirá rutas ni permisos nuevos por el catálogo ni por la asistencia.
  *Criterios de aceptación:*
  - La escritura del acta sigue siendo la del cierre (spec 017) y su autorización no cambia.
  - El miembro sin rol conserva su **403** y el aislamiento se mantiene con **404** entre organizaciones.

## Requisitos no funcionales

- **RNF-001 (aislamiento).** Toda consulta y validación nueva se ejecuta dentro de la transacción con el contexto fijado y filtra por organización. Un identificador de otra organización se resuelve con la regla única de RF-014.
- **RNF-002 (privacidad).** Ningún mensaje nuevo incluye nombres, documentos ni fechas de nacimiento. Las vías de texto libre del acta quedan acotadas a las que se declaran: `client_event_id` pasa a ser un UUID (RF-015), `metadata` queda cerrada (RF-002) y **permanecen** el motivo de la resolución administrativa y las notas de interrupción —ambos con tope de 1 000 caracteres y ambos gobernados por la spec 017—, que no son datos personales por contrato pero podrían contenerlos; se documenta como riesgo aceptado. `players` no expone documentos ni fechas en ningún mensaje.
- **RNF-003 (contratos que cambian).** Se declaran y se documentan en el mismo cambio: (a) el evento de gol admite `assist_player_id`; (b) `metadata` deja de ser libre: una clave desconocida pasa de **aceptada** a **422**; (c) una clave desconocida de **primer nivel** pasa de **ignorada** a **422**; (d) `beneficiary_team_id` fuera de `own_goal` pasa de **tolerado** a **422** (también en un gol que lo iguala a su equipo); (e) el asistente es un campo nuevo y su violación de pertenencia añade el `code` `ASSIST_PLAYER_INVALID` en **409**; (f) `client_event_id` deja de ser texto libre y exige forma de UUID. **Salvedad:** un cliente que ignore los campos nuevos **no** conserva su comportamiento si enviaba `metadata` libre, claves de primer nivel no declaradas, `beneficiary_team_id` en un tipo que no lo admite o un `client_event_id` que no es un UUID: esos casos pasan a **422**. La compatibilidad se mantiene para el cliente actual, que ya envía solo los campos declarados.
- **RNF-004 (base de datos).** Un único cambio de esquema: la migración **026**, aditiva y sin *backfill*, que añade `match_events.assist_player_id` (UUID nula), su clave foránea compuesta con `organization_id` a `players` y la restricción estructural del asistente (solo en `goal`, distinto del goleador). No reescribe filas, no toca `init/01`, no añade RLS y tolera las filas históricas. La forma de `client_event_id` se valida **solo en la API**: un `CHECK` sobre una columna con datos históricos añadiría superficie de migración sin garantía nueva.
- **RNF-005 (verificación).** Pasan `cd backend && pytest -q`, `python -m compileall -q app`, las pruebas con base y, en el frontend, `pnpm test`, `pnpm run typecheck` y `pnpm run build`. Las pruebas de la interfaz son de componente/utilidad (`frontend/tests/*.test.ts`): el arnés `pnpm run e2e:test` **sí** cubre el alta de eventos y el cierre (proyecto `operation-flow`), así que su veredicto (0/1/2/3) se exige y se registra; el job `e2e` forma parte del cumplimiento de la §4 de la constitución. Lo que no se pueda ejecutar se declara **no ejecutado**.
- **RNF-006 (determinismo).** Ninguna regla nueva lee el reloj ni el entorno. La respuesta de un evento depende solo de su contenido y del estado persistido; los mensajes con varios elementos tienen orden estable.
- **RNF-007 (accesibilidad).** El formulario por tipo conserva etiqueta por campo, asociación de error y recorrido con teclado, y anuncia el cambio de tipo. Se conservan las anclas del arnés existente que usa la pantalla (`match.eventType`, `match.minute`) o se actualizan de forma declarada.
- **RNF-008 (rendimiento).** La validación del catálogo es de esquema y no añade consultas. La comprobación del asistente reutiliza el estado en campo ya calculado y no añade una consulta por evento.
- **RNF-009 (documentación).** Se actualizan `AGENTS.md` (catálogo por tipo, asistencia, cierre del `metadata`, identificador de cliente) y `README.md`; `/docs` refleja los campos y el código nuevos. `docs/contrato-reglas.md` no cambia.
- **RNF-010 (auditoría).** No se añade ninguna acción auditada; el cierre sigue registrando la suya (spec 017) y la asistencia viaja dentro de su contenido como identificador.
- **RNF-011 (tiempo real).** No se añaden eventos de outbox ni canales; se conservan los del cierre.

## Datos personales y privacidad

- **No se introducen datos personales nuevos.** El asistente es un jugador ya inscrito en la plantilla del partido y ya visible en la operación; no se guarda ningún dato suyo adicional.
- **Se cierran dos canales de texto libre**: `metadata` (solo `red_card_type`) y `client_event_id` (UUID). El motivo administrativo y las notas de interrupción permanecen y se documentan como riesgo aceptado en la spec 017.
- **Visibilidad:** el acta se ve en el Workspace con el contrato actual. Las asistencias no se publican: no se añaden a ninguna proyección ni ruta pública.
- **Fotos y consentimiento:** no aplica.
- **Auditoría:** guarda identificadores, nunca nombres ni documentos.

## Casos límite

1. **Cambio de tipo con datos escritos:** los campos que el nuevo tipo no admite se descartan y no viajan.
2. **Gol con dos asistentes:** no es representable; el modelo admite como máximo uno y no existe ninguna vía para informar dos.
3. **Asistente del equipo contrario:** **409** `ASSIST_PLAYER_INVALID`.
4. **Asistente que no está en la plantilla del partido:** **409** `ASSIST_PLAYER_INVALID`, aunque esté inscrito en el torneo.
5. **Asistente de otra organización:** **409** `ASSIST_PLAYER_INVALID` (regla única de RF-014); nunca 404 ni 500.
6. **Asistente que ya salió del campo en ese minuto:** **409** `ASSIST_PLAYER_INVALID`.
7. **Asistente igual al goleador:** **422**.
8. **Autogol con asistente:** **422**. **Gol de penalti con asistente:** **422**.
9. **Mismo jugador como asistente en dos goles del mismo partido:** válido; no consume cupo.
10. **Gol sin asistente:** válido siempre; no se exige ni se avisa.
11. **Reintento del mismo gol con el mismo asistente:** idempotente.
12. **Reintento del mismo gol sin el asistente que sí se guardó:** **409** «inmutable».
13. **Reintento que cambia `red_card_type`:** **409** «inmutable» (antes se reutilizaba en silencio).
14. **Gol ya cerrado antes de esta spec:** queda sin asistente y sigue siendo válido; no se reescribe ni se revalida.
15. **Clave de `metadata` desconocida:** **422**, no se persiste y no llega a la auditoría.
16. **Clave de primer nivel desconocida:** **422** (antes se ignoraba).
17. **`yellow_card` con equipo beneficiario:** **422**.
18. **`goal` con beneficiario igual a su equipo:** **422** (antes se aceptaba).
19. **`foul` registrado:** informativo y sin efecto; la interfaz lo ofrece con su formulario mínimo.
20. **`client_event_id` que no es UUID:** **422**; el cliente no añade el evento y lo explica.
21. **Evento histórico con identificador de otra forma o con `metadata` no declarada:** se conserva; no se revalida.
22. **Partido de otra organización:** **404** al operar; el jugador de otra organización es **409** con su código.
23. **Miembro sin rol:** **403**. **Observador:** lee y no escribe.
24. **Acta confirmada abierta en otra pestaña:** la operación se muestra en solo lectura (spec 017).

## Fuera de alcance

- **El cierre del acta, su orden de validación, la idempotencia del acta completa, la inmutabilidad del acta confirmada y los segmentos**: son la spec **017**.
- **El walkover**: estados, autorización, motivo y efecto son la spec **016**.
- **Nuevos tipos de evento** distintos de los siete actuales: no se añade falta técnica, penalti fallado, gol anulado ni asistencia como tipo.
- **API incremental de eventos** y cualquier escritura de eventos fuera del cierre (R11 de la spec 007).
- **`is_voided`** y las columnas de anulación: legado sin vía operativa.
- **Estadísticas por jugador, goleadores, tablas de asistencias o cualquier superficie pública nueva.**
- **Restringir el motivo administrativo o las notas de interrupción:** se documentan como riesgo aceptado; su endurecimiento, si se decide, va en la 017.
- **Cambios en `points_system`, `ranking_pipeline`, `discipline` o `substitutions`.**
- **Cambios en el contrato interno** (`engine_version` 2026.1, `GF1`/`GF2`, formaciones).
- **Rediseño visual completo** de la operación del partido.

## Criterios de finalización

Cada criterio cita los RF que lo respaldan; la columna de cobertura cierra la trazabilidad de los RNF.

| # | Criterio de finalización | RF |
|---|---|---|
| 1 | Cada tipo tiene un formulario propio que pide solo sus campos, marca los obligatorios y no envía los no aplicables; el cambio de tipo no arrastra valores. | RF-001 |
| 2 | El servidor rechaza con **422** cualquier campo o clave no declarado por el tipo, en la raíz y en `metadata`, y no escribe ni audita nada. | RF-002 |
| 3 | El jugador de cada evento es coherente con su tipo y su equipo; la estructura es **422** y la pertenencia **409**. | RF-003 |
| 4 | `foul` se conserva como informativo con formulario mínimo y sin efecto en marcador, clasificación, fair play ni sanciones. | RF-004 |
| 5 | El acta se lee por tipo, sin columnas comunes vacías ni campos ajenos. | RF-005 |
| 6 | El cliente valida **solo** el subconjunto declarado y muestra cada error junto a su campo; el resto se documenta como autoridad del servidor. | RF-006 |
| 7 | Un gol admite como máximo un asistente, del mismo equipo, distinto del goleador y en campo; la pertenencia responde **409** con su código y la igualdad con el goleador **422**. | RF-007, RF-008 |
| 8 | Autogol, penalti, sustitución, tarjeta y falta rechazan el asistente con **422**. | RF-009 |
| 9 | La asistencia no altera marcador, puntos, sanciones ni ganador; una prueba lo compara con y sin asistencia. | RF-010 |
| 10 | La asistencia se devuelve como identificador en la operación, se conserva con el acta y no aparece en ninguna superficie pública. | RF-011 |
| 11 | La idempotencia incluye `metadata` y el asistente: un reintento idéntico se reutiliza y uno distinto responde **409**. | RF-012 |
| 12 | Ningún dato existente se reescribe; los goles previos sin asistente y los eventos con `metadata` no declarada siguen siendo válidos y no se revalidan. | RF-013 |
| 13 | La regla de identificadores es única: 404 para partido, segmento o equipo de otra organización; 409 para el jugador no elegible o de otra organización. | RF-014 |
| 14 | `client_event_id` exige forma de UUID; uno inválido responde **422** y el cliente no inventa un texto alternativo. | RF-015 |
| 15 | `engine_version` sigue en **2026.1** y `docs/contrato-reglas.md` no cambia de versión ni de contenido normativo; se declara por escrito que el catálogo y la asistencia quedan fuera del contrato cerrado. | RF-016 |
| 16 | No hay rutas ni permisos nuevos; la autorización del acta es la del cierre y el miembro sin rol conserva **403**. | RF-017 |
| 17 | La migración es la **026**, aditiva, sin *backfill*, con columna, clave foránea y restricción del asistente; no edita migraciones aplicadas ni `init/01` y `sh -n infra/postgres/migrate.sh` pasa. | RNF-004 |
| 18 | Pasan `cd backend && pytest -q`, `python -m compileall -q app`, las pruebas con base, `pnpm test`, `pnpm run typecheck` y `pnpm run build`; lo no ejecutado se declara **no ejecutado**. | RNF-005 |
| 19 | Ningún mensaje nuevo expone datos personales y las vías de texto libre quedan acotadas a las declaradas (`metadata` cerrada, `client_event_id` UUID, motivo y notas con tope) con el riesgo documentado. | RNF-002 |
| 20 | La validación es determinista: mismas entradas, misma respuesta y orden estable en los mensajes con varios elementos. | RNF-006 |
| 21 | La validación del catálogo no añade consultas y la del asistente reutiliza el estado en campo ya calculado. | RNF-008 |
| 22 | No se añade acción auditada, evento de outbox ni canal de tiempo real. | RNF-010, RNF-011 |
| 23 | `AGENTS.md` y `README.md` describen el catálogo por tipo, la asistencia, el cierre de `metadata` y el identificador de cliente. | RNF-009 |

## Dudas abiertas

**Sin dudas abiertas.** DU-1 a DU-4 y la decisión de división (D-1) están cerradas en «Decisiones cerradas» y aplicadas en los requisitos. La spec está **aprobada** desde el 2026-10-25.

## Apéndice A — Catálogo objetivo por tipo

| Tipo | Propios obligatorios | Compartidos | Prohibidos | Efecto deportivo |
|---|---|---|---|---|
| `goal` | jugador (goleador); **asistente opcional** | equipo, minuto, añadido, segmento | beneficiario, sale/entra, `metadata` | Suma un gol al equipo del jugador |
| `penalty_goal` | jugador | equipo, minuto, añadido, segmento | beneficiario, sale/entra, `metadata`, asistente | Suma un gol al equipo del jugador |
| `own_goal` | jugador (autor) y beneficiario, distinto del equipo del jugador | equipo, minuto, añadido, segmento | sale/entra, `metadata`, asistente | Suma un gol al beneficiario |
| `yellow_card` | jugador | equipo, minuto, añadido, segmento | beneficiario, sale/entra, `metadata`, asistente | Fair play; acumulación |
| `red_card` | jugador y `red_card_type` | equipo, minuto, añadido, segmento | beneficiario, sale/entra, otra clave de `metadata`, asistente | Expulsión y suspensión; fair play |
| `substitution` | quién sale y quién entra, distintos | equipo, minuto, añadido, segmento | beneficiario, `metadata`, asistente | Estado en campo; cupo y ventana |
| `foul` | jugador | equipo, minuto, añadido, segmento | beneficiario, sale/entra, `metadata`, asistente | Ninguno (informativo) |

`assist_player_id` existe solo en `goal`; `client_event_id` (UUID) en todos.

## Apéndice B — Referencias de inspección

- Catálogo y esquema: `backend/app/modules/matches/schemas.py:32-79`; `infra/postgres/init/01_schema.sql:564-598` (`match_events`), `:577,592` (identificador de cliente).
- Persistencia, idempotencia y auditoría: `backend/app/modules/matches/service.py:822-920` (`_persist_events`), `:859-889` (comparación), `:470-478` (auditoría), `:750-789` (marcador), `:177-264` (`replay_report_state`), `:242-246` y `:838-839` (jugador fuera de plantilla → **409**).
- Estado en campo: `backend/app/modules/rules_engine/substitutions.py`.
- Operación: `backend/app/modules/matches/router.py:577-591` (eventos), `:551-568` (plantilla con nombres).
- Frontend: `frontend/app/pages/workspace/matches/[id].vue:260-330` (formulario único), `:1001-1073` (composición), `frontend/app/utils/substitutions.ts` (estado y límites).
- Patrón de migración aditiva: `infra/postgres/migrations/021_match_event_substitutions.sql`.
