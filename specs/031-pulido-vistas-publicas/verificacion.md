# Verificación y cierre de 031 — 2026-11-11

PR A: [#50](https://github.com/edsel9ra/bracket-craft/pull/50). PR B: [#51](https://github.com/edsel9ra/bracket-craft/pull/51), incluido el arreglo de la pista a 800 px. PR C: [#52](https://github.com/edsel9ra/bracket-craft/pull/52), rama `devin/1794419368-spec-031-verificacion-cierre`, desde `origin/main` `081ad060`. Validación cerrada y aprobada por el usuario el 2026-11-11: «Lo apruebo, procede con la task 10. Me encargo de fusionar.» T1–T10 completas; la fusión corresponde al usuario, no al agente.

CI del PR #52 sobre cc6c9404: **7 passed, 0 failed, 0 pending, 0 skipped**. El [job E2E](https://github.com/edsel9ra/bracket-craft/actions/runs/43076141163/job/130716366488) ejecutó y pasó las 21 pruebas públicas nuevas (7 por cada viewport 1440/390/800), dentro de `26 passed (3.1m)`, sin omisiones.

## Evidencia reproducible

- `frontend/e2e/public-polish.spec.ts`: 21 tests anónimos, sin storageState autenticado ni trazas, a 1440×900, 390×844 y 800×900. Se ejecutan en el proyecto `public` existente, conservando `realtime-public.spec.ts`. No añade dependencias ni modifica escenarios anteriores.
- `publicPolishFixtures.ts`: respuestas públicas ficticias tipadas, sin escrituras. Navegación cliente desde la portada ya hidratada: la intercepción se aplica a las peticiones que realmente hace el navegador, no se pretende interceptar el fetch SSR. Normal, vacío, 503 y recuperación; 53 filas en cada tabla, empates 1/1/3, continuación 50→53, carga bloqueada hasta liberar la respuesta, filtros reversibles, nombres largos, foto ausente/fallida y una formación publicada por segmento, no la del rival.
- `publicPolishChecks.ts`: mide las columnas iniciales, región/foco/flechas, identidad sticky al extremo, geometría, colisiones y overflow. Deduce independientemente los pares por IDs/ganador/unicidad, sin importar el algoritmo de la app. Espera dos frames para medir después del trabajo de ResizeObserver; conserva el umbral de 2 px.
- TDD: `031-c-t9-red.log` registra ENOENT antes de crear el arnés/configurarlo; el test guardián nuevo impide omitir el arnés o sustituir realtime. Ningún test existente debilitado.
- Evidencia fuera de Git, raíz `/home/ubuntu/ui-audit/`: `031-after/views/{measurements,contracts}.json`, `031-after/brackets/measurements.json`, `031-after/penales-simulados.json`; scripts `031-c-{views,brackets,penalties}.py`, fixture `031-fixtures.py`, cierre W.O. `031-c-first-outcome.py` y `031-a-more-outcomes.py`. Datos creados por API y retirados por IDs acotados; manifiestos conservados fuera de Git para trazabilidad, no credenciales.
- Composiciones etiquetadas desde `031-before/`, revisadas visualmente: `031-c-pr/jugadores-mobile.png` (recorte inicial equivalente), `clasificacion-mobile.png`, `bracket-16-desktop.png`. Las respuestas y resultados no son idénticos entre el cuadro inicial pendiente y el actual con W.O.: se etiqueta esta diferencia, no se atribuye al CSS.

## RF por RF

| RF | Evidencia |
|---|---|
| 001 | Matriz real: mismas seis lecturas, parámetros y campos; rank/orden de ambas estadísticas iguales a la referencia B. Contextos públicos sin sesión; ninguna escritura del nuevo E2E. |
| 002 | Acceso portada Y=602,89/487,99/503,52 px (desktop/móvil/800); ancla enfocada por el E2E. |
| 003 | «Marcador de ejemplo», DOM y captura reales; aserción persistente. |
| 004 | Accesos detalle Y=498,36/332,25/329,40; selector 585,86/504,06/416,90. 53 equipos ficticios siguen consultables. |
| 005 | Cada cuadro conserva exactamente los IDs, número y orden de sus partidos; pendientes y placeholders, sin duplicados. |
| 006 | Rondas reales Octavos/Cuartos/Semifinales/Final; fallback y ES/EN en `tests/public-bracket.test.ts`, sin deducir la final por página. |
| 007 | 15 mediciones reales, cinco cuadros × tres tamaños: todas Y=0 px, sin solapes. Tests sintéticos de 4/8/16/5 y colisión unitaria en `public-bracket-layout.test.ts`. |
| 008 | Pares dibujados=deducibles; cero líneas falsas. E2E de ganadores repetidos/destino ambiguo no dibuja los pares afectados; pendientes sin ganador no se conectan. |
| 009 | Cinco equipos reales: cuatro partidos, tres byes generados por el producto; no se crean partidos, W.O. ni conexiones para los byes. |
| 010 | Ganador accesible además del color, aserción «Ganador»; pendientes con guion, sin 0–0 inventado. |
| 011 | W.O. reales 3–0. Penales **simulados**, 1–1 y 5–4: tres auditorías axe y fixture persistente; no se declara cierre real del backend ni se publica motivo privado. |
| 012 | Scroll local del diagrama y flecha de teclado hasta otras rondas, nombre por columna, pista cuando desborda; documento sin overflow. |
| 013 | Torneo completo inicial; Liga, Eliminatoria sin filas, restauración y recuperación en ambas tablas, con petición de fase registrada. |
| 014 | Rank/empates/orden real sin cambios; E2E conserva el vector completo 1/1/3…53 al continuar, sin reordenar el fragmento. Criterios visibles en las tablas. |
| 015 | Móvil: tres cabeceras completas Posición/Jugador/Goles y Posición/Equipos/GF; todas las métricas siguen en el scroll; identidad sticky. Nombre completo accesible en el marcado, protegido por tests existentes. |
| 016 | «50 filas mostradas»→«53 filas mostradas»; botón deshabilitado mientras la respuesta está retenida; vacío, 503 y recuperación, ambas estadísticas. |
| 017 | Clasificación y estadísticas: región nombrada enfocada, flechas, pista según overflow real (incluido 800), identidad sticky a ≤1 px del borde al desplazar. Axe `scrollable-region-focusable`=0. |
| 018 | Clasificación/partidos reales a tres tamaños, cero overflow; nombres largos, marcador/fecha/estado/resolución preservados por fixture y captura. |
| 019 | Formación gráfica y equivalente textual reales, tres tamaños; E2E de un solo equipo publicado, segmento 2, diálogo dentro del viewport, Escape y retorno al disparador. |

## Medidas y accesibilidad

| Cuadro real | Partidos | Conectores dibujados/deducibles por tamaño | Y máxima |
|---|---:|---:|---:|
| Demo 8 | 7 | 4/4 | 0 px |
| Temporal 4 | 3 | 2/2 | 0 px |
| Temporal 8 | 7 | 2/2 | 0 px |
| Temporal 16 | 15 | 4/4 | 0 px |
| Temporal 5 | 4 | 2/2 | 0 px |

42/42 líneas en total; cero falsas, solapes, overflow de documento y errores de página en las 15 mediciones. Las relaciones privadas locales se leen únicamente por el auditor para contrastar los pares, nunca desde la app ni como datos del gráfico.

Axe-core 4.10.3, sin excluir reglas ni nodos de la aplicación: **30 vistas reales + 15 cuadros reales + 3 penales simulados = 48 ejecuciones, cero violaciones**, incluido `scrollable-region-focusable`. Las diez superficies por tamaño son portada, detalle, bracket, jugadores, equipos, fase, formación gráfica, formación textual, clasificación y partidos. DevTools no forma parte de la aplicación auditada. RNF-001/002/003: contrato intacto y cero overflow. RNF-004/005/006: tokens/contrastes sin cambios de app, tests de escalas y accesibilidad conservados, teclado y documentación actualizada.

## Criterios de finalización

1. Spec, plan y tareas aprobados por el usuario antes de implementar; D1–D4 conservadas; PR #50/#51 fusionados.
2. Before/after de todas las superficies, anchos/columnas/Y y overflow en los JSON indicados, composiciones en `031-c-pr/`; 800 px añade regresión al breakpoint original.
3. Relaciones contrastadas con una deducción independiente y contra los fixtures locales; fallback ambiguo/pendiente probado, sin ampliar datos públicos.
4. Cuadros 4/8/16/5 reales; byes, W.O. y pendientes reales; penales simulados expresamente, sin pretender verificar un cierre deportivo real.
5. Filtros, rank, empates, orden, continuación y sticky protegidos por el E2E, datos reales y tests unitarios conservados.
6. Cero axe, teclado/Escape/retorno y equivalente textual. No se ha usado lector de pantalla ni dispositivos físicos; no se certifican combinaciones arbitrarias de navegador/zoom/colisión.
7. Contrato real sin cambios y gates locales verdes. CI del PR #52 verde, incluidas las 21 pruebas públicas nuevas; revisión y cierre de validación aprobados por el usuario el 2026-11-11. El usuario se encarga de fusionar.

## Constitución §4

| Criterio obligatorio | Resultado/evidencia |
|---|---|
| CI correspondiente | PR #52 sobre cc6c9404: 7 passed, 0 failed, 0 pending, 0 skipped. [E2E de CI](https://github.com/edsel9ra/bracket-craft/actions/runs/43076141163/job/130716366488): 26 passed (3.1m), incluidas las 21 públicas nuevas. Revisión aprobada por el usuario el 2026-11-11. |
| Sin secretos/credenciales/datos personales nuevos | Solo fixtures ficticios y geometría en los tests; storageState vacío, trazas desactivadas, no se adjuntan cabeceras/cookies ni contexto autenticado. Capturas fuera de Git. |
| Documentación observable | Spec/tareas/memoria, AGENTS y accesibilidad; manual sin cambios porque A/B ya documentan la interfaz y C no la cambia. |
| Pruebas del comportamiento | Guardián nuevo + 21 E2E; realtime y operation-flow conservados. |
| BD: migración/RLS/volúmenes/`sh -n` | No aplica: no hay cambios de esquema, migraciones ni scripts de migración. Fixtures locales retirados por IDs, con comprobación de identidad. |
| Backend/API: contexto RLS, privacidad, router, pytest/compileall | No aplica al diff: no cambia backend, contratos ni rutas. Auditoría de proyecciones públicas real y tipos vigentes, sin afirmar una nueva ejecución de pytest. |
| Frontend: HTTP exclusivo `useApi.ts` | Sin cambios de aplicación ni transporte; el interceptor de Playwright es código de prueba, no otra vía HTTP de la app. |
| Frontend: test/typecheck/build | Ver salidas; lint y typecheck:e2e también verdes. |
| Infra/deploy: compose/producción | No aplica al diff: no cambia infraestructura ni despliegue. Stack Docker local existente, configuración externa de Chromium sin editar el repo. |
| Dependencias: locks/auditorías | No aplica: ningún manifiesto/lock ni dependencia nueva. Se conserva el gate security de CI. |

## Gates locales y limpieza

Node 24.22.2, pnpm 12.12.1. Desde `frontend/`: `pnpm test`, `pnpm run typecheck`, `pnpm run lint`, `pnpm run build`, `pnpm run typecheck:e2e`; todos exit 0. Node 24 ejecutado mediante el contenedor de desarrollo con el volumen node_modules existente; no se cambió configuración compartida.

```text
ℹ tests 873
ℹ pass 871
ℹ fail 0
ℹ skipped 2
◆ ✨ Build complete in 12.6s!
$ tsc -p e2e/tsconfig.json
21 passed (35.4s)
2 passed (47.1s)
```

E2E público: `pnpm exec playwright test e2e/public-polish.spec.ts --project public --no-deps`. E2E operación: `pnpm exec playwright test --project operation-flow`. Localmente ambos añaden `--config /home/ubuntu/ui-audit/031-a-playwright.config.mts` para seleccionar Chromium ya instalado; la configuración externa importa la del repo. Logs `031-c-{gates,t9-final,operation-flow,final-tests,e2e-types-final}.log` en ui-audit. Las mediciones E2E se escriben como JSON en el outputPath de cada test y se adjuntan, sin sesiones ni trazas; 18 registros conservados también en `031-after/anonymous-e2e-measurements.json`.

Limpieza: cuatro torneos de medición/33 equipos y un torneo operation-flow/2 equipos/2 jugadores retirados; contadores de torneos/equipos/partidos/slots y jugadores temporales cero en `031-c-cleanup.log`. Las respuestas sintéticas del E2E nunca se insertaron en la BD. Demo y fixtures anteriores conservados.
