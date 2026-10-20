# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Spec 001 — Correctivos P0 (2026-10-19)
- Implementada y aprobada. R01 (`players` con RLS, migración 015), R02 (overlay de producción), R03 (inmutabilidad de resultados, 016), R04 (versiones alineadas + enmienda 1.1.0). Informe: `docs/auditoria-2026-10-19.md`.
- La excepción §5.1 quedó **retirada** por la spec 003 el 2026-10-19 (run 39361295825, cuatro jobs verdes); se conserva como registro histórico.

## Spec 002 — Cifrado de la fecha de nacimiento (2026-10-19)
- Implementada y cerrada. Migraciones 017/018, backfill `encrypt_birth_dates`, `MIGRATION_TARGET`, edad materializada y `age` en rosters, i18n es/en con paridad.
- Runbook: backup → stop api/worker → 017 → imagen nueva → backfill `--no-deps` → 018 → arranque/smoke. Tras 018 solo *forward-fix*.
- No ejecutado: smoke del runbook ni la secuencia completa en un despliegue real.

## Spec 003 — Deuda de dependencias (2026-10-19)
- **Implementada y cerrada** (T1-T9 + T4b). CI en `main` en verde: run **39361295825**, jobs `infrastructure`, `frontend`, `backend` y `security`.
- La deuda era la cadena de producción de Nuxt (no `devDependencies`). Política: filtro propio `infra/scripts/audit_frontend.py` que falla ante ≥ high con corrección, muestra los no accionables y no persiste listas.
- D-6: `pmOnFail: ignore` en `frontend/pnpm-workspace.yaml` deja el lockfile en **un solo documento** porque Trivy 0.70.0 solo lee el primero; `verify_version_sources.py` acepta ambos formatos. Retirados `package.json` y `pnpm-lock.yaml` de la raíz.
- Constitución **1.2.0** (§3.4 con el comando efectivo). Credencial de Context7 como `{env:CONTEXT7_API_KEY}`. Evidencia: `docs/evidencia-spec-003.md`.
- Siete commits por bloque (filtro, enmienda, CI/guía, lockfile/verificador, cadena raíz, credencial, docs) y push a `main`.

## Riesgo residual
- `braces` 3.0.3 (GHSA-vfj7-8cjw-p6xm) y `node-forge` 1.4.0 (GHSA-86w9-cpqp-85rv), altos y **sin parche upstream**. Visibles en la auditoría; no bloquean.
- Revisión en **cada actualización de dependencias** y en la próxima auditoría técnica; responsable: propietario del producto. Si aparece parche, se adopta en el mismo cambio.

## Pendiente
- Confirmar la revocación de la segunda clave de Context7 (se reexpuso en el árbol y no se usó) y exportar `CONTEXT7_API_KEY`.

## Stack y versiones de referencia (2026-10-19)
- Python 3.14, Node 24, pnpm 12.12.1. Constitución 1.2.0 (historial desde 1.0.0).
- Backend: fastapi 0.143.1, sqlalchemy 2.1.4, asyncpg 0.32.0, PyJWT 2.15.1, redis 8.1.0, python-socketio 5.17.0, boto3 1.43.113, pytest 9.1.1.
- Frontend: Nuxt 4.6.2, vue 3.5.44, TS 5.9.3, vue-tsc 3.3.13, pinia 4.1.0, socket.io-client 4.8.4. Lockfile único con `pmOnFail: ignore`.
- Compose: postgres 17-alpine, redis 8-alpine, SeaweedFS 4.48. Producción sin puertos, `internal` + `edge`, Compose ≥2.24.4.

## Entorno local
- Docker 29.8.2 / Compose 5.5.1. Puertos compartidos con mis-project: no tener ambos stacks.
- Sin pnpm en el host: `node:24-alpine` + `npm i -g --prefix`. Pytest: imagen `bc-api-t007` (no puede escribir `__pycache__` en el repo; `compileall` sobre copia). Trivy: `aquasec/trivy:0.70.0`. `web` escribe `.nuxt` como root.

## Decisiones y gotchas
- TS 7.0.2 revertido (vue-tsc no lo soporta). Nuxt 4 endurece `noUncheckedIndexedAccess`: se corrige en código.
- `init/02_public_projections.sql` en estado pre-012 (los init no son migraciones).
- `trivy-action@v0.36.0` fija Trivy 0.70.0; solo audita npm si el lockfile tiene un único documento.
- La constitución está en CRLF: usar `git -c core.whitespace=cr-at-eol diff --check`.
- `pnpm update --lockfile-only` reescribe rangos en `package.json`: revertirlo y reconciliar con `pnpm install --lockfile-only`.
