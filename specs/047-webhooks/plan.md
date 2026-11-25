# Plan — Spec 047: Webhooks firmados por organización (F6, parte 2)

Estado: aprobado por el usuario el 2026-11-24 («Apruebo el plan y las tareas de la spec 047. Empieza por T1»).

## 1. Alcance y dependencias

- **Constitución 2.1.0** (PR #126, fusionado): `WEBHOOK_SECRET_KEY` es un secreto propio, distinto de `PLAYER_DATA_KEY`.
- **Migración 068** (`068_webhooks.sql`): dos tablas tenant nuevas con RLS en la misma migración, el permiso `MANAGE_WEBHOOKS`, una versión nueva de `record_notification` y de `claim_outbox_events` y funciones de entrega (§2). No se edita la 067.
- **Módulo nuevo** `backend/app/modules/webhooks/`, con router registrado en `backend/app/main.py`.
- **Evento de outbox nuevo:** `WEBHOOK_DELIVERY` (uno por entrega). No se publica en Redis ni en Socket.IO y lo reclama un bucle propio del worker.
- **Variable nueva:** `WEBHOOK_SECRET_KEY` (API y worker). Sin dependencias nuevas: `httpx` ya está en `requirements.txt` y el cifrado usa `pgcrypto`, como `PLAYER_DATA_KEY`. `engine_version` sigue en `2026.1`.
- **Dos PR de implementación:** bloque A (backend y migración, T1–T5) y bloque B (frontend, E2E y documentación, T6–T8), apilados sobre el [PR #125](https://github.com/edsel9ra/bracket-craft/pull/125).

## 2. Base de datos (migración 068)

| Tabla | Columnas clave | RLS y privilegios de `bracket_app` |
|---|---|---|
| `organization_webhooks` | `id`, `organization_id`, `url` (`CHECK`: empieza por `https://`, ≤ 2048), `event_types TEXT[]` (no vacío, subconjunto del catálogo de la 046), `is_active`, `secret_encrypted BYTEA`, `created_by_member_id`, `created_at`, `updated_at`. | `ENABLE` + `FORCE`. `SELECT`, `INSERT`, `UPDATE` y `DELETE` solo con `organization_id` del contexto. `SELECT` por columnas **sin** `secret_encrypted`: la API puede escribir el secreto cifrado, pero nunca leerlo (patrón *write-only* del documento y la fecha de nacimiento). |
| `webhook_deliveries` | `id` (identificador estable de la entrega, RF-007), `organization_id`, `webhook_id` (FK `ON DELETE CASCADE`), `notification_id` (nulo en la prueba), `event_type` (catálogo de la 046 o `webhook_test`), `body JSONB` (cuerpo fijado al registrar, CL-6), `status` (`pending`, `delivered`, `failed`, `rejected`, `discarded`), `attempts`, `last_status_code`, `last_attempt_at`, `outbox_event_id` (`ON DELETE SET NULL`, como en la 067), `created_at`. | `ENABLE` + `FORCE`. Solo `SELECT` con `organization_id` del contexto. La escritura pasa por las funciones de abajo. |

Permiso: `MANAGE_WEBHOOKS` se añade a `role_definitions` y a `roles` ya materializados de `owner` y `administrator`, como en la 064 (DA-1).

Funciones `SECURITY DEFINER` con `search_path` fijo, `REVOKE ... FROM PUBLIC` y `GRANT EXECUTE` a `bracket_app`:

- `record_notification(...)`: `CREATE OR REPLACE` con la misma firma y el mismo comportamiento de la 067. Añade, para cada webhook activo de la organización suscrito al tipo, y solo si el torneo está en `v_public_tournaments` (DA-5), una fila en `webhook_deliveries` y un `WEBHOOK_DELIVERY` con `{"delivery_id"}` (RF-005, CL-1, CL-7). Así todos los productores de la 046 crean las entregas en la transacción del hecho sin cambiar su código. Los webhooks se leen con `FOR KEY SHARE`: un borrado o una edición en curso se espera y el webhook se salta si ya no procede, sin abortar el hecho.
- `webhook_event_body(type, tournament, match, delivery, occurred_at) RETURNS JSONB`: arma el cuerpo de RF-006 leyendo la proyección pública del momento: nombre del torneo, `match_count`, nombres de los equipos, marcador final y, en el W.O., `winner_team_id`. La sanción solo lleva torneo y partido (DA-2).
- `webhook_managed(webhook_id)` (interna): exige `MANAGE_WEBHOOKS` en la organización del contexto (`WEBHOOK_MANAGER_REQUIRED`) y devuelve el webhook bloqueado; uno de otra organización o inexistente da el mismo `WEBHOOK_NOT_FOUND`.
- `enqueue_webhook_test(webhook_id) RETURNS UUID`: entrega de prueba del webhook de la organización del contexto (RF-012); un webhook desactivado responde `WEBHOOK_INACTIVE`.
- `discard_webhook_deliveries(webhook_id)`: marca `discarded` las entregas `pending` al desactivar y cierra sus eventos aún pendientes (RF-008, CL-2).
- `webhook_claimed_delivery(event_id, key) RETURNS JSONB`: exige el evento reclamado (`processing`, tipo y payload exactos, como `notification_claimed_event`). Si el webhook ya no existe, está desactivado o no está suscrito al tipo, marca la entrega `discarded` y devuelve `NULL`. Si sigue vigente, devuelve `url`, `secret` (descifrado con `pgp_sym_decrypt` y la clave recibida), `delivery_id`, `event_type` y `body`. Así los intentos siguientes a una rotación firman con el secreto nuevo (CL-3).
- `record_webhook_attempt(event_id, outcome, status_code)`: `outcome` ∈ `delivered`, `failed`, `rejected`. Actualiza la entrega y el evento. Si falla y quedan intentos, deja el evento `pending` con `available_at` según la tabla de esperas (1, 5, 15 y 30 min y 2 h); al sexto intento o con `rejected`, lo marca final (RF-009, RF-011). Los estados finales cierran el evento como `processed` (con `last_error` `WEBHOOK_FAILED`/`WEBHOOK_REJECTED`), para que la retención del outbox (034) lo purgue; la entrega guarda el resultado. Si la entrega ya no está pendiente (descartada o eliminada), solo cierra el evento.
- `claim_outbox_events(p_limit)`: `CREATE OR REPLACE` que además excluye `WEBHOOK_DELIVERY`. `claim_webhook_delivery_events(p_limit)`, nueva, reclama solo `WEBHOOK_DELIVERY` con el mismo bloqueo y la misma caducidad. La retención del outbox (034) no cambia: borra eventos ya terminados y la entrega conserva su historial.
- `purge_webhook_deliveries(cutoff, batch)`: borra entregas finales de más de 30 días; la llama la purga horaria del worker.

Verificación: la migración se aplica sobre un volumen limpio y sobre uno ya migrado hasta la 067, y reaplicar el runner no cambia nada. `sh -n infra/postgres/migrate.sh` sigue pasando.

## 3. Backend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `backend/app/core/config.py` | `webhook_secret_key` (mín. 32 caracteres) con default solo de desarrollo; fuera de desarrollo se rechaza ese valor (RNF-002). | RF-003 |
| `backend/app/modules/webhooks/catalog.py` | Funciones puras. `EVENT_TYPES` (los de la 046), `TEST_TYPE`, `MAX_WEBHOOKS = 10`, `MAX_ATTEMPTS = 6`, `RETRY_DELAYS`, `validate_url(url)` (`https`, solo ASCII, sin credenciales, ≤ 2048, con host; devuelve el esquema en minúsculas), `audit_host(url)`, `generate_secret()`, `serialize_body(body) -> bytes` (JSON canónico), `sign(secret, timestamp, body) -> str` (HMAC-SHA256 de `"{timestamp}.{body}"`) y `signature_headers(...)`. `timestamp` llega como parámetro. | RF-002, RF-003, RF-006, RF-007, RF-011 |
| `backend/app/modules/webhooks/network.py` | Funciones puras `address_allowed(ip)`: rechaza privadas, loopback, enlace local, CGNAT `100.64.0.0/10`, multidifusión, reservadas, no especificadas, metadatos (`169.254.169.254`, `fd00:ec2::254`) e IPv6 mapeadas a una IPv4 prohibida. `resolve_target(host, port, resolver)` resuelve y exige que **todas** las direcciones estén permitidas (fail closed). | RF-009 |
| `backend/app/modules/webhooks/service.py` | `WebhookService` con `set_rls_context` y `require_permission(..., "MANAGE_WEBHOOKS")` en cada transacción. Alta con `pg_advisory_xact_lock` por organización y recuento (máximo 10), secreto cifrado con `pgp_sym_encrypt` en el `INSERT`; edición, activación (desactivar descarta las pendientes), eliminación, rotación, prueba y lectura de entregas (50, 30 días). Cada cambio escribe su entrada de auditoría con `performed_by_member_id` y solo el dominio. | RF-001–RF-004, RF-008, RF-012, RF-013 |
| `backend/app/modules/webhooks/router.py` y `schemas.py` | Endpoints de §5; modelos `extra="forbid"`. Un webhook de otra organización o inexistente responde el mismo 404. | RF-001, RF-013 |
| `backend/app/modules/webhooks/delivery.py` | `deliver_webhook(db, event, *, key, now, resolver, client)`: lee `webhook_claimed_delivery`; resuelve y comprueba el destino; hace el `POST` a la IP comprobada con `Host` y SNI del dominio (`extensions={"sni_hostname": host}`, así el certificado se verifica contra el dominio), `follow_redirects=False`, sin proxies del entorno ni cookies (el cliente es compartido), `Host` con corchetes si es una IPv6 literal, timeout total de 10 s, sin leer el cuerpo de la respuesta; registra el intento con `record_webhook_attempt`. Los logs solo llevan el id del evento y el tipo de error. | RF-006–RF-011, RNF-002 |
| `backend/app/workers/outbox.py` | Bucle `_run_webhook_loop` aparte, con hasta 10 entregas en paralelo (`asyncio.Semaphore`), cada una con su sesión: un destino lento no frena a los demás ni a los otros bucles (RNF-001). | RNF-001 |
| `backend/app/workers/retention.py` | La purga horaria llama también a `purge_webhook_deliveries`. | RF-012 |
| `backend/app/modules/organization_audit/catalog.py` | Acciones `CREATE_WEBHOOK`, `UPDATE_WEBHOOK`, `ROTATE_WEBHOOK_SECRET`, `SET_WEBHOOK_ACTIVE` y `DELETE_WEBHOOK` (entidad `organization_webhooks`), con los campos `host`, `event_types` e `is_active`. | RF-004 |

### Cuerpo y firma (RF-006, RF-007)

```json
{
  "id": "<delivery_id>",
  "type": "result_confirmed",
  "occurred_at": "2026-11-24T21:00:00Z",
  "organization_id": "…", "tournament_id": "…", "match_id": "…",
  "data": {
    "tournament_name": "Copa 2026",
    "home_team": {"id": "…", "name": "Halcones"},
    "away_team": {"id": "…", "name": "Tigres"},
    "home_score": 2, "away_score": 1
  }
}
```

- `match_scheduled`: `data` = `tournament_name`, `match_count`; sin `match_id`.
- `walkover_declared`: lo mismo que `result_confirmed` más `winner_team_id`.
- `sanction_generated`: `data` = `tournament_name`; con `match_id`, sin jugador ni equipo.
- `webhook_test`: `data` = `{}`; sin torneo ni partido.

Cabeceras: `Content-Type: application/json`, `User-Agent: BracketCraft-Webhooks/1`, `X-BracketCraft-Event`, `X-BracketCraft-Delivery`, `X-BracketCraft-Timestamp` (segundos Unix del intento) y `X-BracketCraft-Signature: v1=<hex>`.

### Pseudocódigo del intento

```
event = claim_webhook_delivery_events(free_slots)
target = webhook_claimed_delivery(event, key)
si target es NULL: complete_outbox_event(event); fin            # descartada (RF-008)
ips = resolver(host, port)
si alguna ip no está permitida o no resuelve: record(rejected)  # sin reintento (RF-009)
body = serialize_body(target.body); ts = now()
resp = POST https://{ips[0]}:{port}{path} Host/SNI=host, headers firmados, timeout 10 s, sin redirecciones
si 2xx: record(delivered) si no: record(failed, status)          # 3xx, 4xx, 5xx o sin respuesta (RF-010, RF-011)
```

## 4. Configuración y secretos

- `.env.example`: `WEBHOOK_SECRET_KEY` con un valor de desarrollo explícito.
- `docker-compose.yml`: la API y el worker la reciben con ese default; `docker-compose.production.yml`: `${WEBHOOK_SECRET_KEY:?...}` en ambos.
- `infra/scripts/check_env_contract.py`: la variable se atribuye a la API y al worker.
- Nunca se registra en logs; el secreto de cada webhook tampoco (RNF-002).

## 5. Interfaz

| Endpoint | Respuesta | RF |
|---|---|---|
| `GET /api/v1/webhooks` | Lista: `id`, `url`, `event_types`, `is_active`, `created_at`, `updated_at`. Sin secreto. | RF-001 |
| `POST /api/v1/webhooks` `{url, event_types}` | 201 con el webhook y `secret` (única vez). 422 por URL inválida; 409 `WEBHOOK_LIMIT_REACHED` con 10. | RF-002, RF-003 |
| `PATCH /api/v1/webhooks/{id}` `{url?, event_types?, is_active?}` | El webhook. Desactivar descarta las pendientes. | RF-001, RF-008 |
| `DELETE /api/v1/webhooks/{id}` | 204. | RF-001, RF-008 |
| `POST /api/v1/webhooks/{id}/rotate-secret` | `{secret}` (única vez). | RF-003 |
| `POST /api/v1/webhooks/{id}/test` | 202 `{delivery_id}`. Webhook desactivado: 409. | RF-012 |
| `GET /api/v1/webhooks/{id}/deliveries` | Hasta 50 de 30 días, de la más reciente a la más antigua: `id`, `event_type`, `created_at`, `attempts`, `last_status_code`, `status`. | RF-012 |

Sin `MANAGE_WEBHOOKS`: 403, como el resto de permisos. Otra organización o inexistente: el mismo 404.

**Frontend** (todo por `useApi`):

- `utils/webhooks.ts`: tipos, catálogo y validación de URL espejo de la del servidor.
- `composables/useWebhooks.ts`: lista, alta, edición, activación, eliminación, rotación, prueba y entregas; se invalida al cambiar de organización.
- Página `/workspace/webhooks`, enlazada en `WorkspaceShell` solo con `MANAGE_WEBHOOKS`.
- `components/webhooks/WebhookForm.vue` (URL y casillas nativas por tipo), `WebhookSecretDialog.vue` (el secreto se muestra una vez, con botón de copiar y aviso de que no se volverá a mostrar), `WebhookDeliveries.vue` (tabla de entregas).
- Rotar, desactivar y eliminar piden confirmación con `useConfirm` (`singleFlight`).
- Claves `webhook.*` y las nuevas acciones de `audit.*` en ES y EN.

## 6. Decisiones

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Las entregas se crean en `record_notification` | Llamar a un registrador nuevo en cada productor | Una sola puerta: todos los productores de la 046 quedan cubiertos sin tocarlos y siempre en la transacción del hecho. |
| El cuerpo se fija al registrar | Armarlo en cada intento | CL-6: los datos son los del momento del hecho y los reintentos envían lo mismo. |
| Cifrado con `pgcrypto` y lectura del secreto solo en una función del worker | Cifrar en Python con una dependencia nueva | Mismo patrón que `PLAYER_DATA_KEY`, sin dependencias nuevas; la API no puede leer el secreto cifrado. |
| Reintentos en una función propia | `fail_outbox_event` (5 intentos, 5 s) | DA-4 fija 6 intentos y esperas de 1 min a 2 h; el resto del outbox no cambia. |
| Conexión a la IP comprobada con SNI del dominio | Volver a resolver en `httpx` | RF-009: evita que un DNS que cambia entre la comprobación y la conexión lleve a una red interna. |
| Bucle aparte con 10 entregas en paralelo | Procesar en el bucle del outbox | RNF-001. |
| Desactivar descarta las pendientes al momento y el worker vuelve a comprobar | Solo la comprobación del worker | RF-008 y CL-2: el historial refleja el descarte en cuanto ocurre. |
| La sanción no lleva los equipos del partido | Incluirlos | DA-2 la deja sin jugador ni equipo; basta con el `match_id`. |
| Las entregas de más de 30 días se purgan | Conservarlas | RF-012 solo muestra 30 días; la tabla no crece sin límite. |
| La validación de la URL en el alta no resuelve DNS | Rechazar al dar de alta las IP internas | La spec lo exige en cada intento (RF-009, CL-4); el alta no hace red. |

## 7. Estrategia de pruebas

| Nivel | Prueba | RF / caso |
|---|---|---|
| Unidad | `test_webhook_catalog.py`: URL, dominio para la auditoría, secreto, JSON canónico, firma con vector conocido, cabeceras y esperas. | RF-002, RF-003, RF-006, RF-007, RF-011 |
| Unidad | `test_webhook_network.py`: cada rango prohibido, IPv6 mapeada, resolución mixta pública y privada, sin resolución. | RF-009, CL-4 |
| Unidad | `test_config.py`: `WEBHOOK_SECRET_KEY` de desarrollo rechazada fuera de desarrollo. | RF-003, RNF-002 |
| BD opt-in | `test_webhooks_migration.py`: tablas, RLS `FORCE`, `bracket_app` sin `SELECT` de `secret_encrypted`, permiso en owner y administrador; entregas en la transacción del hecho y ninguna si se revierte; descarte; reintentos; volumen limpio y ya migrado; `claim_outbox_events` no reclama `WEBHOOK_DELIVERY`. | RF-005, RF-008, RF-011, RF-013, CL-1, CL-7 |
| BD opt-in | `test_webhook_api.py`: CRUD con y sin permiso, límite de 10 con concurrencia, secreto solo en alta y rotación, auditoría solo con el dominio, otra organización con el mismo 404, prueba, historial 50/30 días. | RF-001–RF-004, RF-012, RF-013 |
| BD opt-in | `test_webhook_delivery.py`: servidor HTTPS local de prueba con certificado propio y resolvedor inyectado; firma verificable, mismo id en reintentos, rotación entre intentos, 3xx sin seguir, 4xx/5xx/timeout reintentados, sexto intento final, rechazo de red sin reintento, desactivado o eliminado descartado, destino lento sin frenar a otro; cuerpo sin nombres de jugador; rectificación sin entrega. | RF-006–RF-011, RNF-001, RNF-002, CL-2, CL-3, CL-5, CL-8 |
| Frontend | `webhooks.test.ts` y `webhook-components.test.ts`: validación, secreto mostrado una vez, confirmaciones, enlace solo con permiso y paridad ES/EN. | RF-001, RF-003, RF-012, RNF-004 |
| E2E | `webhooks.spec.ts` (contratos ficticios): alta, secreto, prueba, entregas y rotación con teclado; axe en ambos temas a 1440 y 390 px. | RNF-004 |

## 8. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 2.1 Aislamiento por RLS | Sí | Las dos tablas nacen con RLS `FORCE` y políticas por organización en la 068. |
| 2.2 Sin `BYPASSRLS` | Sí | Las funciones `SECURITY DEFINER` validan la organización del contexto o el evento reclamado, como en la 067. |
| 2.3 Lo publicado es inmutable | Sí | Las entregas solo leen hechos ya cerrados. |
| 2.4 Migraciones append-only | Sí | Migración nueva 068; `record_notification` y `claim_outbox_events` se redefinen en ella, sin editar la 067. |
| 2.5 Proyección pública mínima | Sí | El cuerpo solo lleva datos ya públicos; sin nombres de jugador, documentos ni fechas de nacimiento. Sin campos públicos nuevos. |
| 2.6 Sin secretos por defecto | Sí | `WEBHOOK_SECRET_KEY` solo tiene default en `.env.example`/compose de desarrollo y se rechaza fuera de desarrollo (§3.4, 2.1.0). |
| 2.7 Administración global | No | La plataforma no ve webhooks. |
| 2.8 Verificación | Sí | CI backend, frontend, infraestructura, seguridad y E2E. |
| 2.9 Código de desarrollo | Sí | Sin seed nuevo; el servidor HTTPS de prueba solo vive en los tests. |
| 3.1 `set_rls_context` en la transacción | Sí | `WebhookService` y el worker (por las funciones). |
| 3.2 Módulo propio y outbox | Sí | Módulo `webhooks`; las entregas, solo en el worker. |
| 3.3 `useApi` | Sí | `useWebhooks`. |
| 3.4 Secretos y datos personales fuera de logs | Sí | Secreto cifrado con `WEBHOOK_SECRET_KEY`, solo en alta y rotación; logs con id y tipo de error. |
| 3.6 Rectificación | Sí | No genera entregas (CL-8). |
| §4 Criterios de base de datos, backend y frontend | Sí | Volumen limpio y ya migrado, `pytest -q`, `compileall`, `pnpm test`, `typecheck`, `build` y documentación. |
