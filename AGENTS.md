# Guía para Agentes: Bracket Craft

Plataforma multi-tenant para crear y operar torneos de fútbol con reglas configurables, fases componibles y resultados en tiempo real.

## Fuentes de Verdad

Ante cualquier duda, consulta en este orden:

1. `docs/constitution.md`: principios innegociables, reglas de implementación y criterios obligatorios. Tiene precedencia sobre cualquier otro documento.
2. `README.md`: alcance del producto, flujo local, datos demo, seguridad y modelo de acceso público/privado.
3. `docs/manual-usuario.md`: manual de usuario del producto (acceso y organización, creación de torneos, reglas, fases, equipos y plantillas, calendario, operación de partido y actas, consulta pública, verificación). Coherencia documental con README y AGENTS (RNF-006).
4. `docs/contrato-reglas.md`: contrato interno de reglas (`engine_version` 2026.1): códigos `GF1`/`GF2` y catálogo de formaciones. No es configurable.
5. `specs/NNN-nombre/` (`spec.md`, `plan.md`, `tasks.md`): requisitos, diseño y tareas de cada funcionalidad desarrollada con SDD.
6. `MEMORY.md`: estado y decisiones del trabajo SDD en curso.
7. `docker-compose.yml` y `docker-compose.production.yml`: servicios, puertos, variables y diferencias entre desarrollo y producción.
8. `.env.example`: variables de entorno y defaults **solo de desarrollo**.
9. `infra/postgres/migrations/`: fuente de verdad del esquema de base de datos (migraciones numeradas).
10. `backend/app/main.py`: registro de routers y punto de entrada de la API.
11. `backend/app/modules/`: límites de cada funcionalidad del backend.
12. `frontend/app/composables/useApi.ts`: contrato de llamadas HTTP del frontend.
13. `.github/workflows/ci.yml`: lista autoritativa de verificaciones (cinco jobs con permisos `contents: read`: `backend`, `frontend`, `infrastructure` y `security` en cada `push` y `pull_request`, y `e2e` en cada `pull_request` y solo en `push` a `main`).
14. Documentación interactiva de la API en `http://localhost:8000/docs`.

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
- **Matriz de acceso público (spec 020):** la consulta pública (portada y detalle, sin sesión) solo sirve el listado de torneos, el detalle, la clasificación y los partidos con alineaciones publicadas (RF-013); un torneo no visible responde el mismo `404` indistinguible (RF-014). Todo lo demás exige sesión, organización activa y permiso (RBAC por organización más `match_officials` por partido). Nunca salen documentos de identidad, fecha de nacimiento, edad, `logo_url` heredado, claves de almacenamiento, motivo de walkover/resolución administrativa, sanciones, suspensiones, la plantilla inscrita del equipo ni la asistencia del gol, auditoría ni datos de miembros/organizaciones (RF-016), ni se mezclan datos de otra organización (RF-017); no se añade ninguna escritura, cookie ni dependencia de sesión (RF-018). **La spec 020 no añade campos públicos nuevos** (RNF-001): solo reorganiza la navegación por fases/grupos y audita el acceso. La spec 021 añade aditivamente `segment_number` (entero, nullable) a `PublicTeamLineupResponse` (RF-007, RF-015) para etiquetar la formación con su segmento, sin cambiar permisos ni la matriz. La spec 022 añade dos lecturas públicas nuevas, `GET /tournaments/public/{id}/player-stats` y `GET /tournaments/public/{id}/team-stats`, con las estadísticas de jugadores y equipos y la portería imbatida, cuya definición es **única**: del **equipo**, partido disputado con cero goles recibidos (prórroga incluida, tanda de penales excluida); del **portero**, identificable por `GK` en una formación táctica **publicada** (nunca se infiere), titular del primer segmento o entrante acreditado por sustitución en una formación publicada posterior, con al menos 60 minutos y sin goles recibidos; walkover y resolución administrativa no cuentan para el portero ni para la portería imbatida del equipo. Incluye el cambio no aditivo de publicar nombres de jugadores que participaron en partidos con resultado confirmado aunque no figuren en una alineación publicada (RF-033), sin publicar **plantilla inscrita**, **asistencias**, sanciones ni suspensiones. La **foto** exige inscripción **vigente** + consentimiento de imagen + foto cargada; un jugador **retirado lógicamente** nunca publica foto (iniciales) y solo la recupera al reactivarse. Ámbito por defecto decidido: **torneo completo**, con filtro por fase explícito y reversible (la pantalla todavía preselecciona la primera fase: T15 pendiente). La portería imbatida es una **estadística derivada con criterio fijo** (umbral de 60 min), no configurable: **no** es una regla de juego, no se evalúa en el motor ni en el cierre, no altera resultados, clasificación, actas, sanciones ni avance de fases, no cambia `engine_version` (2026.1) y **no declara ninguna excepción a la constitución** (la excepción a §3.2 se retiró). La **columna de posición** (`rank` compartido en los empates) está **pendiente** de esta ronda de corrección. Matriz completa en `README.md` → «Matriz de acceso (público vs. privado)»; verificación: `backend/tests/test_public_field_allowlist.py` (modelos públicos y campos sensibles de las lecturas de la spec 020), `backend/tests/test_public_access_matrix.py` (lectura anónima, `404` indistinguible y `422` de parámetros de listado, detalle, clasificación, partidos y las dos tablas de estadísticas) y, para las dos rutas de estadísticas, `backend/tests/test_public_stats_endpoints.py` (opt-in con PostgreSQL: `404` indistinguible, aislamiento entre dos organizaciones con partidos, eventos, formaciones y plantillas —también al filtrar por un `stage_id` ajeno, que devuelve lista vacía sin ampliar el resultado—, `422` de parámetros y lista cerrada con datos reales) y `backend/tests/test_public_stats.py` (puro).

- **Invitación vencida:** leer y previsualizar calculan `expired` sin escribir; crear sobre una vencida responde **201** y materializa la anterior, crear sobre una vigente **409**, crear con solo una revocada del mismo correo **201** (la unicidad solo cubre pendientes), revocar una vencida **409** sin reescribirla, reenviar la vencida la reutiliza con token y fecha nuevos, reenviar una **revocada** da **409** `INVITATION_REVOKED_RESEND` (C-1), reabrir una revocada da **200** con token y fecha nuevos sobre la misma fila (el enlace anterior deja de resolver) y aceptarla da **410**. La reapertura es la **tercera ruta de materialización** (C-2): si el mismo correo tiene otra pendiente ya vencida, se materializa y después se reabre, en una transacción; una pendiente **vigente** del mismo correo bloquea con **409** sin materializarse. Se mantiene la unicidad de pendientes por organización y correo.
- **Miembro sin rol (403):** la autorización se resuelve antes del handler. Un miembro **activo** de la organización **sin ninguna fila de rol** recibe **403** `{"detail": "Membresía o rol activo no válido"}` en `GET /organizations/current/access`, `GET /organizations/members`, `PATCH …/members/{id}/role`, `PATCH …/members/{id}/status`, `POST /organizations/invitations`, `POST …/{id}/resend`, `POST …/{id}/reopen` y `DELETE …/{id}`, también con una invitación inexistente o de otra organización; no lee ni escribe, no emite enlace, no envía correo y no audita. La respuesta `200` con rol `viewer` y `[]` solo se obtiene con el rol `viewer` asignado; el rol mostrado no concede permiso.
- **Contratos que cambian:** la aceptación de invitación no devuelve token en el cuerpo (solo cookie, sin transición); el rol mostrado sigue la precedencia dueño → administrador → operador → árbitro → observador sin alterar la autorización aditiva; el servidor devuelve las organizaciones en orden estable (nombre y, en empate, id) y el cliente (008C) restaura la última usada solo si está en la lista; el reenvío de una invitación responde **409** sin escribir ni enviar correo si ya hay **otra** pendiente vigente del mismo correo (reenviar la propia sigue siendo **200** y la renueva); **009:** reenviar una **revocada** pasa de **200** a **409** (**C-1**, `INVITATION_REVOKED_RESEND`) y la reapertura (`POST /organizations/invitations/{id}/reopen`, **200**) es la **tercera ruta de materialización** del vencimiento (**C-2**); los 409 de **crear, reenviar y reabrir** añaden el campo aditivo `code` (`INVITATION_NOT_REVOKED`, `INVITATION_OTHER_PENDING`, `INVITATION_ALREADY_ACCEPTED`, `INVITATION_REVOKED_RESEND`) y `detail` sigue siendo cadena, mientras que el 409 de **revocar una vencida** no lleva `code`; la versión del producto se declara solo en `backend/pyproject.toml` y `/docs` la lee (no es `engine_version` 2026.1); **012 H3:** `GET /matches/{id}/operation` añade a `limits` `max_minute_regular`, `max_minute_extra` (nulo sin prórroga), `extra_time_enabled` y `penalties_enabled` sin cambiar las cuatro claves existentes; `POST …/segments` y `POST …/segments/{id}/interrupt` aceptan `resolution_type` opcional (sin campo = máximo de fase), y crear segmento, interrumpir o cerrar con una resolución no habilitada responde **409** con `detail` de cadena y `code` aditivo `RESOLUTION_NOT_ENABLED`; un cliente que ignora los campos nuevos y `code` conserva su comportamiento; **012 H4:** la configuración de reglas añade `game_format` (`5v5`/`7v7`/`9v9`/`11v11`, default `11v11`), `min_players_per_team` y `max_players_per_team` (enteros ≥ 0; 0 o ausente = sin límite; `min ≤ max` solo cuando ambos > 0; cadena vacía **422**); la inscripción en fase, el alta de equipo con `stage_id` (individual y lote) y el primer segmento responden **409** con `detail` de cadena y `code` aditivo `ROSTER_SIZE_OUT_OF_RANGE`; y `PATCH /tournaments/{id}/rosters/{roster_id}/status` (`{is_active}`) es el **único endpoint nuevo** (200 idempotente, 404 entre organizaciones, 409 de bloqueo por jornada/unicidad/dorsal, sin auditoría). `engine_version` sigue en **2026.1**: el contrato cerrado no incluye estas claves; **015:** el catálogo de eventos del acta se cierra, así que una clave de primer nivel no declarada y una clave de `metadata` distinta de `red_card_type` pasan de ignorarse a **422**, `beneficiary_team_id` fuera de `own_goal` es **422** (también en un gol que lo iguala a su equipo) y `client_event_id` exige forma de UUID (**422** si no la tiene; el servidor lo normaliza a minúsculas al comparar y al escribir, y un evento histórico con identificador de texto libre sigue siendo válido); `goal` admite `assist_player_id` opcional, devuelto como UUID en `GET /matches/{id}/operation` sin nombre, solo en `goal` (**422** en los otros seis tipos, incluidos penalti y autogol), distinto del goleador (**422**) y, si no es del mismo equipo, no está en la plantilla del partido o no está en campo en el minuto del gol, **409** con `detail` de cadena y `code` aditivo `ASSIST_PLAYER_INVALID`; la regla de identificadores es única: `segment_id`, `team_id` y `beneficiary_team_id` de otra organización pasan de **409** a **404**, mientras que un jugador de otra organización o fuera de la plantilla sigue siendo **409**; el cliente actual (que solo envía campos declarados, un `client_event_id` UUID y ninguna `metadata` libre) conserva su comportamiento; **017:** el cierre aplica un **orden único de validación de dominio** de 14 pasos (ver «Arquitectura Clave») y una petición con varios defectos informa el del paso anterior, así que una resolución no habilitada se informa antes que la falta de segmento activo o de plantilla; los **422 estructurales** del esquema siguen prevaleciendo sobre cualquier paso y **no** llevan `code`; la **coherencia numérica** del marcador —final menor que el reglamentario, `regular` con final distinto del reglamentario, `penalties` sin empate y tanda igualada— pasa de **422** a **409** de dominio (`detail` cadena, sin `code`), mientras que las comprobaciones de **presencia** y el resto de **422 estructurales** no cambian; se añade el `code` aditivo `DOUBLE_YELLOW_INCONSISTENT` en **409**; `GET /matches/{id}/operation` añade `next_segment` (aditivo, anulable y de solo lectura); un cliente que ignore los campos y el `code` nuevos conserva su comportamiento salvo en esos cuatro casos de coherencia numérica y en el mensaje concreto de una petición con varios defectos; `engine_version` sigue en **2026.1** y el esquema pasó a **027** con la 016 (la 017 no trae migración); **016:** el walkover se declara con `resolution_type: "walkover"`, `winner_team_id` y un `reason` de **catálogo cerrado** (`no_show`, `withdrawal`, `insufficient_players`, `sanction`), **no** envía ninguno de los seis marcadores y **no** exige segmento activo ni plantilla: el servidor deriva el marcador de `walkover_score` de la fase y lo publica resuelto en `limits.walkover_score` (novena clave, la quinta aditiva); un marcador informado distinto de la pareja efectiva es **409** `WALKOVER_SCORE_MISMATCH`, un estado `finished`/`cancelled`/`administrative_resolution`/`suspended` **409** `WALKOVER_STATE_NOT_ALLOWED` y una pareja configurada con `winner <= loser` **409** `WALKOVER_CONFIG_INCONSISTENT` —los tres con `detail` de cadena y `code` aditivo, sin escribir—; guardar o publicar reglas con `walkover_score.winner <= walkover_score.loser` (default o en cualquier override de fase) es **422**; un cliente anterior que declarara un walkover **sin motivo** pasa a **422** y un walkover con eventos sigue siendo **422**; **018:** una expulsión por doble amarilla cuesta **una sola** sanción, así que los **partidos de suspensión** que cumple el jugador en el caso de coincidencia **bajan** (RNF-004 a), el **motivo** de una roja recién registrada pasa a ser el correcto **en el mismo cierre** (RNF-004 b), **cambia el origen de las sanciones** —antes cerrar un acta volvía a derivar el historial y podía insertar por él; desde la 018 **solo los eventos del acta que se cierra las originan** (RNF-004 c)— y el recuento `suspensions` de la auditoría del cierre pasa a ser el número de **sanciones realmente creadas** y no el de la lista derivada, así que puede bajar (RNF-004 d); **no** cambia ningún contrato HTTP —mismas rutas, mismos códigos, mismos `code` aditivos y mismos campos de respuesta—, ni la configuración, ni `schema_version`, ni `engine_version` (**2026.1**), ni el catálogo de eventos, ni el contrato cerrado, y un cliente que ignore estos cuatro puntos conserva su comportamiento (RNF-004 e); la regla y sus límites están en `specs/018-sancion-doble-amarilla/spec.md` y en «Sanciones y disciplina (spec 018)»; **019:** una clave no declarada en **cualquier** cuerpo JSON deja de ignorarse y responde **422** estructural —la misma clase que los 422 del acta, con `detail` en lista y **sin `code`**—, también en el **primer nivel de `rules_config`**, que antes la descartaba en silencio con 200/201: la configuración cierra su primer nivel y conserva intactos sus bloques anidados, sus tres mapas abiertos (parámetros de desempate, overrides por fase y contenido del bloque deprecado), el bloque deprecado `transfers` (todavía aceptado y promovido) y el ida y vuelta de la configuración guardada (RF-001, RF-002, RF-003); **la precedencia cambia**: con una clave de más el 422 del cuerpo **gana** al 403 de permiso de ruta y al 404 de recurso de otra organización, porque esas comprobaciones viven en el handler, mientras que todo lo que precede al cuerpo conserva su código —rechazos de forma del middleware (**400/413**), origen y CSRF (**403**) y dependencias: sesión (**401**), cabecera de organización (**400**), membresía con rol activo (**403**) y plataforma (**403**)— (RF-009); las **tres operaciones multipart**, los parámetros de consulta, las cabeceras y los puntos de entrada sin cuerpo quedan **fuera** (RF-006); el corte es **limpio y en un solo cambio**, sin ventana de gracia ni excepciones por ruta, con el cliente oficial corregido a la vez: un cliente que solo envía campos declarados conserva su comportamiento y el que enviara una clave de más pasa de un éxito silencioso a **422** (RNF-004): la clave aparece en la **ubicación** del error en los objetos que cierra el modelo de la petición y, en los bloques anidados de `rules_config` que ya cierra su validador, el camino va **solo en el mensaje** y la ubicación señala el bloque (RF-002, RF-010); **no** cambian los modelos de respuesta, el catálogo de eventos de la 015 —que deja de ser la única excepción cerrada y pasa a ser la primera—, los `code` aditivos de los 409, `schema_version` ni `engine_version` (**2026.1**), y el contrato interno de reglas no se toca; la regla y la precedencia están en `specs/019-endurecimiento-de-esquemas/spec.md` y en «Claves no declaradas en el cuerpo (spec 019)»
- **Claves no declaradas en el cuerpo (spec 019):** toda petición con cuerpo JSON rechaza sus **claves no declaradas** —cualquier clave que el esquema del cuerpo no declare— con **422** estructural —la clase ya existente del acta: `detail` en lista, **sin `code`** y sin devolver el valor rechazado; la clave aparece en la **ubicación** del error en los objetos que cierra el modelo de la petición y, en los bloques anidados de `rules_config`, el camino va **solo en el mensaje**—, en las **33 operaciones con cuerpo JSON** y sus **29 modelos de nivel superior** (34 modelos contando los **5** que solo aparecen anidados), **sin excepciones por ruta ni por rol**. El **primer nivel de `rules_config`** también está cerrado (antes descartaba la clave en silencio con 200/201); sus bloques **anidados** ya estaban cerrados, los tres **mapas abiertos** (parámetros de desempate, overrides por fase y el contenido del bloque deprecado) siguen admitiendo claves y `transfers` sigue aceptándose y promoviéndose. **Precedencia declarada:** con una clave de más, el 422 del cuerpo **gana** al 403 de permiso de ruta y al 404 de recurso de otra organización (comprobaciones que viven en el handler), mientras que conservan su respuesta los rechazos previos —tamaño del cuerpo y `Content-Length` (**400/413**), origen y CSRF (**403**), sesión (**401**), cabecera de organización ausente (**400**), membresía con rol activo (**403**) y administrador de plataforma (**403**)—. Las **tres operaciones multipart** quedan fuera: `POST …/rosters/bulk`, `POST …/rosters/{id}/photo` y `POST …/teams/{id}/crest`; los parámetros de consulta, las cabeceras y los puntos de entrada sin cuerpo siguen ignorando lo que no declaran. La garantía de que ningún cuerpo nuevo nace sin la regla es el barrido de `backend/tests/test_request_schema_strictness.py` (ver «Testing»); el detalle de contrato está en la entrada **019** de «Contratos que cambian».
- **Relay sin filtro de rol (riesgo aceptado):** todo miembro conectado de la organización recibe los eventos de la sala `organization:{id}`, sin filtrar por evento ni por rol. La mitigación es la revalidación de sesión, membresía y permisos cada 30 s, que desconecta el socket si cambian; el filtrado por rol exige una spec propia.
- **Estado manual de reintento (producto, no instrumentación):** `retrying` («Reintentando…»/«Retrying…») es un valor más de `RealtimeConnectionStatus`, se anuncia con `role="status"` en las tres vistas y no añade variables globales, contadores ni atributos de prueba (RNF-010). Solo lo fija la pulsación de «Reintentar» cuando `connect()` inicia un intento nuevo; cualquier transición del motor lo sustituye.
- **Arnés E2E fuera de la suite:** `frontend/e2e/` (Playwright + Chromium headless) queda fuera de `pnpm test`, que globa solo `frontend/tests/*.test.ts`, y del `typecheck` de Nuxt; se verifica con `pnpm run e2e`, `pnpm run e2e:test` y `pnpm run typecheck:e2e`. Sus artefactos van a `frontend/e2e-report/` (ignorado) y `frontend/.auth/state.json` nunca se publica. En el resumen, `states` son las **muestras** por estado y `transitions` las **transiciones** (pares consecutivos con estado distinto; `null`/`-` si el artefacto de la vista falta o está inválido); `schemaVersion` sigue en `1` y el veredicto no consulta el campo. El número de muestras `retrying` por vista es variable y **no** es un invariante del veredicto. `screenshots/` se escribe **solo** cuando el veredicto de la vista no es verde. `server.log` lleva la cabecera exacta `# server.log — docker compose logs --no-color api worker web` y está disponible solo con esa cabecera **y** al menos una línea de contenido; la integración continua solo lo reescribe cuando el arnés no lo dejó disponible. El escenario de operación y cierre recorre los tres asistentes **solo con teclado** (título enfocado, `aria-live` y error asociado con `aria-invalid`/`aria-describedby`), comprueba la equivalencia del aviso de cierre con el 409 real en la misma versión y espera siempre la **condición observable** del cambio de paso (`?step=` en la dirección) antes de la siguiente interacción.
- **Acciones auditadas:** guardar planilla, publicar/despublicar formación, asignar/retirar oficial y reabrir una invitación revocada escriben una entrada en `administrative_audit_logs` solo ante un cambio efectivo, en la misma transacción y sin datos personales (la reapertura guarda `REOPEN_INVITATION`, sin correo ni token). Crear, reenviar y revocar invitaciones no auditan; la aceptación conserva `ACCEPT_INVITATION`. Las lecturas no auditan y no hay endpoint de consulta.
- **Workspace del torneo con direcciones propias (012, H1):** `/workspace/tournaments/{id}` es configuración (resumen, reglas, fases y equipos; anclas `#resumen`, `#configuracion` y `#equipos`), `/workspace/tournaments/{id}/calendar` es el calendario (`?stage=`: crear partido, sortear/regenerar y listar con enlace a operación) y `/workspace/tournaments/{id}/rosters` es la **única** pantalla de plantillas (`?team=`: alta individual, importación CSV/ZIP, foto y consentimiento). `#calendario` y `#plantillas` redirigen con reemplazo de historial. Los asistentes de reglas, fases y equipos llevan el paso en `?step=`, que es la **única** fuente del paso (se normaliza una vez al montar con `replace` y cada cambio del usuario apila con `push`, para que el atrás vuelva al paso anterior), y los valores en `sessionStorage` por usuario, organización, torneo, versión y asistente (`bc_wizard:…`), nunca en el servidor ni en almacenamiento persistente; el borrador local del partido es un almacén aparte.
- **Visibilidad, no permisos (012, RF-038):** la entrada «Configuración» deja de ocultarse a un `viewer` y se muestra en solo lectura, igual que calendario y plantillas, sin ninguna acción de escritura. Las capacidades del miembro con permiso de gestión no cambian. Las pantallas nuevas reutilizan los endpoints existentes filtrados por organización y **no aceptan identificadores de otra organización**: `?stage=`, `?team=` y `returnTo` solo valen si están entre los datos del propio torneo ya cargados, y el retorno solo admite la operación de un partido de ese torneo.
- **Formato de juego y límites de plantilla (012 H4 + spec 024):** `game_format` (`5v5`/`7v7`/`9v9`/`11v11`, default **`11v11`**) deja de ser solo declarativo: el formato **11v11** es el único que admite formaciones tácticas gráficas (publicar/seleccionar/aplicar); en `5v5`/`7v7`/`9v9` esas operaciones se rechazan con **409** `FORMATION_NOT_SUPPORTED_FOR_FORMAT`, y un cambio de formato 11v11→otro con formación publicada se rechaza con **409** `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED` hasta despublicar. El aviso genérico «La planilla soportada es de once jugadores…» se retira; la ausencia de formación táctica no bloquea el guardado. El formato sigue sin derivar ni acotar los límites de plantilla, ni cambiar titulares ni planilla. `min_players_per_team`/`max_players_per_team` son enteros ≥ 0, **independientes del formato y sin excepciones por fase**; `0` o ausente significan «sin límite», `min ≤ max` solo se exige con ambos > 0, el cliente normaliza el campo vacío a 0 y la API rechaza la cadena vacía con **422**. Cuentan **jugadores activos** de la plantilla del equipo en el torneo y solo bloquean al inscribir en fase, al crear un equipo con `stage_id` (individual y lote) y al abrir el partido (primer segmento), con el **409** `ROSTER_SIZE_OUT_OF_RANGE`; editar la plantilla **nunca** se bloquea por tamaño. `engine_version` sigue en **2026.1**.
- **Retiro lógico y bloqueo por jornada (012, RC-1/RL-1/RA-1):** `PATCH /tournaments/{id}/rosters/{roster_id}/status` con `{is_active}` retira o reactiva sin borrar la fila y **sin auditoría**; devuelve el modelo de la lista (`player_id`, `age`, …), es idempotente y un roster de otro torneo u organización responde **404**. El **retiro** es la única excepción al bloqueo por jornada (RL-1); la **reactivación** se comporta como un alta (RA-1): **409** del bloqueo, **409** por jugador ya activo en el torneo (`uq_active_player_tournament`) y **409** por dorsal ocupado, sin cambiar filas. El histórico, las alineaciones y las respuestas públicas no cambian; la proyección interna deja de listar al retirado.
- La formación táctica solo es pública después de publicarse explícitamente desde el Workspace.
- Las versiones de torneo son inmutables una vez publicadas.
- La autorización es **RBAC por organización** (roles/permisos de la membresía) más **`match_officials` por partido**. No hay roles por torneo; `tournament_user_roles` fue retirada por la migración 019.
- El avance entre fases es **manual** y solo en versiones en borrador: `GET`/`POST`/`DELETE /tournaments/{id}/stages/{stage_id}/teams`. El sembrado automático por `stage_rank` no está soportado y el calendario no se regenera al asignar o quitar equipos.
- La migración **019** es destructiva y no tiene rollback: se despliega el código nuevo primero y la 019 después; cualquier corrección posterior es una migración nueva (*forward-fix*).
- La migración **013** está aplicada y **no se edita**: reescribió por coincidencia de texto cinco funciones de plataforma (`platform_set_user_active`, `platform_set_organization_active`, `platform_set_membership_active`, `platform_create_membership`, `requeue_outbox_events`) y la vista `v_public_match_lineups_unpublished`, y **falla en silencio** si el texto no coincide. El estado final se verifica con `backend/tests/test_migration_013_hardening.py` (opt-in con PostgreSQL) y cualquier corrección es una migración nueva (*forward-fix*).
- La migración **021** es aditiva y se aplica **antes** del código que escribe `player_out_id`/`player_in_id`; no elimina `match_segment_team_state` ni toca `init/01`.
- La migración **026** es aditiva y se aplica **antes** del código que escribe `assist_player_id`: añade la columna nula, su clave foránea compuesta con la organización y el `CHECK` del asistente, sin *backfill* y sin tocar `init/01`.
- La migración **027** es una corrección aditiva y se aplica **antes** del código que guarda el motivo del walkover: reemplaza `chk_administrative_resolution_reason` para admitir en `walkover` `NULL` o un código del catálogo, conserva la obligatoriedad y el texto libre de `administrative` y el motivo prohibido en el resto; sin columnas, índices, datos reescritos, *backfill* ni cambios en `init/01`.
- Las sustituciones se validan y aplican al **cerrar el acta** (`max_per_team`/`max_windows`/`allow_reentry`), con límites por equipo y partido. No hay API incremental de eventos ni de anulación (R11 fuera de alcance): los eventos de un acta confirmada son inmutables.
- Al desplegar, una versión **`3.2.0` ya publicada** empieza a aplicar sus límites de sustitución (la configuración efectiva sale de la versión publicada y no se reescribe); las actas cerradas no se revalidan y un partido abierto puede rechazar sustituciones antes aceptadas.
- `roster_lock_matchday` es una clave de primer nivel de `rules_config`; su valor efectivo sale de la **versión publicada**. Los minutos reglamentario y de prórroga también salen de `rules_config` (ver «Minutos»).
- No edites migraciones ya aplicadas; agrega una nueva.

## Arquitectura Clave

- **Multi-tenancy con RLS:** las tablas tenant-owned usan Row Level Security. El backend fija `app.current_organization_id` y `app.current_user_id` dentro de cada transacción.
- **Torneos:** torneos con versiones inmutables, fases componibles (Round Robin, grupos, playoffs), equipos y partidos. Puntuación, desempates, disciplina, sustituciones y ventana de inscripción se configuran con JSON; las transferencias no son configuración.
- **Actas de partido:** el cierre registra goles, tarjetas, sustituciones y suspensiones, y emite eventos al outbox.
- **Catálogo de eventos y asistencia (spec 015):** siete tipos cerrados —`goal`, `own_goal`, `penalty_goal`, `yellow_card`, `red_card`, `substitution` y `foul`— con los campos declarados por tipo, `extra="forbid"` en la raíz —esa bandera, que aquí fue la primera, **desde la 019 es la regla general de toda petición JSON** (ver «Claves no declaradas en el cuerpo (spec 019)»)— y una lista cerrada de claves en `metadata`. Compartidos: equipo, minuto, minuto añadido, segmento y tipo. `goal` añade el jugador (goleador) y el asistente opcional; `penalty_goal` y `yellow_card`, el jugador; `own_goal`, el jugador y un equipo beneficiario distinto; `red_card`, el jugador y `metadata.red_card_type` (`direct_red` por defecto o `double_yellow_red`); `substitution`, quién sale y quién entra; `foul`, solo el jugador y **sin efecto** (informativo). `client_event_id` es un UUID en todos los tipos. La **asistencia** es un campo del gol (0..1, columna propia del evento), nunca un evento aparte: es opaca para el juego —no altera marcador, clasificación, sanciones ni outbox— y no se publica en ninguna proyección ni ruta pública; la operación la devuelve como identificador y el cliente la resuelve con la plantilla del partido.
- **Sustituciones:** la configuración efectiva `substitutions` (`max_per_team`, `max_windows`, `allow_reentry`; defaults 5/3/`false`) se aplica **al cerrar el acta**. Los eventos `substitution` llevan `player_out_id`/`player_in_id` y `player_id = player_out_id`. El estado en campo se deriva del XI de `match_rosters` y de los eventos en orden `(minute, added_minute, índice)`, con una **unión de intervalos** `[entrada, salida)` por jugador para la reentrada. Los límites son por equipo y partido; una **ventana** es el grupo `(segment_id, minute, added_minute)`.
- **Proyección de contadores:** `match_segment_team_state` guarda una fila por segmento y equipo con el saldo del partido tras ese segmento. Se asegura al abrir el segmento y se recalcula al cerrar ordenando por `segment_number` (nunca por minuto); el `GET` de operación calcula sin escribir.
- **Minutos (regla única, RF-031…RF-037):** `regular_time_minutes`/`extra_time_minutes` salen de `stage_defaults` con overrides por fase (defaults **90**/**120**) y se resuelven clave por clave, así que un override parcial solo cambia lo que declara. Al guardar se valida la pareja: reglamentario 1..179; con la prórroga habilitada, extra > reglamentario y ≤ 180; deshabilitada, el extra no se valida ni se materializa. El **máximo efectivo** es el reglamentario para `regular`, `walkover` y `administrative`, y el de prórroga para `extra_time`/`penalties` cuando la prórroga está habilitada; el tiempo añadido se cuenta dentro de ese máximo (`minute + added_minute`), con descuento solo en el minuto final, y los topes estructurales 180/30 no son regla de negocio. La **resolución prevista** se elige con un único control en la operación (por defecto `regular`), se muestra y se valida contra ese máximo y el tope de minuto añadido, vive solo en la sesión de la pestaña, se restaura al recargar y se envía al crear o interrumpir segmentos y al cerrar; sin `resolution_type` el servidor conserva el máximo de la fase. `GET …/operation` publica en `limits` las cuatro claves existentes más `max_minute_regular`, `max_minute_extra` (nulo sin prórroga), `extra_time_enabled` y `penalties_enabled`. Una resolución no habilitada (`extra_time` sin su indicador, `penalties` sin el suyo) responde **409** `RESOLUTION_NOT_ENABLED` —`detail` cadena y `code` aditivo— al crear segmento, al interrumpir y al cerrar, sin escribir; las actas cerradas y las versiones publicadas no se revalidan y no hay campos de duración nuevos en el modelo. La duración se presenta como el minuto en que termina el encuentro, no como tiempo jugado.
- **Cierre del acta (spec 017):** un **único orden de validación de dominio** de 14 pasos: (1) sesión y organización —la carga del partido resuelve existencia y aislamiento con **404** antes del permiso y no cuenta como paso—; (2) permiso `CLOSE_MATCH_REPORT` **y**, a la vez, rol `owner`/`administrator`/`operator` **o** estar asignado en `match_officials` (la resolución administrativa exige además dueño o administrador) y sin él, **403**; (3) estado no terminal, ni `suspended`, y versión publicada; (4) dos equipos participantes; (5) resolución habilitada por la configuración efectiva; (6) estructura del acta: segmento activo (**409** sin él, RF-017), segmentos, tiempos, intervalo y máximo efectivo (un segmento que no es de ese partido → **404**); (7) participantes y plantilla (`team_id` o beneficiario de otra organización → **404** antes del **409** de participantes; un jugador de otra organización o fuera de la plantilla → **409**); (8) estado en campo y sustituciones; (9) asistente del gol; (10) coherencia disciplinaria; (11) marcador frente a eventos; (12) sanciones vigentes; (13) coherencia de la resolución y del ganador; (14) escritura atómica. Entre defectos de dominio gana el del paso anterior y un fallo en cualquier paso no escribe eventos, contadores, marcador, clasificación, avance, sanciones, auditoría ni outbox. **Excepción declarada:** los **422 estructurales** del esquema (claves y campos no aplicables, rangos del modelo, `client_event_id` duplicado en el acta, más de 500 eventos) se resuelven antes del handler, prevalecen sobre cualquier paso y no llevan `code`. El paso 5 precede a «sin segmento activo» y a la plantilla, así que una resolución no habilitada se informa antes que esos dos defectos. El walkover (spec 016) no se toca en la 017.
- **Marcadores del cierre (spec 017):** el gol reglamentario se decide con `minute <= regular_time_minutes` y el minuto añadido no interviene en esa clasificación. La **matriz por resolución**: `regular` exige el reglamentario, el final es opcional y debe igualarlo, y prohíbe penales, goles posteriores al reglamentario y `reason`; `extra_time` exige reglamentario y final, con final ≥ reglamentario y ganador; `penalties` exige final igual al reglamentario (empate) y tanda con ganador; `administrative` exige final igual al reglamentario, ganador y `reason` (la columna es `resolution_reason`); `walkover` no pasa por esa matriz: la rama toma el ganador declarado, deriva la pareja de `walkover_score` y **omite** los seis marcadores de la petición (spec 016, ver «Walkover (spec 016)»). La **presencia** de la pareja reglamentaria, del final que exige cada resolución, de los penales, del ganador y de `reason` es **422** del esquema; la **coherencia numérica** —final menor que el reglamentario, `regular` con final distinto del reglamentario, `penalties` sin empate y tanda igualada— es **409** de dominio, con `detail` cadena y sin `code` (antes era **422**), igual que un ganador informado distinto del calculado. El resultado se calcula con los eventos de la **petición** **antes de escribir** (paso 13): un acta inválida no deja ninguna fila y la reutilización idempotente de un evento ya persistido hace equivalente el cálculo a lo que se escribiría.
- **Doble amarilla (spec 017):** una `red_card` con `metadata.red_card_type = double_yellow_red` exige **exactamente dos** amarillas previas del mismo jugador en el mismo partido, contadas en el orden canónico `(minute, added_minute, índice del acta)` y solo entre los eventos de la petición (el acta del partido). Cero, una o tres o más es **409** con `detail` cadena —el minuto, sin nombres— y `code` aditivo `DOUBLE_YELLOW_INCONSISTENT`, en el paso 10 y sin escribir. La roja directa no se ve afectada, una segunda amarilla no deriva en roja y las actas cerradas no se revalidan: un acta abierta que incumpla la regla deja de poder cerrarse.
- **Sanciones y disciplina (spec 018):** una **jugada** —una expulsión por doble amarilla— produce **exactamente una** sanción: la acumulación de sus amarillas **se absorbe** (RF-001, RF-002). La absorción se aplica al final sobre toda el acta y **por jugador**, así que alcanza a **todos** los umbrales que crucen sus amarillas en ese acta —la primera o la última, y también dos umbrales—; nunca a la acumulación de otro jugador ni a la de un acta anterior, y **no** alcanza a la roja directa, que conserva sus dos sanciones (RF-009). La duración es la **única de sanción por expulsión** (`direct_red_suspension_matches` de la configuración efectiva de la versión publicada), aplicada **una sola vez**: la acumulación no la alarga (RF-003). Ninguna amarilla se descuenta —la que provoca la roja **sigue contando** para umbrales posteriores— y el contador no se reinicia con la roja (RF-004). **Solo los eventos del acta que se cierra originan sanciones**; el historial disciplinario **solo cuenta amarillas y empareja** y nunca crea, corrige ni duplica una fila (RF-005, RF-006). La unicidad es **por evento de roja y con cualquier motivo**, comprobada **aparte** de la identidad torneo+jugador+evento+motivo: una lectura acotada a las rojas del acta —que **no se ejecuta** si no hay ninguna— descarta la sanción de un evento que ya tiene fila, aunque esté guardada con el motivo heredado, y no la reescribe. El tipo de roja se lee de `metadata.red_card_type` **también en el cierre que la registra** (el `RETURNING` del `INSERT` de eventos devuelve `metadata`) y nunca del número de amarillas (RF-010). El historial se ordena con un **orden total y estable** construido solo con datos persistidos —el partido por su fecha de juego y, en empate o sin fecha, por su identificador; después minuto, minuto añadido e identificador del evento—, **sin migración** ni columna nueva: el esquema está en **031** (ver «Runtime»; la 018 no trae migración). El recuento que la auditoría del cierre guarda en `suspensions` es el de las **filas realmente creadas** (`RETURNING id`), no el tamaño de la lista derivada (RF-012). **No cambian** el orden de 14 pasos, la coherencia de la doble amarilla (`DOUBLE_YELLOW_INCONSISTENT`), el walkover (no genera ni sirve sanciones; su auditoría conserva `suspensions: 0`), la roja directa junto a un umbral (dos sanciones), el catálogo de eventos, las claves de `discipline` ni la inmutabilidad del acta confirmada. La absorción es **por jugador dentro del acta** porque el paso 8 de la 017 rechaza una amarilla posterior a la roja del mismo jugador; si algún día se permitiera, la absorción sería más amplia que «las amarillas que componen la expulsión». La regla es **fija en el motor**, sin clave de configuración: la excepción acotada a §3.2 está declarada en `specs/018-sancion-doble-amarilla/spec.md`. La disciplina no forma parte del contrato cerrado: `engine_version` sigue en **2026.1** y `docs/contrato-reglas.md` no cambia.
- **Walkover (spec 016):** `resolution_type = "walkover"` con `winner_team_id` obligatorio que debe ser uno de los dos participantes (si no, **409** sin `code`, mensaje del motor) y `reason` de **catálogo cerrado** (`no_show`, `withdrawal`, `insufficient_players`, `sanction`), obligatorio y guardado como código en `resolution_reason` (migración **027**); **no** hay texto libre, campo nuevo ni transición de estado. Se admite en los estados que ya admiten cierre (`scheduled`, `live`) siempre con la versión **publicada**; los cuatro inadmisibles responden **409** `WALKOVER_STATE_NOT_ALLOWED` y la autorización es la **misma conjunción** del cierre (`CLOSE_MATCH_REPORT` **y** rol operativo o estar en `match_officials`), sin permisos nuevos. La rama se inserta **después del paso 5 y antes de la plantilla**, así que **omite** los pasos 6-12: no exige segmento activo ni planilla (un equipo puede no presentarse), no valida tiempos, sustituciones, doble amarilla, marcador contra eventos ni sanciones, y no toma bloqueos de jugador; el orden de bloqueo no cambia (fase → versión → destinos → partido → segmento). El marcador se **deriva** de `walkover_score` de la configuración efectiva (default 3-0 y override de fase) en el orden participación del ganador → pareja incoherente (`WALKOVER_CONFIG_INCONSISTENT`) → marcador informado distinto (`WALKOVER_SCORE_MISMATCH`) y lo revalida `compute_match_outcome`; la misma pareja se publica en `limits.walkover_score`. Los marcadores de juego son **opcionales** y se **ignoran** si coinciden con la pareja (compatibilidad con un cliente anterior); uno distinto es **409** y un marcador de penales es **422** porque solo aplica a `penalties`. Un walkover **no admite eventos** (**422**). Escritura: `status='finished'`, `result_confirmed`, reglamentario y final iguales a la pareja derivada, penales nulos, `winner_team_id`, clasificación recalculada (jugado, ganado/perdido, puntos y goles), avance de llave, **sin** eventos, **sin** proyección por segmento y **sin** servir ni crear sanciones; un segmento activo queda `completed` con `minute_end = minute_start` (los completados e interrumpidos no se tocan, y sin segmentos no se crea ninguno). Auditoría `CLOSE_MATCH_REPORT` con `resolution_reason` en la raíz y los **mismos tres** eventos de outbox. La pantalla no exige segmento ni planilla con esta resolución, pide ganador y motivo, muestra el marcador efectivo en solo lectura, no envía los seis campos y no bloquea el cambio por segmentos fuera del máximo (D-13). `engine_version` sigue en **2026.1**: `walkover_score` es configuración aditiva fuera del contrato cerrado.
- **Segmentos y propuesta (spec 017):** un segmento es una **ventana de tiempo** con número consecutivo, `minute_start`, `minute_end` opcional y estado `active`/`completed`/`interrupted`; **no** es una mitad ni un periodo reglamentario y un partido puede tener cualquier número, incluido uno. Crear un segmento con otro activo cierra el activo en su minuto; un número no consecutivo, o un inicio anterior al final del segmento anterior (cuando lo tiene) o al inicio del activo, responde **422**, y un partido terminado **409**. Interrumpir guarda motivo y minuto y cierra el segmento; reanudar exige un segmento nuevo. `GET /matches/{id}/operation` devuelve `next_segment` —`{segment_number, minute_start, derived}` o `null`— calculado con los segmentos e interrupciones que ya lee: sin segmentos `{1, 0, true}`; último interrumpido → su minuto; último completado con fin → su fin; último activo sin interrupción o completado sin `minute_end` → `{n+1, null, false}`; `null` en partido terminal o versión no publicada, y `suspended` sí propone. Es aditivo y de solo lectura (`GET` no escribe), el servidor sigue siendo la autoridad al crear y el cliente ya no calcula el número: solo prerrellena el minuto si es derivado y el operador no lo ha editado.
- **Contrato interno:** `docs/contrato-reglas.md` (`engine_version` 2026.1) fija `GF1`/`GF2` y las cuatro formaciones; no se configura desde el editor y **no incluye** `game_format`, los límites de plantilla, el catálogo de eventos del acta ni la asistencia, que son configuración y contrato aditivos fuera de ese contrato cerrado (spec 015: `engine_version` sigue en 2026.1).
- **Outbox + worker + Redis:** los eventos se procesan de forma asíncrona y alimentan el tiempo real con Socket.IO. El stream es transporte de mejor esfuerzo con un tope fijo de 10 000 entradas aproximado; no es duradero ni la fuente de verdad.
- **Autenticación y autorización:** email/password y **acceso con Google por redirección** (ningún token del proveedor pasa por el navegador). `POST /auth/google/start` guarda el intento en Redis (`sha256(state)`, TTL 600 s) y fija la cookie `bc_oauth_state` (`HttpOnly`, `SameSite=Lax`, `Path=/api/v1/auth/google`, `Max-Age=600`), devolviendo la URL del proveedor; `GET /auth/google/callback` consume el estado con `GETDEL`, canjea el código en el servidor (presupuesto 10 s), valida emisor, audiencia, vigencia, sujeto, correo verificado y nombre, y emite la sesión existente. `GET /auth/session` rehidrata `{user_id, organization_id}` (primera organización del orden estable), `GET /auth/google/status` publica solo `{enabled}` y `GET /auth/google/link` solo `{linked}`. La vinculación (`flow=link`, desde `/account/google`) no emite ni revoca sesión y nunca reescribe `users.email`; un identificador de otra cuenta responde `LINK_IDENTITY_TAKEN`. El camino anterior `POST /auth/google` responde **410** `GOOGLE_IDENTITY_INVALID` sin leer el cuerpo. Una sesión sin organización usa la pantalla opcional `POST /organizations` (201; `409` sin `code` si ya tiene una; `409 ORGANIZATION_SLUG_TAKEN` si el identificador está ocupado). Firma del `id_token` no verificada (D-9: llega del canje por TLS). RBAC por organización: los permisos se resuelven por la membresía y sus roles; no hay ámbito por torneo ni roles por torneo. La única delegación menor es por partido con `match_officials`.
- **Log de acceso saneado:** la API arranca con `--no-access-log` en desarrollo y producción; el middleware de `app/core/access_log.py` emite una línea `access method=… path=… status=…` por petición, sin consulta, fragmento, cabeceras ni cuerpo. Cubre también los rechazos de CSRF/tamaño y, ante una excepción no controlada, registra 500 y la relanza.
- **Origen de las escrituras:** toda escritura valida `Origin` y `Referer` por separado (`backend/app/core/csrf.py`). Sin ninguna de las dos se admite; si cualquiera está presente y no es un origen permitido, **403**, aunque la otra sí lo esté. Un `Referer` vacío o no parseable se rechaza; un proxy que lo reescriba a un host interno debe permitir ese origen o retirar la cabecera.
- **Avance manual entre fases:** `GET`/`POST`/`DELETE /tournaments/{id}/stages/{stage_id}/teams` en versiones en borrador. `POST` es atómico (1..64 equipos, sin duplicados); 201 si hay altas, 200 si todos ya estaban, 204 en la retirada idempotente; 403/404/409/422 según el contrato. No regenera el calendario ni resuelve `phase_slots` entre fases.
- **Estructura publicada:** los triggers impiden modificar la estructura de una versión publicada o archivada. El trigger de estructura lanza el SQLSTATE **`ZZ409`**; la API lo mapea a **409** por código, sin comparar el texto.
- **Bloqueo y rendimiento:** fase → versión → partido(s) → segmentos → jugadores. El cierre serializa por fase; es una garantía de corrección, no se midió throughput ni latencia (RNF-003).
- **API pública:** `/api/v1/tournaments/public`, `/api/v1/tournaments/public/{id}`, `/api/v1/tournaments/public/{id}/standings`, `/api/v1/tournaments/public/{id}/matches`, `/api/v1/tournaments/public/{id}/player-stats` y `/api/v1/tournaments/public/{id}/team-stats`.
- **Fotos:** se firman en lote, con un cliente cacheado por proceso y endpoint de firma, siempre después de cerrar la transacción. El público degrada a `photo_url: null`, el Workspace responde 503 y se registra una sola entrada por respuesta.
- **Escudos de equipo (spec 014):** una imagen por **equipo**, compartida entre los torneos donde se inscribe y gestionada solo desde el torneo que contiene su inscripción con `MANAGE_TOURNAMENTS` (el `viewer` solo consulta). El contrato es `GET`/`POST`/`DELETE /api/v1/tournaments/{id}/teams/{team_id}/crest` (`200`/`200`/`204`), con `TeamCrestResponse` `{team_id, crest_url, logo_url}`: `crest_url` es un enlace firmado temporal (300 s por defecto) y nunca se devuelve `crest_object_key`. `teams.crest_object_key` guarda la referencia y `logo_url` se retira (`null`) con la primera carga confirmada, sin restituirse al eliminar; en el Workspace es el respaldo mientras no haya escudo y en público **nunca** se muestra. La visibilidad pública sale de `public.v_public_tournament_teams` (`security_barrier`, `GRANT SELECT` solo a `bracket_app`; misma condición que `v_public_tournaments`), que alimenta `teams` del detalle público, `crest_url` de la clasificación, los dos escudos de los partidos y las alineaciones; la operación del partido devuelve además `match.home_team_logo_url`/`away_team_logo_url` como respaldo del Workspace (nunca en público). Códigos aditivos: `CREST_FILE_EMPTY`, `CREST_FORMAT_UNSUPPORTED`, `CREST_ANIMATION_UNSUPPORTED`, `CREST_TOO_LARGE` (422), `CREST_NOT_FOUND` (404), `CREST_FORBIDDEN` (403), `CREST_UPLOAD_FAILED` (500) y `CREST_STORAGE_UNAVAILABLE` (503); el miembro sin rol conserva el 403 de contexto sin código. Validación **declarada**: JPG/PNG/WEBP estáticos, máximo de imagen compartido con las fotos, contenido sobre extensión y animación detectable en el contenedor; no se decodifica, así que un archivo truncado con cabecera válida se acepta y los metadatos se sirven tal cual. Sin consentimiento (no es dato personal) y sin eventos de dominio. **Riesgos aceptados:** huérfanos sin recolección ni cuota, metadatos no eliminados, animación/truncamiento no garantizados, enlaces no revocables durante su TTL y `logo_url` externa en el Workspace. **Orden de despliegue: 024 → 025 → código** (la 024 es del PR de Google).
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

### Migración 026 (asistencia del gol)

La **026** es **aditiva** y se aplica **antes** del código que escribe `assist_player_id`: añade a `public.match_events` la columna `assist_player_id UUID` nula (sin default ni índice), la clave foránea compuesta `(assist_player_id, organization_id)` a `players(id, organization_id)` con `ON DELETE RESTRICT` y `chk_match_event_assist`. El `CHECK` se añade **validado** (no `NOT VALID`), porque la columna nace nula y no hay filas históricas que lo incumplan; solo cubre lo que la base puede probar —la asistencia existe únicamente en `goal` y nunca repite al goleador—, mientras que el mismo equipo, la plantilla del partido y la presencia en campo son autoridad de la API (**409** `ASSIST_PLAYER_INVALID`). No reescribe filas, no hace *backfill* (un gol sin asistente sigue siendo válido antes y después), no toca `init/01` ni `init/02`, no añade políticas ni grants y conserva la RLS de `match_events`.

```sh
MIGRATION_TARGET=026 $COMPOSE run --rm db-migrate
```

**Orden: migración 026 → código.** El código nuevo escribe `assist_player_id` en cada acta y contra el esquema 025 falla por columna inexistente; la imagen anterior ignora la columna nula y sigue cerrando actas. **No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). Va **después** de la 025 y el volumen limpio (`init/00-03` → 001-026) termina con el mismo esquema que una base migrada (`backend/tests/test_migration_026.py`, opt-in con PostgreSQL).

### Migración 027 (motivo del walkover)

La **027** es una migración **correctiva y aditiva** que solo **relaja** una restricción existente: reemplaza `chk_administrative_resolution_reason` en `public.matches` por una versión que admite, en `walkover`, `NULL` (filas históricas y un despliegue en el que la migración llegue antes que el código) o uno de los cuatro códigos del catálogo cerrado (`no_show`, `withdrawal`, `insufficient_players`, `sanction`), conserva en `administrative` el motivo obligatorio de 1..1000 caracteres y sigue prohibiendo el motivo en `regular`, `extra_time` y `penalties`. No añade columnas, índices, políticas, RLS ni grants, no reescribe filas y no toca `init/01`. La **obligatoriedad** y el **catálogo** siguen siendo autoridad de la API (RF-007): la base no exige motivo en un walkover.

```sh
MIGRATION_TARGET=027 $COMPOSE run --rm db-migrate
```

**Orden: migración 027 → código.** El código nuevo escribe un motivo no nulo en `resolution_reason` y contra el esquema 026 el `UPDATE` violaría la restricción, así que el cierre respondería un 409 de integridad engañoso; la imagen anterior convive con la 027 sin cambios (sigue escribiendo `NULL`). **No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). El volumen limpio (`init/00-03` → 001-027) termina con el mismo esquema que una base migrada (`backend/tests/test_migration_027.py`, opt-in con PostgreSQL).

### Migraciones 028, 029, 030 y 031 (estadísticas públicas y proyecciones públicas)

La **028** (spec 021) es aditiva y recrea `public.v_public_match_lineups_unpublished` añadiendo `segment_number` (entero, nulo en la planilla y con valor en la formación) para etiquetar la alineación pública con su segmento; se aplica **antes** del código que lee el campo. Las **029, 030 y 031** (spec 022) también son aditivas, **no reescriben datos** y **no tienen *backfill***: ninguna toca `init/01` ni `init/02`, no añaden políticas de RLS y no cambian `engine_version` (2026.1).

- **029:** recrea `public.v_public_tournaments` con `organization_id` como última columna de salida (columna **interna**, fuera de todo modelo de respuesta) para que el backend fije el contexto RLS al servir lecturas públicas. `CREATE OR REPLACE VIEW` conserva `security_barrier`, propietario y privilegios; no añade tablas, columnas de tablas base, filas, políticas ni índices.
- **030:** crea `public.v_public_match_events`, `public.v_public_match_segments` y `public.v_public_tournament_rosters` (`security_barrier`, `REVOKE ALL … FROM PUBLIC` y `GRANT SELECT` solo a `bracket_app`), filtradas por organización activa, torneo en estado público y versión publicada. Las leen las dos rutas de estadísticas.
- **031:** crea `public.v_public_match_formations` (`security_barrier`, `REVOKE` de `PUBLIC` y `GRANT SELECT` solo a `bracket_app`) con **todas** las formaciones tácticas publicadas por partido, segmento y equipo (jugador, `position_slot`, titular y `segment_number`). Es una **proyección interna**: solo la lee `GET /tournaments/public/{id}/player-stats` para el cálculo de la portería imbatida; no es contrato público y no la expone ningún modelo de respuesta.

```sh
MIGRATION_TARGET=029 $COMPOSE run --rm db-migrate
MIGRATION_TARGET=030 $COMPOSE run --rm db-migrate
MIGRATION_TARGET=031 $COMPOSE run --rm db-migrate
```

**Orden: 029 → 030 → 031 → código.** Las dos rutas nuevas leen `organization_id` de `v_public_tournaments` (029) y consultan las vistas de la 030; contra el esquema 028 fallan por columna o relación inexistente. La imagen anterior convive con las tres sin cambios (no lee las vistas nuevas ni selecciona la columna nueva), así que no hace falta detener `api` ni `worker`. **Smoke:** `GET /docs`, una lectura pública de torneo, las dos tablas de estadísticas (`player-stats`/`team-stats`, con `404` indistinguible en un torneo no visible) y la operación de un partido del Workspace. **No hay rollback**: cualquier defecto se corrige con una migración nueva (*forward-fix*). El volumen limpio (`init/00-03` → 001-031) termina con el mismo esquema que una base migrada (`test_migration_028.py` y `test_migration_031.py`, opt-in con PostgreSQL; las pruebas de migración de la 029 y la 030 están pendientes, T1). Runbook y smoke detallados en `README.md`.

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
- **Migración 025:** aditiva; añade `teams.crest_object_key` (`TEXT` nula) y la vista `public.v_public_tournament_teams` (`security_barrier`, `GRANT SELECT` a `bracket_app` y `REVOKE` de `PUBLIC`). No toca `init/01`, `init/02` ni las migraciones 001–023 y no tiene *backfill*. Se aplica **antes** del código y **después** de la 024 con `MIGRATION_TARGET=025`; sin rollback (*forward-fix*). Runbook y smoke en `README.md`.
- **Migración 026:** aditiva; añade `match_events.assist_player_id` (`UUID` nula), la clave foránea compuesta `(assist_player_id, organization_id)` a `players` (`ON DELETE RESTRICT`) y `chk_match_event_assist` (solo en `goal`, distinto del goleador), validado. Sin índice, sin *backfill*, sin tocar `init/01` ni la RLS. Se aplica **antes** del código y **después** de la 025 con `MIGRATION_TARGET=026`; sin rollback (*forward-fix*). Runbook en `README.md`.
- **Migración 027:** correctiva y aditiva; reemplaza `chk_administrative_resolution_reason` en `matches` para que `walkover` admita `NULL` o un código del catálogo, con `administrative` igual y `regular`/`extra_time`/`penalties` sin motivo. Sin columnas, índices, grants, políticas, RLS ni filas reescritas, sin tocar `init/01` y sin *backfill*. Se aplica **antes** del código y **después** de la 026 con `MIGRATION_TARGET=027`; sin rollback (*forward-fix*). Runbook en `README.md`.
- **Migración 028:** aditiva (spec 021); recrea `v_public_match_lineups_unpublished` y su envoltorio `v_public_match_lineups` con `segment_number` (`INT` nulo en la planilla). Sin tablas, columnas de tabla base, filas, políticas ni grants nuevos; conserva `security_barrier` y el orden `published_at DESC, segment_number DESC, id DESC`. Se aplica **antes** del código que lee el campo, **después** de la 027, sin *backfill* ni rollback (*forward-fix*).
- **Migración 029:** aditiva; añade `organization_id` como última columna de `public.v_public_tournaments` (columna interna, fuera de los modelos de respuesta) para fijar el contexto RLS en las lecturas públicas. Sin tablas, columnas de tablas base, filas, políticas, grants ni índices; conserva `security_barrier`. Se aplica **antes** del código y **después** de la 028 con `MIGRATION_TARGET=029`; sin rollback (*forward-fix*).
- **Migración 030:** aditiva; crea `public.v_public_match_events`, `v_public_match_segments` y `v_public_tournament_rosters` (`security_barrier`, `GRANT SELECT` solo a `bracket_app` y `REVOKE` de `PUBLIC`). Las dos rutas de estadísticas las leen. Sin *backfill*, sin tocar `init/01` ni `init/02`. Se aplica **antes** del código y **después** de la 029 con `MIGRATION_TARGET=030`; sin rollback (*forward-fix*).
- **Migración 031:** aditiva; crea `public.v_public_match_formations` (`security_barrier`, `GRANT SELECT` solo a `bracket_app` y `REVOKE` de `PUBLIC`) con **todas** las formaciones publicadas por partido, segmento y equipo. Es una **proyección interna** que solo consume la ruta pública de estadísticas de jugadores (alimenta el cálculo de la portería imbatida) y que no aparece en ningún modelo de respuesta. Sin *backfill*. Se aplica **antes** del código y **después** de la 030 con `MIGRATION_TARGET=031`; sin rollback (*forward-fix*). Runbook y smoke de 029–031 en `README.md`.
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
- **Formularios:** usan los tokens y clases base de `frontend/app/assets/css/main.css` (`.field`, `.field-grid`, `.field-error`, `.field-hint`) y los componentes `frontend/app/components/ui/FormField.vue` / `FieldError.vue`. Todo input con error lleva `aria-invalid="true"` y `aria-describedby` apuntando al hint y al error; los mensajes de validación se centralizan en i18n (`validation.*`) y el grid colapsa a una columna bajo 760px. El slot prop `ariaInvalid` de `FormField.vue` es `'true' | undefined`; al enlazarlo con `:aria-invalid` hay que normalizarlo a boolean (`ariaInvalid ? true : undefined`), porque `vue-tsc` exige `Booleanish`.
- **Nuevos módulos backend:** crea el módulo bajo `backend/app/modules/` y registra su router en `backend/app/main.py`.
- **Vistas públicas:** no agregues campos sensibles (documentos, fechas de nacimiento) a las proyecciones públicas.
- **Sustituciones:** en un evento `substitution` deben venir `player_out_id` y `player_in_id` no nulos y distintos, con `player_id = player_out_id`; en cualquier otro tipo, ambos nulos. El incumplimiento estructural es **422** y las reglas de negocio (equipo, plantilla, campo/banca, reentrada, límites, ventanas, minutos) son **409**. La comprobación coincide con `chk_match_event_substitution_pair` (021).
- **Actas cerradas inmutables:** el resultado confirmado lo protege `trg_protect_confirmed_match_result` (016) y los eventos de un acta confirmada no se editan ni se anulan (`trg_validate_match_event_context`, 009, bloquea `INSERT`/`UPDATE` en `finished`, `cancelled` y `administrative_resolution`). No existe API incremental de eventos ni de anulación (R11 fuera de alcance); `is_voided` es legado y no es una vía operativa. La 017 no añade ninguna ruta de corrección ni de reapertura: la operación muestra «Acta cerrada: no se puede editar» (`role="status"`) y mantiene las acciones de escritura deshabilitadas.
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

- **Escudos de equipo y migración 025 (opt-in):** requieren PostgreSQL; cubren la forma y privilegios de `teams.crest_object_key`, la vista pública (borrador, sin versión publicada y organización inactiva fuera), el ciclo cargar/reemplazar/eliminar con auditoría, la autorización real con un rol `viewer`, la compensación y la concurrencia.

  ```sh
  cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
    pytest -q tests/test_migration_025.py tests/test_crest_service.py tests/test_crest_endpoints.py tests/test_crest_public.py tests/test_crest_surfaces.py
  ```

- **Catálogo de eventos, asistencias y migración 026 (opt-in parcial):** `tests/test_match_events_contract.py` y `tests/test_match_assists.py` son puros y corren en `pytest -q`; con PostgreSQL y `DATABASE_ADMIN_URL`, `test_migration_026.py` construye la cadena limpia y el salto 025 → 026 y comprueba columna, FK y `CHECK`, y `test_match_assists_db.py` cubre el cierre con asistencia, el **409** `ASSIST_PLAYER_INVALID`, la idempotencia con `metadata` y asistente, la regla única de identificadores (404 para segmento, equipo o beneficiario; 409 para jugador) y que la asistencia no altera marcador, puntos ni sanciones.

  ```sh
  cd backend && pytest -q tests/test_match_events_contract.py tests/test_match_assists.py
  cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
    pytest -q tests/test_migration_026.py tests/test_match_assists_db.py
  ```

- **Walkover y migración 027 (opt-in parcial):** `tests/test_walkover.py`, `tests/test_walkover_close.py` y `tests/test_close_validation_order.py` son puros y corren en `pytest -q`; con PostgreSQL y `DATABASE_ADMIN_URL`, `test_migration_027.py` construye la cadena limpia y el salto 026 → 027, y `test_match_resolution_db.py` cubre el walkover sin segmento y sin plantilla, el marcador derivado, el efecto publicado (clasificación y avance, sin sanciones), los tres 409 con `code`, el acta confirmada y la concurrencia.

  ```sh
  cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
    pytest -q tests/test_migration_027.py tests/test_match_resolution_db.py
  ```

- **Estadísticas públicas y migraciones 028–031 (spec 022, opt-in parcial):** `tests/test_public_stats.py` es **puro** (sin base ni reloj) y corre en `pytest -q`; cubre el cálculo de las dos tablas, la definición de la portería imbatida (equipo y portero, umbral de 60 min, `GK` en formación publicada, walkover y administrativa fuera) y que una formación con `is_public` falso no atribuye portería. Con PostgreSQL y `DATABASE_ADMIN_URL`, `test_migration_028.py` y `test_migration_031.py` construyen la cadena limpia y el salto correspondiente y comprueban columnas, `security_barrier`, `GRANT SELECT` a `bracket_app` y `REVOKE` de `PUBLIC` (las pruebas de migración de la **029** y la **030** están pendientes, T1); `test_public_stats_endpoints.py` cubre las **dos rutas** de estadísticas con datos reales (`404` indistinguible, aislamiento entre dos organizaciones **con partidos, eventos, formaciones y plantillas** y recuentos exactos, `stage_id` ajeno → lista vacía, `422` de parámetros y lista cerrada de campos). `tests/test_public_access_matrix.py` incluye esas dos rutas desde T18 en sus casos de lectura anónima, `404` indistinguible y `422` de parámetros, junto al listado, el detalle, la clasificación y los partidos.

  ```sh
  cd backend && pytest -q tests/test_public_stats.py
  cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
    pytest -q tests/test_migration_028.py tests/test_migration_031.py tests/test_public_stats_endpoints.py
  ```

- **Sanciones y disciplina (spec 018, opt-in parcial):** `tests/test_sanctions.py` es **puro** (sin base y sin reloj) y corre en `pytest -q`: cubre la derivación y la absorción —primera o última amarilla, dos umbrales, umbral histórico, otro jugador—, la duración de expulsión, el tipo de roja desde `metadata`, el contador que no se reinicia, el determinismo, el orden del historial y `drop_recorded_red_sanctions`. Con PostgreSQL y `DATABASE_ADMIN_URL`, `tests/test_sanctions_db.py` cubre el cierre real: absorción y duración configurada, el motivo de la roja registrada en ese mismo cierre, los partidos cumplidos, el acta posterior sin tarjetas que no crea filas, la roja histórica mal etiquetada que no se duplica ni se reescribe, el evento de roja ya sancionado, el recuento auditado frente a `count(*)`, el aislamiento por organización, el reinicio de fase y el **409** `DOUBLE_YELLOW_INCONSISTENT` sin escritura.

  ```sh
  cd backend && pytest -q tests/test_sanctions.py
  cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" \
    pytest -q tests/test_sanctions.py tests/test_sanctions_db.py
  ```

- **Endurecimiento de esquemas de petición (spec 019):** `tests/test_request_schema_strictness.py` es **puro** (sin base y sin opt-in) y corre en `pytest -q`: deriva de las rutas y de la app el barrido de las **33 operaciones con cuerpo JSON** —sus **29 modelos de nivel superior** + **5 anidados** = **34**; las **3 multipart** quedan fuera—, comprueba la bandera y el rechazo de cada modelo, la **precedencia por capas** (el 422 del cuerpo gana al 403 de permiso de ruta y al 404 de recurso ajeno; los rechazos previos conservan su código) y la forma saneada del 422 (`detail` en lista `type`/`loc`/`msg`, sin `code` ni eco del valor). `tests/test_rules_config_compat.py` (puro) cubre el **primer nivel** de `rules_config` cerrado, `transfers` todavía aceptado y promoviéndose, deriva de `RULES_SCHEMA` los **bloques cerrados**, inyecta una clave extra en cada uno (10 rutas, incluidos `discipline.fair_play_penalties` y el `walkover_score` del override por fase) y exige el rechazo de su **validador propio** (motor, modelo de petición y frontera 422), con un guardián que falla si nace un bloque cerrado sin caso, y comprueba la aceptación de los **tres mapas abiertos** de RF-004 (parámetros de desempate, índice de `stage_overrides` y contenido del bloque deprecado); `tests/test_match_events_contract.py` cubre la no regresión del catálogo de la 015.

  ```sh
  cd backend && pytest -q tests/test_request_schema_strictness.py tests/test_rules_config_compat.py tests/test_match_events_contract.py
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
