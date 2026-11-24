# Plan — Spec 046: Notificaciones en la app y por correo (F6, parte 1)

Estado: borrador (2026-11-24), pendiente de aprobación.

## 1. Alcance y dependencias

- **Migración 067** (`067_notifications.sql`): tres tablas tenant nuevas con RLS en la misma migración y una versión nueva de `claim_outbox_events` (§3).
- **Módulo nuevo** `backend/app/modules/notifications/`, con router registrado en `backend/app/main.py`.
- **Eventos de outbox nuevos:** `NOTIFICATION_INBOX` (uno por aviso) y `NOTIFICATION_EMAIL` (uno por destinatario de correo). No se publican en Redis ni en Socket.IO.
- Sin permisos nuevos, sin campos públicos nuevos y sin variables de entorno nuevas: se reutilizan SMTP y `FRONTEND_BASE_URL`. `engine_version` sigue en `2026.1`. Sin dependencias nuevas.
- **Dos PR de implementación:** bloque A (backend y migración, T1–T5) y bloque B (frontend, E2E y documentación, T6–T8), apilados sobre el [PR #122](https://github.com/edsel9ra/bracket-craft/pull/122).

## 2. Base de datos (migración 067)

| Tabla | Columnas clave | RLS y privilegios de `bracket_app` |
|---|---|---|
| `notifications` | `id`, `organization_id`, `notification_type` (`match_scheduled`, `result_confirmed`, `walkover_declared`, `sanction_generated`), `tournament_id`, `match_id` (nulo en `match_scheduled`), `suspension_id` (solo en `sanction_generated`), `match_count` (solo en `match_scheduled`, > 0), `created_at`. `CHECK` por tipo. FK compuestas `(id, organization_id)` a torneo, partido y suspensión. | `ENABLE` + `FORCE`. `SELECT` solo si `organization_id` es la del contexto y existe una entrega `delivered` de bandeja al usuario del contexto. Sin `INSERT`/`UPDATE`/`DELETE` directos. |
| `notification_recipients` | `id`, `organization_id`, `notification_id`, `user_id`, `channel` (`inbox`, `email`), `outbox_event_id` (`UNIQUE`), `outcome` (`pending`, `delivered`, `withheld`), `delivered_at`, `read_at`. `UNIQUE (notification_id, user_id, channel)`. | `ENABLE` + `FORCE`. `SELECT` solo de las filas propias (organización y usuario del contexto). Sin escritura directa. |
| `notification_preferences` | `organization_id`, `user_id`, `notification_type`, `channel`, `enabled`, `updated_at`. PK `(organization_id, user_id, notification_type, channel)`. | `ENABLE` + `FORCE`. `SELECT`, `INSERT` y `UPDATE` solo de las filas propias y con membresía activa (`WITH CHECK` igual). Sin `DELETE`. |

Funciones `SECURITY DEFINER` con `search_path` fijo, `REVOKE ... FROM PUBLIC` y `GRANT EXECUTE` a `bracket_app`, siguiendo el patrón de la 040:

- `record_notification(type, tournament_id, match_id, suspension_id, match_count) RETURNS UUID`. Exige que el torneo, el partido y la suspensión sean de la organización del contexto y que el usuario del contexto sea miembro activo. Inserta el aviso y, para cada miembro activo de la organización, una fila de destinatario por canal activado según `notification_channel_enabled` (RF-004, RF-006), y encola los eventos en `outbox_events`: un `NOTIFICATION_INBOX` con `{"notification_id"}` y un `NOTIFICATION_EMAIL` por destinatario de correo con `{"recipient_id"}`.
- `notification_channel_enabled(org, user, type, channel) RETURNS BOOLEAN`. Preferencia guardada o, si no hay, el valor por defecto: bandeja `TRUE` y correo `FALSE` (DA-2).
- `deliver_notification_inbox(event_id) RETURNS INT`. Exige el evento reclamado (`processing`, tipo y payload exactos, como `sanction_claimed_notice`). Para cada destinatario de bandeja `pending` vuelve a comprobar la membresía activa y la preferencia (RF-007) y lo marca `delivered` o `withheld`. Es idempotente.
- `notification_email_payload(event_id) RETURNS JSONB`. Mismas comprobaciones. Si el destinatario ya no cumple, lo marca `withheld` y devuelve `NULL`. Si cumple, devuelve `recipient` (correo de la cuenta), el tipo, el nombre del torneo, los nombres de los equipos, `match_count` y el `id` del aviso. Nunca devuelve el nombre del jugador (DA-4).
- `record_notification_email_delivery(event_id)`. Marca `delivered` tras el envío.
- `mark_notifications_read(ids UUID[] | NULL)`. Fija `read_at` solo en las entregas propias de bandeja `delivered` de la organización del contexto. `NULL` significa todas.
- `claim_outbox_events(p_limit)`: `CREATE OR REPLACE` que excluye `NOTIFICATION_EMAIL`. `claim_notification_email_events(p_limit)`, nueva, reclama solo `NOTIFICATION_EMAIL` con el mismo bloqueo y la misma caducidad. `complete_outbox_event` y `fail_outbox_event` no cambian: 5 intentos con 5 s de espera (RF-012).

Verificación: la migración se aplica sobre un volumen limpio y sobre uno ya migrado hasta la 066, y reaplicar el runner no cambia nada. `sh -n infra/postgres/migrate.sh` sigue pasando.

## 3. Backend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `backend/app/modules/notifications/catalog.py` | Funciones puras. `NOTIFICATION_TYPES` y `CHANNELS` en orden fijo, `DEFAULT_ENABLED = {"inbox": True, "email": False}` y `effective_preferences(saved) -> list[...]` (tipo × canal con su valor guardado o el defecto). `email_message(payload, base_url) -> (subject, body)`, un texto bilingüe ES/EN sin nombres de jugador, con el enlace `{base_url}/workspace/notifications`. | RF-001, RF-006, RF-011 |
| `backend/app/modules/notifications/recorder.py` | `record_notification(db, type, *, tournament_id, match_id=None, suspension_id=None, match_count=None)`. Llama a la función SQL dentro de la transacción del hecho y no hace nada si `match_count == 0` (caso límite 4). | RF-002 |
| `backend/app/modules/notifications/service.py` | `NotificationService`, con `set_rls_context` en cada transacción. `list` (paginado, del más reciente al más antiguo, con tipo, fecha, torneo, partido con sus equipos, `match_count`, `read_at` y, en `sanction_generated`, jugador, equipo y partidos de suspensión leídos con la RLS del miembro en ese momento; RF-009), `unread_count`, `mark_read`, `mark_all_read`, `preferences` y `save_preferences`. | RF-005, RF-008–RF-010, RF-013 |
| `backend/app/modules/notifications/router.py`, `schemas.py` | Endpoints de §5. Modelos `extra="forbid"`. | RF-005, RF-008, RF-010 |
| `backend/app/modules/notifications/delivery.py` | Handlers del worker. `deliver_inbox(db, event)` y `deliver_email(db, event)`, que pide el payload, envía con `send_notification_email` si no es `NULL` y registra la entrega. Una excepción del SMTP se propaga para que el evento se reintente. | RF-007, RF-011, RF-012 |
| `backend/app/core/email.py` | `send_notification_email(recipient, subject, body)` sobre `_send_account_email`. | RF-011 |
| `backend/app/workers/outbox.py` | `process_once`: rama `NOTIFICATION_INBOX` → `deliver_inbox`, nunca hacia Redis. `process_notification_emails()` reclama con `claim_notification_email_events(20)`, y `_run_notification_email_loop` corre en un bucle aparte junto a `_run_loop` y `_run_account_email_loop`. | RF-007, RF-012, RNF-002 |
| `backend/app/modules/tournaments/routes/matches.py` | Tras persistir el calendario, en la misma transacción: `generate_single_elimination_matches` (eliminatoria y liga o grupos), `draw_stage_schedule` (sorteo, también Swiss) y `create_match` (alta, `match_count=1`). Un aviso `match_scheduled` por operación con su `match_count` (DA-3). | RF-001, RF-002 |
| `backend/app/modules/matches/service.py` | En `execute`, tras la auditoría: `result_confirmed` en un cierre normal o administrativo y `walkover_declared` en `_execute_walkover`. Un `sanction_generated` por cada fila de `_insert_suspensions` que sí se haya creado. | RF-001, RF-002 |
| `backend/app/main.py` | Registrar `notifications_router`. | — |

No se tocan los productores de la 033 ni de la 034 (RF-003). La rectificación no llama a `record_notification`, así que no genera avisos de resultado ni de sanción.

## 4. Algoritmo

```
hecho(transacción):
    ... escritura del hecho ...
    si tipo == match_scheduled y match_count == 0: no hacer nada
    record_notification(tipo, ...)         # misma transacción (RF-002)

record_notification (SQL):
    validar organización del contexto y membresía del autor
    n = insertar aviso
    insertar evento NOTIFICATION_INBOX {notification_id: n}
    para cada miembro activo m de la organización:
        si notification_channel_enabled(m, tipo, inbox): destinatario(m, inbox, evento de bandeja)
        si notification_channel_enabled(m, tipo, email):
            e = insertar evento NOTIFICATION_EMAIL {recipient_id}
            destinatario(m, email, e)

worker, bucle del outbox:      NOTIFICATION_INBOX → deliver_notification_inbox (revalida, marca)
worker, bucle de correo aparte: NOTIFICATION_EMAIL → payload (revalida o withheld) → SMTP → delivered
                                si falla el SMTP: fail_outbox_event (reintento, sin duplicar)
```

## 5. Interfaz

| Endpoint (`/api/v1`) | Quién | Respuesta |
|---|---|---|
| `GET /notifications?limit&offset` | Cualquier miembro | `{items, unread_count}`, solo avisos propios entregados en la bandeja de la organización activa. |
| `POST /notifications/{id}/read` | Cualquier miembro | 204. Un aviso ajeno o inexistente responde el mismo 404. |
| `POST /notifications/read-all` | Cualquier miembro | 204. |
| `GET /notification-preferences` | Cualquier miembro | `{items: [{type, channel, enabled}]}` con los ocho pares, aplicando los valores por defecto. |
| `PUT /notification-preferences` | Cualquier miembro | Mismo cuerpo, todos los pares exactos; si falta o sobra alguno, 422. Devuelve el estado guardado. |

### Frontend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `frontend/app/utils/notifications.ts` | Funciones puras: texto i18n por tipo, enlace de destino (partido → `/workspace/matches/{id}`, calendario → sección de calendario del torneo, sanción → partido de origen) y orden de las preferencias. | RF-008, RF-009 |
| `frontend/app/composables/useNotifications.ts` | Bandeja, no leídos y marcar como leído, todo con `useApi`. Se invalida al cambiar de organización o de usuario, como `useSanctionNotifications`. | RF-008, RF-010 |
| `frontend/app/composables/useNotificationPreferences.ts` | Carga y guardado de preferencias con `useApi`. | RF-005 |
| `frontend/app/pages/workspace/notifications.vue`, `components/notification/NotificationInbox.vue`, `NotificationPreferences.vue` | Bandeja paginada, con los no leídos marcados, «Marcar como leído» y «Marcar todo como leído». Preferencias en una tabla tipo × canal con casillas nativas y un botón «Guardar». | RF-005, RF-008–RF-010, RNF-003 |
| `frontend/app/components/WorkspaceShell.vue` | Enlace «Notificaciones» para todos los miembros, con el número de no leídos como texto accesible. | RF-008 |
| `frontend/app/composables/useI18n.ts` | Claves `notification.*` en ES y EN, con paridad. | RNF-003 |
| `frontend/e2e/notifications.spec.ts` | Contratos ficticios, como en la 045. Bandeja y preferencias con teclado, y axe en ambos temas a 1440 y 390 px. | RNF-003 |
| `README.md`, `AGENTS.md`, `docs/manual-usuario.md`, `MEMORY.md`, `docs/informe-funciones-adicionales.md` | Comportamiento, endpoints y despliegue de la migración 067 antes que la API y el worker. F6 queda parcialmente implementada; los webhooks, en la 047. | — |

## 6. Decisiones

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Destinatarios calculados al registrar el hecho y revalidados al entregar | Calcularlos solo al entregar | RF-004 los fija al registrar. Así un miembro que entra después no recibe avisos anteriores y RF-007 cubre las bajas. |
| El correo va por el outbox, pero lo reclama un bucle aparte | Enviarlo en el bucle principal, como la 034 | RNF-002: un SMTP lento no debe frenar el tiempo real ni la bandeja. RF-012 exige reintentar con el outbox. |
| Un evento de bandeja por aviso y uno de correo por destinatario | Un evento por destinatario y canal | La entrega en bandeja no tiene efecto externo y se resuelve en una sola llamada SQL. El correo necesita reintentos independientes por destinatario. |
| El nombre del jugador sancionado se lee al listar | Copiarlo en el aviso | Así lo fija RF-009, y no se duplica un dato personal. |
| La resolución administrativa cuenta como «resultado confirmado» | No avisar | Cierra el acta con un resultado confirmado. El W.O. tiene su propio tipo. |
| Correo bilingüe (ES y luego EN) | Correo solo en español, o elegir idioma | Las cuentas no guardan idioma y RNF-003 pide ES/EN. |
| Sin Socket.IO para los no leídos; se recargan al navegar y al abrir la bandeja | Emitir un evento privado nuevo | La spec no pide avisos en vivo, y un evento privado nuevo cambiaría el filtro de la 035. |
| Sin purga ni retención de avisos | Purgar los antiguos | Está fuera de la spec. Si hace falta, se tratará en otra. |

## 7. Estrategia de pruebas

| Nivel | Prueba | RF / caso |
|---|---|---|
| Unidad | `test_notification_catalog.py`: catálogo, valores por defecto, `effective_preferences` y correo bilingüe sin nombre de jugador y con enlace. | RF-001, RF-006, RF-011 |
| BD opt-in | `test_notifications_migration.py`: tablas, RLS `FORCE` y políticas; volumen limpio y ya migrado; `claim_outbox_events` no reclama `NOTIFICATION_EMAIL`. | RF-013 |
| BD opt-in | `test_notification_producers.py`: un aviso por generación (eliminatoria, liga, grupos, Swiss) y por alta; ninguno si no se crean partidos; cierre normal y administrativo, W.O. y una sanción por suspensión creada; si la transacción se revierte no queda nada; la rectificación no genera avisos. | RF-001–RF-004, CL 3–5 |
| BD opt-in | `test_notification_delivery.py`: bandeja `delivered`/`withheld` tras perder la membresía o desactivar el canal; correo con SMTP simulado, reintento sin duplicar y `withheld` sin reintento; sin SMTP queda fallido y reintentable; un SMTP bloqueado no frena el bucle del outbox. | RF-007, RF-011, RF-012, RNF-002, CL 1, 2, 7 |
| BD opt-in | `test_notification_api.py`: lista, orden, paginación, no leídos y marcar como leído; nombre del jugador en la bandeja; preferencias propias con 422 si están incompletas; otra organización y otro miembro no ven ni marcan nada (mismo 404); varias organizaciones; aviso de un torneo archivado. | RF-005, RF-008–RF-010, RF-013, CL 6, 8 |
| Frontend | `notifications.test.ts`, `notification-components.test.ts` e i18n: textos, enlaces, invalidación por organización y paridad ES/EN. | RF-008–RF-010, RNF-003 |
| E2E | `notifications.spec.ts`: teclado y axe en ambos temas a 1440 y 390 px. | RNF-003 |

## 8. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 2.1 Aislamiento por RLS | Sí | Las tres tablas nacen con RLS `FORCE` y políticas por organización y usuario en la 067. |
| 2.2 Sin `BYPASSRLS` | Sí | Las funciones `SECURITY DEFINER` validan la organización del contexto o el evento reclamado, como en la 040. No cambia el rol de la aplicación. |
| 2.3 Lo publicado es inmutable | Sí | Los avisos solo leen hechos ya cerrados y no los modifican. |
| 2.4 Migraciones append-only | Sí | Migración nueva 067. `claim_outbox_events` se redefine en ella, sin editar `01_schema.sql`. |
| 2.5 Proyección pública mínima | Sí | No hay campos públicos nuevos. El correo no lleva nombres de jugadores, documentos ni fechas de nacimiento. |
| 2.6 Sin secretos por defecto | Sí | No hay variables nuevas; se reutiliza SMTP. |
| 2.7 Administración global | No | — |
| 2.8 Verificación | Sí | CI backend, frontend, infraestructura, seguridad y E2E. |
| 2.9 Código de desarrollo | Sí | No hay seed nuevo, y el E2E usa contratos ficticios. |
| 3.1 `set_rls_context` en la transacción | Sí | Lo usan `NotificationService` y los productores, que ya lo hacen. |
| 3.2 Módulo propio y outbox | Sí | Módulo `notifications`, registrado en `main.py`. Las entregas, solo en el worker. |
| 3.3 `useApi` | Sí | Los dos composables nuevos. |
| 3.4 Datos personales fuera de logs | Sí | Los logs del worker solo llevan el id del evento y el tipo de error, nunca el correo. |
| 3.6 Rectificación | Sí | No genera avisos (RF-003). |
| §4 Criterios de base de datos, backend y frontend | Sí | Volumen limpio y ya migrado, `pytest -q`, `compileall`, `pnpm test`, `typecheck`, `build` y documentación. |
