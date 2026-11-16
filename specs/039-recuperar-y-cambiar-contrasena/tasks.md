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

- [ ] **T9. E2E de las tres pantallas.** RF-013
- Hecho cuando: `pnpm exec playwright test e2e/password-recovery.spec.ts --project public --no-deps` verde a 1440/390 px en ambos temas con contratos ficticios; `pnpm run typecheck:e2e` y `pnpm run build` verdes.

- [ ] **T10. Documentación y cierre.** Todos
- Hecho cuando: README (rutas, runbook de la 062, límites), AGENTS, manual de usuario y MEMORY actualizados; trazabilidad de cada RF, RNF y CL con su evidencia en esta tarea; CI 7/7 en los PR.
