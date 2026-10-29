# Tareas: Reestructuración del alta de equipos

## T001 — Añadir `teams.entry` y `showInIndex` al modelo del wizard
**RF:** RF-001, RF-002
**Hecho cuando:** `wizardModel.ts` exporta el campo `teams.entry` con valores `'individual' | 'bulk' | 'existing'` y cada paso del wizard tiene la propiedad `showInIndex: boolean`. Tests en `wizard-model.test.ts` verifican la estructura.

## T002 — Añadir estados del asistente de equipos
**RF:** RF-003
**Hecho cuando:** El modelo define los estados `idle`, `validating`, `saving`, `error`, `success` para el asistente de equipos. Tests verifican las transiciones.
**Estado:** hecha.

## T003 — Implementar `validateTeamValues`
**RF:** RF-004
**Hecho cuando:** `teamsWizard.ts` exporta `validateTeamValues(values)` que valida nombre (requerido, max 100), short_name (requerido, max 10), y devuelve lista de errores por campo. Tests cubren casos válidos e inválidos.
**Estado:** hecha.

## T004 — Implementar `teamWizardValues` y `teamWizardStatuses`
**RF:** RF-005, RF-006
**Hecho cuando:** `teamWizardValues(state)` extrae valores del formulario y `teamWizardStatuses(state)` computa el estado visual de cada paso. Tests verifican extracción y estados.
**Estado:** hecha.
## T005 — Implementar normalización legacy
**RF:** RF-007
**Hecho cuando:** Función pura convierte datos de versiones anteriores al nuevo formato con `teams.entry`. Tests cubren migración de datos legacy.
**Estado:** hecha.
## T006 — Implementar `review`
**RF:** RF-008
**Hecho cuando:** `review(state)` genera resumen de revisión (nombre, modo de entrada, jugadores). Tests verifican el resumen.
**Estado:** hecha.

## T007 — Reubicar selector de modo de entrada en `TeamsWizard.vue`
**RF:** RF-009, RF-010
**Hecho cuando:** El selector de modo de entrada (`individual`/`bulk`/`existing`) es el primer paso del asistente. `showEntryPathStep` controla su visibilidad. Tests de componente verifican el render.
**Estado:** hecha.

## T008 — Filtrar pasos por `showInIndex` en `WizardSteps.vue`
**RF:** RF-011
**Hecho cuando:** `WizardSteps.vue` solo muestra en el índice lateral los pasos con `showInIndex === true`. Tests verifican el filtrado.
**Estado:** hecha.

## T009 — Añadir claves i18n `wizard.teams.entry`
**RF:** RF-012
**Hecho cuando:** Se añaden las claves `wizard.teams.entry.individual`, `.bulk`, `.existing` en los archivos de i18n (es/en). Tests de i18n verifican la presencia.
**Estado:** hecha.
## T010 — Tests de integración del flujo completo
**Estado:** hecha.
**RF:** RF-013
**Hecho cuando:** Tests en `stage-teams.test.ts` verifican el flujo completo: selección de modo → formulario → validación → revisión → confirmación. Todos los tests pasan con `pnpm test`.
