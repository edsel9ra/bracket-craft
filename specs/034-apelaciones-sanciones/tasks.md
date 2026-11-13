# Tareas 034 — Apelaciones y resoluciones de sanciones

Estado: **aprobado** por el usuario el 2026-11-12, con PR B dividido en B1/B2. Spec y plan aprobados, incluidas C1–C5. Fase Tareas cerrada; fase actual Implementación, PR A. T1–T10 realizadas; T11–T55 pendientes.

Son **55 tareas**, estimadas en **20–30 min de trabajo por tarea**, en orden de dependencia. **Propuesta: no dividir la spec**, aunque supera diez tareas: la duración efectiva, el bloqueo/cumplimiento y la coordinación 033 forman una garantía indivisible; separarlos en specs permitiría activar resoluciones con lectores antiguos. Por decisión del usuario, la entrega pasa a cinco PRs secuenciales A → B1 → B2 → C → D. Cada PR se verifica y fusiona antes de empezar el siguiente; B1 solo activa lectores equivalentes sin resoluciones y B2 no se fusiona parcialmente. Si una tarea excede el límite al ejecutarla, descomponerla antes de seguir, sin ampliar alcance ni marcarla parcialmente hecha.

En cada tarea: escribir primero los tests indicados, comprobar rojo por la funcionalidad ausente, código mínimo y verde; registrar evidencia antes de marcar. Una tarea cada vez. Las pruebas deben cubrir normal, vacío y error cuando apliquen. Para las tareas pendientes, los archivos de test F9 citados son entregables futuros, no pruebas existentes ya ejecutadas.

Entorno PostgreSQL como CI: exportar previamente `DATABASE_URL` (rol app) y `DATABASE_ADMIN_URL` (administración de una BD local de prueba); los comandos `RUN_DATABASE_TESTS=1` heredan esas variables. No usar producción ni guardar credenciales en archivos versionados. Los tests RLS usan `bracket_app`, dos organizaciones y contextos reales; los mocks no prueban aislamiento, triggers ni carreras.

**Esquema:** T1–T8 preparan la única migración **nueva** `040_sanction_appeals.sql` del PR A, tras comprobar que 040 sigue libre. Son partes de su construcción, no ediciones de 001–039. Usar bases de prueba desechables recreadas, nunca modificar una migración cuyo checksum esté registrado en un volumen persistente. Tras su primera aplicación persistente/fusión, cualquier ajuste requiere la siguiente migración nueva libre (041 o posterior), también en B–D si surgiera necesidad. No relajar 016, 009, 037 ni `03_hardening`; no crear expedientes desde `appealed` ni editar duración original.

## PR A — Fundación inerte (T1–T10)

Sin rutas de escritura ni UI activadas. Las piezas BD de T1–T8 se verifican juntas antes de fusionar A; ningún grant provisional queda abierto. Dependencias internas: T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10.

- [x] **T1. Nueva 040: expedientes, eventos y unicidad de pendiente.** RF-001, RF-009, RF-016, RF-029
- Hecho cuando: tablas de expediente/eventos nacen con RLS/FORCE, FK tenant, motivo y autor, índice parcial compartido por apelación/propuesta y grants mínimos; no se importan filas `appealed`. Pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_040.py -k cases` y `sh -n infra/postgres/migrate.sh`.

- [x] **T2. Nueva 040: decisiones y resoluciones inmutables.** RF-004, RF-005, RF-009, RF-020, RF-034
- Hecho cuando: decisiones/resoluciones registran base original/efectiva, responsable y motivo, evidencia opcional sin archivos y FK tenant; UPDATE/DELETE rechazados, sin tocar `matches_suspended`. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_040.py -k decisions`.

- [x] **T3. Nueva 040: aplicaciones y snapshots por partido.** RF-010, RF-014, RF-030
- Hecho cuando: aplicaciones y snapshots son append-only, tienen FK tenant/unicidad y permiten distinguir decisión, aplicación pendiente y partido efectivo sin exigir un partido ficticio a declaraciones. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_040.py -k applications`.

- [x] **T4. Nueva 040: perjuicio, autorizaciones F9 y avisos.** RF-013, RF-023, RF-032, RF-033
- Hecho cuando: las tres tablas nacen con RLS/FORCE y referencias tenant; autorización no reutiliza la 033 y aviso es único por acto/destinatario/canal, sin evidencia en su cuerpo. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_040.py -k auxiliary`.

- [x] **T5. Nueva 040: transiciones, catálogo y anti-auto-decisión en BD.** RF-005, RF-009, RF-020, RF-021, RF-022, RF-029
- Hecho cuando: INSERT directo del autor como decisor falla aunque cambie de rol; transición terminal no se reabre, decisión/evento obligatorio se comprueba al commit y una propuesta solo admite aprobar/rechazar su medida. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_040.py -k transitions`.

- [x] **T6. Nueva 040: RBAC y lecturas operativas mínimas.** RF-014, RF-015, RF-016, RF-018, RF-019
- Hecho cuando: claves nuevas en `core/roles.py`, defaults owner/admin en roles nuevos/existentes y funciones de elegibilidad por partido verifican permiso sin revelar expediente/evidencia; cerrar o rectificar no concede consulta F9. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_040.py -k permissions`.

- [x] **T7. Nueva 040: scopes y capacidades de plataforma acotadas (C2).** RF-015, RF-016, RF-023, RF-024
- Hecho cuando: funciones F9 verifican admin/dueño/organización/expediente y contexto local propio, grants y search_path seguros; autorización 033 no abre F9 y no se amplía membresía global ni BYPASSRLS. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_040.py -k platform`.

- [x] **T8. Nueva 040: puente 033 y entrega privada; gate de migración.** RF-007, RF-016, RF-025, RF-032, RF-033
- Hecho cuando: funciones de cierre consecuente comprueban publicación/cambio acreditado y funciones de entrega atan el aviso al evento reclamado, sin UPDATE genérico ni suplantación de miembro. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_040.py`, verificando la migración real sobre BD limpia y 039→040, con checksums previos intactos. Pasan además `sh -n infra/postgres/migrate.sh` y el runner de abajo, que prueba el mecanismo MIGRATION_TARGET con migraciones sintéticas, no sustituye los tests reales de la 040.
- Comando del runner desde raíz, con PGHOST/PGPORT/PGUSER/PGPASSWORD exportadas para PostgreSQL local de prueba: `docker run --rm --network host -v "$PWD/infra:/infra:ro" -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD postgres:17-alpine sh /infra/scripts/test_migrate_target.sh`.

- [x] **T9. Proyección pura de duración efectiva y cumplimientos.** RF-003, RF-010, RF-014
- Hecho cuando: sin resolución equivale al comportamiento base; reducción mayor/igual/menor que cumplido, anulación y declaración conservan historial, saldo nunca negativo ni crédito y `appealed` no crea recurso. Pasa `cd backend && pytest -q tests/test_sanction_effective.py -k duration`.

- [x] **T10. Funciones temporales puras y compatibilidad de legado (C4).** RF-011, RF-012, RF-027, RF-030
- Hecho cuando: tiempo recibido por parámetro, primera apertura frente a calendario/reprogramación, partido en curso y legado sin fecha tienen resultados deterministas; no reconstrucción inventada ni reloj interno. Pasa `cd backend && pytest -q tests/test_sanction_effective.py -k temporal`.

## PR B1 — Lectores y cumplimientos efectivos

Depende de A. Orden: T11 → T12 → T14 → T15 → T24 → T25 → T26 → T35. No expone ninguna ruta de escritura de expedientes: los contratos de T11 son inertes; T35 solo registra su lectura privada. Fusionable porque, sin resoluciones, la duración efectiva equivale a la original. Antes de fusionar pasan las pruebas de lectores, apertura, cumplimientos y avisos de estas tareas y `cd backend && RUN_DATABASE_TESTS=1 pytest -q`; no se activa ninguna creación/decisión de expediente.

- [x] **T11. Contratos estrictos del módulo F9.** RF-018, RF-020, RF-028, RF-034
- Hecho cuando: DTOs con extra forbid, UUID, enums, representación, duración y paginación acotadas; motivo vacío, campos extra/archivos y alcance nuevo rechazados; evidencia ausente válida. Pasa `cd backend && pytest -q tests/test_sanction_schemas.py`.

- [x] **T12. Coordinador disciplinario y orden de bloqueos (C3).** RF-016, RF-025, RF-029, RF-030
- Hecho cuando: helper transaccional por organización precede fase/versiones/partidos/segmentos/jugadores/sanciones/expediente/autorización, con IDs estables; no comparte locks entre tenants. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_concurrency.py -k coordinator`.

- [x] **T14. Adoptar protocolo en apertura y cierre de partido.** RF-012, RF-014, RF-030
- Hecho cuando: primer segmento y cierre adquieren coordinador antes de sus locks actuales; fecha se captura después de esperar locks, sin alterar otras reglas operativas. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_concurrency.py -k match_lock`.

- [x] **T15. Repositorio efectivo en lote con contexto RLS.** RF-006, RF-010, RF-014, RF-016
- Hecho cuando: carga original/resoluciones/aplicaciones/cumplimientos sin N+1 y conserva origen; lectura operativa usa funciones mínimas sin conceder evidencia ni consulta de otros expedientes. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_readers.py -k repository`.

- [x] **T24. Aplicar en la primera apertura y registrar snapshot.** RF-010, RF-012, RF-030
- Hecho cuando: apertura aplicable lineariza efecto, partido/instante y snapshot; no depende de convocatoria ni calendario, y no aplica resolución excluida por rectificación. Partido iniciado conserva lectura previa. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_effective_integration.py -k opening`.

- [x] **T25. Bloqueo del cierre con duración efectiva por partido.** RF-003, RF-014, RF-030, RF-031
- Hecho cuando: `_has_suspended_players` y llamadas validan pendientes aplicables, exclusión del acta origen y corte de creación; status actual no levanta indebidamente restricción de un partido ya comenzado. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_readers.py -k blocking`.

- [x] **T26. Cumplimientos y paso a served con duración efectiva.** RF-010, RF-012, RF-014
- Hecho cuando: INSERT y actualización de `_serve_suspensions` usan los mismos datos efectivos, IDs bloqueados y deduplicación, conservan filas y no reviven una anulada tras cerrar un partido anterior. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_readers.py -k serves`.

- [x] **T35. Lectura privada de aviso al preparar alineación.** RF-014, RF-015, RF-017, RF-031
- Hecho cuando: permiso operativo del partido da aviso mínimo por jugador sin expediente/motivo/evidencia; guardar/publicar no bloquean ni modifican alineación y cierre sigue revalidando. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_warnings.py`.

## PR B2 — Expedientes y efectos coordinados

Depende de B1. Orden: T13 → T16 → T17 → T18 → T19 → T20 → T21 → T22 → T23 → T27 → T28 → T29 → T30 → T31 → T32 → T33 → T34 → T36 → T37 → T38 → T39. Mantener las rutas de escritura sin registrar hasta T36; T39 verifica el núcleo completo con los lectores ya fusionados en B1. Incluye API, decisiones, coordinación 033, plataforma, avisos y concurrencia. No fusionar fragmentos inseguros de B2.

- [x] **T13. Adoptar protocolo en publicación 033 de organización/plataforma.** RF-007, RF-011, RF-025
- Hecho cuando: no se bloquea solicitud antes de fase; publicación usa coordinador y mantiene el orden global de la 033, sin cambios a resultados ni permisos. Pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_rectification_concurrency.py` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_concurrency.py -k rectification_lock`.

- [x] **T16. Presentar apelación sin caducidad.** RF-001, RF-002, RF-003, RF-018, RF-026, RF-027, RF-028, RF-034
- Hecho cuando: solo miembro con facultad presenta en nombre de equipo/jugador; tres orígenes y dos ámbitos, archivo y sanción cumplida no añaden caducidad; motivo obligatorio/evidencia opcional, sin cambiar sanción/cumplimientos ni crear acceso del representado. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_cases.py -k appeal`.

- [x] **T17. Presentar propuesta administrativa inmutable.** RF-003, RF-019, RF-020, RF-022, RF-028, RF-034
- Hecho cuando: miembro con resolver propone solo anular/reducir con motivo y medida auditados; no apelación ficticia ni efecto suspensivo y plataforma no propone. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_cases.py -k proposal`.

- [x] **T18. Bandeja, sanciones y detalle privados.** RF-006, RF-009, RF-015, RF-016, RF-017
- Hecho cuando: consulta separada, paginación/filtros y detalle muestran historia, procedencia, duración original/efectiva y efecto pendiente sin mezclar tenants; recibo de presentar no abre consulta completa. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_cases.py -k read`.

- [x] **T19. Preview de decisión sin escritura.** RF-004, RF-010, RF-014, RF-020, RF-030
- Hecho cuando: consulta+resolver obtiene base esperada y efectos previstos, no aplicados; cero cambios a ledger, status, auditoría o outbox, también con motivo/evidencia vacíos de prueba. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_cases.py -k preview`.

- [x] **T20. Retirada auditada solo por autor pendiente.** RF-009, RF-015, RF-029, RF-034
- Hecho cuando: autor con legitimación vigente retira con motivo obligatorio, sin alterar sanción; ajeno, terminal y motivo vacío se rechazan; transición/evento atómicos. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_cases.py -k withdraw`.

- [ ] **T21. Decidir mantener/rechazar con separación de personas.** RF-004, RF-005, RF-020, RF-021, RF-022, RF-034
- Hecho cuando: actor distinto y facultad vigente, también aunque autor acumule roles; mantener solo apelación, rechazar solo propuesta, decisión auditada sin cambio de elegibilidad. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_cases.py -k decide_no_effect`.

- [ ] **T22. Registrar anulación/reducción y declaraciones sin mutar original.** RF-004, RF-005, RF-010, RF-020, RF-022, RF-027, RF-030
- Hecho cuando: resolución conserva valores originales/anteriores/resultantes; efecto queda pendiente si cambia elegibilidad, cumplida admite declaración sin partido ficticio, no aumento/ámbito/crédito ni UPDATE de duración. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_cases.py -k resolution`.

- [ ] **T23. Terminales, segunda instancia y revalidación de base.** RF-011, RF-025, RF-029
- Hecho cuando: misma base resuelta no admite otro recurso; retirada permite nueva presentación y cierre rectificativo exige presentación manual vinculada. Base cambiada cierra sin decisión ni consumo; respuesta no revierte el cierre. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_cases.py -k stale`.

- [ ] **T27. Publicación 033 cierra pendientes afectados en su transacción.** RF-007, RF-009, RF-011, RF-012, RF-025
- Hecho cuando: cancelación/recreación/cambio disciplinario cierra expedientes con referencia/motivo; marcador sin cambio no cierra; fallo del puente revierte publicación y outbox completos. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_rectification.py -k closure`.

- [ ] **T28. Recálculo 033 respeta historia F9 e inventario de lectores.** RF-007, RF-008, RF-011, RF-012, RF-017
- Hecho cuando: duración derivada original no neutraliza reducción; recreación no copia efecto/autorización y deja constancia; resolución pendiente afectada queda excluida explícitamente. Deduplicación de rojas y dependencias de regeneración conservan existencia histórica. Pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_rectification.py -k reconcile` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_readers.py`, incluido el inventario de lectores.

- [ ] **T29. Constancia mínima de perjuicio acreditado.** RF-008, RF-009, RF-013
- Hecho cuando: guarda autor/fecha/motivo y partidos acreditados en expediente, sin inferir por ausencia, compensar, repetir partidos ni tocar resultados/actas/avance o abrir trámite de impacto 033. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_cases.py -k prejudice`.

- [ ] **T30. Concesión y revocación de autorización F9 por dueño.** RF-015, RF-023, RF-024
- Hecho cuando: dueño/admin/organización activos y scope exacto, autorización no reutilizable, rol retirado invalida; grants/revocaciones siguen coordinador y auditoría, sin platform_support. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_platform.py -k authorization`.

- [ ] **T31. Decisión excepcional y consumo transaccional F9.** RF-004, RF-021, RF-023, RF-024
- Hecho cuando: plataforma solo lista/lee/decide su scope con contexto local propio, autor no decide aunque tenga autorización; doble auditoría y consumo junto con decisión, sin privilegio persistente ni membresía. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_platform.py -k decision`.

- [ ] **T32. Registrar y encolar avisos mínimos con cada acto.** RF-032, RF-033, RF-034
- Hecho cuando: decisión/retirada/cierre generan ambos canales y destinatarios deduplicados autorizados; payload solo acto/motivo e identificadores técnicos mínimos, nunca evidencia ni jugadores por esa condición. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_notifications.py -k enqueue`.

- [ ] **T33. Handler interno y lectura privada con revalidación C5.** RF-015, RF-016, RF-032, RF-033
- Hecho cuando: entrega idempotente por evento/aviso, bandeja solo destinatario; pérdida de permiso retiene sin exposición, recuperación permite reintento según outbox, sin conceder consulta F9. Handler explícito no cae al stream Redis ni a rooms organizativos. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_notifications.py -k internal`.

- [ ] **T34. Handler de correo F9 con reintentos.** RF-032, RF-033
- Hecho cuando: usa SMTP existente, revalida destinatario, fallo conserva aviso sin revertir acto; posible repetición del correo nunca duplica decisión, sin evidencia ni publicación Redis por fallback. Pasan `cd backend && pytest -q tests/test_sanction_email.py` y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_notifications.py -k email`.

- [ ] **T36. Registrar router completo y probar contratos HTTP.** RF-002, RF-006, RF-015, RF-018, RF-020, RF-023, RF-029, RF-034
- Hecho cuando: rutas organización y `/api/v1/platform` registradas en `main.py`, sin presentar/proponer desde plataforma; 401/403/404 indistinguible/409/422 y recibos mínimos siguen plan, preview no escribe. Pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_api.py` y `cd backend && python -m compileall -q app`.

- [ ] **T37. Carreras reales de casos, autorizaciones y comienzo.** RF-021, RF-023, RF-025, RF-029, RF-030
- Hecho cuando: dos sesiones prueban apelación/propuesta, doble decisión, retirada/decisión, revocar/decidir, 033/decisión y apertura/cierre entre torneos; un único resultado y sin deadlock ni efecto retroactivo. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_concurrency.py`.

- [ ] **T38. Rollback e aislamiento de la operación completa.** RF-004, RF-005, RF-009, RF-016, RF-024, RF-025, RF-033
- Hecho cuando: fallos tras decisión/efecto/auditoría/outbox revierten todo y consumo; fallo posterior de entrega no revierte acto; FK cruzadas, scope vencido y contexto del pool no filtran tenants. Pasa `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_rollback.py tests/test_sanction_security.py`.

- [ ] **T39. Gate B: RBAC, lectores y público sin regresión.** RF-003, RF-007, RF-008, RF-014, RF-015, RF-016, RF-017, RF-019
- Hecho cuando: todos los escritores/lectores B están integrados y las regresiones de cierre/033/matriz pública pasan; ninguna escritura F9 se fusiona antes. Pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_sanction_*.py tests/test_rectification_*.py tests/test_close_match*.py tests/test_public_field_allowlist.py tests/test_public_access_matrix.py` y `cd backend && python -m compileall -q app`.

## PR C — Workspace y aviso preparatorio (T40–T49)

Depende de B2 ya fusionado. Orden T40 → … → T49. Todas las llamadas pasan por `useApi.ts`, los tests usan contratos estrictos y ES/EN; no se comparte payload privado con componentes públicos.

- [ ] **T40. Composable tipado de expedientes y permisos.** RF-006, RF-015, RF-019, RF-029
- Hecho cuando: `useSanctionCases.ts` transporta sesión/organización mediante useApi, pagina/refresca sin mezclar tenants y tipa errores/recibos; sin acceso implícito por presentar. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run typecheck`.

- [ ] **T41. Bandeja Workspace y filtros privados.** RF-006, RF-015, RF-017, RF-027, RF-028
- Hecho cuando: página muestra sanciones/expedientes autorizados, vacío/carga/error, ambos tipos y archivo, con navegación guardada por permiso; ninguna consulta pública. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run lint`.

- [ ] **T42. Detalle con historial y efecto pendiente.** RF-004, RF-006, RF-009, RF-010, RF-011, RF-013, RF-030
- Hecho cuando: original/efectiva/cumplimientos, procedencia, constancias y cierre rectificativo se distinguen; evidencia solo en detalle autorizado, sin presentar como aplicado un efecto pendiente. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run typecheck`.

- [ ] **T43. Formulario de apelación con representación.** RF-002, RF-003, RF-018, RF-026, RF-028, RF-034
- Hecho cuando: miembro autorizado registra representación y motivo; evidencia opcional/enlaces seguros, sin input de archivos; errores y ausencia de caducidad no cambian sanción ni conceden acceso al representado. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run lint`.

- [ ] **T44. Proponer y decidir con confirmación singleFlight.** RF-004, RF-020, RF-021, RF-022, RF-029, RF-030, RF-034
- Hecho cuando: catálogo y preview correctos, autor no decide, propuesta sin efecto, retirada solo autor; useConfirm ES/EN singleFlight evita doble envío y conflicto refresca estado sin segunda instancia. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run typecheck`.

- [ ] **T45. Gestión owner de autorizaciones F9.** RF-015, RF-023, RF-024
- Hecho cuando: owner concede/revoca scope puntual desde detalle con confirmación, estados inválidos/consumidos visibles y ninguna reutilización de autorizaciones 033. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run lint`.

- [ ] **T46. Bandeja interna privada sin ampliar consulta.** RF-015, RF-017, RF-032, RF-033
- Hecho cuando: lectura HTTP paginada muestra solo acto/motivo al destinatario vigente, vacío/error/reintento, sin evidencia ni broadcast; enlace no elude permiso de detalle. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run typecheck`.

- [ ] **T47. Aviso disciplinario en preparación de alineación.** RF-014, RF-017, RF-031
- Hecho cuando: MatchLineupSection/useMatchLineup muestran aviso privado mínimo, accesible y no bloqueante; guardar/publicar y formaciones no se alteran; PublicLineupModal no recibe datos F9. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run lint`.

- [ ] **T48. Integración i18n, navegación y errores accesibles.** RF-006, RF-015, RF-017, RF-029, RF-034
- Hecho cuando: claves ES/EN completas, foco/teclado y tokens existentes, errores 403/404/409/422 sin filtrar expediente y reapertura manual solo cuando procede; no dialogs nativos. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run typecheck && pnpm run lint`.

- [ ] **T49. E2E Workspace con dos personas y tenants.** RF-003, RF-006, RF-018, RF-021, RF-022, RF-025, RF-029, RF-030, RF-031, RF-034
- Hecho cuando: presentar/proponer/decidir, retirada/cierre rectificativo, pendiente/aplicado y aviso no bloqueante se prueban con fixture local sin ampliar seeds productivos. Pasan `cd frontend && pnpm run typecheck:e2e` y, con pila local de prueba preparada, `cd frontend && pnpm exec playwright test e2e/sanction-workspace.spec.ts`.

## PR D — Admin y cierre verificado (T50–T55)

Depende de C. Orden T50 → … → T55; no declarar implementada la spec hasta verificar todos sus RF y obtener revisión humana. La aprobación de estas tareas no sustituye la aceptación de implementación.

- [ ] **T50. Composable y pantalla admin de decisión excepcional.** RF-006, RF-015, RF-021, RF-023, RF-024
- Hecho cuando: `/admin/sanction-cases` lista solo scopes F9, muestra preview/detalle y decide con useApi/useConfirm singleFlight, ES/EN; no permite presentar/proponer ni ve otro expediente. Pasan `cd frontend && pnpm test` y `cd frontend && pnpm run typecheck && pnpm run lint`.

- [ ] **T51. Regresión E2E admin y pública.** RF-007, RF-008, RF-015, RF-016, RF-017, RF-021, RF-023, RF-024
- Hecho cuando: autorización revocada/consumida/ajena y auto-decisión no ejecutan, auditorías coinciden y público no expone sanciones/motivos/evidencia. Pasan `cd frontend && pnpm run typecheck:e2e`, `cd frontend && pnpm exec playwright test e2e/sanction-platform.spec.ts` con pila de prueba, y `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_public_field_allowlist.py tests/test_public_access_matrix.py tests/test_sanction_platform.py`.

- [ ] **T52. Gate backend completo con PostgreSQL y regresión 033.** RF-001, RF-005, RF-009, RF-010, RF-011, RF-012, RF-016, RF-025, RF-030, RF-033
- Hecho cuando: suite completa con rol real, concurrencia/rollback y legado pasa sin modificar expectativas ajenas; evidencia registra resultados e inventario de lectores actualizado. Pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q` y `cd backend && python -m compileall -q app`.

- [ ] **T53. Gate frontend y comprobación visual acotada.** RF-006, RF-015, RF-017, RF-023, RF-029, RF-030, RF-031, RF-032, RF-034
- Hecho cuando: bandeja/detalle/formularios/admin y aviso no bloqueante se verifican en escritorio/móvil con capturas de los estados cambiados, ES/EN y foco, sin datos reales. Pasan `cd frontend && pnpm test && pnpm run typecheck && pnpm run lint && pnpm run build` y `cd frontend && pnpm run e2e`; guardar rutas de evidencia y límites visuales.

- [ ] **T54. Gate de migraciones, infraestructura y seguridad existente.** RF-005, RF-007, RF-016, RF-017, RF-019, RF-023, RF-025
- Hecho cuando: limpio/migrado, checksums, grants y protecciones originales siguen correctos, Compose dev/merge prod con dummy y jobs de seguridad pasan sin exclusiones ni versiones nuevas. Pasan `cd backend && RUN_DATABASE_TESTS=1 pytest -q tests/test_migration_040.py`, `sh -n infra/postgres/migrate.sh`, runner PostgreSQL de T8, `docker compose config -q`, `python3 infra/scripts/check_env_contract.py --self-test` y auditorías/validación de producción con los comandos exactos de AGENTS.md; revisar los jobs backend/infrastructure/security del PR, no inferirlos de checks locales.

- [ ] **T55. Documentación observable y cierre por RF con revisión humana.** RF-001, RF-006, RF-007, RF-010, RF-013, RF-017, RF-019, RF-023, RF-025, RF-029, RF-030, RF-031, RF-032, RF-033, RF-034
- Hecho cuando: README/AGENTS/manual explican flujo privado, separación de personas, efecto diferido y ausencia de segunda instancia; `verificacion.md` relaciona cada RF-001–RF-034 con test/evidencia y límites, MEMORY refleja fase real. Pasan `git diff --check`, `cd backend && python -m compileall -q app` y `cd frontend && pnpm run typecheck`; CI completa backend/frontend/infrastructure/security/e2e en verde y aceptación humana antes de marcar implementada.

## Cobertura comprobable y condiciones de ejecución

Cada RF figura en al menos una cabecera de tarea; la tabla indica una selección de sus comprobaciones, no limita el resto:

| RF | Tareas |
|---|---|
| RF-001 | T1, T16, T52, T55 |
| RF-002 | T16, T36, T43 |
| RF-003 | T9, T16, T17, T25, T39 |
| RF-004 | T2, T19, T21, T22, T31 |
| RF-005 | T2, T5, T21, T22, T38 |
| RF-006 | T15, T18, T36, T40, T41, T42 |
| RF-007 | T8, T13, T27, T28, T39, T51 |
| RF-008 | T28, T29, T39, T51 |
| RF-009 | T1, T2, T5, T18, T20, T27, T29 |
| RF-010 | T3, T9, T15, T19, T22, T24, T26 |
| RF-011 | T10, T13, T23, T27, T28, T42 |
| RF-012 | T10, T14, T24, T26, T27, T28 |
| RF-013 | T4, T29, T42, T55 |
| RF-014 | T3, T6, T9, T14, T15, T19, T25, T26, T35 |
| RF-015 | T6, T7, T18, T20, T30, T35, T36, T39 |
| RF-016 | T1, T6, T7, T8, T12, T15, T18, T33, T38 |
| RF-017 | T18, T28, T35, T39, T41, T46, T47, T51 |
| RF-018 | T6, T11, T16, T36, T43 |
| RF-019 | T6, T17, T39, T40 |
| RF-020 | T2, T5, T11, T17, T19, T21, T22, T36, T44 |
| RF-021 | T5, T21, T31, T37, T44, T49, T50, T51 |
| RF-022 | T5, T17, T21, T22, T44, T49 |
| RF-023 | T4, T7, T30, T31, T36, T37, T45, T50 |
| RF-024 | T7, T30, T31, T38, T45, T50, T51 |
| RF-025 | T8, T12, T13, T23, T27, T37, T38, T49 |
| RF-026 | T16, T43 |
| RF-027 | T10, T16, T22, T41 |
| RF-028 | T11, T16, T17, T41, T43 |
| RF-029 | T1, T5, T12, T20, T23, T36, T37, T40, T44 |
| RF-030 | T3, T10, T12, T14, T19, T22, T24, T25, T42 |
| RF-031 | T25, T35, T47, T49, T53 |
| RF-032 | T4, T8, T32, T33, T34, T46, T53 |
| RF-033 | T4, T8, T32, T33, T34, T38, T46, T52 |
| RF-034 | T2, T11, T16, T17, T20, T21, T32, T36, T43, T44 |

RF sin cubrir: **ninguno** en la planificación; esto no afirma cobertura ejecutada. RNF-001–RNF-006 se verifican transversalmente mediante historial, atomicidad, lecturas en lote, pruebas, avisos y documentación de los gates A–D. Las confirmaciones C1–C5 ya están aprobadas; cualquier decisión nueva descubierta se consulta, no se implementa tácitamente.
