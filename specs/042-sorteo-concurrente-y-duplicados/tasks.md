# Tareas — Spec 042: Sorteo concurrente y duplicados en calendarios generados (F11)

Estado: aprobadas por el usuario el 2026-11-23. Este PR documental (#110) y un PR de implementación (#111, T1–T6). Spec aceptada por el usuario el 2026-11-23 («acepto la 042»), con la CI de #111 en verde (7/7) y Devin Review sin hallazgos.

- [x] **T1. Migración 065.** RF-007, RF-008, RNF-003
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_065.py` en rojo y luego verde: índice único parcial presente en volumen limpio 001→065 y en salto 064→065 con partidos existentes; reaplicación inocua; mismo código en otra fase u otra versión y partidos manuales sin código aceptados; con duplicados, la migración aborta con la cantidad y los `stage_id` en el mensaje, sin índice y sin cambiar filas; `sh -n infra/postgres/migrate.sh`.
- Evidencia: 4 fallos en rojo sin la migración; 5 passed con ella; `sh -n` limpio.

- [x] **T2. Concurrencia real.** RF-001–RF-005, RF-007, RF-010, RNF-001, RNF-002
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_concurrency_042.py` en verde con la barrera de §5 del plan y todos sus casos. Si algún caso reproduce un duplicado, primero queda en rojo y se corrige el bloqueo que falte en esta tarea, anotándolo aquí.
- Evidencia: 11 passed. Ningún caso reprodujo un duplicado: el bloqueo fase → versión ya serializa los sorteos (Swiss en frío incluido: el segundo recibe 409 de estado cambiado). La inserción directa sin bloqueo queda frenada por el índice de la 065.

- [x] **T3. Comprobación pura.** RF-006
- Hecho cuando: `cd backend && pytest -q tests/test_schedule_integrity.py` en rojo y luego verde: código repetido, pareja por encima del máximo (una y dos vueltas, no orientada, por grupo), parejas anteriores sumadas, huecos sin equipo ignorados, eliminatorias solo con códigos y calendarios reales de los generadores actuales aceptados para varias semillas.
- Evidencia: error de importación en rojo; 88 passed con `schedule_integrity.py`.

- [x] **T4. Integración en liga, grupos y eliminatorias.** RF-006, RF-009
- Hecho cuando: tests nuevos en `test_tournament_scheduling.py` en rojo y luego verde: un generador que devuelve un código o una pareja de más produce 409 sin filas nuevas y sin borrar el calendario anterior en un reemplazo; los sorteos normales mantienen códigos, respuestas y resultado por semilla; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_tournament_scheduling.py tests/test_concurrency_006.py`.
- Evidencia: 5 fallos en rojo sin la integración; con ella, 128 passed junto con `test_concurrency_006.py` y `test_schedule_integrity.py`. La comprobación también cubre `_persist_bracket_schedule` cuando lo usa el avance entre fases.

- [x] **T5. Integración en Swiss.** RF-006, RF-009
- Hecho cuando: tests nuevos en `test_swiss_transaction.py` en rojo y luego verde: una pareja que repite una ronda anterior y un `IntegrityError` de escritura producen 409 sin filas nuevas ni modificadas; rondas válidas sin cambios; `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_swiss_transaction.py tests/test_swiss_budget.py`.
- Evidencia: 3 fallos en rojo sin la integración; con ella, 48 passed en `test_swiss_transaction.py` y `test_swiss_budget.py`, 37 junto con `test_concurrency_042.py` y 155 en las regresiones de liga, grupos, eliminatorias y avance entre fases. Las parejas anteriores se leen bajo el bloqueo de fase y versión. Se corrigió un doble de prueba cuyo historial repetía una pareja del emparejamiento simulado. Reemplazos Swiss simultáneos: el segundo recibe 409 (aclaración de DA-4, «Dejar swiss como está»).

- [x] **T6. Documentación y validación.** RF-011, criterios de finalización
- Hecho cuando: README (runbook de la 065), AGENTS, `docs/manual-usuario.md`, `docs/informe-funciones-adicionales.md` y MEMORY sin H7 como riesgo aceptado y con la protección descrita; `cd backend && RUN_DATABASE_TESTS=1 pytest -q`, `python -m compileall -q app`, `ruff check .` y `bandit -r app -ll` limpios; cinco jobs de CI en verde en el PR; cada RF con su evidencia anotada aquí.
- Evidencia: H7 retirado de README y AGENTS; runbook de la 065 en README; manual (calendario) e informe actualizados; MEMORY en validación. Backend completo con `RUN_DATABASE_TESTS=1`: 4498 passed, 4 skipped y 17 fallos de entorno (Redis apagado en los tests multiproceso de tiempo real); con Redis, esos dos archivos pasan 129/129. `compileall`, `ruff check .`, `bandit -r app -ll` y `sh -n infra/postgres/migrate.sh` limpios. Sin cambios de frontend.
- RF: 001–005 y 010 en `test_concurrency_042.py`; 006 en `test_schedule_integrity.py`, `test_tournament_scheduling.py` y `test_swiss_transaction.py`; 007–008 en `test_migration_065.py`; 009 en las regresiones de sorteo y Swiss; 011 en esta tarea.
