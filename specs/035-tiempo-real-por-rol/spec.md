# Spec 035 — Tiempo real privado según permisos de lectura

Estado: aprobada

Aprobada por el usuario: 2026-11-13 («Apruebo la spec.»).

## Contexto y objetivo

F8 del informe de funciones adicionales aborda el riesgo R32f: pertenecer a una organización permite recibir sus eventos en tiempo real aunque la recepción no compruebe la autorización de lectura de cada evento. La revalidación periódica de la conexión no sustituye ese control. Las specs 008, 009 y 010 mantuvieron ese riesgo fuera de su alcance; esta spec propone tratarlo de forma independiente.

El objetivo es que cada miembro reciba únicamente eventos privados cuya información podría consultar por HTTP en la misma organización y con su autorización vigente. La existencia del cambio, sus identificadores y su contenido también son información protegida. No basta con ocultarlos en la interfaz después de recibirlos.

La autorización combina los permisos efectivos de los roles con las condiciones del recurso y la asignación como oficial de partido cuando la lectura de referencia la exija. No todas las lecturas actuales exigen un permiso específico: algunas admiten a cualquier miembro activo con rol. F8 no debe confundir permisos de escritura con permisos de lectura ni introducir delegación de roles por torneo.

Esta funcionalidad es un requisito previo de F1, conforme a la hoja de ruta F8 → F1 → F13 y al apartado 6.3 del informe. La emisión de borradores de goles, tarjetas, sustituciones e incidencias no se habilita aquí. Su contenido y sus responsables lectores deberán definirse y aprobarse en F1 antes de emitirlos. Tampoco se incorpora al canal la gestión de sanciones F9, que mantiene sus avisos privados independientes.

El usuario cerró DA-1 a DA-4 y aprobó expresamente la spec completa el 2026-11-13. Sus decisiones están incorporadas a los requisitos. Se autoriza la fase Plan; su aprobación será necesaria antes de avanzar a tareas e implementación.

## Usuarios

- Miembro de una organización que consulta el Workspace con permisos de lectura limitados.
- Operador o administrador que necesita actualizaciones de los recursos que puede consultar.
- Oficial asignado a uno o varios partidos, con acceso condicionado por sus permisos y asignaciones.
- Responsable que concede o retira permisos, membresías o asignaciones.
- Visitante que consulta la información pública del torneo.
- Administrador de plataforma, cuyo acceso excepcional no equivale a membresía organizativa.

## Roles y visibilidad

- **Público:** conserva exactamente los eventos y datos públicos actuales. No recibe eventos privados, ni siquiera identificadores de cambios privados.
- **Miembro:** solo recibe información de una organización a la que pertenece activamente y dentro de su lectura autorizada. Tener una conexión abierta o conocer un identificador no concede acceso.
- **Operador, administrador y owner:** se aplica su autorización efectiva de lectura; el nombre del rol por sí solo no crea una excepción nueva ni elimina restricciones del recurso.
- **Oficial:** se respeta la combinación de permiso y asignación requerida por la consulta correspondiente. La asignación no sustituye un permiso exigido y un permiso no elimina una condición de asignación exigida.
- **Administrador de plataforma:** esta spec no le concede suscripciones privadas organizativas ni amplía las autorizaciones excepcionales vigentes. Si también es miembro, se evalúa ese acceso como miembro, sin sumar privilegios de plataforma.
- **Aislamiento:** una autorización de una organización no habilita recepción de datos de otra. Se evalúa cada conexión y organización por separado, también para una misma persona con varias membresías.

## Historias de usuario

- **HU-1.** Como miembro con permisos limitados, quiero recibir solo los cambios que puedo consultar para no acceder indirectamente a información restringida.
- **HU-2.** Como oficial, quiero recibir los cambios de los partidos comprendidos en mi autorización para operar sin conocer cambios de otros partidos restringidos.
- **HU-3.** Como responsable de permisos, quiero que su retirada deje de autorizar nuevas entregas privadas para que una conexión ya abierta no conserve privilegios antiguos.
- **HU-4.** Como visitante, quiero conservar las actualizaciones públicas sin que una función privada amplíe lo que se publica.
- **HU-5.** Como responsable de futuras funciones en vivo, quiero una regla comprobable de autorización antes de incorporar borradores privados, sin considerar la pertenencia a la organización una autorización suficiente para cualquier borrador.

## Definiciones

- **Evento privado:** aviso de un cambio reservado al ámbito privado, incluida su existencia, clase, identificadores y datos. Puede ser privado aunque comparta nombre con un evento público.
- **Lectura de referencia:** consulta HTTP autorizada que permite al destinatario conocer la información concreta del evento. No equivale a poder editar, cerrar, aprobar o gestionar el recurso. Si varias consultas son legítimas, se consideran sus campos y condiciones, no solo sus nombres.
- **Autorización efectiva de lectura:** sesión y usuario válidos, membresía activa con rol en la organización del recurso, permisos acumulados y condiciones de acceso al recurso que correspondan a la lectura de referencia. Incluye asignaciones de oficiales cuando sean condición de esa lectura.
- **Recurso:** entidad o conjunto de entidades afectadas por un cambio, pertenecientes a una única organización; por ejemplo, un partido o su acta. Un torneo puede identificar un recurso sin constituir un nuevo ámbito de roles.
- **Invalidación mínima:** aviso para volver a consultar un recurso por HTTP, sin su contenido de negocio. Sus identificadores y el hecho de que haya cambiado siguen sujetos a autorización.
- **Evaluación de entrega:** decisión de autorizar un evento para un destinatario concreto. Si se inicia a partir de la confirmación de una retirada de autorización, aplica la autorización restante tras esa retirada. No se confunde con la creación del evento ni con la apertura de la conexión; no exige retirar lo ya enviado ni descartar eventos ya aprobados en tránsito.
- **Recepción no autorizada:** llegada de información privada al cliente que carece de autorización para esa información, aunque la interfaz la ignore o una consulta posterior sea rechazada.

## Requisitos funcionales

- **RF-001.** EL SISTEMA limitará cada entrega privada a destinatarios con autorización efectiva para su lectura HTTP de referencia y el recurso concreto, dentro de la organización propietaria del recurso.
  - La comprobación incluye la existencia del cambio, sus identificadores y todos los campos entregados.
  - Un destinatario sin autorización no recibirá el evento para después descartarlo en su interfaz.

- **RF-002.** SI el destinatario no pertenece activamente a la organización del recurso, ENTONCES EL SISTEMA impedirá la entrega privada, aunque pertenezca a otra organización, posea un rol homónimo o conozca los identificadores.

- **RF-003.** CUANDO un miembro posea varios roles, EL SISTEMA evaluará sus permisos efectivos con las mismas reglas que la lectura de referencia, sin elegir un único rol por nombre, prioridad visual u orden de llegada.

- **RF-004.** CUANDO la lectura de referencia condicione el acceso a un permiso y a una asignación de oficial de partido, EL SISTEMA exigirá ambas condiciones para entregar su evento privado y limitará esa autorización al partido correspondiente.
  - La exención de asignación que ya reconozca esa lectura para determinados actores se conserva; esta spec no crea otras.
  - El permiso y la asignación de `match_officials` se exigen solo cuando la lectura HTTP los exige; F8 no crea roles por torneo (F7) ni endurece la lectura HTTP.

- **RF-005.** CUANDO la lectura de referencia permita consultar un recurso sin un permiso adicional al acceso organizativo válido, EL SISTEMA conservará esa regla para el evento correspondiente y el recurso concreto, sin exigir un permiso de escritura ni crear un permiso de lectura nuevo de manera implícita.

- **RF-006.** CUANDO se solicite acceso privado al tiempo real, EL SISTEMA verificará la identidad, la vigencia de la sesión y la pertenencia activa a la organización solicitada, sin aceptar como autorización los roles, permisos o asignaciones declarados por el cliente.

- **RF-007.** CUANDO se confirme el cierre o la revocación de una sesión, o la desactivación de su usuario o membresía, EL SISTEMA denegará los eventos privados afectados cuya evaluación de entrega se inicie a partir de ese momento; si la sesión vence, denegará las evaluaciones iniciadas desde su vencimiento.

- **RF-008.** CUANDO se confirme la retirada de un permiso, el cambio o la retirada de un rol, o el cambio o la retirada de una asignación de oficial, EL SISTEMA aplicará la autorización efectiva restante a toda evaluación de entrega iniciada a partir de ese momento y denegará los eventos que ya no estén autorizados, sin conservar como derecho de lectura la autorización obtenida al abrir la conexión.

- **RF-009.** CUANDO se conceda o recupere una autorización de lectura, EL SISTEMA permitirá las siguientes actualizaciones comprendidas en ella tras verificarla de nuevo, sin entregar un historial privado basado en permisos antiguos.

- **RF-010.** CUANDO cambie la organización activa o la identidad de una conexión privada, EL SISTEMA impedirá que sus entregas y actualizaciones pendientes se apliquen al nuevo contexto, sin combinar permisos ni datos entre organizaciones.

- **RF-011.** CUANDO un evento pendiente llegue a su evaluación de entrega, EL SISTEMA aplicará la autorización del destinatario vigente al inicio de esa evaluación, incluidas las retiradas confirmadas hasta ese momento, y no la que tenía cuando se produjo el cambio o se creó el evento.
  - No se promete retirar lo ya enviado ni descartar eventos ya aprobados en tránsito antes de confirmarse la retirada. La comprobación periódica no permite una ventana de entregas con autorización antigua para evaluaciones posteriores al corte.

- **RF-012.** SI un evento privado no tiene una clasificación de lectura conocida, carece de un recurso u organización verificables, o sus referencias son incompatibles entre sí, ENTONCES EL SISTEMA impedirá su entrega privada por defecto.
  - Incorporar un evento futuro exigirá definir su lectura, campos y destinatarios autorizados; no se hereda acceso por compartir un nombre con otro evento.

- **RF-013.** CUANDO se entregue un evento privado actual, EL SISTEMA lo limitará a una invalidación mínima con identificador de entrega e identificadores autorizados estrictamente necesarios del recurso, sin contenido de negocio; si no puede definir una invalidación enteramente autorizada, no entregará el evento.
  - Esta representación no cambia los eventos públicos ni decide el contrato de los futuros borradores privados de F1.

- **RF-014.** SI no puede comprobarse la autorización vigente de una entrega privada, ENTONCES EL SISTEMA suspenderá la entrega de los eventos privados afectados, sin tiempo de gracia, sin usar la última autorización conocida como permiso y sin desconexión masiva ni alteración de los eventos públicos.

- **RF-015.** CUANDO un destinatario reciba una invalidación privada autorizada, EL SISTEMA recuperará el detalle por HTTP, conservará esa consulta como fuente de verdad y volverá a aplicar su autorización al recuperar los datos, sin tratar el evento como credencial ni como permiso para escribir.

- **RF-016.** MIENTRAS se filtren las entregas privadas, EL SISTEMA conservará los nombres, campos, destinatarios y semántica de los eventos públicos existentes, sin añadir eventos ni campos públicos, ni convertir una actualización privada en pública porque comparta nombre con una pública.

- **RF-017.** CUANDO se recupere una conexión o la posibilidad de comprobar la autorización tras una suspensión, o se requiera resincronización, EL SISTEMA reautorizará al destinatario y reconstruirá mediante resincronización por HTTP únicamente el estado autorizado del contexto vigente, sin reproducir los eventos privados perdidos ni un historial privado, y sin revelar identificadores de recursos restringidos en los avisos de control.

- **RF-018.** CUANDO lleguen entregas duplicadas o se reintente una conexión, EL SISTEMA mantendrá la deduplicación y la recuperación existentes, sin conexiones o suscripciones duplicadas ni recargas adicionales atribuibles al filtrado para un mismo cambio lógico.

- **RF-019.** MIENTRAS F1 no tenga aprobadas la lectura y la visibilidad de sus borradores privados, EL SISTEMA no habilitará su difusión por el solo hecho de disponer del filtro F8; la aceptación de F8 será un requisito previo, no una autorización de publicación de borradores.

- **RF-020.** MIENTRAS se aplique F8, EL SISTEMA mantendrá los expedientes, evidencias y avisos de sanciones F9 fuera del canal de eventos en tiempo real, sin ampliar sus destinatarios ni sus permisos por esta funcionalidad.

## Requisitos no funcionales

- **RNF-001. Seguridad por defecto:** la autorización de recepción se garantiza antes de exponer el evento al cliente, no mediante filtros visuales. El aislamiento de datos conserva las garantías vigentes de la base de datos y no amplía actores ni lecturas.
- **RNF-002. Paridad comprobable:** cada clase de evento privado tendrá una correspondencia documentada con su lectura de referencia, sus campos, condiciones de recurso y destinatarios. La validación cubrirá autorizado y denegado, varios roles, distintas organizaciones y asignaciones de oficiales.
- **RNF-003. Revocación comprobable:** la validación fijará el orden entre retirada de autorización y evaluación de entrega, incluidos eventos pendientes y varias conexiones de la misma persona, conforme a DA-2 y DA-4. No se declarará revocación inmediata a partir de una comprobación periódica.
- **RNF-004. Compatibilidad:** no se cambian los contratos públicos, la entrega de mejor esfuerzo ni los estados accesibles de conexión y reintento existentes. La recuperación no requiere recargar el documento ni garantiza entrega duradera o exactamente una vez.
- **RNF-005. Operación distribuida:** las mismas restricciones se cumplirán en todas las conexiones y procesos que atiendan a un usuario; reconectar o recibir un evento desde otro proceso no permitirá eludirlas.
- **RNF-006. Observabilidad privada:** las incidencias de autorización y recuperación serán diagnosticables sin registrar contenido de eventos privados, credenciales, evidencia ni identificadores personales innecesarios. Esta spec no crea un historial de recepción ni una auditoría de negocio nueva.
- **RNF-007. Accesibilidad e idioma:** si el filtrado exige mensajes visibles nuevos, estarán disponibles en español e inglés y serán accesibles por teclado y tecnologías de asistencia, sin depender solo del color. No se anuncian recursos a los que se haya denegado acceso.

## Datos personales y privacidad

- Se evalúan identidad, sesión, membresía, permisos y asignaciones para decidir destinatarios; no se difunden a otros clientes como parte del evento.
- Los identificadores de un partido, acta o versión y la fecha o existencia de un cambio privado también quedan protegidos. Una invalidación no autoriza por sí misma a conocerlos.
- La decisión DA-3 limita los eventos privados actuales a invalidaciones mínimas sin contenido de negocio. Las lecturas HTTP conservan sus restricciones, incluidas las de datos personales y evidencia.
- No se añade documento de identidad, fecha de nacimiento, edad ni datos de sanciones al contenido público. Las imágenes mantienen las condiciones vigentes de consentimiento.
- Las señales públicas existentes siguen siendo públicas, incluso si las recibe una persona que no tiene acceso privado. Eso no convierte una variante privada del mismo nombre en pública.
- Lo recibido lícitamente antes de una revocación no puede retirarse del dispositivo; el requisito se refiere a nuevas entregas y a no mantener ni restaurar datos privados en otro contexto de identidad u organización.
- No se abre acceso organizativo para administradores de plataforma ni se rediseñan los avisos internos o por correo.

## Casos límite

1. Miembro con conexión válida pero sin lectura del recurso: no recibe siquiera sus identificadores.
2. Dos miembros de la misma organización con permisos diferentes: cada uno recibe solo sus eventos autorizados; el contenido autorizado para uno no sirve de representación para el otro sin comprobación.
3. Mismo rol en organizaciones distintas y misma persona miembro de ambas: no se cruzan entregas ni se suman permisos entre organizaciones.
4. Varios roles, uno de ellos retirado: se aplica la autorización efectiva restante, no el rol que la interfaz muestra.
5. Oficial con permiso pero no asignado, asignado sin permiso requerido, asignado solo a otro partido y actor exento de asignación según la lectura: se reproducen los cuatro resultados de la consulta de referencia.
6. Lectura abierta a cualquier miembro activo con rol: no se exige por error permiso de cerrar o aprobar.
7. Retirada de permiso o asignación mientras existen eventos pendientes, con varias pestañas o procesos: se aplica el punto de corte de DA-2 a todas las evaluaciones afectadas.
8. Alta, expiración o revocación de sesión durante una reconexión: abrir una conexión nueva no restituye la autorización antigua.
9. Evento cuya organización y partido no coinciden, evento desconocido o recurso eliminado: no hay entrega privada por defecto.
10. Mismo nombre de evento para una actualización pública y una rectificación privada: se conserva la distinción de contenido y destinatarios.
11. Caída de la comprobación de autorización o fallo limitado a un destinatario: se aplica DA-4 sin convertir el fallo en autorización ni afectar sin necesidad a otros usuarios.
12. Reinicio del transporte, pérdida de eventos, duplicados o reconexión: recuperación por lecturas autorizadas, sin historial privado ni avisos de control que revelen recursos restringidos.
13. Cambio de organización mientras llega una respuesta o evento anterior: no modifica el estado del nuevo contexto.
14. Administrador de plataforma sin membresía y con una autorización excepcional ajena a F8: no accede al canal organizativo privado por esa autorización.
15. Futuro evento de borrador de partido sin lectura privada aprobada, o aviso F9: no se difunde por incorporarse F8.

## Fuera de alcance

- Implementar esta spec durante su redacción o clarificación, o decidir su arquitectura de distribución en estas fases.
- Crear roles por torneo, nuevos permisos o cambios en las lecturas HTTP y sus reglas de negocio; si resultan necesarios, requieren decisión y aprobación previas.
- Implementar F1, sincronizar borradores, publicar marcador o reloj nuevos, ni añadir la cronología pública F13.
- Ampliar la matriz pública, los destinatarios de F9 o las autorizaciones de plataforma.
- Hacer duradera la entrega, garantizar exactamente una vez, reproducir eventos históricos o añadir infraestructura de observabilidad ajena al filtrado.
- Rediseñar las pantallas, el login, las invitaciones, el cierre atómico de actas o la rectificación administrativa.

## Criterios de finalización

Los siguientes criterios corresponden a la futura implementación y validación; la aprobación de la spec no acredita su cumplimiento técnico:

1. Las decisiones DA-1 a DA-4 del 2026-11-13 están incorporadas a los RF; el usuario aprueba expresamente la spec completa y esta deja de estar en borrador antes de planificar su implementación. Cerrar las dudas no equivale a aprobar la spec.
2. Existe una matriz cerrada de eventos privados actuales, representaciones, lecturas de referencia y destinatarios; los eventos desconocidos no se entregan. Se distinguen las variantes privadas de nombres públicos y los avisos que no pertenecen al canal.
3. Se comprueba la recepción y la no recepción en el límite del cliente, no solo lo visible en pantalla, con dos organizaciones, miembros de varios roles y oficiales con y sin asignación y permiso.
4. Se verifican retirada y recuperación de permisos, asignaciones y sesiones, eventos pendientes, varias conexiones y procesos, con el corte temporal y la política de error aprobados.
5. Los eventos públicos y sus campos no cambian; las pruebas demuestran ausencia de contenido privado en receptores públicos o no autorizados y que F9 sigue fuera del canal.
6. Los consumidores autorizados conservan actualización, deduplicación, resincronización, recuperación y reintento, sin recargas duplicadas ni recarga del documento causada por el filtro.
7. La documentación vigente deja de presentar R32f como mitigado únicamente por la expulsión periódica y distingue la autorización de recepción de la validez de conexión.
8. Queda documentado que F1 depende de la aceptación de F8 y de su propia definición aprobada de borradores y responsables lectores; esta entrega no publica borradores.
9. Las verificaciones aplicables y sus límites se registran, y el usuario acepta explícitamente el resultado; redactar o aprobar la spec no equivale a tener F8 implementado.

## Dudas abiertas

No quedan dudas abiertas identificadas. Spec completa aprobada por el usuario el 2026-11-13; las decisiones de diseño se revisan en la fase Plan.

### Decisiones de clarificación cerradas

- **DA-1 — Cerrada el 2026-11-13 por el usuario: opción C.** Filtrar por la lectura HTTP de referencia y el recurso concreto, con permiso y asignación de `match_officials` solo cuando esa lectura los exija. No crear roles por torneo (F7) ni endurecer HTTP. Los responsables de los borradores de F1 se definirán en su propia spec, sin deducirlos de la lectura general actual de operación. RF-001, RF-004 y RF-005.
- **DA-2 — Cerrada el 2026-11-13 por el usuario: opción B.** Tras confirmarse la retirada de sesión, membresía, rol o asignación, no se entrega ningún evento afectado cuya evaluación se inicie a partir de ese momento con la autorización retirada. Se aplica la autorización efectiva restante. No se promete retirar lo ya enviado ni descartar eventos ya aprobados en tránsito; la revalidación periódica no permite conservar privilegios retirados para evaluaciones posteriores. RF-007, RF-008 y RF-011.
- **DA-3 — Cerrada el 2026-11-13 por el usuario: opción B.** Los eventos privados actuales son invalidaciones mínimas, con identificador de entrega e identificadores autorizados estrictamente necesarios del recurso, sin contenido de negocio. El detalle se recupera por HTTP. No cambia la representación pública ni decide el contrato futuro de F1. RF-013 y RF-015.
- **DA-4 — Cerrada el 2026-11-13 por el usuario: opción B.** Si no pueden comprobarse los permisos, suspender las entregas privadas afectadas; al recuperarse, reautorizar y reconstruir el estado por HTTP con resincronización. Sin tiempo de gracia, desconexión masiva ni reproducción del historial o los eventos privados perdidos. RF-014 y RF-017.
