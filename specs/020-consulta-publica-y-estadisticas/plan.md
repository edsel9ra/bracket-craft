# Plan 020 — Consulta pública: navegación por fases y grupos, y acceso público

## Alcance y dependencias

- Spec: `specs/020-consulta-publica-y-estadisticas/spec.md` (estado **aprobada**).
- Bloques cubiertos: **A** (navegación por fases/grupos) y **E** (acceso público). Los bloques B/C/D quedan para las specs 021 y 022.
- No hay cambio de esquema: el esquema sigue en **027** y `engine_version` en **2026.1**. Los filtros `stage_id`/`group_id` ya existen en `public_standings` y `public_matches`.
- Dependencias posteriores: 021 y 022 dependen de esta spec.

## Archivos y responsabilidades

### Frontend

- `frontend/app/utils/publicTournament.ts` — funciones puras de navegación y presentación pública (ampliación).
- `frontend/app/pages/tournaments/[id].vue` — reestructuración: una fase a la vez, selección por URL, grupos independientes, paginación por combinación, llave con resoluciones por texto, estados vacíos.
- `frontend/app/components/PublicBracket.vue` — indicación textual de prórroga/penales/walkover/resolución administrativa (solo si hace falta ajustar).
- `frontend/tests/public-tournament.test.ts` — ampliación de pruebas de funciones puras.
- `frontend/tests/public-navigation.test.ts` — nuevo: normalización de `stage`/`group`, agrupación por grupo, paginación por combinación (node:test).

### Backend

- `backend/tests/test_public_field_allowlist.py` — nuevo: verificación automática de la lista cerrada de campos públicos (RF-015) y ausencia de campos sensibles (RF-016).
- `backend/tests/test_public_access_matrix.py` — nuevo: matriz de acceso (lecturas anónimas, 404 indistinguible, aislamiento entre dos organizaciones, query params fuera de rango → 422).
- `backend/app/modules/tournaments/router.py` — sin cambios funcionales esperados; solo si la auditoría detecta un campo fuera de la lista (entonces se corrige en el mismo cambio).

### Documentación

- `README.md` — matriz de acceso público/privado (RF-020).
- `AGENTS.md` — anotación de la matriz y de los contratos que no cambian.
- `docs/contrato-reglas.md` — sin cambios (no toca el contrato interno).

## Funciones puras (frontend)

Toda función que dependa del tiempo recibe la fecha como parámetro; aquí no hay lógica temporal, solo datos.

En `frontend/app/utils/publicTournament.ts`:

- `sortPublicStages(stages)` — ya existe; orden estable por `stage_order` y `id`.
- `getPublicStagePresentation(stageType)` — ya existe.
- `normalizePublicSelection(stages, stageParam, groupParam)` → `{ stageId: string | null; groupId: string | null }`:
  - Si `stageParam` no está entre los ids de fases publicadas, devuelve la primera fase publicada y `groupId = null`.
  - Si `groupParam` no está entre los grupos de esa fase, lo elimina (`null`).
  - Si no hay fases, ambos `null`.
- `groupsOfStage(standings, stageId)` → lista ordenada de `{ groupId, groupName }` deducida de las filas de clasificación de esa fase (sin duplicados, orden estable).
- `standingsForGroup(standings, stageId, groupId)` → filas del grupo; si `groupId` es `null`, todas las de la fase.
- `matchesForGroup(matches, stageId, groupId)` → partidos del grupo; si `null`, todos de la fase.
- `resolveMatchOutcomeLabel(match)` → `'walkover' | 'penalties' | 'extra_time' | 'administrative' | null` a partir de `status`, `resolution_type`, `winner_team_id`, `home_penalties`/`away_penalties`, `home_score_regular`/`away_score_regular` vs `home_score`/`away_score`. Sin campos nuevos.
- `hasMoreForCombination(pagination, key)` y `nextOffsetForCombination(...)` — helpers del estado de paginación por combinación `(stageId, groupId)`.

Todas con tests en `frontend/tests/public-navigation.test.ts` (node:test, sin DOM).

## Interfaz: endpoints (sin cambios de contrato)

No se añaden endpoints ni campos. Se reutilizan los existentes con sus parámetros ya soportados:

- `GET /api/v1/tournaments/public` — listado.
- `GET /api/v1/tournaments/public/{id}` — detalle (fases, equipos).
- `GET /api/v1/tournaments/public/{id}/standings?stage_id=&group_id=&limit=&offset=` — clasificación filtrada.
- `GET /api/v1/tournaments/public/{id}/matches?stage_id=&group_id=&limit=&offset=` — partidos filtrados.

La paginación pasa a ser **por combinación** `(stage_id, group_id)` en el cliente: cada combinación mantiene su propio `offset` y su indicador «hay más». El servidor no cambia.

## Decisiones justificadas

1. **Sin nueva migración.** La spec solo reorganiza la navegación y audita el acceso; los filtros `stage_id`/`group_id` ya existen y la lista cerrada de campos ya está fijada por los modelos Pydantic y las vistas. Alternativa descartada: crear una vista agrupada por fase — duplicaría proyecciones y rompería RNF-003 (consultas crecerían con fases).
2. **Selección de fase/grupo en la URL con query params `stage`/`group` (UUID).** Permite compartir y recargar (RF-002). Alternativa descartada: estado en memoria o hash — no compartible ni restorable con «atrás».
3. **Normalización inicial con `replace`, cambios del usuario con `push`.** Una sola fuente del paso (el parámetro), consistente con el patrón de los asistentes del Workspace (AGENTS.md). Alternativa descartada: siempre `push` — rompería el botón «atrás» en la normalización inicial.
4. **Paginación por combinación en el cliente (Map de offsets).** Cada fase/grupo carga bajo demanda; no se pre-cargan todas las fases. Alternativa descartada: una petición global paginada — es el defecto actual (RF-008).
5. **Lista cerrada verificada por introspección de modelos Pydantic + vistas SQL, no por middleware en runtime.** La garantía es una prueba que falla si aparece un campo fuera de la lista. Alternativa descartada: validación en runtime — overhead y duplicación del contrato.
6. **Sin campos nuevos en ninguna respuesta.** RNF-001: solo cambios aditivos futuros se declaran; esta spec no añade ninguno.

## Anexo — Lista cerrada de campos públicos (RF-015)

Modelos de respuesta (`backend/app/modules/tournaments/schemas.py` o equivalente):

- `PublicTournamentSummaryResponse`: `id`, `name`, `season`, `start_date`, `status`.
- `PublicStageResponse`: `id`, `name`, `stage_type`, `stage_order`.
- `PublicTournamentTeamResponse`: `team_id`, `name`, `short_code`, `crest_url`.
- `PublicTournamentResponse`: `id`, `name`, `season`, `start_date`, `status`, `stages`, `teams`.
- `PublicStandingResponse`: `tournament_id`, `stage_id`, `stage_name`, `stage_order`, `group_id`, `group_name`, `team_id`, `team_name`, `short_code`, `played`, `won`, `drawn`, `lost`, `goals_for`, `goals_against`, `goal_difference`, `points`, `fair_play_points`, `rank`, `calculated_at`, `crest_url`.
- `PublicLineupPlayerResponse`: `player_id`, `first_name`, `last_name`, `dorsal_number`, `role`, `position_slot`, `photo_url`.
- `PublicTeamLineupResponse`: `team_id`, `team_name`, `formation_code`, `segment_number`, `crest_url`, `starters`, `substitutes`.
- `PublicMatchLineupResponse`: `home`, `away`.
- `PublicMatchResponse`: `id`, `tournament_id`, `stage_id`, `stage_name`, `stage_order`, `group_id`, `group_name`, `bracket_code`, `matchday`, `match_date`, `home_team_id`, `home_team_name`, `home_team_short_code`, `away_team_id`, `away_team_name`, `away_team_short_code`, `home_team_crest_url`, `away_team_crest_url`, `home_score_regular`, `away_score_regular`, `home_score`, `away_score`, `home_penalties`, `away_penalties`, `winner_team_id`, `status`, `resolution_type`, `lineup`.

Vistas públicas (`infra/postgres/...`): `v_public_tournaments`, `v_public_stages`, `v_public_tournament_teams`, `v_public_standings`, `v_public_matches`, `v_public_match_lineups` — mismos campos, más los internos de firma (`crest_object_key`, `photo_url` crudo) que nunca salen al cliente.

Campos prohibidos (RF-016): documentos de identidad, fecha de nacimiento, edad, `logo_url` heredado, claves de almacenamiento, motivo de walkover/resolución administrativa, sanciones, suspensiones, auditoría, datos de miembros.

## Estrategia de tests

- **Frontend (node:test):** funciones puras en `publicTournament.ts` (normalización, agrupación, resolución de etiqueta, paginación por combinación). Comando: `cd frontend && pnpm test`.
- **Backend (pytest, sin base):** `test_public_field_allowlist.py` introspecciona los modelos Pydantic y los endpoints con DB fake; falla si un campo no está en la lista o si falta uno declarado. Comando: `cd backend && pytest -q`.
- **Backend (pytest, opt-in con PostgreSQL):** `test_public_access_matrix.py` con dos tenants: torneo en borrador/sin versión/org inactiva → 404 indistinguible; aislamiento; query params fuera de rango → 422. Comando: `RUN_DATABASE_TESTS=1 pytest -q`.
- **E2E:** no se añade escenario nuevo en esta spec; el arnés existente sigue cubriendo el tiempo real. Se documenta como no ejecutado si no se corre.

## Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant en la base | Sí | Las lecturas públicas usan las vistas `v_public_*` con RLS; no se añaden tablas ni se elude RLS. El test de aislamiento con dos tenants verifica que no se mezclan datos. |
| §2.2 La app no tiene privilegios de saltar RLS | Sí | Sin cambios de privilegios; el rol `bracket_app` sigue sin `BYPASSRLS`. |
| §2.3 Lo publicado es inmutable | Sí | No se editan versiones publicadas ni resultados; la spec solo lee. |
| §2.4 Historial de esquema append-only | Sí | No hay migración nueva; no se edita ninguna aplicada. |
| §2.5 Lo público es proyección mínima | Sí | RF-015/RF-016 fijan la lista cerrada y los campos prohibidos; la verificación automática falla ante cualquier campo fuera de la lista. Sin fotos sin consentimiento. |
| §2.6 Sin secretos por defecto fuera de desarrollo | No | Sin variables nuevas. |
| §2.7 Administración global separada y auditada | No | Sin cambios en `/admin`. |
| §2.8 Nada terminado sin verificación | Sí | Tests frontend/backend + typecheck + build; CI completo. |
| §2.9 Código de desarrollo no llega a producción | No | Sin seeds ni datos demo. |
| §3.1 `set_rls_context` en transacción | Sí | Las lecturas públicas ya lo usan; no se añaden consultas tenant sin contexto. |
| §3.2 Módulo y router registrados | Sí | Sin módulo nuevo; cambios solo en `tournaments/router.py` si la auditoría lo exige, ya registrado. |
| §3.3 Toda llamada HTTP usa `useApi.ts` | Sí | La página pública ya usa `useApi`; se mantiene. |
| §3.4 Defaults solo en `.env.example` | No | Sin variables nuevas. |
| §3.5 Versiones de referencia | Sí | Sin cambios de versiones. |
| §4 Criterios de cambio (tests, docs, CI) | Sí | Tests añadidos, documentación actualizada, cinco jobs de CI. |
| §4 Cambios de frontend | Sí | `pnpm test`, `pnpm run typecheck`, `pnpm run build`. |
| §4 Cambios de API/backend | Sí | `pytest -q`, `compileall`. |
| RNF-001 Compatibilidad aditiva | Sí | Sin campos nuevos; un cliente que ignore los cambios (no hay campos nuevos) conserva su comportamiento. |
| RNF-003 Rendimiento acotado | Sí | Paginación por combinación con tope de filas; el número de consultas no crece con partidos ni filas (una por combinación activa). Firmas en lote después de cerrar la transacción. |
| RNF-004 Accesibilidad | Sí | Tablas con `caption`/`scope`, sin info solo por color, texto en español e inglés, scroll horizontal dentro del contenedor. |
| RNF-005 Aislamiento y privilegios | Sí | Sin migración; RLS vigente; test de aislamiento. |
| RNF-006 Privacidad en registros | Sí | Sin logs con datos personales. |
| RNF-007 Verificación | Sí | Tests automáticos de lista cerrada y aislamiento. |
| RNF-008 Documentación | Sí | README y AGENTS.md actualizados. |