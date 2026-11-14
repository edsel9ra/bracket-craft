# Auditoría de noviembre de 2026

## Seguimiento R32f — cierre por F8 (2026-11-13)

La spec 035 está implementada y aceptada expresamente por el usuario («Opción A»:
«Acepto F8; ciérrala y empieza la spec de F1»), tras fusionar
[#78](https://github.com/edsel9ra/bracket-craft/pull/78). **R32f cerrado** para
la implementación validada: entrega privada por destinatario con autorización
fresca de la lectura HTTP equivalente, sin fallback organizativo, fail-closed
y recuperación HTTP sin replay. El carril público no cambia y F9 sigue fuera
de Socket.IO. F8 no habilita por sí sola borradores F1.

CI #78 sobre `1edcb5bb`: [pull_request 43512284375](https://github.com/edsel9ra/bracket-craft/actions/runs/43512284375)
y [push 43511994626](https://github.com/edsel9ra/bracket-craft/actions/runs/43511994626)
en `success`, más Devin Review sin hallazgos. Evidencias y límites en
`specs/035-tiempo-real-por-rol/verificacion.md`. Esto no acredita despliegue
productivo: siguen vigentes el orden coordinado y el rollback fail-closed de
`docs/despliegue-tiempo-real-por-rol.md`, incluida la 055 antes de arrancar API.
El informe fechado siguiente y sus límites de ejecución se conservan como
historial; H9 trata la revalidación periódica, no sustituye el filtro por evento.

## Resumen y alcance

Auditoría del **2026-11-09**, contrastada con `main` en
`6502d6b7eb4975d6feaa05060a6fb151d9f106b7`, después de integrar los PR
[#25](https://github.com/edsel9ra/bracket-craft/pull/25),
[#26](https://github.com/edsel9ra/bracket-craft/pull/26) y
[#27](https://github.com/edsel9ra/bracket-craft/pull/27).
La comprobación inicial no introdujo correcciones de código ni cambios de dependencias.
El seguimiento de H6 en [este PR](https://github.com/edsel9ra/bracket-craft/pull/37), sobre `main` en `988a46b`,
añade overrides acotados y las verificaciones descritas en su sección.
El seguimiento de H10 en [este PR](https://github.com/edsel9ra/bracket-craft/pull/38), sobre `main` en `5bf526c`,
divide el router de torneos sin modificar el contrato OpenAPI ni la lógica.

Se revisaron código, configuración, documentación y pruebas automatizadas en
contenedores Python 3.14 y Node 24, con pnpm 12.12.1. Los resultados corresponden
al código de ese commit, no a un despliegue productivo. «Resuelto» indica que la
corrección está presente y cubierta por las verificaciones indicadas; no sustituye
la validación operativa con un proxy real y varios workers.

## Hallazgos

Las rutas y líneas siguientes corresponden al commit auditado. Las suites completas
de la sección de verificación incluyen los tests citados, salvo los opt-in con BD.

| ID | Severidad | Descripción | Estado | PR y evidencia (archivo:línea; test) |
| --- | --- | --- | --- | --- |
| H1 | Alta | Socket.IO con varios workers: cliente WebSocket exclusivo, relay Redis por proceso y gate E2E compatible con conexiones directas. | Resuelto | [#25](https://github.com/edsel9ra/bracket-craft/pull/25). `frontend/app/composables/useRealtime.ts:117`; `backend/app/main.py:479–500,568`; `frontend/e2e/channel.ts:180,227–234,277–285,447`. Tests: `frontend/tests/realtime-manual-retry.test.ts:29`, `realtime-channel-gate.test.ts:31,47,70`; `backend/tests/test_outbox_relay.py:168` y `test_outbox_resync.py:253`. |
| H2 | Media | IP real tras proxy: cabeceras habilitadas, confianza obligatoria, comando exec y validación estricta de IP/CIDR. | Resuelto | [#25](https://github.com/edsel9ra/bracket-craft/pull/25). `docker-compose.production.yml:47–58`; `infra/scripts/assert_production_compose.py:49–55,473–487`. `backend/tests/test_production_compose_assertions.py:495–513` cubre `*`, `/0`, bits de host, IP/red válida y coma+espacio; `test_production_compose_rendering.py` verifica el YAML real cuando hay Docker Compose disponible. |
| H3 | Media | Cabeceras de seguridad API y SSR. | Resuelto | [#26](https://github.com/edsel9ra/bracket-craft/pull/26). `backend/app/core/security_headers.py:7–30`; conexión exterior en `backend/app/main.py:931`; `frontend/app/utils/securityHeaders.ts:1–9`, `frontend/nuxt.config.ts:1–5`. Tests: `backend/tests/test_security_headers.py:12,32,43,55` y `frontend/tests/security-headers.test.ts:8,18`. |
| H4 | Media | Cadena de suministro CI: acciones fijadas por commit y Dependabot. | Resuelto | [#26](https://github.com/edsel9ra/bracket-craft/pull/26). `.github/workflows/ci.yml:29–306`: 14 `uses:`, todos con SHA de 40 caracteres; `.github/dependabot.yml:1–23`: revisión semanal de github-actions, pip y npm, agrupando minor/patch. Tests: `backend/tests/test_workflow_pins.py:10,22`. |
| H5 | Baja | Login ejecuta Argon2 incluso si falta usuario o contraseña almacenada. | Resuelto | [#26](https://github.com/edsel9ra/bracket-craft/pull/26). `backend/app/core/security.py:17–18,26–27`; `backend/app/modules/identity/router.py:282–284`. Tests: `backend/tests/test_auth_login.py:24,123–129,160`: parámetros, llamada al verificador y prohibición de autenticar con el ficticio. Medición local orientativa más abajo. |
| H6 | Baja | Advisories transitivos de frontend: glob/minimatch corregidos; deepmerge sin corrección publicada. | Mitigado | [Este PR](https://github.com/edsel9ra/bracket-craft/pull/37). `frontend/pnpm-workspace.yaml` y `frontend/pnpm-lock.yaml`: overrides a glob 14.0.4 y minimatch 11.0.5. `pnpm audit` conserva solo deepmerge 4.3.1 (bajo). Sin referencias identificables en `.output`; `frontend/Dockerfile:20` copia solo ese artefacto. Verificaciones y límites más abajo. |
| H7 | Baja | Detecciones históricas de Gitleaks en datos demo/artefactos npm. | Mitigado | [#27](https://github.com/edsel9ra/bracket-craft/pull/27). **Historial sin reescribir (decisión del dueño)**. `.github/workflows/ci.yml:184–192` escanea `git archive HEAD`; `.gitleaks.toml:3–13` conserva reglas predeterminadas y permite tres literales dummy exactos. Comprobación CLI del árbol actual: sin fugas. No se volvió a escanear el historial en esta ronda. |
| H8 | Baja | Cliente Redis compartido por proceso y cerrado al apagar. | Resuelto | [#27](https://github.com/edsel9ra/bracket-craft/pull/27). `backend/app/core/redis_client.py:6–20`; consumidores en `backend/app/core/rate_limit.py:70`, `backend/app/main.py:907`; cierre en `backend/app/main.py:583`. Tests: `backend/tests/test_redis_client.py:14,33,40,53`. El relay mantiene su conexión independiente. |
| H9 | Baja | Revalidación de sockets en lote, con registro del fallo. | Resuelto | [#27](https://github.com/edsel9ra/bracket-craft/pull/27). `infra/postgres/migrations/032_socket_session_revalidation.sql:3–18` (`SECURITY INVOKER`); `backend/app/main.py:531–559`: una consulta por ciclo no vacío, cada 30 s; `logger.exception` en línea 545. Tests puros: `backend/tests/test_socket_revalidation.py:11,40`, incluyendo error sin desconexión masiva. Tests reales SQL en `test_socket_revalidation_db.py`, no ejecutados con BD en esta ronda. |
| H10 | Mantenibilidad | Router monolítico de torneos. | Resuelto | [Este PR](https://github.com/edsel9ra/bracket-craft/pull/38). `backend/app/modules/tournaments/router.py`: de 4887 a 22 líneas; helpers compartidos en `access.py` y siete subrouters en `routes/`. OpenAPI normalizado idéntico a `5bf526c`; mismo conjunto de rutas y orden de los cinco pares solapados. `backend/tests/test_tournament_routes_order.py` fija las 31 operaciones y la precedencia privada/pública. Tamaños y suites completas en el seguimiento H10. |
| H11 | Documentación | Memoria con decisiones y resultados históricos diferenciados. | Resuelto | [#27](https://github.com/edsel9ra/bracket-craft/pull/27). Inspección `nl -ba MEMORY.md`: líneas 5–13 registran auditoría, 16 registra migración 032, 21–22 diferencian resultados históricos y corrigen «sin commitear». Sin test dedicado. La línea 10 recoge la verificación inicial H1/H2/H12, no una ejecución E2E de esta ronda. |
| H12 | Media | Resolución de FieldError en FormField. | Resuelto | [#25](https://github.com/edsel9ra/bracket-craft/pull/25). `frontend/app/components/ui/FormField.vue:8,14` usa e importa explícitamente FieldError. Guardián `frontend/tests/ui-component-imports.test.ts:20,25,30,36`: casos válido, vacío, erróneo y barrido de plantillas. |

### Controles adicionales de mantenimiento

- **ESLint gradual — Mitigado, #27:** `frontend/eslint.config.mjs:5–17`
  desactiva temporalmente **12 reglas**. `pnpm run lint` ejecuta
  `nuxt prepare && eslint .`; CI lo exige en `.github/workflows/ci.yml:108`.
  La adopción y las justificaciones están en `docs/mantenimiento-auditoria.md`.
- **Bandit — Resuelto como control CI, #27:** versión **1.9.4** fijada en
  `backend/requirements-dev.txt:5`; comando `bandit -r app -ll` en
  `.github/workflows/ci.yml:181–183`. El umbral es medio/alto, no ausencia de
  cualquier hallazgo: el informe conserva 13 bajos y 10 supresiones específicas.
- **Gitleaks — Mitigado, #27:** imagen 8.30.1 fijada por digest; árbol versionado
  actual exportado, sin historial ni archivos locales no versionados. No es una
  limpieza retroactiva de secretos históricos. La comprobación real fue el CLI,
  no un test unitario del escáner.

## Verificación ejecutada

Todos los comandos siguientes se ejecutaron contra el contenido de `main`
`6502d6b`, antes de escribir este informe. No se ejecutó la suite opt-in con
`RUN_DATABASE_TESTS=1`, ni se repitió el E2E completo, ni una revisión visual.

### Backend y Bandit

Contenedor con Python 3.14.10, repositorio montado en `/repo`,
directorio `/repo/backend`:

```sh
ruff check . && pytest -q && bandit -r app -ll
```

```text
All checks passed!
2211 passed, 480 skipped, 3 warnings in 7.88s
No issues identified.
Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 10
Low: 13
Medium: 0
High: 0
```

Cadena con salida **0**. Los tests parametrizados de H2 ejecutados incluyen
rechazo de `192.0.2.10/24`, `0.0.0.0/0`, `::/0` y `*`, y aceptación de
`192.0.2.0/24` y `192.0.2.10, 198.51.100.7`.
Las tres advertencias pytest son deprecaciones existentes de
`HTTP_413_REQUEST_ENTITY_TOO_LARGE`. Bandit emite advertencias
`nosec encountered (B608), but no failed test` en expresiones SQL suprimidas;
son avisos del escáner, no fallos del comando. `bandit --version` confirmó 1.9.4.

### Frontend

Contenedor `node:24`, pnpm 12.12.1, repositorio completo montado (incluye backend
para el test del catálogo), directorio `/repo/frontend`:

```sh
pnpm install --frozen-lockfile && pnpm run lint && pnpm test
```

```text
Lockfile is up to date, resolution step is skipped
Done in 2.3s using pnpm v12.12.1
$ nuxt prepare && eslint .
◆ Types generated in .nuxt.
ℹ tests 783
ℹ pass 783
ℹ fail 0
ℹ skipped 0
```

Cadena inicial con salida **0**. Build/typecheck no se ejecutaron en esa
comprobación inicial; sí en el seguimiento de H6 descrito a continuación.

### Dependencias frontend: seguimiento de H6 mitigado

La auditoría inicial detectó 1 advisory bajo y 2 moderados. En [este PR](https://github.com/edsel9ra/bracket-craft/pull/37)
se añaden overrides acotados en `frontend/pnpm-workspace.yaml`: `glob@13` a
`^14.0.2` y `minimatch@10` a `^11.0.1`. El lockfile resuelve **glob 14.0.4**
(GHSA-3g3m-2fjr-6pw4 corregido) y **minimatch 11.0.5**
(GHSA-g3hv-75wg-m249 corregido), sin cambiar las dependencias directas.
Retirar los overrides cuando `@vercel/nft` y ESLint declaren glob >=14 y
minimatch >=11, comprobando también los demás consumidores transitivos.

Permanece **deepmerge 4.3.1**, severidad baja, GHSA-gcqx-w48m-w2h4:
`pnpm audit --json` informa `patched_versions: null` y
`patched_versions_unpublished: true`. En el grafo instalado solo entra por las
herramientas de build: Nuxt → Nitro → `@rollup/plugin-node-resolve` → deepmerge.
Antes de aplicar los overrides se construyó `main` en `988a46b`: no aparecen
directorios llamados deepmerge, glob o minimatch, ni referencias textuales a esos
nombres completos en `frontend/.output/`, ni en su manifiesto de dependencias
runtime. La imagen de producción copia solo `.output`
(`frontend/Dockerfile:20`), no el `node_modules` del build. Esta inspección estática
no es una prueba formal de ausencia de código integrado/minificado, ni elimina
el riesgo durante la construcción.

Con Node 24 y pnpm 12.12.1, `pnpm audit` termina con salida **1**:

```text
1 vulnerabilities found
Severity: 1 low
```

El único hallazgo es deepmerge. `pnpm audit --prod --json --audit-level low`
también termina con salida **1**, con ese único advisory. Se ejecutó el filtro
de CI, sin cambiar su política:

```sh
python3 infra/scripts/audit_frontend.py --input audit-prod.json --pnpm-status 1
```

Salida **0**:

```text
Sin hallazgos accionables (>= high con corrección publicada).
Hallazgos no accionables visibles: 1
- NO ACCIONABLE GHSA-gcqx-w48m-w2h4 paquete=deepmerge severidad=low versiones_afectadas=>=4.2.0 <=4.3.1 motivo=sin corrección publicada
Dependencias auditadas: 523
Informativos contabilizados: 0
Resultado: OK
```

Verificación final del frontend con los overrides, cadena con salida **0**:

```sh
pnpm install --frozen-lockfile && pnpm run lint && pnpm test && pnpm run typecheck && pnpm run build
```

```text
Lockfile is up to date, resolution step is skipped
Done in 1.6s using pnpm v12.12.1
$ nuxt prepare && eslint .
◆ Types generated in .nuxt.
ℹ tests 783
ℹ pass 783
ℹ fail 0
ℹ skipped 0
$ nuxt prepare && vue-tsc --noEmit
◆ Types generated in .nuxt.
◆ ✨ Build complete in 8.94s!
```

Estas verificaciones no detectaron incompatibilidades con los saltos transitivos;
no se ejecutaron E2E ni pruebas funcionales del artefacto servido en este seguimiento.
Los advisories cambian con el registro; estos resultados no garantizan ejecuciones futuras.

### Infraestructura, pins y árbol sin secretos

Desde la raíz, renderizado real de desarrollo y validador en Python 3.14:

```sh
docker compose --env-file .env.example config --format json | \
  docker run --rm -i -v "$PWD:/repo:ro" -w /repo python:3.14-slim \
  python infra/scripts/check_env_contract.py
```

```text
OK: contrato de configuración cumplido (7 servicios, 52 variables documentadas, perfil: development)
```

Conteo con `re.findall(r'uses:\s*([^\s]+)', workflow)` y comprobación completa
`re.fullmatch(r'[^@]+@[0-9a-f]{40}', referencia)`; conteo de valores `'off'`:

```text
uses=14, SHA40=14
ESLint reglas off=12
```

Exportación `git archive HEAD` a un directorio vacío y ejecución del mismo escáner
que CI, con salida **0**:

```sh
docker run --rm -v "$TREE:/repo:ro" \
  zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f \
  dir /repo --config /repo/.gitleaks.toml --redact
```

```text
scanned ~10616575 bytes (10.62 MB) in 1.38s
no leaks found
```

`git rev-parse --is-shallow-repository` devolvió `false` y
`git rev-list --max-parents=0 HEAD` conserva la raíz
`8b3f15f638f52fbbf9045d2c5ec1177d084516f2`. No se reescribió historial en esta
ronda. Las detecciones históricas y su aceptación proceden de la auditoría inicial; no se
volvieron a inspeccionar ni reproducir sus valores.

### Medición orientativa de Argon2

Script Python local que importa `hash_password`, `verify_password` y
`DUMMY_PASSWORD_HASH`, genera un hash real con los parámetros actuales y verifica
una contraseña incorrecta contra ambos. Diez muestras por hash, alternando orden;
se comprobó respuesta `False` en las veinte llamadas. No imprime hashes ni claves.

```text
dummy: n=10, median_ms=61.46, min_ms=40.89, max_ms=85.24
real: n=10, median_ms=54.69, min_ms=39.95, max_ms=81.82
median_ratio_dummy_real=1.124
```

Ambos costes son del mismo orden en este contenedor, con variación apreciable.
No es una prueba estadística de indistinguibilidad, ni mide login HTTP, consulta
de usuarios, red o rate limit. El test determinista de H5 fija el uso del
verificador y los parámetros, no la igualdad exacta de latencias.

### Reorganización de torneos: seguimiento de H10 resuelto

En [este PR](https://github.com/edsel9ra/bracket-craft/pull/38) se extraen `access.py` y los subrouters de torneos,
versiones, fases, equipos, plantillas, calendario y público. La fachada usa
`APIRouter()` y aplica `prefix="/tournaments", tags=["tournaments"]` en cada
`include_router`, en ese orden. El prefijo explícito evita el rechazo de FastAPI
a las dos rutas raíz con path vacío. `main.py` no cambia; no hay consumidores
del prefijo/tags de la fachada. `crests/service.py` importa `_ensure_tournament`
desde `access.py`. La fachada no reexporta handlers ni helpers y no se introducen
imports circulares.

La comparación de AST y texto verifica que las **63 funciones/clases** movidas,
incluidos decoradores y firmas, son idénticas a `main` en `5bf526c`. Solo se
ajustan imports y registro; los módulos con logs conservan explícitamente
`app.modules.tournaments.router`. Se migran los imports/monkeypatches de tests
a los módulos dueños y los tres contratos estáticos de estadísticas/proyección
interna a `routes/public.py`, sin relajar sus aserciones. Las specs históricas
permanecen intactas.

Se vuelca `api.openapi()` sin BD ni red y se compara con la base, normalizando
ambos JSON con claves ordenadas. El inventario efectivo se compara como conjunto
de path/métodos/nombre y se verifica el orden de todos los pares que se solapan:

```text
Movimiento mecánico: AST y texto de 63 funciones/clases idénticos, incluidos decoradores
OpenAPI diff: ''
Inventario efectivo (conjunto) diff: ''
Orden de colisiones preservado: 5 pares
Importación de api: OK
```

Se permite el nuevo orden global por subdominio; se conservan métodos, paths,
operationIds, tags, modelos y demás contenido del OpenAPI normalizado. El nuevo
test `test_tournament_routes_order.py` fija las 31 operaciones y comprueba mediante
una petición ASGI que `GET /api/v1/tournaments/public/teams` sigue seleccionando
`list_tournament_teams`, antes de la ruta pública.

Con Python 3.14.10, `ruff check . && pytest -q -p no:cacheprovider` desde backend,
salida **0**:

```text
All checks passed!
2213 passed, 480 skipped, 3 warnings in 8.00s
```

No se ejecuta `ruff format`: el repositorio no lo configura ni lo usa en CI;
formatear los cuerpos impediría verificar el movimiento textual mecánico.

Suite completa con `RUN_DATABASE_TESTS=1`, PostgreSQL 17 aislado sin puertos
publicados, rol de aplicación y rol administrador de pruebas, inicialización y
las **32 migraciones** aplicadas como en CI. `pytest -q -p no:cacheprovider`,
salida **0**:

```text
2688 passed, 5 skipped, 7 warnings in 217.53s (0:03:37)
```

Las advertencias corresponden a la deprecación de `HTTP_413_REQUEST_ENTITY_TOO_LARGE`
y, con BD, a `SAWarning: transaction already deassociated from connection`.
`bandit -r app -ll`, salida **0**:

```text
Test results:
    No issues identified.
Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 10
Total issues (by severity):
    Undefined: 0
    Low: 13
    Medium: 0
    High: 0
```

Bandit conserva avisos `nosec encountered (B608), but no failed test`; no se
añaden supresiones. `wc -l` de los archivos de la reorganización:

```text
   77 backend/app/modules/tournaments/access.py
   22 backend/app/modules/tournaments/router.py
    0 backend/app/modules/tournaments/routes/__init__.py
 1717 backend/app/modules/tournaments/routes/matches.py
  514 backend/app/modules/tournaments/routes/public.py
  948 backend/app/modules/tournaments/routes/rosters.py
  585 backend/app/modules/tournaments/routes/stages.py
  403 backend/app/modules/tournaments/routes/teams.py
  104 backend/app/modules/tournaments/routes/tournaments.py
  681 backend/app/modules/tournaments/routes/versions.py
 5051 total
```

El alcance de H10 aquí es torneos: no se han dividido los routers de partidos,
invitaciones o identidad. No se ejecutan E2E ni pruebas visuales en este seguimiento.

## Requisitos de despliegue

1. Aplicar **migración 032 antes de arrancar la API actual**. La revalidación llama
   a `public.revalidate_socket_sessions`; el test puro no comprueba que la función
   ya exista en una BD de producción.
2. Definir **`FORWARDED_ALLOW_IPS` obligatoria**, sin default global: solo IP válidas
   o redes CIDR estrictas del proxy tal como las ve la API, sin bits de host,
   `*` ni `/0`. Ejemplo: `192.0.2.0/24`, no `192.0.2.10/24`. El comando exec
   preserva listas con coma y espacio. El proxy debe sanear `X-Forwarded-For` y
   `X-Forwarded-Proto`; no confiar en redes de clientes.
3. Permitir **upgrade WebSocket** hacia `/socket.io/`. El cliente no tiene
   fallback a polling; si el proxy bloquea WebSocket, falla la conexión. El relay
   Redis opera por proceso, sin manager compartido ni afinidad para polling.
4. Servir por HTTPS antes de habilitar HSTS: API lo emite fuera de los entornos
   de desarrollo definidos; Nuxt solo en producción. La política
   `max-age=31536000; includeSubDomains` también compromete a los subdominios.
   API/SSR añaden nosniff, DENY y Referrer-Policy; SSR añade la CSP mínima
   `frame-ancestors 'none'; object-src 'none'; base-uri 'self'`, sin restringir
   scripts inline ni conexiones. OAuth conserva su referente más restrictivo.

## Pendientes y riesgos aceptados

- **Deepmerge pendiente (H6 mitigado):** deepmerge 4.3.1 conserva el advisory bajo
  GHSA-gcqx-w48m-w2h4 sin corrección publicada, incluso con `--prod`. Entra por
  herramientas de build y no se identificó en `.output`; vigilar una corrección
  upstream. Glob/minimatch ya están corregidos mediante overrides, que deben
  retirarse cuando los padres declaren versiones corregidas compatibles.
- **H7 mitigado, historial sin reescribir (decisión del dueño):** el control actual
  evita nuevas detecciones en el árbol exportado, pero no elimina contenido de
  commits previos. Una allowlist de dummy no sería válida para credenciales reales.
- **ESLint:** las 12 reglas apagadas son deuda temporal, no una certificación de
  tipado/estilo completo. Su detalle y motivos permanecen en el documento de
  mantenimiento. Bandit `-ll` deja fuera los hallazgos bajos y conserva supresiones
  locales revisadas; Gitleaks solo inspecciona el árbol actual.
- **Límites de la comprobación inicial:** no probado con proxy real y varios workers, sin
  prueba de carga, sin E2E completo ni revisión visual, y sin ejecutar los tests
  opt-in con PostgreSQL. El seguimiento H10 sí ejecuta la suite completa con BD
  descrita más arriba. No se verificó un despliegue productivo ni su migración.
- Los resultados anteriores de `MEMORY.md` son históricos. Este informe registra
  la comprobación inicial de `main` y los seguimientos H6/H10 por separado;
  no convierte las ejecuciones omitidas en verificaciones satisfactorias.
