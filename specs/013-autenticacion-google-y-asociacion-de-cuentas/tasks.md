# Tareas — Spec 013 (autenticación con Google y asociación de cuentas)

**30 tareas en 5 hitos.** La spec no se divide: un solo flujo de extremo a extremo no se puede entregar por mitades sin dejar un estado intermedio inseguro (un `start` sin `callback` o una vinculación sin la restricción de unicidad de la 024 rompería RF-13). Los hitos agrupan por objetivo verificable; cada tarea cabe en 20–30 minutos y **escribe primero su prueba** (Fase 5: rojo → mínimo código → verde). `Tn` es el identificador estable para marcar avance.

**No se edita ninguna migración aplicada.** Todo cambio de esquema es la 024.

---

## Hito H1 — Esquema, estado de un solo uso y piezas puras

**Objetivo verificable:** la restricción de identidad única existe en una base limpia y en una migrada, y las piezas que no tocan red ni base están cubiertas por pruebas unitarias.

- [x] **T1. Migración 024 y su prueba de cadena.** RF-13, RF-22, RNF-11
  Escribe primero `backend/tests/test_migration_024.py` (rojo), después `infra/postgres/migrations/024_google_identity_uniqueness.sql`: pre-chequeo en la misma transacción que **aborta** con el conteo si hay más de una identidad por `(user_id, provider)`, y `ALTER TABLE public.auth_identities ADD CONSTRAINT uq_auth_identity_user_provider UNIQUE (user_id, provider)`. Sin grants, sin RLS, sin tocar `init/01`.
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_024.py` pasa con la cadena limpia (`init` + 001…024) y la migrada (023 → 024), el catálogo de la restricción es idéntico en ambas, y con dos identidades de la misma cuenta sembradas en 023 la migración **falla y no borra filas**; `sh -n infra/postgres/migrate.sh` sale 0.

- [x] **T2. Destino de retorno y nombre para mostrar (puros).** RF-9, RF-12
  En `backend/app/modules/identity/google_claims.py`: `validate_return_destination(value, *, max_length=512)` y `sanitize_display_name(name, email)`. Sin reloj, sin red, sin base. Pruebas en `backend/tests/test_google_claims.py`.
- Hecho cuando: `cd backend && pytest -q tests/test_google_claims.py` pasa con los casos `//host`, esquema absoluto, 513 caracteres, carácter de control, `None`, y nombre vacío/solo espacios/`None`/sin parte local (fallback neutro); cada caso devuelve el valor esperado sin lanzar.

- [x] **T3. Prueba de identidad de Google (pura).** RF-5, RF-8, RNF-4
  En el mismo módulo: `GoogleIdentity`, `GoogleIdentityInvalid`, `parse_identity_claims(raw, *, client_id, now, issuers, max_bytes=8192)`: tamaño, JSON, `id_token`, `iss`, `aud`, `exp` frente a `now` inyectado, `sub` presente y ≤ 255, `email` presente y ≤ 255, `email_verified is True`; los demás campos se descartan. Amplía `test_google_claims.py`.
- Hecho cuando: `cd backend && pytest -q tests/test_google_claims.py` pasa con 8193 bytes, JSON roto, sin `id_token`, emisor ajeno, audiencia ajena, token caducado (`now` inyectado), `sub` ausente, `sub` de 256 caracteres, correo sin verificar, y el caso válido (incluido `accounts.google.com` y `name` ausente).

- [x] **T4. Estado de un solo uso en Redis.** RF-6, RF-9, RNF-5
  `backend/app/modules/identity/google_state.py`: `GoogleAttempt`, `new_state()`, `state_cache_key()` (SHA-256 del estado), `attempt_is_valid(attempt, *, now)`, `save_attempt`, `consume_attempt` (`GETDEL`), `discard_attempt`. TTL 600 s. Pruebas con un Redis falso al estilo de `FakeRedis` de `test_hardening.py`.
- Hecho cuando: `cd backend && pytest -q tests/test_google_state.py` pasa y demuestra: el valor crudo del estado **no** aparece en la clave; `save_attempt` fija `EX 600`; dos `consume_attempt` seguidos devuelven el registro y luego `None`; un registro con `expires_at` anterior a `now` se rechaza; `discard_attempt` borra.

- [x] **T5. Cliente del proveedor (URL y canje).** RF-2, RF-5, RNF-2, RNF-4
  `backend/app/modules/identity/google_provider.py`: `authorization_url(settings, *, state)`, `remaining_seconds(deadline, now)`, `exchange_code(settings, *, code, deadline, client)`, `GoogleUnavailable`/`GoogleIdentityInvalid`, constantes 5 s / 10 s / 8 KiB, sin reintentos. Pruebas con un `httpx` falso.
- Hecho cuando: `cd backend && pytest -q tests/test_google_provider.py` pasa: la URL lleva `client_id`, `redirect_uri` exacta, `response_type=code`, `scope=openid email profile` y `state`, sin token ni secreto; el canje corta al superar 8192 bytes; `timeout`/error de red/`5xx` → `GoogleUnavailable`; `400 invalid_grant` → `GoogleIdentityInvalid`; `remaining_seconds` nunca es negativa.

- [x] **T6. Configuración `GOOGLE_REDIRECT_URI` y contrato de entorno.** RF-1, RF-4, RNF-7
  `Settings.google_redirect_uri` (vacío → `None` con el validador existente), `ValueError` si Google está habilitado y falta, y comprobación de URL absoluta `http(s)`. Añade la variable a `.env.example` con el valor de desarrollo, a `docker-compose.yml` (`api`, `${GOOGLE_REDIRECT_URI:-}`), a `API_ENV` de `infra/scripts/check_env_contract.py` y a las listas de `backend/tests/test_env_contract.py`.
- Hecho cuando: `cd backend && pytest -q tests/test_config.py tests/test_env_contract.py` pasa con los casos «habilitado sin URI → error», «URI vacía → `None`», «URI relativa → error»; `docker compose config -q` y `docker compose config --format json | python3 infra/scripts/check_env_contract.py -` salen 0; `grep -n '^GOOGLE_REDIRECT_URI=' .env.example` devuelve una línea.

---

## Hito H2 — Backend del flujo y de la asociación

**Objetivo verificable:** el flujo completo (inicio, retorno, alta, vinculación, retiro del camino anterior) responde con los contratos de §7 del plan y no escribe nada cuando falla.

- [x] **T7. Matriz de decisión de cuenta (pura).** RF-11, RF-12, RF-14, RF-15, RF-16, RF-17, RF-18, RF-19
  `backend/app/modules/identity/account_rules.py`: `LoginOutcome`, `LinkOutcome`, `decide_linked_account`, `decide_existing_account`, `decide_link`. Pruebas en `backend/tests/test_google_account_rules.py`.
- Hecho cuando: `cd backend && pytest -q tests/test_google_account_rules.py` cubre las 6 salidas de `decide_existing_account` (incluido `matches=2` → inconsistente) y las 5 de `decide_link` (idempotente, cuenta ya vinculada, identidad ajena, correo distinto, vincular).

- [x] **T8. Resolución de login en base real: alta y sesión.** RF-10, RF-12, RF-27, RF-26
  `backend/app/modules/identity/google_accounts.py::resolve_login` con una transacción: identidad → cuenta; identidad ausente → decisión por correo; alta `users` + `auth_identities` con el nombre saneado; `set_rls_context(db, None, user_id)`; primera organización del orden estable; `create_user_session`. Pruebas opt-in en `backend/tests/test_google_accounts_db.py`.
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_google_accounts_db.py` pasa: alta con nombre recortado, con nombre vacío (parte local) y con nombre neutro; correo en mayúsculas reutiliza la cuenta; `organization_id` es la primera del orden estable; **ninguna** fila nueva en `organization_users`/`organization_user_roles`; `users.password_hash` es `NULL`.

- [x] **T9. Conflictos simultáneos y segundo pase.** RF-13, RF-22, RNF-11
  Añade el segundo pase por `IntegrityError` en `resolve_login` y la prueba de concurrencia `backend/tests/test_google_concurrency_db.py` (dos conexiones, patrón de `test_concurrency_006.py`).
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_google_concurrency_db.py` pasa: misma identidad simultánea → **una** cuenta y **una** identidad, ambos intentos con sesión para la misma cuenta; mismo correo con distinto sujeto → **una** cuenta y el segundo recibe `ACCOUNT_EXISTS_GOOGLE_ONLY`; sin filas duplicadas.

- [x] **T10. Vinculación desde una sesión iniciada.** RF-14, RF-18, RF-19, RF-20, RF-21
  `google_accounts.link_identity` con `decide_link`, `INSERT` de la identidad, sin `UPDATE` de `users.email`, sin `DELETE` y sin tocar `user_sessions`. Amplía `test_google_accounts_db.py`.
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_google_accounts_db.py` pasa: vinculación correcta (una fila nueva), mismo sujeto repetido (sin escritura), `GOOGLE_ALREADY_LINKED` con otro sujeto, `LINK_IDENTITY_TAKEN`, `LINK_EMAIL_MISMATCH`, correo del proveedor cambiado no reescribe `users.email`, y las membresías/roles de ambas cuentas no cambian.

- [x] **T11. `POST /auth/google/start`.** RF-1, RF-2, RF-6, RF-9, RF-14, RNF-1, RF-31
  `GoogleAuthError` (`detail` cadena + `code` aditivo, cualquier estado) y handler en `app/main.py`; endpoint con rate limit, guardas (`503 GOOGLE_UNAVAILABLE`, `409 GOOGLE_ALREADY_LINKED`, `401` sin sesión con `flow=link` resuelta con `get_optional_current_user_id`), estado, cookie `bc_oauth_state` e invalidación del intento anterior. Pruebas en `backend/tests/test_google_auth.py` con proveedor y Redis simulados.
- Hecho cuando: `cd backend && pytest -q tests/test_google_auth.py` pasa: `200` con `authorization_url` y `Set-Cookie` (`HttpOnly`, `SameSite=lax`, `Path=/api/v1/auth/google`, `Max-Age=600`); `503`/`409`/`401`/`429` con `code` y `Retry-After`; Google deshabilitado **no** llama al proveedor; dos `start` seguidos descartan el primer estado.

- [x] **T12. `GET /auth/google/callback` (login).** RF-4, RF-5, RF-6, RF-7, RF-8, RF-9, RF-23, RF-27, RF-31, RNF-2, RNF-5, RNF-8
  Endpoint con presupuesto de 10 s, `GETDEL`, canje, `parse_identity_claims`, bucket `google-identity`, revocación de la sesión presentada, `set_auth_cookie` y redirección a `/auth/callback?next=…` con el destino validado o el destino por defecto (`/organization` sin organización, `/workspace` si la hay). Errores como `302` a `/login?error=<CODE>`. Amplía `test_google_auth.py`.
- Hecho cuando: `cd backend && pytest -q tests/test_google_auth.py` pasa: cada código del catálogo que puede producir el login aparece en `Location` sin correo, nombre, sujeto, `code` ni `state`; un fallo no emite `Set-Cookie: bc_access_token`; `?error=access_denied` → `GOOGLE_CANCELLED`; cookie distinta/repetida/caducada → `GOOGLE_STATE_INVALID`; parámetros extra ignorados; la sesión previa del mismo navegador queda revocada en `user_sessions`.

- [x] **T13. `GET /auth/google/callback` (vinculación) y `GET /auth/google/link`.** RF-18, RF-19, RF-33
  Rama `flow=link` (sin emitir ni revocar sesión) y consulta de estado de vinculación. Amplía `test_google_auth.py`.
- Hecho cuando: `cd backend && pytest -q tests/test_google_auth.py` pasa: éxito → `302 /account/google?notice=GOOGLE_LINK_SUCCESS` sin `Set-Cookie` de sesión; cada rechazo de vinculación → `/account/google?error=<CODE>`; `GET /auth/google/link` devuelve `{"linked": false}` y `{"linked": true}` y **nunca** correo, sujeto ni fecha; sin sesión → `401`.

- [x] **T14. `GET /auth/google/status` y `GET /auth/session`.** RF-1, RF-10, RNF-6
  Dos endpoints de lectura con `Cache-Control: no-store`; `session` devuelve `user_id` y la primera organización del orden estable (o `null`). Pruebas en `test_google_auth.py`.
- Hecho cuando: `cd backend && pytest -q tests/test_google_auth.py` pasa: `status` devuelve `{"enabled": false}` con Google sin configurar y `{"enabled": true}` con las tres variables; `session` responde `200` con la cookie válida, `401` sin ella y `no-store` en ambos.

- [x] **T15. Retiro de `POST /auth/google`.** RF-3, RNF-9
  La ruta responde `410` con `{"detail": …, "code": "GOOGLE_IDENTITY_INVALID"}` **antes** de leer el cuerpo, sin rate limit, sin proveedor y sin escritura. Elimina `GoogleLoginRequest` de `schemas.py` (sin importaciones huérfanas).
- Hecho cuando: `cd backend && pytest -q` pasa (incluida la prueba nueva: `410`, cuerpo con `code`, sin `Set-Cookie`, sin consultas a la base ni al proveedor) y `cd backend && python -m compileall -q app` sale 0; `grep -rn "GoogleLoginRequest" backend/app` no devuelve nada.

- [x] **T16. Log de acceso saneado.** RNF-5
  `backend/app/core/access_log.py` con una función pura `access_log_record(method, path, status)` y el middleware registrado en `app/main.py`; `--no-access-log` en los `command` de `docker-compose.yml` y `docker-compose.production.yml`.
- Hecho cuando: `cd backend && pytest -q tests/test_access_log.py` pasa (la línea no contiene `?`, conserva método y estado) y `cd backend && pytest -q` sigue verde; `docker compose config -q` sale 0 y `grep -rn "no-access-log" docker-compose.yml docker-compose.production.yml` devuelve dos líneas.

---

## Hito H3 — Organización opcional

**Objetivo verificable:** una sesión sin organización puede crearla con datos explícitos y una sesión con organización no puede crear otra por esta vía.

- [x] **T17. `POST /organizations` y su error codificado.** RF-23, RF-24, RF-25, RF-26
  `OrganizationCreateRequest`, reutiliza `OrganizationSummaryResponse`, `OrganizationSlugTaken` (409 `code: ORGANIZATION_SLUG_TAKEN`) y su handler en `app/main.py`; guarda de RF-25 con `list_user_organizations()`; alta con `create_organization_with_owner`. Pruebas en `backend/tests/test_organizations_create.py` con base falsa. Comprueba que **no** hace falta registrar un router nuevo.
- Hecho cuando: `cd backend && pytest -q tests/test_organizations_create.py` pasa: `201` con `{id, name, slug, organization_user_id}`; `409` con `code` al ocupado; `409` sin `code` si ya tiene organización; `401` sin sesión; `422` con `slug` inválido y el cuerpo del error no repite la entrada; el router de organizaciones ya está en `app/main.py`.

- [x] **T18. Organización opcional con base real.** RF-24, RF-25, RF-26
  `backend/tests/test_organizations_create_db.py`: alta con dueño, identificador ocupado que conserva la sesión, guarda de organización previa y verificación de que el login con Google no crea organizaciones.
- Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_organizations_create_db.py` pasa: la organización nace con una membresía activa y un rol `owner`; tras el `409` la cuenta y la sesión siguen existiendo y no hay organización nueva; una cuenta con organización recibe `409` y el recuento de organizaciones no cambia.

---

## Hito H4 — Frontend

**Objetivo verificable:** una persona recorre alta, vinculación, cancelación y organización opcional por teclado, con mensajes del catálogo en español e inglés.

- [x] **T19. Utilidades puras de Google y su prueba.** RF-9, RF-31, RNF-10
  `frontend/app/utils/googleAuth.ts` (`GOOGLE_ERROR_CODES`, `googleStartRequest`, `googleErrorKey`, `googleNoticeKey`, `googleCallbackDestination`) y `frontend/tests/google-auth.test.ts`, incluida la paridad de códigos contra los dos catálogos con `catalogKeys`.
- Hecho cuando: `cd frontend && pnpm test` pasa y `tests/google-auth.test.ts` demuestra: `redirect` inválido → `null`, cada código de `GOOGLE_ERROR_CODES` tiene clave en `es` y `en`, un código desconocido cae en `google.error.unknown`, y `googleCallbackDestination` rechaza `//host`, esquema absoluto y caracteres de control.

- [x] **T20. Catálogo i18n completo (es/en).** RF-31, RNF-10
  `frontend/app/composables/useI18n.ts`: los 12 mensajes del catálogo bajo `google.error.*`/`google.notice.*` y los textos de pantalla (`google.continue`, `google.waiting`, `google.error.unknown`, `google.link.*`, `organization.*`), con paridad exacta de claves.
- Hecho cuando: `cd frontend && pnpm test` pasa (el barrido de `utils/i18nCatalog.ts` no encuentra claves usadas sin definir) y `cd frontend && pnpm run typecheck` sale 0.

- [x] **T21. Store de autenticación.** RF-10, RF-23, RF-27, RF-33
  `frontend/app/stores/auth.ts`: `restoreSession()` (`GET /auth/session` + `loadOrganizations`), `startGoogleAuthorization(flow, redirect)` (`POST /auth/google/start`, devuelve la URL), `googleLinkStatus()`, `linkGoogle()`, `createOrganization(payload)`. Todo con `useApi().request`; sin cambios en `useApi.ts`.
- Hecho cuando: `cd frontend && pnpm run typecheck` y `pnpm run build` salen 0; `grep -rn "auth/google" frontend/app` muestra solo llamadas a través de `request(` y ninguna navegación directa a la API.

- [x] **T22. Pantalla de acceso.** RF-1, RF-7, RF-9, RF-32
  `frontend/app/pages/login.vue`: consulta `status` (SSR), botón «Continuar con Google» solo si está habilitado, espera con `aria-busy`/`aria-live` y bloqueo de pulsaciones repetidas, `?error=<CODE>` traducido, `redirect` reenviado al inicio y enlace a `/organization` cuando hay sesión sin organización.
- Hecho cuando: `cd frontend && pnpm run typecheck` y `pnpm test` pasan; con Google deshabilitado la página no contiene el botón (comprobación manual declarada en T30) y con `?error=ACCOUNT_EXISTS_PASSWORD` muestra el texto del catálogo en el idioma activo.

- [x] **T23. Retorno del flujo y middleware de sesión.** RF-9, RF-10, RF-23
  `frontend/app/pages/auth/callback.vue` (rehidrata con `restoreSession`, `loadOrganizations`, `navigateTo(destino, { replace: true })`, sin `next` válido → `/workspace`) y `frontend/app/middleware/session.ts` (exige `userId`, si falta va a `/login?redirect=`).
- Hecho cuando: `cd frontend && pnpm run typecheck` y `pnpm run build` salen 0; `/auth/callback` no usa middleware y navega con `replace` (el destino no deja entrada extra en el historial).

- [x] **T24. Pantalla de vinculación y entrada de menú.** RF-18, RF-32, RF-33
  `frontend/app/pages/account/google.vue` (estado `linked`, aviso previo, botón, espera, `?notice=GOOGLE_LINK_SUCCESS`, `?error=<CODE>`, sin ofrecer vincular si ya hay identidad) y la entrada «Cuenta de Google» en el menú de cuenta de `frontend/app/components/WorkspaceShell.vue`.
- Hecho cuando: `cd frontend && pnpm run typecheck` y `pnpm run build` salen 0; la pantalla no muestra el botón con `linked: true` y el aviso de éxito se anuncia con `role="status"`.

- [x] **T25. Pantalla de organización opcional.** RF-23, RF-24, RF-25
  `frontend/app/pages/organization.vue` con `middleware: 'session'`: formulario de nombre e identificador (normalización y ayuda como en el registro), `?next=` validado con `safeInternalRedirect`, `ORGANIZATION_SLUG_TAKEN` en el propio paso, «Ahora no» que conserva sesión y muestra `auth.noActiveOrganization`, y redirección si la sesión ya tiene organización.
- Hecho cuando: `cd frontend && pnpm run typecheck`, `pnpm test` y `pnpm run build` salen 0; con `?next=/invitations/x` la creación lleva a esa ruta y con el identificador ocupado el formulario sigue utilizable sin repetir el acceso con Google.

---

## Hito H5 — Documentación y verificación

**Objetivo verificable:** el contrato y el runbook están publicados, los jobs aplicables están en verde y la comprobación real está declarada.

- [x] **T26. Documentación y retiro del contrato anterior.** RF-3, RNF-9, RNF-10
  `README.md` (sección de acceso con Google, catálogo, vinculación, organización opcional, runbook de la 024 con orden 024 → código, y la nota de que `POST /auth/google` responde 410) y `AGENTS.md` (sustituye «Google OAuth preparado mediante `auth_identities`», documenta endpoints, estado en Redis, log saneado, restricción 024 y la comprobación manual). No se toca `docs/runbook-despliegue-019-023.md`.
- Hecho cuando: `grep -rn "Google OAuth preparado" README.md AGENTS.md` no devuelve nada; `grep -n "024" README.md AGENTS.md` encuentra el runbook en ambos; `python3 infra/scripts/verify_version_sources.py --exclude-constitution` sale 0.

- [x] **T27. Verificación backend.** RF-1…RF-33, RNF-1…RNF-12
  Suite completa y compilación, más las opt-in de la spec.
- Hecho cuando: `cd backend && pytest -q` pasa; `cd backend && python -m compileall -q app` sale 0; `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_migration_024.py tests/test_google_accounts_db.py tests/test_google_concurrency_db.py tests/test_organizations_create_db.py` pasa o se declara **no ejecutada** con el motivo.

- [x] **T28. Verificación frontend.** RNF-10, RF-31, RF-32, RF-33
  Suite, tipos y build. `pnpm run typecheck:e2e` se ejecuta porque el job `e2e` lo exige, aunque el arnés **no** cubre Google.
- Hecho cuando: `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck`, `cd frontend && pnpm run build` y `cd frontend && pnpm run typecheck:e2e` salen 0.

- [x] **T29. Verificación de infraestructura y seguridad.** §4 (infraestructura, dependencias)
  Mismos checks que CI para el cambio.
- Hecho cuando: `sh -n infra/postgres/migrate.sh`, `sh -n infra/scripts/verify_worker_loop_health.sh`, `docker compose config -q`, `docker compose config --format json | python3 infra/scripts/check_env_contract.py -`, `python3 infra/scripts/check_env_contract.py --self-test`, el merge dev+prod con variables dummy más `assert_production_compose.py`, `pip-audit -r backend/requirements.txt -r backend/requirements-dev.txt` y la auditoría del frontend con `infra/scripts/audit_frontend.py` salen 0.

- [x] **T30. Comprobación manual contra un cliente de Google real (MANUAL, criterio 11).** RF-1…RF-9, RF-15, RF-18, RF-23, RF-33 — **no ejecutada: sin cliente OAuth real en este entorno**
  Ejecuta el guion de §13.5 del plan en un entorno de desarrollo con un cliente OAuth real y registra el resultado (fecha, entorno, códigos observados) en el README, sin correos ni identificadores. El job `e2e` **no** es evidencia de esta funcionalidad.
- Hecho cuando: el README contiene el registro de la corrida con los cinco escenarios (alta, reentrada sin duplicados, `ACCOUNT_EXISTS_PASSWORD` + vinculación, cancelación + `GOOGLE_STATE_INVALID`, retorno a la invitación) y el resultado se declara explícitamente como manual; si no pudo ejecutarse, queda declarado como **no ejecutado** con su motivo.
  **Estado:** declarada **no ejecutada** con su motivo en `README.md` y `AGENTS.md` (este entorno no tiene un cliente OAuth real configurado); no se registran fecha ni resultados.
