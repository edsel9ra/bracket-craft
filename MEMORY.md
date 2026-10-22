# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Sin specs abiertas.** Última cerrada: **011** (2026-10-22). **§6 aprobada** para 004, 005, 008, 009, 010 y 011.
- **Constitución 1.4.0** (job `e2e` en la §4). **`main` protegida:** cinco *required checks*, *strict*, sin force push; los administradores pueden saltar la regla.

## Spec 011 — Cierre de huecos de verificación (cerrada 2026-10-22)
- PR **#7** (`6fa19c3`); CI en verde incluido `e2e` (2m31s). **Sin migraciones ni cambios de producto.**
- **C-2 atómica:** fallo inducido tras materializar → 500, ambas escrituras revertidas, sin auditoría ni correo.
- **Miembro sin rol:** contrato real **403** probado contra el endpoint auténtico; el 200/`viewer`/`[]` exige el rol `viewer` asignado.
- **Sonda de outbox:** `scripts.outbox_probe` + paso 7 del script del worker; solo desarrollo/local, RLS, marcador, presupuesto 120 s y limpieza; sin datos demo → **2** sin escribir.
- **Mensajes de fallo:** 37 migrados a `describe_response` (lista blanca de `code`); las 3 comprobaciones de contenido intactas.
- **Artefactos E2E:** `transitions` aditivo (`schemaVersion` 1), captura solo en fallo, `server.log` disponible con cabecera **y** contenido, fallback de CI que no reescribe.
- Evidencia: backend **1074 passed** con base 023; frontend **247 tests**, typecheck/typecheck:e2e/build; E2E verde con `server.log` de 236 líneas y sin capturas.

## Spec 010 — E2E del reintento (cerrada 2026-10-22)
- PR #6 (`0e735e1`); estado `retrying` («Reintentando…»/«Retrying…») solo si el clic inicia un intento; Playwright en `frontend/e2e/`, job `e2e` en PR y push a `main`; artefactos saneados. **§6 aprobada.**
- El job `e2e` ejecuta el escenario **dentro del contenedor oficial de Playwright** (`--network host`), sin `apt` ni caché de navegadores: el `install --with-deps` agotaba el timeout por el espejo de `apt` del runner.

## Specs 008 y 009 (cerradas 2026-10-21)
- **008:** PR #3 (`393f9fb`); RF R18–R32; migraciones aditivas **022/023**. **009:** PR #5 (`3535b98`); C-1 reenviar revocada 409, C-2 materialización al reabrir, «Reabrir» 200, `code` aditivo; salud 90 s/10 s. Ambas con **§6 aprobada**.

## Specs anteriores
- 001–004 cerradas; 005 cerrada con §6 (riesgo residual de sorteos Swiss en frío); 006 PR #1 (`7284756`); 007 PR #2 (`dc86270`), migración 021 antes del código.
- Dependencias: `braces` 3.0.3 y `node-forge` 1.4.0 con altos sin parche upstream.

## Entorno local
- Backend: `python:3.14-slim` con repo montado + `pip install -r backend/requirements*.txt`; frontend en `node:24-alpine`; E2E en `mcr.microsoft.com/playwright:v1.64.1-noble` con red host y socket de Docker (`COMPOSE_PROJECT_NAME=bracket-craft`).
- Base local en **023** con smoke OK. Si el volumen se creó con otra `BRACKET_DB_PASSWORD`, `bracket_app` conserva la clave vieja: `127.0.0.1` es `trust` y la red usa `scram` → **28P01**; alinear con `ALTER ROLE`.
- `DATABASE_ADMIN_URL` debe apuntar a una base con esquema (`bracket_craft`). Tras reiniciar el servidor, si Docker Desktop pierde la integración WSL, los contenedores antiguos montan `/app` vacío: `docker compose up -d --force-recreate`.

## Pendiente
- **Despliegue en servidor:** paquete en `docs/runbook-despliegue-019-023.md` (ventana recomendada → 019…023 → código → smoke). En local ya está en 023.
- TypeScript fijado en **`~6.0.3`**; no subir a 7.x (`vue-tsc` rompe `typecheck`).
