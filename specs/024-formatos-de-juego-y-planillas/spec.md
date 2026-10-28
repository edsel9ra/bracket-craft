# Spec 024 — Formatos de juego y planillas

Estado: borrador

## Contexto y objetivo

La spec 012 introdujo `game_format` (5v5, 7v7, 9v9, 11v11) como **dato puramente declarativo** con una advertencia visible cuando el formato no era 11v11: «la planilla soportada es de once y la modalidad real en la alineación llegará con la spec de formaciones». Esta spec 024 **convierte el formato en funcional**: deja de ser solo una etiqueta y pasa a **validar la configuración y a habilitar las operaciones compatibles con cada modalidad**, manteniendo intacto el contrato cerrado de formaciones (cuatro formaciones de once, `engine_version 2026.1`) y el modelo de alineaciones tácticas. Al mismo tiempo se **retira la advertencia genérica** y se permite editar la plantilla aunque existan incumplimientos, mostrando los avisos correspondientes.

**Objetivo:** que un torneo declarado 5v5/7v7/9v9 pueda operarse con alineaciones **sin formación táctica** (planilla de convocados) sin que el sistema le exija la formación gráfica de once, y que el formato valide la configuración y las operaciones que le corresponden, **sin cambiar** la estructura de la planilla, las reglas del ciclo de vida del partido, el cierre, las sustituciones, la presencia en campo, los minutos, las sanciones, la clasificación, las estadísticas ni el outbox.

## Usuarios

- Administrador de organización y operador, que configuran el formato y operan partidos.
- Observador, que consulta en modo lectura.
- Aficionado, que consulta públicamente (sin cambios en la proyección pública).

## Roles y visibilidad

- **Público (sin sesión):** sin cambios. Sigue viendo la formación publicada (campo gráfico) cuando existe y la planilla (convocados) cuando no la hay; el formato no añade campos a la proyección pública.
- **Miembro de organización (incluido observador):** ve el formato en la configuración y en el resumen del torneo, en solo lectura cuando la versión está publicada. Sin cambios de permisos.
- **Administrador de organización / operador:** configura el formato en un borrador y opera partidos según las operaciones compatibles con el formato.
- **Administrador de plataforma:** sin cambios.

## Historias de usuario

- HU-1. Como administrador, quiero declarar un torneo como 5v5/7v7/9v9/11v11 y que el sistema deje de exigirme la formación táctica gráfica de once, para poder operarlo con la planilla de convocados sin avisos genéricos.
- HU-2. Como administrador, quiero que el formato valide la configuración y las operaciones que le corresponden, para no usar por error una capacidad exclusiva de 11v11 en otra modalidad.
- HU-3. Como operador, quiero seguir editando la plantilla aunque existan incumplimientos de tamaño, viendo los avisos correspondientes, para poder corregir la situación sin bloqueos.
- HU-4. Como observador, quiero ver el formato declarado como contexto informativo, sin que cambie nada de lo que ya veo.

## Definiciones

- **Formato de juego (`game_format`):** modalidad declarada del torneo, uno de `5v5`, `7v7`, `9v9`, `11v11`. Valor por defecto `11v11`. Es **configuración aditiva** de la versión, fuera del contrato cerrado de formaciones (`docs/contrato-reglas.md`, `engine_version 2026.1`).
- **Formación táctica:** código del catálogo cerrado de cuatro formaciones (`4-3-3`, `4-4-2`, `3-5-2`, `4-2-3-1`) con la posición de cada titular. **Exclusiva de 11v11.**
- **Planilla (convocados):** relación de titulares y suplentes de un equipo en un partido, sin posiciones. Es el modo de alineación disponible en **todos** los formatos.
- **Operación compatible con el formato:** acción que el sistema permite según la modalidad declarada. La ausencia de formación táctica gráfica no es un incumplimiento y no bloquea.
- **Validación funcional explícita:** comprobación concreta y nombrada (tamaño de plantilla, formato no soportado para la operación, etc.) que el servidor aplica y que bloquea el guardado o la operación.

## Requisitos funcionales

### Formato como validador funcional

- **RF-001.** EL SISTEMA mantendrá el `game_format` como valor declarado de la configuración de la versión, con el catálogo cerrado de cuatro opciones (`5v5`, `7v7`, `9v9`, `11v11`) y el valor por defecto `11v11`, y lo tratará como **validador funcional** de las operaciones que le corresponden, sin alterar el contrato cerrado de formaciones ni `engine_version` (2026.1).
  *Criterios de aceptación:*
  - El formato sigue siendo una clave aditiva de la configuración de la versión; no se añaden tablas, columnas ni migraciones.
  - El formato no deriva, acota ni condiciona el mínimo ni el máximo de plantilla, ni el número de titulares, ni la banca: los mismos valores de límites son válidos con 5v5 y con 11v11.
  - El formato se muestra en la configuración y en el resumen del torneo como contexto informativo; no se añade a la proyección pública.

- **RF-002.** CUANDO se intente usar una capacidad exclusiva de 11v11 en un torneo cuyo formato no sea 11v11, EL SISTEMA rechazará la operación como **no soportada para ese formato**, sin alterar datos.
  *Criterios de aceptación:*
  - La **única** capacidad exclusiva de 11v11 es el catálogo de formaciones tácticas (publicar, seleccionar o aplicar una formación gráfica). Intentar publicar, seleccionar o aplicar una formación táctica en un formato distinto de 11v11 responde con un rechazo que identifica la operación como no soportada para el formato, sin escribir.
  - La **despublicación** de una formación táctica sigue permitida en **cualquier** formato, incluido 5v5/7v7/9v9, para retirar formaciones publicadas previamente.
  - El rechazo se expresa como HTTP 409 Conflict con el código aditivo `FORMATION_NOT_SUPPORTED_FOR_FORMAT` y un `detail` en cadena localizado, sin modificaciones persistentes ni eventos de dominio. El código se documenta junto a los errores existentes en RF-006.
  - La planilla de convocados (titulares y suplentes sin posiciones) sigue disponible en **todos** los formatos y no se considera degradada.
  - Las demás operaciones (partidos, segmentos, eventos, cierre, sustituciones, sanciones, clasificación, estadísticas) no dependen del formato y se comportan igual en todas las modalidades.

### Formaciones tácticas exclusivas de 11v11

- **RF-003.** EL SISTEMA mantendrá el catálogo de formaciones tácticas **exclusivo de 11v11**: las cuatro formaciones y sus 23 posiciones solo se usan cuando el formato es 11v11, y los formatos 5v5, 7v7 y 9v9 operan con alineaciones **sin formación táctica**, sin alterar las reglas de titulares y suplentes.
  *Criterios de aceptación:*
  - En un torneo no 11v11 no se ofrece publicar, seleccionar ni aplicar una formación táctica; la alineación se publica como planilla de convocados.
  - La **despublicación** de una formación táctica sigue permitida en cualquier formato.
  - La ausencia de formación táctica gráfica no impide guardar una alineación simplificada (planilla de convocados) en cualquier formato.
  - Las reglas de titulares y suplentes (presencia en campo, sustituciones, límites por equipo y partido) no cambian por formato.
  - `docs/contrato-reglas.md` y `engine_version 2026.1` no se modifican.

### Retiro de la advertencia genérica

- **RF-004.** CUANDO el soporte funcional de un formato esté implementado, EL SISTEMA **retirará** el aviso genérico «la planilla soportada es de once jugadores y la modalidad real en la alineación llegará con la spec de formaciones», en los tres lugares donde se mostraba (paso de reglas, resumen de configuración y pantalla de operación/planilla), y **no** lo sustituirá por mensajes equivalentes que sigan afirmando que la planilla de once es el único formato admitido.
  *Criterios de aceptación:*
  - El aviso genérico se elimina del código y de todos los puntos de presentación identificados; no se mantiene como advertencia ni se sustituye por otro texto equivalente.
  - Con formato 11v11 no aparecía el aviso; con los demás formatos tampoco aparece tras esta spec.
  - La interfaz podrá mostrar información contextual veraz sobre el formato seleccionado y las funciones disponibles (por ejemplo, «Formato 7v7 · alineación sin esquema táctico»).
  - Los mensajes de error solo aparecerán cuando una operación concreta no esté soportada o se incumpla una validación definida.
  - El formato se sigue mostrando como contexto informativo junto a los límites, sin sugerir que determine el número de jugadores.

### Bloqueo solo por validaciones funcionales explícitas

- **RF-005.** EL SISTEMA bloqueará el guardado o la operación **únicamente** por incumplimientos de validaciones funcionales explícitas (tamaño de plantilla fuera de rango, operación no soportada para el formato) o por las validaciones ya existentes; la **ausencia de formación táctica gráfica no bloquea**. Publicar una alineación sin formación táctica es válido en cualquier formato, incluido 11v11.
  *Criterios de aceptación:*
  - Publicar una alineación sin formación táctica es válido en cualquier formato, incluido 11v11.
  - Un equipo con plantilla fuera de los límites de tamaño sigue pudiendo guardar la plantilla; solo se bloquea la inscripción en fase, el alta con fase destino y la apertura del partido (RF-045, RF-046 y RF-050 de la spec 012).
  - No se añade ningún bloqueo nuevo por formato distinto de los enumerados.

### Edición de plantilla con avisos

- **RF-006.** CUANDO el usuario edite la plantilla de un equipo, EL SISTEMA permitirá guardarla **aunque existan incumplimientos** (tamaño fuera de rango, formato no 11v11 sin formación), mostrando los avisos correspondientes, sin perder los datos introducidos. El guardado de borradores no se restringe por formato exclusivamente por ser formación táctica, siempre que no implique publicación ni aplicación a una alineación.
  *Criterios de aceptación:*
  - El alta individual, la importación CSV/ZIP, la subida de foto y el consentimiento se guardan siempre que cumplan sus validaciones propias; los incumplimientos de formato o tamaño solo avisan.
  - Los avisos identifican el motivo (tamaño fuera de rango con mínimo, máximo y cantidad actual; operación no soportada para el formato) en el idioma activo.
  - Ninguna operación de edición de plantilla devuelve un rechazo por formato o por tamaño.
  - En el endpoint de publicación, tras autorización y estado del recurso, se comprueba el formato antes de validar número de titulares/posiciones: si el formato no es 11v11, se responde con `FORMATION_NOT_SUPPORTED_FOR_FORMAT`, independientemente de otros errores estructurales.
  - **Códigos de error aditivos documentados (convención `<CONCEPTO>_<RAZÓN>`):**
    - `FORMATION_NOT_SUPPORTED_FOR_FORMAT`: operación de publicación, selección o aplicación de formación táctica en un formato distinto de 11v11 (HTTP 409).
    - `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED`: intento de cambiar el formato de 11v11 a 5v5/7v7/9v9 mientras exista una formación táctica publicada (HTTP 409).

### Ciclo de vida del partido sin cambios

- **RF-007.** EL SISTEMA conservará sin cambios las reglas del ciclo de vida del partido para todos los formatos: validaciones del cierre del acta, sustituciones, presencia en campo, minutos, sanciones, clasificación, estadísticas y outbox.
  *Criterios de aceptación:*
  - No se añaden validaciones de cierre, sustituciones ni presencia en campo dependientes del formato.
  - La portería imbatida y las estadísticas públicas (spec 022) no cambian por formato ni por la presencia o ausencia de formación táctica publicada.
  - La atribución individual de la portería imbatida al portero sigue dependiendo de la fuente actual (formación publicada con `GK`). En formatos sin formación táctica publicada no se infiere automáticamente la identidad del portero a partir de la planilla de convocados; queda sin determinar si no hay evidencia suficiente. No se recomienda inferir que un jugador convocado como portero jugó en esa posición. Si se quiere atribuir porterías imbatidas en 5v5/7v7/9v9, deberá definirse por separado un mecanismo explícito para identificar al portero por partido/segmento.
  - Los eventos de outbox y el tiempo real no cambian.

### Compatibilidad e inmutabilidad

- **RF-008.** EL SISTEMA mantendrá inmutables las versiones publicadas, las inscripciones existentes y las actas cerradas al introducir el soporte funcional del formato.
  *Criterios de aceptación:*
  - Una versión publicada sin la clave `game_format` se resuelve como 11v11 y conserva el comportamiento actual.
  - Cambiar el formato en un borrador no altera inscripciones, fases, calendario, plantillas ni partidos ya creados.
  - Las actas cerradas no se revalidan ni se corrigen por el formato.

### Aislamiento y permisos

- **RF-009.** EL SISTEMA aplicará el formato y sus validaciones dentro del aislamiento por organización, sin exponerlo fuera de la organización ni aceptar valores de otra, y sin cambiar permisos.
  *Criterios de aceptación:*
  - El formato vive en la configuración de la versión del torneo de la organización activa; ninguna otra organización puede leerlo ni modificarlo.
  - No se añaden endpoints ni parámetros nuevos para el formato; se reutilizan los de configuración de versión.
  - Ningún rol gana ni pierde permisos; la escritura sigue exigiendo el permiso de gestión de torneos.

### Sin migración ni cambio de esquema

- **RF-010.** EL SISTEMA implementará el soporte funcional del formato **sin migración ni cambio de esquema**: reutilizando los campos y la configuración existentes (`game_format`, `min_players_per_team`, `max_players_per_team`), limitando los cambios a validaciones del backend/API y ajustes del frontend.
  *Criterios de aceptación:*
  - No se añaden tablas, columnas, índices, políticas ni permisos de base de datos.
  - `engine_version` se mantiene en 2026.1 y `schema_version` no cambia.
  - `docs/contrato-reglas.md` no cambia; solo se aclara, si hiciera falta, que el formato sigue fuera del contrato cerrado.

### Cambio de formato con formación publicada

- **RF-011.** CUANDO se intente cambiar el formato de un torneo en borrador de 11v11 a 5v5/7v7/9v9 mientras exista una formación táctica publicada, EL SISTEMA rechazará el cambio hasta que la formación haya sido despublicada, sin eliminar ni despublicar automáticamente. Una vez retirada la formación, se podrá modificar el formato, conservándose el registro histórico de la formación y evitando que permanezca publicada como alineación válida.
  *Criterios de aceptación:*
  - El sistema no elimina ni despublica automáticamente la formación al cambiar el formato.
  - La respuesta es HTTP 409 Conflict con el código aditivo `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED` y un `detail` en cadena localizado, sin modificaciones persistentes ni eventos de dominio.
  - Tras despublicar la formación, el cambio de formato se permite si se cumplen las demás reglas.

### Privacidad de la alineación pública

- **RF-012.** EL SISTEMA mantendrá que, en formatos 5v5/7v7/9v9, la publicación de la alineación simplificada no exponga posiciones tácticas individuales ni datos derivados de una formación gráfica, conservando el comportamiento de privacidad existente. La inclusión de nuevos formatos no amplía los datos personales publicados ni los permisos de acceso.
  *Criterios de aceptación:*
  - La verificación se realiza mediante pruebas de contrato de la respuesta pública, no solo visualmente en el frontend.
  - No se añaden campos públicos nuevos ni se amplían los permisos.

### Consistencia de interpretación del formato ausente

- **RF-013.** EL SISTEMA interpretará de forma consistente un `game_format` ausente como `11v11` en backend, API y clientes, no solo en la interfaz.
  *Criterios de aceptación:*
  - Un registro antiguo sin `game_format` se resuelve como 11v11 en todas las capas.
  - La interpretación se aplica en backend, API y clientes de forma consistente.

## Requisitos no funcionales

- **RNF-001. Sin cambios de contrato HTTP.** No se añaden endpoints, campos de petición ni campos de respuesta nuevos. Los códigos de respuesta existentes se conservan; el rechazo por operación no soportada para el formato se expresa con los códigos aditivos `FORMATION_NOT_SUPPORTED_FOR_FORMAT` y `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED` y un `detail` en cadena, sin cambiar los existentes.
- **RNF-002. Sin cambios de esquema ni migración.** Como RF-010.
- **RNF-003. Paridad de idiomas.** Todo texto nuevo (avisos, rechazos, etiquetas) existe en español y en inglés en el mismo cambio.
- **RNF-004. Accesibilidad.** Los avisos y rechazos se anuncian correctamente y no bloquean la edición de la plantilla; los controles mantienen sus etiquetas accesibles.
- **RNF-005. Trazabilidad documental.** Se actualizan en el mismo cambio `README.md`, `AGENTS.md` y `/docs` para reflejar que el formato deja de ser solo declarativo y que la advertencia genérica se retira, sin contradecir la constitución.
- **RNF-006. Sin duplicación de capacidad.** Cada capacidad (configuración del formato, edición de plantilla, publicación de alineación) mantiene una sola pantalla responsable.

## Datos personales y privacidad

- **Datos involucrados:** ninguno nuevo. El formato y sus validaciones no tocan datos personales.
- **Quién los ve:** sin cambios.
- **Qué no se expone:** el formato no se añade a la proyección pública; las respuestas públicas no cambian. En formatos 5v5/7v7/9v9, la publicación de la alineación simplificada no expone posiciones tácticas individuales ni datos derivados de una formación gráfica. No se amplían los datos personales publicados ni los permisos de acceso.
- **Aislamiento:** sin cambios; todo opera sobre la organización activa.

## Casos límite

1. **Torneo 11v11 con formación publicada:** sigue funcionando como hoy; el formato no cambia nada.
2. **Torneo 5v5/7v7/9v9 que intenta publicar una formación táctica:** rechazo HTTP 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT`, sin escribir; la planilla de convocados sigue disponible.
3. **Torneo sin `game_format` (versión antigua):** se resuelve como 11v11; comportamiento actual, en backend, API y clientes.
4. **Plantilla fuera de rango en un formato no 11v11:** se guarda con aviso; solo se bloquea inscripción/apertura/alta con fase destino.
5. **Cambio de formato en un borrador con partidos ya creados:** los partidos y actas no se revalidan ni se corrigen.
6. **Intento de usar una formación táctica en un formato no 11v11 desde un cliente antiguo:** el servidor rechaza con el código aditivo correspondiente; el cliente antiguo muestra el error sin romperse.
7. **Registro antiguo sin `game_format`:** se interpreta como 11v11 (compatibilidad).
8. **Cliente antiguo intenta publicar formación en 7v7:** HTTP 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT`, sin escritura.
9. **Cliente antiguo intenta aplicar una formación en 5v5:** rechazo equivalente, sin mutaciones.
10. **Torneo 11v11 con formación publicada cambia a 9v9:** rechazo hasta despublicar (`PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED`).
11. **Se despublica una formación y después se cambia a 9v9:** operación permitida si se cumplen las demás reglas.
12. **Se guarda un borrador de formación en 7v7:** permitido según contrato de borradores, sin publicación ni aplicación táctica.
13. **Torneo 11v11 existente con formación publicada:** comportamiento actual preservado.

## Fuera de alcance

- Formaciones tácticas por modalidad (5v5, 7v7, 9v9 con sus propios esquemas de posiciones). Se reserva a una spec independiente.
- Cambio del número de titulares o de la banca por formato. La estructura de la planilla no se modifica.
- Nuevos endpoints o migraciones.
- Cambio de `engine_version` o `schema_version`.
- Estadísticas, clasificación o sanciones dependientes del formato.

## Criterios de finalización

- Un torneo declarado no 11v11 puede publicar una alineación como planilla de convocados sin formación táctica y sin avisos genéricos.
- Intentar publicar, seleccionar o aplicar una formación táctica en un formato no 11v11 responde HTTP 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT` y no escribe.
- Intentar cambiar el formato a no 11v11 con formación publicada responde HTTP 409 `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED` y no escribe.
- La advertencia genérica de «once jugadores» no aparece en ningún lugar.
- La edición de plantilla sigue permitida con incumplimientos, mostrando avisos.
- Las validaciones de cierre, sustituciones, presencia, minutos, sanciones, clasificación, estadísticas y outbox no cambian.
- No se añaden migraciones, endpoints ni campos nuevos.
- `engine_version` sigue en 2026.1 y `schema_version` sin cambios.

## Dudas abiertas

Ninguna. Las cinco preguntas de clarificación quedaron resueltas y se incorporaron a los RF anteriores. Las aclaraciones del reviewer sobre formaciones tácticas exclusivas de 11v11, códigos de error aditivos, despublicación permitida, portería imbatida sin inferencia, rechazo de cambio de formato con formación publicada, consistencia de interpretación de `game_format` ausente, privacidad de la alineación pública y retirada del aviso genérico se incorporaron a los RF y casos límite.
