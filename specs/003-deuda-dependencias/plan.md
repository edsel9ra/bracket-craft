# Plan 003 — Retiro de la deuda de dependencias del frontend

## 1. Objetivo y alcance

Implementar la spec 003 en cinco entregas ordenadas, sin cambios funcionales ni de contrato: filtro propio de auditoría, enmienda constitucional 1.2.0, refresco mínimo del lockfile del frontend, retirada de la cadena de dependencias muerta de la raíz, rotación de la credencial expuesta y retiro documental de la excepción §5.1.

El plan no introduce dependencias nuevas ni cambios mayores. Si el refresco exigiera un mayor, el trabajo se detiene y se pregunta (RF-002).

## 2. Archivos y responsabilidades

| Archivo | Responsabilidad | RF |
|---|---|---|
| `infra/scripts/audit_frontend.py` (nuevo) | Filtro determinista: parseo, validación de esquema, juicio de accionables, comparación con `metadata`, salida legible y códigos de salida. Sin red, reloj ni estado global. | RF-003, RNF-009 |
| `backend/tests/test_audit_frontend.py` (nuevo) | Pruebas unitarias y de CLI del filtro, cargando el módulo con `importlib` como las pruebas de `verify_version_sources.py`. Se ejecutan en el job `backend` existente. | RF-003, RF-010 |
| `.github/workflows/ci.yml` | Paso `security` desde la raíz, con `pnpm --dir frontend`, captura de `$?`, archivo temporal y filtro. Sin `working-directory: frontend`. | RF-001, RF-003, RF-009 |
| `docs/constitution.md` | Enmienda 1.2.0: cabecera, historial y §3.4 con el bloque efectivo; conserva el fallo ante accionables. | RF-009 |
| `AGENTS.md` | Comando efectivo y filtro en la sección de verificación; referencia a `frontend/pnpm-lock.yaml`. | RF-005, RF-009 |
| `README.md` | Comando efectivo, política de no accionables y requisito de Node 24/pnpm 12.12.1. | RF-009 |
| `frontend/package.json` | No cambian las declaraciones de rango. Solo se verifica que el diff sea vacío; el pin `pnpm@12.12.1` sigue aquí y es la fuente para el formato de un documento. | RF-002, RF-008 |
| `frontend/pnpm-lock.yaml` | Refresco completo de la resolución dentro de los rangos declarados y formato de un solo documento con `pmOnFail: ignore`. Versionado. | RF-002, RF-007, RF-008 |
| `frontend/pnpm-workspace.yaml` | `pmOnFail: ignore` (D-6) y, si hace falta, entradas temporales de `minimumReleaseAgeExclude` para versiones exactas. Sin listas de auditoría. | RF-002, RF-008, RNF-001 |
| `infra/scripts/verify_version_sources.py` | Acepta el lockfile de dos documentos (comportamiento actual) y el de uno solo, validando el pin desde `frontend/package.json` y las dependencias desde el importer raíz. | RF-008 |
| `backend/tests/test_version_sources.py` | Pruebas de ambos formatos del verificador; se mantienen las del formato de dos documentos. | RF-008 |
| `package.json` y `pnpm-lock.yaml` de la raíz | Se retiran tras comprobar que ninguna build, imagen o verificación los usa. | RF-004 |
| `opencode.json` | Se sustituye la credencial literal por una referencia `{env:...}` o `{file:...}`. Sin reproducir el valor. | RF-011 |
| `specs/001-correctivos-p0-auditoria/spec.md` | Se marca la excepción §5.1 como retirada y se corrige la caracterización de la deuda. | RF-005 |
| `MEMORY.md` | Sección «Riesgo residual» separada de «Pendiente», retiro de la deuda y límite de ~50 líneas. | RF-005, RF-006 |

No se tocan routers, módulos de backend, migraciones, `frontend/app/`, `useApi.ts`, Compose ni `.env.example`.

## 3. Funciones puras y estructura del filtro

El filtro separa lógica pura de E/S. Solo `main()` lee archivos y escribe en stdout.

Funciones puras (sin reloj, red, variables globales mutables ni acceso al sistema de archivos):

- `parse_report(raw: str) -> Mapping[str, Any]`: `json.loads` y comprobación de que la raíz es un objeto.
- `published_fix(advisory: Mapping[str, Any]) -> bool`: `patched_versions` presente, `str`, no vacía y `patched_versions_unpublished is not True`.
- `is_actionable(advisory: Mapping[str, Any]) -> bool`: severidad en `{"high", "critical"}` y `published_fix`.
- `count_by_severity(advisories: Mapping[str, Any]) -> dict[str, int]`.
- `validate_schema(report: Mapping[str, Any]) -> list[str]`: `advisories` obligatorio y objeto; `metadata` y `metadata.vulnerabilities` obligatorios; severidades conocidas; tipos correctos; `metadata.dependencies` si existe.
- `validate_metadata(advisories, metadata) -> list[str]`: compara `low`, `moderate`, `high` y `critical`; claves ausentes cuentan como cero; `info` solo se registra; `dependencies: 0` con advisories es incoherente.
- `decide(report, pnpm_status: int) -> Decision`: produce `exit_code`, `actionables`, `visible`, `info_count` y `errors`.
- `render_decision(decision) -> str`: texto legible con IDs, paquete, severidad, versión afectada y motivo.

E/S (solo en `main()`): leer `--input` o `-` (stdin), validar `--pnpm-status`, imprimir y devolver el código.

Códigos de salida: `0` sin accionables; `1` con al menos un accionable; `2` entrada inválida, esquema incoherente o estado de pnpm inválido. La CI trata cualquier código distinto de 0 como fallo.

## 4. Pseudocódigo del filtro

```text
main(argv):
    args = parse_args(argv)                  # --input, --pnpm-status obligatorios
    if args.pnpm_status is None or args.pnpm_status < 0:
        print("estado de pnpm ausente o inválido"); return 2
    if args.pnpm_status > 1:
        print("pnpm audit falló por una causa operativa"); return 2

    raw = read_input(args.input)             # archivo o stdin; sin red
    report = parse_report(raw)                # JSON inválido -> 2
    errors = validate_schema(report)
    if errors: print(errors); return 2

    advisories = report["advisories"]        # obligatorio; {} es válido
    metadata = report["metadata"]["vulnerabilities"]

    errors = validate_metadata(advisories, metadata)
    if errors: print(errors); return 2

    actionables = []
    visible = []
    for advisory in advisories.values():
        if is_actionable(advisory):
            actionables.append(advisory)
        elif advisory["severity"] in {"high", "moderate", "low"}:
            visible.append(advisory)
        # info no se espera en advisories con --audit-level low;
        # solo se contabiliza metadata.vulnerabilities.info

    if actionables:
        print(render_actionables(actionables))
        print(render_visible(visible))
        return 1

    print(render_visible(visible))
    print(f"informativos contabilizados: {metadata.get('info', 0)}")
    return 0
```

Reglas cerradas:

- `advisories` ausente no es «cero hallazgos»: es error `2`. Solo `advisories: {}` representa vacío.
- `patched_versions` ausente, `null`, cadena vacía o `patched_versions_unpublished: true` significan «sin corrección»; no son errores de esquema.
- `metadata.vulnerabilities` se compara por severidad con `advisories`; un desajuste es error `2`.
- Los informativos no se listan: `--audit-level low` los excluye de `advisories`; solo se contabilizan en `metadata.vulnerabilities.info`.
- `--pnpm-status` es obligatorio y explícito; el filtro decide, no la tubería.

## 5. Comando exacto y ubicación

Se ejecuta desde la raíz del repositorio. El paso de CI usa `working-directory` en la raíz (o lo omite); no usa `working-directory: frontend`.

```sh
AUDIT_JSON="/tmp/pnpm-audit.json"
trap 'rm -f "$AUDIT_JSON"' EXIT
if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
```

Ubicaciones obligatorias, con el mismo bloque:

- `docs/constitution.md` §3.4 (enmienda 1.2.0).
- `AGENTS.md`, sección de verificación/seguridad.
- `README.md`, sección de verificación.
- `.github/workflows/ci.yml`, paso `security`, sin `working-directory: frontend`.

El archivo temporal vive en `/tmp`, fuera del repositorio, y se elimina con `trap` incluso si el filtro falla. No hay tubería: el estado de pnpm se captura y se pasa a `--pnpm-status`.

## 6. Enmienda constitucional 1.2.0

Cambios exactos en `docs/constitution.md`:

- **Cabecera:** versión `1.2.0`, fecha `2026-10-19`.
- **§3.4:** sustituir la exigencia literal de `pnpm audit --prod --audit-level high` por el bloque efectivo anterior, manteniendo que las dependencias deben pasar `pip-audit`, la auditoría del frontend con el filtro y Trivy, y que el filtro **sigue fallando ante hallazgos accionables**.
- **Historial:** nueva fila `1.2.0` con motivo (retirar la deuda y hacer explícita la política de no accionables), regla afectada (§3.4) e impacto (CI y documentación; sin cambio funcional).
- **Sin cambios** en principios innegociables, §3.5, §4, §5.1, §5.2 ni §6.

La enmienda, el cableado de CI y la alineación de `AGENTS.md`/README se fusionan en el mismo PR (PR-2), con commits separados. Así no existe un estado en `main` donde la §3.4 exija un comando distinto del que ejecuta la CI o donde la guía esté desactualizada.

## 7. Estrategia de tests del filtro

`backend/tests/test_audit_frontend.py` se ejecuta con `pytest` en el job `backend` existente; no se crea un job nuevo. Carga `infra/scripts/audit_frontend.py` con `importlib` y usa fixtures JSON en memoria.

Casos mínimos:

1. Accionable `critical` con `patched_versions: ">=1.2.3"` → `1`.
2. Accionable `high` con `patched_versions: ">=4.0.1"` → `1`.
3. `high` sin corrección con `patched_versions` ausente, `null`, `""` y `patched_versions_unpublished: true` → `0`, visible.
4. `moderate` y `low` con corrección → `0`, visibles.
5. Informativo solo en `metadata.vulnerabilities.info` → `0`, contabilizado y no listado.
6. `advisories: {}` con `metadata` en cero → `0`.
7. `advisories` ausente → `2`, aunque `metadata` sea cero.
8. `advisories` no es objeto; severidad desconocida; `patched_versions` con tipo inválido → `2`.
9. Desajuste entre `advisories` y `metadata.vulnerabilities` → `2`.
10. `metadata.dependencies: 0` con advisories → `2`.
11. `--pnpm-status` ausente, negativo, no entero o mayor que 1 → `2`.
12. CLI: leer desde `--input` y desde `-`; no escribir archivos en el directorio de trabajo; imprimir IDs y códigos esperados.

Comandos:

```sh
cd backend && python3 -m pytest -q tests/test_audit_frontend.py
cd backend && pytest -q
python3 -m py_compile infra/scripts/audit_frontend.py
```

Las pruebas de CLI usan `subprocess.run` con `cwd=tmp_path` y `PYTHONDONTWRITEBYTECODE=1`, y comprueban que el directorio queda vacío. Los casos puros no tocan red, reloj ni disco.

### 7.1 Tests de `verify_version_sources.py` (D-6)

`backend/tests/test_version_sources.py` mantiene los casos de dos documentos y añade:

- Un fixture de lockfile de un solo documento con `pmOnFail: ignore`, pin `pnpm@12.12.1` en `frontend/package.json` y dependencias en el importer raíz → válido.
- Un fixture de un solo documento sin `pmOnFail` → inválido, porque el formato no está declarado.
- Un fixture de un solo documento con el pin ausente o distinto → inválido.
- Los casos actuales de dos documentos siguen pasando sin cambios de comportamiento.

Comandos: `cd backend && python3 -m pytest -q tests/test_version_sources.py`, `cd backend && pytest -q` y `python3 infra/scripts/verify_version_sources.py --exclude-constitution`.

## 8. Refresco de dependencias (D-3) y lockfile de un solo documento (D-6)

- Declarar `pmOnFail: ignore` en `frontend/pnpm-workspace.yaml` para que pnpm no escriba el documento de autogestión. CI sigue fijando pnpm 12.12.1 con `pnpm/action-setup`; el pin de `frontend/package.json` no cambia.
- Ejecutar con Node 24 y pnpm 12.12.1, desde `frontend/`, `pnpm update --lockfile-only` para refrescar la resolución completa dentro de los rangos declarados. No se usa `--prod`: se evita una resolución mixta.
- No se editan las declaraciones de rango de `frontend/package.json`; el diff de ese archivo debe quedar vacío.
- Puede mover `devDependencies` directas dentro de rango (`typescript`, `vue-tsc`, `@types/node`) y transitivas de desarrollo; no es «modernización» según la definición de la spec (no cambian declaraciones ni mayores).
- Si `minimumReleaseAge` bloquea una versión corregida, añadir solo esa versión exacta a `minimumReleaseAgeExclude` en `frontend/pnpm-workspace.yaml`, con motivo y condición de retiro. Las entradas existentes de Pinia se conservan; la evidencia registra las que carezcan de motivo.
- Ejecutar `pnpm install --frozen-lockfile`, `pnpm test`, `pnpm run typecheck` y `pnpm run build`.
- Ejecutar el comando efectivo: deben quedar cero accionables. Si un accionable persiste o exige un mayor, detenerse y reportar.
- Verificar que el lockfile queda en **un solo documento**: `lockfileVersion` aparece una vez, no hay `packageManagerDependencies` y no hay separador `---` entre documentos. El lockfile sigue versionado y `frontend/pnpm-workspace.yaml` no contiene listas de GHSA ni configuración de auditoría.
- Evidencia de cobertura de Trivy: el target `frontend/pnpm-lock.yaml` debe aparecer con paquetes analizados (620 en la verificación) y, al ejecutar sin `--ignore-unfixed`, deben aparecer los 2 HIGH sin parche (`braces`, `node-forge`). Una salida 0 sin target del frontend no cuenta.

### 8.1 Adaptación de `verify_version_sources.py`

El verificador actual exige dos documentos: busca `packageManagerDependencies` y el bloque `pnpm@12.12.1` en el primero y las dependencias en el segundo. La adaptación mantiene ambos caminos:

- **Dos documentos:** comportamiento actual sin cambios; sigue validando el pin del primer documento y las dependencias del segundo.
- **Un solo documento con `pmOnFail: ignore`:** valida el pin `pnpm@12.12.1` desde `frontend/package.json` y las dependencias resueltas desde el importer raíz del lockfile. No exige `packageManagerDependencies` ni el separador `---`.
- En ambos casos conserva la comprobación de que las versiones resueltas existen y de que las dependencias declaradas están en el lockfile.
- Tests: los casos de dos documentos se mantienen sin cambios de comportamiento; se añade un fixture de un solo documento con `pmOnFail: ignore` y el pin en `package.json`, más un caso de un solo documento sin `pmOnFail` que debe fallar.
- Comandos: `cd backend && python3 -m pytest -q tests/test_version_sources.py`, `cd backend && pytest -q` y `python3 infra/scripts/verify_version_sources.py --exclude-constitution`.

## 9. Retirada de la cadena raíz (D-2)

1. Comprobar usos con `git grep`, Dockerfiles, CI, README y Compose; confirmar que ninguna build, imagen ni verificación usa el manifiesto o el lockfile raíz.
2. Registrar la comprobación en la descripción del PR y en la evidencia de validación.
3. Retirar `package.json` y `pnpm-lock.yaml` de la raíz con `git rm`; `node_modules` raíz está ignorado y no se versiona.
4. Ejecutar `docker compose config -q`, `cd frontend && pnpm install --frozen-lockfile` y el escaneo Trivy; confirmar que desaparecen los 4 hallazgos de la cadena raíz y que no aparece ninguno nuevo.
5. Si algo dependiera de esa cadena, detenerse y reportar; no se mantiene por inercia ni se oculta del escaneo.

## 10. Rotación de la credencial (D-5)

1. Rotar/revocar la credencial en el proveedor correspondiente; confirmar que el valor anterior deja de ser válido.
2. Sustituir el valor literal en `opencode.json` por una referencia `{env:...}` o `{file:...}`; el archivo local de referencia debe estar ignorado.
3. Registrar el artefacto de rotación: fecha, responsable y confirmación de revocación en el proveedor. Sin valor, sin host y sin cabecera completa con valor.
4. Comprobar el árbol de trabajo y el índice de git; ejecutar el escaneo de secretos de Trivy.
5. PR separado, con revisión propia. Es bloqueante para declarar el job verde y cerrar la spec; no se mezcla con dependencias.
6. No se reescribe el historial de git: la rotación invalida el valor expuesto. Si el escaneo de secretos detecta la credencial, PR-4 se completa antes de la evidencia final.

## 11. MEMORY.md y retiro de la excepción §5.1

- `MEMORY.md` incorpora la spec 003 como aprobada (2026-10-19), en planificación, con las siete decisiones y el diagnóstico; la deuda deja de figurar como «siguiente bloque».
- `MEMORY.md` separa «Riesgo residual» de «Pendiente»; la sección residual lista los GHSA sin corrección, el motivo, el responsable y la condición de revisión. Se resume o poda para respetar ~50 líneas.
- `specs/001-correctivos-p0-auditoria/spec.md` marca la excepción §5.1 como retirada, remite a la spec 003 y corrige la caracterización de «dependencias de desarrollo».
- `AGENTS.md` nombra `frontend/pnpm-lock.yaml`; la alineación del comando ya está en PR-2.
- Ningún documento de estado actual afirma que el job sigue en rojo; los registros históricos fechados se permiten.
- El retiro documental se hace después de la evidencia final y de D-5.

## 12. Interfaz

**No aplica.** No hay endpoints, pantallas, rutas ni contratos de API nuevos. La única interfaz nueva es la CLI del filtro:

```text
python3 infra/scripts/audit_frontend.py --input <archivo|-> --pnpm-status <0|1>
```

Sale con `0` (sin accionables), `1` (accionables) o `2` (entrada/estado inválido) e imprime un resumen legible en stdout. No escribe archivos.

## 13. Decisiones justificadas

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Filtro propio sin estado. | `--ignore-unfixable` o listas de GHSA. | pnpm persiste los IDs en `pnpm-workspace.yaml` y no los poda automáticamente; una decisión transitoria se volvería una lista opaca y permanente. |
| Retirar la cadena raíz. | Mantenerla y actualizarla. | No participa en build, imágenes ni CI, contradice `AGENTS.md` y aporta 4 hallazgos de Trivy. |
| Refresco completo dentro de rangos. | `pnpm update --prod`. | Una resolución mixta es más difícil de reproducir; el refresco completo está cubierto por tests y no cambia declaraciones. |
| Lockfile de un solo documento con `pmOnFail: ignore` (D-6). | Mantener el lockfile de dos documentos. | Trivy 0.70.0 solo lee el primer documento; con dos no audita el frontend y el verde es vacuo. `pmOnFail` evita el documento de autogestión y CI fija la versión. |
| Adaptar `verify_version_sources.py` a ambos formatos. | Revertir `pmOnFail` o relajar la comprobación del pin. | Mantiene `infrastructure` en verde sin perder la validación del pin ni de las dependencias resueltas. |
| Alcance mínimo (D-3). | Modernización de Nuxt/Pinia/Socket.IO. | No es necesaria para cero accionables y mezcla deuda con actualización de producto; aumenta el riesgo. |
| Archivo temporal con `$?` explícito. | Tubería `pnpm audit \| filtro`. | La tubería no conserva el estado de pnpm y `pipefail` puede abortar antes del veredicto. |
| Enmienda, CI y guía en el mismo PR. | Entregas separadas. | Evita un estado en `main` con la constitución enmendada y la guía o el comando desalineados. |
| Rotar la credencial. | Borrar el archivo o reescribir el historial. | El valor está en el historial; solo la rotación lo invalida. La reescritura del historial está fuera de alcance. |
| Pruebas del filtro en el job `backend`. | Job nuevo. | Reutiliza el runner de `pytest` y evita coste adicional; el filtro es Python. |
| `advisories` obligatorio. | Tratar su ausencia como cero. | Un JSON truncado o un cambio de esquema debe fallar de forma cerrada, no producir un falso verde. |

## 14. Cobertura de requisitos

| RF | Dónde se cubre |
|---|---|
| RF-001 | T3 (CI), T7 (evidencia, cobertura de Trivy y rama principal), T9 (verificación final). |
| RF-002 | T4 (refresco y auditoría sin accionables). |
| RF-003 | T1 (filtro y pruebas), T3 (cableado), T7 (ejecución). |
| RF-004 | T5 (comprobación y retirada de la cadena raíz). |
| RF-005 | T8 (spec 001, MEMORY, AGENTS). |
| RF-006 | T8 (sección «Riesgo residual» y revisión D-4). |
| RF-007 | T4 (tests, typecheck, build e imagen). |
| RF-008 | T4, T4b y T5 (lockfile de un documento, verificador de ambos formatos, versiones y cadena raíz). |
| RF-009 | T2 y T3 (enmienda, CI, AGENTS, README). |
| RF-010 | T7 y T9 (evidencia fechada, conteos, jobs). |
| RF-011 | T6 (rotación, referencia y artefacto). |

## 15. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 1. Aislamiento por tenant en la base de datos | No | No se tocan tablas, RLS, migraciones ni datos. |
| 2. La aplicación no se salta RLS | No | No se cambia el rol de base de datos ni la configuración de acceso. |
| 3. Lo publicado es inmutable | No | No se tocan torneos, versiones ni resultados. |
| 4. Historial de esquema append-only | No | No hay cambios de esquema. |
| 5. Lo público es una proyección mínima | No | No se tocan proyecciones públicas ni datos de jugadores. |
| 6. Ningún secreto por defecto fuera de desarrollo | Sí | D-5 retira la credencial versionada y usa referencia externa; no se añaden defaults reales. |
| 7. Administración global separada y auditada | No | No se toca `/admin` ni `platform_audit_logs`. |
| 8. Nada se da por terminado sin verificación | Sí | Evidencia de las tres auditorías, jobs de CI y declaración de lo no ejecutado. |
| 9. El código de desarrollo no llega a producción | No | No se tocan seeds ni datos demo. |
| §3.4 Auditorías de dependencias | Sí | Enmienda 1.2.0 con el bloque efectivo; el filtro sigue fallando ante accionables. |
| §3.5 Versiones de referencia y lockfile | Sí | Python 3.14, Node 24, pnpm 12.12.1; lockfile versionado y `--frozen-lockfile`. |
| §4 «Para todos los cambios» (CI) | Sí | Job `security` en verde con evidencia y revisión humana. |
| §4 «Para cambios de dependencias» | Sí | Lockfile actualizado, auditorías en verde y cadena raíz retirada. |
| §4 «Para cambios de frontend» | Sí | `pnpm test`, `pnpm run typecheck` y `pnpm run build`; no hay cambios de `useApi.ts` ni de rutas. |
| §4 «Para cambios de infraestructura o despliegue» | Sí (CI) | No se modifica Compose, pero sí el job `security` y `verify_version_sources.py`; `docker compose config -q` sigue pasando y no cambia. |
| §5.1 Excepciones | Sí | Se retira la excepción; no se crea otra. El filtro es un criterio general, visible y sin estado. |
| §5.2 Evolución constitucional | Sí | Enmienda menor 1.2.0, con motivo, impacto, revisión separada y sin cambios funcionales. |
| §6 Definición de cumplimiento | Sí | Revisión humana distinta del autor y jobs en verde. |

## 16. Apartados específicos del proyecto

- **Base de datos:** No aplica. No hay migraciones, tablas, RLS ni políticas nuevas; no se toca `infra/postgres/`.
- **Backend:** No aplica funcionalmente. No hay routers, módulos ni consultas nuevas. Solo se añade un script de infraestructura en Python y un archivo de pruebas en `backend/tests/`; no se registra router.
- **Frontend:** solo cambian `frontend/pnpm-lock.yaml` (formato de un solo documento) y `frontend/pnpm-workspace.yaml` (`pmOnFail: ignore` y, si hace falta, exclusiones de edad). No cambian `frontend/app/`, `useApi.ts`, rutas, componentes ni contratos. Se exigen `pnpm test`, `typecheck` y `build`.
- **Exposición pública:** No aplica. No se modifican proyecciones públicas, documentos, fechas de nacimiento, fotos ni consentimiento.
- **Configuración y secretos:** D-5 rota la credencial y la sustituye por `{env:...}` o `{file:...}`. No se añaden variables nuevas a `.env.example` ni defaults reales; el valor no se reproduce en documentos, logs, PRs ni evidencia.
- **Eventos asíncronos:** No aplica. No se tocan outbox, worker, Redis ni Socket.IO.

## 17. Orden de aterrizaje

| PR | Tareas | Contenido | Dependencia |
|---|---|---|---|
| PR-1 | T1 | Filtro y pruebas; sin tocar el job `security`; pruebas en el job `backend` existente. | — |
| PR-2 | T2, T3 | Enmienda 1.2.0 (commit A), cableado de CI y alineación de `AGENTS.md`/README (commit B), mismo PR. | T1 |
| PR-3 | T4, T4b, T5 | Refresco del lockfile con `pmOnFail: ignore` y un solo documento, adaptación de `verify_version_sources.py`/tests y retirada de la cadena raíz; un PR con dos o tres commits. | T3 |
| PR-4 | T6 | Rotación de la credencial y retiro del valor versionado, PR separado. | — (bloqueante antes de T7) |
| Evidencia | T7 | Tres auditorías con Node 24/pnpm 12.12.1; cobertura de Trivy del frontend (620 paquetes, 2 HIGH sin ignore); `security` en verde; escaneo de secretos reproducido. | T4b, T5, T6 |
| PR-5 | T8 | Retiro de la excepción §5.1, `MEMORY.md` con «Riesgo residual» y corrección de la caracterización. | T7 |
| Cierre | T9 | Verificación de los cuatro jobs, comandos de validación y checklist de merge. | T8 |

## 18. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Filtro con falso verde | Fallo cerrado ante esquema inválido, `advisories` ausente, desajuste con `metadata` o estado de pnpm inválido; pruebas de fixtures y contraste con Trivy. |
| Deriva de la base de advisories | Criterio «cero accionables» en la validación, no conteos fijos; evidencia fechada. |
| `minimumReleaseAge` bloquea el parche | Exclusión temporal de versión exacta, con motivo y retiro; sin desactivar la política. |
| La retirada de la cadena raíz rompe algo | Comprobación previa de usos y parada con reporte. |
| El lockfile vuelve a dos documentos o pierde `pmOnFail` | Trivy deja de auditar el frontend; la evidencia exige target con paquetes y los 2 HIGH sin ignore; se corrige antes del verde. |
| `verify_version_sources.py` no entiende el formato de un documento | Se adapta con tests de ambos formatos; el pin se valida desde `package.json` y las dependencias desde el importer raíz. |
| El comando se ejecuta desde `frontend/` | Bloque único desde la raíz con `pnpm --dir frontend`; `working-directory` en la raíz. |
| La credencial sigue vigente | Rotación obligatoria y artefacto con confirmación de revocación antes de la evidencia final. |
| Enmienda y CI desalineados | Mismo PR con commits separados; §3.4, guía y CI con el mismo bloque. |
