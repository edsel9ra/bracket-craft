# Verificación 033 — Acta rectificativa

## Cobertura de criterios 1–9

| Criterio | Evidencia ejecutable |
|---|---|
| 1. Solicitud válida/invalidación y referencias | `test_rectification_flow.py`, `rectification-components.test.ts`, E2E real `rectification.spec.ts` (editor completo). |
| 2. Separación solicitante/aprobador | `test_rectification_flow.py`, `test_rectification_platform.py`, `test_migration_035.py`; E2E separado owner sin botones y retirada. |
| 3. Decisión motivada y delegación auditada | `test_rectification_platform.py`, `test_rectification_flow.py`; E2E de aprobación por otro miembro. |
| 4. Pendiente/rechazada/retirada y preview sin cambios | `test_rectification_flow.py`, `test_rectification_platform_preview.py`, `test_rectification_effects.py`; E2E compara resultado pendiente e historial tras preview/retirada. |
| 5. Atomicidad e inmutabilidad | `test_rectification_effects.py`, `test_migration_035.py`, `test_migration_036.py`; E2E compara todos los originales/históricos después de publicar. |
| 6. Derivados y lectores vigentes | `test_rectification_effects.py`, `test_rectification_sanctions.py`, `test_rectification_readers.py`, `test_migration_038.py`; E2E comprueba API pública y marcador/marca en la llave. |
| 7. Impactos sin alterar posteriores | `test_rectification_effects.py`, `test_migration_039.py`: snapshot de fase completa, bloqueo DB/API, permisos y cierre `keep_as_played`. |
| 8. Outbox y notificaciones | `test_rectification_notifications.py` y tests del worker: alcance organizativo, decisiones, rollback y reintento SMTP. |
| 9. Aislamiento | `test_migration_035.py`, `test_rectification_workspace_reads.py`, `test_rectification_platform.py`: RLS, 404 y páginas vacías indistinguibles. |

## Reproducción E2E

```sh
docker compose up -d --build --wait --wait-timeout 300
docker compose exec -T api python -m scripts.seed_demo
cd frontend
pnpm exec playwright test e2e/rectification.spec.ts --project workspace
```

Chromium headless, storageState del setup Workspace, sin mocks HTTP/BD, sin UUID fijos, sin escritura SQL ni alta de usuarios desde el test. El seed de desarrollo añade un administrador distinto del owner con la misma contraseña ficticia. El test lo descubre por API y conserva sesiones independientes; la consulta final pública no lleva sesión. Un caso publica una nueva versión, el otro retira su pendiente. La limpieza retira pendientes propias tras un fallo, sin borrar auditoría. Las corridas repetidas usan la versión vigente como base y no reescriben históricos.

## Verificación local de T18 (2026-11-12)

Python 3.14.10, Node 24.22.3, pnpm 12.12.1 y Chromium de Playwright 1.64.1; API, worker, Redis y PostgreSQL reales de Compose. Primero se ejecutó el archivo solicitado; después, los checks equivalentes de los cinco jobs de `.github/workflows/ci.yml`.

| Check | Resultado |
|---|---|
| `pnpm exec playwright test e2e/rectification.spec.ts --project workspace` | `3 passed (10.9s)`; incluye setup y ambos casos. |
| `pnpm run e2e:test`, con stack y seed ya preparados | `43 passed (4.1m)`, `RESULTADO: VERDE (0)`; los proyectos existentes incluyen rectificación, tema, public-polish y operation-flow. |
| `RUN_DATABASE_TESTS=1 pytest -q -rs`, base aislada inicializada/migrada | `3159 passed, 4 skipped in 460.54s (0:07:40)`; los cuatro requieren el seed demo. |
| Cuatro casos omitidos por falta de demo, ejecutados con seed | 2 pass en 1.33s (dependencia real de membresía, transacciones revertidas), 2 pass en 1.13s (invitaciones, base demo aislada). |
| `pytest -q`, sin habilitar DB | `2439 passed, 724 skipped in 10.54s`. |
| `pnpm test` | 918 tests, 917 pass, 0 fail, 1 skip opt-in de fuente compilada. |
| `VERIFY_FONT_BUILD=1 node --test --experimental-strip-types tests/fonts.test.ts` | 2 pass, 0 fail, 0 skip, sobre el build real. |
| Typecheck, typecheck E2E, lint y build frontend | Salida 0; build completo en 9.21s. |
| Ruff, compileall y Bandit | Salida 0; `All checks passed!` y `No issues identified.` |
| Infraestructura | Versiones de referencia, sintaxis shell, Compose development/production, contratos de entorno y self-test, estructura de ambos perfiles y runner `MIGRATION_TARGET`: salida 0. |
| `pip-audit` | `No known vulnerabilities found`. |
| Auditoría frontend con la política de CI | `Resultado: OK`; cinco hallazgos no accionables (cuatro moderate, uno low sin corrección). |

El primer intento del full DB quedó invalidado por ejecutar en paralelo el runner `MIGRATION_TARGET`, que cambia la contraseña global de `bracket_app`. Se restauró el default local y se ejecutó el full DB después del runner, como hace CI; no se cambió código ni se relajaron aserciones. La imagen de Playwright no incluye Docker CLI: los logs de Compose se recogieron desde el host, sin repetir tests ni sustituir la API. Se mantiene el aviso existente de Nuxt sobre CSS de operación no inline.

**T18 cerrada tras verificar la CI remota del PR #67** sobre `232eb6c1` con `git_pr_checks(wait_mode="all")`: seis checks aprobados, ninguno fallido, pendiente ni omitido. Incluye Backend tests, Frontend checks, Dependency and filesystem scan, Infrastructure checks, Realtime retry end-to-end y GitGuardian Security Checks. El verde local anterior no sustituye esta comprobación remota.

La cobertura E2E no sustituye las pruebas DB de los nueve criterios. SMTP se comprueba con transporte simulado: no se certifica entrega de correo real. Tampoco es una certificación de producción ni una auditoría visual manual.
