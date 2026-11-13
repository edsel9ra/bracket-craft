# Plan 034 — Apelaciones y resoluciones de sanciones

Fecha: 2026-11-12. Estado: **aprobado** por el usuario el 2026-11-12, incluidas C1–C5 tal como están. Desarrolla la spec 034 aprobada el 2026-11-12 y la constitución 2.0.0, especialmente §3.6. Fase Plan cerrada; fase actual Tareas. La aprobación permite redactar tareas, no las da por aprobadas ni declara implementado F9.

## 1. Idea central y comprobación contra el código

El expediente es independiente de la sanción y no tiene efecto suspensivo. Las decisiones, sus aplicaciones, las transiciones y las constancias son hechos nuevos. La duración original de `player_suspensions.matches_suspended` nunca se modifica: la duración efectiva se deriva de resoluciones aplicables al partido. La reducción no se implementa relajando la 037. Se mantienen intactas las protecciones de la 016, 009 y `init/03_hardening.sql`, las actas y los cumplimientos históricos.

Revisión estática realizada sobre esta rama, después del cierre de la spec; no es una prueba de ejecución de F9:

| Evidencia actual | Consecuencia para el diseño |
|---|---|
| `infra/postgres/migrations/` termina en 039. | Se propone `040_sanction_appeals.sql`; volver a comprobar el número antes de implementar, sin renumerar migraciones aplicadas. |
| 037, `protect_suspension_columns()`, rechaza cambiar cualquier columna salvo `status`. | Historial de resoluciones y lector efectivo, no UPDATE de duración ni de procedencia. |
| `matches/service.py::_has_suspended_players` exige `status='active'` y compara cumplimientos con `matches_suspended`. `_serve_suspensions` inserta por estado y pasa a `served` usando esa duración original. | Ambos deben cambiar juntos, con lectura temporal común; registrar `appealed` desactivaría indebidamente el bloqueo. |
| 035, `player_suspension_annulments`, exige `version_id` de rectificación y tiene unicidad por sanción. `rectifications/sanctions.py::recalculate_sanctions` escribe allí y pone `cancelled`. | Reutilizar el patrón cancelación + registro y la conservación de cumplimientos, no la tabla para F9: no existe una versión 033 legítima para una resolución F9. |
| `reconcile_sanctions` compara identidad lógica, jugador y motivo; no compara duración y excluye filas `cancelled`. | No confundir duración derivada del acta con duración reducida por F9; una recreación debe dejar trazabilidad y revisión expresa, nunca copiar la resolución anterior. |
| 036 amplía `fn_verify_user_org_membership` para autorizaciones de rectificación mediante contexto local. | Copiar sus comprobaciones y consumo, pero no sus autorizaciones. Se propone alcance más estrecho para F9 (C2), no extender automáticamente la membresía global. |
| `core/locking.py` fija fase → versión → partidos → segmentos → jugadores; `RectificationService._match(lock=True)` bloquea los partidos del torneo ordenados por ID. | Conservar ese orden y añadir sanciones después, sin tomar primero un expediente y después esperar la fase. C3 cubre sanciones organizativas y torneos distintos. |
| `core/roles.py` declara precedencia, no los defaults RBAC. Los defaults están en `role_definitions.system_permissions` y `roles.permissions`; 035 los amplía para owner/administrator. | Declarar las nuevas claves en `roles.py` y poblar defaults por migración, sin atribuir al archivo un registro de permisos que hoy no contiene. |
| `rectifications/notifications.py` registra comunicaciones 033, no una bandeja genérica por destinatario. El worker trata `RECTIFICATION_DECISION_EMAIL` explícitamente y el resto va a Redis. `main.py` relaya al room de toda la organización. | Crear bandeja privada F9 y handlers explícitos: jamás enviar el motivo F9 al dispatcher genérico ni al room de organización. |
| El primer `match_segments` representa el comienzo real; guardar/publicar alineación no valida suspensiones. | Aplicación ligada a apertura, no al horario programado; aviso privado sin bloqueo y revalidación al cierre. |

Son diferencias entre la implementación actual y el comportamiento futuro, no una contradicción que obligue a cambiar los RF aprobados. Las ambigüedades de diseño que quedan se identifican en C1–C5.

## 2. Base de datos — nueva migración 040

### 2.1 Tablas y escritura

Todas las tablas de tenant incluyen `organization_id`, `ENABLE` y `FORCE ROW LEVEL SECURITY`, políticas `USING`/`WITH CHECK`, claves compuestas `(id, organization_id)` y FK compuestas para impedir relaciones cruzadas. `ON DELETE RESTRICT`, grants mínimos a `bracket_app`; sin cascadas que eliminen historial. Evidencia: texto y lista de enlaces opcionales, nunca archivos. Motivo no vacío en cada acto. Los estados SQL pueden usar códigos ingleses con traducción exacta a pendiente/resuelto/retirado/cerrado por rectificación.

| Tabla propuesta | Contenido y protección |
|---|---|
| `sanction_cases` | Tipo `appeal`/`administrative_proposal`, sanción, autor user/member, representación equipo/jugador, motivo y evidencia, fecha, antecedente opcional, huella disciplinaria y resolución efectiva base. Columnas originales inmutables; únicamente `pending → resolved/withdrawn/closed_by_rectification`, con trigger controlado y evento obligatorio en la misma transacción. Índice único parcial `(organization_id, suspension_id) WHERE status='pending'` compartido por ambos tipos. |
| `sanction_case_events` | Append-only: presentación, retirada, cierre por rectificación y constancias de afectación posterior de un resuelto. Actor, instante, motivo, referencia a rectificación/sanción sucesora; no reabre terminales ni modifica decisiones. |
| `sanction_case_decisions` | Append-only, única por expediente, responsable user/member o plataforma, motivo/evidencia, fecha, decisión y valores anteriores/resultantes. Apelación: mantener/anular/reducir; propuesta: aprobar/rechazar la medida inmutable propuesta. Trigger rechaza `decided_by_user_id = submitted_by_user_id`, cualquiera que sea el rol. No se decide sobre estados terminales. |
| `sanction_resolutions` | Append-only, FK a decisión: anular/reducir, duración original, efectiva anterior y nueva, cumplimientos observados, fecha de decisión y base revalidada. Las declaraciones sobre cumplidas se identifican como tales. Mantener/rechazar no crea un cambio de elegibilidad. |
| `sanction_effect_applications` | Append-only, única por resolución: partido e instante efectivos cuando cambia elegibilidad; estado anterior/resultante y duración efectiva aplicada. Decisión y efecto no comparten ficticiamente una misma fecha. No se inserta una aplicación si aún no ha ocurrido el siguiente comienzo elegible. |
| `sanction_match_eligibility` | Snapshot append-only por sanción/partido al primer segmento: duración, resoluciones aplicables, estado y referencia temporal. Conserva la lectura de partidos comenzados aunque después se aplique una reducción/anulación a otro partido. No sustituye ni reescribe alineaciones o cumplimientos. Compatibilidad con partidos ya empezados: §3.3 y C4. |
| `sanction_prejudice_records` | Constancia mínima append-only en el expediente: jugador, partidos afectados acreditados, descripción/motivo, autor, fecha y resolución. No procedimiento de impacto 033, compensación ni crédito. No inferir perjuicio solo por ausencia del jugador. |
| `sanction_platform_authorizations` | Organización, expediente, dueño user/member, administrador, motivo, fecha de concesión, revocación y consumo. Solo INSERT y transición controlada de revocación/consumo desde vacío; no edición del alcance ni reutilización. |
| `sanction_notifications` | Aviso por acto, destinatario y canal (`internal`/`email`), motivo y acto mínimos, referencia al outbox; unicidad por acto/destinatario/canal. Cuerpo inmutable sin evidencia; entrega/estado operativo en registro controlado o en el outbox, no sobrescribiendo el acto. Lectura interna solo por el destinatario actualmente autorizado. |

Los triggers de transición comprobarán que existe el evento/decisión correspondiente al finalizar la transacción (constraint trigger diferible cuando proceda). Ni `UPDATE status` directo ni un INSERT de decisión podrán eludir autor distinto, permisos, alcance, catálogo o estado pendiente. Las funciones de escritura controlada validan el usuario del contexto, nunca confían en un actor que venga del JSON. Los triggers append-only rechazan UPDATE/DELETE incluso si un grant accidental lo permitiera. Esta superficie se somete a C1 antes de implementarse.

La unicidad parcial resuelve carreras entre apelación y propuesta, pero **no** basta para impedir una segunda instancia: bajo bloqueo de sanción se rechaza una nueva presentación si ya hubo una decisión definitiva sobre esa sanción/base. Tras retirada cabe una nueva presentación; tras cierre rectificativo solo presentación manual vinculada sobre la sanción vigente, con permisos actuales. No backfill de expedientes a partir de `appealed`, ni cambio masivo de esos estados históricos.

### 2.2 Duración y anulación sin mutación original

`sanction_appeals/effective.py` será la definición pura de la proyección, con un repositorio que cargue en lote original + decisiones + aplicaciones + cumplimientos. El resultado incluye `original_duration`, `effective_duration`, `served_count`, `remaining=max(0, effective_duration-served_count)`, estado aplicable al partido y efecto aún pendiente. La selección es por orden causal de aplicaciones/decisiones, no solo por un timestamp empatado ni por el último expediente creado.

Una reducción aplicada escribe una nueva duración efectiva; nunca `UPDATE matches_suspended`. Si la duración es menor o igual a lo cumplido, saldo cero y estado cumplido, sin crédito. Anular una sanción activa actualiza únicamente `status='cancelled'` al aplicar el efecto y conserva todos los `player_suspension_serves`. Anular una totalmente cumplida es declarativo sin crédito, sin inventar partido efectivo: registra la anulación y cambia solo el status a `cancelled`, sin cambio de elegibilidad. Las reducciones declarativas sobre cumplidas registran su duración resultante desde la decisión, sin esperar una apertura ni inventar aplicación de elegibilidad. El estado físico es una proyección operativa actual, no la fuente para reconstruir la elegibilidad de un partido anterior.

No insertar F9 en `player_suspension_annulments`: requeriría una versión 033 ficticia o relajar su FK. Para lecturas históricas se combinan sus anulaciones con las aplicaciones F9 conservando el tipo y autoría de cada origen. La 037 permanece íntegra. Alternativa descartada: permitir editar duración y guardar el anterior en JSON; sigue mutando el dato original y deja lectores inconsistentes.

### 2.3 Permisos y RLS de organización/plataforma

Claves propuestas: `VIEW_SANCTION_CASES`, `SUBMIT_SANCTION_APPEALS`, `RESOLVE_SANCTION_CASES`, declaradas en `backend/app/core/roles.py`. La 040 añade las tres a defaults owner/administrator en `role_definitions` y a sus roles existentes mediante operaciones idempotentes como la 035; comprobar también las organizaciones creadas después. Ninguna herencia de cierre, rectificación o resolución de partidos. Resolver permite proponer y decidir propuestas ajenas, no consultar genéricamente sin el permiso de consulta. Las respuestas de escrituras son recibos mínimos; ver un expediente completo requiere consulta, salvo el alcance puntual de plataforma aprobado en la spec.

C1: políticas de expediente/evidencia y escrituras usan membresía real activa y permiso concreto, no basta con que una función genérica acepte una excepción de plataforma 033. Las FK tenant no son sustituto de RLS. Políticas de la bandeja además atan `recipient_user_id` al usuario de sesión. Evidencia no aparece en outbox de avisos, respuestas de bandeja, logs operativos ni mensajes Socket.IO.

Los operadores de alineación/cierre y los aprobadores 033 no reciben consulta F9 por usar la duración efectiva. C1 incluye funciones de lectura operativa mínima por partido/jugador (duración, pendientes y vigencia, sin expediente, motivo ni evidencia), que verifican el permiso operativo y contexto del partido antes de cargar el ledger. El puente de publicación 033 también será una operación controlada: comprobar actor autorizado para esa publicación y evidencia del cambio disciplinario/versionado dentro de la transacción antes de cerrar los expedientes afectados. No conceder UPDATE genérico de expedientes a un aprobador 033 ni aceptar un `version_id` arbitrario como autorización para cerrarlos. Este cierre consecuente no equivale a resolver F9 ni a heredar sus permisos/autorizaciones.

C2: crear funciones F9 propias equivalentes a `rectification_owner`, `rectification_platform_candidate`, `rectification_platform_scopes` y `record_rectification_platform_audit`, más acceso mínimo al contexto de la sanción para decidir. Contexto local `app.sanction_authorization_id`, fijado con `set_config(..., true)` tras `set_rls_context()` dentro de la transacción; jamás `app.rectification_authorization_id`. Scopes válidos solo para el administrador activo indicado, dueño aún activo y owner, organización activa, expediente pendiente concreto, autorización no revocada/consumida; excluir `platform_support`. Revalidar y bloquear autorización, dueño y asignación de rol al ejecutar, no solo al listar.

**Desviación propuesta respecto de copiar literalmente la 036:** no ampliar `fn_verify_user_org_membership()` con otra excepción organizativa general. Las políticas F9 admiten el scope exacto del expediente; para filas existentes necesarias (sanción, metadatos de origen y bloqueos), funciones F9 de acceso/ejecución estrechas validan el mismo scope y devuelven solo esa sanción y contexto mínimo. No habilitan consultas genéricas de toda la organización ni reutilizan las funciones 033. Las funciones privilegiadas imprescindibles siguen el patrón 036: `SECURITY DEFINER`, `search_path=pg_catalog, public`, sin SQL dinámico, REVOKE a PUBLIC, grants explícitos y comprobación de identidad/alcance en cada llamada; ningún privilegio BYPASSRLS para la aplicación. La confirmación C2 debe revisar precisamente estas capacidades; no se presume aprobada por parecerse a la 033.

El consumo y cierre del expediente ocurren después de registrar decisión, efectos, avisos y ambas auditorías, en la misma transacción; no invalidar el scope a mitad de la operación. Si cualquier paso falla se revierte todo, incluido el consumo. Revocación y consumo concurrentes quedan serializados; ninguna autorización se transfiere al expediente sucesor.

### 2.4 Verificación de migración

Probar con rol `bracket_app`, no solo propietario: volumen limpio init + 001–040 y volumen 039 → 040; comprobar checksums de las anteriores, grants, RLS/FORCE, FK cruzadas, triggers, índice parcial, separación de personas y roles nuevos/existentes. Verificar rollback ante decisión/aviso incompletos, y que 016/009/037/03_hardening siguen impidiendo lo mismo. El registro de migración y sus tests será parte del PR A; este borrador no crea SQL.

## 3. Backend y algoritmos

### 3.1 Archivos y responsabilidades

| Parte | Responsabilidad |
|---|---|
| `backend/app/modules/sanction_appeals/{router,schemas,service}.py`, `__init__.py` | Contratos estrictos, bandeja/detalle, presentar/proponer/retirar/decidir; router en `backend/app/main.py`. |
| `sanction_appeals/{effective,repository,platform,notifications}.py` | Dominio puro; lecturas en lote; autorización excepcional propia; payloads mínimos y destinatarios. |
| `backend/app/core/{roles,locking}.py` | Claves RBAC y coordinador C3; preservar precedencia y orden global existente. |
| `matches/service.py`, `matches/router.py` | Elegibilidad al cierre, cumplimientos, apertura y snapshot; endpoint privado de aviso preparatorio. |
| `rectifications/{sanctions,effects,service,platform}.py` | Lectura de base y efecto F9, cierre por rectificación en publicación y adopción del mismo protocolo de bloqueos. |
| `backend/app/core/email.py`, `backend/app/workers/outbox.py` | Correo F9 y handler interno explícitos, reintento del outbox existente. No tocar correo 033 salvo extracción compartida si los tests lo permiten. |

Toda consulta tenant usa SQLAlchemy async y contexto RLS dentro de la transacción, antes de leer. El reloj se lee solo en el borde de servicio; funciones puras reciben `decision_at`, `as_of`, `started_at` y datos ya cargados. Ningún `datetime.now()`, `now()` SQL para decidir reglas, ni reloj en el motor puro. Los defaults de auditoría de la BD no son el algoritmo de elegibilidad.

### 3.2 Inventario completo de lectores encontrado en `backend/app`

| Lector/escritor actual | Tratamiento F9 |
|---|---|
| `MatchService._has_suspended_players` y sus llamadas `_validate_suspensions`/validación del cierre | Usar proyección efectiva para el partido: no comparar solo duración original ni descartar por status global una sanción que regía al comienzo. Mantener exclusión de acta origen y corte de creación. |
| `MatchService._serve_suspensions`, INSERT y UPDATE a `served` | Usar la misma duración/estado por partido, limitar a sanciones aplicables aún pendientes; conservar filas existentes y deduplicación. Refrescar estado actual con última aplicación, sin revivir una cancelada porque un partido anterior acaba después. |
| `MatchService._load_recorded_red_suspensions` | Mantener lectura por existencia sin filtro de estado: deduplica origen, no determina elegibilidad. F9 no debe crear otra sanción por la misma roja. |
| `MatchService._insert_suspensions` | Sigue escribiendo duración original derivada de reglas; no copia reducciones de otro ID ni de expedientes previos. |
| `rectifications/sanctions.py`: `recalculate_sanctions`, `reconcile_sanctions`, `_derive`, `capture_discipline`, `accumulation_impacts` | Separar derivación del acta e identidad original de la proyección F9. Comparar cambios de origen con la base original; la duración efectiva sirve a los efectos y al historial, no a recalcular tarjetas ni a deshacer una reducción. No trasladar resoluciones a sanciones recreadas. |
| `rules_engine/engine.py::evaluate_suspensions` | Produce duración base desde configuración; sigue puro y no lee expedientes. No introducir una regla deportiva constante de F9. |
| `tournaments/routes/matches.py`, comprobación `has_dependencies` | Sigue considerando cualquier sanción/cumplimiento como dependencia, sin filtrar por duración efectiva o estado. No permitir regenerar porque se anuló. |
| Nuevos detalle de sanción/expediente, preview de decisión y aviso preparatorio | Comparten el repositorio de duración efectiva; muestran original/efectiva y aplicación pendiente por separado. |

La búsqueda de `player_suspensions`, `player_suspension_annulments` y `matches_suspended` en `backend/app` dio estos sitios; no se detectó otro lector operativo de duración. Antes de implementar, repetir el inventario sobre main para detectar nuevos lectores. No convertir los lectores públicos a una vista de sanciones: no existe una necesidad pública F9.

### 3.3 RF-030: frontera temporal y aplicación

Propuesta C4: comienzo real = primer segmento persistido, no `match_date` ni estado de la conexión. Para una decisión que cambia elegibilidad, el efecto queda pendiente hasta la primera apertura posterior de un partido aplicable del jugador (plantilla activa y equipos participantes, torneo/ámbito de la sanción); no depende de que esté convocado. Conservar el partido y el instante efectivos. Si se reprograma un partido, no cambia una frontera ya registrada. Torneo de origen archivado no bloquea el efecto en otro torneo permitido por el ámbito.

La apertura del primer segmento, bajo el coordinador C3, aplica las resoluciones pendientes que correspondan y registra snapshots antes de seguir. Capturar el instante una sola vez después de adquirir los bloqueos, tanto en apertura como en decisión; no usar una hora del request anterior a la espera de locks. Desempatar aperturas concurrentes por su orden transaccional, no por comparación de timestamps iguales. Guardar alineación no aplica efectos ni abre partidos. La previsualización de un partido no comenzado incluye el efecto pendiente que se aplicaría si ese fuera el siguiente; lo etiqueta como previsto, nunca como ya aplicado.

Un partido ya comenzado conserva su snapshot; una anulación aplicada después a otro partido no hace desaparecer su comprobación disciplinaria al cerrar. La cuenta de cumplimientos para cierre incluye los computables existentes, sin borrar ninguno y sin generar crédito; la duración y la vigencia temporal vienen de ese partido. El estado físico actual se refresca separadamente sin retroceder sobre una anulación posterior.

Partidos empezados antes de desplegar F9 no tendrán snapshot nuevo: reconstruir con primer segmento, creación original, cumplimientos no anulados y sus fechas, anulaciones 033 y aplicaciones F9. No inventar fechas para estados históricos sin procedencia. C4 exige confirmar la política conservadora para una fila histórica sin prueba temporal suficiente: mantener la restricción acreditada anterior y señalar revisión administrativa, sin activar automáticamente `appealed` ni fabricar una apelación. No desplegar una reconstrucción silenciosa o un backfill supuesto. Declaraciones sobre cumplidas, mantener y rechazo no esperan una apertura ni crean efecto de elegibilidad.

Funciones puras propuestas:

- `effective_sanction(original, resolutions, applications, serves, match_start, as_of)` devuelve duración, pendientes, vigencia y resolución aplicable.
- `plan_application(resolution, match_context, started_at, decision_at)` decide si corresponde aplicar o esperar, sin escribir ni leer reloj.
- `validate_case_action(case, actor, action, effective_base, as_of)` comprueba catálogo, autor distinto, motivo, base y estado.
- `affected_cases(before_base, after_base, cases)` determina los expedientes afectados por rectificación; no usa cambios cosméticos del marcador para cerrar recursos disciplinarios intactos.

### 3.4 Bloqueos, decisión y coordinación 033

C3 propone un advisory lock transaccional por organización como coordinador de escritores disciplinarios, **antes** de los bloqueos existentes: coordinador → fase(s) → versión(es) → partidos por ID → segmentos/jugadores cuando correspondan → sanciones por ID → expediente → autorización. Dentro de cada nivel, orden estable por ID; nunca pedir una fase después de bloquear una sanción. Los orígenes administrativos sin partido no inventan fase: bloquean el contexto de versión que corresponda y la sanción. La serialización por organización cubre ámbitos organizativos que se cumplen en varios torneos y el UPDATE hoy global de `_serve_suspensions`. Este último se acota a IDs afectados y se bloquea en orden, no se deja un UPDATE masivo fuera del protocolo.

El coordinador debe adoptarse en decisiones/retiradas/presentaciones y concesión/revocación de autorizaciones F9, publicación 033 de organización y plataforma, apertura del primer segmento y cierre con cumplimientos. Los cambios de organización activa nunca reutilizan un lock de otro tenant. Se preserva el orden relativo de la 033; se elimina la inversión expediente → fase en los caminos que hoy bloquean primero la solicitud y después `_match`. Probar esas interacciones, no solo dos llamadas F9. Alternativa C3: locks de todos los ámbitos afectados en orden global, más concurrente pero mucho más compleja; no mezclar estrategias parcialmente. La contención es explícita y requiere evaluación antes de aprobar.

Pseudocódigo de decisión (todo en una transacción):

```text
contexto RLS local; validar permiso/scope y obtener IDs sin bloquear en orden inverso
coordinador organización; fase/versiones; partidos; sanciones ordenadas; expediente; autorización
releer estado y permisos; impedir auto-decisión por user_id también en BD
revalidar huella disciplinaria y sanción vigente, no solo versión del marcador
si rectificación cambió/anuló la sanción base:
    insertar cierre rectificativo + motivo/referencia + avisos en outbox
    cambiar pending a closed_by_rectification; no insertar decisión ni consumir autorización
    commit del cierre y devolver resultado de cierre, no excepción que lo revierta
si no: validar decisión y duración <= efectiva actual, sin cambio de ámbito
insertar decisión auditada; si anula/reduce, registrar resolución (aplicación pendiente si cambia elegibilidad)
si hay perjuicio acreditado: insertar constancia mínima sin efecto competitivo
registrar avisos internos/correo y auditoría de organización
si plataforma: registrar también auditoría de plataforma y consumir autorización
cambiar pending a resolved; commit; devolver recibo, sin enviar correo en el request
```

La publicación 033 llama al cierre de pendientes afectados desde su recálculo/efectos, **en esa misma transacción**, al cancelar/recrear o cambiar la base disciplinaria de una sanción. Carga y bloquea sanciones/expedientes afectados en orden. Un fallo de cierre/outbox revierte la publicación entera; nunca dejar cancelada la sanción y pendiente el expediente sobre la base vieja. Rectificación de marcador sin cambio disciplinario no lo cierra. Un expediente ya resuelto conserva su decisión y recibe una constancia de afectación vinculada; la revisión sigue siendo una presentación manual nueva, no una segunda instancia ni una transferencia de efecto/autorización. Si su efecto F9 aún esperaba apertura, la constancia identifica la resolución como no aplicable por rectificación y el lector/aplicador la excluye expresamente, sin borrar la decisión ni aplicarla después sobre una sanción cancelada. Una aplicación ya registrada permanece como historia y no revive una sanción cancelada por 033.

`reconcile_sanctions` no deberá interpretar una reducción F9 como modificación del acta, ni una anulación F9 como permiso para recrear silenciosamente su efecto. Si la 033 realmente recrea una sanción, el nuevo ID empieza con su origen propio, registra el vínculo/afectación del antecedente y respeta la 033; no hereda F9. Las sanciones posteriores confirmadas siguen siendo impactos de la 033, sin modificación automática. Un perjuicio F9 no abre ese procedimiento.

## 4. Interfaz HTTP y contratos

Prefijo `/api/v1`, router nuevo registrado en `main.py`. Organización por contexto validado, no por un `organization_id` manipulable del body. Modelos Pydantic con `ConfigDict(extra='forbid')`, enums cerrados, UUID, paginación acotada, motivos no vacíos y representación validada dentro del tenant. Sin uploads; texto/enlaces opcionales no impiden presentar. No descargar URLs de evidencia desde el servidor; frontend escapa texto y restringe enlaces a esquemas seguros, sin HTML ni secretos en logs.

| Endpoints propuestos | Permiso y contrato |
|---|---|
| `GET /sanctions`, `GET /sanction-cases`, `GET /sanction-cases/{id}` | Consulta F9, lista paginada/filtros y detalle privado con original, efectiva, cumplimientos, autoría, evidencia e historial. Listar sanciones permite presentar sin depender de un acta concreta; no crea sanciones administrativas. |
| `POST /sanctions/{id}/appeals` | Presentar: motivo, representación jugador/equipo, evidencia opcional y antecedente cuando procede. 201 con recibo; ningún efecto suspensivo. |
| `POST /sanctions/{id}/administrative-proposals` | Resolver: medida anular/reducir y duración si reduce, motivo/evidencia. 201; miembro real, nunca plataforma. |
| `POST /sanction-cases/{id}/withdraw` | Autor pendiente y legitimación vigente; motivo obligatorio, evidencia opcional; recibo sin mutar sanción. |
| `GET /sanction-cases/{id}/preview`, `POST /sanction-cases/{id}/decision` | Preview con consulta + resolver; decisión con resolver y autor distinto. Incluye base esperada; apelación mantener/anular/reducir o propuesta aprobar/rechazar, motivo/evidencia y duración solo donde corresponde. Revalidar incluso rechazo/mantener si hubo cambio rectificativo. |
| `GET/POST /sanction-cases/{id}/platform-authorizations`, `DELETE /sanction-cases/{id}/platform-authorizations/{authorization_id}` | Dueño activo para conceder/revocar; concesión con admin identificado y motivo, scope de expediente; listar según facultad de gestión. No reutilizar la 033. |
| `GET /platform/sanction-cases`, `GET /platform/sanction-cases/{id}`, `GET /platform/sanction-cases/{id}/preview`, `POST /platform/sanction-cases/{id}/decision` | Actor platform_admin y autorización F9 propia vigente; lista solo scopes autorizados. Ningún endpoint de presentar/proponer. |
| `GET /matches/{id}/suspension-warnings` | Permiso operativo ya exigido para preparar esa alineación, no acceso implícito al expediente; devuelve jugador afectado y aviso mínimo de restricción aplicable, nunca motivo/evidencia/decisión. Endpoint privado independiente del modelo público. No bloquea guardar/publicar. |
| `GET /sanction-notifications` | Bandeja privada del destinatario, paginada; acto y motivo, sin evidencia. No concede lectura del expediente. |

Errores: 401 sesión; 403 permiso local insuficiente; 404 indistinguible para referencias de otro tenant o scope de plataforma ausente; 409 con códigos estables para expediente ya pendiente, terminal/segunda instancia, base obsoleta o auto-decisión; 422 para contrato inválido, motivo vacío, duración inválida, archivos/campos extra. El cierre rectificativo persistido se devuelve como estado terminal específico, no un 409 que provoque rollback de su auditoría. Reintentos después de commit devuelven el resultado existente para la misma operación identificada; solicitudes incompatibles no crean otro acto ni efectos.

## 5. Avisos, outbox, correo y tiempo real

`sanction_appeals/notifications.py` calcula destinatarios sin duplicados: autor del expediente y miembros activos de la organización con permiso de resolver, no roles por nombre ni jugadores/representantes por esa condición. Registra aviso y outbox por acto/destinatario/canal junto a decisión, retirada o cierre rectificativo; nada se envía antes del commit. Payload con identificadores técnicos mínimos de entrega, destinatario y acto/motivo; no serializar expediente, formulario ni evidencia. El motivo no es un volcado de evidencia.

Eventos nuevos `SANCTION_CASE_NOTICE_EMAIL` y `SANCTION_CASE_NOTICE_INTERNAL`; `workers/outbox.py` los despacha explícitamente antes del fallback a Redis. `core/email.py::send_sanction_case_notice_email` usa SMTP existente como el correo 033. La bandeja interna se materializa de forma idempotente por aviso/outbox, con función acotada al evento reclamado; no con un worker que se haga pasar por cualquier miembro. C1 incluye esa capacidad de entrega. Reutilizar claim/fail/complete y backoff; fallo de SMTP o del handler interno deja aviso reintentable sin revertir acto ni efecto. SMTP es entrega al menos una vez: un fallo tras enviar y antes de completar puede repetir correo, no decisión; no prometer exactly-once externo.

No usar `MATCH_UPDATED`, ni el room de toda la organización, ni el canal público para notificaciones F9. El relay actual difunde al conjunto de miembros: la nueva bandeja se consulta por HTTP autorizado y se refresca al entrar/tras acciones. **Efecto Socket.IO de F9: ninguno en esta propuesta inicial**; no hacer pasar eventos privados por el stream genérico. Así se cumple la notificación interna sin inventar rooms con un modelo de acceso nuevo. La reconexión existente de partidos no cambia; no añadir sanciones a payloads compartidos. C5 plantea la autorización a la hora de entregar si el destinatario perdió acceso desde el registro.

## 6. Frontend y exposición pública

- `frontend/app/pages/workspace/sanction-cases.vue` y detalle `workspace/sanction-cases/[id].vue`: bandeja, filtros, historial de apelación/propuesta, valores original/efectivo, efecto pendiente, cumplimientos y constancia de perjuicio. No botón de segunda instancia; un cierre rectificativo ofrece presentación manual vinculada si existe sanción vigente y permiso.
- Componentes `components/sanctions/` para formulario de apelación/propuesta, decisión/preview, historial y avisos internos. No input de archivos. Representación no crea acceso al jugador/tutor. Estados vacíos, carga, error, conflicto concurrente y lectura sin permiso tienen mensajes ES/EN.
- `frontend/app/pages/admin/sanction-cases.vue` y composable de plataforma: solo autorizaciones F9 vigentes y decidir; nunca proponer. Owner concede/revoca desde Workspace. No mezclar bandejas/autorizaciones de rectificaciones.
- `frontend/app/components/match/MatchLineupSection.vue` y `frontend/app/composables/useMatchLineup.ts`: mostrar aviso disciplinario privado al preparar la alineación; guardar/publicar conserva su contrato sin bloqueo. El aviso no modifica la formación ni evita la validación al cerrar.
- `useSanctionCases.ts`/`usePlatformSanctionCases.ts` encapsulan llamadas mediante `useApi.ts`; invalidar/refrescar detalle, bandeja y avisos tras acciones. `useConfirm` con `singleFlight: true`, títulos/verbos i18n para decidir/retirar/conceder/revocar; nunca confirm nativo ni doble envío.
- Reutilizar tokens, componentes UI e imports explícitos, navegación y permisos del Workspace/admin. Accesibilidad de foco/teclado, aviso no basado solo en color, pantallas móviles. Tests de componentes y comprobación visual durante implementación, no en esta entrega documental.
- **Campos públicos nuevos: ninguno.** No tocar vistas/modelos/rutas públicos ni la matriz 020; no publicar sanción, expediente, duración, estado, responsable, motivo, evidencia o cumplimiento. Documentos/nacimiento siguen excluidos; fotos siguen dependiendo del consentimiento. `PublicLineupModal.vue` no recibe el aviso privado.

## 7. Decisiones justificadas y confirmaciones del usuario

Las elecciones de implementación siguientes fueron aprobadas por el usuario el 2026-11-12, incluidas C1–C5 tal como estaban propuestas. Se conservan su justificación y alternativas; las confirmaciones no autorizan excepciones a principios innegociables.

| ID | Decisión propuesta y razón | Alternativa descartada o pendiente |
|---|---|---|
| D1 | Duración efectiva de resoluciones aplicables + dato original inmutable; anulación en ledger F9 con `cancelled` al efecto. | Relajar la 037 o fabricar una versión 033 para usar `player_suspension_annulments`: mutación o procedencia falsa. |
| D2 | Un único pendiente, terminales cerrados y ledger append-only; estado operativo solo por transición controlada. | Filas totalmente actualizables pierden auditoría; eventos sin índice de pendiente dejan la unicidad a carreras en aplicación. |
| D3 | Derivación deportiva original separada de resolución administrativa; puente explícito 033 cierra pendientes afectados en la misma transacción. | Recalcular y sobrescribir la reducción o trasladarla al nuevo ID neutraliza la decisión silenciosamente. |
| D4 | Nuevas claves en `core/roles.py` y defaults reales en migración para owner/admin. | Suponer que `roles.py` ya contiene defaults o heredar permisos 033 no coincide con el código ni RF-019. |
| D5 | Bandeja privada HTTP y dos handlers outbox explícitos, sin broadcast de Socket.IO. | Room organizativo actual filtra información a miembros no autorizados; realtime por usuario necesitaría otro diseño de autorización no exigido por la spec. |
| **C1 — Decisión que requiere confirmación del usuario** | Aprobar el conjunto de controles BD nuevos: tablas/RLS con permisos específicos y FK tenant, triggers append-only/de transición diferida, anti-auto-decisión y funciones de entrega/escritura de alcance mínimo. Seguridad en BD además del servicio. | Solo validación de servicio/grants amplios no garantiza separación ni aislamiento: se descarta por constitución. Puede ajustarse la implementación de funciones/triggers, no eliminar las garantías. |
| **C2 — Decisión que requiere confirmación del usuario** | Patrón local y verificaciones 036 con funciones/tablas F9, pero sin ampliar la membresía global: acceso mínimo de plataforma a expediente/sanción/contexto mediante políticas y funciones acotadas. Desviación para que una autorización puntual no abra otras lecturas de la organización. | Extender `fn_verify_user_org_membership` como 036 simplifica código pero abre el predicado de todas las políticas que lo consumen; exigiría evaluar y acotar cada tabla afectada. Nunca heredar autorización 033 ni BYPASSRLS. |
| **C3 — Decisión que requiere confirmación del usuario** | Coordinador transaccional por organización antes del orden fase → versión → partidos → sanciones, compartido por F9/033/apertura/cierre. Reduce concurrencia pero evita inversiones entre torneos con sanción organizativa y sirve para linearizar efecto/apertura. | Bloquear todos los ámbitos afectados con locks más finos; más rendimiento, mayor complejidad y riesgo de deadlock. Confirmar contención aceptable y extensión exacta de escritores. |
| **C4 — Decisión que requiere confirmación del usuario** | Identificar siguiente partido por primera apertura real, aplicar ahí con snapshot y registrar partido/instante, no elegir por calendario. Para legado sin prueba temporal, tratamiento conservador y revisión explícita; no reconstrucción inventada. | Aplicar inmediatamente con un único status global cambia partidos en curso; usar `match_date` falla con reprogramaciones. La spec fija no retroactividad, pero no resuelve apertura concurrente ni legado sin fechas. Si se prefiere otra frontera, concretarla sin alterar RF-030. |
| **C5 — Decisión que requiere confirmación del usuario** | Revalidar autorización de destinatario antes de entrega/lectura; si perdió membresía/facultad, retener aviso sin exponer contenido y registrar omisión autorizativa (sin revertir acto). Confirmar política de reintento cuando recupere acceso. | Entregar siempre al snapshot original satisface un conjunto fijo de destinatarios pero puede revelar motivos a alguien ya desautorizado. La spec no fija qué hacer ante pérdida de permiso entre registro y entrega; no decidirlo silenciosamente. |

C1–C5 confirmadas expresamente por el usuario el 2026-11-12. Sus rótulos originales identifican los puntos sometidos a confirmación, no dudas pendientes. Se cierra Plan y se redacta `tasks.md` en fase Tareas; no se crean migraciones, permisos reales ni endpoints hasta aprobar las tareas.

## 8. Estrategia de tests — primero las pruebas

En cada entrega de código, escribir tests y observar rojo antes de implementar, luego verde; no modificar tests existentes para acomodar una regresión. Casos normales, vacíos y errores por contrato, más regresiones 033/009/016/037. PostgreSQL real con `RUN_DATABASE_TESTS=1`, contexto tenant y rol de aplicación; los mocks no demuestran RLS ni concurrencia.

| Grupo propuesto | Casos imprescindibles |
|---|---|
| `backend/tests/test_migration_040.py` | Limpio y migrado; RLS/FORCE, FK cruzadas, permisos defaults de roles existentes y nuevas organizaciones, grants mínimos, append-only, transición/evento obligatorio, INSERT directo auto-decisión rechazado, autorización 033 incapaz de acceder a F9. |
| `test_sanction_effective.py` | Puras con tiempos explícitos: sin resoluciones, mantener/rechazar, reducir mayor/igual/menor que cumplidos, anular activa/cumplida, cero crédito, efectos pendientes, no comenzado/en curso/terminado, empate temporal, scope torneo/organización y legado. La ausencia de datos no crea una apelación. |
| `test_sanction_cases.py` | Ambos orígenes de expediente y tres de sanción; sin caducidad; archivo con efectos externos/declaración; motivo vacío, evidencia ausente admitida, enlaces opcionales, adjunto/campo extra rechazado, no aumento/ámbito nuevo. Retirada solo autor, terminales y segunda instancia rechazados. |
| `test_sanction_security.py`, `test_sanction_platform.py` | Dos organizaciones, referencias cruzadas 404, RBAC separado, autor con ambos permisos/otros roles/autorización no decide; dueño inactivo/rol retirado, autorización revocada/consumida/ajena, platform_support, consumo único y auditoría doble; platform no presenta ni propone. |
| `test_sanction_concurrency.py` | Dos sesiones reales: presentar apelación/propuesta a la vez, dos decisiones, retirada/decisión, revocar/decidir, publicación 033/decisión y apertura/cierre en dos torneos. Assert un único resultado, sin deadlock ni aplicación en un partido ya comenzado. |
| `test_sanction_rectification.py` | Cancelación/recreación cierra pendientes en la transacción 033; marcador sin cambio disciplinario no cierra; resuelto conserva decisión y constancia; no copiar efecto/autorización al sucesor. Una reducción no es deshecha por la comparación con duración original; las posteriores confirmadas siguen intactas. |
| `test_sanction_notifications.py` | Destinatarios deduplicados, solo internos/correo y solo acto/motivo, sin evidencia en payload/log/Redis/público; fallo y reintento, SMTP no configurado, duplicado de entrega no duplica acto; pérdida de autorización según C5. |
| Integración de cierre/apertura | Conservar cumplimientos previos y bloqueo vigente, reducción efectiva al siguiente comienzo, snapshot del partido en curso, cálculo de `served`, avisos sin bloquear guardar/publicar; exclusión de sanciones nacidas después de comenzar. |
| Rollback | Fallo tras decisión, efecto, auditoría o encolado revierte todo; fallo de entrega posterior no revierte nada. Fallo al cerrar expedientes revierte publicación 033 completa. |
| Frontend unit/E2E | Bandeja vacía, detalle con historial/efecto pendiente, formularios sin evidencia y errores, autor no puede decidir, confirmación singleFlight, ES/EN, viewport móvil, admin separado, aviso privado no bloqueante y cero campos F9 en público. E2E con dos usuarios autorizados y dos tenants; no reusar seed como mecanismo productivo. |

Comandos para implementación, desde el directorio indicado; **no ejecutados como pruebas de F9 en esta fase documental**:

```sh
# backend/
pytest -q
RUN_DATABASE_TESTS=1 pytest -q
python -m compileall -q app
# frontend/
pnpm test
pnpm run typecheck
pnpm run lint
pnpm run build
pnpm run typecheck:e2e
pnpm run e2e
# raíz: runner PostgreSQL de AGENTS.md además de estos checks
sh -n infra/postgres/migrate.sh
docker compose config -q
```

El runner `infra/scripts/test_migrate_target.sh` se ejecuta con PostgreSQL y entorno de AGENTS/CI, no se declara suficiente `sh -n` para probar migraciones. Validar también merge dev+prod con variables dummy según AGENTS. Mantener los jobs backend/frontend/infrastructure/security/e2e existentes, auditorías `pip-audit`, frontend con filtro constitucional, Bandit/Trivy/Gitleaks, sin cambiar versiones ni añadir exclusiones. Documentar comandos, screenshots de UI y resultados por RF en la fase Validación. Revisión humana obligatoria.

## 9. Cobertura RF → partes

| RF | Diseño/verificación |
|---|---|
| RF-001–RF-006 | Expediente separado, ausencia de efecto suspensivo, decisión/autorización/auditoría, detalle privado; §2–4 y tests de flujo/rollback. |
| RF-007–RF-009 | Acta original inmutable, sin borrar tarjeta, historial append-only y separación 033; migración/triggers y regresión 009/016. |
| RF-010–RF-012 | Duración efectiva, conservación de cumplimientos, coordinación con recálculo y nueva presentación vinculada; §2.2/3.2–3.4. |
| RF-013 | Constancia mínima de perjuicio sin compensación ni trámite de impacto F9; tabla y test de expediente. |
| RF-014–RF-017 | Lectura por partido, RBAC/RLS/404 y ninguna exposición pública; §2.3/3.2/4/6. |
| RF-018–RF-019 | Membresía de presentación, representación sin acceso y tres facultades nuevas; §2.3 y tests de permisos. |
| RF-020–RF-022 | Catálogo, propuesta pendiente y decisión de otra persona; constraints/triggers y validación de contrato. |
| RF-023–RF-024 | Scopes F9, contexto local, consumo y auditorías organización/plataforma; §2.3 y C2. |
| RF-025 | Cierre por rectificación en publicación y revalidación al decidir; §3.4, rollback y concurrencia. |
| RF-026–RF-027 | Sin caducidad y archivo sin reapertura; flujo e integración de ámbitos. |
| RF-028–RF-029 | Tres orígenes, ambos ámbitos, índice parcial, cuatro estados, retirada y ausencia de segunda instancia; §2.1/4. |
| RF-030–RF-031 | Decisión/efecto separados, apertura/snapshots y avisos sin bloqueo; §3.3/4/6 y C4. |
| RF-032–RF-034 | Avisos internos/correo/outbox, motivo obligatorio, evidencia opcional privada sin archivos; §4–5 y C5. |

RNF-001–RNF-006: historial e integridad transaccional (§2–3), rendimiento con cargas en lote e índices (§3.2), pruebas y verificabilidad (§8), entrega diferida privada (§5), documentación observable (§10). No declarar cumplimiento efectivo hasta ejecutar las pruebas de implementación.

## 10. Partición propuesta en PRs fusionables

Con el plan aprobado, derivar tareas pequeñas por PR en fase Tareas. Dependencias A → B → C → D. Este PR #68 sigue siendo documental; no convierte automáticamente su rama en una entrega funcional.

| PR | Alcance | Condición para fusionar seguro con main |
|---|---|---|
| A — Fundación inerte | 040, modelo/lectores efectivos puros, defaults RBAC y controles BD aprobados, tests de migración y dominio. Sin rutas de escritura ni UI activadas. | Sin resoluciones existentes, lector equivalente al actual; migración aditiva, sin alterar duración/actas/estados históricos. RLS probada con rol de aplicación. No habilitar funciones de escritura incompletas o privilegios provisionales. |
| B — Núcleo operativo completo | Servicio/API de organización y plataforma, coordinación 033, todos los lectores/cierre/apertura, outbox interno/correo y pruebas de rollback/concurrencia. | Activar escritura solo al estar integrados en el mismo PR TODOS los lectores y efectos temporales. No fusionar una API que reduzca/anule con lectores antiguos. El UI aún no enlazado no hace insegura la API: debe ser completa y autorizada por sí misma. |
| C — Workspace | Bandeja/detalle/formularios, gestión owner de autorizaciones, notificaciones privadas y aviso preparatorio, ES/EN, unit y E2E. | Backend B ya disponible; ninguna superficie pública tocada, doble envío impedido y cierre sigue validando. |
| D — Admin y cierre | Pantalla `/admin`, regresión integral multitenant/033 y verificación visual; actualizar README, AGENTS, manual y evidencia por RF. | Backend de plataforma B ya seguro; revisión humana de controles confirmados, CI completa y verificación de todos los RF antes de declarar implementada la spec. |

La 040 se reserva en A solo tras confirmar que sigue libre. Si cada PR necesita ajustes posteriores de esquema, usar 041 y siguientes disponibles, nunca editar la 040 fusionada. Reversión funcional mediante deshabilitar rutas/entrada, no borrar el historial aplicado.

## 11. Configuración y secretos

Sin variables ni dependencias nuevas previstas; SMTP, Redis y outbox existentes. No introducir defaults en código ni credenciales en fixtures de producción. Si la implementación descubre una variable imprescindible, declararla solo en `.env.example` con default de desarrollo y revisar contrato/documentación antes de usarla; no aprobarla implícitamente aquí. No usar seeds productivos ni inventar cuentas de segundo aprobador en producción.

## 12. Verificación de constitución

Tabla de cumplimiento **diseñado**, no evidencia de F9 implementado. Plan aprobado con C1–C5 confirmadas el 2026-11-12; ninguna excepción constitucional solicitada. Las tareas requieren su propia aprobación.

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento tenant en BD | Sí | RLS/FORCE, FK compuestas, scopes mínimos y pruebas con dos organizaciones y rol real; C1/C2 confirmadas. |
| §2.2 Sin BYPASSRLS de aplicación | Sí | No cambiar privilegios del rol; funciones mínimas revisadas, contexto local y tests de acceso directo; C2. |
| §2.3 Publicado inmutable | Sí | Actas/eventos/versiones originales sin UPDATE; no relajar 016/009/037/03_hardening. F9 conserva duración original y usa resolución nueva. |
| §2.4 Historial de esquema append-only | Sí | Nueva 040 si sigue libre; limpio/migrado/checksums; correcciones posteriores solo por nuevas migraciones. |
| §2.5 Público mínimo | Sí | Cero campos/rutas/vistas públicos nuevos; matriz 020, consentimiento de imagen y exclusión de documentos/nacimiento intactos. |
| §2.6 Sin secretos por defecto | Sí | Configuración existente; defaults de desarrollo solo en `.env.example`, sin nuevos secretos. |
| §2.7 Administración global separada/auditada | Sí | API `/api/v1/platform`, UI `/admin`, solo platform_admin autorizado, auditoría doble y consumo puntual. |
| §2.8 Nada terminado sin verificar | Sí | TDD, CI por PR, evidencia por RF y comprobación visual durante implementación. Este documento no declara F9 verificado. |
| §2.9 Desarrollo fuera de producción | Sí | Fixtures/seed solo local/test, sin cuentas ni datos demo productivos. |
| §3.1 Transacción y contexto RLS | Sí | `set_rls_context()` antes de cada consulta tenant; políticas en migración; contexto de autorización local a transacción. |
| §3.2 Módulo, async, reglas y outbox | Sí | Módulo propio/router, SQLAlchemy async, funciones puras; disciplina base sigue configuración del torneo; avisos diferidos vía worker, no SMTP síncrono. |
| §3.3 Frontend | Sí | `useApi.ts`; Workspace con organización activa, admin separado y público sin sesión inalterado. |
| §3.4 Seguridad/configuración/dependencias | Sí | Sin evidencia en logs/avisos/público; sin cambios a cifrado; auditorías constitucionales sin exclusiones ni secretos nuevos. |
| §3.5 Infraestructura/CI | Sí | Python/Node/pnpm/Trivy y lockfile existentes; Compose dev y merge producción con dummy; ningún cambio de CI previsto. |
| §3.6 Rectificación y sanciones | Sí | Apelar no altera; resolución auditada y autor distinto; acta solo por 033, cumplimientos y resultados conservados, revisión expresa y cierre transaccional. |
| §4 Todos: CI verde antes de fusionar | Sí | Backend/frontend/infrastructure/security/e2e, según disparadores reales de CI, sin confundir push de rama con PR. |
| §4 Todos: sin secretos, credenciales ni datos personales en repositorio | Sí | Sin datos reales en fixtures/evidencia documental, ni configuración secreta nueva; revisión de diff y escáner de secretos. |
| §4 Todos: README/AGENTS/contratos y defaults | Sí | Actualizaciones observables y manual en D; cambios técnicos documentados en su propio PR; `.env.example` solo si aparece configuración nueva. |
| §4 Todos: pruebas de comportamiento nuevo/corregido | Sí | §8, TDD y cobertura RF de §9. Esta entrega solo documental se comprueba estructuralmente y con CI; no pretende ejecutar funcionalidad aún inexistente. |
| §4 BD: nueva migración, RLS, limpio/migrado y `sh -n` | Sí | §2.4/8, runner PostgreSQL real y no solo comprobación de sintaxis. |
| §4 Backend: router, RLS, público, pytest/compileall | Sí | §3–4/8; modelos públicos sin ampliación, extra forbid y pruebas SQL reales. |
| §4 Frontend: useApi, test/typecheck/build | Sí | §6/8, más lint, accesibilidad y verificación visual. |
| §4 Infraestructura/despliegue | Verificación de regresión | No cambia Compose; conservar validación dev+prod y rechazo de defaults fuera de desarrollo. |
| §4 Dependencias/lockfiles/auditorías | Sin cambios previstos | No paquetes nuevos; ejecutar seguridad de CI; si se añaden, actualizar lockfiles/auditorías en ese PR. |
| §6 Revisión distinta del autor | Sí | Aprobación humana del plan y C1–C5, revisión de cada PR y evidencia antes de cierre de implementación. |
