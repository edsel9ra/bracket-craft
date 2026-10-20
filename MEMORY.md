# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Spec 006 — Scoping de torneo y avance manual (2026-10-20)
- **Implementada, validada por @reviewer y cerrada (2026-10-20). CI en `main` en verde; PR #1 mergeado (merge commit `7284756`).** Queda solo desplegar las migraciones 019 y 020.
- Evidencia: backend **469 passed / 132 skipped**; opt-in **42** (`player_catalog_isolation`, `schema`, `swiss_transaction`) y **23** (migración 019 y concurrencia) en bases desechables; frontend **77 passed**, typecheck OK (build no re-ejecutado por OOM local en la última pasada).
- Autorización real: RBAC por organización + `match_officials` por partido; `tournament_user_roles` retirada; sin roles ni ámbito por torneo.
- Avance manual: `GET/POST/DELETE /tournaments/{id}/stages/{stage_id}/teams`; solo borradores; POST atómico 1..64 sin duplicados (201/200); DELETE 204 idempotente con guardas 409 (versión, no registrado, partido, standings). El calendario no se regenera; `stage_rank`/sembrado automático no soportado; `phase_config` no se interpreta.
- Bloqueo: fase → versión → partidos → segmentos → jugadores. El cierre pre-bloquea origen y destinos (incl. GF2); `standings` bloquea la fase antes del advisory; rendimiento no medido (RNF-003).
- 019 destructiva sin rollback: retira `tournament_user_roles` y `stage_edges`, estrecha el CHECK a `direct_team`/`match_result` y conserva `phase_slots`; trigger con SQLSTATE `ZZ409` → API 409 por código, no por texto.
- Despliegue: código nuevo primero (esquema 018), luego `MIGRATION_TARGET=019` y `020`; la 020 es un *forward-fix* no destructivo que concede `INSERT (id)` en `rosters` para el `id` pre-generado de la importación N-2 (`init/01` lo incluye). Backup verificado con `pg_restore -l`, pre-chequeo con `to_regclass` y catálogo con `incoming_fk`; después solo *forward-fix*.
- Observaciones no bloqueantes: RNF-003 no medida y aclaración de RF-008 en la spec (los tests de la 019 nombran estructuras retiradas); no hay pendientes de código.

## Riesgo residual
- Dos sorteos Swiss simultáneos en frío (ronda 1 sin filas) podrían duplicar calendarios; aceptado en la spec 005.
- `braces` 3.0.3 y `node-forge` 1.4.0: altos y sin parche upstream; revisar en cada actualización.

## Specs anteriores
- 001 (correctivos P0), 002 (cifrado 017/018, backfill y `MIGRATION_TARGET`) y 003 (deuda de dependencias): cerradas.
- 004 (outbox y tiempo real): aprobada; stream de mejor esfuerzo, `event_id` aditivo, `RESYNC` y deduplicación 200.
- 005 (firmas, Swiss y conexión): implementada y validada por review; pendiente CI en `main` y revisión humana.

## Entorno local
- Sin Python ni pnpm en el host: backend con la imagen `bc-api-t007` sobre copia en `/tmp`; frontend con `node:24-alpine` y pnpm 12.12.1 en `/tmp`.
- PostgreSQL local con credenciales desalineadas: la opt-in se ejecuta en bases desechables; no cambiar la base compartida.
- Constitución en CRLF: usar `git -c core.whitespace=cr-at-eol diff --check`. Trivy `aquasec/trivy:0.70.0`; `trivy-action@v0.36.0`.

## Pendiente
- Spec 006: solo desplegar las migraciones **019** y **020** en el entorno real (código nuevo primero); no hay pendientes de código ni de CI.
- Cerrar 005 en `main` (CI + revisión humana).
- Ejecutar la opt-in con el rol de aplicación cuando haya credenciales válidas.
