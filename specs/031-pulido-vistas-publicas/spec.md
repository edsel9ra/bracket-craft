# Spec 031 — Pulido de las vistas públicas

Estado: implementada

Implementación: PR A [#50](https://github.com/edsel9ra/bracket-craft/pull/50), PR B [#51](https://github.com/edsel9ra/bracket-craft/pull/51) fusionados; PR C identificado por la rama `devin/1794419368-spec-031-verificacion-cierre` (sin número mientras no se abra, por instrucción del usuario). Evidencia RF por RF, criterios de finalización y constitución §4 en [verificacion.md](verificacion.md). Implementada no significa autorizada para fusionar: el gate E2E de CI del PR C y su revisión externa quedan pendientes hasta abrir el PR.

Aprobada por el usuario el 2026-11-11. Se conserva la numeración de respuestas de su aprobación: D1 diagrama, D2 seguridad de conectores, D3 nombres y D4 tablas. En el borrador, nombres/estadísticas/seguridad figuraban como D2/D3/D4 respectivamente; cambia la referencia, no el significado de las respuestas.

## Contexto y objetivo

Opción 4 del informe inicial: facilitar la consulta pública de torneos, resultados, llaves y estadísticas sin cambiar los datos publicados ni las reglas deportivas. La base visual de la 029 se conserva; esta propuesta trata de jerarquía, legibilidad, relaciones entre partidos y acceso a la información, no de otra identidad visual.

Auditoría local del 2026-11-11, desde main actualizado (`620669cc`), sin sesión en las vistas públicas, a 1440×900 y 390×844. Se revisaron portada, detalle, llave, clasificación, lista de partidos, estadísticas de jugadores/equipos, filtro de fase, formación gráfica y equivalente textual. La Copa Demo aporta la eliminatoria de ocho equipos y las formaciones; una liga de prueba preexistente aporta una clasificación no vacía. Se crearon y retiraron cuatro torneos temporales con 4, 8, 16 y 5 equipos, generados por el producto. El de cinco equipos admite tres byes; no se simula que el producto rechace los impares.

Hay 32 auditorías axe: 30 sobre respuestas reales y dos sobre una simulación de respuesta pública de penales, una por tamaño de viewport. Los penales se simularon solo en el navegador, con los campos del contrato vigente; no se modificó un resultado cerrado. El W.O. sí se creó mediante el cierre real de un partido temporal: 3–0, ganador resaltado. Las capturas y mediciones se conservan fuera del repositorio en `/home/ubuntu/ui-audit/031-before/`, con resultados en `audit.json` y `extra.json`. Los cuatro fixtures temporales, sus 33 equipos, partidos y slots fueron retirados; se conservaron demo y fixtures anteriores.

### Línea base medida

Las diferencias Y son el valor absoluto entre el centro de un partido destino y el promedio de los centros de sus partidos de origen reales. Se contrastaron con las relaciones guardadas del torneo exclusivamente para la auditoría: esa información no se presume disponible en la consulta pública. Los anchos se expresan como contenido desplazable / ancho visible de la región.

| Superficie | 1440×900 | 390×844 | Hallazgo |
|---|---|---|---|
| Llave demo, 8 equipos | 4/2/1 partidos; diferencia Y máxima 343,5 px | Misma diferencia; 647/320 px | Cero conectores; la final se titula «Ronda 3» aunque su código público es FINAL. |
| Llave temporal, 4 equipos | 2/1 partidos; diferencia Y 77,5 px | 506/320 px; misma diferencia | Las rondas empiezan a la misma altura, no en el centro de sus orígenes. |
| Llave temporal, 8 equipos | 4/2/1; diferencia Y máxima 232,5 px | 767/320 px | El alto variable de las tarjetas cambia el desalineamiento. |
| Llave temporal, 16 equipos | 8/4/2/1; diferencia Y máxima 542,5 px | 1086/320 px | La final se titula «Ronda 4»; gran zona vacía bajo las rondas posteriores. |
| Llave temporal, 5 equipos | 2/1/1 partidos, 3 byes; diferencia Y máxima 77,5 px | 767/320 px | No se explica el pase libre; no existen partidos ficticios para llenar los huecos. |
| Estadísticas de jugadores | 8 columnas completas, 1096/1096 px | 767/278 px; completas solo Posición y Jugador | Goles queda fuera de la vista inicial. Identidad sticky y pista de scroll ya funcionan. |
| Estadísticas de equipos | 6 columnas completas, 1096/1096 px | 524/278 px; completas Posición, Equipos y GF | GC, porterías imbatidas y JL requieren scroll. Identidad sticky funciona. |
| Clasificación de liga | 11 columnas, 1138/1138 px | 760/320 px; completa solo la posición | Sin pista ni columna de identidad fija; axe señala scrollable-region-focusable. |
| Portada | Hero 680,9 px; tarjetas desde Y=876,9 | Hero 951,4 px; tarjetas desde Y=1130,4 | La primera pantalla móvil solo ofrece registro/documentación, no acceso directo a los torneos. |
| Detalle demo | Hero 474,9 px; selector de fase desde Y=819,9 | Hero 393,1 px; selector desde Y=1117,1 | La lista de equipos precede al acceso a los resultados. |
| Formación publicada | Diálogo 1080×868 px | Diálogo 370×824 px | Sin overflow horizontal de página; equivalente textual, cierre y retorno de foco disponibles. |

En las vistas medidas no hay overflow horizontal del documento: el exceso de ancho queda en las regiones internas. Los partidos pendientes conservan una marca neutra y «Por definir». Los ganadores conocidos se destacan; el W.O. real muestra resolución y 3–0. Los penales simulados muestran 1–1 y tanda 5–4, sin confundirse con el marcador principal. La portada contiene además un marcador ilustrativo fijo RIV 2–1 ATL, minuto 78:42, rotulado «En vivo» sin ser un dato de la competición consultada.

Axe detectó una única incidencia de aplicación, `scrollable-region-focusable`, en la clasificación móvil. Aparece en dos ejecuciones porque clasificación y lista de partidos comparten la misma página y tabla. Las otras 30 ejecuciones no dieron violaciones; se ocultó DevTools, sin excluir reglas de la aplicación. No se realizó una certificación con lector de pantalla ni dispositivos físicos.

### Los supuestos pendientes de la 022

T15 y T16 no siguen abiertos: el ámbito inicial de ambas estadísticas es «Torneo completo» y las peticiones iniciales no envían fase ni grupo. Elegir fase añade el filtro a ambas tablas y volver a «Torneo completo» lo retira. Esto es independiente de la primera fase seleccionada para clasificación/calendario. Ambas tablas muestran la posición recibida, comparten posiciones en empates y conservan saltos (por ejemplo, 1,1,1,1,1,1,7,7). Se contrastó código, peticiones y pantalla; la referencia contraria de la guía de agentes estaba obsoleta.

La ordenación actual viene del servicio: jugadores por goles descendentes, partidos disputados ascendentes y apellido; equipos por GF descendentes, GC ascendentes y nombre. No hay controles de ordenación en las cabeceras. Esta propuesta conserva ese orden y las posiciones; no reabre ni reimplementa T15/T16.

## Usuarios

- Afición y personas participantes que consultan resultados desde un móvil.
- Personas que siguen una eliminatoria y necesitan reconocer de dónde llega cada equipo.
- Visitantes que comparan estadísticas y posiciones de una competición.
- Organizadores que comparten el enlace público, sin trasladar operaciones privadas a ese enlace.

## Roles y visibilidad

- Público anónimo: mantiene exactamente las lecturas permitidas por la matriz pública de la 020 y sus ampliaciones aprobadas 021/022, sin iniciar sesión.
- Miembro de organización, administrador de organización y administrador de plataforma: en estas superficies ven la misma proyección pública; sus permisos no añaden datos ni acciones de gestión a la vista pública.
- Un torneo no visible conserva el mismo resultado indistinguible de recurso no disponible. No se consulta ni mezcla información privada de otra organización; los torneos de otras organizaciones que ya son públicos siguen siendo consultables conforme a la matriz vigente.

## Historias de usuario

- HU-1. Como visitante, quiero localizar los torneos y llegar a sus resultados sin atravesar primero contenido promocional o toda la lista de equipos.
- HU-2. Como persona que sigue una eliminatoria, quiero distinguir rondas, ganadores y cruces sin deducir conexiones inexistentes a partir de columnas desalineadas.
- HU-3. Como visitante móvil, quiero identificar al jugador/equipo y su dato principal antes de desplazar la tabla, sin perder acceso a las demás métricas.
- HU-4. Como persona que usa teclado o ayudas técnicas, quiero recorrer las regiones desplazables y consultar la formación con un equivalente textual y retorno de foco.

## Definiciones

- **Origen inequívoco:** partido de la ronda inmediatamente anterior cuyo ganador informado es participante del destino y cuyo par origen/destino es único para ese participante dentro de la misma fase y ámbito. Se usan identificadores públicos, nunca nombres, proximidad, marcador deducido ni el orden de llegada. Sin ganador o ante ambigüedad no se representa línea, incluso si el código permite adivinar una llave teórica (D2).
- **Bye o pase libre:** avance sin disputar un partido. No equivale a una victoria por W.O. ni a un partido pendiente, y no autoriza a inventar un resultado.
- **Marca neutra:** indicación de marcador no informado, distinta de un 0–0 realmente comunicado.
- **Ronda nominal:** Final, Semifinales, Cuartos de final u Octavos de final cuando el significado se puede establecer con la información vigente; «Ronda n» es una denominación genérica válida cuando no hay certeza.
- **Columna prioritaria:** Posición/Jugador/Goles en jugadores y Posición/Equipo/GF en equipos, completamente visibles en la vista inicial móvil sin desplazamiento horizontal (D4); las demás métricas siguen accesibles mediante scroll local y la identidad permanece sticky.
- **Recuento visible:** número de filas cargadas en ese momento, no un total de participantes inferido.

## Requisitos funcionales

Las decisiones D1–D4 están aprobadas e incorporadas a los requisitos. Ninguna autoriza ampliar la información pública.

- RF-001: EL SISTEMA conservará las rutas, lecturas, campos, permisos y visibilidad públicos vigentes; no añadirá escrituras, requisitos de sesión, cookies nuevas ni datos privados para presentar estas mejoras.
- RF-002: CUANDO existan torneos públicos, EL SISTEMA ofrecerá en la primera pantalla de la portada un acceso identificable a la lista de torneos, a 1440×900 y 390×844, sin exigir registro ni usar el enlace a documentación como sustituto; al activarlo se verá el encabezado de la lista sin quedar cubierto.
- RF-003: MIENTRAS un marcador de portada sea una ilustración fija y no un resultado de los datos consultados, EL SISTEMA lo identificará como ejemplo y no como un partido real «En vivo».
- RF-004: CUANDO se abra el detalle de un torneo con resultados o estadísticas, EL SISTEMA ofrecerá accesos a esas secciones dentro de la primera pantalla en ambas resoluciones, sin tener que recorrer antes toda la lista de equipos; se mantendrá accesible esa lista completa.
- RF-005: CUANDO se muestre una llave, EL SISTEMA conservará todos los partidos recibidos, una vez cada uno y en su ronda correspondiente, incluidos los pendientes y aquellos con uno o ambos participantes por definir; no añadirá partidos o resultados para rellenar huecos.
- RF-006: CUANDO los códigos públicos reconocidos identifiquen la ronda, EL SISTEMA mostrará Final, Semifinales, Cuartos de final u Octavos de final y su equivalente en inglés (D3); SI el código no permite establecer ese significado, ENTONCES EL SISTEMA conservará «Ronda n» o una etiqueta genérica cuando no exista número, sin inferir la final de la última página visible.
- RF-007: CUANDO se muestre una llave, EL SISTEMA presentará un diagrama con scroll horizontal y conectores solo entre pares inequívocos de rondas consecutivas (D1/D2). El centro nominal del destino será el promedio Y de sus orígenes conocidos, con tolerancia de 2 px a escala 100 % cuando no haya colisión; si el centrado produce solapes, se aplicará únicamente el desplazamiento mínimo necesario para separarlos. Los partidos sin orígenes permanecerán en su orden de API. Se comprobarán ambas resoluciones y los casos de 4, 8 y 16 equipos.
- RF-008: SI falta ganador, hay más de un par posible o la existencia de un bye no se puede establecer con la información pública disponible, ENTONCES EL SISTEMA mantendrá el partido en su ronda sin línea ni pase libre inventados y explicará que solo se conectan avances identificables (D2). Una línea falsa es peor que una línea ausente; no se amplía la API.
- RF-009: CUANDO el torneo contenga byes o un número impar admitido por el producto, EL SISTEMA conservará las rondas y participantes recibidos sin convertir el bye en W.O., partido ficticio o eliminación; se comprobará el caso real de 5 equipos y 3 pases libres.
- RF-010: CUANDO un partido incluya ganador informado, EL SISTEMA lo distinguirá mediante una señal textual o accesible además del color; SI no hay ganador informado, ENTONCES EL SISTEMA no lo deducirá de la posición de una tarjeta, del nombre del equipo o de un marcador ausente.
- RF-011: CUANDO se muestre un partido resuelto por penales o W.O., EL SISTEMA distinguirá resolución, marcador y, si existe, tanda; conservará exactamente los números recibidos y no publicará el motivo privado de la resolución. SI el marcador no está informado, ENTONCES EL SISTEMA mostrará una marca neutra, nunca un 0–0 inventado.
- RF-012: CUANDO se consulte la llave a 390×844, EL SISTEMA permitirá alcanzar todas las rondas y todos sus partidos con scroll horizontal local del diagrama (D1), con nombre de ronda visible en cada columna, pista de desplazamiento y acceso por teclado, sin causar scroll horizontal del documento ni sustituir el cuadro por listas o pestañas.
- RF-013: CUANDO se abran las estadísticas, EL SISTEMA conservará «Torneo completo» como ámbito inicial independiente de la fase del calendario; CUANDO se elija una fase o se restaure el torneo completo, EL SISTEMA aplicará o retirará ese filtro en ambas tablas sin mezclar filas de ámbitos diferentes, torneos u organizaciones.
- RF-014: MIENTRAS se presenten estadísticas, EL SISTEMA conservará la posición y el orden entregados, incluidos empates y saltos de posición, y hará consultable el criterio de orden actual; cargar más filas no reiniciará la posición ni reordenará solo el fragmento visible. No se incorporan controles nuevos de ordenación.
- RF-015: CUANDO se consulten estadísticas a 390×844, EL SISTEMA conservará tablas con scroll e identidad sticky (D4), mostrará completamente Posición/Jugador/Goles o Posición/Equipo/GF al abrir y permitirá consultar todas las columnas restantes sin suprimir métricas ni sustituir filas por tarjetas. Los nombres abreviados conservarán su versión completa accesible por teclado y ayudas técnicas.
- RF-016: CUANDO una tabla de estadísticas ofrezca cargar más filas, EL SISTEMA identificará el recuento como filas mostradas, no como total del torneo, y conservará la acción de cargar más y sus estados de carga, vacío y error.
- RF-017: CUANDO clasificación o estadísticas excedan el ancho disponible, EL SISTEMA mostrará una pista visible de desplazamiento, una región con nombre accesible y foco de teclado, y mantendrá identificable al equipo o jugador mientras se consultan las métricas de la derecha; el scroll local no desplazará horizontalmente el documento.
- RF-018: CUANDO se consulten partidos en lista, EL SISTEMA mantendrá asociados ambos equipos, marcador, estado, fecha y resolución, sin solapar sus textos ni ocultar controles a 390×844; los participantes por definir conservarán una etiqueta explícita y los nombres completos seguirán siendo accesibles.
- RF-019: CUANDO un partido tenga alineación o formación explícitamente publicada, EL SISTEMA conservará el acceso a esa información, al segmento informado y al equivalente textual; el diálogo cabrá en el viewport, permitirá alcanzar su contenido completo y, al cerrarlo con su control o Escape, devolverá el foco al disparador. SI no existe publicación, ENTONCES EL SISTEMA no inferirá ni mostrará una formación privada.

## Requisitos no funcionales

- RNF-001: EL SISTEMA limitará estas mejoras a la presentación de datos ya disponibles. Se conservarán API, parámetros admitidos, campos públicos, cálculos, criterios de estadísticas, paginación, reglas, resultados y permisos; no se usarán consultas privadas para completar el gráfico público.
- RNF-002: EL SISTEMA tendrá cero violaciones de aplicación en axe en cada superficie auditada a 1440×900 y 390×844, incluida la clasificación móvil hoy afectada; solo se separará el aviso externo de DevTools de los resultados de la aplicación.
- RNF-003: EL SISTEMA no excederá el ancho del viewport en el documento (tolerancia de 1 px por redondeo); el contenido ancho será accesible en su región o mediante el modelo móvil aprobado. El foco no quedará oculto por cabeceras, controles flotantes ni barras de desplazamiento.
- RNF-004: EL SISTEMA conservará la identidad visual y escalas de la 029, contraste de texto normal ≥4,5:1 y de señales gráficas esenciales ≥3:1, sin depender únicamente del color para ganador, selección o conexiones. Las etiquetas compactas de una formación conservarán su alternativa textual completa.
- RNF-005: EL SISTEMA permitirá usar navegación, filtros, desplazamiento y diálogos con teclado, con nombre y foco visibles, y respetará la preferencia de movimiento reducido. Las pestañas de estadísticas expondrán selección y relación con el contenido mostrado.
- RNF-006: EL SISTEMA ofrecerá los textos nuevos en español e inglés, sin traducir ni alterar nombres de torneos, equipos o personas recibidos.

## Datos personales y privacidad

Se conserva la proyección mínima vigente: los nombres y fotografías públicos siguen sujetos a las condiciones aprobadas en 020–022. Una foto solo se representa cuando la respuesta pública permite hacerlo; las iniciales y el equivalente textual siguen disponibles. No se incorporan documentos, edad, fechas de nacimiento, claves de almacenamiento, plantillas privadas, asistencias de gol, sanciones, suspensiones, motivos de W.O./resolución administrativa ni información de membresías. No se cruzan fuentes privadas ni torneos para completar participantes, posiciones o relaciones de avance.

## Casos límite

- Torneo sin fases, sin clasificación, sin estadísticas o sin partidos; carga parcial, error y reintento ya existentes.
- Llaves de 4, 8 y 16 equipos, 5 equipos con 3 byes, rondas incompletas o con jornada desconocida, códigos no reconocidos y formatos distintos de eliminación directa.
- En byes, cuadros parciales o partidos pendientes no se rellenan huecos ni se enlazan partidos saltando rondas; un ganador informado por penales o W.O. puede originar una línea bajo la misma prueba de unicidad. Un equipo repetido en varios partidos hace ambiguos los pares afectados: no se elige uno por nombre, índice o código.
- Si varios destinos reclaman la misma posición Y, el espacio mínimo entre tarjetas prevalece sobre el centro nominal para evitar solapes; se conserva el orden de API de los partidos sin relación y se registra el desplazamiento al verificar el layout (RF-007).
- Participantes por definir, nombres largos o iguales, equipo sin escudo, ganador ausente, 0–0 real, cancelado sin resultado, W.O., prórroga y tanda de penales.
- Empates compartidos y paginación de estadísticas, filtro sin filas, cambio de fase y vuelta al ámbito completo.
- Una o ambas formaciones no publicadas, publicación de solo alineación textual, formación por segmento, nombres largos, foto ausente o fallida.
- Resoluciones emuladas de referencia, zoom y movimiento reducido; las limitaciones de comprobación con dispositivos físicos y ayudas técnicas se declararán expresamente.

## Fuera de alcance

- Cambios en matriz pública, campos, API, permisos, esquema, motor deportivo, calendarios, resultados, avance, privacidad o publicación de formaciones.
- Consultar relaciones de avance privadas para dibujar conectores; añadir esa información pública exigiría otra propuesta y no queda autorizado por D2.
- Rehacer T15/T16 de la 022: están implementadas; aquí solo se protegen como comportamiento existente.
- Nuevos criterios de orden, cálculo local de posiciones, nuevas métricas, tarjetas de jugador con datos adicionales o acciones privadas de gestión.
- Nuevo tema o marca, cambio de tipografía, rediseño del Workspace, autenticación o administración.
- Implementación sin aprobación previa del plan y las tareas. La aprobación de la spec y el encargo de redactar esos documentos no autorizan a tocar la app.

## Criterios de finalización

- Spec aprobada y D1–D4 resueltas el 2026-11-11; obtener la aprobación del plan/tareas antes de implementar.
- Comparar antes/después de todas las superficies auditadas a ambas resoluciones, con medidas Y, anchos visibles/desplazables, columnas prioritarias y cero overflow horizontal de página.
- Verificar las relaciones representadas contra los casos conocidos sin usar datos privados en la vista pública; demostrar el fallback cuando los datos no permiten garantizar una conexión.
- Verificar etiquetas de ronda, 4/8/16 equipos, impares/byes, resultados pendientes, W.O. y penales; no inventar cruces ni resultados.
- Conservar ámbito de estadísticas, orden, posiciones, empates y carga de más filas; comprobar identidad y todas las columnas al desplazarse.
- Obtener cero violaciones de aplicación en axe y comprobar teclado, cierre/retorno de foco y equivalente textual de formación; declarar lo que no se haya comprobado con ayudas técnicas reales.
- Confirmar que las lecturas públicas no añaden campos ni cambian visibilidad, permisos o comportamiento deportivo; pasar las verificaciones y CI aplicables cuando exista implementación.

## Dudas abiertas

Ninguna pendiente. Respuestas del usuario, 2026-11-11: D1 A → RF-007/RF-012; D2 A → definición de origen, RF-008 y casos límite; D3 A → RF-006; D4 A → definición de columnas y RF-015. La matriz pública, campos y API permanecen intactos.
