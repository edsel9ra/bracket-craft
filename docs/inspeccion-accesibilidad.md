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

### Ajuste posterior de abreviaturas y pista móvil

La revisión de la rama sustituyó los códigos crudos visibles por abreviaturas localizadas: por ejemplo POR/DFC/MCI/EI/DC en español y GK/CB/LCM/LW/ST en inglés. Los 23 slots tienen entradas explícitas en ambos catálogos, sin guiones bajos y con un máximo de cuatro caracteres; los nombres completos accesibles se mantienen. Un test recorre todos los slots de todas las formaciones en ambos idiomas y verifica cobertura y formato. Las posiciones desconocidas o sin traducción no muestran el código interno como abreviatura.

La pista visible pasa a «Desliza para ver más columnas» / «Swipe to see more columns»; las instrucciones largas de teclado quedan visualmente ocultas como descripción accesible de la región. Se reconstruyó el frontend y se regeneraron `after/public-lineup-mobile.png` y `after/public-stats-players-mobile.png`: a 390×844 la pista ocupa una sola línea y se comprobaron las abreviaturas españolas junto con sus nombres completos accesibles (`followup-visual.json`). La variante inglesa se verifica en los tests, no mediante una captura adicional.

Los cuatro comandos se volvieron a ejecutar en Node 24 con pnpm 12.12.1: tests 802, pass 801, fail 0, skipped 1; typecheck, lint y build con salida 0. El primer intento de typecheck encontró un binding nativo incompatible al reutilizar dependencias de Alpine en el contenedor Debian; se instaló el lockfile sin cambios en un volumen limpio para ese contenedor y las verificaciones restantes finalizaron correctamente. No se repitió axe en este ajuste: las tablas anteriores corresponden a la auditoría previa, no certifican nuevamente este cambio ni resuelven el contraste pendiente.

## 8. Base de diseño 029 — T1–T5 (2026-11-11)

Esta entrega añade tokens y piezas sin migrar pantallas ni sustituir `window.confirm`. Solo cambia la fuente global a Archivo variable local; el diálogo se monta cerrado una sola vez. T6–T10 siguen pendientes. No se ha realizado una nueva revisión visual, de lector de pantalla o axe: las evidencias de la sección 7 no se presentan como validación de esta entrega.

Contraste calculado mediante luminancia relativa sRGB (WCAG 2.1), con `contrastRatio` y tests de pares semánticos en `design-contrast.test.ts`. No se modificaron los colores existentes. `success` y `home` reutilizan el acento; `away` reutiliza `warning`.

| Primer plano | surface | surface-raised | surface-bright | Uso |
|---|---:|---:|---:|---|
| ink | 15,75:1 | 13,73:1 | 11,58:1 | Texto normal: AA |
| muted | 7,57:1 | 6,60:1 | 5,56:1 | Texto normal: AA |
| accent / success / home | 14,35:1 | 12,51:1 | 10,55:1 | Texto y señal esencial: AA |
| danger | 10,26:1 | 8,94:1 | 7,54:1 | Texto normal: AA |
| warning / away | 12,00:1 | 10,47:1 | 8,83:1 | Texto normal: AA |
| line | 1,79:1 | 1,56:1 | 1,31:1 | **No alcanza 3:1**; solo separador decorativo |

Texto `accent-ink` sobre botones: acento **13,46:1**, peligro **9,62:1**, aviso **11,26:1**. El foco utiliza acento sobre la superficie; los controles secundarios nuevos usan borde muted, no line como única señal esencial. No se certifican pares arbitrarios de colores ni todos los fondos compuestos de las pantallas todavía sin migrar.

Tipografía: `@fontsource-variable/archivo@5.3.0`, únicamente `archivo-latin-wdth-normal.woff2`, ejes peso 100–900 y ancho 62–125 %, emitido por el build con **90 104 bytes** (límite 120 000). La sustitución sobre Arial ajusta tamaño y métricas verticales; las métricas del archivo Archivo son 878/−210/0 unidades (ascendente/descendente/gap) sobre 1000. CSP y su test existente sin cambios; no hay fuentes externas.

Verificación en Node 24 / pnpm 12.12.1 con volumen limpio: `pnpm test` (817 tests, 815 pass, 0 fail, 2 skipped), typecheck, lint, build y typecheck:e2e con salida 0. Un skip es la comprobación del artefacto antes de construir: se ejecutó después del build con `VERIFY_FONT_BUILD=1 node --test --experimental-strip-types tests/fonts.test.ts`, **2 pass / 0 fail**, incluido el peso emitido. La auditoría oficial de dependencias finalizó en OK mediante el filtro constitucional: cinco avisos no accionables (tres moderados y dos bajos), ninguno high/critical accionable.

La cola de confirmaciones se prueba como lógica pura por aplicación (FIFO, cancelación completa, doble resolución y eventos obsoletos). El estado SSR contiene únicamente opciones e identificador; los resolutores permanecen fuera del estado serializado. Los contratos de foco, ARIA, teclado y piezas se verifican estáticamente, y la lógica de flechas/Inicio/Fin mediante tests puros: no equivale a una prueba interactiva del diálogo o a un E2E de su futura integración.

## 9. Confirmaciones 029 — T6 (2026-11-11)

Las 19 llamadas nativas se sustituyen por el diálogo existente. Se conservan los mensajes y las acciones HTTP; los títulos y verbos son específicos por acción en es/en. Las acciones destructivas usan peligro y foco inicial en Cancelar. Reabrir invitación, cambiar resolución y guardar reglas con registros fuera de límite no borran datos y usan tono primario. `beforeunload` no cambia.

Los guards devuelven la promesa. Los selectores de versión y resolución restauran el valor anterior antes de esperar y solo aplican el nuevo tras aceptar. El modo opcional `singleFlight` de cada consumidor devuelve false a activaciones duplicadas mientras espera; los demás consumidores siguen usando la cola compartida. Su liberación ante cancelación o error se prueba, sin cambiar el comportamiento FIFO predeterminado.

Verificación en Node 24 / pnpm 12.12.1: tests **822 pass / 0 fail / 2 skip**, typecheck, lint, build y typecheck:e2e con salida 0. El nuevo guardián analiza llamadas en scripts y expresiones de plantillas, distingue el `confirm` local de las llamadas globales y también rechaza alert/prompt nativos. El inventario tiene 19 sitios convertidos; los otros `confirm` locales de los asistentes son funciones de guardado, no diálogos nativos.

E2E local `operation-flow`: **2 passed (51.0s)** sobre el frontend actualizado del stack demo, incluidos publicar versión y cerrar acta con botón localizado dentro de `role=dialog`. Se usó Chromium de `mcr.microsoft.com/playwright:v1.64.1-noble` (Node 26 de esa imagen; pnpm 12.12.1 instalado solo en el contenedor, que no incluye Corepack). Los cinco checks anteriores sí se ejecutaron en `node:24`. Esto comprueba esos flujos funcionales, no todas las cancelaciones ni cada guard en un navegador. No se repitieron axe, capturas ni revisión visual o de lector de pantalla; CI de T6 queda pendiente del PR.

## 10. Revisión 029 — T7–T10 (2026-11-11)

### Método y cobertura

Stack local de desarrollo, mismo método del §7: Playwright conectado a Chromium por CDP e inyección local de **axe-core 4.10.3**, `axe.run(document, { reporter: 'v2' })`, sin desactivar reglas ni excluir DevTools. Esta revisión sí ejecuta axe a **1440×900 y 390×844**, con movimiento reducido y fuentes cargadas. Se guardan violaciones con todos sus targets y resúmenes de fallo, pases de contraste e incomplete en `/home/ubuntu/ui-audit/axe-029.json`; el baseline conservado es `axe-after.json` del PR #40.

Son **28 estados por resolución, 56 análisis** de documento completo, no 56 páginas independientes:

- Portada, detalle público, bracket, estadísticas de jugadores/equipos y modal de formación.
- Login, registro, invitación válida, 403, organización sin membresías, cuenta Google y callback.
- Workspace, administración real, miembros y su directorio.
- Configuración del torneo, checklist, escudos y asistente de reglas abierto; calendario y formulario; plantillas y formulario; operación de acta cerrada y formulario.
- Diálogo propio de revocación de una invitación abierto y cancelado, sin ejecutar la revocación desde el diálogo.

Los estados reales de admin e invitación no se sustituyen por un 403 ni por un enlace inválido. Se añadió temporalmente una fila local en `platform_admins`, se creó una invitación mediante API (**201**) y se reactivó el usuario local sin organizaciones de T8. Al finalizar, la elevación se retiró, la invitación se revocó mediante API y el usuario temporal se desactivó. No se tocaron seeds ni permisos del producto. El callback se mantiene en espera reteniendo y después entregando la respuesta real de sesión, sin simular datos ni verificar el proveedor OAuth.

### Axe: PR #40 → revisión 029

Las cifras de la tabla son nodos denunciados por regla. El baseline comprende **14 estados solo desktop**; esta revisión amplía a 28 por resolución. En los **13 estados desktop con el mismo identificador** no aparecen reglas nuevas. Los otros estados y móvil amplían cobertura, no tienen un baseline equivalente del PR #40.

| Regla | PR #40 desktop | 029 desktop | 029 móvil |
|---|---:|---:|---:|
| `region`, exclusivamente Nuxt DevTools | 13 | 26 | 26 |
| `color-contrast` | 0 | 0 | 0 |
| `document-title` | 0 | 0 | 0 |
| `landmark-unique` | 0 | 0 | 0 |
| `select-name` | 0 | 0 | 0 |
| Otras reglas con violaciones | 0 | 0 | 0 |
| **Violaciones de aplicación, sin DevTools** | **0** | **0** | **0** |

**Cero violaciones nuevas de aplicación.** Los 52 avisos `region` del nuevo artefacto apuntan únicamente a `nuxt-devtools-frame`/su etiqueta de tiempo. Permanecen en el JSON, no se ocultan para obtener un resultado verde. Los modales de formación y confirmación no presentan violaciones; el resto del documento queda inerte mientras están abiertos.

`color-contrast` deja **incomplete** en 14 estados/1838 nodos del baseline, 27 estados/2700 nodos de 029 desktop y 27 estados/3121 nodos de 029 móvil. Se cuentan apariciones en documentos completos repetidos, no nodos únicos ni regresiones demostradas. Gradientes y fondos compuestos requieren revisión manual: cero violaciones automáticas no certifica WCAG AA universal.

### Contraste, fuente y diálogo

Se conserva la medición sRGB de T1 (§8), verificada por `design-contrast.test.ts`, sin cambiar la paleta base:

| Primer plano | surface | surface-raised | surface-bright |
|---|---:|---:|---:|
| ink | 15,75:1 | 13,73:1 | 11,58:1 |
| muted | 7,57:1 | 6,60:1 | 5,56:1 |
| accent / success / home | 14,35:1 | 12,51:1 | 10,55:1 |
| danger | 10,26:1 | 8,94:1 | 7,54:1 |
| warning / away | 12,00:1 | 10,47:1 | 8,83:1 |
| line | **1,79:1** | **1,56:1** | **1,31:1** |

`--line`/`--color-line` **no alcanza 3:1** y solo se considera separador decorativo, nunca única señal esencial de un control. Los controles nuevos usan muted/acento para esas señales; esto no certifica todos los controles heredados de opción 3. `accent-ink` sobre acento/peligro/aviso mantiene **13,46:1 / 9,62:1 / 11,26:1**. Los tokens añadidos durante T7–T9 representan colores preexistentes, no una nueva paleta.

Archivo variable latino se distribuye localmente con ejes peso/ancho y sustitución métrica sobre Arial; el único woff2 emitido pesa **90 104 bytes**, inferior a 120 000. Sin orígenes de fuentes externos ni cambios de CSP. Las 19 confirmaciones usan el diálogo propio con título, mensaje y verbo localizado; las pruebas de cola/cancelación y el guardián de diálogos nativos permanecen activos. La revisión axe incluye un diálogo peligroso real cancelado; no sustituye una auditoría de todos los caminos de foco y navegación.

### Evidencias, verificación y límites

Las capturas baseline T7 provienen de main y las T8/T9 del worktree `origin/main` (`ce254f0c`); están en `029-before/` y `029-after/`, a ambas resoluciones. La comparación visual corrigió sobredimensionados y superficies nuevas no equivalentes; las diferencias restantes son normalización de escala y presentación de piezas comunes. Operación y asistentes conservan su fuente sin migración visual; heredan solo la normalización global comprobada en T9.

Seis composiciones para el PR, etiquetadas antes/después y de ancho máximo 1600 px, en `/home/ubuntu/ui-audit/029-pr/`: `portada-desktop.png`, `torneo-mobile.png`, `miembros-desktop.png`, `admin-desktop.png`, `configuracion-desktop.png` y `plantillas-mobile.png`.

T10 solo cambia documentación: los inputs del frontend son idénticos al árbol `24a801d79410672966a3c2da45752a1b9a46cd68` verificado en T9, por lo que se conservan sus resultados sin repetir comandos con entradas idénticas. Node **24.22.2**, pnpm **12.12.1**: tests **824 pass / 0 fail / 2 skip**, typecheck, lint sin warnings, build y typecheck:e2e con salida **0**; E2E `operation-flow` **2 passed (44.6s)**, también con Node 24. Auditoría de dependencias constitucional: **OK**, cinco avisos no accionables. Logs `/home/ubuntu/ui-audit/029-t9-*.log`. El guardián conserva **37 excepciones** y únicamente **6 pendientes de opción 3**: operación, RulesEditor, rules/, TeamsWizard, StageTeamsWizard y wizard/.

**Límites:** sin lector de pantalla, dispositivos físicos, Lighthouse ni OAuth real. No se auditan visualmente todos los pasos/estados de asistentes, todos los ratios de fondos compuestos ni todas las cancelaciones; el demo no contiene clasificación de liga. Los emuladores de viewport y axe no equivalen a esas comprobaciones. T1–T10 quedan entregadas localmente, pero el cierre formal como `implementada` continúa pendiente de CI verde sobre la rama completa y revisión final del usuario. No se declara CI verde ni una certificación global de accesibilidad.

## 11. Workspace 030 — cierre T9–T10 (2026-11-11)

Entregas: [PR #44](https://github.com/edsel9ra/bracket-craft/pull/44), [PR #47](https://github.com/edsel9ra/bracket-craft/pull/47), [PR #48](https://github.com/edsel9ra/bracket-craft/pull/48) y PR D, esta entrega en `devin/1794409672-spec-030-asistentes-cierre`. No se abre PR D por instrucción del usuario; no hay todavía número ni resultado de su gate E2E de CI.

### Asistentes: alcance y equivalencia (WZ-1, VI-1)

Solo se modifican los estilos de `RulesEditor.vue`, `rules/RulesWizard.vue`, `TeamsWizard.vue`, `StageTeamsWizard.vue`, `wizard/WizardShell.vue` y `wizard/WizardSteps.vue`. Las 176 decisiones de escala usan `nearestStep`; colores y transparencias se expresan mediante tokens y `color-mix`. Se conservan controles, contratos y estructura, sin sustituciones de markup ni imports. Los seis bloques `<script>` y todo el contenido ajeno a `<style>` son idénticos byte a byte a main (`60f38626`), con hashes SHA-256 en `030-d-scripts.json`. `PENDING_MIGRATION` está vacía y el guardián lo exige; ninguna excepción nueva, 33 históricas conservadas.

Se recorren por Enter los 8 pasos de reglas, los 4 visibles del índice de equipos y los 3 de fase a ambas resoluciones: 30 instantáneas con idénticos títulos, selección, controles, estados disabled y foco antes/después. El E2E existente `operation-flow` cubre además los tres asistentes completos por Tab/Home/flechas/Enter, alta individual/masiva, fase nueva/existente, asociación/corrección de errores y guardado. No existe un proyecto E2E separado de asistentes.

Las seis composiciones etiquetadas de `030-d-pr/` se revisan visualmente: solo normalización de escala, sin pérdida de pasos, controles ni contenido. Los recortes completos proceden de capturas de página desde scroll inicial para evitar que las barras globales sticky oculten parte del asistente en la evidencia; se conservan también capturas de viewport y del último paso. Resoluciones: 1440×900 y 390×844.

### Axe y mediciones finales

48 ejecuciones de axe-core con **0 violaciones de aplicación**: listado, miembros, configuración, calendario, plantillas y operación programada/en vivo/cerrada (16 ejecuciones), más todos los pasos visibles de los tres asistentes y modo JSON (32 ejecuciones). DevTools se oculta durante la auditoría; no se excluye ninguna regla ni nodo de la aplicación. Datos: `axe-030-d-workspace.json` y `030-d-after/flows.json`.

RF-002: alturas sin navegación global; Y desde el documento. En configuración/calendario/plantillas se usa Copa Demo en su versión publicada; el acceso de alta de partido no corresponde a ese estado.

| Pantalla | Cabecera 1440 | Cabecera 390 | Inicio 1440 | Inicio 390 |
|---|---:|---:|---:|---:|
| Listado | 101 px | 84 px | 310 | 325 |
| Miembros | 101 px | 139 px | 301 | 327 |
| Configuración | 101 px | 108 px | 351 | 461 |
| Calendario | 101 px | 84 px | 351 | 375 |
| Plantillas | 101 px | 139 px | 478 | 596 |

Diez inicios dentro del viewport, un `h1` y ningún overflow horizontal. Operación: hero 101/125 px y MatchBar 70/66 px (escritorio/móvil); primera acción móvil Y=790,5 en programado y en vivo, ninguna acción editable en cerrado. PR C conserva la verificación específica de guardar planilla frente a Y=2521 y revisar cierre frente a Y=4520, visibilidad al scroll, anclas sin JS y foco no tapado.

### Verificación y evidencias

Node **24.22.2**, pnpm **12.12.1**: `pnpm test` **851 tests / 849 pass / 0 fail / 2 skip**; `typecheck`, `lint`, `build` y `typecheck:e2e` con salida **0**. `operation-flow`: **2 passed (43.9s)**, incluidos los asistentes por teclado. Los fixtures de capturas y de esta corrida E2E fueron retirados, incluidos sus equipos y jugadores; no se eliminan fixtures anteriores ni datos demo. Evidencia de limpieza en `030-d-cleanup.log`.

Artefactos persistentes bajo `/home/ubuntu/ui-audit/`: `030-d-{before,after,pr,workspace}/`, `030-d-{scripts,flow-parity,nearest-steps,visual}.json`, `axe-030-d-workspace.json`, `030-d-final-checks.log` y `030-d-final-operation-flow.log`.

**Límites:** verificación en Chromium con viewports emulados, no lector de pantalla ni dispositivos físicos. No se certifican todos los estados de error, todos los roles ni contraste sobre cualquier fondo compuesto. La implementación de 030 queda cerrada; los PR #44/#47/#48 tienen CI verde, pero el gate E2E de CI de PR D solo se ejecutará al abrirlo. Una suite local verde no se presenta como resultado de ese gate.

## 12. Público 031 — PR B, T5–T8 (2026-11-11)

Resultados históricos de B; la aceptación conjunta y el pendiente de su arnés sintético se revisan en la sección 13.

- Veinte vistas reales antes/después, Chromium a 1440×900 y 390×844, axe-core 4.10.3: portada, detalle, bracket, jugadores, equipos, fase, formación gráfica/textual, clasificación y partidos. Cero violaciones de app después; dos apariciones previas de `scrollable-region-focusable` en la misma clasificación móvil. Sin excluir reglas ni nodos de la app; DevTools oculto.
- Cero overflow de documento y errores de página en la pasada real. Estadísticas móviles: jugadores 752/278 px y equipos 528/278 px, con Posición/identidad/Goles o GF completas. Desktop: 8/6 columnas completas. Clasificación 760/320 px en móvil, 11 columnas completas en desktop; pista móvil, región nombrada con foco y equipo sticky opaco (desviación 0 px al extremo).
- Ocho anclas sin JavaScript: destinos visibles y foco en el destino. Clasificación recibe flechas y outline visible; el hint se oculta en desktop, donde la tabla medida no desborda. Continuación real de jugadores 50→96 en ambas resoluciones, con posiciones compartidas y orden intactos.
- Portada: acceso Y=602,89/487,99, marcador «Marcador de ejemplo». Selector del detalle Y=819,86/1117,06→585,86/504,06; acceso temprano Y=498,36/332,25. Las tarjetas de portada no se adelantan: en móvil pasan de Y=1130,45 a 1202,74; el acceso directo cumple la alternativa aprobada. Equipos completos, registro y documentación permanecen disponibles.
- Revisión visual: composiciones etiquetadas `/home/ubuntu/ui-audit/031-b-pr/`; datos y axe en `031-b-{before,after}/measurements.json`, contratos en `contracts.json`, teclado/anclas/continuación en `031-b-interactions.json`. Cuatro scripts idénticos a main salvo import (`031-b-scripts.json`); seis lecturas, queries, campos y rank/orden observados sin cambios. Ninguna excepción 029 nueva.
- Límites: sin lector de pantalla ni dispositivos físicos. El arnés adicional con respuestas de equipos simuladas no completó paginación/vacío/error; no se declara verde. El devserver emitió repetidamente `[NUXT_E1001] A composable that requires access to the Nuxt instance was called outside of a plugin, Nuxt hook, Nuxt middleware, or Vue setup function.` Node 24.22.2/Nuxt 4.6.4 y separación de volúmenes verificados; reinicio local sin eliminar el aviso, sin cambiar lógica fuera del alcance. Casos negativos conservan cobertura unitaria; aceptación global y arnés público persistente de T9/T10 pendientes. Dos fixtures E2E retirados por sus IDs; contadores finales cero.

## 13. Público 031 — PR C, aceptación local T9–T10 (2026-11-11)

- 48 ejecuciones axe-core 4.10.3: treinta vistas reales (diez por viewport), quince cuadros reales y tres presentaciones de penales simulados; 1440×900, 390×844 y 800×900. Cero violaciones de aplicación, `scrollable-region-focusable`=0, sin excluir reglas/nodos de app. DevTools separado; cero overflow de documento y errores de página en la pasada real.
- Demo 8 y temporales 4/8/16/5: 42/42 conectores dibujados/deducibles, cero falsos/solapes, centrado Y=0 px; W.O. y pendientes reales, cinco equipos con tres byes. Penales 1–1/5–4 **simulados**, no cierre real del backend.
- Arnés persistente anónimo `e2e/public-polish.spec.ts`: 21 tests verdes, ambos tipos de estadísticas con 50→53 filas, empates, filtros reversibles, carga retenida/deshabilitada, vacío, 503 y recuperación. El pendiente sintético de B queda cubierto por navegación cliente hidratada, sin atribuir retrospectivamente una causa confirmada a NUXT_E1001 ni cambiar lógica de app. Regresión específica de pista y sticky a 800 px; identidad/flechas, anclas, formación publicada/textual, Escape y retorno de foco.
- Contratos públicos reales comparados con la referencia B: mismas lecturas/parámetros/campos/rank/orden. El comparador se ajustó para admitir el tercer viewport adicional, manteniendo igualdad de las muestras anteriores. Sin API, permisos, campos ni escalas nuevos.
- Medidas, RF-001–019, criterios de finalización, constitución §4, comandos/salidas y límites en [verificación 031](../specs/031-pulido-vistas-publicas/verificacion.md). Capturas/JSON en `/home/ubuntu/ui-audit/031-after/`; composiciones etiquetadas revisadas en `031-c-pr/{jugadores-mobile,clasificacion-mobile,bracket-16-desktop}.png`, antes en `031-before/`. Fixtures retirados por IDs con contadores finales cero.
- Límites: Chromium emulado, sin lector de pantalla ni dispositivo físico; no se certifican todos los zooms o escenarios arbitrarios. T10 y validación cerradas: CI del PR #52 verde, incluido el [job E2E](https://github.com/edsel9ra/bracket-craft/actions/runs/43076141163/job/130716366488) con las 21 públicas nuevas dentro de 26 passed (3.1m); revisión aprobada por el usuario el 2026-11-11. La fusión queda a cargo del usuario.
