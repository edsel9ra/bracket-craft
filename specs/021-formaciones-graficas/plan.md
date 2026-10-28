# Plan 021 — Formaciones gráficas en la consulta pública

## Archivos y responsabilidades

### Base de datos
- `infra/postgres/migrations/028_public_lineup_segment_number.sql` (nueva): recrea `public.v_public_match_lineups_unpublished` añadiendo `segment_number` (entero, nullable) a `tactical_rows` (join con `match_segments`) y `NULL::INT` a `classic_rows`. La vista publicada `v_public_match_lineups` hereda la columna vía `raw.*`. Conserva `security_barrier`, `REVOKE`/`GRANT` y el orden `published_at DESC, segment_number DESC, id DESC`. Sin backfill ni cambios en `init/01`.
- `infra/postgres/init/02_public_projections.sql`: sin cambios (la vista de alineaciones no se define en init).

### Backend
- `backend/app/modules/tournaments/schemas.py`: `PublicTeamLineupResponse` añade `segment_number: int | None = None` (aditivo).
- `backend/app/modules/tournaments/router.py`: la consulta a `v_public_match_lineups` incluye `segment_number`; el ensamblado por equipo lo copia del primer renglón (igual que `formation_code`).

### Frontend
- `frontend/app/utils/publicTournament.ts`: `PublicTeamLineup` añade `segment_number: number | null`.
- `frontend/app/utils/publicLineup.ts` (nuevo, funciones puras): validación de formación táctica por equipo, clasificación de slot en línea (portero/defensa/mediocampo/delantera) y equivalente textual.
- `frontend/app/components/public/TeamPitch.vue` (nuevo): campo de un solo equipo con titulares posicionados, código de formación, foto o iniciales, dorsal y posición; suplentes fuera.
- `frontend/app/components/public/PublicLineupModal.vue`: renderizado independiente por equipo (campo o lista), etiquetas «formación táctica» / «planilla del partido», número de segmento, equivalente textual navegable con teclado.
- `frontend/app/i18n/locales/{es,en}.json` (o equivalente): claves nuevas para etiquetas y líneas.

### Tests
- `backend/tests/test_migration_028.py` (nuevo, opt-in PostgreSQL): cadena limpia 001→028 y salto 027→028; columna presente, nula en planilla, con valor en formación.
- `frontend/tests/public-lineup.test.ts` (nuevo): validación, clasificación de línea, equivalente textual, casos límite RF-006.
- `backend/tests/test_public_player_views.py`: sin cambios de aserción; sigue pasando (segment_number es dato técnico, no personal).

## Funciones puras

Toda función que dependa del tiempo recibe la fecha como parámetro; aquí no hay fechas. Funciones en `frontend/app/utils/publicLineup.ts`:

- `isTacticalFormationValid(team: PublicTeamLineup): boolean` — aplica RF-006: `formation_code` debe ser uno de los cuatro del catálogo; `starters.length > 0`; `starters.length === formationSlots(code).length`; todo `position_slot` no nulo, perteneciente a los slots del código; si `formation_code` es nulo no puede haber `position_slot` no nulo. Devuelve `false` en cualquier otro caso (incluido cero titulares con código no nulo).
- `formationSlots(code): string[]` (reutiliza `frontend/app/constants/formations.ts`).
- `slotLine(formation, slot): 'gk' | 'def' | 'mid' | 'att'` — clasifica por la coordenada `y` del slot en `FORMATIONS_GRID` (≥ 60 → defensa, ≥ 45 → mediocampo, resto → delantera; GK explícito).
- `textualFormationLines(team): { line: string; players: PublicLineupPlayer[] }[]` — agrupa titulares por línea en el orden portero, defensa, mediocampo, delantera, ordenados dentro de cada línea por `x` ascendente. Si no es formación válida, devuelve `[]` (el equivalente textual es la propia lista de planilla).
- `playerInitials(player): string`.

El backend no introduce funciones puras nuevas; la selección de la última formación publicada ya vive en la vista (`published_at DESC, segment_number DESC, id DESC`).

## Algoritmo (pseudocódigo)

```
para cada equipo de la alineación del partido:
  si isTacticalFormationValid(equipo):
     mostrar etiqueta "formación táctica"
     mostrar código de formación
     si segment_number no es nulo: mostrar "segmento {n}"
     dibujar TeamPitch con titulares posicionados (foto o iniciales)
     ofrecer equivalente textual (lista por líneas)
     mostrar suplentes en lista aparte
  si no:
     si equipo tiene titulares o suplentes:
        mostrar etiqueta "planilla del partido"
        mostrar lista de titulares y suplentes sin posiciones
     si no:
        omitir la sección sin estado vacío
```

La decisión es independiente por equipo: la validez de uno no afecta al otro (RF-008).

## Interfaz

### Endpoints y contratos
- Sin endpoints nuevos. `GET /tournaments/public/{id}/matches` (y su paginación) sigue devolviendo `lineup.home`/`lineup.away` con `segment_number` aditivo en `PublicTeamLineupResponse`.
- Cambio de contrato aditivo: `PublicTeamLineupResponse.segment_number: int | None`.

### Pantallas
- `PublicLineupModal.vue`: deja de exigir que ambos equipos tengan formación para dibujar; renderiza por equipo. Mantiene el diálogo modal, el foco restaurado al cerrar y la accesibilidad.
- `TeamPitch.vue`: campo de un solo equipo (media cancha) con jugadores posicionados; suplentes en panel diferenciado.
- El botón «ver alineación» solo aparece si existe `lineup` (sin cambios).

## Decisiones justificadas

1. **Añadir `segment_number` a la vista pública en lugar de resolverlo en el router.**  
   Alternativa descartada: join en el router con `match_segments`. Se descarta porque la vista es la fuente de verdad de lo público y el router ya consume `raw.*`; añadir la columna a la vista mantiene un único punto de definición y evita divergencias entre el listado paginado y otras consumidoras futuras. Coste: una migración nueva (028), aceptable y aditiva.

2. **Renderizado independiente por equipo con un componente de media cancha (`TeamPitch`).**  
   Alternativa descartada: seguir usando `MatchPitch` (campo completo) y ocultar la mitad del rival sin formación. Se descarta porque el campo completo asume dos equipos y forzaría posiciones inventadas o espacios vacíos; el spec exige que un equipo se vea aunque el rival no tenga formación (RF-008) y que no se confunda formación con planilla (RF-001). La media cancha reutiliza `FORMATIONS_GRID` y no duplica lógica de alineaciones.

3. **Validación de formación en el frontend (no en el backend).**  
   Alternativa descartada: añadir un flag `is_tactical_valid` al contrato público. Se descarta porque RF-006 describe inconsistencias de datos ya publicados (titular sin posición, conteo distinto al catálogo) que el backend no valida al publicar; exponer un flag sería un campo nuevo no pedido y ampliaría el contrato. La validación local es determinista a partir de los campos ya públicos. Si en el futuro el backend garantiza la consistencia, el helper deja de ser necesario sin cambio de contrato.

4. **Equivalente textual calculado en el cliente a partir de la misma formación.**  
   Alternativa descartada: un endpoint o campo público adicional con el orden de líneas. Se descarta porque duplicaría datos ya disponibles y violaría la lista cerrada de campos (RF-015 de la spec 020). La clasificación por coordenada `y` es estable y no depende del idioma.

## Estrategia de tests

- **Backend (opt-in PostgreSQL):** `test_migration_028.py` construye la cadena limpia 001→028 y el salto 027→028; verifica que `v_public_match_lineups` expone `segment_number`, que es `NULL` en filas de planilla y con valor en filas de formación publicada, y que los grants no cambian. `test_public_player_views.py` sigue pasando.
- **Frontend (node:test):** `public-lineup.test.ts` cubre `isTacticalFormationValid`, `slotLine`, `textualFormationLines` y `playerInitials` con los casos de RF-006 (titular sin posición, posición fuera del catálogo, `formation_code` nulo con `position_slot` no nulo, conteo distinto, cero titulares, código inválido, formación válida completa). Además casos de RF-005/RF-014: una formación sin publicar no aparece porque el backend ya no la sirve (se verifica por la ausencia en la respuesta, no por el helper).
- **CI:** `cd backend && pytest -q`, `cd backend && python -m compileall -q app`, `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck`, `cd frontend && pnpm run build`, `sh -n infra/postgres/migrate.sh`.

## Qué RF cubre cada parte

| Parte | RF |
|---|---|
| Migración 028 (segment_number en la vista) | RF-007, RF-013, RF-015 |
| `PublicTeamLineupResponse.segment_number` | RF-007, RF-015 |
| Router (SELECT + ensamblado) | RF-007, RF-013, RF-015 |
| `isTacticalFormationValid` | RF-002, RF-004, RF-006 |
| `TeamPitch.vue` | RF-002, RF-011 |
| `PublicLineupModal.vue` (independencia, etiquetas, segmento, texto) | RF-001, RF-003, RF-007, RF-008, RF-009, RF-011, RF-013 |
| Omisión sin estado vacío | RF-005, RF-008, RF-014 |
| Suplentes en lista aparte | RF-003 |
| i18n | RNF-002 |
| No publicar plantilla | RF-012 (ya garantizado por el backend; sin cambio) |
| Catálogo cerrado de cuatro | RF-010 (constante existente; sin cambio) |

## Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant en BD | Sí | La vista mantiene `security_barrier`, los filtros por organización/torneo y los grants existentes; no se añade ninguna tabla ni se relaja RLS. |
| §2.2 Rol de app sin BYPASSRLS | Sí | Sin cambios de privilegios; solo `GRANT SELECT` ya existente sobre la vista publicada. |
| §2.3 Lo publicado es inmutable | Sí | No se editan versiones ni resultados; solo se añade una columna a una vista de lectura. |
| §2.4 Historial append-only | Sí | Migración nueva 028; no se edita la 015 ni ninguna aplicada. |
| §2.5 Lo público es proyección mínima | Sí | Solo se añade `segment_number` (dato técnico, no personal); no se exponen documentos, fechas de nacimiento, edad, motivo de interrupción ni minuto de inicio. La foto sigue dependiendo del consentimiento. |
| §2.6 Sin secretos por defecto fuera de dev | No | Sin variables nuevas. |
| §2.7 Admin global separado y auditado | No | Sin cambios en `/admin`. |
| §2.8 Nada se da por terminado sin verificación | Sí | Se ejecutan los jobs de CI aplicables y se declaran los no ejecutados. |
| §2.9 Código de desarrollo no llega a prod | Sí | La migración y el código se despliegan con el flujo habitual; sin seed nuevo. |
| §3.1 RLS y migraciones | Sí | Migración nueva numerada, verificada sobre volumen limpio y ya migrado. |
| §3.2 Módulos y routers | Sí | Sin módulo nuevo; cambios en el módulo `tournaments` existente. |
| §3.3 Frontend vía useApi | Sí | Sin llamadas HTTP nuevas; se reutiliza la respuesta existente. |
| §3.4 Seguridad y configuración | Sí | Sin dependencias nuevas; sin secretos nuevos. |
| §4 (criterios de cambio) | Sí | Pasa `pytest`, `compileall`, `pnpm test`, `typecheck`, `build` y `sh -n migrate.sh`. Cambio de BD es migración nueva. |
| RNF-001 (solo lectura, aditivo) | Sí | La consulta pública no escribe; `segment_number` es nullable y aditivo; `engine_version` sigue en 2026.1. |
| RNF-002 (accesibilidad) | Sí | Equivalente textual, foco restaurado, sin información solo por color, i18n es/en, sin desbordamiento a 360 px. |
| RNF-003 (aislamiento/privilegios) | Sí | Migración aditiva nueva, verificada en volumen limpio y ya migrado. |
| RNF-004 (privacidad en registros) | Sí | Sin registros nuevos. |
| RNF-005 (verificación) | Sí | Casos de ambos con formación, uno con formación y otro con planilla, formación incompleta, sin publicar, titular sin posición, conteo distinto, `formation_code` nulo con slot, cero titulares, walkover, consentimiento retirado. |
| RNF-006 (documentación) | Sí | Se actualiza la lista cerrada de campos públicos (spec 020, RF-015) con `segment_number`. |