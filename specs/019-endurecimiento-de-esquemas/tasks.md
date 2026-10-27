# Tareas 019 — Endurecimiento de esquemas de petición

Plan: `specs/019-endurecimiento-de-esquemas/plan.md`. Spec aprobada el 2026-10-26.
**Sin migración:** ninguna tarea crea ni edita archivos de `infra/postgres/`; el esquema, la RLS
y los datos quedan idénticos (RNF-005). La cadena es: modelos por bloques → barrido completo →
precedencia → regresión → cliente → documentos → verificación.

**10 tareas.** T1-T3 endurecen los modelos por módulo (11 + 14 + 9 = 34); T4 convierte el
barrido en la garantía completa; T5 fija la precedencia medida; T7-T8 son el cliente (pueden
correr en paralelo con T1-T6); T10 cierra con E2E y evidencia. Cada tarea empieza por la prueba
en rojo y termina en verde.

**Entorno:** backend dentro del contenedor `api` (`docker compose exec -T api pytest -q …`,
que ya trae pytest); frontend dentro del contenedor `web`
(`docker compose exec -T web pnpm …`, que es donde está el Node con TypeScript). Ninguna tarea
**crea** pruebas que necesiten `RUN_DATABASE_TESTS=1`: todo el alcance nuevo es puro (plan §7);
T10 sí ejecuta, como regresión exigida por RNF-006, las suites opt-in con base existentes. Si una
prueba **nueva** reclamara BD, es un defecto de la prueba.

---

- [x] **T1. Modelos de identidad, invitaciones, organizaciones y plataforma + esqueleto del barrido.** RF-001, RNF-006
  - **Primero, crear** `backend/tests/test_request_schema_strictness.py` en rojo, con los ayudantes puros del plan §4: `walk_routes` (recursión por `_IncludedRouter.original_router.routes`), `body_model` (anotación en `field_info.annotation`, desenredando `list[T]`/`Optional[T]`), el inventario literal de las **33** operaciones JSON y `minimal_valid_body(model)`. En esta tarea el módulo comprueba: (a) el barrido contra `app.main.api` devuelve **exactamente** las 33 operaciones del inventario (ni una de más —las 3 multipart no aparecen—, ni una de menos) y **29** modelos de primer nivel + **5** anidados; (b) la bandera y el rechazo para los **11** modelos de este bloque, con la lista de corte `STRICT_MODELS` que crece en T2 y T3.
  - Después añadir `model_config = ConfigDict(extra="forbid")` a los **11** modelos: `identity/schemas.py` (`RegisterRequest`, `LoginRequest`, `GoogleStartRequest`), `invitations/schemas.py` (`CreateInvitationRequest`, `UpdateMemberRoleRequest`, `UpdateMemberActiveRequest`, `AcceptInvitationRequest`), `organizations/schemas.py` (`OrganizationCreateRequest`) y `platform/schemas.py` (`OutboxReprocessRequest`, `CreateMembershipRequest`, `SetActiveRequest`). Sin tocar sus campos, validadores ni modelos de respuesta.
- Hecho cuando: `docker compose exec -T api pytest -q tests/test_request_schema_strictness.py` verde; `docker compose exec -T api pytest -q` verde; y la prueba es **sensible**: quitando la bandera de un modelo (por ejemplo `RegisterRequest`) su caso se pone rojo.

- [x] **T2. Modelos de torneos y cierre del primer nivel de `rules_config`.** RF-001, RF-003, RF-004
  - **Primero**, en rojo: (a) ampliar `test_request_schema_strictness.py` con la bandera y el rechazo de los **14** modelos de este bloque en `STRICT_MODELS`; (b) ampliar `backend/tests/test_rules_config_compat.py` con los tres casos de RF-003 y RF-004: un `rules_config` con una clave no declarada en el primer nivel → **422** (hoy se descarta en silencio: es el cambio de comportamiento visible), `transfers` sigue **aceptado** y sigue promoviendo `roster_lock_matchday`, y un `stage_overrides` con claves internas arbitrarias sigue **tolerado**.
  - Después añadir la bandera a: `rules_engine/schemas.py` (`CreateTournamentRequest`, `UpdateRulesConfigRequest`, `TournamentRulesConfig`) y `tournaments/schemas.py` (`CreateTournamentTeamRequest`, `BulkTournamentTeamRequest` + `BulkTournamentTeamItem`, `CreateStageRequest`, `AssignStageTeamsRequest`, `CreateMatchRequest`, `GenerateSingleEliminationRequest`, `CreateDraftVersionRequest`, `CreateRosterPlayerRequest`, `UpdatePhotoConsentRequest`, `UpdateRosterStatusRequest`). En `TournamentRulesConfig` **no** se toca el `model_validator(mode="after")` ni la promoción de `transfers` (plan §6 D-2); los bloques internos siguen siendo `dict[str, Any]`.
- Hecho cuando: `docker compose exec -T api pytest -q tests/test_request_schema_strictness.py tests/test_rules_config_compat.py` verde; `docker compose exec -T api pytest -q` verde; `grep -n 'extra="forbid"' backend/app/modules/rules_engine/schemas.py backend/app/modules/tournaments/schemas.py | wc -l` devuelve **14** (3 + 11).

- [x] **T3. Modelos de partido y comentario del catálogo de eventos.** RF-001, RF-002, RF-008, RNF-007
  - **Primero**, en rojo: (a) ampliar `STRICT_MODELS` con los **9** modelos de este bloque en `test_request_schema_strictness.py`; (b) ampliar `backend/tests/test_match_events_contract.py` con la no regresión del catálogo: un `goal` con `assist_player_id` y un `red_card` con `metadata.red_card_type` siguen siendo **válidos** (la asistencia y el `metadata` declarado no son «claves extra»).
  - Después añadir la bandera a `matches/schemas.py`: `SaveMatchLineupRequest`, `PublishMatchLineupRequest`, `OfficialAssignmentRequest`, `CreateMatchSegmentRequest`, `InterruptMatchSegmentRequest`, `CloseMatchReportDTO`, `MatchTeamLineupConfig`, `MatchLineupEntry`. `MatchEventPayload` **ya** la tiene (línea 80): solo se actualiza su comentario para decir que `extra="forbid"` ya no es una excepción justificada por el catálogo sino la regla general de toda petición (RNF-007), sin tocar `client_event_id` ni `metadata`.
- Hecho cuando: `docker compose exec -T api pytest -q tests/test_request_schema_strictness.py tests/test_match_events_contract.py` verde; `docker compose exec -T api pytest -q` verde; `grep -c 'extra="forbid"' backend/app/modules/matches/schemas.py` devuelve **9**.

- [x] **T4. Barrido completo: biyección, bandera y rechazo en los 34 modelos.** RF-001, RF-002, RNF-002, RNF-006
  - **Primero**, en rojo: sustituir la lista parcial `STRICT_MODELS` por los **34** modelos derivados del inventario y añadir el rechazo parametrizado: `model_validate(minimal_valid_body(model) | {"extra": 1})` lanza `ValidationError` con `type == "extra_forbidden"`, `loc == ["extra", …]` y conservando el valor rechazado solo dentro del error de Pydantic (el saneado de la API lo retira, T5). Un modelo de primer nivel sin bandera, un anidado sin bandera y una operación JSON sin modelo Pydantic deben fallar con mensaje explícito.
  - Sin cambios de producción en esta tarea: es la garantía de que T1-T3 no dejó nada fuera y de que la desviación futura (endpoint nuevo o modelo nuevo) se detecta aquí.
- Hecho cuando: `docker compose exec -T api pytest -q tests/test_request_schema_strictness.py` verde con los 34 casos; `docker compose exec -T api pytest -q` verde; y la prueba es **sensible**: revertiendo la bandera de `TournamentRulesConfig` o de `BulkTournamentTeamItem` (los dos más fáciles de olvidar) al menos un caso se pone rojo.

- [x] **T5. Precedencia y forma saneada del 422.** RF-009, RF-010
  - **Primero**, en rojo: en `test_request_schema_strictness.py`, un subconjunto HTTP representativo (reglas, creación de torneo, alta en roster, evento de partido) con `httpx.ASGITransport` sobre `app.main.api` y `dependency_overrides`, replicando el orden medido en el plan §6 D-4: dependencia de membresía que lanza 403 + cuerpo inválido → **403**; sin sesión → **401**; cabecera de organización inválida → **400**; recurso ajeno resuelto en el handler + cuerpo inválido → **422** (gana el cuerpo); cuerpo inválido + permiso denegado dentro del handler → **422**. En todos los 422: `{"detail": [ {type, loc, msg} ]}`, **sin** `code` y **sin** `input`/`ctx`.
  - Sin tocar `backend/app/main.py`: el handler `_request_validation_exception_handler` (líneas 601-624) y `VALIDATION_ERROR_FIELDS` (línea 67) **no cambian**; si la prueba los toca, el saneado se rompió.
- Hecho cuando: `docker compose exec -T api pytest -q tests/test_request_schema_strictness.py` verde; `git diff backend/app/main.py` está **vacío**; `docker compose exec -T api pytest -q` verde.

- [x] **T6. Regresión de la suite y ajuste de expectativas legítimas.** RF-007, RF-008, RNF-004(e)
  - Ejecutar la suite completa del backend. Revisar una a una las pruebas que fallen: si la expectativa cambió por la 019 (por ejemplo una prueba que enviaba una clave extra y esperaba éxito), se actualiza **citando el RF** en el docstring; si no, el fallo es un defecto del cambio y se corrige el modelo. Comprobar en particular `test_match_events_contract.py`, `test_match_assists.py`, `test_rules_config_compat.py`, `test_substitutions.py`, `test_walkover.py`, `test_close_validation_order.py`, `test_sanctions.py` y los contratos públicos (`test_public_player_views.py`, `test_crest_public.py`): ninguno debe cambiar de significado.
  - No se toca ninguna prueba de migración ni ningún archivo de `infra/`: el esquema no cambia.
- Hecho cuando: `docker compose exec -T api pytest -q` verde sin omisiones nuevas injustificadas; `git diff --stat backend/tests` solo muestra archivos justificados por RF; `git diff --stat infra` está **vacío**.

- [x] **T7. Constructores puros de los cuatro cuerpos del cliente.** RF-005, RNF-004(b)
  - **Primero, crear** `frontend/tests/request-bodies.test.ts` en rojo (`node --test`, patrón de `tests/match-close.test.ts`): cada constructor devuelve **exactamente** las claves declaradas del DTO (`Object.keys(...).sort()`), ignora las claves ajenas del formulario de entrada, no muta su argumento y produce el objeto esperado para un caso de cada uno.
  - Después crear `frontend/app/utils/requestBodies.ts` con `buildRosterPlayerBody`, `buildInviteMemberBody`, `buildOfficialAssignmentBody` y `buildTournamentDraftBody` (plan §9), con tipos de entrada explícitos (sin `any`) y sin acceso a `reactive`, `request` ni efectos. `buildCloseReportBody` (`utils/matchClose.ts:296`) **no** se toca: es el patrón que se replica.
- Hecho cuando: `docker compose exec -T web pnpm test` verde con el archivo nuevo; `docker compose exec -T web pnpm run typecheck` sale 0; los constructores no importan nada de `vue` ni de `#app`.

- [x] **T8. Cableado de las cuatro páginas y verificación del frontend.** RF-005, RNF-004(b)
  - Consumir los constructores en `pages/workspace/tournaments/[id]/rosters.vue` (`createPlayer`), `pages/workspace/members.vue` (`inviteMember`), `pages/workspace/matches/[id].vue` (`assignOfficial`) y `pages/workspace/index.vue` (`createTournament`), sustituyendo la expansión del `reactive()` en el `body`. Sin cambios de UI, de i18n ni de `useApi.ts`; los formularios siguen siendo reactivos, solo cambia lo que se serializa.
  - Comprobar que ninguna página del Workspace queda expandiendo un `reactive` en un `body`: `grep -rn "body: { \.\.\." frontend/app/pages` no debe devolver ninguno de los cuatro patrones endurecidos.
- Hecho cuando: `docker compose exec -T web pnpm test` verde; `docker compose exec -T web pnpm run typecheck` sale 0; `docker compose exec -T web pnpm run build` sale 0; el `grep` anterior no devuelve los cuatro patrones.

- [x] **T9. Documentación de la regla general y de la excepción multipart.** RNF-007, RF-012
  - `AGENTS.md`: entrada en «Límites del Proyecto» (toda petición JSON rechaza claves no declaradas con 422 sin `code`, la primera clave de `rules_config` también, y las **tres operaciones multipart** quedan fuera: `POST …/rosters/bulk`, `POST …/rosters/{id}/photo`, `POST …/teams/{id}/crest`) y mención en «Testing» del archivo nuevo `test_request_schema_strictness.py` (puro, sin opt-in).
  - `README.md`: nota breve de compatibilidad (qué deja de aceptarse y por qué un cliente que solo envía campos declarados no nota nada).
  - Comentarios (no docstrings): `TournamentRulesConfig` (primer nivel cerrado, bloques abiertos, `transfers` todavía aceptado) y los comentarios de los modelos cerrados. **No** se toca `docs/contrato-reglas.md` ni `engine_version` 2026.1 (RF-012).
- Hecho cuando: `git diff --stat` muestra `AGENTS.md` y `README.md` además de los archivos de T1-T8; `git diff docs/contrato-reglas.md` está **vacío**; `grep -n "claves no declaradas" AGENTS.md` devuelve la entrada nueva; `python3 infra/scripts/verify_version_sources.py --exclude-constitution` sale 0.

- [x] **T10. Verificación completa, E2E y evidencia.** RF-001 a RF-012, RNF-001 a RNF-011
  - Ejecutar, en este orden: `docker compose exec -T api pytest -q`; `docker compose exec -T api python -m compileall -q app`; `docker compose exec -T web pnpm test`; `docker compose exec -T web pnpm run typecheck`; `docker compose exec -T web pnpm run build`; `docker compose config -q`; `sh -n infra/postgres/migrate.sh` (sin cambios, como prueba de que no hay migración); `python3 infra/scripts/verify_version_sources.py --exclude-constitution`. Después, las suites opt-in con base que exige RNF-006: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_match_resolution_db.py tests/test_match_assists_db.py tests/test_sanctions_db.py tests/test_substitutions.py tests/test_roster_lock.py tests/test_invitations.py tests/test_organizations_create_db.py` (cierre; configuración y plantillas; invitaciones y organizaciones); si el entorno no permite la base, se declaran **no ejecutadas**, nunca verdes.
  - E2E en **exclusividad** (sin `typecheck`/`build`/servidor de desarrollo concurrentes: comparten `.nuxt`), limpiando los residuos de «Copa E2E» acumulados y con la pila y los datos demo levantados: `cd frontend && pnpm run e2e:test`. El cambio toca la pantalla de operación (`assignOfficial`) y las pantallas de plantillas, miembros y workspace, así que el escenario `operation-flow` es la ruta que debe seguir verde.
  - Recorrer los criterios de finalización de la spec y anotar, criterio por criterio, el archivo y el nombre del caso que lo respalda; rellenar la tabla de evidencia de abajo. Lo que no se pueda ejecutar se declara **no ejecutado**, nunca verde.
- Hecho cuando: todos los comandos salen 0, el E2E termina con **0** y las vistas en `passed` (un **1** es fallo de comportamiento y se corrige el código; **2**, de infraestructura; **3**, corrida inválida), la tabla de evidencia queda completa y `git status --porcelain infra` está vacío.

---

### Evidencia de T10 — Verificación del conjunto (ejecutada el 2026-10-26; nada sin ejecutar)

| # | Comando | Resultado |
|---|---|---|
| 1 | `docker compose exec -T api pytest -q` | **23 failed / 2023 passed / 432 skipped** — falsos negativos de entorno (el contenedor no ve la raíz del repo: `AGENTS.md`, `README.md`, `docs/`, `infra/`); repetido con repo montado `docker run --rm -v "$PWD:/repo" -w /repo/backend bracket-craft-api:devtest python -m pytest -q` → **2046 passed / 432 skipped**, exit **0** (resultado autoritativo) |
| 2 | `docker compose exec -T api pytest -q tests/test_request_schema_strictness.py tests/test_rules_config_compat.py tests/test_match_events_contract.py` | **283 passed**, exit **0** |
| 3 | `docker compose exec -T api` + `PYTHONPYCACHEPREFIX=/tmp/pycache python -m compileall -q app` (y equivalente montado) | exit **0** en ambas rutas |
| 4 | `docker compose exec -T web pnpm test` | **644 tests: 643 pass / 1 skip / 0 fail**, exit **0** |
| 5 | `docker compose exec -T web pnpm run typecheck` | exit **0** (imprime un aviso no fatal del plugin volar `vue-router/volar/sfc-route-blocks`) |
| 6 | `docker compose exec -T web pnpm run build` | exit **0** (`Build complete`, 4.38 MB) |
| 7 | `docker compose config -q` | exit **0** |
| 8 | `sh -n infra/postgres/migrate.sh` (sin cambios) | exit **0**; `git status --porcelain infra` **vacío** |
| 9 | `python3 infra/scripts/verify_version_sources.py --exclude-constitution` | exit **0** («Python 3.14, Node 24 y pnpm 12.12.1 coinciden») |
| 10 | E2E exclusivo (`mcr.microsoft.com/playwright:v1.64.1-noble` + `pnpm run e2e:test`, «Copa E2E» limpio antes) | exit **0 — VERDE**, `5 passed` en 5,0 min: setup, public, workspace, operation y **operation-flow**; las cuatro vistas en `passed` (tabla `RESULTADO: VERDE (0)`) |
| 11 | `RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL=… pytest -q` (7 suites opt-in con base: cierre `test_match_resolution_db`/`test_match_assists_db`/`test_sanctions_db`, configuración y plantillas `test_substitutions`/`test_roster_lock`, invitaciones y organizaciones `test_invitations`/`test_organizations_create_db`) | **156 passed / 0 failed**, exit **0** (el primer intento dio 1 fallo por `__pycache__` huérfano con rutas `/repo` horneadas: ver incidencias) |
| 12 | `git status --porcelain infra backend/app frontend/app` | `infra` **vacío**; solo los archivos de T1-T9 (7 schemas + 4 páginas + `requestBodies.ts`) |

### Criterios de finalización → evidencia (16/16 recorridos)

| # | Criterio | Evidencia (archivo :: caso) |
|---|---|---|
| 1 | 422 de primer nivel en las 33 operaciones, sin escribir | `backend/tests/test_request_schema_strictness.py :: test_json_operations_match_the_literal_inventory`, `:: test_strict_models_are_exactly_the_34_models_of_the_literal_inventory`, `:: test_strict_model_rejects_extra_key` (34 casos); sin escritura: los casos HTTP exigen **0 consultas** con el sustituto de sesión (`:: test_handler_permission_403_loses_to_invalid_body_in_tournament_create`, `:: test_handler_resource_404_loses_to_invalid_body_in_roster`) — el handler nunca corre, así que no hay fila, auditoría, outbox, correo ni enlace |
| 2 | 422 anidado recursivo y ubicación | `:: test_strict_model_rejects_extra_key` (los 5 modelos anidados), `:: test_match_event_extra_key_is_sanitized_422` (clave dentro del evento del acta), `backend/tests/test_rules_config_compat.py :: test_key_inside_a_stage_override_is_still_rejected` (bloque: camino en el mensaje, con el validador propio) |
| 3 | Primer nivel de `rules_config` 422, bloques y deprecado intactos | `test_rules_config_compat.py :: test_undeclared_top_level_key_in_rules_config_is_422_at_the_api_boundary`, `:: test_undeclared_top_level_key_is_extra_forbidden_in_the_request_model`, `:: test_deprecated_transfers_block_is_still_accepted_and_promoted`, `:: test_key_inside_a_stage_override_is_still_rejected` |
| 4 | Solo los tres mapas abiertos admiten claves libres | **COMPLETO (I-3 cerrada):** `test_rules_config_compat.py :: test_the_three_open_maps_of_rf004_accept_a_free_key` — **3/3** con el validador propio y la frontera HTTP (200): `[ranking_pipeline[].params]` (y la clave sobrevive en el modelo), `[stage_overrides index]` (índice libre, valor cerrado), `[transfers content]` (aceptado y no reescrito); conservados los casos previos `:: test_stage_overrides_index_is_still_an_open_map` y `:: test_deprecated_transfers_block_is_still_accepted_and_promoted` |
| 5 | Ida y vuelta de la configuración | `test_rules_config_compat.py :: test_valid_configuration_is_accepted_at_the_api_boundary`, `:: test_tournament_rules_model_accepts_320_and_emits_330`, `:: test_320_with_deprecated_blocks_is_valid_and_normalized`, `:: test_320_without_minutes_reads_default_pair_without_rewriting`; los caminos de lectura no revalidan (sin cambios en ellos) |
| 6 | Constructores puros del cliente con `node --test` | `frontend/tests/request-bodies.test.ts :: buildRosterPlayerBody sends exactly the declared roster player keys`, `:: buildInviteMemberBody …`, `:: buildOfficialAssignmentBody …`, `:: buildTournamentDraftBody …`, `:: the four workspace pages import their request body builders`, `:: no hardened page keeps the legacy reactive spread in the body`; `pnpm test` 644 verdes |
| 7 | Multipart, query, cabeceras y sin-cuerpo intactos y declarados | `test_request_schema_strictness.py :: test_multipart_operations_exist_and_stay_out_of_the_inventory`; sin cambios de código en esas rutas (diff solo `model_config`); `test_google_auth.py :: test_retired_google_login_returns_410_without_reading_the_body` (410 conservado) y `test_access_log.py` (11 passed) verdes; riesgo en spec `RNF-011`, `AGENTS.md` línea 48 y `README.md:643` |
| 8 | Sin cambios de respuesta/fila/acta y sin migración | diff de schemas: **solo** `model_config = ConfigDict(extra="forbid")`, import de `ConfigDict` y comentarios (ningún modelo de respuesta); `git status --porcelain infra` **vacío**; suite completa 2046/432 verdes (contratos públicos y actas incluidos) |
| 9 | 422 del acta, catálogo, 409 con `code`, coherencia numérica, orden de 14 pasos, walkover y límites intactos | suite completa verdes: `test_walkover.py`, `test_walkover_close.py`, `test_close_validation_order.py`, `test_sanctions.py`, `test_match_events_contract.py`, `test_rules_config_compat.py`; opt-in **156 passed**: `test_match_resolution_db.py`, `test_match_assists_db.py`, `test_sanctions_db.py`, `test_substitutions.py`, `test_roster_lock.py` |
| 10 | Precedencia por capas | `test_request_schema_strictness.py :: test_invalid_content_length_400_precedes_body_in_rules`, `:: test_oversized_content_length_413_precedes_body_in_tournament_create`, `:: test_disallowed_origin_403_precedes_body_in_tournament_create`, `:: test_missing_session_401_precedes_body_in_roster`, `:: test_missing_organization_header_400_precedes_body_in_tournament_create`, `:: test_membership_dependency_403_precedes_body_in_rules`, `:: test_platform_admin_dependency_403_precedes_body`, `:: test_handler_resource_404_loses_to_invalid_body_in_roster`, `:: test_handler_permission_403_loses_to_invalid_body_in_tournament_create` |
| 11 | Forma del error sin `code` ni eco del valor y sin rastro en logs | `test_request_schema_strictness.py :: assert_sanitized_validation_error` (usado en todos los casos HTTP: `set(payload) == {"detail"}`, sin `input`/`ctx`, `REJECTED_VALUE not in response.text`); `backend/tests/test_access_log.py` (el log registra solo método/ruta/estado, sin cuerpo) |
| 12 | Sin lecturas/escrituras propias ni sesgo por organización | sustituto determinista de `AsyncSession` que registra consultas (`test_request_schema_strictness.py` líneas 863-891): los 422 exigen la lista **vacía**; los casos corren sin BD ni datos de organización (RF-011) |
| 13 | Sin superficie nueva; `engine_version` 2026.1 | `python3 infra/scripts/verify_version_sources.py --exclude-constitution` exit **0**; `test_rule_contract.py` y `test_version_source.py` verdes en la corrida **montada** (en la del contenedor son parte de I-1); diff sin routers, permisos ni outbox; `git diff docs/contrato-reglas.md` **vacío** (`engine_version` sigue en 2026.1) |
| 14 | Barrido de comportamiento por modelo **y por bloque** + tres mapas abiertos | **COMPLETO (I-3 cerrada):** modelos — `test_request_schema_strictness.py :: test_inventory_has_33_literal_operations`, `:: test_json_operations_match_the_literal_inventory`, `:: test_app_yields_29_top_level_and_5_nested_models`, `:: test_strict_models_are_exactly_the_34_models_of_the_literal_inventory`, `:: test_json_operation_without_pydantic_model_fails_with_explicit_message`, `:: test_strict_model_rejects_extra_key`; bloques — `test_rules_config_compat.py :: test_every_closed_block_of_rules_schema_has_a_rejection_case` (lista literal `CLOSED_BLOCK_PATHS` frente a los caminos derivados de `RULES_SCHEMA`: falla con mensaje que nombra los bloques sin caso si el esquema añade uno) y `:: test_extra_key_in_a_closed_block_is_rejected_by_its_own_validator` (**10 casos**: `<root>`, `points_system`, `ranking_pipeline[]`, `substitutions`, `discipline`, `discipline.fair_play_penalties`, `stage_defaults`, `stage_defaults.walkover_score`, `stage_overrides{}`, `stage_overrides{}.walkover_score`; cada uno exige rechazo en `validate_rules_config` nombrando la clave y la ruta, en `TournamentRulesConfig` y **422** en la frontera HTTP); mapas abiertos — `:: test_the_three_open_maps_of_rf004_accept_a_free_key` (**3 casos**, fila 4) |
| 15 | Comandos todos en 0 y E2E 0; lo no ejecutado declarado | Tabla de evidencia: filas 1-12 todas en **0** (o recuento verde), E2E veredicto **0**; **nada quedó sin ejecutar** (salvo `infra/scripts/test_migrate_target.sh`, prohibido por la consigna de T10 y no exigido por RNF-006) |
| 16 | Documentación en todas sus copias + entrada en «Contratos que cambian» | `AGENTS.md` línea **47** (entrada **019** en «Contratos que cambian» con la declaración de RNF-004) y línea **48** («Claves no declaradas en el cuerpo (spec 019)»); `README.md:643` (nota de compatibilidad); comentarios de `TournamentRulesConfig` y `MatchEventPayload` (diff T3/T9); `docs/contrato-reglas.md` sin cambios (`engine_version` 2026.1) |

### Incidencias de T10 (declaradas, ninguna verde tapada)

- **I-1 — Falsos negativos de entorno en la suite del contenedor.** `docker compose exec -T api pytest -q`
  dio 23 failed por ficheros de raíz que el contenedor no monta (`AGENTS.md`, `README.md`, `docs/`,
  `infra/`). Resultado autoritativo: la misma suite con el repo montado → **2046 passed / 432 skipped**.
- **I-2 — Primer intento de las opt-in con 1 fallo por `__pycache__` huérfano.**
  `test_invitations.py::test_member_without_role_is_rejected_before_the_handler` falló en
  `inspect.getsource` (`OSError: could not get source code`) porque una corrida montada
  (`/repo/backend`) dejó `.pyc` con la ruta `/repo` horneada y el contenedor (`/app`) los reutilizó.
  Causa ambiental, sin código de producto ni de pruebas involucrado: se borraron los `__pycache__`
  (ignorados por git) del árbol `backend/` y el lote se repitió → **156 passed / 0 failed**.
- **I-3 — Criterio 14 parcial (y con él el mapa `params` del criterio 4).** El barrido de
  RNF-006 cubre los **34 modelos** con garantía de fallo explícito, pero **no hay caso commiteado**
  que inyecte una clave de más en **cada bloque cerrado** de `rules_config`
  (`points_system`, `ranking_pipeline`, `substitutions`, `discipline`, `stage_defaults`,
  `walkover_score`) usando el validador propio, ni un caso de **aceptación** del mapa abierto
  `params` de los desempates (los otros dos mapas sí están probados). El **comportamiento en
  producción es correcto** —verificado en esta corrida con `validate_rules_config` contra
  `DEFAULT_RULES_CONFIG`: 6/6 bloques rechazan la clave extra y 3/3 mapas abiertos la aceptan—;
  lo que falta es la **regresión automatizada** que haría fallar la suite si alguien abriera un
  bloque o cerrara `params`. T10 no añade pruebas (es verificación), así que queda declarado
  para decisión del cierre: tarea aparte o aceptación del riesgo.
  **Cerrada el 2026-10-26 (cierre de la laguna de T10):** se añadió el barrido por bloque en
  `backend/tests/test_rules_config_compat.py` —lista literal `CLOSED_BLOCK_PATHS` comparada con
  los caminos derivados de `RULES_SCHEMA`, **10** casos de rechazo (motor + modelo + frontera
  422) y los **3** mapas abiertos aceptando clave libre—, sin ningún cambio de producción:
  ver «Cierre de I-3» más abajo.
- **`DATABASE_ADMIN_URL` no está en el compose de desarrollo:** para las opt-in (RNF-006) se derivó
  de `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` de `.env` apuntando a `db:5432`
  (rol superuser `postgres`); `RUN_DATABASE_TESTS=1` se pasó con `docker compose exec -e`.
- **Limpieza de residuos E2E:** se borraron antes y después de la corrida los torneos «Copa E2E»
  (2 previos + 1 creado por esta corrida) con su cadena de hijos en una transacción
  (`session_replication_role=replica`, sin DDL persistente) y sus 6 jugadores huérfanos;
  `seed_demo` ejecutado (idempotente). La BD queda con 1 torneo demo, 12 equipos, 167 rosters.
- **No ejecutado (por prohibición explícita de la consigna):** `infra/scripts/test_migrate_target.sh`
  (rota la contraseña; T10 no lo exige). Ninguna otra verificación de T10 quedó sin ejecutar.

### Cierre de I-3 — barrido de comportamiento por bloque (2026-10-26)

Las filas 4 y 14 de la tabla de criterios pasan de **PARCIALES** a **completas**. Pruebas
nuevas, todas en `backend/tests/test_rules_config_compat.py` (el módulo ya importa el
validador propio, `RULES_SCHEMA` y el helper de frontera HTTP; `test_request_schema_strictness.py`
barre modelos de petición derivados de las rutas, y un bloque de `rules_config` no lo es):

| Paso | Comando / acción | Resultado |
|---|---|---|
| 1 | **Rojo inicial:** `docker compose exec -T api pytest -q tests/test_rules_config_compat.py -k "closed_block or own_validator"` con `CLOSED_BLOCK_PATHS` sembrado solo con los dos bloques que ya tenían caso commiteado (`<root>`, `stage_overrides{}`) | **1 failed**: `test_every_closed_block_of_rules_schema_has_a_rejection_case` listó **8** bloques sin caso — `discipline`, `discipline.fair_play_penalties`, `points_system`, `ranking_pipeline[]`, `stage_defaults`, `stage_defaults.walkover_score`, `stage_overrides{}.walkover_score`, `substitutions`. Los 2 casos de comportamiento ya existentes pasaron: la producción ya rechazaba, lo que faltaba era la regresión |
| 2 | **Verde sin tocar producción:** `docker compose exec -T api pytest -q tests/test_rules_config_compat.py tests/test_request_schema_strictness.py` | **228 passed**, exit **0** (107 + 121; **14** casos nuevos: 1 de cobertura + 10 de bloque + 3 de mapas abiertos) |
| 3 | Suite completa con repo montado: `docker run --rm -v "$PWD:/repo" -w /repo/backend -e PYTHONDONTWRITEBYTECODE=1 bracket-craft-api:devtest python -m pytest -q` | **2060 passed / 432 skipped**, exit **0** (+14 frente a los 2046 de T10) |
| 4 | **Sensibilidad:** retirar `"additionalProperties": False` del bloque `substitutions` en `backend/app/modules/rules_engine/engine.py` | **2 failed**: `…own_validator[substitutions]` y `test_every_closed_block_of_rules_schema_has_a_rejection_case` («casos sin bloque en el esquema: [`substitutions`]»); 105 passed |
| 5 | Reversión de la sensibilidad | `git diff backend/app/modules/rules_engine/engine.py` **vacío**; `git diff --stat backend/app` sigue siendo solo los 7 `schemas.py` de T1-T3 |

**Qué capa cierra cada bloque (medida, no supuesta).** `validate_rules_config` (jsonschema
contra `RULES_SCHEMA`) rechaza las 10 rutas nombrando clave y ruta; `TournamentRulesConfig`
también rechaza las 10, pero porque su `model_validator(mode="after")` llama a
`normalize_rules_config` → `validate_rules_config`, no porque los bloques estén declarados
(son `dict[str, Any]`/`list[dict[str, Any]]`); la frontera HTTP devuelve **422** en las 10
(caso límite 26) y **200** en los 3 mapas abiertos. Solo el `<root>` produce
`type: extra_forbidden` (bandera `extra="forbid"`); los bloques producen `value_error` con el
mensaje del motor.

### T11 — cobertura del caso límite 20 y de la dependencia real de membresía (2026-10-26)

Solo pruebas, en `backend/tests/test_request_schema_strictness.py` (puras, sin base ni opt-in); producción, docs y specs intactos.
- `test_read_only_platform_admin_422_on_extra_key_and_403_on_valid_body` (caso límite 20, RF-009): `get_platform_context` devuelve `role_code="platform_support"`; `POST /platform/outbox/reprocess` con clave de más → **422** saneado (sin `code`, sin eco, sin consultas), con cuerpo válido → **403** «Permiso de escritura de plataforma requerido» (`require_platform_write` en el manejador).
- `test_real_membership_dependency_403_precedes_body_in_rules`: `get_auth_context` **real** (solo se sustituyen `get_current_user_id` y `get_db` por una sesión que responde a las consultas de la dependencia): sin fila de rol → **403** con clave de más; con rol activo → **422** y ninguna consulta fuera de la dependencia.
- **Sensibilidad:** quitar `extra="forbid"` de `OutboxReprocessRequest` y de `UpdateRulesConfigRequest` → **2 failed** (403 y 404 en lugar de 422); restaurado → verde y `git diff backend/app` idéntico al previo (cmp).
- **Comandos** (la pila Compose no estaba levantada, `docker compose exec` → «service "api" is not running»; se usó la imagen `bracket-craft-api:devtest` con el repo montado y `-p no:cacheprovider`): `pytest -q tests/test_request_schema_strictness.py tests/test_rules_config_compat.py tests/test_match_events_contract.py` → **299 passed**; suite completa `docker run --rm -v "$PWD:/repo" -w /repo/backend -e PYTHONDONTWRITEBYTECODE=1 bracket-craft-api:devtest python -m pytest -q` → **2062 passed / 432 skipped** (+2 frente a 2060).
