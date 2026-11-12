# Plan 033 — Acta rectificativa

Fecha: 2026-11-12. Estado: **aprobado** por el usuario el 2026-11-12 («Apruebo el plan.»). Desarrolla la spec 033 (aprobada el 2026-11-12) y la §3.6 de la constitución 2.0.0. Los nombres de archivos, tablas y endpoints son propuestas; nada de esto está implementado.

## 1. Idea central

El acta original sigue siendo la fila de `matches` y sus `match_events`, protegidas por `trg_protect_confirmed_match_result` (016) y `trg_validate_match_event_context` (009), que **no se relajan**. Cada rectificación publicada es una fila nueva en tablas *append-only* propias, con el resultado completo y sus eventos. Dos vistas internas resuelven la **versión vigente** de cada partido (la última publicada o, si no hay, el acta original), y **todos los lectores** de resultados y eventos confirmados pasan a leer esas vistas: clasificación, historial disciplinario, estadísticas públicas, proyecciones públicas y Workspace (RF-013, RF-021).

Alternativa descartada: copiar el original a un histórico y sobrescribir `matches`/`match_events`. Exige relajar el trigger de la 016, que la spec (RF-013) y la constitución prohíben.

## 2. Base de datos — migración `035_match_report_rectifications.sql`

Todas las tablas son de tenant, llevan `organization_id`, `ENABLE`/`FORCE ROW LEVEL SECURITY`, y la política `FOR ALL` con `USING`/`WITH CHECK` sobre `app.current_organization_id` y `fn_verify_user_org_membership(organization_id)` (patrón de la 014), más `GRANT` explícitos a `bracket_app`. Las tablas *append-only* solo reciben `SELECT, INSERT` y un trigger que rechaza `UPDATE`/`DELETE` (RNF-001, RF-013).

| Tabla | Contenido | Escritura |
|---|---|---|
| `match_report_rectification_requests` | partido, `base_version_number`, propuesta completa (JSONB validado), motivo, evidencia (texto), solicitante (`user_id` y `member_id`), fecha, `status` (`pending`, `rejected`, `withdrawn`, `published`), `withdrawn_at`, versión resultante. Índice único parcial: un `pending` por partido (RF-002). | `INSERT`; `UPDATE` solo de `status` desde `pending`, que impone un trigger. |
| `match_report_rectification_decisions` | solicitud (única), `approve`/`reject`, motivo, `decided_by_user_id`, `decided_by_member_id` (nulo si decide la plataforma), `decided_as` (`member`/`platform_admin`), autorización usada, fecha. Trigger: rechaza la fila si `decided_by_user_id` coincide con el solicitante (RF-007 en base de datos). | *Append-only*. |
| `match_report_platform_authorizations` | solicitud, dueño que concede (`member_id`), administrador de plataforma (`user_id`), motivo, `granted_at`, `revoked_at`, `consumed_at`. | `INSERT`; `UPDATE` solo de `revoked_at`/`consumed_at` vacíos. |
| `match_report_versions` | partido, `version_number` (≥ 2, único por partido), `supersedes_version_number`, referencia al acta original (el propio partido, versión 1), resolución, motivo de la resolución, marcadores regulares y finales, penales, ganador, solicitud, `published_at`, `published_by_user_id`. | *Append-only*. |
| `match_report_version_events` | versión y las mismas columnas de evento que `match_events` (segmento, equipo, beneficiario, jugador, tipo, minuto, añadido, asistencia, entrante/saliente, metadatos). | *Append-only*. |
| `match_report_rectification_effects` | versión, tipo (`standings`, `sanction_created`, `sanction_annulled`, `advancement`, `tiebreak_draw_invalidated`, `impact_opened`, `outbox`), entidad y carga. | *Append-only*. |
| `match_report_rectification_notifications` | solicitud o versión, canal (`realtime`/`email`), tipo, destinatario (`user_id`, nulo en tiempo real), evento de outbox, fecha. | *Append-only*. |
| `competitive_impact_procedures` | versión, partido rectificado, elementos afectados (JSONB: partido, lado, efecto que se habría aplicado), `status` (`open`/`closed`), cierre (`keep_as_played`, motivo, `user_id`, fecha). | `INSERT`; `UPDATE` solo `open → closed`. |
| `player_suspension_annulments` | sanción, versión que la anula, motivo, fecha. | *Append-only*. |

Cambios en tablas existentes:

- `player_suspensions`: la anulación pasa `status` a `cancelled` y deja su registro en `player_suspension_annulments`. Un trigger nuevo impide cambiar cualquier otra columna de una sanción (RF-018). Los cumplimientos (`player_suspension_serves`) no se tocan (DA-8).
- `role_definitions` y `roles`: se añaden `REQUEST_MATCH_REPORT_RECTIFICATION` y `APPROVE_MATCH_REPORT_RECTIFICATION` a `owner` y `administrator`, sin duplicar, como hace la 014 (DA-1).
- Vistas internas `v_match_current_report` (partido, `version_number`, resultado vigente, `rectified_at`) y `v_match_current_events` (eventos de la última versión publicada o, si no hay, los `match_events` no anulados del original). Ambas con `security_barrier`; heredan la RLS de sus tablas.
- Se recrean `v_public_matches` y `v_public_match_events` sobre las vistas vigentes. `v_public_matches` gana solo `rectified_at` (DA-4, RF-022). Las demás proyecciones públicas no cambian.
- `fn_verify_user_org_membership` acepta además, **solo** si la sesión fija `app.rectification_authorization_id`, una autorización de plataforma vigente para ese usuario y esa organización (§5 de este plan, decisión D3).
- `prevent_published_match_structure_mutation` permite sustituir `home_team_id`/`away_team_id` de un partido publicado **solo** si se cumplen todas estas condiciones: la sesión fija `app.rectification_version_id`, esa versión está publicada y registra el efecto `advancement` sobre ese partido y lado, y el partido destino está `scheduled`, sin segmentos y sin confirmar (RF-015; decisión D4). Cualquier otro cambio de estructura publicada sigue prohibido.

Verificación: `sh -n infra/postgres/migrate.sh`, `sh infra/scripts/test_migrate_target.sh`, y `backend/tests/test_migration_035.py` sobre volumen limpio (init + 001–035) y migrado (034 → 035) siguiendo `test_migration_031.py`. El test comprueba RLS, `GRANT`, triggers *append-only*, el trigger de autoaprobación y la equivalencia de las vistas públicas para partidos no rectificados.

## 3. Backend

Módulo nuevo `backend/app/modules/rectifications/` (`router.py`, `schemas.py`, `service.py`, `effects.py`, `diff.py`), registrado en `backend/app/main.py`. Las operaciones van en una sola transacción con `set_rls_context()` al principio.

### 3.1 Reutilización del cierre

De `matches/service.py` se extrae, sin cambiar su comportamiento, un validador `validate_report_payload(snapshot, payload, now)`. El snapshot reúne lo que ya cargan los validadores del cierre (`_validate_rosters`, `_validate_segments`, `_validate_event_participants`, `_validate_substitutions`, `_validate_double_yellow`, `_validate_event_score_consistency`, `compute_match_outcome`) y no escribe nada. El cierre y la rectificación lo llaman igual (RF-001, RNF-005). La propuesta usa los segmentos y plantillas existentes del partido: un evento con un segmento de otro partido es **409** con el mismo `code` que el cierre. Para `walkover`/`administrative` se reutiliza `_execute_walkover` en su parte pura (`derive_walkover_score`) y se exige `RESOLVE_MATCH_ADMINISTRATIVELY` al solicitante y al aprobador.

### 3.2 Endpoints (prefijo `/api/v1`)

| Método y ruta | Permiso | RF |
|---|---|---|
| `POST /matches/{id}/rectifications` | `REQUEST_MATCH_REPORT_RECTIFICATION` | RF-001–RF-003, RF-023 |
| `GET /rectifications` y `GET /matches/{id}/rectifications` | miembro | RF-020 |
| `GET /matches/{id}/report-versions` y `/{n}` | miembro | RF-020 |
| `GET /rectifications/{rid}` (detalle y diferencias) | miembro | RF-005, RF-020 |
| `GET /rectifications/{rid}/preview` (efectos previstos) | `APPROVE_…` | RF-005 |
| `POST /rectifications/{rid}/withdraw` | solicitante | RF-004 |
| `POST /rectifications/{rid}/decision` `{decision, reason, expected_base_version}` | `APPROVE_…` | RF-006–RF-008, RF-010–RF-012 |
| `GET /rectifications/{rid}/platform-authorizations` | `owner`, 404 para el resto | RF-009 |
| `POST /rectifications/{rid}/platform-authorizations` `{platform_admin_email, reason}` y `DELETE …/{aid}` | `owner` | RF-009 |
| `GET /competitive-impacts` y `GET /tournaments/{id}/competitive-impacts` | miembro | RF-017, RF-020 |
| `POST /competitive-impacts/{pid}/close` `{reason}` | `APPROVE_…` | RF-017 |
| `GET /platform/rectifications`, `GET /platform/rectifications/{rid}`, `POST /platform/rectifications/{rid}/decision` | `platform_admin` con autorización vigente | RF-008, RF-009b |
| `GET /platform/rectifications/{rid}/preview` | `platform_admin` con autorización vigente, simulación revertida | RF-005, RF-009b |

Errores con la forma de la spec 017 (RNF-004): **403** `RECTIFICATION_SELF_APPROVAL`; **409** `RECTIFICATION_ALREADY_OPEN`, `RECTIFICATION_NO_CHANGES`, `RECTIFICATION_STALE`, `RECTIFICATION_NOT_PENDING`, `MATCH_NOT_CONFIRMED`, `TOURNAMENT_ARCHIVED` y `COMPETITIVE_IMPACT_OPEN`; **404** indistinguible entre organizaciones. Una aprobación sobre un torneo archivado responde `TOURNAMENT_ARCHIVED`, mientras que el rechazo y la retirada sí se permiten (caso límite de DA-9). La plataforma solo puede designar usuarios con `role_code = 'platform_admin'` activo; una dirección no válida responde el mismo **422** exista o no.

**Contrato de bandeja aprobado para T16:** ambos listados organizativos admiten `status`, `tournament_id`, `limit` (1–100, por defecto 25) y `offset` (≥0, por defecto 0), sin parámetros adicionales. Responden `{items,total,limit,offset}` con orden descendente estable por fecha e ID; un filtro de torneo ajeno o inexistente devuelve la misma página vacía bajo RLS. Solicitudes: `pending|published|rejected|withdrawn`; impactos: `open|closed`. La lectura de autorizaciones devuelve también revocadas/consumidas, solo al owner; para cualquier otro miembro responde el mismo 404 que una solicitud inexistente. Leer impactos no concede permiso para cerrarlos.

**Contrato de revisión de plataforma aprobado para T17:** el detalle añade únicamente `current_version: ReportVersionResponse`. El preview usa GET, igual que el organizativo, y devuelve `{version,effects,expected_base_version}`; ambos previews exponen la base explícita. La simulación siempre revierte sus escrituras, incluidos efectos, notificaciones y auditoría; no consume la autorización ni crea membresía. Autorizaciones ausentes, revocadas o consumidas producen el mismo 404 que una solicitud inexistente. La revisión de plataforma no llama a lecturas organizativas ni ofrece cierre de impactos.

### 3.3 Decisión y publicación

```text
decide(request_id, decision, reason, expected_base, actor, now):
  lock request FOR UPDATE; lock match FOR UPDATE
  require request.status == pending                    -> 409 NOT_PENDING (RNF-003)
  require actor.user_id != request.requested_by_user_id -> 403 SELF_APPROVAL (RF-007)
  require actor may approve (member permission | valid platform authorization) -> 403
  require reason not blank
  insert decision row
  if decision == reject: request.status = rejected; consume authorization; notify(rejected); return
  require current_version(match) == request.base_version == expected_base -> 409 STALE (RF-010)
  require tournament version not archived -> 409 TOURNAMENT_ARCHIVED
  validate_report_payload(snapshot, request.proposal, now) -> 409 (same code as the close)
  v = insert match_report_versions(n+1) + events
  set_config('app.rectification_version_id', v.id, true)
  effects = apply_effects(v, now)        # 3.4
  request.status = published; consume authorization
  audit (tenant and/or platform); notify(published) ; outbox rows
```

Toda la decisión ocurre en una sola transacción: cualquier excepción la deshace entera (RF-012). La vista previa (RF-005) ejecuta esa misma ruta hasta `apply_effects` dentro de una transacción que termina siempre en `ROLLBACK`, y devuelve los efectos calculados. Así la vista previa y la publicación no pueden divergir. No genera efectos externos, porque el correo y el tiempo real solo salen del worker.

### 3.4 Efectos (`effects.py`)

1. **Clasificación (RF-014):** `StandingsService.recalculate(stage)` lee `v_match_current_report`/`v_match_current_events` en lugar de `matches`/`match_events`. Si cambia el grupo empatado de un desempate por sorteo ya resuelto, se registra `tiebreak_draw_invalidated` (caso límite) y el sorteo previo deja de aplicarse. **Aclaración confirmada:** resuelto significa que el grupo llegó empatado a `random_draw` en la clasificación persistida. Se registra un efecto por cada grupo anterior sin los mismos integrantes después, incluyendo los integrantes anteriores y los grupos posteriores relacionados. El recálculo conserva el algoritmo y la semilla actuales; no introduce otro sorteo ni persistencia adicional de sorteos. El estado anterior se captura bajo el bloqueo de fase antes de insertar la versión nueva.
2. **Sanciones (RF-018, DA-8):** se recalculan las sanciones originadas en el partido con `evaluate_suspensions`, alimentado por el historial disciplinario vigente. Se comparan por clave de deduplicación:
   - Las sanciones nuevas se insertan como `active`.
   - Las que ya no corresponden pasan a `cancelled` y quedan anotadas en `player_suspension_annulments`.
   - Los cumplimientos ya registrados se conservan.

   **Aclaraciones aprobadas para T12:** la 037 añade `source_version_event_id` con FK compuesta y exactamente una procedencia para `match_event`, conservando la FK original. La comparación usa evento lógico (`client_event_id` persistido), jugador y motivo: una sanción todavía correspondiente conserva su fila; si una tarjeta anulada reaparece se crea otra sanción, sin reactivar la anterior. El estado disciplinario anterior se captura antes de insertar la versión; se proyecta únicamente el cambio del partido rectificado sobre ese mismo historial. Los partidos se ordenan con la clave disciplinaria existente (fecha y, en empate o sin fecha, ID).

   La elegibilidad al validar una rectificación excluye las sanciones del propio partido y las de `created_at > matches.original_report_confirmed_at`. La 037 captura esa fecha con `now()`, igual que el default `CURRENT_TIMESTAMP` de `player_suspensions.created_at`, y la hace inmutable. El backfill aprobado usa el primer audit `CLOSE_MATCH_REPORT`/`ADMINISTRATIVE_MATCH_RESOLUTION`; sin audit queda NULL y se mantiene la comprobación conservadora anterior, sin error nuevo. La validación del cierre original no usa este corte temporal.

   T12 devuelve los cambios posteriores de acumulación en memoria como `list[AccumulationImpactCandidate]`, con partido, jugador, eventos de umbral anteriores/posteriores y duración. `apply_effects` los entrega a `apply_competitive_impacts` dentro de la transacción. T14 consume los candidatos en ese hook: no se introduce `impact_pending`, no se modifica la sanción posterior y `impact_opened` solo se registra junto con el procedimiento real.

   Una sanción nueva no cuenta como cumplida en ningún partido que ya tuviera un segmento antes de su creación. Para eso se añade esa condición a la elegibilidad de cumplimiento en el cierre (`service.py:1760–1791`). Si el cambio altera una acumulación de amarillas cuya sanción se originó en un partido posterior ya confirmado, esa sanción **no** se toca: se abre un elemento de impacto competitivo (decisión D5).
3. **Avance (RF-015, RF-016):** si cambia el ganador o el perdedor, se revisa cada destino de `advancement_links` (y el reinicio de la gran final). Un destino **no comenzado** (`scheduled`, sin `match_segments`, sin confirmar) recibe el equipo nuevo, sustituyendo al antiguo solo si este llegó por ese enlace. En cualquier otro caso se abre impacto. Las condiciones exactas están en 5.2. Además, si cambia el orden final de una fase y una fase posterior de la misma versión ya tiene equipos asignados, se abre impacto, porque el paso entre fases es manual y no se reasigna.
4. **Impacto (RF-016, RF-017, RF-017b):** se crea un procedimiento por versión con todos sus elementos afectados. Mientras siga abierto, abrir un segmento (`matches/router.py:705`) o cerrar el acta de un partido afectado responde **409** `COMPETITIVE_IMPACT_OPEN`. Se cierra solo con `keep_as_played` y motivo.

   **T14, aclaración confirmada:** un candidato de fase incluye todos sus partidos y sus asignaciones como snapshot. Se agrupan todos los candidatos de una solicitud/versión en un procedimiento y los partidos se deduplican, conservando todos los efectos propuestos. Se bloquean únicamente partidos sin segmentos y sin resultado confirmado (el primer segmento es la apertura según AP-1), no los ya comenzados. La 039 añade los triggers y un índice único por versión, preservando las funciones anteriores. Bloquear las filas de partido serializa la apertura del procedimiento con su primer segmento/confirmación. Los dos endpoints de impacto solo admiten aprobadores organizativos: D3 no autoriza cierre desde plataforma y su autorización se consume al publicar. El cierre conserva snapshots, deja auditoría y no modifica resultados ni sanciones posteriores. Vista previa y errores revierten procedimientos, efectos y auditorías.
5. **Tiempo real y registro (RF-019):** se encolan en la outbox `MATCH_UPDATED`, `STANDINGS_UPDATED` y `MATCH_REPORT_RECTIFIED` (los tres solo para la organización, sin emisión al canal público), y cada efecto y cada notificación quedan registrados. Para no duplicar el SQL del cierre, se extrae un helper `enqueue_outbox(session, …)` en `core/outbox.py`.

### 3.5 Correo (RF-024, DA-10)

El envío de correo actual es síncrono y no pasa por la outbox (`core/email.py:22`). Se añade:

- Un tipo de outbox `RECTIFICATION_DECISION_EMAIL`, con solicitud, decisión y motivo, sin evidencia.
- En el worker, el manejo de ese tipo: llama a una función nueva, `send_rectification_decision_email`, en lugar de publicarlo en Redis.
- La reutilización de los reintentos y fallos existentes de la outbox.

Si SMTP no está configurado, el evento termina como fallido con el mismo tratamiento que hoy, sin bloquear la decisión. No hay variables de entorno nuevas.

**T15 implementada:** el payload de tiempo real lleva `scope=organization` y el relay excluye esos eventos de las salas públicas, sin ampliar la allowlist. El correo se encola y registra antes de consumir la autorización de plataforma para conservar RLS hasta finalizar sus escrituras. Se guarda únicamente destinatario, solicitud, decisión y motivo; el worker no publica ese evento en Redis. SMTP ausente o fallido pasa por `fail_outbox_event`, con reintentos y límite existentes. Las notificaciones son registros de encolado append-only de 035, vinculados al evento; los intentos y la entrega se consultan en la outbox. Se conserva su semántica de al menos una entrega. La vista previa revierte también eventos, efectos outbox y notificaciones. No requiere migración nueva.

### 3.6 Lectores que cambian a la versión vigente (RF-021)

- `standings/service.py`: resultados (`:133`) y disciplina (`:95`).
- Historial disciplinario del cierre: un partido posterior se valida con las tarjetas vigentes.
- `tournaments/routes/public.py`: estadísticas (`:302–378`, `:436–488`) mediante las vistas públicas recreadas.
- Lecturas del Workspace del partido.
- `advancement/service.py`, cuando la llamada viene de la publicación.

Un test de inventario (`test_rectification_readers.py`) busca en `backend/app` consultas a `matches.home_score`/`match_events` fuera de una lista explícita de lectores permitidos (el cierre y el operar en vivo), para que ningún lector nuevo quede leyendo el original.

## 4. Frontend

Todo pasa por `useApi.ts`. Textos en ES/EN (`useI18n.ts`), componentes de `components/ui/` y diálogos con `useConfirm` (RNF-006).

- `pages/workspace/matches/[id].vue`, en partidos confirmados:
  - Sección «Versiones del acta», con el historial, la versión vigente y las diferencias (RF-020).
  - Botón «Solicitar rectificación», que abre `components/match/RectificationEditor.vue`. El editor parte de la versión vigente y edita resolución, marcadores, penales y eventos. Reutiliza las filas de evento de la operación cuando su contrato lo permita.
- `pages/workspace/rectifications.vue`: bandeja de solicitudes pendientes y procedimientos de impacto de la organización.
  - En el detalle, `RectificationReview.vue` muestra la versión vigente, la propuesta, las diferencias y la vista previa de efectos. Permite aprobar o rechazar con motivo y, al dueño, conceder o revocar la autorización de plataforma.
  - El botón de decisión no se muestra al solicitante, aunque el servidor lo rechaza igualmente.
- `pages/admin/rectifications.vue`: lista y detalle de las solicitudes para las que el administrador de plataforma está autorizado, con la misma vista de revisión.
- Público: marca «Resultado rectificado · fecha» en las tarjetas de partido de `pages/tournaments/[id].vue`, en `PublicLineupModal.vue` y en `PublicBracket.vue` (RF-022).
- Composables nuevos: `useMatchRectifications.ts`, `useCompetitiveImpacts.ts` y `usePlatformRectifications.ts`.

## 5. Decisiones y alternativas descartadas

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D1 | Versiones en tablas nuevas y lectores sobre vistas de versión vigente. | Sobrescribir `matches`. | RF-013 y §2.3 prohíben relajar la 016. |
| D2 | Vista previa ejecutando la publicación y haciendo `ROLLBACK`. | Un planificador puro paralelo. | Una sola ruta de cálculo; sin divergencias entre lo previsto y lo publicado. |
| D3 | La plataforma decide con el contexto RLS de la organización, habilitado solo por una autorización vigente fijada en la transacción. **Confirmada el 2026-11-12** (ver 5.1). | Función SQL `SECURITY DEFINER` que publique. | Duplicaría en SQL todos los efectos; la excepción queda limitada a esa solicitud y a esa transacción. |
| D4 | El trigger de estructura publicada permite sustituir el equipo de un destino no comenzado solo bajo una versión publicada que registre ese efecto. **Confirmada el 2026-11-12** (ver 5.2). | Tratar todo destino ya asignado como impacto. | Hoy el cierre ya asigna los destinos al cerrar, así que sin D4 RF-015 nunca se aplicaría. Cambia un trigger de endurecimiento, con las condiciones de 5.2. |
| D5 | Las sanciones por acumulación originadas en partidos posteriores confirmados no se anulan ni se crean automáticamente; se abre impacto. | Recalcular toda la disciplina del torneo. | Esas sanciones pertenecen a actas posteriores ya confirmadas (§3.6). |
| D6 | El correo pasa por la outbox con un manejador propio en el worker. | Envío síncrono tras la transacción, como las invitaciones. | La spec exige la outbox y el registro de la notificación (RF-019, RF-024). |
| D7 | La autoaprobación se impide en el servicio **y** con un trigger en la tabla de decisiones. | Solo el servicio. | «Técnicamente» (§3.6): ni un error de código la permite. |
| D8 | La autorización de plataforma se designa por correo y solo para `platform_admin` activo. | Incluir `platform_support`. | El soporte no tiene permisos de escritura (`require_platform_write`). |

### 5.1 Condiciones de D3 (confirmadas por el usuario)

- La plataforma solo opera sobre datos de la organización con una autorización **vigente y verificable** del dueño. Vigente quiere decir no revocada, no consumida, solicitud `pending` y dueño todavía con rol `owner` activo. Se verifica al ejecutar la decisión, con la autorización bloqueada `FOR UPDATE`.
- La autorización vincula la organización, la solicitud, el administrador ejecutor (`user_id` con `platform_admin` activo) y el dueño autorizante (`member_id`).
- `app.rectification_authorization_id` se fija con `set_config(…, true)`, local a la transacción. `fn_verify_user_org_membership` solo la acepta si coinciden la organización de la sesión, el usuario de la sesión y una autorización vigente. Al terminar la transacción no queda ningún permiso persistente.
- Las políticas RLS siguen aplicándose a todas las tablas. Sin `BYPASSRLS`, sin cambios de rol y sin `SECURITY DEFINER` que escriba datos de la organización.
- La decisión, la publicación de la versión y todos sus efectos van en una única transacción, que además consume la autorización.
- Test: fuera de esa transacción, la misma sesión de plataforma vuelve a recibir 404 o 0 filas sobre la organización.

### 5.2 Condiciones de D4 (confirmadas por el usuario)

El trigger permite sustituir `home_team_id`/`away_team_id` de un partido de una versión publicada **solo si se cumplen todas** estas condiciones. Si falla cualquiera, rechaza la sustitución y el servicio abre un procedimiento de impacto competitivo en su lugar:

1. El partido destino está y permanece `scheduled` durante la sustitución, no tiene filas en `match_segments` y no tiene `result_confirmed` ni lo adquiere en esa sentencia.
2. El equipo sustituido llegó **exclusivamente** por el enlace de avance del partido origen. Hoy el cierre no registra cómo se asigna un equipo. Por eso la 035 añade `match_slot_assignments` (*append-only*: partido, lado, equipo, origen `advancement_link`/`manual`/`rectification`, enlace, versión, fecha), y el cierre y el servicio de avance escriben en ella. Para asignaciones anteriores a la 035, la migración solo infiere el origen `advancement_link` si el equipo coincide con el resultado del enlace del origen confirmado y ningún otro enlace apunta a ese lado. Si no, las marca `manual` y su sustitución automática queda prohibida.
3. El equipo nuevo es el que el enlace determina con la versión publicada: el nuevo ganador o, en enlaces `loser`, el nuevo perdedor.
4. La sesión fija `app.rectification_version_id`, que pertenece a la misma transacción que publica la versión, y esa versión registra el efecto `advancement` sobre ese partido y lado.
5. La sustitución añade una fila `rectification` en `match_slot_assignments` y un efecto con el acta original, la versión, el partido origen, el destino, el equipo anterior y el nuevo. La asignación anterior no se modifica ni se elimina.
6. No hay equipos asignados en una fase posterior de la misma versión. Si los hay, no se sustituye automáticamente (aclaración del brief de T13).

**Implementación T13 confirmada:** la 038 redefine `prevent_published_match_structure_mutation` con copia literal de las demás prohibiciones y solo la excepción D4. La BD verifica el contexto local, la versión del origen creada en esa transacción, sus equipos, el enlace exclusivo, la procedencia anterior y el efecto `advancement` del destino/lado con trazabilidad exacta. El trigger bloquea el destino y añade la asignación `rectification`; el servicio registra primero los efectos y actualiza conjuntamente ambos lados si es necesario. T13 entrega `AdvancementImpactCandidate` al mismo `apply_competitive_impacts` que las acumulaciones de T12, consumidos por T14 para abrir el procedimiento. Los cambios de clasificación con fases posteriores asignadas y los del reinicio GF2 también producen candidatos, no reasignaciones manuales ni activación/cancelación implícita del reinicio.

No se puede modificar una inscripción manual, sustituir un equipo de forma arbitraria ni alterar un partido que ya comenzó.

## 6. Estrategia de tests

Siempre primero en rojo (Fase 5).

- **Puros:** `validate_report_payload` (equivalencia con el cierre en todos sus casos actuales), `diff.py` (diferencias por campo y evento), la comparación de sanciones por clave, la clasificación de destinos (no comenzado o impacto) y la detección de cambios de orden de fase. Las funciones reciben `now` como parámetro.
- **Base de datos** (`RUN_DATABASE_TESTS=1`):
  - `test_migration_035.py`.
  - `test_rectification_flow.py`: solicitud, retirada, rechazo, publicación, versión 3 sobre versión 2, `STALE`, dos aprobaciones concurrentes que producen una sola versión, autoaprobación por servicio y por trigger, plataforma con autorización, sin ella, revocada y consumida, aislamiento 404 entre dos organizaciones y torneo archivado.
  - `test_rectification_effects.py`: D4, una prueba por cada condición de 5.2 que falla (destino con segmento, destino confirmado, asignación manual, equipo distinto del enlace, sin versión en la sesión), que demuestra el rechazo del trigger y la apertura de impacto; clasificación, sanciones (nueva, anulada con cumplimientos conservados y no cumplida en un partido ya comenzado), avance a un destino libre, impacto por destino comenzado, por fase posterior y por acumulación, bloqueo `COMPETITIVE_IMPACT_OPEN` y outbox.
  - `test_rectification_readers.py`.
- **Públicos:** `test_public_field_allowlist.py` y `test_public_access_matrix.py` se amplían solo con `rectified_at`. Para partidos no rectificados, las estadísticas públicas devuelven lo mismo que antes.
- **Worker:** el manejador del correo, con fallo y reintento, y que el correo no incluye la evidencia.
- **Frontend:**
  - `pnpm test`: composables, editor, revisión sin botón para el solicitante y marca pública.
  - `typecheck`, `lint` y `build`.
  - E2E `e2e/rectification.spec.ts` en el proyecto Workspace: solicitar, otro miembro aprueba y la marca pública aparece.

## 7. Cobertura de requisitos

| RF/RNF | Dónde |
|---|---|
| RF-001–RF-004, RF-023 | 3.1, 3.2; tabla de solicitudes |
| RF-005 | 3.2, 3.3 (vista previa) |
| RF-006–RF-010, RF-009b | 3.3; tablas de decisiones y autorizaciones; D3, D7 |
| RF-011–RF-013 | 1, 2, 3.3 |
| RF-014–RF-018, RF-017b | 3.4; D4, D5 |
| RF-019, RF-024 | 3.4 (5), 3.5; D6 |
| RF-020–RF-022 | 2 (vistas), 3.6, 4 |
| RNF-001–RNF-006 | 2, 3.2, 3.3, 4 |

## 8. Entrega propuesta

El trabajo es grande para un solo PR. Propongo dividirlo en cuatro, en orden:

1. **Migración 035 y lectores sobre la versión vigente**, sin endpoints nuevos.
2. **Solicitud y decisión**, con autoaprobación, plataforma y vista previa.
3. **Efectos de la publicación**: clasificación, sanciones, avance, impacto, outbox y correo.
4. **Frontend, documentación** (`README.md`, `AGENTS.md`, `docs/manual-usuario.md`) y E2E.

La división en tareas se hará en `tasks.md` tras aprobar este plan.

## 9. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento tenant en BD | Sí | Todas las tablas nuevas llevan RLS y políticas en la 035; test de aislamiento 404 entre organizaciones. |
| §2.2 Sin BYPASSRLS | Sí | Ningún rol cambia; la plataforma opera con RLS de la organización vía autorización acotada (D3), no con un rol privilegiado. |
| §2.3 Publicado inmutable | Sí | `matches` y `match_events` originales intactos y triggers 016/009 sin cambios. La única excepción estructural (D4) es el recálculo de avance que §3.6 exige, limitado a destinos no comenzados y a una versión publicada; requiere confirmación. Las versiones de torneo no se rectifican. |
| §2.4 Historial de esquema append-only | Sí | Una migración nueva, 035; ninguna aplicada se edita. |
| §2.5 Público mínimo | Sí | Solo se añade `rectified_at`; ningún motivo, evidencia, responsable ni versión anterior; documentos, nacimientos y fotos sin cambios. |
| §2.6 Sin secretos por defecto | Sí | Sin variables nuevas; el correo usa la configuración SMTP existente. |
| §2.7 Administración global separada y auditada | Sí | Endpoints bajo `/platform`, pantalla en `/admin`, `platform_admins` activo y `platform_audit_logs` en cada decisión. |
| §2.8 Nada terminado sin verificar | Sí | TDD por tarea, CI de los cinco jobs y validación por RF antes de cerrar. |
| §2.9 Desarrollo fuera de producción | Sí | Sin seeds nuevos; los datos de prueba solo en tests. |
| §3.6 Rectificación | Sí | Tres pasos, otra persona, plataforma excepcional, versión vigente intacta hasta publicar, *append-only*, recálculo, efectos y notificaciones registrados, impacto sin cambios automáticos. Sanciones: solo las derivadas del acta (F9 aparte). |
| §4 CI correspondiente | Sí | `backend`, `frontend`, `infrastructure`, `security` y `e2e`. |
| §4 BD: migración, RLS, limpio y migrado, `sh -n` | Sí | Sección 2. |
| §4 Backend: contexto RLS, routers, `pytest`/`compileall` | Sí | Sección 3; router registrado en `main.py`. |
| §4 Frontend: `useApi`, tests/typecheck/lint/build | Sí | Sección 4. |
| §4 Documentación observable | Sí | `README.md`, `AGENTS.md` y manual en el PR 4; `MEMORY.md` en cada fase. |
| §4 Dependencias | No | Sin dependencias nuevas. |
