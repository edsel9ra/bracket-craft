# Tareas 015 — Catálogo de eventos y asistencias

Plan: `specs/015-catalogo-de-eventos-y-asistencias/plan.md`. Spec aprobada el 2026-10-25.
**Orden:** migración → contrato → motor → servicio → persistencia → interfaz → documentación → verificación.
Cada tarea empieza por la prueba en rojo y termina en verde.

> **13 tareas: supera el máximo de 10.** No se han fusionado tareas para caber: cada una tiene un "hecho cuando" propio y varias superan los 30 minutos si se juntan. **Corte propuesto** (ya acordado el criterio de dividir): **015A = T1–T7** (esquema, contrato, motor, servicio y persistencia; entregable y verificable solo con `pytest`, y el cliente actual sigue funcionando porque nunca envía `metadata` libre, ni un `client_event_id` que no sea UUID, ni `beneficiary_team_id` en un tipo ajeno) y **015B = T8–T13** (interfaz, textos, documentación y verificación conjunta). Si el usuario prefiere una sola entrega, se ejecutan las 13 en orden.

---

- [x] **T1. Migración 026 con su prueba opt-in.** RF-007 (parte estructural), RF-013, RNF-004
  - Primero `backend/tests/test_migration_026.py` en rojo (cadena limpia `init` + 001..026 y salto 025 → 026; columna, FK compuesta, `CHECK`, tolerancia de filas sin asistencia, rechazo de asistencia en un tipo que no sea `goal`).
  - Después `infra/postgres/migrations/026_match_event_assists.sql`: columna nula, FK `(assist_player_id, organization_id) → players(id, organization_id)` `ON DELETE RESTRICT` y `chk_match_event_assist` validado. Sin *backfill*, sin tocar `init/01` ni políticas/grants.
- Hecho cuando: `sh -n infra/postgres/migrate.sh` sale 0; `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_026.py` está en verde, y la misma prueba falla con la migración ausente (columna inexistente) y con el `CHECK` retirado. La forma final de la cadena limpia y de la migrada coincide (la prueba lo compara).

- [x] **T2. Catálogo cerrado en el esquema: raíz, `metadata` y beneficiario.** RF-002, RF-009, RNF-003
  - Primero `backend/tests/test_match_events_contract.py` en rojo: campo de primer nivel desconocido, `metadata` con clave ajena, `metadata.red_card_type` fuera de `red_card`, `beneficiary_team_id` en `goal`/`yellow_card`/`red_card`/`foul`/`substitution`, y los casos que siguen válidos (`goal` sin beneficiario, roja con su clase).
  - Después `backend/app/modules/matches/schemas.py`: `EventType` como constante, `model_config = ConfigDict(extra="forbid")` y validadores por tipo.
- Hecho cuando: `cd backend && pytest -q tests/test_match_events_contract.py` verde y `pytest -q` completo sin regresiones; `python -m compileall -q app` sale 0.

- [x] **T3. Asistente y `client_event_id` en el esquema.** RF-007 (estructura), RF-015
  - Primero en rojo, en el mismo archivo de T2: `assist_player_id` en `goal` aceptado y en los otros seis tipos **422**; `assist_player_id = player_id` **422**; `client_event_id` con `event-1234`, vacío o de 101 caracteres **422**; UUID con y sin mayúsculas aceptado.
  - Después `schemas.py`: `assist_player_id: UUID | None` y `client_event_id` con patrón UUID.
- Hecho cuando: `cd backend && pytest -q tests/test_match_events_contract.py` verde con los casos nuevos y `pytest -q` sigue verde.

- [x] **T4. Motor puro: código y validación del asistente.** RF-008
  - Primero pruebas unitarias en rojo en `backend/tests/test_match_assists.py` (motor puro, sin base): asistente de otro equipo, fuera de la plantilla del partido, con fila invalidada, expulsado antes del gol, ya sustituido, todavía en la banca y en campo → válido; la reentrada por la unión de intervalos; el minuto exacto de la sustitución; el mismo jugador asistiendo dos goles; el gol sin asistente; y el contrato HTTP del código.
  - Después `backend/app/modules/rules_engine/substitutions.py`: `MatchEvent.assist_player_id` (y su lectura en `from_mapping`), `GOAL`, el código `SubstitutionErrorCode.ASSIST_PLAYER_INVALID` y `validate_assist_player`. La comprobación se invoca **dentro del replay puro** (`matches/service.py:replay_report_state`, no en el servicio de cierre): el estado usado es el de los eventos anteriores al gol en orden canónico, la misma regla que la comprobación del goleador.
  - `backend/app/modules/matches/errors.py`: `AssistPlayerInvalid` (HTTPException 409 con `code`). `backend/app/main.py`: registro del manejador `_coded_exception_handler`.
- Hecho cuando: `cd backend && pytest -q` completo verde (1561 passed, 322 skipped) y `python -m compileall -q app` sale 0; `grep -n "ASSIST_PLAYER_INVALID" backend/app/modules/matches/errors.py` y `grep -n "AssistPlayerInvalid" backend/app/main.py` muestran ambos lados del contrato.

- [x] **T5. Servicio de cierre: pertenencia, asistente y regla de identificadores.** RF-003, RF-008, RF-014, RF-017
  - Primero `backend/tests/test_match_assists_db.py` en rojo (opt-in): cierre con asistente válido, asistente de otro equipo o fuera de plantilla → **409** con `code` `ASSIST_PLAYER_INVALID`, asistente = goleador → **422**, jugador de otra organización → **409** (nunca 404 ni 500), partido y segmento de otra organización → **404**.
  - Después `service.py`: `_validate_substitutions` traduce el error del asistente a `AssistPlayerInvalid`; la pertenencia se decide contra la plantilla del partido.
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_match_assists_db.py` verde en los casos de esta tarea; `cd backend && pytest -q` sigue verde.

- [x] **T6. Persistencia, operación e idempotencia con `metadata` y asistente.** RF-007, RF-011, RF-012
  - Primero en rojo, en `test_match_assists_db.py`: la fila guarda y devuelve `assist_player_id`; la operación lo expone sin nombres; reintento idéntico reutiliza; reintento que cambia `metadata` o el asistente responde **409** «inmutable»; acta sin asistencia sigue funcionando.
  - Después `service._persist_events` (INSERT, `RETURNING` y comparación con `metadata` normalizada `{}` ↔ `None`) y `router.py` (añadir `me.assist_player_id` a la consulta de eventos de la operación).
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_match_assists_db.py` verde; `cd backend && pytest -q` y `python -m compileall -q app` en verde.

- [x] **T7. El asistente no altera resultado, clasificación ni sanciones; históricos intactos.** RF-010, RF-013
  - Primero en rojo, en `test_match_assists_db.py`: dos cierres equivalentes, uno con asistencia y otro sin ella, producen el mismo marcador, los mismos puntos y las mismas sanciones; un acta sembrada sin asistente se lee y se cierra sin tocarla.
  - Después: ninguna lógica nueva; si la prueba en rojo revela acoplamiento, se corrige en `standings/` o en `evaluate_suspensions` **solo** para desacoplar, sin cambiar la regla.
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_match_assists_db.py -k "assist or history"` verde, y `pytest -q` completo verde sin cambios en `tests/test_match_resolution_db.py`.

- [x] **T8. Utilidades puras del cliente.** RF-001, RF-004, RF-005, RF-006, RF-015
  - Primero `frontend/tests/match-events.test.ts` en rojo.
  - Después `frontend/app/utils/matchEvents.ts`: `EVENT_TYPES`, `eventFields`, `assistCandidates`, `validateAssist`, `isUuid`, `newClientEventId(cryptoSource)`, `buildDraftEvent`, `eventSummary`.
- Hecho cuando: `cd frontend && pnpm test` verde con el archivo nuevo, y `pnpm run typecheck` sale 0.

- [x] **T9. Formulario dinámico y resumen en la operación.** RF-001, RF-005, RF-006, RF-007 (UI), RF-008 (UI)
  - Primero: se amplía `frontend/tests/match-events.test.ts` con los casos de campos por tipo y del resumen con asistente (rojo).
  - Después `frontend/app/pages/workspace/matches/[id].vue`: campos desde `eventFields`, selector de asistente solo en `goal` (candidatos del mismo equipo salvo el goleador), resumen con asistente en el borrador y en el acta persistida, alta con `newClientEventId` y bloqueo explícito si no hay `randomUUID`.
- Hecho cuando: `cd frontend && pnpm test` y `pnpm run typecheck` en verde; la pantalla conserva las anclas `match.eventType` y `match.minute` (la prueba de barrido de claves y el `typecheck` no fallan).

- [x] **T10. Borrador local: asistente y descarte de identificadores antiguos.** RF-013, RF-015, RNF-003
  - Primero en rojo, en `frontend/tests/substitutions.test.ts`: `readDraftEvent` acepta el asistente válido, descarta el evento con asistente en tipo ajeno, descarta `client_event_id` que no sea UUID y **conserva** eventos antiguos sin asistente.
  - Después `frontend/app/utils/substitutions.ts` (`DraftEvent.assist_player_id`, lectura y sanea) y, si hace falta, el aviso de eventos descartados en la pantalla.
- Hecho cuando: `cd frontend && pnpm test` verde con los casos nuevos; `pnpm run typecheck` sale 0.

- [x] **T11. Textos en español e inglés.** RF-001, RF-004, RF-005, RNF-009
  - Añadir `match.assist`, `match.assistNone`, `match.assistHint`, `match.eventIdUnavailable`, `match.draftEventsDropped` y `match.foulInformative` en los dos catálogos de `frontend/app/composables/useI18n.ts`.
- Hecho cuando: `cd frontend && pnpm test` verde (incluida la paridad es/en y el barrido de claves usadas) y `pnpm run build` sale 0.
- Ejecutado (2026-10-25): las seis claves están, más `match.assistShort` (separa la etiqueta del campo de la palabra del resumen). `pnpm test` **580 passed** (cifra de esa tarea; el cierre de la spec, tras las dos rondas de correcciones, deja **588**) y `pnpm run typecheck` 0. `pnpm run build` **no ejecutado**: el servidor de desarrollo está vivo y esta tarea no lo permite; lo cubre T13.

- [x] **T12. Documentación del contrato que cambia.** RNF-003, RNF-009, RF-016
  - `AGENTS.md`: catálogo por tipo, asistencia como campo del gol, cierre de `metadata` y de `beneficiary_team_id`, `client_event_id` UUID, migración 026 y orden 026 → código.
  - `README.md`: qué pide cada evento, asistencia opcional y opaca.
  - Confirmar que `docs/contrato-reglas.md` **no** cambia y que `engine_version` sigue en 2026.1.
- Hecho cuando: `git diff --stat` muestra solo `AGENTS.md` y `README.md` además de lo anterior; `git diff docs/contrato-reglas.md` está vacío; `python3 infra/scripts/verify_version_sources.py --exclude-constitution` sale 0.
- Ejecutado (2026-10-25): `AGENTS.md` añade el resumen del catálogo y la asistencia en «Arquitectura Clave», el cambio observable en «Contratos que cambian», la migración 026 en «Límites del Proyecto», «Comandos» (runbook), «Runtime» y «Testing», y actualiza «Contrato interno»; `README.md` añade la sección «Eventos del acta y asistencias» y el runbook de la 026. `docs/contrato-reglas.md` sin cambios. `verify_version_sources.py --exclude-constitution` y `sh -n infra/postgres/migrate.sh` salen 0.

- [x] **T13. Verificación completa del conjunto.** RNF-005, RF-001 a RF-017
  - Ejecutar, en este orden: `cd backend && pytest -q`; `cd backend && python -m compileall -q app`; `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_026.py tests/test_match_assists_db.py`; `sh -n infra/postgres/migrate.sh`; `cd frontend && pnpm test`; `pnpm run typecheck`; `pnpm run build`; `docker compose config -q`.
  - Recorrer la tabla de criterios de finalización de la spec y anotar, criterio por criterio, la prueba o la evidencia que lo respalda.
- Hecho cuando: todos los comandos anteriores salen 0 y la tabla de los 23 criterios queda cubierta con su evidencia; lo que no se haya podido ejecutar (por ejemplo, una corrida con base sin PostgreSQL disponible) se declara **no ejecutado** sin marcarlo como verde.
- Ejecutado (2026-10-25), con los contenedores de la pila de desarrollo (recuentos de la corrida final, tras las dos rondas de correcciones): backend sin base **1575 passed / 341 skipped**; backend con base (`RUN_DATABASE_TESTS=1`, 0 omitidas) **1917 passed**; `compileall` 0; `sh -n infra/postgres/migrate.sh` 0; runner de `MIGRATION_TARGET` 0; `sh -n infra/scripts/verify_worker_loop_health.sh` 0; frontend `pnpm test` **588 passed / 0 failed**, `typecheck` 0, `typecheck:e2e` 0 y `pnpm run build` 0 (con `web` detenido y reiniciado); infraestructura y merge dev+prod 0 (versiones, contrato de entorno 51 variables, aserciones de desarrollo y de producción); seguridad: `pip-audit` sin vulnerabilidades conocidas y auditoría del frontend OK (2 hallazgos no accionables). **No ejecutado:** Trivy (no está instalado en el entorno). El arnés `e2e` **sí** cubre el acta (`operation-flow`) y su resultado se registra en «Correcciones tras la validación».
- Trazabilidad criterio → evidencia de esta corrida (archivos de prueba nuevos salvo indicación; los comandos están en la tabla de verificación del informe de la tarea):

  | # | Evidencia | Estado |
  |---|---|---|
  | 1 | `frontend/tests/match-events.test.ts`: `the catalog of fields per type matches the server contract`, `the payload of every type has exactly the keys the server declares`, `a payload built for each type never carries a forbidden value`, `the form of each type renders only its own fields, in catalog order`, `the catalog marks the required fields and never the optional assistant`; `substitutions.test.ts`: `drops a draft event whose fields belong to another type` | cubierto |
  | 2 | `backend/tests/test_match_events_contract.py`: `an unknown top-level key is rejected`, `metadata with an undeclared key is rejected`, `red card metadata does not admit extra keys`, `red card type only applies to a red card`, `beneficiary_team_id is only admitted in an own goal`; el 422 lo produce el DTO antes del handler | cubierto |
  | 3 | `test_match_events_contract.py`: `own goal requires a beneficiary that is not its own team` (422); `tests/test_close_substitutions.py`: `test_close_rejects_a_player_from_another_team` (409) y `test_close_answers_409_for_a_team_of_the_organization_that_does_not_play`; `tests/test_substitutions_rules.py`: `substitution requires both players in the team roster` | cubierto |
  | 4 | `match-events.test.ts`: catálogo de `foul` (solo jugador), `an own goal and a foul read with their player only`, `the new report notices are announced to the screen reader` (`match.foulInformative`); `rules_engine/engine.py:389` solo cuenta `goal`/`own_goal`/`penalty_goal` | cubierto (el «sin efecto» del servidor, por inspección del cálculo; sin prueba dedicada de `foul`) |
  | 5 | `match-events.test.ts`: `a goal reads with its scorer and, when there is one, its assistant`, `an own goal and a foul read with their player only, never an assistant`, `a substitution reads as outgoing then incoming`, `the summary never shows an assistant outside a goal`, `the summary of the report shows the assistant in the draft and in the report` | cubierto |
  | 6 | `match-events.test.ts`: `the client validation accepts the required fields of every type`, `the client validation reports the missing required field of each type`, `the client validation does not judge what belongs to the server`, `an empty assistant is always valid`; cada error se queda en su campo con `aria-invalid`, `aria-describedby` y su mensaje `role="alert"`, y `every registration error is associated with its field` lo exige en los once controles (`event_type`, `segment`, `team`, `player`, `player_out`, `player_in`, `assist`, `beneficiary`, `red_card_type`, `minute`, `added_minute`); `the minute must fall inside the selected segment when it has an end` cubre el intervalo del segmento y `a change of event type is announced with the fields it shows` el anuncio del cambio de tipo (RNF-007); textos por `t()` (es/en) | cubierto |
  | 7 | `backend/tests/test_match_assists.py`: `test_a_goal_with_an_assist_on_the_field_is_valid`, `test_an_assist_from_the_other_team_is_rejected`, `test_an_assist_outside_the_match_roster_is_rejected`, `test_an_assist_who_was_ejected_before_the_goal_is_rejected`, `test_an_assist_who_left_before_the_goal_is_rejected`, `test_a_substitute_who_has_not_entered_yet_cannot_assist`, `test_the_same_player_can_assist_two_goals_of_the_same_match`; `tests/test_close_substitutions.py`: `test_close_translates_an_assist_from_the_other_team_to_the_coded_409`, `test_close_translates_an_assist_outside_the_match_roster_to_the_coded_409`; `test_match_assists_db.py`: `test_an_assist_from_another_organization_is_a_coded_409`; `test_match_events_contract.py`: `test_the_assistant_must_be_a_different_player_than_the_scorer` (422) | cubierto |
  | 8 | `test_match_events_contract.py`: `an assistant is rejected in every type that does not declare it` (seis tipos, 422) | cubierto |
  | 9 | `test_match_assists_db.py`: `the assist never changes result standings sanctions or outbox` (dos cierres equivalentes, con y sin asistencia) | cubierto |
  | 10 | `test_match_assists_db.py`: `closing with an assist persists the column`, `the operation returns the assist as a uuid without names`; `grep assist_player_id backend/app` solo aparece en `matches/` (operación) y en la 026: ninguna ruta ni vista pública lo expone | cubierto |
  | 11 | `test_match_assists_db.py`: `an identical retry reuses the persisted event`, `a retry with the same metadata is reused`, `a retry with a different metadata is immutable`, `a retry with a different assist is immutable`, `a retry with a different case is the same event` | cubierto |
  | 12 | `backend/tests/test_migration_026.py`: `026 keeps legacy goals without assist and accepts new ones` (sin *backfill*, `metadata` libre conservada y fila aún escribible); `test_match_assists_db.py`: `a historical event without assist is read without revalidation` (identificador no UUID y clave de `metadata` no declarada), `closing beside legacy events never raises the assist error` | cubierto |
  | 13 | `test_match_assists_db.py`: `a segment from another organization is 404`, `a team from another organization is 404`, `a beneficiary team from another organization is 404`, `a segment from another match is 404`, `a scorer from another organization is 409 not 404`; `tests/test_close_substitutions.py`: `close answers 404 for a segment/team of another organization`. **Salvedad:** el «partido de otra organización → 404» depende del filtro por organización preexistente (`router.py:131`), sin prueba nueva | cubierto con salvedad (partido sin prueba explícita) |
  | 14 | `test_match_events_contract.py`: `a client event id that is not a uuid is rejected`, `a client event id with uuid shape is accepted`, `the close request requires uuid client event ids`; `match-events.test.ts`: `without randomUUID the client does not invent an identifier`, `a crypto source that fails... yields nothing`, `without randomUUID the report blocks the registration instead of inventing an id`; `substitutions.test.ts`: `drops a draft event with an identifier of the older drafts and counts it` | cubierto |
  | 15 | `docs/contrato-reglas.md` sin cambios (`git diff` vacío; `engine_version` `2026.1` en la línea 3), `AGENTS.md` lo declara por escrito; `tests/test_rule_contract.py` en verde dentro de la suite | cubierto |
  | 16 | `git diff backend/app` sin rutas ni permisos nuevos (solo un manejador de excepción en `main.py`, el `code` en `errors.py` y la columna en la consulta de operación); `core/permissions.py` sin cambios; suite completa en verde | cubierto |
  | 17 | `infra/postgres/migrations/026_match_event_assists.sql`: columna nula, FK compuesta y `CHECK` validado, sin *backfill* ni cambios en `init/`; `test_migration_026.py` (columna, FK, `CHECK`, filas históricas, cadena limpia = cadena migrada); `sh -n infra/postgres/migrate.sh` 0; runner de `MIGRATION_TARGET` 0 | cubierto |
  | 18 | Los comandos de verificación de esta tarea, todos 0 (recuentos arriba) | cubierto |
  | 19 | `test_match_events_contract.py` (mensajes sin eco de claves), `tests/test_error_sanitization.py` (el 422 descarta `input`/`ctx` globalmente), `test_match_assists.py`: `the error message never needs the player name`; `test_match_assists_db.py`: `test_the_close_audit_keeps_the_assist_uuid_without_names` (la auditoría del cierre guarda el UUID del asistente y ningún nombre, documento ni fecha de nacimiento); motivo y notas (1 000) se documentan como riesgo aceptado | cubierto |
  | 20 | `tests/test_substitutions_rules.py`: `canonical order uses minute then added minute then acta index`, `on field state does not depend on the input event order`; `test_match_assists.py`: `a goal in the exact minute of the substitution follows the canonical order` | cubierto |
  | 21 | Por inspección: el catálogo se valida en el DTO (sin consultas) y `validate_assist_player` reutiliza el estado en campo del *replay*; la única consulta nueva (`_validate_event_team_scope`) solo corre si un evento nombra un equipo no participante y no es por evento. **Sin prueba de conteo de consultas** | cubierto por inspección (sin prueba automatizada) |
  | 22 | `git diff backend/app` sin acciones auditadas, eventos de outbox ni canales nuevos; `test_match_assists_db.py`: `the assist never changes result standings sanctions or outbox` | cubierto |
  | 23 | `AGENTS.md` (catálogo por tipo, asistencia, cierre de `metadata`, `client_event_id` UUID, 026 y su orden) y `README.md` («Eventos del acta y asistencias» y runbook de la 026); `verify_version_sources.py --exclude-constitution` 0 | cubierto |

## Correcciones tras la validación (2026-10-25)

Ronda 1 de validación: `CAMBIOS NECESARIOS` (4 bloqueantes/importantes y 5 menores). Correcciones aplicadas:

| Hallazgo | Corrección | Evidencia |
|---|---|---|
| **B1** (bloqueante) el botón «Añadir evento» se perdió al sustituir esa línea por los avisos de ayuda; `addEvent()` quedó sin invocador | Botón restaurado con su `:disabled` (incluido el caso de sustitución) junto a los avisos | `frontend/app/pages/workspace/matches/[id].vue` (`@click="addEvent"`); prueba de alta en `frontend/tests/match-events.test.ts`; el hito `event-at-limit` del E2E lo recorre de punta a punta |
| **I1** el acta no mostraba el equipo beneficiado del autogol ni la clase de roja | `eventSummary` distingue autogol (autor + beneficiado) y roja directa/doble amarilla, con textos i18n es/en | `frontend/app/utils/matchEvents.ts`; pruebas de resumen por tipo |
| **I2** faltaba el intervalo del segmento y el error no se asociaba al campo | `SegmentMinuteIssue` (`before_segment`/`after_segment`) y `aria-invalid`/`aria-describedby` por campo con `role="alert"` | `matchEvents.ts` + `[id].vue`; la prueba que **exigía la ausencia** de esos atributos se invirtió |
| **I3** los obligatorios no se marcaban | Marca por tipo con `isEventFieldRequired` (el asistente sigue opcional) | `[id].vue`; pruebas de obligatorios por tipo |
| **I4** la spec afirmaba que el arnés E2E no ejercita el acta | Corregido en `spec.md` (RNF-005) y en la nota de T13: el proyecto `operation-flow` **sí** cubre el alta y el cierre, y su veredicto se exige | este registro + E2E verde |
| **M1** el criterio 19 citaba una prueba de auditoría inexistente | Declarado como inspección del cierre (`dto.model_dump` en la auditoría), sin atribuirlo a una prueba | fila 19 de la tabla |
| **M4** el selector de asistente usaba la plantilla del torneo | Usa la alineación, igual que el selector de jugador | `[id].vue` (`assistCandidates`) |
| **M5** `match.addEvent` quedaba huérfana | Vuelve a usarse con la restauración del botón | catálogo es/en |

**Verificación final de la ronda 1:** frontend `pnpm test` **587 passed / 0 failed** (eran 580) y `pnpm run typecheck` 0. La ronda 2 añade una prueba y cierra en **588 passed / 0 failed** (abajo).

**E2E (`pnpm run e2e:test`, 2026-10-25): `RESULTADO: VERDE (0)`** — 5/5 pruebas, 1.8 min. Vistas `public`, `workspace`, `operation` y `operation-flow` en `passed`; `operation-flow` recorrió 31 hitos, entre ellos `event-at-limit`, `event-limit-announced` y `report-closed`.

**Dos incidencias de entorno, ajenas al código de la spec:**
- Tras el `pnpm run build` de T13 el servidor de desarrollo sirvió hidratación inconsistente (sin socket ni datos en el Workspace); reiniciar `web` lo resolvió, como advierte `MEMORY.md`.
- El arnés E2E **no limpia** los torneos «Copa E2E» que crea. Con el listado paginado a 50, 50 corridas acumuladas llenaron la primera página y ocultaron el torneo demo, haciendo fallar `entrada-sin-paso-normalizada`. Se limpiaron los 50 torneos de prueba; **conviene corregir el arnés en un cambio propio** porque es un *required check*.

## Correcciones tras la segunda validación (2026-10-25)

Ronda 2: `CAMBIOS NECESARIOS` (un hueco real de accesibilidad, una prueba incompleta y registros documentales que afirmaban lo contrario de lo implementado). Es la última vuelta.

| Hallazgo | Corrección | Evidencia |
|---|---|---|
| **A1** (RNF-007) el cambio de tipo de evento no se anunciaba: solo `goal`, `foul` y `substitution` tenían región viva, y al pasar a `own_goal`, `red_card`, `penalty_goal` o `yellow_card` el formulario cambiaba sus campos en silencio | Región `role="status"` **siempre montada** en el formulario (no nace con el cambio, que así no se anunciaría) con el tipo y los campos que muestra, por i18n es/en (`match.eventTypeChanged`); los siete tipos, no solo tres | `frontend/app/utils/matchEvents.ts` (`eventTypeAnnouncement`) y `[id].vue` (`eventTypeNotice`); `frontend/tests/match-events.test.ts`: `a change of event type is announced with the fields it shows` (siete tipos, texto distinto por tipo, región no condicionada, claves es/en con `{type}` y `{fields}`); la prueba falla si se retira el anuncio (comprobado) |
| **A2** `added_minute` tenía `aria-invalid`/`aria-describedby` que ningún camino activaba: el tope combinado se colgaba solo de `minute` | El añadido con problema propio (`reason === 'added'`: no entero o por encima de su tope) se queda en `added_minute` con `match.addedMinuteOutOfRange`; el exceso combinado sigue junto a `minute`, que es el campo que lo nombra. Se conserva el atributo porque ahora tiene camino real, en vez de retirarlo | `[id].vue:addEvent`; `every registration error is associated with its field` recorre ya los once controles, incluidos `event_type`, `red_card_type` y `added_minute` |
| **D1** la fila 6 de la tabla afirmaba que **no** había asociación por campo y remitía a una desviación inexistente | Fila reescrita: los errores se asocian con `aria-invalid`/`aria-describedby` y mensaje `role="alert"`, citando `every registration error is associated with its field`, `the minute must fall inside the selected segment when it has an end` y la prueba nueva del anuncio | fila 6 de la tabla de trazabilidad |
| **D2** `plan.md` decía que `pnpm run e2e:test` no se citaba porque no ejercita el acta | Corregido: el proyecto `operation-flow` **sí** recorre el alta y el cierre; su veredicto se exige y se registra | `plan.md` §13 |
| **D3** recuentos desfasados: frontend **580** y backend con base **1916** | Unificados con la corrida final: frontend **588**, backend sin base **1575**, backend con base **1917** | T11 (cifra histórica contextualizada) y T13 |
| **D4** la fila del criterio 1 no citaba la prueba del arreglo de I3 | Añadida `the catalog marks the required fields and never the optional assistant` | fila 1 |
| **D5** la fila del criterio 19 declaraba «por inspección» una comprobación que **sí** tiene prueba | Evidencia corregida a `backend/tests/test_match_assists_db.py` → `test_the_close_audit_keeps_the_assist_uuid_without_names` (audita el UUID y ningún nombre, documento ni fecha) | fila 19 |

**Verificación de la ronda 2:** `docker compose exec -T web pnpm test` **588 passed / 0 failed**; `docker compose exec -T web pnpm run typecheck` **0**; el backend no cambia (**1575** sin base). `pnpm run e2e:test` **no ejecutado** en esta ronda: el único cambio de plantilla es la región viva nueva y el resto es lógica de validación del formulario, así que no se toca ningún recorrido del escenario; la corrida verde de la ronda 1 sigue siendo la evidencia del `operation-flow`.

## Correcciones tras la segunda validación (2026-10-25)

Segunda ronda: `CAMBIOS NECESARIOS` con un IMPORTANTE y cuatro menores. **Veredicto final: `APROBADO`.**

| Hallazgo | Corrección | Evidencia |
|---|---|---|
| **IMPORTANTE — RNF-007: el cambio de tipo no se anunciaba** (fallaba en `own_goal`, `red_card`, `penalty_goal` y `yellow_card`) | `eventTypeAnnouncement` + `EVENT_FIELD_LABEL_KEYS`, región `role="status"` **siempre montada** y clave `match.eventTypeChanged` (es/en): «Tipo de evento: {type}. El formulario muestra: {fields}.» | `a change of event type is announced with the fields it shows` (los siete tipos); verificado por mutación: falla al retirar la región, al no anunciar los campos, al condicionarla con `v-if` y al anunciar solo tres tipos |
| **`added_minute` con ARIA inerte** | Se le dio camino real: `reason === 'added'` → `setEventFieldIssue('added_minute', 'match.addedMinuteOutOfRange')`; `combined` sigue en `minute` (ramas excluyentes, sin duplicar el anuncio ni cambiar la regla) | `every registration error is associated with its field`, ampliada a los once controles |
| **`tasks.md` fila 6 afirmaba lo contrario** | Reescrita: afirma la asociación por campo y cita las pruebas reales; sin «salvedad» ni «desviación» | fila 6 |
| **`plan.md` mantenía la frase falsa sobre el E2E** | Corregida: el proyecto `operation-flow` recorre el alta y el cierre, y su veredicto se exige | `plan.md` §13 |
| **Recuentos y evidencias desfasados** (fila 1, fila 19) | Unificados a la corrida final: frontend **588**, backend **1575** sin base y **1917** con base; fila 19 cita la prueba real de auditoría | filas 1 y 19 |

**Verificación final ejecutada (2026-10-25), en el estado final del árbol:**

- `pnpm test` **588 passed / 0 failed**; `pnpm run typecheck` 0.
- Backend: **1575 passed / 342 skipped** sin base y **1917 passed** con base; `compileall` 0.
- `pnpm run build` 0 (con `web` detenido y reiniciado).
- **E2E `pnpm run e2e:test`: `RESULTADO: VERDE (0)`** — 5/5 pruebas, 1.9 min; `public`, `workspace`, `operation` y `operation-flow` en `passed`; `operation-flow` recorrió los 31 hitos (`event-at-limit`, `event-limit-announced`, `report-closed`, `roster-create-locked`).

**Fragilidad del arnés E2E detectada durante la validación (ajena a esta spec, merece cambio propio):**

1. **No limpia** los torneos «Copa E2E» que crea: con el listado paginado a 50, 50 corridas acumuladas ocultan el torneo demo y `entrada-sin-paso-normalizada` falla.
2. **`short_code` derivado de los 4 últimos dígitos del reloj**: dos corridas seguidas colisionan y el alta masiva responde «Uno o más códigos de equipo ya existen en la organización». Ocurrió en esta validación con 104 equipos acumulados.
3. **`.nuxt` compartido con el servidor de desarrollo**: un `pnpm run typecheck`/`build` concurrente refresca plantillas bajo el servidor vivo y provoca `view-timeout` en mitad del escenario. Estas dos últimas causas produjeron dos corridas rojas que **no** eran defectos del código.

Por eso el E2E de este cierre se ejecutó **en exclusiva**, con la pila reiniciada y sin residuos de corridas anteriores.
