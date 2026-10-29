# Spec 025 — Orden, rótulos, ancla y enlaces del recorrido de configuración

Estado: aprobada

> **Nota de nombre.** Esta spec se redactó como `specs/025-orden-de-configuracion` y el 2026-10-28 se renombró a `specs/025-recorrido-de-configuracion`. No queda ninguna carpeta con el nombre anterior ni ninguna referencia a él. El número `025` no cambia; el estado sigue siendo `aprobada`.

> **Nota de división (2026-10-28).** La redacción anterior de esta spec cubría también la **cadena de avance** entre secciones, el **aviso de minutos** con sus dos controles y la **cifra de composición** de una fase. El usuario aprobó **dividir** ese alcance en dos specs para respetar el máximo de diez tareas: esta **025** se queda con el **reordenado y su presentación y navegación estática** —orden de los asistentes, numeración visible, lista de verificación, ancla `#fases`, enlaces cruzados y no regresión de «Siguiente»/«Anterior»— y es **autocontenida y desplegable por sí sola**; la **026** (`specs/026-cadena-de-avance-y-cifra/`) recibe la cadena de avance, el aviso de minutos y la cifra de composición, y **depende de esta 025** porque usa su ancla `#fases` y su numeración. No queda ningún requisito huérfano ni duplicado: cada uno vive en una sola spec. Las decisiones de clarificación se reparten igual: **ORD-1, ORD-2 revisada de nuevo y ORD-3** aquí; **ORD-4 a ORD-14** en la 026. De **ORD-13** esta spec aplica **solo la parte de los enlaces cruzados** (no nombrar paso en la dirección) y la declara como compartida, sin reescribirla.

## Contexto y objetivo

La configuración de un torneo en borrador se organiza hoy, de arriba abajo, como **Reglas → Fases → Equipos**. Ese orden no acompaña a las dependencias reales del producto: las **reglas** relevantes para dar de alta equipos son los **límites de plantilla** —mínimo y máximo de jugadores, spec 024—, que bloquean la inscripción de un equipo en una fase y la apertura del partido; y los **equipos** deben existir para poder inscribirlos en una **fase**. El **formato de juego** (`game_format`) **no** interviene aquí: no se aplica al alta de equipos ni a la inscripción, y esta spec no lo toca. Con el orden actual el usuario se encuentra primero con la composición de una fase —que solo admite equipos ya registrados— y después con el alta de esos equipos, de modo que el recorrido natural obliga a saltar hacia atrás.

**Objetivo:** que el recorrido de configuración de un torneo en borrador siga el orden **Reglas → Equipos → Fases**, que la **numeración visible** de las secciones y la **lista de verificación previa a la publicación** cuenten esa misma secuencia, que la sección de fases tenga **ancla propia `#fases`** para que se pueda enlazar a ella desde el alta de equipos y desde plantillas, y que ese reordenado **no degrade la navegación de los asistentes**: cada asistente conserva su propio recorrido de pasos y su botón «Siguiente» avanza únicamente dentro de él, sin saltar a otro asistente ni a otra sección.

### Qué cambia y qué no

**Se reordena (decisiones ORD-3 y —en su parte de presentación— ORD-1):**

1. Los **tres asistentes** de la configuración dentro de `/workspace/tournaments/{id}`.
2. La **numeración visible** de los rótulos de sección, que pasa a «01 · Reglas», «02 · Equipos», «03 · Fases» y «04 · Calendario» (ORD-1). El rótulo **«03 · Fases» es un elemento visible nuevo**: su clave de traducción existe hoy, pero no se pinta en ninguna vista.
3. La **lista de verificación previa a la publicación** de esa misma pantalla, que cuenta la misma secuencia.
4. El **orden de los apartados** del manual de usuario (`docs/manual-usuario.md`), coherente con el recorrido nuevo.

**Se añade (decisiones ORD-2 revisada de nuevo, ORD-3 y la parte de enlaces de ORD-13):**

5. Un **ancla propia `#fases`** para la sección de fases, **sin ninguna entrada nueva en el índice del torneo** (ORD-2 revisada de nuevo).
6. Los **enlaces cruzados equipos → fases y plantillas → fases** apuntan al ancla `#fases` **sin nombrar ningún paso**; el asistente de fases resuelve su **paso de entrada** con su mecanismo actual (ORD-13, parte de enlaces).

**No se reordena ni se toca:** los pasos internos de cada asistente, su contenido, su obligatoriedad y sus validaciones; las direcciones y los parámetros de la configuración (no se añade ninguna **ruta** ni ningún **parámetro** —solo el fragmento `#fases`, ORD-2 revisada de nuevo); el índice del torneo, que **conserva sus entradas** (RF-005); el orden de las peticiones existentes; los avisos de la 012, con su texto, condición y anuncio; el calendario y las plantillas, salvo el número del rótulo del calendario (ORD-1); los permisos; el contrato HTTP; el esquema y los datos.

### Relación con la spec 012 — aditiva y sin matices

La spec 012 define los tres asistentes (reglas, fases y equipos), el paso en la dirección compartida (`?step=`), el borrador de pestaña, las confirmaciones, las anclas `#configuracion` y `#equipos` y la accesibilidad. **No fija** un orden visible entre los tres asistentes, ni una numeración de secciones, ni un ancla para la sección de fases, ni el destino de los enlaces cruzados.

Esta spec es **aditiva**: no deroga, sustituye, matiza ni reescribe ningún requisito de la 012. Añade lo que la 012 no fijaba y **verifica sin cambio** los cuatro requisitos que su cambio podría rozar:

| Requisito de la 012 | Cómo queda |
|---|---|
| **RF-018** — el índice marca como activa solo la sección abierta y ofrece una entrada por sección | **Vigente sin matiz.** No se añade ninguna entrada al índice: el ancla `#fases` **no** tiene entrada propia (RF-005), la sección activa sigue siendo **Configuración** y sigue habiendo una sola entrada por sección. |
| **RF-020** — los fragmentos antiguos redirigen a su dirección nueva; los de resumen, configuración, **fases** y equipos siguen resolviendo sobre la configuración | **Vigente sin cambios.** `#fases` **no redirige**: resuelve sobre la configuración, como la 012 ya declaraba, y desde esta spec nombra un bloque real (RF-004). |
| **RNF-005** — accesibilidad verificable en el escenario de navegador de operación y cierre | **Vigente.** El escenario no cambia: esta spec no altera pasos, foco de paso ni anuncios de la 012 (RNF-003). |
| **RNF-008** — continuidad del arnés de extremo a extremo | **Vigente sin cambio.** El arnés **no se toca**: ninguno de sus anclajes depende del orden, de los rótulos numerados ni del enlace cruzado (RNF-002). |

Ningún otro requisito de la 012 cambia: pasos, obligatoriedad, estados del índice, `?step=`, borradores, confirmaciones, permisos, anclas existentes, traducciones, avisos y accesibilidad **siguen vigentes y sin modificar** (RF-015).

### Discrepancia declarada en el estado verificado de la 012

El apartado «Estado verificado (2026-10-22)» de la 012 registró dos datos que **ya no describen** el producto actual y en los que esta spec **no se apoya**:

1. Registró las secciones como «01 · Fases», «02 · Equipos» y «03 · Calendario». Hoy el bloque del asistente de fases **no pinta ningún rótulo numerado** —su clave de traducción existe, pero no se usa en ninguna vista—, así que **«03 · Fases» es un rótulo visible nuevo** que esta spec añade al marcado (RF-003).
2. Registró que el bloque de plantillas se rotulaba «04 · Plantillas» y aparecía **antes** del calendario. Hoy la pantalla de plantillas no lleva número en su rótulo (se rotula «Plantillas» / «Rosters»).

Por eso esta spec fija que: plantillas queda **fuera** de la secuencia y conserva su rótulo actual; el `04` corresponde al calendario en **su ruta propia**, no al documento de configuración (RF-003); y «03 · Fases» se pinta por primera vez como parte del cambio. Si al aplicar el cambio apareciera un número en el rótulo de plantillas, se retira en el mismo cambio. Es una discrepancia declarada, no una contradicción de requisitos.

## Usuarios

- **Administrador de organización con permiso de gestión de torneos:** recorre la configuración de arriba abajo y espera que el orden coincida con lo que necesita hacer —definir reglas, dar de alta equipos, componer las fases— y que los enlaces que ya usa le dejen viendo el bloque al que apuntan.
- **Observador (miembro sin permiso de gestión):** consulta la misma configuración en solo lectura; el orden y la numeración deben serle igual de legibles.
- **Operador de partido, árbitro y público:** no acceden a esta pantalla; no se ven afectados.
- **Mantenedor del producto o redactor de la documentación:** necesita una **fuente normativa única** del recorrido y que las demás piezas documentales remitan a ella sin repetir la secuencia.

## Roles y visibilidad

- **Público:** No aplica. La pantalla es del Workspace y no se publica ningún dato nuevo.
- **Miembro sin rol:** conserva el contrato vigente (**403** en toda ruta protegida); esta spec no le concede ni le retira contexto.
- **Observador (`viewer`):** ve los tres asistentes **en el mismo orden nuevo**, la misma numeración, el ancla y el índice sin entradas nuevas, en solo lectura; puede seguir los enlaces cruzados, que solo mueven la vista. **No** gana ninguna acción de escritura (RF-016).
- **Administrador y dueño:** sin cambio de permisos ni de capacidades; conservan todas las escrituras actuales.
- **Administrador de plataforma:** No aplica; `/admin` queda fuera del alcance.
- **Aislamiento:** sin cambios. La pantalla sigue mostrando solo el torneo de la organización activa y no añade rutas de datos ni acepta identificadores de otra organización; ningún enlace cruzado cruza de torneo ni de versión (RF-013).

## Historias de usuario

- **HU-1.** Como administrador, quiero encontrarme las reglas primero, luego los equipos y solo después las fases, para no tener que retroceder al inscribir equipos que aún no he dado de alta.
- **HU-2.** Como administrador, quiero que el botón «Siguiente» de un asistente me lleve al paso siguiente **de ese asistente**, para no acabar en otro formulario por un cambio de orden.
- **HU-3.** Como administrador, quiero que la numeración y los rótulos de las secciones sigan contando una sola secuencia coherente, para saber dónde estoy.
- **HU-4.** Como observador, quiero ver la configuración en el mismo orden aunque no pueda editar, para leer el recorrido completo.
- **HU-5.** Como mantenedor del producto, quiero que el orden esté declarado en una sola fuente normativa y verificado por una prueba, para que no vuelva a divergir de la numeración.
- **HU-6.** Como administrador, quiero que el enlace a las fases —desde el alta de equipos y desde plantillas— me deje viendo el bloque de fases y no el formulario de reglas, para saber que he llegado a la sección correcta.

## Definiciones

- **Recorrido de configuración:** orden en que se presentan los tres asistentes de la configuración de un torneo (reglas, equipos y fases), tanto en el documento como en el orden de lectura con teclado y lector de pantalla.
- **Asistente:** recorrido de un formulario dividido en pasos ordenados con índice, navegación anterior/siguiente y confirmación, según la definición de la spec 012. Esta spec **no** redefine qué es un asistente ni sus pasos.
- **Paso en la dirección:** representación del paso actual de un asistente en la dirección de la página, según la spec 012. Los tres asistentes de la configuración **comparten un único paso en la dirección**.
- **Paso de entrada:** paso que un asistente muestra cuando la dirección no nombra un paso suyo. En el asistente de fases depende del **estado del borrador**: identificación cuando la versión aún no tiene fases y composición cuando ya las tiene, con la identificación en solo lectura. Esta spec **no define ni calcula** ese paso: lo usa tal como el asistente lo resuelve hoy, y **no lo escribe en la dirección** desde el enlace cruzado (RF-013).
- **Sección numerada:** cada uno de los cuatro rótulos con prefijo numérico visible del recorrido: **Reglas (01)**, **Equipos (02)** y **Fases (03)** en el documento de configuración, y **Calendario (04)** en la pantalla de calendario, que ya tiene dirección propia. Es presentación: no identifica recursos ni contratos. **«03 · Fases» es un rótulo visible nuevo** (RF-003).
- **Numeración visible de sección:** prefijo `NN · ` que precede al rótulo de una sección numerada, con dos dígitos y un separador `·` entre espacios. La secuencia es exactamente `01`…`04`, sin huecos y sin repeticiones (ORD-1).
- **Lista de verificación previa a la publicación (checklist operativa):** bloque de la configuración que resume el estado de la versión en borrador antes de publicar, con un ítem por comprobación y su detalle. Tiene cinco ítems —versión en borrador, equipos, fases, partidos y plantillas—, que antes de esta spec aparecían con los de fases y equipos en el orden inverso. Sus ítems, textos, umbrales y criterios de validez son los actuales; esta spec cambia **solo su orden** (ORD-3). El ítem «Equipos» **mide asignaciones de fase**, no altas de equipo, así que muestra `0` mientras no exista ninguna fase con equipos asignados; eso es su criterio actual y el reordenado no lo cambia (RF-006).
- **Apartado del manual:** cada sección numerada de `docs/manual-usuario.md`. Los apartados de configuración son los de reglas, equipos y plantillas, fases y calendario (ORD-3).
- **Enlace cruzado entre asistentes:** enlace que lleva de un asistente a otro (equipos → fases desde el alta de equipos y desde la pantalla de plantillas).
- **Ancla de la configuración:** fragmento de la dirección de la configuración que lleva a un bloque de la página. Tras esta spec son cuatro: `#resumen`, `#configuracion`, `#equipos` y **`#fases`** (ORD-2 revisada de nuevo). Un ancla no crea una ruta propia, no cambia la sección del torneo que se marca como activa y **no añade ninguna entrada al índice** del torneo (RF-005).
- **Índice del torneo:** lista de secciones del torneo que la pantalla ya ofrece —**cuatro** entradas de configuración (resumen, configuración, calendario y plantillas) más **operación solo cuando hay un partido en contexto**—. Esta spec **no** le añade, retira ni renombra entradas (RF-005).

## Decisiones de clarificación (2026-10-28)

Resueltas con el usuario **antes de la división** de la spec. Las que gobiernan esta 025 son **ORD-1**, **ORD-2 revisada de nuevo** y **ORD-3**; de **ORD-13** se aplica aquí **solo la parte de los enlaces cruzados**, declarada como compartida con la 026. Las decisiones **ORD-4 a ORD-14** pertenecen a la spec 026 y no se reproducen ni se reinterpretan aquí.

- **ORD-1 = A — Se renumera toda la secuencia y reglas recibe número.** Los cuatro rótulos visibles del recorrido pasan a ser **«01 · Reglas», «02 · Equipos», «03 · Fases» y «04 · Calendario»**, con el equivalente en inglés **«01 · Rules», «02 · Teams», «03 · Stages» y «04 · Schedule»** sobre las mismas claves de traducción. **«03 · Fases» se pinta por primera vez**: su clave existe hoy, pero no aparece en ninguna vista. La pantalla de plantillas queda **fuera** de la secuencia: conserva su rótulo actual sin número y no se le asigna un «05». *Descartadas:* retirar la numeración de todas las secciones (B), que pierde la referencia de posición que hoy usa el usuario; y dejar reglas sin número renumerando solo el resto (C), que deja una sección sin número en medio de una secuencia numerada y obliga a un caso especial permanente.
- **ORD-2 revisada de nuevo = A′ — Solo se añade el ancla `#fases`; el índice no gana entradas.** La corrección anterior había añadido además una entrada «Fases» al índice del torneo. Se **retira** esa parte: el índice conserva sus **cuatro** entradas de configuración —resumen, configuración, calendario y plantillas— más **operación solo cuando hay un partido en contexto**, la sección activa sigue siendo **Configuración** y la 012 RF-018 queda vigente **sin matiz**. El ancla resuelve el único problema real —que el enlace desde Equipos deje el bloque de fases a la vista— sin duplicar destinos en el índice ni abrir una segunda forma de llegar a un bloque que ya vive dentro de configuración. Se añade **un** fragmento, `#fases`, sin ruta, pantalla ni parámetro nuevos. *Descartadas:* mantener la entrada «Fases» en el índice (la elección anterior), que añade una segunda vía al mismo bloque y convierte el índice en un mapa de bloques internos; y (C) dar a fases una pantalla o una dirección propia, que multiplica las superficies de navegación y sale del alcance.
- **ORD-3 = A — El reordenado alcanza la lista de verificación y el manual.** Además de los tres asistentes, se reordena la **lista de verificación previa a la publicación** para que cuente la misma secuencia y se reordenan y renumeran los **apartados del manual de usuario**, de modo que pantalla y documentación cuenten una sola historia. *Descartada:* reordenar solo los asistentes y el manual y dejar la checklist como está (B), que mantiene en la misma pantalla dos secuencias contradictorias.
- **ORD-13 = A (parte de enlaces cruzados, compartida con la 026) — El enlace cruzado no escribe paso en la dirección.** El enlace equipos → fases y el de plantillas → fases **no fijan `?step=`**: dejan el **bloque de fases a la vista con el ancla `#fases`** y el **propio asistente resuelve su paso de entrada** con su mecanismo actual de la 012. Así hay **una sola fuente del paso** —la de la 012— y ninguna vía duplica el cálculo ni congela un paso que depende del estado del borrador. La parte de esta decisión que gobierna la **redirección automática** pertenece a la 026 y **no se aplica aquí**. *Descartadas:* (B) escribir en la dirección el paso de entrada calculado por la pantalla de origen, que crearía una segunda fuente del paso, obligaría a recalcularlo en cada vía y lo dejaría congelado si el borrador cambia entre el cálculo y la llegada; y (C) fijar `phases.identity` o `phases.composition`, que fuerzan un paso inútil en un torneo que ya tiene fases o un paso inexistente en el alta.

## Requisitos funcionales

### Orden y presentación

- **RF-001.** CUANDO un usuario abra la configuración de un torneo, EL SISTEMA presentará los tres asistentes en el orden **Reglas → Equipos → Fases**, y ese orden será a la vez el del documento y el de lectura con teclado y lector de pantalla.
  *Criterios de aceptación:*
  - El asistente de reglas precede al de equipos, y el de equipos precede al de fases, en el orden del marcado y en el orden de tabulación.
  - El orden no depende de la versión seleccionada, de su estado (borrador o publicada), de si hay o no equipos o fases, ni del rol del usuario.
  - Ningún otro elemento de la configuración se interpone entre los tres asistentes salvo el resumen, la barra de versión y la lista de verificación, que ya existen.
  - El orden se verifica con una prueba sobre la pantalla que comprueba la **posición relativa** de los tres asistentes, no solo su presencia.

- **RF-002.** EL SISTEMA conservará exactamente las mismas secciones del Workspace: el cambio de orden y el ancla nueva no añaden, retiran ni fusionan ninguna pantalla ni capacidad, y el calendario y las plantillas siguen teniendo su dirección propia fuera de la configuración.

- **RF-003.** CUANDO se muestre el rótulo de una sección numerada del recorrido, EL SISTEMA mostrará exactamente la numeración **01 · Reglas**, **02 · Equipos**, **03 · Fases** y **04 · Calendario** —y **01 · Rules**, **02 · Teams**, **03 · Stages**, **04 · Schedule** en inglés—, sin huecos, repeticiones ni números que contradigan la posición (ORD-1).
  *Criterios de aceptación:*
  - La cadena visible es exactamente la declarada: dos dígitos, espacio, `·`, espacio y el rótulo; no hay números duplicados, prefijos añadidos ni secciones numeradas sin sufijo legible.
  - Los rótulos `01`, `02` y `03` viven en el documento de configuración; el `04` vive en la **pantalla de calendario**, que ya tiene dirección propia, y no se repite en el documento de configuración.
  - **«03 · Fases» es un rótulo visible nuevo:** su clave de traducción existe hoy pero no se pinta en ninguna vista, así que pintarlo forma parte de este cambio (lista cerrada de RF-015, entrada (a)).
  - «01 · Reglas» y «04 · Calendario» sustituyen a los rótulos sin número y al `03` actual del calendario; «02 · Equipos» conserva el texto que ya muestra.
  - La secuencia se lee en orden creciente al recorrer el recorrido de arriba abajo, contando el `04` en su propia pantalla.
  - La pantalla de plantillas **no** forma parte de la secuencia: conserva su rótulo actual, sin número, y no lleva «05».
  - La etiqueta se mantiene en los dos idiomas soportados con la misma numeración (RNF-004).

- **RF-004.** EL SISTEMA mantendrá válidas todas las anclas existentes de la configuración y **añadirá una sola**, `#fases`: abrir la página con `#resumen`, `#configuracion`, `#equipos` o **`#fases`**, o con el paso de cualquier asistente, llevará al mismo contenido que hoy —o, para `#fases`, al bloque del asistente de fases— sin añadir rutas ni parámetros de dirección (ORD-2 revisada de nuevo).
  *Criterios de aceptación:*
  - `#resumen` sigue llevando al resumen, `#configuracion` al bloque de reglas y `#equipos` al bloque de equipos, con el mismo contenido que antes del cambio.
  - **Alcance de `#fases`:** lleva al bloque del asistente de fases de la **misma** pantalla de configuración, con su título visible en el destino; no abre una pantalla ni una sección distinta, no cambia la versión seleccionada, no fija ni cambia el paso del asistente y no crea ningún recurso nombrable por dirección. Su ámbito es un bloque de la pantalla de configuración, no una sección del índice ni un destino de redirección de fragmentos antiguos.
  - `#fases` **no redirige**: la resolución de fragmentos antiguos sigue sin enviar a ninguna otra dirección, como ya declaraba la spec 012, y el fragmento deja de ser un nombre sin destino para pasar a nombrar un bloque real.
  - No se añade ninguna ruta nueva ni ningún parámetro de dirección nuevo; **el índice del torneo conserva sus entradas y no gana ninguna** (RF-005).
  - Un enlace a un paso de otro asistente abre ese paso en el asistente correcto, con independencia de su posición en el documento.
  - **Los enlaces cruzados no introducen ninguna ruta ni ningún parámetro nuevos:** `#equipos` ya existe y `#fases` es la **única adición** de esta spec, y el enlace no **escribe ningún paso en la dirección** (RF-013).

- **RF-005.** EL SISTEMA **no añadirá entradas al índice del torneo**: el índice conserva exactamente las entradas que ya ofrece —las **cuatro** de configuración (resumen, configuración, calendario y plantillas) más **operación solo cuando hay un partido en contexto**— y ninguna se renombra, se retira, se subdivide ni cambia de destino por este cambio.
  *Criterios de aceptación:*
  - **No aparece ninguna entrada «Fases»** ni ninguna otra nueva; el ancla `#fases` no tiene entrada propia en el índice y se llega a ella por el enlace cruzado, no por el índice (RF-004, RF-013).
  - La entrada de configuración conserva su destino actual (`#configuracion`) y no se reescribe para llevar a otro bloque.
  - La sección marcada como activa al abrir la configuración sigue siendo **Configuración**, con independencia del fragmento con el que se abra (incluido `#fases`); nunca hay dos entradas activas.
  - El número de entradas y su orden son los mismos antes y después del cambio, en el documento de configuración y en las demás pantallas del torneo, con permiso de gestión y en solo lectura.
  - La única forma nueva de llegar al bloque de fases es el ancla `#fases` (enlace cruzado); no se añade una segunda vía por el índice (ORD-2 revisada de nuevo).

- **RF-006.** CUANDO se muestre la lista de verificación previa a la publicación, EL SISTEMA presentará sus ítems en el orden **versión en borrador → equipos → fases → partidos → plantillas**, coherente con el recorrido nuevo (ORD-3).
  *Criterios de aceptación:*
  - El ítem de equipos precede al de fases, y ambos conservan su posición relativa respecto de la versión, los partidos y las plantillas.
  - **No** se añade, retira ni redefine ningún ítem: los textos, los detalles, los umbrales de validez de cada ítem y los criterios del indicador son exactamente los actuales.
  - El ítem «Equipos» **mide asignaciones de fase**, no altas de equipo: conserva su texto y su criterio actuales, muestra `0` mientras no haya ninguna fase con equipos asignados y el reordenado no lo convierte en un ítem de alta de equipos ni cambia lo que mide.
  - Con datos reales y con la versión vacía, cada ítem muestra el mismo estado que mostraba antes del cambio; solo cambia su posición.
  - El orden es una decisión de presentación y no altera el cálculo de publicación ni sus umbrales.

- **RF-007.** CUANDO un lector consulte el manual de usuario, LA DOCUMENTACIÓN DEL PRODUCTO presentará sus apartados de configuración en el orden **reglas → equipos y plantillas → fases → calendario**, renumerados de forma consecutiva y sin referencias cruzadas desfasadas; describirá el orden nuevo, la numeración de las secciones, el ancla de fases y los enlaces cruzados; y las enumeraciones de esos apartados y de las anclas que `README.md` y la guía de agentes mantienen se actualizarán al orden y a las anclas nuevas (ORD-3, RNF-002).
  *Criterios de aceptación:*
  - Los apartados de configuración quedan, en ese orden, como «Configurar reglas», «Equipos y plantillas», «Configurar fases» y «Calendario», con numeración consecutiva y el resto de apartados conservando su orden relativo y su contenido.
  - El contenido de cada apartado no se reescribe más allá de lo que el reordenado, la renumeración y la descripción del ancla exigen: no se documentan capacidades nuevas ni se retiran las existentes.
  - Las anclas de la configuración que el manual documente son **cuatro**, con `#fases`, y ninguna referencia del manual ni de `README.md` cita un apartado por un número que haya dejado de corresponderle.
  - `README.md` y la guía de agentes **no repiten la secuencia numerada** del recorrido ni la numeración de los apartados del manual: remiten a él como fuente normativa única. **Sí se actualizan en este mismo cambio**, en cambio, sus **enumeraciones de los apartados del manual** —que hoy los nombran en el orden antiguo (reglas, fases, equipos y plantillas, calendario)— y sus **enumeraciones de las secciones y de las anclas de la configuración** —que hoy listan las secciones en el orden antiguo y las anclas sin `#fases`—: pasan al orden nuevo y a las cuatro anclas `#resumen`, `#configuracion`, `#equipos` y `#fases`. Sus listas operativas y de referencia —comandos, migraciones, contratos, verificaciones y límites del proyecto— se conservan tal cual, sin recortes ni reescrituras, y pueden seguir nombrando las pantallas por su nombre (RNF-002).

### Navegación de los asistentes: no regresión

- **RF-008.** CUANDO el usuario pulse «Siguiente» en un asistente, EL SISTEMA avanzará al paso siguiente **de ese mismo asistente** y nunca abrirá otro asistente, otra sección ni otra pantalla.
  *Criterios de aceptación:*
  - El paso de destino pertenece a la lista de pasos del asistente en el que se pulsó; se verifica para los tres asistentes y en todos sus pasos intermedios.
  - Tras pulsar «Siguiente», el paso en la dirección nombra un paso del mismo asistente y el índice muestra el paso nuevo como actual.
  - Ningún otro asistente cambia de paso como efecto del movimiento, y el orden del documento no interviene en el destino.
  - «Siguiente» no envía ninguna escritura al servidor ni guarda la configuración.
  - **«Siguiente» no cambia de sección:** el movimiento se queda en la configuración que ya está abierta (RF-017).

- **RF-009.** CUANDO el usuario pulse «Anterior» en un asistente, EL SISTEMA retrocederá al paso anterior **de ese mismo asistente**; en el primer paso la acción no estará disponible y no llevará a otro asistente ni a otra sección.

- **RF-010.** MIENTRAS el usuario esté en el último paso de un asistente, EL SISTEMA no ofrecerá un paso siguiente: «Siguiente» no estará disponible y no se producirá ningún salto automático al asistente que ocupa la posición siguiente en el documento.
  *Criterios de aceptación:*
  - Se comprueba en el último paso de los tres asistentes.
  - Completar un asistente no mueve la vista a otra sección por sí solo: la única acción que completa el asistente es su acción principal («Confirmar» o «Guardar reglas»), con sus reglas actuales de pasos obligatorios (spec 012), y el reordenado no le añade ninguna navegación (RF-017).
  - Lo mismo aplica al primer paso con «Anterior» (RF-009).

- **RF-011.** EL SISTEMA mantendrá el paso en la dirección como **única fuente** del paso actual de los tres asistentes después del reordenado: abrir la página con el paso de un asistente mostrará ese paso en ese asistente, y recargar lo conservará.
  *Criterios de aceptación:*
  - Abrir con un paso de reglas, de equipos o de fases deja a ese asistente en ese paso, con el índice en el mismo estado, sin que los otros dos cambien de paso.
  - Recargar conserva el paso; el botón atrás devuelve al paso anterior visitado.
  - La dirección del paso no contiene valores del formulario y el ancla `#fases` no fija ni sustituye ningún paso.
  - Un valor de paso desconocido se resuelve al paso de entrada del asistente, como hoy.

- **RF-012.** CUANDO la página se abra sin un paso en la dirección, EL SISTEMA normalizará la entrada **una sola vez y de forma determinista**, de modo que el reordenado no produzca dos escrituras de la dirección ni un paso distinto del que se muestra.
  *Criterios de aceptación:*
  - Abrir la configuración sin paso deja la dirección con un único paso, perteneciente a un solo asistente, y no se observa ninguna corrección posterior de la dirección.
  - La normalización no cambia el paso mostrado ni provoca un salto visible de asistente, ni pierde el fragmento `#fases` cuando la dirección lo trae.
  - Se verifica que la normalización no añade entradas de historial y que el primer «atrás» sale de la página como hoy.
  - La normalización de la entrada **no** cambia de sección (RF-017).

- **RF-013.** CUANDO el usuario siga el enlace al asistente de fases que ya ofrecen el asistente de equipos y la pantalla de plantillas, EL SISTEMA abrirá el asistente de fases **en su paso de entrada** y con el bloque de fases visible, sin depender de que las fases estén antes o después de los equipos en el documento (ORD-13, parte de enlaces).
  *Criterios de aceptación:*
  - El enlace sigue disponible desde el asistente de equipos y desde la pantalla de plantillas, y los dos llevan al **mismo destino observable**: la configuración del mismo torneo y de la misma versión, con el bloque de fases a la vista y el asistente de fases **en su paso de entrada** (RF-004).
  - El destino es válido en los **dos modos**: sin fases abre la identificación; con fases abre la composición, con la identificación en solo lectura (RF-011).
  - **El enlace actual se modifica en este cambio:** hoy apunta a un paso fijo de fases y al ancla `#configuracion`; tras el cambio **no nombra ningún paso** y apunta solo al ancla `#fases`. No se inventa ruta ni parámetro nuevos (RF-004).
  - **La expectativa de la prueba de la dirección del enlace se actualiza** a la dirección nueva (`frontend/tests/stage-teams.test.ts`), sin relajar la comprobación: sigue exigiendo la dirección exacta del enlace y ahora esa dirección es la del ancla `#fases` sin paso (RNF-001).
  - Al seguirlo, el asistente de fases muestra un paso suyo y ni equipos ni reglas cambian de paso; el `?step=` presente en la dirección **no se añade ni se retira**, de modo que el paso del asistente de origen no cambia y el asistente de fases resuelve su paso de entrada con el mecanismo de la 012 (RF-011).
  - Seguido desde la pantalla de plantillas, el enlace abre la configuración (otra ruta) y el bloque de fases queda a la vista en el destino.

- **RF-014.** EL SISTEMA conservará sin cambios los borradores de pestaña de los asistentes —paso actual y valores—, su ámbito (usuario, organización, torneo, versión y asistente) y las reglas de confirmación y descarte de la spec 012.
  *Criterios de aceptación:*
  - Cambiar de sección y volver devuelve a cada asistente a su paso con sus valores.
  - Cambiar de versión o de torneo sigue pidiendo confirmación y descartando el borrador; cancelar conserva todo.
  - Cerrar la pestaña descarta el borrador.
  - Nada se escribe en el servidor ni en almacenamiento persistente del navegador.
  - Seguir un enlace cruzado no descarta el borrador de ninguno de los asistentes.

- **RF-015.** EL SISTEMA conservará intactos el contenido, los pasos internos, la obligatoriedad, las validaciones y las peticiones de los tres asistentes: el reordenado y el ancla son de presentación y navegación, y no añaden ni retiran ningún paso, campo, comprobación ni bloqueo.
  *Criterios de aceptación:*
  - Cada asistente envía exactamente la misma información que antes del cambio, con las mismas peticiones y en el mismo orden.
  - Ninguna validación del cliente ni del servidor cambia, y ningún flujo (crear fase e inscribir, alta individual o carga masiva de equipos, guardar reglas) cambia su resultado.
  - El orden del documento no altera qué asistente crea, inscribe o guarda.
  - **Ámbito de la lista cerrada.** Los cambios visibles **dentro** de los asistentes —su contenido y su comportamiento: pasos, campos, textos, validaciones, peticiones y navegación interna— son una **lista cerrada de dos**: (a) los **rótulos numerados de sección**, incluido el nuevo «03 · Fases» (RF-003); y (b) el **ancla `#fases`** y, con ella, el **destino del enlace cruzado equipos → fases y plantillas → fases**, que deja de nombrar paso y pasa a apuntar a esa ancla (RF-004, RF-013). Fuera de esas dos, ni el contenido ni el comportamiento de los asistentes cambian.
  - **Fuera del ámbito de la lista (3)**, porque no son contenido ni comportamiento de un asistente y cada uno tiene su propio requisito: el **orden** de los tres asistentes en el documento (RF-001), el **orden de los ítems** de la lista de verificación (RF-006) y el **orden y la numeración de los apartados** del manual (RF-007). Cambiarlos no incumple esta lista; cambiarlos de otra forma que su requisito sí.
  - **Recuento exacto: 2 cambios dentro + 3 fuera = 5 cambios autorizados.** La lista cerrada tiene **dos** entradas —(a) y (b)—; los tres cambios de fuera no son «de la lista» y se nombran aparte. Los demás cambios de presentación y navegación que añade esta spec fuera de los asistentes no se incluyen aquí porque no alteran el interior de ningún asistente.
  - **La lista es decidible:** un cambio **incumple** la lista si altera, dentro de un asistente, un paso, un campo, un texto, una validación, una petición o una navegación interna que no esté autorizado por ninguna de las dos entradas ni por RF-001, RF-006 o RF-007; y **no** la incumple si es exactamente uno de esos cinco cambios declarados (dos dentro + tres fuera).

- **RF-016.** EL SISTEMA mantendrá los permisos y la visibilidad vigentes: el observador ve el recorrido completo en solo lectura y puede seguir los enlaces cruzados, y quien tiene permiso de gestión conserva exactamente sus acciones.
  *Criterios de aceptación:*
  - Con el rol de observador no aparece ninguna acción de escritura en ninguno de los tres asistentes, y el orden, la numeración y el ancla son los mismos que con permiso de gestión; el índice conserva sus entradas.
  - No se oculta ningún asistente por rol ni por estado de la versión.
  - Seguir un enlace cruzado en solo lectura no escribe nada ni envía ninguna petición de escritura.

- **RF-017.** CUANDO el usuario abra la configuración por una dirección que nombra un paso o un ancla, o pulse «Siguiente» o «Anterior», EL SISTEMA **no cambiará de sección**: se quedará en la configuración del torneo que ya está abierta y el reordenado no introduce ninguna navegación automática entre secciones.
  *Criterios de aceptación:*
  - Abrir la página por un enlace a un paso de cualquiera de los tres asistentes —incluidos los de fases— deja la pantalla en ese paso y no en otra sección.
  - Abrir la página con `#fases` no cambia de sección y no altera el paso del asistente (RF-004).
  - «Siguiente» y «Anterior» no cruzan de sección en ningún paso, tampoco en el primero ni en el último (RF-008 a RF-010).
  - Recargar, volver con el botón atrás y cambiar de idioma conservan la sección y el paso.

## Requisitos no funcionales

- **RNF-001. No regresión de la spec 012 y cobertura nueva.** Toda la suite del frontend que cubre asistentes, navegación por paso, borradores, equipos, fases y reglas sigue en verde con el reordenado, y se añade cobertura específica de: la **posición relativa** de los tres asistentes, la cadena exacta de los cuatro rótulos en los dos idiomas —incluido que «03 · Fases» pasa a pintarse—, que el índice del torneo **no gana entradas**, el ancla `#fases` con su título visible y su foco disponible, el orden de los ítems de la lista de verificación, la dirección del enlace cruzado sin paso, y que «Siguiente»/«Anterior» no cruzan de asistente ni de sección. No se relaja ni se retira ninguna comprobación existente para hacerla pasar. **Precisión de alcance:** la expectativa de la **dirección del enlace equipos → fases** en `frontend/tests/stage-teams.test.ts` **se actualiza** a la dirección nueva —el ancla `#fases` sin paso (ORD-13)—, y eso **no** es relajar la comprobación, porque sigue exigiendo la dirección exacta del enlace. La prueba de fuente de `frontend/tests/roster-lock.test.ts` que exige la presencia del enlace desde plantillas se conserva sin cambios.

- **RNF-002. Relación aditiva con la 012 y documentación actualizada sin duplicar la secuencia.** La relación con la spec 012 se declara **una sola vez**, en esta spec, como **aditiva y sin matices**: ningún requisito de la 012 se deroga, matiza ni reescribe, y **RF-018**, **RF-020**, **RNF-005** y **RNF-008** se verifican sin cambio (RF-015). La **fuente normativa única** del recorrido para el usuario es el manual de usuario: describe el orden y la numeración, el ancla de fases y los enlaces cruzados (RF-007). `README.md` y la guía de agentes **no repiten la secuencia numerada** del recorrido ni la numeración de los apartados del manual: **remiten** a él. **Sus enumeraciones de los apartados del manual y de las anclas de la configuración sí se actualizan en este mismo cambio** —al orden nuevo y a las cuatro anclas `#resumen`, `#configuracion`, `#equipos` y `#fases`—, porque hoy las tienen en el orden antiguo y sin `#fases`; sus listas operativas y de referencia —comandos, migraciones, contratos, verificaciones y límites del proyecto— se **conservan íntegras** y no se recortan ni reescriben por esta spec. **Justificación frente a la constitución §4:** §4 exige actualizar la documentación afectada cuando cambia el comportamiento observable, así que dejar esas enumeraciones desfasadas sí la incumpliría; actualizarlas **no** contradice la regla de no duplicar, porque lo que se evita es repetir la **secuencia numerada** (fuente única: el manual), no corregir una enumeración que ya existía, y conservar el resto íntegro evita recortes que §4 no pide. El **arnés de extremo a extremo no se toca** y su escenario sigue igual (012 RNF-008): ningún anclaje del arnés depende del orden, de los rótulos numerados ni del enlace cruzado.

- **RNF-003. Accesibilidad sin regresión.** Se conservan el foco en el título del paso al cambiar de paso, el anuncio del paso actual y del estado, la navegación completa por teclado y la asociación de errores a su campo. El orden de lectura coincide con el orden visible también en pantallas estrechas, donde las secciones se apilan en una columna. El ancla `#fases` deja a la vista el título del bloque, que es enfocable por teclado y se anuncia al recibir el foco, sin mover el foco por sí sola al abrir la página con el fragmento.

- **RNF-004. Paridad de idiomas.** Los rótulos y la numeración se mantienen en español e inglés con la misma numeración y sin etiquetas sin traducir; ninguna vista muestra el identificador de una clave. La pantalla de plantillas conserva su rótulo sin número en los dos idiomas.

- **RNF-005. Cambio sin efectos en datos ni contratos.** No hay cambios de API, de contrato HTTP, de esquema ni de migraciones; ninguna llamada nueva y ningún dato nuevo en el navegador. No hay cambios de backend, de permisos ni de autorización. Los límites de plantilla y el máximo de equipos **por petición** de inscripción no cambian: esta spec no los revalida ni los reinterpreta. El **formato de juego** tampoco cambia ni interviene: no se aplica al alta de equipos ni a la inscripción (spec 024).

## Datos personales y privacidad

No aplica. El cambio reordena y renumera secciones existentes del Workspace, añade un ancla y corrige el destino de dos enlaces. No introduce, muestra ni transporta datos personales nuevos —ni de jugadores ni de miembros—, no expone documentos, fechas de nacimiento ni edades, y no afecta a las proyecciones públicas ni al consentimiento de imagen.

## Casos límite

1. **Abrir con el paso de cualquier asistente:** `?step=` de reglas, de equipos o de fases abre ese paso en su asistente, sin mover a los otros dos (RF-011).
2. **Abrir sin `?step=`:** se muestra el paso de entrada y la dirección queda normalizada una sola vez (RF-012).
3. **Paso desconocido o de otro asistente:** se resuelve al paso de entrada del asistente, sin redirección silenciosa a otro asistente (RF-011).
4. **Primer paso de cada asistente:** «Anterior» no disponible y sin salto a la sección anterior (RF-009).
5. **Último paso de cada asistente:** «Siguiente» no disponible y sin salto al asistente siguiente del documento ni a la sección siguiente (RF-010, RF-017).
6. **Enlace desde plantillas al asistente de fases:** abre la configuración con el bloque de fases y el paso de entrada del asistente, sin depender de la posición de fases en el documento y sin perder el borrador de plantillas (RF-013, RF-004, RF-014).
7. **Enlace desde el alta de equipos al asistente de fases:** mismo comportamiento y mismo destino que el de plantillas; el borrador de equipos no se pierde por seguir el enlace (RF-013, RF-014).
8. **Enlace seguido con un `?step=` en la dirección:** no se añade ni se retira el paso presente; solo se mueve la vista al ancla `#fases` (RF-013, RF-011).
9. **Recarga y botón atrás:** conservan el paso y el orden; un solo «atrás» sale del cambio de paso (RF-011, RF-012).
10. **Cambio de sección (calendario o plantillas) y vuelta:** el orden y los pasos se conservan (RF-014).
11. **Cambio de versión con borradores abiertos:** pide confirmación y descarta; el orden visible y la numeración no cambian (RF-014, RF-003).
12. **Versión publicada o sin permiso de gestión:** mismo orden, misma numeración, mismo ancla y mismo índice, sin acciones de escritura (RF-001, RF-003, RF-005, RF-016).
13. **Torneo sin equipos o sin fases:** el orden visible no depende de que existan datos (RF-001), y la lista de verificación muestra los ítems en el orden nuevo con sus estados vacíos, sin cambiar sus umbrales (RF-006).
14. **Pantalla estrecha:** las secciones se apilan en el mismo orden y el orden de lectura coincide (RNF-003).
15. **Anclas antiguas de la configuración:** `#configuracion` y `#equipos` siguen resolviendo a su bloque; `#fases` se añade y resuelve al bloque de fases; `#resumen` no cambia (RF-004).
16. **Marcador guardado en `#equipos`:** lleva al bloque de equipos, que ahora es la segunda sección del recorrido; el contenido y el destino no cambian, solo su posición (RF-004).
17. **Fragmento `#fases` en un enlace guardado:** abre la configuración con el bloque de fases a la vista, **sin** cambiar de sección, sin redirigir, sin fijar el paso del asistente y sin perder el paso que traiga la dirección (RF-004, RF-017).
18. **Fragmento desconocido:** la pantalla sigue usable, no se convierte en error y no dispara ninguna navegación (RF-004).
19. **Índice del torneo abierto en la configuración:** ofrece las mismas **cuatro** entradas de configuración —resumen, configuración, calendario y plantillas—, más la de operación solo cuando hay un partido en contexto; marca **Configuración** como activa también al llegar con `#fases` y no ofrece ninguna entrada «Fases» (RF-005).
20. **Lista de verificación sin fases y sin asignaciones:** el ítem «Equipos» —que mide asignaciones de fase, no altas de equipo— muestra `0` mientras no exista una fase con equipos asignados, conserva su criterio y no se reinterpreta por haber pasado antes que el de fases (RF-006).
21. **Lista de verificación en una versión publicada:** sus ítems conservan textos y estados y mantienen el orden nuevo; publicar no depende de su orden (RF-006, RF-014).
22. **Manual con el apartado de plantillas separado de su pantalla:** el apartado «Equipos y plantillas» conserva su contenido y su referencia a `/workspace/tournaments/{id}/rosters`; el reordenado no fusiona ni divide apartados (RF-007).
23. **Cambio de idioma en la configuración:** los cuatro rótulos cambian de idioma conservando su número, su posición y su sentido; el calendario conserva su `04` y plantillas su rótulo sin número (RNF-004).
24. **Pantalla de plantillas abierta por su dirección propia:** no lleva número de sección y no se le asigna «05» (RF-003).
25. **Observador siguiendo el enlace cruzado:** llega al bloque de fases con su paso de entrada y no puede escribir nada (RF-016, RF-013).

## Fuera de alcance

- Cualquier cambio en backend, contratos HTTP, esquemas, migraciones o datos.
- El orden interno de los pasos de cada asistente, su contenido, su obligatoriedad y sus validaciones.
- Fusionar, dividir, añadir o retirar asistentes, secciones, ítems de la lista de verificación o apartados del manual.
- Añadir **rutas** o **parámetros** de dirección nuevos: la única adición es el fragmento `#fases` (ORD-2 revisada de nuevo); fases no gana pantalla, dirección propia **ni entrada en el índice** (RF-005).
- Añadir, retirar, renombrar, reordenar o subdividir entradas del **índice del torneo** (RF-005).
- Fijar el **paso concreto** al que llega el asistente de fases desde el enlace cruzado, o **escribir un paso en la dirección**: se usa su paso de entrada, que resuelve el propio asistente, y no se prescribe cómo se calcula (ORD-13).
- Cambiar el **formato de juego** (`game_format`) o su relación con los límites de plantilla: no interviene en el alta de equipos ni en esta spec (spec 024).
- Permisos, roles y visibilidad más allá de conservarlos.
- Rediseño visual, tipografía, espaciado o estilos de los asistentes.
- Cambiar qué asistente normaliza la entrada inicial cuando hay que elegir uno: se conserva el criterio actual.
- **La cadena de avance entre secciones, el aviso de minutos con sus controles y la cifra de composición de una fase: continúan en la spec 026** (`specs/026-cadena-de-avance-y-cifra/`), que depende de esta.

## Criterios de finalización

1. La configuración muestra los tres asistentes en el orden Reglas → Equipos → Fases, con una prueba que comprueba la posición relativa y no solo la presencia (RF-001).
2. Los cuatro rótulos visibles son exactamente «01 · Reglas», «02 · Equipos», «03 · Fases» y «04 · Calendario», con su par en inglés, sin huecos y sin que plantillas reciba número; una prueba comprueba ese **estado final** —la cadena completa en los dos idiomas, con «03 · Fases» pintado— y la evidencia de que antes no se pintaba vive en el diff, no es un criterio de aceptación (RF-003, RNF-004).
3. El `04` se lee en la **pantalla de calendario**, en su ruta propia, y no se repite en el documento de configuración, donde solo aparecen `01`, `02` y `03` (RF-003).
4. La lista de verificación previa a la publicación muestra sus ítems en el orden versión → equipos → fases → partidos → plantillas, con los mismos textos, umbrales y criterios, y el ítem «Equipos» sigue midiendo asignaciones de fase (RF-006).
5. El manual de usuario tiene sus apartados de configuración en el orden reglas → equipos y plantillas → fases → calendario, renumerados y sin referencias desfasadas, y describe el orden nuevo, la numeración, el ancla y los enlaces cruzados; README y guía de agentes remiten a él sin repetir la secuencia numerada, **actualizan sus enumeraciones de apartados y su lista de anclas —con `#fases`—** y conservan íntegras sus listas operativas (RF-007, RNF-002).
6. Las anclas `#resumen`, `#configuracion` y `#equipos` siguen resolviendo al mismo contenido; `#fases` abre el bloque de fases con su título visible, sin cambiar de sección ni de paso; **el índice del torneo conserva sus cuatro entradas de configuración —resumen, configuración, calendario y plantillas— y la de operación solo con un partido en contexto, y no ofrece ninguna «Fases»**; sigue marcando Configuración como sección activa y no hay ruta ni parámetro nuevos (RF-004, RF-005, RNF-003).
7. «Siguiente» y «Anterior» avanzan y retroceden solo dentro de su asistente en los tres asistentes, incluidos el primer y el último paso, y ninguna de las dos cruza de sección; hay prueba que lo cubre (RF-008, RF-009, RF-010, RF-017).
8. El paso en la dirección sigue siendo la única fuente, la entrada se normaliza una sola vez y recargar y el botón atrás se comportan como antes; el enlace cruzado **no escribe ningún paso en la dirección** (RF-011, RF-012, RF-013).
9. Los enlaces cruzados equipos → fases y plantillas → fases llevan al **mismo destino**: bloque de fases a la vista y asistente de fases en su **paso de entrada**, verificado en los dos modos —sin fases → identificación; con fases → composición con la identificación en solo lectura—, **sin fijar ningún paso concreto ni escribirlo en la dirección**, y con la expectativa de la dirección del enlace actualizada en `frontend/tests/stage-teams.test.ts` (RF-013, RF-004).
10. Los borradores de pestaña, las confirmaciones y su descarte se comportan igual que antes, y seguir un enlace cruzado no descarta ninguno (RF-014).
11. Contenido, validaciones y peticiones de los tres asistentes no cambian fuera de la lista cerrada, con el ámbito declarado en RF-015: **2 cambios dentro de los asistentes + 3 fuera = 5 cambios autorizados**, y el destino del enlace equipos → fases y plantillas → fases está autorizado dentro de la entrada del ancla (RF-015).
12. El observador ve el mismo orden, la misma numeración y el mismo ancla, sin ninguna acción de escritura y pudiendo seguir los enlaces (RF-016).
13. El arnés de extremo a extremo (`frontend/e2e/`) **no se modifica**, porque ninguno de sus anclajes depende del orden, de los rótulos numerados ni del enlace cruzado, y el job `e2e` sigue sin cambios; si su ejecución no está disponible, se declara **no ejecutada** (RNF-002).
14. Accesibilidad sin regresión: foco en el título del paso, anuncio del cambio, recorrido completo con teclado, orden de lectura coincidente en pantalla estrecha y título del bloque de fases enfocable y anunciado (RNF-003).
15. Queda declarada la relación **aditiva y sin matices** con la spec 012, con los cuatro requisitos que se verifican sin cambio, sin derogar el resto (RNF-002).
16. No hay cambios de API, contrato, esquema, migración, backend, permisos ni dependencias (RNF-005).
17. Pasan las verificaciones de frontend del cambio: `cd frontend && pnpm test`, `cd frontend && pnpm run typecheck` y `cd frontend && pnpm run build` (constitución §4). Lo que no pueda ejecutarse se declara **no ejecutado**.

## Dudas abiertas

Ninguna. Las decisiones que gobiernan esta spec —**ORD-1**, **ORD-2 revisada de nuevo**, **ORD-3** y la parte de enlaces de **ORD-13**— están resueltas con el usuario el 2026-10-28, y las demás (**ORD-4** a **ORD-14**) pertenecen a la spec 026. No queda ninguna marca de aclaración, ningún destino fijo de fases ni ninguna entrada «Fases» en el índice.
