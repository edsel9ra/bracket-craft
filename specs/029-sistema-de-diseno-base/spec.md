# Spec 029 — Sistema de diseño base

Estado: aprobada (2026-11-11; DT-1, MG-1, VI-1 y RV-1 resueltas)

## Contexto y objetivo

La interfaz tiene una identidad visual reconocible (tema oscuro, acento lima, titulares de gran cuerpo), pero no la sostiene un sistema común. La auditoría de interfaz del 2026-11-11 (opción 2) midió lo siguiente:

- Solo hay dos piezas compartidas de interfaz (campo de formulario y mensaje de error). Botones, tarjetas y paneles, píldoras de estado, pestañas, tablas y estados vacíos se redefinen en cada pantalla. Por ejemplo, el estilo de panel se repite en nueve pantallas.
- Hay **40 tamaños de letra** distintos, unos **10 radios de borde** (8, 9, 10, 12, 16, 20, 24 px, 0.75 rem, 999 px, 50 %) y **10 puntos de corte** responsivos (375 a 1000 px). Además hay **9 colores fijos** fuera de la paleta declarada.
- La tipografía declarada («Avenir Next») no se distribuye con la aplicación, así que cada sistema operativo la sustituye por otra y la marca se ve distinta según el dispositivo.
- Las confirmaciones de acciones críticas (publicar una versión, regenerar el calendario, reemplazar reglas, cerrar el acta, retirar el consentimiento de imagen, eliminar un escudo, descartar cambios de un asistente, salir con un borrador sin guardar…) usan el diálogo nativo del navegador en **19 lugares**. No sigue el estilo ni el idioma de la interfaz y no puede explicar las consecuencias de la acción.

**Objetivo:** dotar al frontend de un sistema de diseño base, formado por escalas cerradas de tipografía, espaciado, radios, colores y puntos de corte, una tipografía propia distribuida con la aplicación y un conjunto mínimo de piezas reutilizables, entre ellas un diálogo de confirmación propio. Las pantallas existentes se migran a ese sistema **sin cambiar comportamiento, permisos, datos ni contratos** y conservando la identidad visual actual. Esta spec es la base de la opción 3 (rediseño del Workspace), que tendrá spec propia.

## Usuarios

Todas las personas que usan la interfaz: público anónimo, miembros de organización (operadores, árbitros, observadores, administradores y dueños) y administradores de plataforma.

## Roles y visibilidad

No aplica: la spec no cambia qué ve ni qué puede hacer ningún rol. Cada pantalla sigue mostrando los mismos datos con los mismos permisos.

## Historias de usuario

- HU-1. Como cualquier usuario, quiero que la aplicación se vea igual en cualquier dispositivo y navegador, para reconocer la marca y leer con comodidad.
- HU-2. Como operador, quiero que una acción crítica me pida confirmación dentro de la propia interfaz, en mi idioma y explicando qué va a pasar, para no ejecutarla por error.
- HU-3. Como usuario de teclado o lector de pantalla, quiero que botones, pestañas, diálogos y tablas se comporten igual en todas las pantallas, para no tener que aprender cada una.
- HU-4. Como persona que mantiene el producto, quiero escalas cerradas y piezas reutilizables, para que un cambio visual se haga en un único lugar.

## Definiciones

- **Escala:** lista cerrada y nombrada de valores permitidos para una propiedad visual (tamaños de letra, espaciados, radios, colores, puntos de corte). Fuera de la escala no se admiten valores literales, salvo las excepciones listadas en RF-006.
- **Pieza reutilizable:** elemento de interfaz definido una sola vez y usado desde varias pantallas, con variantes cerradas. Esta spec define: botón, superficie (panel o tarjeta), píldora de estado, pestañas, tabla, estado vacío/cargando/error y diálogo de confirmación.
- **Diálogo de confirmación:** ventana modal propia que pide confirmar o cancelar una acción. Muestra un título, la consecuencia de la acción y dos acciones con verbo explícito (por ejemplo «Publicar versión» / «Cancelar»).
- **Identidad visual actual:** tema oscuro, acento lima, titulares de gran cuerpo y la composición de cada pantalla tal como estaban en `main` antes de esta spec.

## Requisitos funcionales

### Escalas

- RF-001: EL SISTEMA define una escala tipográfica de un máximo de **8** tamaños, cada uno con su interlineado y peso. Todos los textos de la interfaz usan un tamaño de esa escala.
- RF-002: EL SISTEMA define una escala de espaciado de un máximo de **10** valores, y todos los márgenes, rellenos y separaciones entre elementos la usan.
- RF-003: EL SISTEMA define una escala de radios de borde de un máximo de **4** valores, más el círculo/píldora.
- RF-004: EL SISTEMA define una paleta cerrada que incluye los colores semánticos de éxito, aviso, error, equipo local y equipo visitante. Todo color de la interfaz procede de ella; los 9 colores fijos actuales se incorporan a la paleta o se sustituyen.
- RF-005: EL SISTEMA define un máximo de **4** puntos de corte responsivos, y toda adaptación a pantalla los usa.
- RF-006: SI una pantalla necesita un valor fuera de escala (por ejemplo, la geometría del campo de juego de las formaciones), ENTONCES ese valor queda documentado como excepción en el propio componente, y una verificación automática enumera las excepciones permitidas.

### Tipografía

- RF-007: EL SISTEMA distribuye su propia tipografía con la aplicación, sin depender de servicios externos, de modo que el texto se ve con la misma familia en cualquier sistema operativo.
- RF-008: MIENTRAS la tipografía propia no ha cargado, EL SISTEMA muestra el texto con una fuente de sustitución de métricas similares, sin bloquear ni ocultar el contenido.
- RF-009: EL SISTEMA usa como máximo dos familias tipográficas, con funciones claramente distintas: la principal es **Archivo** (licencia OFL), con su ancho normal para el texto y el ancho condensado para titulares, marcadores y cifras (DT-1); la segunda, si hace falta, es una monoespaciada del sistema para código o JSON.

### Piezas reutilizables

- RF-010: EL SISTEMA ofrece un **botón** con variantes cerradas (principal, secundaria, peligro, discreta) y estados de reposo, foco visible, deshabilitado y en curso. Mientras está en curso no admite una segunda pulsación.
- RF-011: EL SISTEMA ofrece una **superficie** (panel/tarjeta) con un número cerrado de niveles de elevación.
- RF-012: EL SISTEMA ofrece una **píldora de estado** con variantes semánticas (neutro, éxito, aviso, error, en vivo). El estado no se transmite solo con el color: siempre lleva texto o icono con texto accesible.
- RF-013: EL SISTEMA ofrece **pestañas** accesibles. El teclado sigue el patrón de pestañas: flechas para moverse, Inicio/Fin para ir a los extremos, y solo la pestaña activa recibe el tabulador.
- RF-014: EL SISTEMA ofrece una **tabla** con cabeceras asociadas a sus celdas y desplazamiento horizontal accesible, reutilizando la región de desplazamiento introducida en el PR #40.
- RF-015: EL SISTEMA ofrece **estados vacío, cargando y error** comunes. El de carga se anuncia como estado, el de error como alerta, y el de error ofrece «Reintentar» cuando la acción lo admite.
- RF-016: CUANDO una pantalla necesita uno de estos elementos, EL SISTEMA usa la pieza reutilizable y no una redefinición local.

### Diálogo de confirmación

- RF-017: CUANDO el usuario inicia una de las acciones que hoy piden confirmación con el diálogo nativo, EL SISTEMA muestra el diálogo de confirmación propio con título, consecuencia y dos acciones con verbo explícito, en el idioma activo.
- RF-018: MIENTRAS el diálogo está abierto, EL SISTEMA mueve el foco a él, lo mantiene dentro, impide interactuar con el fondo y lo cierra con Escape o con «Cancelar» como equivalente a cancelar. Al cerrarse, devuelve el foco al control que lo abrió.
- RF-019: CUANDO el usuario confirma, EL SISTEMA ejecuta la acción exactamente como hoy. CUANDO cancela, EL SISTEMA no envía ninguna petición ni cambia ningún estado.
- RF-020: SI la acción es destructiva o irreversible (regenerar calendario, reemplazar reglas, eliminar escudo, retirar consentimiento de imagen, cerrar acta, publicar, desactivar en administración, revocar invitación, descartar cambios o un borrador), ENTONCES la acción de confirmar usa la variante de peligro y el foco inicial va a «Cancelar».
- RF-021: EL SISTEMA no usa diálogos nativos del navegador (`confirm`, `alert`, `prompt`) en ninguna pantalla, incluidas la operación de partido y los asistentes (MG-1). Queda fuera solo el aviso de `beforeunload` al cerrar la pestaña o recargar, porque el navegador no permite sustituirlo.

### Migración

- RF-022: EL SISTEMA aplica las escalas y piezas en todas las pantallas públicas, de autenticación, de cuenta, de organización, del Workspace y de administración, conservando la identidad visual actual. **Excepción (MG-1):** la operación de partido y los asistentes (reglas, equipos, fases y su contenedor) no se migran en esta spec y quedan para la spec de la opción 3; solo reciben el diálogo de confirmación. Se admiten diferencias pequeñas debidas a la normalización a la escala (VI-1), revisadas con capturas antes/después en el PR (RV-1); no hay regresión visual automatizada.
- RF-023: La migración no altera textos de la interfaz salvo los nuevos del diálogo de confirmación, ni la navegación, los permisos, las llamadas a la API o los datos mostrados.

## Requisitos no funcionales

- RNF-001: La verificación del frontend que exige la constitución sigue pasando: `pnpm test`, `pnpm run typecheck`, `pnpm run build`, `pnpm run lint` y el job `e2e` de CI.
- RNF-002: Las verificaciones automáticas de escalas (RF-001 a RF-006) y de ausencia de diálogos nativos (RF-021) forman parte de `pnpm test`.
- RNF-003: axe-core, en las páginas del informe de accesibilidad, no muestra violaciones nuevas respecto de la revisión del PR #40.
- RNF-004: Los textos y fondos de la paleta cumplen contraste WCAG 2.1 AA (4.5:1 para texto normal y 3:1 para texto grande y componentes). Se verifica midiendo los pares de la paleta y no solo con axe.
- RNF-005: El peso total de la tipografía distribuida no supera **120 kB** (woff2, solo los pesos y subconjuntos latinos usados).
- RNF-006: La política de seguridad de contenidos de producción sigue sin permitir orígenes externos. La tipografía se sirve desde el propio origen.
- RNF-007: Se respeta `prefers-reduced-motion` en todas las piezas nuevas, incluida la apertura y el cierre del diálogo.

## Datos personales y privacidad

No aplica: no se tratan, muestran ni exponen datos nuevos. Las proyecciones públicas y la matriz de acceso de la spec 020 no cambian.

## Casos límite

- Un diálogo de confirmación abierto cuando llega un evento en tiempo real que recarga la pantalla: el diálogo se mantiene hasta que el usuario decide, y la acción confirmada se ejecuta sobre el estado vigente, igual que hoy tras el `confirm` nativo.
- Navegar a otra ruta (botón atrás) con el diálogo abierto: el diálogo se cierra como cancelación.
- Doble pulsación en «Confirmar»: la acción se ejecuta una sola vez.
- Textos largos en el diálogo o en un botón (traducción inglesa, nombre de equipo largo): se ajustan sin desbordar a 320 px de ancho.
- Navegadores sin la tipografía propia en caché, o con la descarga bloqueada: se aplica la sustitución de RF-008.
- Pruebas E2E que hoy aceptan el diálogo nativo (`page.once('dialog')`) se adaptan al diálogo propio.

## Fuera de alcance

- Rediseño de la composición de pantallas, cabeceras compactas, densidad del Workspace y dividir las páginas grandes en componentes: opción 3, con spec propia.
- Bracket con conectores, héroe del torneo con datos en vivo y estadísticas en vista de tarjetas: opción 4.
- Tema claro o de alto contraste: opción 5.
- Cambios de copy, salvo los textos del diálogo de confirmación.
- Cualquier cambio de backend, API, esquema o permisos.

## Criterios de finalización

- Las verificaciones automáticas de RNF-002 pasan, sin excepciones de escala fuera de la lista documentada.
- No queda ningún uso de diálogo nativo (`grep` vacío y test de RF-021 en verde).
- Las 19 confirmaciones actuales usan el diálogo propio y el E2E de operación pasa con él.
- Las capturas antes y después de las pantallas del informe muestran la misma identidad visual (revisión del usuario).
- La medición de contraste de la paleta está registrada en `docs/inspeccion-accesibilidad.md`.
- Los jobs de CI están en verde.

## Decisiones registradas

- **DT-1 (2026-11-11):** tipografía Archivo (OFL), distribuida con la aplicación; ancho condensado para titulares y marcadores.
- **MG-1 (2026-11-11):** se migran todas las pantallas excepto la operación de partido y los asistentes, que pasan a la spec de la opción 3. El diálogo de confirmación se aplica en los 19 sitios.
- **VI-1 (2026-11-11):** se admiten diferencias pequeñas por normalización a la escala, revisadas con capturas.
- **RV-1 (2026-11-11):** la revisión visual se hace con capturas antes/después en el PR, sin regresión visual automatizada en CI.

## Dudas abiertas

Ninguna.
