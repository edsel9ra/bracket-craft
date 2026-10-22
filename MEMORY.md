# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- Ninguna spec abierta. Última cerrada: **008** (2026-10-21); sin trabajo pendiente de commit.

## Spec 008 — Higiene P2 de auditoría (cerrada 2026-10-21)
- **Implementada, validada por @reviewer y cerrada.** PR **#3** (`spec/008-higiene-p2-auditoria`) fusionada en `main` con merge commit **`393f9fb`**; commit de la spec **`67fcce7`**. 22 tareas (008A/008B/008C) completas.
- **CI real en verde** en `main` y en la PR: `Backend tests` (2m27s en la PR), `Frontend checks`, `Infrastructure checks`, `Dependency and filesystem scan` y GitGuardian.
- **@reviewer validó RF por RF (R18-R32; R11 fuera de alcance)** sin ningún RF sin evidencia; veredicto favorable tras corregir el estado documental de `spec.md` y `plan.md`.
- Decisiones: Q1 anti-duplicado solo en altas manuales (1 por pareja, 2 en ida y vuelta); Q2 orden estable al restaurar organización; Q3 `public_age` interna sin consumo; Q4 aceptar invitación sin `access_token`; Q5 solo la API a loopback en dev; Q6 crear sobre vencida → 201, revocar vencida → 409, reenviar la reutiliza. `Origin`/`Referer` se validan por separado.
- Migraciones **aditivas** 022 (topes de minuto) y 023 (`schedule_legs`); despliegue **022 → 023 → backend → frontend**, sin rollback (*forward-fix*).
- **Riesgos residuales aceptados:** R32f relay sin filtro de rol, R24 013 silenciosa (verificada), R22 unicidad de pendientes con vencimiento diferido, R26 ligas históricas sin *backfill*, R20 deriva del mapa de configuración.
- **Observaciones no bloqueantes:** `GET /organizations/current/access` da 200 con `role_code="viewer"` y `permissions=[]` a un miembro sin rol (no alcanzable por flujos normales, no concede permisos, sin cobertura); `test_pairings_limit.py` solo cubre la función pura y el 409 real es opt-in.

## Spec 007 — Reglas declaradas y constantes (cerrada 2026-10-21)
- **Implementada, validada por @reviewer y cerrada. PR #2 mergeado (`dc86270`); CI en `main` en verde.** Solo queda desplegar la **021 antes** del código.
- Evidencia: backend **616/152**; con base **764/2**; frontend **110**; runner de migraciones y Compose OK; `pip-audit --local` sin hallazgos.
- Migración **021 aditiva antes del código** (`player_out_id`/`player_in_id`, FKs compuestas, `CHECK ... NOT VALID`); no elimina `match_segment_team_state` ni toca `init/01`.
- Sustituciones **al cerrar el acta** (5/3/`false`); orden `(minute, added_minute, índice)` con intervalos y reentrada; límites por equipo y partido; `match_segment_team_state` es proyección (el `GET` calcula sin escribir).
- `roster_lock_matchday` de primer nivel con valor de la **versión publicada**; jornada = `matchday` de la primera fase; alta/importación → 409 sin escribir. Minutos desde `stage_defaults` + overrides (90/120); cierre serializado por fase.
- Enmienda constitucional **1.3.0** (§3.2) va en **commit separado** del cambio funcional.

## Specs anteriores
- 001 (P0), 002 (cifrado 017/018 y `MIGRATION_TARGET`), 003 (dependencias) y 004 (outbox/tiempo real): cerradas.
- 005 (firmas, Swiss y conexión): implementada y validada; CI en `main` cumplido, pendiente la revisión humana de la §6.
- 006 (scoping de torneo y avance manual): cerrada; PR #1 (`7284756`). Autorización = RBAC por organización + `match_officials`; `tournament_user_roles` retirada.
- **Riesgo residual 005:** dos sorteos Swiss simultáneos en frío podrían duplicar calendarios. `braces` 3.0.3 y `node-forge` 1.4.0: altos sin parche upstream.

## Entorno local
- Backend: tests en contenedor `python:3.14-slim` (raíz montada + `pip install -r backend/requirements*.txt`); frontend en `node:24-alpine` con pnpm 12.12.1 vía corepack. Sin venv ni PostgreSQL local.
- `DATABASE_ADMIN_URL` debe apuntar a una base con esquema (`bracket_craft`), no a `postgres`.
- Docker disponible (engine 29.9.1): Compose y contenedores sí; Trivy con la imagen `aquasec/trivy`. `pip-audit -r` falla por `ensurepip` ausente.
- Constitución en CRLF: `git -c core.whitespace=cr-at-eol diff --check`. `trivy-action@v0.36.0`.

## Pendiente
- Desplegar migraciones en orden: **019 → 020** (006, código nuevo primero), **021** (007, antes del código) y **022 → 023 → backend → frontend** (008).
- Cerrar **005** en `main`: ya cumplió CI, falta la revisión humana de la §6. Revisión humana de la §6 también para **008**.
- Ejecutar la opt-in con el rol de aplicación cuando haya credenciales válidas.
- TypeScript fijado en **`~6.0.3`** (instalado 6.0.3) con `vue-tsc` 3.3.13 y `vue` 3.5.44; **no subir a 7.x** (`vue-tsc` rompe `typecheck`). El `~` evita que un bot abra el rango.
- Decisiones posteriores sin spec: UI de «Reenviar» para vencidas/revocadas, reapertura de revocadas, E2E de navegador del reintento y transición real del worker a insano por bucle detenido.
