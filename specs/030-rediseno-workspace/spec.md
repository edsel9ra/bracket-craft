# Spec 030 — Rediseño del Workspace

Estado: implementada (2026-11-11; T1–T10 completas)

Depende de: spec 029 (implementada; PR #41, #42 y #43).

Entregas: [PR #44](https://github.com/edsel9ra/bracket-craft/pull/44) (T1–T3), [PR #47](https://github.com/edsel9ra/bracket-craft/pull/47) (T4–T5), [PR #48](https://github.com/edsel9ra/bracket-craft/pull/48) (T6–T8) y PR D (T9–T10), esta entrega en `devin/1794409672-spec-030-asistentes-cierre`. El PR D no se abre por instrucción del usuario; su número y el gate E2E de CI se incorporarán al abrirlo. La implementación se cierra con las verificaciones locales y evidencias de `tasks.md` y `docs/inspeccion-accesibilidad.md` §11; no se declara ejecutado el gate de un PR inexistente.

## Contexto y objetivo

El Workspace es donde trabajan los organizadores, operadores y árbitros. Funciona, pero su composición viene de la portada pública. El inventario del 2026-11-11, hecho sobre `main` con el stack demo a 1440×900 y 390×844, midió lo siguiente:

- **Cabeceras de marketing.** Cada pantalla abre con un titular de gran cuerpo («Construye la competencia por capas.»). La cabecera ocupa 259–423 px en escritorio y 225–320 px en móvil, sin contar la barra superior, las migas y el selector de sección. En calendario y plantillas el contenido principal queda por debajo de lo visible sin desplazarse en ambos tamaños, y en configuración y miembros, en móvil.
- **Operación de partido en móvil.** El recorrido mide 3831–6167 px de alto según el estado. El marcador queda separado del nombre de los equipos y, en vivo, se muestra como «— : —» al margen derecho. Las acciones principales quedan lejos del inicio: iniciar segmento a 1390 px; en vivo, guardar la planilla a 2521 px y cerrar el acta a 4520 px. Entre ellas no hay un índice ni un acceso directo.
- **Páginas monolíticas.** `pages/workspace/matches/[id].vue` tiene 2125 líneas (script de 1681) y `pages/workspace/tournaments/[id]/index.vue`, 1121. Las decisiones de negocio ya están en funciones puras de `utils/`, pero el estado, la orquestación de peticiones y la plantilla siguen en un único componente.
- **Pendientes de la spec 029.** La operación y los asistentes (RulesEditor, RulesWizard, TeamsWizard, StageTeamsWizard y `wizard/*`; 5213 líneas en total) siguen fuera de las escalas del sistema de diseño, con 256 valores fuera de escala. Figuran en `PENDING_MIGRATION` del guardián `design-scales.test.ts`.

**Objetivo:** que el Workspace sea una herramienta de trabajo densa y clara, en especial la operación de partido en móvil. Para ello hay que compactar las cabeceras, dar a la operación una estructura con el marcador y la acción principal siempre a mano, dividir las páginas grandes en componentes enfocados y completar la migración a las escalas de la spec 029. Todo ello **sin cambiar reglas deportivas, API, permisos, datos ni la matriz pública**.

## Usuarios

Miembros de una organización que usan el Workspace: dueños, administradores, operadores, árbitros y observadores. Las vistas públicas, la autenticación y `/admin` no cambian.

## Roles y visibilidad

No aplica: cada rol ve y puede hacer exactamente lo mismo que ahora. Las acciones que un rol no puede ejecutar siguen ocultas o deshabilitadas con los mismos criterios.

## Historias de usuario

- HU-1. Como operador en la banda con el móvil, quiero ver siempre el marcador, el estado y el minuto del partido, y tener a mano la acción que toca ahora, para registrar el partido sin desplazarme por toda la página.
- HU-2. Como organizador, quiero que cada pantalla del Workspace muestre su contenido principal (checklist, calendario, plantillas, miembros) nada más abrirla, para trabajar sin desplazarme primero.
- HU-3. Como operador, quiero saltar directamente a la sección del acta que necesito (campo, planilla, eventos, cierre), para no perderme en un formulario largo.
- HU-4. Como persona que mantiene el producto, quiero que la operación y la configuración estén divididas en componentes con una sola responsabilidad, para cambiar una sección sin tocar dos mil líneas.

## Definiciones

- **Cabecera compacta:** encabezado de página del Workspace formado por el contexto (migas o rótulo), un título de tamaño de sección y, si procede, un estado y las acciones de página. No incluye titulares de marketing ni descripciones promocionales.
- **Barra de partido:** franja de la operación con los dos equipos, el marcador, el estado y el segmento o minuto en curso. Siempre está visible mientras se recorre la operación.
- **Acción principal:** la siguiente acción que el estado del partido permite al rol actual, con la misma lógica de habilitación que hoy (por ejemplo: iniciar segmento, guardar planilla, añadir evento, cerrar acta).
- **Sección del acta:** cada uno de los bloques actuales de la operación: resolución prevista, 01 Preparar campo, 02 Plantillas, 03 Planilla, 04 Eventos y 05 Cierre.

## Requisitos funcionales

### Cabeceras del Workspace

- RF-001: EL SISTEMA muestra en todas las pantallas del Workspace (listado, configuración, calendario, plantillas, miembros y operación) una cabecera compacta, incluido el listado `/workspace` (HD-1), en lugar del titular de marketing actual.
- RF-002: A 1440×900 y a 390×844, con los datos demo, EL SISTEMA muestra el inicio del contenido principal de cada pantalla del Workspace dentro de la primera pantalla visible, sin desplazarse. En plantillas, calendario y miembros, el contenido principal es la lista: los formularios quedan detrás, con acceso directo en la cabecera (LY-1).
- RF-003: La cabecera compacta conserva la información de contexto que se ve hoy (torneo, versión o estado publicado, formato declarado y fase/jornada en la operación) y la jerarquía de encabezados accesible (un único `h1` por página).

### Operación de partido

- RF-004: EL SISTEMA muestra la barra de partido con ambos equipos, marcador, estado y segmento o minuto. MIENTRAS el usuario recorre la operación, la barra permanece visible.
- RF-005: CUANDO el partido no tiene goles registrados, EL SISTEMA muestra el marcador «0 – 0» si hay un segmento iniciado y una marca neutra de «sin empezar» si no lo hay; en ningún caso un marcador vacío en vivo.
- RF-006: EL SISTEMA ofrece un índice de las secciones del acta que permite saltar a cada una con teclado y lectores de pantalla, e indica en qué sección se encuentra el usuario.
- RF-007: EN pantallas estrechas, EL SISTEMA mantiene accesible la acción principal desde cualquier punto de la operación, sin tener que desplazarse hasta su sección: las secciones siguen apiladas en el orden actual, con la barra de partido fija arriba, el índice de secciones bajo ella y una barra inferior fija con la acción principal (OP-1).
- RF-008: EL SISTEMA muestra los nombres de equipo sin partir palabras. Los nombres largos se recortan de forma legible, con el nombre completo disponible para lectores de pantalla y como texto alternativo.
- RF-009: La operación conserva exactamente su comportamiento actual: las mismas peticiones y sus cuerpos, las validaciones, los borradores locales, el tiempo real, los diálogos de confirmación, los bloqueos y los mensajes.

### Estructura del código

- RF-010: EL SISTEMA divide `pages/workspace/matches/[id].vue` en componentes por sección del acta y en composables de estado y orquestación. Ningún archivo resultante supera **600** líneas (SP-1).
- RF-011: EL SISTEMA divide `pages/workspace/tournaments/[id]/index.vue` en componentes por bloque (resumen y versión, checklist, reglas, equipos y escudos, fases). Ningún archivo resultante supera **600** líneas.
- RF-012: La división no cambia la interfaz pública de los componentes que ya se reutilizan ni la lógica de `utils/`. Las funciones puras se reutilizan y no se duplican.

### Migración pendiente de la spec 029

- RF-013: EL SISTEMA aplica las escalas y piezas de la spec 029 a la operación de partido y a los asistentes (RulesEditor, RulesWizard, TeamsWizard, StageTeamsWizard y `wizard/*`). `PENDING_MIGRATION` queda vacía y el guardián recorre todo `frontend/app/`.
- RF-014: Los asistentes conservan su flujo actual (pasos, validación, borradores, navegación por teclado y foco). En ellos solo cambia la presentación (escalas, piezas y cabecera compacta del contenedor) (WZ-1).

## Requisitos no funcionales

- RNF-001: Pasan `pnpm test`, `pnpm run typecheck`, `pnpm run lint`, `pnpm run build`, `pnpm run typecheck:e2e` y el job `e2e` de CI.
- RNF-002: axe-core no da violaciones nuevas de aplicación respecto a la revisión 029 en las pantallas afectadas, a 1440×900 y 390×844.
- RNF-003: La barra de partido y la acción principal fijas no tapan el foco del teclado (WCAG 2.2 2.4.11), dejan espacio al contenido final y respetan `prefers-reduced-motion`.
- RNF-004: La operación en móvil reduce al menos un **40 %** la distancia desde el inicio hasta la primera acción principal de cada estado (programado, en vivo y cerrado) respecto a las mediciones del inventario.
- RNF-005: Los tests estáticos existentes que inspeccionan el código fuente de la operación o de la configuración se adaptan a la nueva estructura sin perder ninguna aserción de comportamiento.

## Datos personales y privacidad

No cambia: se muestran los mismos datos, con los mismos permisos.

## Casos límite

- Partido cerrado o con walkover/resolución administrativa: la barra muestra el resultado final y no hay acción principal de edición.
- Rol observador o árbitro sin permiso de operar: la barra se ve, pero no aparece ninguna acción principal que el rol no pueda ejecutar.
- Pérdida y recuperación del tiempo real: la barra muestra el mismo estado de conexión que hoy («Reintentando…», etc.).
- Teclado virtual abierto en móvil: la acción fija no tapa el campo enfocado.
- Nombres de equipo muy largos o sin escudo.
- Borrador local restaurado al volver a la operación: se conserva la sección.

## Fuera de alcance

- Cambios en reglas, motor (`engine_version` 2026.1), API, esquema, permisos o la matriz pública.
- Vistas públicas, autenticación y `/admin` (ya migradas en la spec 029).
- Tema claro (opción 5) y pulido del bracket público (opción 4).
- Nuevas funciones de operación (atajos de eventos, cronómetro propio, modo sin conexión).

## Criterios de finalización

- RF y RNF cumplidos con sus verificaciones.
- Capturas antes/después en cada PR a 1440×900 y 390×844, con las mediciones de RF-002 y RNF-004.
- `PENDING_MIGRATION` vacía y el guardián de escalas recorriendo todo `frontend/app/`.
- `AGENTS.md`, `docs/inspeccion-accesibilidad.md` y `MEMORY.md` actualizados.

## Decisiones registradas

- **OP-1 (2026-11-11):** en la operación, las secciones siguen apiladas, con la barra de partido fija arriba, un índice de secciones y la acción principal fija abajo.
- **HD-1 (2026-11-11):** cabecera compacta en todas las pantallas del Workspace, incluido el listado; el titular grande queda solo en la portada pública.
- **LY-1 (2026-11-11):** en plantillas, calendario y miembros, la lista precede al formulario de alta/invitación/partido. El slot de acciones de PageHeader ofrece «Añadir jugador», «Añadir partido» o «Invitar» (es/en), solo si el rol puede usar el formulario, mediante un enlace de ancla a su id que enfoca el primer campo o un encabezado con tabindex -1. Sin animación con reduced-motion; sin cambios de peticiones, validaciones ni textos existentes.
- **SP-1 (2026-11-11):** se dividen la operación de partido y la configuración del torneo, con un máximo de 600 líneas por archivo.
- **WZ-1 (2026-11-11):** en los asistentes solo se migra la presentación a las escalas, sin cambiar su flujo.

## Dudas abiertas

Ninguna.
