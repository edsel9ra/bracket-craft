# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Specs 020, 021 y 022 implementadas y aprobadas** por el reviewer. Cadena de esquema en **031** (026–031 pendientes de despliegue, sin rollback, *forward-fix*).
- **022**: **T1–T22 cerradas**. Pruebas puras: **73/73 en verde** (`backend/tests/test_public_stats.py`); `vue-tsc --noEmit` y `nuxt build` OK; `compileall` OK. Auditoría frontend: el hallazgo alto de `serialize-javascript` (GHSA-m5mm-p8h7-m29v) resuelto con override `>=7.1.3` y lockfile regenerado; solo queda un bajo en `deepmerge`. Las suites opt-in con PostgreSQL, el frontend `pnpm test` y los jobs `security`/`e2e` siguen **no ejecutados** en este entorno (sin Docker/pytest/Node 24).
- **023 T1–T9 cerradas** + opcionales del reviewer: AGENTS.md referencia `docs/manual-usuario.md` (RNF-006); T1 publica la lista de funciones del inventario backend no cubiertas (RF-028: `canonical_client_event_id`, `normalize_event_metadata`); RF-010 sigue declarado «no ejecutado» (riesgo operativo, sin pila aislada). Backend `pytest -q`: 2144 passed, 471 skipped, 0 failed. No se introdujo código de producto ni cambios de esquema.
- Veredicto del reviewer **no re-ejecutado** tras las correcciones: pendiente para la siguiente vuelta (máximo 2 vueltas; esta es la primera).

## Spec 020 — consulta pública: navegación y acceso (implementada)
- Solo bloques A (navegación por fases/grupos) y E (acceso público). 20 RF. Decisiones P1, P9. Reviewer APROBADO.

## Spec 021 — formaciones gráficas (implementada y aprobada)
- Bloque D. 14 RF. Decisión P10. Reviewer APROBADO. Depende de 020; 022 depende de ella.

## Spec 024 — formatos de juego y planillas (implementada)
- Spec aprobada y plan/tareas aprobados. T1–T10 completados: códigos `FORMATION_NOT_SUPPORTED_FOR_FORMAT` y `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED` (backend), rechazo de publicación/selección/aplicación de formación táctica en no 11v11, rechazo de cambio de formato con formación publicada, retiro del aviso genérico en 3 lugares (frontend) con información contextual veraz, prueba pura `test_format_game_format.py`, `AGENTS.md` actualizado.
- `engine_version` sigue en 2026.1, sin migración ni endpoints nuevos. Verificación: backend 2147 passed (3 nuevos), frontend 710 passed, `docker compose config -q` OK.

## Spec 022 — estadísticas y porterías imbatidas (aprobada)
- Bloques B y C. 36 RF. Decisiones P2–P8. Portería imbatida: estadística derivada con criterio fijo (umbral 60 min), sin excepción §3.2; equipo = cero goles recibidos en partido disputado; portero = `GK` en formación publicada, titular del primer segmento o entrante acreditado, ≥ 60 min; walkover/administrativa no cuentan. RF-033 publica nombres no aditivamente.
- Correcciones aplicadas: proyección interna 031 con todas las formaciones; regla del portero sobre todas las formaciones (16b); `player_in_id` cuenta como participación; retirado sin foto; ámbito torneo completo; columna `rank` con empates 1-2-2-4; `response_model` en los dos endpoints; lista cerrada y aislamiento con datos reales; definiciones es/en; runbooks 029–031.
- Decisiones aprobadas por el usuario: caso 3 = Sí (70 ≥ 60); foto del retirado = iniciales (RF-034 prevalece); excepción §3.2 retirada; bump de dependencias intentado.
- T1: pruebas de migración 029/030 escritas, no ejecutadas (sin PostgreSQL). T21 aplicado: override en `pnpm-workspace.yaml` + lockfile regenerado; solo queda un hallazgo bajo (`deepmerge`).

## Entorno local
- Backend `python:3.14-slim`; frontend en `web` (Node 24/pnpm 12.12.1); E2E en Playwright. El host no tiene `pytest` ni Node con TS: usa los contenedores. Para la suite backend monta el repo en `/repo` (23 pruebas leen la raíz).

## Mejora de formularios (en curso)
- Piloto + Workspace aplicados: `.field` en labels de `rosters`, `calendar`, `index`, `members`, `matches/[id]`, wizards (`RulesEditor`, `StageTeamsWizard`, `TeamsWizard`), `invitations`, `admin`, `account/google`, `workspace/index`.
- Componentes `FormField.vue`/`FieldError.vue` y tokens globales en `main.css`. Claves i18n `validation.*` (es/en) añadidas en `useI18n.ts`. Refactor con `FormField` aplicado a `organization.vue`, `login.vue` (email/password), `members.vue` (invitación), `rosters.vue` (alta individual + validación client-side con `validation.*`), `organization.vue` (validación client-side), `login.vue` (email/password), `members.vue` (email), `calendar.vue` (partido + validación client-side), `admin/index.vue` (búsqueda) e `invitations/[token].vue`. `matches/[id].vue` y wizards (`RulesEditor`, `StageTeamsWizard`, `TeamsWizard`) conservan `.field` en labels y `form-error` en bloques cubiertos por tests de fuente / validación por paso (conversión FormField pendiente por alto riesgo). Formularios usan import explícito de `FormField` y slot props en camelCase (corrección de 500 en login). Mejora de distribución: alta individual de rosters usa `field-grid` (2 columnas); validación client-side con `validation.*`; botón de descarga de plantilla CSV; estilos unificados en botones del roster-list y checkbox de consentimiento. Paginación client-side (10 por página) añadida a miembros e invitaciones (members.vue) con botón Cargar más. Aplicación de `validation.*` extendida a `organization`, `login`, `members`, `calendar`. Los wizards conservan validación por paso con claves específicas (`rules.error.*`, `stage.wizard.error.*`, `teams.wizard.error.*`) y aria; migración a `FormField` pendiente por alto riesgo. `matches/[id]` conserva `.field`/`form-error` por tests de fuente; campos de creación de segmento, interrupción y minuto añadido migrados a `FormField`; barrido de `match-events.test.ts` actualizado para excluir `added_minute`. Formulario de cierre: marcadores (regular/final/penales) migrados a `FormField`; test `match-operation-screen` actualizado para contar `FormField`. Formulario de cierre: marcadores (regular/final/penales) migrados a `FormField`; walkover/administrative conservan `.field`+`form-error` por tests de fuente estrictos.
- Todo el trabajo de las specs 020/021/022 sigue **sin commitear** sobre `main`; abrir rama + PR.
