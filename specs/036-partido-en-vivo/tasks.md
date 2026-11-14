# Tareas 036 — Partido en vivo

Estado: **borrador, pendiente de aprobación expresa de las tareas**. Spec y Plan aprobados por el usuario el 2026-11-13 («Apruebo la spec.» y «Apruebo el plan.»), con DA-1–DA-7 y C1–C5 confirmadas. No se autoriza implementación por redactar este documento. Todas las casillas están abiertas; los comandos y archivos nuevos son entregables futuros, no resultados ejecutados.

Son **84 tareas**, cada una estimada en **20–30 minutos de trabajo activo**; esperas de CI, suites completas, carga y aceptación humana se contabilizan aparte. El orden aprobado del Plan es **A → B → C**: **A, 24 tareas (T1–T24)**; **B, 36 (T25–T60)**; **C, 24 (T61–T84)**. El tamaño se consigue separando piezas de dominio, tablas, endpoints, integración y gates; no se oculta todo el backend en una tarea. Si un bloque excede el tamaño al ejecutarlo, se propone descomposición antes de continuar, sin ampliar el alcance ni activar piezas incompletas.

## Dependencias, ejecución y tests primero

- Se ejecuta una sola tarea cada vez. Además de las dependencias explícitas, cada tarea depende de las anteriores del mismo PR; el siguiente PR espera a la fusión y gates del anterior. Una tarea no autoriza comenzar sin aprobación del listado.
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

## Propuesta de partición para revisión — pendiente de aprobación

Se supera ampliamente el umbral de diez tareas de SDD: no conviene revisar A/B/C como tres diffs grandes. Se propone dividir **su entrega**, manteniendo una única spec para no fragmentar autorización, integridad y recuperación de F1. **No se cambia tácitamente C5:** el listado sigue agrupado en los tres PRs aprobados; adoptar estos siete PRs requiere confirmación del usuario antes de implementarlos.

| Parte propuesta | Rango / cantidad | Por qué es segura sola |
|---|---|---|
| A1 — Dominio y contratos inertes | T1–T10 / 10 | Solo funciones puras, contratos y pruebas; nada registrado en HTTP ni productor. |
| A2 — Migración completa | T11–T24 / 14 | Incluye **toda** 056, RLS, permisos, función invocadora y vistas acotadas no consumidas. Ninguna tabla se entrega sin su RLS. No partir 056 en dos PRs ni editarla tras fusionar A2. |
| B1 — Servicios privados internos | T25–T36 / 12 | Handlers/servicios probados con BD, **sin incluir el nuevo router en la aplicación productiva** ni ofrecer inicio F1. No se cambia todavía la ruta pública. |
| B2 — Cierre y avisos preparados | T37–T48 / 12 | Protege cierre clásico frente a estado F1, prepara catálogo, outbox y modelos; sigue sin ruta productora accesible. No hay captura activa que dependa de B3 para ser segura. |
| B3 — Exposición completa y activación | T49–T60 / 12 | Público exacto, consumidores compatibles y registro final del router viajan juntos. Activar solo tras gates y despliegue coordinado sin API antigua. No separar T55 de sus precondiciones. |
| C1 — Interfaz operativa | T61–T72 / 12 | Backend B3 ya es completo y seguro; añade la UX del recorrido sin dejar controles esenciales para después. |
| C2 — Verificación ampliada y aceptación | T73–T84 / 12 | Amplía evidencia/regresión/carga/documentación; no pospone autorizaciones o integridad hasta esta parte. No declarar implementación aceptada antes de T84. |

Gates G-BE/G-FE/G-E2E/G-INF/G-SEC/G-REMOTE al cierre de **cada parte adoptada**, además de los gates del PR lógico. No fusionar commits de tests rojos ni exponer rutas incompletas. En el esquema de tres PRs, los límites internos son checkpoints sin fusión independiente; en el de siete, A2 no comienza hasta fusionar A1, etc.

## PR A — Fundación inerte (T1–T24)

Sin cambios observables del flujo clásico ni productores nuevos. Dependencia externa: aprobación de estas tareas y de la partición, si se adopta.

- [ ] **T1. Caracterizar operación, cierre clásico y permisos con fixtures reutilizables.** RF-003, RF-012, RF-021, RF-022, RF-031; RNF-001, RNF-006
  - Tests primero: baseline con dos tenants, operación sin permiso de cierre, oficial asignado/no asignado y acta confirmada; reutilizar fixtures existentes.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_close_authorization_db.py tests/test_rectification_readers.py` conserva resultados y quedan condiciones de lectura actuales registradas, sin cambios HTTP.

- [ ] **T2. Definir capacidades separadas y evaluación pura de vías organizativa/asignada.** RF-012, RF-031; RNF-001
  - Tests primero: VIEW solo, OPERATE solo, observador, árbitro de otro partido, multirol y contexto ajeno/incompleto.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k access` prueba que escribir no concede leer y que una vía organizativa válida no exige asignación.

- [ ] **T3. Definir los DTO estrictos del sobre de comandos y lectura/capacidades.** RF-001, RF-003, RF-007, RF-012, RF-029, RF-030
  - Tests primero: tipos cerrados, UUID/revisión, cuerpo vacío, campos extra y datos incompatibles con el tipo de comando; 422 saneado.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_contracts.py -k command` verifica unión cerrada reutilizando esquemas existentes; no se registra router.

- [ ] **T4. Reutilizar el catálogo/payload de hechos y contratos de revisión/cierre F1.** RF-004, RF-005, RF-007, RF-019, RF-024
  - Tests primero: catálogo completo, normalización de identidad, metadata desconocida, cero/500/501 hechos y recibo ausente/ajeno en estructura.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_contracts.py -k report` y `cd backend && pytest -q tests/test_match_events_contract.py` mantienen un único catálogo, sin habilitar F13.

- [ ] **T5. Implementar observación pura de reloj con tiempo recibido como argumento.** RF-011, RF-017, RF-029; RNF-003, RNF-004
  - Tests primero: sin referencia, UTC aware, running, pausado, fracciones acumuladas, observación igual y reloj regresivo.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k observe_clock` produce segundos enteros sin perder microsegundos ni consultar reloj global/BD.

- [ ] **T6. Reducir inicio, pausa, reanudación y corrección del reloj.** RF-002, RF-011, RF-026, RF-029, RF-030; RNF-003
  - Tests primero: controles en live/suspended, segmento inválido, corrección running/paused y hechos preexistentes inalterados.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k control_clock` reancla con el instante inyectado y no cambia minutos/tiempo añadido.

- [ ] **T7. Reducir transiciones deportivas permitidas sin efectos secundarios.** RF-001, RF-002, RF-003, RF-025, RF-029
  - Tests primero: scheduled→live→suspended→live, sin participantes, versión no publicada, estados terminales y suspensión sin reloj.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k transition` conserva segmento/borrador al reanudar y nunca arranca el reloj automáticamente.

- [ ] **T8. Derivar marcador provisional reutilizando reglas y validación deportiva.** RF-004, RF-005, RF-007, RF-008, RF-024; RNF-003
  - Tests primero: vacío/cero, goles/autogoles/penaltis, equipos incompatibles y corrección/retirada, sin escribir resultados confirmados.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k provisional_score` usa las reglas publicadas y no introduce constantes deportivas nuevas.

- [ ] **T9. Canonizar conjunto revisado y separar revisión de contenido de reloj.** RF-006, RF-019, RF-020, RF-023, RF-030
  - Tests primero: orden estable, subconjunto distinto, resultado cambiado, hechos retirados y reloj que avanza sin cambiar huella.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py -k review_fingerprint` demuestra invalidación por hechos/resultado, no por observación pública.

- [ ] **T10. Verificar checkpoint de dominio/contratos inertes y su alcance.** RF-003, RF-007, RF-012, RF-019, RF-024; RNF-003, RNF-006
  - Dependencias: T1–T9. Caracterización/gate, sin rojo artificial.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_policy.py tests/test_match_live_contracts.py` y `git diff --check` pasan; ningún router/productor/carril público se ha activado. Si A1 se adopta como PR, además pasan los seis gates y su revisión remota antes de fusionar.

- [ ] **T11. Preparar pruebas de migración limpia/incremental sobre bases desechables.** RF-008, RF-012, RF-023, RF-031; RNF-001
  - Tests primero: caracterizar cadena hasta 055 y construir fixture reutilizable de dos tenants/roles; añadir aserciones de 056 todavía en rojo por ausencia de su esquema, no por fallo del entorno.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k baseline_055` pasa; la selección de esquema nuevo registra rojo esperado hasta T12–T20 sin aplicar una 056 parcial en volumen persistente.

- [ ] **T12. Añadir estado/referencias de reloj y RLS tenant en 056.** RF-001, RF-002, RF-008, RF-011, RF-025, RF-029; RNF-001, RNF-004
  - Tests primero: PK/FK compuestas, checks de referencia/anchor/tiempo, contexto ausente y tenant ajeno.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k state_table` valida `match_live_state` y su RLS con rol aplicativo; no se tocan scores confirmados.

- [ ] **T13. Añadir hechos privados y restricciones de referencias tenant.** RF-004, RF-005, RF-007, RF-008, RF-023, RF-024; RNF-001
  - Tests primero: identidad única, referencias ajenas y retirada, catálogo/estructura compatibles sin insertar `match_events`.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k events_table` valida `match_live_events`, RLS y claves compuestas de equipo/segmento/jugadores.

- [ ] **T14. Añadir registro idempotente de comandos sin credenciales ni cuerpos en logs.** RF-023, RF-026; RNF-001, RNF-004
  - Tests primero: comando repetido, unicidad por partido, hash diferente, actor ajeno y permisos mínimos de tablas.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k commands_table` verifica tabla/RLS/GRANT de comandos y ausencia de DELETE innecesario.

- [ ] **T15. Añadir recibos inmutables de revisión ligados a actor/sesión.** RF-019, RF-020, RF-023, RF-026; RNF-001
  - Tests primero: pertenencia de partido/actor, recibo ajeno, cambio de contexto y prohibición de sobrescritura/borrado por el rol aplicativo.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k reviews_table` valida tabla, políticas y referencias sin convertir recibos en actas confirmadas.

- [ ] **T16. Conceder permisos por defecto sin reemplazar permisos existentes.** RF-012, RF-031; RNF-001, RNF-006
  - Tests primero: roles existentes/nuevos, dueño/administrador/operador/árbitro, observador, personalizados y reejecución sin duplicar entradas.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k permissions` demuestra VIEW/OPERATE independientes y CLOSE/lecturas existentes intactos.

- [ ] **T17. Proteger integridad provisional frente a terminales y congelación de cierre.** RF-003, RF-008, RF-021, RF-022, RF-025
  - Tests primero: SQL directo sobre confirmado, transición inválida, reloj en segmento cerrado y congelación válida seguida de rollback.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k live_integrity` valida triggers nuevos sin relajar los triggers 009/016 ni permitir al mero cerrador una edición ordinaria.

- [ ] **T18. Ampliar en 056 la función invocadora de entrega para F1.** RF-012, RF-013, RF-014, RF-015, RF-031; RNF-001
  - Tests primero: evento cerrado `MATCH_LIVE_UPDATED`, sin versión, permiso/asignación, referencias incompatibles y lote inválido.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k realtime_live` valida firma/límite 256, SECURITY INVOKER y restauración de contexto, sin modificar 055.

- [ ] **T19. Añadir vistas acotadas F1 sin alterar vistas de estadísticas/acta vigente.** RF-009, RF-010, RF-028; RNF-001, RNF-002
  - Tests primero: organizaciones activas, versión publicada actual, cancelado/invisible, live/suspended y referencia nula; barrera de seguridad/grants.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k public_projection` valida selección interna separada de las 14 claves públicas y mantiene las vistas actuales sin consumo de borradores.

- [ ] **T20. Verificar 056 completa en limpio, incremental y reejecución del migrador.** RF-008, RF-012, RF-023, RF-028, RF-031; RNF-001, RNF-006
  - Dependencias: T11–T19. Gate de migración, no edición de una versión aplicada.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py` y `sh -n infra/postgres/migrate.sh` pasan para 001→056 y 055 con datos→056, checksums estables y reejecución sin duplicar permisos; siguiente número libre reconfirmado.

- [ ] **T21. Verificar aislamiento SQL directo de las cuatro tablas y privilegios reales.** RF-012, RF-016, RF-026; RNF-001
  - Tests primero: dos tenants, lectura/escritura cruzada y contexto ausente, bajo bracket_app no superusuario/BYPASSRLS.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_056.py -k rls` cubre las cuatro tablas y documenta la frontera: RLS tenant, RBAC HTTP/entrega por separado.

- [ ] **T22. Probar compatibilidad de las decisiones 055 antiguas y roles acumulados.** RF-012, RF-013, RF-015, RF-027, RF-031; RNF-001, RNF-002
  - Tests primero: los seis casos de catálogo anteriores frente a 056, error/fila ausente, desconocidos/F9 y vías multirol.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py tests/test_migration_056.py -k 'legacy or authorization or multi_role'` recoge casos reales y no amplía destinatarios actuales ni introduce una llamada por socket.

- [ ] **T23. Auditar grants, trazabilidad mínima e inercia de la fundación.** RF-008, RF-014, RF-022, RF-026, RF-027; RNF-001, RNF-006
  - Caracterización: inspeccionar diff y artefactos; no hace falta rojo artificial.
  - Hecho cuando: `git diff --check` y `cd backend && ruff check .` pasan; SQL/tests prueban invocador/GRANT/REVOKE sin PUBLIC ni credenciales y se registra que no existen rutas productoras F1, cambios de estadísticas ni nuevos campos públicos activos.

- [ ] **T24. Cerrar gates locales/remotos y fusión autorizada de A.** RF-003, RF-008, RF-012, RF-013, RF-022, RF-028, RF-031; RNF-001, RNF-002, RNF-003, RNF-006
  - Dependencias: T1–T23. Preparación de evidencias, esperas de suites/CI aparte del trabajo activo.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q` y `git diff --check`, más G-BE/G-FE/G-E2E/G-INF/G-SEC/G-REMOTE pasan; verificación de 056 y rama limpia por SHA registradas. No se da por fusionado A hasta comprobar la fusión decidida por el usuario. Si A2 es separado, es su gate equivalente.

## PR B — Backend completo y consumidores compatibles (T25–T60)

Dependencia externa: A fusionado y sus gates verdes. No habilitar productores hasta T55 y sus precondiciones; si se adopta partición, B1/B2 permanecen sin nuevo router productivo.

- [ ] **T25. Implementar lectura de capacidades sin revelar borrador.** RF-012, RF-016, RF-031; RNF-001, RNF-006
  - Tests primero: booleans efectivos, contexto ajeno, observador y actor sin VIEW; usar fixture HTTP test-only, sin registro productivo del router nuevo.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k access` devuelve capacidades sin hechos/score/reloj privados y no cambia GET operation.

- [ ] **T26. Implementar snapshot privado coherente y lectura vacía sin inicializar.** RF-005, RF-012, RF-016, RF-018, RF-024; RNF-001, RNF-004
  - Tests primero: VIEW sí/no, session/membership actuales, `initialized=false`, cero hechos y dos lectores; lectura no mutante.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k snapshot` verifica GET live autorizado bajo RLS y 404 indistinguible fuera del tenant.

- [ ] **T27. Construir transacción de comandos, revisiones e idempotencia.** RF-003, RF-007, RF-023, RF-026; RNF-001, RNF-004
  - Tests primero: repetición con igual hash, distinto cuerpo, respuesta perdida y revisión obsoleta; permiso revalidado incluso en retry.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k command_identity` prueba ack mínimo sin heredar VIEW y bloqueos/contexto compatibles con cierre.

- [ ] **T28. Aceptar inicio de partido con estado persistido no confirmado.** RF-001, RF-003, RF-008, RF-025, RF-026
  - Tests primero: scheduled válido, participantes ausentes, versión no publicada y doble inicio concurrente.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k start_match` persiste una única transición live sin eventos confirmados ni efectos de cierre.

- [ ] **T29. Aceptar suspensión y reanudación sin autoarranque del reloj.** RF-002, RF-003, RF-011, RF-026, RF-029
  - Tests primero: reloj running/paused/no iniciado, captura durante suspended y conservación de hechos/segmento/tiempo.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k suspend_resume` congela el reloj y rechaza escrituras inválidas sin cambios parciales.

- [ ] **T30. Persistir controles/correcciones del reloj con instante servidor.** RF-011, RF-023, RF-026, RF-030; RNF-003, RNF-004
  - Tests primero: permiso retirado, revisión perdida, reloj running y pausado, corrección inválida y reinicio/lectura posterior.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k clock` recibe el tiempo en el dominio puro y no altera minutos ni content_revision de hechos.

- [ ] **T31. Capturar hechos con catálogo/participantes/reglas actuales.** RF-004, RF-005, RF-007, RF-008, RF-024
  - Tests primero: eventos válidos, vacíos/desconocidos, 501 hechos, referencias de otro tenant y tiempo inválido.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k add_event` reutiliza validadores, actualiza provisional coherentemente y no inserta `match_events`.

- [ ] **T32. Corregir/retirar hechos explícitamente sin pérdida silenciosa.** RF-005, RF-006, RF-007, RF-023, RF-026
  - Tests primero: corrección/retirada de identidad conocida, obsoleta/ajena, cambios simultáneos y nuevo marcador.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k edit_event` incrementa content_revision solo por contenido aceptado y conserva lo anterior si falla validación.

- [ ] **T33. Coordinar rutas actuales de segmentos con el reloj F1.** RF-003, RF-011, RF-025, RF-029; RNF-003, RNF-006
  - Tests primero: interrupción/cierre de segmento pausa reloj, nuevo segmento no arranca implícitamente y modo clásico permanece igual.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k segment_clock` respeta orden de bloqueo y no cambia permisos existentes de segmentos.

- [ ] **T34. Emitir recibos de revisión completa sin confirmar ni congelar hechos.** RF-006, RF-019, RF-020, RF-024, RF-026
  - Tests primero: VIEW+CLOSE, falta cualquiera, vacío válido, resultado inválido y recibo ligado a actor/sesión/conjunto vigente.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k create_review` devuelve conjunto/resultado completos y preserva borrador/acta confirmada.

- [ ] **T35. Probar atomicidad de comandos y ausencia de efectos confirmados.** RF-007, RF-008, RF-023, RF-026; RNF-003, RNF-004
  - Tests primero: fallo inducido tras cambio de estado/hecho antes de commit; no se pierde la respuesta aceptada ni se guarda una parcial.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py -k command_rollback` demuestra reversión de estado/comando/auditoría y clasificación/sanciones/avance intactos; inyección solo test-only.

- [ ] **T36. Verificar checkpoint de servicios internos sin rutas productoras.** RF-001, RF-003, RF-008, RF-012, RF-019, RF-031; RNF-001, RNF-006
  - Dependencias: T25–T35. Gate de servicios, no autorización para exponerlos.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py tests/test_match_live_close_db.py -k 'not consolidation'` y `git diff --check` pasan; el router F1 sigue ausente del montaje productivo. Si B1 se adopta, cumplir todos los gates y revisión antes de fusionar.

- [ ] **T37. Ampliar DTO de cierre sin abrir un bypass clásico de F1.** RF-019, RF-020, RF-022, RF-024; RNF-006
  - Tests primero: cierre clásico sin recibo intacto, variante F1 sin recibo/array vacío por defecto y campos extra; no aceptar subconjuntos del navegador.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_contracts.py -k close` y `cd backend && pytest -q tests/test_close_validation_order.py` validan `live_review_id` explícito y 422/409 previstos.

- [ ] **T38. Extraer punto interno de integración sin transacciones anidadas.** RF-019, RF-020, RF-021, RF-022; RNF-003, RNF-006
  - Tests primero: caracterizar cierre original, walkover/administrativa, bloqueos y orden de errores antes del refactor.
  - Hecho cuando: `cd backend && pytest -q tests/test_close_validation_order.py tests/test_walkover_close.py` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_close_authorization_db.py` pasan con el mismo `begin` y autorización originales.

- [ ] **T39. Revalidar recibo, resultado completo y contenido antes de consolidar.** RF-006, RF-019, RF-020, RF-023, RF-030
  - Tests primero: revisión stale por hecho/resultado, recibo de otra sesión/tenant, permiso retirado y reloj que avanza/corrige sin cambiar hechos.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k validate_review` produce errores aditivos sin invalidar revisión por meras observaciones del reloj.

- [ ] **T40. Construir el DTO canónico desde todos los hechos vigentes del servidor.** RF-004, RF-007, RF-019, RF-024; RNF-003
  - Tests primero: omisión/orden/subconjunto enviado por cliente, retirados excluidos explícitamente, borrador vacío y reglas de resolución.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k canonical_report` conserva identidades y usa validadores actuales sin duplicar reglas ni elegir silenciosamente un subconjunto.

- [ ] **T41. Consolidar hechos y congelar F1 dentro del cierre atómico actual.** RF-008, RF-019, RF-020, RF-021, RF-025
  - Tests primero: cierre válido completo, vacío válido y transición a terminal; efectos actuales se producen una vez.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k consolidation` confirma hechos/resultado/contadores/sanciones/clasificación/avance/outbox en una transacción, sin cambiar triggers de inmutabilidad.

- [ ] **T42. Probar rollback de consolidación en puntos tardíos del cierre.** RF-019, RF-020, RF-021; RNF-004
  - Tests primero: errores test-only en sanciones, avance y outbox después de persistir hechos/congelar reloj.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k rollback` conserva borrador privado aceptado y no deja efectos o acta parcialmente confirmados.

- [ ] **T43. Probar carreras cierre-edición/doble cierre y rectificación posterior.** RF-006, RF-019, RF-021, RF-022, RF-023
  - Tests primero: commits concurrentes y barreras reales; edición posterior a revisión y acta cerrada que solo admite 033.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py -k concurrency` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_rectification_flow.py` pasan sin duplicar hechos ni sobrescribir lo confirmado.

- [ ] **T44. Definir modelos públicos por estado y serialización exacta del suspendido.** RF-009, RF-010, RF-028; RNF-002, RNF-006
  - Tests primero: 14 claves exactas incluyendo null, unión Pydantic, live con campos adicionales y otros estados sin nuevos defaults.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_public.py -k serialization` no añade lineup/fase/escudos/actores a suspended; la ruta pública todavía no se cambia.

- [ ] **T45. Ampliar catálogo Python y adaptación SQL solo para el evento privado nuevo.** RF-012, RF-013, RF-014, RF-015, RF-027
  - Tests primero: scope organizativo sin version_id, referencias inválidas/extra, F9 y payload mínimo sin hechos/revisiones.
  - Hecho cuando: `cd backend && pytest -q tests/test_match_live_realtime.py -k catalog` y `cd backend && pytest -q tests/test_realtime_policy.py` distinguen live de operation/version sin comodines ni cambios del wire antiguo.

- [ ] **T46. Verificar paridad HTTP/SQL real para los nuevos lectores.** RF-012, RF-015, RF-016, RF-031; RNF-001
  - Tests primero: VIEW/OPERATE separados, multirol, oficial asignado a otro partido, plataforma y membresía/sesión inválidas.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k http_sql_parity` compara GET live del router test-only y autorización 056 bajo bracket_app, sin tomar el helper Python como prueba suficiente.

- [ ] **T47. Encolar invalidaciones mínimas y condicionar público a cambios de proyección.** RF-008, RF-013, RF-014, RF-026, RF-027; RNF-002
  - Tests primero: comando aceptado/rechazado/repetido, tarjeta sin efecto público, cambio de score/estado/reloj y rollback transaccional.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k outbox` verifica IDs estables y worker existente sin Redis en request, sin ticks y sin avisos públicos por hechos exclusivamente privados.

- [ ] **T48. Verificar checkpoint de cierre/avisos sin activar productores HTTP.** RF-013, RF-014, RF-019, RF-020, RF-021, RF-022, RF-027; RNF-002, RNF-006
  - Dependencias: T37–T47. Gate de preparación, no activación.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_close_db.py tests/test_match_live_realtime.py` y `git diff --check` pasan; nuevo router no incluido y ruta pública antigua todavía compatible. Si B2 se adopta, cumplir todos los gates y Review antes de fusionar.

- [ ] **T49. Integrar la unión pública en la ruta y paginación existentes.** RF-009, RF-010, RF-028; RNF-001, RNF-002, RNF-006
  - Tests primero: anónimo sin organización, suspendido entre páginas, filtro de fase/grupo, invisible/cancelado y organización ajena.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_public.py -k route` comprueba claves de respuesta HTTP reales, filtros/orden antes de serializar y estadísticas/actas vigentes ajenas al borrador.

- [ ] **T50. Emitir el aviso público nuevo solo tras revalidar visibilidad actual.** RF-009, RF-010, RF-013, RF-014, RF-027, RF-028; RNF-002
  - Tests primero: torneo ocultado después de encolar, referencias de otro tenant, nombre privado compartiendo identificadores y fallos de consulta.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k public_dispatch` no emite si no verifica visibilidad, conserva eventos públicos anteriores y nunca difunde el borrador al room organizativo.

- [ ] **T51. Suscribir nombres nuevos en el único dispatcher cliente con deduplicación.** RF-013, RF-014, RF-017, RF-018; RNF-002, RNF-004
  - Tests primero: duplicados, payload vacío/desconocido y RESYNC; sin otro socket/listener de rectificación.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-realtime.test.ts` conserva el catálogo antiguo y enruta las dos señales nuevas sin suscripciones duplicadas.

- [ ] **T52. Coordinar reconstrucción HTTP de operation/capacidades/live con guardas.** RF-012, RF-015, RF-016, RF-017, RF-018; RNF-001, RNF-004
  - Tests primero: permiso perdido, respuesta antigua tras cambio de contexto, busy/trailing reload y denegación live sin perder historial 033 autorizado.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-context.test.ts` demuestra useApi, contexto/generación y limpieza 401/403/404 vigentes sin remontar componentes.

- [ ] **T53. Adaptar vista pública mínima y agrupación sin inventar campos del suspendido.** RF-009, RF-010, RF-011, RF-028; RNF-002, RNF-005, RNF-006
  - Tests primero: primera carga sin caché, SSR, tarjetas mínimas en consulta general, filtro de origen y marcador provisional/referencia nula.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-public.test.ts` muestra suspendido sin exigir stage_id/lineup/bracket_code y no duplica partidos al cambiar de estado.

- [ ] **T54. Reconocer F1 en Workspace y bloquear el cierre desde una copia local clásica.** RF-019, RF-020, RF-021, RF-024; RNF-006
  - Tests primero: cliente clásico contra F1 inicializado, falta de VIEW/recibo y partido clásico sin F1.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-close.test.ts` no envía una copia local como acta F1 ni borra su texto ante rechazo; cierre clásico sigue igual.

- [ ] **T55. Registrar el router completo y verificar las precondiciones de activación.** RF-001, RF-003, RF-012, RF-013, RF-019, RF-028, RF-031; RNF-001, RNF-006
  - Dependencias: T25–T54 completas, público y consumidores compatibles, revisión de seguridad del diff; si hay subdivisión, B1/B2 fusionados.
  - Tests primero: rutas reales de la aplicación, auth/CSRF y ausencia de bypass por rutas antiguas.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_db.py tests/test_match_live_close_db.py tests/test_match_live_public.py` pasa a través del montaje real, no solo el router test-only. El despliegue exige suspender escrituras y detener toda API/relay antigua antes de reabrir tráfico; no se introduce flag oculto ni rolling mixto.

- [ ] **T56. Comprobar entrega privada real en dos API y dos tenants.** RF-012, RF-013, RF-014, RF-016, RF-018, RF-031; RNF-001, RNF-004
  - Tests primero: arnés multiproceso existente, sockets reales autorizados/denegados y lectura HTTP posterior; sin mock de emisión.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k multiprocess_delivery` observa únicamente los tres identificadores en receptores permitidos y cero frames de dominio en ajenos.

- [ ] **T57. Comprobar retiradas, fallos y recuperación de entrega sin replay.** RF-015, RF-016, RF-017, RF-018; RNF-001, RNF-004
  - Tests primero: retirada confirmada en barrera, expiración real de sesión/JWT, fallo SQL/fila ausente, recuperación y contexto cambiado.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_match_live_realtime.py -k multiprocess_recovery` prueba corte/fail-closed/RESYNC real sin caché de permisos ni prometer retirar frames previamente aprobados.

- [ ] **T58. Verificar matriz pública y clásica de extremo a extremo antes de ofrecer captura UI.** RF-008, RF-009, RF-010, RF-022, RF-027, RF-028; RNF-002, RNF-006
  - Tests primero: flujo por HTTP y espectadores reales, suspensión/reanudación, ocultación del torneo y acta rectificada vigente.
  - Hecho cuando: `cd frontend && pnpm exec playwright test e2e/realtime-public.spec.ts --project public` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_public_access_matrix.py tests/test_public_field_allowlist.py` no revelan hechos ni datos excluidos.

- [ ] **T59. Ejecutar gate backend/BD/seguridad de B y registrar trazabilidad del servidor.** RF-003, RF-007, RF-008, RF-012, RF-019, RF-020, RF-022, RF-027, RF-031; RNF-001, RNF-003, RNF-006
  - Dependencias: T25–T58. Gate, sin rojo artificial; esperas de suites aparte.
  - Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 pytest -q` y `cd backend && python -m compileall -q app`, más G-BE/G-INF/G-SEC pasan y las salidas saneadas quedan asociadas al SHA; no se posponen controles esenciales a C.

- [ ] **T60. Ejecutar gates frontend/E2E/CI y comprobar fusión autorizada de B.** RF-009, RF-013, RF-016, RF-017, RF-018, RF-019, RF-028; RNF-002, RNF-004, RNF-005, RNF-006
  - Dependencias: T59; todos los controles B listos. Gate, esperas de CI aparte.
  - Hecho cuando: `cd frontend && pnpm test`, `cd frontend && pnpm run e2e:test` y `git diff --check`, más G-FE/G-E2E/G-REMOTE pasan; evidencias y Review revisadas. B solo se declara fusionado tras evidencia de la fusión autorizada; si B3 se adopta es su gate final y conserva G-INF/G-SEC de T59.

## PR C — UX, verificación ampliada y aceptación (T61–T84)

Dependencia externa: B completo fusionado con gates verdes; no se difiere seguridad del servidor hasta este PR. Si se adopta C1/C2, el PR C1 ya proporciona un recorrido completo antes de C2.

- [ ] **T61. Separar editor compartido y estado clásico local en el composable.** RF-004, RF-005, RF-012, RF-024; RNF-004, RNF-006
  - Tests primero: carga de F1, vacío, modo clásico y error; ningún hecho local se considera aceptado sin HTTP.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-editor.test.ts` mantiene snapshots separados y usa exclusivamente useApi.

- [ ] **T62. Resolver explícitamente un borrador clásico antes de iniciar F1.** RF-001, RF-019, RF-024; RNF-006
  - Tests primero: borrador local presente/ausente, cancelación de confirmación y fallo de inicio; no importación ni pérdida automática.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-local-draft.test.ts` conserva texto hasta decisión expresa y no reenvía eventos locales como borrador compartido.

- [ ] **T63. Capturar incidencias compartidas con aceptación y errores saneados.** RF-004, RF-005, RF-007, RF-023, RF-024; RNF-005
  - Tests primero: captura válida, campos vacíos, catálogo inválido, error/timeout y doble activación.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-capture.test.ts` espera ack y snapshot autorizado, conserva formulario si falla y no duplica hechos por reintento.

- [ ] **T64. Corregir/retirar hechos con confirmación y conflicto explícito.** RF-006, RF-007, RF-023, RF-026; RNF-005
  - Tests primero: modificación válida, cancelación, revisión obsoleta y hecho retirado por otro operador.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-edit.test.ts` conserva edición ante conflicto, usa useConfirm/single-flight y obliga a revisar la base antes de guardar.

- [ ] **T65. Presentar lector y operador según capacidades independientes.** RF-012, RF-015, RF-016, RF-031; RNF-001, RNF-005
  - Tests primero: VIEW sin OPERATE, OPERATE sin VIEW, observador, retirada y multirol; UI no es la barrera de seguridad.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-access.test.ts` no revela detalle por poder escribir ni ofrece cierre por herencia de OPERATE; denegaciones vigentes limpian lo privado.

- [ ] **T66. Añadir controles y presentación de reloj con tiempo inyectable.** RF-011, RF-017, RF-029, RF-030; RNF-003, RNF-004, RNF-005
  - Tests primero: sin iniciar, running/paused, desactualizado, corrección y reconexión; sin intervalos que escriban al servidor.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-clock.test.ts` conserva hechos/minutos al corregir reloj y distingue cálculo visual de referencia aceptada.

- [ ] **T67. Añadir controles de inicio, suspensión y reanudación del partido.** RF-001, RF-002, RF-003, RF-025, RF-029; RNF-005
  - Tests primero: estados válidos/terminales, cancelación de confirmación, error/ocupado y suspensión sin referencia.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-transitions.test.ts` bloquea captura/control durante suspended y no arranca reloj ni crea segmento al reanudar.

- [ ] **T68. Mostrar revisión expresa del conjunto completo y resultado a cerrar.** RF-006, RF-019, RF-024, RF-030; RNF-005
  - Tests primero: lista completa/vacía, cambio de hechos/resultado y reloj que avanza sin invalidar revisión.
  - Hecho cuando: `cd frontend && pnpm exec node --test --experimental-strip-types tests/match-live-review.test.ts` muestra el conjunto vigente completo y exige nuevo recibo ante cambio real, sin selector de subconjunto silencioso.

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
  - Hecho cuando: `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck` y `cd frontend && pnpm run e2e:test`, más G-FE/G-E2E pasan; si C1 es PR independiente, además todos los gates comunes/Review y fusión autorizada se verifican antes de C2.

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
  - Hecho cuando: `cd frontend && pnpm test`, `cd frontend && pnpm run e2e:test`, `git diff --check` y G-FE/G-E2E/G-REMOTE pasan para el SHA final, con push/PR comprobados por separado y hallazgos triados. La fusión de C se verifica solo si el usuario la decide; no confundirla con aceptación de F1.

- [ ] **T84. Obtener aceptación humana explícita de F1 y cerrar la spec solo entonces.** RF-001, RF-019, RF-021, RF-022, RF-028, RF-031; RNF-001, RNF-002, RNF-003, RNF-004, RNF-005, RNF-006
  - Dependencias: T1–T83 verificadas, entregas integradas según la decisión del usuario y evidencia final disponible. Ningún test/merge sustituye esta decisión.
  - Hecho cuando: se registra fecha y texto de aceptación del usuario tras presentar evidencias/límites; solo entonces se marca implementación aceptada y se actualizan spec/Plan/tareas/MEMORY/documentación. Pasan `git diff --check` y `python3 infra/scripts/verify_version_sources.py --exclude-constitution`; cualquier commit de cierre vuelve a verificar CI. Sin respuesta expresa, T84 permanece abierta y no se declara F1 implementada/aceptada.

## Matriz de cobertura del borrador

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

**Cobertura prevista: RF-001–RF-031 (31/31) y RNF-001–RNF-006 (6/6).** T84 exige aceptación humana de toda la implementación. Ninguna casilla está completada por la aprobación previa de spec o Plan.
