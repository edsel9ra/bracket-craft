# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas.

## Estado
- **Specs 020–024 implementadas y aprobadas** por el reviewer. Cadena de esquema en **031** (migraciones 026–031 sin rollback, *forward-fix*).
- **025 (recorrido de configuración) implementada y aprobada**: orden reglas → equipos → fases; rótulos «01 · Reglas»…«04 · Calendario» (es/en); ancla `#fases` (sin entrada en el índice, sección activa Configuración); `phasesAssistantHref` → `/workspace/tournaments/{id}#fases` sin `?step=`; manual renumerado (3 reglas, 4 equipos y plantillas, 5 fases, 6 calendario); README y AGENTS con las cuatro anclas. `pnpm test` 716 pass, typecheck y build OK. Sin cambios de backend/esquema.
- **026 (cadena de avance y cifra) implementada y aprobada**: cadena Reglas → Equipos → Fases → Calendario solo con guardado efectivo; aviso de minutos con «Continuar»/«Quedarme» (aparece solo tras el `PATCH` correcto); cifra de composición = inscritos ∪ seleccionados sin recorte («0 de 64» en el alta, sin cifra mientras cargan los inscritos en «fase existente»); `StageTeamsWizard` emite `confirmed` solo en confirmación efectiva; sin nueva API, migración ni permiso. `pnpm test` 743 pass / 0 fail / 1 skip; typecheck, build y typecheck:e2e OK; arnés E2E no ejecutado (contenedor Vite 500) — declarado no ejecutado, nunca verde.
- **027 (reestructuración del alta de equipos) implementada**: paso `teams.entry` como primer paso obligatorio; `teams.bulk` con `showInIndex: false`; `name`/`shortCode` opcionales validados solo en vía individual; clasificación de `teams.details` en vía masiva (completo/error/omitido/incompleto) sin bloquear; confirmación filtrada en vía masiva. T010 añade tests de integración del flujo completo. `pnpm test` 755 pass / 0 fail; typecheck OK.
- **028 (propagación de formaciones entre segmentos) implementada y verificada (T6)**: `deriveLineupSource` en `frontend/app/utils/lineupSource.ts`; precarga por equipo en `syncTacticalEditor`; independencia por equipo y estado de publicación; omisión en terminales/no publicados. Cambio de segmento descarta ediciones y recarga; guardar persiste solo en el segmento destino; un único segmento no cambia. `pnpm test` 772 pass / 0 fail; typecheck y build OK.
- Backend `pytest -q`: sin cambios en esta ronda (no se tocó backend). Pruebas frontend puras: navigation 28/28, stage-teams, rules-minutes, stage-composition, section-advance en verde.
- Todo el trabajo sigue **sin commitear** sobre `main`; abrir rama + PR.
- UI de escudos en Workspace: grilla centrada con tarjetas de ancho máximo ~320 px; botones «Cambiar escudo»/«Eliminar escudo» con altura y ancho equitativos; selector muestra «Cambiar escudo» cuando hay escudo y «Subiendo…» durante la carga; auto-carga al seleccionar sin botón de subida.

## Mejora de formularios (en curso)
- Plantillas: `.roster-list` reorganizado como grilla auto-fit de tarjetas (minmax 280px, gap 12px, borde + hover sutil) en `rosters.vue`, con colapso a una columna en ≤620px. Solo CSS scoped, sin cambios de markup ni de contrato.
- Piloto + Workspace aplicados con `.field`/`FormField`/`FieldError` y `validation.*` (es/en). Wizards conservan validación por paso. Refactor con `FormField` pendiente en `matches/[id]` y wizards por alto riesgo.

## Entorno local
- Backend `python:3.14-slim`; frontend en contenedor `web` (Node 24/pnpm 12.12.1); E2E en Playwright. El host no tiene `pytest` ni Node con TS: usa los contenedores. Para la suite backend monta el repo en `/repo`.

## Fix E2E (operación y cierre)
- Alineado `frontend/e2e/operationFlow.ts` con la reestructuración de equipos (spec 027): `TEAMS_STEPS` ahora incluye `teams.entry` y omite `teams.bulk` (oculto del índice); el bloque `equipos-creados` elige la vía masiva desde `teams.entry` y carga el CSV en `teams.bulk`. Añadida `teamsStepEntry` en `labels.ts`. `typecheck:e2e` en verde. Causa del `view-timeout` reportado: desfase del arnés con el nuevo flujo. El error secundario `EACCES` sobre `e2e-report/server.log` es un problema de permisos del directorio (root-owned en entorno local), no del código.

## E2E (segunda corrida)
- Tras los fixes, el escenario avanza hasta `roster-lock-absent` y falla en `jugador-inscrito-7` por `waitForHydration` agotando el timeout (240 s). Causa probable: rendimiento del contenedor local al hidratar la página de plantillas tras el alta de equipos, no un desfase de selectores. Pendiente de validar en CI/entorno con más recursos.

## Spec 028 — Propagación de formaciones por segmento (verificada)
- Estado: implementada y validada (APROBADO). T1-T6 completas.
- Cambio frontend-only: precarga en el editor de operación la formación y posiciones del primer segmento con formación (por equipo) cuando el segmento seleccionado no tiene la suya, como punto de partida editable; no compartida.
- Archivos: frontend/app/utils/lineupSource.ts (nuevo), frontend/tests/lineup-source.test.ts (17 tests), frontend/app/pages/workspace/matches/[id].vue (syncTacticalEditor).
- Verificación: pnpm test 772 pass, typecheck exit 0, build exit 0.
