# Evidencia de auditorías — Spec 003 (T7)

**Fecha de ejecución:** 2026-10-19, 21:46 (UTC-05). Las marcas internas de Trivy aparecen en UTC
(2026-10-20 por la madrugada).
**Estado:** **evidencia local completa; verde en CI pendiente de PR.** Las auditorías se ejecutaron
realmente y sus códigos de salida están abajo. El job `security` **no** está verde en la rama principal
hoy (§6) y este cambio no se ha publicado, así que no se afirma un verde de CI.

Esta evidencia no reproduce credenciales, tokens, hosts ni datos personales. Solo contiene nombres de
paquetes, versiones, severidades e identificadores de advisories/CVE.

## 1. Entorno y versiones usadas

| Herramienta | Versión | Cómo se ejecutó |
|---|---|---|
| Python | 3.14.8 | contenedor `python:3.14-slim` |
| `pip-audit` | 2.10.1 | instalado en ese contenedor |
| Node | v24.22.0 | contenedor `node:24-alpine` |
| pnpm | 12.12.1 | `npm i -g pnpm@12.12.1` en ese contenedor |
| Trivy | 0.70.0 | imagen `ghcr.io/aquasecurity/trivy:0.70.0` |
| Docker / Compose | 29.8.2 / 5.5.1 | host |

`aquasecurity/trivy-action@v0.36.0` usa `v0.70.0` por defecto, así que **la versión de Trivy coincide
con la de CI**. La base de vulnerabilidades se descargó el `2026-10-20T02:44:17Z` desde
`mirror.gcr.io` (129.11 MiB).

**La base de advisories es viva:** los conteos de esta evidencia pueden cambiar en una ejecución
posterior. El criterio de éxito es «cero hallazgos accionables y política aplicada», no un número fijo.

En el host no hay `pip-audit`, `trivy` ni `pnpm`; cada auditoría se ejecutó en el contenedor de la
versión de referencia, con el repositorio montado. El bloque del frontend se ejecutó en dos pasos
equivalentes a CI —`pnpm audit` en el contenedor Node, filtro con el `python3` del host— porque
`node:24-alpine` no trae Python; el estado de pnpm se capturó y se pasó explícitamente, como en CI.

## 2. `pip-audit` (RF-001, RF-010)

```sh
python -m pip install pip-audit
pip-audit -r backend/requirements.txt
```

Resultado: `No known vulnerabilities found`. **Código de salida 0.**

## 3. Auditoría del frontend con el comando efectivo (RF-001, RF-003, RF-010)

Comando, desde la raíz del repositorio, idéntico a la constitución §3.4, `AGENTS.md` y CI:

```sh
AUDIT_JSON="/tmp/pnpm-audit.json"
trap 'rm -f "$AUDIT_JSON"' EXIT
if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
```

- `pnpm --dir frontend audit --prod --json --audit-level low`: **código 1** (encontró advisories),
  capturado como `status=1` y pasado al filtro como `--pnpm-status 1`.
- `infra/scripts/audit_frontend.py --input … --pnpm-status 1`: **código 0**, sin hallazgos accionables.
- El archivo temporal se creó fuera del repositorio y se eliminó con `trap`.

### 3.1 Forma del JSON de pnpm

| Comprobación | Resultado |
|---|---|
| `advisories` presente | Sí |
| `advisories` es objeto | Sí (2 entradas) |
| GHSA únicos | **2** |
| `metadata.vulnerabilities.critical` | 0 |
| `metadata.vulnerabilities.high` | 2 |
| `metadata.vulnerabilities.moderate` | 0 |
| `metadata.vulnerabilities.low` | 0 |
| `metadata.vulnerabilities.info` | 0 |
| `metadata.dependencies` | 538 |
| `metadata.devDependencies` | 0 |
| `metadata.optionalDependencies` | 80 |
| `metadata.totalDependencies` | 618 |

### 3.2 Advisories (los dos únicos, ambos no accionables)

| GHSA | Paquete | Severidad | Versiones afectadas | `patched_versions` | Motivo |
|---|---|---|---|---|---|
| `GHSA-86w9-cpqp-85rv` | `node-forge` | high | `<=1.4.0` | `null` (`patched_versions_unpublished: true`) | Sin corrección publicada |
| `GHSA-vfj7-8cjw-p6xm` | `braces` | high | `<=3.0.3` | `null` (`patched_versions_unpublished: true`) | Sin corrección publicada |

**Accionables: 0.** **Visibles: 2** (`node-forge`, `braces`). **Informativos contabilizados: 0**
(`--audit-level low` excluye `info` de `advisories`; solo se cuenta en `metadata.vulnerabilities.info`,
que está en cero).

Política aplicada: falla solo ante severidad `high`/`critical` **con** corrección publicada en
`patched_versions`. Los dos hallazgos sin corrección no bloquean, se muestran y se revisan en cada
actualización de dependencias y en la próxima auditoría técnica (responsable: propietario del
producto). No se usa ninguna lista de GHSA ni flag que persista exclusiones.

## 4. Trivy (RF-001, RF-010)

### 4.1 Escaneo con los parámetros exactos de CI

```sh
trivy fs . --skip-dirs frontend/node_modules,frontend/.pnpm-store,.venv \
  --ignore-unfixed --severity CRITICAL,HIGH --exit-code 1
```

Resultado: **código de salida 0.** Targets reportados:

| Target | Tipo | Vulnerabilidades |
|---|---|---|
| `backend/requirements.txt` | pip | 0 |
| `frontend/pnpm-lock.yaml` | pnpm | 0 |

El target del frontend **aparece** en el escaneo: el lockfile es de un solo documento
(`lockfileVersion` una vez, sin separador `---`, sin `packageManagerDependencies`), así que Trivy lo
interpreta completo. No se ampliaron directorios ignorados ni se cambió la severidad.

### 4.2 Cobertura real del frontend (prueba exigida por T7)

El mismo escaneo **sin `--ignore-unfixed`** y con `--severity CRITICAL,HIGH --exit-code 1`:

Resultado: **código de salida 1**, con exactamente **2 vulnerabilidades HIGH**, ambas en
`frontend/pnpm-lock.yaml`:

| CVE (Trivy) | Paquete | Versión instalada | Severidad | Corrección | Equivalente en `pnpm audit` |
|---|---|---|---|---|---|
| `CVE-2026-93687` | `braces` | 3.0.3 | HIGH | ninguna | `GHSA-vfj7-8cjw-p6xm` |
| `CVE-2026-85393` | `node-forge` | 1.4.0 | HIGH | ninguna | `GHSA-86w9-cpqp-85rv` |

Paquetes analizados por target (misma invocación con `--format json --list-all-pkgs`, variante de
diagnóstico que no cambia la detección): **620 en `frontend/pnpm-lock.yaml`** y 16 en
`backend/requirements.txt`. Trivy suprime `devDependencies` por defecto, igual que
`pnpm audit --prod`; por eso el conteo de paquetes de Trivy (620) no coincide con
`metadata.totalDependencies` de pnpm (618): son universos de conteo distintos, no una discrepancia de
cobertura.

Conclusión de cobertura: el verde de §4.1 **no es vacuo**; con `--ignore-unfixed` las dos HIGH sin
parche se suprimen por política, y sin ese flag reaparecen en el lockfile del frontend.

### 4.3 Escaneo de secretos

```sh
trivy fs . --skip-dirs frontend/node_modules,frontend/.pnpm-store,.venv \
  --scanners secret --exit-code 1
```

Resultado: **código de salida 0**, sin secretos detectados. El paso de CI usa
`aquasecurity/trivy-action@v0.36.0` con los escáneres por defecto (`vuln` + `secret`); la ejecución de
§4.1 confirma en su log `Secret scanning is enabled`.

Validez del escáner (sondas sintéticas en `/tmp`, nunca en el repositorio):

- Un token tipo GitHub PAT sintético y una clave tipo AWS Access Key ID sintética: **detectados**
  (2 CRITICAL). El escáner está operativo.
- Una cadena sintética con el formato de la clave de Context7: **no detectada**. Es la limitación
  conocida: Trivy no tiene regla para ese prefijo. Por eso la garantía sobre esa credencial no es este
  escaneo, sino la rotación y revocación de T6 (D-5) y la referencia `{env:CONTEXT7_API_KEY}` de
  `opencode.json`; el valor no se reproduce aquí.

## 5. Verificaciones adicionales

| Comprobación | Resultado |
|---|---|
| `python3 infra/scripts/verify_version_sources.py --exclude-constitution` | **0** — «Python 3.14, Node 24 y pnpm 12.12.1 coinciden en las fuentes verificadas» |
| `docker compose config -q` | **0** |
| `git -c core.whitespace=cr-at-eol diff --check` | **0** |
| `git ls-files frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml` | ambos versionados |
| `git ls-files package.json pnpm-lock.yaml` | sin salida (cadena raíz retirada) |
| Formato del lockfile | 1 `lockfileVersion`, 0 separadores `---`, 0 `packageManagerDependencies` |
| `frontend/pnpm-workspace.yaml` | `pmOnFail: ignore`, `allowBuilds` y las exclusiones de `minimumReleaseAgeExclude`; sin listas de advisories ni configuración de auditoría |

## 6. Estado de CI (no verde hoy en la rama principal)

Consultada la API pública de GitHub, la última ejecución de CI sobre la rama principal corresponde al
commit `5f97c4c` (2026-10-19T14:53Z) y **concluyó en fallo**: el job `security` («Dependency and
filesystem scan») falla en el paso «Audit frontend dependencies». Ese commit es **anterior** a esta
spec: su `ci.yml` todavía ejecuta `working-directory: frontend` + `pnpm audit --prod --audit-level high`
y no contiene `infra/scripts/audit_frontend.py`. Es precisamente el fallo que la spec 003 corrige.

El trabajo de la spec 003 (T1-T6) está en la rama local, **sin commit ni push**, y la rama local está
por delante de `origin/main`; por eso no existe ninguna ejecución de CI con el comando nuevo. No se
declara el job verde: queda **pendiente de PR**.

## 7. Lo no ejecutado o no verificable en T7

- **Job `security` en verde en la rama principal:** no se cumple ni se puede obtener en este entorno
  (sin push ni PR; la última ejecución de `main` es roja y previa al cambio). Ver §6.
- `cd backend && pytest -q` y `cd backend && python -m compileall -q app`: no ejecutados en T7 (no hay
  cambios de backend; sí se ejecutaron las pruebas del filtro en T1/T3).
- `cd frontend && pnpm install --frozen-lockfile && pnpm test && pnpm run typecheck && pnpm run build`:
  no repetidos en T7 (sin cambios de código desde T4).
- Construcción o arranque de la imagen del frontend: no ejecutado.
- `sh -n infra/postgres/migrate.sh` y el merge `dev+prod` con las aserciones de
  `infra/scripts/assert_production_compose.py`: no ejecutados en T7; sí `docker compose config -q`.
- Escaneo de secretos con una regla para el formato de la clave de Context7: no existe; ver §4.3.

## 8. Conclusión

Las auditorías se ejecutaron con las versiones de referencia (Python 3.14.8, Node 24.22.0, pnpm
12.12.1, Trivy 0.70.0): `pip-audit` en verde, el filtro del frontend con **0 accionables** y **2
visibles**, y Trivy con los parámetros de CI en **0** pero con **cobertura demostrada** del lockfile
del frontend (620 paquetes; 2 HIGH sin parche al retirar `--ignore-unfixed`). La evidencia local está
completa; el verde en CI sigue **pendiente de PR**, porque la rama principal aún ejecuta el comando
anterior y falla en `security`.
