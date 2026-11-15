# Tareas 036 — Partido en vivo

Estado: **aprobado** por el usuario el 2026-11-13: «Apruebo las tareas, en siete PRs (A1–C2)». Spec y Plan previamente aprobados («Apruebo la spec.» y «Apruebo el plan.»), con DA-1–DA-7 y C1–C5 confirmadas. Se autoriza la fase Implementación en el orden oficial A1–C2, empezando por PR A1 (T1–T10). Las casillas verificadas citan su evidencia; las abiertas siguen siendo entregables futuros. Esta aprobación no equivale a aceptación de la implementación F1.

Son **84 tareas**, cada una estimada en **20–30 minutos de trabajo activo**; esperas de CI, suites completas, carga y aceptación humana se contabilizan aparte. El orden oficial aprobado es **A1 → A2 → B1 → B2 → B3 → C1 → C2**, con los rangos y cantidades de la tabla siguiente. Esta aprobación posterior concreta la división histórica A/B/C del Plan en siete PRs, sin cambiar sus garantías de seguridad ni las demás decisiones C1–C5. El tamaño se consigue separando piezas de dominio, tablas, endpoints, integración y gates; no se oculta todo el backend en una tarea. Si un bloque excede el tamaño al ejecutarlo, se propone descomposición antes de continuar, sin ampliar el alcance ni activar piezas incompletas.

## Dependencias, ejecución y tests primero

- Se ejecuta una sola tarea cada vez. Además de las dependencias explícitas, cada tarea depende de las anteriores del mismo PR; el siguiente PR espera a la fusión y gates del anterior. La aprobación del listado permite comenzar por A1; no permite saltar tareas, gates ni decisiones de fusión del usuario.
- En cada tarea funcional: escribir primero normal/vacío/error pertinentes, ejecutar el comando indicado y registrar **rojo por conducta ausente**, implementar lo mínimo y registrar verde antes de marcar. No contar imports rotos, entorno ausente o selección sin tests como rojo funcional. Las caracterizaciones y gates registran baseline/resultados; documentación y aceptación no inventan un rojo.
- Comandos independientes desde raíz. Python/pnpm se ejecutan en `backend/`/`frontend/` con runtimes de AGENTS o contenedores equivalentes; no hay gestor de paquetes raíz. Exportar `DATABASE_URL` aplicativo y `DATABASE_ADMIN_URL` exclusivamente para preparar/migrar bases de prueba, como CI; PostgreSQL/Redis reales, nunca producción ni BYPASSRLS. Con `RUN_DATABASE_TESTS=1` no sustituir RLS, commits, sockets o dos procesos por mocks.
- Nuevos tests propuestos: `test_match_live_policy.py`, `test_match_live_contracts.py`, `test_match_live_db.py`, `test_match_live_close_db.py`, `test_match_live_public.py`, `test_match_live_realtime.py`, `test_migration_056.py` en backend; `match-live-*.test.ts` en frontend. Los selectores de cada tarea deben recoger casos reales; no basta un exit 0 sin tests.
- 056 se construye en varias tareas **solo en bases desechables**, sin registrarla/aplicarla en volúmenes persistentes hasta completar su contenido y gate. Tras primera aplicación persistente/fusión no se edita: cualquier corrección exige una migración nueva. Reconfirmar siguiente número libre antes de crearla. No editar 001–055.
- E2E dirigidos: pila local sana/sembrada y Chromium del runner existente, con `pnpm exec playwright test`. El gate completo es `pnpm run e2e:test`, sin vistas obligatorias omitidas, `retries: 0`. No compartir `.nuxt` entre build y un servidor dev activo sin reiniciarlo antes del E2E.
- Cada tarea deja comando, resultado, evidencia saneada y SHA en el futuro `verificacion.md`. No incluir tokens, cookies, identidades ni hechos privados en logs/artefactos. Los gates exigen resolver fallos causados por el cambio; los ajenos se escalan con logs y comparación verificable.

## Gates reutilizados

Estas recetas son requisitos futuros. Los «Hecho cuando» siguientes citan el comando focal y, cuando corresponde, estos gates completos; no equivalen a prometer que se han ejecutado ahora.

- **G-BE:** `cd backend && pytest -q`; `cd backend && RUN_DATABASE_TESTS=1 pytest -q`; `cd backend && ruff check .`; `cd backend && python -m compileall -q app`. BD migrada y Redis accesibles, roles separados según CI. Registrar skips reales y resolver los nuevos injustificados.
- **G-FE:** `cd frontend && pnpm test`; `cd frontend && pnpm run typecheck`; `cd frontend && pnpm run lint`; `cd frontend && pnpm run build`; `cd frontend && pnpm run typecheck:e2e`.
- **G-E2E:** `cd frontend && pnpm run e2e:test` con pila preparada como `.github/workflows/ci.yml`/AGENTS; código 0, no solo el grep focal ni una página que carga.
- **G-INF:** `python3 infra/scripts/verify_version_sources.py --exclude-constitution`; `sh -n infra/postgres/migrate.sh`; `sh infra/scripts/test_migrate_target.sh` con PostgreSQL de pruebas; `docker compose config -q`; perfil producción con variables dummy, `docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json | python3 infra/scripts/assert_production_compose.py -`, más las aserciones de desarrollo/versión de Compose del CI.
- **G-SEC:** `pip-audit -r backend/requirements.txt -r backend/requirements-dev.txt`; `cd backend && bandit -r app -ll`; ejecutar desde raíz el bloque constitucional exacto `pnpm --dir frontend audit --prod --json --audit-level low` → `infra/scripts/audit_frontend.py --input ... --pnpm-status ...` con archivo temporal eliminado por trap, además de Gitleaks sobre `git archive HEAD` y Trivy con versión/umbral fijados en CI. Reproducir los comandos completos del workflow, no reemplazar filtros ni añadir exclusiones.
- **G-REMOTE:** commits/push solo cuando el brief de ejecución lo autorice; verificar el SHA con `git rev-parse HEAD`. Para el PR que corresponda, `git_pr_checks(repo="github.com/edsel9ra/bracket-craft", pull_number=<PR>, wait_mode="all")`; comprobar también su run `push` por separado con `gh run view <run> --json headSha,event,conclusion,jobs`. Revisar Devin Review/comentarios para ese SHA, corregir hallazgos reales con test. E2E de push de feature se declara omitido según workflow, no ejecutado. No abrir ni fusionar un PR sin indicación del usuario.

## División oficial aprobada — siete PRs

El usuario aprobó expresamente esta división al aprobar las tareas («Apruebo las tareas, en siete PRs (A1–C2)», 2026-11-13). Se divide **la entrega**, manteniendo una única spec para no fragmentar autorización, integridad y recuperación de F1. Los siete PRs sustituyen la propuesta inicial de tres PRs de C5 con los mismos límites de seguridad. La fecha de aprobación es la comunicada por el usuario, aunque su registro documental sea posterior.

| PR oficial | Rango / cantidad | Por qué es seguro solo |
|---|---|---|
| A1 — Dominio y contratos inertes | T1–T10 / 10 | Solo funciones puras, contratos y pruebas; nada registrado en HTTP ni productor. |
| A2 — Migración completa | T11–T24 / 14 | Incluye **toda** 056, RLS, permisos, función invocadora y vistas acotadas no consumidas. Ninguna tabla se entrega sin su RLS. No partir 056 en dos PRs ni editarla tras fusionar A2. |
| B1 — Servicios privados internos | T25–T36 / 12 | Handlers/servicios probados con BD, **sin incluir el nuevo router en la aplicación productiva** ni ofrecer inicio F1. No se cambia todavía la ruta pública. |
| B2 — Cierre y avisos preparados | T37–T48 / 12 | Protege cierre clásico frente a estado F1, prepara catálogo, outbox y modelos; sigue sin ruta productora accesible. No hay captura activa que dependa de B3 para ser segura. |
| B3 — Exposición completa y activación | T49–T60 / 12 | Público exacto, consumidores compatibles y registro final del router viajan juntos. Activar solo tras gates y despliegue coordinado sin API antigua. No separar T55 de sus precondiciones. |
| C1 — Interfaz operativa | T61–T72 / 12 | Backend B3 ya es completo y seguro; añade la UX del recorrido sin dejar controles esenciales para después. |
| C2 — Verificación ampliada y aceptación | T73–T84 / 12 | Amplía evidencia/regresión/carga/documentación; no pospone autorizaciones o integridad hasta esta parte. No declarar implementación aceptada antes de T84. |

Gates G-BE/G-FE/G-E2E/G-INF/G-SEC/G-REMOTE al cierre de **cada uno de los siete PRs**. No fusionar commits de tests rojos ni exponer rutas incompletas. A2 no comienza hasta verificar la fusión autorizada de A1 y sus gates, y así sucesivamente hasta C2.

## PR A1 — Dominio y contratos inertes (T1–T10)

Sin cambios observables del flujo clásico ni productores nuevos. T1–T10 verificadas el 2026-11-14, con G-REMOTE del PR #80 sobre `d58e65bc7a3660a3776b45ea9a727f58dac068aa`; A2 no comienza antes de fusión y gates de A1.

- [x] **T1. Caracterizar operación, cierre clásico y permisos con fixtures reutilizables.** RF-003, RF-012, RF-021, RF-022, RF-031; RNF-001, RNF-006
  - Tests primero: baseline con dos tenants, operación sin permiso de cierre, oficial asignado/no asignado y acta confirmada; reutilizar fixtures existentes.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_close_authorization_db.py tests/test_rectification_readers.py` conserva resultados y quedan condiciones de lectura actuales registradas, sin cambios HTTP.
  - Evidencia A1: comando anterior, **27 passed in 16.04s**. Reutiliza `committed_application`, `seeded_match`, `add_member`, `close` y `read_state`; añade lectura de operación por observador sin cierre, rollback sin cambios y 404 entre dos tenants. Los casos existentes cubren árbitro asignado/no asignado y acta confirmada. Caracterización del comportamiento actual, sin rojo artificial ni cambio HTTP.

- [x] **T2. Definir capacidades separadas y evaluación pura de vías organizativa/asignada.** RF-012, RF-031; RNF-001
  - Tests primero: VIEW solo, OPERATE solo, observador, árbitro de otro partido, multirol y contexto ajeno/incompleto.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k access` prueba que escribir no concede leer y que una vía organizativa válida no exige asignación.
  - Evidencia A1: comando anterior, rojo **18 failed** por política todavía no implementada; verde **18 passed in 0.04s**. Permisos separados, vías independientes y acumulables, sin unir permiso de una vía inválida a asignación de otra. No concede permisos en BD.

- [x] **T3. Definir los DTO estrictos del sobre de comandos y lectura/capacidades.** RF-001, RF-003, RF-007, RF-012, RF-029, RF-030
  - Tests primero: tipos cerrados, UUID/revisión, cuerpo vacío, campos extra y datos incompatibles con el tipo de comando; 422 saneado.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_contracts.py -k command` verifica unión cerrada reutilizando esquemas existentes; no se registra router.
  - Evidencia A1: comando anterior, rojo **13 failed, 17 passed**; verde **30 passed in 0.75s** tras implementar la unión y completar las cabeceras del Request test-only del saneador 422 existente. Contratos de lectura inicializada/sin inicializar y referencia del reloj ampliados después: rojo **3 failed, 8 passed**, verde **11 passed**, más casos running/paused/UTC cubiertos por los **172 passed** del checkpoint final. Ningún router registrado.

- [x] **T4. Reutilizar el catálogo/payload de hechos y contratos de revisión/cierre F1.** RF-004, RF-005, RF-007, RF-019, RF-024
  - Tests primero: catálogo completo, normalización de identidad, metadata desconocida, cero/500/501 hechos y recibo ausente/ajeno en estructura.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_contracts.py -k report` y `cd backend && pytest -q tests/test_match_events_contract.py` mantienen un único catálogo, sin habilitar F13.
  - Evidencia A1: primera selección, rojo **2 failed, 13 passed** y verde **15 passed in 0.86s**; catálogo clásico **69 passed in 0.07s**. Reutiliza `EVENT_TYPES`, `MatchEventPayload`, `client_event_identity` y la validación de resolución/duplicados de `CloseMatchReportDTO`. Cero/500/501 hechos, identidad normalizada y metadatos cerrados; resultado F1 no acepta ni serializa `events`. Recibo UUID obligatorio, sin ámbito ajeno suministrado por el cliente; la pertenencia real a partido/actor/sesión requiere el servicio/BD de B2, no se infiere de un UUID válido. DTO clásico intacto.

- [x] **T5. Implementar observación pura de reloj con tiempo recibido como argumento.** RF-011, RF-017, RF-029; RNF-003, RNF-004
  - Tests primero: sin referencia, UTC aware, running, pausado, fracciones acumuladas, observación igual y reloj regresivo.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k observe_clock` produce segundos enteros sin perder microsegundos ni consultar reloj global/BD.
  - Evidencia A1: comando anterior, rojo **14 failed** y verde **14 passed in 0.07s**. UTC aware, delta entero en microsegundos con límite inferior cero, sin referencia, pausado, instante igual/regresivo y validación de referencias incompatibles.

- [x] **T6. Reducir inicio, pausa, reanudación y corrección del reloj.** RF-002, RF-011, RF-026, RF-029, RF-030; RNF-003
  - Tests primero: controles en live/suspended, segmento inválido, corrección running/paused y hechos preexistentes inalterados.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k control_clock` reancla con el instante inyectado y no cambia minutos/tiempo añadido.
  - Evidencia A1: comando anterior, rojo **19 failed** y verde **19 passed in 0.09s**. Diez ciclos conservan fracciones; corrección running/paused, rechazo en suspended/segmento inválido y nuevo segmento solo con inicio expreso. El reductor solo devuelve una referencia nueva: no recibe ni modifica hechos.

- [x] **T7. Reducir transiciones deportivas permitidas sin efectos secundarios.** RF-001, RF-002, RF-003, RF-025, RF-029
  - Tests primero: scheduled→live→suspended→live, sin participantes, versión no publicada, estados terminales y suspensión sin reloj.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k transition` conserva segmento/borrador al reanudar y nunca arranca el reloj automáticamente.
  - Evidencia A1: comando anterior, rojo **41 failed** y verde **41 passed in 0.07s**; dos guardas adicionales de reloj imposible verificadas en el checkpoint final. Recorrido completo, versión/participantes, confirmado/terminal, suspensión sin referencia y reanudación conservadora sin tocar el borrador.

- [x] **T8. Derivar marcador provisional reutilizando reglas y validación deportiva.** RF-004, RF-005, RF-007, RF-008, RF-024; RNF-003
  - Tests primero: vacío/cero, goles/autogoles/penaltis, equipos incompatibles y corrección/retirada, sin escribir resultados confirmados.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k provisional_score` usa las reglas publicadas y no introduce constantes deportivas nuevas.
  - Evidencia A1: comando anterior, rojo **8 failed** y verde **8 passed in 0.19s**. Conteo extraído sin cambiar semántica a `count_event_goals`, compartido por `compute_match_outcome` y la política F1; no hay segundo catálogo de goles. Valida participantes/configuración; plantillas, elegibilidad y acta completa siguen correspondiendo a los validadores existentes al integrar B1/B2. Ningún resultado confirmado se escribe.

- [x] **T9. Canonizar conjunto revisado y separar revisión de contenido de reloj.** RF-006, RF-019, RF-020, RF-023, RF-030
  - Tests primero: orden estable, subconjunto distinto, resultado cambiado, hechos retirados y reloj que avanza sin cambiar huella.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k review_fingerprint` demuestra invalidación por hechos/resultado, no por observación pública.
  - Evidencia A1: comando anterior, rojo **8 failed** y verde **8 passed in 0.22s**. SHA-256 canónico de hechos, resultado completo y revisión de contenido; reutiliza `canonical_event_order` y preserva el desempate del payload. Subconjunto, retirada, corrección y resultado distinto cambian huella; reloj/observación no son entradas.

- [x] **T10. Verificar checkpoint de dominio/contratos inertes y su alcance.** RF-003, RF-007, RF-012, RF-019, RF-024; RNF-003, RNF-006
  - Dependencias: T1–T9. Caracterización/gate, sin rojo artificial.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py tests/test_match_live_contracts.py` y `git diff --check` pasan; ningún router/productor/carril público se ha activado. Además pasan los seis gates y su revisión remota antes de la fusión autorizada de A1.
  - Parte local autorizada: checkpoint anterior **172 passed in 0.80s**; `ruff check .`: **All checks passed!**; `python -m compileall -q app`: exit 0; suite sin BD **2852 passed, 950 skipped in 10.57s** (opt-in PostgreSQL). `RUN_DATABASE_TESTS=1 pytest -q -ra`: **3798 passed, 4 skipped in 845.79s (0:14:05)** sobre PostgreSQL/Redis reales, base aislada migrada hasta 055 y roles aplicativo/administrador separados; los cuatro skips son exclusivamente invitaciones que requieren `demo.owner`, ausente en esta base sin seed. La primera ejecución reveló que el arnés local apuntaba la URL administrativa a otra base: corregido fuera del repositorio y repetido en base nueva, sin parche de producto. Verificación AST: sin importaciones productivas de los módulos F1, reloj global, BD ni emisión en la política; sin 056. Sin frontend modificado: no se repiten sus suites en este brief.
  - Comprobaciones adicionales: `bandit -r app -ll` exit 0 (**0 medium/high**, 12 low); recetas CI de Compose desarrollo/producción, contrato de entorno, versiones y sintaxis del migrador correctas. `git diff --check` exit 0. Ninguna de estas evidencias sustituye CI/revisión remotas.
  - **G-REMOTE verificado, PR #80, SHA `d58e65bc7a3660a3776b45ea9a727f58dac068aa`:** `git_pr_checks(..., wait_mode="all")`: **7 passed, 0 failed, 0 pending, 0 skipped**. Run [`pull_request` 43553606036](https://github.com/edsel9ra/bracket-craft/actions/runs/43553606036) y run [`push` 43553601819](https://github.com/edsel9ra/bracket-craft/actions/runs/43553601819), ambos **success**: cinco jobs en PR, cuatro en push y E2E omitido en feature push según workflow. Backend con BD: **3808 passed, 4 skipped** en ambos runs; sin BD: **2862 passed, 950 skipped**; frontend **978 pass, 0 fail, 1 skipped**. Infraestructura y seguridad correctas.
  - **Devin Review:** el hallazgo real sobre estados del snapshot en `f48c8501` se corrigió en `d58e65bc`, cotejando el CHECK de PostgreSQL y migraciones: acepta `administrative_resolution` y rechaza `walkover`/`abandoned`/`postponed`. Regresión rojo **4 failed, 6 passed**, verde de políticas/contratos **182 passed in 0.74s**; ruff correcto. No hay otros Literals de estado de partido incorrectos en los dos módulos. Status Review de `d58e65bc`: **success**, **"Devin fixed the finding"**, sin hallazgos pendientes; review GitHub **5901409056** sobre ese SHA: **1 hallazgo, Fixed by Devin (1)**, cero comentarios inline. Cierre documental separado autorizado por el usuario; su CI se verifica tras el push. No acredita fusión, aceptación F1 ni autorización de A2.

## PR A2 — Migración completa (T11–T24)

Dependencia externa: A1 fusionado y sus gates verdes. Entregar 056 completa con RLS, sin consumidores ni productores nuevos activos.

### Evidencia común A2

- Base: `main` actualizado con #80 fusionado, rama `devin/1794630110-partido-en-vivo-a2`; 056 reconfirmada como siguiente número libre. Solo se desarrolla/aplica en bases desechables; 001–055 intactas.
- Tests escritos antes del SQL: baseline 055 con dos tenants y ausencia de estado F1; primera selección **1 passed, 28 errors** por archivo 056 ausente, no acreditada como rojo funcional. Rojo funcional adicional: cierre de segmento con reloj corriendo y metadata nula de tarjeta roja aceptados indebidamente (**DID NOT RAISE CheckViolationError**), y purga 034 bloqueada por FK de sesión (**ForeignKeyViolationError**). Corregidos en la misma 056 todavía no aplicada persistentemente.
- Checkpoints PostgreSQL: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py`: **60 passed in 63.30s**; regresión adicional `-k compatible_with_existing_session_retention`: **1 passed, 60 deselected in 1.44s**. Suite final `RUN_DATABASE_TESTS=1 pytest -q -ra`: **3869 passed, 4 skipped in 919.30s (0:15:19)**, incluidos los 61 casos nuevos. Los cuatro skips son invitaciones que requieren `demo.owner`, ausente sin seed. La primera suite completa detectó el inventario cerrado de FKs a jugadores: ampliado aditivamente con las cuatro parejas compuestas nuevas, sin exclusiones ni relajación del aislamiento; repetición final verde. Sin BD: **2862 passed, 1011 skipped in 10.68s** (opt-in PostgreSQL).
- Migrador real `sh infra/postgres/migrate.sh`: init + 001→056 en BD nueva y 055 con datos de dos tenants→056; segunda ejecución en ambas conserva **56 checksums** y datos previos. Reejecución SQL directa tampoco duplica permisos. `sh infra/scripts/test_migrate_target.sh`: **OK: todas las pruebas de MIGRATION_TARGET pasaron**. Ese script cambia la contraseña global del rol de pruebas: se restauró con `00_roles.sh` desde la configuración existente antes de repetir la suite, sin cambios de producto ni credenciales en el repo.
- `ruff check .`: **All checks passed!**; `python -m compileall -q app`: exit 0; Bandit `-r app -ll`: exit 0 (**12 low, 0 medium, 0 high**). Recetas CI de infraestructura desarrollo/producción, contrato, versiones y sintaxis del migrador correctas. Gitleaks sobre el árbol final y `git diff --check` se adjuntan al reporte de publicación de A2; no equivalen a G-SEC completo ni a G-REMOTE.
- Auditoría SQL real: **2 vistas security_barrier, SELECT aplicativo y sin PUBLIC; 5 funciones SECURITY INVOKER**. Las cuatro tablas tienen RLS + FORCE; `bracket_app` verificado **no superusuario y sin BYPASSRLS**. RLS garantiza tenant/membresía; RBAC intratenant HTTP y entrega siguen siendo verificaciones separadas.
- Sin router, servicio HTTP, productor, emisión, frontend ni consumidor público F1 nuevo. Las dos vistas nuevas permanecen sin consumir; las definiciones públicas existentes y las filas de partidos se comparan antes/después de 056 en cada fixture. No se declara F1 implementada ni aceptada.

| Tarea | Evidencia específica en `test_migration_056.py` y auditoría |
|---|---|
| T11 | `baseline_055`: dos tenants/partidos y ausencia del estado nuevo; fixture de cadena real anterior a 056. |
| T12 | `state_table`/`rls`: estado vacío, microsegundos, referencias/anchor/tiempo inválidos y tenant ajeno; marcador confirmado intacto. |
| T13 | `events_table`: siete tipos, estructura/metadata cerradas, identidad/retirada, referencias tenant y límite de 500 vigentes. Inventario estricto de `players` ampliado con cuatro FKs compuestas. |
| T14 | `commands_table`: identidad repetida con hash igual/diferente rechazada, actor/sesión válidos y SELECT/INSERT sin UPDATE/DELETE. Conflicto HTTP/recuperación de aceptación siguen en B1. |
| T15 | `reviews_table` y retención: recibo propio persistido, ajeno invisible, actor/sesión falsos rechazados e inmutabilidad. Sesión validada al insertar por trigger sin FK que bloquee 034; su purga conserva historial y no permite nuevos recibos con esa sesión. Huella/consumo de cierre siguen en B2. |
| T16 | `permissions`: concesiones aditivas a owner/administrator/operator/referee, no viewer/personalizados; organización/rol nuevos por mecanismos reales, reejecución sin duplicados, CLOSE intacto y VIEW/OPERATE independientes. |
| T17 | `live_integrity`: terminal/confirmado, suspendido, transición inválida, segmento cerrado con reloj corriendo, congelación/rollback. Un mero cerrador no edita marcador y puede congelar con identidad propia aunque no sea creador; 009/016 intactas. |
| T18 | `realtime_live`: sin version_id, permiso/asignación, revocaciones, referencias incompatibles, 256/257 y restauración de los cuatro GUC; inválidos DENY/INDETERMINATE/fila ausente como antes. |
| T19 | `public_projection`: selección interna y exactamente 14 claves; live/suspended, referencia nula, inactiva/oculto/versión no actual/cancelado. Catálogo verifica barrera/grants; vistas anteriores intactas y sin consumidores nuevos. |
| T20 | `clean_incremental_idempotent`, migrador real en ambas bases, 56 checksums estables, partidos previos intactos, reejecución sin duplicados y sintaxis shell. |
| T21 | `rls`: cuatro tablas bajo SET LOCAL ROLE bracket_app, dos tenants, contexto vacío, lectura/escritura cruzada, sin PUBLIC ni DELETE; comandos/recibos añaden política restrictiva de actor. |
| T22 | `legacy_authorization`: tres casos clásicos y tres rectificativos concretos sobre 056, reutilizando pruebas 055; catálogo F9/desconocido cerrado y multirol. Misma firma, agrupación por usuario y máximo 256 en una llamada. |
| T23 | Catálogo/diff: cinco funciones invocadoras, REVOKE/GRANT mínimos; comandos guardan identificadores/actor/sesión/hash/tipo/revisión/fecha sin cuerpo; recibos conservan el resultado revisado privado y estado responsable/momento. Sin credenciales ni detalle deportivo en logs, Python productivo, HTTP, estadísticas o frontend alterados. |

- [x] **T11. Preparar pruebas de migración limpia/incremental sobre bases desechables.** RF-008, RF-012, RF-023, RF-031; RNF-001
  - Tests primero: caracterizar cadena hasta 055 y construir fixture reutilizable de dos tenants/roles; añadir aserciones de 056 todavía en rojo por ausencia de su esquema, no por fallo del entorno.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k baseline_055` pasa; la selección de esquema nuevo registra rojo esperado hasta T12–T20 sin aplicar una 056 parcial en volumen persistente.

- [x] **T12. Añadir estado/referencias de reloj y RLS tenant en 056.** RF-001, RF-002, RF-008, RF-011, RF-025, RF-029; RNF-001, RNF-004
  - Tests primero: PK/FK compuestas, checks de referencia/anchor/tiempo, contexto ausente y tenant ajeno.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k state_table` valida `match_live_state` y su RLS con rol aplicativo; no se tocan scores confirmados.

- [x] **T13. Añadir hechos privados y restricciones de referencias tenant.** RF-004, RF-005, RF-007, RF-008, RF-023, RF-024; RNF-001
  - Tests primero: identidad única, referencias ajenas y retirada, catálogo/estructura compatibles sin insertar `match_events`.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k events_table` valida `match_live_events`, RLS y claves compuestas de equipo/segmento/jugadores.

- [x] **T14. Añadir registro idempotente de comandos sin credenciales ni cuerpos en logs.** RF-023, RF-026; RNF-001, RNF-004
  - Tests primero: comando repetido, unicidad por partido, hash diferente, actor ajeno y permisos mínimos de tablas.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k commands_table` verifica tabla/RLS/GRANT de comandos y ausencia de DELETE innecesario.

- [x] **T15. Añadir recibos inmutables de revisión ligados a actor/sesión.** RF-019, RF-020, RF-023, RF-026; RNF-001
  - Tests primero: pertenencia de partido/actor, recibo ajeno, cambio de contexto y prohibición de sobrescritura/borrado por el rol aplicativo.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k reviews_table` valida tabla, políticas y referencias sin convertir recibos en actas confirmadas.

- [x] **T16. Conceder permisos por defecto sin reemplazar permisos existentes.** RF-012, RF-031; RNF-001, RNF-006
  - Tests primero: roles existentes/nuevos, dueño/administrador/operador/árbitro, observador, personalizados y reejecución sin duplicar entradas.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k permissions` demuestra VIEW/OPERATE independientes y CLOSE/lecturas existentes intactos.

- [x] **T17. Proteger integridad provisional frente a terminales y congelación de cierre.** RF-003, RF-008, RF-021, RF-022, RF-025
  - Tests primero: SQL directo sobre confirmado, transición inválida, reloj en segmento cerrado y congelación válida seguida de rollback.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k live_integrity` valida triggers nuevos sin relajar los triggers 009/016 ni permitir al mero cerrador una edición ordinaria.

- [x] **T18. Ampliar en 056 la función invocadora de entrega para F1.** RF-012, RF-013, RF-014, RF-015, RF-031; RNF-001
  - Tests primero: evento cerrado `MATCH_LIVE_UPDATED`, sin versión, permiso/asignación, referencias incompatibles y lote inválido.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k realtime_live` valida firma/límite 256, SECURITY INVOKER y restauración de contexto, sin modificar 055.

- [x] **T19. Añadir vistas acotadas F1 sin alterar vistas de estadísticas/acta vigente.** RF-009, RF-010, RF-028; RNF-001, RNF-002
  - Tests primero: organizaciones activas, versión publicada actual, cancelado/invisible, live/suspended y referencia nula; barrera de seguridad/grants.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k public_projection` valida selección interna separada de las 14 claves públicas y mantiene las vistas actuales sin consumo de borradores.

- [x] **T20. Verificar 056 completa en limpio, incremental y reejecución del migrador.** RF-008, RF-012, RF-023, RF-028, RF-031; RNF-001, RNF-006
  - Dependencias: T11–T19. Gate de migración, no edición de una versión aplicada.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py` y `sh -n infra/postgres/migrate.sh` pasan para 001→056 y 055 con datos→056, checksums estables y reejecución sin duplicar permisos; siguiente número libre reconfirmado.

- [x] **T21. Verificar aislamiento SQL directo de las cuatro tablas y privilegios reales.** RF-012, RF-016, RF-026; RNF-001
  - Tests primero: dos tenants, lectura/escritura cruzada y contexto ausente, bajo bracket_app no superusuario/BYPASSRLS.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k rls` cubre las cuatro tablas y documenta la frontera: RLS tenant, RBAC HTTP/entrega por separado.

- [x] **T22. Probar compatibilidad de las decisiones 055 antiguas y roles acumulados.** RF-012, RF-013, RF-015, RF-027, RF-031; RNF-001, RNF-002
  - Tests primero: los seis casos de catálogo anteriores frente a 056, error/fila ausente, desconocidos/F9 y vías multirol.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py tests/test_migration_056.py -k 'legacy or authorization or multi_role'` recoge casos reales y no amplía destinatarios actuales ni introduce una llamada por socket.

- [x] **T23. Auditar grants, trazabilidad mínima e inercia de la fundación.** RF-008, RF-014, RF-022, RF-026, RF-027; RNF-001, RNF-006
  - Caracterización: inspeccionar diff y artefactos; no hace falta rojo artificial.
  - Hecho cuando: `git diff --check` y `cd backend && ruff check .` pasan; SQL/tests prueban invocador/GRANT/REVOKE sin PUBLIC ni credenciales y se registra que no existen rutas productoras F1, cambios de estadísticas ni nuevos campos públicos activos.

- [x] **T24. Cerrar gates locales/remotos y fusión autorizada de A2.** RF-003, RF-008, RF-012, RF-013, RF-022, RF-028, RF-031; RNF-001, RNF-002, RNF-003, RNF-006
  - Dependencias: T1–T23. Preparación de evidencias, esperas de suites/CI aparte del trabajo activo.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q` y `git diff --check`, más G-BE/G-FE/G-E2E/G-INF/G-SEC/G-REMOTE pasan; verificación de 056 y rama limpia por SHA registradas. No se da por fusionado A2 hasta comprobar la fusión decidida por el usuario.
  - **G-REMOTE verificado, PR #81, SHA `8c9de99bd4e0e09241a5e05763f7e5d9ec79e5a5`:** `git_pr_checks(..., wait_mode="all")`: **7 passed, 0 failed, 0 pending, 0 skipped**. Run [`pull_request` 43560167502](https://github.com/edsel9ra/bracket-craft/actions/runs/43560167502) y run [`push` 43560076300](https://github.com/edsel9ra/bracket-craft/actions/runs/43560076300), ambos **success**: cinco jobs en PR, cuatro en push y E2E omitido en feature push según workflow. Backend, frontend, infraestructura, seguridad y E2E acreditados por CI; no se confunden con ejecuciones locales no realizadas.
  - **Devin Review:** review GitHub **5901823122**, sobre `8c9de99b`, **"No Issues Found"**, sin comentarios inline; status **success**, **"Completed analysis in 1m 21s"**. Sin hallazgos ni fixes pendientes. Cierre documental separado solicitado por el usuario; su CI se verifica tras el push. No acredita fusión del PR, inicio de B1 ni aceptación de F1; la fusión sigue en manos del usuario.

## PR B1 — Servicios privados internos (T25–T36)

Dependencia externa: A2 fusionado y sus gates verdes. No habilitar productores hasta T55 y sus precondiciones; B1/B2 permanecen sin nuevo router productivo.

Desviación autorizada el **2026-11-14**, respuesta del usuario **«Opción 1: migración 057 mínima (recomendada)»**: B1 incluye `057_live_segment_automatic_pause.sql` para T33. 056 permanece intacta. CLOSE sin VIEW/OPERATE debe poder interrumpir/completar un segmento con reloj F1 running sin adquirir operación ni lectura F1. La pausa automática ocurre en la misma transacción de segmento; no cambia permisos HTTP. Pruebas: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_057.py`, rojo **2 failed, 7 deselected** (`LIVE_CLOCK_SEGMENT_NOT_ACTIVE`), verde **9 passed in 12.95s**, con negativos y cadena limpia/incremental 056→057, reejecución idempotente y funciones invocadoras.

Desviación adicional autorizada el **2026-11-14**, **Opción 1** del hallazgo 1 de Review #82: `058_live_player_eligibility.sql` para T31/RF-007. Solo devuelve IDs de jugadores no elegibles; OPERATE_MATCH_LIVE con alcance 056, aislamiento de tenant y ninguna lectura F9 heredada. SECURITY DEFINER necesario para calcular sobre historial RLS no legible por el actor; search_path fijo, PUBLIC revocado y EXECUTE solo bracket_app, sin BYPASSRLS. 042/056/057 y permisos HTTP intactos. Captura siempre con 058 y explicación de rechazo existente; cierre/review conservan el cálculo anterior. Diseño y alternativa descartada en plan.md.

Evidencia local 058: rojo previo OPERATE-only SANCTION_OPERATION_DENIED; nueva ronda inicial **16 failed, 6 passed**, verde **33 passed in 43.76s** en `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_058.py tests/test_match_live_review_regressions.py`. Incluye operador sin VIEW/CLOSE, suspensión y rollback, tres roles organizativos, árbitro asignado/no asignado, permiso ausente, otro tenant, salida mínima, equivalencia con load_effective_sanctions en 18 combinaciones y privilegios. Migrador limpio 001→058 e incremental 057→058 con dos tenants, reejecución idempotente, 58 checksums estables y datos previos intactos; el runner usado no cambia la contraseña de bracket_app. T36 se mantuvo abierta hasta la autorización de cierre y evidencia G-REMOTE registradas abajo.

Verificación integral posterior a 058, con PostgreSQL y Redis: `RUN_DATABASE_TESTS=1 pytest -q -ra` **3963 passed, 4 skipped in 1310.18s (0:21:50)**; skips de invitaciones por demo.owner ausente en el arnés. Ruff app/tests `All checks passed!`; `bandit -r app -ll` exit 0, 12 low, 0 medium/high. No se modifica frontend, no se registra router F1 ni se emiten eventos productivos. La publicación separa migración/servicio/tests y documentación en dos commits; el cierre posterior de T36 se realiza en un commit documental autorizado tras verificar G-REMOTE.

- [x] **T25. Implementar lectura de capacidades sin revelar borrador.** RF-012, RF-016, RF-031; RNF-001, RNF-006
  - Tests primero: booleans efectivos, contexto ajeno, observador y actor sin VIEW; usar fixture HTTP test-only, sin registro productivo del router nuevo.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k access` devuelve capacidades sin hechos/score/reloj privados y no cambia GET operation.

- [x] **T26. Implementar snapshot privado coherente y lectura vacía sin inicializar.** RF-005, RF-012, RF-016, RF-018, RF-024; RNF-001, RNF-004
  - Tests primero: VIEW sí/no, session/membership actuales, `initialized=false`, cero hechos y dos lectores; lectura no mutante.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k snapshot` verifica GET live autorizado bajo RLS y 404 indistinguible fuera del tenant.

- [x] **T27. Construir transacción de comandos, revisiones e idempotencia.** RF-003, RF-007, RF-023, RF-026; RNF-001, RNF-004
  - Tests primero: repetición con igual hash, distinto cuerpo, respuesta perdida y revisión obsoleta; permiso revalidado incluso en retry.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k command_identity` prueba ack mínimo sin heredar VIEW y bloqueos/contexto compatibles con cierre.

- [x] **T28. Aceptar inicio de partido con estado persistido no confirmado.** RF-001, RF-003, RF-008, RF-025, RF-026
  - Tests primero: scheduled válido, participantes ausentes, versión no publicada y doble inicio concurrente.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k start_match` persiste una única transición live sin eventos confirmados ni efectos de cierre.

- [x] **T29. Aceptar suspensión y reanudación sin autoarranque del reloj.** RF-002, RF-003, RF-011, RF-026, RF-029
  - Tests primero: reloj running/paused/no iniciado, captura durante suspended y conservación de hechos/segmento/tiempo.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k suspend_resume` congela el reloj y rechaza escrituras inválidas sin cambios parciales.

- [x] **T30. Persistir controles/correcciones del reloj con instante servidor.** RF-011, RF-023, RF-026, RF-030; RNF-003, RNF-004
  - Tests primero: permiso retirado, revisión perdida, reloj running y pausado, corrección inválida y reinicio/lectura posterior.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k clock` recibe el tiempo en el dominio puro y no altera minutos ni content_revision de hechos.

- [x] **T31. Capturar hechos con catálogo/participantes/reglas actuales.** RF-004, RF-005, RF-007, RF-008, RF-024
  - Tests primero: eventos válidos, vacíos/desconocidos, 501 hechos, referencias de otro tenant y tiempo inválido.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k add_event` reutiliza validadores, actualiza provisional coherentemente y no inserta `match_events`.

- [x] **T32. Corregir/retirar hechos explícitamente sin pérdida silenciosa.** RF-005, RF-006, RF-007, RF-023, RF-026
  - Tests primero: corrección/retirada de identidad conocida, obsoleta/ajena, cambios simultáneos y nuevo marcador.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k edit_event` incrementa content_revision solo por contenido aceptado y conserva lo anterior si falla validación.

- [x] **T33. Coordinar rutas actuales de segmentos con el reloj F1.** RF-003, RF-011, RF-025, RF-029; RNF-003, RNF-006
  - Tests primero: interrupción/cierre de segmento pausa reloj, nuevo segmento no arranca implícitamente y modo clásico permanece igual.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k segment_clock` respeta orden de bloqueo y no cambia permisos existentes de segmentos.

- [x] **T34. Emitir recibos de revisión completa sin confirmar ni congelar hechos.** RF-006, RF-019, RF-020, RF-024, RF-026
  - Tests primero: VIEW+CLOSE, falta cualquiera, vacío válido, resultado inválido y recibo ligado a actor/sesión/conjunto vigente.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k create_review` devuelve conjunto/resultado completos y preserva borrador/acta confirmada.

- [x] **T35. Probar atomicidad de comandos y ausencia de efectos confirmados.** RF-007, RF-008, RF-023, RF-026; RNF-003, RNF-004
  - Tests primero: fallo inducido tras cambio de estado/hecho antes de commit; no se pierde la respuesta aceptada ni se guarda una parcial.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k command_rollback` demuestra reversión de estado/comando/auditoría y clasificación/sanciones/avance intactos; inyección solo test-only.

- [x] **T36. Verificar checkpoint de servicios internos sin rutas productoras.** RF-001, RF-003, RF-008, RF-012, RF-019, RF-031; RNF-001, RNF-006
  - Dependencias: T25–T35. Gate de servicios, no autorización para exponerlos.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py tests/test_match_live_close_db.py -k 'not consolidation'` y `git diff --check` pasan; el router F1 sigue ausente del montaje productivo. Cumplir todos los gates y revisión antes de la fusión autorizada de B1.
  - **G-REMOTE verificado, PR #82, SHA `b9a888ad980c013cbc89abd2c9a33c73738a4ace`:** `git_pr_checks(..., wait_mode="all")`: **7 passed, 0 failed, 0 pending, 0 skipped**. Run [`pull_request` 43596664230](https://github.com/edsel9ra/bracket-craft/actions/runs/43596664230) y run [`push` 43596659340](https://github.com/edsel9ra/bracket-craft/actions/runs/43596659340), ambos **success**: cinco jobs en PR, cuatro en push y E2E omitido en feature push según workflow. Backend, frontend, infraestructura, seguridad y E2E acreditados por CI.
  - **Devin Review sin hallazgos pendientes sobre `b9a888ad`:** estado **success**, «Completed analysis in 1m 54s»; los cinco hallazgos anteriores tienen respuesta de resolución, incluido el 1 en comentario `4573559852`. El usuario confirmó Review sin hallazgos y autorizó cerrar T36; el resumen histórico sobre `e6e68784` no representa el estado del SHA verificado. El commit documental de cierre se vuelve a someter a CI y nueva Review; no se acredita fusión ni aceptación F1.

### Evidencia local B1 — 2026-11-14

T25–T35 verificadas en `RUN_DATABASE_TESTS=1 pytest -q -ra`: **3923 passed, 4 skipped in 1116.42s (0:18:36)**. Los cuatro skips son invitaciones que requieren demo.owner, ausente del arnés sin seed. Incluye 45 casos de servicios y 9 de 057; checkpoint previo de servicios: **40 passed in 55.15s**. Entorno Python 3.14, PostgreSQL y Redis reales, rol aplicativo sin BYPASSRLS. No hay router F1 registrado ni emisión F1; main.py, permisos HTTP, vistas públicas existentes y frontend intactos.

| Tareas | Evidencia de comportamiento |
|---|---|
| T25–T26 | HTTP test-only de capacidades sin datos privados; permisos independientes, contexto ajeno, 404 ajeno/inexistente, sesión revocada y usuario/organización/membresía inactivos. Snapshot vacío no escribe; lectores concurrentes y snapshot inicializado coherente. |
| T27–T28 | Reintento con mismo hash y ack mínimo, conflicto de cuerpo/sesión/revisión y permiso retirado; inicio concurrente único y rechazo de participantes ausentes/versión archivada. |
| T29–T30 | Suspender/reanudar desde running/paused/not_started conserva referencia sin autoarranque; captura suspendida denegada. Corrección running/paused con instante servidor, revisión obsoleta y minutos/content_revision de hechos intactos. |
| T31–T32 | Alta/corrección/retirada con marcador derivado y cero match_events; jugador ajeno, tiempo/segmento/equipo inválidos y límite 501 rechazados. Correcciones simultáneas no sobrescriben; fallo preserva contenido, orden validado igual al persistido y hechos de segmentos previos siguen corregibles/retirables. Catálogo vacío/desconocido y contratos estrictos cubiertos además por A1 en la suite completa. |
| T33 | 057: interrupción/completado CLOSE-only, pausa directa/otras operaciones/tenant ajeno denegados. Ruta existente de interrupción pausa; crear otro segmento conserva referencia/revisión detenida sin autoarranque. Migrador real limpio 001→057 e incremental 056→057 con dos tenants: 57 checksums estables al reejecutar y datos previos intactos. |
| T34 | Recibo append-only ligado a actor/sesión/content_revision/huella y conjunto completo; VIEW+CLOSE, resultado inválido y contenido obsoleto. Cambiar solo reloj no invalida revisión; sin congelación ni confirmación. |
| T35 | Fallos inducidos después de cambiar estado/hecho y antes del ack revierten estado, hechos, comando y auditoría; matches, standings, suspensiones/servicios, advancement_links y outbox quedan idénticos. |

Rojos conservados: servicios **17 failed** y revisión **5 failed**, inicialmente por acceso directo no permitido a organizations (corregido reutilizando fn_verify_user_org_membership; no se presenta como rojo funcional separado de cada conducta). Regresiones funcionales posteriores antes del fix: orden de corrección **1 failed, 34 deselected**; huella devuelta **1 failed, 5 deselected**; corregir/retirar hechos de segmentos previos **4 failed, 35 deselected**; 057 **2 failed, 7 deselected**. Todas quedan incluidas en el verde integral anterior. Dos ejecuciones integrales intermedias se interrumpieron para completar estas regresiones: no se cuentan como verificaciones completas.

**T36 cerrada con G-REMOTE y autorización del usuario**, con los runs y Review del SHA `b9a888ad` registrados arriba. Parte local inicial: suite completa anterior, Ruff `All checks passed!`, Bandit exit 0 (12 low, 0 medium/high); Gitleaks del árbol final de 058 sin fugas y árbol publicado idéntico al escaneado. No acredita fusión, aceptación F1, despliegue ni autoriza B2 antes de fusión/gates de B1.

## PR B2 — Cierre y avisos preparados (T37–T48)

Dependencia externa: B1 fusionado y sus gates verdes. Preparar cierre y avisos sin activar rutas productoras F1 ni cambiar todavía la ruta pública.

**Checkpoint local B2 (2026-11-14):** #82 fusionado según el usuario; rama nueva desde main actualizado. T37–T47 verificadas conjuntamente con `RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py tests/test_match_live_realtime.py tests/test_match_live_contracts.py tests/test_match_live_public.py tests/test_realtime_policy.py tests/test_rectification_flow.py`: **285 passed in 122.35s (0:02:02)**. Cada comando por filtro de las tareas es un subconjunto de esa ejecución. Caracterización clásica previa: **223 passed in 21.34s** en test_close_validation_order/test_walkover_close/test_close_authorization_db. Regresión completa y controles finales se registran en T48; no acredita G-REMOTE.

**Rojo → verde:** T37, **1 failed, 14 passed, 60 deselected**, `live_review_id` rechazado como extra; T39, **1 failed, 6 deselected**, el cliente clásico llegaba al UPDATE terminal y fallaba en el trigger en vez de exigir revisión (sin efectos persistidos). Ronda agregada inicial de cierre: **16 failed, 1 passed, 6 deselected**, dominada por el contrato aún ausente, no un rojo funcional independiente por cada carrera/rollback. Dos usos erróneos de dict como modelo en tests se corrigieron sin alterar la conducta de producto. T44: **6 failed** por módulo de unión aún ausente, no prueba roja separada de las 14 claves. T45/T47: **2 failed, 7 passed, 20 deselected**, evento cerrado no clasificado y outbox vacío tras un comando válido. Aislamiento de contratos: **3 failed, 75 deselected**, el recibo se heredaba indebidamente en revisión/033; ClassVar preserva esos contratos y rechaza el campo. Verde conjunto: **285 passed**. Carreras adicionales con barreras y aprobación real 033 se añadieron como regresiones de invariantes, sin atribuirles un rojo funcional propio.

**Límite de activación:** ningún router registrado ni llamada Redis en request; no se modifica main.py, el frontend, la ruta pública ni migraciones 001–058. El router clásico sigue sin pasar sesión al cierre F1; el argumento interno se prepara para B3 y nunca se infiere del UUID del recibo. Unión pública en módulo separado, no aplicada a HTTP. Avisos de comandos internos encolados atómicamente pero sin productores HTTP accesibles; emisión pública/revalidación y consumidores pertenecen a B3. Sin cambios de permisos HTTP ni desviaciones funcionales del plan.

La primera ejecución integral se interrumpió tras descubrir un doble clásico sin el nuevo atributo opcional: **1 failed, 1562 passed, 4 skipped**; no se cuenta como suite completa. Reproducción dirigida: **1 failed** (`AttributeError: SimpleNamespace.live_review_id`); consulta opcional compatible sin modificar el test, verde de todo `test_lock_order.py`: **17 passed in 0.38s**. La suite integral definitiva se registra debajo después de esa corrección.

La siguiente ejecución integral con parada al primer fallo detectó la regresión del seed clásico a esquema 043: **1 failed, 1711 passed, 4 skipped in 328.27s** (`relation match_live_state does not exist`). Tampoco se cuenta como completa. Se corrige consultando primero `to_regclass` en la lectura bloqueada; solo se consulta el estado si está disponible el esquema F1, y un partido sin estado conserva su DTO/camino clásico. No se modifica el seed, sus tests ni ninguna migración aplicada.
Verde posterior: `RUN_DATABASE_TESTS=1 pytest -q tests/test_match_result_immutability.py tests/test_close_validation_order.py tests/test_lock_order.py tests/test_match_live_close_db.py`: **264 passed in 55.93s** (incluye seed 043, cierre clásico y F1, recibos, rollback, carreras y rectificación).

- [x] **T37. Ampliar DTO de cierre sin abrir un bypass clásico de F1.** RF-019, RF-020, RF-022, RF-024; RNF-006
  - Tests primero: cierre clásico sin recibo intacto, variante F1 sin recibo/array vacío por defecto y campos extra; no aceptar subconjuntos del navegador.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_contracts.py -k close` y `cd backend && pytest -q tests/test_close_validation_order.py` validan `live_review_id` explícito y 422/409 previstos.

- [x] **T38. Extraer punto interno de integración sin transacciones anidadas.** RF-019, RF-020, RF-021, RF-022; RNF-003, RNF-006
  - Tests primero: caracterizar cierre original, walkover/administrativa, bloqueos y orden de errores antes del refactor.
  - Hecho cuando: `cd backend && pytest -q tests/test_close_validation_order.py tests/test_walkover_close.py` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_close_authorization_db.py` pasan con el mismo `begin` y autorización originales.

- [x] **T39. Revalidar recibo, resultado completo y contenido antes de consolidar.** RF-006, RF-019, RF-020, RF-023, RF-030
  - Tests primero: revisión stale por hecho/resultado, recibo de otra sesión/tenant, permiso retirado y reloj que avanza/corrige sin cambiar hechos.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k validate_review` produce errores aditivos sin invalidar revisión por meras observaciones del reloj.

- [x] **T40. Construir el DTO canónico desde todos los hechos vigentes del servidor.** RF-004, RF-007, RF-019, RF-024; RNF-003
  - Tests primero: omisión/orden/subconjunto enviado por cliente, retirados excluidos explícitamente, borrador vacío y reglas de resolución.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k canonical_report` conserva identidades y usa validadores actuales sin duplicar reglas ni elegir silenciosamente un subconjunto.

- [x] **T41. Consolidar hechos y congelar F1 dentro del cierre atómico actual.** RF-008, RF-019, RF-020, RF-021, RF-025
  - Tests primero: cierre válido completo, vacío válido y transición a terminal; efectos actuales se producen una vez.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k consolidation` confirma hechos/resultado/contadores/sanciones/clasificación/avance/outbox en una transacción, sin cambiar triggers de inmutabilidad.

- [x] **T42. Probar rollback de consolidación en puntos tardíos del cierre.** RF-019, RF-020, RF-021; RNF-004
  - Tests primero: errores test-only en sanciones, avance y outbox después de persistir hechos/congelar reloj.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k rollback` conserva borrador privado aceptado y no deja efectos o acta parcialmente confirmados.

- [x] **T43. Probar carreras cierre-edición/doble cierre y rectificación posterior.** RF-006, RF-019, RF-021, RF-022, RF-023
  - Tests primero: commits concurrentes y barreras reales; edición posterior a revisión y acta cerrada que solo admite 033.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k concurrency` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_rectification_flow.py` pasan sin duplicar hechos ni sobrescribir lo confirmado.

- [x] **T44. Definir modelos públicos por estado y serialización exacta del suspendido.** RF-009, RF-010, RF-028; RNF-002, RNF-006
  - Tests primero: 14 claves exactas incluyendo null, unión Pydantic, live con campos adicionales y otros estados sin nuevos defaults.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_public.py -k serialization` no añade lineup/fase/escudos/actores a suspended; la ruta pública todavía no se cambia.

- [x] **T45. Ampliar catálogo Python y adaptación SQL solo para el evento privado nuevo.** RF-012, RF-013, RF-014, RF-015, RF-027
  - Tests primero: scope organizativo sin version_id, referencias inválidas/extra, F9 y payload mínimo sin hechos/revisiones.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_realtime.py -k catalog` y `cd backend && pytest -q tests/test_realtime_policy.py` distinguen live de operation/version sin comodines ni cambios del wire antiguo.

- [x] **T46. Verificar paridad HTTP/SQL real para los nuevos lectores.** RF-012, RF-015, RF-016, RF-031; RNF-001
  - Tests primero: VIEW/OPERATE separados, multirol, oficial asignado a otro partido, plataforma y membresía/sesión inválidas.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k http_sql_parity` compara GET live del router test-only y autorización 056 bajo bracket_app, sin tomar el helper Python como prueba suficiente.

- [x] **T47. Encolar invalidaciones mínimas y condicionar público a cambios de proyección.** RF-008, RF-013, RF-014, RF-026, RF-027; RNF-002
  - Tests primero: comando aceptado/rechazado/repetido, tarjeta sin efecto público, cambio de score/estado/reloj y rollback transaccional.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k outbox` verifica IDs estables y worker existente sin Redis en request, sin ticks y sin avisos públicos por hechos exclusivamente privados.

- [x] **T48. Verificar checkpoint de cierre/avisos sin activar productores HTTP.** RF-013, RF-014, RF-019, RF-020, RF-021, RF-022, RF-027; RNF-002, RNF-006
  - Dependencias: T37–T47. Gate de preparación, no activación.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py tests/test_match_live_realtime.py` y `git diff --check` pasan; nuevo router no incluido y ruta pública antigua todavía compatible. Cumplir todos los gates y Review antes de la fusión autorizada de B2.
  - **Cerrada por G-REMOTE el 2026-11-14:** PR #83, SHA corregido **f05ebf960c47547509d57eea25ca20ddcacd5b7b**; `git_pr_checks(wait_mode="all")`: **7 passed, 0 failed, 0 pending, 0 skipped**. [pull_request 43605383194](https://github.com/edsel9ra/bracket-craft/actions/runs/43605383194) y [push 43605378892](https://github.com/edsel9ra/bracket-craft/actions/runs/43605378892) **success**; push con cuatro jobs correctos y E2E omitido conforme al workflow. Devin Review del SHA: **success**, «Completed analysis in 4m 11s». Resultado directo de Review `pr-review-job-7aacbf745fde4c079cf6fa49faa54434`: `head_sha` y `reviewed_head` corresponden a f05ebf96, `lifeguard_status=complete`, `bugs=[]`, `errored_tasks=null`; interfaz «Analysis complete / Nothing for you to triage». Ningún hallazgo pendiente. No se declara fusión, despliegue ni inicio de B3; el commit documental se verifica de nuevo tras publicarlo.
  - **Suites remotas del fix:** backend PR **4026 passed, 4 skipped in 1145.90s (0:19:05)**; backend push **4026 passed, 4 skipped in 1005.65s (0:16:45)**. Frontend **979 tests, 978 pass, 0 fail, 1 skipped**. E2E PR **66 passed (7.9m)**, **RESULTADO: VERDE (0)**. Infraestructura y seguridad correctas en ambos runs.
  - **Review #83 sobre 0cab6674, autorizado por el usuario:** rojo PostgreSQL **2 failed, 3 passed, 38 deselected in 7.72s**: con interrupción y nuevo segmento reales, el recibo previo falla en el cierre clásico pero una nueva revisión se aceptaba; también se admitía corregir conservando el segmento interrumpido. Corrección: revisar con estados reales, sin relajar el cierre 017; rechazar ese destino al corregir y conservar los hechos privados hasta su retirada/reasignación explícita, incluso varios pendientes. Regresiones de reparación y cierre vacío en `test_match_live_interrupted_segments_db.py`; 001–058, permisos, rutas y consumidores intactos.
  - **Verde del fix:** `RUN_DATABASE_TESTS=1 pytest -q` sobre los 21 archivos `test_match*`, `test_live*`, `test_close*`, `test_segment*`, `test_walkover*`: **895 passed in 300.19s (0:05:00)**, PostgreSQL real. Incluye el cierre clásico que sigue rechazando interrumpidos, rechazo de nueva revisión sin alterar hechos, retirada/reasignación parcial de dos hechos, identidades preservadas, cierre vacío y compatibilidad de segmentos completados. `ruff check app tests`: **All checks passed!**; `git diff --check`: exit 0.
  - **Backend integral local anterior al fix, PostgreSQL y Redis, Python 3.14:** `RUN_DATABASE_TESTS=1 pytest -q -ra --maxfail=1`: **4022 passed, 4 skipped in 1408.53s (0:23:28)**. Ejecutadas las 4026 pruebas, sin parada anticipada; 59 casos nuevos frente a B1. Los cuatro skips son invitaciones que requieren demo.owner, ausente en el arnés sin seed. Incluye cierre/validación/seed 043/033/035/056/057/058 y todos los casos B2; no se reemplaza por la ronda focalizada ni por las integrales incompletas. El fix añade otros cuatro casos, verificados también en las integrales remotas anteriores.
  - **Seguridad local original:** `ruff check app tests`: `All checks passed!`; `bandit -r app -ll`: exit 0, 12 low, 0 medium/high. Gitleaks sobre snapshot del árbol stageado y `git diff --check` finales se adjuntaron en el reporte de publicación. Frontend/E2E/G-INF y G-REMOTE no se acreditaron en aquel checkpoint local; su evidencia remota corresponde ahora al SHA corregido y a los runs indicados arriba.

## PR B3 — Exposición completa y activación (T49–T60)

Dependencia externa: B2 fusionado y sus gates verdes. Público exacto, consumidores compatibles y registro del router se entregan juntos; no activar T55 sin sus precondiciones.

Desviación autorizada el **2026-11-15**, respuesta del usuario **«Opción 1: migración 059 mínima (recomendada)»**: B3 incluye `059_live_selection_bracket_code.sql` para T49. La vista interna de selección de 056 no exponía `bracket_code` y sin él el suspendido no conserva el orden clásico antes de paginar. Solo se añade `bracket_code` al final de la vista interna; la salida pública sigue con sus 14 claves exactas, `stage_order` se resuelve con `v_public_stages` y 001–058 permanecen intactas. Diseño y alternativa descartada en plan.md. Pruebas: `RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_059.py`.

- [x] **T49. Integrar la unión pública en la ruta y paginación existentes.** RF-009, RF-010, RF-028; RNF-001, RNF-002, RNF-006
  - Tests primero: anónimo sin organización, suspendido entre páginas, filtro de fase/grupo, invisible/cancelado y organización ajena.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_public.py -k route` comprueba claves de respuesta HTTP reales, filtros/orden antes de serializar y estadísticas/actas vigentes ajenas al borrador.
  - Evidencia: rojo funcional previo **1 failed, 1 passed, 6 deselected** (suspendido ausente). Verde **2 passed, 6 deselected in 6.75s** — respuesta HTTP con exactamente las 14 claves, paginación de frontera consistente, filtros de fase/grupo, torneo invisible/cancelado y tenant ajeno indistinguibles, estadísticas y actas sin provisionales. `tests/test_migration_059.py` **3 passed in 3.67s** (columna interna, dos tenants, limpio/incremental/idempotente y privilegios). Regresión pública `test_public_access_matrix.py` + `test_public_field_allowlist.py` + `test_public_player_views.py` + `test_crest_public.py` + `test_migration_056/057/058.py`: **134 passed**; `test_rectification_flow.py` + `test_api_access.py` + `test_tournament_routes_order.py` + `test_photo_resolution.py`: **121 passed** tras fijar el flujo que lee `/matches` a `schema: 59`. `ruff check app tests`: **All checks passed!** Migración aplicada sobre la base compartida (001→059).

- [x] **T50. Emitir el aviso público nuevo solo tras revalidar visibilidad actual.** RF-009, RF-010, RF-013, RF-014, RF-027, RF-028; RNF-002
  - Tests primero: torneo ocultado después de encolar, referencias de otro tenant, nombre privado compartiendo identificadores y fallos de consulta.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k public_dispatch` no emite si no verifica visibilidad, conserva eventos públicos anteriores y nunca difunde el borrador al room organizativo.
  - Evidencia: rojo previo **3 failed, 15 passed** (el tipo nuevo no se emitía). Verde **18 passed, 24 deselected in 12.06s** — revalidación contra `v_match_live_public_selection` + `v_public_tournaments` con organización del sobre; wire exacto `{event_id, match_id, tournament_id}` al room del torneo verificado; torneo ocultado/organización inactiva/versión archivada/referencias ajenas no emiten; el nombre privado y los ámbitos organizativos quedan fuera del room público; fallo de consulta propaga al relay (posición no avanza → reintento) sin emitir; MATCH_UPDATED/MATCH_CLOSED/STANDINGS_UPDATED intactos. Regresión: `test_match_live_realtime.py` + `test_realtime_delivery.py` + `test_realtime_policy.py` + `test_outbox_resync.py` **214 passed** y `test_realtime_delivery_db.py` **61 passed** (requiere `REDIS_URL=redis://172.17.0.3:6379/0` en el contenedor). `ruff check`: **All checks passed!**

- [x] **T51. Suscribir nombres nuevos en el único dispatcher cliente con deduplicación.** RF-013, RF-014, RF-017, RF-018; RNF-002, RNF-004
  - Tests primero: duplicados, payload vacío/desconocido y RESYNC; sin otro socket/listener de rectificación.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-realtime.test.ts` conserva el catálogo antiguo y enruta las dos señales nuevas sin suscripciones duplicadas.
  - Evidencia: rojo previo (export `parseLiveInvalidationPayload` ausente). Verde **8 tests, 0 fail** — ambas señales enrutan a `onMatchLiveUpdated`/`onMatchLivePublicUpdated` con wire normalizado de tres identificadores (extras descartados, payload vacío/malformado solo llega a `onEvent`), dedupe corta repeticiones y catálogo antiguo + RESYNC intactos. Suite completa `pnpm test`: **986 passed, 0 failed, 1 skipped**; `vue-tsc --noEmit` limpio; `pnpm run lint` limpio. Contenedor `bc-b3-node` (node:24-slim) monta el repo con pnpm 12.12.1.

- [x] **T52. Coordinar reconstrucción HTTP de operation/capacidades/live con guardas.** RF-012, RF-015, RF-016, RF-017, RF-018; RNF-001, RNF-004
  - Tests primero: permiso perdido, respuesta antigua tras cambio de contexto, busy/trailing reload y denegación live sin perder historial 033 autorizado.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-context.test.ts` demuestra useApi, contexto/generación y limpieza 401/403/404 vigentes sin remontar componentes.
  - Evidencia 2026-11-15: rojo previo (`ERR_MODULE_NOT_FOUND` al resolver el módulo del coordinador antes de existir). `utils/matchLiveContext.ts` con `createLiveContextCoordinator` sobre `createReloadCoordinator` (una corrida + una trailing, generación por corrida, `isCurrent` tras cada await); `live/access` autoriza la lectura del borrador y `can_view=false`/401/403/404 limpia capacidades y borrador; la denegación solo del borrador conserva historial y capacidades; el fallo no denegación conserva el estado vigente. `useMatchOperation` dispara `onMatchLiveUpdated` y cada decisión `reload` reconstruye operation + capacidades + live; cambio de contexto limpia ambos refs. 9/9 verde; `vue-tsc` y `eslint` limpios; suites relacionadas 53/53.

- [x] **T53. Adaptar vista pública mínima y agrupación sin inventar campos del suspendido.** RF-009, RF-010, RF-011, RF-028; RNF-002, RNF-005, RNF-006
  - Tests primero: primera carga sin caché, SSR, tarjetas mínimas en consulta general, filtro de origen y marcador provisional/referencia nula.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-public.test.ts` muestra suspendido sin exigir stage_id/lineup/bracket_code y no duplica partidos al cambiar de estado.
  - Evidencia 2026-11-15: rojo previo (exportaciones `SuspendedPublicMatch`/`mergeMatchEntries` ausentes). `publicTournament.ts`: `SuspendedPublicMatch` (14 claves), `PublicMatchState` unión, `normalizePublicMatchState/Page` que descarta objetos malformados sin rellenar nulos, `PublicMatchEntry{match,stageId,groupId}` con el contexto de la consulta fuera del objeto, `mergeMatchEntries` deduplicando por `id` al cambiar de estado, `bracketEligibleMatches` (sin llave, nunca entra al bracket) y `formatSuspendedClock` (MM:SS, null con referencia ausente). `[id].vue` guarda el contexto en la entrada; las tarjetas del suspendido muestran solo nombres, marcador provisional y reloj detenido. 7/7 verde; suite completa **1002 passed, 0 failed, 1 skipped**; `vue-tsc`/`eslint` limpios.

- [x] **T54. Reconocer F1 en Workspace y bloquear el cierre desde una copia local clásica.** RF-019, RF-020, RF-021, RF-024; RNF-006
  - Tests primero: cliente clásico contra F1 inicializado, falta de VIEW/recibo y partido clásico sin F1.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-close.test.ts` no envía una copia local como acta F1 ni borra su texto ante rechazo; cierre clásico sigue igual.
  - Evidencia 2026-11-15: rojo previo (módulo `matchLiveClose` ausente). `utils/matchLiveClose.ts`: `isLiveInitialized` exige `initialized===true` explícito (sin VIEW no hay snapshot → nunca se interpreta como F1) y `classifyLiveCloseConflict` lee los 409 `LIVE_REVIEW_REQUIRED`/`LIVE_REVIEW_STALE` desde `detail` (no el `code` aditivo deportivo). `useMatchClose.closeMatch` bloquea el envío clásico con `match.liveReviewRequired` cuando el snapshot autorizado declara el partido F1, sin tocar `draftEvents` ni el borrador persistido; el 409 del servidor en el camino sin VIEW se clasifica con `match.liveReviewStale`/Required y conserva el texto local. Clásico sin F1 inalterado; i18n ES/EN. 3/3 verde; suite completa **1005 passed, 0 failed, 1 skipped**; `vue-tsc`/`eslint` limpios.

- [x] **T55. Registrar el router completo y verificar las precondiciones de activación.** RF-001, RF-003, RF-012, RF-013, RF-019, RF-028, RF-031; RNF-001, RNF-006
  - Dependencias: T25–T54 completas, público y consumidores compatibles, revisión de seguridad del diff; B1/B2 fusionados.
  - Tests primero: rutas reales de la aplicación, auth/CSRF y ausencia de bypass por rutas antiguas.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py tests/test_match_live_close_db.py tests/test_match_live_public.py` pasa a través del montaje real, no solo el router test-only. El despliegue exige suspender escrituras y detener toda API/relay antigua antes de reabrir tráfico; no se introduce flag oculto ni rolling mixto.
  - Evidencia 2026-11-15: rojo previo (sin rutas `/live` productivas). `modules/matches/live_router.py` nuevo: GET `/live`, GET `/live/access`, POST `/live/commands` y POST `/live/reviews` (201 `LiveReviewResponse` cerrado: `live_review_id`/`content_revision`/`report`/`fingerprint`), incluido en `api` bajo `/api/v1`; `close_match` resuelve `session_id` del `jti` (dependency `get_session_id` en `core/security.py`) para exigir el recibo del actor. Tests reales: tabla de rutas vía `effective_candidates` (montaje perezoso `_IncludedRouter`), 401 sin sesión, 403 `Token CSRF inválido` con credenciales sin token, snapshot `initialized=false` sin crear estado, comando `start_clock`→ack, revisión→recibo y `/close` clásico rechazado `LIVE_REVIEW_REQUIRED` (bypass ausente) y aceptado con `live_review_id`. 80/80 verde (`live_db`+`live_close_db`+`live_public`); `test_match_live_realtime`+`test_rectification_flow` 101/101; Ruff/bandit limpios.

- [x] **T56. Comprobar entrega privada real en dos API y dos tenants.** RF-012, RF-013, RF-014, RF-016, RF-018, RF-031; RNF-001, RNF-004
  - Tests primero: arnés multiproceso existente, sockets reales autorizados/denegados y lectura HTTP posterior; sin mock de emisión.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k multiprocess_delivery` observa únicamente los tres identificadores en receptores permitidos y cero frames de dominio en ajenos.
  - Evidencia 2026-11-15: rojo previo (fixture `flow` no importada). `test_multiprocess_delivery_two_apis_two_tenants` reutiliza `realtime_process.ProcessCluster` con `flow` schema 59: dos procesos uvicorn distintos (pid verificado), sockets del mismo principal en ambos procesos reciben exactamente `{event_id, match_id, tournament_id}`; miembro con rol `permissions='[]'` y receptor del tenant 32000000 reciben cero frames `MATCH_LIVE_UPDATED` (solo control); lectura HTTP posterior `GET /live/access` → 200 con las cuatro claves estrictas y `can_view:true`. 1/1 en `-k multiprocess_delivery`, 43/43 del archivo verde; Ruff limpio.

- [x] **T57. Comprobar retiradas, fallos y recuperación de entrega sin replay.** RF-015, RF-016, RF-017, RF-018; RNF-001, RNF-004
  - Tests primero: retirada confirmada en barrera, expiración real de sesión/JWT, fallo SQL/fila ausente, recuperación y contexto cambiado.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k multiprocess_recovery` prueba corte/fail-closed/RESYNC real sin caché de permisos ni prometer retirar frames previamente aprobados.
  - Evidencia 2026-11-15: rojo previo (tests inexistentes). `test_multiprocess_recovery_cutoff_fail_closed_no_replay` (session/membership/roles/live_view sobre ProcessCluster schema 59): lote pendiente en barrera `gate` se evalúa al inicio; tras retirada real el frame jamás llega a ambos sockets ni al tenant 32000000, la rama `live_view` conserva la lectura clásica y muestra `can_view:false` en `/live/access`. `test_multiprocess_recovery_sql_failure_suspends_and_resyncs`: `fail:true` suspende sin entregar `lost`, `recover` no repite frames (solo RESYNC/negación), sesión expirada no se resuscribe y eventos nuevos van solo al socket vigente del otro proceso. 5/5 en `-k multiprocess_recovery`, 48/48 del archivo; Ruff limpio.

- [x] **T58. Verificar matriz pública y clásica de extremo a extremo antes de ofrecer captura UI.** RF-008, RF-009, RF-010, RF-022, RF-027, RF-028; RNF-002, RNF-006
  - Tests primero: flujo por HTTP y espectadores reales, suspensión/reanudación, ocultación del torneo y acta rectificada vigente.
  - Hecho cuando: `cd frontend && pnpm exec playwright test e2e/realtime-public.spec.ts --project public` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_public_access_matrix.py tests/test_public_field_allowlist.py` no revelan hechos ni datos excluidos.
  - Evidencia 2026-11-15: matriz backend 10/10 verde sobre schema 59; pila Compose completa (db-migrate→api/worker/web, arnés `realtime_e2e_server`) con seed demo real y Chromium del runner (`pnpm exec playwright test e2e/realtime-public.spec.ts --project public`): **3 passed en 53.6s** — matriz pública anónima HTTP/rooms sin variantes F1/F9/probes y reintento manual con canal bloqueado; sin hechos ni datos excluidos. Entorno: `bc-b3-node` unido a `bracket-craft_default` con proxies TCP localhost:8000→api:8000 y localhost:3000→172.17.0.1:3000; Chromium con libs instaladas en el contenedor.

- [x] **T59. Ejecutar gate backend/BD/seguridad de B3 y registrar trazabilidad del servidor.** RF-003, RF-007, RF-008, RF-012, RF-019, RF-020, RF-022, RF-027, RF-031; RNF-001, RNF-003, RNF-006
  - Dependencias: T25–T58. Gate, sin rojo artificial; esperas de suites aparte.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q` y `cd backend && python -m compileall -q app`, más G-BE/G-INF/G-SEC pasan y las salidas saneadas quedan asociadas al SHA; no se posponen controles esenciales a C.
  - Evidencia 2026-11-15: suite completa `pytest -q` con BD **4091 passed, 5 skipped en 11:09**; `compileall -q app` exit 0; `ruff check app tests` limpio; `bandit -r app -ll` 0 medium/high; gitleaks v8.30.1 (SHA de CI) sobre `git archive HEAD` sin fugas. Correcciones previas al verde: el barrido de la spec 019 exige modelo por operación — `LiveCommandRequest` (RootModel sobre la unión discriminada `LiveCommand`, mismo JSON en el wire) registrada junto a `LiveReviewRequest` en `test_request_schema_strictness.py` (46 operaciones, 40+17 modelos, cuerpos mínimos y rama RootModel en forbids/rejects); la nueva dependencia `get_session_id` de `/close` queda sustituida en los fixtures `api_client`/`close_client`/`flow` y la firma `execute(..., session_id)` tolerada en los dobles de `test_match_minutes.py`.

- [x] **T60. Ejecutar gates frontend/E2E/CI y comprobar fusión autorizada de B3.** RF-009, RF-013, RF-016, RF-017, RF-018, RF-019, RF-028; RNF-002, RNF-004, RNF-005, RNF-006
  - Dependencias: T59; todos los controles B listos. Gate, esperas de CI aparte.
  - Hecho cuando: `cd frontend && pnpm test`, `cd frontend && pnpm run e2e:test` y `git diff --check`, más G-FE/G-E2E/G-REMOTE pasan; evidencias y Review revisadas. B3 solo se declara fusionado tras evidencia de la fusión autorizada y conserva G-INF/G-SEC de T59.
  - Evidencia local 2026-11-15: `pnpm test` **1005 pass, 0 fail, 1 skipped**; `pnpm run lint` (eslint) limpio; `pnpm run typecheck` y `pnpm run typecheck:e2e` exit 0; `pnpm run build` exit 0; `git diff --check` limpio; `pnpm run e2e:test` contra la pila Compose completa (override `docker-compose.realtime.yml`, seed demo real) **66 passed en 7.0m, RESULTADO: VERDE (0)** — incluye `realtime-public` (3) y `private-realtime` (11).
  - G-REMOTE 2026-11-15: push autorizado, PR #84 abierto sobre `39a4aa1b`; CI **7/7 verde** (backend, frontend, infra, security+GitGuardian, realtime E2E, Devin Review success). Revisión triada: 5 hallazgos resueltos (`d72907b3` marcadores provisionales live; `a56f8e9c` contexto de grupo del objeto clásico; `4a505571` handler público `MATCH_LIVE_PUBLIC_UPDATED` + tarjeta del suspendido en eliminatorias; `49351a09` carga inicial del contexto live) y 1 rechazado (live sin `match_live_state` imposible: `start` crea ambos en una transacción). Prueba UI-driven con agente de testing: todas las aserciones pasadas, video/comentario E2E en el PR. **Fusión autorizada verificada: `55fde43f` en `main`**.

## PR C1 — Interfaz operativa (T61–T72)

Dependencia externa: B3 fusionado con gates verdes; no se difiere seguridad del servidor hasta este PR. C1 proporciona un recorrido operativo completo antes de C2.

- [x] **T61. Separar editor compartido y estado clásico local en el composable.** RF-004, RF-005, RF-012, RF-024; RNF-004, RNF-006
  - Tests primero: carga de F1, vacío, modo clásico y error; ningún hecho local se considera aceptado sin HTTP.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-editor.test.ts` mantiene snapshots separados y usa exclusivamente useApi.
  - Evidencia 2026-11-15: `match-live-editor.test.ts` **8/8 pass** (rojo inicial por módulo ausente; verde tras la utilidad). `utils/matchLiveEditor.ts` nuevo: `normalizeLiveSnapshot` espeja `LiveSnapshotResponse` (extra=forbid en raíz y por hecho; `initialized:false` → modo clásico con `shared:null`; reloj coherente por estado e instantes UTC). `LiveEditorState` separa `shared` (aceptado por HTTP) de `pending` (capturas locales, nunca presentadas como aceptadas); `applySharedSnapshot` reconoce pendientes aceptados y conserva los locales ante respuesta inválida. `useMatchOperation` crea `liveEditor` reactivo alimentado en `applyLive`, limpio en denegaciones y vacío completo ante cambio de contexto; lecturas solo por `request` de useApi. `pnpm run lint` y `pnpm run typecheck` limpios.

- [x] **T62. Resolver explícitamente un borrador clásico antes de iniciar F1.** RF-001, RF-019, RF-024; RNF-006
  - Tests primero: borrador local presente/ausente, cancelación de confirmación y fallo de inicio; no importación ni pérdida automática.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-local-draft.test.ts` conserva texto hasta decisión expresa y no reenvía eventos locales como borrador compartido.
  - Evidencia 2026-11-15: `match-live-local-draft.test.ts` **7/7 pass**. `utils/matchLiveLocalDraft.ts` nuevo: `createLocalDraftResolver` — sin borrador procede sin confirmar; con borrador pide decisión expresa (`keep` conserva intacto / `discard` limpia expreso / cancelar o fallo aborta el inicio sin tocar texto); `markPending` nunca recibe hechos locales. `useMatchOperation` crea `localDraftResolver` con dos confirmaciones `useConfirm` (descartar → conservar → cancelar aborta), `hasUnsavedDraft` como detector y `clearDraft()` nuevo sin confirmación propia en `useMatchEventsDraft` (`discardDraft` = confirmar + `clearDraft`). Claves ES/EN `live.localDraft.*`. Lint y typecheck limpios.

- [x] **T63. Capturar incidencias compartidas con aceptación y errores saneados.** RF-004, RF-005, RF-007, RF-023, RF-024; RNF-005
  - Tests primero: captura válida, campos vacíos, catálogo inválido, error/timeout y doble activación.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-capture.test.ts` espera ack y snapshot autorizado, conserva formulario si falla y no duplica hechos por reintento.
  - Evidencia 2026-11-15: `match-live-capture.test.ts` **9/9 pass**. `utils/matchLiveCapture.ts` nuevo: `validateLiveEventForm` espeja `MatchEventPayload` (UUIDs, catálogo cerrado, minutos 0–180/0–30, pareja de sustitución, beneficiario de autogol, asistencia solo en gol, metadata solo `red_card_type`, extra=forbid). `createLiveCapture`: sin compartido → `unavailable`; single-flight → `busy`; `add_event` con `command_id` estable + `expected_revision`; ack solo vale si devuelve el mismo `command_id`; el hecho queda `pending` y espera `requestSnapshot` antes de presentarse aceptado; reintento con `client_event_id` pendiente/aceptado no repite el POST; fallos clasificados `conflict`/`denied`/`error` y el formulario jamás se muta. `useMatchOperation` crea `liveCapture` sobre `request`+`liveContext.request`+`crypto.randomUUID`. Lint y typecheck limpios.

- [x] **T64. Corregir/retirar hechos con confirmación y conflicto explícito.** RF-006, RF-007, RF-023, RF-026; RNF-005
  - Tests primero: modificación válida, cancelación, revisión obsoleta y hecho retirado por otro operador.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-edit.test.ts` conserva edición ante conflicto, usa useConfirm/single-flight y obliga a revisar la base antes de guardar.
  - Evidencia 2026-11-15: `match-live-edit.test.ts` **11/11 pass**. `utils/matchLiveEdit.ts` nuevo: `createLiveEdit` mantiene `LiveEditSession` (`baseRevision`, `stale`, `removed`); un compartido avanzado durante la edición o un hecho retirado por otro operador marca `stale`/`removed` y `saveEdit` exige `reviewBase()` antes de enviar `correct_event` con la revisión vigente; 409 marca la base obsoleta sin perder texto. Single-flight cubre la confirmación (`useConfirm` `correct`/`remove`, `remove` en danger); ack exige el `command_id` enviado. `useMatchOperation` crea `liveEdit`, `applyLive` llama `onSharedChanged` y el cambio de contexto cierra la sesión. Claves ES/EN `live.edit*`. Lint y typecheck limpios.

- [x] **T65. Presentar lector y operador según capacidades independientes.** RF-012, RF-015, RF-016, RF-031; RNF-001, RNF-005
  - Tests primero: VIEW sin OPERATE, OPERATE sin VIEW, observador, retirada y multirol; UI no es la barrera de seguridad.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-access.test.ts` no revela detalle por poder escribir ni ofrece cierre por herencia de OPERATE; denegaciones vigentes limpian lo privado.
  - Evidencia 2026-11-15: `match-live-access.test.ts` **8/8 pass**. `utils/matchLiveAccess.ts` nuevo: `deriveLiveView` produce `{mode, detailVisible, controlsEnabled, closeEnabled}` — `detailVisible` solo con `can_view` (escribir no concede leer), `controlsEnabled` con `can_view && can_operate`, `closeEnabled` solo con `can_close` (nunca por herencia de OPERATE); `null`/inválida/`available:false` → `hidden` completo. `useMatchOperation` expone `liveView` computed sobre `liveAccess`; las denegaciones vigentes ya limpian lo privado vía `denyAccess`/`denyLive`.

- [x] **T66. Añadir controles y presentación de reloj con tiempo inyectable.** RF-011, RF-017, RF-029, RF-030; RNF-003, RNF-004, RNF-005
  - Tests primero: sin iniciar, running/paused, desactualizado, corrección y reconexión; sin intervalos que escriban al servidor.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-clock.test.ts` conserva hechos/minutos al corregir reloj y distingue cálculo visual de referencia aceptada.
  - Evidencia 2026-11-15: `match-live-clock.test.ts` **9/9 pass**. `utils/matchLiveClock.ts` nuevo: `displayedClock` calcula elapsed = `elapsed_us` aceptado + tramo desde `anchor_at` solo si `running` (computed), con `now` inyectable — not_started muestra 0 sin inventar referencia, paused no avanza; `clockPresentation` marca `stale` cuando la conexión no está `connected` (desactualizado, nunca tiempo oficial). `createLiveClock` envía `start_clock`/`pause_clock`/`resume_clock`/`correct_clock` con `command_id`+`expected_revision`, valida entradas y single-flight; corregir solo cambia la referencia (hechos/minutos intactos). `useMatchOperation` crea `liveClock`.

- [x] **T67. Añadir controles de inicio, suspensión y reanudación del partido.** RF-001, RF-002, RF-003, RF-025, RF-029; RNF-005
  - Tests primero: estados válidos/terminales, cancelación de confirmación, error/ocupado y suspensión sin referencia.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-transitions.test.ts` bloquea captura/control durante suspended y no arranca reloj ni crea segmento al reanudar.
  - Evidencia 2026-11-15: `match-live-transitions.test.ts` **8/8 pass**; conjunto live (capture/edit/clock/transitions) **37/37**. `utils/matchLiveTransitions.ts` nuevo: `createLiveTransitions` con `start`/`suspend`/`resume` — `start` solo sobre `scheduled` sin compartido, resuelve el borrador clásico antes de confirmar; `suspend` exige `live`; `resume` exige `suspended` y solo devuelve a `live` (sin arrancar reloj ni crear segmento, RF-029). `isDraftEditable` (matchLiveEditor) bloquea captura/corrección/reloj con `status !== 'live'` → `unavailable`. `useMatchOperation` crea `liveTransitions` con `useConfirm`; claves ES/EN `live.transition.*`.

- [x] **T68. Mostrar revisión expresa del conjunto completo y resultado a cerrar.** RF-006, RF-019, RF-024, RF-030; RNF-005
  - Tests primero: lista completa/vacía, cambio de hechos/resultado y reloj que avanza sin invalidar revisión.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-review.test.ts` muestra el conjunto vigente completo y exige nuevo recibo ante cambio real, sin selector de subconjunto silencioso.
  - Evidencia 2026-11-15: `match-live-review.test.ts` **7/7 pass**. `utils/matchLiveReview.ts` nuevo: `reviewModel` expone el conjunto vigente completo en orden del servidor (vacío se muestra vacío, sin inventar incidencias, RF-024). `createLiveReview.beginReview` envía `expected_content_revision` + `result` validado (espejo `LiveResultDTO`: sin hechos ni `live_review_id`, extra=forbid) a `POST .../live/reviews`; guarda el recibo `{liveReviewId, contentRevision, fingerprint, report}`. `receiptValid` solo con el `content_revision` revisado — un avance del reloj (`revision` solo) no invalida; un cambio real exige nuevo recibo (RF-019). `useMatchOperation` crea `liveReview`.

- [ ] **T69. Confirmar el cierre usando recibo sin perder el borrador ante errores.** RF-019, RF-020, RF-021, RF-022, RF-024; RNF-004, RNF-006
  - Tests primero: éxito, 409 stale, fallo transaccional, 401/403/404 vigentes y autorización de cierre retirada.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-close.test.ts` envía el recibo/resultado revisados, no un subconjunto de eventos, conserva borrador no confirmado y termina modo provisional solo tras cierre aceptado.

- [ ] **T70. Integrar edición en curso, invalidaciones y recarga aplazada sin pérdida.** RF-006, RF-016, RF-017, RF-018, RF-023; RNF-004
  - Tests primero: aviso durante escritura, ráfaga, trailing reload, respuesta vieja y cambio de organización/identidad.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-context.test.ts tests/match-live-editor.test.ts` no remonta, no cierra editor ni restaura información revocada, y recupera mediante HTTP autorizado.

- [ ] **T71. Completar ES/EN y accesibilidad de todos los controles F1.** RF-003, RF-007, RF-017, RF-019, RF-029; RNF-005
  - Tests primero: mensajes/claves en ambos idiomas, aria-invalid/describedby, teclado, focus y estado no dependiente del color.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-accessibility.test.ts` y `cd frontend && pnpm run lint` pasan sin diálogos nativos ni imports implícitos inválidos.

- [ ] **T72. Verificar interfaz completa antes del checkpoint C1.** RF-001, RF-004, RF-011, RF-016, RF-019, RF-024, RF-029, RF-030; RNF-004, RNF-005, RNF-006
  - Dependencias: T61–T71. Gate, sin rojo artificial.
  - Hecho cuando: `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck` y `cd frontend && pnpm run e2e:test`, más G-FE/G-E2E pasan; además todos los gates comunes/Review y fusión autorizada de C1 se verifican antes de C2.

## PR C2 — Verificación ampliada y aceptación (T73–T84)

Dependencia externa: C1 fusionado y sus gates verdes. Ampliar evidencias sin posponer controles esenciales; T84 exige aceptación humana expresa y no se completa por la aprobación de estas tareas.

- [ ] **T73. Ampliar E2E del recorrido completo provisional→suspensión→cierre.** RF-001, RF-002, RF-004, RF-005, RF-008, RF-019, RF-021, RF-024, RF-029; RNF-006
  - Tests primero: dos lectores, operador, espectador y cierre con recibo; normal, borrador vacío válido y rechazo con hechos inválidos.
  - Hecho cuando: `cd frontend && pnpm exec playwright test e2e/operationFlow.spec.ts --project operation-flow` cubre recorrido F1 real y clásico sin actualizar manualmente ni adelantar efectos confirmados. Conservar los nombres/proyectos reales del config al ampliar los escenarios.

- [ ] **T74. Ampliar E2E privado con edición abierta y RESYNC real.** RF-006, RF-016, RF-017, RF-018, RF-023; RNF-004
  - Tests primero: publicación mientras se escribe, desconexión de transporte real, trim/reset y recuperación del estado autorizado en otro receptor.
  - Hecho cuando: `cd frontend && pnpm exec playwright test e2e/private-realtime.spec.ts --project private-realtime` comprueba hechos y marcador actuales sin botón Actualizar, conserva edición y no usa replay ni mocks de reconexión.

- [ ] **T75. Ampliar regresión de revocación/cambios de contexto con respuestas en vuelo.** RF-012, RF-015, RF-016, RF-031; RNF-001, RNF-004
  - Tests primero: retirada de lectura con OPERATE vigente, salida de organización, sesión vencida y A→B→A, con respuesta vieja exitosa/denegada.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-context.test.ts` y `cd frontend && pnpm exec playwright test e2e/private-realtime.spec.ts --project private-realtime` no restauran datos/reenvíos ajenos; el cliente solo recupera al reautorizar.

- [ ] **T76. Ampliar recuperación backend entre procesos con reinicio real.** RF-015, RF-017, RF-018, RF-023; RNF-001, RNF-004
  - Tests primero: repetir suspensión de autorización, revocación durante fallo, reinicio API y reconexión al otro proceso usando helpers 035.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k restart_recovery` preserva estado aceptado, no reproduce backlog privado ni recupera permisos antiguos.

- [ ] **T77. Ejecutar carga reproducible de entrega F1 reutilizando el arnés real.** RF-013, RF-014, RF-015, RF-018; RNF-001, RNF-004
  - Tests primero: lote 256/257, dos API, 1.000 sockets/100 principales, ráfagas y fallo/recuperación; no crear generador productivo.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k load` registra p50/p95, SQL/batching/RSS y ausencia de fuga/duplicación con receptores reales, sin inventar SLA ni memoria constante.

- [ ] **T78. Verificar visualmente reloj, suspensión y revisión en desktop/móvil.** RF-009, RF-011, RF-017, RF-019, RF-028, RF-029; RNF-005
  - Dependencias: T73–T75; caracterización visual de las superficies modificadas, no build como sustituto.
  - Hecho cuando: tras `cd frontend && pnpm exec playwright test e2e/realtime-public.spec.ts --project public`, se renderizan y ejercitan en pantalla pública/Workspace los estados live/paused/suspended/desactualizado y revisión con teclado en ambos tamaños; PNG/manifiesto saneados se guardan en ubicación persistente y sus rutas se registran. Un problema visual se corrige y se revalida solo su superficie.

- [ ] **T79. Auditar privacidad de logs/artefactos y exclusiones F9/F13.** RF-008, RF-013, RF-014, RF-022, RF-026, RF-027; RNF-001, RNF-002
  - Tests primero: payloads con campos prohibidos, catálogo desconocido, F9/sonda y dato personal que no debe acabar en salida técnica/pública.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_realtime.py -k privacy` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_public_field_allowlist.py` pasan; se revisan además logs/JSON reales de T73–T78 sin publicar secretos ni hechos privados.

- [ ] **T80. Actualizar manual, README y AGENTS con contratos/permisos finales.** RF-009, RF-012, RF-019, RF-022, RF-027, RF-028, RF-031; RNF-002, RNF-005, RNF-006
  - Documentación: 14 claves exactas, permisos independientes, suspensión/reloj, recuperación HTTP, cierre/rectificación y modos clásico/F1.
  - Hecho cuando: `git diff --check` y `python3 infra/scripts/verify_version_sources.py --exclude-constitution` pasan; 020/036 y manual son coherentes, F9 sigue fuera y la implementación se presenta pendiente de aceptación, no cerrada por CI.

- [ ] **T81. Documentar y ensayar despliegue coordinado y límite de rollback.** RF-003, RF-019, RF-021, RF-022, RF-025; RNF-004, RNF-006
  - Caracterización: 056 antes de backend, pausa de escrituras, drenaje/parada de API/relay antiguos, consumidores compatibles y reapertura; sin rolling mixto ni flag nuevo.
  - Hecho cuando: `docker compose config -q` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k legacy_bypass` pasan; un ensayo local controlado registra versiones/orden y demuestra que el cliente clásico no cierra F1. Rollback antiguo tras crear F1 queda explícitamente no soportado; corrección hacia delante, sin borrar esquema/datos.

- [ ] **T82. Ejecutar gates finales backend/infraestructura/seguridad y auditoría constitucional.** RF-003, RF-008, RF-012, RF-019, RF-020, RF-022, RF-026, RF-027, RF-031; RNF-001, RNF-002, RNF-003, RNF-004, RNF-006
  - Dependencias: T73–T81. Gate, esperas de suites aparte.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q` y `python3 infra/scripts/verify_version_sources.py --exclude-constitution`, más G-BE/G-INF/G-SEC pasan; tabla constitucional del Plan y matriz de cada RF/RNF tienen evidencia con SHA y límites, no solo casillas marcadas.

- [ ] **T83. Ejecutar gates finales frontend/E2E, CI y Review antes de solicitar aceptación.** RF-009, RF-011, RF-016, RF-017, RF-018, RF-019, RF-028, RF-029, RF-030; RNF-002, RNF-004, RNF-005, RNF-006
  - Dependencias: T82. Gate y documentación de evidencias; esperas remotas aparte.
  - Hecho cuando: `cd frontend && pnpm test`, `cd frontend && pnpm run e2e:test`, `git diff --check` y G-FE/G-E2E/G-REMOTE pasan para el SHA final, con push/PR comprobados por separado y hallazgos triados. La fusión de C2 se verifica solo si el usuario la decide; no confundirla con aceptación de F1.

- [ ] **T84. Obtener aceptación humana explícita de F1 y cerrar la spec solo entonces.** RF-001, RF-019, RF-021, RF-022, RF-028, RF-031; RNF-001, RNF-002, RNF-003, RNF-004, RNF-005, RNF-006
  - Dependencias: T1–T83 verificadas, entregas integradas según la decisión del usuario y evidencia final disponible. Ningún test/merge sustituye esta decisión.
  - Hecho cuando: se registra fecha y texto de aceptación del usuario tras presentar evidencias/límites; solo entonces se marca implementación aceptada y se actualizan spec/Plan/tareas/MEMORY/documentación. Pasan `git diff --check` y `python3 infra/scripts/verify_version_sources.py --exclude-constitution`; cualquier commit de cierre vuelve a verificar CI. Sin respuesta expresa, T84 permanece abierta y no se declara F1 implementada/aceptada.

## Matriz de cobertura de las tareas aprobadas

Cada requisito tiene al menos una tarea funcional o de verificación, además de los gates; las referencias siguientes no acreditan su cumplimiento hasta ejecutar las tareas.

| Requisito | Tareas principales |
|---|---|
| RF-001 | T7, T12, T28, T55, T62, T67, T73 |
| RF-002 | T6, T7, T12, T29, T67, T73 |
| RF-003 | T1, T3, T7, T17, T27, T28, T29, T33, T55, T67 |
| RF-004 | T4, T8, T13, T31, T40, T61, T63, T73 |
| RF-005 | T4, T8, T13, T26, T31, T32, T61, T63 |
| RF-006 | T9, T32, T34, T39, T43, T64, T68, T70, T74 |
| RF-007 | T3, T4, T8, T27, T31, T32, T35, T40, T63, T64 |
| RF-008 | T8, T12, T13, T17, T28, T31, T35, T41, T58 |
| RF-009 | T19, T44, T49, T50, T53, T58, T78, T80 |
| RF-010 | T19, T44, T49, T50, T53, T58 |
| RF-011 | T5, T6, T12, T29, T30, T33, T53, T66, T78 |
| RF-012 | T1, T2, T16, T18, T21, T22, T25, T26, T46, T52, T56, T65, T75 |
| RF-013 | T18, T22, T45, T47, T50, T51, T56, T77, T79 |
| RF-014 | T18, T23, T45, T47, T50, T51, T56, T77, T79 |
| RF-015 | T18, T22, T45, T46, T52, T57, T65, T75, T76, T77 |
| RF-016 | T21, T25, T26, T46, T52, T56, T57, T65, T70, T74, T75 |
| RF-017 | T5, T51, T52, T57, T66, T70, T74, T76, T78 |
| RF-018 | T26, T51, T52, T56, T57, T70, T74, T76, T77 |
| RF-019 | T4, T9, T15, T34, T37, T38, T39, T40, T41, T42, T43, T54, T68, T69, T73 |
| RF-020 | T9, T15, T34, T37, T38, T39, T41, T42, T54, T69 |
| RF-021 | T1, T17, T38, T41, T42, T43, T54, T69, T73, T81 |
| RF-022 | T1, T23, T37, T38, T43, T58, T69, T79, T80, T81 |
| RF-023 | T9, T14, T15, T27, T30, T32, T35, T39, T43, T63, T64, T70, T74, T76 |
| RF-024 | T4, T8, T13, T26, T31, T34, T37, T40, T54, T61, T62, T63, T68, T69, T73 |
| RF-025 | T7, T12, T17, T28, T33, T41, T67, T81 |
| RF-026 | T6, T14, T15, T21, T23, T27, T28, T29, T30, T32, T34, T35, T47, T64, T79 |
| RF-027 | T22, T23, T45, T47, T50, T58, T79, T80 |
| RF-028 | T19, T44, T49, T50, T53, T58, T78, T80 |
| RF-029 | T3, T5, T6, T7, T12, T29, T33, T66, T67, T73, T78 |
| RF-030 | T3, T6, T9, T30, T39, T66, T68 |
| RF-031 | T1, T2, T16, T18, T22, T25, T46, T56, T65, T75, T80 |
| RNF-001 | T1, T2, T11–T16, T18, T21, T22, T25–T27, T46, T49, T52, T56, T57, T65, T75–T77, T79 |
| RNF-002 | T19, T22, T44, T47, T49, T50, T51, T53, T58, T79, T80 |
| RNF-003 | T5, T6, T8, T10, T30, T33, T35, T38, T40, T66 |
| RNF-004 | T5, T14, T26, T27, T30, T35, T42, T51, T52, T56, T57, T61, T66, T69, T70, T74–T77, T81 |
| RNF-005 | T53, T63–T68, T71, T72, T78, T80 |
| RNF-006 | T1, T16, T20, T23, T25, T33, T36–T38, T44, T49, T53, T54, T55, T58, T61, T62, T69, T73, T80, T81 |

**Cobertura prevista: RF-001–RF-031 (31/31) y RNF-001–RNF-006 (6/6).** T84 exige aceptación humana de toda la implementación. Ninguna casilla está completada por la aprobación de spec, Plan o tareas.
