# Tareas — Spec 045: Guardar la alineación sin despublicar al rival

Estado: aprobado por el usuario el 2026-11-24 («Apruebo el plan y las tareas»).

## PR de implementación (apilado sobre el #120)

- [x] **T1. Firmas de publicación por equipo.** RF-001, RF-002, RF-004
- Hecho cuando: `team_publication_signatures` y `withdrawn_publications` existen en `audit.py` según el plan §2–§3; `cd backend && pytest -q tests/test_match_operation_audit.py` pasa, tras ver fallar primero los casos nuevos; `ruff check .` limpio.
- Evidencia (2026-11-24): los cuatro tests nuevos de `test_match_operation_audit.py` fallaron primero en la colección (`team_publication_signatures` inexistente). `team_publication_signatures` da una firma por equipo con formación (formación y pares jugador/rol/posición ordenados, sin minutos), y un cambio en un equipo no altera la firma del otro. `withdrawn_publications` devuelve, en orden estable, los equipos publicados cuya firma cambia o desaparece (planilla clásica). `lineup_signature` no cambia. Pasan 14 (+10 omitidos sin BD); `ruff check .` limpio.
- [ ] **T2. Guardar conserva la publicación y audita la retirada.** RF-001–RF-008, RNF-003
- Hecho cuando: `save_match_lineup` conserva `is_public`/`published_at` de los equipos sin cambios y registra `UNPUBLISH_MATCH_LINEUP` por cada retirada; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_lineup_publication_preservation.py tests/test_match_operation_audit.py tests/test_lineup_game_format.py` pasa, tras ver fallar primero los casos nuevos; suite backend con BD, `ruff check .`, `bandit -r app -ll` y `python -m compileall -q app` limpios.
- [ ] **T3. Confirmación en el Workspace.** RF-003, RNF-004
- Hecho cuando: `withdrawnPublicTeams` y la confirmación de `saveLineup` siguen el plan §2; textos ES/EN; `cd frontend && pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios, tras ver fallar primero los tests nuevos.
- [ ] **T4. E2E, documentación y validación.** RF-003, RNF-004
- Hecho cuando: `e2e/lineup-publication.spec.ts` pasa con axe sin violaciones en ambos temas a 1440 y 390 px; README, AGENTS, manual y MEMORY actualizados; `pnpm run build`, `pnpm run typecheck:e2e` y la suite backend completa con BD pasan; PR de implementación con la CI en verde.
