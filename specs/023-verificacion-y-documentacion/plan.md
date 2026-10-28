# Plan 023 — Verificación integral y documentación

Spec: `specs/023-verificacion-y-documentacion/spec.md` (borrador corregido, pendiente de aprobación del reviewer).

## Objetivo y alcance técnico

Programa de verificación integral y actualización de documentación sobre lo ya implementado (specs 015–022 y anteriores). **No añade funcionalidad de producto**: no hay endpoints, migraciones, campos públicos ni cambios de contrato HTTP. `engine_version` sigue en 2026.1.

Bloques verificables, en orden de dependencia:

1. **A** — Pruebas unitarias de servicios de dominio puros (backend + frontend).
2. **B** — Pruebas de integración (endpoints, base de datos, permisos, archivos, auth, asíncronos).
3. **C** — Pruebas de interfaz (wizards, navegación, formularios, calendario, plantillas, vistas públicas).
4. **D** — Pruebas de permisos (anónimo, sin rol, roles, accesos cruzados).
5. **E** — Regresión deportiva (goles, asistencia, walkover, administrativa, cierre, segmentos, clasificación, porterías).
6. **F** — Accesibilidad (teclado, foco, etiquetas, `aria-live`, contraste, `alt`).
7. **G** — Documentación y manual de usuario (README, AGENTS, `docs/manual-usuario.md`).

Herramientas reutilizadas (RNF-001): `pytest` (puro y opt-in con `RUN_DATABASE_TESTS=1`), `node --test`, vitest, Playwright (`pnpm run e2e`/`e2e:test`), `infra/scripts/verify_worker_loop_health.sh`, inspección manual documentada.

## Decisiones de plan (con alternativa descartada)

1. **Sin código de producto.** Todo cambio se limita a pruebas y documentación; si falta cobertura, se añade prueba, no se toca `backend/app` ni `frontend/app` (salvo utils ya puros). *Descartado:* añadir ganchos de prueba al producto (RNF-004, §3.2).
2. **Honestidad de ejecución.** Lo que no se pueda correr en este entorno (sin Docker/PostgreSQL/Node 24/OAuth real) se declara «no ejecutado» con motivo, nunca como verde (RNF-002, §2.8). *Descartado:* marcar como verde por inspección.
3. **Inventario cerrado de sujetos.** La lista de `spec.md` §«Inventario de sujetos verificables» es la fuente de verdad; toda función sin prueba al cierre se declara «no cubierta (fuera de esta entrega)» con motivo. *Descartado:* umbral porcentual (vacío, RNF-001).
4. **Accesibilidad por inspección manual + teclado en E2E.** No se añaden axe/lighthouse (RNF-001); contraste y `alt` se verifican por inspección documentada. *Descartado:* herramienta automatizada nueva.
5. **Manual de usuario en `docs/manual-usuario.md`**, enlazado desde README, sin inflar el README (duda resuelta en la spec).
6. **Corrección del conteo del inventario frontend:** la spec dice «41 archivos» en `frontend/app/utils/`, pero el directorio contiene **42**. Se corrige a 42 en la spec y en la documentación (detalle opcional del reviewer). *Descartado:* dejar el conteo erróneo.
7. **Presupuesto E2E respetado.** Solo el escenario ya existente del reintento del tiempo real se ejecuta en Playwright; no se extiende el arnés más allá del presupuesto de 25 min (RNF-001). Calendario y plantillas se verifican por inspección manual documentada (RF-012 c).
8. **Google por redirección declarado no ejecutado** si no hay cliente OAuth real configurado (RF-009); solo se verifican email/password, sesión y creación de organización.
9. **Trazabilidad de cobertura (RF-028).** Al cerrar el Bloque A backend, T1 publica en `tasks.md` la lista explícita de funciones del inventario no cubiertas en esta entrega con motivo por función, para cerrar RF-001/RNF-002 con trazabilidad. *Descartado:* dejar la lista solo en el informe final sin anclarla a T1.
10. **Coherencia documental (RF-025, RNF-006).** AGENTS.md incluye una referencia a `docs/manual-usuario.md`. *Descartado:* dejar el manual solo enlazado desde README.
11. **Verificación asíncrona opcional (RF-010).** `verify_worker_loop_health.sh` puede ejecutarse en un entorno aislado con Docker y la pila levantada para cerrar RF-010; si no se ejecuta, se mantiene la declaración «no ejecutada» (RNF-002). *Descartado:* presentarla como verde sin ejecución.
## Archivos y responsabilidades

### Bloque A — Pruebas unitarias

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `backend/tests/test_*.py` (existentes) | ajustados/completados | Cubrir funciones puras del inventario backend sin prueba (RF-001, RF-002, RF-005). |
| `frontend/tests/*.test.ts` | ajustados/completados | Cubrir utils puros sin prueba (RF-003). |
| `frontend/app/utils/*.ts` | solo lectura | Sujetos verificables; corrección de conteo 41→42. |

### Bloque B — Integración

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `backend/tests/test_public_access_matrix.py`, `test_public_stats_endpoints.py` | existentes/ajustados | Endpoints públicos (RF-006 a, RF-007, RF-014). |
| `backend/tests/test_invitations.py` | existente | Invitaciones (RF-006 b, RF-005). |
| `backend/tests/test_match_*`, `test_close_validation_order.py` | existentes | Cierre y segmentos (RF-006 c, RF-019). |
| `backend/tests/test_crest_*.py` | existentes | Escudos (RF-006 d, RF-008). |
| `backend/tests/test_google_*.py`, `test_organizations_create_db.py` | existentes | Auth (RF-006 e, RF-009). |
| `backend/tests/test_invitations.py` (sin rol) | existente | Miembro sin rol (RF-006 f, RF-017). |

### Bloque C — Interfaz

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `frontend/e2e/*` | sin extensión | Escenario existente del reintento (RF-012 a, RF-024). |
| `frontend/tests/*.test.ts` | ajustados | Wizards `?step=`, normalización, formularios (RF-012 b, RF-013). |
| Inspección manual documentada | nuevo anexo | Calendario y plantillas (RF-012 c). |

### Bloque D — Permisos

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `backend/tests/test_public_access_matrix.py` | existente/ajustado | Anónimo, 404 indistinguible, sin escritura (RF-015, RF-016, RF-018). |
| `backend/tests/test_invitations.py` | existente | Miembro sin rol 403 (RF-017). |
| Suites de roles | existentes | Observador/operador/admin/propietario/plataforma (RF-015). |

### Bloque E — Regresión deportiva

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `backend/tests/test_match_events_contract.py`, `test_match_assists*.py` | existentes | Goles, asistencia (RF-019). |
| `backend/tests/test_walkover*.py`, `test_close_validation_order.py` | existentes | Walkover, resolución administrativa (RF-019, RF-021). |
| `backend/tests/test_sanctions*.py` | existentes | Doble amarilla, sanciones (RF-020). |
| `backend/tests/test_public_stats*.py` | existentes | Porterías imbatidas (RF-022). |

### Bloque F — Accesibilidad

| Archivo | Estado | Responsabilidad |
|---|---|---|
| Inspección manual documentada | nuevo anexo | Teclado, foco, etiquetas, `aria-live`, contraste, `alt` (RF-023). |
| `frontend/e2e/*` | sin extensión | Teclado en asistentes (RF-024). |

### Bloque G — Documentación

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `README.md` | modificado | Comportamiento real: rutas públicas/Workspace, matriz de acceso, escudos, Google, invitaciones, minutos/resoluciones, walkover, sustituciones, sanciones, estadísticas/porterías, migraciones hasta 031 (RF-025). |
| `AGENTS.md` | modificado | Coherencia con README y código; incluye referencia a `docs/manual-usuario.md` (RF-025, RNF-006). |
| `docs/manual-usuario.md` | nuevo | Flujos operativos reales (RF-026). |
| `specs/023-verificacion-y-documentacion/spec.md` | ajuste menor | Corrección de conteo 41→42 en inventario frontend. |

## Funciones puras

No se añaden funciones puras nuevas. Se reutilizan las ya existentes del inventario (RF-001–RF-004). La corrección de conteo es documental.

## Estrategia de tests

- **Suites puras (siempre):** `cd backend && pytest -q` (sin `RUN_DATABASE_TESTS`), `cd frontend && pnpm test`, `node --test` donde aplique. Deben pasar o declararse el motivo de fallo.
- **Suites opt-in:** `RUN_DATABASE_TESTS=1 pytest -q` contra PostgreSQL con datos demo; se declaran «no ejecutadas» si no hay entorno.
- **E2E:** `pnpm run e2e`/`e2e:test` dentro del presupuesto de 25 min; solo el escenario existente.
- **Operación:** `sh infra/scripts/verify_worker_loop_health.sh` (Docker); se declara no ejecutado si no hay Docker.
- **Accesibilidad:** inspección manual documentada con método.
- **Documentación:** verificación de coherencia README/AGENTS/spec/código.

## Qué RF cubre cada parte

| Parte | RF |
|---|---|
| Bloque A backend | RF-001, RF-002, RF-004, RF-005 |
| Bloque A frontend | RF-003 |
| Bloque B (endpoints) | RF-006, RF-007, RF-008, RF-009, RF-010, RF-011 |
| Bloque C (interfaz) | RF-012, RF-013, RF-014 |
| Bloque D (permisos) | RF-015, RF-016, RF-017, RF-018 |
| Bloque E (regresión deportiva) | RF-019, RF-020, RF-021, RF-022 |
| Bloque F (accesibilidad) | RF-023, RF-024 |
| Bloque G (documentación) | RF-025, RF-026, RF-027 |
| Bloque H (trazabilidad de cobertura) | RF-028 |
| Cierre integral | Todos + RNF-001..RNF-006 |
## Riesgos

| Riesgo | Mitigación |
|---|---|
| Entorno sin Docker/PostgreSQL/Node 24 | Declarar «no ejecutado» con motivo; no marcar como verde. |
| Migraciones 026–031 pendientes | Acotar pruebas al esquema disponible o declarar no ejecutadas; no modificar migraciones. |
| Inventario incompleto de sujetos sin prueba | Declarar «no cubierto (fuera de esta entrega)» con motivo (RNF-002). |
| Contraste/`alt` no automatizables | Inspección manual documentada con método (RF-023). |
| Google sin cliente OAuth real | Declarar no ejecutado (RF-009). |
| Verificación asíncrona sin Docker o con riesgo operativo | Ejecutar `verify_worker_loop_health.sh` en entorno aislado o declarar «no ejecutado» (RF-010, RNF-002). |

## Verificación de constitución

Constitución 1.4.0. No se requiere ninguna excepción de la §5.1.

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 El aislamiento lo garantiza la base de datos | Sí | Las pruebas de permisos fijan contexto RLS y no esquivan RLS; no hay tablas nuevas. |
| §2.2 La aplicación nunca se salta RLS | Sí | Sin uso de `DATABASE_ADMIN_URL` ni rol elevado en las verificaciones. |
| §2.3 Lo publicado es inmutable | Sí | No se editan versiones publicadas ni actas; las pruebas usan datos demo. |
| §2.4 Historial de esquema append-only | Sí | Sin migraciones ni edición de migraciones aplicadas (RNF-004). |
| §2.5 Lo público es una proyección mínima | Sí | No se añaden campos públicos; las verificaciones confirman exclusión de sensibles. |
| §2.6 Ningún secreto por defecto fuera de desarrollo | Sí | Sin variables nuevas ni defaults en producción. |
| §2.7 Administración global separada y auditada | No | No se toca `/admin` ni `platform_audit_logs`. |
| §2.8 Nada se da por terminado sin verificación | Sí | Cada RF se respalda con prueba, inspección o declaración de no ejecución. |
| §2.9 El código de desarrollo no llega a producción | Sí | Sin seeds ni datos demo en producción; verificaciones solo en desarrollo/local. |
| §3.1 Base de datos y multi-tenancy | Sí | Sin DDL; consultas con contexto RLS. |
| §3.2 Backend | Sí | Sin módulos/routers nuevos; solo pruebas y documentación. |
| §3.3 Frontend | Sí | Sin llamadas HTTP nuevas; solo pruebas y documentación. |
| §3.4 Seguridad y configuración | Sí | Sin dependencias nuevas ni supresiones de auditoría; sin secretos en docs. |
| §3.5 Infraestructura y CI | Sí | Versiones de referencia intactas; `docker compose config -q` sigue verde. |
| §4 «Para todos los cambios»: jobs de CI | Sí | Se ejecutan `backend`, `frontend`, `infrastructure`, `security` y `e2e` cuando aplique. |
| §4 «Para todos los cambios»: sin secretos ni datos personales | Sí | Pruebas con datos demo; docs sin datos reales ni secretos. |
| §4 «Para todos los cambios»: documentación y pruebas | Sí | README/AGENTS/manual actualizados en el mismo cambio. |
| §4 «Para cambios de base de datos» | No | Sin cambio de esquema. |
| §4 «Para cambios de API o backend» | Sí | Sin rutas ni contratos nuevos; `pytest -q` y `compileall` pasan. |
| §4 «Para cambios de frontend» | Sí | `pnpm test`, `typecheck` y `build` pasan. |
| §4 «Para cambios de infraestructura o despliegue» | Sí | `docker compose config -q` pasa; sin defaults de desarrollo en producción. |
| §4 «Para cambios de dependencias» | No | Sin nuevas ni actualizadas dependencias. |
| §5.1 Excepciones | No | No se necesita ninguna. |
| §6 Cumplimiento | Sí | Requiere revisión humana distinta del autor. |