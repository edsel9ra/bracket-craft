# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Specs 020 y 021 implementadas y aprobadas** por el reviewer; **spec 022 en ronda de corrección** tras veredicto `CAMBIOS NECESARIOS` (17 bloqueantes). Cadena de esquema en **031** (026–031 pendientes de despliegue, sin rollback, *forward-fix*).
- **022**: **T1–T22 cerradas**. Pruebas puras: **73/73 en verde** (`backend/tests/test_public_stats.py`); `vue-tsc --noEmit` y `nuxt build` OK; `compileall` OK. Auditoría frontend: el hallazgo alto de `serialize-javascript` (GHSA-m5mm-p8h7-m29v) resuelto con override `>=7.1.3` y lockfile regenerado; solo queda un bajo en `deepmerge`. Las suites opt-in con PostgreSQL, el frontend `pnpm test` y los jobs `security`/`e2e` siguen **no ejecutados** en este entorno (sin Docker/pytest/Node 24).
- Veredicto del reviewer **no re-ejecutado** tras las correcciones: pendiente para la siguiente vuelta (máximo 2 vueltas; esta es la primera).

## Spec 020 — consulta pública: navegación y acceso (implementada)
- Solo bloques A (navegación por fases/grupos) y E (acceso público). 20 RF. Decisiones P1, P9. Reviewer APROBADO.

## Spec 021 — formaciones gráficas (implementada y aprobada)
- Bloque D. 14 RF. Decisión P10. Reviewer APROBADO. Depende de 020; 022 depende de ella.

## Spec 022 — estadísticas y porterías imbatidas (ronda de corrección)
- Bloques B y C. 36 RF. Decisiones P2–P8. Portería imbatida: estadística derivada con criterio fijo (umbral 60 min), sin excepción §3.2; equipo = cero goles recibidos en partido disputado; portero = `GK` en formación publicada, titular del primer segmento o entrante acreditado, ≥ 60 min; walkover/administrativa no cuentan. RF-033 publica nombres no aditivamente.
- Correcciones aplicadas: proyección interna 031 con todas las formaciones; regla del portero sobre todas las formaciones (16b); `player_in_id` cuenta como participación; retirado sin foto; ámbito torneo completo; columna `rank` con empates 1-2-2-4; `response_model` en los dos endpoints; lista cerrada y aislamiento con datos reales; definiciones es/en; runbooks 029–031.
- Decisiones aprobadas por el usuario: caso 3 = Sí (70 ≥ 60); foto del retirado = iniciales (RF-034 prevalece); excepción §3.2 retirada; bump de dependencias intentado.
- T1: pruebas de migración 029/030 escritas, no ejecutadas (sin PostgreSQL). T21 aplicado: override en `pnpm-workspace.yaml` + lockfile regenerado; solo queda un hallazgo bajo (`deepmerge`).

## Entorno local
- Backend `python:3.14-slim`; frontend en `web` (Node 24/pnpm 12.12.1); E2E en Playwright. El host no tiene `pytest` ni Node con TS: usa los contenedores. Para la suite backend monta el repo en `/repo` (23 pruebas leen la raíz).
- Todo el trabajo de las specs 020/021/022 sigue **sin commitear** sobre `main`; abrir rama + PR.
