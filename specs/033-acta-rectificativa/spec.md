# Spec 033 — Acta rectificativa

Estado: borrador

Fecha: 2026-11-12. Desarrolla la §3.6 de la constitución 2.0.0 (PR #61). Corresponde a la funcionalidad F4 del informe de funciones adicionales. Las apelaciones y resoluciones de sanciones (F9) tienen su propia spec.

## Contexto y objetivo

Hoy un acta confirmada no tiene ninguna vía de corrección: el resultado y sus eventos son inmutables en la base de datos (spec 017, RF-011) y un error de carga queda en la clasificación, las estadísticas, las sanciones y el avance para siempre. La constitución 2.0.0 (§2.3 y §3.6) admite una única vía: el **acta rectificativa**, una versión nueva que se solicita, se aprueba por otra persona y se publica sin modificar ni eliminar el acta original.

**Objetivo:** que un error en un acta confirmada se pueda corregir de forma trazable, separando quién solicita de quién aprueba, sin borrar nada, recalculando lo que dependa del acta y sin tocar automáticamente los partidos posteriores que ya se disputaron.

### Estado verificado (2026-11-12)

| # | Hecho verificado | Evidencia |
|---|---|---|
| 1 | Un resultado confirmado no admite cambios de marcador, ganador, estado, resolución ni borrado, sin excepción para administradores. | Trigger de la migración 016 |
| 2 | Un acta confirmada no admite `INSERT`/`UPDATE` de eventos; los eventos y los cumplimientos de sanción ya tienen una marca de anulación (`is_voided`) sin vía operativa. | Migración 009; esquema `match_events`, `player_suspension_serves` |
| 3 | El cierre escribe en una transacción marcador, estado, contadores, suspensiones, clasificación, avance, auditoría y outbox, y emite `MATCH_CLOSED`, `MATCH_UPDATED` y `STANDINGS_UPDATED`. | Spec 017, RF-009 |
| 4 | La clasificación de una fase se recalcula completa desde sus partidos confirmados. | Servicio de clasificación |
| 5 | El avance dentro de una llave sigue enlaces de partido a partido (ganador o perdedor a local o visitante); el paso entre fases es manual. | `advancement_links`; README, «Autorización y avance manual entre fases» |
| 6 | La autorización se resuelve por roles de la organización (`owner`, `administrator`, `operator`, `referee`, `viewer`) y permisos; no hay roles por torneo. | Permisos y definiciones de rol |
| 7 | El administrador de plataforma vive fuera de las organizaciones, con su propia auditoría, y hoy no puede editar resultados. | Migración 001; AGENTS, «Límites del proyecto» |

## Usuarios

- **Organizador (dueño o administrador de la organización):** detecta el error y presenta la solicitud.
- **Aprobador:** otro miembro de la organización con permisos suficientes que acepta o rechaza la solicitud.
- **Administrador de plataforma autorizado:** aprobador excepcional cuando la organización no puede aprobar.
- **Operador, árbitro y observador:** consultan el acta vigente y su historial.
- **Público:** ve el resultado vigente.

## Roles y visibilidad

- **Público:** ve solo la versión vigente del resultado y de los datos que ya publica (marcador, clasificación, estadísticas). No ve solicitudes, motivos, evidencias, responsables ni versiones anteriores, salvo lo que decida DA-4.
- **Miembro sin permiso de solicitud o aprobación:** consulta el acta vigente, su historial de versiones y el estado de las solicitudes de su organización; no puede escribir.
- **Solicitante:** miembro con el permiso de solicitud (DA-1). Puede presentar una solicitud y retirarla mientras está pendiente.
- **Aprobador:** miembro con el permiso de aprobación (DA-1), distinto del solicitante. Puede aprobar o rechazar.
- **Administrador de plataforma:** solo con autorización expresa (DA-2) puede aprobar o rechazar una solicitud ya presentada. No puede presentarla, editar resultados ni crear rectificaciones.
- **Aislamiento:** una solicitud, versión o partido de otra organización responde **404** indistinguible de uno inexistente; ninguna organización ve ni modifica los de otra.

## Historias de usuario

- HU-1. Como organizador, quiero solicitar la corrección de un acta confirmada indicando qué cambia, por qué y con qué evidencia, sin poder aplicarla yo solo.
- HU-2. Como aprobador, quiero ver el acta vigente, la propuesta, las diferencias y sus efectos previstos antes de decidir, y que mi decisión quede registrada.
- HU-3. Como miembro, quiero consultar el historial de versiones de un acta y saber cuál rige.
- HU-4. Como responsable del torneo, quiero que al publicarse la rectificación la clasificación, las estadísticas, las sanciones y el avance reflejen la versión vigente.
- HU-5. Como responsable del torneo, quiero que una corrección que afecte a partidos posteriores ya disputados no los modifique sola, sino que abra un procedimiento que se resuelva de forma explícita.
- HU-6. Como dueño de la organización, quiero que, si no hay otro aprobador disponible, un administrador de plataforma autorizado pueda decidir, y que quede registrado.

## Definiciones

- **Acta original.** Acta confirmada por el cierre (spec 017). Nunca se edita ni se elimina.
- **Versión del acta.** El acta original es la versión 1; cada rectificación publicada es la versión siguiente y referencia a la que sustituye y al acta original.
- **Versión vigente.** La última versión publicada. Es la única que alimenta resultado, clasificación, estadísticas, sanciones y avance.
- **Solicitud de rectificación.** Propuesta de una versión nueva, con estado `pendiente`, `aprobada`, `rechazada`, `retirada` o `publicada`.
- **Contenido rectificable.** Lo que el cierre confirmó: resolución, marcadores, ganador, penales, motivo de la resolución y eventos (goles, autogoles, asistencias, tarjetas, sustituciones). Las alineaciones publicadas quedan pendientes de DA-3.
- **Efecto.** Cada cambio derivado de publicar una versión: filas de clasificación, sanciones creadas o anuladas, cumplimientos anulados, participantes de un partido posterior, eventos de outbox.
- **Impacto competitivo.** Efecto que alcanzaría a un partido posterior ya disputado o en juego, o a un equipo ya asignado a una fase posterior.

## Requisitos funcionales

### Solicitud

- **RF-001.** CUANDO un miembro con permiso de solicitud presente una solicitud sobre un acta confirmada de su organización, EL SISTEMA la registrará como `pendiente` con la versión vigente de referencia, el acta original, el contenido propuesto completo, el motivo, la evidencia, el solicitante y la fecha.
  - El motivo es obligatorio y no vacío; la evidencia es obligatoria cuando lo exija DA-5.
  - El contenido propuesto pasa por las mismas validaciones de dominio que el cierre (spec 017, RF-001 a RF-007) sobre la configuración de la versión de torneo del partido; un incumplimiento responde **409** con el mismo `code` que el cierre y no registra nada.
  - Una propuesta idéntica a la versión vigente responde **409** `RECTIFICATION_NO_CHANGES`.
- **RF-002.** SI ya existe una solicitud `pendiente` o `aprobada` sin publicar para ese partido, ENTONCES EL SISTEMA rechazará otra con **409** `RECTIFICATION_ALREADY_OPEN`.
- **RF-003.** SI el partido no está confirmado, ENTONCES EL SISTEMA rechazará la solicitud con **409**; un acta sin confirmar se corrige antes del cierre, no con esta vía.
- **RF-004.** CUANDO el solicitante retire su solicitud pendiente, EL SISTEMA la pasará a `retirada` con fecha y sin borrarla. Nadie más puede retirarla.

### Revisión y decisión

- **RF-005.** EL SISTEMA mostrará al aprobador la versión vigente, la propuesta, la diferencia campo a campo y evento a evento, y los efectos previstos calculados sobre el estado actual, incluido el impacto competitivo, sin escribir nada.
- **RF-006.** CUANDO un aprobador apruebe o rechace una solicitud pendiente, EL SISTEMA registrará el usuario responsable, la fecha, la decisión y el motivo de la decisión, obligatorio en ambos casos.
- **RF-007.** SI quien decide es el solicitante, ENTONCES EL SISTEMA responderá **403** `RECTIFICATION_SELF_APPROVAL`, sean cuales sean sus roles o permisos y también si actúa como administrador de plataforma.
- **RF-008.** SI quien decide no tiene permiso de aprobación en la organización del partido, ni es un administrador de plataforma con autorización vigente (DA-2), ENTONCES EL SISTEMA responderá **403**.
- **RF-009.** CUANDO un administrador de plataforma decida, EL SISTEMA lo registrará en la auditoría de plataforma y en el historial de la solicitud, con la autorización usada, y lo identificará como aprobación excepcional.
- **RF-010.** SI la versión vigente cambió entre la presentación y la decisión, ENTONCES EL SISTEMA rechazará la aprobación con **409** `RECTIFICATION_STALE` y la solicitud seguirá pendiente.
- **RF-011.** MIENTRAS una solicitud esté pendiente, o si es rechazada o retirada, EL SISTEMA mantendrá sin cambios la versión vigente y todo lo que deriva de ella.

### Publicación

- **RF-012.** CUANDO se publique una solicitud aprobada, EL SISTEMA creará en una sola transacción la versión nueva, la marcará como vigente y aplicará sus efectos; un fallo en cualquier paso deja todo como estaba. El momento de publicación lo fija DA-6.
- **RF-013.** EL SISTEMA conservará el acta original y todas las versiones anteriores, con sus eventos y resultados, consultables y sin modificar; ninguna fila anterior se edita ni se elimina, y el trigger que protege el resultado confirmado no se relaja.
- **RF-014.** CUANDO se publique una versión, EL SISTEMA recalculará la clasificación de la fase del partido y las estadísticas que dependan de él a partir de la versión vigente de cada partido.
- **RF-015.** CUANDO la versión publicada cambie el ganador o el perdedor de un partido con enlaces de avance, EL SISTEMA actualizará los participantes de cada partido destino que aún no haya comenzado y registrará cada cambio como efecto.
- **RF-016.** SI un efecto alcanza un partido posterior ya comenzado o confirmado, o un equipo ya asignado a una fase posterior, ENTONCES EL SISTEMA no modificará ese partido ni esa asignación, publicará la versión y abrirá un **procedimiento de impacto competitivo** (RF-017).
- **RF-017.** EL SISTEMA registrará cada procedimiento de impacto competitivo con el partido rectificado, los partidos o asignaciones afectados, el efecto que se habría aplicado y el estado `abierto`. Solo un aprobador puede cerrarlo con una decisión y un motivo registrados; la decisión no modifica actas confirmadas (las opciones las fija DA-7).
- **RF-018.** CUANDO la versión publicada cambie tarjetas o expulsiones, EL SISTEMA recalculará las sanciones de ese partido con las reglas de la versión de torneo: creará las nuevas, anulará con registro las que ya no correspondan y no editará ninguna; el tratamiento de una sanción ya cumplida lo fija DA-8.
- **RF-019.** CUANDO se publique una versión, EL SISTEMA registrará cada efecto y cada notificación emitida, y emitirá los eventos de tiempo real del partido y de la clasificación por la outbox, sin enviarlos en la propia petición.

### Consulta

- **RF-020.** EL SISTEMA ofrecerá a los miembros de la organización el historial de versiones de un acta, con número de versión, fecha, responsables, motivo, evidencia y diferencias, y la lista de solicitudes y procedimientos de impacto con su estado.
- **RF-021.** EL SISTEMA servirá en todas las lecturas públicas y del Workspace la versión vigente; ninguna lectura mezcla datos de versiones distintas de un mismo partido.

## Requisitos no funcionales

- **RNF-001.** Todas las tablas nuevas son de tenant, con RLS y políticas en la misma migración; el rol de aplicación no gana privilegios nuevos.
- **RNF-002.** Solicitud, decisión, publicación y cierre de procedimiento se auditan; la auditoría no incluye datos personales más allá de los identificadores ya auditados.
- **RNF-003.** Dos aprobaciones o publicaciones concurrentes sobre la misma solicitud producen exactamente una versión; la segunda responde **409**.
- **RNF-004.** Las respuestas siguen la forma de la spec 017: 409 con `detail` de cadena y `code` aditivo; 422 saneado.
- **RNF-005.** `engine_version` sigue en 2026.1 y el contrato de reglas no cambia: la rectificación reutiliza las validaciones del cierre.
- **RNF-006.** La interfaz está en español e inglés y cumple los criterios de accesibilidad vigentes.

## Datos personales y privacidad

- Datos involucrados: identificadores de jugadores en los eventos, nombres de solicitante y aprobadores, motivos y evidencias.
- Los ven solo los miembros de la organización; el administrador de plataforma, solo la solicitud que decide.
- El motivo y la evidencia no deben contener documentos de identidad ni fechas de nacimiento; si la evidencia es un archivo, sigue las reglas de almacenamiento existentes (DA-5).
- Nada de esto se publica, salvo lo que decida DA-4.

## Casos límite

- Rectificar una versión ya rectificada: la nueva referencia a la vigente y al acta original.
- Rectificación que cambia la resolución (por ejemplo, de `regular` a `penalties`) o la convierte en `walkover` o `administrative`: aplica la matriz de la spec 017 y los permisos de resolución administrativa.
- Partido de una fase con desempate por sorteo ya resuelto: si cambia el grupo empatado, el sorteo previo deja de aplicar y se registra como efecto.
- Rectificación que solo cambia una asistencia o un minuto: no cambia la clasificación, pero sí las estadísticas.
- Torneo archivado: DA-9.
- Aprobador que pierde el permiso o el rol entre la presentación y la decisión: se evalúa en el momento de decidir.
- El solicitante deja la organización: su solicitud pendiente sigue siendo decidible y él sigue sin poder aprobarla.
- Partido destino de avance ya con participantes asignados a mano: se trata como impacto competitivo, no se sobrescribe.

## Fuera de alcance

- Apelación, anulación o modificación de sanciones que no deriven de rectificar un acta (spec F9).
- Corrección de versiones de torneo publicadas (la §3.6 no la crea).
- Reabrir un acta confirmada o editarla en su sitio.
- Corregir un acta no confirmada por esta vía.
- Avance automático entre fases (R12) y partido en vivo (R11).
- Filtrado del tiempo real por rol (F8).
- Notificaciones por correo, salvo lo que decida DA-10.
- Traspasos entre equipos.

## Criterios de finalización

| # | Criterio | RF |
|---|---|---|
| 1 | Una solicitud válida queda pendiente con motivo, evidencia, solicitante, fecha y referencias; una inválida no registra nada. | RF-001 a RF-004 |
| 2 | El solicitante no puede decidir su propia solicitud con ningún rol, ni como administrador de plataforma. | RF-007 |
| 3 | Cada decisión registra responsable, fecha, decisión y motivo; la del administrador de plataforma queda en las dos auditorías. | RF-006, RF-009 |
| 4 | Con una solicitud pendiente, rechazada o retirada, la versión vigente y sus derivados no cambian. | RF-011 |
| 5 | La publicación crea la versión nueva y sus efectos en una transacción; el acta original y las anteriores siguen intactas y consultables. | RF-012, RF-013 |
| 6 | Clasificación, estadísticas, sanciones y avance pendiente reflejan la versión vigente. | RF-014, RF-015, RF-018, RF-021 |
| 7 | Ningún partido posterior ya comenzado o confirmado cambia; se abre un procedimiento de impacto con su decisión registrada. | RF-016, RF-017 |
| 8 | Efectos y notificaciones quedan registrados y el tiempo real se emite por la outbox. | RF-019 |
| 9 | Ninguna organización ve ni modifica solicitudes, versiones o procedimientos de otra. | Roles y visibilidad |

## Dudas abiertas

- [NECESITA ACLARACIÓN] **DA-1. Permisos.** ¿Quién puede solicitar y quién aprobar? Recomendación: dos permisos nuevos, `REQUEST_MATCH_REPORT_RECTIFICATION` y `APPROVE_MATCH_REPORT_RECTIFICATION`, asignados por defecto a `owner` y `administrator`, para que un torneo con dos administradores no dependa del dueño.
- [NECESITA ACLARACIÓN] **DA-2. Autorización expresa del administrador de plataforma.** ¿Quién la concede y cómo? Opciones: (a) el dueño de la organización la concede para una solicitud concreta; (b) basta un rol de plataforma específico con motivo registrado; (c) solo cuando la organización no tenga ningún otro aprobador. Recomendación: (a).
- [NECESITA ACLARACIÓN] **DA-3. Alineaciones.** ¿Son rectificables las alineaciones y formaciones publicadas o solo resultado y eventos? Recomendación: solo resultado y eventos en esta spec.
- [NECESITA ACLARACIÓN] **DA-4. Visibilidad pública.** ¿El público ve que un resultado fue rectificado? Opciones: (a) nada, solo la versión vigente; (b) una marca «resultado rectificado» con fecha, sin motivo ni responsables. Recomendación: (b).
- [NECESITA ACLARACIÓN] **DA-5. Evidencia.** ¿Texto o enlace, o también archivos adjuntos? ¿Cuándo es obligatoria? Recomendación: texto obligatorio siempre y archivos fuera de esta spec.
- [NECESITA ACLARACIÓN] **DA-6. Publicación.** ¿La aprobación publica en el mismo acto, o la publicación es un paso aparte? Recomendación: en el mismo acto, para no dejar versiones aprobadas sin vigencia.
- [NECESITA ACLARACIÓN] **DA-7. Procedimiento de impacto competitivo.** ¿Qué decisiones admite? Por ejemplo: mantener los partidos posteriores, ordenar repetir el partido (partido nuevo), o resolver administrativamente otro partido aún no confirmado. ¿Bloquea operar los partidos afectados mientras está abierto?
- [NECESITA ACLARACIÓN] **DA-8. Sanciones ya cumplidas.** Si la rectificación elimina una tarjeta cuya sanción ya se cumplió, ¿se anula la sanción y sus cumplimientos (con registro), o se conserva el cumplimiento como hecho consumado? Si añade una sanción, ¿cuenta desde el siguiente partido del jugador?
- [NECESITA ACLARACIÓN] **DA-9. Torneos archivados.** ¿Se pueden rectificar actas de un torneo archivado?
- [NECESITA ACLARACIÓN] **DA-10. Notificaciones.** ¿Basta con registrar las notificaciones y emitir el tiempo real, o hay que avisar por correo a solicitante, aprobadores o equipos?
