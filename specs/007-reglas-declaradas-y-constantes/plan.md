# Plan 007 — Reglas declaradas y constantes de partido

Estado: Implementada, validada por @reviewer y cerrada (2026-10-21). CI en main en verde (PR #2).

Spec: `specs/007-reglas-declaradas-y-constantes/spec.md` (aprobada 2026-10-20).

## 1. Objetivo y alcance técnico

Implementar las sustituciones de punta a punta sobre el flujo actual de acta única (sin API incremental), con migración **021 aditiva**, contadores persistidos en `match_segment_team_state`, reentrada por intervalos, límites por equipo/partido y UI del acta; retirar `transfers` como configuración; aplicar `roster_lock_matchday`; derivar los minutos de `rules_config`; fijar `GF1`/`GF2` y formaciones como contrato interno; y tramitar antes la enmienda constitucional §3.2 → 1.3.0 como cambio propio.

No se añaden endpoints de eventos ni de anulación (R11 fuera de alcance): el servidor valida el acta completa al cerrar y, una vez confirmada, es inmutable por el trigger `trg_validate_match_event_context` (009).

## 2. Archivos y responsabilidades

### Base de datos

| Archivo | Responsabilidad |
|---|---|
| `infra/postgres/migrations/021_match_event_substitutions.sql` (nuevo) | Añade `player_out_id`/`player_in_id`, FK compuestas, `CHECK ... NOT VALID`, pre-chequeos informativos. |
| `infra/postgres/init/01_schema.sql` | **Sin cambios**: el esquema base sigue creándose en su estado pre-migración; la 021 lo lleva al estado final. |
| `infra/postgres/init/03_hardening.sql`, `migrations/011` | Sin cambios; siguen aplicando `FORCE RLS` a `match_events` y `match_segment_team_state`, que ahora se usan. |
| `infra/postgres/migrations/009_…` | **No se toca**. Su trigger es la garantía de inmutabilidad de las actas. |

### Backend

| Archivo | Responsabilidad |
|---|---|
| `backend/app/modules/rules_engine/defaults.py` | `DEFAULT_RULES_CONFIG` en `3.3.0`: sin `transfers`, con `roster_lock_matchday: null`, `substitutions` y minutos 90/120. |
| `backend/app/modules/rules_engine/engine.py` | Esquema JSON tolerante (3.2.0/3.3.0, `substitutions`/`transfers` opcionales, claves nuevas), `normalize_rules_config`, `effective_stage_rules`, `effective_substitutions`, validación de la pareja efectiva. |
| `backend/app/modules/rules_engine/schemas.py` | Modelo Pydantic con `substitutions`/`transfers` opcionales y `roster_lock_matchday`. |
| `backend/app/modules/rules_engine/substitutions.py` (nuevo) | Funciones puras: intervalos en campo, validación de sustitución, uso/ventanas, saldos por segmento. |
| `backend/app/modules/matches/service.py` | Cierre: orden canónico, validación de sustituciones, límites, ventanas, reentrada, minutos efectivos, proyección de contadores, persistencia de columnas nuevas. |
| `backend/app/modules/matches/router.py` | `GET /operation` con estado de sustituciones y límites; alta de contadores al crear segmento; validación de máximo en segmentos/interrupción. |
| `backend/app/modules/matches/schemas.py` | `player_out_id`/`player_in_id` en el payload; respuesta de operación ampliada. |
| `backend/app/modules/tournaments/router.py` | Promoción al guardar configuración; bloqueo de altas por `roster_lock_matchday` (individual y masiva, dos comprobaciones). |

### Frontend

| Archivo | Responsabilidad |
|---|---|
| `frontend/app/utils/rulesConfig.ts` | Acepta 3.2.0/3.3.0, promueve al cargar, normaliza a 3.3.0, sin `transfers`, con minutos y `substitutions`. |
| `frontend/app/components/RulesEditor.vue` | Retira Transferencias; añade Inscripción (`roster_lock_matchday`) y minutos por fase. |
| `frontend/app/utils/substitutions.ts` (nuevo) | Cálculo de vista previa: en campo/banca, contadores y validación local del borrador. |
| `frontend/app/pages/workspace/matches/[id].vue` | Dos selectores sale/entra, filtros, contadores, errores; usa el estado del servidor. |
| `frontend/app/composables/useI18n.ts` | Claves es/en nuevas; sin eliminar claves en uso. |

### Documentación

| Archivo | Responsabilidad |
|---|---|
| `docs/constitution.md` | Enmienda 1.3.0 (T001, cambio propio). |
| `docs/contrato-reglas.md` (nuevo) | Contrato interno: `engine_version` 2026.1, cuatro formaciones con posiciones, `GF1`/`GF2`. |
| `README.md`, `AGENTS.md` | Sustituciones aplicadas, sin transferencias, ventana de inscripción, minutos, orden migración 021 → código y runbook. |

## 3. Modelo de datos y migración 021

```sql
ALTER TABLE public.match_events
    ADD COLUMN IF NOT EXISTS player_out_id UUID,
    ADD COLUMN IF NOT EXISTS player_in_id  UUID;

ALTER TABLE public.match_events
    ADD CONSTRAINT fk_match_events_player_out_organization
        FOREIGN KEY (player_out_id, organization_id)
        REFERENCES public.players (id, organization_id) ON DELETE RESTRICT,
    ADD CONSTRAINT fk_match_events_player_in_organization
        FOREIGN KEY (player_in_id, organization_id)
        REFERENCES public.players (id, organization_id) ON DELETE RESTRICT;

ALTER TABLE public.match_events
    ADD CONSTRAINT chk_match_event_substitution_pair CHECK (
        (event_type = 'substitution'
         AND player_out_id IS NOT NULL
         AND player_in_id IS NOT NULL
         AND player_out_id <> player_in_id
         AND player_id = player_out_id)
        OR (event_type <> 'substitution'
            AND player_out_id IS NULL
            AND player_in_id IS NULL)
    ) NOT VALID;
```

- **Pre-chequeos antes del primer `ALTER`** (bloque `DO`, solo `RAISE NOTICE`): conteo de `match_events` con `event_type = 'substitution'` y conteo de filas en `match_segment_team_state`. No abortan: el cambio es aditivo y los eventos legados quedan tolerados por `NOT VALID`.
- **Legado:** los eventos `substitution` previos no se reescriben (el trigger 009 bloquea `UPDATE` en partidos terminados) y el motor los ignora. No hay `VALIDATE CONSTRAINT`.
- **RLS/grants:** no se crean tablas; `match_segment_team_state` ya tiene RLS `ENABLE`/`FORCE`, política tenant y grants (`init/01:1153,1183,1201,1226`). Las FKs compuestas replican el patrón de la 015 (`uq_player_organization_context`).
- **Volumen limpio:** `init/00-03` → migraciones 001-021 termina en el mismo esquema que un volumen migrado hasta 021. `init/01` no se modifica.
- **Backfill:** ninguno. Las filas de `match_segment_team_state` se crean al abrir segmento o se aseguran al cerrar; los saldos se recalculan.
- **Orden de despliegue:** **021 antes** del código que escribe las columnas. Revertir el código con la 021 aplicada es seguro (las columnas quedan sin uso); la 021 no se desaplica (*forward-fix*).

## 4. Funciones puras

Todas viven en `rules_engine` o `matches` y no leen reloj, base de datos ni configuración global. Ninguna necesita fecha; si alguna la necesitara, se pasaría como parámetro.

### `normalize_rules_config(raw) -> dict`

1. Copia profunda.
2. `substitutions = raw.substitutions` o `DEFAULT_SUBSTITUTIONS` (5/3/`false`).
3. **Promoción:** si `roster_lock_matchday` ausente/nulo y `transfers.roster_lock_matchday` no nulo → copiarlo; luego eliminar `transfers`.
4. `schema_version := "3.3.0"`; `engine_version` se conserva.
5. Minutos: aplicar defaults 90/120 solo en lectura (no se escriben si la pareja es inválida; la validación va antes de persistir).
6. `validate_effective_rules(cfg)`.

### `effective_stage_rules(cfg, stage_id) -> dict`

`base` = defaults de fase + `stage_defaults`; después `stage_overrides[str(stage_id)]` **clave por clave**. Devuelve `extra_time_enabled`, `penalties_enabled`, `regular_time_minutes`, `extra_time_minutes`, `walkover_score`.

### `validate_effective_rules(cfg) -> None` (ValueError → 422)

1. Para `stage_defaults` y **para cada override**: calcular la pareja efectiva.
2. `1 <= regular <= 179`.
3. Si `extra_time_enabled` efectivo: `regular < extra <= 180`.
4. Si está deshabilitado: `extra` no se valida ni se materializa.
5. Mensaje con clave, ámbito (`stage_defaults` o `stage_id`) y pareja efectiva.

### `build_on_field(starters, events, team_id) -> OnFieldState`

```
orden = sort(events, key=(minute, added_minute, índice_en_acta))
estado = {jugador: [] intervalos}  # unión; abierto = None
en_campo = set(starters); expulsados = set()
for evento in orden:
    t = minute + added_minute
    if red_card and evento.team == team:
        cerrar intervalo abierto del jugador en t
        en_campo.remove(jugador); expulsados.add(jugador)
    if substitution and evento.team == team:
        cerrar intervalo del saliente en t; remove;
        abrir intervalo del entrante en t; add
return estado, en_campo, expulsados
```

### `validate_substitution(state, roster, team_id, out_id, in_id, t, allow_reentry) -> None`

1. Ambos en la plantilla del equipo; `out != in`.
2. `out` en campo; `in` en banca (en plantilla, no en campo, no expulsado).
3. Si `allow_reentry = false`: `in` no aparece en ningún intervalo previo.
4. `out`/`in` no expulsados.

### `team_usage(events, team_id) -> (sustituciones, ventanas)`

Sustituciones = eventos `substitution` con par; ventanas = cardinalidad de `{(segment_id, minute, added_minute)}`.

### `segment_balances(segments, events, limits) -> [(segment_id, team_id, remaining, windows_remaining)]`

Recorre segmentos por `segment_number`; resta el consumo del tramo al saldo anterior. Empieza en `(max_per_team, max_windows)`.

### `event_minute_limit(effective, resolution_type, extra_enabled) -> int`

- `extra` si `resolution_type ∈ {extra_time, penalties}` y la prórroga está habilitada; reglamentario en el resto.
- Valida `(a) minute <= max; (b) minute < max ⇒ minute+added <= max; (c) minute == max ⇒ added <= 30`.
- Frontera reglamentario/prórroga: `minute <= regular`.

### `roster_lock_active(published_config, context) -> bool`

Consulta agregada de la spec (RF-023), en una sola lectura y con RLS.

## 5. Algoritmo de cierre (pseudocódigo)

```
tx:
  set_rls_context
  identity = load_match_identity
  lock_stage_and_version
  advancement.lock_targets
  match = lock_match (rules_config)
  config = normalize_rules_config(match.rules_config)
  eff = effective_stage_rules(config, match.stage_id)
  subs_cfg = effective_substitutions(config)
  requerir permiso (existente)
  validar estado/versión/equipos (existente)
  segmento activo (existente)
  rosters = load_match_rosters
  events = dto.events en orden canónico
  starters = rosters role=starter por equipo
  para cada equipo: build_on_field + validar cada sustitución en orden
      (límites y ventanas acumulados por equipo)
  validar eventos de jugador contra intervalos (todos, no solo goles)
  validar segmentos y minutos con eff (409)
  validar coherencia marcador/eventos con la frontera `regular`
  validar suspensiones (existente)
  persistir eventos (incluye player_out_id/player_in_id; idempotencia completa)
  compute_match_outcome + GF1/GF2
  actualizar match y segmento (existente)
  asegurar filas de match_segment_team_state de todos los segmentos/equipos
  recalcular saldos por segment_number y upsert
  suspensiones, standings, advancement, auditoría y outbox (existente)
```

Cualquier `ValueError` antes de la primera escritura → 409 sin cambios (el router ya mapea `ValueError` a 409).

## 6. Interfaz

### `POST /api/v1/matches/{match_id}/close`

- Payload de evento: `player_out_id: UUID | null`, `player_in_id: UUID | null`.
  - `substitution`: ambos no nulos, distintos, `player_id = player_out_id` → si no, **422**.
  - Otros tipos: ambos nulos → si no, **422**.
- Violaciones de negocio (equipo/plantilla/en campo/banca/reentrada/límite/ventana/minutos) → **409** con mensaje que nombra el límite o el máximo efectivo.
- Sin cambios de ruta ni de códigos existentes.

### `GET /api/v1/matches/{match_id}/operation`

Añade:
- `substitutions`: por equipo `{team_id, on_field, bench, substitutions_used, substitutions_remaining, windows_used, windows_remaining, max_per_team, max_windows, allow_reentry, can_register, reason}`.
- `limits`: `{regular_time_minutes, extra_time_minutes, max_minute, added_minute_max}` con override de fase.
- Calculado con las funciones puras; **no escribe**. Sin planilla → listas vacías, `can_register = false`.

### `POST /api/v1/matches/{match_id}/segments` e `.../interrupt`

- `minute_start`/`minute` se validan contra el máximo posible (extra si está habilitada, si no reglamentario) → **422**.
- Al crear segmento se insertan (idempotente) las filas de `match_segment_team_state` de los equipos presentes con el saldo vigente.

### `POST /tournaments/{id}/rosters` y `/rosters/bulk`

- Si el bloqueo de plantilla está activo → **409** «La plantilla está cerrada desde la jornada {N}…», sin filas ni objetos.
- En la importación, comprobación antes de subir fotos y de nuevo en la transacción de escritura.

### Pantallas

- **Acta** (`workspace/matches/[id].vue`): al elegir `substitution`, dos selectores (sale de `on_field`, entra de `bench`), contadores por equipo, errores; misma acción de cierre.
- **Editor de reglas**: sin Transferencias; sección Inscripción; minutos por fase; sustituciones editables.

## 7. Decisiones y alternativas descartadas

1. **Una única migración aditiva (021) antes del código.** Descartado: código primero (las columnas no existirían al insertar).
2. **`CHECK ... NOT VALID`** para no bloquear el despliegue por eventos legados. Descartado: `CHECK` estricto (rompería el despliegue) y trigger de validación (duplica la regla).
3. **FKs compuestas con `organization_id`.** Descartado: FK simple + RLS (el aislamiento no puede depender solo de RLS).
4. **Estado en campo desde `match_rosters` + eventos + rojas.** Descartado: snapshots por segmento (no se pueden guardar tras el primer evento) y `was_ejected` (nunca se escribe).
5. **Intervalos por jugador (unión).** Descartado: un único `[entrada, salida]` (rompe la reentrada y la validación de eventos intermedios).
6. **Límites por equipo y partido, con filas por segmento como saldo.** Descartado: límites por segmento (no es lo que dicen `max_per_team`/`max_windows` ni la regla deportiva) y una tabla por partido (no existe y el segmento es la unidad operativa).
7. **Recalcular los saldos en cada escritura**, nunca decrementar. Descartado: contadores incrementales (se desincronizan con cualquier corrección).
8. **Operación calcula sin escribir.** Descartado: crear filas en `GET` (un GET no debe escribir; ya hay precedente de lock en GET como hallazgo R23).
9. **Tolerancia 3.2.0/3.3.0 con `substitutions` opcional y defaults en lectura.** Descartado: exigir 3.3.0 (rompería configuraciones guardadas) y migrar el JSON (violaría la inmutabilidad de lo publicado).
10. **Contrato interno en `docs/contrato-reglas.md` + constantes nombradas.** Descartado: configuración de formaciones/reset (coste alto, sin demanda).
11. **UI usa el estado del servidor.** Descartado: reimplementar el estado en campo en el cliente (dos fuentes de verdad).
12. **Sin endpoints de eventos/anulación.** Descartado: API incremental (R11, fuera de alcance).

## 8. Estrategia de pruebas

### Unitarias sin base de datos

- **Configuración** (`test_rules_engine.py` + `test_rules_config_compat.py`): 3.2.0 válida con `substitutions`/`transfers`; 3.3.0 sin ellos; `substitutions` ausente → defaults; promoción del heredado (con/sin primer nivel y con ambos); pareja efectiva con overrides parciales, `extra_time_enabled` true/false, `regular` 0/179/180, `extra` ≤ regular/181; promoción no materializa 120 con `regular = 150`; normalización a 3.3.0.
- **Motor de sustituciones** (`test_substitutions_rules.py`): XI inicial; salida/entrada; intervalos con reentrada (gol en 65 válido para el que entró en 60 y 409 para el que salió); expulsiones; `allow_reentry`; ventanas por `(segment, minute, added)`; ventana única con dos cambios al mismo minuto; límites por equipo; `max_per_team = 0`; mensajes 409; frontera 40/100; `minute + added` con descuento.
- **Cierre con dobles de sesión**: orden de validaciones, 409 antes de escribir, eventos de jugador fuera de intervalo, idempotencia de `client_event_id`, límites y ventanas, contadores no negativos.
- **Bloqueo de plantilla** (`test_roster_lock.py`, dobles): fuente publicada vs borrador, referencia por `stage_order`, `matchday` y estados confirmados, cancelados, ausencia de versión/jornada, dos comprobaciones en la importación, mensaje sin datos personales.

### Integración opt-in (`RUN_DATABASE_TESTS=1`, `DATABASE_ADMIN_URL`)

- `backend/tests/test_migration_021.py`: base desechable hasta 020 y aplicar 021; columnas nulas; FKs compuestas (nombres y columnas); `CHECK NOT VALID` rechaza una fila nueva inválida y acepta la válida; un evento legado se conserva y su `UPDATE` se rechaza; pre-chequeos con conteos; esquema limpio (init+001..021) idéntico al migrado; `is_voided` sin uso.
- `backend/tests/test_substitutions.py`: cierre real con sustituciones en dos segmentos; filas de `match_segment_team_state` por segmento con saldo y recálculo ordenado por `segment_number`; límites y ventanas; reentrada; `max_per_team = 0`; idempotencia; inmutabilidad posterior al cierre (INSERT/UPDATE de eventos falla); dos cierres concurrentes; partidos antiguos sin filas; `GET /operation` no escribe y expone estado y límites.
- Se ejecutan con el rol de aplicación salvo la migración (admin, base desechable).

### Frontend

- `frontend/tests/substitutions.test.ts`: filtros de opciones, contadores de vista previa sobre el borrador, bloqueo con `max_per_team = 0`, reentrada.
- `frontend/tests/rules-config.test.ts`: carga 3.2.0 con heredado → promoción; normalización a 3.3.0; sin `transfers`; minutos con defaults; validación de la pareja.
- Paridad i18n es/en (test existente de catálogos).
- `pnpm test`, `pnpm run typecheck`, `pnpm run build`.

### No se cubre

E2E de navegador; rendimiento medido; datos de producción; desempates; `live`/`suspended` (R11); registro incremental de eventos; corrección de actas cerradas; transferencias completas.

## 9. Trazabilidad RF → partes

| RF | Dónde |
|---|---|
| 001 | README/AGENTS (T012) |
| 002-003, 005 | `engine.py`, `defaults.py`, `schemas.py` (T003), `rulesConfig.ts` (T010) |
| 004 | Cierre atómico y altas (T005, T006) |
| 006 | Enmienda (T001) |
| 010-011 | Configuración aplicada y contrato del payload (T003, T004, T005) |
| 012-015 | Funciones puras de estado, reentrada, límites y ventanas (T004) |
| 016-018 | Cierre + proyección + idempotencia/inmutabilidad (T005) |
| 019 | UI del acta y vista previa (T009) |
| 020-029 | Retiro de transferencias, promoción, bloqueo de plantilla y editor (T006, T007, T010) |
| 030-034 | Migración 021 (T002) |
| 040-044, 046-048 | Minutos, pareja efectiva, no reescritura de publicadas, segmentos e interrupciones (T003, T007, T008) |
| 045 | `GET /operation` (T005, T008) |
| 050-052 | Contrato interno (T011) |

## 10. Riesgos y mitigaciones

- **Reentrada e intervalos.** Se modela unión de intervalos con orden canónico; pruebas con gol en 65, retorno en 70 y expulsiones.
- **Estado en campo y fixtures existentes.** La validación estricta de eventos por intervalo puede afectar actas de prueba con suplentes sin sustitución; se revisan y corrigen los fixtures, no el contrato.
- **Límites por partido vs tabla por segmento.** Semántica fijada (saldo acumulado) y recálculo por `segment_number`; prueba con segmentos y minutos no monótonos.
- **Compatibilidad 3.2.0/3.3.0.** Esquema tolerante, defaults en lectura y ninguna reescritura de versiones publicadas; prueba de ambos formatos y del impacto operativo.
- **Actas existentes.** No se revalidan; solo aplican las reglas a cierres nuevos. El despliegue se documenta.
- **Migración 021.** Aditiva, `IF NOT EXISTS`, `NOT VALID`, pre-chequeos y orden migración → código; sin rollback.
- **Concurrencia.** El cierre ya serializa por fase y bloquea el partido; dos cierres simultáneos → 409. La carrera entre bloqueo de plantilla y cierre queda documentada (sin locks nuevos).
- **Rendimiento.** Una pasada sobre eventos ya cargados; sin consultas por evento (RNF-006). No se mide throughput.
- **UI.** El estado viene del servidor; el cliente solo previsualiza sobre el borrador.

## 11. Reversión

- **021:** no se desaplica. Al ser aditiva, revertir el código deja columnas y `CHECK` sin uso; cualquier defecto se corrige con una migración posterior (*forward-fix*).
- **Código:** cada tarea es un commit independiente y revertible; con la 021 aplicada, el código antiguo sigue funcionando (no conoce las columnas).
- **Datos:** no se reescriben actas ni `rules_config` publicados; no hay migración de datos que revertir.
- **Feature:** el comportamiento queda determinado por la configuración de cada versión; no hay flag de entorno.

## 12. Dependencias y configuración

- Sin dependencias nuevas, sin variables de entorno nuevas, sin cambios en Compose ni en `.env.example` (RNF-001).
- Versiones de referencia de CI sin cambios.

## 13. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1 Aislamiento por RLS | Sí | Toda consulta con `set_rls_context`; FKs compuestas `(player_out_id, organization_id)` y `(player_in_id, organization_id)`; `match_segment_team_state` conserva RLS y política. |
| §2.2 Rol sin `BYPASSRLS` | Sí | No se cambia el rol ni se añaden `SECURITY DEFINER`; la migración corre como admin, la app como `bracket_app`. |
| §2.3 Lo publicado es inmutable | Sí | Sin reescritura de `rules_config` publicado ni actas cerradas; los eventos de un acta confirmada son inmutables por el trigger 009 y no hay anulación operativa. |
| §2.4 Migraciones append-only | Sí | Solo 021, aditiva, con checksum; 019/020 intactas; sin rollback. |
| §2.5 Proyección pública mínima | Sí | Las sustituciones no se añaden a vistas públicas ni a la alineación publicada; sin campos sensibles nuevos. |
| §2.6 Sin secretos por defecto | No aplica | Sin variables ni secretos nuevos. |
| §2.7 Administración global separada y auditada | No aplica | No se toca `/admin`. |
| §2.8 Nada sin verificación | Sí | Cada tarea tiene comando de verificación; CI completo al final y declaración de lo no ejecutado. |
| §2.9 El código de desarrollo no llega a producción | Sí | `seed_demo` sigue siendo solo de desarrollo; la migración no depende de datos demo. |
| §3.1 RLS y migraciones | Sí | `set_rls_context` en cada transacción; migración probada en volumen limpio y migrado. |
| §3.2 Backend y reglas en JSON | Sí, con enmienda previa | Sustituciones, ventana de inscripción y minutos en el JSON y aplicados; `transfers` retirado tras la enmienda 1.3.0 (T001). Sin la enmienda no se declara cumplimiento. |
| §3.3 Frontend y `useApi.ts` | Sí | Acta y editor usan `useApi.ts`; paridad i18n; `pnpm test/typecheck/build`. |
| §3.4 Seguridad y configuración | Sí | Sin defaults nuevos; mensajes sin datos personales ni nombre de torneo. |
| §3.5 Infraestructura y CI | Sí | Sin cambios de versiones ni Compose; jobs `infrastructure` y `security` pasan. |
| §4 Criterios de cambio | Sí | Jobs `backend`, `frontend`, `security`; runner de migraciones; documentación; revisión humana distinta del autor. |
| §5.2 Evolución | Sí | Enmienda como cambio propio, aprobada, con motivo/reglas/impacto e historial; T001 antes de T002. |

## 14. Orden de implementación

`T001` enmienda → `T002` migración → `T003` configuración → `T004` motor puro → `T005` cierre/proyección/operación → `T006` bloqueo de plantilla → `T007` retiro de transferencias/promoción/editor → `T008` minutos efectivos/segmentos → `T009` UI del acta → `T010` versiones y minutos en el editor → `T011` contrato interno → `T012` documentación/runbook → `T013` verificación final.

Cada corte deja `pytest -q`, `compileall` y (cuando aplique) `pnpm test/typecheck/build` en verde.
