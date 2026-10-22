# Plan 010 — Prueba de extremo a extremo del reintento del tiempo real

Spec: `specs/010-e2e-reintento-tiempo-real/spec.md` (aprobada 2026-10-22).
Estado del plan: **pendiente de aprobación del usuario**.

## Objetivo y alcance técnico

Dos entregas en un mismo cambio, sin migraciones, sin backend, sin API y sin contratos nuevos:

1. **Producto (RF-001, RNF-011).** Un estado visible propio del **reintento manual** (`retrying`),
   que solo la pulsación de «Reintentar» puede activar y **solo si esa pulsación inicia realmente un
   intento de conexión nuevo**, con texto propio en es/en y anunciado como estado. Vive en el
   composable del tiempo real y en las tres vistas donde ya existe el control.
2. **Verificación (RF-002 a RF-006).** Un arnés de **Playwright con Chromium headless** que ejecuta el
   escenario determinista de la spec en las tres vistas, con un **job propio de CI**, artefactos
   saneados y un comando local reproducible.

No cambia la lógica que decide cuándo abrir una conexión nueva (`shouldForceReconnect`,
`needsNewSocketSession`), ni el transporte, ni `useApi.ts`, ni el contrato de eventos, ni el esquema.
`init/`, `infra/postgres/migrations/` y `backend/` quedan intactos.

**Sin migraciones.** No hay DDL, ni scripts de seed nuevos, ni cambios en `init/`.

## Decisiones de plan (con alternativa descartada)

1. **El estado manual es un valor más de `RealtimeConnectionStatus`: `'retrying'`.**
   El estado visible del tiempo real ya se deriva de una sola fuente (`status`), así que añadir un
   miembro al union mantiene la etiqueta total y evita dos fuentes de verdad que puedan contradecirse.
   *Descartado:* un `manualRetry` booleano paralelo al estado, que obliga a recordar limpiarlo en cada
   transición (`connected`, `error`, `reconnecting`, `idle`) y permite combinaciones imposibles
   (`retrying` + `connected`). Las cuatro derivaciones afectadas se revisan y se cubren con pruebas
   (punto 11 de QA): `shouldForceReconnect`, `isReconnection`, `shouldPollPublicRealtime` y las tres
   etiquetas.
2. **`connect()` devuelve si inició un intento y `retry()` devuelve si mostró el estado manual.**
   El estado se fija **después** de que `connect()` haya creado el socket y **solo** si lo creó; hoy
   `connect()` sale en silencio por el guard de reutilización de sesión y ese caso debe seguir sin
   mostrar nada (caso límite 22). *Descartado:* fijar `retrying` antes de llamar a `connect()` (éxito
   falso con un clic no-op, prohibido por D7) y deducirlo luego con un `watch` sobre `status` (no
   distingue el intento de la pulsación del intento automático).
3. **La etiqueta visible se calcula con una función pura compartida por las tres vistas**
   (`realtimeStatusLabelKey(status, namespace)`), en lugar de tres `computed` con la misma cascada.
   Así la distinción «reintentando ≠ reconectando» es verificable sin navegador y en los dos idiomas
   (RNF-005, RNF-011), y las vistas solo añaden su fallback propio (el panel del Workspace muestra
   «Operación activa» cuando no hay nada que anunciar). *Descartado:* mantener las tres cascadas
   duplicadas y probarlas por aserción de texto sobre el `.vue`, que no detecta una rama olvidada en
   una sola vista.
4. **El escenario bloquea el canal con dos interceptores del navegador: `page.routeWebSocket` para la
   elevación y `page.route` para el sondeo**, y el bloqueo tiene **tres modos** (`pass`, `hold`,
   `abort`). *Descartado:* `page.route` sola, que no intercepta WebSocket (Playwright ≥1.48 ofrece
   `routeWebSocket`), y el `abort` inmediato en todas las fases, que hace durar el estado manual
   milisegundos e impide observarlo (punto 1 de QA). El modo `hold` deja la petición de sondeo **en
   vuelo** (sin respuesta, sin abortar) y es lo que hace **estable y observable** el estado manual
   durante el intento; su cota natural es el `timeout: 10_000` que ya configura el composable, y la
   prueba lo libera explícitamente antes de esa cota. El modo `abort` es el que lleva la vista a
   `error` rápido antes del clic.
5. **La caída del transporte ya establecido se provoca cerrando la conexión persistente interceptada
   desde el propio punto de intercepción del navegador**, con el canal aún bloqueado para que no pueda
   restaurarse. Es la única forma de pasar de `connected` a `error` sin tocar HTTP, sesión ni
   interfaz: `page.route` no ve un WebSocket ya abierto y `setOffline`/CDP offline tumba también la
   API (prohibido por Q3). El cierre lo observa el **motor del navegador** (evento de cierre de
   transporte), no la interfaz: no se simula el estado ni se cambia el cliente. *Descartado:* esperar
   al `pingTimeout` del servidor (10-20 s por vista y depende del temporizador del servidor),
   reiniciar el contenedor (tumba la API y la sesión) y arrancar con el canal ya bloqueado (rompe el
   caso límite 1, que exige una conexión aceptada y estable antes del bloqueo). **Se declara como
   interpretación de Q3 y el usuario debe confirmarla.**
6. **El observable de «no otra secuencia de conexión después» son los eventos WebSocket del
   navegador**, contados por el interceptor: `wsEstablecidos` debe ser **2** (el inicial antes del
   bloqueo y el que termina conectado tras la pulsación), **0** durante el bloqueo, y en una ventana
   de asentamiento de 3 s tras `connected` **no debe iniciarse ninguna petición nueva a
   `/socket.io/`**. *Descartado:* contar handshakes bloqueados como si fueran conexiones (punto 3 de
   QA: un intento rechazado no es un transporte) y contar sesiones del servidor (retirado por D8).
7. **La doble pulsación se prueba de dos maneras complementarias y ninguna es una carrera de DOM.**
   (a) **Prueba unitaria**: con el estado ya en `retrying` y socket vivo, `shouldForceReconnect`
   devuelve `false` y `needsNewSocketSession` también, así que una segunda llamada a `retry()` no
   crea otro intento ni duplica nada. (b) **E2E**: dos pulsaciones en **dos ciclos consecutivos** de
   error, cada una con su estado manual y su desaparición, con la misma conexión final, ≤1 recarga por
   consumidor y 2 conexiones persistentes en total. *Descartado:* dos clics en el mismo ciclo antes
   del repintado: el control solo existe en `error` y desaparece del DOM en la misma actualización, así
   que esa carrera no es reproducible ni determinista desde el navegador (punto 2 de QA). Se declara
   la limitación.
8. **La recarga atribuible se clasifica por origen y por instante, no por número total de
   peticiones**, con una función pura que recibe el instante de reconexión: una recarga es atribuible
   si la petición del consumidor empieza dentro de los **6 s** siguientes a `connected`; el sondeo
   periódico de la página pública (30 s) queda fuera de esa ventana y se registra aparte. Se exige
   **≤1 por consumidor** y **0 recargas del documento** (contadas con `framenavigated` del frame
   principal), y el número observado (0 o 1) se declara en el artefacto (D6). *Descartado:* exigir un
   número fijo (no determinista, contradice la 004) y contar peticiones totales (confunde sondeo con
   recarga).
9. **Los artefactos son propios y sin cabeceras: no se publica la traza de Playwright.**
   La traza de Playwright (`trace.zip`) incrusta peticiones y respuestas con sus cabeceras, es decir
   `Cookie`/`Set-Cookie`, y no ofrece saneado soportado; RF-005 exige artefactos **sin** cookies ni
   tokens. En su lugar el arnés escribe su **propia traza del navegador** (`trace.jsonl`: navegación,
   peticiones con método + ruta + estado + instante relativo y **sin cabeceras**, apertura/cierre de
   WebSocket, mensajes de consola y errores de página), las capturas PNG por vista, el JSON de estados
   y marcas, y el registro del servidor (`docker compose logs --no-color`, saneado por lista de
   patrones). *Descartado:* publicar `trace.zip` (contradice el criterio de artefactos) y
   post-procesar el zip (exigiría una dependencia de descompresión nueva y una enumeración frágil de
   ficheros internos). **Cambia la lectura literal de «traza del navegador» en RF-005 y el usuario debe
   confirmarlo.**
10. **El resultado se clasifica en cuatro salidas y el runner decide el código de salida**: `0` verde,
    `1` fallo de comportamiento, `2` fallo de infraestructura, `3` **corrida inválida**. En CI las
    cuatro últimas son **no verdes**: la invalidez no acusa al producto (la spec no la declara ni
    verde ni roja) pero **no abre el gate** y su causa queda declarada en el resumen del job y en el
    artefacto (punto 6 de QA). El runner exige **exactamente tres resultados** de vista; una vista
    omitida, saltada o ausente del informe convierte la corrida en no verde (RF-003, RNF-007).
    *Descartado:* dejar que el código de salida de Playwright sea el veredicto, que no distingue
    infraestructura de comportamiento ni expresa la invalidez.
11. **Los datos de la corrida salen del seed demo existente, sin ampliarlo.** `scripts.seed_demo`
    ya produce un torneo publicado y en vivo con cuatro cuartos cerrados (resultados públicos) y dos
    semifinales `scheduled` con participantes: sirve de torneo público con eventos y de partido abierto
    para la operación. El arnés **descubre** el torneo y el partido por la API pública
    (`/tournaments/public`, `/public/{id}/matches`) en lugar de fijar UUID. *Descartado:* ampliar el
    seed con UUID fijos (cambia datos de desarrollo y las comprobaciones de la spec 008) y un seed de
    pruebas propio (duplica ~1 500 líneas y una segunda fuente de verdad del modelo). No se toca
    `init/` ni `v_public_tournament_players`.
12. **La autenticación del Workspace se hace por la interfaz, una sola vez, en un proyecto de
    preparación que guarda `storageState`.** La sesión del navegador no se puede reconstruir solo con
    las cookies de la API: `bc_user_id` y `bc_organization_id` las escribe el cliente. *Descartado:*
    inyectar cookies a mano, que reproduce estado interno del cliente y se rompería en silencio si la
    app cambia de cookie. Es también el punto donde se implementa la reautenticación declarada del caso
    límite 13.
13. **El arranque de la pila y el escenario son pasos distintos.** `pnpm run e2e` arranca, siembra,
    mide y baja; `pnpm run e2e:test` ejecuta solo el escenario contra una pila ya levantada (lo que usa
    CI). El tiempo de arranque se declara aparte y no se cuenta como fallo del reintento (caso 18,
    punto 12 de QA). *Descartado:* un único comando monolítico, que mezcla un fallo de `docker compose
    up` con un fallo de aserción.
14. **`@playwright/test` se fija en `1.64.1` como `devDependency` del frontend**, con lockfile; los
    specs viven en `frontend/e2e/` (fuera de `frontend/tests/`, que `pnpm test` globa) y el navegador
    se instala con `pnpm exec playwright install --with-deps chromium`, cacheado por el lockfile. La
    imagen de producción no lo incluye (solo se copia `.output` a la etapa de ejecución) y la auditoría
    `--prod` no lo mira. *Descartado:* un paquete de pruebas en la raíz (no hay gestor en la raíz) y
    Playwright «latest» sin fijar (una subida de versión rompería el determinismo y el cacheado).

## Archivos y responsabilidades

### Producto (frontend)

- `frontend/app/utils/realtimeConnection.ts` — `RealtimeConnectionStatus` gana `'retrying'`, documentado
  como estado **exclusivo del reintento manual** (no lo produce el motor ni la reconexión automática).
  `isReconnection` y `needsNewSocketSession` no cambian de comportamiento (RF-001, RNF-004).
- `frontend/app/utils/realtimeStatusLabel.ts` — **nuevo**. `realtimeStatusLabelKey(status, namespace)`
  devuelve la clave i18n del estado visible o `null` si la vista no tiene nada que anunciar
  (`idle`, `connecting`). Puro, sin reloj, sin DOM (RF-001, RF-003, RNF-011).
- `frontend/app/composables/useRealtime.ts` — `connect()` devuelve `boolean` (si creó un socket) y
  `retry()` devuelve `boolean` (si mostró el estado manual): tras `connect()` con éxito fija
  `'retrying'`; las transiciones existentes (`connected`, `error`, `reconnecting`, `idle`) lo
  sustituyen, de modo que el estado desaparece al conectar y al volver a error (RF-001).
- `frontend/app/composables/useI18n.ts` — tres claves nuevas en **español e inglés**:
  `public.realtimeRetrying`, `workspace.realtimeRetrying`, `match.realtimeRetrying`, distintas de las
  `*RealtimeReconnecting` (RNF-011).
- `frontend/app/pages/tournaments/[id].vue`, `frontend/app/pages/workspace/index.vue`,
  `frontend/app/pages/workspace/matches/[id].vue` — la etiqueta se calcula con
  `realtimeStatusLabelKey`; el panel del Workspace conserva su fallback `workspace.activeOperation`;
  el `span` de estado mantiene `role="status"`; se añade `.realtime-retrying` a la regla de color
  existente sin depender solo del color. El control sigue condicionado a `error` y el aspecto no
  cambia (RF-001, RF-003, RNF-011).

### Pruebas unitarias (frontend, `node --test`)

- `frontend/tests/realtime-manual-retry.test.ts` — **nuevo**: guardas del estado manual, claves y
  distinción es/en, y aserciones de fuente sobre las tres vistas (RF-001, RF-003, RNF-011).
- `frontend/tests/realtime-retry.test.ts` — **ampliado, sin retirar casos**: 'retrying' no fuerza
  reconexión con socket vivo y no inicia un segundo intento (caso límite 3, punto 2 de QA).
- `frontend/tests/realtime-reload.test.ts` — **ampliado**: `shouldPollPublicRealtime('retrying')` es
  `true` (la vista sigue refrescándose por HTTP mientras dura el estado manual, RF-002) y la
  reconexión posterior a una pulsación sigue recargando ≤1 vez.
- `frontend/tests/realtime-dedup.test.ts` — **ampliado**: la ventana de deduplicación pertenece al
  socket lógico y se vacía al abrir uno nuevo, también en el camino del reintento manual; ninguna
  prueba existente se retira (RNF-009).
- `frontend/tests/e2e-observations.test.ts` — **nuevo**: funciones puras del arnés (orden del
  escenario, clasificación de recargas, recuento de conexiones) y contraste de las etiquetas es/en
  usadas por los localizadores contra `useI18n.ts` (RNF-001, RNF-005).

### Arnés E2E (`frontend/e2e/`, nuevo)

- `frontend/e2e/tsconfig.json` — proyecto propio para `tsc --noEmit` (el `typecheck` de Nuxt no
  incluye `e2e/`, porque `.nuxt/tsconfig.json` solo lista `../app/**/*` y `../tests/nuxt/**/*`).
- `frontend/playwright.config.ts` — un proyecto `setup` (`testMatch: /session\.setup\.ts/`) del que
  dependen los tres proyectos de vista; un solo motor `chromium` headless, `fullyParallel: false`,
  `workers: 1`, `retries: 0`, `testDir: './e2e'`, `baseURL` por variable con default
  `http://localhost:3000`, `timeout: 240_000` por vista, `expect.timeout: 10_000`, `storageState` en
  `frontend/.auth/state.json` (fuera de lo que se publica) y salida de artefactos en `e2e-report/`
  (RNF-001, RNF-002, RNF-008).
- `frontend/e2e/channel.ts` — interceptor del canal: `page.routeWebSocket(/\/socket\.io\//)` para la
  elevación y `page.route(/\/socket\.io\//)` para el sondeo, con modos `pass`/`hold`/`abort`, cierre
  del transporte establecido, recuento de conexiones establecidas e intentos, y marcas temporales
  (RF-001, Q3).
- `frontend/e2e/observations.ts` — **puro y sin dependencias de Playwright**: `classifyReloads`,
  `assertScenarioOrder`, `expectedConnectionCount`, `isDuplicateReload`. Recibe todos los instantes y
  ventanas por parámetro; nadie lee el reloj dentro (RNF-001, RF-002).
- `frontend/e2e/labels.ts` — textos es/en usados por los localizadores accesibles, con el contraste
  contra el catálogo verificado en las pruebas unitarias (RNF-005).
- `frontend/e2e/session.setup.ts` — proyecto de preparación: fija el idioma (`bc_locale=es`), inicia
  sesión por la interfaz con la cuenta demo, comprueba el Workspace y guarda `storageState` en
  `frontend/.auth/state.json` —**fuera** de `e2e-report/`, para que las cookies de sesión nunca se
  publiquen como artefacto— (caso 13).
- `frontend/e2e/demo.ts` — descubre torneo público y partido abierto (`status: scheduled`) por la API
  pública; si no hay datos utilizables, falla como **infraestructura/datos**, no omite la vista
  (caso 16).
- `frontend/e2e/realtimeScenario.ts` — escenario determinista compartido por las tres vistas: fija
  idioma, navega, observa estados, ejecuta dos ciclos de pulsación y devuelve marcas, recargas y
  recuentos (RF-001, RF-002, RF-003).
- `frontend/e2e/artifacts.ts` — escritura de `e2e-report/view-<vista>.json`, `trace.jsonl` sin
  cabeceras, capturas PNG y resumen legible; funciones de saneado puras (RF-005, RNF-006).
- `frontend/e2e/realtime-public.spec.ts`, `frontend/e2e/realtime-workspace.spec.ts`,
  `frontend/e2e/realtime-operation.spec.ts` — una vista cada uno, con su propio resultado; sin
  `test.skip`/`test.fixme` (RF-003).
- `frontend/e2e/reporter.ts` — reporter de Playwright que vuelca resultados por vista y el resumen.
- `frontend/e2e/run.ts` — orquestador: `--no-stack` omite el arranque, los argumentos tras `--` se
  reenvían a Playwright (permite demostrar el gate de vistas omitidas), ejecuta, agrega, imprime la
  tabla de las tres vistas y traduce a los códigos 0/1/2/3 (RF-004, RF-005, RF-006).
- `frontend/package.json` — `@playwright/test` en `devDependencies`; scripts `e2e`, `e2e:test` y
  `typecheck:e2e`.
- `.gitignore` — `frontend/e2e-report/`, `frontend/test-results/`, `frontend/playwright-report/` y
  `frontend/.auth/` (estado de sesión de la prueba: nunca se publica).

### Integración continua y documentación

- `.github/workflows/ci.yml` — **job `e2e`** (quinto), con su propio filtro de rama, pasos, límites y
  artefactos; los cuatro jobs existentes no se tocan (RF-004).
- `README.md` — estado visible de reintento manual, comando local, qué ejecuta el job y qué significa
  que falle o que la corrida sea inválida; nota de que marcar el job como *required check* es un
  ajuste del repositorio en GitHub, no del código (RNF-011, RF-006).
- `AGENTS.md` — lista autoritativa de verificaciones (quinto job y comando local), límites del
  proyecto (estado manual, sin instrumentación) y comandos de Testing (RNF-011).
- `docs/constitution.md` — **no se edita**; la enmienda que añade el quinto job a la §4 se tramita por
  separado según §5.2 (ver «Verificación de constitución»).

## Estados y funciones puras

| Función / estado | Ubicación | Regla |
|---|---|---|
| `RealtimeConnectionStatus` (`'retrying'`) | `app/utils/realtimeConnection.ts` | Estado visible **solo manual**; lo fija `retry()` y lo sustituye cualquier transición del motor. |
| `realtimeStatusLabelKey(status, namespace)` | `app/utils/realtimeStatusLabel.ts` | `connected`/`reconnecting`/`retrying`/`error` → `"<namespace>.realtime<Estado>"`; `idle` y `connecting` → `null`. Sin reloj, sin DOM. |
| `shouldForceReconnect(status, hasSocket)` | `app/utils/realtimeRetry.ts` (existente) | Sin cambio de reglas; `retrying` cae en «solo si no hay socket» → `false` con socket vivo (anti-acumulación). |
| `needsNewSocketSession(input)` | `app/utils/realtimeConnection.ts` (existente) | Sin cambio: con socket, mismo alcance y misma versión de sesión devuelve `false`, que es lo que convierte la doble pulsación en un no-op. |
| `retry(): boolean` | `app/composables/useRealtime.ts` | Fuerza reconexión según `shouldForceReconnect`, llama a `connect()` y devuelve `true` **solo** si `connect()` creó socket; en ese caso fija `'retrying'`. |
| `classifyReloads({requests, endpoints, connectedAt, windowMs, pollingIntervalMs})` | `e2e/observations.ts` | Devuelve `{attributable, polling, duplicates}`: atribuible = primera petición del endpoint dentro de la ventana posterior a `connectedAt`; una segunda en la misma ventana es `duplicates` (fallo); el resto es sondeo, informativo. |
| `assertScenarioOrder(marks)` | `e2e/observations.ts` | Lista de violaciones con código (`manual-before-click`, `connected-while-blocked`, `manual-survived`, `connected-without-manual`, `reload-before-reconnect`…); vacía = orden válido. |
| `expectedConnectionCount({cycles, blockedWindow})` | `e2e/observations.ts` | `establecidas = 1 (inicial) + 1 (tras la última pulsación)`; `establecidas durante el bloqueo = 0`. |
| `isDuplicateReload(group)` | `e2e/observations.ts` | Dos recargas del mismo consumidor en la misma ventana → `true`. |
| `redactLine(line)` / `redactPath(path)` | `e2e/artifacts.ts` | Elimina valores de `Cookie`, `Set-Cookie`, `Authorization`, `token` y `bc_csrf_token` de cualquier línea registrada. Sin red, sin reloj. |

Ninguna función de lógica temporal lee el reloj: los instantes los toma el arnés en el borde
(`Date.now()` en `channel.ts`, `realtimeScenario.ts` y `artifacts.ts`) y los pasa como parámetro.

## Pseudocódigo

### Estado manual en el composable

```text
connect(input?, options?) -> boolean
  ... validaciones y guard de sesión como hoy
  si !needsNewSocketSession(...) -> return false            # no-op: no hay intento nuevo
  disconnect(false); socket = io(...); setStatus('connecting'); initialization.start()
  -> return true

retry() -> boolean
  si shouldForceReconnect(status.value, socket !== null) -> disconnect(false)
  started = connect(activeHandlers)
  si !started -> return false                                # clic sin efecto: no se muestra nada (caso 22)
  setStatus('retrying')                                       # DESPUÉS del intento, y solo entonces (D7)
  -> return true

# transiciones que sustituyen el estado manual (sin código nuevo)
on('connect')            -> 'connected'      # el estado manual desaparece al conectar
on('connect_error')      -> 'error'          # … y al fallar el intento (caso 8)
on('disconnect')         -> 'reconnecting'
on('reconnect_attempt')  -> 'reconnecting'
disconnect()             -> 'idle'
```

Consecuencia verificada en pruebas: `shouldPollPublicRealtime('retrying') = true`, así que la página
pública sigue con su sondeo mientras dura el estado manual (RF-002).

### Bloqueo del canal (interceptor)

```text
createChannelGate(page):
  gate = { mode: 'pass', held: [], wsRoutes: [], counts: {establecidas: 0, intentos: 0, sondeo: 0} }

  page.routeWebSocket(/\/socket\.io\//, ws =>
    counts.intentos += 1
    si mode == 'pass':
        ws.connectToServer().then(() => { counts.establecidas += 1; lastUsable = ws })
    si no:
        wsRoutes.push(ws)                    # nunca se acepta el handshake: queda sin conexión al servidor
  )

  page.route(/\/socket\.io\//, route =>
    counts.sondeo += 1; registrar { método, ruta, at: now() }
    si mode == 'pass'  -> route.continue()
    si mode == 'hold'  -> held.push(route)       # EN VUELO: ni respuesta ni aborto
    si mode == 'abort' -> route.abort()          # error rápido del intento
  )

  closeEstablishedTransport():                   # caída real del transporte, no toca HTTP ni sesión
      lastUsable.close()                         # el navegador observa el cierre del WebSocket
  setMode(mode)
  releaseHeld(): held.forEach(r => r.abort()); held = []      # el intento retenido falla -> 'error'
  unblock():
      mode = 'pass'; releaseHeld()
      wsRoutes.forEach(ws => ws.close())         # se descartan los handshakes bloqueados
```

Cota de `hold`: el `timeout: 10_000` del propio cliente. La prueba lo libera explícitamente mucho
antes (≤3 s de espera máxima para observar el estado manual), así que no depende de ese temporizador
para pasar. Mientras el bloqueo dure, `counts.establecidas` no puede aumentar: eso es lo que
demuestra que el estado conectado no aparece por una recuperación espontánea (caso 2).

### Escenario por vista

```text
runScenario(page, view, timeouts)
  1. gate.install()                                  # interceptores en modo 'pass', ANTES de navegar
  2. idioma: context.addCookies([bc_locale = 'es'])  # RNF-005, caso 12
  3. page.goto(view.url, waitUntil: 'load')          # calentamiento aparte, no medido
  4. esperarEstado(view, CONECTADO, T.connect)       -> marcas.connectedOnceAt      # caso 1
  5. gate.setMode('block'); gate.closeEstablishedTransport()
                                                     -> marcas.blockedAt, closedAt
  6. esperarControl(view, «Reintentar», T.error)     -> marcas.errorVisibleAt
     afirmar: el texto visible NUNCA es el conectado; counts.establecidas == 1
  7. para ciclo en [1, 2]:                            # dos ciclos: doble pulsación (caso 3)
        gate.setMode('hold')
        pulsar «Reintentar»                          -> marcas.clickedAt
        marcas.attemptStartedAt = primera petición /socket.io/ posterior a clickedAt
        esperarEstado(view, MANUAL, T.manual)        -> marcas.manualVisibleAt
        afirmar: attemptStartedAt < manualVisibleAt y clickedAt < manualVisibleAt
                 y el texto manual != texto automático de reconexión (caso 9)
                 y el texto visible != conectado (caso 11)
        gate.releaseHeld()                           -> marcas.releasedAt
        esperarControl(view, «Reintentar», T.attemptFail)
                                                     -> marcas.manualGoneAt (vuelve el error, caso 4/8)
        afirmar: el texto manual ya no está y el control está disponible
  8. gate.unblock()                                  -> marcas.unblockedAt
     esperarEstado(view, CONECTADO, T.reconnect)     -> marcas.connectedAt
  9. asentar(3 s): ninguna petición nueva a /socket\.io/   -> marcas.settledAt   # punto 3 de QA
 10. afirmar counts.establecidas == 2 y establecidas durante el bloqueo == 0
 11. afirmar navegaciones del frame principal == 0  (framenavigated)             # sin recarga del documento
 12. reloads = classifyReloads(...)  sobre las peticiones de los endpoints del consumidor
     afirmar reloads.attributable <= 1 y reloads.duplicates == 0
 13. afirmar assertScenarioOrder(marks) == []
 14. escribir artefacto {vista, marcas, counts, reloads (observado 0|1), documentReload: false,
                         sessionId?: {valor, concluyente: false}}
                                                        # RF-005; el sid se toma del handshake inicial
```

`view` fija: la URL, el namespace de las etiquetas (`public`/`workspace`/`match`) y el endpoint del
consumidor (`/tournaments/public/{id}`, `/tournaments`, `/matches/{id}/operation`).

### Runner y veredicto

```text
e2e/run.ts [--no-stack]
  si !--no-stack:
      docker compose up -d --build --wait --wait-timeout 300      # ≤5 min, paso aparte
      docker compose exec -T api python -m scripts.seed_demo
  pnpm exec playwright test --reporter=./e2e/reporter.ts          # retries: 0
  resultados = leer e2e-report/summary.json
  si falta el resumen o falló el arranque        -> 2 (infraestructura)
  si resultados.length != 3                      -> 3 (inválida: vista omitida) + causa
  si alguna vista = invalid                      -> 3 (inválida) + causa de cada una
  si alguna vista = infrastructure               -> 2
  si alguna vista = behavioral                   -> 1
  si no                                          -> 0
  imprimir tabla: vista | resultado | duración | estados | recargas observadas
```

## Interfaz y UX del estado manual

| Estado visible | es | en | Rol | Cuándo |
|---|---|---|---|---|
| `connected` | Actualización en vivo conectada | Live updates connected | `status` | canal conectado |
| `reconnecting` | Reconectando actualización en vivo | Reconnecting live updates | `status` | reconexión automática |
| **`retrying`** | **Reintentando…** | **Retrying…** | `status` | **solo** tras pulsar «Reintentar» y **solo** si se inició un intento nuevo |
| `error` | La actualización en vivo no está disponible | Live updates are unavailable | `status` | transporte caído |
| `idle` / `connecting` | (sin etiqueta) | (sin etiqueta) | — | nada que anunciar |

- Las tres vistas usan su namespace (`public.*`, `workspace.*`, `match.*`); el panel del Workspace
  conserva su fallback a «Operación activa» cuando no hay etiqueta.
- El control «Reintentar» sigue existiendo **solo** en `error` y desaparece al reconectar, también
  mientras se muestra `retrying`, porque el estado ya no es `error`.
- El estado se anuncia por `role="status"` (ya presente en las tres vistas) y el texto es la señal
  principal; `.realtime-retrying` comparte el color de aviso de `reconnecting`/`error`, así que no
  depende solo del color ni de una animación (RNF-011, caso 19).
- Sin cambios de API, de contrato de eventos, de ruta ni de datos.

## Estrategia de pruebas

### Unitarias (siempre corren, sin navegador)

`frontend/tests/realtime-manual-retry.test.ts`:

- `realtimeStatusLabelKey('retrying', ns)` devuelve `ns.realtimeRetrying` para los tres namespaces y es
  **distinto** de `ns.realtimeReconnecting`; `idle` y `connecting` → `null`; `connected` y `error` →
  sus claves (RF-001, RNF-011).
- Catálogo: las tres claves nuevas existen en español **y** en inglés, sus textos no son iguales entre
  sí ni iguales a los de `*RealtimeReconnecting`, y no están vacías (RNF-005, RNF-011).
- Guardas: `shouldForceReconnect('retrying', true) === false` y, con el mismo alcance y la misma
  versión de sesión, `needsNewSocketSession(...) === false` — la segunda pulsación no acumula intentos
  (caso 3, D8).
- `isReconnection` con `previousStatus: 'retrying'` y `nextStatus: 'connected'` es `false` (el estado
  manual no convierte la pulsación en «reconexión» a efectos del respaldo de recarga).
- `shouldPollPublicRealtime('retrying') === true` (RF-002: la vista sigue actualizándose por HTTP).
- Aserciones de fuente sobre las tres vistas: cada una usa `realtimeStatusLabelKey` con su namespace,
  conserva `role="status"`, condiciona el botón a `status.value === 'error'` y **no** contiene el
  literal «Reintentando»/«Retrying» (RF-003, RNF-011).
- Aserción de fuente sobre `useI18n.ts`: paridad es/en de las tres claves nuevas (complementa
  `labels.test.ts`, que no se modifica).

`frontend/tests/realtime-retry.test.ts` y `frontend/tests/realtime-reload.test.ts`: ampliación con los
casos anteriores sin retirar ninguno (RNF-009).

`frontend/tests/realtime-dedup.test.ts`: se fija que la ventana de deduplicación se vacía al abrir un
socket lógico nuevo (incluido el camino del reintento manual) y que una entrega repetida del mismo
`event_id` con la ventana vigente no duplica el despacho. Es el respaldo de D3 y no se retira nada.

`frontend/tests/e2e-observations.test.ts`:

- `classifyReloads`: 0 recargas con la petición del consumidor a los 30 s (sondeo) → `attributable: 0`;
  una a 1,5 s de `connectedAt` → 1; dos dentro de la ventana → `duplicates: 1`; una antes de
  `connectedAt` no es atribuible.
- `assertScenarioOrder`: orden correcto → `[]`; estado manual antes del clic → `manual-before-click`;
  conectado durante el bloqueo → `connected-while-blocked`; manual que sobrevive → `manual-survived`.
- `expectedConnectionCount`: dos ciclos → **2** conexiones establecidas (la inicial antes del bloqueo y
  la única que termina conectada) y **0** durante el bloqueo, porque ningún intento bloqueado llega a
  establecer transporte; el caso de una sola pulsación también se fija.
- `labels.ts` contra `useI18n.ts`: los textos que usan los localizadores existen literalmente en el
  catálogo español y su traducción inglesa también (evita el drift de localizadores, RNF-005).

Comandos: `cd frontend && pnpm test`.

### E2E por vista (`frontend/e2e/`)

| Vista | URL | Namespace | Endpoint de recarga | RF |
|---|---|---|---|---|
| Pública del torneo | `/tournaments/{id}` | `public` | `/api/v1/tournaments/public/{id}` | RF-001, RF-002, RF-003 |
| Panel del Workspace | `/workspace` | `workspace` | `/api/v1/tournaments` | RF-001, RF-002, RF-003 |
| Operación del partido | `/workspace/matches/{id}` | `match` | `/api/v1/matches/{id}/operation` | RF-001, RF-002, RF-003 |

Cada spec: preparación común (idioma y `storageState`), dos ciclos de pulsación, desbloqueo, ventana de
asentamiento, recargas y documento. Un fallo de una vista no impide el informe de las otras
(`workers: 1`, resultados por spec). Una vista que pierda el control falla en su propio spec, sin
omitirse.

### Tiempos máximos (declarados y comprobados)

| Condición | Máximo |
|---|---|
| Idiomas y contexto | — (inmediato) |
| Carga inicial de la vista hasta `connected` (caché del navegador en frío) | 45 s |
| Calentamiento de la pila (una navegación previa a la pública, fuera del escenario) | 120 s |
| Caída → control «Reintentar» visible | 15 s |
| Pulsación → estado manual visible | 3 s |
| Liberar el intento retenido → vuelve `error` y el manual desaparece | 15 s |
| Desbloquear → `connected` | 30 s |
| Ventana de asentamiento sin nuevas secuencias de conexión | 3 s |
| Ventana de recarga atribuible tras `connected` | 6 s |
| Una vista completa (`test` timeout) | **240 s (4 min)** |
| Corrida completa (tres vistas, serializadas) | **15 min** |
| Arranque de pila + seed (paso aparte) | 5 min |
| Job completo (`timeout-minutes`) | 25 min |

Un tiempo agotado no produce «timeout genérico»: cada espera nombra la condición y la vista, y el
mensaje incluye el último texto visible observado (RF-005).

### Qué **no** cubre esta prueba (declarado)

- Entrega duplicada del transporte y deduplicación: pruebas unitarias (`realtime-dedup.test.ts`).
- Conteo de sesiones del servidor: retirado por D8; el `sid` solo se adjunta como dato informativo.
- Motores distintos de Chromium headless, móviles reales y emulación de red móvil (RNF-008).
- Otros flujos (planilla, clasificaciones, invitaciones, miembros), regresión visual y accesibilidad
  general.
- Dos clics en el mismo ciclo antes del repintado: no reproducible por la UI; se cubre con las guardas
  puras (decisión 7).
- Una segunda conexión lógica que nunca recibiera eventos: el detector es «≤1 recarga por consumidor» +
  ventana de asentamiento; se acepta como riesgo residual.
- Rendimiento, latencia o throughput del tiempo real (RNF-003 de la 005 sigue sin medirse).

## Job de integración continua

```yaml
e2e:
  name: Realtime retry end-to-end
  if: >-
    github.event_name == 'pull_request' ||
    (github.event_name == 'push' && github.ref == 'refs/heads/main')
  runs-on: ubuntu-latest
  timeout-minutes: 25
  steps:
    - checkout
    - pnpm/action-setup@v4 (12.12.1) + actions/setup-node@v4 (24, cache pnpm, frontend/pnpm-lock.yaml)
    - pnpm install --frozen-lockfile (frontend)
    - cache ~/.cache/ms-playwright con clave = hash(frontend/pnpm-lock.yaml)
    - pnpm exec playwright install --with-deps chromium
    - pnpm run typecheck:e2e                       # tsc del arnés (no lo cubre el typecheck de Nuxt)
    - cp .env.example .env                          # valores de desarrollo documentados, sin secretos
    - docker compose up -d --build --wait --wait-timeout 300
    - docker compose exec -T api python -m scripts.seed_demo
    - pnpm run e2e:test                             # veredicto 0/1/2/3, declarando la causa
    - docker compose logs --no-color > e2e-report/server.log   (siempre)
    - actions/upload-artifact@v4 (if: always(), retention-days: 7,
      name: e2e-realtime-${{ github.run_id }}, path: frontend/e2e-report)
    - docker compose down -v (if: always())
```

- **Disparadores:** cualquier `pull_request` y solo `push` a `main`. Un `push` a otra rama no ejecuta el
  job y **no** se interpreta como verde (Q1, caso 20). El disparador de nivel superior del flujo de
  trabajo no se toca; el filtro vive en el job.
- **Un solo motor:** `chromium` headless, sin matriz (Q2).
- **En verde:** las tres vistas presentes y `passed`, con `retries: 0`, dentro de 15 min de corrida
  (RF-004). El runner falla si el informe no trae las tres.
- **Inválida:** `run.ts` sale con **3** y el resumen declara la causa (`no-error-before-click`,
  `channel-not-blocked`, `no-accepted-connection-before-block`, `omitted-view`). El job queda **no
  verde** con la causa a la vista, sin acusar al producto (punto 6 de QA).
- **Infraestructura:** `run.ts` sale con **2** cuando falta el resumen, falla el arranque, no hay
  navegador o no hay datos utilizables; el mensaje y el artefacto lo distinguen del comportamiento
  (RF-005, casos 16 y 17).
- **Caché:** el navegador se cachea por lockfile; el `node_modules` del frontend usa el caché de pnpm
  (punto 12 de QA).
- **Required check:** marcar `Realtime retry end-to-end` como *required* en la protección de `main` es
  un ajuste del repositorio en GitHub, no del código; se documenta y se deja al operador (punto 7 de
  QA).

### Comando local (RF-006)

```sh
cd frontend && pnpm install --frozen-lockfile
pnpm exec playwright install --with-deps chromium   # una vez por máquina
pnpm run e2e                                       # arranca pila, siembra, ejecuta, baja y resume
pnpm run e2e:test                                  # solo el escenario contra una pila ya levantada
```

Mismos motores, mismo bloqueo, mismas tres vistas y mismos artefactos que CI. Sin secretos: usa
`.env.example`. Si el entorno no puede ejecutarlo (sin Docker o sin navegador), el runner sale con `2`
y la validación lo declara **no ejecutado**.

## Datos de la corrida y artefactos

- **Datos:** `scripts.seed_demo` sin cambios (organización `demo-federation`, cuenta
  `demo.owner@bracketcraft.dev`, torneo `live` con cuatro cuartos cerrados y dos semifinales
  `scheduled`). La prueba **descubre** torneo y partido por la API pública; si no encuentra un partido
  `scheduled`, falla por datos (caso 16) y no omite la vista. No se toca `init/`,
  `v_public_tournament_players` ni la definición del seed.
- **Artefactos por corrida** (`frontend/e2e-report/`, en `.gitignore`):
  - `summary.json` — resultado de las tres vistas, duración total y de cada una, causa cuando no es
    verde.
  - `view-<vista>.json` — marcas de cada ciclo (bloqueo, cierre, error, clic, inicio del intento,
    estado manual, desaparición, desbloqueo, conectado, asentamiento), recuento de conexiones
    establecidas e intentos, recargas por consumidor con su origen y su instante, recargas del
    documento, y `sid` **informativo y no concluyente** si se pudo leer del handshake inicial.
  - `trace.jsonl` — traza propia del navegador: navegación, peticiones (método, ruta, estado,
    instante relativo), aperturas y cierres de WebSocket, consola y errores de página. **Sin
    cabeceras**, por construcción.
  - `screenshots/<vista>.png` — captura en el instante del fallo (o del último estado si pasa).
  - `server.log` — `docker compose logs --no-color api worker web`, pasado por `redactLine`.
  - Saneado: `redactLine`/`redactPath` eliminan valores de `Cookie`, `Set-Cookie`, `Authorization`,
    `token` y la cookie CSRF; no se registran credenciales ni cuerpos de petición.
- **Retención:** 7 días en CI; local queda en el directorio ignorado. El estado de sesión de la prueba
  vive en `frontend/.auth/state.json`, **fuera** de `e2e-report/`: se reutiliza entre vistas, no se
  versiona y no se sube como artefacto.

## Documentación obligatoria (mismo cambio que el código)

### `README.md`

- Sección «Tiempo real y outbox»: el estado visible de **reintento manual** («Reintentando…»/
  «Retrying…», `role="status"`), cuándo aparece (solo tras pulsar «Reintentar» en error y solo si se
  inicia un intento nuevo) y cuándo desaparece (al conectar o al volver a error); que no altera la
  lógica de reintento ni las recargas.
- Sección «Verificación»: comando local `cd frontend && pnpm run e2e`, qué hace, qué artefactos deja y
  qué significan verde, fallo de comportamiento, fallo de infraestructura y corrida inválida.

### `AGENTS.md`

- «Verificación»: el quinto job `e2e` en la lista autoritativa (disparadores, límites, artefactos) y el
  comando local; nota de que marcar el job como *required check* es ajuste del repositorio.
- «Límites del Proyecto» / «Convenciones»: el estado manual es producto, no instrumentación; la prueba
  no añade ganchos ni variables globales; `frontend/e2e/` no entra en `pnpm test`.
- «Testing»: cómo se ejecuta el E2E y que las pruebas unitarias de reintento y deduplicación se
  conservan.

## Riesgos

- **`nuxt dev` en CI es lento en la primera petición** (compilación bajo demanda): mitigado con una
  navegación de calentamiento fuera del escenario y 45 s para el primer `connected`; si el calentamiento
  no basta, el fallo se declara de infraestructura, no de comportamiento.
- **`routeWebSocket` exige Playwright ≥1.48** y fija el comportamiento del interceptor: se fija
  `1.64.1` exacto y se actualiza de forma deliberada, con lockfile.
- **Lectura del texto por muestreo del DOM** (no hay observador inyectado, por RNF-010): la espera usa
  `expect(locator).toHaveText` con reintento interno, así que la granularidad no afecta al veredicto,
  pero sí al instante registrado (±100 ms); las aserciones son de **orden**, no de delta exacto.
- **El `sid` puede no ser legible** (respuesta del sondeo inicial fuera del alcance de
  `page.on('response')` si se sirve por otro transporte): se registra si aparece y su ausencia no es
  fallo.
- **`docker compose up --build` en CI** consume 2-4 min y puede agotar disco: el paso tiene su propio
  límite y `down -v` al final; el job declara 25 min de techo.
- **Coste de dependencias nuevas:** `@playwright/test` es solo de desarrollo; `pnpm audit --prod` no lo
  audita y Trivy solo mira el lockfile con `--ignore-unfixed`; cualquier hallazgo accionable que
  aparezca se corrige subiendo la versión, sin exclusiones (RNF-003).
- **Interpretaciones que el usuario debe confirmar:** el cierre del transporte para provocar la caída
  (decisión 5) y la sustitución de la traza de Playwright por una traza propia sin cabeceras
  (decisión 9).

## Riesgos residuales

- Dos clics en el mismo ciclo no se reproducen en navegador; quedan cubiertos por guardas puras.
- Una segunda conexión lógica que no llegara a recibir eventos no se detectaría; el detector es la
  ausencia de recargas duplicadas y la ventana de asentamiento.
- El bloqueo por intercepción simula la indisponibilidad en el plano de red del navegador, no un fallo
  de red del sistema operativo; es la única forma admitida por Q3.
- La corrida depende de la pila de desarrollo (`nuxt dev`), no de la imagen de producción; una
  regresión exclusiva del build de producción no la detectaría.
- `pnpm run typecheck` no cubre `e2e/`; se compensa con `typecheck:e2e` en el job, que no está en el job
  `frontend`.

## Qué RF cubre cada parte

| Parte | RF | Dónde |
|---|---|---|
| Estado manual (producto) | RF-001 | `useRealtime.ts`, `realtimeConnection.ts`, `realtimeStatusLabel.ts`, tres vistas |
| Idioma, accesibilidad y distinción | RNF-011, RNF-005 | `useI18n.ts`, `realtimeStatusLabel.ts`, `realtime-manual-retry.test.ts` |
| Bloqueo del canal y escenario | RF-001, RF-002 (orden), Q3 | `e2e/channel.ts`, `e2e/realtimeScenario.ts` |
| Recargas y documento | RF-002 | `e2e/observations.ts`, `e2e/realtimeScenario.ts`, `realtime-reload.test.ts` |
| Tres vistas sin omisiones | RF-003 | tres specs + `run.ts` (exige tres resultados) |
| Job de CI | RF-004 | `.github/workflows/ci.yml` (job `e2e`) |
| Diagnóstico y artefactos | RF-005, RNF-006 | `e2e/artifacts.ts`, `e2e/reporter.ts`, upload del job |
| Comando local | RF-006 | `frontend/package.json`, `e2e/run.ts`, README |
| Deduplicación y convivencia | RNF-009 | `realtime-dedup.test.ts`, `realtime-retry.test.ts` |
| Sin superficie de producción | RNF-003 | `devDependencies` + `.output` |
| Documentación | RNF-011 (docs) | `README.md`, `AGENTS.md` |
| Base de datos | — | **Sin migraciones** |

## Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por tenant garantizado por la base de datos | Sí | No cambia ninguna consulta ni RLS; la prueba usa una sola organización ficticia y no accede a datos de otras (RNF-006). |
| §2.2 La aplicación no se salta RLS | Sí | Sin cambios de rol ni de privilegios; sin migración. |
| §2.3 Lo publicado es inmutable | Sí | No se modifican versiones, actas ni resultados; el escenario es de solo lectura salvo el estado del canal en el navegador. |
| §2.4 Historial de esquema append-only | Sí | **No hay migración**: no se crea ni se edita nada en `infra/postgres/migrations/` ni en `init/`. |
| §2.5 Lo público es una proyección mínima | Sí | Ninguna proyección cambia; no se consume ni se retira `v_public_tournament_players`; los artefactos no incluyen documentos, fechas de nacimiento ni fotos. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Sin secretos nuevos; la prueba usa `.env.example` y las credenciales demo de desarrollo; los artefactos se sanean (RF-005). |
| §2.7 Administración global separada y auditada | Sí | No se toca `/admin` ni la auditoría; la prueba no ejecuta acciones auditables. |
| §2.8 Nada se da por terminado sin verificación | Sí | Cada RF tiene prueba o comando; el E2E se ejecuta de verdad en la validación y cualquier paso no ejecutado se declara (RF-006, criterio 7). |
| §2.9 Código de desarrollo fuera de producción | Sí | No hay seed nuevo; el seed demo sigue siendo solo de desarrollo y el job no se ejecuta contra producción. |
| §3.1 RLS y migraciones | Sí | Sin DDL y sin consultas nuevas; nada que aplicar en volumen limpio ni migrado. |
| §3.2 Backend (módulos, async, outbox) | Sí | **Sin cambios de backend**: no hay módulo, router ni evento nuevo. |
| §3.3 Frontend (`useApi.ts`, rutas) | Sí | Sin llamadas HTTP nuevas en el producto; la prueba reutiliza la interfaz real y las rutas existentes (`/tournaments/{id}`, `/workspace`, `/workspace/matches/{id}`); `/workspace` sigue exigiendo sesión y organización activa. |
| §3.4 Seguridad y configuración | Sí | Sin variables nuevas en Compose ni en `.env.example`; `@playwright/test` es de desarrollo; la auditoría del frontend (`--prod`) y Trivy siguen sin exclusiones. |
| §3.5 Infraestructura y CI | Sí | Versiones de referencia intactas (Python 3.14, Node 24, pnpm 12.12.1) y `docker compose config -q` sigue validando desarrollo y producción; se **añade** un job, no se altera ninguno existente. |
| §4 Todos los cambios | Sí | Jobs `backend`, `frontend`, `infrastructure`, `security` y el nuevo `e2e` en verde; sin secretos ni datos personales; documentación de producto y de agentes actualizada en el mismo cambio; pruebas para el comportamiento nuevo (estado manual y escenario). |
| §4 Cambios de base de datos | No aplica | Sin cambio de esquema. |
| §4 Cambios de API o backend | No aplica | Backend, API y contratos intactos (RNF-004). |
| §4 Cambios de frontend | Sí | Llamadas por `useApi.ts` (sin cambios); `pnpm test`, `pnpm run typecheck` y `pnpm run build` pasan; el estado manual tiene pruebas unitarias y de navegador. |
| §4 Cambios de infraestructura | Parcial | No cambia Compose ni el perfil de producción; solo un job nuevo y comandos documentados. `docker compose config -q` y las aserciones de producción siguen pasando. |
| §4 Cambios de dependencias | Sí | Una `devDependency` (`@playwright/test@1.64.1`) con lockfile actualizado; `pip-audit`, la auditoría del frontend y Trivy pasan sin listas de supresión ni `--ignore-unfixable` añadido por nosotros. |
| §5.1 Excepciones | No aplica | No se omite ninguna regla ni criterio; no se requiere excepción. |
| §5.2 Evolución (quinto job en la §4) | Sí | La §4 enumera hoy cuatro jobs. El job `e2e` **no omite** ningún criterio, pero la enumeración queda desactualizada: se corrige con una **enmienda menor (1.4.0) tramitada por separado**, según §5.2 y según el «Fuera de alcance» de la spec 010. Dueño: responsable del producto; condición: antes del cierre de la spec 010. No se mezcla con este cambio. |
| §6 Definición de cumplimiento | Sí | Principios respetados, reglas y criterios cumplidos, CI en verde (incluido el job nuevo) y revisión humana distinta del autor antes de fusionar. |

**Conclusión:** no hay incumplimientos ni excepciones pendientes. La única deuda declarada es la
enmienda menor de la §4 para nombrar el quinto job, que se tramita como cambio propio (no bloquea la
implementación, sí su cierre documental).

## Dudas abiertas

Ninguna bloqueante. Se piden dos confirmaciones al aprobar el plan: la **decisión 5** (el cierre del
transporte interceptado como forma de provocar la caída con el canal bloqueado) y la **decisión 9**
(traza propia sin cabeceras en lugar de `trace.zip` de Playwright), ambas dentro de RF-001/Q3 y
RF-005 respectivamente.
