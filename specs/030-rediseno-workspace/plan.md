# Plan 030 — Rediseño del Workspace

Spec: `specs/030-rediseno-workspace/spec.md` (aprobada el 2026-11-11). Solo frontend. No cambian el backend, la API, el esquema, los permisos, `engine_version` ni la matriz pública.

## 1. Archivos y responsabilidades

LY-1: en `rosters.vue`, `calendar.vue` y `members.vue` la lista va antes del formulario; PageHeader incluye un acceso de ancla con foco al primer campo, bajo las condiciones actuales de acceso y respetando reduced-motion.

Desviación de PR B (2026-11-11): la división T4–T5 usa props hacia abajo y eventos hacia arriba, en lugar del `provide/inject` previsto inicialmente. Se conserva la cabecera actual en `MatchOperationHeader` y el CSS scoped compartido en `components/match/operation.css`, sin cambiar presentación; `PageHeader` y el rediseño de la operación quedan para PR C. `useMatchOperationState`, `useMatchLineup`, `useMatchEvents`, `useMatchEventsDraft` y `useMatchClose` mantienen cada archivo por debajo de 600 líneas.

| Archivo | Responsabilidad | RF |
|---|---|---|
| `components/ui/PageHeader.vue` (nuevo) | Cabecera compacta: slot de contexto (rótulo o migas), `title` como único `h1` en tamaño de sección (`--text-xl` fijo, sin `clamp` de display), slot de estado y slot de acciones. Sustituye a los heroes de las páginas del Workspace. | RF-001–003 |
| `pages/workspace/{index,members}.vue`, `tournaments/[id]/{calendar,rosters}.vue` | Usan `PageHeader`; se eliminan el titular de marketing y la descripción promocional, y se conserva el contexto (torneo, estado, formato). | RF-001–003 |
| `tests/support/sources.ts` (nuevo) | `featureSource(entry)`: concatena el código fuente de la página y de los componentes y composables locales que importa (recursivo, solo `components/workspace/**`, `components/match/**` y `composables/use*`). Permite que los tests estáticos sigan pasando tras dividir la página. | RNF-005 |
| `tests/*.test.ts` que leen la operación (14) o la configuración (9) | Pasan de `readFileSync(page)` a `featureSource(page)`, con las mismas aserciones. | RNF-005 |
| `composables/useTournamentSetup.ts` + `components/workspace/setup/{SetupHeader,SetupChecklist,SetupRules,SetupTeams,SetupStages}.vue` | División de `tournaments/[id]/index.vue`. El composable concentra la carga, las versiones, el guardado, la publicación, el borrador y el avance de sección; los componentes reciben props, emiten eventos y montan los asistentes sin cambios. La página queda como orquestador de ≤ 250 líneas. | RF-011, RF-012 |
| `composables/useMatchOperation.ts` (+ `useMatchLineup.ts` y `useMatchEventsDraft.ts` si hace falta para ≤ 600) | Script de la operación: tipos de transporte, estado, `fetchOperation`/`refreshOperation`, `runAction`, tiempo real, borrador local, formularios y errores por campo. Reutiliza `utils/` tal cual. | RF-010, RF-012 |
| `components/match/{MatchResolutionPanel,MatchFieldSection,MatchRosterLinks,MatchLineupSection,MatchEventsSection,MatchCloseSection}.vue` | Una sección del acta por componente, con la plantilla y los estilos actuales. Reciben el contexto por props tipadas y emiten las acciones a la página (props hacia abajo, eventos hacia arriba). | RF-010 |
| `components/match/MatchBar.vue` | Barra de partido `position: sticky` (escudo, nombre, marcador y estado), conexión en tiempo real y segmento o minuto. Los nombres van en una línea con `text-overflow: ellipsis`, `title` y el nombre completo accesible. | RF-004, RF-005, RF-008 |
| `components/match/MatchSectionNav.vue` | `nav` con nombre accesible y enlaces de ancla a `#seccion-*`. `aria-current="location"` sigue la sección visible mediante `IntersectionObserver` (sin JS, los anclajes siguen funcionando). | RF-006 |
| `components/match/MatchActionBar.vue` | Barra inferior fija **solo por debajo de `md` (760 px)**. Muestra la acción principal y se oculta mientras hay un campo de texto enfocado (teclado virtual). | RF-007, RNF-003 |
| `utils/matchScoreDisplay.ts` (nuevo, puro) | `matchScoreDisplay({ status, segments, score, resolution }) → { kind: 'pending' \| 'live' \| 'final', home, away, labelKey }`. Sin segmento iniciado devuelve `pending`; con segmento iniciado y sin goles, `0 – 0`. | RF-005 |
| `utils/matchPrimaryAction.ts` (nuevo, puro) | `primaryAction(input) → { id, labelKey, mode: 'run' \| 'focus', target } \| null` (ver §3). | RF-007 |
| `pages/workspace/matches/[id].vue` | Orquestador de ≤ 250 líneas: `useMatchOperation`, props/eventos y las secciones; conserva la cabecera actual en PR B y recibe `PageHeader`, `MatchBar`, `MatchSectionNav` y `MatchActionBar` en PR C. | RF-010 |
| Asistentes (`RulesEditor`, `rules/*`, `TeamsWizard`, `StageTeamsWizard`, `wizard/*`) | Solo estilos: tokens, `nearestStep` y piezas `ui/` donde la sustitución sea directa. Sin tocar script ni flujo. | RF-013, RF-014 |
| `tests/design-scales.test.ts` | `PENDING_MIGRATION` vacía; las excepciones nuevas se documentan con su motivo. | RF-013 |
| `tests/match-score-display.test.ts`, `match-primary-action.test.ts`, `workspace-layout.test.ts` (nuevos) | Funciones puras; contrato de `PageHeader` (un `h1`); `MatchSectionNav` y `MatchActionBar` (nombre accesible, `aria-current`, ocultación por debajo de `md`, reduced-motion). | RF-001–008 |

## 2. Diseño visual

- **Cabecera compacta:** contexto en `--text-xs` en versalitas con el color de acento, `h1` en `--text-xl` condensado, estado como `StatusPill` y acciones a la derecha (debajo en móvil). Alto objetivo: ≤ 120 px en escritorio y ≤ 140 px en móvil, sin contar la barra global.
- **Barra de partido:** sobre `--color-surface-raised`, con el borde inferior `--color-line`. En escritorio va en una fila: equipo local, marcador condensado `--text-xl` y equipo visitante, con el estado y el minuto a la derecha. En móvil ocupa dos filas como máximo: equipos y marcador en la primera, y estado, segmento y conexión en la segunda. Alto ≤ 96 px en móvil. Va fija en `top: 0` dentro del área de contenido del `WorkspaceShell`.
- **Índice de secciones:** fila desplazable horizontalmente bajo la barra (reutiliza `HorizontalScroll`) con «Resolución · Campo · Plantillas · Planilla · Eventos · Cierre». La sección actual se marca con el subrayado de acento.
- **Acción principal (móvil):** `Button` principal a todo el ancho, sobre una superficie con `env(safe-area-inset-bottom)`. `html { scroll-padding-top / scroll-padding-bottom }` reserva su espacio para que el foco y los anclajes no queden tapados (WCAG 2.4.11).

## 3. Lógica no trivial (pseudocódigo)

```
primaryAction({ status, canOperate, canManage, activeSegment, lineupDirty, draftEvents, closeReady, isTerminal }):
  if isTerminal or not (canOperate or canManage): return null
  if not activeSegment and status in (scheduled, interrupted):
    return { id:'startSegment', mode:'focus', target:'#seccion-campo' }        # requiere minuto/formulario
  if lineupDirty and canOperate: return { id:'saveLineup', mode:'run' }       # mismo handler y disabled que hoy
  if draftEvents > 0 and canOperate: return { id:'saveEvents', mode:'run' }
  if closeReady: return { id:'closeReport', mode:'focus', target:'#seccion-cierre' }  # cerrar exige revisar el formulario
  return { id:'addEvent', mode:'focus', target:'#seccion-eventos' }
```

Los nombres exactos de las condiciones se toman de las que ya usa la página. `run` llama al mismo handler que el botón de su sección y respeta su `disabled`/`busyAction`; `focus` hace `scrollIntoView` (sin animación si se prefiere movimiento reducido) y enfoca el primer control de la sección.

La división se hace en este orden: primero el script (la página sigue funcionando con el mismo template) y después la plantilla, sección a sección. Cada paso mantiene verde el E2E de operación.

## 4. Decisiones y alternativas descartadas

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Contexto por props tipadas y acciones por eventos en las secciones | `provide/inject` tipado del plan inicial | Mantiene el flujo de datos explícito (props hacia abajo, eventos hacia arriba); el objeto de contexto tipado evita repetir decenas de props sin introducir inyección implícita. |
| Barra de acción solo por debajo de `md` | Barra también en escritorio | En escritorio el índice y la barra superior bastan, y una barra fija resta espacio. |
| `featureSource()` para los tests estáticos | Reescribir los tests como montaje | Conserva las aserciones actuales sin coste (RNF-005); el montaje queda fuera de alcance. |
| Acciones con entrada → `focus` | Ejecutar todas desde la barra | Iniciar segmento o cerrar el acta exige datos del formulario; ejecutarlas desde la barra cambiaría el comportamiento (RF-009). |
| `PageHeader` en `ui/` | Cabecera dentro de `WorkspaceShell` | Cada página decide su contexto y sus acciones; la pieza se reutiliza sin acoplar el shell. |

## 5. Estrategia de tests

- Puros: `matchScoreDisplay` y `primaryAction` (tabla de estados × roles, incluidos walkover, resolución administrativa, observador y árbitro).
- Estáticos: `PageHeader` con un `h1` por página del Workspace; índice y barra con su ARIA; guardián de escalas sin pendientes; los 23 tests existentes sobre `featureSource`.
- E2E: `operationFlow` sin cambios de recorrido (la barra no debe interceptar clics; si un clic queda tapado, el E2E lo detecta).
- Manual con evidencia: axe a 1440 y 390; capturas antes/después; mediciones de RF-002 (inicio del contenido principal) y RNF-004 (distancia a la primera acción, comparada con `030-before`).
- Siempre: `pnpm test`, `typecheck`, `lint`, `build` y `typecheck:e2e`.

## 6. Entrega

4 PR: **A** T1–T3 (cabeceras, `featureSource` y división de la configuración) · **B** T4–T5 (división de la operación, sin cambio visual) · **C** T6–T8 (barra, índice, acción y escalas de la operación) · **D** T9–T10 (asistentes, validación y documentación).

## 7. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 1–2 RLS y privilegios de BD | No | Sin backend |
| 3 Lo publicado es inmutable | Sí (indirecto) | La barra solo ejecuta los handlers existentes, con sus guardas |
| 4 Esquema append-only | No | Sin migraciones |
| 5 Lo público es proyección mínima | No | Sin cambios públicos |
| 6 Sin secretos por defecto | No | Sin configuración |
| 7 Admin separada y auditada | No | `/admin` no se toca |
| 8 Nada terminado sin verificación | Sí | §5; lo no verificado se declara en cada PR |
| 9 Código de desarrollo fuera de producción | No | Los fixtures de captura son locales y no se versionan |
| §3.3 `useApi.ts` y rutas | Sí | Sin llamadas nuevas; las existentes se mueven al composable sin cambios |
| §4 CI verde, pruebas y documentación | Sí | RNF-001, §5, AGENTS.md y la inspección de accesibilidad |
