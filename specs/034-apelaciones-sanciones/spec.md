# Spec 034 — Apelaciones y resoluciones de sanciones

Estado: borrador

Fecha: 2026-11-12. Desarrolla F9 y la §3.6 de la constitución 2.0.0. Complementa la spec 033; no la sustituye ni amplía la excepción de inmutabilidad de las actas. Conserva la matriz pública de la spec 020.

## Contexto y objetivo

Una sanción puede ser impugnada sin que ello signifique que ha dejado de regir. El recurso, la decisión administrativa y los partidos de suspensión ya cumplidos son hechos distintos que deben poder consultarse sin borrar el pasado ni confundirlos con una corrección del acta que originó la sanción.

La constitución 2.0.0, §3.6, establece literalmente:

> La apelación de una sanción es una solicitud formal de revisión, con estado y resolución administrativa; no modifica la sanción por sí misma. La anulación o modificación de una sanción solo se produce mediante una resolución auditada que determina su nuevo estado. Si la corrección de una sanción altera el contenido confirmado de un acta, requiere su rectificación.

**Objetivo:** permitir tramitar recursos y conocer la sanción que rige como consecuencia de una resolución identificable y motivada, manteniendo la trazabilidad, los cumplimientos históricos, el aislamiento organizativo y la inmutabilidad de lo ya disputado.

Este borrador está en fase de clarificación: DA-1, DA-2, DA-4 y DA-5 están cerradas por el usuario y recogidas en los requisitos. Las recomendaciones de las otras 14 DA **no son decisiones aprobadas** ni autorizan implementación. Siguen pendientes, entre otras políticas, los estados del recurso, los plazos y la separación entre interponente y resolutor.

### Estado actual comprobado (2026-11-12)

Revisión del comportamiento descrito por el código, los contratos de pruebas y las specs vigentes; no es una inspección de datos de producción.

| # | Hecho actual | Consecuencia para F9 |
|---|---|---|
| 1 | El cierre de un acta genera suspensiones por acumulación de amarillas y expulsiones con las reglas de la versión del torneo. El historial ayuda a contar amarillas, pero no origina sanciones por sí solo. La expulsión por doble amarilla absorbe las sanciones por acumulación de ese jugador en esa acta; la roja directa no las absorbe. | Apelar la consecuencia disciplinaria no equivale a corregir una tarjeta ni a cambiar las reglas del torneo. |
| 2 | Una sanción identifica jugador, organización, torneo de origen, motivo, duración en partidos, ámbito de torneo u organización y procedencia. Las derivadas actualmente del cierre tienen ámbito organizativo. Se admiten también orígenes administrativos y de regla de competición, sin un flujo general de alta administrativa de sanciones. | La admisibilidad de cada origen y ámbito se aclara en DA-13; su existencia como categoría no demuestra que ya haya un procedimiento de resolución. |
| 3 | Existen los valores `active`, `served`, `appealed` y `cancelled`. No se encontró un flujo de aplicación que establezca `appealed`, ni operaciones propias de apelación o de modificación administrativa de la duración. | El nombre de un estado existente no constituye un procedimiento de recurso. No se afirma que no existan datos históricos con ese valor. |
| 4 | `cancelled` sí se escribe operativamente en la spec 033 al publicar una rectificación: se anulan con registro las sanciones del partido que ya no corresponden. También se crean las nuevas y se conservan las que siguen correspondiendo. | No debe describirse toda anulación como una función aún inexistente ni confundir esta vía con F9. |
| 5 | Un cumplimiento registra el partido y la sanción. Se cuenta cuando el equipo del jugador disputa el partido, existe inscripción activa y el jugador no está en la convocatoria válida, conforme al ámbito y a las comprobaciones vigentes. Se cuentan los cumplimientos no anulados; al alcanzar la duración, la sanción pasa a `served`. El walkover no crea ni sirve suspensiones. | El número ya cumplido y el pendiente son distintos. La apelación no puede borrar partidos consumados. |
| 6 | El cierre no walkover comprueba si la convocatoria válida contiene un jugador con sanción `active`, aplicable al torneo o a la organización y con partidos pendientes; en ese caso rechaza el cierre. El guardado y la publicación de la alineación no consultan por sí mismos las suspensiones. | El bloqueo comprobado es el del cierre, no un bloqueo anticipado del guardado de alineaciones. Ampliarlo requiere DA-16. |
| 7 | La comprobación de bloqueo y la contabilización de cumplimientos filtran sanciones `active`. Una sanción etiquetada `appealed` no entraría en esas comprobaciones. No se encontró una operación que produzca esa transición por presentar un recurso. | Usar esa etiqueta para una apelación sin más produciría un cambio de efectos contrario a §3.6 y queda excluido por DA-5. |
| 8 | No hay permisos específicos de presentación o resolución de apelaciones. El cierre exige permiso de cierre de actas; la spec 033 tiene permisos distintos para solicitar y aprobar una rectificación. La resolución administrativa de un partido tampoco es una resolución de sanción. | Ninguno de esos permisos concede por analogía facultades F9. DA-2 define su autorización. |
| 9 | La spec 033 conserva los cumplimientos de sanciones anuladas; una sanción nueva solo empieza a cumplirse en el siguiente partido del jugador que no haya comenzado al publicarse la rectificación (DA-8 y RF-018 de esa spec). Distingue procedencia del evento original y de un evento de una versión rectificada. | F9 no puede devolver ni reescribir esos cumplimientos, ni perder la procedencia versionada. |
| 10 | Hoy las características de una sanción, salvo su estado, están protegidas contra modificación. Una tarjeta retirada que reaparece por rectificación genera una nueva sanción, sin reactivar la anulada. Los posibles efectos sobre sanciones de partidos posteriores confirmados se registran como impactos, sin modificarlas automáticamente. | Permitir modificaciones administrativas requiere concretar sus efectos y su convivencia con el recálculo; no basta con habilitar la edición de una duración. |
| 11 | Las sanciones y cumplimientos están aislados por organización. El público no recibe sanciones ni suspensiones; sí puede ver las estadísticas de tarjetas permitidas por las specs públicas. | F9 no amplía esa exposición ni elimina tarjetas de las estadísticas por resolver un recurso. |

## Usuarios

- **Persona legitimada para recurrir:** miembro de la organización con el nuevo permiso de presentación; registra en nombre de qué equipo o jugador presenta el recurso (DA-1).
- **Persona autorizada para resolver:** dispone del nuevo permiso de resolución y puede mantener, anular o reducir los partidos de sanción (DA-2 y DA-4); la separación respecto del interponente sigue pendiente de DA-3.
- **Responsable operativo del partido:** necesita distinguir la tramitación del recurso de la elegibilidad disciplinaria vigente para preparar la convocatoria y cerrar el acta.
- **Jugador afectado y, en su caso, representante:** personas cuyos datos y situación disciplinaria se tratan; no se presupone una cuenta ni un acceso propio.
- **Administrador de plataforma:** posible intervención excepcional pendiente de DA-8; no tiene facultades F9 implícitas.
- **Público:** no participa en este procedimiento ni accede a sus datos.

## Roles y visibilidad

- **Público:** no ve sanciones, suspensiones, recursos, resoluciones, responsables, motivos, evidencias ni cumplimientos. No se añade una marca pública de apelación.
- **Miembros de la organización:** consultar, presentar y resolver requieren facultades nuevas y separadas, asignadas por defecto a dueño y administrador (DA-2). No se presupone lectura de expedientes para todos los miembros ni se hereda ninguna facultad de permisos existentes.
- **Interponente y resolutor:** solo actúan con legitimación y autorización vigentes según DA-1–DA-3; sus capacidades no se deducen de poder operar un partido o aprobar un acta rectificativa.
- **Delegados externos y jugador/tutor:** no tienen acceso propio al procedimiento; quedan fuera de alcance (DA-1). La representación registrada por un miembro autorizado no les concede acceso ni permisos.
- **Plataforma:** su eventual actuación y visibilidad requieren aclaración expresa en DA-8, separación de la organización y auditoría de plataforma. Nunca habilitan edición directa de actas o resultados cerrados.
- **Aislamiento:** ninguna organización puede ver ni modificar sanciones, recursos, resoluciones, evidencias, cumplimientos o historial de otra; tampoco debe poder averiguar su existencia mediante una referencia ajena.

## Historias de usuario

- **HU-1.** Como persona legitimada, quiero presentar un recurso motivado contra una sanción identificada y consultar su tramitación, sin que presentarlo se confunda con levantar la sanción.
- **HU-2.** Como persona autorizada para resolver, quiero conocer la procedencia, los cumplimientos y las decisiones anteriores antes de motivar una resolución y determinar su efecto.
- **HU-3.** Como responsable operativo, quiero saber qué sanción rige para un partido y qué decisión la sustenta, sin interpretar una apelación pendiente como habilitación del jugador.
- **HU-4.** Como miembro con permiso de consulta, quiero reconstruir quién recurrió, quién decidió, cuándo y por qué, sin perder los estados y decisiones anteriores.
- **HU-5.** Como responsable de una revisión, quiero distinguir un desacuerdo con la sanción de un error del acta, para que este último use la vía rectificativa aprobada y no una edición encubierta.

## Definiciones

- **Sanción:** consecuencia disciplinaria atribuida a un jugador, con motivo, origen y ámbito; en el comportamiento actual se materializa como una suspensión por partidos.
- **Apelación:** solicitud formal de revisión contra una sanción. Tiene interponente, motivo y estado de tramitación propios; no es una anulación ni una modificación de la sanción.
- **Resolución administrativa de sanción:** decisión auditada que determina el nuevo estado o mantiene la sanción y, cuando se permita, concreta qué cambia y su efecto. No es la resolución administrativa de un partido ni una rectificación de acta.
- **Anulación:** decisión que deja sin efecto la sanción en los términos que se aprueben, conservando su existencia y los hechos ya cumplidos. No borra el evento deportivo de origen.
- **Modificación administrativa:** reducción de los partidos de sanción mediante resolución auditada, sin reescribir el acta; no permite aumentar la duración ni cambiar el ámbito (DA-4).
- **Cumplimiento:** hecho registrado de un partido computado para servir una suspensión; no es un plazo de tiempo ni una apelación.
- **Procedencia:** relación trazable de la sanción con su causa, distinguiendo, cuando corresponda, el evento del acta original del evento de una versión rectificada.
- **Efecto suspensivo:** cese provisional de efectos de la sanción mientras se tramita un recurso. No se admite en este procedimiento (DA-5): la apelación no suspende ni altera la sanción por sí misma.

## Requisitos funcionales

Las remisiones a DA cerradas recogen decisiones aprobadas; las condiciones que dependen de DA abiertas deberán concretarse antes de aprobar la spec completa.

### Recurso y resolución separados

- **RF-001.** EL SISTEMA distinguirá el estado de tramitación de una apelación del estado y de los efectos de la sanción recurrida, dentro de su organización.
- **RF-002.** CUANDO un miembro de la organización con permiso de presentación presente una apelación conforme a las reglas de admisión que se aprueben, EL SISTEMA registrará la sanción recurrida, la organización, el interponente responsable, el equipo o jugador en cuyo nombre actúa, la fecha y el motivo, sin modificar por ese acto la sanción ni sus cumplimientos.
- **RF-003.** MIENTRAS una apelación no tenga una resolución que altere los efectos disciplinarios, EL SISTEMA conservará los efectos vigentes de la sanción, sin efecto suspensivo ni medidas provisionales de suspensión por el recurso; la sanción seguirá bloqueando el cierre del acta cuando resulte aplicable y tenga partidos pendientes, conforme a las comprobaciones actuales.
- **RF-004.** CUANDO una persona autorizada dicte una resolución, EL SISTEMA registrará el responsable, la fecha, el motivo, la decisión, la sanción afectada, su estado anterior y el resultante y, si hay modificación, los valores anteriores y resultantes y el momento de efecto autorizado. Vinculará el recurso cuando la resolución responda a uno; la posibilidad de resolver sin recurso depende de DA-6.
- **RF-005.** SI no existe una resolución auditada y autorizada que lo sustente, ENTONCES EL SISTEMA impedirá anular o modificar administrativamente una sanción. La etiqueta de apelación no será una vía alternativa para cambiar sus efectos.
- **RF-006.** CUANDO se consulte un expediente con el nuevo permiso de consulta, EL SISTEMA mostrará el recurso, su estado, las resoluciones relacionadas, la sanción que rige y sus cumplimientos históricos, sin mezclar expedientes de organizaciones distintas; la eventual intervención de plataforma sigue pendiente de DA-8.

### Legitimación, facultades y decisiones permitidas

- **RF-018.** SI quien intenta presentar una apelación no es miembro de la organización de la sanción o carece del nuevo permiso de presentación, ENTONCES EL SISTEMA impedirá presentarla, sin crear el recurso ni modificar la sanción; registrar representación de un equipo o jugador no concederá acceso a delegados externos, jugadores o tutores.
- **RF-019.** EL SISTEMA exigirá facultades nuevas y separadas para consultar, presentar y resolver apelaciones y resoluciones de sanciones dentro de la organización, asignadas por defecto a dueño y administrador; no concederá ninguna por herencia de permisos existentes de cierre, resolución administrativa de partidos o rectificación de actas. Disponer de las facultades de presentación y resolución no decide la separación de personas pendiente de DA-3, ni la asignación por defecto resuelve la excepción de plataforma pendiente de DA-8.
- **RF-020.** CUANDO una persona autorizada resuelva sobre una sanción, EL SISTEMA limitará la decisión a mantenerla, anularla o reducir los partidos de sanción, e impedirá aumentarlos o cambiar su ámbito; mantendrá el aislamiento de la organización y el historial auditado, sin modificar el acta de origen.

### Actas, procedencia y hechos consumados

- **RF-007.** SI corregir una sanción exige cambiar, retirar o reasignar una tarjeta u otro contenido confirmado de un acta, ENTONCES EL SISTEMA exigirá la vía de rectificación de la spec 033 para ese cambio: solicitud, revisión y aprobación por otra persona autorizada y publicación de una versión nueva. Resolver una apelación no modificará el acta ni sustituirá esos pasos.
- **RF-008.** CUANDO una resolución no requiera rectificar un acta, EL SISTEMA conservará sus eventos confirmados y las estadísticas derivadas de ellos; anular una suspensión no eliminará por sí mismo la tarjeta registrada.
- **RF-009.** EL SISTEMA conservará el historial de recursos, decisiones y cambios de estado con sus responsables, fechas y motivos, sin borrar registros ni ocultar valores anteriores mediante una corrección posterior.
- **RF-010.** CUANDO se anule o modifique una sanción, EL SISTEMA conservará como hechos históricos los cumplimientos ya registrados. Su cómputo para un saldo pendiente o una obligación posterior se concretará en DA-9, sin borrar ni devolver hechos consumados de la spec 033.
- **RF-011.** CUANDO una sanción proceda de un acta original o rectificada, EL SISTEMA conservará la identificación de esa procedencia y sus decisiones asociadas; no trasladará silenciosamente una resolución a una sanción distinta creada después. La coordinación y prioridad entre procedimientos se concretarán en DA-10.
- **RF-012.** CUANDO intervenga una rectificación de la spec 033, EL SISTEMA respetará su DA-8 y RF-018: las sanciones anuladas conservan los cumplimientos, las nuevas empiezan a cumplirse en el siguiente partido del jugador no comenzado al publicarse la versión y los partidos posteriores confirmados y sus sanciones no se reescriben automáticamente.
- **RF-013.** SI una decisión tiene consecuencias sobre partidos ya disputados, ENTONCES EL SISTEMA no modificará automáticamente sus resultados, actas, alineaciones publicadas, clasificación o avance para compensarlas. El tratamiento del impacto pendiente de DA-11 no autoriza excepciones a la inmutabilidad.

### Elegibilidad, autorización y privacidad

- **RF-014.** CUANDO se compruebe la elegibilidad disciplinaria de un jugador para un partido, EL SISTEMA usará las sanciones y resoluciones aplicables y los cumplimientos computables, no la mera existencia de un recurso ni el nombre de un estado de apelación. El momento de efecto y los puntos de comprobación se concretarán en DA-15 y DA-16.
- **RF-015.** SI una persona carece de autorización para consultar o actuar sobre un expediente, ENTONCES EL SISTEMA impedirá la consulta o la acción sin alterar el recurso, la sanción o el historial. Para referencias ajenas a la organización no revelará si el expediente existe.
- **RF-016.** EL SISTEMA impedirá toda lectura o modificación entre organizaciones de sanciones, apelaciones, resoluciones, evidencias y cumplimientos, incluso al relacionar una sanción con un jugador, partido, acta o recurso.
- **RF-017.** EL SISTEMA no expondrá públicamente sanciones, suspensiones ni información del procedimiento, incluidos estados, motivos, evidencias, responsables, decisiones y cumplimientos; mantendrá la matriz mínima de la spec 020 sin añadir campos públicos por F9.

## Requisitos no funcionales

- **RNF-001.** El aislamiento y las restricciones de acceso cumplirán los principios constitucionales de protección entre organizaciones y de ausencia de privilegios para eludirla; no dependerán solo de ocultar controles al usuario.
- **RNF-002.** La decisión, su efecto disciplinario y su registro auditado serán consistentes: un fallo no dejará un cambio de sanción sin su resolución ni una resolución presentada como aplicada sin su efecto. Los reintentos o decisiones concurrentes no duplicarán efectos ni ocultarán qué decisión rige.
- **RNF-003.** Ninguna resolución habilitará edición directa de actas o resultados confirmados ni de versiones de torneo publicadas. No se altera la constitución ni las reglas deportivas publicadas para resolver un caso individual.
- **RNF-004.** El historial permitirá reconstruir la situación anterior y posterior, el autor, la fecha y el motivo de cada decisión y su vínculo con los hechos deportivos, aun cuando cambie posteriormente la pertenencia o autorización del responsable.
- **RNF-005.** Los efectos diferidos que se aprueben en DA-17 deberán conservar trazabilidad y reintento conforme a las reglas constitucionales; este borrador no decide canales ni destinatarios.
- **RNF-006.** La entrega deberá acreditar las reglas de recurso, resolución, aislamiento, privacidad, inmutabilidad y concurrencia con verificaciones reproducibles; este borrador no declara implementado ni verificado el futuro flujo F9.

## Datos personales y privacidad

Se tratan la identidad del jugador sancionado, la del interponente y los responsables de las decisiones, sus fechas, motivos y, si se admite, la documentación justificativa. Los textos pueden contener información personal sensible y se limitan a la finalidad de tramitar y auditar el caso.

El acceso privado requiere las nuevas facultades de DA-2. La presentación se limita a miembros autorizados que identifican al equipo o jugador representado (DA-1); esa representación no otorga acceso propio al representado. La eventual intervención de plataforma sigue pendiente de DA-8. No se presupone que todo miembro pueda leer la evidencia ni que el jugador tenga acceso por disponer de una ficha deportiva. Las comunicaciones y sus destinatarios requieren DA-17; el contenido justificativo y sus límites, DA-18. Nada de ello se publica ni se incorpora a registros operativos generales que permitan eludir esos accesos.

## Casos límite

1. **Partido próximo con recurso pendiente:** no hay efecto suspensivo ni medida provisional por el recurso (DA-5). La sanción sigue bloqueando el cierre cuando sea aplicable y tenga partidos pendientes; el momento de efecto de una resolución sigue pendiente de DA-15 y los controles adicionales de alineación, de DA-16.
2. **Sanción parcialmente o totalmente cumplida:** los partidos cumplidos siguen siendo hechos; admisibilidad y consecuencias sobre el saldo pendientes de DA-9 y DA-13.
3. **Tarjeta atribuida al jugador equivocado o inexistente:** corregir el evento confirmado exige la spec 033; F9 no lo elimina ni lo reasigna.
4. **Resolución F9 y rectificación simultáneas:** puede cambiar la sanción a revisar o nacer otra con procedencia versionada. No se supone que la resolución anterior se traslade a la nueva; tratamiento en DA-10.
5. **Sanción ya anulada que reaparece por rectificación:** la spec 033 crea una nueva, no reactiva la anterior. La revisión de una resolución administrativa previa queda pendiente de DA-10.
6. **Jugador ausente por una sanción luego anulada:** su ausencia no se convierte retroactivamente en participación, ni se cambia automáticamente el resultado del partido (DA-11).
7. **Torneo archivado:** conservar el historial no decide si puede abrirse un recurso o dictarse una resolución; DA-12. La rectificación de actas sigue las restricciones de la spec 033.
8. **Dos recursos o decisiones sobre la misma sanción:** no se duplican efectos por reintento; admisión de recursos paralelos, retirada y revisión de decisiones en DA-14.
9. **Responsable que pierde permiso o membresía:** se conserva su atribución histórica; no se deduce que pueda continuar actuando con autorización caducada.
10. **Sanción de ámbito organizativo y partido de otro torneo de la misma organización:** el ámbito actual no debe confundirse con aislamiento entre organizaciones; una resolución F9 no puede cambiarlo (DA-4). La admisión de recursos en cada ámbito sigue pendiente de DA-13.
11. **Referencia a sanción, jugador, recurso o acta de otra organización:** no se vincula ni revela el expediente ajeno.
12. **Dato histórico `appealed`:** su existencia no habilita efecto suspensivo en F9 (DA-5). La correspondencia entre los datos previos y el nuevo procedimiento deberá aclararse en DA-14, sin presumir recursos ni decisiones administrativas inexistentes.
13. **Miembro con facultades de presentación y resolución:** la asignación por defecto no autoriza ni prohíbe por sí sola resolver su propio recurso; esa regla sigue pendiente de DA-3.

## Fuera de alcance

- Editar o borrar actas confirmadas, sus versiones históricas o resultados; corregirlos por una vía distinta de la spec 033.
- Reescribir cumplimientos consumados, fabricar participaciones pasadas, repetir partidos o modificar automáticamente partidos ya disputados para compensar una sanción.
- Editar versiones de torneo publicadas o cambiar sus reglas disciplinarias mediante una resolución individual.
- Exponer sanciones, suspensiones o expedientes en consultas públicas.
- Presentación y acceso propios de delegados externos o de jugador/tutor; la presentación corresponde a miembros autorizados que registran a quién representan.
- Aumentar los partidos de sanción o cambiar su ámbito mediante una resolución F9.
- Efecto suspensivo y medidas provisionales de suspensión de la sanción durante la apelación.
- Definir en este borrador contratos técnicos, pantallas o estructura de almacenamiento; corresponden al plan una vez aclarada y aprobada la spec.
- Implementar F9 o dar por aprobada cualquiera de las recomendaciones de las dudas abiertas.

## Criterios de finalización

DA-1, DA-2, DA-4 y DA-5 están cerradas e incorporadas a los requisitos. La aprobación de la spec completa exige resolver las otras 14 DA y convertir sus respuestas en requisitos verificables, sin recomendaciones tácitamente adoptadas. La futura entrega deberá demostrar, como mínimo:

1. Presentar y tramitar un recurso conserva la sanción y su elegibilidad mientras no exista resolución que las altere; el estado de apelación no crea una excepción.
2. Una resolución autorizada, con responsable, fecha, motivo y decisión, determina y muestra el estado y los efectos resultantes sin perder los anteriores.
3. Una anulación o modificación sin resolución auditada o sin permiso no produce cambios, incluida la actuación excepcional que eventualmente se apruebe.
4. Una corrección de tarjeta u otro contenido confirmado usa la spec 033; el original y sus versiones anteriores no se editan ni se eliminan.
5. Los cumplimientos y la procedencia original o versionada se conservan; se cumplen DA-8 y RF-018 de la spec 033 en su ámbito, incluidos sus límites sobre partidos posteriores.
6. La política que se apruebe para parcialidad, plazos, archivo e interacción entre procedimientos tiene casos normales, límites y de rechazo demostrables; no se admite efecto suspensivo ni medidas provisionales de suspensión por apelar.
7. Ninguna organización consulta, altera o relaciona datos de otra; el público no obtiene ningún campo nuevo ni datos del expediente.
8. Los fallos, reintentos y decisiones concurrentes no generan efectos parciales, duplicados ni decisiones vigentes incompatibles.
9. La documentación del producto y las verificaciones de aceptación reflejan las decisiones aprobadas; no se presenta el borrador como funcionalidad disponible.
10. Solo un miembro con permiso presenta, dejando constancia del equipo o jugador representado; delegados externos y jugador/tutor no adquieren acceso propio por esa representación.
11. Consulta, presentación y resolución requieren facultades nuevas y separadas, asignadas por defecto a dueño y administrador; los permisos existentes no las conceden y la separación de personas se verifica según la futura respuesta a DA-3.
12. Solo se permiten mantener, anular o reducir los partidos de sanción; aumentar o cambiar el ámbito se rechaza sin alterar la sanción ni el acta.

## Dudas abiertas

### Decisiones cerradas

| Código | Decisión del usuario (2026-11-12) | Requisitos y alcance |
|---|---|---|
| **DA-1** | Solo miembros de la organización con permiso presentan la apelación, registrando en nombre de qué equipo o jugador actúan. Delegados externos y jugador/tutor quedan fuera de alcance. | RF-002 y RF-018; la representación no concede acceso propio. |
| **DA-2** | Facultades nuevas y separadas para consultar, presentar y resolver apelaciones/resoluciones, asignadas por defecto a dueño y administrador; ninguna se hereda de permisos existentes. | RF-006 y RF-019; no resuelve la separación de personas de DA-3 ni la excepción de plataforma de DA-8. |
| **DA-4** | La resolución puede mantener, anular o reducir los partidos de sanción; aumentar o cambiar el ámbito queda fuera de alcance. | RF-020 y definición de modificación administrativa; efectos sobre cumplimientos pendientes de DA-9. |
| **DA-5** | Sin efecto suspensivo: presentar la apelación nunca suspende ni altera por sí mismo la sanción, que sigue bloqueando conforme a las comprobaciones actuales hasta una resolución aplicable. | RF-003 y caso límite 1; no se admiten medidas provisionales de suspensión por el recurso. |

### Pendientes

Ordenadas por impacto en autorización, efectos disciplinarios e integridad, conservando su numeración. Cada recomendación pendiente es una propuesta para clarificación, no un valor por defecto.

### DA-3. [NECESITA ACLARACIÓN] ¿Debe resolver otra persona distinta de quien interpone o propone?
- **Opciones:** A) misma persona si tiene ambos permisos; B) otra persona; C) órgano con varias personas y reglas de decisión.
- **Recomendación:** B, sin excepciones por acumular roles. La separación exigida para actas rectificativas sigue siendo obligatoria; no se da por extendida automáticamente a todo F9.
- **Límite ya decidido:** DA-2 asigna ambas facultades por defecto a dueño y administrador, pero no responde si una misma persona puede ejercerlas en su propio expediente.

### DA-6. [NECESITA ACLARACIÓN] ¿Puede dictarse una resolución administrativa sin apelación previa?
- **Opciones:** A) solo se resuelve un recurso existente; B) también se permite iniciativa administrativa motivada y auditada, con igual control de permisos y separación que se apruebe.
- **Recomendación:** B, diferenciando esa iniciativa de una apelación y sin fabricar un recurso ficticio para justificarla.
- **Límite ya decidido:** tanto si se exige recurso como si se admite iniciativa administrativa, se necesitan las nuevas facultades de DA-2 y solo se permiten las decisiones de DA-4; no habilita medidas suspensivas excluidas por DA-5. La separación personal sigue pendiente de DA-3.

### DA-7. [NECESITA ACLARACIÓN] ¿Qué plazo existe para apelar y desde qué hecho se cuenta?
- **Opciones:** A) sin caducidad de presentación; B) plazo desde la creación de la sanción; C) plazo desde su notificación acreditada. Para B/C faltan duración, unidad, referencia temporal y tratamiento de notificaciones fallidas.
- **Recomendación:** A hasta que exista una política de notificación acreditada; no inventar un plazo ni suponer que la creación equivale al conocimiento por el afectado.

### DA-8. [NECESITA ACLARACIÓN] ¿Puede intervenir excepcionalmente un administrador de plataforma?
- **Opciones:** A) ninguna decisión F9 desde plataforma; B) autorización expresa del dueño para un expediente concreto, revocable, limitada y auditada, sin edición directa del acta; C) otro mandato excepcional explícito por definir dentro de los límites constitucionales.
- **Recomendación:** B si se confirma la necesidad operativa, con los límites de separación y autorización que se aprueben; no reutilizar implícitamente una autorización de la spec 033 ni conceder acceso general por ser administrador de plataforma.
- **Límite ya decidido:** esta duda no habilita presentación por plataforma al margen de la membresía y el permiso exigidos en DA-1, ni amplía el catálogo de decisiones de DA-4. La eventual excepción para decidir sigue sin aprobarse.

### DA-9. [NECESITA ACLARACIÓN] ¿Cómo afectan reducción o anulación a sanciones parcial o totalmente cumplidas?
- **Opciones:** A) solo efecto sobre lo pendiente, conservando todos los cumplimientos; B) permitir también revisar sanciones ya cumplidas con efecto declarativo; C) reconocer además crédito futuro mediante una decisión específica, sin borrar hechos anteriores.
- **Recomendación:** A y B, sin crédito transferible automático. Definir expresamente el saldo cuando la duración resultante es menor o igual a lo ya cumplido; no devolver partidos consumados ni trasladar cumplimientos entre sanciones por defecto.

### DA-10. [NECESITA ACLARACIÓN] ¿Cómo se coordina una apelación o resolución con una rectificación de acta?
- **Opciones:** A) impedir decisiones mientras esté pendiente el otro procedimiento; B) permitir tramitación paralela y revalidar la sanción y su procedencia antes de decidir; C) cerrar o exigir nueva presentación si la rectificación sustituye la sanción.
- **Recomendación:** B, con revisión expresa si cambia el objeto o una rectificación posterior vuelve a derivar una sanción administrativamente anulada o modificada. No trasladar la decisión a otra sanción ni dejar que un recálculo la deje sin efecto silenciosamente. Concretar cuándo procede C y cómo se informa al interponente.

### DA-11. [NECESITA ACLARACIÓN] ¿Qué tratamiento tiene el perjuicio competitivo ya producido?
- **Opciones:** A) registrar el impacto manteniendo lo jugado, sin procedimiento adicional; B) abrir un procedimiento auditado que solo pueda mantener lo jugado; C) estudiar otras medidas futuras mediante una propuesta específica compatible con la constitución.
- **Recomendación:** B, aclarando si puede utilizarse el procedimiento de la spec 033 o requiere uno propio. No decidir aquí una reutilización ni autorizar repetición, cambios de resultados o de alineaciones ya publicadas.

### DA-12. [NECESITA ACLARACIÓN] ¿Qué se permite en torneos archivados?
- **Opciones:** A) solo consulta histórica; B) admitir recursos y resoluciones declarativas sin efecto deportivo futuro; C) admitir también efectos pendientes sobre sanciones que siguen vigentes en la organización.
- **Recomendación:** C si la sanción sigue afectando a la elegibilidad actual, sin reabrir el torneo ni modificar lo disputado; concretar la admisión de recursos sobre sanciones agotadas. La prohibición de rectificar actas de versiones archivadas de la spec 033 no cambia.

### DA-13. [NECESITA ACLARACIÓN] ¿Qué sanciones son recurribles por origen, ámbito y estado?
- **Opciones:** A) solo sanciones activas derivadas de actas; B) también las de origen administrativo o regla de competición, en ambos ámbitos; C) también sanciones cumplidas o anuladas para revisión histórica, distinguiendo los efectos posibles.
- **Recomendación:** B y revisión declarativa de las cumplidas según DA-9, sin reapertura automática de las anuladas. Definir el tratamiento de datos históricos `appealed` y la admisión por origen/estado, sin reabrir la legitimación de DA-1 ni permitir el cambio de ámbito excluido por DA-4.

### DA-14. [NECESITA ACLARACIÓN] ¿Cuál es el ciclo del recurso y de la revisión de decisiones?
- **Opciones:** A) un recurso abierto por sanción, con retirada y resolución definitiva; B) varios recursos coordinados; C) nueva instancia o resolución correctora vinculada a la anterior. Falta fijar estados, transiciones, admisión/inadmisión y tratamiento de registros históricos sin expediente.
- **Recomendación:** A, y C solo como nueva decisión auditada si se autoriza revisar lo resuelto; conservar cada antecedente. No convertir un antiguo estado `appealed` en prueba de una apelación inexistente ni en habilitación de efecto suspensivo. Las transiciones no pueden crear medidas provisionales excluidas por DA-5, decisiones fuera del catálogo de DA-4 ni facultades heredadas contra DA-2.

### DA-15. [NECESITA ACLARACIÓN] ¿Desde cuándo rige una resolución y qué ocurre con partidos comenzados?
- **Opciones:** A) desde la decisión, incluso durante un partido en curso sin reescribir lo ya ocurrido; B) desde el siguiente partido no comenzado; C) fecha futura explícita con reglas de aplicación por definir.
- **Recomendación:** B para cambios de elegibilidad, con fecha de decisión y momento de efecto diferenciados; concretar la concurrencia con el comienzo y el cierre del partido. La regla ya aprobada para sanciones nuevas de la spec 033 se mantiene en su propio ámbito.
- **Límite ya decidido:** se aclara el efecto de mantener, anular o reducir mediante resolución, no una suspensión provisional durante el recurso, excluida por DA-5.

### DA-16. [NECESITA ACLARACIÓN] ¿Dónde se informa o bloquea una alineación incompatible con una suspensión?
- **Opciones:** A) mantener la comprobación actual al cerrar el acta; B) añadir aviso privado al preparar la convocatoria y revalidar al cerrar; C) impedir además guardar o publicar la alineación incompatible, definiendo qué ocurre si la sanción cambia después de guardarla.
- **Recomendación:** B, sin levantar el control final ni modificar alineaciones automáticamente. C supone un bloqueo nuevo, no un comportamiento actual demostrado, y requiere aprobación explícita.

### DA-17. [NECESITA ACLARACIÓN] ¿Qué avisos se registran y envían, a quién y por qué canales?
- **Opciones:** A) solo consulta privada del historial; B) avisos privados al interponente y a responsables autorizados de la decisión; C) también al jugador o representantes legitimados, por canales que se definan.
- **Recomendación:** B, con registro y reintento de avisos, contenido mínimo y acceso autorizado al expediente; concretar correo u otros canales y destinatarios antes de implementarlos. No emitir datos disciplinarios en canales públicos ni heredar los destinatarios de la spec 033.
- **Límite ya decidido:** los posibles destinatarios de un aviso no adquieren por recibirlo el acceso propio al procedimiento excluido por DA-1 ni las facultades de DA-2.

### DA-18. [NECESITA ACLARACIÓN] ¿Qué documentación justificativa admite o exige el procedimiento?
- **Opciones:** A) motivo obligatorio sin evidencia adicional; B) motivo y texto/referencias verificables, con obligatoriedad y límites explícitos por determinar; C) también archivos, definiendo acceso, límites y tratamiento de datos personales.
- **Recomendación:** B, inicialmente con referencias adicionales opcionales y sin archivos; la evidencia exigida por la spec 033 para rectificar un acta no se convierte por analogía en una exigencia idéntica para toda apelación.
