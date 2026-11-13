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
- T53: `VERIFY_FONT_BUILD=1 pnpm test`: **948 tests, 948 pass, 0 fail, 0 skipped**. Typecheck, lint, build y typecheck E2E salen 0; build en 10.5 s. `pnpm run e2e:test` contra pila local ya iniciada: **54 passed (4.6m)**, **RESULTADO: VERDE (0)**. El contenedor del runner no tiene Docker CLI: no hay `server.log` del runner; no afecta las pruebas de navegador ni acredita logs de despliegue.

## Evidencia visual T53

96 PNG reales con Chromium/Playwright 1.64.1 sobre el build local servido en `localhost:3001`, datos ficticios de los fixtures de F9. Capturas fuera del repo, en `/home/ubuntu/f9-visual/`; no forman parte del commit. Matriz completa 1440/390 px × ES/EN × oscuro/claro. En recortes de formularios altos la altura del viewport se amplía para evitar que la cabecera sticky tape el título; los diálogos se capturan con viewport de 1000 px de alto. No hay cambios de layout para producir las capturas.

Rutas exactas enumeradas en `/home/ubuntu/f9-visual/capturas.txt`; metadatos en `manifest.json` y hashes en `SHA256SUMS`, en el mismo directorio. Cada archivo es `<prefijo>-<superficie>.png`:

- Prefijos: `1440-es-dark`, `1440-es-light`, `1440-en-dark`, `1440-en-light`, `390-es-dark`, `390-es-light`, `390-en-dark`, `390-en-light`.
- Superficies: `workspace`, `appeal`, `appeal-confirmation`, `proposal`, `detail`, `withdrawal`, `owner-authorizations`, `notices`, `lineup`, `admin`, `admin-detail`, `admin-confirmation`.
- Hojas de revisión: `contact-<prefijo>.png` (ocho hojas).
- **Claves:** `390-es-light-appeal.png`, `390-es-dark-appeal-confirmation.png`, `1440-en-dark-detail.png`, `390-en-dark-owner-authorizations.png`, `390-en-light-lineup.png`, `390-en-dark-admin.png`, `1440-en-light-admin-detail.png`, `390-en-light-admin-confirmation.png`.

Se miraron las ocho hojas y las capturas clave a mayor resolución. Formularios/confirmaciones, autorizaciones, avisos, aviso de alineación y administración legibles en ambos temas; no se detectaron desbordes horizontales ni claves i18n sin resolver. El texto libre ficticio conserva su idioma original: no es una traducción de interfaz. Se repitieron las tomas con cabecera sticky intercalada por el scroll de captura y se corrigió la fixture externa de captura de `/admin` (respuestas paginadas `{items: []}` en vez de arrays que causaban un error artificial). **No se necesitaron cambios visuales de producto.** La advertencia de conexión en operación es la desconexión esperada del fixture; el aviso F9 se lee y no bloquea guardar/publicar, comprobado en E2E.

No sustituye una auditoría de accesibilidad completa, SMTP real, login productivo de plataforma, CI remota ni aceptación humana.

## Gate local de seguridad e infraestructura T54

- `ruff check .`: **All checks passed!**. `bandit -r app -ll`: **No issues identified.**, Medium 0 / High 0 (12 Low fuera del umbral existente; sin nuevas exclusiones).
- `pip-audit -r requirements.txt -r requirements-dev.txt`: **No known vulnerabilities found**.
- `pnpm audit --prod --json --audit-level low` + `audit_frontend.py`: **Resultado: OK**, 524 dependencias; cinco avisos no accionables visibles (tres moderate y dos low), sin ignorarlos ni cambiar dependencias.
- Gitleaks v8.30.1 sobre `git archive HEAD`, con configuración del proyecto y redacción: **no leaks found**.
- Trivy 0.70.0, equivalente CLI de la acción fijada v0.36.0: **salida 0**, requirements y pnpm-lock sin vulnerabilidades HIGH/CRITICAL corregibles; sin cambios al workflow.
- Runner PostgreSQL: **OK: todas las pruebas de MIGRATION_TARGET pasaron**. Grants, RLS, checksums, limpio/migrado y migración 040 están incluidos en los 3406 tests de T52; no se repiten porque D no cambia backend ni esquema.
- Sintaxis de migrate/healthcheck: salida 0. Versiones: **OK: Python 3.14, Node 24 y pnpm 12.12.1 coinciden en las fuentes verificadas**; **OK: Docker Compose 5.6.1 >= 2.24.4**.
- Compose dev y merge prod con dummy: salida 0, estructura y contrato de siete servicios/51 variables OK en ambos perfiles. **OK: self-test del contrato de configuración**.

Son comprobaciones locales. No se ha abierto un PR: los jobs remotos y la aceptación humana son requisitos pendientes del cierre formal T55, no se dan por verdes ni por aceptados.

## Límites

La fixture de plataforma no requiere una cuenta sembrada: no se modifica el seed ni se amplían grants de plataforma. Las pruebas PostgreSQL crean sus actores y autorizaciones aislados y comprueban las dos auditorías. La aceptación humana y los jobs remotos del futuro PR no se infieren de resultados locales.
