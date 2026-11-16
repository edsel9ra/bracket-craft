# Tareas — Spec 039: Recuperar y cambiar la contraseña

Estado: borrador, pendiente de aprobación. PR documental y un PR por bloque: A (T1–T6, backend) y B (T7–T10, frontend, E2E, documentación y cierre).

- [ ] **T1. Migración 062: tablas y funciones de recuperación.** RF-002–RF-005, RF-008, RF-012, RNF-002, RNF-003
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_062.py` en rojo y luego verde (sin privilegios directos, `EXECUTE` solo para `bracket_app`, un solo uso concurrente, revocación de sesiones); `sh -n infra/postgres/migrate.sh`; cadena limpia 001→062 y salto 061→062.

- [ ] **T2. Funciones puras, esquemas y plantillas de correo.** RF-002, RF-002b, RF-008, RF-009, RNF-002
- Hecho cuando: `pytest -q tests/test_password_recovery.py` verde tras confirmarlo en rojo (caducidad, token, hash, URL con fragmento, política, correos sin enlaces de acción en el aviso).

- [ ] **T3. `POST /auth/password/forgot` y worker de correos de cuenta.** RF-001, RF-002, RF-002b, RF-003, RF-010, RF-011, RNF-001, CL-1, CL-2, CL-6–CL-8
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_password_recovery_endpoints.py tests/test_account_email_worker.py -k forgot` verde (respuesta idéntica en los cuatro casos, envío según tipo, fallo SMTP que invalida el token, nada sensible en logs, 429/503).

- [ ] **T4. `POST /auth/password/reset`.** RF-004, RF-005, RF-008, RF-009, RF-010, RNF-003, RNF-004, CL-3, CL-5
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_password_recovery_endpoints.py -k reset` verde (un solo uso, caducado, anterior invalidado, cuenta desactivada, igual a la actual, todas las sesiones revocadas, aviso y evento).

- [ ] **T5. `GET /auth/password` y `POST /auth/password/change`.** RF-006–RF-010, CL-4
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_password_recovery_endpoints.py -k change` verde (actual incorrecta, solo-Google 409, se mantiene solo la sesión actual, enlaces pendientes invalidados, límite).

- [ ] **T6. Retención y configuración.** RF-011, RF-012
- Hecho cuando: `pytest -q tests/test_retention.py` verde con la purga de recuperación; `.env.example` y `config.py` con `AUTH_PASSWORD_RESET_RATE_LIMIT`; suite completa con PostgreSQL 17 y Redis, `ruff check .`, `bandit -q -r app -ll` y `python -m compileall -q app` verdes.

- [ ] **T7. Pantallas `/password/forgot` y `/password/reset` y enlace en el login.** RF-001, RF-005, RF-013
- Hecho cuando: `pnpm test -- password-recovery` verde (confirmación genérica, token leído y retirado del fragmento, errores, ES/EN, foco); `pnpm run lint` y `pnpm run typecheck` verdes.

- [ ] **T8. Pantalla `/account/password` y menú de cuenta.** RF-006, RF-007, RF-013, DA-1
- Hecho cuando: `pnpm test -- password-recovery` verde también para el cambio (actual incorrecta, solo-Google sin formulario, éxito) y la entrada del menú en escritorio y móvil.

- [ ] **T9. E2E de las tres pantallas.** RF-013
- Hecho cuando: `pnpm exec playwright test e2e/password-recovery.spec.ts --project public --no-deps` verde a 1440/390 px en ambos temas con contratos ficticios; `pnpm run typecheck:e2e` y `pnpm run build` verdes.

- [ ] **T10. Documentación y cierre.** Todos
- Hecho cuando: README (rutas, runbook de la 062, límites), AGENTS, manual de usuario y MEMORY actualizados; trazabilidad de cada RF, RNF y CL con su evidencia en esta tarea; CI 7/7 en los PR.
