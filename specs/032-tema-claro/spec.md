# Spec 032 — Tema claro opcional

Estado: borrador

Fecha: 2026-11-11. Fase 1 de SDD: solo spec y auditoría, sin aprobación ni implementación. El usuario confirmó que #52 está fusionado. 032 es el siguiente número libre después de la 031. Hallazgos, inventario por archivo, paleta propuesta y matriz completa de contraste en la [auditoría de tema claro](../../docs/auditoria-tema-claro-032.md).

## Contexto y objetivo

Bracket Craft solo ofrece una apariencia oscura. Su identidad y densidad ya se normalizaron con las specs 029–031; esta iniciativa no las rediseña. Algunas personas necesitan consultar tablas o trabajar con formularios sobre un fondo claro sin perder las preferencias de quienes usan el oscuro.

La auditoría estática de la base actual encontró 23 roles de color (20 valores únicos), con espejo idéntico, y ningún color literal hex/rgb/hsl fuera de esos roles en los 64 archivos de interfaz inspeccionados. El problema no es una migración masiva de colores sueltos: son las superficies semitransparentes, avatares, campo de juego, controles nativos, metadatos de ventana y la elección inicial de apariencia.

**Objetivo:** ofrecer un tema claro opcional, legible y coherente en las superficies que se aprueben, conservando el tema oscuro actual con **0 píxeles de diferencia**, sin cambios de backend, API, datos de negocio, reglas deportivas ni permisos. Una preferencia de presentación no es un atributo de cuenta u organización. Las decisiones D1–D4 deben resolverse antes de planificar o implementar.

Hay una incompatibilidad por resolver: añadir un selector visible a una pantalla oscura existente cambia píxeles aunque no se cambie su paleta. El requisito de 0 píxeles se conserva literalmente; no se autoriza una excepción implícita para el selector. D2 pregunta por ese compromiso.

## Usuarios

Público anónimo, miembros de organización (operadores, árbitros, observadores, administradores y dueños) y administradores de plataforma, incluidos usuarios de teclado y tecnologías de asistencia.

## Roles y visibilidad

No aplica: no se añaden roles ni se cambia qué puede consultar o modificar cada persona. Elegir tema no requiere cuenta, sesión u organización; tampoco permite acceder a una superficie que no estuviera autorizada. Las rutas públicas conservan su acceso anónimo y su proyección mínima.

## Historias de usuario

- HU-1. Como visitante, quiero elegir una apariencia clara para leer el torneo cómodamente sin registrarme ni cambiar los datos que veo.
- HU-2. Como operador, quiero conservar mi elección al navegar y, si se aprueba persistencia, al volver, sin perder formularios, filtros o el foco.
- HU-3. Como usuario del oscuro actual, quiero que su aspecto permanezca idéntico, no una aproximación de la nueva paleta.
- HU-4. Como usuario de teclado o lector de pantalla, quiero encontrar y comprender la elección de apariencia y su valor activo sin depender del color o de un icono.

## Definiciones

- **Preferencia:** Claro, Oscuro o Sistema. Es una elección de presentación de este navegador; no pertenece al torneo, cuenta ni tenant. Su valor por defecto se decide en D1 y su persistencia en D3.
- **Tema resuelto:** Claro u Oscuro, tras considerar una elección explícita o la preferencia de sistema cuando corresponda. Una elección explícita tiene prioridad sobre el sistema.
- **Oscuro idéntico:** cero píxeles distintos respecto de la referencia anterior, sin tolerancia porcentual ni máscaras para esconder regresiones, en el mismo estado, datos, viewport, motor, tipografías, reloj y animaciones estabilizados. Incluye colores, geometría, textos, imágenes y estados de navegación preexistentes. D2 no está exceptuada de esta definición mientras el usuario no apruebe expresamente un cambio.
- **Texto:** todo texto presentado por la interfaz, también etiquetas pequeñas, iniciales, placeholders, validación y contenido de controles deshabilitados. El tema claro propuesto exige al menos 4.5:1 en todos ellos, no solo en texto grande.
- **Señal esencial:** borde necesario para reconocer un control, foco visible o gráfico que transmite información; exige al menos 3:1 contra su fondo adyacente. Una sombra decorativa no sustituye esa señal.
- **Isla gráfica del campo:** terreno verde con trazos y etiquetas de contraste propio, integrado en una interfaz clara. No significa dejar oscuro el diálogo, encabezado, banco o alternativa textual que lo rodea. Su inclusión se decide en D4.

## Requisitos funcionales

### Elección y primera presentación

- RF-001: EL SISTEMA ofrecerá las preferencias Claro, Oscuro y Sistema mediante un control con nombre accesible, valor seleccionado perceptible y textos en el idioma activo, sin que un icono sea su único identificador.
- RF-002: CUANDO no exista una preferencia válida, EL SISTEMA aplicará el valor por defecto aprobado en D1; CUANDO exista una elección explícita válida de Claro u Oscuro, EL SISTEMA la priorizará sobre la apariencia del sistema operativo.
- RF-003: CUANDO la preferencia sea Sistema, EL SISTEMA resolverá la apariencia según el sistema operativo y responderá a sus cambios sin recargar la página; SI se eligió Claro u Oscuro explícitamente, ENTONCES esos cambios no alterarán la elección.
- RF-004: CUANDO se cambie la preferencia, EL SISTEMA actualizará el tema sin recargar la ruta, perder el foco ni reiniciar formularios, selección de torneo/fase/grupo, paginación, desplazamiento, diálogos o datos ya cargados; no efectuará peticiones adicionales a la API por esa elección.
- RF-005: CUANDO se abra o recargue una ruta con preferencia recuperable válida, EL SISTEMA mostrará desde el primer pintado el tema resuelto correcto y mantendrá ese mismo resultado tras activar la interacción, sin un fotograma intermedio del tema opuesto ni avisos de divergencia de contenido.
- RF-006: EL SISTEMA conservará la preferencia según D3 durante la navegación; SI la persistencia aprobada está disponible, ENTONCES la recuperará tras recargar y volver a abrir el navegador; SI está bloqueada o el valor es desconocido, ENTONCES permitirá navegar y elegir tema sin excepción visible, aplicando el fallback de D1 donde no pueda recuperarla.
- RF-007: EL SISTEMA mostrará el selector en las ubicaciones aprobadas en D2, con acceso por teclado, etiqueta y valor activo legibles, sin solaparse con acciones, pista de scroll, navegación móvil o contenido a 390, 800 y 1440 px.

### Apariencia y accesibilidad

- RF-008: MIENTRAS el tema claro esté activo, EL SISTEMA presentará texto y fondos con contraste de al menos 4.5:1, y señales esenciales con al menos 3:1, en reposo, hover, foco, selección, validación, cargando, vacío, error y deshabilitado. Las mezclas y transparencias se medirán sobre su fondo efectivo, no contra transparente.
- RF-009: CUANDO cambie el tema, EL SISTEMA conservará tipografía, escalas, radios, medidas y disposición existentes; podrá cambiar únicamente la apariencia cromática y elevación del claro y las adiciones de preferencia que se aprueben en D2. Los estados semánticos seguirán distinguiéndose mediante texto o equivalente accesible, no solo por color.
- RF-010: EL SISTEMA aplicará el tema coherentemente a todas las superficies aprobadas en D4, incluidos tablas, columnas sticky, pistas, formularios, selectores nativos, diálogos, backdrops, mensajes y formaciones; no dejará paneles oscuros accidentales dentro de la interfaz clara.
- RF-011: CUANDO se muestren escudos o fotografías, EL SISTEMA conservará sus bytes, proporciones, URLs y alternativas textuales, sin invertirlos ni recolorearlos automáticamente; CUANDO falte o falle una imagen, EL SISTEMA mostrará iniciales con contraste válido sobre su fondo efectivo.
- RF-012: CUANDO se muestre un bracket o campo de juego en claro, EL SISTEMA conservará partidos, relaciones, posiciones, datos y equivalentes textuales; garantizará contraste en sus líneas y etiquetas, incluyendo jugadores locales y visitantes. SI se aprueba la isla gráfica, ENTONCES la excepción afectará solo al terreno y a los colores necesarios para leerlo, no al contenedor completo.
- RF-013: CUANDO el tema resuelto sea Claro u Oscuro, EL SISTEMA presentará controles nativos y color de ventana del navegador coherentes con él, sin cambiar el color de ventana oscuro actual.

### Aislamiento de la preferencia

- RF-014: EL SISTEMA mantendrá la preferencia separada de sesión y organización, disponible anónimamente; no enviará escrituras de negocio, creará cuentas ni guardará la elección en datos de backend. La presentación de una solicitud no se heredará de otra solicitud o visitante.
- RF-015: EL SISTEMA no creará almacenamiento persistente de apariencia por la mera visita sin elección del usuario; CUANDO este elija persistir su apariencia, EL SISTEMA guardará únicamente un valor de presentación válido, sin identificadores de persona, organización o torneo y sin sincronizarlo entre dispositivos.

## Requisitos no funcionales

- RNF-001: MIENTRAS se use Oscuro, EL SISTEMA conservará **0 píxeles distintos** en cada captura de los estados preexistentes acordados, sin modificar referencias ni excluir zonas para alcanzar el resultado. La incompatibilidad con un selector añadido queda bloqueada por D2, no resuelta por este borrador.
- RNF-002: EL SISTEMA tendrá cero violaciones de aplicación en axe en las superficies cubiertas por D4 en claro a 1440×900, 390×844 y 800×900, y ninguna regresión de accesibilidad en oscuro. Las comprobaciones de contraste completas incluirán los pares y composiciones de la auditoría; axe por sí solo no los sustituye.
- RNF-003: EL SISTEMA no introducirá nuevas fuentes, dependencias de recursos externos, animaciones automáticas de tema ni cambios de escala; respetará reducción de movimiento y conservará el foco visible durante la elección.
- RNF-004: EL SISTEMA conservará backend, API, reglas, datos, permisos y matriz pública: mismas rutas de negocio, parámetros, campos, resultados y ausencia de nuevas llamadas motivadas por el cambio de tema. Toda preferencia persistente será exclusivamente de presentación y opcional.
- RNF-005: EL SISTEMA conservará las políticas de seguridad y no relajará restricciones para resolver el primer pintado. Si el entorno impide recuperar una preferencia, seguirá siendo utilizable según RF-006.
- RNF-006: EL SISTEMA conservará verdes las suites y gates de CI aplicables, sin debilitar tests de escalas, contraste, privacidad, consultas públicas, operación ni tiempo real, y documentará límites de verificación sin presentarlos como resultados ejecutados.

## Datos personales y privacidad

No se añaden datos personales ni se modifica información de torneos, jugadores, miembros u organizaciones. La única persistencia en discusión es una preferencia de apariencia del navegador. No llevará identidad, consentimiento de imagen ni contenido deportivo; no sustituye cookies de autenticación ni requiere sesión. No habrá sincronización con la cuenta ni entre dispositivos. Escudos, fotografías y campos públicos conservan sus reglas de consentimiento, visibilidad y acceso actuales.

## Casos límite

- Sin preferencia, preferencia inválida, almacenamiento bloqueado o borrado: fallback de D1, sin errores ni obligación de iniciar sesión. Si D3 no aprueba persistencia, la elección solo dura lo acordado para ese contexto.
- Preferencia Sistema sin capacidad del navegador de informar una apariencia: fallback oscuro determinista, sin contenido oculto ni saltos tras activar la interacción.
- Recarga profunda en una ruta pública, sesión autenticada, expiración de sesión y cambio de organización: la apariencia no altera autorización, no conserva datos de otro tenant ni pierde su elección por cambiar de organización.
- Solicitudes simultáneas con elecciones opuestas: cada visitante recibe su apariencia, no la última usada por otro; cualquier caché compartida debe preservar ese aislamiento de presentación.
- Cambio con formulario modificado, diálogo abierto, tabla desplazada o partido actualizándose: no se repiten acciones ni se cambia el contenido deportivo por el tema.
- Texto sobre césped, imágenes transparentes, selección, autofill, filas alternas, sticky y hover: comprobar el fondo compuesto real. En claro, opacidad reducida de un contenedor no puede dejar su texto por debajo de 4.5:1; no se cambia esa opacidad en oscuro.
- D2: un control visible nuevo contradice 0 píxeles si aparece en una captura oscura preexistente. No se admite ocultarlo a la herramienta de comparación ni crear una referencia nueva para silenciar el conflicto. Se requiere respuesta del usuario antes del plan.

## Fuera de alcance

- Implementación, plan y tareas en esta entrega; solo documentación y auditoría estática.
- Rediseñar layout, tipografía, navegación, formularios, bracket, campos de juego o reglas deportivas; reparar contraste histórico del oscuro cambiando su aspecto.
- Cambiar backend, API, esquema, datos, permisos o matriz pública; guardar un tema de organización/cuenta, sincronizar dispositivos o añadir analítica.
- Recolorear logos/fotos, generar nuevos assets, fuentes o modos de alto contraste propios, estilos de impresión o una nueva política de seguridad.
- Considerar las ratios calculadas como verificación visual de una implementación que todavía no existe.

## Criterios de finalización

1. D1–D4 resueltas y spec aprobada antes de planificar; decisión explícita sobre el conflicto de D2, sin modificar por inferencia el requisito oscuro de 0 píxeles.
2. Matriz de las rutas/superficies aprobadas en ambos temas, capturas controladas en 1440×900, 390×844 y 800×900 y comparación oscura con 0 píxeles según RNF-001 o el requisito que el usuario apruebe expresamente al resolver D2.
3. Todos los pares de texto y señales esenciales del claro pasan sus umbrales; verificación de mezclas/estados reales además de los 158 pares propuestos, incluyendo iniciales, campos y controles deshabilitados. Cero axe de aplicación en claro y sin regresiones en oscuro.
4. Primera visita, enlace profundo, recarga, navegación, preferencia inválida/bloqueada y cambios de sistema sin fotogramas de tema opuesto con preferencia recuperable, sin divergencias al activar interacción ni pérdida de estado/foco.
5. Matriz pública, llamadas API, contenido y permisos sin cambios; ninguna preferencia compartida accidentalmente entre visitantes; sin dependencia de sesión o persistencia de negocio.
6. Suites/gates aplicables verdes y revisión humana; documentación de uso, accesibilidad, decisiones y límites actualizada, con aprobación del usuario antes de declarar implementada.

## Dudas abiertas

### D1 — Valor por defecto [NECESITA ACLARACIÓN]

- **A — Recomendación: Oscuro sin preferencia previa.** Conserva la experiencia actual y hace que Claro sea opcional; Sistema sigue siendo una elección explícita.
- B — Sistema desde la primera visita. Respeta automáticamente el dispositivo, pero cambia la presentación inicial para dispositivos claros y exige resolverla antes del primer pintado sin conocerla en el servidor.
- Afecta RF-002/003/005 y casos de fallback. Una elección explícita siempre prevalece.

### D2 — Descubrimiento del selector y 0 píxeles [NECESITA ACLARACIÓN]

- **A — Recomendación de usabilidad, condicionada a autorización expresa: junto al idioma en público y Workspace/admin, con la única excepción visual del nuevo control aprobada por el usuario.** En público el idioma hoy es flotante inferior derecho, no una cabecera; en Workspace está en cabecera y menú móvil. Esto hace el control descubrible, pero **no cumple 0 píxeles literal** en las zonas donde se añada. No se considera autorizada esa excepción por proponerla.
- B — Mantener 0 píxeles sin excepciones en todas las vistas existentes; selector en una nueva vista de preferencias accesible por URL documentada, sin añadir entradas a la navegación existente. Preserva estrictamente el oscuro, con peor descubrimiento; cualquier enlace visible añadido volvería a requerir autorización.
- C — Solo en cuenta/menú de cuenta. Reduce exposición y descubrimiento; limita el acceso anónimo si requiere sesión y también cambia los píxeles de los estados de menú modificados. Solo sería viable con acceso anónimo alternativo y decisión expresa sobre esa diferencia.
- Afecta RF-001/007/009, RNF-001 y criterio 2. Elegir ubicación no autoriza por sí solo a debilitar la comparación. El usuario debe elegir mantener el 0 absoluto o aprobar la excepción concreta antes de continuar.

### D3 — Persistencia [NECESITA ACLARACIÓN]

- **A — Recomendación: cookie opcional de preferencia, legible al entregar la página, con duración de un año y alcance del sitio.** Se escribe solo tras elegir, sin identidad, con atributos de seguridad adecuados; permite que el primer pintado respete una elección explícita sin script adicional. No requiere backend ni sesión.
- B — Almacenamiento local del navegador. No se envía al servidor, pero requiere otra solución previa al primer pintado para no mostrar primero el tema incorrecto.
- C — Solo memoria de navegación/contexto actual; al recargar se vuelve a D1. Menos persistencia, pero sin almacenamiento durable.
- Afecta RF-005/006/014/015. Si se elige Sistema, guardar esa elección no equivale a que el servidor conozca la apariencia efectiva del dispositivo.

### D4 — Alcance y campo de juego [NECESITA ACLARACIÓN]

- **A — Recomendación: todas las vistas de la app** (públicas, acceso/invitaciones/cuenta, organización, Workspace, operación/asistentes, administración y errores) con tema claro, preservando el césped como isla gráfica de contraste propio, no diálogos o paneles oscuros. Evita saltos de apariencia al navegar; escudos y fotos conservan su contenido.
- B — Solo públicas y Workspace, con resto oscuro declarado como excepción. Menor alcance, con cambios de apariencia al pasar por cuenta/acceso/admin que deben comunicarse y aceptarse.
- C — Todas las vistas, incluido reinterpretar también el terreno en una paleta clara. Más cambio visual sin necesidad funcional demostrada; exige otra propuesta y validación del campo.
- Afecta RF-008/010/011/012, RNF-002 y matriz de aceptación. La paleta calculada propone A; no presupone su aprobación.
