# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Spec 009 cerrada** (2026-10-21). **Spec 010** (E2E navegador del reintento) en borrador con 3 dudas por resolver antes de planificar.

## Spec 009 — Invitaciones y salud del worker (cerrada 2026-10-21)
- **Implementada, validada por @reviewer (APROBADO) y cerrada.** PR **#5** (`3535b98`); commits `fc45cb8`…`94f9a3f`; CI en verde. **Sin migraciones.** **§6 aprobada por el usuario (2026-10-21).**
- **C-1:** reenviar una revocada → **409** `INVITATION_REVOKED_RESEND`. **C-2:** la reapertura materializa las pendientes vencidas del correo (tercera ruta), en la misma transacción.
- «Reabrir» (`POST /organizations/invitations/{id}/reopen`) → **200**, misma fila con token/fecha nuevos y `revoked_at` limpio; pendiente/aceptada u otra pendiente vigente → **409** sin escribir. Solo la reapertura audita (`REOPEN_INVITATION`); la aceptación conserva `ACCEPT_INVITATION`.
- 409 con campo aditivo `code` en crear, reenviar y reabrir (revocar una vencida no lo lleva); `detail` sigue siendo cadena y el cliente traduce.
- UI: acción por estado, confirmación, una petición por activación, enlace del último emitido y **recarga también cuando el correo falla tras el commit (502)**.
- Salud: «vuelta completada» con 90 s/10 s, sin cambio funcional; `infra/scripts/verify_worker_loop_health.sh` verifica `healthy → unhealthy → healthy` con SIGSTOP (observado: insano ~109-119 s, sano a los 10 s, sin reinicio). No está en CI.
- Evidencia: backend **999 passed** (con base y rol de aplicación), frontend **150 tests**, typecheck y build; Compose dev/prod, contrato de entorno y aserciones de producción en verde.

## Spec 008 — Higiene P2 (cerrada 2026-10-21)
- PR **#3** (`393f9fb`, commit `67fcce7`); RF R18–R32 validados; riesgos R20, R22, R24, R26, R32f. Migraciones aditivas **022** y **023**; `spec.md` aclara el umbral del worker (90 s/10 s).
- **§6 aprobada por el usuario** para 005 y 008.

## Spec 007 — Reglas declaradas y constantes (cerrada 2026-10-21)
- PR #2 (`dc86270`); migración **021 antes del código**; sustituciones al cerrar el acta (5/3/`false`), orden `(minute, added_minute, índice)`, límites por equipo y partido.
- `roster_lock_matchday` de primer nivel con valor de la versión publicada; minutos desde `stage_defaults` + overrides; cierre serializado por fase. Enmienda constitucional 1.3.0 en commit separado.

## Specs anteriores
- 001–004 cerradas. 005: cerrada; riesgo residual de sorteos Swiss simultáneos en frío. 006: PR #1 (`7284756`), RBAC por organización + `match_officials`.
- Dependencias: `braces` 3.0.3 y `node-forge` 1.4.0 tienen altos sin parche upstream.

## Entorno local
- Backend: tests en `python:3.14-slim` (repo montado + `pip install -r backend/requirements*.txt`); frontend en `node:24-alpine` con pnpm 12.12.1. Sin venv ni PostgreSQL local.
- Base local **en 023** con smoke OK. Si el volumen se creó con otra `BRACKET_DB_PASSWORD`, `bracket_app` conserva la clave vieja: `127.0.0.1` es `trust` y la red usa `scram` → **28P01**; alinear con `ALTER ROLE`.
- `DATABASE_ADMIN_URL` debe apuntar a una base con esquema (`bracket_craft`), no a `postgres`. Docker 29.9.1; Trivy con `aquasec/trivy`.
- Constitución en CRLF: `git -c core.whitespace=cr-at-eol diff --check`.

## Pendiente
- **Spec 010:** resolver las 3 dudas (frecuencia del job, navegadores, cómo simular la caída del tiempo real) y planificar.
- **Despliegue en servidor:** 019 → 020 → 021 → 022 → 023 y el código, por ese orden; en local ya está hecho.
- TypeScript fijado en **`~6.0.3`**; no subir a 7.x (`vue-tsc` rompe `typecheck`).
