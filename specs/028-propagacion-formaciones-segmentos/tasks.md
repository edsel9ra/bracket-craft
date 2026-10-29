- [x] **T1. Crear la utilidad pura `deriveLineupSource`.** RF-001, RF-002, RF-006, RF-009, RF-010, RF-014
  - Hecho cuando: existe `frontend/app/utils/lineupSource.ts` exportando `deriveLineupSource` y los tipos `LineupSource`, `LineupSourceByTeam`, sin leer reloj/red/storage (verificable con barrido de patrones como en `match-segments.test.ts`).

- [x] **T2. Añadir pruebas unitarias de la derivación.** RF-001, RF-002, RF-006, RF-009, RF-010, RF-011, RF-014, CL-001..CL-012
  - Hecho cuando: `frontend/tests/lineup-source.test.ts` cubre fuente por equipo, independencia, segmento con formación persistida, sin fuente, parcial, sin snapshots, jugador retirado, pureza y determinismo; `cd frontend && pnpm test` pasa.

- [x] **T3. Consumir la fuente en `syncTacticalEditor`.** RF-001, RF-003, RF-004, RF-005, RF-008
  - Hecho cuando: en `frontend/app/pages/workspace/matches/[id].vue`, `syncTacticalEditor` aplica la formación y las asignaciones de la fuente para los equipos sin formación persistida en el segmento seleccionado, inicializando los rosters no presentes en la fuente con rol vacío y sin posición; la formación persistida prevalece cuando existe (RF-002/RF-010).

- [x] **T4. Respetar la independencia por equipo y el estado de publicación.** RF-007, CL-001, CL-007
  - Hecho cuando: un segmento con formación solo para un equipo precarga únicamente ese equipo; `is_public`/`published_at` no se copian (el segmento precargado nace privado); `toggleLineupPublication` sigue operando solo sobre el segmento seleccionado.

- [x] **T5. Omitir la precarga en terminales y no publicados.** RF-012, RF-013
  - Hecho cuando: en partido terminal (`finished`, `cancelled`, `administrative_resolution`, `suspended`) o versión no publicada no se aplica precarga; en borrador se aplica la misma regla que en publicada.

- [x] **T6. Verificar la regresión del flujo existente.** RF-008, CL-003, CL-004, CL-005, CL-006
  - Hecho cuando: cambiar de segmento descarta ediciones no guardadas y recarga desde la fuente o la formación persistida; guardar persiste solo en el segmento destino; un único segmento no cambia de comportamiento; `cd frontend && pnpm test && pnpm run typecheck && pnpm run build` pasan.