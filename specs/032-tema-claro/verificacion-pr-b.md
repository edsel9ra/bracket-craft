# Verificación local PR B — 032, T4–T6

Fecha: 2026-11-11. Rama `devin/1794426037-spec-032-selector-superficies`.
Base de comparación: `origin/main` `53a7ef06f8ad80ec461281a612c07ddf4d248cea`.
Registro histórico de PR B, limitado a T4–T6. T7–T10 y la aceptación global se cerraron posteriormente con #55 fusionado, CI verde y aprobación del usuario el 2026-11-12: [verificación final](verificacion.md).

## Implementación y TDD

- `ThemeSwitcher`: select nativo, etiqueta/ES/EN, `useId`, únicamente `useTheme`/`setTheme`; sin navegación, fetch ni almacenamiento propio.
- `PublicPreferences` mantiene el idioma flotante original y busca un espacio libre frente a texto/controles, apilando hacia arriba. Medidas compactas de desktop/tableta conservan la R congelada; móvil conserva el tamaño mayor. Actualiza tras fuentes, resize, scroll, mutaciones, hover y fin de movimiento; limpia observadores/listeners.
- Workspace permite reordenar solo la fila de preferencias y el menú móvil abierto. IDs de idioma desktop/móvil distintos, etiquetas recuperadas en el menú.
- Disabled claros opacos por consumidor, nunca globalmente. Backdrops claros con una sola capa alfa. Iniciales ya usaban `avatar-ink`; tests protegen ese rol y fotos/URLs sin recolorear.
- Solo `.pitch` remapea tinta/acento/aviso y superficies de jugadores en claro/Sistema-claro. Visitante claro `#ffd18a`; oscuro, geometría, nombres, segmentos y SVG/currentColor no cambian.
- Rojos previos conservados en `t4-compact-red.log`, `tablet-red.log`, `t5-red.log`, `t6-red.log`, `scoped-red.log`; verdes focales y suite completa posteriores. Axe detectó durante el desarrollo que un prefijo `:global(:root(...))` eliminaba el selector descendiente al compilar Vue. Se corrigió con scopes locales y regresiones sobre CSS **compilado**, no solo regex del fuente.

## R congeladas, sin tolerancias ni ampliaciones

Manifiesto previo al diff: `/home/ubuntu/ui-audit/032-b-pr/after-t4-final/manifest.json`.
SHA-256: `8c94661c86fdde52c362c334a4c1fdc84d6f4fe22c93416a664b63fe8cda3657`.
Coordenadas CSS `(x, y, ancho, alto)`, redondeadas aquí a dos decimales; el JSON es autoritativo. El comparador redondea hacia fuera a píxeles enteros, sin halo adicional.

| Vista | 1440×900 | 390×844 | 800×900 |
| --- | --- | --- | --- |
| Portada | (1103.33, 839, 301.67, 41) | (221.05, 702, 141.95, 130) | (613.28, 790, 151.72, 90) |
| Detalle | (1253.28, 790, 151.72, 90) | (221.05, 702, 141.95, 130) | (613.28, 658, 151.72, 222) |
| Workspace/operación | (472.55, 18.50, 829.95, 33) | Cerrado: vacía | (334.05, 18.50, 430.95, 33) |
| Menú móvil abierto | — | (0, 62, 375, 260.50) | — |

Las cajas reales del nuevo control pueden ser menores, nunca se amplió la máscara. En portada a 800, el control completo de 41 px obligaba a subir 12 px para no cubrir una tarjeta/enlace cuyo borde está en `y=820.015625`; el control compacto de tableta cabe dentro de la R original. En desktop, el control centrado compacto evita el borde de tarjeta en `y=876.890625`. `tablet-obstacle.json` y tests geométricos reproducen las colisiones; no se ignoraron controles ni se derivó R del diff.

## Controles y estabilización

Se conservaron todos los intentos fallidos. Primer mapa (`map-before-after-t4-final.json`):

| Caso | Píxeles fuera | Delta máximo por canal | Distancia a R | Dentro de 8 / 32 px de R |
| --- | ---: | ---: | --- | --- |
| Portada 1440 | 1699 | 10 | 1–1247.18 px | 9 / 21 |
| Portada 390 | 297 | 3 | 2–701 px | 2 / 4 |
| Workspace 390 | 237 | 1 | R vacía | No aplica |

1666/1699, 294/297 y 237/237 tenían delta 1. No estaban concentrados junto al flotante: los bounding boxes fueron `(0,0)-(1425,900)`, `(0,1)-(375,764)` y `(22,351)-(359,835)`. Coincidían con zonas de fondos/degradados; 371, 203 y 147 píxeles estaban a ±1 px de una cuadrícula de 256 px. Es correlación, **no prueba** de un mecanismo de rasterización. Workspace cerrado no monta el flotante público (`app.vue`) y su mapa queda bajo la cabecera sticky: un único backdrop público no explica los tres casos. Las pruebas de hover tampoco explican por sí solas la colisión estable sin hover (`hover-cause.json`).

El arnés espera hidratación, `document.fonts.ready`, scroll cero, puntero `(0,0)`, desactiva movimiento/caret y espera dos rAF. Para eliminar historia de resize/composición compartida, la pasada final usa un proceso Chrome nuevo por caso, software y perfil sRGB. Se conservó el factor nativo **2** del navegador original y el DPR emulado **1**: un ensayo con factor nativo 1 cambió las métricas de selects y fue descartado, sin cambiar R.

Motor: Chrome `156.0.8078.47`, Linux; flags y ejecutable en `software-{main,final}/engine.json`. No se sustituyeron colores, degradados, fotos ni reglas de contraste para obtener el resultado.

Controles finales: tres capturas por caso de portada 1440, portada 390 y Workspace 390, tanto main como rama; todas las combinaciones por tripleta. Se comprobó también RGBA **completo**, sin máscara:

```text
Full RGBA controls: 18 comparisons; 0 changed pixels; maxDelta 0
```

Evidencia: `software-main-control/`, `software-branch-control/`, `controls-full-rgba.json`.
Cruce final: `software-main/`, `software-final/rgba.json`, `software-final-rgba.log`:

```text
RGBA outside R: 0 pixels across 14 pairs
```

Incluye los ocho pares requeridos 1440/390, ambos menús móviles abiertos y cuatro casos adicionales de tableta. Workspace/operación móvil cerrado son idénticos en la imagen completa. Fuera de R, delta máximo final 0 y ningún agrupamiento residual. El último ajuste de límites media a los pasos 480/1280 de la escala no modifica los estilos efectivos de los fixtures 390/800/1440.

## Selector, SSR y primer pintado

`selector-final.log`/`selector.json`: Home/ArrowDown/End/Tab, foco conservado, cookie anual Lax/Path `/`, sin nuevas peticiones API al cambiar, sin sustituir encabezado; persistencia/SSR, ES/EN, Sistema y sus medias. Doce combinaciones público/Workspace × ES/EN × 1440/390/800 sin solapes de texto ni controles y con IDs únicos.

`first-paint.json`/`first-paint.log`: cookie creada por el selector, recarga con scripts de hidratación retenidos; 30 muestras iniciales rAF mantienen claro, ninguna oscura. Tras liberar scripts, formulario/foco/scroll se conservan; un cambio de media con Sistema no sustituye ni cierra el modal ni mueve su foco/scroll. Escape devuelve el foco al lanzador.

```text
30 initial rAF samples: light; hydration held; form/focus/scroll and System open-modal state preserved
HTTP/1.1 200 OK
<html  lang="es" data-theme="light">
<meta name="theme-color" content="#f5f7ef">
Set-Cookie: []
```

Esto no sustituye el E2E formal integrado/concurrente y la matriz completa de primer pintado de T8.

## Visual y axe

`surfaces-final/results.json`: 66 ejecuciones axe, 0 grupos de violaciones, sin reglas/nodos de aplicación excluidos y sin errores de página. Claro/oscuro, 1440/390; portada, detalle/bracket, clasificación, estadísticas, formación/modal, Workspace, menú móvil, miembros, reglas/asistentes publicados, calendario, plantillas, operación programada/en vivo/cerrada y acceso. Dos verificaciones adicionales de portada a 800 px (ambos temas) también dan cero en `tablet-axe.json`; control compacto revisado en `tablet-light.png`. Composiciones revisadas en `composition-public.png`, `composition-workspace.png`, `composition-secondary.png`, `composition-mobile.png`; originales en `surfaces-final/`.

**Límites reales:** `/admin` redirige a forbidden con el dueño demo (no es administrador global); `/organization` redirige al Workspace por tener organización activa. Esas ocho ejecuciones no certifican los formularios destino. Sus scopes se revisaron por fuente/CSS compilado; render con roles/estados adecuados queda para T9. No se cambiaron permisos ni se creó una cuenta para simularlo. No se certifican lectores de pantalla, otros motores ni dispositivos físicos.

## Gates y limpieza

Logs bajo `/home/ubuntu/ui-audit/032-b-pr/`, sufijo `final4` para los cinco gates frontend:

```text
ℹ tests 898
ℹ pass 897
ℹ fail 0
ℹ skipped 1
$ nuxt prepare && vue-tsc --noEmit
◆ Types generated in .nuxt.
$ nuxt prepare && eslint .
◆ Types generated in .nuxt.
◆ ✨ Build complete in 11.9s!
$ tsc -p e2e/tsconfig.json
```

Los cinco comandos terminaron con salida 0. El primer intento host de operation-flow no arrancó: faltaba `chromium_headless_shell-1248` en la caché. Se diagnosticó el entorno y se usó el equivalente documentado de CI, imagen local `mcr.microsoft.com/playwright:v1.64.1-noble`, red host y CLI existente de Playwright, sin instalar dependencias ni editar configuración. Primera ejecución efectiva: `2 passed (35.8s)`, en `operation-flow-container.log`; no se usó el artefacto viejo tras el fallo de arranque.

Tras el último ajuste CSS de tableta se ejecutó de nuevo con la fuente final (`operation-flow-final.log`):

```text
✓ prepara el idioma y la sesión del Workspace (1.8s)
✓ operación y cierre: reglas, avisos, bloqueos y retiro lógico (39.0s)
2 passed (42.2s)
```

Se retiraron por sus UUID solo los dos fixtures de estas ejecuciones, con sus dos equipos/dos jugadores cada uno; comprobaciones `0 | 0 | 0` en `cleanup-fixture.log` y `cleanup-fixture-final.log`. Los fixtures anteriores ajenos a esta corrida se conservaron. Cookies, cabeceras y storageState no forman parte de la entrega Git.
