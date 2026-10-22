# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Spec 009 aprobada** (`specs/009-invitaciones-y-salud-del-worker/`): `plan.md` y `tasks.md` (9 tareas) esperando aprobación del usuario. **Spec 010** (E2E navegador) en borrador con 3 dudas.

## Spec 009 — Invitaciones y salud del worker (aprobada 2026-10-21)
- **11 RF, 7 RNF, 20 casos, 14 criterios; sin migraciones.** Dos cambios de contrato: **C-1** reenviar revocada → 409; **C-2** la reapertura materializa las pendientes vencidas del correo (tercera ruta de materialización).
- «Reabrir» revocada: misma fila, token/fecha nuevos, `revoked_at` limpio, 200; reabrir pendiente/aceptada o con otra pendiente vigente → 409. Solo la reapertura audita (sin correo ni token); la aceptación conserva su `ACCEPT_INVITATION`.
- 409 con campo aditivo `code`; traducción en cliente. Worker: **90 s** sin vuelta / cadencia **10 s**, verificado con SIGSTOP sobre un worker vivo.
- Verificación UI: funciones puras (`node --test`) + aserciones de fuente; **sin** arnés de componentes; navegador → spec 010.

## Spec 008 — Higiene P2 (cerrada 2026-10-21)
- PR **#3** (`393f9fb`), commit `67fcce7`; CI verde y **opt-in local 958 passed** con rol de aplicación. RF R18–R32 validados por @reviewer; riesgos R20, R22, R24, R26, R32f.
- Migraciones aditivas **022** (topes de minuto) y **023** (`schedule_legs`); 019 → 020 → 021 → 022 → 023, sin rollback. `spec.md` aclara el umbral del worker (90 s/10 s, sin cambio de comportamiento).

## Spec 007 — Reglas declaradas y constantes (cerrada 2026-10-21)
- PR #2 (`dc86270`); migración **021 antes del código**; sustituciones al cerrar el acta (5/3/`false`), orden `(minute, added_minute, índice)`, límites por equipo y partido.
- `roster_lock_matchday` de primer nivel con valor de la versión publicada; minutos desde `stage_defaults` + overrides; cierre serializado por fase. Enmienda constitucional 1.3.0 en commit separado.

## Specs anteriores
- 001–004 cerradas. 005: cerrada, §6 aprobada; riesgo residual de sorteos Swiss simultáneos en frío. 006: PR #1 (`7284756`), RBAC por organización + `match_officials`.
- 008 y 009: ver arriba. **§6 aprobada por el usuario (2026-10-21) para 005 y 008.**
- Dependencias: `braces` 3.0.3 y `node-forge` 1.4.0 tienen altos sin parche upstream.

## Entorno local
- Tests backend en `python:3.14-slim` (raíz montada + `pip install -r backend/requirements*.txt`); frontend en `node:24-alpine` con pnpm 12.12.1. Sin venv ni PostgreSQL local.
- Base local **en 023** con smoke OK. Si el volumen se creó con otra `BRACKET_DB_PASSWORD`, `bracket_app` conserva la clave vieja: `127.0.0.1` es `trust` y la red usa `scram` → **28P01**; alinear con `ALTER ROLE`.
- `DATABASE_ADMIN_URL` debe apuntar a una base con esquema (`bracket_craft`), no a `postgres`. Docker 29.9.1; Trivy con `aquasec/trivy`.
- Constitución en CRLF: `git -c core.whitespace=cr-at-eol diff --check`.

## Pendiente
- **Aprobar `plan.md` y `tasks.md` de la 009**; después implementar T1–T9.
- **Spec 010:** resolver sus 3 dudas (frecuencia del job, navegadores, cómo simular la caída) antes de planificar.
- **Despliegue en servidor:** 019 → 020 → 021 → 022 → 023 y el código, por ese orden; en local ya está hecho.
- TypeScript fijado en **`~6.0.3`**; no subir a 7.x (`vue-tsc` rompe `typecheck`).
