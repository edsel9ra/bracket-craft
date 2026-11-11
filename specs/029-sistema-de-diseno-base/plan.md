# Plan 029 — Sistema de diseño base

Spec: `specs/029-sistema-de-diseno-base/spec.md` (aprobada el 2026-11-11). Solo frontend: sin cambios de backend, API, esquema, permisos ni proyecciones públicas.

## 1. Archivos y responsabilidades

| Archivo | Responsabilidad | RF |
|---|---|---|
| `frontend/app/assets/css/tokens.css` (nuevo) | Escalas como propiedades CSS: `--text-*` (8), `--space-*` (10), `--radius-*` (4 + `--radius-pill`), paleta `--color-*` con los semánticos, `--font-sans`, `--font-display` y `--font-mono`. Lo importa `main.css` en primer lugar. | RF-001–005, RF-009 |
| `frontend/app/assets/css/fonts.css` (nuevo) | `@font-face` de Archivo variable (ejes `wght` + `wdth`, subconjunto latino y `font-display: swap`) y una cara de sustitución `Archivo Fallback` sobre Arial con `size-adjust`/`ascent-override` para que el cambio de fuente no desplace el contenido. | RF-007, RF-008 |
| `frontend/app/utils/designTokens.ts` (nuevo) | Fuente única en TypeScript de escalas, puntos de corte (`sm 480`, `md 760`, `lg 1000`, `xl 1280`) y pares de contraste. Funciones puras `contrastRatio(fg, bg)` y `nearestStep(value, scale)`. | RF-001–005, RNF-004 |
| `frontend/app/components/ui/Button.vue` | `variant: primary\|secondary\|danger\|ghost`, `busy`, `disabled`, `as` (botón o `NuxtLink`). Con `busy` queda `aria-busy` e ignora clics. | RF-010 |
| `frontend/app/components/ui/Surface.vue` | `level: 1\|2\|3`, `as`; sustituye los `.panel`/`*-card` locales. | RF-011 |
| `frontend/app/components/ui/StatusPill.vue` | `tone: neutral\|success\|warning\|danger\|live` + texto obligatorio por slot. | RF-012 |
| `frontend/app/components/ui/Tabs.vue` | Patrón WAI-ARIA de pestañas (`tablist`/`tab`/`tabpanel`, tabulador itinerante, flechas e Inicio/Fin) con `v-model`. | RF-013 |
| `frontend/app/components/ui/DataTable.vue` | Envoltorio de `<table>` con `caption` y `scope`, dentro de `HorizontalScroll` (PR #40). | RF-014 |
| `frontend/app/components/ui/StateMessage.vue` | `kind: empty\|loading\|error`, con `role="status"` o `role="alert"` y evento `retry` opcional. | RF-015 |
| `frontend/app/components/ui/ConfirmDialog.vue` | Diálogo sobre `<dialog>` nativo con `showModal()` (foco atrapado e `inert` del fondo los da el navegador), Escape como cancelar, foco inicial en «Cancelar» si es de peligro, devolución del foco y animación que respeta reduced-motion. | RF-017–020, RNF-007 |
| `frontend/app/composables/useConfirm.ts` | `confirm({ title, message, confirmLabel, tone }) → Promise<boolean>`. Cola de una sola petición abierta (una segunda llamada espera a que se resuelva la primera) y doble clic con un único resultado. Se cierra como `false` al cambiar de ruta. | RF-017–019, casos límite |
| `frontend/app/app.vue` | Monta una sola instancia de `ConfirmDialog` conectada a `useConfirm`. | RF-017 |
| Pantallas (ver §3) | Sustituyen valores literales por tokens y las piezas locales por las de `ui/`; los 19 `window.confirm` pasan a `await confirm(...)`. | RF-016, RF-021–023 |
| `frontend/app/composables/useI18n.ts` | Títulos y verbos del diálogo (es/en) por acción, por ejemplo `confirm.publish.title` / `confirm.publish.action` «Publicar versión». El mensaje actual se conserva como consecuencia. | RF-017 |
| `frontend/tests/design-scales.test.ts` (nuevo) | Recorre los `.vue`/`.css` migrados y falla si hay `font-size`, `border-radius`, `gap`/`padding`/`margin`, colores hexadecimales o `@media` fuera de escala, salvo la lista blanca `DESIGN_EXCEPTIONS` (archivo + propiedad + motivo). Las pantallas MG-1 (operación y asistentes) figuran como `PENDING_MIGRATION` y quedan fuera del recorrido. | RF-006, RNF-002 |
| `frontend/tests/no-native-dialogs.test.ts` (nuevo) | Falla si aparece `confirm(`, `alert(` o `prompt(` sobre `window` en `app/`. | RF-021 |
| `frontend/tests/confirm-dialog.test.ts`, `ui-pieces.test.ts` (nuevos) | Lógica pura de `useConfirm` (cola, doble resolución, cancelar al navegar) y contratos de props y ARIA de las piezas (inspección de plantilla, como los tests actuales). | RF-010–020 |
| `frontend/tests/design-contrast.test.ts` (nuevo) | Comprueba 4.5:1 en los pares de texto y 3:1 en los de texto grande y componentes de la paleta. | RNF-004 |
| `frontend/e2e/operationFlow.ts` | Los 2 `page.once('dialog')` pasan a pulsar el botón de confirmar del diálogo propio por su rol y nombre. | caso límite E2E |
| `docs/inspeccion-accesibilidad.md`, `AGENTS.md`, `MEMORY.md` | Revisión con contraste medido; convención de tokens y piezas `ui/` y prohibición de diálogos nativos. | criterio §4 doc |

## 2. Escalas propuestas (derivadas del uso actual)

- **Texto (8):** `2xs 0.6875rem` · `xs 0.75rem` · `sm 0.8125rem` · `md 0.875rem` · `base 1rem` · `lg 1.25rem` · `xl clamp(1.75rem, 4vw, 2.75rem)` · `display clamp(2.5rem, 7vw, 6.5rem)`. Los 40 tamaños actuales se asignan con `nearestStep`. Los que bajan de 0.6875rem solo se conservan en el campo de juego, como excepción (RF-006).
- **Espaciado (10):** `1 4px` · `2 8px` · `3 12px` · `4 16px` · `5 20px` · `6 24px` · `7 32px` · `8 48px` · `9 64px` · `10 80px`. Concentra el 80 % del uso actual (12, 10, 8, 14, 16, 18 px…).
- **Radios (4 + píldora):** `sm 8px` · `md 12px` · `lg 20px` · `xl 28px` · `pill 999px`; el 50 % de los avatares se mantiene como `pill`.
- **Paleta:** la actual (`ink`, `muted`, `surface*`, `line`, `accent`, `accent-ink`, `danger`) más `warning #ffcb7a`, `success`, `home` (acento) y `away` (`#ffcb7a`). Los 9 hexadecimales fijos se asignan a estos tokens o al color existente más cercano.
- **Puntos de corte (4):** 480 / 760 / 1000 / 1280 px. Los 10 actuales se asignan al más cercano.

## 3. Alcance de la migración (MG-1)

**Se migran:** `pages/index.vue`, `pages/tournaments/[id].vue`, `components/public/*`, `login.vue`, `auth/callback.vue`, `account/google.vue`, `organization.vue`, `invitations/[token].vue`, `forbidden.vue`, `admin/index.vue`, `workspace/index.vue`, `workspace/members.vue`, `workspace/tournaments/[id]/{calendar,rosters}.vue`, la parte de página de `workspace/tournaments/[id]/index.vue` (resumen, checklist, escudos y selector de versión), `WorkspaceShell.vue`, `LanguageSwitcher.vue`, `TeamCrest.vue` y `FormatWarning.vue`.

**No se migran (opción 3):** `workspace/matches/[id].vue`, `RulesEditor.vue`, `rules/RulesWizard.vue`, `TeamsWizard.vue`, `StageTeamsWizard.vue` y `wizard/*`. Sí reciben `useConfirm`.

## 4. Algoritmo del diálogo (pseudocódigo)

```
useConfirm():
  state = useState('confirm', { open:false, options:null, resolve:null })
  confirm(options):
    await pendingDone                      # una sola abierta
    return new Promise(res => state = { open:true, options, resolve:res })
  settle(value):
    if !state.resolve: return              # doble clic → un solo resultado
    r = state.resolve; state = closed; r(value)
  router.beforeEach(() => settle(false))   # navegar cancela

onBeforeRouteLeave(async to => ... return await confirm(...))   # los guards admiten promesas
onVersionChange: el select vuelve al valor anterior y solo cambia tras confirmar = true
```

## 5. Decisiones y alternativas descartadas

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Archivo vía la dependencia `@fontsource-variable/archivo` (OFL-1.1, v5.3.0), con solo `archivo-latin-wdth-normal.woff2` (**90 kB**, ejes peso + ancho) importado desde `fonts.css` y empaquetado por Vite en el propio origen | Copiar los woff2 a `public/` | La dependencia queda en el lockfile, pasa por `pnpm audit` y Dependabot, y se sirve igualmente desde el propio origen (CSP intacta, RNF-006) |
| Una sola fuente variable (`wdth`) para texto y titulares | Dos archivos (`wght` 35 kB + condensada aparte) | 90 kB < 120 kB (RNF-005), una sola petición; el ancho condensado se usa con `font-stretch` |
| `<dialog>` nativo con `showModal()` | Modal con `div` y foco atrapado a mano | El navegador ya hace `inert` del fondo, la capa superior y Escape; menos código y menos errores de accesibilidad |
| Composable con promesa e instancia única | Componente por pantalla con `v-if` | Sustitución mecánica de `if (!window.confirm(x)) return` por `if (!(await confirm(x))) return`, sin duplicar el markup |
| Tokens en CSS + espejo TS testeado | Solo CSS | El test de escalas y el de contraste necesitan los valores. Un test comprueba que ambos coinciden. |
| Guardián estático de escalas | Stylelint | No añade dependencia ni configuración nueva, y sigue el patrón de `ui-component-imports.test.ts` |
| Capturas antes/después en el PR (RV-1) | Regresión visual en CI | Decisión del usuario |

## 6. Estrategia de tests

- Unitarios puros: `designTokens` (contraste y paso más cercano), `useConfirm` (cola, una sola resolución, cancelar al navegar).
- Guardianes estáticos: escalas, ausencia de diálogos nativos, contratos ARIA de las piezas e importaciones explícitas de `ui/` (el test existente las cubre).
- E2E: `operationFlow` con el diálogo propio (publicar y cerrar acta) en el job `e2e` de CI.
- Manual con evidencia: axe-core sobre las páginas del informe y capturas antes/después (1440×900 y 390×844) adjuntas al PR.
- Siempre: `pnpm test`, `pnpm run typecheck`, `pnpm run lint`, `pnpm run build`, `pnpm run typecheck:e2e`.

## 7. Frontend y exposición pública

- No hay llamadas HTTP nuevas; las existentes siguen pasando por `useApi.ts`.
- Rutas públicas y del Workspace sin cambios de acceso. Ninguna proyección pública cambia (spec 020 intacta).
- No hay variables de entorno nuevas.

## 8. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 1–2 RLS y privilegios de BD | No | Sin cambios de backend ni BD |
| 3 Lo publicado es inmutable | Sí (indirecto) | El diálogo solo envuelve acciones existentes; publicar y cerrar siguen igual (RF-019) |
| 4 Esquema append-only | No | Sin migraciones |
| 5 Lo público es proyección mínima | Sí | Cambios solo de presentación; sin campos nuevos (RF-023) |
| 6 Sin secretos por defecto | No | Sin configuración nueva |
| 7 Admin separada y auditada | Sí (indirecto) | `/admin` cambia solo de estilo; la desactivación sigue el mismo flujo con diálogo propio |
| 8 Nada terminado sin verificación | Sí | Tests, guardianes, CI, axe y capturas; lo no verificado se declara |
| 9 Código de desarrollo fuera de producción | No | Sin seeds ni scripts nuevos |
| §3.3 `useApi.ts` y rutas públicas sin sesión | Sí | Sin llamadas nuevas ni cambios de acceso |
| §4 CI verde (frontend, security, e2e) | Sí | RNF-001 |
| §4 Sin secretos ni datos personales | Sí | Solo código y fuente OFL |
| §4 Documentación afectada | Sí | AGENTS.md (convención `ui/` + tokens), inspección de accesibilidad, MEMORY.md |
| §4 Pruebas del comportamiento nuevo | Sí | §6 |
| §4 Dependencias: lockfile y auditorías | Sí | `@fontsource-variable/archivo` en `pnpm-lock.yaml`; `pnpm audit` con el filtro de la constitución |
| §4 Frontend: `pnpm test`, `typecheck`, `build` | Sí | RNF-001 |
