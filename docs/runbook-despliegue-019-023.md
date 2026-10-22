# Runbook de despliegue acumulado 019 → 023 (esquema 018 → 023)

Paquete operativo para llevar un servidor que está **en el esquema 018 con el código antiguo** hasta el **esquema 023** con el código actual de `main`, en una sola intervención (estrategia A) o por olas (estrategia B). No sustituye a los runbooks por migración de `README.md` y `AGENTS.md`: los agrupa, fija el orden y añade las comprobaciones de entrada y salida.

> Este documento no incluye secretos. Todos los valores sensibles (`POSTGRES_PASSWORD`, `JWT_SECRET`, `PLAYER_DATA_KEY`, `INVITATION_TOKEN_KEY`, credenciales de almacenamiento y URLs) se inyectan desde el gestor de secretos del operador. `.env.example` **no** es configuración de producción y `scripts.seed_demo` **no** se ejecuta nunca contra producción.

---

## 1. Alcance y riesgos

### 1.1 Qué cubre

| Elemento | Estado | Naturaleza | Rollback |
|---|---|---|---|
| Esquema de partida | **018** | — | — |
| **019** | retira `tournament_user_roles` y `stage_edges`, estrecha el `CHECK` de `phase_slots.source_type` y recrea `prevent_published_structure_mutation()` con SQLSTATE `ZZ409` | **destructiva** | **ninguno** (*forward-fix*) |
| **020** | concede `INSERT (id)` sobre `public.rosters` a `bracket_app` | aditiva | ninguno (*forward-fix*) |
| **021** | añade `player_out_id`/`player_in_id`, FKs compuestas y `chk_match_event_substitution_pair` (`NOT VALID`) a `match_events` | aditiva | ninguno (*forward-fix*) |
| **022** | añade los `CHECK` `chk_match_event_minute_range` y `chk_match_event_added_minute_range` (`match_events`) | aditiva, pre-chequeo que aborta | ninguno (*forward-fix*) |
| **023** | añade `stages.schedule_legs` (`SMALLINT NOT NULL DEFAULT 1`, `CHECK (1,2)`) | aditiva, sin *backfill* | ninguno (*forward-fix*) |

Fuera de alcance: las migraciones **001–018** (si el servidor está por debajo de 018, primero se completa el runbook **017 → 018** del `README.md`), el cambio de imagen base, la rotación de secretos y cualquier corrección de datos.

### 1.2 Dependencias código ↔ esquema

| Código | Requiere | Por qué |
|---|---|---|
| Código antiguo (previo a 006) | ≤ 018 | el clonado de versiones lee `stage_edges`; la 019 se lo quita |
| Código de la **006** | ≥ 018 (import de plantillas: **≥ 020**) | deja de leer `tournament_user_roles`/`stage_edges` y estrena el avance manual; funciona con el esquema 018 y con el 019, pero el `id` pre-generado del roster exige el grant de la 020 |
| Código de la **007** | **≥ 021** | escribe `player_out_id`/`player_in_id` al cerrar un acta con sustituciones |
| Código actual (008/009/010) | **≥ 023** | `_load_draft_stage_context` lee `stages.schedule_legs`; además escribe el par de sustitución (021) |

Reglas de orden que **no** se pueden invertir:

1. **021 antes** del código que escribe el par de sustitución.
2. **023 antes** del backend que lee `schedule_legs`.
3. **019 sin ningún lector antiguo vivo**: ningún proceso con el código previo a 006 puede estar leyendo `stage_edges` cuando se aplica. En la estrategia A se garantiza porque `api` y `worker` están detenidos; en la B, porque el código de la 006 ya está desplegado.

### 1.3 Riesgos

- **La 019 no tiene rollback.** Después de aplicada, la única corrección es una migración nueva. Restaurar la copia de seguridad solo es válido si se acepta perder todos los cambios posteriores.
- **La 019 borra tablas.** Aborta de forma cerrada si tienen filas o si `phase_slots.source_type` contiene valores retirados; nunca borra datos en silencio.
- **La 022 aborta** si existen eventos con `minute` fuera de `0..180` o `added_minute` fuera de `0..30`. No recorta datos; la corrección es manual, revisada y con copia previa.
- **La 021 prohíbe cerrar sustituciones con el código anterior.** Su `CHECK` se evalúa en cada `INSERT`/`UPDATE`: un acta cerrada por el código previo a la 007 con una sustitución sin par viola la restricción. En la estrategia A no ocurre porque no hay servicios vivos; en la B obliga a congelar esa operación.
- **La 023 no reconstruye las vueltas.** Una liga o fase de grupos histórica de dos vueltas queda en una hasta que se regenere su calendario; mientras tanto el límite de enfrentamientos manuales por pareja es uno (las versiones publicadas no admiten altas manuales).
- **La ventana de mantenimiento implica caída del servicio.** Con `api` detenida, el `web` en renderizado de servidor devuelve errores; por eso la estrategia A para también `web`.
- **Supuesto crítico de la estrategia A:** no hay **ningún otro** proceso (segunda réplica, otro stack o un `api` huérfano) conectado a la misma base de datos durante la ventana. Si lo hay, el supuesto se rompe y hay que pasar a la estrategia B.

---

## 2. Dos estrategias

### 2.1 Estrategia A (recomendada): ventana de mantenimiento

Parar `api`, `worker` y `web`, aplicar **019 → 020 → 021 → 022 → 023** con los servicios detenidos, construir y arrancar el código actual, y hacer el smoke.

Es la recomendada porque:

- elimina por completo la ventana de incompatibilidad de la 021 (no hay código antiguo cerrando actas);
- permite aplicar la 019 sin lectores antiguos de `stage_edges`, que es su única condición real (el requisito «código nuevo primero» de los runbooks por migración existe para que no quede un proceso viejo leyendo; con todo parado se cumple igual);
- deja un único punto de smoke y un único punto de verdad (`schema_migrations` en 023);
- evita mantener dos referencias intermedias (006 y 007) construibles y compatibles.

Coste: una interrupción planificada. Con los servicios parados, el backup y las cinco migraciones son minutos; el `pg_dump` y el smoke marcan la duración real.

### 2.2 Estrategia B (solo si no es posible parar)

Orden por olas, con dos puntos de código intermedios:

| Ola | Qué se despliega | Esquema resultante | Condición de paso |
|---|---|---|---|
| 1 | código de la **006** | 018 | funciona con el esquema 018; smoke OK; **sin importación de plantillas hasta la ola 3** (el grant de la 020 todavía no está) |
| 2 | migración **019** | 019 | pre-chequeos en 0 y catálogo limpio; **sin lectores antiguos** |
| 3 | migración **020** | 020 | privilegio de columna verificado |
| 4 | migración **021** | 021 | conteos informativos registrados |
| 5 | código de la **007** | 021 | smoke de sustitución; **desde la ola 4 hasta aquí no se cierran actas con sustituciones** |
| 6 | migración **022** | 022 | pre-chequeo en 0 |
| 7 | migración **023** | 023 | columna presente |
| 8 | **código actual** | 023 | smoke completo |

Es más frágil por tres motivos: hay tres versiones de código que deben estar construidas y disponibles, cada ola es un punto de fallo con estado mixto, y la ola 4 abre una **ventana funcional** en la que el código desplegado no puede cerrar sustituciones (la 021 ya está aplicada y el código aún no escribe el par). Si se elige, la ventana de la 021 es la que más disciplina exige: no se puede cerrar un acta con sustituciones entre las olas 4 y 5.

---

## 3. Requisitos previos

- [ ] **Docker Compose 2.24.4 o superior** (`docker compose version --short`). El overlay de producción usa `!reset`/`!override`.
- [ ] Red externa del proxy creada por el operador: `docker network create "${PROXY_NETWORK:-edge}"` si no existe.
- [ ] **Secretos de producción disponibles** en el entorno o gestor: `POSTGRES_PASSWORD`, `BRACKET_DB_PASSWORD`, `JWT_SECRET`, `PLAYER_DATA_KEY`, `INVITATION_TOKEN_KEY`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`, `STORAGE_PROVIDER`, `STORAGE_BUCKET`, `STORAGE_PUBLIC_BASE_URL`, `FRONTEND_BASE_URL`, `SMTP_HOST`, `SMTP_FROM`, `NUXT_PUBLIC_API_BASE`, `NUXT_PUBLIC_SOCKET_BASE`, `NUXT_API_INTERNAL_BASE` y el no secreto `PLATFORM_ADMIN_EMAIL`. El overlay falla al renderizar si falta cualquiera de los marcados con `:?`.
- [ ] **Checkout en el commit objetivo** de `main` (el que contiene `infra/postgres/migrations/019…023`). El servicio `db-migrate` monta `./infra/postgres` en solo lectura: **las migraciones que se aplican son las del árbol de trabajo del host**, no las de una imagen. Un checkout atrasado deja migraciones sin aplicar; uno adelantado puede aplicar de más.
- [ ] **Backup verificado** y copia **fuera del host**, cifrada y protegida (contiene datos personales).
- [ ] **Acceso al host**, al proxy y a los logs; **ventana acordada** y comunicada.
- [ ] `$COMPOSE config -q` (§4) pasa con los secretos inyectados (valida el merge real antes de tocar nada).
- [ ] Baselines anotados para comparar después: `max(version)` de `schema_migrations`, número de eventos `substitution`, estado de la outbox, salud de los servicios y versión desplegada.
- [ ] **No** se usa `.env.example` como configuración de producción y **no** se ejecuta `python -m scripts.seed_demo`.

---

## 4. Convenciones de los comandos

Todos los comandos se ejecutan desde la raíz del repositorio del host. El perfil de producción se aplica como overlay, en ese orden:

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
```

Ayuda para las consultas SQL (lee el SQL por *stdin* y se ejecuta **dentro** del contenedor `db`, donde `$POSTGRES_USER` y `$POSTGRES_DB` sí existen):

```sh
psql_db() { $COMPOSE exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'; }

schema_version() {
  psql_db <<'SQL'
SELECT max(version) AS esquema, count(*) AS aplicadas FROM public.schema_migrations;
SQL
}
```

- `MIGRATION_TARGET` se pasa **en línea** (`MIGRATION_TARGET=019 $COMPOSE run ...`), nunca con `export`, para que no quede activa en comandos posteriores. Vacía aplica todas las pendientes; no existe `--target`.
- Las versiones de `schema_migrations` son cadenas de tres dígitos (`'018'`, `'019'`, …): `max(version)` es comparable y ordenable como texto.

---

## 5. Estado inicial (no continuar si no es 018)

```sh
docker compose version --short
$COMPOSE config -q
$COMPOSE ps
$COMPOSE exec -T api python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'))['info']['version'])"
$COMPOSE exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
```

```sh
psql_db <<'SQL'
SELECT max(version) AS esquema_actual,
       count(*)      AS migraciones_aplicadas
FROM public.schema_migrations;

SELECT count(*) AS posteriores_a_018
FROM public.schema_migrations
WHERE version > '018';
SQL
```

Criterio de entrada:

- `esquema_actual = '018'` y `posteriores_a_018 = 0`. Si el máximo es **menor** que 018, aplicar antes el runbook **017 → 018**. Si es **mayor** que 018, este runbook no aplica: continuar desde la primera migración pendiente con el runbook de esa migración.
- `$COMPOSE ps` muestra `db`, `api`, `worker`, `web`, `redis` y `storage` sanos. Anotar el estado de la outbox y el número de eventos `substitution` como baseline.

---

## 6. Backup verificado (obligatorio)

```sh
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre019-023.dump"
$COMPOSE exec -T db pg_restore -l < "$HOME/backup-pre019-023.dump" > /dev/null && echo "backup verificable"
sha256sum "$HOME/backup-pre019-023.dump"
```

- `pg_restore -l` debe listar el archivo sin error; sin esa comprobación no hay copia válida.
- Copiar el archivo **fuera del host** y cifrarlo: contiene datos personales. No se versiona ni se deja en el repositorio.
- Anotar el `sha256` y el tamaño. Toda restauración de la §13 usa esta copia.

---

## 7. Pre-chequeos (antes de parar nada)

Los controles de la 019 y el de la 022 se repiten **dentro de la transacción** de la migración: los de aquí son la misma comprobación hecha con antelación para decidir si se abre la ventana, no una alternativa a los del runner.

### 7.1 Migración 019 — conteos

Todos deben ser **0**. Si alguno es mayor, la 019 aborta: el operador decide antes de aplicarla; no se borran filas ni se reescribe `source_type`.

```sh
psql_db <<'SQL'
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
SQL
```

### 7.2 Migración 019 — catálogo de objetos

Antes solo debe aparecer la propia tabla, su política o trigger; **después, nada**. Una **FK entrante** bloquea el `DROP` (no hay `CASCADE`): se resuelve con una migración nueva antes de reintentar.

```sh
psql_db <<'SQL'
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
SQL
```

### 7.3 Migración 021 — conteos informativos (evidencia)

No abortan; se registran para comparar con el post-chequeo.

```sh
psql_db <<'SQL'
SELECT count(*) AS eventos_substitution
FROM public.match_events
WHERE event_type = 'substitution';

SELECT count(*) AS filas_match_segment_team_state
FROM public.match_segment_team_state;
SQL
```

### 7.4 Migración 022 — filas fuera de rango

Ambos conteos deben ser **0**. Si no lo son, la 022 aborta y **no recorta ni corrige** nada: hay que corregir las filas con una revisión explícita (con esta copia de seguridad hecha), **sin editar la 022**, y volver a ejecutarla.

```sh
psql_db <<'SQL'
SELECT count(*) AS minute_fuera_de_rango
FROM public.match_events
WHERE minute < 0 OR minute > 180;

SELECT count(*) AS added_minute_fuera_de_rango
FROM public.match_events
WHERE added_minute < 0 OR added_minute > 30;
SQL
```

### 7.5 Migración 023 — nada especial

Solo confirmar que la columna no existe todavía (si existiera, el esquema ya estaría por encima de 023 y hay que revisar el estado inicial).

```sh
psql_db <<'SQL'
SELECT count(*) AS columna_schedule_legs_presente
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'stages'
  AND column_name = 'schedule_legs';
SQL
```

---

## 8. Parada de servicios (ventana)

```sh
$COMPOSE stop api worker web
$COMPOSE ps
```

- `api` y `worker` deben estar **detenidos** antes de la 019 (ningún lector antiguo de `stage_edges`) y durante toda la secuencia.
- `web` se detiene porque, sin `api`, su renderizado de servidor falla y porque el frontend es parte del mismo release: no debe servirse una versión antigua contra el esquema nuevo.
- Verificar que no queda ningún otro proceso conectado a la base (segunda réplica, otro stack, `api` huérfano). Si existe, este runbook no es aplicable tal cual: pasar a la estrategia B o detener ese proceso también.

---

## 9. Aplicación secuencial 019 → 023

Una migración por comando. Tras cada una, `schema_version` debe confirmar el escalón; si no lo confirma, **no se continúa**. El runner valida el checksum SHA-256 de **todos** los archivos: un checksum distinto aborta y significa que el checkout del host no corresponde al historial del servidor.

```sh
MIGRATION_TARGET=019 $COMPOSE run --rm db-migrate
schema_version   # esperado: esquema = 019

MIGRATION_TARGET=020 $COMPOSE run --rm db-migrate
schema_version   # esperado: esquema = 020

MIGRATION_TARGET=021 $COMPOSE run --rm db-migrate
schema_version   # esperado: esquema = 021

MIGRATION_TARGET=022 $COMPOSE run --rm db-migrate
schema_version   # esperado: esquema = 022

MIGRATION_TARGET=023 $COMPOSE run --rm db-migrate
schema_version   # esperado: esquema = 023 y aplicadas = 23 con este checkout
```

Si una falla:

- **019:** falla cerrada (conteos o catálogo). Corregir los datos o la FK entrante y reintentar; la transacción no deja estado a medias.
- **020:** el grant es aditivo; si falla, revisar que la 019 esté aplicada y el rol `bracket_app` exista.
- **021:** falla si las columnas o la FK compuesta no pueden crearse (por ejemplo, falta el índice único `players (id, organization_id)` de la 015). No continuar.
- **022:** aborta con ambos conteos si hay filas fuera de rango. No editar la migración; corregir los datos y reintentar.
- **023:** falla si la columna ya existe. Revisar el estado inicial antes de tocarla.

---

## 10. Despliegue del código actual

```sh
$COMPOSE build api worker web
$COMPOSE up -d api worker web
```

- Si el pipeline publica imágenes, desplegar esas etiquetas en lugar de construir en el host; el orden (migraciones primero, código después) no cambia.
- `api` y `worker` dependen de `db-migrate: service_completed_successfully`: el `up` vuelve a ejecutar el one-off. Con la 023 ya aplicada no hay nada pendiente y es una red de seguridad (vuelve a validar checksums). **No** dejes `MIGRATION_TARGET` exportada de un paso anterior: comprueba `echo "${MIGRATION_TARGET:-<vacío>}"` y que muestre `<vacío>`.
- No uses `up --build` para esta secuencia: ocultaría el orden porque el `db-migrate` dependiente se ejecutaría en el mismo `up` y aplicaría de golpe lo que quedara pendiente.
- El código actual **no funciona contra el esquema 022** (las rutas que leen el borrador pasan por `_load_draft_stage_context`, que lee `schedule_legs`) **ni cierra sustituciones contra el 020** (escribe `player_out_id`/`player_in_id`). Si el `up` se hace antes de tiempo, el síntoma es un error de columna inexistente: no es un fallo del código.

---

## 11. Smoke

### 11.1 Salud, documentación y versión

```sh
$COMPOSE ps
$COMPOSE exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
$COMPOSE exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/docs').status)"
$COMPOSE exec -T api python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'))['info']['version'])"
```

- `/health/ready` confirma base de datos **y** Redis; `api` debe quedar `healthy`.
- La versión del producto sale de `backend/pyproject.toml` y `/docs` la lee; no es `engine_version` 2026.1.

### 11.2 Lecturas públicas

```sh
$COMPOSE exec -T api python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/tournaments/public')); print(len(d), d[0]['id'] if d else None)"
```

Con el identificador obtenido:

```sh
TOURNAMENT_ID="<uuid>"
$COMPOSE exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/tournaments/public/$TOURNAMENT_ID/standings').status)"
$COMPOSE exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/tournaments/public/$TOURNAMENT_ID/matches').status)"
```

Ambas responden **200**. Las respuestas públicas no incluyen documentos de identidad ni fechas de nacimiento, y `photo_url` solo aparece con consentimiento de imagen. Si el listado público está vacío, es un resultado válido: el smoke de clasificación y partidos se declara **no ejecutado** por falta de datos, no se inventa un torneo.

### 11.3 Workspace (navegador, a través del proxy)

No hay puertos publicados en producción: el smoke funcional se hace en el navegador contra el dominio real.

1. Iniciar sesión en `/workspace` y validar la organización activa.
2. Abrir un torneo en borrador y comprobar la asignación manual de equipos entre fases (`GET`/`POST`/`DELETE /tournaments/{id}/stages/{stage_id}/teams`).
3. Abrir la operación de un partido (`/workspace/matches/{id}`): la pantalla consume `GET /api/v1/matches/{id}/operation` y no escribe en un `GET`.
4. Si hay datos, cerrar un acta con una **sustitución válida** (021) y comprobar que la fila de `match_segment_team_state` del segmento refleja el saldo.
5. Si existe una invitación **revocada**, reabrirla en `/workspace/members` (009): `POST /api/v1/organizations/invitations/{id}/reopen` responde **200**, la misma fila vuelve a `pending` con token y fecha nuevos y el enlace anterior deja de resolver. No copiar ni registrar el token. Se escribe **una** entrada `REOPEN_INVITATION` en `administrative_audit_logs` (sin correo ni token). Si no hay ninguna revocada, el punto se declara **no ejecutado**, no se crea una para probar.

Las escrituras validan `Origin` y `Referer` por separado: usa siempre el origen real del sitio, no un host interno.

### 11.4 Worker y outbox

```sh
$COMPOSE exec -T worker python -c "from app.workers.heartbeat import HEARTBEAT_MAX_AGE_SECONDS, heartbeat_is_fresh_at_path; print(heartbeat_is_fresh_at_path(max_age=HEARTBEAT_MAX_AGE_SECONDS))"
```

Debe imprimir `True`: el latido se publica cada **10 s** y caduca a los **90 s**, haya o no eventos. Opcional (operación, no suite; sale **2** si no hay Docker o contenedor y queda como **no ejecutada**):

```sh
sh infra/scripts/verify_worker_loop_health.sh worker
```

Procesamiento de la outbox:

```sh
psql_db <<'SQL'
SELECT status, count(*) AS total, max(processed_at) AS ultimo_procesado
FROM public.outbox_events
GROUP BY status
ORDER BY status;
SQL
```

- `processed` debe avanzar respecto al baseline y `max(processed_at)` ser reciente.
- `failed` debería ser **0**; si ya había fallidos antes del despliegue, comparar ambos conteos antes de atribuirlos a la ventana.
- Un `pending` residual se drena solo; el worker reintenta. La API HTTP es la fuente de verdad: el tiempo real es una optimización.

---

## 12. Post-chequeos

Todos los comandos de esta sección deben pasar antes de firmar el despliegue.

```sh
psql_db <<'SQL'
-- 1. Esquema en 023 y sin pendientes
SELECT max(version) AS esquema, count(*) AS aplicadas
FROM public.schema_migrations;

-- 2. 019: estructuras retiradas ausentes
SELECT to_regclass('public.tournament_user_roles') AS tournament_user_roles,
       to_regclass('public.stage_edges') AS stage_edges;

SELECT conname, pg_get_constraintdef(oid) AS definicion
FROM pg_constraint
WHERE conrelid = 'public.phase_slots'::regclass
  AND contype = 'c';

SELECT pg_get_functiondef('public.prevent_published_structure_mutation()'::regprocedure)
       LIKE '%ZZ409%' AS con_zz409;

-- 3. 020: privilegio de columna, no de tabla
SELECT has_column_privilege('bracket_app', 'public.rosters', 'id', 'INSERT') AS insert_id_columna,
       has_table_privilege('bracket_app', 'public.rosters', 'INSERT')        AS insert_tabla;

-- 4. 021: columnas, FKs y CHECK not valid
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'match_events'
  AND column_name IN ('player_out_id', 'player_in_id')
ORDER BY column_name;

SELECT conname, contype, convalidated
FROM pg_constraint
WHERE conname = 'chk_match_event_substitution_pair'
   OR (conrelid = 'public.match_events'::regclass AND contype = 'f')
ORDER BY conname;

-- 5. 022: restricciones validadas
SELECT conname, convalidated
FROM pg_constraint
WHERE conname IN ('chk_match_event_minute_range', 'chk_match_event_added_minute_range')
ORDER BY conname;

-- 6. 023: columna y CHECK
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'stages'
  AND column_name = 'schedule_legs';

SELECT conname, pg_get_constraintdef(oid) AS definicion
FROM pg_constraint
WHERE conname = 'chk_stages_schedule_legs';
SQL
```

Criterios:

| Comprobación | Esperado |
|---|---|
| `max(version)` | `023`; `aplicadas` = número de archivos del checkout (23) |
| `tournament_user_roles`, `stage_edges` | `NULL` (ausentes) |
| `CHECK` de `phase_slots.source_type` | existe una con `direct_team` y `match_result`, y ninguna que admita `stage_rank` o `manual` |
| función de estructura | contiene `ZZ409` |
| `insert_id_columna` / `insert_tabla` | `true` / `false` |
| `player_out_id`, `player_in_id` | `uuid`, `YES` (nulables) |
| `chk_match_event_substitution_pair` | `convalidated = false` (**por diseño**: `NOT VALID`, sin `VALIDATE`) |
| FKs de `match_events` | `convalidated = true` |
| `chk_match_event_*_minute_range` | `convalidated = true` (validadas, no `NOT VALID`) |
| `stages.schedule_legs` | `smallint`, `NO`, default `1` |
| `chk_stages_schedule_legs` | `CHECK ((schedule_legs = ANY (ARRAY[1, 2])))` |

Si `max(version)` es mayor que `023`, el checkout del host estaba por delante del commit objetivo y el `up` aplicó migraciones no previstas: detenerse y revisar antes de continuar.

---

## 13. Rollback y forward-fix

### 13.1 Antes de aplicar la 019

Restaurar la copia y volver a la imagen anterior. La restauración **pierde todos los cambios posteriores** al backup.

`pg_restore --clean --if-exists` **no basta**: solo elimina los objetos que existen en el archivo, y los creados después (columnas y `CHECK` de la 021/022, `stages.schedule_legs`, el `CHECK` estrechado y la función con `ZZ409` de la 019, el grant de la 020) sobrevivirían y el esquema quedaría mezclado. La restauración correcta es sobre una base **vacía**:

```sh
$COMPOSE stop api worker web

# Base limpia: el dump contiene extensiones, roles de aplicación, RLS, políticas y grants propios de la base.
$COMPOSE exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)" \
  -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\""'

$COMPOSE exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < "$HOME/backup-pre019-023.dump"
```

- El rol `bracket_app` es del clúster (`init/00_roles.sh`), no de la base: sobrevive al `DROP DATABASE` y el dump no lo necesita recrear.
- `WITH (FORCE)` requiere PostgreSQL 13 o superior (la imagen es 17) y cierra las conexiones restantes; aun así, no debe haber ningún otro proceso usando la base.
- Una restauración parcial o con errores se descarta y se repite sobre otra base limpia: no se "arregla" a mano.

Verifica la restauración antes de arrancar nada (esquema y privilegios del rol de aplicación):

```sh
psql_db <<'SQL'
SELECT max(version) AS esquema FROM public.schema_migrations;

SET ROLE bracket_app;
SELECT count(*) AS torneos_visibles FROM public.tournaments;
RESET ROLE;
SQL
```

`esquema` debe ser `018` y la consulta con `SET ROLE` debe ejecutarse sin error de permisos (con RLS y sin contexto de organización devuelve 0 filas). Ensaya esta restauración sobre una copia antes de la ventana: es la única prueba real de que el backup sirve.

Después, con el checkout de la **release anterior** (sin `019…023`) y sus imágenes construidas o publicadas:

```sh
MIGRATION_TARGET=018 $COMPOSE up -d api worker web
```

El `MIGRATION_TARGET=018` en línea evita que el `db-migrate` dependiente reaplique 019–023 desde un checkout nuevo. No dejes esa variable exportada: congelaría las migraciones futuras. Comprueba el resultado con `SELECT max(version) FROM public.schema_migrations;` → `018` y con `$COMPOSE ps` que `api`, `worker` y `web` vuelven a estar sanos.

### 13.2 Después de la 019

No hay `down`. Cualquier corrección es una **migración nueva** (*forward-fix*); no se edita la 019 ni se reescribe a mano su efecto. Restaurar la copia solo si se acepta perder los cambios posteriores y se vuelve a la imagen anterior.

### 13.3 Después de la 021, 022 o 023

No se desaplican: son aditivas y se quedan. Se puede revertir **código** dentro de los límites que impone el esquema:

- volver a un código previo a la 006 **no** es posible: lee `stage_edges`, que ya no existe;
- volver a un código previo a la 007 deja el cierre de actas con sustituciones roto (el `CHECK` de la 021 rechaza el par ausente);
- el código que no lee `schedule_legs` sigue funcionando con la 023 presente (la columna tiene default).

Cualquier defecto de esquema o de datos se corrige con una migración nueva, nunca editando una aplicada.

### 13.4 Fallo durante la secuencia

- **019:** transaccional y cerrada; corrige el dato o la FK y reintenta. Si ya se aplicó, solo *forward-fix*.
- **020:** aditiva; reintentar tras corregir la causa. No requiere volver atrás.
- **021:** aditiva; reintentar tras verificar el índice único de `players`. Si hay eventos `substitution` legados sin par, se conservan y el `CHECK` no se valida: es el comportamiento previsto.
- **022:** el pre-chequeo aborta sin cambios. Corregir las filas señaladas (con esta copia hecha y revisión explícita) y reejecutar. No se edita la migración.
- **023:** si la columna ya existía, el esquema estaba por delante; revisar el estado inicial.

---

## 14. Notas

- **La 021 no elimina `match_segment_team_state`.** Sigue siendo la proyección de contadores; se asegura al abrir el segmento y se recalcula al cerrar ordenando por `segment_number`. El `GET` de operación calcula sin escribir.
- **La 020 concede solo `INSERT (id)`** (privilegio de columna) sobre `public.rosters` a `bracket_app`; no concede `INSERT` de tabla y no cambia datos, funciones ni políticas.
- **La 023 no hace *backfill*.** Una liga o fase de grupos histórica de dos vueltas queda en una hasta que se regenere su calendario; las versiones publicadas no admiten altas manuales, así que la limitación solo alcanza a borradores que aún no se han vuelto a sortear.
- **La 022 son topes estructurales, no la regla deportiva.** La API sigue aplicando el máximo efectivo de la fase (reglamentario/prórroga) y responde con su error actual antes de llegar a la base. La validación recorre la tabla una vez y toma un bloqueo breve: en la estrategia A no tiene impacto porque el servicio está detenido.
- **La 019 conserva `phase_slots`** y las columnas de slots de `matches` como procedencia; solo retira `tournament_user_roles` y `stage_edges` y estrecha el `CHECK`.
- **El job `e2e` no forma parte del despliegue.** Corre en cada `pull_request` y solo en `push` a `main`, con presupuesto propio (corrida ≤15 min, vista ≤4 min, arranque aparte) y códigos 0/1/2/3; marcar `e2e` como *required check* es configuración de protección de rama en GitHub, no un paso del despliegue. Tampoco se ejecuta `pnpm run e2e` en el host de producción: levanta una pila de desarrollo con seed demo.
- **El stream del outbox es transporte de mejor esfuerzo.** Un hueco o un duplicado no es un fallo del despliegue; la API HTTP es la fuente de verdad.
- **Nada de datos personales en el runbook.** Las consultas devuelven conteos, nombres de estructura y estados; si una revisión de datos requiere identificadores, se hace fuera de este documento y no se registra la fecha de nacimiento ni el documento.
- **Reparto de tiempos:** el `pg_dump` y el smoke dominan la ventana. No se promete una duración: mídela en el ensayo con una copia real.

---

## 15. Checklist final (firmar el despliegue)

**Antes**

- [ ] Checkout en el commit objetivo de `main`; `db-migrate` monta esas migraciones.
- [ ] Docker Compose ≥ 2.24.4 y `$COMPOSE config -q` en verde con los secretos inyectados.
- [ ] Backup `pg_dump -Fc` verificado con `pg_restore -l`, copiado fuera del host y cifrado; `sha256` anotado.
- [ ] `schema_migrations` en **018**, sin versiones posteriores.
- [ ] Pre-chequeo de la 019 en **0** (tablas y `source_type`) y catálogo sin FKs entrantes ni dependencias.
- [ ] Conteos informativos de la 021 anotados (eventos `substitution`, filas de `match_segment_team_state`).
- [ ] Pre-chequeo de la 022 en **0** para `minute` y `added_minute`.
- [ ] Columna `stages.schedule_legs` ausente.
- [ ] Ventana acordada, servicios detenidos (`api`, `worker`, `web`) y ningún otro proceso conectado a la base.

**Durante**

- [ ] 019 aplicada y `max(version) = '019'`.
- [ ] 020 aplicada y `max(version) = '020'`.
- [ ] 021 aplicada y `max(version) = '021'`.
- [ ] 022 aplicada y `max(version) = '022'`.
- [ ] 023 aplicada y `max(version) = '023'`.
- [ ] Código actual construido/publicado y arrancado; `MIGRATION_TARGET` vacía en el entorno.

**Después**

- [ ] `api` y `worker` `healthy`; `/health/ready` confirma base de datos y Redis; `/docs` responde y muestra la versión del producto.
- [ ] Listado público, clasificación y partidos responden **200**.
- [ ] Login del Workspace, avance manual en borrador y operación de un partido comprobados.
- [ ] Cierre de un acta con una sustitución válida (021) y saldo correcto en `match_segment_team_state`.
- [ ] Reapertura de una invitación revocada (009) verificada, o declarada **no ejecutada** con motivo.
- [ ] Worker: latido fresco (`True`) y outbox `processed` avanzando, sin `failed` nuevos.
- [ ] Post-chequeos de la §12 en el estado esperado, incluido `max(version) = '023'` tras el `up`.
- [ ] Sin errores nuevos en los logs de `api`, `worker` y `web` (saneados: sin tokens ni datos personales).
- [ ] `MIGRATION_TARGET` no queda exportada; el checkout queda en el commit desplegado.
