# Plan — Spec 042: Sorteo concurrente y duplicados en calendarios generados (F11)

Estado: borrador, pendiente de aprobación.

## 1. Alcance y dependencias

- No cambia algoritmos, códigos, semillas, respuestas ni validaciones de los sorteos que no coinciden (RF-009).
- Una migración nueva, `065_generated_match_code_unique.sql`. Ninguna migración aplicada se edita.
- Sin cambios de RLS, permisos, outbox, Socket.IO, frontend ni superficie pública.
- Se apoya en el protocolo de bloqueo de la 006: `lock_stage_and_version` (fase → versión con `FOR UPDATE`) antes de leer equipos o escribir partidos, en generación y sorteo no-Swiss y en la transacción de escritura Swiss.

## 2. Hallazgo de partida (H7)

- Hoy todas las rutas que crean partidos de una fase bloquean antes la fila de `stages`, que siempre existe. Por eso el H7 original («`FOR UPDATE` no bloquea filas inexistentes» en Swiss ronda 1 en frío) ya no debería reproducirse: el segundo sorteo espera al primero, ve sus partidos y responde 409.
- `matches.bracket_code` no es único. Los partidos manuales lo dejan `NULL`; los generados siempre lo rellenan, y la clonación de versiones lo copia a la fase nueva de la versión nueva.
- T2 lo demuestra con concurrencia real antes de tocar código. Si algún flujo duplica, se corrige en esa misma tarea añadiendo el bloqueo que falte, y se anota.

## 3. Archivos y responsabilidades

### Base de datos (`infra/postgres/migrations/065_generated_match_code_unique.sql`)
```
BEGIN;
LOCK TABLE public.matches IN SHARE ROW EXCLUSIVE MODE;   -- nadie inserta mientras se comprueba
DO $$
  duplicados := fases (organization_id, tournament_version_id, stage_id) con
                bracket_code NOT NULL repetido (GROUP BY ... HAVING count(*) > 1)
  si hay duplicados:
      RAISE EXCEPTION 'migración 065: % fase(s) con códigos de partido repetidos: %',
                      cantidad, lista ordenada de stage_id
            USING HINT = 'Regenera esas fases y vuelve a aplicar la migración';
$$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_matches_generated_code
    ON public.matches (organization_id, tournament_version_id, stage_id, bracket_code)
    WHERE bracket_code IS NOT NULL;
COMMIT;
```
- RF-007: índice único parcial; los partidos manuales (`NULL`) quedan fuera (CL-4). Fases distintas o versiones clonadas pueden repetir código.
- RF-008: la excepción aborta la transacción; `migrate.sh` (`ON_ERROR_STOP=1`) para sin registrar la 065 en `schema_migrations` y sin cambiar datos.
- RNF-003: `IF NOT EXISTS` hace la reaplicación inocua.
- La migración la aplica el administrador del esquema, que no está sujeto a RLS, así que la comprobación ve todas las organizaciones.

### Backend
- `backend/app/modules/tournaments/schedule_integrity.py` (nuevo, puro): `PlannedMatch`, `ScheduleIntegrityError` y `check_generated_schedule` (§4).
- `backend/app/modules/tournaments/routes/matches.py`:
  - `generate_single_elimination_matches` y `_draw_non_swiss_schedule`: llaman a `check_generated_schedule` con el calendario ya construido y antes del primer `INSERT`. Liga y grupos, con el máximo de `max_meetings_per_pair(stage_type, schedule_legs)`; eliminación directa y doble, solo códigos (máximo `None`, CL-3).
  - Swiss: en la transacción de escritura, después de `_revalidate_swiss_draw_state` y con fase y versión bloqueadas, lee las parejas no canceladas de las rondas anteriores de la fase y llama a la comprobación con máximo 1.
  - `_write_swiss_schedule`: un `IntegrityError` se traduce a 409, como ya ocurre en las otras escrituras.
  - Un `ScheduleIntegrityError` se traduce a 409 dentro de la transacción, que se revierte completa, también el borrado previo de un reemplazo (DA-3).
- Detalles 409 nuevos: `GENERATED_CODE_CONFLICT` («El calendario generado repite el código de partido {code}») y `GENERATED_PAIR_CONFLICT` («El calendario generado supera el máximo de enfrentamientos entre dos equipos de la fase»). No hay aviso nuevo en el Workspace: el frontend ya muestra el `detail` de cualquier 409 del sorteo.

### Tests
- `backend/tests/test_migration_065.py` (BD desechable, `migration_helpers`).
- `backend/tests/test_schedule_integrity.py` (puras).
- `backend/tests/test_concurrency_042.py` (PostgreSQL real con el arnés de `test_concurrency_006.py`: base desechable, rol dedicado sin `BYPASSRLS` y una `AsyncSession` por petición).
- Extensiones de `test_tournament_scheduling.py` y `test_swiss_transaction.py` para el 409 sin escrituras.

## 4. Función pura (`schedule_integrity.py`)

```
PlannedMatch(code: str, home_team_id: UUID | None, away_team_id: UUID | None, group_id: UUID | None)

check_generated_schedule(planned, *, max_meetings: int | None, prior_pairs=()) -> None
    vistos = {}
    para cada partido en orden:
        si partido.code en vistos: lanzar ScheduleIntegrityError("code", partido.code)
        añadir code
    si max_meetings es None: terminar                      # eliminatorias (CL-3)
    cuenta = Counter(clave(p) para p en prior_pairs + planned si ambos equipos existen)
    clave = (group_id, frozenset({home, away}))            # no orientada (CL-2), por grupo
    si alguna cuenta > max_meetings: lanzar ScheduleIntegrityError("pair", clave)
```
- Sin reloj, sin E/S. Los huecos (`None`) de llaves no cuentan como pareja.
- Liga a dos vueltas: dos apariciones por pareja con local invertido pasan (CL-2); una tercera falla.

## 5. Concurrencia real (T2)

Para que las dos peticiones coincidan de verdad y no por azar:
```
barrera = conexión admin: BEGIN; SELECT 1 FROM stages WHERE id = fase FOR UPDATE
lanzar A y B con asyncio.gather (cada una con su sesión y conexión)
esperar hasta que pg_stat_activity muestre 2 backends de la base con wait_event_type = 'Lock'
barrera: ROLLBACK  -> A y B compiten por el bloqueo de la fase
comprobar respuestas y filas finales
```
| Caso | Esperado |
|---|---|
| Liga, grupos, eliminación directa, doble eliminación y Swiss ronda 1: dos sorteos en frío sin reemplazo | Uno 200/201 y otro 409 «ya tiene partidos/sorteo»; un solo calendario, códigos únicos (RF-001, RF-002, CL-1) |
| Dos reemplazos de liga y de Swiss ronda 1 | Ambos se aplican en orden; queda exactamente el calendario del último (semilla de la respuesta), sin partidos del otro (RF-003, DA-4) |
| Dos peticiones de la misma ronda Swiss posterior | Una aplicada y otra 409 `SWISS_STATE_CHANGED_DETAIL` (RF-004) |
| Sorteo frente a alta manual | En ambos órdenes: alta posterior validada con R26 contando los generados; sorteo posterior sin reemplazo, 409 (RF-005) |
| Reemplazo frente a acta cerrada | 409 de partidos operados, sin cambios (CL-5) |
| Fase de otra organización | 404, sin bloqueo ni escritura (RF-010) |
| Dos `INSERT` directos con el mismo código y sin bloqueo | Uno falla con `UniqueViolation` (RF-007) |

## 6. Interfaz

- Sin endpoints nuevos ni cambios de esquema de petición o respuesta. Solo aparecen los dos `detail` 409 de §3, que en la práctica no se alcanzan con los generadores actuales.

## 7. Decisiones

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Índice único parcial `WHERE bracket_code IS NOT NULL` | `UNIQUE` de tabla | Los manuales no tienen código y no deben chocar (CL-4) |
| `LOCK TABLE ... SHARE ROW EXCLUSIVE` y comprobación antes del índice | `CREATE UNIQUE INDEX` y dejar que falle | El fallo nativo no dice cuántas fases ni cuáles (DA-2) |
| Sin `CONCURRENTLY` | Índice concurrente | `migrate.sh` ejecuta cada migración en una transacción; `matches` es pequeña por organización |
| Comprobación pura antes del primer `INSERT` | Confiar solo en el índice | El índice no cubre parejas repetidas (DA-3) |
| Swiss: parejas anteriores leídas bajo bloqueo en la escritura | Leerlas en la fase de cálculo | Solo la lectura bajo bloqueo es definitiva |
| Barrera con bloqueo de fase en los tests | `sleep` o carrera libre | Coincidencia garantizada y test determinista |
| Reemplazos en serie, gana el último | Token de estado esperado | DA-4 |

## 8. Exposición pública, datos personales y configuración

No aplica: sin campos públicos, datos personales, variables ni secretos nuevos.

## 9. Documentación

- README: runbook de la 065 (aplicar antes que la API; qué hacer si aborta) y protección real del sorteo.
- AGENTS: retirar H7 de riesgos aceptados y describir bloqueo + comprobación + índice.
- `docs/manual-usuario.md`: qué ocurre si dos personas sortean a la vez y el nuevo 409.
- `docs/informe-funciones-adicionales.md`: F11 implementada. MEMORY.

## 10. Cobertura de RF

| Parte | RF |
|---|---|
| Migración 065 | RF-007, RF-008, RNF-003 |
| `schedule_integrity.py` e integración | RF-006, RF-009 |
| `test_concurrency_042.py` | RF-001–RF-005, RF-007, RF-010, RNF-001, RNF-002 |
| Documentación | RF-011 |

## 11. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|----------------------|--------|----------------|
| 2.1 Aislamiento por RLS | Sí | Sin cambios de políticas; las rutas siguen con `set_rls_context()` y `organization_id`; test con fase de otra organización |
| 2.2 Sin `BYPASSRLS` | Sí | Tests con rol dedicado `NOBYPASSRLS`; sin funciones `SECURITY DEFINER` nuevas |
| 2.3 Lo publicado es inmutable | Sí | No cambia qué admite una versión publicada (CL-7) |
| 2.4 Migraciones append-only | Sí | 065 nueva e idempotente |
| 2.5 Proyección pública mínima | No | Sin superficie pública |
| 2.6 Sin secretos por defecto | No | Sin variables nuevas |
| 2.7 Administración global | No | No toca `/admin` |
| 2.8 Verificación | Sí | Rojo y luego verde por tarea; cinco jobs de CI |
| 2.9 Código de desarrollo | No | Sin seeds ni rutas de desarrollo |
| 3.1 Rectificaciones append-only | No | No las toca |
| 3.2 Efectos por worker | No | Sin efectos asíncronos |
| 3.3 `useApi.ts` | No | Sin cambios de frontend |
| 3.4 Seguridad | Sí | Sin datos nuevos en errores; 409 con códigos generados, no con datos personales |
| §4 BD | Sí | Volumen limpio 001→065, salto 064→065, reaplicación y datos duplicados en `test_migration_065.py`; `sh -n infra/postgres/migrate.sh` |
| §4 Backend | Sí | `pytest -q`, `python -m compileall -q app`, ruff y bandit |
| §4 Frontend | No | Sin cambios |
| §4 Infraestructura | No | Sin cambios de Compose |
| §4 Documentación | Sí | README, AGENTS, manual, informe y MEMORY en T6 |
