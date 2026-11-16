# Tareas — Spec 037: Cronología pública del partido

Estado: aprobadas por el usuario el 2026-11-15 («Apruebo plan y tareas»). Un solo PR por bloque: A (T1–T4 backend) y B (T5–T10 frontend, documentación y cierre).

- [x] **T1. Migración 060: `segment_id` en `v_public_match_events`.** RF-005, RF-009, RF-016
- Hecho cuando: `test_migration_060.py` en rojo y luego verde con `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_060.py`; `sh -n infra/postgres/migrate.sh`; cadena limpia 001→060 y salto 059→060 con checksums estables.
- Evidencia: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_060.py tests/test_migration_030.py` → 11 passed (PostgreSQL 17); `infra/scripts/test_migrate_target.sh` OK; `sh -n infra/postgres/migrate.sh` OK; `pytest -q` → 2933 passed, 1188 skipped; `ruff check .` limpio.

- [x] **T2. Funciones puras de la cronología.** RF-002, RF-003, RF-005–RF-012
- Hecho cuando: `cd backend && pytest -q tests/test_public_timeline.py` verde tras confirmarlo en rojo, cubriendo CL-1–CL-14 aplicables.
- Evidencia: `pytest -q tests/test_public_timeline.py` → 34 passed (disponibilidad, tipos, orden estable, roja, autogol, sustitución, huérfanos, marcador con prórroga/penales); `ruff check` limpio.

- [x] **T3. Modelos públicos y lista cerrada.** RF-007, RF-015
- Hecho cuando: `pytest -q tests/test_public_field_allowlist.py` falla ante una clave extra y pasa con los tres modelos nuevos.
- Evidencia: `pytest -q tests/test_public_field_allowlist.py` → 5 passed (tres modelos con `extra="forbid"`, sin asistencia/dorsal/foto/IDs internos; claves extra rechazadas).

- [x] **T4. Endpoint `GET /tournaments/public/{tournament_id}/matches/{match_id}/timeline`.** RF-001, RF-004, RF-013, RF-016
- Hecho cuando: `RUN_DATABASE_TESTS=1 pytest -q tests/test_public_timeline_endpoint.py tests/test_public_access_matrix.py` verde (dos organizaciones, rectificación, anulados, 404 indistinguible); `pytest -q`, `ruff check .` y `bandit -q -r app -ll` verdes.
- Evidencia (2026-11-15): `test_public_timeline_endpoint.py` 3 passed (dos organizaciones con lista cerrada y sin mezcla; versión rectificada vigente sin anulados; `live` → `pending`, acta confirmada sin hechos → vacío con segmentos 1–2; cancelado, inexistente, de otro torneo u otra organización → 404 indistinguible) y `test_public_access_matrix.py` con la ruta nueva en los tres grupos de 404; suite con PostgreSQL 17 y Redis 4154 passed (el único fallo, el recuento de rutas, se corrigió a 33 operaciones); `pytest -q` 2969 passed/1190 skipped, `ruff check .` y `bandit -q -r app -ll` limpios.

- [x] **T5. Utilidades frontend `utils/publicTimeline.ts`.** RF-008, RF-009, RF-014
- Hecho cuando: `cd frontend && pnpm test` incluye `public-timeline.test.ts` (minuto, separadores, clave por tipo/roja, decisión de recarga) en verde.
- Evidencia (2026-11-15): `public-timeline.test.ts` 9 passed (apertura solo en `finished`, minuto `45+2'`, claves por tipo y roja sin inferir, nombre y apellido, lado, separadores solo con más de un segmento, recarga por estado/marcador/penales/rectificación); `pnpm test` 1095 passed/0 failed; eslint limpio.

- [x] **T6. Componente `PublicMatchTimeline.vue` e i18n ES/EN.** RF-007, RF-008, RF-012, RNF-002
- Hecho cuando: pruebas del componente (estados, nombres accesibles, foco, ambos idiomas) verdes; `pnpm run lint` y `pnpm run typecheck` verdes; `design-scales.test.ts` sin excepciones nuevas.
- Evidencia (2026-11-15): `PublicMatchTimeline.vue` (diálogo modal nativo, cierre con foco y devolución, `role=status`/`alert`, estados de carga/error/pendiente/sin juego/vacío/descuadre, iconos `aria-hidden`, sin dorsal/foto/asistencia) y 19 claves ES/EN; `public-timeline.test.ts` 13 passed y `theme-surfaces.test.ts` cubre su backdrop claro; `pnpm test` 1099 passed/0 failed; `pnpm run lint` y `pnpm run typecheck` limpios; `design-scales.test.ts` sin excepciones nuevas.

- [x] **T7. Integración en `/tournaments/{id}` y recarga.** RF-001, RF-002, RF-013, RF-014
- Hecho cuando: pruebas de la página verifican el disparador solo en `finished`, la carga vía `useApi` y la recarga del diálogo abierto al cambiar `status`, marcador o `rectified_at`; `pnpm test` y `pnpm run build` verdes.
- Evidencia (2026-11-15): `[id].vue` añade el disparador junto a cada «Ver formación» de las tarjetas (no en la llave, que no tiene ese botón propio en la página), solo con `canOpenTimeline`; carga bajo demanda con `request` de `useApi`, generación para descartar respuestas tardías y reintento; un `watch` del partido abierto recarga con `shouldReloadTimeline` sobre el refresco público existente, sin evento nuevo. `public-timeline.test.ts` 16 passed; `pnpm test` 1102 passed/0 failed; lint, typecheck y `pnpm run build` limpios.

- [x] **T8. E2E público de la cronología.** RNF-002, CL-9, CL-13
- Hecho cuando: `pnpm run typecheck:e2e` verde y `public-polish.spec.ts` ejecutado con el diálogo a 1440/390 px en ambos temas, sin desbordamiento (en CI o en contenedor Playwright 1.65).
- Evidencia (2026-11-15): `pnpm run typecheck:e2e` y eslint limpios; `public-polish.spec.ts` ejecutado en el contenedor `mcr.microsoft.com/playwright:v1.65.0-noble` contra `pnpm run build` + un stub local que solo sirve el listado SSR (el resto lo intercepta el contrato ficticio): 27 passed, incluidas las 6 de la cronología (1440/390/800 px × oscuro/claro: orden, `45+2'`, separadores, roja por doble amarilla, sale/entra con nombres largos, sin `#`, diálogo dentro del viewport, sin scroll horizontal, una sola petición `/timeline`, Escape devuelve el foco). En CI queda pendiente su ejecución en el job `e2e`.

- [x] **T9. Documentación: matriz de acceso, AGENTS, manual y 020.** RF-017
- Hecho cuando: README (matriz y runbook 060), `AGENTS.md`, `docs/manual-usuario.md` y la referencia en la spec 020 describen la ruta, la lista cerrada y el cambio no aditivo; pruebas de coherencia documental verdes.
- Evidencia (2026-11-15): README (fila de la matriz, viñeta con la lista cerrada y el cambio no aditivo, verificación y runbook 060), `AGENTS.md` (viñeta F13), `docs/manual-usuario.md` (consulta pública) y `specs/020/spec.md` (ampliación F13). Pruebas de coherencia documental: `test_version_sources.py`/`test_migration_030.py` 25 passed (7 opt-in omitidas) y `pnpm test` 1102 passed/0 failed.

- [ ] **T10. Validación y cierre.** Criterios de finalización 1–8
- Hecho cuando: los cinco jobs de CI pasan en el PR, cada RF/CL tiene evidencia citada en este archivo, la verificación de constitución está confirmada y `MEMORY.md` actualizado; lo no ejecutado se declara.
