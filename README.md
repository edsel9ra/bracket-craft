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

El servicio `web` de desarrollo se ejecuta como `root` (`user: "0:0"` en `docker-compose.yml`): el servidor de desarrollo escribe caché en el árbol montado `./frontend` y el identificador del contenedor puede no coincidir con el dueño del host (Linux frente a Windows/WSL). Es una excepción **solo de desarrollo**: la etapa de ejecución de `frontend/Dockerfile` declara `USER node` y el perfil de producción fija `user: "node"`, sin heredar la excepción. Se retirará cuando el flujo de desarrollo deje de necesitar escritura en el montaje.

La API de desarrollo se publica solo en `127.0.0.1:8000`: el navegador la alcanza por esa interfaz local y el renderizado en servidor por la red interna. El servicio `web` conserva `3000:3000` porque es el punto de entrada del desarrollador y el flujo en Windows/WSL depende de esa publicación.

Cada servicio declara su propia verificación de salud. La API comprueba `/health/ready` (base de datos y Redis); el web responde por HTTP con el recurso estático `/health.txt`, sin depender de la API ni de la base de datos una vez arrancado; el worker publica un latido de fichero cada **10 s** (`HEARTBEAT_INTERVAL_SECONDS`) y se declara **no sano** cuando su bucle no completa una vuelta en **90 s** (`HEARTBEAT_MAX_AGE_SECONDS`, la única fuente del umbral), haya o no eventos que procesar. Una **vuelta completada** es una iteración que termina, con o sin trabajo y con o sin error de la dependencia; un fallo de base de datos o Redis con el bucle girando y reintentando **no** cuenta como bucle detenido. El web espera una sola vez a que la API esté sana al arrancar. Con la base de datos detenida la API queda `unhealthy` (insana), el web sigue `healthy` y el worker sigue `healthy` mientras su bucle avance y reintente. El latido se escribe en `/tmp/bracket-craft-worker-heartbeat` y la ruta se configura con `WORKER_HEARTBEAT_PATH` en el proceso y en el healthcheck.

La transición real se comprueba con un comando de operación reproducible:

```sh
sh infra/scripts/verify_worker_loop_health.sh [servicio|contenedor]
```

Congela solo el bucle de un worker vivo (`SIGSTOP` al PID 1 dentro del contenedor), observa el paso a `unhealthy` y lo reanuda (`SIGCONT`) hasta `healthy`, sin reiniciar el contenedor. Desde la spec 011 la corrida también comprueba que el worker **procesa trabajo**: tras la recuperación inserta una sonda de outbox inocua (`python -m scripts.outbox_probe insert`, evento `VERIFICATION_OUTBOX_PROBE`), espera su estado `processed` en la cola y la borra siempre al salir, también si algún paso falla.

La verificación empieza por un **paso 0** que pregunta al propio worker su `APP_ENV`: la sonda escribe en la cola, así que **solo se ejecuta en desarrollo/local** (`APP_ENV` `development`, `dev` o `local`). Fuera de ese entorno sale **2** sin escribir nada y no existe opción para forzarla. La espera de la sonda tiene presupuesto propio, independiente de los tiempos de salud, con dos variables: `WORKER_PROBE_TIMEOUT` (segundos, defecto **120**) y `WORKER_PROBE_POLL_INTERVAL` (segundos entre sondeos, defecto **2**); ambas deben ser enteros positivos. Los reintentos del outbox no son un fallo: `pending`/`processing` se tratan como «sigue esperando» hasta agotar el presupuesto.

Códigos de salida: **0** si observa la transición `healthy → unhealthy → healthy` **y** el worker procesa la sonda; **1** si algún paso falla —incluida una sonda `failed`, desaparecida, sin llegar a `processed` en el presupuesto o que no se pudo borrar (informa su `id` y marcador)—; **2** si no hay Docker, falta el contenedor, los argumentos o las variables son inválidos, o el worker no está en desarrollo/local. En los casos **2** la verificación queda **no ejecutada** y no se sustituye por una prueba simulada. No forma parte de la suite que corre sin contenedores. La sonda no tiene handler de dominio ni datos personales; el worker la publica en el stream y en desarrollo aparece como un evento de socket más en la sala de la organización demo, inocuo y acotado por el tope del stream.

## Configuración y contrato de entorno

`.env.example` documenta los defaults de desarrollo. Cada variable declara su consumidor: la API recibe la configuración de la aplicación (JWT, CSRF, autenticación, SMTP, almacenamiento, CORS, límites y URLs); el worker recibe `DATABASE_URL`, `REDIS_URL` y `APP_ENV`, más `JWT_SECRET` y `PLAYER_DATA_KEY` fuera de desarrollo; el web recibe `NUXT_*` y las marcas `CI`/`NODE_ENV`; `db` recibe las credenciales de PostgreSQL; `db-migrate` recibe `POSTGRES_*`, `PGPASSWORD`, `MIGRATION_TARGET` y `PLATFORM_ADMIN_EMAIL`; el one-off de cifrado recibe `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY` con `-e`, nunca la API. Redis y el almacenamiento no reciben variables.

Son excepciones declaradas `PGPASSWORD` (alias de `POSTGRES_PASSWORD`), `DATABASE_URL` (derivada por Compose y obligatoria en producción), `DATABASE_ADMIN_URL` (solo el one-off), `CI` y `NODE_ENV` (marcas del servidor Nuxt), además de los valores de pruebas o de entornos locales. El mapa y la lista cerrada de excepciones viven en `infra/scripts/check_env_contract.py`.

La comprobación se ejecuta sobre la configuración renderizada (comandos en «Verificación»). Falla, con el nombre de la variable y del servicio, si una variable documentada no llega a ningún consumidor (documentada sin efecto), si un servicio declara una variable que no está documentada (declarada sin documentar) o si una variable aparece en un servicio que no la consume (mal atribuida). El merge de producción se valida con `--profile production` y las variables dummy que detalla `AGENTS.md`.

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

## Contratos de invitación, presentación y versión

Contratos de la spec 008 y cambios declarados de la spec 009 (C-1 y C-2). Cliente y servidor se despliegan juntos; no hay periodo de transición ni parámetro que reactive el comportamiento anterior.

- **Invitación vencida.** Una invitación `pending` cuya fecha de vencimiento ya pasó se presenta como `expired` **sin reescribir la fila**; la lectura y la vista previa no escriben. El registro se materializa como vencido al **crear**, al **reenviar** y, desde la spec 009, al **reabrir** una revocada cuando el mismo correo tiene otra pendiente ya vencida (**tercera ruta**, cambio **C-2**). La materialización y la reapertura ocurren en la misma transacción y en ese orden; una pendiente **vigente** del mismo correo bloquea la reapertura con **409** y no se materializa.

  | Acción | Respuesta |
  |---|---|
  | `GET /organizations/invitations` | `expired` calculado por fila; no cambia el estado almacenado ni `updated_at` |
  | `POST /organizations/invitations` con una pendiente vencida del mismo correo | `201`: la anterior queda vencida y se crea la nueva |
  | `POST /organizations/invitations` con una pendiente vigente | `409` `code: INVITATION_OTHER_PENDING` (ya existe una invitación pendiente), sin escribir |
  | `POST /organizations/invitations` con solo una revocada del mismo correo | `201`: crea otra fila; la unicidad solo cubre las pendientes |
  | `DELETE /organizations/invitations/{id}` sobre una vencida | `409` («ya no está pendiente»), sin marcarla revocada ni reescribirla |
  | `POST /organizations/invitations/{id}/resend` sobre una vencida | `200`: reutiliza la fila y la deja `pending` con token y fecha nuevos |
  | `POST /organizations/invitations/{id}/resend` sobre una **revocada** | `409` `code: INVITATION_REVOKED_RESEND` (cambio **C-1**): debe reabrirse; la fila queda intacta y no se envía correo |
  | `POST /organizations/invitations/{id}/resend` sobre una aceptada | `409` `code: INVITATION_ALREADY_ACCEPTED`, sin escribir |
  | `POST /organizations/invitations/{id}/resend` con **otra** pendiente vigente del mismo correo | `409` `code: INVITATION_OTHER_PENDING`, sin escribir ni enviar correo |
  | `POST /organizations/invitations/{id}/reopen` sobre una revocada | `200`: misma fila `pending`, token y fecha nuevos, `revoked_at: null` e `invite_url` nuevo; el enlace anterior deja de resolver |
  | `POST /organizations/invitations/{id}/reopen` sobre una revocada con **otra** pendiente **vencida** del mismo correo | `200`: materializa la otra como `expired` y después reabre (**C-2**); al final queda exactamente una pendiente |
  | `POST /organizations/invitations/{id}/reopen` sobre una pendiente, una vencida o una aceptada | `409` `code: INVITATION_NOT_REVOKED`, sin renovar token ni fecha |
  | `POST /organizations/invitations/{id}/reopen` con **otra** pendiente **vigente** del mismo correo | `409` `code: INVITATION_OTHER_PENDING`, sin escribir ni materializar |
  | `POST /organizations/invitations/{id}/reopen` sin `MANAGE_MEMBERS` o con membresía de organización inválida | `403`, sin leer ni escribir la invitación |
  | `POST /organizations/invitations/{id}/reopen` inexistente o de otra organización | `404`, sin revelar que existe |
  | `POST /invitations/{token}/accept` de una vencida | `410`, sin consumirla |

  Se mantiene la unicidad de invitaciones pendientes por organización y correo. La reapertura y el reenvío exigen `MANAGE_MEMBERS` y solo actúan sobre la organización activa; responden **502** si el correo falla después de escribir (la fila ya quedó pendiente) y no devuelven token como campo aparte ni datos de otra invitación.

- **Acceso del miembro sin rol.** La autorización se resuelve **antes** del handler: un miembro **activo** de la organización **sin ninguna fila de rol** no obtiene contexto y recibe **403** con el mismo cuerpo, `{"detail": "Membresía o rol activo no válido"}`, en `GET /organizations/current/access`, `GET /organizations/members`, `PATCH /organizations/members/{id}/role`, `PATCH /organizations/members/{id}/status`, `POST /organizations/invitations`, `POST /organizations/invitations/{id}/resend`, `POST /organizations/invitations/{id}/reopen` y `DELETE /organizations/invitations/{id}`, incluida una invitación inexistente o de otra organización. La respuesta `200` con rol `viewer` y lista vacía (`[]`) solo se obtiene con el rol `viewer` asignado; cualquier otro rol devuelve su propio `role_code` y sus permisos. Un rechazo así no lee ni escribe la invitación, no emite enlace, no envía correo y no audita. El rol mostrado sigue siendo una regla de presentación: no concede permiso.

- **Reapertura y reenvío.** Revocar es definitivo hasta que se reabra: `POST /organizations/invitations/{id}/reopen` reutiliza la fila revocada, le asigna token y fecha de vencimiento nuevos y la deja pendiente, sin crear otra invitación; el enlace revocado nunca revive y solo el nuevo permite previsualizar y aceptar. Reenviar una revocada ya no la resucita: responde **409** y remite a reabrir (cambio **C-1**). La reapertura escribe **una** entrada `REOPEN_INVITATION` en `administrative_audit_logs` con la acción, la invitación y el miembro que la ejecuta, en la misma transacción y solo si hubo cambio efectivo; la entrada no contiene correo ni token. Crear, reenviar y revocar no auditan; la aceptación conserva `ACCEPT_INVITATION`.

- **Identificador estable del 409.** Los 409 de **crear, reenviar y reabrir** añaden un campo aditivo `code` junto a `detail`, que sigue siendo una cadena y no cambia: `INVITATION_NOT_REVOKED`, `INVITATION_OTHER_PENDING`, `INVITATION_ALREADY_ACCEPTED` e `INVITATION_REVOKED_RESEND`. El 409 de **revocar una invitación vencida** conserva solo `detail`, sin `code`. El cliente traduce `code` al idioma activo y usa `detail` como respaldo; el servidor no negocia idioma. Los 409 no incluyen token, enlace ni correo, y los demás errores (403, 404, 410, 502) no cambian.

- **Pantalla de miembros.** En `/workspace/members`, cada invitación ofrece solo la acción de su estado: «Reenviar» en pendientes y vencidas, «Reabrir» en revocadas, «Revocar» solo en pendientes vigentes y ninguna en aceptadas. Reabrir pide confirmación (el enlace anterior dejará de funcionar y se enviará un correo nuevo), los controles se deshabilitan mientras hay una operación de invitaciones en curso y, tras el éxito, la fila muestra el estado real, la fecha nueva y el **último** enlace emitido por el servidor, listo para copiar. Un 409 se explica en el idioma activo con la acción que corresponde usar, sin presentar la invitación como modificada.

- **Aceptación sin token.** `POST /invitations/{token}/accept` ya no devuelve `access_token` ni `token_type` en el cuerpo: la sesión se entrega solo con la cookie de sesión. No hay versión, cabecera ni parámetro que reactive el token en el cuerpo; un consumidor externo que lo leyera debe usar la cookie.
- **Rol por precedencia.** El rol mostrado de un miembro con varios roles sigue el orden **dueño → administrador → operador → árbitro → observador**, de forma consistente en el listado de miembros, la respuesta de cambio de rol y los datos de acceso de la sesión. Es una regla de **presentación**: la autorización sigue siendo aditiva por permisos y por `match_officials`, y el rol mostrado no concede permiso.
- **Organización activa.** El servidor devuelve solo las organizaciones de la persona, activas y con membresía activa, en **orden estable** por nombre y, en empate, por identificador. El cliente (entrega 008C de la spec 008) restaura la última organización usada solo si su identificador aparece en esa lista; si no hay historial válido, activa la primera del orden estable. El servidor no guarda historial por navegador y revalida la membresía en cada petición.
- **Versión del producto.** `backend/pyproject.toml` (`[project].version`) es la **única** fuente; `/docs` y `/openapi.json` la leen de ahí. La versión del contrato de reglas (`engine_version`, `2026.1`) es otra y no se usa como versión del producto ni al revés.

Los cambios de esquema que acompañan a esta entrega están en «Migración 022: topes de minuto en eventos de partido (runbook)» y «Migración 023: vueltas de fase persistidas (runbook)», en este mismo documento.

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

Para un servidor que sigue en el esquema **018** con el código antiguo, el paquete acumulado hasta **023** (estrategias con y sin ventana, backups, pre-chequeos, orden de aplicación, smoke y post-chequeos) está en [`docs/runbook-despliegue-019-023.md`](docs/runbook-despliegue-019-023.md).

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

## Migración 013: reescritura por texto ya aplicada (riesgo documentado)

La migración **013** ya está aplicada y **no se edita** (historial append-only). Endureció cinco funciones de plataforma (`platform_set_user_active`, `platform_set_organization_active`, `platform_set_membership_active`, `platform_create_membership` y `requeue_outbox_events`) y reescribió la vista cruda de formación (`v_public_match_lineups_unpublished`) **sustituyendo texto sobre su definición vigente**. La sustitución solo actúa cuando el texto coincide; si no coincide, **no hace nada y no avisa**. Una base migrada antes de la comprobación podría conservar una función con `<> 'platform_admin'` o la vista con el orden anterior, y nadie lo habría notado.

El estado final esperado se comprueba con `backend/tests/test_migration_013_hardening.py`: exige `fn_platform_actor_role() IS DISTINCT FROM 'platform_admin'` en las cinco funciones y el orden `tl.match_id, tl.team_id, tl.published_at DESC, ms.segment_number DESC, tl.id DESC` en la vista, y falla nombrando la función o la vista incumplidora. Es una prueba opt-in con PostgreSQL:

```sh
cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
  pytest -q tests/test_migration_013_hardening.py
```

Si la comprobación falla, la corrección es una **migración nueva** (*forward-fix*) que reescriba la función o la vista; no se reescribe, reaplica ni edita la 013.

## Migración 019: retiro de roles por torneo y selectores entre fases (runbook)

La migración **019** es **destructiva y no tiene rollback**. Elimina `tournament_user_roles` y `stage_edges`, estrecha el `CHECK` de `phase_slots.source_type` a `direct_team`/`match_result` y recrea `prevent_published_structure_mutation()` con el SQLSTATE **`ZZ409`**. Conserva `phase_slots` (con `source_reference`) y las columnas de slots de `matches` como procedencia. `schema_migrations` y el checksum impiden aplicarla dos veces; `IF EXISTS` es solo una salvaguarda. Después de aplicada, cualquier corrección es una **migración nueva** (*forward-fix*).

**Orden de despliegue:** primero el código nuevo, que funciona con el esquema 018; después la 019. No apliques la 019 con la imagen anterior: el clonado antiguo todavía lee `stage_edges`.

**Antes de aplicar**, con `api` y `worker` detenidos y una copia verificada:

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre019.dump"
pg_restore -l "$HOME/backup-pre019.dump" > /dev/null && echo "backup verificable"
```

Pre-chequeo de solo conteos (sin identificadores ni datos personales). Las guardas `to_regclass` permiten que una relación ausente cuente como 0. Las consultas siguientes referencian estructuras **retiradas** únicamente para comprobar que están vacías o ausentes antes de la 019:

```sql
DO $$
DECLARE
    v_rows BIGINT;
BEGIN
    IF to_regclass('public.tournament_user_roles') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM public.tournament_user_roles' INTO v_rows;
        RAISE NOTICE 'tournament_user_roles=%', v_rows;
    ELSE
        RAISE NOTICE 'tournament_user_roles=0 (ausente)';
    END IF;

    IF to_regclass('public.stage_edges') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM public.stage_edges' INTO v_rows;
        RAISE NOTICE 'stage_edges=%', v_rows;
    ELSE
        RAISE NOTICE 'stage_edges=0 (ausente)';
    END IF;

    IF to_regclass('public.phase_slots') IS NOT NULL THEN
        SELECT count(*) INTO v_rows FROM public.phase_slots
        WHERE source_type = 'stage_rank';
        RAISE NOTICE 'phase_slots.source_type=stage_rank:%', v_rows;
        SELECT count(*) INTO v_rows FROM public.phase_slots
        WHERE source_type = 'manual';
        RAISE NOTICE 'phase_slots.source_type=manual:%', v_rows;
        SELECT count(*) INTO v_rows FROM public.phase_slots
        WHERE source_type NOT IN ('direct_team', 'match_result');
        RAISE NOTICE 'phase_slots.source_type_retirados_o_desconocidos=%', v_rows;
    ELSE
        RAISE NOTICE 'phase_slots=0 (ausente)';
    END IF;
END
$$;
```

Todos los conteos deben ser **0**. Si alguno es mayor, la 019 falla cerrada: el operador decide antes de aplicarla; no se borran filas en silencio ni se reescribe `source_type`. Comprueba también el catálogo (relaciones, funciones, vistas, políticas, triggers y **FKs entrantes**); antes solo debe aparecer la propia tabla y, si existiera, su política o trigger; después, nada:

```sql
SELECT 'relation' AS kind, n.nspname || '.' || c.relname AS object
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
UNION ALL
SELECT 'function', p.oid::regprocedure::text FROM pg_proc p
WHERE p.prosrc ~ '(tournament_user_roles|stage_edges)'
UNION ALL
SELECT 'view', v.schemaname || '.' || v.viewname FROM pg_views v
WHERE v.definition ~ '(tournament_user_roles|stage_edges)'
UNION ALL
SELECT 'policy', pol.polname FROM pg_policy pol
JOIN pg_class c ON c.oid = pol.polrelid
WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
UNION ALL
SELECT 'trigger', t.tgname FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
UNION ALL
SELECT 'incoming_fk', con.conname FROM pg_constraint con
WHERE con.contype = 'f'
  AND con.confrelid IN (
      SELECT c.oid FROM pg_class c
      WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
  );
```

**Aplicación y smoke:**

```sh
MIGRATION_TARGET=019 $COMPOSE run --rm db-migrate
$COMPOSE up -d api worker
```

El runner aplica la 019 en una transacción. Si falla por un pre-chequeo, corrige los datos y reintenta; si falla por una FK entrante, crea la migración que la resuelva. No hay estado a medias. Después comprueba `GET /docs`, una lectura pública de torneo y una operación del Workspace (incluida la asignación manual de equipos en un borrador). La 019 no crea funciones `SECURITY DEFINER` ni vistas nuevas.

**Si algo falla después:** no hay `down`. Corrige con una migración nueva. Restaurar `$HOME/backup-pre019.dump` solo si se acepta perder los cambios posteriores. Los scripts de `init/` no son migraciones y no se re-ejecutan en volúmenes existentes.

## Migración 020: forward-fix del privilegio `id` de rosters

La **020** no es destructiva y se aplica **después de la 019**. Añade solo el privilegio de columna `INSERT (id)` sobre `public.rosters` a `bracket_app`; no concede `INSERT` a nivel de tabla y no cambia datos ni funciones. Es necesaria porque la importación masiva sube las fotos antes de la transacción (N-2) y por eso la aplicación pre-genera el `id` del roster para construir la clave del objeto y compensar subidas.

```sh
MIGRATION_TARGET=020 $COMPOSE run --rm db-migrate
```

`init/01` incluye el mismo `GRANT INSERT (id, ...)` para que una instalación limpia termine con el mismo estado que una base migrada. `MIGRATION_TARGET=019` sigue limitando el runbook destructivo de la 019; la 020 se aplica después en una segunda ejecución o con el runner sin target.

## Migración 021: referencias de jugador en sustituciones (runbook)

La **021** es **aditiva**: añade `player_out_id` y `player_in_id` (UUID nulas) a `match_events`, dos FKs compuestas `(player_out_id, organization_id)` y `(player_in_id, organization_id)` a `players (id, organization_id)` con `ON DELETE RESTRICT`, y `chk_match_event_substitution_pair` como `CHECK ... NOT VALID`. **No elimina `match_segment_team_state`** (sigue siendo la proyección de contadores), no toca `transfers` (no existe como tabla) y no modifica `init/01` ni las migraciones 019/020.

**Orden de despliegue: migración 021 → código.** El código nuevo escribe las dos columnas y contra el esquema 020 falla al insertar una sustitución. A la inversa, el código anterior no escribe el par y sus eventos `substitution` no cumplen el `CHECK` nuevo, así que detén `api` y `worker` durante la ventana. No hay backfill: los eventos legados sin par se conservan, el motor los ignora y no se ejecuta `VALIDATE CONSTRAINT`.

**Antes de aplicar**, con una copia verificada:

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre021.dump"
$COMPOSE exec -T db pg_restore -l < "$HOME/backup-pre021.dump" >/dev/null && echo "backup OK"
$COMPOSE stop api worker
```

Pre-chequeos **informativos** (no abortan; los conteos quedan como evidencia):

```sql
SELECT count(*) AS eventos_substitution
FROM public.match_events
WHERE event_type = 'substitution';

SELECT count(*) AS filas_match_segment_team_state
FROM public.match_segment_team_state;
```

**Aplicación y smoke:**

```sh
MIGRATION_TARGET=021 $COMPOSE run --rm db-migrate
$COMPOSE build api
$COMPOSE up -d api worker
```

Comprueba `GET /docs`, una lectura pública de torneo, una operación del Workspace con un borrador y, si hay datos, la pantalla de operación de un partido (`GET /matches/{id}/operation`) y el cierre de un acta con una sustitución válida; la fila de `match_segment_team_state` del segmento debe reflejar el saldo.

**Si algo falla después:** no hay rollback de esquema ni de datos. La 021 no se desaplica y cualquier defecto se corrige con una migración nueva (*forward-fix*). Restaurar `$HOME/backup-pre021.dump` solo si se acepta perder los cambios posteriores. La cadena de volumen limpio (`init/00-03` → 001-021) termina con el mismo esquema que una base migrada.

## Migración 022: topes de minuto en eventos de partido (runbook)

La **022** es **aditiva**: añade a `public.match_events` los `CHECK` `chk_match_event_minute_range` (`minute BETWEEN 0 AND 180`) y `chk_match_event_added_minute_range` (`added_minute BETWEEN 0 AND 30`). No añade columnas, no toca datos ni `init/01` y no cambia las políticas RLS existentes. Son **topes estructurales**, no la regla deportiva: la API sigue aplicando el máximo efectivo de la fase (reglamentario/prórroga) y responde con su error actual (422) antes de llegar a la base.

En la misma transacción, un **pre-chequeo aborta** la migración si hay filas con `minute` fuera de 0..180 o `added_minute` fuera de 0..30, nombrando ambos conteos. No recorta ni corrige datos: el operador decide la corrección y aplica una migración nueva. Si el pre-chequeo pasa, las dos restricciones se añaden **validadas** (no `NOT VALID`), así que PostgreSQL recorre la tabla una vez y toma un bloqueo breve; aplícala en una ventana de baja actividad.

```sh
MIGRATION_TARGET=022 $COMPOSE run --rm db-migrate
```

**Orden de despliegue:** la 022 es compatible con el código actual (la API ya limita a 180/30), así que puede aplicarse antes o junto con el despliegue; va **antes** de la 023. **No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). La cadena de volumen limpio (`init/00-03` → 001-022) termina con el mismo esquema que una base migrada.

## Migración 023: vueltas de fase persistidas (runbook)

La **023** es **aditiva**: añade a `public.stages` la columna `schedule_legs SMALLINT NOT NULL DEFAULT 1` con `CHECK (schedule_legs IN (1, 2))` (`chk_stages_schedule_legs`). No reescribe filas, no toca `init/01` ni cambia las políticas RLS existentes: las fases que ya existen quedan en una vuelta. El sorteo de liga (`round_robin`) y de grupos (`custom_group`) escribe las vueltas recibidas en `legs`; el clonado de versiones copia el valor a la fase clonada; las eliminatorias y la fase Swiss conservan el default. Los triggers de estructura existentes impiden reescribir `schedule_legs` en una versión publicada o archivada.

```sh
MIGRATION_TARGET=023 $COMPOSE run --rm db-migrate
```

**Orden de despliegue: migración 023 → código.** El backend nuevo lee `schedule_legs` al cargar el borrador y lo escribe al sortear, así que contra el esquema 022 falla; va **después** de la 022. **No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). La cadena de volumen limpio (`init/00-03` → 001-023) termina con el mismo esquema que una base migrada.

**Limitación documentada:** no hay *backfill*, porque las vueltas de un calendario histórico no se pueden reconstruir. Una liga o fase de grupos de dos vueltas ya generada queda en una hasta que se regenere su calendario; mientras tanto, el límite de enfrentamientos manuales por pareja es uno. Como las versiones publicadas no admiten altas manuales, la limitación solo alcanza a borradores que aún no se han vuelto a sortear.

## Proyección interna de jugadores por torneo

`v_public_tournament_players` es una **proyección interna** de base de datos: ninguna ruta de la API la consulta y ninguna respuesta pública la expone. Se mantiene tal cual por decisión de producto (Q3 de la spec 008); retirarla o consumirla exige una spec propia.

- **Qué calcula:** `public_age` (edad derivada: `age_at_reference` más la diferencia de año entre el inicio del torneo y el año de referencia), junto con nombre, dorsal, equipo y `photo_url`. La calcula para el **rol de aplicación** (`bracket_app`): «público» significa respuesta de la API, no el acceso del rol de aplicación a la base.
- **Qué no expone:** documentos de identidad ni fechas de nacimiento; la definición no selecciona `national_id_*` ni `birth_date_encrypted`. Conserva su protección: solo filas activas de torneos publicados, en juego o finalizados, y `photo_url` solo con consentimiento de imagen.
- **Contrato público de jugadores:** sale de `v_public_match_lineups` en `GET /api/v1/tournaments/public/{id}/matches` (`player_id`, nombre, dorsal, rol, posición y `photo_url`), sin edad ni dato de identidad. `backend/tests/test_public_player_views.py` comprueba con base real que las respuestas públicas no incluyen edad, documento ni fecha de nacimiento y que ningún endpoint consume la proyección interna (opt-in con PostgreSQL; comando en `AGENTS.md`).

## Alcance inicial

- Registro y login por email/password.
- Preparación de Google OAuth mediante `auth_identities`.
- Organizaciones con membresías y RBAC.
- Torneos y versiones inmutables.
- Configuración privada de versiones, fases, equipos y partidos.
- Configuración JSON de puntuación, desempates, disciplina, sustituciones y ventana de inscripción; sin transferencias.
- Cierre de actas con goles, tarjetas, sustituciones, suspensiones y outbox.
- Clasificación Round Robin.
- Estructura de fases lista para grupos y playoffs.
- Avance manual de equipos entre fases en versiones en borrador.
- Autorización por organización y por partido (`match_officials`); sin roles por torneo.

## Reglas declaradas: sustituciones, inscripción y minutos

La configuración efectiva sale del `rules_config` de la versión del partido (con el override de la fase) y se aplica en el cierre; no hay reglas «informativas» en el editor.

- **Sustituciones:** `substitutions` (`max_per_team`, `max_windows`, `allow_reentry`; defaults **5/3/`false`**) se valida al cerrar el acta. Los límites son **por equipo y por partido**; `max_per_team = 0` deshabilita las sustituciones y `max_windows = 0` no admite ninguna ventana. Los eventos `substitution` llevan `player_out_id` y `player_in_id` y cumplen `player_id = player_out_id`. El estado en campo se deriva del XI de `match_rosters` y de los eventos en orden `(minute, added_minute, índice del acta)`: cada jugador tiene una **unión de intervalos** `[entrada, salida)` para modelar la reentrada. El cierre rechaza con **409** (sin escribir) un jugador de otro equipo o fuera de la plantilla, un saliente que no está en campo, un entrante en campo o expulsado, una reentrada no permitida, un exceso de sustituciones o ventanas y un evento fuera del intervalo del jugador; el incumplimiento estructural del evento es **422**. Los eventos de un acta confirmada son **inmutables** y no existe API incremental de eventos ni de anulación (R11 fuera de alcance); `is_voided` es legado.
- **Ventanas:** una ventana es el grupo `(segment_id, minute, added_minute)`. Varias sustituciones del mismo equipo en el mismo segmento y minuto (incluido el descuento) consumen **una** sola ventana; distinto segmento o distinto `added_minute` abren ventanas distintas.
- **Proyección de contadores:** `match_segment_team_state` guarda una fila por segmento y equipo con el saldo del partido tras ese segmento. Se asegura al abrir el segmento y se recalcula al cerrar ordenando por `segment_number`; la pantalla de operación calcula el estado con la misma función pura cuando la fila no existe y **no escribe** en un `GET`. La migración 021 **no elimina** esta tabla.
- **Transferencias retiradas:** `transfers` no se ofrece, no está en los defaults y no se escribe en configuraciones nuevas; los bloques existentes se aceptan como deprecados y se ignoran. La no participación en dos partidos de la misma jornada es una **restricción de base de datos** (`uq_matchday_player_unique`), no una regla configurable.
- **Ventana de inscripción (`roster_lock_matchday`):** clave de primer nivel, entero ≥ 1 o nulo (default nulo). El valor efectivo sale del `rules_config` de la **versión publicada**. La jornada de referencia es el `matchday` de la primera fase por `stage_order` (desempate por `id`) de esa versión, y el bloqueo se activa si hay al menos un partido no `cancelled` en esa jornada y **todos** están confirmados (`finished`/`administrative_resolution` + `result_confirmed`). Con el bloqueo activo, el alta individual y la importación responden **409** («La plantilla está cerrada desde la jornada {N}…») sin escribir filas ni subir objetos; la importación lo comprueba antes de subir fotos y de nuevo dentro de la transacción. No borra ni invalida inscripciones existentes.
- **Minutos:** `regular_time_minutes` y `extra_time_minutes` salen de `stage_defaults` con overrides por fase (defaults **90** y **120**). Al guardar se valida la **pareja efectiva** antes de persistir: reglamentario entre 1 y 179; si la prórroga está habilitada, extra mayor que el reglamentario y ≤ 180; si está deshabilitada, el extra no se valida ni se materializa. Un override parcial solo cambia lo que declara. El cierre aplica el **máximo efectivo** (extra si la resolución es `extra_time`/`penalties` y la prórroga está habilitada; reglamentario en el resto), exige `minute + added_minute` dentro del máximo salvo descuento en el minuto final y separa goles reglamentarios y de prórroga en `regular_time_minutes`. El tope estructural de 180 y `added_minute ≤ 30` no es una regla de negocio.
- **Impacto al desplegar una versión `3.2.0`:** una versión `3.2.0` **ya publicada** empieza a aplicar sus límites de sustitución en cuanto se despliega este código, porque la configuración efectiva sale de la versión publicada y no se reescribe. Las actas ya cerradas **no se revalidan** y los partidos aún abiertos pueden rechazar sustituciones que antes aceptaban; conviene revisar las configuraciones afectadas antes de desplegar.
- **Contrato interno:** `docs/contrato-reglas.md` (`engine_version` **2026.1**) fija los códigos `GF1`/`GF2` y el catálogo cerrado de cuatro formaciones con sus posiciones. No es configurable desde el editor; una formación fuera del catálogo responde **422**.

## Autorización y avance manual entre fases

- **Modelo real:** RBAC por **organización**. Los permisos (`MANAGE_TOURNAMENTS`, `MANAGE_MEMBERS`, `CLOSE_MATCH_REPORT`, etc.) se resuelven con la membresía y sus roles de organización; no existe un ámbito por torneo. La única delegación menor es por **partido**: `match_officials` permite que el árbitro asignado cierre ese partido. La tabla `tournament_user_roles` fue **retirada** por la migración 019 y no hay endpoint ni UI para asignar roles por torneo.
- **Lectura:** `GET /api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams` responde **200** con `{stage_id, version_id, assigned, unassigned}`. `assigned` son los equipos de `stage_teams` de esa fase y versión (deduplicados por `team_id` si hay varias filas en grupos); `unassigned` son los equipos del torneo con estado `registered` que no están asignados a esa fase. No mezcla asignaciones de otras versiones. Un torneo o fase inexistente o de otra organización responde **404**. Es una lectura de organización y no exige `MANAGE_TOURNAMENTS`.
- **Asignación:** `POST /api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams` con `{"team_ids": ["<uuid>", ...]}`. Admite **1 a 64** equipos y rechaza duplicados con **422** sin deduplicar. Responde **201** con `assigned` (nuevos) y `already_assigned` (preexistentes) si hay al menos una alta, **200** con `assigned=[]` si todos ya estaban, **409** si la versión no es borrador o si algún equipo no está `registered` (sin escribir ninguno), **403** sin `MANAGE_TOURNAMENTS`, **404** si el torneo o la fase no existen. El lote es **atómico todo-o-nada**.
- **Retirada:** `DELETE /api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams/{team_id}` responde **204** de forma idempotente. Precedencia: **404** torneo/fase → **409** versión publicada/archivada (aunque el equipo no estuviera asignado) → **403** sin permiso → **409** equipo no `registered` → **409** si hay un partido de la fase que lo referencie → **409** si tiene fila de `standings` en la fase (aunque no haya partidos). Si tiene varias filas `stage_teams` en la fase, se eliminan todas. No borra partidos, grupos, `phase_slots` ni `standings`.
- **Solo borradores:** las versiones publicadas o archivadas siguen siendo inmutables; cualquier asignación o retirada sobre ellas responde **409**. La asignación y la retirada bloquean **fase → versión**; el protocolo completo de las rutas que operan partidos añade **partido(s) → segmentos → jugadores**.
- **Sin regeneración automática:** asignar o quitar equipos **no** altera el calendario, los grupos, los slots ni los partidos existentes. El operador debe regenerar o sortear explícitamente el calendario para incluir los cambios.
- **Procedencia, no motor:** `phase_slots` se conserva como procedencia de la llave (`direct_team`/`match_result`) y se clona, pero no se resuelve entre fases. El sembrado automático por `stage_rank` **no está soportado** y ese valor fue retirado del `CHECK`. `tournament_versions.phase_config` se almacena pero no se interpreta.
- **Estructura publicada:** el trigger de inmutabilidad lanza el SQLSTATE estable **`ZZ409`**; la API lo traduce a **409** comparando el código, nunca el texto del mensaje.

## Tiempo real y outbox

El cierre de actas y los efectos de dominio se registran en `outbox_events`. Un worker publica cada evento en el stream de Redis `bracket_craft.events` y el relay de la API lo reenvía por Socket.IO a la sala de la organización y, para los eventos públicos, a la del torneo. El stream es un **transporte vivo de mejor esfuerzo**, no un registro duradero ni la fuente de verdad.

- **Tope fijo:** cada escritura usa `MAXLEN` aproximado de 10 000 entradas (`OUTBOX_STREAM_MAXLEN`). Es una constante del backend, sin variable de entorno; el recorte mantiene el orden de magnitud, no un número exacto. El criterio de dimensionamiento es P-1: un cierre de partido produce unos 3 eventos, así que 10 000 entradas cubren varios días de operación normal con unos pocos MB.
- **Sobre del evento:** `event_id` (el `id` de la fila de outbox), `id` legado con el mismo valor durante la transición, `organization_id`, `event_type` y `payload`. El payload de dominio no cambia; `event_id` es aditivo.
- **Arranque y reconexión:** un proceso nuevo del relay resuelve la posición en el último id y **no reemite el histórico**. Si se pierde la conexión con Redis con el proceso vivo, conserva la posición y **reanuda** desde ahí, por lo que puede repetir entradas retenidas.
- **`RESYNC`:** evento de control `{event_id, reason}` con `reason` entre `JOIN`, `RELAY_START`, `STREAM_TRIMMED` y `REDIS_RESET`. No lleva datos de negocio, no se persiste y no se escribe en el stream. `JOIN` va solo al socket que entra en su sala; los huecos se emiten a las salas con clientes conectados; sin clientes no se emite nada.
- **Cliente:** deduplica por `event_id` en una ventana FIFO de 200 entregas y separa `RESYNC` de los eventos de dominio. El Workspace y la operación de partido recargan al reconectar; la página pública mantiene su polling de 30 s mientras el socket no está conectado y, ante un `RESYNC` de hueco, recarga y reinicia la paginación.
- **Estado visible del reintento manual:** además de `connecting`, `connected`, `reconnecting`, `error` e `idle`, el estado de conexión tiene un valor propio `retrying` («Reintentando…» / «Retrying…»), anunciado con `role="status"` y con color de aviso compartido con `reconnecting`/`error` (no depende solo del color). **Solo** aparece al pulsar «Reintentar» con el estado en error y **solo si esa pulsación inicia un intento de conexión nuevo**: un clic sin efecto no muestra nada y nunca aparece por reconexión automática ni sin pulsación. Desaparece al conectar o al volver a error; no altera la lógica de reconexión, las recargas ni el sondeo, y no añade instrumentación de pruebas al producto.
- **Alcance por organización, sin filtro de rol (riesgo aceptado, R32f):** el relay emite cada evento a la sala `organization:{id}`, así que **todo miembro conectado** de la organización lo recibe con independencia de su rol o permisos, y el payload no se filtra por evento. *Mitigación vigente:* cada 30 s se revalidan la sesión, la membresía y la huella de permisos; si cambian, el socket se desconecta y deja de recibir eventos. Un filtrado por evento y por rol exige una spec propia y no forma parte de la spec 008.

| Tramo | Garantía | Consecuencia |
|---|---|---|
| `outbox_events` → stream | at-least-once | El mismo evento puede escribirse más de una vez con el mismo `event_id`. |
| stream → cliente | best-effort | Hay huecos (reinicio, recorte, caída de Redis, cliente desconectado) y duplicados posibles; se mitigan con `RESYNC`, deduplicación, polling y reconciliación. |
| cliente → API HTTP | fuente de verdad | Cualquier estado visible se reconstruye con una recarga HTTP; el tiempo real es una optimización. |

## Auditoría organizacional de la operación

Guardar la planilla de un partido, publicar o despublicar la formación de un equipo, asignar o retirar un oficial y reabrir una invitación revocada dejan **una** entrada en `administrative_audit_logs` con la acción, el sujeto afectado, el miembro que la ejecuta y, en las acciones de partido, un resumen (formaciones, conteos y un digest de contenido; nunca nombres, correos, documentos ni el contenido de la planilla).

- La reapertura de una invitación escribe `REOPEN_INVITATION` con la invitación y el miembro que la ejecuta, sin correo ni token; crear, reenviar y revocar invitaciones no añaden entradas y la aceptación conserva `ACCEPT_INVITATION`.

- La entrada depende del **cambio efectivo**: repetir la misma publicación o el mismo guardado no añade nada aunque la petición actualice marcas de tiempo, y las lecturas no generan entradas.
- La inserción ocurre en la misma transacción: una operación fallida o revertida no deja rastro, y no se duplica el registro del cierre de acta ni el de la interrupción de segmento.
- Las entradas quedan sujetas al aislamiento por organización y no se exponen en ninguna ruta ni proyección pública. No hay endpoint ni pantalla de consulta de esta auditoría.

## Rendimiento, fotos y conexión

Los límites de esta sección son constantes del backend: no hay variables de entorno, migraciones ni dependencias nuevas.

- **Sorteo Swiss:** una fase admite como máximo **64 equipos**; el conjunto contado es el de equipos registrados y asignados a la fase. Superarlo responde **422** («La fase Swiss admite como máximo 64 equipos») antes de escribir y antes de calcular. En rondas posteriores a la primera no se borran marcadores ni partidos de rondas anteriores.
- **Presupuesto determinista:** **50 000** evaluaciones de pares por solicitud (40 000 para la búsqueda con retroceso y una reserva de 10 000 para el fallback). El fallback nunca relaja «no repetir rivales» ni las metas de local/visitante.
- **Ejecución:** el emparejamiento corre en un **ejecutor dedicado de 2 hilos** (no el ejecutor por defecto) con un **timeout de seguridad de 10 s**. Un hilo de Python no se puede cancelar: al vencer, el resultado se descarta, la petición responde **409** y el hilo termina por agotar su presupuesto.
- **Errores del sorteo:** **409** para presupuesto de emparejamiento agotado, sorteo imposible sin repetir rivales, tiempo máximo de cálculo excedido y estado de la fase cambiado entre la lectura y la escritura. Los `ValueError` de validación conservan su comportamiento actual (no se convierten en 409).
- **Frontera de transacción:** la lectura (con RLS) se cierra antes de calcular y de firmar. La escritura abre una transacción nueva, vuelve a fijar el contexto RLS, revalida el permiso de gestión y el estado con bloqueo (`FOR UPDATE`) y solo entonces escribe; ningún fallo deja un calendario parcial.
- **Fotos:** se firman en lote, una vez por clave distinta y con un solo despacho off-thread, después de cerrar la transacción. Las subidas y borrados de objetos ocurren con la transacción cerrada. El objeto anterior de una subida se borra **solo tras un commit confirmado**: si el commit falla o se cancela (resultado ambiguo) se conservan el anterior y el nuevo, y el nuevo puede quedar huérfano. La importación compensa las subidas si falla antes del commit, pero un commit fallido puede dejar objetos huérfanos (best-effort); se prefiere un huérfano a una referencia rota. Un cliente de firma cacheado por proceso y endpoint de firma evita reconstruirlo por jugador; la URL conserva el TTL de `STORAGE_PRESIGN_SECONDS` (300 s por defecto). **Rotar las credenciales de almacenamiento exige reiniciar el proceso**.
- **Fallo de firma:** en los endpoints públicos la respuesta sigue siendo **200** con `photo_url: null` en las fotos afectadas; en el Workspace responde **503** («El almacenamiento de fotos no está disponible»). Se registra una sola entrada por respuesta, sin claves ni datos personales.
- **Alta e importación:** si la firma falla después del commit, la fila ya está creada y la respuesta es **503**; el cliente debe releer antes de reintentar.
- **Conexión:** `statement_timeout` de **15 s**, `idle_in_transaction_session_timeout` de **30 s** y pool de **10 + 10** con espera de **10 s** por proceso. El agotamiento del pool responde **503** («Servicio temporalmente no disponible») con un único aviso, y la API registra los valores efectivos al arrancar.
- **Agregado de conexiones:** con `API_WORKERS=2` y un worker del outbox son 2 × 20 + 20 = **60** conexiones teóricas frente a las **100** por defecto de PostgreSQL. Subir `API_WORKERS` o bajar `max_connections` exige revisar ese agregado.
- **Conexión administrativa:** `scripts.encrypt_birth_dates` abre su propia conexión con `DATABASE_ADMIN_URL` y no hereda los timeouts ni el pool del engine de la aplicación.
- **Riesgo residual aceptado:** en la ronda 1, una fase sin partidos no ofrece filas que bloquear, así que dos sorteos simultáneos en frío podrían insertar calendarios duplicados (no hay unicidad de `bracket_code`). Se corrige fuera de este bloque si se prioriza.
- **Cierre serializado por fase:** el cierre toma el lock de fase (y después versión y partidos), por lo que dos cierres de la misma fase se serializan. Es una decisión de corrección, no una promesa de rendimiento; **no se midió** throughput ni latencia (RNF-003).

## Verificación

Las dependencias de ejecución y las de prueba se declaran en archivos separados. `backend/requirements-dev.txt` se instala en local y en CI y **nunca** entra en la imagen de producción, que instala solo `backend/requirements.txt`; la auditoría de dependencias cubre ambos archivos:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cd backend && pytest -q
cd backend && python -m compileall -q app
```

Con Node 24 y pnpm 12.12.1, la auditoría de dependencias del frontend se ejecuta desde la raíz del repositorio:

```sh
AUDIT_JSON="/tmp/pnpm-audit.json"
trap 'rm -f "$AUDIT_JSON"' EXIT
if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
```

El filtro `infra/scripts/audit_frontend.py` falla ante cualquier hallazgo `high` o `critical` con corrección publicada, muestra los no accionables (incluidos los que no tienen parche) para su revisión y no persiste exclusiones. No se admiten listas de GHSA ni flags que persistan exclusiones, como `--ignore-unfixable`, `audit.ignore` o `auditConfig.ignoreGhsas`. El resto de comprobaciones de CI está en `AGENTS.md` y la política completa en la §3.4 de `docs/constitution.md`.

El contrato de entorno y las aserciones de Compose se ejecutan sobre la configuración renderizada. El merge de producción requiere las variables dummy que detalla `AGENTS.md`:

```sh
docker compose config --format json | python3 infra/scripts/check_env_contract.py -
python3 infra/scripts/check_env_contract.py --self-test
docker compose config --format json | python3 infra/scripts/assert_production_compose.py --profile development -
docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json \
  | python3 infra/scripts/assert_production_compose.py -
```

### E2E del reintento del tiempo real

El arnés vive en `frontend/e2e/` (Playwright con un solo motor **Chromium headless**, `workers: 1` y `retries: 0`) y comprueba la secuencia completa en las tres vistas —pública `/tournaments/{id}`, panel `/workspace` y operación `/workspace/matches/{id}`—: conexión estable, caída real del transporte con el canal bloqueado solo para `/socket.io/`, estado de error, pulsación de «Reintentar» con el canal aún bloqueado, estado manual «Reintentando…», fallo del intento, desbloqueo y reconexión, con como máximo una recarga de datos por consumidor y ninguna del documento. También verifica dos ciclos de pulsación y que no quedan intentos ni conexiones de más.

```sh
cd frontend && pnpm exec playwright install --with-deps chromium   # una vez por máquina
cd frontend && pnpm run e2e        # arranca la pila, siembra, ejecuta y baja
cd frontend && pnpm run e2e:test   # solo el escenario, con la pila ya levantada y sembrada
```

`pnpm run e2e` requiere Docker, `cp .env.example .env` y Chromium instalado; arranca con `docker compose up -d --build --wait --wait-timeout 300` (≤5 min, informado aparte), ejecuta el seed demo, corre el escenario y baja la pila que arrancó. `pnpm run e2e:test` es el comando del job de integración continua. Códigos de salida: **0** verde (las tres vistas sin omisiones), **1** fallo de comportamiento, **2** fallo de infraestructura (pila, datos demo o navegador) y **3** corrida inválida (vista omitida/ausente o escenario no concluyente); la invalidez no acusa al producto pero no abre el gate.

Los artefactos quedan en `frontend/e2e-report/` (ignorado por git y sin cookies ni tokens): `summary.json` con la tabla de las tres vistas, un `view-<vista>.json` por vista con marcas y recuentos, una traza propia `trace-<vista>.jsonl` por vista con peticiones sin cabeceras y la consola del navegador, capturas en `screenshots/` **solo** cuando el veredicto de esa vista no es verde (una corrida verde no deja capturas) y `server.log` con el registro saneado de `api`, `worker` y `web`.

En el resumen, **`states` son las muestras** observadas por estado (no transiciones) y **`transitions` cuenta las transiciones**: pares consecutivos de muestras con estado distinto; la primera muestra no cuenta y una vista sin dos muestras da `0`. Si el artefacto de una vista falta o está inválido, `transitions` es `null` y la tabla muestra `-` en la columna `TRANSICIONES` (las columnas son `MUESTRAS` y `TRANSICIONES`). El campo es aditivo y opcional: `schemaVersion` del resumen sigue siendo `1` y el veredicto 0/1/2/3 no lo consulta.

El `server.log` lleva siempre la cabecera exacta `# server.log — docker compose logs --no-color api worker web` y se considera **disponible** solo si además tiene al menos una línea de contenido (no basta la cabecera; una línea `# no disponible: …` lo declara no disponible). Se escribe también en local, no solo en la integración continua; si el entorno no tiene Docker (por ejemplo, el contenedor del arnés) el fichero declara `# no disponible: docker CLI ausente` en lugar de faltar en silencio. El paso de integración continua **solo reescribe** `frontend/e2e-report/server.log` cuando el arnés **no** lo dejó disponible; si está disponible, lo conserva tal cual. El estado de sesión en `frontend/.auth/state.json` nunca se publica.

**No cubre:** la entrega duplicada del transporte (queda en las pruebas unitarias de deduplicación) ni el conteo de sesiones del servidor. El identificador de sesión no forma parte del artefacto de esta entrega: es un dato opcional, no evaluado y no concluyente.

## Seguridad

El backend establece `app.current_organization_id` y `app.current_user_id` dentro de cada transacción. Las tablas tenant-owned tienen RLS y las vistas públicas no exponen documentos ni fechas de nacimiento.

La autorización efectiva es **RBAC por organización** (roles y permisos de la membresía) más el ámbito menor de **`match_officials`** por partido. No hay roles por torneo: `tournament_user_roles` fue retirada por la 019. La inmutabilidad de versiones publicadas se refuerza con triggers; el conflicto de estructura usa `ZZ409` y la API responde **409** sin comparar el texto.

Toda escritura valida `Origin` y `Referer` **por separado**: sin ninguna de las dos se admite (renderizado en servidor y clientes externos); si cualquiera está presente y no es un origen permitido, responde **403**, aunque la otra sí lo esté. Un `Referer` vacío o no parseable también se rechaza. Un proxy que reescriba `Referer` a un host interno debe permitir ese origen o retirar la cabecera; de lo contrario sus escrituras serán rechazadas.

La fecha de nacimiento se almacena cifrada con `PLAYER_DATA_KEY` y el rol de aplicación no puede leer el texto cifrado (patrón *write-only*, igual que el documento). Desde la migración 017 tampoco puede leer ni insertar la fecha en claro; solo escribe el campo cifrado y la edad derivada. La API y el Workspace exponen la edad (`age` solo en `GET /tournaments/{id}/rosters`), nunca la fecha completa. La exposición declarada —la edad y el año de referencia permiten inferir el año de nacimiento— es el mismo dato derivado que la proyección pública ya mostraba. La rotación de `PLAYER_DATA_KEY` y el tratamiento de copias anteriores a la 017 son deuda separada.

La administración global está separada del workspace en `/admin`. Requiere un registro en `platform_admins`; para el primer arranque local se puede indicar `PLATFORM_ADMIN_EMAIL` en `.env` después de registrar la cuenta. Las acciones de usuarios, organizaciones y membresías se auditan en `platform_audit_logs` y no permiten editar directamente resultados ni versiones publicadas.

Las credenciales de desarrollo (`bracket_app`, `POSTGRES_PASSWORD`, `JWT_SECRET` y `PLAYER_DATA_KEY`) incluidas en `.env.example` son únicamente para desarrollo local. En producción deben inyectarse mediante secretos externos y `APP_ENV=production`; el backend rechazará los defaults conocidos. El perfil `docker-compose.production.yml` no publica ningún puerto, deja los servicios internos en una red privada, une solo `web` a la red externa del proxy, elimina los volúmenes de código, desactiva `--reload`, construye el frontend estático y exige los secretos y URLs de producción (ver «Despliegue de producción»).
