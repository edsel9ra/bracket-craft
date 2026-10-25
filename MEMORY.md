# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Spec 013 implementada, aprobada por el usuario y cerrada** (2026-10-24): **30/30 tareas**, reviewer **APROBADO** y correcciones C-1…C-7 aplicadas. T30 no ejecutada (sin cliente OAuth real). Spec 012 cerrada y mergeada (PR #8, `0765683`); 011 en PR #7. Constitución **1.4.0**; `main` protegida con cinco *required checks*.

## Spec 013 — acceso con Google y asociación de cuentas (cerrada 2026-10-24)
- **Migración 024** (`uq_auth_identity_user_provider` en `auth_identities`, pre-chequeo que aborta sin corregir filas; sin grants/RLS). Orden **024 → código**, sin rollback. La base local sigue en **023**: la 024 no se aplicó localmente; sus pruebas usan base desechable.
- **Backend:** flujo único de redirección (`POST /auth/google/start` + `GET /auth/google/callback`), estado en Redis (`sha256(state)`, TTL 600 s, `GETDEL`) y cookie `bc_oauth_state`; `GET /auth/session`, `GET /auth/google/status`, `GET /auth/google/link`; `POST /auth/google` responde **410** `GOOGLE_IDENTITY_INVALID`. Vinculación desde `/account/google` sin tocar sesión ni `users.email`; organización opcional `POST /organizations` (409 sin `code` si ya tiene; `ORGANIZATION_SLUG_TAKEN` si el slug está ocupado).
- **Seguridad:** firma del `id_token` no verificada (D-9: llega del canje por TLS); `GOOGLE_REDIRECT_URI` obligatoria si Google está habilitado; log de acceso saneado (`--no-access-log` + `app/core/access_log.py`, sin consulta).
- **Frontend:** `/login` (estado SSR, espera accesible), `/auth/callback` (rehidrata y navega con `replace`), `/account/google`, `/organization`, `middleware/session.ts`; utilidades puras en `utils/googleAuth.ts` y catálogo es/en con paridad.
- **Evidencia final:** backend `pytest -q` **1314 passed / 289 skipped**; opt-in con base real **32 passed**; frontend `pnpm test` **499**, `typecheck`, `build` y `typecheck:e2e` en verde; infraestructura y seguridad en 0. **Trivy y T30 no ejecutados.**
- **Correcciones de revisión:** C-1 prueba RF-30 (login de cuenta solo-Google), C-2 textos del catálogo literales, C-3 `no-store` en errores de identidad y 201 de organización, C-4 cancelación consume y enruta por `flow`, C-5 plan §6.4, C-6 `Referrer-Policy: no-referrer`, C-7 opt-in en AGENTS.
- **T30 manual:** **no ejecutada** por falta de cliente OAuth real en el entorno; declarada así en README/AGENTS, sin fecha ni resultados. **Pendiente de despliegue:** aplicar la **024 antes del código** y la corrida manual con Google real cuando haya credenciales.

## Spec 012 — formularios asistidos… (cerrada 2026-10-23)
- 35/35 tareas + H-1…H-14; configuración en `/workspace/tournaments/{id}` con `calendar`/`rosters` propias; asistentes con paso solo en `?step=` y borrador en `sessionStorage`; `game_format` declarativo; límites y retiro lógico; `engine_version` 2026.1.
- Evidencia al cerrar: backend 981/256 skipped, frontend 485, `typecheck`/`build`/`typecheck:e2e` y E2E verdes. E2E: esperar `?step=` antes del paso siguiente; no matar el dev server con `build`.

## Specs 011 / 008 / 009 y anteriores
- **011:** PR #7 (sin migraciones). **008:** PR #3 (migraciones 022/023). **009:** PR #5 (C-1/C-2, `code` aditivo, salud 90/10 s). **010:** E2E en Playwright oficial. 001–007 cerradas (005: riesgo de sorteos Swiss en frío; 007: 021 antes del código).

## Entorno local
- Backend `python:3.14-slim`; frontend en `web` (Node 24/pnpm 12.12.1). La imagen `api` no trae dev deps: `pip install --target /tmp/devdeps -r requirements-dev.txt` y `PYTHONPATH=/tmp/devdeps`; los tests de contrato necesitan el repo montado en `/repo`.
- **No ejecutes `pnpm run build` en `web` con el dev server vivo:** reemplaza `.nuxt`; reinicia `web` después.
- Base local en 023; migraciones nuevas con `MIGRATION_TARGET=NNN`.

## Pendiente
- TypeScript `~6.0.3` (no 7.x: rompe `vue-tsc`). Despliegue acumulado y riesgos residuales ya documentados.
