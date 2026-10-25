# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Spec 014 (escudos e imágenes de equipos): implementada y aprobada por el usuario (2026-10-24); reviewer APROBADO; 18/18 tareas.** Última cerrada; antes la **013** (Google, PR #10, `6808fa3`).
- **Spec 013 (acceso con Google): implementada, aprobada y cerrada (2026-10-24); 30/30 tareas y correcciones C-1…C-7; T30 no ejecutada.**
- Constitución **1.4.0**; `main` protegida con cinco *required checks*. Esquema en **025**; **orden de despliegue 024 → 025 → código** (024 de la 013, 025 de la 014), ambas aditivas y sin rollback (*forward-fix*). Base local en 025.

## Spec 014 — cerrada (2026-10-24, APROBADO)
- **Cierre:** 18/18 tareas; renuncia expresa del usuario a la comprobación manual (criterios 5, 15, 16, 18 y 20), con riesgo residual de accesibilidad y carga real no verificadas fuera de las pruebas automáticas/estáticas.
- **Producto:** una imagen por equipo compartida entre torneos, gestionada con `MANAGE_TOURNAMENTS`; `teams.crest_object_key` + `v_public_tournament_teams`; `logo_url` se retira con la primera carga y solo es respaldo del Workspace (nunca público); enlaces firmados de 300 s.
- **Contrato:** `GET/POST/DELETE /tournaments/{id}/teams/{team_id}/crest` (200/200/204), `TeamCrestResponse {team_id, crest_url, logo_url}` y campos aditivos en listado, operación (incluye `*_logo_url`), detalle/clasificación/partidos/alineaciones públicas. Códigos `CREST_*`; 422 tras 403/404. Sin consentimiento ni eventos.
- **Escritura:** subida fuera de transacción, `FOR UPDATE`, auditoría en la misma transacción y borrado del anterior tras commit; fallo previo compensa, commit ambiguo conserva ambos; una cancelación dura puede dejar huérfano (sin `asyncio.shield`).
- **Evidencia final:** backend **1141/283** sin base y **1424** con base; frontend **510**; `typecheck`/`build`/`typecheck:e2e` 0; E2E **VERDE (0)**; infra/seguridad en 0.
- **Migración 025:** `infra/postgres/migrations/025_team_crests.sql`; runbook en README/AGENTS.

## Spec 013 — cerrada (2026-10-24, APROBADA)
- **Migración 024** (`uq_auth_identity_user_provider`, pre-chequeo que aborta sin corregir filas); orden **024 → código**.
- **Backend:** redirección Google (`start`/`callback`), estado en Redis (`sha256`, TTL 600 s, `GETDEL`), cookie `bc_oauth_state`; `/auth/session`, `/auth/google/status|link`; `POST /auth/google` **410**; vinculación sin tocar sesión ni `users.email`; organización opcional `POST /organizations` (409/`ORGANIZATION_SLUG_TAKEN`).
- **Seguridad:** firma del `id_token` no verificada (D-9); log de acceso saneado; `Referrer-Policy: no-referrer`; errores de identidad sin caché.
- **Frontend:** `/login`, `/auth/callback`, `/account/google`, `/organization`, middleware; textos es/en con paridad.
- **Evidencia:** backend **1314/289** y opt-in **32**; frontend **499**; typecheck/build/typecheck:e2e verdes. **T30 (Google real) no ejecutada** (sin cliente OAuth).

## Spec 012 — cerrada (2026-10-23, PR #8)
- 35/35 tareas + H-1…H-14; navegación `calendar`/`rosters`, `?step=` + `sessionStorage`, `game_format`, límites y retiro lógico; `engine_version` 2026.1. Evidencia: 981/256, frontend 485, E2E verde.

## Specs 011 y anteriores
- **011:** PR #7. **008/009/010:** migraciones 021–023 y §6 aprobada. 001–007 cerradas (005: riesgo Swiss en frío; 007: 021 antes del código).

## Entorno local
- Backend `python:3.14-slim`; frontend en `web` (Node 24/pnpm 12.12.1); E2E en Playwright. La imagen `api` no trae dev deps (`pip install --target /tmp/devdeps`).
- No ejecutes `pnpm run build` con el dev server vivo: reinicia `web`. TypeScript `~6.0.3` (no 7.x).
- Si el volumen se creó con otra `BRACKET_DB_PASSWORD`, alinear `bracket_app` con `ALTER ROLE` (`test_migrate_target.sh` la reajusta).
