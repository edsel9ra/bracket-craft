# Plan — Spec 039: Recuperar y cambiar la contraseña

Estado: aprobado por el usuario el 2026-11-16 («Apruebo plan, tareas y aclaraciones»).

## 1. Alcance y dependencias

- Sin enmienda constitucional. No toca tablas de tenants ni proyecciones públicas.
- Migración **062**, que debe aplicarse antes de desplegar API y worker.
- El token nunca existe en la base ni en la respuesta: la petición solo encola un trabajo con el correo; el **worker** resuelve la cuenta, genera el token, guarda su hash y envía el correo (RF-001, RF-002, RNF-001).

## 2. Archivos y responsabilidades

### Base de datos

- `infra/postgres/migrations/062_password_recovery.sql`:
  - `account_email_jobs`: `id`, `kind` (`password_reset_request` | `password_changed_notice`), `email` (normalizado, solo en solicitudes), `user_id` (solo en avisos), `status` (`pending`/`processing`/`processed`/`failed`), `attempts`, `available_at`, `locked_at`, `processed_at`, `created_at`. Al procesarse se anula `email`.
  - `password_reset_tokens`: `id`, `user_id` (FK `users` ON DELETE CASCADE), `token_hash CHAR(64) UNIQUE`, `expires_at`, `used_at`, `invalidated_at`, `created_at`; índice parcial de pendientes por `user_id`.
  - `account_security_events`: `id`, `user_id`, `event_type` (`password_reset` | `password_changed`), `created_at`. Sin correo ni secretos (RF-012).
  - Las tres son tablas de cuenta, no de tenant (como `users` y `user_sessions`): sin `organization_id`. `bracket_app` no recibe privilegios directos sobre ellas; todo pasa por funciones `SECURITY DEFINER` con `search_path` fijo y `GRANT EXECUTE` solo a `bracket_app`:
    - `enqueue_password_reset_request(p_email)`: inserta el trabajo; no consulta `users` (RNF-001).
    - `claim_account_email_jobs(p_limit)`: `FOR UPDATE SKIP LOCKED`, como el reclamo del outbox (migración 010).
    - `issue_password_reset(p_job_id, p_token_hash, p_expires_at)`: resuelve el correo (comparación `LOWER`, CL-8). Cuenta activa con contraseña: invalida pendientes, guarda el hash y devuelve `('reset', correo)`. Activa sin contraseña: `('google_reminder', correo)`. Inexistente o desactivada: `('none', NULL)` (RF-002, RF-002b, RF-003).
    - `password_reset_target(p_token_hash)`: devuelve `user_id` y `password_hash` actual solo si el token es válido (RF-004, RF-005).
    - `complete_password_reset(p_token_hash, p_new_hash)`: bloquea el token `FOR UPDATE`, revalida, fija la contraseña, marca usado, invalida los demás, revoca **todas** las sesiones, encola el aviso y registra el evento. Devuelve `NULL` si ya no es válido (RNF-003).
    - `change_account_password(p_user_id, p_session_id, p_new_hash)`: fija la contraseña, revoca todas las sesiones **salvo** `p_session_id`, invalida tokens, encola el aviso y registra el evento (RF-006, RF-008).
    - `account_email_notice_target(p_job_id)`, `complete_account_email_job`, `fail_account_email_job` (reintento con espera; 5 intentos), `purge_account_recovery_records(p_cutoff, p_limit)`.
  - Verificación: `test_migration_062.py` (opt-in con `RUN_DATABASE_TESTS=1`) sobre cadena limpia 001→062 y salto 061→062; `sh -n infra/postgres/migrate.sh`.

### Backend

- `backend/app/modules/identity/password_recovery.py` (funciones puras): `new_reset_token()` (`secrets.token_urlsafe(32)`, 256 bits), `token_hash()` (SHA-256 hex, como invitaciones), `reset_expires_at(now)` (+30 min, DA-3), `reset_url(base, token)` (token en el **fragmento** `#`), `job_should_expire(created_at, now)`.
- `backend/app/modules/identity/password_router.py`, registrado en `main.py` bajo `/api/v1/auth/password`:
  - `POST /forgot`: rate limit; llama a `enqueue_password_reset_request`; 202 genérico.
  - `POST /reset`: rate limit por IP y hash del token; `password_reset_target`; Argon2 en hilo para comprobar «igual a la actual» y para el hash nuevo; `complete_password_reset`; borra la cookie de sesión.
  - `GET /` (sesión): `{has_password}` para la pantalla de cuenta.
  - `POST /change` (sesión): rate limit por IP y cuenta; verifica la actual con Argon2 en hilo; `change_account_password` con el `jti` actual.
- `backend/app/modules/identity/schemas.py`: `ForgotPasswordRequest`, `ResetPasswordRequest`, `ChangePasswordRequest` (`new_password` 8–128, como el registro; `extra="forbid"`), `PasswordStatusResponse`.
- `backend/app/core/email.py`: `send_password_reset_email`, `send_google_sign_in_reminder_email`, `send_password_changed_email`, en español como el resto de correos; el aviso no lleva enlaces de acción (DA-4).
- `backend/app/workers/account_email.py`: `process_account_email_jobs(now)`, llamado desde el bucle de `outbox.py`. Para una solicitud: genera token, `issue_password_reset`, envía según el tipo. Si el envío falla, invalida ese token antes de reintentar (CL-7). Trabajos de más de 30 min se descartan sin enviar. Nunca registra el correo ni el token en logs ni en `last_error` (RF-011).
- `backend/app/workers/retention.py`: llama además a `purge_account_recovery_records` (tokens usados/caducados y trabajos procesados de más de 7 días; los eventos de seguridad se conservan).
- `backend/app/core/config.py` y `.env.example`: `AUTH_PASSWORD_RESET_RATE_LIMIT` (default 5 por hora, por IP y por correo). Los demás límites reutilizan `AUTH_LOGIN_RATE_LIMIT`/60 s.

### Frontend

- `app/composables/usePasswordAccount.ts`: `forgot`, `reset`, `status`, `change`, todo vía `useApi`.
- `app/utils/passwordRecovery.ts`: lectura y limpieza del token del fragmento, validación local 8–128, mapeo de errores a claves i18n.
- `app/pages/password/forgot.vue` y `app/pages/password/reset.vue` (públicas, sin sesión); `app/pages/account/password.vue` (middleware `session`).
- `app/pages/login.vue`: enlace «¿Olvidaste tu contraseña?» en el modo login.
- `app/components/WorkspaceShell.vue`: entrada «Cambiar contraseña» en el menú de cuenta, escritorio y móvil.
- `app/composables/useI18n.ts`: claves ES/EN.

### Tests

Backend: `test_password_recovery.py` (puras), `test_password_recovery_endpoints.py` y `test_account_email_worker.py` (opt-in con BD), `test_migration_062.py`, `test_retention.py` ampliado. Frontend: `password-recovery.test.ts`. E2E: `e2e/password-recovery.spec.ts` en el proyecto `public` con contratos ficticios.

## 3. Funciones puras

Todas reciben `now` como parámetro: `reset_expires_at(now)`, `job_should_expire(created_at, now)`, `process_account_email_jobs(now)`. `token_hash`, `reset_url` y la validación de política son deterministas.

## 4. Interfaz

| Método y ruta | Sesión | Entrada | Respuestas |
|---|---|---|---|
| `POST /api/v1/auth/password/forgot` | No | `{email}` | 202 `{}` siempre; 422 formato; 429/503 |
| `POST /api/v1/auth/password/reset` | No | `{token, new_password}` | 204; 400 `PASSWORD_RESET_INVALID`; 400 `PASSWORD_REUSED`; 422; 429/503 |
| `GET /api/v1/auth/password` | Sí | — | 200 `{has_password}`; 401 |
| `POST /api/v1/auth/password/change` | Sí | `{current_password, new_password}` | 204; 400 `CURRENT_PASSWORD_INVALID`; 400 `PASSWORD_REUSED`; 409 `PASSWORD_NOT_SET`; 422; 429/503 |

Las peticiones `POST` pasan por el middleware CSRF existente. Pantallas: `/password/forgot` (correo y confirmación genérica), `/password/reset#<token>` (contraseña nueva y confirmación local; éxito lleva al login), `/account/password` (actual, nueva y confirmación; cuenta solo-Google ve un aviso sin formulario).

## 5. Decisiones justificadas

1. **El worker emite el token, no la petición.** Así la respuesta es idéntica en contenido y casi en tiempo, y el token nunca se guarda en claro. *Descartado:* generar el token en la petición y guardarlo cifrado para el worker (más secretos y más código), o enviar SMTP en la petición (revela la existencia por tiempo y falla con SMTP caído).
2. **Cola propia en lugar de `outbox_events`.** `outbox_events` exige `organization_id` y RLS de tenant; la cuenta no pertenece a una organización. *Descartado:* usar una organización ficticia o relajar la restricción.
3. **Funciones `SECURITY DEFINER` y sin privilegios directos.** `bracket_app` no tiene `UPDATE` sobre `users`; las funciones acotan exactamente qué se puede cambiar. *Descartado:* conceder `UPDATE (password_hash)`.
4. **Token en el fragmento de la URL.** El fragmento no llega al servidor SSR ni a logs del proxy ni al `Referer`. *Descartado:* ruta `/password/reset/{token}` como las invitaciones.
5. **Si falla el envío, se invalida el token emitido.** Ningún enlace válido queda sin entregar (CL-7). *Descartado:* reutilizar el mismo token en el reintento.
6. **`CURRENT_PASSWORD_INVALID` con 400, no 401.** Un 401 haría que el frontend cerrase la sesión. *Descartado:* 401.
7. **Cuenta solo-Google en `/account/password`.** Muestra que la cuenta entra con Google y no ofrece formulario (DA-1). *Descartado:* ocultar la entrada del menú, que exigiría consultar el estado en cada carga del Workspace.

## 6. Estrategia de tests

- Puras: caducidad de 30 min, longitud del token, hash, URL con fragmento, expiración de trabajos.
- BD (opt-in): respuesta idéntica para cuenta local, inexistente, desactivada y solo-Google; un solo uso; caducado; enlace anterior invalidado; dos usos concurrentes con un solo cambio; sesiones revocadas (todas al recuperar, todas salvo la actual al cambiar); evento de seguridad sin correo; aviso encolado.
- Worker con SMTP simulado: enlace solo a cuenta local, recordatorio a solo-Google, nada a inexistente o desactivada, fallo SMTP que invalida el token, ningún token ni correo en logs (`caplog`).
- Rate limit: 429 con `Retry-After` y 503 con Redis caído.
- Frontend: páginas, validación, mapeo de errores, ES/EN y foco. E2E: las tres pantallas a 1440/390 px en ambos temas.

## 7. RF cubiertos por parte

| Parte | RF / RNF / CL |
|---|---|
| Migración 062 | RF-002–RF-005, RF-008, RF-012, RNF-002, RNF-003 |
| `POST /forgot` y worker | RF-001, RF-002, RF-002b, RF-003, RF-011, RNF-001, CL-1, CL-2, CL-6–CL-8 |
| `POST /reset` | RF-004, RF-005, RF-009, RF-010, RNF-004, CL-3, CL-5 |
| `GET /` y `POST /change` | RF-006–RF-010, CL-4 |
| Avisos y auditoría | RF-008, RF-012 |
| Frontend y E2E | RF-013 |

## 8. Exposición pública

No hay proyección pública nueva. Las rutas sin sesión solo devuelven un cuerpo genérico o un código de error cerrado; nunca correo, nombre, identidad ni existencia de cuenta.

## 9. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 2.1 Aislamiento por RLS | Sí | Tablas de cuenta sin datos de tenant, accesibles solo por funciones acotadas; ninguna organización ve credenciales |
| 2.2 Sin `BYPASSRLS` | Sí | `bracket_app` sigue sin privilegios especiales; las funciones fijan `search_path` |
| 2.3 Lo publicado es inmutable | No | — |
| 2.4 Migraciones append-only | Sí | Migración 062 nueva |
| 2.5 Proyección pública mínima | Sí | Sin campos públicos nuevos |
| 2.6 Sin secretos por defecto | Sí | Solo una variable de límite; SMTP ya obligatorio en producción |
| 2.7 Administración global | No | Sin cambios |
| 2.8 Verificación | Sí | Tests en §6 y cinco jobs de CI |
| 2.9 Código de desarrollo | Sí | Sin seeds nuevos |
| 3.2 Efectos por worker | Sí | Correos por la cola de cuenta y el worker |
| 3.3 `useApi.ts` | Sí | `usePasswordAccount` |
| 3.4 Seguridad | Sí | Argon2 en hilos, rate limit, token solo con hash, nada en logs |
| §4 BD | Sí | Volumen limpio y migrado en `test_migration_062.py`; `sh -n` |
| §4 Backend | Sí | Router registrado; `pytest -q`, `compileall` |
| §4 Frontend | Sí | `pnpm test`, typecheck, build |
| §4 Documentación | Sí | README, AGENTS, manual y runbook de la 062 |

## 10. Notas de despliegue

Aplicar la 062 antes que API y worker. Sin SMTP configurado (desarrollo), el trabajo falla tras sus reintentos sin generar enlaces utilizables. Revertir el código deja la 062 inerte.
