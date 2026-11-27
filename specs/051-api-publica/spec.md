# Spec 051 — API pública documentada para terceros (F15)

Estado: borrador. DA-1–DA-4 resueltas el 2026-11-27. Pedida por el usuario el 2026-11-27 («Sigue con P3»), primera función pendiente de P3 en `docs/informe-funciones-adicionales.md`.

## Decisiones del usuario (2026-11-27)

- **DA-1 = (a).** El catálogo solo tiene las 9 lecturas JSON. Las tres imágenes para compartir (PNG) de la 043 siguen siendo del sitio y no forman parte del contrato.
- **DA-2 = (a).** El contrato `v1` usa las mismas rutas de hoy (`/api/v1/tournaments/public…`), con un documento OpenAPI propio. El sitio público y los terceros usan las mismas lecturas.
- **DA-3 = (a).** Las lecturas del catálogo se pueden llamar desde el navegador de cualquier origen, sin cookies ni credenciales. El resto de la API conserva su CORS actual.
- **DA-4 = (a).** El límite de peticiones sigue en el proxy, como hoy. Se documenta una configuración de ejemplo con límite por IP que no afecta al SSR del sitio.

## Contexto y objetivo

Las lecturas públicas ya existen y las usa el sitio público sin sesión: listado de torneos, detalle, clasificación, partidos, detalle de un partido, cronología, estadísticas de jugadores y de equipos, y ficha de jugador (specs 020, 022, 037 y 038). Sus campos están cerrados por la matriz de la 020 (RF-013–RF-018) y por las listas de cada ampliación.

Hoy un tercero (un club, una federación, un medio) puede llamarlas, pero:

- No hay un contrato publicado: la documentación interactiva mezcla las lecturas públicas con toda la API privada del Workspace.
- No hay una promesa de estabilidad: nada dice qué puede cambiar dentro de `v1` sin romper a quien la usa.
- No hay una guía de uso: ejemplos, errores, idioma, límites de peticiones.
- El límite de peticiones de las lecturas públicas corresponde al proxy, pero no hay una configuración documentada.

**Objetivo:** que un tercero pueda consumir las lecturas públicas existentes con un contrato documentado y versionado, sin exponer ningún dato nuevo y sin cambiar lo que ve el sitio público.

## Usuarios

- Desarrolladores de clubes, federaciones o medios que muestran en sus propios sitios o aplicaciones los torneos públicos de una organización.
- Operadores que despliegan Bracket Craft y configuran el proxy.

## Roles y visibilidad

- **Público (sin sesión), incluido un tercero:** consulta las mismas lecturas públicas de hoy, con los mismos campos. Sin credenciales, cookies ni claves de API.
- **Miembro de organización:** sin cambios. La API pública no da acceso a nada del Workspace.
- **Administrador de organización:** sin cambios. No hay opción para activar o desactivar la API pública de su organización: un torneo publicado ya es público.
- **Administrador de plataforma:** sin cambios.

## Historias de usuario

- HU-1. Como desarrollador de un club, quiero un documento con solo las lecturas públicas, sus parámetros, campos y errores para integrarlas sin leer la API privada.
- HU-2. Como desarrollador, quiero saber qué cambios puede tener `v1` para que mi integración no se rompa con una actualización.
- HU-3. Como operador, quiero una configuración documentada del límite por IP de las lecturas públicas para protegerlas sin afectar al sitio.

## Definiciones

- **Lectura pública:** cada endpoint `GET` sin sesión bajo `/api/v1/tournaments/public…` que devuelve JSON. El catálogo cerrado se fija en RF-001.
- **Contrato público `v1`:** el conjunto de lecturas públicas, sus parámetros, sus campos de respuesta y sus errores, tal como los fija la matriz de la 020 y sus ampliaciones.
- **Cambio compatible:** añadir una lectura nueva, un campo opcional nuevo en una respuesta o un valor nuevo en un parámetro opcional. Cualquier otro cambio (quitar o renombrar un campo, cambiar su tipo o su significado, cambiar un error) es **incompatible**.

## Requisitos funcionales

### Catálogo y documentación

- **RF-001.** EL SISTEMA documentará como contrato público `v1` un catálogo cerrado de lecturas públicas existentes: listado de torneos, detalle del torneo, clasificación, partidos, detalle de un partido, cronología del partido, estadísticas de jugadores, estadísticas de equipos y ficha de jugador. Las tres imágenes para compartir de la 043 no forman parte del catálogo (DA-1).
- **RF-002.** EL SISTEMA publicará, sin sesión, un documento de la API pública en formato OpenAPI que contenga solo las lecturas del catálogo de RF-001, con sus parámetros, los campos de cada respuesta y sus errores. No contendrá ninguna ruta del Workspace, de autenticación ni de la administración de la plataforma.
- **RF-003.** EL SISTEMA ofrecerá una guía de uso de la API pública, en español y en inglés, con: la URL base, un ejemplo de petición y respuesta por lectura, el significado de cada error, el idioma de los textos, el límite de peticiones y la política de versiones.
- **RF-004.** Una verificación automática fallará SI el documento de RF-002 contiene una ruta fuera del catálogo de RF-001, le falta una ruta del catálogo, o un campo de respuesta que no está en la lista cerrada de la matriz de la 020 (RF-015 de la 020).

### Versiones

- **RF-005.** EL SISTEMA identificará el contrato como `v1` en la ruta (`/api/v1`) y en el documento de RF-002. Las rutas son las mismas que hoy usa el sitio público, sin prefijo ni duplicados (DA-2).
- **RF-006.** MIENTRAS el contrato sea `v1`, EL SISTEMA solo admitirá cambios compatibles en sus lecturas. Una verificación automática comparará el documento de RF-002 con una copia de referencia guardada en el repositorio y fallará ante un cambio incompatible.
- **RF-007.** CUANDO se añada un cambio compatible al contrato, la copia de referencia de RF-006 se actualizará en el mismo cambio y la guía de RF-003 lo registrará en un historial con su fecha.

### Acceso

- **RF-008.** EL SISTEMA servirá las lecturas del catálogo sin sesión, sin cookies, sin claves de API y sin organización activa, como hoy (RF-013 y RF-018 de la 020).
- **RF-009.** CUANDO un navegador pida una lectura del catálogo desde cualquier origen, EL SISTEMA responderá permitiendo ese origen sin credenciales: no autoriza el envío de cookies ni de cabeceras de autenticación, y solo admite `GET` y su comprobación previa (DA-3).
- **RF-009b.** EL SISTEMA conservará el CORS actual en el resto de la API: ninguna ruta fuera del catálogo, ni las imágenes de la 043, se abre a otros orígenes. Una verificación automática lo comprueba con un origen no configurado.
- **RF-010.** SI un torneo, partido o jugador no es visible públicamente, ENTONCES EL SISTEMA responderá el mismo «no encontrado» de hoy, indistinguible de uno inexistente (RF-014 de la 020).

### Límite de peticiones

- **RF-011.** EL SISTEMA mantendrá el límite de peticiones de las lecturas públicas en el proxy, sin límite en la aplicación (DA-4). La documentación de despliegue incluirá una configuración de ejemplo con límite por IP para las rutas del catálogo: SI una IP lo supera, ENTONCES recibe 429 con `Retry-After`.
- **RF-011b.** El límite de RF-011 no afecta al sitio público: el SSR llama a la API por la red interna, sin pasar por el proxy, y la guía de RF-003 indica el límite que verá un tercero.

### Aislamiento

- **RF-012.** EL SISTEMA no mezclará datos de varias organizaciones en ninguna respuesta (RF-017 de la 020, con la excepción acotada de la ficha de jugador de la 038), y ninguna lectura permite modificar datos.

## Requisitos no funcionales

- **RNF-001.** Sin campos nuevos en ninguna respuesta pública ni cambios en lo que ve el sitio público (principio 5 de la constitución).
- **RNF-002.** El documento de RF-002 es válido según OpenAPI 3.1 y lo comprueba un test.
- **RNF-003.** La guía de RF-003 está en ES y EN, y cada ejemplo de respuesta se valida en un test contra el modelo de respuesta real, para que no quede desactualizado.
- **RNF-004.** Pasan los cinco jobs de CI; si se añade alguna dependencia, está fijada y pasa `pip-audit`, la auditoría del frontend y Trivy.

## Datos personales y privacidad

- Las lecturas públicas ya publican nombres de equipos y jugadores, dorsales y, con consentimiento de imagen, fotos (020, 038). Esta spec no añade ninguno.
- Nunca se publican documentos de identidad, fechas de nacimiento, edad, correos, motivos de W.O. o de resoluciones, sanciones ni datos de miembros (RF-016 de la 020).
- Un tercero puede guardar lo que lee. Por eso el contrato no va más allá de lo que ya muestra el sitio público.

## Casos límite

1. Un torneo despublicado o de una organización desactivada da «no encontrado» en todas las lecturas, también a un tercero que lo consultaba antes.
2. Un parámetro desconocido o inválido da el mismo error que hoy.
3. Una ficha de jugador sin ningún torneo autorizado da «no encontrado» (038).
4. Una foto firmada caduca; el documento de RF-002 y la guía lo indican.
5. Un campo que hoy puede ser `null` se documenta como tal; pasar a no aceptar `null` sería incompatible.
6. Redis caído no cambia el comportamiento de las lecturas públicas de hoy.

## Fuera de alcance

- Las imágenes para compartir de la 043 como parte del contrato (DA-1).
- Un límite de peticiones en la aplicación (DA-4).
- Lecturas o campos públicos nuevos, escrituras, webhooks públicos y tiempo real (Socket.IO) para terceros.
- Claves de API, registro de terceros, cuotas por cliente y facturación.
- Un portal para desarrolladores con cuentas.
- Retirar o restringir `/docs` de la API completa.
- Un contrato `v2`.

## Criterios de finalización

| # | Criterio | RF |
|---|---|---|
| 1 | Documento OpenAPI público con solo el catálogo, válido y verificado contra la lista cerrada. | RF-001, RF-002, RF-004, RNF-002 |
| 2 | Guía ES/EN con ejemplos verificados, errores, límites y política de versiones. | RF-003, RNF-003 |
| 3 | Copia de referencia del contrato y test que rechaza cambios incompatibles. | RF-005–RF-007 |
| 4 | Acceso sin credenciales, CORS abierto solo en el catálogo y mismo «no encontrado» que hoy. | RF-008–RF-010 |
| 5 | Configuración de ejemplo del proxy con límite por IP, sin afectar al SSR. | RF-011, RF-011b |
| 6 | Sin campos públicos nuevos ni mezcla de organizaciones. | RF-012, RNF-001 |

## Dudas abiertas

Ninguna. DA-1–DA-4 resueltas el 2026-11-27 (ver «Decisiones del usuario»).
