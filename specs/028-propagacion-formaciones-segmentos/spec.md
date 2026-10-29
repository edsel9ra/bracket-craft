# Spec 028 — Propagación de formaciones entre segmentos

Estado: borrador

## Contexto y objetivo

En la operación de un partido (`/workspace/matches/{id}`), la sección «Define quién juega» configura la formación táctica y las posiciones de los titulares **por segmento y por equipo**. Hoy, al crear un segmento posterior al primero, esa sección queda vacía porque `match_team_lineups` y `match_lineup_snapshots` solo existen para el segmento en el que se guardaron. El operador tiene que reconfigurar la formación y reasignar posiciones en cada segmento, aunque lo habitual es que el once y la formación sean los mismos hasta que se sustituye a alguien.

El objetivo es que, al abrir o crear un segmento que aún no tenga formación persistida, la sección «Define quién juega» se **precargue** con la formación y las posiciones del primer segmento (por equipo) como punto de partida **editable**, sin hacerlas compartidas ni únicas al partido: cada segmento conserva su propia copia una vez guardada.

La precarga es **solo en memoria** (estado del editor) y **no** afecta al borrador local del partido ni a ninguna fila persistida hasta que el operador guarde. No añade llamadas a la API ni altera el contrato.

## Usuarios

- Operador de partido (rol `operator` o miembro con permiso `CLOSE_MATCH_REPORT` asignado al partido).
- Administrador y dueño de la organización, que también operan.

## Roles y visibilidad

- `viewer`: no puede operar; la pantalla se muestra en solo lectura. No aplica a esta spec (no cambia permisos).
- Operador/admin/dueño: ven y editan la formación del segmento seleccionado; guardan con «Guardar planilla».
- Público: no se expone ninguna formación nueva; las formaciones ya publicadas por segmento siguen rigiendo (spec 021). No aplica cambio.

## Historias de usuario

- HU-1. Como operador, quiero que al crear un segundo segmento la sección «Define quién juega» aparezca ya con la formación y las posiciones del primer segmento, para no reconfigurarlas desde cero.
- HU-2. Como operador, quiero poder modificar la formación o las posiciones del nuevo segmento y guardarlas como su propia planilla, sin que el cambio afecte al primer segmento ni a los ya guardados.
- HU-3. Como operador, quiero que, si el primer segmento no tiene formación guardada, la sección aparezca vacía como hasta ahora.

## Definiciones

- **Fuente de precarga (por equipo)**: para cada equipo (local/visitante), el segmento con el menor `segment_number` que tenga al menos una formación táctica persistida para **ese equipo** (`match_team_lineups` con snapshots para ese `team_id`). La fuente se resuelve **independientemente por equipo**: un segmento puede tener formación para un solo equipo y, en ese caso, solo ese equipo se precarga; el otro queda vacío (o se precarga desde su propia fuente si existe).
- **Primer segmento (global)**: el segmento con el menor `segment_number` que tenga al menos una formación táctica persistida para cualquier equipo. Se usa solo como referencia de existencia de fuente; la precarga real es por equipo.
- **Punto de partida editable**: los valores de formación y posición que se muestran en el editor al abrir el segmento, y que solo se persisten al ejecutar «Guardar planilla» sobre ese segmento. No son una vista compartida ni una referencia viva. Viven únicamente en memoria (estado del editor) y no alteran el borrador local del partido.
- **Formación persistida**: fila en `match_team_lineups` (y sus snapshots en `match_lineup_snapshots`) asociada a un `segment_id` concreto.
- **Segmento con formación parcial**: segmento que tiene `match_team_lineups` para un equipo pero no para el otro, o que tiene la fila de formación pero sin snapshots. Se trata como «sin formación persistida para ese equipo» a efectos de precarga para ese equipo.

## Requisitos funcionales

- RF-001: CUANDO el operador selecciona un segmento que no tiene formaciones tácticas persistidas para un equipo, EL SISTEMA precarga en el editor, para ese equipo, la formación y las posiciones de la fuente de precarga de ese equipo (si existe).
- RF-002: CUANDO el operador selecciona un segmento que ya tiene formaciones tácticas persistidas para un equipo, EL SISTEMA carga esas formaciones (comportamiento actual), sin usar ninguna otra como fuente para ese equipo.
- RF-003: CUANDO el operador crea un segmento nuevo, EL SISTEMA selecciona automáticamente ese segmento (siguiendo la lógica actual de `applyOperation`: segmento activo si existe, en otro caso el último) y precarga la formación y las posiciones de la fuente de precarga (si existe), de modo que la sección «Define quién juega» no quede vacía.
- RF-004: MIENTRAS el segmento seleccionado no tenga planilla guardada, la precarga es un valor de partida del editor únicamente: EL SISTEMA no crea ni modifica filas en `match_team_lineups`, `match_lineup_snapshots` ni `match_rosters` hasta que el operador guarde.
- RF-005: CUANDO el operador guarda la planilla de un segmento precargado, EL SISTEMA persiste la formación y las posiciones en ese segmento, y las de la fuente (y de cualquier otro) permanecen sin cambios.
- RF-006: SI la fuente de precarga no existe para un equipo, ENTONCES EL SISTEMA no precarga nada para ese equipo y la sección aparece vacía para él (comportamiento actual).
- RF-007: EL SISTEMA mantiene la independencia por segmento: publicar/despublicar una formación (spec 021) sigue operando solo sobre el segmento seleccionado y no se propaga a otros.
- RF-008: CUANDO el operador cambia de segmento seleccionado, EL SISTEMA recarga el editor con la formación del segmento recién seleccionado (persistida o precargada desde la fuente), descartando las ediciones no guardadas del segmento anterior (comportamiento actual de descarte: `applyOperation` sobrescribe `lineupRoles`, `lineupFormations` y `lineupPositions` vía `syncTacticalEditor`).
- RF-009: EL SISTEMA asume que `tactical_lineups` de la respuesta de operación incluye **todos** los segmentos del partido (dependencia explícita; no se añade filtrado por segmento en el cliente).
- RF-010: CUANDO el segmento seleccionado pasa a tener formación persistida (por ejemplo, tras una recarga que la incluye) y el editor estaba precargado sin guardar, EL SISTEMA carga la formación persistida (RF-002 prevalece sobre la precarga).
- RF-011: SI la fuente cambia entre la precarga y el guardado (otro operador guardó una formación en un segmento anterior), EL SISTEMA no recarga automáticamente mientras el editor está abierto; la precarga inicial sigue vigente hasta guardar o recargar manualmente/socket.
- RF-012: EN partido en estado terminal (`finished`, `cancelled`, `administrative_resolution`, `suspended`) o en versión no publicada, EL SISTEMA omite la precarga (pantalla en solo lectura / sin operación) y se comporta como hoy.
- RF-013: EN versión en borrador, EL SISTEMA aplica la misma regla de precarga que en versión publicada (no hay distinción).
- RF-014: CUANDO la fuente incluye jugadores retirados lógicamente (`is_active = false` en el roster), EL SISTEMA precarga sus snapshots igualmente (la formación persistida ya los contiene); la visibilidad pública sigue sus reglas propias (spec 022).

## Requisitos no funcionales

- RNF-001: No se añade ningún endpoint, migración, tabla ni columna. La precarga es un comportamiento del cliente sobre los datos ya devueltos por `GET /matches/{id}/operation`.
- RNF-002: No se altera el contrato de `GET /matches/{id}/operation` ni de `PUT /matches/{id}/lineup`: los campos, códigos y permisos permanecen idénticos.
- RNF-003: La precarga no debe introducir consultas adicionales al servidor; se deriva de `tactical_lineups` ya presentes en la respuesta de operación.
- RNF-004: `pnpm test`, `pnpm run typecheck` y `pnpm run build` deben pasar. La lógica de derivación de la fuente se extrae a una función pura en `frontend/app/utils/` (p. ej. `deriveLineupSource`) con pruebas unitarias en `frontend/tests/`.
- RNF-005: La precarga no añade llamadas a la API ni altera la matriz de acceso de la spec 020: no cambia permisos, endpoints ni campos; solo reorganiza datos ya disponibles para el operador autenticado.

## Datos personales y privacidad

No aplica: no se exponen ni modifican datos personales; las formaciones y posiciones ya son datos operativos del partido y siguen las reglas de publicación de la spec 021.

## Casos límite

- CL-001: Primer segmento con formación publicada y un segundo segmento creado después: el segundo se precarga con la formación y las posiciones del primero, pero su estado de publicación es «privada» hasta que el operador guarde y publique.
- CL-002: Varios segmentos, todos sin formación: ninguno se precarga; todos aparecen vacíos.
- CL-003: El operador edita la formación precargada en el segundo segmento pero no guarda y cambia al tercer segmento: las ediciones se descartan y el tercero se precarga desde la fuente.
- CL-004: El operador guarda una planilla distinta en el segundo segmento: el primero no se modifica; al volver al segundo se carga su propia planilla.
- CL-005: Partido con un único segmento: no hay precarga (es el propio primer segmento) y el comportamiento no cambia.
- CL-006: Actualización en tiempo real (socket) que recarga la operación mientras el operador edita un segmento precargado no guardado: el editor se recarga desde el servidor (fuente), descartando ediciones no guardadas, igual que hoy.
- CL-007: Segmento con formación para un solo equipo: ese equipo se precarga desde la fuente; el otro queda vacío (o se precarga desde su propia fuente si existe).
- CL-008: Fuente con `match_team_lineups` pero sin snapshots (`match_lineup_snapshots` vacío): se precarga solo el `formation_code`; las posiciones y roles quedan vacíos (sin snapshots no hay asignación de jugadores).
- CL-009: Fuente posterior al segmento seleccionado (el segmento seleccionado es posterior en número al que tiene formación): se precarga desde ese segmento anterior (la fuente es el de menor número con formación para ese equipo).
- CL-010: Recarga por socket mientras el editor está precargado y no editado: la precarga se recalcula desde la fuente actualizada; si la fuente cambió, el editor refleja la nueva fuente.
- CL-011: Jugador retirado lógicamente presente en los snapshots de la fuente: se precarga su posición/rol igual que el resto; no se filtra.
- CL-012: Segmento seleccionado que pasa a tener formación persistida tras una recarga (otro operador la guardó): se carga la persistida, no la precarga.

## Fuera de alcance

- Compartir una única formación global al partido o sincronizar automáticamente los segmentos futuros con cambios del primero.
- Copiar sustituciones, eventos o marcadores entre segmentos.
- Persistir automáticamente la precarga sin acción del operador.
- Cambios de backend, esquema o endpoints.
- Formaciones en el catálogo público o en las estadísticas (spec 022).

## Criterios de finalización

- Al crear un segundo segmento en un partido cuyo primer segmento tiene formación, la sección «Define quién juega» muestra esa formación y esas posiciones sin acción adicional.
- Guardar la planilla del segundo segmento persiste solo en ese segmento; el primero queda intacto.
- Un segmento sin formación persistida y sin fuente de precarga aparece vacío.
- La publicación/despublicación de una formación opera solo sobre el segmento seleccionado y no se propaga a otros (verificable: publicar en el segundo no cambia el estado de publicación del primero).
- La precarga es independiente por equipo: un segmento con formación solo para un equipo precarga únicamente ese equipo.
- La precarga no copia el estado de publicación: un segmento precargado desde una formación publicada aparece como privado hasta guardar y publicar.
- `cd frontend && pnpm test && pnpm run typecheck && pnpm run build` pasan, incluyendo pruebas unitarias de la función de derivación de la fuente.

## Campos copiados y excluidos (precarga)

La precarga copia, **por equipo**, desde la fuente:

- `formation_code` (de `match_team_lineups`).
- Para cada snapshot de `match_lineup_snapshots`: `player_id` → se resuelve a `roster_id` vía `rosters` del partido; `position_slot`; `is_starter` → rol `starter`/`substitute`.

Se excluyen explícitamente:

- `is_public` y `published_at` (estado de publicación): el segmento precargado nace privado.
- `segment_id`, `id`, `created_at`/`updated_at` (identificadores y marcas de la fuente).
- `segment_number` (pertenece al segmento destino).

Jugadores del roster del equipo que no figuren en los snapshots de la fuente se inicializan con rol vacío (`''`) y sin posición (no se copia ningún rol).

## Fuente de derivación (testeable)

La derivación de la fuente se implementa como función pura en `frontend/app/utils/` (nombre sugerido: `deriveLineupSource`), que recibe `tactical_lineups`, `rosters` y el `segment_id` seleccionado, y devuelve, por equipo, la formación y las asignaciones de posición/rol a precargar (o `null` si no hay fuente). Es pura (sin reloj, red ni almacenamiento) y tiene pruebas unitarias en `frontend/tests/`. La pantalla la consume en `syncTacticalEditor` (o equivalente) sin añadir consultas.