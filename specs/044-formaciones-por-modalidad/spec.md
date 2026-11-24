# Spec 044 — Formaciones por modalidad (F12)

Estado: borrador

## Contexto y objetivo

La spec 024 convirtió `game_format` (`5v5`, `7v7`, `9v9`, `11v11`) en validador funcional, pero dejó el catálogo cerrado de formaciones tácticas como **exclusivo de 11v11**: cuatro formaciones de once (`4-3-3`, `4-4-2`, `3-5-2`, `4-2-3-1`) y 23 posiciones. Hoy un torneo 5v5, 7v7 o 9v9:

- solo puede publicar la planilla de convocados, sin campo gráfico;
- recibe 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT` si intenta guardar o publicar una formación;
- no puede atribuir la portería imbatida a un portero, porque esa atribución depende de la posición `GK` de una formación publicada (spec 022).

La 024 reservó las formaciones por modalidad a una spec independiente (su «Fuera de alcance»), y el informe de funciones adicionales las registra como F12.

**Objetivo:** que cada modalidad tenga su propio catálogo cerrado de formaciones tácticas, con el número de titulares que le corresponde, para que los torneos de fútbol 5, 7 y 9 puedan operar y publicar alineaciones gráficas como los de once, sin ampliar lo público ni cambiar las reglas deportivas.

## Usuarios

- Administrador de organización y operador, que configuran el formato y operan partidos.
- Observador, que consulta en modo lectura.
- Aficionado, que consulta la alineación publicada en la vista pública.

## Roles y visibilidad

- **Público (sin sesión):** ve la formación publicada (campo gráfico) de cualquier modalidad, con los mismos campos públicos que hoy. Sin campos nuevos.
- **Miembro de organización (incluido observador):** ve las formaciones del Workspace en solo lectura. Sin cambios de permisos.
- **Administrador de organización / operador:** elige, guarda, publica y despublica la formación de su modalidad con los permisos actuales.
- **Administrador de plataforma:** sin cambios.

## Historias de usuario

- HU-1. Como operador de un torneo 7v7, quiero elegir una formación de siete y colocar a mis titulares en sus posiciones, para publicar la alineación gráfica como en un torneo de once.
- HU-2. Como administrador, quiero que el sistema solo me ofrezca las formaciones de la modalidad del torneo, para no publicar por error una formación de once en fútbol 5.
- HU-3. Como aficionado, quiero ver en el campo gráfico la formación de un partido de fútbol 5, 7 o 9, para entender cómo jugó cada equipo.
- HU-4. Como organizador de un torneo 11v11, quiero que nada cambie en mis torneos y partidos actuales.

## Definiciones

- **Modalidad:** el valor de `game_format` de la versión del torneo; ausente equivale a `11v11` (RF-013 de la 024).
- **Formación táctica:** esquema con un número fijo de titulares y una posición distinta para cada uno, dentro del catálogo cerrado de una modalidad.
- **Titulares de la modalidad:** 5, 7, 9 u 11 jugadores, incluido el portero.
- **Planilla de convocados:** alineación de titulares y suplentes sin formación ni posiciones (sin cambios respecto a la 024).

## Requisitos funcionales

### Catálogo por modalidad

- **RF-001.** EL SISTEMA mantendrá un catálogo cerrado de formaciones tácticas por modalidad. El catálogo de 11v11 conserva exactamente las cuatro formaciones y posiciones actuales. Los catálogos de 5v5, 7v7 y 9v9 se fijan en DA-1.
  *Criterios de aceptación:*
  - Cada formación pertenece a una sola modalidad y declara sus posiciones en orden de portero a delantera.
  - Toda formación incluye exactamente un portero (`GK`) y tantas posiciones como titulares de la modalidad.
  - Las posiciones reutilizan códigos del catálogo actual de 23 posiciones siempre que exista uno equivalente; un código nuevo solo se añade si ninguno existente describe la posición.
  - Una formación fuera del catálogo se rechaza en la API (422) y en la base de datos.

- **RF-002.** CUANDO se guarde una alineación con formación, EL SISTEMA aceptará solo formaciones del catálogo de la modalidad del torneo y exigirá exactamente los titulares de la modalidad, cada uno en una posición distinta de esa formación.
  *Criterios de aceptación:*
  - Una formación de otra modalidad responde 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT`, sin escribir.
  - Un número de titulares distinto del de la modalidad, o posiciones repetidas o ajenas a la formación, responde 422, sin escribir.
  - Las demás validaciones del guardado (segmento activo, sin eventos, inscripciones elegibles, ambos equipos con formación) no cambian.

- **RF-003.** CUANDO se publique una formación, EL SISTEMA exigirá que la alineación guardada tenga exactamente los titulares de la modalidad y todas las posiciones de su formación; SI no los tiene, ENTONCES responderá 409 sin publicar.
  *Criterios de aceptación:*
  - El mensaje de error nombra el número de titulares de la modalidad, en el idioma activo.
  - La despublicación sigue permitida en cualquier modalidad.

### Cambio de formato

- **RF-004.** CUANDO se intente cambiar el formato de un borrador mientras exista una formación publicada de otra modalidad en sus partidos, EL SISTEMA rechazará el cambio con 409 `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED`, sin despublicar ni borrar nada.
  *Criterios de aceptación:*
  - Generaliza la regla de la 024, que solo cubría el paso de 11v11 a otra modalidad, a cualquier par de modalidades distintas.
  - Cambiar a la misma modalidad de las formaciones publicadas se permite.

### Planilla de convocados

- **RF-005.** EL SISTEMA mantendrá la planilla de convocados en todas las modalidades, con las reglas actuales (ver DA-2 para el número de titulares).

### Operación y presentación

- **RF-006.** EL SISTEMA ofrecerá en la operación del partido solo las formaciones de la modalidad del torneo y mostrará cada formación en el campo gráfico del Workspace y de la vista pública, con todas sus posiciones visibles y sin solaparse.
  *Criterios de aceptación:*
  - Las alineaciones de 11v11 se ven igual que hoy.
  - La precarga entre segmentos (028) funciona igual con cualquier modalidad.
  - En la vista pública, una formación publicada de 5v5/7v7/9v9 se dibuja en el campo; una formación inválida o desconocida cae a la planilla, como hoy.

- **RF-007.** EL SISTEMA retirará la información contextual de la 024 que indica que los formatos 5v5/7v7/9v9 se operan «sin esquema táctico», y la sustituirá por texto veraz sobre el catálogo disponible, en español e inglés.

### Estadísticas

- **RF-008.** EL SISTEMA atribuirá la portería imbatida según DA-3.

### Compatibilidad, aislamiento y contrato

- **RF-009.** EL SISTEMA mantendrá inmutables las versiones publicadas, las alineaciones guardadas y las actas cerradas: ninguna formación existente se reescribe ni se revalida.
- **RF-010.** EL SISTEMA aplicará el catálogo dentro del aislamiento por organización y con los permisos actuales; ninguna organización puede leer ni modificar formaciones de otra.
- **RF-011.** EL SISTEMA documentará el catálogo ampliado en `docs/contrato-reglas.md`, con la versión del contrato que fije DA-4, y la prueba del contrato comprobará que el código, la API y la base de datos coinciden con el documento.

## Requisitos no funcionales

- **RNF-001. Contrato HTTP.** No se añaden endpoints ni campos de petición o respuesta; el catálogo de valores admitidos de `formation_code` crece. Los códigos de error existentes se conservan.
- **RNF-002. Base de datos.** El catálogo cerrado se refuerza en la base de datos con una migración nueva, válida sobre un volumen limpio y uno ya migrado.
- **RNF-003. Paridad de idiomas.** Todo texto nuevo existe en español y en inglés.
- **RNF-004. Accesibilidad.** Selector de formación y posiciones con etiquetas accesibles; el campo gráfico mantiene sus nombres accesibles y su contraste en ambos temas, a 1440 y 390 px.
- **RNF-005. Trazabilidad documental.** README, AGENTS, manual de usuario, contrato de reglas, informe (F12) y MEMORY se actualizan en el mismo cambio.

## Datos personales y privacidad

- **Datos involucrados:** ninguno nuevo. Las posiciones son etiquetas tácticas, no datos personales.
- **Qué se expone públicamente:** lo mismo que hoy para 11v11 (formación, posición, nombre y dorsal, y foto solo con consentimiento). No se exponen documentos, fechas de nacimiento ni edad.
- **Aislamiento:** sin cambios.

## Casos límite

1. Torneo sin `game_format`: se trata como 11v11 y solo ofrece las cuatro formaciones de once.
2. Cliente antiguo que envía `4-3-3` en un torneo 7v7: 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT`, sin escribir.
3. Formación de 7v7 con 8 titulares: 422, sin escribir.
4. Torneo 7v7 con una formación de 7 publicada que cambia a 5v5: 409 hasta despublicarla.
5. Torneo 9v9 que cambia a 9v9 con formaciones publicadas: se permite.
6. Partido de 11v11 con formación publicada antes de esta spec: se ve igual y sus estadísticas no cambian.
7. Formación publicada de una modalidad que un cliente público antiguo no conoce: cae a la planilla, sin romperse.
8. Segmento posterior de un partido 5v5: la precarga de la 028 copia la formación de cinco.

## Fuera de alcance

- Cambiar reglas deportivas por modalidad: duración, sustituciones ilimitadas o volantes, tamaño de banca, puntuación o disciplina.
- Derivar del formato el mínimo y el máximo de plantilla (la 024 lo excluyó).
- Formaciones personalizadas o editables por la organización.
- Posiciones libres en el campo (arrastrar jugadores).
- Estadísticas nuevas por posición (F17).
- Campos públicos nuevos.

## Criterios de finalización

1. Cada RF tiene al menos una prueba automatizada que lo cubre.
2. La prueba del contrato de reglas comprueba código, API, base de datos y documento.
3. La migración pasa sobre un volumen limpio y uno ya migrado.
4. E2E del Workspace y de la vista pública con axe sin violaciones en ambos temas, a 1440 y 390 px, para al menos una formación de cada modalidad.
5. CI en verde y documentación actualizada.

## Dudas abiertas

- [NECESITA ACLARACIÓN] DA-1. ¿Qué formaciones forman el catálogo de 5v5, 7v7 y 9v9?
- [NECESITA ACLARACIÓN] DA-2. ¿La modalidad fija también el número de titulares de la planilla de convocados, o solo el de las alineaciones con formación?
- [NECESITA ACLARACIÓN] DA-3. ¿Se atribuye la portería imbatida al `GK` de una formación publicada en 5v5/7v7/9v9, igual que en 11v11?
- [NECESITA ACLARACIÓN] DA-4. ¿El catálogo ampliado mantiene `engine_version` 2026.1 o sube a 2026.2?
