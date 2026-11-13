# Spec 036 — Partido en vivo

Estado: borrador

Fecha: 2026-11-13. Fase: Spec. Corresponde a F1 del informe de funciones adicionales. El usuario autorizó redactar esta spec tras aceptar F8; no ha aprobado las opciones de las dudas abiertas ni autorizado plan, tareas o implementación.

## Contexto y objetivo

La auditoría de octubre identificó en R11 un ciclo de partido incompleto: los estados `live` y `suspended` no tenían un recorrido operativo completo y los eventos se confirmaban únicamente al cerrar el acta. Las specs anteriores de operación mantuvieron los eventos incrementales fuera de su alcance. El seguimiento de noviembre distingue la validez de una conexión de la autorización para recibir información privada; F8, spec 035, ya está implementada y aceptada.

El objetivo es operar un encuentro mientras se disputa: iniciar el partido, suspenderlo y reanudarlo, registrar goles, tarjetas y sustituciones como borradores privados, y ofrecer al público únicamente estado, marcador provisional y reloj de segmento cuando el partido sea visible. El cierre seguirá consolidando el acta y sus efectos de forma atómica, como hasta ahora. Lo observado en vivo no constituye un resultado confirmado.

Fuentes y límites: constitución 2.0.0, apartado F1 y decisión 6.3 del informe de funciones adicionales, auditorías de octubre y noviembre, matriz pública 020 y sus ampliaciones vigentes, cierre 017, rectificación 033 y autorización privada 035. F8 es un prerrequisito, no una autorización genérica para emitir borradores. La cronología pública individual corresponde a F13, no a esta spec.

**Compatibilidad constitucional:** no se propone enmienda. El marcador en vivo debe identificarse como provisional y nunca permitir editar un resultado cerrado. Interpretar «eventos incrementales» como modificación de eventos confirmados contradiría la inmutabilidad y queda excluido: solo la rectificación 033 puede corregir un acta confirmada. La mención del informe a eventos confirmados y cronología pública tras el cierre no amplía aquí la proyección pública vigente. Mostrar un partido suspendido sí ampliaría la matriz 020, que hoy lo excluye; DA-2 exige decidirlo expresamente, sin ampliar datos personales.

## Usuarios

- Organizador de la competición: necesita conocer el estado operativo y asegurar un cierre coherente.
- Operador y árbitro u otro oficial asignado: registran y revisan lo sucedido según su autorización sobre ese partido.
- Lector privado autorizado: sigue el borrador sin que ello le conceda escritura.
- Público: sigue estado, marcador y reloj sin acceder al borrador ni necesitar sesión.
- Administrador de plataforma: mantiene sus atribuciones actuales; esta funcionalidad no le concede operación ni lectura privada adicionales.

## Roles y visibilidad

- **Público:** solo consulta partidos de torneos visibles públicamente. La proyección adicional se limita al estado del partido, marcador provisional, segmento y reloj, con su condición de provisional o desactualizado. No recibe eventos individuales, identidades de sus protagonistas ni incidencias privadas.
- **Miembro de organización:** pertenecer a la organización, conocer el partido o poder leer la operación actual no concede por sí solo acceso nuevo al borrador. La política exacta de lectores y operadores se decide en DA-1.
- **Operador/oficial:** las nuevas acciones requieren autorización vigente sobre el partido. La vía de oficial conserva las condiciones de permiso y asignación que se aprueben en DA-1; una asignación no constituye una excepción general. No se introducen roles por torneo ni privilegios de plataforma implícitos.
- **Aislamiento:** toda lectura o acción privada de los requisitos siguientes queda limitada a la organización propietaria y al partido autorizado. Ninguna otra organización puede leer o modificar ese borrador. Cada consulta pública conserva el contexto del torneo solicitado, sin mezclar organizaciones.
- **Lecturas existentes:** esta spec no da por aprobado endurecer ni ampliar permisos de lecturas existentes; los nuevos datos privados necesitan su propia lectura autorizada equivalente antes de ser distribuidos.

## Historias de usuario

- HU-1. Como responsable autorizado, quiero iniciar, suspender y reanudar el encuentro para que su estado refleje lo que sucede sin cerrar prematuramente el acta.
- HU-2. Como operador autorizado, quiero registrar y corregir el borrador de goles, tarjetas y sustituciones para revisar el acta antes de confirmarla.
- HU-3. Como lector autorizado, quiero seguir el borrador de mi partido sin recibir cambios de partidos u organizaciones ajenos a mi acceso.
- HU-4. Como espectador, quiero ver marcador y reloj provisionales, y saber cuándo dejaron de estar actualizados, sin conocer datos privados.
- HU-5. Como responsable del cierre, quiero consolidar una única acta válida, sin duplicar hechos ni confirmar parcialmente sus efectos.
- HU-6. Como usuario que vuelve a conectarse, quiero recuperar el estado vigente autorizado, no reconstruirlo a partir de avisos perdidos.

## Definiciones

- **`scheduled`:** encuentro programado, aún no iniciado mediante el nuevo flujo en vivo. Conserva las vías de cierre ya admitidas, sin obligar a usar F1.
- **`live`:** partido iniciado y no cerrado, en el que se opera el borrador y el reloj según la autorización correspondiente.
- **`suspended`:** interrupción del encuentro sin confirmación del acta. No admite cierre mientras siga suspendido, como en 017; se reanuda antes de utilizar el cierre existente. Conservación del borrador, operaciones admitidas, reanudación y visibilidad se concretan en DA-2.
- **Borrador privado:** conjunto provisional de hechos deportivos de un partido, todavía corregible y no confirmado. No es una nueva versión del acta ni un historial público.
- **Marcador provisional:** resultado mostrado durante la operación en vivo, coherente con el borrador aceptado y las reglas vigentes; no alimenta por sí solo efectos de un acta cerrada.
- **Reloj de segmento:** referencia temporal del segmento que se está disputando, con modalidad, pausa y corrección pendientes de DA-3; no sustituye el minuto atribuido a cada hecho ni altera las reglas de duración.
- **Consolidación:** confirmación del conjunto válido de eventos junto al resultado y los efectos actuales del cierre, en una sola operación indivisible. La revisión del conjunto que se confirma se decide en DA-4.
- **Aviso privado:** invalidación mínima de 035 para consultar el estado por HTTP autorizado; no transporta el detalle del borrador ni acredita permiso por sí mismo.

## Requisitos funcionales

- **RF-001:** CUANDO un responsable autorizado inicie un partido programado de su organización con versión de torneo publicada y participantes válidos, EL SISTEMA lo pasará a `live` y permitirá identificar su segmento actual sin confirmar el acta.
- **RF-002:** CUANDO se solicite suspender o reanudar un partido de la organización activa, EL SISTEMA validará la autorización y la transición, conservará el borrador aceptado y aplicará la política aprobada en DA-2; suspender no equivaldrá a cerrar ni creará un resultado confirmado.
- **RF-003:** SI una transición es inválida, el partido es terminal o su versión no permite operar, ENTONCES EL SISTEMA rechazará la nueva operación en vivo sin modificar estado, reloj, borrador ni efectos deportivos existentes.
- **RF-004:** MIENTRAS un partido admita captura en vivo según su estado, EL SISTEMA permitirá al operador autorizado registrar los tipos del catálogo cerrado de su acta, incluidos goles, autogoles, tarjetas y sustituciones, manteniéndolos privados y provisionales.
- **RF-005:** CUANDO se acepte un hecho del borrador, EL SISTEMA conservará su equipo, protagonistas y relaciones deportivas aplicables, segmento y tiempo, y actualizará de forma coherente el marcador provisional cuando corresponda; el hecho seguirá perteneciendo solo al partido y organización autorizados.
- **RF-006:** CUANDO un operador autorizado corrija o retire un hecho todavía provisional, EL SISTEMA reflejará la corrección en el borrador y marcador según DA-2/DA-4, sin editar ningún acta confirmada ni perder cambios ajenos por sobrescritura silenciosa.
- **RF-007:** SI un evento es desconocido, incompleto o inválido para participantes, segmento, tiempo o reglas del torneo, ENTONCES EL SISTEMA lo rechazará con una explicación para el operador autorizado, sin incorporarlo al borrador ni cambiar marcador, reloj o efectos de cierre.
- **RF-008:** EL SISTEMA mantendrá separados el borrador y los resultados confirmados: registrar o corregir un hecho provisional no adelantará la clasificación, las estadísticas, las sanciones ni el avance que correspondan al cierre del acta.
- **RF-009:** CUANDO se consulte o actualice un partido visible públicamente, EL SISTEMA mostrará solo el estado, marcador y reloj/segmento autorizados, además de la proyección pública ya vigente, distinguiendo el resultado provisional del confirmado y sin publicar eventos individuales del borrador.
- **RF-010:** SI el torneo o el partido no cumplen la visibilidad pública vigente y la decisión expresa de DA-2, ENTONCES EL SISTEMA no entregará su estado, marcador ni reloj públicos y no revelará más de lo que revelaría ante un recurso inexistente.
- **RF-011:** MIENTRAS se muestre un reloj público o privado, EL SISTEMA identificará el segmento y si la referencia está en curso, pausada o desactualizada conforme a DA-2/DA-3, sin presentar tiempo no verificado como tiempo oficial actualizado ni permitir que un espectador controle el reloj.
- **RF-012:** CUANDO un destinatario consulte el borrador o se evalúe una entrega privada, EL SISTEMA comprobará la autorización vigente de su sesión, usuario, membresía, permisos y asignaciones aplicables para la lectura HTTP equivalente del partido concreto, conforme a DA-1 y a 035.
- **RF-013:** EL SISTEMA exigirá que cada nuevo aviso de F1 esté incluido expresamente en el catálogo cerrado, con su carácter público o privado, lectura HTTP equivalente y recurso autorizado definidos y aprobados antes de habilitarlo; ni F8 ni compartir nombre con un evento público concederán visibilidad pública o acceso al borrador.
- **RF-014:** CUANDO comunique cambios privados del borrador, EL SISTEMA mantendrá las invalidaciones mínimas de 035 y reservará el detalle para su consulta autorizada; nunca difundirá el borrador a todos los miembros por el mero hecho de pertenecer a la organización.
- **RF-015:** SI se retira una autorización o no se puede verificar al destinatario, ENTONCES EL SISTEMA impedirá las entregas privadas afectadas conforme al corte y suspensión fail-closed de 035, sin usar permisos antiguos, convertirlas en públicas ni prometer retirar información ya aprobada o enviada antes del corte.
- **RF-016:** CUANDO cambie la identidad u organización activa o se deniegue una lectura vigente, EL SISTEMA limpiará la vista privada que haya dejado de estar autorizada e impedirá que respuestas o actualizaciones anteriores restauren ese contexto o sus borradores.
- **RF-017:** CUANDO se pierda la conexión, EL SISTEMA distinguirá la información mostrada de una actualización verificada, no simulará la aceptación de nuevas escrituras y advertirá de que marcador, borrador o reloj pueden estar desactualizados.
- **RF-018:** CUANDO se restablezca la conexión o se solicite la resincronización de 035, EL SISTEMA recuperará mediante HTTP el estado actual permitido para el contexto vigente, sin reproducir avisos privados perdidos ni incluir datos de negocio en la señal de resincronización.
- **RF-019:** CUANDO se solicite el cierre de un acta con borrador en vivo, EL SISTEMA revalidará autorización, estado, reglas deportivas y el conjunto vigente que deba confirmarse según DA-4, consolidándolo atómicamente con resultado, contadores y efectos actuales del cierre, sin duplicar eventos.
- **RF-020:** SI falla la validación o consolidación del cierre, ENTONCES EL SISTEMA no confirmará parcialmente eventos, resultado, clasificación, sanciones ni avance, y conservará el borrador previamente aceptado como privado y no confirmado para su revisión autorizada.
- **RF-021:** CUANDO el cierre confirme el acta, EL SISTEMA terminará la operación provisional y servirá el resultado y acta vigentes conforme a las lecturas existentes; ninguna escritura en vivo pendiente podrá modificar lo confirmado ni ejecutar dos veces sus efectos.
- **RF-022:** SI se intenta corregir un acta confirmada desde la operación en vivo, ENTONCES EL SISTEMA rechazará el cambio y conservará la rectificación 033 como única vía de corrección, con original e historial inmutables y sin reapertura implícita.
- **RF-023:** SI una modificación o cierre se basa en un estado que otro operador ya cambió, ENTONCES EL SISTEMA evitará sobrescribir silenciosamente el trabajo aceptado, informará del conflicto al actor autorizado y exigirá revisar el estado vigente antes de confirmarlo.
- **RF-024:** SI el borrador está vacío, ENTONCES EL SISTEMA lo mostrará como tal, sin inventar incidencias, y mantendrá el cierre sin eventos cuando las reglas y la resolución existentes lo permitan; no obligará a capturar eventos ficticios ni a utilizar el flujo en vivo.
- **RF-025:** CUANDO un partido llegue a un estado terminal por una vía ya admitida, EL SISTEMA bloqueará nuevas operaciones provisionales; la mera salida del flujo en vivo no convertirá por sí sola un borrador pendiente en eventos confirmados ni creará una vía nueva de cancelación o abandono.
- **RF-026:** CUANDO acepte una transición, control del reloj o cambio de borrador, EL SISTEMA permitirá atribuir el acto a su responsable y momento dentro de la organización, sin publicar esa trazabilidad ni volcar el contenido privado en registros técnicos.
- **RF-027:** EL SISTEMA conservará los avisos y expedientes F9 fuera del canal de tiempo real del partido, y mantendrá la cronología pública F13 fuera de esta funcionalidad, incluso después del cierre.

## Requisitos no funcionales

- **RNF-001:** EL SISTEMA garantizará que conocer identificadores, acumular roles o mantener conexiones previas no permita leer ni modificar borradores de otra organización; las comprobaciones incluirán al menos dos organizaciones y oficiales asignados/no asignados según DA-1.
- **RNF-002:** EL SISTEMA preservará los nombres, contenido y semántica de los eventos públicos existentes; cualquier proyección adicional de F1 se limitará a lo aprobado aquí y no reutilizará una variante privada como pública por coincidencia de nombre.
- **RNF-003:** EL SISTEMA conservará las reglas configuradas de segmentos, tiempos, participantes, sustituciones y cierre; el reloj no impondrá duraciones deportivas nuevas ni relajará las validaciones actuales.
- **RNF-004:** EL SISTEMA permitirá verificar persistencia y recuperación del estado aceptado tras desconexión o reinicio, coherencia entre dos lectores autorizados y ausencia de duplicados ante reintentos, sin prometer entrega de todos los avisos ni un plazo de entrega no acordado.
- **RNF-005:** EL SISTEMA presentará controles, errores, estado provisional, suspensión y pérdida de actualización en español e inglés, utilizables con teclado y con señales que no dependan solo del color ni del movimiento del reloj.
- **RNF-006:** EL SISTEMA conservará la operación y el cierre de partidos que no utilicen F1 y las consultas públicas anónimas sin añadirles escrituras ni dependencia de sesión.

## Datos personales y privacidad

El borrador relaciona jugadores con hechos deportivos y puede revelar participaciones, tarjetas, sustituciones y asistencias. Solo los lectores autorizados de la organización podrán consultar ese detalle. No se publicarán los protagonistas de un hecho provisional por el simple cambio de marcador.

Se mantienen las exclusiones de la matriz pública: documentos de identidad, fecha de nacimiento, edad y su referencia, claves internas y direcciones privadas de almacenamiento, motivos administrativos o de walkover, sanciones y suspensiones de jugadores, plantilla inscrita, asistencias, auditoría y datos de miembros u organizaciones. La **suspensión del encuentro** no equivale a una suspensión disciplinaria de un jugador ni habilita su publicación.

Las fotos ya públicas siguen sujetas a consentimiento vigente y la formación táctica a publicación explícita. F1 no añade fotos, texto libre público ni acceso a expedientes disciplinarios. Los registros técnicos y evidencias de verificación no incluirán detalle personal del borrador, credenciales ni contenido privado de eventos.

## Casos límite

1. Iniciar sin participantes válidos, en versión no publicada o con autorización insuficiente: rechazo sin transición ni efectos parciales.
2. Repetir una acción, recibir avisos duplicados o perder la respuesta: el estado aceptado se recupera sin duplicar hechos ni confirmar dos veces un cierre.
3. Borrador vacío y marcador cero: sin eventos ficticios; siguen aplicándose las reglas de cierre y resolución existentes.
4. Suspender entre segmentos, corregir el reloj o reanudar: se conserva lo aceptado; la política exacta se cierra con DA-2/DA-3 antes de aprobar la spec.
5. Datos inválidos, tipos desconocidos, jugadores de otro equipo/organización o tiempos incompatibles: rechazo sin cambios ni revelación de información ajena.
6. Dos operadores cambian el mismo partido, o uno cierra mientras otro edita: conflicto explícito, sin pérdida silenciosa ni modificación de lo confirmado.
7. Revocar un permiso/asignación, expirar una sesión o fallar su comprobación durante el partido: no hay nuevas entregas privadas no verificadas; volver a tener permiso exige revalidación y lectura actual, no replay.
8. Cambiar identidad u organización con lecturas pendientes: las respuestas antiguas no recuperan contenido del contexto anterior.
9. Desconectarse antes de suspender/cerrar, y volver después: lectura vigente autorizada, no continuación de un reloj o borrador local como si siguieran siendo oficiales.
10. Suspender, cancelar por una vía existente o dejar de ser visible públicamente: la proyección se retira o actualiza según la política aprobada, sin dejar el marcador anterior presentado como actualizado ni publicar el borrador como alternativa.
11. Fallar el cierre tras capturar eventos: el acta no queda parcialmente confirmada, los efectos derivados no se adelantan y el borrador aceptado sigue siendo privado.
12. Partido ya cerrado o rectificado: F1 no reabre ni corrige; se consulta la versión vigente y se mantiene el procedimiento 033.

## Fuera de alcance

- Cronología pública de goles, tarjetas, sustituciones u otras incidencias, incluso confirmadas: F13 deberá definirla por separado.
- Ampliar datos personales públicos, publicar borradores individuales o convertir el acta cerrada en editable.
- Crear roles por torneo, alterar permisos HTTP existentes, conceder acceso de plataforma o ampliar F9.
- Nuevas vías de cancelación, abandono o reapertura; transición del ciclo del torneo, avance automático entre fases y cambios en reglas deportivas.
- Operación sin conexión con confirmación posterior automática, replay privado, garantía de entrega de cada aviso o un SLA de latencia no aprobado.
- Detalles de retención o incidencias adicionales que no estén en el catálogo de acta aprobado; no se habilitan tipos desconocidos como texto libre alternativo.

## Criterios de finalización

1. DA-1–DA-4 están resueltas y la spec recibe aprobación expresa antes de pasar a Plan; roles lectores/operadores, estados admitidos, reloj y conjunto a consolidar quedan definidos sin opciones implícitas.
2. Se comprueba el recorrido programado → en vivo → suspendido → reanudado → cerrado, además del cierre actual sin F1, con estados y reloj coherentes y sin confirmar borradores antes del cierre.
3. Se verifica captura/corrección autorizada de goles, tarjetas y sustituciones, borrador vacío, eventos inválidos y desconocidos, cierre correcto, cierre fallido y concurrencia sin duplicación ni pérdida silenciosa.
4. Dos organizaciones y perfiles con/sin permisos y asignación demuestran lectura y entrega privada equivalentes, retirada de acceso, sesión expirada y fallo de autorización con suspensión fail-closed.
5. El público observa solo estado, marcador y reloj aprobados, con provisionalidad/actualización identificables; se comprueban partidos invisibles y ausencia de borradores, datos personales y F9 en el canal del partido.
6. Desconexión, reinicio y resincronización recuperan el estado vigente autorizado sin replay privado ni restaurar otra organización/identidad; el carril público existente conserva su comportamiento.
7. El cierre mantiene sus efectos atómicos y la corrección posterior solo usa 033; se documenta la matriz pública final, se ejecutan las verificaciones aplicables y se solicita aceptación humana de la implementación sin inferirla de F8.

## Dudas abiertas

Primera ronda: cuatro grupos. Todas las opciones y recomendaciones siguientes son propuestas, no decisiones aprobadas; los requisitos que remiten a ellas no habilitan comportamiento mientras sigan abiertas. Los detalles derivados se concretarán en rondas posteriores, antes de aprobar la spec.

### DA-1 — [NECESITA ACLARACIÓN] Lectores y operadores del borrador

- **(a)** Leer el borrador requiere la lectura actual de operación; escribir/iniciar/controlar reloj requiere la autorización actual de cierre del partido.
- **(b)** Leer y operar el nuevo borrador se limita a quienes ya pueden cerrar ese partido, incluidos oficiales bajo sus condiciones actuales; no se alteran las lecturas existentes.
- **(c)** Definir autorización explícita de lectura de borrador, separada de la de operar en vivo, con sus roles por defecto y la asignación al partido cuando se utilice la vía de oficial; no se hereda lectura de la escritura ni viceversa.
- **Recomendación: (c).** Permite lectores de seguimiento sin escritura y evita ampliar automáticamente a todo miembro que ya lea la operación. La política y sus roles deben aprobarse expresamente y tener lectura HTTP equivalente antes de emitir; no se endurecen por inferencia permisos HTTP actuales.

### DA-2 — [NECESITA ACLARACIÓN] Suspensión, reanudación y visibilidad

- **(a)** Conservar la matriz 020: el suspendido deja de ser público; reloj detenido y borrador conservado sin nueva captura hasta reanudar a `live`.
- **(b)** Mantener visible el suspendido con estado, último marcador provisional y reloj detenido; conservar el borrador sin nuevas capturas ni correcciones hasta reanudar a `live`.
- **(c)** Igual visibilidad mínima y reloj detenido que (b), pero permitir revisar/corregir el borrador durante la suspensión antes de reanudar, sin confirmar el acta.
- **Recomendación: (b).** Evita que un partido desaparezca al suspenderse, informa al espectador y distingue una pausa de un cierre; la captura continúa tras reanudación. Requiere aprobar expresamente esta ampliación acotada de 020, que hoy oculta suspendidos. Ninguna opción crea cierre automático, abandono o publicación de incidencias.

### DA-3 — [NECESITA ACLARACIÓN] Significado y control del reloj

- **(a)** Segmento y minuto indicados manualmente por el operador; el público ve esa última referencia, sin avance automático entre actualizaciones.
- **(b)** Tiempo transcurrido acumulado por segmento, iniciado/pausado/reanudado por el operador; permite corrección trazable y se detiene al suspender.
- **(c)** Cuenta regresiva del tiempo restante indicado por el operador, con pausa y tiempo añadido, sin convertir segmentos en periodos reglamentarios ni cerrar automáticamente al llegar a cero.
- **Recomendación: (b).** Representa el tiempo de juego sin contar una suspensión como juego efectivo y permite corregir errores de control. Deben concretarse precisión, tiempo añadido y corrección entre segmentos; no cambia la duración reglamentaria ni convierte el reloj en cierre automático.

### DA-4 — [NECESITA ACLARACIÓN] Revisión y consolidación del borrador

- **(a)** El cierre toma todo el borrador vigente válido, sin una revisión final adicional a las validaciones actuales.
- **(b)** El responsable revisa y confirma expresamente el conjunto vigente completo; corrige/retira antes lo provisional erróneo y el cierre consolida ese conjunto sin descartar incidencias silenciosamente.
- **(c)** En el cierre se selecciona expresamente un subconjunto del borrador; lo excluido queda identificado como descartado privado y nunca se confirma por omisión.
- **Recomendación: (b).** Mantiene un cierre atómico y una revisión consciente, evitando confirmar borradores inadvertidos o perder incidencias sin decisión. Un fallo de cierre conserva lo previamente aceptado y un cambio concurrente exige revisar de nuevo; no permite editar el acta después de confirmarla.
