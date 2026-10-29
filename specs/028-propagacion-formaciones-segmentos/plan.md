# Plan 028 — Propagación de formaciones entre segmentos

## Archivos y responsabilidades

- `frontend/app/utils/lineupSource.ts` (nuevo): función pura `deriveLineupSource` y tipos asociados. Deriva, por equipo, la fuente de precarga (segmento de menor número con formación persistida para ese equipo) y construye la formación + asignaciones de rol/posición a precargar. No lee reloj, red ni almacenamiento.
- `frontend/app/pages/workspace/matches/[id].vue`: consume `deriveLineupSource` en `syncTacticalEditor` para precargar la formación y las posiciones de los equipos que no tienen formación persistida en el segmento seleccionado. Sin cambios en `applyOperation` más allá de la llamada ya existente a `syncTacticalEditor`.
- `frontend/tests/lineup-source.test.ts` (nuevo): pruebas unitarias de la función pura con `node --test`.

No hay cambios de backend, migraciones ni endpoints.

## Funciones puras

- `deriveLineupSource(tacticalLineups, rosters, selectedSegmentId): LineupSourceByTeam`
  - Entrada: lista de `TacticalLineupRow`-like (segment_id, segment_number, team_id, formation_code, player_id, is_starter, position_slot), lista de `RosterEntry`-like (roster_id, player_id, team_id) y el `segment_id` seleccionado.
  - Salida: mapa `team_id -> LineupSource | null`.
    - `null` si el segmento seleccionado ya tiene formación persistida para ese equipo (RF-002, RF-010) o no existe ninguna fuente (RF-006).
    - `LineupSource`: `{ source_segment_id, formation_code, roles: Record<roster_id, LineupRole | ''>, positions: Record<roster_id, string | null> }`.
  - Algoritmo:
    1. Determinar el conjunto de equipos (unión de `team_id` en rosters y en tactical_lineups).
    2. Para cada equipo:
       a. Si existe al menos una fila de `tactical_lineups` con `segment_id === selectedSegmentId` y ese `team_id`, devolver `null` (hay formación persistida; RF-002/RF-010).
       b. Filtrar las filas del equipo. Si no hay ninguna, devolver `null` (RF-006).
       c. Elegir la fuente: fila(s) del segmento con menor `segment_number` entre los que tienen formación persistida para ese equipo. Como `tactical_lineups` agrupa por segmento y el `formation_code` se repite por fila, se toman todas las filas de ese segmento y equipo.
       d. `formation_code`: el `formation_code` de la fuente (primera fila no vacía; `''` si no hay).
       e. Inicializar `roles` y `positions` con `''` / `null` para todos los rosters del equipo.
       f. Por cada fila de la fuente con `player_id` no nulo: resolver `roster_id` vía rosters (`player_id` + `team_id`); si existe, asignar rol (`starter` si `is_starter`, si no `substitute`) y posición (`position_slot` si no nulo).
       g. Devolver `{ source_segment_id, formation_code, roles, positions }`.
  - No incluye `is_public`/`published_at` ni identificadores de la fuente en la salida (RF CL campos excluidos).

- `hasPersistedLineupForTeam` no se expone por separado; queda cubierto por el `null` del resultado (RF-002).

## Interfaz

- Sin cambios de API, endpoints ni esquema (RNF-001, RNF-002, RNF-003).
- La pantalla consume `deriveLineupSource` dentro de `syncTacticalEditor`, usando `operation.value.tactical_lineups` y `operation.value.rosters`, sin consultas adicionales.

## Decisiones

1. **Función por equipo en un solo llamado (mapa) en lugar de una función por equipo.**
   - Alternativa descartada: `deriveLineupSourceForTeam(teamId, ...)`. Se descarta porque la pantalla itera equipos y la fuente global (menor segment_number con formación para cualquier equipo) se deriva del mismo conjunto; un único llamado evita recomputar y simplifica las pruebas. La independencia por equipo se mantiene en la lógica interna.
2. **Devolver `null` por equipo cuando el segmento seleccionado ya tiene formación persistida.**
   - Alternativa descartada: devolver la fuente igualmente y que la pantalla decida. Se descarta porque RF-002/RF-010 exigen que la formación persistida prevalezca sin ambigüedad; codificarlo en la función pura hace el comportamiento testeable y evita ramas en la vista.
3. **Inicializar rosters no presentes en la fuente con rol vacío y sin posición.**
   - Alternativa descartada: omitirlos del mapa. Se descarta porque `syncTacticalEditor` ya inicializa todos los rosters con `''`; mantener la inicialización en la función permite que la pantalla aplique la fuente de forma uniforme (asignaciones solo donde haya snapshot) y cubre CL-011/CL-008.
4. **No propagar `is_public`/`published_at`.**
   - Alternativa descartada: copiar el estado de publicación. Se descarta por CL-001 y la sección «Campos copiados y excluidos»: el segmento precargado nace privado.
5. **Omisión en terminal/no publicado se decide en la pantalla, no en la función.**
   - Alternativa descartada: pasar un flag `enabled` a la función. Se descarta para mantener la función pura centrada en la derivación (RNF-004) y alinearla con el resto de utilidades del proyecto, que no conocen el estado del partido.

## Estrategia de tests

- `frontend/tests/lineup-source.test.ts` con `node --test`: cubre CL-001..CL-012 relevantes: fuente por equipo, independencia, segmento con formación persistida (RF-002), sin fuente (RF-006), segmento parcial (CL-007), fuente sin snapshots (CL-008), fuente anterior (CL-009), jugador retirado (CL-011), precarga reciente (CL-012) y pureza/determinismo (sin reloj/red/storage).
- `pnpm test`, `pnpm run typecheck`, `pnpm run build` en verde.

## Qué RF cubre cada parte

- `deriveLineupSource` (utils): RF-001, RF-002, RF-006, RF-009, RF-010, RF-011 (derivación), RF-014, CL-001..CL-012.
- `syncTacticalEditor` (pantalla): RF-001, RF-003, RF-004, RF-005, RF-007, RF-008, RF-012, RF-013.

## Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|----------------------|--------|----------------|
| §2.1 Aislamiento por tenant (RLS) | No | Sin cambios de base de datos ni consultas nuevas; se reutilizan datos ya cargados con RLS. |
| §2.3 Lo publicado es inmutable | Sí | No se modifica ninguna versión publicada; la precarga es solo en memoria y se persiste únicamente al guardar en el segmento destino (RF-004, RF-005). |
| §2.5 Lo público es proyección mínima | Sí | No se exponen campos nuevos ni se cambia la publicación; `is_public` no se copia (CL-001). |
| §2.8 Nada sin verificación | Sí | Pruebas unitarias de la función pura + `pnpm test`, `typecheck`, `build`. |
| §3.3 Frontend: llamadas HTTP por `useApi.ts` | Sí | No se añaden llamadas HTTP. |
| §4 (todos) Pasa CI correspondiente | Sí | Job `frontend`: `pnpm test`, `pnpm run typecheck`, `pnpm run build`. |
| §4 (frontend) `pnpm test`, `typecheck`, `build` | Sí | Se ejecutan y deben pasar. |
| §4 (todos) Sin secretos/datos personales | Sí | No se tocan datos personales; las formaciones ya son datos operativos. |
| §4 (todos) Documentación actualizada si cambia comportamiento | Sí | Spec/plan/tasks documentan el cambio; no requiere README/AGENTS salvo aprobación del reviewer. |