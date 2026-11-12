# Spec 032 — Tema claro opcional

Estado: implementada

Fecha: 2026-11-11; cierre aprobado el 2026-11-12. Spec, clarificación, plan y tareas aprobados por el usuario: D1–D4, todas opción A, y LY-1. PR A (#53), PR B (#54) y PR C (#55) fusionados. T1–T10 completas; CI de #55 verde, run 43109805246, E2E de pull_request: 41 passed, incluidos los 15 escenarios del tema. El usuario autorizó el cierre: «Sí, ciérrala en un PR pequeño de documentación». Evidencias y límites en [verificacion.md](verificacion.md). La [auditoría de tema claro](../../docs/auditoria-tema-claro-032.md) conserva inventario, paleta y 158 pares calculados.

## Contexto y objetivo

Bracket Craft solo ofrece una apariencia oscura. Su identidad y densidad ya se normalizaron con las specs 029–031; esta iniciativa no las rediseña. Algunas personas necesitan consultar tablas o trabajar con formularios sobre un fondo claro sin perder las preferencias de quienes usan el oscuro.

La auditoría estática de la base actual encontró 23 roles de color (20 valores únicos), con espejo idéntico, y ningún color literal hex/rgb/hsl fuera de esos roles en los 64 archivos de interfaz inspeccionados. El problema no es una migración masiva de colores sueltos: son las superficies semitransparentes, avatares, campo de juego, controles nativos, metadatos de ventana y la elección inicial de apariencia.

**Objetivo:** ofrecer un tema claro opcional, legible y coherente en las superficies que se aprueben, conservando el tema oscuro actual con **0 píxeles de diferencia fuera de la región de preferencias R**, sin cambios de backend, API, datos de negocio, reglas deportivas ni permisos. Una preferencia de presentación no es un atributo de cuenta u organización. D1–D4 están resueltas; LY-1 registra la geometría revisada y la autorización de PR B.

D2 resolvió la incompatibilidad original del selector nuevo; LY-1 (2026-11-11) sustituye su límite geométrico: se permite reordenar las preferencias dentro de R, nunca desplazar o modificar lo situado fuera de ella.

## Usuarios

Público anónimo, miembros de organización (operadores, árbitros, observadores, administradores y dueños) y administradores de plataforma, incluidos usuarios de teclado y tecnologías de asistencia.

## Roles y visibilidad

No aplica: no se añaden roles ni se cambia qué puede consultar o modificar cada persona. Elegir tema no requiere cuenta, sesión u organización; tampoco permite acceder a una superficie que no estuviera autorizada. Las rutas públicas conservan su acceso anónimo y su proyección mínima.

## Historias de usuario

- HU-1. Como visitante, quiero elegir una apariencia clara para leer el torneo cómodamente sin registrarme ni cambiar los datos que veo.
- HU-2. Como operador, quiero conservar mi elección al navegar y, si se aprueba persistencia, al volver, sin perder formularios, filtros o el foco.
- HU-3. Como usuario del oscuro actual, quiero que su aspecto permanezca idéntico fuera del nuevo selector, no una aproximación de la nueva paleta.
- HU-4. Como usuario de teclado o lector de pantalla, quiero encontrar y comprender la elección de apariencia y su valor activo sin depender del color o de un icono.

## Definiciones

- **Preferencia:** Claro, Oscuro o Sistema. Es una elección de presentación de este navegador; no pertenece al torneo, cuenta ni tenant. Por D1, sin elección se usa Oscuro incluso si el sistema prefiere claro. Sistema sigue siendo una elección explícita. Por D3, una cookie anual guarda únicamente elecciones explícitas.
- **Tema resuelto:** Claro u Oscuro, tras considerar una elección explícita o la preferencia de sistema cuando corresponda. Una elección explícita tiene prioridad sobre el sistema.
- **Oscuro idéntico fuera de R:** cero píxeles distintos respecto de la referencia anterior fuera de la única región autorizada por LY-1, sin tolerancia porcentual, en el mismo estado, datos, viewport, motor, tipografías, reloj y animaciones estabilizados. Incluye colores, geometría, textos, imágenes y estados de navegación preexistentes fuera de R.
- **Región de preferencias (R), LY-1:** en Workspace/admin escritorio/tableta, caja de la fila de preferencias de cabecera (organización, idioma, tema y cuenta); en móvil, menú abierto completo. Con menú móvil cerrado R está vacía y se exige cero píxeles distintos en toda la captura. En público, R es la caja del grupo flotante de idioma/tema en todos los anchos, incluido móvil: no hay menú y no se traslada el idioma a cabecera. Registrar coordenadas por fixture, viewport y estado antes de comparar, nunca derivarlas del diff. Fuera de R se exigen cero píxeles distintos; el contenido situado debajo de la cabecera del Workspace conserva su posición. No se permite aumentar la altura de cabecera/menú desplazando contenido exterior. Esta definición sustituye los límites antiguos de 192×80/192×200 px; no autoriza ninguna otra máscara.
- **Texto:** todo texto presentado por la interfaz, también etiquetas pequeñas, iniciales, placeholders, validación y contenido de controles deshabilitados. El tema claro propuesto exige al menos 4.5:1 en todos ellos, no solo en texto grande.
- **Señal esencial:** borde necesario para reconocer un control, foco visible o gráfico que transmite información; exige al menos 3:1 contra su fondo adyacente. Una sombra decorativa no sustituye esa señal.
- **Isla gráfica del campo:** terreno verde con trazos y etiquetas de contraste propio, integrado en una interfaz clara. No significa dejar oscuro el diálogo, encabezado, banco o alternativa textual que lo rodea. D4 aprueba esta isla en todas las vistas que la muestran.

## Requisitos funcionales

### Elección y primera presentación

- RF-001: EL SISTEMA ofrecerá las preferencias Claro, Oscuro y Sistema mediante un control con nombre accesible, valor seleccionado perceptible y textos en el idioma activo, sin que un icono sea su único identificador.
- RF-002: CUANDO no exista una preferencia válida, EL SISTEMA aplicará Oscuro; CUANDO exista una elección explícita válida de Claro u Oscuro, EL SISTEMA la priorizará sobre la apariencia del sistema operativo.
- RF-003: CUANDO la preferencia sea Sistema, EL SISTEMA resolverá la apariencia según el sistema operativo y responderá a sus cambios sin recargar la página; SI se eligió Claro u Oscuro explícitamente, ENTONCES esos cambios no alterarán la elección.
- RF-004: CUANDO se cambie la preferencia, EL SISTEMA actualizará el tema sin recargar la ruta, perder el foco ni reiniciar formularios, selección de torneo/fase/grupo, paginación, desplazamiento, diálogos o datos ya cargados; no efectuará peticiones adicionales a la API por esa elección.
- RF-005: CUANDO se abra o recargue una ruta con preferencia recuperable válida, EL SISTEMA mostrará desde el primer pintado el tema resuelto correcto y mantendrá ese mismo resultado tras activar la interacción, sin un fotograma intermedio del tema opuesto ni avisos de divergencia de contenido.
- RF-006: EL SISTEMA conservará la preferencia durante la navegación y la guardará en una cookie anual únicamente cuando el usuario elija; SI esa persistencia está disponible, ENTONCES la recuperará tras recargar y volver a abrir el navegador; SI está bloqueada o el valor es desconocido, ENTONCES permitirá navegar y elegir tema sin excepción visible, aplicando el fallback de D1 donde no pueda recuperarla.
- RF-007: EL SISTEMA mostrará el selector junto al idioma, con etiqueta coherente con «Idioma», en el grupo flotante público y la fila de preferencias de cabecera o menú móvil del Workspace, incluido administración, conforme a LY-1; acceso por teclado, etiqueta y valor activo legibles, sin solapamientos con acciones, pistas, navegación o texto esencial a 390, 800 y 1440 px. El grupo público podrá crecer y se apilará hacia arriba si no cabe horizontalmente.

### Apariencia y accesibilidad

- RF-008: MIENTRAS el tema claro esté activo, EL SISTEMA presentará texto y fondos con contraste de al menos 4.5:1, y señales esenciales con al menos 3:1, en reposo, hover, foco, selección, validación, cargando, vacío, error y deshabilitado. Las mezclas y transparencias se medirán sobre su fondo efectivo, no contra transparente.
- RF-009: CUANDO cambie el tema, EL SISTEMA conservará tipografía, escalas, radios, medidas y disposición existentes fuera de R; podrá cambiar únicamente la apariencia cromática y elevación del claro y reordenar las preferencias dentro de R conforme a LY-1. Los estados semánticos seguirán distinguiéndose mediante texto o equivalente accesible, no solo por color.
- RF-010: EL SISTEMA aplicará el tema coherentemente a todas las vistas públicas, de acceso/invitaciones/cuenta, organización, Workspace, operación/asistentes, administración y errores, incluidos tablas, columnas sticky, pistas, formularios, selectores nativos, diálogos, backdrops, mensajes y formaciones; no dejará paneles oscuros accidentales dentro de la interfaz clara.
- RF-011: CUANDO se muestren escudos o fotografías, EL SISTEMA conservará sus bytes, proporciones, URLs y alternativas textuales, sin invertirlos ni recolorearlos automáticamente; CUANDO falte o falle una imagen, EL SISTEMA mostrará iniciales con contraste válido sobre su fondo efectivo.
- RF-012: CUANDO se muestre un bracket o campo de juego en claro, EL SISTEMA conservará partidos, relaciones, posiciones, datos y equivalentes textuales; garantizará contraste en sus líneas y etiquetas, incluyendo jugadores locales y visitantes. La isla gráfica aprobada por D4 afectará solo al terreno y a los colores necesarios para leerlo, no al contenedor completo.
- RF-013: CUANDO el tema resuelto sea Claro u Oscuro, EL SISTEMA presentará controles nativos y color de ventana del navegador coherentes con él, sin cambiar el color de ventana oscuro actual.

### Aislamiento de la preferencia

- RF-014: EL SISTEMA mantendrá la preferencia separada de sesión y organización, disponible anónimamente; no enviará escrituras de negocio, creará cuentas ni guardará la elección en datos de backend. La presentación de una solicitud no se heredará de otra solicitud o visitante.
- RF-015: EL SISTEMA no creará almacenamiento persistente de apariencia por la mera visita sin elección del usuario; CUANDO este elija persistir su apariencia, EL SISTEMA guardará únicamente un valor de presentación válido, sin identificadores de persona, organización o torneo y sin sincronizarlo entre dispositivos.

## Requisitos no funcionales

- RNF-001: MIENTRAS se use Oscuro, EL SISTEMA conservará **0 píxeles distintos fuera de R** en cada captura acordada. R es la única excepción aprobada por LY-1; se conservarán las referencias y no se excluirán otras zonas ni se ampliará R para alcanzar el resultado. Los controles y contenido fuera de R conservarán geometría y aspecto; con menú móvil Workspace cerrado la igualdad será de toda la captura. En público se compara siempre fuera del grupo flotante, también en móvil.
- RNF-002: EL SISTEMA tendrá cero violaciones de aplicación en axe en las superficies cubiertas por D4 en claro a 1440×900, 390×844 y 800×900, y ninguna regresión de accesibilidad en oscuro. Las comprobaciones de contraste completas incluirán los pares y composiciones de la auditoría; axe por sí solo no los sustituye.
- RNF-003: EL SISTEMA no introducirá nuevas fuentes, dependencias de recursos externos, animaciones automáticas de tema ni cambios de escala; respetará reducción de movimiento y conservará el foco visible durante la elección.
- RNF-004: EL SISTEMA conservará backend, API, reglas, datos, permisos y matriz pública: mismas rutas de negocio, parámetros, campos, resultados y ausencia de nuevas llamadas motivadas por el cambio de tema. Toda preferencia persistente será exclusivamente de presentación y opcional.
- RNF-005: EL SISTEMA conservará las políticas de seguridad y no relajará restricciones para resolver el primer pintado. Si el entorno impide recuperar una preferencia, seguirá siendo utilizable según RF-006.
- RNF-006: EL SISTEMA conservará verdes las suites y gates de CI aplicables, sin debilitar tests de escalas, contraste, privacidad, consultas públicas, operación ni tiempo real, y documentará límites de verificación sin presentarlos como resultados ejecutados.

## Datos personales y privacidad

No se añaden datos personales ni se modifica información de torneos, jugadores, miembros u organizaciones. La única persistencia aprobada es una cookie anual de apariencia del navegador, escrita solo cuando el usuario elige. No llevará identidad, consentimiento de imagen ni contenido deportivo; no sustituye cookies de autenticación ni requiere sesión. No habrá sincronización con la cuenta ni entre dispositivos. Escudos, fotografías y campos públicos conservan sus reglas de consentimiento, visibilidad y acceso actuales.

## Casos límite

- Sin preferencia, preferencia inválida, almacenamiento bloqueado o borrado: Oscuro por defecto, sin errores ni obligación de iniciar sesión. Si la cookie está bloqueada, la elección funciona durante la navegación actual y una nueva visita sin preferencia recuperable vuelve al oscuro. No se escribe ni repara una cookie por leer un valor inválido.
- Preferencia Sistema sin capacidad del navegador de informar una apariencia: fallback oscuro determinista, sin contenido oculto ni saltos tras activar la interacción.
- Recarga profunda en una ruta pública, sesión autenticada, expiración de sesión y cambio de organización: la apariencia no altera autorización, no conserva datos de otro tenant ni pierde su elección por cambiar de organización.
- Solicitudes simultáneas con elecciones opuestas: cada visitante recibe su apariencia, no la última usada por otro; cualquier caché compartida debe preservar ese aislamiento de presentación.
- Cambio con formulario modificado, diálogo abierto, tabla desplazada o partido actualizándose: no se repiten acciones ni se cambia el contenido deportivo por el tema.
- Texto sobre césped, imágenes transparentes, selección, autofill, filas alternas, sticky y hover: comprobar el fondo compuesto real. En claro, opacidad reducida de un contenedor no puede dejar su texto por debajo de 4.5:1; no se cambia esa opacidad en oscuro.
- LY-1: se permite reordenar organización, idioma, tema y cuenta dentro de R. Si se mueve algo fuera de la cabecera o del menú abierto medido, se detiene la implementación y se informa; no se amplía R ni se cambian referencias para silenciarlo.

## Fuera de alcance

- Implementación en esta entrega; solo registro de aprobación y propuesta documental de plan/tareas.
- Rediseñar layout, tipografía, navegación, formularios, bracket, campos de juego o reglas deportivas; reparar contraste histórico del oscuro cambiando su aspecto.
- Cambiar backend, API, esquema, datos, permisos o matriz pública; guardar un tema de organización/cuenta, sincronizar dispositivos o añadir analítica.
- Recolorear logos/fotos, generar nuevos assets, fuentes o modos de alto contraste propios, estilos de impresión o una nueva política de seguridad.
- Considerar las ratios calculadas como verificación visual de una implementación que todavía no existe.

## Criterios de finalización

1. D1–D4 registradas, spec aprobada y plan/tareas aprobados antes de implementar; la única excepción visual es R, autorizada expresamente por el usuario.
2. Todas las vistas en ambos temas, capturas controladas en 1440×900, 390×844 y 800×900, manifiesto de R según LY-1 y comparación oscura con 0 píxeles fuera de ella; cajas exteriores intactas, incluido todo lo situado debajo de la cabecera del Workspace. En móvil Workspace cerrado, R vacía y captura entera idéntica; en público, R del flotante en todos los anchos.
3. Todos los pares de texto y señales esenciales del claro pasan sus umbrales; verificación de mezclas/estados reales además de los 158 pares propuestos, incluyendo iniciales, campos y controles deshabilitados. Cero axe de aplicación en claro y sin regresiones en oscuro.
4. Primera visita, enlace profundo, recarga, navegación, preferencia inválida/bloqueada y cambios de sistema sin fotogramas de tema opuesto con preferencia recuperable, sin divergencias al activar interacción ni pérdida de estado/foco.
5. Matriz pública, llamadas API, contenido y permisos sin cambios; ninguna preferencia compartida accidentalmente entre visitantes; sin dependencia de sesión o persistencia de negocio.
6. Suites/gates aplicables verdes y revisión humana; documentación de uso, accesibilidad, decisiones y límites actualizada, con aprobación del usuario antes de declarar implementada.

## Dudas abiertas

Ninguna. Respuestas del usuario del 2026-11-11, todas opción A:

| Decisión | Respuesta aprobada | Requisitos/casos |
|---|---|---|
| D1 | Sin elección previa, Oscuro; Claro o Sistema solo mediante elección explícita. | RF-002/003/005/006; fallback oscuro. |
| D2 | Selector junto al idioma: flotante público, cabecera y menú móvil del Workspace. Única diferencia oscura autorizada: R, definida y medida; 0 píxeles fuera de R. | RF-007/009, RNF-001, definición de R, criterio 2. |
| D3 | Cookie anual como idioma; solo se escribe al elegir. La primera entrega de página respeta la elección recuperable sin parpadeo. | RF-005/006/014/015, privacidad y cookie inválida/bloqueada. |
| D4 | Todas las vistas; terreno verde como isla con etiquetas legibles, sin dejar oscuros los contenedores del claro. | RF-008/010/011/012, RNF-002 y contraste compuesto. |

Plan y tareas propuestos para revisión; esta aprobación no autoriza todavía la implementación.

### LY-1 — Reordenación de preferencias aprobada, 2026-11-11

Decisión textual del usuario: «Aceptar que la fila de preferencias de la cabecera (organización, idioma, tema, cuenta) y el menú móvil abierto se reordenen; todo lo de debajo de la cabecera sigue idéntico al píxel en el tema oscuro (recomendado)».

Precisión pública aprobada el 2026-11-11: se conserva el flotante existente y se añade el tema en ese mismo grupo; R es su caja en todos los anchos, incluido móvil, porque no hay menú público. Puede crecer sin tapar controles ni texto esencial; si no cabe horizontalmente a 390 px, se apila hacia arriba. No se traslada el idioma a la cabecera pública. Workspace conserva fila de preferencias y menú abierto.

LY-1 sustituye solo la geometría de D2/R y autoriza continuar T4–T6; D1, D3, D4, persistencia, accesibilidad, API y permisos no cambian. Plan/tareas aprobados, PR A fusionado. El control conserva estilo propio, etiqueta coherente con «Idioma» y opciones Oscuro/Claro/Sistema, ES/EN. Si aparece un cambio fuera de R, se detiene y se informa.
