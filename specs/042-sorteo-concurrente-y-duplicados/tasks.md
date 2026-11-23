# Tareas — Spec 042: Sorteo concurrente y duplicados en calendarios generados (F11)

Estado: borrador, pendiente de aprobación. Este PR documental y un PR de implementación (T1–T6).

- [ ] **T1. Migración 065.** RF-007, RF-008, RNF-003
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_065.py` en rojo y luego verde: índice único parcial presente en volumen limpio 001→065 y en salto 064→065 con partidos existentes; reaplicación inocua; mismo código en otra fase u otra versión y partidos manuales sin código aceptados; con duplicados, la migración aborta con la cantidad y los `stage_id` en el mensaje, sin índice y sin cambiar filas; `sh -n infra/postgres/migrate.sh`.

- [ ] **T2. Concurrencia real.** RF-001–RF-005, RF-007, RF-010, RNF-001, RNF-002
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_concurrency_042.py` en verde con la barrera de §5 del plan y todos sus casos. Si algún caso reproduce un duplicado, primero queda en rojo y se corrige el bloqueo que falte en esta tarea, anotándolo aquí.

- [ ] **T3. Comprobación pura.** RF-006
- Hecho cuando: `cd backend && pytest -q tests/test_schedule_integrity.py` en rojo y luego verde: código repetido, pareja por encima del máximo (una y dos vueltas, no orientada, por grupo), parejas anteriores sumadas, huecos sin equipo ignorados, eliminatorias solo con códigos y calendarios reales de los generadores actuales aceptados para varias semillas.

- [ ] **T4. Integración en liga, grupos y eliminatorias.** RF-006, RF-009
- Hecho cuando: tests nuevos en `test_tournament_scheduling.py` en rojo y luego verde: un generador que devuelve un código o una pareja de más produce 409 sin filas nuevas y sin borrar el calendario anterior en un reemplazo; los sorteos normales mantienen códigos, respuestas y resultado por semilla; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_tournament_scheduling.py tests/test_concurrency_006.py`.

- [ ] **T5. Integración en Swiss.** RF-006, RF-009
- Hecho cuando: tests nuevos en `test_swiss_transaction.py` en rojo y luego verde: una pareja que repite una ronda anterior y un `IntegrityError` de escritura producen 409 sin filas nuevas ni modificadas; rondas válidas sin cambios; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_swiss_transaction.py tests/test_swiss_budget.py`.

- [ ] **T6. Documentación y validación.** RF-011, criterios de finalización
- Hecho cuando: README (runbook de la 065), AGENTS, `docs/manual-usuario.md`, `docs/informe-funciones-adicionales.md` y MEMORY sin H7 como riesgo aceptado y con la protección descrita; `cd backend && RUN_DATABASE_TESTS=1 pytest -q`, `python -m compileall -q app`, `ruff check .` y `bandit -r app -ll` limpios; cinco jobs de CI en verde en el PR; cada RF con su evidencia anotada aquí.
