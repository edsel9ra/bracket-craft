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
