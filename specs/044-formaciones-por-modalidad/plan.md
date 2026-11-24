# Plan — Spec 044: Formaciones por modalidad (F12)

Estado: aprobado por el usuario el 2026-11-24 («Apruebo el plan y las tareas. Empieza por T1»).

## 1. Alcance y dependencias

- **Una migración nueva, `066_formations_by_game_format.sql`:** sustituye el `CHECK` anónimo `match_team_lineups_formation_code_check` de la 007 por `chk_match_team_lineup_formation_code`, que acepta los 13 códigos de la spec. Sin tablas, columnas, índices, vistas, políticas RLS ni permisos nuevos. Las filas existentes ya cumplen el `CHECK` nuevo, porque solo se añaden códigos.
- Sin endpoints, campos de API, eventos de outbox ni Socket.IO nuevos. `engine_version` y `schema_version` no cambian (DA-4).
- Sin dependencias nuevas.
- **Orden de despliegue:** la 066 se aplica antes que la API. Si la API se despliega primero, una formación nueva falla en la base de datos y no se guarda nada.
- **Dos PR de implementación:** el bloque A es el backend y la migración (T1–T3); el bloque B, el frontend, el E2E y la documentación (T4–T7).

## 2. Archivos y responsabilidades

### Backend y base de datos

| Archivo | Responsabilidad | RF |
|---|---|---|
| `backend/app/modules/rule_contract.py` | `FORMATION_SLOTS` pasa a tener las 13 formaciones (las 4 de 11v11 intactas). Nuevo `FORMATIONS_BY_GAME_FORMAT: dict[str, tuple[str, ...]]` y funciones puras `formation_game_format(code) -> str` y `starters_for_game_format(fmt) -> int` (5/7/9/11). `FORMATION_CODES` sigue derivado de `FORMATION_SLOTS`, así que `FormationCode` admite los 13 códigos y rechaza el resto con 422. | RF-001, RF-011 |
| `backend/app/modules/matches/formations.py` | Reexporta las funciones nuevas. | RF-001 |
| `backend/app/modules/matches/router.py` | **Guardar (`PUT /{id}/lineup`):** el rechazo general fuera de 11v11 pasa a ser por formación. Si algún `formation_code` pertenece a otra modalidad que la del partido, responde 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT` antes de escribir. El 422 de titulares cita `n = starters_for_game_format(fmt)`. **Publicar:** mismo 409 si la formación guardada es de otra modalidad (caso de una formación privada que quedó de un formato anterior). Se exigen `starters == n` y `players >= n`, y el mensaje cita `n`. La despublicación no se valida. | RF-002, RF-003 |
| `backend/app/modules/tournaments/routes/versions.py` | Generaliza la 024. Lee `SELECT DISTINCT mtl.formation_code ... is_public` en lugar de `SELECT 1`, y responde 409 `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED` si alguna formación publicada es de una modalidad distinta del formato nuevo. Aplica a cualquier par de formatos, también desde 5v5/7v7/9v9 a 11v11. | RF-004 |
| `backend/app/modules/tournaments/public_stats.py` | Sin cambios de código: la atribución del `GK` ya es independiente del formato. Los tests nuevos lo fijan para 5v5/7v7/9v9. | RF-008 |
| `infra/postgres/migrations/066_formations_by_game_format.sql` | `ALTER TABLE ... DROP CONSTRAINT IF EXISTS match_team_lineups_formation_code_check, ADD CONSTRAINT chk_match_team_lineup_formation_code CHECK (formation_code IN (…13…))`, en una transacción. | RF-001, RNF-002 |
| `docs/contrato-reglas.md` | §3 con el catálogo por modalidad; §4 con la prueba de la 066; §5 retira «no habilita formaciones por modalidad». `engine_version` se queda en `2026.1`. | RF-011 |

### Frontend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `frontend/app/constants/formations.ts` | `FormationCode` con 13 códigos, `FORMATIONS_GRID` con las coordenadas de las nueve nuevas (mismas bandas de `y` que usa `slotLine`: portero ≥ 85, defensa ≥ 60, medio ≥ 45, ataque < 45), `FORMATIONS_BY_GAME_FORMAT`, `formationOptionsFor(format)` y `formationGameFormat(code)`. `FORMATION_OPTIONS` queda como la lista de 11v11. | RF-001, RF-006 |
| `frontend/app/utils/publicLineup.ts` | `VALID_FORMATION_CODES` se deriva de `FORMATIONS_GRID` en lugar de estar escrito a mano. Una formación desconocida sigue cayendo a la planilla. | RF-006 |
| `frontend/app/components/match/MatchLineupSection.vue` + `useMatchOperationState.ts` | El selector recibe `matchGameFormat` y ofrece «Planilla clásica» más `formationOptionsFor(matchGameFormat)`. Si la formación guardada es de otra modalidad (formación privada anterior a un cambio de formato), se muestra como opción deshabilitada con un aviso localizado. Para guardar hay que elegir una formación válida o la planilla clásica; publicar sigue en manos del backend (409). | RF-002, RF-006 |
| `frontend/app/composables/useMatchLineup.ts` | Sin cambios de lógica: `formationSlots` ya sale de la rejilla. Los tests fijan la precarga entre segmentos (028) con una formación de 5v5. | RF-006 |
| `frontend/app/components/public/TeamPitch.vue`, `MatchPitch.vue` | Sin cambios de lógica: dibujan con `FORMATIONS_GRID`. Los tests comprueban que las nueve formaciones nuevas se dibujan sin solaparse, con al menos 10 puntos de distancia entre posiciones. | RF-006 |
| `frontend/app/composables/useI18n.ts` | `format.context` y `rules.gameFormatHint` pasan a decir que el formato fija el catálogo de formaciones y los titulares de una formación. Claves nuevas ES/EN para el aviso de formación de otra modalidad y para los códigos 409 en la operación. | RF-007, RNF-003 |
| `README.md`, `AGENTS.md`, `docs/manual-usuario.md`, `docs/informe-funciones-adicionales.md` (F12 implementada), `MEMORY.md` | Documentación y procedimiento de la 066. | RNF-005 |

## 3. Catálogo y coordenadas

Las posiciones son las de la tabla RF-001 de la spec. Las coordenadas están en el mismo sistema que las de 11v11 (0–100, el portero abajo):

| Formación | Coordenadas `x,y` |
|---|---|
| `1-2-1` | GK 50,88 · CB 50,70 · LM 22,48 · RM 78,48 · ST 50,20 |
| `2-1-1` | GK 50,88 · LCB 32,70 · RCB 68,70 · CM 50,50 · ST 50,20 |
| `2-2` | GK 50,88 · LCB 32,70 · RCB 68,70 · ST_L 35,25 · ST_R 65,25 |
| `2-3-1` | GK 50,88 · LCB 32,72 · RCB 68,72 · LM 18,48 · CM 50,52 · RM 82,48 · ST 50,20 |
| `3-2-1` | GK 50,88 · LCB 24,72 · CB 50,74 · RCB 76,72 · LCM 35,50 · RCM 65,50 · ST 50,20 |
| `3-1-2` | GK 50,88 · LCB 24,72 · CB 50,74 · RCB 76,72 · CM 50,52 · ST_L 35,22 · ST_R 65,22 |
| `3-3-2` | GK 50,88 · LCB 24,72 · CB 50,74 · RCB 76,72 · LM 18,48 · CM 50,52 · RM 82,48 · ST_L 38,20 · ST_R 62,20 |
| `3-4-1` | GK 50,88 · LCB 24,72 · CB 50,74 · RCB 76,72 · LM 14,48 · LCM 38,51 · RCM 62,51 · RM 86,48 · ST 50,20 |
| `4-3-1` | GK 50,88 · LB 15,70 · LCB 38,73 · RCB 62,73 · RB 85,70 · CM_L 29,50 · CM 50,54 · CM_R 71,50 · ST 50,20 |

## 4. Interfaz

Sin rutas ni campos nuevos. Cambian los valores admitidos y los errores:

| Operación | Antes (024) | Después |
|---|---|---|
| `PUT /matches/{id}/lineup` con `team_lineups` en 7v7 | 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT` | 200 con `3-2-1`; 409 con `4-3-3`; 422 con 8 titulares o posiciones ajenas |
| Publicar en 7v7 | 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT` | 200 con 7 titulares en sus posiciones; 409 con otro número |
| `formation_code` desconocido | 422 | 422 (catálogo de 13) |
| Cambiar el formato de un borrador con una formación pública | 409 solo de 11v11 a otro | 409 si la modalidad de alguna formación pública ≠ formato nuevo |
| Lectura pública | — | Sin campos nuevos; `formation_code` puede tomar los códigos nuevos |

## 5. Estrategia de pruebas

| Nivel | Prueba | RF |
|---|---|---|
| Unidad backend | `test_rule_contract.py`: 13 formaciones con un `GK` y `n` posiciones distintas del catálogo de 23; las de 11v11 intactas; `FormationCode` == documento == `CHECK` de la 066; `engine_version == "2026.1"`. | RF-001, RF-011 |
| BD opt-in | `test_migration_066.py`: sobre volumen migrado acepta los 13 códigos y rechaza un 14.º; la 066 se puede reaplicar y conserva las filas existentes; nombre del `CHECK` nuevo y ausencia del anterior. `test_migration_021.py` se ajusta al catálogo nuevo. | RF-001, RNF-002 |
| BD opt-in | `test_lineup_game_format.py` (nuevo o ampliación de los de la 024): guardar/publicar en cada modalidad, otra modalidad → 409 sin escribir, titulares de más o de menos → 422/409, despublicar siempre permitido, otra organización → 404 y sin escritura, 11v11 sin cambios. | RF-002, RF-003, RF-009, RF-010 |
| BD opt-in | Cambio de formato: 7v7→5v5 con formación pública → 409; 9v9→9v9 → 200; 7v7→11v11 con formación pública de 7 → 409; sin formaciones públicas → 200. | RF-004 |
| BD opt-in | Estadísticas: portería imbatida atribuida al `GK` en 5v5/7v7/9v9, incluido el portero entrante; sin formación publicada no hay atribución. | RF-008 |
| Unidad frontend | `formations.test.ts`: catálogo por modalidad igual al del backend (lista fija), separación mínima entre posiciones, `slotLine` coherente; `public-lineup.test.ts` con formaciones nuevas y códigos desconocidos; selector por modalidad y formación ajena deshabilitada; textos ES/EN. | RF-001, RF-006, RF-007 |
| E2E | `e2e/formations-by-format.spec.ts` con contratos ficticios, como `public-polish`/`theme-workspace`: Workspace 7v7 con selector de 7v7 y campo público de una formación de 5v5, 7v7 y 9v9; axe sin violaciones en ambos temas a 1440 y 390 px. | RF-006, RNF-004 |

## 6. Verificación de la constitución

- **§2.1–2.2 Multi-tenant y RLS:** las escrituras y lecturas siguen con `set_rls_context` y las políticas existentes. Hay pruebas de otra organización.
- **§2.3 Inmutabilidad:** no se reescribe ninguna formación ni acta; la migración solo amplía el `CHECK` (RF-009).
- **§2.5 Proyección pública mínima:** no hay campos públicos nuevos.
- **§3.2 Reglas configurables:** la modalidad sale de `game_format` en la configuración de la versión. El catálogo de formaciones es contrato interno, no configuración, y no se vuelve configurable.
- **§3.3 Frontend:** toda llamada sigue pasando por `useApi`.
- **§5.2:** no se toca ningún principio, así que no hace falta una enmienda.

## 7. Riesgos

- **API antes de la 066:** las formaciones nuevas fallan en la base de datos con 500 y no se guarda nada. Se mitiga documentando el orden en el README.
- **Clientes antiguos en caché:** un cliente público anterior no conoce los códigos nuevos y cae a la planilla (caso límite 7), sin romperse.
