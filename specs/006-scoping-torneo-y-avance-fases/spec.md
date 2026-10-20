# Spec 006 — Retiro del scoping por torneo y avance manual entre fases

Estado: Implementada y validada por @reviewer (APROBADA, 2026-10-20); pendiente de CI en main y revisión humana (T011).

> **Bloque C del P1** de `docs/auditoria-2026-10-19.md`: R06 (scoping por torneo muerto) y R12 (avance entre fases sin motor). Las decisiones de producto están cerradas: **R06 se retira** y se documenta el modelo real; **R12 se resuelve con avance manual operativo** (API y UI mínima), sin sembrado automático. R09/R10, R11 y R18-R32 quedan fuera y no se documentan como resueltos.

## Decisiones cerradas (2026-10-20)

Decisiones de producto aprobadas por el usuario. El plan no puede reabrirlas.

- **Q1 = A (R06).** Se retira `tournament_user_roles` y el ámbito por torneo inerte. El modelo real queda documentado: **RBAC por organización** + **`match_officials` por partido**. No se implementan roles por torneo.
- **Q2 = B (R12).** Se hace **operativo el avance manual**: asignar equipos ya registrados a una fase, con API y UI mínima. El **sembrado automático** (`stage_rank` desde `standings`) queda **fuera de alcance** y se documenta como no soportado.
- **Q3.** No aplica: solo existía si Q1 hubiera sido B o C.
- **Q4 = A.** El avance manual solo se permite en versiones en **borrador**. Las versiones publicadas o archivadas siguen siendo inmutables; cualquier intento responde **409**. **Sin excepción constitucional** ni cambio de triggers.
- **Q5 = A. Migración `019` quirúrgica:** elimina `tournament_user_roles`, elimina `stage_edges`, estrecha el CHECK de `phase_slots.source_type` y **conserva `phase_slots`** como procedencia de la llave. Ajusta código, RLS, grants, clonado, seed y pruebas.
- **Q6 = 409 por clasificación.** Al quitar de una fase un equipo que tiene fila en `standings`, aunque no tenga partidos, el `DELETE` responde **409** y exige resolver la clasificación primero. No se borran filas de `standings` automáticamente.
- **Q-B1 = A (confirmada).** `init/01` conserva hasta la 019 el `CREATE TABLE` y los flags `ENABLE`/`FORCE` de ambas tablas, porque la migración `011` los altera sin guardas; se retiran **solo** sus políticas y grants (más el trigger `trg_protect_stage_edges`, que deja de tener sentido). La 019 las elimina. El esquema final de un volumen limpio es idéntico al de uno migrado.

## Resoluciones de la revisión (2026-10-20)

Cierran los puntos A-D de la revisión del usuario; no cambian el alcance.

- **R-A. Lote atómico.** El `POST` asigna todos los equipos o ninguno. Duplicados dentro del lote: **422** en la validación de esquema, sin deduplicar en silencio. `assigned` y `already_assigned` son **dos arrays de UUID**, nunca conteos. Si el lote tiene al menos un equipo nuevo, responde **201**; si **todos** ya estaban asignados (`assigned = []`, sin escrituras), responde **200**. Repetir el mismo lote pasa de 201 a 200. No se usa 200 para altas.
- **R-B. Bloqueo y SQLSTATE.** Orden único **fase → versión → partido(s) → segmentos → jugadores** para las rutas que bloquean fase y versión. El trigger de inmutabilidad usa el SQLSTATE estable **`ZZ409`** (clase de usuario, sin colisión con códigos estándar), creado por la 019; el backend lo mapea a 409 sin mirar el texto. Se añaden pruebas de concurrencia reales y de orden de bloqueo con mocks.
- **R-C. Migración 019.** Los tres pre-chequeos (filas de `tournament_user_roles`, filas de `stage_edges`, valores de `source_type`) se ejecutan **antes del primer `DROP`**, en una transacción; `DROP ... IF EXISTS` es solo salvaguarda. Incluye consulta de catálogo con FKs entrantes y `to_regclass`, copia verificada y *forward-fix*.
- **R-D. Pruebas.** Versión publicada con equipo ya asignado → 409 (no 200/201); arrays `assigned`/`already_assigned` y transición 201→200; dos POST/DELETE simultáneos; DELETE contra creación de partido; orden de bloqueo de standings con mocks; mapeo de `ZZ409` sin depender del mensaje.

## Correcciones de la vuelta 1 (2026-10-20)

Cierran los hallazgos de la verificación posterior a la implementación. No cambian el alcance.

- **H5 — referencias en pruebas.** RF-008 se corrige: las pruebas de la propia migración (`backend/tests/test_migration_019.py` y `migration_helpers.py`) nombran `tournament_user_roles`/`stage_edges` para verificar el retiro. La regla es **sin referencias en código de aplicación, seed ni verificadores**, con esas pruebas como excepción justificada.
- **H10 — rendimiento no medido.** El cierre serializa por fase (`lock_stage_and_version`) como garantía de corrección. **No se midió throughput ni latencia**; la afirmación de no degradación es un objetivo no verificado, no un hecho.
- **H1 — cobertura opt-in real.** La suite opt-in ejecutó **42 pruebas** (`player_catalog_isolation` + `schema` + `swiss_transaction`, incluida la 020) y **23 pruebas** (`concurrency_006` + `migration_019`), incluidos cross-tenant, dos DELETE, guarda de `standings`, 409 directo en publicada con equipo asignado y no asignado, `ZZ409` por API, `GET` tras clonar y permisos owner/administrator/operator/referee.
- **H2 — orden de partidos.** Todas las consultas de partidos que se bloquean usan `ORDER BY id`, incluidas `_clear_stage_schedule` y los placeholders Swiss; no se usa `ORDER BY bracket_code`.
- **H4 — UI deshabilitada.** Los botones de asignar/quitar se **renderizan deshabilitados** sin `MANAGE_TOURNAMENTS` o fuera de borrador; no se ocultan.
- **H7/H8 — oficiales y GF2.** El alta/baja de oficiales toma el bloqueo del partido (`lock_matches`). `GF2` se pre-bloquea siempre que el origen sea `GF1` y `GF2` exista, aunque el reset no se active en ese cierre.
- **H11 — forward-fix de privilegios (020).** La importación N-2 pre-genera el `id` del roster para subir la foto antes de la transacción y construir la clave del objeto. El `INSERT INTO rosters (id, ...)` explícito chocaba con el grant por columnas de `bracket_app`; la **020**, no destructiva y posterior a la 019, concede solo `INSERT (id)` sobre `public.rosters` (nunca `INSERT` de tabla). `init/01` incluye el mismo grant para un volumen limpio. Se registra como corrección, no como ampliación del alcance funcional.
- **H12 — Fix B de la prueba opt-in.** `tournament_b` quedó capturado correctamente en `test_swiss_transaction.py`; la prueba opt-in de RLS ya pasa.
- **Evidencia local actualizada:** backend **469 passed / 132 skipped**; opt-in **42 passed** (`player_catalog_isolation` + `schema` + `swiss_transaction`) y **23 passed** (`concurrency_006` + `migration_019`); frontend **77 passed** y `typecheck` OK; `build` no se re-ejecutó en esta vuelta por OOM local (sin cambios de UI desde la última ejecución correcta); `compileall`, `sh -n infra/postgres/migrate.sh` y diff-check OK. T011 sigue abierta hasta CI en `main` y revisión humana.

## Contexto y objetivo

La auditoría del 2026-10-19 identifica un patrón transversal: **mecanismos declarados que no están implementados** y que generan falsa confianza (§1). R06 y R12 son los dos casos que la auditoría deja a una decisión de producto («implementarlo o retirarlo y documentar el modelo real» / «implementar llenado `stage_rank` o documentar alcance»), ambos en P1.

El problema no es que falte una función, sino que el esquema y la firma de las APIs **prometen capacidades que ningún camino ejerce**, y que el avance entre fases ni siquiera es operable de forma manual. Esta spec cierra ambos frentes con el menor alcance que deja el sistema coherente.

**Estado verificado sobre el árbol de trabajo el 2026-10-20.** Las cifras de línea son evidencia; no son el diseño.

### R06 — evidencia

1. **El ámbito por torneo se acepta y se ignora.** `require_permission` recibe `tournament_id` en su firma (`backend/app/core/permissions.py:7-14`) y lo envía como parámetro vinculado (`permissions.py:47`), pero la consulta (`permissions.py:15-40`) **no lo referencia**: resuelve solo el rol de organización. `role_codes` y `match_id` sí se usan (`permissions.py:24-27` y `28-38`).
2. **Los llamadores creen que existe.** Pasan el torneo `tournaments/router.py:83-87`, `tournaments/router.py:3213-3218`, `matches/router.py:82-90`, `matches/router.py:795-800` y `matches/router.py:902-907`. El parámetro viaja y se descarta.
3. **`tournament_user_roles` existe y nadie la escribe ni la lee.** Tabla con FKs a organización, miembro, torneo y rol y unicidad por `(organization_user_id, tournament_id, role_id)` (`infra/postgres/init/01_schema.sql:150-163`); RLS `ENABLE` + `FORCE` (`init/01:1140,1170`; `migrations/011_security_invariants_and_team_codes.sql:7`), política tenant genérica (`init/01:1197-1224`) y grants completos (`init/01:1226-1233`). En el estado auditado **no había referencias en código de aplicación, seed ni frontend**; hoy solo las pruebas de la 019 la nombran para comprobar el retiro. No existe endpoint, pantalla ni seed que la pueble; por tanto, salvo SQL manual, está vacía en cualquier despliegue.
4. **El modelo real es RBAC por organización, con un ámbito menor por partido.** Roles y permisos viven en `roles`/`role_definitions` (`init/01:53-91`) y se asignan por organización (`organization_user_roles`, `init/01:73-83`). La única delegación real es por partido: `match_officials` (`init/01:479-492`) permite que un árbitro asignado cierre ese partido (`permissions.py:28-38`), con endpoints de alta, listado y baja (`matches/router.py:738-767,823-858,913`). La UI solo cambia roles de organización (`frontend/app/pages/workspace/members.vue:136-147`).
5. **Consecuencia.** Cualquier miembro con `MANAGE_TOURNAMENTS` (owner/administrator, `init/01:87-88`) gestiona **todos** los torneos de la organización. La documentación solo promete «Organizaciones con membresías y RBAC» (`README.md:158`) y no menciona roles por torneo, pero el esquema y la firma de los permisos sí lo insinúan.

### R12 — evidencia

1. **`stage_edges` es inalcanzable.** Declara `selector_type` con `top_n`, `match_winner`, `match_loser`, `best_ranked` y `manual`, más `selector_config` (`init/01:180-195`; CHECK en `187-189`). Ningún endpoint la crea: el único `INSERT` del repositorio es el clonado profundo de una versión existente (`tournaments/router.py:446-478`). No hay CRUD de aristas, ni UI, ni seed; salvo SQL manual, está vacía.
2. **`phase_slots` se escribe pero nunca se resuelve.** Declara `source_type` con `direct_team`, **`stage_rank`**, `match_result` y `manual`, más `source_reference` (`init/01:210-224`; CHECK en `217-219`). Se escribe como procedencia al generar la llave (`router.py:2033-2051` en eliminación directa; `router.py:2207-2220` en doble eliminación) **solo con `direct_team` y `match_result`**, se clona (`router.py:408-444`) y el seed la replica (`backend/scripts/seed_demo.py:719-752`). **Ningún camino la lee para llenar un lado de un partido.**
3. **Corrección de premisa:** `stage_rank` **no es una columna**; es uno de los valores admitidos por el CHECK de `phase_slots.source_type` (`init/01:217-219`). La auditoría lo menciona como si fuera columna y esta spec no lo trata como tal.
4. **El único avance real es dentro de la misma fase.** `advancement_links` (`init/01:745-757`) se consume al cerrar un partido (`backend/app/modules/advancement/service.py:12-49`, invocado desde `backend/app/modules/matches/service.py:597-601`): copia ganador/perdedor al partido destino de la **misma llave**. No existe consumidor entre fases.
5. **El avance manual tampoco es operable hoy.** `stage_teams` solo se inserta al **crear** un equipo (`router.py:960` y `1088`), al clonar (`router.py:497`) o en el seed (`seed_demo.py:559`). **No hay endpoint para asignar un equipo ya registrado a otra fase.** Un equipo queda en la fase con la que se creó; el requisito de que esté asignado a la fase para crear un partido (`router.py:3087-3109`; trigger `init/03_hardening.sql:169-213`) impide moverlo.
6. **La publicación congela la estructura.** Los triggers bloquean insertar, actualizar o borrar `stages`, `stage_edges`, `phase_slots` y `stage_teams` en versiones publicadas o archivadas (`init/01:889-945`), y en `matches` solo permiten pasar un lado de `NULL` a un equipo (`init/03_hardening.sql:217-287`). Por eso el avance manual se limita al borrador (Q4 = A).
7. **La UI no declara selectores ni avance.** Se pueden crear fases (`frontend/app/pages/workspace/tournaments/[id].vue:370,889-897`), pero no hay pantalla de aristas, ni de slots, ni de clasificación del Workspace, ni de «siguiente fase». La clasificación se consulta en el endpoint **público** (`router.py:3353-3385`); en el Workspace solo aparece como subproducto del sorteo Swiss (`router.py:2460-2480,2586`). La preparación de publicación solo cuenta fases, equipos y partidos (`router.py:3231-3260`).
8. **Tercera estructura declarada y muerta del mismo tema:** `tournament_versions.phase_config` (`init/01:127`) se crea siempre como `'{}'` y se clona (`router.py:178-179,306,316`); ningún camino la interpreta. **No se modifica**; se documenta como no soportada.
9. **Dependencia de compatibilidad descubierta.** La migración `011` aplica `ALTER TABLE ... FORCE ROW LEVEL SECURITY` **sin guardas** a ambas tablas (`011:7` y `011:9`), y los scripts de `init/` corren **antes** de las migraciones en un volumen limpio. Borrar su `CREATE TABLE` de `init/01` haría fallar la 011. Se resuelve en RF-010 sin editar la 011.

**Objetivo:** retirar el scoping por torneo y las estructuras de selector que no tienen consumidor, y hacer **operativo el avance manual** de equipos entre fases dentro del borrador, con API, UI mínima y pruebas, manteniendo RLS, la inmutabilidad publicada y la coherencia documental.

## Alcance

Incluye:

1. Retiro de `tournament_user_roles` y del parámetro de ámbito por torneo no aplicado, con sus políticas, grants y referencias.
2. Retiro de `stage_edges` y estrechamiento del CHECK de `phase_slots.source_type`; conservación de `phase_slots` como procedencia.
3. Migración nueva `019` de retiro, con pre-chequeo documentado y verificación en volumen limpio y ya migrado.
4. Migración `020` no destructiva, posterior a la 019, que concede solo `INSERT (id)` sobre `public.rosters` a `bracket_app` para el `id` pre-generado de la importación N-2; `init/01` incluye el mismo grant.
5. Endpoints de lectura, asignación y retirada de equipos de una fase en borrador, con validaciones, precedencia, idempotencia y concurrencia.
6. UI mínima en el panel de fases del Workspace: ver equipos de la fase, asignar y quitar.
7. Documentación del modelo real de autorización, del avance manual y de los runbooks de la 019 y la 020.
8. Pruebas unitarias con mocks y opt-in con PostgreSQL.

## No objetivos

- No se implementan roles por torneo ni una UI de delegación por torneo.
- No se implementa sembrado automático desde `standings`, ni resolución de `phase_slots`, ni selectores entre fases.
- No se cambia el formato de los torneos ni las reglas deportivas (desempates, puntuación, número de clasificados).
- No se relajan la inmutabilidad publicada ni los triggers; no hay excepción a la constitución.
- No se toca `phase_config`, el outbox, el tiempo real, la administración de plataforma ni las proyecciones públicas.

## Usuarios

- **Owner/administrator de organización:** gestiona torneos y ahora puede mover equipos entre fases antes de publicar.
- **Operator/referee:** conserva su acceso actual; no gana ni pierde ámbito por este cambio.
- **Equipo de mantenimiento y auditoría:** necesita que el esquema y la documentación describan lo que el sistema hace.
- **Público:** no cambia; no ve roles ni estructura interna.

## Roles y visibilidad

- **Público (sin sesión):** sin cambios. No ve roles, asignaciones ni estructura interna; las proyecciones públicas siguen sin documentos ni fechas de nacimiento.
- **Miembro de organización:** puede leer los equipos de una fase de su organización (RLS), pero no asignarlos ni quitarlos.
- **Owner/administrator:** puede asignar y quitar equipos en fases de versiones en borrador. Gestiona todos los torneos de la organización (modelo real documentado).
- **Operator/referee:** conserva el cierre de actas y su ámbito por partido (`match_officials`). No puede asignar equipos entre fases.
- **Administrador de plataforma:** no participa; no se añaden acciones en `/admin` ni se tocan `platform_admins` o `platform_audit_logs`.

## Historias de usuario

- **HU-1.** Como owner, quiero inscribir en la fase 2 a los equipos que ya están registrados en el torneo, para operar un torneo de varias fases sin duplicar equipos.
- **HU-2.** Como owner, quiero quitar de una fase a un equipo mal inscrito antes de generar el calendario, para corregir el borrador sin tocar la base de datos.
- **HU-3.** Como auditor, quiero que el esquema ya no declare roles por torneo ni selectores entre fases que nadie usa, para que la documentación no me engañe.
- **HU-4.** Como árbitro, quiero que mi acceso siga limitado a los partidos asignados y que retirar una tabla no amplíe mis permisos.
- **HU-5.** Como mantenedor, quiero que una instalación limpia y una ya migrada terminen con el mismo esquema, para no depender del orden de arranque.

## Definiciones

- **Avance manual:** asignar equipos registrados en el torneo a una fase, y quitarlos, siempre en una versión en borrador.
- **Procedencia de la llave:** registro histórico de cómo se generó cada lado de un partido (equipo directo o resultado de otro partido), sin resolución automática entre fases.
- **`stage_rank`:** valor del CHECK de `phase_slots.source_type` que insinúa clasificar por posición de la tabla; **no es una columna** y se retira.
- **Sembrado automático:** llenar la fase destino a partir de `standings`; queda fuera de alcance.
- **Inmutabilidad publicada:** principio §2.3 de la constitución: la estructura de una versión publicada no se modifica.
- **Borrador:** versión con `status = 'draft'`, única donde se permite cambiar la estructura.
- **Equipo registrado:** fila de `tournament_teams` con `status = 'registered'`; `pending`, `disqualified` y `withdrawn` no son asignables.

## Cambios de esquema y datos (migraciones 019 y 020)

1. **Pre-chequeo único, antes de cualquier `DROP` o reemplazo:** en la misma transacción, un bloque `DO` comprueba, con guardas `to_regclass`, que `tournament_user_roles` y `stage_edges` existen (si existen) con **0 filas**, y que `phase_slots.source_type` no tiene valores fuera de `direct_team`/`match_result`. Si cualquiera falla, **aborta con un mensaje y conteos por valor** (solo nombres de estructura y números) antes de tocar nada. La migración se ejecuta envuelta en `BEGIN`/`COMMIT` (el runner la aplica como una unidad); no deja estado a medias.
2. **`tournament_user_roles`:** se elimina con `DROP TABLE IF EXISTS` **después** del pre-chequeo. `DROP TABLE` retira políticas, grants, trigger e índices asociados. No se migran asignaciones porque no existen caminos que las creen.
3. **`stage_edges`:** se elimina con `DROP TABLE IF EXISTS` **después** del pre-chequeo. No se conserva ninguna copia porque ningún camino la escribe salvo el clonado de una versión que ya la tuviera.
4. **`phase_slots.source_type`:** se descubre el CHECK por catálogo (`pg_constraint` con `contype = 'c'` y `pg_get_constraintdef` sobre `source_type`). Si no existe **exactamente una** constraint coincidente, se aborta; se usa el nombre descubierto para `DROP CONSTRAINT IF EXISTS` y `ADD CONSTRAINT` con `direct_team`/`match_result`. **No se hace `UPDATE`**: reescribir la procedencia almacenada falsificaría el historial y no existe una regla determinista para mapear `stage_rank`/`manual`; el operador decide. `source_reference` y `phase_slots` se conservan.
5. **`matches.home_slot_id` / `away_slot_id`:** se conservan con sus FKs. No se tocan.
6. **Documentación del esquema:** `phase_slots` queda descrita como **procedencia de la llave**, no como motor de clasificación. `phase_config` se documenta como no soportada y no se modifica.
7. **`infra/postgres/init/`:** `init/01` conserva el `CREATE TABLE` y `ENABLE`/`FORCE ROW LEVEL SECURITY` de ambas tablas para que la 011 no falle en limpio; se retiran de `init/01` sus **políticas** (loop tenant), **grants** y el trigger `trg_protect_stage_edges`. `init/03` y la 011 conservan sus `FORCE`. La 019 las elimina. El estado intermedio tiene RLS activo, sin políticas ni grants, por lo que el rol de aplicación no accede.
8. **Clonado, generación y seed:** se ajustan para no leer ni escribir `stage_edges` y para no emitir valores retirados de `source_type`. `phase_slots` sigue clonándose y el seed sigue replicándolas como procedencia.
9. **Runbook:** la 019 se documenta en `README.md` y `AGENTS.md` con un pre-chequeo de solo conteos (ver abajo) y la secuencia de aplicación y reversión (solo *forward-fix* después de aplicada, como cualquier migración).
10. **SQLSTATE estable:** la 019 hace `CREATE OR REPLACE FUNCTION prevent_published_structure_mutation()` y sustituye sus dos `RAISE EXCEPTION` por `RAISE EXCEPTION ... USING ERRCODE = 'ZZ409'`, **conservando el texto** de los mensajes. `ZZ409` es de clase de usuario, no asignado por el estándar ni por PostgreSQL, así que no colisiona con códigos estándar. El valor es exacto y no depende del texto; no se usa el nombre de una constraint porque el trigger no expone una. Cualquier `ZZ409` que llegue a la API se traduce a **409**; un cambio de redacción no puede devolverlo a 500. El resto de errores de base conservan su manejo actual.
11. **Dependencias de catálogo:** antes de aplicar, la consulta de catálogo del runbook debe demostrar que ninguna función, vista, policy, trigger o **FK entrante** (distinta del propio trigger de `stage_edges`) referencia las tablas; después de la 019 no debe quedar ninguna referencia. La 019 no crea ni reemplaza funciones `SECURITY DEFINER` ni vistas.
12. **Sin rollback:** la 019 es destructiva y no tiene `down`. Después de aplicada se corrige solo con una migración nueva (*forward-fix*). El runbook exige copia de seguridad verificada (`pg_restore -l`) antes de aplicar y un smoke después.
13. **Reejecutabilidad:** `DROP ... IF EXISTS` y `DROP CONSTRAINT IF EXISTS` son solo salvaguardas. La migración se aplica **una sola vez** y `schema_migrations`/el checksum impiden reaplicarla; no se promete que un segundo `ADD CONSTRAINT` sea idempotente.

### Migración 020 (forward-fix de privilegios)

La **020** no es destructiva y se aplica **después** de la 019. No cambia datos, funciones ni políticas.

- **Qué hace:** `GRANT INSERT (id) ON public.rosters TO bracket_app`. Es un privilegio **de columna**, no de tabla; `has_table_privilege('bracket_app','public.rosters','INSERT')` sigue siendo `false`.
- **Por qué:** la importación masiva del N-2 sube la foto antes de la transacción y construye la clave del objeto con el `id` del roster, por lo que la aplicación pre-genera el `id`. El `INSERT INTO rosters (id, ...)` explícito fallaba porque `bracket_app` solo tenía grants por columnas y no `INSERT` de tabla. La 020 añade únicamente la columna `id`; no amplía el privilegio de tabla.
- **Volumen limpio:** `init/01` incluye el mismo `GRANT INSERT (id, ...) ON rosters` para que una instalación limpia termine con el mismo estado que una migrada.
- **Aplicación:** `MIGRATION_TARGET=020 $COMPOSE run --rm db-migrate`, después de la 019. No hay rollback necesario: el grant es aditivo y una corrección futura sería otra migración. La prueba de esquema es `test_player_catalog_schema.py::test_bracket_app_can_insert_a_pre_generated_roster_id_by_column`.

## Runbook de la migración 019

**Antes de aplicar**, con `api` y `worker` detenidos y una copia de seguridad verificada:

```sh
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.production.yml"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$HOME/backup-pre019.dump"
pg_restore -l "$HOME/backup-pre019.dump" > /dev/null && echo "backup verificable"
```

Ejecutar en la base (solo lectura, sin identificadores de personas) y adjuntar el resultado al cambio. Las guardas `to_regclass` + SQL dinámico permiten que una relación ausente cuente como 0:

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
SELECT 'relation' AS kind, n.nspname || '.' || c.relname AS object
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
UNION ALL
SELECT 'function', p.oid::regprocedure::text
FROM pg_proc p
WHERE p.prosrc ~ '(tournament_user_roles|stage_edges)'
UNION ALL
SELECT 'view', v.schemaname || '.' || v.viewname
FROM pg_views v
WHERE v.definition ~ '(tournament_user_roles|stage_edges)'
UNION ALL
SELECT 'policy', pol.polname
FROM pg_policy pol
JOIN pg_class c ON c.oid = pol.polrelid
WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
UNION ALL
SELECT 'trigger', t.tgname
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
UNION ALL
SELECT 'incoming_fk', con.conname
FROM pg_constraint con
WHERE con.contype = 'f'
  AND con.confrelid IN (
      SELECT c.oid FROM pg_class c
      WHERE c.relname IN ('tournament_user_roles', 'stage_edges')
  );
```

- Todos los conteos deben ser **0** para aplicar sin intervención.
- Si alguno es mayor que 0, la 019 falla cerrada; el operador decide antes de aplicarla (revisar el origen, corregir por SQL administrativo o abrir una migración específica). No se borran filas en silencio ni se reescribe `source_type`.
- La consulta de catálogo debe devolver solo la propia tabla (y, si aún existiera, su política o trigger) antes de la 019 y **nada** después. Si aparece una función, vista o FK entrante, se detiene la aplicación.
- La 019 se ejecuta en **una transacción** (`BEGIN`/`COMMIT`); el runner la aplica una sola vez y `schema_migrations`/el checksum impiden reaplicarla. `IF EXISTS` es solo salvaguarda, no una promesa de reejecutabilidad.
- **Después:** smoke de arranque de la API, `GET /docs`, una lectura pública de torneo y una operación de workspace; si falla, *forward-fix* con una migración nueva. No hay rollback.
- El pre-chequeo, la copia, la verificación con `pg_restore -l` y la secuencia se documentan como paso previo en `README.md` y `AGENTS.md`, junto con el comando de migración y la nota de que los scripts de `init/` no son migraciones.

## Runbook de la migración 020

Después de la 019 y con el código nuevo desplegado:

```sh
MIGRATION_TARGET=020 $COMPOSE run --rm db-migrate
```

- No requiere pre-chequeo de datos ni copia adicional: es un `GRANT` aditivo de columna y no modifica filas.
- Verificar `has_column_privilege('bracket_app','public.rosters','id','INSERT') = true` y `has_table_privilege('bracket_app','public.rosters','INSERT') = false`.
- Smoke: una importación de roster con foto en un borrador (pre-genera `id`) y una lectura del Workspace.
- Si falla, corregir con una migración nueva; no hay `down`.
- Se documenta en `README.md` y `AGENTS.md` junto al runbook de la 019.

## Protocolo de bloqueo (auditoría del código real)

**Hallazgo (estado previo a la implementación):** **ningún** sitio bloqueaba versión → fase. `update_version_rules` (`tournaments/router.py:658`), `publish` (`router.py:3205`) y `create_stage` (validación de versión en `router.py:773-791`) eran version-only; `_create_draft_version_record` bloqueaba torneo → versión de origen (`router.py:238,261`) sin fase; la generación y el sorteo bloqueaban solo partidos (`router.py:1674,2520,2541,2565`); el cierre bloqueaba el partido en `matches/service.py:225` y después escribía eventos/segmentos/jugadores, `standings` y recién entonces llamaba a `_advance_bracket` (`matches/service.py:84,160-161`); `StandingsService.recalculate` usaba un advisory lock por fase (`standings/service.py:17`) y escribía `standings` (`227,255`); `advancement` bloqueaba `GF2` (`advancement/service.py:66`). No había una inversión fase/versión que corregir: había que **añadir** el bloqueo de fase y versión en el orden correcto y **adelantar** el bloqueo de los partidos destino. La implementación ya aplica el protocolo descrito abajo.

**Orden único:** **fase → versión → partido(s) → segmentos → jugadores**. Ninguna ruta puede tomar versión antes que fase ni partido antes que fase/versión. Se aplica a:

1. `POST` y `DELETE` de equipos de una fase (RF-013, RF-016).
2. Creación manual de partido (`POST /tournaments/{id}/matches`): fase → versión antes de validar `stage_teams` e insertar.
3. Alta individual o masiva de equipos con `stage_id` (`POST /tournaments/{id}/teams` y `/teams/bulk`): fase → versión antes de insertar en `stage_teams`.
4. Generación y regeneración de calendario, sorteo Round Robin/grupos y sorteo/rondas Swiss (`/matches/generate`, `/matches/draw`): fase → versión antes de bloquear partidos; **todos los partidos se bloquean con `ORDER BY id`**, incluidas `_clear_stage_schedule` y las consultas de placeholders Swiss. No se usa `ORDER BY bracket_code`.
5. Cierre de acta y resolución administrativa: fase → versión → **conjunto completo de partidos** (origen y destino) en orden ascendente de `id`, **antes de escribir segmentos o jugadores**; después segmentos/jugadores, `standings` y `advancement`. `advancement` no vuelve a bloquear destinos ya bloqueados. `GF2` se pre-bloquea **siempre que el origen sea `GF1` y `GF2` exista**, aunque el reset no se active en ese cierre.
6. `StandingsService.recalculate`: adquiere el bloqueo de fase **antes** del `pg_advisory_xact_lock` (o elimina el advisory); el advisory nunca se toma antes que la fase, para no crear el ciclo advisory → fase frente a fase → advisory. Lo mismo si se invoca desde el cierre, donde la fase ya está bloqueada.
7. Alta y baja de oficiales (`POST/DELETE /matches/{id}/officials`): toman el bloqueo del partido con `lock_matches` antes de escribir. No cruzan el protocolo fase/versión porque no cambian estructura.
8. Publicación: solo versión; si en el futuro necesita fases, las bloquea **antes** de la versión.

**Excepciones version-only justificadas:** `update_version_rules`, `create_stage`, `publish` y el clonado (`_create_draft_version_record`, que además bloquea el torneo) no tienen una fase preexistente que bloquear o solo modifican la versión; ninguna toma versión después de una fase. `create_stage` bloquea la versión antes de insertar la fase. Cualquier ruta nueva que necesite ambos bloqueos usará fase → versión.

Las lecturas (`GET` de equipos, listados, proyecciones) no toman estos locks. La creación de partidos y la generación toman el lock de fase antes de comprobar `stage_teams`, de modo que un `DELETE` concurrente no puede borrar entre la comprobación y la escritura. El cierre y la asignación no coexisten sobre la misma versión (publicada vs borrador), pero el protocolo se mantiene para que el orden sea único. El bloqueo fase → versión → partido se aplica al cierre y a la resolución administrativa; las lecturas, segmentos y alineaciones conservan su bloqueo de partido; los oficiales toman explícitamente `lock_matches` y no cruzan el protocolo fase/versión.

## Requisitos funcionales

### Transversales

- **RF-001.** CUANDO se implemente esta spec, EL SISTEMA y su documentación (`README.md`, `AGENTS.md`) deberán describir el modelo real de autorización (RBAC por organización + `match_officials` por partido) y el avance manual entre fases, sin declarar roles por torneo ni sembrado automático.
- **RF-002.** SI al cerrar el cambio queda una estructura, parámetro, valor de CHECK o pantalla sin consumidor relacionada con R06 o R12, ENTONCES EL SISTEMA deberá cumplir esta **lista cerrada**: (a) **eliminadas**: `tournament_user_roles`, `stage_edges` y los valores `stage_rank`/`manual` de `phase_slots.source_type`; (b) **conservadas y documentadas como procedencia almacenada no resuelta**: `phase_slots` (con `source_reference` y los valores `direct_team`/`match_result`) y `matches.home_slot_id`/`away_slot_id`; (c) **documentada como no soportada**: `tournament_versions.phase_config`; (d) **eliminado**: el parámetro de ámbito por torneo de la comprobación de permisos. La verificación compara el esquema final y la documentación contra esta lista; no queda ningún otro mecanismo de R06/R12 declarado como disponible.
- **RF-003.** CUANDO se apliquen las migraciones `019` y `020`, EL SISTEMA deberá hacerlo como **migraciones nuevas numeradas**, envueltas en una transacción, con `DROP ... IF EXISTS`/`DROP CONSTRAINT IF EXISTS` solo como salvaguardas y sin prometer reejecutabilidad: se aplican una vez y `schema_migrations`/el checksum impiden repetirlas. La 019 es destructiva y sin `down`; la 020 es un *forward-fix* no destructivo posterior que concede solo `INSERT (id)` sobre `public.rosters`. No se editan migraciones aplicadas ni se reescriben checksums; después de la 019 solo cabe *forward-fix*. `sh -n infra/postgres/migrate.sh` y el runner de `MIGRATION_TARGET=019`/`020` deberán seguir pasando; el runbook exigirá copia verificada con `pg_restore -l` y smoke posterior.
- **RF-004.** SI la migración `019` encuentra filas en `tournament_user_roles` o `stage_edges`, o valores de `phase_slots.source_type` fuera de `direct_team`/`match_result`, ENTONCES EL SISTEMA deberá **abortar antes de cualquier `DROP` o reemplazo del CHECK**, con un mensaje claro y solo el nombre de la estructura y el conteo (por valor en `source_type`), sin identificadores de miembros ni datos personales. No se reescriben filas con `UPDATE`.
- **RF-005.** MIENTRAS exista cualquier tabla propiedad de una organización, EL SISTEMA deberá mantener RLS `ENABLE` + `FORCE` y política por `organization_id` con verificación de membresía, salvo las dos tablas retiradas, que hasta la 019 conservan `ENABLE`/`FORCE` y **no tienen políticas ni grants** (deny por defecto); cada transacción deberá fijar el contexto antes de consultar o escribir, y ninguna operación podrá leer ni escribir datos de otra organización.
- **RF-006.** EL SISTEMA deberá cubrir cada RF aplicable con pruebas unitarias y, cuando toque base de datos, con pruebas de integración opt-in (`RUN_DATABASE_TESTS=1`); las que no puedan ejecutarse se declararán como no ejecutadas.

### R06 — retiro del scoping por torneo

- **RF-007.** CUANDO se aplique la migración `019`, EL SISTEMA deberá dejar de declarar `tournament_user_roles` y la comprobación de permisos no deberá aceptar un ámbito por torneo: resolverá únicamente por rol de organización y, cuando corresponda, por asignación en `match_officials`.
- **RF-008.** CUANDO se retire la tabla, EL SISTEMA deberá ajustar exactamente estas referencias: en `init/01` se conservan `CREATE TABLE` y `ENABLE`/`FORCE` y se retiran políticas, grants y el trigger `trg_protect_stage_edges`; `init/03` conserva su `FORCE` hasta la 019; `migrations/011` conserva su `FORCE` y no se edita; se ajusta el clonado de `router.py:446-478` para `stage_edges`; y se registra el cierre de R06/R12 en `MEMORY.md` citando la auditoría como evidencia histórica (sin reescribirla). **No existen referencias en código de aplicación, seed ni verificadores**; las pruebas de la 019 (`test_migration_019.py`, `migration_helpers.py`) son la excepción justificada porque nombran las tablas para verificar el retiro. Además, al quitar `tournament_id` de `require_permission` se actualizarán todos sus llamadores: `tournaments/router.py:85` y `3213-3218`; `matches/router.py:82-90`, `795-800` y `902-907`; `matches/service.py:37-42` (posicional); `permissions.py:64-71` (`require_administrative_resolution`, que también pierde el parámetro y ajusta su llamada en `matches/service.py:29-34`); y los dobles de prueba `test_photo_resolution.py:1552,1779` y `test_swiss_transaction.py:554`. `tournaments/router.py:156`, `invitations/router.py:55` y `test_invitations.py:206,221,236` no pasan ámbito y no cambian. La documentación indicará que la delegación es por organización y que el único ámbito menor es la asignación por partido.
- **RF-009.** CUANDO un miembro con `MANAGE_TOURNAMENTS` gestione un torneo, EL SISTEMA deberá seguir permitiéndolo con independencia del torneo. En una versión en borrador, sin ese permiso: **403**. Torneo o fase de otra organización o inexistentes: **404**. Equipo no registrado en el torneo, incluido el oculto por RLS de otra organización: **409**. El comportamiento observable de autorización no cambia respecto de hoy; en una versión publicada/archivada la precedencia del 409 de inmutabilidad se rige por RF-020.
- **RF-010.** SI un volumen limpio ejecuta `init/` seguido de las migraciones, ENTONCES EL SISTEMA deberá terminar con el mismo esquema que un volumen ya migrado: `init/01` conserva el `CREATE TABLE` y `ENABLE`/`FORCE` de ambas estructuras para que la `011` no falle, retira solo sus políticas y grants, y la `019` las elimina; `init/03` y la `011` conservan sus `FORCE`; `init/01` incluye además el `GRANT INSERT (id)` sobre `public.rosters` que replica la 020.

### R12 — retiro de selectores y avance manual

- **RF-011.** CUANDO se aplique la migración `019`, EL SISTEMA deberá eliminar `stage_edges`, estrechar el CHECK de `phase_slots.source_type` a `direct_team`/`match_result` (descubierto por catálogo; aborta si no hay exactamente una constraint coincidente) y ajustar el clonado (`router.py:446-478`), la generación, el seed y las pruebas para no leer ni escribir las estructuras o valores retirados; el calendario y la proyección pública deberán ser idénticos a los actuales.
- **RF-012.** EL SISTEMA deberá conservar `phase_slots` y `source_reference` como **procedencia de la llave**: se escriben al generar y se clonan, pero no se resuelven automáticamente ni se usan para llenar partidos entre fases. `matches.home_slot_id`/`away_slot_id` se conservan.
- **RF-013.** CUANDO un usuario con `MANAGE_TOURNAMENTS` envíe `POST /api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams` con `{"team_ids": ["<uuid>", ...]}`, EL SISTEMA deberá asignar esos equipos a la fase y responder con `{"stage_id", "version_id", "team_ids", "assigned", "already_assigned"}`, donde `assigned` y `already_assigned` son **dos arrays de UUID** (nunca conteos, sin duplicados). Si el lote tiene al menos un equipo nuevo, responde **201**; si **todos** ya estaban asignados (`assigned = []`, sin escrituras), responde **200**; repetir el mismo lote pasa de 201 a 200. La operación es **atómica todo-o-nada**: si un solo `team_id` no está `registered`, no se inserta ninguno y la respuesta es **409**; las filas preexistentes no se tocan. `team_ids` es la lista de entrada validada. El payload admite de **1 a 64** equipos (límite de payload coherente con `MAX_SWISS_TEAMS`, no un tope de formato) y **no se deduplica en silencio**. Los duplicados dentro de `team_ids` se rechazan con **422** en la validación de esquema, antes del handler y sin escrituras.
- **RF-014.** EL SISTEMA deberá validar el payload con el esquema de entrada **antes del handler** (lista vacía, más de 64 elementos, UUID inválido o `team_ids` duplicados → **422**, sin comprobaciones de recurso ni escrituras). Para una petición bien formada, el orden efectivo es: resolver torneo y fase (**404** si no existen o son de otra organización; es el único paso que permite conocer la versión) → versión de la fase en `draft` (**409** si está publicada o archivada) → permiso `MANAGE_TOURNAMENTS` (**403**) → validación **atómica** de que todos los equipos tienen `tournament_teams.status = 'registered'` (**409** si uno no lo está) → escritura. El 409 de versión precede al permiso, a los equipos y a la idempotencia; el 404 de recurso es necesariamente anterior porque sin fase no hay versión que evaluar.
- **RF-015.** CUANDO un equipo ya esté asignado a la fase, EL SISTEMA deberá tratarlo como idempotente: no duplicará filas, lo incluirá en el array `already_assigned` y, si todo el lote ya estaba asignado, responderá **200** con `assigned = []`. El bloqueo de la fase y de la versión (RF-021) serializa las peticiones simultáneas; la segunda verá las filas de la primera.
- **RF-016.** CUANDO un usuario envíe `DELETE /api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams/{team_id}`, EL SISTEMA deberá quitar la asignación y responder **204**. Precedencia obligatoria: torneo o fase inexistentes/de otra organización **404** (permite conocer la versión); versión publicada o archivada **409** (aunque el equipo no estuviera asignado); permiso `MANAGE_TOURNAMENTS` **403**; equipo no registrado en el torneo **409**; partido de esa fase que referencie al equipo **409**; fila de `standings` de ese equipo en esa fase **409** aunque no haya partidos (Q6); si el equipo está registrado y no estaba asignado, **204** idempotente. Si existieran varias filas `stage_teams` del mismo equipo en la fase (grupos distintos, dato legado), se eliminan **todas** y se responde 204; no se borran partidos, grupos, `phase_slots`, resultados ni filas de `standings`.
- **RF-017.** CUANDO se asigne o quite un equipo, EL SISTEMA deberá dejar intactos el calendario, los grupos, `phase_slots` y los partidos existentes; no reagrupará equipos automáticamente. La regeneración del calendario y la asignación de grupos siguen siendo operaciones explícitas del usuario.
- **RF-018.** CUANDO un miembro de la organización solicite `GET /api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams`, EL SISTEMA deberá responder **200** con `{"stage_id", "version_id", "assigned": [{"team_id", "name", "short_code"}], "unassigned": [...]}`. `assigned` son las filas de `stage_teams` de **esa fase y versión**, **deduplicadas por `team_id`** si existieran varias filas del mismo equipo en grupos distintos; `unassigned` son los equipos del torneo con `status = 'registered'` que no están asignados a esa fase. La consulta **exige el filtro por la versión de la fase** (derivada de `stage_id`, que pertenece a una sola versión) y **no mezcla asignaciones de otras versiones ni fases**; torneo o fase inexistente → **404**. Es una lectura de organización (RLS), no requiere `MANAGE_TOURNAMENTS`.
- **RF-019.** CUANDO se use la UI del Workspace, el panel de la fase seleccionada deberá mostrar los equipos asignados, permitir seleccionar varios equipos **registrados** no asignados y asignarlos, y permitir quitar uno; los controles de asignar y quitar se **renderizan deshabilitados**, no se ocultan, sin `MANAGE_TOURNAMENTS` o si la versión no está en borrador, los errores se mostrarán en línea con `role="alert"` y textos traducidos, y tras un éxito se recargará la configuración sin recargar la página. La lista se obtiene de RF-018 (fuente única), la UI avisará de que el calendario **no se regenera automáticamente** y toda llamada usará `useApi.ts`.
- **RF-020.** SI una petición **bien formada** de `POST` o `DELETE` apunta a una versión publicada o archivada, ENTONCES EL SISTEMA deberá responder **409 antes de resolver la idempotencia** y sin ninguna escritura, aunque el equipo ya estuviera asignado (POST) o no estuviera asignado (DELETE). Los payloads que no pasan el esquema de entrada conservan el **422**; los duplicados internos se rigen por RF-014. No se modifica ningún trigger ni se relaja la inmutabilidad publicada.
- **RF-021.** CUANDO se procese un `POST` o un `DELETE`, EL SISTEMA deberá bloquear **fase → versión → partido(s) → segmentos → jugadores**, en ese orden (`FOR UPDATE` en fase y `FOR UPDATE`/`FOR SHARE` en versión), y releer el estado de la versión bajo el bloqueo. Las rutas de creación de partido, alta/bulk de equipos con `stage_id`, generación/sorteo, cierre, `standings` y `advancement` deberán adoptar el mismo protocolo (sección «Protocolo de bloqueo»). **Todas las consultas de partidos que se bloquean usan `ORDER BY id`**, incluidas `_clear_stage_schedule` y los placeholders Swiss; no se usa `ORDER BY bracket_code`. El cierre pre-bloqueará el **conjunto completo de partidos** (origen y destinos) en orden ascendente de `id` **antes** de escribir segmentos o jugadores; `GF2` se incluye siempre que el origen sea `GF1` y `GF2` exista, aunque no se active. El alta/baja de oficiales toma el bloqueo del partido con `lock_matches`. `create_stage`, `update_version_rules`, el clonado y `publish` son las únicas excepciones version-only justificadas. Si la versión dejó de ser `draft`, o si el trigger de inmutabilidad lanza **`ZZ409`**, la respuesta será **409**, nunca 500; el mapeo se hace por SQLSTATE, no por el texto del mensaje. Dos asignaciones simultáneas, una asignación concurrente con una publicación y un `DELETE` concurrente con la creación de un partido no pueden dejar estado parcial, duplicados ni escrituras huérfanas.
- **RF-022.** EL SISTEMA deberá documentar en `README.md` y `AGENTS.md` que el avance es **manual**, que el sembrado automático (`stage_rank`) no está soportado, y los runbooks de la 019 (copia verificada con `pg_restore -l`, pre-chequeo con `to_regclass`, catálogo con FKs entrantes, aplicación transaccional, smoke y *forward-fix*) y de la 020 (`MIGRATION_TARGET=020`, grant de columna `INSERT (id)` y verificación de que no hay `INSERT` de tabla).

## Requisitos no funcionales

- **RNF-001.** No se añaden dependencias ni variables de entorno; si apareciera una necesidad de configuración nueva, se detiene y se pregunta.
- **RNF-002.** La migración `019` debe funcionar sobre un volumen limpio y sobre uno ya migrado, conservar checksums y `MIGRATION_TARGET`, y no dejar el esquema intermedio accesible al rol de aplicación.
- **RNF-003.** El retiro no altera el contrato de las rutas públicas ni la proyección de llaves y partidos. **No se midió throughput ni latencia**: la serialización del cierre por fase (`lock_stage_and_version`) es una garantía de corrección y la afirmación de no degradación es un objetivo no verificado.
- **RNF-004.** La UI debe mantener paridad de claves i18n es/en y pasar `pnpm test`, `pnpm run typecheck` y `pnpm run build`.
- **RNF-005.** El único tope nuevo es el del payload (64 equipos por petición, RF-013); los límites de formato siguen aplicándose al generar el calendario (Swiss 64; llave 512). Asignar por encima de un tope de formato no corrompe datos, pero la generación fallará con su error actual.
- **RNF-006.** Toda la documentación afectada (`README.md`, `AGENTS.md`) se actualiza en el mismo cambio que el comportamiento (constitución §4).

## Datos personales y privacidad

No aplica. R06 y R12 no tratan datos de jugadores ni documentos, no cambian proyecciones públicas y no alteran `photo_url` ni el consentimiento. La asignación de equipos guarda identificadores internos de equipo y membresía; nunca se expone en rutas públicas. El pre-chequeo y los errores de la migración reportan solo conteos, sin identificadores de miembros ni datos personales.

## Casos límite

1. **La migración 019 encuentra filas** en `tournament_user_roles` o `stage_edges`: falla cerrada con el conteo; no borra en silencio (RF-004).
2. **La migración 019 encuentra `source_type` con `stage_rank` o `manual`:** falla cerrada con el conteo por valor; el operador decide antes de aplicarla.
3. **Volumen limpio:** `init/` crea las estructuras retiradas con RLS y sin políticas/grants, la 011 las fuerza y la 019 las elimina; el esquema final es idéntico al de un volumen ya migrado (RF-010).
4. **Volumen ya migrado:** la 019 se aplica una sola vez y el checksum la protege de ediciones posteriores.
5. **Seed de desarrollo:** no vuelve a escribir `stage_edges` ni valores retirados y sigue creando slots como procedencia (RF-011, RF-012).
6. **Clonado de una versión anterior:** si la versión origen tuviera slots, se clonan; las aristas ya no existen y el clonado no las busca.
7. **Equipo de otra organización o no registrado:** al asignar o quitar responde **409** y no escribe; el torneo o la fase de otra organización responden **404**.
8. **Equipo con `status` distinto de `registered`** (`pending`, `disqualified`, `withdrawn`): 409 al asignar; la UI no lo ofrece (RF-014, RF-019).
9. **Asignación con un `team_id` que ya está en la fase:** `already_assigned` incluye su UUID; si todo el lote ya estaba asignado, 200 con `assigned = []`, sin duplicar.
10. **Payload mal formado** (vacío, más de 64, UUID inválido o `team_ids` duplicados): 422 en la validación de esquema, antes del handler y sin escrituras (RF-013, RF-014).
11. **Dos asignaciones simultáneas:** el bloqueo de fase y versión serializa; la segunda no duplica (RF-015, RF-021).
12. **Asignación concurrente con la publicación:** si la publicación gana, el POST responde 409 y no escribe; si la asignación gana, queda confirmada antes de publicar. Nunca 500 ni estado parcial (RF-021).
13. **Asignar o quitar en una versión publicada:** 409 y cero escrituras; también si el equipo ya estaba asignado (POST) o no lo estaba (DELETE) (RF-020).
14. **Quitar un equipo con partidos en esa fase:** 409 y cero escrituras; el usuario debe eliminar o regenerar el calendario primero.
15. **Quitar un equipo con `standings` y sin partidos:** 409; la clasificación debe resolverse primero (Q6, RF-016). No se borran filas de `standings` automáticamente.
16. **Quitar un equipo registrado, no asignado y sin partidos ni `standings` en la fase:** 204 idempotente, salvo que la versión no sea borrador (409).
17. **Fase con grupos:** la asignación no coloca al equipo en un grupo; el sorteo/regeneración lo distribuye. Un equipo recién asignado no aparece en el calendario hasta regenerarlo (RF-017).
18. **Equipo asignado a dos fases distintas:** permitido; es el caso normal del avance manual.
19. **Lectura de equipos tras clonar una versión:** el `GET` de una fase de la versión nueva no muestra asignaciones de la versión anterior; solo las de su propio `stage_id` (RF-018).
20. **Miembro desactivado:** pierde el permiso en la siguiente petición; no se resucitan accesos.
21. **Cliente antiguo:** ninguna ruta pública cambia; el retiro del parámetro de ámbito no altera contratos HTTP.
22. **`phase_config` con contenido manual:** no se toca; se documenta como no soportada.
23. **Lote mixto (nuevos + ya asignados):** **201** con `assigned` (UUID nuevos) y `already_assigned` (UUID preexistentes); no hay escritura parcial. Repetir el mismo lote responde **200** con `assigned = []` (RF-013).
24. **Lote con un equipo `pending`, `disqualified` o `withdrawn`:** 409 y **ningún** equipo del lote queda asignado, incluidos los que sí eran válidos (RF-013, RF-014).
25. **`DELETE` concurrente con `POST /tournaments/{id}/matches`:** ambos toman el lock de fase; si el partido se crea primero, el `DELETE` ve el partido y responde 409; si el `DELETE` gana, la creación no encuentra el equipo y responde 409. Nunca queda un partido con un equipo no asignado (RF-021).
26. **`DELETE` concurrente con la escritura de `standings`:** ambos toman el lock de fase; el cierre solo ocurre en versión publicada y el `DELETE` en borrador, pero el orden de bloqueo se verifica con mocks y la guarda de `standings` responde 409 si la fila existe (RF-016, RF-021).
27. **El trigger de inmutabilidad lanza `ZZ409` con un texto distinto:** la API responde 409; el mapeo no depende del mensaje (RF-021).
28. **Publicación con un equipo ya asignado en la misma fase:** el `POST` o `DELETE` responde 409, no 200/201/204, porque la versión manda sobre la idempotencia (RF-020).
29. **Equipo con varias filas `stage_teams` en la fase (grupos distintos):** el `GET` lo muestra una sola vez (deduplicado por `team_id`), el `POST` lo considera `already_assigned` y el `DELETE` elimina todas sus filas y responde 204 (RF-016, RF-018).

## Riesgos y mitigaciones

- **Retirar una capacidad futura (roles por torneo).** Mitigación: la retirada es append-only y reversible con otra migración; se documenta el motivo y la condición para reintroducirla.
- **Datos inesperados en producción.** No es verificable desde el repositorio. Mitigación: pre-chequeo de conteos en el runbook y 019 falla cerrada; el operador decide antes de aplicarla.
- **Dependencia de la migración 011.** Borrar el `CREATE TABLE` de `init/01` rompería un volumen limpio. Mitigación: RF-010 conserva solo el `CREATE TABLE` y los flags RLS hasta la 019; sin políticas ni grants.
- **Carrera entre asignación y publicación.** Mitigación: protocolo fase → versión → partido(s), relectura de estado y `ZZ409` mapeado a 409 (RF-021); pruebas de concurrencia obligatorias.
- **Deadlock por órdenes distintos.** Mitigación: auditoría del código real y orden único fase → versión → partido(s) → segmentos → jugadores; ninguna ruta bloquea versión antes que fase ni partido antes que fase/versión (RF-021).
- **Ciclo advisory → fase frente a fase → advisory en standings.** Mitigación: la fase se bloquea antes del `pg_advisory_xact_lock`, o el advisory se elimina (RF-021).
- **Bloqueo tardío de los destinos del cierre.** Mitigación: el cierre pre-bloquea el conjunto completo (origen y destinos, incluida `GF2`) por `id` antes de escribir segmentos/jugadores (RF-021).
- **Carrera entre el `DELETE` y la creación de partidos o la escritura de `standings`.** Mitigación: ambas rutas toman el lock de fase antes de comprobar/escribir; prueba real `DELETE` vs creación y prueba de orden con mocks para `standings`.
- **Migración destructiva sin rollback.** Mitigación: copia verificada, pre-chequeo, catálogo de dependencias y smoke; después de aplicar, solo *forward-fix* (RF-003, RF-022).
- **Excepción del trigger devuelta como 500.** Mitigación: SQLSTATE estable `ZZ409` creado por la 019 y mapeo por código, con prueba que cambia el texto.
- **Inconsistencia al asignar equipos con un calendario ya generado.** La asignación no regenera partidos. Mitigación: se documenta y la UI lo avisa; no se corrompe nada.
- **Duplicados por el `UNIQUE (stage_id, group_id, team_id)` con `group_id` nulo.** PostgreSQL trata los nulos como distintos. Mitigación: bloqueo de la fase y de la versión + comprobación explícita de existencia (RF-015, RF-021).
- **Quitar equipos con partidos o con clasificación.** Mitigación: guardas 409 que no borran resultados ni `standings`; el operador debe resolver la clasificación o el calendario primero (RF-016).
- **Equipo con `standings` sin mecanismo de limpieza en esta spec.** La eliminación queda bloqueada hasta que la clasificación se resuelva por el operador; se documenta como limitación y no se amplía el alcance con un endpoint de limpieza.
- **Confusión entre avance manual y sembrado automático.** Mitigación: RF-022 y documentación explícita; `stage_rank` desaparece del CHECK.
- **Regresión en generación/clonado/público al retirar aristas y valores.** Mitigación: pruebas existentes de scheduling y clonado, más pruebas del esquema final y de la proyección pública.

## Fuera de alcance

- **Sembrado automático** desde `standings` (`stage_rank`), resolución de `phase_slots`, CRUD de aristas y cualquier motor de clasificación entre fases.
- **Roles por torneo**, asignación de roles por torneo, UI de delegación y auditoría asociada.
- **R09/R10** (sustituciones, transferencias, `roster_lock_matchday`; constantes de partido) y **R11** (ciclo de vida `live`/`suspended`, eventos en vivo, transiciones del torneo).
- **R18-R32** y cualquier hallazgo distinto de R06 y R12.
- **R13/R14** y cambios en outbox, Redis, Socket.IO o deduplicación (spec 004).
- Reglas deportivas nuevas: desempates, puntuación, formatos, número de clasificados o mejores terceros.
- Un endpoint o flujo para limpiar `standings`; la guarda 409 solo exige resolver la clasificación fuera de este alcance.
- Rediseñar el Workspace más allá del panel mínimo de equipos por fase.
- Cambiar `phase_config`, el modelo de acceso público, la administración de plataforma o `platform_audit_logs`.
- Relajar la inmutabilidad publicada o editar triggers.
- Añadir dependencias, cambiar versiones de referencia, Compose o `.env.example`.

## Verificación de constitución (para esta spec)

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por RLS | Sí | Las tablas conservadas mantienen RLS `ENABLE`/`FORCE` y política por organización; las dos retiradas conservan `ENABLE`/`FORCE` **sin políticas ni grants** hasta la 019 (deny por defecto) y luego se eliminan; cada transacción fija contexto (RF-005, RF-010). |
| §2.2 Rol sin `BYPASSRLS` | Sí | No se cambia el rol de base de datos ni se añaden funciones `SECURITY DEFINER` que lo eludan. |
| §2.3 Lo publicado es inmutable | Sí | El avance manual solo opera en borrador; publicadas/archivadas responden 409 incluso en no-ops; la carrera se resuelve con el protocolo de bloqueo y `ZZ409` mapeado a 409 (Q4 = A, RF-020, RF-021). |
| §2.4 Migraciones append-only | Sí | Migraciones `019` (retiro) y `020` (*forward-fix* de privilegio), sin editar aplicadas; `IF EXISTS` salvaguarda; sin `down` (RF-003). La dependencia de la 011 se resuelve sin editarla (RF-010). |
| §2.5 Proyección pública mínima | Sí | No se añaden campos públicos; el calendario y la proyección no cambian (RF-011). |
| §2.6 Sin secretos por defecto | No aplica | No hay variables ni secretos nuevos. |
| §2.7 Administración global separada y auditada | No aplica | No se toca `/admin` ni `platform_audit_logs`. |
| §2.8 Nada sin verificación | Sí | Criterios de finalización con todos los jobs de CI y declaración de lo no ejecutado (RF-006). |
| §3.1 RLS y migraciones | Sí | `set_rls_context` en cada transacción; migración con checksum, pre-chequeo y prueba en volumen limpio y migrado (RNF-002). |
| §3.2 Backend y configuración JSON | Sí | Las reglas deportivas siguen en configuración; no se introducen constantes nuevas. |
| §3.3 Frontend y `useApi.ts` | Sí | La UI mínima usa `useApi.ts` y las rutas del Workspace con sesión y organización activa (RF-019). |
| §3.4 Seguridad y configuración | Sí | Sin defaults nuevos; sin PII en logs, pre-chequeo ni reporte de la migración. |
| §3.5 Infraestructura y CI | Sí | No se tocan versiones de referencia ni Compose; los jobs `infrastructure` y `security` se ejecutan igualmente (ver criterios). |
| §4 Criterios de cambio | Sí | Jobs `backend` y `frontend`, migraciones con runner, documentación actualizada y revisión humana distinta del autor. |

## Pruebas previstas y qué no se cubre

- **Unitarias con mocks (sin base de datos):** validación de esquema (vacío, más de 64, UUID inválido, duplicados → 422) antes del handler; orden de validaciones y códigos (404 → 409 versión → 403 permiso → 409 equipos); atomicidad del lote (un equipo no `registered` → 409 y cero escrituras); `assigned`/`already_assigned` como arrays de UUID y transición **201 → 200** al repetir el lote; versión publicada con equipo ya asignado → 409 (no 200/201); guardas de borrado por partidos y por `standings`; múltiples filas `stage_teams` (GET deduplica, DELETE borra todas); mapeo de `ZZ409` a 409 con **texto distinto**; orden de sentencias de bloqueo con un doble de sesión para `POST/DELETE` de equipos, `POST /teams`, `/teams/bulk`, `POST /matches`, generación/sorteo, cierre, oficiales y `standings` (fase antes que versión; versión antes que partidos; fase antes del advisory; todos los partidos con `ORDER BY id`; origen/destinos y `GF2` en orden de `id`); botones de la UI renderizados deshabilitados; y que `require_permission` ya no acepte `tournament_id`.
- **Integración opt-in (`RUN_DATABASE_TESTS=1`, `DATABASE_ADMIN_URL`):** **42 passed** (`player_catalog_isolation` + `schema` + `swiss_transaction`, incluida la prueba de columna de la 020) y **23 passed** (`concurrency_006` + `migration_019`). El bloque de 23 incluye: migración limpia y migrada; abortos por filas y por `source_type`; CHECK final; `ZZ409` en `pg_get_functiondef` y por API; cross-tenant en asignación y GET; dos POST simultáneos; **dos DELETE simultáneos**; guarda de `standings` sin partidos; 409 directo en publicada con el equipo **asignado y no asignado**; `GET` tras clonar sin mezclar versiones; y permisos **owner/administrator/operator/referee**. También cubren `ZZ409` real al insertar en versión publicada, borrado bloqueado con partidos, POST/DELETE concurrentes con publicación, DELETE concurrente con creación de partido y clonado/proyección pública sin cambios.
- **Evidencia local de la vuelta 1:** backend **469 passed / 132 skipped**; opt-in **42 passed** (`player_catalog_isolation` + `schema` + `swiss_transaction`) y **23 passed** (`concurrency_006` + `migration_019`); frontend **77 passed** y `typecheck` OK; `build` no se re-ejecutó en esta vuelta por OOM local (sin cambios de UI desde la última ejecución correcta); `compileall`, `sh -n infra/postgres/migrate.sh` y diff-check OK. El runner se ejecutó en el puerto 55432 por credenciales del PostgreSQL local. T011 sigue sin marcar.
- **Frontend:** paridad i18n es/en, `pnpm test`, `pnpm run typecheck` y `pnpm run build`. No hay suite de componentes; la UI se valida por tipos, build y prueba manual del flujo.
- **No se cubre:** E2E de navegador; **rendimiento medido (no se midió throughput ni latencia)**; datos de producción (por eso el pre-chequeo y el fallo cerrado); sembrado automático (fuera de alcance); limpieza de `standings` (fuera de alcance); reglas de desempate.

## Criterios de finalización

1. R06 retirado: `tournament_user_roles` ya no existe, la comprobación de permisos no acepta ámbito por torneo y el modelo real está documentado (RF-007 a RF-010).
2. R12 acotado: `stage_edges` eliminada, CHECK estrechado con aborto por conteos, `phase_slots` conservadas como procedencia y clonado/generación/seed ajustados; los tres pre-chequeos corren antes del primer `DROP` y la 019 es transaccional (RF-011, RF-012).
3. Migración `020` aplicada después de la 019: `bracket_app` tiene `INSERT (id)` de columna sobre `public.rosters`, no `INSERT` de tabla; `init/01` incluye el mismo grant; el runner pasa con `MIGRATION_TARGET=020` (RF-003, RF-010).
4. Avance manual operativo: `GET`, `POST` y `DELETE` con contrato atómico, precedencia, arrays de UUID, 201 con altas / 200 solo si todo estaba asignado, idempotencia y concurrencia; UI mínima con errores y recarga (RF-013 a RF-021).
5. Inmutabilidad publicada y RLS intactas; ninguna escritura cross-tenant; publicadas responden 409 incluso en no-ops; `ZZ409` mapeado por SQLSTATE (RF-005, RF-020, RF-021).
6. Lista cerrada de RF-002 cumplida y documentación sin promesas de `stage_rank`, selectores o roles por torneo (RF-001, RF-002, RF-022).
7. `require_permission` sin `tournament_id`: se ejecuta `grep -rn -A8 "require_permission(" backend/app backend/tests --include='*.py'` y se confirma que ningún llamador pasa el ámbito; además `cd backend && python -c "import inspect; from app.core.permissions import require_permission; assert 'tournament_id' not in inspect.signature(require_permission).parameters"`.
8. Comandos ejecutados y reportados (evidencia local de la vuelta 1 abajo):
   - **Backend:** `cd backend && pytest -q`; `cd backend && python -m compileall -q app`.
   - **Migraciones:** `sh -n infra/postgres/migrate.sh`; runner con PostgreSQL local, según `AGENTS.md`:
     `docker run --rm --network host -v "$PWD/infra:/infra:ro" -e PGHOST=127.0.0.1 -e PGPORT=5432 -e PGUSER=postgres -e PGPASSWORD=postgres_test_password postgres:17-alpine sh /infra/scripts/test_migrate_target.sh`; pre-chequeo de conteos y de catálogo del runbook; copia verificada con `pg_restore -l`; **`MIGRATION_TARGET=020`** tras la 019; pruebas opt-in `RUN_DATABASE_TESTS=1` con `DATABASE_URL` (rol de aplicación) y `DATABASE_ADMIN_URL` para migraciones.
   - **Frontend/UI:** `cd frontend && pnpm install --frozen-lockfile`, `pnpm test`, `pnpm run typecheck` y `pnpm run build`.
   - **Infraestructura (job `infrastructure`, aplica aunque no se toque Compose):** `python3 infra/scripts/verify_version_sources.py --exclude-constitution`; `sh -n infra/postgres/migrate.sh`; `docker compose config -q` para desarrollo y el merge dev+prod con variables dummy según `AGENTS.md`; aserciones con `infra/scripts/assert_production_compose.py` sobre el JSON renderizado. No se esperan cambios en Compose, pero el job debe pasar.
   - **Seguridad (job `security`, aplica aunque no haya dependencias nuevas):** `pip-audit -r backend/requirements.txt`; auditoría del frontend desde la raíz con `pnpm --dir frontend audit --prod --json --audit-level low` y `infra/scripts/audit_frontend.py` (bloque de `AGENTS.md`); escaneo Trivy de CI. Cualquier hallazgo accionable bloquea.
   - **Evidencia local de la vuelta 1:** backend **469 passed / 132 skipped**; opt-in **42 passed** (`player_catalog_isolation` + `schema` + `swiss_transaction`) y **23 passed** (`concurrency_006` + `migration_019`); frontend **77 passed** y `typecheck` OK; `build` no se re-ejecutó en esta vuelta por OOM local (sin cambios de UI desde la última ejecución correcta); `compileall`, `sh -n infra/postgres/migrate.sh` y diff-check OK. El runner se ejecutó en el puerto 55432 por credenciales del PostgreSQL local; se declara así, no como el comando literal del puerto 5432.
9. Revisión humana distinta del autor y actualización de `MEMORY.md` con las decisiones y su motivo. **T011 sigue `[ ]`** hasta CI en `main` y revisión humana; `MEMORY.md` ya registra «T011 ejecutada localmente, sin marcar».

## Dudas abiertas

No quedan preguntas bloqueantes. La vuelta 1 de correcciones está incorporada; la spec queda **implementada** y solo T011 (CI y revisión humana) permanece abierta.
