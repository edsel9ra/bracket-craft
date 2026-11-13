# Verificación F9 — spec 034

Implementación A–D. Evidencia de desarrollo con datos ficticios; no certifica producción ni sustituye aceptación humana. D añade `/admin/sanction-cases`, sin nuevas rutas backend, migraciones, permisos o campos públicos.

## Inventario de lectores y fronteras

| Camino | Lectura/control vigente |
|---|---|
| Apertura de partido | `record_sanction_opening`, solo CLOSE_MATCH_REPORT; snapshot y aplicación tras coordinador. |
| Cierre regular/walkover | Lectura operacional acotada al partido/organización; CLOSE_MATCH_REPORT, incluidos oficiales asignados. |
| Cierre administrativo | Owner/administrador activo con RESOLVE_MATCH_ADMINISTRATIVELY; no amplía apertura. |
| Solicitud/publicación 033 | Lectura mínima con REQUEST_MATCH_REPORT_RECTIFICATION o autorización 033 vigente para el partido; sin expedientes ni evidencia. |
| Workspace | VIEW_SANCTION_CASES para listado/detalle; presentar, proponer y retirar no implican lectura. |
| Plataforma F9 | `sanction_platform_scopes`, `sanction_platform_history`; autorización F9 exacta, no hereda 033 ni crea membresía. |
| Alineación | GET privado de `player_id` y `remaining`; error/aviso no bloquea guardar/publicar. |
| Avisos | Revalidación C5 en entrega/lectura; sin evidencia, sin Socket.IO. |
| Público | Proyecciones allowlist existentes, sin campos F9. |

## Trazabilidad RF

Todos los nombres siguientes son archivos de `backend/tests/`, salvo los prefijos frontend explícitos. La selección describe cobertura, no añade excepciones ni reemplaza la suite integral.

| RF | Prueba/evidencia |
|---|---|
| 001 | test_sanction_cases.py, test_sanction_effective.py |
| 002 | test_sanction_cases.py, frontend/e2e/sanction-workspace.spec.ts |
| 003 | test_sanction_effective_integration.py, test_sanction_close_permissions.py |
| 004 | test_sanction_cases.py, test_sanction_timestamps.py |
| 005 | test_migration_040.py, test_sanction_security.py, test_sanction_rollback.py |
| 006 | test_sanction_readers.py, test_sanction_platform.py, frontend/e2e/sanction-platform.spec.ts |
| 007 | test_sanction_rectification.py, test_rectification_flow.py |
| 008 | test_sanction_rectification.py, test_public_field_allowlist.py |
| 009 | test_migration_040.py, test_sanction_cases.py |
| 010 | test_sanction_effective.py, test_sanction_effective_integration.py |
| 011 | test_sanction_rectification.py, test_rectification_sanctions.py |
| 012 | test_sanction_effective_integration.py, test_rectification_sanctions.py |
| 013 | test_sanction_cases.py, frontend/tests/sanction-detail.test.ts |
| 014 | test_sanction_readers.py, test_sanction_close_permissions.py |
| 015 | test_sanction_security.py, test_sanction_platform.py, frontend/e2e/sanction-platform.spec.ts |
| 016 | test_sanction_security.py, test_sanction_rollback.py |
| 017 | test_public_field_allowlist.py, test_public_access_matrix.py, frontend/e2e/sanction-platform.spec.ts (HTTP público real) |
| 018 | test_sanction_cases.py, test_sanction_api.py |
| 019 | test_migration_040.py, frontend/tests/sanction-composable.test.ts |
| 020 | test_sanction_schemas.py, test_sanction_cases.py |
| 021 | test_sanction_platform.py, frontend/e2e/sanction-platform.spec.ts |
| 022 | test_sanction_cases.py, frontend/e2e/sanction-workspace.spec.ts |
| 023 | test_sanction_platform.py, test_sanction_platform_duplicates.py |
| 024 | test_sanction_platform.py (auditorías reales), test_sanction_rollback.py |
| 025 | test_sanction_rectification.py, test_sanction_rectification_lock.py, test_sanction_concurrency.py |
| 026 | test_sanction_cases.py, frontend/tests/sanction-forms.test.ts |
| 027 | test_sanction_cases.py, frontend/tests/sanction-inbox.test.ts |
| 028 | test_sanction_cases.py, test_sanction_schemas.py |
| 029 | test_sanction_cases.py, test_sanction_concurrency.py, frontend/e2e/sanction-workspace.spec.ts (retirada sin VIEW) |
| 030 | test_sanction_timestamps.py, test_sanction_effective_integration.py |
| 031 | test_sanction_warnings.py, frontend/e2e/sanction-workspace.spec.ts |
| 032 | test_sanction_notifications.py, test_sanction_email.py |
| 033 | test_sanction_notifications.py, test_sanction_email.py, test_sanction_rollback.py |
| 034 | test_sanction_schemas.py, frontend/tests/sanction-forms.test.ts, frontend/e2e/sanction-workspace.spec.ts |

## Ejecución D

- T50: dos tests nuevos, regresión singleFlight existente; suite frontend 948 tests, 947 pasan y 1 opt-in de fuente omitido; typecheck/lint correctos.
- T51: 3 E2E admin con fixture HTTP (sin membresía, consumo, revocación entre preview/decisión, auto-decisión, error/reintento). Un E2E adicional consulta las proyecciones públicas reales y rechaza lecturas F9 anónimas. No prueban login real de plataforma ni auditorías SQL: esas comprobaciones se hacen en `test_sanction_platform.py` con PostgreSQL, dentro de los 18 tests dirigidos que pasan.
- T52: `RUN_DATABASE_TESTS=1 python -m pytest -q`: **3406 passed in 604.28s (0:10:04)**, PostgreSQL 17 y Python 3.14, sin skips; compileall correcto. Incluye 033, concurrencia, rollback, grants/RLS y migraciones.
- Capturas, gates finales y aceptación: pendientes de registrar.

## Límites

La fixture de plataforma no requiere una cuenta sembrada: no se modifica el seed ni se amplían grants de plataforma. Las pruebas PostgreSQL crean sus actores y autorizaciones aislados y comprueban las dos auditorías. La aceptación humana y los jobs remotos del futuro PR no se infieren de resultados locales.
