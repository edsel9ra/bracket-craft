# Tareas — Spec 052: Estadísticas adicionales (F17)

Estado: aprobadas el 2026-11-27 («Apruebo el plan y las tareas, empieza por T1»).

Dos PR de implementación apilados sobre el PR de la spec: bloque A (T1–T5, backend) y bloque B (T6–T8, frontend, E2E y documentación).

## Bloque A — backend

- [ ] **T1. Migración 070.** RF-007, RF-009, RNF-002
- Hecho cuando: `infra/postgres/migrations/070_additional_player_stats.sql`; `tests/test_migration_070.py` falla primero y pasa con `RUN_DATABASE_TESTS=1` sobre volumen limpio y migrado; `sh -n infra/postgres/migrate.sh`.
- [ ] **T2. Contrato del hecho y validación del catálogo.** RF-007, RF-008, RF-009
- Hecho cuando: `POSITION_LINES`, `positions_for_game_format`, `EVENT_TYPES` y `player_in_position` en `MatchEventPayload`; tests de esquema y de `rule_contract` fallan primero y pasan con `cd backend && pytest -q tests/test_rule_contract.py tests/test_match_event_payload*.py`.
- [ ] **T3. Persistencia en cierre clásico, en vivo y rectificación.** RF-006–RF-010, RF-015
- Hecho cuando: los tres flujos guardan y devuelven la columna y el tipo nuevo; posición fuera del catálogo → 422 sin escritura; marcador, clasificación, sanciones, fair play y cronología iguales; tests con BD en rojo primero y en verde.
- [ ] **T4. Cálculo y superficies públicas.** RF-001–RF-006, RF-012–RF-016, RNF-001, RNF-003
- Hecho cuando: `compute_player_stats` con los tres datos; `player-stats`, ficha, CSV y acta exportada; lista cerrada, `docs/api-publica/openapi-v1.json`, ejemplos e historial ES/EN; `test_public_stats_additional.py` y los de rutas en rojo primero y en verde; `python -m scripts.public_api_reference --check` termina con 0.
- [ ] **T5. Suite completa y PR del bloque A.**
- Hecho cuando: suite backend completa con BD, Ruff, Bandit y compileall sin errores; PR del bloque A con la CI en verde.

## Bloque B — frontend, E2E y documentación

- [ ] **T6. Workspace: posición de entrada y penal atajado.** RF-011, RF-012
- Hecho cuando: acta clásica, en vivo y rectificación ofrecen ambos campos y los muestran; ES/EN; tests en rojo primero y en verde con `cd frontend && pnpm test`; `pnpm run typecheck` y `pnpm run lint`.
- [ ] **T7. Sitio público: tabla y ficha.** RF-001–RF-004, RNF-004
- Hecho cuando: columnas nuevas en `PublicPlayerStatsTable.vue` y en la ficha, con líneas traducidas; tests en rojo primero y en verde; typecheck y lint.
- [ ] **T8. E2E, documentación y PR del bloque B.**
- Hecho cuando: `operationFlow.spec.ts` y `public-polish.spec.ts` ampliados pasan con axe en los dos temas; build; README, AGENTS, manual, informe (F17 implementada) y MEMORY; PR del bloque B con la CI en verde.
