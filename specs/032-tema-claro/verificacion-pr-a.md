# Verificación local de PR A — 032

2026-11-11. Registro histórico de PR A, limitado a T1–T3. T4–T10 se completaron posteriormente en B/C; spec implementada y cierre aprobado el 2026-11-12, con CI de #55 verde: [verificación final](verificacion.md). PR A no añadió selector ni cambios de API, permisos, campos públicos, dependencias o CSP. No se abrió PR en esta entrega.

## Base y TDD

- Rama `devin/1794422163-spec-032-tema-claro`; al comenzar estaba 2 commits delante y 0 detrás de origin/main, sin necesidad de merge/rebase.
- Base main `8993a393c4d64229bd5a16dce6d5157c37d4455c`; árbol frontend `5c33fbe3a53518179981910fa5bd3d1f797c40e7`.
- T1: módulo ausente → tres pruebas verdes. T2: themeContrast ausente → paletas/espejo/158 pares claros y 29 oscuros verdes; guardián incluye hsl/hsla sin nuevas exclusiones.
- T3: cuatro pruebas rojas por composable/integración ausentes → verdes, incluidos ausencia, inválida, aislamiento de solicitudes y bloqueo de escritura. El lector useCookie es readonly/sin default; solo setTheme escribe document.cookie de forma síncrona y atrapa excepciones. No almacenamiento alternativo.
- La comprobación real tras hidratar encontró metadatos duplicados: Unhead reconstruye las metas SSR sin la key personalizada. Se retiraron esas keys, manteniendo la deduplicación nativa por nombre/índice para theme-color; hay una meta explícita y dos con media para Sistema. Regresión de descriptor primero roja. Otro rojo protegió el fallback oscuro de todos los roles de isla en Sistema.

## RGBA oscuro sin cookie

Chrome 156.0.8078.47, DPR 1, ES/UTC, fuentes locales listas, mismo backend demo y sesión Workspace; sin escrituras concurrentes en las comparaciones finales. Runtime aislado en `/home/ubuntu/ui-audit/runtime/frontend`: todos los archivos app/config versionados se compararon byte a byte con main antes de instalar el candidato. Los módulos nuevos quedan sin uso en el root de main. Ningún archivo del checkout se revirtió para capturar.

Animaciones/transiciones se suprimen por igual en ambas mitades y se oculta únicamente DevTools, no controles de app. Sin selector, máscaras, tolerancia ni exclusiones de píxeles. Se decodifican los PNG a RGBA, se exige igual tamaño y se comparan todos los canales/píxeles.

| Vista | 1440×900 | 390×844 |
|---|---:|---:|
| Portada | 0 / 1.296.000 | 0 / 329.160 |
| Detalle | 0 / 1.296.000 | 0 / 329.160 |
| Workspace | 0 / 1.296.000 | 0 / 329.160 |
| Operación | 0 / 1.296.000 | 0 / 329.160 |

Manifiesto final con rutas originales y SHA-256: `/home/ubuntu/ui-audit/032-code/rgba-final.json`; referencias mayoritarias `032-a-baseline-clean/` y candidatos `032-a-candidate-clean/`. El manifiesto identifica las recapturas: detalle desktop `032-a-debug-main/` contra `032-a-debug-candidate/`, operación desktop contra `032-a-settled-operation/`. Diffs finales en `032-code/diff-final-*.png`.

**Límite reproducible:** no fue una única pasada perfectamente estable. Una referencia inicial dio 1.699 píxeles en portada; se retiraron los fixtures E2E y se repitió la escena quieta. La siguiente pasada dio 727/644 píxeles en detalle/operación desktop. Se añadieron dos rAF tras suprimir animaciones y se recapturaron esas superficies. El control main contra main también dio los mismos 727 píxeles frente a la referencia anterior, mientras el main nuevo coincidió exactamente con el candidato: la discrepancia de esa referencia no demuestra una regresión de app. Todos los pares finales dan cero, sin borrar los intentos ni relajar la comparación. El arnés definitivo y su estabilidad siguen siendo T7, no se declaran resueltos aquí.

## SSR, Sistema y referencia clara

`curl -sS -D headers -H 'Cookie: bc_locale=es; bc_theme=light' http://localhost:3000/`:

```text
HTTP/1.1 200 OK
<html  lang="es" data-theme="light">
<meta name="theme-color" content="#f5f7ef">
Set-Cookie: []
```

Inválida y ausencia entregan data-theme="dark" y theme-color #0c0f0c, sin Set-Cookie. Sistema entrega data-theme="system" y dos metas #0c0f0c/#f5f7ef con medias dark/light. Artefactos curl iniciales y finales en `032-code/`; la cookie de idioma existente se envía en la comprobación final para separar su escritura histórica de la de apariencia. Sin bc_locale el idioma conserva su Set-Cookie habitual; nunca se escribe/repara bc_theme por leer.

Seis contextos reales hidratados: sin preferencia/sistema claro → oscuro; light/sistema oscuro → claro; dark/sistema claro → oscuro; inválida → oscuro sin cambiar su valor; system en ambos medios → tema correspondiente y cambio reactivo al invertir el medio. Una/dos metas tras hidratar, cero errores de página. `browser-cases.json`.

Con JavaScript desactivado también se comprobaron light, system/claro, system/oscuro e inválida: color-scheme light/dark y rol de isla #ffd18a/#ffcb7a correctos, antes de depender de mounted. `no-javascript.json`.

Referencias revisadas: `032-code/light-reference-1440.png` y `032-a-candidate-clean/operacion-390.png`. Esta evidencia de PR A no certifica iniciales, disabled, velos, campo, primer pintado ralentizado ni selector: T5/T6/T9 se verificaron posteriormente en B/C, véase [verificación final](verificacion.md). No se certifican dispositivos físicos ni lectores de pantalla.

## Gates y limpieza

Node v24.22.2 / pnpm 12.12.1, desde frontend. Logs persistentes en `/home/ubuntu/ui-audit/032-code/`.

```text
pnpm test: tests 883; pass 882; fail 0; skipped 1
pnpm run typecheck: $ nuxt prepare && vue-tsc --noEmit; ◆ Types generated in .nuxt.
pnpm run lint: $ nuxt prepare && eslint .; ◆ Types generated in .nuxt.
pnpm run build: ◆ ✨ Build complete in 11.1s!
pnpm run typecheck:e2e: $ tsc -p e2e/tsconfig.json
operation-flow: 2 passed (42.6s)
```

Todos terminaron con salida 0. Operation-flow usó la configuración externa local `031-a-playwright.config.mts` para el Chromium instalado, sin cambiar configuración compartida. El primer typecheck encontró EACCES en artefactos ignorados .nuxt/.output propiedad de root; se restituyó su propietario local, sin tocar código/configuración para sortear el error.

Se retiraron exclusivamente los dos fixtures de estas ejecuciones, `7f0ae248-efe7-4c9f-80a2-7aba97abda2c` y `bb10e579-f139-4496-be5f-d29bff53740a`, con sus cuatro equipos/cuatro jugadores. Ambos logs `cleanup-0.log`/`cleanup-1.log` muestran `temporary_tournaments | temporary_teams | temporary_players = 0 | 0 | 0`. Demo y fixtures anteriores conservados. Sin CI de PR ejecutada en esta entrega.
