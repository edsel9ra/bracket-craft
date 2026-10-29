# Plan: Reestructuración del alta de equipos en el asistente de fases

## Contexto

Cambio exclusivamente de frontend (Vue 3 + Nuxt 4 + modelo puro TS). Sin backend ni migración.
Spec: `specs/027-reestructuracion-alta-equipos/spec.md` (8 [NECESITA ACLARACIÓN] registrados).

## Archivos afectados

| Archivo | Acción |
|---|---|
| `frontend/app/utils/wizardModel.ts` | Añadir `teams.entry`, `showInIndex`, estados |
| `frontend/app/utils/teamsWizard.ts` | `validateTeamValues`, `teamWizardValues`, `teamWizardStatuses`, normalización legacy, review |
| `frontend/app/components/TeamsWizard.vue` | Paso inicial, selector reubicado, `showEntryPathStep` |
| `frontend/app/components/wizard/WizardSteps.vue` | Filtrar por `showInIndex` |
| i18n (`wizard.teams.entry`) | Nuevas claves |
| `frontend/tests/wizard-model.test.ts` | Tests de modelo |
| `frontend/tests/stage-teams.test.ts` | Tests de equipos por fase |

## Funciones puras

### `wizardModel.ts`
- `teams.entry`: nuevo campo en el modelo del wizard de equipos (valores: `'individual' | 'bulk' | 'existing'`).
- `showInIndex`: propiedad booleana en cada paso del wizard para controlar visibilidad en el índice lateral.
- Estados del asistente de equipos: `idle`, `validating`, `saving`, `error`, `success`.

### `teamsWizard.ts`
- `validateTeamValues(values)`: valida los valores del formulario de equipo (nombre, short_name, etc.).
- `teamWizardValues(state)`: extrae los valores del formulario a partir del estado del wizard.
- `teamWizardStatuses(state)`: computa el estado visual de cada paso.
- Normalización legacy: convierte datos de versiones anteriores del wizard al nuevo formato.
- `review(state)`: genera el resumen de revisión antes de confirmar.

### `TeamsWizard.vue`
- Paso inicial: selector de modo de entrada (`individual`, `bulk`, `existing`) reubicado al inicio.
- `showEntryPathStep`: controla si se muestra el paso de selección de modo de entrada.

### `WizardSteps.vue`
- Filtrar pasos por `showInIndex` para no mostrar pasos internos en el índice lateral.

## Decisiones de diseño

1. **Selector reubicado al inicio**: El selector de modo de entrada pasa de estar dentro del paso de equipos a ser el primer paso del asistente, para que el usuario elija el flujo antes de ver el formulario.
2. **`showInIndex` como propiedad declarativa**: Cada paso declara si aparece en el índice lateral, evitando lógica condicional dispersa.
3. **Normalización legacy en el modelo**: La conversión de datos antiguos se hace en `teamsWizard.ts` (función pura), no en el componente, para facilitar tests.

## Estrategia de tests

- Tests unitarios puros en `wizard-model.test.ts` y `stage-teams.test.ts` (Node `--test`).
- Verificar normalización legacy, validación y estados.
- No se requieren tests de integración (sin backend).

## Verificación contra constitución

- §3.1: No se añaden campos sensibles. ✅
- §4: No se toca backend ni migraciones. ✅
- RNF-006: Coherencia documental (spec actualizada). ✅
