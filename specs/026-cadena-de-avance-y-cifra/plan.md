# Plan 026 — Cadena de avance, aviso de minutos y cifra de composición

Estado: borrador (2026-10-28)

Parte de `specs/026-cadena-de-avance-y-cifra/spec.md` (**17 RF, 7 RNF**, ORD-4 a ORD-14). El plan no añade requisitos: describe cómo se cumplen. Las tareas están en `tasks.md`.

> **Dependencia declarada de la 025.** Este cambio **usa** el orden, la numeración, el ancla `#fases`, el título enfocable del asistente de fases y el destino del enlace cruzado tal como los deja `specs/025-recorrido-de-configuracion/`. No los reimplementa, no los reordena y **no puede desplegarse antes** que la 025: si la 025 no está aplicada, `#fases` no existe y el destino de Equipos → Fases no tiene bloque al que llegar. La relación con la spec **012** es aditiva y se declara en la spec (matiza RF-007 y RF-035; verifica sin cambio RF-018, RF-020, RNF-005 y RNF-008).

## 1. Alcance del cambio

Cambio **solo de frontend** (Nuxt 4 / Vue 3), más documentación y el arnés E2E. Se toca:

- La página de configuración del torneo (guardado de reglas, alta de equipos, confirmación de fases y aviso de minutos).
- El asistente de fases (evento de confirmación efectiva y cifra de composición del paso de composición y de la revisión).
- Dos utilidades puras nuevas y las traducciones de los dos controles del aviso y del total por encima de 64.
- Las pruebas de frontend, el arnés `frontend/e2e/` y el manual de usuario.

**Confirmaciones de alcance (RNF-005):**

- **Sin backend:** no se toca ningún módulo de `backend/app/`, ni `backend/app/main.py`, ni `scripts/`.
- **Sin migraciones ni esquema:** no se crea ninguna migración; el esquema sigue en **031**.
- **Sin contratos HTTP:** ningún endpoint, campo de respuesta, parámetro de consulta, código `code`, `engine_version` ni `schema_version` nuevos; las peticiones de los asistentes son las mismas y en el mismo orden (RF-012, RNF-005).
- **Sin permisos nuevos:** no se añade rol, permiso ni visibilidad; el observador sigue en solo lectura y sin cadena (RF-005).
- **Sin rediseño visual:** la cifra ocupa el mismo párrafo que hoy, los dos controles del aviso son `button-secondary` y la única estructura nueva es un contenedor mínimo de acciones junto al texto ya existente; no cambian tipografía, espaciado ni paneles.
- **Sin rutas ni parámetros nuevos:** los destinos son el ancla `#equipos` que ya existe, el ancla `#fases` de la 025 y la ruta de calendario que ya existe (RF-001 a RF-003).

## 2. Archivos y responsabilidades

| Archivo | Responsabilidad en este cambio | RF |
|---|---|---|
| `frontend/app/utils/stageComposition.ts` | **Nuevo.** Cálculo puro del total de composición: unión de inscritos y seleccionados, visibilidad según carga y desbordamiento de 64. | RF-010, RF-011, RF-014, RNF-006 |
| `frontend/app/utils/sectionAdvance.ts` | **Nuevo.** Destino puro de cada salto, decisión de avance según el resultado del guardado y resolución del salto pendiente del aviso. | RF-001, RF-002, RF-003, RF-004, RF-007, RF-015, RF-016 |
| `frontend/app/components/StageTeamsWizard.vue` | Cifra única en el paso de composición y en la revisión, estado de carga sin cifra en «fase existente», y evento nuevo `confirmed` solo en la confirmación efectiva. | RF-003, RF-004, RF-010, RF-011, RF-014, RNF-003, RNF-004 |
| `frontend/app/pages/workspace/tournaments/[id]/index.vue` | Cadena Reglas → Equipos y Equipos → Fases, aviso de minutos con sus dos controles después del guardado, foco y anuncio del destino, y salto Fases → Calendario al recibir `confirmed`. | RF-001, RF-004 a RF-009, RF-015 a RF-017 |
| `frontend/app/components/TeamsWizard.vue` | Sin cambio de comportamiento: su `saved` ya solo se emite tras un alta efectiva y pasa a encadenar a Fases desde la página. | RF-002, RF-004 |
| `frontend/app/composables/useI18n.ts` | `rules.minutesWarning.continue`, `rules.minutesWarning.stay` y `stage.wizard.teamCountOverflow`, en español e inglés. | RF-011, RF-015, RNF-004 |
| `frontend/app/pages/workspace/tournaments/[id]/calendar.vue` | **Sin cambio.** Es el destino del último salto y conserva su propia carga, su error y su reintento. | RF-003, RF-008 |
| `frontend/tests/stage-composition.test.ts` | **Nuevo.** Pruebas puras del total, del desbordamiento y de la visibilidad mientras carga. | RF-010, RF-011, RF-014, RNF-006 |
| `frontend/tests/section-advance.test.ts` | **Nuevo.** Pruebas puras de destinos, decisión de avance y salto pendiente; incluye que el destino de Equipos → Fases coincide con `phasesAssistantHref` de la 025. | RF-001, RF-002, RF-003, RF-004, RF-007, RF-015, RF-016 |
| `frontend/tests/stage-teams.test.ts` | Se amplía con la cifra, el estado de carga y el evento `confirmed` por inspección de fuente; la expectativa de la dirección del enlace **no se toca** (la actualizó la 025). | RF-002, RF-010, RF-011, RF-014 |
| `frontend/tests/rules-minutes.test.ts` | Se actualiza el nombre y el comentario de la prueba del aviso a «muestra el aviso después de guardar», sin retirar comprobaciones, y se añade el caso de guardado fallido sin aviso. | RF-015, RF-016, RNF-001 |
| `frontend/tests/navigation.test.ts` | Sin cambio de expectativa: sirve de no regresión de que abrir por `#fases` o por un paso no dispara ningún salto. | RF-006 |
| `frontend/e2e/operationFlow.ts` | El escenario de operación y cierre comprueba la sección de destino tras el alta de equipos y tras confirmar la fase, y vuelve a configuración con la espera existente. | RNF-007 |
| `docs/manual-usuario.md` | Describe la cadena, el paso de entrada del asistente de fases, los dos controles del aviso —con el momento en que aparecen— y la cifra de composición, sin repetir la secuencia numerada. | RNF-002 |
| `README.md`, `AGENTS.md` | Remiten al manual; **no** se vuelven a tocar sus enumeraciones de apartados ni de anclas (las actualizó la 025). | RNF-002 |

**Fuera del cambio:** `frontend/app/composables/useApi.ts` (no hay llamadas nuevas), `frontend/app/utils/wizardStep.ts` y `useWizardStep.ts` (la fuente del paso no se toca, ORD-13), `frontend/app/utils/stageWizard.ts` en su validación y en el máximo por petición (`reviewStage.teamCount` sigue midiendo solo la selección pendiente), `frontend/app/utils/rosterLimits.ts`, `frontend/app/utils/teamsWizard.ts`, `infra/` y `backend/`.

## 3. Funciones puras

### 3.1 `stageComposition.ts`

```ts
import { MAX_STAGE_TEAMS } from '~/utils/stageWizard';

export interface StageCompositionInput {
  readonly mode: 'create' | 'existing';
  readonly assignedTeamIds: readonly string[];
  readonly selectedTeamIds: readonly string[];
  /** La lista de equipos inscritos de la fase aún se está leyendo. */
  readonly loading: boolean;
}

export interface StageComposition {
  /** `false` solo en «fase existente» mientras la lista de inscritos no ha cargado. */
  readonly visible: boolean;
  readonly count: number;
  readonly overflows: boolean;
  readonly teamIds: readonly string[];
}

export function stageComposition(input: StageCompositionInput): StageComposition;

/** Clave i18n y parámetros de la cifra: «N de 64 equipos» o el total real. */
export function compositionMessage(
  composition: StageComposition,
): { readonly key: 'stage.wizard.teamCount' | 'stage.wizard.teamCountOverflow';
     readonly params: { readonly count: number; readonly max?: number } };
```

- `count` es el tamaño de la **unión por identificador** de inscritos y seleccionados, nunca una suma ciega: un equipo marcado que ya estuviera inscrito cuenta una vez (RF-010).
- `visible` es `!(mode === 'existing' && loading)`: en el alta no hay inscritos que leer y la cifra aparece con los seleccionados, incluido «0 de 64» sin selección (RF-014).
- `overflows` es `count > MAX_STAGE_TEAMS`; la cifra no recorta y el mensaje cambia de clave, sin el «de 64» (RF-011).
- No lee reloj, almacenamiento ni red; mismas entradas, mismo resultado (RNF-006).

**Decisión (D-1):** el cálculo vive en un módulo puro nuevo y no dentro de `reviewStage`. *Alternativa descartada:* ampliar `reviewStage.teamCount` para que sume inscritos —convertiría un valor que hoy mide la **selección pendiente** (validación de 64 por petición y avisos de composición vacía) en un total mixto, cambiaría el significado de un campo existente y obligaría a reescribir las pruebas del asistente en vez de añadirlas—.

### 3.2 `sectionAdvance.ts`

```ts
export type ConfigurationSection = 'rules' | 'teams' | 'stages' | 'calendar';

export interface AdvanceTarget {
  readonly path: string;
  /** Fragmento de la misma pantalla; `null` cuando el destino es otra ruta. */
  readonly hash: `#${string}` | null;
  /** El salto conserva la consulta actual, para no añadir ni retirar `?step=`. */
  readonly keepQuery: boolean;
}

export function advanceTarget(
  section: ConfigurationSection,
  tournamentId: string,
): AdvanceTarget | null;

export type AdvanceDecision =
  | { readonly kind: 'navigate'; readonly target: AdvanceTarget }
  | { readonly kind: 'wait'; readonly target: AdvanceTarget }
  | { readonly kind: 'stay' };

export function advanceAfterSave(input: {
  readonly section: ConfigurationSection;
  readonly effective: boolean;
  /** El guardado efectivo dejó el aviso de minutos. */
  readonly notice: boolean;
  readonly tournamentId: string;
}): AdvanceDecision;

export function resolveNotice(
  decision: Extract<AdvanceDecision, { kind: 'wait' }>,
  choice: 'continue' | 'stay',
): AdvanceDecision;

export function clearsPendingAdvance(
  event: 'edit' | 'save' | 'save-failed' | 'navigation' | 'version-change' | 'reload',
): boolean;
```

- `advanceTarget` devuelve `#equipos` para reglas, el mismo destino que `phasesAssistantHref` (025 RF-013) para equipos, la ruta de calendario sin consulta para fases, y `null` para calendario, que es el final de la cadena (RF-001, RF-003).
- **Una sola definición del destino de fases:** `advanceTarget('teams', …)` se construye a partir de `phasesAssistantHref(tournamentId)` de `frontend/app/utils/teamsWizard.ts` —separando ruta y fragmento—, de modo que el salto y el enlace cruzado de la 025 no puedan divergir; no se reescribe la función de la 025 ni se duplica el literal `#fases`.
- `advanceAfterSave` navega solo con `effective`; con `effective && notice` devuelve `wait` —la pantalla se queda en Reglas y el salto queda armado—; sin éxito devuelve `stay` (RF-004, RF-015).
- `resolveNotice` con `continue` devuelve la navegación ya armada y con `stay` devuelve `stay`; ninguna de las dos guarda (RF-015).
- `clearsPendingAdvance` es la tabla única de invalidación de RF-016: `save-failed` y `navigation` y `version-change` y `reload` descartan el salto sin ejecutarlo; `edit` y `save` lo descartan porque el aviso se recalcula; la pulsación de un control no está en la lista porque su efecto lo decide `resolveNotice`.
- `keepQuery` es lo que cumple el criterio de RF-007 de no añadir ni retirar el `?step=` presente: la página compone el destino con la consulta actual.

**Decisión (D-2):** la decisión de avance se calcula en una función pura y la página solo la ejecuta. *Alternativa descartada:* encadenar con un `watch` sobre el resultado del guardado —una segunda fuente del avance, difícil de probar sin navegador y con riesgo de disparar el salto dos veces—.

### 3.3 Sin otras funciones nuevas

El foco, el anuncio y el enrutado son efectos de la página; no se añade ningún módulo puro más. La condición y el texto del aviso de minutos siguen siendo de `frontend/app/utils/rulesMinutes.ts` (012), que no se toca.

## 4. Mecanismo

### 4.1 Cifra de composición (RF-010 a RF-014, RNF-003, RNF-004)

- `StageTeamsWizard.vue` calcula `composition = computed(() => stageComposition({ mode: mode.value, assignedTeamIds: assignedTeams.map(t => t.team_id), selectedTeamIds: review.value.teamIds, loading: teamsLoading.value }))`.
- **Paso de composición:** el párrafo `stage.wizard.teamCount` de la línea actual pasa a pintar `compositionMessage(composition)` y solo se pinta si `composition.visible`; mientras no sea visible se muestra el estado de carga que el asistente ya pinta (`common.loading`, `role="status"`), sin cifra (ORD-14).
- **Resumen de revisión:** la fila de composición usa la misma `compositionMessage(composition)` y, si `!composition.visible`, el mismo estado de carga; nunca «0 de 64» con inscritos.
- `review.teamCount` **no cambia** y sigue midiendo la selección pendiente para `validateStageValues`, `confirmDisabled` y los avisos de composición vacía: el bloqueo por límites de plantilla se sigue evaluando sobre la selección (RF-013). Las listas de disponibles e inscritos no se mueven.
- `setupCheck` de la página no consume la cifra: la cifra no escribe ni envía nada (RF-012).

**Decisión (D-3):** la cifra no recorta y cambia de clave i18n por encima de 64. *Alternativa descartada:* mantener `max: MAX_STAGE_TEAMS` siempre —repetiría el defecto de una cifra que no dice la verdad y mostraría «70 de 64 equipos»—.

### 4.2 Reglas → Equipos (RF-001, RF-007, RF-008, RF-009)

En `saveRules`, el `PATCH` de reglas deja de ser «guardar y recargar» para pasar a ser «guardar, decidir y ejecutar»:

1. Se conserva íntegra la validación previa, el `confirm()` de la 012 cuando hay segmentos ya persistidos fuera del máximo y el cálculo `minutesImpactBeforeSave` (012 RF-035). Cancelar la confirmación sigue sin guardar y sin navegar (RF-004).
2. Si el `PATCH` termina con éxito, se marca `effective = true` y **no se vuelve a guardar**. La navegación se decide con `advanceAfterSave({ section: 'rules', effective, notice: Boolean(message), tournamentId })`.
3. La recarga (`loadConfiguration`) se ejecuta **sin condicionar la navegación**: su error ya se registra en la página (`refreshConfiguration` lo absorbe) y el destino muestra su propio estado (RF-008). La sección abandonada queda sin cambios pendientes porque el guardado ya aplicó los valores del servidor (RF-007).
4. `navigate` → `router.push({ path, hash, query: keepQuery ? route.query : {} })` del `AdvanceTarget`; `wait` → se guarda el `target` como salto armado y no se navega (RF-015).
5. El destino se deja a la vista por el propio `hash` y se enfoca su título (`<h2>` del panel de equipos, con `tabindex="-1"`), una sola vez y sin región adicional (RF-007, RNF-003). No viaja ningún mensaje de éxito (RF-009).

**Decisión (D-4):** navegar con `router.push` de un `AdvanceTarget` construido con la consulta actual. *Alternativas descartadas:* `window.location.hash = …` —depende del idioma del navegador para el historial y no permite decidir la navegación desde una función pura—; y `navigateTo` con una cadena ya montada —perdería la consulta y con ella el `?step=` que RF-007 prohíbe añadir o retirar—.

### 4.3 Aviso de minutos con dos controles (RF-015 a RF-017)

- **Cuándo se pinta:** `rulesMinutesNotice` deja de asignarse antes del envío. El mensaje se calcula antes (para el `confirm()` de la 012) pero **se publica en el estado solo después** de que el `PATCH` termine con éxito: mientras la petición está en vuelo no hay aviso, y si falla no queda ninguno (ORD-12, RF-016).
- **Marcado:** el texto sigue en su párrafo con `role="status"` y su misma clase; los dos botones van en un contenedor **hermano**, fuera de la región anunciada (RF-017). «Continuar» (`rules.minutesWarning.continue`) usa el salto armado; «Quedarme» (`rules.minutesWarning.stay`) cancela y devuelve el foco al título del panel de reglas.
- **Idempotencia:** al pulsar, el salto armado y el aviso se limpian en el mismo tick, así que un segundo clic no navega ni guarda (RF-015).
- **Invalidación (RF-016):** un `watch` sobre la edición de reglas (el `dirty-change` del asistente ya existente y `updateRulesConfig`), el cambio de versión, el cambio de torneo, el `resetToken` y la navegación de la misma página (`onBeforeRouteUpdate`/el enlace del índice) llaman a `clearsPendingAdvance` y, si procede, limpian aviso y salto. No se añade ningún estado nuevo en el servidor ni en `sessionStorage`: el salto armado vive en la página (ORD-9).
- **Sin aviso**, el salto es inmediato y no hay controles (RF-001, RF-015).

**Decisión (D-5):** el aviso y su salto pendiente viven en refs de la página y se invalidan por una tabla pura. *Alternativas descartadas:* guardar el salto pendiente en `sessionStorage` —lo haría sobrevivir a la recarga, que RF-016 manda descartar—; y mostrar el aviso durante la petición con controles deshabilitados —lo descarta ORD-12—.

### 4.4 Equipos → Fases (RF-002, RF-007, RF-008, RF-009)

- **Alta individual y en lote:** `TeamsWizard` ya emite `saved` **solo** después de un `POST` correcto (su `catch` no emite). La página, en `@saved`, ejecuta `advanceAfterSave({ section: 'teams', effective: true, notice: false, tournamentId })` y navega al `AdvanceTarget` de `#fases` con la consulta actual; la recarga sigue siendo la de `refreshConfiguration`, sin condicionar el salto.
- **Paso de entrada:** el salto **no escribe `?step=`**. El asistente de fases ya montado resuelve su paso con `useWizardStep` (su `entryStep` de la 012: identificación sin fases, composición con fases) y el `?step=` presente no se añade ni se retira (ORD-13). El bloque de fases queda a la vista por `#fases` de la 025 y su título, enfocable desde la 025, recibe el foco una sola vez.
- **No redirige** cuando el alta falla, cuando la validación está pendiente o cuando el asistente está deshabilitado: esos caminos no emiten `saved` (RF-004).
- **Consecuencia declarada (ORD-4):** cada alta efectiva encadena, también en visitas sucesivas; volver a Equipos encuentra el formulario vacío y sin borrador, como hoy tras guardar.

**Decisión (D-6):** reutilizar el `saved` de `TeamsWizard` sin tocar el componente. *Alternativa descartada:* añadir un evento `confirmed` también aquí —duplicaría la señal y obligaría a cambiar un componente que ya distingue éxito de error—.

### 4.5 Fases → Calendario (RF-003, RF-004)

- `StageTeamsWizard` emite un evento nuevo **`confirmed`** solo cuando la confirmación termina de forma efectiva: fase creada sin composición, fase creada con inscripción completa y reintento que completa la inscripción. **No** lo emite el guardado parcial (`canRetry`), ni el error, ni el `DELETE` de retirar un equipo, que siguen usando `saved` para refrescar listas como hoy (RF-004).
- La página, en `@confirmed`, ejecuta `advanceAfterSave({ section: 'stages', effective: true, notice: false, tournamentId })` y navega a `/workspace/tournaments/{id}/calendar` **sin consulta ni fragmento**; abrir el calendario no crea partido, no sortea y no escribe (RF-003).
- El borrador de la sección abandonada queda descartado por el propio guardado efectivo (RF-007); el componente de origen se desmonta al cambiar de ruta y con él su mensaje, sin que se traslade ninguno (RF-009).

**Decisión (D-7):** un evento `confirmed` separado de `saved`. *Alternativas descartadas:* dar un payload a `saved` (`{ source: 'confirm' | 'remove' | 'refresh' }`) —obliga a tocar los cinco puntos que hoy emiten `saved` y deja el significado del evento a merced de cada llamada—; y navegar desde cualquier `saved` —encadenaría también al retirar un equipo, que no es la acción principal de la sección (ORD-4)—.

### 4.6 Destino a la vista, foco y anuncio (RF-007, RNF-003)

- Los saltos de la misma pantalla (Reglas → Equipos y Equipos → Fases) conservan el componente de origen montado pero fuera de la vista: el foco se mueve al título del bloque de destino después de `nextTick`, y el título es enfocable porque el de fases lo deja la 025 y el de equipos recibe `tabindex="-1"` en la página.
- El salto a otra ruta (Fases → Calendario) no necesita foco manual: el cambio de página coloca el foco en el documento del calendario.
- No se añade ninguna región `aria-live` nueva: el anuncio del destino es el del título enfocado, una sola vez.

## 5. Interfaz

- **Pantallas:** la configuración del torneo y el calendario. No hay pantallas nuevas.
- **Direcciones:** ninguna ruta ni parámetro nuevos. Los destinos son `#equipos`, `#fases` (025) y `/workspace/tournaments/{id}/calendar`; los saltos de la misma pantalla conservan la consulta actual, así que el `?step=` presente no se añade ni se retira.
- **Contratos:** ninguno. El asistente conserva sus peticiones en el mismo número y orden (`POST` de fase y después `POST`/`DELETE` de equipos).
- **Traducciones:** tres claves nuevas en es/en (`rules.minutesWarning.continue`, `rules.minutesWarning.stay`, `stage.wizard.teamCountOverflow`); el resto de textos del aviso, de los avisos de composición vacía y del resumen no se tocan.
- **Accesibilidad:** los dos controles son `<button type="button">` con etiqueta visible, alcanzables con teclado y fuera de la región anunciada; el foco no se mueve al aparecer el aviso.

## 6. Estrategia de tests

La suite de frontend es de Node (`node --test`): prueba funciones puras e inspecciona el fuente de páginas y componentes. Los tests se escriben **antes** del cambio de comportamiento (T1 y T3) y se confirman en rojo.

1. **Puras de composición** (`stage-composition.test.ts`): unión sin duplicados de inscritos y seleccionados, «5 de 64», total real de 70 con desbordamiento, `visible === false` en «fase existente» cargando y `visible === true` en el alta cargando, cero equipos ya cargados, y determinismo con las mismas entradas (RF-010, RF-011, RF-014, RNF-006).
2. **Puras de avance** (`section-advance.test.ts`): los cuatro destinos, `advanceAfterSave` con efectivo/parcial/fallido y con aviso, `resolveNotice` para los dos controles, la tabla de invalidación, y que el destino de Equipos coincide con `phasesAssistantHref` de la 025 (RF-001 a RF-004, RF-007, RF-015, RF-016).
3. **De fuente (ampliadas):** `stage-teams.test.ts` comprueba que el paso de composición y la revisión usan la cifra nueva y que no hay cifra mientras carga en «fase existente», y —en la tarea del último salto— que existe el evento `confirmed` y que no lo emite el guardado parcial ni el retiro de un equipo; `rules-minutes.test.ts` cambia el nombre de la prueba del aviso a «muestra el aviso después de guardar» y añade el caso de guardado fallido sin aviso, sin retirar comprobaciones (RNF-001).
4. **No regresión:** `navigation.test.ts`, `wizard-step.test.ts`, `roster-lock.test.ts` y `roster-limits.test.ts` sin cambios de expectativa; la dirección del enlace equipos → fases **no se vuelve a tocar** (la actualizó la 025).
5. **Arnés E2E:** `cd frontend && pnpm run typecheck:e2e` y, sobre la pila sembrada, `cd frontend && pnpm run e2e:test`; el escenario de operación y cierre comprueba la sección de destino tras el alta de equipos y tras confirmar la fase, y el escenario de reintento no se toca (RNF-007).
6. **Cierre:** `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck` y `cd frontend && pnpm run build`. Lo que no pueda ejecutarse se declara **no ejecutado**.

## 7. Decisiones y alternativas descartadas

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D-1 | Cálculo de la cifra en `stageComposition.ts`, sin tocar `reviewStage.teamCount` | Ampliar `reviewStage.teamCount` a inscritos + seleccionados | Conserva el significado de la selección pendiente en la validación y el bloqueo, y añade cobertura en vez de reescribirla |
| D-2 | Decisión de avance en `sectionAdvance.ts`, ejecutada por la página | Encadenar con un `watch` sobre el guardado | Una sola fuente del avance y pruebas puras, sin dobles saltos |
| D-3 | Total real por encima de 64 con clave propia | Mostrar siempre «de 64» | 64 es el máximo por petición; recortar repetiría el defecto |
| D-4 | `router.push` con `path`/`hash` y la consulta actual | `window.location.hash`; cadena de destino ya montada | Historial determinista y conservación del `?step=` presente (RF-007) |
| D-5 | Aviso y salto pendiente en refs de la página, invalidados por tabla pura | `sessionStorage`; aviso durante la petición con controles deshabilitados | La recarga debe descartar el salto (RF-016) y ORD-12 fija el momento |
| D-6 | Reutilizar `saved` de `TeamsWizard` | Añadir `confirmed` también al alta de equipos | El componente ya distingue éxito de error; no se duplica la señal |
| D-7 | Evento `confirmed` propio en `StageTeamsWizard` | Payload en `saved`; navegar desde cualquier `saved` | `saved` también cubre retirar equipo y refrescar; la cadena solo la produce la acción principal |
| D-8 | Actualizar `operationFlow.ts` en el mismo cambio | Dejar el arnés como está y declararlo pendiente | RNF-007 y RNF-008 de la 012: el arnés no se abandona |
| D-9 | Manual como fuente normativa única; README y AGENTS remiten | Repetir la cadena y la secuencia en README y AGENTS | RNF-002 y constitución §4 |

## 8. Cobertura de requisitos por parte

| Parte | RF/RNF |
|---|---|
| Destinos y decisión de avance (utilidad pura) | RF-001, RF-002, RF-003, RF-004, RF-007 |
| Reglas → Equipos con guardado efectivo | RF-001, RF-008, RF-009, RF-007 |
| Aviso de minutos: momento, controles e invalidación | RF-015, RF-016, RF-017, RNF-004 |
| Equipos → Fases en su paso de entrada | RF-002, RF-007, RF-008, RF-009 |
| Fases → Calendario | RF-003, RF-004, RF-008 |
| Solo lectura y ausencia de redirección al abrir | RF-005, RF-006 |
| Cifra de composición: cálculo y presentación | RF-010, RF-011, RF-012, RF-014, RNF-006 |
| Listas, bloqueo por límites y 409 | RF-013 |
| Accesibilidad del destino y del aviso | RF-007, RF-017, RNF-003 |
| Documentación | RNF-002 |
| Arnés E2E | RNF-007 |
| No regresión y ausencia de efectos | RNF-001, RNF-005 |

## 9. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant con RLS | No | No hay consultas ni esquema nuevos; los saltos se quedan en el torneo, la versión y la organización en curso (RF-001 a RF-007). |
| §2.2 La aplicación no elude RLS | No | No se toca el backend ni el rol de base de datos. |
| §2.3 Lo publicado es inmutable | Sí | El cambio no escribe nada: la cadena solo se dispara con una acción que ya escribe en un borrador; una versión publicada no tiene acción principal y no navega (RF-005). |
| §2.4 Historial de esquema append-only | No | Sin migraciones ni cambios de esquema (RNF-005). |
| §2.5 Lo público es una proyección mínima | No | No se tocan proyecciones públicas ni datos de jugadores. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | No | No hay variables de entorno nuevas. |
| §2.7 Administración global separada y auditada | No | `/admin` queda fuera del alcance. |
| §2.8 Nada se da por terminado sin verificación | Sí | Pruebas puras nuevas, pruebas de fuente ampliadas, `typecheck:e2e` y `pnpm test`/`typecheck`/`build`; lo no ejecutable se declara no ejecutado. |
| §2.9 El código de desarrollo no llega a producción | No | No se añaden seeds ni datos demo. |
| §3.1 Base de datos y multi-tenancy | No | Sin migraciones, tablas ni políticas. |
| §3.2 Backend | No | Sin módulos, routers, outbox ni reglas de dominio. |
| §3.3 Frontend: `useApi.ts` y rutas | Sí | No hay llamadas nuevas ni modificadas: las peticiones de los asistentes siguen pasando por `useApi.ts` en el mismo orden (RF-012); no se añaden rutas ni parámetros, solo fragmentos y una ruta existente como destino. |
| §3.4 Seguridad y configuración | No | Sin secretos, dependencias ni configuración nuevos. |
| §3.5 Infraestructura y CI | Sí (sin cambio) | No cambian versiones, lockfile ni Compose; el job `e2e` ejecuta los mismos comandos y el arnés se actualiza dentro de él (RNF-007). |
| §4 Pasa el job de CI que aplique | Sí | `frontend` (`pnpm test`, `pnpm run typecheck`, `pnpm run build`) y `e2e` (`pnpm run typecheck:e2e`, `pnpm run e2e:test`). |
| §4 Sin secretos, credenciales ni datos personales | Sí | No se introducen datos personales ni secretos; la documentación y las pruebas no los incluyen. |
| §4 Documentación actualizada si cambia el comportamiento | Sí | Manual actualizado y README/AGENTS remitiendo a él (RNF-002). |
| §4 Pruebas del comportamiento nuevo o corregido | Sí | Pruebas puras de la cifra y del avance, pruebas de fuente y arnés actualizado (RNF-001, RNF-006, RNF-007). |
| §4 Cambios de base de datos / API / infraestructura / dependencias | No | No aplican: sin migración, sin backend, sin infraestructura y sin dependencias. |
| §5.1 Excepciones | No | No se requiere ninguna excepción. |

## 10. Riesgos y límites declarados

- **Límite de ORD-7:** en el modo «fase existente» con 0 equipos seleccionados la acción principal sigue deshabilitada, así que no hay salto y el recorrido se corta ahí. Es un límite declarado, no un defecto; no se añade ninguna acción que navegue sin guardar.
- **Un solo punto de espera:** únicamente Reglas → Equipos puede quedar pendiente del aviso. Un salto armado que no se resuelve no sobrevive a una navegación, a una edición, a un guardado nuevo ni a un cambio de versión (RF-016); no hay cola de salidas.
- **`?step=` presente:** el salto conserva la consulta y no escribe paso, así que si la dirección ya nombraba un paso del asistente de fases, es ese paso el que se ve al llegar. Es la consecuencia declarada de ORD-13; en el caso normal (sin `?step=` de fases) el asistente muestra su paso de entrada.
- **Foco del destino:** el salto de la misma pantalla mueve el foco al título del bloque, que necesita ser enfocable; si el título no existe todavía al terminar el `nextTick`, el foco queda donde estaba y el bloque sigue a la vista por el fragmento. Se verifica con las pruebas de fuente y el arnés, y el requisito es el resultado observable (RNF-003).
- **Cifra dependiente de la lista:** la cifra no puede decir más que lo que la pantalla ya cargó. Mientras la lista de inscritos no cargue no hay cifra en «fase existente»; si esa carga falla, se ve el error del asistente y ninguna cifra (ORD-14, RF-012).
- **Total por encima de 64:** no se alcanza en una sola visita; se verifica con pruebas puras y de fuente, no en el arnés, que trabaja con dos equipos.
- **Arnés E2E:** cambia el punto de observación de dos comprobaciones (alta de equipos y fase creada). No se relaja ninguna comprobación existente ni se toca el escenario de reintento; si el entorno no permite ejecutarlo, se declara **no ejecutado**.
- **Dependencia de la 025:** este cambio asume su ancla `#fases`, su título enfocable y su destino de enlace. Un despliegue sin la 025 dejaría el segundo salto sin bloque al que llegar.
