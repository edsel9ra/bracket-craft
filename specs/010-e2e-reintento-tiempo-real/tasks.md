# Tareas 010 — Prueba de extremo a extremo del reintento del tiempo real

**Spec:** `specs/010-e2e-reintento-tiempo-real/spec.md` (aprobada 2026-10-22).
**Plan:** `specs/010-e2e-reintento-tiempo-real/plan.md`.

**Cubre:** RF-001 a RF-006, RNF-001 a RNF-011 y los criterios de finalización 1 a 10.

**Dependencias:** T1 → T2; T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10. Se ejecutan **en orden, una sola cada
vez**; marca la casilla solo cuando «Hecho cuando» se cumpla. En cada tarea que cambia comportamiento, la
prueba se escribe **primero** y se confirma en rojo. Los comandos con pila requieren
`docker compose up -d --wait` y `docker compose exec -T api python -m scripts.seed_demo`.

**Sin migraciones:** ninguna tarea toca `infra/postgres/migrations/`, `init/` ni `backend/`.

**Dependencia nueva (una sola):** `@playwright/test@1.64.1` en `devDependencies` de `frontend/`, con
lockfile. Ninguna otra.

---

- [x] **T1. Guardas y etiqueta puras del estado manual de reintento.** RF-001, RNF-009, RNF-011
- Hecho cuando: se escriben primero `frontend/tests/realtime-manual-retry.test.ts` (rojo) y las
  ampliaciones de `frontend/tests/realtime-retry.test.ts` y `frontend/tests/realtime-reload.test.ts`
  (rojo), y después `frontend/app/utils/realtimeConnection.ts` añade `'retrying'` a
  `RealtimeConnectionStatus` y `frontend/app/utils/realtimeStatusLabel.ts` exporta
  `realtimeStatusLabelKey(status, namespace)`; `cd frontend && pnpm test` pasa y demuestra:
  `realtimeStatusLabelKey('retrying', ns)` es `ns.realtimeRetrying` para `public`, `workspace` y
  `match`, siempre **distinto** de `ns.realtimeReconnecting`, y `idle`/`connecting` devuelven `null`;
  `shouldForceReconnect('retrying', true) === false` y `needsNewSocketSession` con socket, mismo
  alcance y misma versión de sesión devuelve `false` (segunda pulsación sin intento nuevo, caso límite
  3); `isReconnection` con `previousStatus: 'retrying'` y `nextStatus: 'connected'` es `false`;
  `shouldPollPublicRealtime('retrying') === true`; las claves `public.realtimeRetrying`,
  `workspace.realtimeRetrying` y `match.realtimeRetrying` existen y no están vacías (la comprobación de
  catálogo completa en T2); **todos los casos que ya existían en `realtime-retry.test.ts` y
  `realtime-reload.test.ts` siguen pasando sin retirar ninguno**; `cd frontend && pnpm run typecheck`
  pasa.

- [x] **T2. Producto: estado manual en el composable, i18n y las tres vistas.** RF-001, RF-003, RNF-004, RNF-011
- Hecho cuando: se amplía primero `frontend/tests/realtime-manual-retry.test.ts` con el catálogo y las
  aserciones de fuente (rojo) y después: `frontend/app/composables/useRealtime.ts` hace que `connect()`
  devuelva `boolean` y que `retry()` devuelva `boolean`, fijando `'retrying'` **solo** cuando
  `connect()` creó socket; `frontend/app/composables/useI18n.ts` gana en **español e inglés**
  `public.realtimeRetrying` («Reintentando…» / «Retrying…»), `workspace.realtimeRetrying` y
  `match.realtimeRetrying`; y `frontend/app/pages/tournaments/[id].vue`,
  `frontend/app/pages/workspace/index.vue` y `frontend/app/pages/workspace/matches/[id].vue` calculan
  su etiqueta con `realtimeStatusLabelKey`, conservan `role="status"` y el botón condicionado a
  `status.value === 'error'` (el panel del Workspace mantiene su fallback `workspace.activeOperation`) y
  añaden `.realtime-retrying` a la regla de color existente; `cd frontend && pnpm test` pasa y
  demuestra: las tres claves existen en ambos catálogos, sus textos difieren de los de
  `*RealtimeReconnecting` y entre sí, y cada vista usa la función con su namespace y **no** contiene el
  literal «Reintentando»/«Retrying»; `cd frontend && pnpm run typecheck` y `cd frontend && pnpm run
  build` pasan.

- [ ] **T3. Andamiaje del arnés, funciones puras de observación y etiquetas de los localizadores.** RNF-001, RNF-005, RF-002 (parte pura)
- Hecho cuando: se escribe primero `frontend/tests/e2e-observations.test.ts` (rojo) y después
  `frontend/e2e/observations.ts` (`classifyReloads`, `assertScenarioOrder`, `expectedConnectionCount`,
  `isDuplicateReload`, `EXPECTED_VIEWS`, sin dependencias de Playwright y con todos los instantes y
  ventanas por parámetro), `frontend/e2e/labels.ts` (textos es/en de los localizadores),
  `frontend/playwright.config.ts` (proyecto `setup` con `testMatch: /session\.setup\.ts/` y tres
  proyectos de vista que dependen de él, un solo motor `chromium` headless, `workers: 1`, `retries: 0`,
  `testDir: './e2e'`, `timeout: 240_000`, `storageState` en `frontend/.auth/state.json`),
  `frontend/e2e/tsconfig.json`,
  `frontend/package.json` (`@playwright/test@1.64.1` en `devDependencies`; scripts `e2e`, `e2e:test` y
  `typecheck:e2e`) y las entradas de `.gitignore` (`frontend/e2e-report/`, `frontend/test-results/`,
  `frontend/playwright-report/` y `frontend/.auth/`); `cd frontend && pnpm install` actualiza el lockfile sin cambiar
  dependencias de ejecución; `cd frontend && pnpm test` pasa y demuestra: `classifyReloads` con una
  petición a los 30 s (sondeo) da `attributable: 0`, con una a 1,5 s de `connectedAt` da 1, con dos en
  la ventana da `duplicates: 1` y una anterior a `connectedAt` no es atribuible; `assertScenarioOrder`
  devuelve `[]` en el orden correcto y `manual-before-click`, `connected-while-blocked` y
  `manual-survived` en los tres casos rotos; `expectedConnectionCount` da 2 establecidas y 0 durante el
  bloqueo; los textos de `labels.ts` existen literalmente en el catálogo español de `useI18n.ts`; `cd
  frontend && pnpm run typecheck` y `cd frontend && pnpm run build` siguen pasando; `cd frontend &&
  pnpm run typecheck:e2e` pasa; `cd frontend && pnpm exec playwright --version` responde `1.64.1` y
  `cd frontend && pnpm exec playwright test --list` no lista ningún spec de `tests/`.

- [ ] **T4. Datos de la corrida, sesión del Workspace y artefactos saneados.** RF-005, RNF-005, RNF-006, RF-002 (origen de las recargas)
- Hecho cuando: se escribe primero la ampliación de `frontend/tests/e2e-observations.test.ts` con
  `redactLine`/`redactPath` (rojo) y después `frontend/e2e/demo.ts` (descubre el torneo público por
  `GET /tournaments/public` y un partido `scheduled` por `GET /tournaments/public/{id}/matches`; sin
  datos utilizables falla como **datos/infraestructura**, nunca omite la vista),
  `frontend/e2e/session.setup.ts` (fija `bc_locale=es`, inicia sesión **por la interfaz** con la cuenta
  demo, verifica `/workspace` y guarda `storageState` en `frontend/.auth/state.json`, que se reutiliza y
  sirve para reautenticar de forma declarada, caso límite 13) y `frontend/e2e/artifacts.ts`
  (`summary.json`, `view-<vista>.json`, `trace.jsonl` sin cabeceras, capturas PNG y lectura saneada de
  `docker compose logs`); `cd frontend && pnpm test` pasa y demuestra que `redactLine` elimina los
  valores de `Cookie`, `Set-Cookie`, `Authorization`, `token` y `bc_csrf_token` y deja el resto de la
  línea intacto; `cd frontend && pnpm run typecheck:e2e` pasa; con la pila levantada y sembrada, `cd
  frontend && pnpm exec playwright test --project=setup` sale **0**, deja las cookies de sesión **solo**
  en `frontend/.auth/state.json` (ignorado y fuera de `e2e-report/`) y `grep -R "Cookie" frontend/e2e-
  report` no devuelve nada.

- [ ] **T5. Interceptor del canal con retención y escenario de la vista pública.** RF-001, RF-002, RF-006, RNF-001
- Hecho cuando: se escribe primero `frontend/e2e/realtime-public.spec.ts` (rojo: sin escenario, el spec
  falla en la primera condición) y después
  `frontend/e2e/channel.ts` (`page.routeWebSocket` para la elevación y `page.route` para el sondeo, modos
  `pass`/`hold`/`abort`, cierre del transporte establecido, recuento de conexiones establecidas e
  intentos, marcas temporales), `frontend/e2e/realtimeScenario.ts` (escenario determinista con **dos
  ciclos** de pulsación: bloquear → error → clic con el canal bloqueado → estado manual → liberar →
  error → segundo ciclo → desbloquear → conectado → asentamiento de 3 s → recuentos → documento y
  recargas) y `frontend/e2e/realtime-public.spec.ts`; con la pila levantada y sembrada, `cd frontend &&
  pnpm exec playwright test e2e/realtime-public.spec.ts` (equivalente a `npx playwright test
  e2e/realtime-public.spec.ts`) sale **0** y deja `e2e-report/view-public.json` con: `blockedAt` <
  `errorVisibleAt` < `clickedAt` < `attemptStartedAt` < `manualVisibleAt` < `manualGoneAt` <
  `unblockedAt` < `connectedAt` < `settledAt` en los dos ciclos, `retryingVisibleAt` posterior al inicio
  del intento y anterior al desbloqueo, **0** conexiones establecidas durante el bloqueo, **2**
  establecidas en total, **0** navegaciones del frame principal, ≤1 recarga atribuible del consumidor
  público con su número observado declarado y `assertScenarioOrder` sin violaciones; el texto manual
  observado es «Reintentando…» y **no** aparece sin pulsación; `cd frontend && pnpm run typecheck:e2e`
  pasa y `cd frontend && pnpm test` sigue en verde.

- [ ] **T6. Vistas del Workspace y de la operación del partido.** RF-002, RF-003
- Hecho cuando: se escriben `frontend/e2e/realtime-workspace.spec.ts` y
  `frontend/e2e/realtime-operation.spec.ts` reutilizando `realtimeScenario.ts` (sin duplicar el
  escenario ni el bloqueo) y, con la pila levantada y sembrada, `cd frontend && pnpm exec playwright test
  e2e/realtime-workspace.spec.ts e2e/realtime-operation.spec.ts` sale **0** y deja
  `e2e-report/view-workspace.json` y `e2e-report/view-operation.json` con las mismas invariantes que la
  vista pública (orden, 2 conexiones establecidas, 0 durante el bloqueo, 0 recargas del documento, ≤1
  recarga atribuible por consumidor —`/api/v1/tournaments` y `/api/v1/matches/{id}/operation`
  respectivamente—, estado manual en ambos ciclos y ausencia de estado manual sin pulsación); ninguna de
  las dos usa `test.skip` ni `test.fixme` (`grep -n 'test\.\(skip\|fixme\)' frontend/e2e/*.ts` no
  devuelve nada); si se retira temporalmente el control de una vista, **su** spec falla y los otros dos
  siguen informando; `cd frontend && pnpm run typecheck:e2e` pasa.

- [ ] **T7. Runner local, veredicto y gate de las tres vistas.** RF-004 (local), RF-005, RF-006
- Hecho cuando: existe `frontend/e2e/run.ts` con `--no-stack`, reenvío de argumentos tras `--`, arranque
  acotado (`docker compose up -d --build --wait --wait-timeout 300`, ≤5 min, informado aparte), seed,
  ejecución de Playwright con `retries: 0`, agregación de `summary.json` y traducción a códigos de
  salida (0 verde, 1 comportamiento, 2 infraestructura, 3 inválida con causa); `cd frontend && pnpm run
  e2e` sale **0** con las tres vistas `passed` y una tabla con vista, resultado, duración, estados y
  recargas observadas; `cd frontend && pnpm run e2e:test -- --grep "vista pública"` sale **3** y declara
  `omitted-view` con las dos vistas que faltan; con la pila parada y `--no-stack`, `cd frontend && pnpm
  run e2e:test` sale **2** y se declara como fallo de infraestructura; `cd frontend && pnpm run
  typecheck:e2e` pasa y `grep -n 'retries' frontend/playwright.config.ts` muestra `retries: 0`.

- [ ] **T8. Job `e2e` en la integración continua.** RF-004, RNF-002, RNF-003, RNF-008
- Hecho cuando: `.github/workflows/ci.yml` gana un quinto job `e2e` **sin tocar los cuatro existentes**,
  con `if` que lo ejecuta en cada `pull_request` y solo en `push` a `main`, `timeout-minutes: 25`,
  pasos de pnpm 12.12.1 y Node 24 con caché por `frontend/pnpm-lock.yaml`, caché de
  `~/.cache/ms-playwright` por lockfile, `pnpm exec playwright install --with-deps chromium`, `pnpm run
  typecheck:e2e`, `cp .env.example .env`, arranque con `--wait --wait-timeout 300`, seed, `pnpm run
  e2e:test` como veredicto, volcado de `docker compose logs --no-color`, `actions/upload-artifact@v4`
  con `if: always()` y `retention-days: 7` sobre `frontend/e2e-report`, y `docker compose down -v` con
  `if: always()`; `docker compose config -q` y `docker compose config --format json | python3
  infra/scripts/check_env_contract.py -` siguen pasando (no se añaden variables a Compose ni a
  `.env.example`); `python3 infra/scripts/verify_version_sources.py --exclude-constitution` pasa;
  `pnpm --dir frontend audit --prod --json` no incluye `@playwright/test` y las auditorías y Trivy
  siguen sin exclusiones nuevas; el job no ejecuta ningún motor distinto de `chromium` ni ningún
  reintento del escenario; el flujo de trabajo conserva `permissions: contents: read`.

- [ ] **T9. Documentación de producto, operación y agentes.** RF-004, RF-006, RNF-011
- Hecho cuando: `README.md` documenta en «Tiempo real y outbox» el estado visible de **reintento manual**
  («Reintentando…»/«Retrying…», `role="status"`, aparece solo tras pulsar «Reintentar» en error y solo
  si se inicia un intento nuevo, desaparece al conectar o al volver a error, no altera la lógica ni las
  recargas) y en «Verificación» el comando `cd frontend && pnpm run e2e`, qué arranca, qué artefactos
  deja y qué significan verde, fallo de comportamiento, fallo de infraestructura y **corrida inválida**;
  `AGENTS.md` añade el quinto job a la lista autoritativa de verificaciones (disparadores, límites,
  artefactos), el comando local en Comandos/Testing, la nota de que marcar el job como *required check*
  es un ajuste del repositorio (no del código), y en Límites/Convenciones que el estado manual es
  producto y no instrumentación y que `frontend/e2e/` queda fuera de `pnpm test`; `grep -n
  'Reintentando\|Realtime retry end-to-end\|pnpm run e2e' README.md AGENTS.md` devuelve resultados; `git
  -c core.whitespace=cr-at-eol diff --check` no reporta errores; no se edita `docs/constitution.md`,
  `MEMORY.md`, `backend/`, `infra/` ni otras specs.

- [ ] **T10. Validación completa de la entrega.** Todos los RF (criterios 1 a 10)
- Hecho cuando: `cd frontend && pnpm install --frozen-lockfile`, `cd frontend && pnpm test`, `cd
  frontend && pnpm run typecheck`, `cd frontend && pnpm run build` y `cd frontend && pnpm run
  typecheck:e2e` pasan; **se ejecuta de verdad el E2E**: `docker compose up -d --build --wait` +
  `docker compose exec -T api python -m scripts.seed_demo` + `cd frontend && pnpm run e2e` sale **0** con
  las tres vistas y deja `summary.json` con las duraciones (corrida ≤15 min, cada vista ≤4 min) y los
  artefactos sin cookies ni tokens (`grep -R "bc_csrf_token\|Set-Cookie\|Authorization:" frontend/e2e-
  report` no devuelve nada); `cd backend && pytest -q` y `cd backend && python -m compileall -q app`
  pasan **sin cambios de backend**; `docker compose config -q`, `docker compose config --format json |
  python3 infra/scripts/check_env_contract.py -` y `python3
  infra/scripts/assert_production_compose.py --profile development -` pasan; `python3
  infra/scripts/verify_version_sources.py --exclude-constitution` pasa; `git -c core.whitespace=cr-at-eol
  diff --check` pasa; se recorre el plan RF por RF y criterio por criterio citando la prueba o el
  comando que lo respalda (incluido el job `e2e` ejecutado en la rama, no solo en local); se declaran
  **no ejecutadas** (sin presentarlas como realizadas) las comprobaciones que el entorno no permita,
  como `pip-audit`, Trivy o la ejecución real del job en GitHub Actions, indicando en cada caso quién
  las ejecuta; se confirma que **no hay migraciones** ni cambios en `init/`, `backend/`, la API ni los
  contratos, y que la única deuda declarada es la enmienda menor de la §4 de la constitución (§5.2) para
  nombrar el quinto job.
