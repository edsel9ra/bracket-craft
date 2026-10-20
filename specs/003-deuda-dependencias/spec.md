# Spec 003 — Retiro de la deuda de dependencias del frontend

Estado: aprobada (2026-10-19)

> Aprobada por el usuario tras la revisión QA (tres rondas). Desviación D-6 registrada durante la implementación (2026-10-19) con aprobación del usuario.

## Contexto y objetivo

La spec 001 dejó vigente una excepción a la §5.1 de la constitución: el job `security` de CI permanece en rojo por hallazgos de dependencias del frontend que ya existían antes de aquella entrega. La excepción se aprobó con una condición de retiro explícita —«una spec aparte que resuelva la deuda de dependencias del frontend»— y esta es esa spec.

El objetivo es **extinguir la excepción**, no renovarla: dejar el job `security` en verde con los mismos umbrales de severidad, sin supresiones por CVE, paquete o ruta, sin bajar el nivel de auditoría y sin ampliar el alcance que se ignora. La deuda es de la cadena de dependencias del frontend; `pip-audit` está limpio.

La deuda no es un conjunto homogéneo y la caracterización anterior («dependencias de desarrollo») no es exacta. `pnpm audit --prod` informa **cero** `devDependencies` en el grafo auditado: los paquetes afectados son herramientas de construcción que `nuxt` declara como dependencias de producción, y `nuxt` es una dependencia de producción legítima porque el contenedor sirve el servidor Nuxt compilado. Esto descarta atajos aparentes (reclasificar `nuxt` como dependencia de desarrollo) y explica por qué la auditoría de producción falla.

`pnpm audit` no distingue por sí solo entre hallazgos accionables y no accionables a efectos del job: informa todos y devuelve un código de fallo. Las opciones de exclusión integradas de pnpm guardan identificadores GHSA en `pnpm-workspace.yaml` y no se podan automáticamente —solo con `--fix` y una opción adicional—, lo que convertiría una decisión transitoria en una lista persistente y opaca. Por eso la decisión D-1b opta por un **filtro propio, determinista y sin persistencia**, que deja el comando de auditoría sin flags de supresión y mantiene el fallo ante cualquier hallazgo accionable.

Existe además un hallazgo de seguridad separado y **bloqueante para el cierre** (D-5): `opencode.json`, un archivo de configuración de herramientas versionado, contiene una cabecera de autorización con una credencial en claro, y el valor también está en el historial de git. La credencial debe rotarse y retirarse del archivo versionado antes de declarar el job verde; el valor no se reproduce en esta spec ni en su evidencia.

### Estado verificado al redactar (2026-10-19)

| Auditoría | Comando y versiones | Resultado | Detalle |
|---|---|---|---|
| Python | `pip-audit -r backend/requirements.txt` con Python 3.14 | **Verde** (salida 0) | «No known vulnerabilities found». |
| Frontend, salida completa | `pnpm audit --prod --json --audit-level low` ejecutado en `frontend/` con Node 24 y pnpm 12.12.1 | **Rojo** (salida 1) | `advisories`: 14 entradas y 11 GHSA únicos. `metadata.vulnerabilities`: 14 advisories — 3 críticas, 8 altas, 2 moderadas y 1 baja. `devDependencies: 0`. |
| Frontend, umbral alto | El mismo comando con `--audit-level high` | **Rojo** (salida 1) | La salida detallada muestra 11 entradas (solo ≥ high); `metadata.vulnerabilities` sigue contando 14 advisories porque no se filtra por `--audit-level`, incluidas las 2 moderadas y la baja. |
| Sistema de archivos | Trivy de CI con `aquasecurity/trivy-action@v0.36.0`, `--ignore-unfixed`, `--severity CRITICAL,HIGH`, `--exit-code 1` | **Rojo** (salida 1) | 13 hallazgos de vulnerabilidad: 9 en el lockfile del frontend y 4 en un lockfile de la raíz del repositorio. Todos tienen versión corregida, por lo que `--ignore-unfixed` no los ignora. |

Las cifras anteriores se obtuvieron con esas invocaciones exactas el 2026-10-19. `metadata.vulnerabilities` cuenta advisories, no `findings`, y no se filtra por `--audit-level`; por eso el resumen mantiene 14 aunque la salida detallada con umbral alto muestre 11. Dependen de la base de advisories, que es viva, y deben reproducirse en la validación (RF-010); no son un criterio fijo ni un requisito.

La tabla cubre **solo vulnerabilidades**. El escaneo `trivy fs` de CI también ejecuta el escáner de secretos por defecto; su resultado no se afirma en esta spec y se reproduce en la validación (RF-010 y RF-011). Con la desviación D-6, la verificación de implementación mostró el target del frontend con 620 paquetes y los 2 HIGH sin parche al quitar `--ignore-unfixed`; la tabla anterior describe el estado previo, no el estado final.

Advisories del frontend y su naturaleza (11 GHSA únicos):

- **Críticos y accionables (3):** `simple-git` (GHSA-x6jw-m9v5-85vh), `@simple-git/argv-parser` (GHSA-v5rq-49vh-5v5c) y `shell-quote` (GHSA-pqg4-j6r4-53mv). Cadenas `nuxt > @nuxt/devtools > …`.
- **Altos y accionables (4):** `brace-expansion` (GHSA-qhr7-859c-m2p7 y GHSA-6j4f-fj2g-mc7p, cada uno en dos líneas de versión) y `simple-git` (GHSA-g4wm-2vf7-vfgr y GHSA-858h-whjf-mvg5).
- **Altos sin corrección disponible (2):** `node-forge` (GHSA-86w9-cpqp-85rv) y `braces` (GHSA-vfj7-8cjw-p6xm). La versión más reciente publicada de ambos sigue afectada; en la auditoría aparecen con `patched_versions: null` y `patched_versions_unpublished: true`, y llegan por `nuxt > @nuxt/nitro-server > nitropack` (`listhen` y `globby`).
- **Moderados y bajos, no bloqueantes (2 GHSA):** `brace-expansion` (GHSA-q2hr-2g5m-vwhr, moderado, con corrección; dos entradas) y `serialize-javascript` (GHSA-gfhx-hw2g-v5hg, bajo, con corrección). Quedan visibles pero no alcanzan el umbral alto.

Dos hechos adicionales, ambos verificados:

1. **La prueba de resolución indica que el verde es alcanzable sin cambios mayores ni flags de supresión.** Sobre una copia aislada de los manifiestos, una actualización dentro de los rangos ya declarados resolvió `nuxt` 4.6.2, `@nuxt/devtools` 3.4.3, `shell-quote` 1.12.0 y `brace-expansion` 2.1.7/5.0.12. Dejó exactamente los dos advisories altos sin corrección (`node-forge` y `braces`); conforme a la regla de RF-003, un filtro que solo falle ante accionables no los bloquearía (la prueba de viabilidad no ejecutó el filtro, solo comprobó que eran la única diferencia restante). Trivy quedó en 0 con `--ignore-unfixed`. No hizo falta subir ningún major ni cambiar versiones fijadas de CI.
2. **Hay una segunda cadena de dependencias, muerta, en la raíz del repositorio.** Existe un manifiesto y un lockfile versionados en la raíz, con `nuxt` como única dependencia, que no participan en el build, las imágenes ni la CI, contradicen la guía del proyecto («no existe gestor de paquetes en la raíz») y aportan 4 de los 13 hallazgos de Trivy. Es un residuo, no una decisión de arquitectura.

## Decisiones cerradas (2026-10-19)

- **D-1 = A. Política general de no bloqueo por hallazgos sin corrección.** El job solo falla ante hallazgos accionables; los no accionables se muestran y se revisan. Sin listas de CVEs, paquetes ni rutas. *Motivo:* es la única vía verificada para dejar el job en verde hoy sin bajar umbrales ni suprimir casos concretos.
- **D-1b = A. Mecanismo: filtro propio, sin flags de supresión.** Se mantiene `pnpm audit --prod` sin flags de supresión y se añade un filtro determinista en `infra/scripts/audit_frontend.py` que lee la salida JSON, falla si hay algún advisory ≥ high con corrección publicada y muestra los no accionables. Sin listas persistentes de GHSA como exclusiones, sin `audit.ignore` ni `auditConfig.ignoreGhsas`, con pruebas propias. *Motivo:* las exclusiones integradas de pnpm persisten en el espacio de trabajo y no se podan solas, lo que convertiría una política transitoria en una lista opaca. D-1b sustituye al mecanismo, no a la política de D-1.
- **D-2 = A. Retirada de la cadena de dependencias de la raíz.** Se retiran el manifiesto y el lockfile de la raíz tras comprobar que ninguna build, imagen ni verificación los usa. *Motivo:* es un residuo que contradice la guía del proyecto y aporta 4 de los 13 hallazgos de Trivy.
- **D-3 = A. Alcance mínimo.** Solo se refresca la resolución del lockfile dentro de los rangos ya declarados, sin cambios mayores ni modernización de la cadena de desarrollo en el sentido de la definición (no cambian las declaraciones de rango). *Motivo:* la prueba de resolución sobre una copia aislada indica que basta para dejar cero hallazgos accionables y evita mezclar la deuda con una actualización de producto.
- **D-4 = A. Revisión del riesgo residual.** Los advisories sin corrección se revisan en cada actualización de dependencias y en la próxima auditoría técnica, con el propietario del producto como responsable; si aparece un parche, se adopta en el mismo cambio. *Motivo:* mantiene el riesgo visible sin convertir la exclusión en una excepción permanente.
- **D-5 = A. Rotación y retiro de la credencial versionada.** Se rota la credencial expuesta y se retira del archivo de configuración versionado, que pasa a usar una referencia `{env:...}` o `{file:...}` (variable de entorno o archivo local ignorado). Es un cambio de seguridad separado y **bloqueante para el cierre**. *Motivo:* el valor también está en el historial de git, así que borrarlo del árbol no basta; la rotación es obligatoria para que el valor antiguo deje de ser válido.
- **D-6 = A. Lockfile de un solo documento para que Trivy audite el frontend.** Se añade `pmOnFail: ignore` a `frontend/pnpm-workspace.yaml` para que pnpm no escriba el documento de autogestión; el lockfile queda en un único documento y Trivy audita el grafo real. CI sigue fijando pnpm con `pnpm/action-setup`. Implica adaptar `infra/scripts/verify_version_sources.py` para aceptar ambos formatos sin perder la comprobación del pin. *Motivo:* Trivy 0.70.0, el que fija `trivy-action@v0.36.0`, solo lee el primer documento del lockfile de dos documentos de pnpm 12; con el formato anterior no había target del frontend y el verde era vacuo.

Estas siete decisiones están cerradas y el plan no debe reabrirlas. La spec sigue aprobada; la desviación D-6 se registró durante la implementación con aprobación del usuario.

## Usuarios

- **Mantenedor o desarrollador:** necesita que el rojo del job `security` signifique un riesgo nuevo y accionable, no deuda conocida que se arrastra.
- **Revisor humano de cambios:** necesita que la señal de CI sea confiable para aprobar sin repetir el análisis manual de la deuda preexistente.
- **Responsable del producto:** aprobó la excepción §5.1, decidió retirarla y asume el seguimiento del riesgo residual con la condición de revisión de D-4.
- **Responsable de seguridad:** necesita que la credencial expuesta se rote, que el valor no se reproduzca en documentos ni evidencias y que no se declare verde con un secreto vigente.
- **Operador de despliegue:** se beneficia de que la cadena auditada corresponda a lo que realmente se construye y ejecuta, sin cadenas muertas que generen ruido o falsos positivos.

## Roles y visibilidad

**No aplica.** El cambio no introduce ni modifica roles de producto, permisos, rutas, contratos de API ni contenido público. No altera qué ve el público, un miembro de organización, un administrador de organización ni un administrador de plataforma. Los únicos «accesos» afectados son el del proceso de integración continua a las auditorías y el de la herramienta cuya credencial se rota (D-5).

## Historias de usuario

- **HU-1.** Como mantenedor, quiero que el job `security` esté en verde con los umbrales actuales para que un rojo vuelva a ser una señal de riesgo nuevo.
- **HU-2.** Como revisor, quiero que la única causa conocida de rojo deje de ser deuda preexistente para poder confiar en la CI al aprobar cambios.
- **HU-3.** Como responsable del producto, quiero retirar la excepción §5.1 con evidencia verificable para cumplir la constitución sin prorrogarla.
- **HU-4.** Como operador, quiero que la cadena auditada sea la que se construye y despliega, sin cadenas duplicadas ni muertas, para que la auditoría refleje el riesgo real.
- **HU-5.** Como mantenedor, quiero un criterio general y estable para advisories sin corrección para no tener que volver a negociar una excepción cada vez que aparezca uno.
- **HU-6.** Como responsable de seguridad, quiero que la credencial expuesta se rote y desaparezca del archivo versionado para que el valor del historial deje de ser útil.

## Definiciones

- **Hallazgo accionable a efectos del job:** advisory con severidad **≥ high** y al menos una versión corregida publicada. Hay corrección publicada cuando `patched_versions` está presente, no es `null`, no es cadena vacía y `patched_versions_unpublished` no es `true`. Es el único que hace fallar el filtro. Si la corrección publicada no es compatible con los rangos o las versiones de referencia, el hallazgo sigue siendo accionable y el trabajo se detiene y se pregunta.
- **Hallazgo no accionable a efectos del job:** advisory ≥ high sin corrección publicada —`patched_versions` ausente, `null`, cadena vacía o `patched_versions_unpublished: true`—, o cualquier advisory de severidad moderada o baja, aunque tenga corrección. No bloquea. Los moderados y bajos se muestran; los informativos solo se contabilizan en `metadata.vulnerabilities.info`, porque `--audit-level low` no los incluye en `advisories`.
- **Corrección publicada:** existencia de al menos una versión corregida en el advisory, según `patched_versions` de la salida JSON de pnpm. Se evalúa por paquete y versión, no por cadena completa: que una dependencia padre pueda eliminar el paquete en el futuro no convierte en accionable un advisory que hoy no tiene parche. `patched_versions` es opcional en el esquema y su ausencia, `null` o cadena vacía no son errores; `patched_versions_unpublished: true` significa que la corrección no está publicada.
- **Filtro determinista:** programa propio, sin red y sin estado, que recibe la salida JSON de `pnpm audit` por archivo (`--input`) o entrada estándar, y el estado de pnpm como argumento explícito (`--pnpm-status`). Aplica la regla de accionables y devuelve un código de salida estable; el veredicto es suyo, no el de la tubería. El filtro no escribe archivos ni listas; el único archivo temporal lo crea el shell del comando efectivo y se elimina al salir. Se ejecuta con `PYTHONDONTWRITEBYTECODE=1` para que tampoco deje caché de bytecode.
- **Comando efectivo de auditoría del frontend:** se ejecuta **desde la raíz del repositorio**, con este bloque idéntico en §3.4, `AGENTS.md`, README y CI:
  ```
  AUDIT_JSON="/tmp/pnpm-audit.json"
  trap 'rm -f "$AUDIT_JSON"' EXIT
  if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
  PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
  ```
  El archivo temporal vive fuera del repositorio y se elimina al salir; el filtro recibe el JSON por archivo y el estado de pnpm por `--pnpm-status`, y su código de salida es el resultado del paso. El paso de CI usa `working-directory` en la raíz del repositorio (o lo omite) y `pnpm --dir frontend`; no se ejecuta con `working-directory: frontend`.
- **Artefacto de rotación:** registro de validación con fecha, responsable y confirmación de revocación en el proveedor, sin el valor de la credencial ni el host asociado.
- **Supresión:** exclusión de un advisory, CVE, GHSA, paquete o ruta concretos, incluida la que se persiste en la configuración del gestor de paquetes. No es lo mismo que una política general aplicada por un filtro sin estado.
- **Cadena de producción:** grafo que audita `pnpm audit --prod`; incluye `nuxt` y sus herramientas de construcción porque están declaradas como dependencias de producción y el runtime sirve el servidor Nuxt compilado.
- **Cadena de desarrollo:** `devDependencies` del frontend; sus declaraciones de rango no cambian en esta spec, aunque el refresco del lockfile pueda mover directas dentro de rango (`typescript`, `vue-tsc`, `@types/node`) y transitivas como efecto colateral.
- **Cadena raíz:** manifiesto y lockfile versionados en la raíz del repositorio que no participan en el build, las imágenes ni la CI. La decisión D-2 la retira.
- **Lockfile de un solo documento:** formato de `frontend/pnpm-lock.yaml` con `lockfileVersion` una vez, sin `packageManagerDependencies` y sin separador `---`, habilitado por `pmOnFail: ignore`. Es el único formato que Trivy 0.70.0 audita como target del frontend.
- **Alcance mínimo:** refresco de la resolución del lockfile dentro de los rangos ya declarados, sin cambios mayores ni modernización de la cadena de desarrollo (decisión D-3).
- **Modernización:** cambio de las declaraciones de rango del `package.json` o de la versión mayor de una dependencia. Mover versiones resueltas dentro de un rango ya declarado —aunque sean `devDependencies` directas— no es modernización.
- **Retención de publicaciones:** `minimumReleaseAge` de pnpm (por defecto 1440 minutos desde pnpm 11; no estricto si no se configura) y `minimumReleaseAgeExclude` de `frontend/pnpm-workspace.yaml`, que permite eximir versiones concretas. Es una espera de madurez, no una supresión de auditoría.
- **Documento de estado actual:** `MEMORY.md`, el estado de la excepción en la spec 001, `AGENTS.md` y el README. Un registro histórico fechado no es estado actual y puede conservar el contexto de la deuda.
- **Credencial expuesta:** credencial en claro en un archivo de configuración versionado, cuyo valor también está en el historial de git. Su valor no se reproduce en esta spec, en la evidencia ni en los mensajes.
- **Excepción §5.1:** la excepción documentada en la spec 001 que mantiene el job `security` en rojo por esta deuda. Esta spec la retira; no la prorroga.
- **Versiones de referencia:** Python 3.14, Node 24 y pnpm 12.12.1, fijadas por la §3.5 de la constitución.

## Requisitos funcionales

**RF-001. Job `security` en verde con los umbrales vigentes.**
CUANDO el job `security` se ejecuta sobre el commit o el pull request del cambio, y después del merge sobre la rama principal, EL SISTEMA completa las tres auditorías con los umbrales vigentes y el job termina en verde.
*Criterios de aceptación:*
- `pip-audit`, el bloque de comando efectivo de auditoría del frontend y el escaneo Trivy terminan con salida 0.
- La evidencia de Trivy demuestra cobertura real del frontend: un target `frontend/pnpm-lock.yaml` de tipo pnpm con paquetes analizados (620 en la verificación) y, sin `--ignore-unfixed`, los 2 HIGH sin parche (`braces` y `node-forge`). Una salida 0 sin target del frontend no cuenta como verde.
- El verde se obtiene sin bajar el umbral de severidad (high), sin cambiar CRITICAL/HIGH de Trivy, sin desactivar pasos y sin ampliar los directorios ignorados; la única exclusión es la política general aplicada por el filtro de RF-003.
- Se acepta como evidencia la ejecución del commit o del pull request para la revisión, y se exige además la ejecución de la rama principal después del merge para el cierre.
- La evidencia queda fechada y adjunta al cierre.

**RF-002. La cadena de producción no conserva hallazgos accionables.**
CUANDO se audita la cadena de dependencias de producción del frontend, EL SISTEMA no presenta ningún hallazgo accionable a efectos del job; los corregibles se resuelven refrescando la resolución dentro de los rangos ya declarados, sin cambios mayores, conforme al alcance mínimo de la decisión D-3.
*Criterios de aceptación:*
- El número de hallazgos accionables (≥ high con corrección publicada) es **0** al momento de la validación.
- Los hallazgos ≥ high sin corrección y los moderados o bajos con o sin corrección no bloquean, pero aparecen en la salida; los informativos solo se contabilizan en `metadata.vulnerabilities.info` y no se listan, porque `--audit-level low` los excluye de `advisories`. Nada se oculta del resumen.
- El alcance es el mínimo de D-3: no se actualizan mayores ni se moderniza la cadena de desarrollo en el sentido de la definición (no cambian las declaraciones de rango); el refresco se limita a resolver dentro de los rangos ya declarados.
- El refresco es completo sobre el lockfile del frontend, no limitado a producción, para evitar una resolución mixta. No cambia las declaraciones de rango de `package.json` ni añade dependencias. Puede mover también `devDependencies` directas dentro de rango (`typescript`, `vue-tsc`, `@types/node`) y transitivas de desarrollo como efecto colateral; en ese caso deben pasar `pnpm test`, `pnpm run typecheck` y `pnpm run build` (RF-007).
- No se introduce ningún cambio mayor en `nuxt`, `vue`, `pinia`, `socket.io-client`, `@pinia/nuxt`, `@vue-flow/core`, `typescript` ni `vue-tsc`. Si una corrección exigiera un mayor, el trabajo se detiene y se pregunta.
- La retención de publicaciones se resuelve con `minimumReleaseAge` de pnpm y `minimumReleaseAgeExclude` de `frontend/pnpm-workspace.yaml`, ya versionado. Si una versión corregida no cumple la ventana, se añade solo esa versión exacta a `minimumReleaseAgeExclude`, con motivo y condición de retiro; no se desactiva la política ni se instala una versión vulnerable. Es una excepción temporal de resolución, no una supresión de auditoría, y queda amparada por la excepción acotada de RNF-001.
- Las correcciones quedan fijadas en el lockfile versionado; la instalación con `--frozen-lockfile` pasa y no resuelve versiones distintas.
- La auditoría sigue siendo de producción (`--prod`); no se amplía a `devDependencies` ni se reduce para excluir paquetes concretos.

**RF-003. Filtro determinista de auditoría, sin supresiones persistentes.**
CUANDO el job `security` audita el frontend, EL SISTEMA ejecuta el bloque de comando efectivo definido en «Definiciones» —desde la raíz del repositorio, con `pnpm --dir frontend`, el estado de pnpm capturado y pasado al filtro y el JSON en un archivo temporal—, usa el veredicto del filtro como resultado del paso y falla si existe algún hallazgo accionable, mostrando los no accionables que corresponda.
*Criterios de aceptación:*
- El comando efectivo invoca la auditoría con `--audit-level low` explícito para que una configuración global (`audit.level`) no reduzca la salida y produzca un falso verde. `--audit-level` filtra `advisories`, pero no `metadata`; la comparación de RF-003 detecta el recorte.
- El estado de pnpm se captura con `if ...; then status=0; else status=$?; fi` y se pasa al filtro como `--pnpm-status`; una tubería no decide el resultado y `pipefail` no puede abortar antes del veredicto. El archivo temporal se crea fuera del repositorio y se elimina con `trap ... EXIT`, incluso si el filtro falla.
- El filtro devuelve fallo si al menos un advisory tiene severidad **high o critical** y corrección publicada: `patched_versions` presente, no `null`, no cadena vacía y `patched_versions_unpublished` distinto de `true`.
- `patched_versions` es opcional: su ausencia (`undefined`), `null`, la cadena vacía o `patched_versions_unpublished: true` significan «sin corrección disponible» y **no** son errores de esquema.
- `advisories` debe estar presente y ser un objeto; `advisories: {}` es el único caso que representa «sin hallazgos». Si falta, el filtro falla de forma cerrada aunque `metadata.vulnerabilities` sea 0.
- El filtro devuelve éxito si no hay advisories accionables; en particular, si `advisories` es `{}` o si todos los ≥ high carecen de corrección. En ese caso muestra los no accionables de severidad alta, moderada o baja que corresponda, con identificador, paquete, severidad, versión afectada y ausencia de parche.
- Los advisories moderados y bajos se muestran siempre, tengan o no corrección, y no bloquean. Los informativos **no se listan**: `--audit-level low` los excluye de `advisories` y solo se contabilizan en `metadata.vulnerabilities.info`.
- El filtro compara las entradas de `advisories` con `metadata.vulnerabilities`: cuenta por severidad (`low`, `moderate`, `high`, `critical`) y falla de forma cerrada si no cuadra; las claves ausentes cuentan como cero. Si `metadata.vulnerabilities.info` es mayor que cero, lo registra y no exige su presencia en `advisories`, porque `--audit-level low` no incluye informativos. Si `metadata.dependencies` está presente, lo registra y considera inválido el caso de cero dependencias con advisories; si no está, no se inventa.
- El filtro no escribe archivos, no modifica `frontend/pnpm-workspace.yaml` y no mantiene estado entre ejecuciones. No se versionan listas de GHSA como exclusiones de auditoría ni se usan `audit.ignore` o `auditConfig.ignoreGhsas`.
- Si la salida no es JSON válido, el esquema es realmente inválido (por ejemplo, `advisories` no es un objeto, una severidad desconocida o `patched_versions` con un tipo inesperado), falta un campo obligatorio o `pnpm audit` no produce salida, el filtro falla de forma cerrada; un `patched_versions` ausente o nulo no es un esquema inválido.
- El paso de CI distingue el código de salida 1 de pnpm por hallazgos del fallo operativo: no se detiene antes de ejecutar el filtro por hallazgos, pero falla si no puede obtener o parsear el JSON. La captura explícita del estado y su paso a `--pnpm-status` evita que `set -e` o `pipefail` aborten antes del veredicto.
- El filtro tiene pruebas propias con fixtures que cubren, como mínimo: accionable crítico y alto → falla; alto sin corrección con `patched_versions` ausente, `null`, cadena vacía y `patched_versions_unpublished: true` → pasa y lo muestra; moderado y bajo con corrección → pasan y se muestran; informativo solo en `metadata.vulnerabilities.info` → se contabiliza y no se lista; `advisories: {}` → pasa; `advisories` ausente → falla aunque `metadata` sea cero; desajuste entre `advisories` y `metadata.vulnerabilities`, o `metadata.dependencies: 0` con advisories → falla; JSON inválido, esquema realmente inválido, error de ejecución y estado de pnpm no pasado → fallan. Las pruebas se añaden a un job de CI existente desde el PR-1.
- No se afirma equivalencia exacta con Trivy: `--ignore-unfixed` ignora los estados `affected`, `will_not_fix`, `fix_deferred` y `end_of_life`, mientras que el filtro se basa en `patched_versions` de pnpm. Ambos comparten la política de no bloquear por falta de corrección, pero pueden divergir en los bordes; por eso las dos auditorías deben pasar y ninguna sustituye a la otra.
- Si Trivy señala un hallazgo CRITICAL/HIGH con corrección que el filtro no marcara, prevalece el fallo y se corrige; no se ajusta el filtro para ocultarlo.

**RF-004. Una sola cadena de dependencias auditada.**
EL SISTEMA mantiene una única cadena de dependencias auditable en el repositorio: la del frontend que se construye y se despliega. Retira la cadena raíz muerta conforme a la decisión D-2.
*Criterios de aceptación:*
- El manifiesto y el lockfile de la raíz se retiran del repositorio tras comprobar que ninguna build, imagen ni verificación los usa.
- Tras el cambio no existe ninguna cadena raíz, ni propia ni referenciada, que aporte hallazgos a Trivy.
- El repositorio coincide con la guía del proyecto, que declara que no hay gestor de paquetes en la raíz.
- La comprobación previa de usos queda registrada en la evidencia de validación y en la descripción del pull request; si algo dependiera de esa cadena, el trabajo se detiene y se reporta en lugar de retirarla.
- No se oculta la cadena ampliando los directorios ignorados del escaneo.

**RF-005. Retiro formal de la excepción §5.1 y corrección de la caracterización.**
CUANDO el job `security` quede en verde con la política de D-1 y el filtro de D-1b, EL SISTEMA retira la excepción §5.1 de la spec 001, deja de declararla vigente en la memoria del proyecto y corrige la caracterización errónea de la deuda en los documentos de estado actual.
*Criterios de aceptación:*
- La spec 001 marca la excepción como **retirada**, indica la fecha y remite a esta spec y a su evidencia.
- `MEMORY.md` deja de listar la deuda como pendiente o vigente, registra el retiro con la evidencia y la fecha, y corrige la descripción de «dependencias de desarrollo» por la de herramientas de construcción dentro del grafo de producción.
- El estado de la excepción en la spec 001 también corrige esa caracterización al marcarla como retirada.
- `AGENTS.md` actualiza la referencia al lockfile para nombrar `frontend/pnpm-lock.yaml`, coherente con el layout real del repositorio.
- La alineación del **comando efectivo** en `AGENTS.md` y el README se hace en el PR-2, junto con la enmienda y el cableado de CI; el PR-5 se limita al retiro de la excepción y a la corrección de la caracterización.
- Ningún documento de estado actual afirma que el job `security` sigue en rojo por esta deuda; los registros históricos fechados pueden conservar el contexto y no se consideran incumplimiento.
- La evidencia adjunta incluye fecha, comandos, versiones usadas y salidas (o un resumen con IDs y conteos), sin secretos ni datos personales.
- El retiro documental no se mezcla con cambios funcionales y cuenta con revisión humana distinta del autor.

**RF-006. Riesgo residual visible y con revisión.**
EL SISTEMA registra los advisories sin corrección que sigan presentes, con su motivo de no accionabilidad, el propietario del producto como responsable y la condición de revisión de D-4, de modo que su exclusión no se convierta en una excepción permanente ni silenciosa.
*Criterios de aceptación:*
- El registro único del riesgo residual es `MEMORY.md`, en una sección propia «Riesgo residual», separada de «Pendiente»; no se crea una lista paralela en la configuración ni en otro documento de estado.
- `MEMORY.md` se mantiene dentro del límite de ~50 líneas de `AGENTS.md`: se resume o poda lo que ya no aporte, sin duplicar en «Pendiente» lo que vive en «Riesgo residual».
- Se documentan los identificadores de los advisories sin corrección y se justifica por qué no son accionables (última versión publicada afectada, sin parche), indicando que se evalúan por paquete y versión.
- La condición de revisión es la de D-4: en cada actualización de dependencias y en la próxima auditoría técnica.
- El responsable es el propietario del producto.
- Si aparece un parche, se adopta en el mismo cambio en que se detecte; no hay una fecha de caducidad que silencie el hallazgo.
- `MEMORY.md` se actualiza en cada revisión de D-4 con fecha, identificadores y estado, sin secretos ni datos personales.
- El registro de `MEMORY.md` es informativo: no se consume como exclusión por el filtro ni altera el veredicto del job.

**RF-007. Sin regresiones funcionales ni de verificación.**
CUANDO se actualiza la cadena de dependencias, EL SISTEMA conserva el comportamiento de la aplicación y las verificaciones del frontend.
*Criterios de aceptación:*
- `pnpm install --frozen-lockfile`, `pnpm test`, `pnpm run typecheck` y `pnpm run build` pasan con las versiones de referencia.
- Si el refresco mueve `devDependencies` directas dentro de rango (`typescript`, `vue-tsc`, `@types/node`) o transitivas de desarrollo como efecto colateral, las tres verificaciones se ejecutan igualmente y pasan; no se acepta un cambio de comportamiento como coste de la actualización.
- No cambian rutas, contratos de API, comportamiento observable ni interfaz de usuario.
- La imagen del frontend se construye y arranca el servidor compilado.
- Cualquier cambio de comportamiento detectado se detiene y se reporta.

**RF-008. Versiones de referencia, alcance de auditoría y archivos versionados.**
EL SISTEMA mantiene Python 3.14, Node 24 y pnpm 12.12.1, la instalación con `--frozen-lockfile`, el lockfile y el espacio de trabajo del frontend versionados, y no cambia el alcance de las auditorías más allá de lo que autorice esta spec.
*Criterios de aceptación:*
- Las versiones fijadas en CI no cambian. Si una corrección las exigiera, el trabajo se detiene y se pregunta; no se suben por iniciativa propia.
- El lockfile del frontend sigue versionado y es la fuente de las versiones instaladas.
- `frontend/pnpm-workspace.yaml` sigue versionado. Además de `pmOnFail: ignore` (D-6), sus únicos cambios admisibles son entradas temporales de `minimumReleaseAgeExclude` para versiones exactas, justificadas y con condición de retiro; no se versionan listas de advisories o GHSA como exclusiones de auditoría ni configuraciones de auditoría.
- El lockfile del frontend queda en un solo documento cuando `pmOnFail: ignore` está declarado: `lockfileVersion` aparece una vez, no hay `packageManagerDependencies` y no hay separador `---` entre documentos. Sigue versionado y es la fuente de las versiones instaladas.
- `infra/scripts/verify_version_sources.py` acepta tanto el formato de dos documentos (comportamiento actual) como el de uno solo, sin perder la comprobación del pin `pnpm@12.12.1` ni la de las dependencias resueltas. En el formato de un documento, el pin se valida desde `frontend/package.json` y las dependencias desde el importer raíz del lockfile.
- El filtro no escribe en `frontend/pnpm-workspace.yaml` ni en ningún otro archivo del repositorio.
- La versión de Trivy y sus parámetros (`--ignore-unfixed`, `--severity CRITICAL,HIGH`, `--exit-code 1`, directorios ignorados) no cambian.
- No se añaden dependencias nuevas al producto para sortear un advisory.
- No se actualiza TypeScript a 7.x mientras `vue-tsc` no lo soporte.

**RF-009. Enmienda constitucional obligatoria de la §3.4.**
EL SISTEMA incorpora la política y el mecanismo adoptados en D-1 y D-1b mediante una enmienda constitucional propia de la §3.4, versionada, revisada y separada de los cambios funcionales, y alinea la guía del proyecto y el README con el comando efectivo.
*Criterios de aceptación:*
- La enmienda es un entregable obligatorio de esta spec, no una alternativa.
- La enmienda es de incremento **menor** (nueva versión 1.2.0) porque cambia el contenido de una regla de implementación, no una aclaración.
- La §3.4 pasa a exigir el **bloque de comando efectivo de la definición**, idéntico en §3.4, `AGENTS.md`, README y CI: desde la raíz, `pnpm --dir frontend audit --prod --json --audit-level low`, estado de pnpm capturado y pasado con `--pnpm-status`, filtro `infra/scripts/audit_frontend.py` y archivo temporal limpiado con `trap`. El filtro **sigue fallando ante hallazgos accionables**. No puede formularse como una auditoría que ignore hallazgos ni como un umbral rebajado.
- El paso de CI usa `working-directory` en la raíz del repositorio (o lo omite) y `pnpm --dir frontend`; no se ejecuta con `working-directory: frontend`.
- La cabecera y la fila del historial declaran la misma versión; la §3.4, `AGENTS.md`, el README y la CI contienen el mismo bloque y la misma ruta del filtro; no se reescriben filas anteriores.
- La fila indica motivo, regla afectada e impacto en el código y en la CI.
- La enmienda se tramita como commit separado dentro del mismo pull request que el cableado del comando en CI y la alineación de `AGENTS.md` y el README, con revisión humana distinta del autor, conforme a la §5.2.
- La guía del proyecto y el README describen el comando efectivo, el filtro y el hecho de que los hallazgos accionables siguen haciendo fallar el job.

**RF-010. Evidencia reproducible y sin verificaciones supuestas.**
ANTES de declarar el job en verde, EL SISTEMA ejecuta las tres auditorías con las versiones de CI y registra la salida; si alguna no puede ejecutarse, lo declara expresamente.
*Criterios de aceptación:*
- Hay evidencia fechada de `pip-audit`, del bloque de comando efectivo de la definición (desde la raíz, con `pnpm --dir frontend`, el estado capturado y el filtro `infra/scripts/audit_frontend.py`) y del escaneo Trivy.
- Las auditorías se ejecutan con Node 24 y pnpm 12.12.1; si se usan otras versiones, se indica y no se presenta como equivalente.
- La evidencia distingue el comando exacto, la presencia y forma de `advisories`, los GHSA únicos y los advisories del resumen `metadata`, e indica que `metadata.vulnerabilities` no se filtra por `--audit-level` y que cuenta advisories, no `findings`; los informativos solo se contabilizan en `metadata.vulnerabilities.info`.
- La evidencia incluye el resultado del escaneo de secretos de Trivy, que no se infiere de la tabla de vulnerabilidades ni se declara verde por suposición.
- La evidencia demuestra la cobertura de Trivy sobre el frontend: target `frontend/pnpm-lock.yaml` con paquetes analizados (620 en la verificación) y, sin `--ignore-unfixed`, los 2 HIGH sin parche; no se acepta una salida 0 sin target del frontend.
- La evidencia incluye el estado de `frontend/pnpm-workspace.yaml` (con `pmOnFail: ignore`, sin listas de advisories ni configuración de auditoría) y del lockfile versionado de un solo documento, con la indicación de qué se commitea.
- Se advierte de que la base de advisories es viva y los números pueden variar. El criterio de éxito es «cero hallazgos accionables (≥ high con corrección publicada) y política aplicada», no un conteo fijo copiado de esta spec.
- Los conteos que no puedan reproducirse en el entorno de validación se marcan como evidencia pendiente de esa fase, no como un requisito ni como una duda de la spec.
- No se declara ejecutada ninguna verificación que no se haya ejecutado.

**RF-011. Rotación y retiro de la credencial expuesta (D-5).**
CUANDO se cierre el cambio, EL SISTEMA ya no contiene la credencial expuesta en archivos versionados y esa credencial ha sido rotada, de modo que el valor conservado en el historial de git deja de ser válido.
*Criterios de aceptación:*
- La rotación está confirmada y documentada sin reproducir el valor; el valor anterior ya no es válido.
- El archivo `opencode.json` ya no contiene el valor literal de la credencial ni una cabecera de autorización con valor; permite expresamente una referencia `{env:...}` o `{file:...}`.
- La rotación se registra en el artefacto de rotación: fecha, responsable y confirmación de revocación en el proveedor, sin el valor ni el host.
- La comprobación sobre el árbol de trabajo y el índice de git confirma que la credencial no está en archivos versionados.
- Se reconoce que el historial de git conserva el valor; por eso la rotación es obligatoria y no opcional. No se exige reescribir el historial.
- Es un cambio de seguridad separado, con revisión propia, y es **bloqueante** para declarar el job verde y cerrar la spec; no se mezcla con la actualización de dependencias.
- La credencial no se reproduce en esta spec, en los mensajes de commit, en los pull requests, en los logs ni en la evidencia de validación, ni tampoco el host asociado.

## Requisitos no funcionales

- **RNF-001. Sin supresiones ni umbrales rebajados.** Ninguna solución puede basarse en listas de CVEs, GHSA, paquetes o rutas, ni en reducir la severidad que hace fallar la CI. La única exclusión de auditoría admisible es la política general aplicada por el filtro de RF-003, que no persiste estado. Quedan expresamente amparadas las entradas de **versión exacta** en `minimumReleaseAgeExclude`: son temporales, no están relacionadas con la auditoría y no ocultan vulnerabilidades. Las entradas **nuevas** deben tener motivo y condición de retiro. Las entradas existentes `@pinia/nuxt@1.0.3` y `pinia@4.1.0` se conservan fuera del alcance de esta auditoría; la evidencia registra cuáles carecen de motivo o condición de retiro, sin obligación de cambiarlas en esta spec.
- **RNF-002. Reproducibilidad.** Las versiones quedan fijadas en el lockfile versionado; la instalación de CI es determinista con `--frozen-lockfile`.
- **RNF-003. Estabilidad de las versiones de referencia.** Python 3.14, Node 24 y pnpm 12.12.1 se mantienen; cambiarlas sería otro cambio, con su propia actualización documental.
- **RNF-004. Trazabilidad.** Cada decisión, exclusión y revisión queda registrada con evidencia y fecha, y es revisable por un tercero.
- **RNF-005. Verificación honesta.** Lo que no se pueda ejecutar se declara; no se infiere el verde por inspección.
- **RNF-006. Sin secretos ni datos personales.** La evidencia no incluye credenciales, tokens, hosts ni datos de jugadores. La credencial de D-5 no se reproduce en ningún artefacto de la spec.
- **RNF-007. Separación y orden de entregables.** La enmienda constitucional, el comando de CI, la actualización de dependencias, la rotación de la credencial y el retiro documental se revisan y commitean por separado, en el orden de la sección «Orden de aterrizaje»; la enmienda no se mezcla con cambios funcionales.
- **RNF-008. Coste acotado.** El cambio no añade auditorías nuevas ni aumenta de forma significativa la duración del job; el filtro se ejecuta sobre la misma auditoría y se limita a corregir la deuda existente.
- **RNF-009. Filtro determinista y de fallo cerrado.** El filtro no depende de la red, del reloj ni del orden de la salida; ante una entrada inválida o incompleta falla, nunca aprueba. En particular, la ausencia de `advisories` es un fallo cerrado, no «cero hallazgos»; solo `advisories: {}` se acepta como vacío.

## Datos personales y privacidad

**No aplica** para datos personales. El cambio no trata datos de jugadores, no modifica proyecciones públicas ni privadas, no altera el consentimiento de imagen y no cambia qué información ve cada rol. La credencial de D-5 es un secreto operativo, no un dato personal; su valor no se reproduce en esta spec, en la evidencia ni en los mensajes, y la evidencia de auditoría solo contiene nombres de paquetes, versiones, severidades e identificadores de advisories.

## Casos límite

1. **Advisory sin corrección disponible:** `braces` y `node-forge` siguen afectados en su última versión. El filtro no bloquea, los muestra y se revisan; no se inventa un parche ni se fija una versión inexistente.
2. **Formas de «sin corrección»:** `patched_versions` ausente, `null`, cadena vacía o `patched_versions_unpublished: true` significan que no hay corrección publicada. No son errores de esquema y el filtro no debe fallar por ellos.
3. **Advisory que pasa de no accionable a accionable:** en cuanto upstream publique una versión corregida, el filtro vuelve a fallar y la corrección es obligatoria antes de cerrar cualquier cambio posterior.
4. **Advisory accionable nuevo entre la redacción y la validación:** la base de advisories es viva. El criterio es «cero accionables» en la validación, no la lista exacta de esta spec. Si aparece uno, se corrige o se detiene el cierre.
5. **Advisory nuevo crítico sin corrección:** el filtro no bloquea, pero lo muestra; se documenta en `MEMORY.md` y se revisa. No se abre una excepción ni se baja el umbral.
6. **Advisory moderado o bajo con corrección:** no bloquea, pero se muestra. **Informativo:** no se lista porque `--audit-level low` lo excluye de `advisories`; solo se contabiliza en `metadata.vulnerabilities.info`. En ningún caso se añade al gate ni se convierte en una excepción.
7. **Actualización de una dependencia padre dentro de rangos:** si una versión nueva de `listhen`, `globby` o `nitropack` elimina o sustituye el paquete afectado, el hallazgo puede desaparecer; eso no convierte en accionable un advisory sin parche ni autoriza a subir un mayor. Si la eliminación exigiera un mayor, se detiene y se pregunta.
8. **La retención de publicaciones bloquea una versión corregida:** se añade solo esa versión exacta a `minimumReleaseAgeExclude`, con motivo y condición de retiro; no se desactiva la política ni se instala una versión vulnerable.
9. **El filtro recibe JSON inválido, incompleto o sin `advisories`:** falla de forma cerrada. La ausencia de `advisories` no se interpreta como cero hallazgos, aunque `metadata.vulnerabilities` sea 0; solo `advisories: {}` representa «sin hallazgos». Un error de registro, de red o de esquema no se interpreta como ausencia de vulnerabilidades.
10. **Desajuste entre `advisories` y `metadata`:** si los conteos por severidad no cuadran, el filtro falla de forma cerrada; se corrige la causa y no se interpreta como verde.
11. **La política de no accionables excluye por error un advisory con corrección:** las pruebas del filtro y la comparación con `metadata` lo detectan; se corrige y se trata como fallo de implementación.
12. **Divergencia entre Trivy y el filtro:** si Trivy señala un CRITICAL/HIGH con corrección que el filtro no marcó, prevalece el fallo; se corrige la causa, no se relaja ninguna de las dos auditorías.
13. **Se intenta persistir una exclusión:** el filtro no escribe y no se versionan listas de GHSA como exclusiones de auditoría ni `audit.ignore`/`auditConfig.ignoreGhsas`; si aparecen, se revierten. El registro informativo de `MEMORY.md` no es una exclusión.
14. **Retirada de la cadena raíz (D-2):** se comprueba antes que ninguna build, imagen o verificación la usa; si algo dependiera de ella, se detiene y se reporta en lugar de retirarla. La cadena no se mantiene por inercia ni se oculta del escaneo.
15. **Se reintroduce una cadena raíz en el futuro:** la guía del proyecto ya la prohíbe y el escaneo de Trivy la detectaría; no se añade una excepción para tolerarla.
16. **La versión corregida exige Node o pnpm distintos:** se detiene y se pregunta; no se suben las versiones fijadas por iniciativa propia.
17. **Un cambio de dependencia altera tests, tipos o build:** se revierte o se ajusta dentro de lo permitido; no se acepta un comportamiento distinto como coste de la actualización, aunque el refresco solo mueva `devDependencies` directas dentro de rango.
18. **La credencial expuesta no puede rotarse antes del merge:** el job puede estar verde en vulnerabilidades, pero el cierre queda bloqueado hasta completar D-5. Si el escáner de secretos de Trivy la detecta, el job no está verde hasta el PR-4.
19. **El valor de la credencial está en el historial:** la rotación es obligatoria; borrar el archivo no invalida el valor. No se exige reescribir el historial, pero sí acreditar que el valor antiguo ya no sirve.
20. **El archivo local de configuración con la credencial se versiona por error:** se detecta antes del cierre; el archivo local debe estar ignorado y la comprobación sobre el índice de git debe pasar.
21. **La evidencia local no coincide con CI por diferencias de versión:** prevalece la ejecución con las versiones de CI y se declara la limitación.
22. **El lockfile vuelve a dos documentos o pierde `pmOnFail`:** Trivy deja de auditar el frontend; se detecta en la evidencia por la ausencia del target `frontend/pnpm-lock.yaml` con paquetes y se corrige antes de declarar verde. No se compensa con una salida 0.

## Fuera de alcance

- Cualquier actualización mayor de dependencias del producto (`nuxt`, `vue`, `pinia`, `socket.io-client`, `@pinia/nuxt`, `@vue-flow/core`) o de herramientas (`typescript`, `vue-tsc`); si una corrección exigiera un mayor, el trabajo se detiene y se pregunta (RF-002).
- Subir TypeScript a 7.x, ya revertido por incompatibilidad con `vue-tsc`.
- Cambiar Python 3.14, Node 24, pnpm 12.12.1, las imágenes base o la versión y parámetros de Trivy.
- Ampliar la auditoría a `devDependencies` o cambiar el alcance de `--prod`.
- Bajar umbrales, desactivar pasos, ampliar directorios ignorados o introducir supresiones por CVE, GHSA, paquete o ruta; sustituir el filtro general por listas concretas o persistir exclusiones en la configuración del gestor.
- Revertir `pmOnFail: ignore`, mantener el documento de autogestión del lockfile o sustituir Trivy por otra herramienta de escaneo.
- Mantener, actualizar o alinear la cadena raíz en lugar de retirarla (decisión D-2).
- Prorrogar, renovar o renegociar la excepción §5.1; esta spec la retira.
- Parchear, bifurcar o fijar localmente paquetes sin versión corregida publicada.
- Cambios funcionales, de interfaz, de rutas, de contratos de API o de datos.
- Dependencias del backend: `pip-audit` está limpio y no forma parte de la deuda.
- Cualquier otro hallazgo de seguridad distinto de la credencial de D-5; si aparece, se reporta por separado y no se mezcla con esta spec.
- Reescribir el historial de git: la rotación de D-5 invalida el valor expuesto y es la mitigación exigida.
- Reescribir la herramienta de auditoría o sustituir pnpm/Trivy.

## Orden de aterrizaje

El orden evita que la §3.4 nombre un comando distinto del que ejecuta la CI y que el filtro se active sin pruebas.

| Paso | Pull request | Contenido y commits | Efecto |
|---|---|---|---|
| 1 | PR-1, filtro | Filtro `infra/scripts/audit_frontend.py` y sus pruebas. No toca el job `security`; las pruebas se añaden desde PR-1 a un job de CI existente. Un commit. | El job `security` no cambia; el filtro queda probado antes de usarse. |
| 2 | PR-2, política | Enmienda constitucional 1.2.0 (commit A), cableado del bloque de comando en CI desde la raíz con `pnpm --dir frontend` (commit B) y alineación de `AGENTS.md` y README con el mismo bloque (en uno de esos commits), en el mismo pull request. | Se fusionan juntos: en `main` no existe un estado donde la §3.4 exija un comando distinto del que ejecuta la CI o donde la guía esté desactualizada. La excepción §5.1 sigue vigente y cubre el rojo remanente. |
| 3 | PR-3, dependencias | Refresco completo del lockfile dentro de rangos, `pmOnFail: ignore` con lockfile de un solo documento, adaptación de `verify_version_sources.py` y sus tests, retirada de la cadena raíz y, si hace falta, exclusión temporal de edad de publicación. Dos o tres commits. | El job queda verde en vulnerabilidades y `infrastructure` en verde con el lockfile de un solo documento; el verde completo y la evidencia final requieren PR-4. La excepción aún no se retira. |
| 4 | PR-4, seguridad | Rotación de la credencial, retiro del archivo versionado (D-5) y artefacto de rotación, en un pull request separado. | Debe preceder o acompañar a la evidencia de verde; si el escáner de secretos de Trivy detecta la credencial, va antes de la evidencia final. Ningún PR declara el job verde antes. No se mezcla con dependencias. |
| 5 | PR-5, retiro documental | Spec 001 con la excepción retirada, `MEMORY.md` con «Riesgo residual» separado y corrección de la caracterización, y la referencia al lockfile en `AGENTS.md`, con la evidencia final de `main`. | Cierra la excepción; se hace después del verde y de D-5, con revisión humana. No rehace la alineación del comando, que ya está en PR-2. |

Ningún pull request mezcla la enmienda con cambios funcionales. El intervalo entre PR-2 y PR-3 puede seguir rojo por deuda accionable, pero está cubierto por la excepción §5.1, que no se retira hasta el PR-5. La evidencia final de verde no se emite hasta que PR-4 haya completado D-5 y el escaneo de secretos de Trivy se haya reproducido.

## Relación con la constitución

| Regla o criterio | Numeración | Cómo se cumple |
|---|---|---|
| Nada se da por terminado sin verificación | §2.8 | El cierre exige ejecutar las tres auditorías y adjuntar evidencia; lo no ejecutado se declara. |
| Las dependencias deben pasar las auditorías | §3.4 | Se enmienda a la versión 1.2.0 para que exija el bloque de comando efectivo de RF-003 (desde la raíz, `pnpm --dir frontend`, estado capturado, filtro `infra/scripts/audit_frontend.py`), que sigue fallando ante accionables; no se rebaja ningún principio ni criterio. |
| Versiones de referencia y lockfile versionado | §3.5 | Se mantienen Python 3.14, Node 24 y pnpm 12.12.1; el lockfile y el espacio de trabajo siguen versionados y la instalación usa `--frozen-lockfile`. |
| Pasa el job de CI correspondiente | §4, «Para todos los cambios» | El job `security` debe quedar verde con los umbrales vigentes y el filtro. |
| Lockfiles actualizados y auditorías en verde | §4, «Para cambios de dependencias» | Se actualiza el lockfile, se retira la cadena raíz y se ejecutan las tres auditorías con evidencia. |
| Cambios de frontend | §4, «Para cambios de frontend» | Aplica en las verificaciones: no cambian las llamadas HTTP ni las rutas, pero `pnpm test`, `pnpm run typecheck` y `pnpm run build` son obligatorios. |
| Cambios de infraestructura o despliegue | §4, «Para cambios de infraestructura o despliegue» | Aplica en CI: no se modifica Compose ni el perfil de producción, pero sí el job `security` y la verificación de versiones; `docker compose config -q` sigue siendo obligatorio y no cambia. |
| Documentación afectada actualizada | §4, «Para todos los cambios» | Se actualizan la guía del proyecto, el README y la memoria del retiro, incluida la caracterización de la deuda. |
| Excepciones acotadas, con responsable y condición de retiro | §5.1 | Esta spec **retira** la excepción; no la prorroga ni crea una nueva. El filtro no es una excepción: es un criterio general, visible, sin estado y revisable. |
| Evolución de la constitución | §5.2 | La enmienda de la §3.4 es obligatoria: versión menor 1.2.0, con motivo, impacto, revisión humana separada y sin mezclarse con cambios funcionales. |
| Definición de cumplimiento | §6 | Exige revisión humana distinta del autor y todos los jobs en verde; el retiro de la excepción se apoya en esa evidencia. |

## Criterios de finalización

1. El job `security` está en verde en la rama principal con el umbral de severidad high, el comando efectivo de RF-003 y Trivy CRITICAL/HIGH con `--ignore-unfixed`, sin pasos desactivados ni directorios ignorados ampliados; la evidencia demuestra cobertura real del frontend (target `frontend/pnpm-lock.yaml` con paquetes) y se emite después de D-5.
2. `pip-audit` sigue limpio; la cadena de producción del frontend no tiene hallazgos accionables (≥ high con corrección publicada); los no accionables y los moderados y bajos quedan visibles y no bloquean, y los informativos se contabilizan en `metadata.vulnerabilities.info` sin listarse.
3. El filtro está implementado en `infra/scripts/audit_frontend.py`, tiene pruebas propias que cubren los casos de RF-003 (incluidas las cuatro formas de «sin corrección», la ausencia de `advisories` y el desajuste con `metadata`), es determinista, no escribe archivos y no persiste listas; `frontend/pnpm-workspace.yaml` no contiene listas de advisories ni configuración de auditoría.
4. La política de D-1 y el mecanismo de D-1b están registrados en una enmienda constitucional 1.2.0, fusionada en el mismo pull request que el cableado de CI y la alineación de `AGENTS.md` y README, con commits separados y revisión humana; la §3.4 exige el comando efectivo exacto y conserva el fallo ante accionables.
5. Trivy no reporta hallazgos CRITICAL/HIGH con corrección disponible; la cadena raíz fue retirada del repositorio (D-2) tras comprobar que ninguna build, imagen ni verificación la usaba, y ya no aporta hallazgos.
6. La excepción §5.1 de la spec 001 está marcada como retirada, `MEMORY.md` ya no la declara vigente, separa «Riesgo residual» de «Pendiente», corrige la caracterización de «dependencias de desarrollo» y respeta el límite de ~50 líneas; `AGENTS.md` nombra `frontend/pnpm-lock.yaml` y ningún documento de estado actual afirma que el job sigue en rojo; los registros históricos fechados se permiten.
7. `pnpm install --frozen-lockfile`, `pnpm test`, `pnpm run typecheck` y `pnpm run build` pasan con las versiones de referencia, incluido cualquier movimiento de `devDependencies` directas dentro de rango o de transitivas de desarrollo; la imagen del frontend construye y arranca.
8. El alcance se mantiene en el mínimo de D-3: no se cambiaron las versiones fijadas de CI, no se introdujeron mayores, no hubo modernización en el sentido de la definición (no cambiaron las declaraciones de rango ni las versiones mayores), no se añadieron dependencias de producto y el lockfile y el espacio de trabajo siguen versionados; `frontend/pnpm-workspace.yaml` declara `pmOnFail: ignore` y el lockfile queda en un solo documento.
9. Los advisories sin corrección están registrados en la sección «Riesgo residual» de `MEMORY.md` con identificador, motivo, responsable (el propietario del producto) y condición de revisión (cada actualización de dependencias y la próxima auditoría técnica); el parche se adopta en el mismo cambio en que aparezca.
10. La credencial de D-5 fue rotada y retirada del archivo versionado antes de declarar el verde; el artefacto de rotación registra fecha, responsable y confirmación de revocación, sin el valor ni el host; el árbol y el índice de git no la contienen y el valor antiguo ya no es válido.
11. Se reprodujo el escaneo de secretos de Trivy y su resultado consta en la evidencia; si detecta la credencial, PR-4 se completó antes de la evidencia final.
12. Se respetó el orden de aterrizaje: filtro probado y añadido a un job existente antes de activarse, enmienda y comando de CI con guía alineada en el mismo pull request, actualización de dependencias después, rotación de la credencial antes de la evidencia final y retiro documental al final.
13. Las verificaciones no ejecutadas se declaran como tales y el cambio tiene revisión humana distinta del autor, conforme a la §6.

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Quedan advisories altos sin corrección y moderados o bajos visibles; los informativos solo se contabilizan | El job queda verde con riesgo residual | Los altos sin corrección y los moderados/bajos se muestran; los informativos quedan en `metadata.vulnerabilities.info`. Se registran en `MEMORY.md` y se revisan en cada actualización y en la próxima auditoría (D-4). |
| El filtro se convierte en una lista de exclusiones persistente | Se repite la deuda que esta spec quiere cerrar | El filtro no escribe ni persiste estado; se prohíben listas de GHSA como exclusiones, `audit.ignore` y `auditConfig.ignoreGhsas`, y las pruebas verifican que no se modifica el espacio de trabajo. |
| Un fallo del filtro produce un falso verde | Se oculta un riesgo accionable | Fallo cerrado ante JSON inválido o esquema inesperado, comparación de `advisories` con `metadata.vulnerabilities`, pruebas con fixtures y contraste con Trivy; si divergen, prevalece el fallo. |
| El escaneo de secretos de Trivy no se reproduce | Se declara un verde sin evidencia del secreto | Se reproduce en la validación; si detecta la credencial, PR-4 se completa antes de la evidencia final. |
| El paso de CI se ejecuta desde `frontend/` y el filtro no se encuentra | El job falla o audita otro árbol | Comando fijo desde la raíz con `pnpm --dir frontend`; `working-directory` en la raíz o omitido; no se usa `working-directory: frontend`. |
| La retirada de la cadena raíz rompe una build o una verificación | CI o imagen rota | Comprobación previa de usos y parada con reporte si algo depende de ella; no se retira a ciegas. |
| La credencial expuesta sigue vigente | Uso no autorizado del valor del historial | Rotación obligatoria antes del cierre, retiro del archivo versionado y comprobación de que el valor antiguo ya no sirve. |
| La enmienda y el comando de CI se desalinean | La §3.4 exige algo distinto de lo que ejecuta la CI | Mismo pull request con commits separados y fusión atómica; la excepción cubre el intervalo rojo hasta el PR de dependencias. |
| La retención de publicaciones impide instalar la versión corregida | El hallazgo accionable persiste | Exclusión temporal y exacta en `minimumReleaseAgeExclude`, justificada y con retiro; no se desactiva la política ni se instala una versión vulnerable. |
| El refresco mueve `devDependencies` directas dentro de rango o transitivas de desarrollo | Regresión no detectada | Se ejecutan `pnpm test`, `typecheck` y `build`; cualquier cambio de comportamiento detiene el trabajo. |

## Dudas abiertas

Sin dudas abiertas (2026-10-19). Las siete decisiones están registradas en «Decisiones cerradas (2026-10-19)» y reflejadas en los requisitos, las definiciones, los casos límite, la tabla de constitución y los criterios de finalización. Los conteos exactos de advisories y el resultado del escaneo de secretos son evidencia a reproducir en la fase de validación (RF-010), no una duda de requisito. La spec sigue aprobada; la desviación D-6 se registró durante la implementación con aprobación del usuario.
