# Contrato interno de reglas

**Versión del contrato (`engine_version`):** `2026.1`
**Ámbito:** códigos de llave de doble eliminación y catálogo de formaciones.
**Fuente única en código:** `backend/app/modules/rule_contract.py`
(`ENGINE_VERSION`, `GRAND_FINAL_CODE`, `RESET_CODE`, `FORMATION_CODES`,
`FORMATION_SLOTS`).

Este contrato es **interno y no configurable**. No se expresa en `rules_config`
ni se edita desde el editor de reglas: cambiarlo exige una spec, una prueba y
una actualización de este documento. Cualquier valor fuera del contrato se
rechaza (API 422 para formaciones) o se ignora (códigos de llave ajenos).

## 1. Códigos de llave `GF1` y `GF2`

| Constante | Código | Partido | Estado inicial |
|---|---|---|---|
| `GRAND_FINAL_CODE` | `GF1` | Gran final de la doble eliminación | `scheduled` |
| `RESET_CODE` | `GF2` | Repetición (*bracket reset*) de la gran final | `cancelled` |

- El calendario de doble eliminación genera **exactamente** `GF1`; ningún otro
  código empieza por `GF`. El router crea además `GF2` como partido
  `cancelled`, sin equipos, en la jornada siguiente a la gran final.
- `GF1` y `GF2` deben cerrarse con ganador: si el acta no lo determina, el
  cierre responde 409. La comprobación es la misma para ambos códigos.
- Estos códigos no son configurables. Un `bracket_code` distinto (`FINAL`,
  `SF1`, `R4-1`, etc.) sigue el tratamiento normal de la llave y nunca activa
  la repetición.

## 2. *Bracket reset*

Lógica del formato, no configuración:

1. El calendario genera `GF2` en estado `cancelled`, sin `home_team_id` ni
   `away_team_id`.
2. Al cerrar `GF1`, el ganador avanza según `advancement_links` como en
   cualquier llave.
3. La repetición se **activa solo** cuando el ganador de `GF1` es el finalista
   del cuadro de perdedores (el equipo visitante, `away_team_id`). En ese caso
   `GF2` pasa a `scheduled` y recibe a los **dos** equipos de `GF1` (`home` y
   `away`), y se emite `MATCH_UPDATED` al outbox.
4. Si gana el finalista del cuadro de ganadores, `GF2` permanece `cancelled`.
5. Una repetición ya activada no se vuelve a activar: el `UPDATE` exige
   `status = 'cancelled'` y equipos nulos, y falla si el estado cambió.

## 3. Catálogo cerrado de formaciones

El catálogo tiene cuatro formaciones y es cerrado: `FormationCode` en la API y
el `CHECK` de `match_team_lineups.formation_code` aceptan exactamente estas
cuatro y ninguna más. Una formación distinta responde 422 nombrando el catálogo
y, si se saltara la API, la base de datos la rechaza.

Las posiciones se listan en el orden de la alineación (de portero a delantera)
y son etiquetas internas, no configuración.

### `4-3-3`

Posiciones: `GK`, `LB`, `LCB`, `RCB`, `RB`, `CM_L`, `CM`, `CM_R`, `LW`, `ST`,
`RW`.

### `4-4-2`

Posiciones: `GK`, `LB`, `LCB`, `RCB`, `RB`, `LM`, `LCM`, `RCM`, `RM`, `ST_L`,
`ST_R`.

### `3-5-2`

Posiciones: `GK`, `LCB`, `CB`, `RCB`, `LWB`, `LCM`, `CM`, `RCM`, `RWB`, `ST_L`,
`ST_R`.

### `4-2-3-1`

Posiciones: `GK`, `LB`, `LCB`, `RCB`, `RB`, `CDM_L`, `CDM_R`, `LW`, `CAM`,
`RW`, `ST`.

## 4. Estabilidad y verificación

- `engine_version` se mantiene en `2026.1`; es la versión que valida el motor de
  reglas (`RULES_SCHEMA` y `DEFAULT_RULES_CONFIG`).
- `backend/tests/test_rule_contract.py` comprueba que las constantes coinciden
  con este documento, con el esquema de la API y con el `CHECK` de la migración
  `007`, que el calendario produce `GF1`/`GF2` y que la repetición se activa
  con ambos equipos.
- `backend/tests/test_migration_021.py` (opt-in con PostgreSQL) comprueba que
  el `CHECK` real acepta las cuatro formaciones y rechaza una quinta.

## 5. Alcance del contrato cerrado

Este documento cubre **solo** los códigos de llave `GF1`/`GF2` y el catálogo
cerrado de las cuatro formaciones con sus posiciones. `engine_version` sigue en
**`2026.1`**.

La configuración de la versión incluye además tres claves **aditivas** que
quedan **fuera** de este contrato y no cambian ninguna regla del motor:

| Clave | Tipo | Default | Significado |
|---|---|---|---|
| `game_format` | texto del catálogo `5v5`, `7v7`, `9v9`, `11v11` | `11v11` | Modalidad declarada; no altera formaciones, titulares ni planilla |
| `min_players_per_team` | entero ≥ 0 | `0` (sin límite) | Mínimo de jugadores activos por equipo |
| `max_players_per_team` | entero ≥ 0 | `0` (sin límite) | Máximo de jugadores activos por equipo |

- Los defaults reproducen el comportamiento anterior: una configuración sin las
  claves se lee como `11v11` y sin límites, y no se reescribe.
- El formato **no** es referencia de validación de los límites ni habilita
  formaciones por modalidad; la planilla soportada sigue siendo de once.
- La aclaración no cambia `engine_version`, el catálogo de formaciones ni
  ninguna regla deportiva.
