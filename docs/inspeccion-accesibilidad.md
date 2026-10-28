# Inspección de accesibilidad — Spec 023 (Bloque F)

**RF cubiertos:** RF-023, RF-024.
**Fecha de inspección:** 2026-10-28.
**Entorno:** revisión estática del código fuente (Vue/Nuxt) y de las pruebas existentes. No se dispone de navegador ni de la pila Docker en esta tarea, por lo que la inspección visual e interactiva se declara **no ejecutada** donde se indica (RNF-002).

## 1. Método

- No se introducen herramientas nuevas (RNF-001): no axe, no Lighthouse, no auditoría automatizada de contraste.
- La verificación se apoya en tres fuentes:
  1. Revisión estática de las plantillas Vue (`frontend/app/**/*.vue`) para atributos `aria-*`, `role`, `alt` y regiones `aria-live`.
  2. Pruebas unitarias de frontend (`frontend/tests/*.test.ts`) que ya fijan la presencia de `aria-invalid`/`aria-describedby`/`role="status"` en componentes concretos.
  3. El arnés E2E existente (`frontend/e2e/operationFlow.spec.ts`), que recorre los tres asistentes **solo con teclado** y verifica título enfocado, error asociado y la equivalencia del aviso de cierre con el `409` real (RF-024).
- El contraste de color, el orden real de foco en vistas no cubiertas por E2E y el renderizado efectivo de `alt` se verifican por inspección manual en navegador y se declaran **no ejecutados** en esta entrega, con el método indicado para su futura ejecución.

## 2. Alcance (vistas revisadas)

Públicas:

- Portada de torneos (`frontend/app/pages/index.vue`).
- Detalle de torneo (`frontend/app/pages/tournaments/[id].vue`).
- Modal de alineación pública (`frontend/app/components/public/PublicLineupModal.vue`).
- Tablas de estadísticas públicas (`frontend/app/components/public/PublicPlayerStatsTable.vue`, `PublicTeamStatsTable.vue`).
- Formaciones gráficas (`frontend/app/components/public/MatchPitch.vue`, `TeamPitch.vue`, `PublicBracket.vue`).

Workspace:

- Configuración del torneo (`frontend/app/pages/workspace/tournaments/[id]/index.vue` + `RulesEditor.vue`, `RulesWizard.vue`).
- Calendario (`frontend/app/pages/workspace/tournaments/[id]/calendar.vue`).
- Plantillas (`frontend/app/pages/workspace/tournaments/[id]/rosters.vue`).
- Operación de partido (`frontend/app/pages/workspace/matches/[id].vue`).
- Asistentes de reglas/fases/equipos (`RulesWizard.vue`, `StageTeamsWizard.vue`, `TeamsWizard.vue`, `wizard/WizardShell.vue`, `WizardSteps.vue`).

Autenticación y cuenta:

- Login (`frontend/app/pages/login.vue`), callback (`frontend/app/pages/auth/callback.vue`), cuenta Google (`frontend/app/pages/account/google.vue`), creación de organización (`frontend/app/pages/organization.vue`), invitación (`frontend/app/pages/invitations/[token].vue`).

Administración:

- Panel global (`frontend/app/pages/admin/index.vue`).

## 3. Resultado por criterio (RF-023)

| Criterio | Evidencia estática | Resultado |
|---|---|---|
| Navegación completa por teclado | Los asistentes usan `WizardShell`/`WizardSteps` con foco en el título y navegación por pasos; `operationFlow.spec.ts` recorre los tres asistentes solo con teclado (RF-024). | Verificado en E2E para los tres asistentes; **no verificado** en el resto de vistas (declarado no ejecutado). |
| Foco visible y orden lógico | Las plantillas usan controles nativos (`button`, `input`, `select`, `a`) con orden DOM; no se detectan `tabindex` negativos que rompan el orden. | **No verificado visualmente** (sin navegador); método: recorrer con `Tab`/`Shift+Tab` y comprobar anillo de foco en cada vista del §2. |
| Etiquetas accesibles en controles | Los campos de los asistentes y del editor de reglas tienen `aria-invalid`/`aria-describedby` asociados (ver `frontend/tests/match-operation-screen.test.ts`, `match-events.test.ts`, `rules-config.test.ts`, `crest-surfaces.test.ts`). | Verificado por pruebas unitarias para los componentes cubiertos; **pendiente** de revisión manual en vistas no cubiertas por tests. |
| Mensajes de error asociados (`aria-invalid`/`aria-describedby`) | `RulesEditor.vue`, `TeamsWizard.vue`, `StageTeamsWizard.vue`, `workspace/matches/[id].vue` y el catálogo de eventos usan `:aria-invalid` y `:aria-describedby` por campo. | Verificado estáticamente en los componentes citados; **pendiente** en vistas no listadas. |
| `aria-live` en avisos | `WizardShell.vue` (`aria-live="polite"`), `RulesEditor.vue` (`aria-live="polite"` en lista de validación), `account/google.vue`, `FormatWarning.vue`, `workspace/matches/[id].vue` (`role="alert" aria-live="assertive"` para bloqueo de apertura) y regiones `role="status"`. | Verificado estáticamente; **pendiente** de comprobación de anuncio real en lector de pantalla. |
| Contraste suficiente | Las clases CSS usan variables de tema; no se midió relación de contraste. | **No ejecutado** (sin herramienta de contraste, RNF-001). Método futuro: inspección manual con DevTools/lector de contraste WCAG AA en las vistas del §2, registrando capturas y ratios. |
| Alternativas textuales (`alt`) para escudos/fotos/campos | `TeamCrest.vue` (`:alt`), `MatchPitch.vue`/`TeamPitch.vue`/`PublicLineupModal.vue` (`:alt="playerName(player)"`), `PublicPlayerStatsTable.vue` (`:alt` con nombre). `TeamCrest` exige `alt` por prop. | Verificado estáticamente en los componentes citados; **pendiente** de comprobación de que todo `img` (incluidos escudos en listados) tenga `alt` no vacío y significativo. |

## 4. E2E y teclado (RF-024)

- El arnés existente (`frontend/e2e/operationFlow.spec.ts`) recorre los tres asistentes solo con teclado y verifica:
  - título enfocado al cambiar de paso,
  - error asociado al campo (`aria-invalid`/`aria-describedby`),
  - equivalencia del aviso de cierre con el `409` real.
- Resultado de la última corrida disponible: **no ejecutada en verde** en esta entrega (fallo de setup de sesión en el entorno, registrado en T5). No se modificó código de producto.

## 5. Lo no ejecutable en esta entrega (declarado, no verde)

- Inspección visual de foco visible y orden de foco en vistas distintas a los tres asistentes.
- Medición de contraste (WCAG AA) en vistas públicas y del Workspace.
- Verificación con lector de pantalla del anuncio de `aria-live`/`role="status"`.
- Recorrido por teclado completo en vistas públicas (portada, detalle, estadísticas) y en autenticación/administración.
- Verificación de `alt` efectivo en todos los `img` renderizados (incluidos escudos en tablas/listados).

Método para ejecutarlas en un entorno con navegador: recorrido manual con teclado (Tab/Shift+Tab/Enter/Espacio), inspección de DOM para `aria-*`/`alt`, y medición de contraste con las herramientas de desarrollo del navegador; registrar vistas, hallazgos y capturas en una nueva revisión de este documento.

## 6. Conclusión

La accesibilidad se cubre parcialmente por pruebas unitarias y por el E2E de teclado en los asistentes. La accesibilidad completa (contraste, `alt` en todas las vistas, orden de foco fuera de los asistentes) queda como **inspección manual documentada**, con método y vistas definidos, y se declara **no ejecutada** en esta entrega por falta de navegador/entorno, sin presentarse como verde (RNF-002).
