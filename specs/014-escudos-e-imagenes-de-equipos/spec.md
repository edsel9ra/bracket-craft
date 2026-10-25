# Spec 014 — Escudos e imágenes de equipos

Estado: implementada

## Contexto y objetivo

Un equipo puede tener hoy una dirección externa de escudo guardada como texto: se acepta en el alta individual y en la carga masiva, se valida solo que empiece por `http` o `https` y se devuelve tal cual en el listado del torneo. No existe ninguna forma de subir una imagen, no se comprueba que esa dirección responda, no hay reemplazo ni eliminación, y **ninguna pantalla muestra el escudo**: el dato se guarda pero no se usa.

El producto ya resolvió el caso equivalente de las fotos de jugadores: almacenamiento privado, enlaces temporales firmados, validación por contenido y tamaño, compensación cuando la escritura falla y borrado del objeto anterior solo tras confirmar. Esta spec traslada ese mismo nivel de garantía a la imagen del equipo, con cinco decisiones de producto: el escudo **no** es dato personal y no depende de consentimiento; la imagen es **del equipo** y se comparte entre los torneos donde se inscribe, aunque se gestione desde el torneo en el que está inscrito; las superficies públicas muestran **solo el escudo cargado**; la primera carga **retira** la dirección externa heredada para que no queden dos fuentes de verdad; y la verificación del archivo se limita a lo que puede comprobarse sin decodificar la imagen, declarando expresamente lo que no se garantiza.

El objetivo es que una persona autorizada pueda cargar, reemplazar, consultar y eliminar la imagen de un equipo desde el torneo donde está inscrito, con validación del archivo, nombres seguros y errores comprensibles, sin que ninguna otra organización pueda gestionarla y sin que un fallo del almacenamiento deje imágenes rotas ni referencias huérfanas.

Por qué importa: el escudo es la primera imagen de marca que ve el público en el calendario público, la clasificación y la operación del partido. Un escudo servido desde una dirección pública permanente, desde el espacio de otra organización o desde un archivo que no es lo que dice ser convierte una función estética en una fuga de datos o en un vector de contenido. Y mantener a la vez una dirección externa y un archivo cargado garantiza que tarde o temprano se muestre el equivocado.

## Usuarios

- **Administrador de organización (dueño o administrador):** gestiona los equipos de su organización y quiere que cada equipo tenga su escudo sin depender de un enlace externo que puede caerse.
- **Persona con permiso de gestión de la organización:** carga, reemplaza y elimina escudos desde la pantalla de equipos del torneo donde el equipo está inscrito, sin que exista un permiso por torneo.
- **Operador y árbitro:** ven el escudo en la operación del partido para identificar a los equipos; no lo modifican.
- **Observador (consulta interna):** ve la imagen como parte de la información del torneo; no ve ninguna acción de escritura.
- **Público (sin sesión):** ve el escudo cargado de los equipos de los torneos visibles públicamente en el detalle público del torneo, el calendario público, la clasificación y los partidos con sus alineaciones; nunca la dirección externa heredada.
- **Administrador de plataforma:** no gestiona escudos; su ámbito sigue separado y no entra en el Workspace de la organización.
- **Persona de otra organización:** no ve, no consulta y no puede inducir la gestión de un escudo ajeno.

**Condición operativa, no rol del producto:** si el almacenamiento de archivos no responde, el Workspace avisa con un error de almacenamiento no disponible y las superficies públicas siguen sirviendo el resto de la información sin imágenes rotas.

## Roles y visibilidad

- **Público (sin sesión):** ve **solo el escudo cargado** de los equipos de torneos visibles públicamente —versión publicada y torneo publicado, en juego o finalizado, con organización activa—, en el detalle público del torneo, el calendario público, la clasificación y los partidos con sus alineaciones publicadas. No ve equipos de torneos en borrador, sin versión publicada ni de organizaciones inactivas. Nunca ve la dirección externa heredada, ni recibe la referencia interna como campo de una respuesta, solo un enlace temporal.
- **Miembro con permiso de gestión de la organización (dueño, administrador):** carga, reemplaza y elimina el escudo desde un torneo donde el equipo está inscrito, y consulta la imagen vigente. La autorización es por organización y no por torneo: el torneo aporta el contexto de la pantalla, no un ámbito de permisos. Su autoridad no se extiende a otra organización.
- **Miembro sin permiso de gestión (operador, árbitro, observador):** ve la imagen vigente y no ve ninguna acción de escritura habilitada; cualquier intento directo de escritura se rechaza sin escribir, sin borrar objetos y sin efectuar ninguna llamada al almacenamiento.
- **Miembro activo sin rol:** recibe el rechazo de contexto de la organización, que ocurre antes de la operación y no lleva código de error propio; no lee ni escribe la imagen ni provoca consultas al almacenamiento.
- **Administrador de plataforma:** sin acceso a la gestión de escudos. No puede cargar, reemplazar ni eliminar imágenes de ninguna organización, igual que no puede editar resultados ni versiones publicadas.
- **Otras organizaciones:** no ven la imagen, no ven su existencia y no pueden gestionarla. Un identificador de equipo de otra organización se trata como inexistente.

La visibilidad pública del escudo sigue exactamente la visibilidad pública del torneo: si el torneo no es visible, el escudo no se expone. Que la imagen sea pública no concede ninguna otra capacidad: no abre el listado de equipos, ni la plantilla, ni la operación del partido.

**Regla única de precedencia.** En el Workspace, mientras no haya escudo cargado y exista `logo_url` mostrable, se muestra esa dirección externa; el sustituto visual solo aparece cuando no hay escudo **ni** `logo_url` mostrable en esa superficie, o cuando la imagen no se puede cargar. En las superficies públicas nunca se muestra `logo_url`: si no hay escudo, se muestra el sustituto.

## Historias de usuario

- HU-1. Como administrador de organización, quiero subir el escudo de mis equipos para no depender de un enlace externo que puede dejar de funcionar.
- HU-2. Como persona con permiso de gestión, quiero reemplazar un escudo equivocado desde el torneo donde juego ese equipo, sin dejar rastro del anterior, para que el público no vea dos versiones.
- HU-3. Como persona con permiso de gestión, quiero eliminar un escudo que ya no corresponde para que el equipo se muestre sin imagen en lugar de con una incorrecta.
- HU-4. Como operador, quiero ver el escudo de los dos equipos en la operación del partido para identificarlos sin confundirlos, y sin poder cambiarlo por accidente.
- HU-5. Como espectador, quiero ver el escudo del equipo en el detalle público del torneo, el calendario público, la clasificación y los partidos para identificar a los equipos de un vistazo.
- HU-6. Como espectador, quiero que un escudo retirado deje de verse y no quede accesible por un enlace guardado.
- HU-7. Como responsable del producto, quiero que un archivo que no es una imagen admitida se rechace antes de guardarse para no servir contenido con otro propósito.
- HU-8. Como administrador de organización, quiero que nadie de otra organización pueda sustituir el escudo de mi equipo cambiando un identificador en la petición.
- HU-9. Como operador del producto, quiero que una caída del almacenamiento se vea como un aviso claro en el Workspace y no como una imagen rota en la página pública.
- HU-10. Como administrador de organización, quiero que la primera imagen que subo sustituya de una vez a la dirección externa que ya tenía el equipo, para que nunca se muestre la equivocada.

## Definiciones

- **Escudo (imagen de equipo):** imagen cargada por una persona autorizada y asociada a un equipo de la organización. Es distinta de la **URL externa heredada**, que es el valor de `logo_url`, una dirección `http(s)` que el alta de equipos ya acepta y que el sistema no descarga, no verifica y no copia.
- **Equipo de la organización:** la entidad de equipo que pertenece a una organización y puede inscribirse en uno o varios torneos. Es la que tiene escudo.
- **Equipo inscrito:** equipo registrado en un torneo concreto. Es el contexto desde el que se gestiona el escudo y el único por el que esta funcionalidad se ofrece.
- **Imagen vigente:** la única imagen cargada que el sistema muestra para un equipo en un momento dado. Puede no existir.
- **URL externa heredada (`logo_url`):** dirección de escudo que el equipo tenía antes de esta funcionalidad. Sirve **solo de respaldo en el Workspace mientras no haya imagen cargada** y desaparece con la primera carga confirmada.
- **Sustitución:** reemplazo de la imagen vigente por otra; la anterior deja de estar accesible al confirmarse.
- **Eliminación efectiva:** eliminación que retira una imagen vigente existente. Sin imagen previa, la operación es correcta pero no es efectiva.
- **Enlace temporal:** dirección de acceso con caducidad que el sistema entrega para ver la imagen. Nunca es una dirección pública permanente. Puede contener el identificador opaco que el almacenamiento necesita para resolver el objeto; ese identificador no se deriva del nombre que elige la persona y no se documenta ni se registra.
- **Referencia interna:** dato opaco que el sistema usa para localizar el archivo y que el enlace temporal puede transportar. Lo que el sistema garantiza es que **no se deriva del nombre de archivo elegido por la persona**, que no aparece en mensajes de error, registros técnicos ni entradas de auditoría, y que la API nunca lo devuelve como campo de una respuesta.
- **Archivo admitido:** archivo cuyo contenido real corresponde a JPEG, PNG o WEBP estáticos, no declara animación detectable y no supera el tamaño máximo configurado.
- **Animación detectable:** la que el contenedor declara antes de decodificar la imagen. En PNG, el bloque de control de animación (`acTL`) encontrado al recorrer los bloques **antes** del bloque de datos de imagen (`IDAT`). En WEBP, el indicador de animación del encabezado extendido (`VP8X`) o la presencia del bloque de animación (`ANIM`). JPEG no tiene una marca equivalente.
- **Huérfano:** archivo almacenado que ninguna imagen vigente referencia. Es un coste aceptado cuando una confirmación es ambigua o un borrado falla; nunca se prefiere a una referencia rota.
- **Última escritura confirmada gana:** regla de desempate cuando dos operaciones compiten por la misma imagen: prevalece la que confirme su escritura en último lugar. No se promete que el resultado sea independiente del orden.
- **Consentimiento de imagen:** condición que ya se exige para publicar la foto de un jugador. No se aplica al escudo.
- **Torneo visible públicamente:** torneo con versión publicada y estado publicado, en juego o finalizado, cuya organización está activa. Es la misma condición que ya rige el resto de la proyección pública.
- **Registro de auditoría administrativa:** el registro existente donde ya se anotan las acciones administrativas con cambio efectivo (guardar planilla, publicar o despublicar formación, asignar o retirar oficial y reabrir una invitación).

## Requisitos funcionales

### Alcance, gestión y fuente única

- RF-1. EL SISTEMA mantiene como máximo **una** imagen vigente por equipo de la organización, compartida por todos los torneos en los que ese equipo esté inscrito; la imagen pertenece al equipo y no a un torneo.
- RF-2. CUANDO una persona con permiso de gestión carga, reemplaza o elimina un escudo, EL SISTEMA opera en el contexto del torneo donde el equipo está inscrito, con el permiso de gestión de su organización y solo si el equipo pertenece a esa organización y el torneo del contexto contiene su inscripción.
- RF-3. SI el equipo no está inscrito en ningún torneo, ENTONCES esta funcionalidad no lo alcanza: no se ofrece gestionar ni mostrar su escudo y su caso queda fuera de alcance. EL SISTEMA no gestiona el escudo de un equipo desde un torneo que no contenga su inscripción: esa operación responde como equipo no encontrado (RF-23).
- RF-4. MIENTRAS no exista imagen cargada, EL SISTEMA muestra en el Workspace la URL externa heredada (`logo_url`) cuando exista; el sustituto visual de RF-17 se usa en el Workspace solo cuando no hay imagen cargada **ni** `logo_url` mostrable, y en las superficies públicas siempre que no haya imagen cargada, porque allí `logo_url` nunca se muestra.
- RF-5. CUANDO se confirma la primera carga de un equipo que tenía `logo_url`, EL SISTEMA retira esa dirección en la misma operación; desde entonces `logo_url` se devuelve `null` y no se restituye.
- RF-6. EL SISTEMA no descarga, no copia, no verifica ni migra `logo_url`; el alta de equipos sigue validándola como dirección `http(s)` mientras exista.
- RF-7. CUANDO se elimina la imagen vigente, EL SISTEMA no restituye `logo_url` aunque el equipo la hubiera tenido antes.
- RF-8. EL SISTEMA no comparte archivos entre equipos: dos equipos nunca apuntan a la misma imagen vigente, aunque se cargue el mismo contenido, y el archivo de un equipo no cambia cuando cambia el de otro.

### Contrato de campos

- RF-9. EL SISTEMA devuelve `logo_url` con la dirección externa mientras el equipo no tenga imagen cargada, y `null` desde la primera carga confirmada; nunca devuelve en `logo_url` una dirección generada por el propio sistema, y el alta de equipos sigue aceptando cualquier dirección `http(s)` mientras exista.
- RF-10. EL SISTEMA devuelve el escudo en un **campo distinto de `logo_url`**, con un enlace temporal, y representa la ausencia de imagen como ausencia del valor, nunca como error.
- RF-11. EL SISTEMA no devuelve la referencia interna como campo de ninguna respuesta del Workspace ni pública; tampoco la incluye en un mensaje de error, en un registro técnico ni en una entrada de auditoría, aunque el enlace temporal la transporte para que el almacenamiento resuelva el objeto.

### Operaciones y visualización

- RF-12. CUANDO una persona con permiso de gestión carga un archivo para un equipo inscrito en el torneo desde el que opera, EL SISTEMA valida el archivo, lo guarda en espacio privado, lo deja como imagen vigente, retira `logo_url` si existía y audita el cambio efectivo.
- RF-13. CUANDO se carga una imagen sobre un equipo que ya tenía una, EL SISTEMA la sustituye de forma atómica: al confirmar existe exactamente una imagen vigente y la anterior deja de estar accesible.
- RF-14. CUANDO una persona con permiso de gestión elimina la imagen de un equipo, EL SISTEMA deja el equipo sin imagen vigente al confirmar; responde igual si había imagen o si no la había, y una segunda eliminación no escribe, no borra ningún archivo y no audita.
- RF-15. CUANDO se consulta el listado de equipos de un torneo, EL SISTEMA devuelve, para cada equipo inscrito que tenga imagen vigente, su escudo en el campo de escudo con enlace temporal, de modo que la gestión y la sustitución se puedan verificar en ese mismo listado.
- RF-16. CUANDO se abre la operación de un partido, EL SISTEMA muestra el escudo de los dos equipos que lo disputan.
- RF-17. CUANDO un equipo debe mostrarse sin escudo cargado y sin `logo_url` mostrable en esa superficie, o cuando la imagen no se puede cargar (RF-18), EL SISTEMA muestra un sustituto visual con una regla fija: los dos primeros caracteres del código corto del equipo en mayúsculas y, si el código corto tuviera menos de dos caracteres, los dos primeros caracteres del nombre del equipo en mayúsculas. Nombre y código corto son obligatorios y no vacíos, así que el sustituto siempre tiene al menos un carácter y no se diseña un caso sin caracteres.
- RF-18. SI la imagen no se puede cargar en la vista por un objeto ausente o un enlace caducado, ENTONCES EL SISTEMA muestra ese mismo sustituto visual y no un icono de imagen rota; no reintenta automáticamente, y la nueva solicitud de enlace ocurre solo la próxima vez que la vista pide los datos.
- RF-19. CUANDO una carga, reemplazo o eliminación se confirma, EL SISTEMA actualiza la imagen mostrada en la misma pantalla sin recargarla y conserva el resto del estado de la vista.

### Autorización y aislamiento

- RF-20. EL SISTEMA exige membresía activa con al menos un rol activo en la organización para consultar el escudo en el Workspace.
- RF-21. EL SISTEMA exige permiso de gestión de la organización y pertenencia del equipo a esa organización para cargar, reemplazar y eliminar; el torneo solo aporta el contexto de la pantalla y no crea un ámbito de permisos.
- RF-22. SI la persona no tiene permiso de gestión, ENTONCES EL SISTEMA rechaza la escritura, no escribe ni borra ningún archivo, no efectúa ninguna llamada al almacenamiento y conserva la consulta de la imagen vigente.
- RF-23. SI el equipo no existe, pertenece a otra organización o el torneo del contexto no contiene su inscripción, ENTONCES EL SISTEMA responde igual que ante un equipo inexistente (`CREST_NOT_FOUND`, 404), sin revelar si existe en la organización o en otra, en la carga, el reemplazo, la eliminación y la consulta.
- RF-24. SI falta la organización activa o la membresía no es válida, ENTONCES EL SISTEMA rechaza la operación con el mismo criterio que el resto del Workspace, sin consultar ni modificar el almacenamiento.
- RF-25. SI la persona es un miembro activo de la organización sin ninguna fila de rol, ENTONCES EL SISTEMA la rechaza con el error de contexto de la organización, que se produce antes de la operación y no lleva código de error propio ni provoca consultas al almacenamiento.
- RF-26. EL SISTEMA no acepta identificadores de otra organización en ninguna operación, incluida la consulta, de modo que no existe forma de alcanzar un escudo ajeno alterando un identificador en la petición.
- RF-27. EL SISTEMA aplica defensa en profundidad: el aislamiento entre organizaciones lo garantiza la base de datos y, además, la operación comprueba la organización y el equipo antes de tocar el almacenamiento.

### Validación del archivo

- RF-28. CUANDO llega un archivo, EL SISTEMA detecta su tipo real a partir del contenido.
- RF-29. SI el contenido detectado no corresponde a JPEG, PNG o WEBP, ENTONCES EL SISTEMA lo rechaza sin almacenarlo.
- RF-30. SI el archivo está vacío o supera el tamaño máximo configurado, ENTONCES EL SISTEMA lo rechaza sin escribir en el almacenamiento, aunque el cuerpo de la solicitud se haya podido recibir completo dentro del límite global de la petición. Una solicitud que supera ese límite global se rechaza antes de la operación y queda fuera del catálogo de esta funcionalidad.
- RF-31. SI el contenido detectado es SVG o GIF, ENTONCES EL SISTEMA lo rechaza, con independencia del nombre del archivo y del tipo declarado.
- RF-32. CUANDO el contenido es PNG, EL SISTEMA recorre sus bloques y lo rechaza si encuentra el bloque de control de animación (`acTL`) antes del bloque de datos de imagen (`IDAT`).
- RF-33. CUANDO el contenido es WEBP, EL SISTEMA lo rechaza si el encabezado extendido declara animación o si el contenedor incluye el bloque de animación (`ANIM`).
- RF-34. SI la estructura del contenedor no permite completar el recorrido de bloques, ENTONCES EL SISTEMA acepta el archivo y declara el riesgo de animación no detectada.
- RF-35. EL SISTEMA limita la verificación del contenido a tipo, tamaño y marca de animación: un archivo truncado o corrupto que conserve una cabecera admitida se acepta y se sirve, y esa limitación se declara en la documentación.
- RF-36. EL SISTEMA nunca usa el nombre ni la extensión elegidos por la persona para decidir el tipo: manda el contenido verificado, de modo que un archivo con extensión PNG cuyo contenido es JPEG se acepta y se sirve como JPEG.
- RF-37. CUANDO el archivo es admitido, EL SISTEMA declara el tipo derivado del contenido al guardarlo y sirve la imagen desde el origen del almacenamiento, nunca desde el origen de la aplicación; no la recorta, no la redimensiona ni la re-codifica, y sirve sus metadatos tal como llegaron, sin presentarla como una imagen saneada ni anonimizada.

### Almacenamiento, concurrencia e integridad

- RF-38. EL SISTEMA guarda la imagen fuera de la base de datos, en un espacio privado delimitado por organización y equipo; la base de datos conserva la referencia interna y, si la implementación lo requiere, el tipo detectado al guardar, pero no conserva el archivo ni el nombre elegido, y ninguna respuesta devuelve la referencia.
- RF-39. SI el almacenamiento falla al guardar la imagen, ENTONCES EL SISTEMA no deja ninguna referencia a un archivo inexistente, conserva la imagen anterior intacta cuando la había, deja `logo_url` como estaba y responde con el aviso de almacenamiento no disponible.
- RF-40. CUANDO se sustituye o se elimina una imagen, EL SISTEMA confirma primero la referencia en la base de datos y borra el archivo anterior después; SI el borrado falla, ENTONCES el archivo queda huérfano, se registra una entrada estable sin claves, nombres ni contenido, la operación responde como correcta o idempotente y no se reintenta automáticamente.
- RF-41. SI la operación se cancela o falla antes de confirmar, ENTONCES EL SISTEMA elimina el archivo recién guardado y deja la imagen anterior como estaba; esta compensación ocurre también cuando la cancelación llega entre la escritura del archivo y la escritura de la referencia.
- RF-42. CUANDO dos operaciones se ejecutan simultáneamente sobre el mismo equipo, EL SISTEMA serializa la escritura y deja exactamente una imagen vigente o ninguna, sin ninguna referencia que apunte a un archivo borrado; el desempate es **última escritura confirmada gana** y el resultado no se declara independiente del orden.
- RF-43. SI existe la referencia a una imagen y el archivo no está, ENTONCES EL SISTEMA no borra ni corrige la fila automáticamente, la respuesta sigue siendo válida y la vista recurre al sustituto visual de RF-17 y RF-18.
- RF-44. CUANDO un fallo del almacenamiento impide preparar los enlaces de imagen, EL SISTEMA responde en el Workspace con el aviso de almacenamiento no disponible y el estado 503, y en las superficies públicas devuelve la imagen como ausente sin afectar al resto de la respuesta.

### Auditoría de las operaciones

- RF-45. CUANDO una carga, un reemplazo o una eliminación cambia efectivamente la imagen de un equipo, EL SISTEMA escribe una entrada en el registro de auditoría administrativa en la misma transacción que el cambio, con la acción y el equipo, y sin nombre de archivo, sin contenido, sin referencia interna y sin datos de jugadores.
- RF-46. SI la operación se rechaza o no produce cambio efectivo, ENTONCES EL SISTEMA no escribe ninguna entrada de auditoría.

### Exposición pública

- RF-47. MIENTRAS el torneo sea visible públicamente, EL SISTEMA muestra **solo el escudo cargado** de sus equipos en el detalle público del torneo, el calendario público, la clasificación y los partidos con sus alineaciones publicadas, mediante enlace temporal y nunca mediante una dirección pública permanente.
- RF-48. EL SISTEMA no publica ni enlaza `logo_url` en ninguna superficie pública, y una página pública nunca realiza peticiones a terceros para mostrar el escudo.
- RF-49. MIENTRAS el torneo no sea visible públicamente, EL SISTEMA no expone la imagen de sus equipos, aunque exista, y su ausencia en las superficies públicas no se distingue de la de un equipo sin imagen.
- RF-50. EL SISTEMA no exige consentimiento de imagen para el escudo, porque no es un dato personal, y no relaja ninguna regla existente de las fotos de jugadores: una foto sin consentimiento sigue sin publicarse.
- RF-51. EL SISTEMA no expone datos personales junto al escudo: allí donde aparece la imagen no se muestran documentos de identidad, fechas de nacimiento ni edad, ni se añade ningún campo nuevo que los contenga.
- RF-52. CUANDO se confirma un reemplazo o una eliminación, EL SISTEMA deja de emitir enlaces nuevos para la imagen anterior y deja de servirla; un enlace ya entregado deja de resolver de inmediato cuando el objeto se borra y, si el borrado falló, el huérfano puede seguir resolviendo hasta su caducidad. El comportamiento de cachés del navegador, intermediarios y terceros ajenos al sistema se declara como riesgo aceptado.
- RF-53. CUANDO se cambia o elimina el escudo de un equipo inscrito en un torneo publicado, en juego o finalizado, EL SISTEMA muestra la nueva imagen o su ausencia en ese torneo sin alterar su estructura, sus resultados, sus versiones publicadas ni su planilla.
- RF-54. EL SISTEMA no emite eventos de dominio por cambios de escudo; como consecuencia declarada, otras vistas abiertas no se refrescan hasta que vuelvan a pedir los datos.

### Pantalla, mensajes y estados

- RF-55. CUANDO una persona con permiso de gestión abre la pantalla de equipos de un torneo, EL SISTEMA muestra la imagen vigente de cada equipo inscrito y ofrece cargar, reemplazar y eliminar, indicando en cada caso qué acción corresponde.
- RF-56. MIENTRAS la persona solo tenga permiso de consulta, EL SISTEMA muestra la imagen sin ofrecer ninguna acción de escritura, y cualquier intento directo de escritura se rechaza en el servidor sin escribir.
- RF-57. CUANDO una operación de escudo falla, EL SISTEMA muestra un mensaje comprensible en el idioma activo, asociado al control que la originó, y acompaña el mensaje con un código estable como campo aditivo, sin detalles internos y sin el nombre del archivo que eligió la persona.

## Catálogo de mensajes y códigos estables

El mensaje viaja como texto del error y el código como campo aditivo junto a él, sin cambiar el mensaje de texto; los mensajes se muestran en el idioma activo y el código no cambia de idioma.

| Código | Estado | Cuándo | Qué ve la persona |
|--------|--------|--------|-------------------|
| `CREST_FILE_EMPTY` | 422 | El archivo no tiene contenido | «El archivo está vacío» |
| `CREST_FORMAT_UNSUPPORTED` | 422 | El contenido no es JPEG, PNG o WEBP, o es SVG o GIF | «El escudo debe ser una imagen JPG, PNG o WEBP» |
| `CREST_ANIMATION_UNSUPPORTED` | 422 | El contenedor declara animación de forma detectable | «El escudo no puede ser una imagen animada» |
| `CREST_TOO_LARGE` | 422 | Supera el tamaño máximo | «El escudo supera el tamaño máximo permitido» |
| `CREST_NOT_FOUND` | 404 | Equipo inexistente, de otra organización o no inscrito en el torneo del contexto | «El equipo no fue encontrado» |
| `CREST_FORBIDDEN` | 403 | Sin permiso de gestión | «No tienes permiso para gestionar el escudo de este equipo» |
| `CREST_STORAGE_UNAVAILABLE` | 503 | Fallo del almacenamiento | «El almacenamiento de imágenes no está disponible» |
| `CREST_UPLOAD_FAILED` | 500 | Fallo no clasificado durante la operación | «No se pudo completar la operación del escudo» |

El rechazo por miembro activo sin rol **no** lleva código: es el error de contexto de la organización, que ocurre antes de la operación. `CREST_NOT_FOUND` es la misma respuesta para un equipo inexistente, para uno de otra organización y para uno que existe en la organización pero no está inscrito en el torneo del contexto: no se distingue el motivo. Ningún código incluye la referencia interna del archivo ni indica en qué organización existe el equipo, y ninguno se emite por un archivo truncado, porque esa condición no se detecta sin decodificar. Una solicitud que supera el límite global del cuerpo se rechaza antes de la operación y no pertenece a este catálogo.

## Requisitos no funcionales

- RNF-1. **Tamaño máximo compartido.** El tamaño máximo de un escudo es el máximo de imagen ya configurado, **5 MiB por defecto**, compartido con las fotos de jugadores: esta spec no añade ninguna variable de configuración nueva y un cambio de ese límite afecta a ambas funciones, lo que se documenta. Un archivo que supera el máximo se rechaza sin escribir en el almacenamiento, aunque el cuerpo de la solicitud se haya podido recibir completo dentro del límite global de la petición.
- RNF-2. **Formatos y dependencias.** Se admiten exactamente tres formatos —JPEG, PNG y WEBP estáticos— y la validación no decodifica ni re-codifica la imagen; esta spec no introduce ninguna dependencia de procesamiento de imágenes y, si un cambio futuro la exigiera, se justificaría y se auditaría en su propia spec.
- RNF-3. **Detección de animación verificable.** La comprobación se ejecuta antes de guardar y sigue la regla declarada: recorrido de los bloques del contenedor hasta el bloque de datos de imagen, rechazo si en PNG aparece el bloque de control de animación antes de él, y rechazo en WEBP si el encabezado extendido declara animación o si existe el bloque de animación. Si el recorrido no puede completarse, el archivo se acepta y el límite se documenta. Ninguna prueba puede exigir la detección de una animación que solo se manifieste al decodificar.
- RNF-4. **Transacciones.** Ninguna escritura ni borrado en el almacenamiento ni la preparación de enlaces se ejecuta dentro de una transacción abierta: la conexión de base de datos no queda inactiva en transacción mientras se transfiere el archivo. Las escrituras de base de datos sí van en transacción, y todo ello se verifica con el almacenamiento simulado.
- RNF-5. **Enlaces y caducidad.** Los enlaces temporales caducan en 300 segundos por defecto, configurable entre 60 y 3600, y se preparan en una sola operación por respuesta. Un enlace emitido no es revocable antes de su caducidad.
- RNF-6. **Registro saneado y distinto por causa.** Los rechazos de validación no generan entrada técnica: se informan en la respuesta y no se registra el archivo ni su nombre. Los fallos del almacenamiento y de preparación de enlaces generan una sola entrada por respuesta, con el motivo y sin referencias internas, nombres, rutas, contenido ni datos personales.
- RNF-7. **Auditoría sin datos personales.** La entrada de auditoría nombra la acción y el equipo y no contiene nombre de archivo, contenido, referencia interna ni datos de jugadores; la autoría queda la que el registro ya anota en sus entradas existentes, y esta spec no añade ningún campo nuevo con datos personales.
- RNF-8. **Accesibilidad.** La carga, el reemplazo y la eliminación del escudo son alcanzables y operables solo con teclado, el control de archivo tiene etiqueta asociada, la imagen tiene texto alternativo con el nombre del equipo, el estado de espera y los errores se anuncian a lectores de pantalla y el resultado de cada operación se comunica sin depender solo del color.
- RNF-9. **Cobertura de idioma.** Todos los textos nuevos, incluidos el catálogo de errores y las etiquetas de las acciones, existen en español y en inglés con paridad de claves.
- RNF-10. **Compatibilidad de contrato.** Un cliente que ignore el escudo sigue funcionando: `logo_url` conserva su significado y su validación `http(s)` en el alta, el campo de escudo es aditivo y una respuesta sin imagen sigue siendo válida. No cambia ningún contrato de fotos de jugadores ni de consentimiento.
- RNF-11. **Aislamiento verificable.** Las pruebas incluyen peticiones con identificadores de otra organización, de equipos inexistentes y de equipos de otra organización, y verifican que el resultado es indistinguible del de un equipo inexistente y que no se produce ninguna escritura ni borrado.
- RNF-12. **Cobertura de pruebas.** Todo requisito funcional está cubierto por pruebas automatizadas que incluyen el listado de equipos del torneo, la operación del partido, el sustituto visual y la auditoría; las que necesitan base de datos real o almacenamiento real son opt-in y, si no se ejecutan, se declaran como no ejecutadas. El almacenamiento se simula en las pruebas unitarias, lo que se declara expresamente.
- RNF-13. **Sin lectura pública del almacenamiento ni secretos.** La funcionalidad no habilita ninguna política pública de lectura del almacenamiento ni añade secretos por defecto; las credenciales siguen llegando por configuración y la imagen se sirve solo por enlace temporal.
- RNF-14. **Límite de operaciones por solicitud.** Cada carga realiza como máximo una escritura y, como máximo, un borrado del archivo anterior; una eliminación realiza como máximo un borrado. No hay reintentos automáticos ni descargas del archivo desde su origen externo.
- RNF-15. **Origen de las escrituras.** Toda escritura nueva pasa por la validación de origen y de referencia que ya protege al resto de la API; un origen no permitido se rechaza antes de la operación y no llega al almacenamiento.

## Datos personales y privacidad

- **Qué se almacena:** el archivo de imagen admitido y la referencia interna que lo vincula a un equipo de la organización. El inventario exacto de lo que se persiste —y si hace falta algún dato adicional, como el tipo detectado— se cierra en el plan; esta spec solo exige que la base conserve la referencia, que no se devuelve como campo de una respuesta ni se documenta o registra, aunque el enlace temporal puede transportar el identificador opaco que el almacenamiento necesita.
- **Qué no se almacena:** el nombre de archivo original, una descripción libre, documentos de identidad, fechas de nacimiento, edades ni ningún campo nuevo con datos personales.
- **Metadatos: riesgo aceptado.** Una imagen puede contener metadatos incrustados —por ejemplo, geolocalización de la cámara— porque la plataforma no los elimina al no decodificar el archivo. Se acepta y se declara; la interfaz no presenta el archivo como saneado ni anonimizado.
- **Quién la ve:** el público en los torneos visibles públicamente; los miembros de la organización en el Workspace; ninguna otra organización. La imagen no se acompaña de documentos, edad ni fechas de nacimiento.
- **Consentimiento:** no se exige consentimiento de imagen para el escudo, porque no identifica a una persona, y esta excepción no se extiende a las fotos de jugadores: la regla de consentimiento de las fotos se mantiene sin cambios.
- **Minimización:** en las superficies públicas no se exponen la referencia interna como campo, la ruta interna ni el nombre del archivo, y tampoco el tamaño del archivo; el enlace temporal puede contener el identificador opaco que el almacenamiento necesita. La respuesta pública solo contiene lo necesario para mostrar la imagen.
- **Auditoría:** la entrada registra la acción, el equipo y la autoría que el registro ya anota; no contiene el archivo, ni su nombre, ni su referencia, ni datos de jugadores.
- **Retención:** la imagen vive hasta que se reemplaza o se elimina; no hay borrado automático por antigüedad ni historial de versiones. La baja de un equipo no existe hoy como operación (fuera de alcance) y, si existiera, se trataría en una spec propia.
- **Registros técnicos:** los rechazos de validación no registran nada; los fallos del almacenamiento registran una sola línea sin contenido ni nombre, según RNF-6.

## Riesgos aceptados

- **Huérfanos sin recolección ni cota.** Un borrado fallido o una confirmación ambigua deja archivos sin referencia. No hay recolección automática ni límite de acumulación en esta funcionalidad; se corrigen con operación manual si llegan a ser un problema.
- **Sin cuota por organización.** No se limita el número ni el volumen de escudos por organización más allá del tamaño de cada archivo; un miembro con permiso puede llenar el espacio disponible.
- **Sin dimensiones ni miniaturas.** El servidor no decodifica, así que no rechaza una imagen de dimensiones desproporcionadas ni genera versiones reducidas; aunque el servidor no la decodifique, **el navegador sí**, y una imagen de muchos píxeles puede consumir recursos en el cliente.
- **Metadatos no eliminados.** Se sirven tal cual, incluidos datos que la persona que subió el archivo no pretendía publicar.
- **Animación y truncamiento no garantizados.** La detección se limita a las marcas del contenedor: una animación o un archivo incompleto que solo se manifieste al decodificar se acepta y se sirve.
- **Enlaces no revocables por el sistema.** Al confirmar un reemplazo o una eliminación el sistema deja de emitir enlaces y borra el archivo anterior, de modo que un enlace ya entregado deja de resolver **de inmediato**, salvo que el borrado haya fallado —el huérfano declarado seguirá resolviendo hasta su caducidad— o que una caché lo conserve. El sistema no puede revocar por sí mismo un enlace antes de su caducidad.
- **Cachés del navegador y de intermediarios.** Un navegador o un proxy puede conservar una imagen ya retirada hasta la caducidad o más allá, fuera del control del sistema; también puede ocurrir con un tercero al que alguien haya enviado el enlace.
- **Enlace vivo tras dejar de ser público.** Al despublicar un torneo o desactivar la organización, el sistema deja de emitir y de servir la imagen en superficies públicas, pero un enlace ya entregado sigue vivo hasta su caducidad.
- **Enlace compartido sin sesión.** Cualquiera que reciba un enlace temporal puede ver el escudo mientras siga vigente, sin sesión y sin pertenecer a la organización; el enlace es la credencial.
- **`logo_url` en el Workspace y privacidad del personal.** Cuando el Workspace muestra una dirección externa heredada, el navegador del personal la pide a un dominio de terceros, al que se expone la dirección IP de quien la abre y el `Referer` de la página interna. Se acepta porque el Workspace no es una superficie pública; las superficies públicas nunca muestran ni enlazan `logo_url`.
- **Crecimiento del espacio.** El volumen almacenado depende de organizaciones × equipos, no solo de los escudos de una organización, de modo que no hay una cota simple por organización que lo limite.
- **Dos fuentes durante la transición.** Mientras un equipo conserva `logo_url` y aún no tiene escudo, el Workspace muestra una dirección externa que el sistema no controla, no verifica y no puede garantizar.

## Casos límite

1. **Primera carga con `logo_url` presente:** la imagen se guarda y la dirección externa se retira en la misma operación confirmada; no queda copia, no se descarga y el equipo pasa a mostrar solo la imagen cargada, con `logo_url` en `null` (RF-5, RF-9, RF-12).
2. **Carga sobre un equipo sin `logo_url` y sin imagen:** caso normal; el equipo queda con su primera imagen.
3. **Eliminación sobre un equipo sin imagen:** éxito idempotente, sin escritura, sin borrado, sin llamada al almacenamiento y sin entrada de auditoría (RF-14, RF-46).
4. **Eliminación repetida:** la segunda operación responde igual que la primera y no deja una segunda entrada de auditoría.
5. **Eliminación de un equipo cuyo archivo ya no está:** la referencia se retira igual, la operación es efectiva si había imagen vigente y la ausencia del archivo no convierte la respuesta en error (RF-40, RF-43).
6. **Dos cargas simultáneas:** una sola imagen vigente; prevalece la última escritura confirmada, no se borra ningún archivo de la imagen vigente y no se promete un resultado independiente del orden (RF-42).
7. **Carga y eliminación simultáneas:** el resultado es una imagen vigente o ninguna, nunca una referencia a un archivo borrado (RF-42).
8. **Equipo inexistente, de otra organización o no inscrito en el torneo del contexto:** misma respuesta en las cuatro operaciones (`CREST_NOT_FOUND`, 404), sin consultar el almacenamiento y sin revelar si existe en la organización o en otra (RF-23, RF-26).
9. **Equipo inscrito en un torneo y en otro:** una sola imagen; el cambio hecho desde un torneo se ve en el otro, porque la imagen es del equipo (RF-1).
10. **Equipo sin ninguna inscripción:** fuera de alcance; no se ofrece su escudo ni se gestiona desde esta funcionalidad (RF-3).
11. **PNG animado (APNG):** se rechaza si el recorrido encuentra el bloque de control de animación antes del bloque de datos de imagen (`CREST_ANIMATION_UNSUPPORTED`) (RF-32).
12. **WEBP animado:** se rechaza si el encabezado extendido declara animación o si existe el bloque de animación (RF-33).
13. **Estructura de contenedor ilegible para el recorrido:** se acepta el archivo y el riesgo queda declarado; no se responde con un error que el sistema no puede fundamentar (RF-34, RNF-3).
14. **GIF y SVG:** se rechazan por contenido con independencia del nombre del archivo, y no se convierten a un formato estático (RF-31).
15. **Archivo truncado o corrupto con cabecera válida:** se acepta y se sirve; el navegador mostrará la imagen incompleta. No se detecta sin decodificar y así se declara (RF-35).
16. **Extensión que no coincide con el contenido:** manda el contenido; un archivo con extensión PNG cuyo contenido es JPEG se acepta y se sirve como JPEG (RF-28, RF-36).
17. **Nombre de archivo con rutas o caracteres especiales:** nunca llega a la referencia interna ni al enlace, porque el nombre elegido no se usa en ningún caso (RF-36, RF-11).
18. **Imagen que no carga en la vista:** el equipo muestra el sustituto visual, no un icono de imagen rota; la fila no se corrige y no se reintenta automáticamente: la nueva solicitud de enlace ocurre la próxima vez que la vista pide los datos (RF-18, RF-43).
19. **Fallo del almacenamiento a mitad de un reemplazo:** la imagen anterior sigue vigente y accesible; la persona ve el aviso de almacenamiento no disponible y `logo_url`, si existía, sigue como estaba (RF-39).
20. **Fallo al borrar el archivo anterior o al borrar en una eliminación:** la referencia ya está confirmada, el archivo queda huérfano, se registra una entrada estable sin datos y la operación responde como correcta o idempotente; no se reintenta (RF-40, RNF-6).
21. **Confirmación ambigua al guardar:** se conservan ambos archivos, la referencia es válida y puede quedar un huérfano; se prefiere el huérfano a una imagen rota y no se intenta adivinar el resultado (RF-41).
22. **Archivo ausente con referencia existente:** la respuesta sigue siendo válida, la vista muestra el sustituto y la fila no se corrige ni se borra automáticamente (RF-43).
23. **Enlace ya emitido después de reemplazar o eliminar:** el sistema no emite enlaces nuevos ni sirve la imagen anterior; el enlace previo deja de resolver de inmediato al borrarse el objeto, salvo el huérfano declarado o una caché, que quedan como riesgo aceptado (RF-52, RNF-5).
24. **Enlace caducado abierto directamente:** el acceso falla, la vista muestra el sustituto y no se convierte el fallo en un error de la página; no hay reintento automático, y la nueva solicitud de enlace ocurre solo la próxima vez que la vista pide los datos (RF-18, RNF-14).
25. **Persona sin permiso de gestión forzando la escritura:** rechazo (`CREST_FORBIDDEN`) sin escritura, sin borrado, sin llamada al almacenamiento y sin entrada de auditoría (RF-22, RF-46).
26. **Miembro activo sin rol:** error de contexto de la organización antes de la operación, sin código propio y sin consultas al almacenamiento (RF-25).
27. **Origen no permitido:** la escritura se rechaza antes de la operación y no llega al almacenamiento (RNF-15).
28. **Organización inactiva:** el Workspace queda bloqueado como hoy y el escudo no se expone en las superficies públicas; un enlace ya entregado sigue vivo hasta su caducidad (RF-49, RF-52).
29. **Torneo despublicado:** deja de exponerse el escudo en las superficies públicas; un enlace ya entregado sigue vivo hasta su caducidad (RF-49).
30. **Torneo publicado o finalizado con cambio de escudo:** se muestra la nueva imagen o su ausencia sin alterar estructura, resultados, versiones ni planilla, y sin emitir eventos; otras vistas abiertas no se refrescan (RF-53, RF-54).
31. **Carga mientras el torneo se publica:** la publicación no se bloquea ni se revierte por la imagen; al terminar, la imagen vigente se expone si el torneo queda visible.
32. **Fallo del almacenamiento al preparar enlaces:** el Workspace avisa con el código de almacenamiento no disponible y las superficies públicas devuelven la imagen ausente sin romper la respuesta (RF-44).

## Fuera de alcance

- Edición de la imagen: recorte, rotación, ajuste, filtros, conversión de formato, re-codificación, eliminación de metadatos y generación de miniaturas o variantes de tamaño.
- Dimensiones, resolución o proporción obligatorias: no se imponen y no se corrigen.
- Direcciones públicas permanentes, lectura pública del almacenamiento, CDN y cualquier caché de borde.
- Escudos de torneo, de organización, de fase o de sede: esta spec cubre solo equipos.
- Equipos sin ninguna inscripción: no se gestiona su escudo en esta funcionalidad.
- Importación masiva de escudos por CSV o ZIP y su asociación automática por nombre de archivo.
- Edición, baja o retirada de equipos, y cualquier historial de versiones de la imagen.
- Migración, descarga o validación del contenido de `logo_url`; su retirada solo ocurre con la primera carga.
- Fotos de jugadores, consentimiento de imagen y sus reglas de publicación.
- Moderación de contenido, análisis antivirus, detección de marcas o de derechos de imagen.
- Recolección de huérfanos, cuotas de almacenamiento por organización y revocación de enlaces firmados antes de su caducidad.
- Cambiar o añadir un proveedor de almacenamiento: se reutiliza el existente.
- Prometer detección de animación o de corrupción que exija decodificar la imagen.

## Criterios de finalización

Cada criterio indica el requisito que lo respalda y el tipo de evidencia: **A** = prueba automatizada con el almacenamiento simulado, **B** = prueba automatizada con base de datos real (opt-in), **C** = comprobación manual documentada.

1. **Cobertura.** Los RF-1 a RF-57 y los RNF-1 a RNF-15 quedan cubiertos, cada uno con al menos una prueba o una comprobación manual citada, y las pruebas con base real se ejecutan o se declaran no ejecutadas. *(A, B)*
2. **Ciclo completo en el contexto del torneo.** Una persona con permiso carga un escudo desde el torneo donde el equipo está inscrito, lo ve en el listado de equipos del mismo torneo, lo reemplaza y lo elimina; tras cada paso se cumple el estado descrito en RF-12 a RF-15 y no queda ningún archivo accesible de la imagen anterior. Un equipo sin inscripción no se gestiona, y gestionarlo desde un torneo que no contiene su inscripción responde como equipo no encontrado. *(RF-2, RF-3, RF-12 a RF-15, RF-19, RF-55; A, B)*
3. **Fuente única, contrato de campos y precedencia.** Antes de la primera carga, `logo_url` devuelve la dirección externa o nada; la primera carga la retira y desde entonces devuelve `null`; eliminar la imagen no la restituye; el escudo viaja en otro campo; la referencia interna no se devuelve como campo independiente en ninguna respuesta. En el Workspace, mientras no haya escudo y exista `logo_url`, se muestra esa dirección y el sustituto se reserva para cuando no hay ni escudo ni `logo_url` mostrable; en las superficies públicas nunca se muestra `logo_url`. *(RF-4, RF-5, RF-6, RF-7, RF-9, RF-10, RF-11, RNF-10; A, B)*
4. **Una sola imagen por equipo.** Un equipo inscrito en dos torneos muestra la misma imagen en ambos y su cambio se refleja en los dos; dos equipos distintos nunca comparten imagen. *(RF-1, RF-8; A, B)*
5. **Operación del partido y sustituto visual.** La operación de un partido muestra el escudo de los dos equipos; el sustituto con la regla fija aparece solo cuando no hay escudo ni `logo_url` mostrable en el Workspace, o cuando no hay escudo en una superficie pública, y también cuando la imagen no se puede cargar, nunca como icono roto. *(RF-4, RF-16 a RF-18, RF-43; A, C)*
6. **Autorización por operación.** Consultar exige membresía activa con al menos un rol activo; cargar, reemplazar y eliminar exigen permiso de gestión y pertenencia del equipo; sin permiso no hay escritura, borrado ni llamadas al almacenamiento; sin organización activa o con membresía inválida se rechaza como el resto del Workspace; el miembro sin rol recibe el error de contexto sin código. *(RF-20 a RF-22, RF-24, RF-25, RF-56; A, B)*
7. **Aislamiento sin IDOR.** Ninguna combinación de identificadores de organización o de equipo ajenos produce lectura, escritura ni borrado, y la respuesta es indistinguible de la de un equipo inexistente, con la base de datos y la operación comprobando ambas. Un equipo de la organización que no está inscrito en el torneo del contexto responde igual que uno inexistente, sin revelar que existe en la organización ni permitir gestionarlo desde ese contexto. *(RF-2, RF-3, RF-23, RF-26, RF-27, RNF-11; A, B)*
8. **Validación declarada con honestidad.** Se rechazan archivo vacío, SVG, GIF, animado detectable y mayor que el máximo sin escribir en el almacenamiento; un archivo con estructura ilegible o truncado con cabecera válida se acepta y la limitación queda documentada, sin prometer una detección que no existe. *(RF-28 a RF-36, RNF-1, RNF-2, RNF-3; A, C)*
9. **Tipo y servicio.** El tipo servido es el detectado del contenido y no el nombre; la imagen se sirve desde el origen del almacenamiento y no desde el de la aplicación, sin recodificar. *(RF-36, RF-37, RNF-14; A)*
10. **Nombres seguros.** Ningún nombre elegido por la persona aparece en una referencia interna, en un enlace, en el registro técnico o en la auditoría. *(RF-11, RF-36, RNF-6, RNF-7; A)*
11. **Integridad sin referencias rotas.** No existe ningún estado en el que una referencia apunte a un archivo borrado: los escenarios de fallo, cancelación, doble carga y carga con eliminación simultánea terminan en una imagen vigente o en ninguna, con última escritura confirmada como desempate y sin escrituras de almacenamiento dentro de una transacción abierta. *(RF-38 a RF-42, RNF-4; A, B)*
12. **Borrado fallido.** Cuando el borrado del archivo anterior falla, la operación responde como correcta o idempotente, el archivo queda huérfano, se registra una sola entrada sin datos y no hay reintento automático. *(RF-40, RNF-6, RNF-14; A)*
13. **Degradación limpia.** Con el almacenamiento caído, el Workspace responde con el estado 503 y el aviso de almacenamiento no disponible, y las superficies públicas devuelven la imagen ausente sin romper el resto de la respuesta, con una sola entrada de registro por respuesta. *(RF-44, RNF-6; A)*
14. **Auditoría efectiva y mínima.** Cada carga, reemplazo y eliminación efectiva deja una entrada en el registro de auditoría administrativa en la misma transacción; una operación repetida, rechazada o sin cambio no deja ninguna; la entrada no contiene nombre de archivo, contenido, referencia ni datos de jugadores. *(RF-45, RF-46, RNF-7; A, B)*
15. **Exposición pública acotada.** El escudo se ve solo en torneos visibles públicamente, en el detalle público del torneo, el calendario público, la clasificación y los partidos con sus alineaciones publicadas, mediante enlace temporal, nunca por dirección permanente; `logo_url` no se publica y la página pública no hace peticiones a terceros por el escudo. *(RF-47 a RF-49, RNF-5, RNF-13; A, B, C)*
16. **Retirada de la imagen.** Tras reemplazar o eliminar, el sistema no emite enlaces nuevos ni sirve la imagen anterior, y el enlace ya entregado deja de resolver de inmediato al borrarse el objeto, salvo el huérfano declarado o una caché, que quedan como riesgo. *(RF-52, RNF-5; A, C)*
17. **Consentimiento preservado.** El escudo no requiere consentimiento y las fotos de jugadores siguen sin publicarse sin él: la suite existente de contrato público de jugadores sigue en verde. *(RF-50, RF-51; A, B)*
18. **Inmutabilidad declarada.** El cambio de escudo en un torneo publicado o finalizado se muestra sin alterar estructura, resultados, versiones ni planilla, sin emitir eventos, y la documentación declara que otras vistas abiertas no se refrescan. *(RF-53, RF-54; A, B, C)*
19. **Origen y miembros sin rol.** Una escritura con origen no permitido se rechaza antes de la operación y no llega al almacenamiento; un miembro sin rol no provoca consultas al almacenamiento. *(RF-25, RNF-15; A, B)*
20. **Pantalla accesible, bilingüe y con errores estables.** Cargar, reemplazar y eliminar se operan solo con teclado, con texto alternativo, estado anunciado y mensajes asociados y con el código estable como campo aditivo junto al mensaje; todos los textos existen en español y en inglés con paridad. *(RF-57, RNF-8, RNF-9; A)*
21. **CI y documentación.** Pasan los jobs aplicables (`backend`, `frontend`, `infrastructure` y `security`) y el job `e2e`, que se ejecuta en cada `pull_request` y debe quedar en verde aunque no cubra escudos, por lo que no se declara como evidencia de esta funcionalidad. La documentación afectada —alcance del producto, contrato público y guía de trabajo— queda actualizada, incluidas las limitaciones declaradas sobre metadatos, truncamiento y animación. *(RNF-2, RNF-3, RNF-7, RNF-10, RNF-12; A, C)*

### Nota de cierre: renuncia expresa a la comprobación manual (2026-10-24)

El usuario ha **renunciado expresamente** a la comprobación manual prevista para los criterios que dependen de ella —**5, 15, 16, 18 y 20** en lo que respecta al recorrido completo solo con teclado, al anuncio del lector de pantalla y a la carga de una imagen real en un navegador—. Motivo declarado: **no se dispone de un entorno de navegador y lector de pantalla preparado en esta sesión**. Esta nota no cambia ningún RF ni RNF: esos criterios se cierran con la evidencia automatizada y estática ya recogida (A/B) y con esta renuncia, no con una comprobación manual realizada. **Riesgo residual aceptado:** la accesibilidad real (recorrido completo solo con teclado y anuncio del lector) y la carga/decodificación de una imagen real no se han verificado fuera de las pruebas automáticas y estáticas; queda registrado y podrá cubrirse en una verificación manual posterior.

## Dudas abiertas

Ninguna. Las dudas de las pasadas anteriores quedaron resueltas por el usuario y están incorporadas en los requisitos, las definiciones, los riesgos aceptados y los casos límite; no queda ninguna decisión de producto pendiente para pasar al plan.
