# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Spec 007 — Reglas declaradas y constantes (cerrada 2026-10-21)
- **Implementada, validada por @reviewer y cerrada. PR #2 mergeado (`dc86270`); CI en `main` en verde.** Solo queda el despliegue de la **021 antes** del código.
- Evidencia: backend **616 passed/152 skipped**; suite con base **764 passed/2 skipped**; frontend **110 passed**, typecheck y build OK; runner de migraciones y Compose OK; `pip-audit --local` sin hallazgos; Trivy no disponible.
- Migración **021 aditiva antes del código**: `player_out_id`/`player_in_id`, FKs compuestas y `CHECK ... NOT VALID`; no elimina `match_segment_team_state` ni toca `init/01`; sin rollback (*forward-fix*).
- Sustituciones aplicadas **al cerrar el acta** (`max_per_team`/`max_windows`/`allow_reentry`, defaults 5/3/`false`); orden canónico `(minute, added_minute, índice)` e intervalos con reentrada; límites por equipo y partido; `match_segment_team_state` es proyección (el `GET /operation` calcula sin escribir).
- `roster_lock_matchday` de primer nivel con valor efectivo de la **versión publicada**; jornada = `matchday` de la primera fase por `stage_order`; alta/importación → 409 sin escribir.
- Minutos `regular_time_minutes`/`extra_time_minutes` desde `stage_defaults` + overrides (defaults 90/120); pareja efectiva validada; el cierre usa el máximo efectivo. Contrato interno en `docs/contrato-reglas.md` (`engine_version` 2026.1: `GF1`/`GF2` y cuatro formaciones).
- Enmienda constitucional **1.3.0** (§3.2: retira «transferencias» y añade «sustituciones» y «ventana de inscripción») debe ir en un **commit separado** del cambio funcional.
- Cierre serializado por fase (dos cierres simultáneos → 409); sin API incremental ni anulación (R11 fuera); eventos de acta confirmada inmutables; `is_voided` es legado.

## Spec 006 — Scoping de torneo y avance manual (cerrada)
- **Implementada y validada por @reviewer; PR #1 mergeado (`7284756`).** Solo queda desplegar las migraciones 019 y 020.
- Autorización real: RBAC por organización + `match_officials` por partido; `tournament_user_roles` retirada. Avance manual solo en borradores (1..64, atómico, 204 idempotente); el calendario no se regenera.
- La 019 es destructiva y sin rollback: código nuevo primero, luego 019 y 020; después solo *forward-fix*. Trigger de estructura con `ZZ409` → API 409 por código.

## Riesgo residual
- Dos sorteos Swiss simultáneos en frío (ronda 1 sin filas) podrían duplicar calendarios; aceptado en la spec 005.
- `braces` 3.0.3 y `node-forge` 1.4.0: altos y sin parche upstream; revisar en cada actualización.

## Specs anteriores
- 001 (correctivos P0), 002 (cifrado 017/018, backfill y `MIGRATION_TARGET`) y 003 (deuda de dependencias): cerradas.
- 004 (outbox y tiempo real): aprobada; stream de mejor esfuerzo, `event_id` aditivo, `RESYNC` y deduplicación 200.
- 005 (firmas, Swiss y conexión): implementada y validada; pendiente CI en `main` y revisión humana.

## Entorno local
- Backend con venv `/tmp/opencode/bc-t007-venv`; frontend con Node 24.11 y pnpm 12.12.1 en `/tmp/opencode`; PostgreSQL 18 local en `/tmp/opencode/pgdata` (127.0.0.1:5432).
- `DATABASE_ADMIN_URL` debe apuntar a una base con esquema (`bracket_craft`), no a `postgres`: los tests de seed/fotos hacen `SET LOCAL ROLE bracket_app` sobre ella.
- Docker daemon no disponible: `docker compose config` funciona (cliente) pero no se ejecutan contenedores ni Trivy. `pip-audit -r` falla por `ensurepip` ausente; `pip-audit --local` sí audita el venv.
- Constitución en CRLF: usar `git -c core.whitespace=cr-at-eol diff --check`. `trivy-action@v0.36.0`.

## Pendiente
- Spec 007: desplegar la **021 antes** del código (backup verificado, pre-chequeos, smoke).
- Spec 006: desplegar las migraciones **019** y **020** (código nuevo primero).
- Cerrar 005 en `main` (CI + revisión humana).
- Ejecutar la opt-in con el rol de aplicación cuando haya credenciales válidas.
