# Spec 038 — Fichas públicas de jugador

Estado: borrador

Fecha: 2026-11-16. Corresponde a F16 del informe de funciones adicionales (`docs/informe-funciones-adicionales.md`, tabla §3 y decisión §6.5; orden revisado §6.6, punto 5). Las specs 033–037 están implementadas y aceptadas. Fase Spec abierta: DA-1–DA-4 pendientes.

## Contexto y objetivo

Hoy el público ve a un jugador solo dentro de un torneo: en la alineación publicada (021), en las tablas de estadísticas (022) y en la cronología del partido (037). No existe una vista que reúna lo que ese jugador ha hecho en los distintos torneos de una misma organización.

El objetivo es ofrecer una **ficha pública de jugador**: una vista de solo lectura con su trayectoria en los torneos visibles de **una sola organización**, construida únicamente con resultados confirmados. La decisión §6.5 del informe la permite como «proyección pública adicional, limitada y autorizada», manteniendo la proyección mínima.

**Definición de «autorizada» (decidida por el usuario el 2026-11-16):** la ficha se apoya en el **consentimiento de imagen** que ya se registra por inscripción en la plantilla (spec 022, RF-007/RF-033). No se crea un consentimiento nuevo.

Fuentes y límites: constitución 2.0.0 (§1.3 privacidad con base y consentimiento explícitos, §2.1 aislamiento, §2.3 inmutabilidad y acta rectificativa, §2.5 proyección mínima), matriz pública 020 (RF-013–RF-018) y sus ampliaciones (021, 022, 036 RF-021, 037), rectificación 033.

**Compatibilidad constitucional:** no se propone enmienda. La ficha no publica documentos, fechas de nacimiento ni edad; la foto sigue sujeta al consentimiento de imagen y a la inscripción vigente; solo usa actas confirmadas y, si hay rectificación, su versión vigente; nunca mezcla organizaciones.

**Cambios no aditivos que esta spec declara:**

1. **Matriz 020, RF-017:** hoy ninguna respuesta pública mezcla datos de más de un torneo. La ficha reúne varios torneos **de la misma organización**; la prohibición entre organizaciones se mantiene intacta.
2. **Alcance del consentimiento de imagen:** hasta ahora solo permitía publicar la foto. Con esta spec también habilita la ficha. Los consentimientos ya otorgados quedan cubiertos desde el despliegue, de modo que el Workspace y el manual deben explicar el nuevo alcance (RF-012).

## Usuarios

- Público (aficionado, familiar, prensa local, el propio jugador): quiere ver la trayectoria de un jugador en la organización sin sesión.
- Administrador de organización y operador: deciden el consentimiento de imagen por inscripción, como hoy.
- Jugador (o su tutor): sus datos personales siguen protegidos y su ficha solo existe con su consentimiento.
- Administrador de plataforma: sin cambios.

## Roles y visibilidad

- **Público (sin sesión):** ve la ficha de un jugador autorizado, con solo los campos de la lista cerrada de esta spec y solo de torneos visibles públicamente de una organización activa.
- **Miembro / administrador de organización / operador:** no cambian sus lecturas ni permisos. Siguen gestionando el consentimiento desde la plantilla; no se añade ninguna escritura ni permiso.
- **Administrador de plataforma:** sin cambios.
- **Aislamiento:** una ficha pertenece a un jugador de una sola organización. Ningún dato de otra organización puede verse ni mezclarse en ella, aunque la misma persona juegue en varias organizaciones.

## Historias de usuario

- HU-1. Como aficionado, quiero abrir la ficha de un jugador desde un torneo público para ver su trayectoria en la organización.
- HU-2. Como jugador (o tutor), quiero que mi ficha solo exista si di mi consentimiento y que desaparezca si lo retiro.
- HU-3. Como administrador de organización, quiero que la ficha muestre solo resultados confirmados y respete las rectificaciones.

## Definiciones

- **Jugador autorizado:** [NECESITA ACLARACIÓN DA-1] jugador cuyo consentimiento de imagen habilita la ficha.
- **Torneo visible:** torneo publicado, en juego o finalizado de una organización activa, igual que en la matriz 020 (RF-014).
- **Trayectoria:** las inscripciones del jugador en los torneos visibles de la organización y sus estadísticas confirmadas en cada uno.

## Requisitos funcionales

- **RF-001.** CUANDO un jugador esté autorizado (DA-1) y tenga al menos una inscripción en un torneo visible de su organización, EL SISTEMA ofrecerá sin sesión su ficha pública.
- **RF-002.** SI el jugador no está autorizado, no tiene inscripciones en torneos visibles, pertenece a una organización inactiva o no existe, ENTONCES EL SISTEMA responderá el mismo «no encontrado», indistinguible entre esos casos y del de cualquier recurso público inexistente.
- **RF-003.** EL SISTEMA incluirá en la ficha solo torneos visibles de la organización del jugador; nunca datos de otra organización (020 RF-017, ampliado según «Cambios no aditivos»).
- **RF-004.** EL SISTEMA calculará las estadísticas de la ficha solo con actas confirmadas y, si hay rectificación, con su versión vigente (033), con las mismas reglas que las tablas de la 022, de modo que el valor de un torneo en la ficha coincide con el de su tabla pública.
- **RF-005.** EL SISTEMA publicará en la ficha solo los campos de una lista cerrada [NECESITA ACLARACIÓN DA-2], y la verificación automática de la 020 (RF-015) fallará ante cualquier otro.
- **RF-006.** EL SISTEMA no publicará nunca en la ficha documento de identidad, fecha de nacimiento, edad, año de referencia de la edad, clave de objeto de la foto, asistencias, faltas, sanciones, suspensiones, motivos de walkover o de resolución administrativa, ni auditoría.
- **RF-007.** EL SISTEMA mostrará la foto solo con consentimiento de imagen, inscripción vigente y foto cargada, igual que la 022 (RF-007, RF-034); si falla la firma, responderá con la foto en nulo.
- **RF-008.** CUANDO se retire el consentimiento que autoriza la ficha, EL SISTEMA dejará de servirla (o de incluir el torneo afectado, según DA-1) en la siguiente lectura, sin caché pública que la prolongue.
- **RF-009.** EL SISTEMA ofrecerá el acceso a la ficha [NECESITA ACLARACIÓN DA-4] solo para jugadores autorizados; para los demás, el nombre sigue apareciendo como hoy, sin enlace.
- **RF-010.** EL SISTEMA ordenará la trayectoria por fecha de inicio del torneo, de la más reciente a la más antigua, con un desempate estable.
- **RF-011.** EL SISTEMA no añadirá ninguna escritura, permiso, cookie ni dependencia de sesión a la consulta pública (020 RF-018).
- **RF-012.** EL SISTEMA indicará, junto al control del consentimiento de imagen en la plantilla del Workspace, que ese consentimiento también publica la ficha del jugador; el manual de usuario lo documentará.
- **RF-013.** [NECESITA ACLARACIÓN DA-3] Goleadores históricos y comparativas.

## Requisitos no funcionales

- **RNF-001 (rendimiento acotado).** La ficha está acotada por un tope de torneos y su número de consultas a la base no crece con el número de torneos ni de partidos. Las fotos se firman en un solo lote, fuera de la transacción de lectura.
- **RNF-002 (accesibilidad).** La ficha es navegable con teclado, tiene nombres accesibles y cumple el contraste de los temas oscuro y claro (029/032).
- **RNF-003 (idiomas y diseño).** Textos en español e inglés; usa los tokens y componentes del sistema de diseño.
- **RNF-004 (privacidad en registros).** Ningún registro contiene nombres, fotos, claves de objeto ni datos personales por estas lecturas.
- **RNF-005 (verificación).** La lista cerrada, el «no encontrado» indistinguible y el aislamiento entre dos organizaciones se verifican con pruebas automáticas. Pasan los cinco jobs de CI.

## Datos personales y privacidad

- **Datos involucrados:** nombre y apellido, foto, equipo y estadísticas confirmadas de jugadores, algunos menores de edad.
- **Ya público hoy:** nombre y apellido en estadísticas (022 RF-033) y cronología (037); dorsal y posición en alineaciones publicadas; foto solo con consentimiento.
- **Nuevo:** la reunión de esos datos de varios torneos de una organización en una sola vista, solo para jugadores autorizados.
- **Nunca público:** lo listado en RF-006.
- **Base:** el consentimiento de imagen de la inscripción, con el alcance ampliado declarado en «Cambios no aditivos». Retirarlo retira la ficha (RF-008).

## Casos límite

- **CL-1.** Jugador con consentimiento en un torneo y sin él en otro: depende de DA-1.
- **CL-2.** Jugador retirado lógicamente de una plantilla: su histórico de ese torneo cuenta como en la 022 (RF-034), sin foto de esa inscripción.
- **CL-3.** Torneo despublicado u organización desactivada: desaparece de la ficha; si no queda ninguno, «no encontrado» (RF-002).
- **CL-4.** La misma persona inscrita en dos organizaciones: son fichas distintas, sin enlace entre ellas (RF-003).
- **CL-5.** Acta rectificada: la ficha refleja la versión vigente (RF-004).
- **CL-6.** Torneo en juego: solo cuentan los partidos con acta confirmada; los borradores F1 nunca (RF-004).
- **CL-7.** Jugador autorizado sin partidos jugados: la ficha muestra sus inscripciones con estadísticas en cero.
- **CL-8.** Fallo de firma de la foto: iniciales, sin imagen rota (RF-007).

## Fuera de alcance

- Traspasos entre equipos (§3.2 de la constitución).
- Fichas que mezclen organizaciones.
- Cualquier escritura desde la consulta pública, incluido gestionar el consentimiento.
- Un consentimiento nuevo o distinto del de imagen.
- Buscador global de jugadores entre organizaciones.

## Criterios de finalización

1. Un jugador autorizado tiene ficha pública con solo los campos de la lista cerrada (RF-001, RF-005).
2. Un jugador no autorizado, inexistente o de una organización inactiva da el mismo «no encontrado» (RF-002).
3. Retirar el consentimiento retira la ficha en la siguiente lectura (RF-008).
4. Las cifras de cada torneo coinciden con sus tablas públicas de la 022 (RF-004).
5. Ninguna respuesta mezcla organizaciones (RF-003, RNF-005).
6. El Workspace y el manual explican el nuevo alcance del consentimiento (RF-012).
7. Pasan los cinco jobs de CI y la documentación (README, AGENTS, manual, matriz 020) es coherente.

## Dudas abiertas

- [NECESITA ACLARACIÓN DA-1] Qué consentimiento autoriza la ficha cuando el jugador tiene varias inscripciones.
- [NECESITA ACLARACIÓN DA-2] Qué campos muestra la ficha.
- [NECESITA ACLARACIÓN DA-3] Si entran goleadores históricos y comparativas.
- [NECESITA ACLARACIÓN DA-4] Desde dónde se accede a la ficha.
