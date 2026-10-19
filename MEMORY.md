# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Spec 001 — Correctivos P0 de la auditoría (2026-10-19)
- `specs/001-correctivos-p0-auditoria/` (spec, plan y tasks) implementada y validada funcionalmente; correcciones documentales aplicadas y aprobadas.
- R01: `players` tenant-owned con RLS, unicidad por organización, FKs compuestas y migración 015. R02: overlay de producción sin puertos, red interna + `edge`/`PROXY_NETWORK`, sin montajes de código y merge validado en CI. R03: trigger de inmutabilidad de resultados confirmados (016). R04: versiones alineadas y enmienda constitucional 1.1.0.
- Excepción §5.1 **vigente**: el job `security` sigue en rojo por deuda preexistente de dependencias de desarrollo del frontend (`simple-git` y transitivos de `nuxt`: `shell-quote`, `brace-expansion`, `braces`, `node-forge`, `serialize-javascript`); `pip-audit` limpio. Lista idéntica entre `64aa384` y `HEAD`, ajena a R01-R04. Retiro: spec aparte; revisable en la próxima auditoría.
- Commits por bloque (harness T001, R01, R03, R02, R04 técnico, enmienda 1.1.0, docs SDD, MEMORY); sin push. Informe: `docs/auditoria-2026-10-19.md`.

## Spec 002 — Cifrado de la fecha de nacimiento (2026-10-19)
- `specs/002-cifrado-fecha-nacimiento/`: **implementada y aprobada por el usuario (2026-10-19), cerrada**. T001-T010 hechas.
- Migraciones **017** (esquema intermedio: `birth_date_encrypted`, edad materializada, revoca `SELECT`/`INSERT` de `birth_date`, recrea la vista) y **018** (fallo cerrado, `NOT NULL`, `DROP birth_date`, grants finales; detecta vistas, índices y funciones dependientes). 001-016 intactas.
- Backfill: `python -m scripts.encrypt_birth_dates` con `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY`; verifica clave y HMAC contra un documento cifrado, lotes de 500, idempotente/reanudable, sin PII en logs y **sin rama de confirmación**: con filas y sin documento cifrado aborta.
- `MIGRATION_TARGET` (vacía o `NNN`) en `migrate.sh` y `db-migrate`; valida checksums de todos los archivos y solo omite la aplicación posterior. Runbook: backup → stop api/worker → 017 → imagen nueva → backfill one-off `--no-deps` → 018 → arranque/smoke.
- Edad a nivel de jugador (`age_at_reference`/`age_reference_year`); `age` ajustada por año del torneo **solo** en `GET /tournaments/{id}/rosters`; alta/importación no cambian; un jugador reutilizado conserva fecha y edad (la edad ajustada sí sigue el delta de cada torneo); el seed falla cerrado ante fecha imposible; UI i18n es/en con paridad completa.
- Correcciones de la validación: seed con fallo cerrado, las cuatro pruebas de RF-011 (29 de febrero, seed imposible, delta de `public_age`, paridad i18n), índice dependiente en 018, vista sin descifrado ni subconsultas, edad ajustada del reutilizado y rama no aprobada del backfill retirada.
- Verificado en base limpia: **242 passed + 2 skipped** (skips de invitaciones opt-in); con seed demo **244 passed**; frontend **19 tests**, `typecheck` y `build` OK; `compileall`, `sh -n`, `test_migrate_target.sh`, compose dev/merge de producción. No ejecutado: smoke del runbook ni la secuencia 017→backfill→018 en un despliegue real.

## Pendiente
- **Deuda de dependencias de desarrollo del frontend:** mantiene en rojo el job `security` (§5.1 de la constitución, excepción vigente de la spec 001). Siguiente bloque de trabajo: resolverla con una spec propia.

## Stack y versiones de referencia (2026-10-19)
- **Python 3.14, Node 24 y pnpm 12.12.1**. Constitución **1.1.0** (fila 1.0.1 conservada).
- Backend: fastapi 0.143.1, uvicorn 0.54.0, sqlalchemy 2.1.4, asyncpg 0.32.0, PyJWT 2.15.1, redis 8.1.0, python-socketio 5.17.0, boto3 1.43.113, pytest 9.1.1. Frontend: Nuxt 4.6.1 (layout v4, código en `frontend/app/`), vue 3.5.44, TS ^5.9.3, vue-tsc 3.3.13, pinia 4.1.0, socket.io-client 4.8.4.
- Compose: postgres 17-alpine, redis 8-alpine, SeaweedFS 4.48 (`storage`; S3 9000, UI 9001). Producción: sin puertos, `internal` para todo y solo `web` en `edge` externa.
- Validación de producción: **Docker Compose ≥2.24.4** con `!reset []`/`!override` (las secuencias se concatenan; `ports: []` no anula). CI valida dev, el merge con dummies y el JSON renderizado.

## Entorno local
- Docker 29.8.2 y Compose 5.5.1 disponibles. Puertos compartidos con mis-project: no tener ambos stacks a la vez (5432/6379/8000/3000).
- Suite de BD en CI con PostgreSQL 17 de servicio; rol administrador para migrar (`DATABASE_ADMIN_URL`) y `bracket_app` para testear (`DATABASE_URL`, sin superusuario ni `BYPASSRLS`).
- `pnpm test` requiere Node oficial; corepack del sistema roto (`npm i -g --prefix /tmp/pnpm-home pnpm@X`). Sin pip/ensurepip: usar las imágenes `bc-api-t007` y `node:24-alpine` montando el repo; el venv de `/tmp/opencode` se vacía entre sesiones. Contenedor `web` escribe `.nuxt` como root: limpiar con `docker run -v ... alpine:3 rm -rf`. SeaweedFS: healthcheck con `127.0.0.1` + `start_period`.

## Decisiones y gotchas
- TS 7.0.2 revertido (vue-tsc 3.3.13 aún no lo soporta). Nuxt 4 endurece `noUncheckedIndexedAccess`: se corrigen los errores en código, no se desactiva la flag.
- SeaweedFS elegido sobre Garage/AIStor (Docker Hub, repo activo, probe de 8 checks).
- `init/02_public_projections.sql` revertida a estado pre-012: los init no son migraciones y crear el estado post-012 rompía volúmenes limpios (`cannot drop columns from view`).
- Trivy con `aquasecurity/trivy-action@v0.36.0` sigue al día; no tocar.
