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

## 7. Revisión en navegador — 2026-11-11

Esta revisión es posterior a la inspección estática del 2026-10-28. No convierte sus comprobaciones manuales pendientes en verificaciones realizadas.

### Método y alcance

- Stack local de Docker Compose con `scripts.seed_demo`: torneo de eliminación directa, ocho equipos, 96 jugadores, siete partidos y cuatro cuartos cerrados con formaciones publicadas. Frontend reconstruido con el código de esta revisión. Sin cambios de API, matriz pública ni reglas de cierre.
- Playwright conectado a Chrome por CDP; axe-core **4.10.3** inyectado en el navegador y ejecutado sobre el documento completo en escritorio (1440×900), incluyendo la regla `color-contrast`. Capturas adicionales en móvil (390×844).
- Rutas públicas anónimas; Workspace con la cuenta demo. Se mantiene Nuxt DevTools para que la comparación antes/después use el mismo entorno de desarrollo.
- Artefactos locales: `/home/ubuntu/ui-audit/axe.json` (antes), `axe-after.json` (después), `screens/` (antes), `after/` (después), `verification-after.json` (teclado, sticky, títulos y checklist) y `console-after.json`. Son evidencias de esta ejecución, no ficheros versionados ni un servicio público.
- «Después» cubre los mismos 14 estados que «antes». Las filas de bracket y estadísticas corresponden a distintos estados del mismo detalle público; axe analiza todo el documento, no solo la sección que aparece en la captura. No deben sumarse como páginas independientes.
- La cuenta demo no tiene permiso de plataforma: `/admin` redirige a 403. Solo se evalúa esa pantalla, no la administración real. El demo no tiene clasificación de liga: sus partidos están en el bracket; no se crearon datos adicionales para simular otra modalidad.

### Resultados antes → después

Notación: `región(n)` = regla `region`, impacto moderado, n nodos; `título` = `document-title`, impacto serio, 1 nodo; `landmark` = `landmark-unique`, impacto moderado, 1 nodo; `selector` = `select-name`, impacto crítico, 1 nodo.

| Página / estado | Antes | Después |
|---|---|---|
| Portada `/` | región(2) | región(1), solo DevTools |
| Detalle público | región(2) | región(1), solo DevTools |
| Bracket | región(2) | región(1), solo DevTools |
| Estadísticas de jugadores | región(2) | región(1), solo DevTools |
| Estadísticas de equipos | región(2) | región(1), solo DevTools |
| Modal de formación pública | Sin violaciones detectadas | Sin violaciones detectadas |
| `/login` | región(2) | región(1), solo DevTools |
| `/workspace` | región(1) | región(1), solo DevTools |
| Configuración del torneo | título + landmark + región(1) | región(1), solo DevTools |
| Calendario | título + región(1) | región(1), solo DevTools |
| Plantillas | título + región(1) | región(1), solo DevTools |
| Operación del partido cerrado | título + región(1) | región(1), solo DevTools |
| Miembros | selector + región(1) | región(1), solo DevTools |
| Acceso a `/admin` denegado | región(2) | región(1), solo DevTools |

El aviso `region` restante apunta al indicador de tiempo de `nuxt-devtools-frame`; no se ha ocultado ni excluido del análisis. La formación modal no lo incluye porque el resto del documento queda inerte. No se declara una auditoría global «verde».

### Contraste (`color-contrast`)

**Cero violaciones automáticas detectadas antes y después**, pero axe dejó numerosos nodos como `incomplete` (requieren revisión manual, por ejemplo fondos con gradientes). La ausencia de violaciones **no certifica WCAG AA** ni equivale a contraste verificado en todos los textos.

| Página / estado | Nodos `incomplete` antes | Nodos `incomplete` después | Nodos con pase automático después |
|---|---:|---:|---:|
| Portada | 30 | 30 | 1 |
| Detalle público | 509 | 410 | 152 |
| Bracket | 509 | 410 | 152 |
| Estadísticas de jugadores | 509 | 410 | 152 |
| Estadísticas de equipos | 122 | 99 | 76 |
| Modal de formación | 25 | 25 | 12 |
| Login | 15 | 15 | 0 |
| Workspace | 13 | 13 | 10 |
| Configuración | 138 | 138 | 66 |
| Calendario | 50 | 50 | 20 |
| Plantillas | 111 | 111 | 19 |
| Operación | 97 | 97 | 21 |
| Miembros | 26 | 26 | 12 |
| Acceso admin denegado | 4 | 4 | 5 |

El análisis inicial no guardó el conjunto de pases automáticos; no se reconstruye ese dato. Los distintos conteos públicos reflejan también el fondo opaco de la nueva columna sticky: no significan que se haya revisado manualmente el contraste restante. Esta comprobación automatizada es de escritorio; no se certifica contraste móvil.

### Correcciones y comprobación visual

- Miembros: el selector de rol de cada miembro lleva un nombre contextual, incluido el dueño deshabilitado (`Rol: Demo Owner`). El selector de invitación conserva su label asociado. Axe ya no detecta `select-name`.
- Cada página declara título. Además de las cuatro rutas reportadas, el barrido estático detectó ausencia de título propio en Workspace, cuenta Google, callback y organización; se añadieron con el patrón traducido `… | Bracket Craft`. Las cinco rutas principales de Workspace se verificaron también por navegación; las pantallas OAuth/organización no se recorrieron en una sesión real del proveedor.
- Los índices de asistentes incluyen el título de su asistente en el nombre del landmark. El selector flotante de idioma queda dentro de una navegación con nombre sin cambiar su estilo.
- TeamPitch y MatchPitch muestran los códigos abreviados existentes de formación (`CM`, `CM_L`, `GK`, etc.) sin partirlos. El nombre completo traducido permanece en `title` y en texto visualmente oculto; PublicLineupModal reutiliza TeamPitch y conserva su equivalente textual con nombres completos. Se comprobó visualmente la formación pública móvil, no todas las combinaciones de formaciones en MatchPitch.
- Estadísticas: columna de jugador/equipo sticky con fondo opaco; bracket y tablas usan una región nombrada, enfocable, una instrucción de desplazamiento móvil y degradado de borde sin animación. Se ejercitó el desplazamiento horizontal con flecha derecha y se capturaron los extremos desplazados de ambas tablas y del bracket. Se comprobó sticky en ambas tablas y `scroll-behavior: auto` con reduced-motion. Sin overflow horizontal global en los estados móviles medidos.
- Acta cerrada: la cadena real del demo pasa por `_close_quarterfinal` → `CloseMatchReportService.execute`; el cierre confirma el resultado y marca el segmento como `completed` (`backend/app/modules/matches/service.py`). El frontend buscaba un segmento `active` y representaba todo valor falso como pendiente. Ahora, usando el mismo estado terminal que ya bloquea la edición, la ausencia de segmento activo se representa como **No requerido** y la ausencia de árbitro principal como **Sin asignar**, con guion e indicación neutra, nunca como un árbitro ficticio ni como un requisito satisfecho. Si existe árbitro, mantiene Listo; los partidos abiertos mantienen Pendiente y su alerta. No se cambian validaciones ni escrituras del cierre.
- Capturas mínimas: `after/workspace-members-desktop.png`, `workspace-members-directory-mobile.png`, `public-lineup-mobile.png`, `public-stats-players-mobile.png`, `public-stats-teams-mobile.png`, `public-bracket-mobile.png`, `workspace-match-desktop.png`, `workspace-match-mobile.png` y las tres vistas móviles `*-scrolled-mobile.png`.
- Sin eventos `console.error` ni `pageerror` en la captura principal posterior (`console-after.json`: `[]`). El indicador de DevTools sigue superponiéndose a contenido inferior en móvil: se documenta como artefacto de desarrollo, no como defecto corregido del producto.

### Verificación de código y límites

Contenedor `node:24`, pnpm **12.12.1**: `pnpm test` (800 tests, 799 pass, 0 fail, 1 skipped), `pnpm run typecheck`, `pnpm run lint` y `pnpm run build` finalizaron con código 0. El test de layout que exigía `overflow-wrap: anywhere` se ajustó al nuevo requisito de posiciones sin cortes. Se añadieron tests del checklist abierto/cerrado/vacío, títulos de todas las páginas, landmarks y superficies de scroll.

No se ejecutaron Lighthouse, E2E completo, lector de pantalla ni una revisión manual de todos los ratios de contraste o del foco en todas las páginas. La administración real y el flujo OAuth real permanecen sin verificar. Las evidencias anteriores no sustituyen esas comprobaciones.
