# Tareas — Spec 044: Formaciones por modalidad (F12)

Estado: aprobado por el usuario el 2026-11-24 («Apruebo el plan y las tareas. Empieza por T1»).

## Bloque A — backend y migración (PR de implementación 1)

- [ ] **T1. Catálogo por modalidad y migración 066.** RF-001, RF-011, RNF-002
- Hecho cuando: `rule_contract.py` tiene las 13 formaciones, `FORMATIONS_BY_GAME_FORMAT`, `formation_game_format` y `starters_for_game_format`; existe la 066; `docs/contrato-reglas.md` §3–§5 están actualizados; `pytest -q tests/test_rule_contract.py tests/test_seed_demo.py` y `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_066.py tests/test_migration_021.py` pasan, tras verlos fallar primero.
- [ ] **T2. Guardar y publicar por modalidad.** RF-002, RF-003, RF-009, RF-010
- Hecho cuando: el guardado y la publicación validan la modalidad y los titulares según el plan §4; `RUN_DATABASE_TESTS=1 pytest -q tests/test_lineup_game_format.py` y los tests existentes de alineaciones y formaciones pasan, tras verlos fallar primero.
- [ ] **T3. Cambio de formato y estadísticas.** RF-004, RF-008
- Hecho cuando: el cambio de formato compara modalidades; los tests de portería imbatida en 5v5/7v7/9v9 pasan; suite backend completa con `RUN_DATABASE_TESTS=1`, `ruff check .`, `bandit -r app -ll` y `compileall` limpios; PR del bloque A con la CI en verde.

## Bloque B — frontend, E2E y documentación (PR de implementación 2)

- [ ] **T4. Catálogo y rejilla del frontend.** RF-001, RF-006
- Hecho cuando: `formations.ts` y `publicLineup.ts` siguen el plan §2–§3; `formations.test.ts` y `public-lineup.test.ts` pasan, tras verlos fallar primero; `pnpm test`, `pnpm run typecheck` y `pnpm run lint` limpios.
- [ ] **T5. Selector por modalidad en la operación.** RF-002, RF-006
- Hecho cuando: el selector solo ofrece la modalidad del partido, la formación ajena aparece deshabilitada con aviso y la precarga de la 028 funciona con 5v5; tests de componente y composable pasan, tras verlos fallar primero.
- [ ] **T6. Textos ES/EN.** RF-007, RNF-003
- Hecho cuando: `format.context` y `rules.gameFormatHint` están actualizados, y los avisos y los códigos 409 tienen texto en ES y en EN; el test de paridad de claves pasa.
- [ ] **T7. E2E, documentación y validación.** RF-006, RNF-004, RNF-005
- Hecho cuando: `e2e/formations-by-format.spec.ts` pasa con axe sin violaciones en ambos temas, a 1440 y 390 px; README (procedimiento de la 066), AGENTS, manual, informe (F12 implementada) y MEMORY están actualizados; `pnpm run build` y la suite completa pasan; PR del bloque B con la CI en verde.
