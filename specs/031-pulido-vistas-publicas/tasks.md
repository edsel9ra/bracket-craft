# Tareas 031 — Pulido de las vistas públicas

Fecha: 2026-11-11. Spec, plan y tareas aprobados por el usuario; fases de documentación cerradas. PR A (T1–T4) implementado con tests primero en rojo y comprobación antes de marcar cada casilla; PR B/C pendientes. Comandos desde la raíz con Node 24/pnpm 12.12.1. Evidencias y resultados de PR A al final; los comandos de las tareas pendientes siguen siendo propuestas, no resultados.

## PR A — Diagrama y lógica pura (T1–T4)

- [x] **T1. Inferencia conservadora de conexiones por ganador/participante y unicidad.** RF-005, RF-008–011; RNF-001. 25 min.
  - Hecho cuando: `publicBracket.ts` no muta entradas ni usa DOM/red/reloj; tests cubren regular, penales, W.O., ganador ausente/ajeno, participante null, duplicados, dos fuentes/destinos, rondas no consecutivas, byes, grupos/fases ajenos y datos parciales. Cero líneas ambiguas; orden API estable y todos los partidos conservados.
  - Comando: `cd frontend && node --test --experimental-strip-types tests/public-bracket.test.ts`.

- [x] **T2. Etiquetas de ronda con códigos actuales y fallback ES/EN.** RF-006; RNF-006. Depende de T1. 20 min.
  - Hecho cuando: FINAL, SF1/SF2, QF1–QF4 y R16-1–R16-8 producen las cuatro etiquetas aprobadas; null, mezcla, índices inválidos, R32 y última página incompleta no inventan nombres. «Ronda n»/genérico conserva fallback. Pruebas y traducciones presentes.
  - Comando: `cd frontend && node --test --experimental-strip-types tests/public-bracket.test.ts && pnpm run typecheck`.

- [x] **T3. Layout puro por medidas, promedio de orígenes y separación sin solapes.** RF-007, RF-012; RNF-003. Depende de T1. 25 min.
  - Hecho cuando: `publicBracketLayout.ts` recibe alturas/gap, centra con cero/uno/dos orígenes según plan, conserva orden API y registra desplazamiento mínimo por colisión; tests verifican cajas separadas, coordenadas finitas, alturas variables y entradas incompletas, tolerancia ≤2 px en casos sin colisión y ausencia de mutación/reloj.
  - Comando: `cd frontend && node --test --experimental-strip-types tests/public-bracket-layout.test.ts`.

- [x] **T4. Integrar diagrama medido, SVG decorativo y relaciones textuales.** RF-005, RF-007–012, RF-019; RNF-003–006. Depende de T2/T3. 30 min.
  - Hecho cuando: `PublicBracket` reutiliza `HorizontalScroll`, observa medidas solo en cliente y limpia recursos; SVG aria-hidden sin foco/clics, relaciones aceptadas también en texto y ganador identificable sin solo color. Rondas/partidos/controles permanecen visibles sin medidas, se conserva openLineup, score/tanda/W.O. y marca neutra; escalas 029 sin nuevas exclusiones genéricas y reduced-motion respetado. La revisión de capturas/axe se completa en T10, no se anticipa aquí.
  - Comando: `cd frontend && pnpm test && pnpm run typecheck && pnpm run lint`.

## PR B — Tablas y acceso público (T5–T8)

- [x] **T5. Priorizar las tres columnas móviles y conservar tablas/estadísticas completas.** RF-013–016; RNF-001, RNF-003–006. Después de PR A. 30 min.
  - Hecho cuando: Posición/Jugador/Goles o Posición/Equipo/GF son las columnas iniciales, identidad sticky y resto consultable; Goles se presenta antes de Equipo en jugadores sin quitar columna ni alterar filas. Recuentos indican filas mostradas y criterio actual consultable; props/eventos, foto/iniciales, rank/empates, orden servidor y load-more intactos. Tests estáticos existentes conservados/ampliados; visibilidad geométrica se mide en T10.
  - Comando: `cd frontend && node --test --experimental-strip-types tests/public-stats.test.ts && pnpm run typecheck`.

- [x] **T6. Acceso de teclado, pista y equipo sticky en clasificación.** RF-017; RNF-002–005. 20 min.
  - Hecho cuando: la tabla pública usa `HorizontalScroll` explícitamente importado, región nombrada con foco y pista; identidad de equipo sticky con fondo adecuado, caption/cabeceras/celdas intactos. Tests impiden restaurar `.table-scroll` sin foco o introducir overflow de documento; comprobación axe real de la corrección en T10.
  - Comando: `cd frontend && node --test --experimental-strip-types tests/public-navigation.test.ts && pnpm run lint`.

- [x] **T7. Anclas tempranas, ejemplo de portada y reflow de lista de partidos.** RF-002–004, RF-018; RNF-003, RNF-005/006. 25 min.
  - Hecho cuando: portada accede a torneos y detalle a resultados/estadísticas antes de recorrer equipos; destinos identificables no tapados, anclas sin JS y sin rutas/consultas nuevas. Registro/documentación y equipos siguen disponibles. Marcador fijo rotulado ejemplo, sin afirmación «En vivo»; equipos largos/estado/fecha/score y controles de partidos no se solapan. Textos ES/EN y tests presentes.
  - Comando: `cd frontend && node --test --experimental-strip-types tests/public-navigation.test.ts tests/public-tournament.test.ts && pnpm run typecheck`.

- [x] **T8. Proteger ámbito, paginación, privacidad de presentación y diálogo existentes.** RF-001, RF-010/011, RF-013/014, RF-016, RF-019; RNF-001/006. Depende de T4–T7. 20 min.
  - Hecho cuando: tests existentes de público comprueban ámbito inicial torneo completo, cambio/restauración explícitos en ambas tablas, posiciones compartidas y continuación, vacíos/errores existentes, placeholders, foto ausente/fallida y formación solo publicada con segmento/equivalente textual. Ningún cambio de backend/API/permisos ni cálculo local de ganadores/rank; no se reimplementan T15/T16. Las pruebas de foco y red anónima se completan en T9/T10.
  - Comando: `cd frontend && node --test --experimental-strip-types tests/public-navigation.test.ts tests/public-stats.test.ts tests/public-lineup.test.ts tests/public-tournament.test.ts && pnpm run typecheck`.

## PR C — Verificación y documentación (T9–T10)

- [ ] **T9. Automatizar regresión de público sin sesión y mediciones de aceptación.** RF-001–019; RNF-001–006. Depende de T8. 30 min.
  - Hecho cuando: `e2e/public-polish.spec.ts` usa contexto anónimo, viewport 1440×900/390×844, casos sintéticos del contrato normal/vacío/error y nombres largos; mide tres columnas completas, sticky al final del scroll, geometría, anclas y overflow, verifica filtro/restauración/paginación, teclado, Escape/retorno de foco y relaciones sin falsos positivos. Ampliar solo testMatch del proyecto public existente, conservando realtime y sin nueva dependencia. Traces/cookies/tokens no se guardan en evidencia.
  - Comando: `cd frontend && pnpm run typecheck:e2e && pnpm exec playwright test e2e/public-polish.spec.ts --project=public --no-deps` (test/entrada planeados por esta tarea).

- [ ] **T10. Auditoría final, documentación, limpieza y gates.** RF-001–019; RNF-001–006. Depende de T9. 30 min de trabajo activo; espera CI aparte.
  - Hecho cuando: todas las vistas se comparan con 031-before a ambas resoluciones; capturas/mediciones en `/home/ubuntu/ui-audit/031-after/`, axe cero de app incluida clasificación, navegación de teclado y reduced-motion documentados. Se prueban los cuadros 4/8/16/5 con byes y W.O.; si penales solo se simulan, se declara. Tabla RF con evidencia, desviaciones de centro por colisión explícitas, todas las métricas accesibles, sin datos nuevos ni pérdida de contenido; fixtures retirados por sus IDs. Manual/inspección/AGENTS/memoria actualizados, suites y CI aplicables verdes y revisión humana antes de cerrar como implementada; si falta un gate se deja pendiente, no se marca T10.
  - Comando: `cd frontend && pnpm test && pnpm run typecheck && pnpm run lint && pnpm run build && pnpm run typecheck:e2e && pnpm exec playwright test e2e/public-polish.spec.ts --project=public --no-deps`.
  - Además: ejecutar axe local sobre cada vista/viewport (con versión y JSON de resultados en la evidencia), comprobar `git diff --check` y esperar los jobs de CI descritos en el plan. No se debilitan reglas de axe ni tests para conseguir verde. Datos y capturas fuera del repo.

## Reglas de entrega

- PR A → PR B → PR C, en dependencia; cada PR conserva suites existentes verdes y evidencia de su superficie, no difiere fallos conocidos al siguiente. La pasada completa de aceptación se repite en T10 sobre el conjunto final.
- El usuario autorizó PR A y después PR B desde main actualizado en `devin/1794415336-spec-031-tablas-navegacion`, sin abrir PR. PR C requiere su siguiente encargo.
- Mantener la spec en aprobada hasta validación del conjunto y autorización explícita de cierre. T1–T8 ejecutadas; T9/T10 pendientes.

## Evidencia PR A — 2026-11-11

- TDD: rojo antes de código en T1 (módulo ausente), T2 (export ausente), T3 (módulo ausente) y T4 (integración/textos ausentes). Ver `/home/ubuntu/ui-audit/031-a-t{1,2,3,4}-{red,green}.log`; verdes focales 6/7/4/3 tests respectivamente. Suite final: 865 tests, 863 pass, 0 fail, 2 skip. Node 24.22.2/pnpm 12.12.1; test/typecheck/lint/build/typecheck:e2e con salida 0 (`031-a-final-checks.log`).
- `operation-flow`: setup y escenario existentes sin modificar, 2 passed (38.2s), `031-a-operation-flow.log`. Configuración local `.mts` fuera del repo solo selecciona el Chromium disponible; conserva proyectos/dependencias, localizadores y veredicto. Se corrigieron permisos de dependencias/artefactos ignorados generados previamente por Docker y se reinstaló con lockfile congelado; sin cambios de configuración/lockfile del repo.
- Diez mediciones anónimas: demo 8 y temporales 4/8/16/5 a 1440×900 y 390×844. Por resolución, dibujados/deducibles: 4/4, 1/1, 2/2, 4/4, 2/2; diferencia Y máxima 0 px, sin colisiones, solapes, overflow de documento, errores de página ni violaciones axe (10 ejecuciones). Incluyen pendientes, placeholders, W.O. reales y 3 byes en cuadro de 5. Colisiones/desplazamiento mínimo también cubiertos en test puro.
- Cero líneas falsas: igualdad de los pares SVG con una deducción independiente de los datos públicos y contraste con `advancement_links` locales solo para auditoría; la UI nunca consulta esas relaciones privadas. Repetidos, ambigüedad y ausencia de ganador se cubren en tests sin líneas. Penales se cubren por contrato unitario, no como cierre real de esta corrida.
- Teclado: scroll con flecha, diálogo de formación/Escape/retorno de foco, actualización de trazos al redimensionar y reduced-motion comprobados (`031-a-interactions.json`). Sin animación añadida ni excepciones 029 nuevas.
- Composiciones antes/después revisadas: `/home/ubuntu/ui-audit/031-a-pr/{demo-8,4,8,16,5}-{desktop,mobile}.png`. Datos y geometría en `031-a-{before,after}/measurements.json`. Fixtures retirados: cuatro torneos/33 equipos y un torneo E2E/dos equipos/dos jugadores; contadores finales cero en `031-a-cleanup{,-e2e}.log`. Demo y fixtures anteriores conservados.
- No se han ejecutado T5–T10 ni la aceptación global de portada/estadísticas/clasificación; permanece pendiente el arreglo de clasificación de PR B y el gate CI de PR.

## Evidencia PR B — 2026-11-11

- T5–T8: rojo antes del código, 36/14/6/75 tests focales verdes. Revisión posterior añadió guardas de caption/contexto originales y cabecera Posición sin corte de palabra. Logs `031-b-t{5,6,7,8}-{red,green}.log`, `031-b-review-red.log` y `031-b-header-red.log`, bajo `/home/ubuntu/ui-audit/`.
- Suite final: 871 tests, 869 pass, 0 fail, 2 skip; Node 24.22.2/pnpm 12.12.1. Test/typecheck/lint/build/typecheck:e2e salida 0 (`031-b-final-checks{,-css}.log`). E2E existente `operation-flow`: 2 passed (45.8s), configuración externa de Chromium, sin modificar escenario/configuración del repo.
- Veinte vistas reales por pasada a 1440×900/390×844: portada, detalle, bracket, ambas estadísticas, fase, formación gráfica/textual, clasificación y partidos. Después: cero violaciones axe 4.10.3, errores de página y overflow de documento. `scrollable-region-focusable`: dos apariciones antes, cero después. JSON, peticiones y campos en `031-b-{before,after}/`.
- Móvil: jugadores 767,30→752/278 px, Posición/Jugador→Posición/Jugador/Goles; equipos 523,72→528/278 px, las tres prioridades conservadas. Clasificación 760/320 px con pista, foco, fondo opaco y equipo sticky (desviación 0 px al extremo). Desktop: 8/6/11 columnas completas.
- Portada: acceso nuevo Y=602,89/487,99 (desktop/móvil); tarjetas Y=876,89/1130,45→876,89/1202,74, sin prometer adelantar las tarjetas. Selector del detalle Y=819,86/1117,06→585,86/504,06; accesos Y=498,36/332,25. Marcador rotulado «Marcador de ejemplo».
- Matriz observada de seis lecturas, queries y campos idéntica, incluidos orden/rank. Cuatro scripts idénticos a main salvo import de la tabla extraída (`031-b-scripts.json`); ninguna escritura ni cambio de API/backend/permisos/useApi. Doce comprobaciones reales adicionales: ocho anclas sin JS, foco/sticky en ambas resoluciones y continuación 50→96 jugadores respetando empates (`031-b-interactions{,-normal.log,.json}`).
- Composiciones etiquetadas/revisadas en `031-b-pr/`; sin excepciones 029 nuevas. Dos fixtures E2E creados y retirados (cuatro equipos/cuatro jugadores en total), contadores finales cero en `031-b-cleanup-e2e{,-first}.log`. Demo y fixtures anteriores conservados.
- Limitación: el arnés extra con respuestas simuladas de equipos no completó los casos de paginación/vacío/error; no se cuentan como verificados en navegador. El devserver emitió `[NUXT_E1001] A composable that requires access to the Nuxt instance was called outside of a plugin, Nuxt hook, Nuxt middleware, or Vue setup function.` Entorno Docker comprobado: Node 24.22.2/Nuxt 4.6.4, volúmenes independientes del build; reinicio local no eliminó el aviso. No se cambió lógica fuera del alcance para ocultarlo. Vacío/error y continuación de ambas tablas mantienen cobertura unitaria; T9/T10 y CI de PR quedan pendientes.
