# Spec 036 — Partido en vivo

Estado: borrador

Fecha: 2026-11-13. Revisión: 2026-11-14. Fase: Spec, pendiente de aprobación expresa. Corresponde a F1 del informe de funciones adicionales. El usuario respondió «Recomendación» a ambas rondas: DA-1 (c), DA-2 (b), DA-3 (b), DA-4 (b), DA-5 (a), DA-6 (a) y DA-7 (a) quedan aceptadas. No quedan dudas abiertas identificadas; esto no equivale a aprobar la spec completa ni autoriza plan, tareas o implementación.

## Contexto y objetivo

La auditoría de octubre identificó en R11 un ciclo de partido incompleto: los estados `live` y `suspended` no tenían un recorrido operativo completo y los eventos se confirmaban únicamente al cerrar el acta. Las specs anteriores de operación mantuvieron los eventos incrementales fuera de su alcance. El seguimiento de noviembre distingue la validez de una conexión de la autorización para recibir información privada; F8, spec 035, ya está implementada y aceptada.

El objetivo es operar un encuentro mientras se disputa: iniciar el partido, suspenderlo y reanudarlo, registrar goles, tarjetas y sustituciones como borradores privados, y ofrecer al público únicamente estado, marcador provisional y reloj de segmento cuando el partido sea visible. El cierre seguirá consolidando el acta y sus efectos de forma atómica, como hasta ahora. Lo observado en vivo no constituye un resultado confirmado.

Fuentes y límites: constitución 2.0.0, apartado F1 y decisión 6.3 del informe de funciones adicionales, auditorías de octubre y noviembre, matriz pública 020 y sus ampliaciones vigentes, cierre 017, rectificación 033 y autorización privada 035. F8 es un prerrequisito, no una autorización genérica para emitir borradores. La cronología pública individual corresponde a F13, no a esta spec.

**Compatibilidad constitucional:** no se propone enmienda. El marcador en vivo debe identificarse como provisional y nunca permitir editar un resultado cerrado. Interpretar «eventos incrementales» como modificación de eventos confirmados contradiría la inmutabilidad y queda excluido: solo la rectificación 033 puede corregir un acta confirmada. La mención del informe a eventos confirmados y cronología pública tras el cierre no amplía aquí la proyección pública vigente. DA-2 (b) aprueba una ampliación acotada de la matriz 020: el suspendido permanece visible con estado, marcador provisional y reloj detenido, sin eventos individuales. Es un requisito para F1, todavía no implementado, no una afirmación sobre el producto actual.

## Decisiones cerradas — ronda 1 (2026-11-13)

| Decisión | Respuesta del usuario («Recomendación») | Comportamiento adoptado |
|---|---|---|
| DA-1 | (c) | Lectura explícita del borrador separada de operar en vivo, con asignación al partido cuando se use la vía de oficial. Los roles por defecto se concretan en DA-5. |
| DA-2 | (b) | Suspendido público con estado, último marcador y reloj detenido; se conserva el borrador sin capturas ni correcciones hasta reanudar a `live`. |
| DA-3 | (b) | Tiempo transcurrido acumulado por segmento, iniciado, pausado y reanudado por el operador, con corrección trazable; detenido durante la suspensión. |
| DA-4 | (b) | Revisión y confirmación expresa del conjunto vigente completo antes del cierre; corrección/retirada previa de lo erróneo, sin descartes silenciosos. |

## Decisiones cerradas — ronda 2 (2026-11-14)

| Decisión | Respuesta del usuario («Recomendación») | Comportamiento adoptado |
|---|---|---|
| DA-5 | (a) | Dueño, administrador y operador reciben por defecto lectura de borrador y operación en vivo para su organización; árbitro recibe ambas solo por la vía de oficial asignado; observador no recibe ninguna por defecto. Son autorizaciones separadas y no conceden cierre ni alteran lecturas existentes. |
| DA-6 | (a) | Reanudar conserva segmento y tiempo acumulado, con reloj pausado hasta reanudación expresa del operador. Si no había referencia, sigue sin iniciar. Crear otro segmento requiere una acción separada y confirmada. |
| DA-7 | (a) | Corregir el reloj cambia solo la referencia de seguimiento: no cambia minutos ni tiempo añadido de hechos aceptados. El operador corrige explícitamente los hechos provisionales antes del cierre si corresponde, con las validaciones vigentes. |

## Usuarios

- Organizador de la competición: necesita conocer el estado operativo y asegurar un cierre coherente.
- Operador y árbitro u otro oficial asignado: registran y revisan lo sucedido según su autorización sobre ese partido.
- Lector privado autorizado: sigue el borrador sin que ello le conceda escritura.
- Público: sigue estado, marcador y reloj sin acceder al borrador ni necesitar sesión.
- Administrador de plataforma: mantiene sus atribuciones actuales; esta funcionalidad no le concede operación ni lectura privada adicionales.

## Roles y visibilidad

- **Público:** solo consulta partidos de torneos visibles públicamente. La proyección adicional se limita al estado del partido, marcador provisional, segmento y reloj, con su condición de provisional o desactualizado. No recibe eventos individuales, identidades de sus protagonistas ni incidencias privadas.
- **Lector de borrador:** necesita autorización explícita de lectura de ese borrador en su organización, independiente de operar en vivo. Pertenecer a la organización, conocer el partido o poder leer la operación actual no concede este acceso; tampoco lo concede automáticamente poder escribir.
- **Operador/oficial:** iniciar, suspender, reanudar, controlar el reloj y modificar el borrador requieren autorización explícita de operación en vivo; esta no concede lectura privada ni cierre del acta por sí sola. La vía de oficial requiere además asignación vigente al partido para el permiso correspondiente. No se introducen roles por torneo ni privilegios de plataforma implícitos.
- **Concesiones por defecto (DA-5 a):** dueño, administrador y operador reciben las dos autorizaciones separadas para su organización; árbitro las recibe solo por la vía de oficial asignado al partido; observador no recibe ninguna. Se evalúan los permisos efectivos vigentes: un actor con varios roles conserva cualquier vía válida, sin exigir asignación a quien accede por una concesión organizativa. No se hereda lectura de escritura ni cierre de operación en vivo.
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
- **`suspended`:** interrupción del encuentro sin confirmación del acta. Conserva íntegro el borrador y detiene el reloj; no admite capturas, correcciones del borrador ni cierre mientras siga suspendido. Permanece públicamente visible con la proyección mínima siguiente si el torneo es visible. Se reanuda a `live` antes de volver a operar o utilizar el cierre existente, conservando segmento y tiempo acumulado sin arrancar el reloj; si no había referencia, sigue sin iniciar.
- **Borrador privado:** conjunto provisional de hechos deportivos de un partido, todavía corregible y no confirmado. No es una nueva versión del acta ni un historial público.
- **Marcador provisional:** resultado mostrado durante la operación en vivo, coherente con el borrador aceptado y las reglas vigentes; no alimenta por sí solo efectos de un acta cerrada.
- **Reloj de segmento:** tiempo transcurrido acumulado del segmento, excluyendo pausas; el operador lo inicia, pausa, reanuda y corrige de forma trazable mientras el partido esté `live`. Un segmento sigue siendo la ventana operativa de 017, no una mitad ni un periodo reglamentario. Reanudar el partido no crea un segmento ni arranca su reloj: crear otro segmento exige una acción separada y confirmada conforme a 017. Corregir el reloj no cambia minutos ni tiempo añadido de hechos aceptados ni las validaciones deportivas; cualquier corrección de esos hechos es explícita y previa al cierre.
- **Consolidación:** revisión y confirmación expresa del conjunto vigente completo de eventos junto al resultado y los efectos actuales del cierre, en una sola operación indivisible. Lo erróneo debe corregirse o retirarse antes; no se permite elegir un subconjunto silenciosamente al cerrar. Un cambio posterior de los hechos o resultado a confirmar exige revisar de nuevo; el mero avance del reloj o una nueva observación pública no cambian ese conjunto.
- **Aviso privado:** invalidación mínima de 035 para consultar el estado por HTTP autorizado; no transporta el detalle del borrador ni acredita permiso por sí mismo.

## Proyección pública exacta de F1

DA-2 (b) cambia expresamente la exclusión de suspendidos de 020. Para un partido `suspended` de un torneo visible, la representación pública queda limitada a esta lista cerrada; no se incorpora automáticamente el resto del detalle de operación ni una alineación por el hecho de suspender. El contexto solo identifica al partido, torneo y equipos ya públicos. En `live`, los campos de reloj y provisionalidad se añaden a la proyección pública vigente; los demás estados mantienen sus lecturas actuales. No se alteran los eventos públicos existentes de 035.

| Campo público | Significado y valor en `suspended` |
|---|---|
| `id` | Identificador público del partido. |
| `tournament_id` | Identificador del torneo visible al que pertenece. |
| `home_team_id` | Identificador del equipo local público del partido. |
| `home_team_name` | Nombre público del equipo local. |
| `away_team_id` | Identificador del equipo visitante público del partido. |
| `away_team_name` | Nombre público del equipo visitante. |
| `status` | `suspended`; la suspensión del encuentro no es una sanción de jugador. |
| `home_score` | Goles provisionales del local en el último borrador aceptado antes de suspender. |
| `away_score` | Goles provisionales del visitante en ese mismo borrador. |
| `is_provisional` | `true`, tanto en `live` como en `suspended`; no es un resultado confirmado. |
| `clock_segment_number` | Número del segmento de la última referencia válida, o nulo si aún no existe referencia. |
| `clock_elapsed_seconds` | Segundos completos acumulados en ese segmento, excluidas las pausas; congelados durante la suspensión, o nulo si aún no existe referencia. |
| `clock_state` | `paused` si existe referencia; `not_started` si aún no existe. Nunca `running` durante la suspensión. En `live` admite también `running`. |
| `clock_observed_at` | Instante de observación de la referencia pública, sin identidad de quien controló el reloj; no suma tiempo a un reloj detenido. |

No se publican tipo, minuto, protagonista, asistente, autor ni identificador de eventos individuales; tampoco motivo de suspensión, motivos administrativos, auditoría, sanciones ni borradores. Si el reloj aún no tiene referencia, se muestra «sin iniciar», no un tiempo inventado. La pérdida de conexión se anuncia como estado desactualizado de la vista, no como una transición deportiva ni como un campo privado adicional.

## Requisitos funcionales

- **RF-001:** CUANDO un responsable autorizado inicie un partido programado de su organización con versión de torneo publicada y participantes válidos, EL SISTEMA lo pasará a `live` y permitirá identificar su segmento actual sin confirmar el acta.
- **RF-002:** CUANDO un operador autorizado suspenda un partido `live` de su organización, EL SISTEMA lo pasará a `suspended`, detendrá el reloj y conservará el último marcador y borrador aceptados sin admitir nuevas capturas ni correcciones del borrador hasta reanudar a `live`; suspender no confirmará ni cerrará el acta.
- **RF-003:** SI una transición es inválida, el partido es terminal o su versión no permite operar, ENTONCES EL SISTEMA rechazará la nueva operación en vivo sin modificar estado, reloj, borrador ni efectos deportivos existentes.
- **RF-004:** MIENTRAS un partido admita captura en vivo según su estado, EL SISTEMA permitirá al operador autorizado registrar los tipos del catálogo cerrado de su acta, incluidos goles, autogoles, tarjetas y sustituciones, manteniéndolos privados y provisionales.
- **RF-005:** CUANDO se acepte un hecho del borrador, EL SISTEMA conservará su equipo, protagonistas y relaciones deportivas aplicables, segmento y tiempo, y actualizará de forma coherente el marcador provisional cuando corresponda; el hecho seguirá perteneciendo solo al partido y organización autorizados.
- **RF-006:** CUANDO un operador autorizado corrija o retire un hecho todavía provisional de un partido `live` de su organización, EL SISTEMA reflejará la corrección en el borrador y marcador, invalidará cualquier revisión de cierre anterior y exigirá revisar el conjunto vigente completo, sin editar actas confirmadas ni sobrescribir silenciosamente cambios ajenos.
- **RF-007:** SI un evento es desconocido, incompleto o inválido para participantes, segmento, tiempo o reglas del torneo, ENTONCES EL SISTEMA lo rechazará con una explicación para el operador autorizado, sin incorporarlo al borrador ni cambiar marcador, reloj o efectos de cierre.
- **RF-008:** EL SISTEMA mantendrá separados el borrador y los resultados confirmados: registrar o corregir un hecho provisional no adelantará la clasificación, las estadísticas, las sanciones ni el avance que correspondan al cierre del acta.
- **RF-009:** CUANDO se consulte o actualice un partido visible públicamente, EL SISTEMA aplicará la proyección exacta de F1: solo los catorce campos definidos para `suspended`; para `live`, la proyección pública vigente más reloj y provisionalidad; los demás estados conservarán sus lecturas actuales, distinguiendo el resultado provisional del confirmado y sin publicar eventos individuales del borrador.
- **RF-010:** SI el torneo no es públicamente visible o el partido está cancelado, ENTONCES EL SISTEMA no entregará su estado, marcador ni reloj públicos y no revelará más que ante un recurso inexistente; estar `suspended` no ocultará por sí solo un partido de un torneo visible.
- **RF-011:** MIENTRAS un reloj esté en ejecución en un partido `live`, EL SISTEMA acumulará solo el tiempo transcurrido del segmento fuera de pausas y permitirá su control y corrección trazable exclusivamente al operador autorizado de su organización; al pausar o suspender dejará de acumular tiempo, sin alterar reglas de duración ni presentar una referencia desactualizada como tiempo oficial actualizado.
- **RF-012:** CUANDO un destinatario consulte el borrador o se evalúe una entrega privada, EL SISTEMA comprobará su autorización explícita de lectura, independiente de escritura, junto a sesión, usuario, membresía y asignación vigente cuando use la vía de oficial, para la lectura HTTP equivalente del partido concreto de su organización, conforme a 035 y a las concesiones por defecto de DA-5 (a), sin exigir asignación cuando exista una vía organizativa válida.
- **RF-013:** EL SISTEMA exigirá que cada nuevo aviso de F1 esté incluido expresamente en el catálogo cerrado, con su carácter público o privado, lectura HTTP equivalente y recurso autorizado definidos y aprobados antes de habilitarlo; ni F8 ni compartir nombre con un evento público concederán visibilidad pública o acceso al borrador.
- **RF-014:** CUANDO comunique cambios privados del borrador, EL SISTEMA mantendrá las invalidaciones mínimas de 035 y reservará el detalle para su consulta autorizada; nunca difundirá el borrador a todos los miembros por el mero hecho de pertenecer a la organización.
- **RF-015:** SI se retira una autorización o no se puede verificar al destinatario, ENTONCES EL SISTEMA impedirá las entregas privadas afectadas conforme al corte y suspensión fail-closed de 035, sin usar permisos antiguos, convertirlas en públicas ni prometer retirar información ya aprobada o enviada antes del corte.
- **RF-016:** CUANDO cambie la identidad u organización activa o se deniegue una lectura vigente, EL SISTEMA limpiará la vista privada que haya dejado de estar autorizada e impedirá que respuestas o actualizaciones anteriores restauren ese contexto o sus borradores.
- **RF-017:** CUANDO se pierda la conexión, EL SISTEMA distinguirá la información mostrada de una actualización verificada, no simulará la aceptación de nuevas escrituras y advertirá de que marcador, borrador o reloj pueden estar desactualizados.
- **RF-018:** CUANDO se restablezca la conexión o se solicite la resincronización de 035, EL SISTEMA recuperará mediante HTTP el estado actual permitido para el contexto vigente, sin reproducir avisos privados perdidos ni incluir datos de negocio en la señal de resincronización.
- **RF-019:** CUANDO se solicite cerrar un acta con borrador en vivo, EL SISTEMA exigirá la autorización vigente de cierre ya existente y la revisión y confirmación expresa del conjunto vigente completo mediante su lectura autorizada, revalidará estado y reglas deportivas y lo consolidará atómicamente con resultado, contadores y efectos actuales del cierre; un cambio de los hechos o resultado a confirmar tras la revisión exigirá revisarla de nuevo, sin duplicar ni descartar eventos por omisión. El mero avance del reloj no invalidará la revisión y el cierre sin borrador F1 mantendrá su autorización actual.
- **RF-020:** SI falla la validación o consolidación del cierre, ENTONCES EL SISTEMA no confirmará parcialmente eventos, resultado, clasificación, sanciones ni avance, y conservará el borrador previamente aceptado como privado y no confirmado para su revisión autorizada.
- **RF-021:** CUANDO el cierre confirme el acta, EL SISTEMA terminará la operación provisional y servirá el resultado y acta vigentes conforme a las lecturas existentes; ninguna escritura en vivo pendiente podrá modificar lo confirmado ni ejecutar dos veces sus efectos.
- **RF-022:** SI se intenta corregir un acta confirmada desde la operación en vivo, ENTONCES EL SISTEMA rechazará el cambio y conservará la rectificación 033 como única vía de corrección, con original e historial inmutables y sin reapertura implícita.
- **RF-023:** SI una modificación o cierre se basa en un estado que otro operador ya cambió, ENTONCES EL SISTEMA evitará sobrescribir silenciosamente el trabajo aceptado, informará del conflicto al actor autorizado y exigirá revisar el estado vigente antes de confirmarlo.
- **RF-024:** SI el borrador está vacío, ENTONCES EL SISTEMA lo mostrará como tal, sin inventar incidencias, y mantendrá el cierre sin eventos cuando las reglas y la resolución existentes lo permitan; no obligará a capturar eventos ficticios ni a utilizar el flujo en vivo.
- **RF-025:** CUANDO un partido llegue a un estado terminal por una vía ya admitida, EL SISTEMA bloqueará nuevas operaciones provisionales; la mera salida del flujo en vivo no convertirá por sí sola un borrador pendiente en eventos confirmados ni creará una vía nueva de cancelación o abandono.
- **RF-026:** CUANDO acepte una transición, control del reloj o cambio de borrador, EL SISTEMA permitirá atribuir el acto a su responsable y momento dentro de la organización, sin publicar esa trazabilidad ni volcar el contenido privado en registros técnicos.
- **RF-027:** EL SISTEMA conservará los avisos y expedientes F9 fuera del canal de tiempo real del partido, y mantendrá la cronología pública F13 fuera de esta funcionalidad, incluso después del cierre.
- **RF-028:** CUANDO un partido de un torneo visible esté `suspended`, EL SISTEMA lo mantendrá públicamente visible solo con los catorce campos de la lista cerrada de proyección pública de F1, marcador provisional congelado y reloj detenido o sin iniciar, sin eventos individuales ni nuevos datos personales.
- **RF-029:** CUANDO un operador autorizado reanude un partido `suspended` de su organización, EL SISTEMA lo devolverá a `live`, conservará borrador, segmento y tiempo acumulado y mantendrá el reloj pausado hasta reanudación expresa del operador, o sin iniciar si no había referencia; no creará otro segmento ni recuperará automáticamente como aceptadas escrituras hechas durante la suspensión o sin conexión.
- **RF-030:** CUANDO un operador autorizado corrija el reloj de un partido `live` de su organización, EL SISTEMA cambiará solo su referencia de seguimiento con trazabilidad, sin modificar los minutos ni el tiempo añadido de hechos aceptados; cualquier corrección de un hecho provisional requerirá una acción explícita con las validaciones vigentes e invalidará la revisión de cierre conforme a RF-006.
- **RF-031:** EL SISTEMA concederá por defecto lectura de borrador y operación en vivo como autorizaciones separadas a dueño, administrador y operador para su organización, y a árbitro por la vía de oficial asignado al partido, sin conceder ninguna al observador por defecto ni alterar permisos de cierre o lecturas existentes.

## Requisitos no funcionales

- **RNF-001:** EL SISTEMA garantizará que conocer identificadores, acumular roles o mantener conexiones previas no permita leer ni modificar borradores de otra organización; las comprobaciones incluirán dos organizaciones, permisos de lectura y operación separados, los roles por defecto de DA-5 (a), oficiales asignados/no asignados y miembros con varias vías de acceso.
- **RNF-002:** EL SISTEMA preservará los nombres, contenido y semántica de los eventos públicos existentes; cualquier proyección adicional de F1 se limitará a lo aprobado aquí y no reutilizará una variante privada como pública por coincidencia de nombre.
- **RNF-003:** EL SISTEMA conservará las reglas configuradas de segmentos, tiempos, participantes, sustituciones y cierre; el reloj no impondrá duraciones deportivas nuevas ni relajará las validaciones actuales.
- **RNF-004:** EL SISTEMA conservará el borrador, marcador y referencia de reloj aceptados tras desconexión o reinicio y los devolverá coherentemente a dos lectores autorizados mediante lectura actual, sin duplicar hechos por reintentos ni prometer entrega de todos los avisos o un plazo de entrega no acordado.
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
4. Suspender entre segmentos: marcador y reloj quedan congelados y el borrador privado no admite capturas ni correcciones; reanudar conserva lo aceptado y la última referencia de segmento, con reloj pausado o sin iniciar si no había referencia. No crea ni reactiva implícitamente un segmento deportivo cerrado; crear otro es una acción separada conforme a 017.
5. Datos inválidos, tipos desconocidos, jugadores de otro equipo/organización o tiempos incompatibles: rechazo sin cambios ni revelación de información ajena.
6. Dos operadores cambian el mismo partido, o uno cierra mientras otro edita: conflicto explícito, sin pérdida silenciosa ni modificación de lo confirmado.
7. Revocar un permiso/asignación, expirar una sesión o fallar su comprobación durante el partido: no hay nuevas entregas privadas no verificadas; volver a tener permiso exige revalidación y lectura actual, no replay.
8. Cambiar identidad u organización con lecturas pendientes: las respuestas antiguas no recuperan contenido del contexto anterior.
9. Desconectarse antes de suspender/cerrar, y volver después: lectura vigente autorizada, no continuación de un reloj o borrador local como si siguieran siendo oficiales.
10. Suspender mantiene los catorce campos públicos mínimos, incluido el reloj detenido; cancelar por una vía existente o dejar de ser visible el torneo retira la proyección, sin presentar el marcador anterior como actualizado ni publicar borradores como alternativa.
11. Fallar el cierre tras capturar eventos: el acta no queda parcialmente confirmada, los efectos derivados no se adelantan y el borrador aceptado sigue siendo privado.
12. Partido ya cerrado o rectificado: F1 no reabre ni corrige; se consulta la versión vigente y se mantiene el procedimiento 033.
13. Suspender antes de tener una referencia de reloj: reloj «sin iniciar», con segmento/tiempo nulos; nunca avanza ni inventa un segmento. Dos observaciones durante la suspensión conservan el mismo tiempo acumulado y marcador aunque cambie el instante de observación.
14. Modificar el borrador después de que otro responsable lo revise para cerrar: revisión inválida, nueva lectura y confirmación del conjunto completo; ni selección silenciosa ni cierre sobre una revisión obsoleta.
15. Corregir un reloj con hechos ya aceptados: sus minutos y tiempo añadido permanecen iguales; si procede corregirlos, se hace explícitamente, con rechazo de tiempos inválidos sin cambios parciales y nueva revisión de cierre. Corregir solo el reloj no cambia el conjunto de hechos revisado.
16. Árbitro sin asignación o asignado a otro partido, y observador sin concesión explícita: no leen ni operan el borrador por esos roles. Dueño, administrador u operador con acceso organizativo vigente no necesitan asignación; en varios roles se acepta cualquier vía válida dentro de la organización, sin mezclar permisos entre tenants.

## Fuera de alcance

- Cronología pública de goles, tarjetas, sustituciones u otras incidencias, incluso confirmadas: F13 deberá definirla por separado.
- Ampliar datos personales públicos, publicar borradores individuales o convertir el acta cerrada en editable.
- Crear roles por torneo, alterar permisos HTTP existentes, conceder acceso de plataforma o ampliar F9.
- Nuevas vías de cancelación, abandono o reapertura; transición del ciclo del torneo, avance automático entre fases y cambios en reglas deportivas.
- Operación sin conexión con confirmación posterior automática, replay privado, garantía de entrega de cada aviso o un SLA de latencia no aprobado.
- Detalles de retención o incidencias adicionales que no estén en el catálogo de acta aprobado; no se habilitan tipos desconocidos como texto libre alternativo.

## Criterios de finalización

1. DA-1–DA-7 están registradas como cerradas; la spec completa debe recibir aprobación expresa antes de pasar a Plan. Roles lectores/operadores, control al reanudar y corrección temporal quedan definidos sin opciones implícitas. Cerrar las dudas no equivale a aprobar la spec.
2. Se comprueba el recorrido programado → en vivo → suspendido → reanudado → cerrado, además del cierre actual sin F1, con estados y reloj coherentes y sin confirmar borradores antes del cierre.
3. Se verifica captura/corrección autorizada de goles, tarjetas y sustituciones, borrador vacío, eventos inválidos y desconocidos, cierre correcto, cierre fallido y concurrencia sin duplicación ni pérdida silenciosa.
4. Dos organizaciones y perfiles con/sin permisos y asignación demuestran lectura y entrega privada equivalentes, retirada de acceso, sesión expirada y fallo de autorización con suspensión fail-closed.
5. El suspendido visible cumple exactamente la lista cerrada de catorce campos, sin eventos individuales; el reloj no avanza entre observaciones. Se prueban referencia ausente, torneos invisibles y cancelados, sin borradores, datos personales ni F9 en el canal del partido. Los campos de reloj/provisionalidad de `live` respetan la misma definición.
6. Desconexión, reinicio y resincronización recuperan el estado vigente autorizado sin replay privado ni restaurar otra organización/identidad; el carril público existente conserva su comportamiento.
7. El cierre mantiene sus efectos atómicos y la corrección posterior solo usa 033; se documenta la matriz pública final, se ejecutan las verificaciones aplicables y se solicita aceptación humana de la implementación sin inferirla de F8.

## Dudas abiertas

Sin dudas abiertas identificadas tras la revisión integral de ambas rondas. DA-1–DA-7 están cerradas; no se propone ronda 3. La spec permanece en borrador, pendiente de aprobación expresa del usuario antes de Plan.

La revisión de coherencia conserva: la inmutabilidad y consolidación atómica de la constitución; la lista específica de catorce campos de 020 para suspendidos, sin extenderla a eventos individuales; la rectificación 033 como única corrección del acta confirmada, sin restringir su historial existente a los nuevos lectores de borrador; y la autorización fresca por lectura HTTP equivalente, invalidaciones mínimas y recuperación sin replay de 035. Las concesiones nuevas de F1 no endurecen las lecturas existentes ni habilitan F9 en tiempo real. La reanudación del partido no sustituye las reglas de segmentos de 017.
