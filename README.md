# Bracket Craft

Plataforma multi-tenant para crear y operar torneos de futbol con reglas configurables, fases componibles y resultados en tiempo real.

## Stack

- Backend: FastAPI, SQLAlchemy Async y PostgreSQL.
- Frontend: Nuxt 4, Vue 3 y Pinia.
- Procesamiento: Redis y worker asíncrono de outbox.
- Tiempo real: Socket.IO.
- Infraestructura: Docker Compose.
- Versiones de referencia: Python 3.14, Node 24 y pnpm 12.12.1.

## Inicio local

1. Copiar `.env.example` a `.env`.
2. Ejecutar `docker compose up --build`.
3. Abrir `http://localhost:3000`.
4. Consultar la documentación en `http://localhost:8000/docs`.

La inicialización PostgreSQL se ejecuta en el primer arranque del volumen. Las migraciones numeradas de `infra/postgres/migrations` se aplican una sola vez y quedan registradas en `schema_migrations` por el servicio `db-migrate`.

## Datos demo

El seed de desarrollo crea una cuenta de prueba, una organización y una llave de eliminación directa de ocho equipos. Se ejecuta explícitamente después de levantar los servicios:

```bash
docker compose up --build -d
docker compose exec api python -m scripts.seed_demo
```

Credenciales de acceso:

- Email: `demo.owner@bracketcraft.dev`
- Contraseña: `Demo1234!`
- Organización: `Demo Federation` (`demo-federation`)

El torneo demo queda en estado `live`, con doce jugadores por equipo, los cuatro cuartos finalizados, ambas semifinales con sus participantes y la final pendiente. Los cuatro cuartos tienen alineaciones tácticas públicas: `4-3-3` vs `4-4-2`, `3-5-2` vs `4-2-3-1`, `4-2-3-1` vs `4-3-3` y `4-4-2` vs `3-5-2`.

El comando es idempotente, solo admite entornos de desarrollo/local y no forma parte de las migraciones. El resultado imprime el `tournament_id` para abrir `/tournaments/{tournament_id}` o consultar el torneo desde `/workspace`.

La portada y las rutas `/tournaments/{id}` son públicas. El Workspace de gestión está disponible en `/workspace` después de iniciar sesión y validar una organización activa.

Las proyecciones públicas de torneos, tablas y partidos se sirven desde `/api/v1/tournaments/public`, `/api/v1/tournaments/public/{id}/standings` y `/api/v1/tournaments/public/{id}/matches`. Los partidos incluyen la planilla pública cuando existe; la formación táctica solo aparece después de publicarse explícitamente desde el Workspace.

La configuración local incluye un almacenamiento S3-compatible (SeaweedFS) con interfaz de archivos en `http://localhost:9001`. La importación de plantillas acepta CSV/TXT con `first_name`, `last_name`, `national_id`, `birth_date` y `dorsal_number`; `photo_filename` vincula imágenes JPG, PNG o WEBP incluidas en un ZIP opcional. La proyección pública solo devuelve `photo_url` cuando el roster tiene consentimiento de imagen.

Para ejecutar únicamente el frontend fuera de Docker:

```bash
cd frontend
pnpm install
pnpm dev
```

## Despliegue de producción

El perfil de producción se aplica como overlay sobre la configuración de desarrollo, en ese orden:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

Requisitos y comportamiento:

- **Docker Compose 2.24.4 o superior.** El overlay usa `!reset`/`!override` para anular los puertos y los montajes de código; versiones anteriores fusionan las secuencias y dejarían la configuración de desarrollo activa.
- **Red externa del proxy.** El operador debe crear la red antes de desplegar, fuera de este compose: `docker network create "${PROXY_NETWORK:-edge}"`. El perfil declara esa red como `external: true` con nombre configurable mediante `PROXY_NETWORK` (por defecto `edge`); el proxy alcanza `web` a través de ella.
- **Sin puertos publicados.** Ningún servicio expone puertos en el host. Todos viven en la red interna `internal` y solo `web` se une además a la red del proxy; `api`, `db`, `redis` y `storage` no son accesibles desde fuera del stack.
- **Solo artefactos construidos.** `api`, `worker` y `web` no montan código del host; ejecutan las imágenes construidas (`api` sin `--reload`, `web` con `node .output/server/index.mjs`). Se conservan `postgres_data`, `redis_data` y `storage_data` y los montajes de solo lectura de `./infra/postgres` en `db` y `db-migrate`.
- **Secretos externos.** Los valores `:?` del overlay (contraseñas, claves, URLs y `SMTP_*`) deben inyectarse desde el entorno o un gestor de secretos.

La CI valida el merge real con variables dummy y las aserciones de `infra/scripts/assert_production_compose.py`; el comando exacto está en `AGENTS.md`.

## Alcance inicial

- Registro y login por email/password.
- Preparación de Google OAuth mediante `auth_identities`.
- Organizaciones con membresías y RBAC.
- Torneos y versiones inmutables.
- Configuración privada de versiones, fases, equipos y partidos.
- Configuración JSON de puntuación, desempates, disciplina y transferencias.
- Cierre de actas con goles, tarjetas, suspensiones y outbox.
- Clasificación Round Robin.
- Estructura de fases lista para grupos y playoffs.

## Seguridad

El backend establece `app.current_organization_id` y `app.current_user_id` dentro de cada transacción. Las tablas tenant-owned tienen RLS y las vistas públicas no exponen documentos ni fechas de nacimiento.

La administración global está separada del workspace en `/admin`. Requiere un registro en `platform_admins`; para el primer arranque local se puede indicar `PLATFORM_ADMIN_EMAIL` en `.env` después de registrar la cuenta. Las acciones de usuarios, organizaciones y membresías se auditan en `platform_audit_logs` y no permiten editar directamente resultados ni versiones publicadas.

Las credenciales de desarrollo (`bracket_app`, `POSTGRES_PASSWORD`, `JWT_SECRET` y `PLAYER_DATA_KEY`) incluidas en `.env.example` son únicamente para desarrollo local. En producción deben inyectarse mediante secretos externos y `APP_ENV=production`; el backend rechazará los defaults conocidos. El perfil `docker-compose.production.yml` no publica ningún puerto, deja los servicios internos en una red privada, une solo `web` a la red externa del proxy, elimina los volúmenes de código, desactiva `--reload`, construye el frontend estático y exige los secretos y URLs de producción (ver «Despliegue de producción»).
