# Verificación 035 — PR A inerte

T1–T16 implementadas y verificadas; T17 con gates local/CI/revisión automatizada
verificados, fusión pendiente.
R32f permanece abierto: nada está conectado al relay.
No certifica PR B/C ni aceptación del usuario.

## T1 — Caracterización HTTP (D1)

Base de trabajo: `5155c365`. PostgreSQL 17 local, bases desechables con cadena
limpia hasta 054. Lecturas con `SET ROLE bracket_app`; únicamente preparación
de datos y DDL con administrador. Solo se sustituye identidad autenticada;
`get_auth_context`, las rutas, sus servicios y RLS son reales.

Comando equivalente desde backend, en `bc-t1-python` (Python 3.14):
`RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k http_baseline`.

```text
4 passed in 4.92s
```

Es caracterización: no corresponde inventar un rojo. Operación, lista y versión
concreta permiten miembro con rol sin permisos de escritura ni oficiales,
también con varios roles. Otro tenant y recurso inexistente devuelven el mismo
404. Operación admite partido no confirmado; las versiones exigen confirmación
(409) y versión existente (404). Plataforma sin membresía y miembro sin roles:
403. Todas las variantes del catálogo verifican partido/torneo mediante operación;
las rectificativas añaden versión legible y confirmación, sin permiso adicional.

Entorno: la imagen productiva `api` no incluye pytest. Se usa el contenedor de
pruebas existente `bc-t1-python`, con repo montado y dependencias de desarrollo;
URLs de pruebas inyectadas, nunca registradas. Intentos de arranque sin pytest o
sin URL administrativa no cuentan como rojo funcional.

## T2 — Catálogo (P1)

Base `5155c365`, cambios de trabajo. `pytest -q tests/test_realtime_policy.py -k catalog`:
rojo `6 failed, 10 passed in 0.12s` (ninguna variante reconocida); verde
`16 passed in 0.03s`. Logs `/home/ubuntu/f8-a-t2-{red,green}.log`.

## T3 — Sobre privado (P1)

Base `5155c365`, cambios de trabajo. `pytest -q tests/test_realtime_policy.py -k envelope`:
rojo `11 failed, 7 passed, 16 deselected in 0.08s`; verde
`18 passed, 16 deselected in 0.04s`. IDs divergentes y organizaciones inválidas
antes eran aceptados. Logs `/home/ubuntu/f8-a-t3-{red,green}.log`.

## T4 — Referencias (P1)

`pytest -q tests/test_realtime_policy.py -k references`: rojo
`2 failed, 9 passed, 34 deselected in 0.14s`; verde
`11 passed, 34 deselected in 0.07s`. Resolver inicialmente devolvía vacío para
referencias válidas. Logs `/home/ubuntu/f8-a-t4-{red,green}.log`.

## T5 — Proyección (P1)

`pytest -q tests/test_realtime_policy.py -k invalidation`: rojo
`1 failed, 5 passed, 45 deselected in 0.11s`; verde
`6 passed, 45 deselected in 0.03s`. No se producía la invalidación válida.
Logs `/home/ubuntu/f8-a-t5-{red,green}.log`.

## T6 — Agrupación (P3)

`pytest -q tests/test_realtime_policy.py -k recipients`: rojo
`8 failed, 2 passed, 51 deselected in 0.11s`. Logs
`/home/ubuntu/f8-a-t6-{red,green}.log`; verde `10 passed, 51 deselected in 0.09s`.

## T7 — Permisos (P2)

`pytest -q tests/test_realtime_policy.py -k permissions`: rojo
`9 failed, 2 passed, 61 deselected in 0.13s`. Predicado condicional solo en tests,
sin nuevos permisos de producto. Logs `/home/ubuntu/f8-a-t7-{red,green}.log`.

Verde T7: `11 passed, 61 deselected in 0.07s`.

## T8 — Tiempo explícito (P2)

`pytest -q tests/test_realtime_policy.py -k temporal`: rojo
`8 failed, 6 passed, 72 deselected in 0.24s`; verde
`14 passed, 72 deselected in 0.04s`. Igualdad de expiración deniega y dos
pestañas de una sesión conservan expiraciones JWT independientes.
Logs `/home/ubuntu/f8-a-t8-{red,green}.log`.

## T9 — Estado (P2/P3)

`pytest -q tests/test_realtime_policy.py -k recovery_state`: rojo
`3 failed, 86 deselected in 0.11s`; verde `3 passed, 86 deselected in 0.04s`.
Logs `/home/ubuntu/f8-a-t9-{red,green}.log`. Sin historial de recursos ni I/O.

## T10 — Identidad SQL (D1/D3)

Migración 055: siguiente número libre al iniciar. Solo se ha aplicado a bases
desechables; no se modifica ninguna migración persistida. Contextos excepcionales
se limpian y restauran; no se amplían SELECT ni políticas.
`RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k identity`:
rojo `1 failed, 7 passed, 4 deselected in 10.23s` (sesión válida denegada por
stub); verde `8 passed, 4 deselected in 12.41s`. Caso adicional de contextos y
plataforma real: `1 passed, 12 deselected in 2.40s`.
Logs `/home/ubuntu/f8-a-t10-{red,green,context}.log`.

## T11 — Recursos (D1)

`RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k resources`:
rojo `11 failed, 2 passed, 12 deselected in 14.26s` (solo se comprobaba identidad);
verde `13 passed, 12 deselected in 13.03s`. Se corrigió además la preparación del
caso de acta no confirmada: cambiar estado a scheduled para respetar
`chk_terminal_result` en la base desechable. No se cambió el resultado esperado.
Logs `/home/ubuntu/f8-a-t11-{red,green}.log`.

## T12 — Paridad multirrol (D1)

`RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k parity`:
`6 passed, 25 deselected in 7.53s`. Caracterización adicional: T10 ya exigía
roles efectivos y T11 lecturas concretas; no requiere cambio productivo adicional
ni se inventa un rojo. Retirada del último rol/concesión y de un rol entre dos,
sin permisos de escritura; añadir/quitar oficial irrelevante no retira lectura.
Las seis variantes se comparan contra HTTP con tenancy real. Predicado
condicional permiso/oficial tiene el rojo/verde puro de T7, sin evento nuevo.
Log `/home/ubuntu/f8-a-t12-parity.log`.

## T13 — Adaptador (S1/D2)

`pytest -q tests/test_realtime_delivery.py -k adapter`: rojo
`5 failed, 1 passed in 0.08s`; verde `6 passed in 0.04s`.
`RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k snapshot`:
rojo `1 failed, 31 deselected in 1.62s`; verde `1 passed, 31 deselected in 1.30s`.
Antes el adaptador devolvía cero decisiones incluso para principal autorizado.
Logs `/home/ubuntu/f8-a-t13-{red,green,db-red,db-green}.log`.

## T14 — Corte de commit (D2)

`RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k cutoff`:
`8 passed, 32 deselected in 7.80s`. Regresión sobre T13, sin nuevo código de
producto ni rojo artificial. Barreras asyncio después de adquirir snapshot
REPEATABLE READ y antes de autorizar: commit de retirada y luego continuación
de evaluación anterior permitida; siguiente lote del mismo evento denegado.
Sesión, expiración, membresía, último rol, usuario y organización; permiso y
oficial irrelevantes no retiran lectura. Rehabilitar membresía se ve enseguida.
Log `/home/ubuntu/f8-a-t14-cutoff.log`.

## T15 — Migración, salida parcial y contexto (D3)

Rojo real: candidato malformado reutilizaba la clave anterior y convertía su
ALLOW en INDETERMINATE; el adaptador invalidaba todo el lote ante fila sin clave.
`pytest -q tests/test_realtime_delivery.py -k migration`: rojo
`1 failed, 6 deselected in 0.06s`; verde `1 passed, 6 deselected in 0.03s`.
`RUN_DATABASE_TESTS=1 pytest -q tests/test_realtime_delivery_db.py -k migration`:
verde `3 passed, 40 deselected in 4.49s`. El log rojo contiene también dos fallos
de preparación por generador async en una aserción: no cuentan como rojo funcional.
Se comprueban invocador, grant mínimo, PUBLIC sin EXECUTE, FORCE/políticas
inalteradas y contexto tras transacción; caso T10 restaura contexto no vacío.
Logs `/home/ubuntu/f8-a-t15-{unit-red,unit-green,db-red,db-green}.log`.

Runner real en bases desechables, script externo `/home/ubuntu/f8-a-migrations.sh`:

```text
OK: 055 clean + reejecución idempotente; 55 checksums registrados
OK: 055 incremental + reejecución idempotente; 55 checksums registrados
OK: todas las pruebas de MIGRATION_TARGET pasaron
```

Logs `/home/ubuntu/f8-a-t15-runner.log`, `/home/ubuntu/f8-a-target-runner.log`.

## T16 — Agrupación y coste (L1)

`pytest -q tests/test_realtime_delivery.py -k batching`: rojo
`3 failed, 1 passed, 7 deselected in 0.09s`; verde
`4 passed, 7 deselected in 0.07s`.
`RUN_DATABASE_TESTS=1 pytest -q -s tests/test_realtime_delivery_db.py -k batching`:
verde `3 passed, 43 deselected in 4.17s`.

Rojo SQL: 100 sesiones de un usuario hacían 100 consultas de sesión, y 257 hacían
257. Se agrupan en una consulta por usuario/lote, como roles/recurso. El caso de
100 usuarios tuvo también un fallo de fixture por nombre de rol duplicado; no
se cuenta como rojo funcional. Instrumentación de bloques de consulta mediante
NOTICE añadidos **solo en la base desechable**, no en la migración/producto:

```text
L1 principals=100 users=100 calls=1 blocks={'member': 100, 'resource': 100, 'sessions': 100} seconds=0.2861
L1 principals=100 users=1 calls=1 blocks={'member': 1, 'resource': 1, 'sessions': 1} seconds=0.0093
L1 principals=257 users=1 calls=2 blocks={'member': 2, 'resource': 2, 'sessions': 2} seconds=0.0308
```

1.000 sockets/100 principales: una llamada autorizadora; 257 principales: dos.
Más cuatro sentencias constantes por transacción/lote (aislamiento, timestamp,
dos GUC). El generador no abre la transacción siguiente antes de consumir el
lote anterior. Medidas locales, no SLO; las consultas internas de políticas RLS
y planes de ejecución no están contadas separadamente. SQL **no es O(1)**:
el coste depende de usuarios, sesiones y relaciones, pero no de pestañas.
Logs `/home/ubuntu/f8-a-t16-{unit-red,unit-green,db-red,db-green}.log`.

## T17 — Gate local, CI y Devin Review verificados; fusión pendiente

PR #76 abierto. T17 exige también fusión: esa parte permanece pendiente y la
casilla principal sigue abierta. No hay ningún import nuevo en
`main.py`/relay/worker ni cambios de frontend. PR A no activa F8 ni cierra R32f.

### Checks locales (Python 3.14/PostgreSQL 17)

- Sin base: `pytest -q` → `2618 passed, 934 skipped in 9.50s`.
- Con PostgreSQL: `RUN_DATABASE_TESTS=1 pytest -q` →
  `3552 passed in 637.37s (0:10:37)`, sin omisiones.
- `ruff check .` → `All checks passed!`.
- `python -m compileall -q app` → exit 0.
- `bandit -r app -ll` → `Medium: 0`, `High: 0`, `Files skipped (0)`;
  12 low, fuera del umbral constitucional, sin nuevas exclusiones.
- `pip-audit -r backend/requirements.txt -r backend/requirements-dev.txt` →
  `No known vulnerabilities found`.
- Infraestructura CI: `OK: infraestructura CI desarrollo + producción, contratos,
  versiones y shell`. Incluye contrato/self-test, estructura Compose real en
  ambos perfiles, Compose 5.6.1, versiones fuente y sintaxis de ambos scripts.
- Runner definitivo tras optimizar 055: limpio e incremental 054→055,
  reejecución idempotente, 55 checksums. El test existente MIGRATION_TARGET
  también verde; no se modificó su script.
- Auditoría pnpm de producción: `Dependencias auditadas: 524`, `Resultado: OK`.
  Se conservan visibles cinco avisos no accionables (4 node-forge moderate/low;
  1 deepmerge low sin parche), sin exclusiones nuevas.
- Trivy 0.70.0 sobre snapshot del índice (sin `.env`/artefactos locales), con
  `--ignore-unfixed --severity CRITICAL,HIGH --exit-code 1`: cero vulnerabilidades
  en requirements y lockfile, cero secretos detectados. Mismo código de producto
  y tests; solo se añade evidencia documental después del escaneo.
- Gitleaks: se ejecuta sobre `git archive HEAD` del commit final; el resultado
  se informa en la entrega para no afirmar un escaneo de HEAD antes de crearlo.

Logs `/home/ubuntu/f8-a-{backend-unit,backend-full-final,bandit,pip-audit,
infrastructure,pnpm-audit,trivy}.log`, `/home/ubuntu/f8-a-t17-runner-final.log`.

### Incidencia de entorno y alcance

La primera suite PostgreSQL se interrumpió al detectar fallos de autenticación
del rol de aplicación, no como rojo funcional. El runner MIGRATION_TARGET
existente cambia la contraseña global de `bracket_app` a la de test (líneas
144–145); sus bases son desechables, pero el rol es de clúster. Se restauró la
configuración local original con `00_roles.sh`, sin editarlo ni cambiar secretos,
y se comprobó conexión real como `bracket_app` antes de relanzar la suite.
No se han editado CI, configuración compartida ni migraciones 001–054.

Python del host es 3.10: el análisis AST de inercia se hizo con Python 3.14 del
contenedor de tests. El host necesitó cargar NVM para la auditoría pnpm (Node 24).
La imagen API productiva no lleva pytest; se reutiliza `bc-t1-python`.

Prueba AST con Python 3.14: ningún módulo productivo importa el núcleo/adaptador
nuevo fuera de los dos archivos nuevos. Diff frente a `origin/main`: relay,
worker, frontend, init y migraciones 001–054 intactos. No hay nuevo contrato HTTP,
emisión, dependencia ni flag de activación. README/AGENTS/manual quedan para B/C,
como el plan: no se sustituye su descripción observable actual prematuramente.

No se ejecutaron frontend ni E2E locales: no hay cambio de su superficie ni del
relay. Sí se verificaron en CI como consta a continuación. No se certifican
verificación visual, aceptación humana, fusión, despliegue coordinado ni F8 activo.

### CI y revisión remotas de PR #76 — 2026-11-13

SHA funcional revisado: `d43722274759583d03ca13fb73f504b3c9056066`.
`git_pr_checks(wait_mode="all")` terminó con:

```text
Summary: 7 passed, 0 failed, 0 pending, 0 skipped
```

| Evento | Run | Resultado |
|---|---|---|
| `pull_request` | [43462708237](https://github.com/edsel9ra/bracket-craft/actions/runs/43462708237) | success; cinco jobs verdes, incluido E2E |
| `push` | [43462371097](https://github.com/edsel9ra/bracket-craft/actions/runs/43462371097) | success; cuatro jobs verdes, E2E omitido por condición prevista |

Logs remotos:

```text
Backend PR:   3548 passed, 4 skipped in 834.23s (0:13:54)
Backend push: 3548 passed, 4 skipped in 858.15s (0:14:18)
Frontend PR/push: tests 952; pass 951; fail 0; skipped 1
Build PR:   Build complete in 11.7s!
Build push: Build complete in 11.8s!
E2E PR: 54 passed (5.8m); RESULTADO: VERDE (0)
```

Devin Review, review `5894554689` en ese SHA: «No Issues Found». API de
`review_comments`: cero eventos, última página. No hubo hallazgos reales que
corregir, falsos positivos que descartar ni fallos de CI. Se mantienen sin cambios
el código funcional y los tests; esta actualización solo registra evidencia.

Logs descargados en `/home/ubuntu/f8-pr76-initial-{pr,push}.log`. El commit
documental posterior se vuelve a comprobar por CI; su resultado final se informa
en la entrega, sin dar por fusionado el PR ni cerrar R32f.

## PR B — T18 verificada; integración pendiente

El usuario confirmó el desglose interno T32a–c/T34a–c el 2026-11-13,
sin cambiar alcance, C4 ni el PR B único. Consta en `tasks.md`. La inyección
de fallos queda restringida a pruebas; no se ha añadido ninguna al producto.

T18: `SocketRegistry` indexa organización/principal/sid y limpia reemplazos,
bajas y vaciado. El handshake conserva generación nueva y expiración del JWT
ya verificado. Los nuevos metadatos se serializan para el mantenimiento 032.

```text
Rojo inicial: 2 failed, 11 deselected in 0.67s
Verde T18 final: 6 passed, 11 deselected in 0.67s
Regresión política/adaptador/revalidación: 106 passed in 0.69s
Suite final sin PostgreSQL: 2624 passed, 934 skipped in 8.19s
Ruff de archivos Python cambiados: All checks passed!
compileall app: exit 0
```

Casos nuevos: dos pestañas de una sesión, generación nueva al reconectar,
expiración proveniente del token, sustitución de tenant, limpieza al desconectar
y vaciar, organización sin conexiones y claims ausentes/malformados.

Antes de integrar el relay se detectó que falta una primitiva de contexto para
los controles de C3 (§6.2 del plan), que no deben depender de un partido:

```text
context_api_present: False
resource_free_decision: DENY
database_calls: 0
```

Comprobación ejecutada con `RealtimeAuthorizer.evaluate_batch(None, principals)`
y el harness unitario existente. `realtime_authorization.py:40–48` solo acepta
un evento clasificado con referencias. La función 055 exige partido y torneo
(`055_realtime_delivery_authorization.sql:34–51`), y versión para variantes
privadas. No basta con invocarla sin evento para recuperar un contexto. La 032
compara la huella guardada con la vigente; no sustituye a un gate de contexto
que compruebe la membresía/roles actuales sin usar esa huella como permiso.

Propuesta histórica, descartada por el usuario el 2026-11-13: migración 056 append-only con función de
contexto batch `SECURITY INVOKER`, snapshot fresco, límite 256, contexto RLS por
usuario y sin recurso. Sin editar 055, BYPASSRLS, caché, tablas nuevas ni cambios
en permisos HTTP. Implica comprobar migración limpia y 055→056 y ejecutar E2E
con la 056 aplicada, además de la 055 indicada en el brief. No se implementó
esa extensión ni se cambió el plan unilateralmente.

T19–T37 siguen pendientes: sin gate conectado, cambio de emisiones, frontend,
arnés de fallos ni nuevos endpoints. No se ejecutaron PostgreSQL, frontend,
E2E ni gates completos de infraestructura en este avance parcial. No equivale
a PR B terminado, activación de F8 ni cierre R32f.

## PR B — T19–T26, recuperación con 032 (2026-11-13)

La precisión de C3 reutiliza 032; no se añade 056 ni se modifica ninguna
migración. La interpretación anterior queda sustituida: el control no concede
acceso a negocio y la huella vigente de 032 basta para ese control. La lectura
HTTP y cada entrega posterior siguen autorizándose por separado.

`PrivateDelivery` conecta el adaptador 055 al relay: clasificación cerrada,
evaluación fresca por lote de principales, wire de tres IDs y envío solo a sid.
El carril público se ejecuta antes de comprobar privados y conserva contrato y
rooms. Desconocidos, sonda, F1, F9 y correo no tienen intención de entrega.
El cursor avanza en fallos privados, sin guardar IDs/eventos; la marca solo
contiene generación y estado de control. Se revalida contexto con 032 antes de
un nuevo evento permitido o en el mantenimiento de 30 s, sin evento adicional.
Filas ausentes/errores de 032 y errores de envío conservan la suspensión.
Sesión/JWT, membresía o huella retiradas no reciben RESYNC. JOIN, arranque,
recorte y reset privados pasan la misma comprobación dirigida; público intacto.

Se conservan las tres filas/IDs de rectificación y `scope/version_id` internos,
sin timestamp nuevo. Filas históricas con timestamp siguen siendo clasificables;
el wire omite timestamp/versión. Snapshots de metadatos y comprobación de contexto
y generación justo antes de emitir descartan resultados de conexiones antiguas.

Rojo observado antes de implementación:

```text
13 failed, 17 deselected in 0.19s
ModuleNotFoundError: No module named 'app.core.realtime_delivery'
1 failed, 46 deselected in 1.56s
Extra items in the left set: 'rectified_at'
```

Resultados finales de este tramo:

```text
Unitarios dirigidos relay/control/sonda/worker: 177 passed in 0.92s
Unitarios finales con nuevas matrices de control: 100 passed, 7 skipped in 0.83s
Backend completo sin PostgreSQL: 2673 passed, 940 skipped in 8.66s
PostgreSQL test_realtime_delivery_db.py: 52 passed in 43.73s
PostgreSQL rectification_notifications + rectification_effects: 66 passed in 51.54s
Ruff: All checks passed!
compileall app: exit 0
Bandit -ll: No issues identified. Low: 12; Medium: 0; High: 0
```

Una preparación inicial de los nuevos tests DB omitía fijar RLS antes de cargar
la huella: 032 denegó correctamente el contexto vacío. Corregida la fixture
para obtener la huella como el handshake real; los cinco casos finales pasan.
Las regresiones que esperaban broadcast organizativo se ajustaron al contrato
aprobado (sin fallback); ninguna lectura HTTP ni autorización se endureció.

PostgreSQL dirigido usa el cluster local aislado `bc-f9-postgres` (5540) y el
rol real `bracket_app` mediante SET ROLE, sin ejecutar MIGRATION_TARGET ni
alterar contraseñas de aplicación. No hay inyección de fallo productiva.

Al cerrar este tramo, T27–T37 seguían pendientes: frontend, E2E real T32/T34, gates PostgreSQL completo,
frontend/infra/security finales, despliegue documentado y CI/revisión. Este estado
intermedio no se despliega ni acredita PR B completo, aceptación F8 o cierre R32f.

## PR B — T27–T36 y gate local T37 (2026-11-13)

T19–T26 quedaron publicados previamente en `a19c086e`. Este tramo completa el
frontend y las pruebas reales, sin nueva migración ni cambio de C1–C4:

- `useRealtime`: generaciones de socket/contexto, identidad dentro de la clave
  privada y descarte de callbacks/manager/timers antiguos; público conserva su socket.
- Operación y Workspace: `useApi`, protección de GET/errores y carga inicial obsoletos,
  limpieza ante denegación actual, lectura terminal y una intención trailing durante
  acción ocupada. Se conservan controles de escritura y borradores clásico/táctico.
- `realtime-private-context.test.ts`: 17 escenarios funcionales de composables/stores
  reales ejecutados en VM, incluidos contexto vacío/ABA, terminal, acción exitosa o
  fallida, respuestas fuera de orden, desmontaje y denegaciones 401/403/404.
  Los primeros 14 se escribieron antes de implementar; tres regresiones adicionales
  amplían contexto vacío, trailing tras cambio de contexto y respuesta tras desmontaje.
  El rojo inicial incluía `h.realtime.captureContext is not a function` y `0 !== 1`
  en recargas terminales/ocupadas. No se contabilizan como rojo funcional los fallos
  de preparación del harness ni el ajuste de firma exigido por un test fuente existente.
- E1/E2 en `e2e/private-realtime.spec.ts`, proyecto propio dentro del gate completo:
  sesiones HTTP reales con CSRF, dos tenants, dos pestañas, multirrol, permisos vacíos,
  retirada de oficial no requerido, payload mínimo, sonda excluida y paridad HTTP.
  Captura `framereceived` antes del dispatcher; en los tres cortes de revocación usa
  transporte Engine.IO/Socket.IO real sin UI para que una navegación por GET denegado
  no cierre el socket antes de observar la evaluación posterior. La recuperación sí
  usa el frontend real. Barreras IPC antes/después de SQL verifican tránsito aprobado,
  retirada confirmada de rol/membresía/sesión y concesión/restablecimiento posterior
  (sesión revocada: nuevo login, nunca desrevocar la anterior).
- Fallo exclusivo de autorización y fallo independiente de 032: el válido sigue
  conectado, el revocado no recibe RESYNC, la recuperación ocurre sin evento nuevo ni
  replay y actualiza el marcador terminal por GET sin habilitar edición. Cambio real
  de organización durante la suspensión reconstruye solo el contexto vigente; el
  receptor público sigue recibiendo su contrato anterior.
- Arnés en `backend/tests/realtime_e2e_server.py`, IPC ignorado en `.auth/realtime`,
  guardado por DEVELOPMENT_ENVS antes de instalar adaptadores. Sin ruta productiva
  ni opción operativa de producción. Cadencia de dos segundos solo allí; producto
  conserva 30. El override E2E cambia únicamente entrypoint/mount; CI añade ese
  override en una línea y el runner local lo reutiliza. Las fixtures se archivan al
  acabar para no contaminar el descubrimiento público de las regresiones existentes.
- README/AGENTS enlazan el runbook coordinado: 055 previa, retirar todos los API
  antiguos y sus WebSockets, frontend actualizado, filas históricas compatibles,
  ningún rollback a broadcast y ninguna eliminación/rebobinado de outbox/migraciones.

Resultados locales finales:

```text
RUN_DATABASE_TESTS=1 pytest -q: 3617 passed in 650.81s (0:10:50)
pytest -q tests/test_realtime_e2e_fixture.py: 4 passed in 1.25s
pytest -q tests/test_realtime_delivery.py -k rollout: 2 passed, 64 deselected in 0.85s
Ruff: All checks passed!
compileall -q app: exit 0
Bandit -r app -ll: Low 12, Medium 0, High 0
pnpm test: tests 969; pass 968; fail 0; skipped 1
pnpm run typecheck: exit 0
pnpm run lint: exit 0
pnpm run build: Build complete in 11.0s!
pnpm run typecheck:e2e: exit 0
pnpm run e2e:test: 59 passed (5.2m); RESULTADO: VERDE (0)
Infraestructura CI desarrollo + producción, contratos, versiones y shell: OK
055 clean + reejecución idempotente; 55 checksums registrados: OK
055 incremental + reejecución idempotente; 55 checksums registrados: OK
todas las pruebas de MIGRATION_TARGET: OK
pip-audit: No known vulnerabilities found
pnpm audit: Dependencias auditadas 524; Resultado: OK
Gitleaks snapshot de trabajo: no leaks found
Trivy snapshot de trabajo: requirements.txt 0; pnpm-lock.yaml 0; secrets 0
git diff --check: exit 0
```

pnpm muestra cinco avisos no accionables (node-forge moderate y deepmerge low sin
corrección); no hay excepciones nuevas. El build conserva el aviso preexistente
`Cannot extract styles ... operation.css ... Its styles will not be inlined when
server-rendering`, también presente en los logs B2/C: Node 24/Nuxt preparados y
build correcto; no se cambian estilos ni se aplica un workaround de entorno.

El seed de la pila reutilizada abortó por avance demo SF1 modificado por pruebas
anteriores (`RuntimeError: El avance de SF1 no coincide con el estado demo esperado`).
Se descartó esa corrida de preparación y se creó `bc_f8_b_e2e_verified`, con init real,
migraciones 001–055, seed real y API/worker Compose dirigidos a ella sin editar `.env`.
Ahí pasó el gate completo de 59 pruebas, no solo las cinco nuevas. La suite backend
usó la base original del cluster local y terminó con 3617 pass sin skips. El runner
Node/Playwright no lleva Docker CLI: su `server.log` lo declara; los logs API/worker
se recogieron desde el host en `/home/ubuntu/f8-b-e2e-server.log`. Gates y salidas
persistentes están en `/home/ubuntu/f8-b-*.log`, fuera del repositorio.

MIGRATION_TARGET y la matriz clean/incremental se ejecutaron en el cluster aislado
`bc-f9-postgres` (5540), no en el de la suite/Compose; se restauró su rol mediante
`00_roles.sh`. No se interrumpió la suite ni se sustituyeron credenciales por comando.
Los ajustes de preparación E2E (permisos IPC, hints de identidad del frontend tras
login HTTP, CSRF/origen, dominio de correo válido y selector terminal correcto) no
son rojos funcionales del producto. E1/E2 se construyeron sobre backend T19–T26 ya
verde; no se afirma un rojo E2E de autorización anterior a ese backend.

Sin nueva UI/copy ni cambios visuales: se conservaron regresiones ES/EN, teclado,
tema y axe dentro del gate, pero **no se realizó inspección visual manual**.
T1–T36 verificadas; T37 mantiene CI PR/push, revisión y fusión pendientes del PR
que abrirá el usuario. No hubo despliegue productivo, PR nuevo, cierre R32f ni
aceptación F8; F1 y F9 mantienen sus restricciones.

## PR #77 — CI y rollback de organización (2026-11-13)

Antes del fix se comprobó HEAD exacto `3abdfbe502ac965fc8f6bbbeba3f3868523a0b4f`.
El hallazgo comunicado de Devin Review era real y alcanzable: WorkspaceShell
escribe la organización tentativa antes de `verifyWorkspace`; ante un error distinto
de 401/404 restaura la organización original sin desmontar la página de partido.
`verifyWorkspace` no cambia sessionVersion en ese camino. El watch limpia la
operación, pero el closure de generación inicial queda invalidado para siempre,
incluso cuando la clave vuelve a ser la original.

Dos nuevos tests con watch real de Vue reproducen A → B → A, sin recarga en B,
con GET anterior que termina correctamente o con 403 después del rollback:

```text
failed organization switch restores the mounted match with fresh HTTP, not stale responses (error=false)
AssertionError: 1 !== 2
failed organization switch restores the mounted match with fresh HTTP, not stale responses (error=true)
AssertionError: 1 !== 2
```

Fix separado `57cf9f517cbce90f05d43f23eb948892fede2f95`, un push funcional:
`useMatchOperation` conserva la clave del contexto montado, recaptura generación y
solicita recarga solo cuando vuelve esa misma clave. Cambiar identidad, sesión u
organización no permite reutilizar la operación original; incrementar la generación
de GET al cambiar contexto sigue descartando respuestas y denegaciones antiguas.
Los tests verifican recarga automática, estado recuperado, invalidaciones posteriores
y ausencia de redirección por el 403 obsoleto. Se comprobó además el orden real de
watchers Vue: socket incrementa generación antes de recapturar el contexto restaurado.

Validación local del fix:

```text
pnpm test: tests 971; pass 970; fail 0; skipped 1
pnpm run typecheck: exit 0
pnpm run lint: exit 0
pnpm run build: Build complete in 10.4s!
git diff --check: exit 0
```

CI del SHA funcional, esperado con `git_pr_checks(wait_mode="all")` y comprobado
también por evento mediante la API de Actions:

| Evento | Run | Resultado |
|---|---|---|
| pull_request | 43486317643 | success, cinco jobs correctos |
| push | 43486306264 | success, cuatro jobs correctos; E2E omitido por condición existente |

```text
Summary: 7 passed, 0 failed, 0 pending, 0 skipped
Backend PR: 3613 passed, 4 skipped in 858.68s (0:14:18)
Backend push: 3613 passed, 4 skipped in 628.01s (0:10:28)
Frontend PR: tests 971; pass 970; fail 0; skipped 1
Build PR: Build complete in 14.6s!
E2E PR: 59 passed (6.5m)
RESULTADO: VERDE (0)
```

Los cinco escenarios de `private-realtime` aparecen verdes en el log CI, incluidos
los tres cortes de retirada y recuperación 032/terminal/contexto/público. No hubo
fallos de CI que corregir: el cambio funcional responde al hallazgo de revisión.
GitHub devuelve cero comentarios inline/reviews y Devin Review indica success,
`Completed analysis in 1m 31s`. El hallazgo recibido fue corregido; no se descartó
ningún falso positivo. La página externa de revisión no devuelve texto por webfetch,
por lo que no se afirma una auditoría de contenido adicional a los comentarios
GitHub y al hallazgo transmitido. Sin inspección visual manual nueva.

Este cierre documental marca únicamente gate local, CI y revisión automatizada de
T37. La casilla global y su fusión siguen abiertas; no se fusionó #77 ni se inició C.

## Corrección del historial de versiones — 2026-11-13

Carencia preexistente comprobada en `main` ae0ac998 y HEAD fca81f38: el historial
solo cargaba al montar, cambiar de partido o pulsar Actualizar. La operación sí se
actualizaba en B, pero el componente independiente no recibía una invalidación.

La página pasa la identidad reactiva de la operación aceptada como `refreshKey`;
el historial vuelve a consultar `api.versions` mediante `useApi`. No se cambia su
key, no hay nuevo socket/listener de MATCH_REPORT_RECTIFIED ni cambios del wire.
Mientras se edita, conserva el editor y su versión base; consolida las señales en
una lectura al terminar/cancelar. Abrir el editor también invalida una lectura ya
pendiente, sin aplicar su resultado al borrador. Las generaciones descartan
resultados/errores antiguos y posteriores al desmontaje; cambiar partido limpia
el historial y una denegación HTTP vigente 401/403/404 elimina el detalle previo.

Rojo antes de implementar: rectification-components, 15 tests, 9 pass, 6 fail,
AssertionError `1 !== 2` (y `1 !== 3` para las lecturas concurrentes). Los E2E
contra la imagen anterior reproducen ambos casos: tras publicar y tras RESYNC,
`Expected: "2"`, `Received: "1"`. Se excluyen del rojo las preparaciones inválidas
(API normal sin arnés, frontend baseline sin URL interna) y un selector ambiguo
del motivo, corregidos antes de acreditar el fallo funcional.

Verde local del fix:
```text
Frontend: tests 979; pass 978; fail 0; skipped 1
Typecheck: nuxt prepare && vue-tsc --noEmit (exit 0)
Lint: nuxt prepare && eslint . (exit 0)
Build complete in 10.9s!
E2E types: tsc -p e2e/tsconfig.json (exit 0)
60 passed (5.3m)
RESULTADO: VERDE (0)
```

Ocho regresiones de componente cubren actualización/vacío, editor abierto y
lectura en vuelo al abrirlo, cambio de partido, denegaciones actuales, respuestas
obsoletas y desmontaje. El E2E nuevo comprueba versión 2 tras publicar sin
Actualizar, conservación del motivo escrito y recarga aplazada tras cancelar con
confirmación; recuperación 032 exige también versión 2 tras RESYNC sin replay.

Pila local con arnés test-only y base nueva `bc_f8_history_e2e`, init real,
migraciones 001–055 y seed. No se modificó .env ni el runner/configuración. El
contenedor Playwright no tiene Docker CLI (limitación ya conocida); logs de API y
worker recogidos desde el host en `/home/ubuntu/f8-history-e2e-server.log`.
Sin inspección visual manual. Fix funcional publicado como
`7018d361684dd05ac121d0d60fafed461ddf46d6`.

CI del fix, comprobada por SHA y evento después de esperar `git_pr_checks(all)`:

| Evento | Run | Estado |
|---|---|---|
| pull_request | 43496923078 | success |
| push | 43496914192 | success; E2E omitido según condición existente |

```text
Summary: 7 passed, 0 failed, 0 pending, 0 skipped
Frontend: tests 979; pass 978; fail 0; skipped 1
Build complete in 9.52s!
Backend PR: 3613 passed, 4 skipped in 717.72s (0:11:57)
E2E PR: 60 passed (5.9m)
RESULTADO: VERDE (0)
```

Las seis pruebas private-realtime pasan, incluida publicación con borrador abierto
y reconstrucción del historial tras RESYNC. GitHub Review actualizada:
«Devin Review: No Issues Found», sin nuevos hallazgos que corregir ni falsos
positivos que descartar; cero comentarios inline. Estado del SHA: success,
«No findings left on this commit». El push aún estaba ejecutándose al terminar
el check del PR; se esperó su run específico y se comprobó success por la API.
T37 conserva fusión pendiente; no se fusionó el PR ni se declaró aceptación F8.

## Inicio de PR C y cierre de T37 — 2026-11-13

El usuario comunica la fusión de #77 y autoriza C. Comprobación autoritativa:
```json
{"merge_commit_sha":"ca136b2c1ebd1a2b0d613eafc575d32e055ddfa8","merged":true,"state":"closed"}
```

`main` actualizado por fast-forward hasta ese merge; C parte de él. El HEAD final
de B fue `5daa6d5c586179aaf56ad6caf2933679d9c1af6e`, con CI final comprobada:
PR 43499246334 y push 43499235618 success, frontend 978 pass/1 skip,
backend PostgreSQL 3613 pass/4 skip, E2E PR 60 pass (5.8m) y Review sin hallazgos.
Estas salidas corresponden a B, no son ejecución nueva ni evidencia de C.

T37 verificada por fusión más gates anteriores; T38–T48 pendientes y T49 abierta.
F8 **pendiente de aceptación**, R32f **abierto**; no se habilita F1 ni Socket.IO F9.
No se exige ni introduce migración nueva para este cierre documental.

### Revisión del presupuesto de T38/T39 antes de implementar

Se detiene la ejecución de C conforme a la regla de 20–30 min por tarea y al
brief del usuario; no se escribió código ni tests nuevos, no se alteró el alcance.
La dificultad no es una decisión de permisos ni una necesidad de esquema:

- `frontend/e2e/docker-compose.realtime.yml:1–5` solo arranca un API en 8000.
- `backend/tests/realtime_e2e_server.py:23–33,196–200,205–208` usa un único
  directorio IPC y estado de barrera por proceso. Arrancar dos copias sobre el
  mismo directorio permitiría que cualquiera consumiera un comando; no acredita
  que ambos procesos hayan quedado detenidos antes de la evaluación.
- `backend/tests/test_realtime_delivery_db.py:247–264,301–309` usa PostgreSQL
  real, pero emisores AsyncMock o barreras asyncio del mismo proceso, no dos API
  con sockets. No se presenta esa evidencia existente como multiproceso.
- L1 actual (`test_realtime_delivery_db.py:379–426`) ya mide trabajo SQL interno
  por usuario en una base desechable y 100/257 principales. No mide dos procesos,
  ráfagas con DB lenta, p50/p95, retraso o memoria de episodios repetidos.

Estimación T38: 60–90 min activos, separables en tres unidades de 20–30 min.
T39 necesita ampliar la instrumentación sobre esa topología y también se estima
en tres unidades. Propuesta interna, **sin aprobación ni incorporación todavía**:

| Tarea | Desglose propuesto | Comprobación |
|---|---|---|
| T38a | Dos API reales test-only, DB/Redis compartidos, controles IPC independientes e identificación de procesos. | Demostrar dos PID/puertos y que ambos consumen el mismo evento. |
| T38b | Barreras por proceso para evento pendiente, commit de retirada y evaluación posterior, reutilizando el arnés de B. | PostgreSQL/RLS reales; ningún receptor retirado recibe tras el corte; dos tenants. |
| T38c | Misma persona/sesiones en ambos API y reconexión al otro proceso, con captura antes del dispatcher. | Recepción/ausencia en transporte y HTTP autorizado, sin convertir mocks en prueba de sockets. |
| T39a | Dataset 1.000 sockets/100 principales y borde 256/257, con trabajo SQL interno y llamadas de red. | Lotes máximos 256; coste por principal/lote, no por pestaña. |
| T39b | Ráfagas acotadas, cero destinatarios y DB lenta/caída, repetidos en ambos procesos. | Suspensión aislada y recuperación por 032, sin replay/backlog. |
| T39c | Artefacto reproducible con p50/p95, retraso, memoria y episodios repetidos. | Registrar entorno/dataset y aceptación estructural, sin inventar SLA. |

Todo seguiría dentro del único PR C, sin arquitectura productiva nueva, migración,
permisos HTTP ni cambios de C4. Comandos objetivo siguen siendo los de T38/T39 y
el runner E2E completo; no se ejecutaron selectores vacíos para fingir un rojo.
T40–T46 dependen de estas tareas. Además, T47 exige el PR que abrirá el usuario;
T48 no puede cerrarse sin esa CI/revisión. T49 y aceptación F8 siguen pendientes.

Solo se verifican aquí el diff documental, cierre de T37 y permanencia de
T38–T49 abiertas. No se ejecutaron los gates locales completos ni carga de C;
los resultados anteriores son los de B y no se reutilizan como validación de C.
