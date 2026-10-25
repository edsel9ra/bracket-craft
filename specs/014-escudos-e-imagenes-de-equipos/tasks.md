# Tareas 014 — Escudos e imágenes de equipos

Spec: `specs/014-escudos-e-imagenes-de-equipos/spec.md` (aprobada).
Plan: `specs/014-escudos-e-imagenes-de-equipos/plan.md`.

## Por qué hitos y no una spec partida

La funcionalidad es un corte vertical corto (una imagen por equipo en cuatro
superficies existentes), pero el ciclo de vida de un archivo tiene pasos que se
prueban por separado: validación declarada, subida fuera de transacción, escritura
con bloqueo, borrado tras commit, compensación y degradación. Se divide en **18
tareas de 20–30 minutos** agrupadas en cinco hitos con objetivo verificable, como la
spec 012 (35 tareas con hitos). No conviene dividir la spec: una spec que solo
guarde la imagen dejaría el contrato a medias (escudo almacenado y nunca mostrado) y
una que solo pinte el escudo no tendría dato que pintar.

| Hito | Tareas | Objetivo verificable |
|------|--------|----------------------|
| H1 — Datos y validación declarada | T1–T4 | La columna y la vista pública existen en volumen limpio y migrado; el validador acepta JPEG/PNG/WEBP estáticos y rechaza vacío, GIF, SVG, animado detectable y exceso de tamaño; los códigos de error y la clave segura están fijados. |
| H2 — Ciclo de vida y endpoints | T5–T11 | La firma es un solo lote por respuesta; `GET`/`POST`/`DELETE /tournaments/{id}/teams/{team_id}/crest` dejan exactamente una imagen vigente, con auditoría por cambio efectivo, compensación y última escritura confirmada. |
| H3 — Superficies del producto | T12–T13 | El escudo viaja en el listado de equipos, la operación del partido y las cuatro superficies públicas, siempre por enlace firmado. |
| H4 — Frontend | T14–T16 | Se carga, reemplaza y elimina desde la pantalla de equipos solo con teclado, en español y en inglés, y el escudo (o el sustituto) se ve en operación y en público. |
| H5 — Cierre | T17–T18 | Pasan los jobs aplicables y la documentación declara límites, migración y orden de despliegue. |

Convención: en cada tarea se escriben **primero** las pruebas y se confirman en rojo
(flujo SDD, Fase 5) antes del código mínimo.

---

## H1 — Datos y validación declarada

- [x] **T1. Migración 025: `teams.crest_object_key` y vista pública `v_public_tournament_teams`.** RF-38, RF-47, RF-49, RF-27
- Hecho cuando: existe `infra/postgres/migrations/025_team_crests.sql` con la columna `TEXT` nula y la vista `security_barrier` con `GRANT SELECT` a `bracket_app` y `REVOKE` de `PUBLIC`, sin tocar `init/01`, `init/02` ni las migraciones 001–023; `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_025.py` pasa en verde con la forma de la columna, los privilegios heredados de `teams`, el RLS (otra organización no ve la fila) y la visibilidad de la vista (borrador, sin versión publicada y organización inactiva quedan fuera), y la instantánea de la cadena limpia (`init/00-03` → 001…025) es igual a la de la cadena migrada (`023 → 025`, o `023 → 024 → 025` cuando la 024 esté en `main`); `sh -n infra/postgres/migrate.sh` pasa.

- [x] **T2. Catálogo de errores y clave de objeto segura.** RF-11, RF-36, RF-57
- Hecho cuando: `backend/app/modules/crests/errors.py` define `CrestError(status_code, code, detail)` con los ocho códigos del catálogo de la spec (`CREST_FILE_EMPTY`, `CREST_FORMAT_UNSUPPORTED`, `CREST_ANIMATION_UNSUPPORTED`, `CREST_TOO_LARGE`, `CREST_NOT_FOUND`, `CREST_FORBIDDEN`, `CREST_STORAGE_UNAVAILABLE`, `CREST_UPLOAD_FAILED`), el estado de cada uno, su texto en español y `crest_error_body(exc) -> {"detail": str, "code": str}`, y `validation.py` expone `crest_object_key(organization_id, team_id, token, extension)` con el formato `private/organizations/{org}/teams/{team}/crest/{token}{ext}`; `cd backend && pytest -q tests/test_crest_validation.py -k "error or key"` pasa en verde comprobando estado y código de cada entrada del catálogo, que `detail` es siempre cadena, que la clave válida para `_is_valid_key` no contiene nada del nombre elegido ni `..` y que dos `token` distintos dan claves distintas.

- [x] **T3. Detección de tipo y animación, tamaño y admisión del archivo.** RF-28, RF-29, RF-30, RF-31, RF-32, RF-33, RF-34, RF-35, RNF-1, RNF-2, RNF-3
- Hecho cuando: `backend/app/modules/crests/validation.py` expone `detect_image_type`, `png_declares_animation`, `webp_declares_animation` y `validate_crest_content(content, *, max_bytes)` con el pseudocódigo del plan §6.1; `cd backend && pytest -q tests/test_crest_validation.py` pasa en verde incluyendo: JPEG/PNG/WEBP aceptados con su `content_type` y extensión detectados, archivo con extensión `.png` y contenido JPEG aceptado como JPEG, SVG, GIF y HTML rechazados por contenido aunque la extensión diga otra cosa, vacío → `CREST_FILE_EMPTY`, mayor que el máximo → `CREST_TOO_LARGE` (con el máximo recibido como parámetro, sin leer configuración), PNG con `acTL` antes de `IDAT` → `CREST_ANIMATION_UNSUPPORTED`, PNG con `acTL` después de `IDAT` aceptado, WEBP con bit de animación en `VP8X` y WEBP con bloque `ANIM` rechazados, contenedor truncado o de bloques ilegibles aceptado.

- [x] **T4. Acción de auditoría y su escritura.** RF-45, RF-46, RNF-7
- Hecho cuando: `backend/app/modules/crests/audit.py` define `SET_TEAM_CREST`, `REMOVE_TEAM_CREST`, `crest_audit_action(before, after)` (puro: carga o reemplazo → `SET_TEAM_CREST`, imagen retirada → `REMOVE_TEAM_CREST`, sin imagen previa ni posterior → `None`) y `record_crest_audit(db, *, organization_id, member_id, team_id, action, tournament_id)`, que inserta en `administrative_audit_logs` dentro de la transacción del llamador con `entity_type = 'teams'` y `payload = {"tournament_id": …}`; `cd backend && pytest -q tests/test_crest_audit.py` pasa en verde con la tabla de transiciones y con la comprobación de que el `INSERT` no incluye clave, nombre de archivo, contenido, tamaño ni datos de jugadores.

## H2 — Ciclo de vida y endpoints

- [x] **T5. Resolver de firma en lote con degradación (`sign_media_rows`).** RF-10, RF-11, RF-44, RNF-4, RNF-5, RNF-6
- Hecho cuando: `backend/app/modules/crests/resolver.py` firma fotos y escudos de la misma respuesta en **una** llamada a `ObjectStorage.signed_urls`, deduplica claves, sustituye la clave por el enlace y la elimina de la fila, aplica `policy="error"` (503 con `CREST_STORAGE_UNAVAILABLE`) y `policy="null"` (campo en `None`) y emite **una** línea de registro por respuesta; `cd backend && pytest -q tests/test_crest_resolver.py` pasa en verde, incluida la comprobación de que la firma ocurre sin transacción abierta (`session.in_transaction()` en falso), de que las claves fallidas no bloquean a las demás y de que la clave interna nunca queda en el diccionario devuelto.

- [x] **T6. Contexto de la operación y subida fuera de transacción.** RF-2, RF-3, RF-23, RF-27, RF-39, RNF-4
- Hecho cuando: `backend/app/modules/crests/service.py` expone `resolve_enrolled_team(db, context, tournament_id, team_id, *, lock=False)` —`set_rls_context`, torneo de la organización o 404, equipo inscrito en ese torneo (con `FOR UPDATE OF t` cuando `lock=True`) o `404 CREST_NOT_FOUND`, devolviendo `logo_url` y `crest_object_key`— y `store_crest_object(storage, key, crest)` que sube **con la transacción cerrada** y traduce un fallo del almacenamiento a `503 CREST_STORAGE_UNAVAILABLE` sin escribir nada; `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_crest_service.py -k "context or upload"` pasa en verde comprobando que equipo inexistente, de otra organización y de la organización no inscrito en el torneo producen la misma respuesta, que el fallo de subida no modifica filas y que no hay transacción abierta durante la subida.

- [x] **T7. Escritura con bloqueo: `logo_url`, auditoría y borrado tras el commit.** RF-5, RF-8, RF-12, RF-13, RF-42, RF-45
- Hecho cuando: `load_crest(...)` completa el camino carga/reemplazo: transacción de escritura con `set_rls_context`, permiso revalidado y `SELECT … FOR UPDATE OF t`, `UPDATE teams SET crest_object_key = :nueva, logo_url = NULL`, `record_crest_audit` con `SET_TEAM_CREST` y borrado del archivo anterior **solo** después de confirmar el commit, devolviendo `TeamCrestResponse` con el enlace firmado; `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_crest_service.py -k "load or replace or logo or audit"` pasa en verde comprobando que la primera carga retira `logo_url`, que el reemplazo deja una sola referencia y borra la anterior, que dos equipos distintos nunca comparten clave, que no se audita cuando no hay cambio efectivo y que el archivo anterior solo se borra si el commit se confirmó.

- [x] **T8. Eliminación idempotente.** RF-7, RF-14, RF-40, RF-46
- Hecho cuando: `delete_crest(...)` retira la referencia con bloqueo, escribe `REMOVE_TEAM_CREST` cuando había imagen, responde igual con imagen y sin ella, no restituye `logo_url` y borra el objeto después del commit con el huérfano declarado si el borrado falla; `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_crest_service.py -k "delete"` pasa en verde comprobando que eliminar sin imagen no abre transacción de escritura, no llama al almacenamiento y no audita, que la segunda eliminación no deja una segunda entrada y que un borrado fallido responde correctamente con una sola línea de registro.

- [x] **T9. Compensación, confirmación ambigua y concurrencia.** RF-39, RF-41, RF-42, RNF-4, RNF-14
- Hecho cuando: el camino de escritura distingue «fallo antes del final del cuerpo de escritura» (rollback garantizado → se borra el objeto recién subido) de «confirmación ambigua» (se conservan los dos archivos, la referencia es válida y no hay borrado ni reintento), y no hay ningún borrado de compensación ni de reemplazo ejecutado con transacción abierta; `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_crest_service.py` pasa en verde con los escenarios de fallo forzado (excepción tras la subida y antes del `UPDATE`), dos cargas concurrentes sobre el mismo equipo (una sola referencia, ninguna a un archivo borrado) y carga con eliminación simultánea, y el archivo completo queda como suite de regresión del servicio.

- [x] **T10. Router, registro en `main.py` y manejador de errores.** RF-10, RF-57, RNF-10
- Hecho cuando: `backend/app/modules/crests/router.py` declara `APIRouter(prefix="/tournaments", tags=["crests"])` con `GET` (200), `POST` multipart con campo `file` (200) y `DELETE` (204) en `/{tournament_id}/teams/{team_id}/crest`, cada uno con su `response_model` y su dependencia `get_auth_context`; `main.py` registra `crests_router` con `prefix="/api/v1"` y `api.add_exception_handler(CrestError, _coded_exception_handler)`, con el manejador generalizado para responder `{"detail": str, "code": str}` en cualquier estado; `cd backend && pytest -q tests/test_crest_endpoints.py -k "registered or coded"` pasa en verde comprobando que las tres rutas están en la aplicación con su método y que un `CrestError` de 422, 404, 403, 500 y 503 conserva `detail` cadena y añade `code`; `cd backend && python -m compileall -q app` pasa.

- [x] **T11. Autorización, aislamiento y catálogo de estados del endpoint.** RF-20, RF-21, RF-22, RF-23, RF-24, RF-25, RF-26, RF-27, RNF-11, RNF-15
- Hecho cuando: `cd backend && pytest -q tests/test_crest_endpoints.py` pasa en verde con `httpx.ASGITransport` y dobles de sesión y almacenamiento cubriendo: 403 `CREST_FORBIDDEN` sin `MANAGE_TOURNAMENTS` sin escritura, sin borrado y sin llamada al almacenamiento; 404 `CREST_NOT_FOUND` idéntico para equipo inexistente, de otra organización y no inscrito; 404 de torneo; 422 de los cuatro códigos de validación; 500 `CREST_UPLOAD_FAILED`; 503 `CREST_STORAGE_UNAVAILABLE`; `204` idempotente; el 403 de contexto del miembro sin rol (sin `code`, antes de la operación); cuerpo sin `crest_object_key`; y `Origin` no permitido rechazado antes del manejador; `cd backend && pytest -q` sigue en verde.

## H3 — Superficies del producto

- [x] **T12. Escudo en el listado de equipos y en la operación del partido (Workspace).** RF-15, RF-16, RF-19, RF-44, RNF-4
- Hecho cuando: `GET /tournaments/{id}/teams` devuelve `crest_url` por fila firmado **después** de cerrar la transacción (la lectura del endpoint se reordena como en `public_matches`) y `GET /matches/{id}/operation` devuelve `match.home_team_crest_url`/`match.away_team_crest_url` y `match.home_team_logo_url`/`match.away_team_logo_url` (respaldo del Workspace) sin las claves internas; `cd backend && pytest -q tests/test_crest_surfaces.py` pasa en verde comprobando la firma en un solo lote, que un fallo de firma en el Workspace responde 503 `CREST_STORAGE_UNAVAILABLE`, que `logo_url` sigue devolviéndose mientras no hay escudo y pasa a `null` después, y que ninguna respuesta contiene `crest_object_key`.

- [x] **T13. Escudo en las superficies públicas (detalle, clasificación, partidos y alineaciones).** RF-47, RF-48, RF-49, RF-51, RF-52, RF-10, RNF-13, RNF-5
- Hecho cuando: `GET /tournaments/public/{id}` devuelve `teams: [{team_id, name, short_code, crest_url}]`; `standings` devuelve `crest_url` por fila; `matches` devuelve `home_team_crest_url`, `away_team_crest_url` y `lineup.home.crest_url`/`lineup.away.crest_url`; la consulta solo lee la vista `v_public_tournament_teams` (sin RLS, sin `SECURITY DEFINER` y sin tocar `players`/`rosters`); una firma fallida deja el campo en `null` con 200 y una sola entrada de registro; ninguna respuesta pública incluye `logo_url` ni `crest_object_key`; `cd backend && pytest -q tests/test_crest_public.py tests/test_public_player_views.py` pasa en verde; `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_public_player_views.py` se ejecuta o se declara no ejecutada.

## H4 — Frontend

- [x] **T14. Utilidades puras de escudo, componente `TeamCrest.vue` y textos es/en.** RF-4, RF-17, RF-18, RF-57, RNF-8, RNF-9
- Hecho cuando: `frontend/app/utils/teamCrest.ts` expone `teamInitials`, `crestSource`, `CREST_ERROR_CODES`, `crestErrorMessageKey` y `applyCrestResponse` (fila nueva a partir de la respuesta, o `null` si es de otro equipo) con el contrato del plan §5 (sin DOM, sin reloj, sin red); `frontend/app/components/TeamCrest.vue` pinta `alt` con el nombre del equipo y cae al sustituto de iniciales sin icono roto y sin reintento; `useI18n.ts` incorpora todas las claves nuevas en español y en inglés; `cd frontend && pnpm test` pasa en verde con el nuevo `tests/team-crest.test.ts` (código de 2+ caracteres, código de 1 carácter, nombre, precedencia por superficie con `logo_url` nunca en público, mapeo de los ocho códigos y código desconocido → `null`, y `applyCrestResponse` en carga, reemplazo, eliminación y equipo ausente) y con `tests/labels.test.ts` sin claves huérfanas; `cd frontend && pnpm run typecheck` pasa.

- [x] **T15. Panel de equipos: cargar, reemplazar y eliminar con teclado.** RF-19, RF-55, RF-56, RF-57, RNF-8, RNF-9
- Hecho cuando: en el panel `#equipos` de `workspace/tournaments/[id]/index.vue` cada equipo muestra `TeamCrest` + nombre + código corto y, solo con `MANAGE_TOURNAMENTS`, un `input type="file"` con `<label>` asociada (`accept="image/jpeg,image/png,image/webp"`), «Cargar»/«Reemplazar» y «Eliminar» (este último solo con escudo); sin permiso no se renderiza ningún control de escritura; el estado de espera se anuncia en `role="status"`, el error va en `role="alert"` referenciado por `aria-describedby` desde el botón y el campo, y la respuesta actualiza la fila en sitio sin recargar ni perder versión ni borradores; todas las peticiones pasan por `useApi().request` (con `FormData` y sin fijar `Content-Type`); no se añade `?step=` ni almacenamiento nuevo; `cd frontend && pnpm test && pnpm run typecheck` pasa.

- [x] **T16. Escudo en la operación del partido y en la página pública, con sustituto.** RF-16, RF-18, RF-47, RNF-8
- Hecho cuando: la cabecera de `workspace/matches/[id].vue` muestra los dos escudos sin controles de escritura; `tournaments/[id].vue` muestra el escudo en clasificación, tarjetas de partido, diálogo de alineaciones y lista de equipos del torneo, y **no** pinta `logo_url` en ningún punto; cuando la imagen no carga, ambas vistas muestran el sustituto de iniciales sin icono roto ni reintento automático; `cd frontend && pnpm test && pnpm run typecheck && pnpm run build` pasa.

## H5 — Cierre

- [x] **T17. Documentación: funcionalidad, límites declarados, migración 025 y orden de despliegue.** RF-53, RF-54, RNF-2, RNF-3, RNF-7, RNF-10, RNF-13
- Hecho cuando: `README.md` documenta la funcionalidad (endpoints y campos, límites compartidos con las fotos, validación declarada —metadatos, truncamiento y animación no garantizados—, ausencia de consentimiento, ausencia de eventos, migración 025 y orden **024 → 025 → código**, con pre/comprobaciones y smoke) y `AGENTS.md` recoge el mismo contrato de endpoints y códigos, el orden de despliegue y los riesgos; `grep -q "Escudos de equipo" README.md`, `grep -q "crest_object_key" README.md AGENTS.md` y `grep -q "024 → 025" AGENTS.md` devuelven 0; `python3 infra/scripts/verify_version_sources.py --exclude-constitution` sigue en verde.

- [x] **T18. Verificación completa y declaración honesta.** RNF-12
- Hecho cuando: se ejecutan y se reportan `cd backend && pytest -q`, `cd backend && python -m compileall -q app`, `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck`, `cd frontend && pnpm run build`, `cd frontend && pnpm run typecheck:e2e`, `sh -n infra/postgres/migrate.sh`, `sh -n infra/scripts/verify_worker_loop_health.sh`, `docker compose config -q`; las suites opt-in (`RUN_DATABASE_TESTS=1`) se ejecutan o se declaran **no ejecutadas**; la comprobación manual declarada (carga de una imagen real en navegador, operación solo con teclado y anuncio del lector de pantalla) se marca como realizada o pendiente, sin declarar verde lo que no se ejecutó; el job `e2e` queda en verde y se anota que **no** cubre escudos y no es evidencia de esta funcionalidad.
