# Tareas 021 — Formaciones gráficas en la consulta pública

- [x] **T1. Migración 028: `segment_number` en la vista pública de alineaciones.** RF-007, RF-013, RF-015
  - Hecho cuando: existe `infra/postgres/migrations/028_public_lineup_segment_number.sql` que recrea `v_public_match_lineups_unpublished` añadiendo `segment_number` (join con `match_segments`) en `tactical_rows` y `NULL::INT` en `classic_rows`, conserva `security_barrier`, grants y el orden `published_at DESC, segment_number DESC, id DESC`; `sh -n infra/postgres/migrate.sh` pasa.

- [x] **T2. Backend: `segment_number` en `PublicTeamLineupResponse` y en el router.** RF-007, RF-013, RF-015
  - Hecho cuando: `PublicTeamLineupResponse` declara `segment_number: int | None = None`; la consulta a `v_public_match_lineups` selecciona `segment_number` y el ensamblado lo copia por equipo; `cd backend && python -m compileall -q app` y `cd backend && pytest -q` pasan.

- [x] **T3. Frontend: tipo `PublicTeamLineup.segment_number`.** RF-007, RF-015
  - Hecho cuando: `frontend/app/utils/publicTournament.ts` añade `segment_number: number | null` a `PublicTeamLineup` y a `TeamLineup` del modal; `cd frontend && pnpm run typecheck` pasa.

- [x] **T4. Funciones puras de formación pública (`publicLineup.ts`) + tests.** RF-002, RF-004, RF-006, RF-009, RF-011
  - Hecho cuando: existe `frontend/app/utils/publicLineup.ts` con `isTacticalFormationValid`, `slotLine`, `textualFormationLines` y `playerInitials`; existe `frontend/tests/public-lineup.test.ts` cubriendo los casos de RF-006 y los casos límite 1–12; `cd frontend && pnpm test` pasa.

- [x] **T5. Componente `TeamPitch.vue` (media cancha de un equipo).** RF-002, RF-003, RF-011
  - Hecho cuando: existe `frontend/app/components/public/TeamPitch.vue` que posiciona titulares según `FORMATIONS_GRID`, muestra código de formación, dorsal, posición y foto o iniciales, y suplentes en panel diferenciado; `cd frontend && pnpm run typecheck && pnpm run build` pasan.

- [x] **T6. Reescritura de `PublicLineupModal.vue` para renderizado independiente.** RF-001, RF-003, RF-007, RF-008, RF-009, RF-011, RF-013
  - Hecho cuando: cada equipo se renderiza de forma independiente (campo si formación válida, lista si no, omisión sin estado vacío); se muestran etiquetas «formación táctica» / «planilla del partido», el número de segmento cuando exista, el equivalente textual navegable con teclado y las iniciales sin foto rota; el foco se restaura al cerrar; `cd frontend && pnpm run typecheck && pnpm run build` pasan.

- [x] **T7. Claves de i18n para las etiquetas nuevas (es y en).** RF-001, RF-009, RNF-002
  - Hecho cuando: existen las claves para «formación táctica», «planilla del partido», «segmento {n}», las cuatro líneas (portero, defensa, mediocampo, delantera) y el equivalente textual; `cd frontend && pnpm run build` pasa.

- [x] **T8. Test de migración 028 (opt-in PostgreSQL).** RF-007, RF-013, RF-015, RNF-003
  - Hecho cuando: existe `backend/tests/test_migration_028.py` que construye la cadena limpia 001→028 y el salto 027→028, verifica la columna `segment_number` en `v_public_match_lineups`, su nulidad en planilla y su valor en formación, y los grants sin cambios; documentado como opt-in con `RUN_DATABASE_TESTS=1` y `DATABASE_ADMIN_URL`.

- [x] **T9. Documentación: lista cerrada de campos públicos y matriz de acceso.** RF-015, RF-020 (spec 020), RNF-006
  - Hecho cuando: la documentación del producto y la guía de agentes reflejan `segment_number` en la lista cerrada de campos públicos de `PublicTeamLineupResponse` y la matriz de acceso actualizada.

- [x] **T10. Validación final y MEMORY.md.** RNF-005, RNF-007
  - Hecho cuando: se ejecutan `cd backend && pytest -q`, `cd backend && python -m compileall -q app`, `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck`, `cd frontend && pnpm run build`, `sh -n infra/postgres/migrate.sh` y se declaran los no ejecutados; `MEMORY.md` actualizado con la spec 021 en fase de implementación/validación.