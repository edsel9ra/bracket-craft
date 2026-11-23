# Spec 043 — Compartir y SEO (F14)

Estado: borrador; pendiente de clarificación (DA-1–DA-4) y de aprobación del usuario.

## Contexto y objetivo

Las specs 020–022 dejaron fuera la optimización para buscadores y la vista previa al compartir en redes. Hoy:

- La página de inicio publica título, descripción y tipo OpenGraph, sin imagen.
- La página pública de torneo publica título y descripción, sin OpenGraph ni imagen.
- La ficha pública de jugador (038) solo publica título.
- No hay sitemap ni `robots.txt`; las páginas privadas se excluyen una a una con `noindex`.
- No hay forma de compartir un torneo o un resultado desde la vista pública salvo copiar la URL del navegador.

F14 hace que los torneos públicos se encuentren en buscadores y que, al compartir un enlace, la vista previa muestre información útil y correcta, sin publicar nada que no sea ya público.

Relación con la constitución: §5 (lo público es una proyección mínima: sin documentos, fechas de nacimiento ni fotos sin consentimiento), §2 (aislamiento por organización; solo torneos y versiones publicadas), accesibilidad e i18n ES/EN.

## Usuarios

- Público anónimo que comparte o abre un enlace de un torneo, un resultado o una ficha.
- Buscadores y servicios de vista previa (redes sociales, mensajería).
- Organizadores que difunden su torneo.

## Roles y visibilidad

- **Público y robots:** solo ven lo que ya expone la consulta pública (torneos visibles, versiones publicadas, partidos públicos, fichas autorizadas).
- **Workspace, administración, autenticación e invitaciones:** nunca indexables ni en el sitemap.

## Requisitos funcionales

- **RF-001 Metadatos de torneo.** La página pública de un torneo visible publica título, descripción, URL canónica, tipo, imagen y su texto alternativo para OpenGraph y tarjeta grande de X/Twitter, generados en el servidor (visibles sin ejecutar JavaScript).
- **RF-002 Metadatos de inicio.** La página de inicio añade URL canónica, imagen y tarjeta X/Twitter a los metadatos actuales.
- **RF-003 Imagen de vista previa de torneo.** Según DA-1.
- **RF-004 Imagen de resultado.** Según DA-1 y DA-2: un partido finalizado y público puede compartirse con una vista previa que muestra los equipos y el marcador final vigente (incluida una rectificación aplicada). Un partido suspendido, no jugado o no público nunca genera imagen de resultado.
- **RF-005 Enlace directo a un partido.** Según DA-2.
- **RF-006 Fichas de jugador.** Según DA-3.
- **RF-007 Sitemap.** Un sitemap XML lista las URL públicas indexables según DA-4, con fecha de última modificación cuando exista. Se actualiza sin despliegue al publicar u ocultar torneos.
- **RF-008 `robots.txt`.** Permite las páginas públicas, bloquea Workspace, administración, autenticación, cuenta e invitaciones, y anuncia el sitemap.
- **RF-009 Botón «Compartir».** Las páginas públicas de torneo (y de partido y ficha si quedan incluidas) ofrecen «Compartir»: usa la hoja nativa del dispositivo si existe y, si no, copia el enlace y lo confirma de forma accesible. ES/EN, teclado y lector de pantalla.
- **RF-010 Sin datos nuevos.** Metadatos, imágenes y sitemap solo usan campos que ya devuelve la consulta pública. Torneo inexistente, oculto o de versión no publicada: el mismo 404 de hoy, sin imagen ni entrada en el sitemap.
- **RF-011 URLs absolutas.** Las URL canónicas, de imagen y del sitemap son absolutas y se basan en un origen público configurado por despliegue, no en la cabecera `Host` de la petición.
- **RF-012 Idioma.** Los metadatos usan el idioma de la página servida; el texto generado no depende de datos privados.

## Requisitos no funcionales

- **RNF-001 Rendimiento.** Las imágenes y el sitemap se cachean con un tiempo acotado y no añaden consultas por cada visita de usuario a la página pública.
- **RNF-002 Robustez.** Si la imagen dinámica falla, la vista previa usa la imagen genérica de marca; nunca rompe la página.
- **RNF-003 Seguridad.** Las rutas nuevas son de solo lectura, respetan el límite de tasa público del proxy y no aceptan texto libre que se dibuje en la imagen.
- **RNF-004 Accesibilidad e i18n.** Imágenes con texto alternativo, contraste suficiente, ES/EN.
- **RNF-005 Pruebas.** Pruebas de metadatos SSR, contenido del sitemap y `robots.txt`, exclusión de lo no público y ausencia de campos privados en imágenes y metadatos.

## Fuera de alcance

- Datos estructurados schema.org, AMP, analítica o seguimiento de clics.
- Indexar páginas privadas o borradores.
- Publicar en redes sociales en nombre del organizador.
- Imágenes de alineación o de estadísticas.

## Dudas abiertas

- **DA-1 Imagen de vista previa.** (a) Generada en el servidor: una por torneo (nombre, temporada y estado) y una por resultado final (equipos y marcador), solo texto y colores de marca; (b) solo una imagen fija de marca para todo; (c) generada solo para torneos.
- **DA-2 Enlace directo a un partido.** (a) Sí: un enlace al torneo que abre la cronología del partido finalizado y lleva la vista previa del resultado; (b) no: solo se comparte el torneo.
- **DA-3 Fichas de jugador.** (a) Compartibles con nombre y torneo en la vista previa, sin foto, fuera del sitemap y con `noindex`; (b) indexables y en el sitemap, sin foto; (c) indexables y con foto si hay consentimiento.
- **DA-4 Contenido del sitemap.** (a) Inicio y todos los torneos públicos visibles, sin parámetros de fase o grupo; (b) solo torneos en curso o finalizados en los últimos 12 meses.

## Criterios de aceptación

1. Una petición sin JavaScript a un torneo público devuelve OpenGraph y tarjeta X/Twitter completos con URL absolutas.
2. Un torneo oculto o inexistente devuelve 404, no tiene imagen y no aparece en el sitemap.
3. El sitemap y `robots.txt` cumplen RF-007 y RF-008.
4. Ninguna imagen ni metadato contiene documentos, fechas de nacimiento, fotos sin consentimiento ni datos de partidos suspendidos.
5. «Compartir» funciona con hoja nativa y con copia del enlace, con teclado y anuncio accesible, en ES/EN.
6. Pruebas, typecheck, lint, build y CI en verde; README, AGENTS, manual e informe actualizados.
