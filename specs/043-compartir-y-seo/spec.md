# Spec 043 — Compartir y SEO (F14)

Estado: borrador; DA-1–DA-4 resueltas el 2026-11-23; pendiente de aprobación del usuario.

## Decisiones del usuario (2026-11-23)

- **DA-1 = (a).** Imagen de vista previa generada en el servidor: una por torneo (nombre, temporada y estado) y una por resultado final (equipos y marcador). Solo texto y colores de marca.
- **DA-2 = (a).** Un partido finalizado se puede compartir: el enlace abre su cronología en la página del torneo y la vista previa muestra el resultado.
- **DA-3 = (a).** Las fichas de jugador se pueden compartir con nombre y torneo en la vista previa, sin foto; no aparecen en buscadores ni en el sitemap.
- **DA-4 = (a).** El sitemap incluye la página de inicio y todos los torneos públicos visibles.

## Contexto y objetivo

Las specs 020–022 dejaron fuera la optimización para buscadores y la vista previa al compartir. Hoy:

- La página de inicio publica título, descripción y tipo OpenGraph, sin imagen ni URL canónica.
- La página pública de torneo publica título y descripción, sin OpenGraph ni imagen.
- La ficha pública de jugador (038) solo publica título y es indexable.
- No hay sitemap ni `robots.txt`; las páginas privadas se excluyen una a una con `noindex`.
- Para compartir un torneo o un resultado hay que copiar la URL del navegador, y no existe un enlace que abra un partido concreto.

F14 hace que los torneos públicos se encuentren en buscadores y que, al compartir un enlace, la vista previa muestre información útil y correcta, sin publicar nada que no sea ya público.

Relación con la constitución: §5 (lo público es una proyección mínima: sin documentos, fechas de nacimiento ni fotos sin consentimiento), §2 (aislamiento por organización; solo torneos visibles y versiones publicadas), accesibilidad e i18n ES/EN.

## Usuarios

- Público anónimo que comparte o abre un enlace de un torneo, un resultado o una ficha.
- Buscadores y servicios de vista previa de redes sociales y mensajería.
- Organizadores que difunden su torneo.

## Roles y visibilidad

- **Público, buscadores y servicios de vista previa:** solo acceden a lo que ya expone la consulta pública (torneos visibles, versiones publicadas, partidos públicos, fichas autorizadas). Sin cambios de permisos.
- **Miembro y administrador de organización:** sin cambios; el Workspace sigue siendo privado y nunca indexable.
- **Administrador de plataforma:** sin cambios; la administración nunca es indexable.

## Historias de usuario

- HU-1. Como aficionado, quiero compartir un torneo y que la vista previa muestre su nombre, temporada y estado, para que otros lo reconozcan antes de abrirlo.
- HU-2. Como aficionado, quiero compartir el resultado final de un partido y que el enlace abra su cronología, para mostrar qué pasó.
- HU-3. Como organizador, quiero que los torneos públicos aparezcan en buscadores, para difundirlos sin esfuerzo adicional.
- HU-4. Como jugador, quiero que mi ficha se pueda compartir sin que aparezca en buscadores ni muestre mi foto en la vista previa, para controlar mi exposición.

## Definiciones

- **Vista previa:** tarjeta que muestran redes y mensajería al pegar un enlace, construida con los metadatos OpenGraph y de X/Twitter de la página.
- **Torneo público visible:** torneo que hoy devuelve la consulta pública de torneos; uno oculto, inexistente o sin versión publicada no lo es.
- **Resultado final compartible:** partido público de un torneo visible, en estado finalizado, con ambos equipos definidos. Un partido suspendido, programado, en juego o no jugado no lo es.
- **Origen público:** dirección base del sitio público configurada por despliegue (esquema y dominio).

## Requisitos funcionales

- **RF-001.** CUANDO se solicita la página pública de un torneo visible, EL SISTEMA responde, ya en el HTML inicial y sin ejecutar JavaScript, con título, descripción, URL canónica, tipo, imagen de vista previa, dimensiones y texto alternativo de la imagen para OpenGraph, y tarjeta grande de X/Twitter.
- **RF-002.** CUANDO se solicita la página de inicio, EL SISTEMA añade a los metadatos actuales la URL canónica, una imagen de marca con texto alternativo y la tarjeta de X/Twitter.
- **RF-003.** EL SISTEMA genera para cada torneo visible una imagen de vista previa con el nombre, la temporada y el estado del torneo, solo con texto y colores de marca, sin escudos, fotos ni otros datos.
- **RF-004.** EL SISTEMA genera para cada resultado final compartible una imagen con los nombres de ambos equipos, el marcador final vigente (incluida una rectificación aplicada y, si existe, la tanda de penaltis) y el nombre del torneo, solo con texto y colores de marca.
- **RF-005.** SI se solicita la imagen de un torneo que no es visible, o de un partido que no es un resultado final compartible, ENTONCES EL SISTEMA responde con el mismo «no encontrado» de la consulta pública y no genera imagen.
- **RF-006.** CUANDO se abre un enlace de partido de un torneo visible y el partido es un resultado final compartible, EL SISTEMA muestra la página del torneo con la cronología de ese partido abierta, y los metadatos de la página usan el resultado (título con equipos y marcador, imagen de RF-004 y URL canónica del enlace de partido).
- **RF-007.** SI el enlace de partido apunta a un partido inexistente, de otro torneo o que no es un resultado final compartible, ENTONCES EL SISTEMA muestra la página del torneo sin abrir ningún diálogo y con los metadatos del torneo, sin revelar si el partido existe.
- **RF-008.** CUANDO se solicita una ficha pública de jugador disponible, EL SISTEMA publica título, descripción con el nombre del jugador y su torneo más reciente de la ficha, la imagen de marca y la indicación de no indexar ni seguir; nunca usa la foto del jugador en la vista previa.
- **RF-009.** EL SISTEMA publica un sitemap XML con la página de inicio y una URL por cada torneo público visible, sin parámetros de fase, grupo ni partido, con su fecha de última modificación cuando exista; refleja la publicación u ocultación de torneos sin desplegar, dentro del tiempo de caché de RNF-001.
- **RF-010.** EL SISTEMA publica un `robots.txt` que permite las páginas públicas, bloquea Workspace, administración, autenticación, cuenta, organización, recuperación de contraseña e invitaciones, y anuncia el sitemap.
- **RF-011.** EL SISTEMA ofrece una acción «Compartir» en la página pública de torneo, en el diálogo de cronología de un resultado final compartible y en la ficha pública de jugador. CUANDO se activa, usa la hoja nativa del dispositivo si existe; SI no existe o falla, ENTONCES copia el enlace correspondiente y lo anuncia de forma accesible; SI la copia también falla, ENTONCES muestra el enlace para copiarlo manualmente.
- **RF-012.** EL SISTEMA construye todas las URL de metadatos, imágenes, sitemap y `robots.txt` como URL absolutas a partir del origen público configurado, nunca a partir de la cabecera `Host` de la petición.
- **RF-013.** EL SISTEMA solo usa en metadatos, imágenes y sitemap campos que ya devuelve la consulta pública; un torneo de una organización nunca aparece con datos de otra.
- **RF-014.** EL SISTEMA redacta los textos de metadatos e imágenes en el idioma de la página servida (ES/EN); los nombres propios se muestran tal cual.

## Requisitos no funcionales

- **RNF-001 Caché.** Imágenes, sitemap y `robots.txt` se sirven con caché pública de como máximo 10 minutos; un cambio de resultado, estado u ocultación se refleja en ese plazo.
- **RNF-002 Robustez.** Si la generación de una imagen falla, la imagen solicitada devuelve la imagen genérica de marca; la página pública nunca falla por ello.
- **RNF-003 Formato de imagen.** 1200×630 píxeles en un formato que acepten las principales redes; textos largos se recortan con puntos suspensivos sin salirse de la imagen; contraste de texto mínimo 4.5:1.
- **RNF-004 Seguridad.** Las rutas nuevas son de solo lectura, sin autenticación ni cookies, y quedan bajo el límite de tasa público del proxy; ningún parámetro de la petición se dibuja en la imagen.
- **RNF-005 Accesibilidad e i18n.** «Compartir» operable con teclado, con nombre accesible y anuncio del resultado; ES/EN en todo el texto nuevo; cumple el gate axe existente en ambos temas.
- **RNF-006 Pruebas.** Pruebas automáticas de metadatos en el HTML inicial, contenido de sitemap y `robots.txt`, exclusión de lo no público, enlace de partido y ausencia de campos privados.

## Datos personales y privacidad

- Datos involucrados: nombres de equipos, nombre de jugador en su ficha pública y nombre del torneo, todos ya públicos.
- Nunca se exponen documentos, fechas de nacimiento ni fotos en metadatos o imágenes; la foto del jugador queda fuera de la vista previa aunque tenga consentimiento.
- Las fichas de jugador no se indexan ni aparecen en el sitemap.
- Un partido suspendido no publica en la vista previa más de lo que ya publica hoy (no genera imagen de resultado).

## Casos límite

- Torneo ocultado tras compartirse: la página responde «no encontrado» y la imagen deja de servirse al expirar la caché.
- Resultado rectificado: la imagen muestra el marcador vigente al expirar la caché.
- Partido con victoria administrativa (walkover): se trata como resultado final con el marcador que hoy muestra la vista pública.
- Partido finalizado con un equipo sin definir: no es compartible.
- Nombres muy largos, con acentos o caracteres no latinos: se muestran recortados sin romper la imagen.
- Torneo sin fecha de última modificación conocida: aparece en el sitemap sin esa fecha.
- Origen público sin configurar en producción: el arranque lo detecta y falla, como otras variables obligatorias.

## Fuera de alcance

- Datos estructurados schema.org, AMP, analítica o seguimiento de clics.
- Indexar páginas privadas, borradores o fichas de jugador.
- Imágenes con escudos, fotos, alineaciones o estadísticas.
- Publicar en redes sociales en nombre del organizador.
- Enlaces compartibles para fases o grupos más allá de los parámetros de URL actuales.

## Criterios de finalización

1. Una petición sin JavaScript a un torneo público, a un enlace de partido compartible y a la página de inicio devuelve los metadatos de RF-001, RF-006 y RF-002 con URL absolutas.
2. Un torneo oculto o inexistente devuelve «no encontrado», no tiene imagen y no aparece en el sitemap; un partido no compartible no tiene imagen ni abre diálogo.
3. Sitemap y `robots.txt` cumplen RF-009 y RF-010; las fichas de jugador llevan `noindex` y no están en el sitemap.
4. Ninguna imagen ni metadato contiene documentos, fechas de nacimiento, fotos ni datos de partidos suspendidos.
5. «Compartir» funciona con hoja nativa, con copia del enlace y con copia manual, por teclado y con anuncio accesible, en ES/EN.
6. Tests, typecheck, lint, build y CI en verde; README, AGENTS, manual e informe actualizados.

## Dudas abiertas

Ninguna.
