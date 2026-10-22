# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Spec 008 — Higiene P2 (implementada y validada 2026-10-21)
- **008A/008B/008C completas (22 tareas).** Evidencia: backend **764 passed/194 skipped** sin base y **958 passed/0 skipped** con base; frontend **133 tests**, typecheck y build en Node 24; Compose dev/prod, contrato de entorno, `assert_production_compose`, `pip-audit`, auditoría de frontend y Trivy en verde; migraciones 022/023 en cadena limpia y migrada. Cubre **R18-R32**; **R11 fuera**.
- Decisiones cerradas: **Q1** anti-duplicado solo en altas manuales (1 por pareja y 2 en ida y vuelta); **Q2** restaurar la última organización con orden estable de reserva; **Q3** `public_age` interna y sin consumo; **Q4** aceptar invitación sin `access_token` en el cuerpo; **Q5** solo la API a loopback en dev; **Q6** al crear se materializa la vencida (201), revocar vencida 409, reenviar la reutiliza.
- Correcciones de la ronda 2: RF-004 valida `Origin` y `Referer` **por separado** (403 si cualquiera no está permitido; `Referer` vacío o no parseable se rechaza); reenvío con **409 de dominio** en vez de 500; `NON_SERVICE_CONSUMERS` (one-off de cifrado y navegador) en el contrato de entorno; prueba de las 7 variables.
- Contratos: sin `access_token` al aceptar invitación; revocar vencida → 409; rol mostrado por precedencia (no `MIN(role_code)`); organizaciones en orden estable.
- Migraciones **aditivas**: 022 topes de minuto, 023 `schedule_legs`. Despliegue: **022 → 023 → backend → frontend** de la misma versión; sin rollback, solo *forward-fix*.
- **Riesgos residuales aceptados:** R32f relay sin filtro de rol; R24 013 silenciosa (verificada); R22 unicidad de pendientes con vencimiento diferido; R26 ligas históricas de dos vueltas sin *backfill*; R20 deriva del mapa de configuración.
- **Decisiones posteriores:** UI de «Reenviar» para vencidas/revocadas; reapertura de revocadas; E2E de navegador del reintento; transición real del worker a insano por bucle detenido; revisión humana (§6) y CI real.

## Spec 007 — Reglas declaradas y constantes (cerrada 2026-10-21)
- **Implementada, validada por @reviewer y cerrada. PR #2 mergeado (`dc86270`); CI en `main` en verde.** Solo queda desplegar la **021 antes** del código.
- Evidencia: backend **616/152**; con base **764/2**; frontend **110**; runner de migraciones y Compose OK; `pip-audit --local` sin hallazgos.
- Migración **021 aditiva antes del código** (`player_out_id`/`player_in_id`, FKs compuestas, `CHECK ... NOT VALID`); no elimina `match_segment_team_state` ni toca `init/01`.
- Sustituciones **al cerrar el acta** (5/3/`false`); orden `(minute, added_minute, índice)` con intervalos y reentrada; límites por equipo y partido; `match_segment_team_state` es proyección (el `GET` calcula sin escribir).
- `roster_lock_matchday` de primer nivel con valor de la **versión publicada**; jornada = `matchday` de la primera fase; alta/importación → 409 sin escribir. Minutos desde `stage_defaults` + overrides (90/120); cierre serializado por fase.
- Enmienda constitucional **1.3.0** (§3.2) va en **commit separado** del cambio funcional.

## Specs anteriores
- 001 (P0), 002 (cifrado 017/018 y `MIGRATION_TARGET`), 003 (dependencias) y 004 (outbox/tiempo real): cerradas.
- 005 (firmas, Swiss y conexión): implementada y validada; pendiente CI en `main` y revisión humana.
- 006 (scoping de torneo y avance manual): cerrada; PR #1 (`7284756`). Autorización = RBAC por organización + `match_officials`; `tournament_user_roles` retirada.
- **Riesgo residual 005:** dos sorteos Swiss simultáneos en frío podrían duplicar calendarios. `braces` 3.0.3 y `node-forge` 1.4.0: altos sin parche upstream.

## Entorno local
- Backend: tests en contenedor `python:3.14-slim` (raíz montada + `pip install -r backend/requirements*.txt`); frontend en `node:24-alpine` con pnpm 12.12.1 vía corepack. Sin venv ni PostgreSQL local.
- `DATABASE_ADMIN_URL` debe apuntar a una base con esquema (`bracket_craft`), no a `postgres`.
- Docker disponible (engine 29.9.1): Compose y contenedores sí; Trivy con la imagen `aquasec/trivy`. `pip-audit -r` falla por `ensurepip` ausente.
- Constitución en CRLF: `git -c core.whitespace=cr-at-eol diff --check`. `trivy-action@v0.36.0`.

## Pendiente
- Desplegar **022 → 023** y el código de la 008; **021** antes del código (007); **019** y **020** (006, código nuevo primero).
- Cerrar 005 en `main` (CI + revisión humana). TypeScript: la última es **7.0.2**, pero `vue-tsc` 3.3.13 no soporta su API (rompe `typecheck`); reintentar cuando lo soporte.
- Ejecutar la opt-in con el rol de aplicación cuando haya credenciales válidas.
