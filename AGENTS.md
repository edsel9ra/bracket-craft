# Guía para Agentes: Bracket Craft

Plataforma multi-tenant para crear y operar torneos de fútbol con reglas configurables, fases componibles y resultados en tiempo real.

## Fuentes de Verdad

Ante cualquier duda, consulta en este orden:

1. `docs/constitution.md`: principios innegociables, reglas de implementación y criterios obligatorios. Tiene precedencia sobre cualquier otro documento.
2. `README.md`: alcance del producto, flujo local, datos demo, seguridad y modelo de acceso público/privado.
3. `specs/NNN-nombre/` (`spec.md`, `plan.md`, `tasks.md`): requisitos, diseño y tareas de cada funcionalidad desarrollada con SDD.
4. `MEMORY.md`: estado y decisiones del trabajo SDD en curso.
5. `docker-compose.yml` y `docker-compose.production.yml`: servicios, puertos, variables y diferencias entre desarrollo y producción.
6. `.env.example`: variables de entorno y defaults **solo de desarrollo**.
7. `infra/postgres/migrations/`: fuente de verdad del esquema de base de datos (migraciones numeradas).
8. `backend/app/main.py`: registro de routers y punto de entrada de la API.
9. `backend/app/modules/`: límites de cada funcionalidad del backend.
10. `frontend/app/composables/useApi.ts`: contrato de llamadas HTTP del frontend.
11. `.github/workflows/ci.yml`: lista autoritativa de verificaciones (se ejecuta en cada `push` y `pull_request`, con permisos `contents: read`).
12. Documentación interactiva de la API en `http://localhost:8000/docs`.

Si este archivo contradice a la constitución, gana la constitución. Si contradice al código o a la CI, gana el código/CI. Actualiza este archivo en el mismo cambio.

## Stack

- **Backend:** FastAPI, SQLAlchemy asíncrono y PostgreSQL (Python 3.14 en CI).
- **Frontend:** Nuxt 4, Vue 3 y Pinia (Node 24 y pnpm 12.12.1 en CI). Layout Nuxt 4: el código de app vive en `frontend/app/`.
- **Procesamiento:** Redis y worker asíncrono de outbox.
- **Tiempo real:** Socket.IO.
- **Almacenamiento de archivos:** SeaweedFS con API S3 (fotos de jugadores). Antes: MinIO (repositorio archivado el 2026-04-25).
- **Infraestructura:** Docker Compose.

## Límites del Proyecto

- No existe gestor de paquetes en la raíz. Ejecuta comandos Python desde `backend/` y comandos pnpm desde `frontend/`.
- Las rutas `/` y `/tournaments/{id}` son **públicas**. El Workspace (`/workspace`) requiere sesión y una organización activa validada.
- La administración global vive en `/admin`, separada del Workspace. Requiere un registro en `platform_admins` y no puede editar resultados ni versiones publicadas.
- `scripts.seed_demo` es solo para desarrollo/local: no es una migración ni un comando de producción.
- `scripts.encrypt_birth_dates` es un comando operativo de despliegue, no un seed: requiere `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY` y se ejecuta como servicio one-off entre las migraciones 017 y 018.
- La fecha de nacimiento de los jugadores se almacena solo cifrada (`players.birth_date_encrypted`) y es *write-only* para el rol de aplicación; la edad y el año de referencia son los datos derivados legibles.
- Las proyecciones públicas **nunca** exponen documentos de identidad ni fechas de nacimiento. `photo_url` solo se devuelve si el roster tiene consentimiento de imagen.
- La formación táctica solo es pública después de publicarse explícitamente desde el Workspace.
- Las versiones de torneo son inmutables una vez publicadas.
- No edites migraciones ya aplicadas; agrega una nueva.

## Arquitectura Clave

- **Multi-tenancy con RLS:** las tablas tenant-owned usan Row Level Security. El backend fija `app.current_organization_id` y `app.current_user_id` dentro de cada transacción.
- **Torneos:** torneos con versiones inmutables, fases componibles (Round Robin, grupos, playoffs), equipos y partidos. Puntuación, desempates, disciplina y transferencias se configuran con JSON.
- **Actas de partido:** el cierre registra goles, tarjetas y suspensiones, y emite eventos al outbox.
- **Outbox + worker + Redis:** los eventos se procesan de forma asíncrona y alimentan el tiempo real con Socket.IO. El stream es transporte de mejor esfuerzo con un tope fijo de 10 000 entradas aproximado; no es duradero ni la fuente de verdad.
- **Autenticación:** email/password; Google OAuth preparado mediante `auth_identities`. Membresías y RBAC por organización.
- **API pública:** `/api/v1/tournaments/public`, `/api/v1/tournaments/public/{id}/standings` y `/api/v1/tournaments/public/{id}/matches`.
- **Fotos:** se firman en lote, con un cliente cacheado por proceso y endpoint de firma, siempre después de cerrar la transacción. El público degrada a `photo_url: null`, el Workspace responde 503 y se registra una sola entrada por respuesta.
- **Swiss acotado:** tope de 64 equipos, presupuesto de 50 000 evaluaciones de pares (40 000 búsqueda + 10 000 reserva) y timeout de 10 s en un ejecutor dedicado de 2 hilos. 422 por tope; 409 por presupuesto, sorteo imposible, timeout o estado cambiado; los `ValueError` de validación no cambian.
- **Conexión:** `statement_timeout` de 15 s, `idle_in_transaction_session_timeout` de 30 s y pool 10 + 10 con espera de 10 s por proceso. El agotamiento responde 503 y se registra una sola vez; la API registra los valores efectivos al arrancar. `scripts.encrypt_birth_dates` usa su propia conexión administrativa (`DATABASE_ADMIN_URL`) y no hereda estos timeouts ni el pool.
- **Importación de plantillas:** CSV/TXT con `first_name`, `last_name`, `national_id`, `birth_date` y `dorsal_number`; `photo_filename` enlaza imágenes JPG/PNG/WEBP de un ZIP opcional.

## Comandos

### Arranque local

```sh
cp .env.example .env
docker compose up --build
```

- Frontend: `http://localhost:3000`
- API / documentación: `http://localhost:8000/docs`
- Almacenamiento (SeaweedFS): `http://localhost:9001` (UI de archivos); API S3 en `http://localhost:9000`

### Datos demo (solo desarrollo)

```sh
docker compose exec api python -m scripts.seed_demo
```

Es idempotente e imprime el `tournament_id`. Credenciales demo:

- Email: `demo.owner@bracketcraft.dev`
- Contraseña: `Demo1234!`
- Organización: `Demo Federation` (`demo-federation`)

### Frontend fuera de Docker

```sh
cd frontend
pnpm install
pnpm dev
```

### Cifrado de la fecha de nacimiento (runbook)

La fecha completa se guarda cifrada en `players.birth_date_encrypted` y queda fuera del `SELECT` de `bracket_app`; `age_at_reference` y `age_reference_year` alimentan `age`. Sobre una base con datos históricos aplica la secuencia **017 → imagen nueva → backfill → 018** con `api` y `worker` detenidos. `MIGRATION_TARGET` es una variable no secreta del servicio `db-migrate` (vacía aplica todas las migraciones). El runbook completo, con copia de seguridad verificada, smoke y reversión, está en `README.md`.

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre017.dump"
$COMPOSE stop api worker
MIGRATION_TARGET=017 $COMPOSE run --rm db-migrate
$COMPOSE build api
export DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-bracket_craft}"
$COMPOSE run --rm --no-deps -e DATABASE_ADMIN_URL -e PLAYER_DATA_KEY \
  api python -m scripts.encrypt_birth_dates
MIGRATION_TARGET=018 $COMPOSE run --rm db-migrate
$COMPOSE up -d api worker
```

- El backfill debe salir 0; es idempotente y reanudable y solo procesa filas pendientes.
- `--no-deps` evita que el one-off dispare `db-migrate` con el target por defecto y aplique la 018 antes de tiempo.
- Reversión: antes de 017, restaurar el backup y la imagen anterior; entre 017 y 018, corregir y reintentar el backfill (la app antigua no puede escribir la fecha); después de 018, solo *forward-fix* con una migración nueva.

### Verificación (mismos checks que CI)

```sh
python -m pip install -r backend/requirements.txt
cd backend && pytest -q
cd backend && python -m compileall -q app
cd frontend && pnpm install --frozen-lockfile
cd frontend && pnpm test
cd frontend && pnpm run typecheck
cd frontend && pnpm run build
sh -n infra/postgres/migrate.sh
# Runner de MIGRATION_TARGET (requiere PostgreSQL local; misma prueba que CI)
docker run --rm --network host -v "$PWD/infra:/infra:ro" \
  -e PGHOST=127.0.0.1 -e PGPORT=5432 -e PGUSER=postgres \
  -e PGPASSWORD=postgres_test_password \
  postgres:17-alpine sh /infra/scripts/test_migrate_target.sh
docker compose config -q
pip-audit -r backend/requirements.txt
AUDIT_JSON="/tmp/pnpm-audit.json"
trap 'rm -f "$AUDIT_JSON"' EXIT
if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
```

La auditoría del frontend se ejecuta desde la raíz con el bloque anterior: `infra/scripts/audit_frontend.py` falla ante cualquier hallazgo `high` o `critical` con corrección publicada, muestra los no accionables (incluidos los que no tienen parche) para su revisión y no persiste exclusiones. No uses listas de GHSA ni flags que persistan exclusiones, como `--ignore-unfixable`, `audit.ignore` o `auditConfig.ignoreGhsas`.

La validación de producción exige **Docker Compose 2.24.4 o superior**, porque el overlay usa `!reset`/`!override` y la comparación de versiones incluye el parche. Con variables dummy (nunca secretos reales) se valida el merge real de despliegue (desarrollo y luego producción):

```sh
docker compose version --short
python3 infra/scripts/assert_production_compose.py --compose-version "$(docker compose version --short)"

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
  | python3 infra/scripts/assert_production_compose.py -
```

El overlay no publica puertos, no monta código del host en `api`, `worker` ni `web` y deja todos los servicios en la red interna `internal`; solo `web` se une a la red externa del proxy.

Además, CI ejecuta un escaneo de sistema de archivos con Trivy (`aquasecurity/trivy-action@v0.36.0`). Equivale localmente a:

```sh
trivy fs . --skip-dirs frontend/node_modules,frontend/.pnpm-store,.venv --ignore-unfixed --severity CRITICAL,HIGH --exit-code 1
```

## Runtime

- **Servicios de Docker Compose:** PostgreSQL, `db-migrate` (job de una sola ejecución), API, worker, Redis, `storage` (SeaweedFS) y web.
- **Inicialización de PostgreSQL:** `infra/postgres/init/` solo corre en el primer arranque del volumen.
- **Migraciones:** `infra/postgres/migrate.sh` aplica las migraciones numeradas de `infra/postgres/migrations/` una sola vez y las registra en `schema_migrations` con checksum SHA-256. `MIGRATION_TARGET` (vacía o `NNN`; no existe una bandera `--target`) limita la aplicación a esa versión, valida los checksums de todos los archivos y no desaplica nada.
- **Cifrado de la fecha de nacimiento:** las migraciones 017 y 018 se aplican en dos fases con `MIGRATION_TARGET` y el backfill one-off `python -m scripts.encrypt_birth_dates` (`DATABASE_ADMIN_URL` + `PLAYER_DATA_KEY`, `--no-deps`). La 018 falla de forma cerrada si quedan pendientes.
- **Producción:** `APP_ENV=production` con `docker-compose.production.yml`, que no publica ningún puerto, elimina los montajes de código de `api`, `worker` y `web` con `!reset`, desactiva `--reload`, construye el frontend estático y exige secretos y URLs de producción. El backend rechaza los defaults conocidos.
- **Redes de producción:** todos los servicios viven en la red interna `internal`; solo `web` se une además a la red externa del proxy (`edge` por defecto, configurable con `PROXY_NETWORK`). El operador debe crear esa red antes de desplegar (`docker network create "$PROXY_NETWORK"`); el compose no la crea. Requiere Docker Compose **2.24.4 o superior** (`!reset`/`!override`).
- **Secretos a cambiar fuera de desarrollo:** `JWT_SECRET`, `PLAYER_DATA_KEY`, `INVITATION_TOKEN_KEY`, credenciales de base de datos y almacenamiento; además activar `AUTH_COOKIE_SECURE`. Inyéctalos con secretos externos.
- **Pool por proceso:** cada worker de la API y el worker del outbox tienen su propio engine y pool (hasta 20 conexiones). Con `API_WORKERS=2` y un worker son 2 × 20 + 20 = 60 conexiones teóricas frente a las 100 por defecto de PostgreSQL; subir workers o bajar `max_connections` exige revisar el agregado. Las constantes efectivas (15 s / 30 s, 10 + 10, espera 10 s) las registra la API al arrancar.
- **Primer admin de plataforma:** tras registrar la cuenta, indica `PLATFORM_ADMIN_EMAIL` en `.env`.

## Estructura del Proyecto

```text
AGENTS.md                    Guía para agentes (este archivo)
MEMORY.md                    Estado y decisiones del trabajo SDD
docs/
  constitution.md            Constitución del proyecto
specs/
  NNN-nombre/                spec.md, plan.md y tasks.md por funcionalidad
.agents/
  skills/sdd/SKILL.md        Skill de Spec-Driven Development
backend/                     API FastAPI (async SQLAlchemy)
  app/main.py                Registro de routers
  app/modules/               Límites por funcionalidad
  scripts/                   Utilidades de desarrollo (seed_demo) y operativas (encrypt_birth_dates)
  tests/                     Pruebas pytest
frontend/                    Nuxt 4 / Vue 3 / Pinia (código de app en frontend/app/)
  app/composables/useApi.ts   Cliente HTTP centralizado
infra/postgres/
  init/                      Configuración inicial de la base de datos
  migrations/                Migraciones SQL numeradas
  migrate.sh                 Ejecutor de migraciones con checksums
infra/scripts/
  assert_production_compose.py  Aserciones del merge dev+prod (CI)
  verify_version_sources.py    Consistencia de versiones de referencia (CI)
  test_migrate_target.sh       Pruebas del runner con MIGRATION_TARGET (CI)
docker-compose.yml           Entorno de desarrollo
docker-compose.production.yml  Perfil de producción
.env.example                 Defaults solo de desarrollo
```

## Convenciones Clave

- **RLS obligatorio:** llama a `set_rls_context()` dentro de la transacción y **antes** de cualquier consulta tenant, fijando ambos valores de sesión.
- **Rol de base de datos:** el rol de la aplicación no debe ser superusuario ni tener `BYPASSRLS`.
- **Migraciones:** cada cambio de esquema es la siguiente migración SQL numerada. Nunca edites una ya aplicada (el checksum la rechaza).
- **Frontend:** toda llamada a la API pasa por `frontend/app/composables/useApi.ts`, que elige la URL base de servidor/cliente y lleva organización, cookies y CSRF.
- **Nuevos módulos backend:** crea el módulo bajo `backend/app/modules/` y registra su router en `backend/app/main.py`.
- **Vistas públicas:** no agregues campos sensibles (documentos, fechas de nacimiento) a las proyecciones públicas.
- **Configuración:** mantén los defaults de desarrollo únicamente en `.env.example`.
- **Auditoría:** las acciones de administración de plataforma se registran en `platform_audit_logs`.

## Skills

Las skills del proyecto viven en `.agents/skills/<nombre>/SKILL.md`.

### `sdd` — Spec-Driven Development

- **Ubicación:** `.agents/skills/sdd/SKILL.md`.
- **Cuándo usarla:** siempre que trabajes con `docs/constitution.md` o con cualquier archivo dentro de `specs/`: redactar, revisar o cambiar specs, planes y tareas, o implementar y validar tareas de una spec.
- **Flujo:** Constitución → Spec → Clarificación → Plan → Tareas → Implementación → Validación → Cambio.
- **Reglas clave:**
  - No se pasa a la siguiente fase sin la aprobación explícita del usuario.
  - La spec manda: lo que no está en la spec no se implementa. Si falta una decisión, se para y se pregunta.
  - Todo plan incluye una verificación contra la constitución.
  - Al cerrar cada fase se actualiza `MEMORY.md` (en la raíz).
- **Artefactos:** `specs/NNN-nombre/` con `spec.md`, `plan.md` y `tasks.md`.

## Rarezas y Gotchas

- **Trivy en CI:** mantén `aquasecurity/trivy-action@v0.36.0`. La referencia `v0.28.0` falla por su dependencia faltante `setup-trivy@v0.2.1`. El escaneo falla (`exit-code: 1`) ante vulnerabilidades CRITICAL o HIGH con corrección disponible (`ignore-unfixed`), y omite `frontend/node_modules`, `frontend/.pnpm-store` y `.venv`.
- **Versiones fijadas en CI:** Python 3.14, Node 24 y pnpm 12.12.1 (`pnpm/action-setup@v4`). Si cambias alguna, actualiza `ci.yml`, este archivo y el README.
- **Caché de CI:** pip se cachea con `backend/requirements.txt` y pnpm con `frontend/pnpm-lock.yaml`; mantén `frontend/pnpm-lock.yaml` versionado, porque la instalación usa `--frozen-lockfile`.
- **Compose y secuencias:** `ports: []` y `volumes: []` **no** anulan las secuencias heredadas de desarrollo; el merge las concatena. El overlay de producción usa `!reset []`/`!override` (Compose ≥2.24.4) y la CI valida el JSON renderizado con `infra/scripts/assert_production_compose.py`. No vuelvas a `[]`.
- **Stream del outbox:** no es duradero ni se debe reemitir al arrancar (el relay empieza en el último id). El tope fijo de 10 000 entradas aproximado se dimensiona con P-1 (unos 3 eventos por cierre; varios días con unos pocos MB). Garantías por tramo: outbox→stream *at-least-once*, stream→cliente *best-effort* con huecos y duplicados; la API HTTP es la fuente de verdad. `event_id` es aditivo y `id` se conserva como legado durante la transición; el cliente deduplica 200 entregas. `RESYNC` es una notificación de control (`event_id`/`reason`), no un evento persistido.
- **Cifrado de la fecha (017/018):** la 017 revoca `SELECT`/`INSERT` de `birth_date` y la 018 falla de forma cerrada si el backfill dejó pendientes. En una base con datos no uses el flujo por defecto: sigue el runbook y ejecuta el one-off con `--no-deps`. Tras la 018 no hay reversión de código, solo *forward-fix*.
- **Fotos y transacciones:** no firmes fotos, no subas ni borres objetos y no calcules emparejamientos dentro de una transacción; el contexto RLS es local a cada transacción y se vuelve a fijar en la escritura. En alta/importación, un fallo de firma posterior al commit deja la fila creada y responde 503: el cliente debe releer. Las subidas van antes de la escritura y se compensan si esta falla.
- **Cliente de firma cacheado:** conserva las credenciales resueltas al construirse; rotarlas exige reiniciar el proceso. La caché es por proceso y endpoint de firma efectivo, no por endpoint de subida.
- **Límites Swiss:** 64 equipos, 50 000 evaluaciones y 10 s son límites de seguridad, no reglas deportivas (puntuación, desempates, disciplina y transferencias siguen en el JSON). El hilo de cálculo no se cancela: el timeout descarta el resultado y el hilo termina por su presupuesto.
- **Sorteo simultáneo en frío:** la ronda 1 sin partidos previos no bloquea filas inexistentes, así que dos sorteos concurrentes podrían insertar calendarios duplicados (no hay unicidad de `bracket_code`). Es el riesgo residual aceptado por la spec 005.
- **Migración 002:** un volumen limpio de PostgreSQL había fallado antes con `cannot drop columns from view`. Causa raíz: `infra/postgres/init/02_public_projections.sql` había sido actualizado para reflejar el estado post-012 (`v_public_stages` y `bracket_code` en `v_public_matches`), pero la migración 001 reescribe `v_public_matches` sin `bracket_code`, y `CREATE OR REPLACE VIEW` no puede soltar columnas. La corrección fue revertir `init/02` al estado pre-012 (los scripts de init no son migraciones y no tienen checksum), de modo que 012 introduzca esos cambios en el orden correcto. Solo afecta a volúmenes limpios; los existentes no re-ejecutan init.
- **Windows/WSL:** si pnpm falla con `EPERM` al enlazar `node_modules`, construye y ejecuta mediante el servicio `web` de Docker.
- **Seed demo:** solo admite entornos de desarrollo/local; no lo ejecutes contra producción.
- **Init de PostgreSQL:** los scripts de `init/` no se re-ejecutan en volúmenes existentes; para reiniciar desde cero hay que borrar el volumen.

## Testing

La CI (`ci.yml`) tiene cuatro jobs independientes; reproduce localmente el que corresponda a tu cambio:

- **`backend` (Backend tests):** `cd backend && pytest -q`, más `python -m compileall -q app` para detectar errores de sintaxis. El job también ejecuta `infra/scripts/test_migrate_target.sh` contra PostgreSQL 17 y la suite con base (`RUN_DATABASE_TESTS=1`).
- **`frontend` (Frontend checks):** `pnpm install --frozen-lockfile`, `pnpm test`, `pnpm run typecheck` y `pnpm run build` desde `frontend/`.
- **`infrastructure` (Infrastructure checks):** `python3 infra/scripts/verify_version_sources.py --exclude-constitution`, `sh -n infra/postgres/migrate.sh`, versión de Compose ≥2.24.4, `docker compose config -q` para desarrollo y para el merge dev+prod con variables dummy, y las aserciones de `infra/scripts/assert_production_compose.py` sobre el JSON renderizado.
- **`security` (Dependency and filesystem scan):** `pip-audit -r backend/requirements.txt`, la auditoría del frontend desde la raíz con `infra/scripts/audit_frontend.py` (bloque de Verificación) y el escaneo Trivy descrito en Comandos.
- **Pruebas de integración de invitaciones (opt-in):** requieren PostgreSQL en ejecución con la cuenta y organización demo.

  ```sh
  docker compose exec -e RUN_DATABASE_TESTS=1 api pytest -q tests/test_invitations.py
  ```

- Ejecuta todas las verificaciones relevantes antes de dar una tarea por terminada y reporta cuáles no pudiste correr.

## Memoria
- Al empezar, lee `MEMORY.md` para conocer el estado del proyecto y las decisiones tomadas.
- Al terminar una tarea, actualízalo: estado actual, decisiones importantes (con su porqué) y errores a evitar.
- Mantenlo breve (máximo ~50 líneas): resume o elimina lo que ya no aporte.
- Si algo se convierte en una regla permanente, propón moverlo a `AGENTS.md` en lugar de dejarlo en la memoria.
- No guardes nunca datos sensibles (claves, tokens, datos personales).

## Reglas
- Lee `docs/constitution.md` y la spec activa (`specs/NNN-*/`) antes de tocar código.
