# Spec 023 — Verificación integral y documentación

Estado: borrador (corregido, pendiente de aprobación del reviewer)

## Contexto y objetivo

Las specs 020, 021 y 022 (y las anteriores) han implementado una cantidad considerable de funcionalidad: consulta pública, formaciones gráficas, estadísticas y porterías imbatidas, actas, segmentos, walkovers, sustituciones, sanciones, acceso con Google, invitaciones, escudos, etc. Parte de esa funcionalidad se ha verificado con pruebas puras y opt-in, pero no existe un programa unificado que asegure, de extremo a extremo, que lo implementado cumple los requisitos funcionales, deportivos, de seguridad y de experiencia de usuario, ni una documentación actualizada al comportamiento real.

**Objetivo:** definir un programa de verificación integral, organizado en bloques verificables, y la actualización de la documentación (README, AGENTS, manual de usuario) para que refleje el comportamiento realmente disponible. No se añade funcionalidad de producto: se verifica y se documenta lo que ya existe.

Esta spec **no** cambia `engine_version` (sigue en 2026.1), no añade migraciones ni endpoints, y no modifica contratos HTTP.

## Usuarios

- Verificador/revisor técnico que ejecuta y valida las suites.
- Mantenedor del proyecto que actualiza documentación.
- Usuario final (aficionado, operador, administrador) beneficiado por un manual alineado con lo disponible.

## Roles y visibilidad

- **Verificador:** ejecuta pruebas en contenedores con los datos demo; no tiene acceso a datos reales fuera del entorno local.
- **Mantenedor:** actualiza README, AGENTS y manual de usuario; no altera código de negocio.
- **Usuario final:** consulta el manual actualizado; no cambian sus permisos.

No aplica cambio de roles ni de visibilidad del producto. Trazabilidad: RF-018 de la spec 020 (la consulta pública no añade ninguna escritura, cookie ni dependencia de sesión) se verifica en RF-018 de esta spec (Bloque D). La matriz de acceso público de la spec 020 (RF-013, RF-014, RF-016, RF-017) es el referente para RF-014 y RF-016 de esta spec.

## Historias de usuario

- HU-1. Como verificador, quiero una lista cerrada y verificable de qué se prueba y con qué herramienta, para no declarar como verificado lo que no se ejecutó.
- HU-2. Como mantenedor, quiero que la documentación refleje el comportamiento real (incluidas las rutas públicas nuevas, la portería imbatida y el acceso con Google), para evitar deriva documental.
- HU-3. Como operador, quiero un manual de usuario con los flujos realmente disponibles (torneos, reglas, fases, equipos, plantillas, calendario, actas, consulta pública), para operar sin sorpresas.
- HU-4. Como revisor, quiero que las pruebas de permisos cubran anónimos, autenticados, roles y accesos cruzados, para garantizar el aislamiento entre organizaciones.

## Definiciones

- **Suite pura:** prueba que no requiere base de datos ni servicios externos (pytest sin `RUN_DATABASE_TESTS`, `node --test`, vitest unitario).
- **Suite opt-in:** prueba que requiere PostgreSQL (y a veces `DATABASE_ADMIN_URL`); se ejecuta con `RUN_DATABASE_TESTS=1` y se declara «no ejecutada» si no hay entorno.
- **Suite E2E:** prueba Playwright sobre la pila Docker completa.
- **Veredicto honesto:** toda declaración de verificación cita el comando ejecutado y su resultado; si no se ejecutó, se declara como no ejecutada, nunca como verde.
- **Manual de usuario:** documento (en README o anexo) con instrucciones operativas para el usuario final, alineado con las pantallas reales.

## Dependencias

Esta spec depende de las specs 015, 016, 017, 018, 019, 020, 021 y 022 (funcionalidad a verificar y documentar) y de la cadena de migraciones hasta 031. No añade funcionalidad nueva ni modifica contratos.

## Inventario de herramientas y comandos por bloque

- Bloque A (RF-001–RF-005): `pytest -q` (sin opt-in), `node --test`, vitest unitario.
- Bloque B (RF-006–RF-011): `RUN_DATABASE_TESTS=1 pytest -q`, `infra/scripts/verify_worker_loop_health.sh`, Docker Compose.
- Bloque C (RF-012–RF-014): Playwright (`pnpm run e2e`/`e2e:test`), vitest, `node --test`.
- Bloque D (RF-015–RF-018): pytest opt-in + suites existentes.
- Bloque E (RF-019–RF-022): pytest (puro y opt-in), fixtures/demo.
- Bloque F (RF-023–RF-024): inspección manual documentada + teclado en E2E.
- Bloque G (RF-025–RF-027): edición de README, AGENTS, `docs/manual-usuario.md`.
- Bloque H (RF-028): trazabilidad de cobertura — lista explícita en T1 de las funciones del inventario backend no cubiertas en esta entrega, con motivo por función (RF-001, RNF-002). Opcional no bloqueante del reviewer.
Nota: «EL SISTEMA» en esta spec se refiere al sistema de pruebas y documentación, no al producto.

## Inventario de sujetos verificables (funciones/servicios/utilidades puras)

Lista cerrada y verificable de los sujetos de RF-001 y RF-002. Cada entrada es un módulo/archivo cuyas funciones son puras (sin base de datos, sesión ni servicios externos) y se ejercitan con `pytest -q` (backend) o `node --test`/vitest (frontend). La columna «Prueba existente» cita el test puro que la cubre hoy («—» = pendiente de añadir en esta entrega).

### Backend (`backend/app`)

| Módulo | Funciones/servicios puros sujetos | Prueba existente |
|---|---|---|
| `app/modules/standings/head_to_head.py` | `_fallback_order`, `calculate_head_to_head_stats`, `resolve_head_to_head` | `tests/test_standings_head_to_head.py` |
| `app/modules/tournaments/public_stats.py` | `_v`, `_has`, `_truthy`, `_match_id`, `_event_match_id`, `_confirmed`, `_final_score`, `_resolution`, `_effective_duration`, `_player_id`, `_match_for_event`, `_events_for_match`, `_segments_for_match`, `_formation_players`, `_is_formation_published`, `_position_slot`, `_is_starter`, `_is_goalkeeper`, `_is_formation_object`, `_as_formation`, `_group_flat_rows`, `_normalize_formations`, `_segment_sort_key`, `published_formations`, `clean_sheet_team`, `_player_minutes`, `goalkeeper_minutes`, `clean_sheet_goalkeepers`, `clean_sheet_goalkeeper`, `_visible_criteria_key`, `_stable_identity`, `_write_rank`, `assign_ranks`, `player_stats_rank_key`, `team_stats_rank_key`, `compute_player_stats`, `compute_team_stats` | `tests/test_public_stats.py` |
| `app/modules/tournaments/pairings.py` | `max_meetings_per_pair`, `pair_limit_detail` | `tests/test_tournament_scheduling.py` |
| `app/modules/tournaments/scheduling.py` | `_validate_team_ids`, `_schedule_date`, `distribute_groups`, `build_round_robin_schedule`, `build_swiss_pairings`, `_next_power_of_two`, `_match_code`, `build_single_elimination_bracket`, `build_double_elimination_bracket` | `tests/test_tournament_scheduling.py`, `tests/test_swiss_budget.py` |
| `app/modules/tournaments/roster_status.py` | `_limit_value`, `_read`, `effective_roster_limits`, `roster_size_state`, `roster_violations`, `_detail_sort_key`, `roster_rows_for_new_teams`, `_limit_label`, `describe_roster_violations` | `tests/test_roster_limits.py` |
| `app/modules/identity/account_rules.py` | `decide_linked_account`, `decide_existing_account`, `decide_link` | `tests/test_google_account_rules.py` |
| `app/modules/identity/google_claims.py` | `_contains_control_characters`, `_is_safe_internal_path`, `validate_return_destination`, `sanitize_display_name`, `_now_timestamp`, `_response_body`, `parse_identity_claims` | `tests/test_google_claims.py` |
| `app/modules/organizations/ordering.py` | `organization_sort_key`, `ordered_organizations` | `tests/test_organizations_*.py` (inspección) |
| `app/modules/crests/validation.py` | `detect_image_type`, `png_declares_animation`, `webp_declares_animation`, `validate_crest_content`, `crest_object_key` | `tests/test_crest_validation.py` |
| `app/modules/invitations/lifecycle.py` | `_as_utc`, `effective_invitation_status`, `reopen_conflict`, `resend_conflict` | `tests/test_invitation_reopen_rules.py` |
| `app/modules/matches/service.py` | `effective_match_minutes`, `maximum_minute_for_resolution`, `resolution_enabled`, `derive_walkover_score`, `validate_event_minute`, `canonical_client_event_id`, `normalize_event_metadata`, `double_yellow_violations`, `next_segment_proposal`, `replay_report_state`, `roster_entries` | `tests/test_match_minutes.py`, `tests/test_match_events_contract.py`, `tests/test_walkover.py`, `tests/test_walkover_close.py`, `tests/test_close_validation_order.py`, `tests/test_double_yellow.py`, `tests/test_sanctions.py` |
| `app/modules/rules_engine/substitutions.py` | `canonical_event_order`, `_valid_entries`, `starter_player_ids`, `has_lineup`, `_close_interval`, `_freeze`, `build_on_field`, `apply_substitution`, `apply_red_card`, `_window_key`, `_sorted_windows`, `team_usage`, `remaining_limits`, `check_substitution_limits`, `validate_substitution`, `validate_player_on_field`, `validate_assist_player`, `validate_roster_minutes`, `segment_balances` | `tests/test_substitutions.py`, `tests/test_substitutions_rules.py` |
| `app/modules/rule_contract.py` | `slots_for_formation`, `requires_decisive_winner` | `tests/test_rule_contract.py` |

### Frontend (`frontend/app/utils`)

Sujetos: todos los archivos `*.ts` de `frontend/app/utils/` (42 archivos): `api.ts`, `format.ts`, `googleAuth.ts`, `i18nCatalog.ts`, `invitationActions.ts`, `invitationErrors.ts`, `labels.ts`, `matchClose.ts`, `matchDraft.ts`, `matchEvents.ts`, `matchNavigation.ts`, `matchResolution.ts`, `matchSegments.ts`, `navigation.ts`, `organizationCreation.ts`, `organizationSelection.ts`, `positions.ts`, `publicLineup.ts`, `publicStats.ts`, `publicTournament.ts`, `realtimeConnection.ts`, `realtimeDedup.ts`, `realtimeDispatch.ts`, `realtimeReload.ts`, `realtimeRetry.ts`, `realtimeStatusLabel.ts`, `requestBodies.ts`, `rosterLimits.ts`, `rosterLock.ts`, `rulesConfig.ts`, `rulesMinutes.ts`, `rulesWizard.ts`, `stageTeams.ts`, `stageWizard.ts`, `substitutions.ts`, `teamCrest.ts`, `teamsWizard.ts`, `tournamentNavigation.ts`, `validation.ts`, `wizardDraft.ts`, `wizardModel.ts`, `wizardStep.ts`.

Pruebas existentes: `frontend/tests/*.test.ts` (vitest) y `node --test` donde aplique; inspección por archivo en el plan.

Consideración: por su tamaño, esta spec puede dividirse en specs más pequeñas por bloque siguiendo el patrón de la spec 011; la división queda a criterio del planificador en la fase de plan.

## Requisitos funcionales

### Bloque A — Pruebas unitarias (servicios de dominio)

- RF-001: CUANDO se evalúe un servicio de dominio puro (validaciones, cálculos estadísticos, transiciones de estado, funciones de utilidad), EL SISTEMA DE PRUEBAS (pytest sin `RUN_DATABASE_TESTS`, `node --test`, vitest unitario) DEBE cubrirlo con una prueba unitaria ejecutable sin base de datos ni servicios externos. Conjunto cerrado de sujetos a cubrir en esta entrega: el inventario de la sección «Inventario de sujetos verificables (funciones/servicios/utilidades puras)» (módulos puros de `backend/app` y los archivos `*.ts` de `frontend/app/utils`), más las funciones puras añadidas por las specs 015, 016, 017, 018, 019, 020, 021 y 022 que aún no tengan prueba. No se añaden servicios nuevos. Toda función del inventario que no tenga prueba al cierre de la entrega se declara «no cubierta (fuera de esta entrega)» con motivo (RNF-002).
- RF-002: CUANDO exista una función pura en `backend/app` (por ejemplo, cálculo de clasificación, desempates, portería imbatida, minutos efectivos, validación de eventos), EL SISTEMA DEBE tener al menos una prueba que fije su resultado esperado para los casos típicos y los casos límite declarados en las specs 015, 016, 017, 018, 019, 020, 021 y 022.
- RF-003: CUANDO exista una función pura en `frontend/app/utils` (navegación de asistentes, normalización de pasos, resolución de `?step=`, filtros de fase), EL SISTEMA DEBE cubrirla con `node --test` o vitest.
- RF-004: CUANDO se modifique un cálculo estadístico (jugador o equipo, incluida la portería imbatida), EL SISTEMA DEBE verificar que el resultado coincide con la definición única de la spec 022 (equipo: partido disputado con cero goles recibidos; portero: `GK` en formación publicada, titular del primer segmento o entrante acreditado, ≥ 60 minutos, sin goles recibidos; walkover y resolución administrativa excluidos).
- RF-005: CUANDO se verifique una transición de estado (segmento activo/completado/interrumpido, partido programado/en juego/finalizado, invitación pendiente/vencida/revocada/materializada), EL SISTEMA DEBE comprobar el estado resultante y el rechazo observable (código HTTP y/o estado) de las transiciones no permitidas en los casos ejercitados, sin afirmar imposibilidad absoluta fuera de esos casos.

### Bloque B — Pruebas de integración (endpoints, base de datos, permisos, archivos, auth, asíncronos)

- RF-006: CUANDO se verifique un endpoint de la API, EL SISTEMA DEBE ejercitarlo contra una base de datos real (PostgreSQL) en modo opt-in (`RUN_DATABASE_TESTS=1`) y comprobar código de respuesta, cuerpo y efectos persistentes. Conjunto cerrado de endpoints «relevantes» a cubrir en esta entrega (inventario mínimo, no «todos los endpoints»): (a) los endpoints públicos de la spec 020 (`/tournaments/public`, detalle, clasificación, partidos, `player-stats`, `team-stats`); (b) los endpoints de invitación (crear, reenviar, revocar, reabrir, aceptar, previsualizar); (c) los endpoints de cierre de acta y segmentos; (d) los endpoints de escudos (`GET/POST/DELETE …/teams/{team_id}/crest`); (e) los endpoints de autenticación (email/password, Google por redirección, sesión, creación de organización); (f) los endpoints de permisos/organización listados en AGENTS.md para el miembro sin rol. Los endpoints no listados se verifican por inspección de los tests existentes y se declaran en el inventario como «cubierto por suite existente» o «no cubierto (fuera de esta entrega)».
- RF-007: CUANDO se verifique aislamiento entre organizaciones, EL SISTEMA DEBE probar que un recurso de otra organización responde 404 (o 403 según el contrato) y no filtra datos, para todos los endpoints tenant-owned relevantes.
- RF-008: CUANDO se verifique almacenamiento de archivos (fotos de jugadores, escudos de equipo), EL SISTEMA DEBE comprobar carga, reemplazo, eliminación, firma temporal y degradación a `null`/503 ante fallo de firma, respetando consentimiento de imagen.
- RF-009: CUANDO se verifique autenticación, EL SISTEMA DEBE cubrir email/password, acceso con Google por redirección (inicio, callback, vinculación, estado), sesión rehidratada y creación opcional de organización, incluyendo los códigos de error documentados (`GOOGLE_IDENTITY_INVALID`, `LINK_IDENTITY_TAKEN`, `ORGANIZATION_SLUG_TAKEN`). Si no hay un cliente OAuth real configurado, la parte Google se declara «no ejecutada» (motivo: sin cliente OAuth real), igual que RF-011, y solo se verifican los flujos email/password, sesión y creación de organización. No se inventan credenciales ni clientes OAuth en el repositorio.
- RF-010: CUANDO se verifique un proceso asíncrono (outbox + worker + Redis), EL SISTEMA DEBE comprobar que un evento de dominio se procesa y que el worker mantiene su latido; la verificación operativa se realiza con `infra/scripts/verify_worker_loop_health.sh`. Puede cerrarse ejecutando el script en un entorno aislado con Docker y la pila levantada (incluido el paso de sonda de outbox en desarrollo/local); si no se ejecuta por falta de Docker o por riesgo operativo sobre la pila en uso, se mantiene la declaración «no ejecutada» con motivo (RNF-002), sin presentarla como verde.- RF-011: CUANDO una prueba opt-in no pueda ejecutarse por falta de entorno, EL SISTEMA DEBE declararla «no ejecutada» en el informe final, citando el motivo (sin PostgreSQL, sin Docker, sin Node 24), nunca como verde.

### Bloque C — Pruebas de interfaz (wizards, navegación, formularios, calendario, plantillas, auth, vistas públicas)

- RF-012: CUANDO se verifique la interfaz, EL SISTEMA DEBE cubrir, con Playwright (E2E) o vitest según corresponda, dentro del presupuesto del job `e2e` (25 min): (a) E2E: autenticación, vistas públicas (recorrido por fases/grupos, clasificación, partidos con alineaciones publicadas), y el escenario de operación y cierre con los tres asistentes solo con teclado (RF-024); (b) vitest/`node --test`: wizards de reglas/fases/equipos con `?step=` y persistencia en `sessionStorage` (RF-013), normalización de pasos, formularios dinámicos y navegación por fases/grupos; (c) inspección manual documentada: calendario (crear partido, sortear/regenerar, listar con enlace a operación) y plantillas (alta individual, importación CSV/ZIP, foto, consentimiento), por su coste y dependencia de datos demo. Lo que no entre en el presupuesto de 25 min se declara «no ejecutado en esta entrega» con motivo.
- RF-013: CUANDO un asistente use `?step=` como única fuente del paso, EL SISTEMA DEBE verificar que la normalización al montar usa `replace`, que cada cambio del usuario apila con `push` y que «atrás» vuelve al paso anterior.
- RF-014: CUANDO se verifique una vista pública, EL SISTEMA DEBE comprobar que un visitante anónimo recorre un torneo por fases y grupos, ve clasificaciones, llaves y partidos con alineaciones publicadas, y no ve formaciones sin publicar, documentos, edad, asistencias ni sanciones.

### Bloque D — Pruebas de permisos

- RF-015: CUANDO se verifique permisos, EL SISTEMA DEBE cubrir al menos: usuario anónimo, miembro autenticado sin rol activo (403), observador, operador, administrador de organización y propietario, más administrador de plataforma, en rutas representativas.
- RF-016: CUANDO se verifique un acceso cruzado no autorizado (recurso de otra organización, invitación de otra organización, partido de otra organización), EL SISTEMA DEBE comprobar que la respuesta es 404 indistinguible (o 403 según el contrato) y que no se lee ni se escribe.
- RF-017: CUANDO un miembro activo sin ninguna fila de rol acceda a los endpoints listados en AGENTS.md (organización actual, miembros, cambio de rol/estado, invitaciones, reenvío, reapertura, revocación), EL SISTEMA DEBE verificar que recibe 403 `{"detail": "Membresía o rol activo no válido"}` sin leer ni escribir ni auditar.
- RF-018: CUANDO se verifique una ruta pública, EL SISTEMA DEBE comprobar que no se añade ninguna escritura, cookie ni dependencia de sesión (RF-018 de la spec 020).

### Bloque E — Regresión deportiva

- RF-019: CUANDO se verifique regresión deportiva, EL SISTEMA DEBE comprobar, con datos demo o fixtures (no datos reales de jugadores), al menos: registro de goles (incluido penalti y autogol), asistencia opcional del gol (válida/inválida), walkover (marcador derivado, sin eventos ni sanciones; los segmentos se tratan según la spec 016: si existe un segmento activo queda `completed` con `minute_end = minute_start`, los completados e interrumpidos no se tocan, no se crean segmentos nuevos y no se recalculan los contadores por equipo; clasificación y avance actualizados; auditoría con `suspensions: 0`), resolución administrativa (excluida de sanciones), cierre de acta (orden de 14 pasos, 422 estructurales prevalecientes), segmentos (creación, interrupción, propuesta `next_segment`), clasificaciones (marcador final, prórroga, penales excluidos) y estadísticas con porterías imbatidas.
- RF-020: CUANDO se cierre un acta con una expulsión por doble amarilla, EL SISTEMA DEBE verificar que se crea una sola sanción con la duración de expulsión, que las amarillas se absorben y que el historial no duplica filas (spec 018).
- RF-021: CUANDO se verifique un walkover, EL SISTEMA DEBE comprobar que no genera eventos ni sanciones (ni la resolución administrativa), que no crea segmentos nuevos y que, si existía un segmento activo, queda `completed` con `minute_end = minute_start` mientras los segmentos completados e interrumpidos no se tocan y no se recalculan los contadores por equipo, que la clasificación y el avance de llave se actualizan, y que la auditoría conserva `suspensions: 0`.
- RF-022: CUANDO se verifique la portería imbatida, EL SISTEMA DEBE comprobar los casos límite de la spec 022: portero con ≥ 60 minutos, sustitución acreditada en formación publicada posterior, walkover/administrativa excluidos, formación no publicada no atribuye portero. La verificación de empates con `rank` compartido se declara no ejecutable en esta entrega mientras la columna `rank` no exista (pendiente de la ronda de corrección de la spec 022); se acota al cálculo disponible y se registra como pendiente.

### Bloque F — Accesibilidad

- RF-023: CUANDO se verifique accesibilidad, EL SISTEMA DEBE comprobar, en las vistas públicas y del Workspace relevantes: navegación completa por teclado, foco visible y orden lógico, etiquetas accesibles en controles, mensajes de error asociados (`aria-invalid`/`aria-describedby`), `aria-live` en avisos, contraste suficiente y alternativas textuales (`alt`) para elementos visuales (escudos, fotos, campos).
- RF-024: CUANDO el escenario de operación y cierre se ejecute en el arnés E2E, EL SISTEMA DEBE recorrer los tres asistentes solo con teclado y verificar título enfocado y error asociado, además de la equivalencia del aviso de cierre con el 409 real. Este escenario entra en la entrega E2E; la accesibilidad completa (contraste, `alt`, orden de foco en otras vistas) queda como inspección manual documentada (RF-023).

### Bloque G — Documentación y manual de usuario

- RF-025: CUANDO se actualice la documentación, EL SISTEMA DEBE reflejar el comportamiento real en README y AGENTS: rutas públicas y Workspace, matriz de acceso público, escudos, acceso con Google, invitaciones vencidas, minutos y resoluciones, walkover, sustituciones, sanciones, estadísticas y porterías imbatidas, y la cadena de migraciones hasta 031. AGENTS.md DEBE incluir una referencia a `docs/manual-usuario.md` (RNF-006).
- RF-026: CUANDO se redacte el manual de usuario, EL SISTEMA DEBE incluir instrucciones de: creación de torneos, configuración de reglas y fases, creación de equipos y plantillas, calendario (crear partido, sortear/regenerar), registro de eventos y actas (segmentos, resolución, cierre), y consulta pública (fases, clasificación, partidos, formaciones, estadísticas), según las funcionalidades realmente disponibles.
- RF-027: CUANDO la documentación mencione una verificación, EL SISTEMA DEBE indicar si se ejecutó o se declara no ejecutada, y con qué comando, sin declarar como verde lo no ejecutado.

### Bloque H — Trazabilidad de cobertura (opcional del reviewer)

- RF-028: CUANDO se cierre el Bloque A backend, EL SISTEMA DEBE publicar en T1 de `tasks.md` una lista explícita de las funciones del inventario de `spec.md` §«Inventario de sujetos verificables (funciones/servicios/utilidades puras)» que quedaron sin cubrir en esta entrega, con motivo por función (fuera de alcance, coste, dependencia de base de datos, etc.), para cerrar RF-001 y RNF-002 con trazabilidad. La lista se mantiene en el informe final y no se presenta como verde ninguna función no cubierta.
## Requisitos no funcionales

- RNF-001: EL SISTEMA DE VERIFICACIÓN DEBE reutilizar las herramientas y comandos existentes (pytest, vitest, Playwright, `node --test`, scripts de infraestructura); no se introducen herramientas nuevas ni dependencias.
- RNF-002: EL SISTEMA DEBE ser honesto: una prueba no ejecutada por falta de entorno se declara «no ejecutada» con motivo, y no se marca como verde (principio §2.8 de la constitución).
- RNF-003: EL SISTEMA DEBE ejecutarse en el orden de CI: `backend`, `frontend`, `infrastructure`, `security` y `e2e`, con los comandos de AGENTS.md, y no declarar cumplimiento si algún job falla.
- RNF-004: EL SISTEMA DEBE mantenerse dentro del alcance de verificación y documentación: no añade endpoints, migraciones, campos públicos ni funcionalidad de producto.
- RNF-005: EL SISTEMA DEBE respetar la privacidad: las pruebas y la documentación no exponen datos personales, documentos ni fechas de nacimiento, y no incluyen secretos.
- RNF-006: EL SISTEMA DE DOCUMENTACIÓN DEBE mantener coherencia entre README, AGENTS y esta spec; si divergen, gana el código y la CI (AGENTS.md).

## Datos personales y privacidad

No se añaden datos personales. Las pruebas usan datos demo y fixtures; la documentación y el manual no incluyen datos reales de jugadores ni secretos. Las proyecciones públicas siguen excluyendo documento, fecha de nacimiento y edad.

## Casos límite

- Sin PostgreSQL disponible: las suites opt-in se declaran no ejecutadas; las suites puras deben seguir pasando.
- Sin Docker disponible: el E2E y `verify_worker_loop_health.sh` se declaran no ejecutados.
- `verify_worker_loop_health.sh` puede ejecutarse en un entorno aislado con Docker y la pila levantada para cerrar RF-010; si no se ejecuta, se mantiene la declaración «no ejecutado» con motivo (RNF-002), sin presentarla como verde.- Sin Node 24/pnpm 12.12.1: el frontend y el E2E se declaran no ejecutados.
- Entorno con migraciones pendientes (026–031): las pruebas que dependan de vistas/columnas nuevas deben declararse no ejecutadas o acotarse al esquema disponible, sin modificar migraciones.
- Un RF que no pueda verificarse automáticamente (por ejemplo, contraste visual) se verifica por inspección manual documentada, declarando el método.
- Un hallazgo de seguridad sin corrección publicada se muestra y revisa, sin suprimirlo (constitución §3.4).

## Fuera de alcance

- Nueva funcionalidad de producto, endpoints o migraciones.
- Cambios en el contrato interno de reglas (`engine_version` 2026.1) o en el catálogo de formaciones.
- Reescritura de pruebas existentes que ya pasan; solo se añaden o completan las que falten.
- Ejecución real en este entorno si no hay Docker/PostgreSQL/Node; se declara no ejecutada.
- Traducción o internacionalización nueva.

## Criterios de finalización

- Existe un inventario documentado de qué se verifica en cada bloque (A–G) y con qué herramienta.
- Las suites puras (`pytest -q` sin opt-in, `pnpm test`, `node --test` donde aplique) pasan en verde o se declara el motivo de fallo.
- Las suites opt-in se ejecutan si hay entorno, o se declaran no ejecutadas con motivo.
- README y AGENTS reflejan el comportamiento real incluyendo las specs 020, 021 y 022.
- Existe un manual de usuario con los flujos realmente disponibles.
- Todo RF de esta spec tiene evidencia (prueba, inspección o declaración de no ejecución) citada en el informe final.
- No se introdujeron secretos, datos personales ni cambios de esquema.

## Dudas abiertas

Resueltas en esta corrección:

- Manual de usuario: vive en `docs/manual-usuario.md` (anexo), con enlace desde `README.md`; no se infla el README. (RF-026.)
- Accesibilidad: inspección manual documentada + teclado en el arnés E2E; no se añaden herramientas automatizadas (axe/lighthouse) por RNF-001. El contraste y los `alt` se verifican por inspección manual declarando el método. (RF-023, RF-024.)
- Cobertura: por RF listado en esta spec, sin umbral porcentual, para evitar métricas vacías. (RNF-001, criterios de finalización.)
- Trazabilidad de cobertura: las funciones del inventario backend no cubiertas se listan explícitamente en T1 con motivo (RF-028, RNF-002). (Opcional del reviewer.)
- Coherencia documental: AGENTS.md incluye referencia a `docs/manual-usuario.md` (RF-025, RNF-006). (Opcional del reviewer.)
- Verificación asíncrona: `verify_worker_loop_health.sh` puede ejecutarse en entorno aislado para cerrar RF-010 o mantener la declaración «no ejecutado» (RNF-002). (Opcional del reviewer.)
No quedan dudas abiertas.