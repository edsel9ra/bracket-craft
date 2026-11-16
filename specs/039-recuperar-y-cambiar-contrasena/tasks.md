# Tareas — Spec 039: Recuperar y cambiar la contraseña

Estado: aprobadas por el usuario el 2026-11-16. PR documental y un PR por bloque: A (T1–T6, backend) y B (T7–T10, frontend, E2E, documentación y cierre).

- [x] **T1. Migración 062: tablas y funciones de recuperación.** RF-002–RF-005, RF-008, RF-012, RNF-002, RNF-003
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_062.py` en rojo y luego verde (sin privilegios directos, `EXECUTE` solo para `bracket_app`, un solo uso concurrente, revocación de sesiones); `sh -n infra/postgres/migrate.sh`; cadena limpia 001→062 y salto 061→062.
- Evidencia: `test_migration_062.py` en rojo (`UndefinedTableError`) y luego 11 passed contra PostgreSQL 17: tablas sin privilegios para `bracket_app` y con RLS activada, 11 funciones `SECURITY DEFINER` con `search_path` fijo y `EXECUTE` solo para `bracket_app`; la petición no resuelve la cuenta; resultado `reset`/`google_reminder`/`none`; el enlace nuevo invalida el anterior; un solo uso con revocación de todas las sesiones; caducado, hash cambiado o cuenta desactivada rechazados; dos usos concurrentes producen un cambio; el cambio mantiene solo la sesión actual; reintento, fallo definitivo, aviso y purga. `sh -n infra/postgres/migrate.sh` correcto.

- [x] **T2. Funciones puras, esquemas y plantillas de correo.** RF-002, RF-002b, RF-008, RF-009, RNF-002
- Hecho cuando: `pytest -q tests/test_password_recovery.py` verde tras confirmarlo en rojo (caducidad, token, hash, URL con fragmento, política, correos sin enlaces de acción en el aviso).
- Evidencia: `test_password_recovery.py` en rojo (error de colección) y luego 18 passed: token de 256 bits guardado como SHA-256 hex, caducidad de 30 min, enlace en el fragmento, descarte de trabajos con 30 min o más, política 8–128 en reset y cambio, `extra="forbid"` y `hide_input_in_errors` (el token y la contraseña no salen en el error), recordatorio de Google y aviso sin enlaces, y error sin SMTP.

- [x] **T3. `POST /auth/password/forgot` y worker de correos de cuenta.** RF-001, RF-002, RF-002b, RF-003, RF-010, RF-011, RNF-001, CL-1, CL-2, CL-6–CL-8
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_password_recovery_endpoints.py tests/test_account_email_worker.py -k forgot` verde (respuesta idéntica en los cuatro casos, envío según tipo, fallo SMTP que invalida el token, nada sensible en logs, 429/503).
- Evidencia: en rojo sin el router registrado (17 failed) y sin invalidar el enlace tras el fallo SMTP (1 failed); luego `-k forgot` 8 passed contra PostgreSQL 17: `202 {}` idéntico y sin cookie para cuenta local, solo-Google, desactivada e inexistente, sin envío dentro de la petición; el worker envía el enlace `/password/reset#…` a la local, el recordatorio a la solo-Google y nada a las otras dos; el enlace nuevo invalida el anterior y cada petición emite un token distinto; el fallo SMTP invalida el enlace y deja el reintento en espera; el trabajo de 30 min o más se descarta sin envío; los logs no contienen correos, tokens ni enlaces; 422 sin eco del valor; 429 con `Retry-After` y 503 con Redis caído en `forgot` y `reset`.

- [x] **T4. `POST /auth/password/reset`.** RF-004, RF-005, RF-008, RF-009, RF-010, RNF-003, RNF-004, CL-3, CL-5
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_password_recovery_endpoints.py -k reset` verde (un solo uso, caducado, anterior invalidado, cuenta desactivada, igual a la actual, todas las sesiones revocadas, aviso y evento).
- Evidencia: `-k reset` 6 passed: el enlace cambia la contraseña una vez, revoca todas las sesiones y encola el aviso; segundo uso, enlace desconocido y enlace sustituido dan el mismo `400 PASSWORD_RESET_INVALID` sin cambiar nada; la contraseña actual da `400 PASSWORD_REUSED` y conserva el enlace; una sesión abierta de otra cuenta no interviene. Caducidad, cuenta desactivada y concurrencia los cubre `test_migration_062.py` sobre la misma función. Argon2 en `asyncio.to_thread`.

- [x] **T5. `GET /auth/password` y `POST /auth/password/change`.** RF-006–RF-010, CL-4
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_password_recovery_endpoints.py -k change` verde (actual incorrecta, solo-Google 409, se mantiene solo la sesión actual, enlaces pendientes invalidados, límite).
- Evidencia: `-k change` 6 passed: `GET /auth/password` devuelve `has_password`; el cambio mantiene solo la sesión actual (`jti`), invalida los enlaces pendientes y encola el aviso; actual incorrecta `400 CURRENT_PASSWORD_INVALID` y repetida `400 PASSWORD_REUSED` sin cambios; solo-Google `409 PASSWORD_NOT_SET`; sin sesión 401; límite `password-change` con `AUTH_LOGIN_RATE_LIMIT`/60 s por cuenta.

- [x] **T6. Retención y configuración.** RF-011, RF-012
- Hecho cuando: `pytest -q tests/test_retention.py` verde con la purga de recuperación; `.env.example` y `config.py` con `AUTH_PASSWORD_RESET_RATE_LIMIT`; suite completa con PostgreSQL 17 y Redis, `ruff check .`, `bandit -q -r app -ll` y `python -m compileall -q app` verdes.
- Evidencia (2026-11-16): `tests/test_retention.py` verde con la purga de recuperación (lotes de 500, corte de 7 días, eventos de seguridad conservados) y los correos de cuenta en un bucle propio del worker; `AUTH_PASSWORD_RESET_RATE_LIMIT` en `config.py`, `.env.example`, compose y contrato de entorno, y `FRONTEND_BASE_URL` en el worker; suite completa con PostgreSQL 17 y Redis `4240 passed, 4 skipped` (antes de los arreglos de revisión; tras ellos, los seis archivos afectados `66 passed`), `ruff check .`, `bandit -q -r app -ll` y `python -m compileall -q app` verdes. Revisión de #100: orden de bloqueo usuario → enlace en `complete_password_reset` y revalidación del hash en el login tras crear la sesión.

- [x] **T7. Pantallas `/password/forgot` y `/password/reset` y enlace en el login.** RF-001, RF-005, RF-013
- Hecho cuando: `pnpm test -- password-recovery` verde (confirmación genérica, token leído y retirado del fragmento, errores, ES/EN, foco); `pnpm run lint` y `pnpm run typecheck` verdes.
- Evidencia (2026-11-16): `tests/password-recovery.test.ts` (token solo del fragmento y retirado con `history.replaceState`, confirmación genérica, catálogo cerrado de errores ES/EN, foco en confirmación y errores; el éxito cierra la sesión local y vuelve al login con aviso); `pnpm test` 1124 pass, `pnpm run lint` y `pnpm run typecheck` verdes.

- [x] **T8. Pantalla `/account/password` y menú de cuenta.** RF-006, RF-007, RF-013, DA-1
- Hecho cuando: `pnpm test -- password-recovery` verde también para el cambio (actual incorrecta, solo-Google sin formulario, éxito) y la entrada del menú en escritorio y móvil.
- Evidencia (2026-11-16): `tests/password-recovery.test.ts` cubre `/account/password` con middleware `session`, actual incorrecta con foco en su campo, aviso solo-Google sin formulario, éxito y la entrada «Cambiar la contraseña» del menú de escritorio y móvil del `WorkspaceShell`.

- [x] **T9. E2E de las tres pantallas.** RF-013
- Hecho cuando: `pnpm exec playwright test e2e/password-recovery.spec.ts --project public --no-deps` verde a 1440/390 px en ambos temas con contratos ficticios; `pnpm run typecheck:e2e` y `pnpm run build` verdes.
- Evidencia (2026-11-16): `e2e/password-recovery.spec.ts` (proyecto `public`, contrato ficticio de `/auth/password*`) `16 passed` a 1440/390 px en tema oscuro y claro: enlace del login, confirmación genérica con foco, validación local sin llamadas, token leído del fragmento y retirado de la URL, `PASSWORD_REUSED` y `PASSWORD_RESET_INVALID`, vuelta al login con aviso, cambio con actual incorrecta (foco en su campo), éxito y cuenta solo-Google sin formulario; axe sin violaciones en las tres pantallas y sin desbordamiento horizontal. `pnpm run typecheck:e2e` verde.

- [x] **T10. Documentación y cierre.** Todos
- Hecho cuando: README (rutas, runbook de la 062, límites), AGENTS, manual de usuario y MEMORY actualizados; trazabilidad de cada RF, RNF y CL con su evidencia en esta tarea; CI 7/7 en los PR.
- Documentación (2026-11-16): README (runbook de la 062 con rutas, respuestas, orden 062 → API/worker y `FRONTEND_BASE_URL`; límites en la sección de rate limit), AGENTS (F3), manual §1 y MEMORY.
- Trazabilidad (pruebas backend en `backend/tests/`: `test_migration_062.py` con base real, `test_password_recovery.py` puras/esquemas/correos, `test_password_recovery_endpoints.py`, `test_account_email_worker.py`; frontend `tests/password-recovery.test.ts` y `e2e/password-recovery.spec.ts`):
  - RF-001/RNF-001/CL-1: `forgot` responde `202 {}` en los cuatro casos sin leer `users`, sin Argon2 ni SMTP (endpoints); la pantalla muestra la misma confirmación (unit + E2E).
  - RF-002/RF-002b/CL-6: el worker envía el enlace `/password/reset#<token>` a cuentas locales, el recordatorio sin enlace a solo-Google y nada a inexistentes/desactivadas; sin SMTP no se registra el enlace (worker).
  - RF-003/CL-2: emitir invalida los pendientes (migración + worker).
  - RF-004/RF-005/CL-3: reset válido cambia el hash, marca usado y revoca todas las sesiones; usado, caducado, sustituido, desconocido o cuenta desactivada → `400 PASSWORD_RESET_INVALID` (migración + endpoints); la pantalla ofrece pedir otro enlace (E2E).
  - RF-006/RF-007: el cambio conserva la sesión del `jti` y revoca las demás; actual incorrecta → `400 CURRENT_PASSWORD_INVALID` sin cambios y con el límite del login (endpoints); foco en su campo (E2E).
  - RF-008/CL-4: recuperar o cambiar invalida los enlaces pendientes y encola el aviso sin enlaces; un fallo del aviso no revierte (migración + worker).
  - RF-009: 8–128 puntos de código y distinta de la actual (`PASSWORD_REUSED`) en esquemas y en el cliente (unit, incluido el caso Unicode fuera del BMP).
  - RF-010: 429 con `Retry-After` por IP+correo, IP+hash de enlace e IP+cuenta; Redis caído → 503 (endpoints); el cliente los traduce (unit).
  - RF-011/RNF-002: token de 256 bits, solo su SHA-256 en base; logs del worker solo con id y tipo de excepción; el cliente no registra ni envía el token por la ruta (worker + unit + E2E).
  - RF-012: `account_security_events` con cuenta, tipo y fecha, sin correo ni hash (migración).
  - RF-013: enlace en el login, tres pantallas y entrada en el menú de cuenta de escritorio y móvil, ES/EN, ambos temas, axe sin violaciones (unit + E2E).
  - RNF-003: dos resets simultáneos producen un solo cambio y recuperación/cambio concurrentes no se interbloquean (migración).
  - RNF-004: Argon2 vía `asyncio.to_thread` en reset y cambio (revisión de `password_router.py`; sin prueba dedicada).
  - RNF-005: suites backend y frontend completas y E2E en verde; CI de #99–#101.
  - CL-5: el enlace actúa sobre su propia cuenta; la respuesta del reset borra la cookie del navegador y el cliente limpia su estado, así que la sesión abierta nunca pasa a la cuenta del enlace (endpoints + unit).
  - CL-7: si SMTP falla, el worker invalida el enlace antes de reintentar (worker).
  - CL-8: `enqueue_password_reset_request` normaliza espacios y mayúsculas como el login (`test_062_request_does_not_resolve_the_account`).
- CI (2026-11-16): 7/7 en #99, #100 y #101 (GitGuardian omitido en los PR de código, como en las specs anteriores).
- No ejecutado: el flujo completo contra la pila real con SMTP real (el E2E usa un contrato ficticio y el worker se prueba con SMTP simulado) y un lector de pantalla real.
