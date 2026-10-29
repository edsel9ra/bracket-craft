# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas.

## Estado
- **Specs 020–024 implementadas y aprobadas** por el reviewer. Cadena de esquema en **031** (migraciones 026–031 sin rollback, *forward-fix*).
- **025 (recorrido de configuración) implementada y aprobada**: orden reglas → equipos → fases; rótulos «01 · Reglas»…«04 · Calendario» (es/en); ancla `#fases` (sin entrada en el índice, sección activa Configuración); `phasesAssistantHref` → `/workspace/tournaments/{id}#fases` sin `?step=`; manual renumerado (3 reglas, 4 equipos y plantillas, 5 fases, 6 calendario); README y AGENTS con las cuatro anclas. `pnpm test` 716 pass, typecheck y build OK. Sin cambios de backend/esquema.
- **026 (cadena de avance y cifra) implementada y aprobada**: cadena Reglas → Equipos → Fases → Calendario solo con guardado efectivo; aviso de minutos con «Continuar»/«Quedarme» (aparece solo tras el `PATCH` correcto); cifra de composición = inscritos ∪ seleccionados sin recorte («0 de 64» en el alta, sin cifra mientras cargan los inscritos en «fase existente»); `StageTeamsWizard` emite `confirmed` solo en confirmación efectiva; sin nueva API, migración ni permiso. `pnpm test` 743 pass / 0 fail / 1 skip; typecheck, build y typecheck:e2e OK; arnés E2E no ejecutado (contenedor Vite 500) — declarado no ejecutado, nunca verde.
- Backend `pytest -q`: sin cambios en esta ronda (no se tocó backend). Pruebas frontend puras: navigation 28/28, stage-teams, rules-minutes, stage-composition, section-advance en verde.
- Todo el trabajo sigue **sin commitear** sobre `main`; abrir rama + PR.

## Mejora de formularios (en curso)
- Piloto + Workspace aplicados con `.field`/`FormField`/`FieldError` y `validation.*` (es/en). Wizards conservan validación por paso. Refactor con `FormField` pendiente en `matches/[id]` y wizards por alto riesgo.

## Entorno local
- Backend `python:3.14-slim`; frontend en contenedor `web` (Node 24/pnpm 12.12.1); E2E en Playwright. El host no tiene `pytest` ni Node con TS: usa los contenedores. Para la suite backend monta el repo en `/repo`.
