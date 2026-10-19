# Plan 001 — Correctivos P0 de la auditoría técnica 2026-10-19

Estado: aprobado e implementado (validado en segunda ronda, 2026-10-19)

Spec: `specs/001-correctivos-p0-auditoria/spec.md` (aprobada 2026-10-19)

Excepción aprobada (§5.1 de la spec): el job `security` queda exceptuado por deuda preexistente de `simple-git` en el frontend; el resto de los jobs y verificaciones se exige sin rebaja.

## 1. Resumen técnico

El plan corrige cuatro hallazgos ALTOS sin introducir funcionalidad nueva:

- **R01:** convierte `players` en tabla tenant-owned con `organization_id`, RLS `FORCE`, unicidad por organización y claves foráneas compuestas. La migración **015** divide los registros compartidos, repunta todas las referencias, elimina residuos sin referencia, recrea las dos definiciones que unen `players` y mantiene el wrapper de formación.
- **R02:** corrige el overlay de producción para que no herede puertos ni código del host, declara una red interna y una red externa de proxy unida solo a `web`, conserva los volúmenes de datos y valida el resultado renderizado en CI.
- **R03:** agrega la migración **016** con una función y un trigger `BEFORE UPDATE OR DELETE` que impiden modificar o borrar resultados confirmados, sin bloquear el cierre ni el avance de llaves.
- **R04:** alinea Python 3.14, Node 24 y pnpm 12.12.1 en CI, Dockerfiles, `packageManager`, lockfile (solo el pin del gestor), AGENTS, README y constitución; incluye una puerta de compatibilidad y una enmienda constitucional 1.1.0 separada.

La implementación se ordena en ocho tareas: harness de pruebas de BD y CI, migración 015, backend R01, proyecciones públicas, migración 016, R02, R04 técnico y enmienda constitucional. R01 y R03 comparten el harness; R02 y R04 son independientes y pueden ejecutarse en paralelo después de T001.

## 2. Decisiones de diseño por correctivo

### R01 — Catálogo de jugadores por organización

**Decisión 1: catálogo por organización, no identidad global compartida.**

- Se agrega `players.organization_id UUID NOT NULL` y se trata `players` como tabla tenant-owned.
- Alternativa descartada: mantener un catálogo global con tabla puente de identidad sin PII. Se descarta porque exige dos modelos de datos y repuntes igualmente complejos, y porque el producto no necesita reconocer la misma persona entre organizaciones.
- Motivo: el aislamiento queda garantizado por RLS y por claves foráneas, no por disciplina de la aplicación; es la opción más simple que cumple los principios 1 y 3.

**Decisión 2: división determinista de registros compartidos.**

- Para cada jugador se calcula el conjunto de organizaciones que lo referencian en `rosters`, `match_rosters`, `match_lineup_snapshots`, `match_events` y `player_suspensions`.
- Si no tiene referencias, se elimina (decisión confirmada por el usuario: todo jugador legítimo tiene roster creado en la misma transacción; solo se eliminan residuos).
- Si tiene una organización, se le asigna esa organización.
- Si tiene varias, se conserva el `id` original para la organización con la referencia más antigua y se crean copias con `gen_random_uuid()` para las demás. El desempate es determinista por la marca temporal más antigua disponible y, si empatan, por el UUID de organización.
- Alternativa descartada: crear IDs nuevos para todas las organizaciones. Se descarta porque cambia `player_id` en datos públicos e históricos de la organización que podría conservar el ID original.
- Motivo: minimiza el cambio de identificadores y conserva la trazabilidad.

**Decisión 3: repunte transaccional con FKs diferidas o recreadas.**

- Antes de repuntar se eliminan o difieren las FKs dependientes; después se actualizan `rosters`, `match_rosters`, `match_lineup_snapshots`, `match_events` y `player_suspensions`; al final se recrean y validan las FKs.
- Alternativa descartada: actualizar tabla por tabla dejando las FKs activas. Se descarta porque `match_rosters` referencia `(roster_id, player_id, ...)` y `player_suspensions` referencia `match_events` con `player_id`; un orden intermedio violaría la FK.
- Motivo: la migración debe ser atómica y no dejar referencias inconsistentes ni siquiera dentro de la transacción.

**Decisión 4: claves compuestas y RLS.**

- `UNIQUE (id, organization_id)` en `players`; FKs `(player_id, organization_id)` desde `rosters`, `match_lineup_snapshots`, `match_events` y `player_suspensions`; `match_rosters` queda cubierto por su FK compuesta a `rosters`.
- `UNIQUE (organization_id, document_type, issuing_country, national_id_hmac)`; se elimina `uq_player_document`.
- RLS `ENABLE` + `FORCE` con la política tenant estándar; grants por columna con `organization_id` en `SELECT` e `INSERT`; sin `UPDATE` ni `DELETE`; `national_id_encrypted` sigue fuera de `SELECT`.
- Alternativa descartada: validar la organización solo en el backend. Se descarta por el principio 1: el aislamiento lo garantiza la base de datos.

**Decisión 5: vista cruda recreada por dependencia y wrapper público accesible.**

- La migración 015 recrea las dos definiciones que unen `players` con `security_barrier = true`, unión por `(id, organization_id)`, sin cambiar la lista ni el orden de columnas y sin `security_invoker`: `v_public_tournament_players` y `v_public_match_lineups_unpublished`.
- `v_public_tournament_players` conserva `GRANT SELECT` a `bracket_app`.
- `v_public_match_lineups_unpublished` es la vista **cruda** que alimenta al wrapper; se recrea porque el wrapper depende de ella, pero se mantiene `REVOKE ALL` a `PUBLIC` y a `bracket_app` (endurecimiento de la migración 008). No se concede `SELECT` sobre la vista cruda.
- Solo se accede a la formación pública por `v_public_match_lineups`, el wrapper filtrado que conserva `GRANT SELECT` a `bracket_app` y devuelve únicamente formación publicada.
- Se conserva el propietario actual (rol administrador/superusuario que aplica migraciones), que está exento de RLS; no se cambia a `bracket_app`. El propietario exento permite que el wrapper lea la vista cruda incluso sin contexto de organización.
- Alternativa descartada: conceder `SELECT` a `bracket_app` sobre `_unpublished`. Se descarta porque deshace el endurecimiento de 008 y expone formación no publicada, violando el principio 5.
- Alternativa descartada: convertir las vistas en funciones `SECURITY DEFINER`. Se descarta porque cambia el contrato de las vistas y obliga a tocar endpoints; el modelo actual de propietario exento ya funciona y es verificable.

**Decisión 6: deduplicación en alta e importación.**

- El backend busca por `(organization_id, document_type, issuing_country, national_id_hmac)`; inserta con `organization_id`; usa `ON CONFLICT` o reintento controlado sobre la clave única para carreras.
- `seed_demo.py` se adapta al mismo filtro y a la inserción con `organization_id`.
- Alternativa descartada: mantener una búsqueda global y descartar el resultado si es de otra organización. Se descarta porque sigue revelando la existencia del documento y deja una ventana de carrera.

### R02 — Producción sin puertos, red interna y red de proxy

**Decisión 7: `!reset`/`!override` sobre overlay autocontenido.**

- Se usa `!reset []` para `ports` y `volumes` de los servicios que heredan de desarrollo, y `!override` cuando haga falta reemplazar una secuencia.
- Alternativa descartada: duplicar todo el compose de producción en un archivo autocontenido. Se descarta porque duplica servicios, healthchecks y variables, y genera deriva entre dev y prod.
- Motivo: el overlay sigue siendo la fuente única de diferencias y el merge se valida en CI.

**Decisión 8: red interna + red externa del proxy.**

- Se declara una red `internal` para todo el stack y una red `edge` (nombre configurable con `PROXY_NETWORK`) `external: true`, ya existente y creada por el operador.
- Solo `web` se une a `edge`; `api`, `db`, `redis`, `storage`, `worker` y `db-migrate` quedan solo en `internal`.
- `web` alcanza `api` por `internal` en SSR; no hay puertos publicados.
- Alternativa descartada: publicar `web` en el host y dejar que el proxy lo alcance por puerto. Se descarta porque el requisito es no publicar ningún puerto y porque la red externa ya existe.

**Decisión 9: conservar volúmenes de datos y permitir montajes de infraestructura.**

- No se resetean los volúmenes de `db`, `redis` ni `storage`; los montajes de solo lectura de `./infra/postgres` en `db` y `db-migrate` se consideran infraestructura permitida.
- Se resetean `volumes` solo en `api`, `worker` y `web`.
- Alternativa descartada: resetear todos los `volumes`. Se descarta porque borraría el volumen de datos de PostgreSQL y los datos de Redis/almacenamiento.

**Decisión 10: validación estructural en CI.**

- Se agrega un script puro que recibe la configuración renderizada (`docker compose ... config --format json`) y devuelve errores si hay puertos, binds de código, redes incorrectas o comandos de desarrollo.
- La CI ejecuta `config -q` para desarrollo y para el merge, con variables dummy, y luego el script de aserciones.
- Alternativa descartada: confiar solo en `config -q`. Se descarta porque la sintaxis válida no garantiza que el merge no herede puertos o volúmenes.

### R03 — Inmutabilidad de resultados confirmados

**Decisión 11: trigger de base de datos, no solo aplicación.**

- Migración 016 crea `prevent_confirmed_match_result_mutation()` y el trigger `trg_protect_confirmed_match_result` `BEFORE UPDATE OR DELETE ON matches`.
- Si `OLD.result_confirmed = TRUE`:
  - `DELETE`: error explícito.
  - `UPDATE`: error si cambia con `IS DISTINCT FROM` cualquiera de: `home_score_regular`, `away_score_regular`, `home_score`, `away_score`, `home_penalties`, `away_penalties`, `winner_team_id`, `status`, `resolution_type`, `resolution_reason`, `result_confirmed`.
- Si no cambia ninguno, se permite; `updated_at` y campos no resultantes se permiten.
- Alternativa descartada: bloquear solo en el servicio de cierre. Se descarta porque no protege SQL directo ni otros caminos de escritura.
- Alternativa descartada: bloquear solo `UPDATE` y confiar en el trigger de estructura para `DELETE`. Se descarta porque el requisito es explícito y la defensa en profundidad es barata.

**Decisión 12: sin camino de corrección.**

- No hay excepción para `platform_admin` ni función de corrección. Un resultado confirmado erróneo requerirá una spec futura.
- Alternativa descartada: flujo administrativo de corrección con auditoría. Se descarta en esta spec por decisión del usuario y por el principio 3; si se necesita, se diseña aparte.

**Decisión 13: idempotencia de la migración 016.**

- `CREATE OR REPLACE FUNCTION`, `DROP TRIGGER IF EXISTS` y `CREATE TRIGGER`; se puede reejecutar sin fallar por objetos existentes.
- La migración se aplica siempre después de 015.

### R04 — Versiones de referencia y enmienda

**Decisión 14: Python 3.14, Node 24 y pnpm 12.12.1.**

- Se actualizan `ci.yml` (ambos jobs con Python y ambos usos de pnpm), `backend/Dockerfile`, `frontend/package.json`, `AGENTS.md`, README y `docs/constitution.md` §3.5.
- Alternativa descartada: quedarse en Python 3.12 y pnpm 12.11.2. Se descarta por decisión del usuario.
- Alternativa descartada: pnpm 12.12.2. Se descarta porque no existe en el registro npm; las publicadas son 12.12.0, 12.12.1, 12.13.0 y 12.14.0.

**Decisión 15: el lockfile solo cambia en el pin del gestor.**

- Se permite actualizar `packageManagerDependencies` en `frontend/pnpm-lock.yaml` a `pnpm@12.12.1`.
- No se cambian versiones de dependencias ni el resto del lockfile.
- Alternativa descartada: regenerar el lockfile completo con pnpm 12.12.1. Se descarta porque introduce cambios no revisados y puede alterar resoluciones.
- `pnpm install --frozen-lockfile` debe pasar con el pin nuevo commiteado.

**Decisión 16: puerta de compatibilidad previa, incluido `security`.**

- Antes de dar R04 por válido se ejecutan: Python 3.14 + `backend/requirements.txt` + `pytest` + `compileall`; Node 24 + pnpm 12.12.1 + `pnpm install --frozen-lockfile` + test/typecheck/build; build de imágenes; job `security` (`pip-audit`, `pnpm audit`, Trivy).
- Si algo falla, se detiene y se reporta; no se actualizan dependencias ni se regenera el lockfile más allá del pin.
- Alternativa descartada: actualizar CI primero y descubrir incompatibilidades en la rama. Se descarta porque mezcla el cambio de versión con el diagnóstico y puede dejar CI roja por dependencias.

**Decisión 17: enmienda 1.1.0 separada.**

- La constitución pasa a 1.1.0: cabecera, §3.5 y nueva fila de historial; se conserva la fila 1.0.1.
- Es incremento menor, no parche, porque cambia el contenido de una regla de implementación. La 1.1.0 regulariza el cambio ya presente en `HEAD` (§3.5 con 3.14/12.12.2 sin subir versión) y lo corrige a 12.12.1.
- Alternativa descartada: parche 1.0.2, como sugería la auditoría. Se descarta porque un parche no debe alterar el significado de una regla.
- La enmienda se commitea aparte de R01-R03 y de los cambios técnicos de R04, con revisión humana.

## 3. Orden de implementación y dependencias

```text
T001 Harness PostgreSQL + servicio CI
  ├─ T002 Migración 015 (esquema, datos, definiciones, wrapper y grants)
  │    ├─ T003 Backend R01 (alta, importación, seed)
  │    └─ T004 Vistas públicas: definición, propiedad y tests
  └─ T005 Migración 016 + tests R03
T006 R02 overlay + validación CI        (independiente, puede ir en paralelo)
T007 R04 técnico + puerta de versiones  (independiente, puede ir en paralelo)
T008 Enmienda constitucional 1.1.0      (después de T007; commit separado)
```

Dependencias duras:

- **015 antes que 016.** El historial debe quedar 015 y luego 016. Si R03 se fusiona antes que R01, se espera a 015 o se rebasa la rama para no dejar `016` aplicado sin `015`.
- **T001 antes de T002, T003, T004 y T005** para que las pruebas de BD tengan servicio, rol y fixtures.
- **T002 antes de T003 y T004**: el backend y las vistas dependen del esquema.
- **T003 y T004 pueden solaparse** una vez aplicado 015; T004 verifica las vistas y solo ajusta la migración si aún no se aplicó a una base compartida.
- **T006, T007 y T008** no dependen de R01/R03. T008 depende de T007 para que la enmienda refleje las versiones ya alineadas.
- R02 y R04 tocan `.github/workflows/ci.yml`; coordinar el merge para no pisar el job de infraestructura con el job de PostgreSQL.
- T006 y T007 tocan `AGENTS.md` y `README.md`: T006 agrega Compose/red y T007 las versiones. Coordinar el orden de commits para evitar conflictos; la verificación de T007 excluye la constitución hasta que T008 la enmiende.

## 4. Archivos y responsabilidades

| Archivo o grupo | Responsabilidad | Tarea |
|---|---|---|
| `infra/postgres/migrations/015_player_catalog_tenant_isolation.sql` | Columna, RLS, unicidad, FKs, grants, división/repunte, dos definiciones y wrapper de formación | T002 |
| `infra/postgres/migrations/016_confirmed_match_result_immutability.sql` | Función y trigger de inmutabilidad | T005 |
| `backend/app/modules/tournaments/router.py` | Alta individual, importación masiva, dedupe por organización y joins con `players` | T003 |
| `backend/scripts/seed_demo.py` | Inserción con `organization_id` y dedupe por organización | T003 |
| `backend/app/modules/matches/service.py` | Sin cambio funcional; se verifica que el cierre siga funcionando | T005 |
| `backend/app/modules/matches/router.py`, `backend/app/modules/tournaments/router.py` | Revisión de joins con `players` y proyecciones | T003/T004 |
| `backend/tests/conftest.py`, `backend/tests/db_helpers.py` | Harness de BD, roles, organizaciones y aislamiento | T001 |
| `backend/tests/test_player_catalog_schema.py` | Esquema, RLS, unicidad y FKs | T002 |
| `backend/tests/test_player_catalog_migration.py` | Migración desde 014, división, repunte y huérfanos | T002 |
| `backend/tests/test_player_catalog_isolation.py` | Aislamiento A/B, dedupe y alta/importación | T003 |
| `backend/tests/test_public_player_views.py` | `v_public_tournament_players`, wrapper `v_public_match_lineups`, acceso denegado a la cruda y sin PII | T004 |
| `backend/tests/test_match_result_immutability.py` | UPDATE/DELETE, cierre, avance, bracket reset y seed | T005 |
| `docker-compose.production.yml` | Puertos, volúmenes, redes y comandos de producción | T006 |
| `docker-compose.yml` | Solo si hace falta para la validación; no se cambian puertos de desarrollo | T006 |
| `infra/scripts/assert_production_compose.py` | Función pura de aserciones sobre la configuración renderizada | T006 |
| `backend/tests/test_production_compose_assertions.py` | Pruebas unitarias del validador de Compose | T006 |
| `infra/scripts/verify_version_sources.py` | Comprobación de consistencia de versiones entre fuentes técnicas y documentación | T007/T008 |
| `.github/workflows/ci.yml` | Servicio PostgreSQL, job de BD, merge de producción, versiones y security | T001/T006/T007 |
| `backend/Dockerfile`, `frontend/package.json`, `frontend/pnpm-lock.yaml` | Python 3.14, pnpm 12.12.1 y pin del gestor | T007 |
| `AGENTS.md`, `README.md` | Versiones, Compose ≥2.24.4, red externa y comandos | T006/T007 |
| `docs/constitution.md` | Enmienda 1.1.0 | T008 |

No se prevén cambios en frontend funcional, endpoints, contratos públicos, `.env.example` ni en migraciones aplicadas.

## 5. Funciones puras

Las siguientes funciones no leen el reloj ni el entorno; reciben todos sus datos como parámetros y son testeables sin base de datos:

- `player_identity_key(document_type, issuing_country, national_id_hmac) -> tuple[str, str, str]`: normaliza la clave de deduplicación.
- `choose_original_organization(refs: Sequence[PlayerOrgRef]) -> UUID`: elige la organización que conserva el `player_id` original usando la marca temporal más antigua y el UUID como desempate. Las marcas vienen de los datos, no de `now()`.
- `build_player_split_plan(refs: Sequence[PlayerOrgRef], player_id: UUID) -> list[PlayerSplit]`: produce la lista de copias y el mapeo `(old_player_id, organization_id) -> new_player_id`. Se usa como referencia en tests de la migración.
- `protected_result_fields_changed(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool`: compara solo los campos protegidos con semántica `IS DISTINCT FROM`; se usa para generar casos de prueba y documentar el contrato del trigger.
- `parse_semver(version: str) -> tuple[int, int, int]` y `version_at_least(version: str, minimum: str) -> bool`: comparan mayor, menor y parche para Compose.
- `validate_production_config(config: Mapping[str, Any]) -> list[str]`: recibe la configuración renderizada y devuelve una lista de errores; no ejecuta Docker.
- `validate_version_sources(sources: Mapping[str, str]) -> list[str]`: recibe el contenido de CI, Dockerfiles, `package.json`, AGENTS, README y constitución y devuelve discrepancias de versión.

La migración 015 implementa el mismo algoritmo de división en SQL; `build_player_split_plan` es la referencia ejecutable en tests para calcular el resultado esperado.

## 6. Algoritmos y pseudocódigo

### 6.1 R01 — División y repunte en la migración 015

```text
BEGIN
  ALTER TABLE players ADD COLUMN IF NOT EXISTS organization_id UUID;

  refs = SELECT player_id, organization_id, MIN(ref_at) AS first_ref_at
         FROM (
           rosters (registered_at),
           match_rosters (match_date o created_at del partido),
           match_lineup_snapshots (created_at del segmento/partido),
           match_events (created_at),
           player_suspensions (created_at)
         )
         GROUP BY player_id, organization_id;

  DELETE FROM players p
  WHERE NOT EXISTS (SELECT 1 FROM refs r WHERE r.player_id = p.id);

  FOR cada player con refs:
    orgs = refs del jugador
    owner = min(orgs) por (first_ref_at, organization_id)
    UPDATE players SET organization_id = owner WHERE id = player.id
    FOR cada org distinta de owner:
      new_id = gen_random_uuid()
      INSERT INTO players (id, organization_id, first_name, last_name, document_type,
                           national_id_encrypted, national_id_hmac, issuing_country,
                           birth_date, photo_url, created_at)
      SELECT new_id, org, ... FROM players WHERE id = player.id;
      mapping[(player.id, org)] = new_id
    mapping[(player.id, owner)] = player.id

  -- Evitar violaciones transitorias:
  DROP o DEFERRABLE de FKs dependientes de player_id;
  UPDATE rosters SET player_id = mapping[(player_id, organization_id)];
  UPDATE match_rosters SET player_id = mapping[(player_id, organization_id)];
  UPDATE match_lineup_snapshots SET player_id = mapping[(player_id, organization_id)];
  UPDATE match_events SET player_id = mapping[(player_id, organization_id)];
  UPDATE player_suspensions SET player_id = mapping[(player_id, organization_id)];

  ALTER TABLE players ALTER COLUMN organization_id SET NOT NULL;
  DROP CONSTRAINT uq_player_document;
  ADD UNIQUE (organization_id, document_type, issuing_country, national_id_hmac);
  ADD UNIQUE (id, organization_id);
  ADD FKs compuestas;
  ENABLE/FORCE RLS + política;
  GRANT SELECT/INSERT con organization_id;
  CREATE OR REPLACE las dos definiciones con join por organización;
  REVOKE ALL en v_public_match_lineups_unpublished; mantener GRANT de v_public_match_lineups;
  RE-ADD/validate FKs;
COMMIT;
```

Reglas de idempotencia: `ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS`, `DROP POLICY IF EXISTS`, y el bloque de división solo procesa filas con `organization_id IS NULL`.

### 6.2 R03 — Trigger de inmutabilidad

```text
CREATE OR REPLACE FUNCTION prevent_confirmed_match_result_mutation()
RETURNS TRIGGER AS $$
BEGIN
  IF OLD.result_confirmed = TRUE THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'Un resultado confirmado no se puede borrar' USING ERRCODE = '23514';
    END IF;

    IF NEW.home_score_regular IS DISTINCT FROM OLD.home_score_regular
       OR NEW.away_score_regular IS DISTINCT FROM OLD.away_score_regular
       OR NEW.home_score IS DISTINCT FROM OLD.home_score
       OR NEW.away_score IS DISTINCT FROM OLD.away_score
       OR NEW.home_penalties IS DISTINCT FROM OLD.home_penalties
       OR NEW.away_penalties IS DISTINCT FROM OLD.away_penalties
       OR NEW.winner_team_id IS DISTINCT FROM OLD.winner_team_id
       OR NEW.status IS DISTINCT FROM OLD.status
       OR NEW.resolution_type IS DISTINCT FROM OLD.resolution_type
       OR NEW.resolution_reason IS DISTINCT FROM OLD.resolution_reason
       OR NEW.result_confirmed IS DISTINCT FROM OLD.result_confirmed
    THEN
      RAISE EXCEPTION 'Un resultado confirmado es inmutable' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_protect_confirmed_match_result ON matches;
CREATE TRIGGER trg_protect_confirmed_match_result
BEFORE UPDATE OR DELETE ON matches
FOR EACH ROW EXECUTE FUNCTION prevent_confirmed_match_result_mutation();
```

El cierre normal (`OLD.result_confirmed = FALSE`) no entra en el bloque y puede escribir todos los campos y `result_confirmed = TRUE` en la misma sentencia.

### 6.3 R02 — Aserciones sobre la configuración renderizada

```text
config = docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json

errores = []
for service in config.services:
    if service.ports no vacío: error
    if service in {api, worker, web}:
        for volume in service.volumes:
            if volume.type == "bind" and source in {./backend, ./frontend, ./infra}: error
    if service in {db, db-migrate}:
        for volume in service.volumes:
            if volume.type == "bind" and source not under ./infra/postgres: error
    if service == web:
        if networks != {internal, edge}: error
    else:
        if networks != {internal}: error
if config.networks.edge.external != true: error
if api.command contiene "--reload": error
if web.command no es "node .output/server/index.mjs": error
return errores
```

La CI ejecuta `config -q` primero y luego el script; si el script devuelve errores, el job falla.

### 6.4 R04 — Puerta de compatibilidad y comparación de versiones

```text
if not version_at_least(compose_version, "2.24.4"): fail
python3.14 -m venv /tmp/bc-py314
pip install -r backend/requirements.txt
pytest -q && python -m compileall -q app

pnpm 12.12.1 install --frozen-lockfile
pnpm test && pnpm run typecheck && pnpm run build

docker build backend && docker build frontend
pip-audit -r backend/requirements.txt
pnpm audit --prod --audit-level high
trivy fs . --skip-dirs frontend/node_modules,frontend/.pnpm-store,.venv \
  --ignore-unfixed --severity CRITICAL,HIGH --exit-code 1

if cualquier paso falla:
    detener, reportar evidencia, no actualizar dependencias ni regenerar lockfile
```

`validate_version_sources` comprueba que `ci.yml`, `backend/Dockerfile`, `frontend/package.json`, `AGENTS.md`, README y `docs/constitution.md` declaren la misma combinación. El pin de `pnpm-lock.yaml` se revisa con un diff acotado a `packageManagerDependencies`.

## 7. Interfaces y contratos

- **API:** no hay endpoints nuevos ni cambios de forma en las respuestas. El único cambio observable es que un documento registrado en otra organización ya no devuelve el jugador ajeno: se crea un registro local y el alta responde como alta nueva.
- **Workspace:** las consultas de rosters siguen devolviendo los mismos campos; cambia el filtro interno por organización.
- **Público:** se mantienen los campos de `v_public_tournament_players` y `v_public_match_lineups` (wrapper filtrado); `v_public_match_lineups_unpublished` es una definición interna, no accesible a `bracket_app`, y no se agregan documentos ni fechas de nacimiento.
- **Compose:** se agregan las redes `internal` y `edge`; `edge` es externa y su nombre se configura con `PROXY_NETWORK`. No hay puertos publicados en producción.
- **Configuración:** `PROXY_NETWORK` es una variable de despliegue de producción; se documenta en AGENTS/README y no se agrega a `.env.example`, que es solo de desarrollo.
- **CI:** el job de backend incorpora PostgreSQL de servicio, `DATABASE_URL` para el rol de aplicación y `DATABASE_ADMIN_URL` para las pruebas de migración con `RUN_DATABASE_TESTS=1`; el job de infraestructura valida dev y el merge; el job de security se ejecuta con las versiones objetivo.
- **Frontend:** sin cambios funcionales ni de llamadas HTTP.

## 8. Base de datos

### 8.1 Migración 015

- Agrega `organization_id`, backfill, división, repunte, limpieza de huérfanos, `NOT NULL`, RLS, unicidad, FKs compuestas, grants y las dos definiciones que unen `players` más el wrapper de formación.
- Mantiene `REVOKE ALL` sobre `v_public_match_lineups_unpublished` para `PUBLIC` y `bracket_app`, y conserva el `GRANT SELECT` de `v_public_match_lineups`.
- Se aplica sobre volumen limpio (init + 001-015) y sobre volumen en estado 014.
- La verificación de 014 se hace en una base o esquema aparte, aplicando selectivamente 001-014 y sembrando un jugador compartido por dos organizaciones.
- La migración se ejecuta con el rol administrador; las pruebas de aislamiento con `bracket_app`.
- No se edita ninguna migración aplicada.

### 8.2 Migración 016

- Crea la función y el trigger idempotentes.
- Se aplica después de 015; la secuencia aplicada es 015 y luego 016.
- No modifica datos; si hay que corregir el trigger, se hace con una migración posterior, no editando 016.

### 8.3 RLS y aislamiento

- `players` usa la misma política tenant que el resto: `organization_id = current_setting('app.current_organization_id')` y `fn_verify_user_org_membership(organization_id)`.
- El rol de aplicación no es superusuario ni tiene `BYPASSRLS`.
- Las FKs compuestas son la segunda barrera: aunque una consulta intente cruzar organizaciones, la base rechaza la referencia.

### 8.4 Vistas públicas, vista cruda y wrapper

- `v_public_tournament_players` y `v_public_match_lineups_unpublished` se recrean con `security_barrier = true` y join por `(id, organization_id)`.
- `v_public_tournament_players` conserva `GRANT SELECT` a `bracket_app`.
- `v_public_match_lineups_unpublished` se recrea por dependencia del wrapper, pero se mantiene `REVOKE ALL` a `PUBLIC` y `bracket_app`; no se concede `SELECT`.
- `v_public_match_lineups` (wrapper filtrado) conserva `GRANT SELECT` a `bracket_app` y devuelve solo formación publicada.
- El propietario de las definiciones se mantiene exento de RLS y no se activa `security_invoker`.
- Se prueba con `bracket_app` y sin `app.current_organization_id` que `v_public_tournament_players` y `v_public_match_lineups` devuelven filas, y que `_unpublished` produce permiso denegado.

## 9. Backend, eventos y frontend

- **Backend R01:** `_create_roster_player_record` filtra por `organization_id`, inserta `organization_id` y resuelve carreras con la clave única. La importación masiva reutiliza el mismo helper. `seed_demo.py` usa el mismo criterio. No se crea un módulo nuevo ni se registra un router adicional en `backend/app/main.py`; las consultas siguen usando `set_rls_context()` dentro de la transacción.
- **Joins con `players`:** se revisan `tournaments/router.py` y `matches/router.py` para que cualquier join en el Workspace incluya la organización. Las definiciones y el wrapper se corrigen en la migración.
- **R03:** `matches/service.py` no cambia; el cierre ya escribe `result_confirmed = TRUE` desde `FALSE` y el trigger lo permite. Se verifica cierre, resolución administrativa, avance de llaves y bracket reset.
- **Eventos asíncronos:** no hay eventos nuevos ni cambios de outbox. El cierre sigue emitiendo `MATCH_CLOSED`, `MATCH_UPDATED` y `STANDINGS_UPDATED`.
- **Frontend:** no hay cambios; los contratos y las rutas se mantienen.

## 10. Exposición pública

Campos que siguen expuestos por las proyecciones públicas:

- `v_public_tournament_players`: `tournament_id`, `player_id`, `first_name`, `last_name`, `dorsal_number`, `team_id`, `public_age`, `photo_url` (solo con consentimiento).
- `v_public_match_lineups` (wrapper filtrado): los campos actuales de formación/planilla pública, incluidos `player_id`, nombres, dorsal, rol, posición y `photo_url` con consentimiento; solo formación publicada.

`v_public_match_lineups_unpublished` es una definición interna que alimenta al wrapper: no se expone a `bracket_app` ni a `PUBLIC`. No se exponen `document_type`, `national_id_encrypted`, `national_id_hmac` ni `birth_date`. La foto depende de `rosters.photo_consent`; el join por organización evita mezclar plantillas.

## 11. Configuración y secretos

- No se agregan secretos ni defaults de desarrollo.
- `PROXY_NETWORK` es una variable de despliegue de producción; se documenta con un valor de ejemplo (`edge`) en AGENTS/README, no en `.env.example`.
- La CI del merge usa valores dummy para `POSTGRES_PASSWORD`, `BRACKET_DB_PASSWORD`, `PLATFORM_ADMIN_EMAIL`, `JWT_SECRET`, `PLAYER_DATA_KEY`, `INVITATION_TOKEN_KEY`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`, `STORAGE_*`, `FRONTEND_BASE_URL`, `SMTP_*` y `NUXT_*`; no son secretos reales.
- Los defaults de desarrollo siguen solo en `.env.example`.

## 12. Estrategia de pruebas

### 12.1 Unitarias

- Funciones puras de versión, aserciones de Compose y plan de división.
- Serialización/validación de los DTOs existentes, sin cambios esperados.
- `python -m compileall -q app`.

### 12.2 Integración con PostgreSQL

Harness de T001:

1. Servicio PostgreSQL 17 efímero con healthcheck.
2. Rol administrador aplica `infra/postgres/init` y las migraciones disponibles con `infra/postgres/migrate.sh`; al completar R01/R03, la secuencia es 001-016. La CI exporta `DATABASE_ADMIN_URL` para las pruebas de migración, y su ausencia hace fallar la prueba en vez de saltarla.
3. Se crea/verifica `bracket_app` sin superusuario y sin `BYPASSRLS`.
4. Cada test usa `DATABASE_URL` del rol de aplicación y `RUN_DATABASE_TESTS=1`.
5. Cada test crea organizaciones y usuarios propios con `create_organization_with_owner` (SECURITY DEFINER) y limpia por transacción revertida o borrado acotado.
6. Los tests de R01/R03 se ejecutan en serie y no comparten filas; la suite unitaria sigue funcionando sin base.

Prueba de migración:

- Base o esquema aparte en estado 014 (001-014).
- Insertar dos organizaciones, un jugador compartido, rosters en ambas, un `match_roster`, una alineación, un evento y una suspensión.
- Aplicar 015 y 016.
- Verificar: dos jugadores, referencias repuntadas, conteos, suspensión coherente, huérfano eliminado, historial 015→016.
- Repetir sobre volumen limpio y reejecutar 015/016 para idempotencia.

Pruebas de proyecciones públicas:

- `v_public_tournament_players` con `bracket_app` y sin `app.current_organization_id` devuelve las filas del torneo publicado.
- `v_public_match_lineups` (wrapper) en las mismas condiciones devuelve solo formación publicada.
- `v_public_match_lineups_unpublished` produce permiso denegado con `bracket_app`; se verifica que no tiene `SELECT` para `bracket_app` ni `PUBLIC`.
- Ninguna de las proyecciones accesibles expone documentos, HMAC ni fechas de nacimiento; `photo_url` depende del consentimiento.

### 12.3 Compose

- `docker compose config -q` para desarrollo.
- Merge dev+prod con variables dummy y `config -q`.
- Script de aserciones sobre `--format json`: puertos, binds, redes, comandos, volúmenes.
- Comprobación de versión de Compose ≥2.24.4 comparando parche.

### 12.4 Versiones

- Puerta de compatibilidad de Python 3.14, pnpm 12.12.1, imágenes y job `security` (con la excepción §5.1 de la spec para los hallazgos preexistentes de `simple-git`).
- `validate_version_sources` contra todas las fuentes.
- Diff de `pnpm-lock.yaml` acotado a `packageManagerDependencies`.
- `pnpm install --frozen-lockfile` con el pin nuevo.

### 12.5 Documentación y gobernanza

- Cabecera, historial y §3.5 de la constitución en 1.1.0.
- AGENTS/README con versiones, Compose ≥2.24.4, red externa y comandos.
- `git status` limpio para esos archivos.
- Revisión humana de la enmienda.

## 13. Cobertura de requisitos

| RF | Tarea(s) |
|---|---|
| RF-001 Aislamiento del catálogo | T002, T003, T004 |
| RF-002 Esquema tenant-owned y claves | T002 |
| RF-003 Deduplicación intraorganización y seed | T002, T003 |
| RF-004 Migración 015 sin pérdida | T002 |
| RF-005 Proyecciones públicas, vista cruda y wrapper | T002, T004 |
| RF-006 Producción sin puertos y redes | T006 |
| RF-007 Artefactos, volúmenes y montajes de infraestructura | T006 |
| RF-008 CI valida dev y merge | T006 |
| RF-009 Compose ≥2.24.4 | T006 |
| RF-010 Bloqueo de UPDATE confirmado | T005 |
| RF-011 Bloqueo de DELETE confirmado | T005 |
| RF-012 Cierre y operaciones legítimas | T005 |
| RF-013 Migración 016 idempotente y orden | T005 |
| RF-014 Versiones de referencia y pin del gestor | T007 |
| RF-015 Puerta de compatibilidad incluida security | T007 |
| RF-016 Enmienda constitucional 1.1.0 | T008 |
| RF-017 Estado documental y del repositorio | T007, T008 |
| RF-018 Pruebas de BD en CI con PostgreSQL | T001, T002, T003, T004, T005 |

## 14. Verificación contra la constitución

| Principio, regla o criterio | Aplica | Cómo lo cumple el plan | Evidencia o check |
|---|---|---|---|
| 1. Aislamiento por tenant garantizado por la base de datos | Sí (R01) | `players` tenant-owned con `organization_id`, RLS `FORCE`, unicidad por organización y FKs compuestas | Tests de esquema, RLS y FKs; consulta directa sin contexto; migración 015 |
| 2. La aplicación no puede saltarse RLS | Sí (R01) | No se eleva el rol; `bracket_app` sigue sin superusuario ni `BYPASSRLS`; tests con ese rol | T001 verifica atributos del rol; T002/T003 pruebas con `bracket_app` |
| 3. Lo publicado es inmutable | Sí (R03) | Trigger `BEFORE UPDATE OR DELETE` sobre resultados confirmados; sin excepción para `platform_admin` | T005: UPDATE por campo, DELETE, cierre, avance y bracket reset |
| 4. Historial de esquema append-only | Sí (R01, R03) | Solo migraciones nuevas 015 y 016; no se editan aplicadas; orden 015→016 | `sh -n infra/postgres/migrate.sh`; revisión de `git diff`; prueba de migración |
| 5. Lo público es una proyección mínima | Sí (R01) | Definiciones con join por organización; vista cruda revocada a `bracket_app`/`PUBLIC`; solo el wrapper filtrado es accesible; sin documentos ni fechas de nacimiento; foto con consentimiento | T004: consulta sin contexto a `v_public_tournament_players` y `v_public_match_lineups`; permiso denegado en `_unpublished`; aserción de columnas |
| 6. Ningún secreto por defecto fuera de desarrollo | Sí (R02, R04) | Producción sigue exigiendo secretos externos; CI usa dummy; no se agregan defaults | `docker compose config` con dummy; revisión de `.env.example` sin cambios |
| 7. Administración global separada y auditada | Sí (R03) | `platform_admin` no puede modificar ni borrar resultados confirmados; no hay ruta nueva | T005: prueba con rol de aplicación; revisión de triggers |
| 8. Nada se da por terminado sin verificación | Sí (todas) | Cada tarea tiene check propio; CI con PostgreSQL; puerta de versiones; se declara lo no ejecutado | Comandos de tasks.md; jobs `backend`, `infrastructure`, `security` |
| 9. El código de desarrollo no llega a producción | Sí (R02) | Producción no monta código en `api`/`worker`/`web`; solo permite infraestructura de PostgreSQL; no publica puertos | T006: aserciones sobre configuración renderizada |
| §3.1 RLS y migraciones | Sí | `players` con RLS y políticas; migraciones numeradas con checksum; verificación limpio/migrado | T002/T005; `migrate.sh`; prueba desde 014 |
| §3.2 Backend asíncrono y outbox | Sí (R01/R03) | No se cambian patrones async; el cierre sigue usando el outbox existente | `pytest -q`; revisión de que no hay eventos nuevos |
| §3.3 Frontend | No aplica | No hay cambios de frontend ni de `useApi.ts` | `git diff` sin archivos frontend funcionales |
| §3.4 Seguridad y datos personales | Sí (R01) | Documento cifrado fuera de `SELECT`; PII solo en la organización; sin logs de PII | Tests de grants y de vistas; revisión de logs/mensajes |
| §3.5 Infraestructura y CI | Sí (R02, R04) | Compose ≥2.24.4, Python 3.14, Node 24, pnpm 12.12.1 y validación del merge | T006/T007; `docker compose version`; `ci.yml`; puerta de versiones |
| §4 criterios para cambios de BD | Sí | Migración nueva, RLS, FKs, prueba limpio/migrado, `sh -n` | T002/T005 |
| §4 criterios para API/backend | Sí | Consultas tenant con `set_rls_context`; sin campos sensibles; `pytest` y `compileall` | T003/T004; `cd backend && pytest -q`; `compileall` |
| §4 criterios para infraestructura | Sí | `docker compose config -q` para dev y merge; sin defaults de desarrollo en producción | T006 |
| §4 criterios para dependencias | Sí (R04) | Lockfile versionado; auditorías con versiones objetivo; solo cambia el pin del gestor | T007; `pip-audit`, `pnpm audit`, Trivy |
| §5.2 Evolución de la constitución | Sí (R04) | Enmienda 1.1.0 con motivo, impacto, historial y revisión humana; commit separado | T008; revisión humana; `git show` del commit |
| §6 Definición de cumplimiento | Sí | CI en verde, revisión humana distinta del autor y verificación honesta | Jobs de CI; registro de revisiones; informe de verificaciones no ejecutadas |

## 15. Riesgos, mitigaciones y reversión

| Riesgo | Mitigación | Reversión |
|---|---|---|
| La división de jugadores rompe referencias | Mapeo determinista, FKs diferidas/recreadas, conteos antes/después, prueba desde 014 | La migración 015 es transaccional: si falla, rollback. Si ya se aplicó y el dato es incorrecto, restaurar backup y corregir con migración 017; no editar 015 |
| La migración 015 bloquea tablas o tarda | Repunte por conjunto, sin bucles fila por fila, ventana de mantenimiento y prueba de volumen | Rollback de la transacción; forward-fix |
| El aislamiento rompe vistas o consultas, o expone la vista cruda | Revisión de todos los joins, pruebas sin contexto con `bracket_app`, permiso denegado en `_unpublished` y verificación de grants | Si 015 ya se aplicó, migración 017 para corregir vistas/grants; no editar 015 |
| El trigger 016 bloquea un flujo legítimo | Lista acotada de campos, comparación `IS DISTINCT FROM`, pruebas de cierre/avance/reset | Migración 017 que reemplace la función o elimine el trigger; no editar 016 |
| R02 hereda puertos o volúmenes | `!reset`/`!override`, aserciones renderizadas y CI | Revertir el commit de `docker-compose.production.yml` y el paso de CI |
| La red externa no existe | Prerrequisito documentado y nombre configurable; CI valida `external: true` sin crearla | Cambiar `PROXY_NETWORK` o revertir el overlay; el proxy queda fuera del compose |
| R04 rompe dependencias | Puerta de compatibilidad previa, incluido `security`; no se actualizan dependencias | Revertir el commit técnico de R04; la enmienda se revierte con otra enmienda revisada, sin reescribir historial |
| El pin del lockfile exige cambios adicionales | Diff acotado a `packageManagerDependencies`; si hay más cambios, se detiene | Revertir el pin y reportar |
| Orden 016 antes que 015 | Tareas y revisión exigen 015→016; no fusionar R03 antes de R01 | Reordenar la rama; si ya se aplicó 016, aplicar 015 antes de cualquier uso y documentar el orden |
| Pruebas de BD lentas o inestables | Servicio efímero, datos únicos, transacciones, ejecución serial | Aislar el test, no desactivarlo; si es imposible, declararlo y no cerrar la spec |

## 16. Verificaciones no ejecutables localmente

- **Docker/Compose:** el entorno de planificación observó Docker 29.8.2 y Compose v5.5.1, pero no se ejecutó el merge ni el arranque de servicios. T006 debe ejecutarse en CI o en un entorno con Docker; si no, se declara como no verificado.
- **PostgreSQL:** si no hay una instancia disponible, las pruebas de T002-T005 se ejecutan en CI con el servicio de PostgreSQL; no se declaran aprobadas por inspección.
- **Python 3.14 / pnpm 12.12.1:** si el entorno local no tiene esas versiones, la puerta de T007 se ejecuta en CI o con imágenes Docker; si no se puede, se declara y no se marca R04 como implementado.
- **Auditorías (`pip-audit`, `pnpm audit`, Trivy):** requieren instalación/red. Si no se pueden ejecutar localmente, se ejecutan en el job `security` de CI o se declaran como no ejecutadas.
- **Regla:** ninguna verificación no ejecutada se reporta como aprobada; se anota en la validación final con su motivo.
