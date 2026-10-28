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

Las proyecciones públicas de torneos, tablas y partidos se sirven desde `/api/v1/tournaments/public`, `/api/v1/tournaments/public/{id}`, `/api/v1/tournaments/public/{id}/standings`, `/api/v1/tournaments/public/{id}/matches`, `/api/v1/tournaments/public/{id}/player-stats` y `/api/v1/tournaments/public/{id}/team-stats`. Los partidos incluyen la planilla pública cuando existe; la formación táctica solo aparece después de publicarse explícitamente desde el Workspace. Las dos últimas rutas son las tablas de estadísticas de jugadores y de equipos (spec 022), que incluyen la portería imbatida según la definición única documentada más abajo.

La configuración local incluye un almacenamiento S3-compatible (SeaweedFS) con interfaz de archivos en `http://localhost:9001`. La importación de plantillas acepta CSV/TXT con `first_name`, `last_name`, `national_id`, `birth_date` y `dorsal_number`; `photo_filename` vincula imágenes JPG, PNG o WEBP incluidas en un ZIP opcional. La proyección pública solo devuelve `photo_url` cuando el roster tiene consentimiento de imagen.

## Navegación del Workspace del torneo

Cada área de gestión del torneo tiene su **dirección propia**: abrir, recargar o compartir la dirección devuelve a esa sección, y el índice del torneo marca como activa solo la que está abierta (la sección se deriva de la ruta, nunca de un valor fijo de la pantalla).

| Ruta | Contenido |
|---|---|
| `/workspace/tournaments/{id}` | Configuración: resumen, reglas (asistente), fases (asistente) y equipos (asistente). Conserva las anclas `#resumen`, `#configuracion` y `#equipos` |
| `/workspace/tournaments/{id}/calendar` | Calendario: crear partido, sortear o regenerar (con confirmación antes de reemplazar) y lista de partidos con enlace a su operación. `?stage=` elige la fase |
| `/workspace/tournaments/{id}/rosters` | Plantillas: **única** pantalla de alta de jugadores, con formulario único por equipo (alta individual, importación CSV/ZIP, foto y consentimiento), aviso de cierre de inscripción y enlace al asistente de fases. `?team=` elige el equipo |
| `/workspace/matches/{id}` | Operación del partido: segmentos, planilla, oficiales, eventos y cierre. Sin alta de jugadores; enlaza a la plantilla del equipo |

- **Fragmentos antiguos:** `#calendario` y `#plantillas` **redirigen** a su ruta propia reemplazando la entrada de historial (`#calendario` conserva `?stage=`); `#resumen`, `#configuracion` y `#equipos` siguen resolviendo como anclas dentro de configuración.
- **Asistentes de reglas, fases y equipos:** el paso actual vive en la dirección (`?step=`, la única fuente: se abre con el paso pedido, se actualiza con `router.push` al cambiar de paso —una entrada por paso, así el atrás vuelve al anterior— y se normaliza una sola vez al montar con `router.replace` cuando la dirección no nombra ningún asistente) y los valores introducidos en el **almacenamiento de sesión de la pestaña**, con clave por usuario, organización, torneo, versión y asistente (`bc_wizard:{wizard}:{userId}:{orgId}:{tournamentId}:{versionId}`). Recargar conserva paso y datos; otra pestaña u otro dispositivo empiezan desde el estado del servidor; cerrar la pestaña descarta el borrador. No se envía nada al servidor hasta confirmar y ningún valor del formulario se escribe en la dirección. El borrador local del **partido** (eventos y datos del cierre, en `localStorage`) es un almacén distinto y no guarda el paso de ningún asistente.
- **Plantillas y operación:** la operación enlaza a la plantilla del equipo con `returnTo`. La pantalla de plantillas ofrece «Volver a la operación» solo cuando ese destino es la operación de un partido **de este torneo** (ruta interna, sin origen externo ni parámetros y con el partido entre los del torneo cargado); si no es válido no se muestra. Al cambiar de equipo se conserva el enlace de vuelta y, al volver, se restauran el partido, el segmento seleccionado y el borrador local.
- **Observadores (rol `viewer`):** la entrada «Configuración» deja de ocultarse y se muestra en **solo lectura**, igual que el calendario y las plantillas, sin ninguna acción de escritura. Es un cambio de **visibilidad, no de permisos**: las capacidades del miembro con permiso de gestión no cambian y el servidor sigue siendo la autoridad.
- **Aislamiento:** las pantallas nuevas reutilizan los endpoints existentes, que filtran por organización con el contexto de la transacción. La ruta solo aporta el identificador del torneo; la fase (`?stage=`), el equipo (`?team=`) y el retorno (`returnTo`) solo se aceptan si están entre los datos del propio torneo ya cargados, y un identificador ajeno no se muestra ni se inventa.

Para ejecutar únicamente el frontend fuera de Docker:

```bash
cd frontend
pnpm install
pnpm dev
```

## Acceso con Google

El acceso con Google usa **solo el flujo de redirección con código**: el navegador recibe la dirección del proveedor, el código se canjea en el servidor y la sesión se entrega con la cookie existente. Ningún token del proveedor pasa por el navegador.

**Configuración.** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` y `GOOGLE_AUDIENCE` (= `client_id`) ya existían; `GOOGLE_REDIRECT_URI` es obligatoria cuando Google está habilitado, debe ser una URL absoluta `http(s)` y registrarse en Google Cloud Console con la ruta exacta `{API pública}/api/v1/auth/google/callback`. Su valor de desarrollo está en `.env.example`. Sin `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` el flujo queda deshabilitado.

| Endpoint | Respuesta |
|---|---|
| `GET /auth/google/status` | `200 {"enabled": bool}` (público, sin secretos) |
| `POST /auth/google/start` | Cuerpo `{"flow": "login" o "link", "redirect": texto o null}` → `200 {"authorization_url": …}`; guarda el intento y fija `bc_oauth_state` (`HttpOnly`, `SameSite=Lax`, `Path=/api/v1/auth/google`, `Max-Age=600`) |
| `GET /auth/google/callback` | Login → `302 {frontend}/auth/callback?next=…` + cookie de sesión; vinculación → `302 /account/google?notice=GOOGLE_LINK_SUCCESS`; error → `302 /login?error=<CODE>` (o `/account/google?error=<CODE>` en la vinculación) |
| `GET /auth/session` | `200 {"user_id", "organization_id"}` (primera organización del orden estable o `null`) |
| `GET /auth/google/link` | `200 {"linked": bool}`; sin sesión, `401` |
| `POST /organizations` | `{"name", "slug"}` → `201 {id, name, slug, organization_user_id}`; `409` sin `code` si la cuenta ya tiene organización; `409 ORGANIZATION_SLUG_TAKEN` si el identificador está ocupado |

**Estado e intentos.** El intento vive en Redis con clave `sha256(state)` y TTL de 600 s; se consume con `GETDEL` (un solo uso), se compara con la cookie del navegador y un inicio nuevo invalida el anterior. Si Redis no responde, el flujo responde **503 GOOGLE_UNAVAILABLE** sin escribir.

**Catálogo de códigos (`?error=`):** `GOOGLE_UNAVAILABLE`, `GOOGLE_CANCELLED`, `GOOGLE_STATE_INVALID`, `GOOGLE_IDENTITY_INVALID`, `ACCOUNT_DISABLED`, `ACCOUNT_EXISTS_PASSWORD`, `ACCOUNT_EXISTS_GOOGLE_ONLY`, `GOOGLE_ALREADY_LINKED`, `LINK_EMAIL_MISMATCH`, `LINK_IDENTITY_TAKEN`, `RATE_LIMITED` y `ORGANIZATION_SLUG_TAKEN`; el aviso de éxito es `GOOGLE_LINK_SUCCESS`. El cliente traduce `code`; el servidor no muestra códigos crudos en pantalla.

**Cuentas y vinculación.** Una cuenta creada con Google nace sin contraseña y con su identidad en la misma transacción. Una cuenta local con contraseña recibe `ACCOUNT_EXISTS_PASSWORD` y debe entrar con su contraseña y vincular desde **`/account/google`**; la vinculación exige que el correo verificado coincida, no emite ni revoca sesión y nunca reescribe `users.email`. Un identificador de Google ya vinculado a otra cuenta responde `LINK_IDENTITY_TAKEN`.

**Organización opcional.** Una sesión sin organización llega a **`/organization`** (también enlazada desde `/login`): nombre e identificador explícitos, sin creación automática. «Ahora no» conserva la cuenta y la sesión y muestra el aviso de organización no activa.

**Retiro del camino anterior.** `POST /auth/google` (el que aceptaba un `access_token` del navegador) responde **410** `{"detail": …, "code": "GOOGLE_IDENTITY_INVALID"}` antes de leer el cuerpo, sin rate limit, proveedor ni escritura. Un cliente antiguo recibe un rechazo estable, no un 404.

**Log de acceso.** La API arranca con `--no-access-log` en desarrollo y producción y registra una línea saneada por petición —`access method=… path=… status=…`— sin consulta, cabeceras ni cuerpo: el `code`/`state` del proveedor nunca llega al log.

**Migración 024 (runbook).** Aditiva: un pre-chequeo **aborta con el conteo** si una cuenta tiene más de una identidad del mismo proveedor (no borra, fusiona ni reescribe filas) y después añade `uq_auth_identity_user_provider UNIQUE (user_id, provider)`. Sin grants nuevos, sin RLS y sin tocar `init/01`.

```sh
MIGRATION_TARGET=024 $COMPOSE run --rm db-migrate
```

**Orden: migración 024 → código.** El código nuevo funciona con el esquema 023, pero sin la restricción dos intentos simultáneos podrían dejar dos identidades en una cuenta. **No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). El volumen limpio (`init/00-03` → 001-024) termina con el mismo esquema que una base migrada.

**Comprobación manual (T30, no ejecutada).** El job `e2e` **no** cubre Google. En este entorno no hay un cliente OAuth real configurado, así que la corrida manual —alta, reentrada sin duplicados, `ACCOUNT_EXISTS_PASSWORD` + vinculación, cancelación + `GOOGLE_STATE_INVALID` y retorno a una invitación— **no se ejecutó**; no se registran fecha ni resultados. Queda pendiente para un entorno de desarrollo con credenciales reales y su resultado se anotará aquí (fecha, entorno y códigos observados, sin correos ni identificadores).

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

La **022** es **aditiva**: añade a `public.match_events` los `CHECK` `chk_match_event_minute_range` (`minute BETWEEN 0 AND 180`) y `chk_match_event_added_minute_range` (`added_minute BETWEEN 0 AND 30`). No añade columnas, no toca datos ni `init/01` y no cambia las políticas RLS existentes. Son **topes estructurales**, no la regla deportiva: la API sigue aplicando el máximo efectivo de la fase antes de llegar a la base (ver «Duración y resolución prevista» y `AGENTS.md` → «Minutos») y responde con su error actual (422).

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

## Escudos de equipo

Una persona con `MANAGE_TOURNAMENTS` carga, reemplaza, consulta y elimina **una** imagen por equipo desde el torneo donde el equipo está inscrito. La imagen pertenece al equipo y se comparte entre todos los torneos en los que se inscribe; no hay permiso por torneo. Quien solo consulta (`viewer`) ve la imagen y **no** ve ningún control de escritura; el servidor rechaza la escritura con **403** sin escribir, sin borrar objetos y sin llamar al almacenamiento. El escudo **no es dato personal** y no exige consentimiento de imagen (las fotos de jugadores conservan el suyo).

**Una sola fuente de verdad.** `logo_url` (la dirección externa heredada) se sigue devolviendo mientras el equipo no tenga escudo y pasa a `null` con la primera carga confirmada; no se descarga, no se copia, no se verifica y no se restituye al eliminar. El Workspace muestra esa dirección mientras no haya escudo; **las superficies públicas nunca la muestran**. Sin escudo (o si la imagen no carga) el sustituto son los dos primeros caracteres del código corto —o del nombre si el código tiene menos de dos—, sin icono roto y sin reintento automático: el enlace nuevo se pide cuando la vista vuelve a cargar los datos.

**Endpoints** (Workspace; exigen `X-Organization-ID` y membresía con rol):

| Método y ruta | Permiso | Respuesta |
|---|---|---|
| `GET /api/v1/tournaments/{tournament_id}/teams/{team_id}/crest` | contexto (membresía con rol) | `200 TeamCrestResponse` |
| `POST /api/v1/tournaments/{tournament_id}/teams/{team_id}/crest` | `MANAGE_TOURNAMENTS` | `200 TeamCrestResponse` (carga o reemplazo) |
| `DELETE /api/v1/tournaments/{tournament_id}/teams/{team_id}/crest` | `MANAGE_TOURNAMENTS` | `204`, idempotente |

`TeamCrestResponse` es `{ team_id, crest_url, logo_url }`: `crest_url` es un enlace firmado temporal (`STORAGE_PRESIGN_SECONDS`, 300 s por defecto) o `null`; la referencia interna `crest_object_key` no se devuelve como campo en ninguna respuesta, no aparece en mensajes de error ni en registros y no se guarda en la auditoría.

**Campos de lectura.** `GET /tournaments/{id}/teams` añade `crest_url` por fila; `GET /matches/{id}/operation` añade `match.home_team_crest_url`/`match.away_team_crest_url` (sin las claves) **y** `match.home_team_logo_url`/`match.away_team_logo_url`, la dirección externa que el Workspace usa como respaldo mientras no haya escudo y que nunca se publica; el detalle público añade `teams: [{team_id, name, short_code, crest_url}]` (`[]` sin equipos), la clasificación `crest_url` por fila, los partidos `home_team_crest_url`/`away_team_crest_url` y las alineaciones publicadas `lineup.home.crest_url`/`lineup.away.crest_url`. Ninguna respuesta pública incluye `logo_url`, la clave interna, nombre de archivo, tamaño, documentos, edad ni fecha de nacimiento.

**Validación declarada.** Se admiten **JPG, PNG y WEBP estáticos** con un máximo de **5 MiB** (`STORAGE_MAX_IMAGE_BYTES`, **compartido con las fotos de jugadores**: cambiarlo afecta a ambas funciones). Manda el **contenido**, no el nombre ni la extensión: un archivo llamado `.png` con bytes JPEG se acepta y se sirve como JPEG. Se rechazan el archivo vacío, el exceso de tamaño, SVG y GIF, y la animación **declarada en el contenedor** (PNG con `acTL` antes de `IDAT`; WEBP con el bit de animación de `VP8X` o el bloque `ANIM`). **Lo que no se garantiza**, porque el servidor no decodifica: un contenedor truncado o corrupto con cabecera admitida se acepta y se sirve; los metadatos incrustados se sirven tal cual (no se eliminan); y una animación o corrupción que solo se manifieste al decodificar no se detecta. Las dimensiones tampoco se limitan: el servidor no las lee y el navegador sí.

**Almacenamiento y degradación.** La imagen vive en el espacio privado (clave `private/organizations/{org}/tournaments/{tournament_id}/teams/{team_id}/…`, generada por el sistema); `teams.crest_object_key` guarda la referencia. La subida y la preparación de enlaces ocurren **con la transacción cerrada**; la escritura usa `SELECT … FOR UPDATE` sobre el equipo, deja `logo_url = NULL` y audita en la misma transacción; el objeto anterior se borra **solo tras un commit confirmado**. Si el almacenamiento falla al subir → **503** `CREST_STORAGE_UNAVAILABLE`, sin fila modificada y con la imagen anterior intacta; si falla la firma, el Workspace responde **503** y las superficies públicas dejan el campo en `null` con **200** y una sola entrada de registro. Un borrado fallido del archivo anterior deja un huérfano declarado, registra una línea y no convierte la respuesta en error. Los cambios de escudo **no emiten eventos**: otras vistas abiertas no se refrescan hasta que vuelven a pedir los datos (RF-53, RF-54).

**Auditoría.** Cada carga, reemplazo o eliminación **efectiva** escribe `SET_TEAM_CREST` o `REMOVE_TEAM_CREST` en `administrative_audit_logs` (entidad `teams`, payload solo con `tournament_id`) en la misma transacción. Una operación rechazada, repetida o sin cambio no deja entrada.

**Catálogo de errores** (`detail` sigue siendo una cadena y `code` es aditivo):

| Código | Estado | Cuándo |
|---|---|---|
| `CREST_FILE_EMPTY` | 422 | Archivo vacío |
| `CREST_FORMAT_UNSUPPORTED` | 422 | El contenido no es JPG/PNG/WEBP (incluye SVG y GIF) |
| `CREST_ANIMATION_UNSUPPORTED` | 422 | Animación detectable en el contenedor |
| `CREST_TOO_LARGE` | 422 | Supera el máximo de imagen |
| `CREST_NOT_FOUND` | 404 | Equipo inexistente, de otra organización o no inscrito en el torneo del contexto |
| `CREST_FORBIDDEN` | 403 | Sin `MANAGE_TOURNAMENTS` |
| `CREST_UPLOAD_FAILED` | 500 | Fallo no clasificado durante la operación (compensado antes de responder) |
| `CREST_STORAGE_UNAVAILABLE` | 503 | Fallo del almacenamiento al subir o al firmar |

El miembro activo sin rol recibe el 403 de contexto de la organización, **sin** código propio. Un torneo inexistente o de otra organización responde el 404 existente («Torneo no encontrado»). Superar el límite global del cuerpo se rechaza antes de la operación y no pertenece a este catálogo.

**Comprobación manual pendiente (no ejecutada).** La carga de una imagen real en un navegador, el recorrido completo de la operación solo con teclado y el anuncio del lector de pantalla **no se han ejecutado** en esta entrega; quedan como comprobación manual pendiente de la verificación final de la spec 014 y no se declaran verdes.

**Riesgos aceptados.** Huérfanos sin recolección ni cota si un borrado falla o la confirmación es ambigua; sin cuota por organización; metadatos no eliminados; animación y truncamiento no garantizados; enlaces ya entregados que no se pueden revocar antes de su caducidad (300 s) y posibles cachés de navegador, intermediarios o terceros; `logo_url` externa visible en el Workspace mientras no haya escudo (expone la IP del personal a un tercero; nunca en público); ninguna vista se refresca sola al cambiar un escudo. La comprobación manual de teclado y lector de pantalla se declara en la verificación final de la spec.

## Migración 025: escudos de equipo (runbook)

La **025** es **aditiva** y va **después** de la 024: añade `teams.crest_object_key` (`TEXT` nula, sin default ni índice) y la vista pública `public.v_public_tournament_teams` (`security_barrier = true`, `REVOKE ALL … FROM PUBLIC` y `GRANT SELECT … TO bracket_app`). No toca `init/01`, `init/02` ni las migraciones 001–023, no añade filas, políticas ni restricciones y no reescribe datos (no hay *backfill*: la columna llega nula). La columna hereda el `GRANT` de tabla y la RLS de `teams`; la vista filtra la misma visibilidad que `v_public_tournaments` (versión publicada, torneo `published`/`live`/`finished` y organización activa) y no expone `logo_url`, documentos, edad ni fecha de nacimiento.

**Orden de despliegue: 024 → 025 → código.** La 024 pertenece al PR de Google (spec 013) y aún no está en `main`; el runner aplica en orden numérico las no registradas y esta rama funciona también con el hueco de la 024. El código nuevo lee y escribe `crest_object_key`: contra el esquema 024 falla, mientras que la imagen anterior sigue funcionando con la columna nueva (es nula y no la selecciona). Si esta rama llegara a `main` antes que la 024, la 025 se **renumera** en el merge; no se edita ni se desaplica una migración aplicada.

Prepara una copia verificada y detén `api` y `worker`:

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre025.dump"
$COMPOSE exec -T db pg_restore -l < "$HOME/backup-pre025.dump" >/dev/null && echo "backup OK"
$COMPOSE stop api worker
```

Pre-chequeo informativo (no aborta; deja evidencia de que la 025 no estaba aplicada):

```sql
SELECT count(*) AS columna_existente
FROM pg_attribute
WHERE attrelid = 'public.teams'::regclass
  AND attname = 'crest_object_key'
  AND attnum > 0 AND NOT attisdropped;

SELECT to_regclass('public.v_public_tournament_teams') AS vista_existente;

SELECT has_table_privilege('bracket_app', 'public.teams', 'UPDATE') AS app_update_teams;
```

Aplica la migración **antes** que el código nuevo:

```sh
MIGRATION_TARGET=025 $COMPOSE run --rm db-migrate
$COMPOSE build api
$COMPOSE up -d api worker
```

**Smoke:** `GET /docs`, una lectura pública (`/api/v1/tournaments/public`, el detalle, la clasificación y los partidos), el listado de equipos de un torneo y la operación de un partido; si hay datos, carga un escudo real, comprueba que `teams.crest_object_key` queda escrita y que `v_public_tournament_teams` devuelve el equipo del torneo publicado (y no el de un borrador o una organización inactiva), reemplázalo y elimínalo. La firma real contra SeaweedFS es opcional; el almacenamiento simulado ya está cubierto por la suite.

**No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). Restaurar el backup solo si se acepta perder los cambios posteriores. La cadena de volumen limpio (`init/00-03` → 001-025) termina con el mismo esquema que una base migrada y `backend/tests/test_migration_025.py` lo comprueba (opt-in con PostgreSQL).

## Migración 026: asistencia del gol (runbook)

La **026** es **aditiva** y va **después** de la 025: añade `match_events.assist_player_id` (`UUID` nula, sin default ni índice), la clave foránea compuesta `(assist_player_id, organization_id)` a `players(id, organization_id)` con `ON DELETE RESTRICT` y el `CHECK` `chk_match_event_assist` —la asistencia solo existe en `goal` y nunca repite al goleador—, añadido **validado** porque la columna nace nula y no hay filas que lo incumplan. No reescribe filas, no toca `init/01` ni `init/02`, no cambia políticas ni grants y no tiene *backfill*: los goles ya cerrados quedan sin asistente y siguen siendo válidos. El mismo equipo, la plantilla del partido y la presencia en campo son autoridad de la API (**409** `ASSIST_PLAYER_INVALID`) y no se modelan en la base.

Prepara una copia verificada y aplica la migración; el `CHECK` validado toma un bloqueo breve sobre `match_events`, así que conviene una ventana de baja actividad:

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre026.dump"
$COMPOSE exec -T db pg_restore -l < "$HOME/backup-pre026.dump" >/dev/null && echo "backup OK"
MIGRATION_TARGET=026 $COMPOSE run --rm db-migrate
$COMPOSE build api
$COMPOSE up -d api worker
```

La migración solo imprime conteos (eventos `goal` y cuántos llevan asistencia) y no aborta por datos históricos.

**Orden de despliegue: migración 026 → código.** El backend nuevo escribe `assist_player_id` en cada acta y contra el esquema 025 falla por columna inexistente; la imagen anterior ignora la columna nula y sigue cerrando actas, así que no hace falta detener `api` ni `worker` durante la ventana.

**Smoke:** `GET /docs`, una lectura pública de torneo y, si hay datos, la operación de un partido (`GET /matches/{id}/operation`) y el cierre de un acta con un gol con asistencia válida; comprueba que el evento devuelve `assist_player_id` y que un acta sin asistencia sigue cerrando.

**No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). Restaurar el backup solo si se acepta perder los cambios posteriores. La cadena de volumen limpio (`init/00-03` → 001-026) termina con el mismo esquema que una base migrada y `backend/tests/test_migration_026.py` lo comprueba (opt-in con PostgreSQL).

## Migración 027: motivo del walkover (runbook)

La **027** es **correctiva y aditiva** y va **después** de la 026: `chk_administrative_resolution_reason` solo admitía motivo en `administrative` y lo exigía nulo para cualquier otra resolución, así que el código del walkover no cabía en `resolution_reason`. La 027 reemplaza esa restricción por una que admite en `walkover` `NULL` (filas históricas y un despliegue en el que la migración llegue antes que el código) o uno de los cuatro códigos del catálogo (`no_show`, `withdrawal`, `insufficient_players`, `sanction`), conserva en `administrative` el motivo obligatorio de 1..1000 caracteres y sigue prohibiendo el motivo en `regular`, `extra_time` y `penalties`. No añade columnas, índices, políticas, grants ni RLS, no reescribe filas, no toca `init/01` y no tiene *backfill*. La obligatoriedad y el catálogo son autoridad de la API: la base no exige motivo en un walkover.

Prepara una copia verificada y aplica la migración; el `CHECK` validado recorre `matches` una vez y toma un bloqueo breve, así que conviene una ventana de baja actividad:

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre027.dump"
$COMPOSE exec -T db pg_restore -l < "$HOME/backup-pre027.dump" >/dev/null && echo "backup OK"
MIGRATION_TARGET=027 $COMPOSE run --rm db-migrate
$COMPOSE build api
$COMPOSE up -d api worker
```

**Orden de despliegue: migración 027 → código.** El backend nuevo escribe un motivo no nulo en `resolution_reason` y contra el esquema 026 el `UPDATE` violaría la restricción, así que el cierre respondería un 409 de integridad engañoso; la imagen anterior convive con la 027 sin cambios porque sigue escribiendo `NULL`.

**Smoke:** `GET /docs`, una lectura pública de un torneo y, si hay datos, la operación de un partido (`GET /matches/{id}/operation`), donde `limits.walkover_score` debe traer la pareja efectiva, y el cierre de un acta como walkover con su motivo; después el partido debe mostrar `resolution_type: "walkover"`, el marcador derivado y el resultado en la clasificación.

**No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). Restaurar el backup solo si se acepta perder los cambios posteriores. La cadena de volumen limpio (`init/00-03` → 001-027) termina con el mismo esquema que una base migrada y `backend/tests/test_migration_027.py` lo comprueba (opt-in con PostgreSQL).

## Migraciones 029, 030 y 031: estadísticas públicas y proyecciones públicas (runbook)

Las tres son **aditivas**, van **después** de la 028 (spec 021, `segment_number` en la vista pública de alineaciones), **no reescriben datos** y **no tienen *backfill***:

- **029 — `organization_id` en la proyección pública de torneos.** Recrea `public.v_public_tournaments` añadiendo `organization_id` como última columna de salida, para que el backend pueda fijar el contexto RLS del rol de aplicación al servir lecturas públicas de un torneo. Es una columna **interna**: no forma parte de ningún modelo de respuesta pública. No añade ni retira tablas, columnas de tablas base, filas, políticas, grants ni índices; `CREATE OR REPLACE VIEW` conserva `security_barrier`, propietario y privilegios.
- **030 — vistas públicas de eventos, segmentos y plantillas.** Crea `public.v_public_match_events`, `public.v_public_match_segments` y `public.v_public_tournament_rosters`, las tres con `security_barrier`, `REVOKE ALL … FROM PUBLIC` y `GRANT SELECT` solo a `bracket_app`. Filtran por organización activa, torneo en estado público y versión publicada, y el aislamiento entre organizaciones sale de sus `JOIN`. Son las que leen las dos rutas de estadísticas para calcular las cifras.
- **031 — proyección interna con todas las formaciones publicadas.** Crea `public.v_public_match_formations` (`security_barrier`, `REVOKE` de `PUBLIC` y `GRANT SELECT` solo a `bracket_app`), que devuelve por partido, segmento y equipo **todas** las formaciones tácticas con `is_public` verdadero —jugador, `position_slot`, titular y `segment_number`—, porque `v_public_match_lineups` solo devuelve la última formación publicada por equipo. Es una **proyección interna**: no es contrato público ni aparece en ningún modelo de respuesta; la lee `GET /api/v1/tournaments/public/{id}/player-stats` para el cálculo de la portería imbatida (con ella el cálculo recibe la formación del primer segmento y la del portero entrante).

Ninguna toca `init/01` ni `init/02`, no añade políticas de RLS y no cambia `engine_version` (2026.1). Prepara una copia verificada y aplica las tres en orden; un pre-chequeo informativo confirma el eslabón anterior de la cadena:

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre029.dump"
$COMPOSE exec -T db pg_restore -l < "$HOME/backup-pre029.dump" >/dev/null && echo "backup OK"
$COMPOSE exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT max(version) FROM schema_migrations"'
MIGRATION_TARGET=029 $COMPOSE run --rm db-migrate
MIGRATION_TARGET=030 $COMPOSE run --rm db-migrate
MIGRATION_TARGET=031 $COMPOSE run --rm db-migrate
$COMPOSE build api
$COMPOSE up -d api worker
```

**Orden de despliegue: 029 → 030 → 031 → código.** Las dos rutas nuevas leen `organization_id` de `v_public_tournaments` para fijar el contexto RLS y consultan las vistas de la 030: contra el esquema 028 fallan por columna o relación inexistente, así que primero las migraciones. Al ser aditivas, la imagen anterior convive con las tres sin cambios (no lee las vistas nuevas y no selecciona la columna nueva), de modo que no hace falta detener `api` ni `worker` durante la ventana; el runner aplica en orden numérico y valida el checksum de todos los archivos. La 031 la consume solo la ruta `player-stats` (cálculo de la portería imbatida), así que el código nuevo la necesita en el esquema: aplica la migración antes del despliegue.

**Smoke:** `GET /docs`, una lectura pública de un torneo y, con datos, las dos tablas de estadísticas (`GET /api/v1/tournaments/public/{id}/player-stats` y `…/team-stats`), que deben responder con cifras y con `404` indistinguible para un torneo no visible; después, la operación de un partido del Workspace (`GET /matches/{id}/operation`) y una lectura de detalle, que no deben cambiar. Post-chequeo de catálogo: las cuatro vistas de la 030 y la 031 existen, tienen `security_barrier` y solo `bracket_app` conserva el `SELECT`.

**No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). Restaurar el backup solo si se acepta perder los cambios posteriores. La cadena de volumen limpio (`init/00-03` → 001-031) termina con el mismo esquema que una base migrada; `backend/tests/test_migration_028.py` y `backend/tests/test_migration_031.py` lo comprueban (opt-in con PostgreSQL y `DATABASE_ADMIN_URL`), y las pruebas de migración de la **029** y la **030** están pendientes en esta ronda (spec 022, T1).

## Proyección interna de jugadores por torneo

`v_public_tournament_players` es una **proyección interna** de base de datos: ninguna ruta de la API la consulta y ninguna respuesta pública la expone. Se mantiene tal cual por decisión de producto (Q3 de la spec 008); retirarla o consumirla exige una spec propia.

- **Qué calcula:** `public_age` (edad derivada: `age_at_reference` más la diferencia de año entre el inicio del torneo y el año de referencia), junto con nombre, dorsal, equipo y `photo_url`. La calcula para el **rol de aplicación** (`bracket_app`): «público» significa respuesta de la API, no el acceso del rol de aplicación a la base.
- **Qué no expone:** documentos de identidad ni fechas de nacimiento; la definición no selecciona `national_id_*` ni `birth_date_encrypted`. Conserva su protección: solo filas activas de torneos publicados, en juego o finalizados, y `photo_url` solo con consentimiento de imagen. Un jugador **retirado lógicamente** deja de listarse mientras esté inactivo (012, RC-1).
- **Contrato público de jugadores:** sale de `v_public_match_lineups` en `GET /api/v1/tournaments/public/{id}/matches` (`player_id`, nombre, dorsal, rol, posición y `photo_url`), sin edad ni dato de identidad. `backend/tests/test_public_player_views.py` comprueba con base real que las respuestas públicas no incluyen edad, documento ni fecha de nacimiento y que ningún endpoint consume la proyección interna (opt-in con PostgreSQL; comando en `AGENTS.md`).

## Matriz de acceso (público vs. privado)

Spec 020 audita y documenta qué es público: la consulta pública es de **solo lectura**, no escribe datos y **no añade campos públicos nuevos** (RNF-001) en esa spec; solo reorganiza la navegación por fases y grupos y deja constancia de lo que ya se publica. La spec 021 añade aditivamente un único campo nuevo al contrato público: `segment_number` (entero, nullable) en `PublicTeamLineupResponse`, para etiquetar la formación con su segmento (RF-007, RF-015); no cambia permisos ni la matriz de acceso. La spec 022 añade **dos lecturas públicas** —`player-stats` y `team-stats`— y **un solo cambio no aditivo** (publicar el nombre de jugadores que participaron en partidos con resultado confirmado aunque no figuren en una alineación publicada, RF-033); no añade escrituras, permisos ni rutas nuevas fuera de esas dos lecturas.

### Público (sin sesión, sin organización activa, sin credenciales)

Lecturas anónimas sobre torneos **visibles públicamente** (versión publicada, estado publicado/en juego/finalizado, organización activa). Las rutas `/` y `/tournaments/{id}` son públicas.

| Lectura | Ruta |
|---|---|
| Listado de torneos | `GET /api/v1/tournaments/public` |
| Detalle del torneo (fases, equipos) | `GET /api/v1/tournaments/public/{id}` |
| Clasificación (filtrable por `stage_id`, `group_id`) | `GET /api/v1/tournaments/public/{id}/standings` |
| Partidos (con alineaciones publicadas) | `GET /api/v1/tournaments/public/{id}/matches` |
| Estadísticas de jugadores (goles, amarillas, rojas, porterías imbatidas) | `GET /api/v1/tournaments/public/{id}/player-stats` |
| Estadísticas de equipos (goles a favor/en contra, porterías imbatidas, fair play) | `GET /api/v1/tournaments/public/{id}/team-stats` |

- Un torneo no visible responde el mismo `404` indistinguible de uno inexistente (RF-014).
- Partidos visibles: programados, en juego, finalizados y de resolución administrativa; **suspendidos y cancelados no se publican**.
- Fotos solo con **inscripción vigente** + consentimiento de imagen + foto cargada; `photo_url` es nulo en cualquier otro caso, incluido un jugador **retirado lógicamente** aunque su inscripción retirada tenga consentimiento y foto cargada, y también si falla la firma. Sin foto se muestran las iniciales, sin hueco ni imagen rota.
- Formación táctica solo si se publicó explícitamente desde el Workspace; en otro caso, planilla; si hay formación sin publicar, no se publica ni formación ni planilla.
- Las tablas de estadísticas deben cubrir por defecto el **torneo completo** —sin filtro de fase ni de grupo y sin preseleccionar la primera fase—, con el filtro por fase (o por grupo dentro de la fase) como acción **explícita** y **reversible**. Ese ámbito por defecto es la decisión de producto de la spec 022 (RF-021) y **sigue pendiente** en esta ronda de corrección (T15/T6): hoy la pantalla aún envía la primera fase al pedir las dos tablas.
- Los campos de cada respuesta forman una **lista cerrada** (RF-015); la verificación automática falla ante cualquier campo fuera de la lista. La spec 020 no añade campos nuevos; la spec 021 añade aditivamente `segment_number` (entero, nullable) a `PublicTeamLineupResponse` (RF-007, RF-015). La spec 022 añade dos modelos nuevos, `PublicPlayerStatsResponse` y `PublicTeamStatsResponse`, que fijan el conjunto de campos de cada fila, y un **cambio no aditivo**: publicar nombres de jugadores que participaron en partidos con resultado confirmado aunque no figuren en una alineación publicada (RF-033); la plantilla inscrita sigue sin publicarse y no salen asistencias, sanciones ni suspensiones. Declarar esos dos modelos como `response_model` de sus rutas ya está hecho (spec 022, T5) y es lo que aplica el filtro de la lista cerrada; la prueba con datos reales que lo demuestra llega con T17.

### Exige sesión (Workspace y administración)

Todo lo demás requiere sesión válida, organización activa y el permiso correspondiente (RBAC por organización más `match_officials` por partido): Workspace (`/workspace`), administración global (`/admin`), operación de partidos, escrituras, invitaciones, miembros, etc.

### Nunca sale en público (RF-016)

Documentos de identidad, fecha de nacimiento, edad y año de referencia de la edad; la dirección externa heredada del escudo (`logo_url`); claves internas de almacenamiento (`crest_object_key` y claves de foto); el motivo de un walkover o de una resolución administrativa; sanciones y suspensiones; **la plantilla inscrita del equipo** (la lista de jugadores inscritos en el torneo), también en las tablas de estadísticas; la **asistencia** del gol (no se publica en ninguna proyección ni ruta pública); registros de auditoría; datos de miembros u organizaciones. Ningún torneo ni dato de otra organización se mezcla en una respuesta (RF-017). Ninguna escritura, cookie ni dependencia de sesión se añade a la consulta pública (RF-018).

### Verificación automática

- `backend/tests/test_public_field_allowlist.py` — lista cerrada de campos públicos (RF-015) y ausencia de campos sensibles (RF-016).
- `backend/tests/test_public_access_matrix.py` — lecturas anónimas, `404` indistinguible, aislamiento entre dos organizaciones y parámetros de consulta fuera de rango → `422` con `detail` en lista y sin `code`. **Cubre el listado, el detalle, la clasificación, los partidos y, desde la spec 022 (T18), las dos tablas de estadísticas** (`player-stats` y `team-stats`) en la lectura anónima, el `404` indistinguible y el `422` de parámetros; el aislamiento **con datos** y la lista cerrada de esas dos rutas se verifican en `test_public_stats_endpoints.py`.
- `backend/tests/test_public_stats_endpoints.py` (opt-in con PostgreSQL) — es donde vive la verificación de las dos rutas de estadísticas: torneo no visible → `404` indistinguible, aislamiento entre dos organizaciones con datos reales, `422` de parámetros fuera de rango y lista cerrada de campos de las dos respuestas.
- `backend/tests/test_public_stats.py` (puro, sin base) — cálculo de las estadísticas y definición de la portería imbatida, con 58 pruebas (incluidas las tres estáticas que comprueban que la ruta de jugadores lee `v_public_match_formations` y no `v_public_match_lineups`); que haya **una prueba identificable por cada caso límite `CL-1` a `CL-12`** sigue pendiente en esta ronda (spec 022, T19).

## Alcance inicial

- Registro y login por email/password.
- Acceso con Google por redirección, vinculación desde la cuenta y organización opcional.
- Organizaciones con membresías y RBAC.
- Torneos y versiones inmutables.
- Configuración privada de versiones, fases, equipos y partidos.
- Configuración JSON de puntuación, desempates, disciplina, sustituciones y ventana de inscripción; sin transferencias.
- Cierre de actas con goles (asistencia opcional), tarjetas, sustituciones, suspensiones y outbox.
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
- **Duración y resolución prevista:** la regla normativa —minutos reglamentario y de prórroga, máximo efectivo por resolución, tiempo añadido y resolución prevista— está en `AGENTS.md` → «Minutos»; aquí solo se describe lo que ve el operador. Un único control fija la resolución prevista (por defecto, tiempo reglamentario), muestra el máximo de minuto aplicable y el tope de minuto añadido, se restaura al recargar desde la sesión de la pestaña y se envía al crear o interrumpir segmentos y al cerrar; la operación valida cada registro contra ese máximo antes de enviarlo. Cambiar a una resolución incompatible con segmentos ya guardados se bloquea; si solo afecta a eventos del borrador, se avisa sin borrar, y cerrar con otra resolución compatible pide confirmación explícita. Contrato aditivo: `GET …/operation` expone en `limits` `max_minute_regular`, `max_minute_extra` (nulo sin prórroga), `extra_time_enabled` y `penalties_enabled` junto a las cuatro claves anteriores; `POST …/segments` y `POST …/segments/{id}/interrupt` aceptan `resolution_type` opcional y, sin él, el servidor aplica el máximo de la fase; crear segmento, interrumpir o cerrar con una resolución no habilitada responde **409** con `detail` de cadena y `code` aditivo `RESOLUTION_NOT_ENABLED`. Un cliente antiguo que ignore los campos nuevos y `code` sigue funcionando. `docs/contrato-reglas.md` **no cambia ninguna regla**: la spec 012 solo añade una aclaración de alcance (ver la sección siguiente).
- **Impacto al desplegar una versión `3.2.0`:** una versión `3.2.0` **ya publicada** empieza a aplicar sus límites de sustitución en cuanto se despliega este código, porque la configuración efectiva sale de la versión publicada y no se reescribe. Las actas ya cerradas **no se revalidan** y los partidos aún abiertos pueden rechazar sustituciones que antes aceptaban; conviene revisar las configuraciones afectadas antes de desplegar.
- **Contrato interno:** `docs/contrato-reglas.md` (`engine_version` **2026.1**) fija los códigos `GF1`/`GF2` y el catálogo cerrado de cuatro formaciones con sus posiciones. No es configurable desde el editor; una formación fuera del catálogo responde **422**. El formato de juego y los límites de plantilla **no** forman parte de ese contrato cerrado: son configuración aditiva con defaults que no cambian el comportamiento (ver la sección siguiente).

## Formato de juego, límites de plantilla y retiro lógico

El asistente de reglas pregunta **cómo serán los torneos** y **cuántos jugadores** admite cada plantilla. Son tres claves de la configuración de la versión; el detalle de contrato está en `AGENTS.md` → «Contratos que cambian».

- **Formato (`game_format`):** catálogo cerrado de `5v5`, `7v7`, `9v9` y `11v11`, con **`11v11` por defecto**. Es **declarativo e informativo**: no deriva ni acota el mínimo ni el máximo, no impone jugadores y no cambia las formaciones, los titulares ni la planilla. Con un formato distinto de `11v11` se muestra una advertencia visible —que la planilla soportada es de once y que la modalidad real llegará con la spec de formaciones— en el **paso de reglas**, el **resumen de configuración** y la **operación/planilla**; no bloquea ninguna acción. En una versión publicada o archivada se ve en solo lectura.
- **Límites (`min_players_per_team`, `max_players_per_team`):** enteros ≥ 0, **independientes del formato**. La clave ausente o el valor **0** significan «sin límite» (el comportamiento anterior); el campo vacío se normaliza a 0 al salir y la API rechaza una cadena vacía con **422**. Solo se exige **mínimo ≤ máximo** cuando ambos son mayores que cero. Cuentan los **jugadores activos** de la plantilla del equipo en el torneo, no los alineados.
- **Editar la plantilla nunca se bloquea por tamaño:** el alta individual, la importación CSV/ZIP, la foto y el consentimiento guardan siempre; si el equipo queda fuera de rango, la pantalla muestra un aviso destacado con la cantidad y el rango (`cumple` / `por debajo` / `por encima`).
- **Tres superficies de bloqueo:** inscribir el equipo en una fase, crear un equipo **con fase destino** (`POST /teams` o `/teams/bulk` con `stage_id`, lote todo o nada) y **abrir el partido** (su primer segmento). Si algún equipo participante está fuera de rango, responden **409** con `code: ROSTER_SIZE_OUT_OF_RANGE` y un `detail` que nombra equipo, mínimo, máximo y cantidad actual («sin límite» para 0 o ausente). Sin límites configurados no se añade ninguna comprobación; la apertura rechazada no crea el segmento ni cambia el estado del partido. El detalle es determinista: todos los equipos si son diez o menos; si son más, los diez primeros por nombre (desempate por identificador) y el total.
- **Retiro lógico y reactivación:** en la pantalla de plantillas, un jugador puede **retirarse** (deja de contar como inscrito activo y no se ofrece para alinear) y **reactivarse**. La fila no se borra y el histórico, las alineaciones y los resultados ya registrados no cambian; las respuestas públicas de la API siguen igual y la proyección interna `v_public_tournament_players` deja de listarlo mientras está retirado. La **reactivación** equivale a un alta: conserva el **409** del bloqueo por jornada y los conflictos de jugador ya activo en el torneo o de dorsal ocupado. El **retiro** es la **única** excepción a ese bloqueo (RL-1), porque solo reduce la plantilla. Ni el retiro ni la reactivación escriben auditoría. Contrato aditivo e idempotente: `PATCH /api/v1/tournaments/{tournament_id}/rosters/{roster_id}/status` con `{ "is_active": boolean }`, que devuelve el mismo modelo que la lista de plantilla; un roster de otro torneo u organización responde **404**.

## Eventos del acta y asistencias

El acta se compone con un **catálogo cerrado de siete tipos**. Todos comparten equipo, minuto, minuto añadido, segmento, tipo y `client_event_id` (UUID); cada tipo pide solo lo suyo y los campos que no le corresponden **no se envían**:

| Tipo | Campos propios | Efecto en el juego |
|---|---|---|
| `goal` | jugador (goleador) y **asistente opcional** | Suma un gol al equipo del jugador |
| `penalty_goal` | jugador | Suma un gol al equipo del jugador |
| `own_goal` | jugador (autor) y **equipo beneficiario**, obligatorio y distinto del equipo del jugador | Suma un gol al equipo beneficiario |
| `yellow_card` | jugador | Fair play; acumulación |
| `red_card` | jugador y clase de roja (`direct_red` por defecto o `double_yellow_red`) | Expulsión y suspensión; fair play |
| `substitution` | jugador que sale y jugador que entra, distintos | Estado en campo; cupo y ventana |
| `foul` | jugador | Ninguno: es informativo y no sanciona |

- **Catálogo cerrado (cambio observable para clientes).** Una clave de primer nivel que el tipo no declara es **422** (antes se ignoraba). `metadata` solo admite `red_card_type` en `red_card`: cualquier otra clave, en cualquier tipo, es **422** y no se persiste ni llega a la auditoría. `beneficiary_team_id` solo se admite en `own_goal`; informado en otro tipo —incluido un gol con su propio equipo— es **422**. `assist_player_id` solo en `goal`.
- **La regla del acta se generalizó (spec 019).** El cierre del catálogo del acta pasó a ser la regla de **toda** la API: cualquier clave que el esquema del cuerpo JSON no declare responde **422** estructural (lista de errores, sin `code`), también en el primer nivel de la configuración de reglas, que antes la descartaba en silencio. Un cliente que **solo envía campos declarados no nota nada**; el que enviaba una clave de más recibía un éxito con la clave perdida y ahora recibe un 422: la clave aparece en la ubicación del error en los objetos que cierra el modelo de la petición y, en los bloques anidados de la configuración de reglas, el camino va solo en el mensaje. Las tres operaciones multipart (importación de plantillas, foto de jugador y escudo) quedan fuera. El detalle está en `AGENTS.md` → «Contratos que cambian» (entrada **019**) y «Claves no declaradas en el cuerpo (spec 019)».
- **Identificador de cliente.** `client_event_id` exige **forma de UUID** (con mayúsculas o minúsculas); cualquier otro texto es **422** y no se guarda. El cliente genera `crypto.randomUUID()` y, si el navegador no lo ofrece, no añade el evento y lo explica en lugar de inventar un texto: el respaldo de texto anterior ya no se acepta. El servidor lo normaliza a minúsculas al comparar y al escribir, así que dos reintentos con distinta caja son el mismo evento. La forma se valida **solo en la API** (la base no añade `CHECK`) y los eventos históricos con identificador de texto libre se conservan y no se revalidan.
- **Asistencia.** `assist_player_id` es opcional en `goal`, como máximo uno por gol y **distinto del goleador** (**422** si coincide). Debe ser un jugador de la **misma plantilla del partido**, del **mismo equipo** que el goleador y **en campo** en el minuto del gol; si no, **409** con `detail` de cadena y `code` aditivo `ASSIST_PLAYER_INVALID`. La operación devuelve solo el identificador (UUID), sin nombre: el cliente lo resuelve con la plantilla del partido que ya recibe. Un mismo jugador puede asistir dos goles del mismo partido.
- **Asistencia opaca al juego.** No cambia el marcador, la clasificación, el fair play, las sanciones ni el ganador, no emite eventos de outbox y no se publica en ninguna proyección ni ruta pública. Un gol sin asistente es válido siempre y no se exige.
- **Identificadores de otra organización.** Regla única del acta: partido, segmento, equipo y equipo beneficiario de otra organización responden **404** sin revelar existencia (equipo y beneficiario pasan de **409** a **404**); un jugador de otra organización o fuera de la plantilla del partido sigue siendo **409**, nunca 404 ni 500.
- **Sin rutas ni permisos nuevos.** La escritura sigue siendo la del cierre; el miembro sin rol conserva su **403** y el observador lee sin escribir.
- **Contrato de reglas.** `docs/contrato-reglas.md` (`engine_version` **2026.1**) no cambia: el catálogo de eventos y la asistencia son aditivos y quedan **fuera** del contrato cerrado, que solo cubre los códigos de llave y las formaciones. El detalle de contrato para clientes está en `AGENTS.md` → «Contratos que cambian».

## Cierre de actas y segmentos

El cierre es una **operación atómica**: se valida completa y, si algo falla, no se escribe nada. El contrato detallado está en `AGENTS.md` → «Cierre del acta (spec 017)», «Marcadores del cierre (spec 017)», «Doble amarilla (spec 017)» y «Segmentos y propuesta (spec 017)»; aquí se describe lo que observa el operador y el cliente.

- **Orden único de validación:** (1) sesión y organización —un partido inexistente o de otra organización responde **404** al cargarlo—; (2) permiso `CLOSE_MATCH_REPORT` **y** rol operativo o asignación como oficial (**403** si falta la conjunción); (3) estado no terminal y versión publicada; (4) dos equipos; (5) resolución habilitada; (6) estructura del acta: segmento activo, segmentos, tiempos e intervalo; (7) participantes y plantilla; (8) estado en campo y sustituciones; (9) asistente del gol; (10) doble amarilla; (11) marcador frente a eventos; (12) sanciones; (13) coherencia de la resolución y del ganador; (14) escritura. Entre dos defectos de **dominio** se informa el del paso anterior; los errores de dominio son **409** con `detail` de cadena, salvo el **403** de la autorización y los **404** de aislamiento. Un fallo en cualquier paso no escribe eventos, contadores, marcador, clasificación, avance, sanciones, auditoría ni outbox.
- **Excepción estructural (sin cambio):** los **422** del esquema —claves o campos no aplicables, rangos del modelo, `client_event_id` duplicado en la misma acta o más de 500 eventos— se resuelven antes del handler, prevalecen sobre cualquier paso de dominio y no llevan `code`.
- **La resolución no habilitada va antes:** el paso 5 precede a «sin segmento activo» y a la plantilla. Un cierre con `extra_time` sin prórroga habilitada (o `penalties` sin penales) responde **409** `RESOLUTION_NOT_ENABLED` aunque además falte el segmento activo o la plantilla; antes el orden lo decidía el lugar de cada comprobación.
- **Marcadores y cambio de código:** el reglamentario informado debe coincidir con los goles cuyo `minute` no supera `regular_time_minutes` (el minuto añadido no clasifica el gol). `regular` exige el reglamentario, el final es opcional y debe igualarlo, y no admite penales, goles posteriores al reglamentario ni `reason`; `extra_time` exige final ≥ reglamentario y ganador; `penalties` exige final igual al reglamentario (empate) y tanda con ganador; `administrative` exige final igual al reglamentario, ganador y motivo; `walkover` no pasa por esa matriz: se declara con el ganador y un motivo de catálogo, el marcador se **deriva** de la fase y no se envía ninguno de los seis campos (ver «Walkover (W.O.)»). Las comprobaciones de **presencia** siguen siendo **422**; las cuatro de **coherencia numérica** —final menor que el reglamentario, `regular` con final distinto, `penalties` sin empate y tanda igualada— pasan de **422** a **409** de dominio con `detail` de cadena y **sin** `code`. Un cliente que dependiera del 422 en esos cuatro casos observa un cambio.
- **El resultado se calcula antes de escribir:** el paso 13 calcula el marcador y el ganador con los eventos de la **petición**, no con los persistidos, así que un acta inválida no deja ninguna fila. La reutilización idempotente de un evento ya guardado hace equivalente ese cálculo a lo que finalmente se escribe.
- **Doble amarilla:** una roja marcada como `double_yellow_red` exige **exactamente dos** amarillas previas del mismo jugador en el mismo partido, contadas en orden `(minute, added_minute, índice del acta)`. Cero, una o tres o más responden **409** con `detail` de cadena (el minuto, nunca un nombre) y `code` aditivo `DOUBLE_YELLOW_INCONSISTENT`, sin escribir. La roja directa no cambia, una segunda amarilla no deriva en roja y las actas cerradas no se revalidan: un acta abierta que incumpla la regla deja de poder cerrarse.
- **Propuesta de segmento:** `GET /api/v1/matches/{id}/operation` devuelve `next_segment` con `{segment_number, minute_start, derived}` o `null`, derivado de los segmentos e interrupciones ya persistidos: sin segmentos `{1, 0, true}`; último interrumpido, el minuto de su interrupción; último completado con fin, su fin; último activo sin interrupción o completado sin `minute_end`, `{n+1, null, false}` porque lo indica el operador; `null` en un partido terminal o con la versión no publicada, y `suspended` sí propone. Es un campo aditivo y de solo lectura: el `GET` no escribe, el servidor sigue validando número y minuto al crear y la pantalla ya no los calcula por su cuenta. La propuesta fija el número y prerrellena el minuto solo si es derivado y el operador no lo ha escrito; el origen se anuncia con `role="status"`.
- **Segmento, no periodo:** un segmento es una **ventana de tiempo** con número consecutivo, inicio, fin opcional y estado; **no** es una mitad ni un periodo reglamentario, y un partido puede tener cualquier número, incluido uno. Crear uno con otro activo cierra el activo en su minuto; interrumpir guarda el motivo y el minuto y cierra el segmento, y reanudar exige un segmento nuevo.
- **Acta cerrada:** el resultado confirmado y sus eventos son inmutables (triggers de la 016 y la 009) y no hay ruta de corrección ni de reapertura. La pantalla muestra «Acta cerrada: no se puede editar» (`role="status"`) y mantiene las acciones de escritura deshabilitadas.
- **Sin cambios de contrato interno:** `engine_version` sigue en **2026.1**, `docs/contrato-reglas.md` no cambia y el esquema pasó a **027** con el motivo del walkover (la 017 no trae migración); la 017 no añade acciones auditadas ni eventos de outbox. La cadena de esquema sigue después hasta **031** (028 de la spec 021 y 029–031 de la spec 022; runbook en «Migraciones 029, 030 y 031»).

## Disciplina y sanciones

Las sanciones se derivan **al cerrar el acta**, de los eventos de ese acta. El contrato detallado está en `AGENTS.md` → «Sanciones y disciplina (spec 018)»; aquí se describe lo que observa el administrador y el operador.

- **Una jugada, una sanción:** una expulsión por **doble amarilla** cuesta **una** sanción de suspensión, aunque una de sus amarillas alcance el límite de acumulación configurado —la primera o la última del acta, y también si en la misma acta se cruzan dos umbrales—. La sanción por acumulación de esa jugada **se absorbe** y no se emite. La duración es la configurada para la **sanción por expulsión** (`direct_red_suspension_matches` de la versión publicada), aplicada una sola vez: la acumulación absorbida no la alarga y el número de amarillas no la cambia. Las dos amarillas de la jugada **no se descuentan**: la que provoca la roja sigue contando para acumulaciones posteriores.
- **Roja directa con umbral en la misma acta:** son dos hechos distintos y se mantienen las **dos** sanciones, cada una con la duración de su motivo. La absorción solo alcanza a la doble amarilla.
- **Qué es un partido de suspensión (sin cambios):** un partido del torneo en el que el equipo del jugador compite y el jugador **no** figura en la convocatoria válida. La sanción se cumple partido a partido —un partido en el que su equipo no juega no la cumple—, el cierre rechaza una planilla con un jugador suspendido y vigente (**409**), y la sanción queda cumplida al completar los partidos de su duración. No es un periodo de tiempo ni un partido cualquiera del calendario.
- **Solo el acta que se cierra origina sanciones:** el historial disciplinario cuenta las amarillas para decidir qué evento cruza cada umbral, pero **nunca** crea, corrige ni duplica una sanción. Un evento de roja tiene como máximo **una** sanción, con cualquier motivo: si ya la tenía, no se añade otra con el motivo corregido. Cerrar después un acta del mismo jugador no reemite lo absorbido.
- **Solo hacia delante:** ninguna acta cerrada se revalida y ninguna sanción emitida cambia de motivo, duración o estado. Una sanción histórica que quedó etiquetada como roja directa se conserva tal cual, sin reescribirse ni duplicarse.
- **Lo que no cambia:** las duraciones y los umbrales configurados de la disciplina, los puntos de *fair play* de la clasificación (otra magnitud, no una suspensión), el walkover (no genera ni sirve sanciones) y los contratos HTTP —mismas rutas, mismos códigos y mismos campos de respuesta, sin endpoint ni pantalla nuevos—. `engine_version` sigue en **2026.1** y el contrato interno de reglas no cambia; la regla es fija en el motor y no añade ninguna clave de configuración.

## Walkover (W.O.)

Declarar un walkover es un **cierre del acta** con `resolution_type: "walkover"`, `winner_team_id` y `reason`; no hay ruta, permiso ni estado nuevo. El contrato detallado está en `AGENTS.md` → «Walkover (spec 016)»; aquí se describe lo que observa el operador y el cliente.

- **Cuándo se admite:** en los estados que ya admiten cierre (`scheduled`, `live`) y siempre con la **versión publicada**. `finished`, `cancelled`, `administrative_resolution` y `suspended` responden **409** `WALKOVER_STATE_NOT_ALLOWED`; un acta ya confirmada no se puede reescribir. La autorización es la misma del cierre: `CLOSE_MATCH_REPORT` **y** rol operativo (dueño, administrador u operador) **o** estar asignado en `match_officials`.
- **No exige segmento ni planilla:** un equipo puede no presentarse. La rama no valida tiempos, sustituciones, doble amarilla, marcador contra eventos ni sanciones, así que un partido **sin ningún segmento** y con un equipo **sin jugadores** se puede cerrar. Si hay un segmento activo, queda `completed` en su minuto de inicio; los completados e interrumpidos no se tocan y no se crea ninguno.
- **Motivo de catálogo:** `no_show`, `withdrawal`, `insufficient_players` o `sanction`. Es obligatorio, se guarda como **código** en `resolution_reason` (migración **027**) y no hay texto libre ni «otra»; un motivo ausente o fuera del catálogo, un walkover con eventos o sin ganador responden **422**.
- **Marcador derivado:** el servidor lo toma de `walkover_score` de la configuración efectiva (`3-0` por defecto y el override de la fase) y lo escribe igual en el reglamentario y en el final, con los penales a nulo; la operación lo publica en `limits.walkover_score`. La pareja reglamentaria y el final son opcionales y, si llegan, deben coincidir con esa pareja (**409** `WALKOVER_SCORE_MISMATCH`); un marcador de penales responde **422** porque solo aplica a `penalties`; el ganador debe participar (**409** sin `code`) y una pareja configurada con `winner <= loser` **409** `WALKOVER_CONFIG_INCONSISTENT` —las tres sin escribir nada—. Guardar o publicar reglas con `winner <= loser` en `stage_defaults` o en el override de una fase es **422**.
- **Efecto en clasificación y sanciones:** el partido queda `finished` y confirmado, cuenta como **jugado** con victoria o derrota, los puntos y los goles de la pareja en la tabla y el ganador avanza de llave. No se registran eventos, no se sirve ninguna suspensión de la plantilla y no se crea ninguna; la proyección por segmento no se reescribe. La auditoría guarda la resolución y el motivo, y se emiten los mismos tres eventos de outbox que un cierre normal (**MATCH_CLOSED**, **MATCH_UPDATED**, **STANDINGS_UPDATED**).
- **Pantalla:** con la resolución prevista `walkover` el panel pide ganador y motivo, enseña el marcador efectivo en solo lectura y no muestra ni envía los seis campos; el botón de cerrar no se deshabilita por no haber segmento activo y un aviso (`role="status"`) explica que el W.O. no necesita segmento ni planilla. Cambiar a `walkover` no se bloquea por segmentos persistidos fuera del máximo (el W.O. no los valida), pero los eventos del borrador siguen avisándose y se rechazan en la validación previa.
- **Sin cambios de contrato interno:** `engine_version` sigue en **2026.1**; `walkover_score` es configuración aditiva fuera del contrato cerrado y el motivo no se publica en ninguna proyección pública.

## Estadísticas públicas y portería imbatida

Las tablas de estadísticas se sirven sin sesión desde `GET /api/v1/tournaments/public/{id}/player-stats` (jugadores) y `GET /api/v1/tournaments/public/{id}/team-stats` (equipos), con filtros opcionales `stage_id`/`group_id` y paginación `limit`/`offset` (tope 500). **Ámbito por defecto: el torneo completo** (decisión de producto de la spec 022, RF-021). La regla es que al pedir la tabla no se envíe ningún filtro de fase ni de grupo y que ninguna fase se preseleccione por ser la primera; filtrar por fase (y por grupo dentro de ella) es una acción **explícita** del usuario, se ofrece solo cuando el torneo tiene fases, es **reversible** a «todo el torneo» y un partido cuenta en la fase a la que pertenece. **Estado real:** la pantalla aún preselecciona la primera fase al pedir las dos tablas (corrección pendiente, T15). Solo contribuyen los partidos con **resultado confirmado** de un torneo visible públicamente; un partido programado, en juego, suspendido o cancelado no contribuye nunca, y un evento anulado heredado no se cuenta. Los eventos huérfanos (jugador, equipo o segmento inexistente o de otra organización) se excluyen sin fallar la respuesta ni excluir el partido. Las fotos se firman en un solo lote después de cerrar la transacción y degradan a `null` si falla la firma.

- **Jugadores:** nombre, equipo, goles, tarjetas amarillas, tarjetas rojas y porterías imbatidas. Solo aparecen los jugadores con al menos un evento acreditado o con presencia en una alineación publicada en un partido con resultado confirmado. Un gol y un gol de penalti cuentan como gol del jugador; un autogol no. Las tarjetas incluyen las de un jugador que luego fue expulsado por doble amarilla. La asistencia no se publica y las sanciones y suspensiones no se publican. La estadística se agrega por jugador, sumando la de todos los equipos en los que estuvo inscrito (incluida retirada y reactivación en otro equipo). Un jugador retirado lógicamente aparece con su histórico completo y sin foto.
- **Equipos:** equipo (con escudo), goles a favor, goles en contra, porterías imbatidas y puntos de juego limpio. Solo aparecen los equipos con al menos un partido con resultado confirmado. Un gol a favor cuenta goles, goles de penalti y autogoles del rival; en partidos resueltos fuera del campo (walkover) se cuentan los goles derivados de `walkover_score`. Un gol en contra cuenta goles y goles de penalti del rival más los autogoles propios. Los puntos de juego limpio se suman como los calcula la clasificación.
- **Orden y posición:** jugadores por goles descendente, luego menos partidos disputados, luego apellido y luego identificador estable; equipos por goles a favor descendente, luego menos goles en contra, luego nombre y luego identificador estable. El orden es **total y estable**: dos consultas con los mismos datos devuelven el mismo orden. Las filas empatadas en **todos** los criterios visibles compartirán la misma posición, la numeración continuará después del grupo (1, 2, 2, 4) y el identificador estable solo decidirá el orden de presentación dentro del empate; esa **columna de posición no está implementada todavía** en esta ronda de corrección: ninguna de las dos respuestas incluye aún el campo `rank` y la pantalla no muestra la columna (spec 022, RF-006 y RF-022, pendientes).
- **Fotos:** solo con **inscripción vigente** en ese torneo + consentimiento de imagen + foto cargada. Si falta cualquiera de las tres condiciones se muestran las **iniciales**, sin hueco ni imagen rota; si el navegador no consigue cargar la imagen, también iniciales. Un jugador **retirado lógicamente** (`is_active` falso) **nunca** publica foto —aunque su inscripción retirada tenga consentimiento y foto cargada—: aparece con sus iniciales y solo recupera la condición de foto si se reactiva su inscripción.

### Portería imbatida — definición única (estadística derivada)

La portería imbatida se atribuye a dos unidades independientes, con definiciones separadas. Su definición y su umbral de **60 minutos** son un **criterio fijo de una estadística derivada**, no configurable por torneo ni por versión (dos torneos deben ser comparables), pero **no son una regla de juego**: no se evalúan en el motor de reglas ni en el cierre del acta, no alteran resultados, marcadores, clasificación, actas, sanciones, suspensiones ni el avance de fases, y se calculan **solo al leer**. Por eso `engine_version` sigue en **2026.1**, el contrato interno de reglas (`docs/contrato-reglas.md`) no cambia y **no se declara ninguna excepción a la constitución** (la excepción acotada a §3.2 que se llegó a mencionar **se retiró**: el criterio no contradice ninguna regla de la constitución).

- **Del equipo:** el partido tiene resultado confirmado; la resolución es reglamentaria, prórroga o penales (partido disputado); el equipo no recibió ningún gol (gol, gol de penalti y autogol del rival, incluidos los de prórroga; la tanda de penales no cuenta); sin condición de duración mínima. Los partidos resueltos fuera del campo (walkover o administrativa) no cuentan. Como máximo una por equipo y partido.
- **Del portero:** el equipo tiene portería imbatida; el portero es **identificable** porque ocupa `GK` en una **formación táctica publicada** del equipo en el partido —**nunca se infiere un portero**—; fue **titular**: el portero inicial es el `GK` de la formación publicada del **primer segmento** y un portero **entrante** lo es si figura como `GK` en una formación publicada **posterior**, acreditado por la sustitución registrada en el acta; y jugó al menos 60 minutos (para un titular no sustituido, la duración efectiva del partido; para un sustituido, desde el inicio hasta el minuto de la sustitución; para un expulsado, desde el inicio hasta el minuto de la expulsión). Sin formación táctica publicada no se atribuye a ningún portero y la del equipo se conserva. Como máximo una por portero y partido.

La fuente de la formación es, por tanto, **todas las formaciones tácticas publicadas** del partido —no solo la última por equipo—: la del **primer segmento** para identificar al portero titular y **cualquier formación publicada posterior** para el entrante. Un suplente que nunca figura como `GK` en una formación publicada no es portero identificable. Walkover y resolución administrativa no cuentan para portero ni para portería imbatida del equipo, aunque sí para las demás estadísticas de equipo (goles derivados incluidos). El motivo de walkover o de resolución administrativa nunca se publica.

### Casos límite de la portería imbatida

| # | Caso | Equipo | Portero |
|---|---|---|---|
| 1 | Partido disputado, 0 recibidos, formación publicada y portero titular con ≥ 60 min | Sí | Sí |
| 2 | Partido disputado, 0 recibidos, portero sustituido a los 50 min | Sí | No (menos de 60 min) |
| 3 | Partido disputado, 0 recibidos, portero expulsado a los 70 min | Sí | Sí (70 ≥ 60 min; la expulsión no reduce los minutos ya jugados) |
| 4 | Partido disputado, el equipo recibió un gol y luego empató (1-1) | No | No |
| 5 | Partido disputado, autogol de un jugador propio | No | No |
| 6 | Partido disputado con goles solo en prórroga | Se evalúa con el marcador final (prórroga incluida) | Se evalúa con el marcador final (prórroga incluida) |
| 7 | Partido con tanda de penales (marcador final empatado en juego) | Sí si no recibió gol en juego | Sí si cumple el resto |
| 8 | Walkover (sin eventos, segmentos ni planilla) | No | No (sin portero identificable) |
| 9 | Resolución administrativa | No | No |
| 10 | Partido suspendido o cancelado | No contribuye (no es resultado confirmado) | No contribuye |
| 11 | Partido terminado con menos minutos que el reglamentario pero con acta confirmada | Sí si no recibió gol | Sí si el portero jugó ≥ 60 min |
| 12 | Equipo sin formación táctica publicada (solo planilla) | Sí si no recibió gol | No (sin portero identificable) |
| 13 | Equipo con formación táctica sin publicar | Sí si no recibió gol | No (sin portero identificable) |
| 14 | Dos porteros en el mismo partido (sustitución del portero) | Sí si no recibió gol | Se atribuye a cada uno que cumpla los criterios |
| 15 | Portero que marca un gol (no autogol) | Sí si no recibió gol | Sí si cumple el resto |
| 15b | Portero que marca un autogol | No (el autogol es gol recibido) | No |
| 16 | Portero expulsado y reemplazado por un jugador de campo | Sí si no recibió gol | Solo si el portero titular cumplió los criterios antes de la expulsión |
| 16b | Portero sustituto que figura como `GK` en una formación publicada posterior | Sí si no recibió gol | Sí si cumple los criterios |
| 16c | Portero sustituto que no figura como `GK` en ninguna formación publicada | Sí si no recibió gol | No (no es portero identificable) |
| 17 | Partido con dos inscripciones del mismo jugador en equipos distintos | Se atribuye por equipo y partido | Se agrega por jugador (suma de ambos equipos) |
| 18 | Jugador retirado lógicamente | Su histórico no cambia | Su histórico no cambia |
| 19 | Acta confirmada antes de la existencia de la asistencia o con identificadores de texto libre | Se lee sin error ni cifra inventada | Se lee sin error ni cifra inventada |

La regla vigente se muestra en la interfaz junto a toda cifra que la use, en español e inglés. Un torneo no visible responde el mismo `404` indistinguible. La lista de campos públicos es cerrada: `backend/tests/test_public_field_allowlist.py` comprueba los modelos públicos de las lecturas de la spec 020 y `backend/tests/test_public_stats_endpoints.py` comprueba, con datos reales, la lista cerrada y el aislamiento de las dos rutas de estadísticas; `backend/tests/test_public_access_matrix.py` cubre hoy solo las cuatro lecturas anteriores (listado, detalle, clasificación y partidos) y **no** las de estadísticas.

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
cd frontend && pnpm exec playwright install --with-deps chromium   # una vez por máquina (solo local)
cd frontend && pnpm run e2e        # arranca la pila, siembra, ejecuta y baja
cd frontend && pnpm run e2e:test   # solo el escenario, con la pila ya levantada y sembrada
```

`pnpm run e2e` requiere Docker, `cp .env.example .env` y Chromium instalado; arranca con `docker compose up -d --build --wait --wait-timeout 300` (≤5 min, informado aparte), ejecuta el seed demo, corre el escenario y baja la pila que arrancó. `pnpm run e2e:test` es el comando del job de integración continua, pero allí el escenario no corre en el runner sino **dentro del contenedor oficial `mcr.microsoft.com/playwright:v1.64.1-noble`**, que ya trae Chromium y sus dependencias de sistema: se ejecuta con `--network host` para alcanzar `web` y `api` publicados y con el repositorio montado, de modo que el job no instala navegadores ni paquetes del sistema (sin `apt` ni `--with-deps`) ni cachea `~/.cache/ms-playwright`; `pnpm run typecheck:e2e` sigue ejecutándose en el runner. Códigos de salida: **0** verde (las tres vistas sin omisiones), **1** fallo de comportamiento, **2** fallo de infraestructura (pila, datos demo o navegador) y **3** corrida inválida (vista omitida/ausente o escenario no concluyente); la invalidez no acusa al producto pero no abre el gate.

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
