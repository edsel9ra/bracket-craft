# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Spec 001 — Correctivos P0 de la auditoría (2026-10-19)
- `specs/001-correctivos-p0-auditoria/` (spec, plan y tasks) implementada y validada funcionalmente; validación documental final en curso. `specs/` ya no está vacía.
- R01: `players` tenant-owned con RLS, unicidad por organización, FKs compuestas y migración 015. R02: overlay de producción sin puertos, red interna + red externa del proxy (`edge`/`PROXY_NETWORK`), sin montajes de código y merge validado en CI. R03: trigger de inmutabilidad de resultados confirmados (migración 016). R04: versiones alineadas y enmienda constitucional.
- Excepción §5.1 aprobada por el usuario: el job `security` queda en rojo por deuda preexistente de dependencias de desarrollo del frontend (`simple-git` y otros transitivos de `nuxt`: `shell-quote`, `brace-expansion`, `braces`, `node-forge`, `serialize-javascript`); `pip-audit` limpio. La lista es idéntica entre `64aa384` y `HEAD` y ajena a R01-R04. Retiro: spec aparte; revisable en la próxima auditoría.
- Spec 001 commiteada en 8 commits separados: `2220efd` harness T001, `f0f185f` R01, `e9ed898` R03, `9f5842c` R02, `47fd682` R04 técnico, `7c9817c` enmienda constitucional 1.1.0, `517f514` docs SDD y `f2f0b3e` actualización de MEMORY; árbol limpio y sin push. El job `security` sigue en rojo por la deuda preexistente de dependencias de desarrollo del frontend (`simple-git` y otros transitivos de `nuxt`) bajo la excepción §5.1.
- Informe de la auditoría: `docs/auditoria-2026-10-19.md` (matriz R01-R32, plan P0-P2).

## Stack y versiones de referencia (2026-10-19)
- **Python 3.14, Node 24 y pnpm 12.12.1**. Constitución en **1.1.0** (la fila 1.0.1 se conserva).
- Backend: fastapi 0.143.1, uvicorn 0.54.0, sqlalchemy 2.1.4, asyncpg 0.32.0, PyJWT 2.15.1, redis 8.1.0, python-socketio 5.17.0, boto3 1.43.113, pytest 9.1.1.
- Frontend: Nuxt 4.6.1 (layout v4, código en `frontend/app/`), vue 3.5.44, TS ^5.9.3, vue-tsc 3.3.13, pinia 4.1.0, socket.io-client 4.8.4.
- Compose: postgres 17-alpine, redis 8-alpine, SeaweedFS 4.48 (`storage`; S3 en 9000, UI en 9001). Producción: sin puertos, `internal` para todo el stack y solo `web` en `edge` externa.
- Validación de producción: **Docker Compose ≥2.24.4** con `!reset []`/`!override` (las secuencias de Compose se concatenan; `ports: []` no anula). CI valida dev, el merge con dummies y el JSON renderizado.

## Entorno local
- Docker 29.8.2 y Compose 5.5.1 disponibles en este entorno.
- Suite de BD en CI con PostgreSQL 17 de servicio; rol administrador para migrar (`DATABASE_ADMIN_URL`) y `bracket_app` para testear (`DATABASE_URL`, sin superusuario ni `BYPASSRLS`).
- Puertos compartidos con mis-project: no tener ambos stacks a la vez (5432/6379/8000/3000).
- `pnpm test` requiere Node oficial; corepack del sistema roto (`npm i -g --prefix /tmp/pnpm-home pnpm@X`). Sin pip/ensurepip: venv en /tmp/opencode. Los /tmp de opencode son efímeros al reiniciar.
- Contenedor `web` escribe `.nuxt` como root: limpiar con `docker run -v ... alpine:3 rm -rf`. SeaweedFS: healthcheck con `127.0.0.1` + `start_period`.

## Decisiones y gotchas
- TS 7.0.2 revertido (vue-tsc 3.3.13 aún no lo soporta). Nuxt 4 endurece `noUncheckedIndexedAccess`: se corrigen los errores en código, no se desactiva la flag.
- SeaweedFS elegido sobre Garage/AIStor (Docker Hub, repo activo, probe de 8 checks).
- `init/02_public_projections.sql` revertida a estado pre-012: los init no son migraciones y crear el estado post-012 rompía volúmenes limpios (`cannot drop columns from view`).
- Trivy con `aquasecurity/trivy-action@v0.36.0` sigue al día; no tocar.
