# Tareas 030 — Rediseño del Workspace

Comandos en `frontend/` con node:24 y pnpm 12.12.1.

**PR A**
- [ ] **T1. `PageHeader` y cabeceras compactas** en el listado, miembros, calendario y plantillas (la operación y la configuración la reciben en T3/T5). RF-001–003
  - Hecho cuando: el test de un `h1` por página pasa y las capturas muestran el contenido principal en la primera pantalla a 1440 y 390.
  - Implementación parcial: cabeceras de 101 px escritorio/84 px móvil y un `h1` verificados. Las listas de plantillas (ambas resoluciones), calendario móvil y miembros móvil siguen bajo el pliegue por los formularios previos; pendiente autorizar su reordenación para RF-002. Evidencias: `/home/ubuntu/ui-audit/030-a-{before,after}/`.
- [x] **T2. `featureSource()`** en `tests/support/sources.ts` y los 23 tests estáticos migrados a ella, sin cambiar aserciones. RNF-005
  - Hecho cuando: `pnpm test` pasa con el mismo número de tests.
  - Suite existente: 826 antes/826 después; total 831 al añadir cinco tests de layout/recorrido de fuentes (829 pass, 2 skip). 22 lecturas explícitas y el lector genérico de páginas migrados en 17 archivos; aserciones conservadas.
- [x] **T3. División de la configuración** (`useTournamentSetup` + `components/workspace/setup/*`), con `PageHeader`. RF-011, RF-012
  - Hecho cuando: ningún archivo pasa de 600 líneas (la página ≤ 250), y pasan `pnpm test`, `typecheck` y el E2E `operation-flow` local.
  - Página: 123 líneas; composable principal: 597. Las 38 funciones originales mantienen cuerpo idéntico sin contar whitespace; asistentes sin cambios. Node 24/pnpm 12.12.1: test, typecheck, lint, build y typecheck:e2e correctos; E2E local 2 passed. Logs externos: `/home/ubuntu/ui-audit/030-a-verified.log`, `030-a-operation-flow-final.log`.

**PR B**
- [ ] **T4. Script de la operación a `useMatchOperation`** (y sub-composables si hace falta). La plantilla no cambia. RF-010, RF-012
  - Hecho cuando: pasan `pnpm test`, `typecheck` y el E2E local, y las capturas no muestran diferencias.
- [ ] **T5. Plantilla de la operación en `components/match/*`** por sección, con `provide/inject` tipado y `PageHeader`. RF-010
  - Hecho cuando: ningún archivo pasa de 600 líneas (la página ≤ 250) y pasan los tests, `typecheck` y el E2E local.

**PR C**
- [ ] **T6. `MatchBar` + `matchScoreDisplay`**: marcador, estado y nombres sin partir. RF-004, RF-005, RF-008
  - Hecho cuando: los tests puros pasan y las capturas cubren los estados programado, en vivo y cerrado, y un nombre largo.
- [ ] **T7. `MatchSectionNav` + `MatchActionBar` + `primaryAction`**, con scroll-padding y ocultación con el teclado virtual. RF-006, RF-007, RNF-003, RNF-004
  - Hecho cuando: los tests puros y de ARIA pasan, la medición muestra una distancia a la acción ≤ 60 % del inventario y el E2E local pasa.
- [ ] **T8. Escalas en la operación**: se quita de `PENDING_MIGRATION`. RF-013
  - Hecho cuando: el guardián pasa, y también `lint` y `build`.

**PR D**
- [ ] **T9. Escalas en los asistentes** (solo estilos): `PENDING_MIGRATION` queda vacía. RF-013, RF-014
  - Hecho cuando: el guardián recorre todo `app/` y el E2E de los asistentes por teclado pasa.
- [ ] **T10. Validación y documentación**: axe a 1440 y 390, mediciones RF-002 y RNF-004, `AGENTS.md`, `docs/inspeccion-accesibilidad.md` y `MEMORY.md`. RNF-001–004
  - Hecho cuando: hay cero violaciones nuevas de aplicación y CI está en verde.

Son 10 tareas, el límite que recomienda la skill SDD, así que no hace falta dividir la spec. Cada PR mantiene verde el E2E de operación.
