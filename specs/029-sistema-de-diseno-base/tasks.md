# Tareas 029 — Sistema de diseño base

Comandos en `frontend/` dentro de un contenedor `node:24` con pnpm 12.12.1.

- [x] **T1. Tokens y escalas.** `tokens.css` + `designTokens.ts` (escalas, paleta, puntos de corte, `contrastRatio`, `nearestStep`) y tests de coincidencia CSS↔TS y de contraste. RF-001–005, RNF-004
  - Hecho cuando: `pnpm test` pasa con `design-contrast.test.ts` en verde y sin cambios visuales (todavía no se usan los tokens).
- [x] **T2. Tipografía Archivo.** Dependencia `@fontsource-variable/archivo`, `fonts.css` con `@font-face` latino `wdth` + cara de sustitución, y `--font-sans`/`--font-display` en `body` y titulares. RF-007–009, RNF-005, RNF-006
  - Hecho cuando: `pnpm run build` pasa; un test comprueba que el woff2 emitido pesa ≤ 120 kB y que la CSP no cambió (`security-headers.test.ts`); la auditoría frontend de la constitución pasa.
- [x] **T3. Piezas base: Button, Surface, StatusPill y StateMessage.** RF-010–012, RF-015
  - Hecho cuando: `pnpm test` pasa con `ui-pieces.test.ts` (variantes cerradas, `aria-busy`, roles status/alert, texto obligatorio en la píldora) y con `ui-component-imports.test.ts`.
- [x] **T4. Piezas Tabs y DataTable.** RF-013, RF-014
  - Hecho cuando: los tests de teclado (flechas, Inicio/Fin, tabulador itinerante) y de cabeceras con `scope` pasan; `pnpm run typecheck` pasa.
- [x] **T5. Diálogo de confirmación.** `ConfirmDialog.vue` + `useConfirm.ts` + montaje en `app.vue` + textos i18n es/en. RF-017–020, RNF-007
  - Hecho cuando: `confirm-dialog.test.ts` (cola, una sola resolución, cancelar al navegar, foco inicial en Cancelar si es de peligro) pasa.
- [x] **T6. Sustituir los 19 `window.confirm`** (incluidos la operación de partido y los asistentes) y adaptar los 2 pasos del E2E. RF-019, RF-021
  - Hecho cuando: `no-native-dialogs.test.ts` pasa, `pnpm test`, `pnpm run typecheck:e2e` y `lint` pasan, y el job `e2e` de CI pasa.
  - Verificación local: tests 822 pass/0 fail/2 skip; typecheck, lint, build y typecheck:e2e OK; E2E `operation-flow` 2 pass (publicación y cierre con el diálogo propio). CI pendiente de abrir el PR; no se declara verificada.
- [x] **T7. Migrar las vistas públicas** (portada, detalle del torneo, `components/public/*`, `LanguageSwitcher`, `TeamCrest`). RF-016, RF-022
  - Hecho cuando: `design-scales.test.ts` las recorre sin violaciones fuera de `DESIGN_EXCEPTIONS` y existen capturas antes/después a 1440 y 390 px.
  - Verificación local: 824 pass/0 fail/2 skip; typecheck, lint, build y typecheck:e2e OK (Node 24, pnpm 12.12.1). Guardián con 24 excepciones específicas y 21 entradas pendientes, impresas por el test. Los estilos globales compartidos de `main.css` quedan pendientes de T9, sin migrar pantallas privadas.
  - Capturas: `/home/ubuntu/ui-audit/029-before/` (32) y `029-after/` (12), comparadas visualmente en ambas resoluciones. Se corrigieron la reducción excesiva de los titulares y el apilado de cabeceras a 390px. Excepciones VI-1 para conservar la composición fluida de los heroes y el marcador ilustrado; restantes diferencias de escala y mezcla de colores sobre tokens.
  - Límites del baseline: el demo redirige organización al Workspace y administración a 403; invitación capturada en estado inválido (no se obtuvo enlace válido). El demo de eliminación directa no presenta clasificación de liga. Sin axe nuevo ni CI; T8–T10 siguen pendientes.
- [ ] **T8. Migrar autenticación, cuenta, organización, invitación, 403, administración y miembros.** RF-016, RF-022
  - Hecho cuando: como en T7, para estas pantallas.
- [ ] **T9. Migrar el Workspace** (`WorkspaceShell`, listado, calendario, plantillas, parte de página de la configuración y `FormatWarning`). RF-016, RF-022
  - Hecho cuando: como en T7; los archivos MG-1 figuran en `PENDING_MIGRATION`.
- [ ] **T10. Validación y documentación.** axe-core en las páginas del informe, contraste registrado en `docs/inspeccion-accesibilidad.md`, convención en `AGENTS.md` y cierre en `MEMORY.md`. RNF-001–004, criterios de finalización
  - Hecho cuando: `pnpm test`, `typecheck`, `lint` y `build` pasan; axe no muestra violaciones nuevas frente al PR #40; CI está en verde.

Son 10 tareas, el límite que recomienda la skill SDD; no se propone dividir la spec. Se entregarán en 3 PR: T1–T5 (base), T6 (diálogos) y T7–T10 (migración).
