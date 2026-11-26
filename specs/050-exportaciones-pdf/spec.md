# Spec 050 — Exportaciones PDF (F10, parte 2)

Estado: borrador. Pedida por el usuario el 2026-11-26 («Sigamos con F7 y luego pasemos a PDF»), como continuación de la 048 («Apruebo la 048 solo con CSV; el PDF irá en una spec aparte»).

## Contexto y objetivo

La 048 dejó implementadas las exportaciones CSV del Workspace: clasificación, calendario, estadísticas de jugadores y de equipos, plantillas y el acta de un partido cerrado. El PDF quedó fuera de alcance, con la decisión del usuario de empezar por el acta y la clasificación.

Un CSV sirve para tratar los datos en una hoja de cálculo, pero no para imprimirlos, firmarlos o enviarlos a una federación tal como están. Para eso hace falta un documento con formato fijo, paginado, que se vea igual en cualquier equipo.

Lo que ya existe y se reutiliza: las lecturas de la 048 (los mismos datos del acta y de la clasificación, con los mismos criterios), la página «Exportaciones» del torneo, el botón del acta en el partido y el aislamiento por RLS.

**Objetivo:** que un miembro pueda obtener en PDF el acta de un partido cerrado y la clasificación de un torneo de su organización, con el mismo contenido que el CSV y sin exponer datos que hoy no ve.

## Usuarios

- Miembros de la organización que imprimen o archivan actas y envían la clasificación a equipos o federaciones.

## Roles y visibilidad

- **Público (sin sesión):** sin cambios. La vista pública no ofrece descargas, igual que en la 048.
- **Miembro de organización (cualquier rol, incluido observador):** obtiene en el Workspace el PDF del acta de los partidos cerrados y de la clasificación de los torneos de su organización, porque ya puede descargar sus CSV. No hacen falta permisos nuevos.
- **Administrador de plataforma:** sin cambios. No obtiene datos de ninguna organización.

## Historias de usuario

- HU-1. Como operador, quiero el acta de un partido cerrado en PDF para imprimirla y archivarla.
- HU-2. Como administrador, quiero la clasificación de un torneo en PDF para enviarla a los equipos tal como se ve.

## Definiciones

- **Documento PDF:** un archivo paginado de formato fijo, con el mismo contenido que el CSV correspondiente de la 048, más una cabecera con la organización, el torneo y la fecha de generación.
- **Acta exportable:** la misma de la 048: la versión vigente del acta confirmada de un partido cerrado; tras una rectificación (033), la última publicada. Nunca el borrador del partido en vivo (036).

## Requisitos funcionales

### Catálogo

- **RF-001.** EL SISTEMA ofrecerá en PDF un catálogo cerrado de dos documentos, con el mismo contenido y los mismos criterios que sus CSV de la 048 ([NECESITA ACLARACIÓN] DA-1):
  - **Acta de un partido cerrado:** resultado, oficiales por nombre y función, alineación de cada equipo con dorsal y hechos (minuto, tipo, equipo y jugador). En un W.O. o una resolución administrativa, el resultado y su motivo, sin hechos.
  - **Clasificación del torneo:** una tabla por fase y grupo, con posición, equipo, partidos jugados, ganados, empatados y perdidos, goles a favor y en contra, diferencia, puntos y puntos de juego limpio.
- **RF-002.** EL SISTEMA generará cada documento con los datos del momento de pedirlo y una cabecera con el nombre de la organización, el nombre del torneo, el partido (en el acta) y la fecha y hora de generación.
- **RF-003.** EL SISTEMA ofrecerá el PDF junto al CSV existente: en la fila de la clasificación de la página «Exportaciones» y junto al botón del acta del partido ([NECESITA ACLARACIÓN] DA-2 sobre cómo se genera).

### Visibilidad y privacidad

- **RF-004.** EL SISTEMA solo incluirá en un documento datos que quien lo pide ya puede descargar en el CSV correspondiente. Nunca incluirá documentos de identidad, fechas de nacimiento, edad, correos de cuentas, fotos de jugadores ni el borrador del partido en vivo ([NECESITA ACLARACIÓN] DA-3 sobre los escudos).
- **RF-005.** SI quien pide el documento no es miembro activo de la organización del torneo, o el torneo o el partido no existen, ENTONCES EL SISTEMA responderá con el mismo error que un torneo o partido inexistente, sin revelar si existen en otra organización.
- **RF-006.** CUANDO se pida el acta de un partido que no está cerrado, EL SISTEMA la rechazará con el mismo error explícito que el CSV.

### Auditoría

- **RF-007.** EL SISTEMA no registrará en la auditoría organizacional la obtención de estos documentos, igual que sus CSV en la 048 ([NECESITA ACLARACIÓN] DA-4).

### Aislamiento

- **RF-008.** EL SISTEMA aplicará el aislamiento por RLS a los dos documentos: ninguna organización puede obtener datos de otra.

## Requisitos no funcionales

- **RNF-001.** Los documentos usan tamaño A4 vertical, con márgenes de impresión, número de página («Página n de m» / «Page n of m») y la cabecera de las tablas repetida en cada página.
- **RNF-002.** El texto está en el idioma de la interfaz (ES/EN), es seleccionable (no una imagen) y muestra acentos, «ñ» y cualquier nombre en alfabeto latino sin caracteres sustituidos. Lo verifica un test con nombres con acentos, «ñ» y comillas.
- **RNF-003.** Un nombre de equipo o jugador con marcas o caracteres especiales (`<`, `>`, `&`, comillas) se muestra literalmente y no altera el documento. Lo verifica un test con nombres maliciosos.
- **RNF-004.** El límite es el mismo que en la 048: hasta 10.000 filas. SI se supera, ENTONCES EL SISTEMA responde con el mismo error explícito y no genera un documento truncado.
- **RNF-005.** Un acta de 22 jugadores por equipo y 60 hechos, o una clasificación de 8 grupos de 8 equipos, se genera en menos de 5 segundos en el entorno de CI.
- **RNF-006.** Sin campos públicos nuevos ni cambios en la proyección pública.
- **RNF-007.** Los textos nuevos están en ES y EN. Los botones nuevos se pueden usar con teclado y pasan axe en ambos temas.
- **RNF-008.** Si hace falta una dependencia nueva, debe ser madura y mantenida, y pasar `pip-audit`, la auditoría del frontend y Trivy (constitución §3.4 y §4).

## Datos personales y privacidad

- El acta lleva nombres de jugadores y oficiales, que ya aparecen en su CSV. Los oficiales van por nombre y función, sin correo.
- Nunca se incluyen documento, fecha de nacimiento, edad ni fotos de jugadores (principio 5, §3.4).
- Un documento descargado sale del control del sistema; por eso su contenido no va más allá del CSV correspondiente (RF-004).

## Casos límite

1. Un torneo sin clasificación calculada produce un documento con la cabecera y el aviso «Sin clasificación todavía» / «No standings yet».
2. Un partido rectificado produce el acta de la última versión publicada, no la original.
3. Un partido cerrado por W.O. o por resolución administrativa produce el resultado y su motivo, sin hechos.
4. Un nombre muy largo se parte en varias líneas dentro de su celda, sin salirse de la página ni recortarse.
5. Una clasificación con muchos grupos o un acta con muchos hechos ocupa varias páginas, con la cabecera de la tabla repetida.
6. Un torneo archivado se puede seguir exportando.
7. Cambiar de organización a mitad de una descarga descarta la respuesta, como en la 048.

## Fuera de alcance

- PDF del calendario, de las estadísticas y de las plantillas: quedan para una spec posterior, si se piden.
- Firmas digitales, códigos QR, marcas de agua o verificación del documento.
- Logotipo de la organización y personalización del diseño.
- Descargas en la vista pública.
- Documentos programados, por correo o por webhook.
- Documentos de varios torneos o partidos a la vez.

## Criterios de finalización

| # | Criterio | RF |
|---|---|---|
| 1 | Acta y clasificación en PDF, con el mismo contenido que su CSV y la cabecera. | RF-001, RF-002 |
| 2 | Disponibles junto al CSV en la página «Exportaciones» y en el partido. | RF-003 |
| 3 | Nada fuera de lo que el miembro ya descarga; sin documento, fecha de nacimiento, edad, correo ni foto. | RF-004 |
| 4 | Mismo error para torneo o partido ajeno o inexistente; aislamiento por RLS. | RF-005, RF-008 |
| 5 | Acta solo de partidos cerrados, en su versión vigente. | RF-001, RF-006 |
| 6 | A4 paginado, ES/EN, acentos correctos y nombres maliciosos mostrados literalmente. | RNF-001–RNF-003 |
| 7 | Límite de 10.000 filas sin truncar y tiempo de generación medido. | RNF-004, RNF-005 |
| 8 | Teclado y axe en ambos temas; auditorías de dependencias en verde. | RNF-007, RNF-008 |

## Dudas abiertas

- [NECESITA ACLARACIÓN] **DA-1. Qué documentos.** (a) Solo el acta y la clasificación, como decidiste en la 048 (recomendado). (b) También el calendario y las estadísticas.
- [NECESITA ACLARACIÓN] **DA-2. Cómo se genera.** (a) El servidor genera un archivo PDF con una dependencia Python madura y se descarga igual que el CSV (recomendado: el documento es idéntico en cualquier navegador y se prueba en CI). (b) Una vista imprimible en el navegador, que el usuario guarda con «Imprimir → Guardar como PDF»; sin dependencias, pero el resultado depende del navegador y no es una descarga directa.
- [NECESITA ACLARACIÓN] **DA-3. Escudos de los equipos.** (a) Sin imágenes: solo texto (recomendado: más simple y sin leer el almacenamiento de archivos). (b) Con el escudo de cada equipo, si lo tiene.
- [NECESITA ACLARACIÓN] **DA-4. Auditoría.** (a) Sin auditoría, igual que el CSV del acta y de la clasificación (recomendado). (b) Registrar cada documento generado.
