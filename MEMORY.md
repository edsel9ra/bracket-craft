# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Sin specs abiertas.** Última cerrada: **010** (2026-10-22). **§6 aprobada** para 005, 008, 009 y 010. **Constitución 1.4.0** (job `e2e` en la §4).

## Spec 010 — E2E del reintento del tiempo real (cerrada 2026-10-22)
- **Implementada, validada por @reviewer (APROBADO) y cerrada.** PR **#6** (`0e735e1`); CI en verde, incluido el job `e2e` (**3m10s** en la PR, omitido en push de rama). **Sin migraciones.** **§6 aprobada por el usuario (2026-10-22).**
- **Producto:** estado `retrying` («Reintentando…»/«Retrying…»), distinto del automático, `role="status"` en las tres vistas; **solo** lo fija el clic si `connect()` inicia un intento nuevo (un no-op no lo pinta y el E2E se pone rojo).
- **Arnés:** `frontend/e2e/` (Playwright 1.64.1, Chromium headless, `retries: 0`), interceptor `pass/hold/abort` + `routeWebSocket`, escenario bloquear → error → clic → estado manual → error → desbloquear → conectado; ≤1 recarga por consumidor y 0 del documento; sin conteo de sesiones ni identificador en el artefacto.
- **Artefactos saneados:** `summary.json`, `view-<vista>.json`, `trace-<vista>.jsonl`, `server.log`; sin cookies/tokens/`trace.zip`. `frontend/.auth/` y `e2e-report/` ignorados.
- **Runner:** `pnpm run e2e` / `e2e:test`, códigos 0/1/2/3 (verde, comportamiento, infraestructura, inválida). Evidencia: frontend **236 tests**, typecheck/typecheck:e2e/build; **11 corridas verdes**; backend 793 passed/206 skipped (sin tocar backend).
- **Observador determinista** (`statusObserver.ts`): registra el estado manual tras cada clic; corrigió un falso rojo intermitente.

## Spec 009 — Invitaciones y salud del worker (cerrada 2026-10-21)
- PR **#5** (`3535b98`); C-1 reenviar revocada → 409; C-2 reapertura materializa vencidas; «Reabrir» 200 con token nuevo; solo la reapertura audita; `code` aditivo en los 409 de crear/reenviar/reabrir. **§6 aprobada por el usuario.**
- Salud: 90 s/10 s sin cambio funcional; `verify_worker_loop_health.sh` verifica `healthy → unhealthy → healthy` con SIGSTOP.

## Spec 008 — Higiene P2 (cerrada 2026-10-21)
- PR #3 (`393f9fb`); RF R18–R32; migraciones aditivas **022/023**; riesgos R20, R22, R24, R26, R32f. **§6 aprobada.**

## Specs anteriores
- 001–004 cerradas; 005 cerrada (§6 aprobada; riesgo residual de sorteos Swiss en frío); 006 PR #1 (`7284756`); 007 PR #2 (`dc86270`), migración 021 antes del código.
- Dependencias: `braces` 3.0.3 y `node-forge` 1.4.0 con altos sin parche upstream.

## Entorno local
- Backend: `python:3.14-slim` con repo montado + `pip install -r backend/requirements*.txt`; frontend en `node:24-alpine` (pnpm 12.12.1) y E2E en `mcr.microsoft.com/playwright:v1.64.1-noble` con red host. Sin venv ni PostgreSQL local.
- Base local en **023** con smoke OK. Si el volumen se creó con otra `BRACKET_DB_PASSWORD`, `bracket_app` conserva la clave vieja: `127.0.0.1` es `trust` y la red usa `scram` → **28P01**; alinear con `ALTER ROLE`.
- `DATABASE_ADMIN_URL` debe apuntar a una base con esquema (`bracket_craft`). Docker 29.9.1; Trivy con `aquasec/trivy` y caché local si falla la descarga.

## Pendiente
- Marcar el job `e2e` como ***required check*** en la protección de rama (configuración del repositorio; la §4 ya lo exige desde la 1.4.0).
- **Despliegue en servidor:** 019 → 020 → 021 → 022 → 023 y el código, por ese orden; en local ya está hecho.
- TypeScript fijado en **`~6.0.3`**; no subir a 7.x (`vue-tsc` rompe `typecheck`).
