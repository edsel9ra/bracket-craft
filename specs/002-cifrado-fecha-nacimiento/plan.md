# Plan 002 — Cifrado de la fecha de nacimiento de jugadores

Estado: aprobado e implementado (2026-10-19); validación funcional aprobada; pendiente de cierre

Spec: `specs/002-cifrado-fecha-nacimiento/spec.md` (aprobada 2026-10-19)

## 1. Resumen técnico

El plan cierra **R05** sin reabrir el modelo multi-tenant de la spec 001:

- **Cifrado en reposo:** `players.birth_date` deja de existir en claro. La fecha se guarda cifrada con `PLAYER_DATA_KEY` en `birth_date_encrypted`, *write-only* para `bracket_app`, igual que `national_id_encrypted`.
- **Edad materializada en el jugador:** `players.age_at_reference` y `players.age_reference_year` guardan la edad al año de referencia. La edad ajustada se calcula con `age_at_reference + (año del torneo − age_reference_year)`, equivalente a `año del torneo − año de nacimiento`.
- **Migraciones en dos fases:** **017** habilita el esquema intermedio (campo cifrado, edad, grants, revocación de la fecha en claro y vista pública); **018** verifica que no queden pendientes, hace obligatorio el cifrado y elimina la columna en claro.
- **Backfill:** `python -m scripts.encrypt_birth_dates`, con conexión administrativa, verificación previa de la clave contra el documento cifrado y su HMAC, lotes de 500, idempotente, reanudable y sin PII en logs.
- **Despliegue:** `infra/postgres/migrate.sh` acepta `MIGRATION_TARGET`; la secuencia es mantenimiento → 017 → imagen nueva → backfill → 018 → arranque. El runner valida los checksums de **todos** los archivos y solo omite la aplicación de los posteriores al target.
- **Contrato:** `age` se agrega **solo** a `GET /tournaments/{id}/rosters`; alta e importación no cambian. La UI muestra la edad con etiqueta i18n es/en y refresca el listado.
- **Errores:** se sanean `RequestValidationError` (sin `input`/`ctx` con valores) y `DBAPIError` (sin fila, SQL ni parámetros en logs).

No se modifica `docs/constitution.md`: §3.4 ya exige este estado y la edad derivada es el dato público que la proyección ya exponía.

## 2. Estado de partida y supuestos

- Migraciones aplicadas hasta **016**; `players` es tenant-owned con RLS `FORCE`, `organization_id`, unicidad por organización y FKs compuestas (spec 001).
- `players.birth_date DATE NOT NULL` en claro; `national_id_encrypted BYTEA NOT NULL` fuera del `SELECT` de `bracket_app`; `national_id_hmac VARCHAR(64) NOT NULL`.
- `bracket_app` tiene `SELECT`/`INSERT` por columnas; no tiene `UPDATE` ni `DELETE` sobre `players`.
- Harness PostgreSQL en CI: `DATABASE_URL` (rol de aplicación) y `DATABASE_ADMIN_URL` (rol administrador); migraciones aplicadas con el runner real.
- `v_public_tournament_players` calcula hoy `public_age` uniendo `players.birth_date`; `v_public_match_lineups` no usa la fecha.
- Versiones de referencia: Python 3.14, Node 24 y pnpm 12.12.1.
- El seed de desarrollo crea jugadores y rosters y debe seguir funcionando.

## 3. Decisiones de diseño por RF

### RF-001/RF-002 — Cifrado, *write-only* y RLS

**Decisión 1: una sola fuente cifrada y ninguna copia en claro.**

- `birth_date_encrypted BYTEA` se cifra con `pgp_sym_encrypt(CAST(:birth_date AS TEXT), :player_data_key)`.
- La columna en claro se conserva solo durante la ventana 017→018 y únicamente para el backfill administrativo; se elimina en 018.
- No se crea una columna de año de nacimiento. La edad y el año de referencia son el dato derivado que la proyección ya publicaba.
- Alternativa descartada: cifrar la fecha en la aplicación con una librería simétrica nueva. Se descarta porque duplica el mecanismo ya usado para el documento y añade una dependencia.
- Alternativa descartada: guardar el año de nacimiento en claro. Se descarta por la decisión del usuario y porque el año ya es inferible desde la edad pública sin añadir otra columna.

**Decisión 2: grants por columna y RLS intacto.**

- 017 **revoca** `SELECT (birth_date)` e `INSERT (birth_date)` a `bracket_app`.
- 017 **concede** `SELECT (age_at_reference, age_reference_year)` e `INSERT (birth_date_encrypted, age_at_reference, age_reference_year)`.
- `birth_date_encrypted` queda fuera del `SELECT`; `national_id_encrypted` sigue igual.
- No se concede `UPDATE` ni `DELETE`; RLS `FORCE` y la política tenant no se tocan.
- Alternativa descartada: conceder `SELECT` del texto cifrado y descifrar en la aplicación. Se descarta porque rompe el patrón *write-only* y no es necesario: la edad se materializa.

### RF-003 — Migración 017

**Decisión 3: esquema intermedio operativo y edad histórica determinista.**

Orden de la migración:

1. Agregar `birth_date_encrypted BYTEA` nullable.
2. Agregar `age_at_reference SMALLINT` y `age_reference_year SMALLINT` nullable.
3. Validar fechas imposibles: nulas, posteriores a `CURRENT_DATE` o posteriores a `(created_at AT TIME ZONE 'UTC')::date`. Si hay filas, `RAISE EXCEPTION` con conteo e identificadores internos (sin fecha).
4. Calcular el año de referencia histórico:
   - jugador con rosters: el `tournaments.start_date` del roster con menor `registered_at`; desempate por `rosters.id`;
   - jugador sin roster: `EXTRACT(YEAR FROM players.created_at AT TIME ZONE 'UTC')`.
5. Calcular `age_at_reference = age_reference_year - EXTRACT(YEAR FROM birth_date)::INT`.
6. Dejar `age_at_reference` y `age_reference_year` `NOT NULL`.
7. Hacer `birth_date` nullable (la app nueva inserta sin ella).
8. Revocar `SELECT`/`INSERT` de `birth_date`; conceder los permisos nuevos.
9. Recrear `v_public_tournament_players` con `(age_at_reference + (EXTRACT(YEAR FROM t.start_date)::INT - age_reference_year))::INT AS public_age`, mismo nombre, orden y tipos de columna, `security_barrier = true`, sin `security_invoker`.
10. Mantener `birth_date` en claro para el backfill; solo el rol administrativo puede leerla.

Pseudocódigo del cálculo histórico:

```text
refs = for each player:
    if exists roster:
        ref_year = year(start_date of tournament of min(registered_at, id) roster)
    else:
        ref_year = year(created_at in UTC)
    age = ref_year - year(birth_date)
```

Alternativa descartada: calcular la referencia con `valid_from`. Se descarta porque `registered_at` es la marca de alta del roster, no una fecha deportiva configurable, y es la que mejor representa el momento en que se fijó la edad.
Alternativa descartada: usar el año actual para todos. Se descarta porque introduce el reloj en la migración y rompe el determinismo de las pruebas.

### RF-004 — Comando de backfill

**Decisión 4: verificación previa contra el documento cifrado y lotes reanudables.**

`backend/scripts/encrypt_birth_dates.py` expone:

```text
async def run(admin_url, player_data_key, batch_size=500) -> int
def main() -> int
```

Flujo:

1. Crear un engine asíncrono con `DATABASE_ADMIN_URL`; usar `get_settings().player_data_key` en `main()` y permitir la clave como parámetro en `run()` para pruebas.
2. Detectar el esquema: si no existe `birth_date`, comprobar que `birth_date_encrypted` existe y es obligatoria; si no es obligatoria, fallar; si es obligatoria, registrar «nada que hacer» y salir 0.
3. Si la tabla `players` está vacía, registrar el no-op y salir 0. La rama sin documento solo existe con la tabla vacía porque `national_id_encrypted` es obligatorio.
4. **Verificación de clave:** leer al menos una fila con `national_id_encrypted`, descifrarla y comparar el HMAC calculado con `national_id_hmac` (comparación en tiempo constante). Si no coincide, abortar sin escribir. No se usa una variante «cuando sea posible».
5. Validar fechas imposibles (nulas, futuras o posteriores a `created_at` UTC); si hay filas, reportar conteo e identificadores y abortar.
6. Bucle: seleccionar hasta 500 `id` con `birth_date_encrypted IS NULL`; actualizar solo esas filas con `pgp_sym_encrypt(birth_date::text, :key)`; `COMMIT` por lote. Repetir hasta 0. Si un lote no reduce el número de pendientes, fallar (evita un bucle infinito por una fila sin fecha de origen).
7. Verificación final única: cero pendientes y **todas** las filas procesadas descifran exactamente al valor en claro de origen.
8. Si el esquema ya es el final (018 aplicada), salir 0 sin hacer nada.
9. Capturar `SQLAlchemyError` y registrar solo la clase y el SQLSTATE; nunca la sentencia, los parámetros, la clave, la fecha, el nombre ni el documento.

Alternativa descartada: un único `UPDATE` de toda la tabla. Se descarta porque bloquea la tabla y no es reanudable.
Alternativa descartada: confiar en que el round-trip de la fecha detecta una clave incorrecta. Se descarta porque una clave equivocada puede producir un error de descifrado genérico o, en el peor caso, no detectarse hasta 018; el documento cifrado con HMAC es la prueba previa fiable.

### RF-005 — Migración 018

**Decisión 5: cierre transaccional y fallo cerrado.**

1. Si `birth_date` no existe, no hacer nada (idempotencia directa).
2. Contar filas con `birth_date_encrypted IS NULL`; si hay alguna, `RAISE EXCEPTION` con el conteo y no tocar la fecha en claro.
3. Comprobar que ninguna vista depende de `players.birth_date`; si queda alguna, fallar con un mensaje claro. La 017 ya recreó `v_public_tournament_players`.
4. `ALTER COLUMN birth_date_encrypted SET NOT NULL`.
5. `DROP COLUMN birth_date`.
6. Reafirmar los grants finales de forma idempotente: `INSERT` del cifrado y de la edad; `SELECT` de la edad; sin `SELECT` del cifrado; sin `UPDATE`/`DELETE`.

Alternativa descartada: dejar la columna en claro nullable indefinidamente. Se descarta porque incumple §3.4 y mantiene una copia legible.

### RF-006 — `MIGRATION_TARGET` y despliegue

**Decisión 6: target por variable de entorno, recorrido completo y checksums siempre.**

`infra/postgres/migrate.sh`:

```text
target = MIGRATION_TARGET (vacío o NNN)
si target no vacío y no existe un archivo NNN_*.sql: error y salir
crear schema_migrations
for cada migración ordenada:
    version, name, checksum
    verificar checksum contra schema_migrations (si existe)
        si no coincide: error y salir 3
    si target no vacío y version > target: continue
    aplicar si no está registrada y registrar checksum
```

- La verificación de checksums se ejecuta para **todos** los archivos, también los posteriores al target; el `continue` ocurre después de verificar y solo omite la aplicación.
- No existe `--target`; solo `MIGRATION_TARGET`.
- `MIGRATION_TARGET=017` sobre 016 aplica 017; `MIGRATION_TARGET=018` aplica 018; un target anterior al último aplicado es un no-op; un target inexistente o posterior al último falla.
- El job `db-migrate` recibe `MIGRATION_TARGET` desde el entorno; por defecto vacío.
- Alternativa descartada: `break` al llegar al target. Se descarta porque dejaría sin validar los checksums de los archivos posteriores y podría ocultar una migración alterada.

### RF-007 — Alta, importación y seed

**Decisión 7: edad en el jugador y reutilización sin actualizar la fecha.**

- `_create_roster_player_record` obtiene el año de inicio del torneo en la misma consulta que valida el equipo.
- `_find_or_create_player_record` recibe `reference_year` y calcula `age_at_reference = reference_year - payload.birth_date.year`.
- Si el documento ya existe en la organización, devuelve el `player_id` sin tocar `birth_date_encrypted`, `age_at_reference` ni `age_reference_year`. La fecha enviada se ignora.
- El `INSERT` incluye `birth_date_encrypted` y las columnas de edad; omite `birth_date`.
- Si hay carrera y `ON CONFLICT DO NOTHING`, se relee el jugador ganador y se reutiliza su edad; no se actualiza.
- La importación masiva usa el mismo helper dentro de la transacción del endpoint; un fallo de una fila revierte el archivo completo.
- El seed calcula la referencia con `start_date.year` y usa el mismo `INSERT`.
- `db_helpers.insert_player` se actualiza para insertar cifrado y edad; los tests pasan un `reference_year` explícito para ser deterministas.

Alternativa descartada: actualizar la edad si llega una fecha distinta. Se descarta porque la aplicación no puede descifrar ni comparar y la spec decide que prevalezca la primera.

### RF-008 — Proyección pública

**Decisión 8: misma vista, misma forma, edad entera.**

- 017 recrea `v_public_tournament_players` con la expresión de edad y `::INT`.
- Se conservan nombre, orden y tipo de columnas: `tournament_id`, `player_id`, `first_name`, `last_name`, `dorsal_number`, `team_id`, `public_age` (`integer`), `photo_url`.
- Se conserva `security_barrier = true`, el propietario exento de RLS y el `GRANT SELECT` a `bracket_app`.
- `v_public_match_lineups` y `v_public_match_lineups_unpublished` no seleccionan `birth_date`; se verifican tras 018.
- Alternativa descartada: una función `SECURITY DEFINER` que descifre en lectura. Se descarta por coste, por la clave en la sesión y porque la edad materializada evita el descifrado.

### RF-009 — Workspace

**Decisión 9: modelo de listado separado y cambio aditivo.**

- Se mantiene `RosterPlayerResponse` para alta, importación y foto.
- Se agrega `RosterPlayerListResponse(RosterPlayerResponse)` con `age: int` **solo** para `GET /tournaments/{id}/rosters`.
- La consulta del listado une `tournaments` por `(id, organization_id)` y calcula `age` con la misma expresión que la vista.
- El frontend agrega `age` a `RosterSummary`, muestra la etiqueta i18n `setup.age` (es/en) y conserva el refresco de `loadConfiguration()` tras importar y de `refreshOperation()` tras el alta.
- Alternativa descartada: agregar `age` al modelo compartido. Se descarta porque obligaría a las respuestas de alta/importación a incluirlo y rompería el contrato aprobado.

### RF-010 — Fechas

**Decisión 10: rango del tipo fecha y validación en todos los caminos.**

- Rango admitido: el del tipo `date`; sin límite inferior artificial.
- Se rechaza el futuro en `CreateRosterPlayerRequest` (ya existe) y en la importación (Pydantic).
- 017 y el backfill rechazan nulas, futuras y posteriores a `created_at` UTC, incluidos jugadores sin roster.
- Un alta nueva con fecha posterior a la creación coincide con el futuro y se rechaza por la misma regla.
- Alternativa descartada: aceptar fechas desconocidas y mostrar «edad desconocida». Se descarta por decisión del usuario y porque el campo es obligatorio.

### RF-011/RF-012 — Pruebas y saneo de errores

**Decisión 11: saneo en la frontera HTTP y en los logs.**

- `RequestValidationError`: responder 422 con la lista de errores sin `input` ni `ctx` (esos campos pueden contener la fecha o el documento). Se conservan `type`, `loc` y `msg`.
- `DBAPIError` no capturado: registrar solo el SQLSTATE y devolver 500 con un mensaje genérico. No se registran `exc`, `statement`, `params` ni la fila.
- Los `IntegrityError` que los routers ya traducen a 409 conservan su comportamiento.
- Alternativa descartada: confiar en el handler por defecto de FastAPI. Se descarta porque el cuerpo 422 incluye el valor rechazado y el traceback de base de datos puede incluir la fila.

## 4. Esquema, migraciones y grants

### 017 — `017_player_birth_date_encryption.sql`

| Paso | Efecto |
|---|---|
| Columnas | `birth_date_encrypted BYTEA NULL`, `age_at_reference SMALLINT NULL`, `age_reference_year SMALLINT NULL` |
| Validación | Fechas nulas/futuras/posteriores a `created_at` UTC → excepción con conteo e IDs |
| Backfill de edad | Referencia `registered_at`/`id` o `created_at` UTC; edad = año de referencia − año de nacimiento |
| Restricciones | `age_at_reference` y `age_reference_year` `NOT NULL`; `birth_date` pasa a `NULL` |
| Grants | Revoca `SELECT`/`INSERT` de `birth_date`; concede `SELECT` de edad e `INSERT` de cifrado/edad |
| Vista | `v_public_tournament_players` con `public_age` entero y misma forma |
| Idempotencia | `IF NOT EXISTS`, `CREATE OR REPLACE`, guardas; reejecutable antes de 018 |

### 018 — `018_player_birth_date_plaintext_removal.sql`

| Paso | Efecto |
|---|---|
| Guarda | Si `birth_date` no existe → no-op |
| Pendientes | `birth_date_encrypted IS NULL` → excepción con conteo |
| Dependencias | Si alguna vista depende de `birth_date` → excepción |
| Cierre | `birth_date_encrypted NOT NULL`; `DROP COLUMN birth_date` |
| Grants | Reafirma `INSERT` del cifrado/edad y `SELECT` de edad; sin `SELECT` del cifrado |
| Idempotencia | Guardas para reejecución directa |

### Grants finales de `players` para `bracket_app`

- `SELECT`: `id`, `organization_id`, `first_name`, `last_name`, `document_type`, `national_id_hmac`, `issuing_country`, `age_at_reference`, `age_reference_year`, `created_at`.
- `INSERT`: `organization_id`, `first_name`, `last_name`, `document_type`, `national_id_encrypted`, `national_id_hmac`, `issuing_country`, `birth_date_encrypted`, `age_at_reference`, `age_reference_year`.
- Sin `SELECT` de `birth_date_encrypted` ni `national_id_encrypted`; sin `UPDATE` ni `DELETE`.
- RLS `ENABLE`/`FORCE` y política tenant sin cambios.

## 5. Backfill: algoritmo y contrato operativo

```text
main():
  admin_url = env DATABASE_ADMIN_URL          # obligatorio
  key = get_settings().player_data_key        # reutiliza el guard de producción
  if not admin_url: error claro; exit 2
  return asyncio.run(run(admin_url, key))

run(admin_url, key, batch_size=500):
  engine = create_async_engine(admin_url)
  if birth_date no existe:
      if birth_date_encrypted existe: log "nada que hacer"; return 0
      error "017 no aplicada"; return 1
  if birth_date_encrypted no existe: error "017 no aplicada"; return 1
  if count(players) == 0: log "tabla vacía, nada que hacer"; return 0
  sample = select national_id_encrypted, national_id_hmac limit 1
  if not sample: error; return 1
  decrypted = pgp_sym_decrypt(sample.national_id_encrypted, key)
  if hmac(decrypted, key) != sample.national_id_hmac: error; return 1
  bad = count(players where birth_date is null or birth_date > current_date
              or birth_date > (created_at at time zone 'UTC')::date)
  if bad: report count + ids; return 1
  while true:
      ids = select id where birth_date_encrypted is null order by id limit batch_size
      if not ids: break
      update players set birth_date_encrypted = pgp_sym_encrypt(birth_date::text, key)
        where id = any(ids) and birth_date_encrypted is null
      commit
  pending = count(birth_date_encrypted is null)
  mismatch = count(birth_date is not null and
                   pgp_sym_decrypt(birth_date_encrypted, key)::date <> birth_date)
  if pending or mismatch: error; return 1
  log totals; return 0
```

- `run()` permite inyectar la URL y la clave en pruebas; `main()` lee el entorno.
- Los logs solo contienen conteos, números de lote, duración e identificadores internos cuando hay un error de datos; nunca nombre, documento, fecha, texto cifrado ni clave.
- Un fallo de lote deja los anteriores confirmados; la siguiente ejecución continúa desde los pendientes.
- Si se ejecuta después de 018, detecta el esquema final y no hace nada.

## 6. `MIGRATION_TARGET` en `migrate.sh`

- Variable de entorno, no bandera.
- Validación de formato `NNN` y existencia del archivo.
- Recorrido completo de `migrations/[0-9]*.sql`; nunca `break`.
- Verificación de checksum para cada archivo, incluso los posteriores al target.
- `continue` solo después de verificar y cuando `version > target`.
- El bloque de `PLATFORM_ADMIN_EMAIL` se mantiene al final.
- `MIGRATION_TARGET` se pasa al servicio `db-migrate` desde el entorno; por defecto vacío.
- Pruebas: script `infra/scripts/test_migrate_target.sh` con base desechable y `psql`, ejecutado en CI con el servicio PostgreSQL existente.

## 7. Backend

### Alta e importación

- `_create_roster_player_record` obtiene `start_date` del torneo junto con la validación del equipo.
- `_find_or_create_player_record(..., reference_year)`:
  - si existe por HMAC, devuelve el `id` sin actualizar;
  - si no, inserta `birth_date_encrypted`, `age_at_reference`, `age_reference_year`;
  - `ON CONFLICT DO NOTHING` y relectura del ganador.
- `_load_roster_player` y `RosterPlayerResponse` no cambian.
- `CreateRosterPlayerRequest` mantiene la validación de fecha futura.
- `roster_import.py` no cambia el formato ni las columnas obligatorias; la fecha sigue siendo obligatoria.
- `seed_demo.py` calcula la referencia con `start_date.year` y usa el nuevo `INSERT`.

### Listado del Workspace

- `RosterPlayerListResponse(RosterPlayerResponse)` con `age: int`.
- `list_tournament_rosters` agrega el join a `tournaments` y la expresión de edad, y usa el nuevo `response_model`.
- Las respuestas de alta, importación y foto siguen usando `RosterPlayerResponse`.
- `age` es la misma expresión que la vista pública.

### Saneo de errores

- Handler `RequestValidationError` en `backend/app/main.py`: elimina `input` y `ctx`, conserva `type`, `loc` y `msg`.
- Handler `DBAPIError`: log de `SQLSTATE` y respuesta 500 genérica; sin `statement`, `params` ni `str(exc)`.
- No se tocan los `IntegrityError` que ya traducen los routers.

## 8. Frontend

- `RosterSummary` agrega `age: number`.
- La tarjeta de roster muestra `t('setup.age', { age: roster.age })`.
- Se agrega `setup.age` en español e inglés.
- Se conserva el refresco existente: `importRoster` llama a `loadConfiguration()`; el alta en la página de partido llama a `refreshOperation()`. Si falta alguno, se agrega.
- No se muestra ni se solicita la fecha después del alta.
- Pruebas: test estático de la clave i18n en ambos idiomas y de la presencia de `roster.age`/refresco; `pnpm test`, `typecheck` y `build`. El proyecto no tiene harness de componentes; esa limitación se declara en la verificación.

## 9. Estrategia de pruebas

| Área | Pruebas |
|---|---|
| `migrate.sh` | Script de shell con base desechable: target 017/018, reejecución, target inválido, target posterior, no-op, checksum alterado, checksums de archivos posteriores |
| 017 | Base 016 + datos: columnas, edad por `registered_at`/`id`, `created_at` UTC sin roster, grants/revokes, vista con tipos, fechas imposibles, idempotencia intermedia |
| Backfill | Clave correcta/incorrecta por HMAC, tabla vacía, lotes de 500, reanudación, idempotencia, pendiente sin fuente, fecha imposible, no-op tras 018, logs sin PII |
| 018 | Fallo cerrado con pendientes, dependencia de vista, éxito tras backfill, columna eliminada, grants finales, volumen limpio, reejecución |
| Backend alta/importación/seed | Cifrado, edad, reutilización con otra fecha, permisos, atomicidad, seed idempotente |
| Workspace | `age` correcto en GET, ausencia en alta/importación, aislamiento, cambio de año de inicio |
| Errores | Cuerpo 422 sin fecha/documento; logs de DB sin «Failing row contains» |
| Frontend | Clave i18n es/en, `roster.age`, refresco, typecheck/build |
| Regresión | Suite unitaria, `compileall`, `pytest` con BD, `sh -n`, compose dev/prod |

## 10. Orden de implementación y dependencias

1. **T001** `MIGRATION_TARGET` (habilita el despliegue reproducible).
2. **T002** migración 017 (esquema intermedio y edad histórica). Depende de T001 para el runbook, no para el SQL.
3. **T003** comando de backfill. Depende de T002.
4. **T004** migración 018. Depende de T003 y de las pruebas de fallo cerrado.
5. **T005** alta e importación con fecha cifrada y edad. Depende de T002.
6. **T006** seed, helpers y regresión de esquema. Depende de T005.
7. **T007** `age` en el GET del Workspace. Depende de T006.
8. **T008** saneo de errores. Independiente; puede ir en paralelo con T005-T007.
9. **T009** frontend. Depende de T007 (contrato `age`); puede prepararse antes.
10. **T010** documentación, runbook, configuración y validación final con `MEMORY.md`. Última.

El comando debe existir en la imagen nueva **antes** de ejecutar 018; la imagen nueva es la que se despliega tras 017 y antes del backfill.

## 11. Runbook de despliegue y reversión

### 11.1 Secuencia reproducible (base con datos)

1. **Preparación:** copia de seguridad verificada de PostgreSQL; confirmar `PLAYER_DATA_KEY` y `DATABASE_ADMIN_URL`; construir la imagen nueva del backend.
2. **Mantenimiento:** detener `api` y `worker` (`docker compose stop api worker`) para que ninguna instancia antigua escriba la fecha. Confirmar que no hay escrituras.
3. **017:** `MIGRATION_TARGET=017 docker compose run --rm db-migrate`.
4. **Imagen nueva:** desplegar la imagen del backend con el comando de backfill; no arrancar aún `api`/`worker`.
5. **Backfill:** `docker compose run --rm --no-deps -e DATABASE_ADMIN_URL -e PLAYER_DATA_KEY api python -m scripts.encrypt_birth_dates`. Debe salir 0; revisar conteos.
6. **018:** `MIGRATION_TARGET=018 docker compose run --rm db-migrate`.
7. **Arranque:** `docker compose up -d api worker`; smoke de alta, `GET /rosters` con `age`, proyección pública y seed en desarrollo.
8. **Cierre:** registrar evidencia de la secuencia y actualizar `MEMORY.md`.

### 11.2 Instalación nueva

- `docker compose up --build` aplica todas las migraciones; 018 no encuentra pendientes porque la tabla está vacía. No se ejecuta el backfill.
- El seed de desarrollo se ejecuta después y usa el esquema final.

### 11.3 Reversión

- **Antes de 017:** restaurar la copia de seguridad y desplegar la imagen anterior.
- **Entre 017 y 018:** la app antigua no puede insertar la fecha porque 017 revocó el permiso. No se vuelve a la imagen antigua sobre el esquema intermedio; se corrige y se reintenta el backfill. Si hace falta una reversión total, se restaura la copia previa a 017 y se despliega la imagen anterior.
- **Después de 018:** no hay vuelta atrás de código; solo *forward-fix* con una migración nueva. No se edita 018 ni ninguna migración aplicada.
- **Fallo del backfill:** corregir la clave o los datos y reejecutar; los lotes anteriores quedan cifrados y la reanudación solo procesa pendientes.
- **Fallo de 018:** 018 es transaccional; corregir los pendientes y reejecutar. Nunca se elimina la fecha en claro a mano.

## 12. Verificación contra la constitución

| Principio, regla o criterio | Cómo lo cumple el plan | Check |
|---|---|---|
| §2.1 Aislamiento por tenant garantizado por la BD | `players` conserva RLS `FORCE` y la política tenant; no se añade ninguna vía cross-tenant | Pruebas A/B y consulta sin contexto en `test_birth_date_encryption_migration.py` / `test_player_catalog_schema.py` |
| §2.2 La aplicación no puede saltarse RLS | No se eleva el rol ni se usa `BYPASSRLS`; 017/018 corren con el rol administrador y la app con `bracket_app` | `test_db_harness.py`, pruebas de grants y de estado intermedio |
| §2.3 Lo publicado es inmutable | No se tocan versiones, resultados ni triggers de la spec 001 | Suite de regresión de `test_match_result_immutability.py` |
| §2.4 Historial de esquema append-only | Solo se agregan 017 y 018; no se editan 001-016 | `sh -n infra/postgres/migrate.sh`; checksums; revisión de `git diff` |
| §2.5 Lo público es una proyección mínima | La vista conserva su forma y solo expone `public_age`; nunca fecha completa ni cifrado | Prueba de columnas/tipos y de contenido de `v_public_tournament_players` |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Se reutiliza `PLAYER_DATA_KEY`; no se añaden secretos; `DATABASE_ADMIN_URL` se inyecta por entorno | `test_config.py`, `docker compose config -q`, revisión de `.env.example` |
| §2.7 Administración global separada y auditada | No se modifica `/admin` ni sus permisos | Suite de plataforma sin cambios |
| §2.8 Nada se da por terminado sin verificación | Pruebas de BD en CI, migraciones en ambos volúmenes, runbook probado y verificación honesta | Jobs `backend`, `frontend`, `infrastructure`; T010 |
| §2.9 El código de desarrollo no llega a producción | El seed sigue siendo solo de desarrollo; el backfill es un comando operativo, no un seed | `test_seed_demo.py` y revisión del runbook |
| §3.1 RLS y migraciones | Tabla ya tenant-owned; migraciones nuevas con checksum; RLS intacto | Pruebas de esquema y de idempotencia |
| §3.2 Backend asíncrono | Alta, importación y backfill usan SQLAlchemy async; el backfill confirma por lote | `pytest -q`, `compileall`, pruebas del comando |
| §3.3 Frontend y `useApi.ts` | El cambio de UI usa la página existente y el cliente HTTP actual; no se añaden llamadas directas | `pnpm test`, `typecheck`, `build` |
| §3.4 Seguridad y datos personales | La fecha completa se cifra con `PLAYER_DATA_KEY`, queda *write-only* y no aparece en logs, errores ni proyecciones; la edad derivada es el dato público ya existente | Pruebas de grants, de cifrado, 422, logs y vista pública |
| §3.5 Infraestructura y CI | Python 3.14/Node 24/pnpm 12.12.1 sin cambios; compose dev/prod válido; `MIGRATION_TARGET` documentado | `verify_version_sources.py`, `docker compose config -q`, merge de producción |
| §4 Todos los cambios: CI, sin secretos, docs, pruebas | Se ejecutan los jobs aplicables; no se introducen secretos; se actualizan README/AGENTS; cada cambio tiene prueba | T010 y revisión de la spec |
| §4 Cambios de BD: migración nueva, RLS, volumen limpio y migrado, `sh -n` | 017/018 nuevas; RLS sin cambios; pruebas en ambos volúmenes; `sh -n` | `test_birth_date_encryption_migration.py`; `sh -n` |
| §4 API/backend: `set_rls_context`, endpoints públicos sin campos sensibles, router registrado, `pytest`/`compileall` | Las rutas existentes conservan `set_rls_context`; el GET público no expone la fecha; no hay router nuevo; tests y compileall | `pytest -q`, `compileall`, pruebas de vista y de `age` |
| §4 Frontend: `useApi.ts`, `pnpm test`/`typecheck`/`build` | La página usa `request` de `useApi`; se ejecutan los tres checks | T009 |
| §4 Infraestructura: compose válido y sin defaults de producción | `MIGRATION_TARGET` es opcional; no se añaden defaults de producción | `docker compose config -q` y merge |
| §4 Dependencias: lockfiles y auditorías | No se agregan dependencias ni se toca el lockfile | Job `security` sin cambios |
| §5.1 Excepciones | No se requiere excepción: §3.4 se cumple y la edad derivada es la proyección pública ya existente | Justificación en la spec y este plan; no hay excepción registrada |
| §5.2 Evolución de la constitución | No se enmienda la constitución; el cambio es funcional y no altera principios ni reglas | `git diff docs/constitution.md` vacío |
| §6 Definición de cumplimiento | CI en verde, revisión humana distinta del autor y verificación honesta | T010 y aprobación del usuario |

**Nota constitucional:** la edad y el año de referencia se almacenan en claro, pero son el mismo dato derivado que la proyección pública ya exponía por diseño (principio 5). La fecha completa (día y mes) sigue cifrada y fuera del alcance de la aplicación. Por eso no se tramita una excepción §5.1 ni una enmienda §5.2.

## 13. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Clave incorrecta en el backfill | Cifrado irrecuperable si se elimina la fecha | Verificación previa contra `national_id_encrypted` y HMAC; aborta sin escribir; backup previo |
| Orden de despliegue incorrecto | 018 sin backfill o app antigua escribiendo | Runbook, `MIGRATION_TARGET`, `--no-deps`, mantenimiento antes de 017; 018 falla cerrado |
| Falta un grant de inserción | «Permission denied» en alta/importación/seed | Grants explícitos en 017/018 y prueba de alta de extremo a extremo |
| La vista cambia de tipo o de orden | Ruptura del contrato público | `::INT`, misma lista/orden y prueba de columnas y tipos |
| Fuga de la fecha en 422 o en logs de BD | Exposición de dato personal | Handlers de `RequestValidationError` y `DBAPIError`; pruebas de cuerpo y `caplog` |
| Edad obsoleta por cambio de año del torneo | Edad pública incorrecta | Delta por año en vista y GET; prueba antes/después de publicar |
| Alta posterior con otra fecha | Inconsistencia o intento de descifrado | Reutilización sin actualizar; prueba específica |
| Jugador sin roster con fecha imposible | Migración bloqueada | Validación y reporte con conteo/IDs; prueba explícita |
| Backfill largo o bloqueo | Impacto operativo | Lotes de 500, commit por lote, sin locks entre lotes, ventana de mantenimiento |
| Volumen limpio roto por vistas | Error tipo «cannot drop columns from view» | 017 recrea la vista antes de 018; prueba de volumen limpio |
| Tests/helpers siguen insertando la fecha en claro | Suite roja o falsa cobertura | Actualizar `db_helpers.py` y todas las pruebas que insertan/seleccionan `birth_date` |
| `MIGRATION_TARGET` mal configurado | Migraciones incompletas | Validación de formato/existencia, default vacío, runbook y pruebas |
| Backups con la fecha en claro | Exposición fuera de la base activa | Deuda separada documentada; revisión de retención y rotación |

### Verificaciones que pueden no ser ejecutables localmente

- Pruebas con PostgreSQL real (`RUN_DATABASE_TESTS=1`) si no hay servicio o Docker.
- `infra/scripts/test_migrate_target.sh` si no hay `psql` o Docker.
- Secuencia completa del runbook y smoke de producción si no hay un entorno desplegable.
- `pnpm test`, `typecheck` y `build` si el entorno no tiene Node 24/pnpm 12.12.1 o corepack está roto.
- `pip-audit`, `pnpm audit` y Trivy si no hay red o toolchain.

En todos los casos, la implementación debe declarar qué no ejecutó y no dar la tarea por cerrada sin evidencia.

## 14. Cobertura de RF por parte del plan

| Parte | RF |
|---|---|
| Migración 017 | RF-001, RF-002, RF-003, RF-008, RF-010 |
| Comando `encrypt_birth_dates` | RF-001, RF-004, RF-010, RF-011 |
| Migración 018 | RF-001, RF-002, RF-005, RF-011 |
| `migrate.sh` + `MIGRATION_TARGET` | RF-006, RF-011 |
| Alta, importación y seed | RF-001, RF-007, RF-010 |
| GET de rosters y modelo separado | RF-009, RF-011 |
| Vista pública | RF-008, RF-011 |
| Saneo de errores | RF-012, RF-011 |
| Frontend | RF-009, RF-011 |
| Documentación/runbook | RF-006, RF-012, RNF-012 |
