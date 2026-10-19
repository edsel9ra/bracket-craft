# Tareas 002 — Cifrado de la fecha de nacimiento

Spec: `specs/002-cifrado-fecha-nacimiento/spec.md` (aprobada 2026-10-19)
Plan: `specs/002-cifrado-fecha-nacimiento/plan.md`

Orden de dependencia: **T001 → T002 → T003 → T004**; **T002 → T005 → T006 → T007**; **T008** independiente; **T009** después de T007; **T010** al final. El comando de backfill debe existir en la imagen nueva antes de ejecutar 018.

Cada tarea se ejecuta en una sola invocación del implementador y escribe primero sus pruebas.

## Ronda de validación (2026-10-19)

La validación de la spec devolvió cambios necesarios; ya están aplicados y la validación funcional quedó aprobada. Correcciones: el **seed falla cerrado** ante una fecha imposible sin escribir ninguna fila; se añadieron las **cuatro pruebas de RF-011** que faltaban (29 de febrero, seed imposible, delta de `public_age`, paridad completa de claves i18n); la **018** detecta también índices dependientes de `birth_date`; la **vista pública** se prueba sin descifrado ni subconsultas; se verifica la **edad ajustada del jugador reutilizado** por torneo; y se retiró la **rama de confirmación no aprobada** del backfill. Conteos finales: base limpia **242 passed + 2 skipped** (skips de invitaciones opt-in; `RUN_DATABASE_TESTS=1`); con seed demo **244 passed**; frontend **19 tests**, `typecheck` y `build` OK. T001-T010 están hechas; el cierre formal quedó aprobado por el usuario el 2026-10-19.

## Agrupación de commits

| Commit | Tareas | Contenido |
|---|---|---|
| **C1 — `feat(db): cifrar fecha de nacimiento y backfill (R05)`** | T001-T004 | Runner con `MIGRATION_TARGET`, migración 017, comando de backfill y migración 018 |
| **C2 — `feat(api): edad materializada, age en rosters y saneo de errores`** | T005-T008 | Alta/importación, seed/helpers, `age` en el GET y handlers de error |
| **C3 — `feat(web): mostrar edad en plantillas`** | T009 | Etiqueta i18n y refresco del listado |
| **C4 — `docs: runbook de cifrado, MIGRATION_TARGET y cierre`** | T010 | README, AGENTS, configuración de ejemplo, compose y `MEMORY.md` |

C1 debe ir antes que C2 porque el backend nuevo escribe el esquema intermedio. C3 es independiente de C2 en código, pero depende del contrato `age` de T007. C4 va al final. T001 puede separarse como `chore(infra)` si el revisor lo prefiere, pero debe preceder a la aplicación de 017.

---

## T001 — `MIGRATION_TARGET` en `migrate.sh` y pruebas del runner

**Objetivo:** permitir aplicar 017 y 018 en fases, sin `--target`, validando los checksums de todos los archivos y sin detener el recorrido en el target.

**RF:** RF-006, RF-011.

**Estado:** hecha (2026-10-19); `MIGRATION_TARGET` valida formato y existencia antes de aplicar, recorre y verifica los checksums de todos los archivos (también los posteriores al target) y solo omite la aplicación. `infra/scripts/test_migrate_target.sh` crea bases desechables y usa fixtures 017/018 deterministas para probar el runner sin depender de las migraciones funcionales. CI ejecuta la prueba en el job `backend` con PostgreSQL 17. Se corrigió el fallo previo por checksum: `\quit 3` no propaga el código de salida en psql, así que ahora el runner aborta con una excepción explícita.

**Archivos previstos:**
- `infra/postgres/migrate.sh`
- `infra/scripts/test_migrate_target.sh` (nuevo)
- `.github/workflows/ci.yml` (paso de prueba con PostgreSQL)

**Pruebas a escribir primero:**
- `test_migrate_target.sh` crea una base desechable, aplica inicialización y migraciones hasta 016, y comprueba:
  - `MIGRATION_TARGET=017` aplica 017 y no 018; `schema_migrations` lo refleja.
  - Reejecutar `MIGRATION_TARGET=017` no duplica ni falla.
  - `MIGRATION_TARGET=018` aplica 018.
  - `MIGRATION_TARGET=005` sobre una base al día es un no-op y no desaplica.
  - `MIGRATION_TARGET=999`, `ABC` y `17` fallan con código distinto de cero.
  - Un checksum alterado de un archivo **posterior** al target hace fallar el runner.
  - Sin `MIGRATION_TARGET` se aplican todas las pendientes.
  - `--target` no se acepta como mecanismo (solo la variable).

**Criterios de aceptación:**
- `MIGRATION_TARGET` vacío o `NNN`; cualquier otro formato falla antes de aplicar.
- El target debe corresponder a un archivo de migración existente.
- Se recorre `migrations/[0-9]*.sql` completo; nunca se usa `break`.
- El checksum se valida para todos los archivos; el `continue` ocurre después de validar y solo omite la aplicación de los posteriores.
- El bloque de `PLATFORM_ADMIN_EMAIL` se conserva.
- El comportamiento por defecto no cambia.
- `docker compose config -q` sigue pasando en desarrollo.

**Verificación:**
```sh
sh -n infra/postgres/migrate.sh
docker run --rm --network host -v "$PWD/infra:/infra:ro" \
  -e PGHOST=127.0.0.1 -e PGPORT=5432 -e PGUSER=postgres \
  -e PGPASSWORD=postgres_test_password \
  postgres:17-alpine sh /infra/scripts/test_migrate_target.sh
docker compose config -q
```

**Commit:** C1. **Depende de:** nada.

---

## T002 — Migración 017: esquema intermedio, edad y grants

**Objetivo:** agregar el campo cifrado y la edad del jugador, migrar la edad histórica, revocar la fecha en claro a la aplicación, conceder los permisos nuevos y recrear la vista pública.

**RF:** RF-001, RF-002, RF-003, RF-008, RF-010.

**Estado:** hecha (2026-10-19); `017_player_birth_date_encryption.sql` habilita el esquema intermedio en una sola transacción: agrega `birth_date_encrypted` (bytea, nullable), `age_at_reference` y `age_reference_year` (smallint, `NOT NULL` tras materializar la edad histórica), rechaza fechas nulas, futuras o posteriores a `created_at` UTC con un reporte de conteo e ids internos sin el valor, revoca `SELECT`/`INSERT` de `birth_date` a `bracket_app` y `PUBLIC`, concede `INSERT` del cifrado y `SELECT`/`INSERT` de la edad, deja `birth_date` nullable y recrea `v_public_tournament_players` con `public_age` entero y la misma forma. La referencia histórica usa el torneo del roster con menor `registered_at` (desempate por `id`) y `created_at` UTC si no hay roster; las filas ya cifradas por la app nueva no se sobrescriben al reejecutar. Verificado con las 9 pruebas de `tests/test_birth_date_encryption_migration.py`, `init + 001-017` con el runner real, `MIGRATION_TARGET=017` sobre una base migrada con 96 jugadores (edad y vista idénticas a la fórmula anterior) y `pytest -q` unitaria. La suite con base sigue roja entre 017 y T006 porque `db_helpers` y el seed aún insertan `birth_date` (esperado).

**Archivos previstos:**
- `infra/postgres/migrations/017_player_birth_date_encryption.sql` (nuevo)
- `backend/tests/birth_date_migration_helpers.py` (nuevo; base desechable, init, migraciones por rango, seed)
- `backend/tests/test_birth_date_encryption_migration.py` (nuevo)

**Pruebas a escribir primero:**
- Aplicar init + 001-016 en una base desechable, sembrar dos organizaciones, torneos con años distintos, rosters con `registered_at` distinto, un jugador sin roster y fechas conocidas; aplicar 017 y comprobar:
  - `birth_date_encrypted` existe y es nullable; `age_at_reference` y `age_reference_year` existen y son `NOT NULL`.
  - La edad usa el torneo del roster con menor `registered_at` (desempate por `id`); el jugador sin roster usa `created_at` en UTC.
  - `birth_date` sigue existiendo y es nullable.
  - `bracket_app` no puede `SELECT` ni `INSERT` `birth_date`; no puede `SELECT` `birth_date_encrypted`; sí puede `SELECT`/`INSERT` la edad y `INSERT` el cifrado.
  - `v_public_tournament_players` conserva nombre, orden y tipos, con `public_age` entero y el valor esperado; `v_public_match_lineups` sigue funcionando.
  - Una fila con fecha futura, nula o posterior a `created_at` bloquea 017 con un reporte sin la fecha.
  - Reejecutar 017 en el estado intermedio no duplica ni falla.
- Prueba de volumen limpio: init + 001-017 funciona.

**Criterios de aceptación:**
- 017 no edita ninguna migración aplicada.
- La vista se recrea antes de que 018 elimine la columna.
- El propietario de la vista sigue exento de RLS y sin `security_invoker`.
- Los grants y revocaciones son exactamente los del plan.
- La migración es transaccional y respeta checksums.

**Verificación:**
```sh
sh -n infra/postgres/migrate.sh
cd backend && RUN_DATABASE_TESTS=1 \
  DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_birth_date_encryption_migration.py
cd backend && python -m compileall -q app
```

**Commit:** C1. **Depende de:** T001 para el runbook; el SQL puede escribirse en paralelo.

---

## T003 — Comando `scripts.encrypt_birth_dates`

**Objetivo:** cifrar las filas históricas por lotes con verificación previa de clave y HMAC, reanudación e idempotencia, sin PII en logs.

**RF:** RF-001, RF-004, RF-010, RF-011.

**Estado:** hecha (2026-10-19); `scripts/encrypt_birth_dates.py` verifica `PLAYER_DATA_KEY` antes de escribir descifrando un documento con `pgp_sym_decrypt` y contrastando siempre su HMAC (comparación en tiempo constante); con tabla vacía es un no-op sin confirmación y, con filas y sin ningún documento cifrado, aborta: no existe una rama de confirmación. Detecta el esquema final tras 018 (sale 0), rechaza fechas nulas, futuras o posteriores a `created_at` UTC antes de escribir (incluidos jugadores sin roster), cifra por lotes de 500 con `LIMIT`/`ORDER BY id` y commit por lote, se detiene si un lote no reduce pendientes, es idempotente y reanudable, y verifica al final cero pendientes y que todas las filas descifren al valor original. Los logs solo contienen conteos, lotes, duración e ids internos en errores de datos; los errores de SQLAlchemy solo registran clase y SQLSTATE. Verificado con las 19 pruebas de `tests/test_birth_date_backfill.py`, `python -m scripts.encrypt_birth_dates` real sobre una base en estado 017 (4 filas, dos ejecuciones con salida 0, 0 pendientes y 0 desajustes), `compileall` y `pytest -q` unitaria (132 passed, 84 skipped).

**Archivos previstos:**
- `backend/scripts/encrypt_birth_dates.py` (nuevo)
- `backend/tests/test_birth_date_backfill.py` (nuevo; reutiliza el helper de T002)

**Pruebas a escribir primero:**
- Clave correcta: descifra una muestra de `national_id_encrypted` y el HMAC coincide; el comando cifra todas las pendientes.
- Clave incorrecta o HMAC manipulado: aborta sin escribir; `birth_date_encrypted` sigue nulo.
- Tabla vacía: no-op, salida 0, sin pedir confirmación.
- Lotes de 500: con más de 500 filas se ejecutan varios lotes y todos quedan cifrados.
- Idempotencia: la segunda ejecución no re-cifra y sale 0.
- Reanudación: se cifra parte de la tabla, se ejecuta y solo procesa pendientes.
- Fila pendiente sin `birth_date`: falla y la reporta; no inventa.
- Un lote que no reduce el número de pendientes falla en lugar de entrar en bucle.
- Fecha futura/posterior a `created_at`, incluido un jugador sin roster: falla antes de escribir.
- Después de 018: detecta el esquema final y sale 0 sin hacer nada.
- Logs: `caplog` no contiene fecha, documento, nombre, texto cifrado ni clave; solo conteos/lotes/duración.

**Criterios de aceptación:**
- `python -m scripts.encrypt_birth_dates` funciona desde `backend/`.
- `DATABASE_ADMIN_URL` es obligatorio; `PLAYER_DATA_KEY` se lee con el guard de configuración.
- La verificación de clave es previa, obligatoria y con contraste de HMAC siempre.
- El commit es por lote; un fallo deja lo anterior cifrado y permite reanudar.
- La verificación final exige cero pendientes y que todas las filas procesadas descifren al valor original.
- No se registran valores sensibles en errores de SQLAlchemy.

**Verificación:**
```sh
cd backend && python -m compileall -q app
cd backend && RUN_DATABASE_TESTS=1 \
  DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_birth_date_backfill.py
cd backend && DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  PLAYER_DATA_KEY="<clave-de-prueba>" python -m scripts.encrypt_birth_dates
```

**Commit:** C1. **Depende de:** T002.

---

## T004 — Migración 018: fallo cerrado y eliminación de la fecha en claro

**Objetivo:** verificar que no quedan pendientes, hacer obligatorio el cifrado, eliminar `birth_date` y dejar los grants finales.

**RF:** RF-001, RF-002, RF-005, RF-011.

**Estado:** hecha (2026-10-19); `018_player_birth_date_plaintext_removal.sql` cierra el esquema en una sola transacción. La comprobación de pendientes (`birth_date_encrypted IS NULL`, con conteo y sin valores) y la de dependencias de `players.birth_date` (vistas, vistas materializadas, índices y funciones SQL, con sus nombres) ocurren antes de cualquier DDL y fallan con un mensaje `MIGRACION 018`. Después hace `NOT NULL` el cifrado, elimina `birth_date` y reafirma los grants finales del plan: `SELECT` de las columnas permitidas y de la edad, `INSERT` del cifrado y la edad, sin `SELECT` del cifrado y sin `UPDATE`/`DELETE`. La guarda por ausencia de `birth_date` convierte la reejecución directa en un no-op. Verificado con las 15 pruebas de `tests/test_birth_date_encryption_migration.py` (6 nuevas), la secuencia real 016 → `MIGRATION_TARGET=017` → `python -m scripts.encrypt_birth_dates` → `MIGRATION_TARGET=018` con el runner sobre una base desechable, init + todas las migraciones en volumen limpio, las 19 pruebas de `tests/test_birth_date_backfill.py`, `sh -n infra/postgres/migrate.sh`, `infra/scripts/test_migrate_target.sh` y `pytest -q` unitaria (132 passed, 90 skipped).

**Archivos previstos:**
- `infra/postgres/migrations/018_player_birth_date_plaintext_removal.sql` (nuevo)
- `backend/tests/test_birth_date_encryption_migration.py` (ampliar)

**Pruebas a escribir primero:**
- 018 sobre 017 con una fila `birth_date_encrypted IS NULL` falla, no elimina `birth_date` y no deja cambios parciales.
- 018 tras un backfill completo aplica `NOT NULL`, elimina `birth_date` y conserva conteos/referencias.
- 018 sobre una base limpia sin jugadores funciona.
- 018 falla si una vista depende todavía de `birth_date`.
- Tras 018, `bracket_app` no puede leer el cifrado; sí inserta cifrado y edad; no lee `birth_date` porque no existe.
- Reejecutar 018 directamente no falla por objetos existentes.
- La vista pública y `v_public_match_lineups` siguen funcionando tras eliminar la columna.

**Criterios de aceptación:**
- La migración es transaccional.
- La comprobación de pendientes ocurre antes de cualquier `DROP`.
- La comprobación de dependencias produce un error claro.
- Los grants finales coinciden con el plan.
- No se edita ninguna migración aplicada.

**Verificación:**
```sh
sh -n infra/postgres/migrate.sh
cd backend && RUN_DATABASE_TESTS=1 \
  DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_birth_date_encryption_migration.py
```

**Commit:** C1. **Depende de:** T003.

---

## T005 — Backend: alta e importación con fecha cifrada y edad

**Objetivo:** escribir la fecha cifrada y la edad en el jugador al crear/importar y reutilizar al jugador existente sin actualizar la fecha.

**RF:** RF-001, RF-002, RF-007, RF-010.

**Estado:** hecha (2026-10-19); `_create_roster_player_record` obtiene `tournaments.start_date` en la misma consulta que valida el equipo y `_find_or_create_player_record` inserta `birth_date_encrypted` con `pgp_sym_encrypt(...)` y `age_at_reference`/`age_reference_year` calculados con el año del torneo, omitiendo `birth_date` por completo; la reutilización por HMAC devuelve el jugador existente sin tocar fecha ni edad. Se añadieron pruebas de extremo a extremo como `bracket_app` (sin «permission denied», edad 26/referencia 2026 para fecha 2000-01-01 y torneo 2026, descifrado exacto tras `RESET ROLE`, respuesta sin fecha ni `age`), de reutilización con otra fecha y de importación CSV (todas las filas válidas cifradas; una fecha inválida rechaza el archivo antes de escribir), más la unidad de importación que exige `birth_date` y rechaza el archivo completo. Verificado con las 4 pruebas nuevas en verde, `tests/test_roster_import.py` en verde, `pytest -q` sin base (134 passed, 93 skipped) y `compileall`. La suite con base sigue roja en las 11 pruebas que dependen de `db_helpers.insert_player` y `seed_demo` (insertan `birth_date` en claro) y de los grants/esquema que esperan la columna: es el alcance de T006.

**Archivos previstos:**
- `backend/app/modules/tournaments/router.py`
- `backend/tests/test_player_catalog_isolation.py`
- `backend/tests/test_roster_import.py`

**Pruebas a escribir primero:**
- Alta individual: inserta `birth_date_encrypted`, `age_at_reference`, `age_reference_year`; no escribe `birth_date`; la respuesta no incluye fecha ni edad.
- Alta en un torneo con `start_date` 2026 y fecha 2000-01-01: `age_at_reference` = 26 y referencia 2026.
- Jugador reutilizado con otra fecha: conserva la edad y la referencia originales; no se descifra ni se actualiza.
- Importación CSV/ZIP: todas las filas válidas se cifran; una fecha inválida revierte el archivo completo.
- El rol de aplicación tiene los grants de inserción; el alta no falla con «permission denied».
- Aislamiento: A y B con el mismo documento no comparten jugador ni edad.

**Criterios de aceptación:**
- El `INSERT` de jugador omite `birth_date` y usa el cifrado y la edad.
- La referencia de un alta nueva es el año de `tournaments.start_date`.
- La reutilización por HMAC no modifica la fecha ni la edad.
- La importación sigue exigiendo `birth_date` y siendo atómica.
- `_load_roster_player` y `RosterPlayerResponse` no cambian.

**Verificación:**
```sh
cd backend && pytest -q
cd backend && RUN_DATABASE_TESTS=1 \
  DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_player_catalog_isolation.py tests/test_roster_import.py
cd backend && python -m compileall -q app
```

**Commit:** C2. **Depende de:** T002.

---

## T006 — Seed, helpers y regresión de esquema

**Objetivo:** adaptar el seed y los helpers de prueba al nuevo esquema y actualizar las pruebas de grants/esquema que hoy esperan `birth_date` en claro.

**RF:** RF-001, RF-007, RF-011.

**Estado:** hecha (2026-10-19); `db_helpers.insert_player` cifra la fecha con `pgp_sym_encrypt` y `PLAYER_DATA_KEY`, materializa `age_at_reference`/`age_reference_year` con un `reference_year` explícito (o el año actual si se omite) y no escribe `birth_date`; `seed_demo._ensure_rosters` calcula la referencia con `start_date.year`, cifra la fecha y reutiliza el jugador existente sin tocar edad ni fecha. Las pruebas de esquema afirman que `birth_date` ya no existe, que `birth_date_encrypted` es solo `INSERT` y que la edad es `SELECT`/`INSERT`. Se añadió una prueba de seed de extremo a extremo (idempotencia, roster, edad y descifrado como administrador), se actualizó el seed de inmutabilidad para migrar hasta 018 y se hicieron deterministas las pruebas de `insert_player` que comparan edades. Verificado con `pytest -q` (134 passed, 94 skipped), la suite con BD sobre una base migrada y sembrada (228 passed) y `python -m compileall -q app scripts`. El seed real ejecutado dos veces es idempotente, deja 96 jugadores con roster, cero `birth_date` en claro y edades correctas.

**Archivos previstos:**
- `backend/scripts/seed_demo.py`
- `backend/tests/db_helpers.py`
- `backend/tests/test_player_catalog_schema.py`
- `backend/tests/test_seed_demo.py`
- `backend/tests/test_player_catalog_isolation.py` (ajustes de seed)

**Pruebas a escribir primero:**
- `insert_player` inserta cifrado y edad; ninguna prueba que use el helper escribe `birth_date`.
- Seed: idempotente, cifra, materializa edad y no deja jugadores sin roster.
- Grants: `birth_date` fuera de `SELECT`/`INSERT` de `bracket_app`; `birth_date_encrypted` solo `INSERT`; edad en `SELECT`/`INSERT`.
- La búsqueda de jugador del seed sigue filtrando por organización.
- La suite existente que usa `insert_player` sigue en verde.

**Criterios de aceptación:**
- `seed_demo` calcula la referencia con `start_date.year`.
- `db_helpers` usa `pgp_sym_encrypt` y permite un `reference_year` explícito.
- No queda ningún `INSERT` de prueba con `birth_date`.
- Las pruebas de esquema reflejan los grants finales del plan.

**Verificación:**
```sh
cd backend && pytest -q
cd backend && RUN_DATABASE_TESTS=1 \
  DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_player_catalog_schema.py tests/test_seed_demo.py \
           tests/test_player_catalog_isolation.py
cd backend && python -m compileall -q app
```

**Commit:** C2. **Depende de:** T005.

---

## T007 — GET de rosters: `age` con modelo separado

**Objetivo:** exponer `age` solo en `GET /tournaments/{id}/rosters`, sin cambiar las respuestas de alta/importación.

**RF:** RF-009, RF-008, RF-011.

**Estado:** hecha (2026-10-19); `RosterPlayerResponse` queda intacto y se añade `RosterPlayerListResponse(RosterPlayerResponse)` con `age: int`, usado solo por `GET /tournaments/{id}/rosters`. El listado une `tournaments` por `(id, organization_id)` en la misma consulta y calcula `(p.age_at_reference + (EXTRACT(YEAR FROM t.start_date)::INT - p.age_reference_year))::INT AS age`, sin descifrar ni añadir consultas por fila. Verificado con las 5 pruebas de `tests/test_roster_age.py` (contrato de escritura sin `age`, edades conocidas, delta por año de `start_date`, recuento constante de sentencias con 1 y 5 jugadores, aislamiento A/B y ausencia de fecha/texto cifrado), `tests/test_player_catalog_isolation.py` sin cambios y en verde, `pytest -q` (135 passed, 98 skipped), suite completa con BD (233 passed) y `compileall`.

**Archivos previstos:**
- `backend/app/modules/tournaments/schemas.py`
- `backend/app/modules/tournaments/router.py`
- `backend/tests/test_roster_age.py` (nuevo)
- `backend/tests/test_player_catalog_isolation.py` (ajustes)

**Pruebas a escribir primero:**
- `GET /tournaments/{id}/rosters` devuelve `age` entero y el valor de la fórmula para fechas/torneos conocidos.
- Cambiar el año de `start_date` cambia `age` en el delta; dentro del mismo año no cambia.
- Alta, importación y foto no incluyen `age` (contrato sin cambios).
- La consulta no ejecuta una consulta adicional por jugador (misma consulta con join).
- Aislamiento: el contexto B no ve rosters de A.
- La respuesta no incluye fecha ni texto cifrado.

**Criterios de aceptación:**
- `RosterPlayerResponse` queda intacto para alta/importación/foto.
- Se agrega `RosterPlayerListResponse` con `age: int` y se usa solo en el listado.
- El cálculo es el mismo que la vista pública y usa `(age_at_reference + (año_torneo − age_reference_year))::INT`.
- No se descifra ni se añade una consulta por fila.

**Verificación:**
```sh
cd backend && pytest -q
cd backend && RUN_DATABASE_TESTS=1 \
  DATABASE_URL="postgresql+asyncpg://bracket_app:...@127.0.0.1:5432/bracket_craft" \
  DATABASE_ADMIN_URL="postgresql+asyncpg://postgres:...@127.0.0.1:5432/bracket_craft" \
  pytest -q tests/test_roster_age.py tests/test_player_catalog_isolation.py
```

**Commit:** C2. **Depende de:** T006.

---

## T008 — Saneo de `RequestValidationError` y errores de base de datos

**Objetivo:** impedir que la fecha o el documento aparezcan en el cuerpo 422 o en logs de PostgreSQL.

**RF:** RF-012, RF-010, RF-011.

**Estado:** hecha (2026-10-19); `app/main.py` registra un handler de `RequestValidationError` que conserva solo `type`, `loc` y `msg` (elimina `input` y `ctx`, incluido el `ValueError` original) y mantiene la forma `{"detail": [...]}` que consume el frontend; un `DBAPIError` no controlado responde 500 con `{"detail": "Error interno del servidor"}` y registra únicamente el SQLSTATE (o «desconocido»), sin `str(exc)`, sentencia, parámetros ni fila. No se añadió identificador de correlación porque el proyecto no tiene un patrón previo. Las 4 pruebas de `tests/test_error_sanitization.py` cubren el handler directo, una petición real con `birth_date` futura (422 sin fecha ni documento), el `DBAPIError` con «Failing row contains» (500 genérico y `caplog` sin PII) y la traducción existente de `IntegrityError` a 409 en `POST /tournaments/{id}/stages`. Verificado con `pytest -q` sin base (139 passed, 98 skipped), la suite completa con BD (237 passed) y `python -m compileall -q app`.

**Archivos previstos:**
- `backend/app/main.py`
- `backend/tests/test_error_sanitization.py` (nuevo)
- `backend/tests/test_api_access.py` (si se añade prueba de extremo a extremo)

**Pruebas a escribir primero:**
- Un `RequestValidationError` con `input` que contiene una fecha produce un 422 sin `input` ni `ctx` y sin la fecha en el cuerpo.
- Una petición real con `birth_date` futura (con auth y DB simulados) devuelve 422 sin el valor.
- Un `DBAPIError` cuyo texto simula «Failing row contains <fecha>» produce 500 genérico y el log capturado no contiene la fecha, el documento ni la fila.
- Los `IntegrityError` que los routers traducen a 409 conservan su respuesta.
- El handler no registra `statement`, `params` ni `str(exc)`.

**Criterios de aceptación:**
- El cuerpo 422 conserva `type`, `loc` y `msg`, y elimina `input`/`ctx`.
- El handler de `DBAPIError` solo registra el SQLSTATE y devuelve un mensaje genérico.
- No se altera el comportamiento de los errores de negocio existentes.
- Los logs de la aplicación no contienen PII.

**Verificación:**
```sh
cd backend && pytest -q tests/test_error_sanitization.py
cd backend && pytest -q
cd backend && python -m compileall -q app
```

**Commit:** C2. **Depende de:** nada (puede ir en paralelo con T005-T007).

---

## T009 — Frontend: edad, i18n y refresco del listado

**Objetivo:** mostrar `age` en la tarjeta de roster del Workspace, con etiqueta i18n es/en, y conservar el refresco tras alta/importación.

**RF:** RF-009, RF-011.

**Estado:** hecha (2026-10-19); `RosterSummary` incluye `age: number` y la tarjeta de roster lo muestra con `t('setup.age', { age: roster.age })`; la clave `setup.age` existe en `es` (`Edad: {age}`) y `en` (`Age: {age}`), con paridad de 609 claves por idioma. Se conservan el `await loadConfiguration()` tras `importRoster` y el `await refreshOperation()` tras el alta individual (`addRosterPlayer`), sin tocar endpoints ni el contrato de alta/importación y sin mostrar ni solicitar la fecha en el listado. El nuevo `tests/roster-age.test.ts` es estático (mismo patrón `node:test` del proyecto, sin dependencias nuevas) porque no hay harness de componentes. Verificado con `pnpm test` (19 passed), `pnpm run typecheck` y `pnpm run build` en el contenedor `bc-web-t007` (Node 24.22.0, pnpm 12.12.1), porque el host no tiene pnpm operativo.

**Archivos previstos:**
- `frontend/app/pages/workspace/tournaments/[id].vue`
- `frontend/app/composables/useI18n.ts`
- `frontend/tests/roster-age.test.ts` (nuevo)

**Pruebas a escribir primero:**
- Test estático: `setup.age` existe en los bloques `es` y `en` de `useI18n.ts`.
- Test estático: `RosterSummary` incluye `age` y la tarjeta lo renderiza.
- Test estático: `importRoster` conserva `loadConfiguration()` después de la importación y el alta conserva `refreshOperation()`.
- Si el plan detecta que el refresco falta, la prueba debe fallar primero y luego se agrega la llamada.

**Criterios de aceptación:**
- La tarjeta muestra `Edad: {age}` / `Age: {age}`.
- El listado se refresca tras crear o importar.
- No se muestra ni se solicita la fecha después del alta.
- `age` solo se consume de `GET /tournaments/{id}/rosters`; no se añaden endpoints.
- Los checks de frontend pasan.

**Verificación:**
```sh
cd frontend && pnpm test
cd frontend && pnpm run typecheck
cd frontend && pnpm run build
```

**Commit:** C3. **Depende de:** T007.

---

## T010 — Documentación, runbook, configuración y cierre

**Objetivo:** documentar el cifrado, `MIGRATION_TARGET`, el servicio one-off, la secuencia de despliegue y la reversión; validar el conjunto y actualizar `MEMORY.md`.

**RF:** RF-006, RF-012, RNF-012; validación global de RF-001 a RF-012.

**Estado:** hecha (2026-10-19); README y AGENTS documentan el cifrado *write-only*, `MIGRATION_TARGET`, `DATABASE_ADMIN_URL`, el backfill one-off con `--no-deps`, la secuencia **017 → imagen nueva → backfill → 018**, la copia de seguridad verificada, la ventana de mantenimiento, el smoke y la reversión en tres tramos (antes de 017, entre 017 y 018 y solo *forward-fix* después de 018). `.env.example` documenta `MIGRATION_TARGET` y la conexión administrativa sin credenciales reales; `db-migrate` recibe `MIGRATION_TARGET` con default vacío en desarrollo y en el overlay de producción. Verificado con `pytest -q` en base limpia (242 passed, 2 skipped: invitaciones opt-in), la suite con seed demo (244 passed), `compileall -q app scripts`, frontend con Node 24.22.0/pnpm 12.12.1 (`pnpm test` 19 passed, `typecheck` y `build`), `sh -n`, `test_migrate_target.sh` sobre PostgreSQL 17 desechable, `docker compose config -q` en desarrollo y en el merge de producción con dummies, `assert_production_compose.py` y `verify_version_sources.py`. No ejecutado: smoke del runbook en un despliegue real ni la secuencia 017→backfill→018 en producción. La spec quedó `implementada` tras la aprobación explícita del usuario (2026-10-19).

**Archivos previstos:**
- `README.md`
- `AGENTS.md`
- `.env.example`
- `docker-compose.yml`
- `docker-compose.production.yml`
- `MEMORY.md`

**Pruebas/verificaciones a escribir primero:**
- Comprobación textual de que README/AGENTS incluyen `python -m scripts.encrypt_birth_dates`, `MIGRATION_TARGET`, `DATABASE_ADMIN_URL`, `--no-deps` y la secuencia 017 → imagen nueva → backfill → 018.
- `docker compose config -q` en desarrollo y en el merge de producción con variables dummy.
- `sh -n infra/postgres/migrate.sh`.
- La configuración de ejemplo no contiene secretos reales.
- Validación final: `cd backend && pytest -q`, `compileall`, suite de BD, `pnpm test`/`typecheck`/`build`, y revisión de cada RF y criterio de finalización.

**Criterios de aceptación:**
- `.env.example` documenta `MIGRATION_TARGET` (no secreto) y la conexión administrativa sin valores reales.
- `db-migrate` recibe `MIGRATION_TARGET` desde el entorno; por defecto vacío.
- El runbook incluye backup, mantenimiento, 017, imagen nueva, backfill, 018, arranque y smoke.
- La reversión distingue antes de 017, entre 017 y 018 y después de 018; solo *forward-fix* tras 018.
- No se edita `docs/constitution.md`.
- No se añaden defaults de producción ni secretos.
- `MEMORY.md` queda actualizado con: spec 002, estado real, migraciones 017/018, comando de backfill, `MIGRATION_TARGET`, decisiones de edad/`age`, y verificaciones no ejecutadas.
- La spec se marca `implementada` tras la aprobación explícita del usuario (2026-10-19).

**Verificación:**
```sh
cd backend && pytest -q
cd backend && python -m compileall -q app
cd frontend && pnpm test && pnpm run typecheck && pnpm run build
sh -n infra/postgres/migrate.sh
docker compose config -q
POSTGRES_PASSWORD=dummy BRACKET_DB_PASSWORD=dummy PLATFORM_ADMIN_EMAIL=dummy@example.test \
JWT_SECRET=dummy-jwt-secret-with-at-least-32-characters \
PLAYER_DATA_KEY=dummy-player-key-with-at-least-32-characters \
INVITATION_TOKEN_KEY=dummy-invitation-key-with-at-least-32-characters \
DATABASE_URL=postgresql+asyncpg://dummy:dummy@db:5432/dummy \
CORS_ALLOWED_ORIGINS=http://localhost:3000 \
STORAGE_PROVIDER=s3 STORAGE_BUCKET=dummy STORAGE_PUBLIC_BASE_URL=http://localhost:9000/dummy \
FRONTEND_BASE_URL=http://localhost:3000 SMTP_HOST=localhost SMTP_FROM=noreply@example.test \
NUXT_PUBLIC_API_BASE=http://localhost:8000/api/v1 \
NUXT_PUBLIC_SOCKET_BASE=http://localhost:8000 \
NUXT_API_INTERNAL_BASE=http://api:8000/api/v1 PROXY_NETWORK=edge \
docker compose -f docker-compose.yml -f docker-compose.production.yml config -q
```

**Commit:** C4. **Depende de:** T001-T009.

---

## Resumen de tareas

| Tarea | Contenido | Commit |
|---|---|---|
| T001 | `MIGRATION_TARGET` y pruebas del runner | C1 |
| T002 | Migración 017 | C1 |
| T003 | Comando de backfill | C1 |
| T004 | Migración 018 | C1 |
| T005 | Alta e importación con fecha cifrada y edad | C2 |
| T006 | Seed, helpers y regresión de esquema | C2 |
| T007 | `age` en el GET de rosters | C2 |
| T008 | Saneo de 422 y errores de BD | C2 |
| T009 | Frontend: i18n y refresco | C3 |
| T010 | Documentación, runbook, configuración y cierre | C4 |
