# Spec 048 — Exportaciones CSV (F10)

Estado: borrador. DA-1–DA-4 resueltas el 2026-11-25. Pedida por el usuario el 2026-11-25 («F10: exportaciones CSV o PDF»).

## Decisiones del usuario (2026-11-25)

- **DA-1 = (a).** Las exportaciones solo se descargan en el Workspace, para los miembros de la organización. La vista pública no cambia.
- **DA-2 = (a).** Solo CSV, para las cinco exportaciones, sin dependencias nuevas. El PDF queda fuera de alcance.
- **DA-3 = (a).** Las plantillas llevan equipo, dorsal, nombre, apellidos, estado (activo o retirado) y consentimiento de imagen (sí/no), sin edad. Las descarga cualquier miembro, igual que hoy ve la pantalla de plantillas, y cada descarga queda en la auditoría organizacional (041).
- **DA-4 = (a).** El acta es un archivo por partido cerrado, pedido desde el partido, con las alineaciones y los hechos con el jugador.

## Contexto y objetivo

Hoy los datos de un torneo solo se consultan en pantalla: la clasificación, el calendario y las estadísticas en la vista pública, y el calendario, las plantillas y la operación del partido en el Workspace. No hay forma de sacarlos para imprimirlos, enviarlos a una federación o tratarlos en una hoja de cálculo.

Las specs 018, 020 y 022 dejaron fuera las exportaciones. El informe de funciones adicionales las registra como F10: CSV o PDF de clasificación, calendario, actas y estadísticas, con las plantillas solo en privado y sin documento ni fecha de nacimiento.

Lo que ya existe y se reutiliza: las lecturas privadas del Workspace (calendario, plantillas y operación del partido), la clasificación y las estadísticas que calcula el sistema, la proyección pública (principio 5) y la auditoría organizacional (041).

**Objetivo:** que un miembro pueda descargar los datos de un torneo de su organización en un formato que se abra en una hoja de cálculo, sin exponer datos que hoy no ve.

## Usuarios

- Miembros de la organización que preparan informes, imprimen el calendario o envían resultados a terceros.

## Roles y visibilidad

- **Público (sin sesión):** sin cambios. La vista pública no ofrece descargas (DA-1).
- **Miembro de organización (cualquier rol, incluido observador):** descarga en el Workspace las cinco exportaciones de los torneos de su organización, porque ya ve esos datos. No hacen falta permisos nuevos (DA-3).
- **Administrador de plataforma:** sin cambios. No descarga datos de ninguna organización.

## Historias de usuario

- HU-1. Como administrador, quiero descargar la clasificación y el calendario de un torneo para enviarlos a los equipos.
- HU-2. Como operador, quiero descargar el acta de un partido cerrado para archivarla.
- HU-3. Como administrador, quiero descargar las plantillas de un torneo para comprobar las inscripciones, sin que el archivo lleve documentos ni fechas de nacimiento.
- HU-4. Como miembro, quiero descargar las estadísticas de jugadores y equipos de un torneo.

## Definiciones

- **Exportación:** un archivo descargable con un conjunto cerrado de columnas, generado en el momento de pedirlo.
- **Acta exportable:** la versión vigente del acta confirmada de un partido cerrado; tras una rectificación (033), la última publicada. Nunca el borrador del partido en vivo (036).

## Requisitos funcionales

### Catálogo

- **RF-001.** EL SISTEMA ofrecerá un catálogo cerrado de cinco exportaciones por torneo:
  - **Clasificación:** por fase y grupo, con posición, equipo, partidos jugados, ganados, empatados y perdidos, goles a favor y en contra, diferencia, puntos y puntos de juego limpio.
  - **Calendario:** cada partido con fase, grupo o código de llave, jornada, fecha, local, visitante, estado y, si está cerrado, el marcador.
  - **Estadísticas:** de jugadores (goles, amarillas, rojas, porterías imbatidas y partidos jugados) y de equipos (goles a favor y en contra, porterías imbatidas y juego limpio), con los mismos criterios que la vista pública (020, 022).
  - **Acta de un partido:** un archivo por partido cerrado, pedido desde el partido, con el resultado, los oficiales por nombre y función, la alineación de cada equipo y los hechos (minuto, tipo, equipo y jugador) (DA-4).
  - **Plantillas:** todos los equipos del torneo, con equipo, dorsal, nombre, apellidos, estado (activo o retirado) y consentimiento de imagen (sí/no). Sin edad (DA-3).
- **RF-002.** EL SISTEMA generará cada exportación con los datos del momento de pedirla. Las columnas y su orden son fijos y están documentados.
- **RF-003.** EL SISTEMA generará las cinco exportaciones en CSV (DA-2).

### Visibilidad y privacidad

- **RF-004.** EL SISTEMA solo incluirá en una exportación datos que quien la pide ya puede ver en el Workspace. Nunca incluirá documentos de identidad, fechas de nacimiento, correos de cuentas, fotos ni el borrador del partido en vivo.
- **RF-005.** SI quien pide la exportación no es miembro activo de la organización del torneo, o el torneo o el partido no existen, ENTONCES EL SISTEMA responderá con el mismo error que un torneo o partido inexistente, sin revelar si existen en otra organización.
- **RF-006.** CUANDO se pida el acta de un partido que no está cerrado, EL SISTEMA la rechazará con un error explícito.

### Auditoría

- **RF-007.** CUANDO un miembro descargue las plantillas de un torneo, EL SISTEMA lo registrará en la auditoría organizacional (041) con el torneo y el número de filas, sin nombres de jugadores (DA-3). Las demás exportaciones no se auditan.

### Aislamiento

- **RF-008.** EL SISTEMA aplicará el aislamiento por RLS a todas las exportaciones: ninguna organización puede descargar datos de otra.

## Requisitos no funcionales

- **RNF-001.** Los archivos CSV van en UTF-8 con BOM, separados por comas, con cabecera en el idioma de la interfaz (ES/EN), y se abren con acentos correctos en las hojas de cálculo habituales.
- **RNF-002.** Una celda que empiece por `=`, `+`, `-`, `@`, tabulador o retorno de carro se neutraliza (inyección de fórmulas). Lo verifica un test con nombres de equipo y jugador maliciosos.
- **RNF-003.** Una exportación contiene el torneo completo, sin paginar, hasta 10.000 filas. SI se supera, ENTONCES EL SISTEMA responde con un error explícito y no genera un archivo truncado.
- **RNF-004.** Sin campos públicos nuevos ni cambios en la proyección pública (DA-1).
- **RNF-005.** Los textos nuevos están en ES y EN. Las descargas se pueden usar con teclado y pasan axe en ambos temas.

## Datos personales y privacidad

- Las plantillas y las actas llevan nombres de jugadores, que ya ven los miembros en el Workspace. Nunca llevan documento ni fecha de nacimiento (principio 5, §3.4).
- Los oficiales del acta aparecen por nombre y función, sin su correo.
- Un archivo descargado sale del control del sistema. Por eso la exportación de plantillas se limita a lo imprescindible, sin edad, y cada descarga queda auditada (DA-3).

## Casos límite

1. Un torneo sin partidos o sin clasificación calculada produce un archivo solo con la cabecera.
2. Un partido rectificado exporta la última versión publicada del acta, no la original.
3. Un partido cerrado por W.O. exporta el resultado del W.O. y su motivo, sin hechos.
4. Un jugador retirado de la plantilla aparece con su estado.
5. Un nombre con comas, comillas o saltos de línea se escapa correctamente.
6. Un torneo archivado se puede seguir exportando.
7. Un partido suspendido o en vivo aparece en el calendario con su estado y sin marcador.

## Fuera de alcance

- Exportaciones programadas, por correo o por webhook.
- Exportar la auditoría, las sanciones o los expedientes de la 034.
- Importar desde estos archivos.
- Exportaciones de varios torneos a la vez o de la organización completa.
- Plantillas con documento, fecha de nacimiento, edad o foto.
- PDF o vista imprimible (DA-2) y descargas en la vista pública (DA-1).
- Un archivo de hechos de todo el torneo (DA-4).

## Criterios de finalización

| # | Criterio | RF |
|---|---|---|
| 1 | Las cinco exportaciones, con columnas fijas y documentadas. | RF-001, RF-002 |
| 2 | CSV en UTF-8, con escape correcto y fórmulas neutralizadas. | RF-003, RNF-001, RNF-002 |
| 3 | Nada fuera de lo que el miembro ya ve; sin documento, fecha de nacimiento, correo ni foto. | RF-004 |
| 4 | Mismo error para torneo ajeno o inexistente; aislamiento por RLS. | RF-005, RF-008 |
| 5 | Acta solo de partidos cerrados, en su versión vigente. | RF-001, RF-006 |
| 6 | Límite de 10.000 filas sin truncar. | RNF-003 |
| 7 | Cada descarga de plantillas queda en la auditoría organizacional, sin nombres. | RF-007 |
| 8 | ES/EN, teclado y axe en ambos temas. | RNF-005 |

## Dudas abiertas

Ninguna.
