# Plan 036 — Partido en vivo

Estado: aprobado

Spec aprobada por el usuario («Apruebo la spec.», 2026-11-13, comunicada tras la ronda 2). Plan completo y C1–C5 aprobados expresamente por el usuario («Apruebo el plan.», 2026-11-13, aprobación comunicada tras su redacción). Se autoriza la fase Tareas, no su ejecución ni la implementación. No contiene implementación ni acredita pruebas funcionales. Numeración de migración comprobada en esta rama: última 055; se propone 056, a reconfirmar antes de implementarla.

## 1. Idea central y evidencia del código

Persistir un borrador privado separado del acta confirmada y un reloj referenciado por tiempo del servidor; no escribir incidencias provisionales en `match_events`. Servir el detalle por una lectura nueva con permiso propio; transportar solo invalidaciones dirigidas mediante 035. Consolidar el conjunto revisado dentro de la transacción existente de cierre, conservando sus bloqueos, reglas, efectos y rectificación posterior.

### Hallazgos que condicionan el diseño

| Código inspeccionado | Consecuencia |
|---|---|
| `backend/app/modules/matches/service.py`, `CloseMatchReportService.execute`, `load_report_payload_snapshot`, `validate_report_payload`, `_persist_events` | El cierre abre su propia transacción, toma disciplina → fase/versión → destinos → partido → segmento → jugadores y aplica validaciones, contadores, sanciones, clasificación, avance, auditoría y outbox. No llamarlo desde otra transacción ni duplicarlo en un cierre paralelo. `validate_report_payload` ya recibe el tiempo como argumento. |
| `matches/router.py`, `_load_operation_match`, `get_match_operation`; `core/permissions.py`, `require_permission` | La lectura de operación usa `require_operation_permission=False`; no equivale a lectura del nuevo borrador. El permiso con `match_id` admite una vía de dueño/administrador/operador o asignación para otros roles con permiso, dentro de la organización. Reutilizar esta semántica, sin endurecer GET operation ni dar escritura a todo miembro. |
| `frontend/app/composables/useMatchEvents.ts`, `useMatchEventsDraft.ts`, `useMatchClose.ts` | El borrador actual es local y se envía como `events` al cerrar. No hay borrador F1 persistido que se pueda reutilizar tal cual. Separar ambos modos; nunca importar o enviar automáticamente una copia local antigua sobre un borrador compartido. |
| `core/realtime_policy.py`, `CATALOG`, `resolve_event_references`; `core/realtime_authorization.py`, `evaluate_batch`; migración 055, `authorize_realtime_recipients` | La función SQL, no solo el clasificador Python, cierra los nombres y exige versión para variantes organizativas actuales. No admite el evento F1 nuevo. La adaptación debe cubrir ambos lados en 056; modificar solo `ReadRule.permission` no filtraría la entrega real, cuyo adaptador usa SQL. |
| `core/realtime_delivery.py`, `PrivateDelivery.deliver/control/recover` | Ya existen agrupación por principal, lotes de 256, corte temporal, suspensión fail-closed, generaciones y RESYNC dirigido. Reutilizarlos; no crear otro relay ni caché de permisos. |
| `app/main.py`, `emit_domain_event`, `PUBLIC_REALTIME_EVENTS` | Los tres nombres públicos actuales se emiten al room de torneo si `scope != organization`. No usar `MATCH_UPDATED` para transportar borradores nuevos ni confiar solo en su nombre para hacerlos privados. |
| `modules/tournaments/routes/public.py`, `public_matches`; `schemas.py`, `PublicMatchResponse`; migración 035, `v_public_matches` | La vista excluye suspendidos. El modelo exige metadatos de fase y añade campos por defecto, y la ruta carga alineaciones. Un objeto de 14 campos no puede atravesar este modelo sin ampliarse o fallar. Usar un modelo específico y una unión explícita, sin rellenar campos nulos adicionales. Mantener las vistas de estadísticas/acta vigente fuera del borrador. |
| `frontend/app/pages/tournaments/[id].vue`, `matchesForStage`, `loadCombinationFirstPage`, `formatScore` | La pantalla agrupa por `stage_id/group_id` y usa campos que no existen en la proyección del suspendido. Requiere adaptación real de agrupación/renderizado, no solo añadir un reloj. |
| `core/outbox.py`, `enqueue_outbox`; `workers/outbox.py`, `process_once` | Se conserva la escritura outbox en la transacción y publicación Redis con reintentos/deduplicación. F9 ya usa handlers explícitos antes del publisher general; no cambiar esa exclusión. |

Estas diferencias son carencias esperadas de F1, no contradicciones que obliguen a enmendar la spec o la constitución. Sí sería contradictorio reutilizar la lectura amplia de operación para revelar el nuevo borrador, introducirlo en estadísticas antes del cierre o rellenar el suspendido con todo `PublicMatchResponse`.

## 2. Decisiones técnicas confirmadas

El usuario confirmó C1–C5 tal como estaban recomendadas al aprobar el plan («Apruebo el plan.», 2026-11-13). Las alternativas se conservan como justificación histórica, no como opciones abiertas.

| ID | Recomendación | Alternativa descartada y motivo |
|---|---|---|
| **C1 — Persistencia y reloj** | Tablas tenant separadas para estado/eventos provisionales; reloj anclado a instante UTC del servidor con acumulado en microsegundos y revisión optimista. Una observación calcula segundos, no escribe un tick. | Añadir eventos provisionales a `match_events` y ejecutar un proceso de ticks: arriesga efectos deportivos prematuros, más escrituras y mayor complejidad de recuperación. |
| **C2 — Revisión y cierre** | Recibo de revisión persistido y ligado a usuario/sesión, revisión de contenido y resultado completo; ampliar el cierre existente para consumir el borrador del servidor dentro de su misma transacción. | Aceptar el array reenviado por el navegador o crear un segundo cierre: permite divergencia/omisiones y duplica invariantes y orden de bloqueo. Un simple número de revisión sin el resultado revisado tampoco prueba la revisión del conjunto a confirmar. |
| **C3 — Avisos y autorización** | Dos nombres nuevos: `MATCH_LIVE_UPDATED` privado y `MATCH_LIVE_PUBLIC_UPDATED` público; invalidaciones de tres identificadores. Ampliar 055 mediante 056 y reutilizar entrega dirigida/RESYNC. | Reutilizar `MATCH_UPDATED` o emitir al room organizativo: confunde reglas de lectura antiguas con borradores y crea riesgo de fuga. Una llamada SQL por socket pierde el batching ya verificado. |
| **C4 — Contrato público** | Unión de modelos por estado en la ruta existente; suspendido con exactamente 14 claves. Nueva vista pública acotada para F1, sin cambiar las vistas de resultados/estadísticas. Renderizar suspendidos en tarjetas mínimas; contexto de filtros fuera del objeto recibido. | Añadir valores nulos a `PublicMatchResponse`, o una segunda ruta que deje suspendidos ausentes del listado: la primera viola la lista cerrada, la segunda fragmenta la matriz aprobada y obliga a combinar paginaciones. |
| **C5 — Integración incremental** | Tres PRs secuenciales: fundación inerte; backend completo con autorización/público/cierre y consumidores compatibles; interfaz y aceptación. Ningún productor F1 hasta que todas sus lecturas y consumidores estén preparados en el mismo PR. | Habilitar captura antes de su filtro o dejar público/consumidores para otro PR: un commit intermedio podría filtrar datos o dejar vistas activas incoherentes. Un PR único es posible, pero dificulta aislar migración, contratos y UX. |

## 3. Archivos y responsabilidades previstos

Los nombres de archivos nuevos son propuestas de Plan; no se crean en esta fase.

| Archivos | Responsabilidad y RF |
|---|---|
| `infra/postgres/migrations/056_live_match_operation.sql` (nuevo) | Tablas, RLS, integridad, permisos, proyección F1 y ampliación invocadora de autorización. RF-008, 012–016, 023–031. |
| `backend/app/modules/matches/live_policy.py` (nuevo) | Funciones puras de reloj/transiciones, score provisional y revisión de contenido. RF-001–011, 019–025, 029–030. |
| `backend/app/modules/matches/live_schemas.py`, `live_service.py`, `live_router.py` (nuevos) | Contratos estrictos, lecturas y comandos transaccionales; recibos, idempotencia, errores saneados y auditoría mínima. RF-001–008, 011–012, 019–026, 029–031. Incluir router en el módulo `matches/router.py`, ya registrado en `app/main.py`. |
| `backend/app/modules/matches/service.py`, `schemas.py`, `router.py` | Punto interno de consolidación en cierre; compatibilidad de DTO clásico; coordinación de segmentos con estado/reloj F1, sin cambiar permisos de lecturas/segmentos existentes. RF-003, 019–025, 029. |
| `backend/app/core/realtime_policy.py`, `realtime_authorization.py`, `app/main.py` | Catálogo nuevo, adaptación del evento SQL, validación del carril público nuevo; reutilizar `realtime_delivery.py` sin rediseñarlo. RF-012–018, 027. |
| `backend/app/modules/tournaments/routes/public.py`, `schemas.py` | Unión por estado, serialización exacta y sin alineaciones para suspendidos; filtros/orden/paginación antes de serializar. RF-009–010, 028. |
| `frontend/app/composables/useMatchLive.ts` (nuevo), `useMatchOperation.ts`, `useMatchClose.ts`, `useMatchEvents.ts`, `useMatchEventsDraft.ts` | Borrador compartido separado del clásico, permisos, revisión completa y conflicto explícito; toda llamada mediante `useApi`. RF-004–007, 012, 016–024. |
| `frontend/app/composables/useRealtime.ts`, `utils/realtimeDispatch.ts`, `utils/realtimeReload.ts`, `types/` pertinentes | Suscribir los nombres nuevos en el único dispatcher; un coordinador por contexto, deduplicación y refetch autorizado, sin remontar. RF-013–018. |
| `frontend/app/pages/workspace/matches/[id].vue`, `components/match/` | Controles iniciar/suspender/reanudar/reloj, editor compartido, revisión de cierre y lector sin escritura; ES/EN, teclado, confirmación single-flight. RF-001–007, 019–024, 029–030; RNF-005. |
| `frontend/app/pages/tournaments/[id].vue`, componentes públicos afectados y tipos/i18n | Tarjeta mínima, reloj provisional/desactualizado y unión de respuestas sin campos supuestos. RF-009–011, 017–018, 028. |
| `backend/tests/test_match_live_*.py`, `test_migration_056.py` (nuevos), suites 017/033/035 y públicas existentes | Dominio puro, contratos, permisos, concurrencia, migración, cierre y distribución real. Todos los RF según §9. |
| `frontend/tests/`, `frontend/e2e/private-realtime.spec.ts`, escenarios públicos y de operación | Normal/vacío/error, edición no perdida, reloj con tiempo inyectado y dos receptores reales. RF-001–031. |
| `README.md`, `AGENTS.md`, `docs/manual-usuario.md`, 020 y 036 (`tasks.md`/`verificacion.md` cuando se autoricen), `MEMORY.md` | Matriz, permisos, operaciones, despliegue, evidencias y aceptación. No cambiar el estado de implementada antes de validación y aceptación. |

No se prevén dependencias, secretos ni variables de entorno nuevos. Reutilizar auth, CSRF, `useConfirm`, auditoría, outbox, worker y transporte existentes. No se crea un módulo de plataforma ni se amplía F9/F13.

## 4. Base de datos — propuesta 056

### Desviación autorizada durante B1: migración 058

El usuario aprobó el **2026-11-14** la **Opción 1** para el hallazgo 1 de Review del PR #82: `058_live_player_eligibility.sql`, siguiente número libre confirmado. Con planillas cargadas, capturar con OPERATE sin lectura de sanciones llegaba a la función protegida de 042 y fallaba con SANCTION_OPERATION_DENIED. RF-007 exige validar la elegibilidad al capturar, no diferirla al cierre. 042, 056, 057, permisos HTTP y lecturas VIEW_SANCTION_CASES permanecen intactos.

La función `match_live_ineligible_players(match, players, as_of)` devuelve únicamente los IDs sin duplicados de los jugadores solicitados no elegibles, sin hechos, motivos, duraciones ni historial. Recibe el instante del servidor; por defecto usa statement_timestamp. Su autorización reutiliza match_live_has_permission de 056 para OPERATE_MATCH_LIVE: dueño/administrador/operador en la organización y los demás solo con asignación vigente. Comprueba existencia del partido dentro del tenant actual y restringe cada lectura del ledger a esa organización y al alcance deportivo del partido; un match ajeno o permiso ausente produce la misma denegación.

SECURITY DEFINER es imprescindible para calcular sin conceder al invocador lectura de historial protegido por RLS F9; no existe una función invocadora autorizada para ese actor. Se fija search_path=pg_catalog,public, se califican las tablas, se revoca PUBLIC y se concede EXECUTE solo a bracket_app. No se añade BYPASSRLS ni privilegios de tabla ni se relajan políticas RLS. Alternativas descartadas: ampliar 042 o conceder lectura disciplinaria hereda detalle no autorizado; omitir/diferir la comprobación incumple RF-007.

La captura usa siempre esta proyección mínima y entrega el booleano precalculado al cargador compartido; cierre/review conservan por defecto load_effective_sanctions. Python project_fact no puede ejecutarse en PL/pgSQL sin otra dependencia/lenguaje: la proyección SQL reproduce solo su resultado blocking, y se contrasta con el cálculo existente sobre estados, cumplimientos anulados/vigentes, resoluciones pendientes/aplicadas/excluidas, snapshots y límites temporales del primer segmento. No se duplica la validación deportiva general ni se expone un nuevo router o productor.

Tests: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_058.py tests/test_match_live_review_regressions.py`; el rojo OPERATE-only queda incorporado al repositorio. Migrador real en limpio 001→058 e incremental 057→058 con dos tenants, datos anteriores intactos y 58 checksums estables al reejecutar. El runner no cambia la contraseña de bracket_app; si se usa test_migrate_target.sh, restaurar el rol desde la configuración existente antes de ejecutar suites compartidas.

### Desviación autorizada durante B1: migración 057

El usuario aprobó el 2026-11-14 «Opción 1: migración 057 mínima (recomendada)», incluida en B1. La reproducción con PostgreSQL demostró que CLOSE sin VIEW ni OPERATE supera la autorización existente de segmentos, pero 056 impide interrumpir un segmento con reloj corriendo y también impide pausarlo con esos permisos. T33 no puede cumplirse endureciendo los permisos HTTP. 056 queda intacta.

057 permite exclusivamente materializar y pausar automáticamente la referencia running al pasar su segmento activo a interrupted/completed, en la misma sentencia/transacción autorizada con CLOSE_MATCH_REPORT. Funciones SECURITY INVOKER y RLS vigente; ningún SECURITY DEFINER, BYPASSRLS, permiso nuevo ni lectura HTTP. La excepción requiere ejecución anidada de trigger, segmento ya cerrado/interrumpido, actor vigente y diferencia exacta de reloj/revisión/metadatos, preservando contenido, marcador y congelación. Una pausa directa o cualquier otra edición sigue requiriendo OPERATE; no se usa un flag GUC falsificable. Tests rojo/verde, negativos tenant/operación y cadena limpia/incremental/idempotente en `test_migration_057.py`.

### Tablas e integridad

- `match_live_state`: clave `(match_id, organization_id)` con FK compuesta a partido/tenant; `revision` para comandos, `content_revision` para el conjunto de hechos; marcador provisional derivado, referencia de segmento nullable, `clock_state`, `clock_elapsed_us >= 0`, `clock_anchor_at` UTC nullable, inicialización/finalización, responsable y momento. Sin referencia: segmento/tiempo públicos nulos y `not_started`. `running` exige segmento activo y anchor; `paused` no acumula. La observación no incrementa revisiones. No reutilizar marcadores confirmados de `matches` para persistir el provisional.
- `match_live_events`: identidad estable `client_event_id`, FK a estado y a segmento/equipo/jugadores con organización compatible; payload con el catálogo y estructura de `MatchEventPayload`, orden estable y retirada explícita. Unicidad `(organization_id, match_id, client_event_id)`. No crear copias confirmadas hasta consolidar; máximo vigente de 500 hechos según `CloseMatchReportDTO`. Los detalles son privados, no mensajes técnicos.
- `match_live_commands`: identificador UUID por partido, actor/sesión, hash canónico de petición, revisión resultante y tipo/fecha de acción. Unicidad por partido/comando; reutilizar un ID con otro cuerpo produce conflicto. Permite recuperar aceptación después de perder una respuesta sin repetir captura ni corrección. No guardar credenciales ni cuerpos en logs.
- `match_live_reviews`: recibo UUID, organización/partido, usuario/sesión, `content_revision`, huella del conjunto vigente ordenado, resultado/resolución completos revisados y fecha. Solo para lector autorizado con permiso actual de cierre. No almacena un acta confirmada ni concede permisos por conocer el UUID. Recibos históricos no se reescriben; dejan de ser utilizables si cambia contenido/resultado o identidad/sesión.
- Trazabilidad mediante auditoría existente para transición/reloj/alta/corrección/retirada/cierre: acción, identificadores, actor y fecha; nunca detalle deportivo personal en logs técnicos. El borrador retirado sigue siendo privado; no se introduce un historial público ni nueva política de retención.
- Restricciones y triggers nuevos impiden escrituras provisionales sobre partidos confirmados/terminales, transición incoherente con `matches.status`, referencias cross-tenant y modificación arbitraria por un mero cerrador. No se modifica ni relaja el trigger de actas confirmadas. El camino de consolidación congela el estado dentro de la misma transacción antes de confirmar el partido; rollback restaura todo.

### RLS y permisos

Las cuatro tablas nacen con RLS habilitado y políticas por organización y membresía vigente, más FK compuestas para el partido. La aplicación sigue sin superusuario/BYPASSRLS. El aislamiento tenant no depende de filtrar en Python. Siguiendo el modelo actual, RBAC de lectura/escritura se comprueba en los servicios HTTP y en la función SQL de entrega; RLS no se presenta como una implementación adicional de todo RBAC intratenant. Helpers SQL `SECURITY INVOKER`, `search_path` fijado y revocación de EXECUTE a PUBLIC; no aceptar usuario/organización proporcionados por el navegador como identidad efectiva.

Proponer `VIEW_MATCH_LIVE_DRAFT` y `OPERATE_MATCH_LIVE`, independientes. Lectura HTTP de estado/eventos: VIEW + vía organizativa o asignación del partido. Escritura operativa: OPERATE + la misma regla de alcance; las consultas internas necesarias para validar un comando no son una respuesta de lectura al actor. No exigir VIEW implícitamente para ejecutar ese comando ni devolver sus hechos como resultado. Recibos: VIEW + CLOSE actuales, restringidos al actor/sesión; comandos: resultado mínimo del propio actor, no acceso lateral a otro borrador. Cierre: CLOSE + VIEW para consumir F1, sin exigir OPERATE; los triggers distinguen congelación de cierre de una edición ordinaria. Cada comprobación se revalida dentro de la transacción con `set_rls_context()` antes de consultas tenant. GRANT de tablas limitado a las operaciones necesarias del rol aplicativo, sin DELETE de recibos/comandos ni concesiones a PUBLIC.

056 añade ambas concesiones idempotentemente a `role_definitions.system_permissions` y roles existentes de dueño/administrador/operador/árbitro; no al observador. Reutilizar el patrón de actualización de permisos de 035 y creación de roles desde definiciones. No reemplazar listas existentes ni alterar CLOSE/lectura de operation/033. Roles personalizados reciben solo concesiones explícitas. Probar múltiples roles: cualquier vía válida de la organización sirve, sin exigir asignación a dueño/administrador/operador.

### Función de entrega y vistas

En 056, `CREATE OR REPLACE authorize_realtime_recipients` conserva firma, SECURITY INVOKER, lotes ≤256, aislamiento por candidato, tiempo de evaluación, sesión/membresía, restauración de contexto y ramas antiguas de 055. Añade una rama cerrada para `MATCH_LIVE_UPDATED`, `scope=organization`, sin `version_id`: comprobar recurso, VIEW y asignación con la misma regla SQL de GET live. No interpretar cualquier `scope=organization` como lectura de versión. Denegación ante referencias inválidas; errores/filas ausentes mantienen INDETERMINATE. No editar 055.

Crear una proyección F1 con `security_barrier`, las condiciones de visibilidad pública de `v_public_matches` (organización activa, torneo visible, versión publicada actual, equipos del tenant) y estado `live/suspended` no confirmado. Separar una vista interna de selección (fase/grupo/orden para filtros) de la salida mínima de 14 campos. Se revisan GRANT SELECT únicamente a `bracket_app` y exclusión de PUBLIC conforme al patrón existente de vistas públicas; ningún permiso directo de lectura anónima a tablas tenant. No sustituir las vistas de eventos, estadísticas ni acta rectificada: no deben consumir provisionalidad.

### Verificación y despliegue

`test_migration_056.py` debe levantar cadena limpia 001→056 y volumen equivalente a 055 con datos de dos tenants→056; ejecutar de nuevo el migrador y comprobar idempotencia/checksums. Usar el rol aplicativo para pruebas HTTP/SQL/RLS, administrador solo para crear bases y migrar. Verificar claves compuestas, políticas, restricciones, GRANT/REVOKE, helpers invocadores, roles viejos/nuevos y no duplicación de permisos. Probar que 056 no cambia resultados confirmados ni las decisiones 055 antiguas. Incluir `infra/scripts/test_migrate_target.sh` y `sh -n infra/postgres/migrate.sh`.

Orden: desplegar 056 inerte antes del backend productor; mantener API y worker antiguos compatibles durante esa fase. El PR B requiere una ventana coordinada de suspensión de escrituras: drenar y detener todos los procesos API/relay antiguos, desplegar backend y consumidores compatibles, verificar versiones y después reabrir tráfico productor. No se promete rolling deploy mixto ni cero interrupción sin un mecanismo adicional aprobado; no hay flag nuevo oculto en el diseño. Un rollback al backend anterior tras crear partidos F1 no es seguro: congelar captura, mantener lecturas del backend compatible y aplicar corrección hacia delante; nunca cerrar un borrador con el cliente clásico ni borrar columnas para volver atrás. Documentar y ensayar este límite, no prometer rollback transparente.

## 5. Funciones puras y pseudocódigo

### Reloj

`observe_clock(reference, observed_at)` y `reduce_clock(reference, command, accepted_at, segment_facts)` no consultan BD, reloj global ni red. Fechas UTC aware recibidas como parámetros, delta entero en microsegundos, sin pérdida por redondear cada pausa. `clock_observed_at` es la observación del servidor. Adaptadores obtienen un instante de PostgreSQL después de adquirir bloqueos; frontend recibe referencia y base de observación y usa un `now` inyectable solo para presentación, nunca como aceptación deportiva.

```text
observe(reference, now):
  si sin referencia: devolver segmento=null, segundos=null, estado=not_started
  elapsed = acumulado_us
  si running: elapsed += max(0, now - anchor_at) en microsegundos
  devolver floor(elapsed / 1_000_000), segmento, estado, observed_at=now

control(reference, command, now, match, active_segment):
  exigir live, permiso vigente, revisión esperada y segmento válido
  pause: materializar elapsed_us en now; quitar anchor; estado=paused
  start/resume_clock: exigir segmento activo; anchor=now; estado=running
  correct: reemplazar acumulado validado; si running, reanclar en now
  no tocar minutos/added_minute ni content_revision de hechos
  auditar comando y aumentar revision, no generar ticks persistidos
```

Si un segmento se completa/interrumpe por las rutas existentes, materializar y pausar el reloj F1 en su misma transacción. Crear uno nuevo no arranca implícitamente su reloj; su referencia comienza en cero al iniciarla expresamente, conservando la identificación de hechos de segmentos anteriores. La suspensión del partido no completa ni interrumpe por sí sola un segmento 017. Durante `suspended` no se admite control/corrección del reloj por fuera de la transición; se mantiene congelado.

### Estados, comandos y concurrencia

`decide_live_transition(current, command, facts, accepted_at)`, `derive_provisional_score(events, rules, teams)` y `review_fingerprint(events, result, content_revision)` son puras. Reutilizar catálogo 015, reglas configuradas, `replay_report_state`, validadores de minutos/sustituciones y coherencia marcador/eventos existentes; no duplicar constantes deportivas. Los minutos de captura se introducen explícitamente, no se reescriben desde el reloj. Un catálogo inválido nunca se degrada a texto libre.

```text
comando(context, match, command_id, expected_revision, body):
  transacción + contexto RLS + bloqueos compatibles con cierre/segmentos
  revalidar identidad, membresía, permiso y partido
  si command_id ya aceptado con mismo hash: devolver aceptación mínima vigente
  si command_id existe con otro hash: 409; no mutar
  exigir revision == expected_revision; conflicto => 409 sin sobrescribir
  start: scheduled + versión publicada + equipos válidos => live
  suspend: live => materializar reloj en now, pausar si iniciado, estado=suspended
  resume: suspended => live, misma referencia pausada (o not_started)
  captura/corrección/retirada/reloj: solo live
  terminal/cancelado/confirmado/versión no operable => rechazar
  validar hechos y recalcular score antes de aceptar cambios
  persistir estado, comando, auditoría e invalidaciones en outbox
  aumentar content_revision solo al cambiar hechos/resultado a confirmar
  commit indivisible; devolver revisión/ack, no detalle si falta VIEW
```

Todas las mutaciones F1 y las rutas de segmentos que interactúan con F1 toman primero los bloqueos existentes necesarios, incluido el partido antes de su estado; no invertir el orden al integrar cierre. Identidad/ámbito se resuelven antes de filtrar permisos para conservar 404 ajeno/inexistente. Sesión y autorización se revalidan incluso en retries; un ID de comando no es credencial.

### Revisión y consolidación

```text
review(context, candidate_result):
  exigir VIEW y autorización de cierre actual; lectura coherente del conjunto vigente
  construir DTO canónico con TODOS los hechos aceptados no retirados del servidor
  validar con reglas/cierre actuales; mostrar conjunto completo y efectos a confirmar
  registrar recibo ligado a actor/sesión/content_revision/huella/resultado completo

close(context, body, optional_review_id):
  abrir UNA transacción en CloseMatchReportService.execute como hoy
  contexto RLS; disciplina → fase/versión → destinos → partido → segmento → jugadores
  comprobar CLOSE actual y estado/versión/reglas según orden de validación existente
  si NO hay estado F1: mantener contrato y camino clásico sin requisitos nuevos
  si hay estado F1:
    exigir VIEW actual y recibo de este actor/sesión y partido
    comparar content_revision, huella y resultado completo con lo revisado
    rechazar mezcla de events del navegador, subconjuntos y recibo obsoleto
    construir DTO con conjunto vigente completo del servidor
  ejecutar validaciones/replay/cálculo actuales, incluido borrador vacío válido
  persistir hechos confirmados exactamente una vez con sus identidades estables
  congelar F1 y detener reloj sin convertirlo en dato confirmado adicional
  confirmar acta, contadores, sanciones, clasificación, avance, auditoría y outbox actuales
  commit; fallo en cualquier punto revierte también congelación y deja borrador privado
```

Refactorizar un punto interno del servicio, no llamar `execute` bajo otro `begin`. El DTO clásico conserva `extra=forbid`; añadir explícitamente `live_review_id` opcional y validación condicional: para F1, datos de hechos proceden del servidor, no del array por defecto vacío. Error aditivo `LIVE_REVIEW_REQUIRED/STALE` (409) sin cerrar nada si un cliente clásico intenta cerrar un partido F1. No adelantar el cambio a confirmación a un endpoint distinto. Cambiar solo reloj/referencia no invalida revisión; modificar hechos o resultado sí. Suspensión/terminal/permiso retirado impiden cierre aunque haya recibo válido. Tras cerrar, toda corrección corresponde exclusivamente a 033.

## 6. Endpoints, contratos y pantallas

Rutas propuestas bajo `/matches/{match_id}`; modelos estrictos y errores conforme al contrato actual (`422` saneado, `409` con `code` y detail de cadena, `403` por permiso, `404` indistinguible para tenant ajeno/inexistente). CSRF y contexto existentes. No se cambia autorización de rutas actuales por añadir F1.

| Método/ruta | Contrato y autorización |
|---|---|
| GET `/live/access` | Miembro que ya puede consultar operation: capacidades booleanas efectivas de VIEW/OPERATE/CLOSE, y disponibilidad de F1; no devuelve borrador, marcador privado, actores ni reloj privado. No otorga autorización a otra ruta. |
| GET `/live` | VIEW + alcance; snapshot coherente: estado/revisiones, hechos vigentes completos, marcador provisional y referencia de reloj, trazabilidad permitida. Cero hechos se representa como lista vacía; si F1 no inicializado, respuesta explícita `initialized=false`, sin crear estado al leer. |
| POST `/live/commands` | OPERATE + alcance; unión cerrada `start/suspend/resume/start_clock/pause_clock/resume_clock/correct_clock/add_event/correct_event/remove_event`, `command_id` y `expected_revision`. Referencias y cuerpo según tipo; ack mínimo con revisión e identidad de comando. Sin modo offline ni escritura anticipada aceptada. |
| POST `/live/reviews` | VIEW + permiso actual de cierre; resultado/resolución completos candidatos; devuelve `review_id`, revisión/huella, conjunto y resultado que el usuario confirma expresamente. No confirma acta ni consume el borrador. |
| POST `/close` existente | Contrato clásico preservado si no hay F1; variante explícita `live_review_id` para F1, resultado igual al revisado y conjunto cargado del servidor. No exige OPERATE al cerrador ni omite reglas de resolución administrativa. |
| GET `/tournaments/public/{tournament_id}/matches` existente | Sin sesión; unión de respuesta clásica, live con campos adicionales aprobados y suspendido exacto. Mantener path efectivo del router registrado, filtros y paginación actuales; no crear una ruta paralela para suspendidos. |

Workspace: `useMatchLive` administra un snapshot separado de operation y del localStorage clásico. Acepta solo respuestas del contexto/generación vigente; limpia detalle en 401/403/404 actuales, cambios de identidad/organización y revocación; respuestas antiguas no restauran nada. Operar sin VIEW permite comandos conocidos y ack mínimo, nunca muestra detalle por herencia de escritura. Los perfiles por defecto reciben ambos permisos, pero se prueban por separado.

Al iniciar F1 no importar el borrador local existente: avisar de que no está aceptado, exigir resolverlo explícitamente antes de comenzar y conservarlo hasta una decisión confirmada del usuario. Una vez en modo compartido, las incidencias se aceptan por HTTP, no por insertar elementos locales en el array clásico. La edición en curso mantiene su formulario; si llega cambio de base, marcar conflicto y pedir revisión antes de guardar, sin perder texto ni sobrescribir. Confirmaciones single-flight con `useConfirm`, controles accesibles ES/EN; reloj sin iniciar/pausado/provisional/desactualizado con texto, no solo color.

Reutilizar el coordinador de recargas, las guardas `canUpdate`/generación, el comportamiento de acciones ocupadas y la señal de operación aceptada que alimenta `RectificationVersions`. Nuevos avisos y RESYNC solicitan una reconstrucción coordinada de operation, capacidades y live si autorizado; no agregar sockets, listeners duplicados de rectificación ni remontar componentes. Un fallo de lectura live no debe bloquear el historial 033 al que el miembro conserva acceso.

## 7. Catálogo cerrado, outbox y carriles

| Evento propuesto | Lectura HTTP equivalente | Payload outbox de dominio | Entrega al navegador |
|---|---|---|---|
| `MATCH_LIVE_UPDATED`, scope `organization` | GET `/matches/{id}/live`, VIEW + alcance del partido, sesión/usuario/membresía actuales | `{scope: organization, match_id, tournament_id}`; sobre outbox aporta organización e ID. No `version_id`, revisión de contenido ni hechos. | `{event_id, match_id, tournament_id}`; exclusivamente `PrivateDelivery` dirigido por sid, con SQL ampliado de 056. |
| `MATCH_LIVE_PUBLIC_UPDATED` | GET anónimo de partidos del torneo, únicamente si partido/torneo admiten proyección pública actual | `{match_id, tournament_id}`; sin score, reloj ni detalles. | `{event_id, match_id, tournament_id}` al room del torneo verificado. No entra en el catálogo organizativo privado. |

Productores: transiciones aceptadas, cambios de hechos y controles del reloj; no ticks ni rechazo de comandos. Solo producir público si cambia la proyección pública (una tarjeta sin efecto público no debe revelar una incidencia privada por un aviso público). Al despachar el evento público nuevo revalidar visibilidad/organización/partido desde la proyección autorizada: el torneo puede haberse ocultado tras encolar. En ese caso no emitir; HTTP anónimo mantiene 404 indistinguible. Los nombres y payloads antiguos permanecen intactos.

`resolve_event_references` y el adaptador SQL deben admitir expresamente el scope del nuevo evento sin exigir versión. `ReadRule` distingue lectura live de operation/version; el helper puro y la decisión SQL real deben tener tests de equivalencia. No agregar por defecto nuevos nombres al carril público; solo el nuevo nombre público validado, nunca el privado. Fuera de catálogo/referencias incompatibles: no entrega. Mantener F9 y sonda excluidos. Worker genérico ya publica los eventos de dominio: no hace falta un segundo worker ni publicar Redis dentro del request. Retrys conservan event_id; deduplicación y RESYNC de 035 recuperan HTTP, sin replay privado.

## 8. Proyección pública exacta y presentación

Para `suspended`, el conjunto de claves JSON, también cuando los valores son nulos, es exactamente:

| Campo | Valor/semántica |
|---|---|
| `id` | Partido público. |
| `tournament_id` | Torneo visible. |
| `home_team_id` | Equipo local. |
| `home_team_name` | Nombre local. |
| `away_team_id` | Equipo visitante. |
| `away_team_name` | Nombre visitante. |
| `status` | `suspended`. |
| `home_score` | Último marcador provisional aceptado del local. |
| `away_score` | Último marcador provisional aceptado del visitante. |
| `is_provisional` | `true`. |
| `clock_segment_number` | Última referencia válida o null. |
| `clock_elapsed_seconds` | Segundos completos congelados o null sin referencia. |
| `clock_state` | `paused` o `not_started`; nunca running. |
| `clock_observed_at` | Observación UTC del servidor; cambiarlo no acumula tiempo detenido. |

Modelo `PublicSuspendedMatchResponse` independiente, sin campos de `PublicMatchResponse` heredados. Serializar cada variante con su modelo específico antes de formar la lista y comprobar conjunto de claves, incluido el comportamiento de la unión en FastAPI/Pydantic. No añadir `lineup`, fase/grupo, escudos, motivo, resolución, protagonistas o eventos como null. En live, conservar los campos actuales más los campos de provisionalidad/reloj definidos en la spec; en otros estados no añadirlos por defecto. Confirmados/rectificados siguen leyendo la versión vigente, no el estado F1 congelado.

Filtros y orden SQL usan metadatos internos antes de serializar; la paginación se calcula sobre la unión completa, no combinando dos páginas independientes. El frontend guarda el contexto de la consulta de fase/grupo aparte de cada objeto recibido, sin fabricar campos JSON. Una consulta general renderiza los suspendidos en tarjetas mínimas del torneo; no deduce una posición de llave ausente ni depende de haber visto antes el partido programado. En navegación filtrada, conservar el filtro de origen; al cambiar estado, reconstruir la página/grupo correspondiente para evitar duplicados u omisiones. Cubrir primera carga anónima, móvil, SSR y paginación de frontera con suspendidos.

## 9. Estrategia de tests y trazabilidad

Tests primero para cada comportamiento nuevo: casos normales, vacío y error; medir rojo antes de implementar y verde después. Los comandos siguientes son gates previstos para la implementación, no resultados de esta redacción.

| Cobertura | RF / RNF | Pruebas propuestas |
|---|---|---|
| Inicio, estado, no terminal, permisos de transición | RF-001–003, 025, 029, 031 | Puros de transición + HTTP con PostgreSQL: scheduled/live/suspended/terminal, versión no publicada, participantes ausentes, revocación, varios roles/asignaciones. |
| Catálogo, captura/corrección, coherencia y provisionalidad | RF-004–008, 023–024, 030 | Reutilizar fixtures de cierre; todos los tipos, vacío, máximo actual, autogol, asistentes, sustitución, doble amarilla, tiempos inválidos, corrección/retirada sin efectos confirmados. |
| Público | RF-009–011, 028; RNF-002/006 | Matriz 020 anónima de dos tenants; exactamente 14 claves incluso null, live vs otros estados, invisible/cancelado, no alineaciones; paginación/primera visita sin caché. Estadísticas, sanciones y avance no cambian con provisionales. |
| Reloj y recuperación | RF-011, 017–018, 029–030; RNF-003/004 | Tiempo inyectado: fracciones acumuladas, pausa larga, reinicio, corrección corriendo/pausado, observaciones iguales/reloj regresivo, sin referencia, cambio de segmento, reanudación sin autoarranque. Minutos de hechos invariantes al corregir reloj. |
| Lectura/entrega/autorización | RF-012–018, 027, 031; RNF-001 | Comparar GET live con decisiones SQL/cliente real; VIEW sin OPERATE y viceversa; observador, árbitro no asignado, asignado solo a otro partido, actor multirol, caducidad/revocación entre outbox y entrega; errores/fila ausente fail-closed; F9 fuera. |
| Revisión/cierre/rectificación | RF-019–022, 024–026; RNF-003/006 | Carrera cierre-edición, dos cierres, recibo de otra sesión/tenant, resultado cambiado, modificación de hecho tras revisión, reloj que avanza sin invalidarla; borrador vacío; fallo inyectado en sanciones/avance/outbox => rollback completo. No bypass por DTO clásico ni subconjunto, cierre clásico sin F1 intacto, 033 publica versión nueva sin tocar original. |
| UI, asincronía y accesibilidad | RF-016–018, 026, 029–030; RNF-004/005 | Componentes con reloj inyectado; denegaciones/lecturas antiguas, A→B→A, edición mientras llega invalidación, reconexión/RESYNC, teclado y ES/EN. Playwright con API/Redis/PostgreSQL reales y receptor separado; evidencia visual de reloj/estado, no solo DOM/build. |

Migración y seguridad: SQL con rol aplicativo, RLS directo de las cuatro tablas, intentos cross-tenant y consultas con contexto ausente; limpio/incremental/idempotencia; función 055 antigua frente a 056 para eventos existentes; no crecimiento por ticks ni llamada por socket. Extender arnés multiproceso 035 con dos API, receptores de ambos tenants, retiradas confirmadas y recuperación real. Probar bursts y el borde 256/257; registrar latencias/trabajo SQL sin inventar SLA ni incluir payloads privados.

Gates finales: desde `backend/`, `pytest -q`, `RUN_DATABASE_TESTS=1 pytest -q` con PostgreSQL/Redis y variables documentadas de rol aplicativo/administrador separadas; `python -m compileall -q app`, ruff, bandit y pip-audit según CI. Desde `frontend/`, `pnpm test`, `pnpm run typecheck`, `pnpm run lint`, `pnpm run build`, tipos E2E y runner E2E completo documentado en AGENTS/CI (no sustituirlo por mocks). Desde raíz: validadores de infraestructura/versiones, Compose desarrollo/producción, migrador/targets, Trivy/Gitleaks y auditoría frontend con filtro constitucional exacto. Registrar salidas, skips, evidencia y límites por SHA en verificacion.md. CI pull_request y push, Review triada y aceptación humana independientes de haber redactado este plan.

## 10. División propuesta en PRs seguros de fusionar

1. **PR A — Fundación inerte.** 056, dominio puro, contratos internos y tests de migración/RLS/compatibilidad 055. No rutas productoras, no lectura pública nueva en uso, no suscripciones ni cambios del modo clásico. La función ampliada sigue denegando desconocidos y conserva eventos actuales; tablas vacías no alteran resultados ni vistas existentes. Fusionable sin B/C y con versiones antiguas corriendo. Gates: limpio/incremental, permisos, dominio y regresión 035.
2. **PR B — Recorrido backend completo y consumidores preparados.** Rutas privadas autorizadas, comandos, recibos y cierre adaptado; ruta pública exacta y adaptación mínima de tipos/render público; nuevos eventos, SQL/clasificador coordinados, dispatcher y reconstrucción HTTP de clientes, arnés multiproceso/E2E. La UI aún no ofrece capturar F1, pero un cliente autorizado que use la API obtiene un recorrido seguro completo, y el Workspace reconoce F1 para no cerrarlo desde una copia local. No posponer la protección de cierre ni el soporte público a C. Despliegue coordinado sin productores hasta renovar API/relay/consumidores; verificar que no queda instancia antigua capaz de cerrar un partido F1. Gates: todos los de CI y recorrido completo por HTTP + sockets reales.
3. **PR C — UX de operación, regresión y aceptación.** Editor compartido, transición explícita desde local, controles y reloj, revisión/confirmación completa, conflictos, ES/EN/accesibilidad; pruebas visuales y carga/regresión ampliadas, documentación de usuario/despliegue y matriz final. No introduce autorización nueva no cubierta en B. Fusionable porque B ya protege todos los contratos y no depende de C para confidencialidad o integridad. Mantener implementación pendiente de aceptación humana hasta cerrar validación.

Si la implementación muestra que B requiere mayor división, volver al usuario con el límite de seguridad, no habilitar un estado intermedio incompleto. Plan y C1–C5 ya aprobados autorizan redactar tasks.md; las tareas requieren aprobación propia antes de ejecutarse. Cada PR futuro tendrá sus tests y documentación verificables propios.

## 11. Verificación de constitución

Esta tabla verifica el diseño aprobado, no acredita ejecución ni despliegue.

| Principio/regla/criterio | Aplica | Cómo se cumple / gate |
|---|---|---|
| §2.1 Aislamiento en BD | Sí | RLS tenant desde 056 y FK compuestas; SQL directo con dos tenants y contexto ausente. RBAC HTTP y de entrega se verifica por separado. |
| §2.2 Sin privilegios de bypass | Sí | Rol aplicativo actual, función invocadora; validar `rolsuper=false`, `rolbypassrls=false`, grants mínimos. |
| §2.3 Publicado inmutable | Sí | Tablas separadas, cierre original y trigger intacto; posteriores correcciones solo 033. Ninguna versión de torneo se edita. |
| §2.4 Esquema append-only | Sí | Nueva 056 a reconfirmar; no editar 001–055 ni checksums. |
| §2.5 Público mínimo | Sí | Modelo exacto de 14 claves para suspended, lista cerrada live, sin incidencias/personas/alineaciones nuevas; consentimiento previo no alterado. |
| §2.6 Secretos fuera de desarrollo | Sí | Ningún secreto/default/variable nueva; mantener validaciones existentes. |
| §2.7 Plataforma separada/auditada | Sí | No endpoints admin nuevos ni membresía implícita; sin acceso extra de plataforma a F1. |
| §2.8 Verificación antes de terminar | Sí | Tests primero, gates locales/CI PR y push, Review, carga y aceptación humana; borrador de Plan no acredita implementación. |
| §2.9 Desarrollo no llega a producción | Sí | Barreras/fallos multiproceso solo en arnés test-only; sin fixture/seed en rutas productivas. |
| §3.1 BD, contexto y migraciones | Sí | `set_rls_context` dentro de cada transacción antes de consultas tenant; políticas con tablas, pruebas limpio/incremental y checksums. |
| §3.2 Backend, async y reglas configuradas | Sí | Módulo matches y router registrado; SQLAlchemy async; reusar reglas/publicación de versión; ningún efecto deportivo antes del cierre. Outbox/worker para notificaciones, no Redis en request. |
| §3.3 Frontend y rutas | Sí | `useApi`, público anónimo, Workspace con contexto; coordinador existente y guardas antiguas. |
| §3.4 Seguridad, privacidad y auditorías | Sí | No datos personales ni payload en logs técnicos, escáneres/auditorías con política constitucional sin exclusiones nuevas. |
| §3.5 Infraestructura/CI | Sí | Sin cambiar versiones/actions; pnpm lock intacto; validar ambos Compose y cinco jobs existentes según evento. |
| §3.6 Rectificación y sanciones | Sí | F1 solo provisional antes del cierre; 033 conserva separación solicitud/aprobación/publicación y original; F9 no entra en Redis/Socket.IO. |
| §4 Todos los cambios: CI, secretos, docs, tests | Sí | Evidencias por PR/SHA, documentación observable y normal/vacío/error; no dar aceptación por supuesta. |
| §4 BD: migración, RLS, dos volúmenes, sintaxis | Sí | `test_migration_056.py`, targets migrador, `sh -n infra/postgres/migrate.sh`. |
| §4 Backend: contexto, público, router, tests/compile | Sí | Matrices SQL/HTTP, ruta incluida en matches ya registrado; pytest completo con BD y compileall. |
| §4 Frontend: useApi, tests/tipos/build | Sí | Llamadas exclusivas useApi; tests/typecheck/lint/build y E2E/visual específicos de F1. |
| §4 Infra/despliegue: Compose y defaults | Sí | Mismo perfil de producción, migración antes de API y renovación coordinada; sin nuevos defaults. |
| §4 Dependencias: lock y auditorías | No cambio previsto | No se añaden paquetes; ejecutar auditorías CI existentes. Si fuese necesario uno, actualizar diseño/lock y justificarlo antes. |
| §5 Excepciones/enmiendas | No | No se solicita excepción ni enmienda; si aparece contradicción, detener e informar, no relajar invariantes. |
