# Spec 007 — Reglas declaradas y constantes de partido (R09/R10)

Estado: Implementada, validada por @reviewer y cerrada (2026-10-21). CI en main en verde (PR #2).

> **Bloque D del P1** de `docs/auditoria-2026-10-19.md`: R09 (reglas declaradas no aplicadas) y R10 (constantes hardcodeadas). **Revisión 2026-10-20: Q1 y Q3 quedan revocadas.** Las sustituciones son necesarias en la operación, así que se **implementan por completo** y `match_segment_team_state` se **implementa** en vez de retirarse. Se mantienen el retiro de transferencias, `roster_lock_matchday`, la enmienda constitucional §3.2 → 1.3.0, los minutos desde `rules_config`, el contrato interno de `GF1`/`GF2` y formaciones, y la migración **021** (ahora **añade columnas**, no elimina la tabla). R11, R12 (spec 006) y R18-R32 quedan fuera.

## Decisiones cerradas (2026-10-20)

- **Q1 (revocada) = Implementación operativa completa de sustituciones.** Configuración `substitutions` activa; eventos de salida/entrada; validación del acta; contadores por segmento/equipo; UI del acta. No hay banquillo sustituto ni límites «informativos».
- **Q2 = B · Transferencias: se retiran; `roster_lock_matchday` se aplica.** **No existe tabla `transfers`**, así que no hay nada que eliminar en el esquema. La 021 no toca transferencias.
- **Q3 (revocada) = `match_segment_team_state` se implementa.** Contadores `substitutions_remaining`/`substitution_windows_remaining` por segmento/equipo, inicializados desde `rules_config` y actualizados al registrar o anular sustituciones. La 021 **no la elimina**.
- **Q4 = A · Minutos derivados de `rules_config`** con defaults 90/120, validación y compatibilidad de lectura.
- **Q5 = A · `GF1`/`GF2` y formaciones: contrato interno** documentado y probado; el *bracket reset* es lógica del formato.
- **Q6 = A · Jornada de referencia de `roster_lock_matchday`:** `matchday` de la primera fase por `stage_order` de la **versión publicada**; bloqueo cuando todos los partidos de esa jornada están confirmados; `cancelled` fuera del conjunto.
- **Enmienda constitucional (decisión del usuario).** §3.2 → **1.3.0** para retirar «transferencias» de las reglas configurables y nombrar «sustituciones» y «ventana de inscripción». La tramita el implementador como cambio propio; esta spec no edita `docs/constitution.md`.

## Enmienda constitucional previa (§3.2 → 1.3.0)

**Conflicto reconocido.** El §3.2 vigente exige que las reglas deportivas configurables (puntuación, desempates, disciplina, **transferencias**) se expresen como configuración JSON. Esta spec retira `transfers` porque el producto no tiene operación de transferencia ni consumidor. Sin la enmienda, el cambio incumple §3.2; **no se declara cumplimiento** hasta que esté mergeada. Se tramita conforme a la **§5.2**: cambio propio, aprobado, no mezclado con el funcional, con motivo, reglas e impacto, e historial en §7.

**Texto exacto a aplicar en `docs/constitution.md`** (lo aplica el implementador). El cambio de enmienda **solo toca `docs/constitution.md`**; las actualizaciones de `README.md` y `AGENTS.md` van en el cambio **funcional** (criterio 6).

1. Cabecera: `**Versión:** 1.2.0` → `**Versión:** 1.3.0` y `**Última actualización:** 2026-10-19` → `**Última actualización:** 2026-10-20`.
2. Sustituir la viñeta de §3.2:

   - Antes: `- Las reglas deportivas configurables (puntuación, desempates, disciplina, transferencias) se expresan como configuración JSON de la versión del torneo, no como constantes en el código.`
   - Después: `- Las reglas deportivas configurables (puntuación, desempates, disciplina, sustituciones, ventana de inscripción) se expresan como configuración JSON de la versión del torneo, no como constantes en el código. Las transferencias no forman parte de la configuración: el producto no soporta traspasos entre equipos.`

3. Añadir al historial (§7) la fila:

   `| 1.3.0 | 2026-10-20 | **Reglas afectadas:** §3.2 (Backend). Retira «transferencias» de la lista de reglas deportivas configurables y añade «sustituciones» y «ventana de inscripción»; declara que las transferencias no son configuración porque el producto no soporta traspasos entre equipos. **Motivo:** R09 de la auditoría del 2026-10-19 y spec 007 (Q1/Q2): `substitutions` pasa a aplicarse y `transfers` no tenía operación que la produjera ni consumidor. **Incremento menor** porque cambia el contenido de una regla de implementación. | Sin impacto de datos: `transfers` desaparece de las configuraciones nuevas; `substitutions` y `roster_lock_matchday` quedan como claves aplicadas. No hay cambio de esquema por esta enmienda. |`

**Orden obligatorio:** la enmienda se mergea **antes** de la primera tarea funcional (RF-006). El cambio funcional no edita la constitución.

## Contexto y objetivo

R09 describe la brecha entre configuración declarada y comportamiento real: `substitutions` se ofrece en el editor y **no se aplica**, `match_segment_team_state` existe y **nunca se escribe**, y `transfers` se declara sin operación. La decisión cambia el enfoque en las sustituciones: no se retiran, se implementan, porque la operación real las necesita (límite por equipo, ventanas y reentrada son reglas del juego, no adornos). R10 sigue siendo el otro frente: minutos y códigos/formaciones.

**Objetivo:** dejar las sustituciones operativas y verificables de punta a punta (evento, estado en campo, límites, contadores, acta y UI), retirar solo lo que no tiene operación (transferencias), derivar los minutos de la configuración y fijar como contrato interno lo que no debe configurarse.

**Estado verificado sobre el árbol de trabajo el 2026-10-20.** Las cifras de línea son evidencia, no diseño.

### R09 — evidencia

1. **Sustituciones: declaradas y no aplicadas.** Default y esquema en `backend/app/modules/rules_engine/defaults.py:12` y `rules_engine/engine.py:53-62`; editor en `frontend/app/components/RulesEditor.vue:270-277` (espejo `frontend/app/utils/rulesConfig.ts:138, 270-275`). Consumo: **cero**; `compute_match_outcome` solo cuenta goles (`engine.py:248-251`), `evaluate_suspensions` solo tarjetas (`engine.py:290-321`) y el cierre persiste eventos sin contarlos (`matches/service.py:490-513`).
2. **El evento no puede expresar una sustitución.** `MatchEventPayload` exige `player_id` (`matches/schemas.py:30-31, 46-47`) y no tiene jugador que sale/entra; `metadata` es libre (`schemas.py:35`). `entered_minute`/`left_minute` los envía el cliente en la planilla (`schemas.py:150-151`).
3. **La planilla es del partido, no del segmento.** `match_rosters` guarda `role`, `entered_minute`, `left_minute` y `was_ejected` con `uq_match_player (match_id, player_id)` (`init/01:511-532`); `match_lineup_snapshots` sí es por segmento (`init/01:533-546`). La planilla **no puede modificarse después del primer evento** (`matches/router.py:509-511`) y solo se guarda en el segmento activo (`router.py:497-499`). Por eso el estado en campo debe derivarse de la planilla inicial + eventos, no de snapshots por segmento.
4. **`was_ejected` nunca se escribe** (`init/01:524, 541`; sin escrituras en la aplicación). La única evidencia de expulsión son los eventos `red_card`, ya validados en el cierre (`matches/schemas.py:53-58`).
5. **`match_segment_team_state` nunca se escribe.** Columnas `substitutions_remaining` y `substitution_windows_remaining` con `CHECK >= 0` y `UNIQUE (segment_id, team_id)` (`init/01:549-562`); RLS `ENABLE`/`FORCE` (`init/01:1153,1183`; `migrations/011:24`); política genérica y grants completos (`init/01:1201, 1226`). El único acceso es un `EXISTS` en la guarda de regeneración (`tournaments/router.py:2215`), junto a `match_officials`, `match_segments`, `match_rosters`, `match_lineup_snapshots`, `match_events` y suspensiones (`router.py:2170-2252`).
6. **No hay API de eventos individuales ni de anulación, y un acta confirmada es inmutable.** El único escritor de `match_events` es el cierre (`service.py:492`). El trigger `trg_validate_match_event_context` (`migrations/009_photo_resolution_and_outbox_hardening.sql:228-231`) rechaza **INSERT y UPDATE** de eventos cuando el partido está en `finished`, `cancelled` o `administrative_resolution` (`009:180-182`), y un partido cerrado no admite re-cierre (`matches/service.py:58-59`). Por tanto `is_voided`, `voided_at`, `voided_by_member_id` y `void_reason` (`init/01:579-582`) son **legado sin vía operativa**: se leen en disciplina y clasificación (`service.py:529`, `standings/service.py:104`) pero ningún camino los escribe. Registrar = componer el acta; el servidor valida al cerrar y, una vez confirmada, no se corrige en esta spec.
7. **Transferencias sin operación ni consumidor.** `transfers` en `defaults.py:20-24`, `engine.py:88-100` y `RulesEditor.vue:295-298`; no hay tabla `transfers` ni endpoint de traspaso o baja: `rosters` solo se crea (`router.py:1668-1676`), se importa (`1796`) y se actualiza para foto y consentimiento (`1934, 2026`).
8. **Documentación que promete de más:** `README.md:263`, `AGENTS.md:52` y `AGENTS.md:349` mencionan transferencias configurables.

### R10 — evidencia

1. **Minutos como constantes.** `REGULAR_TIME_MINUTE = 90` y `EXTRA_TIME_MINUTE = 120` (`matches/service.py:18-19`) topan segmentos (`service.py:321-325`) y eventos (`service.py:350-351`) y separan goles reglamentarios de prórroga (`service.py:374`). El tope de la petición es otro: `minute ≤ 180` (`matches/schemas.py:32`) y `added_minute ≤ 30` (`schemas.py:33`); el frontend replica 180 (`frontend/app/pages/workspace/matches/[id].vue:376, 1052`). Las flags de resolución se validan en `rules_engine/engine.py:217-221`.
2. **Segmentos e interrupciones sin máximo.** `POST /segments` solo exige monotonía (`matches/router.py:301-377`) e `interrupt` solo que el minuto no sea anterior al inicio (`router.py:378-430`).
3. **`GF1`/`GF2` como cadenas mágicas:** generados en `tournaments/scheduling.py:725, 738`, consumidos en `matches/service.py:110` y `advancement/service.py:37, 46, 116, 127`.
4. **Formaciones duplicadas en cinco lugares:** `matches/schemas.py:18`, `matches/formations.py:4-57`, `migrations/007_tactical_lineups.sql:8-10`, `matches/router.py:554-566` y `frontend/app/constants/formations.ts:1-27`.
5. **Cadena de volumen limpio:** `init/00_roles.sh` → `01_schema.sql` → `02_public_projections.sql` → `03_hardening.sql` → migraciones 001-021.

## Alcance

1. Enmienda constitucional §3.2 → 1.3.0 como cambio propio previo.
2. **Sustituciones operativas:** configuración aplicada, contrato de evento, estado en campo, límites y ventanas, reentrada, contadores por segmento/equipo, validación del acta y UI.
3. Migración **021** aditiva: columnas `player_out_id`/`player_in_id` en `match_events`, FKs y `CHECK` coherente, con pre-chequeos y compatibilidad.
4. Retiro de `transfers` como configuración (no hay tabla) y aplicación de `roster_lock_matchday` en altas.
5. Minutos desde `rules_config` con validación del par efectivo, tope único y segmentos/interrupciones validados.
6. Normalización del frontend a `3.3.0` con promoción del valor heredado al cargar.
7. Contrato interno documentado y probado de `GF1`/`GF2` y formaciones.

## No objetivos

- R11 (ciclo de vida `live`/`suspended`, eventos en vivo por Socket.IO), R12 (spec 006), R13/R14 y R18-R32.
- Transferencias completas (traspaso entre equipos, ventana de fichajes, historial de inscripciones).
- **API de eventos individuales o de anulación**: los eventos de un acta confirmada son inmutables (ver «Nota de alcance») y el registro sigue siendo el acta y el cierre.
- Reglas deportivas nuevas o cambios de puntuación, desempates, disciplina y `walkover_score`.
- Abrir el catálogo de formaciones o configurar el *bracket reset*.
- Reescribir resultados, actas cerradas o `rules_config` publicados.
- Editar `docs/constitution.md` en esta spec (lo hace el cambio de enmienda).
- Añadir dependencias, cambiar versiones de referencia, Compose o `.env.example`.

### Nota de alcance: registro, inmutabilidad y por qué no hay endpoints nuevos

El producto **no tiene** endpoints de eventos individuales ni de anulación, y añadirlos es R11 (eventos de partido por API), fuera de alcance. Por tanto: **registrar** una sustitución significa componerla en el acta y validarla en el cliente con los datos de operación; el servidor valida el conjunto **al cerrar**. **No existe anulación operativa**: `trg_validate_match_event_context` bloquea INSERT/UPDATE de eventos en partidos terminados y el acta no se re-cierra, así que los eventos de un acta confirmada son **inmutables** (§2.3). La columna `is_voided` es legado y no se usa; corregir un acta cerrada exigiría una spec propia de corrección de resultados. Si se requiere registro incremental con API, también será una spec propia.

## Usuarios

- **Administrador de organización (`MANAGE_TOURNAMENTS`):** configura reglas y altas de plantilla.
- **Operador / árbitro (`CLOSE_MATCH_REPORT` u oficial del partido):** registra el acta, incluidas las sustituciones, y ve contadores.
- **Público:** consulta resultados y alineación publicada; no ve el acta en composición ni los contadores.
- **Desarrollador/revisor:** necesita el contrato exacto del evento y del estado en campo.

## Roles y visibilidad

- Configuración: `MANAGE_TOURNAMENTS` en borradores; las publicadas no se editan.
- Acta y sustituciones: quien puede cerrar el partido. Los contadores se ven en la pantalla de operación (sesión + organización).
- Público: sin cambios; las sustituciones no se añaden a las vistas públicas ni a la alineación publicada.
- Aislamiento: toda lectura/escritura con RLS por organización y FKs por contexto.

## Historias de usuario

- HU-1. Como administrador, quiero que el editor solo ofrezca reglas aplicadas.
- HU-2. Como administrador, quiero configurar la duración reglamentaria y la prórroga.
- HU-3. Como administrador, quiero que la ventana de inscripción se respete y que mi valor no se pierda al cargar ni al guardar.
- HU-4. Como operador, quiero registrar una sustitución eligiendo quién sale y quién entra, y ver cuántas me quedan.
- HU-5. Como operador, quiero que el acta rechace una sustitución fuera de regla sin guardar nada a medias.
- HU-6. Como revisor, quiero un contrato explícito de invariantes y una enmienda constitucional trazable.

## Definiciones

- **En campo:** jugadores del equipo que, en un punto del acta, están en el terreno: titulares de la planilla menos los sustituidos/expulsados, más los que entraron y no han vuelto a salir.
- **Banca:** jugadores del equipo en la planilla que no están en campo ni expulsados.
- **Ventana:** grupo de sustituciones del mismo equipo con el mismo `segment_id`, `minute` y `added_minute`. Todas consumen **una** ventana.
- **Saldo:** `substitutions_remaining` y `substitution_windows_remaining` de una fila de `match_segment_team_state`, expresados como lo que queda **del partido** al final de ese segmento.
- **Configuración efectiva:** `rules_config` de la versión del partido con el override de la fase aplicado (`matches/service.py:260-267`).
- **Evento legado:** `substitution` anterior a la 021, sin `player_out_id`/`player_in_id`; es informativo y el motor lo ignora.
- **Bloque deprecado:** bloque aceptado por el esquema e ignorado (`transfers`), que no se escribe en configuraciones nuevas.
- **Promoción:** traslado de `transfers.roster_lock_matchday` a la clave de primer nivel al cargar o guardar, solo si no hay valor de primer nivel.
- **Fuente efectiva (ventana de inscripción):** `rules_config` de la **versión publicada**.
- **Máximo efectivo:** `extra_time_minutes` si la resolución es `extra_time`/`penalties` y la prórroga está habilitada; `regular_time_minutes` en el resto.
- **Tope estructural:** 180 minutos y `added_minute ≤ 30` como límites de forma.
- **Partido confirmado:** `status IN ('finished','administrative_resolution')` y `result_confirmed = TRUE` (`init/01:347, 400-411`).
- **Jornada de referencia:** `matchday` igual a `roster_lock_matchday` en la primera fase por `stage_order` de la versión publicada.
- **Contrato interno:** `GF1`/`GF2` y las cuatro formaciones, publicados en `docs/contrato-reglas.md` con `engine_version` **2026.1**.

## Requisitos funcionales

### Transversales

- **RF-001.** EL SISTEMA declarará como configurables solo reglas aplicadas; `README.md` y `AGENTS.md` describirán sustituciones aplicadas, ventana de inscripción y ausencia de transferencias, y el contrato interno.
- **RF-002.** CUANDO se valide un `rules_config` guardado, EL SISTEMA aceptará `3.2.0` y `3.3.0`, ignorará bloques deprecados, no exigirá `substitutions` (es opcional en el esquema y aplica defaults 5/3/`false` en lectura si falta) y no reescribirá versiones publicadas ni archivadas. **Impacto operativo:** al desplegar, una versión `3.2.0` ya publicada empieza a aplicar sus límites de sustitución; las actas ya cerradas **no se revalidan** y los partidos aún abiertos pueden rechazar sustituciones antes aceptadas. Se documenta en `README.md`/`AGENTS.md` (RF-001).
- **RF-003.** CUANDO se guarde una configuración, EL SISTEMA normalizará a `3.3.0`, escribirá `substitutions` explícito, promoverá `roster_lock_matchday` (RF-021), omitirá `transfers` y materializará los minutos **solo si la pareja efectiva es válida** (RF-041).
- **RF-004.** SI falla una validación en el cierre, en un segmento o en un alta de plantilla, ENTONCES EL SISTEMA rechazará la operación sin escribir eventos, contadores, marcador, clasificación, avance, outbox, filas de plantilla ni filas nuevas de `players`.
- **RF-005.** EL SISTEMA mantendrá una lista probada que clasifique cada clave de primer nivel de `rules_config` como **aplicada** (`points_system`, `ranking_pipeline`, `substitutions`, `discipline`, `stage_defaults`, `stage_overrides`, `roster_lock_matchday`) o **deprecada** (`transfers`).
- **RF-006.** **Enmienda constitucional previa.** EL PROYECTO enmendará §3.2 a 1.3.0 con el texto exacto de esta spec, en un cambio propio aprobado y no mezclado (§5.2), **antes** de la primera tarea de implementación; el cambio funcional no editará la constitución. SI la enmienda no está mergeada, ENTONCES la implementación queda bloqueada y no se declarará cumplimiento.

### R09 — Sustituciones (implementación)

- **RF-010.** CUANDO se cierre un acta, EL SISTEMA aplicará la configuración efectiva de `substitutions` (`max_per_team`, `max_windows`, `allow_reentry`), con defaults 5/3/`false` si faltara. Los límites son **por equipo y por partido**; `max_per_team = 0` deshabilita las sustituciones y `max_windows = 0` no admite ninguna ventana.
- **RF-011.** EL SISTEMA aceptará en el evento `substitution` los campos `player_out_id` y `player_in_id`. SI el evento es `substitution`, ENTONCES ambos serán no nulos, distintos entre sí y `player_id = player_out_id`; SI es de otro tipo, ENTONCES ambos serán nulos. El incumplimiento estructural responde **422** antes del handler (la pertenencia a la plantilla es validación de negocio, RF-013).
- **RF-012.** CUANDO se valide una sustitución, EL SISTEMA determinará el estado en campo de forma determinista: XI inicial = jugadores de `match_rosters` con `role = 'starter'` e `is_valid` del equipo; después aplica las sustituciones y las expulsiones por `red_card` en orden total **`(minute, added_minute, índice del evento en el acta)`**, con el índice del payload como desempate estable. El estado de cada jugador es un **conjunto de intervalos** (unión) `[entrada, salida)` por reentrada, no un intervalo único; `match_rosters.entered_minute`/`left_minute` solo se contrastan cuando el jugador tiene **un único** intervalo (sin reentrada) y, si hay reentrada, prevalecen los intervalos derivados de los eventos. SI el equipo no tiene planilla o no tiene titulares, ENTONCES responderá **409** («no hay planilla para determinar el estado en campo»).
- **RF-013.** SI en una sustitución el equipo no coincide con ambos jugadores, alguno no está en la plantilla del equipo, el saliente no está en campo, el entrante no está en la banca o alguno está expulsado, ENTONCES EL SISTEMA responderá **409** sin escribir nada.
- **RF-014.** SI `allow_reentry = false` y el jugador entrante ya estuvo en campo antes en el partido, ENTONCES EL SISTEMA responderá **409**. SI `allow_reentry = true`, ENTONCES solo se exige que no esté en campo en ese momento y que no esté expulsado. Un jugador expulsado nunca reingresa.
- **RF-015.** EL SISTEMA contará por equipo y partido: (a) sustituciones = eventos `substitution` **con `player_out_id` y `player_in_id`** (los legados no cuentan); (b) ventanas = grupos distintos `(segment_id, minute, added_minute)` de esos eventos. SI se excede `max_per_team` o `max_windows`, ENTONCES responderá **409** nombrando el límite y el saldo, sin escribir nada. Varias sustituciones del mismo equipo en el mismo segmento y minuto (incluido `added_minute`) consumen **una** ventana.
- **RF-016.** EL SISTEMA mantendrá `match_segment_team_state` como proyección persistida: una fila por segmento y equipo participante, con el **saldo del partido** tras ese segmento. Las filas se crean al abrir el segmento (`POST /segments`) para los equipos ya asignados y se aseguran (`ON CONFLICT DO NOTHING`) antes de procesar sustituciones en el cierre. Al cerrar, EL SISTEMA **reescribe todas las filas de todos los segmentos del partido** en orden `match_segments.segment_number` ascendente (nunca por `minute`), de modo que la fila de un segmento anterior refleja el consumo acumulado **hasta ese segmento**; los saldos se recalculan desde los eventos con salida/entrada, nunca se decrementan a ciegas. La pantalla de operación devuelve el estado con la misma función pura cuando la fila no exista, sin escribir en un `GET`.
- **RF-017.** CUANDO se cierre un acta, EL SISTEMA validará el conjunto completo antes de escribir: límites por equipo, ventanas, reentrada y coherencia de contadores. Para cada evento de jugador comprobará que su minuto cae dentro de la **unión de intervalos** en campo del jugador; solo si el jugador tiene un intervalo único se contrasta además con `match_rosters.entered_minute`/`left_minute`, y se rechaza con **409** cualquier contradicción. Todo el acta es atómica.
- **RF-018.** EL SISTEMA mantendrá la idempotencia de `client_event_id`: duplicados dentro del mismo acta → **422**; un evento ya persistido idéntico (incluidos `player_out_id`/`player_in_id`) se reutiliza sin doble conteo; uno con datos distintos → **409** «inmutable». Los eventos de un acta confirmada son **inmutables**: `trg_validate_match_event_context` rechaza INSERT/UPDATE sobre un partido terminado y no hay re-cierre ni endpoint de anulación. La columna `is_voided` es legado y no se usa como vía operativa.
- **RF-019.** CUANDO se abra la pantalla de operación, EL SISTEMA ofrecerá en el acta dos selectores para una sustitución (sale: jugadores en campo; entra: banca), deshabilitará las opciones inválidas a partir del estado que expone el servidor (RF-045), mostrará los contadores por equipo (sustituciones y ventanas restantes) y los errores de límite o reentrada, con textos es/en, sin cambiar el flujo de cierre único. La vista previa de contadores se calcula en el **cliente sobre el borrador del acta**; el valor del servidor (estado confirmado + configuración efectiva) es la **base** y el servidor sigue siendo la autoridad al cerrar.

### R09 — Transferencias (retiro) y `roster_lock_matchday` (aplicación)

- **RF-020.** CUANDO se edite la configuración, EL SISTEMA no ofrecerá `transfers`, no lo incluirá en defaults y no lo escribirá en configuraciones nuevas; los bloques existentes se aceptan como deprecados e ignorados. EL SISTEMA documentará que `same_matchday_participation_allowed` desaparece y que la no participación en dos partidos de la misma jornada es una **restricción de base de datos** (`uq_matchday_player_unique`).
- **RF-021.** EL SISTEMA admitirá `roster_lock_matchday` como clave de **primer nivel**, entero ≥ 1 o nulo, default nulo. CUANDO se guarde una configuración con `transfers.roster_lock_matchday` no nulo y **sin** valor de primer nivel, ENTONCES lo **promoverá** antes de eliminar el bloque; si ambas claves existen, prevalece la de primer nivel y el heredado se descarta sin error. CUANDO se evalúe el bloqueo, EL SISTEMA usará el heredado si falta la clave de primer nivel.
- **RF-022.** EL SISTEMA obtendrá el valor efectivo de `roster_lock_matchday` del `rules_config` de la **versión publicada**. SIN versión publicada no aplicará bloqueo, aunque el borrador tenga la clave; si el borrador cambia el valor y la publicada no, prevalece la publicada.
- **RF-023.** CUANDO se evalúe el bloqueo, EL SISTEMA resolverá la jornada de referencia: (1) versión publicada; (2) primera fase por `stage_order` y `id`; (3) partidos de esa fase con `matchday = roster_lock_matchday` y `status <> 'cancelled'`; (4) bloqueo activo si hay al menos un partido y todos están confirmados. La consulta corre en la transacción, con RLS, en una lectura agregada.

  Contrato de referencia (pseudoconsulta; el plan fija la forma final):

  ```text
  total, confirmados = SELECT count(*),
                              count(*) FILTER (
                                WHERE m.status IN ('finished','administrative_resolution')
                                  AND m.result_confirmed = TRUE)
                       FROM matches m
                       JOIN stages s ON s.id = m.stage_id
                                    AND s.tournament_version_id = m.tournament_version_id
                                    AND s.organization_id = m.organization_id
                       WHERE m.organization_id = :organization_id
                         AND m.tournament_id = :tournament_id
                         AND m.tournament_version_id = :published_version_id
                         AND s.id = (primer stage_id por stage_order, luego id)
                         AND m.matchday = :roster_lock_matchday
                         AND m.status <> 'cancelled'
  bloqueado = (total > 0 AND confirmados = total)
  ```

- **RF-024.** CUANDO se cree una inscripción individual o se importe una plantilla con el bloqueo activo, EL SISTEMA responderá **409** con «La plantilla está cerrada desde la jornada {N}: no se pueden inscribir jugadores nuevos», **sin escribir filas** (`rosters` ni `players`) **ni subir objetos**. No se aplica a foto, consentimiento, listar ni leer.
- **RF-025.** CUANDO se importe una plantilla, EL SISTEMA comprobará el bloqueo **dos veces**: antes de subir fotos y dentro de la transacción de escritura. SI se activa entre ambas, ENTONCES responderá **409**, no escribirá filas y compensará las fotos subidas. Como máximo dos comprobaciones por importación.
- **RF-026.** EL SISTEMA no borrará ni invalidará inscripciones existentes al aplicar el bloqueo, y no reabrirá ni alterará versiones publicadas.
- **RF-027.** SIN versión publicada, con la versión de referencia ya no `published`, sin fases, sin partidos con la jornada de referencia o con todos `cancelled`, EL SISTEMA no aplicará bloqueo.
- **RF-028.** EL SISTEMA evaluará el bloqueo con el estado confirmado y sin locks nuevos; la carrera entre un alta y el cierre que lo activa queda como riesgo residual documentado.
- **RF-029.** CUANDO se edite la configuración, EL SISTEMA ofrecerá `roster_lock_matchday` en una sección propia de inscripción (no en Transferencias), vacío = nulo, mínimo 1, textos es/en, enviado en `3.3.0` y reflejando el valor promovido.

### Esquema y migración 021

- **RF-030.** La migración **021** añadirá `player_out_id` y `player_in_id` a `match_events`, ambas `UUID` **nulas**, con **FKs compuestas** `(player_out_id, organization_id)` y `(player_in_id, organization_id)` a `players (id, organization_id) ON DELETE RESTRICT`, como la 015 (`uq_player_organization_context` y `fk_match_events_player_organization`), sin eliminar `match_segment_team_state` ni tocar `transfers` (no existe como tabla). Todo cambio de esquema va en esa migración; no se editan 019 ni 020.
- **RF-031.** La 021 añadirá el `CHECK` exacto del contrato de RF-011 **como `NOT VALID`**, que se evalúa en **INSERT y UPDATE** de filas nuevas o modificadas. Los eventos `substitution` legados quedan tolerados solo porque **no se vuelven a escribir**: `trg_validate_match_event_context` rechaza INSERT/UPDATE de eventos en partidos terminados, de modo que son inmutables en la práctica; **no se promete tolerancia en escritura** para ellos y `VALIDATE CONSTRAINT` queda fuera de esta spec. La expresión será equivalente a:

  ```sql
  CHECK (
      (event_type = 'substitution'
       AND player_out_id IS NOT NULL
       AND player_in_id IS NOT NULL
       AND player_out_id <> player_in_id
       AND player_id = player_out_id)
      OR (event_type <> 'substitution'
          AND player_out_id IS NULL
          AND player_in_id IS NULL)
  )
  ```

  El `CHECK` se nombrará de forma explícita y su validación diferida se documentará; `VALIDATE CONSTRAINT` queda fuera de esta spec.
- **RF-032.** Antes del primer `ALTER`, la 021 ejecutará pre-chequeos que **informan** el conteo de eventos `substitution` legados y de filas en `match_segment_team_state`; no aborta por ellos (el cambio es aditivo) y registra los conteos en el runbook.
- **RF-033.** `infra/postgres/init/01` **no cambia**: sigue creando `match_events` y `match_segment_team_state` en su estado base, y la 011 les sigue aplicando `FORCE`. La cadena de volumen limpio (`init/00-03` → 001-021) debe terminar con el mismo esquema que uno ya migrado; no hay rollback, solo *forward-fix*.
- **RF-034.** No habrá backfill de `match_segment_team_state`: sus filas se crean al abrir segmento o se aseguran en el cierre, y sus saldos se recalculan desde los eventos. Los eventos legados sin `player_out_id`/`player_in_id` no consumen cupo ni ventana y no alteran el estado en campo.

### R10 — Minutos derivados de la configuración

- **RF-040.** EL SISTEMA obtendrá `regular_time_minutes` y `extra_time_minutes` de `rules_config.stage_defaults`, con overrides por fase y defaults **90** y **120**. La combinación es **por clave**: el valor efectivo de una fase es el del override si está y, si no, el de `stage_defaults`; un override **parcial** solo cambia lo que declara. Los defaults se aplican en lectura y nunca se escriben para completar una pareja inconsistente.
- **RF-041.** CUANDO se guarde una configuración, EL SISTEMA calculará la **pareja efectiva** y la validará **antes de persistir**: (a) `regular_time_minutes` en `1..179`; (b) SI la prórroga efectiva está habilitada, ENTONCES `extra_time_minutes` será mayor que el reglamentario y ≤ 180; (c) SI está deshabilitada, ENTONCES `extra_time_minutes` es opcional, no se valida y no se materializa. SI incumple, responderá **422** nombrando clave, ámbito (`stage_defaults` o fase) y pareja; **nunca materializará un default que rompa la pareja** (con `extra_time_enabled = true` y `regular = 150` sin `extra`, no se guarda 120; se responde 422), tampoco en overrides parciales.
- **RF-042.** CUANDO se cierre un acta, EL SISTEMA aplicará el máximo efectivo: (a) `minute <= máximo`; (b) SI `minute < máximo`, ENTONCES `minute + added_minute <= máximo`; (c) SI `minute = máximo`, ENTONCES `added_minute <= 30`; (d) `added_minute <= 30` siempre. SI se incumple, responderá **409** nombrando el máximo. El tipo de resolución se valida con las flags reales del motor (`engine.py:217-221`). La frontera reglamentario/prórroga de goles es `minute <= regular_time_minutes`.
- **RF-043.** EL SISTEMA distinguirá el **tope estructural** (180 y `added_minute ≤ 30`, nunca presentado como regla) de la **regla deportiva** aplicada en el cierre; el 180 no aparecerá en mensajes de negocio ni en la validación del cliente, que usará el máximo efectivo.
- **RF-044.** CUANDO una versión existente no declare minutos, EL SISTEMA aplicará 90/120 en lectura sin reescribirla, y el editor mostrará los valores efectivos.
- **RF-045.** CUANDO se consulte la pantalla de operación, EL SISTEMA entregará los límites efectivos (reglamentario, máximo y ventana de descuento, con override de fase), la **configuración efectiva de `substitutions`** y, por equipo, los **jugadores en campo y en banca** y los contadores de sustitución, calculados con la misma función pura que usa el cierre, para que la UI no reimplemente RF-012 ni las reglas de estado. SIN planilla o sin titulares, las listas irán vacías y la respuesta indicará que no se puede registrar una sustitución; el `GET` nunca escribe.
- **RF-046.** EL SISTEMA no reescribirá `rules_config` de versiones publicadas o archivadas; los minutos se escriben solo al guardar un borrador.
- **RF-047.** EL SISTEMA aceptará en el frontend `3.2.0` y `3.3.0`; CUANDO cargue una config con `transfers.roster_lock_matchday` no nulo y sin clave de primer nivel, la **promoverá** al campo antes de normalizar; al guardar normalizará a `3.3.0`, no exigirá `transfers`, conservará `substitutions`, `roster_lock_matchday` y los minutos.
- **RF-048.** CUANDO se cree un segmento o se registre una interrupción, EL SISTEMA validará el minuto contra el **máximo posible** (`extra_time_minutes` si la prórroga está habilitada; `regular_time_minutes` si no) y responderá **422** si lo excede, sin escribir.

### R10 — Contrato interno de códigos y formaciones

- **RF-050.** EL SISTEMA tratará `GF1`/`GF2` como constantes nombradas de única fuente, documentadas como no configurables, y una prueba fallará si el calendario produce otros códigos o el cierre deja de reconocerlos.
- **RF-051.** EL SISTEMA publicará el contrato en `docs/contrato-reglas.md` (`engine_version` **2026.1**) con las cuatro formaciones y sus posiciones y los dos códigos; una prueba verificará que coinciden con las constantes y con el `CHECK` de base de datos. Cualquier otra formación responderá **422** nombrando el catálogo.
- **RF-052.** EL SISTEMA mantendrá el *bracket reset* como lógica del formato: el calendario genera la repetición, el cierre de la gran final exige ganador y la repetición se activa solo si gana el finalista del cuadro de perdedores; una prueba cubrirá la activación.

## Requisitos no funcionales

- **RNF-001.** Sin dependencias ni variables de entorno nuevas.
- **RNF-002.** La 021 es aditiva, con checksums, `MIGRATION_TARGET` y `sh -n infra/postgres/migrate.sh`; sin rollback.
- **RNF-003.** Sin cambios en el contrato público ni campos sensibles nuevos; las sustituciones no se exponen en vistas públicas.
- **RNF-004.** Toda consulta tenant con `set_rls_context()` dentro de la transacción.
- **RNF-005.** Paridad i18n es/en y `pnpm test`, `pnpm run typecheck`, `pnpm run build` si se toca el editor, el acta o `rulesConfig.ts`.
- **RNF-006.** El cierre calcula estado en campo y contadores en memoria sobre los eventos ya cargados (sin consultas por evento); el alta individual hace una comprobación de bloqueo y la importación como máximo dos. No se mide throughput ni latencia.
- **RNF-007.** Documentación afectada (`README.md`, `AGENTS.md`) actualizada en el mismo cambio que el comportamiento (§4).
- **RNF-008.** La enmienda cumple §5.2: cambio propio, aprobado, con motivo/reglas/impacto e historial, sin mezclar.

## Datos personales y privacidad

No aplica en su núcleo. Se tratan reglas deportivas, constantes internas, ventanas de inscripción y **identificadores internos de jugadores** en `match_events` (salida/entrada), que no se añaden a proyecciones públicas ni a la alineación publicada. Los mensajes de error identifican jugadores solo por dorsal/nombre ya visibles en la pantalla de operación, nunca por documento; el mensaje de bloqueo de plantilla solo nombra la jornada.

## Casos límite

1. **Configuración 3.2.0 con `substitutions`:** válida y aplicada; el bloque no es deprecado.
2. **Versión 3.2.0 ya publicada al desplegar:** sus límites de sustitución empiezan a aplicarse; las actas cerradas **no se revalidan** y un partido aún abierto puede rechazar sustituciones antes aceptadas (RF-002).
3. **Configuración sin `substitutions`:** aplica defaults 5/3/`false` en lectura; al guardar se escribe explícito.
4. **Configuración con `substitutions` y `transfers`:** `substitutions` se aplica y `transfers` se ignora.
5. **Versión publicada con bloques deprecados:** mismo resultado; solo cambia el editor en borradores.
6. **`max_per_team = 0`:** toda sustitución responde 409 y el **alta de sustitución en el acta** queda deshabilitada (no es el `RulesEditor`).
7. **`max_windows = 0`:** ninguna sustitución es válida (cada una abre ventana).
8. **Sustitución sin `player_out_id` o `player_in_id`:** 422.
9. **Sustitución con `player_id` distinto de `player_out_id`:** 422.
10. **Evento que no es sustitución con `player_out_id`/`player_in_id`:** 422.
11. **Saliente y entrante iguales:** 422 por contrato (y rechazo por el `CHECK` si se saltara la API).
12. **Jugador de otro equipo:** 409.
13. **Jugador fuera de la plantilla:** 409.
14. **Saliente que no está en campo (ya salió o expulsado):** 409.
15. **Entrante que ya está en campo:** 409.
16. **Entrante expulsado o saliente expulsado:** 409 (un expulsado no se sustituye ni reingresa).
17. **`allow_reentry = false` y entrante que ya estuvo en campo:** 409.
18. **`allow_reentry = true` y entrante que ya estuvo en campo y no está ahora:** válido; consume sustitución y ventana.
19. **Reentrada con intervalos:** jugador que sale en el 60 y vuelve en el 70; un gol en el 65 del jugador que **entró** en el 60 es válido, y el mismo gol atribuido al que salió en el 60 es 409 (unión de intervalos, no intervalo único).
20. **Dos sustituciones del mismo equipo en el mismo segmento y minuto:** una sola ventana, dos sustituciones.
21. **Dos sustituciones del mismo equipo en el mismo minuto pero distinto `added_minute`:** dos ventanas.
22. **Sustituciones en segmentos distintos al mismo minuto:** dos ventanas (el segmento forma parte de la clave).
23. **Segundo equipo con su propio cupo:** los límites son por equipo; los contadores de un equipo no afectan al otro.
24. **Sustitución que excede `max_per_team`:** 409 con el saldo; cero escrituras.
25. **Sustitución que excede `max_windows`:** 409 con el saldo; cero escrituras.
26. **Sin planilla o sin titulares en el equipo:** 409 y el acta no se guarda.
27. **Planilla con minutos que contradicen una sustitución y jugador sin reentrada:** 409.
28. **Gol de un jugador después de su salida (sin reentrada):** 409 por intervalo efectivo.
29. **Gol de un jugador antes de su entrada:** 409.
30. **Gol de un jugador dentro de su segundo intervalo (reentrada):** válido.
31. **Sustitución en un segmento interrumpido:** 409 (los eventos solo van a segmentos activos o completados).
32. **Resolución `walkover` o `administrative` con sustituciones:** 409 (esas resoluciones no admiten eventos).
33. **Duplicado de `client_event_id` en el acta:** 422.
34. **Reintento idéntico de un evento ya persistido:** se reutiliza y no cuenta dos veces.
35. **Reintento con el mismo `client_event_id` y otro jugador:** 409 «inmutable».
36. **Acta confirmada:** INSERT o UPDATE de cualquier evento se rechaza por `trg_validate_match_event_context`; no hay re-cierre ni anulación operativa, y `is_voided` queda como legado.
37. **Evento `substitution` legado sin salida/entrada:** se ignora; no consume cupo ni ventana y no altera el estado en campo.
38. **Intento de UPDATE de un evento legado:** el `CHECK NOT VALID` se evalúa y lo rechaza; no hay tolerancia en escritura (RF-031).
39. **Filas de `match_segment_team_state` inexistentes en un partido antiguo:** se aseguran en el cierre y los saldos se recalculan; el `GET` de operación las calcula sin escribir.
40. **Partido con segmentos creados antes del despliegue:** las filas se crean al asegurarlas en el cierre; no hay backfill.
41. **Partido sin equipos asignados al abrir un segmento:** se crean filas solo para los equipos presentes y se asegura el resto en el cierre.
42. **Segmento nuevo tras una interrupción:** la fila se crea con el cupo disponible del partido (en un partido abierto es el completo, porque los eventos se registran al cerrar) y se recalcula al cerrar con el consumo real de los segmentos anteriores.
43. **Segmentos con numeración y minutos no coincidentes:** el recálculo del cierre ordena por `segment_number`, no por `minute`.
44. **Dos cierres simultáneos del mismo partido:** el bloqueo del partido serializa; el segundo ve el estado final y responde 409.
45. **Migración 021 con eventos legados:** el `CHECK NOT VALID` no bloquea la migración; los conteos quedan en el runbook.
46. **Migración 021 en volumen limpio:** `init/01` crea el esquema base, la 011 fuerza RLS y la 021 añade columnas y FKs compuestas; el esquema final coincide con el migrado.
47. **`init/01` sin cambios:** la tabla, la política y los grants existentes siguen siendo válidos; no se edita ningún script de init.
48. **Código nuevo desplegado antes de la 021:** un cierre con sustitución falla al insertar columnas inexistentes; el orden de despliegue es migración 021 **antes** del código que escribe esas columnas.
49. **Configuración con `extra_time_enabled = true` y `regular = 150` sin `extra`:** 422; no se materializa 120.
50. **Override parcial que cambia solo `regular` a 150 heredando `extra = 120` con prórroga:** 422 y no se guarda.
51. **Override parcial que cambia solo `extra` a 180 heredando `regular = 90`:** válido para esa fase.
52. **Override parcial con `extra_time_enabled = false` y `regular = 150`:** válido; `extra` se ignora y no se materializa.
53. **`regular = 179` y `extra = 180`:** válido; `regular = 180` o `extra = 181` con prórroga → 422.
54. **Torneo 40/100 con gol en el minuto 50:** cuenta como prórroga; máximo 100.
55. **Evento 90+2 en un partido 90/120:** válido y reglamentario; **89+30**: 409; **120+31**: 422.
56. **Segmento en el minuto 95 con prórroga de 120:** válido; con prórroga deshabilitada: 422.
57. **Interrupción en el minuto 125 con máximo 120:** 422.
58. **Acta cerrada antes del despliegue con 120 minutos:** no se revalida.
59. **Formación fuera del catálogo:** 422 por API y rechazo por `CHECK`.
60. **Gran final sin ganador / repetición:** se mantiene el error; la repetición se activa con el finalista del cuadro de perdedores.
61. **Cargar en el editor una config 3.2.0 con `transfers.roster_lock_matchday = 4`:** el campo muestra 4 antes de normalizar; al guardar sale 3.3.0 con la clave y sin `transfers`.
62. **Bloqueo de plantilla activo, alta individual:** 409 con la jornada, sin filas de `rosters` ni `players`.
63. **Bloqueo de plantilla activo, importación:** 409 antes de subir fotos; sin filas ni objetos.
64. **Bloqueo activado entre las dos comprobaciones de la importación:** 409, sin filas y con fotos compensadas.
65. **Torneo sin versión publicada o jornada de referencia inexistente:** no bloquea.
66. **Mensaje de bloqueo:** solo la jornada; sin nombre de torneo ni datos personales.
67. **`GET /operation` con planilla:** devuelve `on_field` y `bench` por equipo, la config efectiva de `substitutions` y los contadores; la UI no recalcula el estado.
68. **`GET /operation` sin planilla:** devuelve listas vacías y el aviso de que no se puede registrar una sustitución; no escribe filas.
69. **Vista previa de contadores:** el cliente calcula saldo y validaciones sobre el borrador usando el estado del servidor como base; al cerrar, el servidor recalcula y su resultado manda (409 si el borrador era inválido).

## Riesgos y mitigaciones

- **Estado en campo mal derivado.** Mitigación: XI inicial explícito desde `match_rosters`, orden total de eventos y pruebas con eventos desordenados, expulsiones y reentrada (RF-012 a RF-014).
- **Contadores que se desincronizan.** Mitigación: recalcular desde los eventos con salida/entrada al cerrar (y al abrir segmento), ordenando por `segment_number`, nunca decrementar a ciegas; la lectura usa la misma función pura (RF-016).
- **Doble conteo por reintentos.** Mitigación: `client_event_id` + comparación completa del evento (RF-018).
- **La anulación no existe como operación.** Mitigación: no se promete; los eventos de un acta confirmada son inmutables por trigger y el acta no se re-cierra (RF-018, Nota de alcance). Corregir un acta cerrada exige otra spec.
- **Configuraciones existentes.** Mitigación: `substitutions` ya existe en 3.2.0, defaults en lectura y `transfers` deprecado (RF-002).
- **Eventos legados de sustitución.** Mitigación: `CHECK NOT VALID`, motor que los ignora y pre-chequeo informativo (RF-031, RF-034).
- **Migración y orden de despliegue.** Mitigación: 021 aditiva **antes** del código que escribe las columnas (caso 43), backup verificado y *forward-fix*.
- **Complejidad del acta.** Mitigación: una sola transacción de cierre ya existente, validaciones ordenadas y UI que filtra opciones inválidas (RF-017, RF-019).
- **Tope de `minute + added_minute`.** Mitigación: descuento solo en el minuto final y actas cerradas no revalidadas (RF-042).
- **Enmienda mezclada.** Mitigación: RF-006 y RNF-008.

## Fuera de alcance

- **R11, R12, R18-R32**; R13/R14 pertenecen a otras specs.
- **Transferencias completas** (traspasos, ventana de fichajes, historial).
- **API de eventos individuales y de anulación**: los eventos de un acta confirmada son inmutables (Nota de alcance).
- Abrir el catálogo de formaciones; configurar el *bracket reset*.
- Reglas deportivas nuevas o cambios de puntuación, desempates, disciplina y `walkover_score`.
- UI de marcador en vivo o cronología más allá de RF-019 y RF-045.
- Reescribir resultados, actas cerradas o `rules_config` publicados.
- Editar `docs/constitution.md` (lo hace el cambio de enmienda), 019/020 o artefactos de la spec 006.
- Añadir dependencias, cambiar versiones de referencia, Compose o `.env.example`.

## Verificación de constitución (para esta spec)

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por RLS | Sí | Lecturas y escrituras con contexto; la 021 no crea tablas tenant y añade **FKs compuestas** `(player_out_id, organization_id)` y `(player_in_id, organization_id)` a `players(id, organization_id)`, como la 015; el aislamiento no se apoya solo en RLS (RF-030, RNF-004). |
| §2.2 Rol sin `BYPASSRLS` | Sí | Sin cambios de rol ni funciones `SECURITY DEFINER`. |
| §2.3 Lo publicado es inmutable | Sí | Las sustituciones se escriben solo en el cierre; los eventos de un acta confirmada son inmutables (`trg_validate_match_event_context` bloquea INSERT/UPDATE en partidos terminados) y no hay anulación operativa (RF-018, RF-046). |
| §2.4 Migraciones append-only | Sí | Solo la 021, aditiva; 019/020 intactas; sin rollback (RF-030 a RF-033, RNF-002). |
| §2.5 Proyección pública mínima | Sí | Las sustituciones no se añaden a vistas públicas ni a la alineación publicada (RNF-003). |
| §2.6 Sin secretos por defecto | No aplica | Sin variables ni secretos nuevos. |
| §2.7 Administración global separada y auditada | No aplica | No se toca `/admin` ni `platform_audit_logs`. |
| §2.8 Nada sin verificación | Sí | Criterios con jobs de CI y declaración de lo no ejecutado. |
| §2.9 El código de desarrollo no llega a producción | Sí | `scripts/seed_demo.py` usa `DEFAULT_RULES_CONFIG` (`seed_demo.py:28, 344, 376, 1425`); el seed sigue siendo solo de desarrollo y ninguna migración depende de datos demo. |
| §3.1 RLS y migraciones | Sí | `set_rls_context` en cada transacción; migración con checksum y prueba en limpio y migrado. |
| §3.2 Backend y reglas en JSON | Sí, **con conflicto** | El §3.2 vigente lista «transferencias»; esta spec las retira y aplica `substitutions`. **No se declara cumplimiento hasta la enmienda 1.3.0 mergeada (RF-006, §5.2).** |
| §3.3 Frontend y `useApi.ts` | Sí | Editor y acta usan `useApi.ts`; paridad i18n y normalización (RF-019, RF-047). |
| §3.4 Seguridad y configuración | Sí | Sin defaults nuevos; mensajes sin datos personales. |
| §3.5 Infraestructura y CI | Sí | Sin cambios de versiones ni Compose; jobs `infrastructure` y `security` se ejecutan. |
| §4 Criterios de cambio | Sí | Jobs `backend`/`frontend`/`security`, runner de migraciones, documentación y revisión humana distinta del autor. |
| §5.2 Evolución | Sí | Enmienda como cambio propio, aprobado, con motivo/reglas/impacto e historial (RF-006, RNF-008). |

## Pruebas previstas y qué no se cubre

- **Enmienda (revisión documental):** el §3.2 de `docs/constitution.md` coincide literalmente con el texto de esta spec, versión `1.3.0`, fecha `2026-10-20` e historial; el cambio de enmienda no incluye código funcional (RF-006).
- **Unitarias puras (sin base de datos):** estado en campo con XI inicial, sustituciones y expulsiones, en cualquier orden de entrada; **unión de intervalos con reentrada** (gol en 65 válido para el que entró en 60, 409 para el que salió en 60); reentrada permitida y prohibida; ventanas por `(segment, minute, added_minute)`; límites por equipo; `max_per_team = 0`; validación del contrato del evento (422); minutos efectivos y conflictos con la planilla cuando no hay reentrada; mensajes 409 con saldo; misma función pura para el payload de operación.
- **Unitarias del motor/config:** `3.2.0` con `substitutions` valida; `3.3.0` sin `transfers`; defaults si falta `substitutions`; promoción del heredado; pareja efectiva con overrides parciales y `extra_time_enabled` true/false; 40/100 con gol al 50; bordes 179/180; tope `minute + added_minute` con descuento final; clasificación de claves aplicadas/deprecadas; contrato de `docs/contrato-reglas.md`; activación de la repetición.
- **Integración opt-in (`RUN_DATABASE_TESTS=1`, `DATABASE_ADMIN_URL`, archivos `backend/tests/test_migration_021.py` y `backend/tests/test_substitutions.py`):** 021 sobre volumen limpio y migrado; columnas, FKs compuestas y `CHECK NOT VALID` aceptando filas nuevas válidas y rechazando las inválidas; un `UPDATE` de un evento legado se rechaza; pre-chequeos con conteos; esquema final idéntico; cierre con sustituciones en varios segmentos, recálculo de **todas** las filas ordenadas por `segment_number`, límites y ventanas, reentrada con intervalos, dos cierres concurrentes, filas aseguradas en partidos antiguos y `GET /operation` sin escrituras que expone campo, banca, configuración efectiva y contadores. **No se prueba anulación** porque no existe.
- **Inmutabilidad (opt-in):** tras el cierre, un INSERT o UPDATE de `match_events` falla por el trigger 009; no hay re-cierre.
- **Frontend (si se toca el acta o `rulesConfig.ts`):** dos selectores con filtros (sale/entra) alimentados por `on_field`/`bench` del servidor, deshabilitado con `max_per_team = 0`, contadores de vista previa calculados sobre el **borrador** con el valor del servidor como base, mensajes de 409/422, promoción al cargar 3.2.0, normalización a 3.3.0, paridad i18n; `pnpm test`, `pnpm run typecheck`, `pnpm run build`.
- **Guarda de código:** sin `transfers` en editor ni configuraciones nuevas; `substitutions` sí en el editor y en el motor; sin endpoints de eventos nuevos.
- **No se cubre:** E2E de navegador; rendimiento medido; datos de producción; desempates; `live`/`suspended` (R11); registro incremental y API de eventos; corrección de actas cerradas; transferencias completas.

## Criterios de finalización

0. **Cambio previo:** la enmienda §3.2 → 1.3.0 está mergeada como cambio propio con el texto exacto, versión, fecha e historial, y el cambio funcional no edita la constitución (RF-006).
1. Sustituciones operativas: configuración aplicada, contrato de evento, estado en campo, límites, ventanas, reentrada, contadores y UI, con 409/422 correctos y acta atómica (RF-010 a RF-019).
2. Migración 021 aplicada **antes** del código que escribe las columnas: columnas, FKs y `CHECK NOT VALID`, pre-chequeos informativos, `init/01` sin cambios, esquema limpio idéntico al migrado y sin rollback (RF-030 a RF-034).
3. Transferencias retiradas y `roster_lock_matchday` aplicado con promoción, fuente publicada, referencia, estado confirmado y dos comprobaciones en la importación (RF-020 a RF-029).
4. Minutos desde `rules_config` con pareja efectiva validada, defaults, frontera reglamentario/prórroga, tope `minute + added_minute` y segmentos/interrupciones validados (RF-040 a RF-048).
5. `GF1`/`GF2` y formaciones publicados en `docs/contrato-reglas.md` con `engine_version` 2026.1, coincidentes con código y `CHECK`, y repetición probada (RF-050 a RF-052).
6. Documentación actualizada: `README.md` y `AGENTS.md` con sustituciones aplicadas, sin transferencias, con el contrato interno (`docs/contrato-reglas.md` en las fuentes de verdad y la estructura) y el runbook de la 021, incluido el **orden migración 021 → código** que escribe las columnas (RF-001, RNF-007).
7. Comandos ejecutados y reportados:
   - **Backend:** `cd backend && pytest -q`; `cd backend && python -m compileall -q app`.
   - **Migraciones:** `sh -n infra/postgres/migrate.sh`; runner con PostgreSQL local según `AGENTS.md`; `MIGRATION_TARGET=021 $COMPOSE run --rm db-migrate` tras backup verificado con `pg_restore -l`; pre-chequeos del runbook.
   - **Opt-in:** `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_021.py tests/test_substitutions.py`.
   - **Frontend:** `cd frontend && pnpm install --frozen-lockfile`, `pnpm test`, `pnpm run typecheck`, `pnpm run build`.
   - **Security (bloque exacto de `AGENTS.md`):**

     ```sh
     pip-audit -r backend/requirements.txt
     AUDIT_JSON="/tmp/pnpm-audit.json"
     trap 'rm -f "$AUDIT_JSON"' EXIT
     if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
     PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
     trivy fs . --skip-dirs frontend/node_modules,frontend/.pnpm-store,.venv --ignore-unfixed --severity CRITICAL,HIGH --exit-code 1
     ```

   - **Infraestructura:** `python3 infra/scripts/verify_version_sources.py --exclude-constitution`; `docker compose config -q` para desarrollo y el merge dev+prod con variables dummy.
8. Si algo no pudo ejecutarse, se declara como no ejecutado; no se da por verificado.

## Dudas abiertas

Ninguna. Las decisiones de producto están cerradas, incluida la implementación de sustituciones y de `match_segment_team_state`; el registro sigue el flujo de cierre existente y un acta confirmada es inmutable (Nota de alcance). No hay ninguna decisión pendiente para planificar.
