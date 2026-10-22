# Plan 009 — Ciclo de vida de las invitaciones y salud del worker

Spec: `specs/009-invitaciones-y-salud-del-worker/spec.md` (aprobada 2026-10-21).
Estado del plan: aprobado e implementado; la validación cerró el 2026-10-21 y la corrección de RF-007 se aplicó en la ronda de corrección posterior a la primera validación.

## Objetivo y alcance técnico

Cerrar los tres huecos de contrato de la spec con cambios localizados y **sin migraciones**:

1. **Reapertura** de una invitación revocada como acción propia (`POST …/reopen`), con token y fecha nuevos sobre la misma fila, una **tercera ruta de materialización** del vencimiento (Q6) y una entrada de auditoría (`REOPEN_INVITATION`).
2. **Reenvío de una revocada → 409** (C-1) con un motivo distinguible y estable.
3. **Salud del worker**: fijar la semántica «bucle detenido = no completa una vuelta en 90 s», dejar las constantes únicas ya existentes como fuente y **verificar la transición real** congelando el bucle de un worker vivo.

No cambia el modelo de autorización (sigue siendo `MANAGE_MEMBERS` por membresía), no se amplía la superficie pública, no hay nuevos eventos de outbox y no se toca el frontend público.

## Decisiones de plan (con alternativa descartada)

1. **La reapertura es un endpoint nuevo**, `POST /api/v1/organizations/invitations/{id}/reopen`, con **200** y la representación de la invitación más `invite_url`. *Descartado:* reutilizar `/resend` con un parámetro `force` o `action`, que mezclaría dos semánticas en una ruta, haría ambiguo el 409 de C-1 y obligaría a versionar el cuerpo.
2. **Identificador estable de error en el cuerpo, campo `code`, aditivo**, al lado del `detail` de siempre. Valores: `INVITATION_NOT_REVOKED`, `INVITATION_OTHER_PENDING`, `INVITATION_ALREADY_ACCEPTED`, `INVITATION_REVOKED_RESEND`. Se traduce **en el cliente**, contra el catálogo del idioma activo. *Descartado:* (a) texto localizado en el servidor, que duplicaría el catálogo en el backend, exigiría negociar `Accept-Language` y dejaría el inglés con el mensaje genérico como hoy; (b) una cabecera `X-Invitation-Error-Code`, invisible en `/docs`, en los registros y para `errorMessage`, y que el cliente actual no lee.
3. **Excepción de dominio `InvitationConflict`** (subclase de `HTTPException`, con `code`) y **un único manejador** registrado en `backend/app/main.py` que devuelve `{"detail": <str>, "code": <str>}`. Starlette resuelve el manejador por MRO, así que la subclase no obliga a tocar cada ruta. *Descartado:* `detail` como objeto `{"code", "message"}`, que rompe el contrato actual (`detail` es cadena) y el `errorMessage` del cliente; y un `JSONResponse` repetido en cada endpoint, que duplica el cuerpo del error en cuatro sitios.
4. **Orden de la transacción de reapertura: permisos → carga con bloqueo → validar 409 → materializar → rotar → auditar.** Los 409 se evalúan **antes** de cualquier escritura, de modo que «un 409 no escribe nada» no dependa solo del rollback. *Descartado:* materializar primero y confiar únicamente en la reversión: da el mismo resultado observable, pero escribe en un camino que nunca persiste y esconde el invariante.
5. **Garantía final de unicidad: el índice único de pendientes por organización y correo**, mapeando `IntegrityError` → 409 `INVITATION_OTHER_PENDING`, igual que hoy en crear y reenviar. *Descartado:* bloquear todas las filas del correo con `ORDER BY id` antes de decidir, que añade serialización y un orden de bloqueo nuevo (la fila objetivo ya se bloqueó antes) sin mejorar la garantía observable.
6. **La materialización reutiliza `_materialize_expired_pending`**, la misma función de crear y reenviar, con el `now` de la petición. *Descartado:* una variante que excluya la fila objetivo: es innecesaria porque el `WHERE` exige `status = 'pending'` y la invitación reabierta está `revoked`.
7. **La auditoría vive en `backend/app/modules/invitations/audit.py`**, con el patrón de `backend/app/modules/matches/audit.py`: payload puro con identificadores y códigos, `INSERT` dentro de la transacción del llamador. *Descartado:* el `INSERT` incrustado en el router (repite SQL y mezcla capas) y meterlo en `lifecycle.py` (módulo puro que no debe hablar con la base de datos).
8. **Salud: el mecanismo no cambia; se fijan y se verifican las constantes únicas.** `HEARTBEAT_MAX_AGE_SECONDS = 90` y `HEARTBEAT_INTERVAL_SECONDS = 10` siguen viviendo solo en `backend/app/workers/heartbeat.py`, y el healthcheck importa la constante en lugar de repetir el número. *Descartado:* convertirlas en variables de entorno del servicio, que duplicarían el umbral en Compose y `.env.example` contra RNF-007 y permitirían dos valores distintos en el mismo despliegue.
9. **Verificación real en un script de operación**, `infra/scripts/verify_worker_loop_health.sh`, que congela el bucle con `kill -STOP 1` dentro del contenedor, sondea `docker inspect` y reanuda con `kill -CONT 1`; códigos de salida 0 (verificado), 1 (no se observó la transición), 2 (no hay Docker → **no ejecutada**). *Descartado:* `docker pause`, que congela también el proceso del healthcheck y confunde «bucle detenido» con «no puedo comprobar»; y un bloque de comandos copiado del README, que no devuelve código de salida ni sirve de evidencia reproducible.
10. **Interfaz verificada con funciones puras y aserciones de fuente**, sin dependencias nuevas. *Descartado:* `@vue/test-utils`/`happy-dom` (los prohíbe RNF-001) y Playwright, que se entrega en la spec 010.
11. **Estado de la operación de invitaciones separado del `saving` de miembros**: un `invitationOperation` (`idle | creating | resending | reopening | revoking`) gobierna el formulario de invitación y los botones de cada fila; `saving` sigue gobernando el directorio de miembros. *Descartado:* reutilizar `saving` para todo, que deshabilitaría el directorio mientras se reenvía y no distingue «operación en curso» de «cargando».

## Archivos y responsabilidades

### Backend

- `backend/app/modules/invitations/errors.py` — **nuevo**. Constantes de los cuatro códigos estables, `InvitationConflict(HTTPException)` con `status_code=409` y atributo `code`, y `conflict_body(exc) -> dict` que construye `{"detail": str, "code": str}` (RF-002, RF-003, RF-007 contrato).
- `backend/app/modules/invitations/lifecycle.py` — ampliado. `reopen_conflict(stored_status, has_live_pending) -> str | None` y `resend_conflict(stored_status) -> str | None`: funciones puras, sin reloj y sin base de datos, que devuelven el código del 409 o `None` (RF-002, RF-003).
- `backend/app/modules/invitations/audit.py` — **nuevo**. `INVITATION_ENTITY_TYPE = "organization_invitations"`, `REOPEN_INVITATION`, `reopen_audit_payload(role_code, previous_status="revoked")` (puro) y `record_invitation_audit(...)` (un `INSERT` en la transacción del llamador) (RF-004).
- `backend/app/modules/invitations/router.py` — nuevo handler `reopen_invitation`; `resend_invitation` gana la guarda de revocada y los 409 con código; `create_invitation` reutiliza `INVITATION_OTHER_PENDING` en su 409 (mismo motivo, sin cambio de comportamiento) (RF-001, RF-002, RF-003, RF-004).
- `backend/app/modules/invitations/schemas.py` — **sin cambios**: `InvitationResponse` ya expone `status`, `expires_at`, `revoked_at`, `updated_at` e `invite_url`.
- `backend/app/main.py` — registra el manejador de `InvitationConflict` (una función de tres líneas); no hay router nuevo que registrar.
- `backend/app/workers/heartbeat.py` — solo documentación: la docstring del módulo fija las definiciones de «bucle detenido» y «vuelta completada» con las mismas palabras que la comprobación (RF-008, RF-010). Las constantes no se mueven.
- `backend/tests/test_invitation_reopen_rules.py` — **nuevo**, sin base de datos (siempre se ejecuta).
- `backend/tests/test_invitations.py` — ampliado con las pruebas de endpoint sobre PostgreSQL (opt-in).
- `backend/tests/test_worker_heartbeat.py` — ampliado con la semántica de salud y la unicidad de constantes.

### Frontend

- `frontend/app/utils/invitationActions.ts` — **nuevo**. Selección de acciones por estado, etiquetas y estado de la operación (RF-005, RF-006).
- `frontend/app/utils/invitationErrors.ts` — **nuevo**. Código estable del 409 → clave i18n, con `null` si el cuerpo no trae código (RF-007).
- `frontend/app/pages/workspace/members.vue` — botones por estado con etiqueta y `aria-label` propios, confirmación antes de reabrir, controles deshabilitados durante la operación, enlace nuevo y mensaje del 409 en el idioma activo (RF-005, RF-006, RF-007).
- `frontend/app/composables/useI18n.ts` — claves nuevas en español e inglés (RF-005, RF-007).
- `frontend/tests/invitation-actions.test.ts` — **nuevo**: funciones puras, catálogo y aserciones de fuente sobre `members.vue`.

### Operación, infraestructura y documentación

- `infra/scripts/verify_worker_loop_health.sh` — **nuevo**; verificación reproducible de RF-011. No se añade a la suite que corre sin contenedores ni al job `backend`.
- `docker-compose.yml` — **sin cambios funcionales**: el healthcheck ya importa `HEARTBEAT_MAX_AGE_SECONDS` y su `interval: 10s` se conserva (RNF-007). Solo se ajusta el comentario si la redacción de la semántica difiere de la de `heartbeat.py`.
- `README.md` — contratos de invitación (tabla y viñeta del ciclo de vida), campo `code`, tercera ruta de materialización, semántica de salud y comando de verificación (RNF-004, RNF-005).
- `AGENTS.md` — viñetas de «Invitación vencida», «Contratos que cambian», «Acciones auditadas» y «Healthchecks», y el comando opt-in de las pruebas de reapertura (RNF-004, RNF-005).
- `infra/postgres/migrations/` — **ningún archivo nuevo** (ver «Base de datos»).

## Funciones puras

| Función | Ubicación | Regla |
|---|---|---|
| `reopen_conflict(stored_status, has_live_pending)` | `invitations/lifecycle.py` | `None` si procede; `INVITATION_NOT_REVOKED` si el estado almacenado no es `revoked`; `INVITATION_OTHER_PENDING` si hay otra pendiente **vigente** del mismo correo. Sin reloj y sin BD. |
| `resend_conflict(stored_status)` | `invitations/lifecycle.py` | `INVITATION_ALREADY_ACCEPTED` para `accepted`; `INVITATION_REVOKED_RESEND` para `revoked`; `None` en el resto (vencida y pendiente siguen permitidas). |
| `effective_invitation_status(stored, expires_at, now)` | `invitations/lifecycle.py` | Ya existe: recibe `now`; se reutiliza para decidir qué pendiente del correo está **vigente**. |
| `reopen_audit_payload(role_code, previous_status)` | `invitations/audit.py` | Solo `role_code` y `previous_status`; nunca correo, token ni nombre. |
| `conflict_body(exc)` | `invitations/errors.py` | Cuerpo del 409: `detail` (cadena, como hoy) + `code` (estable). |
| `invitationActionsFor(status)` | `frontend/app/utils/invitationActions.ts` | `pending → [resend, revoke]`, `expired → [resend]`, `revoked → [reopen]`, `accepted → []`; estado desconocido → `[]`. |
| `invitationActionLabelKey(action)` / `invitationActionErrorKey(action)` / `invitationActionConfirmKey(action)` | idem | Claves i18n por acción; solo `reopen` tiene confirmación. |
| `invitationControlsDisabled(operation)` | idem | `true` para cualquier operación distinta de `idle`. |
| `beginInvitationOperation(current, next)` | idem | Devuelve `next` si `current === 'idle'`; `null` si ya hay una operación en curso (guarda anti doble pulsación que no depende del DOM). |
| `invitationConflictCode(cause)` / `invitationConflictMessageKey(cause)` | `frontend/app/utils/invitationErrors.ts` | Lee `cause.data.code`; devuelve la clave i18n del motivo o `null` si falta o no es una cadena conocida. Sin reloj, sin red, sin DOM. |
| `heartbeat_is_fresh(mtime_epoch, now_epoch, max_age)` / `heartbeat_is_due(last, now, interval)` | `backend/app/workers/heartbeat.py` | Ya existen: reciben el instante; nadie lee el reloj dentro de la lógica. |

## Algoritmos

### Reapertura (transacción)

```text
POST /organizations/invitations/{invitation_id}/reopen

now        = datetime.now(timezone.utc)          # una sola vez por petición
raw_token  = secrets.token_urlsafe(32)
expires_at = now + timedelta(hours=settings.invitation_expire_hours)

BEGIN
  set_rls_context(db, context.organization_id, context.user_id)   # §3.1
  require_permission("MANAGE_MEMBERS")                            # 403 antes de leer (caso 14)

  target = SELECT ... FROM organization_invitations
           WHERE id = :invitation_id AND organization_id = :organization_id
           FOR UPDATE                                            # 404 si no existe o es de otra organización (caso 13)

  # 1) Validar sin escribir (RF-002)
  otra_vigente = EXISTS(SELECT 1 FROM organization_invitations
                        WHERE organization_id = :org AND email = target.email
                          AND id <> target.id
                          AND status = 'pending' AND expires_at > :now)
  reason = reopen_conflict(target.status, otra_vigente)
  SI reason IS NOT NULL → raise InvitationConflict(reason)        # 409, nada escrito

  # 2) Tercera ruta de materialización (Q6): solo las pendientes YA vencidas del correo
  UPDATE organization_invitations
     SET status = 'expired', updated_at = CURRENT_TIMESTAMP
   WHERE organization_id = :org AND email = target.email
     AND status = 'pending' AND expires_at <= :now

  # 3) Rotar el enlace sobre la misma fila (RF-001)
  row = UPDATE organization_invitations
           SET token_hash = :nuevo_hash,
               token_encrypted = pgp_sym_encrypt(:raw_token, :key),
               expires_at = :expires_at,
               status = 'pending',
               revoked_at = NULL,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = :invitation_id AND organization_id = :org
         RETURNING id, organization_id, email, role_code, expires_at, status,
                   invited_by_member_id, accepted_by_user_id, accepted_at,
                   revoked_at, created_at, updated_at
  # IntegrityError (carrera con otra escritura del mismo correo) → 409 INVITATION_OTHER_PENDING

  organization_name = SELECT name FROM get_current_organization()  # 404 si no hay contexto

  # 4) Auditoría: exactamente una entrada, solo con cambio efectivo (RF-004)
  record_invitation_audit(entity='organization_invitations', entity_id=target.id,
                          action='REOPEN_INVITATION',
                          payload=reopen_audit_payload(role_code=target.role_code))
COMMIT

invite_url = f"{frontend_base_url}/invitations/{quote(raw_token)}"
send_invitation_email(row.email, organization_name, row.role_code, invite_url, expires_at)
  # OSError/SMTPException → 502 con la fila YA pendiente (caso 11); un fallo de envío no revierte la escritura (contrato de crear y reenviar)
return 200 con _invitation_payload(row, invite_url)
```

Notas de corrección:

- **Atomicidad (Q6):** materialización y rotación comparten transacción; cualquier error posterior (incluido el `IntegrityError`) deshace las dos. No queda una materializada sin reapertura ni al contrario.
- **Estados que no se reabren** (pendiente, vencida, aceptada): el estado **almacenado** no es `revoked` → 409 `INVITATION_NOT_REVOKED`, sin renovar token ni fecha y sin tocar `revoked_at`.
- **Orden de bloqueo:** la fila objetivo se bloquea antes que las pendientes del correo, igual que en `resend`; el índice único sigue siendo la garantía final frente a dos reaperturas simultáneas del mismo correo (una gana, la otra recibe 409).

### Reenvío (cambio mínimo, C-1)

```text
BEGIN
  set_rls_context / require_permission / carga con FOR UPDATE      # 403, 404 como hoy
  reason = resend_conflict(target.status)
  SI reason IS NOT NULL → raise InvitationConflict(reason)          # accepted o revoked; 409 sin escribir
  materializar pendientes vencidas del correo (:now)
  SI existe otra pendiente → 409 INVITATION_OTHER_PENDING
  UPDATE ... status='pending', token y fecha nuevos, revoked_at = NULL
  organization_name
COMMIT
enviar correo (502 si falla) → 200
```

La única diferencia observable con la spec 008 es que una **revocada** deja de resucitarse por reenvío (C-1); el resto se conserva literalmente.

### Comprobación de salud del worker

```text
# docker-compose.yml, healthcheck del servicio worker (sin cambios de mecanismo)
python -c "import sys;
  from app.workers.heartbeat import HEARTBEAT_MAX_AGE_SECONDS, heartbeat_is_fresh_at_path;
  sys.exit(0 if heartbeat_is_fresh_at_path(max_age=HEARTBEAT_MAX_AGE_SECONDS) else 1)"

heartbeat_is_fresh_at_path(path, now=time.time(), max_age=90):
  mtime = os.stat(path).st_mtime        # ausente o inaccesible → NO fresco (insano)
  age   = now - mtime
  age < 0  → fresco                     # reloj adelantado en el escritor (caso 19)
  age <= 90 → fresco ; en caso contrario → insano   # límite inclusivo
```

Y el bucle que publica la señal (`backend/app/workers/outbox.py`, sin cambios):

```text
mientras True:
  si heartbeat_is_due(último, monotonic(), 10)  → publish_heartbeat()   # al principio de la vuelta
  intentar process_once()                      # la vuelta termina con éxito o con error de dependencia
  dormir 1 s
```

Consecuencias que la prueba debe fijar: un `process_once` bloqueado más de 90 s deja de publicar → insano; una dependencia caída que lanza excepción **completa la vuelta** y el latido sigue publicándose → sano (RF-010); sin eventos, la vuelta se repite y el latido se publica igual (RF-008).

### Verificación operativa de la transición (RF-011)

```text
infra/scripts/verify_worker_loop_health.sh [servicio=worker]
  1. ¿docker y docker compose disponibles? si no → imprime "NO EJECUTADA" y sale 2
  2. docker compose up -d worker ; esperar State.Health.Status == healthy (<= 120 s)
  3. docker compose exec -T worker sh -c 'kill -STOP 1'        # congela el bucle, no el proceso del healthcheck
  4. sondear docker inspect --format '{{.State.Health.Status}}' cada 5 s (<= 180 s)
       unhealthy → registrar el tiempo transcurrido ; no llegó → salir 1
  5. docker compose exec -T worker sh -c 'kill -CONT 1'        # reanuda
  6. sondear hasta healthy (<= 120 s) ; no llegó → salir 1
  7. imprimir ambos tiempos y salir 0
```

El contenedor corre como `app` (no root) y el `exec` usa el mismo usuario, así que `SIGSTOP`/`SIGCONT` sobre el PID 1 son válidos. `docker inspect` lee la salud **reportada por el orquestador**, no una simulación. Sin `restart` en el servicio, Compose no reinicia el contenedor por estar `unhealthy`: la transición es observable y la recuperación no depende de un reinicio.

## Interfaz

### Endpoints

| Método y ruta | Códigos | Cuerpo |
|---|---|---|
| `POST /api/v1/organizations/invitations/{invitation_id}/reopen` (**nuevo**) | **200** | `InvitationResponse`: `status: "pending"`, `expires_at` nueva, `revoked_at: null`, `updated_at` nueva, `invite_url` con el enlace nuevo. Mismo `id`, `email` y `role_code`. |
| | **403** | Sin `MANAGE_MEMBERS` (mismo rechazo exista o no la invitación) o membresía de organización inválida («Membresía no válida»). |
| | **404** | Inexistente o de otra organización (no revela que existe). |
| | **409** | `code` ∈ {`INVITATION_NOT_REVOKED`, `INVITATION_OTHER_PENDING`}; sin token, sin enlace y sin correo en el cuerpo. |
| | **502** | Fallo de envío posterior a la escritura: la invitación queda pendiente y el cliente debe releer. |
| | **422** | UUID de ruta inválido (validación de FastAPI, sin cambios). |
| `POST /api/v1/organizations/invitations/{id}/resend` | **409** (nuevo para revocadas) | `code: INVITATION_REVOKED_RESEND`; aceptadas → `INVITATION_ALREADY_ACCEPTED`; otra pendiente vigente → `INVITATION_OTHER_PENDING`. **200** en vencidas y pendientes, como hoy. |
| `POST /api/v1/organizations/invitations` | **409** | Añade `code: INVITATION_OTHER_PENDING` al 409 existente (mismo motivo, sin cambio de comportamiento). **201** sin cambios. |
| `GET /api/v1/organizations/invitations` | 200 | Sin cambios. |
| `GET /api/v1/invitations/{token}` y `POST …/accept` | 404 / 410 | Sin cambios: un token revocado o sustituido no resuelve (caso 8). |

### Campos nuevos (aditivos)

- Cuerpo de error 409: `{"detail": "<texto en español, como hoy>", "code": "<IDENTIFICADOR_ESTABLE>"}`. `detail` conserva tipo y contenido, así que el cliente actual sigue funcionando; `code` es lo único nuevo y ningún campo se renombra ni se retira.
- Respuesta de reapertura: **ningún campo nuevo**; se reutiliza `InvitationResponse`.
- **Dónde se traduce:** en el cliente (`invitationErrors.ts` → clave `members.conflict*`). El servidor no negocia idioma ni envía texto alternativo.

### Pantallas afectadas

- **`/workspace/members` (Workspace):** por fila, «Reenviar» en `pending` y `expired`, «Reabrir» en `revoked`, «Revocar» solo en `pending` vigente, ninguna en `accepted`; cada control con `aria-label` propio (rol traducido + fecha); confirmación nativa antes de reabrir; controles del formulario y de las filas deshabilitados mientras hay una operación de invitaciones; tras el éxito, estado y fecha reales y el enlace nuevo; ante 409, mensaje del motivo con la acción a usar.
- **`/invitations/{token}` (pública):** sin cambios. Un enlace anterior a la reapertura o al reenvío responde «no encontrada».
- Sin pantallas nuevas y sin ruta de consulta de auditoría (fuera de alcance).

## Base de datos

**No hay migración.** RNF-002 se cumple sin DDL, y se verificó sobre el esquema vigente (023):

- Los estados `pending`, `expired`, `revoked` y `accepted` ya existen en `organization_invitations.status`; la reapertura no introduce un valor nuevo.
- El índice único de pendientes por organización y correo ya existe y sigue siendo la garantía final.
- `administrative_audit_logs` admite la entrada: `entity_type VARCHAR(50)` (`organization_invitations` = 24 caracteres), `action VARCHAR(50)` (`REOPEN_INVITATION` = 17), sin `CHECK` sobre valores; la política `tenant_isolation_policy` y el `GRANT INSERT` a `bracket_app` ya cubren la escritura con contexto de organización.
- `organization_invitations` ya tiene `GRANT SELECT, INSERT, UPDATE, DELETE` para `bracket_app` (migración 014); no se necesitan permisos nuevos (a diferencia de la 020 con `rosters`).
- Al no haber migración, no hay runbook ni orden de despliegue de esquema; código y cliente se despliegan juntos, como en la spec 008.

## Datos personales y privacidad

- La reapertura **no** añade datos personales a la auditoría: `reopen_audit_payload` guarda `previous_status` y `role_code`, nunca el correo, el token, el enlace ni el nombre de la persona.
- El 409 no incluye token, enlace ni el correo del destinatario; el `detail` sigue siendo un texto de dominio y el `code` un identificador de motivo.
- El enlace solo se devuelve al administrador que ejecuta la acción y se envía al destinatario; no se registra en la traza (`logger.exception` existente solo nombra el `id` de la invitación).
- Ninguna proyección pública cambia; la auditoría no se expone en ninguna ruta.
- Las pruebas usan organizaciones y correos ficticios creados por `tenant_factory` dentro de una transacción revertida (RNF-006).

## Estrategia de pruebas

### Backend — función pura y contrato de error (siempre corre)

`backend/tests/test_invitation_reopen_rules.py`:

- `reopen_conflict`: revocada sin otra pendiente → `None`; pendiente, vencida y aceptada → `INVITATION_NOT_REVOKED`; revocada con otra pendiente vigente → `INVITATION_OTHER_PENDING` (RF-002).
- `resend_conflict`: aceptada y revocada → código propio; pendiente y vencida → `None` (RF-003).
- `reopen_audit_payload`: solo `previous_status` y `role_code`; una prueba falla si aparece una clave con correo, token o nombre (RF-004).
- `conflict_body`: `detail` es cadena y `code` es el valor de la excepción (compatibilidad del contrato).
- Manejador de `InvitationConflict`: invocarlo directamente produce un `JSONResponse` 409 con `{"detail", "code"}`.

### Backend — router y servicio sobre PostgreSQL (opt-in)

`backend/tests/test_invitations.py`, reutilizando `tenant_factory`, `_insert_tenant_invitation`, `_stored_invitations` y `_invitation_api` (transacción revertida, endpoints reales):

- **RF-001:** reabrir una revocada → 200, mismo `id`/`email`/`role_code`, `status: pending`, `expires_at` futura, `revoked_at: null`, `updated_at` mayor, `invite_url` presente, una sola fila para el correo; el token anterior no previsualiza (404) y el nuevo sí.
- **RF-001 (Q6/C-2):** revocada + otra pendiente **vencida** del mismo correo → 200, la otra queda `expired` y la reabierta `pending`; exactamente una pendiente.
- **RF-002:** reabrir pendiente vigente, vencida y aceptada → 409 con `INVITATION_NOT_REVOKED`, sin cambios en token, fecha, `revoked_at` ni `updated_at`; con otra pendiente vigente → 409 `INVITATION_OTHER_PENDING` sin escribir ni materializar; sin permiso → 403 (y sin escritura); invitación de otra organización → 404.
- **RF-003 (C-1):** reenviar una revocada → 409 `INVITATION_REVOKED_RESEND`, fila intacta, sin correo; reenviar una vencida sigue en 200.
- **RF-004:** una reapertura con éxito deja **exactamente una** fila en `administrative_audit_logs` con `entity_type = 'organization_invitations'`, `action = 'REOPEN_INVITATION'`, el `entity_id` y el `performed_by_member_id` esperados; un 409 no deja ninguna; la aceptación conserva su `ACCEPT_INVITATION`.
- **Caso 11:** con `send_invitation_email` fallando (monkeypatch existente en `_invitation_api`), la respuesta es 502 y la fila quedó pendiente con token nuevo.

Comando (opt-in, `AGENTS.md`): `docker compose exec -e RUN_DATABASE_TESTS=1 api pytest -q tests/test_invitations.py`.

### Backend — salud del worker (siempre corre)

`backend/tests/test_worker_heartbeat.py` (ampliación):

- Frescura en 90 s exactos (fresco) y 91 s (insano); marca futura → fresco (caso 19) — ya cubierto, se conserva.
- `HEARTBEAT_MAX_AGE_SECONDS == 90` y `HEARTBEAT_INTERVAL_SECONDS == 10`, con `MAX_AGE >= 9 × INTERVAL` como margen mínimo de 9 latidos perdidos.
- **Aserción de fuente sobre `docker-compose.yml`:** el `test` del healthcheck importa `HEARTBEAT_MAX_AGE_SECONDS` y **no** contiene el literal `90`; `interval` es `10s` (RNF-007).
- Bucle con dependencia caída durante varias vueltas: el latido sigue fresco (RF-010), ampliando la prueba existente a ≥ 3 iteraciones.
- Fichero ausente (worker detenido antes de la primera vuelta) → insano (caso 16).
- Reinicio de la salud tras reanudar: simulado a nivel de función (mtime actualizado → fresco), porque la transición real con proceso vivo es la verificación de operación de RF-011 y **no** se declara cubierta por esta suite.

### Frontend — funciones puras y aserciones de fuente

`frontend/tests/invitation-actions.test.ts`:

- `invitationActionsFor`: pendiente → reenviar y revocar; vencida → solo reenviar; revocada → solo reabrir; aceptada → ninguna; estado desconocido → ninguna (RF-005).
- `invitationActionLabelKey` distinto para `resend` y `reopen`, y presente en los dos catálogos; `invitationActionErrorKey` y `invitationActionConfirmKey` (RF-005, RF-006, RF-007).
- `invitationControlsDisabled`: `idle` habilita; cualquier operación deshabilita (RF-006).
- `beginInvitationOperation`: `idle → reopening`; `reopening → resending` devuelve `null` (una sola petición por doble pulsación) (RF-006).
- `invitationConflictMessageKey`: los cuatro códigos → cuatro claves distintas y existentes en español y en inglés; cuerpo sin `code`, `code` no cadena o desconocido → `null` (RF-007).
- **Aserciones de fuente sobre `members.vue`:** usa `invitationActionsFor`, `invitationControlsDisabled` e `invitationConflictMessageKey`; contiene `t('members.reopen')`, `t('members.confirmReopen')` y los `aria-label` de las tres acciones; no contiene el literal «Reabrir»/«Reopen» fijo; el botón de reabrir está condicionado a la acción `reopen` (no a `status !== 'accepted'`).
- **Aserciones de fuente sobre `useI18n.ts`:** las claves nuevas existen en ambos catálogos y el catálogo conserva la paridad que ya verifica `labels.test.ts`.

Comandos: `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck`.

### Operación — contenedores

`infra/scripts/verify_worker_loop_health.sh` (RF-011): se ejecuta a mano, no forma parte de `pnpm test` ni de `pytest`; si no hay Docker, sale con 2 y la validación lo declara **no ejecutado**. Se comprueba también con `sh -n`.

## Documentación obligatoria (mismo cambio que el código)

### `README.md`

- **Viñeta «Invitación vencida»** (sección «Contratos de invitación, presentación y versión»): el registro se materializa al **crear**, al **reenviar** y, desde esta entrega, al **reabrir** una revocada cuando el mismo correo tiene otra pendiente ya vencida (tercera ruta, Q6); lectura y vista previa siguen sin escribir.
- **Tabla de contratos**: filas nuevas para `POST …/{id}/reopen` (200 sobre revocada; 409 sobre pendiente, vencida, aceptada; 409 con otra pendiente vigente; 200 materializando la otra pendiente vencida) y para `POST …/{id}/resend` sobre una revocada (**409**, cambio C-1). Se mantiene la fila del reenvío de una vencida (200).
- **Párrafo del identificador estable:** el 409 de invitación incluye `code` además de `detail`; se enumeran los cuatro valores, se indica que `detail` no cambia y que el cliente traduce `code` al idioma activo.
- **Párrafo de salud (línea de verificaciones de salud):** el worker se declara **insano cuando su bucle no completa una vuelta en 90 s**, haya o no eventos; con la base de datos o Redis caídos pero el bucle girando y reintentando sigue **sano**; señal cada 10 s; `HEARTBEAT_MAX_AGE_SECONDS` es la única fuente del umbral. Se añade el comando `sh infra/scripts/verify_worker_loop_health.sh` y la regla de declararlo **no ejecutado** sin Docker.

### `AGENTS.md`

- **«Invitación vencida»** (Límites del Proyecto): añade reabrir → 200, reenviar una revocada → 409, y la materialización previa de otra pendiente vencida como tercera ruta.
- **«Contratos que cambian»**: registra C-1 y C-2 y el campo aditivo `code` con sus cuatro valores.
- **«Acciones auditadas»**: añade «reabrir una invitación» a la lista y mantiene que la aceptación conserva su entrada y que crear, reenviar y revocar no añaden ninguna.
- **«Healthchecks»** (Runtime): describe «vuelta completada» y «bucle detenido» con las mismas palabras que `heartbeat.py` y cita el script de verificación.
- **Testing**: comando opt-in de las pruebas de reapertura (`docker compose exec -e RUN_DATABASE_TESTS=1 api pytest -q tests/test_invitations.py`) y nota de que la verificación con contenedores no es parte de la suite.

No se toca `docs/constitution.md` (sin cambio de principios ni de reglas) ni la spec 008, salvo la nota ya registrada en la spec 009 sobre la redacción de su RF-014 (Q7), que no altera comportamiento.

## Riesgos

- **Carrera entre reapertura y reenvío (o dos reaperturas del mismo correo):** la fila objetivo se bloquea antes y el índice único decide; el perdedor recibe 409 `INVITATION_OTHER_PENDING`. Queda como riesgo aceptado el mismo que ya existe hoy en crear y reenviar: dos peticiones simultáneas no producen dos pendientes, pero sí un 409 que el usuario debe reintentar.
- **Ventana entre materialización y reapertura:** no es observable fuera de la transacción; si algo falla después, el rollback deja la otra invitación como estaba almacenada (caso 2). Riesgo residual: durante la transacción se mantienen bloqueos sobre las pendientes de ese correo, lo que puede hacer esperar a otra petición del mismo correo hasta el commit.
- **Lectura de una invitación vencida:** sigue sin materializarse (contrato 008). Entre esa lectura y una reapertura posterior el registro puede aparecer `pending` con fecha pasada; el estado efectivo se sigue calculando al leer, así que la presentación no cambia.
- **Cliente antiguo con el servidor nuevo:** sigue mostrando el texto español de `detail` e ignora `code`; no se rompe, solo no traduce. **Servidor antiguo con cliente nuevo:** sin `code`, la interfaz cae al `errorMessage` actual (y al `fallback` en inglés), que es el comportamiento de hoy.
- **Interfaz no verificada en navegador:** diálogo de confirmación, doble pulsación real, refresco de la fila y copia del enlace quedan fuera de esta entrega (RNF-001, Q8) y se remiten a la spec 010. Riesgo residual aceptado y declarado.
- **`SIGSTOP` sobre el PID 1:** si un operador lo ejecuta y no reanuda, el worker queda vivo pero inerte (insano) y el servicio deja de procesar eventos. Mitigación: el script reanuda con `SIGCONT` en el mismo flujo y no hay `restart` que enmascare el estado; se documenta que es una prueba de operación, no un comando de producción.
- **Falso negativo por desfase de reloj:** solo en la dirección reloj-lector atrasado respecto al escritor; el margen 90 s frente a 10 s absorbe desfases pequeños (caso 19) y no se promete simetría.

## Qué RF cubre cada parte

| Parte | RF | Dónde |
|---|---|---|
| Backend — contrato de error | RF-002, RF-003, RF-007 (contrato) | `invitations/errors.py`, manejador en `main.py` |
| Backend — reapertura | RF-001, RF-002, RF-004 | `invitations/router.py` (`reopen_invitation`), `lifecycle.py`, `audit.py` |
| Backend — reenvío | RF-003 (C-1) | `invitations/router.py` (`resend_invitation`) |
| Backend — salud | RF-008, RF-009, RF-010 (RNF-007) | `workers/heartbeat.py` (docstring y constantes), `docker-compose.yml` (healthcheck) |
| Operación | RF-011 | `infra/scripts/verify_worker_loop_health.sh` |
| Frontend | RF-005, RF-006, RF-007 | `utils/invitationActions.ts`, `utils/invitationErrors.ts`, `pages/workspace/members.vue`, `useI18n.ts` |
| Pruebas | RF-001 a RF-011 | `tests/test_invitation_reopen_rules.py`, `tests/test_invitations.py`, `tests/test_worker_heartbeat.py`, `tests/invitation-actions.test.ts` |
| Documentación | RNF-004, RNF-005 | `README.md`, `AGENTS.md` |
| Base de datos | RNF-002 | Sin migración (ver «Base de datos») |

## Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant garantizado por la base de datos | Sí | La reapertura fija `set_rls_context()` antes de leer y escribe con `organization_id` en el `WHERE`; la auditoría cae en una tabla con RLS forzada. Una invitación de otra organización responde 404 sin revelar existencia (RF-001, RF-002, caso 13). |
| §2.2 La aplicación no se salta RLS | Sí | No se cambia el rol ni se añaden privilegios; no hay migración que los altere. |
| §2.3 Lo publicado es inmutable | Sí | No se tocan versiones de torneo, resultados ni actas. |
| §2.4 Historial de esquema append-only | Sí | No se crea ni se edita ninguna migración (RNF-002); la 013 y las aplicadas no se tocan. |
| §2.5 Lo público es una proyección mínima | Sí | Ninguna proyección pública cambia; ni el 409 ni la auditoría exponen correo, token o enlace (RF-002, RF-004). |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Sin variables ni secretos nuevos; el token se genera con `secrets.token_urlsafe(32)` y se cifra con `INVITATION_TOKEN_KEY`, como hoy. |
| §2.7 Administración global separada y auditada | Sí | No se añaden acciones de plataforma; `/admin` no gana acceso a invitaciones ni a la auditoría organizacional. |
| §2.8 Nada se da por terminado sin verificación | Sí | Cada RF tiene prueba o comando citado; la verificación con contenedores y cualquier job no ejecutado se declaran explícitamente (RF-011, criterio 13). |
| §2.9 Código de desarrollo fuera de producción | Sí | Sin scripts nuevos de seed; el script de verificación es de operación y no se ejecuta en producción ni en la suite. |
| §3.1 RLS y migraciones | Sí | `set_rls_context()` dentro de la transacción y antes de cualquier consulta tenant; sin DDL, por lo que no hay migración que aplicar en limpio ni migrado. |
| §3.2 Backend (módulos, async, outbox) | Sí | El cambio vive en el módulo `invitations` existente; no hay router nuevo que registrar en `main.py` (solo un manejador de excepción); no se introduce trabajo síncrono que debiera pasar por el outbox; no se añaden constantes de reglas deportivas. |
| §3.3 Frontend (`useApi.ts`, rutas) | Sí | La reapertura usa `useApi()`; `/workspace/members` sigue exigiendo sesión y organización activa; no hay rutas públicas nuevas. |
| §3.4 Seguridad y configuración | Sí | Sin secretos nuevos ni defaults fuera de `.env.example`; no se persiste ningún dato personal nuevo; la auditoría no incluye PII. |
| §3.5 Infraestructura y CI | Sí | Sin cambios en versiones de referencia, Dockerfiles ni `ci.yml`; `docker compose config -q` sigue siendo la verificación de la configuración. |
| §4 Todos los cambios | Sí | Jobs `backend`, `frontend` e `infrastructure` en verde; sin secretos ni datos personales nuevos; documentación actualizada en el mismo cambio (`README.md`, `AGENTS.md`); pruebas para todo comportamiento nuevo. |
| §4 Cambios de base de datos | No aplica | No hay cambio de esquema. |
| §4 Cambios de API o backend | Sí | `set_rls_context()` en la transacción; sin campos sensibles en respuestas; el router existente sigue registrado en `main.py`; `pytest -q` y `python -m compileall -q app` pasan. |
| §4 Cambios de frontend | Sí | Llamadas por `useApi.ts`; `pnpm test`, `pnpm run typecheck` y `pnpm run build` pasan. |
| §4 Cambios de infraestructura | Parcial | Solo se añade un script de operación; `docker compose config -q` y las aserciones de producción siguen pasando sin cambios en el perfil de producción. |
| §4 Cambios de dependencias | No aplica | No se añaden ni actualizan dependencias (RNF-001). |
| §5.1 Excepciones | No aplica | No se requiere ninguna excepción: no se omite ninguna regla ni criterio. |
| §6 Definición de cumplimiento | Sí | Principios respetados, reglas cumplidas, CI en verde y revisión humana distinta del autor antes de fusionar. |

**Conclusión:** no hay incumplimientos ni excepciones pendientes.
