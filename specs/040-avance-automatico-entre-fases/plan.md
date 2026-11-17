# Plan — Spec 040: Avance automático entre fases (F2)

Estado: aprobado por el usuario el 2026-11-16 («Apruebo plan y tareas»).

## 1. Alcance y dependencias

- Parte de la spec 006 (avance manual en borrador, `stage_teams` inmutable al publicar), de la 019 (estrechó `phase_slots.source_type` a `direct_team`/`match_result`), de la 033/038 (rectificación del avance e impacto `later_phase`) y del motor de clasificación (`StandingsService`, `ranking_pipeline`).
- No cambia `engine_version` ni `docs/contrato-reglas.md`. No requiere enmienda constitucional (spec §Contexto).
- Una migración nueva, `063_stage_slot_origins.sql`. No se edita ninguna migración aplicada.

## 2. Archivos y responsabilidades

### Base de datos (`infra/postgres/migrations/063_stage_slot_origins.sql`)
- Vuelve a admitir `stage_rank` en `phase_slots.source_type`, descubriendo el CHECK por catálogo como la 019. `source_reference` de `stage_rank`: `{"kind":"group_position","source_stage_id","group_id"|null,"position"}` o `{"kind":"best_of_position","source_stage_id","position","ordinal"}`.
- Tabla tenant `stage_slot_resolutions` (RLS `ENABLE`+`FORCE` y políticas en la misma migración): destino, versión, gestor, fecha, huella de la clasificación usada y asignaciones `plaza → equipo`. `UNIQUE (stage_id)`: como máximo una resolución por llave (RNF-002). `bracket_app` solo `SELECT, INSERT` (append-only).
- `match_slot_assignments.origin` admite `stage_rank` y gana `stage_slot_resolution_id` nullable con FK compuesta por organización.
- Excepción acotada de inmutabilidad: `prevent_published_structure_mutation()` permite **solo** `INSERT` en `stage_teams` de una versión `published` cuando `app.stage_slot_resolution_id` apunta a una resolución de esa misma fase y organización que contiene ese equipo, con `group_id` nulo. Ninguna otra tabla ni operación cambia. Patrón equivalente a `app.rectification_version_id` de la 038. `SECURITY INVOKER`, sin `BYPASSRLS`.
- Las plazas de partido ya se llenan en lo publicado (el trigger de partidos admite `NULL → equipo`); no se toca.
- Vista interna `v_public_match_slot_origins` (partido, lado, tipo, nombre de grupo, posición, ordinal) solo para torneos públicos visibles, para la etiqueta pública de las plazas sin resolver.

### Backend
- `modules/stage_advancement/` (nuevo): `origins.py` (funciones puras), `service.py` (declarar, previsualizar, confirmar), `schemas.py` (`extra="forbid"`, `hide_input_in_errors=True`), `router.py`.
- `tournaments/scheduling.py`: `build_seeded_single_elimination_bracket` y `build_seeded_double_elimination_bracket`, que reciben plazas ordenadas por cabeza de serie en lugar de barajar. Las funciones actuales no cambian.
- `tournaments/routes/versions.py`: el clonado reasigna en `source_reference` los IDs de fase y grupo de las plazas `stage_rank` (CL-6).
- `tournaments/routes/stages.py`: `POST/DELETE .../teams` y el sorteo responden 409 en una llave con orígenes (RF-011).
- `tournaments/routes/public.py`: `home_origin`/`away_origin` nulos salvo en plazas sin resolver.
- `main.py`: registro del router.

### Frontend
- `composables/useStageAdvancement.ts` (vía `useApi`), `utils/stageAdvancement.ts` (modelo puro y etiquetas ES/EN).
- `components/workspace/setup/StageSlotOriginsEditor.vue` (borrador) y `StageResolutionPanel.vue` (publicado), enlazados desde `SetupStages.vue`.
- Llave pública: etiqueta de origen en plazas vacías (`PublicBracket` y utilidades existentes).

### Tests
- Backend: `test_migration_063.py` (opt-in DB), `test_stage_slot_origins.py` (puras), `test_stage_advancement_routes.py` (DB).
- Frontend: `stage-advancement.test.ts`, extensión de `public-bracket*.test.ts`.
- E2E: `e2e/stage-advancement.spec.ts` en el proyecto `workspace` y la etiqueta en `public-polish.spec.ts`, con contratos ficticios.

## 3. Funciones puras (`origins.py`)

- `validate_origins(origins, source_stages, groups)` → errores por plaza (RF-002, RF-013, CL-8).
- `classic_template(groups, slots_count)` → orígenes sugeridos: primeros, segundos y «mejores N.º» hasta completar, colocados con el emparejamiento estándar de cabezas de serie (1 contra N…) y evitando cruces del mismo grupo en primera ronda cuando hay alternativa (RF-001b, CL-7: los pases libres van a las cabezas de serie más altas).
- `rank_best_of(rows_by_group, position, pipeline)` → orden entre grupos sin `head_to_head` (RF-012); `random_draw` usa `deterministic_tie_value` con clave propia.
- `unresolved_ties(...)` → plazas bloqueadas por empate que ningún criterio declarado rompe (RF-006).
- `standings_fingerprint(...)` → SHA-256 estable de clasificación, estados de equipos, tamaños de grupo y estado de partidos de las fases de origen (RF-008).
- `stage_finished(matches)` → solo `finished` o resolución administrativa; cancelado, programado, en vivo o suspendido no cuentan (CL-2).

## 4. Interfaz

Todas bajo `/api/v1/tournaments/{tournament_id}/stages/{stage_id}/`, con RLS y `set_rls_context()` en la transacción. Lectura para miembros; escritura con `MANAGE_TOURNAMENTS`.

| Método y ruta | Respuesta |
|---|---|
| `GET slot-origins` | `200` plazas, orígenes, estado (`editable`, `frozen`, `resolved`) |
| `GET slot-origins/template?slots_count=N` | `200` propuesta, sin escribir |
| `PUT slot-origins` | `200`; solo borrador; valida y regenera la llave con plazas `stage_rank` (`replace_existing` como hoy); `409` publicado, `422` origen inválido |
| `GET resolution/preview` | `200` por plaza: origen, equipo propuesto o motivo de bloqueo; `resolvable`, `fingerprint` |
| `POST resolution` `{fingerprint}` | `201` llena todo; `409` huella obsoleta, ya resuelta o versión no publicada; `422` no resoluble |

Confirmación: bloqueo fase → versión (`lock_stage_and_version`) → partidos de la llave; recalcula la vista previa, compara la huella, inserta la resolución (la `UNIQUE` corta la carrera), fija `app.stage_slot_resolution_id`, inserta `stage_teams`, llena `home_team_id`/`away_team_id` de las plazas (también las de segunda ronda tras pase libre), registra `match_slot_assignments` con `origin='stage_rank'`, audita en `administrative_audit_logs` (`STAGE_SLOTS_RESOLVED`, solo IDs) y encola `MATCH_UPDATED` por partido.

## 5. Decisiones justificadas

- **Llave generada en borrador con plazas vacías:** los partidos y enlaces existen antes de publicar, así que publicar congela cruces y orígenes con los triggers actuales (RF-003) y la confirmación solo llena plazas.
- **Escribir `stage_teams` al confirmar:** mantiene coherentes plantillas, alineaciones y la detección `later_phase` de la 038, que ya abre un impacto competitivo si una rectificación cambia la clasificación de origen (RF-010) sin código nuevo de rectificación.
- **Sin sustitución automática:** `substitute_slots` solo actúa sobre asignaciones `advancement_link`/`rectification`; las de `stage_rank` nunca se reemplazan.
- **Huella en vez de versión:** la clasificación no tiene contador de revisión; la huella cubre también estados de equipos y partidos.

## 6. Estrategia de tests

- Cada tarea empieza en rojo. Puras con tablas de casos (4, 6, 8, 12, 16 plazas; grupos 3×4, 4×4, 6×4, 3+4).
- DB: torneo grupos → llave publicado sin clasificados; confirmación llena; huella obsoleta 409; dos confirmaciones simultáneas → una; organización ajena 404; publicado: `PUT` 409 y `stage_teams` directo rechazado por trigger; rectificación posterior abre `later_phase` y no cambia plazas; clon reasigna IDs.

## 7. RF cubiertos por parte

- A (T1–T6): RF-001–RF-013, RNF-001–RNF-003, CL-1–CL-8.
- B (T7–T11): RF-001b y RF-004–RF-009 en UI, RNF-004, criterios 1–4.

## 8. Exposición pública

- Nuevo: `home_origin`/`away_origin` en partidos públicos de la llave (lista cerrada: `kind`, `group_name`, `position`, `ordinal`), nulos en plazas llenas. Cambio no aditivo declarado en la matriz de la 020.
- Vista previa, huella, auditoría y gestor nunca son públicos.

## 9. Verificación de constitución

- RLS + `FORCE` + políticas en la 063; `set_rls_context()` en toda transacción; sin `BYPASSRLS` ni `SECURITY DEFINER`.
- Lo publicado no se edita: la excepción solo inserta asignaciones derivadas de una regla publicada y una resolución append-only.
- Actas corregidas solo por la 033; partidos posteriores no se modifican automáticamente.
- Migración nueva y numerada; `useApi` en el frontend; tests en todas las tareas.

## 10. Notas de despliegue

Aplicar la 063 antes de la API. Runbook en README (pre-chequeo del CHECK, aplicación y forward-fix).
