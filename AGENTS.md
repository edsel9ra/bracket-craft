# Guía para Agentes: Bracket Craft

Plataforma multi-tenant para crear y operar torneos de fútbol con reglas configurables, fases componibles y resultados en tiempo real.

## Fuentes de Verdad

Ante cualquier duda, consulta en este orden:

1. `docs/constitution.md`: principios innegociables, reglas de implementación y criterios obligatorios. Tiene precedencia sobre cualquier otro documento.
2. `README.md`: alcance del producto, flujo local, datos demo, seguridad y modelo de acceso público/privado.
3. `docs/contrato-reglas.md`: contrato interno de reglas (`engine_version` 2026.1): códigos `GF1`/`GF2` y catálogo de formaciones. No es configurable.
4. `specs/NNN-nombre/` (`spec.md`, `plan.md`, `tasks.md`): requisitos, diseño y tareas de cada funcionalidad desarrollada con SDD.
5. `MEMORY.md`: estado y decisiones del trabajo SDD en curso.
6. `docker-compose.yml` y `docker-compose.production.yml`: servicios, puertos, variables y diferencias entre desarrollo y producción.
7. `.env.example`: variables de entorno y defaults **solo de desarrollo**.
8. `infra/postgres/migrations/`: fuente de verdad del esquema de base de datos (migraciones numeradas).
9. `backend/app/main.py`: registro de routers y punto de entrada de la API.
10. `backend/app/modules/`: límites de cada funcionalidad del backend.
11. `frontend/app/composables/useApi.ts`: contrato de llamadas HTTP del frontend.
12. `.github/workflows/ci.yml`: lista autoritativa de verificaciones (cinco jobs con permisos `contents: read`: `backend`, `frontend`, `infrastructure` y `security` en cada `push` y `pull_request`, y `e2e` en cada `pull_request` y solo en `push` a `main`).
13. Documentación interactiva de la API en `http://localhost:8000/docs`.

Si este archivo contradice a la constitución, gana la constitución. Si contradice al código o a la CI, gana el código/CI. Actualiza este archivo en el mismo cambio.

## Stack

- **Backend:** FastAPI, SQLAlchemy asíncrono y PostgreSQL (Python 3.14 en CI).
- **Frontend:** Nuxt 4, Vue 3 y Pinia (Node 24 y pnpm 12.12.1 en CI). Layout Nuxt 4: el código de app vive en `frontend/app/`.
- **Procesamiento:** Redis y worker asíncrono de outbox.
- **Tiempo real:** Socket.IO. El estado visible de la conexión sale de una sola fuente (`status`): `connected`, `reconnecting`, `error` y el estado **manual** `retrying` («Reintentando…»/«Retrying…»), que solo activa la pulsación de «Reintentar» cuando inicia un intento nuevo; `idle` y `connecting` no muestran etiqueta.
- **Almacenamiento de archivos:** SeaweedFS con API S3 (fotos de jugadores). Antes: MinIO (repositorio archivado el 2026-04-25).
- **Infraestructura:** Docker Compose.

## Límites del Proyecto

- No existe gestor de paquetes en la raíz. Ejecuta comandos Python desde `backend/` y comandos pnpm desde `frontend/`.
- Las rutas `/` y `/tournaments/{id}` son **públicas**. El Workspace (`/workspace`) requiere sesión y una organización activa validada.
- La administración global vive en `/admin`, separada del Workspace. Requiere un registro en `platform_admins` y no puede editar resultados ni versiones publicadas.
- `scripts.seed_demo` es solo para desarrollo/local: no es una migración ni un comando de producción.
- `scripts.outbox_probe` es una **utilidad de verificación operativa**, no un seed ni un comando de producción: inserta, consulta y borra un evento de outbox inocuo (`VERIFICATION_OUTBOX_PROBE`) con el rol de aplicación y `set_rls_context`, lo orquesta `infra/scripts/verify_worker_loop_health.sh` dentro del contenedor del worker y **solo** se ejecuta en desarrollo/local (`APP_ENV` `development`, `dev` o `local`); fuera de ese entorno sale **2** sin escribir nada y no hay opción para forzarla.
- `scripts.encrypt_birth_dates` es un comando operativo de despliegue, no un seed: requiere `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY` y se ejecuta como servicio one-off entre las migraciones 017 y 018.
- La fecha de nacimiento de los jugadores se almacena solo cifrada (`players.birth_date_encrypted`) y es *write-only* para el rol de aplicación; la edad y el año de referencia son los datos derivados legibles.
- Las proyecciones públicas **nunca** exponen documentos de identidad ni fechas de nacimiento. `photo_url` solo se devuelve si el roster tiene consentimiento de imagen.
- `v_public_tournament_players` es una **proyección interna**: ningún endpoint la consume y no se retira; calcula `public_age` solo para el rol de aplicación y filtra por actividad, así que **deja de listar** al jugador retirado mientras esté inactivo (012, RC-1). «Público» significa respuesta de la API y el contrato público de jugadores (edad, documento y fecha de nacimiento excluidos) se verifica en `backend/tests/test_public_player_views.py`. Consumirla o retirarla exige una spec propia.
- **Invitación vencida:** leer y previsualizar calculan `expired` sin escribir; crear sobre una vencida responde **201** y materializa la anterior, crear sobre una vigente **409**, crear con solo una revocada del mismo correo **201** (la unicidad solo cubre pendientes), revocar una vencida **409** sin reescribirla, reenviar la vencida la reutiliza con token y fecha nuevos, reenviar una **revocada** da **409** `INVITATION_REVOKED_RESEND` (C-1), reabrir una revocada da **200** con token y fecha nuevos sobre la misma fila (el enlace anterior deja de resolver) y aceptarla da **410**. La reapertura es la **tercera ruta de materialización** (C-2): si el mismo correo tiene otra pendiente ya vencida, se materializa y después se reabre, en una transacción; una pendiente **vigente** del mismo correo bloquea con **409** sin materializarse. Se mantiene la unicidad de pendientes por organización y correo.
- **Miembro sin rol (403):** la autorización se resuelve antes del handler. Un miembro **activo** de la organización **sin ninguna fila de rol** recibe **403** `{"detail": "Membresía o rol activo no válido"}` en `GET /organizations/current/access`, `GET /organizations/members`, `PATCH …/members/{id}/role`, `PATCH …/members/{id}/status`, `POST /organizations/invitations`, `POST …/{id}/resend`, `POST …/{id}/reopen` y `DELETE …/{id}`, también con una invitación inexistente o de otra organización; no lee ni escribe, no emite enlace, no envía correo y no audita. La respuesta `200` con rol `viewer` y `[]` solo se obtiene con el rol `viewer` asignado; el rol mostrado no concede permiso.
- **Contratos que cambian:** la aceptación de invitación no devuelve token en el cuerpo (solo cookie, sin transición); el rol mostrado sigue la precedencia dueño → administrador → operador → árbitro → observador sin alterar la autorización aditiva; el servidor devuelve las organizaciones en orden estable (nombre y, en empate, id) y el cliente (008C) restaura la última usada solo si está en la lista; el reenvío de una invitación responde **409** sin escribir ni enviar correo si ya hay **otra** pendiente vigente del mismo correo (reenviar la propia sigue siendo **200** y la renueva); **009:** reenviar una **revocada** pasa de **200** a **409** (**C-1**, `INVITATION_REVOKED_RESEND`) y la reapertura (`POST /organizations/invitations/{id}/reopen`, **200**) es la **tercera ruta de materialización** del vencimiento (**C-2**); los 409 de **crear, reenviar y reabrir** añaden el campo aditivo `code` (`INVITATION_NOT_REVOKED`, `INVITATION_OTHER_PENDING`, `INVITATION_ALREADY_ACCEPTED`, `INVITATION_REVOKED_RESEND`) y `detail` sigue siendo cadena, mientras que el 409 de **revocar una vencida** no lleva `code`; la versión del producto se declara solo en `backend/pyproject.toml` y `/docs` la lee (no es `engine_version` 2026.1); **012 H3:** `GET /matches/{id}/operation` añade a `limits` `max_minute_regular`, `max_minute_extra` (nulo sin prórroga), `extra_time_enabled` y `penalties_enabled` sin cambiar las cuatro claves existentes; `POST …/segments` y `POST …/segments/{id}/interrupt` aceptan `resolution_type` opcional (sin campo = máximo de fase), y crear segmento, interrumpir o cerrar con una resolución no habilitada responde **409** con `detail` de cadena y `code` aditivo `RESOLUTION_NOT_ENABLED`; un cliente que ignora los campos nuevos y `code` conserva su comportamiento; **012 H4:** la configuración de reglas añade `game_format` (`5v5`/`7v7`/`9v9`/`11v11`, default `11v11`), `min_players_per_team` y `max_players_per_team` (enteros ≥ 0; 0 o ausente = sin límite; `min ≤ max` solo cuando ambos > 0; cadena vacía **422**); la inscripción en fase, el alta de equipo con `stage_id` (individual y lote) y el primer segmento responden **409** con `detail` de cadena y `code` aditivo `ROSTER_SIZE_OUT_OF_RANGE`; y `PATCH /tournaments/{id}/rosters/{roster_id}/status` (`{is_active}`) es el **único endpoint nuevo** (200 idempotente, 404 entre organizaciones, 409 de bloqueo por jornada/unicidad/dorsal, sin auditoría). `engine_version` sigue en **2026.1**: el contrato cerrado no incluye estas claves.
- **Relay sin filtro de rol (riesgo aceptado):** todo miembro conectado de la organización recibe los eventos de la sala `organization:{id}`, sin filtrar por evento ni por rol. La mitigación es la revalidación de sesión, membresía y permisos cada 30 s, que desconecta el socket si cambian; el filtrado por rol exige una spec propia.
- **Estado manual de reintento (producto, no instrumentación):** `retrying` («Reintentando…»/«Retrying…») es un valor más de `RealtimeConnectionStatus`, se anuncia con `role="status"` en las tres vistas y no añade variables globales, contadores ni atributos de prueba (RNF-010). Solo lo fija la pulsación de «Reintentar» cuando `connect()` inicia un intento nuevo; cualquier transición del motor lo sustituye.
- **Arnés E2E fuera de la suite:** `frontend/e2e/` (Playwright + Chromium headless) queda fuera de `pnpm test`, que globa solo `frontend/tests/*.test.ts`, y del `typecheck` de Nuxt; se verifica con `pnpm run e2e`, `pnpm run e2e:test` y `pnpm run typecheck:e2e`. Sus artefactos van a `frontend/e2e-report/` (ignorado) y `frontend/.auth/state.json` nunca se publica. En el resumen, `states` son las **muestras** por estado y `transitions` las **transiciones** (pares consecutivos con estado distinto; `null`/`-` si el artefacto de la vista falta o está inválido); `schemaVersion` sigue en `1` y el veredicto no consulta el campo. El número de muestras `retrying` por vista es variable y **no** es un invariante del veredicto. `screenshots/` se escribe **solo** cuando el veredicto de la vista no es verde. `server.log` lleva la cabecera exacta `# server.log — docker compose logs --no-color api worker web` y está disponible solo con esa cabecera **y** al menos una línea de contenido; la integración continua solo lo reescribe cuando el arnés no lo dejó disponible. El escenario de operación y cierre recorre los tres asistentes **solo con teclado** (título enfocado, `aria-live` y error asociado con `aria-invalid`/`aria-describedby`), comprueba la equivalencia del aviso de cierre con el 409 real en la misma versión y espera siempre la **condición observable** del cambio de paso (`?step=` en la dirección) antes de la siguiente interacción.
- **Acciones auditadas:** guardar planilla, publicar/despublicar formación, asignar/retirar oficial y reabrir una invitación revocada escriben una entrada en `administrative_audit_logs` solo ante un cambio efectivo, en la misma transacción y sin datos personales (la reapertura guarda `REOPEN_INVITATION`, sin correo ni token). Crear, reenviar y revocar invitaciones no auditan; la aceptación conserva `ACCEPT_INVITATION`. Las lecturas no auditan y no hay endpoint de consulta.
- **Workspace del torneo con direcciones propias (012, H1):** `/workspace/tournaments/{id}` es configuración (resumen, reglas, fases y equipos; anclas `#resumen`, `#configuracion` y `#equipos`), `/workspace/tournaments/{id}/calendar` es el calendario (`?stage=`: crear partido, sortear/regenerar y listar con enlace a operación) y `/workspace/tournaments/{id}/rosters` es la **única** pantalla de plantillas (`?team=`: alta individual, importación CSV/ZIP, foto y consentimiento). `#calendario` y `#plantillas` redirigen con reemplazo de historial. Los asistentes de reglas, fases y equipos llevan el paso en `?step=`, que es la **única** fuente del paso (se normaliza una vez al montar con `replace` y cada cambio del usuario apila con `push`, para que el atrás vuelva al paso anterior), y los valores en `sessionStorage` por usuario, organización, torneo, versión y asistente (`bc_wizard:…`), nunca en el servidor ni en almacenamiento persistente; el borrador local del partido es un almacén aparte.
- **Visibilidad, no permisos (012, RF-038):** la entrada «Configuración» deja de ocultarse a un `viewer` y se muestra en solo lectura, igual que calendario y plantillas, sin ninguna acción de escritura. Las capacidades del miembro con permiso de gestión no cambian. Las pantallas nuevas reutilizan los endpoints existentes filtrados por organización y **no aceptan identificadores de otra organización**: `?stage=`, `?team=` y `returnTo` solo valen si están entre los datos del propio torneo ya cargados, y el retorno solo admite la operación de un partido de ese torneo.
- **Formato de juego y límites de plantilla (012, H4):** `game_format` (`5v5`/`7v7`/`9v9`/`11v11`, default **`11v11`**) es **declarativo**: no deriva ni acota los límites, no cambia formaciones, titulares ni planilla, y con un formato distinto de `11v11` se avisa en reglas, resumen y operación **sin bloquear**. `min_players_per_team`/`max_players_per_team` son enteros ≥ 0, **independientes del formato y sin excepciones por fase**; `0` o ausente significan «sin límite», `min ≤ max` solo se exige con ambos > 0, el cliente normaliza el campo vacío a 0 y la API rechaza la cadena vacía con **422**. Cuentan **jugadores activos** de la plantilla del equipo en el torneo y solo bloquean al inscribir en fase, al crear un equipo con `stage_id` (individual y lote) y al abrir el partido (primer segmento), con el **409** `ROSTER_SIZE_OUT_OF_RANGE`; editar la plantilla **nunca** se bloquea por tamaño.
- **Retiro lógico y bloqueo por jornada (012, RC-1/RL-1/RA-1):** `PATCH /tournaments/{id}/rosters/{roster_id}/status` con `{is_active}` retira o reactiva sin borrar la fila y **sin auditoría**; devuelve el modelo de la lista (`player_id`, `age`, …), es idempotente y un roster de otro torneo u organización responde **404**. El **retiro** es la única excepción al bloqueo por jornada (RL-1); la **reactivación** se comporta como un alta (RA-1): **409** del bloqueo, **409** por jugador ya activo en el torneo (`uq_active_player_tournament`) y **409** por dorsal ocupado, sin cambiar filas. El histórico, las alineaciones y las respuestas públicas no cambian; la proyección interna deja de listar al retirado.
- La formación táctica solo es pública después de publicarse explícitamente desde el Workspace.
- Las versiones de torneo son inmutables una vez publicadas.
- La autorización es **RBAC por organización** (roles/permisos de la membresía) más **`match_officials` por partido**. No hay roles por torneo; `tournament_user_roles` fue retirada por la migración 019.
- El avance entre fases es **manual** y solo en versiones en borrador: `GET`/`POST`/`DELETE /tournaments/{id}/stages/{stage_id}/teams`. El sembrado automático por `stage_rank` no está soportado y el calendario no se regenera al asignar o quitar equipos.
- La migración **019** es destructiva y no tiene rollback: se despliega el código nuevo primero y la 019 después; cualquier corrección posterior es una migración nueva (*forward-fix*).
- La migración **013** está aplicada y **no se edita**: reescribió por coincidencia de texto cinco funciones de plataforma (`platform_set_user_active`, `platform_set_organization_active`, `platform_set_membership_active`, `platform_create_membership`, `requeue_outbox_events`) y la vista `v_public_match_lineups_unpublished`, y **falla en silencio** si el texto no coincide. El estado final se verifica con `backend/tests/test_migration_013_hardening.py` (opt-in con PostgreSQL) y cualquier corrección es una migración nueva (*forward-fix*).
- La migración **021** es aditiva y se aplica **antes** del código que escribe `player_out_id`/`player_in_id`; no elimina `match_segment_team_state` ni toca `init/01`.
- Las sustituciones se validan y aplican al **cerrar el acta** (`max_per_team`/`max_windows`/`allow_reentry`), con límites por equipo y partido. No hay API incremental de eventos ni de anulación (R11 fuera de alcance): los eventos de un acta confirmada son inmutables.
- Al desplegar, una versión **`3.2.0` ya publicada** empieza a aplicar sus límites de sustitución (la configuración efectiva sale de la versión publicada y no se reescribe); las actas cerradas no se revalidan y un partido abierto puede rechazar sustituciones antes aceptadas.
- `roster_lock_matchday` es una clave de primer nivel de `rules_config`; su valor efectivo sale de la **versión publicada**. Los minutos reglamentario y de prórroga también salen de `rules_config` (ver «Minutos»).
- No edites migraciones ya aplicadas; agrega una nueva.

## Arquitectura Clave

- **Multi-tenancy con RLS:** las tablas tenant-owned usan Row Level Security. El backend fija `app.current_organization_id` y `app.current_user_id` dentro de cada transacción.
- **Torneos:** torneos con versiones inmutables, fases componibles (Round Robin, grupos, playoffs), equipos y partidos. Puntuación, desempates, disciplina, sustituciones y ventana de inscripción se configuran con JSON; las transferencias no son configuración.
- **Actas de partido:** el cierre registra goles, tarjetas, sustituciones y suspensiones, y emite eventos al outbox.
- **Sustituciones:** la configuración efectiva `substitutions` (`max_per_team`, `max_windows`, `allow_reentry`; defaults 5/3/`false`) se aplica **al cerrar el acta**. Los eventos `substitution` llevan `player_out_id`/`player_in_id` y `player_id = player_out_id`. El estado en campo se deriva del XI de `match_rosters` y de los eventos en orden `(minute, added_minute, índice)`, con una **unión de intervalos** `[entrada, salida)` por jugador para la reentrada. Los límites son por equipo y partido; una **ventana** es el grupo `(segment_id, minute, added_minute)`.
- **Proyección de contadores:** `match_segment_team_state` guarda una fila por segmento y equipo con el saldo del partido tras ese segmento. Se asegura al abrir el segmento y se recalcula al cerrar ordenando por `segment_number` (nunca por minuto); el `GET` de operación calcula sin escribir.
- **Minutos (regla única, RF-031…RF-037):** `regular_time_minutes`/`extra_time_minutes` salen de `stage_defaults` con overrides por fase (defaults **90**/**120**) y se resuelven clave por clave, así que un override parcial solo cambia lo que declara. Al guardar se valida la pareja: reglamentario 1..179; con la prórroga habilitada, extra > reglamentario y ≤ 180; deshabilitada, el extra no se valida ni se materializa. El **máximo efectivo** es el reglamentario para `regular`, `walkover` y `administrative`, y el de prórroga para `extra_time`/`penalties` cuando la prórroga está habilitada; el tiempo añadido se cuenta dentro de ese máximo (`minute + added_minute`), con descuento solo en el minuto final, y los topes estructurales 180/30 no son regla de negocio. La **resolución prevista** se elige con un único control en la operación (por defecto `regular`), se muestra y se valida contra ese máximo y el tope de minuto añadido, vive solo en la sesión de la pestaña, se restaura al recargar y se envía al crear o interrumpir segmentos y al cerrar; sin `resolution_type` el servidor conserva el máximo de la fase. `GET …/operation` publica en `limits` las cuatro claves existentes más `max_minute_regular`, `max_minute_extra` (nulo sin prórroga), `extra_time_enabled` y `penalties_enabled`. Una resolución no habilitada (`extra_time` sin su indicador, `penalties` sin el suyo) responde **409** `RESOLUTION_NOT_ENABLED` —`detail` cadena y `code` aditivo— al crear segmento, al interrumpir y al cerrar, sin escribir; las actas cerradas y las versiones publicadas no se revalidan y no hay campos de duración nuevos en el modelo. La duración se presenta como el minuto en que termina el encuentro, no como tiempo jugado.
- **Contrato interno:** `docs/contrato-reglas.md` (`engine_version` 2026.1) fija `GF1`/`GF2` y las cuatro formaciones; no se configura desde el editor y **no incluye** `game_format` ni los límites de plantilla, que son configuración aditiva fuera de ese contrato.
- **Outbox + worker + Redis:** los eventos se procesan de forma asíncrona y alimentan el tiempo real con Socket.IO. El stream es transporte de mejor esfuerzo con un tope fijo de 10 000 entradas aproximado; no es duradero ni la fuente de verdad.
- **Autenticación y autorización:** email/password y **acceso con Google por redirección** (ningún token del proveedor pasa por el navegador). `POST /auth/google/start` guarda el intento en Redis (`sha256(state)`, TTL 600 s) y fija la cookie `bc_oauth_state` (`HttpOnly`, `SameSite=Lax`, `Path=/api/v1/auth/google`, `Max-Age=600`), devolviendo la URL del proveedor; `GET /auth/google/callback` consume el estado con `GETDEL`, canjea el código en el servidor (presupuesto 10 s), valida emisor, audiencia, vigencia, sujeto, correo verificado y nombre, y emite la sesión existente. `GET /auth/session` rehidrata `{user_id, organization_id}` (primera organización del orden estable), `GET /auth/google/status` publica solo `{enabled}` y `GET /auth/google/link` solo `{linked}`. La vinculación (`flow=link`, desde `/account/google`) no emite ni revoca sesión y nunca reescribe `users.email`; un identificador de otra cuenta responde `LINK_IDENTITY_TAKEN`. El camino anterior `POST /auth/google` responde **410** `GOOGLE_IDENTITY_INVALID` sin leer el cuerpo. Una sesión sin organización usa la pantalla opcional `POST /organizations` (201; `409` sin `code` si ya tiene una; `409 ORGANIZATION_SLUG_TAKEN` si el identificador está ocupado). Firma del `id_token` no verificada (D-9: llega del canje por TLS). RBAC por organización: los permisos se resuelven por la membresía y sus roles; no hay ámbito por torneo ni roles por torneo. La única delegación menor es por partido con `match_officials`.
- **Log de acceso saneado:** la API arranca con `--no-access-log` en desarrollo y producción; el middleware de `app/core/access_log.py` emite una línea `access method=… path=… status=…` por petición, sin consulta, fragmento, cabeceras ni cuerpo. Cubre también los rechazos de CSRF/tamaño y, ante una excepción no controlada, registra 500 y la relanza.
- **Origen de las escrituras:** toda escritura valida `Origin` y `Referer` por separado (`backend/app/core/csrf.py`). Sin ninguna de las dos se admite; si cualquiera está presente y no es un origen permitido, **403**, aunque la otra sí lo esté. Un `Referer` vacío o no parseable se rechaza; un proxy que lo reescriba a un host interno debe permitir ese origen o retirar la cabecera.
- **Avance manual entre fases:** `GET`/`POST`/`DELETE /tournaments/{id}/stages/{stage_id}/teams` en versiones en borrador. `POST` es atómico (1..64 equipos, sin duplicados); 201 si hay altas, 200 si todos ya estaban, 204 en la retirada idempotente; 403/404/409/422 según el contrato. No regenera el calendario ni resuelve `phase_slots` entre fases.
- **Estructura publicada:** los triggers impiden modificar la estructura de una versión publicada o archivada. El trigger de estructura lanza el SQLSTATE **`ZZ409`**; la API lo mapea a **409** por código, sin comparar el texto.
- **Bloqueo y rendimiento:** fase → versión → partido(s) → segmentos → jugadores. El cierre serializa por fase; es una garantía de corrección, no se midió throughput ni latencia (RNF-003).
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
- API / documentación: `http://localhost:8000/docs`; la API se publica solo en `127.0.0.1:8000` y el web conserva `3000:3000` porque es el punto de entrada del desarrollador y el flujo en Windows/WSL depende de esa publicación.
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

### Migración 019 (runbook)

La **019** es destructiva y **no tiene rollback**: elimina `tournament_user_roles` y `stage_edges`, estrecha el `CHECK` de `phase_slots.source_type` a `direct_team`/`match_result` y recrea `prevent_published_structure_mutation()` con SQLSTATE **`ZZ409`**. Conserva `phase_slots` y las columnas de slots de `matches`. Después de aplicada solo cabe *forward-fix* con otra migración; `schema_migrations`/checksum impiden reaplicarla. Orden: **código nuevo primero (esquema 018), después la 019**; la imagen antigua lee `stage_edges` en el clonado.

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre019.dump"
pg_restore -l "$HOME/backup-pre019.dump" > /dev/null && echo "backup verificable"
$COMPOSE stop api worker
```

Pre-chequeo (solo conteos; `to_regclass` permite que una tabla ausente cuente como 0). Ejecuta las ramas de cada tabla solo si existe. Las referencias a estructuras **retiradas** son solo para comprobar que están vacías o ausentes:

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

Todo debe ser 0. Después revisa el catálogo: relaciones, funciones, vistas, políticas, triggers y **FKs entrantes**; antes solo debe aparecer la propia tabla (y su política/trigger) y después nada:

```sql
SELECT 'relation' AS kind, c.relname AS object FROM pg_class c
WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
UNION ALL SELECT 'function', p.oid::regprocedure::text FROM pg_proc p
WHERE p.prosrc ~ '(tournament_user_roles|stage_edges)'
UNION ALL SELECT 'view', v.viewname FROM pg_views v
WHERE v.definition ~ '(tournament_user_roles|stage_edges)'
UNION ALL SELECT 'policy', pol.polname FROM pg_policy pol
JOIN pg_class c ON c.oid = pol.polrelid
WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
UNION ALL SELECT 'trigger', t.tgname FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
UNION ALL SELECT 'incoming_fk', con.conname FROM pg_constraint con
WHERE con.contype = 'f' AND con.confrelid IN (
  SELECT c.oid FROM pg_class c
  WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
);
```

Aplica y haz smoke:

```sh
MIGRATION_TARGET=019 $COMPOSE run --rm db-migrate
$COMPOSE up -d api worker
```

Comprueba `/docs`, una lectura pública y una operación del Workspace (incluida la asignación manual en un borrador). Si falla un pre-chequeo, corrige los datos y reintenta; si falla una FK entrante, crea la migración que la resuelva. Después de la 019 no hay `down`; restaura el backup solo si aceptas perder cambios posteriores. El conflicto de estructura publicada devuelve **409** por `ZZ409`; no se compara el texto.

### Migración 020 (forward-fix de privilegios)

La **020** no es destructiva y va **después de la 019**. Concede solo `INSERT (id)` sobre `public.rosters` a `bracket_app` (privilegio de columna, no de tabla): la importación masiva pre-genera el `id` del roster para subir la foto antes de la transacción y construir la clave del objeto. `init/01` incluye el mismo grant para un volumen limpio. No cambia datos, funciones ni políticas.

```sh
MIGRATION_TARGET=020 $COMPOSE run --rm db-migrate
```

### Migración 021 (referencias de jugador en sustituciones)

La **021** es **aditiva** y se aplica **antes** del código que escribe las columnas: añade `player_out_id`/`player_in_id` (UUID nulas) a `match_events`, dos FKs compuestas `(player_out_id, organization_id)` y `(player_in_id, organization_id)` a `players(id, organization_id)` con `ON DELETE RESTRICT`, y `chk_match_event_substitution_pair` como `CHECK ... NOT VALID`. **No elimina `match_segment_team_state`** (sigue siendo la proyección de contadores), no toca `transfers` (no existe como tabla) y no modifica `init/01` ni las migraciones 019/020. Los eventos `substitution` legados (sin par salida/entrada) no se reescriben; el `CHECK` se evalúa en `INSERT`/`UPDATE` y el motor los ignora. No hay backfill ni `VALIDATE CONSTRAINT`.

Prepara una copia verificada y detén `api`/`worker` durante la ventana: el código anterior no escribe el par y no debe seguir cerrando actas con eventos `substitution` contra el `CHECK` nuevo.

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

Aplica la migración y después el código nuevo:

```sh
MIGRATION_TARGET=021 $COMPOSE run --rm db-migrate
$COMPOSE build api
$COMPOSE up -d api worker
```

Orden obligatorio: **migración 021 → código**. El código nuevo contra el esquema 020 falla al insertar una sustitución porque las columnas no existen. Con la 021 aplicada, el código anterior sigue leyendo el esquema, pero no debe cerrar sustituciones (el `CHECK` rechaza el par ausente).

**Smoke:** `GET /docs`, una lectura pública de torneo, una operación del Workspace con un borrador y, si hay datos, la pantalla de operación de un partido (`GET /matches/{id}/operation`) y el cierre de un acta con una sustitución válida. Comprueba que la fila de `match_segment_team_state` del segmento refleja el saldo.

**Si algo falla después:** la 021 no se desaplica. Al ser aditiva, cualquier defecto se corrige con una migración nueva (*forward-fix*); no hay rollback de datos ni de esquema. Restaurar `$HOME/backup-pre021.dump` solo si se acepta perder los cambios posteriores. El volumen limpio (`init/00-03` → 001-021) termina con el mismo esquema que una base migrada.

### Migración 022 (topes de minuto en eventos)

La **022** es **aditiva** y compatible con el código actual: añade a `public.match_events` los `CHECK` `chk_match_event_minute_range` (`minute BETWEEN 0 AND 180`) y `chk_match_event_added_minute_range` (`added_minute BETWEEN 0 AND 30`). No añade columnas, no modifica datos ni `init/01` y no cambia RLS. Un pre-chequeo en la misma transacción aborta con ambos conteos si hay filas fuera de rango y **no recorta** datos; si pasa, las restricciones se añaden **validadas** (no `NOT VALID`), con un bloqueo breve sobre la tabla. Son topes estructurales: la regla deportiva de la fase sigue en la API (180/30 son el máximo de forma).

```sh
MIGRATION_TARGET=022 $COMPOSE run --rm db-migrate
```

Va **antes** de la 023. No hay rollback: cualquier defecto se corrige con una migración nueva (*forward-fix*). El volumen limpio (`init/00-03` → 001-022) termina con el mismo esquema que una base migrada.

### Migración 023 (vueltas de fase persistidas)

La **023** es **aditiva**: añade a `public.stages` la columna `schedule_legs SMALLINT NOT NULL DEFAULT 1` con `CHECK (schedule_legs IN (1, 2))` (`chk_stages_schedule_legs`). No reescribe filas ni toca `init/01` ni RLS. El sorteo de liga y de grupos escribe las vueltas recibidas (`legs`), `_load_draft_stage_context` las lee en el borrador y el clonado de versiones copia el valor; eliminatorias y Swiss conservan el default. Los triggers de estructura existentes impiden reescribir el formato en una versión publicada o archivada.

```sh
MIGRATION_TARGET=023 $COMPOSE run --rm db-migrate
```

Va **después** de la 022 y **antes** del backend que lee `schedule_legs`. Sin *backfill*: una liga histórica de dos vueltas queda en una hasta que se regenere su calendario, de modo que el límite de enfrentamientos manuales por pareja es uno mientras no se regenere (las versiones publicadas no admiten altas manuales). No hay rollback: cualquier defecto se corrige con una migración nueva (*forward-fix*). El volumen limpio (`init/00-03` → 001-023) termina con el mismo esquema que una base migrada.

### Verificación (mismos checks que CI)

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cd backend && pytest -q
cd backend && python -m compileall -q app
cd frontend && pnpm install --frozen-lockfile
cd frontend && pnpm test
cd frontend && pnpm run typecheck
cd frontend && pnpm run build
cd frontend && pnpm run typecheck:e2e
cd frontend && pnpm run e2e
sh -n infra/postgres/migrate.sh
sh -n infra/scripts/verify_worker_loop_health.sh
# Runner de MIGRATION_TARGET (requiere PostgreSQL local; misma prueba que CI)
docker run --rm --network host -v "$PWD/infra:/infra:ro" \
  -e PGHOST=127.0.0.1 -e PGPORT=5432 -e PGUSER=postgres \
  -e PGPASSWORD=postgres_test_password \
  postgres:17-alpine sh /infra/scripts/test_migrate_target.sh
docker compose config -q
docker compose config --format json | python3 infra/scripts/check_env_contract.py -
python3 infra/scripts/check_env_contract.py --self-test
docker compose config --format json | python3 infra/scripts/assert_production_compose.py --profile development -
pip-audit -r backend/requirements.txt -r backend/requirements-dev.txt
AUDIT_JSON="/tmp/pnpm-audit.json"
trap 'rm -f "$AUDIT_JSON"' EXIT
if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
```

La auditoría del frontend se ejecuta desde la raíz con el bloque anterior: `infra/scripts/audit_frontend.py` falla ante cualquier hallazgo `high` o `critical` con corrección publicada, muestra los no accionables (incluidos los que no tienen parche) para su revisión y no persiste exclusiones. No uses listas de GHSA ni flags que persistan exclusiones, como `--ignore-unfixable`, `audit.ignore` o `auditConfig.ignoreGhsas`.

El E2E del reintento del tiempo real vive en `frontend/e2e/` y **no** entra en `pnpm test`. `pnpm run e2e` arranca la pila con `docker compose up -d --build --wait --wait-timeout 300` (≤5 min, informado aparte), ejecuta el seed demo, corre Playwright con un solo motor Chromium headless y `retries: 0`, y baja la pila que arrancó. `pnpm run e2e:test` es el mismo escenario con `--no-stack` contra una pila ya levantada y sembrada (`docker compose up -d --wait` + `python -m scripts.seed_demo`) y es lo que ejecuta CI. Requisitos: Docker operativo, `.env` (`cp .env.example .env`) y Chromium (`cd frontend && pnpm exec playwright install --with-deps chromium`). Códigos de salida: **0** verde (las tres vistas `passed`), **1** fallo de comportamiento, **2** fallo de infraestructura (pila, datos demo o navegador) y **3** corrida inválida (vista omitida/ausente o escenario no concluyente); solo **0** abre el gate. Los artefactos quedan en `frontend/e2e-report/`, ignorado por git.

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
  | python3 infra/scripts/check_env_contract.py --profile production -
docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json \
  | python3 infra/scripts/assert_production_compose.py -
```

El overlay no publica puertos, no monta código del host en `api`, `worker` ni `web` y deja todos los servicios en la red interna `internal`; solo `web` se une a la red externa del proxy.

Además, CI ejecuta un escaneo de sistema de archivos con Trivy (`aquasecurity/trivy-action@v0.36.0`). Equivale localmente a:

```sh
trivy fs . --skip-dirs frontend/node_modules,frontend/.pnpm-store,.venv --ignore-unfixed --severity CRITICAL,HIGH --exit-code 1
```

### Migración 024 (identidad de Google única)

Aditiva: un pre-chequeo aborta con el conteo si una cuenta tiene más de una identidad del mismo proveedor (no borra, fusiona ni reescribe filas) y después añade `uq_auth_identity_user_provider UNIQUE (user_id, provider)` a `auth_identities`. Sin grants nuevos, sin RLS y sin tocar `init/01`.

```sh
MIGRATION_TARGET=024 $COMPOSE run --rm db-migrate
```

**Orden: migración 024 → código.** El código nuevo funciona con el esquema 023, pero sin la restricción dos intentos simultáneos podrían dejar dos identidades en una cuenta; la restricción es la garantía. **No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). El volumen limpio (`init/00-03` → 001-024) termina con el mismo esquema que una base migrada.

## Runtime

- **Servicios de Docker Compose:** PostgreSQL, `db-migrate` (job de una sola ejecución), API, worker, Redis, `storage` (SeaweedFS) y web.
- **Inicialización de PostgreSQL:** `infra/postgres/init/` solo corre en el primer arranque del volumen.
- **Migraciones:** `infra/postgres/migrate.sh` aplica las migraciones numeradas de `infra/postgres/migrations/` una sola vez y las registra en `schema_migrations` con checksum SHA-256. `MIGRATION_TARGET` (vacía o `NNN`; no existe una bandera `--target`) limita la aplicación a esa versión, valida los checksums de todos los archivos y no desaplica nada.
- **Cifrado de la fecha de nacimiento:** las migraciones 017 y 018 se aplican en dos fases con `MIGRATION_TARGET` y el backfill one-off `python -m scripts.encrypt_birth_dates` (`DATABASE_ADMIN_URL` + `PLAYER_DATA_KEY`, `--no-deps`). La 018 falla de forma cerrada si quedan pendientes.
- **Migración 019:** retira `tournament_user_roles` y `stage_edges`, estrecha el `CHECK` de `phase_slots.source_type` y recrea el trigger con `ZZ409`; es destructiva y sin rollback. Se aplica después del código nuevo con `MIGRATION_TARGET=019 $COMPOSE run --rm db-migrate`, tras backup verificado y pre-chequeo de catálogo.
- **Migración 020:** *forward-fix* no destructivo que concede `INSERT (id)` sobre `rosters` a `bracket_app` para el `id` pre-generado de la importación N-2; `init/01` incluye el mismo grant y se aplica después de la 019 (`MIGRATION_TARGET=020`).
- **Migración 021:** aditiva; añade `player_out_id`/`player_in_id`, FKs compuestas y `chk_match_event_substitution_pair` (`NOT VALID`) a `match_events`; se aplica **antes** del código con `MIGRATION_TARGET=021` y no elimina `match_segment_team_state` ni tiene rollback (*forward-fix*).
- **Migración 022:** aditiva; añade los `CHECK` `chk_match_event_minute_range` (`minute` 0..180) y `chk_match_event_added_minute_range` (`added_minute` 0..30), validados tras un pre-chequeo que aborta sin recortar datos; es compatible con el código actual y sin rollback (*forward-fix*).
- **Migración 023:** aditiva; añade `stages.schedule_legs` (`SMALLINT NOT NULL DEFAULT 1`, `CHECK (1,2)`), escrito por el sorteo de liga/grupos con las vueltas recibidas, leído por `_load_draft_stage_context` y copiado al clonar versiones. Sin *backfill*: una liga histórica de dos vueltas queda en una hasta regenerarse (las publicadas no admiten altas manuales); sin rollback (*forward-fix*).
- **Producción:** `APP_ENV=production` con `docker-compose.production.yml`, que no publica ningún puerto, elimina los montajes de código de `api`, `worker` y `web` con `!reset`, desactiva `--reload`, construye el frontend estático y exige secretos y URLs de producción. El backend rechaza los defaults conocidos.
- **Healthchecks:** la API se declara sana cuando `/health/ready` confirma base de datos y Redis; el web, cuando responde por HTTP con `/health.txt` (estático, no mide la API ni la base de datos tras arrancar); el worker, mientras su latido de fichero tenga menos de `HEARTBEAT_MAX_AGE_SECONDS` (**90 s**, única fuente del umbral). Una **vuelta completada** es una iteración que termina, con o sin trabajo y con o sin error de la dependencia; el **bucle detenido** es un worker vivo que no completa una vuelta en **90 s**, haya o no eventos. El worker publica cada **10 s** (`HEARTBEAT_INTERVAL_SECONDS`) en `/tmp/bracket-craft-worker-heartbeat` (configurable con `WORKER_HEARTBEAT_PATH`, que debe coincidir en el proceso y en el healthcheck) también sin eventos que procesar. Un fallo de base de datos o Redis con el bucle girando y reintentando **no** cuenta como detenido: sigue sano. El web espera una sola vez a la API con `depends_on.condition: service_healthy`; con la base de datos detenida la API queda `unhealthy` (insana), el web sigue `healthy` y el worker sigue `healthy` mientras su bucle avance y reintente. La transición real se verifica con `sh infra/scripts/verify_worker_loop_health.sh [servicio|contenedor]` (congela el bucle de un worker vivo y observa `healthy → unhealthy → healthy`) y, desde la spec 011, la misma corrida comprueba que el worker **procesa trabajo**: un **paso 0** pregunta el `APP_ENV` efectivo del worker (`python -m scripts.outbox_probe guard`) y, solo en desarrollo/local, un **paso 7** posterior a la reanudación inserta una sonda de outbox inocua, espera su estado `processed` en la cola (el stream solo corrobora) y la borra siempre en el `trap` de salida. Presupuesto propio con `WORKER_PROBE_TIMEOUT` (defecto **120** s) y `WORKER_PROBE_POLL_INTERVAL` (defecto **2** s), enteros positivos; `pending`/`processing` se tratan como «sigue esperando». Códigos: **0** transición y sonda procesada, **1** fallo de comportamiento (incluida sonda `failed`, desaparecida, agotada o no borrada, que informa `id` y marcador), **2** no ejecutable sin Docker, sin contenedor, con variables inválidas, sin los datos demo (organización y propietario demo, o su membresía activa) o fuera de desarrollo/local (no escribe nada y se declara **no ejecutada**). No forma parte de la suite. La sonda no tiene handler de dominio ni datos personales y en desarrollo aparece como un evento de socket inocuo en la sala de la organización demo.
- **Contrato de entorno:** `.env.example` es la fuente de documentación y el mapa variable→servicio vive en `infra/scripts/check_env_contract.py`. La API recibe la configuración de la aplicación; el worker `DATABASE_URL`, `REDIS_URL` y `APP_ENV` (más `JWT_SECRET` y `PLAYER_DATA_KEY` fuera de desarrollo); el web `NUXT_*` y `CI`/`NODE_ENV`; `db` las credenciales de PostgreSQL; `db-migrate` `POSTGRES_*`, `PGPASSWORD`, `MIGRATION_TARGET` y `PLATFORM_ADMIN_EMAIL`; el one-off de cifrado `DATABASE_ADMIN_URL` y `PLAYER_DATA_KEY` con `-e`, nunca la API. Excepciones: `PGPASSWORD`, `DATABASE_URL`, `DATABASE_ADMIN_URL`, `CI`, `NODE_ENV` y valores de pruebas o entornos locales. El comando está en «Verificación»; falla por variable documentada sin efecto, declarada sin documentar o mal atribuida.
- **Dependencias de prueba:** `backend/requirements-dev.txt` se instala solo en local y CI (`python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt`); la imagen de producción instala únicamente `backend/requirements.txt` y `pip-audit` audita ambos archivos.
- **Web no-root solo en producción:** la etapa de ejecución de `frontend/Dockerfile` declara `USER node` y el overlay de producción fija `web.user: "node"`. `docker-compose.yml` fija `web.user: "0:0"` como excepción de desarrollo, porque el servidor escribe caché en el árbol montado `./frontend` y el propietario del montaje difiere entre Linux y Windows/WSL; producción no hereda esa excepción. Condición de retiro: cuando el flujo de desarrollo deje de necesitar escritura en el montaje. El arranque no-root se validó localmente con Docker (uid 1000, `.output` no escribible, HTTP 200) y la salvaguarda automatizada en CI es `infra/scripts/assert_production_compose.py` (perfil de producción), porque la CI no construye la imagen.
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
  contrato-reglas.md         Contrato interno: GF1/GF2 y formaciones (engine_version 2026.1)
  runbook-despliegue-019-023.md  Despliegue acumulado 018 → 023 (ventana, pre/post-chequeos)
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
  app/pages/workspace/tournaments/[id]/
                              Rutas propias del torneo: calendar.vue y rosters.vue
  app/utils/                  Funciones puras de navegación, asistentes y reglas (node --test)
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
- **Sustituciones:** en un evento `substitution` deben venir `player_out_id` y `player_in_id` no nulos y distintos, con `player_id = player_out_id`; en cualquier otro tipo, ambos nulos. El incumplimiento estructural es **422** y las reglas de negocio (equipo, plantilla, campo/banca, reentrada, límites, ventanas, minutos) son **409**. La comprobación coincide con `chk_match_event_substitution_pair` (021).
- **Actas cerradas inmutables:** los eventos de un acta confirmada no se editan ni se anulan (`trg_validate_match_event_context` bloquea `INSERT`/`UPDATE` en `finished`, `cancelled` y `administrative_resolution`). No existe API incremental de eventos ni de anulación (R11 fuera de alcance); `is_voided` es legado y no es una vía operativa.
- **Promoción de configuración:** el editor promueve `transfers.roster_lock_matchday` a la clave de primer nivel al cargar si esta falta, y el backend hace lo mismo al guardar; `transfers` se acepta como bloque deprecado y no se escribe.
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
- **Caché de CI:** pip se cachea con `backend/requirements.txt` y `backend/requirements-dev.txt`, y pnpm con `frontend/pnpm-lock.yaml`; mantén `frontend/pnpm-lock.yaml` versionado, porque la instalación usa `--frozen-lockfile`.
- **Compose y secuencias:** `ports: []` y `volumes: []` **no** anulan las secuencias heredadas de desarrollo; el merge las concatena. El overlay de producción usa `!reset []`/`!override` (Compose ≥2.24.4) y la CI valida el JSON renderizado con `infra/scripts/assert_production_compose.py`. No vuelvas a `[]`.
- **Stream del outbox:** no es duradero ni se debe reemitir al arrancar (el relay empieza en el último id). El tope fijo de 10 000 entradas aproximado se dimensiona con P-1 (unos 3 eventos por cierre; varios días con unos pocos MB). Garantías por tramo: outbox→stream *at-least-once*, stream→cliente *best-effort* con huecos y duplicados; la API HTTP es la fuente de verdad. `event_id` es aditivo y `id` se conserva como legado durante la transición; el cliente deduplica 200 entregas. `RESYNC` es una notificación de control (`event_id`/`reason`), no un evento persistido.
- **Cifrado de la fecha (017/018):** la 017 revoca `SELECT`/`INSERT` de `birth_date` y la 018 falla de forma cerrada si el backfill dejó pendientes. En una base con datos no uses el flujo por defecto: sigue el runbook y ejecuta el one-off con `--no-deps`. Tras la 018 no hay reversión de código, solo *forward-fix*.
- **Migración 019 (roles por torneo y `stage_edges`):** es destructiva y no tiene `down`. Retira `tournament_user_roles` y `stage_edges`, estrecha el `CHECK` de `phase_slots.source_type` a `direct_team`/`match_result` y recrea el trigger de estructura con **`ZZ409`**. Despliega el código nuevo antes de aplicarla; después solo *forward-fix* con una migración nueva. `init/01` conserva las dos tablas (con RLS y sin políticas/grants) solo hasta que la 019 las elimina.
- **Fotos y transacciones:** no firmes fotos, no subas ni borres objetos y no calcules emparejamientos dentro de una transacción; el contexto RLS es local a cada transacción y se vuelve a fijar en la escritura. En alta/importación, un fallo de firma posterior al commit deja la fila creada y responde 503: el cliente debe releer. Las subidas van antes de la escritura y se compensan si falla antes del commit. El objeto anterior de una subida se borra solo tras un commit confirmado; un commit fallido o cancelado (ambiguo) conserva ambos y puede dejar el nuevo huérfano. La importación puede dejar objetos huérfanos si el commit falla (best-effort): se prefiere un huérfano a una referencia rota.
- **Cliente de firma cacheado:** conserva las credenciales resueltas al construirse; rotarlas exige reiniciar el proceso. La caché es por proceso y endpoint de firma efectivo, no por endpoint de subida.
- **Límites Swiss:** 64 equipos, 50 000 evaluaciones y 10 s son límites de seguridad, no reglas deportivas (puntuación, desempates, disciplina, sustituciones y ventana de inscripción siguen en el JSON). El hilo de cálculo no se cancela: el timeout descarta el resultado y el hilo termina por su presupuesto.
- **Sustituciones y 021:** el número de línea del acta es el **índice del payload** y desempata el orden canónico `(minute, added_minute, índice)`. `max_per_team = 0` deshabilita las sustituciones y `max_windows = 0` no admite ninguna ventana. Los eventos legados sin par no consumen cupo ni ventana y el `CHECK` no tolera reescribirlos. `match_segment_team_state` no se elimina en la 021; sin filas previas se aseguran al cerrar y el `GET` de operación no escribe.
- **Sorteo simultáneo en frío:** la ronda 1 sin partidos previos no bloquea filas inexistentes, así que dos sorteos concurrentes podrían insertar calendarios duplicados (no hay unicidad de `bracket_code`). Es el riesgo residual aceptado por la spec 005.
- **Migración 002:** un volumen limpio de PostgreSQL había fallado antes con `cannot drop columns from view`. Causa raíz: `infra/postgres/init/02_public_projections.sql` había sido actualizado para reflejar el estado post-012 (`v_public_stages` y `bracket_code` en `v_public_matches`), pero la migración 001 reescribe `v_public_matches` sin `bracket_code`, y `CREATE OR REPLACE VIEW` no puede soltar columnas. La corrección fue revertir `init/02` al estado pre-012 (los scripts de init no son migraciones y no tienen checksum), de modo que 012 introduzca esos cambios en el orden correcto. Solo afecta a volúmenes limpios; los existentes no re-ejecutan init.
- **Windows/WSL:** si pnpm falla con `EPERM` al enlazar `node_modules`, construye y ejecuta mediante el servicio `web` de Docker.
- **Seed demo:** solo admite entornos de desarrollo/local; no lo ejecutes contra producción.
- **Init de PostgreSQL:** los scripts de `init/` no se re-ejecutan en volúmenes existentes; para reiniciar desde cero hay que borrar el volumen.

## Testing

La CI (`ci.yml`) tiene **cinco** jobs independientes; reproduce localmente el que corresponda a tu cambio. La §4 de `docs/constitution.md` (versión **1.4.0**) incluye el job `e2e` junto a `backend`, `frontend`, `infrastructure` y `security`; la enmienda se tramitó en un cambio propio según §5.2. Marcar `e2e` como *required check* es configuración del repositorio en GitHub (protección de rama), no un cambio de código ni de `ci.yml`.

- **`backend` (Backend tests):** `cd backend && pytest -q`, más `python -m compileall -q app` para detectar errores de sintaxis. El job también ejecuta `infra/scripts/test_migrate_target.sh` contra PostgreSQL 17 y la suite con base (`RUN_DATABASE_TESTS=1`).
- **`frontend` (Frontend checks):** `pnpm install --frozen-lockfile`, `pnpm test`, `pnpm run typecheck` y `pnpm run build` desde `frontend/`.
- **`infrastructure` (Infrastructure checks):** `python3 infra/scripts/verify_version_sources.py --exclude-constitution`, `sh -n infra/postgres/migrate.sh`, versión de Compose ≥2.24.4, `docker compose config -q` para desarrollo y para el merge dev+prod con variables dummy, y las aserciones de `infra/scripts/assert_production_compose.py` sobre el JSON renderizado.
- **`security` (Dependency and filesystem scan):** `pip-audit -r backend/requirements.txt -r backend/requirements-dev.txt`, la auditoría del frontend desde la raíz con `infra/scripts/audit_frontend.py` (bloque de Verificación) y el escaneo Trivy descrito en Comandos.
- **`e2e` (Realtime retry end-to-end):** el **quinto** job, con `timeout-minutes: 25`, se ejecuta en **cada `pull_request`** y **solo** en `push` a `main` (un `push` a otra rama no lo ejecuta y no se declara verde). Instala pnpm 12.12.1 y Node 24 con caché por `frontend/pnpm-lock.yaml`, ejecuta `pnpm run typecheck:e2e`, `cp .env.example .env`, `docker compose up -d --build --wait --wait-timeout 300`, el seed demo y `pnpm run e2e:test` **dentro del contenedor oficial `mcr.microsoft.com/playwright:v1.64.1-noble`** (que ya trae Chromium y sus dependencias de sistema, con `--network host` para alcanzar `web`/`api` publicados y el repositorio montado), de modo que el job **no** instala navegadores ni paquetes del sistema en el runner (sin `apt`, sin `playwright install --with-deps` y sin caché de `~/.cache/ms-playwright`); el veredicto sigue siendo **0/1/2/3** sin reintentos (`retries: 0`); en `if: always()` vuelca `docker compose logs` saneado y publica `frontend/e2e-report` como artefacto `e2e-realtime-<run_id>` (retención 7 días) y baja la pila con `docker compose down -v`. Presupuesto: corrida ≤15 min y vista ≤4 min, con el arranque informado aparte. `typecheck:e2e` es imprescindible porque el `typecheck` de `frontend` no cubre `e2e/`.
- **Acceso con Google (manual, T30):** el job `e2e` **no** cubre Google. La comprobación con un cliente OAuth real —alta, reentrada sin duplicados, `ACCOUNT_EXISTS_PASSWORD` + vinculación, cancelación/estado inválido y retorno a una invitación— está **declarada no ejecutada** porque este entorno **no tiene un cliente OAuth real configurado**; no se registran fecha ni resultados. Cuando se ejecute, su resultado (fecha, entorno y códigos, sin correos ni identificadores) se registra en `README.md`.

- **Pruebas de integración de invitaciones (opt-in):** requieren PostgreSQL en ejecución con la cuenta y organización demo. Cubren crear, reenviar, revocar, aceptar y reabrir: reabrir una revocada (**200**, misma fila y enlace anterior sin resolver), sus 409 `INVITATION_NOT_REVOKED`/`INVITATION_OTHER_PENDING`, reenviar una revocada **409** `INVITATION_REVOKED_RESEND` (C-1), la materialización previa de otra pendiente vencida (C-2), la entrada `REOPEN_INVITATION`, la **atomicidad de C-2** con un fallo inducido después de materializar (500 sin enlace, ambas escrituras revertidas, sin auditoría ni correo) y el **403 del miembro sin rol** contra el endpoint auténtico (la dependencia de contexto se ejecuta de verdad; solo se sustituyen sesión e identidad). Los mensajes de fallo usan `describe_response`/`describe_status` de `backend/tests/assertion_messages.py` y nunca vuelcan el cuerpo. Los unitarios que no necesitan base —`test_assertion_messages.py` (barrido `ast` de los mensajes) y `test_outbox_probe.py` (funciones puras y aserciones de fuente)— corren en `pytest -q`.

  ```sh
  cd backend && pytest -q tests/test_assertion_messages.py tests/test_outbox_probe.py
  # con PostgreSQL local y las variables del contenedor
  cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_invitations.py
  # o contra la pila de Compose ya levantada
  docker compose exec -e RUN_DATABASE_TESTS=1 api pytest -q tests/test_invitations.py
  ```

- **Acceso con Google y organización opcional (opt-in):** requieren PostgreSQL y `DATABASE_ADMIN_URL`. `test_migration_024.py` construye bases desechables (cadena limpia `init` + 001…024 y 023 → 024); `test_google_accounts_db.py` y `test_organizations_create_db.py` usan la base configurada con `SAVEPOINT` y la revierten; `test_google_concurrency_db.py` crea bases y un rol dedicado por prueba.

  ```sh
  cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
    pytest -q tests/test_migration_024.py tests/test_google_accounts_db.py \
             tests/test_google_concurrency_db.py tests/test_organizations_create_db.py
  ```

- **Salud del worker con contenedores (operación, no suite):** `sh infra/scripts/verify_worker_loop_health.sh` congela el bucle de un worker vivo y comprueba la transición `healthy → unhealthy → healthy` sin reiniciar el contenedor y, solo en desarrollo/local, que el worker procesa una sonda de outbox y que la fila se borra al salir. Requiere Docker; sin él, con `APP_ENV` fuera de desarrollo/local o con variables inválidas sale **2** sin escribir nada y la validación la declara **no ejecutada**. Ajusta el presupuesto de la sonda con `WORKER_PROBE_TIMEOUT` (defecto 120 s) y `WORKER_PROBE_POLL_INTERVAL` (defecto 2 s). No forma parte de `pytest` ni de `pnpm test`.

- **Migración 019 y concurrencia (opt-in):** requieren PostgreSQL y `DATABASE_ADMIN_URL`; crean bases desechables o usan la configurada. Si no se ejecutan, se declaran como no ejecutadas.

  ```sh
  cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
    pytest -q tests/test_migration_019.py tests/test_concurrency_006.py
  ```

- **Sustituciones y migración 021 (opt-in):** requieren PostgreSQL y `DATABASE_ADMIN_URL`.

  ```sh
  cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
    pytest -q tests/test_migration_021.py tests/test_substitutions.py tests/test_roster_lock.py
  ```

- **Proyección interna y contrato público de jugadores (opt-in):** requieren PostgreSQL; comprueban que las respuestas públicas no incluyen edad, documento ni fecha de nacimiento y que ningún endpoint consume `v_public_tournament_players`.

  ```sh
  cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
    pytest -q tests/test_public_player_views.py
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
