# Tareas — Spec 046: Notificaciones en la app y por correo (F6, parte 1)

Estado: aprobado por el usuario el 2026-11-24 («Apruebo el plan y las tareas»).

## Bloque A — backend y migración (PR apilado sobre el #122)

- [ ] **T1. Migración 067.** RF-002, RF-004, RF-006, RF-007, RF-012, RF-013
- Hecho cuando: `067_notifications.sql` sigue el plan §2; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_notifications_migration.py` pasa sobre un volumen limpio y uno ya migrado, tras ver fallar primero los casos nuevos; `sh -n infra/postgres/migrate.sh` pasa.
- [ ] **T2. Catálogo puro y registro.** RF-001, RF-002, RF-006, RF-011
- Hecho cuando: `catalog.py` y `recorder.py` siguen el plan §3; `cd backend && pytest -q tests/test_notification_catalog.py` pasa, tras ver fallar primero los tests; `ruff check .` limpio.
- [ ] **T3. Productores.** RF-001–RF-004
- Hecho cuando: el calendario, el alta, el cierre, el W.O. y las suspensiones registran sus avisos según el plan §3; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_notification_producers.py` pasa, tras ver fallar primero los casos nuevos.
- [ ] **T4. Entrega en el worker.** RF-007, RF-011, RF-012, RNF-002
- Hecho cuando: `delivery.py`, `send_notification_email` y el bucle de correo aparte siguen el plan §3; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_notification_delivery.py tests/test_worker*.py` pasa, tras ver fallar primero los casos nuevos.
- [ ] **T5. API de bandeja y preferencias, y PR del bloque A.** RF-005, RF-008–RF-010, RF-013
- Hecho cuando: los endpoints del plan §5 están registrados en `main.py`; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_notification_api.py` pasa, tras ver fallar primero los casos nuevos; la suite backend con BD, `ruff check .`, `bandit -r app -ll` y `python -m compileall -q app` limpios; PR del bloque A con la CI en verde.

## Bloque B — frontend, E2E y documentación (PR apilado sobre el bloque A)

- [ ] **T6. Bandeja en el Workspace.** RF-008–RF-010, RNF-003
- Hecho cuando: `utils/notifications.ts`, `useNotifications`, la página, `NotificationInbox` y el enlace con no leídos siguen el plan §5; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios, tras ver fallar primero los tests nuevos.
- [ ] **T7. Preferencias y textos ES/EN.** RF-005, RF-006, RNF-003
- Hecho cuando: `useNotificationPreferences` y `NotificationPreferences` siguen el plan §5 y las claves `notification.*` tienen paridad ES/EN; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios, tras ver fallar primero los tests nuevos.
- [ ] **T8. E2E, documentación y validación.** RNF-003
- Hecho cuando: `e2e/notifications.spec.ts` pasa con axe sin violaciones en ambos temas a 1440 y 390 px; README, AGENTS, manual, informe y MEMORY actualizados, incluido el despliegue de la 067; `pnpm run build`, `pnpm run typecheck:e2e` y la suite backend completa con BD pasan; PR del bloque B con la CI en verde.
