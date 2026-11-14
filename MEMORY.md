# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas; detalle histórico en specs y git.

## Spec activa
- 036-partido-en-vivo, fase Implementación. Spec, plan y tareas aprobados por el usuario el 2026-11-13; DA-1–DA-7 y C1–C5 confirmadas. División oficial A1 → A2 → B1 → B2 → B3 → C1 → C2.
- #80/A1, #81/A2 y #82/B1 fusionados según el usuario. B2 prepara T37–T47 sin productores HTTP accesibles; T48 abierta por G-REMOTE. Rama nueva desde main a86c6f5c: devin/1794663227-partido-en-vivo-b2. Sin aceptación F1 ni despliegue.

## Pendiente
- B2: commit/push sin abrir PR; T48 requiere el PR del usuario, CI y Devin Review antes de cerrarse. No activar B3 ni fusionar desde esta ronda.
- Solo después de B2 fusionado: B3 T49–T60 → C1 T61–T72 → C2 T73–T84. Sin productores F1 antes de B3, sin aceptación antes de T84.

## Historial de fases 036
- 2026-11-13 · Spec, plan C1–C5 y 84 tareas en siete PRs aprobados expresamente; #79 fusionado. Las aprobaciones no equivalen a implementación ni aceptación F1.
- 2026-11-14 · A1 dominio/contratos inertes. Fix d58e65bc alinea estados del snapshot con CHECK real; T10 cerrada en cf14948e. PR #80: pull_request 43554669201/push 43554665420 success, Review sin pendientes; backend 3808 pass/4 skips demo. #80 fusionado según el usuario.
- 2026-11-14 · A2 migración 056 completa: cuatro tablas privadas RLS/FORCE, permisos aditivos, integridad, autorización invocadora y vistas sin consumidores. 61 casos nuevos; backend PostgreSQL 3869 pass/4 skips demo. Migrador limpio/incremental con dos tenants y 56 checksums estables. Funcional 8c9de99b, cierre T24 3e1de39f; PR #81 pull_request 43561739543/push 43561736578 success, Review sin hallazgos. #81 fusionado según el usuario.
- 2026-11-14 · Usuario autorizó «Opción 1: migración 057 mínima (recomendada)» dentro de B1: T33 era imposible con 056 para CLOSE sin VIEW/OPERATE. Desviación registrada en plan/tasks; 056 intacta.
- 2026-11-14 · B1 T25–T35: capacidades/snapshot, comandos transaccionales, reloj, hechos provisionales y recibos completos; sin router nuevo, productores, cambios HTTP/públicos/frontend. Backend PostgreSQL 3923 pass/4 skips demo (45 casos de servicios, 9 de 057), Ruff y Bandit correctos. Seguridad final del árbol stageado en reporte. Migrador limpio 001→057 e incremental 056 con dos tenants, reejecución y 57 checksums estables. T36 pendiente remoto.
- Rojos B1 conservados: pausa CLOSE-only, orden estable de corrección, huella devuelta y corrección/retirada en segmentos previos. Primer rojo agregado de servicios era acceso no concedido a organizations; no acredita rojo funcional separado de cada conducta. Dos suites intermedias interrumpidas no cuentan como completas.
- 2026-11-14 · T36 cerrada por autorización del usuario: PR #82, SHA b9a888ad980c013cbc89abd2c9a33c73738a4ace, CI 7/7; pull_request 43596664230 y push 43596659340 success (E2E push omitido). Devin Review success «Completed analysis in 1m 54s», sin hallazgos según confirmación del usuario; cinco hallazgos anteriores resueltos. Evidencia detallada en tasks.md; no declara fusión.
- 2026-11-14 · Cierre documental T36 5a40d6e7: pull_request 43598550413/push 43598545804 success, 7/7, nueva Review sin hallazgos. #82 fusionado según el usuario antes de iniciar B2.
- 2026-11-14 · B2 T37–T47: DTO con recibo, hechos íntegros del servidor y congelación en la transacción clásica; recibo actor/sesión/permisos/contenido/resultado actual, reloj solo no invalida. Catálogo privado 056 y outbox mínimo en comandos internos; público solo si cambia la proyección. Unión pública inerte de 14 claves suspendidas. Focalizado 285 passed (carreras reales, rollback tardío, aprobación 033 y paridad HTTP/SQL incluidos); rojos y límites en tasks.md. T48 pendiente remoto.
- B2 integral final: 4022 passed, 4 skipped in 1408.53s, PostgreSQL/Redis y Python 3.14 (59 casos nuevos; skips demo.owner). Ruff correcto; Bandit exit 0, 12 low, 0 medium/high; Gitleaks/árbol final en reporte de publicación. Corregidas regresiones del doble clásico y seed 043 sin alterar sus tests ni migraciones; detalle de rondas incompletas y verde de 264 casos en tasks.md.

## Decisiones y límites vigentes
- 2026-11-14 · Usuario aprobó Opción 1 del hallazgo 1/#82: 058 de elegibilidad mínima para OPERATE, sin ampliar lecturas F9 ni editar 042/056/057. SECURITY DEFINER necesario para calcular sin otorgar historial; tenant/permisos 056, search_path fijo y EXECUTE solo bracket_app. Captura usa IDs no elegibles; cierre/review siguen con load_effective_sanctions. Equivalencia, roles/tenant y migrador limpio/incremental/idempotente verificados localmente; evidencia y límites en plan/tasks. Fixes Review 2–5: f5646b15, 629de4e8, bc8c5111, e6e68784.
- VIEW_MATCH_LIVE_DRAFT y OPERATE_MATCH_LIVE independientes; dueño/administrador/operador con alcance organizativo, árbitro asignado y observador sin concesión por defecto. Recibos requieren VIEW+CLOSE; operar no hereda lectura ni devuelve borrador.
- Reloj basado en instante servidor UTC recibido por dominio puro, microsegundos, sin ticks persistidos. Reanudar conserva referencia detenida; corregir reloj no cambia minutos/content_revision de hechos. Revisiones optimistas, identidad idempotente y recibos actor/sesión/contenido.
- 057 permite solo pausa automática al interrumpir/completar un segmento activo ya autorizado con CLOSE. SECURITY INVOKER y RLS, sin BYPASSRLS/SECURITY DEFINER, sin permiso de lectura ni operación F1 general. Excepción de trigger exige diferencia exacta de reloj/revisión/metadatos; no utiliza flag GUC falsificable.
- Comandos/recibos validan sesión vigente al insertar y guardan UUID histórico sin FK a user_sessions: una FK restrictiva rompía la purga 034. No añadir retención nueva ni borrar historial.
- Borrador separado de match_events/resultados confirmados; ninguna clasificación/sanción/estadística/avance anticipado. Actas confirmadas solo se corrigen mediante 033. Público suspendido: exactamente 14 campos, sin eventos individuales.
- B2 no cambia main.py, frontend, ruta/vista pública, permisos HTTP ni migraciones 001–058. Close recibe session_id interno opcional; B3 debe pasar la sesión autenticada desde el router, nunca inferirla del recibo. live_review_id no se admite en revisión/033; sus DTO conservan extra=forbid. Wire privado sin versión, hechos, revisión ni reloj; F9 fuera del catálogo.
- F8/035 aceptada por el usuario el 2026-11-13, #78 fusionado, R32f cerrado: autorización privada fresca por destinatario, wire de tres IDs, recuperación HTTP sin replay. No habilita borradores F1 ni acredita producción. F9 permanece fuera de Redis/Socket.IO.
- 034 F9: administración global separada por autorización puntual; avisos mínimos con handlers explícitos y revalidación en entrega/lectura. No heredar VIEW desde escritura ni exponer evidencia en avisos. Detalles en spec/README/AGENTS.
- 029–032 implementadas/aceptadas: diseño/tokens, operación móvil, público y tema. Evidencias históricas en sus specs; no reinterpretar resultados históricos como checks actuales.

## Corrección independiente: planilla clásica
- useMatchLineup.syncTacticalEditor conserva roles de operation.lineup sin formación; snapshots/precarga 028 mantienen prioridad. Sin backend, migración ni permisos nuevos. Regresión de composable con 24 roles y E2E que exige persistencia tras guardar/recargar.

## Entorno y errores a evitar
- Backend Python 3.14 en contenedor bc-t1-python con repo /repo; host sin pytest adecuado. Frontend Node 24/pnpm 12.12.1 y E2E en contenedores. No introducir defaults/secretos nuevos.
- El arnés debe apuntar DATABASE_URL y DATABASE_ADMIN_URL a la misma base aislada. test_migrate_target.sh cambia contraseña del rol de pruebas: restaurar desde configuración existente antes de suites compartidas, nunca imprimir credenciales.
- organizations no es legible directamente por bracket_app: reutilizar fn_verify_user_org_membership. No eludir privilegios/RLS para verificar sesión o membresía.
- Gates y Review remotos se registran solo al existir evidencia del SHA correspondiente; no afirmar fusión, aceptación ni despliegue sin confirmación. Sin verificación visual: B2 es interno e inerte en HTTP.
