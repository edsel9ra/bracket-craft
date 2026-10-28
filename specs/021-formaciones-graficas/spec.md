# Spec 021 — Formaciones gráficas en la consulta pública

Estado: implementada

## Contexto y objetivo

La consulta pública ya muestra la formación táctica publicada de un equipo (campo gráfico cuando ambos equipos la tienen) y la planilla cuando no la tiene, pero el visitante no distingue con claridad entre una **formación táctica** y una **planilla** de convocados sin posiciones, y las fotos solo aparecen dentro de las alineaciones. Esta spec (segunda de tres) cierra la presentación gráfica y la distinción entre ambas nociones, sin publicar nada que no esté ya publicado, salvo un campo aditivo mínimo (número de segmento) necesario para etiquetar la formación.

**Objetivo:** que el público vea la formación de cada equipo de forma independiente, con un gráfico claro que no se confunda con una lista de jugadores, y entienda qué representa, sin ampliar lo público más allá de lo mínimo necesario.

### Comportamiento actual verificado

| # | Hecho verificado |
|---|---|
| 1 | La alineación pública de un equipo en un partido es: (a) la **formación táctica** (código del catálogo de cuatro formaciones y posición de cada titular) **solo si se publicó explícitamente** desde el Workspace; (b) si el equipo **no tiene** formación táctica para ese partido, la **planilla** (titulares y suplentes, sin posiciones); (c) si existe una formación táctica **sin publicar**, no se publica ni la formación ni la planilla de ese equipo. De varias formaciones publicadas por segmento se publica la **última** (por `published_at`, luego `segment_number`, luego `id`). |
| 2 | La pantalla dibuja el campo con las dos formaciones **solo si ambos equipos** tienen formación y todos sus titulares tienen posición; en otro caso muestra listas. Los suplentes van en lista. |
| 3 | La identidad del portero solo consta como la **posición `GK` dentro de una formación táctica** (por segmento y equipo). La planilla no tiene posiciones, los jugadores no tienen posición habitual y una sustitución no registra la posición del jugador que entra. |
| 4 | El catálogo cerrado de formaciones es `4-3-3`, `4-4-2`, `3-5-2` y `4-2-3-1`. El formato de juego (`5v5`, `7v7`, `9v9`, `11v11`) es declarativo y no deriva ni acota las formaciones ni los límites de plantilla. |
| 5 | La formación solo es pública después de publicarse explícitamente desde el Workspace. Las versiones de torneo son inmutables una vez publicadas. |
| 6 | La vista pública de alineaciones (`v_public_match_lineups`) selecciona la última formación publicada por `(match_id, team_id)` y expone `segment_id`, pero **no** `segment_number` ni el motivo de interrupción. |

## Dirección visual (guía no funcional para el implementer)

Esta sección no añade requisitos funcionales: fija el criterio de diseño que el implementer debe seguir para la representación gráfica, derivado de la inspiración visual aportada por el propietario del producto. No cambia ningún RF ni RNF.

### Paleta y estilo
- Estética deportiva moderna y limpia. Paleta principal: azul noche o grafito oscuro, azul eléctrico como acento, verde para el terreno de juego, líneas blancas y grises neutros. Los colores propios del equipo se respetan cuando existan.
- Tipografía legible, etiquetas compactas, bordes discretos y sombras moderadas. Evitar efectos tridimensionales excesivos o decoraciones que reduzcan la lectura.

### Composición
1. **Cabecera del equipo:** escudo, nombre, esquema táctico y estado de la alineación publicada.
2. **Campo táctico:** elemento principal, con dimensiones proporcionales, líneas claramente visibles y posiciones de jugadores calculadas a partir de la formación registrada.
3. **Representación del jugador:** fotografía autorizada, avatar alternativo o camiseta estilizada; nombre o apellido identificable, dorsal y posición cuando estén disponibles.
4. **Suplentes:** panel diferenciado situado debajo del campo en móviles o lateralmente en pantallas amplias, con fotografía o avatar, nombre y posición.
5. **Entrenador:** bloque secundario opcional con nombre y fotografía cuando exista información disponible.

### Reglas de presentación
- Compatible con todas las formaciones y formatos de juego soportados; no limitada a una sola formación.
- La distribución de los jugadores corresponde a las posiciones de la formación publicada; no se asume un esquema único para todos los equipos.
- Cada equipo muestra de forma independiente su última formación publicada, identificada con su número de segmento.
- Si un equipo no dispone de formación publicada, se presenta su lista de jugadores como alternativa, sin impedir que el rival muestre su propia representación gráfica.
- No se exponen borradores como alineaciones oficiales.
- Evitar superposiciones entre jugadores, etiquetas ilegibles o información duplicada.
- No convertir la pantalla pública en un panel estadístico de videojuego; priorizar la alineación, el reconocimiento de los jugadores y la lectura táctica.

### Fotografías y privacidad
- Fotografías reales únicamente con autorización válida. Formato visual uniforme, imágenes optimizadas y respeto de los controles de acceso del almacenamiento. Sin fotografía autorizada, avatar genérico o camiseta del equipo. La ausencia de fotografía no bloquea la visualización.

### Adaptabilidad y accesibilidad
- Diseño mobile-first, adaptado a escritorio y tableta. Contraste suficiente, nombres legibles, alternativas textuales para las imágenes y controles accesibles. Las posiciones y los datos esenciales no dependen exclusivamente del color.

### Criterio de aceptación visual
La alineación permite identificar el equipo, su esquema táctico, los titulares y los suplentes; respeta las posiciones registradas; mantiene legibilidad en distintos tamaños de pantalla; utiliza fotografías autorizadas o alternativas visuales; y gestiona de forma independiente la formación publicada de cada equipo. La implementación debe integrarse en la arquitectura y los componentes existentes de Bracket Craft, evitando duplicar la lógica de alineaciones o introducir reglas deportivas no aprobadas.

---

## Usuarios

- Aficionado, familiar, jugador o prensa que consulta un torneo **sin cuenta**.
- Administrador de organización y operador, que publican formaciones (no cambian).
- Jugador (o su tutor), cuyos datos personales y foto deben seguir protegidos.

## Roles y visibilidad

- **Público (sin sesión):** ve, de torneos visibles públicamente, la formación **publicada** de cada equipo (campo gráfico o planilla) y las fotos con consentimiento. No ve formaciones sin publicar, documentos, fechas de nacimiento ni edad. No ve la **plantilla inscrita** del equipo.
- **Miembro de organización (incluido observador):** sin cambios; sigue viendo todo lo de su organización en el Workspace.
- **Administrador de organización / operador:** sin cambios; publican o despublican formaciones como hoy. Lo que publican es exactamente lo que el público puede ver, ni más ni menos.
- **Administrador de plataforma:** sin cambios.

## Historias de usuario

- HU-1. Como aficionado, quiero ver la formación de cada equipo en un gráfico y distinguirla de una simple lista de convocados, para saber quién jugó dónde.
- HU-2. Como aficionado, quiero entender a qué momento del partido corresponde el gráfico, para no confundirlo con otra alineación.
- HU-3. Como aficionado, quiero que la formación de un equipo se vea aunque el rival no tenga la suya, para no depender de que ambos la hayan publicado.
- HU-4. Como administrador de organización, quiero que una formación sin publicar nunca aparezca en público, para controlar lo que mi organización muestra.
- HU-5. Como jugador (o tutor), quiero que mi foto solo se vea si lo autoricé, para proteger mi privacidad.

## Definiciones

- **Torneo visible públicamente:** versión publicada, estado publicado, en juego o finalizado, y organización activa.
- **Plantilla inscrita:** lista de jugadores inscritos de un equipo **en el torneo** (con dorsal). No dice quién juega un partido concreto ni dónde. **Nunca se publica** en la consulta pública.
- **Planilla del partido (alineación sin formación):** titulares y suplentes convocados de un equipo en un partido, **sin posiciones**.
- **Formación táctica:** código del catálogo cerrado de formaciones (`4-3-3`, `4-4-2`, `3-5-2`, `4-2-3-1`) más la **posición asignada a cada titular**, guardada por segmento y equipo y **publicada explícitamente**. Es el único dato del que se puede dibujar un campo.
- **Segmento:** ventana de tiempo de un partido, con número consecutivo, minuto de inicio y estado (activo, completado, interrumpido). No es una mitad ni un periodo reglamentario.
- **Portero identificable:** jugador que ocupa la posición `GK` en una formación táctica del equipo en el partido. Sin formación táctica no hay portero identificable.
- **P10 (decisión incorporada):** de varias formaciones tácticas publicadas por un equipo en un mismo partido, se muestra **la última publicada** (por `published_at`, luego `segment_number`, luego `id`), **etiquetada con su número de segmento**, y cada equipo se presenta de forma **independiente** (no se exige que ambos tengan formación para dibujar uno).

## Requisitos funcionales

Todo dato de una organización sigue protegido por el aislamiento entre organizaciones (heredado de la spec 020).

### Presentación y distinción

- **RF-001.** EL SISTEMA distinguirá con una **etiqueta visible** dos presentaciones posibles: **formación táctica** (campo gráfico) y **planilla del partido** (lista sin posiciones), y no presentará una lista como si fuera una formación. La **plantilla inscrita** no se publica ni se presenta; la etiqueta de una lista deja claro que es la planilla del partido, no la plantilla del equipo.
- **RF-002.** CUANDO un equipo tenga formación táctica **publicada** en un partido, EL SISTEMA mostrará un campo con sus titulares en la posición que el catálogo asigna a cada slot ocupado, con el código de la formación visible, y por jugador nombre, dorsal y foto o iniciales.
- **RF-003.** EL SISTEMA mostrará los suplentes en una lista aparte, fuera del campo.
- **RF-004.** SI un equipo solo tiene planilla del partido (sin formación táctica), ENTONCES EL SISTEMA mostrará la lista de titulares y suplentes etiquetada como planilla, sin campo y sin sugerir posiciones.
- **RF-005.** SI un equipo tiene una formación táctica **sin publicar**, ENTONCES EL SISTEMA no mostrará ni la formación ni la planilla de ese equipo ni ningún indicio de que exista.
- **RF-006.** SI algún titular de un equipo carece de posición, su posición no pertenece al catálogo de la formación, `formation_code` es nulo con `position_slot` no nulo, o el número de titulares no coincide con el del catálogo, ENTONCES EL SISTEMA no dibujará a ese equipo en posiciones inventadas y lo presentará como lista.
- **RF-007.** EL SISTEMA indicará de forma visible **a qué segmento corresponde** el gráfico: el **número del segmento** publicado. Este es un campo aditivo mínimo sobre `PublicTeamLineupResponse` (`segment_number`, entero, puede ser nulo para datos heredados), que se añade a la lista cerrada de campos públicos de la spec 020. No se publica el motivo de interrupción ni el minuto de inicio del segmento.
- **RF-008.** CUANDO solo uno de los dos equipos tenga formación táctica publicada, EL SISTEMA mostrará ese equipo en campo y al otro como lista (o lo omitirá si no tiene planilla publicada), de forma independiente; no exigirá que ambos tengan formación para dibujar uno. Si un equipo no tiene ni formación ni planilla publicada, se omite su sección sin estado vacío ni indicio.
- **RF-009.** EL SISTEMA ofrecerá del campo un **equivalente textual** (lista ordenada por línea: portero, defensa, mediocampo, delantera, en el mismo orden que el campo), navegable con teclado, con las posiciones traducidas al idioma activo y sin transmitir información solo por color. Si el equipo se presenta como lista (planilla), el equivalente textual es esa misma lista.
- **RF-010.** EL SISTEMA mantendrá el catálogo cerrado de cuatro formaciones y no derivará formaciones ni límites del formato de juego declarado.
- **RF-011.** EL SISTEMA mostrará, por jugador del campo y de la planilla, su foto si existe consentimiento de imagen y, en caso contrario, sus iniciales (nombre y apellido), sin hueco ni imagen rota.
- **RF-012.** EL SISTEMA **no publicará** la plantilla inscrita del equipo (lista de jugadores inscritos en el torneo) en la consulta pública. Solo las alineaciones de los partidos (formación o planilla).
- **RF-013.** CUANDO un equipo tenga varias formaciones tácticas publicadas en un mismo partido, EL SISTEMA mostrará **la última publicada** (por `published_at`, luego `segment_number`, luego `id`), etiquetada con su número de segmento, según P10. No se ofrecerá navegación a formaciones anteriores en esta spec (candidato a una spec futura).
- **RF-014.** EL SISTEMA no mostrará ninguna formación sin publicar ni ningún indicio de su existencia, ni en el gráfico ni en la lista.

### Cambio de contrato (aditivo)

- **RF-015.** EL SISTEMA añadirá el campo `segment_number` (entero, nullable) a `PublicTeamLineupResponse`. Es un cambio **aditivo**: un cliente que lo ignore conserva su comportamiento. Se añade a la lista cerrada de campos públicos de la spec 020 (RF-015 de esa spec) en el mismo cambio. No se añaden otros campos.

## Requisitos no funcionales

- **RNF-001 (solo lectura y compatibilidad).** La consulta pública no escribe datos. Las respuestas públicas existentes solo cambian de forma **aditiva** (campo `segment_number` nullable). `engine_version` sigue en **2026.1** y el contrato interno de reglas no se toca.
- **RNF-002 (accesibilidad y adaptación).** El campo gráfico tiene equivalente textual y diálogo operable con teclado, con foco restaurado al cerrar; ninguna información depende solo del color; todo texto nuevo existe en español e inglés. En una pantalla de 360 px de ancho la página no desborda horizontalmente.
- **RNF-003 (aislamiento y privilegios).** Toda lectura respeta el aislamiento por organización. Cualquier cambio de esquema es aditivo, migración nueva numerada, verificado sobre volumen limpio y ya migrado.
- **RNF-004 (privacidad en registros).** Ningún registro contiene nombres, fotos ni datos personales por el uso de estas lecturas.
- **RNF-005 (verificación).** La distinción entre formación táctica y planilla se verifica con casos que cubren: ambos con formación completa; uno con formación y otro con planilla; uno con formación incompleta y otro completo; formación sin publicar; titular sin posición; formación con número de titulares distinto al del catálogo; `formation_code` nulo con `position_slot` no nulo; cero titulares; partido de walkover (sin lineup); jugador con consentimiento retirado. Pasan los cinco jobs de CI.
- **RNF-006 (documentación).** El cambio actualiza la documentación afectada y la lista cerrada de campos públicos (spec 020, RF-015).

## Datos personales y privacidad

- **Datos involucrados:** nombre y apellido, dorsal, posición asignada en una formación publicada, foto del jugador (algunos pueden ser menores).
- **Ya público hoy:** nombre, apellido, dorsal y posición de los jugadores que figuran en una alineación publicada; foto solo con consentimiento de imagen.
- **Nuevo con esta spec:** el **número de segmento** de la formación publicada (dato técnico, no personal). Nada más.
- **Nunca público:** documento de identidad, fecha de nacimiento, edad, clave de objeto de la foto, motivo de walkover o de resolución administrativa, sanciones y suspensiones, auditoría, datos de miembros, plantilla inscrita, motivo de interrupción de segmento.
- **Foto:** solo con consentimiento de imagen de la inscripción en ese torneo, como enlace temporal; retirar el consentimiento la oculta en la siguiente consulta.
- **Quién puede ver qué:** el público, solo lo anterior; los miembros de la organización, lo que ya ven; ninguna otra organización ve ni modifica estos datos.

## Casos límite

1. **Formación sin publicar** de un equipo y publicada del rival: el que tiene formación se dibuja; el otro se muestra como lista o se omite, sin indicio de que exista la formación sin publicar (RF-005, RF-008).
2. **Posición faltante o fuera del catálogo** en un titular publicado (dato inconsistente): lista, no campo (RF-006).
3. **`formation_code` nulo con `position_slot` no nulo:** se trata como planilla, sin campo (RF-006).
4. **Número de titulares distinto al del catálogo** (por ejemplo 10 en un `4-3-3`): lista, no campo (RF-006).
5. **Cero titulares** con `formation_code` no nulo: lista, no campo vacío (RF-006).
6. **Solo un equipo con formación publicada:** se dibuja ese equipo; el otro se muestra como lista o se omite (RF-008).
7. **Varios segmentos con formación publicada:** se muestra la última publicada, etiquetada con su número de segmento (RF-013).
8. **Jugador con consentimiento retirado, sin foto cargada o con fallo de firma:** iniciales, nunca imagen rota (RF-011).
9. **Jugador retirado lógicamente** de la plantilla: si aparece en una alineación publicada se muestra con foto o iniciales según consentimiento.
10. **Partido de walkover:** sin lineup publicado; no se muestra botón ni sección de formación.
11. **Equipo completo con formación y rival con formación incompleta:** el completo se dibuja en campo, el incompleto se muestra como lista (RF-006, RF-008).
12. **Pantalla de 360 px:** el campo y las listas no desbordan; las listas se desplazan dentro de su contenedor.

## Fuera de alcance

- Estadísticas de jugadores y equipos y porterías imbatidas: **spec 022**.
- Navegación por fases y acceso público: **spec 020**.
- Editar, publicar o despublicar formaciones desde la consulta pública.
- Navegación a formaciones anteriores de un mismo partido (solo se muestra la última).
- Formaciones fuera del catálogo de cuatro, edición o publicación de formaciones desde la consulta pública, y formaciones derivadas del formato de juego (5v5, 7v7, 9v9).
- Publicar el motivo de interrupción de un segmento, el minuto de inicio o cualquier otro dato de segmento distinto del número.
- API pública documentada para terceros, exportaciones, notificaciones y optimización para buscadores o compartir en redes.

## Dependencias

- **Spec 020 (navegación y acceso público):** base. Esta spec hereda su matriz de acceso y su aislamiento por organización, y amplía la lista cerrada de campos públicos con `segment_number`.
- **Spec 022 (estadísticas y porterías imbatidas):** depende de esta spec para la fuente del portero (posición `GK` en formación publicada).

## Criterios de finalización

La spec está **implementada** cuando:

1. Cada RF aplicable tiene una prueba o evidencia citada y todos los casos límite de su alcance tienen un caso propio.
2. Un torneo con un equipo con formación publicada y otro sin ella muestra el primero en campo y el segundo como lista o lo omite, sin indicio de formación sin publicar (RF-005, RF-008).
3. La distinción entre formación táctica y planilla del partido es visible y verificable en la interfaz (RF-001).
4. El gráfico tiene equivalente textual navegable con teclado y sin información solo por color (RF-009).
5. El campo `segment_number` se publica como aditivo y aparece en la lista cerrada de campos públicos (RF-007, RF-015).
6. Una verificación automática enumera los campos de cada respuesta pública y falla ante un campo fuera de la lista cerrada (heredado de la spec 020, actualizado).
7. Los cinco jobs de CI pasan.
8. La documentación refleja los contratos que cambian.
9. Todo lo no ejecutado se declara como tal.

## Dudas abiertas

Ninguna. La decisión P10 se incorporó a las definiciones y a los RF correspondientes (RF-007, RF-008, RF-013). Las observaciones del reviewer (campos públicos no declarados, P10 no definida, plantilla inscrita visible vs. no publicada, mecanismo de formaciones anteriores, «línea», «vacío») se resolvieron en esta revisión.
