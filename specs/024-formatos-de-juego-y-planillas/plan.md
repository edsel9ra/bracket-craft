# Plan 024 — Formatos de juego y planillas

Spec: `specs/024-formatos-de-juego-y-planillas/spec.md` (13 RF, aprobada). Constitución: `docs/constitution.md` v1.4.0. Contrato interno: `docs/contrato-reglas.md` (`engine_version` **2026.1**, sin cambios). Esquema: **031** (sin migración; esta spec no añade tablas ni columnas).

## 1. Alcance

Solo validaciones backend/API y ajustes frontend. No hay migración, ni endpoints, ni campos nuevos. Cambios en:
- `backend/app/modules/matches/errors.py` (dos códigos nuevos).
- `backend/app/main.py` (registro de los dos manejadores).
- `backend/app/modules/matches/router.py` (publicación de formación y guardado con formación en un no 11v11; lectura de `game_format` desde `rules_config` de la versión cargada).
- `backend/app/modules/tournaments/router.py` (`_update_version_rules_record`: rechazar el cambio de formato a no 11v11 si existe formación táctica publicada).
- Frontend: retirar `FormatWarning` de los 3 lugares, contextualizar el formato, permitir guardar plantilla con avisos; actualizar i18n/tests.
- Documentación: README, AGENTS.

Fuera de alcance: formaciones por modalidad, cambio del número de titulares/banca, nuevos endpoints, cambio de versiones, estadísticas dependientes del formato (RF fuera de alcance de la spec).

## 2. Archivos y responsabilidades

### Backend
| Archivo | Responsabilidad |
|---|---|
| `backend/app/modules/matches/errors.py` | Nuevas excepciones `FormationNotSupportedForFormat` (409, `FORMATION_NOT_SUPPORTED_FOR_FORMAT`) y `PublishedFormationMustBeUnpublished` (409, `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED`), con `detail` cadena y `code` aditivo, patrón `_coded_exception_handler`. |
| `backend/app/main.py` | Registrar ambas excepciones con `_coded_exception_handler`. |
| `backend/app/modules/matches/router.py` | En `publish_match_lineup`: tras autorización y estado del recurso, comprobar el formato antes de validar titulares/posiciones; si no es 11v11 → `FormationNotSupportedForFormat`. En `save_match_lineup`: si `payload.team_lineups` no vacío (formación táctica) en formato no 11v11 → `FormationNotSupportedForFormat`. El formato se lee de `match["rules_config"]["game_format"]` (ya cargado por `_load_operation_match`), con ausente → `11v11`. |
| `backend/app/modules/tournaments/router.py` | En `_update_version_rules_record`: si el nuevo `game_format` != `11v11` y existe al menos una formación publicada en `match_team_lineups` de esa versión → `PublishedFormationMustBeUnpublished` (409), antes de escribir. Consulta acotada por `organization_id` y `tournament_version_id`. |

### Frontend
| Archivo | Responsabilidad |
|---|---|
| `frontend/app/components/FormatWarning.vue` | Retirar su uso en los 3 lugares (paso de reglas, resumen, operación). Puede mantenerse el componente o eliminarse; la spec exige retirar el aviso genérico y no sustituirlo por equivalente. |
| `frontend/app/pages/workspace/tournaments/[id]/index.vue` | Quitar `<FormatWarning message-key="format.notice.summary" />`. |
| `frontend/app/pages/workspace/matches/[id].vue` | Quitar `<FormatWarning message-key="format.notice.operation" />`. |
| `frontend/app/components/RulesEditor.vue` | Quitar `<FormatWarning message-key="format.notice.rules" />`; mostrar información contextual veraz (ej. "Formato 7v7 · alineación sin esquema táctico"). |
| `frontend/app/composables/useI18n.ts` | Retirar/ajustar claves `format.notice.*` si quedan sin uso; añadir etiquetas contextuales si se usan. |
| `frontend/app/utils/rulesWizard.ts` | Mantener `formatWarns` si se reutiliza para contextualización; si no, retirar. |

### Documentación
| Archivo | Responsabilidad |
|---|---|
| `README.md`, `AGENTS.md` | Reflejar que el formato deja de ser solo declarativo y que la advertencia genérica se retira. |

## 3. Funciones puras

| Función | Firma | Dónde | Nota |
|---|---|---|---|
| `game_format_of` | `(rules_config) -> str` | helper en router o `rules_engine` | Ausente → `11v11`; sin reloj ni red. |
| `has_published_formation` | `(db, org_id, version_id) -> bool` | `tournaments/router.py` | Consulta acotada por RLS; pura en el sentido de no mutar. |

No se añaden funciones con reloj, entorno ni almacenamiento.

## 4. Decisiones justificadas

| # | Decisión | Alternativa descartada y por qué |
|---|---|---|
| D-1 | El rechazo por formato se comprueba **en el endpoint de publicación**, tras autorización y estado del recurso, y **antes** de validar titulares/posiciones (RF-006). | Validar antes de autorización: rompe la precedencia declarada (permiso y estado primero). Validar después de posiciones: un 422 estructural ganaría al 409 de formato, contradiciendo el RF. |
| D-2 | El guardado de borrador de formación (PUT lineup con `team_lineups`) se rechaza si el formato no es 11v11; la planilla sin posiciones sigue permitida. | Bloquear todo guardado en no 11v11: contradice RF-005/RF-006 (la planilla de convocados está disponible en todos los formatos). |
| D-3 | `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED` se comprueba en `_update_version_rules_record` consultando `match_team_lineups.is_public` de esa versión, sin despublicar automáticamente. | Despublicar automáticamente: contradice RF-011. Comprobar solo el formato anterior: el formato publicado puede haber cambiado; la presencia de formación publicada es la condición real. |
| D-4 | El formato ausente se resuelve como `11v11` en backend al leer `rules_config`, no se materializa ni se reescribe (RF-013). | Materializar en la migración: fuera de alcance (sin migración, RF-010). |
| D-5 | No se añade excepción en `main.py` nueva más allá del patrón existente; ambos errores siguen `_coded_exception_handler`. | Handler ad hoc: inconsistente con el resto de códigos. |

## 5. Estrategia de tests

### Backend (sin base)
- `backend/tests/test_match_lineup_publication.py` o ampliación: publicar formación en no 11v11 → 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT`, sin escritura; publicar en 11v11 sigue OK; despublicar permitido en cualquier formato.
- `backend/tests/test_rules_config_compat.py` / nuevo: cambio de formato con formación publicada → 409 `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED`.

### Backend (opt-in con PostgreSQL)
- Verificación real de la consulta de formación publicada y del rechazo en `_update_version_rules_record`.

### Frontend
- `frontend/tests/rules-config.test.ts`: retirar aserciones de `<FormatWarning` en los 3 lugares o actualizar al nuevo contrato (contextualización sin aviso genérico). Nuevas aserciones: no aparece `format.notice.*` genérico.
- Barrido de pantallas para `aria`/i18n.

### No ejecutable en este entorno
- Suites opt-in y E2E se declaran no ejecutadas si no hay Docker/Node/pytest.

## 6. Verificación de constitución

| Principio/criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 RLS | Sí | Consultas acotadas por `organization_id`; sin tablas nuevas. |
| §2.3 Lo publicado es inmutable | Sí | No se modifica versión publicada; solo borrador. |
| §2.4 Historial append-only | Sí | Sin migración. |
| §2.5 Proyección mínima | Sí | Sin campos públicos nuevos. |
| §4 Todos: CI | Sí | `backend`, `frontend`, `infrastructure`, `security`. |
| §4 Todos: sin secretos/datos personales | Sí | Solo códigos. |
| §4 Todos: documentación | Sí | README/AGENTS. |
| §4 Todos: pruebas | Sí | Listadas en §5. |
| §4 API: consultas tenant con `set_rls_context()` | Sí | Dentro de `db.begin()`. |
| §4 API: endpoints públicos sin sensibles | Sí | Sin cambios. |
| §4 API: `pytest -q` y `compileall` | Sí | Tareas de verificación. |
| §4 Frontend: `pnpm test`, `typecheck`, `build` | Sí | Tareas de verificación. |

## 7. Trazabilidad RF → archivo/prueba

| RF | Implementación | Prueba |
|---|---|---|
| RF-001 (game_format validador funcional) | `errors.py`, router lectura de `game_format` | backend tests |
| RF-002 (rechazo de capacidad exclusiva) | `publish_match_lineup`, `save_match_lineup` | backend tests |
| RF-003 (formaciones exclusivas 11v11) | mismo | backend tests |
| RF-004 (retiro de advertencia genérica) | Frontend 3 lugares | `rules-config.test.ts` actualizado |
| RF-005 (bloqueo solo por validaciones explícitas) | Sin bloqueo nuevo por tamaño | tests existentes |
| RF-006 (edición de plantilla con avisos) | Frontend sin bloqueo | tests existentes |
| RF-007 (ciclo de vida sin cambios) | Sin cambios | suites existentes |
| RF-008 (inmutabilidad) | Sin cambios en publicado | — |
| RF-009 (aislamiento) | RLS | — |
| RF-010 (sin migración) | Sin migración | — |
| RF-011 (cambio de formato con formación publicada) | `_update_version_rules_record` | backend tests |
| RF-012 (privacidad) | Sin campos nuevos | — |
| RF-013 (interpretación consistente de ausente) | `game_format_of` | backend tests |