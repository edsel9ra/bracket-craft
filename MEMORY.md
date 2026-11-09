# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas.

## Estado
- Mantenimiento de auditoría (2026-11-09): ESLint gradual, Bandit con supresiones locales revisadas y Gitleaks sobre árbol versionado; Redis compartido para rate limit/readiness; migración **032** para revalidación de sockets en una llamada con RLS. Detalles: `docs/mantenimiento-auditoria.md`.
- 2026-11-04 · Spec 001 (cambio posterior) · RF-006 enmendado: `api` y `storage` también se unen a la red del proxy, porque el navegador llama directamente a la API, a Socket.IO y a las fotos y `web` no hace de proxy. Aprobado por Edson.
- **Specs 020–024 implementadas y aprobadas** por el reviewer. Introdujeron las migraciones 026–031 sin rollback (*forward-fix*); mantenimiento añade **032**.
- **025 (recorrido de configuración) implementada y aprobada**: orden reglas → equipos → fases; rótulos «01 · Reglas»…«04 · Calendario» (es/en); ancla `#fases` (sin entrada en el índice, sección activa Configuración); `phasesAssistantHref` → `/workspace/tournaments/{id}#fases` sin `?step=`; manual renumerado (3 reglas, 4 equipos y plantillas, 5 fases, 6 calendario); README y AGENTS con las cuatro anclas. `pnpm test` 716 pass, typecheck y build OK. Sin cambios de backend/esquema.
- **026 (cadena de avance y cifra) implementada y aprobada**: cadena Reglas → Equipos → Fases → Calendario solo con guardado efectivo; aviso de minutos con «Continuar»/«Quedarme» (aparece solo tras el `PATCH` correcto); cifra de composición = inscritos ∪ seleccionados sin recorte («0 de 64» en el alta, sin cifra mientras cargan los inscritos en «fase existente»); `StageTeamsWizard` emite `confirmed` solo en confirmación efectiva; sin nueva API, migración ni permiso. `pnpm test` 743 pass / 0 fail / 1 skip; typecheck, build y typecheck:e2e OK; arnés E2E no ejecutado (contenedor Vite 500) — declarado no ejecutado, nunca verde.
- **027 (reestructuración del alta de equipos) implementada**: paso `teams.entry` como primer paso obligatorio; `teams.bulk` con `showInIndex: false`; `name`/`shortCode` opcionales validados solo en vía individual; clasificación de `teams.details` en vía masiva (completo/error/omitido/incompleto) sin bloquear; confirmación filtrada en vía masiva. T010 añade tests de integración del flujo completo. `pnpm test` 755 pass / 0 fail; typecheck OK.
- **028 (propagación de formaciones entre segmentos) implementada y verificada (T6)**: `deriveLineupSource` en `frontend/app/utils/lineupSource.ts`; precarga por equipo en `syncTacticalEditor`; independencia por equipo y estado de publicación; omisión en terminales/no publicados. Cambio de segmento descarta ediciones y recarga; guardar persiste solo en el segmento destino; un único segmento no cambia. `pnpm test` 772 pass / 0 fail; typecheck y build OK.
- Las verificaciones anteriores de specs 025–028 son resultados históricos, no resultados de la ronda actual.
- Las specs 025–028 están materializadas en git: `890b280`, `0977a26` y `e5df755`; `main` incluye además `a30be0a` (PR #24). La nota anterior «sin commitear» era obsoleta.
- UI de escudos en Workspace: grilla centrada con tarjetas de ancho máximo ~320 px; botones «Cambiar escudo»/«Eliminar escudo» con altura y ancho equitativos; selector muestra «Cambiar escudo» cuando hay escudo y «Subiendo…» durante la carga; auto-carga al seleccionar sin botón de subida.

## Mejora de formularios (estado histórico incorporado en main)
- Plantillas: `.roster-list` reorganizado como grilla auto-fit de tarjetas (minmax 280px, gap 12px, borde + hover sutil) en `rosters.vue`, con colapso a una columna en ≤620px. Solo CSS scoped, sin cambios de markup ni de contrato.
- Piloto + Workspace aplicados con `.field`/`FormField`/`FieldError` y `validation.*` (es/en). Wizards conservan validación por paso. Refactor con `FormField` pendiente en `matches/[id]` y wizards por alto riesgo.

## Entorno local
- Backend `python:3.14-slim`; frontend en contenedor `web` (Node 24/pnpm 12.12.1); E2E en Playwright. El host no tiene `pytest` ni Node con TS: usa los contenedores. Para la suite backend monta el repo en `/repo`.

## E2E: cambios confirmados y límites de la evidencia
- `4eba00b` («Fix e2e») modifica `labels.ts` y `operationFlow.ts`; `0977a26` adapta después el arnés al flujo de alta de equipos de la spec 027. Son cambios commiteados, no trabajo pendiente de commit.

- La sesión anterior registró una corrida local detenida en `jugador-inscrito-7` por timeout de hidratación (240 s). No se conserva aquí evidencia que confirme su causa; se retira la atribución a rendimiento del contenedor. El historial git no prueba un E2E verde. En mantenimiento no se ejecuta E2E completo ni se declara resuelto ese resultado histórico.

## Spec 028 — Propagación de formaciones por segmento (verificada)
- Estado: implementada y validada (APROBADO). T1-T6 completas.
- Cambio frontend-only: precarga en el editor de operación la formación y posiciones del primer segmento con formación (por equipo) cuando el segmento seleccionado no tiene la suya, como punto de partida editable; no compartida.
- Archivos: frontend/app/utils/lineupSource.ts (nuevo), frontend/tests/lineup-source.test.ts (17 tests), frontend/app/pages/workspace/matches/[id].vue (syncTacticalEditor).
- Verificación: pnpm test 772 pass, typecheck exit 0, build exit 0.
