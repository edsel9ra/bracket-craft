# Tareas 035 — Tiempo real privado según permisos de lectura

Estado: **aprobado** por el usuario el 2026-11-13 («Apruebo las tareas.»). Spec y plan aprobados por el usuario el 2026-11-13, incluidas C1–C4 tal como estaban recomendadas. Implementación autorizada en orden PR A → B → C. Las casillas permanecen abiertas hasta realizar y comprobar el trabajo correspondiente.

Son **49 tareas**, estimadas en **20–30 min de trabajo activo por tarea**, más esperas de CI. Orden de entrega aprobado: **PR A → PR B → PR C**. A: **17 tareas** (T1–T17); B: **20 tareas** (T18–T37); C: **12 tareas** (T38–T49). Cada PR se verifica y fusiona antes de empezar el siguiente. Las dependencias indicadas son necesarias; no autorizan paralelismo de implementación: una tarea cada vez, conforme a SDD.

**Partición:** se superan diez tareas, por lo que se revisó la división exigida por Fase 4. Se recomienda mantener una sola spec y los tres PR aprobados por C4: todos desarrollan la misma garantía de privacidad; separar specs permitiría declarar terminado el filtro sin recuperación. Ningún PR supera veinte tareas. No se propone subdivisión adicional: B llega al límite, pero gate, invalidación compatible y reconstrucción HTTP deben fusionarse juntos, con tests de no recepción y recuperación. A es inerte; C amplía verificación/cierre, no difiere controles esenciales de B. Si al ejecutar una tarea excede 30 min o un diff resulta demasiado grande, detenerse y proponer una subdivisión verificable antes de continuar; no activar ni fusionar parcialmente B ni cambiar C4 tácitamente.

## Reglas de ejecución y entorno

- **Tests primero en cada tarea funcional:** escribir los casos indicados, ejecutar el comando y registrar rojo por la conducta ausente; implementar lo mínimo y ejecutar verde antes de marcar. Un fallo de imports/infraestructura no sustituye una reproducción válida. Incluir normal, vacío y error cuando apliquen. Los nombres de archivos/selectores nuevos son entregables futuros; una selección sin tests no abre el gate.
- Las tareas de caracterización, regresión, documentación y aceptación no inventan un rojo: registran el baseline o evidencia existente y verifican el resultado. No modificar tests para aceptar un permiso nuevo, un broadcast o un resultado no autorizado. Si falla algo ajeno al alcance, documentar/escalar con evidencia, no ampliar el cambio.
- Los comandos se leen **independientemente desde la raíz**, con el entorno de AGENTS cargado; Python y pnpm en sus contenedores equivalentes si el host no tiene el runtime correcto. No hay gestor de paquetes en la raíz.
- Para comandos `RUN_DATABASE_TESTS=1`, preparar PostgreSQL local de pruebas como CI y exportar `DATABASE_URL` con rol `bracket_app` y `DATABASE_ADMIN_URL` para preparar datos/migraciones. Las lecturas bajo prueba usan el rol de aplicación, nunca superusuario ni BYPASSRLS. Dos organizaciones y contextos RLS reales; mocks no prueban aislamiento ni commits concurrentes. No producción, secretos ni datos personales en evidencias.
- **Migración:** T10–T12 construyen partes de la nueva **055** —comprobar siguiente número libre antes—, no cambios a 032/054. Hasta fijarla, reconstruir bases de prueba desechables para probar cada versión; no cambiar una migración registrada en un volumen persistente. Tras aplicación persistente/fusión, cualquier corrección requiere la siguiente migración nueva libre. Sin tablas/generaciones ni ampliación de políticas/grants SELECT.
- Los E2E dirigidos requieren pila local iniciada y sembrada según AGENTS y Chromium del runner existente. Los comandos `pnpm exec playwright test` sirven para desarrollar el caso; el gate es **`pnpm run e2e:test`**, código 0 y ninguna vista obligatoria omitida. No añadir endpoints productivos de inyección ni modificar CI para facilitar las pruebas.
- Respetar los IDs de suites del plan §8: P1–P3 (puras), D1–D3 (DB/paridad/corte), S1–S3 (transporte/outbox), F1–F2 (frontend), E1–E2 (navegador) y L1 (eficiencia). Cada tarea registra comando, salida y SHA en la evidencia futura antes de marcarse; ningún resultado futuro se da por ejecutado aquí.

## PR A — Núcleo y autorización inertes (T1–T17)

No invocar todavía el nuevo gate desde el relay ni cambiar entrega observable. R32f permanece abierto. Dependencias internas detalladas abajo; **T17 exige T1–T16 completas**. Contrato C1/C2, sin nuevas lecturas HTTP, permisos ni borradores F1.

- [x] **T1. Caracterizar las lecturas HTTP y preparar fixtures de paridad.** RF-001, RF-002, RF-003, RF-004, RF-005
- Dependencias: aprobación expresa de estas tareas; PR A.
- Tests primero: crear casos HTTP reales de operación y versiones con dos tenants, miembro lector sin permiso de escritura ni oficial, multirrol, vacío/404 y plataforma sin membresía. Baseline verde sin cambiar HTTP; dejar documentadas las condiciones exactas por variante del catálogo.
- Hecho cuando: los fixtures de `test_realtime_delivery_db.py` cubren las rutas existentes, no inventan `/tournaments/{id}/standings` ni restringen lecturas. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k http_baseline` (D1).

- [x] **T2. Clasificar el catálogo cerrado y sus exclusiones.** RF-012, RF-016, RF-019, RF-020
- Dependencias: T1; PR A.
- Tests primero: P1 en `test_realtime_policy.py`, seis variantes actuales, desconocido, scope incoherente, sonda, correo, avisos F9 y borrador F1.
- Hecho cuando: `realtime_policy.py` declara tipo+variante+lectura, sin herencia por nombre público ni comodín de membresía. Pasa `cd backend && pytest -q tests/test_realtime_policy.py -k catalog`; desconocidos/excluidos no producen intención de entrega.

- [x] **T3. Validar el sobre privado y el ID legado.** RF-012, RF-013, RF-018
- Dependencias: T2; PR A.
- Tests primero: P1 con `event_id`, alias `id`, ambos iguales/divergentes, ID ausente, sobre vacío/malformado y organización inválida.
- Hecho cuando: clasificación privada deniega incoherencia sin alterar parseo público ni generar un segundo ID. Pasa `cd backend && pytest -q tests/test_realtime_policy.py -k envelope`.

- [x] **T4. Resolver referencias tipadas sin atribuir autorización.** RF-001, RF-002, RF-012
- Dependencias: T3; PR A.
- Tests primero: P1 normal/vacío/error para partido/torneo y versión obligatoria en variantes rectificativas; referencias desconocidas o incompletas.
- Hecho cuando: el resolver puro solo devuelve qué verificar por RLS, no declara legible un recurso por UUID. Pasa `cd backend && pytest -q tests/test_realtime_policy.py -k references`.

- [x] **T5. Proyectar invalidaciones de tres IDs por whitelist.** RF-013, RF-015, RF-016
- Dependencias: T4; PR A.
- Tests primero: P1 con referencias autorizadas, vacías y dato de negocio inesperado; entrada histórica con timestamp conocido.
- Hecho cuando: `build_private_invalidation` produce únicamente `event_id,match_id,tournament_id`, sin copiar payload ni emitir versión/scope/timestamp/negocio. Pasa `cd backend && pytest -q tests/test_realtime_policy.py -k invalidation`; el contrato público permanece separado.

- [x] **T6. Agrupar principales y sockets por tenant.** RF-002, RF-010, RF-018
- Dependencias: T3; PR A.
- Tests primero: P3 para cero candidatos, varias pestañas/sesiones, metadatos inválidos, otro tenant y límites 256/257.
- Hecho cuando: agrupación determinista por organización/usuario/sesión, con sid/generación y lotes de hasta 256 principales; no combina derechos de identidades distintas. Pasa `cd backend && pytest -q tests/test_realtime_policy.py -k recipients`.

- [x] **T7. Decidir lectura efectiva multirrol sin inventar permisos.** RF-001, RF-003, RF-004, RF-005, RF-012
- Dependencias: T1, T2, T4; PR A.
- Tests primero: P2 con hechos de varios roles, acceso organizativo general y predicado condicional permiso+oficial/exención; hechos incompletos o incompatibles.
- Hecho cuando: decisión pura `ALLOW/DENY/INDETERMINATE` respeta las conjunciones de HTTP y no exige `CLOSE_MATCH_REPORT` ni oficial a lecturas generales. La fixture condicional no añade evento/permiso de producto. Pasa `cd backend && pytest -q tests/test_realtime_policy.py -k permissions`.

- [x] **T8. Aplicar tiempo explícito a sesión y JWT por destinatario.** RF-006, RF-007, RF-011
- Dependencias: T6, T7; PR A.
- Tests primero: P2 para sesión/usuario/membresía inválidos y expiración antes/igual/después de `evaluation_time`, incluidos sid de una sesión con expiraciones JWT diferentes.
- Hecho cuando: el núcleo no lee el reloj ni confía en metadatos del cliente, y compartir hechos SQL no comparte indebidamente la vigencia del token. Pasa `cd backend && pytest -q tests/test_realtime_policy.py -k temporal`.

- [x] **T9. Modelar suspensión y recuperación como transición pura.** RF-009, RF-010, RF-014, RF-017, RF-018
- Dependencias: T6, T8; PR A.
- Tests primero: P2/P3 para error repetido, DENY, recuperación, marca vacía, generación obsoleta y fallo de control.
- Hecho cuando: estado por sid/generación genera una intención de RESYNC por episodio, sin almacenar IDs de recursos perdidos ni decisiones reutilizables; `now`/instantes son parámetros. Pasa `cd backend && pytest -q tests/test_realtime_policy.py -k recovery_state`.

- [x] **T10. Construir la nueva función invocadora: identidad y contexto.** RF-002, RF-006, RF-007
- Dependencias: T1, T8; PR A.
- Tests primero: D1/D3 con rol app, sesiones válidas/retiradas/ajenas, usuario u organización inactivos, membresía real y ausencia de rol; contextos administrativos excepcionales presentes.
- Hecho cuando: nueva 055 comprueba identidad/sesión/membresía por principal, fija contexto RLS local por usuario, limpia excepciones 033/F9 y recibe `evaluation_time`; no usa BYPASSRLS ni membresía de plataforma. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k identity`.

- [x] **T11. Completar la función batch: recursos y variantes verificables.** RF-001, RF-002, RF-005, RF-012, RF-013
- Dependencias: T4, T10; PR A.
- Tests primero: D1 con JOIN/accesibilidad de operación, partido/torneo/versión cruzados, inexistentes, acta no confirmada y versión ajena; lectura válida sin publicación pública del torneo.
- Hecho cuando: cada regla verifica el recurso concreto por RLS y conserva las condiciones HTTP, sin endpoint de clasificación inventado. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k resources`.

- [x] **T12. Completar la función batch: roles efectivos y paridad.** RF-001, RF-003, RF-004, RF-005, RF-008, RF-009
- Dependencias: T7, T11; PR A.
- Tests primero: D1 compara HTTP/gate por variante, lector sin permisos de escritura, dos roles, retirada de uno con otro vigente, concesión posterior y oficial con/sin permiso/asignación.
- Hecho cuando: ninguna restricción se infiere de un permiso de escritura o de `system_permissions` fuera de la semántica HTTP. Quitar oficial/permiso que HTTP no exige no retira esa lectura. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k parity`.

- [x] **T13. Implementar el adaptador de evaluación fresca por lote.** RF-006, RF-007, RF-008, RF-009, RF-011, RF-014
- Dependencias: T6, T8, T10, T11, T12; PR A.
- Tests primero: S1/D2 en `test_realtime_delivery.py` para nueva transacción REPEATABLE READ por lote, snapshot/tiempo de frontera, contexto previo a lectura, principal faltante/error y cero candidatos.
- Hecho cuando: `realtime_authorization.py` consulta primaria sin reutilizar autorización positiva/negativa y valida JWT por sid con el mismo instante; una llamada autorizadora por lote más coste constante de contexto. Pasan `cd backend && pytest -q tests/test_realtime_delivery.py -k adapter` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k snapshot`.

- [x] **T14. Demostrar el corte DA-2 con barreras de commit.** RF-007, RF-008, RF-009, RF-011
- Dependencias: T12, T13; PR A.
- Tests primero: D2 sincroniza retirada confirmada antes de evaluación, autorización antes del commit/envío después y evaluación siguiente; evento creado antes de retirada, expiración, concesión posterior y siguiente lote del mismo evento.
- Hecho cuando: tests reales, sin sleeps, prueban instantánea nueva después del commit y permiten solo el tránsito aprobado antes del corte; no inventan una retirada de lectura por quitar un permiso irrelevante. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k cutoff`.

- [x] **T15. Verificar migración, grants y limpieza de contexto.** RF-001, RF-002, RF-006, RF-012, RF-014
- Dependencias: T10, T11, T12, T13; PR A.
- Tests primero: D3 para EXECUTE de PUBLIC revocado/grant mínimo, función invocadora, rol app no superusuario/BYPASSRLS, salida parcial y error, reutilización de pool sin contexto anterior.
- Hecho cuando: D3 aplica la nueva migración en base limpia y 054→055 mediante runner, con reejecución controlada y políticas/FORCE intactos. Pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k migration` y `sh -n infra/postgres/migrate.sh`; ejecutar además `infra/scripts/test_migrate_target.sh` con el contenedor PostgreSQL y variables indicados en AGENTS, registrando ambas rutas de migración.

- [x] **T16. Medir agrupación y coste SQL de la autorización inerte.** RF-001, RF-011, RF-014, RF-018
- Dependencias: T6, T13, T14, T15; PR A.
- Tests primero: L1 con 1.000 sockets/100 principales y 257 principales, lotes vacíos y error DB; contar llamadas de red y trabajo SQL por usuario, no solo la llamada exterior.
- Hecho cuando: se observa una/dos llamadas autorizadoras respectivamente, más coste constante por lote, sin consulta por sid ni caché de permisos; se registran datos/medidas sin afirmar O(1) dentro de SQL. Pasan `cd backend && pytest -q tests/test_realtime_delivery.py -k batching` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k batching`.

- [x] **T17. Gate de PR A y contrato inerte documentado.** RF-001, RF-002, RF-005, RF-011, RF-012, RF-014, RF-018, RF-019, RF-020
- Dependencias: T1–T16; PR A.
- Tests primero: regresión P/D/L y tests existentes de outbox/sockets; caracterizar que el relay aún no invoca el adaptador, sin modificar el comportamiento para fingir un rojo.
- Hecho cuando: pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q`, `cd backend && python -m compileall -q app`, `cd backend && ruff check .` y `git diff --check`; CI PR/push de A verdes con E2E de PR. Evidencia inicial de contrato en `verificacion.md`, R32f aún abierto, ninguna migración aplicada editada ni producto nuevo anunciado. Revisión y fusión de A antes de B.
  - [x] T1–T16 y gate local verificados; contrato inerte y R32f abierto documentados.
  - [x] CI de PR #76 y push verdes en `d4372227`, incluido E2E del PR; ejecuciones y resultados en `verificacion.md`.
  - [x] Devin Review revisado: «No Issues Found», sin comentarios inline ni hallazgos pendientes.
  - [x] PR A #76 fusionado en main antes de iniciar B; fusión comunicada por el usuario y verificada en GitHub.

## PR B — Entrega privada y recuperación end-to-end (T18–T37)

Depende de A fusionado y verde. Contiene juntos gate, invalidaciones, control compatible y reconstrucción HTTP. Los estados intermedios de estas tareas no se despliegan ni fusionan. **T37 exige T18–T36 completas**; C no se usa para posponer una comprobación esencial de privacidad.

- [x] **T18. Indexar conexiones y conservar hechos del handshake.** RF-002, RF-006, RF-010, RF-018
- Dependencias: T17; PR B.
- Tests primero: S1 para alta/baja, varios sid de una sesión, JWT verificado/expiración, sesión ausente, otro tenant y generación nueva.
- Hecho cuando: `main.py` mantiene índice local organización→principal→sid coherente, con expiración procedente del token validado y limpieza al desconectar; sin nuevo permiso del cliente ni sockets duplicados. Pasa `cd backend && pytest -q tests/test_realtime_delivery.py -k registry`.

- [x] **T19. Activar el gate en el momento de entregar a cada sid.** RF-001, RF-002, RF-003, RF-005, RF-007, RF-008, RF-009, RF-011, RF-012, RF-013
- Dependencias: T17, T18; PR B.
- Tests primero: S1 con autorizado/denegado, lector general sin oficial, evento pendiente, resultado ausente y catálogo desconocido, observando `sio.emit` antes de cualquier UI.
- Hecho cuando: el relay usa evaluación fresca y proyección mínima por sid; nunca emite dominio al room organizativo ni envía un payload vacío al denegado. Pasa `cd backend && pytest -q tests/test_realtime_delivery.py -k delivery`.

- [x] **T20. Separar el carril público de errores privados.** RF-014, RF-016, RF-018
- Dependencias: T19; PR B.
- Tests primero: S1 con los tres nombres/campos públicos, mismo room/criterio actual, nombres compartidos `scope=organization` y excepción de autorización privada.
- Hecho cuando: el fallo privado no impide la emisión pública elegible ni convierte la variante privada en pública; sin campos/eventos nuevos. Pasan `cd backend && pytest -q tests/test_realtime_delivery.py -k public` y `cd backend && pytest -q tests/test_outbox_relay.py tests/test_outbox_resync.py`.

- [x] **T21. Reducir nuevas filas privadas de rectificación conservando compatibilidad.** RF-011, RF-012, RF-013, RF-015, RF-016, RF-018
- Dependencias: T5, T19, T20; PR B.
- Tests primero: S3 para productor transaccional, tres entradas/IDs propios, payload nuevo sin timestamp, fila histórica con timestamp y referencias de versión verificadas.
- Hecho cuando: `rectifications/notifications.py` conserva `scope/version_id` internos y nombres/cantidad; wire solo tres IDs, sin reescribir outbox ni cambiar auditoría/publicación/correo. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k rectification`; añadir estos casos de productor a la suite DB futura.

- [x] **T22. Probar la sonda, F9 y correo fuera del canal de producto.** RF-012, RF-019, RF-020
- Dependencias: T2, T19, T21; PR B.
- Tests primero: S3 observa worker/Redis/socket: sonda procesada y visible en Redis, cero emisiones Socket.IO; handlers F9/correo no publican Redis y una inyección errónea de esos tipos en stream no se difunde.
- Hecho cuando: no se rompe la utilidad operativa ni se habilita F1 por compartir outbox. Pasan `cd backend && pytest -q tests/test_outbox_probe.py tests/test_outbox_worker.py` y `cd backend && pytest -q tests/test_realtime_delivery.py -k exclusions`.

- [x] **T23. Suspender solo entregas privadas no verificables y avanzar cursor.** RF-011, RF-014, RF-016, RF-017
- Dependencias: T9, T19, T20; PR B.
- Tests primero: S2 con excepción/timeout de lote o principal, salida faltante, varios tenants, nuevos eventos y error repetido; comprobar mensajes y logs.
- Hecho cuando: ninguna autorización antigua ni desconexión masiva, marca por afectados, cursor avanza y no guarda backlog/IDs privados; diagnósticos sin payload/tokens/evidencia. Pasa `cd backend && pytest -q tests/test_realtime_delivery.py -k suspension`.

- [x] **T24. Recuperar antes de la siguiente entrega con RESYNC compatible.** RF-006, RF-009, RF-014, RF-017, RF-018
- Dependencias: T9, T23; PR B.
- Tests primero: S2 para recuperación válida/parcial/denegada, varios errores coalescidos y fallo al enviar control, incluidos token o membresía ya retirados.
- Hecho cuando: reautoriza contexto, emite al sid un `RESYNC {event_id,reason:'RELAY_START'}` sin recursos y comprueba regla del siguiente evento; mantiene marca si falla envío. No replay ni control por cada pérdida. Pasa `cd backend && pytest -q tests/test_realtime_delivery.py -k recovery_event`.

- [x] **T25. Recuperar sin evento nuevo y reautorizar controles organizativos.** RF-006, RF-007, RF-009, RF-014, RF-016, RF-017
- Dependencias: T24; PR B.
- Tests primero: S2 usa reloj/programador inyectado para ciclo de 30 s, sin nuevo evento; reintento fallido, desconexión real, JOIN/RELAY_START/trim/reset organizativos y público intacto.
- Hecho cuando: mantenimiento intenta recuperar solo marcas vigentes con evaluación nueva, sin TTL de permiso; controles organizativos pasan gate de contexto y el fallo no desconecta masivamente. Pasan `cd backend && pytest -q tests/test_realtime_delivery.py -k recovery_cycle` y `cd backend && pytest -q tests/test_socket_revalidation.py tests/test_outbox_resync.py`.

- [x] **T26. Descartar autorizaciones de una generación de conexión anterior.** RF-002, RF-010, RF-011, RF-018
- Dependencias: T18, T24, T25; PR B.
- Tests primero: S1 pausa entre consulta/control/emit y cambia o desconecta el contexto, incluidas sesiones diferentes del mismo usuario y sid nuevo.
- Hecho cuando: antes de emitir se comprueba generación/contexto, sin aplicar la autorización de A a B ni confundir el caso con la entrega aprobada en tránsito de DA-2. Pasa `cd backend && pytest -q tests/test_realtime_delivery.py -k generation`.

- [x] **T27. Aislar callbacks y respuestas HTTP del contexto frontend anterior.** RF-010, RF-015, RF-017, RF-018
- Dependencias: T26; PR B.
- Tests primero: F1 del composable real con cambio de usuario/organización mientras hay callback, reconexión o GET pendiente; contexto vacío/error.
- Hecho cuando: `useRealtime.ts` y consumidores ignoran generaciones viejas, limpian suscripción/marcas y mantienen un socket del contexto vigente; usan `useApi`. Pasa `cd frontend && pnpm test` con los nuevos escenarios incluidos, sin limitarse a regex del código fuente.

- [x] **T28. Conservar dispatcher y deduplicación con las invalidaciones mínimas.** RF-013, RF-015, RF-016, RF-018
- Dependencias: T21, T24, T27; PR B.
- Tests primero: F1 entrega los tres IDs, mismo `event_id` repetido, varios IDs de una publicación, RESYNC válido/vacío/malformado y eventos públicos actuales.
- Hecho cuando: no se depende de `version_id/rectified_at`, no se añade callback redundante a `MATCH_REPORT_RECTIFIED` ni se multiplican recargas/suscripciones respecto al baseline. Pasa `cd frontend && pnpm test`, incluidas `realtime-dedup.test.ts` y `realtime-reload.test.ts`.

- [x] **T29. Reconstruir por HTTP la operación de un acta terminal.** RF-013, RF-015, RF-017
- Dependencias: T27, T28; PR B.
- Tests primero: F2 reproduce en rojo el composable real descartando RESYNC/invalidación con `isTerminal`; casos de partido distinto, vacío y GET fallido.
- Hecho cuando: una lectura autorizada de terminal sí se solicita y actualiza, sin habilitar edición, reabrir acta ni usar el evento como credencial. Pasa `cd frontend && pnpm test` con regresión del composable y de controles de escritura terminal.

- [x] **T30. Consolidar la recarga aplazada durante una acción ocupada.** RF-010, RF-015, RF-017, RF-018
- Dependencias: T29; PR B.
- Tests primero: F2 reproduce pérdida de señal durante `busyAction`, múltiples señales, éxito/error de acción y cambio de contexto antes de finalizar; borrador local y planilla clásica/táctica.
- Hecho cuando: una sola intención trailing sobrevive hasta poder leer, no se aplica a otro contexto ni borra borradores/ediciones por el filtro; el coordinador no duplica recargas. Pasa `cd frontend && pnpm test` con pruebas reales del composable y regresiones de hidratación de planilla.

- [x] **T31. Reconstruir Workspace con la autorización HTTP vigente.** RF-005, RF-010, RF-015, RF-017, RF-018
- Dependencias: T27, T28, T30; PR B.
- Tests primero: F2 comprueba invalidación/RESYNC, GET autorizado/vacío/401/403/404 y respuesta antigua después de cambiar organización.
- Hecho cuando: Workspace usa `useApi`, conserva coordinación de recargas y tratamiento de acceso/error, no restaura detalle desde evento ni conserva una recarga denegada como exitosa. Pasa `cd frontend && pnpm test`.

- [x] **T32. Preparar la observación E2E de receptores reales.** RF-001, RF-002, RF-006, RF-010
- Nota: desglose interno sin cambio de alcance, 2026-11-13; confirmado por el usuario, C4 intacta y B en un único PR:
  - [x] T32a: fixtures aisladas de dos tenants y sesiones reales.
  - [x] T32b: captura del transporte por receptor antes del dispatcher.
  - [x] T32c: arnés de barreras de commit/evaluación entre procesos.
- Precisión de ejecución, 2026-11-13: E1/E2 quedan en `e2e/private-realtime.spec.ts`, proyecto `private-realtime`, junto a las regresiones workspace/operation/public existentes. Ejecutar `pnpm exec playwright test e2e/private-realtime.spec.ts --project private-realtime` o el gate completo `pnpm run e2e:test`; los comandos originales siguientes conservan su papel de regresión.
- Dependencias: T19, T22, T26, T31; PR B.
- Tests primero: E1 con fixtures sintéticas de dos tenants, sesiones/roles/pestañas y captura del socket **antes** del dispatcher; control de orden de publicación/commit desde el arnés.
- Hecho cuando: las aserciones de recepción/no recepción no se satisfacen solo ocultando UI; no se añade endpoint productivo ni se amplía seed de producción. Pasan `cd frontend && pnpm run typecheck:e2e` y `cd frontend && pnpm exec playwright test e2e/realtime-workspace.spec.ts --project workspace` con el escenario de fixtures incluido.

- [x] **T33. Verificar autorización y revocación con sockets abiertos.** RF-001, RF-002, RF-003, RF-004, RF-005, RF-007, RF-008, RF-009, RF-011, RF-013
- Dependencias: T14, T32; PR B.
- Tests primero: E1 compara GET/socket para lectores generales, multirrol, otro tenant y asignados/no asignados; retira sesión/membresía/rol con orden de commit controlado y concede de nuevo donde corresponda.
- Hecho cuando: el desautorizado no recibe ni existencia ni IDs; retirar oficial/permiso no requerido no restringe HTTP ni evento, y tránsito aprobado antes del corte se distingue del posterior. Pasa `cd frontend && pnpm exec playwright test e2e/realtime-workspace.spec.ts --project workspace`.

- [x] **T34. Verificar recuperación real sin replay y público independiente.** RF-010, RF-014, RF-015, RF-016, RF-017, RF-018
- Nota: desglose interno sin cambio de alcance, 2026-11-13; confirmado por el usuario, C4 intacta y B en un único PR:
  - [x] T34a: inyección de fallo exclusiva de autorización en fixture/arnés de pruebas, sin ruta productiva ni configuración de producción.
  - [x] T34b: recuperación sin evento adicional, sin replay y con sockets conectados.
  - [x] T34c: acta terminal, contexto cambiado y carril público independiente.
- Dependencias: T24, T25, T29, T30, T31, T32; PR B.
- Tests primero: E2 interrumpe solo comprobación privada mediante arnés de test, mantiene sockets, publica, recupera sin evento adicional y observa RESYNC+GET; acta terminal y contexto cambiado.
- Hecho cuando: no hay replay, desconexión masiva ni señal privada pública, se reconstruye contexto vigente y el receptor público mantiene contrato/recuperación. Pasan `cd frontend && pnpm exec playwright test e2e/realtime-operation.spec.ts --project operation` y `cd frontend && pnpm exec playwright test e2e/realtime-public.spec.ts --project public`.

- [x] **T35. Verificar regresión frontend, accesibilidad e idioma.** RF-010, RF-013, RF-015, RF-016, RF-017, RF-018
- Dependencias: T27–T34; PR B.
- Tests primero: F1/F2 y regresiones existentes, sin crear etiquetas/estados de conexión nuevos; si hubiera mensaje visible necesario, test ES/EN, teclado y ausencia de recursos denegados.
- Hecho cuando: pasan `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck`, `cd frontend && pnpm run lint`, `cd frontend && pnpm run build` y `cd frontend && pnpm run typecheck:e2e`. Documentar si no hay UI nueva; cualquier cambio visual exige inspección real y evidencia, no afirmar validación visual por build.

- [x] **T36. Preparar despliegue coordinado y contingencia fail-closed.** RF-002, RF-011, RF-014, RF-016, RF-017, RF-020
- Dependencias: T20, T22, T23, T25, T26, T34; PR B.
- Tests primero: S1/S2 ensayan función ausente/error de migración y contingencia sin emisiones organizativas, manteniendo HTTP/público. Revisar el procedimiento para no dejar procesos API antiguos haciendo broadcast.
- Hecho cuando: README/AGENTS documentan migración previa, sustitución/drenaje de todos los API, compatibilidad de filas históricas y rollback que **no** restaura rooms vulnerables ni borra migración/outbox. Pasan `cd backend && pytest -q tests/test_realtime_delivery.py -k rollout` y `git diff --check`; no se ejecuta despliegue productivo como parte de la prueba.

- [x] **T37. Gate indivisible de PR B.** RF-001, RF-002, RF-006, RF-011, RF-012, RF-014, RF-015, RF-016, RF-017, RF-018, RF-019, RF-020
- [x] Gate local completo (2026-11-13): backend PostgreSQL 3617 pass; frontend 968 pass/1 skip; E2E Compose 59 pass; infraestructura, migraciones 055/runner y escaneos. Evidencia y límites en `verificacion.md`.
- [x] CI de PR/push y revisión automatizada de B: PR #77, fix `57cf9f51`, ambos runs verdes y E2E 59 pass (2026-11-13). Hallazgo comunicado de Devin Review reproducido en rojo y corregido; check de revisión verde, cero comentarios inline en GitHub. Detalles y límites en `verificacion.md`.
- [x] Fusión de B: #77 fusionado en `ca136b2c1ebd1a2b0d613eafc575d32e055ddfa8`, comprobado por API el 2026-11-13. CI final de `5daa6d5c`: PR 43499246334 y push 43499235618 success; frontend 978 pass/1 skip, E2E PR 60 pass, Devin Review sin hallazgos. Autoriza iniciar C; F8 pendiente de aceptación y R32f abierto hasta T49.
- Dependencias: T18–T36; PR B.
- Tests primero: regresión completa y E1/E2 mínimos, incluida no recepción antes de UI, sin posponer estos controles a C.
- Hecho cuando: pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q`, `cd backend && python -m compileall -q app`, `cd frontend && pnpm run e2e:test` y `git diff --check`, junto con frontend T35 e infrastructure/security de CI. CI PR/push verdes y revisión de B; no hay fallback a broadcast ni implantación parcial. Fusionar B antes de C, sin declarar aún cierre R32f/F8 aceptado.

## PR C — Regresión ampliada, seguridad y cierre (T38–T49)

Depende de B fusionado y verde. No introduce una arquitectura distinta ni pospone arreglos de seguridad observados en B. **T49 es la aceptación expresa del usuario**, no la aprobación de estas tareas.

- [x] **T38. Ampliar revocación y aislamiento a dos procesos API.** RF-001, RF-002, RF-006, RF-007, RF-008, RF-009, RF-010, RF-011
- Dependencias: T37; PR C.
- Tests primero: D2/E1 ejecuta procesos distintos con sockets de la misma persona y de dos tenants, evento pendiente, commit de retirada y evaluación posterior en cada proceso; reconexión al otro proceso.
- Hecho cuando: ningún proceso reutiliza permisos antiguos o se beneficia de no recibir una invalidación Redis; registrar la topología de prueba real. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k multiprocess`; extender las fixtures sin añadir servicios/configuración productiva ni confundir mocks con procesos reales.

**Desglose interno sin cambio de alcance, 2026-11-13**, confirmado por el usuario; sin presupuesto de tiempo por tarea. C4 y un único PR C se mantienen.
- [x] T38a: dos API reales test-only, DB/Redis compartidos, IPC independiente y PID/puertos distintos.
- [x] T38b: barreras por proceso, evento pendiente y retirada con commit antes de evaluación; RLS y dos tenants reales.
- [x] T38c: sesiones/pestañas en ambos procesos, captura del transporte y reconexión al otro API sin replay.

- [ ] **T39. Ampliar L1 con ráfagas, DB lenta y memoria acotada.** RF-001, RF-011, RF-014, RF-016, RF-018
- Dependencias: T16, T37, T38; PR C.
- Tests primero: L1 reproduce dos procesos, muchos sockets/principales, cero destinatarios, error/latencia DB y episodios repetidos de suspensión/recuperación.
- Hecho cuando: se registran dataset, llamadas de red/trabajo SQL, p50/p95, retraso y memoria, sin crecimiento por pérdidas ni decisiones autorizadas acumuladas; lotes máximos 256, sin caché. No inventar SLA ni usar la llamada exterior para ocultar trabajo interno. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k load` y se adjunta evidencia de L1 en `verificacion.md`.
- [ ] T39a: 1.000 sockets/100 principales y borde 256/257; llamadas y trabajo SQL interno.
- [ ] T39b: ráfagas, cero destinatarios, DB lenta/caída y suspensión/recuperación repetidas en ambos procesos.
- [ ] T39c: artefacto reproducible de p50/p95, retraso, memoria y dataset; aceptación estructural sin SLA inventado.

- [ ] **T40. Ampliar fallos y recuperación parcial por conexión/proceso.** RF-006, RF-009, RF-010, RF-014, RF-016, RF-017, RF-018
- Dependencias: T38; PR C.
- Tests primero: S2/D2 con comprobación caída para un lote/proceso, otro operativo, errores repetidos, control fallido, sesión/membresía retirada durante suspensión y proceso reiniciado.
- Hecho cuando: reautoriza a cada afectado, coalesce RESYNC y descarta marca al cambiar generación; público/otros autorizados no heredan suspensión ajena, reinicio recupera por JOIN/HTTP y nunca replay. Pasan `cd backend && pytest -q tests/test_realtime_delivery.py -k partial_recovery` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k recovery`.

- [ ] **T41. Completar regresión E2E de identidades y ciclo de transporte.** RF-001, RF-002, RF-003, RF-004, RF-005, RF-007, RF-008, RF-009, RF-010, RF-015, RF-017, RF-018
- Dependencias: T33, T34, T38, T40; PR C.
- Tests primero: E1/E2 amplían sesiones/pestañas, permisos restantes, expiración, cambio de organización/identidad durante GET, duplicados, reconexión, stream trim/reset y acción ocupada.
- Hecho cuando: se comprueban ausencia en transporte, reconstrucción HTTP y no duplicación, sin gracia artificial ni sleeps que sustituyan barreras de commit. Pasa `cd frontend && pnpm run e2e:test` sin omisiones; artefactos saneados no contienen cookies/tokens/payloads privados.

- [ ] **T42. Auditar matriz pública y exclusiones F1/F9/sonda.** RF-012, RF-013, RF-016, RF-019, RF-020
- Dependencias: T22, T37, T41; PR C.
- Tests primero: S3/E2 compara respuestas HTTP anónimas y los tres eventos/rooms públicos, variantes privadas con nombre compartido y tipos excluidos inyectados en stream.
- Hecho cuando: ni expedientes/evidencias/avisos F9 ni documentos/nacimiento/edad sensible/motivos/auditoría aparecen; sonda procesada en Redis pero cero Socket.IO, F1 sin catálogo aprobado sigue denegado. Pasan `cd backend && pytest -q tests/test_realtime_policy.py tests/test_outbox_worker.py tests/test_outbox_probe.py` y `cd frontend && pnpm exec playwright test e2e/realtime-public.spec.ts --project public`; evidencia de matriz 020 sin campos/actores nuevos.

- [ ] **T43. Ejecutar backend completo y migraciones de cierre.** RF-001, RF-002, RF-003, RF-004, RF-005, RF-006, RF-007, RF-008, RF-009, RF-011, RF-012, RF-014, RF-019, RF-020
- Dependencias: T38, T39, T40, T42; PR C.
- Tests primero: regresión unitaria/DB completa tras el último cambio, sin saltar tests antiguos por introducir el filtro.
- Hecho cuando: pasan `cd backend && pytest -q`, `cd backend && RUN_DATABASE_TESTS=1 pytest -q`, `cd backend && python -m compileall -q app`, `cd backend && ruff check .` y `sh -n infra/postgres/migrate.sh`; repetir migración limpia/054→055 y runner MIGRATION_TARGET con entorno de T15. Registrar skips y sus condiciones, sin llamar completos a tests DB omitidos.

- [ ] **T44. Ejecutar frontend y runner E2E completos de cierre.** RF-010, RF-013, RF-015, RF-016, RF-017, RF-018
- Dependencias: T41, T42; PR C.
- Tests primero: regresiones de dispatcher/reload/composables, planilla clásica/táctica y pantallas existentes; no añadir conexiones ni mensajes de estados incompatibles.
- Hecho cuando: pasan `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck`, `cd frontend && pnpm run lint`, `cd frontend && pnpm run build`, `cd frontend && pnpm run typecheck:e2e` y `cd frontend && pnpm run e2e:test`. Evidencia del runner 0, sin reemplazarlo por casos dirigidos; documentar inspección visual si cambió una superficie visible, o su no aplicación.

- [ ] **T45. Ejecutar gates de seguridad, infraestructura y privacidad de logs.** RF-001, RF-002, RF-006, RF-012, RF-014, RF-016, RF-020
- Dependencias: T39, T40, T42, T43, T44; PR C.
- Tests primero: mantener los self-tests/contratos actuales; revisar que los escenarios de fallo no registran tokens, negocio, evidencia ni identidades innecesarias y no crean historial de recepción.
- Hecho cuando: pasan `cd backend && bandit -r app -ll`, `pip-audit -r backend/requirements.txt`, `docker compose config -q`, `python3 infra/scripts/check_env_contract.py --self-test` y `python3 infra/scripts/verify_version_sources.py --exclude-constitution`; ejecutar también perfil producción con secretos externos de prueba, contratos, auditoría pnpm con filtro constitucional, Trivy fijado y Gitleaks sobre árbol comprometido según AGENTS/CI. Sin exclusiones nuevas ni defaults de desarrollo productivos; registrar salidas de cada gate.

- [ ] **T46. Consolidar documentación observable y evidencias por RF/RNF.** RF-001, RF-004, RF-005, RF-007, RF-008, RF-011, RF-013, RF-014, RF-015, RF-016, RF-017, RF-018, RF-019, RF-020
- Dependencias: T36, T39, T40, T41, T42, T43, T44, T45; PR C.
- Tests primero: confrontar las afirmaciones documentales con las salidas/escenarios ya ejecutados, sin inventar un rojo ni rehacer auditorías históricas.
- Hecho cuando: README/AGENTS/manual describen catálogo, corte real, pérdida/recuperación HTTP, compatibilidad, despliegue y rollback; corregir la descripción vigente de la sonda como evento de socket. `verificacion.md` enlaza todos los RF/RNF, tests, SHA/artefactos y límites. Pasa `git diff --check`; MEMORY refleja validación real, sin marcar implementado ni cerrar R32f/F8 antes de aceptación T49.

- [ ] **T47. Vigilar CI y revisión del PR C y su push.** RF-001, RF-002, RF-011, RF-014, RF-016, RF-017, RF-018, RF-020
- Dependencias: T43, T44, T45, T46; PR C.
- Tests primero: comprobar el SHA publicado y los jobs de `.github/workflows/ci.yml`; ante un fallo causado por el cambio, reproducirlo con el test adecuado antes del fix y volver a comprobar el nuevo SHA.
- Hecho cuando: `git_pr_checks(wait_mode="all")` está verde y `gh run view <run_id> --json event,headSha,status,conclusion,jobs` acredita también push del mismo SHA; backend/frontend/infrastructure/security verdes y E2E verde en PR (omitido en push de feature conforme al workflow). Revisión independiente y hallazgos resueltos o decisión humana explícita, sin declarar verde un check pendiente ni crear excepciones silenciosas.

- [ ] **T48. Auditar el cierre técnico completo contra spec, plan y constitución.** RF-001, RF-002, RF-003, RF-004, RF-005, RF-006, RF-007, RF-008, RF-009, RF-010, RF-011, RF-012, RF-013, RF-014, RF-015, RF-016, RF-017, RF-018, RF-019, RF-020
- Dependencias: T1–T47; PR C.
- Tests primero: cruzar la tabla siguiente y plan §9 con evidencia ejecutada P/D/S/F/E/L y cada criterio constitucional, incluidos normal/vacío/error, cortes y ausencia de recepción.
- Hecho cuando: `verificacion.md` no deja ningún RF sin prueba ni confunde tests puros/mocks con RLS/procesos reales; estados documentales no afirman aceptación todavía. Pasan `git diff --check` y `git status --short` como revisión de alcance; citar comandos/artefactos por RF y CI del SHA validado. Si falta evidencia, mantener la tarea abierta y no pedir aceptación como si estuviera terminada.

- [ ] **T49. Obtener aceptación expresa del usuario y cerrar formalmente F8.** RF-001, RF-002, RF-003, RF-004, RF-005, RF-006, RF-007, RF-008, RF-009, RF-010, RF-011, RF-012, RF-013, RF-014, RF-015, RF-016, RF-017, RF-018, RF-019, RF-020
- Dependencias: T1–T48; PR C.
- Tests primero: presentar evidencia técnica, límites y SHA validado al usuario; esta tarea requiere su aceptación de la **implementación**, no basta aprobar spec/plan/tareas ni una revisión automática.
- Hecho cuando: el usuario acepta expresamente, con fecha y alcance registrados en `verificacion.md`/MEMORY; solo entonces marcar spec/plan/tareas implementados y cerrar R32f/F8 como prerrequisito de F1, sin habilitar sus borradores ni Socket.IO F9. Pasan `git diff --check` y comprobación de CI PR/push del commit documental final mediante `gh run view <run_id> --json event,headSha,status,conclusion,jobs`; cualquier cambio posterior de código vuelve a validación antes del cierre. Sin aceptación o con CI pendiente, esta casilla sigue abierta.

## Cobertura comprobable y condiciones de cierre

Cada RF aparece en cabeceras de tareas concretas además de T48/T49. La tabla destaca tareas de construcción y de comprobación; no limita el resto de cabeceras ni afirma cobertura ejecutada.

| RF | Construcción / comprobaciones principales | Validación y aceptación final |
|---|---|---|
| RF-001 | T1, T4, T7, T11, T12, T19, T33 | T38, T43, T48, T49 |
| RF-002 | T1, T4, T6, T10, T11, T18, T19 | T33, T38, T43, T48, T49 |
| RF-003 | T1, T7, T12, T19 | T33, T41, T43, T48, T49 |
| RF-004 | T1, T7, T12 | T33, T41, T43, T48, T49 |
| RF-005 | T1, T7, T11, T12, T19, T31 | T33, T41, T43, T48, T49 |
| RF-006 | T8, T10, T13, T18, T24, T25 | T32, T38, T40, T43, T48, T49 |
| RF-007 | T8, T10, T13, T14, T19, T25 | T33, T38, T41, T43, T48, T49 |
| RF-008 | T12, T13, T14, T19 | T33, T38, T41, T43, T48, T49 |
| RF-009 | T9, T12, T13, T14, T19, T24, T25 | T33, T38, T40, T41, T43, T48, T49 |
| RF-010 | T6, T9, T18, T26, T27, T30, T31 | T34, T38, T40, T41, T44, T48, T49 |
| RF-011 | T8, T13, T14, T19, T21, T23, T26 | T33, T38, T39, T43, T48, T49 |
| RF-012 | T2, T3, T4, T7, T11, T15, T19, T22 | T42, T43, T45, T48, T49 |
| RF-013 | T3, T5, T11, T19, T21, T28, T29 | T33, T35, T42, T44, T48, T49 |
| RF-014 | T9, T13, T15, T16, T20, T23, T24, T25 | T34, T39, T40, T43, T45, T48, T49 |
| RF-015 | T5, T21, T27, T28, T29, T30, T31 | T34, T35, T41, T44, T48, T49 |
| RF-016 | T2, T5, T20, T21, T25, T28, T36 | T34, T39, T40, T42, T44, T48, T49 |
| RF-017 | T9, T23, T24, T25, T27, T29, T30, T31 | T34, T40, T41, T44, T48, T49 |
| RF-018 | T3, T6, T9, T16, T18, T20, T21, T24, T26, T27, T28, T30, T31 | T35, T39, T40, T41, T44, T48, T49 |
| RF-019 | T2, T17, T22 | T37, T42, T43, T46, T48, T49 |
| RF-020 | T2, T17, T22, T36 | T37, T42, T43, T45, T46, T48, T49 |

RF sin cubrir en la planificación: **ninguno (20/20)**. RF-004 y retirada de asignación en RF-008 se verifican sin inventar una lectura restringida: el catálogo actual admite miembros lectores sin oficial/permiso de escritura; el predicado condicional solo se prueba con fixture técnica hasta que exista una lectura real aprobada que lo exija.

RNF-001/002: T1–T15, T19, T33, T38, T42; RNF-003: T14, T33, T38, T41; RNF-004: T20–T31, T34–T37, T44; RNF-005: T26, T38–T41; RNF-006: T23, T40, T45, T46; RNF-007: T35, T44. La verificación constitucional y los criterios obligatorios se cierran con T43–T49, no por redactar esta tabla.

Las tareas futuras no se marcan al aprobar su redacción. C1–C4 están confirmadas; cualquier decisión nueva que cambie el comportamiento o la partición exige consulta y aprobación, no un supuesto en implementación. No hay código funcional, migraciones aplicadas ni evidencia de ejecución nueva en esta entrega documental.
