# Tareas 001 — Correctivos P0 de la auditoría

Spec: `specs/001-correctivos-p0-auditoria/spec.md`
Plan: `specs/001-correctivos-p0-auditoria/plan.md`

Orden de dependencia: T001 → T002 → T003/T004; T002 → T005; T006, T007 y T008 son independientes de R01/R03. T008 va después de T007. Aplicar siempre 015 antes que 016.

**Nota de validación (segunda ronda, 2026-10-19):** tras la primera validación se corrigieron el aislamiento y el determinismo del test de seed usando una base desechable, se añadieron dos pruebas negativas de FK cross-tenant, y T001 quedó con el ajuste de CI que exporta `DATABASE_ADMIN_URL` para que las pruebas de migración no se salten. Con esas correcciones la implementación pasa la validación funcional, salvo la excepción aprobada del job `security` (§5.1 de la spec) por deuda preexistente de dependencias de desarrollo del frontend (`simple-git` y otros transitivos de `nuxt`).

Cada tarea se ejecuta en una sola invocación del implementador y escribe primero sus pruebas.

---

## T001 — Harness de pruebas PostgreSQL y servicio en CI

**Objetivo:** disponer de una base PostgreSQL efímera en CI, un rol administrador para migrar y un rol de aplicación para testear, con fixtures reutilizables y aislamiento entre pruebas.

**RF:** RF-018 (habilita RF-001 a RF-013).

**Estado:** hecha (2026-10-19); `.github/workflows/ci.yml` ya exporta `DATABASE_ADMIN_URL` en el paso de pruebas de BD, por lo que las pruebas de migración no se saltan en CI.

**Archivos previstos:**
- `.github/workflows/ci.yml`
- `backend/tests/conftest.py`
- `backend/tests/db_helpers.py`
- `backend/tests/test_db_harness.py`

**Pruebas a escribir primero:**
- `test_db_harness.py`: el rol de aplicación existe, no es superusuario y no tiene `BYPASSRLS`.
- El fixture crea una organización y un usuario con `create_organization_with_owner` y establece `app.current_organization_id`/`app.current_user_id`.
- Una consulta tenant devuelve filas con contexto y cero sin contexto.
- La suite unitaria sigue pasando sin `RUN_DATABASE_TESTS=1`.

**Criterios de aceptación:**
- El job de CI levanta PostgreSQL 17 con healthcheck y aplica `infra/postgres/init` y las migraciones con el script real.
- Las migraciones usan el rol administrador; los tests usan `DATABASE_URL` del rol de aplicación y `RUN_DATABASE_TESTS=1`.
- El paso de tests de BD exporta `DATABASE_ADMIN_URL` con el rol administrador, de modo que las pruebas de migración que necesitan crear/aplicar esquemas no se salten silenciosamente en CI.
- Si `DATABASE_ADMIN_URL` falta, la prueba de migración debe fallar explícitamente, no saltarse.
- Las pruebas crean sus propias organizaciones/usuarios y limpian por transacción revertida o borrado acotado.
- Los tests de BD no dependen de `seed_demo` ni de datos demo y pueden ejecutarse en cualquier orden.
- La suite que no necesita BD sigue funcionando sin la variable.

**Verificación:**
```sh
cd backend && pytest -q
cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_db_harness.py
cd backend && python -m compileall -q app
```
En CI, el job de backend debe quedar en verde con el servicio PostgreSQL.

**Commit:** preparación de pruebas; puede ir en un commit propio antes de R01/R03.

---

## T002 — Migración 015: esquema, división de datos, FKs, grants y vistas

**Objetivo:** convertir `players` en tabla tenant-owned y migrar los datos existentes sin perder rosters ni histórico.

**RF:** RF-001, RF-002, RF-003, RF-004, RF-005 (definiciones y wrapper), RF-018.

**Estado:** hecha (2026-10-19).

**Archivos previstos:**
- `infra/postgres/migrations/015_player_catalog_tenant_isolation.sql`
- `backend/tests/test_player_catalog_schema.py`
- `backend/tests/test_player_catalog_migration.py`

**Pruebas a escribir primero:**
- `test_player_catalog_schema.py`: `organization_id NOT NULL`, RLS `ENABLE`/`FORCE`, política tenant, unicidad `(organization_id, document_type, issuing_country, national_id_hmac)`, ausencia de unicidad global, `UNIQUE (id, organization_id)`, FKs compuestas en `rosters`, `match_lineup_snapshots`, `match_events` y `player_suspensions`, grants con `organization_id`, `national_id_encrypted` fuera de `SELECT`, `v_public_match_lineups_unpublished` sin `SELECT` para `bracket_app` y wrapper `v_public_match_lineups` con `SELECT`.
- `test_player_catalog_migration.py`: base en estado 014 con un jugador compartido por dos organizaciones, rosters en ambas, `match_rosters`, una alineación, un evento y una suspensión; tras 015 debe haber dos jugadores, referencias repuntadas, conteos iguales, suspensión coherente y ningún huérfano.
- Prueba de residuo: jugador sin ninguna referencia se elimina.
- Prueba de idempotencia: reejecutar 015 no duplica ni falla.
- Prueba de volumen limpio: init + 001-015 funciona (001-016 se cubre al cerrar T005).

**Criterios de aceptación:**
- La migración agrega `organization_id`, divide por organización, conserva el `id` original para la organización con referencia más antigua y crea copias para las demás.
- Repunta `rosters`, `match_rosters`, `match_lineup_snapshots`, `match_events` y `player_suspensions` sin violar FKs transitorias.
- Elimina jugadores sin referencia; no quedan filas con `organization_id` nulo.
- Reemplaza la unicidad global por la unicidad por organización y agrega las FKs compuestas.
- Habilita y fuerza RLS; actualiza grants sin conceder `UPDATE`/`DELETE` ni exponer `national_id_encrypted`.
- Recrea `v_public_tournament_players` y `v_public_match_lineups_unpublished` con join por organización y `security_barrier = true`, conservando el propietario exento de RLS.
- Mantiene `REVOKE ALL` sobre `v_public_match_lineups_unpublished` para `PUBLIC` y `bracket_app`; no concede `SELECT` sobre la vista cruda.
- Conserva `GRANT SELECT` de `v_public_match_lineups` (wrapper filtrado) a `bracket_app`.
- La migración se aplica sobre volumen limpio y sobre base 014; `sh -n` sigue pasando.
- La verificación de migración usa `DATABASE_ADMIN_URL` exportado por el job de CI; si falta, la prueba falla explícitamente en vez de saltarse.
- No se edita ninguna migración aplicada.

**Verificación:**
```sh
cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_player_catalog_schema.py tests/test_player_catalog_migration.py
sh -n infra/postgres/migrate.sh
```

**Commit:** R01, separado de R03.

---

## T003 — Backend R01: alta, importación masiva, joins y seed

**Objetivo:** adaptar el alta individual, la importación CSV/TXT, las consultas de rosters y `seed_demo` a la deduplicación por organización.

**RF:** RF-001, RF-002, RF-003, RF-004 (seed), RF-018.

**Estado:** hecha (2026-10-19). `_find_or_create_player_record` busca por organización y usa `ON CONFLICT DO NOTHING` con reintento de lectura; los joins del Workspace filtran por organización; `seed_demo` inserta `organization_id`, filtra por organización y verifica que no queden jugadores sin roster.

**Archivos previstos:**
- `backend/app/modules/tournaments/router.py`
- `backend/app/modules/matches/router.py` (revisión de joins con `players`; solo cambios si faltan filtros)
- `backend/scripts/seed_demo.py`
- `backend/tests/test_player_catalog_isolation.py`

**Pruebas a escribir primero:**
- A/B: A registra un documento; B registra el mismo documento y recibe solo sus datos, sin fila, nombre, apellidos, fecha ni foto de A.
- Misma organización: dos altas del mismo documento reutilizan el jugador.
- Importación masiva: usa la misma regla y no consulta un catálogo global.
- Carrera/duplicado: la clave única por organización impide dos registros; el reintento o conflicto no deja datos parciales.
- `seed_demo`: inserta `organization_id`, filtra por organización y deja todos sus jugadores con roster.

**Criterios de aceptación:**
- La búsqueda por HMAC incluye `organization_id` y el `INSERT` escribe `organization_id`.
- La importación masiva y el alta individual comparten helper y regla.
- Las consultas de rosters del Workspace filtran por organización.
- `seed_demo` funciona después de 015, es idempotente y no crea jugadores sin referencia.
- No hay cambios de contrato en la respuesta de roster; el único cambio es no revelar jugadores de otra organización.

**Verificación:**
```sh
cd backend && pytest -q
cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_player_catalog_isolation.py
cd backend && python -m compileall -q app
```
Si el entorno permite el seed:
```sh
docker compose exec api python -m scripts.seed_demo
```

**Commit:** R01, junto con T002/T004 o en commits sucesivos de la misma entrega.

---

## T004 — Proyecciones públicas: vista de jugadores, wrapper y acceso denegado a la cruda

**Objetivo:** verificar que `v_public_tournament_players` y el wrapper `v_public_match_lineups` siguen devolviendo filas sin contexto de organización, sin mezclar organizaciones y sin PII, y que la vista cruda `v_public_match_lineups_unpublished` sigue inaccesible a `bracket_app`.

**RF:** RF-005, RF-018.

**Estado:** hecha (2026-10-19). Los siete casos nuevos viven en `backend/tests/test_public_player_views.py` y la prueba frágil de `test_player_catalog_schema.py` (`count(*) == 0`) se reescribió para no depender de una base vacía. No fue necesario ajustar la migración 015. Verificado con y sin la semilla demo cargada en la misma base.

**Archivos previstos:**
- `backend/tests/test_public_player_views.py`
- `infra/postgres/migrations/015_player_catalog_tenant_isolation.sql` solo si hace falta un ajuste antes de aplicar 015; si ya se aplicó, la corrección va en migración nueva.

**Pruebas a escribir primero:**
- Consulta a `v_public_tournament_players` con `bracket_app` y sin `app.current_organization_id` devuelve las filas del torneo publicado.
- Consulta a `v_public_match_lineups` (wrapper) en las mismas condiciones devuelve solo formación publicada.
- Consulta a `v_public_match_lineups_unpublished` con `bracket_app` falla con permiso denegado.
- `v_public_match_lineups_unpublished` no tiene `SELECT` para `bracket_app` ni `PUBLIC`; `v_public_match_lineups` sí tiene `SELECT` para `bracket_app`.
- Las dos definiciones y el wrapper tienen propietario exento de RLS y no tienen `security_invoker`.
- No aparecen `document_type`, `national_id_encrypted`, `national_id_hmac` ni `birth_date`.
- `photo_url` solo aparece con consentimiento.
- Un torneo de otra organización no aparece.

**Criterios de aceptación:**
- Las dos definiciones que unen `players` usan join por `(id, organization_id)` y `security_barrier = true`.
- `v_public_tournament_players` y `v_public_match_lineups` son accesibles a `bracket_app`; la vista cruda no.
- El propietario sigue exento de RLS; no se cambia a `bracket_app`.
- Los endpoints públicos siguen devolviendo la misma información en los mismos casos.
- La prueba de acceso denegado se ejecuta con el rol de aplicación.

**Verificación:**
```sh
cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_public_player_views.py
```

**Commit:** R01, junto con T002/T003.

---

## T005 — Migración 016 y pruebas de inmutabilidad R03

**Objetivo:** impedir en base de datos cualquier cambio o borrado de un resultado confirmado, sin romper cierre, avance de llaves, bracket reset ni seed.

**RF:** RF-010, RF-011, RF-012, RF-013, RF-018.

**Estado:** hecha (2026-10-19). La migración 016 crea la función `prevent_confirmed_match_result_mutation()` y el trigger `trg_protect_confirmed_match_result` (`BEFORE UPDATE OR DELETE` sobre `matches`), con `IS DISTINCT FROM`, solo cuando `OLD.result_confirmed = TRUE`, sin excepción para `platform_admin` e idempotente. `backend/tests/test_match_result_immutability.py` cubre los once campos protegidos, el borrado, los mismos valores, `updated_at`, cierre normal, resolución administrativa, avance, bracket reset, sentencia masiva, el seed demo y la migración 016 sobre volumen limpio y base migrada desde 015. Verificado con y sin la semilla demo cargada.

**Archivos previstos:**
- `infra/postgres/migrations/016_confirmed_match_result_immutability.sql`
- `backend/tests/test_match_result_immutability.py`

**Pruebas a escribir primero:**
- `UPDATE` directo de cada campo protegido (`home_score_regular`, `away_score_regular`, `home_score`, `away_score`, `home_penalties`, `away_penalties`, `winner_team_id`, `status`, `resolution_type`, `resolution_reason`, `result_confirmed`) falla sobre un partido confirmado.
- `DELETE` de un partido confirmado falla.
- Actualizar con los mismos valores se permite; actualizar solo `updated_at` se permite.
- Cierre normal desde `result_confirmed = FALSE` funciona y confirma.
- Resolución administrativa funciona.
- Avance de llaves y bracket reset funcionan sobre partidos no confirmados.
- Seed de desarrollo sigue cerrando partidos.
- Reejecutar 016 no falla por objetos existentes.

**Criterios de aceptación:**
- Función `prevent_confirmed_match_result_mutation()` y trigger `trg_protect_confirmed_match_result` `BEFORE UPDATE OR DELETE ON matches`.
- La comparación usa `IS DISTINCT FROM` y solo actúa si `OLD.result_confirmed = TRUE`.
- No hay excepción para `platform_admin`.
- La migración se aplica después de 015 y es idempotente.
- No se edita ninguna migración aplicada.

**Verificación:**
```sh
cd backend && RUN_DATABASE_TESTS=1 DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_match_result_immutability.py
sh -n infra/postgres/migrate.sh
```

**Commit:** R03, separado de R01.

---

## T006 — R02: overlay de producción, redes y validación en CI

**Objetivo:** eliminar puertos y montajes de código del perfil de producción, declarar la red interna y la red externa del proxy, conservar los volúmenes de datos y validar el merge en CI.

**RF:** RF-006, RF-007, RF-008, RF-009.

**Estado:** hecha (2026-10-19). El overlay usa `!reset []` para puertos y volúmenes de código y declara `internal` (todos) y `edge` (`external: true`, `name: ${PROXY_NETWORK:-edge}`, solo en `web`). `infra/scripts/assert_production_compose.py` valida el JSON renderizado (puertos, binds, redes, comandos, volúmenes y versión de Compose ≥2.24.4) y la CI ejecuta dev, merge con dummies y aserciones. Verificado localmente con Docker 29.8.2 / Compose 5.5.1.
**Archivos previstos:**
- `docker-compose.production.yml`
- `infra/scripts/assert_production_compose.py`
- `.github/workflows/ci.yml`
- `AGENTS.md`
- `README.md`
- Pruebas unitarias del script (por ejemplo, `backend/tests/test_production_compose_assertions.py` o un test junto al script)

**Pruebas a escribir primero:**
- `validate_production_config` detecta puertos publicados.
- Detecta bind mounts de `./backend`/`./frontend`/`./infra` en `api`, `worker` o `web`.
- Acepta montajes de solo lectura de `./infra/postgres` en `db`/`db-migrate`.
- Exige `web` en `internal` + `edge` y el resto solo en `internal`.
- Exige `edge.external = true` y comandos de producción (`api` sin `--reload`, `web` con `node .output/server/index.mjs`).
- `version_at_least("2.24.3", "2.24.4")` es falso y `("2.24.4", "2.24.4")` verdadero.

**Criterios de aceptación:**
- La configuración combinada no publica ningún puerto.
- `api`, `worker` y `web` no montan código del host; `db`/`db-migrate` conservan solo los montajes de infraestructura de PostgreSQL.
- `postgres_data`, Redis y almacenamiento conservan sus volúmenes.
- La red externa del proxy se declara `external: true` con nombre configurable y solo `web` se une a ella.
- La CI ejecuta `docker compose config -q` para dev y para el merge con variables dummy, y luego las aserciones.
- La documentación indica Compose ≥2.24.4, `PROXY_NETWORK` y el prerrequisito de la red externa.

**Verificación:**
```sh
docker compose config -q
export POSTGRES_PASSWORD=dummy BRACKET_DB_PASSWORD=dummy PLATFORM_ADMIN_EMAIL=dummy@example.test \
  JWT_SECRET=dummy-jwt-secret-with-at-least-32-characters \
  PLAYER_DATA_KEY=dummy-player-key-with-at-least-32-characters \
  INVITATION_TOKEN_KEY=dummy-invitation-key-with-at-least-32-characters \
  DATABASE_URL=postgresql+asyncpg://dummy:dummy@db:5432/dummy \
  CORS_ALLOWED_ORIGINS=http://localhost:3000 \
  STORAGE_PROVIDER=s3 STORAGE_BUCKET=dummy STORAGE_PUBLIC_BASE_URL=http://localhost:9000/dummy \
  FRONTEND_BASE_URL=http://localhost:3000 SMTP_HOST=localhost SMTP_FROM=noreply@example.test \
  NUXT_PUBLIC_API_BASE=http://localhost:8000/api/v1 \
  NUXT_PUBLIC_SOCKET_BASE=http://localhost:8000 \
  NUXT_API_INTERNAL_BASE=http://api:8000/api/v1 \
  PROXY_NETWORK=edge
docker compose -f docker-compose.yml -f docker-compose.production.yml config -q
docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json \
  | python infra/scripts/assert_production_compose.py -
docker compose version --short
```

**Commit:** R02, commit propio separado de R01/R03 y R04.

---

## T007 — R04 técnico: versiones, Dockerfiles, lockfile y puerta de compatibilidad

**Objetivo:** alinear Python 3.14, Node 24 y pnpm 12.12.1 en todas las fuentes técnicas y verificar compatibilidad antes de dar el cambio por válido.

**RF:** RF-014, RF-015, RF-017 (parte documental).

**Estado:** hecha (2026-10-19). Python 3.14, Node 24 y pnpm 12.12.1 alineados en `ci.yml` (Python en `backend` y `security`, pnpm en `frontend` y `security`), `backend/Dockerfile` (`python:3.14-slim`), `frontend/package.json`, `pnpm-lock.yaml` (solo el bloque del gestor en `packageManagerDependencies`; las dependencias de proyecto no cambian), `AGENTS.md` y README. `infra/scripts/verify_version_sources.py` (con `backend/tests/test_version_sources.py`) comprueba la consistencia y la CI lo ejecuta con `--exclude-constitution` (la constitución se valida en T008). Puerta ejecutada: Python 3.14 + requirements + `pytest` (**186 passed, 2 skipped** con PostgreSQL 17 y rol de aplicación; estado tras añadir las pruebas de FK) + `compileall`; Node 24 + pnpm 12.12.1 + `pnpm install --frozen-lockfile` + `pnpm test`/`typecheck`/`build`; `docker build` de `bc-api` y `bc-web`; `pip-audit` limpio. Salvedad honesta: `pnpm audit` (14 advisories en el momento de la validación: `simple-git`, `@simple-git/argv-parser`, `shell-quote`, `brace-expansion`, `braces`, `node-forge` y `serialize-javascript`) y Trivy (9 hallazgos en `pnpm-lock.yaml`: `simple-git`, `argv-parser`, `shell-quote` y `brace-expansion`; el conteo depende de la base de vulnerabilidades) fallan, pero son hallazgos preexistentes idénticos entre `64aa384` y `HEAD`, y actualizar dependencias queda fuera del alcance de R04; el job `security` sigue en rojo bajo la excepción §5.1 hasta una spec aparte.

**Archivos previstos:**
- `.github/workflows/ci.yml`
- `backend/Dockerfile`
- `frontend/package.json`
- `frontend/pnpm-lock.yaml` (solo `packageManagerDependencies`)
- `AGENTS.md`
- `README.md`
- `infra/scripts/verify_version_sources.py` o test equivalente de consistencia
- `backend/tests/test_version_sources.py` (pruebas del verificador)

**Pruebas a escribir primero:**
- Una comprobación de fuentes detecta discrepancias entre `ci.yml`, Dockerfiles, `package.json`, AGENTS y README; la constitución se valida en T008 para no mezclar el commit técnico con la enmienda.
- `parse_semver`/`version_at_least` cubren 3.14, Node 24 y pnpm 12.12.1.
- La puerta de compatibilidad falla si una versión de dependencia o el lockfile (más allá del pin) no es compatible.
- `pnpm install --frozen-lockfile` pasa con el pin nuevo.

**Criterios de aceptación:**
- `ci.yml` usa Python 3.14 y pnpm 12.12.1 en todos los usos; Node 24 se mantiene.
- `backend/Dockerfile` usa Python 3.14.
- `frontend/package.json` declara `pnpm@12.12.1`.
- En `pnpm-lock.yaml` solo cambia `packageManagerDependencies`; no cambian dependencias ni el resto del lockfile.
- AGENTS y README declaran las versiones, Compose ≥2.24.4 y el prerrequisito de red.
- La puerta de compatibilidad pasa: Python 3.14 + requirements + tests + compileall; Node 24 + pnpm 12.12.1 + install frozen + test/typecheck/build; imágenes; `pip-audit`, `pnpm audit`, Trivy.
- Si algo falla, se detiene y se reporta; no se actualizan dependencias.
- No se toca `docs/constitution.md` en esta tarea (va en T008).

**Verificación:**
```sh
python3.14 -m venv /tmp/bc-py314
. /tmp/bc-py314/bin/activate
python -m pip install -r backend/requirements.txt
cd backend && pytest -q && python -m compileall -q app

corepack enable && corepack prepare pnpm@12.12.1 --activate
cd frontend && pnpm install --frozen-lockfile
cd frontend && pnpm test && pnpm run typecheck && pnpm run build

docker build -t bc-api backend
docker build -t bc-web frontend

pip-audit -r backend/requirements.txt
cd frontend && pnpm audit --prod --audit-level high
trivy fs . --skip-dirs frontend/node_modules,frontend/.pnpm-store,.venv \
  --ignore-unfixed --severity CRITICAL,HIGH --exit-code 1

python infra/scripts/verify_version_sources.py --exclude-constitution
git diff -- frontend/pnpm-lock.yaml   # solo packageManagerDependencies
```
Si el entorno no tiene Python 3.14, pnpm 12.12.1 o Docker, ejecutar la puerta en CI y declarar lo no ejecutado.

**Commit:** R04 técnico, commit propio separado de R01/R03 y de la enmienda.

---

## T008 — Enmienda constitucional 1.1.0 (commit separado)

**Objetivo:** regularizar y corregir §3.5 en la constitución, dejando cabecera, historial y reglas coherentes, con revisión humana y sin mezclar cambios funcionales.

**RF:** RF-016, RF-017.

**Estado:** hecha (2026-10-19); revisión humana del usuario registrada.

**Archivos previstos:**
- `docs/constitution.md`

**Pruebas a escribir primero:**
- Comprobación de que la cabecera declara `1.1.0`.
- Comprobación de que la última fila del historial es `1.1.0` y la fila `1.0.1` se conserva.
- Comprobación de que §3.5 declara Python 3.14, Node 24 y pnpm 12.12.1.
- Comprobación de que `git status` no deja cambios pendientes en la constitución tras el commit.
- Revisión humana registrada y distinta del autor.

**Criterios de aceptación:**
- La constitución pasa a `1.1.0`, con fecha de última actualización del cambio.
- La fila `1.1.0` explica el motivo, las reglas afectadas y el impacto.
- La enmienda regulariza el cambio ya presente en `HEAD` (§3.5 con 3.14/12.12.2) y lo corrige a 12.12.1.
- Se justifica el incremento menor frente al parche recomendado por la auditoría.
- La enmienda se commitea aparte de T007 y de R01/R03.
- La revisión humana queda registrada.

**Verificación:**
```sh
grep -n "Versión:" docs/constitution.md
grep -n "1.1.0" docs/constitution.md
grep -n "Python 3.14" docs/constitution.md
python infra/scripts/verify_version_sources.py
git status --short docs/constitution.md
git show --stat --oneline HEAD
```
La revisión humana se registra fuera del repositorio o en el flujo de revisión del proyecto.

**Commit:** solo `docs/constitution.md`, separado de T007.
