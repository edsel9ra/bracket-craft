# Plan 008 — Higiene del bloque P2 (R18-R32)

Spec: `specs/008-higiene-p2-auditoria/spec.md` (aprobada 2026-10-21).
Estado del plan: aprobado e implementado; el trabajo se dividió en tres archivos de tareas (`tasks-a.md`, `tasks-b.md` y `tasks-c.md`, 22 tareas en total) y las 22 están completadas.

## Objetivo y alcance técnico

Cerrar R18-R32 con cambios pequeños y localizados en infraestructura, backend, base de datos, frontend y documentación. Dos migraciones **aditivas** nuevas, sin editar ninguna aplicada:

- **022** — topes estructurales de minuto y minuto añadido en `match_events` (R27).
- **023** — persistencia de las vueltas de fase (`stages.schedule_legs`) para que el límite de enfrentamientos manuales sea verificable (R26).

No se toca el modelo de autorización, las reglas deportivas, el outbox ni las proyecciones públicas. R11 queda fuera.

## Decisiones de plan (con alternativa descartada)

1. **Orden de migraciones: 022 y luego 023.** Ambas aditivas; 022 puede aplicarse con el código actual y 023 debe existir antes del backend que la lee. *Descartado:* una sola migración mixta, que mezcla dominios y complica el *forward-fix*.
2. **Vueltas persistidas como columna `stages.schedule_legs`** (`SMALLINT NOT NULL DEFAULT 1`, `CHECK (1,2)`), escrita por el sorteo de liga y copiada al clonar versiones. *Descartado:* inferir las vueltas contando partidos, que se contamina con las altas manuales.
3. **Límite de enfrentamientos en una función pura** `max_meetings_per_pair(stage_type, schedule_legs)` y conteo en la misma transacción del alta manual, ya serializada por `lock_stage_and_version`. *Descartado:* un índice único, que impediría la ida y vuelta y las repeticiones legítimas de eliminatorias.
4. **Vencimiento de invitaciones calculado en lectura** con `effective_invitation_status(stored, expires_at, now)`; la materialización ocurre solo en crear y reenviar; revocar evalúa el estado efectivo sin escribirlo. *Descartado:* un trabajo periódico, que añade una pieza operativa para un dato derivable.
5. **CSRF partido en dos comprobaciones**: origen para toda escritura, token solo con credenciales o en rutas de identidad. `Origin` y `Referer` se comprueban por separado: sin ninguno se admite y un `Referer` presente no permitido rechaza aunque `Origin` lo esté. *Descartado:* exigir token en escrituras públicas, que rompe a clientes sin sesión.
6. **Lectura de operación sin bloqueo**: `_load_operation_match` recibe `lock=False` en el `GET` y conserva `FOR UPDATE OF m` en las rutas de escritura. *Descartado:* mantener el bloqueo «por coherencia», que serializa lecturas con cierres.
7. **Auditoría por tránsito de estado**, comparando firma de planilla y publicación antes/después; sin entrada si no hay cambio efectivo. *Descartado:* registrar toda petición, que infla la auditoría con repeticiones.
8. **Versión del producto en `backend/pyproject.toml` (`[project].version`)** leída con `tomllib` al arrancar; `engine_version` y la versión del motor quedan aparte. *Descartado:* un literal en `main.py` o una variable de entorno, que duplican la fuente.
9. **Orden estable de organizaciones en la capa de aplicación** (`sorted` por nombre y luego id), sin reemplazar la función SQL. *Descartado:* reescribir `list_user_organizations`, que exigiría otra migración por un cambio de presentación.
10. **Web no-root solo en producción**: la imagen declara `USER node`, el compose de desarrollo fija `user: "0:0"` con la excepción documentada y el overlay de producción fija `user: "node"`. *Descartado:* no-root en desarrollo con el árbol montado, que rompe la caché del servidor y la propiedad en Windows/WSL.
11. **Configuración verificada por contrato**: `infra/scripts/check_env_contract.py` compara el JSON renderizado de Compose con un mapa servicio→variables y con `.env.example`, con lista de excepciones. *Descartado:* revisión manual, que vuelve a derivar.
12. **Salud con semánticas separadas**: API `/health/ready` (BD+Redis), web HTTP propio, worker frescura de un latido de fichero. *Descartado:* salud de web dependiente de la BD, que mezcla responsabilidades.
13. **Dependencias de prueba en `backend/requirements-dev.txt`**; la imagen instala solo `requirements.txt`, CI instala ambos y `pip-audit` audita ambos. *Descartado:* mantener pytest en producción y documentarlo.

## Archivos y responsabilidades

### Infraestructura y configuración

- `frontend/Dockerfile` — `USER node` en la etapa de ejecución; `.output` legible por ese usuario (R19).
- `docker-compose.yml` — `web.user: "0:0"` con comentario de excepción de desarrollo; `api` publica `127.0.0.1:8000:8000`; healthchecks de `api`, `web` y `worker`; `web.depends_on.api.condition: service_healthy`; variables de `api` sincronizadas (R19, R20, R30, R31).
- `docker-compose.production.yml` — `web.user: "node"`; healthchecks heredados; sin puertos (R19, R31).
- `.env.example` — documenta `AUTH_LOGIN_RATE_LIMIT` y `AUTH_REGISTER_RATE_LIMIT`; comentarios sin la marca anterior; valores de almacenamiento etiquetados como solo desarrollo (R20, R32g).
- `infra/scripts/check_env_contract.py` — nuevo; contrato variable→servicio con excepciones (R20).
- `infra/scripts/assert_production_compose.py` — exige healthchecks y usuario no-root en producción; gana un modo de comprobación de desarrollo (puerto de API en loopback, healthchecks, publicación del web intacta) (R19, R30, R31).
- `.github/workflows/ci.yml` — instala `requirements-dev.txt`; audita ambos archivos; ejecuta el contrato de entorno y las nuevas aserciones de compose (R20, R28, R30, R31).
- `backend/requirements-dev.txt` — nuevo, con `pytest` y `pytest-asyncio` (R28).

### Backend

- `backend/app/main.py` — origen en toda escritura y token condicional (R21); cuerpo incompleto no procesado (R32h); versión leída de los metadatos (R32d).
- `backend/app/core/csrf.py` — separa `validate_request_origin` y `validate_csrf_token`; conserva `validate_csrf_request` como composición para no romper llamadas existentes (R21).
- `backend/app/core/roles.py` — nuevo; precedencia declarada y fragmento SQL reutilizable (R32b).
- `backend/app/core/config.py` — mensajes de credenciales de desarrollo sin la marca anterior (R32g).
- `backend/app/modules/invitations/lifecycle.py` — nuevo; `effective_invitation_status` (R22).
- `backend/app/modules/invitations/router.py` — listado sin escritura, creación que materializa la vencida, revocación con estado efectivo, reenvío, rol por precedencia, respuesta de aceptación sin token (R22, R32a, R32b).
- `backend/app/modules/invitations/schemas.py` — quita `access_token`/`token_type` de la respuesta de aceptación (R32a).
- `backend/app/modules/organizations/router.py` — orden estable de organizaciones (R32c).
- `backend/app/modules/identity/router.py` — organización inicial determinista (nombre e id) (R32c).
- `backend/app/modules/matches/router.py` — lectura de operación sin bloqueo (R23); auditoría de planilla, publicación y oficiales (R25).
- `backend/app/modules/tournaments/pairings.py` — nuevo; `max_meetings_per_pair` y conteo previo al alta manual (R26).
- `backend/app/modules/tournaments/router.py` — lee `schedule_legs` en `_load_draft_stage_context`; escribe las vueltas en `_draw_non_swiss_schedule`; copia la columna en el clonado de versiones; guarda de duplicados en `create_match` (R26).
- `backend/app/workers/outbox.py` — latido del bucle y helper puro de frescura (R31).
- `backend/pyproject.toml` — `[project]` con nombre y versión (R32d).

### Frontend

- `frontend/app/composables/useRealtime.ts` — método `retry()` que cierra el socket y reconecta conservando el alcance (R18).
- `frontend/app/pages/tournaments/[id].vue`, `frontend/app/pages/workspace/index.vue`, `frontend/app/pages/workspace/matches/[id].vue` — el botón «Reintentar» llama a `retry()` (R18).
- `frontend/app/utils/realtimeRetry.ts` — nuevo; decisión pura de reconexión forzada (R18).
- `frontend/app/utils/organizationSelection.ts` — nuevo; `selectActiveOrganization` (R32c).
- `frontend/app/utils/labels.ts` — nuevo; claves de traducción de roles y estados (R29).
- `frontend/app/pages/workspace/members.vue` — roles, estados y etiqueta accesible traducidos; sin códigos crudos (R29).
- `frontend/app/pages/invitations/[token].vue` — rol traducido; aceptación sin token en el cuerpo (R29, R32a).
- `frontend/app/composables/useI18n.ts` — claves nuevas en español e inglés (R29).
- `frontend/app/stores/auth.ts` — restaura la organización recordada solo si está en la lista; no sobrescribe con la primera (R32c); tipo de sesión sin `access_token` (R32a).
- `frontend/app/components/public/PublicBracket.vue` — retira el marcado comentado (R32i).

### Base de datos

- `infra/postgres/migrations/022_match_event_minute_bounds.sql` — nuevo (R27).
- `infra/postgres/migrations/023_stage_schedule_legs.sql` — nuevo (R26).
- `infra/postgres/init/01_schema.sql` — **no se edita**; la cadena limpia sigue siendo `init/00-03` → 001-023.

### Documentación

- `README.md` — runbook de 022/023, ciclo de vida de invitaciones, contrato de configuración, healthchecks, excepción de desarrollo del web, versión del producto, alcance del relay y de la proyección interna (R19-R32).
- `AGENTS.md` — comandos con `requirements-dev.txt`, `pip-audit` de ambos archivos, healthchecks, puerto de API en loopback, contrato de entorno, fuente de versión y nota de la migración 013 (R20, R24, R28, R30, R31, R32d).

## Funciones puras

| Función | Ubicación | Regla |
|---|---|---|
| `effective_invitation_status(stored_status, expires_at, now)` | `backend/app/modules/invitations/lifecycle.py` | Recibe `now`; no lee el reloj. |
| `max_meetings_per_pair(stage_type, schedule_legs)` | `backend/app/modules/tournaments/pairings.py` | 1 por defecto; 2 solo en liga/grupos con dos vueltas; eliminatorias fuera. |
| `role_precedence_index(code)` y `ROLE_PRECEDENCE_SQL` | `backend/app/core/roles.py` | Orden dueño→observador; el SQL se compone, no se duplica. |
| `request_origin(headers)` / `referer_origin(headers)` / `is_allowed_origin(origin, allowed)` | `backend/app/core/csrf.py` | `Origin` y `Referer` se comprueban por separado; sin ambos, admitido; si cualquiera está presente y no está permitido, rechaza. |
| `heartbeat_is_fresh(mtime_epoch, now_epoch, max_age)` | `backend/app/workers/outbox.py` | Recibe `now`; usado por el healthcheck y por pruebas. |
| `selectActiveOrganization(organizations, remembered)` | `frontend/app/utils/organizationSelection.ts` | Devuelve la recordada si está en la lista; si no, la primera estable. |
| `roleLabelKey(code)` / `invitationStatusLabelKey(status)` | `frontend/app/utils/labels.ts` | Claves i18n; valor desconocido se muestra tal cual. |
| `shouldForceReconnect(status, hasSocket)` | `frontend/app/utils/realtimeRetry.ts` | Solo en estado de error; el reintento destruye el socket. |

## Interfaz

### Endpoints y contratos que cambian

- `POST /api/v1/invitations/{token}/accept` — la respuesta deja de incluir `access_token` y `token_type`; la sesión sigue en la cookie. Ruptura documentada (RF-015).
- `GET /api/v1/organizations/invitations` — mismo esquema; el `status` devuelto es el efectivo y la petición no escribe (RF-005).
- `POST /api/v1/organizations/invitations` — 201 al reemplazar una pendiente vencida (materializa la anterior); 409 si la pendiente sigue vigente (RF-005).
- `DELETE /api/v1/organizations/invitations/{id}` — 204 si estaba pendiente y vigente; 409 si está vencida, revocada o aceptada (RF-005).
- `GET /api/v1/organizations/members` y respuestas de rol — `role_code` por precedencia declarada, no alfabética (RF-016).
- `POST /api/v1/auth/login` y `GET /api/v1/organizations` — organización inicial y lista en orden estable; el cliente restaura la recordada (RF-017).
- `POST /api/v1/tournaments/{id}/matches` — nuevo 409 por exceder el máximo de enfrentamientos del par en la fase y grupo (RF-009).
- `GET /api/v1/matches/{id}/operation` — mismo cuerpo; sin bloqueo de fila (RF-006).
- `GET /docs` — la versión mostrada es la declarada en los metadatos (RF-018).
- Sin endpoints nuevos. La auditoría de R25 se escribe en las rutas existentes.

### Pantallas afectadas

- Torneo público, Workspace y operación de partido: botón «Reintentar» funcional (RF-001).
- Directorio de miembros e invitación por enlace: roles y estados traducidos (RF-012).
- Aceptación de invitación: flujo sin token en el cuerpo (RF-015).
- Workspace: restauración de la organización activa (RF-017).

## Base de datos

### Migración 022 — topes de minuto

- Tabla: `public.match_events`. Añade `chk_match_event_minute_range` (`minute BETWEEN 0 AND 180`) y `chk_match_event_added_minute_range` (`added_minute BETWEEN 0 AND 30`).
- Pre-chequeo en la misma transacción: cuenta filas fuera de rango y aborta con `RAISE EXCEPTION` nombrando ambos conteos; no corrige datos.
- Aditiva: solo `ALTER TABLE ... ADD CONSTRAINT`; no elimina ni reescribe. No crea tablas tenant, así que no hay RLS nueva; la política existente sigue aplicando.
- Se verifica en volumen limpio (`init/00-03` → 001-023) y en base migrada; ambos terminan con las dos restricciones. `VALIDATE` implícito al añadir sobre datos ya comprobados.

### Migración 023 — vueltas de fase

- Tabla: `public.stages`. Añade `schedule_legs SMALLINT NOT NULL DEFAULT 1` con `CHECK (schedule_legs IN (1,2))`.
- Aditiva y con default: las filas existentes quedan en una vuelta. No se hace *backfill*: una liga histórica de dos vueltas mantiene el límite de una hasta regenerarse, y las versiones publicadas no admiten altas manuales.
- Los triggers de estructura existentes ya impiden modificar `stages` en versiones publicadas; no se añaden triggers.
- RLS: `stages` ya es tenant-owned; la columna hereda la política y el `GRANT` de tabla.
- Se verifica en limpio y migrado; el clonado de versiones copia el valor y el sorteo lo escribe en borradores.

### Orden de despliegue

1. Aplicar **022** (compatible con el código actual; el código ya limita a 180/30).
2. Aplicar **023** antes de desplegar el backend que lee `schedule_legs`.
3. Desplegar backend y después frontend de la misma versión (cambios de contrato de RF-015/RF-016/RF-017).
4. Sin rollback: cualquier defecto se corrige con una migración nueva (*forward-fix*) o con código compatible.

## Configuración y secretos

- **Variables recuperadas para `api`** (hoy documentadas sin efecto): `JWT_ALGORITHM`, `GOOGLE_AUDIENCE`, `CSRF_COOKIE_NAME`, `CSRF_TOKEN_TTL_SECONDS`, `MAX_REQUEST_BODY_BYTES`, `STORAGE_SIGNING_ENDPOINT_URL`, `STORAGE_PRESIGN_SECONDS`.
- **Variables documentadas nuevas en `.env.example`**: `AUTH_LOGIN_RATE_LIMIT`, `AUTH_REGISTER_RATE_LIMIT`, con los mismos defaults de desarrollo que ya usa la composición.
- **Excepciones del contrato** (no inyectadas a la API): credenciales y parámetros de PostgreSQL, `MIGRATION_TARGET`, `PLATFORM_ADMIN_EMAIL`, `DATABASE_ADMIN_URL`, variables del servicio web (`NUXT_*`, `CI`) y valores de pruebas o entornos locales.
- No se añaden secretos ni defaults fuera de `.env.example`; producción sigue exigiendo los valores con `:?` y el backend sigue rechazando los de desarrollo.

## Exposición pública

Ninguna proyección pública cambia: no se añaden documentos, fechas de nacimiento ni edad. `v_public_tournament_players` sigue calculando la edad para el rol de aplicación y **no se consume desde ningún endpoint**; se documenta como proyección interna y una prueba verifica que las respuestas públicas de jugadores y alineaciones no incluyen edad, documento ni fecha de nacimiento (RF-019, RNF-003). El token de sesión deja de viajar en el cuerpo de una respuesta (RF-015).

## Eventos asíncronos

Sin cambios en el outbox, el stream ni los eventos de dominio. El worker solo publica un latido de fichero para su healthcheck, que no se escribe en el stream ni en la base de datos (RF-014).

## Estrategia de pruebas

### Backend

- Unitarias nuevas o ampliadas: `tests/test_hardening.py` (origen sin credenciales, `Referer` no permitido, sin origen), `tests/test_invitations.py` (estado efectivo, crear sobre vencida, revocar 409, reenviar, sin escritura en `GET`), `tests/test_roles.py` o ampliación de `test_api_access.py` (precedencia), `tests/test_match_operation_audit.py` (tres acciones, idempotencia, fallo sin entrada), `tests/test_pairings_limit.py` (límite por formato), `tests/test_version_source.py` (versión única), `tests/test_organizations_order.py` (orden estable y restauración), `tests/test_body_buffer.py` (cuerpo abortado).
- Opt-in con PostgreSQL y rol de aplicación (`RUN_DATABASE_TESTS=1`, `DATABASE_ADMIN_URL`): `tests/test_migration_022.py` (rechaza 181/31, acepta 180/30, pre-chequeo falla con datos fuera de rango), `tests/test_migration_023.py` (columna, CHECK, clonado, escritura en sorteo), `tests/test_invitations.py` (unicidad de pendientes y materialización), `tests/test_match_operation_audit.py` (filas de auditoría y RLS), `tests/test_migration_013_hardening.py` (las cinco funciones y la vista con el estado esperado).
- Comandos: `cd backend && pytest -q`; `cd backend && python -m compileall -q app`; opt-in:
  `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_022.py tests/test_migration_023.py tests/test_migration_013_hardening.py`.

### Frontend

- Unitarias de utilidades puras: `tests/realtime-retry.test.ts`, `tests/organization-selection.test.ts`, `tests/labels.test.ts`, y paridad de catálogos en el test existente de i18n.
- Comandos: `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck`, `cd frontend && pnpm run build`.

### Infraestructura y seguridad

- `sh -n infra/postgres/migrate.sh`.
- `docker compose config -q` para desarrollo y el merge `-f docker-compose.yml -f docker-compose.production.yml config -q` con variables dummy.
- `docker compose config --format json | python3 infra/scripts/check_env_contract.py -`.
- Aserciones de compose (dev y producción) y `infra/scripts/assert_production_compose.py` con la versión de Compose.
- `pip-audit -r backend/requirements.txt -r backend/requirements-dev.txt`; auditoría del frontend con `infra/scripts/audit_frontend.py`; escaneo Trivy según `AGENTS.md`.

### Verificación en este entorno

- El daemon de Docker y Trivy estuvieron disponibles durante la implementación y se usaron: `docker compose config` de desarrollo y del merge de producción, arranque de contenedores y healthchecks, comprobación de usuario no-root en ejecución y escaneo de Trivy.
- `pnpm run build` puede fallar por memoria en local; se declara si no se ejecuta.

## Riesgos de implementación

- **Web no-root y desarrollo:** si el overlay no fija `user: "node"`, producción heredaría el `0:0` de desarrollo. Mitigación: aserción en CI y prueba de la configuración renderizada.
- **Latido del worker:** un falso negativo al arrancar marcaría el worker insano. Mitigación: `start_period` y latido desde la primera iteración.
- **Materialización del vencimiento:** dos creaciones simultáneas pueden competir; el índice único resuelve y la segunda recibe 409. La transacción no deja dos pendientes.
- **`schedule_legs` en datos históricos:** las ligas de dos vueltas ya generadas quedan con límite uno hasta regenerarse; se documenta como limitación (no hay *backfill* fiable).
- **Alta manual concurrente:** el bloqueo fase→versión serializa el conteo y la inserción; no se añade índice único.
- **Origen en escrituras:** proxies que eliminen `Origin`/`Referer` seguirían admitidos (comportamiento actual); los que envíen un origen no configurado serán rechazados. Se documenta en el README.
- **Retirada del token del cuerpo:** rompe consumidores externos que usaban el bearer; se documenta la alternativa de cookie.
- **Versión leída de `pyproject.toml`:** si el archivo no se copia en la imagen, el arranque falla; se añade prueba y se verifica en el Dockerfile.
- **Dependencias divididas:** CI y documentación deben instalar las de desarrollo; si no, la suite falla por importación.
- **Migración 022 con tabla grande:** el `CHECK` valida las filas existentes; el pre-chequeo ya las recorre. Ejecutar en ventana de baja actividad.

## Qué RF cubre cada parte

| Parte | RF | Dónde |
|---|---|---|
| Infra/config | RF-002, RF-003, RF-011, RF-013, RF-014 | Dockerfiles, Compose dev/prod, `.env.example`, scripts de CI |
| Backend/datos | RF-004 a RF-010, RF-015 a RF-022 | `main.py`, `core/`, `invitations/`, `matches/`, `tournaments/`, `identity/`, `workers/`, migraciones 022/023 |
| Frontend | RF-001, RF-012, RF-017 (cliente), RF-015 (cliente), RF-023 | `useRealtime.ts`, páginas, `stores/auth.ts`, i18n, `PublicBracket.vue` |
| Documentación | RF-007, RF-019, RF-020, RF-021 | README, AGENTS |

## Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant | Sí | Toda consulta nueva (conteo de enfrentamientos, auditoría, invitaciones) usa contexto de organización; las migraciones no crean tablas tenant. |
| §2.2 Sin `BYPASSRLS` | Sí | No se cambia el rol; las pruebas opt-in usan el rol de aplicación. |
| §2.3 Lo publicado es inmutable | Sí | `schedule_legs` no se reescribe en publicadas (triggers existentes); no se tocan resultados. |
| §2.4 Historial append-only | Sí | Solo 022 y 023, aditivas; 013 no se edita. |
| §2.5 Proyección pública mínima | Sí | Sin campos nuevos; edad no expuesta; token fuera del cuerpo. |
| §2.6 Sin secretos por defecto | Sí | Sin secretos nuevos; defaults solo en `.env.example`; producción los rechaza. |
| §2.7 Admin global separada y auditada | Sí | No se añaden acciones; la comprobación de 013 protege las funciones de plataforma. |
| §2.8 Nada sin verificación | Sí | Comandos por área y declaración de lo no ejecutable (Docker/Trivy). |
| §2.9 Código de desarrollo fuera de producción | Sí | La imagen de producción no monta código ni instala herramientas de prueba. |
| §3.1 RLS y migraciones | Sí | Contexto por transacción; checksums y pruebas en limpio y migrado. |
| §3.2 Backend y reglas en JSON | Sí | Sin cambios de reglas deportivas; los minutos siguen saliendo de la configuración. |
| §3.3 Frontend y `useApi.ts` | Sí | Las llamadas siguen el cliente centralizado; cambios de cliente acotados. |
| §3.4 Seguridad y configuración | Sí | Origen en escrituras, token fuera del cuerpo, auditoría sin PII y secretos sin cambios. |
| §3.5 Infraestructura y CI | Sí | Compose ≥2.24.4, merge validado, auditorías y Trivy según CI. |
| §4 criterios de cambio | Sí | `pytest`, `compileall`, `pnpm test/typecheck/build`, `compose config`, `pip-audit` y docs. |
| §5.1 Excepciones | Sí | Excepción de web no-root solo en desarrollo, documentada con motivo y retiro. |
| §6 Cumplimiento | Sí | Revisión humana distinta del autor y CI en verde. |

## División propuesta (obligatoria antes de escribir `tasks.md`)

El trabajo suma **22 tareas** de 20-30 minutos; supera el máximo de 10. Se propone dividir la implementación en tres entregas bajo la misma spec aprobada, cada una con su propio archivo de tareas en esta carpeta (`tasks-a.md`, `tasks-b.md`, `tasks-c.md`) para no duplicar requisitos:

**008A — Infraestructura y configuración (7 tareas):** R19, R20, R28, R30, R31 y su documentación.

**008B — Backend y datos (10 tareas):** R21-R27, R32a-h y su documentación.

**008C — Frontend (5 tareas):** R18, R29, R32a (cliente), R32c (cliente) y R32i.

Cada parte se aprueba y se valida por separado; el orden recomendado es 008A (sin dependencias de datos) → 008B (migraciones y API) → 008C (cliente de los contratos nuevos). La spec 008 no se divide: sigue siendo la fuente única de requisitos. *Alternativa descartada:* renumerar en specs 009/010/011, que duplicaría los requisitos y rompería la trazabilidad y la tabla de constitución ya aprobadas.
