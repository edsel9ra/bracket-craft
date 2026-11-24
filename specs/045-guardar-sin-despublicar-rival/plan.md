# Plan — Spec 045: Guardar la alineación sin despublicar al rival

Estado: borrador, pendiente de aprobación.

## 1. Alcance y dependencias

- Sin migraciones (RNF-002): `match_team_lineups` ya tiene `is_public` y `published_at`, y ninguna tabla la referencia por `id`, así que se puede seguir borrando y recreando la fila con los valores conservados.
- Sin endpoints, campos de API, campos públicos, eventos de outbox ni Socket.IO nuevos (RNF-001). `engine_version` sigue en `2026.1`.
- Sin dependencias nuevas.
- **Un PR de implementación** (T1–T4), apilado sobre el [PR #120](https://github.com/edsel9ra/bracket-craft/pull/120).

## 2. Archivos y responsabilidades

### Backend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `backend/app/modules/matches/audit.py` | Funciones puras nuevas. `team_publication_signatures(formations, entries) -> dict[UUID, str]`: por equipo, firma de la formación y de los pares `(player_id, rol, posición)` ordenados, **sin minutos** (DA-2). `withdrawn_publications(before_public, before_signatures, after_signatures) -> list[UUID]`: equipos con formación publicada cuya firma cambia o desaparece, en orden estable. `lineup_signature` y `lineup_audit_action` no cambian: la entrada `SAVE_MATCH_LINEUP` sigue registrando cualquier cambio guardado, también de minutos. | RF-001, RF-002, RF-004 |
| `backend/app/modules/matches/router.py` | `save_match_lineup`: con el partido ya bloqueado (`FOR UPDATE OF m`, igual que hoy), lee `team_id, formation_code, is_public, published_at` de las formaciones del segmento junto al estado anterior. Calcula las firmas antes y después, y los equipos retirados. Al recrear `match_team_lineups`, escribe `is_public`/`published_at` anteriores para los equipos con alineación sin cambios y `FALSE`/`NULL` para el resto. Tras la entrada de guardado, registra `UNPUBLISH_MATCH_LINEUP` por cada equipo retirado, con el mismo payload que la despublicación explícita (`segment_id`, `team_id`, `is_public: false`, `formation_code` anterior). | RF-001, RF-002, RF-004, RF-008 |

`publish_match_lineup` no cambia. Guardar y publicar ya bloquean la fila del partido con `FOR UPDATE`, así que se ejecutan uno detrás de otro (RNF-003). Una formación conservada ya cumplía las reglas de publicación y su contenido no cambia, por lo que sigue cumpliéndolas. Cualquier otro caso queda privado.

### Frontend

| Archivo | Responsabilidad | RF |
|---|---|---|
| `frontend/app/utils/lineupPublication.ts` (nuevo) | Función pura `withdrawnPublicTeams(tacticalRows, editorFormations, editorEntries, rosterPlayers) -> string[]`. Toma las filas `tactical_lineups` del segmento seleccionado (formación, `is_public`, `player_id`, `is_starter`, `position_slot`) y el estado del editor, aplica la misma definición que el backend y devuelve los equipos publicados cuya alineación cambia o desaparece. | RF-003 |
| `frontend/app/composables/useMatchLineup.ts` | `saveLineup()`: tras las validaciones actuales y antes de llamar a la API, si `withdrawnPublicTeams` no está vacío, pide `confirm` con el nombre de cada equipo afectado, `tone: 'danger'` y `singleFlight` (el `confirm` de `useMatchOperationState`). Si se cancela, no envía nada y el editor conserva su estado. Si no hay equipos retirados, guarda sin preguntar, como hoy. | RF-003 |
| `frontend/app/composables/useI18n.ts` | Claves ES/EN `confirm.lineupWithdraw.title`, `.message` (con `{teams}`) y `.action`. | RNF-004 |
| `frontend/e2e/lineup-publication.spec.ts` (nuevo) | Contratos ficticios, como `formations-by-format.spec.ts`. | RF-003, RNF-004 |
| `README.md`, `AGENTS.md`, `docs/manual-usuario.md`, `MEMORY.md` | Comportamiento al guardar con formaciones publicadas. | — |

## 3. Algoritmo

```
firma(equipo) = json(formación del equipo o null,
                     ordenar([(player_id, rol, posición) de sus jugadores]))

guardar(segmento, petición):
    bloquear partido                       # sin cambios
    validar como hoy                       # RF-005, RF-007
    antes   = formaciones del segmento con is_public y published_at
    f_antes = firma por equipo del estado guardado
    f_desp  = firma por equipo de la petición
    retirados = [e en antes si e.is_public y f_antes[e] != f_desp.get(e)]
    borrar y recrear como hoy, con
        is_public, published_at = antes[e] si e no está en retirados y e sigue con formación
                                  FALSE, NULL en otro caso
    auditar SAVE_MATCH_LINEUP si cambia la firma completa      # sin cambios
    por cada e en retirados: auditar UNPUBLISH_MATCH_LINEUP    # RF-004
```

El frontend usa la misma `firma`, con `is_starter` de `tactical_lineups` como rol guardado.

## 4. Interfaz

| Operación | Antes | Después |
|---|---|---|
| `PUT /matches/{id}/lineup` con un equipo publicado sin cambios | queda privado | sigue publicado con su `published_at` |
| `PUT` que cambia un equipo publicado | queda privado, sin auditoría de despublicación | queda privado y se registra `UNPUBLISH_MATCH_LINEUP` |
| `PUT` que solo cambia minutos | queda privado | sigue publicado; sigue habiendo `SAVE_MATCH_LINEUP` |
| Guardar en el Workspace retirando alguna publicación | sin aviso | confirmación con los equipos afectados; cancelar no envía nada |
| Respuesta del `PUT`, lectura pública, publicación | — | sin cambios |

## 5. Decisiones

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Conservar `is_public`/`published_at` al recrear la fila | Cambiar a `UPDATE`/`UPSERT` por equipo | Es el cambio mínimo y conserva el borrado y recreado que ya prueban la 021, la 028 y la 044. |
| La entrada de guardado sigue incluyendo los minutos | Que también ignore los minutos | DA-2 define el cambio que afecta a la publicación. La auditoría de guardado ya registraba cualquier cambio y la spec no la cambia. |
| Despublicación por guardado con el mismo payload que la explícita | Añadir un campo `reason` | El catálogo de la 041 solo muestra `is_public`, y la entrada `SAVE_MATCH_LINEUP` contigua da el contexto. Así no hay campos nuevos. |
| Confirmación calculada en el cliente con el estado cargado | Ensayo previo en el servidor (*dry run*) | No añade endpoints. RF-008 deja al servidor la decisión final. |

## 6. Estrategia de pruebas

| Nivel | Prueba | RF / caso |
|---|---|---|
| Unidad backend | `test_match_operation_audit.py`: `team_publication_signatures` ignora el orden y los minutos y cambia con la formación, el rol, la posición y quién está convocado; `withdrawn_publications` solo devuelve equipos publicados que cambian o desaparecen. | RF-001, RF-002, CL 6, 9, 10 |
| BD opt-in | `test_lineup_publication_preservation.py` (nuevo), en 11v11 y 7v7. Casos 1–5, 9 y 10: rival conservado con el mismo `published_at`; equipo cambiado privado; planilla clásica retira los dos; entradas `UNPUBLISH_MATCH_LINEUP` exactas; sin entrada de despublicación si no hay retirada. Caso 7: 409 sin cambios. Otra organización: 404 sin escritura. La proyección pública sigue mostrando al rival. | RF-001–RF-008, CL 1–10 |
| BD opt-in | Concurrencia: con el partido bloqueado por un guardado, una publicación espera y después ve el estado final; el resultado cumple las reglas de publicación. | RNF-003, CL 8 |
| Unidad frontend | `lineup-publication.test.ts`: `withdrawnPublicTeams` con los mismos casos. `match-lineup-hydration.test.ts`: confirmación con los nombres, cancelar no llama a la API, sin retirada no pregunta. Paridad ES/EN. | RF-003, RNF-004 |
| E2E | `e2e/lineup-publication.spec.ts`: con teclado, el diálogo nombra al equipo; cancelar no envía el `PUT`; confirmar lo envía; axe sin violaciones con el diálogo abierto en ambos temas, a 1440 y 390 px. | RF-003, RNF-004 |

## 7. Verificación de la constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| §2.1–2.2 RLS, sin `BYPASSRLS` | Sí | Mismas consultas con `set_rls_context`; prueba de otra organización. |
| §2.3 Lo publicado es inmutable | Sí | No se edita ninguna versión publicada ni acta cerrada; la planilla solo cambia en el segmento activo sin eventos, como hoy. |
| §2.4 Esquema append-only | No | Sin migraciones. |
| §2.5 Proyección pública mínima | Sí | Sin campos nuevos; una formación solo es pública si se publicó explícitamente y no ha cambiado. |
| §3.2 Backend | Sí | Funciones puras en `audit.py`, sin reloj (las fechas se copian, no se calculan). |
| §3.3 Frontend con `useApi` | Sí | Sin llamadas nuevas; `saveLineup` sigue usando `request`. |
| §4 Documentación y pruebas | Sí | Ver §6; README, AGENTS, manual y MEMORY en T4. |
| §4 Backend: `pytest -q`, `compileall` | Sí | En T2 y T4. |
| §4 Frontend: test, typecheck, build | Sí | En T3 y T4. |
| §5.2 Enmienda | No | No se toca ningún principio. |

## 8. Riesgos

- **Estado del Workspace desfasado:** si otra persona publicó o cambió algo después de cargar la operación, la confirmación puede no coincidir con lo que pasa. El servidor decide (RF-008) y la auditoría lo registra; al terminar, `refreshOperation()` muestra el estado real.
