# Plan 031 — Pulido de las vistas públicas

Fecha: 2026-11-11. Spec, plan y tareas aprobados por el usuario; fases de documentación cerradas. PR A (T1–T4) implementado y verificado; PR B/C pendientes. La spec permanece aprobada hasta completar y validar el conjunto.

## 1. Alcance y archivos por responsabilidad

Todas las rutas de frontend de la tabla son relativas a `frontend/`. Vue Composition API, estado derivado en `computed`, props hacia abajo y eventos hacia arriba; no se mueve la carga de datos ni se introduce otro estado de sesión.

| Archivo | Responsabilidad y contrato | Cobertura |
|---|---|---|
| `app/utils/publicBracket.ts` (nuevo) | Funciones puras `groupPublicRounds`, `inferPublicAdvances`, `publicRoundLabel`: reciben datos públicos inmutables y devuelven rondas, relaciones y claves i18n; sin DOM, red ni reloj. | RF-005–010, RF-012; RNF-001 |
| `app/utils/publicBracketLayout.ts` (nuevo) | `layoutPublicBracket(rounds, edges, measurements, spacing)`: centros, cajas y extremos de líneas; medidas y separación recibidas, sin leer el DOM. | RF-007, RF-012; RNF-003 |
| `app/composables/usePublicBracketLayout.ts` (nuevo) | Adaptador cliente: referencias a tarjetas, medidas tras montaje/fuentes, `ResizeObserver`, una actualización agrupada por frame. Limpia observadores/frame al desmontar o cambiar ámbito. El SSR ya muestra todas las tarjetas en orden, sin depender de medidas. | RF-005, RF-007, RF-012; RNF-003/005 |
| `app/components/public/PublicBracket.vue` | Compone rondas, tarjetas y `HorizontalScroll`; aplica posiciones del layout sin ocultar tarjetas, texto de procedencia solo para relaciones aceptadas, mensaje de conectores limitados. Conserva `matches` y evento `openLineup(match,event)`. | RF-005–012, RF-019 |
| `app/components/public/PublicBracketConnections.vue` (nuevo) | SVG local, trazos ortogonales entre el borde del origen y el del destino; `aria-hidden="true"`, `focusable="false"`, `pointer-events:none`. Nunca envuelve/oculta las tarjetas ni sus controles accesibles. | RF-007, RF-010; RNF-004/005 |
| `app/components/public/PublicPlayerStatsTable.vue`, `PublicTeamStatsTable.vue` | Tabla compacta, identidad sticky, prioridades iniciales, orden y rank intactos, recuento de filas mostradas y explicación del criterio actual. Mismos props/`load-more`, fotos y fallback actuales. | RF-013–017; RNF-001/003–006 |
| `app/pages/tournaments/[id].vue` | Accesos por ancla dentro de primera pantalla; sustituye `.table-scroll` de clasificación por `HorizontalScroll` importado explícitamente y fija identidad del equipo. Conserva selector de fase y ámbito independiente de estadísticas, filtros, paginación, cargas/errores y disparador del diálogo. Ajustes locales de lista de partidos, sin reordenar secciones ni rehacer el diálogo. | RF-001, RF-004, RF-013, RF-017–019 |
| `app/pages/index.vue` | Acceso «Ver torneos» a la sección de torneos, sin quitar registro/documentación; identifica marcador fijo como «Ejemplo», no «En vivo». No convierte el ejemplo en una consulta nueva. | RF-002/003 |
| `app/components/ui/HorizontalScroll.vue` (reutilizado, no modificar su contrato) | Pista móvil, región nombrada/foco/scroll de teclado; ya sirve a estadísticas y bracket. | RF-012/017; RNF-005 |
| `app/composables/useI18n.ts` | Nuevas etiquetas ES/EN, rondas, relación conocida, limitación de conexiones, ejemplo, recuento mostrado y orden actual. | RF-003/006/008/010/014/016; RNF-006 |
| `tests/public-bracket.test.ts`, `public-bracket-layout.test.ts` (nuevos) | Tablas de casos de funciones puras, sin navegador ni fixtures privados. | RF-005–012 |
| `tests/public-navigation.test.ts`, `public-stats.test.ts`, `public-lineup.test.ts`, `public-tournament.test.ts`, `design-scales.test.ts` | Ampliar las comprobaciones existentes, sin retirar ni debilitar aserciones. Si cambian límites del componente, seguir leyendo las piezas importadas para conservar cobertura. | RF-001–019; RNF-001–006 |
| `e2e/public-polish.spec.ts` (nuevo) | Recorrido público anónimo con Playwright y capturas/medidas de aceptación. Usará el proyecto Chromium existente mediante `--project=public --no-deps`; en T9 se amplía su `testMatch` para admitir esta spec sin alterar el escenario realtime existente. La spec crea un contexto sin `storageState`, aunque el proyecto público heredado lo tenga. | RF-001–019; RNF-002/003/005 |
| `docs/manual-usuario.md`, `docs/inspeccion-accesibilidad.md`, `AGENTS.md`, `MEMORY.md` | Documentación observable y evidencia, no anuncios de funcionalidad antes de verificarse. Actualizar README solo si su descripción de consulta pública queda obsoleta. | RNF y constitución §4 |

No backend, migraciones, tablas, RLS, registro de routers, outbox, worker, Socket.IO, variables, secretos ni dependencias nuevas. No se cambia `.env.example`, lockfile ni CI. El único ajuste de configuración previsto es el patrón acotado del proyecto Playwright ya descrito.

## 2. Algoritmo puro de conexiones

### 2.1 Entradas, seguridad y orden

La página entrega el ámbito público de un único torneo y los partidos cargados; `PublicMatch` ya tiene `id`, `stage_id`, `group_id`, `matchday`, identificadores de participantes y `winner_team_id`. No se consulta `advancement_links` ni slots privados. La salida contiene referencias internas a los IDs que ya llegaron; no amplía el contrato de respuesta.

Se agrupa por fase/grupo y jornada numérica, conservando el orden de aparición de la API dentro de la ronda (no reordenar por nombre, fecha o código). Las rondas se presentan por jornada; los partidos sin jornada quedan en una sección sin conexiones. Rondas consecutivas significa **r y r+1**, no dos columnas cargadas cualesquiera: si faltan datos de r+1 no se salta a r+2. No se mezclan fases, grupos, torneos ni páginas de otros ámbitos. La concatenación de páginas elimina duplicados idénticos por ID; un mismo ID con datos contradictorios se excluye de la inferencia, no se escoge arbitrariamente una versión.

```text
inferPublicAdvances(scope, matches):
  rounds = groupPublicRounds(scope, matches)  # copia estable; no muta matches
  edges = []
  for each (stage_id, group_id) partition:
    for each numeric round r with numeric round r+1 present:
      left = rounds[r]; right = rounds[r+1]
      winnersByTeam = map team_id -> list of source matches
      targetsByTeam = map team_id -> list of (target match, home|away)
      for A in left:
        if A.winner_team_id is not null:
          winnersByTeam[A.winner_team_id].append(A)
      for B in right:
        append each non-null participant occurrence to targetsByTeam
        # dos lados con el mismo equipo cuentan como dos ocurrencias: ambiguo
      for (team, sources) in winnersByTeam, in API order:
        targets = targetsByTeam[team]
        if length(sources) == 1 and length(targets) == 1:
          A = sources[0]; (B, side) = targets[0]
          if IDs and input records are valid and A.id != B.id
             and A.winner_team_id occurs exactly once among A.home_team_id,A.away_team_id:
            edges.append({sourceId:A.id, targetId:B.id, teamId:team, side})
  return stable edges
```

No se infiere ganador del score, ni se exige una resolución concreta: un ganador explícito por penales o W.O. cumple la misma condición. Una tanda, un estado `finished` o el código FINAL sin ganador **no** bastan. Si hay dos ganadores del mismo equipo en una ronda o dos apariciones posibles en la siguiente, no sale ninguna de esas líneas. Compartir nombre no importa si los IDs son distintos.

**Casos expresos:** bye sin partido origen → sin línea inventada; avance que salta una jornada → sin línea; cuadro parcial → solo pares presentes de r/r+1; pendientes sin ganador → sin línea; participante por definir → no hace match con null; repetidos → omisión conservadora; datos cargados después → recomputar solo con el ámbito vigente. El cuadro sigue mostrando todos los partidos aunque no tenga una sola conexión. **Una línea falsa es peor que una línea ausente.**

### 2.2 Layout vertical y colisiones

Las alturas reales cambian por nombres largos, formación o resolución: no asumir tarjetas de altura idéntica ni espaciar rondas con una constante por número de ronda. La función recibe cajas medidas y el gap resuelto desde un token de la 029. Cada columna tiene un encabezado independiente y las coordenadas se calculan respecto a una misma área de partidos, no respecto al documento desplazado.

```text
layoutPublicBracket(rounds, edges, heightsById, gap):
  positions = {}; deviations = []
  for round in numeric round order:
    nextTop = 0
    for B in round.matches in API order:
      h = heightsById[B.id]  # número finito, positivo; si falta, posponer medición
      origins = sources of edges whose targetId == B.id
      desired = mean(positions[A].centerY for A in origins) if origins else nextTop+h/2
      centerY = max(desired, nextTop+h/2)  # desplazamiento mínimo hacia abajo
      top = centerY-h/2
      positions[B.id] = {top, height:h, centerY}
      nextTop = top+h+gap
      deviations.append({id:B.id, nominal:desired, actual:centerY, collision:centerY>desired})
  columnHeight = max(top+height of all positions)
  paths = edges.map(A,B -> border(A.right, A.centerY) -> middle gutter -> border(B.left,B.centerY))
  return {positions, paths, columnHeight, deviations}
```

Se centra B en el promedio de los **orígenes aceptados presentes**, incluso si solo hay uno; sin orígenes conserva el orden de API y el empaquetado normal. No se reordenan tarjetas para disimular colisiones ni se añade una relación. Todos los intervalos de una columna quedan separados al menos por gap. El SVG abarca el tamaño real del cuadro dentro del mismo scroll, no el viewport; líneas no capturan clics ni foco. Sin medidas/JS, siguen visibles los partidos y las rondas; nunca bloquear la consulta esperando al observador.

**Compatibilidad de requisitos:** el borrador pedía error Y ≤2 px en todos los casos. Ese absoluto puede ser incompatible con el nuevo «evita solapes» cuando dos destinos reclaman una misma altura. RF-007 y el caso límite ahora distinguen centrado nominal (≤2 px sin colisión) de desplazamiento mínimo por colisión. Se mide y registra cada desviación; no se declara alineación exacta si se ha empaquetado. No se elimina una conexión cierta para aprobar una captura. Esta prioridad queda explícita para revisar el plan antes de implementar.

### 2.3 Nombres desde códigos existentes

Fuente comprobada: `backend/app/modules/tournaments/scheduling.py::_match_code(round_count, round_number, match_number)`, consumida por `build_single_elimination_bracket`. El contrato público vigente expone el resultado en `PublicMatchResponse.bracket_code` (`schemas.py`) y la lectura `/matches`; no expone una propiedad de nombre de ronda.

| Código exacto reconocido | Validación | Nombre ES / EN |
|---|---|---|
| `FINAL` | Igualdad exacta | Final / Final |
| `SF1`, `SF2` | `^SF[12]$` | Semifinales / Semifinals |
| `QF1`–`QF4` | `^QF[1-4]$` | Cuartos de final / Quarterfinals |
| `R16-1`–`R16-8` | `^R16-[1-8]$` | Octavos de final / Round of 16 |

El generador también emite `R{teams_in_round}-{match_number}` para tamaños mayores (por ejemplo `R32-1`): no se amplía la lista nominal aprobada, se usa «Ronda n». `publicRoundLabel(round)` solo nombra si todos los códigos de sus partidos son reconocidos y pertenecen a la misma familia; mezcla, null, código desconocido, minúsculas no contractuales o datos contradictorios → `public.round` con matchday; jornada null → etiqueta genérica existente de llave. Nunca contar columnas para llamar Final a la última. El código sirve para nombrar, **no** para inferir conexiones.

Ninguna función lee el reloj; si un formato de fecha futuro necesita «ahora», recibirá fecha de referencia explícita. Las fechas existentes siguen sus formateadores actuales.

## 3. Presentación y accesibilidad

- **Diagrama:** `HorizontalScroll` con nombre, pista y foco existentes. Columnas con encabezados legibles y todos sus partidos; no tarjetas/pestañas alternativas. SVG decorativo con `aria-hidden`, sin animaciones de trazado. Texto en la tarjeta destino «Procede del partido …» para cada relación aceptada, usando código público o etiqueta ordinal visible del partido, nunca datos privados. Falta de línea no se anuncia como eliminación ni bye. Señal de ganador textual/accesible además del peso/color; conservar score, tanda, resolución, placeholders y `openLineup`.
- **Escalas 029:** tamaños de texto, espacios, radios y colores existentes; `nearestStep` cuando corresponda. Conexiones esenciales en accent/muted con contraste ≥3:1, no `--color-line` decorativo. No nueva excepción genérica ni nueva `PENDING_MIGRATION`. Respeto de `prefers-reduced-motion` para cualquier transición/scroll; foco visible sin animación necesaria.
- **Clasificación móvil:** importar/reutilizar `HorizontalScroll`, quitar solo el contenedor `.table-scroll` sustituido, conservar caption/cabeceras/celdas. Columna de equipo sticky con fondo opaco y borde/sombra tokenizados; región con nombre y `tabindex=0` elimina el caso `scrollable-region-focusable`. Pista móvil visible, sin foco artificial en cada celda ni scroll en el documento.
- **Estadísticas:** mantener tablas. Jugadores: reubicar Goles antes de Equipo para que el orden visual sea Posición/Jugador/Goles/Equipo/resto, conservando todas las métricas y significado de encabezados; ajustar las aserciones de orden para el requisito aprobado, no borrarlas. Equipos ya ordena Posición/Equipo/GF. Reducir padding anidado y espacios móviles locales, anchos compactos para posición/métrica, identidad limitada con nombre completo accesible (no solo tooltip dependiente del ratón). Identidad sticky, rank/empates y filas intactos; no ordenar en cliente. A 390×844 las tres columnas prioritarias completas, no solo el principio de Goles. Pista/scroll y todas las otras columnas siguen disponibles. Recuento «N filas mostradas» al ofrecer cargar más; sin inventar un total no enviado.
- **Portada:** acceso por ancla a la lista de torneos dentro del primer viewport, sección destino identificada y con margen de scroll. Conservar la marca, hero, registro y documentación. Ejemplo fijo rotulado explícitamente como ejemplo, sin punto/etiqueta que afirme un vivo real; no agregar consulta de partido.
- **Detalle y fases:** anclas a resultados y estadísticas antes de la lista completa de equipos; destinos no tapados por controles flotantes. Conservar selector y primera fase del calendario; estadísticas siguen independientes, inicialmente torneo completo. No agregar grupos ni campos de selección nuevos. Preservar estados vacío/error, paginación y recuentos existentes salvo la precisión aprobada de filas mostradas.
- **Partidos/formaciones:** ajustes solo de reflow para nombres, marcador, estado y acciones, mismos campos; formación explícitamente publicada, segmento y alternativa textual actuales, Escape/retorno de foco. No redibujar el campo ni deducir una formación ausente. Todos los textos nuevos ES/EN.

## 4. Interfaz y exposición pública exacta

Se conservan `/` y `/tournaments/{id}` sin sesión, con las peticiones existentes mediante `app/composables/useApi.ts` (la ruta abreviada histórica de la skill no corresponde al layout Nuxt 4). Prefijo API actual `/api/v1`. No nuevos endpoints, parámetros, cuerpos, cookies ni permisos.

| Lectura actual | Contrato de respuesta que se conserva |
|---|---|
| `GET /tournaments/public` | Lista: `id,name,season,start_date,status`. |
| `GET /tournaments/public/{id}` | Esos cinco campos + `stages[]:{id,name,stage_type,stage_order}` y `teams[]:{team_id,name,short_code,crest_url}`. |
| `GET /tournaments/public/{id}/standings` | `tournament_id,stage_id,stage_name,stage_order,group_id,group_name,team_id,team_name,short_code,played,won,drawn,lost,goals_for,goals_against,goal_difference,points,fair_play_points,rank,calculated_at,crest_url`. |
| `GET /tournaments/public/{id}/matches` | `id,tournament_id,stage_id,stage_name,stage_order,group_id,group_name,bracket_code,matchday,match_date,home_team_id,home_team_name,home_team_short_code,home_team_crest_url,away_team_id,away_team_name,away_team_short_code,away_team_crest_url,home_score_regular,away_score_regular,home_score,away_score,home_penalties,away_penalties,winner_team_id,status,resolution_type,lineup`. |
| `lineup` anidado, no endpoint nuevo | `home,away`; cada equipo: `team_id,team_name,formation_code,segment_number,crest_url,starters,substitutes`; jugador publicado: `player_id,first_name,last_name,dorsal_number,role,position_slot,photo_url`. |
| `GET /tournaments/public/{id}/player-stats` | `rank,player_id,first_name,last_name,team_name,team_id,goals,yellow_cards,red_cards,clean_sheets,matches_played,photo_url`. |
| `GET /tournaments/public/{id}/team-stats` | `rank,team_id,team_name,short_code,crest_url,goals_for,goals_against,clean_sheets,fair_play_points`. |

Lista cerrada contrastada con `backend/app/modules/tournaments/schemas.py::Public*Response`. Se conservan `limit/offset` y los filtros `stage_id/group_id` de cada ruta que ya los admite; las estadísticas inicialmente omiten ambos y no heredan la fase del calendario. Las cargas futuras no utilizan consultas privadas ni nuevos campos. No se alteran el `404` indistinguible ni los límites/errores de parámetros de la 020/022.

No documentos, fechas de nacimiento, edad, motivos de resolución, sanciones, suspensiones, asistencias ni claves de almacenamiento. Fotos solo si llegan autorizadas por consentimiento/inscripción vigente conforme a 022; nunca pedirlas por una vía privada. Formación solo cuando está explícitamente publicada. No nuevas proyecciones ni campos calculados expuestos por API: relaciones/coordenadas son presentación local de los datos ya permitidos.

## 5. Decisiones y alternativas descartadas

| Decisión | Alternativa descartada | Motivo / RF |
|---|---|---|
| D1: diagrama con scroll horizontal | Lista o pestañas por ronda | Aprobación del usuario; conserva contexto y todas las rondas. RF-007/012. |
| D2: ganador explícito + participante + unicidad en r/r+1 | Código, posición de array, score o enlaces privados | No inventa un avance y no cambia API; omite conservadoramente. RF-008/009. |
| D3: códigos reconocidos actuales, fallback genérico | Inferir final por última columna o tamaño cargado | Funciona con cuadros parciales sin hacer autoritativa una inferencia. RF-006. |
| D4: tabla compacta con identidad sticky | Tarjetas o esconder métricas | Conserva comparación y datos; tres prioridades visibles. RF-015. |
| Priorizar no solapes, conservando orden de API, sobre centro exacto en colisión | Superponer tarjetas para satisfacer 2 px o reordenar silenciosamente | Reconcilia centrado y la instrucción posterior de no solapar; desplazamiento mínimo medido. RF-007/caso límite. |
| SVG decorativo y relaciones en texto | Canvas o interacción obligatoria para descubrir relaciones | Menos complejidad, sin librerías nuevas, teclado y lectura textual. RF-007; RNF-004/005. |
| Medidas inyectadas en función pura | DOM/reloj dentro del algoritmo | Tests deterministas, alturas reales y SSR independiente. RF-007; RNF-003. |
| Anclas en portada/detalle | Suprimir contenido promocional/equipos o nuevas rutas | Cumple acceso temprano sin ampliar alcance. RF-002/004. |
| Reutilizar `HorizontalScroll` localmente | Cambiar estilos globales o parchear solo axe | Soluciona foco, pista y acceso real sin regresión global. RF-017. |

## 6. Estrategia de tests y comprobaciones

**Primero tests en rojo**, después código mínimo, una tarea cada vez. Node 24/pnpm 12.12.1. No ejecutar ni declarar estas pruebas como pasadas en la entrega documental.

- `public-bracket.test.ts`: ganador regular, penales y W.O.; sin ganador, score sin ganador, null, nombres iguales/IDs distintos, ganador ajeno a participantes, participante duplicado en ambos lados, dos posibles fuentes/destinos, IDs duplicados contradictorios, ámbitos distintos, ronda ausente/null, mismo r no consecutivo, bye y conjunto parcial. Garantizar no mutación y salida estable; códigos FINAL/SF/QF/R16 exactos, otros R*, mezclas y vacíos. RF-005/006/008–011.
- `public-bracket-layout.test.ts`: alturas variables por formación/nombres, cero/uno/dos orígenes, centro promedio, colisiones y desplazamiento mínimo, gap tokenizado, orden de API, métricas incompletas, cajas sin solapes y coordenadas finitas. RF-007/012. La tolerancia de 2 px se comprueba separada de las colisiones deliberadas.
- Tests existentes de público y escalas: mantener todas las aserciones; añadir región con foco, sticky/pista, textos ES/EN, ganador sin solo color, cambios de columna/prioridades y recuento mostrado. RF-001–019; RNF. No «resolver» una aserción borrándola tras extraer componentes.
- Navegador anónimo en 1440×900 y 390×844: portada, detalle, clasificación, partidos, diagrama 4/8/16 y 5 con byes, estadísticas jugadores/equipos con carga de más, fase explícita/restaurada, formación gráfica/texto. Medir columnas prioritarias **completas**, región frente a ancho total, identidad a la derecha, centros/desviaciones, gap, anclas en primera pantalla y ausencia de overflow del documento. Incluir tabla sin filas, fallo de lectura y recuperación, cambios rápidos de fase y nombres largos. RF-001–019.
- Axe por vista/viewport: cero de aplicación, incluida la incidencia anterior `.table-scroll`; DevTools se separa, no se excluyen reglas/nodos de app. Sin dependencia nueva: usar el axe-core local de auditoría con versión registrada, como en la línea base. Teclado real Tab/flechas/Enter/Escape, foco no tapado, texto alternativo y reduced-motion. RNF-002–006.
- Datos de referencia: demo local y fixtures de contrato sin datos privados; si hacen falta torneos reales de 4/8/16/5, crearlos por servicios existentes en desarrollo, guardar IDs y retirarlos. Penales simulados se etiquetan como tales, no como cierre backend verificado. Capturas comparables con la base `031-before`; evidencias en `/home/ubuntu/ui-audit/031-after/`, fuera de Git. No trazas/cookies/tokens en evidencias ni datos demo en producción.
- Comandos desde `frontend/`: `pnpm test`, `pnpm run typecheck`, `pnpm run lint`, `pnpm run build`, `pnpm run typecheck:e2e`; navegador: `pnpm exec playwright test e2e/public-polish.spec.ts --project=public --no-deps`. Es un test planeado, aún no existe. Los tests puros se pueden ejecutar con `node --test --experimental-strip-types tests/public-bracket.test.ts tests/public-bracket-layout.test.ts`.
- CI: conservar jobs/disparadores actuales; gates backend/frontend/infrastructure/security y e2e en PR/main según constitución. No crear PR en esta entrega; no presentar un push documental como validación funcional ni como autorización de implementación. Actualizar manual/inspección/memoria tras la verificación real.

## 7. Entrega propuesta

PR A T1–T4: funciones puras, layout y diagrama. PR B T5–T8: tablas, acceso público y protección de contratos/diálogo. PR C T9–T10: regresión navegador, axe, documentación y gates. Dependencias y criterios en `tasks.md`; ≤30 minutos por tarea estimados, no autorización para extender su alcance. Si una tarea excede esa caja o surge una necesidad de API, parar y proponer división/revisión, no implementarla de forma implícita. El estado seguirá `aprobada` hasta completar validación y obtener autorización de cierre.

## 8. Verificación de constitución

La tabla es una comprobación del diseño, no una afirmación de pruebas ejecutadas. No se solicita excepción constitucional.

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por RLS | Sí, preservación | Sin consultas nuevas ni cambios de tablas/políticas; nunca usar enlaces privados; particionar por ámbito público. |
| §2.2 Sin privilegios BYPASSRLS | Sí, preservación | No roles, credenciales ni conexiones de BD en frontend. |
| §2.3 Publicado inmutable | Sí | Solo representación de lecturas; no escribir actas/versiones ni corregir resultados. |
| §2.4 Historial append-only | No cambia | Sin esquema ni migración; no editar ninguna existente. |
| §2.5 Proyección pública mínima | Sí | Lista cerrada §4, fotos consentidas y formación publicada; ninguna ampliación pública. |
| §2.6 Sin secretos por defecto | Sí, preservación | Sin configuración/variables nuevas; evidencias sin sesiones ni secretos. |
| §2.7 Administración separada/auditada | No cambia | `/admin` y auditoría de plataforma intactos. |
| §2.8 Verificación obligatoria | Sí | §6 y T9/T10, gates CI reales y revisión humana antes de cierre; declarar pendientes. |
| §2.9 Desarrollo fuera de producción | Sí | Fixtures/axe/capturas solo locales; limpiar IDs y no versionar datos/artefactos. |
| §3.3 HTTP por useApi y rutas | Sí | Mantener peticiones mediante `app/composables/useApi.ts`; contexto anónimo en ambas rutas. |
| §3.4/3.5 Seguridad y versiones | Sí, preservación | Node 24/pnpm 12.12.1, sin paquetes nuevos, lockfile intacto, auditorías de CI sin exclusiones. |
| §4 Todos: jobs CI correspondientes | Sí | Backend/frontend/infrastructure/security; e2e en PR/main, sin cambiar workflow ni omitir checks. |
| §4 Todos: sin secretos/datos personales en repo | Sí | Fixtures sintéticos y capturas fuera de Git; revisión de diff/artefactos y security CI. |
| §4 Todos: documentación de comportamiento observable | Sí | Spec aprobada, manual, inspección, AGENTS y memoria al finalizar. |
| §4 Todos: pruebas de comportamiento nuevo/corregido | Sí | Puros, estáticos, navegador y mediciones RF; casos normal/vacío/error explícitos. |
| §4 BD: nueva migración, RLS, volumen limpio/migrado, sh -n | No | No cambia BD ni migrador; no inventar migración para este frontend. |
| §4 API/backend: contexto RLS, exposición, router, pytest/compileall | Exposición sí; código backend no | Lista cerrada y matriz preservadas; CI backend existente, sin nuevo router ni consulta ni alteración de set_rls_context. |
| §4 Frontend: HTTP por useApi | Sí | §4 mantiene el transporte actual y no añade llamadas directas. |
| §4 Frontend: test/typecheck/build | Sí | Comandos §6, más lint/typecheck:e2e y navegador. |
| §4 Infra/despliegue: compose/defaults producción | No cambia | Sin Compose/despliegue; infrastructure CI existente sigue siendo gate. |
| §4 Dependencias: lockfiles/auditorías | No cambios de paquetes | Sin instalar librerías ni modificar lockfile; security CI se mantiene, sin nuevas exclusiones. |
