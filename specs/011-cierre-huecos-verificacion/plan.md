# Plan 011 — Cierre de los huecos de verificación de las specs 009 y 010

Spec: `specs/011-cierre-huecos-verificacion/spec.md` (**aprobada 2026-10-22**).
Estado del plan: aprobado e implementado; validación cerrada el 2026-10-22; corrección de la ronda 1 (códigos del worker, RF-007/AGENTS, contrato del README, fallback de CI) y ajuste del timeout de CI.

## Objetivo y alcance técnico

Ocho requisitos de **verificación y documentación**, sin producto nuevo:

1. **RF-001** — prueba de atomicidad de C-2 con fallo inducido después de materializar (backend, opt-in con PostgreSQL).
2. **RF-002** — contrato **403** del miembro sin rol contra el endpoint **auténtico** (backend, opt-in con PostgreSQL).
3. **RF-003** — sonda de outbox en la verificación operativa del worker (script `sh` + utilidad Python dentro del contenedor).
4. **RF-004** — mensajes de fallo de la suite de invitaciones sin cuerpo, enlace ni token.
5. **RF-005** — evidencia real de `server.log` con Docker (corrida, no código).
6. **RF-006** — `states` = muestras y `transitions` = transiciones en el resumen.
7. **RF-007** — captura solo en fallo, con predicado puro.
8. **RF-008** — el paso de CI solo reescribe `server.log` cuando no está **disponible**.

**Sin migraciones y sin job nuevo.** No hay DDL, ni cambios en `infra/postgres/`, ni en `init/`, ni
tablas, columnas, políticas o permisos: el rol de aplicación ya tiene `SELECT`/`INSERT`/`DELETE` sobre
`outbox_events` y la política `tenant_isolation_policy` admite la escritura dentro de la organización
demo con el contexto fijado, que es justo lo que la sonda necesita (RNF-002). `ci.yml` cambia **solo el
cuerpo** del paso «Collect sanitized server logs» del job `e2e` existente: no se añade job, ni paso nuevo,
ni se toca su veredicto (RNF-006, Q3). No se abren specs 009/010, ni `README.md` de producto cambia de
alcance, ni se toca `docs/constitution.md`.

Arquitectura técnica en una frase: **las pruebas y el arnés ganan observables**, el producto no cambia
—ni una ruta, ni un permiso, ni un mensaje de la API (RNF-001)—.

## Decisiones de plan (con alternativa descartada)

1. **RF-001: el fallo se induce sustituyendo `record_invitation_audit` en el espacio de nombres del
   router** (`monkeypatch.setattr(invitations_router, "record_invitation_audit", doble)`). Ese punto se
   ejecuta **después** de `_materialize_expired_pending` y del `UPDATE` que reabre la revocada, y
   **antes** de cerrar la transacción; el doble, antes de lanzar, **lee la fila materializada y la
   reabierta en la misma transacción** y las registra, que es la prueba de «el fallo ocurrió ahí».
   *Descartado:* fallar en `send_invitation_email`, que corre **después del commit** y es el caso límite 3
   (contrato de la 009, no atomicidad); fallar con un error de base de datos inyectado por SQL (no
   determinista y ensucia la sesión); añadir un gancho de prueba al producto (RNF-003).
2. **RF-001 corre en el savepoint del arnés existente** (`_RequestSession.begin()` → `session.begin_nested()`),
   igual que el resto de la suite, y las aserciones se hacen **después** de la reversión de ese
   savepoint, sobre la misma sesión con el contexto RLS fijado. *Descartado:* abrir una transacción real
   por petición (deja filas y exige limpieza), y comprobar el estado con una segunda conexión (no ve el
   estado interno y complica el contexto RLS).
3. **La respuesta de error se obtiene como HTTP 500 con `raise_app_exceptions=False`**, ampliando
   `_invitation_api` con ese parámetro (patrón ya usado en `test_swiss_transaction.py`). *Descartado:*
   dejar que la excepción se propague (el caso límite 5 lo prohíbe expresamente como evidencia).
4. **RF-002: solo se sustituyen la identidad y la sesión de pruebas** —`api.dependency_overrides[get_current_user_id]`
   y `[get_db]`— y `get_auth_context` se ejecuta **de verdad** contra PostgreSQL, con el header
   `X-Organization-ID`. Un helper nuevo (`_invitation_api_as_user`) convive con el existente, que sigue
   sustituyendo el contexto para las pruebas de autorización de rol. *Descartado:* reutilizar
   `_invitation_api` (sustituye el contexto: caso límite 16, ya no cierra el hueco) y firmar un JWT real
   (añade criptografía de sesión y una cookie a la prueba sin aportar nada al requisito).
5. **La organización demo se resuelve con el camino que el rol de aplicación sí tiene**: leer `users` por
   correo (`GRANT SELECT (id, email, …)`), fijar `app.current_user_id` con `set_rls_context(session, None, user_id)`,
   llamar a `list_user_organizations()` y localizar por `slug = 'demo-federation'`; después se fija el
   contexto completo con organización y usuario. `organizations` no tiene `GRANT SELECT` para
   `bracket_app` y `organization_users` está bajo RLS con `FORCE`, así que ese es el único camino sin
   elevar privilegios. *Descartado:* `DATABASE_ADMIN_URL` (rompe el modelo de rol de aplicación que el
   propio hueco quiere respetar), `SELECT` directo sobre `organizations` (no existe el permiso) y fijar
   el UUID de la organización demo (frágil ante un volumen recreado).
6. **RF-002 crea el sujeto sin rol dentro de la organización demo, en una transacción que se revierte**
   (`db_session`): usuario ficticio (`no-role-<hex>@example.test`), membresía activa en
   `organization_users` y **ninguna** fila en `organization_user_roles`. La organización aislada de
   `tenant_factory` se usa **solo** para el caso «invitación de otra organización», que también se
   revierte. *Descartado:* crear el sujeto en una organización aislada (contradice RF-002: «dentro de la
   organización demo»); crear el sujeto en la organización demo con `invitation_context` (esa fixture
   **confirma** al salir y dejaría filas en el entorno de desarrollo); `DATABASE_ADMIN_URL` (privilegio
   innecesario).
7. **Las pruebas de RF-001 y RF-002 viven en `backend/tests/test_invitations.py`**, junto a los helpers
   que ya usan (`_insert_tenant_invitation`, `_stored_invitations`, `_invitation_api`,
   `invitation_context`). *Descartado:* dos ficheros nuevos que importen helpers de un módulo de pruebas
   (acoplamiento entre suites y riesgo de reejecutar sustituciones), y mover helpers existentes (37
   llamadas afectadas, riesgo alto para cero beneficio).
8. **RF-003: la sonda la ejecuta una utilidad `backend/scripts/outbox_probe.py` dentro del contenedor del
   worker** (`worker_exec python -m scripts.outbox_probe …`), orquestada por el `sh` existente. La
   utilidad concentra la resolución de la organización demo, el contexto RLS, la inserción, la consulta y
   el borrado, y expone funciones **puras** comprobables con `pytest` sin base de datos. *Descartado:*
   SQL incrustado en `sh` (sin funciones puras, sin distinción de errores y con comillas frágiles),
   `psql` desde el host con `DATABASE_ADMIN_URL` (privilegios que no queremos) y `psql` dentro del
   contenedor (no está instalado en la imagen `python:3.14-slim`).
9. **Guard de entorno al principio: paso 0, antes de esperar el estado sano y de congelar**, leyendo
   `APP_ENV` de la configuración efectiva **del propio worker** (`scripts.outbox_probe guard`), con
   `DEVELOPMENT_ENVS` (`development`, `dev`, `local`) como única fuente. La utilidad repite el guard en
   `insert`/`status`/`delete` (defensa en profundidad). Sin `APP_ENV`, valor desconocido o producción →
   **código 2**, mensaje «no ejecutable» y **cero escrituras**. No existe ninguna opción para forzarlo.
   *Descartado:* leer el `.env` del host (puede diferir del contenedor), y una bandera `--force`
   (RF-003 la prohíbe).
10. **Los reintentos del outbox no son fallo: `pending`/`processing` significan «sigue esperando».**
    `fail_outbox_event` devuelve el evento a `pending` con `available_at = now + 5 s` hasta que
    `attempts >= 5`, y solo entonces lo deja en `failed`. Presupuesto propio: `WORKER_PROBE_TIMEOUT`
    (defecto **120 s**) y `WORKER_PROBE_POLL_INTERVAL` (defecto **2 s**), independientes de los tiempos de
    salud; 5 intentos × 5 s + procesamiento queda muy por debajo. Agotar el presupuesto es **código 1**
    con el paso identificado; `failed` (5 intentos agotados) es **código 1 inmediato** con el
    `last_error` saneado. *Descartado:* una espera fija (RNF-003 la prohíbe), tratar un reintento como
    fallo (falso rojo) y tratar una cola vacía como éxito (caso límite 7).
11. **La corroboración en el stream es informativa y acotada al final del stream** (`XREVRANGE` con
    `COUNT 1000`, buscando el `event_id` de la fila). Nunca decide el veredicto. *Descartado:* recorrer
    el stream completo (hasta 10 000 entradas, coste y complejidad) y usar el stream como criterio
    principal (mejor esfuerzo, con pérdidas posibles: RF-003 elige el estado persistido).
12. **RF-004: el formateador vive en el código de apoyo de las pruebas** (`backend/tests/assertion_messages.py`)
    y es el **único** punto que mira el cuerpo, con **lista blanca de una clave**: `code`, y solo si es
    `str`. El mensaje es `"<etiqueta>: HTTP <estado>[ (code=<code>)]"`. La comprobación de fuente usa
    `ast` sobre `backend/tests/test_invitations.py` y mira el `msg` de cada `ast.Assert`. *Descartado:*
    seguir usando `response.text` (filtra `invite_url` con token), un barrido por regex (frágil con
    f-strings y multilínea) y poner el formateador en `app/` (cambio de producto, RF-004 lo prohíbe).
13. **RF-006: `transitions` se publica en el resumen por vista (`summary.json`) y el artefacto no
    cambia.** `states` del resumen conserva el nombre y la semántica de **muestras**; `transitions` es un
    entero **o `null`** si el artefacto falta, está inválido o tiene menos de dos muestras. `schemaVersion`
    del resumen sigue en `1` (campo aditivo y opcional, decisión documentada junto al campo). *Descartado:*
    añadir `transitions` al artefacto de vista (duplica datos y mueve la fuente de verdad) y subir
    `schemaVersion` (rompe lectores sin necesidad).
14. **RF-007: predicado puro `shouldCaptureScreenshot(verdict)` en `frontend/e2e/observations.ts`**, usado
    por `realtimeScenario.ts` en el punto donde hoy hay un `if` inline. *Descartado:* dejar el `if` y
    comprobarlo por aserción de texto del fuente (no cubre la decisión) y capturar también en verde
    (Q2 descartada).
15. **RF-008: la disponibilidad se decide sobre el fichero, no sobre el flag.** `SERVER_LOG_HEADER` pasa a
    exportarse con el texto **exacto**
    `# server.log — docker compose logs --no-color api worker web`; `serverLogIsAvailable(content)` es la
    única decisión (cabecera + ≥1 línea de contenido que no sea `# no disponible:` ni blanco) y
    `buildServerLog` deriva su `available` de ella, de modo que un `docker compose logs` con código 0 y
    salida vacía ya **no** se declara disponible. `composeServerLog(raw)` centraliza cabecera + saneado
    para el paso de CI. *Descartado:* mantener el flag (un volcado vacío dejaría un `server.log` solo con
    cabecera y CI no lo reescribiría), escribir un fichero distinto (cambia nombre y retención) y añadir
    un paso de compilación (RF-008 exige el mecanismo actual con Node 24).
16. **Sin job nuevo y sin sumar la sonda al job `e2e`.** La sonda se cierra con **ejecución real con
    Docker** citada en la validación (Q3). *Descartado:* añadirla al job de navegador (alarga y acopla dos
    fallos distintos) y un job de operación propio (RNF-006).

## Archivos y responsabilidades

### Backend — pruebas (RF-001, RF-002, RF-004) y utilidad operativa (RF-003)

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `backend/tests/assertion_messages.py` | **nuevo** | `describe_response(label, response)`, `describe_status(label, status, code)` y `reason_code(payload)` (lista blanca: solo `code` si es `str` y no vacío). Único punto autorizado a leer el cuerpo. |
| `backend/tests/test_assertion_messages.py` | **nuevo** | Unitario siempre activo: un cuerpo con `invite_url` y token no aparece en la salida; recuento de hallazgos **cero** en `test_invitations.py` con `ast` sobre `ast.Assert.msg`; las tres comprobaciones de contenido siguen presentes y no cuentan como hallazgo. |
| `backend/tests/test_invitations.py` | **modificado** | (a) los **37** mensajes de fallo pasan a `describe_response`; (b) `_invitation_api` acepta `raise_app_exceptions`; (c) prueba de atomicidad de C-2; (d) helper `_invitation_api_as_user` (identidad + sesión, contexto real) y prueba del miembro sin rol; (e) helper `_demo_tenant(session)` con el camino `users` → `list_user_organizations()` → slug. |
| `backend/scripts/outbox_probe.py` | **nuevo** | Subcomandos `guard`, `insert`, `status`, `delete`; resolución demo, contexto RLS, inserción/consulta/borrado por `id` + marcador, corroboración acotada en el stream y funciones puras del guard y de la clasificación. |
| `backend/tests/test_outbox_probe.py` | **nuevo** | Unitario siempre activo sobre las funciones puras (guard, marcador único, clasificación, presupuesto, comandos) y aserciones de fuente: usa `list_user_organizations` y `set_rls_context`, no usa `DATABASE_ADMIN_URL` ni el rol administrador. |

Notas de implementación del helper (sin cambios de producto):

- `outbox_probe.py` reutiliza `SessionFactory`/`create_async_engine` con `DATABASE_URL` (rol de
  aplicación) y `set_rls_context`; **no** importa `DATABASE_ADMIN_URL`.
- El evento se inserta con `event_type = 'VERIFICATION_OUTBOX_PROBE'` (sin handler de dominio) y
  `payload = {"marker": …, "verification": "spec-011"}`; el marcador es único por corrida
  (`worker-probe-<epoch>-<pid>-<4 bytes hex>`).
- `worker_exec` ya resuelve «contenedor o servicio de Compose»; la utilidad se invoca con `python -m`
  para no depender del directorio de trabajo.

### Operación — verificación del worker (RF-003)

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `infra/scripts/verify_worker_loop_health.sh` | **modificado** | Paso 0 de entorno antes de tocar el healthcheck; paso 7 de sonda **después** de la reanudación (insertar, esperar, clasificar); variables nuevas `WORKER_PROBE_TIMEOUT` (120) y `WORKER_PROBE_POLL_INTERVAL` (2) validadas como enteros positivos; limpieza en el `trap` (tras reanudar el bucle); códigos 0/1/2 conservados y documentados en la cabecera. |

La verificación **no** entra en `pytest`, en `pnpm test` ni en ningún job: su cierre es una corrida real
(Q3) y así se declara en la validación.

### Arnés E2E y CI (RF-006, RF-007, RF-008)

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `frontend/e2e/observations.ts` | **modificado** | `countSamples(samples)`, `countTransitions(samples)` y `shouldCaptureScreenshot(verdict)`; puros, sin reloj y sin Playwright. |
| `frontend/e2e/runModel.ts` | **modificado** | `SERVER_LOG_HEADER` exportado con el texto exacto; `serverLogIsAvailable(content)`; `composeServerLog(rawOutput)`; `buildServerLog` deriva `available` del contenido; `ViewSummary.transitions: number \| null`; tabla con `MUESTRAS` y `TRANSICIONES`. |
| `frontend/e2e/realtimeScenario.ts` | **modificado** | La captura se decide con `shouldCaptureScreenshot(verdict)` (mismo comportamiento: solo en fallo). |
| `frontend/tests/e2e-runner.test.ts` | **modificado** | Casos de `serverLogIsAvailable` (disponible, ausente, solo cabecera, declara no disponible, comando con código ≠ 0, comando agotado) y de `transitions` en el resumen y en la tabla. |
| `frontend/tests/e2e-observations.test.ts` | **modificado** | `countTransitions` (repetidos, primero no cuenta, artefacto vacío) y `shouldCaptureScreenshot` (verde → `false`; cada no verde → `true`). |
| `.github/workflows/ci.yml` | **modificado** | Solo el cuerpo del paso «Collect sanitized server logs»: lee `frontend/e2e-report/server.log`, sale sin escribir si `serverLogIsAvailable` es verdadero y, si no, escribe `composeServerLog(salida real)`. Conserva `if: always()`, `continue-on-error`, ruta, nombre y retención. |

Sin cambios en `frontend/e2e/artifacts.ts`, en `channel.ts`, en los specs de vista, en
`playwright.config.ts` ni en `frontend/package.json`; sin dependencias nuevas.

### Documentación (RF-002, RF-003, RF-006, RF-007, RF-008 — RNF-007)

| Archivo | Cambio |
|---|---|
| `README.md` | Contrato de acceso (sin rol → **403**; `200`/`viewer`/`[]` solo con rol `viewer`); artefactos del arnés: `screenshots/` **solo** en fallo, `states` = muestras y `transitions` = transiciones; `server.log` con cabecera y regla de disponibilidad, y el fallback de CI; verificación del worker con la sonda, sus dos variables, la restricción a desarrollo/local, los códigos y la limpieza; nota de que la sonda aparece como evento de socket en desarrollo y es inocua. |
| `AGENTS.md` | «Límites del Proyecto»: `scripts.outbox_probe` es utilidad de verificación (no seed, no producción) y el contrato **403** del miembro sin rol; «Healthchecks»: la verificación observa una sonda; «Arnés E2E»: captura solo en fallo, `states`/`transitions` y disponibilidad de `server.log`; «Verificación»/Testing: comandos unitarios nuevos, opt-in de `test_invitations.py` y el comando del script con sus variables. |

No se editan `docs/constitution.md`, `MEMORY.md`, `specs/009-*`, `specs/010-*` ni `.env.example` (las
variables de la sonda las lee el script, no un servicio de Compose, así que el contrato de entorno no
cambia).

## Funciones puras

| Función | Ubicación | Regla |
|---|---|---|
| `describe_status(label, status, code)` | `backend/tests/assertion_messages.py` | `"<label>: HTTP <status>"` + `" (code=<code>)"` solo si `code` es `str` no vacío. Sin cuerpo, sin enlace, sin token. |
| `reason_code(payload)` | `backend/tests/assertion_messages.py` | Lista blanca de **una** clave: devuelve `payload["code"]` si es `str` no vacío; en cualquier otro caso `None`. |
| `environment_allows_probe(app_env)` | `backend/scripts/outbox_probe.py` | `app_env.lower().strip() in DEVELOPMENT_ENVS`; cadena vacía, `None` o desconocida → `False`. Sin reloj, sin entorno global (recibe el valor). |
| `probe_marker(epoch_seconds, pid, random_hex)` | `backend/scripts/outbox_probe.py` | `worker-probe-<epoch>-<pid>-<hex>`; los tres valores llegan por parámetro (el borde los toma de `date`, `os.getpid` y `os.urandom`). |
| `classify_probe(row)` | `backend/scripts/outbox_probe.py` | `processed` → `processed`; `pending`/`processing` → `retrying`; `failed` → `failed`; fila ausente → `missing`. |
| `probe_deadline(inserted_at, timeout_seconds)` | `backend/scripts/outbox_probe.py` | `inserted_at + timeout_seconds`; el instante llega por parámetro. |
| `probe_exhausted(now, deadline)` | `backend/scripts/outbox_probe.py` | `now >= deadline`; sin leer el reloj. |
| `countSamples(samples)` | `frontend/e2e/observations.ts` | Recuento por estado observado (semántica actual de `states`). |
| `countTransitions(samples)` | `frontend/e2e/observations.ts` | Pares consecutivos con estado **distinto**; el primero no cuenta; `[]` y `[x]` → `0`. |
| `shouldCaptureScreenshot(verdict)` | `frontend/e2e/observations.ts` | `verdict !== 'passed'`. |
| `serverLogIsAvailable(content)` | `frontend/e2e/runModel.ts` | `content != null`, primera línea igual a `SERVER_LOG_HEADER` y ≥1 línea de contenido no blanca; cualquier línea `# no disponible:` → `false`. |
| `composeServerLog(rawOutput)` | `frontend/e2e/runModel.ts` | `redactLog` + cabecera + salto final; función pura (sin reloj, sin disco). |

Ninguna función de lógica temporal lee el reloj: los instantes los toma el borde (`date +%s` en el
script; `Date.now()` en el arnés) y llegan por parámetro.

## Pseudocódigo

### RF-001 — fallo inducido después de materializar

```text
test_reopen_failure_after_materializing_rolls_back_both_writes
  tenant  = tenant_factory("Reopen Atomicity")            # organización aislada; dueño con MANAGE_MEMBERS
  email   = f"atomic-{uuid4().hex}@example.test"
  revocada = insertar(status='revoked', token=T1, revoked_at=hace 1 h, expires_at=futuro)
  vencida  = insertar(status='pending', token=T2, expires_at=ahora - 5 min)      # mismo correo
  antes = {revocada: (status, token_hash, expires_at, revoked_at, updated_at),
           vencida : (status, token_hash, expires_at, updated_at)}

  visto = {}
  async def doble_auditoria(db, *, organization_id, member_id, invitation_id, action, payload):
      # se ejecuta DENTRO de la transacción del request, tras materializar y reabrir
      visto['vencida_status']  = SELECT status FROM organization_invitations WHERE id = vencida
      visto['reabierta']       = SELECT status, token_hash FROM organization_invitations WHERE id = revocada
      visto['auditoria_previa']= SELECT count(*) FROM administrative_audit_logs WHERE entity_id = revocada
      raise RuntimeError("fallo inducido: después de materializar y antes del commit")

  monkeypatch.setattr(invitations_router, 'record_invitation_audit', doble_auditoria)
  enviados = []
  monkeypatch.setattr(invitations_router, 'send_invitation_email', recorder(enviados))

  async with _invitation_api(db_session, tenant, monkeypatch, raise_app_exceptions=False) as client:
      r = await client.post(f"/api/v1/organizations/invitations/{revocada}/reopen")

  # 1) hubo respuesta HTTP de error y no filtró nada
  afirmar r.status_code == 500
  afirmar "invite_url" not in r.text and T1 not in r.text
  # 2) el fallo ocurrió en el punto declarado (doble ejecutado y ambas escrituras visibles)
  afirmar visto['vencida_status'] == 'expired'
  afirmar visto['reabierta'].status == 'pending' and visto['reabierta'].token_hash != antes.revocada.token_hash
  afirmar visto['auditoria_previa'] == 0
  # 3) tras la reversión del savepoint no persiste ninguna de las dos escrituras
  afirmar estado_actual(vencida)  == antes.vencida       # status pendiente, token, vencimiento y updated_at
  afirmar estado_actual(revocada) == antes.revocada      # revocada, token, revoked_at y updated_at
  afirmar filas_con_ese_correo == 2                      # ninguna fila nueva
  afirmar count(administrative_audit_logs, entity_id=revocada) == 0
  afirmar enviados == []
```

`raise_app_exceptions=False` es el único cambio de apoyo: sin él, la excepción se propaga y no hay
respuesta HTTP que afirmar (caso límite 5).

### RF-002 — miembro sin rol contra el endpoint auténtico

```text
test_member_without_role_is_rejected_before_the_handler
  demo   = _demo_tenant(db_session)          # ver «resolución demo» abajo; requiere el seed demo
  sujeto = INSERT INTO users(email=f"no-role-{uuid4().hex}@example.test", password_hash='x', full_name='Sin Rol')
  INSERT INTO organization_users(organization_id=demo.org, user_id=sujeto)      # SIN organization_user_roles
  propia = insertar invitación pendiente en demo.org (correo ficticio)

  async with _invitation_api_as_user(db_session, user_id=sujeto, organization_id=demo.org) as client:
      # solo se sustituyen get_db y get_current_user_id: get_auth_context corre de verdad
      peticiones = [
        GET    /organizations/current/access,
        GET    /organizations/members,
        PATCH  /organizations/members/{demo.member_de_dueño}/role,
        PATCH  /organizations/members/{demo.member_de_dueño}/status,
        POST   /organizations/invitations,
        POST   /organizations/invitations/{propia}/resend,
        POST   /organizations/invitations/{propia}/reopen,
        DELETE /organizations/invitations/{propia},
        DELETE /organizations/invitations/{uuid4()},                      # inexistente
        DELETE /organizations/invitations/{de_otra_org},                  # otra organización (tenant_factory)
      ]
  afirmar todas 403 y cuerpo idéntico {"detail": "Membresía o rol activo no válido"}
  afirmar la propia sigue pendiente con token, vencimiento y updated_at intactos
  afirmar ninguna fila nueva, cero auditoría para ella y enviados == []
  # guarda siempre activa (sin base de datos): el helper no sustituye get_auth_context
  afirmar "get_auth_context" not in getsource(_invitation_api_as_user)
```

Resolución demo (`_demo_tenant`, y su gemela en `outbox_probe`):

```text
user_id = SELECT id FROM users WHERE LOWER(email) = 'demo.owner@bracketcraft.dev'   # único SELECT concedido
si no existe -> pytest.skip (prueba) / salida 2 (script)
set_rls_context(session, None, user_id)
fila = SELECT id, organization_user_id FROM list_user_organizations() WHERE slug = 'demo-federation'
si falta -> pytest.skip / salida 2
set_rls_context(session, fila.id, user_id)
```

### RF-003 — sonda de outbox en la verificación del worker

```text
# --- scripts/outbox_probe.py (dentro del contenedor del worker) ---
guard            -> si !environment_allows_probe(settings.app_env): salida 2
                    imprime "APP_ENV=<valor>"; salida 0
insert --marker M-> guard; (org, user) = resolver_demo();  BEGIN
                    INSERT INTO outbox_events (organization_id, event_type, payload)
                    VALUES (:org, 'VERIFICATION_OUTBOX_PROBE',
                            jsonb_build_object('marker', :M, 'verification', 'spec-011'))
                    RETURNING id;  COMMIT;  imprime "<id> <M>"
status --id X --marker M
                 -> guard; (org, user) = resolver_demo()
                    fila = SELECT id, status, attempts, processed_at, last_error
                           FROM outbox_events WHERE id = :X AND payload->>'marker' = :M
                    imprime "status=<s> attempts=<n> processed_at=<t|-> stream=<found|not-found>"
                    (stream: XREVRANGE OUTBOX_STREAM + - COUNT 1000 buscando event_id = X; informativo)
delete --id X --marker M
                 -> guard; (org, user) = resolver_demo()
                    DELETE FROM outbox_events WHERE id = :X AND payload->>'marker' = :M RETURNING id
                    imprime "deleted=1" (o "deleted=0" y salida 1 si no encontró la fila)
```

```text
# --- infra/scripts/verify_worker_loop_health.sh ---
... resolución de contenedor/servicio (sin cambios) ...

Paso 0 (nuevo, ANTES de cualquier espera o señal):
  app_env = worker_exec python -m scripts.outbox_probe guard
  si sale != 0 -> not_executable "APP_ENV no es desarrollo/local (nada escrito)"   # código 2

Pasos 1..6  (sin cambios: healthy, SIGSTOP, unhealthy, SIGCONT, healthy, sin reinicio, latido)

Paso 7 (nuevo, SOLO después de la reanudación):
  PROBE_MARKER = probe_marker(date +%s, $$, 4 bytes hex)
  PROBE_ID = worker_exec python -m scripts.outbox_probe insert --marker "$PROBE_MARKER"
  si sale != 0 -> fail "no se pudo insertar la sonda (paso 7)"
  limite = now + WORKER_PROBE_TIMEOUT
  bucle:
      salida = worker_exec python -m scripts.outbox_probe status --id "$PROBE_ID" --marker "$PROBE_MARKER"
      caso classify(salida):
          processed -> progress "la sonda se procesó"; break
          failed    -> fail "la sonda agotó 5 intentos: <last_error saneado> (paso 7)"
          retrying  -> progress "[<s>] <salida>"; si probe_exhausted(now, limite) -> fail
          missing   -> fail "la sonda desapareció de la cola (paso 7)"
      sleep WORKER_PROBE_POLL_INTERVAL
  progress "sonda procesada en <s>s; id=<id> marcador=<M>"

cleanup (trap EXIT/HUP/INT/TERM, al final):
  restaurar el bucle (SIGCONT) como hoy
  si PROBE_ID no vacío:
      worker_exec python -m scripts.outbox_probe delete --id "$PROBE_ID" --marker "$PROBE_MARKER"
      si falla -> imprime id y marcador, deja salida 1
  exit <código>
```

La sonda publica en el stream y el relay la reenvía a `organization:{id}`: en desarrollo aparece como un
evento de socket más. No tiene handler, no lleva datos personales y caduca con el tope del stream; se
documenta como inocuo (nota de QA 9).

### RF-008 — disponibilidad del `server.log` y fallback de CI

```text
SERVER_LOG_HEADER = "# server.log — docker compose logs --no-color api worker web"

serverLogIsAvailable(content):
    si content es null o vacío -> false
    lineas = split(content, /\r?\n/)
    si trimEnd(lineas[0]) != SERVER_LOG_HEADER -> false
    cuerpo = lineas[1..] filtrando blancas
    si cuerpo vacío -> false
    si alguna línea empieza por "# no disponible:" -> false
    -> true

composeServerLog(salidaCruda):
    cuerpo = sin líneas finales vacías (redactLog(salidaCruda))
    -> SERVER_LOG_HEADER + "\n" + cuerpo + "\n"

buildServerLog({dockerAvailable, command}):
    contenido = (sin Docker)            -> cabecera + "# no disponible: docker CLI ausente"
              | (comando != 0/timeout)  -> cabecera + "# no disponible: …" [+ salida saneada]
              | (comando == 0)          -> cabecera + salida saneada
    available = serverLogIsAvailable(contenido)      # sobre el fichero, no sobre el flag
```

```text
# .github/workflows/ci.yml — cuerpo del paso existente
docker compose logs --no-color api worker web > "$RUNNER_TEMP/e2e-server.log" 2>&1 || true
node --input-type=module -e '
  import { readFileSync, existsSync, writeFileSync } from "node:fs";
  import { serverLogIsAvailable, composeServerLog } from "./frontend/e2e/runModel.ts";
  const destino = "frontend/e2e-report/server.log";
  const actual  = existsSync(destino) ? readFileSync(destino, "utf8") : null;
  if (serverLogIsAvailable(actual)) { console.log("[ci] server.log del arnés conservado"); }
  else { writeFileSync(destino, composeServerLog(readFileSync(process.env.RUNNER_TEMP + "/e2e-server.log", "utf8"))); }
'
```

Se conserva `if: always()`, `continue-on-error: true`, el nombre `e2e-realtime-<run_id>`, la ruta y la
retención de 7 días; el veredicto del job sigue sin depender de este paso.

### RF-006 — transiciones frente a muestras

```text
countTransitions(muestras):
    n = 0
    para i en 1 .. len(muestras)-1:
        si muestras[i].status != muestras[i-1].status: n += 1
    -> n                                   # [] y [x] -> 0

evaluateView(vista):
    states      = countSamples(artefacto.states)          # como hoy
    transitions = artefacto ? countTransitions(artefacto.states) : null
    -> ViewSummary{ ..., states, transitions, ... }

formatSummaryTable:
    columnas = [VISTA, RESULTADO, DURACIÓN, MUESTRAS, TRANSICIONES, RECARGAS]
    MUESTRAS      -> "retrying=2 connected=1"
    TRANSICIONES  -> "3" | "-"           # "-" cuando es null
```

`schemaVersion` del resumen **no** cambia; el campo se documenta como aditivo y opcional, y el veredicto
0/1/2/3 no lo consulta.

## Interfaz de comandos y variables

| Comando / variable | Contrato |
|---|---|
| `sh infra/scripts/verify_worker_loop_health.sh [servicio\|contenedor]` | 0 verde (transición + sonda), 1 fallo de comportamiento, 2 no ejecutable (Docker, contenedor, argumentos o **entorno no desarrollo/local**; sin escrituras). |
| `WORKER_PROBE_TIMEOUT` | Segundos de espera del efecto de la sonda; defecto **120**; entero positivo; propio, independiente de los tiempos de salud. |
| `WORKER_PROBE_POLL_INTERVAL` | Segundos entre sondeos del estado de la sonda; defecto **2**; entero positivo. |
| `python -m scripts.outbox_probe guard\|insert\|status\|delete` | Solo dentro del contenedor del worker; 0 éxito, 1 fallo (escritura, fila ausente o no borrada), 2 no ejecutable (entorno no desarrollo/local o datos demo ausentes). |
| `pnpm run e2e` / `pnpm run e2e:test` | Sin cambios de contrato; `e2e-report/server.log` se escribe **disponible o declarando no disponible**, siempre con cabecera. |

Ninguna de estas variables entra en `.env.example` ni en Compose: no las consume ningún servicio, así que
`check_env_contract.py` sigue en verde sin cambios.

## Estrategia de pruebas por RF

| RF | Unitaria (siempre) | Opt-in con PostgreSQL (`RUN_DATABASE_TESTS=1`) | Operación con Docker (no suite) | Se declara no ejecutada cuando |
|---|---|---|---|---|
| RF-001 | — | `pytest -q tests/test_invitations.py -k reopen_failure` (fallo inducido, 500, reversión, sin auditoría, sin correo) | — | no hay PostgreSQL; la validación lo dice y no cuenta como verde |
| RF-002 | Aserción de fuente: `_invitation_api_as_user` no sustituye `get_auth_context` | `pytest -q tests/test_invitations.py -k member_without_role` (403 en 10 peticiones, sin efecto, sin correo) | — | no hay PostgreSQL |
| RF-003 | `pytest -q tests/test_outbox_probe.py` (guard, marcador, clasificación, presupuesto, comandos y fuente) + `sh -n infra/scripts/verify_worker_loop_health.sh` | — | `sh infra/scripts/verify_worker_loop_health.sh` → 0 con sonda procesada y fila eliminada | no hay Docker (código 2) o el entorno no es desarrollo/local |
| RF-004 | `pytest -q tests/test_assertion_messages.py` (formateador + barrido `ast` con cero hallazgos) | — | — | nunca: corre en `pytest -q` sin base |
| RF-005 | — | — | `cd frontend && pnpm run e2e` → `e2e-report/server.log` disponible con contenido real | no hay Docker |
| RF-006 | `pnpm test` (`countTransitions`, `transitions` en el resumen, cabeceras `MUESTRAS`/`TRANSICIONES`) | — | — | nunca |
| RF-007 | `pnpm test` (`shouldCaptureScreenshot` + uso en `realtimeScenario.ts`) | — | corrida verde de `pnpm run e2e` sin `screenshots/` | no hay Docker para la parte operativa |
| RF-008 | `pnpm test` (`serverLogIsAvailable`: 6 casos) + `pnpm run typecheck:e2e` | — | smoke local del fragmento de CI con un `server.log` disponible y otro solo con cabecera | la corrida real del job solo se observa en la PR (se declara así) |

Las pruebas existentes no se retiran: el barrido de RF-004 **conserva** las tres comprobaciones de
contenido, y las de UE de la 010 se amplían sin borrar casos.

## Qué RF cubre cada parte

| Parte | RF |
|---|---|
| `test_invitations.py` (atomicidad, helper y prueba sin rol, `raise_app_exceptions`) | RF-001, RF-002 |
| `backend/tests/assertion_messages.py` + `test_assertion_messages.py` + 37 mensajes | RF-004 |
| `backend/scripts/outbox_probe.py` + `test_outbox_probe.py` | RF-003 (unidad) |
| `infra/scripts/verify_worker_loop_health.sh` | RF-003 (operación) |
| `frontend/e2e/observations.ts` + `runModel.ts` (transiciones) | RF-006 |
| `frontend/e2e/observations.ts` + `realtimeScenario.ts` (captura) | RF-007 |
| `frontend/e2e/runModel.ts` + paso de CI | RF-008 |
| Corrida real `pnpm run e2e` | RF-005, RF-007 (evidencia) |
| `README.md` y `AGENTS.md` | RF-002, RF-003, RF-006, RF-007, RF-008 (RNF-007) |

## Riesgos y riesgos residuales

| Riesgo | Mitigación / decisión |
|---|---|
| La prueba de RF-001 depende del nombre importado `record_invitation_audit` en el router: si un refactor cambia el import, el doble deja de aplicarse y el test fallaría por «500 esperado y no observado». | Falla **en rojo**, nunca en verde silencioso: se afirma el 500 y que el doble se ejecutó (`visto` no vacío). Se documenta como acoplamiento aceptado de la prueba. |
| Reescribir 37 mensajes puede perder detalle de diagnóstico. | El mensaje conserva etiqueta + estado + `code`, que es lo que RF-004 declara suficiente; ninguna aserción cambia de semántica. |
| La sonda añade hasta `WORKER_PROBE_TIMEOUT` (120 s) al final de la verificación operativa. | Presupuesto propio y declarado; el total se informa en la salida y en la validación. Las variables permiten ajustarlo sin tocar el script. |
| Un fallo transitorio de Redis hace que la sonda se reintente (5 intentos, 5 s). | `pending`/`processing` se tratan como «sigue esperando»; solo el presupuesto decide, y `failed` informa el `last_error` saneado. |
| La sonda aparece como evento de socket en la sala de la organización demo durante la verificación. | Sin handler de dominio, sin datos personales, caduca por el tope del stream; documentado como inocuo (AGENTS/README). |
| El paso de CI solo se ejerce de verdad en una PR o en `push` a `main`. | `serverLogIsAvailable` queda cubierto por unitarios y el fragmento se prueba localmente con los dos casos; el job no cambia de veredicto. |
| La prueba del miembro sin rol depende del seed demo (`demo-federation`). | Sin ese dato se **omite** con `pytest.skip` explícito y la validación la declara **no ejecutada** (RNF-005). |
| Lectores externos del resumen podrían leer `states` como transiciones (motivo del hueco). | Cabeceras explícitas `MUESTRAS`/`TRANSICIONES`, campo nuevo `transitions` y documentación en README; `schemaVersion` se mantiene y la decisión queda escrita junto al campo. |

**Riesgos residuales aceptados:** `retrying`-style «ruido» de la sonda en el stream de desarrollo; la
verificación del worker sigue sin cobertura automática por PR (Q3); la captura en verde no existe, por
diseño (Q2); `frontend/e2e-report/` sigue fuera de git, así que la evidencia de RF-005 se **cita** en la
validación y no se versiona.

**Sin migraciones y sin job nuevo — cómo se comprueba:** `git status --porcelain infra/postgres` vacío,
`git diff --stat .github/workflows/ci.yml` limitado al cuerpo del paso existente, y
`docker compose config -q` en verde. No se toca `init/`, ni ninguna migración aplicada, ni
`backend/app/`.

## Verificación de constitución

Constitución **1.4.0** (`docs/constitution.md`). No se requiere ninguna excepción de la §5.1.

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 El aislamiento lo garantiza la base de datos | Sí | Las pruebas y la sonda fijan contexto con `set_rls_context` y no esquivan RLS; no hay tablas nuevas. |
| §2.2 La aplicación nunca se salta RLS | Sí | Ni la sonda ni las pruebas usan `DATABASE_ADMIN_URL` ni un rol elevado; la sonda corre con el rol de aplicación del worker. |
| §2.3 Lo publicado es inmutable | Sí | Sin cambios en versiones publicadas, actas ni resultados; las pruebas de invitaciones no tocan torneos. |
| §2.4 Historial de esquema append-only | Sí | Sin migraciones ni edición de migraciones aplicadas (RNF-002); se verifica con `git status --porcelain infra/postgres`. |
| §2.5 Lo público es una proyección mínima | Sí | No se añaden campos públicos; mensajes de fallo, artefactos y `server.log` se publican saneados y sin tokens. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Sin variables nuevas en `.env.example` ni en Compose; `check_env_contract.py` sigue verde. |
| §2.7 Administración global separada y auditada | No | No se toca `/admin`, `platform_admins` ni `platform_audit_logs`. |
| §2.8 Nada se da por terminado sin verificación | Sí | Cada hueco se cierra con la prueba o la corrida citada; lo no ejecutable se declara **no ejecutado** (RNF-005). |
| §2.9 El código de desarrollo no llega a producción | Sí | El guard de entorno rechaza producción y no escribe nada; la sonda no es un seed ni un comando de producción y así se documenta. |
| §3.1 Base de datos y multi-tenancy | Sí | Cumple por ausencia: sin DDL; las consultas nuevas fijan contexto RLS en la transacción. |
| §3.2 Backend | Sí | Sin módulo ni router nuevos; `scripts/outbox_probe.py` es utilidad operativa, no producto; `pytest -q` y `python -m compileall -q app` pasan. |
| §3.3 Frontend | Sí | No se añaden llamadas HTTP ni pantallas; solo arnés y pruebas; `pnpm test`, `typecheck` y `build` pasan. |
| §3.4 Seguridad y configuración | Sí | Sin dependencias nuevas ni supresiones de auditoría; ningún artefacto contiene tokens, cookies ni datos personales. |
| §3.5 Infraestructura y CI | Sí | Versiones de referencia intactas (Python 3.14, Node 24, pnpm 12.12.1; el paso de CI sigue con el mecanismo de Node 24), `docker compose config -q` pasa y no hay job nuevo. |
| §4 «Para todos los cambios»: jobs de CI | Sí | `backend` y `frontend` cubren lo nuevo; `e2e` se ejecuta en la PR y su paso ajustado no cambia el veredicto. |
| §4 «Para todos los cambios»: sin secretos ni datos personales | Sí | Correos y usuarios ficticios; mensajes y artefactos saneados. |
| §4 «Para todos los cambios»: documentación y pruebas | Sí | `README.md` y `AGENTS.md` se actualizan en el mismo cambio; cada comportamiento nuevo o corregido tiene prueba. |
| §4 «Para cambios de base de datos» | No | No hay cambio de esquema. |
| §4 «Para cambios de API o backend» | Sí | Sin rutas ni contratos nuevos; `pytest -q` y `compileall` pasan; ninguna consulta tenant queda sin contexto RLS. |
| §4 «Para cambios de frontend» | Sí | Sin `useApi` nuevo; `pnpm test`, `typecheck` y `build` pasan; `typecheck:e2e` cubre `frontend/e2e/`. |
| §4 «Para cambios de infraestructura o despliegue» | Sí | `docker compose config -q` y el contrato de entorno siguen verdes; no hay defaults de desarrollo accesibles en producción (no se añaden variables). |
| §4 «Para cambios de dependencias» | No | No se añaden ni actualizan dependencias. |
| §5.1 Excepciones | No | No se necesita ninguna. |
| §6 Cumplimiento | Sí | Requiere revisión humana distinta del autor (§6.5): la validación la solicita al cerrar la fase 6. |
