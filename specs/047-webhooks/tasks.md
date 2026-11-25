# Tareas — Spec 047: Webhooks firmados por organización (F6, parte 2)

Estado: aprobado por el usuario el 2026-11-24 («Apruebo el plan y las tareas de la spec 047. Empieza por T1»).

## Bloque A — backend y migración (PR apilado sobre el #125)

- [x] **T1. Migración 068.** RF-001, RF-003, RF-005, RF-008, RF-011, RF-013
- Hecho cuando: `068_webhooks.sql` sigue el plan §2; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_webhooks_migration.py` pasa sobre un volumen limpio y uno ya migrado, tras ver fallar primero los casos nuevos; `sh -n infra/postgres/migrate.sh` pasa.
- Evidencia (2026-11-24): `test_webhooks_migration.py` falló primero (sin `068_webhooks.sql`) y ahora pasa 25/25 con PostgreSQL real, incluidos volumen limpio = migrado y reaplicación sin cambios; con `test_notifications_migration.py`, `test_notification_delivery.py` y `test_migration_064.py` pasan 60, y la suite backend completa con base de datos pasa 4709 (sin `test_config.py`, que falla por las variables de Google del `.env` local). `sh -n infra/postgres/migrate.sh` y Ruff limpios.
- [x] **T2. Catálogo puro, red y configuración.** RF-002, RF-003, RF-006, RF-007, RF-009, RF-011, RNF-002
- Hecho cuando: `catalog.py`, `network.py`, `config.py`, `.env.example`, los compose y `check_env_contract.py` siguen el plan §3–§4; `cd backend && pytest -q tests/test_webhook_catalog.py tests/test_webhook_network.py tests/test_config.py` y `python infra/scripts/check_env_contract.py` pasan, tras ver fallar primero los tests nuevos; `ruff check .` limpio.
- Evidencia (2026-11-24): los tests nuevos fallaron primero (módulos ausentes y 2 de `test_config.py`); ahora `test_webhook_catalog.py`, `test_webhook_network.py` y `test_config.py` pasan 83. `check_env_contract.py` cumple en desarrollo y en producción (54 variables), igual que `assert_production_compose.py`; suite backend sin BD 3323 pasados; Ruff, Bandit y compileall limpios. `WEBHOOK_SECRET_KEY` se añadió a API y worker, a la CI y al render de producción; fuera de desarrollo se rechaza el valor por defecto y una clave igual a `PLAYER_DATA_KEY`.
- [ ] **T3. API de gestión y auditoría.** RF-001–RF-004, RF-008, RF-012, RF-013
- Hecho cuando: los endpoints del plan §5 están registrados en `main.py` y las acciones en el catálogo de la 041; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_webhook_api.py tests/test_request_schema_strictness.py` pasa, tras ver fallar primero los casos nuevos.
- [ ] **T4. Entrega en el worker.** RF-005–RF-011, RNF-001, RNF-002
- Hecho cuando: `delivery.py`, el bucle de webhooks y la purga siguen el plan §3; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_webhook_delivery.py tests/test_worker*.py tests/test_retention.py` pasa, tras ver fallar primero los casos nuevos.
- [ ] **T5. Validación del bloque A y PR.** Todos los RF del bloque
- Hecho cuando: la suite backend con BD, `ruff check .`, `bandit -r app -ll` y `python -m compileall -q app` están limpios; PR del bloque A con la CI en verde.

## Bloque B — frontend, E2E y documentación (PR apilado sobre el bloque A)

- [ ] **T6. Gestión de webhooks en el Workspace.** RF-001–RF-003, RF-012
- Hecho cuando: `utils/webhooks.ts`, `useWebhooks`, la página `/workspace/webhooks`, sus componentes y el enlace con permiso siguen el plan §5; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios, tras ver fallar primero los tests nuevos.
- [ ] **T7. Textos ES/EN y auditoría en el Workspace.** RF-004, RNF-004
- Hecho cuando: las claves `webhook.*` y las acciones nuevas de la auditoría tienen paridad ES/EN y se muestran en `/workspace/audit`; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios, tras ver fallar primero los tests nuevos.
- [ ] **T8. E2E, documentación y validación.** RNF-004
- Hecho cuando: `e2e/webhooks.spec.ts` pasa con axe sin violaciones en ambos temas a 1440 y 390 px; README (runbook de la 068 y de `WEBHOOK_SECRET_KEY`, con el formato de la firma para los receptores), AGENTS, manual, informe y MEMORY actualizados; `pnpm run build`, `pnpm run typecheck:e2e` y la suite backend completa con BD pasan; PR del bloque B con la CI en verde.
