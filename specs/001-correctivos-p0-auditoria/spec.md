# Spec 001 — Correctivos P0 de la auditoría técnica 2026-10-19

Estado: implementada y validada funcionalmente (2026-10-19); validación documental final completada (2026-10-22) y spec cerrada. Los commits de la entrega están materializados.

## Contexto y objetivo

La auditoría técnica integral del 2026-10-19 concluyó que Bracket Craft no tiene hallazgos críticos explotables vía API, pero sí cuatro hallazgos **ALTOS** que contradicen la constitución y deben corregirse antes de operar torneos reales:

- **R01 — Fuga potencial de PII cross-tenant:** el catálogo de jugadores es global y el alta reutiliza jugadores por HMAC sin filtrar por organización. Una organización podría obtener nombre, apellidos y fecha de nacimiento de jugadores de otra registrando su documento.
- **R02 — Despliegue de producción inseguro:** la configuración de producción no anula los puertos ni los volúmenes de desarrollo porque la fusión de Compose agrega secuencias. La base de datos, Redis y el almacenamiento quedarían publicados en el host, y el código fuente del host podría sombrear la build compilada en `api`, `worker` y `web`.
- **R03 — Inmutabilidad de resultados solo en aplicación:** los triggers existentes protegen la estructura publicada, pero no impiden modificar marcadores, penales, ganador, estado o tipo de resolución de un partido con resultado confirmado.
- **R04 — Deriva documental de versiones:** la constitución, `AGENTS.md`, el README y lo que realmente ejecuta la integración continua no declaran la misma combinación de Python, Node y pnpm.

El objetivo es cerrar los cuatro correctivos P0 con garantías verificables, sin introducir funcionalidad nueva. R02 incluye además la validación del merge de producción en CI, lo que cierra el hallazgo medio **R08**. R01 y R03 incorporan pruebas de base de datos en CI, lo que cierra parcialmente la brecha **R07**.

Estado observado al redactar esta spec: el árbol de trabajo está limpio y `HEAD` contiene en `docs/constitution.md` una cabecera que declara `1.0.0`, una fila `1.0.1` en el historial y una regla §3.5 con Python 3.14, Node 24 y pnpm 12.12.2; `ci.yml` y `AGENTS.md` usan Python 3.12, Node 24 y pnpm 12.11.2. La auditoría describió parte de ese contenido como cambio local sin commitear. Esta spec no depende de ese estado: describe el **estado objetivo** y exige coherencia entre cabecera, historial y fuentes operativas.

Decisiones cerradas de esta revisión:

1. **R01:** catálogo de jugadores por organización con RLS; se dividen los registros compartidos existentes y se eliminan los residuos sin referencia (decisión confirmada por el usuario); el seed también filtra por organización; la deduplicación cross-tenant deja de existir.
2. **R02:** producción no publica ningún puerto; solo `web` se une a una red externa de proxy ya existente y el resto queda en la red interna; el overlay no monta código del host en `api`, `worker` ni `web`, pero sí permite los montajes de solo lectura de infraestructura de PostgreSQL; no se anula el volumen de datos de PostgreSQL; CI valida el merge dev+prod.
3. **R03:** ningún camino de corrección para resultados confirmados; se bloquean `UPDATE` y `DELETE`; no hay excepción para `platform_admin`; migración 016 aplicada después de 015.
4. **R04:** Python 3.14, Node 24 y pnpm **12.12.1** (12.12.2 no existe); CI, Dockerfiles, `packageManager`, AGENTS, README y constitución se alinean; se permite el ajuste del pin de pnpm en `packageManagerDependencies`; si una dependencia fijada no es compatible, el trabajo se detiene y se reporta.
5. **Pruebas:** aislamiento de R01 e inmutabilidad de R03 se ejecutan en CI con PostgreSQL de servicio y un harness explícito, incluidas las proyecciones públicas, el acceso denegado a la vista cruda y la migración desde 014.

## Usuarios

- **Administrador u operador de una organización:** da de alta e importa plantillas y necesita que sus jugadores no se mezclen con los de otra organización.
- **Visitante público:** consulta torneos publicados y no debe recibir documentos, fechas de nacimiento ni datos de organizaciones ajenas.
- **Administrador de plataforma:** audita organizaciones y no debe poder ver PII cross-tenant ni editar resultados confirmados.
- **Operador de despliegue:** levanta el perfil de producción y necesita que no herede puertos, volúmenes de código ni comandos de desarrollo.
- **Desarrollador o revisor:** necesita una única referencia de versiones para reproducir CI, imágenes y documentación.

## Roles y visibilidad

- **Público:** ve la proyección pública de torneos publicados (incluidos nombres y apellidos de jugadores, dorsal, edad derivada y foto solo con consentimiento). No ve documentos, fechas de nacimiento ni datos de organizaciones no publicadas.
- **Miembro de organización:** puede consultar y operar únicamente los jugadores vinculados a su organización.
- **Administrador de organización:** puede importar, registrar y mantener los jugadores de su organización; no puede ver ni reutilizar los de otra.
- **Administrador de plataforma:** no obtiene acceso a PII cross-tenant por el catálogo de jugadores y no puede modificar ni borrar resultados confirmados.
- **Operador de despliegue:** ejecuta el perfil de producción sin puertos publicados ni código del host montado en los servicios de ejecución.

## Historias de usuario

- **HU-1.** Como administrador de una organización, quiero registrar o importar un jugador por su documento sin que el sistema me revele si ese documento ya existe en otra organización, para no filtrar datos personales ajenos.
- **HU-2.** Como operador de despliegue, quiero que el perfil de producción no herede puertos ni volúmenes de desarrollo, para que el despliegue ejecute solo lo construido y no exponga servicios internos.
- **HU-3.** Como responsable de integridad deportiva, quiero que un resultado confirmado sea inmutable también en la base de datos, para que ningún camino —aplicación o SQL directo— pueda alterarlo o borrarlo.
- **HU-4.** Como desarrollador o revisor, quiero que la constitución, la guía, el README, la CI y las imágenes declaren las mismas versiones, para reproducir el entorno sin ambigüedad.

## Definiciones

- **PII de jugador:** nombre, apellidos, tipo y número de documento, fecha de nacimiento y foto. El número de documento se almacena cifrado; el HMAC solo se usa para deduplicación.
- **Catálogo de jugadores:** conjunto de registros de jugador reutilizables al dar de alta una plantilla. Con la decisión de R01, su alcance es la organización propietaria.
- **Deduplicación:** reutilización de un registro de jugador ya existente cuando coinciden organización, tipo de documento, país emisor y HMAC del número de documento.
- **Resultado confirmado:** partido con `result_confirmed = TRUE`, alcanzado al cerrar un acta en estado `finished` o `administrative_resolution`.
- **Configuración combinada de producción:** resultado de aplicar la configuración de desarrollo y, sobre ella, el perfil de producción. No es el archivo de producción por separado.
- **Volumen limpio:** base de datos creada desde cero con los scripts de inicialización y todas las migraciones. **Volumen migrado:** base existente que ya aplicó migraciones anteriores; para R01 se prueba específicamente una base en el estado 014.
- **Vista cruda de formación:** `v_public_match_lineups_unpublished`, definición interna que alimenta al wrapper y que no es accesible a `bracket_app` ni a `PUBLIC`.
- **Wrapper de formación pública:** `v_public_match_lineups`, vista filtrada que solo devuelve formación publicada y que sí es accesible a `bracket_app`.
- **Versión de referencia:** combinación exacta de Python, Node y pnpm que ejecutan CI, imágenes y herramientas locales.
- **Puerta de compatibilidad:** verificación previa que debe pasar antes de cambiar CI, Dockerfiles o `packageManager`; si falla, el trabajo se detiene sin actualizar dependencias por iniciativa propia.

## Requisitos funcionales

### R01 — Catálogo de jugadores por organización

**RF-001. Aislamiento del catálogo por organización.**
CUANDO una organización registra, importa o consulta un jugador por su documento, EL SISTEMA solo puede leer, reutilizar o crear registros de jugador cuyo `organization_id` sea el de esa organización, y nunca devuelve datos de un jugador que solo pertenece a otra.
*Criterios de aceptación:*
- Con dos organizaciones A y B, si A registra un documento y B registra el mismo documento, la respuesta para B contiene únicamente los datos aportados por B y no revela nombre, apellidos, fecha de nacimiento, foto ni la existencia previa del registro de A.
- Ningún endpoint del Workspace devuelve un jugador que no esté vinculado a la organización del contexto.
- Una consulta directa con el rol de aplicación y contexto de la organización B no devuelve la fila de A; sin contexto de organización no devuelve filas de jugadores.
- La respuesta de B no se diferencia de un alta nueva por código de estado, mensaje ni carga útil.

**RF-002. Esquema tenant-owned y claves de integridad.**
EL SISTEMA trata `players` como tabla propiedad de una organización: agrega `organization_id UUID NOT NULL`, habilita y fuerza RLS, impone unicidad de documento por organización y agrega claves foráneas compuestas que impiden referencias cross-tenant.
*Criterios de aceptación:*
- `players` tiene `organization_id NOT NULL` con referencia a `organizations(id)`.
- RLS está habilitado y forzado con una política equivalente a la del resto de tablas tenant.
- Existe unicidad por `(organization_id, document_type, issuing_country, national_id_hmac)` y deja de existir la unicidad global por documento.
- Existe unicidad `(id, organization_id)` que permite las claves foráneas compuestas.
- `rosters`, `match_lineup_snapshots`, `match_events` y `player_suspensions` referencian al jugador mediante `(player_id, organization_id)`; se reemplazan las claves foráneas simples a `players(id)`. `match_rosters` queda protegido a través de su referencia compuesta a `rosters`.
- Insertar un roster, una alineación, un evento o una suspensión con un jugador de otra organización falla por clave foránea.
- El mismo HMAC puede existir en dos organizaciones distintas; dentro de una misma organización no puede repetirse.
- Los grants del rol de aplicación incluyen `organization_id` en `SELECT` e `INSERT`, mantienen `national_id_encrypted` fuera de `SELECT` y no conceden `UPDATE` ni `DELETE` sobre `players`.
- El seed de desarrollo (`backend/scripts/seed_demo.py`) cumple el nuevo esquema: inserta jugadores con `organization_id` y no consulta un catálogo global.

**RF-003. Deduplicación estrictamente intraorganización en alta e importación.**
EL SISTEMA aplica la deduplicación por organización tanto en el alta individual como en la importación masiva: busca el HMAC filtrando por `organization_id`, inserta con la organización del contexto y resuelve las carreras de alta concurrente sin duplicar.
*Criterios de aceptación:*
- Dos altas del mismo documento en la misma organización reutilizan el mismo registro y no crean un duplicado.
- El mismo documento en dos organizaciones produce dos registros independientes, sin vínculo visible entre ellos.
- Dos importaciones concurrentes del mismo documento en la misma organización no dejan dos registros para esa organización ni pierden rosters ya existentes; la segunda operación reutiliza el registro ganador o recibe un conflicto controlado sin datos parciales.
- La importación CSV/TXT y el alta individual usan la misma regla y no dependen de un catálogo global.
- El seed de desarrollo filtra la búsqueda de jugador por `organization_id` y crea el roster en la misma transacción, de modo que todo jugador del seed queda referenciado.
- El mensaje de error dentro de una organización no revela datos de otra.

**RF-004. Migración 015 sin pérdida de rosters ni histórico.**
CUANDO la migración 015 se aplica sobre una base con jugadores compartidos entre organizaciones, EL SISTEMA divide o duplica cada registro por organización, repunta todas las referencias a la copia correcta y deja el esquema en el estado tenant-owned.
*Criterios de aceptación:*
- Sobre una base en estado 014 con un jugador referenciado por rosters de dos organizaciones, después de 015 existen dos registros de jugador independientes, uno por organización.
- Cada roster, alineación, evento, suspensión y registro de `match_rosters` queda apuntando al jugador de su propia organización; no aparecen referencias huérfanas ni cruces.
- Los conteos de rosters, alineaciones, eventos y suspensiones se mantienen antes y después de la migración.
- El historial de suspensiones que referencia eventos se conserva coherente después de repuntar el jugador.
- Las filas de jugador sin ninguna referencia se eliminan por decisión confirmada del usuario: todo jugador legítimo tiene referencia porque el alta crea el roster en la misma transacción, de modo que la eliminación solo alcanza residuos; al final no queda ninguna fila con `organization_id` nulo.
- El seed de desarrollo se ejecuta correctamente después de 015 y deja todos sus jugadores referenciados por rosters.
- La migración conserva el `national_id_encrypted`, el HMAC, los datos personales y la foto; no los expone en logs ni en mensajes de error.
- La migración se aplica correctamente sobre un volumen limpio y sobre uno en estado 014.
- La migración es idempotente: volver a ejecutarla sobre la misma base no duplica jugadores ni falla por objetos existentes.
- `sh -n infra/postgres/migrate.sh` sigue pasando y no se edita ninguna migración aplicada.

**RF-005. Proyecciones públicas, vista cruda y wrapper de formación.**
MIENTRAS un torneo está publicado, EL SISTEMA sigue exponiendo la misma proyección pública de jugadores y formación —nombre, apellidos, dorsal, edad derivada, formación publicada y foto solo con consentimiento— sin documentos ni fechas de nacimiento, y el nuevo aislamiento no rompe las vistas ni los endpoints públicos.
*Criterios de aceptación:*
- La migración 015 recrea las **dos definiciones que unen `players`** con join por `organization_id` además de por id, `security_barrier = true` y sin cambiar la lista ni el orden de columnas: `v_public_tournament_players` y `v_public_match_lineups_unpublished`. No queda ninguna unión de `players` sin el filtro de organización.
- `v_public_tournament_players` sigue accesible a `bracket_app`.
- `v_public_match_lineups_unpublished` es la vista **cruda** que alimenta al wrapper: se recrea por dependencia, pero queda **inaccesible** a `bracket_app` y `PUBLIC`; se mantiene la revocación de la migración 008 y no se concede `SELECT` sobre ella.
- Solo se accede a la formación pública a través de `v_public_match_lineups`, el wrapper filtrado que conserva su `GRANT SELECT` a `bracket_app` y devuelve únicamente formación publicada.
- `v_public_tournament_players` y `v_public_match_lineups` se conservan con un propietario que sea superusuario o tenga una exención efectiva de RLS (el rol administrador que aplica las migraciones) y sin `security_invoker`; no se cambia su propietario a `bracket_app` ni a un rol sujeto a RLS. Lo mismo aplica a la definición cruda.
- Los endpoints públicos de torneo, tabla, partidos y formación publicada siguen devolviendo la misma información en los mismos casos que antes.
- La proyección pública no incluye tipo de documento, número de documento, HMAC, fecha de nacimiento ni datos de otra organización.
- La foto sigue apareciendo únicamente cuando el roster tiene consentimiento de imagen.
- Una prueba con el rol de aplicación y sin `app.current_organization_id` confirma que `v_public_tournament_players` y `v_public_match_lineups` devuelven las filas públicas esperadas y ninguna fila de otra organización.
- Una prueba con `bracket_app` confirma que consultar `v_public_match_lineups_unpublished` produce un error de permiso denegado.

### R02 — Configuración de producción y validación del merge

**RF-006. Producción no publica ningún puerto y separa red interna de red del proxy.**
CUANDO se ejecuta la configuración combinada de producción, EL SISTEMA no publica en el host ningún puerto de ningún servicio, mantiene `db`, `redis`, `storage`, `api` y `worker` solo en la red interna del stack, y une únicamente `web` a la red externa del proxy.
*Criterios de aceptación:*
- La configuración renderizada no contiene puertos publicados ni `host_ip` para ningún servicio: base de datos, Redis, almacenamiento, API, worker ni web.
- La anulación se hace con la semántica de fusión de Compose (`!reset []`/`!override`), no confiando en que `ports: []` reemplace la secuencia de desarrollo.
- Existe una red interna del stack donde están todos los servicios; `api`, `db`, `redis` y `storage` no se unen a ninguna red externa.
- Existe una red externa ya existente para el proxy (por ejemplo `edge`/`proxy`), con nombre configurable por variable de entorno (por ejemplo `PROXY_NETWORK`), declarada como `external: true`; solo `web` se une a ella.
- `web` alcanza `api` por la red interna en SSR, sin puertos publicados.
- La configuración de desarrollo conserva sus puertos locales como hasta ahora.
- La creación o unión de la red del proxy se documenta como prerrequisito de despliegue a cargo del operador, fuera de este compose.

**RF-007. Producción ejecuta artefactos construidos, conserva los volúmenes de datos y permite solo los montajes de infraestructura.**
CUANDO se ejecuta el perfil de producción, EL SISTEMA ejecuta el código y los artefactos construidos dentro de las imágenes, no monta código fuente del host en `api`, `worker` ni `web`, mantiene los volúmenes de datos y permite únicamente los montajes de solo lectura de infraestructura de PostgreSQL.
*Criterios de aceptación:*
- La configuración combinada no monta `./backend` ni `./frontend` en `api`, `worker` ni `web`; tampoco monta `./infra` en `api`, `worker` ni `web`.
- El volumen de datos de PostgreSQL (`postgres_data`) no se anula; tampoco los volúmenes de datos de Redis ni de almacenamiento.
- Los montajes de solo lectura de `./infra/postgres` (init y migraciones) en `db` y `db-migrate` son infraestructura permitida y no se consideran "código del host"; el job `db-migrate` puede conservar `./infra/postgres:/migrations:ro`.
- `api` no arranca con recarga automática; `web` arranca el servidor compilado.
- Las imágenes de `api`, `worker` y `web` se construyen desde sus Dockerfiles de producción.

**RF-008. CI valida desarrollo y el merge de producción.**
EL SISTEMA valida en integración continua la configuración de desarrollo y la combinación desarrollo+producción, y falla si reaparecen puertos, volúmenes de código o comandos de desarrollo.
*Criterios de aceptación:*
- El job de infraestructura ejecuta `docker compose config -q` para desarrollo.
- El mismo job ejecuta `docker compose -f docker-compose.yml -f docker-compose.production.yml config -q` con variables dummy que satisfacen los `:?` de secretos, sin secretos reales.
- Además de la validación sintáctica, el job inspecciona la configuración renderizada y falla si algún servicio publica puertos, si `api`, `worker` o `web` montan código del host, si los comandos no son de producción o si la red externa no queda restringida a `web`.
- La validación no anula ni exige el volumen de datos de PostgreSQL y acepta los montajes de solo lectura de `./infra/postgres` en `db` y `db-migrate`.
- La documentación del repositorio indica la versión mínima de Compose y el comando exacto de validación.
- Esta validación cubre el hallazgo R08 de la auditoría.

**RF-009. Versión mínima de Compose verificada.**
EL SISTEMA documenta y comprueba la versión mínima de Compose que soporta `!reset`/`!override`, comparando mayor, menor y parche, antes de usar esa sintaxis en producción.
*Criterios de aceptación:*
- La versión mínima es **2.24.4**; `AGENTS.md` y el README la indican junto con el motivo.
- La CI comprueba la versión disponible comparando también el parche (por ejemplo, 2.24.3 no cumple y 2.24.4 sí) y falla con un mensaje comprensible si no alcanza el mínimo.
- El entorno local observado durante la planificación es Compose v5.5.1; la comprobación no depende de ese valor concreto.

### R03 — Inmutabilidad de resultados confirmados en base de datos

**RF-010. Bloqueo de cambios sobre un resultado confirmado.**
CUANDO un partido tiene `result_confirmed = TRUE`, EL SISTEMA rechaza cualquier actualización que modifique los marcadores regular y final, los penales, el equipo ganador, el estado, el tipo o motivo de resolución o el propio indicador de confirmación.
*Criterios de aceptación:*
- Un `UPDATE` directo sobre `home_score_regular`, `away_score_regular`, `home_score`, `away_score`, `home_penalties`, `away_penalties`, `winner_team_id`, `status`, `resolution_type`, `resolution_reason` o `result_confirmed` de un partido confirmado falla con un error explícito y no deja cambios parciales.
- Intentar volver `result_confirmed` a `FALSE` también falla.
- Una actualización que solo modifica campos no resultantes —por ejemplo `updated_at`— se permite.
- Una actualización que repite exactamente los mismos valores no se considera un cambio y se permite.
- La protección se aplica con el rol de aplicación, que no es superusuario ni tiene `BYPASSRLS`.

**RF-011. Bloqueo del borrado de resultados confirmados.**
CUANDO un partido tiene `result_confirmed = TRUE`, EL SISTEMA rechaza su borrado con un error explícito, además de la protección de estructura publicada que ya exista.
*Criterios de aceptación:*
- Un `DELETE` directo de un partido confirmado falla.
- El bloqueo se aplica en el mismo trigger o en uno equivalente de `BEFORE DELETE`.
- Si el partido no está confirmado, el borrado sigue sujeto a las reglas de estructura publicada existentes.
- La prueba se ejecuta con el rol de aplicación.

**RF-012. Cierre y operaciones legítimas sin regresiones.**
CUANDO se cierra un acta de un partido aún no confirmado (`OLD.result_confirmed = FALSE`), EL SISTEMA permite la transición a `finished` o `administrative_resolution` con `result_confirmed = TRUE` en la misma transacción; y permite las operaciones legítimas sobre partidos no confirmados.
*Criterios de aceptación:*
- El cierre normal de un acta sigue funcionando y confirma el resultado.
- La resolución administrativa sigue funcionando y confirma el resultado.
- El avance de llaves que asigna equipos a partidos no confirmados y la reactivación del bracket reset de doble eliminación siguen funcionando.
- El seed de desarrollo sigue funcionando: carga jugadores con `organization_id` y cierra sus partidos sin errores.
- Las actualizaciones de estructura protegidas por los triggers existentes mantienen su comportamiento.
- No existe ninguna excepción para `platform_admin`: la administración global tampoco puede modificar ni borrar un resultado confirmado.

**RF-013. Migración 016 nueva, segura e idempotente.**
EL SISTEMA aplica la protección de resultados mediante la migración 016, con definiciones idempotentes, sin editar migraciones ya aplicadas y respetando el historial append-only.
*Criterios de aceptación:*
- La migración 016 se aplica sobre un volumen limpio y sobre uno ya migrado.
- La migración puede volver a ejecutarse sobre la misma base sin fallar por funciones o triggers ya existentes.
- La función y el trigger usan `CREATE OR REPLACE`/`DROP ... IF EXISTS` o una estrategia equivalente.
- `sh -n infra/postgres/migrate.sh` sigue pasando.
- No se modifica ninguna migración aplicada anteriormente.
- La aplicación se hace en el orden 015 y luego 016; si las entregas se fusionan por separado, la entrega de R03 no se integra antes que la de R01 para no dejar un hueco `016` aplicado sin `015` en el historial.

### R04 — Versiones de referencia y enmienda constitucional

**RF-014. Una sola combinación de versiones de referencia.**
EL SISTEMA declara y ejecuta una única combinación de versiones de referencia: Python 3.14, Node 24 y pnpm 12.12.1, y esa combinación coincide en la constitución (§3.5), `AGENTS.md`, el README, el workflow de CI, los Dockerfiles y el gestor de paquetes del frontend.
*Criterios de aceptación:*
- La versión de pnpm es **12.12.1** y no 12.12.2: 12.12.2 no existe en el registro npm; las versiones publicadas cercanas son 12.12.0, 12.12.1, 12.13.0 y 12.14.0.
- `ci.yml` usa Python 3.14 en todos los jobs que instalan Python y pnpm 12.12.1 en todos los usos de `pnpm/action-setup`.
- `backend/Dockerfile` usa una imagen base de Python 3.14.
- `frontend/package.json` declara `packageManager: pnpm@12.12.1`; Node 24 se mantiene.
- `AGENTS.md`, el README y `docs/constitution.md` §3.5 declaran Python 3.14, Node 24 y pnpm 12.12.1.
- No queda ninguna fuente de **runtime** (workflow, Dockerfiles, `packageManager`, documentación de versiones de referencia) que declare Python 3.12, Node 22 o pnpm 12.11.2; los tipos de desarrollo como `@types/node: ^22` no cuentan como versión de runtime.
- El pin del gestor de paquetes en `frontend/pnpm-lock.yaml` (bloque `packageManagerDependencies`, es decir el propio pin de pnpm) puede actualizarse a 12.12.1 como parte de R04; no se cambian versiones de dependencias ni el resto del lockfile.
- `pnpm install --frozen-lockfile` pasa con el pin de pnpm actualizado y commiteado.
- El lockfile del frontend sigue versionado.

**RF-015. Puerta de compatibilidad antes de cambiar CI e imágenes.**
ANTES de dar por válida la alineación de versiones, EL SISTEMA verifica que las dependencias fijadas y el lockfile funcionan con Python 3.14 y pnpm 12.12.1; si algo falla, el trabajo se detiene y se reporta sin actualizar versiones de dependencias por iniciativa propia.
*Criterios de aceptación:*
- Se crea un entorno con Python 3.14, se instala `backend/requirements.txt` sin modificar versiones y se ejecutan `pytest -q` y `python -m compileall -q app`.
- Se ejecuta `pnpm install --frozen-lockfile` con Node 24 y pnpm 12.12.1, seguido de `pnpm test`, `pnpm run typecheck` y `pnpm run build`.
- Se ejecuta el job `security` con Python 3.14: `pip-audit -r backend/requirements.txt`, `pnpm audit --prod --audit-level high` con pnpm 12.12.1 y el escaneo Trivy de CI; si alguna auditoría falla por incompatibilidad de versión, se detiene y se reporta. Los hallazgos preexistentes de la cadena de producción de Nuxt quedaron cubiertos por la excepción §5.1, retirada por la spec 003; el job está verde desde el run 39361295825.
- Se construyen las imágenes de backend y frontend con las versiones objetivo.
- Se permite únicamente el ajuste del pin del gestor de paquetes en `frontend/pnpm-lock.yaml` (bloque `packageManagerDependencies`); cualquier otro cambio del lockfile o de versiones de dependencias queda prohibido.
- Si una dependencia fijada, el lockfile (más allá del pin del gestor) o una imagen no es compatible, se detiene la implementación, se reporta la incompatibilidad con evidencia y no se actualiza ninguna versión de dependencia ni se regenera el lockfile más allá del ajuste permitido del pin del gestor.
- La evidencia de la puerta queda registrada en la verificación de la spec.

**RF-016. Enmienda constitucional conforme a la sección 5.2.**
CUANDO se corrija la constitución, EL SISTEMA registra una versión coherente en la cabecera, en el historial y en la regla §3.5, con motivo, reglas afectadas e impacto, siguiendo el procedimiento de evolución y con revisión humana distinta del autor.
*Criterios de aceptación:*
- La constitución pasa a la versión **1.1.0**, incremento menor justificado porque cambia el contenido de una regla de implementación (§3.5), no solo una aclaración.
- La enmienda **regulariza** un cambio que ya está presente en `HEAD`: §3.5 ya declara Python 3.14, Node 24 y pnpm (12.12.2) sin haber subido la versión; la 1.1.0 lo registra formalmente, lo corrige a 12.12.1 y deja cabecera, §3.5 e historial coherentes.
- Se usa incremento menor y no parche aunque la auditoría recomendara un parche: el parche (§5.2) aplica a aclaraciones que no alteran el significado, y aquí se modifica el contenido de una regla de implementación (las versiones de referencia), por lo que corresponde la versión menor.
- La cabecera declara `1.1.0`, la última fila del historial es `1.1.0` y la fecha de última actualización corresponde al cambio.
- La fila `1.1.0` describe el motivo, las reglas afectadas y el impacto en el código existente.
- La fila `1.0.1` existente se conserva; no se reescribe el historial anterior.
- La enmienda se tramita como entregable y commit separado de R01, R02 y R03, y no se mezcla con cambios funcionales.
- La revisión humana queda registrada y es distinta de la persona o agente autor.

**RF-017. Estado documental y del repositorio consistente.**
EL SISTEMA mantiene el estado documentado y el árbol de trabajo consistentes: no queda una edición local sin commitear de la constitución que contradiga la versión registrada, ni una cabecera que contradiga su propio historial.
*Criterios de aceptación:*
- `git status` no muestra cambios pendientes en `docs/constitution.md`, `AGENTS.md` ni el README después del cambio.
- El contenido de `HEAD` para esos archivos coincide con el estado objetivo.
- La cabecera, el historial y §3.5 declaran la misma versión y las mismas versiones de referencia.
- El README declara explícitamente las versiones de referencia junto al stack.

### Pruebas de base de datos en CI

**RF-018. Aislamiento e inmutabilidad verificados en CI con PostgreSQL de servicio.**
EL SISTEMA ejecuta en integración continua las pruebas de aislamiento de R01 y de inmutabilidad de R03 contra una instancia real de PostgreSQL, con un harness explícito que aplica migraciones con un rol administrador y ejecuta las pruebas con el rol de aplicación.
*Criterios de aceptación:*
- El workflow de CI levanta un servicio PostgreSQL 17 con healthcheck, crea el rol de aplicación sin superusuario y sin `BYPASSRLS`, y aplica los scripts de inicialización y todas las migraciones **con un rol administrador** (superusuario o rol con exención efectiva de RLS).
- Las migraciones se aplican con el script real del repositorio, respetando checksums y orden numérico; los tests se conectan con `DATABASE_URL` apuntando al **rol de aplicación** y con `RUN_DATABASE_TESTS=1`.
- Las pruebas crean sus propias organizaciones y usuarios con la función SECURITY DEFINER `create_organization_with_owner`, porque `bracket_app` no puede insertar en `organizations`; no dependen de `seed_demo` ni de datos demo.
- El aislamiento entre pruebas es explícito: cada prueba usa organizaciones, usuarios y torneos con identificadores únicos y limpia por transacción revertida o por eliminación acotada; puede ejecutarse en cualquier orden y no comparte filas con otras.
- Existen pruebas de aislamiento que cubren: alta del mismo documento en A y B sin fuga, consulta directa sin contexto, deduplicación intraorganización, unicidad por organización, claves foráneas cross-tenant rechazadas y ambas proyecciones públicas sin datos sensibles y con filas devueltas sin contexto de organización.
- Existen pruebas de migración con un harness dedicado: se crea una base o esquema aparte, se aplican selectivamente los scripts de inicialización y las migraciones 001-014 para obtener una base en **estado 014**, se siembra un jugador compartido por dos organizaciones y luego se aplican 015 y 016; se verifican la división, el repunte de referencias, los conteos y la coherencia del historial.
- Existen pruebas de inmutabilidad que cubren: `UPDATE` de cada campo protegido, `DELETE`, mismo valor permitido, `updated_at` permitido, cierre de acta, resolución administrativa, avance de llaves y bracket reset.
- Las pruebas conviven con el resto del job de CI: la base de pruebas es independiente de cualquier servicio de desarrollo, la suite unitaria que no requiere base sigue funcionando sin `RUN_DATABASE_TESTS=1`, y las pruebas que sí la requieren se identifican y ejecutan de forma determinista.
- Las pruebas fallan si se elimina la política RLS, la unicidad por organización, la clave foránea compuesta o el trigger de inmutabilidad.
- Los tests de invitaciones existentes pueden seguir siendo opt-in; esta spec no los convierte en obligatorios, pero el servicio de PostgreSQL puede reutilizarse para ellos si no requieren cambios adicionales.

## Requisitos no funcionales

- **RNF-001. Compatibilidad de API:** salvo el cambio deliberado de no revelar la existencia de un jugador de otra organización, los contratos de los endpoints existentes no cambian; en particular, la proyección pública conserva su forma.
- **RNF-002. Atomicidad:** las migraciones 015 y 016 se ejecutan en transacción; si fallan, la base queda en el estado anterior.
- **RNF-003. Bloqueos acotados:** la migración 015 se ejecuta en una transacción, no usa `LOCK TABLE` explícito y repunta referencias por conjunto, no con un bucle fila por fila por jugador; el plan detalla la estrategia para el volumen esperado del catálogo.
- **RNF-004. Sin secretos ni defaults nuevos:** los cambios no introducen secretos, credenciales ni valores por defecto de desarrollo fuera de `.env.example`; la validación de CI usa valores dummy.
- **RNF-005. Verificación honesta:** toda prueba que no pueda ejecutarse en el entorno se declara como no ejecutada, con su motivo; no se da por aprobada una verificación no realizada.
- **RNF-006. Compatibilidad de Compose:** la sintaxis elegida debe ser compatible con Compose **2.24.4** o superior (comparando también el parche) y con el entorno de CI; si la CI no puede garantizar esa versión, el cambio debe detectarlo y fallar con un mensaje claro.
- **RNF-007. Sin regresiones de RLS:** el rol de aplicación sigue sin ser superusuario y sin `BYPASSRLS`; ninguna solución de R01 puede basarse en elevarlo.
- **RNF-008. Determinismo de pruebas:** las pruebas de base de datos no dependen del orden, de datos demo ni de tiempos; usan identificadores únicos y contextos RLS explícitos.
- **RNF-009. Sin upgrades improvisados de dependencias:** si la puerta de compatibilidad de R04 falla, no se actualizan versiones de dependencias ni se regenera el lockfile más allá del pin del gestor de paquetes; se reporta y se detiene. El ajuste del pin de pnpm en `packageManagerDependencies` sí forma parte de R04.
- **RNF-010. Separación de entregables y orden de migraciones:** R01, R02, R03 y R04 se pueden revisar y commitear de forma separada; R04 se entrega separado de R01-R03 y, dentro de R04, la enmienda constitucional se commitea aparte de los cambios de CI, Dockerfiles y documentación técnica. La enmienda no se mezcla con cambios funcionales. Cuando R01 y R03 se entreguen por separado, el orden de fusión y aplicación es 015 y luego 016, para no dejar un hueco en la secuencia del historial de esquema.

## Datos personales y privacidad

- **Datos involucrados:** nombre, apellidos, tipo y número de documento (cifrado), HMAC del documento, país emisor, fecha de nacimiento, foto y consentimiento de imagen.
- **Quién puede verlos:** solo la organización propietaria del registro de jugador dentro del Workspace. La administración de plataforma no obtiene acceso cross-tenant por el catálogo.
- **Qué se expone públicamente:** nombre, apellidos, dorsal, edad derivada y foto solo con consentimiento. Nunca documento, HMAC ni fecha de nacimiento.
- **R01** corrige la vía de exposición cross-tenant y elimina los registros de jugador sin referencias, por decisión confirmada del usuario. **R02** evita que un despliegue de producción exponga servicios internos o ejecute código no construido. **R03** no trata datos personales. **R04** no trata datos personales.
- Los datos existentes que se dupliquen por organización durante la migración deben conservar su protección y no aparecer en logs ni en mensajes de error.
- La limpieza de pruebas en CI no debe dejar datos personales reales ni reutilizar la base de producción.

## Casos límite

### R01

1. **Jugador existente compartido por rosters de dos organizaciones:** la migración 015 lo separa en registros independientes y repunta cada referencia a la organización correcta, conservando la validez histórica.
2. **Mismo documento con datos distintos en dos organizaciones:** no se fusionan ni se sobrescriben; cada organización conserva los datos que aportó.
3. **Mismo documento repetido dentro de una importación o en importaciones concurrentes de la misma organización:** debe quedar un solo registro por organización y no perderse ningún roster.
4. **Jugador referenciado solo por eventos, alineaciones o suspensiones históricas:** la migración conserva esas referencias aunque no tenga roster activo.
5. **Jugador referenciado por `match_rosters`:** al cambiar el jugador del roster, también se actualiza la referencia duplicada de `match_rosters` para no romper su clave foránea.
6. **Suspensión que referencia un evento:** el repunte del jugador en `match_events` y en `player_suspensions` debe quedar coherente con la clave foránea compuesta.
7. **Rosters inactivos o vencidos:** siguen apuntando a un jugador de su organización y mantienen su historial.
8. **Filas de jugador sin ninguna referencia:** se eliminan durante la migración por decisión confirmada del usuario; todo jugador legítimo tiene referencia porque el alta crea el roster en la misma transacción, así que la eliminación solo alcanza residuos. No quedan filas con `organization_id` nulo.
9. **Seed de desarrollo:** tras 015 sigue funcionando, inserta `organization_id` y filtra la deduplicación por organización; no crea jugadores sin referencia.
10. **Foto y consentimiento:** el consentimiento es del roster, no del jugador; duplicar un jugador no cambia el consentimiento ni publica una foto sin él.
11. **Proyecciones públicas:** `v_public_tournament_players` y `v_public_match_lineups` deben seguir funcionando después de habilitar el aislamiento, aun cuando el propietario de las definiciones sea un rol exento de RLS y la petición pública no tenga contexto de organización.
12. **Acceso directo a la vista cruda denegado al rol de aplicación:** `v_public_match_lineups_unpublished` se recrea por dependencia del wrapper, pero `bracket_app` y `PUBLIC` no tienen `SELECT`; consultarla produce permiso denegado y no expone formación no publicada.
13. **Alta de un documento que existe en otra organización:** la respuesta no debe permitir inferir su existencia por código de estado, mensaje ni carga útil.
14. **Importación con `photo_filename`:** la resolución de la foto y la creación del jugador deben seguir siendo atómicas.
15. **Jugador duplicado en la misma organización por una carrera:** la clave única por organización debe impedir el duplicado y la operación debe reintentar o devolver un conflicto controlado.

### R02

1. **Checkout limpio sin `.env`:** la validación del merge en CI funciona con valores dummy para las variables obligatorias, sin secretos reales.
2. **Compose anterior a 2.24.4:** la validación falla con un mensaje claro o usa una alternativa compatible; no produce una configuración silenciosamente incorrecta. Se compara también el parche.
3. **Secuencias que se fusionan por adición:** `ports: []` y `volumes: []` no anulan por sí solos los valores de desarrollo; la solución garantiza el resultado renderizado.
4. **Volumen de datos de PostgreSQL:** no se anula; el reset de `volumes` se aplica solo a los servicios que montan código.
5. **Volúmenes de datos de Redis y almacenamiento:** se conservan como volúmenes nombrados.
6. **Montajes de infraestructura:** los montajes de solo lectura de `./infra/postgres` (init y migraciones) en `db` y `db-migrate` son infraestructura permitida y no se consideran código del host; no se monta código de aplicación ni se ejecuta el servidor.
7. **Red externa ausente:** si el operador no creó la red del proxy, la configuración no debe publicar puertos ni fallar de forma silenciosa; el prerrequisito queda documentado y la validación de CI usa un nombre de red configurable.
8. **Aislamiento de red:** solo `web` se une a la red externa del proxy; `api`, `db`, `redis` y `storage` quedan solo en la red interna, y `web` alcanza `api` por esa red interna en SSR.
9. **Orden de fusión:** la validación usa el orden real de despliegue (desarrollo y luego producción), no solo el archivo de producción aislado.
10. **Entornos sin Docker:** si no se puede ejecutar la validación, se declara como no verificada; no se asume que el merge es correcto por inspección.

### R03

1. **Cierre normal:** `OLD.result_confirmed = FALSE`; la misma sentencia que confirma el resultado se permite.
2. **Resolución administrativa:** mismo comportamiento que el cierre normal, con `resolution_type = 'administrative'` y motivo.
3. **Intento de `UPDATE` directo:** cualquier cambio de un campo de resultado sobre un partido confirmado falla y aborta la transacción.
4. **Actualización con los mismos valores:** no se considera cambio; se permite para no romper reintentos idempotentes.
5. **Actualización de un campo no resultante:** `updated_at` u otros campos permitidos se pueden actualizar sin bloquear el avance de llaves.
6. **Avance de llaves:** actualiza `home_team_id`/`away_team_id` de partidos destino no confirmados; sigue funcionando.
7. **Bracket reset de doble eliminación:** reactiva un partido `cancelled` no confirmado cambiando su estado a `scheduled`; sigue funcionando.
8. **Seed de desarrollo:** cierra partidos a través del servicio de cierre; sigue funcionando.
9. **Sentencia masiva:** si afecta a la vez partidos confirmados y no confirmados, la transacción completa falla; es el comportamiento esperado.
10. **`resolution_reason`:** forma parte del resultado administrativo y también queda protegido.
11. **Borrado:** un partido confirmado no se puede borrar, aunque la versión no estuviera publicada; la prueba se hace con el rol de aplicación.
12. **`platform_admin`:** no tiene excepción en el trigger; si en el futuro se necesita un camino de corrección, será una spec aparte.
13. **Superusuario o `session_replication_role`:** pueden saltarse triggers por diseño; el rol de aplicación no tiene esos privilegios y el requisito se verifica con ese rol.

### R04

1. **Dependencia fijada incompatible con Python 3.14:** se detiene la implementación y se reporta; no se actualiza ni se sustituye la dependencia.
2. **Lockfile incompatible con pnpm 12.12.1:** se permite actualizar únicamente el pin del gestor de paquetes en `packageManagerDependencies`; si `pnpm install --frozen-lockfile` exige cambiar dependencias o el resto del lockfile, se detiene la implementación y se reporta sin regenerarlo.
3. **Imagen base o build incompatible:** se detiene y se reporta.
4. **Job `security` incompatible con Python 3.14 o pnpm 12.12.1:** si `pip-audit`, `pnpm audit` o Trivy fallan por incompatibilidad de versión, se detiene y se reporta.
5. **CI sin Compose 2.24.4 o superior:** la validación falla con un mensaje claro y se documenta el requisito.
6. **Cabecera e historial desalineados:** el estado objetivo deja una sola versión coherente en `1.1.0`, regularizando el cambio ya presente en `HEAD`.
7. **Cambios locales sin commitear:** la spec no asume que el estado del working tree sea el definitivo; exige que el estado objetivo quede registrado y sin contradicciones pendientes.
8. **Actualización futura de versiones:** deberá tocar todas las fuentes en el mismo cambio, según §3.5.
9. **Enmienda mezclada con cambios funcionales:** no se permite; se tramita como cambio propio y con revisión humana.
10. **Entregas separadas de R01 y R03 en orden inverso:** si R03 (016) se fusionara antes que R01 (015), quedaría un hueco `016` aplicado sin `015`; el orden de aplicación debe ser 015 y luego 016.

## Fuera de alcance

- **R05 a R32 de la auditoría**, incluidos los MEDIOS y BAJOS, salvo **R08**, que se cubre con R02:
  - R05, cifrado de `birth_date` en claro.
  - R06 y R12, scoping por torneo y avance entre fases.
  - R07 completo: solo se añaden las pruebas de BD que R01 y R03 necesitan; no se convierten en obligatorios todos los tests de BD existentes.
  - R09 y R10, reglas declaradas no aplicadas y constantes hardcodeadas.
  - R11, ciclo de vida de partidos.
  - R13 y R14, outbox (`MAXLEN`, `event_id`).
  - R15 a R17, rendimiento de firmas, Swiss y timeouts/pool.
  - R18 a R32, higiene, i18n, healthchecks, usuario no-root, drift de `.env.example`, CSRF, GET con efecto secundario, auditoría organizacional, emparejamientos duplicados y menores.
- Cualquier camino de corrección o reapertura de resultados confirmados; si se necesita, será una spec aparte y compatible con el principio 3.
- Actualización, sustitución o desbloqueo de versiones de dependencias si la puerta de compatibilidad de Python 3.14 o pnpm 12.12.1 falla. El único cambio permitido en `frontend/pnpm-lock.yaml` es el pin del gestor de paquetes en `packageManagerDependencies`.
- Cambios de infraestructura de red distintos de la red interna del stack y la red externa del proxy descritos en R02 (por ejemplo, balanceadores, TLS o enrutamiento del proxy).
- Reescritura o edición de migraciones ya aplicadas.
- Rotación de secretos, cambios de proveedor de almacenamiento o rearquitectura de despliegue distinta del overlay.
- Cambios de funcionalidad, interfaz de usuario, nuevas rutas o nuevos contratos de API.

## Impacto en la constitución

| Principio o regla | Aplica | Cómo se cumple |
|---|---|---|
| 1. Aislamiento por tenant garantizado por la base de datos | Sí (R01) | `players` pasa a ser tenant-owned, con `organization_id`, RLS `FORCE` y claves compuestas; el rol de aplicación no puede eludirlo. |
| 2. La aplicación no puede saltarse RLS | Sí (R01) | No se eleva el rol ni se usa `BYPASSRLS`; las pruebas se hacen con el rol de aplicación. |
| 3. Lo publicado es inmutable | Sí (R03) | Un trigger de base de datos impide modificar y borrar resultados confirmados, incluso por SQL directo. |
| 4. Historial de esquema append-only | Sí (R01, R03) | Solo se agregan las migraciones 015 y 016; no se editan las aplicadas. |
| 5. Lo público es una proyección mínima | Sí (R01) | Las proyecciones públicas se mantienen sin documentos ni fechas de nacimiento; las definiciones unen por organización, la vista cruda sigue revocada a `bracket_app`/`PUBLIC` y solo el wrapper filtrado es accesible; la foto depende del consentimiento. |
| 6. Ningún secreto por defecto fuera de desarrollo | Sí (R02) | El perfil de producción sigue exigiendo secretos externos; la CI usa valores dummy y no introduce defaults nuevos. |
| 7. Administración global separada y auditada | Sí (R03) | `platform_admin` tampoco puede modificar ni borrar resultados confirmados. |
| 8. Nada se da por terminado sin verificación | Sí (todas) | R01 y R03 se prueban en CI con PostgreSQL; se ejecutan los checks aplicables y se declara lo que no pudo ejecutarse. |
| 9. El código de desarrollo no llega a producción | Sí (R02) | Producción ejecuta artefactos construidos, no publica puertos y no monta código fuente del host; solo se permiten los montajes de solo lectura de infraestructura de PostgreSQL. |
| §3.1 RLS y migraciones | Sí | `players` nace tenant-owned con RLS y las migraciones nuevas mantienen checksum. |
| §3.4 Seguridad y datos personales | Sí (R01) | Se mantiene el cifrado del documento, la exclusión de columnas sensibles y la no exposición en logs. |
| §3.5 Infraestructura y CI | Sí (R04) | Una sola combinación de versiones, con Python 3.14 y pnpm 12.12.1, y validación del merge de producción. |
| §4 criterios para cambios de BD, backend e infraestructura | Sí | Migraciones nuevas, RLS, FKs compuestas, pruebas, `pytest`, `compileall`, `compose config` y auditorías. |
| §5.2 Evolución de la constitución | Sí (R04) | Enmienda 1.1.0 propia, versionada, con motivo, impacto y revisión humana separada de R01-R03. |
| §6 Definición de cumplimiento | Sí | Revisión humana distinta del autor y CI en verde. |

## Archivos y módulos afectados (previsión para el plan, no normativo)

- **Migración 015 (R01):** `infra/postgres/migrations/015_player_catalog_tenant_isolation.sql`. Agrega `organization_id`, RLS, unicidad por organización, claves compuestas, grants y las dos definiciones que unen `players` más el wrapper de formación; migra y repunta datos existentes y elimina jugadores sin referencia.
- **Migración 016 (R03):** `infra/postgres/migrations/016_confirmed_match_result_immutability.sql`. Función y trigger `BEFORE UPDATE OR DELETE` sobre `matches`, idempotentes.
- **Backend R01:** `backend/app/modules/tournaments/router.py` (alta individual, importación masiva y consultas de rosters); `backend/scripts/seed_demo.py` (inserción de `players` con `organization_id` y deduplicación filtrada por organización); consultas con `JOIN players` en `backend/app/modules/tournaments/router.py` y `backend/app/modules/matches/router.py`; posible helper de catálogo si el plan lo justifica. `backend/app/modules/matches/service.py` no requiere cambios funcionales para R03, pero debe verificarse.
- **Pruebas backend:** nuevos `backend/tests/test_player_catalog_isolation.py`, `backend/tests/test_player_catalog_migration.py` y `backend/tests/test_match_result_immutability.py`, con fixtures de PostgreSQL real, rol administrador para migraciones, rol de aplicación para pruebas y aislamiento por prueba.
- **Infraestructura R02:** `docker-compose.production.yml` (puertos y volúmenes con `!reset`/`!override`, red interna del stack y red externa del proxy unida solo a `web`) y `.github/workflows/ci.yml` para el merge y el servicio PostgreSQL; posible ajuste de `docker-compose.yml` solo si es necesario para la validación.
- **Versiones R04:** `.github/workflows/ci.yml`, `backend/Dockerfile`, `frontend/package.json`, `AGENTS.md`, `README.md` y `docs/constitution.md`. `backend/requirements.txt` no cambia. En `frontend/pnpm-lock.yaml` solo se permite el ajuste del pin del gestor de paquetes en `packageManagerDependencies` a `pnpm@12.12.1`; si la puerta de compatibilidad exige cualquier otro cambio en el lockfile, se detiene y se reporta.
- **Documentación:** `AGENTS.md` y README deben declarar Compose ≥2.24.4, el comando de validación del merge, el prerrequisito de la red externa del proxy y las versiones de referencia.
- **Sin cambios previstos:** frontend funcional, contratos públicos y `.env.example`. `infra/postgres/init/` no se edita salvo que el plan demuestre que la migración 015 no puede aplicarse sobre un volumen limpio; en ese caso se actualiza el init y la migración sigue siendo idempotente. `backend/scripts/seed_demo.py` **sí** está en el alcance de R01.

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| La migración 015 rompe referencias históricas | Pérdida de trazabilidad deportiva | Transacción única, mapeo explícito por organización, repunte de `rosters`, `match_rosters`, alineaciones, eventos y suspensiones, conteos antes/después y pruebas sobre base 014. |
| El aislamiento de `players` rompe consultas legítimas o las proyecciones públicas | Endpoints del Workspace o proyección pública caídos; exposición de la vista cruda | Inventario de todas las uniones con `players` en `v_public_tournament_players` y `v_public_match_lineups_unpublished`, pruebas de `v_public_tournament_players` y `v_public_match_lineups` sin contexto, acceso denegado a la cruda con `bracket_app` y verificación de que el propietario sigue exento de RLS. |
| Duplicar PII por organización aumenta el volumen de datos sensibles | Mayor superficie de privacidad | Duplicar solo lo necesario, conservar cifrado y HMAC, eliminar residuos sin referencias (decisión confirmada) y no registrar PII en logs. |
| La migración elige mal el registro original al dividir | Cambio de `player_id` en datos públicos o históricos | Regla determinista (por ejemplo, referencia más antigua) y repunte completo; probar que no quedan cruces ni huérfanos. |
| Carrera de alta concurrente en la misma organización | Duplicado o pérdida de roster | Clave única por organización, `ON CONFLICT`/reintento controlado y prueba de concurrencia. |
| El seed de desarrollo falla tras 015 | Datos demo roto | Actualizar `seed_demo.py` para insertar `organization_id` y filtrar la deduplicación por organización; ejecutar el seed en la verificación. |
| La sintaxis de Compose no funciona en la versión de CI o del operador | Producción mal configurada o CI roja | Documentar Compose ≥2.24.4, comprobarlo en CI comparando el parche y validar el resultado renderizado, no solo el archivo. |
| La red externa del proxy no existe o queda mal declarada | `web` inaccesible o servicios internos expuestos | Red externa `external: true` con nombre configurable, unida solo a `web`; documentar el prerrequisito y validarlo en CI. |
| La validación del merge exige variables obligatorias | CI no puede ejecutar el check | Variables dummy no secretas y validación de la estructura renderizada. |
| El reset de `volumes` borra el volumen de datos de PostgreSQL | Pérdida de datos | Resetear `volumes` solo en `api`, `worker` y `web`; no tocar `db`, `redis` ni `storage`, y permitir sus montajes de solo lectura de infraestructura. |
| El trigger de R03 bloquea un flujo legítimo | Cierres, avance de llaves o seed fallan | Bloquear solo campos de resultado cuando `OLD.result_confirmed` es verdadero, permitir mismo valor, y probar cierre, avance, bracket reset y seed. |
| Un resultado confirmado erróneo no se puede corregir | Operación deportiva bloqueada | Es el comportamiento buscado por el principio 3; cualquier flujo de corrección será una spec aparte. |
| Python 3.14 o pnpm 12.12.1 no son compatibles con las dependencias fijadas o con el job `security` | CI o imágenes rotas | Puerta de compatibilidad previa que incluye `pip-audit`, `pnpm audit` y Trivy; si falla, detenerse y reportar sin upgrades improvisados de dependencias. |
| El pin del gestor de paquetes en el lockfile choca con la regla de no tocar dependencias | Bloqueo de R04 o cambio no deseado | Permitir solo el ajuste de `packageManagerDependencies` a `pnpm@12.12.1`; cualquier otro cambio del lockfile se detiene y se reporta. |
| La enmienda constitucional se mezcla con cambios funcionales | Incumplimiento de §5.2 | Commit y revisión separados; enmienda 1.1.0 como entregable propio. |
| Dos cambios de esquema compiten por el número de migración | Checksum o despliegue roto | Números asignados: 015 para R01 y 016 para R03; si se fusionan por separado, el orden de aplicación es 015 y luego 016, sin editar migraciones aplicadas. |
| Las pruebas de BD son lentas o inestables en CI | CI lenta o falsos negativos | Servicio PostgreSQL efímero, datos únicos por prueba, limpieza por transacción, ejecución serial y pruebas de migración en base separada. |
| El entorno de implementación no tiene Docker o PostgreSQL | Verificación incompleta | Ejecutar lo posible, declarar lo no ejecutado y no cerrar la spec hasta completar las pruebas requeridas. |

## Verificación esperada

- **Backend unitario:** `cd backend && pytest -q` y `cd backend && python -m compileall -q app`.
- **Backend con PostgreSQL:** job de CI con servicio PostgreSQL 17, rol administrador para inicialización y migraciones, y `RUN_DATABASE_TESTS=1` con `DATABASE_URL` apuntando al rol de aplicación; organizaciones y usuarios creados con `create_organization_with_owner`; pruebas aisladas y ejecución en orden 001-016.
- **Aislamiento R01:** pruebas A/B, consulta directa sin contexto, deduplicación intraorganización, unicidad por organización, claves foráneas cross-tenant, `v_public_tournament_players` y `v_public_match_lineups` devolviendo filas sin contexto y acceso denegado a `v_public_match_lineups_unpublished` con `bracket_app`.
- **Migración R01:** harness con base o esquema aparte en estado 014 (aplicando selectivamente 001-014), jugador compartido por dos organizaciones, aplicación de 015 y 016, verificación de división, repunte de rosters, `match_rosters`, alineaciones, eventos y suspensiones, conteos, ausencia de huérfanos y orden del historial. Repetir sobre volumen limpio.
- **Seed R01/R03:** ejecutar `python -m scripts.seed_demo` tras 015 y comprobar que inserta `organization_id`, deduplica por organización, es idempotente y cierra partidos sin errores.
- **Inmutabilidad R03:** `UPDATE` de cada campo protegido, `DELETE`, mismo valor permitido, `updated_at` permitido, cierre de acta, resolución administrativa, avance de llaves y bracket reset. Aplicar 016 sobre volumen limpio y migrado y reejecutarla.
- **Migraciones:** `sh -n infra/postgres/migrate.sh`; comprobar que no se modificó ninguna migración aplicada y que la secuencia aplicada es 015 y luego 016.
- **Compose desarrollo:** `docker compose config -q`.
- **Compose producción:** `docker compose -f docker-compose.yml -f docker-compose.production.yml config -q` con variables dummy, más aserciones sobre la configuración renderizada: ningún puerto publicado; sin bind mounts de código en `api`, `worker` ni `web`; montajes de solo lectura de `./infra/postgres` aceptados solo en `db`/`db-migrate`; red externa del proxy unida únicamente a `web`; `postgres_data` y los volúmenes de datos conservados; comandos de producción.
- **Compose versión:** `docker compose version` ≥2.24.4 (comparando mayor, menor y parche) y comprobación en CI; documentación de la versión mínima.
- **Versiones R04:** Python 3.14 con `backend/requirements.txt` instalado y tests; Node 24 + pnpm 12.12.1 con `pnpm install --frozen-lockfile` (pin del gestor actualizado y commiteado), `pnpm test`, `pnpm run typecheck` y `pnpm run build`; construcción de imágenes.
- **Documentación:** comprobación textual de que constitución, `AGENTS.md`, README, workflow, Dockerfiles y `packageManager` declaran la misma combinación; cabecera e historial en `1.1.0`; `git status` sin cambios pendientes en esos archivos; ninguna referencia de runtime a Python 3.12, Node 22 o pnpm 12.11.2.
- **Frontend:** `pnpm test`, `pnpm run typecheck` y `pnpm run build` con las versiones objetivo.
- **Seguridad:** job `security` con Python 3.14 y pnpm 12.12.1: `pip-audit -r backend/requirements.txt`, `pnpm audit --prod --audit-level high` y el escaneo Trivy de CI; `pip-audit` está limpio y los hallazgos de `pnpm audit`/Trivy quedaron cubiertos por la excepción §5.1, retirada por la spec 003; la deuda preexistente era de la cadena de producción de Nuxt (herramientas de construcción que `nuxt` declara como dependencias de producción; `pnpm audit --prod` informaba 0 devDependencies), no de `devDependencies`. El job está verde desde el run 39361295825.
- **Limitación conocida:** la auditoría no pudo ejecutar `pytest`, `docker compose config` ni las auditorías por falta de toolchain/Docker. La implementación debe ejecutar estas verificaciones o declarar explícitamente cuáles no pudo ejecutar.

## Criterios de finalización

1. R01 está implementado con `players` tenant-owned, RLS, unicidad por organización, FKs compuestas y migración 015 probada sobre volumen limpio y base 014 sin pérdida de rosters ni histórico; el seed de desarrollo sigue funcionando.
2. La importación masiva, el alta individual y el seed deduplican solo dentro de la organización; ninguna prueba permite obtener PII de otra organización; `v_public_tournament_players` y `v_public_match_lineups` devuelven filas sin contexto de organización sin exponer datos sensibles, y `bracket_app` recibe permiso denegado al consultar la vista cruda `v_public_match_lineups_unpublished`.
3. R02 está implementado: producción no publica ningún puerto, une solo `web` a la red externa del proxy y mantiene el resto en la red interna, no monta código en `api`, `worker` ni `web`, conserva el volumen de PostgreSQL y permite solo los montajes de solo lectura de infraestructura; CI valida el merge con variables dummy.
4. R03 está implementado con la migración 016: `UPDATE` y `DELETE` de resultados confirmados fallan con el rol de aplicación, y cierre, resolución administrativa, avance de llaves, bracket reset y seed siguen funcionando.
5. R01 y R03 tienen pruebas de base de datos ejecutándose en CI con PostgreSQL de servicio, con harness explícito y aisladas entre sí.
6. R04 está implementado con Python 3.14, Node 24 y pnpm 12.12.1 en CI, Dockerfiles, `packageManager`, pin del gestor en `frontend/package.json`, AGENTS, README y constitución, y la puerta de compatibilidad pasó. El job `security` está verde desde el run 39361295825; la deuda preexistente era de la cadena de producción de Nuxt (no de `devDependencies`) y la excepción §5.1 quedó retirada por la spec 003. Si la puerta falla por incompatibilidad de las versiones objetivo, la implementación se detiene, se reporta y la spec no se marca como implementada hasta resolverla.
7. La constitución quedó en `1.1.0` en esta entrega, con cabecera e historial coherentes, enmienda que regulariza §3.5 y separada de R01-R03, con revisión humana; la versión vigente es `1.2.0` por la spec 003.
8. El orden de migraciones aplicadas es 015 y luego 016, sin huecos en el historial, aunque las entregas se fusionen por separado.
9. Los jobs de CI aplicables están en verde; el job `security` está verde desde el run 39361295825 y la excepción §5.1 fue retirada por la spec 003. Las verificaciones no ejecutadas se declaran como tales.
10. La spec queda implementada, validada funcionalmente y cerrada, con la validación documental final completada (2026-10-22), y `MEMORY.md` actualizado al estado real.

## Excepción a la constitución (§5.1)

**Estado: RETIRADA (2026-10-19).** Retirada al quedar el job `security` en verde en `main` (run 39361295825, cuatro jobs) tras la spec 003. Se conserva como registro histórico; ya no está vigente ni cubre ningún hallazgo.

Excepción aprobada por el usuario el 2026-10-19 para cerrar la validación de esta spec sin rebajar ningún principio innegociable.

- **(a) Regla omitida:** §3.4 (las dependencias deben pasar `pip-audit`, `pnpm audit --prod --audit-level high` y el escaneo Trivy de CI), §6 (definición de cumplimiento) y el criterio de §4 “Para todos los cambios: Pasa el job de CI correspondiente (backend, frontend, infrastructure y security)”, en lo relativo a que el job `security` de CI quede en verde. No se omite ninguna otra regla ni criterio.
- **(b) Alcance exacto:** solo el job `security` de CI y solo sus hallazgos preexistentes en la cadena de producción de Nuxt —herramientas de construcción que `nuxt` declara como dependencias de producción—. En el momento de la validación (registro histórico):
  - `pnpm audit`: 14 advisories en el momento de la validación — `simple-git` ×3, `@simple-git/argv-parser` ×1, `shell-quote` ×1, `brace-expansion` ×6, `braces` ×1, `node-forge` ×1 y `serialize-javascript` ×1. Todas pertenecen a la cadena de producción de `nuxt`, en cadenas como `nuxt > @nuxt/devtools > simple-git` y `nuxt > @nuxt/nitro-server > nitropack > ...`; `pnpm audit --prod` informaba **0 devDependencies**. El conteo puede variar con la base de advisories y no debe usarse como criterio fijo.
  - Trivy CRITICAL/HIGH sobre `frontend/pnpm-lock.yaml`: 9 hallazgos en la validación (`simple-git` 3, `@simple-git/argv-parser` 1, `shell-quote` 1 y `brace-expansion` 4). El conteo depende de la base de vulnerabilidades y no debe usarse como criterio fijo.
  - `pip-audit` está limpio y no forma parte de la excepción.
- **(c) Evidencia:** la lista de hallazgos es idéntica entre `64aa384` (HEAD previo a la entrega) y `HEAD`, es decir, son preexistentes y ajenos a R01-R04. No se introdujeron dependencias nuevas ni se degradó ninguna auditoría.
- **(d) Justificación:** es deuda técnica preexistente, fuera del alcance P0 de esta spec. Corregirla exige actualizar dependencias del frontend (por ejemplo `simple-git`, `@nuxt/devtools` y otras dependencias transitivas de `nuxt`), algo expresamente excluido por RF-015 y RNF-009, que prohíben actualizar dependencias o regenerar el lockfile más allá del pin del gestor.
- **(e) Acotación:** la excepción cubría únicamente el job `security` y la lista corregida de la cadena de producción de Nuxt del apartado (b). No se relajó ningún principio innegociable: el aislamiento entre organizaciones (R01), la inmutabilidad de resultados (R03), la privacidad, el RLS ni la validación del merge de producción (R02) siguen plenamente exigidos y verificados.
- **(f) Responsable:** el propietario del producto (el usuario), que aprobó la excepción.
- **(g) Condición de retiro:** una spec aparte que resuelva la deuda de dependencias del frontend. La condición se cumplió con la spec 003 (`specs/003-deuda-dependencias/spec.md`), que dejó el job `security` en verde con el filtro determinista y retiró esta excepción; la evidencia está en `docs/evidencia-spec-003.md` y en el run 39361295825.
- **(h) Aprobación:** revisión humana del usuario, distinta de los agentes autores; la excepción queda registrada en esta spec y no se mezcla con cambios funcionales.

**Cierre (2026-10-19):** run 39361295825, cuatro jobs verdes (`Infrastructure checks`, `Frontend checks`, `Backend tests`, `Dependency and filesystem scan`). Política vigente: filtro determinista `infra/scripts/audit_frontend.py`, sin listas de GHSA; riesgo residual de `braces` y `node-forge` sin parche, revisado en cada actualización de dependencias y en la próxima auditoría técnica, con el propietario del producto como responsable.

## Dudas abiertas

No quedan dudas abiertas. Las decisiones adoptadas son:

1. **R01:** catálogo por organización con RLS; `organization_id` en `players`; unicidad por organización; FKs compuestas; migración 015 que divide registros compartidos, repunta referencias y elimina filas sin referencias (decisión confirmada por el usuario: todo jugador legítimo tiene referencia, así que solo se eliminan residuos); `seed_demo.py` en alcance; deduplicación cross-tenant eliminada.
2. **R02:** producción sin puertos publicados; `web` unido a una red externa de proxy ya existente y configurable, y `api`, `db`, `redis` y `storage` solo en la red interna; sin montajes de código en `api`, `worker` ni `web`; volumen de PostgreSQL intacto; montajes de solo lectura de `./infra/postgres` permitidos en `db`/`db-migrate`; `!reset`/`!override` con Compose ≥2.24.4; validación del merge en CI con variables dummy.
3. **R03:** ningún camino de corrección; trigger `BEFORE UPDATE OR DELETE` sobre resultados confirmados; sin excepción para `platform_admin`; migración 016 idempotente y aplicada después de 015.
4. **R04:** Python 3.14, Node 24 y pnpm **12.12.1** (12.12.2 no existe; publicadas 12.12.0/12.12.1/12.13.0/12.14.0); alineación de todas las fuentes; se permite el ajuste del pin de pnpm en `packageManagerDependencies`, sin tocar dependencias ni el resto del lockfile; puerta de compatibilidad con parada y reporte si falla por incompatibilidad de las versiones objetivo. La deuda preexistente era de la cadena de producción de Nuxt (no de `devDependencies`); la excepción §5.1 quedó retirada por la spec 003 y el job `security` está verde desde el run 39361295825. Enmienda constitucional 1.1.0 que regulariza §3.5, separada y con revisión humana; la versión vigente es 1.2.0 por la spec 003.
5. **Pruebas:** CI con PostgreSQL de servicio para aislamiento R01 e inmutabilidad R03; harness explícito (rol administrador para migraciones, rol de aplicación para tests, organizaciones creadas con `create_organization_with_owner`), datos propios por prueba, pruebas de `v_public_tournament_players` y `v_public_match_lineups`, acceso denegado a la vista cruda y prueba específica de migración desde 014.

**Evidencia de cierre documental (2026-10-22, `main` en `9ad8db1`):** `python3 infra/scripts/verify_version_sources.py --exclude-constitution` → «OK: Python 3.14, Node 24 y pnpm 12.12.1 coinciden en las fuentes verificadas»; `git status --porcelain` sin cambios antes de esta reconciliación documental; ninguna referencia a Python 3.12, Node 22 ni pnpm 12.11.2 en `docs/constitution.md`, `AGENTS.md`, `README.md`, `.github/workflows/ci.yml` ni los Dockerfiles; cabecera e historial de la constitución coherentes en `1.4.0` (la versión avanzó con las specs 003 y 010 sobre la `1.1.0` de esta entrega).
