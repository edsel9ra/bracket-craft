# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Skills instaladas (2026-10-14)
En `.agents/skills/` además de `sdd` y `find-skills`: `fastapi`, `python-testing-patterns`, `postgresql-table-design`, `pinia` (de antfu), `vue-best-practices`, `nuxt` (del pack `onmax/nuxt-skills`; basado en Nuxt 5.x — ahora ya útil, el proyecto pasó a Nuxt 4).

## Stack actualizado — Fases 1-4 completadas (2026-10-14)
- Backend: fastapi 0.143.1, uvicorn 0.54.0, sqlalchemy 2.1.4, asyncpg 0.32.0, PyJWT 2.15.1, pwdlib 0.3.1, redis 8.1.0, python-socketio 5.17.0, boto3 1.43.113, pytest 9.1.1 (proxies: starlette 1.8.0).
- Frontend: **Nuxt 4.6.1 con layout v4 (`frontend/app/`)**, vue 3.5.44, TS ^5.9.3, vue-tsc 3.3.13, pinia 4.1.0 + @pinia/nuxt 1.0.3, socket.io-client 4.8.4, Node 24 + pnpm 12.11.2 (ci.yml ×2, packageManager, Dockerfile node:24-alpine).
- Compose: postgres **17-alpine** (cadena 001→014 limpia), redis **8-alpine**, **SeaweedFS 4.48** reemplazó a MinIO (repo archivado 2026-04-25): servicio `storage` (API S3 en 9000, filer UI en 9001).
- E2E verificada: migraciones 14 ✔, seed idempotente ✔, test_invitations 2 passed ✔, API/web/filer/Socket.IO 200 ✔, pip-audit limpio ✔, prod-config OK ✔. NO local: Trivy (no instalado aquí).

## Decisiones y porqués
- **SeaweedFS vs Garage/AIStor**: Garage falló (docker-credential helper WSL) y AIStor se reparte por dl.min.io (DNS filtrado aquí); SeaweedFS es Docker Hub + repo activo y pasó probe de 8 checks (get anónimo público ✔, `NoSuchBucketPolicy` tolerado por storage.py ✔).
- **TS 7.0.2 probado y revertido**: vue-tsc 3.3.13 aún no soporta el empaquetado nativo de TS 7 (`./lib/tsc` sin export). Queda para cuando vue-tsc lo soporte.
- **Nuxt 4 endurece `noUncheckedIndexedAccess`**: 9 errores reales corregidos en código (no se desactivó la flag).
- **Age-gate de pnpm**: para pinia 4.1.0/@pinia/nuxt 1.0.3 (publicados hoy) pnpm escribió `minimumReleaseAgeExclude` en pnpm-workspace.yaml — quedó la exclusión documentada y los checks verdes; no repetir bypass sin razón.
- **pnpm audit**: Nuxt 4 bajó las vulns de 21 a 14 (quedan transitivos de nitropack/pèpendiente devtools). Revisar con overrides `pnpm.overrides` si hay parches retrocompatibles.
- `.pnpm-store` ya se desversionó (pnpm 12 lo auto-ignora en `.gitignore` y `git rm --cached` limpió 13.281 archivos del index).
- `init/02_public_projections.sql` revertida a estado pre-012: los init NO son migraciones y crear el estado post-012 desde el init rompía a-migraciones limpias (causa raíz del fallo `cannot drop columns from view`).
- Constitución enmendada a **1.0.1** (solo ruta de `useApi.ts` → `frontend/app/composables/`) — requiere revisión humana por §5.2.
- Trivy pi v0.36.0 sigue al día; no tocar.

## Gotchas de entorno local (WSL)
- **Puertos compartidos con mis-project**: no tener ambos stacks a la vez (5432/6379/8000/frontend 3000). Para alternar: `docker compose -p mis-project stop|start` y `docker compose stop|up -d`.
- `pnpm test` necesita binario oficial de Node (el de la distro da ERR_NO_TYPESCRIPT). Corepack del sistema roto: `npm i -g --prefix /tmp/pnpm-home pnpm@X`.
- Python sin pip/ensurepip en el sistema: venv en /tmp/opencode + pip wheel desde pypi.org (bootstrap.pypa.io no resuelve). pip-audit solo en modo ambiente (`-l`), no `-r` (necesita venv temporal).
- Contenedor `web` escribe `.nuxt` como root en volumen del host: borrar con `docker run -v ... alpine:3 rm -rf` antes de builds locales.
- Healthcheck de SeaweedFS con `localhost` falla (IPv6): usar `127.0.0.1` + `start_period` (boot de raft/filer tarda ~30-60s).
- Los /tmp de opencode son EFÍMEROS al reinicar el server: recrear venv/pnpm-sandboxes.

## Auditoría técnica integral (2026-10-19)
- Informe completo en `docs/auditoria-2026-10-19.md` (3 pasadas: backend/datos, API/seguridad/pruebas, frontend/infra).
- ALTOS: `players` sin RLS filtra PII cross-tenant vía dedupe HMAC; compose de producción no resetea ports/volumes (usar `!reset []`); inmutabilidad de resultados cerrados sin trigger en BD; constitución §3.5 desalineada de ci.yml y sin commit.
- Plan priorizado P0-P2 y matriz R01-R32 en el informe. `specs/` sigue vacía.
- No ejecutado en la auditoría (sin toolchain/Docker): pytest, docker compose config, pip-audit/pnpm audit/Trivy.
