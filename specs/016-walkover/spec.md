# Spec 016 — Walkover

Estado: implementada (2026-10-25)

## Contexto y objetivo

El walkover (W.O.) existe hoy **solo** como una resolución más del cierre. Exige `winner_team_id`, prohíbe cualquier evento y **el marcador lo escribe el cliente**, que debe acertar el valor configurado. El cierre exige además un **segmento activo** y **al menos un jugador en la plantilla de cada equipo**, de modo que el caso típico —un equipo que no se presenta— es hoy **imposible** sin abrir un segmento y sin inventar plantilla para el ausente. La declaración no deja motivo, no distingue estados y no comprueba que el marcador configurado sea coherente con el ganador.

Lo que **sí** está definido por las reglas del torneo: `stage_defaults.walkover_score`, con default `{winner: 3, loser: 0}` y override por fase. Esta spec no inventa marcadores, sanciones ni efectos: formaliza los que existen y hace que la declaración sea coherente, trazable y posible sin datos falsos.

**Objetivo:** que un W.O. se pueda declarar en un partido que no llegó a jugarse, con el marcador que fijan las reglas, un motivo de catálogo cerrado, la misma autorización que cerrar un acta y un efecto explícito en el resultado, la clasificación y las estadísticas.

### Estado verificado (2026-10-25, referencias revisadas tras la 017)

Las referencias se comprobaron de nuevo al cerrar la 017, que reescribió el cierre: los 14 pasos viven hoy en `CloseMatchReportService.execute` (`service.py:556-839`).

| # | Hecho verificado | Evidencia |
|---|---|---|
| 1 | `walkover` es una resolución del cierre: exige `winner_team_id`, prohíbe cualquier evento y el `reason` sigue prohibido fuera de la administrativa. | `backend/app/modules/matches/schemas.py:144-206` |
| 2 | El marcador **sí está definido por las reglas**: `stage_defaults.walkover_score` (default 3-0) con override por fase, y el cierre lo valida contra lo que envía el cliente. | `backend/app/modules/rules_engine/engine.py:127-168`, `:361-385`; `rules_engine/defaults.py:23, 54` |
| 3 | El esquema de reglas admite `winner` y `loser` como enteros ≥ 0 **sin exigir `winner > loser`**. | `rules_engine/engine.py:136-155` |
| 4 | La operación **sí** devuelve la configuración de la versión, incluidas `stage_defaults.walkover_score` y `stage_overrides`; lo que **no** publica es el valor **resuelto** en `limits`. | `matches/router.py:102` (campo `rules_config`), `:352-377` (`limits`) |
| 5 | El cierre exige un **segmento activo** y **al menos un jugador por equipo** de la plantilla válida, también para `walkover`. | `matches/service.py:651-664` (pasos 6 y 7), `:906-920` (`_validate_rosters`) |
| 6 | El cierre recalcula `match_segment_team_state` en **todas** las resoluciones, y cierra el segmento activo con el máximo minuto de los eventos del acta. | `service.py:762-780` (paso 14), `:1102-1169` (`_rewrite_segment_team_state`) |
| 7 | El cierre **valida las sanciones de la plantilla** (`_validate_suspensions`) y después **sirve** suspensiones de los jugadores del equipo que no están en la plantilla del partido, en cualquier resolución. | `service.py:695-696`, `:782-787`, `:1239-1462` |
| 8 | La clasificación decide la victoria **por marcador** y solo usa `winner_team_id` cuando el marcador está empatado. | `backend/app/modules/standings/service.py:153-198` |
| 9 | La autorización del cierre es una **conjunción**: permiso `CLOSE_MATCH_REPORT` **y** (rol `owner`/`administrator`/`operator` **o** estar asignado en `match_officials`). | `backend/app/core/permissions.py:7-59`; `matches/service.py:588-607` |
| 10 | La resolución administrativa exige **además** rol `owner` o `administrator`; el walkover no pasa por esa comprobación. | `permissions.py:62-75`; `service.py:592-604` |
| 11 | El formulario de cierre exige segmento activo y planilla completa en su validación previa y en la habilitación del botón, para **todas** las resoluciones; los marcadores solo cambian de `required`, no se deshabilitan, y el reglamentario siempre se envía (0 por defecto). | `frontend/app/pages/workspace/matches/[id].vue:762-804`, `:1329-1394`, `:1815-1831` |
| 12 | Un partido en estado `suspended` no puede cerrarse; ninguna ruta asigna `live` ni `suspended`. | `service.py:610-613` |
| 13 | Un resultado confirmado es inmutable en la base, sin excepción para administradores. | `infra/postgres/migrations/016_confirmed_match_result_immutability.sql` |
| 14 | **El motivo del walkover no cabe en `resolution_reason` con el esquema actual:** la restricción `chk_administrative_resolution_reason` (creada por la migración 009) exige `resolution_reason IS NULL` para toda resolución distinta de `administrative`. | `infra/postgres/init/01_schema.sql:416-424`; `infra/postgres/migrations/009_photo_resolution_and_outbox_hardening.sql:26-45` |
| 15 | Cuatro validaciones del cierre **ya** eximen a `walkover` en el tronco común; `_validate_rosters` es la única del paso 7 que no lo hace. | `service.py:995`, `:1039`, `:1083`, `:1200` (exenciones) frente a `:906-920` |

### Dependencias con las otras specs

- **015 (catálogo y asistencias)** define los tipos de evento. Esta spec solo declara que un W.O. **no admite ninguno**; la forma del catálogo no se toca aquí.
- **017 (cierre de actas y segmentos)** define la autorización del cierre (que esta spec reutiliza tal cual), el orden único de validación sobre el que esta spec define su rama, la matriz de marcadores por resolución y la inmutabilidad del acta confirmada. **La rama del walkover la implementa esta spec (016)**; la 017 delega en ella y no la reconoce ni la exime (decisión del 2026-10-25).
- **Contrato con la 017 (corregido el 2026-10-25):** la rama de walkover **la implementa esta spec**; la **017 delega** en ella y no la añade. Esta spec define una rama que se ejecuta **después** de comprobar sesión, permiso, estado, versión, dos equipos y resolución habilitada, y que **omite** los pasos de estructura de segmentos, plantilla, estado en campo, asistente, disciplina, marcador contra eventos y sanciones; la 017 mantiene el orden de los 14 pasos y el criterio 16 de esa spec queda **no aplicable hasta esta**.
- **Exenciones preexistentes que no son la rama:** cuatro validaciones del cierre (`_validate_event_team_scope`, `_validate_event_participants`, `_validate_substitutions` y `_validate_event_score_consistency`) ya devuelven sin hacer nada para `walkover` y administrativa desde antes de la 017. No son el mecanismo de esta spec —la rama las hace inalcanzables para el walkover— y se conservan porque siguen siendo la exención de la resolución administrativa (evidencia 15).

## Usuarios

- **Operador de partido (árbitro u oficial asignado):** declara el W.O. cuando el partido no se disputa.
- **Administrador o dueño de la organización:** declara W.O. por causas de gestión (retirada, sanción) y corrige la configuración de reglas si el marcador de W.O. es incoherente.
- **Observador (`viewer`):** consulta el resultado y la clasificación; no declara nada.
- **Público:** ve el resultado y la clasificación, sin ninguna marca de W.O.
- **Mantenedor:** necesita saber por qué el W.O. deja de exigir segmento y plantilla.

## Roles y visibilidad

- **Público:** sin cambios. No se añade ninguna marca de walkover ni superficie nueva; ve el marcador, el estado y la clasificación como hoy.
- **Miembro sin rol (403):** conserva el contrato vigente.
- **Observador (`viewer`):** no declara W.O. aunque esté asignado como oficial del partido, porque **no** tiene el permiso (RF-002).
- **Árbitro (`referee`) con el permiso `CLOSE_MATCH_REPORT`, pero no asignado al partido:** **no** puede declarar el W.O.; la conjunción exige la asignación (RF-002).
- **Árbitro asignado en `match_officials` sin el permiso:** **no** puede declararlo. **Operador con el permiso:** sí, sin necesidad de asignación.
- **Dueño y administrador:** declaran el W.O. con el mismo criterio; la resolución **administrativa** sigue exigiendo además rol `owner`/`administrator` (no cambia).
- **Administrador de plataforma:** no aplica; `/admin` no edita resultados.
- **Aislamiento:** un partido de otra organización responde **404**; un jugador de otra organización no interviene en esta ruta.

## Historias de usuario

- **HU-1.** Como operador, quiero declarar un W.O. sin abrir un segmento ni inventar una plantilla para el equipo que no se presentó.
- **HU-2.** Como operador, quiero que el marcador del W.O. salga de las reglas del torneo y no de lo que yo teclee.
- **HU-3.** Como administrador, quiero saber por qué se declaró un W.O. (incomparecencia, retirada, jugadores insuficientes o sanción).
- **HU-4.** Como administrador, quiero que no se pueda guardar un marcador de W.O. en el que el ganador pierda.
- **HU-5.** Como responsable de la tabla, quiero que un W.O. no altere la clasificación de forma distinta a la declarada.

## Definiciones

- **Walkover (W.O.).** Resolución por la que un partido se da por perdido sin disputarse, con un ganador declarado, el marcador que fija la configuración efectiva de la fase y un motivo de catálogo cerrado.
- **Marcador de walkover.** Pareja `{winner, loser}` configurada por fase, con default 3-0. Se aplica al marcador reglamentario y al final del partido.
- **Motivo de walkover.** Código del catálogo cerrado `no_show`, `withdrawal`, `insufficient_players` o `sanction`. Es descriptivo: **no** deriva sanción, puntuación ni efecto por sí mismo.
- **Configuración efectiva.** La de la versión publicada del partido, con la excepción de su fase si la declara.
- **Partido terminal.** Estado `finished`, `cancelled` o `administrative_resolution`; un partido terminal no admite escrituras de acta.

## Decisiones cerradas

| Código | Decisión | Motivo |
|---|---|---|
| **D-1** (2026-10-25) | La funcionalidad se divide en tres specs; el walkover tiene la suya. | Tiene disparador, riesgo y verificación propios. |
| **DU-5** (corregida) | Declara el W.O. **quien puede cerrar el acta**, con el criterio real: permiso **y** rol operativo **o** asignación como oficial. Sin permisos nuevos ni criterio más permisivo. | El árbitro presencia la incomparecencia; la autorización no se relaja. |
| **DU-6** | Efecto en la clasificación **como hoy**: cuenta como jugado, con el marcador configurado y sus goles en la diferencia. | Es lo que ya hace el motor; sin claves ni contrato nuevos. |
| **DU-7** | Motivo **obligatorio** de catálogo cerrado, en la auditoría existente, sin texto libre. | Trazabilidad sin abrir un campo libre en el acta. |
| **D-3** (2026-10-25) | `walkover_score` se valida al guardar y al publicar: `winner > loser` (**422**). | Hoy `winner < loser` produce un resultado cuya clasificación da la victoria al otro equipo. |
| **D-5** (decisión del autor, 2026-10-25) | Si en el cierre la pareja efectiva no refleja al ganador (`winner <= loser`, posible solo en una versión publicada antes de D-3), el W.O. responde **409** `WALKOVER_CONFIG_INCONSISTENT` y se ofrece la resolución administrativa como salida. | Una versión publicada no se puede reescribir; sin la guarda, el acta escribiría una clasificación que contradice al ganador declarado. Se prefiere fallar de forma explícita y trazable. |
| **D-6** (corrección verificada, 2026-10-25) | El motivo se guarda en la columna existente `resolution_reason` con una **migración correctiva (027)** que **relaja** `chk_administrative_resolution_reason` para admitir el código de walkover (o `NULL`). La obligatoriedad y el catálogo siguen siendo de la API. | La restricción vigente (009, `init/01`) exige `resolution_reason IS NULL` en toda resolución distinta de `administrative`, así que sin migración el `UPDATE` del cierre viola el `CHECK`. Se descarta guardar el motivo solo en la auditoría (incumpliría RF-007) y añadir una columna nueva (más superficie que relajar una restricción existente). Corrige RNF-004, el criterio de RF-007 y el criterio de finalización 20, que afirmaban «sin migración». |

## Requisitos funcionales

- **RF-001.** EL SISTEMA declarará un walkover solo con la resolución `walkover`, un ganador que sea uno de los dos participantes y la versión del torneo publicada, sobre un partido en **cualquiera de los estados que hoy admiten cierre**.
  *Criterios de aceptación:*
  - Los estados que hoy admiten cierre son los que no son `finished`, `cancelled`, `administrative_resolution` ni `suspended`; esta spec **no introduce ninguna transición de estado** y no asigna `live` ni `suspended` (hoy ninguna ruta lo hace).
  - `finished`, `cancelled` y `administrative_resolution` responden **409** con `code` aditivo `WALKOVER_STATE_NOT_ALLOWED`; `suspended`, **409** con el mismo código, porque hoy el cierre no lo admite.
  - Un ganador que no participa responde **409**; la falta de ganador, **422**.
  - Un partido de otra organización responde **404**.

- **RF-002.** EL SISTEMA exigirá para declarar un walkover **exactamente** la misma autorización que para cerrar un acta: el permiso `CLOSE_MATCH_REPORT` **y**, a la vez, rol `owner`, `administrator` u `operator` **o** estar asignado en `match_officials` para ese partido.
  *Criterios de aceptación:*
  - Un miembro con el permiso y sin rol operativo ni asignación responde **403**; un miembro asignado como oficial y sin el permiso, **403**.
  - No se añade ningún permiso, rol, delegación ni ámbito nuevo.
  - El W.O. **no** pasa por `require_administrative_resolution`; la resolución administrativa conserva su exigencia adicional de rol `owner`/`administrator`.
  - Un miembro sin rol conserva su **403** de contexto.

- **RF-003.** CUANDO se declare un walkover, EL SISTEMA **no** exigirá segmento activo, ni ningún segmento, ni planilla, ni alineación, ni oficiales, ni eventos.
  *Criterios de aceptación:*
  - Un partido sin ningún segmento se puede cerrar como walkover.
  - Un equipo sin ningún jugador inscrito no impide el walkover.
  - La apertura del partido y su control de tamaño de plantilla (spec 012) no se ejecutan en esta ruta.
  - **Contrato con la 017:** la rama de walkover la implementa **esta spec** (la 017 delega en ella); se ejecuta después de sesión, permiso, estado, versión, dos equipos y resolución habilitada, y omite los pasos de estructura, plantilla, estado en campo, asistente, disciplina, marcador contra eventos y sanciones.

- **RF-004.** CUANDO el partido tenga segmentos, EL SISTEMA cerrará el segmento **activo** en su propio minuto de inicio, dejará intactos los completados y los interrumpidos y **no** recalculará la proyección de contadores por equipo.
  *Criterios de aceptación:*
  - Un partido terminal no conserva ningún segmento activo: el activo pasa a `completed` con `minute_end = minute_start`, porque un walkover no registra eventos de los que derivar un final.
  - Los segmentos ya completados o interrumpidos no cambian de estado ni de minutos.
  - `match_segment_team_state` **no** se reescribe: no hay sustituciones que proyectar y el saldo inicial no aporta información nueva.
  - Sin segmentos, no se crea ninguno.

- **RF-005.** EL SISTEMA derivará el marcador del walkover de la configuración efectiva de la fase, lo publicará resuelto en la operación y aceptará la declaración sin marcadores.
  *Criterios de aceptación:*
  - `limits` añade `walkover_score` con los valores **efectivos** (incluida la excepción de fase), sin cambiar ninguna clave existente; la operación ya devuelve la configuración de la versión, pero no este valor resuelto.
  - Sin marcadores en la petición, el servidor aplica los configurados al reglamentario y al final.
  - Con marcadores informados que coincidan, la declaración sigue funcionando como hoy.
  - Con marcadores informados que no coincidan, **409** con `code` aditivo `WALKOVER_SCORE_MISMATCH`, sin escribir.
  - La interfaz los muestra en solo lectura: el operador no los edita.

- **RF-006.** EL SISTEMA rechazará con **422** cualquier evento en un walkover.
  *Criterios de aceptación:*
  - Se conserva la prohibición vigente y su código; no se admite ni un evento informativo.
  - El rechazo ocurre antes de escribir eventos, contadores, marcador o clasificación.

- **RF-007.** EL SISTEMA exigirá un motivo obligatorio de catálogo cerrado y lo registrará en el acta y en la auditoría del cierre.
  *Criterios de aceptación:*
  - El campo de la petición es `reason` (el de la columna es `resolution_reason`); para `walkover` lleva uno de los códigos `no_show`, `withdrawal`, `insufficient_players` o `sanction`.
  - Un motivo ausente o fuera del catálogo es **422**; no hay texto libre ni código «otra».
  - La obligatoriedad y el catálogo se validan en la **API**; la base solo **almacena** el código. La migración **027** (D-6) **relaja** la restricción existente `chk_administrative_resolution_reason` para que la columna lo admita; **no** impone la obligación, porque un `CHECK ... IN (...)` acepta `NULL` y no puede exigirla.
  - Se conserva la acción de auditoría existente `CLOSE_MATCH_REPORT`, que ya guarda el tipo de resolución; el motivo viaja en su contenido y no se añade una acción auditada nueva.
  - El motivo es **descriptivo**: no genera sanciones, no cambia puntos y no altera el marcador.

- **RF-008.** CUANDO se declare un walkover, EL SISTEMA aplicará el efecto vigente en el resultado, la clasificación y las estadísticas, y nunca generará tarjetas, sanciones, fair play ni estadísticas por jugador.
  *Criterios de aceptación:*
  - El partido queda `finished`, con `result_confirmed = TRUE`, y el marcador configurado en el reglamentario y en el final.
  - Cuenta como un partido **jugado** para ambos equipos: `played`, `won`/`lost`, puntos según `points_system` y goles del marcador en `goals_for`/`goals_against` y en la diferencia.
  - **Victory coherente:** el ganador declarado es el que recibe la victoria. Si el marcador efectivo no lo refleja —`winner <= loser` en una versión publicada antes de D-3— el sistema responde **409** con `code` aditivo `WALKOVER_CONFIG_INCONSISTENT` en lugar de escribir un resultado cuya tabla daría la victoria al otro equipo. La salida documentada es declarar el resultado como **resolución administrativa** (que exige dueño o administrador y admite un único marcador final), no reescribir la configuración publicada.
  - El avance de llave recibe al ganador; las comprobaciones de `GF1`/`GF2` siguen exigiendo ganador y la repetición se activa con la misma regla que un cierre normal.
  - No hay ninguna marca de walkover en la clasificación ni en las estadísticas.

- **RF-009.** CUANDO se declare un walkover, EL SISTEMA **no** validará ni servirá sanciones.
  *Criterios de aceptación:*
  - No se ejecuta la comprobación de jugadores suspendidos de la plantilla: el partido no se juega y no hay plantilla que comprobar.
  - No se registra el cumplimiento de ninguna suspensión: un partido no disputado no cumple sanción.
  - No se crea ninguna suspensión nueva, porque no hay eventos.

- **RF-010.** MIENTRAS un partido esté confirmado, EL SISTEMA no permitirá declarar un walkover, cambiarlo ni revertirlo.
  *Criterios de aceptación:*
  - El segundo intento responde **409** y no escribe.
  - La interfaz no ofrece ninguna acción de anulación.
  - La reversión queda fuera de alcance: exige la corrección de actas cerradas, que necesita enmienda constitucional y spec propia (spec 017).

- **RF-011.** CUANDO se guarde o se publique la configuración de reglas, EL SISTEMA exigirá que el marcador de walkover tenga un ganador por delante: `winner > loser`.
  *Criterios de aceptación:*
  - Un `winner <= loser` responde **422** al guardar y al publicar, sin guardar ni publicar nada; el mensaje nombra la pareja recibida.
  - La comprobación es de configuración cruzada, como la de `min_players_per_team ≤ max_players_per_team`; **no** cambia `engine_version` ni el esquema de la clave, que ya existe con sus dos enteros ≥ 0.
  - Se aplica en el **límite de configuración** —guardar y publicar— y **no** en el cierre ni en la clasificación, para no revalidar versiones ya publicadas; el caso histórico lo cubre RF-008.
  - Las versiones **ya publicadas** no se revalidan ni se reescriben; el caso histórico se resuelve en el cierre con RF-008.
  - Un marcador con el ganador por delante se acepta con cualquier valor no negativo (por ejemplo 3-1 o 5-0): esta spec no impone una cifra.

- **RF-012.** CUANDO la resolución prevista sea `walkover`, EL SISTEMA adaptará la validación previa del cliente y el formulario de cierre.
  *Criterios de aceptación:*
  - La validación previa **no** exige segmento activo ni planilla completa para `walkover` (hoy los exige para todas las resoluciones y bloquea el botón).
  - El formulario pide **ganador** y **motivo** (selector de catálogo) y muestra el marcador efectivo en solo lectura; no envía los cuatro marcadores.
  - La acción de cerrar está disponible sin segmento activo cuando la resolución prevista es `walkover`.
  - Un cambio a `walkover` **no** se bloquea por segmentos persistidos fuera del máximo de la resolución (el W.O. no valida segmentos y no depende de sus minutos); el aviso por eventos del borrador se conserva.
  - El resto de resoluciones conserva su validación y su formulario sin cambios.
  - Los textos existen en español e inglés y el motivo del rechazo se muestra sin perder lo escrito.

- **RF-013.** EL SISTEMA mantendrá el contrato interno de reglas sin cambios: `engine_version` sigue en **`2026.1`** y no se añade ni retira ninguna clave de `rules_config`.
  *Criterios de aceptación:*
  - `walkover_score` ya existe con su default y su override; esta spec solo valida su contenido.
  - `docs/contrato-reglas.md` no cambia de versión: el marcador de walkover ya está documentado como configuración y queda fuera del contrato cerrado de llaves y formaciones.
  - No se añade ninguna regla de puntuación, desempate, disciplina o sustitución.

## Requisitos no funcionales

- **RNF-001 (aislamiento).** La declaración se ejecuta con el contexto de aislamiento fijado y filtra por organización. Un partido de otra organización responde **404** sin revelar existencia, también con segmentos o configuración de otra organización en el cuerpo.
- **RNF-002 (privacidad).** El motivo es un **código**, no texto libre, y la auditoría guarda el código, el ganador y el marcador; nunca nombres ni documentos. Esta spec no añade ninguna vía de texto libre.
- **RNF-003 (contratos que cambian).** Se declaran y se documentan en el mismo cambio: (a) `limits` añade `walkover_score`; (b) el cierre acepta un walkover **sin** marcadores y sigue aceptándolos con validación; (c) el walkover deja de exigir segmento y plantilla; (d) `reason` pasa de **prohibido** a **obligatorio y de catálogo** en el walkover (un cliente que enviara texto libre recibe **422**); (e) dos `code` aditivos en **409**: `WALKOVER_STATE_NOT_ALLOWED` y `WALKOVER_SCORE_MISMATCH`, más `WALKOVER_CONFIG_INCONSISTENT` en **409**; (f) `walkover_score` con `winner <= loser` pasa de aceptarse a **422**. **Salvedad:** un cliente que ignore los cambios **no** conserva el comportamiento en (d) y (f); el resto de su comportamiento se mantiene.
- **RNF-004 (base de datos).** **Una migración, la 027** (D-6): **relaja** `chk_administrative_resolution_reason` para admitir en `resolution_reason` el código de walkover del catálogo cerrado (o `NULL`), sin columnas nuevas, sin índices, sin reescribir filas y sin tocar `init/01`. La obligatoriedad y el catálogo siguen siendo de la API: la base no puede imponerlos (`CHECK ... IN (...)` acepta `NULL`). Se aplica **antes** del código y no tiene rollback (*forward-fix*).
- **RNF-005 (verificación).** Pasan `cd backend && pytest -q`, `python -m compileall -q app`, las pruebas con base (incluida `tests/test_migration_027.py`) y, en el frontend, `pnpm test`, `pnpm run typecheck` y `pnpm run build`. **El arnés E2E es obligatorio:** `frontend/e2e/` (proyecto `operation-flow`) sí ejercita el acta —apertura de segmento, alta de evento y **cierre**— y esta spec cambia la pantalla de cierre, así que `pnpm run e2e:test` se ejecuta **en exclusiva** (sin `typecheck` ni `build` concurrentes, que comparten `.nuxt`, y limpiando los torneos «Copa E2E» de corridas anteriores). Solo la salida **0** es verde. Lo no ejecutado se declara **no ejecutado**.
- **RNF-006 (determinismo).** La derivación del marcador y del motivo es función de la configuración efectiva y de la petición; no lee el reloj. El orden de los mensajes con varios elementos es estable.
- **RNF-007 (accesibilidad).** El selector de motivo y el ganador se recorren con teclado, tienen etiqueta y asocian su error; el aviso de marcador en solo lectura se anuncia.
- **RNF-008 (rendimiento y bloqueo).** La rama de walkover no consulta plantilla, alineación, contadores ni sanciones y no reescribe la proyección por segmento, pero **respeta el mismo orden de bloqueo que el cierre normal** de la spec 017 (fase → versión → destinos de avance → partido → segmento → jugadores), porque avanza la llave y recalcula la clasificación; solo la **exigencia** de un segmento activo deja de ser necesaria, aunque la fila se sigue bloqueando para cerrarla si existe. Consultar la operación sigue siendo una lectura sin bloqueo.
- **RNF-009 (documentación).** Se actualizan `AGENTS.md` (walkover: estados, autorización, motivo, marcador derivado, efecto y validación de `walkover_score`) y `README.md`; `/docs` refleja el campo y los códigos nuevos. `docs/contrato-reglas.md` no cambia.
- **RNF-010 (auditoría).** No se añade ninguna acción auditada: el walkover usa la acción de cierre existente y su contenido incluye resolución, ganador, marcador y motivo.
- **RNF-011 (tiempo real).** Se emiten los mismos eventos de outbox que un cierre normal (`MATCH_CLOSED`, `MATCH_UPDATED`, `STANDINGS_UPDATED`); no se añade ninguno.

## Datos personales y privacidad

- **No se introducen datos personales.** El W.O. no toca plantilla, alineación ni jugadores: no lee ni escribe datos de personas.
- **El motivo es un código**, no texto libre, así que no puede transportar datos personales a la auditoría.
- **Visibilidad:** el resultado y la clasificación se ven como hoy y no llevan ninguna marca de W.O. que revele más de lo que ya revela el marcador.
- **Fotos y consentimiento:** no aplica.
- **Auditoría:** guarda resolución, ganador, marcador y motivo; nunca nombres ni documentos.

## Casos límite

1. **Walkover sin ningún segmento:** se acepta y el partido queda terminado y confirmado.
2. **Walkover con el equipo ausente sin plantilla:** se acepta; no se exige plantilla.
3. **Walkover con un segmento activo:** se cierra en su minuto de inicio; el partido no queda con segmentos activos.
4. **Walkover con segmentos completados o interrumpidos:** no cambian y la proyección por equipo no se reescribe.
5. **Walkover con eventos en el borrador:** **422**; no se cierra.
6. **Walkover sin marcadores:** el servidor aplica los de la configuración efectiva.
7. **Walkover con marcador informado distinto del configurado:** **409** `WALKOVER_SCORE_MISMATCH`.
8. **Walkover con override de fase:** el marcador sale de la excepción de la fase, no del valor por defecto.
9. **Walkover sin motivo o con un motivo fuera del catálogo:** **422**, sin escribir; no hay texto libre ni «otra».
10. **Walkover sobre un partido `suspended`:** **409** `WALKOVER_STATE_NOT_ALLOWED`.
11. **Walkover sobre un partido `finished`, `cancelled` o `administrative_resolution`:** **409**, sin escritura.
12. **Walkover sobre un partido ya confirmado:** **409**, sin reversión.
13. **Walkover de una llave `GF1`:** exige ganador y activa la repetición con la misma regla que un cierre normal.
14. **Walkover de un partido con jugadores suspendidos en la plantilla:** se declara; no se valida ni se sirve ninguna suspensión.
15. **Dos walkovers simultáneos sobre el mismo partido:** el segundo espera el bloqueo del partido, lo encuentra confirmado y responde **409** sin escribir.
16. **Walkover concurrente con la creación de un segmento:** la que llegue después ve el estado resultante; si el partido ya está terminado, la creación de segmento responde **409** y si el segmento se creó antes, el walkover lo cierra en su minuto de inicio.
17. **Walkover concurrente con una interrupción:** la interrupción posterior encuentra el partido terminado y responde **409**; la anterior deja el segmento interrumpido y el walkover no lo toca.
18. **Marcador configurado 0-3 (ganador por detrás):** al guardar o publicar es **422**; en una versión ya publicada, el cierre responde **409** `WALKOVER_CONFIG_INCONSISTENT` y se documenta la vía administrativa.
19. **Marcador 3-1:** válido; se aplica tal cual al resultado y a la diferencia.
20. **Configuración histórica sin las claves nuevas:** `walkover_score` ya existía y su default es 3-0; no se reescribe.
21. **Árbitro con el permiso y sin asignación al partido:** **403**.
22. **Observador asignado como oficial:** **403** por falta del permiso.
23. **Operador con el permiso y sin asignación:** declara el W.O.
24. **Partido de otra organización:** **404**.
25. **Cliente antiguo que declara un walkover con marcadores 3-0 y sin motivo:** **422** por el motivo; el comportamiento cambia de forma declarada.
26. **Recarga tras declarar:** el partido se muestra en solo lectura, sin acción de anulación.

## Fuera de alcance

- **Corrección, reapertura o anulación de un W.O. confirmado.** Exige la corrección de actas cerradas, que necesita **enmienda constitucional** (§5.2, cambio propio) y spec propia; el principio 3 es innegociable.
- **Sanciones, multas o efectos disciplinarios derivados del W.O.**: el motivo es descriptivo y no deriva nada.
- **Marcadores de W.O. distintos del configurado** y cualquier regla nueva de puntuación por incomparecencia.
- **Cambiar el efecto vigente en la clasificación** (los goles del W.O. cuentan para la diferencia): se conserva tal cual.
- **Añadir o cambiar transiciones de estado del partido** (`live`, `suspended`).
- **Revalidar versiones publicadas** con `winner <= loser` o reescribir su configuración.
- **El cierre normal, su orden de validaciones y la inmutabilidad del acta:** spec 017.
- **El catálogo de eventos y la asistencia:** spec 015.
- **Notificaciones, correo o webhooks por un W.O.**
- **Administración de plataforma** y cualquier vía global sobre resultados.

## Criterios de finalización

| # | Criterio de finalización | RF |
|---|---|---|
| 1 | Un W.O. se declara solo con resolución `walkover`, ganador participante, versión publicada y un estado que hoy admite cierre; `finished`, `cancelled`, `administrative_resolution` y `suspended` responden **409** `WALKOVER_STATE_NOT_ALLOWED`. | RF-001 |
| 2 | La autorización es la **conjunción** real: permiso **y** (rol operativo **o** asignación como oficial); el árbitro no asignado y el observador asignado reciben **403**; no hay permisos ni roles nuevos. | RF-002 |
| 3 | Un partido sin segmentos y con un equipo sin plantilla se declara como W.O.; la apertura y el control de tamaño no se ejecutan. | RF-003 |
| 4 | Con segmentos, el activo se cierra en su minuto de inicio, los demás no cambian y `match_segment_team_state` no se reescribe; ningún partido terminal conserva un segmento activo. | RF-004 |
| 5 | El marcador se deriva de la configuración efectiva, se publica en `limits` y se aplica sin que el cliente lo envíe; un marcador distinto informado responde **409** `WALKOVER_SCORE_MISMATCH`. | RF-005 |
| 6 | Un walkover con eventos responde **422** y no escribe. | RF-006 |
| 7 | El motivo es obligatorio y de catálogo cerrado (`no_show`, `withdrawal`, `insufficient_players`, `sanction`), se guarda como código en `resolution_reason` y en la auditoría existente, y no deriva ningún efecto. | RF-007 |
| 8 | El partido queda terminado y confirmado, cuenta como jugado con sus puntos y sus goles en la diferencia, avanza la llave y no genera tarjetas, sanciones ni fair play; el ganador declarado es el que recibe la victoria o el cierre responde **409** `WALKOVER_CONFIG_INCONSISTENT`. | RF-008 |
| 9 | No se valida ni se sirve ninguna suspensión y no se crea ninguna. | RF-009 |
| 10 | Un partido confirmado no admite un segundo W.O., cambio ni reversión, y la interfaz no ofrece ninguna vía de cambio. | RF-010 |
| 11 | Guardar o publicar `walkover_score` con `winner <= loser` responde **422** sin guardar nada; `winner > loser` se acepta con cualquier cifra no negativa; las versiones ya publicadas no se revalidan. | RF-011 |
| 12 | Con la resolución prevista `walkover`, la validación previa del cliente y el botón no exigen segmento activo ni planilla; el formulario pide ganador y motivo, muestra el marcador en solo lectura y no envía marcadores; el resto de resoluciones no cambia. | RF-012 |
| 13 | `engine_version` sigue en **2026.1**, `docs/contrato-reglas.md` no cambia y no se añade ni retira ninguna clave de `rules_config`. | RF-013 |
| 14 | El aislamiento se mantiene: un partido de otra organización responde **404** y el miembro sin rol **403**. | RNF-001 |
| 15 | Ningún mensaje ni registro nuevo contiene datos personales; el motivo es un código. | RNF-002 |
| 16 | Pasan `cd backend && pytest -q`, `python -m compileall -q app`, las pruebas con base, `pnpm test`, `pnpm run typecheck`, `pnpm run build` y el **E2E en exclusiva** (`pnpm run e2e:test` con salida **0**); lo no ejecutado se declara **no ejecutado**. | RNF-005 |
| 17 | La derivación es determinista (sin reloj) y el orden de los mensajes con varios elementos es estable. | RNF-006 |
| 18 | El selector de motivo y el ganador se recorren con teclado, tienen etiqueta y asocian su error. | RNF-007 |
| 19 | La rama de walkover no consulta plantilla, alineación, contadores ni sanciones y no reescribe la proyección por segmento; su diferencia de bloqueo está justificada en el plan. | RNF-008 |
| 20 | La **migración 027** relaja `chk_administrative_resolution_reason` para admitir el código de walkover (o `NULL`) sin reescribir datos, y se aplica antes del código; no hay acción auditada nueva ni evento de outbox nuevo. | RNF-004, RNF-010, RNF-011 |
| 21 | `AGENTS.md` y `README.md` describen estados, autorización, motivo, marcador derivado, efecto y validación de `walkover_score`. | RNF-009 |

## Dudas abiertas

**Sin dudas abiertas.** DU-5 (corregida), DU-6, DU-7, D-3 y D-5 están cerradas en «Decisiones cerradas» y aplicadas. **D-6** (corrección verificada el 2026-10-25) sustituye la afirmación «sin migración» por la migración 027. La spec queda **aprobada** el 2026-10-25; el plan y las tareas están en `plan.md` y `tasks.md` de esta misma carpeta.

## Apéndice — Referencias de inspección

Referencias comprobadas de nuevo el 2026-10-25, **después** de la 017 (que reescribió el cierre en 14 pasos).

- Resolución y motivo: `backend/app/modules/matches/schemas.py:144-206` (`CloseMatchReportDTO`); `matches/errors.py:24-99` (códigos de dominio); `infra/postgres/init/01_schema.sql:416-424` y `migrations/009_photo_resolution_and_outbox_hardening.sql:26-45` (restricción del motivo).
- Marcador: `rules_engine/engine.py:127-168` (esquema de `walkover_score`), `:361-385` (walkover y administrativa), `rules_engine/defaults.py:23, 54`; `rules_engine/schemas.py:31-41` (límite de guardado).
- Cierre: `matches/service.py:556-839` (los 14 pasos y las escrituras), `:588-607` (permisos), `:610-617` (estado, versión, equipos), `:622-641` (bloqueo del segmento activo, plantilla y minutos), `:651-664` (pasos 6 y 7), `:666-696` (pasos 8-12), `:698-723` (paso 13), `:725-831` (paso 14: escritura, clasificación, avance, auditoría y outbox), `:762-780` (cierre del segmento), `:906-920` (`_validate_rosters`), `:995`, `:1039`, `:1083`, `:1200` (exenciones de walkover ya existentes), `:1239-1462` (sanciones).
- Autorización: `backend/app/core/permissions.py:7-75`.
- Clasificación: `backend/app/modules/standings/service.py:30-198` (recalcula y valida reglas).
- Operación: `backend/app/modules/matches/router.py:88-143` (carga del partido), `:102` (configuración de la versión), `:352-377` (`limits`), `:448-472` (cierre), `:475-642` (`GET /operation` y `next_segment`).
- Publicación y clonado de reglas: `backend/app/modules/tournaments/router.py:4287-4294` (publicar valida), `:594-599` (clonar normaliza sin capturar `ValueError`).
- Frontend: `frontend/app/pages/workspace/matches/[id].vue:762-804` (validación previa), `:1329-1394` (cuerpo del cierre), `:1815-1831` (formulario y botón), `frontend/app/utils/matchResolution.ts` (resolución prevista y clasificador de `code`).
- Inmutabilidad: `infra/postgres/migrations/016_confirmed_match_result_immutability.sql`.
- Arneses de prueba reutilizables: `backend/tests/test_close_validation_order.py` (dobles y matriz de precedencia), `backend/tests/test_match_resolution_db.py` (base real por prueba), `backend/tests/test_migration_026.py` (patrón de migración opt-in), `frontend/e2e/operationFlow.ts` (cierre del acta, `report-closed`).
