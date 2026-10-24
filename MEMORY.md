# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Spec 012 implementada, validada (veredicto APROBADO) y cerrada (2026-10-23).** Rama y PR abiertos para revisión en CI. Última cerrada en `main`: **011** (2026-10-22).
- **Constitución 1.4.0** (job `e2e` en la §4). **`main` protegida:** cinco *required checks*, *strict*, sin force push; los administradores pueden saltar la regla.

## Spec 012 — formularios asistidos, navegación, formato y límites (implementada 2026-10-23)
- **35/35 tareas y correcciones H-1…H-14 (H-5 sustituida por H-14); 4 hitos; sin migraciones** (reutiliza `rosters.is_active` y sus índices parciales). Esquema local en **023**.
- **Navegación:** configuración en `/workspace/tournaments/{id}` (`#resumen`, `#configuracion`, `#equipos`); calendario y plantillas con ruta propia (`?stage=`/`?team=`); `#calendario` y `#plantillas` redirigen con reemplazo de historial.
- **Asistentes (reglas, fases, equipos):** «Configuración» se muestra en solo lectura a `viewer` (visibilidad, no permiso); el paso vive **solo** en `?step=` (`useWizardStep` lo deriva de la dirección, `replace` al montar y `push` por cambio; nunca `history.replaceState`) y el borrador en `sessionStorage` por usuario/organización/torneo/versión/asistente, nunca en servidor.
- **Formato y límites:** `game_format` (`5v5`/`7v7`/`9v9`/`11v11`, default `11v11`) es declarativo y solo avisa; `min/max_players_per_team` ≥ 0, 0/ausente = sin límite, `min ≤ max` solo con ambos > 0 y cadena vacía **422**; cuentan jugadores **activos**.
- **Bloqueos 409 `ROSTER_SIZE_OUT_OF_RANGE`:** inscribir en fase, alta de equipo con `stage_id` (individual y lote) y primer segmento; editar la plantilla nunca se bloquea por tamaño.
- **Retiro lógico RC-1:** `PATCH …/rosters/{id}/status` (`{is_active}`) idempotente, sin auditoría, 404 entre organizaciones; el retiro es la única excepción al bloqueo por jornada (RL-1) y la reactivación se comporta como un alta (RA-1: bloqueo, jugador ya activo y dorsal).
- **Duración H3:** un único máximo efectivo para operación y cierre; `limits` gana `max_minute_regular`, `max_minute_extra`, `extra_time_enabled` y `penalties_enabled`; `resolution_type` opcional en segmento/interrupción; 409 `RESOLUTION_NOT_ENABLED`. La resolución prevista solo vive en la sesión de la pestaña.
- **i18n y contrato:** posiciones y roles desde `utils/i18nCatalog.ts`/`positions.ts`; `engine_version` sigue en **2026.1** (las tres claves nuevas quedan fuera del contrato cerrado y el formato no altera alineaciones).
- **Evidencia final (2026-10-23, reejecutada al cerrar):** backend `pytest -q` **981 passed / 256 skipped**; frontend `pnpm test` **485/485**; `typecheck`, `build` y `typecheck:e2e` en verde; E2E **VERDE (0)** con 5 pruebas (`operation-flow` 87.9 s, 29 transiciones); `infra/postgres/migrations/` sin cambios.
- **E2E:** la condición de fin de un cambio de paso es `?step=` en la dirección; sin esperarla, la navegación pendiente revierte el paso siguiente. `server.log` puede quedar no disponible sin Docker CLI (declarado, no invalidante).
- **Riesgos/opcionales que quedan:** relay sin filtro de rol (mitigación de revalidación cada 30 s, spec 011); sin API incremental ni anulación de eventos de acta cerrada (R11); elegir la vía de alta ya muestra su paso (RF-011) y el segmento en el límite se crea antes de la planilla.
- **Pendiente:** PR y revisión en CI; validación RF por RF con QA y despliegue (la 012 no añade migraciones).

## Spec 011 — cierre de huecos (cerrada 2026-10-22)
- PR **#7** (`6fa19c3`); CI en verde con `e2e`. C-2 atómica, miembro sin rol 403 real, sonda de outbox, mensajes de fallo y artefactos E2E. **Sin migraciones.**

## Specs 008/009 y anteriores
- **008:** PR #3; migraciones 022/023. **009:** PR #5; C-1 revocada 409, C-2 reapertura, `code` aditivo, salud 90/10 s. **010:** E2E del reintento en el contenedor oficial de Playwright. Ambas con **§6 aprobada**.
- 001–004 cerradas; 005 con riesgo residual de sorteos Swiss en frío; 006 PR #1; 007 PR #2 (migración 021 antes del código).

## Entorno local
- Backend: `python:3.14-slim` con repo montado; frontend en el servicio `web` (Node 24/pnpm 12.12.1); E2E en `mcr.microsoft.com/playwright:v1.64.1-noble` con red host.
- La imagen `api` **no** trae `requirements-dev`: `pip install --target /tmp/devdeps -r requirements-dev.txt` y `PYTHONPATH=/tmp/devdeps`; monta el repo en `/repo` y ejecuta pytest desde `/repo/backend` con `PYTHONPYCACHEPREFIX` (los tests de contrato leen `/.env.example` y `docs/`).
- **No ejecutes `pnpm run build` en `web` con el servidor de desarrollo vivo:** reemplaza `.nuxt` y sirve chunks rotos (la navegación del E2E se queda en la página anterior). Reinicia `web` tras el `build`.
- Base local en **023** con smoke OK. Si el volumen se creó con otra `BRACKET_DB_PASSWORD`, `bracket_app` conserva la clave vieja (`127.0.0.1` es `trust`): alinear con `ALTER ROLE`.

## Pendiente
- **Despliegue en servidor:** paquete en `docs/runbook-despliegue-019-023.md`; la 012 no añade migraciones.
- TypeScript fijado en **`~6.0.3`**; no subir a 7.x (`vue-tsc` rompe `typecheck`).
