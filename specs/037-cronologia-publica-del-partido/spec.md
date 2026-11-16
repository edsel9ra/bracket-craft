# Spec 037 — Cronología pública del partido

Estado: implementada y aceptada (2026-11-15); spec cerrada

Fecha: 2026-11-15. Corresponde a F13 del informe de funciones adicionales (`docs/informe-funciones-adicionales.md`, §3 P3 y orden revisado §6.6, punto 4: F8 → F1 → F13). F8 (spec 035) y F1 (spec 036) están implementadas y aceptadas. Fase Spec abierta: DA-1 (b), DA-2 (a), DA-3 (a) y DA-4 (a) cerradas por el usuario el 2026-11-15; Spec aprobada expresamente por el usuario el 2026-11-15 («Apruebo la spec 037»).

## Contexto y objetivo

La consulta pública muestra el resultado de cada partido confirmado, su alineación publicada (021) y las estadísticas agregadas del torneo (022), pero no lo que ocurrió dentro del encuentro: quién marcó, en qué minuto y qué tarjetas hubo. La decisión 6.3 del informe fija que, **tras el cierre**, el público recibe «resultado y eventos confirmados; cronología pública autorizada (F13)». La spec 036 dejó esa cronología fuera de su alcance de forma expresa (036 RF-027 y «Fuera de alcance») y la 020 la excluyó como «cronología pública partido a partido».

El objetivo es publicar, para cada partido con acta confirmada de un torneo visible, una **línea de tiempo de solo lectura** con los hechos deportivos confirmados que esta spec autorice, en el orden en que ocurrieron. Es una ampliación de la matriz pública de la spec 020 (RF-013–RF-018) con su propia lista cerrada de campos, no una apertura general del acta.

Fuentes y límites: constitución 2.0.0 (§2.3 inmutabilidad y acta rectificativa, §2.5 proyección mínima), matriz 020 y sus ampliaciones (021, 022, 036 RF-021), catálogo de eventos 015, doble amarilla 018, cierre 017, rectificación 033 y partido en vivo 036.

**Compatibilidad constitucional:** no se propone enmienda. La cronología se construye solo con lo confirmado: nunca con borradores F1, nunca editando un acta y, si hay rectificación, solo con la versión vigente (033 RF-021). Cumple §2.5 porque no añade documentos, fechas de nacimiento, edad ni fotos fuera del consentimiento vigente. Amplía la matriz pública con una lista cerrada que esta spec declara.

## Decisiones cerradas — ronda 1 (2026-11-15)

| Decisión | Respuesta del usuario | Comportamiento adoptado |
|---|---|---|
| DA-1 | (b) | Se publican goles (gol, gol de penal, autogol), tarjetas (amarilla, roja) y sustituciones (sale/entra). Las faltas informativas no se publican. |
| DA-2 | (a) | De cada jugador solo se publican nombre y apellido; ni dorsal ni foto. |
| DA-3 | (a) | La roja se muestra como «roja directa» o «roja por doble amarilla» según la clasificación del acta (015/018), sin publicar la sanción derivada. |
| DA-4 | (a) | Lista única ordenada, con un separador por segmento solo cuando el partido tiene más de uno. |

## Usuarios

- Público (espectador, familiar, jugador, prensa local): quiere saber cómo se desarrolló un partido ya cerrado sin necesidad de sesión.
- Organizador de la competición: quiere que su torneo ofrezca esa información sin trabajo adicional, a partir del acta que ya confirma.
- Administrador de plataforma: sin cambios; esta funcionalidad no le concede atribuciones nuevas.

## Roles y visibilidad

- **Público:** consulta, sin sesión, la cronología de los partidos con acta confirmada de un torneo visible públicamente. Ve solo los campos de la lista cerrada de esta spec.
- **Miembro de organización / administrador de organización:** no cambian sus lecturas ni permisos. La cronología se alimenta del acta que ya cierran con los permisos vigentes; no se añade ninguna escritura ni permiso.
- **Administrador de plataforma:** sin cambios.
- **Aislamiento:** cada cronología pertenece a un único partido de un único torneo; ninguna respuesta mezcla datos de otro torneo ni de otra organización, y ningún dato de otra organización puede verse a través de ella.

## Historias de usuario

- HU-1. Como espectador, quiero ver en orden los goles, tarjetas y sustituciones de un partido cerrado para entender cómo llegó su resultado.
- HU-2. Como espectador, quiero distinguir el tipo de cada hecho (gol, penal, autogol, amarilla, roja directa o por doble amarilla, sustitución) y su minuto, incluido el tiempo añadido, sin depender solo del color.
- HU-3. Como organizador, quiero que la cronología refleje siempre el acta vigente, también tras una rectificación aprobada, sin publicar nada que no esté confirmado.
- HU-4. Como espectador que sigue un partido en vivo, quiero que su cronología aparezca cuando se confirma el acta, sin recargar la página.

## Definiciones

- **Cronología pública:** lista ordenada de hechos confirmados de un partido que esta spec autoriza a publicar. No es el acta completa, ni el borrador F1, ni un historial de versiones.
- **Hecho confirmado:** evento no anulado de la versión vigente del acta de un partido cerrado: la original si no hay rectificación, o la última versión publicada por 033.
- **Partido con acta confirmada:** partido `finished` con resultado deportivo disputado. Un walkover o una resolución administrativa no tienen hechos de juego (017, 016).
- **Minuto público:** minuto del hecho y, si existe, su tiempo añadido, tal como figuran en el acta confirmada (por ejemplo, «45+2'»).
- **Segmento:** ventana operativa del acta de 017, identificada por su número; no es una mitad ni un periodo reglamentario.

## Requisitos funcionales

### Disponibilidad

- **RF-001.** CUANDO un partido de un torneo públicamente visible tenga acta confirmada, EL SISTEMA ofrecerá sin sesión su cronología pública.
- **RF-002.** MIENTRAS un partido esté `scheduled`, `live` o `suspended`, EL SISTEMA no publicará ningún hecho individual de ese partido: lo provisional sigue limitado a la proyección de 036 (estado, marcador provisional y reloj).
- **RF-003.** CUANDO un partido se haya resuelto por walkover o resolución administrativa, EL SISTEMA no ofrecerá hechos de juego y lo indicará con un estado explicativo, sin publicar el motivo de la resolución (020 RF-016).
- **RF-004.** SI un partido está cancelado, o su torneo no es visible públicamente (borrador, sin versión publicada, organización inactiva o inexistente), ENTONCES EL SISTEMA responderá el mismo «no encontrado» que el resto de lecturas públicas (020 RF-014), indistinguible de un partido inexistente.

### Contenido

- **RF-005.** EL SISTEMA construirá la cronología únicamente con hechos confirmados de la versión vigente del acta (033 RF-021); nunca con borradores F1, eventos anulados ni versiones anteriores.
- **RF-006 (DA-1 b).** EL SISTEMA publicará solo hechos de tipo gol, gol de penal, autogol, tarjeta amarilla, tarjeta roja y sustitución; nunca faltas informativas, y nunca la asistencia (015 RF-011, 022 RF-012), sanciones ni suspensiones de jugadores (020 RF-016).
- **RF-007 (DA-2 a).** EL SISTEMA publicará de cada hecho solo: su tipo, su minuto público, el número de segmento, el equipo al que se atribuye y el jugador protagonista, identificado únicamente por su identificador, nombre y apellido, sin dorsal ni foto. Un autogol mostrará además el equipo beneficiado. Una sustitución mostrará el jugador que sale y el jugador que entra, ambos con esos mismos datos.
- **RF-008 (DA-3 a).** EL SISTEMA mostrará cada tarjeta roja como «roja directa» o «roja por doble amarilla» según la clasificación del acta, sin publicar las sanciones que derivan de ella. SI una roja histórica no tiene clasificación en el acta, ENTONCES EL SISTEMA la mostrará solo como «roja», sin inferir su tipo.
- **RF-009.** EL SISTEMA ordenará los hechos por segmento, minuto y tiempo añadido, y desempatará con un criterio estable, de modo que dos consultas con los mismos datos devuelvan el mismo orden. **(DA-4 a)** La cronología es una lista única; CUANDO el partido tenga más de un segmento con hechos o sin ellos, EL SISTEMA mostrará un separador con el número de cada segmento, y con un solo segmento no mostrará separador.
- **RF-010.** EL SISTEMA garantizará que los goles de la cronología (gol, gol de penal y autogol, este último a favor del beneficiado) coinciden con el marcador final publicado del partido (prórroga incluida). La tanda de penales no genera hechos y se muestra solo como el resultado de penales que ya es público.
- **RF-011.** SI un hecho histórico referencia un jugador, equipo o segmento inexistente o de otra organización, ENTONCES EL SISTEMA lo excluirá sin fallar la respuesta, con el mismo criterio que las estadísticas (022 RF-004). SI esa exclusión rompe la coincidencia de RF-010, ENTONCES EL SISTEMA lo indicará con texto en lugar de inventar un hecho.
- **RF-012.** CUANDO un partido tenga acta confirmada pero ningún hecho publicable (por ejemplo, solo faltas informativas o ningún evento), EL SISTEMA mostrará un estado vacío explicativo, distinto de un error de carga.
- **RF-013.** CUANDO el partido esté rectificado, EL SISTEMA mostrará la cronología de la versión vigente junto a la marca de rectificación existente (033 RF-022), sin motivo, evidencia, responsables ni diferencias con versiones anteriores.

### Actualización

- **RF-014.** CUANDO se confirme el acta de un partido o se publique una versión rectificativa, EL SISTEMA reflejará la nueva cronología en las vistas públicas abiertas con la misma señal pública de actualización que ya refresca resultado y clasificación, sin crear un canal ni un evento público nuevo ni transportar hechos individuales por tiempo real.

### Matriz pública

- **RF-015.** EL SISTEMA añadirá a la lista cerrada de campos públicos de 020 RF-015 exactamente los campos de la cronología que esta spec apruebe, y la verificación automática fallará si aparece cualquier otro.
- **RF-016.** EL SISTEMA servirá la cronología con las mismas reglas de la 020: sin sesión, sin cookies, sin escrituras, sin permisos nuevos y sin mezclar torneos ni organizaciones (020 RF-013, RF-017, RF-018).
- **RF-017.** EL SISTEMA documentará en la matriz de acceso del README y en `AGENTS.md`, en el mismo cambio, la ampliación pública y su lista cerrada (020 RF-020).

## Requisitos no funcionales

- **RNF-001 (aislamiento):** las pruebas incluyen dos organizaciones y demuestran que la cronología de una nunca contiene datos de la otra, también ante identificadores cruzados.
- **RNF-002 (accesibilidad e idioma):** la cronología se presenta en español e inglés, se recorre con teclado y lector de pantalla, y el tipo de hecho se identifica con texto o icono con nombre accesible, no solo con color; respeta ambos temas (032) y el sistema de diseño (029).
- **RNF-003 (contrato):** no se cambian los campos ni la semántica de las respuestas públicas existentes; la ampliación es aditiva y no afecta a la proyección de partidos `live` o `suspended` de 036.
- **RNF-004 (coste de lectura):** la cronología de un partido es acotada y no requiere paginación; abrir la vista de un torneo no obliga a cargar la cronología de todos sus partidos.
- **RNF-005 (determinismo):** mismos datos, misma respuesta (RF-009); el acta confirmada es inmutable y la cronología solo cambia al publicarse una rectificación.

## Datos personales y privacidad

- **Datos involucrados:** nombre y apellido del jugador que protagoniza cada hecho publicado y su relación con goles, tarjetas y sustituciones de un partido concreto. Las tablas de 022 ya publican el nombre y los totales de goles y tarjetas por torneo (022 RF-033); la cronología añade el **partido y el minuto** de cada hecho, lo que aumenta el detalle sobre una persona. Por eso los tipos (DA-1) y los datos de identidad (DA-2) se decidieron de forma explícita.
- **Cambio no aditivo declarado (sustituciones):** el jugador que **entra** puede no figurar en ninguna alineación publicada ni en las tablas de 022, porque la sustitución se acredita al que sale. Publicar su nombre amplía el conjunto de personas públicas: se declara aquí y se añade a la matriz de acceso de 020. Solo se publican nombre y apellido de quienes participan en un hecho publicado; la plantilla inscrita sigue sin publicarse.
- **Nunca se publica:** documentos de identidad, fecha de nacimiento, edad, plantilla inscrita, asistencias, sanciones, suspensiones disciplinarias, motivos de walkover o de resolución administrativa, notas de interrupción, auditoría, datos de miembros u organizaciones ni borradores F1.
- **Foto y dorsal:** la cronología no publica ninguno de los dos (DA-2 a), aunque el jugador tenga consentimiento de imagen.
- **Jugador retirado lógicamente:** sus hechos confirmados se conservan en la cronología con nombre y apellido, coherente con 022 RF-034.

## Casos límite

- **CL-1.** Partido sin goles ni tarjetas: estado vacío explicativo (RF-012).
- **CL-2.** Walkover o resolución administrativa: sin hechos de juego, con estado explicativo y sin motivo (RF-003).
- **CL-3.** Partido rectificado que añade, retira o cambia hechos: solo la versión vigente, con marca de rectificación (RF-005, RF-013).
- **CL-4.** Doble amarilla: dos amarillas y la roja «por doble amarilla»; sin publicar la suspensión. Roja histórica sin clasificación: «roja» (RF-008).
- **CL-5.** Autogol: atribuido al autor y a su equipo, con el equipo beneficiado; suma al marcador del beneficiado (RF-007, RF-010).
- **CL-6.** Varios hechos en el mismo minuto y tiempo añadido: orden estable (RF-009).
- **CL-7.** Prórroga y tanda de penales: los goles de prórroga figuran como hechos; la tanda no genera hechos (RF-010).
- **CL-8.** Acta histórica con referencias inválidas: hecho excluido sin error y aviso si el marcador no cuadra (RF-011).
- **CL-9.** Partido en vivo o suspendido: sin hechos individuales hasta el cierre; al confirmarse, la cronología aparece en la vista abierta (RF-002, RF-014).
- **CL-10.** Torneo que deja de ser visible u organización desactivada: «no encontrado» indistinguible (RF-004).
- **CL-11.** Jugador retirado lógicamente o sin consentimiento de imagen: hechos visibles con nombre y apellido, nunca foto (RF-007).
- **CL-12.** Sustitución cuyo jugador que entra no figura en ninguna alineación publicada: se publica su nombre y apellido como parte del hecho (cambio no aditivo declarado).
- **CL-13.** Partido con un solo segmento: lista sin separador; con varios, separador por segmento aunque alguno no tenga hechos (RF-009).
- **CL-14.** Acta con faltas informativas: no aparecen; si son los únicos eventos, estado vacío (RF-006, RF-012).

## Fuera de alcance

- Hechos individuales durante `live` o `suspended`, marcadores en vivo nuevos o estadísticas minuto a minuto.
- Publicar asistencias, sanciones, suspensiones, faltas informativas, dorsales, fotos, notas de interrupción o motivos administrativos.
- Fichas de jugador, históricos entre torneos y comparativas (F16).
- Cambios en el catálogo de eventos (015), en el cierre (017), en la rectificación (033), en las reglas (`engine_version` 2026.1) o en permisos.
- Exportaciones, API pública documentada para terceros, SEO o compartir en redes (F10, F14, F15).
- Notificaciones de cualquier tipo (F6).

## Criterios de finalización

1. DA-1 a DA-4 están cerradas y registradas (2026-11-15) y la spec recibe aprobación expresa antes del Plan.
2. Cada RF y caso límite tiene una prueba o evidencia citada.
3. La verificación automática de la lista cerrada pública incluye los campos nuevos y falla ante cualquier otro; no aparece ningún documento, fecha de nacimiento, edad, dorsal, foto, asistencia, falta informativa ni sanción (RF-006, RF-007, RF-015).
4. Dos organizaciones de prueba demuestran el aislamiento (RNF-001), y un torneo no visible, un partido cancelado o inexistente responden igual (RF-004).
5. Un partido en vivo no publica hechos y, al cerrarse, su cronología aparece en la vista pública abierta (RF-002, RF-014).
6. Un partido rectificado muestra solo la versión vigente con su marca (RF-013).
7. Los cinco jobs de CI pasan y la documentación refleja la matriz ampliada (RF-017).
8. Todo lo no ejecutado se declara como tal.

## Dudas abiertas

Ninguna. DA-1 (b), DA-2 (a), DA-3 (a) y DA-4 (a) se incorporaron a RF-006–RF-009, a «Datos personales y privacidad» y a los casos límite.
