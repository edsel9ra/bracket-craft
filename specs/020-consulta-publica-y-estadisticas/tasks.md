# Tareas 020 — Consulta pública: navegación por fases y grupos, y acceso público

Máximo 10 tareas, en orden de dependencia. Cada una se implementa y verifica antes de pasar a la siguiente (Fase 5 del SDD).

- [x] **T1. Funciones puras de navegación pública.** RF-001, RF-002, RF-003, RF-004, RF-008
  - Archivo: `frontend/app/utils/publicTournament.ts`.
  - Añadir `normalizePublicSelection`, `groupsOfStage`, `standingsForGroup`, `matchesForGroup`, `resolveMatchOutcomeLabel`.
  - Hecho cuando: `cd frontend && pnpm test` pasa con los nuevos casos en `frontend/tests/public-navigation.test.ts` (node:test) cubriendo normalización de fase inexistente, grupo inexistente, orden estable de grupos y etiqueta de resolución por texto.

- [x] **T2. Selección de fase y grupo por URL.** RF-002
  - Archivo: `frontend/app/pages/tournaments/[id].vue`.
  - Leer `route.query.stage`/`group`; normalizar al montar con `replace`; cada cambio del visitante apila con `push`; restaurar fase/grupo al recargar.
  - Hecho cuando: `cd frontend && pnpm run typecheck` pasa y la navegación manual (cambio de fase, atrás del navegador, recarga) restaura la misma fase/grupo sin error.

- [x] **T3. Una fase a la vez con grupos independientes.** RF-001, RF-003, RF-004, RF-005, RF-006
  - Archivo: `frontend/app/pages/tournaments/[id].vue` (y `PublicBracket.vue` si aplica).
  - Mostrar solo la fase seleccionada; en fase de grupos, una tabla por grupo con encabezado de grupo; en liga/suiza, una tabla y partidos por jornada/ronda; en eliminatoria, llave por rondas con resultado y ganador, e indicación textual de prórroga/penales/walkover/resolución administrativa.
  - Estado vacío propio si la fase no tiene equipos/partidos/clasificación.
  - Hecho cuando: `cd frontend && pnpm run typecheck && pnpm run build` pasan y la revisión visual confirma tablas por grupo y llave con texto de resolución.

- [x] **T4. Paginación por combinación (fase, grupo).** RF-008, RF-009
  - Archivo: `frontend/app/pages/tournaments/[id].vue`.
  - Mantener un `Map` de offsets e indicadores «hay más» por clave `(stageId, groupId)`; cada combinación carga bajo demanda con sus propios controles; el cierre de un acta (evento en tiempo real) reinicia la paginación de la combinación activa a la primera página conservando fase/grupo.
  - Hecho cuando: `cd frontend && pnpm test && pnpm run typecheck` pasan y un torneo con >50 filas en dos fases permite alcanzar todas las filas de la segunda fase sin pulsar controles de la primera.

- [x] **T5. Tabla de posiciones completa.** RF-011, RF-012
  - Archivo: `frontend/app/pages/tournaments/[id].vue`.
  - Mostrar posición, equipo con escudo, jugados, ganados, empatados, perdidos, GF, GC, DG, puntos y puntos de juego limpio; verificar en cliente que jugados = G+E+P y DG = GF−GC; filas en orden de posición.
  - Hecho cuando: `cd frontend && pnpm run typecheck && pnpm run build` pasan y la tabla muestra las columnas nuevas en español e inglés.

- [x] **T6. Torneos sin fases (presentación heredada).** RF-010
  - Archivo: `frontend/app/pages/tournaments/[id].vue`.
  - Conservar la presentación actual cuando no hay fases publicadas, sin errores.
  - Hecho cuando: `cd frontend && pnpm test && pnpm run build` pasan y un torneo sin fases se muestra como antes.

- [x] **T7. Verificación automática de lista cerrada de campos públicos.** RF-015, RF-016
  - Archivo: `backend/tests/test_public_field_allowlist.py` (nuevo).
  - Introspeccionar los modelos Pydantic públicos y verificar que el conjunto de campos coincide exactamente con el anexo del plan; fallar si aparece un campo fuera de la lista o falta uno declarado; comprobar ausencia de campos sensibles.
  - Hecho cuando: `cd backend && pytest -q tests/test_public_field_allowlist.py` pasa.

- [x] **T8. Matriz de acceso y aislamiento entre organizaciones.** RF-013, RF-014, RF-017, RF-019
  - Archivos: `backend/tests/test_public_access_matrix.py` (nuevo).
  - Verificar lecturas anónimas (200/404), torneo en borrador/sin versión/org inactiva → 404 indistinguible, aislamiento entre dos tenants, y query params fuera de rango → 422 con `detail` en lista y sin `code`.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_public_access_matrix.py` pasa (o se declara no ejecutado si no hay PostgreSQL).

- [x] **T9. Documentación de la matriz de acceso.** RF-020, RNF-008
  - Archivos: `README.md`, `AGENTS.md`.
  - Añadir la matriz (qué es público, qué exige sesión, qué no sale nunca) y la nota de que esta spec no añade campos públicos.
  - Hecho cuando: la documentación refleja la matriz y `sh -n`/config no aplican (solo docs); revisión manual.

- [x] **T10. Validación final y cierre.** RNF-007
  - Comandos: `cd backend && pytest -q && python -m compileall -q app`; `cd frontend && pnpm test && pnpm run typecheck && pnpm run build`; actualizar `MEMORY.md` (spec 020 → implementada tras aprobación).
  - Hecho cuando: todos los comandos anteriores pasan y `MEMORY.md` refleja el estado.