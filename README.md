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

## Cifrado de la fecha de nacimiento y runbook de despliegue

La fecha de nacimiento de los jugadores se almacena cifrada con `PLAYER_DATA_KEY` en `players.birth_date_encrypted`. El rol de aplicación puede insertarla, pero no leer el texto cifrado ni, desde la migración 017, la fecha en claro. La edad (`age_at_reference` y `age_reference_year`) se materializa por jugador y se ajusta con el año de inicio del torneo; la fecha completa no se expone en la API, el Workspace, las proyecciones públicas, los errores ni los logs.

Sobre una base con datos históricos, el cambio se aplica en dos fases con una ventana de mantenimiento. La secuencia es **017 → imagen nueva → backfill → 018**; no apliques la 018 hasta que el backfill termine con salida 0. `MIGRATION_TARGET` es una variable no secreta del servicio `db-migrate`: vacía aplica todas las migraciones pendientes y `017`/`018` limitan la aplicación a esa versión. El runner sigue validando los checksums de todos los archivos, también los posteriores al target.

Los comandos siguientes usan el perfil de producción; en desarrollo, define `COMPOSE="docker compose"`. En local, carga el `.env` en la shell (`set -a; . ./.env; set +a`) para que `POSTGRES_PASSWORD`, `POSTGRES_DB` y `PLAYER_DATA_KEY` estén exportados. En producción, los secretos se inyectan con el gestor externo y nunca se guardan en el repositorio.

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
```

1. **Copia de seguridad verificada (estado 016).** No continúes sin un archivo restaurable. Guárdalo fuera del repositorio (contiene datos personales) y protégelo; no lo commitees.

   ```sh
   $COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre017.dump"
   $COMPOSE exec -T db pg_restore -l < "$HOME/backup-pre017.dump" >/dev/null && echo "backup OK"
   ```

2. **Ventana de mantenimiento.** Detén `api` y `worker` para que ninguna instancia antigua escriba la fecha en claro. La 017 revoca el `SELECT`/`INSERT` de `birth_date` a `bracket_app`; no arranques la aplicación hasta completar la 018.

   ```sh
   $COMPOSE stop api worker
   $COMPOSE ps
   ```

3. **Migración 017 (esquema intermedio).** Aplica el campo cifrado, la edad y los permisos, y deja la fecha en claro solo para el backfill administrativo.

   ```sh
   MIGRATION_TARGET=017 $COMPOSE run --rm db-migrate
   ```

4. **Imagen nueva del backend.** Debe contener `scripts.encrypt_birth_dates`; en producción despliega la imagen publicada por el pipeline en lugar de construirla en el host.

   ```sh
   $COMPOSE build api
   ```

5. **Backfill one-off.** Se ejecuta sobre la imagen del backend (`api`) con la conexión administrativa `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY`, y con `--no-deps` para no disparar `db-migrate` (el target por defecto aplicaría la 018 antes de tiempo). La salida debe ser 0. Si se interrumpe, se reanuda con el mismo comando: solo procesa filas pendientes. Una clave incorrecta o un HMAC que no coincide aborta sin escribir. Los logs solo muestran conteos, lotes y duración.

   ```sh
   export DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-bracket_craft}"
   $COMPOSE run --rm --no-deps \
     -e DATABASE_ADMIN_URL -e PLAYER_DATA_KEY \
     api python -m scripts.encrypt_birth_dates
   ```

6. **Migración 018 (cierre).** Verifica que no queden pendientes, hace obligatorio el cifrado y elimina `birth_date`. Falla de forma cerrada si el backfill no terminó, sin dejar cambios parciales.

   ```sh
   MIGRATION_TARGET=018 $COMPOSE run --rm db-migrate
   ```

7. **Arranque y smoke.** Confirma la salud del stack, la proyección pública y el flujo del Workspace.

   ```sh
   $COMPOSE up -d api worker
   $COMPOSE exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
   $COMPOSE exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/tournaments/public').status)"
   $COMPOSE ps
   ```

   Smoke funcional: inicia sesión en el Workspace, abre un torneo, registra un jugador y comprueba que el listado muestra `Edad: {age}`; abre la página pública del torneo y confirma que muestra la edad y nunca la fecha. En desarrollo, ejecuta el seed con `docker compose exec api python -m scripts.seed_demo`.

**Instalación nueva.** `docker compose up --build` aplica todas las migraciones; la 018 no encuentra pendientes porque la tabla está vacía y no se ejecuta el backfill. El seed de desarrollo usa el esquema final.

### Reversión

- **Antes de 017:** restaura la copia de seguridad y despliega la imagen anterior.

  ```sh
  $COMPOSE stop api worker
  $COMPOSE exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$HOME/backup-pre017.dump"
  $COMPOSE up -d api worker
  ```

- **Entre 017 y 018:** la aplicación antigua no puede insertar la fecha porque la 017 revocó el permiso. No vuelvas a la imagen antigua sobre el esquema intermedio: corrige la clave o los datos y reintenta el backfill. Para una reversión total, restaura la copia previa a la 017 y despliega la imagen anterior.
- **Después de 018:** no hay vuelta atrás de código; solo *forward-fix* con una migración nueva. No edites la 018 ni restaures la fecha en claro a mano. Los snapshots anteriores a la 017 pueden contenerla: su tratamiento y la rotación de `PLAYER_DATA_KEY` son deuda separada.
- **Fallo de la 018:** es transaccional; corrige los pendientes, reintenta el backfill y vuelve a ejecutar la 018. Si el backfill reporta una fecha imposible, corrige los datos reportados (solo ids internos) y reanuda.

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

## Tiempo real y outbox

El cierre de actas y los efectos de dominio se registran en `outbox_events`. Un worker publica cada evento en el stream de Redis `bracket_craft.events` y el relay de la API lo reenvía por Socket.IO a la sala de la organización y, para los eventos públicos, a la del torneo. El stream es un **transporte vivo de mejor esfuerzo**, no un registro duradero ni la fuente de verdad.

- **Tope fijo:** cada escritura usa `MAXLEN` aproximado de 10 000 entradas (`OUTBOX_STREAM_MAXLEN`). Es una constante del backend, sin variable de entorno; el recorte mantiene el orden de magnitud, no un número exacto. El criterio de dimensionamiento es P-1: un cierre de partido produce unos 3 eventos, así que 10 000 entradas cubren varios días de operación normal con unos pocos MB.
- **Sobre del evento:** `event_id` (el `id` de la fila de outbox), `id` legado con el mismo valor durante la transición, `organization_id`, `event_type` y `payload`. El payload de dominio no cambia; `event_id` es aditivo.
- **Arranque y reconexión:** un proceso nuevo del relay resuelve la posición en el último id y **no reemite el histórico**. Si se pierde la conexión con Redis con el proceso vivo, conserva la posición y **reanuda** desde ahí, por lo que puede repetir entradas retenidas.
- **`RESYNC`:** evento de control `{event_id, reason}` con `reason` entre `JOIN`, `RELAY_START`, `STREAM_TRIMMED` y `REDIS_RESET`. No lleva datos de negocio, no se persiste y no se escribe en el stream. `JOIN` va solo al socket que entra en su sala; los huecos se emiten a las salas con clientes conectados; sin clientes no se emite nada.
- **Cliente:** deduplica por `event_id` en una ventana FIFO de 200 entregas y separa `RESYNC` de los eventos de dominio. El Workspace y la operación de partido recargan al reconectar; la página pública mantiene su polling de 30 s mientras el socket no está conectado y, ante un `RESYNC` de hueco, recarga y reinicia la paginación.

| Tramo | Garantía | Consecuencia |
|---|---|---|
| `outbox_events` → stream | at-least-once | El mismo evento puede escribirse más de una vez con el mismo `event_id`. |
| stream → cliente | best-effort | Hay huecos (reinicio, recorte, caída de Redis, cliente desconectado) y duplicados posibles; se mitigan con `RESYNC`, deduplicación, polling y reconciliación. |
| cliente → API HTTP | fuente de verdad | Cualquier estado visible se reconstruye con una recarga HTTP; el tiempo real es una optimización. |

## Verificación

Con Node 24 y pnpm 12.12.1, la auditoría de dependencias del frontend se ejecuta desde la raíz del repositorio:

```sh
AUDIT_JSON="/tmp/pnpm-audit.json"
trap 'rm -f "$AUDIT_JSON"' EXIT
if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
```

El filtro `infra/scripts/audit_frontend.py` falla ante cualquier hallazgo `high` o `critical` con corrección publicada, muestra los no accionables (incluidos los que no tienen parche) para su revisión y no persiste exclusiones. No se admiten listas de GHSA ni flags que persistan exclusiones, como `--ignore-unfixable`, `audit.ignore` o `auditConfig.ignoreGhsas`. El resto de comprobaciones de CI está en `AGENTS.md` y la política completa en la §3.4 de `docs/constitution.md`.

## Seguridad

El backend establece `app.current_organization_id` y `app.current_user_id` dentro de cada transacción. Las tablas tenant-owned tienen RLS y las vistas públicas no exponen documentos ni fechas de nacimiento.

La fecha de nacimiento se almacena cifrada con `PLAYER_DATA_KEY` y el rol de aplicación no puede leer el texto cifrado (patrón *write-only*, igual que el documento). Desde la migración 017 tampoco puede leer ni insertar la fecha en claro; solo escribe el campo cifrado y la edad derivada. La API y el Workspace exponen la edad (`age` solo en `GET /tournaments/{id}/rosters`), nunca la fecha completa. La exposición declarada —la edad y el año de referencia permiten inferir el año de nacimiento— es el mismo dato derivado que la proyección pública ya mostraba. La rotación de `PLAYER_DATA_KEY` y el tratamiento de copias anteriores a la 017 son deuda separada.

La administración global está separada del workspace en `/admin`. Requiere un registro en `platform_admins`; para el primer arranque local se puede indicar `PLATFORM_ADMIN_EMAIL` en `.env` después de registrar la cuenta. Las acciones de usuarios, organizaciones y membresías se auditan en `platform_audit_logs` y no permiten editar directamente resultados ni versiones publicadas.

Las credenciales de desarrollo (`bracket_app`, `POSTGRES_PASSWORD`, `JWT_SECRET` y `PLAYER_DATA_KEY`) incluidas en `.env.example` son únicamente para desarrollo local. En producción deben inyectarse mediante secretos externos y `APP_ENV=production`; el backend rechazará los defaults conocidos. El perfil `docker-compose.production.yml` no publica ningún puerto, deja los servicios internos en una red privada, une solo `web` a la red externa del proxy, elimina los volúmenes de código, desactiva `--reload`, construye el frontend estático y exige los secretos y URLs de producción (ver «Despliegue de producción»).
