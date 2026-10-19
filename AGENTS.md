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

- **Backend:** FastAPI, SQLAlchemy asíncrono y PostgreSQL (Python 3.12 en CI).
- **Frontend:** Nuxt 4, Vue 3 y Pinia (Node 24 y pnpm 12.11.2 en CI). Layout Nuxt 4: el código de app vive en `frontend/app/`.
- **Procesamiento:** Redis y worker asíncrono de outbox.
- **Tiempo real:** Socket.IO.
- **Almacenamiento de archivos:** SeaweedFS con API S3 (fotos de jugadores). Antes: MinIO (repositorio archivado el 2026-04-25).
- **Infraestructura:** Docker Compose.

## Límites del Proyecto

- No existe gestor de paquetes en la raíz. Ejecuta comandos Python desde `backend/` y comandos pnpm desde `frontend/`.
- Las rutas `/` y `/tournaments/{id}` son **públicas**. El Workspace (`/workspace`) requiere sesión y una organización activa validada.
- La administración global vive en `/admin`, separada del Workspace. Requiere un registro en `platform_admins` y no puede editar resultados ni versiones publicadas.
- `scripts.seed_demo` es solo para desarrollo/local: no es una migración ni un comando de producción.
- Las proyecciones públicas **nunca** exponen documentos de identidad ni fechas de nacimiento. `photo_url` solo se devuelve si el roster tiene consentimiento de imagen.
- La formación táctica solo es pública después de publicarse explícitamente desde el Workspace.
- Las versiones de torneo son inmutables una vez publicadas.
- No edites migraciones ya aplicadas; agrega una nueva.

## Arquitectura Clave

- **Multi-tenancy con RLS:** las tablas tenant-owned usan Row Level Security. El backend fija `app.current_organization_id` y `app.current_user_id` dentro de cada transacción.
- **Torneos:** torneos con versiones inmutables, fases componibles (Round Robin, grupos, playoffs), equipos y partidos. Puntuación, desempates, disciplina y transferencias se configuran con JSON.
- **Actas de partido:** el cierre registra goles, tarjetas y suspensiones, y emite eventos al outbox.
- **Outbox + worker + Redis:** los eventos se procesan de forma asíncrona y alimentan el tiempo real con Socket.IO.
- **Autenticación:** email/password; Google OAuth preparado mediante `auth_identities`. Membresías y RBAC por organización.
- **API pública:** `/api/v1/tournaments/public`, `/api/v1/tournaments/public/{id}/standings` y `/api/v1/tournaments/public/{id}/matches`.
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
docker compose config -q
pip-audit -r backend/requirements.txt
cd frontend && pnpm audit --prod --audit-level high
```

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
- **Migraciones:** `infra/postgres/migrate.sh` aplica las migraciones numeradas de `infra/postgres/migrations/` una sola vez y las registra en `schema_migrations` con checksum SHA-256.
- **Producción:** `APP_ENV=production` con `docker-compose.production.yml`, que no publica ningún puerto, elimina los montajes de código de `api`, `worker` y `web` con `!reset`, desactiva `--reload`, construye el frontend estático y exige secretos y URLs de producción. El backend rechaza los defaults conocidos.
- **Redes de producción:** todos los servicios viven en la red interna `internal`; solo `web` se une además a la red externa del proxy (`edge` por defecto, configurable con `PROXY_NETWORK`). El operador debe crear esa red antes de desplegar (`docker network create "$PROXY_NETWORK"`); el compose no la crea. Requiere Docker Compose **2.24.4 o superior** (`!reset`/`!override`).
- **Secretos a cambiar fuera de desarrollo:** `JWT_SECRET`, `PLAYER_DATA_KEY`, `INVITATION_TOKEN_KEY`, credenciales de base de datos y almacenamiento; además activar `AUTH_COOKIE_SECURE`. Inyéctalos con secretos externos.
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
  scripts/                   Utilidades (p. ej. seed_demo, solo desarrollo)
  tests/                     Pruebas pytest
frontend/                    Nuxt 4 / Vue 3 / Pinia (código de app en frontend/app/)
  app/composables/useApi.ts   Cliente HTTP centralizado
infra/postgres/
  init/                      Configuración inicial de la base de datos
  migrations/                Migraciones SQL numeradas
  migrate.sh                 Ejecutor de migraciones con checksums
infra/scripts/
  assert_production_compose.py  Aserciones del merge dev+prod (CI)
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
- **Versiones fijadas en CI:** Python 3.12, Node 24 y pnpm 12.11.2 (`pnpm/action-setup@v4`). Si cambias alguna, actualiza `ci.yml`, este archivo y el README.
- **Caché de CI:** pip se cachea con `backend/requirements.txt` y pnpm con `frontend/pnpm-lock.yaml`; mantén `pnpm-lock.yaml` versionado, porque la instalación usa `--frozen-lockfile`.
- **Compose y secuencias:** `ports: []` y `volumes: []` **no** anulan las secuencias heredadas de desarrollo; el merge las concatena. El overlay de producción usa `!reset []`/`!override` (Compose ≥2.24.4) y la CI valida el JSON renderizado con `infra/scripts/assert_production_compose.py`. No vuelvas a `[]`.
- **Migración 002:** un volumen limpio de PostgreSQL había fallado antes con `cannot drop columns from view`. Causa raíz: `infra/postgres/init/02_public_projections.sql` había sido actualizado para reflejar el estado post-012 (`v_public_stages` y `bracket_code` en `v_public_matches`), pero la migración 001 reescribe `v_public_matches` sin `bracket_code`, y `CREATE OR REPLACE VIEW` no puede soltar columnas. La corrección fue revertir `init/02` al estado pre-012 (los scripts de init no son migraciones y no tienen checksum), de modo que 012 introduzca esos cambios en el orden correcto. Solo afecta a volúmenes limpios; los existentes no re-ejecutan init.
- **Windows/WSL:** si pnpm falla con `EPERM` al enlazar `node_modules`, construye y ejecuta mediante el servicio `web` de Docker.
- **Seed demo:** solo admite entornos de desarrollo/local; no lo ejecutes contra producción.
- **Init de PostgreSQL:** los scripts de `init/` no se re-ejecutan en volúmenes existentes; para reiniciar desde cero hay que borrar el volumen.

## Testing

La CI (`ci.yml`) tiene cuatro jobs independientes; reproduce localmente el que corresponda a tu cambio:

- **`backend` (Backend tests):** `cd backend && pytest -q`, más `python -m compileall -q app` para detectar errores de sintaxis.
- **`frontend` (Frontend checks):** `pnpm install --frozen-lockfile`, `pnpm test`, `pnpm run typecheck` y `pnpm run build` desde `frontend/`.
- **`infrastructure` (Infrastructure checks):** `sh -n infra/postgres/migrate.sh` y `docker compose config -q`.
- **`security` (Dependency and filesystem scan):** `pip-audit -r backend/requirements.txt`, `pnpm audit --prod --audit-level high` y el escaneo Trivy descrito en Comandos.
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
